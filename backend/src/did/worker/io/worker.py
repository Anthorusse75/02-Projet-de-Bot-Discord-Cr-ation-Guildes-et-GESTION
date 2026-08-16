from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from did.domain.discord_runtime import WorkloadJob, WorkloadPriority
from did.infrastructure.discord import DiscordAdapterError
from did.infrastructure.runtime_repository import RuntimeRepository
from did.worker.io.governor import DiscordWorkloadGovernor, WorkloadHaltedError


class DiscordSyncPort(Protocol):
    async def refresh_channels(self, guild_id: int) -> dict[str, int]: ...

    async def initial_sync(self, guild_id: int) -> dict[str, int]: ...


class UnsupportedWorkloadError(RuntimeError):
    pass


class DurableDiscordIOWorker:
    """Lease locally, perform Discord I/O outside DB transactions, then acknowledge."""

    def __init__(
        self,
        repository: RuntimeRepository,
        sync: DiscordSyncPort,
        *,
        worker_id: str,
    ) -> None:
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id must be present and bounded")
        self._repository = repository
        self._sync = sync
        self._worker_id = worker_id

    async def run_guild_once(self, guild_id: int) -> bool:
        leased = await self._repository.lease_next_job(guild_id, lease_owner=self._worker_id)
        if leased is None:
            return False
        await self._execute_leased(guild_id, leased, governor=None)
        return True

    async def dispatch_guild_once(
        self, guild_id: int, governor: DiscordWorkloadGovernor
    ) -> asyncio.Future[Any] | None:
        leased = await self._repository.lease_next_job(guild_id, lease_owner=self._worker_id)
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
        try:
            if governor is not None and governor.halted:
                await self._repository.retry_job(
                    guild_id,
                    job_id,
                    lease_owner=self._worker_id,
                    retry_after_seconds=300.0,
                    terminal=False,
                )
                raise WorkloadHaltedError("Discord token workload is halted")
            workload_type = str(leased["workload_type"])
            if workload_type == "REFRESH_CHANNELS":
                await self._sync.refresh_channels(guild_id)
            elif workload_type in {"INITIAL_SYNC", "RECONCILE_STRUCTURE"}:
                await self._sync.initial_sync(guild_id)
            else:
                raise UnsupportedWorkloadError(workload_type)
        except DiscordAdapterError as exc:
            if governor is not None:
                governor.record_discord_failure(exc.failure)
            await self._repository.retry_job(
                guild_id,
                job_id,
                lease_owner=self._worker_id,
                retry_after_seconds=exc.failure.retry_after_seconds,
                terminal=not exc.failure.retryable,
            )
            raise
        except WorkloadHaltedError:
            raise
        except Exception:
            await self._repository.retry_job(
                guild_id,
                job_id,
                lease_owner=self._worker_id,
                retry_after_seconds=None,
                terminal=True,
            )
            raise
        acknowledged = await self._repository.complete_job(
            guild_id, job_id, lease_owner=self._worker_id
        )
        if not acknowledged:
            raise RuntimeError("Discord job lease was lost before acknowledgement")
