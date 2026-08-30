from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

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
                channel.channel_id
                for channel in guild.channels
                if not channel.is_thread
                and channel.observability is not ObservabilityState.DELETED_CONFIRMED
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
                if channel.parent_id == category_id
                and not channel.is_thread
                and channel.observability is not ObservabilityState.DELETED_CONFIRMED
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
            guild.guild_id,
            "category",
            sorted(value for value in selected_channels if channels[value].channel_type == 4),
        )
        channel_keys.update(
            self._keys(
                guild.guild_id,
                "channel",
                sorted(value for value in selected_channels if channels[value].channel_type != 4),
            )
        )
        role_keys = self._keys(guild.guild_id, "role", sorted(selected_roles - {guild.guild_id}))
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
                overwrite_key = self._logical_key(
                    guild.guild_id,
                    "overwrite",
                    f"{channel_id}:{overwrite.target_type}:{overwrite.target_id}",
                )
                if overwrite.target_type == 0:
                    principal_key = (
                        everyone_key
                        if overwrite.target_id == guild.guild_id
                        else role_keys[overwrite.target_id]
                    )
                else:
                    principal_key = self._logical_key(
                        guild.guild_id, "principal_requirement", str(overwrite.target_id)
                    )
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

    def build_live_translation_group(
        self,
        guild: GuildSnapshot,
        group: dict[str, Any],
        *,
        policies: tuple[dict[str, Any], ...] = (),
        language_role_bindings: tuple[dict[str, Any], ...] = (),
        provider_requirement: dict[str, Any] | None = None,
    ) -> PortableArtifact:
        """Extend the Stage 06 snapshot with allowlisted Stage 08 topology metadata."""

        active_categories = tuple(
            row
            for row in group["category_variants"]
            if str(row["state"]) == "ACTIVE"
        )
        active_channels = tuple(
            row for row in group["channel_variants"] if str(row["state"]) == "ACTIVE"
        )
        if not active_categories and not active_channels:
            raise ValueError("translation clone requires at least one active Discord variant")
        structural = self.build_live(
            guild,
            ArtifactSelection(
                ArtifactType.CUSTOM_BUNDLE,
                tuple(int(row["discord_category_id"]) for row in active_categories),
                tuple(int(row["discord_channel_id"]) for row in active_channels),
            ),
        )
        resources = list(structural.resources)
        dependencies = list(structural.dependencies)
        languages = tuple(group["languages"])
        if not languages or any(not bool(row["enabled"]) for row in languages):
            raise ValueError("portable translation topology requires enabled languages")
        language_by_id = {str(row["id"]): row for row in languages}
        language_keys = {
            identity: self._logical_key(guild.guild_id, "translation_language", identity)
            for identity in language_by_id
        }
        for identity, language in language_by_id.items():
            resources.append(
                PortableResource.build(
                    language_keys[identity],
                    PortableResourceType.LANGUAGE_PROFILE,
                    {
                        "code": str(language["code"]),
                        "display_name": str(language["display_name"]),
                    },
                )
            )
        group_identity = str(group["id"])
        group_key = self._logical_key(
            guild.guild_id, "translation_group", group_identity
        )
        source_language_id = group.get("source_language_profile_id")
        source_language = (
            language_by_id.get(str(source_language_id))
            if source_language_id is not None
            else None
        )
        resources.append(
            PortableResource.build(
                group_key,
                PortableResourceType.TRANSLATION_GROUP,
                {
                    "name": str(group["name"]),
                    "root_kind": str(group["root_kind"]),
                    "routing_mode": str(group["routing_mode"]),
                    "source_language_code": (
                        str(source_language["code"]) if source_language is not None else None
                    ),
                },
            )
        )
        for language_key in language_keys.values():
            dependencies.append(
                PortableDependency(group_key, language_key, "language")
            )

        policy_by_resource = {
            (str(row["resource_type"]), int(row["discord_resource_id"])): row
            for row in policies
        }
        category_by_id = {str(row["id"]): row for row in active_categories}
        category_keys: dict[str, str] = {}
        for row in active_categories:
            identity = str(row["id"])
            language_id = str(row["language_profile_id"])
            language = language_by_id.get(language_id)
            if language is None:
                raise ValueError("category variant language is outside its translation group")
            resource_id = int(row["discord_category_id"])
            policy = self._portable_visibility_policy(
                policy_by_resource.get(("CATEGORY", resource_id))
            )
            variant_key = self._logical_key(
                guild.guild_id, "translation_category_variant", identity
            )
            category_keys[identity] = variant_key
            resources.append(
                PortableResource.build(
                    variant_key,
                    PortableResourceType.TRANSLATION_CATEGORY_VARIANT,
                    {
                        "language_code": str(language["code"]),
                        "is_source": bool(row["is_source"]),
                        "visibility_policy": policy["visibility_policy"],
                        "inherit_language": policy["inherit_language"],
                    },
                )
            )
            dependencies.extend(
                (
                    PortableDependency(variant_key, group_key, "translation_group"),
                    PortableDependency(
                        variant_key, language_keys[language_id], "language"
                    ),
                    PortableDependency(
                        variant_key,
                        self._logical_key(guild.guild_id, "category", str(resource_id)),
                        "discord_resource",
                    ),
                )
            )

        channel_group_keys: dict[str, str] = {}
        for row in group["channel_groups"]:
            identity = str(row["id"])
            source_id = row.get("source_language_profile_id")
            source = language_by_id.get(str(source_id)) if source_id is not None else None
            channel_group_key = self._logical_key(
                guild.guild_id, "translation_channel_group", identity
            )
            channel_group_keys[identity] = channel_group_key
            resources.append(
                PortableResource.build(
                    channel_group_key,
                    PortableResourceType.TRANSLATION_CHANNEL_GROUP,
                    {
                        "logical_key": str(row["logical_key"]),
                        "display_name": str(row["display_name"]),
                        "source_language_code": (
                            str(source["code"]) if source is not None else None
                        ),
                    },
                )
            )
            dependencies.append(
                PortableDependency(
                    channel_group_key, group_key, "translation_group"
                )
            )

        for row in active_channels:
            identity = str(row["id"])
            language_id = str(row["language_profile_id"])
            language = language_by_id.get(language_id)
            resolved_channel_group_key = channel_group_keys.get(
                str(row["translation_channel_group_id"])
            )
            if language is None or resolved_channel_group_key is None:
                raise ValueError("channel variant references foreign translation metadata")
            resource_id = int(row["discord_channel_id"])
            parent = category_by_id.get(str(row["translation_category_variant_id"]))
            inherited_policy = (
                policy_by_resource.get(("CATEGORY", int(parent["discord_category_id"])))
                if parent is not None
                else None
            )
            policy = self._portable_visibility_policy(
                policy_by_resource.get(("CHANNEL", resource_id)),
                inherited=inherited_policy,
            )
            variant_key = self._logical_key(
                guild.guild_id, "translation_channel_variant", identity
            )
            resources.append(
                PortableResource.build(
                    variant_key,
                    PortableResourceType.TRANSLATION_CHANNEL_VARIANT,
                    {
                        "language_code": str(language["code"]),
                        "visibility_policy": policy["visibility_policy"],
                        "inherit_language": policy["inherit_language"],
                    },
                )
            )
            dependencies.extend(
                (
                    PortableDependency(variant_key, group_key, "translation_group"),
                    PortableDependency(
                        variant_key, language_keys[language_id], "language"
                    ),
                    PortableDependency(
                        variant_key,
                        resolved_channel_group_key,
                        "translation_channel_group",
                    ),
                    PortableDependency(
                        variant_key,
                        self._logical_key(guild.guild_id, "channel", str(resource_id)),
                        "discord_resource",
                    ),
                )
            )
            category_identity = row.get("translation_category_variant_id")
            if category_identity is not None:
                category_key = category_keys.get(str(category_identity))
                if category_key is None:
                    raise ValueError("channel variant category is outside its translation group")
                dependencies.append(
                    PortableDependency(
                        variant_key, category_key, "translation_category_variant"
                    )
                )

        for row in group["routes"]:
            source = language_by_id.get(str(row["source_language_profile_id"]))
            destination = language_by_id.get(
                str(row["destination_language_profile_id"])
            )
            if source is None or destination is None:
                raise ValueError("translation route language is outside its group")
            route_key = self._logical_key(
                guild.guild_id, "translation_route", str(row["id"])
            )
            resources.append(
                PortableResource.build(
                    route_key,
                    PortableResourceType.TRANSLATION_ROUTE,
                    {
                        "source_language_code": str(source["code"]),
                        "destination_language_code": str(destination["code"]),
                    },
                )
            )
            dependencies.extend(
                (
                    PortableDependency(route_key, group_key, "translation_group"),
                    PortableDependency(
                        route_key,
                        language_keys[str(row["source_language_profile_id"])],
                        "source_language",
                    ),
                    PortableDependency(
                        route_key,
                        language_keys[str(row["destination_language_profile_id"])],
                        "destination_language",
                    ),
                )
            )

        role_by_id = {role.role_id: role for role in guild.roles}
        structural_keys = {resource.logical_key for resource in structural.resources}
        for binding in language_role_bindings:
            language_id = str(binding["language_profile_id"])
            language = language_by_id.get(language_id)
            role_id = int(binding["discord_role_id"])
            role = role_by_id.get(role_id)
            if language is None or role is None or str(binding["role_state"]) != "ACTIVE":
                continue
            role_key = self._logical_key(guild.guild_id, "role", str(role_id))
            if role_key not in structural_keys:
                continue
            if role.permissions != 0 or role.hoist or role.mentionable or role.managed:
                raise ValueError("portable technical language role attributes are unsafe")
            binding_key = self._logical_key(
                guild.guild_id, "translation_language_role", language_id
            )
            resources.append(
                PortableResource.build(
                    binding_key,
                    PortableResourceType.TRANSLATION_LANGUAGE_ROLE,
                    {"language_code": str(language["code"])},
                )
            )
            dependencies.extend(
                (
                    PortableDependency(binding_key, group_key, "translation_group"),
                    PortableDependency(binding_key, language_keys[language_id], "language"),
                    PortableDependency(
                        binding_key,
                        role_key,
                        "discord_resource",
                    ),
                )
            )

        if provider_requirement is not None:
            provider_key = self._logical_key(
                guild.guild_id, "translation_provider_requirement", group_identity
            )
            resources.append(
                PortableResource.build(
                    provider_key,
                    PortableResourceType.PROVIDER_REQUIREMENT,
                    provider_requirement,
                )
            )
            dependencies.append(
                PortableDependency(provider_key, group_key, "translation_group")
            )
        return PortableArtifact(
            ArtifactType.CUSTOM_BUNDLE,
            tuple(resources),
            tuple(dependencies),
            (group_key,),
            structural.provenance,
        )

    @staticmethod
    def _portable_visibility_policy(
        policy: dict[str, Any] | None,
        *,
        inherited: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        effective = policy
        inherit = bool(policy and policy.get("inherit_language"))
        if effective is None or inherit:
            effective = inherited or effective
        visibility = str(
            effective["visibility_policy"] if effective is not None else "OPEN_ALL"
        )
        if visibility not in {"OPEN_ALL", "LANGUAGE_FILTERED"}:
            raise ValueError(
                "scope-bound or custom visibility requires explicit destination mapping"
            )
        return {"visibility_policy": visibility, "inherit_language": inherit}

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
    def _keys(source_guild_id: int, prefix: str, source_ids: list[int]) -> dict[int, str]:
        return {
            source_id: PortableArtifactBuilder._logical_key(source_guild_id, prefix, str(source_id))
            for source_id in source_ids
        }

    @staticmethod
    def _logical_key(source_guild_id: int, resource_type: str, source_identity: str) -> str:
        """Encode a stable source identity without exposing a raw Discord ID as a reference."""

        material = (
            f"did:portable-logical:v1:{source_guild_id}:{resource_type}:{source_identity}"
        ).encode()
        return f"{resource_type}.k{hashlib.sha256(material).hexdigest()[:40]}"

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
