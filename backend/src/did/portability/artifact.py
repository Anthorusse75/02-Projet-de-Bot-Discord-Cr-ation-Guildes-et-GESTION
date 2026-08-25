from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

ARTIFACT_SCHEMA_VERSION = "did-portable-artifact-v1"
FILE_SCHEMA_VERSION = "did-portable-file-v1"
MAX_RAW_FILE_BYTES = 2_000_000
MAX_RESOURCES = 1_000
MAX_DEPENDENCIES = 5_000
MAX_STRING_BYTES = 16_384
MAX_NESTING_DEPTH = 12

_FORBIDDEN_OPERATIONAL_KEYS = frozenset(
    {
        "bot_token",
        "oauth_access_token",
        "oauth_refresh_token",
        "webhook_token",
        "webhook_url",
        "url",
        "uri",
        "provider_secret",
        "translation_provider_secret",
        "session",
        "cookie",
        "capability",
        "capabilities",
        "discord_user_id",
        "source_role_id",
        "source_channel_id",
        "source_category_id",
        "destination_resource_id",
        "discord_role_id",
        "discord_channel_id",
        "bindings",
        "principal_bindings",
        "user_bindings",
        "role_bindings",
        "owner_id",
        "message_id",
    }
)


class ArtifactType(StrEnum):
    CHANNEL = "CHANNEL"
    CATEGORY = "CATEGORY"
    LOGICAL_GROUP = "LOGICAL_GROUP"
    GUILD_CONFIG = "GUILD_CONFIG"
    CUSTOM_BUNDLE = "CUSTOM_BUNDLE"


class PortableResourceType(StrEnum):
    ROLE = "ROLE"
    CATEGORY = "CATEGORY"
    CHANNEL = "CHANNEL"
    OVERWRITE = "OVERWRITE"
    LOGICAL_GROUP = "LOGICAL_GROUP"
    POLICY = "POLICY"
    SYSTEM_PRINCIPAL = "SYSTEM_PRINCIPAL"
    PRINCIPAL_REQUIREMENT = "PRINCIPAL_REQUIREMENT"
    BOT_REFERENCE = "BOT_REFERENCE"
    WEBHOOK_REFERENCE = "WEBHOOK_REFERENCE"


PORTABLE_ATTRIBUTE_SCHEMA_VERSION = "did-portable-attributes-v2"

_ATTRIBUTE_KEYS: dict[PortableResourceType, frozenset[str]] = {
    PortableResourceType.ROLE: frozenset(
        {"name", "permissions", "color", "hoist", "mentionable", "position", "managed"}
    ),
    PortableResourceType.CATEGORY: frozenset({"name", "position"}),
    PortableResourceType.CHANNEL: frozenset(
        {
            "name",
            "type",
            "position",
            "topic",
            "nsfw",
            "flags",
            "bitrate",
            "user_limit",
            "rate_limit_per_user",
            "default_auto_archive_duration",
        }
    ),
    PortableResourceType.OVERWRITE: frozenset({"target_type", "allow", "deny"}),
    PortableResourceType.LOGICAL_GROUP: frozenset({"name", "slug", "description"}),
    PortableResourceType.POLICY: frozenset({"name", "rules"}),
    PortableResourceType.SYSTEM_PRINCIPAL: frozenset({"kind"}),
    PortableResourceType.PRINCIPAL_REQUIREMENT: frozenset({"kind", "name", "source_binding"}),
    PortableResourceType.BOT_REFERENCE: frozenset({"name"}),
    PortableResourceType.WEBHOOK_REFERENCE: frozenset({"name"}),
}


def validate_portable_attributes(
    resource_type: PortableResourceType, attributes: dict[str, Any]
) -> None:
    """Fail closed on fields that are not part of the versioned portable contract."""

    unknown = set(attributes) - _ATTRIBUTE_KEYS[resource_type]
    if unknown:
        raise ValueError(
            "unsupported portable attributes for "
            f"{resource_type.value}: {','.join(sorted(unknown))}"
        )
    if resource_type is PortableResourceType.CHANNEL:
        channel_type = attributes.get("type")
        if not isinstance(channel_type, int) or isinstance(channel_type, bool):
            raise ValueError("portable channel type must be an integer")
        if channel_type not in {0, 2, 5, 13, 14, 15, 16}:
            raise ValueError("unsupported portable channel type")
        text_only = {"rate_limit_per_user", "default_auto_archive_duration"}
        voice_only = {"bitrate", "user_limit"}
        if channel_type not in {0, 5} and text_only & set(attributes):
            raise ValueError("text-only portable attributes used by another channel type")
        if channel_type not in {2, 13} and voice_only & set(attributes):
            raise ValueError("voice-only portable attributes used by another channel type")


@dataclass(frozen=True, slots=True)
class FrozenObject:
    items: tuple[tuple[str, JsonValue], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class FrozenArray:
    items: tuple[JsonValue, ...] = field(default_factory=tuple)


type JsonValue = bool | int | str | FrozenObject | FrozenArray | None


def _freeze(value: Any, *, depth: int = 0) -> JsonValue:
    if depth > MAX_NESTING_DEPTH:
        raise ValueError("portable value exceeds maximum nesting depth")
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_STRING_BYTES:
            raise ValueError("portable string exceeds maximum size")
        return value
    if isinstance(value, list | tuple):
        if len(value) > MAX_RESOURCES:
            raise ValueError("portable array exceeds maximum size")
        return FrozenArray(tuple(_freeze(item, depth=depth + 1) for item in value))
    if isinstance(value, dict):
        if len(value) > 256 or not all(isinstance(key, str) for key in value):
            raise ValueError("portable object keys are invalid or excessive")
        return FrozenObject(
            tuple(sorted((key, _freeze(item, depth=depth + 1)) for key, item in value.items()))
        )
    raise ValueError(f"unsupported portable value type: {type(value).__name__}")


def _thaw(value: JsonValue) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, FrozenObject):
        return {key: _thaw(item) for key, item in value.items}
    return [_thaw(item) for item in value.items]


def _validate_logical_key(value: str) -> None:
    if not value or len(value) > 256 or value != value.strip():
        raise ValueError("logical key must be present, trimmed and bounded")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-")
    if any(character not in allowed for character in value):
        raise ValueError("logical key contains unsupported characters")


def _walk_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.lower()
            if normalized in _FORBIDDEN_OPERATIONAL_KEYS or normalized.endswith("_token"):
                raise ValueError(f"forbidden portable field: {key}")
            _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            _walk_keys(item)


@dataclass(frozen=True, slots=True)
class PortableProvenance:
    source_guild_id: str | None = None
    source_resource_ids: tuple[str, ...] = field(default_factory=tuple)
    assertion: str = "NON_AUTHORITATIVE"

    def __post_init__(self) -> None:
        if self.assertion != "NON_AUTHORITATIVE":
            raise ValueError("portable provenance is always non-authoritative")
        if self.source_guild_id is not None and (
            not self.source_guild_id.isdecimal() or int(self.source_guild_id) <= 0
        ):
            raise ValueError("source_guild_id provenance must be a positive decimal ID")
        if len(self.source_resource_ids) > MAX_RESOURCES or any(
            not value.isdecimal() or int(value) <= 0 for value in self.source_resource_ids
        ):
            raise ValueError("source resource provenance is invalid")
        object.__setattr__(
            self, "source_resource_ids", tuple(sorted(set(self.source_resource_ids)))
        )


@dataclass(frozen=True, slots=True)
class PortableResource:
    logical_key: str
    resource_type: PortableResourceType
    attributes: JsonValue = field(default_factory=FrozenObject)

    def __post_init__(self) -> None:
        _validate_logical_key(self.logical_key)
        thawed = _thaw(self.attributes)
        if not isinstance(thawed, dict):
            raise ValueError("portable resource attributes must be an object")
        _walk_keys(thawed)
        validate_portable_attributes(self.resource_type, thawed)

    @classmethod
    def build(
        cls,
        logical_key: str,
        resource_type: PortableResourceType,
        attributes: dict[str, Any] | None = None,
    ) -> PortableResource:
        return cls(logical_key, resource_type, _freeze(attributes or {}))

    def attribute_map(self) -> dict[str, Any]:
        result = _thaw(self.attributes)
        assert isinstance(result, dict)
        return result


@dataclass(frozen=True, slots=True, order=True)
class PortableDependency:
    source: str
    target: str
    relation: str
    required: bool = True

    def __post_init__(self) -> None:
        _validate_logical_key(self.source)
        _validate_logical_key(self.target)
        _validate_logical_key(self.relation)
        if self.source == self.target:
            raise ValueError("portable dependency cannot be a self-edge")


@dataclass(frozen=True, slots=True)
class PortableArtifact:
    artifact_type: ArtifactType
    resources: tuple[PortableResource, ...]
    dependencies: tuple[PortableDependency, ...] = field(default_factory=tuple)
    roots: tuple[str, ...] = field(default_factory=tuple)
    provenance: PortableProvenance = field(default_factory=PortableProvenance)
    schema_version: str = ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ARTIFACT_SCHEMA_VERSION:
            raise ValueError("unsupported portable artifact schema")
        if not 1 <= len(self.resources) <= MAX_RESOURCES:
            raise ValueError("portable artifact resource count is invalid")
        if len(self.dependencies) > MAX_DEPENDENCIES:
            raise ValueError("portable artifact dependency count is excessive")
        ordered_resources = tuple(sorted(self.resources, key=lambda item: item.logical_key))
        keys = {resource.logical_key for resource in ordered_resources}
        if len(keys) != len(ordered_resources):
            raise ValueError("portable logical keys must be unique")
        ordered_dependencies = tuple(sorted(set(self.dependencies)))
        for dependency in ordered_dependencies:
            if dependency.source not in keys or dependency.target not in keys:
                raise ValueError("portable dependency references an unknown resource")
        roots = tuple(sorted(set(self.roots)))
        if not roots or any(root not in keys for root in roots):
            raise ValueError("portable artifact roots must reference known resources")
        object.__setattr__(self, "resources", ordered_resources)
        object.__setattr__(self, "dependencies", ordered_dependencies)
        object.__setattr__(self, "roots", roots)

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type.value,
            "resources": [
                {
                    "logical_key": resource.logical_key,
                    "resource_type": resource.resource_type.value,
                    "attributes": resource.attribute_map(),
                }
                for resource in self.resources
            ],
            "dependencies": [
                {
                    "source": dependency.source,
                    "target": dependency.target,
                    "relation": dependency.relation,
                    "required": dependency.required,
                }
                for dependency in self.dependencies
            ],
            "roots": list(self.roots),
            "provenance": {
                "source_guild_id": self.provenance.source_guild_id,
                "source_resource_ids": list(self.provenance.source_resource_ids),
                "assertion": self.provenance.assertion,
            },
        }

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.canonical_payload())).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def artifact_to_bytes(artifact: PortableArtifact) -> bytes:
    envelope = {
        "file_schema_version": FILE_SCHEMA_VERSION,
        "content_hash": artifact.content_hash,
        "artifact": artifact.canonical_payload(),
    }
    encoded = _canonical_json(envelope)
    if len(encoded) > MAX_RAW_FILE_BYTES:
        raise ValueError("portable file exceeds maximum raw size")
    return encoded


def artifact_from_bytes(raw: bytes) -> PortableArtifact:
    if not raw or len(raw) > MAX_RAW_FILE_BYTES:
        raise ValueError("portable file size is invalid")
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("portable file is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict) or set(value) != {
        "file_schema_version",
        "content_hash",
        "artifact",
    }:
        raise ValueError("portable file envelope is invalid")
    if value["file_schema_version"] != FILE_SCHEMA_VERSION:
        raise ValueError("unsupported portable file schema")
    artifact_value = value["artifact"]
    artifact = artifact_from_dict(artifact_value)
    claimed = value["content_hash"]
    if not isinstance(claimed, str) or claimed != artifact.content_hash:
        raise ValueError("portable artifact content hash mismatch")
    return artifact


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate portable field: {key}")
        result[key] = value
    return result


def artifact_from_dict(value: Any) -> PortableArtifact:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "artifact_type",
        "resources",
        "dependencies",
        "roots",
        "provenance",
    }:
        raise ValueError("portable artifact fields are invalid")
    if value["schema_version"] != ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported portable artifact schema")
    raw_resources = value["resources"]
    raw_dependencies = value["dependencies"]
    raw_roots = value["roots"]
    provenance = value["provenance"]
    if not isinstance(raw_resources, list) or not isinstance(raw_dependencies, list):
        raise ValueError("portable resources/dependencies must be arrays")
    if not isinstance(raw_roots, list) or not all(isinstance(item, str) for item in raw_roots):
        raise ValueError("portable roots must be strings")
    if not isinstance(provenance, dict) or set(provenance) != {
        "source_guild_id",
        "source_resource_ids",
        "assertion",
    }:
        raise ValueError("portable provenance fields are invalid")
    resources: list[PortableResource] = []
    for item in raw_resources:
        if not isinstance(item, dict) or set(item) != {
            "logical_key",
            "resource_type",
            "attributes",
        }:
            raise ValueError("portable resource fields are invalid")
        if not isinstance(item["logical_key"], str) or not isinstance(item["attributes"], dict):
            raise ValueError("portable resource shape is invalid")
        resources.append(
            PortableResource.build(
                item["logical_key"],
                PortableResourceType(item["resource_type"]),
                item["attributes"],
            )
        )
    dependencies: list[PortableDependency] = []
    for item in raw_dependencies:
        if not isinstance(item, dict) or set(item) != {
            "source",
            "target",
            "relation",
            "required",
        }:
            raise ValueError("portable dependency fields are invalid")
        if not all(isinstance(item[key], str) for key in ("source", "target", "relation")):
            raise ValueError("portable dependency shape is invalid")
        if not isinstance(item["required"], bool):
            raise ValueError("portable dependency required flag is invalid")
        dependencies.append(
            PortableDependency(item["source"], item["target"], item["relation"], item["required"])
        )
    source_ids = provenance["source_resource_ids"]
    if not isinstance(source_ids, list) or not all(isinstance(item, str) for item in source_ids):
        raise ValueError("portable provenance resource IDs are invalid")
    source_guild_id = provenance["source_guild_id"]
    if source_guild_id is not None and not isinstance(source_guild_id, str):
        raise ValueError("portable provenance Guild ID is invalid")
    if not isinstance(provenance["assertion"], str):
        raise ValueError("portable provenance assertion is invalid")
    return PortableArtifact(
        ArtifactType(value["artifact_type"]),
        tuple(resources),
        tuple(dependencies),
        tuple(raw_roots),
        PortableProvenance(source_guild_id, tuple(source_ids), provenance["assertion"]),
        str(value["schema_version"]),
    )
