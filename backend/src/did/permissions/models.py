from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from did.domain.discord_runtime import CoverageMode, FreshnessState


class DecisionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class PermissionOutcome(StrEnum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"


class TraceStep(StrEnum):
    BASE_EVERYONE = "BASE_EVERYONE"
    BASE_ROLE = "BASE_ROLE"
    BASE_ROLES_OR = "BASE_ROLES_OR"
    OWNER_BYPASS = "OWNER_BYPASS"
    ADMINISTRATOR_BYPASS = "ADMINISTRATOR_BYPASS"
    EVERYONE_OVERWRITE_DENY = "EVERYONE_OVERWRITE_DENY"
    EVERYONE_OVERWRITE_ALLOW = "EVERYONE_OVERWRITE_ALLOW"
    ROLE_OVERWRITES_DENY_AGGREGATE = "ROLE_OVERWRITES_DENY_AGGREGATE"
    ROLE_OVERWRITES_ALLOW_AGGREGATE = "ROLE_OVERWRITES_ALLOW_AGGREGATE"
    MEMBER_OVERWRITE_DENY = "MEMBER_OVERWRITE_DENY"
    MEMBER_OVERWRITE_ALLOW = "MEMBER_OVERWRITE_ALLOW"
    THREAD_INHERITANCE = "THREAD_INHERITANCE"
    IMPLICIT_DENIAL = "IMPLICIT_DENIAL"
    COVERAGE_INCOMPLETE = "COVERAGE_INCOMPLETE"


@dataclass(frozen=True, slots=True)
class PermissionTraceEntry:
    step: TraceStep
    source_type: str
    source_id: int | None
    allow_bits: int
    deny_bits: int
    before: int
    after: int
    reason_key: str


@dataclass(frozen=True, slots=True)
class ImplicitDenial:
    denied_bits: int
    missing_permission: str
    reason_key: str


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    guild_id: int
    subject_id: int
    resource_id: int | None
    calculated_bits: int
    effective_bits: int
    unknown_bits: int
    status: DecisionStatus
    requested_permission: str | None
    outcome: PermissionOutcome
    coverage: CoverageMode
    freshness: FreshnessState
    incomplete_reasons: tuple[str, ...] = field(default_factory=tuple)
    trace: tuple[PermissionTraceEntry, ...] = field(default_factory=tuple)
    implicit_denials: tuple[ImplicitDenial, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    source_versions: tuple[str, ...] = field(default_factory=tuple)
    registry_version: str = ""
    data_assertion: str = "CURRENT_CONFIRMED"

    def __post_init__(self) -> None:
        if min(self.guild_id, self.subject_id) <= 0:
            raise ValueError("Discord identifiers must be positive")
        if min(self.calculated_bits, self.effective_bits, self.unknown_bits) < 0:
            raise ValueError("permission bitfields cannot be negative")
        if self.status is not DecisionStatus.COMPLETE and self.outcome is PermissionOutcome.ALLOWED:
            raise ValueError("an incomplete permission decision cannot claim ALLOWED")

    def has(self, bit: int) -> bool:
        return self.status is DecisionStatus.COMPLETE and (self.effective_bits & bit) == bit
