from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from did.application.policies.planning import AccessChange, ImpactAccuracy
from did.application.policies.reconciler import (
    PolicyReconcileResult,
    PolicyReconcilerService,
    ReconcileOutcome,
)
from did.application.policies.service import POLICY_RECONCILER_ACTOR_ID
from did.domain.policies import Policy, PolicyLifecycleState, PolicyScopeType
from did.planning.preflight import PreflightResult
from did.policies.resolver import PolicyResolutionOutcome

GUILD = 997_001
ACTOR = 997_011
CHANNEL = 997_101


def _policy(number: int, *, locked: bool = True, revision: int = 3) -> Policy:
    return Policy(
        UUID(int=number),
        GUILD,
        "ACCESS_CONTROL",
        1,
        "Locked",
        "",
        PolicyLifecycleState.ACTIVE,
        revision,
        PolicyScopeType.CHANNEL,
        str(CHANNEL),
        ({"kind": "ALWAYS"},),
        ({"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"},),
        {"summary": "Locked", "tags": []},
        ACTOR,
        ACTOR,
        priority=0,
        locked=locked,
    )


def _entry(
    change: AccessChange,
    *,
    proposed_outcome: PolicyResolutionOutcome = PolicyResolutionOutcome.CAN,
    current_outcome: PolicyResolutionOutcome = PolicyResolutionOutcome.CANNOT,
) -> SimpleNamespace:
    return SimpleNamespace(
        target=SimpleNamespace(
            subject_id=ACTOR,
            scope_type=PolicyScopeType.CHANNEL,
            scope_id=str(CHANNEL),
            requested_access="VIEW",
        ),
        access_change=change,
        proposed=SimpleNamespace(outcome=proposed_outcome),
        current=SimpleNamespace(outcome=current_outcome),
    )


def _preview(
    entries: tuple[SimpleNamespace, ...], *, accuracy: ImpactAccuracy = ImpactAccuracy.EXACT
) -> SimpleNamespace:
    return SimpleNamespace(
        entries=entries,
        impact=SimpleNamespace(accuracy=accuracy),
        source_versions=("cache-v1",),
    )


def _services(
    policy: Policy, preview: object
) -> tuple[PolicyReconcilerService, SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    policies = SimpleNamespace(
        list=AsyncMock(return_value=(policy,)),
        get=AsyncMock(return_value=policy),
        annotate_reconcile_status=AsyncMock(return_value=policy),
    )
    policy_planning = SimpleNamespace(
        detect_drift=AsyncMock(return_value=preview),
        create_drift_plan=AsyncMock(
            return_value=(
                preview,
                {
                    "id": uuid4(),
                    "status": "VALIDATED",
                    "state_version": 2,
                    "plan_hash": "hash",
                },
                True,
                PreflightResult(True),
            )
        ),
    )
    planning = SimpleNamespace(
        confirm=AsyncMock(
            side_effect=lambda **kwargs: {
                "id": kwargs["plan_id"],
                "status": "CONFIRMED",
                "state_version": kwargs["expected_version"] + 1,
                "plan_hash": kwargs["supplied_plan_hash"],
            }
        ),
        apply=AsyncMock(),
    )
    service = PolicyReconcilerService(
        policies=policies, policy_planning=policy_planning, planning=planning
    )  # type: ignore[arg-type]
    return service, policies, policy_planning, planning


@pytest.mark.asyncio
async def test_compliant_policy_is_left_untouched() -> None:
    policy = _policy(1)
    preview = _preview((_entry(AccessChange.UNCHANGED),))
    service, policies, policy_planning, planning = _services(policy, preview)

    result = await service.reconcile_policy(GUILD, policy)

    assert result == PolicyReconcileResult(policy.policy_id, ReconcileOutcome.COMPLIANT)
    policies.annotate_reconcile_status.assert_not_called()
    policy_planning.create_drift_plan.assert_not_called()
    planning.confirm.assert_not_called()


@pytest.mark.asyncio
async def test_drifted_policy_is_auto_repaired_via_the_canonical_plan_pipeline() -> None:
    policy = _policy(2)
    preview = _preview((_entry(AccessChange.GAINED),))
    service, policies, policy_planning, planning = _services(policy, preview)

    result = await service.reconcile_policy(GUILD, policy)

    assert result.outcome is ReconcileOutcome.REPAIR_SCHEDULED
    policy_planning.create_drift_plan.assert_awaited_once()
    call = policy_planning.create_drift_plan.await_args
    assert call.kwargs["actor_user_id"] == POLICY_RECONCILER_ACTOR_ID
    planning.confirm.assert_awaited_once()
    confirm_call = planning.confirm.await_args
    assert confirm_call.kwargs["actor_user_id"] == POLICY_RECONCILER_ACTOR_ID
    assert confirm_call.kwargs["reinforced_acknowledgement"] is True
    planning.apply.assert_awaited_once()
    policies.annotate_reconcile_status.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("terminal", "annotation"),
    [("SUCCEEDED", "repaired"), ("FAILED", "intervention_required")],
)
async def test_terminal_worker_outcome_is_annotated_only_after_plan_finalization(
    terminal: str, annotation: str
) -> None:
    from did.planning.models import PlanState

    policy = _policy(11)
    service, policies, _policy_planning, _planning = _services(policy, _preview(()))

    await service.record_plan_outcome(
        guild_id=GUILD,
        plan={
            "origin_type": "POLICY",
            "origin_metadata": {"simulate": "REASSERT", "auto_reconcile": True},
            "actor_user_id": POLICY_RECONCILER_ACTOR_ID,
            "source_policy_id": policy.policy_id,
            "source_policy_revision": policy.revision,
        },
        status=PlanState(terminal),
        correlation_id=uuid4(),
    )

    policies.annotate_reconcile_status.assert_awaited_once()
    assert policies.annotate_reconcile_status.await_args.kwargs["status"] == annotation


@pytest.mark.asyncio
async def test_unresolved_drift_marks_intervention_required() -> None:
    policy = _policy(3)
    preview = _preview(
        (_entry(AccessChange.BLOCKED, proposed_outcome=PolicyResolutionOutcome.BLOCKED),)
    )
    service, policies, policy_planning, planning = _services(policy, preview)

    result = await service.reconcile_policy(GUILD, policy)

    assert result.outcome is ReconcileOutcome.INTERVENTION_REQUIRED
    policy_planning.create_drift_plan.assert_not_called()
    planning.confirm.assert_not_called()
    policies.annotate_reconcile_status.assert_awaited_once()
    assert policies.annotate_reconcile_status.await_args.kwargs["status"] == "intervention_required"


@pytest.mark.asyncio
async def test_inexact_drift_accuracy_marks_intervention_required() -> None:
    policy = _policy(9)
    preview = _preview((_entry(AccessChange.GAINED),), accuracy=ImpactAccuracy.INCOMPLETE)
    service, _policies, policy_planning, _planning = _services(policy, preview)

    result = await service.reconcile_policy(GUILD, policy)

    assert result.outcome is ReconcileOutcome.INTERVENTION_REQUIRED
    policy_planning.create_drift_plan.assert_not_called()


@pytest.mark.asyncio
async def test_a_failed_confirm_or_apply_marks_intervention_required_and_never_raises() -> None:
    policy = _policy(4)
    preview = _preview((_entry(AccessChange.GAINED),))
    service, policies, _policy_planning, planning = _services(policy, preview)
    planning.apply.side_effect = RuntimeError("Discord apply worker unavailable")

    result = await service.reconcile_policy(GUILD, policy)

    assert result.outcome is ReconcileOutcome.INTERVENTION_REQUIRED
    assert result.reason == "auto_repair_failed"
    policies.annotate_reconcile_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_drift_check_failure_marks_intervention_required_and_never_raises() -> None:
    policy = _policy(10)
    policies = SimpleNamespace(
        list=AsyncMock(return_value=(policy,)),
        annotate_reconcile_status=AsyncMock(return_value=policy),
    )
    policy_planning = SimpleNamespace(
        detect_drift=AsyncMock(side_effect=RuntimeError("read model unavailable")),
        create_drift_plan=AsyncMock(),
    )
    planning = SimpleNamespace(confirm=AsyncMock(), apply=AsyncMock())
    service = PolicyReconcilerService(
        policies=policies, policy_planning=policy_planning, planning=planning
    )  # type: ignore[arg-type]

    result = await service.reconcile_policy(GUILD, policy)

    assert result.outcome is ReconcileOutcome.INTERVENTION_REQUIRED
    assert result.reason == "drift_check_failed"


@pytest.mark.asyncio
async def test_reconcile_guild_only_considers_active_locked_policies() -> None:
    locked_active = _policy(5, locked=True)
    unlocked_active = _policy(6, locked=False)
    preview = _preview(())
    policies = SimpleNamespace(
        list=AsyncMock(return_value=(locked_active, unlocked_active)),
        annotate_reconcile_status=AsyncMock(),
    )
    policy_planning = SimpleNamespace(
        detect_drift=AsyncMock(return_value=preview), create_drift_plan=AsyncMock()
    )
    planning = SimpleNamespace(confirm=AsyncMock(), apply=AsyncMock())
    service = PolicyReconcilerService(
        policies=policies, policy_planning=policy_planning, planning=planning
    )  # type: ignore[arg-type]

    results = await service.reconcile_guild(GUILD)

    assert len(results) == 1
    assert results[0].policy_id == locked_active.policy_id
    policy_planning.detect_drift.assert_awaited_once()
    assert policy_planning.detect_drift.await_args.kwargs["policy_id"] == locked_active.policy_id


@pytest.mark.asyncio
async def test_one_policys_failure_never_blocks_the_others_in_the_guild_sweep() -> None:
    failing = _policy(7)
    healthy = _policy(8)
    policies = SimpleNamespace(
        list=AsyncMock(return_value=(failing, healthy)),
        annotate_reconcile_status=AsyncMock(),
    )
    healthy_preview = _preview((_entry(AccessChange.UNCHANGED),))

    async def detect_drift(*, guild_id: int, policy_id: UUID, actor_user_id: int):
        if policy_id == failing.policy_id:
            raise RuntimeError("read model unavailable")
        return healthy_preview

    policy_planning = SimpleNamespace(
        detect_drift=AsyncMock(side_effect=detect_drift), create_drift_plan=AsyncMock()
    )
    planning = SimpleNamespace(confirm=AsyncMock(), apply=AsyncMock())
    service = PolicyReconcilerService(
        policies=policies, policy_planning=policy_planning, planning=planning
    )  # type: ignore[arg-type]

    results = await service.reconcile_guild(GUILD)

    outcomes = {result.policy_id: result.outcome for result in results}
    assert outcomes[failing.policy_id] is ReconcileOutcome.INTERVENTION_REQUIRED
    assert outcomes[healthy.policy_id] is ReconcileOutcome.COMPLIANT
