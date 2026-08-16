import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from did.application.reconciliation import AdaptiveReconcilePolicy, ReconcileSignals
from did.domain.discord_runtime import WorkloadJob, WorkloadPriority
from did.worker.io import BackpressureError, DiscordWorkloadGovernor

pytestmark = pytest.mark.load

GUILD_A = 530303030303030301
GUILD_B = 530303030303030302


def workload(guild_id: int, logical_key: str) -> WorkloadJob:
    return WorkloadJob(
        uuid4(),
        guild_id,
        "LOAD_PROBE",
        logical_key,
        WorkloadPriority.BACKGROUND_RECONCILE,
        datetime.now(UTC),
    )


def write_report(report: dict[str, object]) -> None:
    destination = os.environ.get("DID_LOAD_REPORT")
    if destination is None:
        return
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


async def test_noisy_guild_is_bounded_and_quiet_guild_progress_is_measured() -> None:
    governor = DiscordWorkloadGovernor(
        global_concurrency=4,
        per_guild_concurrency=1,
        max_queue_depth=1_000,
    )

    async def complete(value: str) -> str:
        await asyncio.sleep(0)
        return value

    futures = [
        governor.submit(
            workload(GUILD_A, f"a-{index}"),
            lambda index=index: complete(f"a-{index}"),
        )
        for index in range(500)
    ]
    quiet = [
        governor.submit(
            workload(GUILD_B, f"b-{index}"),
            lambda index=index: complete(f"b-{index}"),
        )
        for index in range(20)
    ]
    coalesced = [
        governor.submit(workload(GUILD_B, "shared"), lambda: complete("shared")) for _ in range(3)
    ]
    await governor.drain()
    fairness = governor.fairness_report(GUILD_A, GUILD_B)
    report: dict[str, object] = {
        "scenario": "stage03-deterministic-noisy-a-quiet-b",
        "guild_a_jobs": len(futures),
        "guild_b_jobs": len(quiet) + 1,
        "first_b_slot": fairness["first_b_slot"],
        "a_dispatches_before_b": fairness["a_dispatches_before_b"],
        "fairness_bound_slots": fairness["fairness_bound_slots"],
        "b_progressed_within_bound": fairness["b_progressed_within_bound"],
        "peak_backlog": governor.metrics.peak_queue_depth,
        "peak_global_concurrency": governor.metrics.peak_global_concurrency,
        "peak_guild_concurrency": governor.metrics.peak_guild_concurrency,
        "coalesced_requests": governor.metrics.coalesced,
        "completed": governor.metrics.completed,
    }
    write_report(report)
    assert fairness["b_progressed_within_bound"] is True
    assert fairness["first_b_slot"] == 1
    assert fairness["a_dispatches_before_b"] == 1
    assert governor.metrics.peak_queue_depth == 521
    assert governor.metrics.peak_global_concurrency == 2
    assert governor.metrics.peak_guild_concurrency == 1
    assert governor.metrics.coalesced == 2
    assert await asyncio.gather(*coalesced) == ["shared"] * 3
    assert all(future.done() for future in futures + quiet)


async def test_load_backpressure_is_bounded_and_measured() -> None:
    governor = DiscordWorkloadGovernor(global_concurrency=2, max_queue_depth=20)

    async def complete() -> None:
        await asyncio.sleep(0)

    for index in range(20):
        governor.submit(workload(GUILD_A, f"bounded-{index}"), complete)
    with pytest.raises(BackpressureError):
        governor.submit(workload(GUILD_B, "rejected"), complete)
    assert governor.queue_depth == 20
    assert governor.background_paused is True
    assert governor.metrics.rejected_backpressure == 1
    await governor.drain()


def test_rate_pressure_delays_background_reconcile_in_load_profile() -> None:
    now = datetime.now(UTC)
    policy = AdaptiveReconcilePolicy(jitter_ratio=0)
    normal = ReconcileSignals(GUILD_A, now, active=True)
    pressured = ReconcileSignals(GUILD_A, now, active=True, rate_limit_pressure=1.0)
    assert policy.next_due_at(pressured, now=now) > policy.next_due_at(normal, now=now)
