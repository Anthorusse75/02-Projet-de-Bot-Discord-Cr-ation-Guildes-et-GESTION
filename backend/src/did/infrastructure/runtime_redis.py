from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, TypeVar, cast
from uuid import UUID, uuid4

from redis.asyncio import Redis

from did.domain.discord_runtime import DiscordErrorKind, DiscordFailure
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


def _redis_int(value: object) -> int:
    if isinstance(value, bytes):
        return int(value.decode())
    return int(str(value))


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
            self.metrics.cache_misses += 1
            return None
        decoded = json.loads(raw)
        if not isinstance(decoded, dict) or decoded.get("guild_id") != str(guild_id):
            await self._redis.delete(self.channels_key(guild_id))
            self.metrics.cache_misses += 1
            return None
        channels = decoded.get("channels")
        if not isinstance(channels, list):
            await self._redis.delete(self.channels_key(guild_id))
            self.metrics.cache_misses += 1
            return None
        self.metrics.cache_hits += 1
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
    """A tenant-scoped, generation-bound lease with result fan-out."""

    _RELEASE_SCRIPT = (
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('del', KEYS[1]) else return 0 end"
    )
    _RENEW_SCRIPT = (
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end"
    )
    _ACQUIRE_OR_OBSERVE_SCRIPT = """
local current = redis.call('get', KEYS[1])
if not current then
    redis.call('set', KEYS[1], ARGV[1], 'PX', ARGV[2])
    return {1, ARGV[1]}
end
return {0, current}
"""

    def __init__(
        self,
        redis: Redis,
        *,
        after_observe: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._redis = redis
        self._after_observe = after_observe

    def _keys(self, guild_id: int, logical_key: str) -> tuple[str, str]:
        digest = hashlib.sha256(logical_key.encode()).hexdigest()
        namespace = guild_namespace(guild_id)
        return (
            namespace.key("singleflight", digest, "lock"),
            namespace.key("singleflight", digest, "result"),
        )

    @staticmethod
    def _generation_result_key(result_prefix: str, generation: str) -> str:
        return f"{result_prefix}:{generation}"

    @staticmethod
    def _decode_result(raw_result: str | bytes) -> dict[str, Any]:
        decoded = json.loads(raw_result)
        if not isinstance(decoded, dict):
            raise RuntimeError("coalesced operation returned an invalid result envelope")
        return decoded

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
        lock_key, result_prefix = self._keys(guild_id, logical_key)
        deadline = asyncio.get_running_loop().time() + wait_timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            requested_generation = uuid4().hex
            decision = cast(
                list[object],
                await self._redis.eval(
                    self._ACQUIRE_OR_OBSERVE_SCRIPT,
                    1,
                    lock_key,
                    requested_generation,
                    int(lease_seconds * 1000),
                ),
            )
            acquired = _redis_int(decision[0]) == 1
            raw_generation = decision[1]
            generation = (
                raw_generation.decode()
                if isinstance(raw_generation, bytes)
                else str(raw_generation)
            )
            if acquired:
                result_key = self._generation_result_key(result_prefix, generation)
                return await self._run_owner(
                    lock_key,
                    result_key,
                    generation,
                    operation,
                    lease_seconds=lease_seconds,
                )
            if self._after_observe is not None:
                await self._after_observe(generation)
            result_key = self._generation_result_key(result_prefix, generation)
            while asyncio.get_running_loop().time() < deadline:
                raw_result = await self._redis.get(result_key)
                if raw_result is not None:
                    decoded = self._decode_result(raw_result)
                    if decoded.get("generation") != generation:
                        raise RuntimeError("single-flight generation mismatch")
                    if decoded.get("status") == "ok" and isinstance(decoded.get("value"), dict):
                        return cast(T, decoded["value"])
                    if decoded.get("status") == "error":
                        raise RuntimeError(
                            f"coalesced operation failed: {decoded.get('type', 'unknown')}"
                        )
                current = await self._redis.get(lock_key)
                current_generation = (
                    (current.decode() if isinstance(current, bytes) else str(current))
                    if current is not None
                    else None
                )
                if current_generation != generation:
                    # The observed generation crashed, expired, or completed without a
                    # result.  A new outer iteration may recover as a fresh owner.
                    break
                await asyncio.sleep(0.025)
        raise TimeoutError("single-flight wait timed out after lease recovery attempts")

    async def _run_owner(
        self,
        lock_key: str,
        result_key: str,
        generation: str,
        operation: Callable[[], Awaitable[T]],
        *,
        lease_seconds: int,
    ) -> T:
        stopped = asyncio.Event()
        lost = asyncio.Event()

        async def heartbeat() -> None:
            interval = max(0.1, lease_seconds / 3)
            while not stopped.is_set():
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=interval)
                    return
                except TimeoutError:
                    pass
                try:
                    renewed = bool(
                        await self._redis.eval(
                            self._RENEW_SCRIPT,
                            1,
                            lock_key,
                            generation,
                            lease_seconds * 1000,
                        )
                    )
                except Exception:
                    renewed = False
                if not renewed:
                    lost.set()
                    return

        async def invoke() -> T:
            return await operation()

        heartbeat_task = asyncio.create_task(heartbeat())
        operation_task: asyncio.Task[T] = asyncio.create_task(invoke())
        lost_task = asyncio.create_task(lost.wait())
        try:
            done, _ = await asyncio.wait(
                {operation_task, lost_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if lost_task in done and lost.is_set() and not operation_task.done():
                operation_task.cancel()
                await asyncio.gather(operation_task, return_exceptions=True)
                raise TimeoutError("single-flight owner lease was lost")
            try:
                result = await operation_task
                if lost.is_set():
                    raise TimeoutError("single-flight owner lease was lost before publication")
                envelope = {"generation": generation, "status": "ok", "value": result}
            except Exception as exc:
                envelope = {
                    "generation": generation,
                    "status": "error",
                    "type": type(exc).__name__,
                }
                await self._redis.set(
                    result_key,
                    json.dumps(envelope, separators=(",", ":")),
                    ex=max(lease_seconds * 2, 5),
                )
                raise
            await self._redis.set(
                result_key,
                json.dumps(
                    envelope,
                    default=_json_default,
                    separators=(",", ":"),
                ),
                ex=max(lease_seconds * 2, 5),
            )
            return result
        finally:
            stopped.set()
            if not operation_task.done():
                operation_task.cancel()
            heartbeat_task.cancel()
            lost_task.cancel()
            await asyncio.gather(heartbeat_task, lost_task, operation_task, return_exceptions=True)
            await self._redis.eval(self._RELEASE_SCRIPT, 1, lock_key, generation)


class DistributedPermitLostError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DistributedPermit:
    token: str
    guild_id: int
    global_concurrency: int
    guild_concurrency: int


class RedisDiscordWorkloadCoordinator:
    """Crash-safe system-wide permits and shared Discord failure state."""

    _ACQUIRE_SCRIPT = """
local now = tonumber(ARGV[2])
redis.call('zremrangebyscore', KEYS[1], '-inf', now)
redis.call('zremrangebyscore', KEYS[2], '-inf', now)
local global_count = redis.call('zcard', KEYS[1])
local guild_count = redis.call('zcard', KEYS[2])
if global_count >= tonumber(ARGV[3]) or guild_count >= tonumber(ARGV[4]) then
    return {0, global_count, guild_count}
end
local expiry = now + tonumber(ARGV[5])
redis.call('zadd', KEYS[1], expiry, ARGV[1])
redis.call('zadd', KEYS[2], expiry, ARGV[1])
redis.call('pexpire', KEYS[1], tonumber(ARGV[5]) * 2)
redis.call('pexpire', KEYS[2], tonumber(ARGV[5]) * 2)
return {1, global_count + 1, guild_count + 1}
"""
    _RENEW_SCRIPT = """
if not redis.call('zscore', KEYS[1], ARGV[1]) or
   not redis.call('zscore', KEYS[2], ARGV[1]) then return 0 end
local expiry = tonumber(ARGV[2]) + tonumber(ARGV[3])
redis.call('zadd', KEYS[1], expiry, ARGV[1])
redis.call('zadd', KEYS[2], expiry, ARGV[1])
redis.call('pexpire', KEYS[1], tonumber(ARGV[3]) * 2)
redis.call('pexpire', KEYS[2], tonumber(ARGV[3]) * 2)
return 1
"""
    _RELEASE_SCRIPT = """
local removed_global = redis.call('zrem', KEYS[1], ARGV[1])
local removed_guild = redis.call('zrem', KEYS[2], ARGV[1])
return removed_global + removed_guild
"""
    _INVALID_SCRIPT = """
local cutoff = tonumber(ARGV[1]) - 600000
redis.call('zremrangebyscore', KEYS[1], '-inf', cutoff)
redis.call('zadd', KEYS[1], tonumber(ARGV[1]), ARGV[2])
redis.call('pexpire', KEYS[1], 660000)
return redis.call('zcard', KEYS[1])
"""

    def __init__(
        self,
        redis: Redis,
        *,
        global_concurrency: int,
        per_guild_concurrency: int,
        permit_ttl_seconds: float = 30.0,
        invalid_request_warning: int = 8_000,
    ) -> None:
        if global_concurrency < 1 or per_guild_concurrency < 1:
            raise ValueError("distributed concurrency limits must be positive")
        if per_guild_concurrency > global_concurrency or permit_ttl_seconds < 0.1:
            raise ValueError("distributed permit limits are inconsistent")
        self._redis = redis
        self._global_limit = global_concurrency
        self._guild_limit = per_guild_concurrency
        self._ttl_seconds = permit_ttl_seconds
        self._ttl_ms = int(permit_ttl_seconds * 1000)
        self._invalid_warning = invalid_request_warning
        self._global_key = "did:runtime:discord:permits:global"
        self._invalid_key = "did:runtime:discord:invalid-requests"
        self._halt_key = "did:runtime:discord:token-halted"
        self._rate_pressure_key = "did:runtime:discord:rate-penalty"

    @property
    def permit_ttl_seconds(self) -> float:
        return self._ttl_seconds

    def _guild_key(self, guild_id: int) -> str:
        return guild_namespace(guild_id).key("discord", "permits")

    async def acquire(self, guild_id: int) -> DistributedPermit:
        token = uuid4().hex
        while True:
            if await self.is_halted():
                raise RuntimeError("Discord token is halted system-wide")
            now_ms = int(datetime.now().timestamp() * 1000)
            decision = cast(
                list[object],
                await self._redis.eval(
                    self._ACQUIRE_SCRIPT,
                    2,
                    self._global_key,
                    self._guild_key(guild_id),
                    token,
                    now_ms,
                    self._global_limit,
                    self._guild_limit,
                    self._ttl_ms,
                ),
            )
            if _redis_int(decision[0]) == 1:
                return DistributedPermit(
                    token,
                    guild_id,
                    _redis_int(decision[1]),
                    _redis_int(decision[2]),
                )
            await asyncio.sleep(min(0.025, self._ttl_seconds / 4))

    async def renew(self, permit: DistributedPermit) -> bool:
        return bool(
            await self._redis.eval(
                self._RENEW_SCRIPT,
                2,
                self._global_key,
                self._guild_key(permit.guild_id),
                permit.token,
                int(datetime.now().timestamp() * 1000),
                self._ttl_ms,
            )
        )

    async def release(self, permit: DistributedPermit) -> None:
        await self._redis.eval(
            self._RELEASE_SCRIPT,
            2,
            self._global_key,
            self._guild_key(permit.guild_id),
            permit.token,
        )

    async def is_halted(self) -> bool:
        return bool(await self._redis.exists(self._halt_key))

    async def record_failure(self, failure: DiscordFailure) -> int:
        if failure.kind is DiscordErrorKind.UNAUTHORIZED:
            await self._redis.set(self._halt_key, "invalid", nx=True)
        if failure.kind is DiscordErrorKind.RATE_LIMITED:
            await self._redis.set(self._rate_pressure_key, "1", ex=30)
        if failure.kind not in {
            DiscordErrorKind.UNAUTHORIZED,
            DiscordErrorKind.FORBIDDEN,
            DiscordErrorKind.RATE_LIMITED,
        }:
            return await self.invalid_request_count()
        now_ms = int(datetime.now().timestamp() * 1000)
        return int(
            await self._redis.eval(
                self._INVALID_SCRIPT,
                1,
                self._invalid_key,
                now_ms,
                f"{now_ms}:{uuid4().hex}",
            )
        )

    async def invalid_request_count(self) -> int:
        cutoff = int(datetime.now().timestamp() * 1000) - 600_000
        await self._redis.zremrangebyscore(self._invalid_key, "-inf", cutoff)
        return int(await self._redis.zcard(self._invalid_key))

    async def invalid_request_budget_degraded(self) -> bool:
        return await self.invalid_request_count() >= self._invalid_warning


class RedisRuntimeWakeup:
    """Lossy global routing hints containing guild identifiers and nothing else."""

    _PRESSURE_REPORT_SCRIPT = """
local expired = redis.call('zrangebyscore', KEYS[2], '-inf', ARGV[3])
for _, member in ipairs(expired) do redis.call('hdel', KEYS[1], member) end
redis.call('zremrangebyscore', KEYS[2], '-inf', ARGV[3])
redis.call('hset', KEYS[1], ARGV[1], ARGV[2])
redis.call('zadd', KEYS[2], ARGV[4], ARGV[1])
redis.call('pexpire', KEYS[1], 60000)
redis.call('pexpire', KEYS[2], 60000)
return 1
"""
    _PRESSURE_READ_SCRIPT = """
local expired = redis.call('zrangebyscore', KEYS[2], '-inf', ARGV[1])
for _, member in ipairs(expired) do redis.call('hdel', KEYS[1], member) end
redis.call('zremrangebyscore', KEYS[2], '-inf', ARGV[1])
local values = redis.call('hvals', KEYS[1])
local maximum = 0
for _, value in ipairs(values) do
    if tonumber(value) > maximum then maximum = tonumber(value) end
end
return tostring(maximum)
"""

    def __init__(self, redis: Redis, *, reporter_id: str | None = None) -> None:
        self._redis = redis
        self._job_key = "did:runtime:routing:jobs"
        self._pressure_key = "did:runtime:discord:workload-pressure"
        self._pressure_expiry_key = "did:runtime:discord:workload-pressure-expiry"
        self._rate_pressure_key = "did:runtime:discord:rate-penalty"
        self._reporter_id = reporter_id or uuid4().hex

    async def signal_job(self, guild_id: int) -> None:
        if guild_id <= 0:
            raise ValueError("guild_id must be positive")
        await self._redis.zadd(self._job_key, {str(guild_id): datetime.now().timestamp()})

    async def pop_job_guilds(self, *, limit: int = 256) -> list[int]:
        if not 1 <= limit <= 1000:
            raise ValueError("wakeup batch limit must be between 1 and 1000")
        rows = await self._redis.zpopmin(self._job_key, count=limit)
        typed_rows = cast(list[tuple[str, float]], rows)
        return [int(member) for member, _ in typed_rows]

    async def set_rate_limit_pressure(self, pressure: float) -> None:
        if not 0.0 <= pressure <= 1.0:
            raise ValueError("rate-limit pressure must be between 0 and 1")
        now_ms = int(datetime.now().timestamp() * 1000)
        await self._redis.eval(
            self._PRESSURE_REPORT_SCRIPT,
            2,
            self._pressure_key,
            self._pressure_expiry_key,
            self._reporter_id,
            f"{pressure:.6f}",
            now_ms,
            now_ms + 30_000,
        )

    async def clear_rate_limit_pressure(self) -> None:
        await self._redis.hdel(self._pressure_key, self._reporter_id)
        await self._redis.zrem(self._pressure_expiry_key, self._reporter_id)

    async def rate_limit_pressure(self) -> float:
        now_ms = int(datetime.now().timestamp() * 1000)
        raw = await self._redis.eval(
            self._PRESSURE_READ_SCRIPT,
            2,
            self._pressure_key,
            self._pressure_expiry_key,
            now_ms,
        )
        shared = float(raw or 0.0)
        penalty = 1.0 if await self._redis.exists(self._rate_pressure_key) else 0.0
        return min(1.0, max(0.0, shared, penalty))


class OutboxPublisher:
    def __init__(
        self,
        repository: RuntimeRepository,
        pubsub: TenantPubSub,
        *,
        hot_cache: RedisHotCache | None = None,
        wakeup: RedisRuntimeWakeup | None = None,
        after_publish: Callable[[], object] | None = None,
        publisher_id: str | None = None,
        lease_seconds: float = 30.0,
    ) -> None:
        self._repository = repository
        self._pubsub = pubsub
        self._hot_cache = hot_cache
        self._wakeup = wakeup
        self._after_publish = after_publish
        self._publisher_id = publisher_id or f"outbox-{uuid4().hex}"
        self._lease_seconds = lease_seconds

    async def _apply_side_effects(self, guild_id: int, row: dict[str, Any]) -> None:
        topic = str(row["topic"])
        if self._hot_cache is not None and topic in {
            "discord.cache.changed",
            "discord.cache.reconciled",
            "discord.cache.purged",
        }:
            await self._hot_cache.invalidate_channels(guild_id)
        if self._wakeup is not None and topic == "discord.io.job.enqueued":
            await self._wakeup.signal_job(guild_id)
        await self._pubsub.publish(
            guild_id,
            {
                "event_id": str(row["event_id"]),
                "topic": topic,
                "payload": dict(row["payload"]),
                "correlation_id": str(row["correlation_id"]),
            },
        )

    async def publish_guild(self, guild_id: int, *, limit: int = 100) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("outbox publish limit must be between 1 and 1000")
        published = 0
        for _ in range(limit):
            pending = await self._repository.lease_outbox(
                guild_id,
                lease_owner=self._publisher_id,
                limit=1,
                lease_seconds=self._lease_seconds,
            )
            if not pending:
                break
            row = pending[0]
            event_id = UUID(str(row["event_id"]))
            lease_token = UUID(str(row["lease_token"]))
            stopped = asyncio.Event()
            lost = asyncio.Event()

            async def renew(
                stopped_event: asyncio.Event = stopped,
                current_event_id: UUID = event_id,
                current_token: UUID = lease_token,
                lost_event: asyncio.Event = lost,
            ) -> None:
                interval = max(0.01, self._lease_seconds / 5)
                while not stopped_event.is_set():
                    try:
                        await asyncio.wait_for(stopped_event.wait(), timeout=interval)
                        return
                    except TimeoutError:
                        pass
                    try:
                        renewed = await self._repository.renew_outbox_lease(
                            guild_id,
                            current_event_id,
                            lease_owner=self._publisher_id,
                            lease_token=current_token,
                            lease_seconds=self._lease_seconds,
                        )
                    except Exception:
                        renewed = False
                    if not renewed:
                        lost_event.set()
                        return

            heartbeat = asyncio.create_task(renew())
            try:
                await self._apply_side_effects(guild_id, row)
                if self._after_publish is not None:
                    outcome = self._after_publish()
                    if inspect.isawaitable(outcome):
                        await outcome
                if lost.is_set():
                    raise RuntimeError("outbox publication lease expired during side effects")
                acknowledged = await self._repository.mark_outbox_published(
                    guild_id,
                    event_id,
                    lease_owner=self._publisher_id,
                    lease_token=lease_token,
                )
                if not acknowledged:
                    raise RuntimeError("outbox publication lease was lost before acknowledgement")
                published += 1
            except Exception:
                await self._repository.mark_outbox_retry(
                    guild_id,
                    event_id,
                    lease_owner=self._publisher_id,
                    lease_token=lease_token,
                )
                raise
            finally:
                stopped.set()
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
        return published
