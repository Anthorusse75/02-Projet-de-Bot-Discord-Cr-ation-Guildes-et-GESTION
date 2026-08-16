from datetime import UTC, datetime, timedelta

from did.application.reconciliation import AdaptiveReconcilePolicy, ReconcileSignals


def test_adaptive_reconcile_prioritizes_gap_and_uses_stable_jitter() -> None:
    now = datetime(2026, 8, 16, 12, tzinfo=UTC)
    policy = AdaptiveReconcilePolicy()
    healthy = ReconcileSignals(101, now - timedelta(hours=2), active=True)
    gap = ReconcileSignals(
        202,
        now - timedelta(minutes=1),
        active=False,
        gateway_gap=True,
        coverage_degraded=True,
    )
    assert policy.priority_score(gap, now=now) > policy.priority_score(healthy, now=now)
    assert policy.next_due_at(gap, now=now) == now
    assert policy.next_due_at(healthy, now=now) == policy.next_due_at(healthy, now=now)


def test_rate_limit_pressure_delays_background_without_hiding_critical_work() -> None:
    now = datetime(2026, 8, 16, 12, tzinfo=UTC)
    policy = AdaptiveReconcilePolicy(jitter_ratio=0)
    normal = ReconcileSignals(101, now, active=True)
    pressured = ReconcileSignals(101, now, active=True, rate_limit_pressure=1.0)
    assert policy.next_due_at(pressured, now=now) > policy.next_due_at(normal, now=now)
    non_resumed = ReconcileSignals(101, now, active=True, non_resumed=True, rate_limit_pressure=1.0)
    assert policy.next_due_at(non_resumed, now=now) == now
