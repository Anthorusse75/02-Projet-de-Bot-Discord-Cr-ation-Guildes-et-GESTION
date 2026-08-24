from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from did.portability.artifact import PortableResource, PortableResourceType
from did.portability.graph import DependencyGraph


class CloneMode(StrEnum):
    COPY_AS_NEW = "COPY_AS_NEW"
    MERGE = "MERGE"
    RECONCILE = "RECONCILE"
    MAXIMUM_COMPATIBLE = "MAXIMUM_COMPATIBLE"


class MappingDecision(StrEnum):
    CREATE = "CREATE"
    MAP_EXISTING = "MAP_EXISTING"
    SKIP = "SKIP"
    UNSUPPORTED = "UNSUPPORTED"
    MANUAL = "MANUAL"


@dataclass(frozen=True, slots=True)
class DestinationCandidate:
    destination_guild_id: int
    resource_type: PortableResourceType
    destination_ref: str
    name: str | None = None
    portable_key: str | None = None
    managed: bool = False
    attributes: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.destination_guild_id <= 0:
            raise ValueError("destination candidate Guild must be positive")
        if not self.destination_ref.isdecimal() or int(self.destination_ref) <= 0:
            raise ValueError("destination candidate ref must be a positive Discord ID")


@dataclass(frozen=True, slots=True)
class ExplicitMapping:
    source_logical_ref: str
    destination_guild_id: int
    destination_ref: str
    resource_type: PortableResourceType
    confirmed: bool


@dataclass(frozen=True, slots=True)
class MappingResolution:
    source_logical_ref: str
    resource_type: PortableResourceType
    decision: MappingDecision
    reason: str
    destination_ref: str | None = None
    candidate_refs: tuple[str, ...] = field(default_factory=tuple)
    score: int | None = None
    confirmation_required: bool = False


class MappingResolver:
    """Resolve portable symbols without ever comparing source Discord IDs."""

    def resolve(
        self,
        graph: DependencyGraph,
        *,
        destination_guild_id: int,
        mode: CloneMode,
        candidates: tuple[DestinationCandidate, ...] = (),
        explicit: tuple[ExplicitMapping, ...] = (),
    ) -> tuple[MappingResolution, ...]:
        explicit_by_source = {item.source_logical_ref: item for item in explicit}
        candidate_by_ref = {(item.destination_ref, item.resource_type): item for item in candidates}
        result: list[MappingResolution] = []
        for resource in graph.nodes:
            mapping = explicit_by_source.get(resource.logical_key)
            if mapping is not None:
                expected_target_type = self._explicit_target_type(resource)
                candidate = candidate_by_ref.get((mapping.destination_ref, expected_target_type))
                if (
                    mapping.destination_guild_id != destination_guild_id
                    or mapping.resource_type is not resource.resource_type
                    or candidate is None
                    or candidate.destination_guild_id != destination_guild_id
                    or candidate.resource_type is not expected_target_type
                ):
                    raise ValueError("explicit mapping target is foreign or incompatible")
                if not mapping.confirmed:
                    result.append(
                        MappingResolution(
                            resource.logical_key,
                            resource.resource_type,
                            MappingDecision.MANUAL,
                            "mapping.explicit_confirmation_required",
                            candidate.destination_ref,
                            (candidate.destination_ref,),
                            100,
                            True,
                        )
                    )
                else:
                    result.append(
                        MappingResolution(
                            resource.logical_key,
                            resource.resource_type,
                            MappingDecision.MAP_EXISTING,
                            "mapping.explicit_confirmed",
                            candidate.destination_ref,
                            (candidate.destination_ref,),
                            100,
                            False,
                        )
                    )
                continue
            result.append(self._automatic(resource, destination_guild_id, mode, candidates))
        return tuple(sorted(result, key=lambda item: item.source_logical_ref))

    @staticmethod
    def _explicit_target_type(resource: PortableResource) -> PortableResourceType:
        if resource.resource_type is PortableResourceType.PRINCIPAL_REQUIREMENT:
            kind = resource.attribute_map().get("kind")
            if kind == "ROLE":
                return PortableResourceType.ROLE
        return resource.resource_type

    @staticmethod
    def _automatic(
        resource: PortableResource,
        destination_guild_id: int,
        mode: CloneMode,
        candidates: tuple[DestinationCandidate, ...],
    ) -> MappingResolution:
        attributes = resource.attribute_map()
        if resource.resource_type is PortableResourceType.SYSTEM_PRINCIPAL:
            if attributes.get("kind") != "EVERYONE":
                return MappingResolution(
                    resource.logical_key,
                    resource.resource_type,
                    MappingDecision.UNSUPPORTED,
                    "mapping.system_principal_unsupported",
                )
            return MappingResolution(
                resource.logical_key,
                resource.resource_type,
                MappingDecision.MAP_EXISTING,
                "mapping.destination_everyone",
                str(destination_guild_id),
                (str(destination_guild_id),),
                100,
            )
        if resource.resource_type in {
            PortableResourceType.PRINCIPAL_REQUIREMENT,
            PortableResourceType.BOT_REFERENCE,
            PortableResourceType.WEBHOOK_REFERENCE,
        }:
            name = attributes.get("name")
            suggestions = tuple(
                sorted(
                    item.destination_ref
                    for item in candidates
                    if item.destination_guild_id == destination_guild_id
                    and item.resource_type is MappingResolver._explicit_target_type(resource)
                    and (not isinstance(name, str) or item.name == name)
                )
            )
            return MappingResolution(
                resource.logical_key,
                resource.resource_type,
                MappingDecision.MANUAL,
                "mapping.sensitive_principal_requires_explicit_destination",
                candidate_refs=suggestions,
                score=50 if suggestions else None,
                confirmation_required=True,
            )
        if resource.resource_type is PortableResourceType.ROLE and bool(attributes.get("managed")):
            return MappingResolution(
                resource.logical_key,
                resource.resource_type,
                MappingDecision.MANUAL,
                "mapping.managed_role_cannot_be_created",
                confirmation_required=True,
            )
        safe = tuple(
            item
            for item in candidates
            if item.destination_guild_id == destination_guild_id
            and item.resource_type is resource.resource_type
            and item.portable_key == resource.logical_key
        )
        if len(safe) == 1 and mode in {CloneMode.MERGE, CloneMode.RECONCILE}:
            return MappingResolution(
                resource.logical_key,
                resource.resource_type,
                MappingDecision.MAP_EXISTING,
                "mapping.unique_did_managed_key",
                safe[0].destination_ref,
                (safe[0].destination_ref,),
                100,
            )
        if len(safe) > 1:
            return MappingResolution(
                resource.logical_key,
                resource.resource_type,
                MappingDecision.MANUAL,
                "mapping.ambiguous_managed_key",
                candidate_refs=tuple(sorted(item.destination_ref for item in safe)),
                confirmation_required=True,
            )
        name = attributes.get("name")
        same_name = tuple(
            item
            for item in candidates
            if item.destination_guild_id == destination_guild_id
            and item.resource_type is resource.resource_type
            and isinstance(name, str)
            and item.name == name
        )
        if same_name and mode is not CloneMode.COPY_AS_NEW:
            return MappingResolution(
                resource.logical_key,
                resource.resource_type,
                MappingDecision.MANUAL,
                "mapping.name_is_candidate_not_identity",
                candidate_refs=tuple(sorted(item.destination_ref for item in same_name)),
                score=50,
                confirmation_required=True,
            )
        if resource.resource_type in {
            PortableResourceType.OVERWRITE,
            PortableResourceType.POLICY,
            PortableResourceType.LOGICAL_GROUP,
        }:
            return MappingResolution(
                resource.logical_key,
                resource.resource_type,
                MappingDecision.CREATE,
                "mapping.create_portable_configuration",
            )
        return MappingResolution(
            resource.logical_key,
            resource.resource_type,
            MappingDecision.CREATE,
            "mapping.create_new_destination_resource",
        )
