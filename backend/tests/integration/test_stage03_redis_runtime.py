import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from did.api.runtime_cache import cached_channels
from did.application.discord_runtime import normalize_gateway_dispatch
from did.domain.discord_runtime import DiscordErrorKind, DiscordFailure
from did.infrastructure.database import create_database_engine, create_session_factory
from did.infrastructure.redis import create_redis_client
from did.infrastructure.runtime_redis import (
    OutboxPublisher,
    RedisDiscordWorkloadCoordinator,
    RedisHotCache,
    RedisRuntimeWakeup,
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


def channel_update(name: str, *, sequence: int):
    envelope = normalize_gateway_dispatch(
        {
            "op": 0,
            "s": sequence,
            "t": "CHANNEL_UPDATE",
            "d": {
                "guild_id": str(GUILD_A),
                "id": str(CHANNEL_A),
                "type": 0,
                "position": 0,
                "parent_id": None,
                "name": name,
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

        async def operation_v2() -> dict[str, object]:
            nonlocal calls
            calls += 1
            return {"value": "new-generation"}

        second_generation = await flight.run(GUILD_A, "same-request", operation_v2)
        assert second_generation == {"value": "new-generation"}
        assert calls == 2

        concurrent_failure_calls = 0

        async def concurrent_failure() -> dict[str, object]:
            nonlocal concurrent_failure_calls
            concurrent_failure_calls += 1
            await asyncio.sleep(0.05)
            raise ValueError("controlled concurrent failure")

        failures = await asyncio.gather(
            *(flight.run(GUILD_A, "concurrent-failure", concurrent_failure) for _ in range(3)),
            return_exceptions=True,
        )
        assert concurrent_failure_calls == 1
        assert all(isinstance(failure, Exception) for failure in failures)

        sequential_failure_calls = 0

        async def failure() -> dict[str, object]:
            nonlocal sequential_failure_calls
            sequential_failure_calls += 1
            raise ValueError("controlled")

        with pytest.raises(ValueError, match="controlled"):
            await flight.run(GUILD_A, "failure", failure)
        with pytest.raises(ValueError, match="controlled"):
            await flight.run(GUILD_A, "failure", failure)
        assert sequential_failure_calls == 2

        tenant_b = await flight.run(GUILD_B, "same-request", operation_v2)
        assert tenant_b == {"value": "new-generation"}

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


async def test_singleflight_acquire_or_observe_forced_release_race() -> None:
    redis = create_redis_client(REDIS_URL)
    waiter_observed = asyncio.Event()
    owner_may_finish = asyncio.Event()
    waiter_may_continue = asyncio.Event()
    calls = 0

    async def after_observe(_: str) -> None:
        waiter_observed.set()
        await waiter_may_continue.wait()

    flight = RedisSingleFlight(redis, after_observe=after_observe)

    async def operation() -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            await owner_may_finish.wait()
        return {"generation_call": calls}

    try:
        await redis.flushdb()
        owner = asyncio.create_task(flight.run(GUILD_A, "forced-race", operation))
        await asyncio.sleep(0)
        waiter = asyncio.create_task(flight.run(GUILD_A, "forced-race", operation))
        await asyncio.wait_for(waiter_observed.wait(), timeout=1)
        owner_may_finish.set()
        assert await asyncio.wait_for(owner, timeout=1) == {"generation_call": 1}
        waiter_may_continue.set()
        assert await asyncio.wait_for(waiter, timeout=1) == {"generation_call": 1}
        assert calls == 1

        sequential = await flight.run(GUILD_A, "forced-race", operation)
        assert sequential == {"generation_call": 2}
        assert calls == 2
    finally:
        await redis.aclose()


async def test_distributed_failure_budget_pressure_and_halt_are_shared() -> None:
    redis = create_redis_client(REDIS_URL)
    first = RedisDiscordWorkloadCoordinator(
        redis, global_concurrency=2, per_guild_concurrency=1, invalid_request_warning=2
    )
    second = RedisDiscordWorkloadCoordinator(
        redis, global_concurrency=2, per_guild_concurrency=1, invalid_request_warning=2
    )
    try:
        await redis.flushdb()
        assert await first.record_failure(DiscordFailure(DiscordErrorKind.FORBIDDEN, 403)) == 1
        assert await second.invalid_request_count() == 1
        await first.record_failure(DiscordFailure(DiscordErrorKind.RATE_LIMITED, 429))
        assert await second.invalid_request_budget_degraded() is True
        assert await RedisRuntimeWakeup(redis).rate_limit_pressure() == 1.0
        await first.record_failure(DiscordFailure(DiscordErrorKind.UNAUTHORIZED, 401))
        assert await second.is_halted() is True
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
            raise asyncio.CancelledError("controlled process loss before ack")

        with pytest.raises(asyncio.CancelledError, match="controlled process loss before ack"):
            await OutboxPublisher(
                repository,
                pubsub,
                after_publish=crash_after_publish,
                publisher_id="crashed-outbox-worker",
                lease_seconds=0.1,
            ).publish_guild(GUILD_A)
        assert await repository.pending_outbox(GUILD_A) == []
        await asyncio.sleep(0.12)
        assert await OutboxPublisher(repository, pubsub).publish_guild(GUILD_A) == 1
        assert await OutboxPublisher(repository, pubsub).publish_guild(GUILD_A) == 0
    finally:
        await redis.aclose()
        await engine.dispose()


async def test_outbox_multiworker_leases_prevent_publication_storm() -> None:
    repository, engine = await seeded_repository()
    redis = create_redis_client(REDIS_URL)
    published_side_effects = 0
    both_started = asyncio.Event()

    class PubSubProbe:
        async def publish(self, guild_id: int, payload: dict[str, object]) -> int:
            nonlocal published_side_effects
            assert guild_id == GUILD_A
            published_side_effects += 1
            both_started.set()
            await asyncio.sleep(0.18)
            return 1

    try:
        await repository.ingest_gateway_event(channel_create())
        first = OutboxPublisher(
            repository,
            PubSubProbe(),  # type: ignore[arg-type]
            publisher_id="outbox-worker-a",
            lease_seconds=0.1,
        )
        second = OutboxPublisher(
            repository,
            PubSubProbe(),  # type: ignore[arg-type]
            publisher_id="outbox-worker-b",
            lease_seconds=0.1,
        )
        results = await asyncio.gather(first.publish_guild(GUILD_A), second.publish_guild(GUILD_A))
        assert sum(results) == 1
        assert published_side_effects == 1
        assert both_started.is_set()
        assert await repository.pending_outbox(GUILD_A) == []
    finally:
        await redis.aclose()
        await engine.dispose()


async def test_gateway_cache_invalidation_retries_durably_after_redis_failure() -> None:
    repository, engine = await seeded_repository()
    redis = create_redis_client(REDIS_URL)
    pubsub = TenantPubSub(redis)
    hot = RedisHotCache(redis)

    class AuthorizationProbe:
        discord_calls = 0

        async def authorize(self, **_: object) -> None:
            return None

    container = SimpleNamespace(
        authorization=AuthorizationProbe(),
        runtime_repository=repository,
        hot_cache=hot,
    )
    session = SimpleNamespace(discord_user_id=GUILD_A + 100)
    try:
        await redis.flushdb()
        await repository.ingest_gateway_event(channel_create())
        assert await OutboxPublisher(repository, pubsub, hot_cache=hot).publish_guild(GUILD_A) == 1
        initial = await cached_channels(
            str(GUILD_A), session, container, include_hidden_deleted=False
        )
        assert initial["channels"][0]["name"] == "durable"

        await repository.ingest_gateway_event(channel_update("projected-new-value", sequence=2))

        class RedisDownHotCache:
            async def invalidate_channels(self, guild_id: int) -> None:
                assert guild_id == GUILD_A
                raise ConnectionError("controlled hot-cache outage")

        with pytest.raises(ConnectionError, match="controlled hot-cache outage"):
            await OutboxPublisher(
                repository,
                pubsub,
                hot_cache=RedisDownHotCache(),  # type: ignore[arg-type]
            ).publish_guild(GUILD_A)
        still_old = await hot.get_channels(GUILD_A)
        assert still_old is not None
        assert still_old[0]["name"] == "durable"

        await asyncio.sleep(1.05)
        assert await OutboxPublisher(repository, pubsub, hot_cache=hot).publish_guild(GUILD_A) == 1
        assert await hot.get_channels(GUILD_A) is None
        rebuilt = await cached_channels(
            str(GUILD_A), session, container, include_hidden_deleted=False
        )
        assert rebuilt["channels"][0]["name"] == "projected-new-value"
        assert container.authorization.discord_calls == 0
        assert await repository.pending_outbox(GUILD_A) == []
    finally:
        await redis.aclose()
        await engine.dispose()
