from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from did.application.discord_runtime import normalize_gateway_dispatch
from did.application.planning.service import PlanningService
from did.application.translation.lifecycle import Stage08PostVerificationMaterializer
from did.domain.discord_runtime import (
    DiscordErrorKind,
    DiscordFailure,
    WorkloadJob,
    WorkloadPriority,
)
from did.infrastructure.database import (
    create_database_engine,
    create_session_factory,
    tenant_transaction,
)
from did.infrastructure.discord.mutations import (
    MutableDiscordError,
    MutationResult,
    PreconditionOutcome,
    RecoveryOutcome,
    RecoveryResult,
)
from did.infrastructure.planning_lock import (
    GuildMutationLockUnavailable,
    RedisGuildMutationLock,
)
from did.infrastructure.planning_repository import (
    ConfirmationInvalid,
    PlanFencingError,
    PlanningRepository,
    PlanNotFound,
)
from did.infrastructure.redis import create_redis_client
from did.infrastructure.runtime_redis import OutboxPublisher
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage08_lifecycle_repository import Stage08LifecycleRepository
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    TranslationGroupRepository,
    TranslationProviderBindingRepository,
)
from did.planning.canonical import canonical_hash
from did.planning.models import (
    CompensationClass,
    DesiredNode,
    DesiredStateGraph,
    OperationType,
    PlanOperation,
    PlanState,
    RecoveryStrategy,
    ResourceType,
    RiskLevel,
    VerificationStrategy,
    freeze_json_object,
)
from did.planning.risk import ImpactSummary, RiskAssessment
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
GUILD_A = 550505050505050501
GUILD_B = 550505050505050502
ACTOR = 550505050505050503
ACTOR_B = 550505050505050507
BOT = 550505050505050504
CREATED_ROLE = 550505050505050505
CREATED_CHANNEL = 550505050505050506


async def seed() -> None:
    engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE users, guild_installations CASCADE"))
            await connection.execute(
                text(
                    "INSERT INTO users (discord_user_id,username) VALUES "
                    "(:id,'stage05'),(:other,'stage05-other')"
                ),
                {"id": ACTOR, "other": ACTOR_B},
            )
            await connection.execute(
                text(
                    "INSERT INTO guild_installations "
                    "(guild_id,name,owner_id,installation_status,application_id,bot_user_id) "
                    "VALUES (:a,'A',:actor,'ACTIVE',:bot,:bot),"
                    "(:b,'B',:actor,'ACTIVE',:bot,:bot)"
                ),
                {"a": GUILD_A, "b": GUILD_B, "actor": ACTOR, "bot": BOT},
            )
    finally:
        await engine.dispose()


async def test_stage08_role_binding_is_materialized_only_after_targeted_verification() -> None:
    engine, plans, runtime, plan_id, _, _ = await prepare_apply_case()
    factory = create_session_factory(engine)
    languages = LanguageProfileRepository(factory)
    lifecycle = Stage08LifecycleRepository(factory)
    adapter = FakeMutationAdapter()
    try:
        language = await languages.create(
            guild_id=GUILD_A,
            code="fr",
            display_name="Français",
        )
        reservations = await asyncio.gather(
            lifecycle.reserve_role(
                guild_id=GUILD_A,
                binding_kind="LANGUAGE",
                binding_key=f"language:{language['id']}",
                language_profile_id=UUID(str(language["id"])),
                symbol="sym.role.stage05",
            ),
            lifecycle.reserve_role(
                guild_id=GUILD_A,
                binding_kind="LANGUAGE",
                binding_key=f"language:{language['id']}",
                language_profile_id=UUID(str(language["id"])),
                symbol="sym.role.stage05",
            ),
        )
        assert sum(1 for _, created in reservations if created) == 1
        reservation = next(row for row, created in reservations if created)
        assert (
            await lifecycle.language_binding(
                guild_id=GUILD_A,
                language_profile_id=UUID(str(language["id"])),
            )
            is None
        )
        await lifecycle.attach_role_plan(
            guild_id=GUILD_A,
            reservation_id=UUID(str(reservation["id"])),
            plan_id=plan_id,
            intent_type="BIND_LANGUAGE_ROLE",
            payload={
                "reservation_id": str(reservation["id"]),
                "language_profile_id": str(language["id"]),
                "symbol": "sym.role.stage05",
            },
        )
        assert (
            await lifecycle.language_binding(
                guild_id=GUILD_A,
                language_profile_id=UUID(str(language["id"])),
            )
            is None
        )
        leased = await runtime.lease_next_job(
            GUILD_A,
            lease_owner="stage08-materializer",
            lease_seconds=30,
        )
        assert leased is not None
        executor = ApplyPlanExecutor(
            plans,
            adapter,
            PassLock(),  # type: ignore[arg-type]
            worker_id="stage08-materializer",
            authorization=AllowAuthorization(),
            post_verification=Stage08PostVerificationMaterializer(lifecycle),
        )
        await executor.execute_leased(GUILD_A, leased, None)
        binding = await lifecycle.language_binding(
            guild_id=GUILD_A,
            language_profile_id=UUID(str(language["id"])),
        )
        assert adapter.verify_calls == 1
        assert binding is not None
        assert int(binding["discord_role_id"]) == CREATED_ROLE
        assert (await plans.get_plan(GUILD_A, plan_id))["status"] == "SUCCEEDED"
    finally:
        await engine.dispose()


async def test_stage08_channel_variant_is_materialized_only_after_targeted_verification() -> None:
    engine, plans, runtime, plan_id, _, _ = await prepare_apply_case(channel=True)
    factory = create_session_factory(engine)
    languages = LanguageProfileRepository(factory)
    groups = TranslationGroupRepository(factory)
    lifecycle = Stage08LifecycleRepository(factory)
    adapter = FakeMutationAdapter()
    try:
        language = await languages.create(
            guild_id=GUILD_A,
            code="fr",
            display_name="French",
        )
        group = await groups.create(
            guild_id=GUILD_A,
            name="Localized channels",
            root_kind="CHANNEL_SET",
            routing_mode="HUB_AND_SPOKE",
            group_id=uuid4(),
        )
        await groups.add_language(
            guild_id=GUILD_A,
            translation_group_id=UUID(str(group["id"])),
            language_profile_id=UUID(str(language["id"])),
        )
        channel_group = await groups.create_channel_group(
            guild_id=GUILD_A,
            translation_group_id=UUID(str(group["id"])),
            logical_key="general",
        )
        variant_id = uuid4()
        await lifecycle.add_plan_intent(
            guild_id=GUILD_A,
            plan_id=plan_id,
            intent_key=f"variant:{variant_id}",
            intent_type="MATERIALIZE_CHANNEL_VARIANT",
            payload={
                "variant_id": str(variant_id),
                "translation_group_id": str(group["id"]),
                "translation_channel_group_id": str(channel_group["id"]),
                "language_profile_id": str(language["id"]),
                "symbol": "sym.channel.stage05",
            },
        )
        leased = await runtime.lease_next_job(
            GUILD_A,
            lease_owner="stage08-channel-materializer",
            lease_seconds=30,
        )
        assert leased is not None
        executor = ApplyPlanExecutor(
            plans,
            adapter,
            PassLock(),  # type: ignore[arg-type]
            worker_id="stage08-channel-materializer",
            authorization=AllowAuthorization(),
            post_verification=Stage08PostVerificationMaterializer(lifecycle),
        )
        await executor.execute_leased(GUILD_A, leased, None)
        variant = await groups.get_variant(
            guild_id=GUILD_A,
            translation_group_id=UUID(str(group["id"])),
            variant_id=variant_id,
            variant_type="CHANNEL",
        )
        assert adapter.verify_calls == 1
        assert int(variant["discord_channel_id"]) == CREATED_CHANNEL
        assert variant["state"] == "ACTIVE"
        assert (await plans.get_plan(GUILD_A, plan_id))["status"] == "SUCCEEDED"
    finally:
        await engine.dispose()


async def test_stage08_provider_becomes_manual_only_after_structure_verification() -> None:
    engine, plans, runtime, plan_id, _, _ = await prepare_apply_case(channel=True)
    factory = create_session_factory(engine)
    providers = TranslationProviderBindingRepository(factory)
    groups = TranslationGroupRepository(factory)
    lifecycle = Stage08LifecycleRepository(factory)
    adapter = FakeMutationAdapter()
    try:
        provider = await providers.create(
            guild_id=GUILD_A,
            provider_type="existing_translation_bot",
            provider_instance_key="stage08-post-verify",
            capabilities={"supports_hub_and_spoke": True},
            status="UNKNOWN",
        )
        group = await groups.create(
            guild_id=GUILD_A,
            name="Provider lifecycle",
            root_kind="CHANNEL_SET",
            routing_mode="HUB_AND_SPOKE",
            provider_binding_id=UUID(str(provider["id"])),
        )
        await lifecycle.add_plan_intent(
            guild_id=GUILD_A,
            plan_id=plan_id,
            intent_key=f"provider:{provider['id']}",
            intent_type="VERIFY_PROVIDER",
            payload={
                "binding_id": str(provider["id"]),
                "translation_group_id": str(group["id"]),
                "verified_status": "MANUAL_CONFIGURATION_REQUIRED",
            },
        )
        assert (await providers.get(guild_id=GUILD_A, binding_id=UUID(str(provider["id"]))))[
            "status"
        ] == "UNKNOWN"
        leased = await runtime.lease_next_job(
            GUILD_A,
            lease_owner="stage08-provider-materializer",
            lease_seconds=30,
        )
        assert leased is not None
        executor = ApplyPlanExecutor(
            plans,
            adapter,
            PassLock(),  # type: ignore[arg-type]
            worker_id="stage08-provider-materializer",
            authorization=AllowAuthorization(),
            post_verification=Stage08PostVerificationMaterializer(lifecycle),
        )
        await executor.execute_leased(GUILD_A, leased, None)
        verified = await providers.get(
            guild_id=GUILD_A,
            binding_id=UUID(str(provider["id"])),
        )
        assert adapter.verify_calls == 1
        assert verified["status"] == "MANUAL_CONFIGURATION_REQUIRED"
        assert verified["last_validated_at"] is None
        assert (await groups.get(GUILD_A, UUID(str(group["id"]))))["status"] == ("PROVIDER_PENDING")
        plan = await plans.get_plan(GUILD_A, plan_id)
        assert plan["status"] == "APPLIED_WITH_PENDING_PROVIDER"
        assert plan["error_code"] == "PROVIDER_MANUAL_CONFIGURATION_REQUIRED"
        assert plan["verification_summary"]["discord_verified"] is True
        assert plan["verification_summary"]["post_verification_outcome"] == ("PENDING_PROVIDER")
    finally:
        await engine.dispose()


async def test_stage08_post_verification_failure_never_claims_plan_success() -> None:
    engine, plans, runtime, plan_id, _, _ = await prepare_apply_case()
    lifecycle = Stage08LifecycleRepository(create_session_factory(engine))
    adapter = FakeMutationAdapter()
    try:
        await lifecycle.add_plan_intent(
            guild_id=GUILD_A,
            plan_id=plan_id,
            intent_key="unsupported-clone",
            intent_type="MATERIALIZE_CLONE",
            payload={"destination_group_id": str(uuid4())},
        )
        leased = await runtime.lease_next_job(
            GUILD_A,
            lease_owner="stage08-failed-materializer",
            lease_seconds=30,
        )
        assert leased is not None
        executor = ApplyPlanExecutor(
            plans,
            adapter,
            PassLock(),  # type: ignore[arg-type]
            worker_id="stage08-failed-materializer",
            authorization=AllowAuthorization(),
            post_verification=Stage08PostVerificationMaterializer(lifecycle),
        )
        await executor.execute_leased(GUILD_A, leased, None)
        plan = await plans.get_plan(GUILD_A, plan_id)
        assert adapter.verify_calls == 1
        assert plan["status"] == "PARTIALLY_APPLIED"
        assert plan["error_code"] == "STAGE08_POST_VERIFICATION_FAILED"
        assert plan["verification_summary"]["discord_verified"] is True
        assert plan["verification_summary"]["post_verification_applied"] is False
    finally:
        await engine.dispose()


async def test_member_role_operation_runs_through_durable_plan_and_cache_write_through() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=3)
    factory = create_session_factory(engine)
    plans = PlanningRepository(factory)
    runtime = RuntimeRepository(factory)
    plan_id = uuid4()
    correlation = uuid4()
    node = DesiredNode.build(
        logical_key=f"stage08.member.{ACTOR}.role.{CREATED_ROLE}",
        resource_type=ResourceType.MEMBER_ROLE,
        discord_id=ACTOR,
        properties={
            "member_id": ACTOR,
            "role_id": CREATED_ROLE,
            "assigned": True,
            "current_assigned": False,
        },
    )
    operation = PlanOperation(
        uuid4(),
        OperationType.ADD_MEMBER_ROLE,
        ResourceType.MEMBER_ROLE,
        node.logical_key,
        freeze_json_object(
            {"id": ACTOR, "member_id": ACTOR, "role_id": CREATED_ROLE, "assigned": True}
        ),
        freeze_json_object(
            {"id": ACTOR, "member_id": ACTOR, "role_id": CREATED_ROLE, "assigned": False}
        ),
        ("MANAGE_ROLES",),
        CompensationClass.REVERSIBLE,
        RiskLevel.LOW,
        VerificationStrategy.TARGETED_GET,
        RecoveryStrategy.UPDATE_COMPARE_BEFORE_DESIRED,
        ("GUILD_MEMBER_UPDATE",),
        preconditions=freeze_json_object(
            {
                "schema_version": "did-operation-precondition-v1",
                "mode": "MATCH_BEFORE",
                "resource_type": "MEMBER_ROLE",
                "resource_id": ACTOR,
                "before": {
                    "id": ACTOR,
                    "member_id": ACTOR,
                    "role_id": CREATED_ROLE,
                    "assigned": False,
                },
            }
        ),
    )
    try:
        async with tenant_transaction(factory, TenantContext(GUILD_A)) as session:
            await session.execute(
                text(
                    "INSERT INTO discord_member_authorization_cache "
                    "(guild_id,discord_user_id,role_ids,source,validity,observed_at) "
                    "VALUES (:guild_id,:member_id,ARRAY[:everyone_id]::bigint[],"
                    "'GATEWAY','FRESH',now())"
                ),
                {"guild_id": GUILD_A, "member_id": ACTOR, "everyone_id": GUILD_A},
            )
        await persist_draft(
            plans,
            plan_id=plan_id,
            guild_id=GUILD_A,
            actor_user_id=ACTOR,
            idempotency_key="stage08-member-role-plan",
            graph=DesiredStateGraph(GUILD_A, (node,)),
            operations=(operation,),
            correlation_id=correlation,
        )
        _, leased = await confirm_enqueue_and_lease(
            plans,
            runtime,
            plan_id=plan_id,
            correlation_id=correlation,
            worker_id="stage08-member-role-worker",
        )
        executor = ApplyPlanExecutor(
            plans,
            FakeMutationAdapter(),
            PassLock(),  # type: ignore[arg-type]
            worker_id="stage08-member-role-worker",
            authorization=AllowAuthorization(),
        )
        await executor.execute_leased(GUILD_A, leased, None)
        async with tenant_transaction(factory, TenantContext(GUILD_A)) as session:
            role_ids = await session.scalar(
                text(
                    "SELECT role_ids FROM discord_member_authorization_cache "
                    "WHERE guild_id=:guild_id AND discord_user_id=:member_id"
                ),
                {"guild_id": GUILD_A, "member_id": ACTOR},
            )
        assert role_ids is not None and CREATED_ROLE in {int(value) for value in role_ids}
        assert (await plans.get_plan(GUILD_A, plan_id))["status"] == "SUCCEEDED"
    finally:
        await engine.dispose()


def graph_and_operation() -> tuple[DesiredStateGraph, PlanOperation]:
    node = DesiredNode.build(
        logical_key="role.stage05",
        resource_type=ResourceType.ROLE,
        symbol="sym.role.stage05",
        properties={"name": "DID Stage 05", "permissions": "0"},
    )
    operation = PlanOperation(
        uuid4(),
        OperationType.CREATE_ROLE,
        ResourceType.ROLE,
        node.logical_key,
        freeze_json_object(node.property_map()),
        freeze_json_object({}),
        ("MANAGE_ROLES",),
        CompensationClass.REVERSIBLE,
        RiskLevel.LOW,
        VerificationStrategy.TARGETED_LIST_AND_MATCH,
        RecoveryStrategy.CREATE_RECONCILE,
        ("GUILD_ROLE_CREATE",),
        produces_symbol=node.symbol,
    )
    return DesiredStateGraph(GUILD_A, (node,)), operation


def channel_graph_and_operation() -> tuple[DesiredStateGraph, PlanOperation]:
    node = DesiredNode.build(
        logical_key="channel.stage05",
        resource_type=ResourceType.CHANNEL,
        symbol="sym.channel.stage05",
        properties={"name": "did-stage-05", "type": 0},
    )
    operation = PlanOperation(
        uuid4(),
        OperationType.CREATE_CHANNEL,
        ResourceType.CHANNEL,
        node.logical_key,
        freeze_json_object(node.property_map()),
        freeze_json_object({}),
        ("MANAGE_CHANNELS",),
        CompensationClass.REVERSIBLE,
        RiskLevel.LOW,
        VerificationStrategy.TARGETED_LIST_AND_MATCH,
        RecoveryStrategy.CREATE_RECONCILE,
        ("CHANNEL_CREATE",),
        produces_symbol=node.symbol,
    )
    return DesiredStateGraph(GUILD_A, (node,)), operation


async def persist_draft(
    plans: PlanningRepository,
    *,
    plan_id: UUID,
    guild_id: int,
    actor_user_id: int,
    idempotency_key: str,
    graph: DesiredStateGraph,
    operations: tuple[PlanOperation, ...],
    correlation_id: UUID,
    plan_hash: str = "b" * 64,
    snapshot: dict[str, Any] | None = None,
    snapshot_hash: str = "a" * 64,
) -> tuple[dict[str, Any], bool]:
    risk = RiskAssessment(RiskLevel.LOW, 4, (), ImpactSummary(len(operations)), False)
    return await plans.create_plan(
        plan_id=plan_id,
        guild_id=guild_id,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        graph=graph,
        operations=operations,
        before_snapshot=snapshot or {"guild_id": str(guild_id)},
        base_structure_version="guild:1|coverage:1",
        base_structure_hash=snapshot_hash,
        capability_version="discord-permissions-2026-08-24",
        plan_hash=plan_hash,
        risk=risk,
        compiler_version="did-plan-compiler-v1",
        correlation_id=correlation_id,
    )


async def confirm_enqueue_and_lease(
    plans: PlanningRepository,
    runtime: RuntimeRepository,
    *,
    plan_id: UUID,
    correlation_id: UUID,
    worker_id: str,
) -> tuple[UUID, dict[str, Any]]:
    await plans.transition_plan(
        guild_id=GUILD_A,
        plan_id=plan_id,
        actor_user_id=ACTOR,
        expected=PlanState.DRAFT,
        target=PlanState.VALIDATED,
        expected_version=1,
        correlation_id=correlation_id,
    )
    await plans.confirm(
        guild_id=GUILD_A,
        plan_id=plan_id,
        actor_user_id=ACTOR,
        idempotency_key=f"confirmation-{plan_id}",
        plan_hash="b" * 64,
        risk_level=RiskLevel.LOW,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        expected_version=2,
        correlation_id=correlation_id,
    )
    job_id = await plans.enqueue_apply(
        guild_id=GUILD_A,
        plan_id=plan_id,
        actor_user_id=ACTOR,
        correlation_id=correlation_id,
    )
    leased = await runtime.lease_next_job(GUILD_A, lease_owner=worker_id, lease_seconds=30)
    assert leased is not None
    return job_id, leased


async def test_plan_lifecycle_is_tenant_scoped_fenced_and_durable() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=3)
    factory = create_session_factory(engine)
    plans = PlanningRepository(factory)
    runtime = RuntimeRepository(factory)
    graph, operation = graph_and_operation()
    correlation = uuid4()
    risk = RiskAssessment(RiskLevel.LOW, 4, (), ImpactSummary(1), False)
    plan_id = uuid4()
    worker_id = "stage05-worker"
    try:
        created, was_created = await plans.create_plan(
            plan_id=plan_id,
            guild_id=GUILD_A,
            actor_user_id=ACTOR,
            idempotency_key="create-plan-1",
            graph=graph,
            operations=(operation,),
            before_snapshot={"guild_id": str(GUILD_A)},
            base_structure_version="guild:1|coverage:1",
            base_structure_hash="a" * 64,
            capability_version="discord-permissions-2026-08-24",
            plan_hash="b" * 64,
            risk=risk,
            compiler_version="did-plan-compiler-v1",
            correlation_id=correlation,
        )
        assert was_created and created["status"] == "DRAFT"
        repeated, was_created = await plans.create_plan(
            plan_id=uuid4(),
            guild_id=GUILD_A,
            actor_user_id=ACTOR,
            idempotency_key="create-plan-1",
            graph=graph,
            operations=(operation,),
            before_snapshot={"guild_id": str(GUILD_A)},
            base_structure_version="guild:1|coverage:1",
            base_structure_hash="a" * 64,
            capability_version="discord-permissions-2026-08-24",
            plan_hash="b" * 64,
            risk=risk,
            compiler_version="did-plan-compiler-v1",
            correlation_id=correlation,
        )
        assert not was_created and UUID(str(repeated["id"])) == plan_id
        with pytest.raises(PlanNotFound):
            await plans.get_plan(GUILD_B, plan_id)

        validated = await plans.transition_plan(
            guild_id=GUILD_A,
            plan_id=plan_id,
            actor_user_id=ACTOR,
            expected=PlanState.DRAFT,
            target=PlanState.VALIDATED,
            expected_version=1,
            correlation_id=correlation,
        )
        assert validated["status"] == "VALIDATED"
        confirmed = await plans.confirm(
            guild_id=GUILD_A,
            plan_id=plan_id,
            actor_user_id=ACTOR,
            idempotency_key="confirm-1",
            plan_hash="b" * 64,
            risk_level=RiskLevel.LOW,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            expected_version=2,
            correlation_id=correlation,
        )
        assert confirmed["status"] == "CONFIRMED"
        job_id = await plans.enqueue_apply(
            guild_id=GUILD_A,
            plan_id=plan_id,
            actor_user_id=ACTOR,
            correlation_id=correlation,
        )
        leased = await runtime.lease_next_job(GUILD_A, lease_owner=worker_id, lease_seconds=30)
        assert leased is not None and UUID(str(leased["job_id"])) == job_id
        fence = {
            "guild_id": GUILD_A,
            "plan_id": plan_id,
            "job_id": job_id,
            "lease_owner": worker_id,
            "lease_token": UUID(str(leased["lease_token"])),
            "lease_generation": int(leased["lease_generation"]),
        }
        applying = await plans.begin_apply(
            **fence,
            actor_user_id=ACTOR,
            correlation_id=correlation,  # type: ignore[arg-type]
        )
        assert applying["status"] == "APPLYING"
        prepared = await plans.prepare_next_operation(**fence)  # type: ignore[arg-type]
        assert prepared is not None and prepared["status"] == "PENDING"
        await plans.mark_attempt_in_flight(
            **fence,  # type: ignore[arg-type]
            operation_id=operation.operation_id,
            attempt_id=UUID(str(prepared["attempt_id"])),
        )
        await plans.record_operation_success(
            **fence,  # type: ignore[arg-type]
            operation_id=operation.operation_id,
            attempt_id=UUID(str(prepared["attempt_id"])),
            discord_status=201,
            result_payload={
                "id": CREATED_ROLE,
                "name": "DID Stage 05",
                "position": 1,
                "permissions": 0,
                "color": 0,
                "hoist": False,
                "mentionable": False,
            },
            correlation_id=correlation,
            audit_reason_fingerprint="c" * 64,
        )
        counts = await plans.operation_counts(GUILD_A, plan_id)
        assert counts == {"SUCCEEDED": 1}
        gateway = normalize_gateway_dispatch(
            {
                "op": 0,
                "s": 1,
                "t": "GUILD_ROLE_CREATE",
                "d": {
                    "guild_id": str(GUILD_A),
                    "role": {
                        "id": str(CREATED_ROLE),
                        "name": "DID Stage 05",
                        "position": 1,
                        "permissions": "0",
                        "color": 0,
                        "hoist": False,
                        "mentionable": False,
                        "managed": False,
                    },
                },
            },
            discord_session_id="stage05-own-event",
            received_at=datetime.now(UTC),
        )
        assert gateway is not None and await runtime.ingest_gateway_event(gateway)
        assert (await plans.get_plan(GUILD_A, plan_id))["status"] == "APPLYING"
        await plans.finalize_plan(
            guild_id=GUILD_A,
            plan_id=plan_id,
            status=PlanState.SUCCEEDED,
            verification_summary={"verified": True},
            error_code=None,
            correlation_id=correlation,
        )
        assert (await plans.get_plan(GUILD_A, plan_id))["status"] == "SUCCEEDED"
        assert await runtime.complete_job(
            GUILD_A,
            job_id,
            lease_owner=worker_id,
            lease_token=UUID(str(leased["lease_token"])),
        )

        admin_engine = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin_engine.begin() as connection:
                with pytest.raises(DBAPIError):
                    await connection.execute(
                        text("UPDATE plans SET compiler_version='tampered' WHERE id=:id"),
                        {"id": plan_id},
                    )
        finally:
            await admin_engine.dispose()
    finally:
        await engine.dispose()


def test_apply_plan_workload_uses_highest_priority() -> None:
    job = WorkloadJob(
        uuid4(),
        GUILD_A,
        "APPLY_PLAN",
        "apply-plan:test",
        WorkloadPriority.APPLY_CONTINUATION,
        datetime.now(UTC),
    )
    assert int(job.priority) == 0


class PassLock:
    async def run(self, guild_id: int, operation: Any) -> Any:
        del guild_id
        return await operation()


class AllowAuthorization:
    async def authorize_apply(self, *, guild_id: int, actor_user_id: int) -> None:
        assert guild_id == GUILD_A
        assert actor_user_id == ACTOR


class CrashAfterDiscord:
    async def checkpoint(self, name: str) -> None:
        if name == "E_AFTER_DISCORD_BEFORE_COMMIT":
            raise RuntimeError("injected worker crash")


class CrashAt:
    def __init__(self, checkpoint: str) -> None:
        self.target = checkpoint

    async def checkpoint(self, name: str) -> None:
        if name == self.target:
            raise RuntimeError(f"injected crash at {name}")


class FakeMutationAdapter:
    def __init__(
        self,
        recovery_outcome: RecoveryOutcome = RecoveryOutcome.PROVED_CREATED,
    ) -> None:
        self.create_calls = 0
        self.verify_calls = 0
        self.recover_calls = 0
        self.recovery_outcome = recovery_outcome

    async def check_preconditions(self, **kwargs: Any) -> PreconditionOutcome:
        del kwargs
        return PreconditionOutcome.SATISFIED

    async def execute(self, **kwargs: Any) -> MutationResult:
        operation_type = kwargs["operation_type"]
        self.create_calls += 1
        if operation_type in {
            OperationType.ADD_MEMBER_ROLE,
            OperationType.REMOVE_MEMBER_ROLE,
        }:
            payload = kwargs.get("payload", {})
            return MutationResult(
                204,
                {
                    "id": int(payload["member_id"]),
                    "member_id": int(payload["member_id"]),
                    "role_id": int(payload["role_id"]),
                    "assigned": operation_type is OperationType.ADD_MEMBER_ROLE,
                },
                "d" * 64,
            )
        if operation_type is OperationType.CREATE_CHANNEL:
            return MutationResult(
                201,
                {
                    "id": CREATED_CHANNEL,
                    "name": "did-stage-05",
                    "type": 0,
                    "position": 1,
                },
                "d" * 64,
            )
        return MutationResult(
            201,
            {
                "id": CREATED_ROLE,
                "name": "DID Stage 05",
                "position": 1,
                "permissions": 0,
                "color": 0,
                "hoist": False,
                "mentionable": False,
            },
            "d" * 64,
        )

    async def recover(self, **kwargs: Any) -> RecoveryResult:
        operation_type = kwargs["operation_type"]
        self.recover_calls += 1
        if (
            operation_type is OperationType.CREATE_CHANNEL
            and self.recovery_outcome is not RecoveryOutcome.PROVED_ABSENT
        ):
            return RecoveryResult(
                self.recovery_outcome,
                {
                    "id": CREATED_CHANNEL,
                    "name": "did-stage-05",
                    "type": 0,
                    "position": 1,
                },
            )
        return RecoveryResult(
            self.recovery_outcome,
            (
                {
                    "id": CREATED_ROLE,
                    "name": "DID Stage 05",
                    "position": 1,
                    "permissions": 0,
                    "color": 0,
                    "hoist": False,
                    "mentionable": False,
                }
                if self.recovery_outcome is not RecoveryOutcome.PROVED_ABSENT
                else None
            ),
        )

    async def verify(self, **kwargs: Any) -> bool:
        del kwargs
        self.verify_calls += 1
        return True


async def prepare_apply_case(
    *, channel: bool = False
) -> tuple[Any, PlanningRepository, RuntimeRepository, UUID, UUID, UUID]:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=3)
    factory = create_session_factory(engine)
    plans = PlanningRepository(factory)
    runtime = RuntimeRepository(factory)
    graph, operation = channel_graph_and_operation() if channel else graph_and_operation()
    plan_id = uuid4()
    correlation = uuid4()
    risk = RiskAssessment(RiskLevel.LOW, 4, (), ImpactSummary(1), False)
    await plans.create_plan(
        plan_id=plan_id,
        guild_id=GUILD_A,
        actor_user_id=ACTOR,
        idempotency_key=f"fault-plan-{plan_id}",
        graph=graph,
        operations=(operation,),
        before_snapshot={"guild_id": str(GUILD_A)},
        base_structure_version="guild:1|coverage:1",
        base_structure_hash="a" * 64,
        capability_version="discord-permissions-2026-08-24",
        plan_hash=("f" if channel else "e") * 64,
        risk=risk,
        compiler_version="did-plan-compiler-v1",
        correlation_id=correlation,
    )
    await plans.transition_plan(
        guild_id=GUILD_A,
        plan_id=plan_id,
        actor_user_id=ACTOR,
        expected=PlanState.DRAFT,
        target=PlanState.VALIDATED,
        expected_version=1,
        correlation_id=correlation,
    )
    await plans.confirm(
        guild_id=GUILD_A,
        plan_id=plan_id,
        actor_user_id=ACTOR,
        idempotency_key=f"fault-confirm-{plan_id}",
        plan_hash=("f" if channel else "e") * 64,
        risk_level=RiskLevel.LOW,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        expected_version=2,
        correlation_id=correlation,
    )
    job_id = await plans.enqueue_apply(
        guild_id=GUILD_A,
        plan_id=plan_id,
        actor_user_id=ACTOR,
        correlation_id=correlation,
    )
    return engine, plans, runtime, plan_id, job_id, correlation


async def prepare_channel_apply_case() -> tuple[
    Any, PlanningRepository, RuntimeRepository, UUID, UUID, UUID
]:
    return await prepare_apply_case(channel=True)


async def expire_job(job_id: UUID) -> None:
    admin = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with admin.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE discord_io_jobs SET leased_until=now()-interval '1 second' "
                    "WHERE job_id=:job"
                ),
                {"job": job_id},
            )
    finally:
        await admin.dispose()


@pytest.mark.parametrize(
    ("checkpoint", "calls_before_recovery", "recovery_outcome"),
    (
        ("A_BEFORE_PREPARED_COMMIT", 0, RecoveryOutcome.PROVED_CREATED),
        ("B_AFTER_PREPARED_BEFORE_IN_FLIGHT", 0, RecoveryOutcome.PROVED_CREATED),
        ("C_AFTER_IN_FLIGHT_BEFORE_NETWORK", 0, RecoveryOutcome.PROVED_ABSENT),
        ("E_AFTER_DISCORD_BEFORE_COMMIT", 1, RecoveryOutcome.PROVED_CREATED),
        ("F_AFTER_SUCCESS_COMMIT", 1, RecoveryOutcome.PROVED_CREATED),
        ("G_DURING_VERIFICATION", 1, RecoveryOutcome.PROVED_CREATED),
    ),
)
async def test_failure_injection_matrix_recovers_without_duplicate_create(
    checkpoint: str,
    calls_before_recovery: int,
    recovery_outcome: RecoveryOutcome,
) -> None:
    engine, plans, runtime, plan_id, job_id, _ = await prepare_apply_case()
    adapter = FakeMutationAdapter(recovery_outcome)
    try:
        first = await runtime.lease_next_job(
            GUILD_A, lease_owner="fault-worker-one", lease_seconds=30
        )
        assert first is not None
        crashing = ApplyPlanExecutor(
            plans,
            adapter,
            PassLock(),  # type: ignore[arg-type]
            worker_id="fault-worker-one",
            authorization=AllowAuthorization(),
            faults=CrashAt(checkpoint),
        )
        with pytest.raises(RuntimeError, match="injected crash"):
            await crashing.execute_leased(GUILD_A, first, None)
        assert adapter.create_calls == calls_before_recovery

        await expire_job(job_id)
        second = await runtime.lease_next_job(
            GUILD_A, lease_owner="fault-worker-two", lease_seconds=30
        )
        assert second is not None and int(second["lease_generation"]) == 2
        recovering = ApplyPlanExecutor(
            plans,
            adapter,
            PassLock(),  # type: ignore[arg-type]
            worker_id="fault-worker-two",
            authorization=AllowAuthorization(),
        )
        await recovering.execute_leased(GUILD_A, second, None)
        assert adapter.create_calls == 1
        assert (await plans.get_plan(GUILD_A, plan_id))["status"] == "SUCCEEDED"
        if checkpoint == "C_AFTER_IN_FLIGHT_BEFORE_NETWORK":
            assert adapter.recover_calls == 1
        if checkpoint == "G_DURING_VERIFICATION":
            assert adapter.verify_calls == 2
    finally:
        await engine.dispose()


async def test_create_channel_crash_after_success_never_duplicates_create() -> None:
    engine, plans, runtime, plan_id, job_id, _ = await prepare_channel_apply_case()
    adapter = FakeMutationAdapter()
    try:
        first = await runtime.lease_next_job(
            GUILD_A, lease_owner="channel-worker-one", lease_seconds=30
        )
        assert first is not None
        crashing = ApplyPlanExecutor(
            plans,
            adapter,
            PassLock(),  # type: ignore[arg-type]
            worker_id="channel-worker-one",
            authorization=AllowAuthorization(),
            faults=CrashAt("E_AFTER_DISCORD_BEFORE_COMMIT"),
        )
        with pytest.raises(RuntimeError, match="injected crash"):
            await crashing.execute_leased(GUILD_A, first, None)
        assert adapter.create_calls == 1
        await expire_job(job_id)
        second = await runtime.lease_next_job(
            GUILD_A, lease_owner="channel-worker-two", lease_seconds=30
        )
        assert second is not None
        recovering = ApplyPlanExecutor(
            plans,
            adapter,
            PassLock(),  # type: ignore[arg-type]
            worker_id="channel-worker-two",
            authorization=AllowAuthorization(),
        )
        await recovering.execute_leased(GUILD_A, second, None)
        assert adapter.create_calls == 1
        assert adapter.recover_calls == 1
        assert (await plans.get_plan(GUILD_A, plan_id))["status"] == "SUCCEEDED"
    finally:
        await engine.dispose()


class TimeoutThenRecoveryCrash(FakeMutationAdapter):
    async def execute(self, **kwargs: Any) -> MutationResult:
        del kwargs
        self.create_calls += 1
        raise MutableDiscordError(
            DiscordFailure(DiscordErrorKind.UNKNOWN_OUTCOME, None),
            outcome_unknown=True,
        )

    async def recover(self, **kwargs: Any) -> RecoveryResult:
        del kwargs
        raise RuntimeError("recovery process crash")


async def test_fault_d_timeout_is_persisted_unknown_before_recovery() -> None:
    engine, plans, runtime, plan_id, _, _ = await prepare_apply_case()
    adapter = TimeoutThenRecoveryCrash()
    try:
        leased = await runtime.lease_next_job(
            GUILD_A, lease_owner="timeout-worker", lease_seconds=30
        )
        assert leased is not None
        executor = ApplyPlanExecutor(
            plans,
            adapter,
            PassLock(),  # type: ignore[arg-type]
            worker_id="timeout-worker",
            authorization=AllowAuthorization(),
        )
        with pytest.raises(RuntimeError, match="recovery process crash"):
            await executor.execute_leased(GUILD_A, leased, None)
        assert adapter.create_calls == 1
        assert await plans.operation_counts(GUILD_A, plan_id) == {"UNKNOWN_OUTCOME": 1}
    finally:
        await engine.dispose()


class FailingPubSub:
    async def publish(self, guild_id: int, payload: dict[str, Any]) -> int:
        del guild_id, payload
        raise ConnectionError("injected Redis outage")


async def test_fault_h_redis_outage_after_db_commit_preserves_durable_result() -> None:
    engine, plans, runtime, plan_id, _, _ = await prepare_apply_case()
    adapter = FakeMutationAdapter()
    try:
        leased = await runtime.lease_next_job(
            GUILD_A, lease_owner="redis-outage-worker", lease_seconds=30
        )
        assert leased is not None
        executor = ApplyPlanExecutor(
            plans,
            adapter,
            PassLock(),  # type: ignore[arg-type]
            worker_id="redis-outage-worker",
            authorization=AllowAuthorization(),
            faults=CrashAt("F_AFTER_SUCCESS_COMMIT"),
        )
        with pytest.raises(RuntimeError, match="injected crash"):
            await executor.execute_leased(GUILD_A, leased, None)
        assert await plans.operation_counts(GUILD_A, plan_id) == {"SUCCEEDED": 1}
        publisher = OutboxPublisher(runtime, FailingPubSub())  # type: ignore[arg-type]
        with pytest.raises(ConnectionError, match="injected Redis outage"):
            await publisher.publish_guild(GUILD_A, limit=1)
        assert await plans.operation_counts(GUILD_A, plan_id) == {"SUCCEEDED": 1}
    finally:
        await engine.dispose()


async def test_fault_i_dead_lock_expires_and_old_worker_is_fenced() -> None:
    engine, plans, runtime, plan_id, job_id, correlation = await prepare_apply_case()
    redis = create_redis_client(os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0"))
    lock = RedisGuildMutationLock(redis, ttl_seconds=0.1)
    try:
        await redis.set(lock.key(GUILD_A), "dead-worker", px=100)
        with pytest.raises(GuildMutationLockUnavailable):
            await lock.run(GUILD_A, _return_true)
        await asyncio.sleep(0.12)
        assert await lock.run(GUILD_A, _return_true)

        first = await runtime.lease_next_job(GUILD_A, lease_owner="old-worker", lease_seconds=30)
        assert first is not None
        await expire_job(job_id)
        second = await runtime.lease_next_job(GUILD_A, lease_owner="new-worker", lease_seconds=30)
        assert second is not None
        with pytest.raises(PlanFencingError):
            await plans.begin_apply(
                guild_id=GUILD_A,
                plan_id=plan_id,
                job_id=job_id,
                lease_owner="old-worker",
                lease_token=UUID(str(first["lease_token"])),
                lease_generation=int(first["lease_generation"]),
                actor_user_id=ACTOR,
                correlation_id=correlation,
            )
    finally:
        await redis.aclose()
        await engine.dispose()


async def _return_true() -> bool:
    return True


async def test_crash_after_create_recovers_without_a_second_create() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=3)
    factory = create_session_factory(engine)
    plans = PlanningRepository(factory)
    runtime = RuntimeRepository(factory)
    graph, operation = graph_and_operation()
    plan_id = uuid4()
    correlation = uuid4()
    risk = RiskAssessment(RiskLevel.LOW, 4, (), ImpactSummary(1), False)
    try:
        await plans.create_plan(
            plan_id=plan_id,
            guild_id=GUILD_A,
            actor_user_id=ACTOR,
            idempotency_key="crash-create-plan",
            graph=graph,
            operations=(operation,),
            before_snapshot={"guild_id": str(GUILD_A)},
            base_structure_version="guild:1|coverage:1",
            base_structure_hash="a" * 64,
            capability_version="discord-permissions-2026-08-24",
            plan_hash="e" * 64,
            risk=risk,
            compiler_version="did-plan-compiler-v1",
            correlation_id=correlation,
        )
        await plans.transition_plan(
            guild_id=GUILD_A,
            plan_id=plan_id,
            actor_user_id=ACTOR,
            expected=PlanState.DRAFT,
            target=PlanState.VALIDATED,
            expected_version=1,
            correlation_id=correlation,
        )
        await plans.confirm(
            guild_id=GUILD_A,
            plan_id=plan_id,
            actor_user_id=ACTOR,
            idempotency_key="crash-confirm",
            plan_hash="e" * 64,
            risk_level=RiskLevel.LOW,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            expected_version=2,
            correlation_id=correlation,
        )
        job_id = await plans.enqueue_apply(
            guild_id=GUILD_A,
            plan_id=plan_id,
            actor_user_id=ACTOR,
            correlation_id=correlation,
        )
        first = await runtime.lease_next_job(
            GUILD_A, lease_owner="crashing-worker", lease_seconds=30
        )
        assert first is not None
        adapter = FakeMutationAdapter()
        crashing = ApplyPlanExecutor(
            plans,
            adapter,
            PassLock(),  # type: ignore[arg-type]
            worker_id="crashing-worker",
            authorization=AllowAuthorization(),
            faults=CrashAfterDiscord(),
        )
        with pytest.raises(RuntimeError, match="injected worker crash"):
            await crashing.execute_leased(GUILD_A, first, None)
        assert adapter.create_calls == 1

        admin = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE discord_io_jobs SET leased_until=now()-interval '1 second' "
                        "WHERE job_id=:job"
                    ),
                    {"job": job_id},
                )
        finally:
            await admin.dispose()
        second = await runtime.lease_next_job(
            GUILD_A, lease_owner="recovery-worker", lease_seconds=30
        )
        assert second is not None and int(second["lease_generation"]) == 2
        recovering = ApplyPlanExecutor(
            plans,
            adapter,
            PassLock(),  # type: ignore[arg-type]
            worker_id="recovery-worker",
            authorization=AllowAuthorization(),
        )
        await recovering.execute_leased(GUILD_A, second, None)
        assert adapter.create_calls == 1
        assert (await plans.get_plan(GUILD_A, plan_id))["status"] == "SUCCEEDED"
    finally:
        await engine.dispose()


async def test_plan_idempotency_is_actor_scoped_and_operation_identity_is_plan_scoped() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=2)
    plans = PlanningRepository(create_session_factory(engine))
    graph, operation = graph_and_operation()
    correlation = uuid4()
    try:
        plan_a = uuid4()
        plan_b = uuid4()
        plan_c = uuid4()
        row_a, created_a = await persist_draft(
            plans,
            plan_id=plan_a,
            guild_id=GUILD_A,
            actor_user_id=ACTOR,
            idempotency_key="shared-key",
            graph=graph,
            operations=(operation,),
            correlation_id=correlation,
        )
        row_b, created_b = await persist_draft(
            plans,
            plan_id=plan_b,
            guild_id=GUILD_A,
            actor_user_id=ACTOR_B,
            idempotency_key="shared-key",
            graph=graph,
            operations=(operation,),
            correlation_id=correlation,
        )
        row_c, created_c = await persist_draft(
            plans,
            plan_id=plan_c,
            guild_id=GUILD_A,
            actor_user_id=ACTOR,
            idempotency_key="different-key",
            graph=graph,
            operations=(operation,),
            correlation_id=correlation,
        )
        assert created_a and created_b and created_c
        assert {UUID(str(row_a["id"])), UUID(str(row_b["id"])), UUID(str(row_c["id"]))} == {
            plan_a,
            plan_b,
            plan_c,
        }
        assert all(
            UUID(str(rows[0]["id"])) == operation.operation_id
            for rows in (
                await plans.operations(GUILD_A, plan_a),
                await plans.operations(GUILD_A, plan_b),
                await plans.operations(GUILD_A, plan_c),
            )
        )

        graph_b = DesiredStateGraph(GUILD_B, graph.nodes)
        row_d, created_d = await persist_draft(
            plans,
            plan_id=uuid4(),
            guild_id=GUILD_B,
            actor_user_id=ACTOR,
            idempotency_key="cross-guild",
            graph=graph_b,
            operations=(operation,),
            correlation_id=correlation,
        )
        assert created_d and int(row_d["guild_id"]) == GUILD_B
    finally:
        await engine.dispose()


async def test_apply_confirmation_is_bound_to_durable_requesting_actor() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=2)
    factory = create_session_factory(engine)
    plans = PlanningRepository(factory)
    runtime = RuntimeRepository(factory)
    graph, operation = graph_and_operation()
    plan_id = uuid4()
    correlation = uuid4()
    try:
        await persist_draft(
            plans,
            plan_id=plan_id,
            guild_id=GUILD_A,
            actor_user_id=ACTOR,
            idempotency_key="actor-bound-plan",
            graph=graph,
            operations=(operation,),
            correlation_id=correlation,
        )
        await plans.transition_plan(
            guild_id=GUILD_A,
            plan_id=plan_id,
            actor_user_id=ACTOR,
            expected=PlanState.DRAFT,
            target=PlanState.VALIDATED,
            expected_version=1,
            correlation_id=correlation,
        )
        await plans.confirm(
            guild_id=GUILD_A,
            plan_id=plan_id,
            actor_user_id=ACTOR,
            idempotency_key="actor-a-confirmation",
            plan_hash="b" * 64,
            risk_level=RiskLevel.LOW,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            expected_version=2,
            correlation_id=correlation,
        )
        job_id = await plans.enqueue_apply(
            guild_id=GUILD_A,
            plan_id=plan_id,
            actor_user_id=ACTOR,
            correlation_id=correlation,
        )
        admin = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE plan_confirmations SET confirmed_at=now()-interval '2 minutes',"
                        "expires_at=now()-interval '1 minute' "
                        "WHERE guild_id=:guild_id AND plan_id=:plan_id AND actor_user_id=:actor"
                    ),
                    {"guild_id": GUILD_A, "plan_id": plan_id, "actor": ACTOR},
                )
                await connection.execute(
                    text(
                        "INSERT INTO plan_confirmations "
                        "(id,guild_id,plan_id,actor_user_id,plan_hash,risk_level,"
                        "idempotency_key,confirmed_at,expires_at) VALUES "
                        "(:id,:guild_id,:plan_id,:actor,:hash,'LOW','actor-b-confirmation',"
                        "now(),now()+interval '10 minutes')"
                    ),
                    {
                        "id": uuid4(),
                        "guild_id": GUILD_A,
                        "plan_id": plan_id,
                        "actor": ACTOR_B,
                        "hash": "b" * 64,
                    },
                )
        finally:
            await admin.dispose()
        leased = await runtime.lease_next_job(
            GUILD_A, lease_owner="actor-binding-worker", lease_seconds=30
        )
        assert leased is not None
        with pytest.raises(ConfirmationInvalid):
            await plans.begin_apply(
                guild_id=GUILD_A,
                plan_id=plan_id,
                job_id=job_id,
                lease_owner="actor-binding-worker",
                lease_token=UUID(str(leased["lease_token"])),
                lease_generation=int(leased["lease_generation"]),
                actor_user_id=ACTOR,
                correlation_id=correlation,
            )
        assert (await plans.get_plan(GUILD_A, plan_id))["status"] == "CONFIRMED"
    finally:
        await engine.dispose()


async def test_apply_and_cancel_commands_are_logically_idempotent() -> None:
    engine, plans, _, plan_id, first_job, correlation = await prepare_apply_case()
    try:
        second_job = await plans.enqueue_apply(
            guild_id=GUILD_A,
            plan_id=plan_id,
            actor_user_id=ACTOR,
            correlation_id=correlation,
        )
        assert second_job == first_job
        first_cancel = await plans.request_cancel(
            guild_id=GUILD_A,
            plan_id=plan_id,
            actor_user_id=ACTOR,
            correlation_id=correlation,
        )
        second_cancel = await plans.request_cancel(
            guild_id=GUILD_A,
            plan_id=plan_id,
            actor_user_id=ACTOR,
            correlation_id=correlation,
        )
        assert first_cancel["status"] == second_cancel["status"] == "CANCELLED"
        assert first_cancel["state_version"] == second_cancel["state_version"]
    finally:
        await engine.dispose()


async def test_validated_graph_children_and_snapshots_are_immutable_for_app_and_admin() -> None:
    await seed()
    app_engine = create_database_engine(APP_URL, pool_size=2)
    factory = create_session_factory(app_engine)
    plans = PlanningRepository(factory)
    graph, operation = graph_and_operation()
    plan_id = uuid4()
    correlation = uuid4()
    try:
        await persist_draft(
            plans,
            plan_id=plan_id,
            guild_id=GUILD_A,
            actor_user_id=ACTOR,
            idempotency_key="immutable-plan",
            graph=graph,
            operations=(operation,),
            correlation_id=correlation,
        )
        await plans.transition_plan(
            guild_id=GUILD_A,
            plan_id=plan_id,
            actor_user_id=ACTOR,
            expected=PlanState.DRAFT,
            target=PlanState.VALIDATED,
            expected_version=1,
            correlation_id=correlation,
        )
        statements = (
            "INSERT INTO plan_operations SELECT * FROM plan_operations "
            "WHERE guild_id=:guild_id AND plan_id=:plan_id LIMIT 1",
            "DELETE FROM plan_operations WHERE guild_id=:guild_id AND plan_id=:plan_id",
            "INSERT INTO plan_symbol_bindings SELECT * FROM plan_symbol_bindings "
            "WHERE guild_id=:guild_id AND plan_id=:plan_id LIMIT 1",
            "DELETE FROM plan_symbol_bindings WHERE guild_id=:guild_id AND plan_id=:plan_id",
            "UPDATE plan_snapshots SET payload='{}'::jsonb WHERE guild_id=:guild_id "
            "AND id=(SELECT before_snapshot_id FROM plans WHERE guild_id=:guild_id "
            "AND id=:plan_id)",
        )
        for statement in statements:
            with pytest.raises(DBAPIError):
                async with tenant_transaction(factory, TenantContext(GUILD_A, ACTOR)) as session:
                    await session.execute(
                        text(statement), {"guild_id": GUILD_A, "plan_id": plan_id}
                    )
        admin = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            for statement in statements:
                with pytest.raises(DBAPIError):
                    async with admin.begin() as connection:
                        await connection.execute(
                            text(statement), {"guild_id": GUILD_A, "plan_id": plan_id}
                        )
        finally:
            await admin.dispose()
    finally:
        await app_engine.dispose()


async def test_draft_tamper_is_detected_by_full_persisted_plan_hash() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=2)
    factory = create_session_factory(engine)
    plans = PlanningRepository(factory)
    graph, operation = graph_and_operation()
    snapshot = {"guild_id": str(GUILD_A), "roles": [], "channels": []}
    snapshot_hash = canonical_hash(snapshot)
    plan_hash = PlanningService._plan_hash(
        graph=graph,
        operations=(operation,),
        snapshot=snapshot,
        snapshot_schema_version="did-guild-snapshot-v1",
        compiler_version="did-plan-compiler-v1",
        capability_version="discord-permissions-2026-08-24",
        base_structure_version="guild:1|coverage:1",
        base_structure_hash=snapshot_hash,
        symbols=PlanningService._symbol_definitions((operation,)),
    )
    plan_id = uuid4()
    try:
        await persist_draft(
            plans,
            plan_id=plan_id,
            guild_id=GUILD_A,
            actor_user_id=ACTOR,
            idempotency_key="tamper-plan",
            graph=graph,
            operations=(operation,),
            correlation_id=uuid4(),
            plan_hash=plan_hash,
            snapshot=snapshot,
            snapshot_hash=snapshot_hash,
        )
        admin = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE plan_operations SET desired_payload="
                        "jsonb_set(desired_payload,'{name}','\"tampered\"'::jsonb) "
                        "WHERE guild_id=:guild_id AND plan_id=:plan_id"
                    ),
                    {"guild_id": GUILD_A, "plan_id": plan_id},
                )
        finally:
            await admin.dispose()
        service = PlanningService(plans, Any)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="immutable hash mismatch"):
            await service._assert_persisted_integrity(GUILD_A, plan_id)
    finally:
        await engine.dispose()


async def test_progress_sequence_allocation_is_atomic_under_concurrency() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=12)
    factory = create_session_factory(engine)
    plans = PlanningRepository(factory)
    graph, operation = graph_and_operation()
    plan_id = uuid4()
    try:
        await persist_draft(
            plans,
            plan_id=plan_id,
            guild_id=GUILD_A,
            actor_user_id=ACTOR,
            idempotency_key="progress-plan",
            graph=graph,
            operations=(operation,),
            correlation_id=uuid4(),
        )

        async def append(index: int) -> None:
            async with tenant_transaction(factory, TenantContext(GUILD_A, ACTOR)) as session:
                await PlanningRepository._append_progress(
                    session,
                    guild_id=GUILD_A,
                    plan_id=plan_id,
                    operation_id=None,
                    plan_status=PlanState.DRAFT,
                    operation_status=None,
                    message_key=f"plans.progress.concurrent{index}",
                    error_code=None,
                    correlation_id=uuid4(),
                )

        await asyncio.gather(*(append(index) for index in range(20)))
        events = await plans.progress_since(GUILD_A, plan_id)
        sequences = [int(event["sequence"]) for event in events]
        assert sequences == list(range(1, 22))
        assert len({event["message_key"] for event in events}) == 21
    finally:
        await engine.dispose()


async def test_per_operation_precondition_change_blocks_second_mutable_call() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=3)
    factory = create_session_factory(engine)
    plans = PlanningRepository(factory)
    runtime = RuntimeRepository(factory)
    graph, first = graph_and_operation()
    second = PlanOperation(
        uuid4(),
        OperationType.CREATE_ROLE,
        ResourceType.ROLE,
        "role.stage05.second",
        freeze_json_object({"name": "DID Stage 05 second", "permissions": "0"}),
        freeze_json_object({}),
        ("MANAGE_ROLES",),
        CompensationClass.REVERSIBLE,
        RiskLevel.LOW,
        VerificationStrategy.TARGETED_LIST_AND_MATCH,
        RecoveryStrategy.CREATE_RECONCILE,
        ("GUILD_ROLE_CREATE",),
    )
    first = PlanOperation(
        first.operation_id,
        first.operation_type,
        first.resource_type,
        first.resource_ref,
        first.desired_payload,
        first.before_payload,
        first.required_capabilities,
        first.compensation,
        first.risk,
        first.verification,
        first.recovery,
        first.expected_gateway_events,
    )
    plan_id = uuid4()
    correlation = uuid4()

    class ChangingPreconditionAdapter(FakeMutationAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.precondition_calls = 0

        async def check_preconditions(self, **kwargs: Any) -> PreconditionOutcome:
            del kwargs
            self.precondition_calls += 1
            return (
                PreconditionOutcome.SATISFIED
                if self.precondition_calls == 1
                else PreconditionOutcome.CHANGED
            )

    adapter = ChangingPreconditionAdapter()
    try:
        await persist_draft(
            plans,
            plan_id=plan_id,
            guild_id=GUILD_A,
            actor_user_id=ACTOR,
            idempotency_key="jit-precondition-plan",
            graph=graph,
            operations=(first, second),
            correlation_id=correlation,
        )
        _, leased = await confirm_enqueue_and_lease(
            plans,
            runtime,
            plan_id=plan_id,
            correlation_id=correlation,
            worker_id="jit-precondition-worker",
        )
        executor = ApplyPlanExecutor(
            plans,
            adapter,
            PassLock(),  # type: ignore[arg-type]
            worker_id="jit-precondition-worker",
            authorization=AllowAuthorization(),
        )
        await executor.execute_leased(GUILD_A, leased, None)
        assert adapter.precondition_calls == 2
        assert adapter.create_calls == 1
        assert (await plans.get_plan(GUILD_A, plan_id))["status"] == ("INTERVENTION_REQUIRED")
        assert await plans.operation_counts(GUILD_A, plan_id) == {
            "SUCCEEDED": 1,
            "INTERVENTION_REQUIRED": 1,
        }
    finally:
        await engine.dispose()


async def test_bulk_reorder_registers_one_expected_gateway_item_per_resource() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=3)
    factory = create_session_factory(engine)
    plans = PlanningRepository(factory)
    runtime = RuntimeRepository(factory)
    graph, _ = graph_and_operation()
    operation = PlanOperation(
        uuid4(),
        OperationType.REORDER_ROLES,
        ResourceType.ROLE,
        "bulk:roles",
        freeze_json_object(
            {
                "items": [
                    {"id": CREATED_ROLE, "position": 2},
                    {"id": CREATED_ROLE + 1, "position": 3},
                ]
            }
        ),
        freeze_json_object(
            {
                "items": [
                    {"id": CREATED_ROLE, "position": 1},
                    {"id": CREATED_ROLE + 1, "position": 2},
                ]
            }
        ),
        ("MANAGE_ROLES",),
        CompensationClass.REVERSIBLE,
        RiskLevel.MEDIUM,
        VerificationStrategy.TARGETED_LIST_AND_MATCH,
        RecoveryStrategy.UPDATE_COMPARE_BEFORE_DESIRED,
        ("GUILD_ROLE_UPDATE",),
    )
    plan_id = uuid4()
    correlation = uuid4()
    try:
        await persist_draft(
            plans,
            plan_id=plan_id,
            guild_id=GUILD_A,
            actor_user_id=ACTOR,
            idempotency_key="bulk-expected-plan",
            graph=graph,
            operations=(operation,),
            correlation_id=correlation,
        )
        job_id, leased = await confirm_enqueue_and_lease(
            plans,
            runtime,
            plan_id=plan_id,
            correlation_id=correlation,
            worker_id="bulk-expected-worker",
        )
        fence = {
            "guild_id": GUILD_A,
            "plan_id": plan_id,
            "job_id": job_id,
            "lease_owner": "bulk-expected-worker",
            "lease_token": UUID(str(leased["lease_token"])),
            "lease_generation": int(leased["lease_generation"]),
        }
        await plans.begin_apply(
            **fence,
            actor_user_id=ACTOR,
            correlation_id=correlation,  # type: ignore[arg-type]
        )
        prepared = await plans.prepare_next_operation(**fence)  # type: ignore[arg-type]
        assert prepared is not None
        await plans.mark_attempt_in_flight(
            **fence,  # type: ignore[arg-type]
            operation_id=operation.operation_id,
            attempt_id=UUID(str(prepared["attempt_id"])),
        )
        admin = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin.connect() as connection:
                rows = (
                    await connection.execute(
                        text(
                            "SELECT discord_resource_id,status FROM plan_expected_mutations "
                            "WHERE guild_id=:guild_id AND plan_id=:plan_id ORDER BY "
                            "discord_resource_id"
                        ),
                        {"guild_id": GUILD_A, "plan_id": plan_id},
                    )
                ).all()
        finally:
            await admin.dispose()
        assert [(int(row[0]), str(row[1])) for row in rows] == [
            (CREATED_ROLE, "EXPECTED"),
            (CREATED_ROLE + 1, "EXPECTED"),
        ]
    finally:
        await engine.dispose()


async def test_overwrite_own_event_after_success_rejects_external_same_channel() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=3)
    factory = create_session_factory(engine)
    plans = PlanningRepository(factory)
    runtime = RuntimeRepository(factory)
    channel_id = CREATED_CHANNEL
    target_id = CREATED_ROLE
    other_target = CREATED_ROLE + 1
    admin = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with admin.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO discord_channels_cache "
                    "(guild_id,channel_id,type,name,parent_id,position,nsfw,last_full_payload,"
                    "observability_state,freshness_state,last_full_observed_at) VALUES "
                    "(:guild_id,:channel_id,0,'overwrite-target',NULL,0,false,'{}',"
                    "'VISIBLE','FRESH',now())"
                ),
                {"guild_id": GUILD_A, "channel_id": channel_id},
            )
        graph, _ = graph_and_operation()
        operation = PlanOperation(
            uuid4(),
            OperationType.UPSERT_OVERWRITE,
            ResourceType.OVERWRITE,
            "overwrite.target",
            freeze_json_object(
                {
                    "channel_id": channel_id,
                    "subject_id": target_id,
                    "target_type": 0,
                    "allow": 1,
                    "deny": 2,
                }
            ),
            freeze_json_object({}),
            ("MANAGE_ROLES",),
            CompensationClass.REVERSIBLE,
            RiskLevel.MEDIUM,
            VerificationStrategy.TARGETED_GET,
            RecoveryStrategy.UPDATE_COMPARE_BEFORE_DESIRED,
            ("CHANNEL_UPDATE",),
        )
        plan_id = uuid4()
        correlation = uuid4()
        await persist_draft(
            plans,
            plan_id=plan_id,
            guild_id=GUILD_A,
            actor_user_id=ACTOR,
            idempotency_key="overwrite-gateway-plan",
            graph=graph,
            operations=(operation,),
            correlation_id=correlation,
        )
        job_id, leased = await confirm_enqueue_and_lease(
            plans,
            runtime,
            plan_id=plan_id,
            correlation_id=correlation,
            worker_id="overwrite-gateway-worker",
        )
        fence = {
            "guild_id": GUILD_A,
            "plan_id": plan_id,
            "job_id": job_id,
            "lease_owner": "overwrite-gateway-worker",
            "lease_token": UUID(str(leased["lease_token"])),
            "lease_generation": int(leased["lease_generation"]),
        }
        await plans.begin_apply(
            **fence,
            actor_user_id=ACTOR,
            correlation_id=correlation,  # type: ignore[arg-type]
        )
        prepared = await plans.prepare_next_operation(**fence)  # type: ignore[arg-type]
        assert prepared is not None
        attempt_id = UUID(str(prepared["attempt_id"]))
        await plans.mark_attempt_in_flight(
            **fence,  # type: ignore[arg-type]
            operation_id=operation.operation_id,
            attempt_id=attempt_id,
        )
        await plans.record_operation_success(
            **fence,  # type: ignore[arg-type]
            operation_id=operation.operation_id,
            attempt_id=attempt_id,
            discord_status=204,
            result_payload={
                "channel_id": channel_id,
                "target_id": target_id,
                "target_type": 0,
                "allow": 1,
                "deny": 2,
            },
            correlation_id=correlation,
            audit_reason_fingerprint="c" * 64,
        )

        def channel_update(sequence: int, overwrites: list[dict[str, str | int]]) -> Any:
            return normalize_gateway_dispatch(
                {
                    "op": 0,
                    "s": sequence,
                    "t": "CHANNEL_UPDATE",
                    "d": {
                        "id": str(channel_id),
                        "guild_id": str(GUILD_A),
                        "type": 0,
                        "name": "overwrite-target",
                        "position": 0,
                        "parent_id": None,
                        "permission_overwrites": overwrites,
                    },
                },
                discord_session_id="overwrite-gateway",
                received_at=datetime.now(UTC),
            )

        own = channel_update(
            1,
            [{"id": str(target_id), "type": 0, "allow": "1", "deny": "2"}],
        )
        assert own is not None and await runtime.ingest_gateway_event(own)
        async with admin.connect() as connection:
            expected_status = await connection.scalar(
                text(
                    "SELECT status FROM plan_expected_mutations WHERE guild_id=:guild_id "
                    "AND plan_id=:plan_id"
                ),
                {"guild_id": GUILD_A, "plan_id": plan_id},
            )
        assert expected_status == "OBSERVED"
        assert (await plans.get_plan(GUILD_A, plan_id))["status"] == "APPLYING"

        external = channel_update(
            2,
            [
                {"id": str(target_id), "type": 0, "allow": "1", "deny": "2"},
                {"id": str(other_target), "type": 0, "allow": "4", "deny": "0"},
            ],
        )
        assert external is not None and await runtime.ingest_gateway_event(external)
        assert (await plans.get_plan(GUILD_A, plan_id))["status"] == ("INTERVENTION_REQUIRED")
    finally:
        await admin.dispose()
        await engine.dispose()


async def test_external_gateway_drift_stales_only_resource_dependent_plan() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=3)
    plans = PlanningRepository(create_session_factory(engine))
    runtime = RuntimeRepository(create_session_factory(engine))
    graph, _ = graph_and_operation()
    channel_operation = PlanOperation(
        uuid4(),
        OperationType.UPDATE_CHANNEL,
        ResourceType.CHANNEL,
        "channel.sales",
        freeze_json_object({"id": CREATED_CHANNEL, "name": "sales-new"}),
        freeze_json_object({"id": CREATED_CHANNEL, "name": "sales"}),
        ("MANAGE_CHANNELS",),
        CompensationClass.REVERSIBLE,
        RiskLevel.LOW,
        VerificationStrategy.TARGETED_GET,
        RecoveryStrategy.UPDATE_COMPARE_BEFORE_DESIRED,
        ("CHANNEL_UPDATE",),
    )
    role_operation = PlanOperation(
        uuid4(),
        OperationType.UPDATE_ROLE,
        ResourceType.ROLE,
        "role.independent",
        freeze_json_object({"id": CREATED_ROLE, "name": "independent-new"}),
        freeze_json_object({"id": CREATED_ROLE, "name": "independent"}),
        ("MANAGE_ROLES",),
        CompensationClass.REVERSIBLE,
        RiskLevel.LOW,
        VerificationStrategy.TARGETED_GET,
        RecoveryStrategy.UPDATE_COMPARE_BEFORE_DESIRED,
        ("GUILD_ROLE_UPDATE",),
    )
    channel_plan = uuid4()
    role_plan = uuid4()
    correlation = uuid4()
    try:
        for plan_id, key, operation in (
            (channel_plan, "dependent-channel", channel_operation),
            (role_plan, "independent-role", role_operation),
        ):
            await persist_draft(
                plans,
                plan_id=plan_id,
                guild_id=GUILD_A,
                actor_user_id=ACTOR,
                idempotency_key=key,
                graph=graph,
                operations=(operation,),
                correlation_id=correlation,
            )
            await plans.transition_plan(
                guild_id=GUILD_A,
                plan_id=plan_id,
                actor_user_id=ACTOR,
                expected=PlanState.DRAFT,
                target=PlanState.VALIDATED,
                expected_version=1,
                correlation_id=correlation,
            )
        event = normalize_gateway_dispatch(
            {
                "op": 0,
                "s": 1,
                "t": "CHANNEL_UPDATE",
                "d": {
                    "id": str(CREATED_CHANNEL),
                    "guild_id": str(GUILD_A),
                    "type": 0,
                    "name": "external-sales",
                    "position": 0,
                    "parent_id": None,
                    "permission_overwrites": [],
                },
            },
            discord_session_id="relevant-plan-drift",
            received_at=datetime.now(UTC),
        )
        assert event is not None and await runtime.ingest_gateway_event(event)
        assert (await plans.get_plan(GUILD_A, channel_plan))["status"] == "STALE"
        assert (await plans.get_plan(GUILD_A, role_plan))["status"] == "VALIDATED"
    finally:
        await engine.dispose()


async def test_late_old_worker_lease_loss_does_not_touch_new_attempt() -> None:
    engine, plans, runtime, plan_id, job_id, correlation = await prepare_apply_case()
    try:
        old = await runtime.lease_next_job(
            GUILD_A, lease_owner="lease-old-worker", lease_seconds=30
        )
        assert old is not None
        old_fence = {
            "guild_id": GUILD_A,
            "plan_id": plan_id,
            "job_id": job_id,
            "lease_owner": "lease-old-worker",
            "lease_token": UUID(str(old["lease_token"])),
            "lease_generation": int(old["lease_generation"]),
        }
        await plans.begin_apply(
            **old_fence,  # type: ignore[arg-type]
            actor_user_id=ACTOR,
            correlation_id=correlation,
        )
        prepared = await plans.prepare_next_operation(**old_fence)  # type: ignore[arg-type]
        assert prepared is not None
        operation_id = UUID(str(prepared["id"]))
        old_attempt_id = UUID(str(prepared["attempt_id"]))
        await plans.mark_attempt_in_flight(
            **old_fence,  # type: ignore[arg-type]
            operation_id=operation_id,
            attempt_id=old_attempt_id,
        )
        await expire_job(job_id)
        new = await runtime.lease_next_job(
            GUILD_A, lease_owner="lease-new-worker", lease_seconds=30
        )
        assert new is not None
        new_attempt_id = uuid4()
        admin = create_database_engine(ADMIN_URL, pool_size=1)
        try:
            async with admin.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO operation_attempts "
                        "(id,guild_id,plan_id,operation_id,attempt_number,status,prepared_at,"
                        "in_flight_at,request_fingerprint,lease_owner,lease_token,"
                        "lease_generation,outcome_detail) VALUES "
                        "(:id,:guild_id,:plan_id,:operation_id,2,'IN_FLIGHT',now(),now(),"
                        ":fingerprint,'lease-new-worker',:token,:generation,'{}')"
                    ),
                    {
                        "id": new_attempt_id,
                        "guild_id": GUILD_A,
                        "plan_id": plan_id,
                        "operation_id": operation_id,
                        "fingerprint": "d" * 64,
                        "token": UUID(str(new["lease_token"])),
                        "generation": int(new["lease_generation"]),
                    },
                )
                await connection.execute(
                    text(
                        "UPDATE plan_operations SET attempt_count=2 WHERE guild_id=:guild_id "
                        "AND plan_id=:plan_id AND id=:operation_id"
                    ),
                    {
                        "guild_id": GUILD_A,
                        "plan_id": plan_id,
                        "operation_id": operation_id,
                    },
                )
            changed = await plans.mark_inflight_unknown_after_lease_loss(
                GUILD_A,
                plan_id,
                lease_owner="lease-old-worker",
                lease_token=UUID(str(old["lease_token"])),
                lease_generation=int(old["lease_generation"]),
                correlation_id=correlation,
            )
            assert changed == 0
            async with admin.connect() as connection:
                current = (
                    (
                        await connection.execute(
                            text(
                                "SELECT attempts.status AS attempt_status,operations.status AS "
                                "operation_status FROM operation_attempts attempts JOIN "
                                "plan_operations operations ON operations.guild_id="
                                "attempts.guild_id AND operations.plan_id=attempts.plan_id "
                                "AND operations.id="
                                "attempts.operation_id WHERE attempts.id=:attempt_id"
                            ),
                            {"attempt_id": new_attempt_id},
                        )
                    )
                    .mappings()
                    .one()
                )
            assert current["attempt_status"] == "IN_FLIGHT"
            assert current["operation_status"] == "IN_FLIGHT"
        finally:
            await admin.dispose()
    finally:
        await engine.dispose()
