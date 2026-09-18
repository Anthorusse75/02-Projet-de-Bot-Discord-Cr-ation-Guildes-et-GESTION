"""REQ-AP-LOCK-*/REQ-AP-TST-005: real PostgreSQL proof of the locked-Policy
drift/auto-reconciliation loop -- mutation externe -> détection -> remise en
conformité, and a reconciliation-failure path, both against real Policy/Plan
persistence rather than mocks.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from did.application.discord_runtime import normalize_gateway_dispatch
from did.application.planning.service import PlanningService
from did.application.policies.planning import PolicyPlanningService
from did.application.policies.reconciler import PolicyReconcilerService, ReconcileOutcome
from did.application.policies.service import POLICY_RECONCILER_ACTOR_ID, PolicyService
from did.domain.policies import PolicyScopeType
from did.infrastructure.database import create_database_engine, tenant_transaction
from did.infrastructure.discord.mutations import (
    MutationResult,
    PreconditionOutcome,
    RecoveryOutcome,
    RecoveryResult,
)
from did.infrastructure.planning_repository import PlanningRepository
from did.infrastructure.policies_repository import PoliciesRepository
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage04_repository import Stage04Repository
from did.permissions import DEFAULT_PERMISSION_REGISTRY
from did.planning.models import PlanState
from did.tenancy import TenantContext
from did.worker.io.plan_executor import ApplyPlanExecutor

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.failure_injection]

APP_URL = os.environ.get(
    "DID_DATABASE_URL",
    "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test",
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD = 884_005_001
ACTOR = 884_005_011
BOT = 884_005_021
ROLE = 884_005_031
MEMBER = 884_005_041
CHANNEL = 884_005_101
BOT_ROLE = 884_005_061
VIEW_BIT = DEFAULT_PERMISSION_REGISTRY.value("VIEW_CHANNEL")


_ReconcilerContext = tuple[
    PoliciesRepository,
    PolicyService,
    PolicyReconcilerService,
    PlanningRepository,
    PlanningService,
]


@pytest.fixture
async def reconciler_context() -> AsyncIterator[_ReconcilerContext]:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=2)
    app_engine = create_database_engine(APP_URL, pool_size=4)
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(
                text("SELECT set_config('app.tenant_purge_in_progress', 'on', true)")
            )
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id=:g"), {"g": GUILD}
            )
            await connection.execute(
                text(
                    "INSERT INTO users (discord_user_id,username) VALUES (:id,:name) "
                    "ON CONFLICT (discord_user_id) DO NOTHING"
                ),
                {"id": ACTOR, "name": f"reconciler-user-{ACTOR}"},
            )
            await connection.execute(
                text(
                    "INSERT INTO guild_installations "
                    "(guild_id,name,owner_id,installation_status,application_id,bot_user_id) "
                    "VALUES (:guild_id,:name,:owner_id,'ACTIVE',:bot_id,:bot_id)"
                ),
                {
                    "guild_id": GUILD,
                    "name": f"Reconciler {GUILD}",
                    "owner_id": ACTOR,
                    "bot_id": BOT,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO discord_cache_coverage "
                    "(guild_id,coverage_mode,freshness_state,known_channels,"
                    "visible_channels,known_roles,members_complete) "
                    "VALUES (:guild_id,'FULL','FRESH',1,1,3,true)"
                ),
                {"guild_id": GUILD},
            )
            await connection.execute(
                text(
                    "INSERT INTO discord_roles_cache "
                    "(guild_id,role_id,name,position,permissions_bits,managed,color,hoist,"
                    "mentionable,raw_json,last_gateway_seen_at) VALUES "
                    "(:guild_id,:guild_id,'@everyone',0,0,false,0,false,false,"
                    "CAST('{}' AS jsonb),now()),"
                    "(:guild_id,:role_id,'managers',1,0,false,0,false,false,"
                    "CAST('{}' AS jsonb),now()),"
                    "(:guild_id,:bot_role_id,'bot',2,:bot_permissions,false,0,false,false,"
                    "CAST('{}' AS jsonb),now())"
                ),
                {
                    "guild_id": GUILD,
                    "role_id": ROLE,
                    "bot_role_id": BOT_ROLE,
                    # A dedicated bot-only role (never @everyone/managers, which
                    # must stay at 0 -- MEMBER's VIEW must come solely from the
                    # Policy's channel overwrite, or the drift scenario becomes
                    # a no-op): ADMINISTRATOR both grants the bot everything it
                    # needs to create the corrective overwrite (real Discord
                    # bots managing server infrastructure are typically
                    # ADMINISTRATOR) and, via the same OWNER_BYPASS-shaped
                    # exemption in did.policies.drift, keeps the bot itself out
                    # of the Policy drift comparison -- Discord's real
                    # ADMINISTRATOR bypass means the bot always sees this
                    # channel regardless of the Policy, so it is never a
                    # meaningful drift subject.
                    "bot_permissions": 1 << 3,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO discord_channels_cache "
                    "(guild_id,channel_id,type,name,position,last_full_payload,"
                    "observability_state,freshness_state,last_full_observed_at) VALUES "
                    "(:guild_id,:channel_id,0,'board',0,CAST('{}' AS jsonb),"
                    "'VISIBLE','FRESH',now())"
                ),
                {"guild_id": GUILD, "channel_id": CHANNEL},
            )
            await connection.execute(
                text(
                    "INSERT INTO discord_member_authorization_cache "
                    "(guild_id,discord_user_id,role_ids,source,validity,observed_at,is_bot) "
                    "VALUES "
                    "(:guild_id,:owner_id,ARRAY[:guild_id]::bigint[],'GATEWAY','FRESH',now(),false),"
                    "(:guild_id,:bot_id,ARRAY[:bot_role_id]::bigint[],'GATEWAY','FRESH',now(),true),"
                    "(:guild_id,:member_id,ARRAY[:role_id]::bigint[],'GATEWAY','FRESH',now(),false)"
                ),
                {
                    "guild_id": GUILD,
                    "owner_id": ACTOR,
                    "bot_id": BOT,
                    "member_id": MEMBER,
                    "role_id": ROLE,
                    "bot_role_id": BOT_ROLE,
                },
            )
        factory = async_sessionmaker(app_engine, expire_on_commit=False)
        policies_repository = PoliciesRepository(factory)
        stage04_repository = Stage04Repository(factory)
        policy_service = PolicyService(policies_repository, read_models=stage04_repository)
        policy_planning = PolicyPlanningService(
            policies=policy_service, read_models=stage04_repository
        )
        planning_repository = PlanningRepository(factory)
        planning_service = PlanningService(
            planning_repository, stage04_repository, policy_preflight=policy_planning
        )
        policy_planning.bind_planning(planning_service)
        reconciler = PolicyReconcilerService(
            policies=policy_service, policy_planning=policy_planning, planning=planning_service
        )
        yield policies_repository, policy_service, reconciler, planning_repository, planning_service
    finally:
        async with admin_engine.begin() as connection:
            await connection.execute(
                text("SELECT set_config('app.tenant_purge_in_progress', 'on', true)")
            )
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id=:g"), {"g": GUILD}
            )
            await connection.execute(
                text("DELETE FROM users WHERE discord_user_id=:a"), {"a": ACTOR}
            )
        await app_engine.dispose()
        await admin_engine.dispose()


async def _create_active_locked_policy(repository: PoliciesRepository, service: PolicyService):
    draft = await service.create_draft(
        guild_id=GUILD,
        actor_id=ACTOR,
        policy_type="ACCESS_CONTROL",
        contract_version=1,
        name="Locked board visibility",
        description="",
        scope_type=PolicyScopeType.CHANNEL,
        scope_id=str(CHANNEL),
        conditions=[{"kind": "ROLE_MATCH", "match": "ANY", "role_ids": [str(ROLE)]}],
        effects=[{"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"}],
        metadata={"summary": "Locked board visibility"},
        idempotency_key=f"reconciler-create-{uuid4()}",
    )
    repository.assert_activation_plan = AsyncMock(return_value={"id": uuid4()})  # type: ignore[method-assign]
    active = await service.activate(
        GUILD, draft.policy_id, ACTOR, draft.revision, f"reconciler-activate-{uuid4()}", uuid4()
    )
    del repository.assert_activation_plan
    locked = await service.set_locked(
        GUILD,
        active.policy_id,
        ACTOR,
        locked=True,
        expected_revision=active.revision,
        idempotency_key=f"reconciler-lock-{uuid4()}",
    )
    return locked


async def _set_real_overwrite(factory, *, allow: int) -> None:
    async with tenant_transaction(factory, TenantContext(GUILD)) as session:
        await session.execute(
            text(
                "DELETE FROM channel_overwrites_cache "
                "WHERE guild_id=:g AND channel_id=:c AND target_id=:m"
            ),
            {"g": GUILD, "c": CHANNEL, "m": MEMBER},
        )
        if allow:
            await session.execute(
                text(
                    "INSERT INTO channel_overwrites_cache "
                    "(guild_id,channel_id,target_id,target_type,allow_bits,deny_bits,"
                    "last_full_observed_at) VALUES "
                    "(:g,:c,:m,1,:allow,0,now())"
                ),
                {"g": GUILD, "c": CHANNEL, "m": MEMBER, "allow": allow},
            )


@pytest.mark.asyncio
async def test_external_gateway_access_change_enqueues_event_driven_reconcile(
    reconciler_context,
) -> None:
    repository, _service, _reconciler, _planning_repository, _planning_service = reconciler_context
    factory = object.__getattribute__(repository, "_factory")
    runtime = RuntimeRepository(factory)
    envelope = normalize_gateway_dispatch(
        {
            "op": 0,
            "s": 42,
            "t": "CHANNEL_UPDATE",
            "d": {
                "guild_id": str(GUILD),
                "id": str(CHANNEL),
                "type": 0,
                "position": 0,
                "parent_id": None,
                "name": "board",
                "topic": None,
                "nsfw": False,
                "flags": 0,
                "permission_overwrites": [],
            },
        },
        discord_session_id="policy-reconcile-gateway",
        received_at=datetime.now(UTC),
    )
    assert envelope is not None

    assert await runtime.ingest_gateway_event(envelope) is True

    async with tenant_transaction(factory, TenantContext(GUILD)) as session:
        job = (
            (
                await session.execute(
                    text(
                        "SELECT workload_type,logical_key,payload FROM discord_io_jobs "
                        "WHERE guild_id=:g AND workload_type='RECONCILE_STRUCTURE'"
                    ),
                    {"g": GUILD},
                )
            )
            .mappings()
            .one()
        )
    assert job["logical_key"] == "reconcile:structure"
    assert job["payload"]["reason"] == "gateway-external-change"


@pytest.mark.asyncio
async def test_locked_policy_drift_is_detected_and_auto_repaired(reconciler_context) -> None:
    repository, service, reconciler, planning_repository, planning_service = reconciler_context
    policy = await _create_active_locked_policy(repository, service)
    factory = object.__getattribute__(repository, "_factory")

    # Discord already reflects the locked Policy: nothing to do.
    await _set_real_overwrite(factory, allow=VIEW_BIT)
    compliant_results = await reconciler.reconcile_guild(GUILD)
    assert compliant_results == (
        type(compliant_results[0])(policy.policy_id, ReconcileOutcome.COMPLIANT),
    )
    versions_before = await repository.versions(GUILD, policy.policy_id)
    assert [value.change_kind for value in versions_before] == ["CREATE", "ACTIVATE", "ANNOTATE"]

    # REQ-AP-LOCK-002/003: an external mutation (the member overwrite is
    # removed outside DID) is detected and auto-repaired without any manual
    # confirmation step.
    await _set_real_overwrite(factory, allow=0)
    repaired_results = await reconciler.reconcile_guild(GUILD)
    assert len(repaired_results) == 1
    assert repaired_results[0].outcome is ReconcileOutcome.REPAIR_SCHEDULED

    # Enqueueing alone is deliberately not called "repaired" and does not
    # increment the Policy revision before final worker preflight.
    versions_scheduled = await repository.versions(GUILD, policy.policy_id)
    assert [value.change_kind for value in versions_scheduled] == [
        "CREATE",
        "ACTIVATE",
        "ANNOTATE",
    ]

    # Execute the real canonical Plan worker against the persisted Plan/job.
    # The adapter boundary is fake, but Plan fencing, final preflight,
    # operation persistence, verification and completion annotation are real.
    runtime = RuntimeRepository(factory)
    leased = await runtime.lease_next_job(
        GUILD, lease_owner="policy-reconciler-test", lease_seconds=30
    )
    assert leased is not None and leased["workload_type"] == "APPLY_PLAN"
    executor = ApplyPlanExecutor(
        planning_repository,
        _SuccessfulOverwriteAdapter(),  # type: ignore[arg-type]
        _PassLock(),  # type: ignore[arg-type]
        worker_id="policy-reconciler-test",
        authorization=_RejectSyntheticActorAuthorization(),
        preflight=planning_service,
        completion=reconciler,
    )
    await executor.execute_leased(GUILD, leased, None)

    # REQ-AP-LOCK-004: only verified completion is annotated as repaired,
    # with initiator POLICY_RECONCILER and the Plan's before/desired state in
    # the canonical Plan/operation audit.
    versions_after = await repository.versions(GUILD, policy.policy_id)
    assert [value.change_kind for value in versions_after] == [
        "CREATE",
        "ACTIVATE",
        "ANNOTATE",
        "ANNOTATE",
    ]
    repaired_version = versions_after[-1]
    assert repaired_version.author_user_id == POLICY_RECONCILER_ACTOR_ID
    assert "reconciler:repaired" in repaired_version.snapshot["metadata"]["tags"]

    async with tenant_transaction(factory, TenantContext(GUILD)) as session:
        plan_row = (
            (
                await session.execute(
                    text(
                        "SELECT id,status FROM plans WHERE guild_id=:g AND origin_type='POLICY' "
                        "AND source_policy_id=:p ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"g": GUILD, "p": policy.policy_id},
                )
            )
            .mappings()
            .one()
        )
        assert plan_row["status"] == PlanState.SUCCEEDED.value
        job_row = (
            (
                await session.execute(
                    text(
                        "SELECT workload_type FROM discord_io_jobs WHERE guild_id=:g "
                        "AND workload_type='APPLY_PLAN' AND payload->>'plan_id'=:plan_id"
                    ),
                    {"g": GUILD, "plan_id": str(plan_row["id"])},
                )
            )
            .mappings()
            .one_or_none()
        )
        assert job_row is not None


@pytest.mark.asyncio
async def test_reconciliation_failure_marks_intervention_required_not_compliant(
    reconciler_context,
) -> None:
    repository, service, reconciler, _planning_repository, _planning_service = reconciler_context
    policy = await _create_active_locked_policy(repository, service)
    factory = object.__getattribute__(repository, "_factory")
    await _set_real_overwrite(factory, allow=0)

    # Force the drift-plan compilation to fail (simulating an impossible
    # correction, e.g. a revoked bot capability) by retiring the coverage to
    # incomplete right before the sweep -- detect_drift() must fail closed.
    async with tenant_transaction(factory, TenantContext(GUILD)) as session:
        await session.execute(
            text("UPDATE discord_cache_coverage SET members_complete=false WHERE guild_id=:g"),
            {"g": GUILD},
        )

    results = await reconciler.reconcile_guild(GUILD)

    assert len(results) == 1
    assert results[0].outcome is ReconcileOutcome.INTERVENTION_REQUIRED
    versions = await repository.versions(GUILD, policy.policy_id)
    tags = versions[-1].snapshot["metadata"]["tags"]
    assert "reconciler:intervention_required" in tags
    # REQ-AP-LOCK-005: never silently "compliant" or "repaired" when the
    # comparison itself could not be trusted.
    assert "reconciler:repaired" not in tags


@pytest.mark.asyncio
async def test_unlocked_drift_exception_is_persisted_as_an_audited_annotation(
    reconciler_context,
) -> None:
    repository, service, _reconciler, _planning_repository, _planning_service = reconciler_context
    locked = await _create_active_locked_policy(repository, service)
    unlocked = await service.set_locked(
        GUILD,
        locked.policy_id,
        ACTOR,
        locked=False,
        expected_revision=locked.revision,
        idempotency_key=f"reconciler-unlock-{uuid4()}",
    )

    accepted = await service.accept_drift_exception(
        GUILD,
        unlocked.policy_id,
        ACTOR,
        drift_fingerprint="f" * 64,
        expected_revision=unlocked.revision,
        idempotency_key=f"accept-drift-{uuid4()}",
    )

    assert accepted.locked is False
    assert "drift-exception:" + "f" * 40 in accepted.metadata["tags"]
    versions = await repository.versions(GUILD, accepted.policy_id)
    assert versions[-1].change_kind == "ANNOTATE"
    assert versions[-1].author_user_id == ACTOR


class _PassLock:
    async def run(self, guild_id: int, operation: Any) -> Any:
        assert guild_id == GUILD
        return await operation()


class _RejectSyntheticActorAuthorization:
    async def authorize_apply(self, *, guild_id: int, actor_user_id: int) -> None:
        raise AssertionError(
            f"automatic repair must use locked-Policy authorization, got {guild_id}/{actor_user_id}"
        )


class _SuccessfulOverwriteAdapter:
    async def check_preconditions(self, **kwargs: Any) -> PreconditionOutcome:
        del kwargs
        return PreconditionOutcome.SATISFIED

    async def execute(self, **kwargs: Any) -> MutationResult:
        payload = dict(kwargs["payload"])
        return MutationResult(204, payload, "d" * 64)

    async def recover(self, **kwargs: Any) -> RecoveryResult:
        del kwargs
        return RecoveryResult(RecoveryOutcome.PROVED_APPLIED, None)

    async def verify(self, **kwargs: Any) -> bool:
        del kwargs
        return True
