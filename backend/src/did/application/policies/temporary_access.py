"""Durable expiry orchestration for temporary Policy grants.

The scheduler only prepares and queues the existing canonical DISABLE Plan.
Discord mutation remains exclusively owned by the normal APPLY_PLAN worker.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol
from uuid import UUID, uuid4

from did.application.planning.service import PlanningService
from did.application.policies.planning import PolicyPlanningService
from did.application.policies.service import POLICY_RECONCILER_ACTOR_ID, PolicyService
from did.domain.policies import PolicyLifecycleState, PolicyTemporaryAccess
from did.infrastructure.planning_repository import PlanningRepository
from did.infrastructure.policies_repository import PoliciesRepository
from did.planning.models import PlanOriginType, PlanState


class PlanCompletionHandler(Protocol):
    async def record_plan_outcome(
        self,
        *,
        guild_id: int,
        plan: dict[str, Any],
        status: PlanState,
        correlation_id: UUID,
    ) -> None: ...


class CompositePlanCompletion:
    """Fan terminal Plan outcomes out to independent durable projections."""

    def __init__(self, *handlers: PlanCompletionHandler) -> None:
        self._handlers = handlers

    async def record_plan_outcome(
        self,
        *,
        guild_id: int,
        plan: dict[str, Any],
        status: PlanState,
        correlation_id: UUID,
    ) -> None:
        for handler in self._handlers:
            await handler.record_plan_outcome(
                guild_id=guild_id,
                plan=plan,
                status=status,
                correlation_id=correlation_id,
            )


class TemporaryAccessScheduler:
    def __init__(
        self,
        *,
        repository: PoliciesRepository,
        policies: PolicyService,
        policy_planning: PolicyPlanningService,
        planning: PlanningService,
        planning_repository: PlanningRepository,
        lease_owner: str,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self._repository = repository
        self._policies = policies
        self._policy_planning = policy_planning
        self._planning = planning
        self._planning_repository = planning_repository
        self._lease_owner = lease_owner
        self._poll_interval_seconds = poll_interval_seconds
        self._logger = logging.getLogger(__name__)

    async def tick(self) -> int:
        claimed = await self._repository.claim_due_temporary_accesses(lease_owner=self._lease_owner)
        for schedule in claimed:
            await self._process(schedule)
        return len(claimed)

    async def _process(self, schedule: PolicyTemporaryAccess) -> None:
        try:
            policy = await self._policies.get(schedule.guild_id, schedule.policy_id)
            plan: dict[str, Any]
            correlation_id = uuid4()
            if schedule.removal_plan_id is None:
                if policy.lifecycle_state is not PolicyLifecycleState.ACTIVE:
                    raise RuntimeError("temporary_policy_is_not_active")
                idempotency_key = (
                    f"temporary-expiry:{schedule.policy_id}:{schedule.expires_at.isoformat()}"
                )
                _, plan, _, preflight = await self._policy_planning.create_disable_plan(
                    guild_id=schedule.guild_id,
                    policy_id=schedule.policy_id,
                    actor_user_id=POLICY_RECONCILER_ACTOR_ID,
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                    expected_revision=policy.revision,
                    temporary_access=True,
                )
                if not preflight.allowed:
                    raise RuntimeError("temporary_removal_preflight_blocked")
                if PlanState(str(plan["status"])) is PlanState.VALIDATED:
                    plan = await self._planning.confirm(
                        guild_id=schedule.guild_id,
                        plan_id=UUID(str(plan["id"])),
                        actor_user_id=POLICY_RECONCILER_ACTOR_ID,
                        idempotency_key=idempotency_key,
                        expected_version=int(plan["state_version"]),
                        supplied_plan_hash=str(plan["plan_hash"]),
                        reinforced_acknowledgement=True,
                        correlation_id=correlation_id,
                    )
                schedule = await self._repository.mark_temporary_removal_scheduled(
                    guild_id=schedule.guild_id,
                    policy_id=schedule.policy_id,
                    plan_id=UUID(str(plan["id"])),
                )
            else:
                plan = await self._planning_repository.get_plan(
                    schedule.guild_id, schedule.removal_plan_id
                )

            plan_id = UUID(str(plan["id"]))
            state = PlanState(str(plan["status"]))
            if state in {PlanState.SUCCEEDED, PlanState.APPLIED_WITH_PENDING_PROVIDER}:
                await self._repository.mark_temporary_plan_outcome(
                    guild_id=schedule.guild_id, plan_id=plan_id, succeeded=True
                )
                return
            if state in {
                PlanState.STALE,
                PlanState.PARTIALLY_APPLIED,
                PlanState.FAILED,
                PlanState.VERIFICATION_FAILED,
                PlanState.INTERVENTION_REQUIRED,
                PlanState.CANCELLED,
            }:
                await self._repository.mark_temporary_plan_outcome(
                    guild_id=schedule.guild_id,
                    plan_id=plan_id,
                    succeeded=False,
                    error=f"plan_{state.value.lower()}",
                )
                return
            if state is PlanState.CONFIRMED:
                policy = await self._policies.disable(
                    schedule.guild_id,
                    schedule.policy_id,
                    POLICY_RECONCILER_ACTOR_ID,
                    policy.revision,
                    f"temporary-disable:{schedule.policy_id}:{schedule.expires_at.isoformat()}",
                    plan_id,
                )
                await self._planning.apply(
                    guild_id=schedule.guild_id,
                    plan_id=plan_id,
                    actor_user_id=POLICY_RECONCILER_ACTOR_ID,
                    correlation_id=correlation_id,
                )
            # APPLYING is already durably owned by the canonical worker. Its
            # completion callback will project the terminal state here.
        except Exception as exc:
            self._logger.exception(
                "temporary access expiry failed",
                extra={"guild_id": schedule.guild_id, "policy_id": str(schedule.policy_id)},
            )
            await self._repository.mark_temporary_failure(
                guild_id=schedule.guild_id,
                policy_id=schedule.policy_id,
                error=type(exc).__name__,
            )

    async def record_plan_outcome(
        self,
        *,
        guild_id: int,
        plan: dict[str, Any],
        status: PlanState,
        correlation_id: UUID,
    ) -> None:
        del correlation_id
        metadata = dict(plan.get("origin_metadata") or {})
        if (
            str(plan.get("origin_type")) != PlanOriginType.POLICY.value
            or metadata.get("simulate") != "DISABLE"
            or metadata.get("temporary_access") is not True
        ):
            return
        await self._repository.mark_temporary_plan_outcome(
            guild_id=guild_id,
            plan_id=UUID(str(plan["id"])),
            succeeded=status in {PlanState.SUCCEEDED, PlanState.APPLIED_WITH_PENDING_PROVIDER},
            error=None
            if status in {PlanState.SUCCEEDED, PlanState.APPLIED_WITH_PENDING_PROVIDER}
            else f"plan_{status.value.lower()}",
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.tick()
            except Exception:
                self._logger.exception("temporary access scheduler tick failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                pass
