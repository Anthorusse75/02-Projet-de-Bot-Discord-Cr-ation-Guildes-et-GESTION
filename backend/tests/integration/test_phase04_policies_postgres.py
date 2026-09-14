"""Real PostgreSQL proofs for the generic Policy persistence foundation."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from did.application.policies.service import PolicyService
from did.domain.policies import PolicyLifecycleState, PolicyScopeType
from did.infrastructure.database import create_database_engine, tenant_transaction
from did.infrastructure.policies_repository import (
    PoliciesRepository,
    PolicyConflict,
    PolicyIdempotencyConflict,
    PolicyNotFound,
    PolicyTargetNotFound,
)
from did.tenancy import TenantContext

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL",
    "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test",
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 884004001
GUILD_B = 884004002
ACTOR_A = 884004011
ACTOR_B = 884004012


@pytest.fixture
async def policies_context() -> AsyncIterator[tuple[PoliciesRepository, PolicyService]]:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=2)
    app_engine = create_database_engine(APP_URL, pool_size=4)
    params = {"ga": GUILD_A, "gb": GUILD_B, "ua": ACTOR_A, "ub": ACTOR_B}
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id IN (:ga,:gb)"), params
            )
            for user_id in (ACTOR_A, ACTOR_B):
                await connection.execute(
                    text(
                        "INSERT INTO users (discord_user_id,username) VALUES (:id,:name) "
                        "ON CONFLICT (discord_user_id) DO NOTHING"
                    ),
                    {"id": user_id, "name": f"policy-user-{user_id}"},
                )
            for guild_id, owner_id in ((GUILD_A, ACTOR_A), (GUILD_B, ACTOR_B)):
                await connection.execute(
                    text(
                        "INSERT INTO guild_installations "
                        "(guild_id,name,owner_id,installation_status) "
                        "VALUES (:guild_id,:name,:owner_id,'ACTIVE')"
                    ),
                    {"guild_id": guild_id, "name": f"Policy {guild_id}", "owner_id": owner_id},
                )
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        repository = PoliciesRepository(factory)
        yield repository, PolicyService(repository)
    finally:
        async with admin_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id IN (:ga,:gb)"), params
            )
            await connection.execute(
                text("DELETE FROM users WHERE discord_user_id IN (:ua,:ub)"), params
            )
        await app_engine.dispose()
        await admin_engine.dispose()


async def _create(
    service: PolicyService,
    guild_id: int,
    actor_id: int,
    key: str,
    *,
    priority: int = 0,
):
    return await service.create_draft(
        guild_id=guild_id,
        actor_id=actor_id,
        policy_type="ACCESS_CONTROL",
        contract_version=1,
        name=f"Policy {key}",
        description="",
        scope_type=PolicyScopeType.GUILD,
        scope_id=None,
        conditions=[{"kind": "ALWAYS"}],
        effects=[{"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"}],
        metadata={"summary": "Real PostgreSQL proof"},
        idempotency_key=key,
        priority=priority,
    )


@pytest.mark.asyncio
async def test_rls_and_repository_isolate_two_guilds(policies_context) -> None:
    repository, service = policies_context
    policy_a = await _create(service, GUILD_A, ACTOR_A, "create-a")
    policy_b = await _create(service, GUILD_B, ACTOR_B, "create-b")

    assert {value.policy_id for value in await repository.list(GUILD_A)} == {policy_a.policy_id}
    assert {value.policy_id for value in await repository.list(GUILD_B)} == {policy_b.policy_id}
    with pytest.raises(PolicyNotFound):
        await repository.get(GUILD_B, policy_a.policy_id)

    engine = create_database_engine(APP_URL, pool_size=1)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        # Deliberately no guild predicate: PostgreSQL RLS is the isolation boundary.
        async with tenant_transaction(factory, TenantContext(GUILD_A)) as session:
            rows = (await session.execute(text("SELECT guild_id FROM policies"))).scalars().all()
        assert set(rows) == {GUILD_A}
        async with tenant_transaction(factory, TenantContext(GUILD_B)) as session:
            rows = (await session.execute(text("SELECT guild_id FROM policies"))).scalars().all()
        assert set(rows) == {GUILD_B}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_history_is_versioned_and_app_role_cannot_mutate_it(policies_context) -> None:
    repository, service = policies_context
    created = await _create(service, GUILD_A, ACTOR_A, "history-create")
    updated = await service.update_draft(
        guild_id=GUILD_A,
        policy_id=created.policy_id,
        actor_id=ACTOR_A,
        expected_revision=1,
        name="Renamed",
        description="edited",
        scope_type=PolicyScopeType.GUILD,
        scope_id=None,
        conditions=[{"kind": "ALWAYS"}],
        effects=[{"kind": "SET_ACCESS", "access": "WRITE", "decision": "DENY"}],
        metadata={"summary": "Changed"},
        idempotency_key="history-update",
    )
    assert updated.revision == 2
    versions = await repository.versions(GUILD_A, created.policy_id)
    assert [(value.revision, value.change_kind) for value in versions] == [
        (1, "CREATE"),
        (2, "UPDATE"),
    ]
    assert versions[0].snapshot["name"] == "Policy history-create"
    assert versions[1].snapshot["name"] == "Renamed"

    engine = create_database_engine(APP_URL, pool_size=1)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        with pytest.raises(DBAPIError):
            async with tenant_transaction(factory, TenantContext(GUILD_A)) as session:
                await session.execute(
                    text(
                        "UPDATE policy_versions SET change_kind='RETIRE' "
                        "WHERE guild_id=:guild_id AND policy_id=:policy_id"
                    ),
                    {"guild_id": GUILD_A, "policy_id": created.policy_id},
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_explicit_priority_round_trips_and_is_versioned(policies_context) -> None:
    repository, service = policies_context
    created = await _create(
        service,
        GUILD_A,
        ACTOR_A,
        "priority-create",
        priority=42,
    )

    assert created.priority == 42
    assert (await repository.get(GUILD_A, created.policy_id)).priority == 42
    assert (await repository.versions(GUILD_A, created.policy_id))[0].snapshot["priority"] == 42


@pytest.mark.asyncio
async def test_cas_allows_only_one_concurrent_draft_update(policies_context) -> None:
    repository, service = policies_context
    created = await _create(service, GUILD_A, ACTOR_A, "concurrent-create")
    first = replace(created, name="First", revision=2)
    second = replace(created, name="Second", revision=2)

    results = await asyncio.gather(
        repository.update_draft(
            first,
            expected_revision=1,
            idempotency_key="concurrent-first",
            request_hash="a" * 64,
            correlation_id=uuid4(),
        ),
        repository.update_draft(
            second,
            expected_revision=1,
            idempotency_key="concurrent-second",
            request_hash="b" * 64,
            correlation_id=uuid4(),
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, PolicyConflict) for result in results) == 1
    persisted = await repository.get(GUILD_A, created.policy_id)
    assert persisted.revision == 2
    assert persisted.name in {"First", "Second"}


@pytest.mark.asyncio
async def test_activation_and_disable_are_idempotent_and_audited(policies_context) -> None:
    repository, service = policies_context
    created = await _create(service, GUILD_A, ACTOR_A, "lifecycle-create")
    active = await service.activate(GUILD_A, created.policy_id, ACTOR_A, 1, "activate-once")
    replayed_active = await service.activate(
        GUILD_A, created.policy_id, ACTOR_A, 1, "activate-once"
    )
    disabled = await service.disable(GUILD_A, created.policy_id, ACTOR_A, 2, "disable-once")
    replayed_disabled = await service.disable(
        GUILD_A, created.policy_id, ACTOR_A, 2, "disable-once"
    )

    assert active.lifecycle_state is PolicyLifecycleState.ACTIVE
    assert replayed_active.revision == active.revision == 2
    assert disabled.lifecycle_state is PolicyLifecycleState.DISABLED
    assert replayed_disabled.revision == disabled.revision == 3
    versions = await repository.versions(GUILD_A, created.policy_id)
    assert [(value.revision, value.change_kind) for value in versions] == [
        (1, "CREATE"),
        (2, "ACTIVATE"),
        (3, "DISABLE"),
    ]


@pytest.mark.asyncio
async def test_create_replay_returns_one_policy_and_one_history_row(policies_context) -> None:
    repository, service = policies_context
    first = await _create(service, GUILD_A, ACTOR_A, "same-create-key")
    replay = await _create(service, GUILD_A, ACTOR_A, "same-create-key")

    assert replay.policy_id == first.policy_id
    assert len(await repository.list(GUILD_A)) == 1
    versions = await repository.versions(GUILD_A, first.policy_id)
    assert [(value.revision, value.change_kind) for value in versions] == [(1, "CREATE")]

    with pytest.raises(PolicyIdempotencyConflict):
        await service.create_draft(
            guild_id=GUILD_A,
            actor_id=ACTOR_A,
            policy_type="ACCESS_CONTROL",
            contract_version=1,
            name="Different request",
            description="",
            scope_type=PolicyScopeType.GUILD,
            scope_id=None,
            conditions=[{"kind": "ALWAYS"}],
            effects=[{"kind": "SET_ACCESS", "access": "VIEW", "decision": "DENY"}],
            metadata={"summary": "Different request"},
            idempotency_key="same-create-key",
        )


@pytest.mark.asyncio
async def test_application_validation_rejects_another_guilds_target(policies_context) -> None:
    _repository, service = policies_context
    foreign_group_id = uuid4()
    engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO logical_groups "
                    "(id,guild_id,name,slug,metadata_json) VALUES "
                    "(:id,:guild_id,'Foreign group','foreign-group',CAST('{}' AS jsonb))"
                ),
                {"id": foreign_group_id, "guild_id": GUILD_B},
            )
        with pytest.raises(PolicyTargetNotFound):
            await service.create_draft(
                guild_id=GUILD_A,
                actor_id=ACTOR_A,
                policy_type="ACCESS_CONTROL",
                contract_version=1,
                name="Cross-tenant attempt",
                description="",
                scope_type=PolicyScopeType.LOGICAL_GROUP,
                scope_id=str(foreign_group_id),
                conditions=[{"kind": "ALWAYS"}],
                effects=[{"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"}],
                metadata={"summary": "Must fail closed"},
                idempotency_key="cross-tenant-target",
            )
        assert await service.list(GUILD_A) == ()
    finally:
        await engine.dispose()
