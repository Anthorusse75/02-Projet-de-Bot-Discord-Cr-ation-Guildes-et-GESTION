from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

from did.infrastructure.database import create_database_engine, tenant_transaction
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    Stage08Conflict,
    TranslationGroupRepository,
    TranslationProviderBindingRepository,
    VisibilityScopeLanguageRepository,
)
from did.tenancy import TenantContext

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 880000001
GUILD_B = 880000002
USER_ID = 880000101
CLEANUP_STATEMENTS = (
    "DELETE FROM translation_channel_variants WHERE guild_id IN (:a,:b)",
    "DELETE FROM translation_category_variants WHERE guild_id IN (:a,:b)",
    "DELETE FROM translation_channel_groups WHERE guild_id IN (:a,:b)",
    "DELETE FROM translation_routes WHERE guild_id IN (:a,:b)",
    "DELETE FROM translation_group_languages WHERE guild_id IN (:a,:b)",
    "DELETE FROM translation_groups WHERE guild_id IN (:a,:b)",
    "DELETE FROM translation_provider_bindings WHERE guild_id IN (:a,:b)",
    "DELETE FROM visibility_scope_language_roles WHERE guild_id IN (:a,:b)",
    "DELETE FROM visibility_scopes WHERE guild_id IN (:a,:b)",
    "DELETE FROM member_visible_languages WHERE guild_id IN (:a,:b)",
    "DELETE FROM resource_language_policies WHERE guild_id IN (:a,:b)",
    "DELETE FROM language_profiles WHERE guild_id IN (:a,:b)",
)
RLS_COUNT_STATEMENTS = (
    "SELECT count(*) FROM translation_groups WHERE guild_id=:guild_id",
    "SELECT count(*) FROM translation_category_variants WHERE guild_id=:guild_id",
    "SELECT count(*) FROM translation_channel_groups WHERE guild_id=:guild_id",
    "SELECT count(*) FROM translation_channel_variants WHERE guild_id=:guild_id",
    "SELECT count(*) FROM translation_routes WHERE guild_id=:guild_id",
    "SELECT count(*) FROM translation_provider_bindings WHERE guild_id=:guild_id",
    "SELECT count(*) FROM visibility_scope_language_roles WHERE guild_id=:guild_id",
)


async def _insert_installation(connection: AsyncConnection, guild_id: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO guild_installations "
            "(guild_id,name,owner_id,installation_status) "
            "VALUES (:guild_id,:name,:owner_id,'ACTIVE') "
            "ON CONFLICT (guild_id) DO UPDATE SET name=EXCLUDED.name,owner_id=EXCLUDED.owner_id"
        ),
        {"guild_id": guild_id, "name": f"Stage 08 {guild_id}", "owner_id": USER_ID},
    )


@pytest.fixture(autouse=True)
async def database_setup() -> AsyncIterator[None]:
    engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), {"a": GUILD_A, "b": GUILD_B})
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id IN (:a,:b)"),
                {"a": GUILD_A, "b": GUILD_B},
            )
            await _insert_installation(connection, GUILD_A)
            await _insert_installation(connection, GUILD_B)
        yield
    finally:
        async with engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), {"a": GUILD_A, "b": GUILD_B})
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id IN (:a,:b)"),
                {"a": GUILD_A, "b": GUILD_B},
            )
        await engine.dispose()


@pytest.fixture
async def persistence_context() -> AsyncIterator[
    tuple[LanguageProfileRepository, TranslationGroupRepository]
]:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
    app_engine = create_database_engine(APP_URL, pool_size=2)
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM translation_channel_variants WHERE guild_id IN (:a,:b)"),
                {"a": GUILD_A, "b": GUILD_B},
            )
            await connection.execute(
                text("DELETE FROM translation_category_variants WHERE guild_id IN (:a,:b)"),
                {"a": GUILD_A, "b": GUILD_B},
            )
            await connection.execute(
                text("DELETE FROM translation_channel_groups WHERE guild_id IN (:a,:b)"),
                {"a": GUILD_A, "b": GUILD_B},
            )
            await connection.execute(
                text("DELETE FROM translation_routes WHERE guild_id IN (:a,:b)"),
                {"a": GUILD_A, "b": GUILD_B},
            )
            await connection.execute(
                text("DELETE FROM translation_groups WHERE guild_id IN (:a,:b)"),
                {"a": GUILD_A, "b": GUILD_B},
            )
            await connection.execute(
                text("DELETE FROM translation_provider_bindings WHERE guild_id IN (:a,:b)"),
                {"a": GUILD_A, "b": GUILD_B},
            )
            await connection.execute(
                text("DELETE FROM member_visible_languages WHERE guild_id IN (:a,:b)"),
                {"a": GUILD_A, "b": GUILD_B},
            )
            await connection.execute(
                text("DELETE FROM language_profiles WHERE guild_id IN (:a,:b)"),
                {"a": GUILD_A, "b": GUILD_B},
            )
            await _insert_installation(connection, GUILD_A)
            await _insert_installation(connection, GUILD_B)
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        yield LanguageProfileRepository(factory), TranslationGroupRepository(factory)
    finally:
        async with admin_engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), {"a": GUILD_A, "b": GUILD_B})
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id IN (:a,:b)"),
                {"a": GUILD_A, "b": GUILD_B},
            )
        await app_engine.dispose()
        await admin_engine.dispose()


@pytest.mark.asyncio
async def test_rls_and_member_language_isolation(
    persistence_context: tuple[LanguageProfileRepository, TranslationGroupRepository],
) -> None:
    languages, groups = persistence_context
    fr = await languages.create(guild_id=GUILD_A, code="fr", display_name="French")
    de = await languages.create(guild_id=GUILD_B, code="de", display_name="German")
    await languages.set_member_languages(
        guild_id=GUILD_A, discord_user_id=USER_ID, language_profile_ids=(fr["id"],)
    )
    await languages.set_member_languages(
        guild_id=GUILD_B, discord_user_id=USER_ID, language_profile_ids=(de["id"],)
    )
    group_a = await groups.create(
        guild_id=GUILD_A,
        name="A",
        root_kind="CHANNEL_SET",
        routing_mode="HUB_AND_SPOKE",
        group_id=uuid4(),
    )
    group_b = await groups.create(
        guild_id=GUILD_B,
        name="B",
        root_kind="CHANNEL_SET",
        routing_mode="HUB_AND_SPOKE",
        group_id=uuid4(),
    )
    assert [row["code"] for row in await languages.list_profiles(GUILD_A)] == ["fr"]
    assert [row["code"] for row in await languages.list_profiles(GUILD_B)] == ["de"]
    assert [
        row["language_profile_id"] for row in await languages.member_languages(GUILD_A, USER_ID)
    ] == [fr["id"]]
    assert [
        row["language_profile_id"] for row in await languages.member_languages(GUILD_B, USER_ID)
    ] == [de["id"]]
    with pytest.raises(LookupError):
        await groups.get(GUILD_B, UUID(str(group_a["id"])))
    assert group_a["id"] != group_b["id"]


@pytest.mark.asyncio
async def test_composite_foreign_keys_reject_cross_tenant_references() -> None:
    engine = create_database_engine(APP_URL, pool_size=2)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    languages = LanguageProfileRepository(factory)
    groups = TranslationGroupRepository(factory)
    providers = TranslationProviderBindingRepository(factory)
    try:
        lang_a = await languages.create(guild_id=GUILD_A, code="en", display_name="English")
        lang_b = await languages.create(guild_id=GUILD_B, code="es", display_name="Spanish")
        group_a = await groups.create(
            guild_id=GUILD_A,
            name="A",
            root_kind="CHANNEL_SET",
            routing_mode="HUB_AND_SPOKE",
            group_id=uuid4(),
        )
        group_b = await groups.create(
            guild_id=GUILD_B,
            name="B",
            root_kind="CHANNEL_SET",
            routing_mode="HUB_AND_SPOKE",
            group_id=uuid4(),
        )
        await groups.add_language(
            guild_id=GUILD_A, translation_group_id=group_a["id"], language_profile_id=lang_a["id"]
        )
        with pytest.raises(DBAPIError):
            await groups.add_language(
                guild_id=GUILD_A,
                translation_group_id=group_a["id"],
                language_profile_id=lang_b["id"],
            )
        provider_b = await providers.create(
            guild_id=GUILD_B,
            provider_type="existing_translation_bot",
            provider_instance_key=f"b-{uuid4()}",
            capabilities={},
        )
        with pytest.raises(DBAPIError):
            await groups.create(
                guild_id=GUILD_A,
                name="cross-provider",
                root_kind="CHANNEL_SET",
                routing_mode="HUB_AND_SPOKE",
                provider_binding_id=provider_b["id"],
            )
        assert group_b["guild_id"] == GUILD_B
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_rls_hides_variants_routes_provider_and_scope_bindings() -> None:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
    app_engine = create_database_engine(APP_URL, pool_size=1)
    factory = async_sessionmaker(app_engine, expire_on_commit=False)
    languages = LanguageProfileRepository(factory)
    groups = TranslationGroupRepository(factory)
    providers = TranslationProviderBindingRepository(factory)
    scope_id = uuid4()
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO visibility_scopes "
                    "(id,guild_id,scope_type,scope_key,name,config_json) "
                    "VALUES (:id,:guild_id,'GLOBAL',:scope_key,'B scope','{}'::jsonb)"
                ),
                {"id": scope_id, "guild_id": GUILD_B, "scope_key": f"b-{scope_id}"},
            )
        language_b = await languages.create(guild_id=GUILD_B, code="it", display_name="Italian")
        destination_b = await languages.create(guild_id=GUILD_B, code="ja", display_name="Japanese")
        provider_b = await providers.create(
            guild_id=GUILD_B,
            provider_type="existing_translation_bot",
            provider_instance_key=f"b-{uuid4()}",
            capabilities={},
        )
        group_b = await groups.create(
            guild_id=GUILD_B,
            name="B",
            root_kind="CHANNEL_SET",
            routing_mode="HUB_AND_SPOKE",
            provider_binding_id=provider_b["id"],
        )
        await groups.add_language(
            guild_id=GUILD_B,
            translation_group_id=group_b["id"],
            language_profile_id=language_b["id"],
        )
        channel_group_b = await groups.create_channel_group(
            guild_id=GUILD_B,
            translation_group_id=group_b["id"],
            logical_key=f"b-{uuid4()}",
        )
        category_b = await groups.create_category_variant(
            guild_id=GUILD_B,
            translation_group_id=group_b["id"],
            language_profile_id=language_b["id"],
            discord_category_id=880000201,
        )
        await groups.create_channel_variant(
            guild_id=GUILD_B,
            translation_group_id=group_b["id"],
            translation_channel_group_id=channel_group_b["id"],
            language_profile_id=language_b["id"],
            discord_channel_id=880000202,
            translation_category_variant_id=category_b["id"],
        )
        await groups.create_route(
            guild_id=GUILD_B,
            translation_group_id=group_b["id"],
            source_language_profile_id=language_b["id"],
            destination_language_profile_id=destination_b["id"],
        )
        await VisibilityScopeLanguageRepository(factory).create(
            guild_id=GUILD_B,
            visibility_scope_id=scope_id,
            language_profile_id=language_b["id"],
            discord_role_id=880000203,
        )
        async with tenant_transaction(factory, TenantContext(GUILD_A)) as session:
            for statement in RLS_COUNT_STATEMENTS:
                result = await session.execute(
                    text(statement),
                    {"guild_id": GUILD_A},
                )
                assert result.scalar_one() == 0
        async with tenant_transaction(factory, TenantContext(GUILD_A)) as session:
            await session.execute(
                text("UPDATE translation_groups SET name='forbidden' WHERE guild_id=:guild_id"),
                {"guild_id": GUILD_B},
            )
            await session.execute(
                text("DELETE FROM translation_routes WHERE guild_id=:guild_id"),
                {"guild_id": GUILD_B},
            )
        async with admin_engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT name FROM translation_groups WHERE guild_id=:guild_id"),
                    {"guild_id": GUILD_B},
                )
                == "B"
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM translation_routes WHERE guild_id=:guild_id"),
                    {"guild_id": GUILD_B},
                )
                == 1
            )
    finally:
        await app_engine.dispose()
        await admin_engine.dispose()


@pytest.mark.asyncio
async def test_database_uniqueness_constraints_resolve_concurrent_creates() -> None:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
    app_engine = create_database_engine(APP_URL, pool_size=4)
    factory = async_sessionmaker(app_engine, expire_on_commit=False)
    languages = LanguageProfileRepository(factory)
    groups = TranslationGroupRepository(factory)
    providers = TranslationProviderBindingRepository(factory)
    scope_repository = VisibilityScopeLanguageRepository(factory)
    scope_id = uuid4()
    try:
        duplicate_language_results = await asyncio.gather(
            languages.create(guild_id=GUILD_A, code="pt", display_name="Portuguese"),
            languages.create(guild_id=GUILD_A, code="pt", display_name="Portuguese"),
            return_exceptions=True,
        )
        assert sum(isinstance(result, dict) for result in duplicate_language_results) == 1
        assert sum(isinstance(result, DBAPIError) for result in duplicate_language_results) == 1

        language_a = await languages.create(guild_id=GUILD_A, code="nl", display_name="Dutch")
        duplicate_member_results = await asyncio.gather(
            languages.add_member_language(
                guild_id=GUILD_A,
                discord_user_id=USER_ID,
                language_profile_id=language_a["id"],
            ),
            languages.add_member_language(
                guild_id=GUILD_A,
                discord_user_id=USER_ID,
                language_profile_id=language_a["id"],
            ),
            return_exceptions=True,
        )
        assert sum(result is None for result in duplicate_member_results) == 1
        assert sum(isinstance(result, DBAPIError) for result in duplicate_member_results) == 1

        language_b = await languages.create(guild_id=GUILD_A, code="sv", display_name="Swedish")
        group = await groups.create(
            guild_id=GUILD_A,
            name="Concurrency",
            root_kind="CHANNEL_SET",
            routing_mode="HUB_AND_SPOKE",
        )
        await groups.add_language(
            guild_id=GUILD_A,
            translation_group_id=group["id"],
            language_profile_id=language_a["id"],
        )
        await groups.add_language(
            guild_id=GUILD_A,
            translation_group_id=group["id"],
            language_profile_id=language_b["id"],
        )
        duplicate_route_results = await asyncio.gather(
            groups.create_route(
                guild_id=GUILD_A,
                translation_group_id=group["id"],
                source_language_profile_id=language_a["id"],
                destination_language_profile_id=language_b["id"],
            ),
            groups.create_route(
                guild_id=GUILD_A,
                translation_group_id=group["id"],
                source_language_profile_id=language_a["id"],
                destination_language_profile_id=language_b["id"],
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, dict) for result in duplicate_route_results) == 1
        assert sum(isinstance(result, DBAPIError) for result in duplicate_route_results) == 1

        async with admin_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO visibility_scopes "
                    "(id,guild_id,scope_type,scope_key,name,config_json) "
                    "VALUES (:id,:guild_id,'GLOBAL',:scope_key,'Concurrency','{}'::jsonb)"
                ),
                {"id": scope_id, "guild_id": GUILD_A, "scope_key": f"c-{scope_id}"},
            )
        duplicate_binding_results = await asyncio.gather(
            scope_repository.create(
                guild_id=GUILD_A,
                visibility_scope_id=scope_id,
                language_profile_id=language_a["id"],
                discord_role_id=880000301,
            ),
            scope_repository.create(
                guild_id=GUILD_A,
                visibility_scope_id=scope_id,
                language_profile_id=language_a["id"],
                discord_role_id=880000301,
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, dict) for result in duplicate_binding_results) == 1
        assert sum(isinstance(result, DBAPIError) for result in duplicate_binding_results) == 1

        duplicate_provider_results = await asyncio.gather(
            providers.create(
                guild_id=GUILD_A,
                provider_type="existing_translation_bot",
                provider_instance_key="same-instance",
                capabilities={},
            ),
            providers.create(
                guild_id=GUILD_A,
                provider_type="existing_translation_bot",
                provider_instance_key="same-instance",
                capabilities={},
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, dict) for result in duplicate_provider_results) == 1
        assert sum(isinstance(result, DBAPIError) for result in duplicate_provider_results) == 1
    finally:
        await app_engine.dispose()
        await admin_engine.dispose()


@pytest.mark.asyncio
async def test_translation_group_cas_allows_one_update_only() -> None:
    engine = create_database_engine(APP_URL, pool_size=4)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    groups = TranslationGroupRepository(factory)
    try:
        group = await groups.create(
            guild_id=GUILD_A,
            name="CAS",
            root_kind="CHANNEL_SET",
            routing_mode="HUB_AND_SPOKE",
            group_id=uuid4(),
        )
        results = await asyncio.gather(
            groups.update_name(
                guild_id=GUILD_A, group_id=group["id"], expected_version=1, name="first"
            ),
            groups.update_name(
                guild_id=GUILD_A, group_id=group["id"], expected_version=1, name="second"
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, dict) for result in results) == 1
        assert sum(isinstance(result, Stage08Conflict) for result in results) == 1
    finally:
        await engine.dispose()
