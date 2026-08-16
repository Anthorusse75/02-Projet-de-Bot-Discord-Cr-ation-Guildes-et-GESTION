import os

import pytest

from did.infrastructure.redis import create_redis_client, guild_namespace, redis_is_ready

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
