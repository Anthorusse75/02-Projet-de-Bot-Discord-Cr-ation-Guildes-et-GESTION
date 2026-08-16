import asyncio
import os

import pytest

from did.infrastructure.redis import create_redis_client
from did.oauth.stores import (
    OAuthStateError,
    RedisOAuthStateStore,
    RedisSessionStore,
)

pytestmark = [pytest.mark.integration, pytest.mark.security]


async def test_oauth_state_is_ttl_bound_single_use_and_rejects_open_redirect() -> None:
    redis = create_redis_client(os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0"))
    store = RedisOAuthStateStore(redis, ttl_seconds=60)
    try:
        state = await store.create(return_to="/guilds")
        assert state.browser_binding is not None
        with pytest.raises(OAuthStateError, match="binding"):
            await store.consume(state.state, "wrong-browser-binding")
        with pytest.raises(OAuthStateError, match="missing"):
            await store.consume(state.state, None)
        assert (await store.consume(state.state, state.browser_binding)).return_to == "/guilds"
        with pytest.raises(OAuthStateError, match="already used"):
            await store.consume(state.state, state.browser_binding)
        with pytest.raises(OAuthStateError, match="allowlisted"):
            await store.create(return_to="https://attacker.example/")
        with pytest.raises(OAuthStateError, match="allowlisted"):
            await store.create(return_to="//attacker.example/")
        expiring_store = RedisOAuthStateStore(redis, ttl_seconds=1)
        expiring_state = await expiring_store.create(return_to="/guilds")
        assert expiring_state.browser_binding is not None
        await asyncio.sleep(1.05)
        with pytest.raises(OAuthStateError, match="expired"):
            await expiring_store.consume(expiring_state.state, expiring_state.browser_binding)
    finally:
        await redis.aclose()


async def test_session_rotation_logout_and_absolute_expiration() -> None:
    redis = create_redis_client(os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0"))
    test_session_material = "stage02-test-" + ("x" * 32)
    store = RedisSessionStore(
        redis,
        session_secret=test_session_material,
        idle_ttl_seconds=30,
        absolute_ttl_seconds=30,
    )
    expiring = RedisSessionStore(
        redis,
        session_secret=test_session_material,
        idle_ttl_seconds=1,
        absolute_ttl_seconds=1,
    )
    try:
        fixed = await store.create(discord_user_id=10, previous_session_id=None)
        rotated = await store.create(discord_user_id=10, previous_session_id=fixed.session_id)
        assert rotated.session_id != fixed.session_id
        assert await store.load(fixed.session_id) is None
        assert await store.load(rotated.session_id) is not None
        await store.revoke(rotated.session_id)
        assert await store.load(rotated.session_id) is None

        short = await expiring.create(discord_user_id=11, previous_session_id=None)
        await asyncio.sleep(1.05)
        assert await expiring.load(short.session_id) is None
    finally:
        await redis.aclose()
