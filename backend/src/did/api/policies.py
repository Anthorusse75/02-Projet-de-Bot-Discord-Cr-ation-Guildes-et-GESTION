from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator

from did.api.dependencies import ApiProblem, CsrfSessionDep, CurrentSessionDep, ServicesDep
from did.api.guilds import parse_snowflake
from did.api.stage05 import _plan_response
from did.application.policies.service import BulkPolicyDraftDefinition, PolicyService
from did.domain.auth import AuthorizationScope, Capability
from did.domain.policies import Policy, PolicyScopeType, PolicyVersion

router = APIRouter(prefix="/api/v1/guilds", tags=["policies"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=160)]


class PolicyDefinitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    scope_type: PolicyScopeType
    scope_id: str | None = Field(default=None, max_length=64)
    conditions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    effects: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    metadata: dict[str, Any]

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value


class PolicyCreate(PolicyDefinitionInput):
    policy_type: str = Field(min_length=1, max_length=64)
    contract_version: int = Field(ge=1)
    priority: int = Field(default=0, ge=-1_000_000, le=1_000_000)


class PolicyPatch(PolicyDefinitionInput):
    expected_revision: int = Field(ge=1)
    priority: int | None = Field(default=None, ge=-1_000_000, le=1_000_000)


class PolicyTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


class PolicyActivation(PolicyTransition):
    plan_id: UUID


class PolicyPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


MAX_MATRIX_ROLES = 50
MAX_MATRIX_RESOURCES = 150
MAX_BULK_POLICIES = 100


class AccessMatrixRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_ids: list[str] = Field(min_length=1, max_length=MAX_MATRIX_ROLES)
    resource_ids: list[str] = Field(min_length=1, max_length=MAX_MATRIX_RESOURCES)


class BulkPolicyPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definitions: list[PolicyCreate] = Field(min_length=1, max_length=MAX_BULK_POLICIES)

    @field_validator("definitions")
    @classmethod
    def unique_targets(cls, values: list[PolicyCreate]) -> list[PolicyCreate]:
        targets = [(value.scope_type, value.scope_id) for value in values]
        if len(set(targets)) != len(targets):
            raise ValueError("bulk Policy targets must be unique")
        supported = {PolicyScopeType.CATEGORY, PolicyScopeType.CHANNEL}
        if any(value.scope_type not in supported for value in values):
            raise ValueError("bulk Policy targets must be categories or channels")
        return values


class BulkPolicyPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_id: UUID
    expected_revision: int = Field(ge=1)


class BulkPolicyPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policies: list[BulkPolicyPlanItem] = Field(min_length=1, max_length=MAX_BULK_POLICIES)

    @field_validator("policies")
    @classmethod
    def unique_policies(cls, values: list[BulkPolicyPlanItem]) -> list[BulkPolicyPlanItem]:
        if len({value.policy_id for value in values}) != len(values):
            raise ValueError("bulk Policy ids must be unique")
        return values


class PolicyResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_id: str
    target_scope_type: Literal[
        PolicyScopeType.GUILD,
        PolicyScopeType.LOGICAL_GROUP,
        PolicyScopeType.CATEGORY,
        PolicyScopeType.CHANNEL,
    ]
    target_scope_id: str | None = Field(default=None, max_length=64)
    requested_access: Literal["VIEW", "WRITE", "MANAGE", "CONNECT", "SPEAK"]

    @field_validator("subject_id")
    @classmethod
    def subject_snowflake(cls, value: str) -> str:
        return str(parse_snowflake(value))


def _policy(value: Policy) -> dict[str, Any]:
    return {
        "policy_id": str(value.policy_id),
        "guild_id": str(value.guild_id),
        "policy_type": value.policy_type,
        "contract_version": value.contract_version,
        "name": value.name,
        "description": value.description,
        "lifecycle_state": value.lifecycle_state.value,
        "revision": value.revision,
        "priority": value.priority,
        "scope_type": value.scope_type.value,
        "scope_id": value.scope_id,
        "conditions": list(value.conditions),
        "effects": list(value.effects),
        "metadata": value.metadata,
        "created_by_user_id": str(value.created_by_user_id),
        "modified_by_user_id": str(value.modified_by_user_id),
        "created_at": value.created_at,
        "updated_at": value.updated_at,
        "activated_at": value.activated_at,
        "disabled_at": value.disabled_at,
        "retired_at": value.retired_at,
    }


def _version(value: PolicyVersion) -> dict[str, Any]:
    return {
        "version_id": str(value.version_id),
        "guild_id": str(value.guild_id),
        "policy_id": str(value.policy_id),
        "revision": value.revision,
        "change_kind": value.change_kind,
        "snapshot": value.snapshot,
        "author_user_id": str(value.author_user_id),
        "correlation_id": str(value.correlation_id),
        "idempotency_key": value.idempotency_key,
        "created_at": value.created_at,
    }


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


@router.get("/{guild_id}/policies")
async def list_policies(
    guild_id: str, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.POLICIES_READ)
    values = await container.policies.list(parsed)
    return {"guild_id": guild_id, "policies": [_policy(value) for value in values]}


@router.get("/{guild_id}/policies/{policy_id}")
async def get_policy(
    guild_id: str, policy_id: UUID, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.POLICIES_READ)
    return _policy(await container.policies.get(parsed, policy_id))


@router.get("/{guild_id}/policies/{policy_id}/versions")
async def get_policy_versions(
    guild_id: str, policy_id: UUID, session: CurrentSessionDep, container: ServicesDep
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.POLICIES_READ)
    values = await container.policies.versions(parsed, policy_id)
    return {
        "guild_id": guild_id,
        "policy_id": str(policy_id),
        "versions": [_version(v) for v in values],
    }


@router.post("/{guild_id}/policies", status_code=status.HTTP_201_CREATED)
async def create_policy(
    guild_id: str,
    body: PolicyCreate,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.POLICIES_CREATE, sensitive=True)
    return _policy(
        await container.policies.create_draft(
            guild_id=parsed,
            actor_id=session.discord_user_id,
            policy_type=body.policy_type,
            contract_version=body.contract_version,
            name=body.name,
            description=body.description,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            conditions=body.conditions,
            effects=body.effects,
            metadata=body.metadata,
            idempotency_key=idempotency_key,
            priority=body.priority,
        )
    )


@router.patch("/{guild_id}/policies/{policy_id}")
async def update_policy(
    guild_id: str,
    policy_id: UUID,
    body: PolicyPatch,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.POLICIES_UPDATE, sensitive=True)
    return _policy(
        await container.policies.update_draft(
            guild_id=parsed,
            policy_id=policy_id,
            actor_id=session.discord_user_id,
            expected_revision=body.expected_revision,
            name=body.name,
            description=body.description,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            conditions=body.conditions,
            effects=body.effects,
            metadata=body.metadata,
            idempotency_key=idempotency_key,
            priority=body.priority,
        )
    )


@router.post("/{guild_id}/policy-resolution")
async def resolve_policy(
    guild_id: str,
    body: PolicyResolutionRequest,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    """Explain a cache-first decision; this endpoint has no mutation semantics."""

    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.POLICIES_READ)
    resolution = await container.policies.resolve_access(
        guild_id=parsed,
        subject_id=parse_snowflake(body.subject_id),
        target_scope_type=PolicyScopeType(body.target_scope_type),
        target_scope_id=body.target_scope_id,
        requested_access=body.requested_access,
    )
    encoded = jsonable_encoder(resolution)
    assert isinstance(encoded, dict)
    return encoded


@router.post("/{guild_id}/access-matrix/resolve")
async def resolve_access_matrix(
    guild_id: str,
    body: AccessMatrixRequest,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    """Batch role x resource access synthesis (REQ-AP-MAT-001..004).

    Read-only: delegates entirely to the canonical `PermissionEvaluator` and
    `PolicyResolver` after a single Guild/Policies/logical-groups read. No
    Discord call, no mutation, no second permission or Policy calculation.
    """

    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.POLICIES_READ)
    await _authorize(parsed, session, container, Capability.PERMISSIONS_READ)
    role_ids = tuple(parse_snowflake(value) for value in body.role_ids)
    resource_ids = tuple(parse_snowflake(value) for value in body.resource_ids)
    if len(set(role_ids)) != len(role_ids):
        raise ApiProblem(
            status_code=422, code="DUPLICATE_ROLE_ID", message_key="errors.input.duplicate"
        )
    if len(set(resource_ids)) != len(resource_ids):
        raise ApiProblem(
            status_code=422, code="DUPLICATE_RESOURCE_ID", message_key="errors.input.duplicate"
        )
    result = await container.policies.resolve_matrix(
        guild_id=parsed,
        actor_user_id=session.discord_user_id,
        role_ids=role_ids,
        resource_ids=resource_ids,
    )
    encoded = jsonable_encoder(result)
    assert isinstance(encoded, dict)
    return encoded


@router.post("/{guild_id}/policies/bulk-preview", status_code=status.HTTP_201_CREATED)
async def preview_bulk_policies(
    guild_id: str,
    body: BulkPolicyPreviewRequest,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    """Create explicit retry-safe DRAFTs, then preview them in one bounded call."""

    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.POLICIES_CREATE, sensitive=True)
    await _authorize(parsed, session, container, Capability.POLICIES_READ)
    definitions = tuple(
        BulkPolicyDraftDefinition(
            policy_type=value.policy_type,
            contract_version=value.contract_version,
            name=value.name,
            description=value.description,
            scope_type=value.scope_type,
            scope_id=value.scope_id,
            conditions=value.conditions,
            effects=value.effects,
            metadata=value.metadata,
            priority=value.priority,
        )
        for value in body.definitions
    )
    drafts = await container.policies.create_bulk_drafts(
        guild_id=parsed,
        actor_id=session.discord_user_id,
        definitions=definitions,
        idempotency_key=idempotency_key,
    )
    previews = await container.policy_planning.preview_many(
        guild_id=parsed,
        policy_ids=tuple(draft.policy_id for draft in drafts),
        actor_user_id=session.discord_user_id,
    )
    return {
        "operation_id": PolicyService.bulk_operation_id(idempotency_key),
        "draft_count": len(drafts),
        "discord_mutations": 0,
        "items": [
            {"policy": _policy(draft), "preview": jsonable_encoder(preview)}
            for draft, preview in zip(drafts, previews, strict=True)
        ],
    }


@router.post("/{guild_id}/policies/bulk-plan", status_code=status.HTTP_201_CREATED)
async def plan_bulk_policies(
    guild_id: str,
    body: BulkPolicyPlanRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    """Prepare one canonical Policy Plan per DRAFT, never apply it."""

    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.POLICIES_ACTIVATE, sensitive=True)
    await _authorize(parsed, session, container, Capability.PLANS_CREATE, sensitive=True)
    items = tuple(
        (
            value.policy_id,
            value.expected_revision,
            PolicyService.bulk_child_key(
                idempotency_key, "plan", str(value.policy_id), str(value.expected_revision)
            ),
        )
        for value in body.policies
    )
    results = await container.policy_planning.create_plans(
        guild_id=parsed,
        items=items,
        actor_user_id=session.discord_user_id,
        correlation_id=UUID(str(request.state.correlation_id)),
    )
    response_items = []
    for preview, plan, created, preflight in results:
        response_items.append(
            {
                "policy_id": str(preview.policy_id),
                "created": created,
                "plan": _plan_response(plan),
                "preflight": {
                    "allowed": preflight.allowed,
                    "errors": list(preflight.errors),
                    "warnings": list(preflight.warnings),
                    "checked_capabilities": list(preflight.checked_capabilities),
                    "limits_version": preflight.limits_version,
                    "policy_explanations": list(preflight.policy_explanations),
                },
            }
        )
    return {
        "prepared_count": len(response_items),
        "discord_mutations": 0,
        "items": response_items,
    }


@router.post("/{guild_id}/policies/{policy_id}/preview")
async def preview_policy(
    guild_id: str,
    policy_id: UUID,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    """Simulate a DRAFT Policy without persisting or mutating anything."""

    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.POLICIES_READ)
    preview = await container.policy_planning.preview(
        guild_id=parsed,
        policy_id=policy_id,
        actor_user_id=session.discord_user_id,
    )
    encoded = jsonable_encoder(preview)
    assert isinstance(encoded, dict)
    return encoded


@router.post("/{guild_id}/policies/{policy_id}/plan", status_code=status.HTTP_201_CREATED)
async def plan_policy(
    guild_id: str,
    policy_id: UUID,
    body: PolicyPlanRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    """Compile a preview to the canonical DSG/Plan and run canonical preflight."""

    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.POLICIES_ACTIVATE, sensitive=True)
    await _authorize(parsed, session, container, Capability.PLANS_CREATE, sensitive=True)
    preview, plan, created, preflight = await container.policy_planning.create_plan(
        guild_id=parsed,
        policy_id=policy_id,
        actor_user_id=session.discord_user_id,
        idempotency_key=idempotency_key,
        correlation_id=UUID(str(request.state.correlation_id)),
        expected_revision=body.expected_revision,
    )
    encoded_preview = jsonable_encoder(preview)
    assert isinstance(encoded_preview, dict)
    return {
        "created": created,
        "preview": encoded_preview,
        "plan": _plan_response(plan),
        "preflight": {
            "allowed": preflight.allowed,
            "errors": list(preflight.errors),
            "warnings": list(preflight.warnings),
            "checked_capabilities": list(preflight.checked_capabilities),
            "limits_version": preflight.limits_version,
            "policy_explanations": list(preflight.policy_explanations),
        },
    }


async def _transition(
    guild_id: str,
    policy_id: UUID,
    body: PolicyTransition,
    key: str,
    session: Any,
    container: Any,
    action: str,
    capability: Capability,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, capability, sensitive=True)
    method = getattr(container.policies, action)
    return _policy(
        await method(
            parsed,
            policy_id,
            session.discord_user_id,
            body.expected_revision,
            key,
        )
    )


@router.post("/{guild_id}/policies/{policy_id}/activate")
async def activate_policy(
    guild_id: str,
    policy_id: UUID,
    body: PolicyActivation,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    parsed = parse_snowflake(guild_id)
    await _authorize(parsed, session, container, Capability.POLICIES_ACTIVATE, sensitive=True)
    policy = await container.policies.activate(
        parsed,
        policy_id,
        session.discord_user_id,
        body.expected_revision,
        idempotency_key,
        body.plan_id,
    )
    plan = await container.planning_repository.get_plan(parsed, body.plan_id)
    response = _policy(policy)
    response["discord_application"] = {
        "plan_id": str(body.plan_id),
        "plan_status": str(plan["status"]),
        "applied_and_verified": str(plan["status"]) == "SUCCEEDED",
    }
    return response


@router.post("/{guild_id}/policies/{policy_id}/disable")
async def disable_policy(
    guild_id: str,
    policy_id: UUID,
    body: PolicyTransition,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    return await _transition(
        guild_id,
        policy_id,
        body,
        idempotency_key,
        session,
        container,
        "disable",
        Capability.POLICIES_ACTIVATE,
    )


@router.post("/{guild_id}/policies/{policy_id}/retire")
async def retire_policy(
    guild_id: str,
    policy_id: UUID,
    body: PolicyTransition,
    idempotency_key: IdempotencyKey,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, Any]:
    return await _transition(
        guild_id,
        policy_id,
        body,
        idempotency_key,
        session,
        container,
        "retire",
        Capability.POLICIES_RETIRE,
    )
