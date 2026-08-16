from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from did.api.dependencies import (
    ApiProblem,
    CsrfSessionDep,
    CurrentSessionDep,
    ServicesDep,
)
from did.application.auth.service import AuthorizationDenied
from did.domain.auth import Capability, InstallationStatus, PlatformRole

router = APIRouter(prefix="/api/v1/guilds", tags=["guilds"])


class UserAccessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    discord_user_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    platform_role: PlatformRole
    revoked: bool = False


class RoleBindingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    discord_role_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    platform_role: PlatformRole


@router.get("")
async def guilds(
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, object]:
    discovered = await container.authorization.guilds_for_user(session.discord_user_id)
    items: list[dict[str, object]] = []
    for guild in discovered:
        installation = await container.repository.get_installation(
            guild.guild_id, session.discord_user_id
        )
        items.append(
            {
                "guild_id": str(guild.guild_id),
                "name": guild.name,
                "icon_hash": guild.icon_hash,
                "owner": guild.owner,
                "permissions": str(guild.permissions),
                "installation_status": None if installation is None else installation.status.value,
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
    discovery = await container.authorization.discovery(session.discord_user_id, parsed)
    installation = await container.repository.get_installation(parsed, session.discord_user_id)
    can_setup = bool(
        installation
        and installation.status is InstallationStatus.PENDING_SETUP
        and discovery.can_bootstrap
    )
    if not can_setup:
        await container.authorization.authorize(
            discord_user_id=session.discord_user_id,
            guild_id=parsed,
            capability=Capability.TENANT_READ,
        )
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
    await container.authorization.discovery(session.discord_user_id, parsed)
    record = await container.repository.get_installation(parsed, session.discord_user_id)
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
    await container.installations.delegate_user(
        guild_id=parsed,
        actor_user_id=session.discord_user_id,
        target_user_id=parse_snowflake(body.discord_user_id),
        role=body.platform_role,
        revoke=body.revoked,
    )
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
    )
    return {"status": "ACTIVE"}


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
