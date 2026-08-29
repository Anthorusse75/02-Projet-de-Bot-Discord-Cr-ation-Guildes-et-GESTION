from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from did.domain.read_model import GuildSnapshot, OverwriteSnapshot
from did.infrastructure.planning_repository import PlanningRepository
from did.infrastructure.stage04_repository import Stage04Repository
from did.permissions import DEFAULT_PERMISSION_REGISTRY, PermissionEvaluator
from did.planning.canonical import canonical_hash
from did.planning.compiler import PlanCompiler
from did.planning.dag import topological_order
from did.planning.models import (
    DesiredNode,
    DesiredStateGraph,
    NodePresence,
    OperationType,
    PlanOperation,
    PlanState,
    ReferenceKind,
    ResourceReference,
    ResourceType,
    RiskLevel,
    thaw_json_object,
)
from did.planning.preflight import PreflightContext, PreflightEngine, PreflightResult
from did.planning.risk import ImpactSummary, RiskEngine


class PlanningService:
    """Pure compile/preflight orchestration over cache-first tenant repositories."""

    def __init__(
        self,
        repository: PlanningRepository,
        read_models: Stage04Repository,
        *,
        confirmation_ttl_seconds: int = 600,
    ) -> None:
        self._repository = repository
        self._read_models = read_models
        self._compiler = PlanCompiler()
        self._risk = RiskEngine()
        self._preflight = PreflightEngine()
        self._confirmation_ttl = confirmation_ttl_seconds

    async def create(
        self,
        *,
        graph: DesiredStateGraph,
        actor_user_id: int,
        idempotency_key: str,
        correlation_id: UUID,
        operation_order_policy: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        guild, _ = await self._read_models.guild_snapshot(graph.guild_id, actor_user_id)
        plan_id = uuid4()
        compiled = self._compiler.compile(guild, graph, plan_id=plan_id)
        if operation_order_policy is not None:
            if operation_order_policy != "STAGE08_STRUCTURAL":
                raise ValueError("unsupported operation order policy")
            compiled = self._stage08_structural_order(compiled)
        operations = self._ordered(compiled)
        impact = await self._impact(guild, operations)
        risk = self._risk.assess(operations, impact)
        snapshot = self.snapshot_payload(guild)
        structure_version = self.structure_version(guild)
        structure_hash = canonical_hash(snapshot)
        plan_hash = self._plan_hash(
            graph=graph,
            operations=operations,
            snapshot=snapshot,
            snapshot_schema_version="did-guild-snapshot-v1",
            compiler_version=self._compiler.version,
            capability_version=DEFAULT_PERMISSION_REGISTRY.version,
            base_structure_version=structure_version,
            base_structure_hash=structure_hash,
            symbols=self._symbol_definitions(operations),
        )
        return await self._repository.create_plan(
            plan_id=plan_id,
            guild_id=graph.guild_id,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            graph=graph,
            operations=operations,
            before_snapshot=snapshot,
            base_structure_version=structure_version,
            base_structure_hash=structure_hash,
            capability_version=DEFAULT_PERMISSION_REGISTRY.version,
            plan_hash=plan_hash,
            risk=risk,
            compiler_version=self._compiler.version,
            correlation_id=correlation_id,
        )

    async def validate(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        actor_user_id: int,
        expected_version: int,
        correlation_id: UUID,
        actor_authorization_fresh: bool,
    ) -> tuple[dict[str, Any], PreflightResult]:
        plan = await self._repository.get_plan(guild_id, plan_id)
        if str(plan["status"]) != PlanState.DRAFT.value:
            raise ValueError("only DRAFT plans can be validated")
        await self._assert_persisted_integrity(guild_id, plan_id)
        result = await self.recheck(
            guild_id=guild_id,
            plan_id=plan_id,
            actor_authorization_fresh=actor_authorization_fresh,
        )
        if not result.allowed:
            if "preflight.structure_stale" in result.errors:
                plan = await self._repository.transition_plan(
                    guild_id=guild_id,
                    plan_id=plan_id,
                    actor_user_id=actor_user_id,
                    expected=PlanState.DRAFT,
                    target=PlanState.STALE,
                    expected_version=expected_version,
                    correlation_id=correlation_id,
                )
            return plan, result
        updated = await self._repository.transition_plan(
            guild_id=guild_id,
            plan_id=plan_id,
            actor_user_id=actor_user_id,
            expected=PlanState.DRAFT,
            target=PlanState.VALIDATED,
            expected_version=expected_version,
            correlation_id=correlation_id,
        )
        return updated, result

    async def recheck(
        self, *, guild_id: int, plan_id: UUID, actor_authorization_fresh: bool
    ) -> PreflightResult:
        """Re-evaluate mutable Discord facts without changing plan state.

        The worker calls this after fencing the APPLYING transition and before
        selecting an operation, so a queued plan cannot mutate Discord using a
        stale structure or capability decision.
        """
        plan = await self._repository.get_plan(guild_id, plan_id)
        bot_id, installation_status = await self._read_models.bot_identity(guild_id)
        if bot_id is None:
            return PreflightResult(False, ("preflight.bot_identity_unavailable",))
        guild, bot = await self._read_models.guild_snapshot(guild_id, bot_id)
        operations = self._operations_from_rows(
            await self._repository.operations(guild_id, plan_id)
        )
        graph = graph_from_json(dict(plan["desired_graph"]))
        impact = await self._impact(guild, operations)
        risk = self._risk.assess(operations, impact)
        return self._preflight.check(
            graph=graph,
            operations=operations,
            context=PreflightContext(
                guild=guild,
                bot=bot,
                installation_active=installation_status == "ACTIVE",
                actor_authorization_fresh=actor_authorization_fresh,
                base_structure_version=str(plan["base_structure_version"]),
                current_structure_version=self.structure_version(guild),
                capability_version=str(plan["capability_version"]),
            ),
            risk=risk,
        )

    async def confirm(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        actor_user_id: int,
        idempotency_key: str,
        expected_version: int,
        supplied_plan_hash: str,
        reinforced_acknowledgement: bool,
        correlation_id: UUID,
    ) -> dict[str, Any]:
        plan = await self._repository.get_plan(guild_id, plan_id)
        if supplied_plan_hash != str(plan["plan_hash"]):
            raise ValueError("confirmation hash does not match the immutable plan")
        if bool(plan["confirmation_required"]) and not reinforced_acknowledgement:
            raise ValueError("reinforced confirmation is required")
        return await self._repository.confirm(
            guild_id=guild_id,
            plan_id=plan_id,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
            plan_hash=supplied_plan_hash,
            risk_level=RiskLevel(str(plan["risk_level"])),
            expires_at=datetime.now(UTC) + timedelta(seconds=self._confirmation_ttl),
            expected_version=expected_version,
            correlation_id=correlation_id,
        )

    async def apply(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        actor_user_id: int,
        correlation_id: UUID,
    ) -> UUID:
        return await self._repository.enqueue_apply(
            guild_id=guild_id,
            plan_id=plan_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )

    @staticmethod
    def structure_version(guild: GuildSnapshot) -> str:
        return "|".join(guild.source_versions)

    @staticmethod
    def snapshot_payload(guild: GuildSnapshot) -> dict[str, Any]:
        return {
            "schema_version": "did-guild-snapshot-v1",
            "guild_id": str(guild.guild_id),
            "owner_id": str(guild.owner_id),
            "source_versions": list(guild.source_versions),
            "coverage": {
                "mode": guild.coverage.mode.value,
                "freshness": guild.coverage.freshness.value,
                "state_version": guild.coverage.state_version,
                "channels_complete": guild.channels_complete,
                "roles_complete": guild.roles_complete,
            },
            "roles": [
                {
                    "id": str(role.role_id),
                    "name": role.name,
                    "position": role.position,
                    "permissions": str(role.permissions),
                    "managed": role.managed,
                    "color": role.color,
                    "hoist": role.hoist,
                    "mentionable": role.mentionable,
                }
                for role in sorted(guild.roles, key=lambda item: item.role_id)
            ],
            "channels": [
                {
                    "id": str(channel.channel_id),
                    "type": int(channel.channel_type),
                    "name": channel.name,
                    "position": channel.position,
                    "parent_id": str(channel.parent_id) if channel.parent_id else None,
                    "topic": channel.topic,
                    "nsfw": channel.nsfw,
                    "flags": channel.flags,
                    "observability": channel.observability.value,
                    "overwrites": [
                        {
                            "target_id": str(overwrite.target_id),
                            "target_type": overwrite.target_type,
                            "allow": str(overwrite.allow),
                            "deny": str(overwrite.deny),
                        }
                        for overwrite in channel.overwrites
                    ],
                }
                for channel in sorted(guild.channels, key=lambda item: item.channel_id)
            ],
        }

    async def _impact(
        self, guild: GuildSnapshot, operations: tuple[PlanOperation, ...]
    ) -> ImpactSummary:
        subjects = await self._read_models.cached_member_snapshots(guild.guild_id)
        after = guild
        after_subjects = list(subjects)
        affected_resources = {operation.resource_ref for operation in operations}
        permission_sensitive = False
        for operation in operations:
            payload = thaw_json_object(operation.desired_payload)
            operation_type = operation.operation_type
            permission_sensitive |= operation_type in {
                OperationType.UPDATE_ROLE,
                OperationType.DELETE_ROLE,
                OperationType.UPSERT_OVERWRITE,
                OperationType.DELETE_OVERWRITE,
                OperationType.DELETE_CHANNEL,
            }
            if operation_type is OperationType.UPDATE_ROLE and payload.get("id") is not None:
                role_id = int(payload["id"])
                after = replace(
                    after,
                    roles=tuple(
                        replace(
                            role,
                            permissions=int(payload.get("permissions", role.permissions)),
                            name=str(payload.get("name", role.name)),
                            color=int(payload.get("color", role.color)),
                            hoist=bool(payload.get("hoist", role.hoist)),
                            mentionable=bool(payload.get("mentionable", role.mentionable)),
                        )
                        if role.role_id == role_id
                        else role
                        for role in after.roles
                    ),
                )
            elif operation_type is OperationType.DELETE_ROLE and payload.get("id") is not None:
                role_id = int(payload["id"])
                after = replace(
                    after,
                    roles=tuple(role for role in after.roles if role.role_id != role_id),
                )
                after_subjects = [
                    replace(
                        subject,
                        role_ids=tuple(value for value in subject.role_ids if value != role_id),
                    )
                    for subject in after_subjects
                ]
            elif operation_type in {
                OperationType.UPSERT_OVERWRITE,
                OperationType.DELETE_OVERWRITE,
            }:
                channel_id = payload.get("channel_id")
                target_id = payload.get("subject_id") or payload.get("target_id")
                if channel_id is None or target_id is None:
                    continue
                target_type = int(payload.get("target_type", 0))
                channels = []
                for channel in after.channels:
                    if channel.channel_id != int(channel_id):
                        channels.append(channel)
                        continue
                    overwrites = tuple(
                        item
                        for item in channel.overwrites
                        if not (
                            item.target_id == int(target_id) and item.target_type == target_type
                        )
                    )
                    if operation_type is OperationType.UPSERT_OVERWRITE:
                        overwrites += (
                            OverwriteSnapshot(
                                guild.guild_id,
                                int(channel_id),
                                int(target_id),
                                target_type,
                                int(payload.get("allow", 0)),
                                int(payload.get("deny", 0)),
                            ),
                        )
                    channels.append(
                        replace(
                            channel,
                            overwrites=tuple(
                                sorted(
                                    overwrites,
                                    key=lambda item: (item.target_type, item.target_id),
                                )
                            ),
                            overwrites_complete=True,
                        )
                    )
                after = replace(after, channels=tuple(channels))
            elif operation_type is OperationType.DELETE_CHANNEL and payload.get("id") is not None:
                channel_id = int(payload["id"])
                target = after.channel(channel_id)
                if target is not None and int(target.channel_type) == 4:
                    affected_resources.update(
                        f"channel:{channel.channel_id}"
                        for channel in after.channels
                        if channel.parent_id == channel_id
                    )
                after = replace(
                    after,
                    channels=tuple(
                        channel for channel in after.channels if channel.channel_id != channel_id
                    ),
                )

        evaluator = PermissionEvaluator()
        affected_subject_ids: set[int] = set()
        additions = removals = visibility_losses = administrator_grants = 0
        incomplete = permission_sensitive and not guild.coverage.members_complete
        after_by_id = {subject.user_id: subject for subject in after_subjects}
        view_bit = DEFAULT_PERMISSION_REGISTRY.value("VIEW_CHANNEL")
        admin_bit = DEFAULT_PERMISSION_REGISTRY.value("ADMINISTRATOR")
        for subject in subjects:
            after_subject = after_by_id[subject.user_id]
            before_guild = evaluator.evaluate(guild=guild, member=subject)
            after_guild = evaluator.evaluate(guild=after, member=after_subject)
            guild_added = after_guild.effective_bits & ~before_guild.effective_bits
            guild_removed = before_guild.effective_bits & ~after_guild.effective_bits
            if guild_added or guild_removed:
                affected_subject_ids.add(subject.user_id)
                additions += guild_added.bit_count()
                removals += guild_removed.bit_count()
            if guild_added & admin_bit:
                administrator_grants += 1
            if before_guild.status.value != "COMPLETE" or after_guild.status.value != "COMPLETE":
                incomplete = True
            for before_channel in guild.channels:
                before_decision = evaluator.evaluate(
                    guild=guild, member=subject, resource=before_channel
                )
                after_channel = after.channel(before_channel.channel_id)
                if after_channel is None:
                    if before_decision.effective_bits:
                        affected_subject_ids.add(subject.user_id)
                        removals += before_decision.effective_bits.bit_count()
                    if before_decision.effective_bits & view_bit:
                        visibility_losses += 1
                    incomplete |= before_decision.status.value != "COMPLETE"
                    continue
                after_decision = evaluator.evaluate(
                    guild=after, member=after_subject, resource=after_channel
                )
                added = after_decision.effective_bits & ~before_decision.effective_bits
                removed = before_decision.effective_bits & ~after_decision.effective_bits
                if added or removed:
                    affected_subject_ids.add(subject.user_id)
                    additions += added.bit_count()
                    removals += removed.bit_count()
                if before_decision.effective_bits & view_bit and not (
                    after_decision.effective_bits & view_bit
                ):
                    visibility_losses += 1
                if (
                    before_decision.status.value != "COMPLETE"
                    or after_decision.status.value != "COMPLETE"
                ):
                    incomplete = True
        return ImpactSummary(
            affected_resources=len(affected_resources),
            affected_subjects=len(affected_subject_ids),
            permission_additions=additions,
            permission_removals=removals,
            visibility_losses=visibility_losses,
            administrator_grants=administrator_grants,
            incomplete_or_unknown=incomplete,
        )

    @staticmethod
    def _ordered(operations: tuple[PlanOperation, ...]) -> tuple[PlanOperation, ...]:
        by_id = {operation.operation_id: operation for operation in operations}
        return tuple(by_id[operation_id] for operation_id in topological_order(operations))

    @classmethod
    def _stage08_structural_order(
        cls, operations: tuple[PlanOperation, ...]
    ) -> tuple[PlanOperation, ...]:
        """Serialize STAGE 08 structural phases without changing worker semantics."""
        forward = {
            ResourceType.GUILD: -1,
            ResourceType.CATEGORY: 0,
            ResourceType.CHANNEL: 1,
            ResourceType.ROLE: 2,
            ResourceType.OVERWRITE: 3,
        }
        delete_types = {
            OperationType.DELETE_OVERWRITE,
            OperationType.DELETE_ROLE,
            OperationType.DELETE_CHANNEL,
        }
        base_order = cls._ordered(operations)

        def phase(operation: PlanOperation) -> tuple[int, int]:
            index = forward[operation.resource_type]
            if operation.operation_type in delete_types:
                return (1, -index)
            return (0, index)

        sequenced = sorted(enumerate(base_order), key=lambda item: (phase(item[1]), item[0]))
        result: list[PlanOperation] = []
        previous: UUID | None = None
        for _, operation in sequenced:
            predecessors = set(operation.predecessors)
            if previous is not None:
                predecessors.add(previous)
            operation = replace(operation, predecessors=tuple(sorted(predecessors, key=str)))
            result.append(operation)
            previous = operation.operation_id
        materialized = tuple(result)
        topological_order(materialized)
        return materialized

    @staticmethod
    def _operations_from_rows(rows: list[dict[str, Any]]) -> tuple[PlanOperation, ...]:
        from did.planning.models import (  # local import keeps the API surface compact
            CompensationClass,
            OperationType,
            RecoveryStrategy,
            VerificationStrategy,
            freeze_json_object,
        )

        return tuple(
            PlanOperation(
                UUID(str(row["id"])),
                OperationType(str(row["operation_type"])),
                ResourceType(str(row["resource_type"])),
                str(row["resource_ref"]),
                freeze_json_object(dict(row["desired_payload"])),
                freeze_json_object(dict(row["before_payload"])),
                tuple(row["required_capabilities"]),
                CompensationClass(str(row["compensation_class"])),
                RiskLevel(str(row["risk_level"])),
                VerificationStrategy(str(row["verification_strategy"])),
                RecoveryStrategy(str(row["recovery_strategy"])),
                tuple(row["expected_gateway_events"]),
                preconditions=freeze_json_object(dict(row["preconditions"])),
                predecessors=tuple(UUID(str(value)) for value in row["predecessors"]),
                produces_symbol=row["produces_symbol"],
                consumes_symbols=tuple(row["consumes_symbols"]),
            )
            for row in rows
        )

    async def _assert_persisted_integrity(self, guild_id: int, plan_id: UUID) -> None:
        bundle = await self._repository.integrity_bundle(guild_id, plan_id)
        plan = bundle["plan"]
        graph = graph_from_json(dict(plan["desired_graph"]))
        if canonical_hash(graph) != str(plan["desired_graph_hash"]):
            raise ValueError("persisted desired graph hash mismatch")
        operations = self._operations_from_rows(bundle["operations"])
        for row, operation in zip(bundle["operations"], operations, strict=True):
            if canonical_hash(operation) != str(row["immutable_hash"]):
                raise ValueError("persisted operation immutable hash mismatch")
        snapshot = bundle["snapshot"]
        snapshot_payload = dict(snapshot["payload"])
        if canonical_hash(snapshot_payload) != str(snapshot["snapshot_hash"]):
            raise ValueError("persisted before snapshot hash mismatch")
        if str(snapshot["structure_version"]) != str(plan["base_structure_version"]):
            raise ValueError("persisted before snapshot version mismatch")
        if str(snapshot["snapshot_hash"]) != str(plan["base_structure_hash"]):
            raise ValueError("persisted before snapshot reference hash mismatch")
        calculated = self._plan_hash(
            graph=graph,
            operations=operations,
            snapshot=snapshot_payload,
            snapshot_schema_version=str(snapshot["schema_version"]),
            compiler_version=str(plan["compiler_version"]),
            capability_version=str(plan["capability_version"]),
            base_structure_version=str(snapshot["structure_version"]),
            base_structure_hash=str(snapshot["snapshot_hash"]),
            symbols=tuple(bundle["symbols"]),
        )
        if calculated != str(plan["plan_hash"]):
            raise ValueError("persisted plan hash mismatch")

    @staticmethod
    def _symbol_definitions(operations: tuple[PlanOperation, ...]) -> tuple[dict[str, str], ...]:
        return tuple(
            sorted(
                (
                    {
                        "symbol": str(operation.produces_symbol),
                        "resource_type": operation.resource_type.value,
                        "producer_operation_id": str(operation.operation_id),
                    }
                    for operation in operations
                    if operation.produces_symbol is not None
                ),
                key=lambda item: item["symbol"],
            )
        )

    @staticmethod
    def _plan_hash(
        *,
        graph: DesiredStateGraph,
        operations: tuple[PlanOperation, ...],
        snapshot: dict[str, Any],
        snapshot_schema_version: str,
        compiler_version: str,
        capability_version: str,
        base_structure_version: str,
        base_structure_hash: str,
        symbols: tuple[dict[str, str], ...],
    ) -> str:
        dependencies = tuple(
            {
                "operation_id": str(operation.operation_id),
                "predecessor_operation_id": str(predecessor),
            }
            for operation in operations
            for predecessor in operation.predecessors
        )
        return canonical_hash(
            {
                "desired_graph": graph,
                "desired_graph_hash": canonical_hash(graph),
                "compiler_version": compiler_version,
                "capability_version": capability_version,
                "before_snapshot": {
                    "schema_version": snapshot_schema_version,
                    "structure_version": base_structure_version,
                    "snapshot_hash": base_structure_hash,
                    "payload": snapshot,
                },
                "operations": operations,
                "dependencies": dependencies,
                "symbols": symbols,
            }
        )


def graph_from_json(value: dict[str, Any]) -> DesiredStateGraph:
    nodes = []
    for item in value.get("nodes", []):
        relations = {
            str(relation["name"]): ResourceReference(
                ReferenceKind(str(relation["kind"])), str(relation["value"])
            )
            for relation in item.get("relations", [])
        }
        discord_id = item.get("discord_id")
        nodes.append(
            DesiredNode.build(
                logical_key=str(item["logical_key"]),
                resource_type=ResourceType(str(item["resource_type"])),
                properties=dict(item.get("properties", {})),
                discord_id=int(discord_id) if discord_id is not None else None,
                symbol=item.get("symbol"),
                presence=NodePresence(str(item.get("presence", "PRESENT"))),
                relations=relations,
            )
        )
    return DesiredStateGraph(
        guild_id=int(value["guild_id"]),
        nodes=tuple(nodes),
        schema_version=str(value.get("schema_version", "did-dsg-v1")),
    )
