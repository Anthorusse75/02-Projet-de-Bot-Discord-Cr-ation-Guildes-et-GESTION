from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import date, datetime
from typing import Any, TypeVar, cast
from uuid import UUID, uuid4

from redis.asyncio import Redis

from did.infrastructure.redis import guild_namespace
from did.infrastructure.runtime_metrics import RuntimeMetrics
from did.infrastructure.runtime_repository import RuntimeRepository

T = TypeVar("T", bound=dict[str, Any])


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"unsupported cache value: {type(value).__name__}")


class RedisHotCache:
    def __init__(
        self,
        redis: Redis,
        *,
        ttl_seconds: int = 300,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        self._redis = redis
        self._ttl_seconds = ttl_seconds
        self.metrics = metrics or RuntimeMetrics()

    def channels_key(self, guild_id: int) -> str:
        return guild_namespace(guild_id).key("cache", "channels", "v1")

    async def get_channels(self, guild_id: int) -> list[dict[str, Any]] | None:
        raw = await self._redis.get(self.channels_key(guild_id))
        if raw is None:
            return None
        decoded = json.loads(raw)
        if not isinstance(decoded, dict) or decoded.get("guild_id") != str(guild_id):
            await self._redis.delete(self.channels_key(guild_id))
            return None
        channels = decoded.get("channels")
        if not isinstance(channels, list):
            await self._redis.delete(self.channels_key(guild_id))
            return None
        return [dict(channel) for channel in channels if isinstance(channel, dict)]

    async def put_channels(self, guild_id: int, channels: list[dict[str, Any]]) -> None:
        encoded = json.dumps(
            {"guild_id": str(guild_id), "channels": channels},
            default=_json_default,
            separators=(",", ":"),
        )
        await self._redis.set(self.channels_key(guild_id), encoded, ex=self._ttl_seconds)

    async def invalidate_channels(self, guild_id: int) -> None:
        await self._redis.delete(self.channels_key(guild_id))

    async def rebuild_channels(
        self, repository: RuntimeRepository, guild_id: int
    ) -> list[dict[str, Any]]:
        channels = await repository.channels(guild_id, None, include_hidden_deleted=True)
        await self.put_channels(guild_id, channels)
        self.metrics.redis_rebuilds += 1
        return channels


class TenantPubSub:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def channel(self, guild_id: int) -> str:
        return guild_namespace(guild_id).key("events", "v1")

    async def publish(self, guild_id: int, payload: dict[str, Any]) -> int:
        scoped = {**payload, "guild_id": str(guild_id)}
        return int(
            await self._redis.publish(
                self.channel(guild_id),
                json.dumps(scoped, default=_json_default, separators=(",", ":")),
            )
        )

    @staticmethod
    def decode_for_guild(guild_id: int, raw: str | bytes) -> dict[str, Any] | None:
        if isinstance(raw, bytes):
            raw = raw.decode()
        decoded = json.loads(raw)
        if not isinstance(decoded, dict) or decoded.get("guild_id") != str(guild_id):
            return None
        return decoded

    async def subscribe(self, guild_id: int) -> AsyncGenerator[dict[str, Any]]:
        pubsub = self._redis.pubsub()
        channel = self.channel(guild_id)
        await pubsub.subscribe(channel)
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    await asyncio.sleep(0)
                    continue
                decoded = self.decode_for_guild(guild_id, message["data"])
                if decoded is not None:
                    yield decoded
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()  # type: ignore[no-untyped-call]


class RedisSingleFlight:
    """A tenant-scoped lease with result fan-out and crash-expiry recovery."""

    _RELEASE_SCRIPT = (
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('del', KEYS[1]) else return 0 end"
    )

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _keys(self, guild_id: int, logical_key: str) -> tuple[str, str]:
        digest = hashlib.sha256(logical_key.encode()).hexdigest()
        namespace = guild_namespace(guild_id)
        return (
            namespace.key("singleflight", digest, "lock"),
            namespace.key("singleflight", digest, "result"),
        )

    async def run(
        self,
        guild_id: int,
        logical_key: str,
        operation: Callable[[], Awaitable[T]],
        *,
        lease_seconds: int = 10,
        wait_timeout_seconds: float = 15.0,
    ) -> T:
        if lease_seconds < 1 or wait_timeout_seconds <= 0:
            raise ValueError("single-flight timeouts must be positive")
        lock_key, result_key = self._keys(guild_id, logical_key)
        deadline = asyncio.get_running_loop().time() + wait_timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            # A peer may have published and released between two polling iterations.
            # Consume that short-lived result before trying to become a second owner.
            raw_result = await self._redis.get(result_key)
            if raw_result is not None:
                decoded = json.loads(raw_result)
                if decoded.get("status") == "ok" and isinstance(decoded.get("value"), dict):
                    return cast(T, decoded["value"])
                if decoded.get("status") == "error":
                    raise RuntimeError(
                        f"coalesced operation failed: {decoded.get('type', 'unknown')}"
                    )
            token = uuid4().hex
            acquired = bool(await self._redis.set(lock_key, token, nx=True, ex=lease_seconds))
            if acquired:
                await self._redis.delete(result_key)
                try:
                    result = await operation()
                    await self._redis.set(
                        result_key,
                        json.dumps(
                            {"status": "ok", "value": result},
                            default=_json_default,
                            separators=(",", ":"),
                        ),
                        ex=max(lease_seconds * 2, 5),
                    )
                    return result
                except Exception as exc:
                    await self._redis.set(
                        result_key,
                        json.dumps(
                            {"status": "error", "type": type(exc).__name__},
                            separators=(",", ":"),
                        ),
                        ex=max(lease_seconds * 2, 5),
                    )
                    raise
                finally:
                    await self._redis.eval(self._RELEASE_SCRIPT, 1, lock_key, token)
            await asyncio.sleep(0.025)
        raise TimeoutError("single-flight wait timed out after lease recovery attempts")


class OutboxPublisher:
    def __init__(
        self,
        repository: RuntimeRepository,
        pubsub: TenantPubSub,
        *,
        after_publish: Callable[[], object] | None = None,
    ) -> None:
        self._repository = repository
        self._pubsub = pubsub
        self._after_publish = after_publish

    async def publish_guild(self, guild_id: int, *, limit: int = 100) -> int:
        pending = await self._repository.pending_outbox(guild_id, limit=limit)
        published = 0
        for row in pending:
            event_id = UUID(str(row["event_id"]))
            try:
                await self._pubsub.publish(
                    guild_id,
                    {
                        "event_id": str(event_id),
                        "topic": str(row["topic"]),
                        "payload": dict(row["payload"]),
                        "correlation_id": str(row["correlation_id"]),
                    },
                )
                if self._after_publish is not None:
                    outcome = self._after_publish()
                    if inspect.isawaitable(outcome):
                        await outcome
                await self._repository.mark_outbox_published(guild_id, event_id)
                published += 1
            except Exception:
                await self._repository.mark_outbox_retry(guild_id, event_id)
                raise
        return published
