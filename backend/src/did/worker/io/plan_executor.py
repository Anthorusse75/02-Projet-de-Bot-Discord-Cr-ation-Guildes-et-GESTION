from __future__ import annotations

import asyncio
from typing import Any, Protocol
from uuid import UUID

from did.application.auth.service import AuthorizationDenied
from did.infrastructure.discord.mutations import (
    MutableDiscordError,
    MutableDiscordPort,
    PreconditionOutcome,
)
from did.infrastructure.planning_lock import RedisGuildMutationLock
from did.infrastructure.planning_repository import PlanningRepository
from did.planning.models import OperationState, OperationType, PlanState
from did.worker.io.governor import DiscordWorkloadGovernor


class FaultInjector(Protocol):
    async def checkpoint(self, name: str) -> None: ...


class ApplyPreflightPort(Protocol):
    async def recheck(
        self, *, guild_id: int, plan_id: UUID, actor_authorization_fresh: bool
    ) -> Any: ...


class ApplyAuthorizationPort(Protocol):
    async def authorize_apply(self, *, guild_id: int, actor_user_id: int) -> None: ...


class PostVerificationPort(Protocol):
    async def apply(
        self, *, guild_id: int, plan_id: UUID, correlation_id: UUID
    ) -> bool: ...


class NoFaults:
    async def checkpoint(self, name: str) -> None:
        del name


class ApplyPlanExecutor:
    """Executes one persisted DAG with fenced attempts and recovery-before-retry."""

    def __init__(
        self,
        repository: PlanningRepository,
        adapter: MutableDiscordPort,
        mutation_lock: RedisGuildMutationLock,
        *,
        worker_id: str,
        authorization: ApplyAuthorizationPort,
        faults: FaultInjector | None = None,
        preflight: ApplyPreflightPort | None = None,
        post_verification: PostVerificationPort | None = None,
    ) -> None:
        self._repository = repository
        self._adapter = adapter
        self._lock = mutation_lock
        self._worker_id = worker_id
        self._authorization = authorization
        self._faults = faults or NoFaults()
        self._preflight = preflight
        self._post_verification = post_verification

    async def execute_leased(
        self,
        guild_id: int,
        leased: dict[str, Any],
        governor: DiscordWorkloadGovernor | None,
    ) -> None:
        payload = dict(leased.get("payload") or {})
        plan_id = UUID(str(payload["plan_id"]))

        async def execute_locked() -> None:
            await self._execute(guild_id, plan_id, leased, governor)

        try:
            await self._lock.run(guild_id, execute_locked)
        except asyncio.CancelledError:
            await self._repository.mark_inflight_unknown_after_lease_loss(
                guild_id,
                plan_id,
                lease_owner=self._worker_id,
                lease_token=UUID(str(leased["lease_token"])),
                lease_generation=int(leased["lease_generation"]),
                correlation_id=UUID(str(leased["correlation_id"])),
            )
            raise

    async def _execute(
        self,
        guild_id: int,
        plan_id: UUID,
        leased: dict[str, Any],
        governor: DiscordWorkloadGovernor | None,
    ) -> None:
        job_id = UUID(str(leased["job_id"]))
        lease_token = UUID(str(leased["lease_token"]))
        lease_generation = int(leased["lease_generation"])
        correlation_id = UUID(str(leased["correlation_id"]))
        actor_user_id = int(leased["requested_by"])
        if lease_generation > 1:
            # A previous process may have transmitted Discord I/O and died before
            # persisting the response.  Promote its in-flight attempt to UNKNOWN
            # before selecting any new work; recovery below must decide the truth.
            stale_fence = await self._repository.inflight_attempt_fence(guild_id, plan_id)
            if stale_fence is not None and int(stale_fence["lease_generation"]) < lease_generation:
                await self._repository.mark_inflight_unknown_after_lease_loss(
                    guild_id,
                    plan_id,
                    lease_owner=str(stale_fence["lease_owner"]),
                    lease_token=UUID(str(stale_fence["lease_token"])),
                    lease_generation=int(stale_fence["lease_generation"]),
                    correlation_id=correlation_id,
                )
        await self._repository.begin_apply(
            guild_id=guild_id,
            plan_id=plan_id,
            job_id=job_id,
            lease_owner=self._worker_id,
            lease_token=lease_token,
            lease_generation=lease_generation,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )
        try:

            async def authorize_actor() -> None:
                await self._authorization.authorize_apply(
                    guild_id=guild_id, actor_user_id=actor_user_id
                )

            (
                await governor.run_distributed(guild_id, authorize_actor)
                if governor is not None
                else await authorize_actor()
            )
        except AuthorizationDenied as exc:
            await self._repository.finalize_plan(
                guild_id=guild_id,
                plan_id=plan_id,
                status=PlanState.FAILED,
                verification_summary={
                    "strategy": "ACTOR_AUTHORIZATION_RECHECK",
                    "verified": False,
                    "errors": [exc.code],
                },
                error_code="ACTOR_AUTHORIZATION_REVOKED",
                correlation_id=correlation_id,
            )
            return
        if self._preflight is not None:
            result = await self._preflight.recheck(
                guild_id=guild_id,
                plan_id=plan_id,
                actor_authorization_fresh=True,
            )
            if not result.allowed:
                await self._repository.finalize_plan(
                    guild_id=guild_id,
                    plan_id=plan_id,
                    status=PlanState.FAILED,
                    verification_summary={
                        "strategy": "FINAL_PREFLIGHT",
                        "verified": False,
                        "errors": list(result.errors),
                    },
                    error_code="FINAL_PREFLIGHT_FAILED",
                    correlation_id=correlation_id,
                )
                return
        while True:
            unknown = await self._repository.unresolved_operation(guild_id, plan_id)
            if unknown is not None:
                await self._recover_unknown(guild_id, plan_id, unknown, correlation_id, governor)
                continue
            await self._faults.checkpoint("A_BEFORE_PREPARED_COMMIT")
            operation = await self._repository.prepare_next_operation(
                guild_id=guild_id,
                plan_id=plan_id,
                job_id=job_id,
                lease_owner=self._worker_id,
                lease_token=lease_token,
                lease_generation=lease_generation,
            )
            if operation is None:
                await self._finalize(guild_id, plan_id, correlation_id, governor)
                return
            operation_id = UUID(str(operation["id"]))
            attempt_id = UUID(str(operation["attempt_id"]))
            operation_type = OperationType(str(operation["operation_type"]))
            await self._faults.checkpoint("B_AFTER_PREPARED_BEFORE_IN_FLIGHT")

            async def check_precondition(
                operation_type: OperationType = operation_type,
                operation: dict[str, Any] = operation,
            ) -> PreconditionOutcome:
                return await self._adapter.check_preconditions(
                    guild_id=guild_id,
                    operation_type=operation_type,
                    payload=dict(operation["resolved_payload"]),
                    preconditions=dict(operation["preconditions"]),
                )

            precondition = (
                await governor.run_distributed(guild_id, check_precondition)
                if governor is not None
                else await check_precondition()
            )
            if precondition is not PreconditionOutcome.SATISFIED:
                await self._repository.reject_operation_precondition(
                    guild_id=guild_id,
                    plan_id=plan_id,
                    operation_id=operation_id,
                    attempt_id=attempt_id,
                    job_id=job_id,
                    lease_owner=self._worker_id,
                    lease_token=lease_token,
                    lease_generation=lease_generation,
                    outcome=precondition.value,
                    correlation_id=correlation_id,
                )
                return
            await self._repository.mark_attempt_in_flight(
                guild_id=guild_id,
                plan_id=plan_id,
                operation_id=operation_id,
                attempt_id=attempt_id,
                job_id=job_id,
                lease_owner=self._worker_id,
                lease_token=lease_token,
                lease_generation=lease_generation,
            )
            await self._faults.checkpoint("C_AFTER_IN_FLIGHT_BEFORE_NETWORK")

            async def mutate(
                operation_id: UUID = operation_id,
                operation_type: OperationType = operation_type,
                operation: dict[str, Any] = operation,
            ) -> Any:
                return await self._adapter.execute(
                    guild_id=guild_id,
                    plan_id=plan_id,
                    operation_id=operation_id,
                    correlation_id=correlation_id,
                    operation_type=operation_type,
                    payload=dict(operation["resolved_payload"]),
                )

            try:
                result = (
                    await governor.run_distributed(guild_id, mutate)
                    if governor is not None
                    else await mutate()
                )
                await self._faults.checkpoint("E_AFTER_DISCORD_BEFORE_COMMIT")
                await self._repository.record_operation_success(
                    guild_id=guild_id,
                    plan_id=plan_id,
                    job_id=job_id,
                    lease_owner=self._worker_id,
                    lease_token=lease_token,
                    lease_generation=lease_generation,
                    operation_id=operation_id,
                    attempt_id=attempt_id,
                    discord_status=result.discord_status,
                    result_payload=result.payload,
                    correlation_id=correlation_id,
                    audit_reason_fingerprint=result.audit_reason_fingerprint,
                )
                await self._faults.checkpoint("F_AFTER_SUCCESS_COMMIT")
            except MutableDiscordError as exc:
                if governor is not None:
                    governor.record_discord_failure(exc.failure)
                    await governor.record_distributed_failure(exc.failure)
                retryable_rejection = (
                    exc.failure.kind.value == "RATE_LIMITED" and not exc.outcome_unknown
                )
                await self._repository.record_operation_failure(
                    guild_id=guild_id,
                    plan_id=plan_id,
                    job_id=job_id,
                    lease_owner=self._worker_id,
                    lease_token=lease_token,
                    lease_generation=lease_generation,
                    operation_id=operation_id,
                    attempt_id=attempt_id,
                    unknown_outcome=exc.outcome_unknown,
                    discord_status=exc.failure.status_code,
                    discord_error_code=exc.failure.error_code,
                    error_classification=exc.failure.kind.value,
                    correlation_id=correlation_id,
                    retryable_rejection=retryable_rejection,
                )
                if retryable_rejection:
                    await asyncio.sleep(max(0.0, exc.failure.retry_after_seconds or 0.0))
                    continue
                if not exc.outcome_unknown:
                    await self._finalize(guild_id, plan_id, correlation_id, governor)
                    return

    async def _recover_unknown(
        self,
        guild_id: int,
        plan_id: UUID,
        operation: dict[str, Any],
        correlation_id: UUID,
        governor: DiscordWorkloadGovernor | None,
    ) -> None:
        async def recover() -> Any:
            return await self._adapter.recover(
                guild_id=guild_id,
                operation_type=OperationType(str(operation["operation_type"])),
                payload=dict(operation["desired_payload"]),
                before_payload=dict(operation["before_payload"]),
            )

        await self._faults.checkpoint("RECOVERY_BEFORE_RECONCILE")
        result = (
            await governor.run_distributed(guild_id, recover)
            if governor is not None
            else await recover()
        )
        await self._repository.resolve_unknown(
            guild_id=guild_id,
            plan_id=plan_id,
            operation_id=UUID(str(operation["id"])),
            outcome=result.outcome.value,
            resource_payload=result.payload,
            correlation_id=correlation_id,
        )
        await self._faults.checkpoint("RECOVERY_AFTER_RECONCILE")

    async def _finalize(
        self,
        guild_id: int,
        plan_id: UUID,
        correlation_id: UUID,
        governor: DiscordWorkloadGovernor | None,
    ) -> None:
        plan = await self._repository.get_plan(guild_id, plan_id)
        counts = await self._repository.operation_counts(guild_id, plan_id)
        total = sum(counts.values())
        succeeded = counts.get(OperationState.SUCCEEDED.value, 0)
        discord_verified = False
        post_verified = False
        error: str | None
        if str(plan["status"]) == PlanState.CANCEL_REQUESTED.value:
            terminal = PlanState.CANCELLED
            error = "CANCELLED_AT_SAFE_BOUNDARY"
        elif counts.get(OperationState.INTERVENTION_REQUIRED.value, 0):
            terminal = PlanState.INTERVENTION_REQUIRED
            error = "OPERATION_INTERVENTION_REQUIRED"
        elif counts.get(OperationState.FAILED.value, 0):
            terminal = PlanState.PARTIALLY_APPLIED if succeeded else PlanState.FAILED
            error = "OPERATION_FAILED"
        elif succeeded != total:
            terminal = PlanState.INTERVENTION_REQUIRED
            error = "DAG_BLOCKED"
        else:
            discord_verified = await self._verify(guild_id, plan_id, governor)
            post_verified = discord_verified
            if discord_verified and self._post_verification is not None:
                post_verified = await self._post_verification.apply(
                    guild_id=guild_id,
                    plan_id=plan_id,
                    correlation_id=correlation_id,
                )
            if not discord_verified:
                terminal = PlanState.VERIFICATION_FAILED
                error = "TARGETED_VERIFICATION_FAILED"
            elif not post_verified:
                terminal = PlanState.PARTIALLY_APPLIED
                error = "STAGE08_POST_VERIFICATION_FAILED"
            else:
                terminal = PlanState.SUCCEEDED
                error = None
        await self._faults.checkpoint("I_BEFORE_FINALIZE")
        await self._repository.finalize_plan(
            guild_id=guild_id,
            plan_id=plan_id,
            status=terminal,
            verification_summary={
                "strategy": "TARGETED_REST",
                "verified": terminal is PlanState.SUCCEEDED,
                "discord_verified": discord_verified,
                "post_verification_applied": post_verified,
                "completed_operations": succeeded,
                "total_operations": total,
            },
            error_code=error,
            correlation_id=correlation_id,
        )

    async def _verify(
        self,
        guild_id: int,
        plan_id: UUID,
        governor: DiscordWorkloadGovernor | None,
    ) -> bool:
        rows = await self._repository.verification_operations(guild_id, plan_id)
        for row in rows:

            async def verify(row: dict[str, Any] = row) -> bool:
                return await self._adapter.verify(
                    guild_id=guild_id,
                    operation_type=OperationType(str(row["operation_type"])),
                    payload=dict(row["resolved_payload"] or row["desired_payload"]),
                    result_payload=(
                        dict(row["result_payload"]) if row["result_payload"] is not None else None
                    ),
                )

            current = (
                await governor.run_distributed(guild_id, verify)
                if governor is not None
                else await verify()
            )
            await self._faults.checkpoint("G_DURING_VERIFICATION")
            if not current:
                return False
        return True
