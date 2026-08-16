import logging

from did.application.auth.service import AuthorizationDenied, AuthorizationService
from did.domain.auth import (
    AccessStatus,
    AuthorizationScope,
    Capability,
    InstallationStatus,
    PlatformRole,
)
from did.infrastructure.auth_repository import AuthRepository, InstallationRecord
from did.infrastructure.logging import EventId, emit_event

logger = logging.getLogger(__name__)


class TargetIdentityRequired(RuntimeError):
    pass


class InstallationService:
    def __init__(self, *, authorization: AuthorizationService, repository: AuthRepository) -> None:
        self.authorization = authorization
        self.repository = repository

    async def record_detected(
        self,
        *,
        guild_id: int,
        name: str,
        icon_hash: str | None,
        owner_id: int | None,
        application_id: int,
        bot_user_id: int,
    ) -> None:
        await self.repository.record_installation(
            guild_id=guild_id,
            name=name,
            icon_hash=icon_hash,
            owner_id=owner_id,
            application_id=application_id,
            bot_user_id=bot_user_id,
        )
        emit_event(
            logger,
            logging.INFO,
            EventId.INSTALLATION_DETECTED,
            fields={"guild_id": guild_id},
        )

    async def bootstrap(self, *, guild_id: int, actor_user_id: int) -> InstallationRecord:
        discovery = await self.authorization.discovery(actor_user_id, guild_id, force_refresh=True)
        if not discovery.can_bootstrap:
            raise AuthorizationDenied("BOOTSTRAP_OWNER_OR_ADMINISTRATOR_REQUIRED")
        installation = await self.repository.get_installation(guild_id, actor_user_id)
        if installation is None:
            raise AuthorizationDenied("INSTALLATION_NOT_FOUND")
        if installation.status is InstallationStatus.ACTIVE:
            await self.authorization.authorize(
                discord_user_id=actor_user_id,
                guild_id=guild_id,
                capability=Capability.TENANT_READ,
                scope=AuthorizationScope.guild(),
            )
            return installation
        await self.repository.activate_and_create_owner(guild_id, actor_user_id)
        emit_event(
            logger,
            logging.INFO,
            EventId.INSTALLATION_BOOTSTRAPPED,
            fields={"guild_id": guild_id, "user_id": actor_user_id},
        )
        activated = await self.repository.get_installation(guild_id, actor_user_id)
        if activated is None:
            raise RuntimeError("installation disappeared after bootstrap")
        return activated

    async def uninstall(self, *, guild_id: int, actor_user_id: int) -> None:
        await self.authorization.authorize(
            discord_user_id=actor_user_id,
            guild_id=guild_id,
            capability=Capability.RBAC_WRITE,
            scope=AuthorizationScope.guild(),
            sensitive=True,
        )
        await self.repository.mark_uninstalled(guild_id, actor_user_id)
        emit_event(
            logger,
            logging.INFO,
            EventId.INSTALLATION_UNINSTALLED,
            fields={"guild_id": guild_id, "user_id": actor_user_id},
        )

    async def delegate_user(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        target_user_id: int,
        role: PlatformRole,
        scope: AuthorizationScope,
        revoke: bool = False,
    ) -> None:
        await self.authorization.authorize(
            discord_user_id=actor_user_id,
            guild_id=guild_id,
            capability=Capability.RBAC_WRITE,
            scope=scope,
            sensitive=True,
        )
        if role is PlatformRole.OWNER:
            raise AuthorizationDenied("OWNER_DELEGATION_NOT_SUPPORTED")
        if await self.repository.get_user(target_user_id) is None:
            raise TargetIdentityRequired("target user must already have a DID identity")
        existing = await self.repository.get_access(guild_id, target_user_id, scope)
        if existing is not None and existing.platform_role is PlatformRole.OWNER:
            raise AuthorizationDenied("OWNER_ACCESS_IMMUTABLE")
        await self.repository.save_user_access(
            guild_id=guild_id,
            target_user_id=target_user_id,
            role=role,
            actor_user_id=actor_user_id,
            scope=scope,
            status=AccessStatus.REVOKED if revoke else AccessStatus.ACTIVE,
        )
        emit_event(
            logger,
            logging.INFO,
            EventId.RBAC_CHANGED,
            fields={"guild_id": guild_id, "user_id": actor_user_id},
        )

    async def bind_role(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        discord_role_id: int,
        role: PlatformRole,
        scope: AuthorizationScope,
    ) -> None:
        await self.authorization.authorize(
            discord_user_id=actor_user_id,
            guild_id=guild_id,
            capability=Capability.RBAC_WRITE,
            scope=scope,
            sensitive=True,
        )
        if role is PlatformRole.OWNER:
            raise AuthorizationDenied("OWNER_ROLE_BINDING_NOT_SUPPORTED")
        await self.repository.save_role_binding(
            guild_id=guild_id,
            discord_role_id=discord_role_id,
            dashboard_role=role,
            actor_user_id=actor_user_id,
            scope=scope,
        )
        emit_event(
            logger,
            logging.INFO,
            EventId.RBAC_CHANGED,
            fields={"guild_id": guild_id, "user_id": actor_user_id},
        )

    async def unbind_role(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        discord_role_id: int,
        scope: AuthorizationScope,
    ) -> None:
        await self.authorization.authorize(
            discord_user_id=actor_user_id,
            guild_id=guild_id,
            capability=Capability.RBAC_WRITE,
            scope=scope,
            sensitive=True,
        )
        await self.repository.delete_role_binding(
            guild_id=guild_id,
            discord_role_id=discord_role_id,
            actor_user_id=actor_user_id,
            scope=scope,
        )
        emit_event(
            logger,
            logging.INFO,
            EventId.RBAC_CHANGED,
            fields={"guild_id": guild_id, "user_id": actor_user_id},
        )
