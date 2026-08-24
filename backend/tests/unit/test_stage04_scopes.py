from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from did.domain.discord_runtime import FreshnessState
from did.domain.read_model import FreshnessSnapshot, MemberSnapshot
from did.domain.scopes import (
    MembershipOutcome,
    MembershipRuleType,
    ScopeMembershipResolver,
    ScopeMembershipRule,
    ScopeType,
    VisibilityScope,
)

GUILD = 100
MEMBER = 200
SCOPE_ID = UUID("00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 17, tzinfo=UTC)


def member(
    *roles: int,
    complete: bool = True,
    state: FreshnessState = FreshnessState.FRESH,
) -> MemberSnapshot:
    return MemberSnapshot(
        GUILD,
        MEMBER,
        roles,
        complete,
        FreshnessSnapshot(state, "GATEWAY", 7, NOW, NOW, NOW),
    )


def scope() -> VisibilityScope:
    return VisibilityScope(SCOPE_ID, GUILD, ScopeType.PROJECT, "alpha", "Alpha", version=3)


def test_visibility_scope_domain_requires_exact_logical_group_coupling() -> None:
    with pytest.raises(ValueError, match="logical_group_id"):
        VisibilityScope(SCOPE_ID, GUILD, ScopeType.LOGICAL_GROUP, "group", "Group")
    with pytest.raises(ValueError, match="logical_group_id"):
        VisibilityScope(
            SCOPE_ID,
            GUILD,
            ScopeType.PROJECT,
            "project",
            "Project",
            logical_group_id=uuid4(),
        )


def rule(
    index: int,
    rule_type: MembershipRuleType,
    config: dict[str, object],
    *,
    priority: int | None = None,
) -> ScopeMembershipRule:
    return ScopeMembershipRule(
        UUID(f"00000000-0000-0000-0000-{index:012d}"),
        GUILD,
        SCOPE_ID,
        rule_type,
        config,
        index if priority is None else priority,
        version=2,
    )


@pytest.mark.parametrize(
    ("rule_type", "config", "roles", "expected"),
    [
        (MembershipRuleType.DISCORD_ROLE, {"role_ids": [10]}, (10,), MembershipOutcome.MATCH),
        (
            MembershipRuleType.ANY_DISCORD_ROLE,
            {"role_ids": [10, 11]},
            (11,),
            MembershipOutcome.MATCH,
        ),
        (
            MembershipRuleType.ALL_DISCORD_ROLES,
            {"role_ids": [10, 11]},
            (10,),
            MembershipOutcome.NO_MATCH,
        ),
        (
            MembershipRuleType.ALL_DISCORD_ROLES,
            {"role_ids": [10, 11]},
            (10, 11),
            MembershipOutcome.MATCH,
        ),
    ],
)
def test_role_membership_rules(
    rule_type: MembershipRuleType,
    config: dict[str, object],
    roles: tuple[int, ...],
    expected: MembershipOutcome,
) -> None:
    decision = ScopeMembershipResolver().resolve(
        scope=scope(), member=member(*roles), rules=(rule(1, rule_type, config),)
    )

    assert decision.outcome is expected
    assert decision.trace[0].outcome is expected
    assert decision.cache_version.startswith("3:7:")


def test_explicit_membership_is_did_data_and_custom_rule_is_not_executed() -> None:
    explicit = ScopeMembershipResolver().resolve(
        scope=scope(),
        member=member(),
        rules=(rule(1, MembershipRuleType.EXPLICIT_DID_MEMBERSHIP, {}),),
        explicit_member_ids=frozenset({MEMBER}),
    )
    custom = ScopeMembershipResolver().resolve(
        scope=scope(),
        member=member(),
        rules=(
            rule(
                2,
                MembershipRuleType.CUSTOM,
                {"expression": "__import__('os').system('never')"},
            ),
        ),
    )

    assert explicit.outcome is MembershipOutcome.MATCH
    assert custom.outcome is MembershipOutcome.UNKNOWN
    assert custom.diagnostics == ("scopes.custom_rule_not_supported",)


@pytest.mark.parametrize(
    "subject",
    [member(10, complete=False), member(10, state=FreshnessState.STALE)],
)
def test_missing_or_stale_role_knowledge_is_unknown(subject: MemberSnapshot) -> None:
    decision = ScopeMembershipResolver().resolve(
        scope=scope(),
        member=subject,
        rules=(rule(1, MembershipRuleType.DISCORD_ROLE, {"role_ids": [10]}),),
    )
    assert decision.outcome is MembershipOutcome.UNKNOWN


def test_invalid_or_duplicate_role_rule_is_unknown() -> None:
    for config in ({"role_ids": []}, {"role_ids": [10, 10]}, {"role_ids": ["10"]}):
        decision = ScopeMembershipResolver().resolve(
            scope=scope(),
            member=member(10),
            rules=(rule(1, MembershipRuleType.ANY_DISCORD_ROLE, config),),
        )
        assert decision.outcome is MembershipOutcome.UNKNOWN


def test_rule_order_is_deterministic_and_a_later_match_resolves_prior_unknown() -> None:
    unknown = rule(9, MembershipRuleType.CUSTOM, {}, priority=1)
    matching = rule(2, MembershipRuleType.DISCORD_ROLE, {"role_ids": [10]}, priority=2)
    decision = ScopeMembershipResolver().resolve(
        scope=scope(), member=member(10), rules=(matching, unknown)
    )

    assert decision.outcome is MembershipOutcome.MATCH
    assert [entry.rule_id for entry in decision.trace] == [unknown.id, matching.id]


@pytest.mark.security
def test_cross_tenant_scope_rule_or_member_is_rejected() -> None:
    foreign = member(10)
    foreign_rule = ScopeMembershipRule(
        UUID("00000000-0000-0000-0000-000000000099"),
        999,
        SCOPE_ID,
        MembershipRuleType.DISCORD_ROLE,
        {"role_ids": [10]},
        1,
    )
    with pytest.raises(ValueError, match="tenant boundary"):
        ScopeMembershipResolver().resolve(scope=scope(), member=foreign, rules=(foreign_rule,))
