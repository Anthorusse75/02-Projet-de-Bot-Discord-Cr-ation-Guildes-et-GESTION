from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from did.planning.models import OperationState, OperationType, PlanState, RiskLevel


@dataclass(slots=True)
class PlanningMetrics:
    """Process-local bounded metrics; no tenant or Discord ID labels are accepted."""

    plans_by_state: Counter[str] = field(default_factory=Counter)
    plans_by_risk: Counter[str] = field(default_factory=Counter)
    operations_by_type_and_state: Counter[tuple[str, str]] = field(default_factory=Counter)
    unknown_recovery_outcomes: Counter[str] = field(default_factory=Counter)
    stale_plans: int = 0
    intervention_required: int = 0

    def plan_created(self, risk: RiskLevel) -> None:
        self.plans_by_state[PlanState.DRAFT.value] += 1
        self.plans_by_risk[risk.value] += 1

    def plan_transition(self, state: PlanState) -> None:
        self.plans_by_state[state.value] += 1
        if state is PlanState.STALE:
            self.stale_plans += 1
        if state is PlanState.INTERVENTION_REQUIRED:
            self.intervention_required += 1

    def operation_transition(self, operation_type: OperationType, state: OperationState) -> None:
        self.operations_by_type_and_state[(operation_type.value, state.value)] += 1

    def unknown_recovery(self, outcome: str) -> None:
        if outcome not in {
            "PROVED_CREATED",
            "PROVED_APPLIED",
            "PROVED_ABSENT",
            "AMBIGUOUS",
        }:
            raise ValueError("unknown recovery metric label must be bounded")
        self.unknown_recovery_outcomes[outcome] += 1

    def snapshot(self) -> dict[str, object]:
        return {
            "plans_by_state": dict(self.plans_by_state),
            "plans_by_risk": dict(self.plans_by_risk),
            "operations_by_type_and_state": {
                f"{operation_type}:{state}": count
                for (operation_type, state), count in self.operations_by_type_and_state.items()
            },
            "unknown_recovery_outcomes": dict(self.unknown_recovery_outcomes),
            "stale_plans": self.stale_plans,
            "intervention_required": self.intervention_required,
        }
