from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from did.application.reconciliation import (
    AdaptiveReconcilePolicy,
    ReconcileScheduler,
    ReconcileSignals,
)
from did.domain.discord_runtime import DiscordErrorKind, DiscordFailure
from did.infrastructure.discord import DiscordAdapterError
from did.worker.io import (
    DiscordWorkloadGovernor,
    DurableDiscordIOWorker,
    UnsupportedWorkloadError,
)

GUILD = 630303030303030301


class WorkerRepositoryProbe:
    def __init__(self, workload_type: str = "REFRESH_CHANNELS") -> None:
        self.workload_type = workload_type
        self.calls: list[str] = []
        self.lease_durations: list[float] = []

    async def lease_next_job(self, guild_id: int, **values: object):
        self.calls.append("lease-committed")
        self.lease_durations.append(float(values["lease_seconds"]))
        return {
            "job_id": uuid4(),
            "lease_token": uuid4(),
            "workload_type": self.workload_type,
            "logical_key": "worker-probe",
            "priority": 3,
            "created_at": datetime.now(UTC),
            "payload": {},
        }

    async def renew_job_lease(self, guild_id: int, job_id, **_: object) -> bool:
        self.calls.append("lease-renewed")
        return True

    async def complete_job(self, guild_id: int, job_id, **_: object) -> bool:
        self.calls.append("ack-transaction")
        return True

    async def retry_job(self, guild_id: int, job_id, **values: object) -> bool:
        self.calls.append(f"retry-terminal-{values['terminal']}")
        return True


class SyncProbe:
    def __init__(self, repository: WorkerRepositoryProbe) -> None:
        self.repository = repository
        self.failure: Exception | None = None

    async def refresh_channels(self, guild_id: int) -> dict[str, int]:
        self.repository.calls.append("discord-network-outside-transaction")
        if self.failure is not None:
            raise self.failure
        return {"channels": 1}

    async def initial_sync(self, guild_id: int) -> dict[str, int]:
        self.repository.calls.append("discord-network-outside-transaction")
        return {"channels": 1, "roles": 1, "interrupted": 0}


async def test_worker_transaction_network_transaction_order_is_short() -> None:
    repository = WorkerRepositoryProbe()
    worker = DurableDiscordIOWorker(
        repository,
        SyncProbe(repository),
        worker_id="stage03-worker",  # type: ignore[arg-type]
    )
    assert await worker.run_guild_once(GUILD) is True
    assert repository.calls == [
        "lease-committed",
        "discord-network-outside-transaction",
        "ack-transaction",
    ]


async def test_dispatched_subsecond_lease_is_protected_while_queued() -> None:
    repository = WorkerRepositoryProbe()
    worker = DurableDiscordIOWorker(
        repository,
        SyncProbe(repository),
        worker_id="stage03-subsecond-worker",  # type: ignore[arg-type]
        lease_seconds=0.15,
    )
    governor = DiscordWorkloadGovernor(global_concurrency=1, per_guild_concurrency=1)

    future = await worker.dispatch_guild_once(GUILD, governor)

    assert future is not None
    assert repository.lease_durations == [0.5]
    await governor.drain()
    assert future.done()


async def test_worker_does_not_retry_403_or_unknown_workload_blindly() -> None:
    repository = WorkerRepositoryProbe()
    sync = SyncProbe(repository)
    sync.failure = DiscordAdapterError(DiscordFailure(DiscordErrorKind.FORBIDDEN, 403))
    worker = DurableDiscordIOWorker(
        repository,
        sync,
        worker_id="stage03-worker",  # type: ignore[arg-type]
    )
    with pytest.raises(DiscordAdapterError):
        await worker.run_guild_once(GUILD)
    assert repository.calls[-1] == "retry-terminal-True"

    unsupported_repository = WorkerRepositoryProbe("FUTURE_STAGE_WORKLOAD")
    unsupported = DurableDiscordIOWorker(
        unsupported_repository,
        SyncProbe(unsupported_repository),
        worker_id="stage03-worker",
    )  # type: ignore[arg-type]
    with pytest.raises(UnsupportedWorkloadError):
        await unsupported.run_guild_once(GUILD)
    assert unsupported_repository.calls[-1] == "retry-terminal-True"


class SchedulerRepositoryProbe:
    def __init__(self) -> None:
        self.guilds: list[int] = []

    async def enqueue_job(self, job, **_: object):
        self.guilds.append(job.guild_id)
        return job.job_id


async def test_scheduler_enqueues_only_due_guilds_in_priority_order() -> None:
    now = datetime.now(UTC)
    repository = SchedulerRepositoryProbe()
    scheduler = ReconcileScheduler(
        repository,
        AdaptiveReconcilePolicy(jitter_ratio=0),  # type: ignore[arg-type]
    )
    due_gap = ReconcileSignals(GUILD + 1, now, active=True, gateway_gap=True)
    due_old = ReconcileSignals(GUILD + 2, now - timedelta(days=2), active=False)
    not_due = ReconcileSignals(GUILD + 3, now, active=True)
    enqueued = await scheduler.enqueue_due([not_due, due_old, due_gap], now=now)
    assert [guild_id for guild_id, _ in enqueued] == [GUILD + 1, GUILD + 2]
    assert repository.guilds == [GUILD + 1, GUILD + 2]
