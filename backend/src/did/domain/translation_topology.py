from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
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


class ProviderConfigurationMode(StrEnum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL_CONFIGURATION_REQUIRED = "MANUAL_CONFIGURATION_REQUIRED"
    OBSERVATION_ONLY = "OBSERVATION_ONLY"


class CapabilitySupport(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class EffectiveLanguageSource(StrEnum):
    SELF = "SELF"
    CATEGORY = "CATEGORY"
    NONE = "NONE"


@runtime_checkable
class TranslationProvider(Protocol):
    async def capabilities(self, guild_id: int) -> TranslationProviderCapabilities: ...
    async def validate_group(self, desired_group: Any) -> list[dict[str, Any]]: ...
    async def prepare_configuration(self, desired_group: Any) -> dict[str, Any]: ...
    async def observe_health(self, guild_id: int) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ScopeLanguageBinding:
    guild_id: int
    scope_id: UUID
    language_profile_id: UUID
    discord_role_id: int | None = None
    binding_key: str = ""

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if not self.binding_key:
            object.__setattr__(
                self,
                "binding_key",
                resolve_scope_language_role_key(self.scope_id, self.language_profile_id),
            )


@dataclass(frozen=True, slots=True)
class ScopeLanguageRoleDecision:
    guild_id: int
    scope_id: UUID
    visibility_policy: VisibilityPolicy
    requires_explicit_binding: bool
    required_bindings: tuple[ScopeLanguageBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class TranslationChannelGroup:
    id: UUID
    guild_id: int
    name: str
    logical_group_key: str
    category_discord_id: int | None = None
    status: str = "ACTIVE"

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if not self.name or not self.name.strip():
            raise ValueError("translation channel group name must be present")
        if not self.logical_group_key or not self.logical_group_key.strip():
            raise ValueError("logical_group_key must be present")
        if self.category_discord_id is not None and self.category_discord_id <= 0:
            raise ValueError("category_discord_id must be positive")

    def renamed(self, name: str) -> TranslationChannelGroup:
        if not name or not name.strip():
            raise ValueError("translation channel group name must be present")
        return TranslationChannelGroup(
            id=self.id,
            guild_id=self.guild_id,
            name=name,
            logical_group_key=self.logical_group_key,
            category_discord_id=self.category_discord_id,
            status=self.status,
        )


class TranslationProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, TranslationProvider] = {}

    def register(self, key: str, provider: TranslationProvider) -> None:
        if not key or not key.strip():
            raise ValueError("provider key must be present")
        self._providers[key] = provider

    def get(self, key: str) -> TranslationProvider:
        try:
            return self._providers[key]
        except KeyError as exc:  # pragma: no cover - defensive branch
            raise KeyError(f"unknown translation provider: {key}") from exc

    async def capabilities(self, key: str, guild_id: int) -> TranslationProviderCapabilities:
        provider = self.get(key)
        capabilities = await provider.capabilities(guild_id)
        if (
            capabilities.configuration_mode
            is ProviderConfigurationMode.MANUAL_CONFIGURATION_REQUIRED
        ):
            return TranslationProviderCapabilities(
                supports_hub_and_spoke=capabilities.supports_hub_and_spoke,
                supports_full_mesh=capabilities.supports_full_mesh,
                supports_custom=capabilities.supports_custom,
                supports_message_edits=capabilities.supports_message_edits,
                supports_message_deletes=capabilities.supports_message_deletes,
                supports_attachments=capabilities.supports_attachments,
                supports_embeds=capabilities.supports_embeds,
                supports_threads=capabilities.supports_threads,
                requires_message_content=capabilities.requires_message_content,
                max_languages_per_group=capabilities.max_languages_per_group,
                configuration_mode=ProviderConfigurationMode.MANUAL_CONFIGURATION_REQUIRED,
                supports_automatic_configuration=capabilities.supports_automatic_configuration,
                requires_manual_configuration=True,
                health=capabilities.health,
                discord_bot_present=capabilities.discord_bot_present,
                bot_permissions=capabilities.bot_permissions,
            )
        return capabilities


def compile_scope_language_roles(
    *,
    guild_id: int,
    scope_id: UUID,
    member_language_ids: Iterable[UUID],
    visibility_policy: VisibilityPolicy,
) -> ScopeLanguageRoleDecision:
    if guild_id <= 0:
        raise ValueError("guild_id must be positive")
    if visibility_policy in {
        VisibilityPolicy.OPEN_ALL,
        VisibilityPolicy.LANGUAGE_FILTERED,
        VisibilityPolicy.CUSTOM,
    }:
        return ScopeLanguageRoleDecision(
            guild_id=guild_id,
            scope_id=scope_id,
            visibility_policy=visibility_policy,
            requires_explicit_binding=False,
            required_bindings=(),
        )
    ordered_languages = tuple(dict.fromkeys(member_language_ids))
    if not ordered_languages:
        return ScopeLanguageRoleDecision(
            guild_id=guild_id,
            scope_id=scope_id,
            visibility_policy=visibility_policy,
            requires_explicit_binding=False,
            required_bindings=(),
        )
    return ScopeLanguageRoleDecision(
        guild_id=guild_id,
        scope_id=scope_id,
        visibility_policy=visibility_policy,
        requires_explicit_binding=True,
        required_bindings=tuple(
            ScopeLanguageBinding(
                guild_id=guild_id,
                scope_id=scope_id,
                language_profile_id=language_profile_id,
            )
            for language_profile_id in ordered_languages
        ),
    )


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
    supports_message_edits: bool = False
    supports_message_deletes: bool = False
    supports_attachments: bool = False
    supports_embeds: bool = False
    supports_threads: bool = False
    requires_message_content: bool = False
    max_languages_per_group: int | None = None
    configuration_mode: ProviderConfigurationMode = ProviderConfigurationMode.OBSERVATION_ONLY
    supports_automatic_configuration: bool = False
    requires_manual_configuration: bool = False
    health: str = TranslationProviderStatus.UNKNOWN.value
    discord_bot_present: bool = False
    bot_permissions: tuple[str, ...] = ()

    def support_for(self, topology: TranslationGroupTopology) -> CapabilitySupport:
        supported = {
            TranslationGroupTopology.HUB_AND_SPOKE: self.supports_hub_and_spoke,
            TranslationGroupTopology.FULL_MESH: self.supports_full_mesh,
            TranslationGroupTopology.CUSTOM: self.supports_custom,
        }[topology]
        if supported:
            return CapabilitySupport.SUPPORTED
        # A negative boolean is deliberately not treated as authoritative.  An
        # adapter must advertise a known healthy capability set before a
        # routing mode can be enabled; this keeps FULL_MESH fail-closed.
        if self.health == TranslationProviderStatus.READY.value:
            return CapabilitySupport.UNSUPPORTED
        return CapabilitySupport.UNKNOWN

    def is_capable_for(self, topology: TranslationGroupTopology) -> bool:
        return self.support_for(topology) is CapabilitySupport.SUPPORTED


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
        channel_policy: ResourceLanguagePolicy | None = None,
    ) -> tuple[UUID | None, str]:
        if channel_language is not None:
            if not channel_language.enabled:
                return None, EffectiveLanguageSource.NONE.value
            return channel_language.id, EffectiveLanguageSource.SELF.value
        if channel_policy is not None and not channel_policy.inherit_language:
            return None, EffectiveLanguageSource.NONE.value
        if category_language is not None and category_language.enabled:
            return category_language.id, EffectiveLanguageSource.CATEGORY.value
        return None, EffectiveLanguageSource.NONE.value


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
        mapped_group_id = route.get("translation_group_id")
        if not isinstance(source, UUID) or not isinstance(destination, UUID):
            raise RouteValidationError(f"route[{index}] missing valid language ids")
        if mapped_group_id != group_id:
            raise RouteValidationError(
                f"route[{index}] declares translation_group_id={mapped_group_id} but expected "
                f"{group_id}"
            )
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
                if item.get("guild_id") == guild_id
                and item.get("translation_group_id") == group_id
                and item.get("language_profile_id") == source
            ),
            None,
        )
        destination_variant = next(
            (
                item
                for item in variants.values()
                if item.get("guild_id") == guild_id
                and item.get("translation_group_id") == group_id
                and item.get("language_profile_id") == destination
            ),
            None,
        )
        if source_variant is None or destination_variant is None:
            raise RouteValidationError(
                f"route[{index}] points to a missing variant for translation_group_id={group_id}"
            )
        if (
            int(source_variant.get("guild_id", -1)) != guild_id
            or int(destination_variant.get("guild_id", -1)) != guild_id
            or source_variant.get("translation_group_id") != group_id
            or destination_variant.get("translation_group_id") != group_id
        ):
            raise RouteValidationError(f"route[{index}] crosses a tenant or group boundary")
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
