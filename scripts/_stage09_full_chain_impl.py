"""Implementation for validate_discord_live_stage09_full_chain.py, kept in a
separate module so the CLI wrapper's argument parsing works even when the
heavy did.* import graph is unavailable (e.g. `--help`), and so `--include`
only pays the import cost when it is actually needed. Not a package member
of `did` -- this is test/ops-only scaffolding, imported directly by path
(scripts/ is added to sys.path by the CLI wrapper) exactly like every other
validate_discord_live_stageNN.py script in this repository.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import discord
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from did.api.main import create_app
from did.campaigns.approved_variants import compute_source_fingerprint
from did.campaigns.dispatch import CampaignDeliveryExecutor
from did.campaigns.retention import RetentionPolicy, purge_expired_deliveries
from did.campaigns.runtime import CampaignSchedulerRuntime
from did.domain.campaigns import ApprovedVariant, MessageCampaign
from did.infrastructure.campaigns_repository import CampaignsRepository
from did.infrastructure.database import create_database_engine
from did.infrastructure.discord_message_sender import DiscordPyMessageSender
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage04_repository import Stage04Repository
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    TranslationGroupRepository,
    TranslationProviderBindingRepository,
)
from did.messaging.message_model import MessageModel
from did.oauth.models import DiscordGuild, DiscordUser, OAuthTokenSet
from did.settings import AppEnvironment, Settings
from did.translation.googletrans_adapter import GoogletransCampaignTranslationProvider
from did.worker.io import DurableDiscordIOWorker
from did.worker.io.governor import DiscordWorkloadGovernor

APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
REDIS_URL = os.environ.get("DID_REDIS_URL", "redis://localhost:56379/0")

#: A synthetic owner id distinct from every other Stage09 test module's own
#: synthetic ids (all under 9.9e11) to avoid colliding with a
#: concurrently-run test suite against the same local database.
OWNER = 990920000001

CLEANUP_STATEMENTS = (
    "DELETE FROM discord_io_jobs WHERE guild_id = ANY(:guilds)",
    "DELETE FROM message_deliveries WHERE guild_id = ANY(:guilds)",
    "DELETE FROM message_campaign_targets WHERE guild_id = ANY(:guilds)",
    "DELETE FROM message_campaign_trigger_sources WHERE guild_id = ANY(:guilds)",
    "DELETE FROM message_campaign_trigger_consumptions WHERE guild_id = ANY(:guilds)",
    "DELETE FROM discord_gateway_inbox WHERE guild_id = ANY(:guilds)",
    "DELETE FROM message_campaign_triggers WHERE owner_discord_user_id = :owner",
    "DELETE FROM message_occurrences WHERE owner_discord_user_id = :owner",
    "DELETE FROM message_campaign_schedules WHERE owner_discord_user_id = :owner",
    "DELETE FROM message_approved_variants WHERE owner_discord_user_id = :owner",
    "DELETE FROM message_campaigns WHERE owner_discord_user_id = :owner",
    "DELETE FROM logical_group_resources WHERE guild_id = ANY(:guilds)",
    "DELETE FROM logical_groups WHERE guild_id = ANY(:guilds)",
    "DELETE FROM translation_channel_variants WHERE guild_id = ANY(:guilds)",
    "DELETE FROM translation_category_variants WHERE guild_id = ANY(:guilds)",
    "DELETE FROM translation_channel_groups WHERE guild_id = ANY(:guilds)",
    "DELETE FROM translation_group_languages WHERE guild_id = ANY(:guilds)",
    "DELETE FROM translation_groups WHERE guild_id = ANY(:guilds)",
    "DELETE FROM translation_provider_bindings WHERE guild_id = ANY(:guilds)",
    "DELETE FROM language_profiles WHERE guild_id = ANY(:guilds)",
    "DELETE FROM discord_member_authorization_cache WHERE guild_id = ANY(:guilds)",
    "DELETE FROM discord_channels_cache WHERE guild_id = ANY(:guilds)",
    "DELETE FROM discord_roles_cache WHERE guild_id = ANY(:guilds)",
    "DELETE FROM discord_cache_coverage WHERE guild_id = ANY(:guilds)",
    "DELETE FROM guild_installations WHERE guild_id = ANY(:guilds)",
    "DELETE FROM users WHERE discord_user_id = :owner",
)


async def _reset(admin_engine: Any, guild_a: int, guild_b: int) -> None:
    async with admin_engine.begin() as connection:
        for statement in CLEANUP_STATEMENTS:
            await connection.execute(
                text(statement), {"guilds": [guild_a, guild_b], "owner": OWNER}
            )


async def _seed_stage04_cache(
    connection: Any, guild_id: int, channel_ids: list[int], bot_user_id: int
) -> None:
    """Same seeding technique as test_stage09_api_postgres.py's own
    _seed_stage04_snapshot_for_guild_a, parametrized with the real sandbox
    Guild/channel/bot ids so the app's REAL CampaignGuildAuthorizationChecker
    (backed by the real PermissionEvaluator, never a fake) genuinely
    resolves bot_can_send=True for these real Discord resources."""
    now = datetime.now(UTC)
    await connection.execute(
        text(
            "INSERT INTO discord_roles_cache "
            "(guild_id,role_id,name,position,permissions_bits,managed,color,hoist,"
            "mentionable,raw_json,last_gateway_seen_at) VALUES "
            "(:guild,:everyone,'@everyone',0,3072,false,0,false,false,'{}',:now) "
            "ON CONFLICT (guild_id, role_id) DO UPDATE SET permissions_bits=3072"
        ),
        {"guild": guild_id, "everyone": guild_id, "now": now},
    )
    for channel_id in channel_ids:
        await connection.execute(
            text(
                "INSERT INTO discord_channels_cache "
                "(guild_id,channel_id,type,name,parent_id,position,nsfw,last_full_payload,"
                "observability_state,freshness_state,last_full_observed_at,"
                "last_gateway_seen_at) VALUES "
                "(:guild,:channel,0,'live-tmp',NULL,0,false,'{}','VISIBLE','FRESH',:now,:now) "
                "ON CONFLICT (guild_id, channel_id) DO UPDATE SET observability_state='VISIBLE'"
            ),
            {"guild": guild_id, "channel": channel_id, "now": now},
        )
    await connection.execute(
        text(
            "INSERT INTO discord_cache_coverage "
            "(guild_id,coverage_mode,freshness_state,known_channels,visible_channels,"
            "known_roles,last_gateway_event_at,gateway_continuity) VALUES "
            "(:guild,'FULL','FRESH',:known,:known,1,:now,'CONNECTED') "
            "ON CONFLICT (guild_id) DO UPDATE SET freshness_state='FRESH'"
        ),
        {"guild": guild_id, "known": len(channel_ids), "now": now},
    )
    await connection.execute(
        text(
            "INSERT INTO discord_member_authorization_cache "
            "(guild_id,discord_user_id,role_ids,source,validity,observed_at) VALUES "
            "(:guild,:bot,:roles,'TARGETED_REST','FRESH',:now) "
            "ON CONFLICT (guild_id, discord_user_id) DO UPDATE SET validity='FRESH'"
        ),
        {"guild": guild_id, "bot": bot_user_id, "roles": [], "now": now},
    )


class FakeOAuthClient:
    def __init__(self, guilds: tuple[DiscordGuild, ...]) -> None:
        self._guilds = guilds

    def authorization_url(self, *, state: str) -> str:
        return f"https://discord.com/oauth2/authorize?state={state}"

    async def exchange_code(self, code: str) -> OAuthTokenSet:
        del code
        return OAuthTokenSet(
            access_token=f"access-{OWNER}",
            refresh_token=f"refresh-{OWNER}",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=frozenset({"identify", "guilds"}),
        )

    async def refresh(self, refresh_token: str) -> OAuthTokenSet:  # pragma: no cover
        raise AssertionError(f"refresh should not be needed: {refresh_token}")

    async def revoke(self, token: str) -> None:  # pragma: no cover
        del token

    async def current_user(self, access_token: str) -> DiscordUser:
        del access_token
        return DiscordUser(OWNER, "stage09-full-chain-live", None, None)

    async def current_user_guilds(self, access_token: str) -> tuple[DiscordGuild, ...]:
        del access_token
        return self._guilds


class FakeMemberClient:
    async def get_member_roles(self, guild_id: int, user_id: int) -> tuple[int, ...]:
        del guild_id, user_id
        return ()


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        database_url=SecretStr(APP_URL),
        database_admin_url=SecretStr(ADMIN_URL),
        redis_url=SecretStr(REDIS_URL),
        discord_client_id="123",
        discord_client_secret=SecretStr("test-only-client-value"),
        discord_oauth_redirect_uri="http://test/auth/discord/callback",
        session_secret=SecretStr("stage09-full-chain-live-session-secret-material"),
        oauth_token_encryption_key=SecretStr("a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s"),
        oauth_state_ttl_seconds=60,
        guild_discovery_ttl_seconds=60,
    )


async def _login(client: AsyncClient) -> str:
    start = await client.get("/auth/discord/login")
    assert start.status_code == 302
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    callback = await client.get(
        "/auth/discord/callback", params={"code": "live-owner", "state": state}
    )
    assert callback.status_code == 303
    me = await client.get("/api/v1/me")
    assert me.status_code == 200
    return str(me.json()["csrf_token"])


class _AlwaysAuthorizedChecker:
    """Mirrors test_stage09_runtime_chain_postgres.py's own documented
    rationale: Group "immediate_channel" already proves real authorization
    end to end through the real HTTP layer (the real
    CampaignGuildAuthorizationChecker, backed by the Stage04 cache this
    script genuinely seeds for the real sandbox Guild). The
    scheduler/event-triggered groups below isolate the ONE thing nothing
    else in this script proves: the scheduler/event composition itself."""

    async def is_guild_authorized(self, *, guild_id: int, owner_discord_user_id: int) -> bool:
        del guild_id, owner_discord_user_id
        return True

    async def bot_can_send(self, *, guild_id: int, discord_channel_id: int) -> bool:
        del guild_id, discord_channel_id
        return True

    async def logical_group_belongs_to_guild(self, *, guild_id: int, logical_group_id: Any) -> bool:
        del guild_id, logical_group_id
        return True

    async def translation_group_belongs_to_guild(
        self, *, guild_id: int, translation_group_id: Any
    ) -> bool:
        del guild_id, translation_group_id
        return True


class _Context:
    def __init__(
        self,
        *,
        client_http: AsyncClient,
        csrf: str,
        discord_client: discord.Client,
        guild_a: discord.Guild,
        guild_b: discord.Guild,
        bot_user_id: int,
        admin_engine: Any,
        campaigns_repo: CampaignsRepository,
        runtime_repo: RuntimeRepository,
        admin_factory: async_sessionmaker[Any],
        worker: DurableDiscordIOWorker,
        governor: DiscordWorkloadGovernor,
        runtime: CampaignSchedulerRuntime,
        translation_runtime: CampaignSchedulerRuntime,
        language_profiles: LanguageProfileRepository,
        translation_groups: TranslationGroupRepository,
        provider_bindings: TranslationProviderBindingRepository,
    ) -> None:
        self.client_http = client_http
        self.csrf = csrf
        self.discord_client = discord_client
        self.guild_a = guild_a
        self.guild_b = guild_b
        self.bot_user_id = bot_user_id
        self.admin_engine = admin_engine
        self.campaigns_repo = campaigns_repo
        self.runtime_repo = runtime_repo
        self.admin_factory = admin_factory
        self.worker = worker
        self.governor = governor
        self.runtime = runtime
        #: Same real production entrypoint as `runtime`, but with the REAL
        #: did.translation.googletrans_adapter.GoogletransCampaignTranslationProvider
        #: wired -- exactly mirroring did.runtime.py's own construction --
        #: instead of `translation_provider=None`. Kept as a second instance
        #: so ordinary (non-translation) scenario groups never accidentally
        #: make a live translation call.
        self.translation_runtime = translation_runtime
        self.language_profiles = language_profiles
        self.translation_groups = translation_groups
        self.provider_bindings = provider_bindings
        self.temp_channels: list[discord.TextChannel] = []
        #: Non-blocking observations about real-world conditions outside
        #: DID's own code (e.g. whether the live googletrans dependency is
        #: currently producing genuinely different text) -- recorded in the
        #: durable evidence report's own "notes" field, never silently
        #: dropped, but never a PASS/FAIL gate the way `results` is.
        self.observations: list[str] = []


async def _run_worker_once(ctx: _Context, guild_id: int) -> bool:
    """Drives exactly one durable discord_io_jobs row for guild_id through
    the REAL DurableDiscordIOWorker.dispatch_guild_once, wired to the REAL
    DiscordWorkloadGovernor and the REAL DiscordPyMessageSender -- the one
    link the existing 5-scenario adapter-only script never exercises.

    Mirrors did.worker.io.runtime.DiscordWorkerRuntime._dispatch_fair_batch's
    real production pattern exactly: dispatch_guild_once() only ENQUEUES the
    leased job into the Governor's own internal queue and returns a Future
    that resolves only once the Governor's own drain() loop actually
    executes it -- drain() must be driven concurrently, or the future (and
    this call) hangs forever. Never call this concurrently against the same
    governor for multiple Guilds (drain() is not reentrant against shared
    state) -- use _dispatch_and_drain_many for that."""
    future = await ctx.worker.dispatch_guild_once(guild_id, ctx.governor)
    if future is None:
        return False
    drain_task = asyncio.create_task(ctx.governor.drain())
    try:
        await future
    finally:
        await drain_task
    return True


async def _dispatch_and_drain_many(ctx: _Context, guild_ids: list[int]) -> dict[int, bool]:
    """Dispatches one durable job per Guild in ``guild_ids`` against the
    SAME shared real DiscordWorkloadGovernor, then drains ONCE for all of
    them together -- the real per-Guild fairness/concurrency dimension
    (did.worker.io.runtime.DiscordWorkerRuntime._dispatch_fair_batch's own
    dispatch-then-one-shared-drain pattern), never N independent drain()
    calls racing the same governor instance."""
    futures: dict[int, asyncio.Future[Any]] = {}
    for guild_id in guild_ids:
        future = await ctx.worker.dispatch_guild_once(guild_id, ctx.governor)
        if future is not None:
            futures[guild_id] = future
    if not futures:
        return dict.fromkeys(guild_ids, False)
    drain_task = asyncio.create_task(ctx.governor.drain())
    try:
        await asyncio.gather(*futures.values(), return_exceptions=True)
    finally:
        await drain_task
    return {
        guild_id: guild_id in futures and not futures[guild_id].exception()
        for guild_id in guild_ids
    }


async def _get_delivery_for_channel(
    ctx: _Context, campaign_id: str, channel_id: int
) -> dict[str, Any] | None:
    listed = await ctx.client_http.get(f"/api/v1/campaigns/{campaign_id}/deliveries")
    for delivery in listed.json()["deliveries"]:
        if int(delivery["discord_channel_id"]) == channel_id:
            return dict(delivery)
    return None


async def _get_deliveries(ctx: _Context, campaign_id: str) -> list[dict[str, Any]]:
    listed = await ctx.client_http.get(f"/api/v1/campaigns/{campaign_id}/deliveries")
    return list(listed.json()["deliveries"])


async def _drain_all(ctx: _Context, guild_id: int, *, max_jobs: int = 10) -> int:
    """Repeatedly drives _run_worker_once until no durable job remains for
    guild_id (or max_jobs is hit) -- a single DID_TRANSLATED_FANOUT target
    enqueues one durable discord_io_jobs row per destination (source plus
    each translated language), so a multi-destination fan-out needs more
    than one dispatch_guild_once/governor.drain() cycle to fully drain."""
    count = 0
    while count < max_jobs and await _run_worker_once(ctx, guild_id):
        count += 1
    return count


async def _seed_channel(ctx: _Context, guild: discord.Guild, channel: discord.TextChannel) -> None:
    async with ctx.admin_engine.begin() as connection:
        await _seed_stage04_cache(connection, guild.id, [channel.id], ctx.bot_user_id)


async def _send_immediate(
    ctx: _Context, guild: discord.Guild, name: str, message_model: dict[str, Any]
) -> tuple[str, discord.TextChannel, dict[str, Any]]:
    """The Group "immediate_channel" backbone, reused by every other group
    that just needs one real SENT delivery to build on: real HTTP campaign
    create -> real HTTP target create (real Stage04 authorization) -> real
    HTTP activate (synchronously fans out + routes to a durable job for
    IMMEDIATE campaigns) -> the real worker/governor/adapter chain."""
    channel = await guild.create_text_channel(f"did-s09-fc-{uuid4().hex[:8]}")
    ctx.temp_channels.append(channel)
    await _seed_channel(ctx, guild, channel)

    created = await ctx.client_http.post(
        "/api/v1/campaigns",
        json={
            "name": name,
            "source_language_code": "en",
            "message_model": message_model,
            "allowed_mentions_policy": {},
            "publication_mode": "IMMEDIATE",
        },
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-campaign-{uuid4()}"},
    )
    if created.status_code != 201:
        raise RuntimeError(f"campaign create failed: {created.status_code} {created.text}")
    campaign_id = created.json()["campaign"]["id"]

    targeted = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/targets",
        json={
            "guild_id": str(guild.id),
            "target_kind": "CHANNEL",
            "discord_channel_id": str(channel.id),
        },
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-target-{uuid4()}"},
    )
    if targeted.status_code != 201:
        raise RuntimeError(f"target create failed: {targeted.status_code} {targeted.text}")

    activated = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/activate",
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-activate-{uuid4()}"},
    )
    if activated.status_code != 200:
        raise RuntimeError(f"activate failed: {activated.status_code} {activated.text}")

    await _run_worker_once(ctx, guild.id)
    delivery = await _get_delivery_for_channel(ctx, campaign_id, channel.id)
    return campaign_id, channel, delivery or {}


# ---------------------------------------------------------------------------
# Scenario groups
# ---------------------------------------------------------------------------


async def _group_immediate_channel(ctx: _Context, results: dict[str, bool]) -> None:
    content = "Full chain immediate (synthetic, live qualification)."
    _campaign_id, channel, delivery = await _send_immediate(
        ctx, ctx.guild_a, "Full chain immediate", {"content": content}
    )
    results["immediate_channel.delivery_reconciled_sent"] = delivery.get("status") == "SENT"
    matched = False
    if delivery.get("discord_message_id"):
        fetched = await channel.fetch_message(int(delivery["discord_message_id"]))
        matched = fetched.content == content
    results["immediate_channel.discord_content_matches"] = matched


async def _group_one_shot_deferred(ctx: _Context, results: dict[str, bool]) -> None:
    content = "Full chain one-shot deferred (synthetic, live qualification)."
    channel = await ctx.guild_a.create_text_channel(f"did-s09-fc-{uuid4().hex[:8]}")
    ctx.temp_channels.append(channel)
    await _seed_channel(ctx, ctx.guild_a, channel)

    created = await ctx.client_http.post(
        "/api/v1/campaigns",
        json={
            "name": "Full chain one-shot",
            "source_language_code": "en",
            "message_model": {"content": content},
            "allowed_mentions_policy": {},
            "publication_mode": "ONE_SHOT_DEFERRED",
        },
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-osd-campaign-{uuid4()}"},
    )
    results["one_shot_deferred.campaign_created"] = created.status_code == 201
    campaign_id = created.json()["campaign"]["id"]

    targeted = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/targets",
        json={
            "guild_id": str(ctx.guild_a.id),
            "target_kind": "CHANNEL",
            "discord_channel_id": str(channel.id),
        },
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-osd-target-{uuid4()}"},
    )
    results["one_shot_deferred.target_created"] = targeted.status_code == 201

    fire_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    scheduled = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/schedule",
        json={"schedule_kind": "ONE_SHOT", "fire_at": fire_at},
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-osd-schedule-{uuid4()}"},
    )
    results["one_shot_deferred.schedule_created"] = scheduled.status_code == 201

    activated = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/activate",
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-osd-activate-{uuid4()}"},
    )
    results["one_shot_deferred.activated_scheduled_armed"] = (
        activated.status_code == 200
        and activated.json()["campaign"]["lifecycle_status"] == "SCHEDULED_ARMED"
    )

    routed = await ctx.runtime.tick(datetime.now(UTC))
    results["one_shot_deferred.scheduler_tick_routed_delivery"] = routed >= 1
    await _run_worker_once(ctx, ctx.guild_a.id)
    delivery = await _get_delivery_for_channel(ctx, campaign_id, channel.id)
    results["one_shot_deferred.delivery_sent"] = (
        delivery is not None and delivery["status"] == "SENT"
    )

    routed_again = await ctx.runtime.tick(datetime.now(UTC))
    results["one_shot_deferred.second_tick_is_noop"] = routed_again == 0


async def _group_recurring(ctx: _Context, results: dict[str, bool]) -> None:
    content = "Full chain recurring (synthetic, live qualification)."
    channel = await ctx.guild_a.create_text_channel(f"did-s09-fc-{uuid4().hex[:8]}")
    ctx.temp_channels.append(channel)
    await _seed_channel(ctx, ctx.guild_a, channel)

    created = await ctx.client_http.post(
        "/api/v1/campaigns",
        json={
            "name": "Full chain recurring",
            "source_language_code": "en",
            "message_model": {"content": content},
            "allowed_mentions_policy": {},
            "publication_mode": "RECURRING",
        },
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-rec-campaign-{uuid4()}"},
    )
    results["recurring.campaign_created"] = created.status_code == 201
    campaign_id = created.json()["campaign"]["id"]

    await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/targets",
        json={
            "guild_id": str(ctx.guild_a.id),
            "target_kind": "CHANNEL",
            "discord_channel_id": str(channel.id),
        },
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-rec-target-{uuid4()}"},
    )

    # starts_at is an EXCLUSIVE cursor (did.campaigns.scheduling's own
    # contract): with a daily RRULE the first candidate occurrence is
    # starts_at + 1 day. 30 hours in the past puts that candidate 6 hours
    # ago (due) while the next one is 18 hours in the future (not due) --
    # guaranteed exactly one due occurrence, never two, independent of DST
    # edge cases (no fixed calendar date is used).
    starts_at = (datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=30)).isoformat()
    scheduled = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/schedule",
        json={
            "schedule_kind": "RECURRING",
            "rrule": "FREQ=DAILY",
            "starts_at": starts_at,
            "timezone": "UTC",
            "catch_up_bound": 5,
        },
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-rec-schedule-{uuid4()}"},
    )
    results["recurring.schedule_created"] = scheduled.status_code == 201

    activated = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/activate",
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-rec-activate-{uuid4()}"},
    )
    results["recurring.activated_scheduled_armed"] = (
        activated.status_code == 200
        and activated.json()["campaign"]["lifecycle_status"] == "SCHEDULED_ARMED"
    )

    routed = await ctx.runtime.tick(datetime.now(UTC))
    results["recurring.scheduler_tick_routed_delivery"] = routed >= 1
    await _run_worker_once(ctx, ctx.guild_a.id)
    delivery = await _get_delivery_for_channel(ctx, campaign_id, channel.id)
    results["recurring.delivery_sent"] = delivery is not None and delivery["status"] == "SENT"

    # There is no GET .../schedule endpoint -- read the durable row directly
    # to prove the real scheduler advanced next_fire_at past its own
    # exclusive starts_at cursor (did.campaigns.scheduling's own contract).
    async with ctx.admin_engine.begin() as connection:
        next_fire_at = await connection.scalar(
            text("SELECT next_fire_at FROM message_campaign_schedules WHERE campaign_id=:cid"),
            {"cid": campaign_id},
        )
    results["recurring.next_fire_at_advanced_past_starts_at"] = (
        next_fire_at is not None and next_fire_at.isoformat() > starts_at
    )


async def _group_event_triggered(ctx: _Context, results: dict[str, bool]) -> None:
    """A non-MESSAGE_CREATE event_type deliberately sidesteps
    did.campaigns.event_transport's own-bot-message correlation grace
    period (REQ-MSG-030 producing side) -- irrelevant to what this group
    proves (the trigger/event composition), and would otherwise force this
    script to wait out that grace window for no reason."""
    content = "Full chain event-triggered (synthetic, live qualification)."
    event_type = "GUILD_MEMBER_ADD"
    channel = await ctx.guild_a.create_text_channel(f"did-s09-fc-{uuid4().hex[:8]}")
    ctx.temp_channels.append(channel)
    await _seed_channel(ctx, ctx.guild_a, channel)

    created = await ctx.client_http.post(
        "/api/v1/campaigns",
        json={
            "name": "Full chain event-triggered",
            "source_language_code": "en",
            "message_model": {"content": content},
            "allowed_mentions_policy": {},
            "publication_mode": "EVENT_TRIGGERED",
        },
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-evt-campaign-{uuid4()}"},
    )
    results["event_triggered.campaign_created"] = created.status_code == 201
    campaign_id = created.json()["campaign"]["id"]

    await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/targets",
        json={
            "guild_id": str(ctx.guild_a.id),
            "target_kind": "CHANNEL",
            "discord_channel_id": str(channel.id),
        },
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-evt-target-{uuid4()}"},
    )

    trigger_created = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/triggers",
        json={"event_type": event_type, "condition_ast": {"op": "ALWAYS"}},
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-evt-trigger-{uuid4()}"},
    )
    results["event_triggered.trigger_created"] = trigger_created.status_code == 201
    trigger_id = trigger_created.json()["id"]

    source_created = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/triggers/{trigger_id}/sources",
        json={"guild_id": str(ctx.guild_a.id), "source_scope_kind": "GUILD"},
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-evt-source-{uuid4()}"},
    )
    results["event_triggered.trigger_source_bound"] = source_created.status_code == 201

    activated = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/activate",
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-evt-activate-{uuid4()}"},
    )
    results["event_triggered.activated_running"] = (
        activated.status_code == 200
        and activated.json()["campaign"]["lifecycle_status"] == "ACTIVE_RUNNING"
    )

    event_id = uuid4()
    async with ctx.admin_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO discord_gateway_inbox "
                "(event_id,guild_id,event_type,discord_session_id,received_at,correlation_id,"
                "schema_version,source,origin,causation_depth,payload) VALUES "
                "(:event_id,:guild,:event_type,'stage09-full-chain-live',:received_at,:event_id,1,"
                "'GATEWAY','DISCORD_EXTERNAL',0,CAST(:payload AS JSONB))"
            ),
            {
                "event_id": event_id,
                "guild": ctx.guild_a.id,
                "event_type": event_type,
                "received_at": datetime.now(UTC),
                "payload": json.dumps({}),
            },
        )

    routed = await ctx.runtime.tick(datetime.now(UTC))
    results["event_triggered.scheduler_tick_consumed_event_and_routed"] = routed >= 1
    await _run_worker_once(ctx, ctx.guild_a.id)
    delivery = await _get_delivery_for_channel(ctx, campaign_id, channel.id)
    results["event_triggered.delivery_sent"] = delivery is not None and delivery["status"] == "SENT"


async def _group_logical_group(ctx: _Context, results: dict[str, bool]) -> None:
    content = "Full chain logical group (synthetic, live qualification)."
    channel_1 = await ctx.guild_a.create_text_channel(f"did-s09-fc-{uuid4().hex[:8]}")
    channel_2 = await ctx.guild_a.create_text_channel(f"did-s09-fc-{uuid4().hex[:8]}")
    ctx.temp_channels.extend([channel_1, channel_2])
    async with ctx.admin_engine.begin() as connection:
        await _seed_stage04_cache(
            connection, ctx.guild_a.id, [channel_1.id, channel_2.id], ctx.bot_user_id
        )

    stage04 = Stage04Repository(ctx.admin_factory)
    group_id = await stage04.create_logical_group(
        guild_id=ctx.guild_a.id,
        actor_id=OWNER,
        name="Full chain live group",
        slug=f"full-chain-live-{uuid4().hex[:8]}",
        description=None,
        metadata={},
        resources=(
            {"resource_type": "CHANNEL", "discord_resource_id": channel_1.id},
            {"resource_type": "CHANNEL", "discord_resource_id": channel_2.id},
        ),
    )

    created = await ctx.client_http.post(
        "/api/v1/campaigns",
        json={
            "name": "Full chain logical group",
            "source_language_code": "en",
            "message_model": {"content": content},
            "allowed_mentions_policy": {},
            "publication_mode": "IMMEDIATE",
        },
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-lg-campaign-{uuid4()}"},
    )
    results["logical_group.campaign_created"] = created.status_code == 201
    campaign_id = created.json()["campaign"]["id"]

    targeted = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/targets",
        json={
            "guild_id": str(ctx.guild_a.id),
            "target_kind": "LOGICAL_GROUP",
            "logical_group_id": str(group_id),
        },
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-lg-target-{uuid4()}"},
    )
    results["logical_group.target_created"] = targeted.status_code == 201

    activated = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/activate",
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-lg-activate-{uuid4()}"},
    )
    results["logical_group.activation_routed_both_deliveries"] = (
        activated.status_code == 200 and activated.json()["durable_work"]["deliveries_routed"] == 2
    )

    await _run_worker_once(ctx, ctx.guild_a.id)
    await _run_worker_once(ctx, ctx.guild_a.id)
    delivery_1 = await _get_delivery_for_channel(ctx, campaign_id, channel_1.id)
    delivery_2 = await _get_delivery_for_channel(ctx, campaign_id, channel_2.id)
    results["logical_group.both_channels_reconciled_sent"] = (
        delivery_1 is not None
        and delivery_1["status"] == "SENT"
        and delivery_2 is not None
        and delivery_2["status"] == "SENT"
    )
    matched_1 = matched_2 = False
    if delivery_1 and delivery_1.get("discord_message_id"):
        fetched_1 = await channel_1.fetch_message(int(delivery_1["discord_message_id"]))
        matched_1 = fetched_1.content == content
    if delivery_2 and delivery_2.get("discord_message_id"):
        fetched_2 = await channel_2.fetch_message(int(delivery_2["discord_message_id"]))
        matched_2 = fetched_2.content == content
    results["logical_group.both_channels_content_matches"] = matched_1 and matched_2


async def _group_owned_edit_delete(ctx: _Context, results: dict[str, bool]) -> None:
    original = "Full chain owned edit source (synthetic, live qualification)."
    edited = "Full chain owned edit RESULT (synthetic, live qualification)."
    campaign_id, channel, delivery = await _send_immediate(
        ctx, ctx.guild_a, "Full chain owned edit/delete", {"content": original}
    )
    results["owned_edit_delete.initial_send"] = delivery.get("status") == "SENT"
    delivery_id = delivery.get("id")
    if not delivery_id:
        results["owned_edit_delete.durable_edit_job_applied"] = False
        results["owned_edit_delete.durable_delete_job_applied"] = False
        return

    edit_requested = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/edit",
        json={"message_model": {"content": edited, "embeds": [], "action_rows": []}},
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-edit-{uuid4()}"},
    )
    results["owned_edit_delete.edit_enqueued"] = edit_requested.status_code == 200
    await _run_worker_once(ctx, ctx.guild_a.id)
    fetched_after_edit = await channel.fetch_message(int(delivery["discord_message_id"]))
    results["owned_edit_delete.durable_edit_job_applied"] = fetched_after_edit.content == edited

    delete_requested = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/deliveries/{delivery_id}/delete",
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-delete-{uuid4()}"},
    )
    results["owned_edit_delete.delete_enqueued"] = delete_requested.status_code == 200
    await _run_worker_once(ctx, ctx.guild_a.id)
    deleted_ok = False
    try:
        await channel.fetch_message(int(delivery["discord_message_id"]))
    except discord.NotFound:
        deleted_ok = True
    results["owned_edit_delete.durable_delete_job_applied"] = deleted_ok
    listed = await ctx.client_http.get(f"/api/v1/campaigns/{campaign_id}/deliveries")
    final_status = next(
        (d["status"] for d in listed.json()["deliveries"] if d["id"] == delivery_id), None
    )
    results["owned_edit_delete.delivery_marked_deleted"] = final_status == "DELETED"


async def _group_embed_button(ctx: _Context, results: dict[str, bool]) -> None:
    message_model = {
        "content": "Full chain embed/button (synthetic, live qualification).",
        "embeds": [
            {
                "title": "Live qualification embed",
                "description": "Full chain description",
                "url": None,
                "color": 0x00FF00,
                "footer_text": "footer",
                "author_name": "author",
                "fields": [{"name": "Field", "value": "Value", "inline": False}],
            }
        ],
        "action_rows": [
            {"buttons": [{"label": "Confirm", "style": "PRIMARY", "custom_id": "fc-confirm"}]}
        ],
    }
    campaign_id, channel, delivery = await _send_immediate(
        ctx, ctx.guild_a, "Full chain embed/button", message_model
    )
    del campaign_id
    results["embed_button.delivery_sent"] = delivery.get("status") == "SENT"
    embed_ok = False
    button_ok = False
    if delivery.get("discord_message_id"):
        fetched = await channel.fetch_message(int(delivery["discord_message_id"]))
        embed_ok = bool(fetched.embeds) and fetched.embeds[0].title == "Live qualification embed"
        children = getattr(fetched.components[0], "children", []) if fetched.components else []
        first_child = children[0] if children else None
        button_ok = getattr(first_child, "label", None) == "Confirm"
    results["embed_button.discord_embed_rendered"] = embed_ok
    results["embed_button.discord_button_rendered"] = button_ok


async def _group_governor_fairness(ctx: _Context, results: dict[str, bool]) -> None:
    content = "Full chain governor fairness (synthetic, live qualification)."
    channel_a = await ctx.guild_a.create_text_channel(f"did-s09-fc-{uuid4().hex[:8]}")
    channel_b = await ctx.guild_b.create_text_channel(f"did-s09-fc-{uuid4().hex[:8]}")
    ctx.temp_channels.extend([channel_a, channel_b])
    await _seed_channel(ctx, ctx.guild_a, channel_a)
    await _seed_channel(ctx, ctx.guild_b, channel_b)

    async def _create_and_activate(guild: discord.Guild, channel: discord.TextChannel) -> str:
        created = await ctx.client_http.post(
            "/api/v1/campaigns",
            json={
                "name": "Full chain governor fairness",
                "source_language_code": "en",
                "message_model": {"content": content},
                "allowed_mentions_policy": {},
                "publication_mode": "IMMEDIATE",
            },
            headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-gov-campaign-{uuid4()}"},
        )
        campaign_id = created.json()["campaign"]["id"]
        await ctx.client_http.post(
            f"/api/v1/campaigns/{campaign_id}/targets",
            json={
                "guild_id": str(guild.id),
                "target_kind": "CHANNEL",
                "discord_channel_id": str(channel.id),
            },
            headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-gov-target-{uuid4()}"},
        )
        await ctx.client_http.post(
            f"/api/v1/campaigns/{campaign_id}/activate",
            headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-gov-activate-{uuid4()}"},
        )
        return str(campaign_id)

    campaign_a = await _create_and_activate(ctx.guild_a, channel_a)
    campaign_b = await _create_and_activate(ctx.guild_b, channel_b)

    # ONE shared real DiscordWorkloadGovernor dispatching both real Guilds'
    # durable jobs, drained together -- the per-guild fairness/concurrency
    # dimension the existing 5-scenario adapter-only script never touches.
    progressed = await _dispatch_and_drain_many(ctx, [ctx.guild_a.id, ctx.guild_b.id])
    results["governor_fairness.both_guilds_progressed"] = all(progressed.values())

    delivery_a = await _get_delivery_for_channel(ctx, campaign_a, channel_a.id)
    delivery_b = await _get_delivery_for_channel(ctx, campaign_b, channel_b.id)
    results["governor_fairness.both_guilds_delivered_via_shared_governor"] = (
        delivery_a is not None
        and delivery_a["status"] == "SENT"
        and delivery_b is not None
        and delivery_b["status"] == "SENT"
    )


async def _group_retention_leaves_discord_untouched(
    ctx: _Context, results: dict[str, bool]
) -> None:
    content = "Full chain retention (synthetic, live qualification)."
    campaign_id, channel, delivery = await _send_immediate(
        ctx, ctx.guild_a, "Full chain retention", {"content": content}
    )
    del campaign_id
    results["retention.initial_send"] = delivery.get("status") == "SENT"
    delivery_id = delivery.get("id")
    if not delivery_id:
        results["retention.purge_removed_durable_row"] = False
        results["retention.discord_message_survives_purge"] = False
        return

    backdated = datetime.now(UTC) - timedelta(days=91)
    async with ctx.admin_engine.begin() as connection:
        await connection.execute(
            text("UPDATE message_deliveries SET updated_at=:updated_at WHERE id=:id"),
            {"updated_at": backdated, "id": delivery_id},
        )

    purged = await purge_expired_deliveries(
        ctx.campaigns_repo,
        RetentionPolicy(retention_days=90),
        guild_id=ctx.guild_a.id,
        now=datetime.now(UTC),
    )
    results["retention.purge_removed_durable_row"] = purged == 1
    status_after_purge = await ctx.campaigns_repo.get_delivery_status(ctx.guild_a.id, delivery_id)
    results["retention.durable_row_gone"] = status_after_purge is None

    # The whole point of this group: retention purges only the durable
    # HISTORY row, it must never reach out to Discord itself.
    still_there = True
    try:
        fetched = await channel.fetch_message(int(delivery["discord_message_id"]))
        still_there = fetched.content == content
    except discord.NotFound:
        still_there = False
    results["retention.discord_message_survives_purge"] = still_there


# ---------------------------------------------------------------------------
# Translation Group live scenarios -- REQ-MSG-007/013. Wired against the
# REAL did.translation.googletrans_adapter.GoogletransCampaignTranslationProvider
# (never a fake), exactly as did.runtime.py itself constructs it, via
# ctx.translation_runtime (a second CampaignSchedulerRuntime instance kept
# separate so ordinary non-translation scenario groups never accidentally
# make a live translation call). IMMEDIATE+HTTP activation never wires a
# live provider (did.api.stage09.activate_campaign hardcodes
# translation_provider=None for its synchronous IMMEDIATE fan-out) --
# ONE_SHOT_DEFERRED + the real CampaignSchedulerRuntime.tick() is the only
# real product-chain entrypoint that can exercise live translation, so
# every scenario below uses that publication mode, mirroring
# _group_one_shot_deferred's own pattern.
# ---------------------------------------------------------------------------


async def _setup_language_profiles(ctx: _Context, guild: discord.Guild) -> dict[str, Any]:
    """Four real Stage08 language profiles (en/fr/de/es) for guild, reused
    across every Translation Group scenario below -- the real
    LanguageProfileRepository, never a raw ad-hoc INSERT. Profiles
    themselves carry no channel-exclusivity constraint (unlike
    translation_channel_variants, see _setup_translation_group), so
    creating them once and reusing the ids across many groups is safe.

    Idempotent per Guild: language_profiles carries a real UNIQUE(guild_id,
    code) constraint, and more than one scenario group in the same run
    calls this for the same real sandbox Guild -- reuses an
    already-created profile's id for a code instead of colliding on a
    fresh INSERT."""
    display_names = {"en": "English", "fr": "Francais", "de": "Deutsch", "es": "Espanol"}
    existing = {
        str(row["code"]): row["id"] for row in await ctx.language_profiles.list_profiles(guild.id)
    }
    profile_ids: dict[str, Any] = {}
    for code, display_name in display_names.items():
        if code in existing:
            profile_ids[code] = existing[code]
            continue
        created = await ctx.language_profiles.create(
            guild_id=guild.id, code=code, display_name=display_name
        )
        profile_ids[code] = created["id"]
    return profile_ids


async def _setup_translation_group(
    ctx: _Context,
    guild: discord.Guild,
    *,
    source_code: str,
    profile_ids: dict[str, Any],
    variant_codes: tuple[str, ...],
    provider_binding_id: Any = None,
) -> tuple[Any, dict[str, discord.TextChannel]]:
    """One real Stage08 Translation Group (one channel group, one channel
    variant per code in variant_codes plus the source itself) through the
    REAL TranslationGroupRepository -- the same repository did.api.stage08
    itself uses, never a raw ad-hoc INSERT. create_with_languages (not the
    bare create) is required: translation_channel_groups has a real FK to
    translation_group_languages, so every language profile a channel group
    or variant will reference -- source included -- must already be an
    enabled member of the group before either is created.

    Creates its own FRESH real Discord channels every call, never reusing
    ones from an earlier group: translation_channel_variants carries a
    real UNIQUE(guild_id, discord_channel_id) constraint, so a physical
    channel can only ever be one Translation Group's variant at a time,
    system-wide -- a real, deliberate product constraint this validator
    must respect, not merely a test-scaffolding convenience."""
    codes = (source_code, *variant_codes)
    channels: dict[str, discord.TextChannel] = {}
    for code in codes:
        channel = await guild.create_text_channel(f"did-s09-fc-tr-{code}-{uuid4().hex[:6]}")
        ctx.temp_channels.append(channel)
        channels[code] = channel
    async with ctx.admin_engine.begin() as connection:
        await _seed_stage04_cache(
            connection, guild.id, [channel.id for channel in channels.values()], ctx.bot_user_id
        )
    group = await ctx.translation_groups.create_with_languages(
        guild_id=guild.id,
        name=f"Full chain live {source_code}-{uuid4().hex[:6]}",
        root_kind="CHANNEL_SET",
        routing_mode="HUB_AND_SPOKE",
        language_profile_ids=tuple(profile_ids[code] for code in codes),
        source_language_profile_id=profile_ids[source_code],
        provider_binding_id=provider_binding_id,
    )
    group_id = group["id"]
    channel_group = await ctx.translation_groups.create_channel_group(
        guild_id=guild.id,
        translation_group_id=group_id,
        logical_key="main",
        source_language_profile_id=profile_ids[source_code],
    )
    for code in codes:
        await ctx.translation_groups.create_channel_variant(
            guild_id=guild.id,
            translation_group_id=group_id,
            translation_channel_group_id=channel_group["id"],
            language_profile_id=profile_ids[code],
            discord_channel_id=channels[code].id,
        )
    return group_id, channels


async def _activate_translation_group_campaign(
    ctx: _Context,
    guild: discord.Guild,
    *,
    name: str,
    source_language_code: str,
    content: str,
    group_id: Any,
    mode: str,
    selected_language_profile_ids: list[str] | None = None,
) -> str:
    """The real HTTP campaign/target/schedule/activate sequence, targeting
    a Translation Group instead of a plain CHANNEL -- ONE_SHOT_DEFERRED so
    the real CampaignSchedulerRuntime.tick() (with the real translation
    provider wired) does the actual fan-out, never IMMEDIATE (which never
    wires a live provider)."""
    created = await ctx.client_http.post(
        "/api/v1/campaigns",
        json={
            "name": name,
            "source_language_code": source_language_code,
            "message_model": {"content": content},
            "allowed_mentions_policy": {},
            "publication_mode": "ONE_SHOT_DEFERRED",
        },
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-tr-campaign-{uuid4()}"},
    )
    if created.status_code != 201:
        raise RuntimeError(f"campaign create failed: {created.status_code} {created.text}")
    campaign_id = created.json()["campaign"]["id"]

    target_body: dict[str, Any] = {
        "guild_id": str(guild.id),
        "target_kind": "TRANSLATION_GROUP",
        "translation_group_id": str(group_id),
        "translation_publication_mode": mode,
    }
    if selected_language_profile_ids is not None:
        target_body["selected_language_profile_ids"] = selected_language_profile_ids
    targeted = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/targets",
        json=target_body,
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-tr-target-{uuid4()}"},
    )
    if targeted.status_code != 201:
        raise RuntimeError(f"target create failed: {targeted.status_code} {targeted.text}")

    fire_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    scheduled = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/schedule",
        json={"schedule_kind": "ONE_SHOT", "fire_at": fire_at},
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-tr-schedule-{uuid4()}"},
    )
    if scheduled.status_code != 201:
        raise RuntimeError(f"schedule create failed: {scheduled.status_code} {scheduled.text}")

    activated = await ctx.client_http.post(
        f"/api/v1/campaigns/{campaign_id}/activate",
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-tr-activate-{uuid4()}"},
    )
    if activated.status_code != 200:
        raise RuntimeError(f"activate failed: {activated.status_code} {activated.text}")
    return str(campaign_id)


async def _group_translation_group_did_fanout(ctx: _Context, results: dict[str, bool]) -> None:
    guild = ctx.guild_a
    profile_ids = await _setup_language_profiles(ctx, guild)
    codes = ("en", "fr", "de", "es")
    # Deliberately linguistic prose, natively phrased per source language --
    # not proper nouns/acronyms/technical-only strings -- so that a
    # translated destination coming back identical to this source text is
    # objectively not an acceptable outcome (mission: "the actual
    # destination message must demonstrate that real translation occurred").
    contents = {
        "en": "The winter update brings many new challenges for everyone to enjoy.",
        "fr": "La mise a jour d'hiver apporte de nombreux nouveaux defis pour tout le monde.",
        "de": "Das Winterupdate bringt viele neue Herausforderungen, die jeder genieszen kann.",
        "es": "La actualizacion de invierno trae muchos desafios nuevos para que todos disfruten.",
    }

    # --- SOURCE_ONLY: DID never publishes a DID-translated destination in
    # this mode -- only the source channel is ever touched. ---
    source_only_group, source_only_channels = await _setup_translation_group(
        ctx,
        guild,
        source_code="en",
        profile_ids=profile_ids,
        variant_codes=("fr", "de", "es"),
    )
    source_only_campaign = await _activate_translation_group_campaign(
        ctx,
        guild,
        name="Full chain translation SOURCE_ONLY",
        source_language_code="en",
        content=contents["en"],
        group_id=source_only_group,
        mode="SOURCE_ONLY",
    )
    await ctx.translation_runtime.tick(datetime.now(UTC))
    await _drain_all(ctx, guild.id)
    deliveries = await _get_deliveries(ctx, source_only_campaign)
    results["translation_group.source_only_publishes_only_source"] = (
        len(deliveries) == 1
        and deliveries[0]["status"] == "SENT"
        and deliveries[0]["language_profile_id"] is None
    )
    del source_only_channels

    # --- One real DID_TRANSLATED_FANOUT direction per source language
    # (EN/FR/DE/ES) -- each destination's translated content must genuinely
    # differ from the untranslated source text (never a bare echo), proving
    # the real googletrans provider actually ran. ---
    for source_code in codes:
        variant_codes = tuple(code for code in codes if code != source_code)
        group_id, group_channels = await _setup_translation_group(
            ctx,
            guild,
            source_code=source_code,
            profile_ids=profile_ids,
            variant_codes=variant_codes,
        )
        campaign_id = await _activate_translation_group_campaign(
            ctx,
            guild,
            name=f"Full chain translation fanout {source_code}",
            source_language_code=source_code,
            content=contents[source_code],
            group_id=group_id,
            mode="DID_TRANSLATED_FANOUT",
        )
        await ctx.translation_runtime.tick(datetime.now(UTC))
        await _drain_all(ctx, guild.id)
        deliveries = await _get_deliveries(ctx, campaign_id)
        sent = [delivery for delivery in deliveries if delivery["status"] == "SENT"]
        results[f"translation_group.{source_code}_source_fanout_delivery_count"] = len(sent) == 4

        source_delivery = next(
            (delivery for delivery in sent if delivery["language_profile_id"] is None), None
        )
        content_ok = False
        if source_delivery is not None:
            fetched = await group_channels[source_code].fetch_message(
                int(source_delivery["discord_message_id"])
            )
            content_ok = fetched.content == contents[source_code]
        results[f"translation_group.{source_code}_source_content_matches"] = content_ok

        # Verifies both what DID's own code is responsible for (correct,
        # distinct destination routing and real non-empty rendered content
        # -- did.campaigns.rendering.render_message_model never silently
        # falls back to untranslated source text on its own; an
        # IntegrityViolation/provider error propagates instead, which these
        # checks catch indirectly via the delivery/count checks above never
        # having reached SENT) AND that a real translation genuinely
        # occurred: `contents[source_code]` is deliberately linguistic prose
        # (not a proper noun/acronym/technical-only string), so a
        # translated destination coming back byte-identical to the
        # untranslated source is treated as a real failure here, not merely
        # logged -- the googletrans-adapter-level fix
        # (`GoogletransCampaignTranslationProvider`'s `raise_exception=True`
        # fail-closed contract) means a genuine provider/transport failure
        # now raises and prevents the delivery from ever reaching SENT in
        # the first place, so reaching this comparison at all means the
        # provider really did respond successfully -- at which point an
        # unchanged destination for this kind of prose is a genuine
        # translation-quality regression, not an acceptable echo.
        translated = [delivery for delivery in sent if delivery["language_profile_id"] is not None]
        routing_ok = len(translated) == 3
        seen_dest_codes: set[str] = set()
        for delivery in translated:
            dest_code = next(
                (
                    code
                    for code, profile_id in profile_ids.items()
                    if str(profile_id) == str(delivery["language_profile_id"])
                ),
                None,
            )
            if dest_code is None or dest_code in seen_dest_codes:
                routing_ok = False
                continue
            seen_dest_codes.add(dest_code)
            fetched = await group_channels[dest_code].fetch_message(
                int(delivery["discord_message_id"])
            )
            if not fetched.content:
                routing_ok = False
            elif fetched.content == contents[source_code]:
                routing_ok = False
                note = (
                    f"REJECTED: {source_code}->{dest_code} destination content is "
                    "byte-identical to the deliberately linguistic source prose -- a "
                    "real translation did not occur for this delivery"
                )
                ctx.observations.append(note)
                print(f"  [FAIL] {note}.", flush=True)
        results[f"translation_group.{source_code}_source_translated_destinations_genuine"] = (
            routing_ok
        )

    # --- SELECTED_LANGUAGES: an explicit subset (fr, de) of the EN group's
    # three non-source variants -- es must never receive a delivery for
    # this campaign. ---
    selected_group, selected_channels = await _setup_translation_group(
        ctx,
        guild,
        source_code="en",
        profile_ids=profile_ids,
        variant_codes=("fr", "de", "es"),
    )
    del selected_channels
    selected_campaign = await _activate_translation_group_campaign(
        ctx,
        guild,
        name="Full chain translation SELECTED_LANGUAGES",
        source_language_code="en",
        content=contents["en"],
        group_id=selected_group,
        mode="SELECTED_LANGUAGES",
        selected_language_profile_ids=[str(profile_ids["fr"]), str(profile_ids["de"])],
    )
    await ctx.translation_runtime.tick(datetime.now(UTC))
    await _drain_all(ctx, guild.id)
    deliveries = await _get_deliveries(ctx, selected_campaign)
    sent = [delivery for delivery in deliveries if delivery["status"] == "SENT"]
    selected_codes = {
        code
        for code, profile_id in profile_ids.items()
        if any(str(profile_id) == str(delivery["language_profile_id"]) for delivery in sent)
    }
    # did.campaigns.target_resolution's own SELECTED_LANGUAGES branch
    # returns ONLY the explicitly selected destinations -- never the
    # source channel (unlike DID_TRANSLATED_FANOUT, which always includes
    # it) -- exactly 2 deliveries (fr, de), es never touched.
    results["translation_group.selected_languages_exact_subset"] = len(
        sent
    ) == 2 and selected_codes == {"fr", "de"}

    # --- Approved variant reuse: a pre-approved FR variant must be sent
    # verbatim, never retranslated live, even while DE (no approved
    # variant) is genuinely live-translated in the very same fan-out. ---
    variant_group, variant_channels = await _setup_translation_group(
        ctx,
        guild,
        source_code="en",
        profile_ids=profile_ids,
        variant_codes=("fr", "de"),
    )
    # Deliberately linguistic prose, same rationale as `contents` above --
    # DE has no approved variant and must be genuinely live-translated, so a
    # byte-identical DE destination is a real failure, not an echo excused
    # as translation-quality noise.
    variant_source_content = "We have rebalanced several older items that had fallen out of use."
    approved_content = "Approved French content -- must never be retranslated live."
    created = await ctx.client_http.post(
        "/api/v1/campaigns",
        json={
            "name": "Full chain approved-variant reuse",
            "source_language_code": "en",
            "message_model": {"content": variant_source_content},
            "allowed_mentions_policy": {},
            "publication_mode": "ONE_SHOT_DEFERRED",
        },
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-tr-variant-campaign-{uuid4()}"},
    )
    if created.status_code != 201:
        raise RuntimeError(f"campaign create failed: {created.status_code} {created.text}")
    variant_campaign_id = created.json()["campaign"]["id"]
    # The real, durably-stored message_model is what the real
    # did.campaigns.approved_variants.compute_source_fingerprint would
    # itself hash -- read it back rather than recomputing it from the
    # locally-held request body, so this can never silently drift from
    # whatever normalization the create endpoint actually applied.
    campaign_row = await ctx.campaigns_repo.get_campaign(OWNER, UUID(variant_campaign_id))
    assert campaign_row is not None
    fingerprint = compute_source_fingerprint(
        cast(MessageCampaign, SimpleNamespace(message_model=campaign_row["message_model"]))
    )
    await ctx.campaigns_repo.upsert_approved_variant(
        ApprovedVariant(
            id=uuid4(),
            owner_discord_user_id=OWNER,
            campaign_id=UUID(variant_campaign_id),
            target_language_code="fr",
            source_fingerprint=fingerprint,
            localized_message_model=MessageModel(content=approved_content).to_dict(),
            approved_by_discord_user_id=OWNER,
        )
    )
    target_body = {
        "guild_id": str(guild.id),
        "target_kind": "TRANSLATION_GROUP",
        "translation_group_id": str(variant_group),
        "translation_publication_mode": "DID_TRANSLATED_FANOUT",
    }
    targeted = await ctx.client_http.post(
        f"/api/v1/campaigns/{variant_campaign_id}/targets",
        json=target_body,
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-tr-variant-target-{uuid4()}"},
    )
    if targeted.status_code != 201:
        raise RuntimeError(f"target create failed: {targeted.status_code} {targeted.text}")
    fire_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    await ctx.client_http.post(
        f"/api/v1/campaigns/{variant_campaign_id}/schedule",
        json={"schedule_kind": "ONE_SHOT", "fire_at": fire_at},
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-tr-variant-schedule-{uuid4()}"},
    )
    await ctx.client_http.post(
        f"/api/v1/campaigns/{variant_campaign_id}/activate",
        headers={"X-CSRF-Token": ctx.csrf, "Idempotency-Key": f"fc-tr-variant-activate-{uuid4()}"},
    )
    await ctx.translation_runtime.tick(datetime.now(UTC))
    await _drain_all(ctx, guild.id)
    deliveries = await _get_deliveries(ctx, variant_campaign_id)
    sent = [delivery for delivery in deliveries if delivery["status"] == "SENT"]
    fr_delivery = next(
        (d for d in sent if str(d["language_profile_id"]) == str(profile_ids["fr"])), None
    )
    de_delivery = next(
        (d for d in sent if str(d["language_profile_id"]) == str(profile_ids["de"])), None
    )
    fr_ok = False
    if fr_delivery is not None:
        fetched = await variant_channels["fr"].fetch_message(int(fr_delivery["discord_message_id"]))
        fr_ok = fetched.content == approved_content
    # DE has no approved variant, so it must take the live-translation
    # branch rather than REUSABLE -- verified by real delivery/non-empty
    # content AND that a genuine translation occurred: `variant_source_
    # content` is deliberately linguistic prose, so a DE destination coming
    # back byte-identical to it is treated as a real failure here, not an
    # acceptable echo (see the fanout loop above for the full rationale --
    # a real provider/transport failure now raises via the adapter's
    # fail-closed `raise_exception=True` contract before ever reaching a
    # SENT delivery, so reaching this comparison means the provider really
    # did respond).
    de_ok = False
    if de_delivery is not None:
        fetched = await variant_channels["de"].fetch_message(int(de_delivery["discord_message_id"]))
        de_ok = bool(fetched.content) and fetched.content != variant_source_content
        if fetched.content == variant_source_content:
            note = (
                "REJECTED: en->de approved-variant sibling destination content is "
                "byte-identical to the deliberately linguistic source prose -- a real "
                "translation did not occur for this delivery"
            )
            ctx.observations.append(note)
            print(f"  [FAIL] {note}.", flush=True)
    results["translation_group.approved_variant_reused_verbatim"] = fr_ok
    results["translation_group.approved_variant_sibling_genuinely_translated"] = de_ok


async def _group_translation_group_provider_boundary(
    ctx: _Context, results: dict[str, bool]
) -> None:
    guild = ctx.guild_a
    profile_ids = await _setup_language_profiles(ctx, guild)

    # --- EXISTING_PROVIDER: DID publishes only the source channel, exactly
    # like SOURCE_ONLY -- did.campaigns.target_resolution's own
    # source_only_modes tuple treats both identically, by design (DID never
    # itself posts a destination-language message in either mode, so there
    # is no external-bot participation for DID's own code path to
    # exercise). ---
    existing_provider_group, existing_provider_channels = await _setup_translation_group(
        ctx,
        guild,
        source_code="en",
        profile_ids=profile_ids,
        variant_codes=("fr",),
    )
    del existing_provider_channels
    existing_provider_campaign = await _activate_translation_group_campaign(
        ctx,
        guild,
        name="Full chain EXISTING_PROVIDER",
        source_language_code="en",
        content="Full chain EXISTING_PROVIDER source (synthetic, live qualification).",
        group_id=existing_provider_group,
        mode="EXISTING_PROVIDER",
    )
    await ctx.translation_runtime.tick(datetime.now(UTC))
    await _drain_all(ctx, guild.id)
    deliveries = await _get_deliveries(ctx, existing_provider_campaign)
    results["translation_group.existing_provider_publishes_only_source"] = (
        len(deliveries) == 1
        and deliveries[0]["status"] == "SENT"
        and deliveries[0]["language_profile_id"] is None
    )

    # --- No actual external translation provider bot exists in this
    # sandbox -- a genuine environment limitation, not simulated. Rather
    # than fake one, this proves DID's own real fail-closed contract
    # (did.campaigns.translation_group_safety.evaluate_translation_group_safety)
    # against a REAL durable Stage08 provider-binding row (status=READY),
    # live, through the real product chain -- no Discord bot participates
    # on the other end, and none is required to prove this dimension: DID's
    # own contract is that ANY possibly-active binding blocks its own
    # DID-translated fan-out, never that the bound provider is verified to
    # actually behave correctly. A fresh pair of channels for this specific
    # scenario (never touched by the EXISTING_PROVIDER campaign above)
    # means a plain post-run zero count is already the strongest possible
    # no-mutation evidence -- no before/after delta needed. ---
    binding = await ctx.provider_bindings.create(
        guild_id=guild.id,
        provider_type="EXTERNAL_BOT",
        provider_instance_key=f"full-chain-live-{uuid4().hex[:8]}",
        capabilities={},
        status="READY",
    )
    blocked_group, blocked_channels = await _setup_translation_group(
        ctx,
        guild,
        source_code="en",
        profile_ids=profile_ids,
        variant_codes=("fr",),
        provider_binding_id=binding["id"],
    )
    blocked_campaign = await _activate_translation_group_campaign(
        ctx,
        guild,
        name="Full chain provider-bound block",
        source_language_code="en",
        content="Full chain provider-bound block source (synthetic, live qualification).",
        group_id=blocked_group,
        mode="DID_TRANSLATED_FANOUT",
    )
    await ctx.translation_runtime.tick(datetime.now(UTC))
    await _drain_all(ctx, guild.id)
    deliveries = await _get_deliveries(ctx, blocked_campaign)
    # MANUAL_CONFIGURATION_REQUIRED: did.campaigns.target_resolution's own
    # fail-closed contract means NOTHING is sent at all when a possibly-
    # active external provider is bound to the same group -- not even the
    # source destination -- rather than risk a re-translation loop.
    results["translation_group.provider_bound_blocks_fanout_no_mutation"] = len(deliveries) == 0
    en_count = len([message async for message in blocked_channels["en"].history(limit=10)])
    fr_count = len([message async for message in blocked_channels["fr"].history(limit=10)])
    results["translation_group.provider_bound_no_discord_messages_sent"] = (
        en_count == 0 and fr_count == 0
    )


GROUP_FUNCTIONS = {
    "immediate_channel": _group_immediate_channel,
    "one_shot_deferred": _group_one_shot_deferred,
    "recurring": _group_recurring,
    "event_triggered": _group_event_triggered,
    "logical_group": _group_logical_group,
    "owned_edit_delete": _group_owned_edit_delete,
    "embed_button": _group_embed_button,
    "governor_fairness": _group_governor_fairness,
    "retention_leaves_discord_untouched": _group_retention_leaves_discord_untouched,
    "translation_group_did_fanout": _group_translation_group_did_fanout,
    "translation_group_provider_boundary": _group_translation_group_provider_boundary,
}


async def run_live(
    guild_a_id: int, guild_b_id: int, token: str, groups: tuple[str, ...]
) -> tuple[dict[str, bool], list[str]]:
    admin_engine = create_database_engine(ADMIN_URL, pool_size=5)
    app_engine = create_database_engine(APP_URL, pool_size=5)
    results: dict[str, bool] = {}
    observations: list[str] = []
    try:
        await _reset(admin_engine, guild_a_id, guild_b_id)

        intents = discord.Intents.default()
        discord_client = discord.Client(intents=intents)
        temp_channels: list[discord.TextChannel] = []
        captured_exception: list[BaseException] = []

        @discord_client.event
        async def on_ready() -> None:
            try:
                bot_user_id = discord_client.user.id  # type: ignore[union-attr]
                guild_a = discord_client.get_guild(guild_a_id) or await discord_client.fetch_guild(
                    guild_a_id
                )
                guild_b = discord_client.get_guild(guild_b_id) or await discord_client.fetch_guild(
                    guild_b_id
                )

                oauth = FakeOAuthClient(
                    (
                        DiscordGuild(guild_a_id, "Sandbox A", None, True, 0),
                        DiscordGuild(guild_b_id, "Sandbox B", None, True, 0),
                    )
                )
                app = create_app(
                    _settings(),
                    oauth_client=oauth,
                    member_client=FakeMemberClient(),
                )
                async with app.router.lifespan_context(app):
                    # Real did.application.installations.InstallationService
                    # .record_detected (not a raw INSERT) -- it leaves the
                    # installation in its real pre-bootstrap state, exactly
                    # like every Stage09 API test's own setup, so the
                    # subsequent HTTP bootstrap call below genuinely runs
                    # activate_and_create_owner rather than short-circuiting
                    # on an already-ACTIVE row with no owner access row yet.
                    for guild_id in (guild_a_id, guild_b_id):
                        await app.state.services.installations.record_detected(
                            guild_id=guild_id,
                            name=f"Stage09 full-chain live {guild_id}",
                            icon_hash=None,
                            owner_id=OWNER,
                            application_id=OWNER,
                            bot_user_id=bot_user_id,
                        )

                    async with AsyncClient(
                        transport=ASGITransport(app=app, raise_app_exceptions=False),
                        base_url="http://test",
                        follow_redirects=False,
                    ) as client_http:
                        csrf = await _login(client_http)
                        for guild_id in (guild_a_id, guild_b_id):
                            bootstrapped = await client_http.post(
                                f"/api/v1/guilds/{guild_id}/bootstrap",
                                headers={"X-CSRF-Token": csrf},
                            )
                            if bootstrapped.status_code != 200:
                                raise RuntimeError(
                                    f"bootstrap failed for guild {guild_id}: "
                                    f"{bootstrapped.status_code} {bootstrapped.text}"
                                )

                        factory = async_sessionmaker(app_engine, expire_on_commit=False)
                        admin_factory = async_sessionmaker(admin_engine, expire_on_commit=False)
                        campaigns_repo = CampaignsRepository(factory)
                        runtime_repo = RuntimeRepository(factory)
                        sender = DiscordPyMessageSender(discord_client)
                        governor = DiscordWorkloadGovernor()
                        executor = CampaignDeliveryExecutor(
                            campaigns_repo, sender, worker_id="stage09-full-chain-live"
                        )
                        worker = DurableDiscordIOWorker(
                            runtime_repo,
                            _NullSync(),
                            worker_id="stage09-full-chain-live",
                            campaign_delivery_executor=executor,
                        )
                        language_profiles = LanguageProfileRepository(admin_factory)
                        translation_groups = TranslationGroupRepository(admin_factory)
                        provider_bindings = TranslationProviderBindingRepository(admin_factory)
                        stage04_repo = Stage04Repository(admin_factory)
                        runtime = CampaignSchedulerRuntime(
                            campaigns_repository=campaigns_repo,
                            runtime_repository=runtime_repo,
                            admin_factory=admin_factory,
                            language_profiles=language_profiles,
                            translation_groups=translation_groups,
                            checker=_AlwaysAuthorizedChecker(),
                            translation_provider=None,
                            lease_owner="stage09-full-chain-live",
                        )
                        # Same real production entrypoint, wired with the
                        # REAL GoogletransCampaignTranslationProvider exactly
                        # as did.runtime.py itself constructs it (never a
                        # fake) -- and with stage04_repository/
                        # provider_bindings wired so a Translation Group's
                        # real provider-binding status genuinely gates
                        # DID_TRANSLATED_FANOUT/SELECTED_LANGUAGES the same
                        # way the production scheduler process does.
                        translation_runtime = CampaignSchedulerRuntime(
                            campaigns_repository=campaigns_repo,
                            runtime_repository=runtime_repo,
                            admin_factory=admin_factory,
                            language_profiles=language_profiles,
                            translation_groups=translation_groups,
                            checker=_AlwaysAuthorizedChecker(),
                            translation_provider=GoogletransCampaignTranslationProvider(),
                            stage04_repository=stage04_repo,
                            provider_bindings=provider_bindings,
                            lease_owner="stage09-full-chain-live-translation",
                        )

                        ctx = _Context(
                            client_http=client_http,
                            csrf=csrf,
                            discord_client=discord_client,
                            guild_a=guild_a,
                            guild_b=guild_b,
                            bot_user_id=bot_user_id,
                            admin_engine=admin_engine,
                            campaigns_repo=campaigns_repo,
                            runtime_repo=runtime_repo,
                            admin_factory=admin_factory,
                            worker=worker,
                            governor=governor,
                            runtime=runtime,
                            translation_runtime=translation_runtime,
                            language_profiles=language_profiles,
                            translation_groups=translation_groups,
                            provider_bindings=provider_bindings,
                        )

                        for group_name in groups:
                            await GROUP_FUNCTIONS[group_name](ctx, results)

                        temp_channels.extend(ctx.temp_channels)
                        observations.extend(ctx.observations)
            except BaseException as exc:
                # discord.py's own event dispatch swallows an exception
                # raised inside an @event handler (routes it to on_error,
                # logs it, and lets client.start() return normally) -- left
                # unhandled here, a mid-run failure would silently produce a
                # PASS from an empty/partial `results` dict via vacuous
                # `all(results.values())`. Captured and re-raised below,
                # once the client has actually shut down, so main() reports
                # BLOCKED honestly instead.
                captured_exception.append(exc)
            finally:
                for channel in temp_channels:
                    try:
                        await channel.delete()
                    except discord.NotFound:
                        pass
                await discord_client.close()

        await discord_client.start(token)
        if captured_exception:
            raise captured_exception[0]
        return results, observations
    finally:
        await _reset(admin_engine, guild_a_id, guild_b_id)
        await app_engine.dispose()
        await admin_engine.dispose()


class _NullSync:
    async def refresh_channels(self, guild_id: int) -> dict[str, int]:
        raise NotImplementedError

    async def initial_sync(self, guild_id: int) -> dict[str, int]:
        raise NotImplementedError
