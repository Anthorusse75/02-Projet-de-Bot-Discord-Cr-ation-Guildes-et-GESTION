from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from did.domain.discord_runtime import FreshnessState
from did.domain.read_model import MemberSnapshot


class ScopeType(StrEnum):
    GLOBAL = "GLOBAL"
    LOGICAL_GROUP = "LOGICAL_GROUP"
    STAFF = "STAFF"
    PROJECT = "PROJECT"
    CUSTOM = "CUSTOM"


class MembershipRuleType(StrEnum):
    DISCORD_ROLE = "DISCORD_ROLE"
    ANY_DISCORD_ROLE = "ANY_DISCORD_ROLE"
    ALL_DISCORD_ROLES = "ALL_DISCORD_ROLES"
    EXPLICIT_DID_MEMBERSHIP = "EXPLICIT_DID_MEMBERSHIP"
    CUSTOM = "CUSTOM"


class MembershipOutcome(StrEnum):
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class VisibilityScope:
    id: UUID
    guild_id: int
    scope_type: ScopeType
    scope_key: str
    name: str
    logical_group_id: UUID | None = None
    config: dict[str, Any] = field(default_factory=dict)
    version: int = 1

    def __post_init__(self) -> None:
        if self.guild_id <= 0 or self.version <= 0:
            raise ValueError("scope guild and version must be positive")
        if not self.scope_key or len(self.scope_key) > 128:
            raise ValueError("scope_key must be present and bounded")
        if (self.scope_type is ScopeType.LOGICAL_GROUP) != (self.logical_group_id is not None):
            raise ValueError(
                "logical_group_id is required only for LOGICAL_GROUP visibility scopes"
            )


@dataclass(frozen=True, slots=True)
class ScopeMembershipRule:
    id: UUID
    guild_id: int
    visibility_scope_id: UUID
    rule_type: MembershipRuleType
    config: dict[str, Any]
    priority: int
    status: str = "ACTIVE"
    version: int = 1

    def __post_init__(self) -> None:
        if self.guild_id <= 0 or self.version <= 0:
            raise ValueError("rule guild and version must be positive")
        if self.priority < 0:
            raise ValueError("rule priority cannot be negative")


@dataclass(frozen=True, slots=True)
class MembershipTraceEntry:
    rule_id: UUID
    rule_type: MembershipRuleType
    outcome: MembershipOutcome
    reason_key: str


@dataclass(frozen=True, slots=True)
class MembershipDecision:
    guild_id: int
    visibility_scope_id: UUID
    subject_id: int
    outcome: MembershipOutcome
    trace: tuple[MembershipTraceEntry, ...]
    diagnostics: tuple[str, ...]
    freshness: FreshnessState
    cache_version: str


class ScopeMembershipResolver:
    """Central, deterministic and non-executable membership rule resolver."""

    def resolve(
        self,
        *,
        scope: VisibilityScope,
        member: MemberSnapshot,
        rules: tuple[ScopeMembershipRule, ...],
        explicit_member_ids: frozenset[int] = frozenset(),
        explicit_memberships_complete: bool = True,
    ) -> MembershipDecision:
        if member.guild_id != scope.guild_id or any(
            rule.guild_id != scope.guild_id or rule.visibility_scope_id != scope.id
            for rule in rules
        ):
            raise ValueError("scope membership input crosses a tenant boundary")
        trace: list[MembershipTraceEntry] = []
        diagnostics: list[str] = []
        saw_unknown = False
        active_rules = sorted(
            (rule for rule in rules if rule.status == "ACTIVE"),
            key=lambda rule: (rule.priority, str(rule.id)),
        )
        for rule in active_rules:
            outcome, reason = self._evaluate_rule(
                rule,
                member=member,
                explicit_member_ids=explicit_member_ids,
                explicit_memberships_complete=explicit_memberships_complete,
            )
            trace.append(MembershipTraceEntry(rule.id, rule.rule_type, outcome, reason))
            if outcome is MembershipOutcome.MATCH:
                final = MembershipOutcome.MATCH
                break
            if outcome is MembershipOutcome.UNKNOWN:
                saw_unknown = True
                diagnostics.append(reason)
        else:
            final = MembershipOutcome.UNKNOWN if saw_unknown else MembershipOutcome.NO_MATCH
        versions = ":".join(
            [str(scope.version), str(member.freshness.state_version)]
            + [f"{rule.id}:{rule.version}" for rule in active_rules]
        )
        return MembershipDecision(
            scope.guild_id,
            scope.id,
            member.user_id,
            final,
            tuple(trace),
            tuple(dict.fromkeys(diagnostics)),
            member.freshness.state,
            versions,
        )

    @staticmethod
    def _role_ids(rule: ScopeMembershipRule) -> tuple[int, ...] | None:
        raw = rule.config.get("role_ids")
        if not isinstance(raw, list) or not raw:
            return None
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in raw
        ):
            return None
        values = tuple(raw)
        return values if len(values) == len(set(values)) else None

    def _evaluate_rule(
        self,
        rule: ScopeMembershipRule,
        *,
        member: MemberSnapshot,
        explicit_member_ids: frozenset[int],
        explicit_memberships_complete: bool,
    ) -> tuple[MembershipOutcome, str]:
        if rule.rule_type is MembershipRuleType.CUSTOM:
            return MembershipOutcome.UNKNOWN, "scopes.custom_rule_not_supported"
        if rule.rule_type is MembershipRuleType.EXPLICIT_DID_MEMBERSHIP:
            if not explicit_memberships_complete:
                return MembershipOutcome.UNKNOWN, "scopes.explicit_membership_incomplete"
            return (
                MembershipOutcome.MATCH
                if member.user_id in explicit_member_ids
                else MembershipOutcome.NO_MATCH,
                "scopes.explicit_membership",
            )
        role_ids = self._role_ids(rule)
        if role_ids is None:
            return MembershipOutcome.UNKNOWN, "scopes.role_rule_invalid"
        if not member.roles_complete:
            return MembershipOutcome.UNKNOWN, "scopes.member_roles_incomplete"
        if member.freshness.state in {FreshnessState.STALE, FreshnessState.UNKNOWN}:
            return MembershipOutcome.UNKNOWN, "scopes.member_roles_not_current"
        member_roles = set(member.role_ids)
        if rule.rule_type is MembershipRuleType.DISCORD_ROLE:
            matched = role_ids[0] in member_roles and len(role_ids) == 1
        elif rule.rule_type is MembershipRuleType.ANY_DISCORD_ROLE:
            matched = bool(member_roles.intersection(role_ids))
        else:
            matched = set(role_ids).issubset(member_roles)
        return (
            MembershipOutcome.MATCH if matched else MembershipOutcome.NO_MATCH,
            "scopes.discord_role_rule",
        )
