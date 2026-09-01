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

from did.campaigns.causality import validate_condition_ast
from did.domain.campaigns import (
    ApprovedVariant,
    CampaignSchedule,
    CampaignTarget,
    CampaignTrigger,
    GlossaryEntry,
    GlossaryScope,
    MessageCampaign,
    MessageDelivery,
    MessageOccurrence,
    TriggerSourceBinding,
)
from did.infrastructure.database import tenant_transaction
from did.tenancy.context import TenantContext, UserContext

#: Only a campaign in one of these lifecycle states may have its schedule
#: fire -- a PAUSED/CANCELLED/COMPLETED/FAILED_INTERVENTION campaign's
#: schedule must never be claimed, regardless of next_fire_at.
_FIRING_ELIGIBLE_LIFECYCLE_STATUSES = ("SCHEDULED_ARMED", "ACTIVE_RUNNING")


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

    async def get_campaign_by_key(
        self, owner_discord_user_id: int, logical_campaign_key: str
    ) -> dict[str, Any] | None:
        """Owner-scoped lookup by the caller's own natural idempotency key
        (``UNIQUE(owner_discord_user_id, logical_campaign_key)``) -- lets a
        create-campaign API call detect a retried request and replay the
        existing campaign instead of erroring on the unique constraint."""
        async with tenant_transaction(
            self._factory, UserContext(user_id=owner_discord_user_id)
        ) as session:
            row = (
                (
                    await session.execute(
                        text("SELECT * FROM message_campaigns WHERE logical_campaign_key=:key"),
                        {"key": logical_campaign_key},
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
                (await session.execute(text("SELECT * FROM message_campaigns ORDER BY created_at")))
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def update_campaign_draft_fields(
        self,
        owner_discord_user_id: int,
        campaign_id: UUID,
        expected_version: int,
        *,
        name: str | None = None,
        message_model: dict[str, object] | None = None,
        allowed_mentions_policy: dict[str, object] | None = None,
        attachment_policy: str | None = None,
    ) -> bool:
        """Owner-scoped, optimistic-concurrency (CAS on ``version``) partial
        update of a campaign's authoring fields -- fenced by
        ``lifecycle_status='DRAFT'`` in the WHERE clause itself, never
        merely checked beforehand by the caller: a campaign that left DRAFT
        between the caller's read and this write can never be silently
        edited. Returns False (safe no-op the caller must treat as a
        conflict) when the campaign does not exist for this owner, is not
        currently DRAFT, or ``expected_version`` is stale."""
        async with tenant_transaction(
            self._factory, UserContext(user_id=owner_discord_user_id)
        ) as session:
            result = await session.execute(
                text(
                    "UPDATE message_campaigns SET "
                    "name=COALESCE(:name, name), "
                    "message_model=COALESCE(CAST(:model AS JSONB), message_model), "
                    "allowed_mentions_policy=COALESCE(CAST(:mentions AS JSONB), "
                    "allowed_mentions_policy), "
                    "attachment_policy=COALESCE(:attachments, attachment_policy), "
                    "version=version+1, updated_at=now() "
                    "WHERE id=:id AND lifecycle_status='DRAFT' AND version=:expected_version"
                ),
                {
                    "id": campaign_id,
                    "name": name,
                    "model": _to_json(message_model) if message_model is not None else None,
                    "mentions": (
                        _to_json(allowed_mentions_policy)
                        if allowed_mentions_policy is not None
                        else None
                    ),
                    "attachments": attachment_policy,
                    "expected_version": expected_version,
                },
            )
        return cast(CursorResult[Any], result).rowcount == 1

    async def update_campaign_lifecycle_status(
        self,
        owner_discord_user_id: int,
        campaign_id: UUID,
        expected_version: int,
        *,
        new_status: str,
    ) -> bool:
        """Owner-scoped, optimistic-concurrency (CAS on ``version``)
        persistence of a lifecycle transition. The transition's legality
        itself is the domain layer's job (``MessageCampaign.transition_to``,
        called by the caller BEFORE this method) -- this method only proves
        the row is still at the version the caller last observed, so a
        concurrent transition (another request, a background worker) can
        never be silently clobbered. Returns False (safe no-op, the caller
        must treat it as a conflict) when the campaign does not exist for
        this owner or ``expected_version`` is stale."""
        async with tenant_transaction(
            self._factory, UserContext(user_id=owner_discord_user_id)
        ) as session:
            result = await session.execute(
                text(
                    "UPDATE message_campaigns SET lifecycle_status=:status, "
                    "version=version+1, updated_at=now() "
                    "WHERE id=:id AND version=:expected_version"
                ),
                {"id": campaign_id, "status": new_status, "expected_version": expected_version},
            )
        return cast(CursorResult[Any], result).rowcount == 1

    async def list_deliveries_for_campaign(
        self,
        admin_factory: async_sessionmaker[Any],
        owner_discord_user_id: int,
        campaign_id: UUID,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """System/runtime-only read, mirroring
        :meth:`list_targets_for_campaign`'s identical rationale: a
        campaign's deliveries span every Guild it targets, so there is no
        single ``TenantContext`` that can see all of them under ordinary
        RLS. Runs on the admin (RLS-bypassing) session factory, with
        ownership verified in the query itself (the join to
        ``message_campaigns``) rather than trusted from the caller -- used
        only to serve the owner's own delivery-history API request, never
        by the runtime itself."""
        if not 1 <= limit <= 1000:
            raise ValueError("delivery listing limit must be between 1 and 1000")
        async with admin_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT d.* FROM message_deliveries d "
                            "JOIN message_campaigns c ON c.id = d.campaign_id "
                            "WHERE d.campaign_id = :campaign_id "
                            "AND c.owner_discord_user_id = :owner "
                            "ORDER BY d.created_at DESC LIMIT :limit"
                        ),
                        {
                            "campaign_id": campaign_id,
                            "owner": owner_discord_user_id,
                            "limit": limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def get_schedule(
        self, owner_discord_user_id: int, schedule_id: UUID
    ) -> dict[str, Any] | None:
        async with tenant_transaction(
            self._factory, UserContext(user_id=owner_discord_user_id)
        ) as session:
            row = (
                (
                    await session.execute(
                        text("SELECT * FROM message_campaign_schedules WHERE id=:id"),
                        {"id": schedule_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    async def create_schedule(self, schedule: CampaignSchedule) -> None:
        async with tenant_transaction(
            self._factory, UserContext(user_id=schedule.owner_discord_user_id)
        ) as session:
            await session.execute(
                text(
                    "INSERT INTO message_campaign_schedules "
                    "(id, owner_discord_user_id, campaign_id, schedule_kind, fire_at, rrule, "
                    "timezone, starts_at, misfire_policy, dst_nonexistent_policy, "
                    "dst_ambiguous_policy, catch_up_bound, next_fire_at, last_cursor_local, "
                    "version) "
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
                    "last_cursor": schedule.last_cursor_local,
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
        schedules across every owner, but ONLY when the owning campaign is
        still in a firing-eligible lifecycle state (SCHEDULED_ARMED or
        ACTIVE_RUNNING) -- a PAUSED/CANCELLED/COMPLETED/FAILED_INTERVENTION
        campaign's schedule is never claimed even if next_fire_at is due.
        Must run on the admin (RLS-bypassing) session factory -- see the
        module docstring. Each returned row's ``lease_token`` MUST be passed
        back to :meth:`finalize_schedule_claim`; a claimant that loses its
        lease (expiry, another worker reclaiming) cannot finalize.
        """
        async with admin_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            "WITH candidate AS ("
                            "SELECT s.id FROM message_campaign_schedules s "
                            "JOIN message_campaigns c "
                            "ON c.owner_discord_user_id = s.owner_discord_user_id "
                            "AND c.id = s.campaign_id "
                            "WHERE s.next_fire_at <= :now AND "
                            "(s.leased_until IS NULL OR s.leased_until < :now) AND "
                            "c.lifecycle_status = ANY(:eligible_statuses) "
                            "ORDER BY s.next_fire_at LIMIT :limit FOR UPDATE OF s SKIP LOCKED) "
                            "UPDATE message_campaign_schedules AS s SET "
                            "lease_owner=:owner, lease_token=:token, "
                            "leased_until=:now + (:lease_seconds * interval '1 second') "
                            "FROM candidate WHERE s.id=candidate.id "
                            "RETURNING s.id, s.owner_discord_user_id, s.campaign_id, "
                            "s.schedule_kind, s.fire_at, s.rrule, s.timezone, s.starts_at, "
                            "s.misfire_policy, s.dst_nonexistent_policy, s.dst_ambiguous_policy, "
                            "s.catch_up_bound, s.last_cursor_local, s.version, s.lease_token"
                        ),
                        {
                            "now": now,
                            "limit": limit,
                            "owner": lease_owner,
                            "token": uuid4(),
                            "lease_seconds": lease_seconds,
                            "eligible_statuses": list(_FIRING_ELIGIBLE_LIFECYCLE_STATUSES),
                        },
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def finalize_schedule_claim(
        self,
        admin_factory: async_sessionmaker[Any],
        schedule_id: UUID,
        lease_token: UUID,
        *,
        now: datetime,
        new_last_cursor_local: datetime | None,
        new_next_fire_at: datetime | None,
    ) -> bool:
        """Write back the evaluated cursor/next-fire, fenced by
        ``lease_token`` AND unexpired ``leased_until`` AND the owning
        campaign still being firing-eligible at commit time -- three
        independent, jointly-necessary conditions (external-review finding,
        second remediation pass: token-matching alone let a worker that ran
        past its own promised lease window still commit, since nothing else
        had raced in to change the token yet). If another worker already
        reclaimed this schedule (token mismatch), if this worker overran its
        own lease window (even with no competing claimant -- a stalled
        worker's computation was made against a ``now`` that may no longer be
        current), or if the campaign was paused/cancelled after the claim was
        taken, the update becomes a safe no-op: the stale/unsafe worker must
        not advance the cursor or next_fire_at. Always releases the lease on
        success.
        """
        async with admin_factory() as session, session.begin():
            result = await session.execute(
                text(
                    "UPDATE message_campaign_schedules AS s SET "
                    "last_cursor_local=:cursor, next_fire_at=:next_fire, "
                    "lease_owner=NULL, lease_token=NULL, leased_until=NULL, "
                    "updated_at=now() "
                    "FROM message_campaigns AS c "
                    "WHERE s.id=:id AND s.lease_token=:token "
                    "AND s.leased_until IS NOT NULL AND s.leased_until > :now "
                    "AND c.owner_discord_user_id = s.owner_discord_user_id "
                    "AND c.id = s.campaign_id "
                    "AND c.lifecycle_status = ANY(:eligible_statuses)"
                ),
                {
                    "id": schedule_id,
                    "token": lease_token,
                    "now": now,
                    "cursor": new_last_cursor_local,
                    "next_fire": new_next_fire_at,
                    "eligible_statuses": list(_FIRING_ELIGIBLE_LIFECYCLE_STATUSES),
                },
            )
        return cast(CursorResult[Any], result).rowcount == 1

    async def create_target(self, target: CampaignTarget) -> None:
        async with tenant_transaction(self._factory, TenantContext(target.guild_id)) as session:
            await session.execute(
                text(
                    "INSERT INTO message_campaign_targets "
                    "(id, guild_id, campaign_id, target_kind, discord_channel_id, "
                    "translation_group_id, translation_publication_mode, "
                    "selected_language_profile_ids, logical_group_id) "
                    "VALUES (:id, :guild_id, :campaign_id, :kind, :channel_id, :group_id, "
                    ":pub_mode, CAST(:languages AS JSONB), :logical_group_id)"
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
                    "logical_group_id": target.logical_group_id,
                },
            )

    async def list_targets_for_campaign(
        self,
        admin_factory: async_sessionmaker[Any],
        owner_discord_user_id: int,
        campaign_id: UUID,
    ) -> list[dict[str, Any]]:
        """System/runtime-only read: every target across every Guild a
        campaign touches -- a campaign header is owner-scoped, not
        Guild-scoped (REQ-MSG-002: a single campaign may target several
        Guilds), so there is no single ``TenantContext`` that could see all
        of a campaign's targets at once under ordinary RLS. Mirrors
        :meth:`claim_due_schedules`'s exact system-process exception: runs
        on the admin (RLS-bypassing) session factory, with ownership
        verified in the query itself (the join to ``message_campaigns``)
        rather than relied upon from the caller. Never used to serve a
        user-facing request directly -- callers are the campaign runtime
        (schedulers/event consumers/simulation), which already durably
        loaded ``owner_discord_user_id`` from the campaign row itself."""
        async with admin_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT t.* FROM message_campaign_targets t "
                            "JOIN message_campaigns c ON c.id = t.campaign_id "
                            "WHERE t.campaign_id = :campaign_id "
                            "AND c.owner_discord_user_id = :owner "
                            "ORDER BY t.id"
                        ),
                        {"campaign_id": campaign_id, "owner": owner_discord_user_id},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

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
                    "source_correlation_id, source_causation_depth, source_ancestry, status) "
                    "VALUES (:id, :owner, :campaign_id, :key, :source, :scheduled_for, "
                    ":event_id, :correlation_id, :causation_depth, CAST(:ancestry AS JSONB), "
                    ":status) "
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
                    "causation_depth": occurrence.source_causation_depth,
                    "ancestry": _to_json(sorted(occurrence.source_ancestry)),
                    "status": occurrence.status.value,
                },
            )
        return cast(CursorResult[Any], result).rowcount == 1

    async def get_occurrence_by_key(
        self, owner_discord_user_id: int, campaign_id: UUID, occurrence_key: str
    ) -> dict[str, Any] | None:
        """The recovery-path lookup for :meth:`create_occurrence` returning
        False: the occurrence already exists (this could be the very
        occurrence a prior, possibly-crashed fan-out attempt created) --
        callers use this to find it and resume via
        :meth:`claim_occurrence_for_fanout` rather than treating "already
        exists" as an error."""
        async with tenant_transaction(
            self._factory, UserContext(user_id=owner_discord_user_id)
        ) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM message_occurrences "
                            "WHERE campaign_id=:campaign_id AND occurrence_key=:key"
                        ),
                        {"campaign_id": campaign_id, "key": occurrence_key},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    async def claim_occurrence_for_fanout(
        self,
        owner_discord_user_id: int,
        occurrence_id: UUID,
        *,
        lease_owner: str,
        lease_seconds: float = 30.0,
    ) -> dict[str, Any] | None:
        """WP12 crash-safety: claims exactly ``occurrence_id`` (never an
        arbitrary other occurrence -- see the identical named-identity
        rationale in ``CampaignsRepository.claim_delivery``) if it is
        ``PENDING_FANOUT`` or stuck in ``CLAIMED`` past its lease expiry
        (a fan-out worker crashed mid-expansion). ``FANNED_OUT``/
        ``COMPLETED``/``FAILED`` occurrences are never reclaimed -- fan-out
        is not repeated once it has genuinely finished (successfully or
        not); a partial-failure retry is a distinct, explicit decision, not
        an automatic reclaim. Returns ``None`` (idempotent no-op) if not
        currently claimable, including for a foreign/nonexistent id."""
        async with tenant_transaction(
            self._factory, UserContext(user_id=owner_discord_user_id)
        ) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "UPDATE message_occurrences SET status='CLAIMED', "
                            "lease_owner=:owner, lease_token=:token, "
                            "leased_until=now() + (:lease_seconds * interval '1 second'), "
                            "updated_at=now() "
                            "WHERE id=:id AND ("
                            "status='PENDING_FANOUT' OR "
                            "(status='CLAIMED' AND (leased_until IS NULL OR leased_until < now()))"
                            ") "
                            "RETURNING *"
                        ),
                        {
                            "id": occurrence_id,
                            "owner": lease_owner,
                            "token": uuid4(),
                            "lease_seconds": lease_seconds,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    async def renew_occurrence_fanout_lease(
        self,
        owner_discord_user_id: int,
        occurrence_id: UUID,
        lease_token: UUID,
        *,
        lease_seconds: float,
    ) -> bool:
        """Heartbeat renewal for a long-running fan-out (many Guilds/
        destinations/translation-provider calls can easily outlive a short
        fixed lease). Fenced by the exact lease token the caller was granted
        by :meth:`claim_occurrence_for_fanout` -- ``False`` means the lease
        was already lost (expired and possibly reclaimed by another worker),
        and the caller must stop and never report success."""
        if lease_seconds < 0.05:
            raise ValueError("occurrence fan-out lease duration must be at least 50ms")
        async with tenant_transaction(
            self._factory, UserContext(user_id=owner_discord_user_id)
        ) as session:
            result = await session.execute(
                text(
                    "UPDATE message_occurrences SET "
                    "leased_until=now() + (:lease_seconds * interval '1 second'), "
                    "updated_at=now() "
                    "WHERE id=:id AND status='CLAIMED' AND lease_token=:token"
                ),
                {"id": occurrence_id, "token": lease_token, "lease_seconds": lease_seconds},
            )
        return cast(CursorResult[Any], result).rowcount == 1

    async def finalize_occurrence_fanout(
        self,
        owner_discord_user_id: int,
        occurrence_id: UUID,
        lease_token: UUID,
        *,
        status: str,
    ) -> bool:
        """Fenced CLAIMED -> FANNED_OUT/FAILED transition, releasing the
        lease. A worker that lost its lease (expiry + reclaim by another
        worker) gets ``False`` -- a safe no-op, never a silent overwrite of
        a fan-out another worker already completed or is now responsible
        for."""
        async with tenant_transaction(
            self._factory, UserContext(user_id=owner_discord_user_id)
        ) as session:
            result = await session.execute(
                text(
                    "UPDATE message_occurrences SET status=:status, "
                    "lease_owner=NULL, lease_token=NULL, leased_until=NULL, updated_at=now() "
                    "WHERE id=:id AND status='CLAIMED' AND lease_token=:token"
                ),
                {"id": occurrence_id, "token": lease_token, "status": status},
            )
        return cast(CursorResult[Any], result).rowcount == 1

    async def list_pending_delivery_ids(self, guild_id: int, *, limit: int = 200) -> list[UUID]:
        """Read-only: every currently-PENDING delivery id for ``guild_id``,
        oldest first -- the durable delivery-dispatch routing sweep
        (``did.campaigns.dispatch.route_pending_deliveries_to_jobs``) uses
        this to (re-)enqueue a discord_io_jobs row for each one. Never
        claims/mutates anything itself."""
        if not 1 <= limit <= 1000:
            raise ValueError("pending delivery listing limit must be between 1 and 1000")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT id FROM message_deliveries WHERE guild_id=:guild_id "
                        "AND status='PENDING' ORDER BY created_at LIMIT :limit"
                    ),
                    {"guild_id": guild_id, "limit": limit},
                )
            ).scalars()
        return [UUID(str(value)) for value in rows]

    async def create_delivery(self, delivery: MessageDelivery) -> bool:
        """Returns False when delivery_key already exists for this Guild --
        the WP6 idempotency ledger's core guarantee. ``delivery.content_snapshot``,
        when given, is the exact resolved MessageModel (already
        translated/glossary-applied/approved as appropriate) the caller has
        decided this specific delivery must send -- the delivery worker
        (``did.campaigns.delivery_worker``) sends precisely this and never
        re-derives content of its own at send time."""
        async with tenant_transaction(self._factory, TenantContext(delivery.guild_id)) as session:
            result = await session.execute(
                text(
                    "INSERT INTO message_deliveries "
                    "(id, guild_id, campaign_id, occurrence_id, target_id, "
                    "language_profile_id, delivery_key, discord_channel_id, status, "
                    "allowed_mentions_snapshot, content_snapshot) "
                    "VALUES (:id, :guild_id, :campaign_id, :occurrence_id, :target_id, "
                    ":language_id, :key, :channel_id, :status, CAST(:mentions AS JSONB), "
                    "CAST(:content AS JSONB)) "
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
                    "content": (
                        _to_json(delivery.content_snapshot)
                        if delivery.content_snapshot is not None
                        else None
                    ),
                },
            )
        return cast(CursorResult[Any], result).rowcount == 1

    async def claim_next_delivery(
        self,
        guild_id: int,
        *,
        lease_owner: str,
        lease_seconds: float = 30.0,
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        """Guild-scoped atomic claim of PENDING deliveries (the delivery
        worker's WP13 dispatch primitive), durably lease-fenced.

        Also reclaims deliveries stuck in ``CLAIMED`` past their lease
        expiry -- safe because ``CLAIMED`` means the previous worker never
        even reached the external send call yet (see
        :meth:`mark_delivery_sending`); once a worker marks a delivery
        ``SENDING`` it is no longer eligible here, since a stale reclaim at
        that point is exactly the ambiguous-outcome scenario
        ``did.campaigns.delivery_reconciliation`` handles instead of a
        blind second claim. Every returned row's ``lease_token`` MUST be
        passed to :meth:`mark_delivery_sending`/:meth:`finalize_delivery`.
        """
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "WITH candidate AS (SELECT id FROM message_deliveries "
                            "WHERE guild_id=:guild_id AND ("
                            "status='PENDING' OR "
                            "(status='CLAIMED' AND (leased_until IS NULL OR leased_until < now()))"
                            ") "
                            "ORDER BY created_at LIMIT :limit FOR UPDATE SKIP LOCKED) "
                            "UPDATE message_deliveries AS d SET status='CLAIMED', "
                            "lease_owner=:owner, lease_token=:token, "
                            "leased_until=now() + (:lease_seconds * interval '1 second'), "
                            "attempt_count=attempt_count+1, updated_at=now() "
                            "FROM candidate WHERE d.id=candidate.id "
                            "RETURNING d.id, d.campaign_id, d.occurrence_id, d.target_id, "
                            "d.language_profile_id, d.delivery_key, d.discord_channel_id, "
                            "d.discord_nonce, d.attempt_count, d.lease_token, "
                            "d.content_snapshot, d.allowed_mentions_snapshot"
                        ),
                        {
                            "guild_id": guild_id,
                            "owner": lease_owner,
                            "token": uuid4(),
                            "lease_seconds": lease_seconds,
                            "limit": limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def claim_delivery(
        self,
        guild_id: int,
        delivery_id: UUID,
        *,
        lease_owner: str,
        lease_seconds: float = 30.0,
    ) -> dict[str, Any] | None:
        """Named-identity counterpart to :meth:`claim_next_delivery`
        (external-review finding, fourth remediation pass): claims exactly
        ``delivery_id`` -- never an arbitrary next-pending row in
        ``guild_id`` -- with the identical PENDING-or-expired-CLAIMED
        eligibility and lease semantics. Returns ``None`` (never another
        delivery) when ``delivery_id`` does not exist, belongs to another
        Guild, or is not currently eligible (already ``SENDING``, resolved
        to a terminal status, or still validly leased by another worker) --
        the caller must treat that as an idempotent no-op, not an error.

        This is what a durable governor job that names one specific
        ``delivery_id`` must use instead of :meth:`claim_next_delivery`: a
        job's identity and the row it is allowed to touch must be the same
        row, so a delayed/replayed/stale job can never consume a different
        delivery than the one it names.
        """
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "UPDATE message_deliveries AS d SET status='CLAIMED', "
                            "lease_owner=:owner, lease_token=:token, "
                            "leased_until=now() + (:lease_seconds * interval '1 second'), "
                            "attempt_count=attempt_count+1, updated_at=now() "
                            "WHERE d.guild_id=:guild_id AND d.id=:delivery_id AND ("
                            "status='PENDING' OR "
                            "(status='CLAIMED' AND (leased_until IS NULL OR leased_until < now()))"
                            ") "
                            "RETURNING d.id, d.campaign_id, d.occurrence_id, d.target_id, "
                            "d.language_profile_id, d.delivery_key, d.discord_channel_id, "
                            "d.discord_nonce, d.attempt_count, d.lease_token, "
                            "d.content_snapshot, d.allowed_mentions_snapshot"
                        ),
                        {
                            "guild_id": guild_id,
                            "delivery_id": delivery_id,
                            "owner": lease_owner,
                            "token": uuid4(),
                            "lease_seconds": lease_seconds,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    async def get_delivery_status(self, guild_id: int, delivery_id: UUID) -> str | None:
        """Cheap existence/status probe for a job whose named delivery
        turned out not to be claimable -- lets the caller distinguish
        "already resolved" (SENT/FAILED/UNKNOWN/INTERVENTION_REQUIRED) from
        "genuinely gone/foreign" (returns None) for audit/logging, without
        claiming or mutating anything."""
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            status = await session.scalar(
                text("SELECT status FROM message_deliveries WHERE guild_id=:guild_id AND id=:id"),
                {"guild_id": guild_id, "id": delivery_id},
            )
        return str(status) if status is not None else None

    async def find_delivery_by_discord_message(
        self,
        admin_factory: async_sessionmaker[Any],
        *,
        guild_id: int,
        discord_channel_id: int,
        discord_message_id: int,
    ) -> dict[str, Any] | None:
        """REQ-MSG-030 producing side: resolves a Gateway-captured
        MESSAGE_CREATE back to the exact SENT delivery (and its
        occurrence's durable causal metadata -- ``source_causation_depth``/
        ``source_ancestry``/``source_correlation_id``/``source_event_id``)
        that produced it, if any. System/runtime-only cross-authority read
        -- a delivery is Guild-scoped and its occurrence is owner-scoped, so
        no single ``TenantContext`` can see both at once under ordinary
        RLS; runs on the admin (RLS-bypassing) factory like
        :meth:`list_targets_for_campaign`. Only ever matches a delivery
        already finalized ``SENT`` with this EXACT (guild, channel, message)
        triple -- never inferred, never a caller-supplied guess."""
        async with admin_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT d.id AS delivery_id, d.campaign_id, d.occurrence_id, "
                            "o.source_causation_depth, o.source_ancestry, "
                            "o.source_correlation_id, o.source_event_id "
                            "FROM message_deliveries d "
                            "JOIN message_occurrences o ON o.id = d.occurrence_id "
                            "WHERE d.guild_id = :guild_id "
                            "AND d.discord_channel_id = :channel_id "
                            "AND d.discord_message_id = :message_id "
                            "AND d.status = 'SENT'"
                        ),
                        {
                            "guild_id": guild_id,
                            "channel_id": discord_channel_id,
                            "message_id": discord_message_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    async def purge_terminal_deliveries(
        self, guild_id: int, *, cutoff: datetime, limit: int = 1000
    ) -> int:
        """REQ-MSG-019 delivery-history retention: permanently deletes
        SENT/FAILED deliveries (the only genuinely terminal, resolved
        states) last updated before ``cutoff`` for this Guild. Never
        touches PENDING/CLAIMED/SENDING/UNKNOWN/INTERVENTION_REQUIRED --
        active or still-ambiguous records are not history yet and are
        never purged by age alone, regardless of how old they are. Returns
        the number of rows actually deleted (may be less than every
        eligible row when ``limit`` is reached; the caller is expected to
        call again for a full sweep). Guild-scoped (RLS) like every other
        message_deliveries mutation -- a purge for one Guild can never
        touch another Guild's or another owner's rows."""
        if limit < 1:
            raise ValueError("purge limit must be positive")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await session.execute(
                text(
                    "WITH candidate AS (SELECT id FROM message_deliveries "
                    "WHERE guild_id=:guild_id AND status IN ('SENT','FAILED') "
                    "AND updated_at < :cutoff ORDER BY updated_at LIMIT :limit) "
                    "DELETE FROM message_deliveries WHERE id IN (SELECT id FROM candidate)"
                ),
                {"guild_id": guild_id, "cutoff": cutoff, "limit": limit},
            )
        return cast(CursorResult[Any], result).rowcount

    async def mark_delivery_sending(
        self,
        delivery_id: UUID,
        guild_id: int,
        lease_token: UUID,
        *,
        now: datetime,
        discord_nonce: str | None = None,
    ) -> bool:
        """CLAIMED -> SENDING, fenced by ``lease_token`` AND an unexpired
        ``leased_until`` (external-review finding, second remediation pass:
        token-matching alone let a worker begin the irreversible external
        mutation on a lease it had already overrun, since nothing else had
        raced in yet to change the token). An expired CLAIMED lease can never
        begin the external send -- the caller must re-claim instead. Once
        this succeeds, the delivery is no longer eligible for stale-lease
        reclaim by :meth:`claim_next_delivery` -- only :meth:`finalize_delivery`
        (by the same worker, using the same token) may resolve it further,
        and deliberately does NOT re-check ``leased_until`` (see that
        method's docstring for why).

        ``discord_nonce``, when given, is durably persisted in the SAME
        fenced transition that is about to make the delivery worker attempt
        the actual external send -- this is the one and only point a fresh
        nonce is ever generated for a delivery's first attempt. If the
        worker then crashes before :meth:`finalize_delivery`, the stalled-
        SENDING reconciliation path (:meth:`claim_stalled_sending_for_reconciliation`)
        reads this same already-persisted nonce back and reuses it for a
        same-nonce retry -- a fresh nonce is never generated for a retry.
        """
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await session.execute(
                text(
                    "UPDATE message_deliveries SET status='SENDING', updated_at=now(), "
                    "discord_nonce=COALESCE(:nonce, discord_nonce) "
                    "WHERE id=:id AND guild_id=:guild_id AND status='CLAIMED' "
                    "AND lease_token=:token "
                    "AND leased_until IS NOT NULL AND leased_until > :now"
                ),
                {
                    "id": delivery_id,
                    "guild_id": guild_id,
                    "token": lease_token,
                    "now": now,
                    "nonce": discord_nonce,
                },
            )
        return cast(CursorResult[Any], result).rowcount == 1

    async def finalize_delivery(
        self,
        delivery_id: UUID,
        guild_id: int,
        lease_token: UUID,
        *,
        status: str,
        discord_message_id: int | None = None,
        discord_nonce: str | None = None,
        content_snapshot: dict[str, object] | None = None,
        last_error: str | None = None,
    ) -> bool:
        """Resolve a CLAIMED/SENDING/UNKNOWN delivery, fenced by
        ``lease_token`` -- deliberately NOT additionally fenced by
        ``leased_until`` freshness.
        Design rationale (external review, second remediation pass): once
        :meth:`mark_delivery_sending` has succeeded, the external Discord
        mutation may already be irrevocably in flight or committed; the
        lease's nominal time budget says nothing about how long Discord's
        API actually takes to respond. Adding a freshness check here would
        let a worker whose send genuinely succeeded, but arrived a moment
        after its own lease's nominal expiry, lose the ability to record
        that outcome -- and since ``SENDING`` rows are never reclaimed by
        :meth:`claim_next_delivery`, that would strand the delivery
        permanently rather than merely delay it. Token identity is the
        correct fence for an outcome report: it proves this is the same
        worker that made the mutation, which is the only thing that still
        matters once the mutation may have already happened. Recovery from a
        worker that legitimately crashed and never calls this at all is a
        distinct concern, handled by the stalled-``SENDING`` reconciliation
        sweep (:meth:`claim_stalled_sending_for_reconciliation`) feeding
        ``did.campaigns.delivery_reconciliation``, not by this method. Also
        accepts an ``UNKNOWN``-status row: this is the SAME fenced call a
        reconciliation worker uses to resolve a delivery to SENT/FAILED/
        INTERVENTION_REQUIRED after claiming it via
        :meth:`claim_unknown_deliveries_for_reconciliation`. A worker that
        lost its lease to another worker's reclaim (only possible pre-
        ``SENDING`` or, for reconciliation, pre-claim of the ``UNKNOWN``
        row) is already excluded by the respective claim method's own
        fencing. Always releases the lease on success."""
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await session.execute(
                text(
                    "UPDATE message_deliveries SET status=:status, "
                    "discord_message_id=COALESCE(:message_id, discord_message_id), "
                    "discord_nonce=COALESCE(:nonce, discord_nonce), "
                    "content_snapshot=COALESCE(CAST(:snapshot AS JSONB), content_snapshot), "
                    "last_error=:last_error, "
                    "lease_owner=NULL, lease_token=NULL, leased_until=NULL, updated_at=now() "
                    "WHERE id=:id AND guild_id=:guild_id "
                    "AND status IN ('CLAIMED','SENDING','UNKNOWN') "
                    "AND lease_token=:token"
                ),
                {
                    "id": delivery_id,
                    "guild_id": guild_id,
                    "token": lease_token,
                    "status": status,
                    "message_id": discord_message_id,
                    "nonce": discord_nonce,
                    "snapshot": (
                        _to_json(content_snapshot) if content_snapshot is not None else None
                    ),
                    "last_error": last_error,
                },
            )
        return cast(CursorResult[Any], result).rowcount == 1

    async def claim_stalled_sending_for_reconciliation(
        self,
        guild_id: int,
        *,
        now: datetime,
        lease_owner: str,
        stall_after_seconds: float = 120.0,
        lease_seconds: float = 30.0,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Atomically claim ``SENDING`` deliveries stuck well past any
        realistic Discord round-trip time -- the recovery path for a worker
        that crashed (or lost its response) after :meth:`mark_delivery_sending`
        but before :meth:`finalize_delivery`, i.e. exactly the UNKNOWN_OUTCOME
        case ``did.campaigns.delivery_reconciliation`` decides on.

        ``stall_after_seconds`` (default 120s) is deliberately much larger
        than the normal claim ``lease_seconds`` (default 30s): a send that is
        merely slow (Discord API latency) must be left alone so its original
        worker can still call :meth:`finalize_delivery` -- see that method's
        docstring for why finalize is token-fenced, not time-fenced. Only a
        delivery whose ``updated_at`` (set exactly when it entered
        ``SENDING``) is older than this much longer stall bound is treated as
        abandoned. Reissues a fresh ``lease_token``/``leased_until`` so the
        reconciliation worker's own :meth:`finalize_delivery` call is
        correctly fenced; the original worker's now-superseded token can no
        longer finalize (a safe no-op, not a duplicate send -- if that worker
        is in fact still alive it will observe the failed finalize and must
        not retry with a fresh nonce, only escalate).
        """
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "WITH candidate AS (SELECT id, updated_at AS original_updated_at "
                            "FROM message_deliveries "
                            "WHERE guild_id=:guild_id AND status='SENDING' "
                            "AND updated_at < CAST(:now AS timestamptz) "
                            "- (:stall_seconds * interval '1 second') "
                            "ORDER BY updated_at LIMIT :limit FOR UPDATE SKIP LOCKED) "
                            "UPDATE message_deliveries AS d SET "
                            "lease_owner=:owner, lease_token=:token, "
                            "leased_until=CAST(:now AS timestamptz) "
                            "+ (:lease_seconds * interval '1 second'), "
                            "updated_at=now() "
                            "FROM candidate WHERE d.id=candidate.id "
                            "RETURNING d.id, d.campaign_id, d.occurrence_id, d.target_id, "
                            "d.language_profile_id, d.delivery_key, d.discord_channel_id, "
                            "d.discord_nonce, d.content_snapshot, d.allowed_mentions_snapshot, "
                            "d.attempt_count, d.lease_token, "
                            "candidate.original_updated_at AS attempted_at"
                        ),
                        {
                            "guild_id": guild_id,
                            "now": now,
                            "stall_seconds": stall_after_seconds,
                            "owner": lease_owner,
                            "token": uuid4(),
                            "lease_seconds": lease_seconds,
                            "limit": limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def claim_unknown_deliveries_for_reconciliation(
        self,
        guild_id: int,
        *,
        now: datetime,
        lease_owner: str,
        lease_seconds: float = 30.0,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Atomically claim ``UNKNOWN`` deliveries -- the ordinary
        UNKNOWN_OUTCOME reconciliation path: the original worker itself
        caught an ambiguous send exception, already finalized the delivery
        to ``UNKNOWN`` (releasing its own lease in the same call -- see
        :meth:`finalize_delivery`), and a reconciliation pass now decides,
        via ``did.campaigns.delivery_reconciliation``, whether a same-nonce
        retry is still safe or the delivery must go to
        ``INTERVENTION_REQUIRED``. Distinct from
        :meth:`claim_stalled_sending_for_reconciliation`, which recovers a
        delivery whose worker crashed before it could even reach that
        finalize call -- both feed the same
        did.campaigns.delivery_worker.reconcile_one_stalled_delivery entry
        point. No stall-time requirement here: a released UNKNOWN lease has
        no live worker to race with.
        """
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "WITH candidate AS (SELECT id, updated_at AS original_updated_at "
                            "FROM message_deliveries "
                            "WHERE guild_id=:guild_id AND status='UNKNOWN' "
                            "AND (leased_until IS NULL "
                            "OR leased_until < CAST(:now AS timestamptz)) "
                            "ORDER BY updated_at LIMIT :limit FOR UPDATE SKIP LOCKED) "
                            "UPDATE message_deliveries AS d SET "
                            "lease_owner=:owner, lease_token=:token, "
                            "leased_until=CAST(:now AS timestamptz) "
                            "+ (:lease_seconds * interval '1 second'), "
                            "updated_at=now() "
                            "FROM candidate WHERE d.id=candidate.id "
                            "RETURNING d.id, d.campaign_id, d.occurrence_id, d.target_id, "
                            "d.language_profile_id, d.delivery_key, d.discord_channel_id, "
                            "d.discord_nonce, d.content_snapshot, d.allowed_mentions_snapshot, "
                            "d.attempt_count, d.lease_token, "
                            "candidate.original_updated_at AS attempted_at"
                        ),
                        {
                            "guild_id": guild_id,
                            "now": now,
                            "owner": lease_owner,
                            "token": uuid4(),
                            "lease_seconds": lease_seconds,
                            "limit": limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def list_approved_variants(
        self, owner_discord_user_id: int, campaign_id: UUID
    ) -> dict[str, dict[str, Any]]:
        """Keyed by ``target_language_code`` -- exactly the shape
        ``did.campaigns.approved_variants.resolve_variant_for_delivery``
        expects (WP11/WP12: one approved-variant read per campaign, reused
        for every target language a fan-out considers)."""
        async with tenant_transaction(
            self._factory, UserContext(user_id=owner_discord_user_id)
        ) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM message_approved_variants WHERE campaign_id=:campaign_id"
                        ),
                        {"campaign_id": campaign_id},
                    )
                )
                .mappings()
                .all()
            )
        return {str(row["target_language_code"]): dict(row) for row in rows}

    async def upsert_approved_variant(self, variant: ApprovedVariant) -> None:
        """Approving a variant for (campaign_id, target_language_code)
        replaces any prior approval for that same pair -- there is only ever
        one current approval per language, never a history of stale ones
        left behind to be accidentally reused."""
        async with tenant_transaction(
            self._factory, UserContext(user_id=variant.owner_discord_user_id)
        ) as session:
            await session.execute(
                text(
                    "INSERT INTO message_approved_variants "
                    "(id, owner_discord_user_id, campaign_id, target_language_code, "
                    "source_fingerprint, localized_message_model, approved_by_discord_user_id) "
                    "VALUES (:id, :owner, :campaign_id, :language, :fingerprint, "
                    "CAST(:model AS JSONB), :approved_by) "
                    "ON CONFLICT (campaign_id, target_language_code) DO UPDATE SET "
                    "source_fingerprint=EXCLUDED.source_fingerprint, "
                    "localized_message_model=EXCLUDED.localized_message_model, "
                    "approved_by_discord_user_id=EXCLUDED.approved_by_discord_user_id, "
                    "approved_at=now(), updated_at=now()"
                ),
                {
                    "id": variant.id,
                    "owner": variant.owner_discord_user_id,
                    "campaign_id": variant.campaign_id,
                    "language": variant.target_language_code,
                    "fingerprint": variant.source_fingerprint,
                    "model": _to_json(variant.localized_message_model),
                    "approved_by": variant.approved_by_discord_user_id,
                },
            )

    async def create_glossary_entry(self, entry: GlossaryEntry) -> None:
        """GUILD-scoped entries need both GUCs set (the row's RLS policy
        checks guild_id under app.current_guild_id()), so this always opens
        under a TenantContext carrying the entry's own owner as user_id --
        that also satisfies the owner-only policy branch for
        GLOBAL_USER/CAMPAIGN entries, which never touches guild_id at all.
        A entry with no natural guild dimension (GLOBAL_USER/CAMPAIGN) still
        needs a positive guild_id to open a TenantContext; callers without a
        real Guild in scope should use guild_id=entry's own campaign's
        eventual target Guild once known, or any positive placeholder is
        rejected as unsafe -- so those two scopes are created without a
        Guild dimension by using UserContext instead.
        """
        if entry.scope_kind is GlossaryScope.GUILD:
            assert entry.guild_id is not None
            context: TenantContext | UserContext = TenantContext(
                entry.guild_id, user_id=entry.owner_discord_user_id
            )
        else:
            context = UserContext(user_id=entry.owner_discord_user_id)
        async with tenant_transaction(self._factory, context) as session:
            await session.execute(
                text(
                    "INSERT INTO message_glossary_entries "
                    "(id, owner_discord_user_id, scope_kind, campaign_id, guild_id, "
                    "source_term, target_language_code, behavior, forced_translation, "
                    "match_mode) "
                    "VALUES (:id, :owner, :scope, :campaign_id, :guild_id, :term, "
                    ":language, :behavior, :forced, :match_mode)"
                ),
                {
                    "id": entry.id,
                    "owner": entry.owner_discord_user_id,
                    "scope": entry.scope_kind.value,
                    "campaign_id": entry.campaign_id,
                    "guild_id": entry.guild_id,
                    "term": entry.source_term,
                    "language": entry.target_language_code,
                    "behavior": entry.behavior.value,
                    "forced": entry.forced_translation,
                    "match_mode": entry.match_mode.value,
                },
            )

    async def list_applicable_glossary_entries(
        self, *, owner_discord_user_id: int, guild_id: int
    ) -> list[dict[str, Any]]:
        """Every GLOBAL_USER/CAMPAIGN entry owned by ``owner_discord_user_id``
        plus every GUILD entry for ``guild_id`` -- exactly the set
        did.campaigns.glossary.resolve_applicable_entries() needs, visible
        in one query because TenantContext sets both RLS GUCs together."""
        context = TenantContext(guild_id, user_id=owner_discord_user_id)
        async with tenant_transaction(self._factory, context) as session:
            rows = (
                (await session.execute(text("SELECT * FROM message_glossary_entries")))
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def create_trigger(self, trigger: CampaignTrigger) -> None:
        """Raises :class:`ConditionEvaluationError` for a malformed/disallowed/
        oversized condition AST -- validated before any INSERT is attempted,
        so an invalid AST can never reach durable state through this path."""
        validate_condition_ast(trigger.condition_ast)
        async with tenant_transaction(
            self._factory, UserContext(user_id=trigger.owner_discord_user_id)
        ) as session:
            await session.execute(
                text(
                    "INSERT INTO message_campaign_triggers "
                    "(id, owner_discord_user_id, campaign_id, event_type, "
                    "condition_ast, max_causation_depth, version, requires_message_content) "
                    "VALUES (:id, :owner, :campaign_id, :event_type, "
                    "CAST(:condition AS JSONB), :depth, :version, :requires_message_content)"
                ),
                {
                    "id": trigger.id,
                    "owner": trigger.owner_discord_user_id,
                    "campaign_id": trigger.campaign_id,
                    "event_type": trigger.event_type,
                    "condition": _to_json(trigger.condition_ast),
                    "depth": trigger.max_causation_depth,
                    "version": trigger.version,
                    "requires_message_content": trigger.requires_message_content,
                },
            )

    async def get_trigger(
        self, owner_discord_user_id: int, trigger_id: UUID
    ) -> dict[str, Any] | None:
        """RLS-scoped by owner -- returns None for a trigger that does not
        exist OR belongs to a different owner, indistinguishably (never
        discloses which). Used by the create-time target/source
        authorization service (REQ-MSG target/source authority) to prove a
        trigger source binding is being attached to a trigger the calling
        owner actually owns before any Guild-scoped row is persisted."""
        async with tenant_transaction(
            self._factory, UserContext(user_id=owner_discord_user_id)
        ) as session:
            row = (
                (
                    await session.execute(
                        text("SELECT * FROM message_campaign_triggers WHERE id=:id"),
                        {"id": trigger_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    async def list_triggers_for_campaign(
        self, owner_discord_user_id: int, campaign_id: UUID
    ) -> list[dict[str, Any]]:
        """RLS-scoped by owner, same never-discloses-cross-owner posture as
        :meth:`get_trigger`. Used by the simulation endpoint to surface
        every MESSAGE_CONTENT-dependent trigger's blocking state (REQ-MSG-020/
        REQ-MSG-022) without exposing triggers belonging to another owner."""
        async with tenant_transaction(
            self._factory, UserContext(user_id=owner_discord_user_id)
        ) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM message_campaign_triggers "
                            "WHERE campaign_id=:campaign_id ORDER BY id"
                        ),
                        {"campaign_id": campaign_id},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def create_trigger_source(self, binding: TriggerSourceBinding) -> None:
        async with tenant_transaction(self._factory, TenantContext(binding.guild_id)) as session:
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

    async def list_candidate_triggers_for_event(
        self,
        admin_factory: async_sessionmaker[Any],
        *,
        guild_id: int,
        event_type: str,
    ) -> list[dict[str, Any]]:
        """System/runtime-only read: every trigger bound to ``guild_id``
        whose own ``event_type`` matches. Triggers are owner-scoped, not
        Guild-scoped, but their source bindings are Guild-scoped -- there is
        no single RLS context that can see both at once, so (mirroring
        :meth:`list_targets_for_campaign`'s identical system-process
        exception) this runs on the admin session factory, joining the two
        directly rather than trusting a caller-supplied owner id. The real
        event_type match still happens again inside
        did.campaigns.causality.should_trigger via
        TriggerEvaluationContext.event_type -- this is a coarse pre-filter
        to avoid loading every trigger bound to a Guild for every event,
        never the sole authorization gate."""
        async with admin_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT DISTINCT t.* FROM message_campaign_triggers t "
                            "JOIN message_campaign_trigger_sources s "
                            "ON s.trigger_id = t.id "
                            "WHERE s.guild_id = :guild_id AND t.event_type = :event_type"
                        ),
                        {"guild_id": guild_id, "event_type": event_type},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

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
