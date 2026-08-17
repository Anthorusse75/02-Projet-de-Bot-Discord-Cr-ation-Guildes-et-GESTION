from typing import Any

import discord
import pytest

from did.domain.discord_runtime import DiscordErrorKind
from did.infrastructure.discord import DiscordPyStructureAdapter


class FakeResponse:
    def __init__(self, status: int, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.reason = "contract fixture"
        self.headers = headers or {}


def http_error(status: int, headers: dict[str, str] | None = None) -> discord.HTTPException:
    return discord.HTTPException(FakeResponse(status, headers), {"code": 0, "message": "fixture"})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("error", "kind", "retryable"),
    [
        (discord.Forbidden(FakeResponse(403), "forbidden"), DiscordErrorKind.FORBIDDEN, False),  # type: ignore[arg-type]
        (discord.NotFound(FakeResponse(404), "missing"), DiscordErrorKind.NOT_FOUND, False),  # type: ignore[arg-type]
        (http_error(401), DiscordErrorKind.UNAUTHORIZED, False),
        (http_error(400), DiscordErrorKind.INVALID_REQUEST, False),
        (http_error(503), DiscordErrorKind.TRANSIENT, True),
        (OSError("network"), DiscordErrorKind.TRANSIENT, True),
    ],
)
def test_discord_errors_are_normalized_without_blind_retry(
    error: Exception, kind: DiscordErrorKind, retryable: bool
) -> None:
    translated = DiscordPyStructureAdapter._translate(error)
    assert translated.failure.kind is kind
    assert translated.failure.retryable is retryable


def test_429_preserves_retry_after_and_global_contract_for_library_limiter() -> None:
    translated = DiscordPyStructureAdapter._translate(
        http_error(429, {"Retry-After": "2.75", "X-RateLimit-Global": "true"})
    )
    assert translated.failure.kind is DiscordErrorKind.RATE_LIMITED
    assert translated.failure.retry_after_seconds == 2.75
    assert translated.failure.global_rate_limit is True
    assert translated.failure.retryable is True


def test_adapter_contract_does_not_expose_raw_http_exception() -> None:
    translated: Any = DiscordPyStructureAdapter._translate(http_error(500))
    assert type(translated).__name__ == "DiscordAdapterError"
    assert not isinstance(translated, discord.HTTPException)
