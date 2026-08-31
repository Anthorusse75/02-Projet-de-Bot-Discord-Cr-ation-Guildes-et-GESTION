"""PostgreSQL integration tests for the Stage 09 campaign engine (WP1/WP2).

Proves, against a real database (not app-level filtering): owner RLS
isolation between two Control-Plane owners, Guild RLS isolation between two
tenants, composite-FK rejection of a cross-Guild delivery target reference,
occurrence/delivery uniqueness as the source of truth for idempotency, and
atomic FOR UPDATE SKIP LOCKED claim concurrency for due schedules.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.campaigns.scheduling import evaluate_recurring
from did.domain.campaigns import CampaignSchedule as DomainSchedule
from did.domain.campaigns import CampaignTarget as DomainTarget
from did.domain.campaigns import (
    GlossaryBehavior,
    GlossaryEntry,
    GlossaryScope,
    LifecycleStatus,
    MessageCampaign,
    MessageDelivery,
    MessageOccurrence,
    OccurrenceSource,
    PublicationMode,
    ScheduleKind,
)
from did.domain.campaigns import TargetKind as DomainTargetKind
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.database import create_database_engine, tenant_transaction
from did.tenancy import TenantContext

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 880000901
GUILD_B = 880000902
OWNER_A = 880000911
OWNER_B = 880000912

CLEANUP_STATEMENTS = (
    "DELETE FROM message_deliveries WHERE guild_id IN (:ga,:gb)",
    "DELETE FROM message_campaign_trigger_consumptions WHERE guild_id IN (:ga,:gb)",
    "DELETE FROM message_campaign_trigger_sources WHERE guild_id IN (:ga,:gb)",
    "DELETE FROM message_campaign_targets WHERE guild_id IN (:ga,:gb)",
    "DELETE FROM message_occurrences WHERE owner_discord_user_id IN (:oa,:ob)",
    "DELETE FROM message_campaign_triggers WHERE owner_discord_user_id IN (:oa,:ob)",
    "DELETE FROM message_campaign_schedules WHERE owner_discord_user_id IN (:oa,:ob)",
    "DELETE FROM message_glossary_entries WHERE owner_discord_user_id IN (:oa,:ob)",
    "DELETE FROM message_approved_variants WHERE owner_discord_user_id IN (:oa,:ob)",
    "DELETE FROM message_campaigns WHERE owner_discord_user_id IN (:oa,:ob)",
)
CLEANUP_PARAMS = {"ga": GUILD_A, "gb": GUILD_B, "oa": OWNER_A, "ob": OWNER_B}


async def _insert_installation(connection: AsyncConnection, guild_id: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO guild_installations "
            "(guild_id,name,owner_id,installation_status) "
            "VALUES (:guild_id,:name,:owner_id,'ACTIVE') "
            "ON CONFLICT (guild_id) DO UPDATE SET name=EXCLUDED.name"
        ),
        {"guild_id": guild_id, "name": f"Stage 09 {guild_id}", "owner_id": OWNER_A},
    )


async def _insert_user(connection: AsyncConnection, user_id: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO users (discord_user_id, username) VALUES (:id, :name) "
            "ON CONFLICT (discord_user_id) DO NOTHING"
        ),
        {"id": user_id, "name": f"user-{user_id}"},
    )


@pytest.fixture
async def campaigns_context() -> AsyncIterator[CampaignsRepository]:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=3)
    app_engine = create_database_engine(APP_URL, pool_size=3)
    try:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id IN (:ga,:gb)"),
                CLEANUP_PARAMS,
            )
            await _insert_user(connection, OWNER_A)
            await _insert_user(connection, OWNER_B)
            await _insert_installation(connection, GUILD_A)
            await _insert_installation(connection, GUILD_B)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        yield CampaignsRepository(factory)
    finally:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id IN (:ga,:gb)"),
                CLEANUP_PARAMS,
            )
        await app_engine.dispose()
        await admin_engine.dispose()


def _campaign(
    owner: int, *, lifecycle_status: LifecycleStatus = LifecycleStatus.DRAFT
) -> MessageCampaign:
    return MessageCampaign(
        id=uuid4(),
        owner_discord_user_id=owner,
        logical_campaign_key=f"key-{uuid4().hex[:8]}",
        name="Launch",
        source_language_code="en",
        message_model={"content": "hello"},
        allowed_mentions_policy={"parse": []},
        publication_mode=PublicationMode.IMMEDIATE,
        lifecycle_status=lifecycle_status,
    )


@pytest.mark.asyncio
class TestOwnerRlsIsolation:
    async def test_owner_cannot_list_another_owners_campaigns(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign_a = _campaign(OWNER_A)
        campaign_b = _campaign(OWNER_B)
        await repo.create_campaign(campaign_a)
        await repo.create_campaign(campaign_b)

        owner_a_view = await repo.list_campaigns(OWNER_A)
        owner_b_view = await repo.list_campaigns(OWNER_B)

        assert {row["id"] for row in owner_a_view} == {campaign_a.id}
        assert {row["id"] for row in owner_b_view} == {campaign_b.id}

    async def test_owner_cannot_fetch_another_owners_campaign_by_id(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign_b = _campaign(OWNER_B)
        await repo.create_campaign(campaign_b)

        assert await repo.get_campaign(OWNER_A, campaign_b.id) is None
        assert await repo.get_campaign(OWNER_B, campaign_b.id) is not None


@pytest.mark.asyncio
class TestGuildRlsIsolation:
    async def test_guild_session_never_sees_other_guilds_deliveries(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign(OWNER_A)
        await repo.create_campaign(campaign)
        occurrence = MessageOccurrence(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            occurrence_key="occ-1",
            occurrence_source=OccurrenceSource.EVENT,
            source_event_id=uuid4(),
        )
        assert await repo.create_occurrence(OWNER_A, occurrence)

        target_a = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.CHANNEL,
            discord_channel_id=111,
        )
        target_b = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_B,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.CHANNEL,
            discord_channel_id=222,
        )
        await repo.create_target(target_a)
        await repo.create_target(target_b)

        delivery_a = MessageDelivery(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            occurrence_id=occurrence.id,
            target_id=target_a.id,
            delivery_key="dk-a",
            discord_channel_id=111,
            allowed_mentions_snapshot={"parse": []},
        )
        delivery_b = MessageDelivery(
            id=uuid4(),
            guild_id=GUILD_B,
            campaign_id=campaign.id,
            occurrence_id=occurrence.id,
            target_id=target_b.id,
            delivery_key="dk-b",
            discord_channel_id=222,
            allowed_mentions_snapshot={"parse": []},
        )
        assert await repo.create_delivery(delivery_a)
        assert await repo.create_delivery(delivery_b)

        engine = create_database_engine(APP_URL, pool_size=1)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            query = text("SELECT guild_id FROM message_deliveries")
            # No guild_id filter in the query at all -- RLS, not app
            # filtering, must be what limits the result set.
            async with tenant_transaction(factory, TenantContext(GUILD_A)) as session:
                rows = (await session.execute(query)).all()
            assert {r[0] for r in rows} == {GUILD_A}

            async with tenant_transaction(factory, TenantContext(GUILD_B)) as session:
                rows = (await session.execute(query)).all()
            assert {r[0] for r in rows} == {GUILD_B}
        finally:
            await engine.dispose()


@pytest.mark.asyncio
class TestCompositeForeignKeyRejection:
    async def test_delivery_cannot_reference_a_target_from_another_guild(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign(OWNER_A)
        await repo.create_campaign(campaign)
        occurrence = MessageOccurrence(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            occurrence_key="occ-fk",
            occurrence_source=OccurrenceSource.EVENT,
            source_event_id=uuid4(),
        )
        await repo.create_occurrence(OWNER_A, occurrence)
        target_b = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_B,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.CHANNEL,
            discord_channel_id=333,
        )
        await repo.create_target(target_b)

        engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO message_deliveries "
                            "(id, guild_id, campaign_id, occurrence_id, target_id, "
                            "delivery_key, discord_channel_id, allowed_mentions_snapshot) "
                            "VALUES (:id, :guild_id, :campaign_id, :occurrence_id, :target_id, "
                            "'dk-cross', 333, CAST('{}' AS JSONB))"
                        ),
                        {
                            "id": uuid4(),
                            "guild_id": GUILD_A,  # delivery claims GUILD_A...
                            "campaign_id": campaign.id,
                            "occurrence_id": occurrence.id,
                            "target_id": target_b.id,  # ...but target belongs to GUILD_B
                        },
                    )
        finally:
            await engine.dispose()


@pytest.mark.asyncio
class TestOccurrenceAndDeliveryUniqueness:
    async def test_duplicate_occurrence_key_is_a_noop_not_an_error(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign(OWNER_A)
        await repo.create_campaign(campaign)
        occurrence = MessageOccurrence(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            occurrence_key="dup-key",
            occurrence_source=OccurrenceSource.EVENT,
            source_event_id=uuid4(),
        )
        first = await repo.create_occurrence(OWNER_A, occurrence)
        duplicate = MessageOccurrence(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            occurrence_key="dup-key",
            occurrence_source=OccurrenceSource.EVENT,
            source_event_id=uuid4(),
        )
        second = await repo.create_occurrence(OWNER_A, duplicate)
        assert first is True
        assert second is False

    async def test_duplicate_delivery_key_within_guild_is_a_noop(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign(OWNER_A)
        await repo.create_campaign(campaign)
        occurrence = MessageOccurrence(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            occurrence_key="occ-dk",
            occurrence_source=OccurrenceSource.EVENT,
            source_event_id=uuid4(),
        )
        await repo.create_occurrence(OWNER_A, occurrence)
        target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.CHANNEL,
            discord_channel_id=444,
        )
        await repo.create_target(target)

        def _delivery() -> MessageDelivery:
            return MessageDelivery(
                id=uuid4(),
                guild_id=GUILD_A,
                campaign_id=campaign.id,
                occurrence_id=occurrence.id,
                target_id=target.id,
                delivery_key="same-key",
                discord_channel_id=444,
                allowed_mentions_snapshot={"parse": []},
            )

        assert await repo.create_delivery(_delivery()) is True
        assert await repo.create_delivery(_delivery()) is False


@pytest.mark.asyncio
class TestScheduleClaimConcurrency:
    async def test_two_concurrent_claims_only_one_wins(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign(OWNER_A, lifecycle_status=LifecycleStatus.ACTIVE_RUNNING)
        await repo.create_campaign(campaign)
        schedule = DomainSchedule(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            schedule_kind=ScheduleKind.ONE_SHOT,
            fire_at=datetime.now(UTC) - timedelta(minutes=5),
            next_fire_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        await repo.create_schedule(schedule)

        admin_engine = create_database_engine(ADMIN_URL, pool_size=4)
        try:
            admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
            results = await asyncio.gather(
                repo.claim_due_schedules(
                    admin_factory, now=datetime.now(UTC), lease_owner="worker-1", limit=5
                ),
                repo.claim_due_schedules(
                    admin_factory, now=datetime.now(UTC), lease_owner="worker-2", limit=5
                ),
            )
            claimed_ids = [row["id"] for result in results for row in result]
            assert claimed_ids == [schedule.id]
        finally:
            await admin_engine.dispose()

    async def test_paused_campaigns_schedule_is_never_claimed_even_if_due(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """External-review finding: claim_due_schedules previously ignored
        the owning campaign's lifecycle_status entirely."""
        repo = campaigns_context
        campaign = _campaign(OWNER_A, lifecycle_status=LifecycleStatus.PAUSED)
        await repo.create_campaign(campaign)
        schedule = DomainSchedule(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            schedule_kind=ScheduleKind.ONE_SHOT,
            fire_at=datetime.now(UTC) - timedelta(minutes=5),
            next_fire_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        await repo.create_schedule(schedule)

        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
            claimed = await repo.claim_due_schedules(
                admin_factory, now=datetime.now(UTC), lease_owner="worker-1", limit=5
            )
            assert claimed == []
        finally:
            await admin_engine.dispose()

    async def test_finalize_schedule_claim_fenced_by_lease_token(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign(OWNER_A, lifecycle_status=LifecycleStatus.ACTIVE_RUNNING)
        await repo.create_campaign(campaign)
        schedule = DomainSchedule(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            schedule_kind=ScheduleKind.ONE_SHOT,
            fire_at=datetime.now(UTC) - timedelta(minutes=5),
            next_fire_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        await repo.create_schedule(schedule)

        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
            claim_now = datetime.now(UTC)
            [claimed] = await repo.claim_due_schedules(
                admin_factory, now=claim_now, lease_owner="worker-1", limit=5
            )
            real_token = claimed["lease_token"]

            # A stale/wrong token can never finalize -- safe no-op.
            wrong_token_result = await repo.finalize_schedule_claim(
                admin_factory,
                schedule.id,
                uuid4(),
                now=claim_now,
                new_last_cursor_local=None,
                new_next_fire_at=None,
            )
            assert wrong_token_result is False

            # The rightful lease holder finalizes successfully.
            correct_result = await repo.finalize_schedule_claim(
                admin_factory,
                schedule.id,
                real_token,
                now=claim_now,
                new_last_cursor_local=None,
                new_next_fire_at=None,
            )
            assert correct_result is True

            # Having already finalized (lease released), a second finalize
            # with the same now-stale token is a no-op, not a double-apply.
            replay_result = await repo.finalize_schedule_claim(
                admin_factory,
                schedule.id,
                real_token,
                now=claim_now,
                new_last_cursor_local=None,
                new_next_fire_at=None,
            )
            assert replay_result is False
        finally:
            await admin_engine.dispose()

    async def test_finalize_schedule_claim_rejects_an_already_expired_lease(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """External-review finding (second remediation pass): token-matching
        alone let a worker that overran its own lease window still commit,
        even with no competing claimant. finalize must independently prove
        the lease had not yet expired at commit time."""
        repo = campaigns_context
        campaign = _campaign(OWNER_A, lifecycle_status=LifecycleStatus.ACTIVE_RUNNING)
        await repo.create_campaign(campaign)
        schedule = DomainSchedule(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            schedule_kind=ScheduleKind.ONE_SHOT,
            fire_at=datetime.now(UTC) - timedelta(minutes=5),
            next_fire_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        await repo.create_schedule(schedule)

        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
            claim_now = datetime.now(UTC)
            [claimed] = await repo.claim_due_schedules(
                admin_factory,
                now=claim_now,
                lease_owner="worker-1",
                lease_seconds=0.01,
                limit=5,
            )
            await asyncio.sleep(0.05)

            stale_result = await repo.finalize_schedule_claim(
                admin_factory,
                schedule.id,
                claimed["lease_token"],
                now=datetime.now(UTC),
                new_last_cursor_local=None,
                new_next_fire_at=datetime.now(UTC) + timedelta(days=1),
            )
            assert stale_result is False

            # A second worker can now legitimately reclaim and finalize.
            [reclaimed] = await repo.claim_due_schedules(
                admin_factory, now=datetime.now(UTC), lease_owner="worker-2", limit=5
            )
            assert reclaimed["lease_token"] != claimed["lease_token"]
            fresh_result = await repo.finalize_schedule_claim(
                admin_factory,
                schedule.id,
                reclaimed["lease_token"],
                now=datetime.now(UTC),
                new_last_cursor_local=None,
                new_next_fire_at=None,
            )
            assert fresh_result is True
        finally:
            await admin_engine.dispose()

    async def test_finalize_schedule_claim_rejects_a_campaign_paused_after_claim(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """External-review race scenario: campaign paused/cancelled after
        the schedule claim was taken but before finalize commits -- finalize
        must recheck lifecycle eligibility at commit time, not just at claim
        time."""
        repo = campaigns_context
        campaign = _campaign(OWNER_A, lifecycle_status=LifecycleStatus.ACTIVE_RUNNING)
        await repo.create_campaign(campaign)
        schedule = DomainSchedule(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            schedule_kind=ScheduleKind.ONE_SHOT,
            fire_at=datetime.now(UTC) - timedelta(minutes=5),
            next_fire_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        await repo.create_schedule(schedule)

        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
            claim_now = datetime.now(UTC)
            [claimed] = await repo.claim_due_schedules(
                admin_factory, now=claim_now, lease_owner="worker-1", limit=5
            )

            async with admin_factory() as session, session.begin():
                await session.execute(
                    text("UPDATE message_campaigns SET lifecycle_status='PAUSED' WHERE id=:id"),
                    {"id": campaign.id},
                )

            result = await repo.finalize_schedule_claim(
                admin_factory,
                schedule.id,
                claimed["lease_token"],
                now=claim_now,
                new_last_cursor_local=None,
                new_next_fire_at=datetime.now(UTC) + timedelta(days=1),
            )
            assert result is False
        finally:
            await admin_engine.dispose()


async def _setup_pending_delivery(
    repo: CampaignsRepository, *, guild_id: int, owner: int
) -> MessageDelivery:
    campaign = _campaign(owner)
    await repo.create_campaign(campaign)
    occurrence = MessageOccurrence(
        id=uuid4(),
        owner_discord_user_id=owner,
        campaign_id=campaign.id,
        occurrence_key=f"occ-{uuid4().hex[:8]}",
        occurrence_source=OccurrenceSource.EVENT,
        source_event_id=uuid4(),
    )
    await repo.create_occurrence(owner, occurrence)
    target = DomainTarget(
        id=uuid4(),
        guild_id=guild_id,
        campaign_id=campaign.id,
        target_kind=DomainTargetKind.CHANNEL,
        discord_channel_id=999,
    )
    await repo.create_target(target)
    delivery = MessageDelivery(
        id=uuid4(),
        guild_id=guild_id,
        campaign_id=campaign.id,
        occurrence_id=occurrence.id,
        target_id=target.id,
        delivery_key=f"dk-{uuid4().hex[:8]}",
        discord_channel_id=999,
        allowed_mentions_snapshot={"parse": []},
    )
    await repo.create_delivery(delivery)
    return delivery


@pytest.mark.asyncio
class TestDeliveryLeaseFencing:
    async def test_claim_sets_lease_and_returns_the_token(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        delivery = await _setup_pending_delivery(repo, guild_id=GUILD_A, owner=OWNER_A)
        [claimed] = await repo.claim_next_delivery(GUILD_A, lease_owner="worker-1")
        assert claimed["id"] == delivery.id
        assert claimed["lease_token"] is not None

    async def test_finalize_with_wrong_token_is_a_safe_noop(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        delivery = await _setup_pending_delivery(repo, guild_id=GUILD_A, owner=OWNER_A)
        await repo.claim_next_delivery(GUILD_A, lease_owner="worker-1")

        result = await repo.finalize_delivery(
            delivery.id, GUILD_A, uuid4(), status="SENT", discord_message_id=123456789
        )
        assert result is False

    async def test_finalize_with_correct_token_succeeds_exactly_once(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        delivery = await _setup_pending_delivery(repo, guild_id=GUILD_A, owner=OWNER_A)
        [claimed] = await repo.claim_next_delivery(GUILD_A, lease_owner="worker-1")
        token = claimed["lease_token"]

        assert (
            await repo.mark_delivery_sending(delivery.id, GUILD_A, token, now=datetime.now(UTC))
            is True
        )
        assert (
            await repo.finalize_delivery(
                delivery.id, GUILD_A, token, status="SENT", discord_message_id=123456789
            )
            is True
        )
        # Lease already released by the successful finalize -- replaying
        # with the same token must not be able to finalize again.
        replay = await repo.finalize_delivery(
            delivery.id, GUILD_A, token, status="SENT", discord_message_id=999999999
        )
        assert replay is False

    async def test_expired_claimed_lease_becomes_reclaimable(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """A worker that claimed but crashed before ever calling
        mark_delivery_sending must not strand the delivery -- a second
        claim_next_delivery with a near-zero lease duration must be able to
        reclaim it once the lease has expired."""
        repo = campaigns_context
        delivery = await _setup_pending_delivery(repo, guild_id=GUILD_A, owner=OWNER_A)
        [first_claim] = await repo.claim_next_delivery(
            GUILD_A, lease_owner="worker-1", lease_seconds=0.01
        )
        await asyncio.sleep(0.05)

        [second_claim] = await repo.claim_next_delivery(GUILD_A, lease_owner="worker-2")
        assert second_claim["id"] == delivery.id
        assert second_claim["lease_token"] != first_claim["lease_token"]

        # The first worker's stale token can no longer finalize.
        stale_result = await repo.finalize_delivery(
            delivery.id,
            GUILD_A,
            first_claim["lease_token"],
            status="SENT",
            discord_message_id=123456789,
        )
        assert stale_result is False

    async def test_expired_claimed_lease_cannot_begin_sending(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """External-review finding (second remediation pass): CLAIMED ->
        SENDING requires a currently valid lease -- a worker that overran
        its claim window must not be allowed to start the irreversible
        external mutation on a lease that had already expired, even before
        anyone else has reclaimed it."""
        repo = campaigns_context
        delivery = await _setup_pending_delivery(repo, guild_id=GUILD_A, owner=OWNER_A)
        [claimed] = await repo.claim_next_delivery(
            GUILD_A, lease_owner="worker-1", lease_seconds=0.01
        )
        await asyncio.sleep(0.05)

        sending_ok = await repo.mark_delivery_sending(
            delivery.id, GUILD_A, claimed["lease_token"], now=datetime.now(UTC)
        )
        assert sending_ok is False

        # A second worker can legitimately reclaim and start sending instead.
        [reclaimed] = await repo.claim_next_delivery(GUILD_A, lease_owner="worker-2")
        assert reclaimed["lease_token"] != claimed["lease_token"]
        second_sending_ok = await repo.mark_delivery_sending(
            delivery.id, GUILD_A, reclaimed["lease_token"], now=datetime.now(UTC)
        )
        assert second_sending_ok is True

        # The stale first worker's own attempt, retried after the reclaim,
        # still fails -- it never becomes a duplicate SENDING transition.
        first_retry = await repo.mark_delivery_sending(
            delivery.id, GUILD_A, claimed["lease_token"], now=datetime.now(UTC)
        )
        assert first_retry is False

    async def test_sending_delivery_is_not_reclaimed_by_a_fresh_claim(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """Once mark_delivery_sending succeeds, the delivery must never be
        picked up again by claim_next_delivery -- an ambiguous outcome past
        that point is handled by did.campaigns.delivery_reconciliation, not
        by a blind second claim/second send. Uses a normal (non-expired)
        lease for the SENDING transition itself -- see
        test_expired_claimed_lease_cannot_begin_sending for the separate
        expired-before-SENDING scenario."""
        repo = campaigns_context
        delivery = await _setup_pending_delivery(repo, guild_id=GUILD_A, owner=OWNER_A)
        [claimed] = await repo.claim_next_delivery(GUILD_A, lease_owner="worker-1")
        sending_ok = await repo.mark_delivery_sending(
            delivery.id, GUILD_A, claimed["lease_token"], now=datetime.now(UTC)
        )
        assert sending_ok is True

        still_none = await repo.claim_next_delivery(GUILD_A, lease_owner="worker-2")
        assert still_none == []

    async def test_finalize_after_sending_succeeds_even_if_the_original_lease_would_have_expired(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """Design contract (external review): finalize_delivery is
        token-fenced, not time-fenced, because a legitimately slow Discord
        response must still be recordable by the worker that made the call
        -- see finalize_delivery's docstring."""
        repo = campaigns_context
        delivery = await _setup_pending_delivery(repo, guild_id=GUILD_A, owner=OWNER_A)
        [claimed] = await repo.claim_next_delivery(
            GUILD_A, lease_owner="worker-1", lease_seconds=0.05
        )
        token = claimed["lease_token"]
        sending_ok = await repo.mark_delivery_sending(
            delivery.id, GUILD_A, token, now=datetime.now(UTC)
        )
        assert sending_ok is True

        await asyncio.sleep(0.1)  # simulate a slow Discord round trip past the nominal lease

        finalized = await repo.finalize_delivery(
            delivery.id, GUILD_A, token, status="SENT", discord_message_id=123456789
        )
        assert finalized is True

    async def test_stalled_sending_delivery_is_reclaimable_for_reconciliation(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """A worker that crashed after mark_delivery_sending and never
        finalized must eventually be recoverable via the dedicated stalled-
        SENDING reconciliation claim, not the normal claim_next_delivery
        path (which correctly never touches SENDING rows)."""
        repo = campaigns_context
        delivery = await _setup_pending_delivery(repo, guild_id=GUILD_A, owner=OWNER_A)
        [claimed] = await repo.claim_next_delivery(GUILD_A, lease_owner="worker-1")
        original_token = claimed["lease_token"]
        sending_ok = await repo.mark_delivery_sending(
            delivery.id, GUILD_A, original_token, now=datetime.now(UTC)
        )
        assert sending_ok is True

        # Not stalled yet: too recent to be picked up.
        too_soon = await repo.claim_stalled_sending_for_reconciliation(
            GUILD_A, now=datetime.now(UTC), lease_owner="reconciler-1", stall_after_seconds=60.0
        )
        assert too_soon == []

        [reclaimed] = await repo.claim_stalled_sending_for_reconciliation(
            GUILD_A,
            now=datetime.now(UTC) + timedelta(seconds=120),
            lease_owner="reconciler-1",
            stall_after_seconds=60.0,
        )
        assert reclaimed["id"] == delivery.id
        assert reclaimed["lease_token"] != original_token

        # The reconciliation worker's fresh token can finalize.
        finalized = await repo.finalize_delivery(
            delivery.id,
            GUILD_A,
            reclaimed["lease_token"],
            status="SENT",
            discord_message_id=123456789,
        )
        assert finalized is True

        # The original (crashed) worker's superseded token cannot.
        stale = await repo.finalize_delivery(
            delivery.id, GUILD_A, original_token, status="SENT", discord_message_id=999
        )
        assert stale is False


@pytest.mark.asyncio
class TestCrossOwnerCrossCampaignRelationalIntegrity:
    """External-review CRITICAL finding: composite FKs must prove an owner-
    scoped child belongs to ITS OWNER's real campaign, and that a delivery's
    campaign_id matches both its target's and its occurrence's campaign_id
    -- not just that guild_id/campaign existence checks pass independently.
    """

    async def _two_campaigns(
        self, repo: CampaignsRepository
    ) -> tuple[MessageCampaign, MessageCampaign]:
        campaign_a = _campaign(OWNER_A, lifecycle_status=LifecycleStatus.ACTIVE_RUNNING)
        campaign_b = _campaign(OWNER_B, lifecycle_status=LifecycleStatus.ACTIVE_RUNNING)
        await repo.create_campaign(campaign_a)
        await repo.create_campaign(campaign_b)
        return campaign_a, campaign_b

    async def test_owner_b_schedule_cannot_reference_owner_a_campaign(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign_a, _campaign_b = await self._two_campaigns(repo)

        engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO message_campaign_schedules "
                            "(id, owner_discord_user_id, campaign_id, schedule_kind, "
                            "fire_at) "
                            "VALUES (:id, :owner_b, :campaign_a_id, 'ONE_SHOT', now())"
                        ),
                        {"id": uuid4(), "owner_b": OWNER_B, "campaign_a_id": campaign_a.id},
                    )
        finally:
            await engine.dispose()

    async def test_owner_b_trigger_cannot_reference_owner_a_campaign(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign_a, _campaign_b = await self._two_campaigns(repo)

        engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO message_campaign_triggers "
                            "(id, owner_discord_user_id, campaign_id, event_type) "
                            "VALUES (:id, :owner_b, :campaign_a_id, 'MEMBER_JOIN')"
                        ),
                        {"id": uuid4(), "owner_b": OWNER_B, "campaign_a_id": campaign_a.id},
                    )
        finally:
            await engine.dispose()

    async def test_owner_b_occurrence_cannot_reference_owner_a_campaign(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign_a, _campaign_b = await self._two_campaigns(repo)

        engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO message_occurrences "
                            "(id, owner_discord_user_id, campaign_id, occurrence_key, "
                            "occurrence_source, source_event_id) "
                            "VALUES (:id, :owner_b, :campaign_a_id, 'occ-x', 'EVENT', :evt)"
                        ),
                        {
                            "id": uuid4(),
                            "owner_b": OWNER_B,
                            "campaign_a_id": campaign_a.id,
                            "evt": uuid4(),
                        },
                    )
        finally:
            await engine.dispose()

    async def test_owner_b_approved_variant_cannot_reference_owner_a_campaign(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign_a, _campaign_b = await self._two_campaigns(repo)

        engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO message_approved_variants "
                            "(id, owner_discord_user_id, campaign_id, target_language_code, "
                            "source_fingerprint, localized_message_model, "
                            "approved_by_discord_user_id) "
                            "VALUES (:id, :owner_b, :campaign_a_id, 'fr', :fp, "
                            "CAST('{}' AS JSONB), :owner_b)"
                        ),
                        {
                            "id": uuid4(),
                            "owner_b": OWNER_B,
                            "campaign_a_id": campaign_a.id,
                            "fp": "a" * 64,
                        },
                    )
        finally:
            await engine.dispose()

    async def test_owner_b_glossary_campaign_scope_cannot_reference_owner_a_campaign(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign_a, _campaign_b = await self._two_campaigns(repo)

        engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO message_glossary_entries "
                            "(id, owner_discord_user_id, scope_kind, campaign_id, "
                            "source_term, behavior) "
                            "VALUES (:id, :owner_b, 'CAMPAIGN', :campaign_a_id, 'Widget', "
                            "'DO_NOT_TRANSLATE')"
                        ),
                        {"id": uuid4(), "owner_b": OWNER_B, "campaign_a_id": campaign_a.id},
                    )
        finally:
            await engine.dispose()

    async def test_glossary_global_user_scope_with_null_campaign_is_unaffected(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """The composite FK must not break the legitimate GLOBAL_USER case
        (campaign_id NULL) -- Postgres MATCH SIMPLE bypasses the check when
        any FK column is NULL."""
        repo = campaigns_context
        await repo.create_campaign(_campaign(OWNER_A))

        engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO message_glossary_entries "
                        "(id, owner_discord_user_id, scope_kind, campaign_id, "
                        "source_term, behavior) "
                        "VALUES (:id, :owner_a, 'GLOBAL_USER', NULL, 'Widget', "
                        "'DO_NOT_TRANSLATE')"
                    ),
                    {"id": uuid4(), "owner_a": OWNER_A},
                )
        finally:
            await engine.dispose()

    async def test_delivery_campaign_id_must_match_its_targets_campaign(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """Same Guild, but the delivery claims a DIFFERENT campaign than the
        target it points at -- must be rejected even though guild_id alone
        would have matched under the old (guild_id, target_id)-only FK."""
        repo = campaigns_context
        campaign_a, campaign_b = await self._two_campaigns(repo)

        occurrence_b = MessageOccurrence(
            id=uuid4(),
            owner_discord_user_id=OWNER_B,
            campaign_id=campaign_b.id,
            occurrence_key="occ-b",
            occurrence_source=OccurrenceSource.EVENT,
            source_event_id=uuid4(),
        )
        await repo.create_occurrence(OWNER_B, occurrence_b)

        target_a = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign_a.id,
            target_kind=DomainTargetKind.CHANNEL,
            discord_channel_id=555,
        )
        await repo.create_target(target_a)

        engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            # The delivery claims campaign_b, but target_a actually belongs
            # to campaign_a -- the composite FK must reject this.
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO message_deliveries "
                            "(id, guild_id, campaign_id, occurrence_id, target_id, "
                            "delivery_key, discord_channel_id, allowed_mentions_snapshot) "
                            "VALUES (:id, :guild_id, :wrong_campaign_id, :occurrence_id, "
                            ":target_id, 'dk-mismatch', 555, CAST('{}' AS JSONB))"
                        ),
                        {
                            "id": uuid4(),
                            "guild_id": GUILD_A,
                            "wrong_campaign_id": campaign_b.id,
                            "occurrence_id": occurrence_b.id,
                            "target_id": target_a.id,
                        },
                    )
        finally:
            await engine.dispose()

    async def test_delivery_occurrence_must_belong_to_the_same_campaign(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign_a, campaign_b = await self._two_campaigns(repo)

        occurrence_b = MessageOccurrence(
            id=uuid4(),
            owner_discord_user_id=OWNER_B,
            campaign_id=campaign_b.id,
            occurrence_key="occ-b2",
            occurrence_source=OccurrenceSource.EVENT,
            source_event_id=uuid4(),
        )
        await repo.create_occurrence(OWNER_B, occurrence_b)

        target_a = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign_a.id,
            target_kind=DomainTargetKind.CHANNEL,
            discord_channel_id=556,
        )
        await repo.create_target(target_a)

        engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            # campaign_id matches target_a's campaign, but occurrence_b
            # belongs to campaign_b -- the composite FK must reject this.
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO message_deliveries "
                            "(id, guild_id, campaign_id, occurrence_id, target_id, "
                            "delivery_key, discord_channel_id, allowed_mentions_snapshot) "
                            "VALUES (:id, :guild_id, :campaign_a_id, :occurrence_b_id, "
                            ":target_a_id, 'dk-mismatch2', 556, CAST('{}' AS JSONB))"
                        ),
                        {
                            "id": uuid4(),
                            "guild_id": GUILD_A,
                            "campaign_a_id": campaign_a.id,
                            "occurrence_b_id": occurrence_b.id,
                            "target_a_id": target_a.id,
                        },
                    )
        finally:
            await engine.dispose()


@pytest.mark.asyncio
class TestScheduleCursorPersistenceRoundTrip:
    """External-review finding: message_campaign_schedules.last_cursor_at
    was TIMESTAMPTZ in the DB while did.campaigns.scheduling treated it as
    a naive local wall-clock value -- a real persistence round-trip, not
    just an in-memory evaluation, is required to prove this is fixed."""

    async def test_persist_reload_and_evaluate_across_a_real_dst_boundary(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        campaign = _campaign(OWNER_A, lifecycle_status=LifecycleStatus.ACTIVE_RUNNING)
        await repo.create_campaign(campaign)

        # Starts two days before the real 2026-03-29 Europe/Paris
        # spring-forward transition; daily 09:00 never lands in the gap.
        # next_fire_at is what a real creation service would compute as the
        # first occurrence (Europe/Paris is CET/UTC+1 before the transition)
        # -- schedule creation setting an initial next_fire_at is an
        # application-layer responsibility not yet wired into a service
        # (see the WP13 orchestration gap in the handoff); set explicitly
        # here since this test exercises claim_due_schedules directly.
        schedule = DomainSchedule(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            schedule_kind=ScheduleKind.RECURRING,
            rrule="FREQ=DAILY",
            timezone="Europe/Paris",
            starts_at=datetime(2026, 3, 27, 9, 0, 0),
            catch_up_bound=10,
            next_fire_at=datetime(2026, 3, 27, 8, 0, 0, tzinfo=UTC),
        )
        await repo.create_schedule(schedule)

        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)

            # --- First evaluation pass (simulates the scheduler's first run) ---
            now_1 = datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC)
            [claimed_1] = await repo.claim_due_schedules(
                admin_factory, now=now_1, lease_owner="worker-1", limit=5
            )
            reloaded_1 = DomainSchedule(
                id=claimed_1["id"],
                owner_discord_user_id=claimed_1["owner_discord_user_id"],
                campaign_id=claimed_1["campaign_id"],
                schedule_kind=ScheduleKind.RECURRING,
                rrule=claimed_1["rrule"],
                timezone=claimed_1["timezone"],
                starts_at=claimed_1["starts_at"],
                catch_up_bound=claimed_1["catch_up_bound"],
                last_cursor_local=claimed_1["last_cursor_local"],
            )
            # This is the exact operation that would raise
            # "can't compare offset-naive and offset-aware datetimes" if the
            # persistence layer still round-tripped an aware value here.
            evaluation_1 = evaluate_recurring(reloaded_1, now=now_1)
            assert len(evaluation_1.due) >= 1  # crosses the real DST transition day

            finalized_1 = await repo.finalize_schedule_claim(
                admin_factory,
                schedule.id,
                claimed_1["lease_token"],
                now=now_1,
                new_last_cursor_local=evaluation_1.new_last_cursor_local,
                new_next_fire_at=evaluation_1.next_fire_at_utc,
            )
            assert finalized_1 is True

            # --- Second evaluation pass after a simulated restart ---
            persisted = await repo.get_schedule(OWNER_A, schedule.id)
            assert persisted is not None
            assert persisted["last_cursor_local"].tzinfo is None  # naive, as stored

            now_2 = datetime(2026, 3, 31, 12, 0, 0, tzinfo=UTC)
            reloaded_2 = DomainSchedule(
                id=persisted["id"],
                owner_discord_user_id=persisted["owner_discord_user_id"],
                campaign_id=persisted["campaign_id"],
                schedule_kind=ScheduleKind.RECURRING,
                rrule=persisted["rrule"],
                timezone=persisted["timezone"],
                starts_at=persisted["starts_at"],
                catch_up_bound=persisted["catch_up_bound"],
                last_cursor_local=persisted["last_cursor_local"],
            )
            evaluation_2 = evaluate_recurring(reloaded_2, now=now_2)

            # Deterministic: re-running the exact same evaluation again
            # produces the identical due set (same occurrence keys).
            evaluation_2_repeat = evaluate_recurring(reloaded_2, now=now_2)
            assert [o.occurrence_key for o in evaluation_2.due] == [
                o.occurrence_key for o in evaluation_2_repeat.due
            ]
            # No occurrence from pass 1 is ever repeated in pass 2 (the
            # cursor genuinely advanced, proving the round trip preserved
            # local-time semantics rather than silently resetting).
            assert set(o.occurrence_key for o in evaluation_1.due).isdisjoint(
                o.occurrence_key for o in evaluation_2.due
            )
        finally:
            await admin_engine.dispose()


@pytest.mark.asyncio
class TestGlossaryGuildScopeRls:
    """External-review REQ-MSG-014 finding: the missing GUILD glossary tier
    (migration 0024_stage_09) uses a dual-condition RLS policy -- prove it
    against real PostgreSQL, not just in-memory logic."""

    async def test_guild_scoped_entry_visible_to_any_owner_authorized_for_that_guild(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        entry = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            scope_kind=GlossaryScope.GUILD,
            guild_id=GUILD_A,
            source_term="Widget",
            behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
        )
        await repo.create_glossary_entry(entry)

        # OWNER_B, resolving glossary entries for the SAME Guild, must see
        # OWNER_A's GUILD-scoped entry -- it is Guild-wide, not author-only.
        visible_to_b = await repo.list_applicable_glossary_entries(
            owner_discord_user_id=OWNER_B, guild_id=GUILD_A
        )
        assert {row["id"] for row in visible_to_b} == {entry.id}

    async def test_guild_scoped_entry_not_visible_under_a_different_guild(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        entry = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            scope_kind=GlossaryScope.GUILD,
            guild_id=GUILD_A,
            source_term="Widget",
            behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
        )
        await repo.create_glossary_entry(entry)

        visible_under_b = await repo.list_applicable_glossary_entries(
            owner_discord_user_id=OWNER_A, guild_id=GUILD_B
        )
        assert visible_under_b == []

    async def test_global_user_entry_still_owner_isolated_not_leaked_via_guild_context(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        """The dual-condition policy must not accidentally widen
        GLOBAL_USER/CAMPAIGN visibility to other owners just because a
        Guild GUC happens to be set in the session."""
        repo = campaigns_context
        entry = GlossaryEntry(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            scope_kind=GlossaryScope.GLOBAL_USER,
            source_term="Gadget",
            behavior=GlossaryBehavior.DO_NOT_TRANSLATE,
        )
        await repo.create_glossary_entry(entry)

        visible_to_b = await repo.list_applicable_glossary_entries(
            owner_discord_user_id=OWNER_B, guild_id=GUILD_A
        )
        assert entry.id not in {row["id"] for row in visible_to_b}

        visible_to_a = await repo.list_applicable_glossary_entries(
            owner_discord_user_id=OWNER_A, guild_id=GUILD_A
        )
        assert entry.id in {row["id"] for row in visible_to_a}
