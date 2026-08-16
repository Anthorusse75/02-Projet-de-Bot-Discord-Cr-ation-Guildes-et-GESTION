from __future__ import annotations

from uuid import UUID

from did.infrastructure.runtime_redis import RedisHotCache
from did.infrastructure.runtime_repository import RuntimeRepository


class CachePurgeService:
    """Local-only purge service; it deliberately owns no Discord adapter."""

    def __init__(self, repository: RuntimeRepository, hot_cache: RedisHotCache) -> None:
        self._repository = repository
        self._hot_cache = hot_cache

    async def preview(
        self, *, guild_id: int, actor_user_id: int, channel_ids: list[int]
    ) -> list[dict[str, object]]:
        selected = set(channel_ids)
        channels = await self._repository.channels(
            guild_id, actor_user_id, include_hidden_deleted=True
        )
        return [
            {
                "channel_id": str(row["channel_id"]),
                "type": row["type"],
                "last_known_name": row["name"],
                "last_known_parent_id": (
                    str(row["parent_id"]) if row["parent_id"] is not None else None
                ),
                "observability_state": row["observability_state"],
                "last_full_observed_at": row["last_full_observed_at"],
            }
            for row in channels
            if int(row["channel_id"]) in selected
        ]

    async def purge(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        channel_ids: list[int],
        correlation_id: UUID,
        user_confirmed_deleted: bool,
    ) -> int:
        count = await self._repository.purge_channels(
            guild_id=guild_id,
            actor_user_id=actor_user_id,
            channel_ids=channel_ids,
            correlation_id=correlation_id,
            user_confirmed_deleted=user_confirmed_deleted,
        )
        return count
