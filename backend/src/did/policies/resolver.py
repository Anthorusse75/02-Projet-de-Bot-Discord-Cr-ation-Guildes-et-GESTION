"""Deterministic, fail-closed resolver for declarative Policies.

The normative precedence rule is deliberately independent from persistence
order: higher explicit ``Policy.priority`` wins first; at equal priority, a
strictly more specific scope wins only inside a declared hierarchy.  The
resource hierarchy is GUILD -> LOGICAL_GROUP -> CATEGORY -> CHANNEL and the
subject hierarchy is GUILD -> ROLE -> MEMBER/BOT.  Resource and subject scopes
are incomparable at equal priority, so incompatible effects block instead of
being broken by an arbitrary total order.  Stable IDs are used only to order
the explanation, never to decide a semantic tie.

This module evaluates the closed ACCESS_CONTROL v1 registry.  It performs no
Discord I/O, planning or mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID

from did.domain.discord_runtime import CoverageMode, FreshnessState
from did.domain.policies import Policy, PolicyLifecycleState, PolicyScopeType
from did.policies.registry import (
    POLICY_TYPE_REGISTRY,
    PolicyDefinitionValidationError,
    PolicyTypeRegistry,
)


class PolicyResolutionOutcome(StrEnum):
    CAN = "CAN"
    CANNOT = "CANNOT"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class PolicyTruthValue(StrEnum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class PolicyTargetState(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    DELETED = "DELETED"
    INACCESSIBLE = "INACCESSIBLE"
    UNKNOWN = "UNKNOWN"


class PolicyConflictOutcome(StrEnum):
    RESOLVED = "RESOLVED"
    BLOCKED = "BLOCKED"


class PolicyScopeFamily(StrEnum):
    UNIVERSAL = "UNIVERSAL"
    RESOURCE = "RESOURCE"
    SUBJECT = "SUBJECT"
    INCOMPARABLE = "INCOMPARABLE"


_RESOURCE_SPECIFICITY = {
    PolicyScopeType.GUILD: 0,
    PolicyScopeType.LOGICAL_GROUP: 1,
    PolicyScopeType.CATEGORY: 2,
    PolicyScopeType.CHANNEL: 3,
}
_SUBJECT_SPECIFICITY = {
    PolicyScopeType.GUILD: 0,
    PolicyScopeType.ROLE: 1,
    PolicyScopeType.MEMBER: 2,
    PolicyScopeType.BOT: 2,
}
_TARGET_SCOPE_TYPES = frozenset(
    {
        PolicyScopeType.GUILD,
        PolicyScopeType.LOGICAL_GROUP,
        PolicyScopeType.CATEGORY,
        PolicyScopeType.CHANNEL,
    }
)


@dataclass(frozen=True, slots=True)
class PolicyResolutionContext:
    guild_id: int
    requested_access: str
    target_scope_type: PolicyScopeType
    target_scope_id: str | None
    target_state: PolicyTargetState
    target_freshness: FreshnessState
    coverage: CoverageMode
    subject_id: int
    subject_role_ids: tuple[str, ...]
    subject_roles_complete: bool
    subject_freshness: FreshnessState
    subject_is_bot: bool | None
    category_id: str | None = None
    logical_group_ids: tuple[str, ...] = ()
    known_role_ids: tuple[str, ...] = ()
    roles_catalog_complete: bool = False
    source_versions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.guild_id <= 0 or self.subject_id <= 0:
            raise ValueError("Policy resolution identifiers must be positive")
        if self.target_scope_type not in _TARGET_SCOPE_TYPES:
            raise ValueError("Policy resolution target must be a resource scope")
        if self.target_scope_type is PolicyScopeType.GUILD:
            if self.target_scope_id is not None:
                raise ValueError("GUILD resolution target_id must be null")
        elif self.target_scope_id is None or not self.target_scope_id:
            raise ValueError("non-GUILD resolution target_id must be explicit")
        if self.requested_access not in {"VIEW", "WRITE", "MANAGE", "CONNECT", "SPEAK"}:
            raise ValueError("requested access is not supported by ACCESS_CONTROL v1")
        if len(set(self.subject_role_ids)) != len(self.subject_role_ids):
            raise ValueError("subject role IDs must be unique")


@dataclass(frozen=True, slots=True)
class ApplicablePolicy:
    policy_id: UUID
    revision: int
    priority: int
    scope_type: PolicyScopeType
    scope_id: str | None
    inherited: bool
    specificity: int


@dataclass(frozen=True, slots=True)
class PolicySourceScope:
    policy_id: UUID
    revision: int
    scope_type: PolicyScopeType
    scope_id: str | None
    family: PolicyScopeFamily
    specificity: int
    inherited: bool


@dataclass(frozen=True, slots=True)
class PolicyConditionEvaluation:
    policy_id: UUID
    revision: int
    condition_index: int
    kind: str
    outcome: PolicyTruthValue
    reason: str


@dataclass(frozen=True, slots=True)
class PolicyContribution:
    policy_id: UUID
    revision: int
    effect_index: int
    priority: int
    scope_type: PolicyScopeType
    scope_id: str | None
    family: PolicyScopeFamily
    specificity: int
    inherited: bool
    access: str
    decision: str
    condition_outcome: PolicyTruthValue
    selected: bool = False
    disposition: str = "CANDIDATE"


@dataclass(frozen=True, slots=True)
class PolicyPriorityTraceEntry:
    policy_id: UUID
    revision: int
    effect_index: int
    priority: int
    family: PolicyScopeFamily
    specificity: int
    canonical_position: int
    disposition: str
    resolution_rule: str | None


@dataclass(frozen=True, slots=True)
class PolicyConflict:
    policy_ids: tuple[UUID, ...]
    revisions: tuple[int, ...]
    source_scopes: tuple[str, ...]
    effects: tuple[str, ...]
    resolution_rule: str | None
    outcome: PolicyConflictOutcome
    winning_policy_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class PolicyResolution:
    guild_id: int
    subject_id: int
    decision: str
    outcome: PolicyResolutionOutcome
    target_scope_type: PolicyScopeType
    target_scope_id: str | None
    target_state: PolicyTargetState
    target_freshness: FreshnessState
    coverage: CoverageMode
    applicable_policies: tuple[ApplicablePolicy, ...]
    contributions: tuple[PolicyContribution, ...]
    conflicts: tuple[PolicyConflict, ...]
    source_scopes: tuple[PolicySourceScope, ...]
    priority_trace: tuple[PolicyPriorityTraceEntry, ...]
    conditions: tuple[PolicyConditionEvaluation, ...]
    incomplete_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    source_versions: tuple[str, ...]


class PolicyResolver:
    """Resolve one ACCESS_CONTROL decision from active Policy declarations."""

    def __init__(self, registry: PolicyTypeRegistry = POLICY_TYPE_REGISTRY) -> None:
        self._registry = registry

    def resolve(
        self,
        *,
        policies: tuple[Policy, ...],
        context: PolicyResolutionContext,
    ) -> PolicyResolution:
        if any(policy.guild_id != context.guild_id for policy in policies):
            raise ValueError("Policy resolution input crosses a tenant boundary")

        conditions: list[PolicyConditionEvaluation] = []
        contributions: list[PolicyContribution] = []
        incomplete: list[str] = []
        warnings = list(context.warnings)
        invalid_relevant_policy = False

        active = sorted(
            (
                policy
                for policy in policies
                if policy.lifecycle_state is PolicyLifecycleState.ACTIVE
            ),
            key=self._policy_order,
        )
        for policy in active:
            scope_outcome, scope_reason = self._scope_matches(policy, context)
            if scope_outcome is PolicyTruthValue.FALSE:
                continue
            if scope_outcome is PolicyTruthValue.UNKNOWN:
                incomplete.append(scope_reason)
            try:
                definition = self._registry.validate(
                    policy_type=policy.policy_type,
                    contract_version=policy.contract_version,
                    scope_type=policy.scope_type,
                    conditions=policy.conditions,
                    effects=policy.effects,
                    metadata=policy.metadata,
                )
            except PolicyDefinitionValidationError:
                invalid_relevant_policy = True
                incomplete.append(f"policy.definition_invalid:{policy.policy_id}")
                continue

            requested_effects = tuple(
                (index, effect)
                for index, effect in enumerate(definition.effects)
                if effect.get("access") == context.requested_access
            )
            if not requested_effects:
                continue

            condition_outcome: PolicyTruthValue = scope_outcome
            if scope_outcome is PolicyTruthValue.TRUE:
                condition_outcome = PolicyTruthValue.TRUE
                for index, condition in enumerate(definition.conditions):
                    evaluated = self._evaluate_condition(policy, index, condition, context)
                    conditions.append(evaluated)
                    condition_outcome = self._and(condition_outcome, evaluated.outcome)
                    if evaluated.outcome is PolicyTruthValue.UNKNOWN:
                        incomplete.append(evaluated.reason)
            else:
                conditions.append(
                    PolicyConditionEvaluation(
                        policy.policy_id,
                        policy.revision,
                        -1,
                        "SCOPE_MATCH",
                        PolicyTruthValue.UNKNOWN,
                        scope_reason,
                    )
                )

            family, specificity = self._specificity(policy.scope_type)
            inherited = self._is_inherited(policy, context)
            for effect_index, effect in requested_effects:
                effect_outcome = condition_outcome
                audience = effect.get("audience")
                if audience is not None and scope_outcome is PolicyTruthValue.TRUE:
                    assert isinstance(audience, dict)
                    audience_evaluation = self._evaluate_condition(
                        policy,
                        len(definition.conditions) + effect_index,
                        {
                            "kind": "ROLE_MATCH",
                            "match": audience["match"],
                            "role_ids": audience["role_ids"],
                        },
                        context,
                    )
                    if audience["mode"] == "EXCLUDE":
                        inverted = {
                            PolicyTruthValue.TRUE: PolicyTruthValue.FALSE,
                            PolicyTruthValue.FALSE: PolicyTruthValue.TRUE,
                            PolicyTruthValue.UNKNOWN: PolicyTruthValue.UNKNOWN,
                        }[audience_evaluation.outcome]
                        audience_evaluation = replace(
                            audience_evaluation,
                            outcome=inverted,
                            kind="ROLE_AUDIENCE_EXCLUDE",
                            reason="policy.condition.roles_excluded",
                        )
                    else:
                        audience_evaluation = replace(
                            audience_evaluation,
                            kind="ROLE_AUDIENCE_INCLUDE",
                            reason="policy.condition.roles_included",
                        )
                    conditions.append(audience_evaluation)
                    effect_outcome = self._and(effect_outcome, audience_evaluation.outcome)
                    if audience_evaluation.outcome is PolicyTruthValue.UNKNOWN:
                        incomplete.append(audience_evaluation.reason)
                contributions.append(
                    PolicyContribution(
                        policy.policy_id,
                        policy.revision,
                        effect_index,
                        policy.priority,
                        policy.scope_type,
                        policy.scope_id,
                        family,
                        specificity,
                        inherited,
                        context.requested_access,
                        str(effect["decision"]),
                        effect_outcome,
                        disposition=(
                            "CONDITION_FALSE"
                            if effect_outcome is PolicyTruthValue.FALSE
                            else "CONDITION_UNKNOWN"
                            if effect_outcome is PolicyTruthValue.UNKNOWN
                            else "CANDIDATE"
                        ),
                    )
                )

        ordered = sorted(contributions, key=self._contribution_order)
        known = tuple(
            contribution
            for contribution in ordered
            if contribution.condition_outcome is PolicyTruthValue.TRUE
        )
        uncertain = tuple(
            contribution
            for contribution in ordered
            if contribution.condition_outcome is PolicyTruthValue.UNKNOWN
        )
        maximal = self._maximal(known)
        maximal_decisions = {contribution.decision for contribution in maximal}

        outcome = self._known_outcome(maximal_decisions)
        if invalid_relevant_policy:
            outcome = PolicyResolutionOutcome.UNKNOWN
        elif self._uncertainty_can_change(known=maximal, uncertain=uncertain):
            outcome = PolicyResolutionOutcome.UNKNOWN

        if context.target_state in {PolicyTargetState.DELETED, PolicyTargetState.INACCESSIBLE}:
            outcome = PolicyResolutionOutcome.BLOCKED
            incomplete.append(f"policy.target_{context.target_state.value.lower()}")
            warnings.append("policy.reconcile_target_recommended")
        elif context.target_state in {PolicyTargetState.STALE, PolicyTargetState.UNKNOWN}:
            outcome = PolicyResolutionOutcome.UNKNOWN
            incomplete.append(f"policy.target_{context.target_state.value.lower()}")
            warnings.append("policy.targeted_refresh_recommended")

        selected_keys = {
            (item.policy_id, item.revision, item.effect_index)
            for item in maximal
            if outcome in {PolicyResolutionOutcome.CAN, PolicyResolutionOutcome.CANNOT}
        }
        unresolved_keys = {
            (item.policy_id, item.revision, item.effect_index)
            for item in maximal
            if len(maximal_decisions) > 1
        }
        finalized: list[PolicyContribution] = []
        for contribution in ordered:
            key = (contribution.policy_id, contribution.revision, contribution.effect_index)
            if key in selected_keys:
                finalized.append(replace(contribution, selected=True, disposition="SELECTED"))
            elif key in unresolved_keys:
                finalized.append(replace(contribution, disposition="CONFLICT_UNRESOLVED"))
            elif contribution in maximal and context.target_state in {
                PolicyTargetState.DELETED,
                PolicyTargetState.INACCESSIBLE,
            }:
                finalized.append(replace(contribution, disposition="TARGET_BLOCKED"))
            elif contribution in maximal and outcome is PolicyResolutionOutcome.UNKNOWN:
                finalized.append(replace(contribution, disposition="DATA_INCOMPLETE"))
            elif contribution.condition_outcome is PolicyTruthValue.TRUE:
                finalized.append(replace(contribution, disposition="OVERRIDDEN"))
            else:
                finalized.append(contribution)

        final_contributions = tuple(finalized)
        conflicts = self._conflicts(known, maximal)
        applicable = self._applicable(final_contributions)
        source_scopes = tuple(self._source_scope(item) for item in applicable)
        priority_trace = tuple(
            PolicyPriorityTraceEntry(
                item.policy_id,
                item.revision,
                item.effect_index,
                item.priority,
                item.family,
                item.specificity,
                position,
                item.disposition,
                self._trace_rule(item, maximal),
            )
            for position, item in enumerate(final_contributions, start=1)
        )
        if context.target_freshness is FreshnessState.AGING:
            warnings.append("policy.target_aging")
        if context.coverage is not CoverageMode.FULL:
            warnings.append(f"policy.coverage_{context.coverage.value.lower()}")
        if any("member_roles" in reason for reason in incomplete):
            warnings.append("policy.member_refresh_recommended")
        if outcome is PolicyResolutionOutcome.BLOCKED:
            warnings.append("policy.intervention_required")

        return PolicyResolution(
            guild_id=context.guild_id,
            subject_id=context.subject_id,
            decision=f"ACCESS_CONTROL:{context.requested_access}",
            outcome=outcome,
            target_scope_type=context.target_scope_type,
            target_scope_id=context.target_scope_id,
            target_state=context.target_state,
            target_freshness=context.target_freshness,
            coverage=context.coverage,
            applicable_policies=applicable,
            contributions=final_contributions,
            conflicts=conflicts,
            source_scopes=source_scopes,
            priority_trace=priority_trace,
            conditions=tuple(sorted(conditions, key=self._condition_order)),
            incomplete_reasons=tuple(sorted(set(incomplete))),
            warnings=tuple(sorted(set(warnings))),
            source_versions=tuple(sorted(set(context.source_versions))),
        )

    @staticmethod
    def _known_outcome(decisions: set[str]) -> PolicyResolutionOutcome:
        if not decisions:
            return PolicyResolutionOutcome.CANNOT
        if len(decisions) > 1:
            return PolicyResolutionOutcome.BLOCKED
        return (
            PolicyResolutionOutcome.CAN
            if decisions == {"ALLOW"}
            else PolicyResolutionOutcome.CANNOT
        )

    def _uncertainty_can_change(
        self,
        *,
        known: tuple[PolicyContribution, ...],
        uncertain: tuple[PolicyContribution, ...],
    ) -> bool:
        if not uncertain:
            return False
        possible_maximal = self._maximal(known + uncertain)
        possible_decisions = {item.decision for item in possible_maximal}
        known_decisions = {item.decision for item in known}
        return not known_decisions or possible_decisions != known_decisions

    def _conflicts(
        self,
        contributions: tuple[PolicyContribution, ...],
        maximal: tuple[PolicyContribution, ...],
    ) -> tuple[PolicyConflict, ...]:
        conflicts: list[PolicyConflict] = []
        maximal_keys = {self._contribution_key(item) for item in maximal}
        for index, left in enumerate(contributions):
            for right in contributions[index + 1 :]:
                if left.decision == right.decision:
                    continue
                comparison, rule = self._compare(left, right)
                if comparison is not None:
                    winners: tuple[UUID, ...] = (comparison.policy_id,)
                    conflict_outcome = PolicyConflictOutcome.RESOLVED
                elif {
                    self._contribution_key(left),
                    self._contribution_key(right),
                }.issubset(maximal_keys):
                    winners = ()
                    conflict_outcome = PolicyConflictOutcome.BLOCKED
                else:
                    winners = tuple(dict.fromkeys(item.policy_id for item in maximal))
                    rule = "DOMINANT_POLICY"
                    conflict_outcome = PolicyConflictOutcome.RESOLVED
                pair = tuple(sorted((left, right), key=self._contribution_order))
                conflicts.append(
                    PolicyConflict(
                        policy_ids=tuple(item.policy_id for item in pair),
                        revisions=tuple(item.revision for item in pair),
                        source_scopes=tuple(self._scope_label(item) for item in pair),
                        effects=tuple(f"{item.decision} {item.access}" for item in pair),
                        resolution_rule=rule,
                        outcome=conflict_outcome,
                        winning_policy_ids=winners,
                    )
                )
        return tuple(conflicts)

    def _maximal(
        self, contributions: tuple[PolicyContribution, ...]
    ) -> tuple[PolicyContribution, ...]:
        return tuple(
            item
            for item in contributions
            if not any(
                other is not item and self._compare(other, item)[0] is other
                for other in contributions
            )
        )

    def _compare(
        self, left: PolicyContribution, right: PolicyContribution
    ) -> tuple[PolicyContribution | None, str | None]:
        if left.priority != right.priority:
            return (
                (left, "HIGHER_PRIORITY")
                if left.priority > right.priority
                else (right, "HIGHER_PRIORITY")
            )
        if left.family is PolicyScopeFamily.UNIVERSAL and right.family is not left.family:
            return right, "MORE_SPECIFIC_SCOPE"
        if right.family is PolicyScopeFamily.UNIVERSAL and left.family is not right.family:
            return left, "MORE_SPECIFIC_SCOPE"
        if left.family is right.family and left.specificity != right.specificity:
            return (
                (left, "MORE_SPECIFIC_SCOPE")
                if left.specificity > right.specificity
                else (right, "MORE_SPECIFIC_SCOPE")
            )
        return None, None

    def _scope_matches(
        self, policy: Policy, context: PolicyResolutionContext
    ) -> tuple[PolicyTruthValue, str]:
        scope_id = policy.scope_id
        if policy.scope_type is PolicyScopeType.GUILD:
            return PolicyTruthValue.TRUE, "policy.scope.guild"
        if policy.scope_type is PolicyScopeType.LOGICAL_GROUP:
            matched = (
                context.target_scope_type is PolicyScopeType.LOGICAL_GROUP
                and context.target_scope_id == scope_id
            ) or scope_id in context.logical_group_ids
            return (
                (PolicyTruthValue.TRUE, "policy.scope.logical_group")
                if matched
                else (PolicyTruthValue.FALSE, "policy.scope.not_applicable")
            )
        if policy.scope_type is PolicyScopeType.CATEGORY:
            matched = (
                context.target_scope_type is PolicyScopeType.CATEGORY
                and context.target_scope_id == scope_id
            ) or context.category_id == scope_id
            return (
                (PolicyTruthValue.TRUE, "policy.scope.category")
                if matched
                else (PolicyTruthValue.FALSE, "policy.scope.not_applicable")
            )
        if policy.scope_type is PolicyScopeType.CHANNEL:
            matched = (
                context.target_scope_type is PolicyScopeType.CHANNEL
                and context.target_scope_id == scope_id
            )
            return (
                (PolicyTruthValue.TRUE, "policy.scope.channel")
                if matched
                else (PolicyTruthValue.FALSE, "policy.scope.not_applicable")
            )
        if policy.scope_type is PolicyScopeType.MEMBER:
            return (
                (PolicyTruthValue.TRUE, "policy.scope.member")
                if scope_id == str(context.subject_id)
                else (PolicyTruthValue.FALSE, "policy.scope.not_applicable")
            )
        if policy.scope_type is PolicyScopeType.BOT:
            if scope_id != str(context.subject_id):
                return PolicyTruthValue.FALSE, "policy.scope.not_applicable"
            if context.subject_is_bot is None:
                return PolicyTruthValue.UNKNOWN, "policy.subject_kind_unknown"
            return (
                (PolicyTruthValue.TRUE, "policy.scope.bot")
                if context.subject_is_bot
                else (PolicyTruthValue.FALSE, "policy.scope.not_applicable")
            )
        if policy.scope_type is PolicyScopeType.ROLE:
            if not context.subject_roles_complete or context.subject_freshness in {
                FreshnessState.STALE,
                FreshnessState.UNKNOWN,
            }:
                return PolicyTruthValue.UNKNOWN, "policy.member_roles_incomplete"
            if scope_id not in context.known_role_ids and context.roles_catalog_complete:
                return PolicyTruthValue.FALSE, f"policy.role_target_deleted:{scope_id}"
            return (
                (PolicyTruthValue.TRUE, "policy.scope.role")
                if scope_id in context.subject_role_ids
                else (PolicyTruthValue.FALSE, "policy.scope.not_applicable")
            )
        return PolicyTruthValue.FALSE, "policy.scope.unsupported"

    def _evaluate_condition(
        self,
        policy: Policy,
        index: int,
        condition: dict[str, object],
        context: PolicyResolutionContext,
    ) -> PolicyConditionEvaluation:
        kind = str(condition["kind"])
        if kind == "ALWAYS":
            outcome, reason = PolicyTruthValue.TRUE, "policy.condition.always"
        elif kind == "SUBJECT_KIND":
            if context.subject_is_bot is None:
                outcome, reason = PolicyTruthValue.UNKNOWN, "policy.subject_kind_unknown"
            else:
                actual = "BOT" if context.subject_is_bot else "MEMBER"
                outcome = (
                    PolicyTruthValue.TRUE
                    if condition["subject_kind"] == actual
                    else PolicyTruthValue.FALSE
                )
                reason = "policy.condition.subject_kind"
        else:
            raw_role_ids = condition["role_ids"]
            assert isinstance(raw_role_ids, list | tuple)
            role_ids = tuple(str(value) for value in raw_role_ids)
            missing_roles = tuple(
                role_id for role_id in role_ids if role_id not in context.known_role_ids
            )
            if not context.roles_catalog_complete:
                outcome, reason = PolicyTruthValue.UNKNOWN, "policy.roles_catalog_incomplete"
            elif missing_roles:
                outcome = PolicyTruthValue.UNKNOWN
                reason = f"policy.role_reference_deleted:{','.join(missing_roles)}"
            elif not context.subject_roles_complete:
                outcome, reason = PolicyTruthValue.UNKNOWN, "policy.member_roles_incomplete"
            elif context.subject_freshness in {FreshnessState.STALE, FreshnessState.UNKNOWN}:
                outcome, reason = PolicyTruthValue.UNKNOWN, "policy.member_roles_not_current"
            else:
                member_roles = set(context.subject_role_ids)
                configured_roles = set(role_ids)
                matched = (
                    bool(member_roles.intersection(configured_roles))
                    if condition["match"] == "ANY"
                    else configured_roles.issubset(member_roles)
                )
                outcome = PolicyTruthValue.TRUE if matched else PolicyTruthValue.FALSE
                reason = f"policy.condition.roles_{str(condition['match']).lower()}"
        return PolicyConditionEvaluation(
            policy.policy_id,
            policy.revision,
            index,
            kind,
            outcome,
            reason,
        )

    @staticmethod
    def _and(left: PolicyTruthValue, right: PolicyTruthValue) -> PolicyTruthValue:
        if PolicyTruthValue.FALSE in {left, right}:
            return PolicyTruthValue.FALSE
        if PolicyTruthValue.UNKNOWN in {left, right}:
            return PolicyTruthValue.UNKNOWN
        return PolicyTruthValue.TRUE

    @staticmethod
    def _specificity(scope_type: PolicyScopeType) -> tuple[PolicyScopeFamily, int]:
        if scope_type is PolicyScopeType.GUILD:
            return PolicyScopeFamily.UNIVERSAL, 0
        if scope_type in _RESOURCE_SPECIFICITY:
            return PolicyScopeFamily.RESOURCE, _RESOURCE_SPECIFICITY[scope_type]
        if scope_type in _SUBJECT_SPECIFICITY:
            return PolicyScopeFamily.SUBJECT, _SUBJECT_SPECIFICITY[scope_type]
        return PolicyScopeFamily.INCOMPARABLE, 0

    @staticmethod
    def _is_inherited(policy: Policy, context: PolicyResolutionContext) -> bool:
        if policy.scope_type is PolicyScopeType.GUILD:
            return context.target_scope_type is not PolicyScopeType.GUILD
        if policy.scope_type is PolicyScopeType.LOGICAL_GROUP:
            return context.target_scope_type is not PolicyScopeType.LOGICAL_GROUP
        if policy.scope_type is PolicyScopeType.CATEGORY:
            return context.target_scope_type is PolicyScopeType.CHANNEL
        return False

    @staticmethod
    def _policy_order(policy: Policy) -> tuple[object, ...]:
        family, specificity = PolicyResolver._specificity(policy.scope_type)
        return (
            -policy.priority,
            -specificity,
            family.value,
            policy.scope_type.value,
            policy.scope_id or "",
            str(policy.policy_id),
            policy.revision,
        )

    @staticmethod
    def _contribution_order(item: PolicyContribution) -> tuple[object, ...]:
        return (
            -item.priority,
            -item.specificity,
            item.family.value,
            item.scope_type.value,
            item.scope_id or "",
            str(item.policy_id),
            item.revision,
            item.effect_index,
        )

    @staticmethod
    def _condition_order(item: PolicyConditionEvaluation) -> tuple[object, ...]:
        return str(item.policy_id), item.revision, item.condition_index

    @staticmethod
    def _contribution_key(item: PolicyContribution) -> tuple[UUID, int, int]:
        return item.policy_id, item.revision, item.effect_index

    @staticmethod
    def _scope_label(item: PolicyContribution) -> str:
        return f"{item.scope_type.value}:{item.scope_id or '*'}"

    def _applicable(
        self, contributions: tuple[PolicyContribution, ...]
    ) -> tuple[ApplicablePolicy, ...]:
        values: list[ApplicablePolicy] = []
        seen: set[tuple[UUID, int]] = set()
        for item in contributions:
            identity = (item.policy_id, item.revision)
            if item.condition_outcome is not PolicyTruthValue.TRUE or identity in seen:
                continue
            seen.add(identity)
            values.append(
                ApplicablePolicy(
                    item.policy_id,
                    item.revision,
                    item.priority,
                    item.scope_type,
                    item.scope_id,
                    item.inherited,
                    item.specificity,
                )
            )
        return tuple(values)

    @staticmethod
    def _source_scope(item: ApplicablePolicy) -> PolicySourceScope:
        family, specificity = PolicyResolver._specificity(item.scope_type)
        return PolicySourceScope(
            item.policy_id,
            item.revision,
            item.scope_type,
            item.scope_id,
            family,
            specificity,
            item.inherited,
        )

    def _trace_rule(
        self,
        item: PolicyContribution,
        maximal: tuple[PolicyContribution, ...],
    ) -> str | None:
        if item in maximal:
            return "MAXIMAL_PRECEDENCE"
        dominators = [
            (other, rule)
            for other in maximal
            for winner, rule in (self._compare(other, item),)
            if winner is other
        ]
        if not dominators:
            return None
        return dominators[0][1]


__all__ = [
    "ApplicablePolicy",
    "PolicyConditionEvaluation",
    "PolicyConflict",
    "PolicyConflictOutcome",
    "PolicyContribution",
    "PolicyPriorityTraceEntry",
    "PolicyResolution",
    "PolicyResolutionContext",
    "PolicyResolutionOutcome",
    "PolicyResolver",
    "PolicyScopeFamily",
    "PolicySourceScope",
    "PolicyTargetState",
    "PolicyTruthValue",
]
