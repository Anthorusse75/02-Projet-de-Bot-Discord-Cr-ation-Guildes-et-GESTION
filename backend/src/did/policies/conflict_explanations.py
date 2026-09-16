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

Scope: both explanations attribute causes to Policy role conditions/audiences
only (REQ-AP-VIS-011/012/013 core case). Attributing a cause to
ADMINISTRATOR, a raw Discord member overwrite, or category inheritance is
intentionally left to the existing, separate Discord-effective evaluation
path (``AccessMatrixCell``/``PermissionEvaluator``); unifying every cause
family into one explanation is left open for a future lot.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from did.domain.policies import Policy
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


@dataclass(frozen=True, slots=True)
class BlacklistRegrant:
    excluding_policy_id: UUID
    excluding_role_ids: tuple[str, ...]
    regranting_policy_id: UUID
    regranting_role_ids: tuple[ConflictCauseRole, ...]
    accepted: bool
    reason_key: str


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


__all__ = [
    "BlacklistRegrant",
    "ConflictCauseRole",
    "ConflictExplanation",
    "explain_conflicts",
    "find_blacklist_regrants",
]
