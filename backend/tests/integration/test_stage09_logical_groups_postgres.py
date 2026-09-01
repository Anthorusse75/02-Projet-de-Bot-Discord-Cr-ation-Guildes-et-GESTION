"""PostgreSQL integration tests for REQ-MSG-002 logical group campaign
targets (sixth remediation pass): did.campaigns.logical_groups
.expand_logical_group against a real Stage04Repository/logical_groups
schema, did.campaigns.target_resolution.resolve_logical_group_target, and
a full did.campaigns.activation.fan_out_occurrence run creating one
delivery per real expanded channel.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.campaigns.activation import fan_out_occurrence
from did.campaigns.logical_groups import expand_logical_group
from did.campaigns.target_resolution import BlockReason, resolve_target
from did.domain.campaigns import (
    CampaignTarget as DomainTarget,
)
from did.domain.campaigns import (
    LifecycleStatus,
    MessageCampaign,
    MessageOccurrence,
    OccurrenceSource,
    PublicationMode,
)
from did.domain.campaigns import TargetKind as DomainTargetKind
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.database import create_database_engine
from did.infrastructure.stage04_repository import Stage04Repository
from did.messaging.allowed_mentions import NO_MENTIONS
from did.messaging.message_model import MessageModel

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 880001101
OWNER_A = 880001111
CATEGORY_ID = 880001121
TEXT_CHANNEL_1 = 880001122
TEXT_CHANNEL_2 = 880001123
VOICE_CHANNEL = 880001124
STANDALONE_CHANNEL = 880001125
ROLE_ID = 880001126

CLEANUP_STATEMENTS = (
    "DELETE FROM message_deliveries WHERE guild_id = :ga",
    "DELETE FROM message_campaign_targets WHERE guild_id = :ga",
    "DELETE FROM message_occurrences WHERE owner_discord_user_id = :oa",
    "DELETE FROM message_campaigns WHERE owner_discord_user_id = :oa",
    "DELETE FROM logical_group_resources WHERE guild_id = :ga",
    "DELETE FROM logical_groups WHERE guild_id = :ga",
    "DELETE FROM discord_channels_cache WHERE guild_id = :ga",
    "DELETE FROM discord_roles_cache WHERE guild_id = :ga",
    "DELETE FROM discord_cache_coverage WHERE guild_id = :ga",
)
CLEANUP_PARAMS = {"ga": GUILD_A, "oa": OWNER_A}

NOW = datetime.now(UTC)


async def _insert_installation(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            "INSERT INTO guild_installations "
            "(guild_id,name,owner_id,installation_status,last_gateway_seen_at) "
            "VALUES (:guild_id,'Guild A',:owner_id,'ACTIVE',:now) "
            "ON CONFLICT (guild_id) DO UPDATE SET name=EXCLUDED.name"
        ),
        {"guild_id": GUILD_A, "owner_id": OWNER_A, "now": NOW},
    )


async def _insert_user(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            "INSERT INTO users (discord_user_id, username) VALUES (:id, :name) "
            "ON CONFLICT (discord_user_id) DO NOTHING"
        ),
        {"id": OWNER_A, "name": f"user-{OWNER_A}"},
    )


async def _insert_channel(
    connection: AsyncConnection, *, channel_id: int, channel_type: int, parent_id: int | None
) -> None:
    await connection.execute(
        text(
            "INSERT INTO discord_channels_cache "
            "(guild_id,channel_id,type,name,parent_id,position,nsfw,last_full_payload,"
            "observability_state,freshness_state,last_full_observed_at,last_gateway_seen_at) "
            "VALUES (:guild,:channel,:type,'channel',:parent,0,false,'{}','VISIBLE','FRESH',"
            ":now,:now)"
        ),
        {
            "guild": GUILD_A,
            "channel": channel_id,
            "type": channel_type,
            "parent": parent_id,
            "now": NOW,
        },
    )


async def _insert_role(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            "INSERT INTO discord_roles_cache "
            "(guild_id,role_id,name,position,permissions_bits,managed,color,hoist,"
            "mentionable,raw_json,last_gateway_seen_at) VALUES "
            "(:guild,:role,'role',1,0,false,0,false,false,'{}',:now)"
        ),
        {"guild": GUILD_A, "role": ROLE_ID, "now": NOW},
    )


async def _insert_coverage(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            "INSERT INTO discord_cache_coverage "
            "(guild_id,coverage_mode,freshness_state,known_channels,visible_channels,"
            "known_roles,last_gateway_event_at,gateway_continuity) VALUES "
            "(:guild,'FULL','FRESH',4,4,1,:now,'CONNECTED')"
        ),
        {"guild": GUILD_A, "now": NOW},
    )


async def _insert_logical_group(connection: AsyncConnection) -> tuple[UUID, list[UUID]]:
    group_id = uuid4()
    await connection.execute(
        text(
            "INSERT INTO logical_groups (id,guild_id,name,slug,metadata_json) "
            "VALUES (:id,:guild,'Announcements','announcements','{}')"
        ),
        {"id": group_id, "guild": GUILD_A},
    )
    resource_ids = []
    for resource_type, channel_id, role_id in (
        ("CHANNEL", STANDALONE_CHANNEL, None),
        ("CATEGORY", CATEGORY_ID, None),
        ("ROLE", None, ROLE_ID),
    ):
        resource_id = uuid4()
        resource_ids.append(resource_id)
        await connection.execute(
            text(
                "INSERT INTO logical_group_resources "
                "(id,guild_id,logical_group_id,resource_type,discord_channel_id,discord_role_id) "
                "VALUES (:id,:guild,:group_id,:kind,:channel,:role)"
            ),
            {
                "id": resource_id,
                "guild": GUILD_A,
                "group_id": group_id,
                "kind": resource_type,
                "channel": channel_id,
                "role": role_id,
            },
        )
    return group_id, resource_ids


@pytest.fixture
async def stage09_context() -> AsyncIterator[tuple[CampaignsRepository, Stage04Repository, UUID]]:
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
            await _insert_channel(
                connection, channel_id=CATEGORY_ID, channel_type=4, parent_id=None
            )
            await _insert_channel(
                connection, channel_id=TEXT_CHANNEL_1, channel_type=0, parent_id=CATEGORY_ID
            )
            await _insert_channel(
                connection, channel_id=TEXT_CHANNEL_2, channel_type=0, parent_id=CATEGORY_ID
            )
            await _insert_channel(
                connection, channel_id=VOICE_CHANNEL, channel_type=2, parent_id=CATEGORY_ID
            )
            await _insert_channel(
                connection, channel_id=STANDALONE_CHANNEL, channel_type=0, parent_id=None
            )
            await _insert_role(connection)
            await _insert_coverage(connection)
            group_id, _resource_ids = await _insert_logical_group(connection)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        yield CampaignsRepository(factory), Stage04Repository(factory), group_id
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
    def __init__(self, *, sendable_channels: set[int] | None = None) -> None:
        self.sendable_channels = sendable_channels

    async def is_guild_authorized(self, *, guild_id: int, owner_discord_user_id: int) -> bool:
        return True

    async def bot_can_send(self, *, guild_id: int, discord_channel_id: int) -> bool:
        if self.sendable_channels is None:
            return True
        return discord_channel_id in self.sendable_channels


@pytest.mark.asyncio
class TestExpandLogicalGroup:
    async def test_expands_to_standalone_channel_and_category_text_channels_only(
        self, stage09_context: tuple[CampaignsRepository, Stage04Repository, UUID]
    ) -> None:
        _repo, stage04_repo, group_id = stage09_context
        expansion = await expand_logical_group(
            stage04_repo, guild_id=GUILD_A, logical_group_id=group_id
        )
        assert expansion is not None
        # STANDALONE_CHANNEL (direct CHANNEL resource) + the category's two
        # text channels -- never the category itself, never the voice
        # channel, never anything from the ROLE resource.
        assert set(expansion.discord_channel_ids) == {
            STANDALONE_CHANNEL,
            TEXT_CHANNEL_1,
            TEXT_CHANNEL_2,
        }
        assert CATEGORY_ID not in expansion.discord_channel_ids
        assert VOICE_CHANNEL not in expansion.discord_channel_ids

    async def test_unknown_group_returns_none(
        self, stage09_context: tuple[CampaignsRepository, Stage04Repository, UUID]
    ) -> None:
        _repo, stage04_repo, _group_id = stage09_context
        expansion = await expand_logical_group(
            stage04_repo, guild_id=GUILD_A, logical_group_id=uuid4()
        )
        assert expansion is None


@pytest.mark.asyncio
class TestResolveLogicalGroupTarget:
    async def test_resolves_to_real_expanded_channels_with_fresh_authorization(
        self, stage09_context: tuple[CampaignsRepository, Stage04Repository, UUID]
    ) -> None:
        _repo, stage04_repo, group_id = stage09_context
        expansion = await expand_logical_group(
            stage04_repo, guild_id=GUILD_A, logical_group_id=group_id
        )
        target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=uuid4(),
            target_kind=DomainTargetKind.LOGICAL_GROUP,
            logical_group_id=group_id,
        )
        resolved = await resolve_target(
            target,
            owner_discord_user_id=OWNER_A,
            authorization=_FakeChecker(),
            logical_group_expansion=expansion,
        )
        assert {dest.discord_channel_id for dest in resolved} == {
            STANDALONE_CHANNEL,
            TEXT_CHANNEL_1,
            TEXT_CHANNEL_2,
        }
        assert all(dest.is_ready for dest in resolved)

    async def test_a_channel_the_bot_cannot_send_in_is_individually_blocked(
        self, stage09_context: tuple[CampaignsRepository, Stage04Repository, UUID]
    ) -> None:
        _repo, stage04_repo, group_id = stage09_context
        expansion = await expand_logical_group(
            stage04_repo, guild_id=GUILD_A, logical_group_id=group_id
        )
        target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=uuid4(),
            target_kind=DomainTargetKind.LOGICAL_GROUP,
            logical_group_id=group_id,
        )
        resolved = await resolve_target(
            target,
            owner_discord_user_id=OWNER_A,
            authorization=_FakeChecker(sendable_channels={STANDALONE_CHANNEL}),
            logical_group_expansion=expansion,
        )
        blocked = [dest for dest in resolved if not dest.is_ready]
        ready = [dest for dest in resolved if dest.is_ready]
        assert len(ready) == 1
        assert ready[0].discord_channel_id == STANDALONE_CHANNEL
        assert len(blocked) == 2
        assert all(dest.blocked_reason is BlockReason.BOT_CANNOT_SEND for dest in blocked)


@pytest.mark.asyncio
class TestFanOutWithLogicalGroupTarget:
    async def test_fan_out_creates_one_delivery_per_expanded_channel(
        self, stage09_context: tuple[CampaignsRepository, Stage04Repository, UUID]
    ) -> None:
        repo, stage04_repo, group_id = stage09_context
        campaign = MessageCampaign(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            logical_campaign_key=f"key-{uuid4().hex[:8]}",
            name="Logical group launch",
            source_language_code="en",
            message_model=MessageModel(content="Hello everyone!").to_dict(),
            allowed_mentions_policy={"parse": []},
            publication_mode=PublicationMode.IMMEDIATE,
            lifecycle_status=LifecycleStatus.ACTIVE_RUNNING,
        )
        await repo.create_campaign(campaign)
        target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=campaign.id,
            target_kind=DomainTargetKind.LOGICAL_GROUP,
            logical_group_id=group_id,
        )
        await repo.create_target(target)
        expansion = await expand_logical_group(
            stage04_repo, guild_id=GUILD_A, logical_group_id=group_id
        )
        occurrence = MessageOccurrence(
            id=uuid4(),
            owner_discord_user_id=OWNER_A,
            campaign_id=campaign.id,
            occurrence_key=f"occ-{uuid4().hex[:8]}",
            occurrence_source=OccurrenceSource.EVENT,
            source_event_id=uuid4(),
        )

        outcome = await fan_out_occurrence(
            repository=repo,
            checker=_FakeChecker(),
            campaign=campaign,
            targets=(target,),
            occurrence=occurrence,
            lease_owner="worker-1",
            topology_by_target={},
            logical_group_expansion_by_target={target.id: expansion},
            language_profile_codes={},
            compiled_mentions=NO_MENTIONS,
            template_variable_definitions={},
            glossary_entries=(),
            translate_masked_text_for_language=None,
        )
        assert outcome.is_fully_healthy
        assert outcome.deliveries_created == 3
