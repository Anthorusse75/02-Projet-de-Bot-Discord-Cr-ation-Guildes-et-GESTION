import pytest

from did.infrastructure.runtime_metrics import RuntimeMetrics


def test_stage04_metrics_are_bounded_and_have_no_tenant_or_resource_labels() -> None:
    metrics = RuntimeMetrics()
    metrics.permission_evaluation(0.01, "COMPLETE")
    metrics.permission_evaluation(0.02, "INCOMPLETE")
    metrics.permission_evaluation(0.03, "UNKNOWN")
    metrics.targeted_actor_refresh()
    metrics.coverage_gap("PARTIAL")
    metrics.capability_check("CANNOT")
    metrics.scope_resolution("MATCH")

    snapshot = metrics.snapshot()
    assert snapshot["permission_evaluation_count"] == 3
    assert snapshot["permission_decision_incomplete"] == 1
    assert snapshot["permission_decision_unknown"] == 1
    assert snapshot["targeted_actor_refresh"] == 1
    assert snapshot["coverage_gap"] == {"PARTIAL": 1}
    assert snapshot["capability_check_outcome"] == {"CANNOT": 1}
    assert snapshot["scope_resolution_outcome"] == {"MATCH": 1}
    assert not {"guild_id", "channel_id", "role_id", "user_id"}.intersection(snapshot)


@pytest.mark.parametrize(
    ("method", "value"),
    [
        ("permission", "NOT_A_STATUS"),
        ("coverage", "guild-123"),
        ("capability", "MAYBE"),
        ("scope", "user-456"),
    ],
)
def test_stage04_metrics_reject_unbounded_or_unknown_label_values(method: str, value: str) -> None:
    metrics = RuntimeMetrics()
    with pytest.raises(ValueError):
        if method == "permission":
            metrics.permission_evaluation(0.1, value)
        elif method == "coverage":
            metrics.coverage_gap(value)
        elif method == "capability":
            metrics.capability_check(value)
        else:
            metrics.scope_resolution(value)
