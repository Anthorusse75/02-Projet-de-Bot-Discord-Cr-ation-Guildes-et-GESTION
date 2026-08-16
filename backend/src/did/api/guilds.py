from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from did.api.dependencies import (
    ApiProblem,
    CsrfSessionDep,
    CurrentSessionDep,
    ServicesDep,
)
from did.application.auth.service import AuthorizationDenied
from did.application.installations.service import TargetIdentityRequired
from did.domain.auth import (
    AuthorizationScope,
    Capability,
    InstallationStatus,
    PlatformRole,
    ScopeKind,
    bootstrap_allowed,
)
from did.oauth.models import DiscordGuild

router = APIRouter(prefix="/api/v1/guilds", tags=["guilds"])


class ScopedUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_kind: ScopeKind
    scope_id: str

    @model_validator(mode="after")
    def validate_scope_pair(self) -> "ScopedUpdate":
        AuthorizationScope(self.scope_kind, self.scope_id)
        return self

    def authorization_scope(self) -> AuthorizationScope:
        return AuthorizationScope(self.scope_kind, self.scope_id)


class UserAccessUpdate(ScopedUpdate):
    discord_user_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    platform_role: PlatformRole
    revoked: bool = False


class RoleBindingUpdate(ScopedUpdate):
    discord_role_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    platform_role: PlatformRole


@router.get("")
async def guilds(
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, object]:
    discovered = await container.authorization.guilds_for_user(session.discord_user_id)
    items: list[dict[str, object]] = []
    refreshed: dict[int, DiscordGuild] | None = None
    for guild in discovered:
        installation = None
        try:
            decision = await container.authorization.authorize(
                discord_user_id=session.discord_user_id,
                guild_id=guild.guild_id,
                capability=Capability.TENANT_READ,
                scope=AuthorizationScope.guild(),
                require_active_installation=False,
            )
            installation = decision.installation
        except AuthorizationDenied:
            if bootstrap_allowed(owner=guild.owner, permissions=guild.permissions):
                if refreshed is None:
                    fresh_guilds = await container.authorization.guilds_for_user(
                        session.discord_user_id, force_refresh=True
                    )
                    refreshed = {item.guild_id: item for item in fresh_guilds}
                fresh = refreshed.get(guild.guild_id)
                if fresh is not None and bootstrap_allowed(
                    owner=fresh.owner, permissions=fresh.permissions
                ):
                    candidate = await container.repository.get_installation(
                        guild.guild_id, session.discord_user_id
                    )
                    if (
                        candidate is not None
                        and candidate.status is InstallationStatus.PENDING_SETUP
                    ):
                        installation = candidate
        if installation is None:
            continue
        items.append(
            {
                "guild_id": str(guild.guild_id),
                "name": guild.name,
                "icon_hash": guild.icon_hash,
                "owner": guild.owner,
                "permissions": str(guild.permissions),
                "installation_status": installation.status.value,
            }
        )
    return {"guilds": items}


@router.post("/{guild_id}/select")
async def select_guild(
    guild_id: str,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, object]:
    parsed = parse_snowflake(guild_id)
    try:
        await container.authorization.authorize(
            discord_user_id=session.discord_user_id,
            guild_id=parsed,
            capability=Capability.TENANT_READ,
            scope=AuthorizationScope.guild(),
        )
    except AuthorizationDenied as exc:
        if exc.code == "INSTALLATION_NOT_ACTIVE":
            raise
        discovery = await container.authorization.discovery(
            session.discord_user_id, parsed, force_refresh=True
        )
        installation = None
        if discovery.can_bootstrap:
            installation = await container.repository.get_installation(
                parsed, session.discord_user_id
            )
        if installation is None or installation.status is not InstallationStatus.PENDING_SETUP:
            raise AuthorizationDenied("TENANT_ACCESS_DENIED") from None
    updated = await container.sessions.select_guild(session, parsed)
    return {
        "guild_id": str(parsed),
        "csrf_token": updated.csrf_token,
        "policy_version": updated.policy_version,
    }


@router.get("/{guild_id}/installation")
async def installation(
    guild_id: str,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, object]:
    parsed = parse_snowflake(guild_id)
    try:
        decision = await container.authorization.authorize(
            discord_user_id=session.discord_user_id,
            guild_id=parsed,
            capability=Capability.TENANT_READ,
            scope=AuthorizationScope.guild(),
            require_active_installation=False,
        )
        record = decision.installation
    except AuthorizationDenied:
        discovery = await container.authorization.discovery(
            session.discord_user_id, parsed, force_refresh=True
        )
        record = None
        if discovery.can_bootstrap:
            candidate = await container.repository.get_installation(parsed, session.discord_user_id)
            if candidate is not None and candidate.status is InstallationStatus.PENDING_SETUP:
                record = candidate
    if record is None:
        raise ApiProblem(
            status_code=404,
            code="INSTALLATION_NOT_FOUND",
            message_key="errors.installation.notFound",
        )
    return {
        "guild_id": str(record.guild_id),
        "status": record.status.value,
        "name": record.name,
        "version": record.version,
    }


@router.post("/{guild_id}/bootstrap")
async def bootstrap(
    guild_id: str,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, object]:
    parsed = parse_snowflake(guild_id)
    activated = await container.installations.bootstrap(
        guild_id=parsed, actor_user_id=session.discord_user_id
    )
    return {"guild_id": str(activated.guild_id), "status": activated.status.value}


@router.delete("/{guild_id}/installation", status_code=204)
async def uninstall(
    guild_id: str,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> None:
    await container.installations.uninstall(
        guild_id=parse_snowflake(guild_id),
        actor_user_id=session.discord_user_id,
    )


@router.put("/{guild_id}/rbac/users")
async def set_user_access(
    guild_id: str,
    body: UserAccessUpdate,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, object]:
    parsed = parse_snowflake(guild_id)
    try:
        await container.installations.delegate_user(
            guild_id=parsed,
            actor_user_id=session.discord_user_id,
            target_user_id=parse_snowflake(body.discord_user_id),
            role=body.platform_role,
            scope=body.authorization_scope(),
            revoke=body.revoked,
        )
    except TargetIdentityRequired as exc:
        raise ApiProblem(
            status_code=409,
            code="TARGET_DID_IDENTITY_REQUIRED",
            message_key="errors.rbac.targetIdentityRequired",
        ) from exc
    return {"status": "REVOKED" if body.revoked else "ACTIVE"}


@router.put("/{guild_id}/rbac/roles")
async def set_role_binding(
    guild_id: str,
    body: RoleBindingUpdate,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, object]:
    parsed = parse_snowflake(guild_id)
    await container.installations.bind_role(
        guild_id=parsed,
        actor_user_id=session.discord_user_id,
        discord_role_id=parse_snowflake(body.discord_role_id),
        role=body.platform_role,
        scope=body.authorization_scope(),
    )
    return {"status": "ACTIVE"}


@router.delete("/{guild_id}/rbac/roles/{discord_role_id}", status_code=204)
async def delete_role_binding(
    guild_id: str,
    discord_role_id: str,
    scope_kind: ScopeKind,
    scope_id: str,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> None:
    try:
        scope = AuthorizationScope(scope_kind, scope_id)
    except ValueError as exc:
        raise ApiProblem(
            status_code=422,
            code="RBAC_SCOPE_INVALID",
            message_key="errors.rbac.scopeInvalid",
        ) from exc
    await container.installations.unbind_role(
        guild_id=parse_snowflake(guild_id),
        actor_user_id=session.discord_user_id,
        discord_role_id=parse_snowflake(discord_role_id),
        scope=scope,
    )


def parse_snowflake(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ApiProblem(
            status_code=422, code="SNOWFLAKE_INVALID", message_key="errors.input.snowflake"
        ) from exc
    if parsed <= 0 or parsed > 2**64 - 1:
        raise ApiProblem(
            status_code=422, code="SNOWFLAKE_INVALID", message_key="errors.input.snowflake"
        )
    return parsed


def authorization_problem(exc: AuthorizationDenied) -> ApiProblem:
    status = 404 if exc.code in {"INSTALLATION_NOT_FOUND", "TENANT_ACCESS_DENIED"} else 403
    return ApiProblem(
        status_code=status,
        code=exc.code,
        message_key="errors.authorization.denied",
    )
