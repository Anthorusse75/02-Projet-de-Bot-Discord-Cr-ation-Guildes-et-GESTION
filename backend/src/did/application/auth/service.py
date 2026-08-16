import asyncio
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn

from redis.asyncio import Redis

from did.domain.auth import (
    AccessStatus,
    ActorMembership,
    AuthorizationScope,
    Capability,
    GuildDiscovery,
    InstallationStatus,
    PlatformRole,
    capabilities_for_role,
)
from did.infrastructure.auth_repository import AuthRepository, InstallationRecord
from did.infrastructure.logging import EventId, emit_event
from did.infrastructure.redis import user_control_key
from did.oauth.crypto import TokenCipher
from did.oauth.discord import DiscordMemberClient, DiscordOAuthClient
from did.oauth.models import (
    OAUTH_SCOPES,
    DiscordGuild,
    DiscordUser,
    OAuthGrantRecord,
    OAuthTokenSet,
)
from did.oauth.stores import (
    OAuthState,
    RedisActorMembershipStore,
    RedisGuildDiscoveryStore,
    RedisOAuthStateStore,
    RedisSessionStore,
    SessionData,
)

logger = logging.getLogger(__name__)


class AuthenticationError(RuntimeError):
    pass


class AuthorizationDenied(RuntimeError):
    def __init__(self, code: str = "TENANT_ACCESS_DENIED") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class LoginResult:
    session: SessionData
    return_to: str


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    guild_id: int
    user_id: int
    role: PlatformRole
    capabilities: frozenset[Capability]
    scope: AuthorizationScope
    installation: InstallationRecord


class AuthService:
    def __init__(
        self,
        *,
        redis: Redis,
        oauth_client: DiscordOAuthClient,
        repository: AuthRepository,
        cipher: TokenCipher,
        state_store: RedisOAuthStateStore,
        session_store: RedisSessionStore,
        guild_store: RedisGuildDiscoveryStore,
    ) -> None:
        self._redis = redis
        self.oauth_client = oauth_client
        self.repository = repository
        self.cipher = cipher
        self.state_store = state_store
        self.session_store = session_store
        self.guild_store = guild_store

    async def start(self, *, return_to: str) -> tuple[OAuthState, str]:
        state = await self.state_store.create(return_to=return_to)
        return state, self.oauth_client.authorization_url(state=state.state)

    async def callback(
        self,
        *,
        code: str,
        state: str,
        browser_binding: str | None,
        previous_session_id: str | None,
    ) -> LoginResult:
        state_record = await self.state_store.consume(state, browser_binding)
        try:
            tokens = await self.oauth_client.exchange_code(code)
            self._validate_scopes(tokens)
            user = await self.oauth_client.current_user(tokens.access_token)
            guilds = await self.oauth_client.current_user_guilds(tokens.access_token)
            encrypted = self.cipher.encrypt(discord_user_id=user.discord_user_id, tokens=tokens)
            await self.repository.save_identity_and_grant(
                user=user, tokens=tokens, encrypted=encrypted
            )
            await self.guild_store.put(user.discord_user_id, guilds)
            session = await self.session_store.create(
                discord_user_id=user.discord_user_id,
                previous_session_id=previous_session_id,
            )
        except Exception:
            emit_event(logger, logging.WARNING, EventId.AUTH_LOGIN_DENIED)
            raise
        emit_event(
            logger,
            logging.INFO,
            EventId.AUTH_LOGIN_SUCCEEDED,
            fields={"user_id": user.discord_user_id},
        )
        return LoginResult(session=session, return_to=state_record.return_to)

    async def logout(self, session_id: str) -> None:
        await self.session_store.revoke(session_id)
        emit_event(logger, logging.INFO, EventId.AUTH_LOGOUT)

    async def revoke_discord(self, session: SessionData) -> None:
        grant = await self.repository.get_grant(session.discord_user_id)
        if grant is not None and grant.revoked_at is None:
            refresh_token = self.cipher.decrypt_refresh(grant)
            await self.oauth_client.revoke(refresh_token)
        await self.repository.revoke_grant(session.discord_user_id)
        await self.session_store.revoke_user(session.discord_user_id)
        emit_event(
            logger,
            logging.INFO,
            EventId.AUTH_GRANT_REVOKED,
            fields={"user_id": session.discord_user_id},
        )

    async def access_token(self, discord_user_id: int) -> str:
        grant = await self.repository.get_grant(discord_user_id)
        if grant is None or grant.revoked_at is not None:
            raise AuthenticationError("OAuth grant is unavailable")
        now = datetime.now(UTC)
        if grant.access_token_expires_at > now + timedelta(seconds=30):
            return self.cipher.decrypt_access(grant)
        return await self._refresh(discord_user_id, grant)

    async def refresh_guilds(self, discord_user_id: int) -> tuple[DiscordGuild, ...]:
        access_token = await self.access_token(discord_user_id)
        guilds = await self.oauth_client.current_user_guilds(access_token)
        await self.guild_store.put(discord_user_id, guilds)
        return guilds

    async def _refresh(self, discord_user_id: int, initial: OAuthGrantRecord) -> str:
        lock_key = user_control_key("user", str(discord_user_id), "oauth-refresh-lock")
        lock_value = secrets_token()
        acquired = await self._redis.set(lock_key, lock_value, nx=True, ex=10)
        if not acquired:
            for _ in range(10):
                await asyncio.sleep(0.05)
                reloaded = await self.repository.get_grant(discord_user_id)
                if reloaded and reloaded.row_version != initial.row_version:
                    return self.cipher.decrypt_access(reloaded)
            raise AuthenticationError("OAuth refresh is already in progress")
        try:
            current = await self.repository.get_grant(discord_user_id)
            if current is None or current.revoked_at is not None:
                raise AuthenticationError("OAuth grant is unavailable")
            if current.access_token_expires_at > datetime.now(UTC) + timedelta(seconds=30):
                return self.cipher.decrypt_access(current)
            refresh_token = self.cipher.decrypt_refresh(current)
            tokens = await self.oauth_client.refresh(refresh_token)
            self._validate_scopes(tokens)
            user = await self.repository.get_user(discord_user_id)
            if user is None:
                raise AuthenticationError("OAuth identity is unavailable")
            encrypted = self.cipher.encrypt(discord_user_id=discord_user_id, tokens=tokens)
            await self.repository.save_identity_and_grant(
                user=DiscordUser(
                    discord_user_id=user.discord_user_id,
                    username=user.username,
                    global_name=user.global_name,
                    avatar_hash=user.avatar_hash,
                ),
                tokens=tokens,
                encrypted=encrypted,
                expected_row_version=current.row_version,
            )
            return tokens.access_token
        finally:
            script = (
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end"
            )
            await self._redis.eval(script, 1, lock_key, lock_value)

    @staticmethod
    def _validate_scopes(tokens: OAuthTokenSet) -> None:
        if tokens.scopes != OAUTH_SCOPES:
            raise AuthenticationError("Discord returned unexpected OAuth scopes")


class AuthorizationService:
    def __init__(
        self,
        *,
        auth: AuthService,
        repository: AuthRepository,
        membership_store: RedisActorMembershipStore,
        member_client: DiscordMemberClient | None,
        freshness_seconds: int,
    ) -> None:
        self.auth = auth
        self.repository = repository
        self.membership_store = membership_store
        self.member_client = member_client
        self.freshness_seconds = freshness_seconds

    async def guilds_for_user(
        self, discord_user_id: int, *, force_refresh: bool = False
    ) -> tuple[DiscordGuild, ...]:
        if not force_refresh:
            cached = await self.auth.guild_store.get(discord_user_id)
            if cached is not None:
                return cached
        return await self.auth.refresh_guilds(discord_user_id)

    async def discovery(
        self, discord_user_id: int, guild_id: int, *, force_refresh: bool = False
    ) -> GuildDiscovery:
        guilds = await self.guilds_for_user(discord_user_id, force_refresh=force_refresh)
        guild = next((item for item in guilds if item.guild_id == guild_id), None)
        if guild is None:
            self._deny(guild_id, discord_user_id, "GUILD_MEMBERSHIP_REQUIRED")
        assert guild is not None
        return GuildDiscovery(
            guild_id=guild.guild_id,
            name=guild.name,
            icon_hash=guild.icon_hash,
            owner=guild.owner,
            permissions=guild.permissions,
        )

    async def authorize(
        self,
        *,
        discord_user_id: int,
        guild_id: int,
        capability: Capability,
        scope: AuthorizationScope,
        sensitive: bool = False,
        require_active_installation: bool = True,
    ) -> AuthorizationDecision:
        await self.discovery(discord_user_id, guild_id)
        accesses = await self.repository.get_accesses(guild_id, discord_user_id)
        direct_roles = [
            access.platform_role
            for access in accesses
            if access.status is AccessStatus.ACTIVE
            and AuthorizationScope(access.scope_kind, access.scope_id).covers(scope)
        ]
        role = _strongest(*direct_roles)
        bindings = await self.repository.role_bindings(guild_id, discord_user_id)
        applicable_bindings = [
            binding
            for binding in bindings
            if AuthorizationScope(binding.scope_kind, binding.scope_id).covers(scope)
        ]
        direct_grant_satisfies = role is not None and capability in capabilities_for_role(role)
        if sensitive or (applicable_bindings and not direct_grant_satisfies):
            membership = await self._membership(
                guild_id=guild_id,
                user_id=discord_user_id,
                force=False,
            )
            matching_roles = [
                binding.dashboard_role
                for binding in applicable_bindings
                if binding.discord_role_id in membership.role_ids
            ]
            role = _strongest(role, *matching_roles)
        if role is None or capability not in capabilities_for_role(role):
            self._deny(guild_id, discord_user_id, "CAPABILITY_REQUIRED")
        installation = await self.repository.get_installation(guild_id, discord_user_id)
        if installation is None:
            self._deny(guild_id, discord_user_id, "INSTALLATION_NOT_FOUND")
        assert installation is not None
        if require_active_installation and installation.status is not InstallationStatus.ACTIVE:
            self._deny(guild_id, discord_user_id, "INSTALLATION_NOT_ACTIVE")
        return AuthorizationDecision(
            guild_id=guild_id,
            user_id=discord_user_id,
            role=role,
            capabilities=capabilities_for_role(role),
            scope=scope,
            installation=installation,
        )

    async def _membership(self, *, guild_id: int, user_id: int, force: bool) -> ActorMembership:
        cached = await self.membership_store.get(guild_id, user_id)
        if (
            cached is not None
            and not force
            and cached.is_fresh(max_age_seconds=self.freshness_seconds)
        ):
            return cached
        if self.member_client is None:
            self._deny(guild_id, user_id, "AUTHORIZATION_FRESHNESS_UNAVAILABLE")
        assert self.member_client is not None
        try:
            roles = await self.member_client.get_member_roles(guild_id, user_id)
        except Exception as exc:
            self._deny(guild_id, user_id, "GUILD_MEMBERSHIP_REQUIRED")
            raise AssertionError("unreachable") from exc
        membership = ActorMembership(
            guild_id=guild_id,
            discord_user_id=user_id,
            role_ids=roles,
            observed_at=datetime.now(UTC),
            source="TARGETED_REST",
        )
        await self.membership_store.put(membership)
        return membership

    @staticmethod
    def _deny(guild_id: int, user_id: int, code: str) -> NoReturn:
        emit_event(
            logger,
            logging.WARNING,
            EventId.AUTHORIZATION_DENIED,
            fields={"guild_id": guild_id, "user_id": user_id, "reason": code},
        )
        raise AuthorizationDenied(code)


def _strongest(*roles: PlatformRole | None) -> PlatformRole | None:
    order = {PlatformRole.READ_ONLY: 1, PlatformRole.TENANT_ADMIN: 2, PlatformRole.OWNER: 3}
    available = [role for role in roles if role is not None]
    return max(available, key=order.__getitem__) if available else None


def secrets_token() -> str:
    return secrets.token_urlsafe(24)
