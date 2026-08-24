from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from did.domain.read_model import GuildSnapshot
from did.infrastructure.planning_repository import PlanningRepository
from did.infrastructure.stage04_repository import Stage04Repository
from did.permissions import DEFAULT_PERMISSION_REGISTRY
from did.planning.canonical import canonical_hash
from did.planning.compiler import PlanCompiler
from did.planning.dag import topological_order
from did.planning.models import (
    DesiredNode,
    DesiredStateGraph,
    NodePresence,
    PlanOperation,
    PlanState,
    ReferenceKind,
    ResourceReference,
    ResourceType,
    RiskLevel,
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
    ) -> tuple[dict[str, Any], bool]:
        guild, _ = await self._read_models.guild_snapshot(graph.guild_id, actor_user_id)
        operations = self._ordered(self._compiler.compile(guild, graph))
        impact = self._impact(operations)
        risk = self._risk.assess(operations, impact)
        snapshot = self.snapshot_payload(guild)
        structure_version = self.structure_version(guild)
        structure_hash = canonical_hash(snapshot)
        plan_hash = canonical_hash(
            {
                "schema": graph.schema_version,
                "compiler": self._compiler.version,
                "capability_version": DEFAULT_PERMISSION_REGISTRY.version,
                "base_structure_version": structure_version,
                "base_structure_hash": structure_hash,
                "desired_graph_hash": canonical_hash(graph),
                "operations": operations,
            }
        )
        return await self._repository.create_plan(
            plan_id=uuid4(),
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
    ) -> tuple[dict[str, Any], PreflightResult]:
        plan = await self._repository.get_plan(guild_id, plan_id)
        if str(plan["status"]) != PlanState.DRAFT.value:
            raise ValueError("only DRAFT plans can be validated")
        result = await self.recheck(guild_id=guild_id, plan_id=plan_id)
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

    async def recheck(self, *, guild_id: int, plan_id: UUID) -> PreflightResult:
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
        impact = self._impact(operations)
        risk = self._risk.assess(operations, impact)
        return self._preflight.check(
            graph=graph,
            operations=operations,
            context=PreflightContext(
                guild=guild,
                bot=bot,
                installation_active=installation_status == "ACTIVE",
                actor_authorization_fresh=True,
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

    @staticmethod
    def _impact(operations: tuple[PlanOperation, ...]) -> ImpactSummary:
        return ImpactSummary(
            affected_resources=len({operation.resource_ref for operation in operations}),
            incomplete_or_unknown=any(
                operation.resource_type is ResourceType.OVERWRITE for operation in operations
            ),
        )

    @staticmethod
    def _ordered(operations: tuple[PlanOperation, ...]) -> tuple[PlanOperation, ...]:
        by_id = {operation.operation_id: operation for operation in operations}
        return tuple(by_id[operation_id] for operation_id in topological_order(operations))

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
                predecessors=tuple(UUID(str(value)) for value in row["predecessors"]),
                produces_symbol=row["produces_symbol"],
                consumes_symbols=tuple(row["consumes_symbols"]),
            )
            for row in rows
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
