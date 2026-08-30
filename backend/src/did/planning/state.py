from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from did.planning.models import AttemptState, OperationState, PlanState


class InvalidStateTransition(ValueError):
    pass


PLAN_TRANSITIONS: Mapping[PlanState, frozenset[PlanState]] = {
    PlanState.DRAFT: frozenset({PlanState.VALIDATED, PlanState.STALE, PlanState.CANCELLED}),
    PlanState.VALIDATED: frozenset({PlanState.CONFIRMED, PlanState.STALE, PlanState.CANCELLED}),
    PlanState.CONFIRMED: frozenset({PlanState.APPLYING, PlanState.STALE, PlanState.CANCELLED}),
    PlanState.APPLYING: frozenset(
        {
            PlanState.APPLIED_WITH_PENDING_PROVIDER,
            PlanState.PARTIALLY_APPLIED,
            PlanState.SUCCEEDED,
            PlanState.FAILED,
            PlanState.VERIFICATION_FAILED,
            PlanState.CANCEL_REQUESTED,
            PlanState.INTERVENTION_REQUIRED,
        }
    ),
    PlanState.CANCEL_REQUESTED: frozenset(
        {PlanState.CANCELLED, PlanState.PARTIALLY_APPLIED, PlanState.INTERVENTION_REQUIRED}
    ),
    PlanState.APPLIED_WITH_PENDING_PROVIDER: frozenset(),
    PlanState.PARTIALLY_APPLIED: frozenset(),
    PlanState.SUCCEEDED: frozenset(),
    PlanState.FAILED: frozenset(),
    PlanState.VERIFICATION_FAILED: frozenset(),
    PlanState.CANCELLED: frozenset(),
    PlanState.STALE: frozenset(),
    PlanState.INTERVENTION_REQUIRED: frozenset(),
}

OPERATION_TRANSITIONS: Mapping[OperationState, frozenset[OperationState]] = {
    OperationState.PENDING: frozenset({OperationState.IN_FLIGHT, OperationState.CANCELLED}),
    OperationState.IN_FLIGHT: frozenset(
        {OperationState.SUCCEEDED, OperationState.FAILED, OperationState.UNKNOWN_OUTCOME}
    ),
    OperationState.UNKNOWN_OUTCOME: frozenset(
        {
            OperationState.PENDING,
            OperationState.SUCCEEDED,
            OperationState.IN_FLIGHT,
            OperationState.INTERVENTION_REQUIRED,
        }
    ),
    OperationState.SUCCEEDED: frozenset(),
    OperationState.FAILED: frozenset(),
    OperationState.INTERVENTION_REQUIRED: frozenset(),
    OperationState.CANCELLED: frozenset(),
}

ATTEMPT_TRANSITIONS: Mapping[AttemptState, frozenset[AttemptState]] = {
    AttemptState.PREPARED: frozenset({AttemptState.IN_FLIGHT, AttemptState.FAILED}),
    AttemptState.IN_FLIGHT: frozenset(
        {AttemptState.SUCCEEDED, AttemptState.FAILED, AttemptState.UNKNOWN}
    ),
    AttemptState.SUCCEEDED: frozenset(),
    AttemptState.FAILED: frozenset(),
    AttemptState.UNKNOWN: frozenset(),
}


def _transition[T: StrEnum](
    current: T,
    target: T,
    transitions: Mapping[T, frozenset[T]],
) -> T:
    if target not in transitions[current]:
        raise InvalidStateTransition(f"invalid transition {current.value} -> {target.value}")
    return target


def transition_plan(current: PlanState, target: PlanState) -> PlanState:
    return _transition(current, target, PLAN_TRANSITIONS)


def transition_operation(current: OperationState, target: OperationState) -> OperationState:
    return _transition(current, target, OPERATION_TRANSITIONS)


def transition_attempt(current: AttemptState, target: AttemptState) -> AttemptState:
    return _transition(current, target, ATTEMPT_TRANSITIONS)
