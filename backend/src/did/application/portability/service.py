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
from did.domain.discord_runtime import ObservabilityState
from did.infrastructure.planning_repository import PlanningRepository
from did.infrastructure.portability_repository import PortabilityRepository, TransferConflict
from did.infrastructure.runtime_metrics import RuntimeMetrics
from did.infrastructure.stage04_repository import Stage04Repository
from did.infrastructure.stage08_lifecycle_repository import Stage08LifecycleRepository
from did.infrastructure.stage08_repository import (
    ResourceLanguagePolicyRepository,
    TranslationGroupRepository,
    TranslationProviderBindingRepository,
)
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
        translation_groups: TranslationGroupRepository | None = None,
        translation_policies: ResourceLanguagePolicyRepository | None = None,
        translation_providers: TranslationProviderBindingRepository | None = None,
        translation_lifecycle: Stage08LifecycleRepository | None = None,
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
        self._translation_groups = translation_groups
        self._translation_policies = translation_policies
        self._translation_providers = translation_providers
        self._translation_lifecycle = translation_lifecycle

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

    async def export_live_translation_group(
        self,
        *,
        source_guild_id: int,
        translation_group_id: UUID,
        actor_user_id: int,
        kind: ArtifactKind,
        name: str | None,
        idempotency_key: str,
        correlation_id: UUID,
    ) -> tuple[dict[str, Any], bool]:
        if (
            self._translation_groups is None
            or self._translation_policies is None
            or self._translation_lifecycle is None
        ):
            raise ValueError("translation portability is not configured")
        guild, _ = await self._read_models.guild_snapshot(source_guild_id, actor_user_id)
        group = await self._translation_groups.workspace_group(
            guild_id=source_guild_id,
            group_id=translation_group_id,
        )
        policies = tuple(
            await self._translation_policies.list_policies(source_guild_id)
        )
        language_bindings = tuple(
            await self._translation_lifecycle.list_language_bindings(
                guild_id=source_guild_id
            )
        )
        provider_requirement: dict[str, Any] | None = None
        provider_binding_id = group.get("provider_binding_id")
        if provider_binding_id is not None:
            if self._translation_providers is None:
                raise ValueError("translation provider portability is not configured")
            binding = await self._translation_providers.get(
                guild_id=source_guild_id,
                binding_id=UUID(str(provider_binding_id)),
            )
            capabilities = dict(binding.get("capabilities_json") or {})
            provider_requirement = {
                "provider_type": str(binding["provider_type"]),
                "required_capabilities": [str(group["routing_mode"])],
                "configuration_mode": "MANUAL_CONFIGURATION_REQUIRED",
                "requires_message_content": bool(
                    capabilities.get("requires_message_content", False)
                ),
            }
        started = perf_counter()
        artifact = self._builder.build_live_translation_group(
            guild,
            group,
            policies=policies,
            language_role_bindings=language_bindings,
            provider_requirement=provider_requirement,
        )
        if self._metrics is not None:
            self._metrics.artifact_built(
                perf_counter() - started, len(artifact_to_bytes(artifact))
            )
        metadata, created = await self.repository.create_artifact(
            owner_user_id=actor_user_id,
            kind=kind.value,
            artifact=artifact,
            name=name,
            expires_at=self._expiry(kind),
            idempotency_operation="TRANSLATION_GROUP_EXPORT",
            idempotency_key=self._translation_export_idempotency_key(
                source_guild_id,
                translation_group_id,
                kind,
                idempotency_key,
            ),
        )
        if created:
            await self.repository.audit_boundary(
                guild_id=source_guild_id,
                actor_user_id=actor_user_id,
                transfer_id=UUID(str(metadata["id"])),
                event_type="TRANSLATION_PORTABLE_ARTIFACT_EXPORTED",
                artifact_hash=artifact.content_hash,
                correlation_id=correlation_id,
                target_type="ARTIFACT",
            )
        return metadata, created

    async def find_live_export(
        self,
        *,
        actor_user_id: int,
        source_guild_id: int,
        selection: ArtifactSelection,
        kind: ArtifactKind,
        idempotency_key: str,
        logical_group_id: UUID | None = None,
    ) -> dict[str, Any] | None:
        return await self.repository.find_artifact_by_idempotency(
            actor_user_id,
            "LIVE_EXPORT",
            self._export_idempotency_key(
                source_guild_id, selection, kind, logical_group_id, idempotency_key
            ),
        )

    async def find_resumable_transfer(
        self,
        *,
        actor_user_id: int,
        artifact_id: UUID,
        destination_guild_id: int,
        mode: CloneMode,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        transfer = await self.repository.find_transfer_by_idempotency(
            actor_user_id,
            self._stored_transfer_idempotency_key(
                artifact_id, destination_guild_id, mode, idempotency_key
            ),
        )
        if transfer is None or str(transfer["status"]) == TransferState.CREATED.value:
            return None
        return transfer

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
        source_authorized: bool = False,
        relationship_id: UUID | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None, bool]:
        transfer, transfer_created, artifact = await self.prepare_stored_transfer(
            actor_user_id=actor_user_id,
            artifact_id=artifact_id,
            destination_guild_id=destination_guild_id,
            mode=mode,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_authorized=source_authorized,
            relationship_id=relationship_id,
        )
        transfer_id = UUID(str(transfer["id"]))
        state = TransferState(str(transfer["status"]))
        frozen_mapping_hash: str | None = None
        frozen_mapping_json: list[dict[str, Any]] | None = None
        if state in {TransferState.READY, TransferState.COMPILED}:
            raw_mapping = transfer.get("mapping_json")
            if not isinstance(raw_mapping, list) or not all(
                isinstance(item, dict) for item in raw_mapping
            ):
                raise TransferConflict("frozen transfer mapping is invalid")
            frozen_mapping_json = [dict(item) for item in raw_mapping]
            stored_mapping_hash = transfer.get("mapping_hash")
            if not isinstance(stored_mapping_hash, str) or len(stored_mapping_hash) != 64:
                raise TransferConflict("frozen transfer mapping hash is invalid")
            replay_mapping_hash = self._semantic_mapping_hash(
                explicit_mappings, frozen_mapping_json
            )
            if replay_mapping_hash != stored_mapping_hash:
                raise TransferConflict("transfer mapping is already frozen")
            frozen_mapping_hash = stored_mapping_hash
            if state is TransferState.COMPILED:
                raw_plan_id = transfer.get("destination_plan_id")
                plan = (
                    await self._planning_repository.get_plan(
                        destination_guild_id, UUID(str(raw_plan_id))
                    )
                    if raw_plan_id is not None
                    else None
                )
                return transfer, plan, False
        destination, _ = await self._read_models.guild_snapshot(destination_guild_id, actor_user_id)
        candidates, owned_scope = await self._server_relationship_candidates(
            actor_user_id=actor_user_id,
            destination_guild_id=destination_guild_id,
            relationship_id=UUID(str(transfer["relationship_id"])),
            candidates=self._destination_candidates(destination),
        )
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
        mapping_json = [
            self._resolution_json(item, actor_user_id=actor_user_id) for item in resolutions
        ]
        resolved_mapping_hash = self._semantic_mapping_hash(explicit_mappings, mapping_json)
        if state is TransferState.READY:
            if resolved_mapping_hash != frozen_mapping_hash:
                raise TransferConflict("frozen transfer mapping is stale")
            if frozen_mapping_json is None:
                raise TransferConflict("frozen transfer mapping is invalid")
            mapping_json = frozen_mapping_json
        if unresolved and mode is not CloneMode.MAXIMUM_COMPATIBLE:
            if state is TransferState.EXPORTED:
                await self.repository.transition_transfer(
                    actor_user_id=actor_user_id,
                    transfer_id=transfer_id,
                    expected=TransferState.EXPORTED,
                    target=TransferState.MAPPING_REQUIRED,
                    mapping=mapping_json,
                    report=mapping_json,
                )
            raise MappingRequired(unresolved)
        if state in {TransferState.EXPORTED, TransferState.MAPPING_REQUIRED}:
            transfer = await self.repository.freeze_transfer_mapping(
                actor_user_id=actor_user_id,
                transfer_id=transfer_id,
                expected=state,
                mapping=mapping_json,
                mapping_hash=resolved_mapping_hash,
            )
            state = TransferState.READY
            frozen_mapping_hash = resolved_mapping_hash
        if frozen_mapping_hash is None:
            raise TransferConflict("transfer mapping was not frozen")
        compilation = self._compiler.compile(
            artifact,
            destination_guild_id=destination_guild_id,
            mode=mode,
            resolutions=resolutions,
            candidates=candidates,
            reconcile_scope=owned_scope if mode is CloneMode.RECONCILE else None,
        )
        if self._metrics is not None:
            self._metrics.portability_outcome("transfer_state", TransferState.READY.value)
        report_json = [self._report_json(item) for item in compilation.report.entries]
        report_hash = self._canonical_hash(report_json)
        if compilation.no_mutation:
            transfer = await self.repository.compile_transfer(
                actor_user_id=actor_user_id,
                transfer_id=transfer_id,
                destination_plan_id=None,
                report=report_json,
                mapping_hash=frozen_mapping_hash,
                report_hash=report_hash,
            )
            await self.repository.audit_boundary(
                guild_id=destination_guild_id,
                actor_user_id=actor_user_id,
                transfer_id=transfer_id,
                event_type="PORTABLE_ARTIFACT_COMPILED",
                artifact_hash=artifact.content_hash,
                correlation_id=correlation_id,
            )
            return transfer, None, transfer_created
        planning_key = self._planning_idempotency_key(
            artifact_id, destination_guild_id, mode, frozen_mapping_hash, idempotency_key
        )
        if compilation.graph is None:
            raise RuntimeError("mutable compilation is missing a destination graph")
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
        if self._metrics is not None:
            for report_entry in compilation.report.entries:
                self._metrics.portability_outcome("clone_report", report_entry.outcome.value)
            self._metrics.portability_outcome("transfer_state", TransferState.COMPILED.value)
        transfer = await self.repository.compile_transfer(
            actor_user_id=actor_user_id,
            transfer_id=transfer_id,
            destination_plan_id=UUID(str(plan["id"])),
            report=report_json,
            mapping_hash=frozen_mapping_hash,
            report_hash=report_hash,
        )
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

    async def prepare_stored_transfer(
        self,
        *,
        actor_user_id: int,
        artifact_id: UUID,
        destination_guild_id: int,
        mode: CloneMode,
        idempotency_key: str,
        correlation_id: UUID,
        source_authorized: bool = False,
        relationship_id: UUID | None = None,
    ) -> tuple[dict[str, Any], bool, Any]:
        metadata, artifact = await self.repository.get_artifact(actor_user_id, artifact_id)
        if relationship_id is None:
            if mode is CloneMode.RECONCILE:
                raise TransferConflict("RECONCILE requires an explicit clone relationship")
            relationship, _ = await self.repository.create_clone_relationship(
                actor_user_id=actor_user_id,
                destination_guild_id=destination_guild_id,
                creation_key=self._relationship_creation_key(
                    artifact_id, destination_guild_id, mode, idempotency_key
                ),
                source_descriptor={
                    "artifact_type": artifact.artifact_type.value,
                    "source_guild_id": metadata.get("source_guild_id"),
                    "authority": "INFORMATIVE_ONLY",
                },
            )
            relationship_id = UUID(str(relationship["relationship_id"]))
        else:
            await self.repository.get_clone_relationship(
                actor_user_id, destination_guild_id, relationship_id
            )
        request_hash = self._canonical_hash(
            {
                "artifact_id": str(artifact_id),
                "artifact_hash": artifact.content_hash,
                "destination_guild_id": str(destination_guild_id),
                "mode": mode.value,
                "caller_key": idempotency_key,
                "relationship_id": str(relationship_id),
            }
        )
        transfer_key = self._stored_transfer_idempotency_key(
            artifact_id, destination_guild_id, mode, idempotency_key
        )
        transfer, created = await self.repository.create_transfer(
            transfer_id=uuid4(),
            actor_user_id=actor_user_id,
            source_guild_id=metadata["source_guild_id"],
            destination_guild_id=destination_guild_id,
            artifact_id=artifact_id,
            artifact_content_hash=artifact.content_hash,
            mode=mode.value,
            mapping=[],
            status=TransferState.CREATED.value,
            correlation_id=correlation_id,
            idempotency_key=transfer_key,
            relationship_id=relationship_id,
            request_hash=request_hash,
        )
        state = TransferState(str(transfer["status"]))
        if state is TransferState.CREATED and source_authorized:
            transfer = await self.repository.transition_transfer(
                actor_user_id=actor_user_id,
                transfer_id=UUID(str(transfer["id"])),
                expected=TransferState.CREATED,
                target=TransferState.SOURCE_AUTHORIZED,
            )
            state = TransferState(str(transfer["status"]))
        if state in {TransferState.CREATED, TransferState.SOURCE_AUTHORIZED}:
            transfer = await self.repository.transition_transfer(
                actor_user_id=actor_user_id,
                transfer_id=UUID(str(transfer["id"])),
                expected=state,
                target=TransferState.EXPORTED,
            )
        return transfer, created, artifact

    async def preview_stored(
        self,
        *,
        actor_user_id: int,
        artifact_id: UUID,
        destination_guild_id: int,
        mode: CloneMode,
        explicit_mappings: tuple[ExplicitMapping, ...],
        relationship_id: UUID | None = None,
    ) -> dict[str, Any]:
        _, artifact = await self.repository.get_artifact(actor_user_id, artifact_id)
        destination, _ = await self._read_models.guild_snapshot(destination_guild_id, actor_user_id)
        if mode is CloneMode.RECONCILE and relationship_id is None:
            raise TransferConflict("RECONCILE requires an explicit clone relationship")
        if relationship_id is not None:
            await self.repository.get_clone_relationship(
                actor_user_id, destination_guild_id, relationship_id
            )
            candidates, scope = await self._server_relationship_candidates(
                actor_user_id=actor_user_id,
                destination_guild_id=destination_guild_id,
                relationship_id=relationship_id,
                candidates=self._destination_candidates(destination),
            )
        else:
            candidates = self._destination_candidates(destination)
            scope = ReconcileScope()
        resolutions = self._resolver.resolve(
            DependencyGraph.build(artifact),
            destination_guild_id=destination_guild_id,
            mode=mode,
            candidates=candidates,
            explicit=explicit_mappings,
        )
        compilation = self._compiler.compile(
            artifact,
            destination_guild_id=destination_guild_id,
            mode=mode,
            resolutions=resolutions,
            candidates=candidates,
            reconcile_scope=scope if mode is CloneMode.RECONCILE else None,
        )
        report = [self._report_json(item) for item in compilation.report.entries]
        return {
            "mappings": [
                self._resolution_json(item, actor_user_id=actor_user_id) for item in resolutions
            ],
            "report": report,
            "delete_candidates": [item for item in report if item["destructive"]],
            "no_mutation": compilation.no_mutation,
        }

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
    ) -> tuple[dict[str, Any], dict[str, Any] | None, bool]:
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
        raw_relationship_id = transfer.get("relationship_id")
        if raw_relationship_id is None:
            raise ValueError("clone relationship is unavailable")
        relationship_id = UUID(str(raw_relationship_id))
        durable_bindings: list[dict[str, Any]] = []
        for logical_ref, resource in resources_by_ref.items():
            if resource.resource_type not in {
                PortableResourceType.ROLE,
                PortableResourceType.CATEGORY,
                PortableResourceType.CHANNEL,
            }:
                continue
            mapping = mappings[logical_ref]
            destination_ref = mapping.get("destination_ref")
            origin = "EXPLICIT"
            if mapping["decision"] == MappingDecision.CREATE.value:
                destination_ref = bindings.get(f"portable:{logical_ref}")
                origin = "CREATED"
            elif mapping.get("reason") == "mapping.unique_did_managed_key":
                origin = "MANAGED_KEY"
            if destination_ref is None:
                raise ValueError("clone destination binding is unresolved")
            durable_bindings.append(
                {
                    "logical_ref": logical_ref,
                    "resource_type": resource.resource_type.value,
                    "destination_resource_id": int(destination_ref),
                    "binding_origin": origin,
                }
            )
        await self.repository.save_clone_bindings(
            actor_user_id=actor_user_id,
            transfer_id=transfer_id,
            destination_guild_id=destination_guild_id,
            relationship_id=relationship_id,
            artifact_hash=artifact.content_hash,
            bindings=durable_bindings,
        )
        translation_result = await self._finalize_translation_topology(
            artifact=artifact,
            destination_guild_id=destination_guild_id,
            transfer_id=transfer_id,
            mappings=mappings,
            symbol_bindings=bindings,
        )
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
            "translation_topology": translation_result,
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

    async def _finalize_translation_topology(
        self,
        *,
        artifact: Any,
        destination_guild_id: int,
        transfer_id: UUID,
        mappings: dict[str, dict[str, Any]],
        symbol_bindings: dict[str, int],
    ) -> dict[str, Any] | None:
        translation_groups = tuple(
            resource
            for resource in artifact.resources
            if resource.resource_type is PortableResourceType.TRANSLATION_GROUP
        )
        if not translation_groups:
            return None
        if len(translation_groups) != 1 or self._translation_groups is None:
            raise ValueError("portable translation topology is unavailable or ambiguous")
        dependencies = {
            (edge.source, edge.relation): edge.target for edge in artifact.dependencies
        }

        def identity(logical_ref: str, kind: str) -> UUID:
            return uuid5(
                NAMESPACE_URL,
                f"did:portable-translation:{kind}:{transfer_id}:{logical_ref}",
            )

        def destination_resource(logical_ref: str) -> int:
            mapping = mappings[logical_ref]
            destination_ref = mapping.get("destination_ref")
            if mapping["decision"] == MappingDecision.CREATE.value:
                destination_ref = symbol_bindings.get(f"portable:{logical_ref}")
            if destination_ref is None:
                raise ValueError("portable translation Discord binding is unresolved")
            return int(destination_ref)

        group_resource = translation_groups[0]
        group_attributes = group_resource.attribute_map()
        language_resources = tuple(
            resource
            for resource in artifact.resources
            if resource.resource_type is PortableResourceType.LANGUAGE_PROFILE
        )
        topology: dict[str, Any] = {
            "languages": [
                {
                    "id": identity(resource.logical_key, "language"),
                    **resource.attribute_map(),
                }
                for resource in language_resources
            ],
            "group": {
                "id": identity(group_resource.logical_key, "group"),
                **group_attributes,
            },
            "channel_groups": [],
            "category_variants": [],
            "channel_variants": [],
            "routes": [],
            "language_roles": [],
        }
        for resource in artifact.resources:
            attributes = resource.attribute_map()
            if resource.resource_type is PortableResourceType.TRANSLATION_CHANNEL_GROUP:
                topology["channel_groups"].append(
                    {
                        "id": identity(resource.logical_key, "channel-group"),
                        "logical_ref": resource.logical_key,
                        **attributes,
                    }
                )
            elif resource.resource_type is PortableResourceType.TRANSLATION_CATEGORY_VARIANT:
                discord_ref = dependencies.get((resource.logical_key, "discord_resource"))
                if discord_ref is None:
                    raise ValueError("portable category variant has no Discord dependency")
                topology["category_variants"].append(
                    {
                        "id": identity(resource.logical_key, "category-variant"),
                        "policy_id": identity(resource.logical_key, "category-policy"),
                        "logical_ref": resource.logical_key,
                        "discord_resource_id": destination_resource(discord_ref),
                        **attributes,
                    }
                )
            elif resource.resource_type is PortableResourceType.TRANSLATION_CHANNEL_VARIANT:
                discord_ref = dependencies.get((resource.logical_key, "discord_resource"))
                channel_group_ref = dependencies.get(
                    (resource.logical_key, "translation_channel_group")
                )
                if discord_ref is None or channel_group_ref is None:
                    raise ValueError("portable channel variant dependencies are incomplete")
                topology["channel_variants"].append(
                    {
                        "id": identity(resource.logical_key, "channel-variant"),
                        "policy_id": identity(resource.logical_key, "channel-policy"),
                        "logical_ref": resource.logical_key,
                        "discord_resource_id": destination_resource(discord_ref),
                        "translation_channel_group_ref": channel_group_ref,
                        "translation_category_variant_ref": dependencies.get(
                            (resource.logical_key, "translation_category_variant")
                        ),
                        **attributes,
                    }
                )
            elif resource.resource_type is PortableResourceType.TRANSLATION_ROUTE:
                topology["routes"].append(
                    {"id": identity(resource.logical_key, "route"), **attributes}
                )
            elif resource.resource_type is PortableResourceType.TRANSLATION_LANGUAGE_ROLE:
                discord_ref = dependencies.get((resource.logical_key, "discord_resource"))
                if discord_ref is None:
                    raise ValueError("portable language role has no Discord dependency")
                topology["language_roles"].append(
                    {
                        "id": identity(resource.logical_key, "language-role"),
                        "discord_role_id": destination_resource(discord_ref),
                        **attributes,
                    }
                )
        result = await self._translation_groups.materialize_portable_topology(
            guild_id=destination_guild_id,
            topology=topology,
        )
        result["source_translation_group_id_propagated"] = False
        result["provider_requirements"] = [
            resource.attribute_map()
            for resource in artifact.resources
            if resource.resource_type is PortableResourceType.PROVIDER_REQUIREMENT
        ]
        result["provider_bindings_omitted"] = True
        return result

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
            if channel.is_thread or channel.observability is ObservabilityState.DELETED_CONFIRMED:
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
                        "bitrate": channel.bitrate,
                        "user_limit": channel.user_limit,
                        "rate_limit_per_user": channel.rate_limit_per_user,
                        "default_auto_archive_duration": channel.default_auto_archive_duration,
                    },
                )
            )
        return tuple(result)

    async def _server_relationship_candidates(
        self,
        *,
        actor_user_id: int,
        destination_guild_id: int,
        relationship_id: UUID,
        candidates: tuple[DestinationCandidate, ...],
    ) -> tuple[tuple[DestinationCandidate, ...], ReconcileScope]:
        rows = await self.repository.reconcile_bindings(
            actor_user_id, destination_guild_id, relationship_id
        )
        candidates_by_identity = {
            (item.destination_ref, item.resource_type): item for item in candidates
        }
        owned_by_identity: dict[tuple[str, PortableResourceType], DestinationCandidate] = {}
        for row in rows:
            resource_type = PortableResourceType(str(row["resource_type"]))
            destination_ref = str(row["destination_resource_id"])
            candidate = candidates_by_identity.get((destination_ref, resource_type))
            if candidate is None:
                continue
            owned_by_identity[(destination_ref, resource_type)] = DestinationCandidate(
                destination_guild_id,
                resource_type,
                destination_ref,
                candidate.name,
                portable_key=str(row["logical_ref"]),
                managed=candidate.managed,
                attributes=candidate.attributes,
            )
        decorated = tuple(
            owned_by_identity.get((item.destination_ref, item.resource_type), item)
            for item in candidates
        )
        return decorated, ReconcileScope(
            tuple(
                sorted(
                    owned_by_identity.values(),
                    key=lambda item: (item.resource_type.value, item.destination_ref),
                )
            )
        )

    @staticmethod
    def _relationship_creation_key(
        artifact_id: UUID,
        destination_guild_id: int,
        mode: CloneMode,
        caller_key: str,
    ) -> str:
        material = json.dumps(
            {
                "operation": "CREATE_CLONE_RELATIONSHIP",
                "artifact_id": str(artifact_id),
                "destination_guild_id": str(destination_guild_id),
                "mode": mode.value,
                "caller_key": caller_key,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(material).hexdigest()

    @staticmethod
    def _canonical_explicit_mappings(
        explicit_mappings: tuple[ExplicitMapping, ...],
    ) -> list[dict[str, Any]]:
        return [
            {
                "source_logical_ref": item.source_logical_ref,
                "destination_guild_id": str(item.destination_guild_id),
                "destination_ref": item.destination_ref,
                "resource_type": item.resource_type.value,
                "confirmed": item.confirmed,
            }
            for item in sorted(
                explicit_mappings,
                key=lambda value: (
                    value.source_logical_ref,
                    value.resource_type.value,
                    value.destination_ref,
                ),
            )
        ]

    @classmethod
    def _semantic_mapping_hash(
        cls,
        explicit_mappings: tuple[ExplicitMapping, ...],
        resolved_mapping: list[dict[str, Any]],
    ) -> str:
        explicit_sources = {item.source_logical_ref for item in explicit_mappings}
        resolved = []
        for item in resolved_mapping:
            source_logical_ref = str(item["source_logical_ref"])
            if source_logical_ref in explicit_sources:
                confirmation = "CONFIRMED"
            elif bool(item.get("confirmation_required")):
                confirmation = "REQUIRED"
            else:
                confirmation = "NOT_REQUIRED"
            resolved.append(
                {
                    "source_logical_ref": source_logical_ref,
                    "resource_type": str(item["resource_type"]),
                    "decision": str(item["decision"]),
                    "destination_ref": (
                        str(item["destination_ref"])
                        if item.get("destination_ref") is not None
                        else None
                    ),
                    "confirmation": confirmation,
                }
            )
        resolved.sort(
            key=lambda item: (
                item["source_logical_ref"],
                item["resource_type"],
                item["decision"],
                item["destination_ref"] or "",
            )
        )
        return cls._canonical_hash(
            {
                "explicit": cls._canonical_explicit_mappings(explicit_mappings),
                "resolved": resolved,
            }
        )

    @staticmethod
    def _canonical_hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _stored_transfer_idempotency_key(
        cls,
        artifact_id: UUID,
        destination_guild_id: int,
        mode: CloneMode,
        idempotency_key: str,
    ) -> str:
        return cls._transfer_idempotency_key(
            artifact_id, destination_guild_id, mode, [], idempotency_key
        )

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
        mapping_hash: str,
        caller_key: str,
    ) -> str:
        material = json.dumps(
            {
                "artifact_id": str(artifact_id),
                "destination_guild_id": str(destination_guild_id),
                "mode": mode.value,
                "mapping_hash": mapping_hash,
                "caller_key": caller_key,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return "portable-plan:" + hashlib.sha256(material).hexdigest()

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

    @staticmethod
    def _translation_export_idempotency_key(
        source_guild_id: int,
        translation_group_id: UUID,
        kind: ArtifactKind,
        caller_key: str,
    ) -> str:
        material = json.dumps(
            {
                "source_guild_id": str(source_guild_id),
                "translation_group_id": str(translation_group_id),
                "kind": kind.value,
                "caller_key": caller_key,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return "translation-portable-export:" + hashlib.sha256(material).hexdigest()
