"""WP12: consumes real Stage03 ``EventEnvelope`` objects and decides
whether/what campaign occurrence to reserve -- REQ-MSG-020/021/027/030's
event-triggered campaign path.

Deliberately consumes ``did.domain.discord_runtime.EventEnvelope``, the
actual shared Stage03 event shape (``event_id``, ``guild_id``,
``causation_depth``, ``correlation_id``, ``causation_id``, ``payload``) --
never a parallel Stage09-specific event type. This module does not read the
durable outbox/pub-sub feed itself (that transport plumbing belongs to
whatever Stage03 consumer loop already exists); it is the pure decision
step a caller already holding one envelope and one trigger's config
invokes, mirroring how ``did.campaigns.delivery_worker`` is the processing
function a governor dispatch calls rather than the queue-reading loop
itself.

Trigger/event dedup (``CampaignsRepository.record_trigger_consumption``,
the ``UNIQUE(guild_id, trigger_id, event_id)`` constraint) and the
occurrence's own deterministic key
(``trigger:{trigger_id}:event:{event_id}``) are two independent, each
individually idempotent safety nets -- deliberately not forced into one
cross-schema (Guild-scoped trigger consumption vs. owner-scoped occurrence)
database transaction, since both are safe to retry independently: a crash
between them just means a retry re-attempts whichever one did not
complete, and neither can double-fire on its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from did.campaigns.causality import TriggerEvaluationContext, should_trigger
from did.domain.campaigns import (
    CampaignTrigger,
    OccurrenceSource,
    TriggerSourceBinding,
    TriggerSourceScopeKind,
)
from did.domain.campaigns import MessageOccurrence as DomainOccurrence
from did.infrastructure.campaigns_repository import CampaignsRepository


@dataclass(frozen=True, slots=True)
class EventConsumptionResult:
    fired: bool
    reason: str
    occurrence: DomainOccurrence | None = None
    #: True when the trigger/event pair had already been consumed by a
    #: prior attempt (safe replay, not a new firing) -- the caller must not
    #: fan out again in this case even though ``fired`` may still be True
    #: (the occurrence to hand to fan-out is still returned so a caller
    #: recovering from its own crash can resume the fan-out step, which is
    #: independently idempotent).
    already_consumed: bool = False


async def consume_event_for_trigger(
    *,
    repository: CampaignsRepository,
    owner_discord_user_id: int,
    trigger: CampaignTrigger,
    event_id: UUID,
    guild_id: int,
    discord_resource_id: int | None,
    payload: Mapping[str, object],
    causation_depth: int,
    correlation_id: UUID | None = None,
    message_content_available: bool = True,
) -> EventConsumptionResult:
    """The single REQ-MSG-020/021/027/030 gate for one (trigger, event)
    pair: loads this trigger's real ``TriggerSourceBinding`` rows for
    ``guild_id`` (Guild-scoped RLS -- a binding for a different Guild could
    never match this envelope's guild_id regardless, so this is exactly the
    minimal correct read), evaluates ``did.campaigns.causality.should_trigger``
    (source binding + depth + ancestor-loop + MESSAGE_CONTENT + condition
    AST, all required), and if it fires, durably records the trigger/event
    consumption and returns a deterministic occurrence ready for
    ``did.campaigns.activation.fan_out_occurrence`` -- this function never
    calls fan-out itself, callers do so as an explicit next step, keeping
    the "decide to fire" and "expand into deliveries" concerns separate and
    independently testable/idempotent."""
    source_bindings = [
        TriggerSourceBinding(
            id=row["id"],
            guild_id=row["guild_id"],
            trigger_id=row["trigger_id"],
            source_scope_kind=TriggerSourceScopeKind(row["source_scope_kind"]),
            discord_resource_id=row["discord_resource_id"],
        )
        for row in await repository.load_trigger_sources(guild_id, trigger.id)
    ]

    context = TriggerEvaluationContext(
        event_id=event_id,
        guild_id=guild_id,
        discord_resource_id=discord_resource_id,
        causation_depth=causation_depth,
        payload=payload,
        message_content_available=message_content_available,
    )
    if not should_trigger(trigger, source_bindings, context):
        return EventConsumptionResult(
            fired=False,
            reason=(
                "source binding, depth, ancestor-loop, MESSAGE_CONTENT, or "
                "condition gate rejected this event"
            ),
        )

    occurrence = DomainOccurrence(
        id=_deterministic_occurrence_id(trigger.id, event_id),
        owner_discord_user_id=owner_discord_user_id,
        campaign_id=trigger.campaign_id,
        occurrence_key=f"trigger:{trigger.id}:event:{event_id}",
        occurrence_source=OccurrenceSource.EVENT,
        source_event_id=event_id,
        source_correlation_id=correlation_id,
    )

    consumed_now = await repository.record_trigger_consumption(
        guild_id, trigger.id, event_id, occurrence.id
    )
    return EventConsumptionResult(
        fired=True,
        reason="trigger fired"
        if consumed_now
        else "already consumed by a prior attempt (safe replay)",
        occurrence=occurrence,
        already_consumed=not consumed_now,
    )


def _deterministic_occurrence_id(trigger_id: UUID, event_id: UUID) -> UUID:
    """A stable UUID derived from (trigger_id, event_id) -- so a replayed
    consumption attempt builds the exact same occurrence id, not just the
    same occurrence_key string (belt-and-suspenders: the UNIQUE(campaign_id,
    occurrence_key) constraint is still the actual source of truth for
    occurrence idempotency)."""
    from uuid import uuid5

    return uuid5(trigger_id, str(event_id))
