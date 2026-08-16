from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from did.application.reconciliation.scheduler import AdaptiveReconcilePolicy, ReconcileSignals
from did.domain.discord_runtime import WorkloadJob, WorkloadPriority
from did.infrastructure.runtime_repository import RuntimeRepository


class ReconcileScheduler:
    """Compute tenant due work with stable jitter and only enqueue durable jobs."""

    def __init__(self, repository: RuntimeRepository, policy: AdaptiveReconcilePolicy) -> None:
        self._repository = repository
        self._policy = policy

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
