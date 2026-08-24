from __future__ import annotations

from dataclasses import dataclass, field

from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
from did.domain.read_model import GuildSnapshot, MemberSnapshot
from did.domain.read_model.models import ChannelType
from did.permissions.capabilities import BotCapabilityChecker, BotOperation, CapabilityOutcome
from did.permissions.registry import DEFAULT_PERMISSION_REGISTRY
from did.planning.models import (
    DesiredStateGraph,
    NodePresence,
    OperationType,
    PlanOperation,
    ReferenceKind,
    ResourceType,
    RiskLevel,
    thaw_json_object,
)
from did.planning.risk import RiskAssessment


@dataclass(frozen=True, slots=True)
class DiscordLimits:
    version: str
    max_channels_per_guild: int
    max_roles_per_guild: int
    max_channels_per_category: int
    max_permission_overwrites_per_channel: int


DEFAULT_DISCORD_LIMITS = DiscordLimits(
    version="discord-capacity-2026-08-24",
    max_channels_per_guild=500,
    max_roles_per_guild=250,
    max_channels_per_category=50,
    max_permission_overwrites_per_channel=1000,
)


@dataclass(frozen=True, slots=True)
class PreflightContext:
    guild: GuildSnapshot
    bot: MemberSnapshot
    installation_active: bool
    actor_authorization_fresh: bool
    base_structure_version: str
    current_structure_version: str
    capability_version: str = DEFAULT_PERMISSION_REGISTRY.version
    limits: DiscordLimits = DEFAULT_DISCORD_LIMITS


@dataclass(frozen=True, slots=True)
class PreflightResult:
    allowed: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    checked_capabilities: tuple[str, ...] = field(default_factory=tuple)
    limits_version: str = DEFAULT_DISCORD_LIMITS.version


class PreflightEngine:
    """Fail-safe final checks reusing the STAGE 04 capability checker."""

    def __init__(self, checker: BotCapabilityChecker | None = None) -> None:
        self._checker = checker or BotCapabilityChecker()

    def check(
        self,
        *,
        graph: DesiredStateGraph,
        operations: tuple[PlanOperation, ...],
        context: PreflightContext,
        risk: RiskAssessment,
    ) -> PreflightResult:
        errors: list[str] = []
        warnings: list[str] = []
        checked: set[str] = set()
        guild = context.guild
        if graph.guild_id != guild.guild_id or context.bot.guild_id != guild.guild_id:
            errors.append("preflight.tenant_mismatch")
        if not context.installation_active:
            errors.append("preflight.installation_not_active")
        if not context.actor_authorization_fresh:
            errors.append("preflight.actor_authorization_stale")
        if context.base_structure_version != context.current_structure_version:
            errors.append("preflight.structure_stale")
        if context.capability_version != DEFAULT_PERMISSION_REGISTRY.version:
            errors.append("preflight.capability_version_stale")
        if guild.coverage.mode is not CoverageMode.FULL:
            errors.append("preflight.coverage_incomplete")
        if guild.freshness.state is not FreshnessState.FRESH:
            errors.append("preflight.guild_state_not_fresh")
        if not guild.channels_complete or not guild.roles_complete:
            errors.append("preflight.resource_inventory_incomplete")
        self._check_symbols(operations, errors)
        self._check_topology(graph, guild, errors)
        self._check_limits(graph, guild, context.limits, errors)
        for operation in operations:
            self._check_operation(
                operation,
                guild,
                context.bot,
                context.installation_active,
                errors,
                warnings,
                checked,
            )
        if risk.impact.incomplete_or_unknown and risk.level in {
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        }:
            if risk.reinforced_confirmation_required:
                warnings.append("preflight.impact_unknown_reinforced_confirmation")
            else:
                errors.append("preflight.destructive_impact_unknown")
        return PreflightResult(
            not errors,
            tuple(sorted(set(errors))),
            tuple(sorted(set(warnings))),
            tuple(sorted(checked)),
            context.limits.version,
        )

    @staticmethod
    def _check_symbols(operations: tuple[PlanOperation, ...], errors: list[str]) -> None:
        producers = {
            operation.produces_symbol
            for operation in operations
            if operation.produces_symbol is not None
        }
        for operation in operations:
            if set(operation.consumes_symbols) - producers:
                errors.append("preflight.unresolved_symbol_without_producer")

    @staticmethod
    def _check_topology(graph: DesiredStateGraph, guild: GuildSnapshot, errors: list[str]) -> None:
        desired_by_id = {
            node.discord_id: node for node in graph.nodes if node.discord_id is not None
        }
        for node in graph.nodes:
            parent = node.relation("parent")
            if node.resource_type is ResourceType.CATEGORY and parent is not None:
                errors.append("preflight.category_parent_forbidden")
            if parent is not None:
                parent_node = None
                if parent.kind is ReferenceKind.LOGICAL:
                    parent_node = graph.node(parent.value)
                elif parent.kind is ReferenceKind.DISCORD_ID:
                    parent_node = desired_by_id.get(int(parent.value))
                    observed_parent = guild.channel(int(parent.value))
                    if observed_parent is not None and int(observed_parent.channel_type) != int(
                        ChannelType.GUILD_CATEGORY
                    ):
                        errors.append("preflight.parent_not_category")
                elif parent.kind is ReferenceKind.SYMBOL:
                    parent_node = next(
                        (item for item in graph.nodes if item.symbol == parent.value), None
                    )
                if (
                    parent_node is not None
                    and parent_node.resource_type is not ResourceType.CATEGORY
                ):
                    errors.append("preflight.parent_not_category")
            if (
                node.resource_type is ResourceType.CATEGORY
                and node.presence is NodePresence.ABSENT
                and node.discord_id is not None
            ):
                children = [
                    channel for channel in guild.channels if channel.parent_id == node.discord_id
                ]
                for child in children:
                    child_node = desired_by_id.get(child.channel_id)
                    if child_node is None:
                        errors.append("preflight.category_delete_child_effect_implicit")
                        continue
                    relation = child_node.relation("parent")
                    still_child = (
                        relation is not None
                        and relation.kind is ReferenceKind.DISCORD_ID
                        and int(relation.value) == node.discord_id
                    )
                    if child_node.presence is NodePresence.PRESENT and still_child:
                        errors.append("preflight.category_delete_child_effect_implicit")

    @staticmethod
    def _check_limits(
        graph: DesiredStateGraph,
        guild: GuildSnapshot,
        limits: DiscordLimits,
        errors: list[str],
    ) -> None:
        creates_channels = sum(
            node.discord_id is None
            and node.presence is NodePresence.PRESENT
            and node.resource_type in {ResourceType.CATEGORY, ResourceType.CHANNEL}
            for node in graph.nodes
        )
        deletes_channels = sum(
            node.discord_id is not None
            and node.presence is NodePresence.ABSENT
            and node.resource_type in {ResourceType.CATEGORY, ResourceType.CHANNEL}
            for node in graph.nodes
        )
        creates_roles = sum(
            node.discord_id is None
            and node.presence is NodePresence.PRESENT
            and node.resource_type is ResourceType.ROLE
            for node in graph.nodes
        )
        deletes_roles = sum(
            node.discord_id is not None
            and node.presence is NodePresence.ABSENT
            and node.resource_type is ResourceType.ROLE
            for node in graph.nodes
        )
        if (
            len(guild.channels) + creates_channels - deletes_channels
            > limits.max_channels_per_guild
        ):
            errors.append("preflight.channel_limit_exceeded")
        if len(guild.roles) + creates_roles - deletes_roles > limits.max_roles_per_guild:
            errors.append("preflight.role_limit_exceeded")
        by_parent: dict[str, int] = {}
        for node in graph.nodes:
            parent = node.relation("parent")
            if node.presence is NodePresence.PRESENT and parent is not None:
                key = f"{parent.kind.value}:{parent.value}"
                by_parent[key] = by_parent.get(key, 0) + 1
        if any(value > limits.max_channels_per_category for value in by_parent.values()):
            errors.append("preflight.category_child_limit_exceeded")
        overwrite_counts: dict[str, int] = {}
        for node in graph.nodes:
            if (
                node.resource_type is ResourceType.OVERWRITE
                and node.presence is NodePresence.PRESENT
            ):
                channel = node.relation("channel")
                if channel is not None:
                    key = f"{channel.kind.value}:{channel.value}"
                    overwrite_counts[key] = overwrite_counts.get(key, 0) + 1
        if any(
            value > limits.max_permission_overwrites_per_channel
            for value in overwrite_counts.values()
        ):
            errors.append("preflight.overwrite_limit_exceeded")

    def _check_operation(
        self,
        operation: PlanOperation,
        guild: GuildSnapshot,
        bot: MemberSnapshot,
        installation_active: bool,
        errors: list[str],
        warnings: list[str],
        checked: set[str],
    ) -> None:
        payload = thaw_json_object(operation.desired_payload)
        resource_id = payload.get("id")
        channel = guild.channel(int(resource_id)) if resource_id is not None else None
        target_role = guild.role(int(resource_id)) if resource_id is not None else None
        operation_map = {
            OperationType.CREATE_CHANNEL: BotOperation.CREATE_CHANNEL,
            OperationType.UPDATE_CHANNEL: BotOperation.MANAGE_CHANNEL,
            OperationType.DELETE_CHANNEL: BotOperation.MANAGE_CHANNEL,
            OperationType.MOVE_OR_REORDER_CHANNELS: BotOperation.REORDER_CHANNELS,
            OperationType.UPSERT_OVERWRITE: BotOperation.MANAGE_OVERWRITES,
            OperationType.DELETE_OVERWRITE: BotOperation.MANAGE_OVERWRITES,
            OperationType.CREATE_ROLE: BotOperation.CREATE_ROLE,
            OperationType.UPDATE_ROLE: BotOperation.MANAGE_ROLE,
            OperationType.DELETE_ROLE: BotOperation.MANAGE_ROLE,
            OperationType.REORDER_ROLES: BotOperation.REORDER_ROLES,
        }
        bot_operation = operation_map[operation.operation_type]
        if operation.operation_type is OperationType.REORDER_ROLES:
            items = payload.get("items")
            if not isinstance(items, list) or not items:
                errors.append("preflight.role_reorder_targets_required")
                checked.add(bot_operation.value)
                return
            for item in items:
                if not isinstance(item, dict) or item.get("id") is None:
                    errors.append("preflight.role_reorder_target_invalid")
                    continue
                role_id = int(item["id"])
                target = guild.role(role_id)
                decision = self._checker.check(
                    operation=bot_operation,
                    guild=guild,
                    bot=bot,
                    target_role=target,
                    installation_active=installation_active,
                )
                warnings.extend(decision.warnings)
                if decision.outcome is not CapabilityOutcome.CAN:
                    errors.extend(decision.causes or ("preflight.capability_unknown",))
                desired_position = item.get("position")
                highest_position = (
                    decision.hierarchy.bot_highest_position
                    if decision.hierarchy is not None
                    else None
                )
                if (
                    desired_position is not None
                    and highest_position is not None
                    and int(desired_position) >= highest_position
                ):
                    errors.append("preflight.role_reorder_destination_not_below_bot")
                if target is None:
                    errors.append("preflight.role_reorder_target_missing")
                elif target.guild_id != guild.guild_id:
                    errors.append("preflight.role_reorder_target_tenant_mismatch")
                elif target.managed:
                    errors.append("preflight.managed_role_forbidden")
                if role_id == guild.guild_id:
                    errors.append("preflight.default_role_reorder_forbidden")
            checked.add(bot_operation.value)
            return
        if operation.operation_type in {
            OperationType.UPSERT_OVERWRITE,
            OperationType.DELETE_OVERWRITE,
        }:
            channel_id = payload.get("channel_id")
            channel = guild.channel(int(channel_id)) if channel_id is not None else None
        decision = self._checker.check(
            operation=bot_operation,
            guild=guild,
            bot=bot,
            channel=channel,
            target_role=target_role,
            installation_active=installation_active,
        )
        checked.add(bot_operation.value)
        warnings.extend(decision.warnings)
        if decision.outcome is not CapabilityOutcome.CAN:
            errors.extend(decision.causes or ("preflight.capability_unknown",))
        if channel is not None and (
            channel.observability is not ObservabilityState.VISIBLE
            or channel.freshness.state is not FreshnessState.FRESH
        ):
            errors.append("preflight.channel_not_current_visible")
        if target_role is not None and target_role.managed:
            errors.append("preflight.managed_role_forbidden")
        if (
            operation.operation_type is OperationType.DELETE_ROLE
            and target_role is not None
            and target_role.role_id == guild.guild_id
        ):
            errors.append("preflight.default_role_delete_forbidden")
