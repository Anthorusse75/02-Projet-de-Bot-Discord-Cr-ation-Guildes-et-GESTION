from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from did.application.reconciliation.scheduler import AdaptiveReconcilePolicy, ReconcileSignals
from did.domain.discord_runtime import WorkloadJob, WorkloadPriority
from did.infrastructure.runtime_redis import RedisRuntimeWakeup
from did.infrastructure.runtime_repository import RuntimeRepository


class ReconcileScheduler:
    """Compute tenant due work with stable jitter and only enqueue durable jobs."""

    def __init__(
        self,
        repository: RuntimeRepository,
        policy: AdaptiveReconcilePolicy,
        *,
        wakeup: RedisRuntimeWakeup | None = None,
        poll_interval_seconds: float = 5.0,
        routing_batch_size: int = 256,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("scheduler polling interval must be positive")
        if not 1 <= routing_batch_size <= 1000:
            raise ValueError("scheduler routing batch size must be between 1 and 1000")
        self._repository = repository
        self._policy = policy
        self._wakeup = wakeup
        self._poll_interval = poll_interval_seconds
        self._routing_batch_size = routing_batch_size
        self._logger = logging.getLogger(__name__)

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval)
            except TimeoutError:
                pass

    async def run_once(self, *, now: datetime | None = None) -> list[tuple[int, UUID]]:
        pressure = 0.0
        if self._wakeup is not None:
            try:
                pressure = await self._wakeup.rate_limit_pressure()
            except Exception:
                self._logger.warning("scheduler rate-pressure signal unavailable")
        guild_ids = await self._repository.runtime_reconcile_guilds(limit=self._routing_batch_size)
        signals = [
            await self._repository.reconcile_signals(guild_id, rate_limit_pressure=pressure)
            for guild_id in guild_ids
        ]
        return await self.enqueue_due(signals, now=now)

    async def enqueue_due(
        self, signals: list[ReconcileSignals], *, now: datetime | None = None
    ) -> list[tuple[int, UUID]]:
        reference = now or datetime.now(UTC)
        ordered = sorted(
            signals,
            key=lambda item: self._policy.priority_score(item, now=reference),
            reverse=True,
        )
        enqueued: list[tuple[int, UUID]] = []
        for item in ordered:
            if self._policy.next_due_at(item, now=reference) > reference:
                continue
            job = WorkloadJob(
                uuid4(),
                item.guild_id,
                "RECONCILE_STRUCTURE",
                "reconcile:structure",
                WorkloadPriority.BACKGROUND_RECONCILE,
                reference,
                payload={"reason": "adaptive-policy"},
            )
            job_id = await self._repository.enqueue_job(
                job, requested_by=None, correlation_id=uuid4()
            )
            enqueued.append((item.guild_id, job_id))
        return enqueued
