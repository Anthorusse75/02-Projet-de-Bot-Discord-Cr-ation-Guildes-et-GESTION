from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from did.domain.scopes import ScopeType
from did.infrastructure.database import (
    create_database_engine,
    create_session_factory,
    tenant_transaction,
)
from did.infrastructure.stage04_repository import Stage04NotFound, Stage04Repository
from did.tenancy import TenantContext

pytestmark = [pytest.mark.integration, pytest.mark.security]

APP_URL = os.environ.get(
    "DID_DATABASE_URL",
    "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test",
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 530303030303030301
GUILD_B = 530303030303030302
OWNER_A = 530303030303030303
OWNER_B = 530303030303030304
CHANNEL_A = 530303030303030311
CHANNEL_B = 530303030303030312
ROLE_A = 530303030303030321
ROLE_B = 530303030303030322
ACTOR = 530303030303030331
NOW = datetime(2026, 8, 17, tzinfo=UTC)


async def seed_stage04() -> None:
    engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE users, guild_installations CASCADE"))
            await connection.execute(
                text("INSERT INTO users (discord_user_id, username) VALUES (:actor, 'actor')"),
                {"actor": ACTOR},
            )
            await connection.execute(
                text(
                    "INSERT INTO guild_installations "
                    "(guild_id,name,owner_id,installation_status,last_gateway_seen_at) VALUES "
                    "(:a,'Guild A',:owner_a,'ACTIVE',:now),"
                    "(:b,'Guild B',:owner_b,'ACTIVE',:now)"
                ),
                {
                    "a": GUILD_A,
                    "b": GUILD_B,
                    "owner_a": OWNER_A,
                    "owner_b": OWNER_B,
                    "now": NOW,
                },
            )
            for guild_id, role_id, channel_id in (
                (GUILD_A, ROLE_A, CHANNEL_A),
                (GUILD_B, ROLE_B, CHANNEL_B),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO discord_roles_cache "
                        "(guild_id,role_id,name,position,permissions_bits,managed,color,hoist,"
                        "mentionable,raw_json,last_gateway_seen_at) VALUES "
                        "(:guild,:everyone,'@everyone',0,1024,false,0,false,false,'{}',:now),"
                        "(:guild,:role,'role',1,2048,false,0,false,false,'{}',:now)"
                    ),
                    {
                        "guild": guild_id,
                        "everyone": guild_id,
                        "role": role_id,
                        "now": NOW,
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO discord_channels_cache "
                        "(guild_id,channel_id,type,name,parent_id,position,nsfw,last_full_payload,"
                        "observability_state,freshness_state,last_full_observed_at,"
                        "last_gateway_seen_at) VALUES "
                        "(:guild,:channel,0,'channel',NULL,0,false,'{}','VISIBLE','FRESH',:now,:now)"
                    ),
                    {"guild": guild_id, "channel": channel_id, "now": NOW},
                )
                await connection.execute(
                    text(
                        "INSERT INTO discord_cache_coverage "
                        "(guild_id,coverage_mode,freshness_state,known_channels,visible_channels,"
                        "known_roles,last_gateway_event_at,gateway_continuity) VALUES "
                        "(:guild,'FULL','FRESH',1,1,2,:now,'CONNECTED')"
                    ),
                    {"guild": guild_id, "now": NOW},
                )
                await connection.execute(
                    text(
                        "INSERT INTO discord_member_authorization_cache "
                        "(guild_id,discord_user_id,role_ids,source,validity,observed_at) VALUES "
                        "(:guild,:actor,:roles,'TARGETED_REST','FRESH',:now)"
                    ),
                    {"guild": guild_id, "actor": ACTOR, "roles": [role_id], "now": NOW},
                )
    finally:
        await engine.dispose()


async def test_batch_snapshot_and_local_crud_are_tenant_isolated_and_audited() -> None:
    await seed_stage04()
    engine = create_database_engine(APP_URL, pool_size=2)
    factory = create_session_factory(engine)
    repository = Stage04Repository(factory)
    try:
        snapshot, actor = await repository.guild_snapshot(GUILD_A, ACTOR)
        assert [item.role_id for item in snapshot.roles] == [GUILD_A, ROLE_A]
        assert [item.channel_id for item in snapshot.channels] == [CHANNEL_A]
        assert actor.role_ids == (ROLE_A,)

        group_id = await repository.create_logical_group(
            guild_id=GUILD_A,
            actor_id=ACTOR,
            name="Alpha",
            slug="alpha",
            description=None,
            metadata={"kind": "did-only"},
            resources=(
                {
                    "resource_type": "CHANNEL",
                    "discord_resource_id": str(CHANNEL_A),
                    "semantic_role": "discussion",
                },
            ),
        )
        groups_a = await repository.list_logical_groups(GUILD_A)
        groups_b = await repository.list_logical_groups(GUILD_B)
        assert groups_a[0]["id"] == group_id
        assert groups_a[0]["resources"][0]["discord_channel_id"] == CHANNEL_A
        assert groups_b == []

        await repository.update_logical_group(
            guild_id=GUILD_A,
            group_id=group_id,
            actor_id=ACTOR,
            name="Alpha updated",
            description="local DID abstraction",
            metadata={},
            resources=(
                {
                    "resource_type": "ROLE",
                    "discord_resource_id": str(ROLE_A),
                    "semantic_role": "staff",
                },
            ),
        )
        updated = (await repository.list_logical_groups(GUILD_A))[0]
        assert updated["version"] == 2
        assert updated["resources"][0]["discord_role_id"] == ROLE_A

        scope_id = await repository.create_visibility_scope(
            guild_id=GUILD_A,
            actor_id=ACTOR,
            scope_type=ScopeType.LOGICAL_GROUP,
            scope_key="alpha",
            name="Alpha",
            logical_group_id=group_id,
            config={},
            rules=(
                {
                    "rule_type": "DISCORD_ROLE",
                    "config": {"role_ids": [ROLE_A]},
                    "priority": 1,
                    "status": "ACTIVE",
                },
            ),
            explicit_member_ids=(ACTOR,),
        )
        scopes = await repository.list_visibility_scopes(GUILD_A)
        assert scopes[0][0].id == scope_id
        assert scopes[0][1][0].config == {"role_ids": [ROLE_A]}
        assert scopes[0][2] == frozenset({ACTOR})

        async with tenant_transaction(factory, TenantContext(GUILD_A, ACTOR)) as session:
            assert await session.scalar(text("SELECT count(*) FROM logical_groups")) == 1
            assert await session.scalar(text("SELECT count(*) FROM visibility_scopes")) == 1
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM internal_audit_events WHERE event_type LIKE "
                        "'LOGICAL_GROUP_%' OR event_type LIKE 'VISIBILITY_SCOPE_%'"
                    )
                )
                == 3
            )
        async with tenant_transaction(factory, TenantContext(GUILD_B, ACTOR)) as session:
            assert await session.scalar(text("SELECT count(*) FROM logical_groups")) == 0
            assert await session.scalar(text("SELECT count(*) FROM visibility_scopes")) == 0
    finally:
        await engine.dispose()


async def test_cross_guild_resources_duplicate_targets_and_rls_writes_are_rejected() -> None:
    await seed_stage04()
    engine = create_database_engine(APP_URL, pool_size=1)
    factory = create_session_factory(engine)
    repository = Stage04Repository(factory)
    try:
        with pytest.raises(Stage04NotFound):
            await repository.create_logical_group(
                guild_id=GUILD_A,
                actor_id=ACTOR,
                name="Foreign",
                slug="foreign",
                description=None,
                metadata={},
                resources=(
                    {
                        "resource_type": "CHANNEL",
                        "discord_resource_id": str(CHANNEL_B),
                    },
                ),
            )
        with pytest.raises(IntegrityError):
            await repository.create_logical_group(
                guild_id=GUILD_A,
                actor_id=ACTOR,
                name="Duplicate",
                slug="duplicate",
                description=None,
                metadata={},
                resources=(
                    {
                        "resource_type": "CHANNEL",
                        "discord_resource_id": str(CHANNEL_A),
                    },
                    {
                        "resource_type": "CHANNEL",
                        "discord_resource_id": str(CHANNEL_A),
                    },
                ),
            )
        with pytest.raises(Stage04NotFound):
            await repository.create_visibility_scope(
                guild_id=GUILD_A,
                actor_id=ACTOR,
                scope_type=ScopeType.PROJECT,
                scope_key="foreign-role",
                name="Foreign role",
                logical_group_id=None,
                config={},
                rules=(
                    {
                        "rule_type": "DISCORD_ROLE",
                        "config": {"role_ids": [ROLE_B]},
                        "priority": 1,
                        "status": "ACTIVE",
                    },
                ),
                explicit_member_ids=(),
            )
        with pytest.raises(DBAPIError):
            async with tenant_transaction(factory, TenantContext(GUILD_A, ACTOR)) as session:
                await session.execute(
                    text(
                        "INSERT INTO logical_groups "
                        "(id,guild_id,name,slug,metadata_json) VALUES "
                        "(:id,:guild_b,'Injected','injected','{}')"
                    ),
                    {"id": uuid4(), "guild_b": GUILD_B},
                )
    finally:
        await engine.dispose()
