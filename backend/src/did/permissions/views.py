from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from did.domain.read_model import (
    ChannelSnapshot,
    FreshnessSnapshot,
    GuildSnapshot,
    MemberSnapshot,
    OverwriteSnapshot,
)
from did.permissions.calculator import PermissionEvaluator
from did.permissions.models import PermissionDecision
from did.permissions.registry import DEFAULT_PERMISSION_REGISTRY, PermissionRegistry


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
