import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from did.domain.auth import (
    AccessStatus,
    AuthorizationScope,
    InstallationStatus,
    PlatformRole,
    ScopeKind,
)
from did.infrastructure.database import tenant_transaction
from did.oauth.models import DiscordUser, EncryptedTokenSet, OAuthGrantRecord, OAuthTokenSet
from did.tenancy import TenantContext, UserContext


class ConcurrentGrantRefreshError(RuntimeError):
    pass


class InstallationIdentityMismatch(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class UserRecord:
    discord_user_id: int
    username: str
    global_name: str | None
    avatar_hash: str | None


@dataclass(frozen=True, slots=True)
class InstallationRecord:
    guild_id: int
    name: str
    icon_hash: str | None
    owner_id: int | None
    status: InstallationStatus
    application_id: int | None
    bot_user_id: int | None
    version: int


@dataclass(frozen=True, slots=True)
class AccessRecord:
    guild_id: int
    discord_user_id: int
    platform_role: PlatformRole
    status: AccessStatus
    scope_kind: ScopeKind
    scope_id: str
    policy_version: int


@dataclass(frozen=True, slots=True)
class RoleBindingRecord:
    guild_id: int
    discord_role_id: int
    dashboard_role: PlatformRole
    scope_kind: ScopeKind
    scope_id: str


class AuthRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def save_identity_and_grant(
        self,
        *,
        user: DiscordUser,
        tokens: OAuthTokenSet,
        encrypted: EncryptedTokenSet,
        expected_row_version: int | None = None,
    ) -> None:
        async with tenant_transaction(self._factory, UserContext(user.discord_user_id)) as session:
            await session.execute(
                text(
                    "INSERT INTO users (discord_user_id, username, global_name, avatar_hash) "
                    "VALUES (:user_id, :username, :global_name, :avatar_hash) "
                    "ON CONFLICT (discord_user_id) DO UPDATE SET "
                    "username=EXCLUDED.username, global_name=EXCLUDED.global_name, "
                    "avatar_hash=EXCLUDED.avatar_hash, updated_at=now()"
                ),
                {
                    "user_id": user.discord_user_id,
                    "username": user.username,
                    "global_name": user.global_name,
                    "avatar_hash": user.avatar_hash,
                },
            )
            parameters = {
                "user_id": user.discord_user_id,
                "scopes": json.dumps(sorted(tokens.scopes)),
                "access_ciphertext": encrypted.access_token_ciphertext,
                "access_nonce": encrypted.access_token_nonce,
                "expires_at": tokens.expires_at,
                "refresh_ciphertext": encrypted.refresh_token_ciphertext,
                "refresh_nonce": encrypted.refresh_token_nonce,
                "key_version": encrypted.key_version,
            }
            if expected_row_version is None:
                await session.execute(
                    text(
                        "INSERT INTO discord_oauth_grants "
                        "(discord_user_id, scopes_json, access_token_ciphertext, "
                        "access_token_nonce, "
                        "access_token_expires_at, refresh_token_ciphertext, refresh_token_nonce, "
                        "key_version, last_refreshed_at, revoked_at) "
                        "VALUES (:user_id, CAST(:scopes AS jsonb), :access_ciphertext, "
                        ":access_nonce, :expires_at, :refresh_ciphertext, :refresh_nonce, "
                        ":key_version, now(), NULL) "
                        "ON CONFLICT (discord_user_id) DO UPDATE SET "
                        "scopes_json=EXCLUDED.scopes_json, "
                        "access_token_ciphertext=EXCLUDED.access_token_ciphertext, "
                        "access_token_nonce=EXCLUDED.access_token_nonce, "
                        "access_token_expires_at=EXCLUDED.access_token_expires_at, "
                        "refresh_token_ciphertext=EXCLUDED.refresh_token_ciphertext, "
                        "refresh_token_nonce=EXCLUDED.refresh_token_nonce, "
                        "key_version=EXCLUDED.key_version, last_refreshed_at=now(), "
                        "revoked_at=NULL, "
                        "row_version=discord_oauth_grants.row_version+1, updated_at=now()"
                    ),
                    parameters,
                )
            else:
                result = await session.execute(
                    text(
                        "UPDATE discord_oauth_grants SET scopes_json=CAST(:scopes AS jsonb), "
                        "access_token_ciphertext=:access_ciphertext, "
                        "access_token_nonce=:access_nonce, "
                        "access_token_expires_at=:expires_at, "
                        "refresh_token_ciphertext=:refresh_ciphertext, "
                        "refresh_token_nonce=:refresh_nonce, "
                        "key_version=:key_version, last_refreshed_at=now(), "
                        "row_version=row_version+1, updated_at=now() "
                        "WHERE discord_user_id=:user_id AND row_version=:expected "
                        "AND revoked_at IS NULL RETURNING row_version"
                    ),
                    {**parameters, "expected": expected_row_version},
                )
                if result.scalar_one_or_none() is None:
                    raise ConcurrentGrantRefreshError("OAuth grant changed during refresh")

    async def get_grant(self, discord_user_id: int) -> OAuthGrantRecord | None:
        async with tenant_transaction(self._factory, UserContext(discord_user_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT discord_user_id, scopes_json, access_token_ciphertext, "
                            "access_token_nonce, access_token_expires_at, "
                            "refresh_token_ciphertext, "
                            "refresh_token_nonce, key_version, row_version, revoked_at "
                            "FROM discord_oauth_grants WHERE discord_user_id=:user_id"
                        ),
                        {"user_id": discord_user_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None or any(
            row[name] is None
            for name in (
                "access_token_ciphertext",
                "access_token_nonce",
                "access_token_expires_at",
                "refresh_token_ciphertext",
                "refresh_token_nonce",
            )
        ):
            return None
        return OAuthGrantRecord(
            discord_user_id=int(row["discord_user_id"]),
            scopes=frozenset(row["scopes_json"]),
            access_token_ciphertext=bytes(row["access_token_ciphertext"]),
            access_token_nonce=bytes(row["access_token_nonce"]),
            access_token_expires_at=row["access_token_expires_at"],
            refresh_token_ciphertext=bytes(row["refresh_token_ciphertext"]),
            refresh_token_nonce=bytes(row["refresh_token_nonce"]),
            key_version=int(row["key_version"]),
            row_version=int(row["row_version"]),
            revoked_at=row["revoked_at"],
        )

    async def revoke_grant(self, discord_user_id: int) -> None:
        async with tenant_transaction(self._factory, UserContext(discord_user_id)) as session:
            await session.execute(
                text(
                    "UPDATE discord_oauth_grants SET access_token_ciphertext=NULL, "
                    "access_token_nonce=NULL, refresh_token_ciphertext=NULL, "
                    "refresh_token_nonce=NULL, "
                    "revoked_at=now(), row_version=row_version+1, updated_at=now() "
                    "WHERE discord_user_id=:user_id"
                ),
                {"user_id": discord_user_id},
            )

    async def get_user(self, discord_user_id: int) -> UserRecord | None:
        async with tenant_transaction(self._factory, UserContext(discord_user_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT discord_user_id, username, global_name, avatar_hash FROM users "
                            "WHERE discord_user_id=:user_id"
                        ),
                        {"user_id": discord_user_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return UserRecord(
            discord_user_id=int(row["discord_user_id"]),
            username=str(row["username"]),
            global_name=row["global_name"],
            avatar_hash=row["avatar_hash"],
        )

    async def get_preferences(self, discord_user_id: int) -> tuple[str | None, str | None]:
        async with tenant_transaction(self._factory, UserContext(discord_user_id)) as session:
            row = (
                await session.execute(
                    text(
                        "SELECT ui_locale_override_code, timezone FROM user_ui_preferences "
                        "WHERE discord_user_id=:user_id"
                    ),
                    {"user_id": discord_user_id},
                )
            ).one_or_none()
        return (None, None) if row is None else (row[0], row[1])

    async def save_preferences(
        self, discord_user_id: int, *, locale: str | None, timezone: str | None
    ) -> None:
        async with tenant_transaction(self._factory, UserContext(discord_user_id)) as session:
            await session.execute(
                text(
                    "INSERT INTO user_ui_preferences "
                    "(discord_user_id, ui_locale_override_code, timezone) "
                    "VALUES (:user_id, :locale, :timezone) "
                    "ON CONFLICT (discord_user_id) DO UPDATE SET "
                    "ui_locale_override_code=EXCLUDED.ui_locale_override_code, "
                    "timezone=EXCLUDED.timezone, updated_at=now()"
                ),
                {"user_id": discord_user_id, "locale": locale, "timezone": timezone},
            )

    async def record_installation(
        self,
        *,
        guild_id: int,
        name: str,
        icon_hash: str | None,
        owner_id: int | None,
        application_id: int,
        bot_user_id: int,
    ) -> None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await session.execute(
                text(
                    "INSERT INTO guild_installations "
                    "(guild_id, name, icon_hash, owner_id, installation_status, application_id, "
                    "bot_user_id, last_gateway_seen_at) "
                    "VALUES (:guild_id, :name, :icon_hash, :owner_id, 'PENDING_SETUP', "
                    ":application_id, :bot_user_id, now()) "
                    "ON CONFLICT (guild_id) DO UPDATE SET name=EXCLUDED.name, "
                    "icon_hash=EXCLUDED.icon_hash, owner_id=EXCLUDED.owner_id, "
                    "installation_status=CASE "
                    "WHEN guild_installations.installation_status IN "
                    "('DISCOVERED', 'INSTALLED', 'UNINSTALLED') THEN 'PENDING_SETUP' "
                    "ELSE guild_installations.installation_status END, "
                    "application_id=COALESCE(guild_installations.application_id, "
                    "EXCLUDED.application_id), "
                    "bot_user_id=COALESCE(guild_installations.bot_user_id, EXCLUDED.bot_user_id), "
                    "installed_at=CASE WHEN guild_installations.installation_status='UNINSTALLED' "
                    "THEN now() ELSE guild_installations.installed_at END, "
                    "activated_at=CASE WHEN guild_installations.installation_status='UNINSTALLED' "
                    "THEN NULL ELSE guild_installations.activated_at END, "
                    "uninstalled_at=CASE WHEN "
                    "guild_installations.installation_status='UNINSTALLED' "
                    "THEN NULL ELSE guild_installations.uninstalled_at END, "
                    "last_gateway_seen_at=now(), version=guild_installations.version+1 "
                    "WHERE (guild_installations.application_id IS NULL OR "
                    "guild_installations.application_id=EXCLUDED.application_id) "
                    "AND (guild_installations.bot_user_id IS NULL OR "
                    "guild_installations.bot_user_id=EXCLUDED.bot_user_id) "
                    "RETURNING installation_status"
                ),
                {
                    "guild_id": guild_id,
                    "name": name,
                    "icon_hash": icon_hash,
                    "owner_id": owner_id,
                    "application_id": application_id,
                    "bot_user_id": bot_user_id,
                },
            )
            if result.scalar_one_or_none() is None:
                raise InstallationIdentityMismatch(
                    "installation application or bot identity does not match"
                )

    async def get_installation(self, guild_id: int, user_id: int) -> InstallationRecord | None:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id=guild_id, user_id=user_id)
        ) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT guild_id, name, icon_hash, owner_id, installation_status, "
                            "application_id, bot_user_id, version FROM guild_installations "
                            "WHERE guild_id=:guild_id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return InstallationRecord(
            guild_id=int(row["guild_id"]),
            name=str(row["name"]),
            icon_hash=row["icon_hash"],
            owner_id=row["owner_id"],
            status=InstallationStatus(row["installation_status"]),
            application_id=row["application_id"],
            bot_user_id=row["bot_user_id"],
            version=int(row["version"]),
        )

    async def activate_and_create_owner(self, guild_id: int, actor_user_id: int) -> None:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id=guild_id, user_id=actor_user_id)
        ) as session:
            updated = await session.execute(
                text(
                    "UPDATE guild_installations SET installation_status='ACTIVE', "
                    "activated_at=COALESCE(activated_at, now()), version=version+1 "
                    "WHERE guild_id=:guild_id AND installation_status='PENDING_SETUP' "
                    "RETURNING version"
                ),
                {"guild_id": guild_id},
            )
            if updated.scalar_one_or_none() is None:
                raise ValueError("installation is not pending setup")
            await session.execute(
                text(
                    "INSERT INTO guild_user_access "
                    "(guild_id, discord_user_id, platform_role, status, scope_kind, scope_id, "
                    "created_by) "
                    "VALUES (:guild_id, :user_id, 'OWNER', 'ACTIVE', 'GUILD', '*', :user_id) "
                    "ON CONFLICT (guild_id, discord_user_id, scope_kind, scope_id) DO UPDATE SET "
                    "platform_role='OWNER', status='ACTIVE', "
                    "policy_version=guild_user_access.policy_version+1, updated_at=now()"
                ),
                {"guild_id": guild_id, "user_id": actor_user_id},
            )

    async def mark_uninstalled(self, guild_id: int, actor_user_id: int | None = None) -> None:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id=guild_id, user_id=actor_user_id)
        ) as session:
            await session.execute(
                text(
                    "UPDATE guild_installations SET installation_status='UNINSTALLED', "
                    "uninstalled_at=now(), version=version+1 WHERE guild_id=:guild_id"
                ),
                {"guild_id": guild_id},
            )

    async def get_accesses(self, guild_id: int, user_id: int) -> tuple[AccessRecord, ...]:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id=guild_id, user_id=user_id)
        ) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT guild_id, discord_user_id, platform_role, status, scope_kind, "
                            "scope_id, policy_version FROM guild_user_access "
                            "WHERE guild_id=:guild_id AND discord_user_id=:user_id "
                            "ORDER BY scope_kind, scope_id"
                        ),
                        {"guild_id": guild_id, "user_id": user_id},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            AccessRecord(
                guild_id=int(row["guild_id"]),
                discord_user_id=int(row["discord_user_id"]),
                platform_role=PlatformRole(row["platform_role"]),
                status=AccessStatus(row["status"]),
                scope_kind=ScopeKind(row["scope_kind"]),
                scope_id=str(row["scope_id"]),
                policy_version=int(row["policy_version"]),
            )
            for row in rows
        )

    async def get_access(
        self, guild_id: int, user_id: int, scope: AuthorizationScope
    ) -> AccessRecord | None:
        accesses = await self.get_accesses(guild_id, user_id)
        return next(
            (
                access
                for access in accesses
                if access.scope_kind is scope.kind and access.scope_id == scope.scope_id
            ),
            None,
        )

    async def save_user_access(
        self,
        *,
        guild_id: int,
        target_user_id: int,
        role: PlatformRole,
        actor_user_id: int,
        scope: AuthorizationScope,
        status: AccessStatus = AccessStatus.ACTIVE,
    ) -> None:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id=guild_id, user_id=actor_user_id)
        ) as session:
            await session.execute(
                text(
                    "INSERT INTO guild_user_access "
                    "(guild_id, discord_user_id, platform_role, status, scope_kind, scope_id, "
                    "created_by) "
                    "VALUES (:guild_id, :target, :role, :status, :scope_kind, :scope_id, :actor) "
                    "ON CONFLICT (guild_id, discord_user_id, scope_kind, scope_id) DO UPDATE SET "
                    "platform_role=EXCLUDED.platform_role, status=EXCLUDED.status, "
                    "policy_version=guild_user_access.policy_version+1, updated_at=now()"
                ),
                {
                    "guild_id": guild_id,
                    "target": target_user_id,
                    "role": role.value,
                    "status": status.value,
                    "scope_kind": scope.kind.value,
                    "scope_id": scope.scope_id,
                    "actor": actor_user_id,
                },
            )

    async def role_bindings(self, guild_id: int, user_id: int) -> tuple[RoleBindingRecord, ...]:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id=guild_id, user_id=user_id)
        ) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT guild_id, discord_role_id, dashboard_role, "
                            "scope_kind, scope_id "
                            "FROM guild_role_bindings WHERE guild_id=:guild_id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            RoleBindingRecord(
                guild_id=int(row["guild_id"]),
                discord_role_id=int(row["discord_role_id"]),
                dashboard_role=PlatformRole(row["dashboard_role"]),
                scope_kind=ScopeKind(row["scope_kind"]),
                scope_id=str(row["scope_id"]),
            )
            for row in rows
        )

    async def save_role_binding(
        self,
        *,
        guild_id: int,
        discord_role_id: int,
        dashboard_role: PlatformRole,
        actor_user_id: int,
        scope: AuthorizationScope,
    ) -> None:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id=guild_id, user_id=actor_user_id)
        ) as session:
            await session.execute(
                text(
                    "INSERT INTO guild_role_bindings "
                    "(guild_id, discord_role_id, dashboard_role, scope_kind, scope_id, created_by) "
                    "VALUES (:guild_id, :role_id, :dashboard_role, :scope_kind, :scope_id, :actor) "
                    "ON CONFLICT (guild_id, discord_role_id, scope_kind, scope_id) DO UPDATE SET "
                    "dashboard_role=EXCLUDED.dashboard_role"
                ),
                {
                    "guild_id": guild_id,
                    "role_id": discord_role_id,
                    "dashboard_role": dashboard_role.value,
                    "scope_kind": scope.kind.value,
                    "scope_id": scope.scope_id,
                    "actor": actor_user_id,
                },
            )

    async def delete_role_binding(
        self,
        *,
        guild_id: int,
        discord_role_id: int,
        actor_user_id: int,
        scope: AuthorizationScope,
    ) -> None:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id=guild_id, user_id=actor_user_id)
        ) as session:
            await session.execute(
                text(
                    "DELETE FROM guild_role_bindings WHERE guild_id=:guild_id "
                    "AND discord_role_id=:role_id AND scope_kind=:scope_kind "
                    "AND scope_id=:scope_id"
                ),
                {
                    "guild_id": guild_id,
                    "role_id": discord_role_id,
                    "scope_kind": scope.kind.value,
                    "scope_id": scope.scope_id,
                },
            )


def utc_now() -> datetime:
    return datetime.now(UTC)
