from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Final

from did.domain.discord_runtime import FreshnessState, WorkloadPriority

REST_OUTCOMES: Final = frozenset(
    {"success", "unauthorized", "forbidden", "not_found", "rate_limited", "transient", "invalid"}
)
GATEWAY_SIGNALS: Final = frozenset(
    {"dispatch", "duplicate", "rejected", "gap", "resumed", "non_resumed", "disconnected"}
)


@dataclass(slots=True)
class RuntimeMetrics:
    """In-process bounded telemetry; tenant/resource IDs are deliberately never labels."""

    gateway: Counter[str] = field(default_factory=Counter)
    rest_outcomes: Counter[str] = field(default_factory=Counter)
    jobs_by_priority: Counter[str] = field(default_factory=Counter)
    cache_freshness: Counter[str] = field(default_factory=Counter)
    redis_rebuilds: int = 0
    outbox_backlog: int = 0
    queue_depth: int = 0
    reconcile_age_seconds: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    rate_limit_wait_seconds: float = 0.0
    invalid_requests_10m: int = 0

    def gateway_signal(self, signal: str) -> None:
        if signal not in GATEWAY_SIGNALS:
            raise ValueError("Gateway metric signal is not from the bounded registry")
        self.gateway[signal] += 1

    def rest_outcome(self, outcome: str) -> None:
        if outcome not in REST_OUTCOMES:
            raise ValueError("REST outcome is not from the bounded registry")
        self.rest_outcomes[outcome] += 1

    def job_submitted(self, priority: WorkloadPriority) -> None:
        self.jobs_by_priority[priority.name] += 1

    def observe_freshness(self, state: FreshnessState) -> None:
        self.cache_freshness[state.value] += 1

    def snapshot(self) -> dict[str, object]:
        cache_total = self.cache_hits + self.cache_misses
        return {
            "gateway": dict(self.gateway),
            "rest_outcomes": dict(self.rest_outcomes),
            "jobs_by_priority": dict(self.jobs_by_priority),
            "cache_freshness": dict(self.cache_freshness),
            "redis_rebuilds": self.redis_rebuilds,
            "outbox_backlog": self.outbox_backlog,
            "queue_depth": self.queue_depth,
            "reconcile_age_seconds": self.reconcile_age_seconds,
            "cache_hit_ratio": self.cache_hits / cache_total if cache_total else 0.0,
            "rate_limit_wait_seconds": self.rate_limit_wait_seconds,
            "invalid_requests_10m": self.invalid_requests_10m,
        }
