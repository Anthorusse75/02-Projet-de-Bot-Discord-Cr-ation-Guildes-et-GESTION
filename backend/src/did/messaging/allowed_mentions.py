"""AllowedMentionsCompiler (WP5).

REQ-MSG: default is NO mentions. ``everyone``/``here`` is only ever allowed
when the caller explicitly passes ``capability_allows_everyone=True`` (that
flag must itself be derived from a real, authorized capability check --
never a client-supplied boolean trusted as-is). Explicit user/role
allowlists are always compiled as an id list, never combined with the
matching ``parse`` entry for that kind, so translation can never turn a
literal ``@everyone``/mention token embedded in message content into a mass
ping by accident: only what this compiler explicitly allowlists can ping.
"""

from __future__ import annotations

from dataclasses import dataclass


class MentionPolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AllowedMentionsPolicy:
    allow_everyone: bool = False
    allowed_user_ids: tuple[int, ...] = ()
    allowed_role_ids: tuple[int, ...] = ()
    replied_user: bool = False

    def __post_init__(self) -> None:
        if any(user_id <= 0 for user_id in self.allowed_user_ids):
            raise ValueError("allowed_user_ids must all be positive snowflakes")
        if any(role_id <= 0 for role_id in self.allowed_role_ids):
            raise ValueError("allowed_role_ids must all be positive snowflakes")


@dataclass(frozen=True, slots=True)
class CompiledAllowedMentions:
    parse: tuple[str, ...] = ()
    users: tuple[int, ...] = ()
    roles: tuple[int, ...] = ()
    replied_user: bool = False

    def to_discord_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "parse": list(self.parse),
            "replied_user": self.replied_user,
        }
        if self.users:
            payload["users"] = list(self.users)
        if self.roles:
            payload["roles"] = list(self.roles)
        return payload


#: The one and only "no mentions" compiled value -- the default for every
#: campaign delivery unless a capability-gated policy explicitly widens it.
NO_MENTIONS = CompiledAllowedMentions()


class AllowedMentionsCompiler:
    def compile(
        self,
        policy: AllowedMentionsPolicy,
        *,
        capability_allows_everyone: bool,
    ) -> CompiledAllowedMentions:
        if policy.allow_everyone and not capability_allows_everyone:
            raise MentionPolicyError(
                "everyone/here mentions require an explicitly granted capability"
            )
        parse: tuple[str, ...] = ("everyone",) if policy.allow_everyone else ()
        return CompiledAllowedMentions(
            parse=parse,
            users=policy.allowed_user_ids,
            roles=policy.allowed_role_ids,
            replied_user=policy.replied_user,
        )
