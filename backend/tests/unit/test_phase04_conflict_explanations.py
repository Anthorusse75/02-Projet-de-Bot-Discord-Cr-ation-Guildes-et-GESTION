from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
from did.domain.policies import Policy, PolicyLifecycleState, PolicyScopeType
from did.domain.read_model import (
    ChannelSnapshot,
    CoverageSnapshot,
    FreshnessSnapshot,
    GuildSnapshot,
    MemberSnapshot,
    OverwriteSnapshot,
    RoleSnapshot,
)
from did.domain.read_model.models import ChannelType
from did.permissions import DEFAULT_PERMISSION_REGISTRY, PermissionEvaluator
from did.policies.conflict_explanations import (
    explain_conflicts,
    explain_observable_access_conflict,
    find_blacklist_regrants,
)
from did.policies.resolver import (
    PolicyResolution,
    PolicyResolutionContext,
    PolicyResolver,
    PolicyTargetState,
)

GUILD_ID = 100
SUBJECT_ID = 101
CHANNEL_ID = "300"
CONTRACTORS = "500"
MANAGERS = "600"
NOW = datetime(2026, 9, 18, tzinfo=UTC)
VIEW = DEFAULT_PERMISSION_REGISTRY.value("VIEW_CHANNEL")
ADMINISTRATOR = DEFAULT_PERMISSION_REGISTRY.value("ADMINISTRATOR")


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


def _observable_facts(
    *,
    role_permissions: int = 0,
    member_overwrite_allow: int = 0,
    inherited: bool = False,
) -> tuple[GuildSnapshot, MemberSnapshot, ChannelSnapshot]:
    fresh = FreshnessSnapshot(FreshnessState.FRESH, "CACHE", 1, NOW, NOW, NOW)
    coverage = CoverageSnapshot(
        GUILD_ID,
        CoverageMode.FULL,
        FreshnessState.FRESH,
        "CACHE",
        1,
        known_channels=2 if inherited else 1,
        visible_channels=2 if inherited else 1,
        known_roles=2,
        members_complete=True,
        overwrites_complete=True,
    )
    parent_id = 299 if inherited else None
    overwrites = (
        (OverwriteSnapshot(GUILD_ID, int(CHANNEL_ID), SUBJECT_ID, 1, member_overwrite_allow, 0),)
        if member_overwrite_allow
        else ()
    )
    channel = ChannelSnapshot(
        GUILD_ID,
        int(CHANNEL_ID),
        ChannelType.GUILD_TEXT,
        1,
        parent_id,
        "board",
        overwrites,
        True,
        ObservabilityState.VISIBLE,
        fresh,
    )
    channels = (channel,)
    if inherited:
        parent_overwrites = tuple(
            replace(value, channel_id=parent_id) for value in overwrites if parent_id is not None
        )
        parent = ChannelSnapshot(
            GUILD_ID,
            parent_id,
            ChannelType.GUILD_CATEGORY,
            0,
            None,
            "parent",
            parent_overwrites,
            True,
            ObservabilityState.VISIBLE,
            fresh,
        )
        channels = (parent, channel)
    guild = GuildSnapshot(
        GUILD_ID,
        999,
        (
            RoleSnapshot(GUILD_ID, GUILD_ID, "@everyone", 0, 0, False, fresh),
            RoleSnapshot(
                GUILD_ID, int(MANAGERS), "Managers", 1, role_permissions, False, fresh
            ),
        ),
        channels,
        coverage,
        fresh,
    )
    member = MemberSnapshot(GUILD_ID, SUBJECT_ID, (int(MANAGERS),), True, fresh)
    return guild, member, channel


def _deny_resolution() -> tuple[Policy, PolicyResolution]:
    deny = _policy(
        20,
        effects=({"kind": "SET_ACCESS", "access": "VIEW", "decision": "DENY"},),
    )
    resolution = PolicyResolver().resolve(
        policies=(deny,), context=_context((MANAGERS,))
    )
    return deny, resolution


def test_observable_conflict_attributes_administrator_and_role_removal_collateral() -> None:
    deny, resolution = _deny_resolution()
    guild, member, channel = _observable_facts(role_permissions=ADMINISTRATOR)
    decision = PermissionEvaluator().evaluate(guild=guild, member=member, resource=channel)

    conflict = explain_observable_access_conflict(
        resolution, guild=guild, member=member, channel=channel, permission_decision=decision
    )

    assert conflict is not None and conflict.policy_ids == (deny.policy_id,)
    assert conflict.actual_outcome == "ALLOWED"
    assert conflict.granting_causes[0].kind == "ADMINISTRATOR"
    removal = next(item for item in conflict.remediations if item.kind == "REMOVE_MEMBER_ROLE")
    assert removal.requires_separate_plan is True
    assert "ADMINISTRATOR" in removal.collateral_losses


def test_observable_conflict_attributes_raw_member_overwrite_and_category_inheritance() -> None:
    _deny, resolution = _deny_resolution()
    guild, member, channel = _observable_facts(
        member_overwrite_allow=VIEW,
        inherited=True,
    )
    decision = PermissionEvaluator().evaluate(guild=guild, member=member, resource=channel)

    conflict = explain_observable_access_conflict(
        resolution, guild=guild, member=member, channel=channel, permission_decision=decision
    )

    assert conflict is not None
    cause = conflict.granting_causes[0]
    assert cause.kind == "MEMBER_OVERWRITE"
    assert cause.inherited_from_category_id == "299"
    remediation = conflict.remediations[0]
    assert remediation.kind == "EDIT_MEMBER_OVERWRITE"
    assert remediation.target_id == "299"
    assert remediation.collateral_losses == ("VIEW_CHANNEL",)


def test_two_contradictory_roles_on_one_member_name_both_role_causes() -> None:
    manager_allow = replace(
        _policy(30, effects=({"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"},)),
        conditions=({"kind": "ROLE_MATCH", "match": "ANY", "role_ids": [MANAGERS]},),
    )
    contractor_deny = replace(
        _policy(31, effects=({"kind": "SET_ACCESS", "access": "VIEW", "decision": "DENY"},)),
        conditions=({"kind": "ROLE_MATCH", "match": "ANY", "role_ids": [CONTRACTORS]},),
    )
    policies = (manager_allow, contractor_deny)
    resolution = PolicyResolver().resolve(
        policies=policies, context=_context((MANAGERS, CONTRACTORS))
    )
    guild, member, _channel = _observable_facts(
        role_permissions=DEFAULT_PERMISSION_REGISTRY.value("MANAGE_CHANNELS")
    )
    guild = replace(
        guild,
        roles=(
            *guild.roles,
            RoleSnapshot(
                GUILD_ID,
                int(CONTRACTORS),
                "Contractors",
                2,
                DEFAULT_PERMISSION_REGISTRY.value("SEND_MESSAGES"),
                False,
                guild.freshness,
            ),
        ),
        coverage=replace(guild.coverage, known_roles=3),
    )
    member = replace(member, role_ids=(int(MANAGERS), int(CONTRACTORS)))

    explanations = explain_conflicts(
        resolution,
        policies_by_id={policy.policy_id: policy for policy in policies},
        member_role_ids=(MANAGERS, CONTRACTORS),
        guild=guild,
        member=member,
    )

    assert resolution.outcome.value == "BLOCKED"
    assert {cause.role_id for cause in explanations[0].causing_roles} == {
        MANAGERS,
        CONTRACTORS,
    }
    role_removals = tuple(
        item for item in explanations[0].remediations if item.kind == "REMOVE_MEMBER_ROLE"
    )
    assert {item.target_id for item in role_removals} == {MANAGERS, CONTRACTORS}
    assert {item.collateral_losses for item in role_removals} == {
        ("MANAGE_CHANNELS",),
        ("SEND_MESSAGES",),
    }
    assert all(item.requires_separate_plan for item in explanations[0].remediations)
