"""WP12/WP13: durable delivery dispatch -- bridges
``did.campaigns.activation.fan_out_occurrence`` (which creates
``message_deliveries`` rows) to the shared Stage01-08 durable
``discord_io_jobs``/``DurableDiscordIOWorker`` runtime, so a delivery a
fan-out created is guaranteed to eventually execute even across a process
crash. Before this module, a delivery row's only path to actually being
sent was an in-memory ``DiscordWorkloadGovernor.submit()`` call
(``did.campaigns.delivery_worker.submit_delivery_to_governor``) -- real for
governor-level fairness testing, but not durable: a crash between
``create_delivery``'s commit and that in-memory submission (or while the
job merely sat in the in-memory queue) could silently strand the delivery
forever. This module makes "delivery exists" and "a durable worker will
eventually execute it" the same guarantee, exactly the way every other
Discord-facing workload type (``APPLY_PLAN``, ``REFRESH_CHANNELS``, ...)
already works.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from did.campaigns.delivery_worker import (
    DELETE_CAMPAIGN_MESSAGE_WORKLOAD_TYPE,
    EDIT_CAMPAIGN_MESSAGE_WORKLOAD_TYPE,
    SEND_CAMPAIGN_MESSAGE_WORKLOAD_TYPE,
    execute_owned_delete,
    execute_owned_edit,
    process_delivery,
)
from did.domain.discord_runtime import WorkloadJob, WorkloadPriority
from did.domain.message_sending import DiscordMessageSender
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.runtime_repository import RuntimeRepository


async def enqueue_delivery_job(
    runtime_repository: RuntimeRepository,
    *,
    guild_id: int,
    delivery_id: UUID,
    requested_by: int | None = None,
    correlation_id: UUID | None = None,
) -> UUID:
    """Durably enqueue exactly one ``discord_io_jobs`` row whose logical
    identity IS ``delivery_id`` (``logical_key=str(delivery_id)``) -- never
    "any next pending" (see ``did.campaigns.delivery_worker.process_delivery``
    for why that distinction matters). Idempotent: ``enqueue_job``'s own
    ``UNIQUE(guild_id, logical_key)`` coalescing (``ON CONFLICT ... DO
    NOTHING`` while a live PENDING/LEASED job already exists) makes calling
    this twice for the same delivery a safe no-op, which is exactly what
    lets :func:`route_pending_deliveries_to_jobs` re-sweep repeatedly
    without any bespoke "did I already enqueue this" bookkeeping."""
    job = WorkloadJob(
        job_id=delivery_id,
        guild_id=guild_id,
        workload_type=SEND_CAMPAIGN_MESSAGE_WORKLOAD_TYPE,
        logical_key=str(delivery_id),
        priority=WorkloadPriority.SEND_CAMPAIGN_MESSAGE,
        enqueued_at=datetime.now(UTC),
        payload={"delivery_id": str(delivery_id)},
    )
    return await runtime_repository.enqueue_job(
        job, requested_by=requested_by, correlation_id=correlation_id or uuid4()
    )


async def enqueue_edit_job(
    runtime_repository: RuntimeRepository,
    *,
    guild_id: int,
    delivery_id: UUID,
    requested_by: int | None = None,
    correlation_id: UUID | None = None,
) -> UUID:
    """REQ-MSG owned edit (mission section 7): a FRESH ``job_id`` (never
    ``delivery_id`` -- that identity is already permanently used by this
    delivery's own SEND job, and ``job_id`` is a durable, all-time-unique
    primary key, not merely unique among currently-active jobs). Coalescing
    against a rapid duplicate edit request instead uses a dedicated
    ``logical_key`` (``edit-delivery:{delivery_id}``, distinct from the
    send job's own ``str(delivery_id)`` key) so at most one live edit job
    exists per delivery at a time; the durable job's payload names only
    ``delivery_id`` -- see :func:`did.campaigns.delivery_worker
    .execute_owned_edit` for why the channel/message id are never carried
    in the payload itself."""
    job = WorkloadJob(
        job_id=uuid4(),
        guild_id=guild_id,
        workload_type=EDIT_CAMPAIGN_MESSAGE_WORKLOAD_TYPE,
        logical_key=f"edit-delivery:{delivery_id}",
        priority=WorkloadPriority.SEND_CAMPAIGN_MESSAGE,
        enqueued_at=datetime.now(UTC),
        payload={"delivery_id": str(delivery_id)},
    )
    return await runtime_repository.enqueue_job(
        job, requested_by=requested_by, correlation_id=correlation_id or uuid4()
    )


async def enqueue_delete_job(
    runtime_repository: RuntimeRepository,
    *,
    guild_id: int,
    delivery_id: UUID,
    requested_by: int | None = None,
    correlation_id: UUID | None = None,
) -> UUID:
    """REQ-MSG owned delete (mission section 8) -- same fresh-job_id/
    dedicated-logical_key rationale as :func:`enqueue_edit_job`."""
    job = WorkloadJob(
        job_id=uuid4(),
        guild_id=guild_id,
        workload_type=DELETE_CAMPAIGN_MESSAGE_WORKLOAD_TYPE,
        logical_key=f"delete-delivery:{delivery_id}",
        priority=WorkloadPriority.SEND_CAMPAIGN_MESSAGE,
        enqueued_at=datetime.now(UTC),
        payload={"delivery_id": str(delivery_id)},
    )
    return await runtime_repository.enqueue_job(
        job, requested_by=requested_by, correlation_id=correlation_id or uuid4()
    )


async def route_pending_deliveries_to_jobs(
    campaigns_repository: CampaignsRepository,
    runtime_repository: RuntimeRepository,
    *,
    guild_id: int,
    limit: int = 200,
) -> int:
    """Durable, idempotent recovery sweep: (re-)enqueue a durable job for
    every currently-PENDING delivery in ``guild_id``. This is what closes
    the crash window between ``fan_out_occurrence``'s ``create_delivery``
    commit and this same process's own :func:`enqueue_delivery_job` call --
    if the process dies in between, a LATER call to this sweep (this
    worker restarting, or any other worker) notices the delivery is still
    PENDING and enqueues it; ``enqueue_delivery_job``'s coalescing means a
    delivery that already has a live job is simply skipped, so calling this
    repeatedly (e.g. every scheduler tick, for every Guild
    ``RuntimeRepository.runtime_campaign_delivery_guilds`` names) is cheap
    and safe. Returns the number of deliveries routed this call."""
    delivery_ids = await campaigns_repository.list_pending_delivery_ids(guild_id, limit=limit)
    for delivery_id in delivery_ids:
        await enqueue_delivery_job(runtime_repository, guild_id=guild_id, delivery_id=delivery_id)
    return len(delivery_ids)


class CampaignDeliveryExecutor:
    """The ``did.worker.io.worker.DurableDiscordIOWorker``-facing port for
    every campaign-message workload_type (``SEND_CAMPAIGN_MESSAGE``,
    ``EDIT_CAMPAIGN_MESSAGE``, ``DELETE_CAMPAIGN_MESSAGE``): wraps
    ``did.campaigns.delivery_worker``'s ``process_delivery``/
    ``execute_owned_edit``/``execute_owned_delete`` (each a fenced or
    ledger-sourced, named-identity primitive) so a leased ``discord_io_jobs``
    row can only ever execute the exact ``delivery_id`` its own payload
    names, never a substitute -- the same named-identity guarantee
    ``process_delivery`` already gives the in-memory governor path, now also
    given to the durable dispatch path, and shared by the owned edit/delete
    flows (mission sections 7-8): neither ever reads a channel/message id
    from the job payload, only ``delivery_id``, resolving everything else
    from the delivery's own current ledger row.

    ``message_deliveries`` owns the true state machine for a delivery
    attempt, not ``discord_io_jobs``. This executor therefore always
    completes normally once the underlying operation returns -- regardless
    of whether a SEND ended up SENT/FAILED/UNKNOWN_OUTCOME/ALREADY_RESOLVED/
    STALE_OUTCOME/LEASE_LOST, or an EDIT/DELETE found nothing left to act on
    -- so ``discord_io_jobs``' own retry mechanism never fights with
    ``message_deliveries``' independent lease/reconciliation lifecycle
    (``did.campaigns.delivery_worker.reconcile_one_stalled_delivery`` is the
    only thing that ever retries an ambiguous SEND, on its own schedule).
    Only a genuine infrastructure exception (a lost DB connection mid-claim,
    or a definitive Discord failure the edit/delete adapter methods raise)
    propagates out of this method, which correctly falls through to
    ``DurableDiscordIOWorker``'s normal exception -> ``retry_job`` handling
    for the durable job itself."""

    def __init__(
        self,
        repository: CampaignsRepository,
        sender: DiscordMessageSender,
        *,
        worker_id: str,
    ) -> None:
        self._repository = repository
        self._sender = sender
        self._worker_id = worker_id

    async def execute_leased(self, guild_id: int, leased: dict[str, Any]) -> None:
        payload = dict(leased.get("payload") or {})
        delivery_id = UUID(str(payload["delivery_id"]))
        workload_type = str(leased["workload_type"])
        if workload_type == EDIT_CAMPAIGN_MESSAGE_WORKLOAD_TYPE:
            await execute_owned_edit(
                repository=self._repository,
                sender=self._sender,
                guild_id=guild_id,
                delivery_id=delivery_id,
            )
            return
        if workload_type == DELETE_CAMPAIGN_MESSAGE_WORKLOAD_TYPE:
            await execute_owned_delete(
                repository=self._repository,
                sender=self._sender,
                guild_id=guild_id,
                delivery_id=delivery_id,
            )
            return
        await process_delivery(
            repository=self._repository,
            sender=self._sender,
            guild_id=guild_id,
            delivery_id=delivery_id,
            lease_owner=self._worker_id,
        )
