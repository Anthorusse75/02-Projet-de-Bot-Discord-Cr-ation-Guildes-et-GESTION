"""PostgreSQL integration tests for REQ-MSG-019 delivery-history retention
(sixth remediation pass): did.campaigns.retention.purge_expired_deliveries /
CampaignsRepository.purge_terminal_deliveries against a real database --
proves cutoff-boundary correctness, that only genuinely terminal
(SENT/FAILED) deliveries are ever purged by age, and Guild/owner isolation.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.campaigns.retention import (
    DEFAULT_RETENTION_DAYS,
    InvalidRetentionPolicy,
    RetentionPolicy,
    purge_expired_deliveries,
)
from did.domain.campaigns import (
    CampaignTarget as DomainTarget,
)
from did.domain.campaigns import (
    LifecycleStatus,
    MessageCampaign,
    MessageDelivery,
    MessageOccurrence,
    OccurrenceSource,
    PublicationMode,
)
from did.domain.campaigns import TargetKind as DomainTargetKind
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.database import create_database_engine
from did.messaging.message_model import MessageModel

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 880001001
GUILD_B = 880001002
OWNER_A = 880001011
OWNER_B = 880001012

CLEANUP_STATEMENTS = (
    "DELETE FROM message_deliveries WHERE guild_id IN (:ga,:gb)",
    "DELETE FROM message_campaign_targets WHERE guild_id IN (:ga,:gb)",
    "DELETE FROM message_occurrences WHERE owner_discord_user_id IN (:oa,:ob)",
    "DELETE FROM message_campaigns WHERE owner_discord_user_id IN (:oa,:ob)",
)
CLEANUP_PARAMS = {"ga": GUILD_A, "gb": GUILD_B, "oa": OWNER_A, "ob": OWNER_B}


async def _insert_installation(connection: AsyncConnection, guild_id: int, owner: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO guild_installations "
            "(guild_id,name,owner_id,installation_status) "
            "VALUES (:guild_id,:name,:owner_id,'ACTIVE') "
            "ON CONFLICT (guild_id) DO UPDATE SET name=EXCLUDED.name"
        ),
        {"guild_id": guild_id, "name": f"Stage 09 retention {guild_id}", "owner_id": owner},
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
            await _insert_installation(connection, GUILD_A, OWNER_A)
            await _insert_installation(connection, GUILD_B, OWNER_B)
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


async def _insert_delivery(
    repo: CampaignsRepository,
    *,
    guild_id: int,
    owner: int,
    status: str,
    age_days: float,
) -> MessageDelivery:
    """Creates a real delivery through the repository, then directly
    backdates its updated_at/status via a raw admin connection -- there is
    no public API for setting an arbitrary historical timestamp, and this
    test module deliberately does not add one just for testing."""
    campaign = MessageCampaign(
        id=uuid4(),
        owner_discord_user_id=owner,
        logical_campaign_key=f"key-{uuid4().hex[:8]}",
        name="Retention",
        source_language_code="en",
        message_model={"content": "hi"},
        allowed_mentions_policy={"parse": []},
        publication_mode=PublicationMode.IMMEDIATE,
        lifecycle_status=LifecycleStatus.ACTIVE_RUNNING,
    )
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
        allowed_mentions_snapshot={"parse": [], "users": [], "roles": [], "replied_user": False},
        content_snapshot=MessageModel(content="hi").to_dict(),
    )
    await repo.create_delivery(delivery)

    admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        backdated = datetime.now(UTC) - timedelta(days=age_days)
        async with admin_engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE message_deliveries SET status=:status, updated_at=:updated_at "
                    "WHERE id=:id"
                ),
                {"status": status, "updated_at": backdated, "id": delivery.id},
            )
    finally:
        await admin_engine.dispose()
    return delivery


class TestRetentionPolicyValidation:
    def test_default_policy_is_within_bounds(self) -> None:
        policy = RetentionPolicy()
        assert policy.retention_days == DEFAULT_RETENTION_DAYS

    def test_zero_or_negative_days_is_rejected(self) -> None:
        with pytest.raises(InvalidRetentionPolicy):
            RetentionPolicy(retention_days=0)
        with pytest.raises(InvalidRetentionPolicy):
            RetentionPolicy(retention_days=-1)

    def test_unbounded_duration_is_rejected(self) -> None:
        with pytest.raises(InvalidRetentionPolicy):
            RetentionPolicy(retention_days=999_999)

    def test_none_disables_purge_without_raising(self) -> None:
        policy = RetentionPolicy(retention_days=None)
        assert policy.cutoff(now=datetime.now(UTC)) is None


@pytest.mark.asyncio
class TestPurgeExpiredDeliveries:
    async def test_disabled_policy_purges_nothing(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        delivery = await _insert_delivery(
            repo, guild_id=GUILD_A, owner=OWNER_A, status="SENT", age_days=9999
        )
        purged = await purge_expired_deliveries(
            repo, RetentionPolicy(retention_days=None), guild_id=GUILD_A, now=datetime.now(UTC)
        )
        assert purged == 0
        assert await repo.get_delivery_status(GUILD_A, delivery.id) == "SENT"

    async def test_recent_terminal_delivery_is_retained(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        delivery = await _insert_delivery(
            repo, guild_id=GUILD_A, owner=OWNER_A, status="SENT", age_days=1
        )
        purged = await purge_expired_deliveries(
            repo, RetentionPolicy(retention_days=90), guild_id=GUILD_A, now=datetime.now(UTC)
        )
        assert purged == 0
        assert await repo.get_delivery_status(GUILD_A, delivery.id) == "SENT"

    async def test_old_terminal_delivery_is_purged(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        delivery = await _insert_delivery(
            repo, guild_id=GUILD_A, owner=OWNER_A, status="SENT", age_days=91
        )
        purged = await purge_expired_deliveries(
            repo, RetentionPolicy(retention_days=90), guild_id=GUILD_A, now=datetime.now(UTC)
        )
        assert purged == 1
        assert await repo.get_delivery_status(GUILD_A, delivery.id) is None

    async def test_old_failed_delivery_is_also_purged(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        delivery = await _insert_delivery(
            repo, guild_id=GUILD_A, owner=OWNER_A, status="FAILED", age_days=91
        )
        purged = await purge_expired_deliveries(
            repo, RetentionPolicy(retention_days=90), guild_id=GUILD_A, now=datetime.now(UTC)
        )
        assert purged == 1
        assert await repo.get_delivery_status(GUILD_A, delivery.id) is None

    @pytest.mark.parametrize(
        "status", ["PENDING", "CLAIMED", "SENDING", "UNKNOWN", "INTERVENTION_REQUIRED"]
    )
    async def test_active_or_ambiguous_deliveries_are_never_purged_regardless_of_age(
        self, campaigns_context: CampaignsRepository, status: str
    ) -> None:
        repo = campaigns_context
        delivery = await _insert_delivery(
            repo, guild_id=GUILD_A, owner=OWNER_A, status=status, age_days=9999
        )
        purged = await purge_expired_deliveries(
            repo, RetentionPolicy(retention_days=90), guild_id=GUILD_A, now=datetime.now(UTC)
        )
        assert purged == 0
        assert await repo.get_delivery_status(GUILD_A, delivery.id) == status

    async def test_cutoff_boundary_is_exclusive_of_the_retention_window(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        just_inside = await _insert_delivery(
            repo, guild_id=GUILD_A, owner=OWNER_A, status="SENT", age_days=89.9
        )
        just_outside = await _insert_delivery(
            repo, guild_id=GUILD_A, owner=OWNER_A, status="SENT", age_days=90.1
        )
        purged = await purge_expired_deliveries(
            repo, RetentionPolicy(retention_days=90), guild_id=GUILD_A, now=datetime.now(UTC)
        )
        assert purged == 1
        assert await repo.get_delivery_status(GUILD_A, just_inside.id) == "SENT"
        assert await repo.get_delivery_status(GUILD_A, just_outside.id) is None

    async def test_guild_isolation_purge_never_crosses_guilds(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        old_in_a = await _insert_delivery(
            repo, guild_id=GUILD_A, owner=OWNER_A, status="SENT", age_days=91
        )
        old_in_b = await _insert_delivery(
            repo, guild_id=GUILD_B, owner=OWNER_B, status="SENT", age_days=91
        )
        purged = await purge_expired_deliveries(
            repo, RetentionPolicy(retention_days=90), guild_id=GUILD_A, now=datetime.now(UTC)
        )
        assert purged == 1
        assert await repo.get_delivery_status(GUILD_A, old_in_a.id) is None
        # Guild B's own old delivery is untouched by a purge scoped to Guild A.
        assert await repo.get_delivery_status(GUILD_B, old_in_b.id) == "SENT"

    async def test_owner_isolation_purge_scoped_by_guild_never_touches_another_owner(
        self, campaigns_context: CampaignsRepository
    ) -> None:
        repo = campaigns_context
        old_owner_a = await _insert_delivery(
            repo, guild_id=GUILD_A, owner=OWNER_A, status="SENT", age_days=91
        )
        old_owner_b = await _insert_delivery(
            repo, guild_id=GUILD_B, owner=OWNER_B, status="SENT", age_days=91
        )
        await purge_expired_deliveries(
            repo, RetentionPolicy(retention_days=90), guild_id=GUILD_A, now=datetime.now(UTC)
        )
        assert await repo.get_delivery_status(GUILD_A, old_owner_a.id) is None
        assert await repo.get_delivery_status(GUILD_B, old_owner_b.id) == "SENT"
