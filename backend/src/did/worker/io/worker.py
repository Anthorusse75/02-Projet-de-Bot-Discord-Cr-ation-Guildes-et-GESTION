from __future__ import annotations

from typing import Protocol
from uuid import UUID

from did.infrastructure.discord import DiscordAdapterError
from did.infrastructure.runtime_repository import RuntimeRepository


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
        job_id = UUID(str(leased["job_id"]))
        try:
            workload_type = str(leased["workload_type"])
            if workload_type == "REFRESH_CHANNELS":
                await self._sync.refresh_channels(guild_id)
            elif workload_type in {"INITIAL_SYNC", "RECONCILE_STRUCTURE"}:
                await self._sync.initial_sync(guild_id)
            else:
                raise UnsupportedWorkloadError(workload_type)
        except DiscordAdapterError as exc:
            await self._repository.retry_job(
                guild_id,
                job_id,
                lease_owner=self._worker_id,
                retry_after_seconds=exc.failure.retry_after_seconds,
                terminal=not exc.failure.retryable,
            )
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
        return True
