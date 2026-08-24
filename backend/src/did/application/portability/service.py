from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from time import perf_counter
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from did.application.planning import PlanningService
from did.cloning import (
    ArtifactSelection,
    DestinationPlanCompiler,
    PortableArtifactBuilder,
    ReconcileScope,
)
from did.infrastructure.planning_repository import PlanningRepository
from did.infrastructure.portability_repository import PortabilityRepository
from did.infrastructure.runtime_metrics import RuntimeMetrics
from did.infrastructure.stage04_repository import Stage04Repository
from did.portability import (
    CloneMode,
    DependencyGraph,
    DestinationCandidate,
    ExplicitMapping,
    MappingDecision,
    MappingResolver,
    PortableResourceType,
    TransferState,
    artifact_from_bytes,
    artifact_to_bytes,
)


class ArtifactKind(StrEnum):
    CLIPBOARD = "CLIPBOARD"
    LIBRARY = "LIBRARY"
    EXPORT_BUNDLE = "EXPORT_BUNDLE"
    FILE_IMPORT = "FILE_IMPORT"


class MappingRequired(ValueError):
    def __init__(self, resolutions: tuple[object, ...]) -> None:
        self.resolutions = resolutions
        super().__init__("portable mapping requires explicit intervention")


class PortabilityService:
    def __init__(
        self,
        repository: PortabilityRepository,
        read_models: Stage04Repository,
        planning: PlanningService,
        planning_repository: PlanningRepository,
        *,
        clipboard_ttl_seconds: int = 3_600,
        export_ttl_seconds: int = 2_592_000,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        self.repository = repository
        self._read_models = read_models
        self._planning = planning
        self._planning_repository = planning_repository
        self._builder = PortableArtifactBuilder()
        self._resolver = MappingResolver()
        self._compiler = DestinationPlanCompiler()
        self._clipboard_ttl = clipboard_ttl_seconds
        self._export_ttl = export_ttl_seconds
        self._metrics = metrics

    async def export_live(
        self,
        *,
        source_guild_id: int,
        actor_user_id: int,
        selection: ArtifactSelection,
        kind: ArtifactKind,
        name: str | None,
        idempotency_key: str,
        correlation_id: UUID,
        logical_group_id: UUID | None = None,
    ) -> tuple[dict[str, Any], bool]:
        guild, _ = await self._read_models.guild_snapshot(source_guild_id, actor_user_id)
        started = perf_counter()
        if logical_group_id is None:
            artifact = self._builder.build_live(guild, selection)
        else:
            groups = await self._read_models.list_logical_groups(source_guild_id)
            group = next((item for item in groups if item["id"] == logical_group_id), None)
            if group is None:
                raise ValueError("logical group is unavailable")
            artifact = self._builder.build_live_logical_group(guild, group)
        if self._metrics is not None:
            self._metrics.artifact_built(perf_counter() - started, len(artifact_to_bytes(artifact)))
        expires_at = self._expiry(kind)
        metadata, created = await self.repository.create_artifact(
            owner_user_id=actor_user_id,
            kind=kind.value,
            artifact=artifact,
            name=name,
            expires_at=expires_at,
            idempotency_operation="LIVE_EXPORT",
            idempotency_key=self._export_idempotency_key(
                source_guild_id, selection, kind, logical_group_id, idempotency_key
            ),
        )
        if created:
            await self.repository.audit_boundary(
                guild_id=source_guild_id,
                actor_user_id=actor_user_id,
                transfer_id=UUID(str(metadata["id"])),
                event_type="PORTABLE_ARTIFACT_EXPORTED",
                artifact_hash=artifact.content_hash,
                correlation_id=correlation_id,
                target_type="ARTIFACT",
            )
        return metadata, created

    async def import_file(
        self,
        *,
        actor_user_id: int,
        raw: bytes,
        name: str | None,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        try:
            artifact = artifact_from_bytes(raw)
        except ValueError:
            if self._metrics is not None:
                self._metrics.portability_outcome("artifact_import", "rejected")
            raise
        if self._metrics is not None:
            self._metrics.portability_outcome("artifact_import", "success")
        return await self.repository.create_artifact(
            owner_user_id=actor_user_id,
            kind=ArtifactKind.FILE_IMPORT.value,
            artifact=artifact,
            name=name,
            expires_at=datetime.now(UTC) + timedelta(seconds=self._export_ttl),
            idempotency_operation="FILE_IMPORT",
            idempotency_key=(
                "file-import:" + hashlib.sha256(raw + idempotency_key.encode("utf-8")).hexdigest()
            ),
        )

    async def export_file(self, actor_user_id: int, artifact_id: UUID) -> bytes:
        _, artifact = await self.repository.get_artifact(actor_user_id, artifact_id)
        return artifact_to_bytes(artifact)

    async def compile_stored(
        self,
        *,
        actor_user_id: int,
        artifact_id: UUID,
        destination_guild_id: int,
        mode: CloneMode,
        explicit_mappings: tuple[ExplicitMapping, ...],
        idempotency_key: str,
        correlation_id: UUID,
        reconcile_scope: ReconcileScope | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        metadata, artifact = await self.repository.get_artifact(actor_user_id, artifact_id)
        destination, _ = await self._read_models.guild_snapshot(destination_guild_id, actor_user_id)
        candidates = self._destination_candidates(destination)
        graph = DependencyGraph.build(artifact)
        resolutions = self._resolver.resolve(
            graph,
            destination_guild_id=destination_guild_id,
            mode=mode,
            candidates=candidates,
            explicit=explicit_mappings,
        )
        if self._metrics is not None:
            self._metrics.portability_outcome("clone_mode", mode.value)
            for item in resolutions:
                self._metrics.portability_outcome("mapping", item.decision.value)
                if item.decision is MappingDecision.MANUAL and item.candidate_refs:
                    self._metrics.mapping_ambiguities += 1
        unresolved = tuple(
            item
            for item in resolutions
            if item.decision in {MappingDecision.MANUAL, MappingDecision.UNSUPPORTED}
        )
        if unresolved and mode is not CloneMode.MAXIMUM_COMPATIBLE:
            raise MappingRequired(unresolved)
        compilation = self._compiler.compile(
            artifact,
            destination_guild_id=destination_guild_id,
            mode=mode,
            resolutions=resolutions,
            candidates=candidates,
            reconcile_scope=reconcile_scope,
        )
        transfer_id = uuid4()
        mapping_json = [
            self._resolution_json(item, actor_user_id=actor_user_id) for item in resolutions
        ]
        transfer_key = self._transfer_idempotency_key(
            artifact_id, destination_guild_id, mode, mapping_json, idempotency_key
        )
        transfer, transfer_created = await self.repository.create_transfer(
            transfer_id=transfer_id,
            actor_user_id=actor_user_id,
            source_guild_id=metadata["source_guild_id"],
            destination_guild_id=destination_guild_id,
            artifact_id=artifact_id,
            artifact_content_hash=artifact.content_hash,
            mode=mode.value,
            mapping=mapping_json,
            status=TransferState.READY.value,
            correlation_id=correlation_id,
            idempotency_key=transfer_key,
        )
        if self._metrics is not None:
            self._metrics.portability_outcome("transfer_state", TransferState.READY.value)
        transfer_id = UUID(str(transfer["id"]))
        planning_key = self._planning_idempotency_key(
            artifact_id, destination_guild_id, mode, mapping_json, idempotency_key
        )
        plan, plan_created = await self._planning.create(
            graph=compilation.graph,
            actor_user_id=actor_user_id,
            idempotency_key=planning_key,
            correlation_id=correlation_id,
        )
        if self._metrics is not None:
            self._metrics.portability_outcome(
                "destination_plan_compile", "created" if plan_created else "reused"
            )
        report_json = [self._report_json(item) for item in compilation.report.entries]
        if self._metrics is not None:
            for report_entry in compilation.report.entries:
                self._metrics.portability_outcome("clone_report", report_entry.outcome.value)
            self._metrics.portability_outcome("transfer_state", TransferState.COMPILED.value)
        transfer = await self.repository.compile_transfer(
            actor_user_id=actor_user_id,
            transfer_id=transfer_id,
            destination_plan_id=UUID(str(plan["id"])),
            report=report_json,
        )
        if transfer_created or plan_created:
            await self.repository.audit_boundary(
                guild_id=destination_guild_id,
                actor_user_id=actor_user_id,
                transfer_id=transfer_id,
                event_type="PORTABLE_ARTIFACT_COMPILED",
                artifact_hash=artifact.content_hash,
                correlation_id=correlation_id,
                destination_plan_id=UUID(str(plan["id"])),
            )
        return transfer, plan, plan_created

    async def preview_stored(
        self,
        *,
        actor_user_id: int,
        artifact_id: UUID,
        destination_guild_id: int,
        mode: CloneMode,
        explicit_mappings: tuple[ExplicitMapping, ...],
    ) -> list[dict[str, Any]]:
        _, artifact = await self.repository.get_artifact(actor_user_id, artifact_id)
        destination, _ = await self._read_models.guild_snapshot(destination_guild_id, actor_user_id)
        resolutions = self._resolver.resolve(
            DependencyGraph.build(artifact),
            destination_guild_id=destination_guild_id,
            mode=mode,
            candidates=self._destination_candidates(destination),
            explicit=explicit_mappings,
        )
        return [self._resolution_json(item, actor_user_id=actor_user_id) for item in resolutions]

    async def create_template(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        artifact_id: UUID,
        name: str,
        correlation_id: UUID,
    ) -> dict[str, Any]:
        _, artifact = await self.repository.get_artifact(actor_user_id, artifact_id)
        row = await self.repository.create_template(
            guild_id=guild_id,
            actor_user_id=actor_user_id,
            template_id=uuid4(),
            name=name,
            artifact=artifact,
        )
        await self.repository.audit_boundary(
            guild_id=guild_id,
            actor_user_id=actor_user_id,
            transfer_id=UUID(str(row["id"])),
            event_type="PORTABLE_TEMPLATE_CREATED",
            artifact_hash=artifact.content_hash,
            correlation_id=correlation_id,
            target_type="TEMPLATE",
        )
        return row

    async def compile_template(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        template_id: UUID,
        mode: CloneMode,
        explicit_mappings: tuple[ExplicitMapping, ...],
        idempotency_key: str,
        correlation_id: UUID,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        template, artifact = await self.repository.get_template(
            guild_id, actor_user_id, template_id
        )
        stored, _ = await self.repository.create_artifact(
            owner_user_id=actor_user_id,
            kind=ArtifactKind.EXPORT_BUNDLE.value,
            artifact=artifact,
            name=f"template:{template['name']}",
            expires_at=datetime.now(UTC) + timedelta(seconds=self._export_ttl),
            idempotency_operation="TEMPLATE_APPLY",
            idempotency_key=(
                "template-apply:"
                + hashlib.sha256(f"{guild_id}:{template_id}:{idempotency_key}".encode()).hexdigest()
            ),
        )
        return await self.compile_stored(
            actor_user_id=actor_user_id,
            artifact_id=UUID(str(stored["id"])),
            destination_guild_id=guild_id,
            mode=mode,
            explicit_mappings=explicit_mappings,
            idempotency_key=f"template:{template_id}:{idempotency_key}",
            correlation_id=correlation_id,
        )

    async def finalize_transfer(
        self,
        *,
        actor_user_id: int,
        transfer_id: UUID,
        correlation_id: UUID,
    ) -> dict[str, Any]:
        transfer = await self.repository.get_transfer(actor_user_id, transfer_id)
        if transfer.get("local_result_json") is not None:
            return transfer
        destination_guild_id = int(transfer["destination_guild_id"])
        raw_plan_id = transfer.get("destination_plan_id")
        if raw_plan_id is None:
            raise ValueError("destination plan is unavailable")
        plan_id = UUID(str(raw_plan_id))
        plan = await self._planning_repository.get_plan(destination_guild_id, plan_id)
        if str(plan["status"]) != "SUCCEEDED":
            raise ValueError("destination plan must succeed before local finalization")
        _, artifact = await self.repository.get_artifact(
            actor_user_id, UUID(str(transfer["portable_artifact_id"]))
        )
        bindings = {
            str(row["symbol"]): int(row["discord_id"])
            for row in await self._planning_repository.symbol_bindings(
                destination_guild_id, plan_id
            )
            if row["discord_id"] is not None and str(row["status"]) == "BOUND"
        }
        mappings = {
            str(item["source_logical_ref"]): item
            for item in transfer["mapping_json"]
            if isinstance(item, dict)
        }
        resources_by_ref = {item.logical_key: item for item in artifact.resources}
        created_groups: list[dict[str, str]] = []
        created_policies: list[dict[str, str]] = []
        for group in artifact.resources:
            if group.resource_type is not PortableResourceType.LOGICAL_GROUP:
                continue
            group_resources: list[dict[str, Any]] = []
            contained = sorted(
                edge.target
                for edge in artifact.dependencies
                if edge.source == group.logical_key and edge.relation == "contains"
            )
            for logical_ref in contained:
                resource = resources_by_ref[logical_ref]
                if resource.resource_type not in {
                    PortableResourceType.CATEGORY,
                    PortableResourceType.CHANNEL,
                    PortableResourceType.ROLE,
                }:
                    continue
                mapping = mappings[logical_ref]
                destination_ref = mapping.get("destination_ref")
                if mapping["decision"] == MappingDecision.CREATE.value:
                    destination_ref = bindings.get(f"portable:{logical_ref}")
                if destination_ref is None:
                    raise ValueError("logical group destination binding is unresolved")
                group_resources.append(
                    {
                        "resource_type": resource.resource_type.value,
                        "discord_resource_id": int(destination_ref),
                        "semantic_role": "CLONED",
                    }
                )
            attributes = group.attribute_map()
            group_id = uuid5(NAMESPACE_URL, f"did:portable:{transfer_id}:{group.logical_key}")
            await self._read_models.create_logical_group(
                guild_id=destination_guild_id,
                actor_id=actor_user_id,
                name=str(attributes["name"]),
                slug=f"{attributes['slug']}-{str(transfer_id)[:8]}",
                description=(
                    str(attributes["description"])
                    if attributes.get("description") is not None
                    else None
                ),
                metadata={
                    "portable_artifact_hash": artifact.content_hash,
                    "portable_transfer_id": str(transfer_id),
                },
                resources=tuple(group_resources),
                group_id=group_id,
            )
            created_groups.append({"logical_ref": group.logical_key, "id": str(group_id)})
        for policy in artifact.resources:
            if policy.resource_type is not PortableResourceType.POLICY:
                continue
            principal_mappings: list[dict[str, str]] = []
            for edge in artifact.dependencies:
                if edge.source != policy.logical_key or edge.relation != "principal":
                    continue
                mapping = mappings[edge.target]
                destination_ref = mapping.get("destination_ref")
                if (
                    mapping["decision"] != MappingDecision.MAP_EXISTING.value
                    or destination_ref is None
                    or mapping.get("confirmed_by") != str(actor_user_id)
                ):
                    raise ValueError("policy principal mapping is unresolved or unconfirmed")
                principal_mappings.append(
                    {
                        "principal_logical_ref": edge.target,
                        "destination_ref": str(destination_ref),
                        "confirmed_by": str(actor_user_id),
                    }
                )
            attributes = policy.attribute_map()
            policy_id = uuid5(
                NAMESPACE_URL, f"did:portable-policy:{transfer_id}:{policy.logical_key}"
            )
            await self.repository.create_policy_definition(
                guild_id=destination_guild_id,
                actor_user_id=actor_user_id,
                definition_id=policy_id,
                logical_key=policy.logical_key,
                name=str(attributes.get("name", policy.logical_key)),
                definition=attributes,
                principal_mappings=principal_mappings,
                artifact_hash=artifact.content_hash,
            )
            created_policies.append({"logical_ref": policy.logical_key, "id": str(policy_id)})
        result = {
            "logical_groups": created_groups,
            "policy_definitions": created_policies,
        }
        transfer = await self.repository.record_local_result(actor_user_id, transfer_id, result)
        await self.repository.audit_boundary(
            guild_id=destination_guild_id,
            actor_user_id=actor_user_id,
            transfer_id=transfer_id,
            event_type="PORTABLE_LOCAL_RESOURCES_FINALIZED",
            artifact_hash=str(transfer["artifact_content_hash"]),
            correlation_id=correlation_id,
            destination_plan_id=plan_id,
        )
        return transfer

    def _expiry(self, kind: ArtifactKind) -> datetime | None:
        if kind is ArtifactKind.LIBRARY:
            return None
        ttl = self._clipboard_ttl if kind is ArtifactKind.CLIPBOARD else self._export_ttl
        return datetime.now(UTC) + timedelta(seconds=ttl)

    @staticmethod
    def _destination_candidates(guild: Any) -> tuple[DestinationCandidate, ...]:
        result: list[DestinationCandidate] = []
        for role in guild.roles:
            resource_type = (
                PortableResourceType.SYSTEM_PRINCIPAL
                if role.role_id == guild.guild_id
                else PortableResourceType.ROLE
            )
            result.append(
                DestinationCandidate(
                    guild.guild_id,
                    resource_type,
                    str(role.role_id),
                    role.name,
                    managed=role.managed,
                    attributes={
                        "name": role.name,
                        "permissions": str(role.permissions),
                        "color": role.color,
                        "hoist": role.hoist,
                        "mentionable": role.mentionable,
                        "position": role.position,
                        "managed": role.managed,
                    },
                )
            )
            if role.managed and role.role_id != guild.guild_id:
                result.append(
                    DestinationCandidate(
                        guild.guild_id,
                        PortableResourceType.BOT_REFERENCE,
                        str(role.role_id),
                        role.name,
                        managed=True,
                        attributes={"name": role.name, "managed": True},
                    )
                )
        for channel in guild.channels:
            if channel.is_thread:
                continue
            resource_type = (
                PortableResourceType.CATEGORY
                if int(channel.channel_type) == 4
                else PortableResourceType.CHANNEL
            )
            result.append(
                DestinationCandidate(
                    guild.guild_id,
                    resource_type,
                    str(channel.channel_id),
                    channel.name,
                    attributes={
                        "name": channel.name,
                        "type": int(channel.channel_type),
                        "position": channel.position,
                        "parent_id": channel.parent_id,
                        "topic": channel.topic,
                        "nsfw": channel.nsfw,
                        "flags": channel.flags,
                    },
                )
            )
        return tuple(result)

    @staticmethod
    def _resolution_json(item: Any, *, actor_user_id: int) -> dict[str, Any]:
        value = {
            "source_logical_ref": item.source_logical_ref,
            "resource_type": item.resource_type.value,
            "decision": item.decision.value,
            "reason": item.reason,
            "destination_ref": item.destination_ref,
            "candidate_refs": list(item.candidate_refs),
            "score": item.score,
            "confirmation_required": item.confirmation_required,
        }
        if (
            item.decision is MappingDecision.MAP_EXISTING
            and item.reason == "mapping.explicit_confirmed"
        ):
            value["confirmed_by"] = str(actor_user_id)
            value["confirmed_at"] = "TRANSFER_CREATED_AT"
        return value

    @staticmethod
    def _report_json(item: Any) -> dict[str, Any]:
        value = asdict(item)
        value["resource_type"] = item.resource_type.value
        value["outcome"] = item.outcome.value
        return value

    @staticmethod
    def _planning_idempotency_key(
        artifact_id: UUID,
        destination_guild_id: int,
        mode: CloneMode,
        mapping: list[dict[str, Any]],
        caller_key: str,
    ) -> str:
        digest = hashlib.sha256(
            json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:24]
        value = f"portable:{artifact_id}:{destination_guild_id}:{mode.value}:{digest}:{caller_key}"
        return value[:160]

    @staticmethod
    def _transfer_idempotency_key(
        artifact_id: UUID,
        destination_guild_id: int,
        mode: CloneMode,
        mapping: list[dict[str, Any]],
        caller_key: str,
    ) -> str:
        material = json.dumps(
            {
                "artifact_id": str(artifact_id),
                "destination_guild_id": str(destination_guild_id),
                "mode": mode.value,
                "mapping": mapping,
                "caller_key": caller_key,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return "portable-transfer:" + hashlib.sha256(material).hexdigest()

    @staticmethod
    def _export_idempotency_key(
        source_guild_id: int,
        selection: ArtifactSelection,
        kind: ArtifactKind,
        logical_group_id: UUID | None,
        caller_key: str,
    ) -> str:
        material = json.dumps(
            {
                "source_guild_id": str(source_guild_id),
                "artifact_type": selection.artifact_type.value,
                "category_ids": selection.category_ids,
                "channel_ids": selection.channel_ids,
                "role_ids": selection.role_ids,
                "logical_group_id": str(logical_group_id) if logical_group_id else None,
                "kind": kind.value,
                "caller_key": caller_key,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return "portable-export:" + hashlib.sha256(material).hexdigest()
