"""WP13: the actual Discord delivery worker (fenced claim -> mark SENDING ->
send -> finalize), and its integration with the shared
``DiscordWorkloadGovernor``.

Every real message send traverses this single path -- there is no other
code in the Campaign Engine that calls ``DiscordMessageSender.send``. This
is deliberate: it is the one place the fenced claim/send/finalize contract,
the durable nonce, and the UNKNOWN_OUTCOME reconciliation decision all
compose correctly, and it is what ``DiscordWorkloadGovernor`` schedules
under ``WorkloadPriority.SEND_CAMPAIGN_MESSAGE`` -- bulk campaign sends
never bypass the same per-Guild fairness and global concurrency limits that
protect structural apply/critical reconcile work for every other Stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from did.campaigns.delivery_reconciliation import (
    ReconciliationAction,
    decide_unknown_outcome_recovery,
    generate_delivery_nonce,
)
from did.domain.campaigns import DeliveryStatus
from did.domain.discord_runtime import WorkloadJob, WorkloadPriority
from did.domain.message_sending import DiscordMessageSender, DiscordSendError
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.messaging.allowed_mentions import CompiledAllowedMentions
from did.messaging.message_model import MessageModel
from did.worker.io.governor import DiscordWorkloadGovernor

#: The single workload_type every campaign delivery is submitted to the
#: shared governor under -- see the module docstring.
SEND_CAMPAIGN_MESSAGE_WORKLOAD_TYPE = "SEND_CAMPAIGN_MESSAGE"

#: How long a SENDING delivery may go unfinalized before it is considered
#: abandoned by its original worker and eligible for reconciliation --
#: deliberately much larger than any normal claim lease (see
#: CampaignsRepository.claim_stalled_sending_for_reconciliation).
STALLED_SENDING_THRESHOLD_SECONDS = 120.0


class DeliveryWorkOutcome(StrEnum):
    SENT = "SENT"
    FAILED = "FAILED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    INTERVENTION_REQUIRED = "INTERVENTION_REQUIRED"
    NOTHING_TO_DO = "NOTHING_TO_DO"
    LEASE_LOST = "LEASE_LOST"


@dataclass(frozen=True, slots=True)
class DeliveryWorkResult:
    outcome: DeliveryWorkOutcome
    delivery_id: UUID | None = None
    discord_message_id: int | None = None
    error: str | None = None


def _compiled_mentions_from_snapshot(snapshot: dict[str, Any]) -> CompiledAllowedMentions:
    return CompiledAllowedMentions(
        parse=tuple(snapshot.get("parse", ())),
        users=tuple(snapshot.get("users", ())),
        roles=tuple(snapshot.get("roles", ())),
        replied_user=bool(snapshot.get("replied_user", False)),
    )


async def _send_and_finalize(
    *,
    repository: CampaignsRepository,
    sender: DiscordMessageSender,
    guild_id: int,
    delivery_id: UUID,
    lease_token: UUID,
    channel_id: int,
    message: MessageModel,
    allowed_mentions: CompiledAllowedMentions,
    nonce: str,
) -> DeliveryWorkResult:
    """Shared by the first-attempt path and the UNKNOWN_OUTCOME retry path:
    attempt the send, then finalize with the fenced token. Any exception
    that is NOT :class:`DiscordSendError` is, by the
    ``DiscordMessageSender`` contract, an unknown/ambiguous outcome -- never
    treated as a plain failure."""
    try:
        result = await sender.send(
            channel_id=channel_id, message=message, allowed_mentions=allowed_mentions, nonce=nonce
        )
    except DiscordSendError as exc:
        await repository.finalize_delivery(
            delivery_id,
            guild_id,
            lease_token,
            status=DeliveryStatus.FAILED.value,
            last_error=str(exc),
        )
        return DeliveryWorkResult(DeliveryWorkOutcome.FAILED, delivery_id, error=str(exc))
    except Exception as exc:
        await repository.finalize_delivery(
            delivery_id,
            guild_id,
            lease_token,
            status=DeliveryStatus.UNKNOWN.value,
            discord_nonce=nonce,
            last_error=str(exc),
        )
        return DeliveryWorkResult(DeliveryWorkOutcome.UNKNOWN_OUTCOME, delivery_id, error=str(exc))

    await repository.finalize_delivery(
        delivery_id,
        guild_id,
        lease_token,
        status=DeliveryStatus.SENT.value,
        discord_message_id=result.discord_message_id,
        discord_nonce=nonce,
    )
    return DeliveryWorkResult(
        DeliveryWorkOutcome.SENT, delivery_id, discord_message_id=result.discord_message_id
    )


async def process_one_pending_delivery(
    *,
    repository: CampaignsRepository,
    sender: DiscordMessageSender,
    guild_id: int,
    lease_owner: str,
    now: datetime | None = None,
) -> DeliveryWorkResult:
    """Claim exactly one PENDING (or stale-CLAIMED) delivery for
    ``guild_id``, send it, and finalize -- the atomic unit of work a
    worker/governor dispatch submits. Returns
    :attr:`DeliveryWorkOutcome.NOTHING_TO_DO` when nothing was claimable."""
    now = now or datetime.now(UTC)
    claimed = await repository.claim_next_delivery(guild_id, lease_owner=lease_owner)
    if not claimed:
        return DeliveryWorkResult(DeliveryWorkOutcome.NOTHING_TO_DO)
    row = claimed[0]

    nonce = row.get("discord_nonce") or generate_delivery_nonce()
    marked = await repository.mark_delivery_sending(
        row["id"], guild_id, row["lease_token"], now=now, discord_nonce=nonce
    )
    if not marked:
        return DeliveryWorkResult(DeliveryWorkOutcome.LEASE_LOST, row["id"])

    message = MessageModel.from_dict(row["content_snapshot"] or {})
    mentions = _compiled_mentions_from_snapshot(row.get("allowed_mentions_snapshot") or {})
    return await _send_and_finalize(
        repository=repository,
        sender=sender,
        guild_id=guild_id,
        delivery_id=row["id"],
        lease_token=row["lease_token"],
        channel_id=row["discord_channel_id"],
        message=message,
        allowed_mentions=mentions,
        nonce=nonce,
    )


async def reconcile_one_stalled_delivery(
    *,
    repository: CampaignsRepository,
    sender: DiscordMessageSender,
    guild_id: int,
    lease_owner: str,
    now: datetime | None = None,
) -> DeliveryWorkResult:
    """WP6/REQ-MSG-029 UNKNOWN_OUTCOME recovery. Tries two distinct claim
    paths, in order, and reconciles whichever finds a candidate first:

    1. :meth:`CampaignsRepository.claim_stalled_sending_for_reconciliation`
       -- the delivery's worker crashed entirely before it could even reach
       :meth:`~CampaignsRepository.finalize_delivery` (still stuck in
       ``SENDING``).
    2. :meth:`CampaignsRepository.claim_unknown_deliveries_for_reconciliation`
       -- the ordinary case: the worker itself caught the ambiguous
       exception and already finalized to ``UNKNOWN``.

    Either way, ``did.campaigns.delivery_reconciliation.decide_unknown_outcome_recovery``
    decides, from the delivery's real original attempt timestamp, whether a
    same-nonce retry is still within Discord's documented enforce_nonce
    horizon or the delivery must go to ``INTERVENTION_REQUIRED`` instead.
    Never generates a fresh nonce -- the same nonce originally persisted by
    :func:`process_one_pending_delivery` is always reused, so a same-nonce
    retry either creates the one true message or Discord's own dedup
    collapses it back to the original; both are indistinguishable and
    equally safe."""
    now = now or datetime.now(UTC)
    reclaimed = await repository.claim_stalled_sending_for_reconciliation(
        guild_id,
        now=now,
        lease_owner=lease_owner,
        stall_after_seconds=STALLED_SENDING_THRESHOLD_SECONDS,
    )
    if not reclaimed:
        reclaimed = await repository.claim_unknown_deliveries_for_reconciliation(
            guild_id, now=now, lease_owner=lease_owner
        )
    if not reclaimed:
        return DeliveryWorkResult(DeliveryWorkOutcome.NOTHING_TO_DO)
    row = reclaimed[0]

    nonce = row.get("discord_nonce")
    if not nonce:
        # Should be unreachable: mark_delivery_sending always persists a
        # nonce before a delivery can ever reach SENDING/UNKNOWN. Fail
        # closed rather than invent one.
        await repository.finalize_delivery(
            row["id"],
            guild_id,
            row["lease_token"],
            status=DeliveryStatus.INTERVENTION_REQUIRED.value,
            last_error="reconciled delivery has no persisted nonce",
        )
        return DeliveryWorkResult(DeliveryWorkOutcome.INTERVENTION_REQUIRED, row["id"])

    attempted_at = row.get("attempted_at") or (
        now - timedelta(seconds=STALLED_SENDING_THRESHOLD_SECONDS)
    )
    decision = decide_unknown_outcome_recovery(
        attempted_at=attempted_at,
        now=now,
        attempt_count=row.get("attempt_count", 0),
    )
    if decision.action is ReconciliationAction.REQUIRE_INTERVENTION:
        await repository.finalize_delivery(
            row["id"],
            guild_id,
            row["lease_token"],
            status=DeliveryStatus.INTERVENTION_REQUIRED.value,
            last_error=decision.reason,
        )
        return DeliveryWorkResult(DeliveryWorkOutcome.INTERVENTION_REQUIRED, row["id"])

    message = MessageModel.from_dict(row["content_snapshot"] or {})
    mentions = _compiled_mentions_from_snapshot(row.get("allowed_mentions_snapshot") or {})
    return await _send_and_finalize(
        repository=repository,
        sender=sender,
        guild_id=guild_id,
        delivery_id=row["id"],
        lease_token=row["lease_token"],
        channel_id=row["discord_channel_id"],
        message=message,
        allowed_mentions=mentions,
        nonce=nonce,
    )


def build_delivery_workload_job(
    *, guild_id: int, delivery_id: UUID, enqueued_at: datetime
) -> WorkloadJob:
    """The explicit, campaign-specific workload the governor dispatches --
    lowest priority tier of the shared enum (see
    ``WorkloadPriority.SEND_CAMPAIGN_MESSAGE``'s docstring) so bulk campaign
    fan-out can never starve structural apply/critical reconcile/other
    Guilds' higher-priority work; per-Guild fairness is handled by the
    governor's own round-robin regardless of this priority tier."""
    return WorkloadJob(
        job_id=delivery_id,
        guild_id=guild_id,
        workload_type=SEND_CAMPAIGN_MESSAGE_WORKLOAD_TYPE,
        logical_key=str(delivery_id),
        priority=WorkloadPriority.SEND_CAMPAIGN_MESSAGE,
        enqueued_at=enqueued_at,
    )


def submit_delivery_to_governor(
    governor: DiscordWorkloadGovernor,
    *,
    repository: CampaignsRepository,
    sender: DiscordMessageSender,
    guild_id: int,
    delivery_id: UUID,
    lease_owner: str,
    enqueued_at: datetime,
) -> Any:
    """Submit exactly one already-known-pending delivery through the shared
    governor rather than sending it directly -- this is what keeps campaign
    bulk work subject to the same global/per-Guild concurrency limits and
    backpressure as every other Discord workload type."""
    job = build_delivery_workload_job(
        guild_id=guild_id, delivery_id=delivery_id, enqueued_at=enqueued_at
    )

    async def _operation() -> DeliveryWorkResult:
        return await process_one_pending_delivery(
            repository=repository, sender=sender, guild_id=guild_id, lease_owner=lease_owner
        )

    return governor.submit(job, _operation)
