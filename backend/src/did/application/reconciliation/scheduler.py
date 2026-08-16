from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True, slots=True)
class ReconcileSignals:
    guild_id: int
    last_reconcile_at: datetime | None
    active: bool
    gateway_gap: bool = False
    non_resumed: bool = False
    pending_critical_work: bool = False
    drift_count: int = 0
    coverage_degraded: bool = False
    rate_limit_pressure: float = 0.0

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if self.drift_count < 0:
            raise ValueError("drift_count cannot be negative")
        if not 0.0 <= self.rate_limit_pressure <= 1.0:
            raise ValueError("rate_limit_pressure must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class AdaptiveReconcilePolicy:
    active_target: timedelta = timedelta(hours=6)
    inactive_target: timedelta = timedelta(hours=24)
    jitter_ratio: float = 0.15
    pressure_extension: timedelta = timedelta(hours=6)

    def __post_init__(self) -> None:
        if self.active_target <= timedelta(0) or self.inactive_target <= timedelta(0):
            raise ValueError("reconcile targets must be positive")
        if not 0 <= self.jitter_ratio <= 0.5:
            raise ValueError("jitter_ratio must be between 0 and 0.5")

    def priority_score(self, signals: ReconcileSignals, *, now: datetime | None = None) -> float:
        reference = now or datetime.now(UTC)
        target = self.active_target if signals.active else self.inactive_target
        if signals.last_reconcile_at is None:
            age_ratio = 2.0
        else:
            age_ratio = max(
                0.0,
                (reference - signals.last_reconcile_at).total_seconds() / target.total_seconds(),
            )
        score = age_ratio
        score += 5.0 if signals.gateway_gap or signals.non_resumed else 0.0
        score += 2.0 if signals.pending_critical_work else 0.0
        score += min(signals.drift_count, 10) * 0.2
        score += 1.0 if signals.coverage_degraded else 0.0
        score -= signals.rate_limit_pressure * 2.0
        return round(score, 6)

    def next_due_at(self, signals: ReconcileSignals, *, now: datetime | None = None) -> datetime:
        reference = now or datetime.now(UTC)
        if signals.gateway_gap or signals.non_resumed or signals.last_reconcile_at is None:
            return reference
        target = self.active_target if signals.active else self.inactive_target
        digest = hashlib.sha256(str(signals.guild_id).encode()).digest()
        unit = int.from_bytes(digest[:4], "big") / (2**32 - 1)
        signed_jitter = (unit * 2.0) - 1.0
        jitter = timedelta(seconds=target.total_seconds() * self.jitter_ratio * signed_jitter)
        pressure = self.pressure_extension * signals.rate_limit_pressure
        return signals.last_reconcile_at + target + jitter + pressure
