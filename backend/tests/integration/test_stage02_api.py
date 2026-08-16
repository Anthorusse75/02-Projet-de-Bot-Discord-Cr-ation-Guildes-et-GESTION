import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text

from did.api.main import create_app
from did.application.auth.service import AuthorizationDenied
from did.domain.auth import (
    ActorMembership,
    AuthorizationScope,
    Capability,
    PlatformRole,
    ScopeKind,
)
from did.infrastructure.auth_repository import InstallationIdentityMismatch
from did.infrastructure.database import create_database_engine
from did.oauth.discord import DiscordOAuthError
from did.oauth.models import DiscordGuild, DiscordUser, OAuthTokenSet
from did.settings import AppEnvironment, Settings

pytestmark = [pytest.mark.integration, pytest.mark.api, pytest.mark.security]

ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 515151515151515151
GUILD_B = 616161616161616161
GUILD_HIDDEN = 717171717171717171
GUILD_ADMIN = 919191919191919191
USER = 818181818181818181
TARGET_USER = 828282828282828282
ADMIN_USER = 838383838383838383
ROLE_USER = 848484848484848484


class FakeOAuthClient:
    def __init__(self) -> None:
        self.refresh_calls = 0
        self.revoked: list[str] = []
        self.expired_initial = False
        self.unexpected_scopes = False
        self.admin_permissions = 1 << 3
        self.guild_calls = 0

    def authorization_url(self, *, state: str) -> str:
        return f"https://discord.com/oauth2/authorize?state={state}"

    async def exchange_code(self, code: str) -> OAuthTokenSet:
        assert code == "oauth-code"
        expiry = datetime.now(UTC) - timedelta(seconds=1)
        if not self.expired_initial:
            expiry = datetime.now(UTC) + timedelta(hours=1)
        scopes = (
            frozenset({"identify"}) if self.unexpected_scopes else frozenset({"identify", "guilds"})
        )
        return OAuthTokenSet(
            access_token="contract-access",
            refresh_token="contract-refresh",
            expires_at=expiry,
            scopes=scopes,
        )

    async def refresh(self, refresh_token: str) -> OAuthTokenSet:
        assert refresh_token == "contract-refresh"
        self.refresh_calls += 1
        return OAuthTokenSet(
            access_token="refreshed-access",
            refresh_token="rotated-refresh",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=frozenset({"identify", "guilds"}),
        )

    async def revoke(self, token: str) -> None:
        self.revoked.append(token)

    async def current_user(self, access_token: str) -> DiscordUser:
        assert access_token == "contract-access"
        return DiscordUser(USER, "stage02-user", "Stage 02", None)

    async def current_user_guilds(self, access_token: str) -> tuple[DiscordGuild, ...]:
        assert access_token in {"contract-access", "refreshed-access"}
        self.guild_calls += 1
        return (
            DiscordGuild(GUILD_A, "Guild A", None, True, 0),
            DiscordGuild(GUILD_B, "Guild B", None, False, 0),
            DiscordGuild(GUILD_ADMIN, "Guild Admin", None, False, self.admin_permissions),
        )


class FakeMemberClient:
    def __init__(self) -> None:
        self.roles: dict[tuple[int, int], tuple[int, ...]] = {
            (GUILD_A, USER): (9001,),
            (GUILD_A, TARGET_USER): (9001,),
        }
        self.calls: list[tuple[int, int]] = []
        self.missing: set[tuple[int, int]] = set()

    async def get_member_roles(self, guild_id: int, user_id: int) -> tuple[int, ...]:
        self.calls.append((guild_id, user_id))
        if (guild_id, user_id) in self.missing:
            raise DiscordOAuthError("targeted_member_lookup", 404)
        return self.roles.get((guild_id, user_id), ())


def stage02_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        database_url=SecretStr(
            os.environ.get(
                "DID_DATABASE_URL",
                "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test",
            )
        ),
        database_admin_url=SecretStr(ADMIN_URL),
        redis_url=SecretStr(os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0")),
        discord_client_id="123",
        discord_client_secret=SecretStr("test-only-client-value"),
        discord_oauth_redirect_uri="http://test/auth/discord/callback",
        session_secret=SecretStr("stage02-test-session-secret-material"),
        oauth_token_encryption_key=SecretStr("a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s"),
        oauth_state_ttl_seconds=60,
        guild_discovery_ttl_seconds=60,
    )


async def reset_stage02() -> None:
    engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE guild_role_bindings, guild_user_access, guild_installations, "
                    "user_ui_preferences, discord_oauth_grants, users CASCADE"
                )
            )
    finally:
        await engine.dispose()


async def seed_did_identities(*user_ids: int) -> None:
    engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with engine.begin() as connection:
            for user_id in user_ids:
                await connection.execute(
                    text(
                        "INSERT INTO users (discord_user_id, username) "
                        "VALUES (:user_id, :username) ON CONFLICT DO NOTHING"
                    ),
                    {"user_id": user_id, "username": f"user-{user_id}"},
                )
    finally:
        await engine.dispose()


async def force_installation_status(guild_id: int, value: str) -> None:
    engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE guild_installations SET installation_status=:status "
                    "WHERE guild_id=:guild_id"
                ),
                {"status": value, "guild_id": guild_id},
            )
    finally:
        await engine.dispose()


async def login(client: AsyncClient) -> tuple[str, str]:
    start = await client.get("/auth/discord/login", params={"return_to": "/dashboard"})
    assert start.status_code == 302
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    callback = await client.get(
        "/auth/discord/callback",
        params={"code": "oauth-code", "state": state},
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/dashboard"
    assert "HttpOnly" in callback.headers["set-cookie"]
    assert "SameSite=lax" in callback.headers["set-cookie"]
    assert "did_oauth_binding=" in callback.headers["set-cookie"]
    assert "Max-Age=0" in callback.headers["set-cookie"]
    me = await client.get("/api/v1/me")
    assert me.status_code == 200
    return state, me.json()["csrf_token"]


async def test_login_state_replay_fixation_csrf_bootstrap_idor_logout_and_revoke() -> None:
    await reset_stage02()
    oauth = FakeOAuthClient()
    member = FakeMemberClient()
    application = create_app(stage02_settings(), oauth_client=oauth, member_client=member)
    async with application.router.lifespan_context(application):
        container = application.state.services
        fixed = await container.sessions.create(discord_user_id=USER, previous_session_id=None)
        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=False
        ) as client:
            client.cookies.set("did_session", fixed.session_id)
            state, csrf = await login(client)
            assert await container.sessions.load(fixed.session_id) is None

            replay = await client.get(
                "/auth/discord/callback",
                params={"code": "oauth-code", "state": state},
            )
            assert replay.status_code == 400
            assert replay.json()["error"]["code"] == "OAUTH_STATE_INVALID"

            await container.installations.record_detected(
                guild_id=GUILD_A,
                name="Guild A",
                icon_hash=None,
                owner_id=USER,
                application_id=123,
                bot_user_id=999,
            )
            await container.installations.record_detected(
                guild_id=GUILD_B,
                name="Guild B",
                icon_hash=None,
                owner_id=999,
                application_id=123,
                bot_user_id=999,
            )
            await force_installation_status(GUILD_B, "ACTIVE")
            await container.installations.record_detected(
                guild_id=GUILD_HIDDEN,
                name="Hidden",
                icon_hash=None,
                owner_id=999,
                application_id=123,
                bot_user_id=999,
            )
            await container.installations.record_detected(
                guild_id=GUILD_ADMIN,
                name="Guild Admin",
                icon_hash=None,
                owner_id=999,
                application_id=123,
                bot_user_id=999,
            )

            original_get_installation = container.repository.get_installation
            with patch.object(
                container.repository,
                "get_installation",
                wraps=original_get_installation,
            ) as list_installation_lookup:
                guild_list = await client.get("/api/v1/guilds")
                assert all(
                    call.args[0] != GUILD_B for call in list_installation_lookup.call_args_list
                )
            assert guild_list.status_code == 200
            listed_ids = {item["guild_id"] for item in guild_list.json()["guilds"]}
            assert str(GUILD_A) in listed_ids
            assert str(GUILD_B) not in listed_ids

            with patch.object(
                container.repository,
                "get_installation",
                wraps=original_get_installation,
            ) as installation_lookup:
                denied_installation = await client.get(f"/api/v1/guilds/{GUILD_B}/installation")
                assert all(call.args[0] != GUILD_B for call in installation_lookup.call_args_list)
            assert denied_installation.status_code == 404

            no_csrf = await client.post(f"/api/v1/guilds/{GUILD_A}/bootstrap")
            assert no_csrf.status_code == 403
            assert no_csrf.json()["error"]["code"] == "CSRF_INVALID"

            bootstrap_a = await client.post(
                f"/api/v1/guilds/{GUILD_A}/bootstrap",
                headers={"X-CSRF-Token": csrf},
            )
            assert bootstrap_a.status_code == 200
            assert bootstrap_a.json()["status"] == "ACTIVE"
            bootstrap_a_again = await client.post(
                f"/api/v1/guilds/{GUILD_A}/bootstrap",
                headers={"X-CSRF-Token": csrf},
            )
            assert bootstrap_a_again.status_code == 200
            assert bootstrap_a_again.json()["status"] == "ACTIVE"

            oauth.admin_permissions = 0
            bootstrap_admin_stale = await client.post(
                f"/api/v1/guilds/{GUILD_ADMIN}/bootstrap",
                headers={"X-CSRF-Token": csrf},
            )
            assert bootstrap_admin_stale.status_code == 403
            assert bootstrap_admin_stale.json()["error"]["code"] == (
                "BOOTSTRAP_OWNER_OR_ADMINISTRATOR_REQUIRED"
            )
            oauth.admin_permissions = 1 << 3
            bootstrap_admin = await client.post(
                f"/api/v1/guilds/{GUILD_ADMIN}/bootstrap",
                headers={"X-CSRF-Token": csrf},
            )
            assert bootstrap_admin.status_code == 200

            bootstrap_b = await client.post(
                f"/api/v1/guilds/{GUILD_B}/bootstrap",
                headers={"X-CSRF-Token": csrf},
            )
            assert bootstrap_b.status_code == 403
            assert bootstrap_b.json()["error"]["code"] == (
                "BOOTSTRAP_OWNER_OR_ADMINISTRATOR_REQUIRED"
            )

            with patch.object(
                container.repository,
                "get_installation",
                wraps=original_get_installation,
            ) as installation_lookup:
                hidden = await client.get(f"/api/v1/guilds/{GUILD_HIDDEN}/installation")
                installation_lookup.assert_not_called()
            assert hidden.status_code == 403
            assert hidden.json()["error"]["code"] == "GUILD_MEMBERSHIP_REQUIRED"

            uninstall = await client.delete(
                f"/api/v1/guilds/{GUILD_A}/installation",
                headers={"X-CSRF-Token": csrf},
            )
            assert uninstall.status_code == 204
            inactive = await client.post(
                f"/api/v1/guilds/{GUILD_A}/select",
                headers={"X-CSRF-Token": csrf},
            )
            assert inactive.status_code == 403
            assert inactive.json()["error"]["code"] == "INSTALLATION_NOT_ACTIVE"

            await container.installations.record_detected(
                guild_id=GUILD_A,
                name="Guild A",
                icon_hash=None,
                owner_id=USER,
                application_id=123,
                bot_user_id=999,
            )
            rebootstrap = await client.post(
                f"/api/v1/guilds/{GUILD_A}/bootstrap",
                headers={"X-CSRF-Token": csrf},
            )
            assert rebootstrap.status_code == 200

            binding = await client.put(
                f"/api/v1/guilds/{GUILD_A}/rbac/roles",
                headers={"X-CSRF-Token": csrf},
                json={
                    "discord_role_id": "9001",
                    "platform_role": "READ_ONLY",
                    "scope_kind": "GUILD",
                    "scope_id": "*",
                },
            )
            assert binding.status_code == 200
            await container.auth.guild_store.put(
                TARGET_USER,
                (DiscordGuild(GUILD_A, "Guild A", None, False, 0),),
            )
            decision = await container.authorization.authorize(
                discord_user_id=TARGET_USER,
                guild_id=GUILD_A,
                capability=Capability.TENANT_READ,
                scope=AuthorizationScope.guild(),
                sensitive=True,
            )
            assert decision.role.value == "READ_ONLY"
            assert member.calls[-1] == (GUILD_A, TARGET_USER)

            member.roles[(GUILD_A, TARGET_USER)] = ()
            await container.authorization.membership_store.put(
                ActorMembership(
                    guild_id=GUILD_A,
                    discord_user_id=TARGET_USER,
                    role_ids=(9001,),
                    observed_at=datetime.now(UTC) - timedelta(seconds=121),
                    source="TARGETED_REST",
                )
            )
            with pytest.raises(AuthorizationDenied, match="CAPABILITY_REQUIRED"):
                await container.authorization.authorize(
                    discord_user_id=TARGET_USER,
                    guild_id=GUILD_A,
                    capability=Capability.TENANT_READ,
                    scope=AuthorizationScope.guild(),
                    sensitive=True,
                )

            await container.auth.guild_store.put(TARGET_USER, ())
            with pytest.raises(AuthorizationDenied, match="GUILD_MEMBERSHIP_REQUIRED"):
                await container.authorization.authorize(
                    discord_user_id=TARGET_USER,
                    guild_id=GUILD_A,
                    capability=Capability.TENANT_READ,
                    scope=AuthorizationScope.guild(),
                    sensitive=True,
                )

            selected = await client.post(
                f"/api/v1/guilds/{GUILD_A}/select",
                headers={"X-CSRF-Token": csrf},
            )
            assert selected.status_code == 200
            rotated_csrf = selected.json()["csrf_token"]
            assert rotated_csrf != csrf

            old_csrf_logout = await client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
            assert old_csrf_logout.status_code == 403
            logout = await client.post("/auth/logout", headers={"X-CSRF-Token": rotated_csrf})
            assert logout.status_code == 204
            assert (await client.get("/api/v1/me")).status_code == 401

            _, csrf = await login(client)
            revoke = await client.post(
                "/api/v1/me/oauth/discord/revoke",
                headers={"X-CSRF-Token": csrf},
            )
            assert revoke.status_code == 204
            assert oauth.revoked == ["contract-refresh"]
            assert (await client.get("/api/v1/me")).status_code == 401


async def test_oauth_state_is_bound_to_the_exact_browser_without_consuming_on_mismatch() -> None:
    await reset_stage02()
    application = create_app(
        stage02_settings(), oauth_client=FakeOAuthClient(), member_client=FakeMemberClient()
    )
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application, raise_app_exceptions=False)
        async with (
            AsyncClient(
                transport=transport, base_url="http://test", follow_redirects=False
            ) as browser_a,
            AsyncClient(
                transport=transport, base_url="http://test", follow_redirects=False
            ) as browser_b,
        ):
            start = await browser_a.get("/auth/discord/login")
            state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
            binding_a = browser_a.cookies.get("did_oauth_binding")
            assert binding_a

            missing = await browser_b.get(
                "/auth/discord/callback",
                params={"code": "oauth-code", "state": state},
            )
            assert missing.status_code == 400
            assert missing.json()["error"]["code"] == "OAUTH_STATE_INVALID"
            assert (await browser_b.get("/api/v1/me")).status_code == 401

            await browser_b.get("/auth/discord/login")
            binding_b = browser_b.cookies.get("did_oauth_binding")
            assert binding_b and binding_b != binding_a
            wrong_browser = await browser_b.get(
                "/auth/discord/callback",
                params={"code": "oauth-code", "state": state},
            )
            assert wrong_browser.status_code == 400
            assert wrong_browser.json()["error"]["code"] == "OAUTH_STATE_INVALID"

            success = await browser_a.get(
                "/auth/discord/callback",
                params={"code": "oauth-code", "state": state},
            )
            assert success.status_code == 303
            assert (await browser_a.get("/api/v1/me")).status_code == 200
            assert browser_a.cookies.get("did_oauth_binding") is None

            replay = await browser_a.get(
                "/auth/discord/callback",
                params={"code": "oauth-code", "state": state},
            )
            assert replay.status_code == 400
            assert replay.json()["error"]["code"] == "OAUTH_STATE_INVALID"

            second = await browser_a.get("/auth/discord/login")
            second_state = parse_qs(urlparse(second.headers["location"]).query)["state"][0]
            second_binding = browser_a.cookies.get("did_oauth_binding")
            wrong_state = await browser_a.get(
                "/auth/discord/callback",
                params={"code": "oauth-code", "state": "wrong-state"},
            )
            assert wrong_state.status_code == 400
            browser_a.cookies.set("did_oauth_binding", second_binding)
            recovered = await browser_a.get(
                "/auth/discord/callback",
                params={"code": "oauth-code", "state": second_state},
            )
            assert recovered.status_code == 303


async def test_scoped_rbac_owner_protection_revoke_and_sensitive_freshness() -> None:
    await reset_stage02()
    oauth = FakeOAuthClient()
    member = FakeMemberClient()
    member.roles[(GUILD_A, ROLE_USER)] = (9002,)
    application = create_app(stage02_settings(), oauth_client=oauth, member_client=member)
    async with application.router.lifespan_context(application):
        container = application.state.services
        async with AsyncClient(
            transport=ASGITransport(app=application, raise_app_exceptions=False),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            _, csrf = await login(client)
            await seed_did_identities(TARGET_USER, ADMIN_USER, ROLE_USER)
            await container.installations.record_detected(
                guild_id=GUILD_A,
                name="Guild A",
                icon_hash=None,
                owner_id=USER,
                application_id=123,
                bot_user_id=999,
            )
            assert (
                await client.post(
                    f"/api/v1/guilds/{GUILD_A}/bootstrap",
                    headers={"X-CSRF-Token": csrf},
                )
            ).status_code == 200
            for principal in (TARGET_USER, ADMIN_USER, ROLE_USER):
                await container.auth.guild_store.put(
                    principal,
                    (DiscordGuild(GUILD_A, "Guild A", None, False, 0),),
                )

            alpha_admin = await client.put(
                f"/api/v1/guilds/{GUILD_A}/rbac/users",
                headers={"X-CSRF-Token": csrf},
                json={
                    "discord_user_id": str(TARGET_USER),
                    "platform_role": "TENANT_ADMIN",
                    "scope_kind": "LOGICAL_GROUP",
                    "scope_id": "alpha",
                },
            )
            assert alpha_admin.status_code == 200
            beta_reader = await client.put(
                f"/api/v1/guilds/{GUILD_A}/rbac/users",
                headers={"X-CSRF-Token": csrf},
                json={
                    "discord_user_id": str(TARGET_USER),
                    "platform_role": "READ_ONLY",
                    "scope_kind": "LOGICAL_GROUP",
                    "scope_id": "beta",
                },
            )
            assert beta_reader.status_code == 200
            assert len(await container.repository.get_accesses(GUILD_A, TARGET_USER)) == 2

            alpha = AuthorizationScope(ScopeKind.LOGICAL_GROUP, "alpha")
            beta = AuthorizationScope(ScopeKind.LOGICAL_GROUP, "beta")
            alpha_decision = await container.authorization.authorize(
                discord_user_id=TARGET_USER,
                guild_id=GUILD_A,
                capability=Capability.RBAC_WRITE,
                scope=alpha,
            )
            assert alpha_decision.role.value == "TENANT_ADMIN"
            with pytest.raises(AuthorizationDenied, match="CAPABILITY_REQUIRED"):
                await container.authorization.authorize(
                    discord_user_id=TARGET_USER,
                    guild_id=GUILD_A,
                    capability=Capability.RBAC_WRITE,
                    scope=beta,
                )
            with pytest.raises(AuthorizationDenied, match="CAPABILITY_REQUIRED"):
                await container.authorization.authorize(
                    discord_user_id=TARGET_USER,
                    guild_id=GUILD_A,
                    capability=Capability.RBAC_WRITE,
                    scope=AuthorizationScope.guild(),
                )

            await container.installations.delegate_user(
                guild_id=GUILD_A,
                actor_user_id=TARGET_USER,
                target_user_id=ROLE_USER,
                role=PlatformRole.READ_ONLY,
                scope=alpha,
            )
            with pytest.raises(AuthorizationDenied, match="CAPABILITY_REQUIRED"):
                await container.installations.delegate_user(
                    guild_id=GUILD_A,
                    actor_user_id=TARGET_USER,
                    target_user_id=ROLE_USER,
                    role=PlatformRole.READ_ONLY,
                    scope=beta,
                )
            with pytest.raises(AuthorizationDenied, match="CAPABILITY_REQUIRED"):
                await container.installations.delegate_user(
                    guild_id=GUILD_A,
                    actor_user_id=TARGET_USER,
                    target_user_id=ROLE_USER,
                    role=PlatformRole.READ_ONLY,
                    scope=AuthorizationScope.guild(),
                )

            guild_admin = await client.put(
                f"/api/v1/guilds/{GUILD_A}/rbac/users",
                headers={"X-CSRF-Token": csrf},
                json={
                    "discord_user_id": str(ADMIN_USER),
                    "platform_role": "TENANT_ADMIN",
                    "scope_kind": "GUILD",
                    "scope_id": "*",
                },
            )
            assert guild_admin.status_code == 200
            with pytest.raises(AuthorizationDenied, match="OWNER_ACCESS_IMMUTABLE"):
                await container.installations.delegate_user(
                    guild_id=GUILD_A,
                    actor_user_id=ADMIN_USER,
                    target_user_id=USER,
                    role=PlatformRole.READ_ONLY,
                    scope=AuthorizationScope.guild(),
                )
            with pytest.raises(AuthorizationDenied, match="OWNER_ACCESS_IMMUTABLE"):
                await container.installations.delegate_user(
                    guild_id=GUILD_A,
                    actor_user_id=ADMIN_USER,
                    target_user_id=USER,
                    role=PlatformRole.READ_ONLY,
                    scope=AuthorizationScope.guild(),
                    revoke=True,
                )
            owner_self_revoke = await client.put(
                f"/api/v1/guilds/{GUILD_A}/rbac/users",
                headers={"X-CSRF-Token": csrf},
                json={
                    "discord_user_id": str(USER),
                    "platform_role": "READ_ONLY",
                    "scope_kind": "GUILD",
                    "scope_id": "*",
                    "revoked": True,
                },
            )
            assert owner_self_revoke.status_code == 403
            assert owner_self_revoke.json()["error"]["code"] == "OWNER_ACCESS_IMMUTABLE"

            with patch.object(container.repository, "save_user_access") as save_access:
                unknown = await client.put(
                    f"/api/v1/guilds/{GUILD_A}/rbac/users",
                    headers={"X-CSRF-Token": csrf},
                    json={
                        "discord_user_id": "858585858585858585",
                        "platform_role": "READ_ONLY",
                        "scope_kind": "LOGICAL_GROUP",
                        "scope_id": "alpha",
                    },
                )
                save_access.assert_not_called()
            assert unknown.status_code == 409
            assert unknown.json()["error"]["code"] == "TARGET_DID_IDENTITY_REQUIRED"

            for scope_id, dashboard_role in (
                ("alpha", "TENANT_ADMIN"),
                ("beta", "READ_ONLY"),
            ):
                response = await client.put(
                    f"/api/v1/guilds/{GUILD_A}/rbac/roles",
                    headers={"X-CSRF-Token": csrf},
                    json={
                        "discord_role_id": "9002",
                        "platform_role": dashboard_role,
                        "scope_kind": "LOGICAL_GROUP",
                        "scope_id": scope_id,
                    },
                )
                assert response.status_code == 200
            role_alpha = await container.authorization.authorize(
                discord_user_id=ROLE_USER,
                guild_id=GUILD_A,
                capability=Capability.RBAC_WRITE,
                scope=alpha,
            )
            assert role_alpha.role.value == "TENANT_ADMIN"
            with pytest.raises(AuthorizationDenied, match="CAPABILITY_REQUIRED"):
                await container.authorization.authorize(
                    discord_user_id=ROLE_USER,
                    guild_id=GUILD_A,
                    capability=Capability.RBAC_WRITE,
                    scope=beta,
                )
            for _ in range(2):
                deleted = await client.delete(
                    f"/api/v1/guilds/{GUILD_A}/rbac/roles/9002",
                    params={"scope_kind": "LOGICAL_GROUP", "scope_id": "alpha"},
                    headers={"X-CSRF-Token": csrf},
                )
                assert deleted.status_code == 204
            with pytest.raises(AuthorizationDenied, match="CAPABILITY_REQUIRED"):
                await container.authorization.authorize(
                    discord_user_id=ROLE_USER,
                    guild_id=GUILD_A,
                    capability=Capability.RBAC_WRITE,
                    scope=alpha,
                )

            await container.authorization.membership_store.put(
                ActorMembership(
                    guild_id=GUILD_A,
                    discord_user_id=TARGET_USER,
                    role_ids=(),
                    observed_at=datetime.now(UTC) - timedelta(seconds=121),
                    source="TARGETED_REST",
                )
            )
            member.missing.add((GUILD_A, TARGET_USER))
            calls_before = len(member.calls)
            with pytest.raises(AuthorizationDenied, match="GUILD_MEMBERSHIP_REQUIRED"):
                await container.authorization.authorize(
                    discord_user_id=TARGET_USER,
                    guild_id=GUILD_A,
                    capability=Capability.RBAC_WRITE,
                    scope=alpha,
                    sensitive=True,
                )
            assert member.calls[calls_before:] == [(GUILD_A, TARGET_USER)]


async def test_installation_reobservation_state_machine_and_identity_are_fail_closed() -> None:
    await reset_stage02()
    application = create_app(
        stage02_settings(), oauth_client=FakeOAuthClient(), member_client=FakeMemberClient()
    )
    async with application.router.lifespan_context(application):
        container = application.state.services

        async def observe() -> None:
            await container.installations.record_detected(
                guild_id=GUILD_A,
                name="Guild A",
                icon_hash=None,
                owner_id=USER,
                application_id=123,
                bot_user_id=999,
            )

        async def status() -> str:
            record = await container.repository.get_installation(GUILD_A, USER)
            assert record is not None
            return record.status.value

        await observe()
        assert await status() == "PENDING_SETUP"
        await observe()
        assert await status() == "PENDING_SETUP"
        await force_installation_status(GUILD_A, "DISCOVERED")
        await observe()
        assert await status() == "PENDING_SETUP"
        await force_installation_status(GUILD_A, "INSTALLED")
        await observe()
        assert await status() == "PENDING_SETUP"
        await force_installation_status(GUILD_A, "ACTIVE")
        await observe()
        assert await status() == "ACTIVE"
        await container.repository.mark_uninstalled(GUILD_A, USER)
        assert await status() == "UNINSTALLED"
        await observe()
        assert await status() == "PENDING_SETUP"
        await force_installation_status(GUILD_A, "DEGRADED")
        await observe()
        assert await status() == "DEGRADED"
        await force_installation_status(GUILD_A, "REVOKED")
        await observe()
        assert await status() == "REVOKED"
        with pytest.raises(InstallationIdentityMismatch, match="identity"):
            await container.installations.record_detected(
                guild_id=GUILD_A,
                name="Guild A",
                icon_hash=None,
                owner_id=USER,
                application_id=456,
                bot_user_id=999,
            )
        assert await status() == "REVOKED"


@pytest.mark.failure_injection
async def test_refresh_is_rotation_safe_and_single_flight() -> None:
    await reset_stage02()
    oauth = FakeOAuthClient()
    oauth.expired_initial = True
    application = create_app(
        stage02_settings(), oauth_client=oauth, member_client=FakeMemberClient()
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            await login(client)
            tokens = await __import__("asyncio").gather(
                application.state.services.auth.access_token(USER),
                application.state.services.auth.access_token(USER),
            )
            assert tokens == ["refreshed-access", "refreshed-access"]
            assert oauth.refresh_calls == 1


async def test_callback_provider_denial_missing_parameters_and_scope_drift_fail_closed() -> None:
    await reset_stage02()
    oauth = FakeOAuthClient()
    application = create_app(
        stage02_settings(), oauth_client=oauth, member_client=FakeMemberClient()
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application, raise_app_exceptions=False),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            missing = await client.get("/auth/discord/callback")
            assert missing.status_code == 400
            assert missing.json()["error"]["code"] == "OAUTH_CALLBACK_INVALID"

            start = await client.get("/auth/discord/login")
            state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
            denied = await client.get(
                "/auth/discord/callback",
                params={"error": "access_denied", "state": state},
            )
            assert denied.status_code == 400
            assert denied.json()["error"]["code"] == "OAUTH_PROVIDER_DENIED"
            assert "did_oauth_binding=" in denied.headers["set-cookie"]
            assert "Max-Age=0" in denied.headers["set-cookie"]
            replay = await client.get(
                "/auth/discord/callback",
                params={"code": "oauth-code", "state": state},
            )
            assert replay.status_code == 400
            assert replay.json()["error"]["code"] == "OAUTH_STATE_INVALID"

            start = await client.get("/auth/discord/login")
            state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
            oauth.unexpected_scopes = True
            drift = await client.get(
                "/auth/discord/callback",
                params={"code": "oauth-code", "state": state},
            )
            assert drift.status_code == 502
            assert drift.json()["error"]["code"] == "OAUTH_EXCHANGE_FAILED"
            assert (await client.get("/api/v1/me")).status_code == 401
