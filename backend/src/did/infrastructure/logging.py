import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_SENSITIVE_FRAGMENTS = (
    "authorization",
    "cookie",
    "database_url",
    "password",
    "redis_url",
    "secret",
    "token",
)


def redact(value: Any, *, key: str = "") -> Any:
    if any(fragment in key.lower() for fragment in _SENSITIVE_FRAGMENTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        correlation_id = correlation_id_var.get()
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(redact(fields))
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


def bind_correlation_id(correlation_id: str) -> Token[str | None]:
    return correlation_id_var.set(correlation_id)


def reset_correlation_id(token: Token[str | None]) -> None:
    correlation_id_var.reset(token)
