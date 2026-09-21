"""Real PostgreSQL proofs for the generic Policy persistence foundation."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from did.application.planning.service import PlanningService
from did.application.policies.planning import PolicyPlanningService
from did.application.policies.service import PolicyService
from did.domain.policies import PolicyLifecycleError, PolicyLifecycleState, PolicyScopeType
from did.infrastructure.database import create_database_engine, tenant_transaction
from did.infrastructure.planning_repository import PlanningRepository, PlanNotFound
from did.infrastructure.policies_repository import (
    PoliciesRepository,
    PolicyConflict,
    PolicyIdempotencyConflict,
    PolicyNotFound,
    PolicyTargetNotFound,
)
from did.infrastructure.stage04_repository import Stage04Repository
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
BOT_A = 884004021
BOT_B = 884004022
CHANNEL_A = 884004101
CHANNEL_B = 884004102


@pytest.fixture
async def policies_context() -> AsyncIterator[tuple[PoliciesRepository, PolicyService]]:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=2)
    app_engine = create_database_engine(APP_URL, pool_size=4)
    params = {"ga": GUILD_A, "gb": GUILD_B, "ua": ACTOR_A, "ub": ACTOR_B}
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(
                text("SELECT set_config('app.tenant_purge_in_progress', 'on', true)")
            )
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
            for guild_id, owner_id, bot_id, channel_id in (
                (GUILD_A, ACTOR_A, BOT_A, CHANNEL_A),
                (GUILD_B, ACTOR_B, BOT_B, CHANNEL_B),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO guild_installations "
                        "(guild_id,name,owner_id,installation_status,application_id,bot_user_id) "
                        "VALUES (:guild_id,:name,:owner_id,'ACTIVE',:bot_id,:bot_id)"
                    ),
                    {
                        "guild_id": guild_id,
                        "name": f"Policy {guild_id}",
                        "owner_id": owner_id,
                        "bot_id": bot_id,
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO discord_cache_coverage "
                        "(guild_id,coverage_mode,freshness_state,known_channels,"
                        "visible_channels,known_roles,members_complete) "
                        "VALUES (:guild_id,'FULL','FRESH',1,1,1,true)"
                    ),
                    {"guild_id": guild_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO discord_roles_cache "
                        "(guild_id,role_id,name,position,permissions_bits,managed,color,hoist,"
                        "mentionable,raw_json,last_gateway_seen_at) VALUES "
                        "(:guild_id,:guild_id,'@everyone',0,:permissions,false,0,false,false,"
                        "CAST('{}' AS jsonb),now())"
                    ),
                        {
                            "guild_id": guild_id,
                            "permissions": (1 << 28) | (1 << 10),
                        },
                )
                await connection.execute(
                    text(
                        "INSERT INTO discord_channels_cache "
                        "(guild_id,channel_id,type,name,position,last_full_payload,"
                        "observability_state,freshness_state,last_full_observed_at) VALUES "
                        "(:guild_id,:channel_id,0,'policy-target',0,CAST('{}' AS jsonb),"
                        "'VISIBLE','FRESH',now())"
                    ),
                    {"guild_id": guild_id, "channel_id": channel_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO discord_member_authorization_cache "
                        "(guild_id,discord_user_id,role_ids,source,validity,observed_at,is_bot) "
                        "VALUES (:guild_id,:owner_id,ARRAY[:guild_id]::bigint[],'GATEWAY',"
                        "'FRESH',now(),false),(:guild_id,:bot_id,ARRAY[:guild_id]::bigint[],"
                        "'GATEWAY','FRESH',now(),true)"
                    ),
                    {
                        "guild_id": guild_id,
                        "owner_id": owner_id,
                        "bot_id": bot_id,
                    },
                )
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        repository = PoliciesRepository(factory)
        yield repository, PolicyService(repository)
    finally:
        async with admin_engine.begin() as connection:
            await connection.execute(
                text("SELECT set_config('app.tenant_purge_in_progress', 'on', true)")
            )
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


@pytest.mark.asyncio
async def test_policy_favorites_persist_idempotently_and_isolate_user_and_guild(
    policies_context,
) -> None:
    _repository, service = policies_context
    policy_a = await _create(service, GUILD_A, ACTOR_A, "favorite-a")
    policy_b = await _create(service, GUILD_B, ACTOR_B, "favorite-b")
    custom_a = f"custom:{policy_a.policy_id}"

    assert await service.list_favorites(GUILD_A, ACTOR_A) == ()
    assert await service.set_favorite(
        GUILD_A, ACTOR_A, "native:visible_only", pinned=True
    ) == ("native:visible_only",)
    assert await service.set_favorite(GUILD_A, ACTOR_A, custom_a, pinned=True) == (
        "native:visible_only",
        custom_a,
    )
    assert await service.set_favorite(GUILD_A, ACTOR_A, custom_a, pinned=True) == (
        "native:visible_only",
        custom_a,
    )

    assert await service.list_favorites(GUILD_A, ACTOR_B) == ()
    assert await service.set_favorite(
        GUILD_B, ACTOR_B, "native:staff_only", pinned=True
    ) == ("native:staff_only",)
    assert await service.list_favorites(GUILD_A, ACTOR_A) == (
        "native:visible_only",
        custom_a,
    )
    with pytest.raises(PolicyNotFound):
        await service.set_favorite(
            GUILD_A, ACTOR_A, f"custom:{policy_b.policy_id}", pinned=True
        )

    assert await service.set_favorite(GUILD_A, ACTOR_A, custom_a, pinned=False) == (
        "native:visible_only",
    )


@pytest.mark.asyncio
async def test_policy_deletion_is_soft_audited_and_cross_tenant_replacement_is_refused(
    policies_context,
) -> None:
    repository, service = policies_context
    policy_a = await _create(service, GUILD_A, ACTOR_A, "delete-a")
    policy_b = await _create(service, GUILD_B, ACTOR_B, "delete-b")

    dependencies = await service.deletion_dependencies(GUILD_A, policy_a.policy_id)
    assert dependencies.policy.policy_id == policy_a.policy_id
    assert dependencies.plans == () and dependencies.scope_binding_count == 0

    retired = await service.delete_with_strategy(
        guild_id=GUILD_A,
        policy_id=policy_a.policy_id,
        actor_id=ACTOR_A,
        expected_revision=1,
        strategy="DETACH",
        idempotency_key="delete-a-detach",
    )
    assert retired.lifecycle_state is PolicyLifecycleState.RETIRED
    assert retired.revision == 2
    versions = await repository.versions(GUILD_A, policy_a.policy_id)
    assert [version.change_kind for version in versions] == ["CREATE", "RETIRE"]

    other_a = await _create(service, GUILD_A, ACTOR_A, "delete-a-cross-tenant")
    with pytest.raises(PolicyNotFound):
        await service.delete_with_strategy(
            guild_id=GUILD_A,
            policy_id=other_a.policy_id,
            actor_id=ACTOR_A,
            expected_revision=1,
            strategy="REPLACE",
            replacement_policy_id=policy_b.policy_id,
            idempotency_key="delete-a-replace-b",
        )

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
    plan_id = uuid4()
    repository.assert_activation_plan = AsyncMock(return_value={"id": plan_id})  # type: ignore[method-assign]
    active = await service.activate(
        GUILD_A, created.policy_id, ACTOR_A, 1, "activate-once", plan_id
    )
    replayed_active = await service.activate(
        GUILD_A, created.policy_id, ACTOR_A, 1, "activate-once", plan_id
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
async def test_disable_requires_a_real_validated_plan_for_this_exact_policy_and_revision(
    policies_context,
) -> None:
    """REQ-AP-INH-003 'reapply category policy': disabling an ACTIVE Policy
    with a plan_id must be gated on a REAL, preflight-validated canonical
    Plan for this exact Policy/revision -- the same guarantee activate()
    already has, reusing the same repository check (assert_activation_plan)
    against a real database row, not a mock."""

    repository, _ = policies_context
    factory = object.__getattribute__(repository, "_factory")
    read_models = Stage04Repository(factory)
    policy_service = PolicyService(repository, read_models=read_models)
    policy_planning = PolicyPlanningService(policies=policy_service, read_models=read_models)
    plans = PlanningRepository(factory)
    planning = PlanningService(plans, read_models, policy_preflight=policy_planning)
    policy_planning.bind_planning(planning)

    draft = await _create(policy_service, GUILD_A, ACTOR_A, "disable-plan-chain")
    repository.assert_activation_plan = AsyncMock(return_value={"id": uuid4()})  # type: ignore[method-assign]
    active = await policy_service.activate(
        GUILD_A, draft.policy_id, ACTOR_A, 1, "disable-plan-chain-activate", uuid4()
    )
    assert active.lifecycle_state is PolicyLifecycleState.ACTIVE
    del repository.assert_activation_plan  # restore the real, unmocked method

    preview = await policy_planning.preview_disable(
        guild_id=GUILD_A, policy_id=active.policy_id, actor_user_id=ACTOR_A
    )
    assert preview.lifecycle_state is PolicyLifecycleState.ACTIVE

    _, disable_plan, created, preflight = await policy_planning.create_disable_plan(
        guild_id=GUILD_A,
        policy_id=active.policy_id,
        actor_user_id=ACTOR_A,
        idempotency_key="disable-plan-once",
        correlation_id=uuid4(),
        expected_revision=2,
    )
    assert created and preflight.allowed
    assert disable_plan["status"] == "VALIDATED"
    assert disable_plan["source_policy_id"] == active.policy_id
    assert int(disable_plan["source_policy_revision"]) == 2
    deletion_plan = await repository.assert_deletion_plan(
        guild_id=GUILD_A,
        policy_id=active.policy_id,
        policy_revision=2,
        plan_id=UUID(str(disable_plan["id"])),
    )
    assert deletion_plan["id"] == disable_plan["id"]

    with pytest.raises(PolicyLifecycleError):
        await policy_service.disable(
            GUILD_A, active.policy_id, ACTOR_A, 2, "reject-disable-unrelated-plan", uuid4()
        )

    disabled = await policy_service.disable(
        GUILD_A,
        active.policy_id,
        ACTOR_A,
        2,
        "disable-from-validated-plan",
        UUID(str(disable_plan["id"])),
    )
    assert disabled.lifecycle_state is PolicyLifecycleState.DISABLED
    versions = await repository.versions(GUILD_A, active.policy_id)
    assert [(value.revision, value.change_kind) for value in versions] == [
        (1, "CREATE"),
        (2, "ACTIVATE"),
        (3, "DISABLE"),
    ]

    # Disabling without a plan_id at all remains supported (backward
    # compatible): an ACTIVE policy can still be disabled unconditionally,
    # exactly like before REQ-AP-INH-003 existed.
    other = await _create(policy_service, GUILD_A, ACTOR_A, "disable-without-plan")
    repository.assert_activation_plan = AsyncMock(return_value={"id": uuid4()})  # type: ignore[method-assign]
    other_active = await policy_service.activate(
        GUILD_A, other.policy_id, ACTOR_A, 1, "disable-without-plan-activate", uuid4()
    )
    del repository.assert_activation_plan
    disabled_without_plan = await policy_service.disable(
        GUILD_A, other_active.policy_id, ACTOR_A, 2, "disable-without-plan-once"
    )
    assert disabled_without_plan.lifecycle_state is PolicyLifecycleState.DISABLED


@pytest.mark.asyncio
async def test_accept_exception_persists_a_new_metadata_only_revision(policies_context) -> None:
    repository, service = policies_context
    created = await _create(service, GUILD_A, ACTOR_A, "exception-create")
    plan_id = uuid4()
    repository.assert_activation_plan = AsyncMock(return_value={"id": plan_id})  # type: ignore[method-assign]
    active = await service.activate(
        GUILD_A, created.policy_id, ACTOR_A, 1, "exception-activate", plan_id
    )
    other_policy_id = uuid4()

    annotated = await service.accept_exception(
        GUILD_A,
        active.policy_id,
        ACTOR_A,
        other_policy_id=other_policy_id,
        expected_revision=2,
        idempotency_key="accept-once",
        reason="Managers keeps intentional visibility",
    )
    replayed = await service.accept_exception(
        GUILD_A,
        active.policy_id,
        ACTOR_A,
        other_policy_id=other_policy_id,
        expected_revision=2,
        idempotency_key="accept-once",
        reason="Managers keeps intentional visibility",
    )

    assert annotated.lifecycle_state is PolicyLifecycleState.ACTIVE
    assert annotated.revision == replayed.revision == 3
    assert f"exception_accepted:{other_policy_id}" in annotated.metadata["tags"]
    assert annotated.metadata["reason"] == "Managers keeps intentional visibility"
    assert annotated.conditions == active.conditions
    assert annotated.effects == active.effects
    versions = await repository.versions(GUILD_A, active.policy_id)
    assert [(value.revision, value.change_kind) for value in versions] == [
        (1, "CREATE"),
        (2, "ACTIVATE"),
        (3, "ANNOTATE"),
    ]


@pytest.mark.asyncio
async def test_accept_exception_rejects_a_stale_revision(policies_context) -> None:
    repository, service = policies_context
    created = await _create(service, GUILD_A, ACTOR_A, "exception-cas-create")
    plan_id = uuid4()
    repository.assert_activation_plan = AsyncMock(return_value={"id": plan_id})  # type: ignore[method-assign]
    active = await service.activate(
        GUILD_A, created.policy_id, ACTOR_A, 1, "exception-cas-activate", plan_id
    )

    with pytest.raises(PolicyConflict):
        await service.accept_exception(
            GUILD_A,
            active.policy_id,
            ACTOR_A,
            other_policy_id=uuid4(),
            expected_revision=999,
            idempotency_key="accept-stale",
        )


@pytest.mark.asyncio
async def test_accept_exception_is_tenant_isolated(policies_context) -> None:
    repository, service = policies_context
    created = await _create(service, GUILD_A, ACTOR_A, "exception-tenant-create")
    plan_id = uuid4()
    repository.assert_activation_plan = AsyncMock(return_value={"id": plan_id})  # type: ignore[method-assign]
    active = await service.activate(
        GUILD_A, created.policy_id, ACTOR_A, 1, "exception-tenant-activate", plan_id
    )

    with pytest.raises(PolicyNotFound):
        await service.accept_exception(
            GUILD_B,
            active.policy_id,
            ACTOR_B,
            other_policy_id=uuid4(),
            expected_revision=2,
            idempotency_key="cross-tenant-accept",
        )


@pytest.mark.asyncio
async def test_policy_preview_preflight_plan_idempotency_and_provenance_chain(
    policies_context,
) -> None:
    repository, _ = policies_context
    factory = object.__getattribute__(repository, "_factory")
    read_models = Stage04Repository(factory)
    policy_service = PolicyService(repository, read_models=read_models)
    policy_planning = PolicyPlanningService(
        policies=policy_service,
        read_models=read_models,
    )
    plans = PlanningRepository(factory)
    planning = PlanningService(plans, read_models, policy_preflight=policy_planning)
    policy_planning.bind_planning(planning)
    draft = await _create(policy_service, GUILD_A, ACTOR_A, "canonical-chain")

    preview = await policy_planning.preview(
        guild_id=GUILD_A,
        policy_id=draft.policy_id,
        actor_user_id=ACTOR_A,
    )
    assert draft.lifecycle_state is PolicyLifecycleState.DRAFT
    assert preview.persisted is False and preview.discord_mutations == 0
    assert preview.impact.accuracy.value == "EXACT"

    correlation = uuid4()
    _, first, created, first_preflight = await policy_planning.create_plan(
        guild_id=GUILD_A,
        policy_id=draft.policy_id,
        actor_user_id=ACTOR_A,
        idempotency_key="canonical-plan-once",
        correlation_id=correlation,
        expected_revision=1,
    )
    _, replay, replay_created, replay_preflight = await policy_planning.create_plan(
        guild_id=GUILD_A,
        policy_id=draft.policy_id,
        actor_user_id=ACTOR_A,
        idempotency_key="canonical-plan-once",
        correlation_id=uuid4(),
        expected_revision=1,
    )

    assert created is True and replay_created is False
    assert replay["id"] == first["id"]
    assert first_preflight.allowed, first_preflight
    assert replay_preflight.allowed, replay_preflight
    assert first["status"] == "VALIDATED"
    assert first["source_policy_id"] == draft.policy_id
    assert int(first["source_policy_revision"]) == 1
    assert first["origin_type"] == "POLICY"
    dependencies = await policy_service.deletion_dependencies(GUILD_A, draft.policy_id)
    assert [(row["id"], row["status"]) for row in dependencies.plans] == [
        (first["id"], "VALIDATED")
    ]
    operations = await plans.operations(GUILD_A, UUID(str(first["id"])))
    assert operations and all(row["plan_id"] == first["id"] for row in operations)
    async with tenant_transaction(factory, TenantContext(GUILD_A)) as session:
        provenance = (
            (
                await session.execute(
                    text(
                        "SELECT o.id AS operation_id,p.id AS plan_id,p.source_policy_id,"
                        "p.source_policy_revision FROM plan_operations o JOIN plans p "
                        "ON p.guild_id=o.guild_id AND p.id=o.plan_id "
                        "WHERE o.guild_id=:guild_id AND o.plan_id=:plan_id LIMIT 1"
                    ),
                    {"guild_id": GUILD_A, "plan_id": first["id"]},
                )
            )
            .mappings()
            .one()
        )
    assert provenance["plan_id"] == first["id"]
    assert provenance["source_policy_id"] == draft.policy_id
    assert int(provenance["source_policy_revision"]) == 1
    with pytest.raises(DBAPIError):
        async with tenant_transaction(factory, TenantContext(GUILD_A)) as session:
            await session.execute(
                text(
                    "UPDATE plans SET origin_metadata=jsonb_build_object('tampered',true) "
                    "WHERE guild_id=:guild_id AND id=:plan_id"
                ),
                {"guild_id": GUILD_A, "plan_id": first["id"]},
            )

    pre_apply_before_activation = await planning.recheck(
        guild_id=GUILD_A,
        plan_id=UUID(str(first["id"])),
        actor_authorization_fresh=True,
    )
    assert not pre_apply_before_activation.allowed
    assert "preflight.policy_not_active" in pre_apply_before_activation.errors

    with pytest.raises(PolicyLifecycleError):
        await policy_service.activate(
            GUILD_A,
            draft.policy_id,
            ACTOR_A,
            1,
            "reject-activation-without-policy-plan",
            uuid4(),
        )

    active = await policy_service.activate(
        GUILD_A,
        draft.policy_id,
        ACTOR_A,
        1,
        "activate-from-validated-plan",
        UUID(str(first["id"])),
    )
    assert active.lifecycle_state is PolicyLifecycleState.ACTIVE
    pre_apply_after_activation = await planning.recheck(
        guild_id=GUILD_A,
        plan_id=UUID(str(first["id"])),
        actor_authorization_fresh=True,
    )
    assert pre_apply_after_activation.allowed, pre_apply_after_activation
    with pytest.raises(PolicyNotFound):
        await policy_service.get(GUILD_B, draft.policy_id)
    with pytest.raises(PlanNotFound):
        await plans.get_plan(GUILD_B, UUID(str(first["id"])))


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
