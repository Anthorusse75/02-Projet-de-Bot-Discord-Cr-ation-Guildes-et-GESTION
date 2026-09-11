import os

import pytest

from did.infrastructure.redis import (
    create_redis_client,
    guild_namespace,
    purge_guild_namespace,
    redis_is_ready,
)
from did.infrastructure.runtime_redis import RedisRuntimeWakeup

pytestmark = pytest.mark.integration


async def test_real_redis_uses_tenant_namespace() -> None:
    client = create_redis_client(os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0"))
    key = guild_namespace(333333333333333333).key("stage01", "probe")
    try:
        assert await redis_is_ready(client)
        await client.set(key, "ok", ex=30)
        assert await client.get(key) == "ok"
        assert key.startswith("did:guild:333333333333333333:")
    finally:
        await client.delete(key)
        await client.aclose()


async def test_guild_redis_purge_removes_only_tenant_keys_and_job_routing() -> None:
    client = create_redis_client(os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0"))
    guild_id = 333333333333333334
    other_guild_id = 333333333333333335
    guild_keys = [
        guild_namespace(guild_id).key("cache", "channels"),
        guild_namespace(guild_id).key("events", "v1"),
    ]
    other_key = guild_namespace(other_guild_id).key("cache", "channels")
    wakeup = RedisRuntimeWakeup(client)
    try:
        await client.mset({guild_keys[0]: "channels", guild_keys[1]: "events", other_key: "other"})
        await wakeup.signal_job(guild_id)
        await wakeup.signal_job(other_guild_id)

        assert await purge_guild_namespace(client, guild_id) == 2
        assert await client.exists(*guild_keys) == 0
        assert await client.get(other_key) == "other"
        assert await wakeup.remove_job_guild(guild_id) is True
        assert await client.zscore("did:runtime:routing:jobs", str(guild_id)) is None
        assert await client.zscore("did:runtime:routing:jobs", str(other_guild_id)) is not None
    finally:
        await purge_guild_namespace(client, guild_id)
        await purge_guild_namespace(client, other_guild_id)
        await wakeup.remove_job_guild(guild_id)
        await wakeup.remove_job_guild(other_guild_id)
        await client.aclose()
