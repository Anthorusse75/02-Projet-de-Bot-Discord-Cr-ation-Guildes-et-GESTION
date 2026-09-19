"""Human-narratable explanations for Policy conflicts and blacklist bypasses.

This module adds no resolution logic of its own: it re-reads the already
computed :class:`~did.policies.resolver.PolicyResolution` (contributions,
conflicts, condition trace) together with the declared
:class:`~did.domain.policies.Policy` objects involved, and explains *why*
something happened in terms a non-technical Guild admin can act on
("Martin possède aussi Managers, qui lui redonne l'accès."). It performs no
Discord I/O and evaluates nothing the resolver has not already evaluated.

Two distinct situations are covered:

* :func:`explain_conflicts` — a genuine resolver-detected
  :class:`~did.policies.resolver.PolicyConflict`: two contributions that both
  actively applied (``condition_outcome`` TRUE) with different decisions for
  the same access.
* :func:`find_blacklist_regrants` — the more common "silent" case an
  audience-based blacklist produces: a policy's ``EXCLUDE`` audience
  correctly filtered a member out (its own contribution never applied,
  ``CONDITION_FALSE``), yet the resolution still lands on the opposite
  decision because a *different*, unrelated Policy independently applies to
  the member. The blacklist author never sees a "conflict" in the resolver's
  own sense (nothing here competed), but from the Guild admin's perspective
  the blacklist plainly did not do what they expected.

The observable Discord layer is also explained here, but never recalculated:
``explain_observable_access_conflict`` consumes the canonical
``PermissionDecision`` and its trace. It unifies role permissions,
ADMINISTRATOR/owner bypass, role/member/everyone overwrites and category
inheritance in the same response shape (REQ-AP-VIS-004/CFL-001..004).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from did.domain.policies import Policy
from did.domain.read_model import ChannelSnapshot, GuildSnapshot, MemberSnapshot
from did.permissions.models import DecisionStatus, PermissionDecision
from did.permissions.registry import DEFAULT_PERMISSION_REGISTRY
from did.permissions.views import CategorySyncState, category_sync_state
from did.policies.resolver import PolicyConflict, PolicyConflictOutcome, PolicyResolution

_ROLE_CONDITION_KINDS = frozenset({"ROLE_MATCH", "ROLE_EXCLUDE"})


@dataclass(frozen=True, slots=True)
class ConflictCauseRole:
    role_id: str
    source_policy_id: UUID
    source: str  # "CONDITION" | "AUDIENCE_INCLUDE"


@dataclass(frozen=True, slots=True)
class ConflictExplanation:
    conflict: PolicyConflict
    accepted: bool
    causing_roles: tuple[ConflictCauseRole, ...]
    reason_key: str
    remediations: tuple[ConflictRemediation, ...] = ()


@dataclass(frozen=True, slots=True)
class BlacklistRegrant:
    excluding_policy_id: UUID
    excluding_role_ids: tuple[str, ...]
    regranting_policy_id: UUID
    regranting_role_ids: tuple[ConflictCauseRole, ...]
    accepted: bool
    reason_key: str


@dataclass(frozen=True, slots=True)
class ObservableConflictCause:
    kind: str
    source_id: str | None
    source_name: str | None
    decision: str
    permission_names: tuple[str, ...]
    inherited_from_category_id: str | None
    reason_key: str


@dataclass(frozen=True, slots=True)
class ConflictRemediation:
    kind: str
    target_id: str
    route: str
    requires_separate_plan: bool
    collateral_losses: tuple[str, ...]
    collateral_scope: tuple[str, ...]
    reason_key: str


@dataclass(frozen=True, slots=True)
class ObservableAccessConflict:
    member_id: str
    resource_id: str
    policy_ids: tuple[UUID, ...]
    expected_outcome: str
    actual_outcome: str
    granting_causes: tuple[ObservableConflictCause, ...]
    denying_causes: tuple[ObservableConflictCause, ...]
    remediations: tuple[ConflictRemediation, ...]


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value)


def _exception_tag(other_policy_id: UUID) -> str:
    return f"exception_accepted:{other_policy_id}"


def _has_accepted_tag(policy: Policy | None, other_policy_id: UUID) -> bool:
    if policy is None:
        return False
    return _exception_tag(other_policy_id) in _string_tuple(policy.metadata.get("tags"))


def _is_accepted(pair: tuple[UUID, UUID], policies_by_id: dict[UUID, Policy]) -> bool:
    left_id, right_id = pair
    return _has_accepted_tag(policies_by_id.get(left_id), right_id) or _has_accepted_tag(
        policies_by_id.get(right_id), left_id
    )


def _causing_roles(
    policy: Policy, member_role_ids: frozenset[str]
) -> tuple[ConflictCauseRole, ...]:
    causes: list[ConflictCauseRole] = []
    for condition in policy.conditions:
        if condition.get("kind") != "ROLE_MATCH":
            continue
        role_ids = _string_tuple(condition.get("role_ids"))
        causes.extend(
            ConflictCauseRole(role_id, policy.policy_id, "CONDITION")
            for role_id in role_ids
            if role_id in member_role_ids
        )
    for effect in policy.effects:
        audience = effect.get("audience")
        if not isinstance(audience, dict) or audience.get("mode") != "INCLUDE":
            continue
        role_ids = tuple(str(value) for value in audience.get("role_ids", ()))
        causes.extend(
            ConflictCauseRole(role_id, policy.policy_id, "AUDIENCE_INCLUDE")
            for role_id in role_ids
            if role_id in member_role_ids
        )
    return tuple(dict.fromkeys(causes))


def explain_conflicts(
    resolution: PolicyResolution,
    *,
    policies_by_id: dict[UUID, Policy],
    member_role_ids: tuple[str, ...],
    guild: GuildSnapshot | None = None,
    member: MemberSnapshot | None = None,
) -> tuple[ConflictExplanation, ...]:
    """Explain each resolver-detected :class:`PolicyConflict` using the member's roles."""

    roles = frozenset(member_role_ids)
    explanations: list[ConflictExplanation] = []
    for conflict in resolution.conflicts:
        pair = conflict.policy_ids
        accepted = len(pair) == 2 and _is_accepted(pair, policies_by_id)
        causes: list[ConflictCauseRole] = []
        for policy_id in conflict.winning_policy_ids or pair:
            policy = policies_by_id.get(policy_id)
            if policy is not None:
                causes.extend(_causing_roles(policy, roles))
        reason_key = (
            "policy.conflict.exception_accepted"
            if accepted
            else "policy.conflict.blocked"
            if conflict.outcome is PolicyConflictOutcome.BLOCKED
            else "policy.conflict.role_regrants_access"
            if causes
            else "policy.conflict.resolved_no_role_cause"
        )
        explanations.append(
            ConflictExplanation(
                conflict=conflict,
                accepted=accepted,
                causing_roles=tuple(causes),
                reason_key=reason_key,
                remediations=_policy_conflict_remediations(
                    conflict,
                    tuple(causes),
                    guild=guild,
                    member=member,
                ),
            )
        )
    return tuple(explanations)


def find_blacklist_regrants(
    resolution: PolicyResolution,
    *,
    policies_by_id: dict[UUID, Policy],
    member_role_ids: tuple[str, ...],
) -> tuple[BlacklistRegrant, ...]:
    """Detect a blacklist that correctly excluded this member, bypassed by another Policy.

    This is the "silent" case: the excluding Policy's own contribution never
    applies to this member (``CONDITION_FALSE``, because the member holds one
    of its excluded roles) so the resolver never records a
    :class:`PolicyConflict` for it — nothing here competed. Yet the member
    still ends up with the opposite decision because a different Policy
    independently grants it.
    """

    roles = frozenset(member_role_ids)
    selected = tuple(item for item in resolution.contributions if item.selected)
    if not selected:
        return ()
    winner_decision = selected[0].decision
    winner_access = selected[0].access
    regrants: list[BlacklistRegrant] = []
    for contribution in resolution.contributions:
        if (
            contribution.disposition != "CONDITION_FALSE"
            or contribution.access != winner_access
            or contribution.decision != winner_decision
        ):
            continue
        excluding_policy = policies_by_id.get(contribution.policy_id)
        if excluding_policy is None or contribution.effect_index >= len(excluding_policy.effects):
            continue
        audience = excluding_policy.effects[contribution.effect_index].get("audience")
        if not isinstance(audience, dict) or audience.get("mode") != "EXCLUDE":
            continue
        excluding_roles = tuple(
            str(value) for value in audience.get("role_ids", ()) if str(value) in roles
        )
        if not excluding_roles:
            continue
        for winner in selected:
            if winner.policy_id == contribution.policy_id:
                continue
            winning_policy = policies_by_id.get(winner.policy_id)
            if winning_policy is None:
                continue
            regranting_roles = _causing_roles(winning_policy, roles)
            accepted = _is_accepted((contribution.policy_id, winner.policy_id), policies_by_id)
            regrants.append(
                BlacklistRegrant(
                    excluding_policy_id=contribution.policy_id,
                    excluding_role_ids=excluding_roles,
                    regranting_policy_id=winner.policy_id,
                    regranting_role_ids=regranting_roles,
                    accepted=accepted,
                    reason_key=(
                        "policy.conflict.exception_accepted"
                        if accepted
                        else "policy.conflict.blacklist_bypassed_by_role"
                    ),
                )
            )
    return tuple(regrants)


def explain_observable_access_conflict(
    resolution: PolicyResolution,
    *,
    guild: GuildSnapshot,
    member: MemberSnapshot,
    channel: ChannelSnapshot,
    permission_decision: PermissionDecision,
) -> ObservableAccessConflict | None:
    """Explain a concrete Policy-vs-Discord mismatch from canonical facts.

    This function deliberately performs no permission resolution. It only
    attributes bits in an already computed ``PermissionDecision`` to the
    cached roles/overwrites that supplied them, and offers bounded navigation
    to existing Plan-producing workspaces. No remediation mutates Discord.
    """

    if (
        permission_decision.status is not DecisionStatus.COMPLETE
        or resolution.outcome.value not in {"CAN", "CANNOT"}
    ):
        return None
    allow_bits = int(resolution.discord_allow_bits)
    deny_bits = int(resolution.discord_deny_bits)
    if resolution.outcome.value == "CAN":
        mismatch_bits = allow_bits & ~permission_decision.effective_bits
        if mismatch_bits == 0:
            return None
        actual_outcome = "DENIED"
        granting: tuple[ObservableConflictCause, ...] = ()
        denying = _overwrite_causes(
            guild, member, channel, mismatch_bits=mismatch_bits, decision="DENY"
        )
        if not denying:
            denying = (
                _cause(
                    "IMPLICIT_DENIAL",
                    None,
                    None,
                    "DENY",
                    mismatch_bits,
                    None,
                    "policy.conflict.cause.implicit_denial",
                ),
            )
    else:
        mismatch_bits = deny_bits & permission_decision.effective_bits
        if mismatch_bits == 0:
            return None
        actual_outcome = "ALLOWED"
        denying = ()
        granting = _granting_causes(guild, member, channel, mismatch_bits)

    causes = (*granting, *denying)
    inherited_category = next(
        (
            cause.inherited_from_category_id
            for cause in causes
            if cause.inherited_from_category_id is not None
        ),
        None,
    )
    return ObservableAccessConflict(
        member_id=str(member.user_id),
        resource_id=str(channel.channel_id),
        policy_ids=tuple(
            dict.fromkeys(
                item.policy_id
                for item in resolution.contributions
                if item.selected or item.disposition == "CONFLICT_UNRESOLVED"
            )
        ),
        expected_outcome=resolution.outcome.value,
        actual_outcome=actual_outcome,
        granting_causes=granting,
        denying_causes=denying,
        remediations=_remediations(
            guild,
            member,
            channel,
            causes,
            inherited_category_id=inherited_category,
        ),
    )


def _granting_causes(
    guild: GuildSnapshot,
    member: MemberSnapshot,
    channel: ChannelSnapshot,
    mismatch_bits: int,
) -> tuple[ObservableConflictCause, ...]:
    if member.user_id == guild.owner_id:
        return (
            _cause(
                "OWNER",
                str(member.user_id),
                None,
                "ALLOW",
                mismatch_bits,
                None,
                "policy.conflict.cause.owner",
            ),
        )
    administrator = DEFAULT_PERMISSION_REGISTRY.value("ADMINISTRATOR")
    admin_roles = tuple(
        role
        for role in guild.roles
        if role.role_id in member.role_ids and role.permissions & administrator
    )
    if admin_roles:
        return tuple(
            _cause(
                "ADMINISTRATOR",
                str(role.role_id),
                role.name,
                "ALLOW",
                mismatch_bits,
                None,
                "policy.conflict.cause.administrator",
            )
            for role in admin_roles
        )

    causes = list(
        _overwrite_causes(guild, member, channel, mismatch_bits=mismatch_bits, decision="ALLOW")
    )
    for role in guild.roles:
        matching = role.role_id == guild.guild_id or role.role_id in member.role_ids
        supplied = role.permissions & mismatch_bits
        if matching and supplied:
            causes.append(
                _cause(
                    "BASE_ROLE",
                    str(role.role_id),
                    role.name,
                    "ALLOW",
                    supplied,
                    None,
                    "policy.conflict.cause.base_role",
                )
            )
    return tuple(dict.fromkeys(causes))


def _overwrite_causes(
    guild: GuildSnapshot,
    member: MemberSnapshot,
    channel: ChannelSnapshot,
    *,
    mismatch_bits: int,
    decision: str,
) -> tuple[ObservableConflictCause, ...]:
    parent = guild.channel(channel.parent_id) if channel.parent_id is not None else None
    inherited_category_id = (
        str(parent.channel_id)
        if parent is not None and category_sync_state(channel, parent) is CategorySyncState.SYNCED
        else None
    )
    causes: list[ObservableConflictCause] = []
    for overwrite in channel.overwrites:
        if overwrite.target_type == 1 and overwrite.target_id != member.user_id:
            continue
        if overwrite.target_type == 0 and overwrite.target_id not in {
            guild.guild_id,
            *member.role_ids,
        }:
            continue
        bits = (overwrite.allow if decision == "ALLOW" else overwrite.deny) & mismatch_bits
        if not bits:
            continue
        if overwrite.target_type == 1:
            kind = "MEMBER_OVERWRITE"
            name = None
        elif overwrite.target_id == guild.guild_id:
            kind = "EVERYONE_OVERWRITE"
            name = "@everyone"
        else:
            kind = "ROLE_OVERWRITE"
            role = guild.role(overwrite.target_id)
            name = role.name if role is not None else None
        causes.append(
            _cause(
                kind,
                str(overwrite.target_id),
                name,
                decision,
                bits,
                inherited_category_id,
                f"policy.conflict.cause.{kind.lower()}",
            )
        )
    return tuple(causes)


def _cause(
    kind: str,
    source_id: str | None,
    source_name: str | None,
    decision: str,
    bits: int,
    inherited_from_category_id: str | None,
    reason_key: str,
) -> ObservableConflictCause:
    return ObservableConflictCause(
        kind=kind,
        source_id=source_id,
        source_name=source_name,
        decision=decision,
        permission_names=DEFAULT_PERMISSION_REGISTRY.names(bits),
        inherited_from_category_id=inherited_from_category_id,
        reason_key=reason_key,
    )


def _remediations(
    guild: GuildSnapshot,
    member: MemberSnapshot,
    channel: ChannelSnapshot,
    causes: tuple[ObservableConflictCause, ...],
    *,
    inherited_category_id: str | None,
) -> tuple[ConflictRemediation, ...]:
    values: list[ConflictRemediation] = []
    seen: set[tuple[str, str]] = set()
    for cause in causes:
        if cause.kind in {"ADMINISTRATOR", "BASE_ROLE", "ROLE_OVERWRITE"}:
            if cause.source_id is None:
                continue
            role_removal = _role_removal_remediation(guild, int(cause.source_id))
            if role_removal is not None:
                _append_remediation(values, seen, role_removal)
            if cause.kind == "ROLE_OVERWRITE":
                _append_remediation(
                    values,
                    seen,
                    ConflictRemediation(
                        kind="EDIT_ROLE_OVERWRITE",
                        target_id=inherited_category_id or str(channel.channel_id),
                        route="matrix",
                        requires_separate_plan=True,
                        collateral_losses=cause.permission_names,
                        collateral_scope=(cause.source_id,),
                        reason_key="policy.conflict.remediation.edit_role_overwrite",
                    ),
                )
        elif cause.kind == "MEMBER_OVERWRITE":
            _append_remediation(
                values,
                seen,
                ConflictRemediation(
                    kind="EDIT_MEMBER_OVERWRITE",
                    target_id=inherited_category_id or str(channel.channel_id),
                    route="matrix",
                    requires_separate_plan=True,
                    collateral_losses=cause.permission_names,
                    collateral_scope=(str(member.user_id),),
                    reason_key="policy.conflict.remediation.edit_member_overwrite",
                ),
            )
        elif cause.kind == "EVERYONE_OVERWRITE":
            _append_remediation(
                values,
                seen,
                ConflictRemediation(
                    kind="EDIT_EVERYONE_OVERWRITE",
                    target_id=inherited_category_id or str(channel.channel_id),
                    route="matrix",
                    requires_separate_plan=True,
                    collateral_losses=cause.permission_names,
                    collateral_scope=("ALL_MEMBERS",),
                    reason_key="policy.conflict.remediation.edit_everyone_overwrite",
                ),
            )
    return tuple(values)


def _policy_conflict_remediations(
    conflict: PolicyConflict,
    causes: tuple[ConflictCauseRole, ...],
    *,
    guild: GuildSnapshot | None,
    member: MemberSnapshot | None,
) -> tuple[ConflictRemediation, ...]:
    values: list[ConflictRemediation] = []
    seen: set[tuple[str, str]] = set()
    if guild is not None and member is not None:
        for cause in causes:
            role_id = int(cause.role_id)
            if role_id not in member.role_ids:
                continue
            remediation = _role_removal_remediation(guild, role_id)
            if remediation is not None:
                _append_remediation(values, seen, remediation)
    for policy_id in conflict.policy_ids:
        _append_remediation(
            values,
            seen,
            ConflictRemediation(
                kind="EDIT_POLICY_DRAFT",
                target_id=str(policy_id),
                route="policies",
                requires_separate_plan=True,
                collateral_losses=(),
                collateral_scope=tuple(str(value) for value in conflict.policy_ids),
                reason_key="policy.conflict.remediation.edit_policy_draft",
            ),
        )
    return tuple(values)


def _role_removal_remediation(
    guild: GuildSnapshot, role_id: int
) -> ConflictRemediation | None:
    role = guild.role(role_id)
    if role is None or role.role_id == guild.guild_id or role.managed:
        return None
    collateral_bits = role.permissions
    collateral_scope: set[str] = set()
    for resource in guild.channels:
        for overwrite in resource.overwrites:
            if overwrite.target_type == 0 and overwrite.target_id == role.role_id:
                collateral_bits |= overwrite.allow
                if overwrite.allow:
                    collateral_scope.add(str(resource.channel_id))
    return ConflictRemediation(
        kind="REMOVE_MEMBER_ROLE",
        target_id=str(role.role_id),
        route="roles",
        requires_separate_plan=True,
        collateral_losses=DEFAULT_PERMISSION_REGISTRY.names(collateral_bits),
        collateral_scope=tuple(sorted(collateral_scope)),
        reason_key="policy.conflict.remediation.remove_role",
    )


def _append_remediation(
    values: list[ConflictRemediation],
    seen: set[tuple[str, str]],
    remediation: ConflictRemediation,
) -> None:
    key = (remediation.kind, remediation.target_id)
    if key not in seen:
        seen.add(key)
        values.append(remediation)


__all__ = [
    "BlacklistRegrant",
    "ConflictCauseRole",
    "ConflictExplanation",
    "ConflictRemediation",
    "ObservableAccessConflict",
    "ObservableConflictCause",
    "explain_conflicts",
    "explain_observable_access_conflict",
    "find_blacklist_regrants",
]
