from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import secrets
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from did.oauth.crypto import decode_encryption_key
from did.oauth.discord import (
    DISCORD_API_BASE,
    DISCORD_AUTHORIZE_URL,
    DISCORD_USER_AGENT,
    DiscordOAuthError,
    HttpDiscordMemberClient,
    HttpDiscordOAuthClient,
)
from did.oauth.models import OAUTH_SCOPE_PARAMETER, OAUTH_SCOPES, DiscordGuild, OAuthTokenSet

REQUIRED_VARIABLES = (
    "DISCORD_CLIENT_ID",
    "DISCORD_CLIENT_SECRET",
    "DISCORD_BOT_TOKEN",
    "DISCORD_REDIRECT_URI",
    "DISCORD_TEST_GUILD_A_ID",
    "DISCORD_TEST_GUILD_B_ID",
    "SESSION_SECRET",
    "OAUTH_TOKEN_ENCRYPTION_KEY",
)
ADMINISTRATOR = 1 << 3
PROFILE_ORDER = ("single-account",)


@dataclass(frozen=True, slots=True)
class LiveConfig:
    client_id: str
    client_secret: str = field(repr=False)
    bot_token: str = field(repr=False)
    redirect_uri: str
    guilds: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class ProfileEvidence:
    user_id: int = field(repr=False)
    guild_id: int = field(repr=False)
    tokens: OAuthTokenSet = field(repr=False)


@dataclass(slots=True)
class LiveRun:
    config: LiveConfig
    report_path: Path
    states: dict[str, str] = field(default_factory=dict, repr=False)
    profiles: dict[str, ProfileEvidence] = field(default_factory=dict, repr=False)
    installation_steps: dict[str, str] = field(default_factory=dict)
    checks: list[str] = field(default_factory=list)
    skipped_not_verified: list[str] = field(default_factory=list)
    error: str | None = None
    done: bool = False

    def __post_init__(self) -> None:
        self.installation_steps = {label: "ENSURE_PRESENT" for label, _ in self.config.guilds}

    @property
    def next_profile(self) -> str | None:
        return next((profile for profile in PROFILE_ORDER if profile not in self.profiles), None)

    @property
    def profile_phase_complete(self) -> bool:
        return self.next_profile is None

    @property
    def installation_phase_complete(self) -> bool:
        return all(step == "DONE" for step in self.installation_steps.values())


class BotProbe:
    def __init__(self, token: str) -> None:
        self._client = httpx.Client(
            timeout=10.0,
            headers={"Authorization": f"Bot {token}", "User-Agent": DISCORD_USER_AGENT},
        )
        self._blocked_until = 0.0

    def close(self) -> None:
        self._client.close()

    def get(self, path: str) -> httpx.Response:
        remaining = self._blocked_until - time.monotonic()
        if remaining > 0:
            raise RuntimeError("Discord bot probe is rate-limit deferred")
        response = self._client.get(f"{DISCORD_API_BASE}{path}")
        delay = _rate_limit_delay(response)
        if delay is not None:
            self._blocked_until = time.monotonic() + delay
        return response

    def validate_identity(self, expected_application_id: str) -> None:
        response = self.get("/users/@me")
        if response.status_code != 200:
            raise RuntimeError(f"Discord bot identity probe failed ({response.status_code})")
        payload = response.json()
        if not isinstance(payload, dict) or str(payload.get("id")) != expected_application_id:
            raise RuntimeError("Discord bot identity does not match DISCORD_CLIENT_ID")

    def guild_present(self, guild_id: int) -> bool:
        response = self.get(f"/guilds/{guild_id}")
        if response.status_code == 200:
            return True
        if response.status_code in {403, 404}:
            return False
        raise RuntimeError(f"Discord Guild presence probe failed ({response.status_code})")


def load_local_environment(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name in REQUIRED_VARIABLES and name not in os.environ:
            os.environ[name] = value.strip().strip('"').strip("'")


def write_report(
    path: Path,
    *,
    status: str,
    checks: list[str],
    missing: list[str],
    details: dict[str, str] | None = None,
    skipped_not_verified: list[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "stage": "02",
        "profile": "discord-live-sandbox",
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "missing_variable_names": missing,
        "details": details or {},
        "skipped_not_verified": skipped_not_verified or [],
        "secrets_recorded": False,
    }
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def load_config() -> LiveConfig:
    guilds: list[tuple[str, int]] = []
    for label, name in (
        ("Guild A", "DISCORD_TEST_GUILD_A_ID"),
        ("Guild B", "DISCORD_TEST_GUILD_B_ID"),
    ):
        try:
            guild_id = int(os.environ[name])
        except ValueError as exc:
            raise RuntimeError(f"{name} must be a Discord snowflake") from exc
        if guild_id <= 0:
            raise RuntimeError(f"{name} must be a positive Discord snowflake")
        guilds.append((label, guild_id))
    if guilds[0][1] == guilds[1][1]:
        raise RuntimeError("Guild A and Guild B must be different sandboxes")
    redirect_uri = os.environ["DISCORD_REDIRECT_URI"]
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("DISCORD_REDIRECT_URI must use an HTTP loopback address for this run")
    if parsed.port is None or not parsed.path:
        raise RuntimeError("DISCORD_REDIRECT_URI must include an explicit port and callback path")
    if len(os.environ["SESSION_SECRET"]) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 characters")
    decode_encryption_key(os.environ["OAUTH_TOKEN_ENCRYPTION_KEY"])
    return LiveConfig(
        client_id=os.environ["DISCORD_CLIENT_ID"],
        client_secret=os.environ["DISCORD_CLIENT_SECRET"],
        bot_token=os.environ["DISCORD_BOT_TOKEN"],
        redirect_uri=redirect_uri,
        guilds=tuple(guilds),
    )


async def exchange_profile(
    config: LiveConfig, code: str
) -> tuple[int, OAuthTokenSet, tuple[DiscordGuild, ...]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        oauth = HttpDiscordOAuthClient(
            client_id=config.client_id,
            client_secret=config.client_secret,
            redirect_uri=config.redirect_uri,
            client=client,
        )
        tokens = await oauth.exchange_code(code)
        if tokens.scopes != OAUTH_SCOPES:
            returned = " ".join(sorted(tokens.scopes)) or "<none>"
            raise RuntimeError(
                "Discord returned scopes different from identify guilds: " + returned
            )
        user = await oauth.current_user(tokens.access_token)
        guilds = await oauth.current_user_guilds(tokens.access_token)
        return user.discord_user_id, tokens, guilds


async def revoke_profiles(config: LiveConfig, profiles: dict[str, ProfileEvidence]) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        oauth = HttpDiscordOAuthClient(
            client_id=config.client_id,
            client_secret=config.client_secret,
            redirect_uri=config.redirect_uri,
            client=client,
        )
        for profile in profiles.values():
            await oauth.revoke(profile.tokens.refresh_token)


async def verify_targeted_members(config: LiveConfig, profiles: dict[str, ProfileEvidence]) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        member_client = HttpDiscordMemberClient(bot_token=config.bot_token, client=client)
        for profile in profiles.values():
            await member_client.get_member_roles(profile.guild_id, profile.user_id)


def oauth_url(config: LiveConfig, state: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": config.client_id,
            "scope": OAUTH_SCOPE_PARAMETER,
            "state": state,
            "redirect_uri": config.redirect_uri,
            "prompt": "consent",
        }
    )
    return f"{DISCORD_AUTHORIZE_URL}?{query}"


def installation_url(config: LiveConfig, guild_id: int) -> str:
    query = urlencode(
        {
            "client_id": config.client_id,
            "scope": "bot",
            "permissions": "0",
            "guild_id": str(guild_id),
            "disable_guild_select": "true",
        }
    )
    return f"{DISCORD_AUTHORIZE_URL}?{query}"


def installation_prompt(*, label: str, link: str, reinstall: bool) -> str:
    verb = "Reinstall" if reinstall else "Install"
    initial_guidance = (
        "<p>If the bot is already present, do not install it again; check its status first.</p>"
        if not reinstall
        else ""
    )
    return (
        f"<h2>{verb} the zero-permission test bot on {label}</h2>"
        f"{initial_guidance}<a href='{link}' target='_blank'>{verb} on {label}</a>"
        "<p>After Discord confirms the installation, return here and check once.</p>"
        "<a href='/'>Check Discord status</a>"
    )


def _rate_limit_delay(response: httpx.Response) -> float | None:
    if response.status_code == 429:
        raw: object = response.headers.get("Retry-After")
        if raw is None:
            payload = response.json()
            raw = payload.get("retry_after") if isinstance(payload, dict) else 1
        try:
            return max(0.0, float(str(raw)))
        except ValueError:
            return 1.0
    if response.headers.get("X-RateLimit-Remaining") == "0":
        try:
            return max(0.0, float(response.headers["X-RateLimit-Reset-After"]))
        except (KeyError, ValueError):
            return None
    return None


def handler_factory(
    run: LiveRun, bot: BotProbe, callback_path: str
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/":
                    self._serve_home()
                elif parsed.path == "/start":
                    self._start_profile(parse_qs(parsed.query))
                elif parsed.path == callback_path:
                    self._oauth_callback(parse_qs(parsed.query))
                else:
                    self.send_error(404)
            except Exception as exc:
                if isinstance(exc, (RuntimeError, DiscordOAuthError)):
                    reason = str(exc)
                else:
                    reason = type(exc).__name__
                run.error = f"Live validation failed safely: {reason}"
                self._redirect_home()

        def _start_profile(self, query: dict[str, list[str]]) -> None:
            profile = query.get("profile", [""])[0]
            if profile != run.next_profile:
                raise RuntimeError("unexpected live profile sequence")
            state = secrets.token_urlsafe(32)
            run.states[state] = profile
            self.send_response(302)
            self.send_header("Location", oauth_url(run.config, state))
            self.end_headers()

        def _oauth_callback(self, query: dict[str, list[str]]) -> None:
            state = query.get("state", [""])[0]
            profile = run.states.pop(state, None)
            if profile is None:
                raise RuntimeError("OAuth state is missing, expired, replayed or mismatched")
            if query.get("error"):
                raise RuntimeError("Discord OAuth authorization was denied")
            code = query.get("code", [""])[0]
            if not code:
                raise RuntimeError("Discord OAuth callback code is missing")
            user_id, tokens, guilds = asyncio.run(exchange_profile(run.config, code))
            temporary = {profile: ProfileEvidence(user_id, run.config.guilds[0][1], tokens)}
            if run.profiles and any(
                evidence.user_id != user_id for evidence in run.profiles.values()
            ):
                asyncio.run(revoke_profiles(run.config, temporary))
                raise RuntimeError("all live profiles must reuse the same sandbox account")
            expected = {guild_id for _, guild_id in run.config.guilds}
            discovered = {guild.guild_id: guild for guild in guilds if guild.guild_id in expected}
            if set(discovered) != expected:
                asyncio.run(revoke_profiles(run.config, temporary))
                raise RuntimeError("the single sandbox account must be a member of Guild A and B")
            owned = [guild for guild in discovered.values() if guild.owner]
            if not owned:
                asyncio.run(revoke_profiles(run.config, temporary))
                raise RuntimeError("the single sandbox account must own Guild A or Guild B")
            non_owned = [guild for guild in discovered.values() if not guild.owner]
            administrator_observed = any(
                bool(guild.permissions & ADMINISTRATOR) for guild in non_owned
            )
            non_administrator_observed = any(
                not bool(guild.permissions & ADMINISTRATOR) for guild in non_owned
            )
            run.profiles[profile] = ProfileEvidence(user_id, owned[0].guild_id, tokens)
            run.checks.append("OAuth identify/guilds profile: owner")
            if administrator_observed:
                run.checks.append("OAuth Guild discovery profile: administrator")
            else:
                run.skipped_not_verified.append("live administrator non-owner profile")
            if non_administrator_observed:
                run.checks.append("OAuth Guild discovery profile: non-administrator")
            else:
                run.skipped_not_verified.append("live non-administrator profile")
            run.error = None
            self._redirect_home()

        def _serve_home(self) -> None:
            if run.profile_phase_complete and not run.installation_phase_complete:
                self._advance_installation()
            if run.profile_phase_complete and run.installation_phase_complete and not run.done:
                asyncio.run(verify_targeted_members(run.config, run.profiles))
                run.checks.append("targeted Get Guild Member for each live actor")
                asyncio.run(revoke_profiles(run.config, run.profiles))
                run.checks.append("temporary OAuth grants revoked")
                run.done = True
            body = self._home_body()
            encoded = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'"
            )
            self.end_headers()
            self.wfile.write(encoded)

        def _advance_installation(self) -> None:
            current = next(
                (
                    (label, guild_id, run.installation_steps[label])
                    for label, guild_id in run.config.guilds
                    if run.installation_steps[label] != "DONE"
                ),
                None,
            )
            if current is None:
                return
            label, guild_id, step = current
            present = bot.guild_present(guild_id)
            if step == "ENSURE_PRESENT" and present:
                run.installation_steps[label] = "REMOVE"
                run.checks.append(f"minimal bot installation observed: {label}")
            elif step == "REMOVE" and not present:
                run.installation_steps[label] = "REINSTALL"
                run.checks.append(f"bot uninstall observed: {label}")
            elif step == "REINSTALL" and present:
                run.installation_steps[label] = "DONE"
                run.checks.append(f"bot reinstall observed: {label}")
            run.error = None

        def _home_body(self) -> str:
            error = f"<p class='error'>{html.escape(run.error)}</p>" if run.error else ""
            if run.done:
                action = (
                    "<h2>PASS</h2><p>The redacted live report is complete. "
                    "You may close this tab.</p>"
                )
            elif run.next_profile is not None:
                profile = run.next_profile
                action = (
                    "<h2>OAuth profile: single sandbox account</h2>"
                    "<p>Use the one account that owns one configured Guild and is a member of "
                    "the other. Its actual permission state on the second Guild will be recorded "
                    "without requiring another account.</p>"
                    f"<a href='/start?profile={html.escape(profile)}'>Continue with Discord</a>"
                )
            else:
                action = self._installation_action()
            completed = "".join(f"<li>{html.escape(check)}</li>" for check in run.checks)
            skipped = "".join(
                f"<li>{html.escape(item)}: SKIPPED_NOT_VERIFIED</li>"
                for item in run.skipped_not_verified
            )
            return (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>DID STAGE 02 live validation</title><style>"
                "body{font:16px system-ui;max-width:760px;margin:48px auto;padding:0 20px}"
                "a{display:inline-block;padding:10px 14px;background:#5865f2;color:white;"
                "text-decoration:none;border-radius:6px}.error{color:#b42318}</style></head><body>"
                "<h1>Discord Infrastructure Designer - STAGE 02 live validation</h1>"
                "<p>Only the two configured sandbox Guilds are in scope. No Guild is deleted.</p>"
                f"{error}{action}<h2>Completed checks</h2><ul>{completed}</ul>"
                f"<h2>Explicit limitations</h2><ul>{skipped}</ul></body></html>"
            )

        def _installation_action(self) -> str:
            current = next(
                (
                    (label, guild_id, run.installation_steps[label])
                    for label, guild_id in run.config.guilds
                    if run.installation_steps[label] != "DONE"
                ),
                None,
            )
            if current is None:
                return "<p>Finalizing targeted member checks and OAuth cleanup...</p>"
            label, guild_id, step = current
            if step in {"ENSURE_PRESENT", "REINSTALL"}:
                link = html.escape(installation_url(run.config, guild_id), quote=True)
                return installation_prompt(
                    label=label,
                    link=link,
                    reinstall=step == "REINSTALL",
                )
            return (
                f"<h2>Remove the test bot from {label}</h2>"
                "<p>Use Discord Server Settings to remove only this sandbox bot. "
                "Do not delete the server. Then check once.</p>"
                "<a href='/'>Check Discord status</a>"
            )

        def _redirect_home(self) -> None:
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

    return Handler


def run_interactive(config: LiveConfig, report_path: Path) -> LiveRun:
    parsed = urlparse(config.redirect_uri)
    assert parsed.hostname is not None
    assert parsed.port is not None
    bot = BotProbe(config.bot_token)
    run = LiveRun(config=config, report_path=report_path)
    try:
        bot.validate_identity(config.client_id)
        run.checks.append("bot identity matches application")
        server = HTTPServer(
            (parsed.hostname, parsed.port),
            handler_factory(run, bot, parsed.path),
        )
        server.timeout = 2.0
        start_url = f"http://{parsed.hostname}:{parsed.port}/"
        print(f"Discord live guided validation: {start_url}")
        webbrowser.open(start_url)
        deadline = time.monotonic() + 1500
        while not run.done and time.monotonic() < deadline:
            server.handle_request()
        server.server_close()
        if not run.done:
            raise RuntimeError("interactive Discord validation timed out")
        return run
    except Exception:
        if run.profiles:
            try:
                asyncio.run(revoke_profiles(config, run.profiles))
            except Exception as cleanup_error:
                run.checks.append(f"OAuth cleanup failed safely: {type(cleanup_error).__name__}")
        raise
    finally:
        bot.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="STAGE 02 Discord sandbox validation gate")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--include", action="store_true")
    arguments = parser.parse_args()

    if not arguments.include:
        write_report(
            arguments.report,
            status="SKIPPED_NOT_VERIFIED",
            checks=[],
            missing=[],
        )
        print("Discord live: SKIPPED_NOT_VERIFIED (use --include-discord-live explicitly)")
        return 0

    load_local_environment(Path(".env.local"))
    missing = [name for name in REQUIRED_VARIABLES if not os.environ.get(name)]
    if missing:
        write_report(
            arguments.report,
            status="SKIPPED_NOT_VERIFIED",
            checks=[],
            missing=missing,
        )
        print("Discord live: SKIPPED_NOT_VERIFIED; missing variable names: " + ", ".join(missing))
        return 2

    try:
        config = load_config()
        run = run_interactive(config, arguments.report)
    except Exception as exc:
        write_report(
            arguments.report,
            status="FAIL",
            checks=[],
            missing=[],
            details={"reason": f"{type(exc).__name__}: live validation did not complete"},
        )
        print(f"Discord live: FAIL ({type(exc).__name__}); no secret value was recorded")
        return 1
    live_status = "PASS" if not run.skipped_not_verified else "PASS_WITH_APPROVED_LIMITATION"
    write_report(
        arguments.report,
        status=live_status,
        checks=run.checks,
        missing=[],
        details={
            "oauth_profiles": "one sandbox account; actual A/B permission states recorded",
            "guilds": "Guild A and Guild B",
            "cleanup": "bot reinstalled on both sandboxes; temporary OAuth grants revoked",
            "limitation": "single-account live profile explicitly required by the user",
        },
        skipped_not_verified=run.skipped_not_verified,
    )
    print(f"Discord live: {live_status}; redacted report written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
