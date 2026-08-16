import asyncio
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode

import httpx

from did.oauth.models import (
    OAUTH_SCOPE_PARAMETER,
    DiscordGuild,
    DiscordUser,
    OAuthTokenSet,
)

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_USER_AGENT = "DiscordBot (https://github.com/Anthorusse75, 0.1.0)"


class DiscordOAuthError(RuntimeError):
    """An intentionally non-sensitive OAuth adapter error."""

    def __init__(self, operation: str, status_code: int | None = None) -> None:
        self.operation = operation
        self.status_code = status_code
        super().__init__(f"Discord OAuth operation failed: {operation}")


class DiscordOAuthClient(Protocol):
    def authorization_url(self, *, state: str) -> str: ...

    async def exchange_code(self, code: str) -> OAuthTokenSet: ...

    async def refresh(self, refresh_token: str) -> OAuthTokenSet: ...

    async def revoke(self, token: str) -> None: ...

    async def current_user(self, access_token: str) -> DiscordUser: ...

    async def current_user_guilds(self, access_token: str) -> tuple[DiscordGuild, ...]: ...


class DiscordMemberClient(Protocol):
    async def get_member_roles(self, guild_id: int, user_id: int) -> tuple[int, ...]: ...


class HttpDiscordOAuthClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not client_id or not client_secret or not redirect_uri:
            raise ValueError("Discord OAuth client configuration is incomplete")
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._owns_client = client is None

    def authorization_url(self, *, state: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "scope": OAUTH_SCOPE_PARAMETER,
                "state": state,
                "redirect_uri": self._redirect_uri,
                "prompt": "consent",
            }
        )
        return f"{DISCORD_AUTHORIZE_URL}?{query}"

    async def exchange_code(self, code: str) -> OAuthTokenSet:
        return await self._token_request(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": self._redirect_uri}
        )

    async def refresh(self, refresh_token: str) -> OAuthTokenSet:
        return await self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    async def revoke(self, token: str) -> None:
        response = await self._client.post(
            f"{DISCORD_API_BASE}/oauth2/token/revoke",
            data={"token": token, "token_type_hint": "refresh_token"},
            auth=(self._client_id, self._client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code >= 400:
            raise DiscordOAuthError("revoke", response.status_code)

    async def current_user(self, access_token: str) -> DiscordUser:
        payload = await self._get_json("/users/@me", access_token, "current_user")
        return DiscordUser(
            discord_user_id=_snowflake(payload.get("id"), "user.id"),
            username=_required_string(payload.get("username"), "user.username"),
            global_name=_optional_string(payload.get("global_name")),
            avatar_hash=_optional_string(payload.get("avatar")),
        )

    async def current_user_guilds(self, access_token: str) -> tuple[DiscordGuild, ...]:
        response = await self._client.get(
            f"{DISCORD_API_BASE}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code >= 400:
            raise DiscordOAuthError("current_user_guilds", response.status_code)
        payload = response.json()
        if not isinstance(payload, list):
            raise DiscordOAuthError("current_user_guilds_contract")
        guilds: list[DiscordGuild] = []
        for item in payload:
            if not isinstance(item, dict):
                raise DiscordOAuthError("current_user_guilds_contract")
            guilds.append(
                DiscordGuild(
                    guild_id=_snowflake(item.get("id"), "guild.id"),
                    name=_required_string(item.get("name"), "guild.name"),
                    icon_hash=_optional_string(item.get("icon")),
                    owner=bool(item.get("owner", False)),
                    permissions=_permission_bits(item.get("permissions")),
                )
            )
        return tuple(guilds)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _token_request(self, data: Mapping[str, str]) -> OAuthTokenSet:
        response = await self._client.post(
            f"{DISCORD_API_BASE}/oauth2/token",
            data=data,
            auth=(self._client_id, self._client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code >= 400:
            raise DiscordOAuthError("token", response.status_code)
        payload = response.json()
        if not isinstance(payload, dict):
            raise DiscordOAuthError("token_contract")
        try:
            access_token = _required_string(payload.get("access_token"), "access_token")
            refresh_token = _required_string(payload.get("refresh_token"), "refresh_token")
            expires_in = int(payload["expires_in"])
            scopes = frozenset(_required_string(payload.get("scope"), "scope").split())
        except (KeyError, TypeError, ValueError) as exc:
            raise DiscordOAuthError("token_contract") from exc
        if expires_in <= 0:
            raise DiscordOAuthError("token_contract")
        return OAuthTokenSet(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
            scopes=scopes,
        )

    async def _get_json(self, path: str, access_token: str, operation: str) -> dict[str, object]:
        response = await self._client.get(
            f"{DISCORD_API_BASE}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code >= 400:
            raise DiscordOAuthError(operation, response.status_code)
        payload = response.json()
        if not isinstance(payload, dict):
            raise DiscordOAuthError(f"{operation}_contract")
        return payload


class HttpDiscordMemberClient:
    def __init__(self, *, bot_token: str, client: httpx.AsyncClient | None = None) -> None:
        if not bot_token:
            raise ValueError("Discord bot token is required")
        self._bot_token = bot_token
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._owns_client = client is None
        self._gate = _Stage02BotRestGate()

    async def get_member_roles(self, guild_id: int, user_id: int) -> tuple[int, ...]:
        response = await self._gate.get(
            self._client,
            f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}",
            headers={
                "Authorization": f"Bot {self._bot_token}",
                "User-Agent": DISCORD_USER_AGENT,
            },
        )
        if response.status_code >= 400:
            raise DiscordOAuthError("targeted_member_lookup", response.status_code)
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("roles"), list):
            raise DiscordOAuthError("targeted_member_lookup_contract")
        return tuple(_snowflake(value, "member.role_id") for value in payload["roles"])

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class _Stage02BotRestGate:
    """Conservative bot-token gate until the distributed STAGE 03 governor exists."""

    def __init__(self, *, maximum_request_wait_seconds: float = 10.0) -> None:
        self._lock = asyncio.Lock()
        self._blocked_until = 0.0
        self._maximum_request_wait_seconds = maximum_request_wait_seconds

    async def get(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> httpx.Response:
        async with self._lock:
            wait_seconds = max(0.0, self._blocked_until - time.monotonic())
            if wait_seconds > self._maximum_request_wait_seconds:
                raise DiscordOAuthError("targeted_member_rate_limit_deferred", 429)
            if wait_seconds:
                await asyncio.sleep(wait_seconds)
            response = await client.get(url, headers=headers)
            delay = _discord_rate_limit_delay(response)
            if delay is not None:
                self._blocked_until = max(self._blocked_until, time.monotonic() + delay)
            return response


def _discord_rate_limit_delay(response: httpx.Response) -> float | None:
    delay: float | None = None
    if response.status_code == 429:
        raw_delay: object = response.headers.get("Retry-After")
        if raw_delay is None:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                raw_delay = payload.get("retry_after")
        try:
            delay = max(0.0, float(str(raw_delay)))
        except (TypeError, ValueError):
            delay = 1.0
    elif response.headers.get("X-RateLimit-Remaining") == "0":
        try:
            delay = max(0.0, float(response.headers["X-RateLimit-Reset-After"]))
        except (KeyError, ValueError):
            delay = None
    return delay


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DiscordOAuthError(f"invalid_{field}")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _snowflake(value: object, field: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise DiscordOAuthError(f"invalid_{field}") from exc
    if parsed <= 0:
        raise DiscordOAuthError(f"invalid_{field}")
    return parsed


def _permission_bits(value: object) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise DiscordOAuthError("invalid_guild.permissions") from exc
    if parsed < 0:
        raise DiscordOAuthError("invalid_guild.permissions")
    return parsed
