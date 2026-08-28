from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class TranslationGroupTopology(StrEnum):
    HUB_AND_SPOKE = "HUB_AND_SPOKE"
    FULL_MESH = "FULL_MESH"
    CUSTOM = "CUSTOM"


class VisibilityPolicy(StrEnum):
    OPEN_ALL = "OPEN_ALL"
    LANGUAGE_FILTERED = "LANGUAGE_FILTERED"
    SCOPE_AND_LANGUAGE = "SCOPE_AND_LANGUAGE"
    CUSTOM = "CUSTOM"


class RouteDecision(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    MISSING = "MISSING"


class TranslationProviderStatus(StrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"
    MANUAL_CONFIGURATION_REQUIRED = "MANUAL_CONFIGURATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    id: UUID
    guild_id: int
    code: str
    display_name: str
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if not self.code or not self.code.strip():
            raise ValueError("language code must be present")


@dataclass(frozen=True, slots=True)
class TranslationGroup:
    id: UUID
    guild_id: int
    name: str
    topology: TranslationGroupTopology
    routing_mode: TranslationGroupTopology
    visibility_policy: VisibilityPolicy
    language_ids: tuple[UUID, ...] = ()
    provider_binding_id: UUID | None = None
    status: str = "ACTIVE"
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if self.version <= 0:
            raise ValueError("version must be positive")
        if not self.name or not self.name.strip():
            raise ValueError("translation group name must be present")
        if not self.language_ids:
            raise ValueError("translation group must declare at least one language")
        if len(set(self.language_ids)) != len(self.language_ids):
            raise ValueError("language ids must be unique")


@dataclass(frozen=True, slots=True)
class TranslationRoute:
    guild_id: int
    translation_group_id: UUID
    source_language_profile_id: UUID
    destination_language_profile_id: UUID
    decision: RouteDecision = RouteDecision.ACCEPTED
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if self.source_language_profile_id == self.destination_language_profile_id:
            raise ValueError("route cannot be self-referential")


@dataclass(frozen=True, slots=True)
class TranslationProviderCapabilities:
    supports_hub_and_spoke: bool = False
    supports_full_mesh: bool = False
    supports_custom: bool = False
    supports_automatic_configuration: bool = False
    requires_manual_configuration: bool = False
    health: str = TranslationProviderStatus.UNKNOWN.value
    discord_bot_present: bool = False
    bot_permissions: tuple[str, ...] = ()

    def is_capable_for(self, topology: TranslationGroupTopology) -> bool:
        if topology is TranslationGroupTopology.HUB_AND_SPOKE:
            return self.supports_hub_and_spoke
        if topology is TranslationGroupTopology.FULL_MESH:
            return self.supports_full_mesh
        if topology is TranslationGroupTopology.CUSTOM:
            return self.supports_custom
        raise ValueError(f"unsupported topology: {topology}")


@dataclass(frozen=True, slots=True)
class ResourceLanguagePolicy:
    id: UUID
    guild_id: int
    resource_type: str
    discord_resource_id: int
    explicit_language_profile_id: UUID | None = None
    inherit_language: bool = False
    visibility_policy: VisibilityPolicy = VisibilityPolicy.OPEN_ALL
    visibility_scope_id: UUID | None = None
    custom_policy_json: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if self.discord_resource_id <= 0:
            raise ValueError("discord_resource_id must be positive")


@dataclass(frozen=True, slots=True)
class TranslationChannelVariant:
    id: UUID
    guild_id: int
    translation_channel_group_id: UUID
    language_profile_id: UUID
    discord_channel_id: int
    translation_category_variant_id: UUID | None = None
    state: str = "ACTIVE"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if self.discord_channel_id <= 0:
            raise ValueError("discord_channel_id must be positive")


class ResourceLanguageResolver:
    """Resolve resource language with an explicit SELF/CATEGORY/NONE source."""

    def resolve(
        self,
        *,
        channel_language: LanguageProfile | None,
        category_language: LanguageProfile | None,
    ) -> tuple[UUID | None, str]:
        if channel_language is not None:
            return channel_language.id, "SELF"
        if category_language is not None:
            return category_language.id, "CATEGORY"
        return None, "NONE"


def member_language_set_is_valid(languages: Iterable[str]) -> bool:
    """A member has zero, one or many visible languages; no primary language is required."""
    normalized = tuple(
        dict.fromkeys((value.strip() if isinstance(value, str) else "") for value in languages)
    )
    return all(item for item in normalized)


def resolve_scope_language_role_key(scope_id: UUID, language_profile_id: UUID) -> str:
    return f"scope:{scope_id}:language:{language_profile_id}"


def validate_translation_routes(
    *,
    guild_id: int,
    group_id: UUID,
    language_ids: tuple[UUID, ...],
    variants: dict[str, dict[str, Any]],
    routes: list[dict[str, Any]],
) -> list[TranslationRoute]:
    if guild_id <= 0:
        raise ValueError("guild_id must be positive")
    if len(set(language_ids)) != len(language_ids):
        raise ValueError("language ids must be unique")

    seen_routes: set[tuple[UUID, UUID]] = set()
    accepted: list[TranslationRoute] = []
    for index, route in enumerate(routes):
        source = route.get("source_language_profile_id")
        destination = route.get("destination_language_profile_id")
        if not isinstance(source, UUID) or not isinstance(destination, UUID):
            raise RouteValidationError(f"route[{index}] missing valid language ids")
        if source not in set(language_ids) or destination not in set(language_ids):
            raise RouteValidationError(f"route[{index}] references language outside the group")
        if source == destination:
            raise RouteValidationError(f"route[{index}] is self-referential")
        if (source, destination) in seen_routes:
            raise RouteValidationError(f"route[{index}] is a duplicate route")
        seen_routes.add((source, destination))
        source_variant = next(
            (
                item
                for item in variants.values()
                if item.get("guild_id") == guild_id and item.get("language_profile_id") == source
            ),
            None,
        )
        destination_variant = next(
            (
                item
                for item in variants.values()
                if item.get("guild_id") == guild_id
                and item.get("language_profile_id") == destination
            ),
            None,
        )
        if source_variant is None or destination_variant is None:
            raise RouteValidationError(f"route[{index}] points to a missing variant")
        if (
            int(source_variant.get("guild_id", -1)) != guild_id
            or int(destination_variant.get("guild_id", -1)) != guild_id
        ):
            raise RouteValidationError(f"route[{index}] crosses a tenant boundary")
        accepted.append(
            TranslationRoute(
                guild_id=guild_id,
                translation_group_id=group_id,
                source_language_profile_id=source,
                destination_language_profile_id=destination,
                decision=RouteDecision.ACCEPTED,
                reason="translation.route.validated",
            )
        )
    return accepted


class RouteValidationError(ValueError):
    pass
