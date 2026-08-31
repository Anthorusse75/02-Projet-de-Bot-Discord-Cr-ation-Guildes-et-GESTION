import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_SENSITIVE_FRAGMENTS = (
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "database_url",
    "password",
    "private_key",
    "redis_url",
    "secret",
    "token",
)


class EventId(StrEnum):
    """Closed registry of static log event identifiers."""

    PROCESS_STARTED = "process.started"
    PROCESS_STOPPED = "process.stopped"
    AUTH_LOGIN_SUCCEEDED = "auth.login.succeeded"
    AUTH_LOGIN_DENIED = "auth.login.denied"
    AUTH_LOGOUT = "auth.logout"
    AUTH_GRANT_REVOKED = "auth.grant.revoked"
    AUTHORIZATION_DENIED = "authorization.denied"
    INSTALLATION_DETECTED = "installation.detected"
    INSTALLATION_BOOTSTRAPPED = "installation.bootstrapped"
    INSTALLATION_UNINSTALLED = "installation.uninstalled"
    RBAC_CHANGED = "rbac.changed"
    GATEWAY_DISPATCH_REJECTED = "gateway.dispatch.rejected"
    GATEWAY_GAP_DETECTED = "gateway.gap.detected"
    GATEWAY_NON_RESUMED = "gateway.non_resumed"
    DISCORD_WORKLOAD_HALTED = "discord.workload.halted"
    DISCORD_BACKPRESSURE = "discord.workload.backpressure"
    REDIS_CACHE_REBUILT = "redis.cache.rebuilt"
    OUTBOX_PUBLISH_FAILED = "outbox.publish.failed"
    STAGE08_POST_VERIFICATION_FAILED = "stage08.post_verification.failed"
    CAMPAIGN_SCHEDULE_EVALUATION_FAILED = "campaign.schedule.evaluation_failed"
    CAMPAIGN_SCHEDULER_TICK_FAILED = "campaign.scheduler.tick_failed"


UNSTRUCTURED_EVENT_ID = "logging.unstructured_rejected"


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
        event_id = getattr(record, "event_id", None)
        if not isinstance(event_id, EventId):
            event = UNSTRUCTURED_EVENT_ID
        else:
            event = event_id.value
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": event,
        }
        correlation_id = correlation_id_var.get()
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload["fields"] = redact(fields)
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def emit_event(
    logger: logging.Logger,
    level: int,
    event_id: EventId,
    *,
    fields: dict[str, Any] | None = None,
) -> None:
    """Emit a registered event; all dynamic values belong in recursively redacted fields."""

    if not isinstance(event_id, EventId):
        raise TypeError("event_id must be a registered EventId")
    logger.log(level, event_id.value, extra={"event_id": event_id, "fields": fields or {}})


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
