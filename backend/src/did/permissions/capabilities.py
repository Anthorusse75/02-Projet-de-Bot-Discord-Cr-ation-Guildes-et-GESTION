from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from did.domain.read_model import ChannelSnapshot, GuildSnapshot, MemberSnapshot, RoleSnapshot
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
    can_manage = highest.role_id != target.role_id and (
        target.role_id == guild.guild_id
        or highest.position > target.position
        or (highest.position == target.position and highest.role_id < target.role_id)
    )
    return HierarchyDiagnostic(
        CapabilityOutcome.CAN if can_manage else CapabilityOutcome.CANNOT,
        highest.role_id,
        highest.position,
        target.role_id,
        target.position,
        () if can_manage else ("capability.hierarchy.bot_role_not_above_target",),
    )


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
        role_operations = {BotOperation.MANAGE_ROLE, BotOperation.ASSIGN_ROLE}
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
        if operation in {BotOperation.MANAGE_ROLE, BotOperation.ASSIGN_ROLE}:
            hierarchy = hierarchy_diagnostic(guild, bot, target_role)
            causes.extend(hierarchy.reasons)
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
