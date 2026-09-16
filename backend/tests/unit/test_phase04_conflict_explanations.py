from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from did.domain.discord_runtime import CoverageMode, FreshnessState
from did.domain.policies import Policy, PolicyLifecycleState, PolicyScopeType
from did.policies.conflict_explanations import explain_conflicts, find_blacklist_regrants
from did.policies.resolver import PolicyResolutionContext, PolicyResolver, PolicyTargetState

GUILD_ID = 100
SUBJECT_ID = 101
CHANNEL_ID = "300"
CONTRACTORS = "500"
MANAGERS = "600"


def _policy(number: int, *, effects: tuple[dict[str, object], ...], priority: int = 0) -> Policy:
    return Policy(
        policy_id=UUID(int=number),
        guild_id=GUILD_ID,
        policy_type="ACCESS_CONTROL",
        contract_version=1,
        name=f"Policy {number}",
        description="",
        lifecycle_state=PolicyLifecycleState.ACTIVE,
        revision=1,
        scope_type=PolicyScopeType.GUILD,
        scope_id=None,
        conditions=({"kind": "ALWAYS"},),
        effects=effects,
        metadata={"summary": f"Policy {number}", "tags": ()},
        created_by_user_id=SUBJECT_ID,
        modified_by_user_id=SUBJECT_ID,
        priority=priority,
    )


def _context(subject_role_ids: tuple[str, ...]) -> PolicyResolutionContext:
    return PolicyResolutionContext(
        guild_id=GUILD_ID,
        requested_access="VIEW",
        target_scope_type=PolicyScopeType.CHANNEL,
        target_scope_id=CHANNEL_ID,
        target_state=PolicyTargetState.CURRENT,
        target_freshness=FreshnessState.FRESH,
        coverage=CoverageMode.FULL,
        subject_id=SUBJECT_ID,
        subject_role_ids=subject_role_ids,
        subject_roles_complete=True,
        subject_freshness=FreshnessState.FRESH,
        subject_is_bot=False,
        known_role_ids=(CONTRACTORS, MANAGERS),
        roles_catalog_complete=True,
    )


def _visible_except_contractors() -> Policy:
    return _policy(
        1,
        effects=(
            {
                "kind": "SET_ACCESS",
                "access": "VIEW",
                "decision": "ALLOW",
                "audience": {"mode": "EXCLUDE", "match": "ANY", "role_ids": [CONTRACTORS]},
            },
        ),
    )


def _managers_always_see() -> Policy:
    return _policy(
        2,
        effects=(
            {
                "kind": "SET_ACCESS",
                "access": "VIEW",
                "decision": "ALLOW",
                "audience": {"mode": "INCLUDE", "match": "ANY", "role_ids": [MANAGERS]},
            },
        ),
    )


def test_blacklist_bypass_is_explained_with_the_exact_regranting_role() -> None:
    blacklist = _visible_except_contractors()
    regrant = _managers_always_see()
    policies = (blacklist, regrant)
    resolution = PolicyResolver().resolve(
        policies=policies, context=_context((CONTRACTORS, MANAGERS))
    )

    explanations = find_blacklist_regrants(
        resolution,
        policies_by_id={p.policy_id: p for p in policies},
        member_role_ids=(CONTRACTORS, MANAGERS),
    )

    assert len(explanations) == 1
    explanation = explanations[0]
    assert explanation.excluding_policy_id == blacklist.policy_id
    assert explanation.excluding_role_ids == (CONTRACTORS,)
    assert explanation.regranting_policy_id == regrant.policy_id
    assert {cause.role_id for cause in explanation.regranting_role_ids} == {MANAGERS}
    assert explanation.reason_key == "policy.conflict.blacklist_bypassed_by_role"
    assert explanation.accepted is False


def test_blacklist_correctly_denies_a_contractor_without_a_regrant() -> None:
    blacklist = _visible_except_contractors()
    policies = (blacklist,)
    resolution = PolicyResolver().resolve(policies=policies, context=_context((CONTRACTORS,)))

    explanations = find_blacklist_regrants(
        resolution,
        policies_by_id={p.policy_id: p for p in policies},
        member_role_ids=(CONTRACTORS,),
    )

    assert resolution.outcome.value == "CANNOT"
    assert explanations == ()


def test_non_excluded_member_produces_no_explanation() -> None:
    blacklist = _visible_except_contractors()
    regrant = _managers_always_see()
    policies = (blacklist, regrant)
    resolution = PolicyResolver().resolve(policies=policies, context=_context((MANAGERS,)))

    explanations = find_blacklist_regrants(
        resolution,
        policies_by_id={p.policy_id: p for p in policies},
        member_role_ids=(MANAGERS,),
    )

    assert resolution.outcome.value == "CAN"
    assert explanations == ()


def test_explain_conflicts_attributes_the_winning_role_for_a_real_conflict() -> None:
    manager_allow = _policy(
        1,
        priority=2,
        effects=({"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"},),
    )
    manager_allow = replace(
        manager_allow,
        conditions=({"kind": "ROLE_MATCH", "match": "ANY", "role_ids": [MANAGERS]},),
    )
    blanket_deny = _policy(
        2, effects=({"kind": "SET_ACCESS", "access": "VIEW", "decision": "DENY"},)
    )
    policies = (manager_allow, blanket_deny)
    resolution = PolicyResolver().resolve(policies=policies, context=_context((MANAGERS,)))

    explanations = explain_conflicts(
        resolution,
        policies_by_id={p.policy_id: p for p in policies},
        member_role_ids=(MANAGERS,),
    )

    assert len(explanations) == 1
    explanation = explanations[0]
    assert explanation.reason_key == "policy.conflict.role_regrants_access"
    assert {cause.role_id for cause in explanation.causing_roles} == {MANAGERS}
    assert explanation.accepted is False


def test_accepted_exception_tag_marks_the_bypass_as_intentional() -> None:
    blacklist = _visible_except_contractors()
    regrant = _managers_always_see()
    annotated_blacklist = replace(
        blacklist,
        metadata={
            **blacklist.metadata,
            "tags": (f"exception_accepted:{regrant.policy_id}",),
        },
    )
    policies = (annotated_blacklist, regrant)
    resolution = PolicyResolver().resolve(
        policies=policies, context=_context((CONTRACTORS, MANAGERS))
    )

    explanations = find_blacklist_regrants(
        resolution,
        policies_by_id={p.policy_id: p for p in policies},
        member_role_ids=(CONTRACTORS, MANAGERS),
    )

    assert len(explanations) == 1
    assert explanations[0].accepted is True
    assert explanations[0].reason_key == "policy.conflict.exception_accepted"
