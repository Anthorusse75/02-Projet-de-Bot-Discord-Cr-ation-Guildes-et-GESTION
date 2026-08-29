from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from did.api.dependencies import ApiProblem, CsrfSessionDep, CurrentSessionDep, ServicesDep
from did.api.guilds import parse_snowflake
from did.application.translation import (
    LanguageProfileService,
    LanguageVisibilityCompiler,
    MemberTechnicalRoleReconciler,
    RoleCapacityEngine,
    TranslationCloneExpander,
    TranslationProviderCoordinator,
    TranslationRouteCompiler,
    TranslationTopologyService,
)
from did.domain.auth import AuthorizationScope, Capability
from did.domain.translation_topology import (
    ProviderConfigurationMode,
    TranslationGroupTopology,
    TranslationProviderCapabilities,
    VisibilityPolicy,
)
from did.infrastructure.translation_provider import NonInvasiveExistingBotProvider
from did.planning import (
    DesiredNode,
    DesiredStateGraph,
    NodePresence,
    ReferenceKind,
    ResourceReference,
    ResourceType,
)

router = APIRouter(tags=["stage-08-multilingual-topology"])


class LanguageCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    emoji: str | None = Field(default=None, max_length=16)


class LanguageUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    emoji: str | None = Field(default=None, max_length=16)
    enabled: bool | None = None


class MemberLanguagesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language_profile_ids: list[UUID] = Field(default_factory=list, max_length=64)
    source: Literal["EXPLICIT", "ONBOARDING", "SYNC", "MANUAL"] = "EXPLICIT"


class MemberLanguageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language_profile_id: UUID
    source: Literal["EXPLICIT", "ONBOARDING", "SYNC", "MANUAL"] = "EXPLICIT"


class ResourcePolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_type: Literal["CATEGORY", "CHANNEL"]
    discord_resource_id: str
    explicit_language_profile_id: UUID | None = None
    inherit_language: bool = False
    visibility_policy: VisibilityPolicy = VisibilityPolicy.OPEN_ALL
    visibility_scope_id: UUID | None = None
    custom_policy: dict[str, Any] = Field(default_factory=dict)

    @field_validator("discord_resource_id")
    @classmethod
    def snowflake(cls, value: str) -> str:
        return str(parse_snowflake(value))


class TranslationGroupCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    root_kind: Literal["CATEGORY_SET", "CHANNEL_SET"]
    routing_mode: TranslationGroupTopology
    language_profile_ids: list[UUID] = Field(min_length=1, max_length=64)
    visibility_scope_id: UUID | None = None
    source_language_profile_id: UUID | None = None
    provider_binding_id: UUID | None = None


class GroupRenameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=128)


class GroupLanguageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    language_profile_id: UUID
    destructive_discord_delete: bool = False


class VariantUnlinkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant_id: UUID
    variant_type: Literal["CATEGORY", "CHANNEL"]
    delete_discord_resource: bool = False


class VariantLinkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language_profile_id: UUID
    variant_type: Literal["CATEGORY", "CHANNEL"]
    discord_resource_id: str
    confirmed_explicit_selection: bool
    translation_channel_group_id: UUID | None = None
    translation_category_variant_id: UUID | None = None

    @field_validator("discord_resource_id")
    @classmethod
    def resource_snowflake(cls, value: str) -> str:
        return str(parse_snowflake(value))


class ChannelGroupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logical_key: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    source_language_profile_id: UUID | None = None


class ChannelGroupRenameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=128)


class RouteCompileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topology: TranslationGroupTopology
    language_profile_ids: list[UUID] = Field(min_length=1, max_length=64)
    hub_language_profile_id: UUID | None = None
    custom_routes: list[tuple[UUID, UUID]] = Field(default_factory=list, max_length=4096)
    supports_hub_and_spoke: bool = False
    supports_full_mesh: bool = False
    supports_custom: bool = False
    provider_health: str = "UNKNOWN"
    max_languages_per_group: int | None = Field(default=None, ge=1)


class RouteReplaceInput(RouteCompileInput):
    expected_version: int = Field(ge=1)


class VisibilityCompileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: VisibilityPolicy
    language_profile_id: UUID | None = None
    visibility_scope_id: UUID | None = None
    binding_role_id: str | None = None
    custom_policy: dict[str, Any] = Field(default_factory=dict)

    @field_validator("binding_role_id")
    @classmethod
    def optional_snowflake(cls, value: str | None) -> str | None:
        return str(parse_snowflake(value)) if value is not None else None


class CapacityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_roles: int = Field(ge=0)
    required_bindings: int = Field(ge=0)
    reusable_bindings: int = Field(ge=0)
    current_overwrites: int = Field(ge=0)
    proposed_overwrite_delta: int


class MemberRoleReconcileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    member_scope_ids: list[UUID] = Field(default_factory=list, max_length=256)
    visible_language_ids: list[UUID] = Field(default_factory=list, max_length=64)
    required_pairs: list[tuple[UUID, UUID]] = Field(default_factory=list, max_length=4096)
    bindings: dict[str, str] = Field(default_factory=dict)
    current_role_ids: list[str] = Field(default_factory=list, max_length=250)


class ProviderAccessInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot_present: bool
    effective_permissions_by_variant: dict[str, str] = Field(default_factory=dict)
    require_threads: bool = False
    require_embeds: bool = False
    require_attachments: bool = False


class ProviderPrepareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    binding_id: UUID | None = None
    observed_capabilities: RouteCompileInput
    discord_bot_present: bool = False
    bot_permissions: list[str] = Field(default_factory=list, max_length=64)
    desired_group: dict[str, Any] = Field(default_factory=dict)


class DriftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_state: str = Field(min_length=1, max_length=32)
    evidence: str = Field(min_length=1, max_length=64)
    discord_resource_present: bool | None = None
    variant_id: UUID | None = None
    variant_type: Literal["CATEGORY", "CHANNEL"] | None = None


class MultilingualCloneInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination_guild_id: str
    languages: list[str] = Field(min_length=1, max_length=64)
    groups: list[dict[str, Any]] = Field(min_length=1, max_length=256)
    provider_requirements: list[dict[str, Any]] = Field(default_factory=list, max_length=64)

    @field_validator("destination_guild_id")
    @classmethod
    def destination_snowflake(cls, value: str) -> str:
        return str(parse_snowflake(value))


class StructuralPlanNodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logical_key: str = Field(min_length=1, max_length=256)
    resource_type: Literal["CATEGORY", "CHANNEL", "ROLE", "OVERWRITE"]
    properties: dict[str, Any] = Field(default_factory=dict)
    discord_id: str | None = None
    symbol: str | None = Field(default=None, max_length=256)
    presence: Literal["PRESENT", "ABSENT"] = "PRESENT"
    relations: dict[str, tuple[Literal["LOGICAL", "DISCORD_ID", "SYMBOL"], str]] = Field(
        default_factory=dict, max_length=8
    )

    @field_validator("discord_id")
    @classmethod
    def optional_id(cls, value: str | None) -> str | None:
        return str(parse_snowflake(value)) if value is not None else None


class StructuralPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[StructuralPlanNodeInput] = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(min_length=1, max_length=160)


def _correlation(request: Request) -> UUID:
    try:
        return UUID(str(request.state.correlation_id))
    except (AttributeError, ValueError):
        return uuid4()


async def _authorize(
    guild_id: int,
    session: Any,
    container: Any,
    capability: Capability,
    *,
    sensitive: bool = False,
) -> None:
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=guild_id,
        capability=capability,
        scope=AuthorizationScope.guild(),
        sensitive=sensitive,
    )


def _require(container: ServicesDep) -> tuple[LanguageProfileService, TranslationTopologyService]:
    if container.stage08_languages is None or container.stage08_topology is None:
        raise ApiProblem(
            status_code=503,
            code="STAGE08_NOT_CONFIGURED",
            message_key="errors.translations.notConfigured",
        )
    return container.stage08_languages, container.stage08_topology


async def _audit(
    container: Any,
    *,
    guild_id: int,
    actor_id: int,
    event_type: str,
    target_type: str,
    target_id: str,
    correlation_id: UUID,
    data: dict[str, Any] | None = None,
) -> None:
    await container.stage08_audit_repository.append(
        guild_id=guild_id,
        actor_user_id=actor_id,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        correlation_id=correlation_id,
        data=data,
    )


@router.get("/api/v1/guilds/{guild_id}/languages")
async def list_languages(
    guild_id: str, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_READ)
    languages, _ = _require(container)
    return {
        "guild_id": str(parsed),
        "source": "POSTGRESQL_DURABLE_TRUTH",
        "discord_rest_calls": 0,
        "languages": await languages.list_profiles(guild_id=parsed),
    }


@router.post("/api/v1/guilds/{guild_id}/languages", status_code=status.HTTP_201_CREATED)
async def create_language(
    guild_id: str,
    body: LanguageCreateInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    languages, _ = _require(container)
    row = await languages.create(guild_id=parsed, **body.model_dump())
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="LANGUAGE_PROFILE_CREATED",
        target_type="LANGUAGE_PROFILE",
        target_id=str(row["id"]),
        correlation_id=_correlation(request),
    )
    return row


@router.patch("/api/v1/guilds/{guild_id}/languages/{language_id}")
async def update_language(
    guild_id: str,
    language_id: UUID,
    body: LanguageUpdateInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    languages, _ = _require(container)
    row = await languages.update(guild_id=parsed, language_id=language_id, **body.model_dump())
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type=("LANGUAGE_PROFILE_ENABLED" if row["enabled"] else "LANGUAGE_PROFILE_DISABLED"),
        target_type="LANGUAGE_PROFILE",
        target_id=str(language_id),
        correlation_id=_correlation(request),
    )
    return row


@router.put("/api/v1/guilds/{guild_id}/members/{user_id}/languages")
async def set_member_languages(
    guild_id: str,
    user_id: str,
    body: MemberLanguagesInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    member_id = parse_snowflake(user_id)
    await _authorize(parsed, session, container, Capability.MEMBERS_WRITE, sensitive=True)
    languages, _ = _require(container)
    rows = await languages.set_member_languages(
        guild_id=parsed,
        discord_user_id=member_id,
        language_ids=tuple(body.language_profile_ids),
        source=body.source,
    )
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="MEMBER_LANGUAGE_CHANGED",
        target_type="MEMBER",
        target_id=str(member_id),
        correlation_id=_correlation(request),
        data={"language_count": len(rows), "source": body.source},
    )
    return {"guild_id": str(parsed), "discord_user_id": str(member_id), "languages": rows}


@router.get("/api/v1/guilds/{guild_id}/members/{user_id}/languages")
async def get_member_languages(
    guild_id: str, user_id: str, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    member_id = parse_snowflake(user_id)
    await _authorize(parsed, session, container, Capability.MEMBERS_READ)
    languages, _ = _require(container)
    return {
        "guild_id": str(parsed),
        "discord_user_id": str(member_id),
        "languages": await languages.member_languages(guild_id=parsed, discord_user_id=member_id),
        "primary_language": None,
    }


@router.post("/api/v1/guilds/{guild_id}/members/{user_id}/languages")
async def add_member_language(
    guild_id: str,
    user_id: str,
    body: MemberLanguageInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    member_id = parse_snowflake(user_id)
    await _authorize(parsed, session, container, Capability.MEMBERS_WRITE, sensitive=True)
    languages, _ = _require(container)
    rows = await languages.add_member_language(
        guild_id=parsed,
        discord_user_id=member_id,
        language_id=body.language_profile_id,
        source=body.source,
    )
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="MEMBER_LANGUAGE_ADDED",
        target_type="MEMBER",
        target_id=str(member_id),
        correlation_id=_correlation(request),
    )
    return {"guild_id": str(parsed), "discord_user_id": str(member_id), "languages": rows}


@router.delete("/api/v1/guilds/{guild_id}/members/{user_id}/languages/{language_profile_id}")
async def remove_member_language(
    guild_id: str,
    user_id: str,
    language_profile_id: UUID,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    member_id = parse_snowflake(user_id)
    await _authorize(parsed, session, container, Capability.MEMBERS_WRITE, sensitive=True)
    languages, _ = _require(container)
    rows = await languages.remove_member_language(
        guild_id=parsed,
        discord_user_id=member_id,
        language_id=language_profile_id,
    )
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="MEMBER_LANGUAGE_REMOVED",
        target_type="MEMBER",
        target_id=str(member_id),
        correlation_id=_correlation(request),
    )
    return {"guild_id": str(parsed), "discord_user_id": str(member_id), "languages": rows}


@router.put("/api/v1/guilds/{guild_id}/resource-language-policies")
async def upsert_resource_policy(
    guild_id: str,
    body: ResourcePolicyInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    languages, _ = _require(container)
    row = await languages.upsert_resource_policy(
        guild_id=parsed,
        resource_type=body.resource_type,
        discord_resource_id=int(body.discord_resource_id),
        explicit_language_profile_id=body.explicit_language_profile_id,
        inherit_language=body.inherit_language,
        visibility_policy=body.visibility_policy.value,
        visibility_scope_id=body.visibility_scope_id,
        custom_policy=body.custom_policy,
    )
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="RESOURCE_LANGUAGE_POLICY_CHANGED",
        target_type=body.resource_type,
        target_id=body.discord_resource_id,
        correlation_id=_correlation(request),
    )
    return row


@router.get("/api/v1/guilds/{guild_id}/resources/{channel_id}/effective-language")
async def effective_language(
    guild_id: str,
    channel_id: str,
    category_id: str | None,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_READ)
    languages, _ = _require(container)
    return await languages.resolve_resource_language(
        guild_id=parsed,
        channel_id=parse_snowflake(channel_id),
        category_id=parse_snowflake(category_id) if category_id else None,
    )


@router.get("/api/v1/guilds/{guild_id}/translation-workspace")
async def translation_workspace(
    guild_id: str, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_READ)
    languages, topology = _require(container)
    workspace = await topology.workspace(parsed)
    return {
        **workspace,
        "languages": await languages.list_profiles(guild_id=parsed),
        "resource_language_policies": await languages.resource_policies(guild_id=parsed),
    }


@router.get("/api/v1/guilds/{guild_id}/translation-groups")
async def list_translation_groups(
    guild_id: str, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    workspace = await translation_workspace(guild_id, session, container)
    return {"guild_id": workspace["guild_id"], "groups": workspace["groups"]}


@router.get("/api/v1/guilds/{guild_id}/translation-groups/{group_id}")
async def get_translation_group(
    guild_id: str, group_id: UUID, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_READ)
    _, topology = _require(container)
    return await topology.get_group(guild_id=parsed, group_id=group_id)


@router.post("/api/v1/guilds/{guild_id}/translation-groups", status_code=status.HTTP_201_CREATED)
async def create_translation_group(
    guild_id: str,
    body: TranslationGroupCreateInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    _, topology = _require(container)
    group = await topology.create_group(
        guild_id=parsed,
        name=body.name,
        root_kind=body.root_kind,
        routing_mode=body.routing_mode.value,
        language_ids=tuple(body.language_profile_ids),
        visibility_scope_id=body.visibility_scope_id,
        source_language_profile_id=body.source_language_profile_id,
        provider_binding_id=body.provider_binding_id,
    )
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="TRANSLATION_GROUP_CREATED",
        target_type="TRANSLATION_GROUP",
        target_id=str(group["id"]),
        correlation_id=_correlation(request),
    )
    return group


@router.patch("/api/v1/guilds/{guild_id}/translation-groups/{group_id}")
async def rename_translation_group(
    guild_id: str,
    group_id: UUID,
    body: GroupRenameInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    _, topology = _require(container)
    row = await topology.rename_group(
        guild_id=parsed,
        group_id=group_id,
        expected_version=body.expected_version,
        name=body.name,
    )
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="TRANSLATION_GROUP_RENAMED",
        target_type="TRANSLATION_GROUP",
        target_id=str(group_id),
        correlation_id=_correlation(request),
    )
    return row


@router.post("/api/v1/guilds/{guild_id}/translation-groups/{group_id}/languages")
async def add_group_language(
    guild_id: str,
    group_id: UUID,
    body: GroupLanguageInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    _, topology = _require(container)
    row = await topology.add_language_delta(
        guild_id=parsed,
        group_id=group_id,
        language_id=body.language_profile_id,
        expected_version=body.expected_version,
    )
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="TRANSLATION_LANGUAGE_ADDED",
        target_type="TRANSLATION_GROUP",
        target_id=str(group_id),
        correlation_id=_correlation(request),
        data={"delta_only": True},
    )
    return row


@router.delete("/api/v1/guilds/{guild_id}/translation-groups/{group_id}/languages")
async def remove_group_language(
    guild_id: str,
    group_id: UUID,
    body: GroupLanguageInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    _, topology = _require(container)
    row = await topology.remove_language_non_destructive(
        guild_id=parsed,
        group_id=group_id,
        language_id=body.language_profile_id,
        expected_version=body.expected_version,
        destructive_discord_delete=body.destructive_discord_delete,
    )
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="TRANSLATION_LANGUAGE_REMOVED",
        target_type="TRANSLATION_GROUP",
        target_id=str(group_id),
        correlation_id=_correlation(request),
        data={"discord_resources_deleted": False},
    )
    return row


@router.post("/api/v1/guilds/{guild_id}/translation-groups/{group_id}/unlink")
async def unlink_variant(
    guild_id: str,
    group_id: UUID,
    body: VariantUnlinkInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    if body.delete_discord_resource:
        raise ValueError("unlink never deletes the Discord resource")
    _, topology = _require(container)
    await topology.get_group(guild_id=parsed, group_id=group_id)
    row = await topology.unlink_variant(
        guild_id=parsed,
        group_id=group_id,
        variant_id=body.variant_id,
        variant_type=body.variant_type,
    )
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="TRANSLATION_VARIANT_UNBOUND",
        target_type=f"{body.variant_type}_VARIANT",
        target_id=str(body.variant_id),
        correlation_id=_correlation(request),
    )
    return row


@router.post("/api/v1/guilds/{guild_id}/translation-groups/{group_id}/channel-groups")
async def create_translation_channel_group(
    guild_id: str,
    group_id: UUID,
    body: ChannelGroupInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    _, topology = _require(container)
    row = await topology.create_channel_group(
        guild_id=parsed,
        group_id=group_id,
        logical_key=body.logical_key,
        display_name=body.display_name,
        source_language_id=body.source_language_profile_id,
    )
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="TRANSLATION_CHANNEL_GROUP_CREATED",
        target_type="TRANSLATION_CHANNEL_GROUP",
        target_id=str(row["id"]),
        correlation_id=_correlation(request),
    )
    return row


@router.patch(
    "/api/v1/guilds/{guild_id}/translation-groups/{group_id}/channel-groups/{channel_group_id}"
)
async def rename_translation_channel_group(
    guild_id: str,
    group_id: UUID,
    channel_group_id: UUID,
    body: ChannelGroupRenameInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    _, topology = _require(container)
    row = await topology.rename_channel_group(
        guild_id=parsed,
        group_id=group_id,
        channel_group_id=channel_group_id,
        display_name=body.display_name,
    )
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="TRANSLATION_CHANNEL_GROUP_RENAMED",
        target_type="TRANSLATION_CHANNEL_GROUP",
        target_id=str(channel_group_id),
        correlation_id=_correlation(request),
    )
    return row


@router.post("/api/v1/guilds/{guild_id}/translation-groups/{group_id}/link")
async def link_existing_variant(
    guild_id: str,
    group_id: UUID,
    body: VariantLinkInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    _, topology = _require(container)
    row = await topology.link_existing_variant(
        guild_id=parsed,
        group_id=group_id,
        language_id=body.language_profile_id,
        variant_type=body.variant_type,
        discord_resource_id=int(body.discord_resource_id),
        confirmed_explicit_selection=body.confirmed_explicit_selection,
        channel_group_id=body.translation_channel_group_id,
        category_variant_id=body.translation_category_variant_id,
    )
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="TRANSLATION_VARIANT_LINKED",
        target_type=f"{body.variant_type}_VARIANT",
        target_id=str(row["id"]),
        correlation_id=_correlation(request),
        data={"selection_was_explicit": True, "inferred_by_name": False},
    )
    return row


@router.post("/api/v1/guilds/{guild_id}/translation-routes/compile")
async def compile_routes(
    guild_id: str,
    body: RouteCompileInput,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_READ)
    capabilities = TranslationProviderCapabilities(
        supports_hub_and_spoke=body.supports_hub_and_spoke,
        supports_full_mesh=body.supports_full_mesh,
        supports_custom=body.supports_custom,
        max_languages_per_group=body.max_languages_per_group,
        configuration_mode=ProviderConfigurationMode.OBSERVATION_ONLY,
        health=body.provider_health,
    )
    routes = TranslationRouteCompiler().compile(
        topology=body.topology,
        language_ids=tuple(body.language_profile_ids),
        hub_language_id=body.hub_language_profile_id,
        custom_routes=tuple(body.custom_routes),
        capabilities=capabilities,
    )
    return {"routes": [[str(source), str(destination)] for source, destination in routes]}


@router.put("/api/v1/guilds/{guild_id}/translation-groups/{group_id}/routes")
async def replace_group_routes(
    guild_id: str,
    group_id: UUID,
    body: RouteReplaceInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    _, topology = _require(container)
    row = await topology.replace_routes(
        guild_id=parsed,
        group_id=group_id,
        expected_version=body.expected_version,
        topology=body.topology,
        language_ids=tuple(body.language_profile_ids),
        hub_language_id=body.hub_language_profile_id,
        custom_routes=tuple(body.custom_routes),
        capabilities=TranslationProviderCapabilities(
            supports_hub_and_spoke=body.supports_hub_and_spoke,
            supports_full_mesh=body.supports_full_mesh,
            supports_custom=body.supports_custom,
            max_languages_per_group=body.max_languages_per_group,
            configuration_mode=ProviderConfigurationMode.OBSERVATION_ONLY,
            health=body.provider_health,
        ),
    )
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="TRANSLATION_ROUTES_CHANGED",
        target_type="TRANSLATION_GROUP",
        target_id=str(group_id),
        correlation_id=_correlation(request),
    )
    return row


@router.post("/api/v1/guilds/{guild_id}/visibility/compile")
async def compile_visibility(
    guild_id: str,
    body: VisibilityCompileInput,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.PERMISSIONS_READ)
    result = LanguageVisibilityCompiler().compile(
        policy=body.policy,
        guild_id=parsed,
        language_profile_id=body.language_profile_id,
        scope_id=body.visibility_scope_id,
        binding_role_id=int(body.binding_role_id) if body.binding_role_id else None,
        custom_policy=body.custom_policy,
    )
    return {
        "policy": result.policy.value,
        "overwrites": [
            {
                "target_type": item.target_type,
                "target_id": str(item.target_id),
                "allow": str(item.allow),
                "deny": str(item.deny),
            }
            for item in result.overwrites
        ],
        "roles_to_create": [
            {
                "scope_id": str(item.scope_id),
                "language_profile_id": str(item.language_profile_id),
                "name": item.name,
                "permissions": str(item.permissions),
                "hoist": item.hoist,
                "mentionable": item.mentionable,
            }
            for item in result.roles_to_create
        ],
        "reused_role_ids": [str(value) for value in result.reused_role_ids],
    }


@router.post("/api/v1/guilds/{guild_id}/visibility/capacity")
async def capacity_preflight(
    guild_id: str,
    body: CapacityInput,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.PERMISSIONS_READ)
    engine = RoleCapacityEngine()
    return {
        "roles": engine.role_budget(
            current_count=body.current_roles,
            required_bindings=body.required_bindings,
            reusable_bindings=body.reusable_bindings,
        ),
        "overwrites": engine.overwrite_budget(
            current_count=body.current_overwrites,
            proposed_delta=body.proposed_overwrite_delta,
        ),
    }


@router.post("/api/v1/guilds/{guild_id}/members/technical-roles/reconcile")
async def reconcile_member_roles(
    guild_id: str,
    body: MemberRoleReconcileInput,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.MEMBERS_READ)
    bindings: dict[tuple[UUID, UUID], int] = {}
    for key, role_id in body.bindings.items():
        scope, language = key.split(":", 1)
        bindings[(UUID(scope), UUID(language))] = parse_snowflake(role_id)
    reconciler = MemberTechnicalRoleReconciler()
    desired = reconciler.desired_roles(
        member_scope_ids=set(body.member_scope_ids),
        visible_language_ids=set(body.visible_language_ids),
        required_pairs=set(body.required_pairs),
        role_bindings=bindings,
    )
    return reconciler.diff(
        current_role_ids={parse_snowflake(value) for value in body.current_role_ids},
        desired_role_ids=set(desired),
    )


@router.post("/api/v1/guilds/{guild_id}/translation-providers/access-preflight")
async def provider_access_preflight(
    guild_id: str,
    body: ProviderAccessInput,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.BOTS_AUDIT)
    result = TranslationProviderCoordinator().access_preflight(
        bot_present=body.bot_present,
        effective_permissions_by_variant={
            parse_snowflake(key): int(value)
            for key, value in body.effective_permissions_by_variant.items()
        },
        require_threads=body.require_threads,
        require_embeds=body.require_embeds,
        require_attachments=body.require_attachments,
    )
    return {
        "allowed": result.allowed,
        "state": result.state,
        "missing_permissions": result.missing_permissions,
        "warnings": result.warnings,
        "required_permissions": result.required_permissions,
        "recommended_administrator": False,
        "uses_human_language_roles": False,
    }


@router.post("/api/v1/guilds/{guild_id}/translation-providers/prepare")
async def prepare_provider_configuration(
    guild_id: str,
    body: ProviderPrepareInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)

    async def capabilities_probe(_: int) -> dict[str, Any]:
        values = body.observed_capabilities
        return {
            "supports_hub_and_spoke": values.supports_hub_and_spoke,
            "supports_full_mesh": values.supports_full_mesh,
            "supports_custom": values.supports_custom,
            "max_languages_per_group": values.max_languages_per_group,
            "health": values.provider_health,
            "discord_bot_present": body.discord_bot_present,
            "bot_permissions": body.bot_permissions,
        }

    async def health_probe(_: int) -> dict[str, Any]:
        return {"status": body.observed_capabilities.provider_health}

    provider = NonInvasiveExistingBotProvider(capabilities_probe, health_probe)
    result = await TranslationProviderCoordinator().prepare(
        provider=provider, guild_id=parsed, desired_group=body.desired_group
    )
    if body.binding_id is not None:
        _, topology = _require(container)
        await topology.record_provider_status(
            guild_id=parsed,
            binding_id=body.binding_id,
            status=result.state,
            verified=False,
        )
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="TRANSLATION_PROVIDER_CONFIGURATION_PREPARED",
        target_type="TRANSLATION_PROVIDER_BINDING",
        target_id=str(body.binding_id or "unbound"),
        correlation_id=_correlation(request),
        data={"state": result.state.value, "verification_state": result.verification_state},
    )
    return {
        "state": result.state.value,
        "instructions": result.instructions,
        "verification_state": result.verification_state,
        "payload": result.payload,
        "automatic_mutation_performed": False,
        "token_shared": False,
    }


@router.post("/api/v1/guilds/{guild_id}/translation-drift/observe")
async def observe_drift(
    guild_id: str,
    body: DriftInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    _, topology = _require(container)
    result = await topology.observe_drift(guild_id=parsed, **body.model_dump())
    await _audit(
        container,
        guild_id=parsed,
        actor_id=session.discord_user_id,
        event_type="TRANSLATION_DRIFT_OBSERVED",
        target_type=f"{body.variant_type or 'UNKNOWN'}_VARIANT",
        target_id=str(body.variant_id or "unbound"),
        correlation_id=_correlation(request),
        data={"drift": result["drift"], "evidence": body.evidence},
    )
    return result


@router.post("/api/v1/guilds/{guild_id}/multilingual-clone/preview")
async def multilingual_clone_preview(
    guild_id: str,
    body: MultilingualCloneInput,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    source = parse_snowflake(guild_id)
    destination = parse_snowflake(body.destination_guild_id)
    await _authorize(source, session, container, Capability.STRUCTURE_READ)
    await _authorize(destination, session, container, Capability.PLANS_CREATE, sensitive=True)
    await _authorize(destination, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    expander = TranslationCloneExpander()
    artifact = expander.export(
        source_guild_id=source,
        languages=tuple(body.languages),
        groups=tuple(body.groups),
        provider_requirements=tuple(body.provider_requirements),
    )
    return {
        "artifact": artifact.to_dict(),
        "preview": expander.expand_for_destination(
            artifact=artifact, destination_guild_id=destination
        ),
    }


@router.post("/api/v1/guilds/{guild_id}/translation-groups/{group_id}/provider/plan")
@router.post("/api/v1/guilds/{guild_id}/translation-groups/{group_id}/repair/plan")
@router.post("/api/v1/guilds/{guild_id}/translation-groups/{group_id}/visibility/plan")
@router.post("/api/v1/guilds/{guild_id}/translation-groups/{group_id}/routes/plan")
@router.post("/api/v1/guilds/{guild_id}/translation-groups/{group_id}/unlink/plan")
@router.post("/api/v1/guilds/{guild_id}/translation-groups/{group_id}/link/plan")
@router.post("/api/v1/guilds/{guild_id}/translation-groups/{group_id}/variants/plan")
@router.post("/api/v1/guilds/{guild_id}/translation-groups/{group_id}/structural-plan")
async def create_structural_plan(
    guild_id: str,
    group_id: UUID,
    body: StructuralPlanInput,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.PLANS_CREATE, sensitive=True)
    await _authorize(parsed, session, container, Capability.STRUCTURE_WRITE, sensitive=True)
    _, topology = _require(container)
    await topology.get_group(guild_id=parsed, group_id=group_id)
    if container.planning is None:
        raise ApiProblem(
            status_code=503,
            code="PLANNING_NOT_CONFIGURED",
            message_key="errors.plans.notConfigured",
        )
    graph = DesiredStateGraph(
        parsed,
        tuple(
            DesiredNode.build(
                logical_key=node.logical_key,
                resource_type=ResourceType(node.resource_type),
                properties=node.properties,
                discord_id=int(node.discord_id) if node.discord_id else None,
                symbol=node.symbol,
                presence=NodePresence(node.presence),
                relations={
                    name: ResourceReference(ReferenceKind(kind), value)
                    for name, (kind, value) in node.relations.items()
                },
            )
            for node in body.nodes
        ),
    )
    plan, replayed = await container.planning.create(
        graph=graph,
        actor_user_id=session.discord_user_id,
        idempotency_key=f"stage08:{group_id}:{body.idempotency_key}",
        correlation_id=_correlation(request),
        operation_order_policy="STAGE08_STRUCTURAL",
    )
    return {
        "plan_id": str(plan["id"]),
        "guild_id": str(plan["guild_id"]),
        "status": str(plan["status"]),
        "replayed": replayed,
        "pipeline": [
            "DSG",
            "PLAN",
            "PREFLIGHT",
            "CONFIRMATION",
            "DURABLE_JOB",
            "WORKER",
            "GOVERNOR",
            "DISCORD_ADAPTER",
            "VERIFICATION",
            "AUDIT",
        ],
        "structural_execution_order": [
            "CATEGORIES",
            "CHANNELS",
            "ROLES",
            "OVERWRITES",
        ],
        "provider_configuration": "AFTER_DISCORD_VERIFICATION",
    }
