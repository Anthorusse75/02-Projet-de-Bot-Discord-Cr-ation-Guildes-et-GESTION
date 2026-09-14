"""Generic Policy aggregate and lifecycle primitives.

This module deliberately contains no resolver and no Discord mutation logic.  It
models the durable, tenant-scoped declaration that later Phase 4 lots will
resolve and compile through the existing Plan Engine.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class PolicyLifecycleState(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    RETIRED = "RETIRED"


class PolicyScopeType(StrEnum):
    GUILD = "GUILD"
    LOGICAL_GROUP = "LOGICAL_GROUP"
    CATEGORY = "CATEGORY"
    CHANNEL = "CHANNEL"
    ROLE = "ROLE"
    MEMBER = "MEMBER"
    BOT = "BOT"
    CAMPAIGN = "CAMPAIGN"
    TEMPLATE = "TEMPLATE"


class PolicyLifecycleError(ValueError):
    """Raised when a Policy lifecycle transition is not allowed."""


_ALLOWED_TRANSITIONS: dict[PolicyLifecycleState, frozenset[PolicyLifecycleState]] = {
    PolicyLifecycleState.DRAFT: frozenset({PolicyLifecycleState.ACTIVE}),
    PolicyLifecycleState.ACTIVE: frozenset({PolicyLifecycleState.DISABLED}),
    PolicyLifecycleState.DISABLED: frozenset({PolicyLifecycleState.RETIRED}),
    PolicyLifecycleState.RETIRED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class Policy:
    policy_id: UUID
    guild_id: int
    policy_type: str
    contract_version: int
    name: str
    description: str
    lifecycle_state: PolicyLifecycleState
    revision: int
    scope_type: PolicyScopeType
    scope_id: str | None
    conditions: tuple[dict[str, object], ...]
    effects: tuple[dict[str, object], ...]
    metadata: dict[str, object]
    created_by_user_id: int
    modified_by_user_id: int
    priority: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    activated_at: datetime | None = None
    disabled_at: datetime | None = None
    retired_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if self.created_by_user_id <= 0 or self.modified_by_user_id <= 0:
            raise ValueError("Policy authors must be positive Discord user IDs")
        if not self.policy_type.strip():
            raise ValueError("policy_type must not be blank")
        if self.contract_version <= 0 or self.revision <= 0:
            raise ValueError("Policy contract version and revision must be positive")
        if isinstance(self.priority, bool) or not -1_000_000 <= self.priority <= 1_000_000:
            raise ValueError("Policy priority must be an integer between -1000000 and 1000000")
        if not self.name.strip():
            raise ValueError("Policy name must not be blank")
        if self.name != self.name.strip():
            raise ValueError("Policy name cannot contain surrounding whitespace")
        if self.scope_type is PolicyScopeType.GUILD:
            if self.scope_id is not None:
                raise ValueError("GUILD Policy scope_id must be null")
        elif self.scope_id is None or not self.scope_id.strip():
            raise ValueError("non-GUILD Policy scope_id must be explicit")

    def transition_to(self, target: PolicyLifecycleState) -> Policy:
        if target not in _ALLOWED_TRANSITIONS[self.lifecycle_state]:
            raise PolicyLifecycleError(
                f"cannot transition Policy from {self.lifecycle_state.value} to {target.value}"
            )
        return replace(self, lifecycle_state=target, revision=self.revision + 1)


@dataclass(frozen=True, slots=True)
class PolicyVersion:
    version_id: UUID
    guild_id: int
    policy_id: UUID
    revision: int
    change_kind: str
    snapshot: dict[str, object]
    author_user_id: int
    correlation_id: UUID
    idempotency_key: str | None
    created_at: datetime
