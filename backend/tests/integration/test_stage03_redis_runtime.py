import asyncio
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from did.application.discord_runtime import normalize_gateway_dispatch
from did.infrastructure.database import create_database_engine, create_session_factory
from did.infrastructure.redis import create_redis_client
from did.infrastructure.runtime_redis import (
    OutboxPublisher,
    RedisHotCache,
    RedisSingleFlight,
    TenantPubSub,
)
from did.infrastructure.runtime_repository import RuntimeRepository

pytestmark = [pytest.mark.integration, pytest.mark.security]

APP_URL = os.environ.get(
    "DID_DATABASE_URL",
    "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test",
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
REDIS_URL = os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0")
GUILD_A = 230303030303030301
GUILD_B = 230303030303030302
CHANNEL_A = 230303030303030311


async def seeded_repository() -> tuple[RuntimeRepository, object]:
    admin = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with admin.begin() as connection:
            await connection.execute(text("TRUNCATE guild_installations CASCADE"))
            await connection.execute(
                text(
                    "INSERT INTO guild_installations "
                    "(guild_id, name, installation_status) VALUES "
                    "(:a, 'Guild A', 'ACTIVE'), (:b, 'Guild B', 'ACTIVE')"
                ),
                {"a": GUILD_A, "b": GUILD_B},
            )
    finally:
        await admin.dispose()
    engine = create_database_engine(APP_URL, pool_size=3)
    return RuntimeRepository(create_session_factory(engine)), engine


def channel_create():
    envelope = normalize_gateway_dispatch(
        {
            "op": 0,
            "s": 1,
            "t": "CHANNEL_CREATE",
            "d": {
                "guild_id": str(GUILD_A),
                "id": str(CHANNEL_A),
                "type": 0,
                "position": 0,
                "parent_id": None,
                "name": "durable",
                "topic": None,
                "nsfw": False,
                "permission_overwrites": [],
            },
        },
        discord_session_id="redis-runtime-session",
        received_at=datetime.now(UTC),
    )
    assert envelope is not None
    return envelope


async def test_redis_loss_rebuilds_from_postgres_without_durable_loss() -> None:
    repository, engine = await seeded_repository()
    redis = create_redis_client(REDIS_URL)
    hot = RedisHotCache(redis)
    try:
        await redis.flushdb()
        await repository.ingest_gateway_event(channel_create())
        projected = await hot.rebuild_channels(repository, GUILD_A)
        assert projected[0]["name"] == "durable"
        await redis.flushdb()
        assert await hot.get_channels(GUILD_A) is None
        rebuilt = await hot.rebuild_channels(repository, GUILD_A)
        assert rebuilt[0]["channel_id"] == CHANNEL_A
        assert (await repository.channels(GUILD_A, None, include_hidden_deleted=True))[0][
            "name"
        ] == "durable"
        assert hot.channels_key(GUILD_A) != hot.channels_key(GUILD_B)
    finally:
        await redis.aclose()
        await engine.dispose()


async def test_singleflight_success_failure_timeout_and_expired_owner_recovery() -> None:
    redis = create_redis_client(REDIS_URL)
    flight = RedisSingleFlight(redis)
    calls = 0

    async def operation() -> dict[str, object]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"value": "shared"}

    try:
        await redis.flushdb()
        results = await asyncio.gather(
            *(flight.run(GUILD_A, "same-request", operation) for _ in range(3))
        )
        assert results == [{"value": "shared"}] * 3
        assert calls == 1

        async def failure() -> dict[str, object]:
            raise ValueError("controlled")

        with pytest.raises(ValueError, match="controlled"):
            await flight.run(GUILD_A, "failure", failure)
        with pytest.raises(RuntimeError, match="coalesced operation failed"):
            await flight.run(GUILD_A, "failure", failure)

        lock_key, _ = flight._keys(GUILD_A, "expired-owner")
        await redis.set(lock_key, "crashed-worker", ex=1)
        recovered = await flight.run(
            GUILD_A,
            "expired-owner",
            operation,
            lease_seconds=1,
            wait_timeout_seconds=2.5,
        )
        assert recovered == {"value": "shared"}

        lock_key, _ = flight._keys(GUILD_A, "timeout")
        await redis.set(lock_key, "long-owner", ex=10)
        with pytest.raises(TimeoutError):
            await flight.run(
                GUILD_A,
                "timeout",
                operation,
                lease_seconds=1,
                wait_timeout_seconds=0.05,
            )
    finally:
        await redis.aclose()


async def test_pubsub_is_strictly_tenant_partitioned() -> None:
    redis = create_redis_client(REDIS_URL)
    pubsub = TenantPubSub(redis)
    stream_a = pubsub.subscribe(GUILD_A)
    stream_b = pubsub.subscribe(GUILD_B)
    receive_a = asyncio.create_task(anext(stream_a))
    receive_b = asyncio.create_task(anext(stream_b))
    try:
        await asyncio.sleep(0.05)
        await pubsub.publish(GUILD_A, {"kind": "A"})
        await pubsub.publish(GUILD_B, {"kind": "B"})
        event_a, event_b = await asyncio.wait_for(asyncio.gather(receive_a, receive_b), timeout=2)
        assert event_a == {"kind": "A", "guild_id": str(GUILD_A)}
        assert event_b == {"kind": "B", "guild_id": str(GUILD_B)}
        assert (
            TenantPubSub.decode_for_guild(GUILD_A, f'{{"guild_id":"{GUILD_B}","kind":"forged"}}')
            is None
        )
        assert pubsub.channel(GUILD_A) != pubsub.channel(GUILD_B)
    finally:
        await stream_a.aclose()
        await stream_b.aclose()
        await redis.aclose()


async def test_outbox_survives_publish_failure_and_publish_before_ack_crash() -> None:
    repository, engine = await seeded_repository()
    redis = create_redis_client(REDIS_URL)
    pubsub = TenantPubSub(redis)
    try:
        await repository.ingest_gateway_event(channel_create())

        class RedisDownPubSub:
            async def publish(self, guild_id: int, payload: dict[str, object]) -> int:
                raise ConnectionError("controlled redis outage")

        with pytest.raises(ConnectionError, match="controlled redis outage"):
            await OutboxPublisher(repository, RedisDownPubSub()).publish_guild(GUILD_A)  # type: ignore[arg-type]
        assert len(await repository.pending_outbox(GUILD_A)) == 0
        await asyncio.sleep(1.05)
        assert len(await repository.pending_outbox(GUILD_A)) == 1

        def crash_after_publish() -> None:
            raise RuntimeError("controlled crash before ack")

        with pytest.raises(RuntimeError, match="controlled crash before ack"):
            await OutboxPublisher(
                repository, pubsub, after_publish=crash_after_publish
            ).publish_guild(GUILD_A)
        await asyncio.sleep(2.05)
        assert await OutboxPublisher(repository, pubsub).publish_guild(GUILD_A) == 1
        assert await OutboxPublisher(repository, pubsub).publish_guild(GUILD_A) == 0
    finally:
        await redis.aclose()
        await engine.dispose()
