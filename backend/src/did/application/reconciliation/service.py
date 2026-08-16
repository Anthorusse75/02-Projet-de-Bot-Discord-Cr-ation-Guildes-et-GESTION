from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from did.domain.discord_runtime import WorkloadJob, WorkloadPriority
from did.infrastructure.discord import DiscordAdapterError, DiscordStructurePort
from did.infrastructure.runtime_redis import RedisHotCache, RedisSingleFlight
from did.infrastructure.runtime_repository import RuntimeRepository
from did.worker.io import DiscordWorkloadGovernor


class DiscordSyncService:
    def __init__(
        self,
        *,
        adapter: DiscordStructurePort,
        repository: RuntimeRepository,
        hot_cache: RedisHotCache,
        singleflight: RedisSingleFlight,
        governor: DiscordWorkloadGovernor,
    ) -> None:
        self._adapter = adapter
        self._repository = repository
        self._hot_cache = hot_cache
        self._singleflight = singleflight
        self._governor = governor

    async def initial_sync(
        self, guild_id: int, *, stop_event: asyncio.Event | None = None
    ) -> dict[str, int]:
        if stop_event is not None and stop_event.is_set():
            return {"channels": 0, "roles": 0, "interrupted": 1}
        correlation_id = uuid4()
        now = datetime.now(UTC)

        async def fetch_channels() -> dict[str, Any]:
            return {"channels": await self._adapter.fetch_channels(guild_id)}

        async def fetch_roles() -> dict[str, Any]:
            return {"roles": await self._adapter.fetch_roles(guild_id)}

        channel_job = WorkloadJob(
            uuid4(),
            guild_id,
            "INITIAL_SYNC_CHANNELS",
            "refresh:channels",
            WorkloadPriority.CRITICAL_PREFLIGHT,
            now,
        )
        role_job = WorkloadJob(
            uuid4(),
            guild_id,
            "INITIAL_SYNC_ROLES",
            "refresh:roles",
            WorkloadPriority.CRITICAL_PREFLIGHT,
            now,
        )
        channel_future = self._governor.submit(
            channel_job,
            lambda: self._singleflight.run(guild_id, "refresh:channels", fetch_channels),
        )
        role_future = self._governor.submit(
            role_job,
            lambda: self._singleflight.run(guild_id, "refresh:roles", fetch_roles),
        )
        try:
            await self._governor.drain()
            channel_result = await channel_future
            role_result = await role_future
        except DiscordAdapterError as exc:
            self._governor.record_discord_failure(exc.failure)
            raise
        if stop_event is not None and stop_event.is_set():
            return {"channels": 0, "roles": 0, "interrupted": 1}
        channels = list(channel_result["channels"])
        roles = list(role_result["roles"])
        await self._repository.apply_rest_channel_snapshot(
            guild_id=guild_id,
            channels=channels,
            correlation_id=correlation_id,
            observed_at=now,
        )
        await self._repository.apply_rest_role_snapshot(
            guild_id=guild_id,
            roles=roles,
            correlation_id=correlation_id,
            observed_at=now,
        )
        await self._repository.mark_structure_sync_complete(guild_id, completed_at=now)
        await self._hot_cache.invalidate_channels(guild_id)
        await self._hot_cache.rebuild_channels(self._repository, guild_id)
        return {"channels": len(channels), "roles": len(roles), "interrupted": 0}

    async def refresh_channels(self, guild_id: int) -> dict[str, int]:
        correlation_id = uuid4()

        async def fetch() -> dict[str, Any]:
            return {"channels": await self._adapter.fetch_channels(guild_id)}

        job = WorkloadJob(
            uuid4(),
            guild_id,
            "REFRESH_CHANNELS",
            "refresh:channels",
            WorkloadPriority.USER_REFRESH,
            datetime.now(UTC),
        )
        future = self._governor.submit(
            job, lambda: self._singleflight.run(guild_id, "refresh:channels", fetch)
        )
        try:
            await self._governor.drain()
            result = await future
        except DiscordAdapterError as exc:
            self._governor.record_discord_failure(exc.failure)
            raise
        channels = list(result["channels"])
        await self._repository.apply_rest_channel_snapshot(
            guild_id=guild_id,
            channels=channels,
            correlation_id=correlation_id,
        )
        await self._hot_cache.invalidate_channels(guild_id)
        return {"channels": len(channels)}
