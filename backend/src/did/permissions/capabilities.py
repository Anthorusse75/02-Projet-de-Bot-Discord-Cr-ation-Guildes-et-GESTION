from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from did.domain.read_model import ChannelSnapshot, GuildSnapshot, MemberSnapshot, RoleSnapshot
from did.domain.read_model.models import ChannelType
from did.permissions.calculator import PermissionEvaluator
from did.permissions.models import DecisionStatus
from did.permissions.registry import DEFAULT_PERMISSION_REGISTRY, PermissionRegistry


class CapabilityOutcome(StrEnum):
    CAN = "CAN"
    CANNOT = "CANNOT"
    UNKNOWN = "UNKNOWN"


class BotOperation(StrEnum):
    CREATE_CHANNEL = "CREATE_CHANNEL"
    MANAGE_CHANNEL = "MANAGE_CHANNEL"
    REORDER_CHANNELS = "REORDER_CHANNELS"
    MANAGE_OVERWRITES = "MANAGE_OVERWRITES"
    CREATE_ROLE = "CREATE_ROLE"
    MANAGE_ROLE = "MANAGE_ROLE"
    REORDER_ROLES = "REORDER_ROLES"
    ASSIGN_ROLE = "ASSIGN_ROLE"
    SEND_MESSAGE = "SEND_MESSAGE"
    MANAGE_THREAD = "MANAGE_THREAD"


@dataclass(frozen=True, slots=True)
class HierarchyDiagnostic:
    outcome: CapabilityOutcome
    bot_highest_role_id: int | None
    bot_highest_position: int | None
    target_role_id: int | None
    target_position: int | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    operation: BotOperation
    outcome: CapabilityOutcome
    required_permissions: tuple[str, ...]
    causes: tuple[str, ...]
    remediations: tuple[str, ...]
    hierarchy: HierarchyDiagnostic | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


def hierarchy_diagnostic(
    guild: GuildSnapshot, bot: MemberSnapshot, target: RoleSnapshot | None
) -> HierarchyDiagnostic:
    known_roles = [guild.role(role_id) for role_id in bot.role_ids]
    if not bot.roles_complete or any(role is None for role in known_roles):
        return HierarchyDiagnostic(
            CapabilityOutcome.UNKNOWN,
            None,
            None,
            target.role_id if target else None,
            None,
            ("capability.hierarchy.bot_roles_incomplete",),
        )
    roles = [role for role in known_roles if role is not None]
    highest = max(roles, key=lambda role: (role.position, -role.role_id), default=None)
    if target is None or highest is None:
        return HierarchyDiagnostic(
            CapabilityOutcome.UNKNOWN,
            highest.role_id if highest else None,
            highest.position if highest else None,
            target.role_id if target else None,
            target.position if target else None,
            ("capability.hierarchy.target_or_bot_role_missing",),
        )
    if target.managed:
        return HierarchyDiagnostic(
            CapabilityOutcome.CANNOT,
            highest.role_id,
            highest.position,
            target.role_id,
            target.position,
            ("capability.hierarchy.target_managed",),
        )
    # Discord's role hierarchy permits bots to edit/sort only roles at a
    # strictly lower position.  Snowflake ordering is useful to render roles
    # tied at one position, but it must not turn an equal-position target into
    # a mutable role.
    can_manage = highest.role_id != target.role_id and (
        target.role_id == guild.guild_id or highest.position > target.position
    )
    return HierarchyDiagnostic(
        CapabilityOutcome.CAN if can_manage else CapabilityOutcome.CANNOT,
        highest.role_id,
        highest.position,
        target.role_id,
        target.position,
        () if can_manage else ("capability.hierarchy.bot_role_not_above_target",),
    )


@dataclass(frozen=True, slots=True)
class BotPermissionAudit:
    """Guild-wide ADMINISTRATOR posture for one cached bot member (REQ-BOT-004)."""

    user_id: int
    role_ids: tuple[int, ...]
    is_administrator: bool
    status: DecisionStatus
    incomplete_reasons: tuple[str, ...]


def audit_guild_bots(
    guild: GuildSnapshot,
    members: Iterable[MemberSnapshot],
    evaluator: PermissionEvaluator | None = None,
) -> tuple[BotPermissionAudit, ...]:
    """Flag every locally cached bot member of a Guild that holds ADMINISTRATOR.

    Reuses the same guild-level permission evaluation Stage04 already performs
    for the installed DID bot (`BotCapabilityChecker`) against every bot member
    the cache already knows about -- it never queries Discord itself, never
    requests a new intent/scope, and never asks a tenant to grant ADMINISTRATOR;
    it only reports what is already cached and observable.
    """
    bot_evaluator = evaluator or PermissionEvaluator()
    audits = [_audit_one(guild, member, bot_evaluator) for member in members if member.is_bot]
    return tuple(sorted(audits, key=lambda audit: audit.user_id))


def _audit_one(
    guild: GuildSnapshot, bot: MemberSnapshot, evaluator: PermissionEvaluator
) -> BotPermissionAudit:
    decision = evaluator.evaluate(guild=guild, member=bot, resource=None)
    is_administrator = (
        bot.user_id == guild.owner_id
        or "permissions.warning.administratorBypassesOverwrites" in decision.warnings
    )
    return BotPermissionAudit(
        user_id=bot.user_id,
        role_ids=bot.role_ids,
        is_administrator=is_administrator,
        status=decision.status,
        incomplete_reasons=decision.incomplete_reasons,
    )


@dataclass(frozen=True, slots=True)
class BotChannelAccess:
    """One channel's real read/write posture for one bot (REQ-BOT-005)."""

    channel_id: int
    can_read: bool
    can_write: bool
    status: DecisionStatus


def _write_permission_name(channel: ChannelSnapshot) -> str:
    if channel.is_thread:
        return "SEND_MESSAGES_IN_THREADS"
    if channel.channel_type in {ChannelType.GUILD_VOICE, ChannelType.GUILD_STAGE_VOICE}:
        return "CONNECT"
    return "SEND_MESSAGES"


def bot_channel_access_map(
    guild: GuildSnapshot,
    bot: MemberSnapshot,
    evaluator: PermissionEvaluator | None = None,
    registry: PermissionRegistry = DEFAULT_PERMISSION_REGISTRY,
) -> tuple[BotChannelAccess, ...]:
    """REQ-BOT-005: where a single bot can read and write, from real cached
    roles/overwrites -- never a simulated or hypothetical permission set. One
    entry per channel already known to this Guild's cache; a channel absent
    from `guild.channels` (never observed) simply has no entry, it is never
    guessed."""
    access_evaluator = evaluator or PermissionEvaluator(registry)
    view_bit = registry.value("VIEW_CHANNEL")
    results = []
    for channel in guild.channels:
        decision = access_evaluator.evaluate(guild=guild, member=bot, resource=channel)
        write_bit = registry.value(_write_permission_name(channel))
        results.append(
            BotChannelAccess(
                channel_id=channel.channel_id,
                can_read=bool(decision.effective_bits & view_bit),
                can_write=bool(decision.effective_bits & write_bit),
                status=decision.status,
            )
        )
    return tuple(results)


class BotCapabilityChecker:
    def __init__(
        self,
        evaluator: PermissionEvaluator | None = None,
        registry: PermissionRegistry = DEFAULT_PERMISSION_REGISTRY,
    ) -> None:
        self.registry = registry
        self.evaluator = evaluator or PermissionEvaluator(registry)

    def check(
        self,
        *,
        operation: BotOperation,
        guild: GuildSnapshot,
        bot: MemberSnapshot,
        channel: ChannelSnapshot | None = None,
        target_role: RoleSnapshot | None = None,
        installation_active: bool = True,
        required_intents_available: bool = True,
    ) -> CapabilityDecision:
        permission_map = {
            BotOperation.CREATE_CHANNEL: ("MANAGE_CHANNELS",),
            BotOperation.MANAGE_CHANNEL: ("MANAGE_CHANNELS",),
            BotOperation.REORDER_CHANNELS: ("MANAGE_CHANNELS",),
            BotOperation.MANAGE_OVERWRITES: ("MANAGE_ROLES",),
            BotOperation.CREATE_ROLE: ("MANAGE_ROLES",),
            BotOperation.MANAGE_ROLE: ("MANAGE_ROLES",),
            BotOperation.REORDER_ROLES: ("MANAGE_ROLES",),
            BotOperation.ASSIGN_ROLE: ("MANAGE_ROLES",),
            BotOperation.SEND_MESSAGE: (
                "VIEW_CHANNEL",
                "SEND_MESSAGES_IN_THREADS" if channel and channel.is_thread else "SEND_MESSAGES",
            ),
            BotOperation.MANAGE_THREAD: ("VIEW_CHANNEL", "MANAGE_THREADS"),
        }
        required = permission_map[operation]
        causes: list[str] = []
        remediations: list[str] = []
        hierarchy: HierarchyDiagnostic | None = None
        channel_operations = {
            BotOperation.MANAGE_CHANNEL,
            BotOperation.MANAGE_OVERWRITES,
            BotOperation.SEND_MESSAGE,
            BotOperation.MANAGE_THREAD,
        }
        role_operations = {
            BotOperation.MANAGE_ROLE,
            BotOperation.REORDER_ROLES,
            BotOperation.ASSIGN_ROLE,
        }
        if operation in channel_operations and channel is None:
            causes.append("capability.channel_required")
        if operation in role_operations and target_role is None:
            causes.append("capability.target_role_required")
        if not installation_active:
            causes.append("capability.installation_not_active")
        if not required_intents_available:
            causes.append("capability.required_intent_missing")
        decision = self.evaluator.evaluate(guild=guild, member=bot, resource=channel)
        if decision.status is not DecisionStatus.COMPLETE:
            causes.extend(decision.incomplete_reasons)
        else:
            for name in required:
                bit = self.registry.value(name)
                if not decision.effective_bits & bit:
                    causes.append(f"capability.permission_missing.{name.lower()}")
                    remediations.append(f"capability.remediation.grant.{name.lower()}")
        if operation in role_operations:
            hierarchy = hierarchy_diagnostic(guild, bot, target_role)
            causes.extend(hierarchy.reasons)
            if operation is BotOperation.REORDER_ROLES and target_role is not None:
                if target_role.role_id == guild.guild_id:
                    causes.append("capability.hierarchy.default_role_reorder_forbidden")
                    hierarchy = HierarchyDiagnostic(
                        CapabilityOutcome.CANNOT,
                        hierarchy.bot_highest_role_id,
                        hierarchy.bot_highest_position,
                        hierarchy.target_role_id,
                        hierarchy.target_position,
                        tuple(
                            dict.fromkeys(
                                (
                                    *hierarchy.reasons,
                                    "capability.hierarchy.default_role_reorder_forbidden",
                                )
                            )
                        ),
                    )
        if not installation_active or (
            decision.status is DecisionStatus.COMPLETE
            and (
                any(item.startswith("capability.permission_missing") for item in causes)
                or (hierarchy is not None and hierarchy.outcome is CapabilityOutcome.CANNOT)
            )
        ):
            outcome = CapabilityOutcome.CANNOT
        elif (
            decision.status is not DecisionStatus.COMPLETE
            or not required_intents_available
            or "capability.channel_required" in causes
            or "capability.target_role_required" in causes
        ):
            outcome = CapabilityOutcome.UNKNOWN
        else:
            outcome = CapabilityOutcome.CAN
        return CapabilityDecision(
            operation,
            outcome,
            required,
            tuple(dict.fromkeys(causes)),
            tuple(dict.fromkeys(remediations)),
            hierarchy,
            tuple(decision.warnings),
        )
