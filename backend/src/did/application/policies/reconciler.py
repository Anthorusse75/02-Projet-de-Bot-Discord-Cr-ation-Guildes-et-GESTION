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

Trigger: `RuntimeRepository.ingest_gateway_event()` durably coalesces a
`RECONCILE_STRUCTURE` job for an externally-originated channel/role/member
change; `did/worker/io/worker.py` refreshes the Guild cache and then calls
`reconcile_guild()`. The existing adaptive scheduler enqueues that same job
type periodically as the lost-event safety net. Expected Gateway events from
DID's own Plans are classified and excluded, preventing repair loops.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from did.application.planning.service import PlanningService
from did.application.policies.planning import (
    AccessChange,
    ImpactAccuracy,
    PolicyPlanningService,
    drift_fingerprint,
)
from did.application.policies.service import POLICY_RECONCILER_ACTOR_ID, PolicyService
from did.domain.policies import Policy, PolicyLifecycleState
from did.planning.models import PlanOriginType, PlanState
from did.policies.resolver import PolicyResolutionOutcome

_INTERVENTION_TAG_VALUE = "intervention_required"
_REPAIRED_TAG_VALUE = "repaired"


class ReconcileOutcome(StrEnum):
    COMPLIANT = "COMPLIANT"
    REPAIR_SCHEDULED = "REPAIR_SCHEDULED"
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
            idempotency_key = (
                f"reconcile:{policy.policy_id}:{policy.revision}:{drift_fingerprint(preview)[:20]}"
            )
            correlation_id = uuid4()
            _, plan, created, preflight = await self._policy_planning.create_drift_plan(
                guild_id=guild_id,
                policy_id=policy.policy_id,
                actor_user_id=POLICY_RECONCILER_ACTOR_ID,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                expected_revision=policy.revision,
                auto_reconcile=True,
            )
            if not preflight.allowed:
                return await self._mark_intervention_required(
                    guild_id, policy, "drift_plan_preflight_blocked"
                )
            plan_state = PlanState(str(plan["status"]))
            if created or plan_state is PlanState.VALIDATED:
                plan = await self._planning.confirm(
                    guild_id=guild_id,
                    plan_id=plan["id"],
                    actor_user_id=POLICY_RECONCILER_ACTOR_ID,
                    idempotency_key=idempotency_key,
                    expected_version=int(plan["state_version"]),
                    supplied_plan_hash=str(plan["plan_hash"]),
                    reinforced_acknowledgement=True,
                    correlation_id=correlation_id,
                )
                plan_state = PlanState(str(plan["status"]))
            if plan_state is PlanState.CONFIRMED:
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

        # Enqueueing is not success.  The canonical APPLY_PLAN worker still
        # has to re-authorize, re-run preflight, mutate Discord and verify the
        # result.  Its completion callback records REPAIRED or
        # INTERVENTION_REQUIRED without invalidating this Plan beforehand.
        return PolicyReconcileResult(policy.policy_id, ReconcileOutcome.REPAIR_SCHEDULED)

    async def record_plan_outcome(
        self,
        *,
        guild_id: int,
        plan: dict[str, Any],
        status: PlanState,
        correlation_id: UUID,
    ) -> None:
        """Persist the honest terminal state of an automatic repair Plan.

        This runs only after the canonical worker has finalized and verified
        the Plan.  In particular, it never increments a Policy revision while
        that same revision is still required by final preflight.
        """

        del correlation_id
        metadata = dict(plan.get("origin_metadata") or {})
        if (
            str(plan.get("origin_type")) != PlanOriginType.POLICY.value
            or metadata.get("simulate") != "REASSERT"
            or metadata.get("auto_reconcile") is not True
            or int(plan.get("actor_user_id") or 0) != POLICY_RECONCILER_ACTOR_ID
            or plan.get("source_policy_id") is None
        ):
            return
        policy = await self._policies.get(guild_id, UUID(str(plan["source_policy_id"])))
        source_revision = int(plan.get("source_policy_revision") or 0)
        if policy.revision != source_revision:
            self._logger.warning(
                "policy reconciler: terminal Plan belongs to an older Policy revision",
                extra={"policy_id": str(policy.policy_id), "plan_status": status.value},
            )
            return
        terminal_success = status in {
            PlanState.SUCCEEDED,
            PlanState.APPLIED_WITH_PENDING_PROVIDER,
        }
        await self._annotate(
            guild_id,
            policy,
            _REPAIRED_TAG_VALUE if terminal_success else _INTERVENTION_TAG_VALUE,
        )

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
