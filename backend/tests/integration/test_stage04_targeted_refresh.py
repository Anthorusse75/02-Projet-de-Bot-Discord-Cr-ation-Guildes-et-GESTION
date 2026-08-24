from __future__ import annotations

import asyncio
import os

import pytest

from did.application.auth.service import AuthorizationDenied, AuthorizationService
from did.infrastructure.redis import create_redis_client
from did.infrastructure.runtime_metrics import RuntimeMetrics
from did.infrastructure.runtime_redis import RedisSingleFlight
from did.oauth.stores import RedisActorMembershipStore

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

REDIS_URL = os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0")
GUILD = 430303030303030301
MEMBER = 430303030303030302
ROLE = 430303030303030303


class CountingMemberClient:
    def __init__(self, *, fails: bool = False) -> None:
        self.calls = 0
        self.fails = fails

    async def get_member_roles(self, guild_id: int, user_id: int) -> tuple[int, ...]:
        assert (guild_id, user_id) == (GUILD, MEMBER)
        self.calls += 1
        await asyncio.sleep(0.05)
        if self.fails:
            raise RuntimeError("controlled refresh failure")
        return (ROLE,)


async def test_three_sensitive_consumers_share_one_targeted_actor_refresh() -> None:
    redis = create_redis_client(REDIS_URL)
    client = CountingMemberClient()
    metrics = RuntimeMetrics()
    service = AuthorizationService(
        auth=None,  # type: ignore[arg-type]
        repository=None,  # type: ignore[arg-type]
        membership_store=RedisActorMembershipStore(redis, ttl_seconds=60),
        member_client=client,
        freshness_seconds=60,
        membership_singleflight=RedisSingleFlight(redis),
        metrics=metrics,
    )
    try:
        await redis.flushdb()
        memberships = await asyncio.gather(
            *(service._membership(guild_id=GUILD, user_id=MEMBER, force=True) for _ in range(3))
        )
        assert [item.role_ids for item in memberships] == [(ROLE,)] * 3
        assert client.calls == 1
        assert metrics.targeted_actor_refreshes == 1
    finally:
        await redis.aclose()


async def test_targeted_refresh_failure_is_coalesced_and_fails_closed() -> None:
    redis = create_redis_client(REDIS_URL)
    client = CountingMemberClient(fails=True)
    service = AuthorizationService(
        auth=None,  # type: ignore[arg-type]
        repository=None,  # type: ignore[arg-type]
        membership_store=RedisActorMembershipStore(redis, ttl_seconds=60),
        member_client=client,
        freshness_seconds=60,
        membership_singleflight=RedisSingleFlight(redis),
    )
    try:
        await redis.flushdb()
        failures = await asyncio.gather(
            *(service._membership(guild_id=GUILD, user_id=MEMBER, force=True) for _ in range(3)),
            return_exceptions=True,
        )
        assert client.calls == 1
        assert all(isinstance(item, AuthorizationDenied) for item in failures)
        assert all(str(item) == "GUILD_MEMBERSHIP_REQUIRED" for item in failures)
    finally:
        await redis.aclose()
