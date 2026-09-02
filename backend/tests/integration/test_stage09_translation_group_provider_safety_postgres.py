"""PostgreSQL integration test for REQ-MSG-007/013 double-translation
safety against REAL Stage08 Translation Group/provider-binding data:
did.campaigns.context.load_translation_group_topology must surface the
actual translation_provider_bindings.status for a group's real
provider_binding_id, and did.campaigns.target_resolution
.resolve_translation_group_target must then block/allow
DID_TRANSLATED_FANOUT accordingly -- proven end to end, not just at the
pure-decision unit level.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.campaigns.context import load_translation_group_topology
from did.campaigns.target_resolution import BlockReason, resolve_target
from did.domain.campaigns import (
    CampaignTarget as DomainTarget,
)
from did.domain.campaigns import TargetKind as DomainTargetKind
from did.domain.campaigns import TranslationPublicationMode
from did.infrastructure.database import create_database_engine
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    TranslationGroupRepository,
    TranslationProviderBindingRepository,
)

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 880001301
OWNER_A = 880001311
SOURCE_CHANNEL = 880001321
VARIANT_CHANNEL = 880001322

CLEANUP_STATEMENTS = (
    "DELETE FROM translation_channel_variants WHERE guild_id = :ga",
    "DELETE FROM translation_channel_groups WHERE guild_id = :ga",
    "DELETE FROM translation_group_languages WHERE guild_id = :ga",
    "DELETE FROM translation_groups WHERE guild_id = :ga",
    "DELETE FROM translation_provider_bindings WHERE guild_id = :ga",
    "DELETE FROM language_profiles WHERE guild_id = :ga",
    "DELETE FROM discord_channels_cache WHERE guild_id = :ga",
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


async def _insert_channel(connection: AsyncConnection, *, channel_id: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO discord_channels_cache "
            "(guild_id,channel_id,type,name,position,nsfw,last_full_payload,"
            "observability_state,freshness_state) "
            "VALUES (:guild,:channel,0,'channel',0,false,'{}','VISIBLE','FRESH')"
        ),
        {"guild": GUILD_A, "channel": channel_id},
    )


@pytest.fixture
async def stage08_setup() -> AsyncIterator[
    tuple[TranslationGroupRepository, TranslationProviderBindingRepository, UUID]
]:
    """Builds a REAL Stage08 Translation Group with one channel group and
    one non-source language variant -- returns the repos plus the
    translation_group_id."""
    admin_engine = create_database_engine(ADMIN_URL, pool_size=3)
    app_engine = create_database_engine(APP_URL, pool_size=3)
    try:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id = :ga"), CLEANUP_PARAMS
            )
            await _insert_installation(connection)
            await _insert_channel(connection, channel_id=SOURCE_CHANNEL)
            await _insert_channel(connection, channel_id=VARIANT_CHANNEL)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        language_profiles = LanguageProfileRepository(factory)
        translation_groups = TranslationGroupRepository(factory)
        provider_bindings = TranslationProviderBindingRepository(factory)

        source_language = await language_profiles.create(
            guild_id=GUILD_A, code="en", display_name="English"
        )
        target_language = await language_profiles.create(
            guild_id=GUILD_A, code="fr", display_name="French"
        )
        group = await translation_groups.create_with_languages(
            guild_id=GUILD_A,
            name="Announcements",
            root_kind="CHANNEL_SET",
            routing_mode="HUB_AND_SPOKE",
            language_profile_ids=(source_language["id"], target_language["id"]),
            source_language_profile_id=source_language["id"],
        )
        channel_group = await translation_groups.create_channel_group(
            guild_id=GUILD_A,
            translation_group_id=group["id"],
            logical_key="main",
            source_language_profile_id=source_language["id"],
        )
        await translation_groups.create_channel_variant(
            guild_id=GUILD_A,
            translation_group_id=group["id"],
            translation_channel_group_id=channel_group["id"],
            language_profile_id=source_language["id"],
            discord_channel_id=SOURCE_CHANNEL,
        )
        await translation_groups.create_channel_variant(
            guild_id=GUILD_A,
            translation_group_id=group["id"],
            translation_channel_group_id=channel_group["id"],
            language_profile_id=target_language["id"],
            discord_channel_id=VARIANT_CHANNEL,
        )
        yield translation_groups, provider_bindings, group["id"]
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


@pytest.mark.asyncio
class TestRealProviderBindingGatesFanOut:
    async def test_no_provider_bound_allows_did_translated_fanout(
        self,
        stage08_setup: tuple[
            TranslationGroupRepository, TranslationProviderBindingRepository, UUID
        ],
    ) -> None:
        translation_groups, _provider_bindings, group_id = stage08_setup
        topology = await load_translation_group_topology(
            translation_groups, guild_id=GUILD_A, translation_group_id=group_id
        )
        assert topology is not None
        assert topology.provider_binding_status is None

        target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=uuid4(),
            target_kind=DomainTargetKind.TRANSLATION_GROUP,
            translation_group_id=group_id,
            translation_publication_mode=TranslationPublicationMode.DID_TRANSLATED_FANOUT,
        )
        resolved = await resolve_target(
            target, owner_discord_user_id=OWNER_A, authorization=_FakeChecker(), topology=topology
        )
        assert len(resolved) == 2
        assert all(dest.is_ready for dest in resolved)

    async def test_ready_bound_provider_blocks_did_translated_fanout(
        self,
        stage08_setup: tuple[
            TranslationGroupRepository, TranslationProviderBindingRepository, UUID
        ],
    ) -> None:
        translation_groups, provider_bindings, group_id = stage08_setup
        binding = await provider_bindings.create(
            guild_id=GUILD_A,
            provider_type="EXTERNAL_BOT",
            provider_instance_key="polyglot-bot",
            capabilities={},
            status="READY",
        )
        async with create_database_engine(ADMIN_URL, pool_size=1).begin() as connection:
            await connection.execute(
                text(
                    "UPDATE translation_groups SET provider_binding_id=:binding_id "
                    "WHERE guild_id=:guild_id AND id=:group_id"
                ),
                {"binding_id": binding["id"], "guild_id": GUILD_A, "group_id": group_id},
            )

        topology = await load_translation_group_topology(
            translation_groups,
            guild_id=GUILD_A,
            translation_group_id=group_id,
            provider_bindings=provider_bindings,
        )
        assert topology is not None
        assert topology.provider_binding_status == "READY"

        target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=uuid4(),
            target_kind=DomainTargetKind.TRANSLATION_GROUP,
            translation_group_id=group_id,
            translation_publication_mode=TranslationPublicationMode.DID_TRANSLATED_FANOUT,
        )
        resolved = await resolve_target(
            target, owner_discord_user_id=OWNER_A, authorization=_FakeChecker(), topology=topology
        )
        assert len(resolved) == 1
        assert (
            resolved[0].blocked_reason is BlockReason.PROVIDER_SAFETY_MANUAL_CONFIGURATION_REQUIRED
        )

        # EXISTING_PROVIDER is unaffected by the same real bound provider --
        # it is designed to delegate to exactly this provider.
        existing_provider_target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=uuid4(),
            target_kind=DomainTargetKind.TRANSLATION_GROUP,
            translation_group_id=group_id,
            translation_publication_mode=TranslationPublicationMode.EXISTING_PROVIDER,
        )
        existing_provider_resolved = await resolve_target(
            existing_provider_target,
            owner_discord_user_id=OWNER_A,
            authorization=_FakeChecker(),
            topology=topology,
        )
        assert len(existing_provider_resolved) == 1
        assert existing_provider_resolved[0].is_ready

    async def test_disabled_bound_provider_allows_did_translated_fanout(
        self,
        stage08_setup: tuple[
            TranslationGroupRepository, TranslationProviderBindingRepository, UUID
        ],
    ) -> None:
        translation_groups, provider_bindings, group_id = stage08_setup
        binding = await provider_bindings.create(
            guild_id=GUILD_A,
            provider_type="EXTERNAL_BOT",
            provider_instance_key="polyglot-bot-disabled",
            capabilities={},
            status="DISABLED",
        )
        async with create_database_engine(ADMIN_URL, pool_size=1).begin() as connection:
            await connection.execute(
                text(
                    "UPDATE translation_groups SET provider_binding_id=:binding_id "
                    "WHERE guild_id=:guild_id AND id=:group_id"
                ),
                {"binding_id": binding["id"], "guild_id": GUILD_A, "group_id": group_id},
            )

        topology = await load_translation_group_topology(
            translation_groups,
            guild_id=GUILD_A,
            translation_group_id=group_id,
            provider_bindings=provider_bindings,
        )
        assert topology is not None
        assert topology.provider_binding_status == "DISABLED"

        target = DomainTarget(
            id=uuid4(),
            guild_id=GUILD_A,
            campaign_id=uuid4(),
            target_kind=DomainTargetKind.TRANSLATION_GROUP,
            translation_group_id=group_id,
            translation_publication_mode=TranslationPublicationMode.DID_TRANSLATED_FANOUT,
        )
        resolved = await resolve_target(
            target, owner_discord_user_id=OWNER_A, authorization=_FakeChecker(), topology=topology
        )
        assert len(resolved) == 2
        assert all(dest.is_ready for dest in resolved)
