from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, status
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
from did.domain.discord_runtime import WorkloadJob, WorkloadPriority
from did.infrastructure.stage04_repository import Stage04NotFound
from did.oauth.models import DiscordGuild
from did.permissions.capabilities import BotCapabilityChecker, BotOperation

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
    """Return installed Guilds visible to the OAuth identity.

    Discovery itself is the caller's Discord `/users/@me/guilds` snapshot.  The
    endpoint deliberately does not force one Discord refresh per Guild: that was
    both noisy and made the first dashboard page fragile.  Sensitive bootstrap
    decisions are revalidated by the onboarding endpoints below.
    """

    discovered = await container.authorization.guilds_for_user(session.discord_user_id)
    items: list[dict[str, object]] = []
    for guild in discovered:
        installation = await container.repository.get_installation(
            guild.guild_id, session.discord_user_id
        )
        if installation is None:
            # DID is not known to be installed in this Guild.  Never invent an
            # installation merely because OAuth says the user belongs to it.
            continue

        dashboard_access = False
        try:
            await container.authorization.authorize(
                discord_user_id=session.discord_user_id,
                guild_id=guild.guild_id,
                capability=Capability.TENANT_READ,
                scope=AuthorizationScope.guild(),
                require_active_installation=False,
            )
            dashboard_access = True
        except AuthorizationDenied:
            pass

        can_bootstrap = (
            installation.status is InstallationStatus.PENDING_SETUP
            and bootstrap_allowed(owner=guild.owner, permissions=guild.permissions)
        )
        blocked_reason = None
        if not dashboard_access and not can_bootstrap:
            blocked_reason = (
                "BOOTSTRAP_OWNER_OR_ADMINISTRATOR_REQUIRED"
                if installation.status is InstallationStatus.PENDING_SETUP
                else "TENANT_ACCESS_DENIED"
            )

        items.append(
            {
                "guild_id": str(guild.guild_id),
                "name": guild.name,
                "icon_hash": guild.icon_hash,
                "owner": guild.owner,
                "permissions": str(guild.permissions),
                "installation_status": installation.status.value,
                "dashboard_access": dashboard_access,
                "can_bootstrap": can_bootstrap,
                "blocked_reason": blocked_reason,
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


async def _onboarding_snapshot(
    *,
    guild_id: int,
    actor_user_id: int,
    container: ServicesDep,
    force_discovery: bool,
) -> dict[str, object]:
    discovery = await container.authorization.discovery(
        actor_user_id, guild_id, force_refresh=force_discovery
    )
    record = await container.repository.get_installation(guild_id, actor_user_id)
    if record is None:
        raise ApiProblem(
            status_code=404,
            code="INSTALLATION_NOT_FOUND",
            message_key="errors.installation.notFound",
        )

    can_bootstrap = discovery.can_bootstrap
    bot_id, _ = await container.stage04_repository.bot_identity(guild_id)
    coverage = "UNKNOWN"
    freshness = "UNKNOWN"
    channel_count = 0
    role_count = 0
    permissions_checked = False
    bot_operations: dict[str, dict[str, object]] = {}

    if bot_id is not None:
        try:
            guild_snapshot, bot_member = await container.stage04_repository.guild_snapshot(
                guild_id, bot_id
            )
        except Stage04NotFound:
            pass
        else:
            coverage = guild_snapshot.coverage.mode.value
            freshness = guild_snapshot.freshness.state.value
            channel_count = len(guild_snapshot.channels)
            role_count = len(guild_snapshot.roles)
            checker = BotCapabilityChecker()
            for operation in BotOperation:
                # Onboarding asks "would Discord allow this?" independently
                # from the DID installation state that is about to become ACTIVE.
                decision = checker.check(
                    operation=operation,
                    guild=guild_snapshot,
                    bot=bot_member,
                    installation_active=True,
                )
                bot_operations[operation.value] = {
                    "outcome": decision.outcome.value,
                    "required_permissions": list(decision.required_permissions),
                    "causes": list(decision.causes),
                    "remediations": list(decision.remediations),
                    "warnings": list(decision.warnings),
                }
            permissions_checked = True

    structure_imported = coverage == "FULL"
    pending = record.status is InstallationStatus.PENDING_SETUP
    active = record.status is InstallationStatus.ACTIVE
    ready_to_activate = bool(
        pending and can_bootstrap and bot_id is not None and structure_imported and permissions_checked
    )
    blocked_reason = None
    if pending and not can_bootstrap:
        blocked_reason = "BOOTSTRAP_OWNER_OR_ADMINISTRATOR_REQUIRED"
    elif bot_id is None:
        blocked_reason = "BOT_GATEWAY_IDENTITY_NOT_OBSERVED"
    elif not structure_imported:
        blocked_reason = "INITIAL_STRUCTURE_IMPORT_REQUIRED"
    elif not permissions_checked:
        blocked_reason = "BOT_PERMISSIONS_NOT_VERIFIED"

    return {
        "guild_id": str(guild_id),
        "name": record.name,
        "installation_status": record.status.value,
        "can_bootstrap": can_bootstrap,
        "bot_present": bot_id is not None,
        "bot_user_id": str(bot_id) if bot_id is not None else None,
        "configurator_verified": can_bootstrap or active,
        "structure_imported": structure_imported,
        "channel_count": channel_count,
        "role_count": role_count,
        "coverage": coverage,
        "freshness": freshness,
        "permissions_checked": permissions_checked,
        "bot_operations": bot_operations,
        "initial_audit_complete": permissions_checked,
        "dashboard_configuration_ready": True,
        "ready_to_activate": ready_to_activate,
        "complete": active,
        "blocked_reason": blocked_reason,
    }


@router.get("/{guild_id}/onboarding")
async def onboarding_status(
    guild_id: str,
    session: CurrentSessionDep,
    container: ServicesDep,
) -> dict[str, object]:
    return await _onboarding_snapshot(
        guild_id=parse_snowflake(guild_id),
        actor_user_id=session.discord_user_id,
        container=container,
        force_discovery=False,
    )


@router.post("/{guild_id}/onboarding/import", status_code=status.HTTP_202_ACCEPTED)
async def onboarding_import(
    guild_id: str,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, object]:
    parsed = parse_snowflake(guild_id)
    snapshot = await _onboarding_snapshot(
        guild_id=parsed,
        actor_user_id=session.discord_user_id,
        container=container,
        force_discovery=True,
    )
    if snapshot["installation_status"] == InstallationStatus.ACTIVE.value:
        return {"guild_id": str(parsed), "status": "ALREADY_ACTIVE", "job_id": None}
    if not snapshot["can_bootstrap"]:
        raise AuthorizationDenied("BOOTSTRAP_OWNER_OR_ADMINISTRATOR_REQUIRED")

    job = WorkloadJob(
        uuid4(),
        parsed,
        "INITIAL_SYNC",
        f"onboarding:initial-sync:{parsed}",
        WorkloadPriority.USER_REFRESH,
        datetime.now(UTC),
    )
    job_id = await container.runtime_repository.enqueue_job(
        job,
        requested_by=session.discord_user_id,
        correlation_id=uuid4(),
    )
    return {"guild_id": str(parsed), "status": "PENDING", "job_id": str(job_id)}


@router.post("/{guild_id}/onboarding/activate")
async def onboarding_activate(
    guild_id: str,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> dict[str, object]:
    parsed = parse_snowflake(guild_id)
    snapshot = await _onboarding_snapshot(
        guild_id=parsed,
        actor_user_id=session.discord_user_id,
        container=container,
        force_discovery=True,
    )
    if snapshot["complete"]:
        return snapshot
    if not snapshot["can_bootstrap"]:
        raise AuthorizationDenied("BOOTSTRAP_OWNER_OR_ADMINISTRATOR_REQUIRED")
    if not snapshot["ready_to_activate"]:
        raise ApiProblem(
            status_code=409,
            code="ONBOARDING_NOT_READY",
            message_key="errors.onboarding.notReady",
            params={"reason": str(snapshot["blocked_reason"] or "UNKNOWN")},
        )
    await container.installations.bootstrap(
        guild_id=parsed, actor_user_id=session.discord_user_id
    )
    return await _onboarding_snapshot(
        guild_id=parsed,
        actor_user_id=session.discord_user_id,
        container=container,
        force_discovery=False,
    )


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


@router.delete("/{guild_id}/installation/purge", status_code=204)
async def purge_installation(
    guild_id: str,
    session: CsrfSessionDep,
    container: ServicesDep,
) -> None:
    await container.installations.purge_tenant(
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
    status_code = 404 if exc.code in {"INSTALLATION_NOT_FOUND", "TENANT_ACCESS_DENIED"} else 403
    return ApiProblem(
        status_code=status_code,
        code=exc.code,
        message_key="errors.authorization.denied",
    )
