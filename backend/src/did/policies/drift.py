"""REQ-AP-LOCK-*: compare what a Policy says Discord should grant against what
Discord ACTUALLY grants right now, reusing the existing, real
``PermissionEvaluator`` (the same calculator the Access Matrix already uses)
rather than a second permission engine. This module produces no I/O and no
mutation -- it only decides, for one already-computed ``PolicyResolution``,
whether the live Discord state already satisfies it.
"""

from __future__ import annotations

from did.domain.discord_runtime import CoverageMode, FreshnessState
from did.domain.read_model import ChannelSnapshot, GuildSnapshot, MemberSnapshot
from did.permissions import PermissionEvaluator
from did.permissions.models import DecisionStatus, TraceStep
from did.policies.resolver import PolicyResolution, PolicyResolutionOutcome, PolicyTargetState

_UNRESTRICTABLE_TRACE_STEPS = frozenset({TraceStep.OWNER_BYPASS, TraceStep.ADMINISTRATOR_BYPASS})


def discord_currently_satisfies(
    resolution: PolicyResolution,
    *,
    guild: GuildSnapshot,
    member: MemberSnapshot,
    channel: ChannelSnapshot,
    evaluator: PermissionEvaluator,
) -> tuple[bool, bool]:
    """True when Discord's real, currently-effective permissions for this
    member on this channel already reflect what ``resolution`` (the Policy's
    computed decision) requires.

    Returns ``(satisfied, unknown)``: ``unknown`` is True when Discord's live
    state cannot be evaluated with confidence (stale/incomplete coverage) --
    callers must fail closed on this, never treat it as compliant.
    """

    decision = evaluator.evaluate(guild=guild, member=member, resource=channel)
    if decision.status is not DecisionStatus.COMPLETE:
        return False, True
    if resolution.outcome is PolicyResolutionOutcome.CANNOT and any(
        entry.step in _UNRESTRICTABLE_TRACE_STEPS for entry in decision.trace
    ):
        # The guild owner and ADMINISTRATOR roles bypass every overwrite at
        # the real Discord layer -- no Plan can ever create a channel
        # overwrite that denies them (Discord itself does not support it).
        # A Policy that would otherwise deny this subject is not "drifted"
        # here: there was never anything to correct.
        return True, False
    required_allow = int(resolution.discord_allow_bits)
    required_deny = int(resolution.discord_deny_bits)
    if resolution.outcome is PolicyResolutionOutcome.CAN:
        satisfied = (decision.effective_bits & required_allow) == required_allow
    else:
        satisfied = (decision.effective_bits & required_deny) == 0
    return satisfied, False


def real_state_resolution(
    resolution: PolicyResolution, *, satisfied: bool, unknown: bool
) -> PolicyResolution:
    """Build a ``PolicyResolution``-shaped view of what Discord ACTUALLY has
    right now for the exact same subject/scope/access as ``resolution`` -- so
    the existing entry-diff (``_entry``) and DSG compiler (``_compile_graph``)
    can compare "Policy says" against "Discord has" exactly the way they
    already compare "Policy A" against "Policy B", with zero changes to
    either.
    """

    if unknown:
        outcome = PolicyResolutionOutcome.UNKNOWN
    elif satisfied:
        outcome = resolution.outcome
    else:
        outcome = (
            PolicyResolutionOutcome.CANNOT
            if resolution.outcome is PolicyResolutionOutcome.CAN
            else PolicyResolutionOutcome.CAN
        )
    return PolicyResolution(
        guild_id=resolution.guild_id,
        subject_id=resolution.subject_id,
        decision=resolution.decision,
        outcome=outcome,
        target_scope_type=resolution.target_scope_type,
        target_scope_id=resolution.target_scope_id,
        target_state=PolicyTargetState.CURRENT,
        target_freshness=FreshnessState.FRESH,
        coverage=CoverageMode.FULL,
        # When Discord already reflects the Policy (satisfied), mirror its
        # contributions/scopes verbatim so the contribution-key comparison in
        # `_entry()` correctly reports UNCHANGED instead of a false
        # RESOLUTION_CHANGED (matching outcomes with differently-shaped
        # provenance would otherwise never compare as equal). When drifted or
        # unknown, these are genuinely empty: Discord does not actually
        # reflect this Policy's contribution right now.
        applicable_policies=resolution.applicable_policies if satisfied else (),
        contributions=resolution.contributions if satisfied else (),
        conflicts=(),
        source_scopes=resolution.source_scopes if satisfied else (),
        priority_trace=(),
        conditions=(),
        incomplete_reasons=("policy.drift.discord_state_unknown",) if unknown else (),
        warnings=(),
        source_versions=resolution.source_versions,
        discord_permissions=resolution.discord_permissions,
        discord_allow_bits=resolution.discord_allow_bits if satisfied else "0",
        discord_deny_bits=resolution.discord_deny_bits if satisfied else "0",
    )
