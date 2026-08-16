import json
import logging

import pytest

from did.infrastructure.logging import (
    UNSTRUCTURED_EVENT_ID,
    EventId,
    JsonFormatter,
    bind_correlation_id,
    emit_event,
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


def test_json_formatter_adds_correlation_and_recursively_redacts_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord("did", logging.INFO, __file__, 1, "ignored", (), None)
    record.event_id = EventId.PROCESS_STARTED
    record.fields = {"nested": {"token": "sensitive-value"}, "guild_id": 42}
    token = bind_correlation_id("request-123")
    try:
        rendered = formatter.format(record)
    finally:
        reset_correlation_id(token)
    parsed = json.loads(rendered)
    assert parsed["correlation_id"] == "request-123"
    assert parsed["event"] == "process.started"
    assert parsed["fields"]["nested"]["token"] == "[REDACTED]"
    assert parsed["fields"]["guild_id"] == 42
    assert "sensitive-value" not in rendered


def test_unstructured_log_message_is_never_rendered() -> None:
    formatter = JsonFormatter()
    secret = "plain-dynamic-secret"
    record = logging.LogRecord(
        "did",
        logging.ERROR,
        __file__,
        1,
        f"failed with token {secret}",
        (),
        None,
    )

    rendered = formatter.format(record)

    assert json.loads(rendered)["event"] == UNSTRUCTURED_EVENT_ID
    assert secret not in rendered


def test_emit_event_rejects_unregistered_dynamic_identifier() -> None:
    logger = logging.getLogger("did.test")
    with pytest.raises(TypeError, match="registered EventId"):
        emit_event(logger, logging.INFO, "process.dynamic")  # type: ignore[arg-type]
