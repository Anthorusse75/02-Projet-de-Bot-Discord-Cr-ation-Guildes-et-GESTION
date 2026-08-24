from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

type JsonScalar = bool | int | str | None


@dataclass(frozen=True, slots=True)
class FrozenJsonObject:
    items: tuple[tuple[str, FrozenJsonValue], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class FrozenJsonArray:
    items: tuple[FrozenJsonValue, ...] = field(default_factory=tuple)


type FrozenJsonValue = JsonScalar | FrozenJsonObject | FrozenJsonArray


def freeze_json(value: Any) -> FrozenJsonValue:
    """Convert bounded JSON-compatible data into an immutable canonical shape."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return FrozenJsonObject(
            tuple(sorted((key, freeze_json(item)) for key, item in value.items()))
        )
    if isinstance(value, list | tuple):
        return FrozenJsonArray(tuple(freeze_json(item) for item in value))
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def freeze_json_object(value: dict[str, Any]) -> FrozenJsonObject:
    frozen = freeze_json(value)
    if not isinstance(frozen, FrozenJsonObject):
        raise TypeError("JSON object required")
    return frozen


def thaw_json(value: FrozenJsonValue) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, FrozenJsonObject):
        return {key: thaw_json(item) for key, item in value.items}
    return [thaw_json(item) for item in value.items]


def thaw_json_object(value: FrozenJsonObject) -> dict[str, Any]:
    return {key: thaw_json(item) for key, item in value.items}


class ResourceType(StrEnum):
    GUILD = "GUILD"
    ROLE = "ROLE"
    CATEGORY = "CATEGORY"
    CHANNEL = "CHANNEL"
    OVERWRITE = "OVERWRITE"


class NodePresence(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"


class ReferenceKind(StrEnum):
    LOGICAL = "LOGICAL"
    DISCORD_ID = "DISCORD_ID"
    SYMBOL = "SYMBOL"


@dataclass(frozen=True, slots=True, order=True)
class ResourceReference:
    kind: ReferenceKind
    value: str

    def __post_init__(self) -> None:
        if not self.value or len(self.value) > 256 or self.value != self.value.strip():
            raise ValueError("resource reference must be present, trimmed and bounded")
        if self.kind is ReferenceKind.DISCORD_ID and (
            not self.value.isdecimal() or int(self.value) <= 0
        ):
            raise ValueError("Discord reference must be a positive decimal snowflake")


@dataclass(frozen=True, slots=True)
class DesiredNode:
    logical_key: str
    resource_type: ResourceType
    properties: FrozenJsonObject = field(default_factory=FrozenJsonObject)
    discord_id: int | None = None
    symbol: str | None = None
    presence: NodePresence = NodePresence.PRESENT
    relations: tuple[tuple[str, ResourceReference], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.logical_key or len(self.logical_key) > 256:
            raise ValueError("logical_key must be present and bounded")
        if self.discord_id is not None and self.discord_id <= 0:
            raise ValueError("discord_id must be positive")
        if self.discord_id is None and self.presence is NodePresence.PRESENT and not self.symbol:
            if self.resource_type not in {ResourceType.GUILD, ResourceType.OVERWRITE}:
                raise ValueError("future resources require a symbol")
        if self.symbol is not None and (not self.symbol or len(self.symbol) > 256):
            raise ValueError("symbol must be present and bounded")
        relation_names = [name for name, _ in self.relations]
        if len(relation_names) != len(set(relation_names)):
            raise ValueError("relation names must be unique")
        if self.resource_type is ResourceType.CATEGORY and any(
            name == "parent" for name, _ in self.relations
        ):
            raise ValueError("Discord categories cannot have a parent category")
        if self.resource_type is ResourceType.OVERWRITE:
            required = {"channel", "subject"}
            if not required.issubset(relation_names):
                raise ValueError("overwrites require channel and subject relations")

    @classmethod
    def build(
        cls,
        *,
        logical_key: str,
        resource_type: ResourceType,
        properties: dict[str, Any] | None = None,
        discord_id: int | None = None,
        symbol: str | None = None,
        presence: NodePresence = NodePresence.PRESENT,
        relations: dict[str, ResourceReference] | None = None,
    ) -> DesiredNode:
        return cls(
            logical_key=logical_key,
            resource_type=resource_type,
            properties=freeze_json_object(properties or {}),
            discord_id=discord_id,
            symbol=symbol,
            presence=presence,
            relations=tuple(sorted((relations or {}).items())),
        )

    def property_map(self) -> dict[str, Any]:
        return thaw_json_object(self.properties)

    def relation(self, name: str) -> ResourceReference | None:
        return dict(self.relations).get(name)


@dataclass(frozen=True, slots=True)
class DesiredStateGraph:
    guild_id: int
    nodes: tuple[DesiredNode, ...]
    schema_version: str = "did-dsg-v1"

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if self.schema_version != "did-dsg-v1":
            raise ValueError("unsupported Desired State Graph schema")
        ordered = tuple(sorted(self.nodes, key=lambda node: node.logical_key))
        if len({node.logical_key for node in ordered}) != len(ordered):
            raise ValueError("logical keys must be unique within a DSG")
        symbols = [node.symbol for node in ordered if node.symbol is not None]
        if len(symbols) != len(set(symbols)):
            raise ValueError("symbols must be unique within a DSG")
        known_keys = {node.logical_key for node in ordered}
        known_symbols = set(symbols)
        for node in ordered:
            for _, reference in node.relations:
                if reference.kind is ReferenceKind.LOGICAL and reference.value not in known_keys:
                    raise ValueError(f"unknown logical reference: {reference.value}")
                if reference.kind is ReferenceKind.SYMBOL and reference.value not in known_symbols:
                    raise ValueError(f"unknown symbol reference: {reference.value}")
        object.__setattr__(self, "nodes", ordered)

    def node(self, logical_key: str) -> DesiredNode | None:
        return next((node for node in self.nodes if node.logical_key == logical_key), None)


class DiffAction(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    MOVE_OR_REORDER = "MOVE_OR_REORDER"
    DELETE = "DELETE"
    NO_CHANGE = "NO_CHANGE"


@dataclass(frozen=True, slots=True)
class DiffEntry:
    action: DiffAction
    node: DesiredNode
    before: FrozenJsonObject = field(default_factory=FrozenJsonObject)
    changed_fields: tuple[str, ...] = field(default_factory=tuple)


class ExecutionTarget(StrEnum):
    DISCORD = "DISCORD"


class OperationType(StrEnum):
    CREATE_ROLE = "CREATE_ROLE"
    UPDATE_ROLE = "UPDATE_ROLE"
    DELETE_ROLE = "DELETE_ROLE"
    REORDER_ROLES = "REORDER_ROLES"
    CREATE_CHANNEL = "CREATE_CHANNEL"
    UPDATE_CHANNEL = "UPDATE_CHANNEL"
    MOVE_OR_REORDER_CHANNELS = "MOVE_OR_REORDER_CHANNELS"
    DELETE_CHANNEL = "DELETE_CHANNEL"
    UPSERT_OVERWRITE = "UPSERT_OVERWRITE"
    DELETE_OVERWRITE = "DELETE_OVERWRITE"


class CompensationClass(StrEnum):
    REVERSIBLE = "REVERSIBLE"
    RECREATABLE_NOT_RESTORABLE = "RECREATABLE_NOT_RESTORABLE"
    NON_COMPENSABLE = "NON_COMPENSABLE"


class VerificationStrategy(StrEnum):
    TARGETED_GET = "TARGETED_GET"
    TARGETED_LIST_AND_MATCH = "TARGETED_LIST_AND_MATCH"
    ABSENCE_WITH_OBSERVABILITY = "ABSENCE_WITH_OBSERVABILITY"


class RecoveryStrategy(StrEnum):
    CREATE_RECONCILE = "CREATE_RECONCILE"
    UPDATE_COMPARE_BEFORE_DESIRED = "UPDATE_COMPARE_BEFORE_DESIRED"
    DELETE_PROVE_ABSENCE = "DELETE_PROVE_ABSENCE"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PlanState(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    STALE = "STALE"
    CONFIRMED = "CONFIRMED"
    APPLYING = "APPLYING"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    INTERVENTION_REQUIRED = "INTERVENTION_REQUIRED"


class OperationState(StrEnum):
    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    INTERVENTION_REQUIRED = "INTERVENTION_REQUIRED"
    CANCELLED = "CANCELLED"


class AttemptState(StrEnum):
    PREPARED = "PREPARED"
    IN_FLIGHT = "IN_FLIGHT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PlanOperation:
    operation_id: UUID
    operation_type: OperationType
    resource_type: ResourceType
    resource_ref: str
    desired_payload: FrozenJsonObject
    before_payload: FrozenJsonObject
    required_capabilities: tuple[str, ...]
    compensation: CompensationClass
    risk: RiskLevel
    verification: VerificationStrategy
    recovery: RecoveryStrategy
    expected_gateway_events: tuple[str, ...]
    predecessors: tuple[UUID, ...] = field(default_factory=tuple)
    produces_symbol: str | None = None
    consumes_symbols: tuple[str, ...] = field(default_factory=tuple)
    execution_target: ExecutionTarget = ExecutionTarget.DISCORD

    def __post_init__(self) -> None:
        if not self.resource_ref or len(self.resource_ref) > 256:
            raise ValueError("operation resource_ref must be present and bounded")
        if self.operation_id in self.predecessors:
            raise ValueError("operation cannot depend on itself")
        object.__setattr__(self, "predecessors", tuple(sorted(set(self.predecessors), key=str)))
        object.__setattr__(self, "consumes_symbols", tuple(sorted(set(self.consumes_symbols))))
        object.__setattr__(
            self,
            "required_capabilities",
            tuple(sorted(set(self.required_capabilities))),
        )
