from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from did.domain.discord_runtime import (
    CHANNEL_OBFUSCATED_FLAG,
    EventEnvelope,
    EventOrigin,
    EventSource,
    GatewayContinuity,
)

SUPPORTED_DISPATCHES = frozenset(
    {
        "GUILD_CREATE",
        "GUILD_UPDATE",
        "GUILD_DELETE",
        "CHANNEL_CREATE",
        "CHANNEL_UPDATE",
        "CHANNEL_DELETE",
        "GUILD_ROLE_CREATE",
        "GUILD_ROLE_UPDATE",
        "GUILD_ROLE_DELETE",
        "GUILD_MEMBER_UPDATE",
    }
)
MAX_NORMALIZED_PAYLOAD_BYTES = 1_048_576


class GatewayContractError(ValueError):
    pass


def _snowflake(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise GatewayContractError(f"{field} must be a Discord snowflake")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise GatewayContractError(f"{field} must be a Discord snowflake") from exc
    if parsed <= 0 or parsed > 2**64 - 1:
        raise GatewayContractError(f"{field} must be a Discord snowflake")
    return parsed


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise GatewayContractError(f"{field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise GatewayContractError(f"{field} must be an integer") from exc
    if parsed < minimum:
        raise GatewayContractError(f"{field} must be >= {minimum}")
    return parsed


def _nullable_snowflake(value: object, field: str) -> int | None:
    return None if value is None else _snowflake(value, field)


def _normalize_overwrites(raw: object) -> list[dict[str, int]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise GatewayContractError("permission_overwrites must be an array")
    normalized: list[dict[str, int]] = []
    for overwrite in raw:
        if not isinstance(overwrite, dict):
            raise GatewayContractError("permission overwrite must be an object")
        target_type = _integer(overwrite.get("type"), "overwrite.type")
        if target_type not in (0, 1):
            raise GatewayContractError("overwrite.type must be 0 or 1")
        normalized.append(
            {
                "id": _snowflake(overwrite.get("id"), "overwrite.id"),
                "type": target_type,
                "allow": _integer(overwrite.get("allow", 0), "overwrite.allow"),
                "deny": _integer(overwrite.get("deny", 0), "overwrite.deny"),
            }
        )
    return normalized


def normalize_channel_payload(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise GatewayContractError("channel payload must be an object")
    flags = _integer(raw.get("flags", 0), "channel.flags")
    obfuscated = bool(flags & CHANNEL_OBFUSCATED_FLAG)
    position = _integer(raw.get("position", 0), "channel.position")
    payload: dict[str, Any] = {
        "channel_id": _snowflake(raw.get("id"), "channel.id"),
        "type": _integer(raw.get("type"), "channel.type"),
        "position": position,
        "parent_id": _nullable_snowflake(raw.get("parent_id"), "channel.parent_id"),
        "flags": flags,
        "is_obfuscated": obfuscated,
        "permission_overwrites": _normalize_overwrites(raw.get("permission_overwrites")),
    }
    if obfuscated:
        payload.update({"name": None, "topic": None, "nsfw": None})
    else:
        name = raw.get("name")
        topic = raw.get("topic")
        nsfw = raw.get("nsfw")
        if name is not None and not isinstance(name, str):
            raise GatewayContractError("channel.name must be a string or null")
        if topic is not None and not isinstance(topic, str):
            raise GatewayContractError("channel.topic must be a string or null")
        if nsfw is not None and not isinstance(nsfw, bool):
            raise GatewayContractError("channel.nsfw must be a boolean or null")
        payload.update({"name": name, "topic": topic, "nsfw": nsfw})
    return payload


def normalize_role_payload(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise GatewayContractError("role payload must be an object")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise GatewayContractError("role.name must be a non-empty string")
    return {
        "role_id": _snowflake(raw.get("id"), "role.id"),
        "name": name,
        "position": _integer(raw.get("position", 0), "role.position"),
        "permissions": _integer(raw.get("permissions", 0), "role.permissions"),
        "managed": bool(raw.get("managed", False)),
        "color": _integer(
            raw.get(
                "color",
                raw.get("colors", {}).get("primary_color", 0)
                if isinstance(raw.get("colors"), dict)
                else 0,
            ),
            "role.color",
        ),
        "hoist": bool(raw.get("hoist", False)),
        "mentionable": bool(raw.get("mentionable", False)),
    }


def _guild_id(event_type: str, data: dict[str, Any]) -> int:
    if event_type.startswith("GUILD_") and event_type not in {
        "GUILD_ROLE_CREATE",
        "GUILD_ROLE_UPDATE",
        "GUILD_ROLE_DELETE",
        "GUILD_MEMBER_UPDATE",
    }:
        return _snowflake(data.get("id"), "guild.id")
    return _snowflake(data.get("guild_id"), "guild_id")


def _normalized_payload(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    if event_type in {"CHANNEL_CREATE", "CHANNEL_UPDATE", "CHANNEL_DELETE"}:
        return normalize_channel_payload(data)
    if event_type in {"GUILD_ROLE_CREATE", "GUILD_ROLE_UPDATE"}:
        return normalize_role_payload(data.get("role"))
    if event_type == "GUILD_ROLE_DELETE":
        return {"role_id": _snowflake(data.get("role_id"), "role_id")}
    if event_type == "GUILD_MEMBER_UPDATE":
        user = data.get("user")
        if not isinstance(user, dict):
            raise GatewayContractError("member.user must be an object")
        roles = data.get("roles")
        if not isinstance(roles, list):
            raise GatewayContractError("member.roles must be an array")
        return {
            "discord_user_id": _snowflake(user.get("id"), "member.user.id"),
            "role_ids": [_snowflake(role_id, "member.roles[]") for role_id in roles],
        }
    if event_type == "GUILD_CREATE":
        channels = data.get("channels", [])
        roles = data.get("roles", [])
        if not isinstance(channels, list) or not isinstance(roles, list):
            raise GatewayContractError("GUILD_CREATE channels and roles must be arrays")
        return {
            "name": str(data.get("name", "unknown"))[:100],
            "owner_id": _nullable_snowflake(data.get("owner_id"), "guild.owner_id"),
            "unavailable": bool(data.get("unavailable", False)),
            "channels": [normalize_channel_payload(channel) for channel in channels],
            "roles": [normalize_role_payload(role) for role in roles],
        }
    if event_type == "GUILD_UPDATE":
        name = data.get("name")
        return {
            "name": name if isinstance(name, str) else None,
            "owner_id": _nullable_snowflake(data.get("owner_id"), "guild.owner_id"),
        }
    if event_type == "GUILD_DELETE":
        return {"unavailable": bool(data.get("unavailable", False))}
    raise GatewayContractError(f"unsupported Gateway dispatch: {event_type}")


def normalize_gateway_dispatch(
    packet: object,
    *,
    discord_session_id: str,
    received_at: datetime | None = None,
) -> EventEnvelope | None:
    if not isinstance(packet, dict):
        raise GatewayContractError("Gateway packet must be an object")
    if packet.get("op") != 0:
        return None
    event_type = packet.get("t")
    if not isinstance(event_type, str):
        raise GatewayContractError("dispatch event name must be a string")
    if event_type not in SUPPORTED_DISPATCHES:
        return None
    sequence = packet.get("s")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise GatewayContractError("dispatch sequence must be a non-negative integer")
    data = packet.get("d")
    if not isinstance(data, dict):
        raise GatewayContractError("dispatch data must be an object")
    guild_id = _guild_id(event_type, data)
    payload = _normalized_payload(event_type, data)
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    if len(encoded) > MAX_NORMALIZED_PAYLOAD_BYTES:
        raise GatewayContractError("normalized Gateway payload exceeds the durable bound")
    event_id = uuid4()
    return EventEnvelope(
        event_id=event_id,
        guild_id=guild_id,
        event_type=event_type,
        discord_sequence=sequence,
        discord_session_id=discord_session_id,
        occurred_at=None,
        received_at=received_at or datetime.now(UTC),
        correlation_id=event_id,
        causation_id=None,
        schema_version=1,
        payload=payload,
        source=EventSource.GATEWAY,
        origin=EventOrigin.DISCORD_EXTERNAL,
    )


@dataclass(slots=True)
class GatewaySessionTracker:
    session_id: str | None = None
    last_sequence: int | None = None
    continuity: GatewayContinuity = GatewayContinuity.DISCONNECTED

    def ready(self, session_id: str) -> GatewayContinuity:
        if not session_id:
            raise GatewayContractError("READY session_id must be present")
        previous = self.session_id
        self.session_id = session_id
        self.last_sequence = None
        self.continuity = (
            GatewayContinuity.CONNECTED if previous is None else GatewayContinuity.NON_RESUMED
        )
        return self.continuity

    def resumed(self, session_id: str) -> GatewayContinuity:
        if self.session_id != session_id:
            raise GatewayContractError("RESUMED session does not match the active session")
        self.continuity = GatewayContinuity.RESUMED
        return self.continuity

    def observe_sequence(self, sequence: int) -> GatewayContinuity:
        if sequence < 0:
            raise GatewayContractError("Gateway sequence cannot be negative")
        if self.last_sequence is not None and sequence > self.last_sequence + 1:
            self.continuity = GatewayContinuity.GAP_DETECTED
        self.last_sequence = max(sequence, self.last_sequence or sequence)
        return self.continuity

    def disconnected(self) -> None:
        self.continuity = GatewayContinuity.DISCONNECTED
