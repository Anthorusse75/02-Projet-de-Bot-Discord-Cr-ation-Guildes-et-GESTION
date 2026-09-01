"""WP12/WP8: the real Stage03 event transport for event-triggered
campaigns -- reads durable ``discord_gateway_inbox`` rows (via a per-Guild
cursor, migration ``0028_stage_09``) and feeds each one to
``did.campaigns.event_consumer.consume_event_for_trigger``, then fans out
whatever fires.

Covers every event_type Stage03's own gateway client actually captures
under its minimal-intents architecture (ADR-008): structural dispatches --
``GUILD_*``/``CHANNEL_*``/``THREAD_*``/``GUILD_ROLE_*``/``GUILD_MEMBER_*``.
``MESSAGE_CREATE`` and any other message-content-bearing dispatch are
outside Stage03's own capture surface entirely (no message intent is ever
requested) -- an event-triggered campaign depending on message content
stays governed by the existing REQ-MSG-020 capability/blocker machinery
(``did.campaigns.message_content_policy``), which this module does not and
cannot change; there is simply no durable event for it to consume yet.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from did.campaigns.activation import fan_out_occurrence
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

    MESSAGE_CONTENT is never available through this transport (Stage03's
    gateway client requests no message intent at all) -- a bound trigger
    declaring ``requires_message_content=True`` therefore always evaluates
    with ``message_content_available=False`` here, correctly failing closed
    via ``did.campaigns.causality.should_trigger`` rather than silently
    treating absent content as a non-match.
    """
    rows = await runtime_repository.claim_new_campaign_events(guild_id, limit=batch_limit)
    if not rows:
        return 0

    fired_count = 0
    for row in rows:
        envelope = envelope_from_gateway_inbox_row(row)
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
                    template_variable_definitions={},
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

    last_row = rows[-1]
    await runtime_repository.advance_campaign_event_cursor(
        guild_id,
        last_event_id=UUID(str(last_row["event_id"])),
        last_event_received_at=last_row["received_at"],
    )
    return fired_count
