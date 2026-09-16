from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Literal

from did.domain.discord_runtime import FreshnessState
from did.domain.read_model import (
    ChannelSnapshot,
    FreshnessSnapshot,
    GuildSnapshot,
    MemberSnapshot,
    OverwriteSnapshot,
)
from did.domain.read_model.models import ChannelType
from did.permissions.calculator import PermissionEvaluator
from did.permissions.models import PermissionDecision
from did.permissions.registry import DEFAULT_PERMISSION_REGISTRY, PermissionRegistry
from did.planning.models import DesiredNode, ReferenceKind, ResourceReference, ResourceType


class ViewAsMode(StrEnum):
    VIEW_AS_MEMBER = "VIEW_AS_MEMBER"
    VIEW_AS_ROLE = "VIEW_AS_ROLE"
    VIEW_AS_NEWCOMER = "VIEW_AS_NEWCOMER"


@dataclass(frozen=True, slots=True)
class ViewAsSubject:
    mode: ViewAsMode
    member: MemberSnapshot
    synthetic: bool
    source_role_id: int | None = None


def view_as_member(member: MemberSnapshot) -> ViewAsSubject:
    return ViewAsSubject(ViewAsMode.VIEW_AS_MEMBER, member, False)


def view_as_role(
    guild: GuildSnapshot, role_id: int, *, freshness: FreshnessSnapshot
) -> ViewAsSubject:
    if guild.role(role_id) is None or role_id == guild.guild_id:
        raise ValueError("VIEW_AS_ROLE requires a known non-everyone role")
    member = MemberSnapshot(
        guild_id=guild.guild_id,
        user_id=_synthetic_subject_id(guild),
        role_ids=(role_id,),
        roles_complete=True,
        freshness=freshness,
        private_thread_memberships_complete=False,
    )
    return ViewAsSubject(ViewAsMode.VIEW_AS_ROLE, member, True, role_id)


def view_as_newcomer(guild: GuildSnapshot, *, freshness: FreshnessSnapshot) -> ViewAsSubject:
    member = MemberSnapshot(
        guild_id=guild.guild_id,
        user_id=_synthetic_subject_id(guild),
        role_ids=(),
        roles_complete=True,
        freshness=freshness,
        private_thread_memberships_complete=False,
    )
    return ViewAsSubject(ViewAsMode.VIEW_AS_NEWCOMER, member, True)


def _synthetic_subject_id(guild: GuildSnapshot) -> int:
    """Return an unmistakably synthetic positive ID that cannot trigger owner bypass."""

    occupied = {guild.guild_id, guild.owner_id, *(role.role_id for role in guild.roles)}
    candidate = max(occupied) + 1
    while candidate in occupied:
        candidate += 1
    return candidate


class CategorySyncState(StrEnum):
    SYNCED = "SYNCED"
    DESYNCED = "DESYNCED"
    UNKNOWN = "UNKNOWN"


def category_sync_state(
    channel: ChannelSnapshot, category: ChannelSnapshot | None
) -> CategorySyncState:
    if channel.parent_id is None or category is None or channel.parent_id != category.channel_id:
        return CategorySyncState.UNKNOWN
    if not channel.overwrites_complete or not category.overwrites_complete:
        return CategorySyncState.UNKNOWN
    if channel.observability.value != "VISIBLE" or category.observability.value != "VISIBLE":
        return CategorySyncState.UNKNOWN
    if (
        channel.freshness.state is not FreshnessState.FRESH
        or category.freshness.state is not FreshnessState.FRESH
    ):
        return CategorySyncState.UNKNOWN

    def canonical(values: tuple[OverwriteSnapshot, ...]) -> list[tuple[int, int, int, int]]:
        return sorted(
            (value.target_type, value.target_id, value.allow, value.deny) for value in values
        )

    return (
        CategorySyncState.SYNCED
        if canonical(channel.overwrites) == canonical(category.overwrites)
        else CategorySyncState.DESYNCED
    )


class SimplePermissionConcept(StrEnum):
    VIEW = "VIEW"
    WRITE = "WRITE"
    MANAGE = "MANAGE"
    VOICE_JOIN = "VOICE_JOIN"
    VOICE_SPEAK = "VOICE_SPEAK"
    VOICE_STREAM = "VOICE_STREAM"


@dataclass(frozen=True, slots=True)
class SimpleCompilation:
    concepts: tuple[SimplePermissionConcept, ...]
    allow_bits: int
    deny_bits: int
    known_flags: tuple[str, ...]
    diagnostics: tuple[str, ...]
    registry_version: str


@dataclass(frozen=True, slots=True)
class PolicyAccessCompilation:
    """Canonical intent -> Discord permission translation used by explain and DSG."""

    access: str
    permission_names: tuple[str, ...]
    bits: int
    diagnostics: tuple[str, ...]
    registry_version: str


def compile_simple_permissions(
    concepts: tuple[SimplePermissionConcept, ...],
    *,
    registry: PermissionRegistry = DEFAULT_PERMISSION_REGISTRY,
) -> SimpleCompilation:
    mapping = {
        SimplePermissionConcept.VIEW: ("VIEW_CHANNEL",),
        SimplePermissionConcept.WRITE: ("SEND_MESSAGES", "SEND_MESSAGES_IN_THREADS"),
        SimplePermissionConcept.MANAGE: (
            "MANAGE_CHANNELS",
            "MANAGE_MESSAGES",
            "MANAGE_THREADS",
        ),
        SimplePermissionConcept.VOICE_JOIN: ("VIEW_CHANNEL", "CONNECT"),
        SimplePermissionConcept.VOICE_SPEAK: ("CONNECT", "SPEAK"),
        SimplePermissionConcept.VOICE_STREAM: ("CONNECT", "STREAM"),
    }
    bits = 0
    for concept in concepts:
        for name in mapping[concept]:
            bits |= registry.value(name)
    diagnostics = (
        ("permissions.simple.write_context_dependent",)
        if SimplePermissionConcept.WRITE in concepts
        else ()
    )
    return SimpleCompilation(
        concepts=concepts,
        allow_bits=bits,
        deny_bits=0,
        known_flags=registry.names(bits),
        diagnostics=diagnostics,
        registry_version=registry.version,
    )


def compile_policy_access(
    access: str,
    *,
    channel_type: ChannelType | int | None = None,
    registry: PermissionRegistry = DEFAULT_PERMISSION_REGISTRY,
) -> PolicyAccessCompilation:
    """Translate one ACCESS_CONTROL v1 business intent to real Discord flags.

    Thread creation is deliberately distinct from participation. Discord forum/media
    posts require ``SEND_MESSAGES`` while text/announcement threads use the dedicated
    create flags. ``@everyone`` and ``@here`` intentionally remain one business intent
    because Discord exposes a single ``MENTION_EVERYONE`` permission for both.
    """

    unknown_type_diagnostic: tuple[str, ...] = ()
    try:
        normalized_type = ChannelType(channel_type) if channel_type is not None else None
    except ValueError:
        normalized_type = None
        unknown_type_diagnostic = ("policy.translation.channel_type_unknown",)
    diagnostics: tuple[str, ...] = ()
    names: tuple[str, ...]
    if access == "VIEW":
        names = ("VIEW_CHANNEL",)
    elif access == "WRITE":
        names = ("SEND_MESSAGES", "SEND_MESSAGES_IN_THREADS")
    elif access == "MANAGE":
        names = ("MANAGE_CHANNELS", "MANAGE_MESSAGES", "MANAGE_THREADS")
    elif access == "CONNECT":
        names = ("CONNECT",)
    elif access == "SPEAK":
        if normalized_type is ChannelType.GUILD_STAGE_VOICE:
            names = ("REQUEST_TO_SPEAK",)
            diagnostics = ("policy.translation.stage_speak_controls_request",)
        else:
            names = ("SPEAK",)
    elif access == "MANAGE_VOICE":
        names = (
            ("MANAGE_CHANNELS", "MOVE_MEMBERS", "MUTE_MEMBERS")
            if normalized_type is ChannelType.GUILD_STAGE_VOICE
            else ("MANAGE_CHANNELS", "MOVE_MEMBERS", "MUTE_MEMBERS", "DEAFEN_MEMBERS")
        )
    elif access == "CREATE_THREAD":
        if normalized_type in {ChannelType.GUILD_FORUM, ChannelType.GUILD_MEDIA}:
            names = ("SEND_MESSAGES",)
            diagnostics = ("policy.translation.thread_forum_uses_send_messages",)
        elif normalized_type is ChannelType.GUILD_ANNOUNCEMENT:
            names = ("CREATE_PUBLIC_THREADS",)
        else:
            names = ("CREATE_PUBLIC_THREADS", "CREATE_PRIVATE_THREADS")
    elif access == "PARTICIPATE_THREAD":
        names = ("SEND_MESSAGES_IN_THREADS",)
    elif access == "REACT":
        names = ("ADD_REACTIONS",)
        diagnostics = ("policy.translation.reactions_existing_emoji_limitation",)
    elif access == "MENTION_EVERYONE_HERE":
        names = ("MENTION_EVERYONE",)
        diagnostics = ("policy.translation.everyone_here_share_discord_permission",)
    elif access == "READ_HISTORY":
        names = ("READ_MESSAGE_HISTORY",)
    elif access == "SEND":
        names = (
            ("SEND_MESSAGES_IN_THREADS",)
            if normalized_type is not None and normalized_type.is_thread
            else ("SEND_MESSAGES",)
        )
    elif access == "MANAGE_CHANNEL":
        names = ("MANAGE_CHANNELS",)
    else:
        raise ValueError(f"unsupported ACCESS_CONTROL intent: {access}")
    diagnostics = tuple(dict.fromkeys((*diagnostics, *unknown_type_diagnostic)))
    bits = 0
    for name in names:
        bits |= registry.value(name)
    return PolicyAccessCompilation(access, names, bits, diagnostics, registry.version)


class AccessSynthesis(StrEnum):
    """Human synthesis tier for an access-matrix cell (REQ-AP-MAT-002).

    Reuses the exact same concept -> bit tables as ``compile_simple_permissions``;
    it never introduces a second permission calculation.
    """

    UNKNOWN = "UNKNOWN"
    NONE = "NONE"
    VIEW = "VIEW"
    WRITE = "WRITE"
    MANAGE = "MANAGE"
    CONNECT = "CONNECT"
    SPEAK = "SPEAK"


def synthesize_access(
    effective_bits: int,
    *,
    is_voice: bool,
    registry: PermissionRegistry = DEFAULT_PERMISSION_REGISTRY,
) -> AccessSynthesis:
    if not effective_bits & registry.value("VIEW_CHANNEL"):
        return AccessSynthesis.NONE
    manage_bits = compile_simple_permissions(
        (SimplePermissionConcept.MANAGE,), registry=registry
    ).allow_bits
    if is_voice:
        if effective_bits & manage_bits:
            return AccessSynthesis.MANAGE
        connect_bit = registry.value("CONNECT")
        if not effective_bits & connect_bit:
            return AccessSynthesis.NONE
        if effective_bits & registry.value("SPEAK"):
            return AccessSynthesis.SPEAK
        return AccessSynthesis.CONNECT
    if effective_bits & manage_bits:
        return AccessSynthesis.MANAGE
    write_bits = compile_simple_permissions(
        (SimplePermissionConcept.WRITE,), registry=registry
    ).allow_bits
    if effective_bits & write_bits:
        return AccessSynthesis.WRITE
    return AccessSynthesis.VIEW


def bot_writes_humans_read_overwrite_nodes(
    *,
    channel_id: int,
    bot_subject_id: int,
    human_role_id: int,
    bot_target_type: Literal[0, 1] = 0,
    registry: PermissionRegistry = DEFAULT_PERMISSION_REGISTRY,
) -> tuple[DesiredNode, DesiredNode]:
    """REQ-BOT-006: build the two `OVERWRITE` DesiredNodes for a real Discord
    channel that grant a bot VIEW+WRITE and deny WRITE to a human role
    (VIEW stays allowed). Bit values come from the same VIEW/WRITE concept
    compiler the simple permission dashboard already uses
    (`compile_simple_permissions`), never a separately invented bitmask.

    Callers feed the returned nodes into a normal `DesiredStateGraph` and
    apply it through the existing Stage05 plan/apply engine -- this function
    never mutates Discord itself and is not a parallel mutation path.
    """
    write_bits = compile_simple_permissions(
        (SimplePermissionConcept.WRITE,), registry=registry
    ).allow_bits
    view_bits = compile_simple_permissions(
        (SimplePermissionConcept.VIEW,), registry=registry
    ).allow_bits
    channel_ref = ResourceReference(ReferenceKind.DISCORD_ID, str(channel_id))
    bot_overwrite = DesiredNode.build(
        logical_key=f"overwrite.bot-writes.{channel_id}.{bot_subject_id}",
        resource_type=ResourceType.OVERWRITE,
        properties={
            "target_type": bot_target_type,
            "allow": str(view_bits | write_bits),
            "deny": "0",
        },
        relations={
            "channel": channel_ref,
            "subject": ResourceReference(ReferenceKind.DISCORD_ID, str(bot_subject_id)),
        },
    )
    humans_overwrite = DesiredNode.build(
        logical_key=f"overwrite.humans-read.{channel_id}.{human_role_id}",
        resource_type=ResourceType.OVERWRITE,
        properties={"target_type": 0, "allow": str(view_bits), "deny": str(write_bits)},
        relations={
            "channel": channel_ref,
            "subject": ResourceReference(ReferenceKind.DISCORD_ID, str(human_role_id)),
        },
    )
    return bot_overwrite, humans_overwrite


@dataclass(frozen=True, slots=True)
class ExpertPermissionModel:
    calculated_bits: int
    effective_bits: int
    calculated_known_flags: tuple[str, ...]
    effective_known_flags: tuple[str, ...]
    unknown_bits: int
    overwrites: tuple[OverwriteSnapshot, ...]
    coverage: str
    freshness: str
    status: str


def expert_model(
    decision: PermissionDecision,
    channel: ChannelSnapshot | None,
    *,
    registry: PermissionRegistry = DEFAULT_PERMISSION_REGISTRY,
) -> ExpertPermissionModel:
    return ExpertPermissionModel(
        calculated_bits=decision.calculated_bits,
        effective_bits=decision.effective_bits,
        calculated_known_flags=registry.names(decision.calculated_bits),
        effective_known_flags=registry.names(decision.effective_bits),
        unknown_bits=decision.unknown_bits,
        overwrites=channel.overwrites if channel is not None else (),
        coverage=decision.coverage.value,
        freshness=decision.freshness.value,
        status=decision.status.value,
    )


@dataclass(frozen=True, slots=True)
class SubjectImpact:
    subject_id: int
    before: PermissionDecision
    after: PermissionDecision
    added_effective_bits: int
    removed_effective_bits: int


@dataclass(frozen=True, slots=True)
class ImpactResult:
    subjects: tuple[SubjectImpact, ...]
    incomplete_subject_ids: tuple[int, ...]
    warnings: tuple[str, ...]
    persisted: bool = False


def simulate_overwrites(
    *,
    evaluator: PermissionEvaluator,
    guild: GuildSnapshot,
    channel: ChannelSnapshot,
    subjects: tuple[MemberSnapshot, ...],
    proposed_overwrites: tuple[OverwriteSnapshot, ...],
) -> ImpactResult:
    if any(
        overwrite.guild_id != channel.guild_id or overwrite.channel_id != channel.channel_id
        for overwrite in proposed_overwrites
    ):
        raise ValueError("proposed overwrite crosses the selected resource tenant")
    proposed = replace(channel, overwrites=proposed_overwrites, overwrites_complete=True)
    impacts: list[SubjectImpact] = []
    incomplete: list[int] = []
    for subject in sorted(subjects, key=lambda item: item.user_id):
        before = evaluator.evaluate(guild=guild, member=subject, resource=channel)
        after = evaluator.evaluate(guild=guild, member=subject, resource=proposed)
        impacts.append(
            SubjectImpact(
                subject_id=subject.user_id,
                before=before,
                after=after,
                added_effective_bits=after.effective_bits & ~before.effective_bits,
                removed_effective_bits=before.effective_bits & ~after.effective_bits,
            )
        )
        if before.status.value != "COMPLETE" or after.status.value != "COMPLETE":
            incomplete.append(subject.user_id)
    return ImpactResult(tuple(impacts), tuple(incomplete), ())
