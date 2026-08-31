"""Stage 09 campaign persistence.

Follows the Stage 03/08 convention exactly: short-lived transactions opened
through ``tenant_transaction`` with an explicit RLS context, raw
parameterized SQL (no ORM), ``FOR UPDATE SKIP LOCKED`` for atomic claims.

Two distinct authority levels are used deliberately:

* Owner-scoped methods (``create_campaign``, ``get_campaign``, ...) run
  under a ``UserContext`` -- RLS restricts them to the authenticated
  owner's own rows, mirroring every authorized API request.
* Guild-scoped methods (``create_target``, ``create_delivery``, ...) run
  under a ``TenantContext`` -- RLS restricts them to that one Guild.
* Cross-owner claim methods (``claim_due_schedules``) are system/scheduler
  operations that must see every owner's due work, so they run against the
  admin session factory (RLS-bypassing, same authority already used for
  cross-tenant fixture setup/teardown in the Stage 08 tests) rather than
  under any single owner's RLS context. This is a deliberate, narrow
  system-process exception -- never used to serve a user-facing request.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from did.domain.campaigns import (
    CampaignSchedule,
    CampaignTarget,
    CampaignTrigger,
    MessageCampaign,
    MessageDelivery,
    MessageOccurrence,
    TriggerSourceBinding,
)
from did.infrastructure.database import tenant_transaction
from did.tenancy.context import TenantContext, UserContext


class CampaignsRepository:
    def __init__(self, factory: async_sessionmaker[Any]) -> None:
        self._factory = factory

    async def create_campaign(self, campaign: MessageCampaign) -> None:
        async with tenant_transaction(
            self._factory, UserContext(user_id=campaign.owner_discord_user_id)
        ) as session:
            await session.execute(
                text(
                    "INSERT INTO message_campaigns "
                    "(id, owner_discord_user_id, logical_campaign_key, name, "
                    "source_language_code, message_model, allowed_mentions_policy, "
                    "attachment_policy, publication_mode, lifecycle_status, version) "
                    "VALUES (:id, :owner, :key, :name, :lang, CAST(:model AS JSONB), "
                    "CAST(:mentions AS JSONB), :attachments, :mode, :status, :version)"
                ),
                {
                    "id": campaign.id,
                    "owner": campaign.owner_discord_user_id,
                    "key": campaign.logical_campaign_key,
                    "name": campaign.name,
                    "lang": campaign.source_language_code,
                    "model": _to_json(campaign.message_model),
                    "mentions": _to_json(campaign.allowed_mentions_policy),
                    "attachments": campaign.attachment_policy.value,
                    "mode": campaign.publication_mode.value,
                    "status": campaign.lifecycle_status.value,
                    "version": campaign.version,
                },
            )

    async def get_campaign(
        self, owner_discord_user_id: int, campaign_id: UUID
    ) -> dict[str, Any] | None:
        async with tenant_transaction(
            self._factory, UserContext(user_id=owner_discord_user_id)
        ) as session:
            row = (
                (
                    await session.execute(
                        text("SELECT * FROM message_campaigns WHERE id=:id"),
                        {"id": campaign_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    async def list_campaigns(self, owner_discord_user_id: int) -> list[dict[str, Any]]:
        async with tenant_transaction(
            self._factory, UserContext(user_id=owner_discord_user_id)
        ) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM message_campaigns ORDER BY created_at"
                        )
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def create_schedule(self, schedule: CampaignSchedule) -> None:
        async with tenant_transaction(
            self._factory, UserContext(user_id=schedule.owner_discord_user_id)
        ) as session:
            await session.execute(
                text(
                    "INSERT INTO message_campaign_schedules "
                    "(id, owner_discord_user_id, campaign_id, schedule_kind, fire_at, rrule, "
                    "timezone, starts_at, misfire_policy, dst_nonexistent_policy, "
                    "dst_ambiguous_policy, catch_up_bound, next_fire_at, last_cursor_at, version) "
                    "VALUES (:id, :owner, :campaign_id, :kind, :fire_at, :rrule, :tz, :starts_at, "
                    ":misfire, :dst_nonexistent, :dst_ambiguous, :catch_up, :next_fire, "
                    ":last_cursor, :version)"
                ),
                {
                    "id": schedule.id,
                    "owner": schedule.owner_discord_user_id,
                    "campaign_id": schedule.campaign_id,
                    "kind": schedule.schedule_kind.value,
                    "fire_at": schedule.fire_at,
                    "rrule": schedule.rrule,
                    "tz": schedule.timezone,
                    "starts_at": schedule.starts_at,
                    "misfire": schedule.misfire_policy.value,
                    "dst_nonexistent": schedule.dst_nonexistent_policy.value,
                    "dst_ambiguous": schedule.dst_ambiguous_policy.value,
                    "catch_up": schedule.catch_up_bound,
                    "next_fire": schedule.next_fire_at,
                    "last_cursor": schedule.last_cursor_at,
                    "version": schedule.version,
                },
            )

    async def claim_due_schedules(
        self,
        admin_factory: async_sessionmaker[Any],
        *,
        now: datetime,
        lease_owner: str,
        lease_seconds: float = 30.0,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """System/scheduler-only: atomically claim due RECURRING/ONE_SHOT
        schedules across every owner. Must run on the admin (RLS-bypassing)
        session factory -- see the module docstring.
        """
        async with admin_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            "WITH candidate AS (SELECT id FROM message_campaign_schedules "
                            "WHERE next_fire_at <= :now AND "
                            "(leased_until IS NULL OR leased_until < :now) "
                            "ORDER BY next_fire_at LIMIT :limit FOR UPDATE SKIP LOCKED) "
                            "UPDATE message_campaign_schedules AS s SET "
                            "lease_owner=:owner, lease_token=:token, "
                            "leased_until=:now + (:lease_seconds * interval '1 second') "
                            "FROM candidate WHERE s.id=candidate.id "
                            "RETURNING s.id, s.owner_discord_user_id, s.campaign_id, "
                            "s.schedule_kind, s.rrule, s.timezone, s.starts_at, "
                            "s.misfire_policy, s.dst_nonexistent_policy, s.dst_ambiguous_policy, "
                            "s.catch_up_bound, s.last_cursor_at, s.version"
                        ),
                        {
                            "now": now,
                            "limit": limit,
                            "owner": lease_owner,
                            "token": uuid4(),
                            "lease_seconds": lease_seconds,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def create_target(self, target: CampaignTarget) -> None:
        async with tenant_transaction(
            self._factory, TenantContext(target.guild_id)
        ) as session:
            await session.execute(
                text(
                    "INSERT INTO message_campaign_targets "
                    "(id, guild_id, campaign_id, target_kind, discord_channel_id, "
                    "translation_group_id, translation_publication_mode, "
                    "selected_language_profile_ids) "
                    "VALUES (:id, :guild_id, :campaign_id, :kind, :channel_id, :group_id, "
                    ":pub_mode, CAST(:languages AS JSONB))"
                ),
                {
                    "id": target.id,
                    "guild_id": target.guild_id,
                    "campaign_id": target.campaign_id,
                    "kind": target.target_kind.value,
                    "channel_id": target.discord_channel_id,
                    "group_id": target.translation_group_id,
                    "pub_mode": (
                        target.translation_publication_mode.value
                        if target.translation_publication_mode
                        else None
                    ),
                    "languages": (
                        _to_json([str(x) for x in target.selected_language_profile_ids])
                        if target.selected_language_profile_ids
                        else None
                    ),
                },
            )

    async def create_occurrence(
        self, owner_discord_user_id: int, occurrence: MessageOccurrence
    ) -> bool:
        """Returns False (no-op) instead of raising when the deterministic
        occurrence_key already exists for this campaign -- the DB unique
        constraint is the single source of truth for duplicate prevention.
        """
        async with tenant_transaction(
            self._factory, UserContext(user_id=owner_discord_user_id)
        ) as session:
            result = await session.execute(
                text(
                    "INSERT INTO message_occurrences "
                    "(id, owner_discord_user_id, campaign_id, occurrence_key, "
                    "occurrence_source, scheduled_for, source_event_id, "
                    "source_correlation_id, status) "
                    "VALUES (:id, :owner, :campaign_id, :key, :source, :scheduled_for, "
                    ":event_id, :correlation_id, :status) "
                    "ON CONFLICT (campaign_id, occurrence_key) DO NOTHING"
                ),
                {
                    "id": occurrence.id,
                    "owner": owner_discord_user_id,
                    "campaign_id": occurrence.campaign_id,
                    "key": occurrence.occurrence_key,
                    "source": occurrence.occurrence_source.value,
                    "scheduled_for": occurrence.scheduled_for,
                    "event_id": occurrence.source_event_id,
                    "correlation_id": occurrence.source_correlation_id,
                    "status": occurrence.status.value,
                },
            )
        return cast(CursorResult[Any], result).rowcount == 1

    async def create_delivery(self, delivery: MessageDelivery) -> bool:
        """Returns False when delivery_key already exists for this Guild --
        the WP6 idempotency ledger's core guarantee."""
        async with tenant_transaction(
            self._factory, TenantContext(delivery.guild_id)
        ) as session:
            result = await session.execute(
                text(
                    "INSERT INTO message_deliveries "
                    "(id, guild_id, campaign_id, occurrence_id, target_id, "
                    "language_profile_id, delivery_key, discord_channel_id, status, "
                    "allowed_mentions_snapshot) "
                    "VALUES (:id, :guild_id, :campaign_id, :occurrence_id, :target_id, "
                    ":language_id, :key, :channel_id, :status, CAST(:mentions AS JSONB)) "
                    "ON CONFLICT (guild_id, delivery_key) DO NOTHING"
                ),
                {
                    "id": delivery.id,
                    "guild_id": delivery.guild_id,
                    "campaign_id": delivery.campaign_id,
                    "occurrence_id": delivery.occurrence_id,
                    "target_id": delivery.target_id,
                    "language_id": delivery.language_profile_id,
                    "key": delivery.delivery_key,
                    "channel_id": delivery.discord_channel_id,
                    "status": delivery.status.value,
                    "mentions": _to_json(delivery.allowed_mentions_snapshot),
                },
            )
        return cast(CursorResult[Any], result).rowcount == 1

    async def claim_next_delivery(
        self, guild_id: int, *, lease_owner: str, limit: int = 1
    ) -> list[dict[str, Any]]:
        """Guild-scoped atomic claim of PENDING deliveries (the delivery
        worker's WP13 dispatch primitive)."""
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "WITH candidate AS (SELECT id FROM message_deliveries "
                            "WHERE guild_id=:guild_id AND status='PENDING' "
                            "ORDER BY created_at LIMIT :limit FOR UPDATE SKIP LOCKED) "
                            "UPDATE message_deliveries AS d SET status='CLAIMED', "
                            "attempt_count=attempt_count+1, updated_at=now() "
                            "FROM candidate WHERE d.id=candidate.id "
                            "RETURNING d.id, d.campaign_id, d.occurrence_id, d.target_id, "
                            "d.language_profile_id, d.delivery_key, d.discord_channel_id, "
                            "d.discord_nonce, d.attempt_count"
                        ),
                        {"guild_id": guild_id, "owner": lease_owner, "limit": limit},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def create_trigger(self, trigger: CampaignTrigger) -> None:
        async with tenant_transaction(
            self._factory, UserContext(user_id=trigger.owner_discord_user_id)
        ) as session:
            await session.execute(
                text(
                    "INSERT INTO message_campaign_triggers "
                    "(id, owner_discord_user_id, campaign_id, event_type, "
                    "condition_ast, max_causation_depth, version) "
                    "VALUES (:id, :owner, :campaign_id, :event_type, "
                    "CAST(:condition AS JSONB), :depth, :version)"
                ),
                {
                    "id": trigger.id,
                    "owner": trigger.owner_discord_user_id,
                    "campaign_id": trigger.campaign_id,
                    "event_type": trigger.event_type,
                    "condition": _to_json(trigger.condition_ast),
                    "depth": trigger.max_causation_depth,
                    "version": trigger.version,
                },
            )

    async def create_trigger_source(self, binding: TriggerSourceBinding) -> None:
        async with tenant_transaction(
            self._factory, TenantContext(binding.guild_id)
        ) as session:
            await session.execute(
                text(
                    "INSERT INTO message_campaign_trigger_sources "
                    "(id, guild_id, trigger_id, source_scope_kind, discord_resource_id) "
                    "VALUES (:id, :guild_id, :trigger_id, :kind, :resource_id)"
                ),
                {
                    "id": binding.id,
                    "guild_id": binding.guild_id,
                    "trigger_id": binding.trigger_id,
                    "kind": binding.source_scope_kind.value,
                    "resource_id": binding.discord_resource_id,
                },
            )

    async def record_trigger_consumption(
        self, guild_id: int, trigger_id: UUID, event_id: UUID, occurrence_id: UUID | None
    ) -> bool:
        """Returns False when (guild_id, trigger_id, event_id) was already
        consumed -- the durable dedup guarantee backing REQ-MSG-027/030."""
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await session.execute(
                text(
                    "INSERT INTO message_campaign_trigger_consumptions "
                    "(guild_id, trigger_id, event_id, occurrence_id) "
                    "VALUES (:guild_id, :trigger_id, :event_id, :occurrence_id) "
                    "ON CONFLICT (guild_id, trigger_id, event_id) DO NOTHING"
                ),
                {
                    "guild_id": guild_id,
                    "trigger_id": trigger_id,
                    "event_id": event_id,
                    "occurrence_id": occurrence_id,
                },
            )
        return cast(CursorResult[Any], result).rowcount == 1

    async def load_trigger_sources(
        self, guild_id: int, trigger_id: UUID
    ) -> Sequence[dict[str, Any]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM message_campaign_trigger_sources "
                            "WHERE guild_id=:guild_id AND trigger_id=:trigger_id"
                        ),
                        {"guild_id": guild_id, "trigger_id": trigger_id},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]


def _to_json(value: object) -> str:
    import json

    return json.dumps(value)
