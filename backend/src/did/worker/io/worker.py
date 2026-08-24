from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from did.domain.discord_runtime import WorkloadJob, WorkloadPriority
from did.infrastructure.discord import DiscordAdapterError
from did.infrastructure.planning_lock import GuildMutationLockUnavailable
from did.infrastructure.runtime_repository import RuntimeRepository
from did.worker.io.governor import DiscordWorkloadGovernor, WorkloadHaltedError


class DiscordSyncPort(Protocol):
    async def refresh_channels(self, guild_id: int) -> dict[str, int]: ...

    async def initial_sync(self, guild_id: int) -> dict[str, int]: ...


class ApplyPlanPort(Protocol):
    async def execute_leased(
        self,
        guild_id: int,
        leased: dict[str, Any],
        governor: DiscordWorkloadGovernor | None,
    ) -> None: ...


class UnsupportedWorkloadError(RuntimeError):
    pass


class JobLeaseLostError(RuntimeError):
    pass


class DurableDiscordIOWorker:
    """Lease locally, perform Discord I/O outside DB transactions, then acknowledge."""

    def __init__(
        self,
        repository: RuntimeRepository,
        sync: DiscordSyncPort,
        *,
        worker_id: str,
        lease_seconds: float = 30.0,
        plan_executor: ApplyPlanPort | None = None,
    ) -> None:
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id must be present and bounded")
        self._repository = repository
        self._sync = sync
        self._worker_id = worker_id
        self._plan_executor = plan_executor
        if lease_seconds < 0.05:
            raise ValueError("lease_seconds must be at least 50ms")
        self._lease_seconds = lease_seconds

    async def run_guild_once(self, guild_id: int) -> bool:
        leased = await self._repository.lease_next_job(
            guild_id, lease_owner=self._worker_id, lease_seconds=self._lease_seconds
        )
        if leased is None:
            return False
        await self._execute_leased(guild_id, leased, governor=None)
        return True

    async def dispatch_guild_once(
        self, guild_id: int, governor: DiscordWorkloadGovernor
    ) -> asyncio.Future[Any] | None:
        leased = await self._repository.lease_next_job(
            guild_id, lease_owner=self._worker_id, lease_seconds=self._lease_seconds
        )
        if leased is None:
            return None
        job = WorkloadJob(
            UUID(str(leased["job_id"])),
            guild_id,
            str(leased["workload_type"]),
            str(leased["logical_key"]),
            WorkloadPriority(int(leased["priority"])),
            leased.get("created_at") or datetime.now(UTC),
            payload=dict(leased.get("payload") or {}),
        )
        try:
            return governor.submit(
                job,
                lambda: self._execute_leased(guild_id, leased, governor=governor),
            )
        except Exception:
            await self._repository.retry_job(
                guild_id,
                job.job_id,
                lease_owner=self._worker_id,
                lease_token=UUID(str(leased["lease_token"])),
                retry_after_seconds=1.0,
                terminal=False,
            )
            raise

    async def _execute_leased(
        self,
        guild_id: int,
        leased: dict[str, Any],
        *,
        governor: DiscordWorkloadGovernor | None,
    ) -> None:
        job_id = UUID(str(leased["job_id"]))
        lease_token = UUID(str(leased["lease_token"]))
        try:
            if governor is not None and await governor.system_halted():
                raise WorkloadHaltedError("Discord token workload is halted")
            await self._execute_with_lease_heartbeat(guild_id, leased, governor=governor)
        except DiscordAdapterError as exc:
            if governor is not None:
                governor.record_discord_failure(exc.failure)
                await governor.record_distributed_failure(exc.failure)
            await self._repository.retry_job(
                guild_id,
                job_id,
                lease_owner=self._worker_id,
                lease_token=lease_token,
                retry_after_seconds=exc.failure.retry_after_seconds,
                terminal=not exc.failure.retryable,
            )
            raise
        except WorkloadHaltedError:
            await self._repository.retry_job(
                guild_id,
                job_id,
                lease_owner=self._worker_id,
                lease_token=lease_token,
                retry_after_seconds=300.0,
                terminal=False,
            )
            raise
        except GuildMutationLockUnavailable:
            await self._repository.retry_job(
                guild_id,
                job_id,
                lease_owner=self._worker_id,
                lease_token=lease_token,
                retry_after_seconds=1.0,
                terminal=False,
            )
            raise
        except JobLeaseLostError:
            # Fencing deliberately leaves acknowledgement/retry to the current owner.
            raise
        except Exception:
            await self._repository.retry_job(
                guild_id,
                job_id,
                lease_owner=self._worker_id,
                lease_token=lease_token,
                retry_after_seconds=None,
                terminal=True,
            )
            raise
        acknowledged = await self._repository.complete_job(
            guild_id,
            job_id,
            lease_owner=self._worker_id,
            lease_token=lease_token,
        )
        if not acknowledged:
            raise RuntimeError("Discord job lease was lost before acknowledgement")

    async def _execute_with_lease_heartbeat(
        self,
        guild_id: int,
        leased: dict[str, Any],
        *,
        governor: DiscordWorkloadGovernor | None,
    ) -> None:
        job_id = UUID(str(leased["job_id"]))
        lease_token = UUID(str(leased["lease_token"]))
        stopped = asyncio.Event()
        lost = asyncio.Event()

        async def renew() -> None:
            interval = max(0.01, self._lease_seconds / 5)
            while not stopped.is_set():
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=interval)
                    return
                except TimeoutError:
                    pass
                try:
                    renewed = await self._repository.renew_job_lease(
                        guild_id,
                        job_id,
                        lease_owner=self._worker_id,
                        lease_token=lease_token,
                        lease_seconds=max(0.5, self._lease_seconds),
                    )
                except Exception:
                    renewed = False
                if not renewed:
                    lost.set()
                    return

        async def discord_operation() -> None:
            workload_type = str(leased["workload_type"])
            if workload_type == "REFRESH_CHANNELS":
                await self._sync.refresh_channels(guild_id)
            elif workload_type in {"INITIAL_SYNC", "RECONCILE_STRUCTURE"}:
                await self._sync.initial_sync(guild_id)
            elif workload_type == "APPLY_PLAN" and self._plan_executor is not None:
                await self._plan_executor.execute_leased(guild_id, leased, governor)
            else:
                raise UnsupportedWorkloadError(workload_type)

        async def operation() -> None:
            if str(leased["workload_type"]) == "APPLY_PLAN":
                await discord_operation()
            elif governor is None:
                await discord_operation()
            else:
                await governor.run_distributed(guild_id, discord_operation)

        heartbeat = asyncio.create_task(renew())
        operation_task = asyncio.create_task(operation())
        lost_task = asyncio.create_task(lost.wait())
        try:
            done, _ = await asyncio.wait(
                {operation_task, lost_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if lost_task in done and lost.is_set() and not operation_task.done():
                operation_task.cancel()
                await asyncio.gather(operation_task, return_exceptions=True)
                raise JobLeaseLostError("Discord job lease fencing token was lost")
            await operation_task
        finally:
            stopped.set()
            if not operation_task.done():
                operation_task.cancel()
            heartbeat.cancel()
            lost_task.cancel()
            await asyncio.gather(heartbeat, lost_task, operation_task, return_exceptions=True)
