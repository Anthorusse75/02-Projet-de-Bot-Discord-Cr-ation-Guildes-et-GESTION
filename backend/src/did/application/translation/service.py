from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from did.domain.translation_topology import (
    CapabilitySupport,
    LanguageProfile,
    ProviderConfigurationMode,
    ResourceLanguagePolicy,
    ResourceLanguageResolver,
    TranslationGroupTopology,
    TranslationProvider,
    TranslationProviderCapabilities,
    TranslationProviderStatus,
    VisibilityPolicy,
)
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    ResourceLanguagePolicyRepository,
    TranslationGroupRepository,
    TranslationProviderBindingRepository,
    VisibilityScopeLanguageRepository,
)

VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
EMBED_LINKS = 1 << 14
ATTACH_FILES = 1 << 15
READ_MESSAGE_HISTORY = 1 << 16
ADMINISTRATOR = 1 << 3
SEND_MESSAGES_IN_THREADS = 1 << 38

DISCORD_ROLE_LIMIT = 250
DISCORD_OVERWRITE_LIMIT = 1000


@dataclass(frozen=True, slots=True)
class DiscordOverwrite:
    target_type: str
    target_id: int
    allow: int
    deny: int


@dataclass(frozen=True, slots=True)
class TechnicalRoleSpec:
    scope_id: UUID | None
    language_profile_id: UUID
    name: str
    permissions: int = 0
    hoist: bool = False
    mentionable: bool = False


@dataclass(frozen=True, slots=True)
class VisibilityCompilation:
    policy: VisibilityPolicy
    overwrites: tuple[DiscordOverwrite, ...]
    roles_to_create: tuple[TechnicalRoleSpec, ...] = ()
    reused_role_ids: tuple[int, ...] = ()
    custom_semantics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CapacityDecision:
    current: int
    proposed_delta: int
    reuse_count: int
    limit: int
    projected: int
    remaining: int
    allowed: bool
    error_code: str | None = None


class RoleCapacityEngine:
    def role_budget(
        self,
        *,
        current_count: int,
        required_bindings: int,
        reusable_bindings: int,
        limit: int = DISCORD_ROLE_LIMIT,
    ) -> CapacityDecision:
        if min(current_count, required_bindings, reusable_bindings) < 0:
            raise ValueError("capacity counts cannot be negative")
        if reusable_bindings > required_bindings:
            raise ValueError("reusable bindings cannot exceed required bindings")
        delta = required_bindings - reusable_bindings
        projected = current_count + delta
        return CapacityDecision(
            current=current_count,
            proposed_delta=delta,
            reuse_count=reusable_bindings,
            limit=limit,
            projected=projected,
            remaining=max(0, limit - projected),
            allowed=projected <= limit,
            error_code=None if projected <= limit else "ROLE_CAPACITY_EXCEEDED",
        )

    def overwrite_budget(
        self,
        *,
        current_count: int,
        proposed_delta: int,
        limit: int = DISCORD_OVERWRITE_LIMIT,
    ) -> CapacityDecision:
        if current_count < 0:
            raise ValueError("current overwrite count cannot be negative")
        projected = current_count + proposed_delta
        return CapacityDecision(
            current=current_count,
            proposed_delta=proposed_delta,
            reuse_count=0,
            limit=limit,
            projected=projected,
            remaining=max(0, limit - projected),
            allowed=0 <= projected <= limit,
            error_code=(None if 0 <= projected <= limit else "OVERWRITE_CAPACITY_EXCEEDED"),
        )


class LanguageVisibilityCompiler:
    """Compile exact role overwrites without pretending Discord supports role AND."""

    def compile(
        self,
        *,
        policy: VisibilityPolicy,
        guild_id: int,
        language_profile_id: UUID | None,
        scope_id: UUID | None,
        binding_role_id: int | None,
        custom_policy: dict[str, Any] | None = None,
    ) -> VisibilityCompilation:
        if guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if policy is VisibilityPolicy.OPEN_ALL:
            return VisibilityCompilation(policy, ())
        if policy is VisibilityPolicy.CUSTOM:
            custom = custom_policy or {}
            raw = custom.get("overwrites")
            if not isinstance(raw, list):
                raise ValueError("CUSTOM visibility requires explicit overwrites")
            overwrites = tuple(self._custom_overwrite(item) for item in raw)
            return VisibilityCompilation(policy, overwrites, custom_semantics=custom)
        if language_profile_id is None:
            raise ValueError("language-filtered visibility requires an enabled language")
        if policy is VisibilityPolicy.LANGUAGE_FILTERED:
            role_spec = TechnicalRoleSpec(
                scope_id=None,
                language_profile_id=language_profile_id,
                name=f"DID·LANG·{str(language_profile_id)[:8]}",
            )
        else:
            if scope_id is None:
                raise ValueError("scope-and-language visibility requires an explicit scope")
            role_spec = TechnicalRoleSpec(
                scope_id=scope_id,
                language_profile_id=language_profile_id,
                name=f"DID·{str(scope_id)[:8]}·{str(language_profile_id)[:8]}",
            )
        if binding_role_id is None:
            return VisibilityCompilation(policy, (), roles_to_create=(role_spec,))
        # @everyone deny + exactly one derived audience role allow.  For
        # SCOPE_AND_LANGUAGE this derived role is the materialized intersection.
        return VisibilityCompilation(
            policy,
            (
                DiscordOverwrite("ROLE", guild_id, 0, VIEW_CHANNEL),
                DiscordOverwrite("ROLE", binding_role_id, VIEW_CHANNEL, 0),
            ),
            reused_role_ids=(binding_role_id,),
        )

    @staticmethod
    def _custom_overwrite(value: Any) -> DiscordOverwrite:
        if not isinstance(value, dict):
            raise ValueError("custom overwrite must be an object")
        target_type = str(value.get("target_type", ""))
        target_id = int(value.get("target_id", 0))
        allow = int(value.get("allow", 0))
        deny = int(value.get("deny", 0))
        if target_type not in {"ROLE", "MEMBER"} or target_id <= 0 or min(allow, deny) < 0:
            raise ValueError("invalid custom overwrite")
        return DiscordOverwrite(target_type, target_id, allow, deny)


class MemberTechnicalRoleReconciler:
    def desired_roles(
        self,
        *,
        member_scope_ids: set[UUID],
        visible_language_ids: set[UUID],
        required_pairs: set[tuple[UUID, UUID]],
        role_bindings: dict[tuple[UUID, UUID], int],
    ) -> frozenset[int]:
        # Language choices never add a business scope.  We intersect only with
        # memberships already resolved by the Stage04 ScopeMembershipResolver.
        desired_pairs = {
            (scope_id, language_id)
            for scope_id in member_scope_ids
            for language_id in visible_language_ids
            if (scope_id, language_id) in required_pairs
        }
        return frozenset(role_bindings[pair] for pair in desired_pairs if pair in role_bindings)

    def diff(self, *, current_role_ids: set[int], desired_role_ids: set[int]) -> dict[str, Any]:
        return {
            "assign": sorted(desired_role_ids - current_role_ids),
            "remove": sorted(current_role_ids - desired_role_ids),
            "member_specific_overwrites": [],
            "all_languages_role": None,
        }


class RoleOptimizer:
    """Choose reusable bindings and prove safe cleanup candidates."""

    def optimize(
        self,
        *,
        required_pairs: set[tuple[UUID, UUID]],
        existing_bindings: dict[tuple[UUID, UUID], int],
        referenced_role_ids: set[int],
        member_role_ids: set[int],
    ) -> dict[str, Any]:
        reused = {
            pair: role_id for pair, role_id in existing_bindings.items() if pair in required_pairs
        }
        create = sorted(required_pairs - set(reused), key=lambda pair: (str(pair[0]), str(pair[1])))
        unused = set(existing_bindings) - required_pairs
        cleanup = sorted(
            existing_bindings[pair]
            for pair in unused
            if existing_bindings[pair] not in referenced_role_ids
            and existing_bindings[pair] not in member_role_ids
        )
        return {
            "reuse": reused,
            "create": create,
            "cleanup_role_ids": cleanup,
            "cleanup_requires_plan": bool(cleanup),
        }


class TranslationRouteCompiler:
    def compile(
        self,
        *,
        topology: TranslationGroupTopology,
        language_ids: tuple[UUID, ...],
        hub_language_id: UUID | None,
        custom_routes: tuple[tuple[UUID, UUID], ...],
        capabilities: TranslationProviderCapabilities,
    ) -> tuple[tuple[UUID, UUID], ...]:
        if capabilities.support_for(topology) is not CapabilitySupport.SUPPORTED:
            raise ValueError("PROVIDER_CAPABILITY_UNKNOWN_OR_UNSUPPORTED")
        if capabilities.max_languages_per_group is not None and (
            len(language_ids) > capabilities.max_languages_per_group
        ):
            raise ValueError("PROVIDER_LANGUAGE_LIMIT_EXCEEDED")
        if topology is TranslationGroupTopology.CUSTOM:
            return self._validate(custom_routes, language_ids)
        if topology is TranslationGroupTopology.HUB_AND_SPOKE:
            if hub_language_id not in language_ids:
                raise ValueError("hub language must belong to the group")
            routes = tuple(
                route
                for language_id in language_ids
                if language_id != hub_language_id
                for route in ((hub_language_id, language_id), (language_id, hub_language_id))
            )
            return self._validate(routes, language_ids)
        routes = tuple(
            (source, destination)
            for source in language_ids
            for destination in language_ids
            if source != destination
        )
        return self._validate(routes, language_ids)

    @staticmethod
    def _validate(
        routes: tuple[tuple[UUID, UUID], ...], language_ids: tuple[UUID, ...]
    ) -> tuple[tuple[UUID, UUID], ...]:
        allowed = set(language_ids)
        if len(set(routes)) != len(routes):
            raise ValueError("translation routes must be unique")
        if any(
            source == destination or source not in allowed or destination not in allowed
            for source, destination in routes
        ):
            raise ValueError("translation route references an invalid language")
        return routes


@dataclass(frozen=True, slots=True)
class ProviderAccessPreflight:
    allowed: bool
    state: str
    missing_permissions: tuple[str, ...]
    warnings: tuple[str, ...]
    required_permissions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderConfigurationResult:
    state: TranslationProviderStatus
    instructions: tuple[str, ...]
    verification_state: str
    payload: dict[str, Any] = field(default_factory=dict)


class TranslationProviderCoordinator:
    def access_preflight(
        self,
        *,
        bot_present: bool,
        effective_permissions_by_variant: dict[int, int],
        require_threads: bool = False,
        require_embeds: bool = False,
        require_attachments: bool = False,
    ) -> ProviderAccessPreflight:
        required = {"VIEW_CHANNEL", "READ_MESSAGE_HISTORY", "SEND_MESSAGES"}
        if require_threads:
            required.add("SEND_MESSAGES_IN_THREADS")
        if require_embeds:
            required.add("EMBED_LINKS")
        if require_attachments:
            required.add("ATTACH_FILES")
        if not bot_present:
            return ProviderAccessPreflight(
                False, "NOT_INSTALLED", tuple(sorted(required)), (), tuple(sorted(required))
            )
        bit_by_name = {
            "VIEW_CHANNEL": VIEW_CHANNEL,
            "READ_MESSAGE_HISTORY": READ_MESSAGE_HISTORY,
            "SEND_MESSAGES": SEND_MESSAGES,
            "SEND_MESSAGES_IN_THREADS": SEND_MESSAGES_IN_THREADS,
            "EMBED_LINKS": EMBED_LINKS,
            "ATTACH_FILES": ATTACH_FILES,
        }
        missing = {
            name
            for permissions in effective_permissions_by_variant.values()
            for name in required
            if not permissions & bit_by_name[name]
        }
        warnings = (
            ("PROVIDER_HAS_ADMINISTRATOR",)
            if any(value & ADMINISTRATOR for value in effective_permissions_by_variant.values())
            else ()
        )
        return ProviderAccessPreflight(
            not missing,
            "ACCESS_READY" if not missing else "MISSING_PERMISSIONS",
            tuple(sorted(missing)),
            warnings,
            tuple(sorted(required)),
        )

    async def prepare(
        self,
        *,
        provider: TranslationProvider,
        guild_id: int,
        desired_group: dict[str, Any],
    ) -> ProviderConfigurationResult:
        capabilities = await provider.capabilities(guild_id)
        if capabilities.configuration_mode is not ProviderConfigurationMode.AUTOMATIC:
            prepared = await provider.prepare_configuration(desired_group)
            raw_instructions = prepared.get("instructions", ())
            instructions = tuple(str(item) for item in raw_instructions)
            return ProviderConfigurationResult(
                TranslationProviderStatus.MANUAL_CONFIGURATION_REQUIRED,
                instructions,
                "PENDING_MANUAL_VERIFICATION",
                self._without_secrets(prepared),
            )
        problems = await provider.validate_group(desired_group)
        if problems:
            return ProviderConfigurationResult(
                TranslationProviderStatus.ERROR,
                (),
                "VALIDATION_FAILED",
                {"problems": problems},
            )
        prepared = self._without_secrets(await provider.prepare_configuration(desired_group))
        return ProviderConfigurationResult(
            TranslationProviderStatus.UNKNOWN,
            (),
            "PREPARED_NOT_VERIFIED",
            prepared,
        )

    @classmethod
    def _without_secrets(cls, value: Any) -> Any:
        forbidden = {"token", "secret", "credential", "config_encrypted"}
        if isinstance(value, dict):
            return {
                str(key): cls._without_secrets(item)
                for key, item in value.items()
                if str(key).lower() not in forbidden
            }
        if isinstance(value, list | tuple):
            return [cls._without_secrets(item) for item in value]
        return value


class TranslationDriftDetector:
    def observe_variant(
        self,
        *,
        current_state: str,
        evidence: str,
        discord_resource_present: bool | None,
    ) -> dict[str, Any]:
        sufficient_missing_evidence = evidence in {
            "GATEWAY_DELETE",
            "DID_DELETE_CONFIRMED",
            "USER_CONFIRMED_DELETED",
        }
        if discord_resource_present is False and sufficient_missing_evidence:
            return {"state": "MISSING", "drift": "MISSING_VARIANT", "repair": "PLAN_REQUIRED"}
        if discord_resource_present is False:
            return {"state": current_state, "drift": "OBSERVABILITY_UNCERTAIN", "repair": None}
        return {"state": current_state, "drift": None, "repair": None}


@dataclass(frozen=True, slots=True)
class PortableProviderRequirement:
    """Allowlisted provider metadata that is safe to serialize and transfer."""

    provider_type: str
    required_capabilities: tuple[str, ...] = ()
    configuration_mode: str = "MANUAL_CONFIGURATION_REQUIRED"
    requires_message_content: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> PortableProviderRequirement:
        _reject_secret_material(value)
        allowed = {
            "provider_type",
            "type",
            "required_capabilities",
            "configuration_mode",
            "requires_message_content",
        }
        unknown = {str(key) for key in value} - allowed
        if unknown:
            raise ValueError("unsupported portable provider requirement fields")
        provider_type = str(value.get("provider_type") or value.get("type") or "").strip()
        if not provider_type:
            raise ValueError("portable provider_type must be present")
        raw_capabilities = value.get("required_capabilities", ())
        if not isinstance(raw_capabilities, list | tuple):
            raise ValueError("required_capabilities must be an array")
        capabilities = tuple(dict.fromkeys(str(item).strip() for item in raw_capabilities))
        if any(not item for item in capabilities):
            raise ValueError("required_capabilities cannot contain empty values")
        return cls(
            provider_type=provider_type,
            required_capabilities=capabilities,
            configuration_mode=str(
                value.get("configuration_mode", "MANUAL_CONFIGURATION_REQUIRED")
            ),
            requires_message_content=bool(value.get("requires_message_content", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_type": self.provider_type,
            "required_capabilities": list(self.required_capabilities),
            "configuration_mode": self.configuration_mode,
            "requires_message_content": self.requires_message_content,
        }


@dataclass(frozen=True, slots=True)
class PortableTranslationGroup:
    """Portable translation metadata without provider bindings or opaque configuration."""

    source_logical_id: str
    languages: tuple[str, ...]
    name: str | None = None
    root_kind: str | None = None
    routing_mode: str | None = None
    visibility_policy: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> PortableTranslationGroup:
        _reject_secret_material(value)
        source_id = str(value.get("logical_id") or value.get("id") or "").strip()
        if not source_id:
            raise ValueError("portable translation group requires a logical id")
        raw_languages = value.get("languages", ())
        if not isinstance(raw_languages, list | tuple):
            raise ValueError("portable translation group languages must be an array")
        return cls(
            source_logical_id=source_id,
            languages=tuple(dict.fromkeys(str(item) for item in raw_languages)),
            name=str(value["name"]) if value.get("name") is not None else None,
            root_kind=str(value["root_kind"]) if value.get("root_kind") is not None else None,
            routing_mode=(
                str(value["routing_mode"]) if value.get("routing_mode") is not None else None
            ),
            visibility_policy=(
                str(value["visibility_policy"])
                if value.get("visibility_policy") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "logical_id": self.source_logical_id,
            "languages": list(self.languages),
        }
        for key in ("name", "root_kind", "routing_mode", "visibility_policy"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result


def _reject_secret_material(value: Any) -> None:
    secret_keys = {
        "token",
        "accesstoken",
        "refreshtoken",
        "secret",
        "clientsecret",
        "apisecret",
        "providersecret",
        "apikey",
        "credential",
        "credentials",
        "authorization",
        "password",
        "configencrypted",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = "".join(
                character for character in str(key).lower() if character.isalnum()
            )
            if (
                normalized in secret_keys
                or normalized.endswith("token")
                or normalized.endswith("secret")
            ):
                raise ValueError("secret-bearing fields are forbidden in portable artifacts")
            _reject_secret_material(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _reject_secret_material(item)


@dataclass(frozen=True, slots=True)
class MultilingualPortableArtifact:
    schema_version: str
    source_guild_id: int
    languages: tuple[str, ...]
    groups: tuple[PortableTranslationGroup, ...]
    provider_requirements: tuple[PortableProviderRequirement, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_guild_id": str(self.source_guild_id),
            "multilingual": {
                "languages": list(self.languages),
                "translation_groups": [group.to_dict() for group in self.groups],
                "provider_requirements": [item.to_dict() for item in self.provider_requirements],
            },
        }


class TranslationCloneExpander:
    def export(
        self,
        *,
        source_guild_id: int,
        languages: tuple[str, ...],
        groups: tuple[dict[str, Any], ...],
        provider_requirements: tuple[dict[str, Any], ...] = (),
    ) -> MultilingualPortableArtifact:
        safe_requirements = tuple(
            PortableProviderRequirement.from_mapping(value) for value in provider_requirements
        )
        safe_groups = tuple(PortableTranslationGroup.from_mapping(value) for value in groups)
        return MultilingualPortableArtifact(
            "did-portable-multilingual-v1",
            source_guild_id,
            tuple(dict.fromkeys(languages)),
            safe_groups,
            safe_requirements,
        )

    def expand_for_destination(
        self, *, artifact: MultilingualPortableArtifact, destination_guild_id: int
    ) -> dict[str, Any]:
        if destination_guild_id <= 0 or destination_guild_id == artifact.source_guild_id:
            raise ValueError("multilingual clone requires a distinct positive destination guild")
        mappings = []
        for group in artifact.groups:
            source_id = group.source_logical_id
            mappings.append(
                {
                    "source_logical_id": source_id,
                    "destination_translation_group_id": str(uuid4()),
                    "destination_guild_id": str(destination_guild_id),
                    "live_source_link": False,
                }
            )
        return {
            "pipeline": [
                "PORTABLE_SNAPSHOT",
                "LANGUAGE_EXPANSION",
                "DEPENDENCY_GRAPH",
                "VISIBILITY_RESOLVER",
                "TRANSLATION_TOPOLOGY",
                "PREFLIGHT",
                "DESTINATION_PLAN",
            ],
            "destination_guild_id": str(destination_guild_id),
            "group_mappings": mappings,
            "provider_bindings_omitted": True,
            "source_unchanged": True,
        }


class LanguageProfileService:
    def __init__(
        self,
        profiles: LanguageProfileRepository,
        policies: ResourceLanguagePolicyRepository,
    ) -> None:
        self._profiles = profiles
        self._policies = policies
        self._resolver = ResourceLanguageResolver()

    async def list_profiles(self, *, guild_id: int) -> list[dict[str, Any]]:
        return await self._profiles.list_profiles(guild_id)

    async def member_languages(
        self, *, guild_id: int, discord_user_id: int
    ) -> list[dict[str, Any]]:
        return await self._profiles.member_languages(guild_id, discord_user_id)

    async def resource_policies(self, *, guild_id: int) -> list[dict[str, Any]]:
        return await self._policies.list_policies(guild_id)

    async def upsert_resource_policy(
        self,
        *,
        guild_id: int,
        resource_type: str,
        discord_resource_id: int,
        explicit_language_profile_id: UUID | None,
        inherit_language: bool,
        visibility_policy: str,
        visibility_scope_id: UUID | None,
        custom_policy: dict[str, Any],
    ) -> dict[str, Any]:
        if explicit_language_profile_id is not None:
            profile = await self._profiles.get(guild_id, explicit_language_profile_id)
            if not bool(profile["enabled"]):
                raise ValueError("resource language must reference an enabled profile")
        return await self._policies.upsert(
            guild_id=guild_id,
            resource_type=resource_type,
            discord_resource_id=discord_resource_id,
            explicit_language_profile_id=explicit_language_profile_id,
            inherit_language=inherit_language,
            visibility_policy=visibility_policy,
            visibility_scope_id=visibility_scope_id,
            custom_policy=custom_policy,
        )

    async def create(
        self, *, guild_id: int, code: str, display_name: str, emoji: str | None = None
    ) -> dict[str, Any]:
        return await self._profiles.create(
            guild_id=guild_id,
            code=self._canonical_code(code),
            display_name=display_name.strip(),
            emoji=emoji,
        )

    async def update(
        self,
        *,
        guild_id: int,
        language_id: UUID,
        display_name: str | None = None,
        emoji: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        return await self._profiles.update(
            guild_id=guild_id,
            language_id=language_id,
            display_name=display_name,
            emoji=emoji,
            enabled=enabled,
        )

    async def set_member_languages(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        language_ids: tuple[UUID, ...],
        source: str,
    ) -> list[dict[str, Any]]:
        enabled = {
            row["id"] for row in await self._profiles.list_profiles(guild_id, enabled_only=True)
        }
        if any(language_id not in enabled for language_id in language_ids):
            raise ValueError("member languages must reference enabled tenant profiles")
        await self._profiles.set_member_languages(
            guild_id=guild_id,
            discord_user_id=discord_user_id,
            language_profile_ids=language_ids,
            source=source,
        )
        return await self._profiles.member_languages(guild_id, discord_user_id)

    async def add_member_language(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        language_id: UUID,
        source: str,
    ) -> list[dict[str, Any]]:
        profile = await self._profiles.get(guild_id, language_id)
        if not bool(profile["enabled"]):
            raise ValueError("member language must reference an enabled tenant profile")
        await self._profiles.add_member_language(
            guild_id=guild_id,
            discord_user_id=discord_user_id,
            language_profile_id=language_id,
            source=source,
        )
        return await self._profiles.member_languages(guild_id, discord_user_id)

    async def remove_member_language(
        self, *, guild_id: int, discord_user_id: int, language_id: UUID
    ) -> list[dict[str, Any]]:
        await self._profiles.remove_member_language(
            guild_id=guild_id,
            discord_user_id=discord_user_id,
            language_profile_id=language_id,
        )
        return await self._profiles.member_languages(guild_id, discord_user_id)

    async def resolve_resource_language(
        self,
        *,
        guild_id: int,
        channel_id: int,
        category_id: int | None,
    ) -> dict[str, Any]:
        channel_policy = await self._policies.get_optional(guild_id, "CHANNEL", channel_id)
        category_policy = (
            await self._policies.get_optional(guild_id, "CATEGORY", category_id)
            if category_id is not None
            else None
        )
        channel_language = await self._profile_from_policy(guild_id, channel_policy)
        category_language = await self._profile_from_policy(guild_id, category_policy)
        domain_policy = self._policy_model(channel_policy) if channel_policy else None
        language_id, source = self._resolver.resolve(
            channel_language=channel_language,
            category_language=category_language,
            channel_policy=domain_policy,
        )
        return {
            "language_profile_id": str(language_id) if language_id else None,
            "source": source,
            "disabled_or_missing": language_id is None
            and (channel_language is not None or category_language is not None),
        }

    async def _profile_from_policy(
        self, guild_id: int, policy: dict[str, Any] | None
    ) -> LanguageProfile | None:
        if policy is None or policy.get("explicit_language_profile_id") is None:
            return None
        row = await self._profiles.get_optional(
            guild_id, UUID(str(policy["explicit_language_profile_id"]))
        )
        return self._profile_model(row) if row else None

    @staticmethod
    def _profile_model(row: dict[str, Any]) -> LanguageProfile:
        return LanguageProfile(
            id=UUID(str(row["id"])),
            guild_id=int(row["guild_id"]),
            code=str(row["code"]),
            display_name=str(row["display_name"]),
            enabled=bool(row["enabled"]),
        )

    @staticmethod
    def _policy_model(row: dict[str, Any]) -> ResourceLanguagePolicy:
        return ResourceLanguagePolicy(
            id=UUID(str(row["id"])),
            guild_id=int(row["guild_id"]),
            resource_type=str(row["resource_type"]),
            discord_resource_id=int(row["discord_resource_id"]),
            explicit_language_profile_id=(
                UUID(str(row["explicit_language_profile_id"]))
                if row.get("explicit_language_profile_id")
                else None
            ),
            inherit_language=bool(row["inherit_language"]),
            visibility_policy=VisibilityPolicy(str(row["visibility_policy"])),
            visibility_scope_id=(
                UUID(str(row["visibility_scope_id"])) if row.get("visibility_scope_id") else None
            ),
            custom_policy_json=dict(row.get("custom_policy_json") or {}),
        )

    @staticmethod
    def _canonical_code(code: str) -> str:
        parts = code.strip().replace("_", "-").split("-")
        if not parts or not parts[0].isalpha() or not 2 <= len(parts[0]) <= 8:
            raise ValueError("language code must be a canonical BCP 47-like tag")
        normalized = [parts[0].lower()]
        for part in parts[1:]:
            if not part.isalnum() or not 1 <= len(part) <= 8:
                raise ValueError("language code must be a canonical BCP 47-like tag")
            normalized.append(part.upper() if len(part) == 2 and part.isalpha() else part)
        return "-".join(normalized)


class TranslationTopologyService:
    def __init__(
        self,
        groups: TranslationGroupRepository,
        providers: TranslationProviderBindingRepository,
        visibility: VisibilityScopeLanguageRepository,
    ) -> None:
        self._groups = groups
        self._providers = providers
        self._visibility = visibility

    async def create_group(
        self,
        *,
        guild_id: int,
        name: str,
        root_kind: str,
        routing_mode: str,
        language_ids: tuple[UUID, ...],
        visibility_scope_id: UUID | None,
        source_language_profile_id: UUID | None,
        provider_binding_id: UUID | None,
    ) -> dict[str, Any]:
        if (
            source_language_profile_id is not None
            and source_language_profile_id not in language_ids
        ):
            raise ValueError("source language must belong to the translation group")
        unique_language_ids = tuple(dict.fromkeys(language_ids))
        group = await self._groups.create_with_languages(
            guild_id=guild_id,
            name=name.strip(),
            root_kind=root_kind,
            routing_mode=routing_mode,
            language_profile_ids=unique_language_ids,
            visibility_scope_id=visibility_scope_id,
            source_language_profile_id=source_language_profile_id,
            provider_binding_id=provider_binding_id,
        )
        return await self._groups.get(guild_id, UUID(str(group["id"])))

    async def get_group(self, *, guild_id: int, group_id: UUID) -> dict[str, Any]:
        return await self._groups.get(guild_id, group_id)

    async def rename_group(
        self, *, guild_id: int, group_id: UUID, expected_version: int, name: str
    ) -> dict[str, Any]:
        return await self._groups.update_name(
            guild_id=guild_id,
            group_id=group_id,
            expected_version=expected_version,
            name=name.strip(),
        )

    async def link_existing_variant(
        self,
        *,
        guild_id: int,
        group_id: UUID,
        language_id: UUID,
        variant_type: str,
        discord_resource_id: int,
        confirmed_explicit_selection: bool,
        channel_group_id: UUID | None = None,
        category_variant_id: UUID | None = None,
    ) -> dict[str, Any]:
        if not confirmed_explicit_selection:
            raise ValueError("an existing Discord resource link requires explicit confirmation")
        await self._groups.get(guild_id, group_id)
        if variant_type == "CATEGORY":
            return await self._groups.create_category_variant(
                guild_id=guild_id,
                translation_group_id=group_id,
                language_profile_id=language_id,
                discord_category_id=discord_resource_id,
            )
        if variant_type == "CHANNEL" and channel_group_id is not None:
            await self._groups.get_channel_group(
                guild_id=guild_id,
                translation_group_id=group_id,
                channel_group_id=channel_group_id,
            )
            if category_variant_id is not None:
                await self._groups.get_variant(
                    guild_id=guild_id,
                    translation_group_id=group_id,
                    variant_id=category_variant_id,
                    variant_type="CATEGORY",
                )
            return await self._groups.create_channel_variant(
                guild_id=guild_id,
                translation_group_id=group_id,
                translation_channel_group_id=channel_group_id,
                language_profile_id=language_id,
                discord_channel_id=discord_resource_id,
                translation_category_variant_id=category_variant_id,
            )
        raise ValueError("channel links require an explicit translation channel group")

    async def create_channel_group(
        self,
        *,
        guild_id: int,
        group_id: UUID,
        logical_key: str,
        display_name: str | None,
        source_language_id: UUID | None,
    ) -> dict[str, Any]:
        await self._groups.get(guild_id, group_id)
        return await self._groups.create_channel_group(
            guild_id=guild_id,
            translation_group_id=group_id,
            logical_key=logical_key,
            display_name=display_name,
            source_language_profile_id=source_language_id,
        )

    async def rename_channel_group(
        self, *, guild_id: int, group_id: UUID, channel_group_id: UUID, display_name: str
    ) -> dict[str, Any]:
        await self._groups.get(guild_id, group_id)
        return await self._groups.rename_channel_group(
            guild_id=guild_id,
            translation_group_id=group_id,
            channel_group_id=channel_group_id,
            display_name=display_name.strip(),
        )

    async def replace_routes(
        self,
        *,
        guild_id: int,
        group_id: UUID,
        expected_version: int,
        topology: TranslationGroupTopology,
        language_ids: tuple[UUID, ...],
        hub_language_id: UUID | None,
        custom_routes: tuple[tuple[UUID, UUID], ...],
        capabilities: TranslationProviderCapabilities,
    ) -> dict[str, Any]:
        routes = TranslationRouteCompiler().compile(
            topology=topology,
            language_ids=language_ids,
            hub_language_id=hub_language_id,
            custom_routes=custom_routes,
            capabilities=capabilities,
        )
        group = await self._groups.replace_routes(
            guild_id=guild_id,
            group_id=group_id,
            expected_version=expected_version,
            routing_mode=topology.value,
            source_language_profile_id=hub_language_id,
            routes=routes,
        )
        return {**group, "routes": [[str(a), str(b)] for a, b in routes]}

    async def record_provider_status(
        self,
        *,
        guild_id: int,
        binding_id: UUID,
        status: TranslationProviderStatus,
        verified: bool,
    ) -> dict[str, Any]:
        return await self._providers.set_status(
            guild_id=guild_id,
            binding_id=binding_id,
            status=status.value,
            verified=verified,
        )

    async def observe_drift(
        self,
        *,
        guild_id: int,
        variant_id: UUID | None,
        variant_type: str | None,
        current_state: str,
        evidence: str,
        discord_resource_present: bool | None,
    ) -> dict[str, Any]:
        decision = TranslationDriftDetector().observe_variant(
            current_state=current_state,
            evidence=evidence,
            discord_resource_present=discord_resource_present,
        )
        if decision["state"] == "MISSING" and variant_id is not None and variant_type is not None:
            await self._groups.mark_variant_missing(
                guild_id=guild_id, variant_id=variant_id, variant_type=variant_type
            )
        return {**decision, "other_variants_unchanged": True, "automatic_deletion": False}

    async def workspace(self, guild_id: int) -> dict[str, Any]:
        return {
            "guild_id": str(guild_id),
            "source": "POSTGRESQL_DURABLE_TRUTH",
            "discord_rest_calls": 0,
            "groups": await self._groups.workspace(guild_id),
            "providers": await self._providers.list_bindings(guild_id),
            "visibility_bindings": await self._visibility.list_bindings(guild_id),
        }

    async def add_language_delta(
        self,
        *,
        guild_id: int,
        group_id: UUID,
        language_id: UUID,
        expected_version: int,
    ) -> dict[str, Any]:
        return await self._groups.add_language_delta(
            guild_id=guild_id,
            group_id=group_id,
            language_profile_id=language_id,
            expected_version=expected_version,
        )

    async def remove_language_non_destructive(
        self,
        *,
        guild_id: int,
        group_id: UUID,
        language_id: UUID,
        expected_version: int,
        destructive_discord_delete: bool,
    ) -> dict[str, Any]:
        if destructive_discord_delete:
            raise ValueError("Discord deletion requires a separately confirmed destructive plan")
        result = await self._groups.detach_language(
            guild_id=guild_id,
            group_id=group_id,
            language_profile_id=language_id,
            expected_version=expected_version,
        )
        return {**result, "discord_resources_deleted": False}

    async def unlink_variant(
        self, *, guild_id: int, group_id: UUID, variant_id: UUID, variant_type: str
    ) -> dict[str, Any]:
        row = await self._groups.detach_variant(
            guild_id=guild_id,
            translation_group_id=group_id,
            variant_id=variant_id,
            variant_type=variant_type,
        )
        return {**row, "discord_resource_deleted": False}
