from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from did.planning.models import (
    DesiredNode,
    DesiredStateGraph,
    NodePresence,
    ReferenceKind,
    ResourceReference,
    ResourceType,
)
from did.portability.artifact import PortableArtifact, PortableResourceType
from did.portability.mapping import (
    CloneMode,
    DestinationCandidate,
    MappingDecision,
    MappingResolution,
)


class CloneReportOutcome(StrEnum):
    CLONED = "CLONED"
    CREATED = "CREATED"
    REMAPPED = "REMAPPED"
    SKIPPED = "SKIPPED"
    IMPOSSIBLE = "IMPOSSIBLE"
    INTERVENTION_REQUIRED = "INTERVENTION_REQUIRED"
    DELETE_CANDIDATE = "DELETE_CANDIDATE"


@dataclass(frozen=True, slots=True)
class CloneReportEntry:
    logical_ref: str
    resource_type: PortableResourceType
    outcome: CloneReportOutcome
    reason: str
    destination_ref: str | None = None
    destructive: bool = False


@dataclass(frozen=True, slots=True)
class CloneReport:
    mode: CloneMode
    entries: tuple[CloneReportEntry, ...]

    @property
    def complete(self) -> bool:
        return all(
            entry.outcome
            in {CloneReportOutcome.CLONED, CloneReportOutcome.CREATED, CloneReportOutcome.REMAPPED}
            for entry in self.entries
        )


@dataclass(frozen=True, slots=True)
class ReconcileScope:
    """Explicitly bounded destination resources owned by this clone relationship."""

    resources: tuple[DestinationCandidate, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class DestinationCompilation:
    graph: DesiredStateGraph
    report: CloneReport
    local_resources: tuple[str, ...] = field(default_factory=tuple)


def support_matrix() -> dict[str, dict[str, tuple[str, ...]]]:
    create_merge_reconcile = {
        CloneMode.COPY_AS_NEW.value: ("CREATE",),
        CloneMode.MERGE.value: ("CREATE", "MAP_EXISTING", "UPDATE"),
        CloneMode.RECONCILE.value: ("CREATE", "MAP_EXISTING", "UPDATE", "DELETE_IN_SCOPE"),
        CloneMode.MAXIMUM_COMPATIBLE.value: ("CREATE", "MAP_EXISTING", "REPORT"),
    }
    return {
        "version": {"value": ("did-clone-support-v1",)},
        PortableResourceType.ROLE.value: create_merge_reconcile,
        PortableResourceType.CATEGORY.value: create_merge_reconcile,
        PortableResourceType.CHANNEL.value: create_merge_reconcile,
        PortableResourceType.OVERWRITE.value: create_merge_reconcile,
        PortableResourceType.LOGICAL_GROUP.value: {
            mode.value: ("CREATE_DID_LOCAL", "REPORT") for mode in CloneMode
        },
        PortableResourceType.POLICY.value: {
            mode.value: ("CREATE_DEFINITION_WITHOUT_BINDINGS", "REPORT") for mode in CloneMode
        },
        PortableResourceType.BOT_REFERENCE.value: {
            mode.value: ("MAP_EXISTING_CONFIRMED", "MANUAL", "REPORT") for mode in CloneMode
        },
        PortableResourceType.WEBHOOK_REFERENCE.value: {
            mode.value: ("MAP_EXISTING_CONFIRMED", "MANUAL", "REPORT") for mode in CloneMode
        },
    }


class DestinationPlanCompiler:
    def compile(
        self,
        artifact: PortableArtifact,
        *,
        destination_guild_id: int,
        mode: CloneMode,
        resolutions: tuple[MappingResolution, ...],
        candidates: tuple[DestinationCandidate, ...] = (),
        reconcile_scope: ReconcileScope | None = None,
    ) -> DestinationCompilation:
        if destination_guild_id <= 0:
            raise ValueError("destination Guild must be positive")
        resolution_by_ref = {item.source_logical_ref: item for item in resolutions}
        candidate_by_ref = {(item.destination_ref, item.resource_type): item for item in candidates}
        nodes: list[DesiredNode] = []
        report: list[CloneReportEntry] = []
        local_resources: list[str] = []
        dependencies = {(item.source, item.relation): item.target for item in artifact.dependencies}
        for resource in artifact.resources:
            resolution = resolution_by_ref.get(resource.logical_key)
            if resolution is None:
                raise ValueError("every portable resource requires a mapping decision")
            if resolution.decision in {MappingDecision.MANUAL, MappingDecision.UNSUPPORTED}:
                report.append(
                    CloneReportEntry(
                        resource.logical_key,
                        resource.resource_type,
                        CloneReportOutcome.INTERVENTION_REQUIRED
                        if resolution.decision is MappingDecision.MANUAL
                        else CloneReportOutcome.IMPOSSIBLE,
                        resolution.reason,
                        resolution.destination_ref,
                    )
                )
                continue
            if resolution.decision is MappingDecision.SKIP:
                report.append(
                    CloneReportEntry(
                        resource.logical_key,
                        resource.resource_type,
                        CloneReportOutcome.SKIPPED,
                        resolution.reason,
                    )
                )
                continue
            if resource.resource_type in {
                PortableResourceType.LOGICAL_GROUP,
                PortableResourceType.POLICY,
            }:
                dependency_resolutions = (
                    resolution_by_ref[edge.target]
                    for edge in artifact.dependencies
                    if edge.source == resource.logical_key and edge.required
                )
                blocked = next(
                    (
                        item
                        for item in dependency_resolutions
                        if item.decision
                        in {
                            MappingDecision.MANUAL,
                            MappingDecision.UNSUPPORTED,
                            MappingDecision.SKIP,
                        }
                    ),
                    None,
                )
                if blocked is not None:
                    report.append(
                        CloneReportEntry(
                            resource.logical_key,
                            resource.resource_type,
                            CloneReportOutcome.INTERVENTION_REQUIRED,
                            "clone.local_dependency_unresolved",
                        )
                    )
                    continue
                local_resources.append(resource.logical_key)
                report.append(
                    CloneReportEntry(
                        resource.logical_key,
                        resource.resource_type,
                        CloneReportOutcome.CREATED,
                        "clone.destination_local_identity_created",
                    )
                )
                continue
            node = self._node(
                resource,
                resolution,
                dependencies,
                resolution_by_ref,
                candidate_by_ref,
            )
            if node is not None:
                nodes.append(node)
                report.append(
                    CloneReportEntry(
                        resource.logical_key,
                        resource.resource_type,
                        CloneReportOutcome.REMAPPED
                        if resolution.decision is MappingDecision.MAP_EXISTING
                        else CloneReportOutcome.CREATED,
                        resolution.reason,
                        resolution.destination_ref,
                    )
                )
        if mode is CloneMode.RECONCILE:
            self._append_reconcile_deletes(
                nodes,
                report,
                artifact,
                resolutions,
                reconcile_scope or ReconcileScope(),
            )
        if not nodes and not local_resources:
            raise ValueError("portable compilation produced no destination plan operations")
        return DestinationCompilation(
            DesiredStateGraph(destination_guild_id, tuple(nodes)),
            CloneReport(mode, tuple(sorted(report, key=lambda item: item.logical_ref))),
            tuple(sorted(local_resources)),
        )

    @staticmethod
    def _node(
        resource: object,
        resolution: MappingResolution,
        dependencies: dict[tuple[str, str], str],
        resolutions: dict[str, MappingResolution],
        candidates: dict[tuple[str, PortableResourceType], DestinationCandidate],
    ) -> DesiredNode | None:
        from did.portability.artifact import PortableResource

        assert isinstance(resource, PortableResource)
        kind_map = {
            PortableResourceType.ROLE: ResourceType.ROLE,
            PortableResourceType.SYSTEM_PRINCIPAL: ResourceType.ROLE,
            PortableResourceType.CATEGORY: ResourceType.CATEGORY,
            PortableResourceType.CHANNEL: ResourceType.CHANNEL,
            PortableResourceType.OVERWRITE: ResourceType.OVERWRITE,
        }
        planning_type = kind_map.get(resource.resource_type)
        if planning_type is None:
            return None
        attributes = resource.attribute_map()
        attributes.pop("managed", None)
        if resolution.decision is MappingDecision.MAP_EXISTING:
            assert resolution.destination_ref is not None
            candidate = candidates.get((resolution.destination_ref, resource.resource_type))
            if candidate is not None and candidate.attributes:
                attributes = dict(candidate.attributes)
                attributes.pop("managed", None)
                allowed = {
                    ResourceType.ROLE: {
                        "name",
                        "permissions",
                        "color",
                        "hoist",
                        "mentionable",
                        "position",
                    },
                    ResourceType.CATEGORY: {"name", "position"},
                    ResourceType.CHANNEL: {
                        "type",
                        "name",
                        "topic",
                        "nsfw",
                        "position",
                        "flags",
                        "bitrate",
                        "user_limit",
                        "rate_limit_per_user",
                        "lock_permissions",
                        "parent_id",
                    },
                    ResourceType.OVERWRITE: {"target_type", "allow", "deny"},
                }[planning_type]
                attributes = {key: value for key, value in attributes.items() if key in allowed}
            discord_id = int(resolution.destination_ref)
            symbol = None
        else:
            discord_id = None
            symbol = f"portable:{resource.logical_key}"
        relations: dict[str, ResourceReference] = {}
        relation_names = {
            "parent": "parent",
            "channel": "channel",
            "principal": "subject",
        }
        for source_relation, destination_relation in relation_names.items():
            dependency_ref = dependencies.get((resource.logical_key, source_relation))
            if dependency_ref is None:
                continue
            dependency_resolution = resolutions[dependency_ref]
            if dependency_resolution.decision in {
                MappingDecision.MANUAL,
                MappingDecision.UNSUPPORTED,
                MappingDecision.SKIP,
            }:
                return None
            relations[destination_relation] = ResourceReference(
                ReferenceKind.LOGICAL, dependency_ref
            )
        return DesiredNode.build(
            logical_key=resource.logical_key,
            resource_type=planning_type,
            properties=attributes,
            discord_id=discord_id,
            symbol=symbol,
            relations=relations,
        )

    @staticmethod
    def _append_reconcile_deletes(
        nodes: list[DesiredNode],
        report: list[CloneReportEntry],
        artifact: PortableArtifact,
        resolutions: tuple[MappingResolution, ...],
        scope: ReconcileScope,
    ) -> None:
        mapped = {
            item.destination_ref
            for item in resolutions
            if item.decision is MappingDecision.MAP_EXISTING and item.destination_ref is not None
        }
        artifact_types = {resource.resource_type for resource in artifact.resources}
        type_map = {
            PortableResourceType.ROLE: ResourceType.ROLE,
            PortableResourceType.CATEGORY: ResourceType.CATEGORY,
            PortableResourceType.CHANNEL: ResourceType.CHANNEL,
        }
        for candidate in scope.resources:
            if candidate.destination_ref in mapped or candidate.resource_type not in artifact_types:
                continue
            planning_type = type_map.get(candidate.resource_type)
            if planning_type is None:
                continue
            logical_ref = (
                f"reconcile.delete.{candidate.resource_type.value.lower()}."
                f"{candidate.destination_ref}"
            )
            nodes.append(
                DesiredNode.build(
                    logical_key=logical_ref,
                    resource_type=planning_type,
                    discord_id=int(candidate.destination_ref),
                    presence=NodePresence.ABSENT,
                )
            )
            report.append(
                CloneReportEntry(
                    logical_ref,
                    candidate.resource_type,
                    CloneReportOutcome.DELETE_CANDIDATE,
                    "clone.reconcile_explicit_scope_extra",
                    candidate.destination_ref,
                    True,
                )
            )
