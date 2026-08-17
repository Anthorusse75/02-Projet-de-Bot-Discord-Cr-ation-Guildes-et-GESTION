import pytest

from did.domain.discord_runtime import FreshnessState, WorkloadPriority
from did.infrastructure.runtime_metrics import RuntimeMetrics


def test_runtime_metrics_use_only_bounded_dimensions() -> None:
    metrics = RuntimeMetrics()
    metrics.gateway_signal("gap")
    metrics.gateway_signal("duplicate")
    metrics.rest_outcome("rate_limited")
    metrics.job_submitted(WorkloadPriority.USER_REFRESH)
    metrics.observe_freshness(FreshnessState.AGING)
    metrics.cache_hits = 3
    metrics.cache_misses = 1
    metrics.rate_limit_wait_seconds = 1.5
    metrics.invalid_requests_10m = 2
    snapshot = metrics.snapshot()
    assert snapshot["gateway"] == {"gap": 1, "duplicate": 1}
    assert snapshot["rest_outcomes"] == {"rate_limited": 1}
    assert snapshot["jobs_by_priority"] == {"USER_REFRESH": 1}
    assert snapshot["cache_hit_ratio"] == 0.75
    assert snapshot["rate_limit_wait_seconds"] == 1.5
    assert snapshot["invalid_requests_10m"] == 2
    serialized = str(snapshot)
    assert "guild_id" not in serialized
    assert "channel_id" not in serialized
    assert "user_id" not in serialized


@pytest.mark.parametrize(
    ("method", "value"),
    [("gateway_signal", "guild-123"), ("rest_outcome", "route-/channels/123")],
)
def test_unbounded_metric_labels_are_rejected(method: str, value: str) -> None:
    metrics = RuntimeMetrics()
    with pytest.raises(ValueError, match="bounded registry"):
        getattr(metrics, method)(value)
