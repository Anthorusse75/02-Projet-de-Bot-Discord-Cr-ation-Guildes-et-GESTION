"""Closed, versioned schemas for declarative Policy definitions.

The registry validates data only.  It neither evaluates expressions nor accepts
callbacks, source code, SQL or user-provided operators.  A future resolver can
consume the normalized models without changing the persistence contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from did.domain.policies import PolicyScopeType


class PolicyDefinitionValidationError(ValueError):
    """A Policy type, scope, condition, effect or metadata contract is invalid."""


class _ClosedModel(BaseModel):
    # JSON arrays are intentionally accepted for tuple fields; scalar fields stay
    # closed and explicitly typed, while the normalized result is immutable.
    model_config = ConfigDict(extra="forbid", frozen=True)


class AlwaysCondition(_ClosedModel):
    kind: Literal["ALWAYS"]


class RoleMatchCondition(_ClosedModel):
    kind: Literal["ROLE_MATCH"]
    match: Literal["ANY", "ALL"]
    role_ids: tuple[str, ...] = Field(min_length=1, max_length=100)

    @field_validator("role_ids")
    @classmethod
    def positive_unique_snowflakes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("role_ids must be unique")
        if any(not value.isascii() or not value.isdigit() or int(value) <= 0 for value in values):
            raise ValueError("role_ids must contain positive decimal Discord IDs")
        return values


class SubjectKindCondition(_ClosedModel):
    kind: Literal["SUBJECT_KIND"]
    subject_kind: Literal["MEMBER", "BOT"]


PolicyCondition = Annotated[
    AlwaysCondition | RoleMatchCondition | SubjectKindCondition,
    Field(discriminator="kind"),
]


class SetAccessEffect(_ClosedModel):
    kind: Literal["SET_ACCESS"]
    access: Literal["VIEW", "WRITE", "MANAGE", "CONNECT", "SPEAK"]
    decision: Literal["ALLOW", "DENY"]


PolicyEffect = SetAccessEffect


class AccessPolicyMetadata(_ClosedModel):
    summary: str = Field(min_length=1, max_length=300)
    tags: tuple[str, ...] = Field(default=(), max_length=20)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("summary")
    @classmethod
    def summary_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be blank")
        return value.strip()

    @field_validator("tags")
    @classmethod
    def tags_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value or len(value) > 64 for value in normalized):
            raise ValueError("tags must be non-empty and at most 64 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("tags must be unique")
        return normalized


@dataclass(frozen=True, slots=True)
class PolicyReference:
    scope_type: PolicyScopeType
    scope_id: str


@dataclass(frozen=True, slots=True)
class ValidatedPolicyDefinition:
    conditions: tuple[dict[str, object], ...]
    effects: tuple[dict[str, object], ...]
    metadata: dict[str, object]
    references: tuple[PolicyReference, ...]


@dataclass(frozen=True, slots=True)
class PolicyTypeContract:
    type_id: str
    contract_version: int
    allowed_scopes: frozenset[PolicyScopeType]
    condition_adapter: TypeAdapter[tuple[PolicyCondition, ...]]
    effect_adapter: TypeAdapter[tuple[PolicyEffect, ...]]
    metadata_adapter: TypeAdapter[AccessPolicyMetadata]

    def validate(
        self,
        *,
        scope_type: PolicyScopeType,
        conditions: object,
        effects: object,
        metadata: object,
    ) -> ValidatedPolicyDefinition:
        if scope_type not in self.allowed_scopes:
            raise PolicyDefinitionValidationError(
                f"scope {scope_type.value} is not supported by "
                f"{self.type_id} v{self.contract_version}"
            )
        try:
            parsed_conditions = self.condition_adapter.validate_python(conditions)
            parsed_effects = self.effect_adapter.validate_python(effects)
            parsed_metadata = self.metadata_adapter.validate_python(metadata)
        except ValueError as exc:
            raise PolicyDefinitionValidationError(str(exc)) from exc
        if not parsed_effects:
            raise PolicyDefinitionValidationError("a Policy requires at least one effect")
        references: list[PolicyReference] = []
        for condition in parsed_conditions:
            if isinstance(condition, RoleMatchCondition):
                references.extend(
                    PolicyReference(PolicyScopeType.ROLE, role_id) for role_id in condition.role_ids
                )
        return ValidatedPolicyDefinition(
            conditions=tuple(item.model_dump(mode="json") for item in parsed_conditions),
            effects=tuple(item.model_dump(mode="json") for item in parsed_effects),
            metadata=parsed_metadata.model_dump(mode="json"),
            references=tuple(references),
        )


class PolicyTypeRegistry:
    def __init__(self, contracts: tuple[PolicyTypeContract, ...]) -> None:
        indexed = {
            (contract.type_id, contract.contract_version): contract for contract in contracts
        }
        if len(indexed) != len(contracts):
            raise ValueError("duplicate Policy type contract")
        self._contracts = indexed

    def get(self, policy_type: str, contract_version: int) -> PolicyTypeContract:
        try:
            return self._contracts[(policy_type, contract_version)]
        except KeyError as exc:
            raise PolicyDefinitionValidationError(
                f"unknown Policy type contract: {policy_type} v{contract_version}"
            ) from exc

    def validate(
        self,
        *,
        policy_type: str,
        contract_version: int,
        scope_type: PolicyScopeType,
        conditions: object,
        effects: object,
        metadata: object,
    ) -> ValidatedPolicyDefinition:
        return self.get(policy_type, contract_version).validate(
            scope_type=scope_type,
            conditions=conditions,
            effects=effects,
            metadata=metadata,
        )


_ACCESS_SCOPES = frozenset(
    {
        PolicyScopeType.GUILD,
        PolicyScopeType.LOGICAL_GROUP,
        PolicyScopeType.CATEGORY,
        PolicyScopeType.CHANNEL,
        PolicyScopeType.ROLE,
        PolicyScopeType.MEMBER,
        PolicyScopeType.BOT,
    }
)

POLICY_TYPE_REGISTRY = PolicyTypeRegistry(
    (
        PolicyTypeContract(
            type_id="ACCESS_CONTROL",
            contract_version=1,
            allowed_scopes=_ACCESS_SCOPES,
            condition_adapter=TypeAdapter(
                Annotated[tuple[PolicyCondition, ...], Field(max_length=100)]
            ),
            effect_adapter=TypeAdapter(
                Annotated[tuple[PolicyEffect, ...], Field(min_length=1, max_length=100)]
            ),
            metadata_adapter=TypeAdapter(AccessPolicyMetadata),
        ),
    )
)
