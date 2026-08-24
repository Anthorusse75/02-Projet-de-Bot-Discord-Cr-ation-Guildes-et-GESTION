from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar
from uuid import uuid4

from redis.asyncio import Redis

from did.infrastructure.redis import guild_namespace

T = TypeVar("T")


class GuildMutationLockUnavailable(RuntimeError):
    pass


class RedisGuildMutationLock:
    _RENEW = (
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end"
    )
    _RELEASE = (
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('del', KEYS[1]) else return 0 end"
    )

    def __init__(self, redis: Redis, *, ttl_seconds: float = 30.0) -> None:
        if ttl_seconds < 0.1:
            raise ValueError("Guild mutation lock TTL must be at least 100ms")
        self._redis = redis
        self._ttl_ms = int(ttl_seconds * 1000)

    @staticmethod
    def key(guild_id: int) -> str:
        return guild_namespace(guild_id).key("mutation", "lock", "v1")

    async def run(self, guild_id: int, operation: Callable[[], Awaitable[T]]) -> T:
        token = uuid4().hex
        key = self.key(guild_id)
        acquired = await self._redis.set(key, token, nx=True, px=self._ttl_ms)
        if not acquired:
            raise GuildMutationLockUnavailable("another mutation owns this Guild")
        stopped = asyncio.Event()
        lost = asyncio.Event()

        async def renew() -> None:
            interval = max(0.05, self._ttl_ms / 5000)
            while not stopped.is_set():
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=interval)
                    return
                except TimeoutError:
                    renewed = await self._redis.eval(self._RENEW, 1, key, token, self._ttl_ms)
                    if int(renewed) != 1:
                        lost.set()
                        return

        async def invoke() -> T:
            return await operation()

        heartbeat = asyncio.create_task(renew())
        task: asyncio.Task[T] = asyncio.create_task(invoke())
        lost_task = asyncio.create_task(lost.wait())
        try:
            done, _ = await asyncio.wait({task, lost_task}, return_when=asyncio.FIRST_COMPLETED)
            if lost_task in done and lost.is_set() and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise GuildMutationLockUnavailable("Guild mutation lock ownership was lost")
            return await task
        finally:
            stopped.set()
            heartbeat.cancel()
            lost_task.cancel()
            await asyncio.gather(heartbeat, lost_task, return_exceptions=True)
            await self._redis.eval(self._RELEASE, 1, key, token)
