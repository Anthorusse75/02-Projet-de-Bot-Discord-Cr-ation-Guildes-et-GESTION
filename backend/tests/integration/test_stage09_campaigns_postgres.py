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

from did.domain.campaigns import CampaignSchedule as DomainSchedule
from did.domain.campaigns import CampaignTarget as DomainTarget
from did.domain.campaigns import (
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


def _campaign(owner: int) -> MessageCampaign:
    return MessageCampaign(
        id=uuid4(),
        owner_discord_user_id=owner,
        logical_campaign_key=f"key-{uuid4().hex[:8]}",
        name="Launch",
        source_language_code="en",
        message_model={"content": "hello"},
        allowed_mentions_policy={"parse": []},
        publication_mode=PublicationMode.IMMEDIATE,
        lifecycle_status=LifecycleStatus.DRAFT,
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
        campaign = _campaign(OWNER_A)
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
