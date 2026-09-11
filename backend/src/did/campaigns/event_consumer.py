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

from dataclasses import dataclass
from uuid import UUID

from did.campaigns.causality import TriggerEvaluationContext, read_campaign_ancestry, should_trigger
from did.domain.campaigns import (
    CampaignTrigger,
    OccurrenceSource,
    TriggerSourceBinding,
    TriggerSourceScopeKind,
)
from did.domain.campaigns import MessageOccurrence as DomainOccurrence
from did.domain.discord_runtime import EventEnvelope
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
    trigger: CampaignTrigger,
    event: EventEnvelope,
    discord_resource_id: int | None,
    message_content_available: bool = True,
) -> EventConsumptionResult:
    """The single REQ-MSG-020/021/027/030 gate for one (trigger, event)
    pair. Takes the REAL shared Stage03 ``EventEnvelope`` object -- never a
    caller-unpacked bag of loose fields -- so ``event.event_type``,
    ``event.guild_id``, ``event.causation_depth`` and ``event.payload`` are
    exactly what a durably-captured Gateway dispatch actually carries, not a
    caller's possibly-stale or mistaken restatement of them.

    Two external-review findings closed here (this pass):

    1. ``trigger.event_type`` is never checked against the event being
       evaluated by this function's caller alone -- it is now enforced
       inside ``did.campaigns.causality.should_trigger`` itself via
       ``TriggerEvaluationContext.event_type``, so a caller can never
       accidentally (or a compromised caller never deliberately) fire a
       trigger configured for a different event_type just because a source
       binding and condition AST happen to also match.
    2. Ownership is derived from ``trigger.owner_discord_user_id`` -- the
       value durably loaded with the trigger row itself -- never from a
       separately caller-supplied ``owner_discord_user_id`` parameter. A
       caller cannot make this function attribute an occurrence to a
       different owner than the trigger's actual owner, cross-owner or
       otherwise.

    Loads this trigger's real ``TriggerSourceBinding`` rows for
    ``event.guild_id`` (Guild-scoped RLS -- a binding for a different Guild
    could never match this envelope's guild_id regardless, so this is
    exactly the minimal correct read), evaluates ``should_trigger`` (event
    type + source binding + depth + ancestor-loop + MESSAGE_CONTENT +
    condition AST, all required), and if it fires, durably records the
    trigger/event consumption and returns a deterministic occurrence ready
    for ``did.campaigns.activation.fan_out_occurrence`` -- this function
    never calls fan-out itself, callers do so as an explicit next step,
    keeping the "decide to fire" and "expand into deliveries" concerns
    separate and independently testable/idempotent."""
    source_bindings = [
        TriggerSourceBinding(
            id=row["id"],
            guild_id=row["guild_id"],
            trigger_id=row["trigger_id"],
            source_scope_kind=TriggerSourceScopeKind(row["source_scope_kind"]),
            discord_resource_id=row["discord_resource_id"],
        )
        for row in await repository.load_trigger_sources(event.guild_id, trigger.id)
    ]

    context = TriggerEvaluationContext(
        event_id=event.event_id,
        guild_id=event.guild_id,
        event_type=event.event_type,
        discord_resource_id=discord_resource_id,
        causation_depth=event.causation_depth,
        payload=event.payload,
        message_content_available=message_content_available,
    )
    if not should_trigger(trigger, source_bindings, context):
        return EventConsumptionResult(
            fired=False,
            reason=(
                "event_type, source binding, depth, ancestor-loop, "
                "MESSAGE_CONTENT, or condition gate rejected this event"
            ),
        )

    occurrence = DomainOccurrence(
        id=_deterministic_occurrence_id(trigger.id, event.event_id),
        owner_discord_user_id=trigger.owner_discord_user_id,
        campaign_id=trigger.campaign_id,
        occurrence_key=f"trigger:{trigger.id}:event:{event.event_id}",
        occurrence_source=OccurrenceSource.EVENT,
        source_event_id=event.event_id,
        source_correlation_id=event.correlation_id,
        # REQ-MSG-030: this occurrence inherits the depth of the event that
        # caused it (should_trigger already bounded that against
        # trigger.max_causation_depth above); its own ancestry is whatever
        # already causally led to that event, plus this campaign itself --
        # durably carried so a later Discord message this occurrence's
        # fan-out sends can be correctly attributed however long afterward
        # it re-enters ingestion.
        source_causation_depth=event.causation_depth,
        source_ancestry=read_campaign_ancestry(event.payload) | {str(trigger.campaign_id)},
    )

    consumed_now = await repository.record_trigger_consumption(
        event.guild_id, trigger.id, event.event_id, occurrence.id
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
