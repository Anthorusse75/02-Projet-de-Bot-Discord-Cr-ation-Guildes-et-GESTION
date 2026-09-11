"""PostgreSQL integration tests for the real Stage03 event transport
(WP8/WP12, sixth remediation pass): did.campaigns.event_transport
.consume_new_events_for_guild against a real discord_gateway_inbox row,
proving discovery (RuntimeRepository.runtime_campaign_event_guilds),
candidate-trigger cross-join, fan-out, cursor advancement, and that a
replayed/duplicate event never fires twice.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.campaigns.event_transport import consume_new_events_for_guild
from did.domain.campaigns import (
    CampaignTarget as DomainTarget,
)
from did.domain.campaigns import (
    CampaignTrigger,
    LifecycleStatus,
    MessageCampaign,
    PublicationMode,
)
from did.domain.campaigns import TargetKind as DomainTargetKind
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.database import create_database_engine
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    TranslationGroupRepository,
)
from did.messaging.message_model import MessageModel

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 880001201
OWNER_A = 880001211
NEW_MEMBER_ID = 880001221
TARGET_CHANNEL = 880001222

CLEANUP_STATEMENTS = (
    "DELETE FROM discord_gateway_inbox WHERE guild_id = :ga",
    "DELETE FROM message_campaign_event_cursor WHERE guild_id = :ga",
    "DELETE FROM message_campaign_trigger_consumptions WHERE guild_id = :ga",
    "DELETE FROM message_campaign_trigger_sources WHERE guild_id = :ga",
    "DELETE FROM message_deliveries WHERE guild_id = :ga",
    "DELETE FROM message_occurrences WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_campaign_targets WHERE guild_id = :ga",
    "DELETE FROM message_campaign_triggers WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_campaigns WHERE owner_discord_user_id = :oa",
)
CLEANUP_PARAMS = {"ga": GUILD_A, "oa": OWNER_A}


async def _insert_installation(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            "INSERT INTO guild_installations "
            "(guild_id,name,owner_id,installation_status) "
            "VALUES (:guild_id,'Guild A',:owner_id,'ACTIVE') "
            "ON CONFLICT (guild_id) DO UPDATE SET name=EXCLUDED.name"
        ),
        {"guild_id": GUILD_A, "owner_id": OWNER_A},
    )


async def _insert_user(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            "INSERT INTO users (discord_user_id, username) VALUES (:id, :name) "
            "ON CONFLICT (discord_user_id) DO NOTHING"
        ),
        {"id": OWNER_A, "name": f"user-{OWNER_A}"},
    )


async def _insert_gateway_event(
    connection: AsyncConnection, *, event_type: str, payload: dict[str, object]
) -> tuple[object, datetime]:
    import json

    event_id = uuid4()
    received_at = datetime.now(UTC)
    await connection.execute(
        text(
            "INSERT INTO discord_gateway_inbox "
            "(event_id,guild_id,event_type,discord_session_id,received_at,correlation_id,"
            "schema_version,source,origin,causation_depth,payload) VALUES "
            "(:event_id,:guild,:event_type,'test-session',:received_at,:event_id,1,"
            "'GATEWAY','DISCORD_EXTERNAL',0,CAST(:payload AS JSONB))"
        ),
        {
            "event_id": event_id,
            "guild": GUILD_A,
            "event_type": event_type,
            "received_at": received_at,
            "payload": json.dumps(payload),
        },
    )
    return event_id, received_at


@pytest.fixture
async def stage09_context() -> AsyncIterator[
    tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]]
]:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=3)
    app_engine = create_database_engine(APP_URL, pool_size=3)
    try:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id = :ga"), CLEANUP_PARAMS
            )
            await _insert_user(connection)
            await _insert_installation(connection)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
        yield CampaignsRepository(factory), RuntimeRepository(factory), admin_factory
    finally:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id = :ga"), CLEANUP_PARAMS
            )
        await app_engine.dispose()
        await admin_engine.dispose()


class _FakeChecker:
    async def is_guild_authorized(self, *, guild_id: int, owner_discord_user_id: int) -> bool:
        return True

    async def bot_can_send(self, *, guild_id: int, discord_channel_id: int) -> bool:
        return True


async def _setup_campaign_and_trigger(repo: CampaignsRepository) -> CampaignTrigger:
    campaign = MessageCampaign(
        id=uuid4(),
        owner_discord_user_id=OWNER_A,
        logical_campaign_key=f"key-{uuid4().hex[:8]}",
        name="Welcome",
        source_language_code="en",
        message_model=MessageModel(content="Welcome!").to_dict(),
        allowed_mentions_policy={"parse": []},
        publication_mode=PublicationMode.EVENT_TRIGGERED,
        lifecycle_status=LifecycleStatus.ACTIVE_RUNNING,
    )
    await repo.create_campaign(campaign)
    target = DomainTarget(
        id=uuid4(),
        guild_id=GUILD_A,
        campaign_id=campaign.id,
        target_kind=DomainTargetKind.CHANNEL,
        discord_channel_id=TARGET_CHANNEL,
    )
    await repo.create_target(target)
    trigger = CampaignTrigger(
        id=uuid4(),
        owner_discord_user_id=OWNER_A,
        campaign_id=campaign.id,
        event_type="GUILD_MEMBER_ADD",
        condition_ast={"op": "ALWAYS"},
    )
    await repo.create_trigger(trigger)
    from did.domain.campaigns import TriggerSourceBinding, TriggerSourceScopeKind

    await repo.create_trigger_source(
        TriggerSourceBinding(
            id=uuid4(),
            guild_id=GUILD_A,
            trigger_id=trigger.id,
            source_scope_kind=TriggerSourceScopeKind.GUILD,
        )
    )
    return trigger


@pytest.mark.asyncio
class TestConsumeNewEventsForGuild:
    async def test_real_gateway_event_fires_trigger_and_creates_a_delivery(
        self,
        stage09_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        campaigns_repo, runtime_repo, factory = stage09_context
        await _setup_campaign_and_trigger(campaigns_repo)

        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin_engine.begin() as connection:
                await _insert_gateway_event(
                    connection,
                    event_type="GUILD_MEMBER_ADD",
                    payload={"discord_user_id": NEW_MEMBER_ID},
                )
        finally:
            await admin_engine.dispose()

        assert GUILD_A in await runtime_repo.runtime_campaign_event_guilds()

        fired = await consume_new_events_for_guild(
            campaigns_repository=campaigns_repo,
            runtime_repository=runtime_repo,
            admin_factory=factory,
            language_profiles=LanguageProfileRepository(factory),
            translation_groups=TranslationGroupRepository(factory),
            checker=_FakeChecker(),
            translation_provider=None,
            lease_owner="event-transport-test",
            guild_id=GUILD_A,
        )
        assert fired == 1

        deliveries = await campaigns_repo.list_pending_delivery_ids(GUILD_A, limit=10)
        assert len(deliveries) == 1

        # The cursor advanced -- the Guild no longer shows up as having new
        # unconsumed campaign events.
        assert GUILD_A not in await runtime_repo.runtime_campaign_event_guilds()

    async def test_replaying_the_same_event_never_fires_twice(
        self,
        stage09_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        campaigns_repo, runtime_repo, factory = stage09_context
        await _setup_campaign_and_trigger(campaigns_repo)

        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin_engine.begin() as connection:
                await _insert_gateway_event(
                    connection,
                    event_type="GUILD_MEMBER_ADD",
                    payload={"discord_user_id": NEW_MEMBER_ID},
                )
        finally:
            await admin_engine.dispose()

        kwargs = dict(
            campaigns_repository=campaigns_repo,
            runtime_repository=runtime_repo,
            admin_factory=factory,
            language_profiles=LanguageProfileRepository(factory),
            translation_groups=TranslationGroupRepository(factory),
            checker=_FakeChecker(),
            translation_provider=None,
            lease_owner="event-transport-test",
            guild_id=GUILD_A,
        )
        first = await consume_new_events_for_guild(**kwargs)  # type: ignore[arg-type]
        assert first == 1

        # Nothing new since the cursor advanced -- a second pass finds no
        # rows at all (not even a replay attempt).
        second = await consume_new_events_for_guild(**kwargs)  # type: ignore[arg-type]
        assert second == 0

        deliveries = await campaigns_repo.list_pending_delivery_ids(GUILD_A, limit=10)
        assert len(deliveries) == 1

    async def test_wrong_event_type_trigger_does_not_fire(
        self,
        stage09_context: tuple[CampaignsRepository, RuntimeRepository, async_sessionmaker[Any]],
    ) -> None:
        campaigns_repo, runtime_repo, factory = stage09_context
        campaign = MessageCampaign(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            logical_campaign_key=f"key-{uuid4().hex[:8]}",
            name="Wrong type",
            source_language_code="en",
            message_model=MessageModel(content="Hi").to_dict(),
            allowed_mentions_policy={"parse": []},
            publication_mode=PublicationMode.EVENT_TRIGGERED,
            lifecycle_status=LifecycleStatus.ACTIVE_RUNNING,
        )
        await campaigns_repo.create_campaign(campaign)
        trigger = CampaignTrigger(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            event_type="GUILD_ROLE_CREATE",
            condition_ast={"op": "ALWAYS"},
        )
        await campaigns_repo.create_trigger(trigger)
        from did.domain.campaigns import TriggerSourceBinding, TriggerSourceScopeKind

        await campaigns_repo.create_trigger_source(
            TriggerSourceBinding(
                id=uuid4(),
                guild_id=GUILD_A,
                trigger_id=trigger.id,
                source_scope_kind=TriggerSourceScopeKind.GUILD,
            )
        )

        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin_engine.begin() as connection:
                await _insert_gateway_event(
                    connection,
                    event_type="GUILD_MEMBER_ADD",
                    payload={"discord_user_id": NEW_MEMBER_ID},
                )
        finally:
            await admin_engine.dispose()

        fired = await consume_new_events_for_guild(
            campaigns_repository=campaigns_repo,
            runtime_repository=runtime_repo,
            admin_factory=factory,
            language_profiles=LanguageProfileRepository(factory),
            translation_groups=TranslationGroupRepository(factory),
            checker=_FakeChecker(),
            translation_provider=None,
            lease_owner="event-transport-test",
            guild_id=GUILD_A,
        )
        assert fired == 0
