from __future__ import annotations

from dataclasses import dataclass

from did.planning.models import OperationType, PlanOperation, RiskLevel, thaw_json_object


@dataclass(frozen=True, slots=True)
class ImpactSummary:
    affected_resources: int
    affected_subjects: int = 0
    permission_additions: int = 0
    permission_removals: int = 0
    visibility_losses: int = 0
    administrator_grants: int = 0
    incomplete_or_unknown: bool = False

    def __post_init__(self) -> None:
        values = (
            self.affected_resources,
            self.affected_subjects,
            self.permission_additions,
            self.permission_removals,
            self.visibility_losses,
            self.administrator_grants,
        )
        if any(value < 0 for value in values):
            raise ValueError("impact counters cannot be negative")


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    level: RiskLevel
    score: int
    reasons: tuple[str, ...]
    impact: ImpactSummary
    reinforced_confirmation_required: bool


class RiskEngine:
    """Deterministic risk classification using operation, blast radius and uncertainty."""

    def assess(
        self,
        operations: tuple[PlanOperation, ...],
        impact: ImpactSummary,
    ) -> RiskAssessment:
        score = 0
        reasons: list[str] = []
        for operation in operations:
            payload = thaw_json_object(operation.desired_payload)
            if operation.operation_type in {
                OperationType.DELETE_CHANNEL,
                OperationType.DELETE_ROLE,
            }:
                score += 40
                reasons.append("risk.destructive_delete")
            elif operation.operation_type in {
                OperationType.UPSERT_OVERWRITE,
                OperationType.DELETE_OVERWRITE,
                OperationType.REORDER_ROLES,
            }:
                score += 12
            else:
                score += 4
            permissions = int(payload.get("permissions", 0))
            if permissions & (1 << 3):
                score += 70
                reasons.append("risk.administrator_grant")
            if (
                operation.resource_type.value == "CATEGORY"
                and operation.operation_type is OperationType.DELETE_CHANNEL
            ):
                score += 20
                reasons.append("risk.category_delete")
        score += min(30, impact.affected_resources // 10)
        score += min(25, impact.affected_subjects // 100)
        if impact.visibility_losses:
            score += 20
            reasons.append("risk.visibility_loss")
        if impact.incomplete_or_unknown:
            score += 30
            reasons.append("risk.impact_unknown")
        if impact.administrator_grants:
            score += 70
            reasons.append("risk.administrator_impact")
        if score >= 80:
            level = RiskLevel.CRITICAL
        elif score >= 40:
            level = RiskLevel.HIGH
        elif score >= 15:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW
        destructive = any(
            operation.operation_type in {OperationType.DELETE_CHANNEL, OperationType.DELETE_ROLE}
            for operation in operations
        )
        return RiskAssessment(
            level,
            score,
            tuple(sorted(set(reasons))),
            impact,
            destructive and level in {RiskLevel.HIGH, RiskLevel.CRITICAL},
        )
