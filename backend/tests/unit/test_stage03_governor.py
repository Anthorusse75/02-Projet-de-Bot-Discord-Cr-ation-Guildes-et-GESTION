import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from did.domain.discord_runtime import (
    DiscordErrorKind,
    DiscordFailure,
    WorkloadJob,
    WorkloadPriority,
)
from did.worker.io.governor import (
    BackpressureError,
    DiscordWorkloadGovernor,
    WorkloadHaltedError,
)

GUILD_A = 101
GUILD_B = 202


def job(
    guild_id: int,
    logical_key: str,
    priority: WorkloadPriority = WorkloadPriority.BACKGROUND_RECONCILE,
    *,
    enqueued_at: datetime | None = None,
) -> WorkloadJob:
    return WorkloadJob(
        uuid4(),
        guild_id,
        "TEST",
        logical_key,
        priority,
        enqueued_at or datetime.now(UTC),
    )


async def test_round_robin_fairness_bounds_noisy_guild_and_measures_progress() -> None:
    governor = DiscordWorkloadGovernor(global_concurrency=1, max_queue_depth=100)

    async def complete(value: str) -> str:
        await asyncio.sleep(0)
        return value

    futures = [
        governor.submit(job(GUILD_A, f"a-{index}"), lambda index=index: complete(f"a-{index}"))
        for index in range(30)
    ]
    guild_b = governor.submit(job(GUILD_B, "b-0"), lambda: complete("b-0"))
    await governor.drain()
    assert await guild_b == "b-0"
    assert all(future.done() for future in futures)
    report = governor.fairness_report(GUILD_A, GUILD_B)
    assert report["b_progressed_within_bound"] is True
    assert report["first_b_slot"] == 1
    assert report["a_dispatches_before_b"] == 1


async def test_priority_aging_backpressure_concurrency_and_coalescing() -> None:
    governor = DiscordWorkloadGovernor(
        global_concurrency=2,
        per_guild_concurrency=1,
        max_queue_depth=3,
        aging_interval_seconds=1,
    )
    order: list[str] = []
    running = 0
    peak = 0

    async def operation(value: str) -> str:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        order.append(value)
        await asyncio.sleep(0.01)
        running -= 1
        return value

    old = datetime.now(UTC) - timedelta(seconds=10)
    aged = governor.submit(job(GUILD_A, "aged", enqueued_at=old), lambda: operation("aged"))
    urgent = governor.submit(
        job(GUILD_A, "urgent", WorkloadPriority.USER_REFRESH),
        lambda: operation("urgent"),
    )
    guild_b = governor.submit(job(GUILD_B, "b"), lambda: operation("b"))
    coalesced = governor.submit(job(GUILD_B, "b"), lambda: operation("never"))
    assert coalesced is guild_b
    with pytest.raises(BackpressureError):
        governor.submit(job(303, "overflow-1"), lambda: operation("overflow-1"))
    await governor.drain()
    assert await aged == "aged"
    assert await urgent == "urgent"
    assert await coalesced == "b"
    assert order[0] == "aged"
    assert "never" not in order
    assert peak == 2
    assert governor.metrics.coalesced == 1
    assert governor.metrics.peak_guild_concurrency == 1


def test_invalid_request_budget_and_unauthorized_halt_are_fail_safe() -> None:
    governor = DiscordWorkloadGovernor(invalid_request_warning=2)
    governor.record_discord_failure(DiscordFailure(DiscordErrorKind.FORBIDDEN, 403))
    governor.record_discord_failure(DiscordFailure(DiscordErrorKind.RATE_LIMITED, 429, 1.5))
    assert governor.invalid_request_budget_degraded is True
    assert governor.metrics.invalid_requests_10m == 2
    assert governor.metrics.rate_limited == 1
    assert governor.metrics.rate_limit_wait_seconds == 1.5
    governor.record_discord_failure(DiscordFailure(DiscordErrorKind.UNAUTHORIZED, 401))
    assert governor.halted is True


async def test_halted_governor_rejects_new_work() -> None:
    governor = DiscordWorkloadGovernor()
    governor.record_discord_failure(DiscordFailure(DiscordErrorKind.UNAUTHORIZED, 401))
    with pytest.raises(WorkloadHaltedError):
        governor.submit(job(GUILD_A, "blocked"), lambda: asyncio.sleep(0))
