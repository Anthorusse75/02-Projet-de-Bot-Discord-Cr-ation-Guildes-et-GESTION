from __future__ import annotations

import json
from dataclasses import asdict
from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from did.api.dependencies import ApiProblem, CsrfSessionDep, CurrentSessionDep, ServicesDep
from did.api.guilds import parse_snowflake
from did.domain.auth import AuthorizationScope, Capability
from did.domain.read_model import ChannelSnapshot, MemberSnapshot, OverwriteSnapshot
from did.domain.scopes import ScopeMembershipResolver, ScopeType
from did.permissions import DEFAULT_PERMISSION_REGISTRY, PermissionEvaluator
from did.permissions.capabilities import BotCapabilityChecker, BotOperation, CapabilityOutcome
from did.permissions.views import (
    SimplePermissionConcept,
    category_sync_state,
    compile_simple_permissions,
    simulate_overwrites,
    view_as_member,
    view_as_newcomer,
    view_as_role,
)

router = APIRouter(prefix="/api/v1/guilds", tags=["stage-04-read-permissions"])


class PermissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    view_as: Literal["VIEW_AS_MEMBER", "VIEW_AS_ROLE", "VIEW_AS_NEWCOMER"]
    subject_id: str | None = None
    role_id: str | None = None
    resource_id: str | None = None
    requested_permission: str | None = Field(default=None, max_length=64)


class OverwriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: str
    target_type: Literal[0, 1]
    allow: str
    deny: str

    @field_validator("allow", "deny")
    @classmethod
    def permission_string(cls, value: str) -> str:
        DEFAULT_PERMISSION_REGISTRY.parse_api_bits(value)
        return value


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: str
    subject_ids: list[str] = Field(min_length=1, max_length=500)
    proposed_overwrites: list[OverwriteInput] = Field(max_length=1000)


class SimpleCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concepts: list[SimplePermissionConcept] = Field(min_length=1, max_length=12)


class LogicalGroupResourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_type: Literal["CATEGORY", "CHANNEL", "ROLE"]
    discord_resource_id: str
    semantic_role: str | None = Field(default=None, max_length=64)


class LogicalGroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    resources: list[LogicalGroupResourceInput] = Field(default_factory=list, max_length=500)


class LogicalGroupPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    resources: list[LogicalGroupResourceInput] | None = Field(default=None, max_length=500)


class ScopeRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_type: Literal[
        "DISCORD_ROLE",
        "ANY_DISCORD_ROLE",
        "ALL_DISCORD_ROLES",
        "EXPLICIT_DID_MEMBERSHIP",
        "CUSTOM",
    ]
    config: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(ge=0, le=10000)
    status: Literal["ACTIVE", "DISABLED"] = "ACTIVE"

    @model_validator(mode="after")
    def validate_rule_config(self) -> ScopeRuleInput:
        role_rules = {"DISCORD_ROLE", "ANY_DISCORD_ROLE", "ALL_DISCORD_ROLES"}
        if self.rule_type in role_rules:
            if set(self.config) != {"role_ids"} or not isinstance(
                self.config.get("role_ids"), list
            ):
                raise ValueError("role membership rules require only role_ids")
            raw_ids = self.config["role_ids"]
            if not raw_ids or len(raw_ids) > 100:
                raise ValueError("role_ids must contain between 1 and 100 Snowflakes")
            if any(not isinstance(value, str) for value in raw_ids):
                raise ValueError("role_ids API values must be decimal strings")
            parsed = [parse_snowflake(value) for value in raw_ids]
            if len(parsed) != len(set(parsed)):
                raise ValueError("role_ids cannot contain duplicates")
            if self.rule_type == "DISCORD_ROLE" and len(parsed) != 1:
                raise ValueError("DISCORD_ROLE requires exactly one role_id")
            self.config = {"role_ids": parsed}
        elif self.rule_type == "EXPLICIT_DID_MEMBERSHIP" and self.config:
            raise ValueError("explicit DID membership does not accept executable config")
        elif (
            self.rule_type == "CUSTOM"
            and len(json.dumps(self.config, separators=(",", ":"))) > 4096
        ):
            raise ValueError("custom rule metadata is too large")
        return self


class VisibilityScopeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_type: ScopeType
    scope_key: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$", max_length=128)
    name: str = Field(min_length=1, max_length=128)
    logical_group_id: UUID | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    rules: list[ScopeRuleInput] = Field(default_factory=list, max_length=100)
    explicit_member_ids: list[str] = Field(default_factory=list, max_length=1000)


class VisibilityScopePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    config: dict[str, Any] = Field(default_factory=dict)
    rules: list[ScopeRuleInput] = Field(default_factory=list, max_length=100)
    explicit_member_ids: list[str] = Field(default_factory=list, max_length=1000)


class ScopeResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    member_id: str


def _id(value: str | None, field: str) -> int:
    if value is None:
        raise ApiProblem(
            status_code=422, code=f"{field.upper()}_REQUIRED", message_key="errors.input.required"
        )
    return parse_snowflake(value)


def _channel_response(channel: ChannelSnapshot) -> dict[str, Any]:
    return {
        "guild_id": str(channel.guild_id),
        "id": str(channel.channel_id),
        "type": int(channel.channel_type),
        "name": channel.name,
        "position": channel.position,
        "parent_id": str(channel.parent_id) if channel.parent_id else None,
        "resource_kind": channel.resource_kind.value,
        "observability": channel.observability.value,
        "freshness": channel.freshness.state.value,
        "data_assertion": (
            "CURRENT_CONFIRMED"
            if channel.observability.value == "VISIBLE" and channel.freshness.state.value == "FRESH"
            else "LAST_KNOWN"
        ),
    }


def _decision_response(decision: Any) -> dict[str, Any]:
    return {
        "guild_id": str(decision.guild_id),
        "subject_id": str(decision.subject_id),
        "resource_id": str(decision.resource_id) if decision.resource_id else None,
        "calculated_bits": str(decision.calculated_bits),
        "effective_bits": str(decision.effective_bits),
        "unknown_bits": str(decision.unknown_bits),
        "decision_status": decision.status.value,
        "requested_permission": decision.requested_permission,
        "outcome": decision.outcome.value,
        "coverage": decision.coverage.value,
        "freshness": decision.freshness.value,
        "incomplete_reasons": list(decision.incomplete_reasons),
        "trace": [
            {
                "step": entry.step.value,
                "source_type": entry.source_type,
                "source_id": str(entry.source_id) if entry.source_id else None,
                "allow_bits": str(entry.allow_bits),
                "deny_bits": str(entry.deny_bits),
                "before": str(entry.before),
                "after": str(entry.after),
                "reason_key": entry.reason_key,
            }
            for entry in decision.trace
        ],
        "implicit_denials": [
            {
                "denied_bits": str(item.denied_bits),
                "missing_permission": item.missing_permission,
                "reason_key": item.reason_key,
            }
            for item in decision.implicit_denials
        ],
        "warnings": list(decision.warnings),
        "source_versions": list(decision.source_versions),
        "registry_version": decision.registry_version,
        "data_assertion": decision.data_assertion,
    }


async def _permission_context(
    guild_id: int, body: PermissionRequest, container: Any
) -> tuple[Any, MemberSnapshot, ChannelSnapshot | None, ChannelSnapshot | None]:
    lookup_id = _id(body.subject_id, "subject_id") if body.view_as == "VIEW_AS_MEMBER" else guild_id
    guild, cached_member = await container.stage04_repository.guild_snapshot(guild_id, lookup_id)
    if body.view_as == "VIEW_AS_MEMBER":
        member = view_as_member(cached_member).member
    elif body.view_as == "VIEW_AS_ROLE":
        member = view_as_role(guild, _id(body.role_id, "role_id"), freshness=guild.freshness).member
    else:
        member = view_as_newcomer(guild, freshness=guild.freshness).member
    resource = guild.channel(parse_snowflake(body.resource_id)) if body.resource_id else None
    if body.resource_id and resource is None:
        raise ApiProblem(
            status_code=404, code="RESOURCE_NOT_FOUND", message_key="errors.resource.notFound"
        )
    parent = (
        guild.channel(resource.parent_id)
        if resource and resource.is_thread and resource.parent_id
        else None
    )
    return guild, member, resource, parent


@router.get("/{guild_id}/structure")
async def structure(
    guild_id: str,
    session: CurrentSessionDep,
    container: ServicesDep,
    include_hidden_deleted: bool = Query(default=False),
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.STRUCTURE_READ,
        scope=AuthorizationScope.guild(),
    )
    projection = await container.stage04_repository.structure(parsed)
    snapshot = projection["snapshot"]

    def visible(item: ChannelSnapshot) -> bool:
        return include_hidden_deleted or item.observability.value == "VISIBLE"

    threads = projection["threads"]

    def with_threads(channel: ChannelSnapshot) -> dict[str, Any]:
        result = _channel_response(channel)
        result["threads"] = [
            _channel_response(thread)
            for thread in threads.get(channel.channel_id, [])
            if visible(thread)
        ]
        category = snapshot.channel(channel.parent_id) if channel.parent_id else None
        result["category_sync"] = category_sync_state(channel, category).value
        return result

    categories = []
    for category in projection["categories"]:
        if not visible(category):
            continue
        item = _channel_response(category)
        item["channels"] = [
            with_threads(channel)
            for channel in projection["children"].get(category.channel_id, [])
            if visible(channel)
        ]
        categories.append(item)
    return {
        "guild_id": str(parsed),
        "source": "LOCAL_CACHE",
        "discord_rest_calls": 0,
        "resource_kind": "DISCORD_RESOURCE",
        "categories": categories,
        "root_channels": [with_threads(item) for item in projection["roots"] if visible(item)],
    }


@router.get("/{guild_id}/roles")
async def roles(
    guild_id: str, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.ROLES_READ,
        scope=AuthorizationScope.guild(),
    )
    guild, _ = await container.stage04_repository.guild_snapshot(parsed, session.discord_user_id)
    return {
        "guild_id": str(parsed),
        "source": "LOCAL_CACHE",
        "discord_rest_calls": 0,
        "registry_version": DEFAULT_PERMISSION_REGISTRY.version,
        "roles": [
            {
                "id": str(role.role_id),
                "name": role.name,
                "position": role.position,
                "permissions": str(role.permissions),
                "known_flags": list(DEFAULT_PERMISSION_REGISTRY.names(role.permissions)),
                "unknown_bits": str(DEFAULT_PERMISSION_REGISTRY.unknown_bits(role.permissions)),
                "managed": role.managed,
                "freshness": role.freshness.state.value,
            }
            for role in guild.roles
        ],
    }


@router.get("/{guild_id}/coverage")
async def coverage(
    guild_id: str, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.STRUCTURE_READ,
        scope=AuthorizationScope.guild(),
    )
    guild, _ = await container.stage04_repository.guild_snapshot(parsed, session.discord_user_id)
    value = asdict(guild.coverage)
    value.update(
        guild_id=str(parsed),
        mode=guild.coverage.mode.value,
        freshness=guild.coverage.freshness.value,
        discord_rest_calls=0,
    )
    if guild.coverage.mode.value != "FULL":
        container.runtime_repository.metrics.coverage_gap(guild.coverage.mode.value)
    return value


@router.post("/{guild_id}/permissions/evaluate")
async def evaluate_permission(
    guild_id: str,
    body: PermissionRequest,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.PERMISSIONS_READ,
        scope=AuthorizationScope.guild(),
    )
    guild, member, resource, parent = await _permission_context(parsed, body, container)
    started = perf_counter()
    decision = PermissionEvaluator().evaluate(
        guild=guild,
        member=member,
        resource=resource,
        parent=parent,
        requested_permission=body.requested_permission,
    )
    container.runtime_repository.metrics.permission_evaluation(
        perf_counter() - started, decision.status.value
    )
    return _decision_response(decision)


@router.post("/{guild_id}/permissions/explain")
async def explain_permission(
    guild_id: str,
    body: PermissionRequest,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    native = await evaluate_permission(guild_id, body, session, container)
    return {
        "guild_id": native["guild_id"],
        "discord_native_permission": native,
        "did_dashboard_authorization": {
            "capability": Capability.PERMISSIONS_READ.value,
            "scope_kind": "GUILD",
            "scope_id": "*",
            "authorized": True,
            "is_discord_native_restriction": False,
        },
    }


@router.post("/{guild_id}/permissions/simple/compile")
async def simple_compile(
    guild_id: str,
    body: SimpleCompileRequest,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.PERMISSIONS_READ,
        scope=AuthorizationScope.guild(),
    )
    result = compile_simple_permissions(tuple(body.concepts))
    return {
        "guild_id": str(parsed),
        "allow": str(result.allow_bits),
        "deny": str(result.deny_bits),
        "known_flags": list(result.known_flags),
        "diagnostics": list(result.diagnostics),
        "registry_version": result.registry_version,
        "persisted": False,
        "discord_mutations": 0,
    }


@router.post("/{guild_id}/permissions/simulate")
async def simulate_permission(
    guild_id: str,
    body: SimulationRequest,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.PERMISSIONS_READ,
        scope=AuthorizationScope.guild(),
    )
    subject_ids = tuple(parse_snowflake(value) for value in body.subject_ids)
    if len(set(subject_ids)) != len(subject_ids):
        raise ApiProblem(
            status_code=422, code="DUPLICATE_SUBJECT_ID", message_key="errors.input.duplicate"
        )
    guild, _ = await container.stage04_repository.guild_snapshot(parsed, subject_ids[0])
    channel = guild.channel(parse_snowflake(body.resource_id))
    if channel is None:
        raise ApiProblem(
            status_code=404, code="RESOURCE_NOT_FOUND", message_key="errors.resource.notFound"
        )
    if channel.is_thread:
        raise ApiProblem(
            status_code=422,
            code="THREAD_OVERWRITES_UNSUPPORTED",
            message_key="errors.permissions.threadOverwrites",
        )
    proposed = tuple(
        OverwriteSnapshot(
            parsed,
            channel.channel_id,
            parse_snowflake(item.target_id),
            item.target_type,
            DEFAULT_PERMISSION_REGISTRY.parse_api_bits(item.allow),
            DEFAULT_PERMISSION_REGISTRY.parse_api_bits(item.deny),
        )
        for item in body.proposed_overwrites
    )
    targets = [(item.target_type, item.target_id) for item in proposed]
    if len(targets) != len(set(targets)):
        raise ApiProblem(
            status_code=422,
            code="DUPLICATE_OVERWRITE_TARGET",
            message_key="errors.permissions.duplicateOverwriteTarget",
        )
    subjects = await container.stage04_repository.member_snapshots(parsed, subject_ids)
    impact = simulate_overwrites(
        evaluator=PermissionEvaluator(),
        guild=guild,
        channel=channel,
        subjects=subjects,
        proposed_overwrites=proposed,
    )
    return {
        "guild_id": str(parsed),
        "resource_id": str(channel.channel_id),
        "subjects": [
            {
                "subject_id": str(item.subject_id),
                "before": _decision_response(item.before),
                "after": _decision_response(item.after),
                "added_effective_permissions": str(item.added_effective_bits),
                "removed_effective_permissions": str(item.removed_effective_bits),
            }
            for item in impact.subjects
        ],
        "incomplete_subject_ids": [str(value) for value in impact.incomplete_subject_ids],
        "warnings": list(impact.warnings),
        "persisted": False,
        "discord_mutations": 0,
    }


@router.get("/{guild_id}/capabilities")
async def capabilities(
    guild_id: str,
    session: CurrentSessionDep,
    container: ServicesDep,
    operation: Annotated[BotOperation, Query()] = BotOperation.MANAGE_CHANNEL,
    channel_id: str | None = Query(default=None),
    target_role_id: str | None = Query(default=None),
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.BOTS_AUDIT,
        scope=AuthorizationScope.guild(),
        sensitive=True,
    )
    bot_id, installation_status = await container.stage04_repository.bot_identity(parsed)
    if bot_id is None:
        container.runtime_repository.metrics.capability_check(CapabilityOutcome.UNKNOWN.value)
        return {
            "guild_id": str(parsed),
            "operation": operation.value,
            "outcome": CapabilityOutcome.UNKNOWN.value,
            "causes": ["capability.bot_identity_unknown"],
            "remediations": [],
        }
    guild, bot = await container.stage04_repository.guild_snapshot(parsed, bot_id)
    channel = guild.channel(parse_snowflake(channel_id)) if channel_id else None
    target = guild.role(parse_snowflake(target_role_id)) if target_role_id else None
    decision = BotCapabilityChecker().check(
        operation=operation,
        guild=guild,
        bot=bot,
        channel=channel,
        target_role=target,
        installation_active=installation_status == "ACTIVE",
    )
    container.runtime_repository.metrics.capability_check(decision.outcome.value)
    result = asdict(decision)
    result["guild_id"] = str(parsed)
    result["operation"] = decision.operation.value
    result["outcome"] = decision.outcome.value
    if decision.hierarchy:
        result["hierarchy"] = {
            **asdict(decision.hierarchy),
            "outcome": decision.hierarchy.outcome.value,
            "bot_highest_role_id": str(decision.hierarchy.bot_highest_role_id)
            if decision.hierarchy.bot_highest_role_id
            else None,
            "target_role_id": str(decision.hierarchy.target_role_id)
            if decision.hierarchy.target_role_id
            else None,
        }
    return result


@router.get("/{guild_id}/logical-groups")
async def logical_groups(
    guild_id: str, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.STRUCTURE_READ,
        scope=AuthorizationScope.guild(),
    )
    groups = await container.stage04_repository.list_logical_groups(parsed)
    return {
        "guild_id": str(parsed),
        "resource_kind": "DID_LOGICAL_RESOURCE",
        "groups": _json_ids(groups),
    }


@router.post("/{guild_id}/logical-groups", status_code=status.HTTP_201_CREATED)
async def create_logical_group(
    guild_id: str, body: LogicalGroupCreate, session: CsrfSessionDep, container: ServicesDep
) -> dict[str, str]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.STRUCTURE_WRITE,
        scope=AuthorizationScope.guild(),
        sensitive=True,
    )
    resources = tuple(
        {
            "resource_type": item.resource_type,
            "discord_resource_id": parse_snowflake(item.discord_resource_id),
            "semantic_role": item.semantic_role,
        }
        for item in body.resources
    )
    group_id = await container.stage04_repository.create_logical_group(
        guild_id=parsed,
        actor_id=session.discord_user_id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        metadata=body.metadata,
        resources=resources,
    )
    return {"guild_id": str(parsed), "id": str(group_id), "resource_kind": "DID_LOGICAL_RESOURCE"}


@router.patch("/{guild_id}/logical-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def patch_logical_group(
    guild_id: str,
    group_id: UUID,
    body: LogicalGroupPatch,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> None:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.STRUCTURE_WRITE,
        scope=AuthorizationScope.guild(),
        sensitive=True,
    )
    await container.stage04_repository.update_logical_group(
        guild_id=parsed,
        group_id=group_id,
        actor_id=session.discord_user_id,
        name=body.name,
        description=body.description,
        metadata=body.metadata,
        resources=(
            tuple(item.model_dump() for item in body.resources)
            if body.resources is not None
            else None
        ),
    )


@router.delete("/{guild_id}/logical-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_logical_group(
    guild_id: str, group_id: UUID, session: CsrfSessionDep, container: ServicesDep
) -> None:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.STRUCTURE_WRITE,
        scope=AuthorizationScope.guild(),
        sensitive=True,
    )
    await container.stage04_repository.delete_logical_group(
        parsed, group_id, session.discord_user_id
    )


@router.get("/{guild_id}/visibility-scopes")
async def visibility_scopes(
    guild_id: str, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.PERMISSIONS_READ,
        scope=AuthorizationScope.guild(),
    )
    scopes = await container.stage04_repository.list_visibility_scopes(parsed)
    return {
        "guild_id": str(parsed),
        "scopes": [
            {
                **_json_ids(asdict(scope)),
                "scope_type": scope.scope_type.value,
                "rules": [
                    {**_json_ids(asdict(rule)), "rule_type": rule.rule_type.value} for rule in rules
                ],
                "explicit_member_ids": [str(value) for value in sorted(members)],
            }
            for scope, rules, members in scopes
        ],
    }


@router.post("/{guild_id}/visibility-scopes", status_code=status.HTTP_201_CREATED)
async def create_visibility_scope(
    guild_id: str, body: VisibilityScopeCreate, session: CsrfSessionDep, container: ServicesDep
) -> dict[str, str]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.PERMISSIONS_WRITE,
        scope=AuthorizationScope.guild(),
        sensitive=True,
    )
    scope_id = await container.stage04_repository.create_visibility_scope(
        guild_id=parsed,
        actor_id=session.discord_user_id,
        scope_type=body.scope_type,
        scope_key=body.scope_key,
        name=body.name,
        logical_group_id=body.logical_group_id,
        config=body.config,
        rules=tuple(item.model_dump() for item in body.rules),
        explicit_member_ids=_member_ids(body.explicit_member_ids),
    )
    return {"guild_id": str(parsed), "id": str(scope_id)}


@router.patch("/{guild_id}/visibility-scopes/{scope_id}", status_code=status.HTTP_204_NO_CONTENT)
async def patch_visibility_scope(
    guild_id: str,
    scope_id: UUID,
    body: VisibilityScopePatch,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> None:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.PERMISSIONS_WRITE,
        scope=AuthorizationScope.guild(),
        sensitive=True,
    )
    await container.stage04_repository.update_visibility_scope(
        guild_id=parsed,
        scope_id=scope_id,
        actor_id=session.discord_user_id,
        name=body.name,
        config=body.config,
        rules=tuple(item.model_dump() for item in body.rules),
        explicit_member_ids=_member_ids(body.explicit_member_ids),
    )


@router.delete("/{guild_id}/visibility-scopes/{scope_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_visibility_scope(
    guild_id: str, scope_id: UUID, session: CsrfSessionDep, container: ServicesDep
) -> None:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.PERMISSIONS_WRITE,
        scope=AuthorizationScope.guild(),
        sensitive=True,
    )
    await container.stage04_repository.delete_visibility_scope(
        parsed, scope_id, session.discord_user_id
    )


@router.post("/{guild_id}/visibility-scopes/{scope_id}/resolve")
async def resolve_visibility_scope(
    guild_id: str,
    scope_id: UUID,
    body: ScopeResolveRequest,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=parsed,
        capability=Capability.PERMISSIONS_READ,
        scope=AuthorizationScope.guild(),
    )
    member_id = parse_snowflake(body.member_id)
    _, member = await container.stage04_repository.guild_snapshot(parsed, member_id)
    records = await container.stage04_repository.list_visibility_scopes(parsed)
    selected = next((record for record in records if record[0].id == scope_id), None)
    if selected is None:
        raise ApiProblem(
            status_code=404, code="SCOPE_NOT_FOUND", message_key="errors.scope.notFound"
        )
    scope, rules, explicit = selected
    decision = ScopeMembershipResolver().resolve(
        scope=scope, member=member, rules=rules, explicit_member_ids=explicit
    )
    container.runtime_repository.metrics.scope_resolution(decision.outcome.value)
    return {
        "guild_id": str(parsed),
        "visibility_scope_id": str(scope_id),
        "subject_id": str(member_id),
        "outcome": decision.outcome.value,
        "freshness": decision.freshness.value,
        "cache_version": decision.cache_version,
        "diagnostics": list(decision.diagnostics),
        "trace": [
            {
                "rule_id": str(item.rule_id),
                "rule_type": item.rule_type.value,
                "outcome": item.outcome.value,
                "reason_key": item.reason_key,
            }
            for item in decision.trace
        ],
    }


def _member_ids(values: list[str]) -> tuple[int, ...]:
    parsed = tuple(parse_snowflake(value) for value in values)
    if len(parsed) != len(set(parsed)):
        raise ApiProblem(
            status_code=422, code="DUPLICATE_MEMBER_ID", message_key="errors.input.duplicate"
        )
    return parsed


def _json_ids(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if (
                key
                in {
                    "guild_id",
                    "discord_channel_id",
                    "discord_role_id",
                    "discord_user_id",
                    "logical_group_id",
                    "visibility_scope_id",
                    "id",
                }
                and item is not None
            ):
                result[key] = str(item)
            elif key == "role_ids" and isinstance(item, list):
                result[key] = [str(role_id) for role_id in item]
            else:
                result[key] = _json_ids(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_ids(item) for item in value]
    return value
