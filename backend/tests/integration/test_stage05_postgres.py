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
from did.domain.discord_runtime import (
    DiscordErrorKind,
    DiscordFailure,
    WorkloadJob,
    WorkloadPriority,
)
from did.infrastructure.database import create_database_engine, create_session_factory
from did.infrastructure.discord.mutations import (
    MutableDiscordError,
    MutationResult,
    RecoveryOutcome,
    RecoveryResult,
)
from did.infrastructure.planning_lock import (
    GuildMutationLockUnavailable,
    RedisGuildMutationLock,
)
from did.infrastructure.planning_repository import (
    PlanFencingError,
    PlanningRepository,
    PlanNotFound,
)
from did.infrastructure.redis import create_redis_client
from did.infrastructure.runtime_redis import OutboxPublisher
from did.infrastructure.runtime_repository import RuntimeRepository
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
BOT = 550505050505050504
CREATED_ROLE = 550505050505050505
CREATED_CHANNEL = 550505050505050506


async def seed() -> None:
    engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE users, guild_installations CASCADE"))
            await connection.execute(
                text("INSERT INTO users (discord_user_id,username) VALUES (:id,'stage05')"),
                {"id": ACTOR},
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
        applying = await plans.begin_apply(**fence, correlation_id=correlation)  # type: ignore[arg-type]
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

    async def execute(self, **kwargs: Any) -> MutationResult:
        operation_type = kwargs["operation_type"]
        self.create_calls += 1
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
        )
        await recovering.execute_leased(GUILD_A, second, None)
        assert adapter.create_calls == 1
        assert (await plans.get_plan(GUILD_A, plan_id))["status"] == "SUCCEEDED"
    finally:
        await engine.dispose()
