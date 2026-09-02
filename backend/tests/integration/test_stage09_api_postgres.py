"""PostgreSQL + real FastAPI app integration tests for the Stage 09
campaign API router (``did.api.stage09``).

Exercises the router through the exact same real stack
``backend/tests/integration/test_stage02_api.py`` uses for auth (a real
``create_app()`` under ``httpx.ASGITransport``, a fake Discord OAuth/member
client, a real Redis session store) combined with the real
``CampaignsRepository``/``AuthorizationService``/``Stage04Repository`` this
router actually depends on -- so every authorization/ownership/resource-
membership check below is the REAL check, not a stand-in fake.

Covers:
* Campaign create/list/get is owner-scoped; PATCH only while DRAFT.
* A foreign owner's GET/PATCH/target-create/activate on someone else's
  campaign_id returns the identical generic not-found shape -- never a 403
  that would disclose the campaign's existence.
* A target on a Guild the caller is not authorized for is rejected (403)
  before persistence; a target naming a channel that does not belong to the
  declared guild_id is rejected (404-shaped) before persistence.
* Activation of an IMMEDIATE campaign creates real durable work --
  ``message_occurrences``/``message_deliveries``/``discord_io_jobs`` rows,
  asserted directly against the database -- and the router module never
  references the Discord-sending adapter (see the dedicated unit test
  ``test_stage09_api_router_never_sends.py`` for the import-graph proof).
* Variant approval always records the AUTHENTICATED caller as
  ``approved_by_discord_user_id``; a request body that tries to smuggle a
  different one is rejected outright (``extra="forbid"``), never silently
  ignored-but-accepted.
* The ``Idempotency-Key`` header is required on a mutating POST.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text

from did.api.main import create_app
from did.infrastructure.database import create_database_engine
from did.oauth.models import DiscordGuild, DiscordUser, OAuthTokenSet
from did.settings import AppEnvironment, Settings

pytestmark = [pytest.mark.integration, pytest.mark.api, pytest.mark.security]

ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)

GUILD_A = 990100001111
GUILD_FOREIGN = 990100002222
OWNER_A = 990100011111
OWNER_B = 990100012222
CHANNEL_A = 990100021111
CHANNEL_UNKNOWN = 990100099999
BOT_ID = 990100031111

CLEANUP_STATEMENTS = (
    "DELETE FROM discord_io_jobs WHERE guild_id = :ga",
    "DELETE FROM message_deliveries WHERE guild_id = :ga",
    "DELETE FROM message_campaign_targets WHERE guild_id = :ga",
    "DELETE FROM message_campaign_schedules WHERE owner_discord_user_id IN (:oa,:ob)",
    "DELETE FROM message_occurrences WHERE owner_discord_user_id IN (:oa,:ob)",
    "DELETE FROM message_approved_variants WHERE owner_discord_user_id IN (:oa,:ob)",
    "DELETE FROM message_campaigns WHERE owner_discord_user_id IN (:oa,:ob)",
    "DELETE FROM discord_member_authorization_cache WHERE guild_id = :ga",
    "DELETE FROM discord_channels_cache WHERE guild_id = :ga",
    "DELETE FROM discord_roles_cache WHERE guild_id = :ga",
    "DELETE FROM discord_cache_coverage WHERE guild_id = :ga",
    "DELETE FROM guild_role_bindings WHERE guild_id IN (:ga,:gf)",
    "DELETE FROM guild_user_access WHERE guild_id IN (:ga,:gf)",
    "DELETE FROM guild_installations WHERE guild_id IN (:ga,:gf)",
    "DELETE FROM discord_oauth_grants WHERE discord_user_id IN (:oa,:ob)",
    "DELETE FROM users WHERE discord_user_id IN (:oa,:ob)",
)
CLEANUP_PARAMS = {"ga": GUILD_A, "gf": GUILD_FOREIGN, "oa": OWNER_A, "ob": OWNER_B}


async def _reset() -> None:
    engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with engine.begin() as connection:
            for statement in CLEANUP_STATEMENTS:
                await connection.execute(text(statement), CLEANUP_PARAMS)
    finally:
        await engine.dispose()


async def _seed_stage04_snapshot_for_guild_a() -> None:
    """Seeds a REAL Stage04 read-model snapshot for GUILD_A: a bot identity,
    one text channel (``CHANNEL_A``), and an ``@everyone`` role granting
    VIEW_CHANNEL (1024) + SEND_MESSAGES (2048) so the router's real
    ``CampaignGuildAuthorizationChecker.bot_can_send`` (backed by the real
    ``did.permissions.PermissionEvaluator``, not a fake) genuinely resolves
    to True for CHANNEL_A -- exactly what a target/activation test needs to
    prove real destinations are actually reachable, not merely mocked as
    such."""
    engine = create_database_engine(ADMIN_URL, pool_size=1)
    now = datetime.now(UTC)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE guild_installations SET bot_user_id=:bot WHERE guild_id=:guild"),
                {"bot": BOT_ID, "guild": GUILD_A},
            )
            await connection.execute(
                text(
                    "INSERT INTO discord_roles_cache "
                    "(guild_id,role_id,name,position,permissions_bits,managed,color,hoist,"
                    "mentionable,raw_json,last_gateway_seen_at) VALUES "
                    "(:guild,:everyone,'@everyone',0,3072,false,0,false,false,'{}',:now)"
                ),
                {"guild": GUILD_A, "everyone": GUILD_A, "now": now},
            )
            await connection.execute(
                text(
                    "INSERT INTO discord_channels_cache "
                    "(guild_id,channel_id,type,name,parent_id,position,nsfw,last_full_payload,"
                    "observability_state,freshness_state,last_full_observed_at,"
                    "last_gateway_seen_at) VALUES "
                    "(:guild,:channel,0,'general',NULL,0,false,'{}','VISIBLE','FRESH',:now,:now)"
                ),
                {"guild": GUILD_A, "channel": CHANNEL_A, "now": now},
            )
            await connection.execute(
                text(
                    "INSERT INTO discord_cache_coverage "
                    "(guild_id,coverage_mode,freshness_state,known_channels,visible_channels,"
                    "known_roles,last_gateway_event_at,gateway_continuity) VALUES "
                    "(:guild,'FULL','FRESH',1,1,1,:now,'CONNECTED')"
                ),
                {"guild": GUILD_A, "now": now},
            )
            await connection.execute(
                text(
                    "INSERT INTO discord_member_authorization_cache "
                    "(guild_id,discord_user_id,role_ids,source,validity,observed_at) VALUES "
                    "(:guild,:bot,:roles,'TARGETED_REST','FRESH',:now)"
                ),
                {"guild": GUILD_A, "bot": BOT_ID, "roles": [], "now": now},
            )
    finally:
        await engine.dispose()


class FakeOAuthClient:
    """Multi-user fake: each ``code`` maps to its own Discord identity and
    guild list, so two independently-logged-in owners (this router's
    ownership tests need at least two) never share state."""

    def __init__(self) -> None:
        self._users: dict[str, DiscordUser] = {}
        self._guilds: dict[str, tuple[DiscordGuild, ...]] = {}

    def register(self, code: str, user: DiscordUser, guilds: tuple[DiscordGuild, ...]) -> None:
        self._users[code] = user
        self._guilds[code] = guilds

    def authorization_url(self, *, state: str) -> str:
        return f"https://discord.com/oauth2/authorize?state={state}"

    async def exchange_code(self, code: str) -> OAuthTokenSet:
        assert code in self._users
        return OAuthTokenSet(
            access_token=f"access-{code}",
            refresh_token=f"refresh-{code}",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=frozenset({"identify", "guilds"}),
        )

    async def refresh(self, refresh_token: str) -> OAuthTokenSet:  # pragma: no cover
        raise AssertionError(f"refresh should not be needed in this test: {refresh_token}")

    async def revoke(self, token: str) -> None:  # pragma: no cover
        del token

    async def current_user(self, access_token: str) -> DiscordUser:
        code = access_token.removeprefix("access-")
        return self._users[code]

    async def current_user_guilds(self, access_token: str) -> tuple[DiscordGuild, ...]:
        code = access_token.removeprefix("access-")
        return self._guilds[code]


class FakeMemberClient:
    async def get_member_roles(self, guild_id: int, user_id: int) -> tuple[int, ...]:
        del guild_id, user_id
        return ()


def stage09_settings() -> Settings:
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
        session_secret=SecretStr("stage09-test-session-secret-material"),
        oauth_token_encryption_key=SecretStr("a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s"),
        oauth_state_ttl_seconds=60,
        guild_discovery_ttl_seconds=60,
    )


def _app(oauth: FakeOAuthClient):
    return create_app(
        stage09_settings(),
        oauth_client=oauth,  # type: ignore[arg-type]
        member_client=FakeMemberClient(),  # type: ignore[arg-type]
    )


async def _login(client: AsyncClient, code: str) -> str:
    start = await client.get("/auth/discord/login")
    assert start.status_code == 302
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    callback = await client.get("/auth/discord/callback", params={"code": code, "state": state})
    assert callback.status_code == 303
    me = await client.get("/api/v1/me")
    assert me.status_code == 200
    return str(me.json()["csrf_token"])


def _client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        follow_redirects=False,
    )


CAMPAIGN_BODY = {
    "name": "Launch Announcement",
    "source_language_code": "en",
    "message_model": {"content": "Hello world!"},
    "allowed_mentions_policy": {},
    "publication_mode": "IMMEDIATE",
}


async def test_campaign_crud_ownership_idempotency_and_foreign_owner_non_disclosure() -> None:
    await _reset()
    oauth = FakeOAuthClient()
    oauth.register("owner-a", DiscordUser(OWNER_A, "owner-a", None, None), ())
    oauth.register("owner-b", DiscordUser(OWNER_B, "owner-b", None, None), ())
    application = _app(oauth)
    async with application.router.lifespan_context(application):
        async with _client(application) as client_a, _client(application) as client_b:
            csrf_a = await _login(client_a, "owner-a")
            csrf_b = await _login(client_b, "owner-b")

            # Missing Idempotency-Key -> 422, matching the existing
            # header-required convention (did.api.stage06).
            missing_key = await client_a.post(
                "/api/v1/campaigns",
                json=CAMPAIGN_BODY,
                headers={"X-CSRF-Token": csrf_a},
            )
            assert missing_key.status_code == 422

            created = await client_a.post(
                "/api/v1/campaigns",
                json=CAMPAIGN_BODY,
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "launch-2026-01"},
            )
            assert created.status_code == 201
            body = created.json()
            assert body["created"] is True
            campaign = body["campaign"]
            assert campaign["owner_discord_user_id"] == str(OWNER_A)
            assert campaign["lifecycle_status"] == "DRAFT"
            campaign_id = campaign["id"]

            # A client-supplied owner id anywhere in the body would be
            # rejected by extra="forbid" before this point even if sent --
            # confirm the input model has no such field to smuggle one into.
            smuggle_owner = await client_a.post(
                "/api/v1/campaigns",
                json={**CAMPAIGN_BODY, "owner_discord_user_id": str(OWNER_B)},
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "launch-owner-smuggle"},
            )
            assert smuggle_owner.status_code == 422

            # Idempotent replay: the same Idempotency-Key returns the SAME
            # campaign rather than a duplicate or a conflict.
            replayed = await client_a.post(
                "/api/v1/campaigns",
                json=CAMPAIGN_BODY,
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "launch-2026-01"},
            )
            assert replayed.status_code == 201
            assert replayed.json()["created"] is False
            assert replayed.json()["campaign"]["id"] == campaign_id

            listed = await client_a.get("/api/v1/campaigns")
            assert listed.status_code == 200
            assert {item["id"] for item in listed.json()["campaigns"]} == {campaign_id}

            fetched = await client_a.get(f"/api/v1/campaigns/{campaign_id}")
            assert fetched.status_code == 200
            assert fetched.json()["id"] == campaign_id

            patched = await client_a.patch(
                f"/api/v1/campaigns/{campaign_id}",
                json={"expected_version": 1, "name": "Launch Announcement (v2)"},
                headers={"X-CSRF-Token": csrf_a},
            )
            assert patched.status_code == 200
            assert patched.json()["name"] == "Launch Announcement (v2)"
            assert patched.json()["version"] == 2

            # Stale expected_version -> conflict, never a silent overwrite.
            stale_patch = await client_a.patch(
                f"/api/v1/campaigns/{campaign_id}",
                json={"expected_version": 1, "name": "Should not apply"},
                headers={"X-CSRF-Token": csrf_a},
            )
            assert stale_patch.status_code == 409

            # --- Foreign owner: every one of these must be the SAME
            # generic not-found shape, never a 403 that discloses the
            # campaign's existence to OWNER_B.
            foreign_get = await client_b.get(f"/api/v1/campaigns/{campaign_id}")
            assert foreign_get.status_code == 404
            foreign_code = foreign_get.json()["error"]["code"]

            foreign_patch = await client_b.patch(
                f"/api/v1/campaigns/{campaign_id}",
                json={"expected_version": 2, "name": "Hijacked"},
                headers={"X-CSRF-Token": csrf_b},
            )
            assert foreign_patch.status_code == 404
            assert foreign_patch.json()["error"]["code"] == foreign_code

            foreign_target = await client_b.post(
                f"/api/v1/campaigns/{campaign_id}/targets",
                json={
                    "guild_id": str(GUILD_A),
                    "target_kind": "CHANNEL",
                    "discord_channel_id": str(CHANNEL_A),
                },
                headers={"X-CSRF-Token": csrf_b, "Idempotency-Key": "foreign-target"},
            )
            assert foreign_target.status_code == 404
            assert foreign_target.json()["error"]["code"] == foreign_code

            foreign_activate = await client_b.post(
                f"/api/v1/campaigns/{campaign_id}/activate",
                headers={"X-CSRF-Token": csrf_b, "Idempotency-Key": "foreign-activate"},
            )
            assert foreign_activate.status_code == 404
            assert foreign_activate.json()["error"]["code"] == foreign_code

            # A totally nonexistent campaign_id gets the IDENTICAL shape --
            # a caller can never distinguish "not yours" from "never
            # existed".
            never_existed = await client_b.get(f"/api/v1/campaigns/{uuid4()}")
            assert never_existed.status_code == 404
            assert never_existed.json()["error"]["code"] == foreign_code


async def test_campaign_message_model_embeds_and_components_are_validated_and_round_trip() -> None:
    """REQ-MSG-013/mission section 9: did.messaging.message_model
    .validate_message_model is now genuinely enforced at every API entry
    point that accepts a message_model (create/update/owned-edit) -- not
    merely documented as such. An over-limit or structurally invalid embed/
    button is rejected with 422 before it is ever persisted; a valid one
    round-trips exactly, including the technical fields (embed url/color,
    button custom_id/url) REQ-MSG-013's translation policy protects
    elsewhere."""
    await _reset()
    oauth = FakeOAuthClient()
    oauth.register("owner-a", DiscordUser(OWNER_A, "owner-a", None, None), ())
    application = _app(oauth)
    async with application.router.lifespan_context(application):
        async with _client(application) as client:
            csrf = await _login(client, "owner-a")

            # A LINK-style button must not carry a custom_id -- rejected
            # before persistence, exactly the same DiscordLimits contract
            # did.messaging.message_model.validate_message_model enforces
            # for a real Discord edit.
            invalid = await client.post(
                "/api/v1/campaigns",
                json={
                    **CAMPAIGN_BODY,
                    "message_model": {
                        "content": "Hello",
                        "embeds": [],
                        "action_rows": [
                            {
                                "buttons": [
                                    {
                                        "label": "Visit",
                                        "style": "LINK",
                                        "url": "https://example.com",
                                        "custom_id": "not-allowed-on-link",
                                    }
                                ]
                            }
                        ],
                    },
                },
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "invalid-message-model"},
            )
            assert invalid.status_code == 422
            assert invalid.json()["error"]["code"] == "CAMPAIGN_INPUT_INVALID"

            valid = await client.post(
                "/api/v1/campaigns",
                json={
                    **CAMPAIGN_BODY,
                    "message_model": {
                        "content": "Hello",
                        "embeds": [
                            {
                                "title": "Launch",
                                "description": "Big news",
                                "url": "https://example.com/launch",
                                "color": 5793266,
                                "footer_text": "Autumn sale",
                                "author_name": "The Team",
                                "fields": [{"name": "Starts", "value": "Today", "inline": True}],
                            }
                        ],
                        "action_rows": [
                            {
                                "buttons": [
                                    {
                                        "label": "Visit",
                                        "style": "LINK",
                                        "url": "https://example.com",
                                    },
                                    {
                                        "label": "Confirm",
                                        "style": "PRIMARY",
                                        "custom_id": "confirm-launch",
                                    },
                                ]
                            }
                        ],
                    },
                },
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "valid-message-model"},
            )
            assert valid.status_code == 201
            model = valid.json()["campaign"]["message_model"]
            assert model["embeds"][0]["title"] == "Launch"
            assert model["embeds"][0]["url"] == "https://example.com/launch"
            assert model["embeds"][0]["fields"][0]["name"] == "Starts"
            assert model["action_rows"][0]["buttons"][0]["url"] == "https://example.com"
            assert model["action_rows"][0]["buttons"][1]["custom_id"] == "confirm-launch"


async def test_target_creation_guild_authorization_and_resource_membership() -> None:
    await _reset()
    oauth = FakeOAuthClient()
    oauth.register(
        "owner-a",
        DiscordUser(OWNER_A, "owner-a", None, None),
        (DiscordGuild(GUILD_A, "Guild A", None, True, 0),),
    )
    application = _app(oauth)
    async with application.router.lifespan_context(application):
        container = application.state.services
        await container.installations.record_detected(
            guild_id=GUILD_A,
            name="Guild A",
            icon_hash=None,
            owner_id=OWNER_A,
            application_id=123,
            bot_user_id=BOT_ID,
        )
        async with _client(application) as client:
            csrf = await _login(client, "owner-a")
            bootstrapped = await client.post(
                f"/api/v1/guilds/{GUILD_A}/bootstrap", headers={"X-CSRF-Token": csrf}
            )
            assert bootstrapped.status_code == 200
            await _seed_stage04_snapshot_for_guild_a()

            created = await client.post(
                "/api/v1/campaigns",
                json=CAMPAIGN_BODY,
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "target-tests"},
            )
            assert created.status_code == 201
            campaign_id = created.json()["campaign"]["id"]

            # GUILD_FOREIGN was never bootstrapped/authorized for OWNER_A --
            # rejected before any target row is persisted.
            not_authorized = await client.post(
                f"/api/v1/campaigns/{campaign_id}/targets",
                json={
                    "guild_id": str(GUILD_FOREIGN),
                    "target_kind": "CHANNEL",
                    "discord_channel_id": str(CHANNEL_A),
                },
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "target-guild-not-authorized"},
            )
            assert not_authorized.status_code == 403

            # CHANNEL_UNKNOWN was never seeded as belonging to GUILD_A's
            # real Stage04 snapshot -- rejected before any target row is
            # persisted, even though the caller IS authorized for GUILD_A
            # itself.
            unknown_channel = await client.post(
                f"/api/v1/campaigns/{campaign_id}/targets",
                json={
                    "guild_id": str(GUILD_A),
                    "target_kind": "CHANNEL",
                    "discord_channel_id": str(CHANNEL_UNKNOWN),
                },
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "target-unknown-channel"},
            )
            assert unknown_channel.status_code == 404

            valid_target = await client.post(
                f"/api/v1/campaigns/{campaign_id}/targets",
                json={
                    "guild_id": str(GUILD_A),
                    "target_kind": "CHANNEL",
                    "discord_channel_id": str(CHANNEL_A),
                },
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "target-valid"},
            )
            assert valid_target.status_code == 201
            assert valid_target.json()["target"]["discord_channel_id"] == str(CHANNEL_A)
            assert valid_target.json()["bot_send_preflight_ok"] is True

            listed = await client.get(f"/api/v1/campaigns/{campaign_id}/targets")
            assert listed.status_code == 200
            assert len(listed.json()["targets"]) == 1

            # Neither rejected attempt above ever persisted a row.
            assert unknown_channel.status_code == 404
            assert len(listed.json()["targets"]) == 1


async def test_trigger_creation_message_content_dependency_is_blocked() -> None:
    """REQ-MSG-020, Option B (did.campaigns.message_content_policy's module
    docstring): Stage09 has no content-capture capability at all right now,
    so declaring requires_message_content=True is always rejected before
    the trigger is ever persisted -- never silently accepted, never left as
    a half-working configuration."""
    await _reset()
    oauth = FakeOAuthClient()
    oauth.register("owner-a", DiscordUser(OWNER_A, "owner-a", None, None), ())
    application = _app(oauth)
    async with application.router.lifespan_context(application):
        async with _client(application) as client:
            csrf = await _login(client, "owner-a")
            created = await client.post(
                "/api/v1/campaigns",
                json=CAMPAIGN_BODY,
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "trigger-tests"},
            )
            assert created.status_code == 201
            campaign_id = created.json()["campaign"]["id"]

            blocked = await client.post(
                f"/api/v1/campaigns/{campaign_id}/triggers",
                json={
                    "event_type": "MEMBER_JOIN",
                    "condition_ast": {"op": "ALWAYS"},
                    "requires_message_content": True,
                },
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "trigger-blocked"},
            )
            assert blocked.status_code == 422
            assert blocked.json()["error"]["code"] == "CAMPAIGN_TRIGGER_MESSAGE_CONTENT_UNAVAILABLE"

            engine = create_database_engine(ADMIN_URL, pool_size=1)
            try:
                async with engine.begin() as connection:
                    trigger_count = (
                        await connection.execute(
                            text(
                                "SELECT count(*) FROM message_campaign_triggers "
                                "WHERE campaign_id=:cid"
                            ),
                            {"cid": campaign_id},
                        )
                    ).scalar_one()
                    assert trigger_count == 0
            finally:
                await engine.dispose()

            # A trigger that does NOT declare the dependency is unaffected --
            # proves the block is specific to requires_message_content, not
            # a general trigger-creation regression.
            allowed = await client.post(
                f"/api/v1/campaigns/{campaign_id}/triggers",
                json={
                    "event_type": "MEMBER_JOIN",
                    "condition_ast": {"op": "ALWAYS"},
                    "requires_message_content": False,
                },
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "trigger-allowed"},
            )
            assert allowed.status_code == 201
            assert allowed.json()["requires_message_content"] is False


async def test_activation_creates_durable_work_never_sends_and_variant_identity() -> None:
    await _reset()
    oauth = FakeOAuthClient()
    oauth.register(
        "owner-a",
        DiscordUser(OWNER_A, "owner-a", None, None),
        (DiscordGuild(GUILD_A, "Guild A", None, True, 0),),
    )
    application = _app(oauth)
    async with application.router.lifespan_context(application):
        container = application.state.services
        await container.installations.record_detected(
            guild_id=GUILD_A,
            name="Guild A",
            icon_hash=None,
            owner_id=OWNER_A,
            application_id=123,
            bot_user_id=BOT_ID,
        )
        async with _client(application) as client:
            csrf = await _login(client, "owner-a")
            assert (
                await client.post(
                    f"/api/v1/guilds/{GUILD_A}/bootstrap", headers={"X-CSRF-Token": csrf}
                )
            ).status_code == 200
            await _seed_stage04_snapshot_for_guild_a()

            created = await client.post(
                "/api/v1/campaigns",
                json=CAMPAIGN_BODY,
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "activation-tests"},
            )
            assert created.status_code == 201
            campaign_id = created.json()["campaign"]["id"]

            target = await client.post(
                f"/api/v1/campaigns/{campaign_id}/targets",
                json={
                    "guild_id": str(GUILD_A),
                    "target_kind": "CHANNEL",
                    "discord_channel_id": str(CHANNEL_A),
                },
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "activation-target"},
            )
            assert target.status_code == 201

            simulated = await client.post(f"/api/v1/campaigns/{campaign_id}/simulate")
            assert simulated.status_code == 200
            assert simulated.json()["estimated_delivery_count"] == 1
            # No trigger declares requires_message_content -- nothing to
            # warn about (see test_trigger_creation_message_content_
            # dependency_is_blocked for the case where one is attempted).
            assert simulated.json()["message_content_warnings"] == []

            activated = await client.post(
                f"/api/v1/campaigns/{campaign_id}/activate",
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "activation-go"},
            )
            assert activated.status_code == 200
            payload = activated.json()
            assert payload["campaign"]["lifecycle_status"] == "ACTIVE_RUNNING"
            assert payload["durable_work"]["occurrence_created"] is True
            assert payload["durable_work"]["deliveries_created"] == 1
            assert payload["durable_work"]["deliveries_routed"] == 1
            assert payload["durable_work"]["is_fully_healthy"] is True

            # Assert on the ACTUAL database state -- not just the response.
            engine = create_database_engine(ADMIN_URL, pool_size=1)
            try:
                async with engine.begin() as connection:
                    occurrence_count = (
                        await connection.execute(
                            text(
                                "SELECT count(*) FROM message_occurrences "
                                "WHERE campaign_id=:cid AND status IN ('FANNED_OUT','COMPLETED')"
                            ),
                            {"cid": campaign_id},
                        )
                    ).scalar_one()
                    assert occurrence_count == 1
                    delivery_row = (
                        (
                            await connection.execute(
                                text(
                                    "SELECT status, discord_message_id FROM message_deliveries "
                                    "WHERE campaign_id=:cid"
                                ),
                                {"cid": campaign_id},
                            )
                        )
                        .mappings()
                        .one()
                    )
                    assert delivery_row["status"] == "PENDING"
                    # Never actually sent -- no discord_message_id yet, and
                    # never will be from this HTTP request: only the
                    # separate durable worker process ever calls Discord.
                    assert delivery_row["discord_message_id"] is None
                    job_count = (
                        await connection.execute(
                            text(
                                "SELECT count(*) FROM discord_io_jobs "
                                "WHERE guild_id=:gid AND workload_type='SEND_CAMPAIGN_MESSAGE'"
                            ),
                            {"gid": GUILD_A},
                        )
                    ).scalar_one()
                    assert job_count == 1
            finally:
                await engine.dispose()

            # --- Variant approval identity (REQ-MSG-016 gap closed): the
            # approving principal is ALWAYS the authenticated caller.
            smuggled = await client.post(
                f"/api/v1/campaigns/{campaign_id}/variants/fr/approve",
                json={
                    "localized_message_model": {"content": "Bonjour le monde !"},
                    "approving_discord_user_id": str(OWNER_B),
                },
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "variant-smuggle"},
            )
            assert smuggled.status_code == 422

            approved = await client.post(
                f"/api/v1/campaigns/{campaign_id}/variants/fr/approve",
                json={"localized_message_model": {"content": "Bonjour le monde !"}},
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "variant-approve"},
            )
            assert approved.status_code == 201
            assert approved.json()["approved_by_discord_user_id"] == str(OWNER_A)

            preview = await client.get(f"/api/v1/campaigns/{campaign_id}/variants/fr")
            assert preview.status_code == 200
            assert preview.json()["outcome"] == "REUSABLE"
            assert preview.json()["approved_variant"]["approved_by_discord_user_id"] == str(OWNER_A)


async def test_intervention_resolution_and_requeue_product_flow() -> None:
    """REQ-MSG-029 product surface: never a universal Retry button -- an
    INTERVENTION_REQUIRED delivery only resolves to the owner's own
    attested outcome (SENT with a real discord_message_id, or FAILED), and
    only a confirmed-FAILED delivery can be requeued for a fresh send.
    Neither endpoint ever calls Discord (see did.api.stage09's own
    never-sends regression test for the router-wide proof); this test
    proves the HTTP-level ownership/state-machine contract specifically."""
    await _reset()
    oauth = FakeOAuthClient()
    oauth.register(
        "owner-a",
        DiscordUser(OWNER_A, "owner-a", None, None),
        (DiscordGuild(GUILD_A, "Guild A", None, True, 0),),
    )
    oauth.register("owner-b", DiscordUser(OWNER_B, "owner-b", None, None), ())
    application = _app(oauth)
    async with application.router.lifespan_context(application):
        container = application.state.services
        await container.installations.record_detected(
            guild_id=GUILD_A,
            name="Guild A",
            icon_hash=None,
            owner_id=OWNER_A,
            application_id=123,
            bot_user_id=BOT_ID,
        )
        async with _client(application) as client_a, _client(application) as client_b:
            csrf_a = await _login(client_a, "owner-a")
            csrf_b = await _login(client_b, "owner-b")
            assert (
                await client_a.post(
                    f"/api/v1/guilds/{GUILD_A}/bootstrap", headers={"X-CSRF-Token": csrf_a}
                )
            ).status_code == 200
            await _seed_stage04_snapshot_for_guild_a()

            created = await client_a.post(
                "/api/v1/campaigns",
                json=CAMPAIGN_BODY,
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "intervention-tests"},
            )
            assert created.status_code == 201
            campaign_id = created.json()["campaign"]["id"]
            target = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/targets",
                json={
                    "guild_id": str(GUILD_A),
                    "target_kind": "CHANNEL",
                    "discord_channel_id": str(CHANNEL_A),
                },
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "intervention-target"},
            )
            assert target.status_code == 201
            activated = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/activate",
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "intervention-go"},
            )
            assert activated.status_code == 200

            engine = create_database_engine(ADMIN_URL, pool_size=1)
            try:
                async with engine.begin() as connection:
                    delivery_id = (
                        await connection.execute(
                            text("SELECT id FROM message_deliveries WHERE campaign_id=:cid"),
                            {"cid": campaign_id},
                        )
                    ).scalar_one()
                    await connection.execute(
                        text(
                            "UPDATE message_deliveries SET status='INTERVENTION_REQUIRED', "
                            "discord_nonce='intervention-test-nonce' WHERE id=:id"
                        ),
                        {"id": delivery_id},
                    )
            finally:
                await engine.dispose()

            # --- Validation: SENT requires a message id, FAILED forbids one.
            sent_missing_id = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/intervention/resolve",
                json={"resolution": "SENT"},
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "resolve-missing-id"},
            )
            assert sent_missing_id.status_code == 422

            failed_with_id = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/intervention/resolve",
                json={"resolution": "FAILED", "discord_message_id": str(CHANNEL_A)},
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "resolve-extra-id"},
            )
            assert failed_with_id.status_code == 422

            # --- A foreign owner can never resolve someone else's
            # intervention -- identical not-found shape, never a 403.
            foreign_resolve = await client_b.post(
                f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/intervention/resolve",
                json={"resolution": "FAILED"},
                headers={"X-CSRF-Token": csrf_b, "Idempotency-Key": "resolve-foreign"},
            )
            assert foreign_resolve.status_code == 404

            # --- Real resolution: the owner attests the message was sent,
            # supplying the discord_message_id they observed themselves.
            resolved = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/intervention/resolve",
                json={"resolution": "SENT", "discord_message_id": "123456789012345678"},
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "resolve-sent"},
            )
            assert resolved.status_code == 200
            assert resolved.json()["delivery"]["status"] == "SENT"
            assert resolved.json()["delivery"]["discord_message_id"] == "123456789012345678"

            # --- Already resolved -- no longer claimable, never a duplicate
            # resolution or a silent no-op success.
            replay = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/intervention/resolve",
                json={"resolution": "FAILED"},
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "resolve-replay"},
            )
            assert replay.status_code == 404

            # --- A SENT delivery is never requeuable (only FAILED is).
            requeue_sent = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/requeue",
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "requeue-sent"},
            )
            assert requeue_sent.status_code == 404

            # --- Separate delivery, resolved FAILED, is genuinely requeuable.
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE message_deliveries SET status='FAILED', last_error='boom' "
                        "WHERE id=:id"
                    ),
                    {"id": delivery_id},
                )
            failed_requeue_foreign = await client_b.post(
                f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/requeue",
                headers={"X-CSRF-Token": csrf_b, "Idempotency-Key": "requeue-foreign"},
            )
            assert failed_requeue_foreign.status_code == 404

            requeued = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/requeue",
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "requeue-real"},
            )
            assert requeued.status_code == 200
            assert requeued.json()["delivery"]["status"] == "PENDING"
            assert requeued.json()["delivery"]["discord_message_id"] is None

            engine2 = create_database_engine(ADMIN_URL, pool_size=1)
            try:
                async with engine2.begin() as connection:
                    row = (
                        (
                            await connection.execute(
                                text(
                                    "SELECT discord_nonce, attempt_count FROM message_deliveries "
                                    "WHERE id=:id"
                                ),
                                {"id": delivery_id},
                            )
                        )
                        .mappings()
                        .one()
                    )
                    assert row["discord_nonce"] != "intervention-test-nonce"
                    assert row["attempt_count"] == 0
            finally:
                await engine2.dispose()


async def test_owned_edit_and_delete_never_accept_a_client_supplied_message_id() -> None:
    """REQ-MSG owned edit/delete (mission sections 7-8): the edit/delete
    endpoints only ever act through the owned delivery ledger -- proves
    this at the HTTP contract level (no request body field could ever name
    a channel/message, extra="forbid" rejects any attempt) and at the
    product level (ownership enforced, only a SENT delivery is eligible,
    both endpoints only ever create durable work -- discord_io_jobs rows --
    never a discord_message_id change from this handler alone)."""
    await _reset()
    oauth = FakeOAuthClient()
    oauth.register(
        "owner-a",
        DiscordUser(OWNER_A, "owner-a", None, None),
        (DiscordGuild(GUILD_A, "Guild A", None, True, 0),),
    )
    oauth.register("owner-b", DiscordUser(OWNER_B, "owner-b", None, None), ())
    application = _app(oauth)
    async with application.router.lifespan_context(application):
        container = application.state.services
        await container.installations.record_detected(
            guild_id=GUILD_A,
            name="Guild A",
            icon_hash=None,
            owner_id=OWNER_A,
            application_id=123,
            bot_user_id=BOT_ID,
        )
        async with _client(application) as client_a, _client(application) as client_b:
            csrf_a = await _login(client_a, "owner-a")
            csrf_b = await _login(client_b, "owner-b")
            assert (
                await client_a.post(
                    f"/api/v1/guilds/{GUILD_A}/bootstrap", headers={"X-CSRF-Token": csrf_a}
                )
            ).status_code == 200
            await _seed_stage04_snapshot_for_guild_a()

            created = await client_a.post(
                "/api/v1/campaigns",
                json=CAMPAIGN_BODY,
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "owned-edit-delete-tests"},
            )
            assert created.status_code == 201
            campaign_id = created.json()["campaign"]["id"]
            target = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/targets",
                json={
                    "guild_id": str(GUILD_A),
                    "target_kind": "CHANNEL",
                    "discord_channel_id": str(CHANNEL_A),
                },
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "owned-edit-target"},
            )
            assert target.status_code == 201
            activated = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/activate",
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "owned-edit-go"},
            )
            assert activated.status_code == 200

            engine = create_database_engine(ADMIN_URL, pool_size=1)
            try:
                async with engine.begin() as connection:
                    delivery_id = (
                        await connection.execute(
                            text("SELECT id FROM message_deliveries WHERE campaign_id=:cid"),
                            {"cid": campaign_id},
                        )
                    ).scalar_one()
                    await connection.execute(
                        text(
                            "UPDATE message_deliveries SET status='SENT', "
                            "discord_message_id=987654321098765432 WHERE id=:id"
                        ),
                        {"id": delivery_id},
                    )
            finally:
                await engine.dispose()

            # The edit request body has no field a client could use to
            # smuggle a channel/message id -- extra="forbid" rejects the
            # attempt before the handler even runs.
            smuggle = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/edit",
                json={"message_model": {"content": "edited"}, "discord_message_id": "1"},
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "edit-smuggle"},
            )
            assert smuggle.status_code == 422

            # A foreign owner can never edit or delete someone else's
            # delivery -- identical not-found shape, never a 403.
            foreign_edit = await client_b.post(
                f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/edit",
                json={"message_model": {"content": "hijacked"}},
                headers={"X-CSRF-Token": csrf_b, "Idempotency-Key": "edit-foreign"},
            )
            assert foreign_edit.status_code == 404
            foreign_delete = await client_b.post(
                f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/delete",
                headers={"X-CSRF-Token": csrf_b, "Idempotency-Key": "delete-foreign"},
            )
            assert foreign_delete.status_code == 404

            edited = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/edit",
                json={"message_model": {"content": "edited content"}},
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "edit-real"},
            )
            assert edited.status_code == 200
            assert edited.json()["delivery"]["status"] == "SENT"

            deleted = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/delete",
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "delete-real"},
            )
            assert deleted.status_code == 200
            # The router never calls Discord -- status is still SENT right
            # after this HTTP response; only the durable worker (never
            # exercised by this HTTP-only test) transitions it to DELETED.
            assert deleted.json()["delivery"]["status"] == "SENT"

            engine2 = create_database_engine(ADMIN_URL, pool_size=1)
            try:
                async with engine2.begin() as connection:
                    content = (
                        await connection.execute(
                            text("SELECT content_snapshot FROM message_deliveries WHERE id=:id"),
                            {"id": delivery_id},
                        )
                    ).scalar_one()
                    assert content["content"] == "edited content"
                    job_types = (
                        (
                            await connection.execute(
                                text(
                                    "SELECT workload_type FROM discord_io_jobs "
                                    "WHERE guild_id=:gid ORDER BY created_at"
                                ),
                                {"gid": GUILD_A},
                            )
                        )
                        .scalars()
                        .all()
                    )
                    assert "EDIT_CAMPAIGN_MESSAGE" in job_types
                    assert "DELETE_CAMPAIGN_MESSAGE" in job_types
            finally:
                await engine2.dispose()


async def test_template_variable_crud_validation_and_ownership() -> None:
    """REQ-MSG-018 (mission section 10): full authoring CRUD, ownership
    isolation (same generic not-found shape as every other resource in
    this router), and shape validation delegated to the same domain type
    the render pipeline actually consumes (did.messaging.template_variables
    .TemplateVariableDefinition) -- never a second, looser validation path."""
    await _reset()
    oauth = FakeOAuthClient()
    oauth.register("owner-a", DiscordUser(OWNER_A, "owner-a", None, None), ())
    oauth.register("owner-b", DiscordUser(OWNER_B, "owner-b", None, None), ())
    application = _app(oauth)
    async with application.router.lifespan_context(application):
        async with _client(application) as client_a, _client(application) as client_b:
            csrf_a = await _login(client_a, "owner-a")
            csrf_b = await _login(client_b, "owner-b")
            created = await client_a.post(
                "/api/v1/campaigns",
                json=CAMPAIGN_BODY,
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "template-variable-tests"},
            )
            assert created.status_code == 201
            campaign_id = created.json()["campaign"]["id"]

            # LOCALIZED_VALUE must not also carry a single `value` --
            # rejected before persistence, the exact shape rule
            # TemplateVariableDefinition.__post_init__ enforces.
            invalid = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/template-variables",
                json={
                    "name": "price",
                    "variable_type": "LOCALIZED_VALUE",
                    "value": "not allowed here",
                    "values_by_language": {"en": "$10"},
                },
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "tv-invalid"},
            )
            assert invalid.status_code == 422

            first = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/template-variables",
                json={"name": "name", "variable_type": "TRANSLATABLE_TEXT", "value": "Alex"},
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "tv-create-1"},
            )
            assert first.status_code == 201
            variable_id = first.json()["id"]
            assert first.json()["value"] == "Alex"

            # A foreign owner can never create/list/update/delete another
            # owner's campaign's template variables -- identical not-found
            # shape, never a 403.
            foreign_create = await client_b.post(
                f"/api/v1/campaigns/{campaign_id}/template-variables",
                json={"name": "other", "variable_type": "TRANSLATABLE_TEXT", "value": "x"},
                headers={"X-CSRF-Token": csrf_b, "Idempotency-Key": "tv-foreign-create"},
            )
            assert foreign_create.status_code == 404
            foreign_update = await client_b.patch(
                f"/api/v1/campaigns/{campaign_id}/template-variables/{variable_id}",
                json={"variable_type": "TRANSLATABLE_TEXT", "value": "hijacked"},
                headers={"X-CSRF-Token": csrf_b},
            )
            assert foreign_update.status_code == 404
            foreign_delete = await client_b.delete(
                f"/api/v1/campaigns/{campaign_id}/template-variables/{variable_id}",
                headers={"X-CSRF-Token": csrf_b},
            )
            assert foreign_delete.status_code == 404

            # Duplicate name within the same campaign is a conflict, never
            # a silent overwrite.
            duplicate = await client_a.post(
                f"/api/v1/campaigns/{campaign_id}/template-variables",
                json={"name": "name", "variable_type": "TRANSLATABLE_TEXT", "value": "Jordan"},
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "tv-create-dup"},
            )
            assert duplicate.status_code == 409

            listed = await client_a.get(f"/api/v1/campaigns/{campaign_id}/template-variables")
            assert listed.status_code == 200
            assert len(listed.json()["template_variables"]) == 1

            updated = await client_a.patch(
                f"/api/v1/campaigns/{campaign_id}/template-variables/{variable_id}",
                json={"variable_type": "NON_TRANSLATABLE", "value": "Fixed"},
                headers={"X-CSRF-Token": csrf_a},
            )
            assert updated.status_code == 200
            assert updated.json()["variable_type"] == "NON_TRANSLATABLE"
            assert updated.json()["value"] == "Fixed"
            # The name itself is never editable through this endpoint.
            assert updated.json()["name"] == "name"

            deleted = await client_a.delete(
                f"/api/v1/campaigns/{campaign_id}/template-variables/{variable_id}",
                headers={"X-CSRF-Token": csrf_a},
            )
            assert deleted.status_code == 204
            listed_after_delete = await client_a.get(
                f"/api/v1/campaigns/{campaign_id}/template-variables"
            )
            assert listed_after_delete.json()["template_variables"] == []


async def test_glossary_crud_authorization_across_all_three_scopes() -> None:
    """REQ-MSG-014 (mission section 11): CAMPAIGN needs campaign ownership,
    GUILD needs real Guild authorization (never merely being logged in),
    GLOBAL_USER needs only authentication -- each verified independently,
    plus duplicate-term conflict and shape-invalid rejection."""
    await _reset()
    oauth = FakeOAuthClient()
    oauth.register(
        "owner-a",
        DiscordUser(OWNER_A, "owner-a", None, None),
        (DiscordGuild(GUILD_A, "Guild A", None, True, 0),),
    )
    oauth.register("owner-b", DiscordUser(OWNER_B, "owner-b", None, None), ())
    application = _app(oauth)
    async with application.router.lifespan_context(application):
        container = application.state.services
        await container.installations.record_detected(
            guild_id=GUILD_A,
            name="Guild A",
            icon_hash=None,
            owner_id=OWNER_A,
            application_id=123,
            bot_user_id=BOT_ID,
        )
        async with _client(application) as client_a, _client(application) as client_b:
            csrf_a = await _login(client_a, "owner-a")
            csrf_b = await _login(client_b, "owner-b")
            assert (
                await client_a.post(
                    f"/api/v1/guilds/{GUILD_A}/bootstrap", headers={"X-CSRF-Token": csrf_a}
                )
            ).status_code == 200
            await _seed_stage04_snapshot_for_guild_a()

            created = await client_a.post(
                "/api/v1/campaigns",
                json=CAMPAIGN_BODY,
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "glossary-tests"},
            )
            assert created.status_code == 201
            campaign_id = created.json()["campaign"]["id"]

            # GLOBAL_USER: only authentication required.
            global_entry = await client_a.post(
                "/api/v1/glossary",
                json={
                    "scope_kind": "GLOBAL_USER",
                    "source_term": "Widget",
                    "behavior": "DO_NOT_TRANSLATE",
                },
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "glossary-global"},
            )
            assert global_entry.status_code == 201
            global_id = global_entry.json()["id"]

            # CAMPAIGN: requires owning the campaign -- a foreign owner is
            # rejected with the same generic not-found shape.
            foreign_campaign_entry = await client_b.post(
                "/api/v1/glossary",
                json={
                    "scope_kind": "CAMPAIGN",
                    "campaign_id": campaign_id,
                    "source_term": "Gadget",
                    "behavior": "DO_NOT_TRANSLATE",
                },
                headers={"X-CSRF-Token": csrf_b, "Idempotency-Key": "glossary-foreign-campaign"},
            )
            assert foreign_campaign_entry.status_code == 404

            campaign_entry = await client_a.post(
                "/api/v1/glossary",
                json={
                    "scope_kind": "CAMPAIGN",
                    "campaign_id": campaign_id,
                    "source_term": "Gadget",
                    "behavior": "FORCED_TRANSLATION",
                    "forced_translation": "Widget",
                },
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "glossary-campaign"},
            )
            assert campaign_entry.status_code == 201
            campaign_entry_id = campaign_entry.json()["id"]

            # Shape-invalid: FORCED_TRANSLATION without forced_translation text.
            invalid = await client_a.post(
                "/api/v1/glossary",
                json={
                    "scope_kind": "GLOBAL_USER",
                    "source_term": "Thingamajig",
                    "behavior": "FORCED_TRANSLATION",
                },
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "glossary-invalid"},
            )
            assert invalid.status_code == 422

            # GUILD: unauthorized Guild is rejected before persistence.
            unauthorized_guild_entry = await client_a.post(
                "/api/v1/glossary",
                json={
                    "scope_kind": "GUILD",
                    "guild_id": str(GUILD_FOREIGN),
                    "source_term": "Doohickey",
                    "behavior": "DO_NOT_TRANSLATE",
                },
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "glossary-unauth-guild"},
            )
            assert unauthorized_guild_entry.status_code == 403

            guild_entry = await client_a.post(
                "/api/v1/glossary",
                json={
                    "scope_kind": "GUILD",
                    "guild_id": str(GUILD_A),
                    "source_term": "Doohickey",
                    "behavior": "DO_NOT_TRANSLATE",
                },
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "glossary-guild"},
            )
            assert guild_entry.status_code == 201
            guild_entry_id = guild_entry.json()["id"]

            # Duplicate term within the same (owner, scope, campaign/guild,
            # language) tuple is a conflict, never a silent overwrite.
            duplicate = await client_a.post(
                "/api/v1/glossary",
                json={
                    "scope_kind": "GLOBAL_USER",
                    "source_term": "Widget",
                    "behavior": "DO_NOT_TRANSLATE",
                },
                headers={"X-CSRF-Token": csrf_a, "Idempotency-Key": "glossary-dup"},
            )
            assert duplicate.status_code == 409

            # Listing surfaces exactly the right scope.
            assert len((await client_a.get("/api/v1/glossary")).json()["glossary_entries"]) == 1
            assert (
                len(
                    (await client_a.get(f"/api/v1/campaigns/{campaign_id}/glossary")).json()[
                        "glossary_entries"
                    ]
                )
                == 1
            )
            unauthorized_guild_list = await client_b.get(f"/api/v1/guilds/{GUILD_A}/glossary")
            assert unauthorized_guild_list.status_code == 403
            authorized_guild_list = await client_a.get(f"/api/v1/guilds/{GUILD_A}/glossary")
            assert authorized_guild_list.status_code == 200
            assert len(authorized_guild_list.json()["glossary_entries"]) == 1

            # A foreign owner can never delete another owner's GLOBAL_USER/
            # CAMPAIGN entry.
            assert (
                await client_b.delete(
                    f"/api/v1/glossary/{global_id}", headers={"X-CSRF-Token": csrf_b}
                )
            ).status_code == 404
            assert (
                await client_b.delete(
                    f"/api/v1/glossary/{campaign_entry_id}", headers={"X-CSRF-Token": csrf_b}
                )
            ).status_code == 404

            deleted = await client_a.delete(
                f"/api/v1/glossary/{guild_entry_id}", headers={"X-CSRF-Token": csrf_a}
            )
            assert deleted.status_code == 204
            assert (await client_a.get(f"/api/v1/guilds/{GUILD_A}/glossary")).json()[
                "glossary_entries"
            ] == []
