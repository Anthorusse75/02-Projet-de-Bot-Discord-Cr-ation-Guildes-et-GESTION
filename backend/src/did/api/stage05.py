from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from did.api.dependencies import ApiProblem, CsrfSessionDep, CurrentSessionDep, ServicesDep
from did.api.guilds import parse_snowflake
from did.domain.auth import AuthorizationScope, Capability
from did.planning.models import (
    DesiredNode,
    DesiredStateGraph,
    NodePresence,
    ReferenceKind,
    ResourceReference,
    ResourceType,
)

router = APIRouter(prefix="/api/v1/guilds", tags=["stage-05-plans"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)]


class RelationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["parent", "channel", "subject"]
    kind: ReferenceKind
    value: str = Field(min_length=1, max_length=256)


class DesiredNodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logical_key: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$", min_length=1, max_length=256)
    resource_type: ResourceType
    discord_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,19}$")
    symbol: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_.:-]+$", min_length=1, max_length=256
    )
    presence: NodePresence = NodePresence.PRESENT
    properties: dict[str, Any] = Field(default_factory=dict)
    relations: list[RelationInput] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def supported_shape(self) -> DesiredNodeInput:
        allowed = {
            ResourceType.GUILD: set(),
            ResourceType.ROLE: {
                "name",
                "permissions",
                "color",
                "hoist",
                "mentionable",
                "position",
            },
            ResourceType.CATEGORY: {"name", "position"},
            ResourceType.CHANNEL: {
                "type",
                "name",
                "topic",
                "nsfw",
                "position",
                "flags",
                "bitrate",
                "user_limit",
                "rate_limit_per_user",
                "default_auto_archive_duration",
                "lock_permissions",
                "parent_id",
            },
            ResourceType.OVERWRITE: {"target_type", "allow", "deny"},
        }[self.resource_type]
        unsupported = set(self.properties) - allowed
        if unsupported:
            raise ValueError(f"unsupported properties: {','.join(sorted(unsupported))}")
        if len(json.dumps(self.properties, separators=(",", ":"))) > 16_384:
            raise ValueError("node properties are too large")
        for key in ("permissions", "allow", "deny"):
            value = self.properties.get(key)
            if value is not None and (not isinstance(value, str) or not value.isdecimal()):
                raise ValueError(f"{key} must be a decimal string")
        name = self.properties.get("name")
        if name is not None and (not isinstance(name, str) or not 1 <= len(name) <= 100):
            raise ValueError("Discord resource name must contain 1 to 100 characters")
        parent_id = self.properties.get("parent_id")
        if parent_id is not None and (
            not isinstance(parent_id, str) or not parent_id.isdecimal() or int(parent_id) <= 0
        ):
            raise ValueError("parent_id must be null or a decimal Snowflake string")
        channel_type = self.properties.get("type")
        if channel_type is not None and channel_type not in {0, 2, 4, 5, 13}:
            raise ValueError("unsupported mutable Discord channel type")
        target_type = self.properties.get("target_type")
        if target_type is not None and target_type not in {0, 1}:
            raise ValueError("overwrite target_type must be role (0) or member (1)")
        if len({item.name for item in self.relations}) != len(self.relations):
            raise ValueError("relation names must be unique")
        allowed_relations = {
            ResourceType.GUILD: set(),
            ResourceType.ROLE: set(),
            ResourceType.CATEGORY: set(),
            ResourceType.CHANNEL: {"parent"},
            ResourceType.OVERWRITE: {"channel", "subject"},
        }[self.resource_type]
        unsupported_relations = {item.name for item in self.relations} - allowed_relations
        if unsupported_relations:
            raise ValueError(f"unsupported relations: {','.join(sorted(unsupported_relations))}")
        return self

    def domain(self) -> DesiredNode:
        return DesiredNode.build(
            logical_key=self.logical_key,
            resource_type=self.resource_type,
            properties=self.properties,
            discord_id=parse_snowflake(self.discord_id) if self.discord_id else None,
            symbol=self.symbol,
            presence=self.presence,
            relations={
                relation.name: ResourceReference(relation.kind, relation.value)
                for relation in self.relations
            },
        )


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["did-dsg-v1"] = "did-dsg-v1"
    nodes: list[DesiredNodeInput] = Field(min_length=1, max_length=500)

    @field_validator("nodes")
    @classmethod
    def bounded_graph(cls, value: list[DesiredNodeInput]) -> list[DesiredNodeInput]:
        if len(json.dumps([item.model_dump(mode="json") for item in value])) > 1_000_000:
            raise ValueError("desired state graph is too large")
        return value


class VersionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)


class ConfirmationCommand(VersionCommand):
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    acknowledgement: str | None = Field(default=None, max_length=128)


def _correlation(request: Request) -> UUID:
    return UUID(str(request.state.correlation_id))


def _plan_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "guild_id": str(row["guild_id"]),
        "actor_user_id": str(row["actor_user_id"]),
        "status": str(row["status"]),
        "state_version": int(row["state_version"]),
        "schema_version": str(row["desired_graph_schema_version"]),
        "compiler_version": str(row["compiler_version"]),
        "desired_graph_hash": str(row["desired_graph_hash"]),
        "base_structure_version": str(row["base_structure_version"]),
        "base_structure_hash": str(row["base_structure_hash"]),
        "capability_version": str(row["capability_version"]),
        "plan_hash": str(row["plan_hash"]),
        "risk_level": str(row["risk_level"]),
        "risk": dict(row["risk_summary"]),
        "impact": dict(row["impact_summary"]),
        "reinforced_confirmation_required": bool(row["confirmation_required"]),
        "error_code": row["error_code"],
        "verification": row["verification_summary"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def _authorize(
    *, guild_id: int, session: Any, container: Any, capability: Capability
) -> None:
    await container.authorization.authorize(
        discord_user_id=session.discord_user_id,
        guild_id=guild_id,
        capability=capability,
        scope=AuthorizationScope.guild(),
        sensitive=True,
    )


@router.post("/{guild_id}/plans", status_code=status.HTTP_201_CREATED)
async def create_plan(
    guild_id: str,
    body: PlanCreate,
    request: Request,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(
        guild_id=parsed,
        session=session,
        container=container,
        capability=Capability.PLANS_CREATE,
    )
    graph = DesiredStateGraph(parsed, tuple(item.domain() for item in body.nodes))
    row, created = await container.planning.create(
        graph=graph,
        actor_user_id=session.discord_user_id,
        idempotency_key=idempotency_key,
        correlation_id=_correlation(request),
    )
    return {"created": created, "plan": _plan_response(row)}


@router.get("/{guild_id}/plans/{plan_id}")
async def get_plan(
    guild_id: str,
    plan_id: UUID,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(
        guild_id=parsed,
        session=session,
        container=container,
        capability=Capability.PLANS_CREATE,
    )
    return _plan_response(await container.planning_repository.get_plan(parsed, plan_id))


@router.get("/{guild_id}/plans/{plan_id}/operations")
async def plan_operations(
    guild_id: str,
    plan_id: UUID,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(
        guild_id=parsed,
        session=session,
        container=container,
        capability=Capability.PLANS_CREATE,
    )
    rows = await container.planning_repository.operations(parsed, plan_id)
    return {
        "guild_id": str(parsed),
        "plan_id": str(plan_id),
        "operations": [
            {
                **dict(row),
                "id": str(row["id"]),
                "guild_id": str(row["guild_id"]),
                "plan_id": str(row["plan_id"]),
                "resource_discord_id": (
                    str(row["resource_discord_id"])
                    if row["resource_discord_id"] is not None
                    else None
                ),
                "predecessors": [str(value) for value in row["predecessors"]],
            }
            for row in rows
        ],
    }


@router.get("/{guild_id}/plans/{plan_id}/progress")
async def plan_progress(
    guild_id: str,
    plan_id: UUID,
    session: CurrentSessionDep,
    container: ServicesDep,
    after_sequence: int = 0,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(
        guild_id=parsed,
        session=session,
        container=container,
        capability=Capability.PLANS_CREATE,
    )
    events = await container.planning_repository.progress_since(
        parsed, plan_id, after_sequence=after_sequence
    )
    return {"guild_id": str(parsed), "plan_id": str(plan_id), "events": events}


@router.post("/{guild_id}/plans/{plan_id}/validate")
async def validate_plan(
    guild_id: str,
    plan_id: UUID,
    body: VersionCommand,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(
        guild_id=parsed,
        session=session,
        container=container,
        capability=Capability.PLANS_CREATE,
    )
    row, result = await container.planning.validate(
        guild_id=parsed,
        plan_id=plan_id,
        actor_user_id=session.discord_user_id,
        expected_version=body.expected_version,
        correlation_id=_correlation(request),
        actor_authorization_fresh=True,
    )
    return {
        "plan": _plan_response(row),
        "preflight": {
            "allowed": result.allowed,
            "errors": list(result.errors),
            "warnings": list(result.warnings),
            "checked_capabilities": list(result.checked_capabilities),
            "limits_version": result.limits_version,
        },
    }


@router.post("/{guild_id}/plans/{plan_id}/confirm")
async def confirm_plan(
    guild_id: str,
    plan_id: UUID,
    body: ConfirmationCommand,
    request: Request,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(
        guild_id=parsed,
        session=session,
        container=container,
        capability=Capability.PLANS_APPLY,
    )
    exact_ack = f"CONFIRM DESTRUCTIVE {body.plan_hash}"
    row = await container.planning.confirm(
        guild_id=parsed,
        plan_id=plan_id,
        actor_user_id=session.discord_user_id,
        idempotency_key=idempotency_key,
        expected_version=body.expected_version,
        supplied_plan_hash=body.plan_hash,
        reinforced_acknowledgement=body.acknowledgement == exact_ack,
        correlation_id=_correlation(request),
    )
    return _plan_response(row)


@router.post("/{guild_id}/plans/{plan_id}/apply", status_code=status.HTTP_202_ACCEPTED)
async def apply_plan(
    guild_id: str,
    plan_id: UUID,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, str]:
    parsed = parse_snowflake(guild_id)
    await _authorize(
        guild_id=parsed,
        session=session,
        container=container,
        capability=Capability.PLANS_APPLY,
    )
    job_id = await container.planning.apply(
        guild_id=parsed,
        plan_id=plan_id,
        actor_user_id=session.discord_user_id,
        correlation_id=_correlation(request),
    )
    return {"guild_id": str(parsed), "plan_id": str(plan_id), "job_id": str(job_id)}


@router.post("/{guild_id}/plans/{plan_id}/cancel")
async def cancel_plan(
    guild_id: str,
    plan_id: UUID,
    request: Request,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(
        guild_id=parsed,
        session=session,
        container=container,
        capability=Capability.PLANS_APPLY,
    )
    row = await container.planning_repository.request_cancel(
        guild_id=parsed,
        plan_id=plan_id,
        actor_user_id=session.discord_user_id,
        correlation_id=_correlation(request),
    )
    return _plan_response(row)


def invalid_planning_input(exc: ValueError) -> ApiProblem:
    del exc
    return ApiProblem(
        status_code=422,
        code="PLAN_INPUT_INVALID",
        message_key="errors.plans.inputInvalid",
    )
