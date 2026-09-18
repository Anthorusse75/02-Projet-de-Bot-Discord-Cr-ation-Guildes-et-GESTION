from __future__ import annotations

from datetime import UTC, datetime

from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
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
from did.policies.drift import discord_currently_satisfies, real_state_resolution
from did.policies.resolver import (
    PolicyResolution,
    PolicyResolutionOutcome,
    PolicyScopeType,
    PolicyTargetState,
)

GUILD = 995_001
ACTOR = 995_011
MEMBER = 995_021
ROLE = 995_031
CHANNEL = 995_101
NOW = datetime(2026, 9, 17, tzinfo=UTC)
VIEW_BIT = DEFAULT_PERMISSION_REGISTRY.value("VIEW_CHANNEL")
EVALUATOR = PermissionEvaluator()


def _guild(overwrites: tuple[OverwriteSnapshot, ...] = ()) -> GuildSnapshot:
    fresh = FreshnessSnapshot(FreshnessState.FRESH, "CACHE", 1, NOW, NOW, NOW)
    coverage = CoverageSnapshot(
        GUILD, CoverageMode.FULL, FreshnessState.FRESH, "CACHE", 1,
        known_channels=1, visible_channels=1, known_roles=2,
        members_complete=True, overwrites_complete=True,
    )
    return GuildSnapshot(
        GUILD, ACTOR,
        (
            RoleSnapshot(GUILD, GUILD, "@everyone", 0, 0, False, fresh),
            RoleSnapshot(GUILD, ROLE, "role", 1, 0, False, fresh),
        ),
        (
            ChannelSnapshot(
                GUILD, CHANNEL, ChannelType.GUILD_TEXT, 0, None, "board",
                overwrites, True, ObservabilityState.VISIBLE, fresh,
            ),
        ),
        coverage, fresh, source_versions=("guild:1",),
    )


def _member() -> MemberSnapshot:
    fresh = FreshnessSnapshot(FreshnessState.FRESH, "CACHE", 1, NOW, NOW, NOW)
    return MemberSnapshot(GUILD, MEMBER, (ROLE,), True, fresh)


def _resolution(
    outcome: PolicyResolutionOutcome, *, allow: int = 0, deny: int = 0
) -> PolicyResolution:
    return PolicyResolution(
        guild_id=GUILD, subject_id=MEMBER, decision="ACCESS_CONTROL:VIEW", outcome=outcome,
        target_scope_type=PolicyScopeType.CHANNEL, target_scope_id=str(CHANNEL),
        target_state=PolicyTargetState.CURRENT, target_freshness=FreshnessState.FRESH,
        coverage=CoverageMode.FULL, applicable_policies=(), contributions=(), conflicts=(),
        source_scopes=(), priority_trace=(), conditions=(), incomplete_reasons=(), warnings=(),
        source_versions=("cache:1",), discord_permissions=("VIEW_CHANNEL",),
        discord_allow_bits=str(allow), discord_deny_bits=str(deny),
    )


def test_no_drift_when_the_locked_policy_allow_bit_is_already_granted() -> None:
    guild = _guild((OverwriteSnapshot(GUILD, CHANNEL, MEMBER, 1, VIEW_BIT, 0),))
    resolution = _resolution(PolicyResolutionOutcome.CAN, allow=VIEW_BIT)
    satisfied, unknown = discord_currently_satisfies(
        resolution, guild=guild, member=_member(), channel=guild.channels[0], evaluator=EVALUATOR
    )
    assert satisfied is True and unknown is False


def test_drift_detected_when_discord_no_longer_grants_the_required_allow_bit() -> None:
    guild = _guild(())  # the member overwrite was externally removed
    resolution = _resolution(PolicyResolutionOutcome.CAN, allow=VIEW_BIT)
    satisfied, unknown = discord_currently_satisfies(
        resolution, guild=guild, member=_member(), channel=guild.channels[0], evaluator=EVALUATOR
    )
    assert satisfied is False and unknown is False


def test_drift_detected_when_discord_grants_a_bit_the_policy_requires_denied() -> None:
    guild = _guild((OverwriteSnapshot(GUILD, CHANNEL, MEMBER, 1, VIEW_BIT, 0),))
    resolution = _resolution(PolicyResolutionOutcome.CANNOT, deny=VIEW_BIT)
    satisfied, unknown = discord_currently_satisfies(
        resolution, guild=guild, member=_member(), channel=guild.channels[0], evaluator=EVALUATOR
    )
    assert satisfied is False and unknown is False


def test_no_drift_when_the_locked_policy_deny_is_already_respected() -> None:
    guild = _guild(())
    resolution = _resolution(PolicyResolutionOutcome.CANNOT, deny=VIEW_BIT)
    satisfied, unknown = discord_currently_satisfies(
        resolution, guild=guild, member=_member(), channel=guild.channels[0], evaluator=EVALUATOR
    )
    assert satisfied is True and unknown is False


def test_incomplete_coverage_fails_closed_as_unknown_never_compliant() -> None:
    fresh = FreshnessSnapshot(FreshnessState.FRESH, "CACHE", 1, NOW, NOW, NOW)
    stale_member = MemberSnapshot(GUILD, MEMBER, (ROLE,), False, fresh)  # roles_complete=False
    guild = _guild((OverwriteSnapshot(GUILD, CHANNEL, MEMBER, 1, VIEW_BIT, 0),))
    resolution = _resolution(PolicyResolutionOutcome.CAN, allow=VIEW_BIT)
    satisfied, unknown = discord_currently_satisfies(
        resolution, guild=guild, member=stale_member, channel=guild.channels[0],
        evaluator=EVALUATOR,
    )
    assert satisfied is False and unknown is True


def test_real_state_resolution_mirrors_the_policy_outcome_when_satisfied() -> None:
    resolution = _resolution(PolicyResolutionOutcome.CAN, allow=VIEW_BIT)
    current = real_state_resolution(resolution, satisfied=True, unknown=False)
    assert current.outcome is PolicyResolutionOutcome.CAN
    assert current.discord_allow_bits == str(VIEW_BIT)


def test_real_state_resolution_flips_outcome_when_drifted() -> None:
    resolution = _resolution(PolicyResolutionOutcome.CAN, allow=VIEW_BIT)
    current = real_state_resolution(resolution, satisfied=False, unknown=False)
    assert current.outcome is PolicyResolutionOutcome.CANNOT
    assert current.discord_allow_bits == "0"


def test_real_state_resolution_is_unknown_with_a_diagnostic_when_incomplete() -> None:
    resolution = _resolution(PolicyResolutionOutcome.CAN, allow=VIEW_BIT)
    current = real_state_resolution(resolution, satisfied=False, unknown=True)
    assert current.outcome is PolicyResolutionOutcome.UNKNOWN
    assert "policy.drift.discord_state_unknown" in current.incomplete_reasons
