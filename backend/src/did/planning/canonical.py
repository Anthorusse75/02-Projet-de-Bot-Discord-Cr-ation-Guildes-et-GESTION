from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any
from uuid import UUID

from did.planning.models import (
    DesiredNode,
    DesiredStateGraph,
    FrozenJsonArray,
    FrozenJsonObject,
    FrozenJsonValue,
)


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, DesiredStateGraph):
        return {
            "schema_version": value.schema_version,
            "guild_id": str(value.guild_id),
            "nodes": [_json_value(node) for node in value.nodes],
        }
    if isinstance(value, DesiredNode):
        return {
            "logical_key": value.logical_key,
            "resource_type": value.resource_type.value,
            "discord_id": str(value.discord_id) if value.discord_id is not None else None,
            "symbol": value.symbol,
            "presence": value.presence.value,
            "properties": _frozen_value(value.properties),
            "relations": [
                {"name": name, "kind": reference.kind.value, "value": reference.value}
                for name, reference in value.relations
            ],
        }
    if isinstance(value, FrozenJsonObject | FrozenJsonArray):
        return _frozen_value(value)
    if is_dataclass(value):
        return _json_value(asdict(value))  # type: ignore[arg-type]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value


def _frozen_value(value: FrozenJsonValue) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, FrozenJsonObject):
        return {key: _frozen_value(item) for key, item in value.items}
    if isinstance(value, FrozenJsonArray):
        return [_frozen_value(item) for item in value.items]
    raise TypeError("invalid frozen JSON value")


def canonical_json(value: Any) -> str:
    """Versioned UTF-8 JSON; never pickle/repr and never insertion-order dependent."""
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
