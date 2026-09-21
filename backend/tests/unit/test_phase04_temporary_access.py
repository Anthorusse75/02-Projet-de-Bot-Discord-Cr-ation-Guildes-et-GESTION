from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from did.application.policies.temporary_access import TemporaryAccessScheduler
from did.domain.policies import (
    Policy,
    PolicyLifecycleState,
    PolicyScopeType,
    PolicyTemporaryAccess,
    TemporaryAccessState,
)
from did.planning.models import PlanState
from did.planning.preflight import PreflightResult

GUILD = 998_001
ACTOR = 998_011
POLICY_ID = UUID(int=41)
PLAN_ID = UUID(int=42)
NOW = datetime(2026, 9, 21, 10, tzinfo=UTC)


def _policy() -> Policy:
    return Policy(
        POLICY_ID,
        GUILD,
        "ACCESS_CONTROL",
        1,
        "Temporary staff access",
        "",
        PolicyLifecycleState.ACTIVE,
        2,
        PolicyScopeType.CHANNEL,
        "998101",
        ({"kind": "ALWAYS"},),
        ({"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"},),
        {"summary": "Temporary"},
        ACTOR,
        ACTOR,
    )


def _schedule(*, plan_id: UUID | None = None) -> PolicyTemporaryAccess:
    return PolicyTemporaryAccess(
        guild_id=GUILD,
        policy_id=POLICY_ID,
        expires_at=NOW - timedelta(minutes=1),
        status=TemporaryAccessState.PROCESSING,
        created_by_user_id=ACTOR,
        removal_plan_id=plan_id,
    )


def _runtime(schedule: PolicyTemporaryAccess):
    policy = _policy()
    repository = SimpleNamespace(
        claim_due_temporary_accesses=AsyncMock(return_value=(schedule,)),
        mark_temporary_removal_scheduled=AsyncMock(
            return_value=replace(
                schedule,
                status=TemporaryAccessState.REMOVAL_SCHEDULED,
                removal_plan_id=PLAN_ID,
            )
        ),
        mark_temporary_failure=AsyncMock(),
        mark_temporary_plan_outcome=AsyncMock(),
    )
    policies = SimpleNamespace(
        get=AsyncMock(return_value=policy),
        disable=AsyncMock(
            return_value=replace(policy, lifecycle_state=PolicyLifecycleState.DISABLED)
        ),
    )
    policy_planning = SimpleNamespace(
        create_disable_plan=AsyncMock(
            return_value=(
                object(),
                {
                    "id": PLAN_ID,
                    "status": "VALIDATED",
                    "state_version": 3,
                    "plan_hash": "hash",
                },
                True,
                PreflightResult(True),
            )
        )
    )
    planning = SimpleNamespace(
        confirm=AsyncMock(
            return_value={
                "id": PLAN_ID,
                "status": "CONFIRMED",
                "state_version": 4,
                "plan_hash": "hash",
            }
        ),
        apply=AsyncMock(),
    )
    planning_repository = SimpleNamespace(get_plan=AsyncMock())
    runtime = TemporaryAccessScheduler(
        repository=repository,
        policies=policies,
        policy_planning=policy_planning,
        planning=planning,
        planning_repository=planning_repository,
        lease_owner="test-scheduler",
    )
    return runtime, repository, policies, policy_planning, planning


@pytest.mark.asyncio
async def test_due_expiry_builds_and_queues_only_the_canonical_disable_plan() -> None:
    runtime, repository, policies, policy_planning, planning = _runtime(_schedule())

    assert await runtime.tick() == 1

    call = policy_planning.create_disable_plan.await_args.kwargs
    assert call["temporary_access"] is True
    assert call["expected_revision"] == 2
    planning.confirm.assert_awaited_once()
    repository.mark_temporary_removal_scheduled.assert_awaited_once_with(
        guild_id=GUILD, policy_id=POLICY_ID, plan_id=PLAN_ID
    )
    policies.disable.assert_awaited_once()
    planning.apply.assert_awaited_once()
    repository.mark_temporary_failure.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_worker_failure_becomes_actionable_not_removed() -> None:
    runtime, repository, *_ = _runtime(_schedule(plan_id=PLAN_ID))
    plan = {
        "id": PLAN_ID,
        "origin_type": "POLICY",
        "origin_metadata": {"simulate": "DISABLE", "temporary_access": True},
    }

    await runtime.record_plan_outcome(
        guild_id=GUILD,
        plan=plan,
        status=PlanState.VERIFICATION_FAILED,
        correlation_id=uuid4(),
    )

    repository.mark_temporary_plan_outcome.assert_awaited_once_with(
        guild_id=GUILD,
        plan_id=PLAN_ID,
        succeeded=False,
        error="plan_verification_failed",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [PlanState.STALE, PlanState.PARTIALLY_APPLIED])
async def test_recovered_terminal_plan_becomes_actionable(state: PlanState) -> None:
    runtime, repository, *_ = _runtime(_schedule(plan_id=PLAN_ID))
    runtime._planning_repository.get_plan.return_value = {
        "id": PLAN_ID,
        "status": state.value,
    }

    assert await runtime.tick() == 1

    repository.mark_temporary_plan_outcome.assert_awaited_once_with(
        guild_id=GUILD,
        plan_id=PLAN_ID,
        succeeded=False,
        error=f"plan_{state.value.lower()}",
    )
    repository.mark_temporary_failure.assert_not_called()


@pytest.mark.asyncio
async def test_transient_preparation_failure_is_durably_retried() -> None:
    runtime, repository, _, policy_planning, planning = _runtime(_schedule())
    policy_planning.create_disable_plan.side_effect = RuntimeError("read model unavailable")

    assert await runtime.tick() == 1

    repository.mark_temporary_failure.assert_awaited_once_with(
        guild_id=GUILD,
        policy_id=POLICY_ID,
        error="RuntimeError",
    )
    planning.apply.assert_not_called()
