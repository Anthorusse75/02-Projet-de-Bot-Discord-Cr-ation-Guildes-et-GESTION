from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from did.domain.discord_runtime import DiscordErrorKind, DiscordFailure, WorkloadJob

if TYPE_CHECKING:
    from did.infrastructure.runtime_redis import (
        DistributedPermit,
        RedisDiscordWorkloadCoordinator,
    )


class BackpressureError(RuntimeError):
    pass


class WorkloadHaltedError(RuntimeError):
    pass


@dataclass(slots=True)
class GovernorMetrics:
    submitted: int = 0
    completed: int = 0
    failed: int = 0
    coalesced: int = 0
    rejected_backpressure: int = 0
    peak_queue_depth: int = 0
    peak_global_concurrency: int = 0
    peak_guild_concurrency: int = 0
    peak_system_global_concurrency: int = 0
    peak_system_guild_concurrency: int = 0
    invalid_requests_10m: int = 0
    rate_limited: int = 0
    rate_limit_wait_seconds: float = 0.0
    dispatch_slots: list[int] = field(default_factory=list)
    queue_wait_seconds: list[float] = field(default_factory=list)

    def snapshot(self) -> dict[str, int | float]:
        average_wait = (
            sum(self.queue_wait_seconds) / len(self.queue_wait_seconds)
            if self.queue_wait_seconds
            else 0.0
        )
        return {
            "submitted": self.submitted,
            "completed": self.completed,
            "failed": self.failed,
            "coalesced": self.coalesced,
            "rejected_backpressure": self.rejected_backpressure,
            "peak_queue_depth": self.peak_queue_depth,
            "peak_global_concurrency": self.peak_global_concurrency,
            "peak_guild_concurrency": self.peak_guild_concurrency,
            "peak_system_global_concurrency": self.peak_system_global_concurrency,
            "peak_system_guild_concurrency": self.peak_system_guild_concurrency,
            "invalid_requests_10m": self.invalid_requests_10m,
            "rate_limited": self.rate_limited,
            "rate_limit_wait_seconds": round(self.rate_limit_wait_seconds, 6),
            "average_queue_wait_seconds": round(average_wait, 6),
        }


@dataclass(slots=True)
class _ScheduledWork:
    job: WorkloadJob
    operation: Callable[[], Awaitable[Any]]
    future: asyncio.Future[Any]
    sequence: int


class DiscordWorkloadGovernor:
    """Application workload control above discord.py's protocol limiter."""

    def __init__(
        self,
        *,
        global_concurrency: int = 4,
        per_guild_concurrency: int = 1,
        max_queue_depth: int = 1_000,
        aging_interval_seconds: float = 30.0,
        invalid_request_warning: int = 8_000,
        distributed_coordinator: RedisDiscordWorkloadCoordinator | None = None,
    ) -> None:
        if global_concurrency < 1 or per_guild_concurrency < 1:
            raise ValueError("concurrency limits must be positive")
        if per_guild_concurrency > global_concurrency:
            raise ValueError("per-guild concurrency cannot exceed global concurrency")
        if max_queue_depth < global_concurrency:
            raise ValueError("queue must hold at least one global dispatch window")
        if aging_interval_seconds <= 0:
            raise ValueError("aging interval must be positive")
        self._global_limit = global_concurrency
        self._guild_limit = per_guild_concurrency
        self._max_queue_depth = max_queue_depth
        self._aging_interval = aging_interval_seconds
        self._invalid_request_warning = invalid_request_warning
        self._distributed = distributed_coordinator
        self._queues: dict[int, list[_ScheduledWork]] = defaultdict(list)
        self._guild_ring: deque[int] = deque()
        self._coalesced: dict[tuple[int, str], asyncio.Future[Any]] = {}
        self._running_by_guild: dict[int, int] = defaultdict(int)
        self._running = 0
        self._sequence = 0
        self._dispatch_slot = 0
        self._invalid_requests: deque[datetime] = deque()
        self._halted = False
        self._backlog_active = False
        self.metrics = GovernorMetrics()

    @property
    def queue_depth(self) -> int:
        return sum(len(queue) for queue in self._queues.values())

    @property
    def background_paused(self) -> bool:
        return self._backlog_active or self.queue_depth >= max(1, self._max_queue_depth // 2)

    @property
    def running_count(self) -> int:
        return self._running

    @property
    def global_concurrency_limit(self) -> int:
        return self._global_limit

    @property
    def max_queue_depth(self) -> int:
        return self._max_queue_depth

    @property
    def workload_pressure(self) -> float:
        if self._backlog_active:
            return 1.0
        return min(
            1.0,
            (self.queue_depth + self._running) / max(1, self._global_limit),
        )

    def set_backlog_active(self, active: bool) -> None:
        self._backlog_active = active

    def can_admit(self, guild_id: int) -> bool:
        queued_for_guild = len(self._queues.get(guild_id, ()))
        return (
            self.queue_depth < self._max_queue_depth
            and self.queue_depth + self._running < self._global_limit
            and queued_for_guild + self._running_by_guild[guild_id] < self._guild_limit
        )

    def record_admission_backpressure(self) -> None:
        self.metrics.rejected_backpressure += 1

    @property
    def halted(self) -> bool:
        return self._halted

    async def system_halted(self) -> bool:
        return self._halted or (
            self._distributed is not None and await self._distributed.is_halted()
        )

    def submit(
        self, job: WorkloadJob, operation: Callable[[], Awaitable[Any]]
    ) -> asyncio.Future[Any]:
        if self._halted:
            raise WorkloadHaltedError("Discord workload is halted after token invalidation")
        coalescing_key = (job.guild_id, job.logical_key)
        existing = self._coalesced.get(coalescing_key)
        if existing is not None and not existing.done():
            self.metrics.coalesced += 1
            return existing
        if self.queue_depth >= self._max_queue_depth:
            self.metrics.rejected_backpressure += 1
            raise BackpressureError("Discord workload queue is full")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        scheduled = _ScheduledWork(job, operation, future, self._sequence)
        self._sequence += 1
        if not self._queues[job.guild_id]:
            self._guild_ring.append(job.guild_id)
        self._queues[job.guild_id].append(scheduled)
        self._coalesced[coalescing_key] = future
        self.metrics.submitted += 1
        self.metrics.peak_queue_depth = max(self.metrics.peak_queue_depth, self.queue_depth)
        return future

    def _effective_priority(self, work: _ScheduledWork, now: datetime) -> int:
        waited = max(0.0, (now - work.job.enqueued_at).total_seconds())
        promotions = int(waited // self._aging_interval)
        return max(0, int(work.job.priority) - promotions)

    def _next_work(self) -> _ScheduledWork | None:
        if not self._guild_ring:
            return None
        now = datetime.now(UTC)
        for _ in range(len(self._guild_ring)):
            guild_id = self._guild_ring[0]
            self._guild_ring.rotate(-1)
            if self._running_by_guild[guild_id] >= self._guild_limit:
                continue
            queue = self._queues[guild_id]
            if not queue:
                self._remove_guild(guild_id)
                continue
            best_index = min(
                range(len(queue)),
                key=lambda index: (
                    self._effective_priority(queue[index], now),
                    queue[index].sequence,
                ),
            )
            work = queue.pop(best_index)
            if not queue:
                self._remove_guild(guild_id)
            return work
        return None

    def _remove_guild(self, guild_id: int) -> None:
        try:
            self._guild_ring.remove(guild_id)
        except ValueError:
            pass
        if not self._queues[guild_id]:
            self._queues.pop(guild_id, None)

    async def drain(self) -> list[Any]:
        results: list[Any] = []
        active: set[asyncio.Task[tuple[_ScheduledWork, Any, BaseException | None]]] = set()
        while self.queue_depth or active:
            while self._running < self._global_limit:
                work = self._next_work()
                if work is None:
                    break
                self._running += 1
                self._running_by_guild[work.job.guild_id] += 1
                self._dispatch_slot += 1
                self.metrics.dispatch_slots.append(work.job.guild_id)
                self.metrics.queue_wait_seconds.append(
                    max(0.0, (datetime.now(UTC) - work.job.enqueued_at).total_seconds())
                )
                self.metrics.peak_global_concurrency = max(
                    self.metrics.peak_global_concurrency, self._running
                )
                self.metrics.peak_guild_concurrency = max(
                    self.metrics.peak_guild_concurrency,
                    self._running_by_guild[work.job.guild_id],
                )
                active.add(asyncio.create_task(self._execute(work)))
            if not active:
                if self.queue_depth:
                    raise RuntimeError("queued workload cannot progress under concurrency policy")
                break
            done, active = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                work, value, error = task.result()
                self._running -= 1
                self._running_by_guild[work.job.guild_id] -= 1
                self._coalesced.pop((work.job.guild_id, work.job.logical_key), None)
                if error is None:
                    self.metrics.completed += 1
                    if not work.future.done():
                        work.future.set_result(value)
                    results.append(value)
                else:
                    self.metrics.failed += 1
                    if not work.future.done():
                        work.future.set_exception(error)
        return results

    async def _execute(
        self, work: _ScheduledWork
    ) -> tuple[_ScheduledWork, Any, BaseException | None]:
        try:
            return work, await work.operation(), None
        except BaseException as exc:
            return work, None, exc

    async def run_distributed(self, guild_id: int, operation: Callable[[], Awaitable[Any]]) -> Any:
        """Acquire the system permit after the durable job heartbeat has started."""
        if self._distributed is None:
            return await operation()
        if await self._distributed.is_halted():
            raise WorkloadHaltedError("Discord token is halted system-wide")
        try:
            permit = await self._distributed.acquire(guild_id)
        except RuntimeError as exc:
            raise WorkloadHaltedError("Discord token is halted system-wide") from exc
        # Acquisition intentionally uses the configured crash-recovery TTL. Extend
        # it to the active-owner jitter floor before starting I/O so scheduler delay
        # before the first heartbeat cannot expire a live permit.
        if not await self._distributed.renew(permit):
            from did.infrastructure.runtime_redis import DistributedPermitLostError

            await self._distributed.release(permit)
            raise DistributedPermitLostError(
                "distributed Discord permit was lost during activation"
            )
        self.metrics.peak_system_global_concurrency = max(
            self.metrics.peak_system_global_concurrency,
            permit.global_concurrency,
        )
        self.metrics.peak_system_guild_concurrency = max(
            self.metrics.peak_system_guild_concurrency,
            permit.guild_concurrency,
        )
        return await self._run_with_distributed_permit(permit, operation)

    async def _run_with_distributed_permit(
        self,
        permit: DistributedPermit,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        from did.infrastructure.runtime_redis import DistributedPermitLostError

        assert self._distributed is not None
        coordinator = self._distributed
        stopped = asyncio.Event()
        lost = asyncio.Event()

        async def heartbeat() -> None:
            interval = max(0.05, coordinator.permit_ttl_seconds / 3)
            while not stopped.is_set():
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=interval)
                    return
                except TimeoutError:
                    pass
                try:
                    renewed = await coordinator.renew(permit)
                except Exception:
                    renewed = False
                if not renewed:
                    lost.set()
                    return

        async def invoke_operation() -> Any:
            return await operation()

        heartbeat_task = asyncio.create_task(heartbeat())
        operation_task: asyncio.Task[Any] = asyncio.create_task(invoke_operation())
        lost_task = asyncio.create_task(lost.wait())
        try:
            done, _ = await asyncio.wait(
                {operation_task, lost_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if lost_task in done and lost.is_set() and not operation_task.done():
                operation_task.cancel()
                await asyncio.gather(operation_task, return_exceptions=True)
                raise DistributedPermitLostError("distributed Discord permit expired")
            return await operation_task
        finally:
            stopped.set()
            if not operation_task.done():
                operation_task.cancel()
            heartbeat_task.cancel()
            lost_task.cancel()
            await asyncio.gather(heartbeat_task, lost_task, operation_task, return_exceptions=True)
            await coordinator.release(permit)

    def record_discord_failure(
        self, failure: DiscordFailure, *, occurred_at: datetime | None = None
    ) -> None:
        now = occurred_at or datetime.now(UTC)
        if failure.kind is DiscordErrorKind.UNAUTHORIZED:
            self._halted = True
        if failure.counts_toward_invalid_request_limit:
            self._invalid_requests.append(now)
        if failure.kind is DiscordErrorKind.RATE_LIMITED:
            self.metrics.rate_limited += 1
            self.metrics.rate_limit_wait_seconds += max(0.0, failure.retry_after_seconds or 0.0)
        cutoff = now - timedelta(minutes=10)
        while self._invalid_requests and self._invalid_requests[0] < cutoff:
            self._invalid_requests.popleft()
        self.metrics.invalid_requests_10m = len(self._invalid_requests)

    async def record_distributed_failure(self, failure: DiscordFailure) -> None:
        if self._distributed is None:
            return
        count = await self._distributed.record_failure(failure)
        self.metrics.invalid_requests_10m = max(self.metrics.invalid_requests_10m, count)

    @property
    def invalid_request_budget_degraded(self) -> bool:
        return len(self._invalid_requests) >= self._invalid_request_warning

    def fairness_report(self, guild_a: int, guild_b: int) -> dict[str, int | bool]:
        slots = self.metrics.dispatch_slots
        first_b = next((index for index, guild in enumerate(slots) if guild == guild_b), -1)
        a_before_b = sum(1 for guild in slots[:first_b] if guild == guild_a) if first_b >= 0 else -1
        bound = max(1, len({guild for guild in slots if guild in {guild_a, guild_b}}))
        return {
            "first_b_slot": first_b,
            "a_dispatches_before_b": a_before_b,
            "fairness_bound_slots": bound,
            "b_progressed_within_bound": first_b >= 0 and first_b < bound,
            "peak_queue_depth": self.metrics.peak_queue_depth,
            "peak_global_concurrency": self.metrics.peak_global_concurrency,
        }


def job_id_text(value: UUID) -> str:
    return str(value)
