from __future__ import annotations

import asyncio
import logging
from collections import deque

from did.infrastructure.runtime_redis import OutboxPublisher, RedisRuntimeWakeup
from did.infrastructure.runtime_repository import RuntimeRepository
from did.worker.io.governor import BackpressureError, DiscordWorkloadGovernor
from did.worker.io.worker import DurableDiscordIOWorker


class DiscordWorkerRuntime:
    """Operational durable dispatcher sharing one long-lived workload Governor."""

    def __init__(
        self,
        *,
        repository: RuntimeRepository,
        worker: DurableDiscordIOWorker,
        governor: DiscordWorkloadGovernor,
        outbox: OutboxPublisher,
        wakeup: RedisRuntimeWakeup,
        poll_interval_seconds: float = 0.25,
        recovery_interval_seconds: float = 2.0,
        routing_batch_size: int = 256,
        dispatch_batch_size: int = 512,
    ) -> None:
        if poll_interval_seconds <= 0 or recovery_interval_seconds <= 0:
            raise ValueError("worker polling intervals must be positive")
        if not 1 <= routing_batch_size <= 1000:
            raise ValueError("routing batch size must be between 1 and 1000")
        if dispatch_batch_size < 1:
            raise ValueError("dispatch batch size must be positive")
        self._repository = repository
        self._worker = worker
        self.governor = governor
        self._outbox = outbox
        self._wakeup = wakeup
        self._poll_interval = poll_interval_seconds
        self._recovery_interval = recovery_interval_seconds
        self._routing_batch_size = routing_batch_size
        self._dispatch_batch_size = dispatch_batch_size
        self._logger = logging.getLogger(__name__)

    async def run(self, stop_event: asyncio.Event) -> None:
        loop = asyncio.get_running_loop()
        next_recovery = 0.0
        while not stop_event.is_set():
            now = loop.time()
            guild_ids: set[int] = set()
            try:
                guild_ids.update(await self._wakeup.pop_job_guilds(limit=self._routing_batch_size))
            except Exception:
                self._logger.warning("runtime Redis wakeup unavailable; using durable recovery")
            if now >= next_recovery:
                guild_ids.update(
                    await self._repository.runtime_job_guilds(limit=self._routing_batch_size)
                )
                next_recovery = now + self._recovery_interval

            await self._publish_pending_outbox()
            if guild_ids and not await self.governor.system_halted():
                await self._dispatch_fair_batch(sorted(guild_ids))

            try:
                pressure = (
                    1.0
                    if self.governor.invalid_request_budget_degraded
                    else self.governor.workload_pressure
                )
                await self._wakeup.set_rate_limit_pressure(pressure)
            except Exception:
                self._logger.warning("runtime rate-pressure signal unavailable")

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval)
            except TimeoutError:
                pass

        # A stop does not lease new work.  Any already submitted bounded operations are
        # drained and acknowledged before the process releases its resources.
        if self.governor.queue_depth:
            await self.governor.drain()
        try:
            await self._wakeup.clear_rate_limit_pressure()
        except Exception:
            self._logger.warning("runtime rate-pressure cleanup unavailable")

    async def _publish_pending_outbox(self) -> int:
        published = 0
        guild_ids = await self._repository.runtime_outbox_guilds(limit=self._routing_batch_size)
        for guild_id in guild_ids:
            try:
                published += await self._outbox.publish_guild(guild_id, limit=100)
            except Exception:
                # The publisher has durably scheduled its own retry.  Other Guilds keep
                # progressing, and the bounded DB discovery will revisit this one.
                self._logger.warning("outbox publication deferred after side-effect failure")
        return published

    async def _dispatch_fair_batch(self, guild_ids: list[int]) -> int:
        ring = deque(guild_ids)
        dispatched = 0
        self.governor.set_backlog_active(True)
        try:
            while (
                ring
                and dispatched < self._dispatch_batch_size
                and not await self.governor.system_halted()
            ):
                futures: list[asyncio.Future[object]] = []
                blocked_turns = 0
                while ring and dispatched < self._dispatch_batch_size:
                    guild_id = ring.popleft()
                    if not self.governor.can_admit(guild_id):
                        self.governor.record_admission_backpressure()
                        ring.append(guild_id)
                        blocked_turns += 1
                        if blocked_turns >= len(ring):
                            break
                        continue
                    try:
                        future = await self._worker.dispatch_guild_once(guild_id, self.governor)
                    except BackpressureError:
                        self.governor.record_admission_backpressure()
                        ring.appendleft(guild_id)
                        break
                    if future is None:
                        continue
                    futures.append(future)
                    dispatched += 1
                    blocked_turns = 0
                    # One admission per Guild per round preserves quiet-tenant progress.
                    ring.append(guild_id)
                if not futures:
                    break
                await self._drain_with_pressure()
                await asyncio.gather(*futures, return_exceptions=True)
                await self._publish_pending_outbox()
        finally:
            self.governor.set_backlog_active(False)
            try:
                await self._wakeup.set_rate_limit_pressure(0.0)
            except Exception:
                self._logger.warning("runtime rate-pressure signal unavailable")
        return dispatched

    async def _drain_with_pressure(self) -> None:
        drain = asyncio.create_task(self.governor.drain())
        try:
            while not drain.done():
                try:
                    await self._wakeup.set_rate_limit_pressure(self.governor.workload_pressure)
                except Exception:
                    self._logger.warning("runtime rate-pressure signal unavailable")
                try:
                    await asyncio.wait_for(asyncio.shield(drain), timeout=0.05)
                except TimeoutError:
                    pass
            await drain
        finally:
            if not drain.done():
                drain.cancel()
                await asyncio.gather(drain, return_exceptions=True)
