import json
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from did.infrastructure.database import (
    create_database_engine,
    create_session_factory,
    tenant_transaction,
)
from did.tenancy import TenantContext, UserContext

pytestmark = [pytest.mark.integration, pytest.mark.security]

APP_URL = os.environ.get(
    "DID_DATABASE_URL",
    "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test",
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
USER_A = 101010101010101010
USER_B = 202020202020202020
GUILD_A = 303030303030303030
GUILD_B = 404040404040404040


async def _seed_stage02() -> None:
    engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE guild_role_bindings, guild_user_access, guild_installations, "
                    "user_ui_preferences, discord_oauth_grants, users CASCADE"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO users (discord_user_id, username) VALUES "
                    "(:user_a, 'user-a'), (:user_b, 'user-b')"
                ),
                {"user_a": USER_A, "user_b": USER_B},
            )
            await connection.execute(
                text(
                    "INSERT INTO user_ui_preferences "
                    "(discord_user_id, ui_locale_override_code) VALUES "
                    "(:user_a, 'fr'), (:user_b, 'de')"
                ),
                {"user_a": USER_A, "user_b": USER_B},
            )
            await connection.execute(
                text(
                    "INSERT INTO guild_installations "
                    "(guild_id, name, installation_status) VALUES "
                    "(:guild_a, 'Guild A', 'ACTIVE'), (:guild_b, 'Guild B', 'ACTIVE')"
                ),
                {"guild_a": GUILD_A, "guild_b": GUILD_B},
            )
            await connection.execute(
                text(
                    "INSERT INTO guild_user_access "
                    "(guild_id, discord_user_id, platform_role, status, created_by) VALUES "
                    "(:guild_a, :user_a, 'OWNER', 'ACTIVE', :user_a), "
                    "(:guild_b, :user_b, 'OWNER', 'ACTIVE', :user_b)"
                ),
                {
                    "guild_a": GUILD_A,
                    "guild_b": GUILD_B,
                    "user_a": USER_A,
                    "user_b": USER_B,
                },
            )
    finally:
        await engine.dispose()


async def test_user_control_plane_and_guild_rls_are_independently_fail_closed() -> None:
    await _seed_stage02()
    engine = create_database_engine(APP_URL, pool_size=1)
    factory = create_session_factory(engine)
    try:
        async with tenant_transaction(factory, UserContext(USER_A)) as session:
            locales = (
                (
                    await session.execute(
                        text("SELECT ui_locale_override_code FROM user_ui_preferences")
                    )
                )
                .scalars()
                .all()
            )
            assert locales == ["fr"]
        async with tenant_transaction(factory, UserContext(USER_B)) as session:
            locales = (
                (
                    await session.execute(
                        text("SELECT ui_locale_override_code FROM user_ui_preferences")
                    )
                )
                .scalars()
                .all()
            )
            assert locales == ["de"]
        async with tenant_transaction(factory, TenantContext(GUILD_A, USER_A)) as session:
            assert await session.scalar(text("SELECT count(*) FROM guild_installations")) == 1
            assert await session.scalar(text("SELECT count(*) FROM guild_user_access")) == 1
        async with tenant_transaction(factory, TenantContext(GUILD_B, USER_B)) as session:
            assert await session.scalar(text("SELECT count(*) FROM guild_installations")) == 1
            assert await session.scalar(text("SELECT count(*) FROM guild_user_access")) == 1
        async with tenant_transaction(factory, None) as session:
            assert await session.scalar(text("SELECT count(*) FROM guild_installations")) == 0
            assert await session.scalar(text("SELECT count(*) FROM user_ui_preferences")) == 0
    finally:
        await engine.dispose()


async def test_cross_tenant_write_and_missing_composite_parent_are_rejected() -> None:
    await _seed_stage02()
    engine = create_database_engine(APP_URL, pool_size=1)
    factory = create_session_factory(engine)
    try:
        with pytest.raises(DBAPIError):
            async with tenant_transaction(factory, TenantContext(GUILD_A, USER_A)) as session:
                await session.execute(
                    text(
                        "INSERT INTO guild_role_bindings "
                        "(guild_id, discord_role_id, dashboard_role, created_by) "
                        "VALUES (:guild_b, 55, 'READ_ONLY', :user_a)"
                    ),
                    {"guild_b": GUILD_B, "user_a": USER_A},
                )
        with pytest.raises(DBAPIError):
            async with tenant_transaction(factory, TenantContext(999, USER_A)) as session:
                await session.execute(
                    text(
                        "INSERT INTO guild_role_bindings "
                        "(guild_id, discord_role_id, dashboard_role, created_by) "
                        "VALUES (999, 56, 'READ_ONLY', :user_a)"
                    ),
                    {"user_a": USER_A},
                )
    finally:
        await engine.dispose()


async def test_scoped_rbac_keys_allow_siblings_and_enforce_canonical_pairs() -> None:
    await _seed_stage02()
    engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO guild_user_access "
                    "(guild_id, discord_user_id, platform_role, status, scope_kind, scope_id, "
                    "created_by) VALUES "
                    "(:guild, :user, 'TENANT_ADMIN', 'ACTIVE', 'LOGICAL_GROUP', 'alpha', :user), "
                    "(:guild, :user, 'READ_ONLY', 'ACTIVE', 'LOGICAL_GROUP', 'beta', :user)"
                ),
                {"guild": GUILD_A, "user": USER_A},
            )
            await connection.execute(
                text(
                    "INSERT INTO guild_role_bindings "
                    "(guild_id, discord_role_id, dashboard_role, scope_kind, scope_id, created_by) "
                    "VALUES "
                    "(:guild, 88, 'TENANT_ADMIN', 'LOGICAL_GROUP', 'alpha', :user), "
                    "(:guild, 88, 'READ_ONLY', 'LOGICAL_GROUP', 'beta', :user)"
                ),
                {"guild": GUILD_A, "user": USER_A},
            )
            access_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM guild_user_access "
                    "WHERE guild_id=:guild AND discord_user_id=:user"
                ),
                {"guild": GUILD_A, "user": USER_A},
            )
            binding_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM guild_role_bindings "
                    "WHERE guild_id=:guild AND discord_role_id=88"
                ),
                {"guild": GUILD_A},
            )
            primary_key = await connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname='pk_guild_user_access'"
                )
            )
            constraints = set(
                (
                    await connection.execute(
                        text(
                            "SELECT conname FROM pg_constraint WHERE conname IN "
                            "('fk_guild_user_access_user', "
                            "'fk_guild_user_access_installation', "
                            "'fk_guild_role_bindings_installation', "
                            "'uq_guild_installations_app')"
                        )
                    )
                )
                .scalars()
                .all()
            )
            indexes = set(
                (
                    await connection.execute(
                        text(
                            "SELECT indexname FROM pg_indexes WHERE indexname IN "
                            "('ix_guild_user_access_user', 'ix_installations_status', "
                            "'ix_oauth_grants_active')"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert access_count == 3
        assert binding_count == 2
        assert primary_key == ("PRIMARY KEY (guild_id, discord_user_id, scope_kind, scope_id)")
        assert constraints == {
            "fk_guild_user_access_user",
            "fk_guild_user_access_installation",
            "fk_guild_role_bindings_installation",
            "uq_guild_installations_app",
        }
        assert indexes == {
            "ix_guild_user_access_user",
            "ix_installations_status",
            "ix_oauth_grants_active",
        }

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO guild_user_access "
                        "(guild_id, discord_user_id, platform_role, status, scope_kind, scope_id, "
                        "created_by) VALUES "
                        "(:guild, :user, 'READ_ONLY', 'ACTIVE', 'GUILD', 'alpha', :user)"
                    ),
                    {"guild": GUILD_A, "user": USER_A},
                )
        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO guild_role_bindings "
                        "(guild_id, discord_role_id, dashboard_role, scope_kind, scope_id, "
                        "created_by) VALUES "
                        "(:guild, 89, 'READ_ONLY', 'VISIBILITY_SCOPE', '*', :user)"
                    ),
                    {"guild": GUILD_A, "user": USER_A},
                )
    finally:
        await engine.dispose()


async def test_oauth_ciphertext_columns_do_not_store_plaintext() -> None:
    await _seed_stage02()
    admin = create_database_engine(ADMIN_URL, pool_size=1)
    access = b"encrypted-access-envelope"
    refresh = b"encrypted-refresh-envelope"
    try:
        async with admin.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO discord_oauth_grants "
                    "(discord_user_id, scopes_json, access_token_ciphertext, access_token_nonce, "
                    "access_token_expires_at, refresh_token_ciphertext, refresh_token_nonce, "
                    "key_version) "
                    "VALUES (:user_id, CAST(:scopes AS jsonb), :access, :nonce_a, now(), "
                    ":refresh, :nonce_r, 1)"
                ),
                {
                    "user_id": USER_A,
                    "scopes": json.dumps(["guilds", "identify"]),
                    "access": access,
                    "refresh": refresh,
                    "nonce_a": b"a" * 12,
                    "nonce_r": b"r" * 12,
                },
            )
            row = (
                await connection.execute(
                    text(
                        "SELECT access_token_ciphertext, refresh_token_ciphertext "
                        "FROM discord_oauth_grants WHERE discord_user_id=:user_id"
                    ),
                    {"user_id": USER_A},
                )
            ).one()
        assert bytes(row[0]) == access
        assert bytes(row[1]) == refresh
        assert b"plaintext" not in bytes(row[0]) + bytes(row[1])
    finally:
        await admin.dispose()


@pytest.mark.failure_injection
async def test_rbac_transaction_rolls_back_without_partial_binding() -> None:
    await _seed_stage02()
    engine = create_database_engine(APP_URL, pool_size=1)
    factory = create_session_factory(engine)
    try:
        with pytest.raises(RuntimeError, match="injected rollback"):
            async with tenant_transaction(factory, TenantContext(GUILD_A, USER_A)) as session:
                await session.execute(
                    text(
                        "INSERT INTO guild_role_bindings "
                        "(guild_id, discord_role_id, dashboard_role, created_by) "
                        "VALUES (:guild_id, 77, 'READ_ONLY', :actor)"
                    ),
                    {"guild_id": GUILD_A, "actor": USER_A},
                )
                raise RuntimeError("injected rollback")
        async with tenant_transaction(factory, TenantContext(GUILD_A, USER_A)) as session:
            count = await session.scalar(
                text("SELECT count(*) FROM guild_role_bindings WHERE discord_role_id=77")
            )
            assert count == 0
    finally:
        await engine.dispose()
