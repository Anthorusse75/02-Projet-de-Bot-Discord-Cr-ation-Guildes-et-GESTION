from __future__ import annotations

from dataclasses import dataclass, field

from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
from did.domain.read_model import GuildSnapshot
from did.domain.read_model.models import ChannelType
from did.portability.artifact import (
    ArtifactType,
    PortableArtifact,
    PortableDependency,
    PortableProvenance,
    PortableResource,
    PortableResourceType,
)


class SourceNotObservable(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ArtifactSelection:
    artifact_type: ArtifactType
    category_ids: tuple[int, ...] = field(default_factory=tuple)
    channel_ids: tuple[int, ...] = field(default_factory=tuple)
    role_ids: tuple[int, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        values = self.category_ids + self.channel_ids + self.role_ids
        if any(value <= 0 for value in values):
            raise ValueError("source selection IDs must be positive")


class PortableArtifactBuilder:
    """Build a closed immutable snapshot while the source read context is active."""

    def build_live(self, guild: GuildSnapshot, selection: ArtifactSelection) -> PortableArtifact:
        self._assert_live_source_coverage(guild)
        channels = {channel.channel_id: channel for channel in guild.channels}
        roles = {role.role_id: role for role in guild.roles}
        selected_channels = set(selection.channel_ids)
        selected_categories = set(selection.category_ids)
        selected_roles = set(selection.role_ids)
        if selection.artifact_type is ArtifactType.GUILD_CONFIG and not (
            selected_channels or selected_categories or selected_roles
        ):
            selected_channels.update(
                channel.channel_id for channel in guild.channels if not channel.is_thread
            )
            selected_roles.update(role.role_id for role in guild.roles)
        for category_id in tuple(selected_categories):
            category = channels.get(category_id)
            if category is None or category.channel_type != ChannelType.GUILD_CATEGORY:
                raise ValueError("selected category is unavailable")
            selected_channels.add(category_id)
            selected_channels.update(
                channel.channel_id
                for channel in guild.channels
                if channel.parent_id == category_id and not channel.is_thread
            )
        for channel_id in tuple(selected_channels):
            channel = channels.get(channel_id)
            if channel is None or channel.is_thread:
                raise ValueError("selected channel is unavailable or unsupported")
            if channel.parent_id is not None:
                selected_channels.add(channel.parent_id)
            for overwrite in channel.overwrites:
                if overwrite.target_type == 0:
                    selected_roles.add(overwrite.target_id)
        if not selected_channels and not selected_roles:
            raise ValueError("portable selection is empty")
        self._assert_selected_observable(guild, selected_channels, selected_roles)

        channel_keys = self._keys(
            "category",
            sorted(value for value in selected_channels if channels[value].channel_type == 4),
        )
        channel_keys.update(
            self._keys(
                "channel",
                sorted(value for value in selected_channels if channels[value].channel_type != 4),
            )
        )
        role_keys = self._keys("role", sorted(selected_roles - {guild.guild_id}))
        resources: list[PortableResource] = []
        dependencies: list[PortableDependency] = []
        source_ids: set[str] = {str(value) for value in selected_channels | selected_roles}

        everyone_key = "principal.everyone"
        if guild.guild_id in selected_roles:
            resources.append(
                PortableResource.build(
                    everyone_key,
                    PortableResourceType.SYSTEM_PRINCIPAL,
                    {"kind": "EVERYONE"},
                )
            )
        for role_id in sorted(selected_roles - {guild.guild_id}):
            role = roles.get(role_id)
            if role is None:
                raise ValueError("selected or dependent role is unavailable")
            resources.append(
                PortableResource.build(
                    role_keys[role_id],
                    PortableResourceType.ROLE,
                    {
                        "name": role.name,
                        "permissions": str(role.permissions),
                        "color": role.color,
                        "hoist": role.hoist,
                        "mentionable": role.mentionable,
                        "position": role.position,
                        "managed": role.managed,
                    },
                )
            )
        overwrite_index = 0
        for channel_id in sorted(selected_channels):
            channel = channels[channel_id]
            key = channel_keys[channel_id]
            kind = (
                PortableResourceType.CATEGORY
                if channel.channel_type == ChannelType.GUILD_CATEGORY
                else PortableResourceType.CHANNEL
            )
            attributes: dict[str, object] = {
                "name": channel.name or "unnamed",
                "position": channel.position,
            }
            if kind is PortableResourceType.CHANNEL:
                attributes.update(
                    {
                        "type": int(channel.channel_type),
                        "topic": channel.topic,
                        "nsfw": channel.nsfw,
                        "flags": channel.flags,
                    }
                )
                if int(channel.channel_type) in {0, 5}:
                    attributes.update(
                        {
                            "rate_limit_per_user": channel.rate_limit_per_user,
                            "default_auto_archive_duration": (
                                channel.default_auto_archive_duration
                            ),
                        }
                    )
                if int(channel.channel_type) in {2, 13}:
                    attributes.update(
                        {
                            "bitrate": channel.bitrate,
                            "user_limit": channel.user_limit,
                        }
                    )
            resources.append(PortableResource.build(key, kind, attributes))
            if channel.parent_id is not None:
                dependencies.append(
                    PortableDependency(key, channel_keys[channel.parent_id], "parent")
                )
            for overwrite in channel.overwrites:
                overwrite_index += 1
                overwrite_key = f"overwrite.o{overwrite_index:04d}"
                if overwrite.target_type == 0:
                    principal_key = (
                        everyone_key
                        if overwrite.target_id == guild.guild_id
                        else role_keys[overwrite.target_id]
                    )
                else:
                    principal_key = f"principal_requirement.member{overwrite_index:04d}"
                    resources.append(
                        PortableResource.build(
                            principal_key,
                            PortableResourceType.PRINCIPAL_REQUIREMENT,
                            {"kind": "MEMBER", "source_binding": "REMOVED"},
                        )
                    )
                resources.append(
                    PortableResource.build(
                        overwrite_key,
                        PortableResourceType.OVERWRITE,
                        {
                            "target_type": overwrite.target_type,
                            "allow": str(overwrite.allow),
                            "deny": str(overwrite.deny),
                        },
                    )
                )
                dependencies.extend(
                    (
                        PortableDependency(overwrite_key, key, "channel"),
                        PortableDependency(overwrite_key, principal_key, "principal"),
                    )
                )
        roots = self._roots(selection, selected_channels, selected_roles, channel_keys, role_keys)
        return PortableArtifact(
            selection.artifact_type,
            tuple(resources),
            tuple(dependencies),
            roots,
            PortableProvenance(str(guild.guild_id), tuple(sorted(source_ids))),
        )

    def build_live_logical_group(
        self, guild: GuildSnapshot, group: dict[str, object]
    ) -> PortableArtifact:
        raw_resources = group.get("resources")
        if not isinstance(raw_resources, list):
            raise ValueError("logical group resources are unavailable")
        categories: list[int] = []
        channels: list[int] = []
        roles: list[int] = []
        for item in raw_resources:
            if not isinstance(item, dict):
                raise ValueError("logical group resource is invalid")
            resource_id = item.get("discord_resource_id")
            resource_type = item.get("resource_type")
            if not isinstance(resource_id, int) or resource_id <= 0:
                raise ValueError("logical group resource ID is invalid")
            if resource_type == "CATEGORY":
                categories.append(resource_id)
            elif resource_type == "CHANNEL":
                channels.append(resource_id)
            elif resource_type == "ROLE":
                roles.append(resource_id)
            else:
                raise ValueError("logical group resource type is unsupported")
        structural = self.build_live(
            guild,
            ArtifactSelection(
                ArtifactType.LOGICAL_GROUP,
                tuple(categories),
                tuple(channels),
                tuple(roles),
            ),
        )
        group_key = "logical_group.root"
        dependencies = list(structural.dependencies)
        for root in structural.roots:
            dependencies.append(PortableDependency(group_key, root, "contains"))
        name = group.get("name")
        slug = group.get("slug")
        description = group.get("description")
        if not isinstance(name, str) or not isinstance(slug, str):
            raise ValueError("logical group metadata is invalid")
        resource = PortableResource.build(
            group_key,
            PortableResourceType.LOGICAL_GROUP,
            {
                "name": name,
                "slug": slug,
                "description": description if isinstance(description, str) else None,
            },
        )
        return PortableArtifact(
            ArtifactType.LOGICAL_GROUP,
            (*structural.resources, resource),
            tuple(dependencies),
            (group_key,),
            structural.provenance,
        )

    @staticmethod
    def _assert_live_source_coverage(guild: GuildSnapshot) -> None:
        if (
            guild.coverage.mode is not CoverageMode.FULL
            or guild.coverage.freshness is not FreshnessState.FRESH
            or guild.freshness.state is not FreshnessState.FRESH
            or not guild.channels_complete
            or not guild.roles_complete
            or not guild.coverage.overwrites_complete
        ):
            raise SourceNotObservable("live clone source coverage is insufficient")

    @staticmethod
    def _assert_selected_observable(
        guild: GuildSnapshot,
        channel_ids: set[int],
        role_ids: set[int],
    ) -> None:
        channels = {channel.channel_id: channel for channel in guild.channels}
        roles = {role.role_id: role for role in guild.roles}
        if any(
            channel_id not in channels
            or channels[channel_id].observability is not ObservabilityState.VISIBLE
            or channels[channel_id].freshness.state is not FreshnessState.FRESH
            or not channels[channel_id].overwrites_complete
            for channel_id in channel_ids
        ) or any(
            role_id not in roles or roles[role_id].freshness.state is not FreshnessState.FRESH
            for role_id in role_ids
        ):
            raise SourceNotObservable("live clone source is stale, hidden or inaccessible")

    @staticmethod
    def _keys(prefix: str, source_ids: list[int]) -> dict[int, str]:
        return {
            source_id: f"{prefix}.{prefix[0]}{index:04d}"
            for index, source_id in enumerate(source_ids, 1)
        }

    @staticmethod
    def _roots(
        selection: ArtifactSelection,
        selected_channels: set[int],
        selected_roles: set[int],
        channel_keys: dict[int, str],
        role_keys: dict[int, str],
    ) -> tuple[str, ...]:
        roots = [channel_keys[value] for value in selection.category_ids + selection.channel_ids]
        roots.extend(role_keys[value] for value in selection.role_ids if value in role_keys)
        if not roots:
            roots.extend(channel_keys[value] for value in sorted(selected_channels))
            roots.extend(role_keys[value] for value in sorted(selected_roles) if value in role_keys)
        return tuple(sorted(set(roots)))
