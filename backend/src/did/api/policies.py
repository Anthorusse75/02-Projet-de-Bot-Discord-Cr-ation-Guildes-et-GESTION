from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from did.api.dependencies import CsrfSessionDep, CurrentSessionDep, ServicesDep
from did.api.guilds import parse_snowflake
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


class PolicyPatch(PolicyDefinitionInput):
    expected_revision: int = Field(ge=1)


class PolicyTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


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
        )
    )


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
        "activate",
        Capability.POLICIES_ACTIVATE,
    )


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
