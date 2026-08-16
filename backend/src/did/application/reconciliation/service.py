from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from did.infrastructure.discord import DiscordStructurePort
from did.infrastructure.runtime_redis import RedisSingleFlight
from did.infrastructure.runtime_repository import RuntimeRepository


class DiscordSyncService:
    def __init__(
        self,
        *,
        adapter: DiscordStructurePort,
        repository: RuntimeRepository,
        singleflight: RedisSingleFlight,
    ) -> None:
        self._adapter = adapter
        self._repository = repository
        self._singleflight = singleflight

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

        # The durable worker submits this bounded operation through its one long-lived
        # Governor.  The sync service therefore performs no nested drain and cannot
        # create a competing scheduler/consumer around the same Governor instance.
        channel_result = await self._singleflight.run(
            guild_id, "refresh:channels", fetch_channels
        )
        role_result = await self._singleflight.run(guild_id, "refresh:roles", fetch_roles)
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
        return {"channels": len(channels), "roles": len(roles), "interrupted": 0}

    async def refresh_channels(self, guild_id: int) -> dict[str, int]:
        correlation_id = uuid4()

        async def fetch() -> dict[str, Any]:
            return {"channels": await self._adapter.fetch_channels(guild_id)}

        result = await self._singleflight.run(guild_id, "refresh:channels", fetch)
        channels = list(result["channels"])
        await self._repository.apply_rest_channel_snapshot(
            guild_id=guild_id,
            channels=channels,
            correlation_id=correlation_id,
        )
        return {"channels": len(channels)}
