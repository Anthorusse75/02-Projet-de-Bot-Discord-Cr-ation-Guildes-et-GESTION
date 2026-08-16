import json
import logging

from did.infrastructure.logging import (
    JsonFormatter,
    bind_correlation_id,
    redact,
    reset_correlation_id,
)


def test_redaction_is_recursive() -> None:
    payload = {
        "guild_id": 42,
        "authorization": "Bot should-never-appear",
        "nested": {"database_url": "postgresql://secret"},
    }
    redacted = redact(payload)
    assert redacted["guild_id"] == 42
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["nested"]["database_url"] == "[REDACTED]"


def test_json_formatter_adds_correlation_without_secret() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord("did", logging.INFO, __file__, 1, "health_checked", (), None)
    record.fields = {"token": "sensitive-value", "guild_id": 42}
    token = bind_correlation_id("request-123")
    try:
        rendered = formatter.format(record)
    finally:
        reset_correlation_id(token)
    parsed = json.loads(rendered)
    assert parsed["correlation_id"] == "request-123"
    assert parsed["token"] == "[REDACTED]"
    assert "sensitive-value" not in rendered
