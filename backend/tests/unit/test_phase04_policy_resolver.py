from __future__ import annotations

from itertools import permutations
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from did.application.policies.service import PolicyService
from did.domain.discord_runtime import CoverageMode, FreshnessState
from did.domain.policies import Policy, PolicyLifecycleState, PolicyScopeType
from did.policies.resolver import (
    PolicyConflictOutcome,
    PolicyResolutionContext,
    PolicyResolutionOutcome,
    PolicyResolver,
    PolicyTargetState,
    PolicyTruthValue,
)

GUILD_ID = 100
SUBJECT_ID = 101
GROUP_ID = "00000000-0000-0000-0000-000000000111"
CATEGORY_ID = "200"
CHANNEL_ID = "300"


def _policy(
    number: int,
    *,
    scope_type: PolicyScopeType = PolicyScopeType.GUILD,
    scope_id: str | None = None,
    decision: str = "ALLOW",
    priority: int = 0,
    conditions: tuple[dict[str, object], ...] = ({"kind": "ALWAYS"},),
    effects: tuple[dict[str, object], ...] | None = None,
) -> Policy:
    return Policy(
        policy_id=UUID(int=number),
        guild_id=GUILD_ID,
        policy_type="ACCESS_CONTROL",
        contract_version=1,
        name=f"Policy {number}",
        description="",
        lifecycle_state=PolicyLifecycleState.ACTIVE,
        revision=number,
        scope_type=scope_type,
        scope_id=scope_id,
        conditions=conditions,
        effects=effects or ({"kind": "SET_ACCESS", "access": "VIEW", "decision": decision},),
        metadata={"summary": f"Policy {number}"},
        created_by_user_id=SUBJECT_ID,
        modified_by_user_id=SUBJECT_ID,
        priority=priority,
    )


def _context(**overrides: object) -> PolicyResolutionContext:
    values: dict[str, object] = {
        "guild_id": GUILD_ID,
        "requested_access": "VIEW",
        "target_scope_type": PolicyScopeType.CHANNEL,
        "target_scope_id": CHANNEL_ID,
        "target_state": PolicyTargetState.CURRENT,
        "target_freshness": FreshnessState.FRESH,
        "coverage": CoverageMode.FULL,
        "subject_id": SUBJECT_ID,
        "subject_role_ids": ("10", "20"),
        "subject_roles_complete": True,
        "subject_freshness": FreshnessState.FRESH,
        "subject_is_bot": False,
        "category_id": CATEGORY_ID,
        "logical_group_ids": (GROUP_ID,),
        "known_role_ids": ("10", "20", "30"),
        "roles_catalog_complete": True,
        "source_versions": ("guild:2", "coverage:4"),
    }
    values.update(overrides)
    return PolicyResolutionContext(**values)  # type: ignore[arg-type]


def test_resolution_is_identical_for_every_input_order() -> None:
    resolver = PolicyResolver()
    policies = (
        _policy(1, decision="DENY", priority=1),
        _policy(
            2,
            scope_type=PolicyScopeType.CATEGORY,
            scope_id=CATEGORY_ID,
            decision="ALLOW",
            priority=1,
        ),
        _policy(3, decision="ALLOW", priority=-1),
    )

    results = [
        resolver.resolve(policies=tuple(order), context=_context())
        for order in permutations(policies)
    ]

    assert all(result == results[0] for result in results)
    assert results[0].outcome is PolicyResolutionOutcome.CAN
    assert [item.policy_id for item in results[0].applicable_policies] == [
        UUID(int=2),
        UUID(int=1),
        UUID(int=3),
    ]


def test_effect_audiences_support_whitelist_blacklist_and_separate_read_write() -> None:
    resolver = PolicyResolver()
    policy = _policy(
        10,
        effects=(
            {"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"},
            {
                "kind": "SET_ACCESS",
                "access": "WRITE",
                "decision": "ALLOW",
                "audience": {"mode": "INCLUDE", "match": "ANY", "role_ids": ["10"]},
            },
        ),
    )
    excluded = _policy(
        11,
        priority=1,
        effects=(
            {
                "kind": "SET_ACCESS",
                "access": "VIEW",
                "decision": "ALLOW",
                "audience": {"mode": "EXCLUDE", "match": "ANY", "role_ids": ["30"]},
            },
        ),
    )

    assert (
        resolver.resolve(policies=(policy,), context=_context()).outcome
        is PolicyResolutionOutcome.CAN
    )
    assert (
        resolver.resolve(policies=(policy,), context=_context(requested_access="WRITE")).outcome
        is PolicyResolutionOutcome.CAN
    )
    assert (
        resolver.resolve(
            policies=(policy,),
            context=_context(requested_access="WRITE", subject_role_ids=("20",)),
        ).outcome
        is PolicyResolutionOutcome.CANNOT
    )
    assert (
        resolver.resolve(policies=(excluded,), context=_context(subject_role_ids=("10",))).outcome
        is PolicyResolutionOutcome.CAN
    )
    assert (
        resolver.resolve(
            policies=(excluded,), context=_context(subject_role_ids=("10", "30"))
        ).outcome
        is PolicyResolutionOutcome.CANNOT
    )


@pytest.mark.asyncio
async def test_application_service_uses_cache_first_context_and_canonical_resolver() -> None:
    policy = _policy(1)
    repository = SimpleNamespace(list=AsyncMock(return_value=(policy,)))
    freshness = SimpleNamespace(state=FreshnessState.FRESH)
    guild = SimpleNamespace(
        guild_id=GUILD_ID,
        freshness=freshness,
        coverage=SimpleNamespace(mode=CoverageMode.FULL, freshness=FreshnessState.FRESH),
        roles=(),
        roles_complete=True,
        source_versions=("guild:1",),
    )
    member = SimpleNamespace(
        role_ids=(),
        roles_complete=True,
        freshness=freshness,
        is_bot=False,
    )
    read_models = SimpleNamespace(
        guild_snapshot=AsyncMock(return_value=(guild, member)),
        list_logical_groups=AsyncMock(return_value=[]),
    )
    service = PolicyService(repository, read_models=read_models)  # type: ignore[arg-type]

    result = await service.resolve_access(
        guild_id=GUILD_ID,
        subject_id=SUBJECT_ID,
        target_scope_type=PolicyScopeType.GUILD,
        target_scope_id=None,
        requested_access="VIEW",
    )

    assert result.outcome is PolicyResolutionOutcome.CAN
    repository.list.assert_awaited_once_with(GUILD_ID)
    read_models.guild_snapshot.assert_awaited_once_with(GUILD_ID, SUBJECT_ID)


def test_explicit_priority_dominates_scope_specificity() -> None:
    result = PolicyResolver().resolve(
        policies=(
            _policy(1, decision="DENY", priority=20),
            _policy(
                2,
                scope_type=PolicyScopeType.CHANNEL,
                scope_id=CHANNEL_ID,
                decision="ALLOW",
                priority=10,
            ),
        ),
        context=_context(),
    )

    assert result.outcome is PolicyResolutionOutcome.CANNOT
    assert result.conflicts[0].resolution_rule == "HIGHER_PRIORITY"
    assert result.conflicts[0].winning_policy_ids == (UUID(int=1),)


@pytest.mark.parametrize(
    ("scope_type", "scope_id"),
    [
        (PolicyScopeType.LOGICAL_GROUP, GROUP_ID),
        (PolicyScopeType.CATEGORY, CATEGORY_ID),
        (PolicyScopeType.CHANNEL, CHANNEL_ID),
    ],
)
def test_resource_specificity_overrides_guild_at_equal_priority(
    scope_type: PolicyScopeType, scope_id: str
) -> None:
    result = PolicyResolver().resolve(
        policies=(
            _policy(1, decision="DENY"),
            _policy(2, scope_type=scope_type, scope_id=scope_id, decision="ALLOW"),
        ),
        context=_context(),
    )

    assert result.outcome is PolicyResolutionOutcome.CAN
    assert result.conflicts[0].resolution_rule == "MORE_SPECIFIC_SCOPE"


def test_guild_group_category_channel_inheritance_keeps_every_source() -> None:
    policies = (
        _policy(1),
        _policy(2, scope_type=PolicyScopeType.LOGICAL_GROUP, scope_id=GROUP_ID),
        _policy(3, scope_type=PolicyScopeType.CATEGORY, scope_id=CATEGORY_ID),
        _policy(4, scope_type=PolicyScopeType.CHANNEL, scope_id=CHANNEL_ID),
    )

    result = PolicyResolver().resolve(policies=policies, context=_context())

    assert result.outcome is PolicyResolutionOutcome.CAN
    assert [item.scope_type for item in result.applicable_policies] == [
        PolicyScopeType.CHANNEL,
        PolicyScopeType.CATEGORY,
        PolicyScopeType.LOGICAL_GROUP,
        PolicyScopeType.GUILD,
    ]
    assert [item.inherited for item in result.applicable_policies] == [False, True, True, True]
    assert len(result.contributions) == 4


def test_local_exception_wins_but_inherited_history_remains_visible() -> None:
    result = PolicyResolver().resolve(
        policies=(
            _policy(
                1,
                scope_type=PolicyScopeType.CATEGORY,
                scope_id=CATEGORY_ID,
                decision="DENY",
            ),
            _policy(
                2,
                scope_type=PolicyScopeType.CHANNEL,
                scope_id=CHANNEL_ID,
                decision="ALLOW",
            ),
        ),
        context=_context(),
    )

    assert result.outcome is PolicyResolutionOutcome.CAN
    assert [(item.policy_id, item.disposition) for item in result.contributions] == [
        (UUID(int=2), "SELECTED"),
        (UUID(int=1), "OVERRIDDEN"),
    ]
    assert result.source_scopes[1].inherited is True


def test_resolvable_conflict_reports_both_effects_and_rule() -> None:
    result = PolicyResolver().resolve(
        policies=(_policy(1, decision="ALLOW", priority=2), _policy(2, decision="DENY")),
        context=_context(),
    )

    assert result.outcome is PolicyResolutionOutcome.CAN
    assert result.conflicts[0].resolution_rule == "HIGHER_PRIORITY"
    assert result.conflicts[0].outcome is PolicyConflictOutcome.RESOLVED
    assert result.conflicts[0].winning_policy_ids == (UUID(int=1),)
    assert set(result.conflicts[0].effects) == {"ALLOW VIEW", "DENY VIEW"}


def test_unresolvable_equal_rank_conflict_blocks() -> None:
    result = PolicyResolver().resolve(
        policies=(
            _policy(1, scope_type=PolicyScopeType.CHANNEL, scope_id=CHANNEL_ID),
            _policy(
                2,
                scope_type=PolicyScopeType.CHANNEL,
                scope_id=CHANNEL_ID,
                decision="DENY",
            ),
        ),
        context=_context(),
    )

    assert result.outcome is PolicyResolutionOutcome.BLOCKED
    assert result.conflicts[0].outcome is PolicyConflictOutcome.BLOCKED
    assert result.conflicts[0].resolution_rule is None
    assert all(item.disposition == "CONFLICT_UNRESOLVED" for item in result.contributions)
    assert "policy.intervention_required" in result.warnings


def test_compatible_policies_compose_without_losing_contributions() -> None:
    result = PolicyResolver().resolve(
        policies=(_policy(1), _policy(2)),
        context=_context(),
    )

    assert result.outcome is PolicyResolutionOutcome.CAN
    assert len(result.applicable_policies) == 2
    assert len(result.contributions) == 2
    assert all(item.selected for item in result.contributions)
    assert result.conflicts == ()


@pytest.mark.parametrize(
    ("member_roles", "expected"),
    [
        ((), PolicyResolutionOutcome.CANNOT),
        (("10",), PolicyResolutionOutcome.CAN),
        (("10", "20"), PolicyResolutionOutcome.CAN),
    ],
)
def test_any_role_condition_uses_the_members_full_role_set(
    member_roles: tuple[str, ...], expected: PolicyResolutionOutcome
) -> None:
    policy = _policy(
        1,
        conditions=({"kind": "ROLE_MATCH", "match": "ANY", "role_ids": ["10", "30"]},),
    )

    result = PolicyResolver().resolve(
        policies=(policy,), context=_context(subject_role_ids=member_roles)
    )

    assert result.outcome is expected


@pytest.mark.parametrize(
    ("member_roles", "expected"),
    [
        (("10",), PolicyResolutionOutcome.CANNOT),
        (("10", "20"), PolicyResolutionOutcome.CAN),
        (("10", "20", "30"), PolicyResolutionOutcome.CAN),
    ],
)
def test_all_role_condition_requires_every_configured_role(
    member_roles: tuple[str, ...], expected: PolicyResolutionOutcome
) -> None:
    policy = _policy(
        1,
        conditions=({"kind": "ROLE_MATCH", "match": "ALL", "role_ids": ["10", "20"]},),
    )

    result = PolicyResolver().resolve(
        policies=(policy,), context=_context(subject_role_ids=member_roles)
    )

    assert result.outcome is expected


def test_incomplete_critical_member_data_fails_closed_as_unknown() -> None:
    policy = _policy(
        1,
        conditions=({"kind": "ROLE_MATCH", "match": "ANY", "role_ids": ["10"]},),
    )

    result = PolicyResolver().resolve(
        policies=(policy,),
        context=_context(
            subject_roles_complete=False,
            subject_freshness=FreshnessState.UNKNOWN,
        ),
    )

    assert result.outcome is PolicyResolutionOutcome.UNKNOWN
    assert "policy.member_roles_incomplete" in result.incomplete_reasons
    assert result.conditions[0].outcome is PolicyTruthValue.UNKNOWN


def test_lower_priority_unknown_condition_cannot_change_a_known_winner() -> None:
    uncertain_deny = _policy(
        2,
        decision="DENY",
        conditions=({"kind": "ROLE_MATCH", "match": "ANY", "role_ids": ["10"]},),
    )
    result = PolicyResolver().resolve(
        policies=(_policy(1, priority=1), uncertain_deny),
        context=_context(
            subject_roles_complete=False,
            subject_freshness=FreshnessState.UNKNOWN,
        ),
    )

    assert result.outcome is PolicyResolutionOutcome.CAN
    assert result.contributions[0].selected is True
    assert result.contributions[1].disposition == "CONDITION_UNKNOWN"


def test_stale_target_is_unknown_with_targeted_refresh_diagnostic() -> None:
    result = PolicyResolver().resolve(
        policies=(_policy(1),),
        context=_context(
            target_state=PolicyTargetState.STALE,
            target_freshness=FreshnessState.STALE,
        ),
    )

    assert result.outcome is PolicyResolutionOutcome.UNKNOWN
    assert result.target_state is PolicyTargetState.STALE
    assert "policy.target_stale" in result.incomplete_reasons
    assert "policy.targeted_refresh_recommended" in result.warnings


@pytest.mark.parametrize(
    "target_state", [PolicyTargetState.DELETED, PolicyTargetState.INACCESSIBLE]
)
def test_deleted_or_inaccessible_target_blocks_explicitly(
    target_state: PolicyTargetState,
) -> None:
    result = PolicyResolver().resolve(
        policies=(_policy(1),),
        context=_context(target_state=target_state),
    )

    assert result.outcome is PolicyResolutionOutcome.BLOCKED
    assert f"policy.target_{target_state.value.lower()}" in result.incomplete_reasons
    assert result.contributions[0].disposition == "TARGET_BLOCKED"


@pytest.mark.parametrize(
    ("left", "right", "expected", "rule"),
    [
        (
            _policy(11, decision="ALLOW", priority=2),
            _policy(12, decision="DENY", priority=1),
            PolicyResolutionOutcome.CAN,
            "HIGHER_PRIORITY",
        ),
        (
            _policy(13, decision="DENY"),
            _policy(14, scope_type=PolicyScopeType.CHANNEL, scope_id=CHANNEL_ID),
            PolicyResolutionOutcome.CAN,
            "MORE_SPECIFIC_SCOPE",
        ),
        (
            _policy(15),
            _policy(16, decision="DENY"),
            PolicyResolutionOutcome.BLOCKED,
            None,
        ),
        (
            _policy(17, scope_type=PolicyScopeType.ROLE, scope_id="10"),
            _policy(
                18,
                scope_type=PolicyScopeType.CHANNEL,
                scope_id=CHANNEL_ID,
                decision="DENY",
            ),
            PolicyResolutionOutcome.BLOCKED,
            None,
        ),
    ],
)
def test_compact_conflict_matrix(
    left: Policy,
    right: Policy,
    expected: PolicyResolutionOutcome,
    rule: str | None,
) -> None:
    result = PolicyResolver().resolve(policies=(right, left), context=_context())

    assert result.outcome is expected
    assert result.conflicts[0].resolution_rule == rule
