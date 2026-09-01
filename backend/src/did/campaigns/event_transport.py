"""WP12/WP8: the real Stage03 event transport for event-triggered
campaigns -- reads durable ``discord_gateway_inbox`` rows (via a per-Guild
cursor, migration ``0028_stage_09``) and feeds each one to
``did.campaigns.event_consumer.consume_event_for_trigger``, then fans out
whatever fires.

Covers every event_type Stage03's own gateway client can capture under its
configurable-intents architecture (ADR-008): structural dispatches --
``GUILD_*``/``CHANNEL_*``/``THREAD_*``/``GUILD_ROLE_*``/``GUILD_MEMBER_*`` --
plus, when ``Settings.discord_campaign_message_events_enabled`` is on (the
non-privileged ``GUILD_MESSAGES`` intent -- ADR-008 gates the genuinely
privileged ``MESSAGE_CONTENT`` intent, not this one), ``MESSAGE_CREATE``.
An event-triggered campaign whose *condition* depends on actual message
content still stays governed by the existing REQ-MSG-020 capability/blocker
machinery (``did.campaigns.message_content_policy``) -- this module never
extracts content/embeds/attachments from a message payload regardless of
which intents are active.

REQ-MSG-030 producing side -- durable correlation, no lucky ordering
=====================================================================

``did.campaigns.causality.should_trigger`` already refuses to fire when its
own campaign_id is present in an event's ``did_campaign_ancestry`` payload
(the consuming-side guard). The producing side is: when the bot's own
resulting Discord message re-enters ingestion as a ``MESSAGE_CREATE``, the
derived event evaluated against triggers here must carry the ancestry/
causation metadata of whatever occurrence actually sent it -- durably
recorded on ``message_occurrences.source_ancestry``/
``source_causation_depth`` at occurrence-creation time (migration
``0029_stage_09``), since the causing event's own payload is typically long
gone by the time the Gateway echo arrives.

A bot-authored ``MESSAGE_CREATE`` is correlated to the exact
``message_deliveries`` row that sent it by
``CampaignsRepository.find_delivery_by_discord_message`` (exact
guild_id/discord_channel_id/discord_message_id match, ``status='SENT'``
only). The real race this must survive without assuming an ordering: the
Gateway dispatch can arrive before OR after the HTTP send response has been
persisted (``finalize_delivery`` setting ``discord_message_id``).

* Finalize-before-Gateway (the common case): the delivery row already
  exists with this exact message id when the event is consumed --
  correlation succeeds immediately, the derived event is built with the
  occurrence's real ancestry/causation, evaluated against triggers, and the
  cursor advances past it in the same tick as any other event.
* Gateway-before-finalize (the race): no matching delivery exists *yet*.
  Rather than guessing, the per-Guild event cursor simply does not advance
  past this specific event -- every event in this batch is processed in
  strict ``(received_at, event_id)`` order already, so refusing to advance
  past an unresolved bot-authored ``MESSAGE_CREATE`` means the next tick
  (a few seconds later, per the scheduler's own poll interval -- far longer
  than a typical Discord HTTP round trip) simply re-reads and re-attempts
  it, by which point the finalize almost always has landed. This needs no
  new durable state at all: ``discord_gateway_inbox``'s own
  ``received_at`` and the existing ``message_campaign_event_cursor`` are
  already exactly the durable, restart-safe primitives this requires -- a
  process restart between either ordering simply resumes from the last
  successfully advanced cursor position, same as any other event type.
* No silent, indefinite stall, and no silent fail-open either: if a message
  confirmed to be DID's own bot identity was never actually sent through the
  Stage09 delivery ledger at all (some other bot feature, or a future edit
  path outside this ledger), it will never correlate.
  ``BOT_MESSAGE_CORRELATION_GRACE_SECONDS`` bounds how long the cursor will
  wait on any single such event before giving up -- the cursor still
  advances (the Guild's event processing is never stalled forever), but the
  event is deliberately never handed to trigger evaluation at all (see
  ``EventId.CAMPAIGN_BOT_MESSAGE_UNCORRELATED_SKIPPED``): treating an
  unresolved DID-bot message as an "ordinary" event would reopen exactly
  the self/cross-campaign loop the ancestor-loop guard exists to prevent.
  This wait/fail-closed path only ever applies to DID's own confirmed bot
  identity (resolved via
  ``did.infrastructure.stage04_repository.Stage04Repository.bot_identity``,
  never a hardcoded snowflake) -- a third-party bot's or a human's
  MESSAGE_CREATE is never delayed and always evaluated normally.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from did.campaigns.activation import fan_out_occurrence
from did.campaigns.causality import ANCESTRY_PAYLOAD_KEY
from did.campaigns.context import load_campaign, load_fan_out_context
from did.campaigns.event_consumer import consume_event_for_trigger
from did.campaigns.target_resolution import TargetAuthorizationChecker
from did.domain.campaigns import CampaignTrigger
from did.domain.discord_runtime import EventEnvelope, EventOrigin, EventSource
from did.domain.translation_provider import CampaignTranslationProvider
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.logging import EventId, emit_event
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage04_repository import Stage04Repository
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    TranslationGroupRepository,
    TranslationProviderBindingRepository,
)

logger = logging.getLogger(__name__)

#: How long the per-Guild event cursor will wait on an unresolved
#: bot-authored MESSAGE_CREATE before giving up correlation and advancing
#: past it as an ordinary, unattributed event. See the module docstring's
#: "REQ-MSG-030 producing side" section.
BOT_MESSAGE_CORRELATION_GRACE_SECONDS = 120

#: Which normalized-payload key names the single resource a given
#: structural event_type concerns, so should_trigger's CHANNEL/CATEGORY
#: source-binding match has something real to compare against. Event types
#: absent from this mapping (GUILD_CREATE/UPDATE/DELETE, THREAD_LIST_SYNC,
#: THREAD_MEMBERS_UPDATE -- all either Guild-wide or bulk/multi-resource)
#: resolve to no single resource id; only a GUILD-scoped source binding can
#: ever match them (see TriggerSourceBinding.matches).
_RESOURCE_ID_PAYLOAD_KEYS: dict[str, str] = {
    "CHANNEL_CREATE": "channel_id",
    "CHANNEL_UPDATE": "channel_id",
    "CHANNEL_DELETE": "channel_id",
    "THREAD_CREATE": "channel_id",
    "THREAD_UPDATE": "channel_id",
    "THREAD_DELETE": "channel_id",
    "THREAD_MEMBER_UPDATE": "thread_id",
    "GUILD_ROLE_CREATE": "role_id",
    "GUILD_ROLE_UPDATE": "role_id",
    "GUILD_ROLE_DELETE": "role_id",
    "GUILD_MEMBER_ADD": "discord_user_id",
    "GUILD_MEMBER_UPDATE": "discord_user_id",
    "GUILD_MEMBER_REMOVE": "discord_user_id",
}


def extract_discord_resource_id(event_type: str, payload: Mapping[str, object]) -> int | None:
    key = _RESOURCE_ID_PAYLOAD_KEYS.get(event_type)
    if key is None:
        return None
    value = payload.get(key)
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def envelope_from_gateway_inbox_row(row: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=row["event_id"],
        guild_id=row["guild_id"],
        event_type=row["event_type"],
        discord_sequence=row.get("discord_sequence"),
        discord_session_id=row["discord_session_id"],
        occurred_at=row.get("occurred_at"),
        received_at=row["received_at"],
        correlation_id=row["correlation_id"],
        causation_id=row.get("causation_id"),
        schema_version=row["schema_version"],
        payload=dict(row.get("payload") or {}),
        source=EventSource(row["source"]),
        origin=EventOrigin(row["origin"]),
        causation_depth=row["causation_depth"],
    )


def trigger_from_row(row: dict[str, Any]) -> CampaignTrigger:
    return CampaignTrigger(
        id=row["id"],
        owner_discord_user_id=row["owner_discord_user_id"],
        campaign_id=row["campaign_id"],
        event_type=row["event_type"],
        condition_ast=dict(row["condition_ast"]),
        max_causation_depth=row["max_causation_depth"],
        version=row["version"],
        requires_message_content=row["requires_message_content"],
    )


def _is_own_did_bot_message_create(envelope: EventEnvelope, *, our_bot_user_id: int | None) -> bool:
    """True only for a MESSAGE_CREATE genuinely authored by DID's OWN bound
    bot identity -- never merely "some bot" (a third-party bot's own
    messages are not DID's concern at all and must never enter the
    correlation-wait path below, which exists specifically to avoid a false
    negative on DID's own re-entrant sends) and never a hardcoded snowflake
    (``our_bot_user_id`` is the durable per-Guild identity
    ``did.infrastructure.stage04_repository.Stage04Repository.bot_identity``
    resolves, bound once from the real Gateway READY dispatch -- see the
    module docstring). ``our_bot_user_id is None`` (identity not yet known,
    or no ``stage04_repository`` supplied at all) deliberately resolves to
    False: without positive confirmation this message is DID's own, it must
    never be treated as a possible DID send either."""
    if envelope.event_type != "MESSAGE_CREATE" or our_bot_user_id is None:
        return False
    if not envelope.payload.get("author_is_bot", False):
        return False
    author_id = envelope.payload.get("author_discord_user_id")
    return (
        isinstance(author_id, int)
        and not isinstance(author_id, bool)
        and (author_id == our_bot_user_id)
    )


async def _correlate_bot_message(
    campaigns_repository: CampaignsRepository,
    admin_factory: async_sessionmaker[Any],
    envelope: EventEnvelope,
    *,
    guild_id: int,
) -> EventEnvelope | None:
    """Attempts to resolve a bot-authored MESSAGE_CREATE against the exact
    SENT delivery that produced it. Returns an enriched envelope (real
    ancestry/causation/origin) when resolved, or ``None`` when no matching
    delivery exists *yet* -- the caller decides, based on the event's own
    age, whether that means "keep waiting" or "give up and treat as
    ordinary" (see the module docstring)."""
    channel_id = envelope.payload.get("channel_id")
    message_id = envelope.payload.get("message_id")
    if not isinstance(channel_id, int) or not isinstance(message_id, int):
        return None
    match = await campaigns_repository.find_delivery_by_discord_message(
        admin_factory,
        guild_id=guild_id,
        discord_channel_id=channel_id,
        discord_message_id=message_id,
    )
    if match is None:
        return None
    ancestry = sorted(str(item) for item in (match.get("source_ancestry") or ()))
    source_correlation_id = match.get("source_correlation_id")
    source_event_id = match.get("source_event_id")
    return dataclasses.replace(
        envelope,
        origin=EventOrigin.DID_CAMPAIGN,
        correlation_id=(
            UUID(str(source_correlation_id))
            if source_correlation_id is not None
            else match["occurrence_id"]
        ),
        causation_id=(UUID(str(source_event_id)) if source_event_id is not None else None),
        causation_depth=int(match["source_causation_depth"]) + 1,
        payload={**envelope.payload, ANCESTRY_PAYLOAD_KEY: ancestry},
    )


async def consume_new_events_for_guild(
    *,
    campaigns_repository: CampaignsRepository,
    runtime_repository: RuntimeRepository,
    admin_factory: async_sessionmaker[Any],
    language_profiles: LanguageProfileRepository,
    translation_groups: TranslationGroupRepository,
    checker: TargetAuthorizationChecker,
    translation_provider: CampaignTranslationProvider | None,
    lease_owner: str,
    guild_id: int,
    batch_limit: int = 100,
    stage04_repository: Stage04Repository | None = None,
    provider_bindings: TranslationProviderBindingRepository | None = None,
    now: datetime | None = None,
) -> int:
    """One durable-transport pass for ``guild_id``: read every new
    ``discord_gateway_inbox`` row since the cursor, evaluate it against
    every candidate trigger bound to this Guild for its exact event_type,
    fan out whatever fires, and only then advance the cursor -- a crash at
    any point before the cursor is advanced simply replays the same batch
    on the next tick; ``consume_event_for_trigger``'s own
    ``message_campaign_trigger_consumptions`` dedup (WP1) is what makes
    that replay safe, never this cursor. Returns the number of triggers
    that actually fired this pass.

    An unresolved MESSAGE_CREATE confirmed to be authored by DID's OWN bot
    identity, younger than ``BOT_MESSAGE_CORRELATION_GRACE_SECONDS``, stops
    this pass from advancing the cursor past it (see the module docstring's
    "REQ-MSG-030 producing side" section) -- everything strictly before it
    in ``(received_at, event_id)`` order is still evaluated and the cursor
    still advances up to (not including) that event. A THIRD-PARTY bot's or
    a human's MESSAGE_CREATE is never subject to this wait at all -- only
    DID's own confirmed identity ever enters the correlation path. If it
    still cannot be correlated once the grace period elapses, it is
    deliberately never evaluated against any trigger (fail-closed -- see
    ``EventId.CAMPAIGN_BOT_MESSAGE_UNCORRELATED_SKIPPED``): silently
    treating it as an "ordinary" event at that point would reopen exactly
    the self/cross-campaign loop the ancestor-loop guard exists to prevent.

    ``message_content_available`` is always False here regardless of
    whether the (structural-only) MESSAGE_CREATE dispatch is currently
    enabled -- this transport never captures message content at all, so a
    bound trigger declaring ``requires_message_content=True`` always
    correctly fails closed via ``did.campaigns.causality.should_trigger``
    rather than silently treating absent content as a non-match.
    """
    rows = await runtime_repository.claim_new_campaign_events(guild_id, limit=batch_limit)
    if not rows:
        return 0
    reference_now = now or datetime.now(UTC)
    our_bot_user_id: int | None = None
    if stage04_repository is not None:
        our_bot_user_id, _installation_status = await stage04_repository.bot_identity(guild_id)

    fired_count = 0
    last_processed_row: dict[str, Any] | None = None
    for row in rows:
        envelope = envelope_from_gateway_inbox_row(row)
        if _is_own_did_bot_message_create(envelope, our_bot_user_id=our_bot_user_id):
            resolved = await _correlate_bot_message(
                campaigns_repository, admin_factory, envelope, guild_id=guild_id
            )
            if resolved is not None:
                envelope = resolved
            else:
                age = reference_now - envelope.received_at
                if age < timedelta(seconds=BOT_MESSAGE_CORRELATION_GRACE_SECONDS):
                    # Gateway-before-finalize race: do not advance the
                    # cursor past this event yet -- stop this pass here,
                    # the next tick re-attempts correlation.
                    break
                # Fail-closed: never correlated to a Stage09 delivery
                # within the grace window (or never will). The cursor
                # still advances past it -- this Guild's event processing
                # must not stall forever over one anomalous event -- but
                # it is never handed to any trigger. A future
                # reconciliation/repair pass may investigate; nothing here
                # exposes message content, ids, or PII beyond the guild_id
                # already durably known.
                emit_event(
                    logger,
                    logging.WARNING,
                    EventId.CAMPAIGN_BOT_MESSAGE_UNCORRELATED_SKIPPED,
                    fields={"guild_id": str(guild_id)},
                )
                last_processed_row = row
                continue
        discord_resource_id = extract_discord_resource_id(envelope.event_type, envelope.payload)
        candidate_rows = await campaigns_repository.list_candidate_triggers_for_event(
            admin_factory, guild_id=guild_id, event_type=envelope.event_type
        )
        for trigger_row in candidate_rows:
            trigger = trigger_from_row(trigger_row)
            result = await consume_event_for_trigger(
                repository=campaigns_repository,
                trigger=trigger,
                event=envelope,
                discord_resource_id=discord_resource_id,
                message_content_available=False,
            )
            if not result.fired or result.already_consumed or result.occurrence is None:
                continue
            fired_count += 1
            campaign = await load_campaign(
                campaigns_repository,
                owner_discord_user_id=trigger.owner_discord_user_id,
                campaign_id=trigger.campaign_id,
            )
            if campaign is None:
                continue
            context = await load_fan_out_context(
                campaigns_repository=campaigns_repository,
                admin_factory=admin_factory,
                language_profiles=language_profiles,
                translation_groups=translation_groups,
                campaign=campaign,
                translation_provider=translation_provider,
                stage04_repository=stage04_repository,
                provider_bindings=provider_bindings,
            )
            try:
                await fan_out_occurrence(
                    repository=campaigns_repository,
                    checker=checker,
                    campaign=campaign,
                    targets=context.targets,
                    occurrence=result.occurrence,
                    lease_owner=lease_owner,
                    topology_by_target=context.topology_by_target,
                    logical_group_expansion_by_target=context.logical_group_expansion_by_target,
                    language_profile_codes=context.language_profile_codes,
                    compiled_mentions=context.compiled_mentions,
                    template_variable_definitions=context.template_variable_definitions,
                    glossary_entries=context.glossary_entries,
                    translate_masked_text_for_language=context.translate_masked_text_for_language,
                )
            except Exception as exc:
                emit_event(
                    logger,
                    logging.ERROR,
                    EventId.CAMPAIGN_SCHEDULER_TICK_FAILED,
                    fields={"trigger_id": str(trigger.id), "error": str(exc)},
                )
        last_processed_row = row

    if last_processed_row is None:
        return fired_count
    await runtime_repository.advance_campaign_event_cursor(
        guild_id,
        last_event_id=UUID(str(last_processed_row["event_id"])),
        last_event_received_at=last_processed_row["received_at"],
    )
    return fired_count
