from __future__ import annotations

from typing import Any

from did.domain.read_model import GuildSnapshot
from did.planning.models import (
    DesiredNode,
    DesiredStateGraph,
    DiffAction,
    DiffEntry,
    NodePresence,
    ReferenceKind,
    ResourceReference,
    ResourceType,
    freeze_json_object,
)


class DiffEngine:
    """Pure semantic diff. It performs no persistence and no network I/O."""

    _MOVE_FIELDS = frozenset({"position", "parent_id"})

    def compare(self, observed: GuildSnapshot, desired: DesiredStateGraph) -> tuple[DiffEntry, ...]:
        if observed.guild_id != desired.guild_id:
            raise ValueError("observed and desired states belong to different Guilds")
        entries = [self._compare_node(observed, desired, node) for node in desired.nodes]
        return tuple(sorted(entries, key=lambda entry: entry.node.logical_key))

    def _compare_node(
        self,
        observed: GuildSnapshot,
        desired: DesiredStateGraph,
        node: DesiredNode,
    ) -> DiffEntry:
        if node.resource_type is ResourceType.GUILD:
            return DiffEntry(DiffAction.NO_CHANGE, node)
        if node.resource_type is ResourceType.MEMBER_ROLE:
            properties = node.property_map()
            desired_assigned = bool(properties.get("assigned", False))
            current_assigned = bool(properties.get("current_assigned", False))
            member_before = {
                "id": node.discord_id,
                "member_id": node.discord_id,
                "role_id": properties.get("role_id"),
                "assigned": current_assigned,
            }
            return DiffEntry(
                DiffAction.NO_CHANGE if desired_assigned == current_assigned else DiffAction.UPDATE,
                node,
                freeze_json_object(member_before),
                (() if desired_assigned == current_assigned else ("assigned",)),
            )
        if node.resource_type is ResourceType.OVERWRITE:
            return self._compare_overwrite(observed, desired, node)
        before = self._observed_resource(observed, node)
        exists = before is not None
        if node.presence is NodePresence.ABSENT:
            return DiffEntry(
                DiffAction.DELETE if exists else DiffAction.NO_CHANGE,
                node,
                freeze_json_object(before or {}),
            )
        if not exists:
            return DiffEntry(DiffAction.CREATE, node)
        assert before is not None
        desired_values = self._desired_values(desired, node)
        changed = tuple(
            sorted(
                key
                for key, value in desired_values.items()
                if key in before and self._semantic(before[key]) != self._semantic(value)
            )
        )
        if not changed:
            return DiffEntry(
                DiffAction.NO_CHANGE,
                node,
                freeze_json_object(before),
            )
        action = (
            DiffAction.MOVE_OR_REORDER
            if set(changed).issubset(self._MOVE_FIELDS)
            else DiffAction.UPDATE
        )
        return DiffEntry(action, node, freeze_json_object(before), changed)

    def _compare_overwrite(
        self,
        observed: GuildSnapshot,
        desired: DesiredStateGraph,
        node: DesiredNode,
    ) -> DiffEntry:
        channel_id = self._resolve_reference(desired, node.relation("channel"))
        target_id = self._resolve_reference(desired, node.relation("subject"))
        properties = node.property_map()
        target_type = int(properties.get("target_type", 0))
        channel = observed.channel(channel_id) if channel_id is not None else None
        current = None
        if channel is not None and target_id is not None:
            current = next(
                (
                    item
                    for item in channel.overwrites
                    if item.target_id == target_id and item.target_type == target_type
                ),
                None,
            )
        before: dict[str, Any] = (
            {
                "channel_id": channel_id,
                "target_id": target_id,
                "target_type": target_type,
                "allow": current.allow,
                "deny": current.deny,
            }
            if current is not None
            else {}
        )
        if node.presence is NodePresence.ABSENT:
            action = DiffAction.DELETE if current is not None else DiffAction.NO_CHANGE
            return DiffEntry(action, node, freeze_json_object(before))
        if current is None:
            return DiffEntry(DiffAction.CREATE, node)
        changed = tuple(
            key for key in ("allow", "deny") if int(properties.get(key, 0)) != int(before[key])
        )
        return DiffEntry(
            DiffAction.UPDATE if changed else DiffAction.NO_CHANGE,
            node,
            freeze_json_object(before),
            changed,
        )

    def _desired_values(self, desired: DesiredStateGraph, node: DesiredNode) -> dict[str, Any]:
        values = node.property_map()
        parent = node.relation("parent")
        if parent is not None:
            values["parent_id"] = self._resolve_reference(desired, parent)
        elif node.resource_type is ResourceType.CHANNEL and "parent_id" in values:
            values["parent_id"] = values["parent_id"]
        return values

    @staticmethod
    def _observed_resource(observed: GuildSnapshot, node: DesiredNode) -> dict[str, Any] | None:
        if node.discord_id is None:
            return None
        if node.resource_type is ResourceType.ROLE:
            role = observed.role(node.discord_id)
            if role is None:
                return None
            return {
                "id": role.role_id,
                "name": role.name,
                "position": role.position,
                "permissions": role.permissions,
                "managed": role.managed,
                "color": role.color,
                "hoist": role.hoist,
                "mentionable": role.mentionable,
            }
        if node.resource_type in {ResourceType.CATEGORY, ResourceType.CHANNEL}:
            channel = observed.channel(node.discord_id)
            if channel is None:
                return None
            return {
                "id": channel.channel_id,
                "type": int(channel.channel_type),
                "name": channel.name,
                "position": channel.position,
                "parent_id": channel.parent_id,
                "topic": channel.topic,
                "nsfw": channel.nsfw,
                "flags": channel.flags,
                "bitrate": channel.bitrate,
                "user_limit": channel.user_limit,
                "rate_limit_per_user": channel.rate_limit_per_user,
                "default_auto_archive_duration": channel.default_auto_archive_duration,
            }
        return None

    @staticmethod
    def _resolve_reference(
        desired: DesiredStateGraph, reference: ResourceReference | None
    ) -> int | None:
        if reference is None:
            return None
        if reference.kind is ReferenceKind.DISCORD_ID:
            return int(reference.value)
        if reference.kind is ReferenceKind.LOGICAL:
            target = desired.node(reference.value)
            return target.discord_id if target is not None else None
        target = next((node for node in desired.nodes if node.symbol == reference.value), None)
        return target.discord_id if target is not None else None

    @staticmethod
    def _semantic(value: Any) -> Any:
        if isinstance(value, str) and value.isdecimal():
            return int(value)
        if isinstance(value, list):
            return tuple(sorted((DiffEngine._semantic(item) for item in value), key=repr))
        if isinstance(value, dict):
            return tuple((key, DiffEngine._semantic(item)) for key, item in sorted(value.items()))
        return value
