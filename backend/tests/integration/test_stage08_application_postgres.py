from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.application.discord_runtime import normalize_gateway_dispatch
from did.application.translation import LanguageProfileService, TranslationTopologyService
from did.domain.translation_topology import (
    TranslationGroupTopology,
)
from did.infrastructure.database import create_database_engine
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    ResourceLanguagePolicyRepository,
    Stage08Conflict,
    Stage08NotFound,
    TranslationGroupRepository,
    TranslationProviderBindingRepository,
    VisibilityScopeLanguageRepository,
)

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A, GUILD_B, USER = 881000001, 881000002, 881000101
DELETE_STATEMENTS = (
    "DELETE FROM translation_channel_variants WHERE guild_id IN (:a,:b)",
    "DELETE FROM translation_category_variants WHERE guild_id IN (:a,:b)",
    "DELETE FROM translation_channel_groups WHERE guild_id IN (:a,:b)",
    "DELETE FROM translation_routes WHERE guild_id IN (:a,:b)",
    "DELETE FROM translation_group_languages WHERE guild_id IN (:a,:b)",
    "DELETE FROM translation_groups WHERE guild_id IN (:a,:b)",
    "DELETE FROM translation_provider_bindings WHERE guild_id IN (:a,:b)",
    "DELETE FROM visibility_scope_language_roles WHERE guild_id IN (:a,:b)",
    "DELETE FROM member_visible_languages WHERE guild_id IN (:a,:b)",
    "DELETE FROM resource_language_policies WHERE guild_id IN (:a,:b)",
    "DELETE FROM language_profiles WHERE guild_id IN (:a,:b)",
)


async def installation(connection: AsyncConnection, guild_id: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO guild_installations "
            "(guild_id,name,owner_id,installation_status) "
            "VALUES (:id,:name,:owner,'ACTIVE') ON CONFLICT (guild_id) "
            "DO UPDATE SET name=EXCLUDED.name"
        ),
        {"id": guild_id, "name": f"Stage08 application {guild_id}", "owner": USER},
    )


@pytest.fixture
async def repositories() -> AsyncIterator[
    tuple[
        LanguageProfileRepository,
        ResourceLanguagePolicyRepository,
        TranslationGroupRepository,
        TranslationProviderBindingRepository,
        VisibilityScopeLanguageRepository,
    ]
]:
    admin = create_database_engine(ADMIN_URL, pool_size=1)
    app = create_database_engine(APP_URL, pool_size=4)
    async with admin.begin() as connection:
        for statement in DELETE_STATEMENTS:
            await connection.execute(text(statement), {"a": GUILD_A, "b": GUILD_B})
        await connection.execute(
            text("DELETE FROM guild_installations WHERE guild_id IN (:a,:b)"),
            {"a": GUILD_A, "b": GUILD_B},
        )
        await installation(connection, GUILD_A)
        await installation(connection, GUILD_B)
    factory = async_sessionmaker(app, expire_on_commit=False)
    try:
        yield (
            LanguageProfileRepository(factory),
            ResourceLanguagePolicyRepository(factory),
            TranslationGroupRepository(factory),
            TranslationProviderBindingRepository(factory),
            VisibilityScopeLanguageRepository(factory),
        )
    finally:
        async with admin.begin() as connection:
            for statement in DELETE_STATEMENTS:
                await connection.execute(
                    text(statement),
                    {"a": GUILD_A, "b": GUILD_B},
                )
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id IN (:a,:b)"),
                {"a": GUILD_A, "b": GUILD_B},
            )
        await app.dispose()
        await admin.dispose()


@pytest.mark.asyncio
async def test_member_zero_many_disable_and_resource_no_fallback(
    repositories: tuple[
        LanguageProfileRepository,
        ResourceLanguagePolicyRepository,
        TranslationGroupRepository,
        TranslationProviderBindingRepository,
        VisibilityScopeLanguageRepository,
    ],
) -> None:
    profiles, policies, *_ = repositories
    service = LanguageProfileService(profiles, policies)
    fr = await service.create(guild_id=GUILD_A, code="fr", display_name="French")
    en = await service.create(guild_id=GUILD_A, code="en", display_name="English")
    many = await service.set_member_languages(
        guild_id=GUILD_A,
        discord_user_id=USER,
        language_ids=(UUID(str(fr["id"])), UUID(str(en["id"]))),
        source="ONBOARDING",
    )
    assert len(many) == 2 and {row["source"] for row in many} == {"ONBOARDING"}
    await service.upsert_resource_policy(
        guild_id=GUILD_A,
        resource_type="CATEGORY",
        discord_resource_id=5001,
        explicit_language_profile_id=UUID(str(fr["id"])),
        inherit_language=False,
        visibility_policy="OPEN_ALL",
        visibility_scope_id=None,
        custom_policy={},
    )
    assert (
        await service.resolve_resource_language(guild_id=GUILD_A, channel_id=5002, category_id=5001)
    )["source"] == "CATEGORY"
    await service.update(guild_id=GUILD_A, language_id=UUID(str(fr["id"])), enabled=False)
    rows = await service.member_languages(guild_id=GUILD_A, discord_user_id=USER)
    assert (
        len(rows) == 2
        and next(row for row in rows if row["language_profile_id"] == fr["id"])["enabled"] is False
    )
    resolved = await service.resolve_resource_language(
        guild_id=GUILD_A, channel_id=5002, category_id=5001
    )
    assert resolved["language_profile_id"] is None and resolved["source"] == "NONE"
    assert (
        await service.set_member_languages(
            guild_id=GUILD_A, discord_user_id=USER, language_ids=(), source="EXPLICIT"
        )
        == []
    )


@pytest.mark.asyncio
async def test_stable_channel_group_rename_independent_groups_and_atomic_delta_cas(
    repositories: tuple[
        LanguageProfileRepository,
        ResourceLanguagePolicyRepository,
        TranslationGroupRepository,
        TranslationProviderBindingRepository,
        VisibilityScopeLanguageRepository,
    ],
) -> None:
    profiles, _, groups, providers, visibility = repositories
    topology = TranslationTopologyService(groups, providers, visibility)
    fr = await profiles.create(guild_id=GUILD_A, code="fr", display_name="French")
    en = await profiles.create(guild_id=GUILD_A, code="en", display_name="English")
    disabled = await profiles.create(guild_id=GUILD_A, code="it", display_name="Italian")
    await profiles.update(
        guild_id=GUILD_A,
        language_id=disabled["id"],
        display_name=None,
        emoji=None,
        enabled=False,
    )
    with pytest.raises(ValueError, match="enabled tenant"):
        await topology.create_group(
            guild_id=GUILD_A,
            name="Must roll back",
            root_kind="CHANNEL_SET",
            routing_mode="HUB_AND_SPOKE",
            language_ids=(fr["id"], disabled["id"]),
            visibility_scope_id=None,
            source_language_profile_id=fr["id"],
            provider_binding_id=None,
        )
    assert await groups.list_groups(GUILD_A) == []
    left = await topology.create_group(
        guild_id=GUILD_A,
        name="Guides",
        root_kind="CHANNEL_SET",
        routing_mode="HUB_AND_SPOKE",
        language_ids=(fr["id"], en["id"]),
        visibility_scope_id=None,
        source_language_profile_id=fr["id"],
        provider_binding_id=None,
    )
    right = await topology.create_group(
        guild_id=GUILD_A,
        name="Support",
        root_kind="CHANNEL_SET",
        routing_mode="HUB_AND_SPOKE",
        language_ids=(fr["id"], en["id"]),
        visibility_scope_id=None,
        source_language_profile_id=fr["id"],
        provider_binding_id=None,
    )
    assert left["id"] != right["id"]
    with pytest.raises(ValueError, match="enabled"):
        await topology.add_language_delta(
            guild_id=GUILD_A,
            group_id=left["id"],
            language_id=disabled["id"],
            expected_version=1,
        )
    unchanged = await groups.get(GUILD_A, left["id"])
    assert unchanged["version"] == 1
    channel_group = await topology.create_channel_group(
        guild_id=GUILD_A,
        group_id=left["id"],
        logical_key="guides.general",
        display_name="General",
        source_language_id=fr["id"],
    )
    variant = await groups.create_channel_variant(
        guild_id=GUILD_A,
        translation_group_id=left["id"],
        translation_channel_group_id=channel_group["id"],
        language_profile_id=fr["id"],
        discord_channel_id=881000201,
    )
    renamed = await topology.rename_channel_group(
        guild_id=GUILD_A,
        group_id=left["id"],
        channel_group_id=channel_group["id"],
        display_name="Renamed General",
    )
    assert (
        renamed["id"] == channel_group["id"]
        and renamed["logical_key"] == "guides.general"
        and renamed["display_name"] == "Renamed General"
    )
    assert variant["translation_channel_group_id"] == channel_group["id"]
    de = await profiles.create(guild_id=GUILD_A, code="de", display_name="German")
    es = await profiles.create(guild_id=GUILD_A, code="es", display_name="Spanish")
    results = await asyncio.gather(
        topology.add_language_delta(
            guild_id=GUILD_A, group_id=left["id"], language_id=de["id"], expected_version=1
        ),
        topology.add_language_delta(
            guild_id=GUILD_A, group_id=left["id"], language_id=es["id"], expected_version=1
        ),
        return_exceptions=True,
    )
    assert (
        sum(isinstance(item, dict) for item in results) == 1
        and sum(isinstance(item, Stage08Conflict) for item in results) == 1
    )
    workspace = await topology.workspace(GUILD_A)
    groups_by_id = {row["id"]: row for row in workspace["groups"]}
    assert (
        len(groups_by_id[left["id"]]["languages"]) == 3
        and len(groups_by_id[right["id"]]["languages"]) == 2
    )


@pytest.mark.asyncio
async def test_same_guild_nested_children_cannot_cross_translation_group_boundary(
    repositories: tuple[
        LanguageProfileRepository,
        ResourceLanguagePolicyRepository,
        TranslationGroupRepository,
        TranslationProviderBindingRepository,
        VisibilityScopeLanguageRepository,
    ],
) -> None:
    profiles, _, groups, providers, visibility = repositories
    topology = TranslationTopologyService(groups, providers, visibility)
    fr = await profiles.create(guild_id=GUILD_A, code="fr", display_name="French")
    group_a = await topology.create_group(
        guild_id=GUILD_A,
        name="A",
        root_kind="CHANNEL_SET",
        routing_mode="HUB_AND_SPOKE",
        language_ids=(fr["id"],),
        visibility_scope_id=None,
        source_language_profile_id=fr["id"],
        provider_binding_id=None,
    )
    group_b = await topology.create_group(
        guild_id=GUILD_A,
        name="B",
        root_kind="CHANNEL_SET",
        routing_mode="HUB_AND_SPOKE",
        language_ids=(fr["id"],),
        visibility_scope_id=None,
        source_language_profile_id=fr["id"],
        provider_binding_id=None,
    )
    channel_group_b = await topology.create_channel_group(
        guild_id=GUILD_A,
        group_id=group_b["id"],
        logical_key="b.general",
        display_name="B General",
        source_language_id=fr["id"],
    )
    category_b = await groups.create_category_variant(
        guild_id=GUILD_A,
        translation_group_id=group_b["id"],
        language_profile_id=fr["id"],
        discord_category_id=881000301,
    )
    channel_b = await groups.create_channel_variant(
        guild_id=GUILD_A,
        translation_group_id=group_b["id"],
        translation_channel_group_id=channel_group_b["id"],
        language_profile_id=fr["id"],
        discord_channel_id=881000302,
        translation_category_variant_id=category_b["id"],
    )

    with pytest.raises(Stage08NotFound):
        await topology.rename_channel_group(
            guild_id=GUILD_A,
            group_id=group_a["id"],
            channel_group_id=channel_group_b["id"],
            display_name="Compromised",
        )
    with pytest.raises(Stage08NotFound):
        await topology.unlink_variant(
            guild_id=GUILD_A,
            group_id=group_a["id"],
            variant_id=category_b["id"],
            variant_type="CATEGORY",
        )
    with pytest.raises(Stage08NotFound):
        await topology.unlink_variant(
            guild_id=GUILD_A,
            group_id=group_a["id"],
            variant_id=channel_b["id"],
            variant_type="CHANNEL",
        )
    with pytest.raises(Stage08NotFound):
        await topology.link_existing_variant(
            guild_id=GUILD_A,
            group_id=group_a["id"],
            language_id=fr["id"],
            variant_type="CHANNEL",
            discord_resource_id=881000303,
            confirmed_explicit_selection=True,
            channel_group_id=channel_group_b["id"],
        )

    preserved_channel_group = await groups.get_channel_group(
        guild_id=GUILD_A,
        translation_group_id=group_b["id"],
        channel_group_id=channel_group_b["id"],
    )
    preserved_category = await groups.get_variant(
        guild_id=GUILD_A,
        translation_group_id=group_b["id"],
        variant_id=category_b["id"],
        variant_type="CATEGORY",
    )
    preserved_channel = await groups.get_variant(
        guild_id=GUILD_A,
        translation_group_id=group_b["id"],
        variant_id=channel_b["id"],
        variant_type="CHANNEL",
    )
    assert preserved_channel_group["display_name"] == "B General"
    assert preserved_category["state"] == "ACTIVE"
    assert preserved_channel["state"] == "ACTIVE"


@pytest.mark.asyncio
async def test_route_replacement_cas_and_provider_ready_requires_verification(
    repositories: tuple[
        LanguageProfileRepository,
        ResourceLanguagePolicyRepository,
        TranslationGroupRepository,
        TranslationProviderBindingRepository,
        VisibilityScopeLanguageRepository,
    ],
) -> None:
    profiles, _, groups, providers, visibility = repositories
    topology = TranslationTopologyService(groups, providers, visibility)
    fr = await profiles.create(guild_id=GUILD_A, code="fr", display_name="French")
    en = await profiles.create(guild_id=GUILD_A, code="en", display_name="English")
    binding = await providers.create(
        guild_id=GUILD_A,
        provider_type="existing_translation_bot",
        provider_instance_key=f"ready-{uuid4()}",
        capabilities={"supports_custom": True},
    )
    await providers.set_status(
        guild_id=GUILD_A,
        binding_id=binding["id"],
        status="READY",
        verified=True,
    )
    group = await topology.create_group(
        guild_id=GUILD_A,
        name="Routes",
        root_kind="CHANNEL_SET",
        routing_mode="CUSTOM",
        language_ids=(fr["id"], en["id"]),
        visibility_scope_id=None,
        source_language_profile_id=None,
        provider_binding_id=binding["id"],
    )
    updated = await topology.replace_routes(
        guild_id=GUILD_A,
        group_id=group["id"],
        expected_version=1,
        topology=TranslationGroupTopology.CUSTOM,
        hub_language_id=None,
        custom_routes=((fr["id"], en["id"]),),
    )
    assert updated["version"] == 2 and len(updated["routes"]) == 1
    with pytest.raises(Stage08Conflict):
        await topology.replace_routes(
            guild_id=GUILD_A,
            group_id=group["id"],
            expected_version=1,
            topology=TranslationGroupTopology.CUSTOM,
            hub_language_id=None,
            custom_routes=((en["id"], fr["id"]),),
        )
    unverified_binding = await providers.create(
        guild_id=GUILD_A,
        provider_type="existing_translation_bot",
        provider_instance_key=f"manual-{uuid4()}",
        capabilities={},
    )
    with pytest.raises(ValueError, match="verification"):
        await providers.set_status(
            guild_id=GUILD_A,
            binding_id=unverified_binding["id"],
            status="READY",
            verified=False,
        )
    ready = await providers.set_status(
        guild_id=GUILD_A,
        binding_id=unverified_binding["id"],
        status="READY",
        verified=True,
    )
    assert ready["status"] == "READY" and ready["last_validated_at"] is not None


@pytest.mark.asyncio
async def test_gateway_delete_marks_only_the_exact_translation_variant_missing(
    repositories: tuple[
        LanguageProfileRepository,
        ResourceLanguagePolicyRepository,
        TranslationGroupRepository,
        TranslationProviderBindingRepository,
        VisibilityScopeLanguageRepository,
    ],
) -> None:
    profiles, _, groups, providers, visibility = repositories
    topology = TranslationTopologyService(groups, providers, visibility)
    fr = await profiles.create(guild_id=GUILD_A, code="fr", display_name="French")
    en = await profiles.create(guild_id=GUILD_A, code="en", display_name="English")
    group = await topology.create_group(
        guild_id=GUILD_A,
        name="Gateway truth",
        root_kind="CATEGORY_SET",
        routing_mode="HUB_AND_SPOKE",
        language_ids=(fr["id"], en["id"]),
        visibility_scope_id=None,
        source_language_profile_id=fr["id"],
        provider_binding_id=None,
    )
    deleted = await groups.create_category_variant(
        guild_id=GUILD_A,
        translation_group_id=group["id"],
        language_profile_id=fr["id"],
        discord_category_id=881000501,
    )
    preserved = await groups.create_category_variant(
        guild_id=GUILD_A,
        translation_group_id=group["id"],
        language_profile_id=en["id"],
        discord_category_id=881000502,
    )
    engine = create_database_engine(APP_URL, pool_size=1)
    try:
        runtime = RuntimeRepository(async_sessionmaker(engine, expire_on_commit=False))
        envelope = normalize_gateway_dispatch(
            {
                "op": 0,
                "s": 42,
                "t": "CHANNEL_DELETE",
                "d": {
                    "guild_id": str(GUILD_A),
                    "id": "881000501",
                    "type": 4,
                    "position": 1,
                },
            },
            discord_session_id="stage08-trusted-gateway",
        )
        assert envelope is not None
        assert await runtime.ingest_gateway_event(envelope)
        assert (
            await groups.get_variant(
                guild_id=GUILD_A,
                translation_group_id=group["id"],
                variant_id=deleted["id"],
                variant_type="CATEGORY",
            )
        )["state"] == "MISSING"
        assert (
            await groups.get_variant(
                guild_id=GUILD_A,
                translation_group_id=group["id"],
                variant_id=preserved["id"],
                variant_type="CATEGORY",
            )
        )["state"] == "ACTIVE"
    finally:
        await engine.dispose()
