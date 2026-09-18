"""REQ-AP-LOCK-002/003/004/005: automatic reconciliation for LOCKED Policies.

This is deliberately NOT a second apply engine. Every corrective mutation
goes through the exact same canonical pipeline a human-initiated Policy
change already uses: detect_drift() -> create_drift_plan() (preview/plan,
PolicyPlanningService) -> confirm() -> apply() (PlanningService, the same
Stage05 Plan/Apply engine every other Plan in the product goes through).
The only thing specific to reconciliation is *who* initiates it
(POLICY_RECONCILER_ACTOR_ID, a reserved system actor -- see
did.application.policies.service) and that no human confirmation step is
required in between, because REQ-AP-LOCK-002 explicitly wants that for a
Policy the admin has already locked.

Trigger: `did/worker/io/worker.py`'s handler for RECONCILE_STRUCTURE calls
`reconcile_guild()` right after refreshing the guild's cache. That single
job type is already both event-driven (a Gateway continuity gap or drift
signal makes `ReconcileScheduler` enqueue it near-immediately, per
REQ-AP-LOCK-003's "event-driven trigger") and periodic (the adaptive
scheduler's normal polling is the safety net) -- so this module needs no
separate scheduler or Gateway hook of its own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from did.application.planning.service import PlanningService
from did.application.policies.planning import AccessChange, ImpactAccuracy, PolicyPlanningService
from did.application.policies.service import POLICY_RECONCILER_ACTOR_ID, PolicyService
from did.domain.policies import Policy, PolicyLifecycleState
from did.policies.resolver import PolicyResolutionOutcome

_INTERVENTION_TAG_VALUE = "intervention_required"
_REPAIRED_TAG_VALUE = "repaired"


class ReconcileOutcome(StrEnum):
    COMPLIANT = "COMPLIANT"
    REPAIRED = "REPAIRED"
    INTERVENTION_REQUIRED = "INTERVENTION_REQUIRED"


@dataclass(frozen=True, slots=True)
class PolicyReconcileResult:
    policy_id: UUID
    outcome: ReconcileOutcome
    reason: str | None = None


class PolicyReconcilerService:
    def __init__(
        self,
        *,
        policies: PolicyService,
        policy_planning: PolicyPlanningService,
        planning: PlanningService,
    ) -> None:
        self._policies = policies
        self._policy_planning = policy_planning
        self._planning = planning
        self._logger = logging.getLogger(__name__)

    async def reconcile_guild(self, guild_id: int) -> tuple[PolicyReconcileResult, ...]:
        """Check every ACTIVE, LOCKED Policy in this guild for drift and
        auto-repair it. Never raises for an individual Policy's failure --
        one bad Policy must not block the others; each failure is reported
        as INTERVENTION_REQUIRED instead.
        """
        policies = await self._policies.list(guild_id)
        locked = tuple(
            policy
            for policy in policies
            if policy.locked and policy.lifecycle_state is PolicyLifecycleState.ACTIVE
        )
        results = []
        for policy in locked:
            results.append(await self.reconcile_policy(guild_id, policy))
        return tuple(results)

    async def reconcile_policy(self, guild_id: int, policy: Policy) -> PolicyReconcileResult:
        try:
            preview = await self._policy_planning.detect_drift(
                guild_id=guild_id,
                policy_id=policy.policy_id,
                actor_user_id=POLICY_RECONCILER_ACTOR_ID,
            )
        except Exception:
            self._logger.exception(
                "policy reconciler: drift check failed", extra={"policy_id": str(policy.policy_id)}
            )
            return await self._mark_intervention_required(guild_id, policy, "drift_check_failed")

        drifted = [
            entry for entry in preview.entries if entry.access_change is not AccessChange.UNCHANGED
        ]
        if not drifted:
            return PolicyReconcileResult(policy.policy_id, ReconcileOutcome.COMPLIANT)

        # REQ-AP-LOCK-005: an inexact or unresolved comparison is never
        # silently treated as compliant or auto-repaired blind.
        unresolved_outcomes = {PolicyResolutionOutcome.BLOCKED, PolicyResolutionOutcome.UNKNOWN}
        unresolved = any(
            entry.proposed.outcome in unresolved_outcomes
            or entry.current.outcome is PolicyResolutionOutcome.UNKNOWN
            for entry in preview.entries
        )
        if preview.impact.accuracy is not ImpactAccuracy.EXACT or unresolved:
            return await self._mark_intervention_required(
                guild_id, policy, "drift_not_exact_or_unresolved"
            )

        try:
            idempotency_key = f"reconcile:{policy.policy_id}:{policy.revision}"
            correlation_id = uuid4()
            _, plan, _, preflight = await self._policy_planning.create_drift_plan(
                guild_id=guild_id,
                policy_id=policy.policy_id,
                actor_user_id=POLICY_RECONCILER_ACTOR_ID,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                expected_revision=policy.revision,
            )
            if not preflight.allowed:
                return await self._mark_intervention_required(
                    guild_id, policy, "drift_plan_preflight_blocked"
                )
            await self._planning.confirm(
                guild_id=guild_id,
                plan_id=plan["id"],
                actor_user_id=POLICY_RECONCILER_ACTOR_ID,
                idempotency_key=idempotency_key,
                expected_version=int(plan["state_version"]),
                supplied_plan_hash=str(plan["plan_hash"]),
                reinforced_acknowledgement=True,
                correlation_id=correlation_id,
            )
            await self._planning.apply(
                guild_id=guild_id,
                plan_id=plan["id"],
                actor_user_id=POLICY_RECONCILER_ACTOR_ID,
                correlation_id=correlation_id,
            )
        except Exception:
            self._logger.exception(
                "policy reconciler: auto-repair failed", extra={"policy_id": str(policy.policy_id)}
            )
            return await self._mark_intervention_required(guild_id, policy, "auto_repair_failed")

        await self._annotate(guild_id, policy, _REPAIRED_TAG_VALUE)
        return PolicyReconcileResult(policy.policy_id, ReconcileOutcome.REPAIRED)

    async def _mark_intervention_required(
        self, guild_id: int, policy: Policy, reason: str
    ) -> PolicyReconcileResult:
        await self._annotate(guild_id, policy, _INTERVENTION_TAG_VALUE)
        return PolicyReconcileResult(
            policy.policy_id, ReconcileOutcome.INTERVENTION_REQUIRED, reason
        )

    async def _annotate(self, guild_id: int, policy: Policy, status: str) -> None:
        try:
            await self._policies.annotate_reconcile_status(
                guild_id,
                policy.policy_id,
                status=status,
                expected_revision=policy.revision,
                idempotency_key=f"reconcile-status:{policy.policy_id}:{policy.revision}:{status}",
            )
        except Exception:
            # The Policy revision moved under us (e.g. an admin edited it
            # concurrently) -- the next reconciliation pass will re-evaluate
            # from the new revision. Never let an annotation race mask the
            # drift/repair outcome already returned to the caller.
            self._logger.warning(
                "policy reconciler: could not annotate reconcile status (revision moved)",
                extra={"policy_id": str(policy.policy_id), "status": status},
            )
