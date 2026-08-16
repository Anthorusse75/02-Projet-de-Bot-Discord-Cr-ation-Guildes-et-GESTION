from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from did.oauth.discord import DiscordOAuthError, HttpDiscordMemberClient, HttpDiscordOAuthClient


def test_authorization_url_uses_code_grant_exact_scopes_and_registered_redirect() -> None:
    client = HttpDiscordOAuthClient(
        client_id="123",
        client_secret="not-a-real-secret",
        redirect_uri="https://dashboard.example/auth/discord/callback",
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))),
    )
    query = parse_qs(urlparse(client.authorization_url(state="unique-state")).query)
    assert query == {
        "response_type": ["code"],
        "client_id": ["123"],
        "scope": ["identify guilds"],
        "state": ["unique-state"],
        "redirect_uri": ["https://dashboard.example/auth/discord/callback"],
        "prompt": ["consent"],
    }
    assert "guilds.members.read" not in query["scope"]


async def test_token_exchange_is_backend_form_encoded_and_error_is_redacted() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(400, json={"error": "invalid_grant", "token": "do-not-leak"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = HttpDiscordOAuthClient(
            client_id="123",
            client_secret="not-a-real-secret",
            redirect_uri="https://dashboard.example/auth/discord/callback",
            client=http_client,
        )
        with pytest.raises(DiscordOAuthError) as captured:
            await client.exchange_code("single-use-code")
    assert seen[0].headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert b"grant_type=authorization_code" in seen[0].content
    assert "do-not-leak" not in str(captured.value)
    assert "single-use-code" not in str(captured.value)


async def test_targeted_member_lookup_does_not_list_members() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"roles": ["9007199254740993"]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = HttpDiscordMemberClient(bot_token="not-a-real-token", client=http_client)
        roles = await client.get_member_roles(11, 22)
    assert roles == (9007199254740993,)
    assert paths == ["/api/v10/guilds/11/members/22"]


async def test_targeted_member_lookup_defers_after_discord_rate_limit() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(429, headers={"Retry-After": "60"}, json={"retry_after": 60})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = HttpDiscordMemberClient(bot_token="not-a-real-token", client=http_client)
        with pytest.raises(DiscordOAuthError) as first:
            await client.get_member_roles(11, 22)
        with pytest.raises(DiscordOAuthError, match="rate_limit_deferred"):
            await client.get_member_roles(11, 22)
    assert first.value.status_code == 429
    assert paths == ["/api/v10/guilds/11/members/22"]
