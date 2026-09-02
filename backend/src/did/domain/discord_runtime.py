from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any
from uuid import UUID

CHANNEL_OBFUSCATED_FLAG = 1 << 17
CHANNEL_OBFUSCATION_GATEWAY_CAPABILITY = 1 << 15


class EventSource(StrEnum):
    GATEWAY = "GATEWAY"
    MUTATION_WRITE_THROUGH = "MUTATION_WRITE_THROUGH"
    TARGETED_REST = "TARGETED_REST"
    RECONCILE = "RECONCILE"
    SYSTEM = "SYSTEM"


class EventOrigin(StrEnum):
    DISCORD_EXTERNAL = "DISCORD_EXTERNAL"
    DID_PLAN = "DID_PLAN"
    DID_CAMPAIGN = "DID_CAMPAIGN"
    DID_TRANSLATION = "DID_TRANSLATION"
    SYSTEM = "SYSTEM"


class ObservabilityState(StrEnum):
    VISIBLE = "VISIBLE"
    OBFUSCATED = "OBFUSCATED"
    ACCESS_LOST = "ACCESS_LOST"
    UNKNOWN = "UNKNOWN"
    DELETED_CONFIRMED = "DELETED_CONFIRMED"
    USER_CONFIRMED_DELETED = "USER_CONFIRMED_DELETED"


class TombstoneState(StrEnum):
    PURGED_TOMBSTONE = "PURGED_TOMBSTONE"


class FreshnessState(StrEnum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class CoverageMode(StrEnum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"


class MemberDataCapability(StrEnum):
    FULL_MEMBER_EVENTS = "FULL_MEMBER_EVENTS"
    ON_DEMAND_MEMBER_LOOKUP = "ON_DEMAND_MEMBER_LOOKUP"
    DEGRADED_NO_PRIVILEGED_INTENT = "DEGRADED_NO_PRIVILEGED_INTENT"


class GatewayContinuity(StrEnum):
    CONNECTED = "CONNECTED"
    RESUMED = "RESUMED"
    GAP_DETECTED = "GAP_DETECTED"
    NON_RESUMED = "NON_RESUMED"
    DISCONNECTED = "DISCONNECTED"


class WorkloadPriority(IntEnum):
    APPLY_CONTINUATION = 0
    UNKNOWN_OUTCOME_RECOVERY = 1
    CRITICAL_PREFLIGHT = 2
    USER_REFRESH = 3
    BACKGROUND_RECONCILE = 4
    LOW_MAINTENANCE = 5
    #: Stage 09 campaign message sends (WP13). Deliberately the lowest
    #: (least urgent) tier of all -- appended after LOW_MAINTENANCE rather
    #: than interleaved with the existing values so no prior comparison
    #: anywhere in the codebase changes meaning. Bulk campaign fan-out must
    #: never preempt structural apply, critical reconcile, or any other
    #: Stage's higher-priority Discord workload; per-Guild dispatch
    #: fairness across campaigns/other Guilds is still fully provided by
    #: DiscordWorkloadGovernor's own round-robin, independent of this tier.
    SEND_CAMPAIGN_MESSAGE = 6


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: UUID
    guild_id: int
    event_type: str
    discord_sequence: int | None
    discord_session_id: str
    occurred_at: datetime | None
    received_at: datetime
    correlation_id: UUID
    causation_id: UUID | None
    schema_version: int
    payload: dict[str, Any]
    source: EventSource
    origin: EventOrigin = EventOrigin.DISCORD_EXTERNAL
    causation_depth: int = 0

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if not self.event_type or len(self.event_type) > 128:
            raise ValueError("event_type must be present and bounded")
        if not self.discord_session_id or len(self.discord_session_id) > 256:
            raise ValueError("discord_session_id must be present and bounded")
        if self.discord_sequence is not None and self.discord_sequence < 0:
            raise ValueError("discord_sequence cannot be negative")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        if self.causation_depth < 0 or self.causation_depth > 32:
            raise ValueError("causation_depth must be between 0 and 32")
        if self.received_at.tzinfo is None:
            raise ValueError("received_at must be timezone-aware")
        if self.occurred_at is not None and self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")

    @property
    def deduplication_key(self) -> str:
        sequence = "none" if self.discord_sequence is None else str(self.discord_sequence)
        return f"{self.discord_session_id}:{sequence}:{self.event_type}"


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    fresh_for: timedelta
    aging_for: timedelta

    def __post_init__(self) -> None:
        if self.fresh_for <= timedelta(0):
            raise ValueError("fresh_for must be positive")
        if self.aging_for <= self.fresh_for:
            raise ValueError("aging_for must be greater than fresh_for")

    def classify(
        self, observed_at: datetime | None, *, now: datetime | None = None
    ) -> FreshnessState:
        if observed_at is None:
            return FreshnessState.UNKNOWN
        reference = now or datetime.now(UTC)
        age = reference - observed_at
        if age <= self.fresh_for:
            return FreshnessState.FRESH
        if age <= self.aging_for:
            return FreshnessState.AGING
        return FreshnessState.STALE


@dataclass(frozen=True, slots=True)
class DiscordChannelObservation:
    guild_id: int
    channel_id: int
    channel_type: int
    position: int
    parent_id: int | None
    name: str | None
    topic: str | None
    nsfw: bool | None
    flags: int
    permission_overwrites: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def is_obfuscated(self) -> bool:
        return bool(self.flags & CHANNEL_OBFUSCATED_FLAG)


@dataclass(frozen=True, slots=True)
class WorkloadJob:
    job_id: UUID
    guild_id: int
    workload_type: str
    logical_key: str
    priority: WorkloadPriority
    enqueued_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if not self.workload_type or len(self.workload_type) > 64:
            raise ValueError("workload_type must be present and bounded")
        if not self.logical_key or len(self.logical_key) > 256:
            raise ValueError("logical_key must be present and bounded")
        if self.enqueued_at.tzinfo is None:
            raise ValueError("enqueued_at must be timezone-aware")


class DiscordErrorKind(StrEnum):
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT = "TRANSIENT"
    INVALID_REQUEST = "INVALID_REQUEST"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    CONTRACT_ERROR = "CONTRACT_ERROR"


@dataclass(frozen=True, slots=True)
class DiscordFailure:
    kind: DiscordErrorKind
    status_code: int | None
    retry_after_seconds: float | None = None
    global_rate_limit: bool = False
    error_code: int | None = None
    rate_limit_scope: str | None = None

    @property
    def retryable(self) -> bool:
        return self.kind in {DiscordErrorKind.RATE_LIMITED, DiscordErrorKind.TRANSIENT}

    @property
    def counts_toward_invalid_request_limit(self) -> bool:
        return self.kind in {DiscordErrorKind.UNAUTHORIZED, DiscordErrorKind.FORBIDDEN} or (
            self.kind is DiscordErrorKind.RATE_LIMITED and self.rate_limit_scope != "shared"
        )


DEFAULT_FRESHNESS_POLICIES: dict[str, FreshnessPolicy] = {
    "channels": FreshnessPolicy(timedelta(minutes=15), timedelta(hours=6)),
    "roles": FreshnessPolicy(timedelta(minutes=15), timedelta(hours=6)),
    "coverage": FreshnessPolicy(timedelta(hours=1), timedelta(hours=24)),
}
