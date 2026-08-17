import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from did.application.reconciliation import (
    AdaptiveReconcilePolicy,
    ReconcileScheduler,
    ReconcileSignals,
)
from did.domain.discord_runtime import WorkloadJob, WorkloadPriority
from did.infrastructure.database import (
    create_database_engine,
    create_session_factory,
    tenant_transaction,
)
from did.infrastructure.redis import create_redis_client
from did.infrastructure.runtime_redis import (
    OutboxPublisher,
    RedisDiscordWorkloadCoordinator,
    RedisRuntimeWakeup,
    TenantPubSub,
)
from did.infrastructure.runtime_repository import RuntimeRepository
from did.tenancy import TenantContext
from did.worker.io import (
    BackpressureError,
    DiscordWorkerRuntime,
    DiscordWorkloadGovernor,
    DurableDiscordIOWorker,
)

pytestmark = pytest.mark.load

GUILD_A = 530303030303030301
GUILD_B = 530303030303030302
GUILD_C = 530303030303030303
APP_URL = os.environ.get(
    "DID_DATABASE_URL",
    "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test",
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
REDIS_URL = os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0")


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


async def test_durable_noisy_a_quiet_b_progresses_through_real_pipeline() -> None:
    guild_a_jobs = 300
    guild_b_jobs = 30
    admin = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with admin.begin() as connection:
            await connection.execute(text("TRUNCATE guild_installations CASCADE"))
            await connection.execute(
                text(
                    "INSERT INTO guild_installations "
                    "(guild_id, name, installation_status) VALUES "
                    "(:guild_a, 'Noisy A', 'ACTIVE'), (:guild_b, 'Quiet B', 'ACTIVE')"
                ),
                {"guild_a": GUILD_A, "guild_b": GUILD_B},
            )
    finally:
        await admin.dispose()

    engine = create_database_engine(APP_URL, pool_size=8)
    repository = RuntimeRepository(create_session_factory(engine))
    redis = create_redis_client(REDIS_URL)

    class SyncProbe:
        async def refresh_channels(self, guild_id: int) -> dict[str, int]:
            await asyncio.sleep(0.001)
            return {"guild_id": guild_id}

        async def initial_sync(self, guild_id: int) -> dict[str, int]:
            raise AssertionError(f"unexpected initial sync for {guild_id}")

    try:
        await redis.flushdb()
        enqueued_at = datetime.now(UTC)
        for guild_id, count, prefix in (
            (GUILD_A, guild_a_jobs, "a"),
            (GUILD_B, guild_b_jobs, "b"),
        ):
            for index in range(count):
                job = WorkloadJob(
                    uuid4(),
                    guild_id,
                    "REFRESH_CHANNELS",
                    f"durable-load:{prefix}:{index}",
                    WorkloadPriority.BACKGROUND_RECONCILE,
                    enqueued_at,
                )
                await repository.enqueue_job(job, requested_by=None, correlation_id=uuid4())

        wakeup = RedisRuntimeWakeup(redis)
        await wakeup.signal_job(GUILD_A)
        await wakeup.signal_job(GUILD_B)
        governor = DiscordWorkloadGovernor(
            global_concurrency=4,
            per_guild_concurrency=1,
            max_queue_depth=1_000,
        )
        runtime = DiscordWorkerRuntime(
            repository=repository,
            worker=DurableDiscordIOWorker(
                repository,
                SyncProbe(),
                worker_id="durable-load-worker",
            ),
            governor=governor,
            outbox=OutboxPublisher(
                repository,
                TenantPubSub(redis),
                wakeup=wakeup,
            ),
            wakeup=wakeup,
            poll_interval_seconds=0.05,
            recovery_interval_seconds=0.1,
            routing_batch_size=32,
            dispatch_batch_size=512,
        )
        stop = asyncio.Event()
        process = asyncio.create_task(runtime.run(stop))
        deadline = asyncio.get_running_loop().time() + 30.0
        counts: dict[int, tuple[int, int]] = {}
        while asyncio.get_running_loop().time() < deadline:
            counts.clear()
            for guild_id in (GUILD_A, GUILD_B):
                async with tenant_transaction(
                    create_session_factory(engine), TenantContext(guild_id)
                ) as session:
                    succeeded = int(
                        await session.scalar(
                            text("SELECT count(*) FROM discord_io_jobs WHERE status='SUCCEEDED'")
                        )
                        or 0
                    )
                    unpublished = int(
                        await session.scalar(
                            text("SELECT count(*) FROM discord_outbox WHERE status!='PUBLISHED'")
                        )
                        or 0
                    )
                counts[guild_id] = (succeeded, unpublished)
            if counts == {
                GUILD_A: (guild_a_jobs, 0),
                GUILD_B: (guild_b_jobs, 0),
            }:
                break
            if process.done():
                process.result()
            await asyncio.sleep(0.05)
        else:
            raise TimeoutError(f"durable fairness pipeline timed out: {counts}")
        stop.set()
        await asyncio.wait_for(process, timeout=2)

        fairness = governor.fairness_report(GUILD_A, GUILD_B)
        report: dict[str, object] = {
            "scenario": "stage03-durable-postgres-routing-worker-governor-ack",
            "pipeline": [
                "postgresql.discord_io_jobs",
                "redis.wakeup",
                "durable-worker",
                "long-lived-governor",
                "fake-discord",
                "postgresql.ack",
            ],
            "guild_a_jobs": guild_a_jobs,
            "guild_b_jobs": guild_b_jobs,
            "first_b_slot": fairness["first_b_slot"],
            "a_dispatches_before_b": fairness["a_dispatches_before_b"],
            "fairness_bound_slots": fairness["fairness_bound_slots"],
            "b_progressed_within_bound": fairness["b_progressed_within_bound"],
            "peak_backlog": governor.metrics.peak_queue_depth,
            "peak_global_concurrency": governor.metrics.peak_global_concurrency,
            "peak_guild_concurrency": governor.metrics.peak_guild_concurrency,
            "jobs_completed": governor.metrics.completed,
            "durable_jobs_succeeded": guild_a_jobs + guild_b_jobs,
            "starvation": False,
        }
        write_report(report)
        assert fairness["first_b_slot"] == 1
        assert fairness["a_dispatches_before_b"] == 1
        assert fairness["b_progressed_within_bound"] is True
        assert governor.metrics.peak_global_concurrency == 2
        assert governor.metrics.peak_guild_concurrency == 1
        assert governor.metrics.peak_queue_depth == 2
        assert governor.metrics.completed == guild_a_jobs + guild_b_jobs
        assert counts[GUILD_B][0] == guild_b_jobs
    finally:
        await redis.aclose()
        await engine.dispose()


async def test_two_workers_share_permits_leases_backpressure_and_scheduler_pressure() -> None:
    admin = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with admin.begin() as connection:
            await connection.execute(text("TRUNCATE guild_installations CASCADE"))
            await connection.execute(
                text(
                    "INSERT INTO guild_installations "
                    "(guild_id, name, installation_status) VALUES "
                    "(:a, 'Distributed A', 'ACTIVE'), "
                    "(:b, 'Distributed B', 'ACTIVE'), "
                    "(:c, 'Scheduler C', 'ACTIVE')"
                ),
                {"a": GUILD_A, "b": GUILD_B, "c": GUILD_C},
            )
    finally:
        await admin.dispose()

    engine = create_database_engine(APP_URL, pool_size=12)
    repository = RuntimeRepository(create_session_factory(engine))
    redis = create_redis_client(REDIS_URL)
    active_global = 0
    peak_global = 0
    active_by_guild = {GUILD_A: 0, GUILD_B: 0}
    peak_by_guild = {GUILD_A: 0, GUILD_B: 0}
    calls = {GUILD_A: 0, GUILD_B: 0}
    start_order: list[int] = []

    class SlowSync:
        async def _call(self, guild_id: int) -> dict[str, int]:
            nonlocal active_global, peak_global
            calls[guild_id] += 1
            start_order.append(guild_id)
            active_global += 1
            active_by_guild[guild_id] += 1
            peak_global = max(peak_global, active_global)
            peak_by_guild[guild_id] = max(peak_by_guild[guild_id], active_by_guild[guild_id])
            try:
                await asyncio.sleep(0.18)
                return {"guild_id": guild_id}
            finally:
                active_global -= 1
                active_by_guild[guild_id] -= 1

        async def refresh_channels(self, guild_id: int) -> dict[str, int]:
            return await self._call(guild_id)

        async def initial_sync(self, guild_id: int) -> dict[str, int]:
            return await self._call(guild_id)

    try:
        await redis.flushdb()
        expected = {GUILD_A: 14, GUILD_B: 4}
        for guild_id, count in expected.items():
            for index in range(count):
                await repository.enqueue_job(
                    WorkloadJob(
                        uuid4(),
                        guild_id,
                        "REFRESH_CHANNELS",
                        f"distributed:{guild_id}:{index}",
                        WorkloadPriority.USER_REFRESH,
                        datetime.now(UTC),
                    ),
                    requested_by=None,
                    correlation_id=uuid4(),
                )

        # A crashed owner leaves both its DB lease and Redis permit to expire.
        crashed = await repository.lease_next_job(
            GUILD_A, lease_owner="crashed-worker", lease_seconds=0.15
        )
        assert crashed is not None
        crashed_coordinator = RedisDiscordWorkloadCoordinator(
            redis,
            global_concurrency=2,
            per_guild_concurrency=1,
            permit_ttl_seconds=0.15,
        )
        await crashed_coordinator.acquire(GUILD_A)
        await asyncio.sleep(0.18)

        runtimes: list[DiscordWorkerRuntime] = []
        governors: list[DiscordWorkloadGovernor] = []
        for index in range(2):
            worker_id = f"distributed-worker-{index}"
            wakeup = RedisRuntimeWakeup(redis, reporter_id=worker_id)
            coordinator = RedisDiscordWorkloadCoordinator(
                redis,
                global_concurrency=2,
                per_guild_concurrency=1,
                permit_ttl_seconds=0.15,
            )
            governor = DiscordWorkloadGovernor(
                global_concurrency=2,
                per_guild_concurrency=1,
                max_queue_depth=10,
                distributed_coordinator=coordinator,
            )
            governors.append(governor)
            runtimes.append(
                DiscordWorkerRuntime(
                    repository=repository,
                    worker=DurableDiscordIOWorker(
                        repository,
                        SlowSync(),
                        worker_id=worker_id,
                        lease_seconds=0.15,
                    ),
                    governor=governor,
                    outbox=OutboxPublisher(
                        repository,
                        TenantPubSub(redis),
                        wakeup=wakeup,
                        publisher_id=worker_id,
                        lease_seconds=0.15,
                    ),
                    wakeup=wakeup,
                    poll_interval_seconds=0.02,
                    recovery_interval_seconds=0.03,
                    routing_batch_size=32,
                    dispatch_batch_size=512,
                )
            )

        stop = asyncio.Event()
        tasks = [asyncio.create_task(item.run(stop)) for item in runtimes]
        observer = RedisRuntimeWakeup(redis, reporter_id="pressure-observer")
        deadline = asyncio.get_running_loop().time() + 3
        pressure_during_backlog = 0.0
        while asyncio.get_running_loop().time() < deadline:
            pressure_during_backlog = await observer.rate_limit_pressure()
            if pressure_during_backlog > 0 and sum(calls.values()) > 0:
                break
            await asyncio.sleep(0.01)
        assert pressure_during_backlog > 0

        scheduler = ReconcileScheduler(repository, AdaptiveReconcilePolicy(jitter_ratio=0))
        now = datetime.now(UTC)
        scheduled = await scheduler.enqueue_due(
            [
                ReconcileSignals(
                    GUILD_C,
                    None,
                    active=True,
                    rate_limit_pressure=pressure_during_backlog,
                ),
                ReconcileSignals(
                    GUILD_B,
                    now,
                    active=True,
                    gateway_gap=True,
                    rate_limit_pressure=pressure_during_backlog,
                ),
            ],
            now=now,
        )
        assert [guild_id for guild_id, _ in scheduled] == [GUILD_B]
        expected[GUILD_B] += 1

        deadline = asyncio.get_running_loop().time() + 15
        while asyncio.get_running_loop().time() < deadline:
            statuses: dict[int, tuple[int, int]] = {}
            for guild_id in (GUILD_A, GUILD_B):
                async with tenant_transaction(
                    create_session_factory(engine), TenantContext(guild_id)
                ) as session:
                    statuses[guild_id] = (
                        int(
                            await session.scalar(
                                text(
                                    "SELECT count(*) FROM discord_io_jobs WHERE status='SUCCEEDED'"
                                )
                            )
                            or 0
                        ),
                        int(
                            await session.scalar(
                                text("SELECT count(*) FROM discord_io_jobs WHERE status='LEASED'")
                            )
                            or 0
                        ),
                    )
            if all(statuses[guild][0] == expected[guild] for guild in expected):
                break
            assert all(not task.done() for task in tasks)
            await asyncio.sleep(0.03)
        else:
            raise TimeoutError(f"two-worker workload timed out: {statuses}")

        stop.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=2)
        assert calls == expected
        assert start_order.index(GUILD_B) <= 1
        assert peak_global == 2
        assert peak_by_guild == {GUILD_A: 1, GUILD_B: 1}
        assert all(value[1] == 0 for value in statuses.values())
        assert sum(item.metrics.rejected_backpressure for item in governors) > 0
        assert max(item.metrics.peak_system_global_concurrency for item in governors) == 2
        assert max(item.metrics.peak_system_guild_concurrency for item in governors) == 1
        assert await observer.rate_limit_pressure() == 0.0
        assert (
            await repository.complete_job(
                GUILD_A,
                crashed["job_id"],
                lease_owner="crashed-worker",
                lease_token=crashed["lease_token"],
            )
            is False
        )
    finally:
        await redis.aclose()
        await engine.dispose()
