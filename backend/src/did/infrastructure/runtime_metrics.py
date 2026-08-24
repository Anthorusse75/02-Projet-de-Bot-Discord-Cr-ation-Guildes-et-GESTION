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
PERMISSION_DECISIONS: Final = frozenset({"COMPLETE", "INCOMPLETE", "UNKNOWN"})
CAPABILITY_OUTCOMES: Final = frozenset({"CAN", "CANNOT", "UNKNOWN"})
SCOPE_OUTCOMES: Final = frozenset({"MATCH", "NO_MATCH", "UNKNOWN"})


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
    permission_evaluation_duration_seconds: float = 0.0
    permission_evaluation_count: int = 0
    permission_decisions: Counter[str] = field(default_factory=Counter)
    targeted_actor_refreshes: int = 0
    coverage_gaps: Counter[str] = field(default_factory=Counter)
    capability_check_outcomes: Counter[str] = field(default_factory=Counter)
    scope_resolution_outcomes: Counter[str] = field(default_factory=Counter)
    artifact_build_duration_seconds: float = 0.0
    artifact_build_count: int = 0
    artifact_size_bytes: int = 0
    artifact_import_outcomes: Counter[str] = field(default_factory=Counter)
    artifact_crypto_outcomes: Counter[str] = field(default_factory=Counter)
    mapping_outcomes: Counter[str] = field(default_factory=Counter)
    mapping_ambiguities: int = 0
    transfer_states: Counter[str] = field(default_factory=Counter)
    clone_modes: Counter[str] = field(default_factory=Counter)
    clone_report_outcomes: Counter[str] = field(default_factory=Counter)
    destination_plan_compiles: Counter[str] = field(default_factory=Counter)
    artifact_purges: int = 0
    quota_rejections: int = 0

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

    def permission_evaluation(self, duration_seconds: float, decision: str) -> None:
        if duration_seconds < 0 or decision not in PERMISSION_DECISIONS:
            raise ValueError("permission metric values are outside the bounded registry")
        self.permission_evaluation_duration_seconds += duration_seconds
        self.permission_evaluation_count += 1
        self.permission_decisions[decision] += 1

    def targeted_actor_refresh(self) -> None:
        self.targeted_actor_refreshes += 1

    def coverage_gap(self, mode: str) -> None:
        if mode not in {"PARTIAL", "DEGRADED", "STALE", "UNKNOWN", "OBFUSCATED"}:
            raise ValueError("coverage gap is outside the bounded registry")
        self.coverage_gaps[mode] += 1

    def capability_check(self, outcome: str) -> None:
        if outcome not in CAPABILITY_OUTCOMES:
            raise ValueError("capability outcome is outside the bounded registry")
        self.capability_check_outcomes[outcome] += 1

    def scope_resolution(self, outcome: str) -> None:
        if outcome not in SCOPE_OUTCOMES:
            raise ValueError("scope outcome is outside the bounded registry")
        self.scope_resolution_outcomes[outcome] += 1

    def artifact_built(self, duration_seconds: float, size_bytes: int) -> None:
        if duration_seconds < 0 or size_bytes <= 0:
            raise ValueError("artifact metric values are invalid")
        self.artifact_build_duration_seconds += duration_seconds
        self.artifact_build_count += 1
        self.artifact_size_bytes += size_bytes

    def portability_outcome(self, metric: str, outcome: str) -> None:
        registries = {
            "artifact_import": (self.artifact_import_outcomes, {"success", "rejected"}),
            "artifact_crypto": (
                self.artifact_crypto_outcomes,
                {"encrypt_success", "decrypt_success", "tamper", "key_unavailable"},
            ),
            "mapping": (
                self.mapping_outcomes,
                {"CREATE", "MAP_EXISTING", "SKIP", "UNSUPPORTED", "MANUAL"},
            ),
            "transfer_state": (
                self.transfer_states,
                {
                    "CREATED",
                    "SOURCE_AUTHORIZED",
                    "EXPORTED",
                    "MAPPING_REQUIRED",
                    "READY",
                    "COMPILED",
                    "FAILED",
                    "CANCELLED",
                },
            ),
            "clone_mode": (
                self.clone_modes,
                {"COPY_AS_NEW", "MERGE", "RECONCILE", "MAXIMUM_COMPATIBLE"},
            ),
            "clone_report": (
                self.clone_report_outcomes,
                {
                    "CLONED",
                    "CREATED",
                    "REMAPPED",
                    "SKIPPED",
                    "IMPOSSIBLE",
                    "INTERVENTION_REQUIRED",
                    "DELETE_CANDIDATE",
                },
            ),
            "destination_plan_compile": (
                self.destination_plan_compiles,
                {"created", "reused", "rejected"},
            ),
        }
        try:
            counter, allowed = registries[metric]
        except KeyError as exc:
            raise ValueError("unknown portability metric") from exc
        if outcome not in allowed:
            raise ValueError("portability outcome is outside the bounded registry")
        counter[outcome] += 1

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
            "permission_evaluation_duration_seconds": (self.permission_evaluation_duration_seconds),
            "permission_evaluation_count": self.permission_evaluation_count,
            "permission_decision_incomplete": self.permission_decisions["INCOMPLETE"],
            "permission_decision_unknown": self.permission_decisions["UNKNOWN"],
            "targeted_actor_refresh": self.targeted_actor_refreshes,
            "coverage_gap": dict(self.coverage_gaps),
            "capability_check_outcome": dict(self.capability_check_outcomes),
            "scope_resolution_outcome": dict(self.scope_resolution_outcomes),
            "artifact_build_duration_seconds": self.artifact_build_duration_seconds,
            "artifact_build_count": self.artifact_build_count,
            "artifact_size_bytes": self.artifact_size_bytes,
            "artifact_import_outcome": dict(self.artifact_import_outcomes),
            "artifact_crypto_outcome": dict(self.artifact_crypto_outcomes),
            "mapping_outcome": dict(self.mapping_outcomes),
            "mapping_ambiguity": self.mapping_ambiguities,
            "transfer_state": dict(self.transfer_states),
            "clone_mode": dict(self.clone_modes),
            "clone_report_outcome": dict(self.clone_report_outcomes),
            "destination_plan_compile": dict(self.destination_plan_compiles),
            "artifact_purge": self.artifact_purges,
            "quota_rejection": self.quota_rejections,
        }
