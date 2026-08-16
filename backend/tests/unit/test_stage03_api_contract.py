from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from did.api.runtime_cache import (
    ChannelSelection,
    PurgeRequest,
    cached_channels,
    enqueue_channel_refresh,
    preview_channel_purge,
    purge_channels,
)
from did.oauth.stores import SessionData

GUILD = 430303030303030301
CHANNEL = 430303030303030311
USER = 430303030303030321


def session() -> SessionData:
    now = datetime.now(UTC)
    return SessionData(
        session_id="stage03-api",
        discord_user_id=USER,
        csrf_token="csrf",
        active_guild_id=GUILD,
        created_at=now,
        last_seen_at=now,
        absolute_expires_at=now + timedelta(hours=1),
        policy_version=1,
    )


class AuthorizationProbe:
    def __init__(self) -> None:
        self.calls = 0

    async def authorize(self, **_: object) -> None:
        self.calls += 1


class HotCacheProbe:
    def __init__(self) -> None:
        self.value = None
        self.put_calls = 0
        self.invalidations = 0

    async def get_channels(self, guild_id: int):
        assert guild_id == GUILD
        return self.value

    async def put_channels(self, guild_id: int, channels: list[dict[str, object]]) -> None:
        assert guild_id == GUILD
        self.value = channels
        self.put_calls += 1

    async def invalidate_channels(self, guild_id: int) -> None:
        assert guild_id == GUILD
        self.invalidations += 1


class RuntimeRepositoryProbe:
    def __init__(self) -> None:
        self.reads = 0
        self.enqueues = 0
        self.purges = 0
        self.discord_calls = 0

    async def channels(self, guild_id: int, actor_user_id: int, **_: object):
        assert (guild_id, actor_user_id) == (GUILD, USER)
        self.reads += 1
        return [
            {
                "guild_id": GUILD,
                "channel_id": CHANNEL,
                "parent_id": None,
                "type": 0,
                "name": "cache-only",
                "observability_state": "VISIBLE",
                "last_full_observed_at": datetime.now(UTC),
            }
        ]

    async def enqueue_job(self, job, *, requested_by: int, correlation_id):
        assert job.guild_id == GUILD
        assert requested_by == USER
        assert correlation_id is not None
        self.enqueues += 1
        return job.job_id

    async def purge_channels(self, **values: object) -> int:
        assert values["guild_id"] == GUILD
        assert values["actor_user_id"] == USER
        assert values["channel_ids"] == [CHANNEL]
        assert values["user_confirmed_deleted"] is True
        self.purges += 1
        return 1


def container():
    authorization = AuthorizationProbe()
    runtime = RuntimeRepositoryProbe()
    hot = HotCacheProbe()
    return SimpleNamespace(
        authorization=authorization,
        runtime_repository=runtime,
        hot_cache=hot,
    )


async def test_cache_hit_and_postgres_fallback_make_zero_discord_rest_calls() -> None:
    services = container()
    first = await cached_channels(str(GUILD), session(), services, include_hidden_deleted=False)
    second = await cached_channels(str(GUILD), session(), services, include_hidden_deleted=False)
    assert first == second
    assert first["source"] == "LOCAL_CACHE"
    assert services.runtime_repository.reads == 1
    assert services.hot_cache.put_calls == 1
    assert services.runtime_repository.discord_calls == 0


async def test_explicit_refresh_only_enqueues_durable_work() -> None:
    services = container()
    response = await enqueue_channel_refresh(str(GUILD), session(), services)
    assert response["status"] == "PENDING"
    assert response["freshness"] == "UNCHANGED"
    assert services.runtime_repository.enqueues == 1
    assert services.runtime_repository.discord_calls == 0


async def test_purge_preview_and_execution_are_strictly_local() -> None:
    services = container()
    selection = ChannelSelection(channel_ids=[str(CHANNEL)])
    preview = await preview_channel_purge(str(GUILD), selection, session(), services)
    assert preview["local_only"] is True
    assert preview["discord_delete_calls"] == 0
    result = await purge_channels(
        str(GUILD),
        PurgeRequest(
            channel_ids=[str(CHANNEL)],
            confirm_local_only=True,
            confirm_resource_deleted=True,
        ),
        session(),
        services,
    )
    assert result == {"purged": 1, "local_only": True, "discord_delete_calls": 0}
    assert services.runtime_repository.purges == 1
    # Redis invalidation is an outbox side effect; a Redis outage cannot turn a
    # committed PostgreSQL purge into an API failure.
    assert services.hot_cache.invalidations == 0
    assert services.runtime_repository.discord_calls == 0


async def test_purge_requires_explicit_local_only_confirmation() -> None:
    services = container()
    with pytest.raises(RuntimeError, match="CACHE_PURGE_CONFIRMATION_REQUIRED"):
        await purge_channels(
            str(GUILD),
            PurgeRequest(channel_ids=[str(CHANNEL)], confirm_local_only=False),
            session(),
            services,
        )


def test_channel_selection_rejects_duplicates() -> None:
    with pytest.raises(RuntimeError, match="DUPLICATE_CHANNEL_ID"):
        ChannelSelection(channel_ids=[str(CHANNEL), str(CHANNEL)]).parsed_ids()
