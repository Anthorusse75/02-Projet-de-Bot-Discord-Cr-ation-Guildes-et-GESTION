from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, cast
from uuid import UUID

import aiohttp
import discord

from did.domain.discord_runtime import DiscordErrorKind, DiscordFailure
from did.infrastructure.discord.adapter import DiscordAdapterError, DiscordPyStructureAdapter
from did.planning.canonical import canonical_hash
from did.planning.models import OperationType


class RecoveryOutcome(StrEnum):
    PROVED_CREATED = "PROVED_CREATED"
    PROVED_APPLIED = "PROVED_APPLIED"
    PROVED_ABSENT = "PROVED_ABSENT"
    AMBIGUOUS = "AMBIGUOUS"


class PreconditionOutcome(StrEnum):
    SATISFIED = "SATISFIED"
    CHANGED = "CHANGED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MutationResult:
    discord_status: int
    payload: dict[str, Any]
    audit_reason_fingerprint: str


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    outcome: RecoveryOutcome
    payload: dict[str, Any] | None = None


class MutableDiscordError(DiscordAdapterError):
    def __init__(self, failure: DiscordFailure, *, outcome_unknown: bool) -> None:
        self.outcome_unknown = outcome_unknown
        super().__init__(failure)


class UnsafeRoleMutation(ValueError):
    """Adapter-level fence for a role target Discord never permits."""


class MutableDiscordPort(Protocol):
    async def check_preconditions(
        self,
        *,
        guild_id: int,
        operation_type: OperationType,
        payload: dict[str, Any],
        preconditions: dict[str, Any],
    ) -> PreconditionOutcome: ...

    async def execute(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        operation_id: UUID,
        correlation_id: UUID,
        operation_type: OperationType,
        payload: dict[str, Any],
    ) -> MutationResult: ...

    async def recover(
        self,
        *,
        guild_id: int,
        operation_type: OperationType,
        payload: dict[str, Any],
        before_payload: dict[str, Any],
    ) -> RecoveryResult: ...

    async def verify(
        self,
        *,
        guild_id: int,
        operation_type: OperationType,
        payload: dict[str, Any],
        result_payload: dict[str, Any] | None,
    ) -> bool: ...


def audit_reason(plan_id: UUID, operation_id: UUID, correlation_id: UUID) -> tuple[str, str]:
    reason = f"DID plan={plan_id} op={operation_id} corr={correlation_id}"
    encoded_length = len(reason.encode("utf-8"))
    if encoded_length > 512:
        raise ValueError("Discord audit reason exceeds 512 UTF-8 bytes")
    return reason, hashlib.sha256(reason.encode()).hexdigest()


class DiscordPyMutableAdapter:
    """Closed structural mutation adapter; discord.py owns route buckets and 429s."""

    def __init__(self, client: discord.Client) -> None:
        self._client = client
        self._reads = DiscordPyStructureAdapter(client)

    async def check_preconditions(
        self,
        *,
        guild_id: int,
        operation_type: OperationType,
        payload: dict[str, Any],
        preconditions: dict[str, Any],
    ) -> PreconditionOutcome:
        if preconditions.get("schema_version") != "did-operation-precondition-v1":
            return PreconditionOutcome.UNKNOWN
        role_operations = {
            OperationType.CREATE_ROLE,
            OperationType.UPDATE_ROLE,
            OperationType.DELETE_ROLE,
            OperationType.REORDER_ROLES,
        }
        if operation_type in {
            OperationType.ADD_MEMBER_ROLE,
            OperationType.REMOVE_MEMBER_ROLE,
        }:
            return await self._member_role_precondition(
                guild_id=guild_id,
                operation_type=operation_type,
                payload=payload,
                preconditions=preconditions,
            )
        resources = (
            await self._reads.fetch_roles(guild_id)
            if operation_type in role_operations
            else await self._reads.fetch_channels(guild_id)
        )
        if operation_type in {
            OperationType.UPSERT_OVERWRITE,
            OperationType.DELETE_OVERWRITE,
        }:
            return self._overwrite_precondition(resources, payload, preconditions)
        before = preconditions.get("before")
        if not isinstance(before, dict):
            return PreconditionOutcome.UNKNOWN
        if operation_type in {
            OperationType.REORDER_ROLES,
            OperationType.MOVE_OR_REORDER_CHANNELS,
        }:
            expected_items = before.get("items")
            if not isinstance(expected_items, list):
                return PreconditionOutcome.UNKNOWN
            by_id = {
                int(item.get("id", item.get("role_id", item.get("channel_id", 0)))): item
                for item in resources
            }
            for item in expected_items:
                if not isinstance(item, dict) or item.get("id") is None:
                    return PreconditionOutcome.UNKNOWN
                current = by_id.get(int(item["id"]))
                if current is None:
                    return (
                        PreconditionOutcome.CHANGED
                        if operation_type is OperationType.REORDER_ROLES
                        else PreconditionOutcome.UNKNOWN
                    )
                if not self._matches(current, item):
                    return PreconditionOutcome.CHANGED
            if operation_type is OperationType.REORDER_ROLES:
                return await self._role_hierarchy_precondition(
                    guild_id=guild_id,
                    operation_type=operation_type,
                    payload=payload,
                    roles=resources,
                )
            return PreconditionOutcome.SATISFIED
        if operation_type in {OperationType.CREATE_ROLE, OperationType.CREATE_CHANNEL}:
            identity = preconditions.get("identity")
            if not isinstance(identity, dict) or not identity:
                return PreconditionOutcome.UNKNOWN
            candidates = [item for item in resources if self._matches(item, identity)]
            return PreconditionOutcome.CHANGED if candidates else PreconditionOutcome.SATISFIED
        resource_id = payload.get("id") or preconditions.get("resource_id")
        if resource_id is None:
            return PreconditionOutcome.UNKNOWN
        current = next(
            (
                item
                for item in resources
                if int(item.get("id", item.get("role_id", item.get("channel_id", 0))))
                == int(resource_id)
            ),
            None,
        )
        if current is None:
            return (
                PreconditionOutcome.CHANGED
                if operation_type in {OperationType.UPDATE_ROLE, OperationType.DELETE_ROLE}
                else PreconditionOutcome.UNKNOWN
            )
        if not self._matches(current, before):
            return PreconditionOutcome.CHANGED
        if operation_type in {OperationType.UPDATE_ROLE, OperationType.DELETE_ROLE}:
            return await self._role_hierarchy_precondition(
                guild_id=guild_id,
                operation_type=operation_type,
                payload=payload,
                roles=resources,
            )
        return PreconditionOutcome.SATISFIED

    async def _member_role_precondition(
        self,
        *,
        guild_id: int,
        operation_type: OperationType,
        payload: dict[str, Any],
        preconditions: dict[str, Any],
    ) -> PreconditionOutcome:
        try:
            member_id = self._required_id(payload, "member_id", fallback="id")
            role_id = self._required_id(payload, "role_id")
            member = await self._reads.fetch_member(guild_id, member_id)
            roles = await self._reads.fetch_roles(guild_id)
        except Exception:
            return PreconditionOutcome.UNKNOWN
        before = preconditions.get("before")
        role_ids = member.get("role_ids")
        if not isinstance(before, dict) or not isinstance(role_ids, list):
            return PreconditionOutcome.UNKNOWN
        if (role_id in {int(value) for value in role_ids}) != bool(before.get("assigned", False)):
            return PreconditionOutcome.CHANGED
        hierarchy_payload = {**payload, "id": role_id}
        return await self._role_hierarchy_precondition(
            guild_id=guild_id,
            operation_type=operation_type,
            payload=hierarchy_payload,
            roles=roles,
        )

    async def _role_hierarchy_precondition(
        self,
        *,
        guild_id: int,
        operation_type: OperationType,
        payload: dict[str, Any],
        roles: list[dict[str, Any]],
    ) -> PreconditionOutcome:
        if operation_type is OperationType.REORDER_ROLES:
            raw_targets = payload.get("items")
            if not isinstance(raw_targets, list) or not raw_targets:
                return PreconditionOutcome.UNKNOWN
        else:
            raw_targets = [payload]

        by_id = {
            int(item.get("id", item.get("role_id", 0))): item
            for item in roles
            if int(item.get("id", item.get("role_id", 0))) > 0
        }
        targets: list[dict[str, Any]] = []
        for raw_target in raw_targets:
            if not isinstance(raw_target, dict) or raw_target.get("id") is None:
                return PreconditionOutcome.UNKNOWN
            target_id = int(raw_target["id"])
            target = by_id.get(target_id)
            if target is None:
                return PreconditionOutcome.CHANGED
            if bool(target.get("managed", False)):
                return PreconditionOutcome.CHANGED
            if target_id == guild_id:
                if operation_type in {OperationType.DELETE_ROLE, OperationType.REORDER_ROLES}:
                    return PreconditionOutcome.CHANGED
                continue
            targets.append(target)

        bot_user = getattr(self._client, "user", None)
        bot_user_id = getattr(bot_user, "id", None)
        if bot_user_id is None:
            return PreconditionOutcome.UNKNOWN
        try:
            member = await self._reads.fetch_member(guild_id, int(bot_user_id))
        except Exception:
            return PreconditionOutcome.UNKNOWN
        role_ids = member.get("role_ids")
        if not isinstance(role_ids, list) or not role_ids:
            return PreconditionOutcome.UNKNOWN
        bot_roles = [by_id.get(int(role_id)) for role_id in role_ids]
        if any(role is None for role in bot_roles):
            return PreconditionOutcome.UNKNOWN
        highest = max(
            (role for role in bot_roles if role is not None),
            key=lambda role: int(role.get("position", -1)),
            default=None,
        )
        if highest is None:
            return PreconditionOutcome.UNKNOWN
        highest_id = int(highest.get("id", highest.get("role_id", 0)))
        highest_position = int(highest.get("position", -1))
        if highest_id <= 0 or highest_position < 0:
            return PreconditionOutcome.UNKNOWN
        if any(
            int(target.get("id", target.get("role_id", 0))) == highest_id
            or int(target.get("position", -1)) >= highest_position
            for target in targets
        ):
            return PreconditionOutcome.CHANGED
        if operation_type is OperationType.REORDER_ROLES and any(
            raw_target.get("position") is None or int(raw_target["position"]) >= highest_position
            for raw_target in raw_targets
        ):
            return PreconditionOutcome.CHANGED
        return PreconditionOutcome.SATISFIED

    @classmethod
    def _overwrite_precondition(
        cls,
        channels: list[dict[str, Any]],
        payload: dict[str, Any],
        preconditions: dict[str, Any],
    ) -> PreconditionOutcome:
        try:
            channel_id = cls._required_id(payload, "channel_id")
            target_id = cls._required_id(payload, "subject_id", fallback="target_id")
        except ValueError:
            return PreconditionOutcome.UNKNOWN
        channel = next(
            (item for item in channels if int(item.get("channel_id", 0)) == channel_id), None
        )
        if channel is None:
            return PreconditionOutcome.UNKNOWN
        target_type = int(payload.get("target_type", 0))
        current = next(
            (
                item
                for item in channel.get("permission_overwrites", [])
                if int(item.get("id", 0)) == target_id and int(item.get("type", 0)) == target_type
            ),
            None,
        )
        before = preconditions.get("before")
        if not isinstance(before, dict):
            return PreconditionOutcome.UNKNOWN
        if not before:
            return PreconditionOutcome.SATISFIED if current is None else PreconditionOutcome.CHANGED
        comparable_before = {
            key: value for key, value in before.items() if key not in {"channel_id", "subject_id"}
        }
        return (
            PreconditionOutcome.SATISFIED
            if current is not None and cls._matches(current, comparable_before)
            else PreconditionOutcome.CHANGED
        )

    async def execute(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        operation_id: UUID,
        correlation_id: UUID,
        operation_type: OperationType,
        payload: dict[str, Any],
    ) -> MutationResult:
        reason, reason_fingerprint = audit_reason(plan_id, operation_id, correlation_id)
        http = self._client.http
        try:
            result, status_code = await self._dispatch(
                http, guild_id, operation_type, dict(payload), reason
            )
        except Exception as exc:
            raise self._translate_mutation(exc) from exc
        return MutationResult(status_code, result, reason_fingerprint)

    async def _dispatch(
        self,
        http: discord.http.HTTPClient,
        guild_id: int,
        operation_type: OperationType,
        payload: dict[str, Any],
        reason: str,
    ) -> tuple[dict[str, Any], int]:
        if operation_type is OperationType.CREATE_ROLE:
            fields = self._only(payload, {"name", "permissions", "color", "hoist", "mentionable"})
            if "permissions" in fields:
                fields["permissions"] = str(fields["permissions"])
            role_result = await http.create_role(guild_id, reason=reason, **fields)
            return self._normalise(role_result), 201
        if operation_type is OperationType.UPDATE_ROLE:
            role_id = self._required_id(payload, "id")
            fields = self._only(payload, {"name", "permissions", "color", "hoist", "mentionable"})
            if "permissions" in fields:
                fields["permissions"] = str(fields["permissions"])
            role_result = await http.edit_role(guild_id, role_id, reason=reason, **fields)
            return self._normalise(role_result), 200
        if operation_type is OperationType.DELETE_ROLE:
            role_id = self._required_id(payload, "id")
            if role_id == guild_id:
                raise UnsafeRoleMutation("discord.guard.default_role_delete_forbidden")
            await http.delete_role(guild_id, role_id, reason=reason)
            return {"id": role_id, "deleted": True}, 204
        if operation_type is OperationType.REORDER_ROLES:
            positions = [
                {"id": self._required_id(item, "id"), "position": int(item["position"])}
                for item in self._items(payload)
            ]
            if any(item["id"] == guild_id for item in positions):
                raise UnsafeRoleMutation("discord.guard.default_role_reorder_forbidden")
            role_results = await http.move_role_position(
                guild_id, cast(Any, positions), reason=reason
            )
            return {"items": [self._normalise(item) for item in role_results]}, 200
        if operation_type is OperationType.CREATE_CHANNEL:
            channel_type = int(payload.get("type", 0))
            fields = self._only(
                payload,
                {
                    "name",
                    "topic",
                    "parent_id",
                    "position",
                    "nsfw",
                    "bitrate",
                    "user_limit",
                    "rate_limit_per_user",
                    "default_auto_archive_duration",
                },
            )
            channel_result = await http.create_channel(
                guild_id, cast(Any, channel_type), reason=reason, **fields
            )
            return self._normalise(channel_result), 201
        if operation_type is OperationType.UPDATE_CHANNEL:
            channel_id = self._required_id(payload, "id")
            fields = self._only(
                payload,
                {
                    "name",
                    "topic",
                    "nsfw",
                    "bitrate",
                    "user_limit",
                    "rate_limit_per_user",
                    "default_auto_archive_duration",
                    "flags",
                },
            )
            edited_channel_result = await http.edit_channel(channel_id, reason=reason, **fields)
            return self._normalise(edited_channel_result), 200
        if operation_type is OperationType.MOVE_OR_REORDER_CHANNELS:
            items = []
            parent_changes = 0
            for item in self._items(payload):
                clean = self._only(item, {"id", "position", "parent_id", "lock_permissions"})
                clean["id"] = self._required_id(item, "id")
                if "parent_id" in clean:
                    parent_changes += 1
                items.append(clean)
            if parent_changes > 1:
                raise ValueError("Discord permits one channel parent change per request")
            await http.bulk_channel_update(guild_id, cast(Any, items), reason=reason)
            return {"items": items}, 204
        if operation_type is OperationType.DELETE_CHANNEL:
            channel_id = self._required_id(payload, "id")
            await http.delete_channel(channel_id, reason=reason)
            return {"id": channel_id, "deleted": True}, 204
        if operation_type is OperationType.UPSERT_OVERWRITE:
            channel_id = self._required_id(payload, "channel_id")
            target_id = self._required_id(payload, "subject_id", fallback="target_id")
            await http.edit_channel_permissions(
                channel_id,
                target_id,
                str(payload.get("allow", 0)),
                str(payload.get("deny", 0)),
                cast(Any, int(payload.get("target_type", 0))),
                reason=reason,
            )
            return {
                "channel_id": channel_id,
                "target_id": target_id,
                "target_type": int(payload.get("target_type", 0)),
                "allow": int(payload.get("allow", 0)),
                "deny": int(payload.get("deny", 0)),
            }, 204
        if operation_type is OperationType.DELETE_OVERWRITE:
            channel_id = self._required_id(payload, "channel_id")
            target_id = self._required_id(payload, "subject_id", fallback="target_id")
            await http.delete_channel_permissions(channel_id, target_id, reason=reason)
            return {"channel_id": channel_id, "target_id": target_id, "deleted": True}, 204
        if operation_type in {
            OperationType.ADD_MEMBER_ROLE,
            OperationType.REMOVE_MEMBER_ROLE,
        }:
            member_id = self._required_id(payload, "member_id", fallback="id")
            role_id = self._required_id(payload, "role_id")
            if operation_type is OperationType.ADD_MEMBER_ROLE:
                await http.add_role(guild_id, member_id, role_id, reason=reason)
                assigned = True
            else:
                await http.remove_role(guild_id, member_id, role_id, reason=reason)
                assigned = False
            return {
                "id": member_id,
                "member_id": member_id,
                "role_id": role_id,
                "assigned": assigned,
            }, 204
        raise ValueError(f"unsupported structural operation: {operation_type.value}")

    async def recover(
        self,
        *,
        guild_id: int,
        operation_type: OperationType,
        payload: dict[str, Any],
        before_payload: dict[str, Any],
    ) -> RecoveryResult:
        if operation_type in {
            OperationType.UPSERT_OVERWRITE,
            OperationType.DELETE_OVERWRITE,
        }:
            channels = await self._reads.fetch_channels(guild_id)
            return self._recover_overwrite(operation_type, channels, payload, before_payload)
        if operation_type in {
            OperationType.ADD_MEMBER_ROLE,
            OperationType.REMOVE_MEMBER_ROLE,
        }:
            try:
                member_id = self._required_id(payload, "member_id", fallback="id")
                role_id = self._required_id(payload, "role_id")
                member = await self._reads.fetch_member(guild_id, member_id)
            except Exception:
                return RecoveryResult(RecoveryOutcome.AMBIGUOUS)
            raw_roles = member.get("role_ids")
            if not isinstance(raw_roles, list):
                return RecoveryResult(RecoveryOutcome.AMBIGUOUS)
            assigned = role_id in {int(value) for value in raw_roles}
            desired = operation_type is OperationType.ADD_MEMBER_ROLE
            if assigned == desired:
                return RecoveryResult(
                    RecoveryOutcome.PROVED_APPLIED,
                    {
                        "id": member_id,
                        "member_id": member_id,
                        "role_id": role_id,
                        "assigned": assigned,
                    },
                )
            if assigned == bool(before_payload.get("assigned", not desired)):
                return RecoveryResult(RecoveryOutcome.PROVED_ABSENT)
            return RecoveryResult(RecoveryOutcome.AMBIGUOUS)
        resources = (
            await self._reads.fetch_roles(guild_id)
            if operation_type
            in {
                OperationType.CREATE_ROLE,
                OperationType.UPDATE_ROLE,
                OperationType.DELETE_ROLE,
                OperationType.REORDER_ROLES,
            }
            else await self._reads.fetch_channels(guild_id)
        )
        creates = {OperationType.CREATE_ROLE, OperationType.CREATE_CHANNEL}
        deletes = {OperationType.DELETE_ROLE, OperationType.DELETE_CHANNEL}
        if operation_type in {
            OperationType.REORDER_ROLES,
            OperationType.MOVE_OR_REORDER_CHANNELS,
        }:
            items = payload.get("items", [])
            if not isinstance(items, list):
                return RecoveryResult(RecoveryOutcome.AMBIGUOUS)
            verification_items = items
            if operation_type is OperationType.REORDER_ROLES:
                expected_segment = payload.get("expected_position_segment")
                explicit_items = [
                    item
                    for item in (expected_segment if isinstance(expected_segment, list) else items)
                    if isinstance(item, dict)
                    and not str(item.get("resource_ref", "")).startswith("discord.role.")
                ]
                if explicit_items:
                    verification_items = explicit_items
            by_id = {
                int(item.get("id", item.get("role_id", item.get("channel_id", 0)))): item
                for item in resources
            }
            if all(
                int(item.get("id", 0)) in by_id and self._matches(by_id[int(item["id"])], item)
                for item in verification_items
                if isinstance(item, dict)
            ):
                return RecoveryResult(RecoveryOutcome.PROVED_APPLIED, {"items": verification_items})
            return RecoveryResult(RecoveryOutcome.AMBIGUOUS)
        if operation_type in creates:
            candidates = [
                item for item in resources if self._matches(item, payload, ignore={"position"})
            ]
            expected_id = payload.get("id")
            if expected_id is not None:
                candidates = [
                    item
                    for item in candidates
                    if int(item.get("id", item.get("role_id", item.get("channel_id", 0))))
                    == int(expected_id)
                ]
            if len(candidates) == 1:
                recovered = dict(candidates[0])
                recovered["id"] = int(
                    recovered.get(
                        "id",
                        recovered.get("role_id", recovered.get("channel_id", 0)),
                    )
                )
                if recovered["id"] <= 0:
                    return RecoveryResult(RecoveryOutcome.AMBIGUOUS)
                return RecoveryResult(RecoveryOutcome.PROVED_CREATED, recovered)
            if not candidates:
                return RecoveryResult(
                    RecoveryOutcome.PROVED_ABSENT
                    if operation_type is OperationType.CREATE_ROLE
                    else RecoveryOutcome.AMBIGUOUS
                )
            return RecoveryResult(RecoveryOutcome.AMBIGUOUS)
        resource_id = payload.get("id")
        current = next(
            (
                item
                for item in resources
                if int(item.get("id", item.get("role_id", item.get("channel_id", 0))))
                == int(resource_id or 0)
            ),
            None,
        )
        if operation_type in deletes:
            if operation_type is OperationType.DELETE_CHANNEL and current is None:
                # Get Guild Channels omission can mean access loss/obfuscation.
                return RecoveryResult(RecoveryOutcome.AMBIGUOUS)
            return RecoveryResult(
                RecoveryOutcome.PROVED_APPLIED
                if current is None
                else RecoveryOutcome.PROVED_ABSENT,
                current,
            )
        if current is not None and self._matches(current, payload):
            return RecoveryResult(RecoveryOutcome.PROVED_APPLIED, current)
        if current is not None and self._matches(current, before_payload):
            return RecoveryResult(RecoveryOutcome.PROVED_ABSENT, current)
        return RecoveryResult(RecoveryOutcome.AMBIGUOUS, current)

    @classmethod
    def _recover_overwrite(
        cls,
        operation_type: OperationType,
        channels: list[dict[str, Any]],
        payload: dict[str, Any],
        before_payload: dict[str, Any],
    ) -> RecoveryResult:
        try:
            channel_id = cls._required_id(payload, "channel_id")
            target_id = cls._required_id(payload, "subject_id", fallback="target_id")
        except ValueError:
            return RecoveryResult(RecoveryOutcome.AMBIGUOUS)
        channel = next(
            (item for item in channels if int(item.get("channel_id", 0)) == channel_id), None
        )
        if channel is None:
            return RecoveryResult(RecoveryOutcome.AMBIGUOUS)
        target_type = int(payload.get("target_type", 0))
        current = next(
            (
                item
                for item in channel.get("permission_overwrites", [])
                if int(item.get("id", 0)) == target_id and int(item.get("type", 0)) == target_type
            ),
            None,
        )
        if operation_type is OperationType.DELETE_OVERWRITE:
            return RecoveryResult(
                RecoveryOutcome.PROVED_APPLIED
                if current is None
                else RecoveryOutcome.PROVED_ABSENT,
                current,
            )
        desired = {
            "allow": int(payload.get("allow", 0)),
            "deny": int(payload.get("deny", 0)),
        }
        if current is not None and all(
            int(current[key]) == value for key, value in desired.items()
        ):
            return RecoveryResult(RecoveryOutcome.PROVED_APPLIED, current)
        if current is None and not before_payload:
            return RecoveryResult(RecoveryOutcome.PROVED_ABSENT)
        comparable_before = {
            key: value
            for key, value in before_payload.items()
            if key not in {"channel_id", "subject_id"}
        }
        if current is not None and comparable_before and cls._matches(current, comparable_before):
            return RecoveryResult(RecoveryOutcome.PROVED_ABSENT, current)
        return RecoveryResult(RecoveryOutcome.AMBIGUOUS, current)

    async def verify(
        self,
        *,
        guild_id: int,
        operation_type: OperationType,
        payload: dict[str, Any],
        result_payload: dict[str, Any] | None,
    ) -> bool:
        if result_payload is not None:
            if operation_type in {OperationType.DELETE_ROLE, OperationType.DELETE_CHANNEL} and bool(
                result_payload.get("deleted")
            ):
                return True
        verification_payload = dict(payload)
        if (
            operation_type in {OperationType.CREATE_ROLE, OperationType.CREATE_CHANNEL}
            and result_payload is not None
            and result_payload.get("id") is not None
        ):
            verification_payload["id"] = result_payload["id"]
        recovery = await self.recover(
            guild_id=guild_id,
            operation_type=operation_type,
            payload=verification_payload,
            before_payload={},
        )
        if operation_type in {OperationType.DELETE_ROLE, OperationType.DELETE_CHANNEL}:
            return recovery.outcome is RecoveryOutcome.PROVED_APPLIED
        return recovery.outcome in {
            RecoveryOutcome.PROVED_APPLIED,
            RecoveryOutcome.PROVED_CREATED,
        }

    @staticmethod
    def _translate_mutation(exc: Exception) -> MutableDiscordError:
        if isinstance(exc, MutableDiscordError):
            return exc
        if isinstance(exc, UnsafeRoleMutation):
            return MutableDiscordError(
                DiscordFailure(DiscordErrorKind.CONTRACT_ERROR, None), outcome_unknown=False
            )
        if isinstance(exc, asyncio.TimeoutError | aiohttp.ClientConnectionError):
            return MutableDiscordError(
                DiscordFailure(DiscordErrorKind.TRANSIENT, None), outcome_unknown=True
            )
        translated = DiscordPyStructureAdapter._translate(exc)
        return MutableDiscordError(
            translated.failure,
            outcome_unknown=translated.failure.kind is DiscordErrorKind.TRANSIENT,
        )

    @staticmethod
    def _normalise(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            result = dict(value)
        else:
            result = {"id": int(value.id)}
            for key in (
                "name",
                "position",
                "permissions",
                "managed",
                "color",
                "hoist",
                "mentionable",
                "type",
                "topic",
                "parent_id",
                "nsfw",
                "flags",
                "bitrate",
                "user_limit",
                "slowmode_delay",
                "default_auto_archive_duration",
            ):
                if hasattr(value, key):
                    destination_key = "rate_limit_per_user" if key == "slowmode_delay" else key
                    result[destination_key] = getattr(value, key)
        for key in ("id", "guild_id", "parent_id"):
            if result.get(key) is not None:
                result[key] = int(result[key])
        for key in (
            "permissions",
            "color",
            "flags",
            "type",
            "bitrate",
            "user_limit",
            "rate_limit_per_user",
            "default_auto_archive_duration",
        ):
            item = result.get(key)
            raw_value = getattr(item, "value", None)
            if raw_value is not None:
                result[key] = int(raw_value)
            elif isinstance(item, str) and item.isdecimal():
                result[key] = int(item)
        return result

    @staticmethod
    def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
        items = payload.get("items")
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise ValueError("bulk operation requires an items array")
        return items

    @staticmethod
    def _required_id(payload: dict[str, Any], key: str, *, fallback: str | None = None) -> int:
        value = payload.get(key)
        if value is None and fallback is not None:
            value = payload.get(fallback)
        if value is None or not str(value).isdecimal() or int(value) <= 0:
            raise ValueError(f"{key} must be a positive Discord snowflake")
        return int(value)

    @staticmethod
    def _only(payload: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
        return {key: value for key, value in payload.items() if key in allowed}

    @staticmethod
    def _matches(
        observed: dict[str, Any], desired: dict[str, Any], *, ignore: set[str] | None = None
    ) -> bool:
        skipped = (ignore or set()) | {
            "id",
            "resource_ref",
            "parent_symbol",
            "channel_symbol",
            "subject_symbol",
            "lock_permissions",
        }
        comparable = {key: value for key, value in desired.items() if key not in skipped}

        missing = object()

        def observed_value(key: str) -> object:
            if key == "id":
                return observed.get(
                    "id", observed.get("role_id", observed.get("channel_id", missing))
                )
            if key == "target_id":
                return observed.get("target_id", observed.get("id", missing))
            if key == "target_type":
                return observed.get("target_type", observed.get("type", missing))
            return observed.get(key, missing)

        def matches_value(key: str, value: object) -> bool:
            current = observed_value(key)
            if current is missing:
                return False
            if value is None:
                return current is None
            return current is not None and str(current) == str(value)

        return bool(comparable) and all(
            matches_value(key, value) for key, value in comparable.items()
        )


def request_fingerprint(operation_type: OperationType, payload: dict[str, Any]) -> str:
    return canonical_hash({"operation_type": operation_type.value, "payload": payload})
