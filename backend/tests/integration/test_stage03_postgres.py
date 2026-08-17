import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from did.application.discord_runtime import normalize_gateway_dispatch
from did.domain.discord_runtime import CHANNEL_OBFUSCATED_FLAG, WorkloadJob, WorkloadPriority
from did.infrastructure.database import (
    create_database_engine,
    create_session_factory,
    tenant_transaction,
)
from did.infrastructure.runtime_repository import RuntimeRepository
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
GUILD_A = 130303030303030301
GUILD_B = 130303030303030302
CHANNEL_A = 130303030303030311
CHANNEL_B = 130303030303030312
ACTOR = 130303030303030321


def dispatch(
    event_type: str,
    data: dict[str, object],
    *,
    sequence: int,
    session_id: str = "stage03-session-a",
):
    envelope = normalize_gateway_dispatch(
        {"op": 0, "s": sequence, "t": event_type, "d": data},
        discord_session_id=session_id,
        received_at=datetime.now(UTC),
    )
    assert envelope is not None
    return envelope


def channel_payload(
    guild_id: int,
    channel_id: int,
    name: str,
    *,
    flags: int = 0,
    overwrites: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "guild_id": str(guild_id),
        "id": str(channel_id),
        "type": 0,
        "position": 1,
        "parent_id": None,
        "name": name,
        "topic": f"topic-{name}",
        "nsfw": False,
        "flags": flags,
        "permission_overwrites": overwrites or [],
    }


async def reset_runtime() -> None:
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
                text("INSERT INTO users (discord_user_id, username) VALUES (:actor, 'actor')"),
                {"actor": ACTOR},
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
                    "(:guild_a, :actor, 'OWNER', 'ACTIVE', :actor)"
                ),
                {"actor": ACTOR, "guild_a": GUILD_A},
            )
    finally:
        await engine.dispose()


async def test_gateway_projection_dedup_order_session_obfuscation_and_coverage() -> None:
    await reset_runtime()
    engine = create_database_engine(APP_URL, pool_size=2)
    repository = RuntimeRepository(create_session_factory(engine))
    try:
        created = dispatch(
            "CHANNEL_CREATE",
            channel_payload(
                GUILD_A,
                CHANNEL_A,
                "reliable-name",
                overwrites=[{"id": str(GUILD_A), "type": 0, "allow": "0", "deny": "1024"}],
            ),
            sequence=10,
        )
        assert await repository.ingest_gateway_event(created) is True
        duplicate = dispatch(
            "CHANNEL_CREATE",
            channel_payload(GUILD_A, CHANNEL_A, "duplicate-must-not-apply"),
            sequence=10,
        )
        assert await repository.ingest_gateway_event(duplicate) is False

        older = dispatch(
            "CHANNEL_UPDATE",
            channel_payload(GUILD_A, CHANNEL_A, "older-must-not-apply"),
            sequence=9,
        )
        assert await repository.ingest_gateway_event(older) is True
        rows = await repository.channels(GUILD_A, ACTOR, include_hidden_deleted=True)
        assert rows[0]["name"] == "reliable-name"

        new_session = dispatch(
            "CHANNEL_UPDATE",
            channel_payload(
                GUILD_A,
                CHANNEL_A,
                "new-session-state",
                overwrites=[{"id": str(GUILD_A), "type": 0, "allow": "0", "deny": "1024"}],
            ),
            sequence=1,
            session_id="stage03-session-b",
        )
        assert await repository.ingest_gateway_event(new_session) is True
        obfuscated = dispatch(
            "CHANNEL_UPDATE",
            channel_payload(
                GUILD_A,
                CHANNEL_A,
                "___hidden___",
                flags=CHANNEL_OBFUSCATED_FLAG,
                overwrites=[{"id": str(GUILD_A), "type": 0, "allow": "0", "deny": "1024"}],
            ),
            sequence=2,
            session_id="stage03-session-b",
        )
        assert await repository.ingest_gateway_event(obfuscated) is True
        rows = await repository.channels(GUILD_A, ACTOR, include_hidden_deleted=True)
        assert rows[0]["name"] == "new-session-state"
        assert rows[0]["observability_state"] == "OBFUSCATED"
        assert rows[0]["is_obfuscated"] is True

        async with tenant_transaction(
            create_session_factory(engine), TenantContext(GUILD_A, ACTOR)
        ) as session:
            assert await session.scalar(text("SELECT count(*) FROM discord_gateway_inbox")) == 4
            assert await session.scalar(text("SELECT count(*) FROM channel_overwrites_cache")) == 1
            coverage = (
                (
                    await session.execute(
                        text(
                            "SELECT known_channels, obfuscated_channels, freshness_state "
                            "FROM discord_cache_coverage"
                        )
                    )
                )
                .mappings()
                .one()
            )
            assert dict(coverage) == {
                "known_channels": 1,
                "obfuscated_channels": 1,
                "freshness_state": "FRESH",
            }
    finally:
        await engine.dispose()


async def test_http_omission_is_access_loss_then_local_purge_and_reobservation() -> None:
    await reset_runtime()
    engine = create_database_engine(APP_URL, pool_size=2)
    repository = RuntimeRepository(create_session_factory(engine))
    try:
        await repository.ingest_gateway_event(
            dispatch(
                "CHANNEL_CREATE",
                channel_payload(GUILD_A, CHANNEL_A, "never-false-delete"),
                sequence=1,
            )
        )
        await repository.apply_rest_channel_snapshot(
            guild_id=GUILD_A,
            channels=[],
            correlation_id=uuid4(),
        )
        row = (await repository.channels(GUILD_A, ACTOR, include_hidden_deleted=True))[0]
        assert row["observability_state"] == "ACCESS_LOST"
        assert row["deleted_confirmed_at"] is None
        assert row["name"] == "never-false-delete"

        with pytest.raises(ValueError, match="explicit deletion confirmation"):
            await repository.purge_channels(
                guild_id=GUILD_A,
                actor_user_id=ACTOR,
                channel_ids=[CHANNEL_A],
                correlation_id=uuid4(),
                user_confirmed_deleted=False,
            )
        assert len(await repository.channels(GUILD_A, ACTOR, include_hidden_deleted=True)) == 1

        assert (
            await repository.purge_channels(
                guild_id=GUILD_A,
                actor_user_id=ACTOR,
                channel_ids=[CHANNEL_A],
                correlation_id=uuid4(),
                user_confirmed_deleted=True,
            )
            == 1
        )
        assert await repository.channels(GUILD_A, ACTOR, include_hidden_deleted=True) == []
        async with tenant_transaction(
            create_session_factory(engine), TenantContext(GUILD_A, ACTOR)
        ) as session:
            tombstone = (
                (
                    await session.execute(
                        text("SELECT reason, confirmed_by_user_id FROM discord_channel_tombstones")
                    )
                )
                .mappings()
                .one()
            )
            assert dict(tombstone) == {
                "reason": "USER_CONFIRMED_DELETED",
                "confirmed_by_user_id": ACTOR,
            }

        await repository.apply_rest_channel_snapshot(
            guild_id=GUILD_A,
            channels=[
                {
                    "channel_id": CHANNEL_A,
                    "type": 0,
                    "name": "reobserved-by-rest",
                    "topic": "targeted-reconcile",
                    "parent_id": None,
                    "position": 1,
                    "nsfw": False,
                    "flags": 0,
                    "permission_overwrites": [],
                }
            ],
            correlation_id=uuid4(),
        )
        assert (await repository.channels(GUILD_A, ACTOR, include_hidden_deleted=True))[0][
            "name"
        ] == "reobserved-by-rest"
        async with tenant_transaction(
            create_session_factory(engine), TenantContext(GUILD_A, ACTOR)
        ) as session:
            assert (
                await session.scalar(text("SELECT count(*) FROM discord_channel_tombstones")) == 0
            )
            audit_data = await session.scalar(
                text(
                    "SELECT data_json FROM internal_audit_events "
                    "WHERE event_type='PURGED_RESOURCE_REOBSERVED'"
                )
            )
            assert audit_data == {"origin": "RECONCILE", "source": "TARGETED_REST"}
    finally:
        await engine.dispose()


async def test_runtime_rls_and_durable_job_coalescing_are_tenant_scoped() -> None:
    await reset_runtime()
    engine = create_database_engine(APP_URL, pool_size=4)
    factory = create_session_factory(engine)
    repository = RuntimeRepository(factory)
    try:
        await repository.ingest_gateway_event(
            dispatch(
                "CHANNEL_CREATE",
                channel_payload(GUILD_A, CHANNEL_A, "guild-a"),
                sequence=1,
            )
        )
        await repository.ingest_gateway_event(
            dispatch(
                "CHANNEL_CREATE",
                channel_payload(GUILD_B, CHANNEL_B, "guild-b"),
                sequence=1,
            )
        )
        async with tenant_transaction(factory, TenantContext(GUILD_A, ACTOR)) as session:
            assert await session.scalar(text("SELECT count(*) FROM discord_channels_cache")) == 1
            assert (
                await session.scalar(text("SELECT max(name) FROM discord_channels_cache"))
                == "guild-a"
            )
        async with tenant_transaction(factory, None) as session:
            assert await session.scalar(text("SELECT count(*) FROM discord_channels_cache")) == 0

        now = datetime.now(UTC)
        first = WorkloadJob(
            uuid4(),
            GUILD_A,
            "REFRESH_CHANNELS",
            "refresh:channels",
            WorkloadPriority.USER_REFRESH,
            now,
        )
        second = WorkloadJob(
            uuid4(),
            GUILD_A,
            "REFRESH_CHANNELS",
            "refresh:channels",
            WorkloadPriority.USER_REFRESH,
            now,
        )
        first_id = await repository.enqueue_job(first, requested_by=ACTOR, correlation_id=uuid4())
        second_id = await repository.enqueue_job(second, requested_by=ACTOR, correlation_id=uuid4())
        assert first_id == second_id
        async with tenant_transaction(factory, TenantContext(GUILD_A, ACTOR)) as session:
            assert await session.scalar(text("SELECT count(*) FROM discord_io_jobs")) == 1
        assert await repository.runtime_job_guilds() == [GUILD_A]
        assert set(await repository.runtime_outbox_guilds()) == {GUILD_A, GUILD_B}
        assert set(await repository.runtime_reconcile_guilds()) == {GUILD_A, GUILD_B}
    finally:
        await engine.dispose()


async def test_first_guild_create_establishes_tenant_root_and_active_stays_active() -> None:
    await reset_runtime()
    admin = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with admin.begin() as connection:
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id=:guild"),
                {"guild": GUILD_B},
            )
    finally:
        await admin.dispose()
    engine = create_database_engine(APP_URL, pool_size=1)
    repository = RuntimeRepository(create_session_factory(engine))
    try:
        guild_create = dispatch(
            "GUILD_CREATE",
            {
                "id": str(GUILD_B),
                "name": "Discovered Guild",
                "owner_id": str(ACTOR),
                "channels": [],
                "roles": [],
            },
            sequence=1,
        )
        assert await repository.ingest_gateway_event(guild_create) is True
        async with tenant_transaction(
            create_session_factory(engine), TenantContext(GUILD_B)
        ) as session:
            assert (
                await session.scalar(text("SELECT installation_status FROM guild_installations"))
                == "PENDING_SETUP"
            )

        active_observation = dispatch(
            "GUILD_CREATE",
            {
                "id": str(GUILD_A),
                "name": "Still Active",
                "owner_id": str(ACTOR),
                "channels": [],
                "roles": [],
            },
            sequence=2,
        )
        assert await repository.ingest_gateway_event(active_observation) is True
        async with tenant_transaction(
            create_session_factory(engine), TenantContext(GUILD_A, ACTOR)
        ) as session:
            assert (
                await session.scalar(text("SELECT installation_status FROM guild_installations"))
                == "ACTIVE"
            )
    finally:
        await engine.dispose()


async def test_channel_and_role_update_delete_project_confirmed_state() -> None:
    await reset_runtime()
    engine = create_database_engine(APP_URL, pool_size=1)
    factory = create_session_factory(engine)
    repository = RuntimeRepository(factory)
    role_id = 130303030303030399
    try:
        await repository.ingest_gateway_event(
            dispatch(
                "CHANNEL_CREATE",
                channel_payload(GUILD_A, CHANNEL_A, "before-delete"),
                sequence=1,
            )
        )
        await repository.ingest_gateway_event(
            dispatch(
                "CHANNEL_DELETE",
                channel_payload(GUILD_A, CHANNEL_A, "before-delete"),
                sequence=4,
            )
        )
        channel = (await repository.channels(GUILD_A, ACTOR, include_hidden_deleted=True))[0]
        assert channel["observability_state"] == "DELETED_CONFIRMED"
        assert channel["deleted_confirmed_at"] is not None
        assert (
            await repository.purge_channels(
                guild_id=GUILD_A,
                actor_user_id=ACTOR,
                channel_ids=[CHANNEL_A],
                correlation_id=uuid4(),
                user_confirmed_deleted=False,
            )
            == 1
        )
        async with tenant_transaction(factory, TenantContext(GUILD_A, ACTOR)) as session:
            tombstone = (
                (
                    await session.execute(
                        text(
                            "SELECT reason, confirmed_by_user_id "
                            "FROM discord_channel_tombstones WHERE channel_id=:channel"
                        ),
                        {"channel": CHANNEL_A},
                    )
                )
                .mappings()
                .one()
            )
            assert dict(tombstone) == {
                "reason": "DELETED_CONFIRMED",
                "confirmed_by_user_id": None,
            }

        await repository.ingest_gateway_event(
            dispatch(
                "GUILD_ROLE_CREATE",
                {
                    "guild_id": str(GUILD_A),
                    "role": {
                        "id": str(role_id),
                        "name": "created",
                        "position": 1,
                        "permissions": "0",
                    },
                },
                sequence=5,
            )
        )
        await repository.ingest_gateway_event(
            dispatch(
                "GUILD_ROLE_UPDATE",
                {
                    "guild_id": str(GUILD_A),
                    "role": {
                        "id": str(role_id),
                        "name": "updated",
                        "position": 2,
                        "permissions": "8",
                    },
                },
                sequence=6,
            )
        )
        await repository.ingest_gateway_event(
            dispatch(
                "GUILD_ROLE_DELETE",
                {"guild_id": str(GUILD_A), "role_id": str(role_id)},
                sequence=7,
            )
        )
        async with tenant_transaction(factory, TenantContext(GUILD_A, ACTOR)) as session:
            role = (
                (
                    await session.execute(
                        text(
                            "SELECT name, permissions_bits, deleted_confirmed_at "
                            "FROM discord_roles_cache WHERE role_id=:role"
                        ),
                        {"role": role_id},
                    )
                )
                .mappings()
                .one()
            )
            assert role["name"] == "updated"
            assert int(role["permissions_bits"]) == 8
            assert role["deleted_confirmed_at"] is not None
    finally:
        await engine.dispose()


async def test_gateway_gap_remains_stale_until_full_structure_reconcile() -> None:
    await reset_runtime()
    engine = create_database_engine(APP_URL, pool_size=2)
    factory = create_session_factory(engine)
    repository = RuntimeRepository(factory)
    try:
        await repository.ingest_gateway_event(
            dispatch(
                "CHANNEL_CREATE",
                channel_payload(GUILD_A, CHANNEL_A, "before-gap"),
                sequence=10,
            )
        )
        await repository.record_gateway_discontinuity(
            guild_id=GUILD_A,
            continuity="GAP_DETECTED",
            correlation_id=uuid4(),
        )
        await repository.ingest_gateway_event(
            dispatch(
                "CHANNEL_UPDATE",
                channel_payload(GUILD_A, CHANNEL_A, "after-gap-dispatch"),
                sequence=12,
            )
        )
        await repository.apply_rest_channel_snapshot(
            guild_id=GUILD_A,
            channels=[
                {
                    "channel_id": CHANNEL_A,
                    "type": 0,
                    "name": "targeted-rest-during-gap",
                    "topic": None,
                    "parent_id": None,
                    "position": 1,
                    "nsfw": False,
                    "flags": 0,
                    "permission_overwrites": [],
                }
            ],
            correlation_id=uuid4(),
        )
        async with tenant_transaction(factory, TenantContext(GUILD_A, ACTOR)) as session:
            coverage = (
                (
                    await session.execute(
                        text(
                            "SELECT coverage_mode, freshness_state, gateway_continuity "
                            "FROM discord_cache_coverage"
                        )
                    )
                )
                .mappings()
                .one()
            )
            assert dict(coverage) == {
                "coverage_mode": "DEGRADED",
                "freshness_state": "STALE",
                "gateway_continuity": "GAP_DETECTED",
            }

        await repository.mark_structure_sync_complete(GUILD_A)
        async with tenant_transaction(factory, TenantContext(GUILD_A, ACTOR)) as session:
            coverage = (
                (
                    await session.execute(
                        text(
                            "SELECT coverage_mode, freshness_state, gateway_continuity "
                            "FROM discord_cache_coverage"
                        )
                    )
                )
                .mappings()
                .one()
            )
            assert dict(coverage) == {
                "coverage_mode": "FULL",
                "freshness_state": "FRESH",
                "gateway_continuity": "CONNECTED",
            }
    finally:
        await engine.dispose()


async def test_out_of_order_gateway_events_do_not_emit_false_audit_or_outbox() -> None:
    await reset_runtime()
    engine = create_database_engine(APP_URL, pool_size=2)
    factory = create_session_factory(engine)
    repository = RuntimeRepository(factory)
    role_id = 130303030303030398
    try:
        newest_channel = dispatch(
            "CHANNEL_UPDATE",
            channel_payload(GUILD_A, CHANNEL_A, "newest-channel"),
            sequence=30,
        )
        await repository.ingest_gateway_event(newest_channel)
        stale_obfuscated = dispatch(
            "CHANNEL_UPDATE",
            channel_payload(
                GUILD_A,
                CHANNEL_A,
                "___hidden___",
                flags=CHANNEL_OBFUSCATED_FLAG,
            ),
            sequence=29,
        )
        stale_deleted = dispatch(
            "CHANNEL_DELETE",
            channel_payload(GUILD_A, CHANNEL_A, "stale-delete"),
            sequence=28,
        )
        assert await repository.ingest_gateway_event(stale_obfuscated) is True
        assert await repository.ingest_gateway_event(stale_deleted) is True

        newest_role = dispatch(
            "GUILD_ROLE_UPDATE",
            {
                "guild_id": str(GUILD_A),
                "role": {
                    "id": str(role_id),
                    "name": "newest-role",
                    "position": 3,
                    "permissions": "8",
                },
            },
            sequence=40,
        )
        await repository.ingest_gateway_event(newest_role)
        stale_role_update = dispatch(
            "GUILD_ROLE_UPDATE",
            {
                "guild_id": str(GUILD_A),
                "role": {
                    "id": str(role_id),
                    "name": "stale-role-update",
                    "position": 1,
                    "permissions": "0",
                },
            },
            sequence=38,
        )
        stale_role_delete = dispatch(
            "GUILD_ROLE_DELETE",
            {"guild_id": str(GUILD_A), "role_id": str(role_id)},
            sequence=39,
        )
        assert await repository.ingest_gateway_event(stale_role_update) is True
        assert await repository.ingest_gateway_event(stale_role_delete) is True

        channel = (await repository.channels(GUILD_A, ACTOR, include_hidden_deleted=True))[0]
        assert channel["name"] == "newest-channel"
        assert channel["observability_state"] == "VISIBLE"
        async with tenant_transaction(factory, TenantContext(GUILD_A, ACTOR)) as session:
            role = (
                (
                    await session.execute(
                        text(
                            "SELECT name, deleted_confirmed_at FROM discord_roles_cache "
                            "WHERE role_id=:role"
                        ),
                        {"role": role_id},
                    )
                )
                .mappings()
                .one()
            )
            assert dict(role) == {"name": "newest-role", "deleted_confirmed_at": None}
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM internal_audit_events "
                        "WHERE causation_id = ANY(:causation_ids)"
                    ),
                    {
                        "causation_ids": [
                            stale_obfuscated.event_id,
                            stale_deleted.event_id,
                            stale_role_update.event_id,
                            stale_role_delete.event_id,
                        ]
                    },
                )
                == 0
            )
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM discord_outbox "
                        "WHERE causation_id = ANY(:causation_ids)"
                    ),
                    {
                        "causation_ids": [
                            stale_obfuscated.event_id,
                            stale_deleted.event_id,
                            stale_role_update.event_id,
                            stale_role_delete.event_id,
                        ]
                    },
                )
                == 0
            )
            assert (
                await session.scalar(
                    text("SELECT last_gateway_event_at FROM discord_cache_coverage")
                )
                == newest_role.received_at
            )
    finally:
        await engine.dispose()


async def test_durable_job_lease_recovers_after_worker_crash_and_acks_by_owner() -> None:
    await reset_runtime()
    engine = create_database_engine(APP_URL, pool_size=2)
    factory = create_session_factory(engine)
    repository = RuntimeRepository(factory)
    try:
        job = WorkloadJob(
            uuid4(),
            GUILD_A,
            "REFRESH_CHANNELS",
            "refresh:crash-recovery",
            WorkloadPriority.USER_REFRESH,
            datetime.now(UTC),
        )
        await repository.enqueue_job(job, requested_by=ACTOR, correlation_id=uuid4())
        first = await repository.lease_next_job(
            GUILD_A, lease_owner="worker-crashed", lease_seconds=60
        )
        assert first is not None
        assert await repository.lease_next_job(GUILD_A, lease_owner="worker-too-early") is None
        admin = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE discord_io_jobs SET leased_until=now() - interval '1 second' "
                        "WHERE job_id=:job_id"
                    ),
                    {"job_id": job.job_id},
                )
        finally:
            await admin.dispose()
        recovered = await repository.lease_next_job(GUILD_A, lease_owner="worker-recovered")
        assert recovered is not None
        assert recovered["attempt_count"] == 2
        assert (
            await repository.complete_job(
                GUILD_A,
                job.job_id,
                lease_owner="worker-crashed",
                lease_token=first["lease_token"],
            )
            is False
        )
        assert (
            await repository.complete_job(
                GUILD_A,
                job.job_id,
                lease_owner="worker-recovered",
                lease_token=recovered["lease_token"],
            )
            is True
        )
    finally:
        await engine.dispose()
