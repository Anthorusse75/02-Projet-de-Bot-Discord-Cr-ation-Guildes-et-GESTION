from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from did.domain.discord_runtime import EventEnvelope, ObservabilityState, WorkloadJob
from did.infrastructure.auth_repository import InstallationIdentityMismatch
from did.infrastructure.database import tenant_transaction
from did.infrastructure.runtime_metrics import RuntimeMetrics
from did.tenancy import TenantContext


class RuntimeRepository:
    """Durable tenant-scoped event ledger and Discord cache projector."""

    def __init__(
        self, factory: async_sessionmaker[AsyncSession], *, metrics: RuntimeMetrics | None = None
    ) -> None:
        self._factory = factory
        self.metrics = metrics or RuntimeMetrics()
        self._application_id: int | None = None
        self._bot_user_id: int | None = None

    def bind_bot_identity(self, *, application_id: int, bot_user_id: int) -> None:
        if application_id <= 0 or bot_user_id <= 0:
            raise ValueError("Discord application and bot identities must be positive")
        identity = (self._application_id, self._bot_user_id)
        if identity != (None, None) and identity != (application_id, bot_user_id):
            raise InstallationIdentityMismatch("runtime bot identity changed after binding")
        self._application_id = application_id
        self._bot_user_id = bot_user_id

    async def audit_events(self, guild_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 200:
            raise ValueError("audit list limit must be between 1 and 200")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT id,event_type,target_type,target_id,result_state,"
                            "occurred_at,plan_id,correlation_id FROM internal_audit_events "
                            "WHERE guild_id=:guild_id ORDER BY occurred_at DESC,id DESC "
                            "LIMIT :limit"
                        ),
                        {"guild_id": guild_id, "limit": limit},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def ingest_gateway_event(self, envelope: EventEnvelope) -> bool:
        async with tenant_transaction(self._factory, TenantContext(envelope.guild_id)) as session:
            # The inbox is deliberately FK-bound to an installation. A brand-new guild is
            # first discovered by GUILD_CREATE, so establish that tenant root in the same
            # transaction before recording the event. Projection below enriches it.
            if envelope.event_type == "GUILD_CREATE":
                existing_identity = (
                    (
                        await session.execute(
                            text(
                                "SELECT application_id, bot_user_id FROM guild_installations "
                                "WHERE guild_id=:guild_id"
                            ),
                            {"guild_id": envelope.guild_id},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing_identity is not None:
                    application_mismatch = (
                        self._application_id is not None
                        and existing_identity["application_id"] is not None
                        and int(existing_identity["application_id"]) != self._application_id
                    )
                    bot_mismatch = (
                        self._bot_user_id is not None
                        and existing_identity["bot_user_id"] is not None
                        and int(existing_identity["bot_user_id"]) != self._bot_user_id
                    )
                    if application_mismatch or bot_mismatch:
                        raise InstallationIdentityMismatch(
                            "Gateway installation application or bot identity does not match"
                        )
                await session.execute(
                    text(
                        "INSERT INTO guild_installations "
                        "(guild_id, name, owner_id, installation_status, last_gateway_seen_at, "
                        "application_id, bot_user_id) VALUES "
                        "(:guild_id, :name, :owner_id, 'PENDING_SETUP', :seen_at, "
                        ":application_id, :bot_user_id) ON CONFLICT (guild_id) DO UPDATE SET "
                        "application_id=COALESCE(guild_installations.application_id, "
                        "EXCLUDED.application_id), bot_user_id=COALESCE("
                        "guild_installations.bot_user_id, EXCLUDED.bot_user_id)"
                    ),
                    {
                        "guild_id": envelope.guild_id,
                        "name": envelope.payload["name"],
                        "owner_id": envelope.payload.get("owner_id"),
                        "seen_at": envelope.received_at,
                        "application_id": self._application_id,
                        "bot_user_id": self._bot_user_id,
                    },
                )
            inserted = await session.scalar(
                text(
                    "INSERT INTO discord_gateway_inbox "
                    "(event_id, guild_id, event_type, discord_sequence, discord_session_id, "
                    "occurred_at, received_at, correlation_id, causation_id, schema_version, "
                    "source, origin, causation_depth, payload) VALUES "
                    "(:event_id, :guild_id, :event_type, :discord_sequence, :session_id, "
                    ":occurred_at, :received_at, :correlation_id, :causation_id, "
                    ":schema_version, :source, :origin, :causation_depth, CAST(:payload AS jsonb)) "
                    "ON CONFLICT DO NOTHING RETURNING event_id"
                ),
                {
                    "event_id": envelope.event_id,
                    "guild_id": envelope.guild_id,
                    "event_type": envelope.event_type,
                    "discord_sequence": envelope.discord_sequence,
                    "session_id": envelope.discord_session_id,
                    "occurred_at": envelope.occurred_at,
                    "received_at": envelope.received_at,
                    "correlation_id": envelope.correlation_id,
                    "causation_id": envelope.causation_id,
                    "schema_version": envelope.schema_version,
                    "source": envelope.source.value,
                    "origin": envelope.origin.value,
                    "causation_depth": envelope.causation_depth,
                    "payload": json.dumps(envelope.payload, separators=(",", ":")),
                },
            )
            if inserted is None:
                self.metrics.gateway_signal("duplicate")
                return False
            self.metrics.gateway_signal("dispatch")
            applied = await self._project(session, envelope)
            if applied and envelope.event_type in {
                "CHANNEL_CREATE",
                "CHANNEL_UPDATE",
                "CHANNEL_DELETE",
                "GUILD_ROLE_CREATE",
                "GUILD_ROLE_UPDATE",
                "GUILD_ROLE_DELETE",
                "GUILD_MEMBER_UPDATE",
            }:
                await self._classify_plan_gateway_event(session, envelope)
            await session.execute(
                text(
                    "UPDATE discord_gateway_inbox SET status='PROJECTED', projected_at=now() "
                    "WHERE event_id=:event_id"
                ),
                {"event_id": envelope.event_id},
            )
            if applied:
                await self._append_outbox(
                    session,
                    guild_id=envelope.guild_id,
                    topic="discord.cache.changed",
                    payload={
                        "event_id": str(envelope.event_id),
                        "event_type": envelope.event_type,
                        "guild_id": str(envelope.guild_id),
                    },
                    correlation_id=envelope.correlation_id,
                    causation_id=envelope.event_id,
                )
                await self._refresh_coverage(session, envelope.guild_id, envelope.received_at)
            return True

    async def _classify_plan_gateway_event(
        self, session: AsyncSession, envelope: EventEnvelope
    ) -> None:
        """Match inferred own events conservatively; never claim native plan correlation."""
        resource_id = int(
            envelope.payload.get("channel_id")
            or envelope.payload.get("role_id")
            or envelope.payload.get("discord_user_id")
            or 0
        )
        if resource_id <= 0:
            return
        observed = self._plan_event_payload(envelope, resource_id)
        candidates = (
            (
                await session.execute(
                    text(
                        "SELECT expected.*,operations.operation_type FROM "
                        "plan_expected_mutations expected JOIN plan_operations operations ON "
                        "operations.guild_id=expected.guild_id AND operations.plan_id="
                        "expected.plan_id AND operations.id=expected.operation_id WHERE "
                        "expected.guild_id=:guild_id "
                        "AND expected.event_type=:event_type AND expected.discord_resource_id="
                        ":resource_id AND expected.status='EXPECTED' AND expected.expires_at>"
                        "now() ORDER BY expected.expires_at"
                    ),
                    {
                        "guild_id": envelope.guild_id,
                        "event_type": envelope.event_type,
                        "resource_id": resource_id,
                    },
                )
            )
            .mappings()
            .all()
        )
        exact = [
            row
            for row in candidates
            if self._matches_expected_gateway(
                str(row["operation_type"]),
                envelope.event_type,
                dict(row["expected_payload"]),
                observed,
            )
        ]
        if len(exact) == 1:
            await session.execute(
                text(
                    "UPDATE plan_expected_mutations SET status='OBSERVED',observed_at=now() "
                    "WHERE guild_id=:guild_id AND id=:id AND status='EXPECTED'"
                ),
                {"guild_id": envelope.guild_id, "id": exact[0]["id"]},
            )
            return

        # Gateway may beat the REST response/DB commit for a CREATE.  A unique
        # in-flight operation with a matching desired subset is inferred as own,
        # without manufacturing a Discord-native correlation identifier.
        inflight = (
            (
                await session.execute(
                    text(
                        "SELECT operations.operation_type,COALESCE(attempts.outcome_detail->"
                        "'resolved_payload',operations.desired_payload) AS desired_payload FROM "
                        "plan_operations operations LEFT JOIN operation_attempts attempts ON "
                        "attempts.guild_id=operations.guild_id AND attempts.plan_id="
                        "operations.plan_id AND attempts.operation_id=operations.id AND "
                        "attempts.attempt_number=operations.attempt_count "
                        "JOIN plans ON plans.guild_id=operations.guild_id "
                        "AND plans.id=operations.plan_id WHERE operations.guild_id=:guild_id "
                        "AND plans.status='APPLYING' AND operations.status IN "
                        "('IN_FLIGHT','SUCCEEDED') "
                        "AND :event_type=ANY(operations.expected_gateway_events)"
                    ),
                    {"guild_id": envelope.guild_id, "event_type": envelope.event_type},
                )
            )
            .mappings()
            .all()
        )
        inferred = [
            row
            for row in inflight
            if self._matches_expected_gateway(
                str(row["operation_type"]),
                envelope.event_type,
                dict(row["desired_payload"]),
                observed,
            )
        ]
        if len(inferred) == 1:
            return

        stale = (
            (
                await session.execute(
                    text(
                        "UPDATE plans SET status='STALE',drift_detected_at=now(),"
                        "error_code='STRUCTURE_DRIFT',state_version=state_version+1,"
                        "updated_at=now() WHERE guild_id=:guild_id AND status IN "
                        "('DRAFT','VALIDATED','CONFIRMED') AND EXISTS (SELECT 1 FROM "
                        "plan_resource_dependencies dependencies WHERE dependencies.guild_id="
                        "plans.guild_id AND dependencies.plan_id=plans.id AND dependencies."
                        "resource_type=:resource_type AND dependencies.discord_resource_id="
                        ":resource_id) RETURNING id"
                    ),
                    {
                        "guild_id": envelope.guild_id,
                        "resource_type": self._gateway_resource_type(envelope.event_type),
                        "resource_id": resource_id,
                    },
                )
            )
            .scalars()
            .all()
        )
        interrupted = (
            (
                await session.execute(
                    text(
                        "UPDATE plans SET status='INTERVENTION_REQUIRED',"
                        "drift_detected_at=now(),completed_at=now(),"
                        "error_code='DRIFT_DURING_APPLY',state_version=state_version+1,"
                        "updated_at=now() WHERE guild_id=:guild_id AND status IN "
                        "('APPLYING','CANCEL_REQUESTED') AND EXISTS (SELECT 1 FROM "
                        "plan_resource_dependencies dependencies WHERE dependencies.guild_id="
                        "plans.guild_id AND dependencies.plan_id=plans.id AND dependencies."
                        "resource_type=:resource_type AND dependencies.discord_resource_id="
                        ":resource_id) RETURNING id"
                    ),
                    {
                        "guild_id": envelope.guild_id,
                        "resource_type": self._gateway_resource_type(envelope.event_type),
                        "resource_id": resource_id,
                    },
                )
            )
            .scalars()
            .all()
        )
        if stale or interrupted:
            await self._append_audit(
                session,
                envelope,
                event_type="PLAN_STRUCTURE_DRIFT_DETECTED",
                target_type="DISCORD_RESOURCE",
                target_id=resource_id,
                result_state="INTERVENTION_REQUIRED" if interrupted else "STALE",
            )

    @staticmethod
    def _plan_event_payload(envelope: EventEnvelope, resource_id: int) -> dict[str, Any]:
        payload = dict(envelope.payload)
        payload["id"] = resource_id
        if envelope.event_type.endswith("_DELETE"):
            payload["deleted"] = True
        return payload

    @staticmethod
    def _matches_expected_gateway(
        operation_type: str,
        event_type: str,
        expected: dict[str, Any],
        observed: dict[str, Any],
    ) -> bool:
        if operation_type in {"ADD_MEMBER_ROLE", "REMOVE_MEMBER_ROLE"}:
            role_id = expected.get("role_id")
            role_ids = observed.get("role_ids")
            if role_id is None or not isinstance(role_ids, list):
                return False
            assigned = int(role_id) in {int(value) for value in role_ids}
            return assigned is (operation_type == "ADD_MEMBER_ROLE")
        if operation_type in {"UPSERT_OVERWRITE", "DELETE_OVERWRITE"}:
            expected_channel_id = expected.get("channel_id")
            if expected_channel_id is None or str(observed.get("channel_id")) != str(
                expected_channel_id
            ):
                return False
            specification = expected.get("overwrite")
            overwrites = observed.get("permission_overwrites")
            if not isinstance(specification, dict) or not isinstance(overwrites, list):
                return False
            expected_full = expected.get("full_overwrites")
            if isinstance(expected_full, list):
                normalized_expected = sorted(
                    (
                        int(item.get("type", 0)),
                        int(item.get("id", 0)),
                        int(item.get("allow", 0)),
                        int(item.get("deny", 0)),
                    )
                    for item in expected_full
                    if isinstance(item, dict)
                )
                normalized_observed = sorted(
                    (
                        int(item.get("type", 0)),
                        int(item.get("id", 0)),
                        int(item.get("allow", 0)),
                        int(item.get("deny", 0)),
                    )
                    for item in overwrites
                    if isinstance(item, dict)
                )
                if normalized_expected != normalized_observed:
                    return False
            target_id = specification.get("target_id")
            target_type = specification.get("target_type")
            if target_id is None or target_type is None:
                return False
            current = next(
                (
                    item
                    for item in overwrites
                    if isinstance(item, dict)
                    and str(item.get("id")) == str(target_id)
                    and str(item.get("type")) == str(target_type)
                ),
                None,
            )
            if bool(specification.get("present")):
                return current is not None and all(
                    key in current and str(current[key]) == str(specification[key])
                    for key in ("allow", "deny")
                    if key in specification
                )
            return current is None

        ignored = {
            "resource_ref",
            "parent_symbol",
            "channel_symbol",
            "subject_symbol",
            "lock_permissions",
            "items",
        }
        aliases = {
            "id": ("id", "channel_id", "role_id"),
            "target_id": ("target_id", "id"),
            "target_type": ("target_type", "type"),
        }
        comparable = {key: value for key, value in expected.items() if key not in ignored}
        if operation_type in {"REORDER_ROLES", "MOVE_OR_REORDER_CHANNELS"}:
            raw_items = expected.get("items")
            if isinstance(raw_items, list):
                observed_id = (
                    observed.get("id") or observed.get("role_id") or observed.get("channel_id")
                )
                expected = next(
                    (
                        item
                        for item in raw_items
                        if isinstance(item, dict) and str(item.get("id")) == str(observed_id)
                    ),
                    {},
                )
            comparable = {
                key: value
                for key, value in expected.items()
                if key in {"id", "position", "parent_id"}
            }
        if event_type.endswith("_DELETE"):
            comparable["deleted"] = True
        if not comparable:
            return False
        for key, value in comparable.items():
            observed_keys = aliases.get(key, (key,))
            present = next(
                (candidate for candidate in observed_keys if candidate in observed), None
            )
            if present is None or str(observed[present]) != str(value):
                return False
        return True

    @staticmethod
    def _gateway_resource_type(event_type: str) -> str:
        if event_type == "GUILD_MEMBER_UPDATE":
            return "MEMBER"
        return "ROLE" if event_type.startswith("GUILD_ROLE_") else "CHANNEL"

    async def _project(self, session: AsyncSession, envelope: EventEnvelope) -> bool:
        event_type = envelope.event_type
        if event_type in {
            "CHANNEL_CREATE",
            "CHANNEL_UPDATE",
            "CHANNEL_DELETE",
            "THREAD_CREATE",
            "THREAD_UPDATE",
            "THREAD_DELETE",
        }:
            return await self._project_channel(session, envelope, envelope.payload)
        elif event_type in {"GUILD_ROLE_CREATE", "GUILD_ROLE_UPDATE", "GUILD_ROLE_DELETE"}:
            return await self._project_role(session, envelope, envelope.payload)
        elif event_type == "GUILD_CREATE":
            await self._project_guild_create(session, envelope)
            return True
        elif event_type == "THREAD_LIST_SYNC":
            await self._project_thread_list_sync(session, envelope)
            return True
        elif event_type in {"THREAD_MEMBER_UPDATE", "THREAD_MEMBERS_UPDATE"}:
            await self._project_thread_membership_event(session, envelope)
            return True
        elif event_type == "GUILD_UPDATE":
            result = await session.execute(
                text(
                    "UPDATE guild_installations SET "
                    "name=COALESCE(:name, name), owner_id=COALESCE(:owner_id, owner_id), "
                    "last_gateway_seen_at=:seen_at, version=version+1 "
                    "WHERE guild_id=:guild_id RETURNING guild_id"
                ),
                {
                    "guild_id": envelope.guild_id,
                    "name": envelope.payload.get("name"),
                    "owner_id": envelope.payload.get("owner_id"),
                    "seen_at": envelope.received_at,
                },
            )
            return result.scalar_one_or_none() is not None
        elif event_type == "GUILD_DELETE":
            await self._project_guild_delete(session, envelope)
            return True
        elif event_type in {"GUILD_MEMBER_ADD", "GUILD_MEMBER_UPDATE"}:
            await self._project_member(session, envelope)
            if event_type == "GUILD_MEMBER_ADD":
                await self._refresh_member_coverage(session, envelope, delta=1)
            return True
        elif event_type == "GUILD_MEMBER_REMOVE":
            await session.execute(
                text(
                    "DELETE FROM discord_member_authorization_cache WHERE guild_id=:guild_id "
                    "AND discord_user_id=:user_id"
                ),
                {
                    "guild_id": envelope.guild_id,
                    "user_id": int(envelope.payload["discord_user_id"]),
                },
            )
            await self._refresh_member_coverage(session, envelope, delta=-1)
            return True
        return False

    async def _project_guild_create(self, session: AsyncSession, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        await session.execute(
            text(
                "INSERT INTO guild_installations "
                "(guild_id, name, owner_id, installation_status, last_gateway_seen_at) VALUES "
                "(:guild_id, :name, :owner_id, 'PENDING_SETUP', :seen_at) "
                "ON CONFLICT (guild_id) DO UPDATE SET "
                "name=EXCLUDED.name, owner_id=COALESCE(EXCLUDED.owner_id, "
                "guild_installations.owner_id), "
                "last_gateway_seen_at=EXCLUDED.last_gateway_seen_at, "
                "installation_status=CASE "
                "WHEN guild_installations.installation_status IN "
                "('DISCOVERED','INSTALLED','UNINSTALLED') "
                "THEN 'PENDING_SETUP' ELSE guild_installations.installation_status END, "
                "uninstalled_at=CASE WHEN guild_installations.installation_status='UNINSTALLED' "
                "THEN NULL ELSE guild_installations.uninstalled_at END, "
                "version=guild_installations.version+1"
            ),
            {
                "guild_id": envelope.guild_id,
                "name": payload["name"],
                "owner_id": payload.get("owner_id"),
                "seen_at": envelope.received_at,
            },
        )
        for channel in payload.get("channels", []):
            await self._project_channel(session, envelope, channel, audit=False)
        for thread in payload.get("threads", []):
            await self._project_channel(session, envelope, thread, audit=False)
        await self._mark_threads_outside_active_sync(
            session,
            envelope,
            thread_ids={int(thread["channel_id"]) for thread in payload.get("threads", [])},
            parent_ids=None,
        )
        await self._project_sync_memberships(
            session,
            envelope,
            payload.get("threads", []),
            member_rows=(),
            absence_is_proof=True,
        )
        await self._record_thread_sync_coverage(session, envelope, parent_ids=None)
        for role in payload.get("roles", []):
            await self._project_role(session, envelope, role, audit=False)
        if bool(payload.get("members_complete")):
            await session.execute(
                text("DELETE FROM discord_member_authorization_cache WHERE guild_id=:guild_id"),
                {"guild_id": envelope.guild_id},
            )
            for member in payload.get("members", []):
                member_envelope = EventEnvelope(
                    event_id=envelope.event_id,
                    guild_id=envelope.guild_id,
                    event_type="GUILD_MEMBER_UPDATE",
                    discord_sequence=envelope.discord_sequence,
                    discord_session_id=envelope.discord_session_id,
                    occurred_at=envelope.occurred_at,
                    received_at=envelope.received_at,
                    correlation_id=envelope.correlation_id,
                    causation_id=envelope.causation_id,
                    schema_version=envelope.schema_version,
                    payload=member,
                    source=envelope.source,
                    origin=envelope.origin,
                )
                await self._project_member(session, member_envelope)
        known_members = len(payload.get("members", [])) if payload.get("members_complete") else 0
        await session.execute(
            text(
                "UPDATE discord_cache_coverage SET known_members=:known_members,"
                "member_count=:member_count,members_complete=:members_complete,"
                "last_full_member_sync_at=CASE WHEN :members_complete "
                "THEN CAST(:seen_at AS timestamptz) ELSE NULL END,"
                "state_version=state_version+1,updated_at=now() WHERE guild_id=:guild_id"
            ),
            {
                "guild_id": envelope.guild_id,
                "known_members": known_members,
                "member_count": int(payload.get("member_count", 0)),
                "members_complete": bool(payload.get("members_complete")),
                "seen_at": envelope.received_at,
            },
        )
        await self._append_audit(
            session,
            envelope,
            event_type="INSTALLATION_DETECTED",
            target_type="GUILD",
            target_id=envelope.guild_id,
            result_state="OBSERVED",
        )

    async def _project_guild_delete(self, session: AsyncSession, envelope: EventEnvelope) -> None:
        if bool(envelope.payload.get("unavailable")):
            await session.execute(
                text(
                    "UPDATE discord_cache_coverage SET gateway_continuity='DISCONNECTED', "
                    "freshness_state='STALE', active_threads_coverage='DEGRADED', "
                    "updated_at=now(), state_version=state_version+1 "
                    "WHERE guild_id=:guild_id"
                ),
                {"guild_id": envelope.guild_id},
            )
            return
        await session.execute(
            text(
                "UPDATE guild_installations SET installation_status='UNINSTALLED', "
                "uninstalled_at=:seen_at, last_gateway_seen_at=:seen_at, version=version+1 "
                "WHERE guild_id=:guild_id"
            ),
            {"guild_id": envelope.guild_id, "seen_at": envelope.received_at},
        )
        await session.execute(
            text(
                "UPDATE discord_io_jobs SET status='CANCELLED', updated_at=now() "
                "WHERE guild_id=:guild_id AND status IN ('PENDING','LEASED')"
            ),
            {"guild_id": envelope.guild_id},
        )
        await self._append_audit(
            session,
            envelope,
            event_type="INSTALLATION_UNINSTALLED",
            target_type="GUILD",
            target_id=envelope.guild_id,
            result_state="UNINSTALLED",
        )

    async def _project_channel(
        self,
        session: AsyncSession,
        envelope: EventEnvelope,
        payload: dict[str, Any],
        *,
        audit: bool = True,
    ) -> bool:
        channel_id = int(payload["channel_id"])
        is_delete = envelope.event_type in {"CHANNEL_DELETE", "THREAD_DELETE"}
        if is_delete:
            result = await session.execute(
                text(
                    "INSERT INTO discord_channels_cache "
                    "(guild_id, channel_id, type, parent_id, position, flags, observability_state, "
                    "is_obfuscated, freshness_state, deleted_confirmed_at, last_gateway_seen_at, "
                    "last_gateway_sequence, last_gateway_session_id) VALUES "
                    "(:guild_id, :channel_id, :type, :parent_id, :position, :flags, "
                    "'DELETED_CONFIRMED', false, 'FRESH', :seen_at, :seen_at, :sequence, "
                    ":session_id) "
                    "ON CONFLICT (guild_id, channel_id) DO UPDATE SET "
                    "observability_state='DELETED_CONFIRMED', is_obfuscated=false, "
                    "freshness_state='FRESH', deleted_confirmed_at=EXCLUDED.deleted_confirmed_at, "
                    "last_gateway_seen_at=EXCLUDED.last_gateway_seen_at, "
                    "last_gateway_sequence=EXCLUDED.last_gateway_sequence, "
                    "last_gateway_session_id=EXCLUDED.last_gateway_session_id, "
                    "state_version=discord_channels_cache.state_version+1, cache_updated_at=now() "
                    "WHERE discord_channels_cache.last_gateway_session_id IS DISTINCT FROM "
                    "EXCLUDED.last_gateway_session_id OR "
                    "discord_channels_cache.last_gateway_sequence IS NULL OR "
                    "EXCLUDED.last_gateway_sequence >= "
                    "discord_channels_cache.last_gateway_sequence "
                    "RETURNING channel_id"
                ),
                self._channel_parameters(envelope, payload),
            )
            applied = result.scalar_one_or_none() is not None
            if applied:
                await self._project_stage08_channel_delete(session, envelope, channel_id)
            drift_type = (
                "THREAD_DELETED" if envelope.event_type == "THREAD_DELETE" else "CHANNEL_DELETED"
            )
        elif bool(payload.get("is_obfuscated")):
            result = await session.execute(
                text(
                    "INSERT INTO discord_channels_cache "
                    "(guild_id, channel_id, type, parent_id, position, flags, observability_state, "
                    "is_obfuscated, freshness_state, access_lost_at, obfuscated_at, "
                    "last_gateway_seen_at, last_gateway_sequence, last_gateway_session_id) VALUES "
                    "(:guild_id, :channel_id, :type, :parent_id, :position, :flags, "
                    "'OBFUSCATED', true, 'FRESH', :seen_at, :seen_at, :seen_at, :sequence, "
                    ":session_id) "
                    "ON CONFLICT (guild_id, channel_id) DO UPDATE SET "
                    "type=EXCLUDED.type, parent_id=EXCLUDED.parent_id, position=EXCLUDED.position, "
                    "flags=EXCLUDED.flags, observability_state='OBFUSCATED', is_obfuscated=true, "
                    "freshness_state='FRESH', access_lost_at=COALESCE("
                    "discord_channels_cache.access_lost_at, EXCLUDED.access_lost_at), "
                    "obfuscated_at=EXCLUDED.obfuscated_at, "
                    "last_gateway_seen_at=EXCLUDED.last_gateway_seen_at, "
                    "last_gateway_sequence=EXCLUDED.last_gateway_sequence, "
                    "last_gateway_session_id=:session_id, "
                    "state_version=discord_channels_cache.state_version+1, cache_updated_at=now() "
                    "WHERE discord_channels_cache.last_gateway_session_id IS DISTINCT FROM "
                    ":session_id OR discord_channels_cache.last_gateway_sequence IS NULL OR "
                    "EXCLUDED.last_gateway_sequence >= "
                    "discord_channels_cache.last_gateway_sequence "
                    "RETURNING channel_id"
                ),
                self._channel_parameters(envelope, payload),
            )
            applied = result.scalar_one_or_none() is not None
            drift_type = "CHANNEL_OBFUSCATED"
        else:
            result = await session.execute(
                text(
                    "INSERT INTO discord_channels_cache "
                    "(guild_id, channel_id, type, name, topic, parent_id, position, nsfw, flags, "
                    "last_full_payload, observability_state, is_obfuscated, freshness_state, "
                    "last_full_observed_at, last_gateway_seen_at, last_gateway_sequence, "
                    "last_gateway_session_id) VALUES "
                    "(:guild_id, :channel_id, :type, :name, :topic, :parent_id, :position, :nsfw, "
                    ":flags, CAST(:full_payload AS jsonb), 'VISIBLE', false, 'FRESH', :seen_at, "
                    ":seen_at, :sequence, :session_id) "
                    "ON CONFLICT (guild_id, channel_id) DO UPDATE SET "
                    "type=EXCLUDED.type, name=EXCLUDED.name, topic=EXCLUDED.topic, "
                    "parent_id=EXCLUDED.parent_id, position=EXCLUDED.position, nsfw=EXCLUDED.nsfw, "
                    "flags=EXCLUDED.flags, last_full_payload=EXCLUDED.last_full_payload, "
                    "observability_state='VISIBLE', is_obfuscated=false, freshness_state='FRESH', "
                    "last_full_observed_at=EXCLUDED.last_full_observed_at, "
                    "last_gateway_seen_at=EXCLUDED.last_gateway_seen_at, access_lost_at=NULL, "
                    "obfuscated_at=NULL, deleted_confirmed_at=NULL, "
                    "last_gateway_sequence=EXCLUDED.last_gateway_sequence, "
                    "last_gateway_session_id=:session_id, "
                    "state_version=discord_channels_cache.state_version+1, cache_updated_at=now() "
                    "WHERE discord_channels_cache.last_gateway_session_id IS DISTINCT FROM "
                    ":session_id OR discord_channels_cache.last_gateway_sequence IS NULL OR "
                    "EXCLUDED.last_gateway_sequence >= "
                    "discord_channels_cache.last_gateway_sequence "
                    "RETURNING channel_id"
                ),
                self._channel_parameters(envelope, payload),
            )
            applied_id = result.scalar_one_or_none()
            applied = applied_id is not None
            if applied:
                reobserved = await session.scalar(
                    text(
                        "DELETE FROM discord_channel_tombstones "
                        "WHERE guild_id=:guild_id AND channel_id=:channel_id RETURNING channel_id"
                    ),
                    {"guild_id": envelope.guild_id, "channel_id": channel_id},
                )
                await session.execute(
                    text(
                        "DELETE FROM channel_overwrites_cache "
                        "WHERE guild_id=:guild_id AND channel_id=:channel_id"
                    ),
                    {"guild_id": envelope.guild_id, "channel_id": channel_id},
                )
                await self._insert_overwrites(
                    session,
                    guild_id=envelope.guild_id,
                    channel_id=channel_id,
                    overwrites=payload.get("permission_overwrites", []),
                    observed_at=envelope.received_at,
                )
                if reobserved is not None:
                    await self._append_audit(
                        session,
                        envelope,
                        event_type="PURGED_RESOURCE_REOBSERVED",
                        target_type="CHANNEL",
                        target_id=channel_id,
                        result_state="VISIBLE",
                    )
            drift_type = (
                "CHANNEL_CREATED_OUTSIDE_PLATFORM"
                if envelope.event_type in {"CHANNEL_CREATE", "THREAD_CREATE"}
                else "CHANNEL_PERMISSION_CHANGED"
            )
        if audit and applied:
            await self._append_audit(
                session,
                envelope,
                event_type=drift_type,
                target_type="THREAD" if envelope.event_type.startswith("THREAD_") else "CHANNEL",
                target_id=channel_id,
                result_state=str(
                    ObservabilityState.DELETED_CONFIRMED.value
                    if is_delete
                    else (
                        ObservabilityState.OBFUSCATED.value
                        if payload.get("is_obfuscated")
                        else ObservabilityState.VISIBLE.value
                    )
                ),
            )
        if applied and int(payload["type"]) in {10, 11, 12}:
            thread_state = (
                "UNKNOWN"
                if is_delete
                else "ARCHIVED"
                if payload.get("archived") is True
                else "ACTIVE"
            )
            await session.execute(
                text(
                    "UPDATE discord_channels_cache SET thread_active_state=:thread_state "
                    "WHERE guild_id=:guild_id AND channel_id=:channel_id"
                ),
                {
                    "guild_id": envelope.guild_id,
                    "channel_id": channel_id,
                    "thread_state": thread_state,
                },
            )
            if payload.get("current_user_member") is True:
                await self._upsert_current_thread_membership(
                    session,
                    envelope,
                    thread_id=channel_id,
                    user_id=self._bot_user_id,
                    state="MEMBER",
                    source=envelope.event_type,
                )
        return applied

    async def _project_thread_list_sync(
        self, session: AsyncSession, envelope: EventEnvelope
    ) -> None:
        threads = envelope.payload.get("threads", [])
        parent_ids = envelope.payload.get("channel_ids")
        for thread in threads:
            await self._project_channel(session, envelope, thread, audit=False)
        await self._mark_threads_outside_active_sync(
            session,
            envelope,
            thread_ids={int(thread["channel_id"]) for thread in threads},
            parent_ids=None if parent_ids is None else {int(value) for value in parent_ids},
        )
        await self._project_sync_memberships(
            session,
            envelope,
            threads,
            member_rows=envelope.payload.get("members", []),
            absence_is_proof=True,
        )
        await self._record_thread_sync_coverage(
            session,
            envelope,
            parent_ids=None if parent_ids is None else {int(value) for value in parent_ids},
        )

    async def _mark_threads_outside_active_sync(
        self,
        session: AsyncSession,
        envelope: EventEnvelope,
        *,
        thread_ids: set[int],
        parent_ids: set[int] | None,
    ) -> None:
        await session.execute(
            text(
                "UPDATE discord_channels_cache SET thread_active_state='NOT_IN_ACTIVE_SYNC', "
                "observability_state='UNKNOWN', freshness_state='UNKNOWN', "
                "state_version=state_version+1, cache_updated_at=now() "
                "WHERE guild_id=:guild_id AND type IN (10,11,12) "
                "AND deleted_confirmed_at IS NULL "
                "AND (:all_parents OR parent_id = ANY(:parent_ids)) "
                "AND NOT (channel_id = ANY(:thread_ids))"
            ).bindparams(bindparam("parent_ids"), bindparam("thread_ids")),
            {
                "guild_id": envelope.guild_id,
                "all_parents": parent_ids is None,
                "parent_ids": list(parent_ids or []),
                "thread_ids": list(thread_ids),
            },
        )

    async def _project_sync_memberships(
        self,
        session: AsyncSession,
        envelope: EventEnvelope,
        threads: Iterable[dict[str, Any]],
        *,
        member_rows: Iterable[dict[str, Any]],
        absence_is_proof: bool,
    ) -> None:
        if self._bot_user_id is None:
            return
        member_thread_ids = {
            int(row["thread_id"])
            for row in member_rows
            if int(row["discord_user_id"]) == self._bot_user_id
        }
        for thread in threads:
            thread_id = int(thread["channel_id"])
            is_member = bool(thread.get("current_user_member")) or thread_id in member_thread_ids
            if is_member or absence_is_proof:
                await self._upsert_current_thread_membership(
                    session,
                    envelope,
                    thread_id=thread_id,
                    user_id=self._bot_user_id,
                    state="MEMBER" if is_member else "NOT_MEMBER",
                    source=envelope.event_type,
                )

    async def _project_thread_membership_event(
        self, session: AsyncSession, envelope: EventEnvelope
    ) -> None:
        if self._bot_user_id is None:
            return
        if envelope.event_type == "THREAD_MEMBER_UPDATE":
            if int(envelope.payload["discord_user_id"]) != self._bot_user_id:
                return
            await self._upsert_current_thread_membership(
                session,
                envelope,
                thread_id=int(envelope.payload["thread_id"]),
                user_id=self._bot_user_id,
                state="MEMBER",
                source=envelope.event_type,
            )
            return
        thread_id = int(envelope.payload["thread_id"])
        if self._bot_user_id in {int(value) for value in envelope.payload["added_user_ids"]}:
            state = "MEMBER"
        elif self._bot_user_id in {int(value) for value in envelope.payload["removed_user_ids"]}:
            state = "NOT_MEMBER"
        else:
            return
        await self._upsert_current_thread_membership(
            session,
            envelope,
            thread_id=thread_id,
            user_id=self._bot_user_id,
            state=state,
            source=envelope.event_type,
        )

    async def _upsert_current_thread_membership(
        self,
        session: AsyncSession,
        envelope: EventEnvelope,
        *,
        thread_id: int,
        user_id: int | None,
        state: str,
        source: str,
    ) -> None:
        if user_id is None:
            return
        await session.execute(
            text(
                "INSERT INTO discord_current_thread_memberships "
                "(guild_id, thread_id, discord_user_id, membership_state, source, observed_at) "
                "SELECT :guild_id, :thread_id, :user_id, :state, :source, :seen_at "
                "WHERE EXISTS (SELECT 1 FROM discord_channels_cache WHERE guild_id=:guild_id "
                "AND channel_id=:thread_id AND type IN (10,11,12)) "
                "ON CONFLICT (guild_id, thread_id, discord_user_id) DO UPDATE SET "
                "membership_state=EXCLUDED.membership_state, source=EXCLUDED.source, "
                "observed_at=EXCLUDED.observed_at, state_version="
                "discord_current_thread_memberships.state_version+1, updated_at=now()"
            ),
            {
                "guild_id": envelope.guild_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "state": state,
                "source": source,
                "seen_at": envelope.received_at,
            },
        )

    async def _record_thread_sync_coverage(
        self,
        session: AsyncSession,
        envelope: EventEnvelope,
        *,
        parent_ids: set[int] | None,
    ) -> None:
        state = "ACTIVE_VISIBLE_THREADS_FULL" if parent_ids is None else "PARTIAL"
        coverage_mode = "FULL" if envelope.event_type == "GUILD_CREATE" else "PARTIAL"
        await session.execute(
            text(
                "INSERT INTO discord_cache_coverage "
                "(guild_id, coverage_mode, freshness_state, active_threads_coverage, "
                "active_thread_parent_ids, last_active_threads_sync_at) VALUES "
                "(:guild_id, :coverage_mode, 'FRESH', :state, :parent_ids, :seen_at) "
                "ON CONFLICT (guild_id) DO UPDATE SET coverage_mode=CASE WHEN "
                ":coverage_mode='FULL' AND discord_cache_coverage.gateway_continuity NOT IN "
                "('GAP_DETECTED','NON_RESUMED','DISCONNECTED') THEN 'FULL' ELSE "
                "discord_cache_coverage.coverage_mode END, active_threads_coverage=CASE "
                "WHEN EXCLUDED.active_threads_coverage='ACTIVE_VISIBLE_THREADS_FULL' THEN "
                "EXCLUDED.active_threads_coverage WHEN discord_cache_coverage."
                "active_threads_coverage='ACTIVE_VISIBLE_THREADS_FULL' AND "
                "discord_cache_coverage.gateway_continuity NOT IN "
                "('GAP_DETECTED','NON_RESUMED','DISCONNECTED') THEN "
                "discord_cache_coverage.active_threads_coverage ELSE 'PARTIAL' END, "
                "active_thread_parent_ids=EXCLUDED.active_thread_parent_ids, "
                "last_active_threads_sync_at=EXCLUDED.last_active_threads_sync_at, "
                "state_version=discord_cache_coverage.state_version+1, updated_at=now()"
            ).bindparams(bindparam("parent_ids")),
            {
                "guild_id": envelope.guild_id,
                "coverage_mode": coverage_mode,
                "state": state,
                "parent_ids": list(parent_ids or []),
                "seen_at": envelope.received_at,
            },
        )

    def _channel_parameters(
        self, envelope: EventEnvelope, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "guild_id": envelope.guild_id,
            "channel_id": int(payload["channel_id"]),
            "type": int(payload["type"]),
            "name": payload.get("name"),
            "topic": payload.get("topic"),
            "parent_id": payload.get("parent_id"),
            "position": int(payload.get("position", 0)),
            "nsfw": payload.get("nsfw"),
            "flags": int(payload.get("flags", 0)),
            "full_payload": json.dumps(payload, separators=(",", ":")),
            "seen_at": envelope.received_at,
            "sequence": envelope.discord_sequence,
            "session_id": envelope.discord_session_id,
        }

    async def _insert_overwrites(
        self,
        session: AsyncSession,
        *,
        guild_id: int,
        channel_id: int,
        overwrites: Iterable[dict[str, Any]],
        observed_at: datetime,
    ) -> None:
        statement = text(
            "INSERT INTO channel_overwrites_cache "
            "(guild_id, channel_id, target_id, target_type, allow_bits, deny_bits, "
            "last_full_observed_at) VALUES "
            "(:guild_id, :channel_id, :target_id, :target_type, :allow_bits, :deny_bits, "
            ":observed_at)"
        )
        for overwrite in overwrites:
            await session.execute(
                statement,
                {
                    "guild_id": guild_id,
                    "channel_id": channel_id,
                    "target_id": int(overwrite["id"]),
                    "target_type": int(overwrite["type"]),
                    "allow_bits": int(overwrite.get("allow", 0)),
                    "deny_bits": int(overwrite.get("deny", 0)),
                    "observed_at": observed_at,
                },
            )

    async def _project_role(
        self,
        session: AsyncSession,
        envelope: EventEnvelope,
        payload: dict[str, Any],
        *,
        audit: bool = True,
    ) -> bool:
        role_id = int(payload["role_id"])
        if envelope.event_type == "GUILD_ROLE_DELETE":
            result = await session.execute(
                text(
                    "UPDATE discord_roles_cache SET deleted_confirmed_at=:seen_at, "
                    "last_gateway_seen_at=:seen_at, last_gateway_session_id=:session_id, "
                    "last_gateway_sequence=:sequence, state_version=state_version+1, "
                    "cache_updated_at=now() WHERE guild_id=:guild_id AND role_id=:role_id "
                    "AND (last_gateway_session_id IS DISTINCT FROM :session_id OR "
                    "last_gateway_sequence IS NULL OR :sequence >= last_gateway_sequence) "
                    "RETURNING role_id"
                ),
                {
                    "guild_id": envelope.guild_id,
                    "role_id": role_id,
                    "seen_at": envelope.received_at,
                    "session_id": envelope.discord_session_id,
                    "sequence": envelope.discord_sequence,
                },
            )
            applied = result.scalar_one_or_none() is not None
            if applied:
                await self._project_stage08_role_delete(session, envelope, role_id)
            drift_type = "ROLE_DELETED"
        else:
            result = await session.execute(
                text(
                    "INSERT INTO discord_roles_cache "
                    "(guild_id, role_id, name, position, permissions_bits, managed, color, hoist, "
                    "mentionable, raw_json, last_gateway_seen_at, last_gateway_session_id, "
                    "last_gateway_sequence) VALUES "
                    "(:guild_id, :role_id, :name, :position, :permissions, :managed, :color, "
                    ":hoist, :mentionable, CAST(:raw_json AS jsonb), :seen_at, :session_id, "
                    ":sequence) "
                    "ON CONFLICT (guild_id, role_id) DO UPDATE SET name=EXCLUDED.name, "
                    "position=EXCLUDED.position, permissions_bits=EXCLUDED.permissions_bits, "
                    "managed=EXCLUDED.managed, color=EXCLUDED.color, hoist=EXCLUDED.hoist, "
                    "mentionable=EXCLUDED.mentionable, raw_json=EXCLUDED.raw_json, "
                    "last_gateway_seen_at=EXCLUDED.last_gateway_seen_at, "
                    "last_gateway_session_id=:session_id, last_gateway_sequence=:sequence, "
                    "deleted_confirmed_at=NULL, "
                    "state_version=discord_roles_cache.state_version+1, cache_updated_at=now() "
                    "WHERE discord_roles_cache.last_gateway_session_id IS DISTINCT FROM "
                    ":session_id OR discord_roles_cache.last_gateway_sequence IS NULL OR "
                    ":sequence >= discord_roles_cache.last_gateway_sequence "
                    "RETURNING role_id"
                ),
                {
                    "guild_id": envelope.guild_id,
                    "role_id": role_id,
                    "name": payload["name"],
                    "position": payload["position"],
                    "permissions": payload["permissions"],
                    "managed": payload["managed"],
                    "color": payload["color"],
                    "hoist": payload["hoist"],
                    "mentionable": payload["mentionable"],
                    "raw_json": json.dumps(payload, separators=(",", ":")),
                    "seen_at": envelope.received_at,
                    "session_id": envelope.discord_session_id,
                    "sequence": envelope.discord_sequence,
                },
            )
            applied = result.scalar_one_or_none() is not None
            drift_type = (
                "ROLE_MOVED" if envelope.event_type == "GUILD_ROLE_UPDATE" else "ROLE_CREATED"
            )
        if applied:
            await session.execute(
                text(
                    "UPDATE discord_member_authorization_cache SET validity='INVALIDATED', "
                    "invalidated_at=:seen_at, cache_updated_at=now() WHERE guild_id=:guild_id"
                ),
                {"guild_id": envelope.guild_id, "seen_at": envelope.received_at},
            )
        if audit and applied:
            await self._append_audit(
                session,
                envelope,
                event_type=drift_type,
                target_type="ROLE",
                target_id=role_id,
                result_state="OBSERVED",
            )
        return applied

    async def _project_stage08_channel_delete(
        self,
        session: AsyncSession,
        envelope: EventEnvelope,
        channel_id: int,
    ) -> None:
        statements = (
            (
                "CATEGORY_VARIANT",
                "UPDATE translation_category_variants SET state='MISSING',updated_at=now() "
                "WHERE guild_id=:guild_id AND discord_category_id=:resource_id "
                "AND state<>'MISSING' RETURNING id",
            ),
            (
                "CHANNEL_VARIANT",
                "UPDATE translation_channel_variants SET state='MISSING',updated_at=now() "
                "WHERE guild_id=:guild_id AND discord_channel_id=:resource_id "
                "AND state<>'MISSING' RETURNING id",
            ),
        )
        for target_type, statement in statements:
            rows = (
                await session.execute(
                    text(statement),
                    {"guild_id": envelope.guild_id, "resource_id": channel_id},
                )
            ).scalars()
            for variant_id in rows:
                await self._append_audit(
                    session,
                    envelope,
                    event_type="TRANSLATION_VARIANT_MISSING",
                    target_type=target_type,
                    target_id=variant_id,
                    result_state="MISSING",
                )

    async def _project_stage08_role_delete(
        self,
        session: AsyncSession,
        envelope: EventEnvelope,
        role_id: int,
    ) -> None:
        statements = (
            (
                "LANGUAGE_ROLE_BINDING",
                "UPDATE language_profile_roles SET role_state='MISSING',updated_at=now() "
                "WHERE guild_id=:guild_id AND discord_role_id=:resource_id "
                "AND role_state<>'MISSING' RETURNING id",
            ),
            (
                "SCOPE_LANGUAGE_ROLE_BINDING",
                "UPDATE visibility_scope_language_roles SET role_state='MISSING',"
                "updated_at=now() WHERE guild_id=:guild_id AND discord_role_id=:resource_id "
                "AND role_state<>'MISSING' RETURNING id",
            ),
        )
        for target_type, statement in statements:
            rows = (
                await session.execute(
                    text(statement),
                    {"guild_id": envelope.guild_id, "resource_id": role_id},
                )
            ).scalars()
            for binding_id in rows:
                await self._append_audit(
                    session,
                    envelope,
                    event_type="TRANSLATION_ROLE_BINDING_MISSING",
                    target_type=target_type,
                    target_id=binding_id,
                    result_state="MISSING",
                )

    async def _project_member(self, session: AsyncSession, envelope: EventEnvelope) -> None:
        await session.execute(
            text(
                "INSERT INTO discord_member_authorization_cache "
                "(guild_id, discord_user_id, role_ids, is_bot, source, validity, observed_at) "
                "VALUES (:guild_id, :user_id, :role_ids, :is_bot, 'GATEWAY', 'FRESH', :seen_at) "
                "ON CONFLICT (guild_id, discord_user_id) DO UPDATE SET "
                "role_ids=EXCLUDED.role_ids,is_bot=EXCLUDED.is_bot,source='GATEWAY',"
                "validity='FRESH', "
                "observed_at=EXCLUDED.observed_at, invalidated_at=NULL, cache_updated_at=now()"
            ).bindparams(bindparam("role_ids")),
            {
                "guild_id": envelope.guild_id,
                "user_id": int(envelope.payload["discord_user_id"]),
                "role_ids": [int(role_id) for role_id in envelope.payload["role_ids"]],
                "is_bot": bool(envelope.payload.get("is_bot", False)),
                "seen_at": envelope.received_at,
            },
        )

    async def _refresh_member_coverage(
        self, session: AsyncSession, envelope: EventEnvelope, *, delta: int
    ) -> None:
        await session.execute(
            text(
                "UPDATE discord_cache_coverage SET known_members=(SELECT count(*) FROM "
                "discord_member_authorization_cache WHERE guild_id=:guild_id),"
                "member_count=CASE WHEN members_complete THEN (SELECT count(*) FROM "
                "discord_member_authorization_cache WHERE guild_id=:guild_id) ELSE "
                "GREATEST(member_count+:delta,0) END,state_version=state_version+1,"
                "last_gateway_event_at=:seen_at,updated_at=now() WHERE guild_id=:guild_id"
            ),
            {
                "guild_id": envelope.guild_id,
                "delta": delta,
                "seen_at": envelope.received_at,
            },
        )

    async def _refresh_coverage(
        self, session: AsyncSession, guild_id: int, observed_at: datetime
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO discord_cache_coverage "
                "(guild_id, coverage_mode, freshness_state, known_channels, visible_channels, "
                "obfuscated_channels, known_roles, last_gateway_event_at) SELECT "
                ":guild_id, 'PARTIAL', 'FRESH', "
                "(SELECT count(*) FROM discord_channels_cache WHERE guild_id=:guild_id), "
                "(SELECT count(*) FROM discord_channels_cache WHERE guild_id=:guild_id "
                "AND observability_state='VISIBLE'), "
                "(SELECT count(*) FROM discord_channels_cache WHERE guild_id=:guild_id "
                "AND observability_state='OBFUSCATED'), "
                "(SELECT count(*) FROM discord_roles_cache WHERE guild_id=:guild_id "
                "AND deleted_confirmed_at IS NULL), :observed_at "
                "ON CONFLICT (guild_id) DO UPDATE SET "
                "known_channels=EXCLUDED.known_channels, "
                "visible_channels=EXCLUDED.visible_channels, "
                "obfuscated_channels=EXCLUDED.obfuscated_channels, "
                "known_roles=EXCLUDED.known_roles, "
                "last_gateway_event_at=EXCLUDED.last_gateway_event_at, "
                "freshness_state=CASE WHEN discord_cache_coverage.gateway_continuity IN "
                "('GAP_DETECTED','NON_RESUMED') THEN 'STALE' ELSE 'FRESH' END, "
                "coverage_mode=CASE WHEN discord_cache_coverage.gateway_continuity IN "
                "('GAP_DETECTED','NON_RESUMED') THEN 'DEGRADED' "
                "ELSE discord_cache_coverage.coverage_mode END, "
                "state_version=discord_cache_coverage.state_version+1, updated_at=now()"
            ),
            {"guild_id": guild_id, "observed_at": observed_at},
        )

    async def _append_audit(
        self,
        session: AsyncSession,
        envelope: EventEnvelope,
        *,
        event_type: str,
        target_type: str,
        target_id: int | str,
        result_state: str,
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO internal_audit_events "
                "(id, guild_id, source, event_type, target_type, target_id, correlation_id, "
                "causation_id, result_state, data_json, occurred_at) VALUES "
                "(:id, :guild_id, 'DISCORD', :event_type, :target_type, :target_id, "
                ":correlation_id, :causation_id, :result_state, CAST(:data AS jsonb), :occurred_at)"
            ),
            {
                "id": uuid4(),
                "guild_id": envelope.guild_id,
                "event_type": event_type,
                "target_type": target_type,
                "target_id": str(target_id),
                "correlation_id": envelope.correlation_id,
                "causation_id": envelope.event_id,
                "result_state": result_state,
                "data": json.dumps({"origin": envelope.origin.value}),
                "occurred_at": envelope.occurred_at or envelope.received_at,
            },
        )

    async def _append_outbox(
        self,
        session: AsyncSession,
        *,
        guild_id: int,
        topic: str,
        payload: dict[str, Any],
        correlation_id: UUID,
        causation_id: UUID | None,
    ) -> UUID:
        event_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO discord_outbox "
                "(event_id, guild_id, topic, payload, correlation_id, causation_id) VALUES "
                "(:event_id, :guild_id, :topic, CAST(:payload AS jsonb), "
                ":correlation_id, :causation_id)"
            ),
            {
                "event_id": event_id,
                "guild_id": guild_id,
                "topic": topic,
                "payload": json.dumps(payload, separators=(",", ":")),
                "correlation_id": correlation_id,
                "causation_id": causation_id,
            },
        )
        return event_id

    async def channels(
        self,
        guild_id: int,
        actor_user_id: int | None,
        *,
        include_hidden_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT guild_id, channel_id, type, name, topic, parent_id, position, nsfw, "
            "observability_state, is_obfuscated, freshness_state, last_full_observed_at, "
            "last_gateway_seen_at, last_rest_seen_at, last_mutation_confirmed_at, "
            "access_lost_at, obfuscated_at, deleted_confirmed_at, state_version, "
            "cache_updated_at FROM discord_channels_cache WHERE guild_id=:guild_id "
        )
        if not include_hidden_deleted:
            query += "AND observability_state='VISIBLE' "
        query += "ORDER BY position, channel_id"
        async with tenant_transaction(
            self._factory, TenantContext(guild_id, actor_user_id)
        ) as session:
            rows = (
                (
                    await session.execute(
                        text(query),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def apply_rest_channel_snapshot(
        self,
        *,
        guild_id: int,
        channels: Iterable[dict[str, Any]],
        correlation_id: UUID,
        observed_at: datetime | None = None,
    ) -> None:
        observed = observed_at or datetime.now(UTC)
        normalized = list(channels)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            observed_ids: list[int] = []
            for channel in normalized:
                channel_id = int(channel["channel_id"])
                observed_ids.append(channel_id)
                await session.execute(
                    text(
                        "INSERT INTO discord_channels_cache "
                        "(guild_id, channel_id, type, name, topic, parent_id, position, "
                        "nsfw, flags, "
                        "last_full_payload, observability_state, is_obfuscated, freshness_state, "
                        "last_full_observed_at, last_rest_seen_at) VALUES "
                        "(:guild_id, :channel_id, :type, :name, :topic, :parent_id, :position, "
                        ":nsfw, :flags, CAST(:payload AS jsonb), 'VISIBLE', false, 'FRESH', "
                        ":observed_at, :observed_at) ON CONFLICT (guild_id, channel_id) "
                        "DO UPDATE SET "
                        "type=EXCLUDED.type, name=EXCLUDED.name, topic=EXCLUDED.topic, "
                        "parent_id=EXCLUDED.parent_id, position=EXCLUDED.position, "
                        "nsfw=EXCLUDED.nsfw, "
                        "flags=EXCLUDED.flags, last_full_payload=EXCLUDED.last_full_payload, "
                        "observability_state='VISIBLE', is_obfuscated=false, "
                        "freshness_state='FRESH', "
                        "last_full_observed_at=EXCLUDED.last_full_observed_at, "
                        "last_rest_seen_at=EXCLUDED.last_rest_seen_at, access_lost_at=NULL, "
                        "obfuscated_at=NULL, deleted_confirmed_at=NULL, "
                        "state_version=discord_channels_cache.state_version+1, "
                        "cache_updated_at=now()"
                    ),
                    {
                        "guild_id": guild_id,
                        "channel_id": channel_id,
                        "type": int(channel["type"]),
                        "name": channel.get("name"),
                        "topic": channel.get("topic"),
                        "parent_id": channel.get("parent_id"),
                        "position": int(channel.get("position", 0)),
                        "nsfw": channel.get("nsfw"),
                        "flags": int(channel.get("flags", 0)),
                        "payload": json.dumps(channel, separators=(",", ":")),
                        "observed_at": observed,
                    },
                )
                reobserved = await session.scalar(
                    text(
                        "DELETE FROM discord_channel_tombstones "
                        "WHERE guild_id=:guild_id AND channel_id=:channel_id "
                        "RETURNING channel_id"
                    ),
                    {"guild_id": guild_id, "channel_id": channel_id},
                )
                if reobserved is not None:
                    await session.execute(
                        text(
                            "INSERT INTO internal_audit_events "
                            "(id, guild_id, source, event_type, target_type, target_id, "
                            "correlation_id, result_state, data_json, occurred_at) VALUES "
                            "(:id, :guild_id, 'DISCORD', 'PURGED_RESOURCE_REOBSERVED', "
                            "'CHANNEL', :target_id, :correlation_id, 'VISIBLE', "
                            "CAST(:data AS jsonb), :occurred_at)"
                        ),
                        {
                            "id": uuid4(),
                            "guild_id": guild_id,
                            "target_id": str(channel_id),
                            "correlation_id": correlation_id,
                            "data": json.dumps({"origin": "RECONCILE", "source": "TARGETED_REST"}),
                            "occurred_at": observed,
                        },
                    )
                await session.execute(
                    text(
                        "DELETE FROM channel_overwrites_cache "
                        "WHERE guild_id=:guild_id AND channel_id=:channel_id"
                    ),
                    {"guild_id": guild_id, "channel_id": channel_id},
                )
                await self._insert_overwrites(
                    session,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    overwrites=channel.get("permission_overwrites", []),
                    observed_at=observed,
                )
            if observed_ids:
                await session.execute(
                    text(
                        "UPDATE discord_channels_cache SET observability_state='ACCESS_LOST', "
                        "is_obfuscated=false, freshness_state='AGING', "
                        "access_lost_at=COALESCE(access_lost_at, :observed_at), "
                        "cache_updated_at=now(), "
                        "state_version=state_version+1 WHERE guild_id=:guild_id "
                        "AND observability_state='VISIBLE' "
                        "AND NOT (channel_id = ANY(:observed_ids))"
                    ),
                    {"guild_id": guild_id, "observed_at": observed, "observed_ids": observed_ids},
                )
            else:
                await session.execute(
                    text(
                        "UPDATE discord_channels_cache SET observability_state='ACCESS_LOST', "
                        "is_obfuscated=false, freshness_state='AGING', "
                        "access_lost_at=COALESCE(access_lost_at, :observed_at), "
                        "cache_updated_at=now(), "
                        "state_version=state_version+1 WHERE guild_id=:guild_id "
                        "AND observability_state='VISIBLE'"
                    ),
                    {"guild_id": guild_id, "observed_at": observed},
                )
            await session.execute(
                text(
                    "INSERT INTO discord_cache_coverage "
                    "(guild_id, coverage_mode, freshness_state, last_full_reconcile_at, "
                    "last_successful_rest_sync_at) VALUES "
                    "(:guild_id, 'PARTIAL', 'FRESH', :observed_at, :observed_at) "
                    "ON CONFLICT (guild_id) DO UPDATE SET freshness_state=CASE "
                    "WHEN discord_cache_coverage.gateway_continuity IN "
                    "('GAP_DETECTED','NON_RESUMED') THEN 'STALE' ELSE 'FRESH' END, "
                    "coverage_mode=CASE WHEN discord_cache_coverage.gateway_continuity IN "
                    "('GAP_DETECTED','NON_RESUMED') THEN 'DEGRADED' "
                    "ELSE discord_cache_coverage.coverage_mode END, "
                    "last_full_reconcile_at=EXCLUDED.last_full_reconcile_at, "
                    "last_successful_rest_sync_at=EXCLUDED.last_successful_rest_sync_at, "
                    "state_version=discord_cache_coverage.state_version+1, updated_at=now()"
                ),
                {"guild_id": guild_id, "observed_at": observed},
            )
            await self._append_outbox(
                session,
                guild_id=guild_id,
                topic="discord.cache.reconciled",
                payload={"guild_id": str(guild_id), "resource_type": "channels"},
                correlation_id=correlation_id,
                causation_id=None,
            )

    async def purge_channels(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        channel_ids: Iterable[int],
        correlation_id: UUID,
        user_confirmed_deleted: bool,
    ) -> int:
        targets = sorted(set(channel_ids))
        if not targets or len(targets) > 500:
            raise ValueError("purge requires between 1 and 500 unique channel IDs")
        allowed = {
            ObservabilityState.OBFUSCATED.value,
            ObservabilityState.ACCESS_LOST.value,
            ObservabilityState.DELETED_CONFIRMED.value,
            ObservabilityState.USER_CONFIRMED_DELETED.value,
        }
        async with tenant_transaction(
            self._factory, TenantContext(guild_id, actor_user_id)
        ) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT channel_id, type, parent_id, position, observability_state, "
                            "deleted_confirmed_at "
                            "FROM discord_channels_cache WHERE guild_id=:guild_id "
                            "AND channel_id = ANY(:channel_ids) FOR UPDATE"
                        ),
                        {"guild_id": guild_id, "channel_ids": targets},
                    )
                )
                .mappings()
                .all()
            )
            if len(rows) != len(targets) or any(
                row["observability_state"] not in allowed for row in rows
            ):
                raise ValueError(
                    "purge targets must be known non-visible or confirmed-deleted channels"
                )
            requires_confirmation = any(
                row["observability_state"]
                in {
                    ObservabilityState.OBFUSCATED.value,
                    ObservabilityState.ACCESS_LOST.value,
                }
                for row in rows
            )
            if requires_confirmation and not user_confirmed_deleted:
                raise ValueError(
                    "obfuscated or access-lost channels require explicit deletion confirmation"
                )
            now = datetime.now(UTC)
            for row in rows:
                metadata = f"{row['channel_id']}:{row['type']}:{row['parent_id']}:{row['position']}"
                metadata_hash = hashlib.sha256(metadata.encode()).hexdigest()
                current_state = str(row["observability_state"])
                user_confirmed = current_state in {
                    ObservabilityState.OBFUSCATED.value,
                    ObservabilityState.ACCESS_LOST.value,
                    ObservabilityState.USER_CONFIRMED_DELETED.value,
                }
                reason = (
                    ObservabilityState.USER_CONFIRMED_DELETED.value
                    if user_confirmed
                    else ObservabilityState.DELETED_CONFIRMED.value
                )
                if user_confirmed and current_state != ObservabilityState.USER_CONFIRMED_DELETED:
                    await session.execute(
                        text(
                            "UPDATE discord_channels_cache SET "
                            "observability_state='USER_CONFIRMED_DELETED', "
                            "deleted_confirmed_at=:now, state_version=state_version+1, "
                            "cache_updated_at=now() WHERE guild_id=:guild_id "
                            "AND channel_id=:channel_id"
                        ),
                        {
                            "guild_id": guild_id,
                            "channel_id": row["channel_id"],
                            "now": now,
                        },
                    )
                    await session.execute(
                        text(
                            "INSERT INTO internal_audit_events "
                            "(id, guild_id, actor_user_id, source, event_type, target_type, "
                            "target_id, correlation_id, result_state, data_json, occurred_at) "
                            "VALUES (:id, :guild_id, :actor, 'DASHBOARD', "
                            "'CHANNEL_USER_CONFIRMED_DELETED', 'CHANNEL', :target_id, "
                            ":correlation_id, 'USER_CONFIRMED_DELETED', "
                            "CAST(:data AS jsonb), :now)"
                        ),
                        {
                            "id": uuid4(),
                            "guild_id": guild_id,
                            "actor": actor_user_id,
                            "target_id": str(row["channel_id"]),
                            "correlation_id": correlation_id,
                            "data": json.dumps({"previous_state": current_state}),
                            "now": now,
                        },
                    )
                await session.execute(
                    text(
                        "INSERT INTO discord_channel_tombstones "
                        "(guild_id, channel_id, resource_type, reason, confirmed_by_user_id, "
                        "confirmed_at, purged_at, last_known_parent_id, last_known_type, "
                        "last_known_position, metadata_hash) VALUES "
                        "(:guild_id, :channel_id, :resource_type, :reason, "
                        ":confirmed_by, :confirmed_at, :now, :parent_id, :type, :position, "
                        ":metadata_hash) "
                        "ON CONFLICT (guild_id, channel_id) DO UPDATE SET "
                        "reason=EXCLUDED.reason, "
                        "confirmed_by_user_id=EXCLUDED.confirmed_by_user_id, "
                        "confirmed_at=EXCLUDED.confirmed_at, purged_at=EXCLUDED.purged_at, "
                        "metadata_hash=EXCLUDED.metadata_hash"
                    ),
                    {
                        "guild_id": guild_id,
                        "channel_id": row["channel_id"],
                        "resource_type": "CATEGORY" if row["type"] == 4 else "CHANNEL",
                        "reason": reason,
                        "confirmed_by": actor_user_id if user_confirmed else None,
                        "confirmed_at": row["deleted_confirmed_at"] or now,
                        "now": now,
                        "parent_id": row["parent_id"],
                        "type": row["type"],
                        "position": row["position"],
                        "metadata_hash": metadata_hash,
                    },
                )
            await session.execute(
                text(
                    "DELETE FROM channel_overwrites_cache WHERE guild_id=:guild_id "
                    "AND channel_id = ANY(:channel_ids)"
                ),
                {"guild_id": guild_id, "channel_ids": targets},
            )
            await session.execute(
                text(
                    "DELETE FROM discord_channels_cache WHERE guild_id=:guild_id "
                    "AND channel_id = ANY(:channel_ids)"
                ),
                {"guild_id": guild_id, "channel_ids": targets},
            )
            await session.execute(
                text(
                    "INSERT INTO internal_audit_events "
                    "(id, guild_id, actor_user_id, source, event_type, target_type, target_id, "
                    "correlation_id, result_state, data_json, occurred_at) VALUES "
                    "(:id, :guild_id, :actor, 'DASHBOARD', 'CHANNEL_CACHE_PURGED', 'CHANNEL_SET', "
                    ":target_id, :correlation_id, 'PURGED_TOMBSTONE', CAST(:data AS jsonb), :now)"
                ),
                {
                    "id": uuid4(),
                    "guild_id": guild_id,
                    "actor": actor_user_id,
                    "target_id": ",".join(str(item) for item in targets),
                    "correlation_id": correlation_id,
                    "data": json.dumps({"count": len(targets)}),
                    "now": now,
                },
            )
            await self._append_outbox(
                session,
                guild_id=guild_id,
                topic="discord.cache.purged",
                payload={"guild_id": str(guild_id), "count": len(targets)},
                correlation_id=correlation_id,
                causation_id=None,
            )
            return len(targets)

    async def apply_rest_role_snapshot(
        self,
        *,
        guild_id: int,
        roles: Iterable[dict[str, Any]],
        correlation_id: UUID,
        observed_at: datetime | None = None,
    ) -> None:
        observed = observed_at or datetime.now(UTC)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            for role in roles:
                await session.execute(
                    text(
                        "INSERT INTO discord_roles_cache "
                        "(guild_id, role_id, name, position, permissions_bits, managed, "
                        "color, hoist, "
                        "mentionable, raw_json, last_rest_seen_at) VALUES "
                        "(:guild_id, :role_id, :name, :position, :permissions, :managed, :color, "
                        ":hoist, :mentionable, CAST(:raw_json AS jsonb), :observed_at) "
                        "ON CONFLICT (guild_id, role_id) DO UPDATE SET name=EXCLUDED.name, "
                        "position=EXCLUDED.position, permissions_bits=EXCLUDED.permissions_bits, "
                        "managed=EXCLUDED.managed, color=EXCLUDED.color, hoist=EXCLUDED.hoist, "
                        "mentionable=EXCLUDED.mentionable, raw_json=EXCLUDED.raw_json, "
                        "last_rest_seen_at=EXCLUDED.last_rest_seen_at, deleted_confirmed_at=NULL, "
                        "state_version=discord_roles_cache.state_version+1, cache_updated_at=now()"
                    ),
                    {
                        "guild_id": guild_id,
                        "role_id": int(role["role_id"]),
                        "name": str(role["name"]),
                        "position": int(role.get("position", 0)),
                        "permissions": int(role.get("permissions", 0)),
                        "managed": bool(role.get("managed", False)),
                        "color": int(role.get("color", 0)),
                        "hoist": bool(role.get("hoist", False)),
                        "mentionable": bool(role.get("mentionable", False)),
                        "raw_json": json.dumps(role, separators=(",", ":")),
                        "observed_at": observed,
                    },
                )
            await session.execute(
                text(
                    "INSERT INTO discord_cache_coverage "
                    "(guild_id, coverage_mode, freshness_state, known_roles, "
                    "last_successful_rest_sync_at) VALUES "
                    "(:guild_id, 'PARTIAL', 'FRESH', "
                    "(SELECT count(*) FROM discord_roles_cache WHERE guild_id=:guild_id "
                    "AND deleted_confirmed_at IS NULL), :observed_at) "
                    "ON CONFLICT (guild_id) DO UPDATE SET known_roles=EXCLUDED.known_roles, "
                    "freshness_state=CASE WHEN discord_cache_coverage.gateway_continuity IN "
                    "('GAP_DETECTED','NON_RESUMED') THEN 'STALE' ELSE 'FRESH' END, "
                    "coverage_mode=CASE WHEN discord_cache_coverage.gateway_continuity IN "
                    "('GAP_DETECTED','NON_RESUMED') THEN 'DEGRADED' "
                    "ELSE discord_cache_coverage.coverage_mode END, "
                    "last_successful_rest_sync_at=EXCLUDED.last_successful_rest_sync_at, "
                    "state_version=discord_cache_coverage.state_version+1, updated_at=now()"
                ),
                {"guild_id": guild_id, "observed_at": observed},
            )
            await self._append_outbox(
                session,
                guild_id=guild_id,
                topic="discord.cache.roles.reconciled",
                payload={"guild_id": str(guild_id), "resource_type": "roles"},
                correlation_id=correlation_id,
                causation_id=None,
            )

    async def apply_complete_rest_member_snapshot(
        self,
        *,
        guild_id: int,
        members: Iterable[dict[str, Any]],
        correlation_id: UUID,
        observed_at: datetime | None = None,
    ) -> int:
        """Replace member authorization cache after a fully paginated Discord REST listing."""
        observed = observed_at or datetime.now(UTC)
        rows = tuple(members)
        member_ids = [int(row["discord_user_id"]) for row in rows]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("complete member snapshot contains duplicate users")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await session.execute(
                text("DELETE FROM discord_member_authorization_cache WHERE guild_id=:guild_id"),
                {"guild_id": guild_id},
            )
            for member in rows:
                await session.execute(
                    text(
                        "INSERT INTO discord_member_authorization_cache "
                        "(guild_id,discord_user_id,role_ids,is_bot,source,validity,observed_at) "
                        "VALUES (:guild_id,:user_id,:role_ids,:is_bot,'FULL_REST_LIST','FRESH',"
                        ":observed_at)"
                    ).bindparams(bindparam("role_ids")),
                    {
                        "guild_id": guild_id,
                        "user_id": int(member["discord_user_id"]),
                        "role_ids": sorted({int(value) for value in member.get("role_ids", [])}),
                        "is_bot": bool(member.get("is_bot", False)),
                        "observed_at": observed,
                    },
                )
            await session.execute(
                text(
                    "INSERT INTO discord_cache_coverage "
                    "(guild_id,coverage_mode,freshness_state,known_members,member_count,"
                    "members_complete,last_full_member_sync_at,last_successful_rest_sync_at) "
                    "VALUES (:guild_id,'PARTIAL','FRESH',:count,:count,true,:observed_at,"
                    ":observed_at) ON CONFLICT (guild_id) DO UPDATE SET "
                    "known_members=:count,member_count=:count,members_complete=true,"
                    "last_full_member_sync_at=:observed_at,"
                    "last_successful_rest_sync_at=:observed_at,"
                    "freshness_state=CASE WHEN discord_cache_coverage.gateway_continuity IN "
                    "('GAP_DETECTED','NON_RESUMED','DISCONNECTED') THEN 'STALE' ELSE 'FRESH' END,"
                    "state_version=discord_cache_coverage.state_version+1,updated_at=now()"
                ),
                {
                    "guild_id": guild_id,
                    "count": len(rows),
                    "observed_at": observed,
                },
            )
            await self._append_outbox(
                session,
                guild_id=guild_id,
                topic="discord.cache.members.reconciled",
                payload={
                    "guild_id": str(guild_id),
                    "resource_type": "members",
                    "count": len(rows),
                    "complete": True,
                },
                correlation_id=correlation_id,
                causation_id=None,
            )
        return len(rows)

    async def mark_structure_sync_complete(
        self, guild_id: int, *, completed_at: datetime | None = None
    ) -> None:
        completed = completed_at or datetime.now(UTC)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await session.execute(
                text(
                    "UPDATE discord_cache_coverage SET coverage_mode='FULL', "
                    "freshness_state='FRESH', gateway_continuity='CONNECTED', "
                    "last_full_reconcile_at=:completed, "
                    "state_version=state_version+1, updated_at=now() WHERE guild_id=:guild_id"
                ),
                {"guild_id": guild_id, "completed": completed},
            )
            await session.execute(
                text(
                    "INSERT INTO discord_reconcile_checkpoints "
                    "(guild_id, resource_type, checkpoint, status, last_attempt_at, "
                    "last_success_at, next_due_at, attempt_count) VALUES "
                    "(:guild_id, 'STRUCTURE', CAST(:checkpoint AS jsonb), 'SUCCEEDED', "
                    ":completed, :completed, NULL, 1) ON CONFLICT (guild_id, resource_type) "
                    "DO UPDATE SET checkpoint=EXCLUDED.checkpoint, status='SUCCEEDED', "
                    "last_attempt_at=EXCLUDED.last_attempt_at, "
                    "last_success_at=EXCLUDED.last_success_at, attempt_count="
                    "discord_reconcile_checkpoints.attempt_count+1, updated_at=now()"
                ),
                {
                    "guild_id": guild_id,
                    "checkpoint": json.dumps({"schema_version": 1, "complete": True}),
                    "completed": completed,
                },
            )

    async def record_gateway_discontinuity(
        self,
        *,
        guild_id: int,
        continuity: str,
        correlation_id: UUID,
    ) -> None:
        if continuity not in {"GAP_DETECTED", "NON_RESUMED", "DISCONNECTED"}:
            raise ValueError("only unsafe Gateway continuity states mark cache stale")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await session.execute(
                text(
                    "INSERT INTO discord_cache_coverage "
                    "(guild_id, coverage_mode, freshness_state, gateway_continuity) VALUES "
                    "(:guild_id, 'DEGRADED', 'STALE', :continuity) "
                    "ON CONFLICT (guild_id) DO UPDATE SET coverage_mode='DEGRADED', "
                    "freshness_state='STALE', gateway_continuity=EXCLUDED.gateway_continuity, "
                    "active_threads_coverage='DEGRADED', "
                    "state_version=discord_cache_coverage.state_version+1, updated_at=now()"
                ),
                {"guild_id": guild_id, "continuity": continuity},
            )
            await session.execute(
                text(
                    "UPDATE discord_channels_cache SET freshness_state='STALE', "
                    "cache_updated_at=now() WHERE guild_id=:guild_id"
                ),
                {"guild_id": guild_id},
            )
            await session.execute(
                text(
                    "INSERT INTO internal_audit_events "
                    "(id, guild_id, source, event_type, target_type, target_id, correlation_id, "
                    "result_state, data_json, occurred_at) VALUES "
                    "(:id, :guild_id, 'SYSTEM', 'CACHE_STALE_AFTER_GATEWAY_GAP', 'GUILD', "
                    ":target_id, :correlation_id, :continuity, CAST('{}' AS jsonb), now())"
                ),
                {
                    "id": uuid4(),
                    "guild_id": guild_id,
                    "target_id": str(guild_id),
                    "correlation_id": correlation_id,
                    "continuity": continuity,
                },
            )

    async def _runtime_guild_ids(self, function_name: str, *, limit: int) -> list[int]:
        if function_name not in {
            "runtime_job_guilds",
            "runtime_outbox_guilds",
            "runtime_reconcile_guilds",
        }:
            raise ValueError("runtime routing function is not allowlisted")
        if not 1 <= limit <= 1000:
            raise ValueError("runtime routing limit must be between 1 and 1000")
        statements = {
            "runtime_job_guilds": text("SELECT guild_id FROM app.runtime_job_guilds(:limit)"),
            "runtime_outbox_guilds": text("SELECT guild_id FROM app.runtime_outbox_guilds(:limit)"),
            "runtime_reconcile_guilds": text(
                "SELECT guild_id FROM app.runtime_reconcile_guilds(:limit)"
            ),
        }
        async with tenant_transaction(self._factory, None) as session:
            rows = (
                await session.execute(
                    statements[function_name],
                    {"limit": limit},
                )
            ).scalars()
            return [int(guild_id) for guild_id in rows]

    async def runtime_job_guilds(self, *, limit: int = 256) -> list[int]:
        return await self._runtime_guild_ids("runtime_job_guilds", limit=limit)

    async def runtime_outbox_guilds(self, *, limit: int = 256) -> list[int]:
        return await self._runtime_guild_ids("runtime_outbox_guilds", limit=limit)

    async def runtime_reconcile_guilds(self, *, limit: int = 256) -> list[int]:
        return await self._runtime_guild_ids("runtime_reconcile_guilds", limit=limit)

    async def reconcile_signals(self, guild_id: int, *, rate_limit_pressure: float) -> Any:
        from did.application.reconciliation.scheduler import ReconcileSignals

        if not 0.0 <= rate_limit_pressure <= 1.0:
            raise ValueError("rate-limit pressure must be between 0 and 1")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT installations.last_gateway_seen_at, "
                            "coverage.coverage_mode, coverage.gateway_continuity, "
                            "checkpoints.last_success_at, "
                            "EXISTS (SELECT 1 FROM discord_io_jobs jobs "
                            "WHERE jobs.guild_id=:guild_id AND jobs.status IN ('PENDING','LEASED') "
                            "AND jobs.priority <= 2) AS pending_critical_work, "
                            "(SELECT count(*) FROM internal_audit_events audit "
                            "WHERE audit.guild_id=:guild_id "
                            "AND audit.event_type IN ('CHANNEL_CREATED_OUTSIDE_PLATFORM', "
                            "'CHANNEL_PERMISSION_CHANGED','ROLE_MOVED','ROLE_DELETED') "
                            "AND audit.occurred_at >= now() - interval '24 hours') AS drift_count "
                            "FROM guild_installations installations "
                            "LEFT JOIN discord_cache_coverage coverage "
                            "ON coverage.guild_id=installations.guild_id "
                            "LEFT JOIN discord_reconcile_checkpoints checkpoints "
                            "ON checkpoints.guild_id=installations.guild_id "
                            "AND checkpoints.resource_type='STRUCTURE' "
                            "WHERE installations.guild_id=:guild_id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .one()
            )
        last_gateway = row["last_gateway_seen_at"]
        active = last_gateway is not None and last_gateway >= datetime.now(UTC) - timedelta(hours=1)
        continuity = str(row["gateway_continuity"] or "DISCONNECTED")
        return ReconcileSignals(
            guild_id=guild_id,
            last_reconcile_at=row["last_success_at"],
            active=active,
            gateway_gap=continuity == "GAP_DETECTED",
            non_resumed=continuity == "NON_RESUMED",
            pending_critical_work=bool(row["pending_critical_work"]),
            drift_count=int(row["drift_count"]),
            coverage_degraded=str(row["coverage_mode"] or "DEGRADED") == "DEGRADED",
            rate_limit_pressure=rate_limit_pressure,
        )

    async def enqueue_job(
        self, job: WorkloadJob, *, requested_by: int | None, correlation_id: UUID
    ) -> UUID:
        async with tenant_transaction(
            self._factory, TenantContext(job.guild_id, requested_by)
        ) as session:
            inserted = await session.scalar(
                text(
                    "INSERT INTO discord_io_jobs "
                    "(job_id, guild_id, workload_type, logical_key, priority, payload, "
                    "requested_by, correlation_id, available_at) VALUES "
                    "(:job_id, :guild_id, :workload_type, :logical_key, :priority, "
                    "CAST(:payload AS jsonb), :requested_by, :correlation_id, :available_at) "
                    "ON CONFLICT (guild_id, logical_key) "
                    "WHERE status IN ('PENDING','LEASED') DO NOTHING RETURNING job_id"
                ),
                {
                    "job_id": job.job_id,
                    "guild_id": job.guild_id,
                    "workload_type": job.workload_type,
                    "logical_key": job.logical_key,
                    "priority": int(job.priority),
                    "payload": json.dumps(job.payload, separators=(",", ":")),
                    "requested_by": requested_by,
                    "correlation_id": correlation_id,
                    "available_at": job.enqueued_at,
                },
            )
            if inserted is None:
                existing = await session.scalar(
                    text(
                        "SELECT job_id FROM discord_io_jobs WHERE guild_id=:guild_id "
                        "AND logical_key=:logical_key AND status IN ('PENDING','LEASED') "
                        "ORDER BY created_at LIMIT 1"
                    ),
                    {"guild_id": job.guild_id, "logical_key": job.logical_key},
                )
                if existing is None:
                    raise RuntimeError("active workload coalescing conflict was not recoverable")
                return UUID(str(existing))
            self.metrics.job_submitted(job.priority)
            await self._append_outbox(
                session,
                guild_id=job.guild_id,
                topic="discord.io.job.enqueued",
                payload={"job_id": str(job.job_id), "guild_id": str(job.guild_id)},
                correlation_id=correlation_id,
                causation_id=None,
            )
            return job.job_id

    async def pending_outbox(self, guild_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT event_id, guild_id, topic, payload, correlation_id, "
                            "causation_id "
                            "FROM discord_outbox WHERE guild_id=:guild_id AND status='PENDING' "
                            "AND next_attempt_at <= now() AND "
                            "(leased_until IS NULL OR leased_until < now()) "
                            "ORDER BY created_at LIMIT :limit"
                        ),
                        {"guild_id": guild_id, "limit": limit},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def lease_outbox(
        self,
        guild_id: int,
        *,
        lease_owner: str,
        limit: int = 100,
        lease_seconds: float = 30.0,
    ) -> list[dict[str, Any]]:
        if not lease_owner or len(lease_owner) > 128:
            raise ValueError("outbox lease owner must be present and bounded")
        if not 1 <= limit <= 1000 or lease_seconds < 0.05:
            raise ValueError("outbox lease limit and duration must be bounded")
        lease_token = uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "WITH candidates AS (SELECT event_id FROM discord_outbox "
                            "WHERE guild_id=:guild_id AND status='PENDING' "
                            "AND next_attempt_at <= now() AND "
                            "(leased_until IS NULL OR leased_until < now()) "
                            "ORDER BY created_at LIMIT :limit FOR UPDATE SKIP LOCKED) "
                            "UPDATE discord_outbox AS outbox SET lease_owner=:owner, "
                            "lease_token=:token, leased_until=now() + "
                            "(:lease_seconds * interval '1 second') FROM candidates "
                            "WHERE outbox.event_id=candidates.event_id RETURNING "
                            "outbox.event_id, outbox.guild_id, outbox.topic, outbox.payload, "
                            "outbox.correlation_id, outbox.causation_id, outbox.lease_token"
                        ),
                        {
                            "guild_id": guild_id,
                            "owner": lease_owner,
                            "token": lease_token,
                            "lease_seconds": lease_seconds,
                            "limit": limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def lease_next_job(
        self, guild_id: int, *, lease_owner: str, lease_seconds: float = 30.0
    ) -> dict[str, Any] | None:
        if not lease_owner or len(lease_owner) > 128 or lease_seconds < 0.05:
            raise ValueError("job lease owner and duration must be bounded")
        lease_token = uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "WITH candidate AS (SELECT job_id FROM discord_io_jobs "
                            "WHERE guild_id=:guild_id AND available_at <= now() AND "
                            "(status='PENDING' OR (status='LEASED' AND leased_until < now())) "
                            "ORDER BY priority, available_at, created_at LIMIT 1 "
                            "FOR UPDATE SKIP LOCKED) UPDATE discord_io_jobs AS jobs SET "
                            "status='LEASED', lease_owner=:owner, lease_token=:token, "
                            "leased_until=now() + (:lease_seconds * interval '1 second'), "
                            "lease_generation=lease_generation+1, "
                            "attempt_count=attempt_count+1, updated_at=now() FROM candidate "
                            "WHERE jobs.job_id=candidate.job_id RETURNING jobs.job_id, "
                            "jobs.guild_id, jobs.workload_type, jobs.logical_key, jobs.priority, "
                            "jobs.payload, jobs.requested_by, jobs.correlation_id, "
                            "jobs.attempt_count, "
                            "jobs.created_at, jobs.lease_token, jobs.lease_generation, "
                            "jobs.leased_until"
                        ),
                        {
                            "guild_id": guild_id,
                            "owner": lease_owner,
                            "token": lease_token,
                            "lease_seconds": lease_seconds,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    async def renew_outbox_lease(
        self,
        guild_id: int,
        event_id: UUID,
        *,
        lease_owner: str,
        lease_token: UUID,
        lease_seconds: float,
    ) -> bool:
        if lease_seconds < 0.05:
            raise ValueError("outbox lease duration must be at least 50ms")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            updated = await session.scalar(
                text(
                    "UPDATE discord_outbox SET leased_until=now() + "
                    "(:lease_seconds * interval '1 second') "
                    "WHERE guild_id=:guild_id AND event_id=:event_id AND status='PENDING' "
                    "AND lease_owner=:owner AND lease_token=:token RETURNING event_id"
                ),
                {
                    "guild_id": guild_id,
                    "event_id": event_id,
                    "owner": lease_owner,
                    "token": lease_token,
                    "lease_seconds": lease_seconds,
                },
            )
        return updated is not None

    async def renew_job_lease(
        self,
        guild_id: int,
        job_id: UUID,
        *,
        lease_owner: str,
        lease_token: UUID,
        lease_seconds: float,
    ) -> bool:
        if lease_seconds < 0.05:
            raise ValueError("job lease duration must be at least 50ms")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            updated = await session.scalar(
                text(
                    "UPDATE discord_io_jobs SET leased_until=now() + "
                    "(:lease_seconds * interval '1 second'), updated_at=now() "
                    "WHERE guild_id=:guild_id AND job_id=:job_id AND status='LEASED' "
                    "AND lease_owner=:owner AND lease_token=:token RETURNING job_id"
                ),
                {
                    "guild_id": guild_id,
                    "job_id": job_id,
                    "owner": lease_owner,
                    "token": lease_token,
                    "lease_seconds": lease_seconds,
                },
            )
        return updated is not None

    async def complete_job(
        self,
        guild_id: int,
        job_id: UUID,
        *,
        lease_owner: str,
        lease_token: UUID,
    ) -> bool:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            updated = await session.scalar(
                text(
                    "UPDATE discord_io_jobs SET status='SUCCEEDED', leased_until=NULL, "
                    "lease_owner=NULL, lease_token=NULL, updated_at=now() "
                    "WHERE guild_id=:guild_id AND job_id=:job_id AND status='LEASED' "
                    "AND lease_owner=:owner AND lease_token=:token "
                    "AND leased_until > now() "
                    "RETURNING job_id"
                ),
                {
                    "guild_id": guild_id,
                    "job_id": job_id,
                    "owner": lease_owner,
                    "token": lease_token,
                },
            )
        return updated is not None

    async def retry_job(
        self,
        guild_id: int,
        job_id: UUID,
        *,
        lease_owner: str,
        lease_token: UUID,
        retry_after_seconds: float | None,
        terminal: bool,
    ) -> bool:
        delay = max(0.0, min(retry_after_seconds or 0.0, 3600.0))
        status = "FAILED" if terminal else "PENDING"
        available_at = datetime.now(UTC) + timedelta(seconds=delay)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            updated = await session.scalar(
                text(
                    "UPDATE discord_io_jobs SET status=:status, available_at=:available_at, "
                    "leased_until=NULL, lease_owner=NULL, lease_token=NULL, updated_at=now() "
                    "WHERE guild_id=:guild_id AND job_id=:job_id AND status='LEASED' "
                    "AND lease_owner=:owner AND lease_token=:token "
                    "AND leased_until > now() RETURNING job_id"
                ),
                {
                    "status": status,
                    "available_at": available_at,
                    "guild_id": guild_id,
                    "job_id": job_id,
                    "owner": lease_owner,
                    "token": lease_token,
                },
            )
        return updated is not None

    async def mark_outbox_published(
        self,
        guild_id: int,
        event_id: UUID,
        *,
        lease_owner: str,
        lease_token: UUID,
    ) -> bool:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            updated = await session.scalar(
                text(
                    "UPDATE discord_outbox SET status='PUBLISHED', published_at=now(), "
                    "attempt_count=attempt_count+1, lease_owner=NULL, lease_token=NULL, "
                    "leased_until=NULL WHERE guild_id=:guild_id AND event_id=:event_id "
                    "AND status='PENDING' AND lease_owner=:owner AND lease_token=:token "
                    "AND leased_until > now() RETURNING event_id"
                ),
                {
                    "guild_id": guild_id,
                    "event_id": event_id,
                    "owner": lease_owner,
                    "token": lease_token,
                },
            )
        return updated is not None

    async def mark_outbox_retry(
        self,
        guild_id: int,
        event_id: UUID,
        *,
        lease_owner: str,
        lease_token: UUID,
    ) -> bool:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            updated = await session.scalar(
                text(
                    "UPDATE discord_outbox SET attempt_count=attempt_count+1, "
                    "next_attempt_at=now() + "
                    "(LEAST(300, power(2, LEAST(attempt_count, 8))) * interval '1 second'), "
                    "lease_owner=NULL, lease_token=NULL, leased_until=NULL "
                    "WHERE guild_id=:guild_id AND event_id=:event_id AND status='PENDING' "
                    "AND lease_owner=:owner AND lease_token=:token RETURNING event_id"
                ),
                {
                    "guild_id": guild_id,
                    "event_id": event_id,
                    "owner": lease_owner,
                    "token": lease_token,
                },
            )
        return updated is not None
