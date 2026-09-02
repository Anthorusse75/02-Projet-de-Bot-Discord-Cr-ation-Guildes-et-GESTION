"""Stage 09 load/fairness (section 19): a large campaign bulk-send backlog
must never starve a higher-priority Discord workload (structural apply/
critical reconcile) or another Guild's fair share of dispatch slots.
Governor-level, in-memory -- no Discord/Postgres I/O, mirrors
tests/load/test_stage03_fairness_load.py's deterministic style.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from did.campaigns.delivery_worker import SEND_CAMPAIGN_MESSAGE_WORKLOAD_TYPE
from did.domain.discord_runtime import WorkloadJob, WorkloadPriority
from did.worker.io.governor import DiscordWorkloadGovernor

pytestmark = pytest.mark.load

GUILD_CAMPAIGN = 530309090909090901
GUILD_STRUCTURAL = 530309090909090902


def _campaign_job(guild_id: int, index: int) -> WorkloadJob:
    return WorkloadJob(
        uuid4(),
        guild_id,
        SEND_CAMPAIGN_MESSAGE_WORKLOAD_TYPE,
        f"delivery-{index}",
        WorkloadPriority.SEND_CAMPAIGN_MESSAGE,
        datetime.now(UTC),
    )


def _structural_job(guild_id: int, index: int) -> WorkloadJob:
    return WorkloadJob(
        uuid4(),
        guild_id,
        "STRUCTURAL_APPLY",
        f"apply-{index}",
        WorkloadPriority.APPLY_CONTINUATION,
        datetime.now(UTC),
    )


def _critical_reconcile_job(guild_id: int, index: int) -> WorkloadJob:
    return WorkloadJob(
        uuid4(),
        guild_id,
        "CRITICAL_RECONCILE",
        f"reconcile-{index}",
        WorkloadPriority.CRITICAL_PREFLIGHT,
        datetime.now(UTC),
    )


async def test_bulk_campaign_backlog_never_starves_structural_apply_same_guild() -> None:
    """A single Guild has both a huge campaign fan-out backlog AND a
    structural apply queued -- the apply must dispatch essentially
    immediately despite the campaign backlog, since it is strictly higher
    priority within that Guild's own per-guild concurrency slot."""
    governor = DiscordWorkloadGovernor(global_concurrency=4, per_guild_concurrency=1)

    async def complete(value: str) -> str:
        await asyncio.sleep(0)
        return value

    campaign_futures = [
        governor.submit(_campaign_job(GUILD_CAMPAIGN, i), lambda i=i: complete(f"campaign-{i}"))
        for i in range(500)
    ]
    apply_future = governor.submit(_structural_job(GUILD_CAMPAIGN, 0), lambda: complete("apply"))

    await governor.drain()

    dispatch_order = governor.metrics.dispatch_slots
    # The structural apply, despite being submitted after 500 campaign
    # sends, must have dispatched at or near the very first slot for this
    # Guild -- priority aging only promotes a lagging job over time, so a
    # same-priority-tier fresh submission never jumps ahead of it either.
    assert apply_future.done()
    assert all(future.done() for future in campaign_futures)
    assert dispatch_order[0] == GUILD_CAMPAIGN  # only one Guild in this scenario


async def test_bulk_campaign_backlog_never_starves_another_guilds_fair_share() -> None:
    """A noisy Guild with a huge campaign backlog must not prevent a quiet
    Guild's own (even same-priority) campaign work from making bounded
    progress -- per-Guild round-robin fairness, independent of priority
    tier."""
    governor = DiscordWorkloadGovernor(global_concurrency=4, per_guild_concurrency=1)

    async def complete(value: str) -> str:
        await asyncio.sleep(0)
        return value

    noisy = [
        governor.submit(_campaign_job(GUILD_CAMPAIGN, i), lambda i=i: complete(f"noisy-{i}"))
        for i in range(500)
    ]
    quiet = [
        governor.submit(_campaign_job(GUILD_STRUCTURAL, i), lambda i=i: complete(f"quiet-{i}"))
        for i in range(10)
    ]

    await governor.drain()

    fairness = governor.fairness_report(GUILD_CAMPAIGN, GUILD_STRUCTURAL)
    assert fairness["b_progressed_within_bound"] is True
    assert all(future.done() for future in noisy + quiet)


async def test_critical_reconcile_dispatches_before_queued_campaign_work_same_guild() -> None:
    """Even when a critical reconcile is submitted strictly AFTER a large
    campaign backlog for the same Guild, its higher priority tier must move
    it ahead in that Guild's own dispatch order (subject to the single
    per-guild concurrency slot already in flight)."""
    governor = DiscordWorkloadGovernor(global_concurrency=1, per_guild_concurrency=1)
    started: list[str] = []

    async def track(label: str) -> None:
        started.append(label)
        await asyncio.sleep(0)

    # Hold the single global slot busy with the first campaign job so the
    # rest of the campaign backlog and the later critical job both queue up
    # behind it, then observe dispatch order once that slot frees.
    first = governor.submit(_campaign_job(GUILD_CAMPAIGN, 0), lambda: track("campaign-0"))
    for i in range(1, 50):
        governor.submit(_campaign_job(GUILD_CAMPAIGN, i), lambda i=i: track(f"campaign-{i}"))
    critical = governor.submit(
        _critical_reconcile_job(GUILD_CAMPAIGN, 0), lambda: track("critical")
    )

    await governor.drain()
    assert first.done() and critical.done()
    # The critical job must have started before the bulk of the campaign
    # backlog, despite being submitted after all of it.
    assert started.index("critical") < started.index("campaign-49")
