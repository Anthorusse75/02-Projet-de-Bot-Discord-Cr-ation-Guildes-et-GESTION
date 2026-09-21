from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from did.domain.policies import (
    Policy,
    PolicyLifecycleError,
    PolicyLifecycleState,
    PolicyScopeType,
    PolicyTemporaryAccess,
    PolicyVersion,
    TemporaryAccessState,
)
from did.infrastructure.database import tenant_transaction
from did.tenancy import TenantContext

_UPDATE_POLICY_SQL = (
    "UPDATE policies SET name=:name,description=:description,"
    "lifecycle_state=:lifecycle_state,revision=:revision,priority=:priority,locked=:locked,"
    "scope_type=:scope_type,"
    "scope_id=:scope_id,conditions_json=CAST(:conditions AS jsonb),"
    "effects_json=CAST(:effects AS jsonb),metadata_json=CAST(:metadata AS jsonb),"
    "modified_by_user_id=:modified_by,updated_at=:now "
    "WHERE guild_id=:guild_id AND policy_id=:policy_id "
    "AND revision=:expected_revision AND lifecycle_state=:expected_state RETURNING *"
)


class PolicyNotFound(LookupError):
    pass


class PolicyConflict(RuntimeError):
    pass


class PolicyIdempotencyConflict(PolicyConflict):
    pass


class PolicyTargetNotFound(LookupError):
    pass


class PoliciesRepository:
    """Short-transaction persistence for current Policies and append-only history."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        *,
        admin_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._factory = factory
        self._admin_factory = admin_factory

    async def list(self, guild_id: int) -> tuple[Policy, ...]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM policies WHERE guild_id=:guild_id "
                            "ORDER BY created_at, policy_id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(self._policy(row) for row in rows)

    async def get(self, guild_id: int, policy_id: UUID) -> Policy:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = await self._get_row(session, guild_id, policy_id)
        if row is None:
            raise PolicyNotFound("Policy not found")
        return self._policy(row)

    async def versions(self, guild_id: int, policy_id: UUID) -> tuple[PolicyVersion, ...]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM policy_versions WHERE guild_id=:guild_id "
                            "AND policy_id=:policy_id ORDER BY revision"
                        ),
                        {"guild_id": guild_id, "policy_id": policy_id},
                    )
                )
                .mappings()
                .all()
            )
        if not rows and not await self._exists(guild_id, policy_id):
            raise PolicyNotFound("Policy not found")
        return tuple(self._version(row) for row in rows)

    async def get_revision(self, guild_id: int, policy_id: UUID, revision: int) -> Policy:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT snapshot_json FROM policy_versions WHERE guild_id=:guild_id "
                            "AND policy_id=:policy_id AND revision=:revision"
                        ),
                        {"guild_id": guild_id, "policy_id": policy_id, "revision": revision},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise PolicyNotFound("Policy revision not found")
        return self._policy_snapshot(dict(row["snapshot_json"]))

    async def list_favorites(self, guild_id: int, actor_user_id: int) -> tuple[str, ...]:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id, actor_user_id)
        ) as session:
            values = (
                await session.execute(
                    text(
                        "SELECT favorite_key FROM policy_favorites "
                        "WHERE guild_id=:guild_id AND discord_user_id=:actor_user_id "
                        "ORDER BY created_at,favorite_key"
                    ),
                    {"guild_id": guild_id, "actor_user_id": actor_user_id},
                )
            ).scalars()
            return tuple(str(value) for value in values)

    async def set_favorite(
        self, guild_id: int, actor_user_id: int, favorite_key: str, *, pinned: bool
    ) -> tuple[str, ...]:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id, actor_user_id)
        ) as session:
            if pinned:
                await session.execute(
                    text(
                        "INSERT INTO policy_favorites "
                        "(guild_id,discord_user_id,favorite_key) "
                        "VALUES (:guild_id,:actor_user_id,:favorite_key) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "guild_id": guild_id,
                        "actor_user_id": actor_user_id,
                        "favorite_key": favorite_key,
                    },
                )
            else:
                await session.execute(
                    text(
                        "DELETE FROM policy_favorites WHERE guild_id=:guild_id "
                        "AND discord_user_id=:actor_user_id AND favorite_key=:favorite_key"
                    ),
                    {
                        "guild_id": guild_id,
                        "actor_user_id": actor_user_id,
                        "favorite_key": favorite_key,
                    },
                )
            values = (
                await session.execute(
                    text(
                        "SELECT favorite_key FROM policy_favorites "
                        "WHERE guild_id=:guild_id AND discord_user_id=:actor_user_id "
                        "ORDER BY created_at,favorite_key"
                    ),
                    {"guild_id": guild_id, "actor_user_id": actor_user_id},
                )
            ).scalars()
            return tuple(str(value) for value in values)

    async def get_temporary_access(
        self, guild_id: int, policy_id: UUID
    ) -> PolicyTemporaryAccess | None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM policy_temporary_access "
                            "WHERE guild_id=:guild_id AND policy_id=:policy_id"
                        ),
                        {"guild_id": guild_id, "policy_id": policy_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._temporary_access(row)

    async def schedule_temporary_access(
        self,
        *,
        guild_id: int,
        policy_id: UUID,
        actor_user_id: int,
        expires_at: datetime,
        correlation_id: UUID,
    ) -> PolicyTemporaryAccess:
        now = datetime.now(UTC)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "INSERT INTO policy_temporary_access "
                            "(guild_id,policy_id,expires_at,status,next_attempt_at,created_by_user_id,"
                            "created_at,updated_at) VALUES "
                            "(:guild_id,:policy_id,:expires_at,'SCHEDULED',:expires_at,:actor,"
                            ":now,:now) "
                            "ON CONFLICT (guild_id,policy_id) DO UPDATE SET "
                            "expires_at=EXCLUDED.expires_at,status='SCHEDULED',"
                            "removal_plan_id=NULL,attempt_count=0,next_attempt_at=EXCLUDED.expires_at,"
                            "lease_owner=NULL,lease_expires_at=NULL,last_error=NULL,"
                            "created_by_user_id=EXCLUDED.created_by_user_id,updated_at=:now,"
                            "removal_started_at=NULL,completed_at=NULL RETURNING *"
                        ),
                        {
                            "guild_id": guild_id,
                            "policy_id": policy_id,
                            "expires_at": expires_at,
                            "actor": actor_user_id,
                            "now": now,
                        },
                    )
                )
                .mappings()
                .one()
            )
            await self._temporary_access_audit(
                session,
                guild_id=guild_id,
                policy_id=policy_id,
                actor_user_id=actor_user_id,
                event_type="POLICY_TEMPORARY_ACCESS_SCHEDULED",
                result_state="SUCCEEDED",
                correlation_id=correlation_id,
                data={"expires_at": expires_at.isoformat()},
                now=now,
            )
        return self._temporary_access(row)

    async def cancel_temporary_access(
        self,
        *,
        guild_id: int,
        policy_id: UUID,
        actor_user_id: int,
        correlation_id: UUID,
    ) -> PolicyTemporaryAccess:
        now = datetime.now(UTC)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "UPDATE policy_temporary_access SET status='CANCELLED',updated_at=:now,"
                            "lease_owner=NULL,lease_expires_at=NULL WHERE guild_id=:guild_id "
                            "AND policy_id=:policy_id "
                            "AND status IN ('SCHEDULED','INTERVENTION_REQUIRED') "
                            "RETURNING *"
                        ),
                        {"guild_id": guild_id, "policy_id": policy_id, "now": now},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise PolicyConflict("temporary access cannot be cancelled in its current state")
            await self._temporary_access_audit(
                session,
                guild_id=guild_id,
                policy_id=policy_id,
                actor_user_id=actor_user_id,
                event_type="POLICY_TEMPORARY_ACCESS_CANCELLED",
                result_state="SUCCEEDED",
                correlation_id=correlation_id,
                data={},
                now=now,
            )
        return self._temporary_access(row)

    async def claim_due_temporary_accesses(
        self, *, lease_owner: str, limit: int = 20, lease_seconds: int = 60
    ) -> tuple[PolicyTemporaryAccess, ...]:
        if self._admin_factory is None:
            raise RuntimeError("admin factory is required to claim cross-tenant expirations")
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=lease_seconds)
        async with self._admin_factory.begin() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "WITH due AS (SELECT guild_id,policy_id FROM policy_temporary_access "
                            "WHERE status IN ('SCHEDULED','PROCESSING','REMOVAL_SCHEDULED') "
                            "AND next_attempt_at<=:now "
                            "AND (lease_expires_at IS NULL OR lease_expires_at<=:now) "
                            "ORDER BY next_attempt_at,guild_id,policy_id FOR UPDATE SKIP LOCKED "
                            "LIMIT :limit) UPDATE policy_temporary_access item SET "
                            "status='PROCESSING',lease_owner=:lease_owner,"
                            "lease_expires_at=:lease_until,updated_at=:now FROM due "
                            "WHERE item.guild_id=due.guild_id AND item.policy_id=due.policy_id "
                            "RETURNING item.*"
                        ),
                        {
                            "now": now,
                            "limit": limit,
                            "lease_owner": lease_owner,
                            "lease_until": lease_until,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return tuple(self._temporary_access(row) for row in rows)

    async def mark_temporary_removal_scheduled(
        self, *, guild_id: int, policy_id: UUID, plan_id: UUID
    ) -> PolicyTemporaryAccess:
        now = datetime.now(UTC)
        recovery_at = now + timedelta(minutes=5)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "UPDATE policy_temporary_access SET status='REMOVAL_SCHEDULED',"
                            "removal_plan_id=:plan_id,"
                            "removal_started_at=COALESCE(removal_started_at,:now),"
                            "next_attempt_at=:recovery_at,lease_owner=NULL,lease_expires_at=NULL,"
                            "updated_at=:now "
                            "WHERE guild_id=:guild_id AND policy_id=:policy_id RETURNING *"
                        ),
                        {
                            "guild_id": guild_id,
                            "policy_id": policy_id,
                            "plan_id": plan_id,
                            "now": now,
                            "recovery_at": recovery_at,
                        },
                    )
                )
                .mappings()
                .one()
            )
        return self._temporary_access(row)

    async def mark_temporary_failure(
        self, *, guild_id: int, policy_id: UUID, error: str, max_attempts: int = 3
    ) -> PolicyTemporaryAccess:
        now = datetime.now(UTC)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            current = await session.execute(
                text(
                    "SELECT attempt_count FROM policy_temporary_access "
                    "WHERE guild_id=:guild_id AND policy_id=:policy_id FOR UPDATE"
                ),
                {"guild_id": guild_id, "policy_id": policy_id},
            )
            attempts = int(current.scalar_one()) + 1
            terminal = attempts >= max_attempts
            next_attempt = now + timedelta(seconds=min(300, 2**attempts * 5))
            row = (
                (
                    await session.execute(
                        text(
                            "UPDATE policy_temporary_access SET status=:status,"
                            "attempt_count=:attempts,"
                            "next_attempt_at=:next_attempt,last_error=:error,lease_owner=NULL,"
                            "lease_expires_at=NULL,updated_at=:now WHERE guild_id=:guild_id "
                            "AND policy_id=:policy_id RETURNING *"
                        ),
                        {
                            "guild_id": guild_id,
                            "policy_id": policy_id,
                            "status": "INTERVENTION_REQUIRED" if terminal else "SCHEDULED",
                            "attempts": attempts,
                            "next_attempt": next_attempt,
                            "error": error[:160],
                            "now": now,
                        },
                    )
                )
                .mappings()
                .one()
            )
            await self._temporary_access_audit(
                session,
                guild_id=guild_id,
                policy_id=policy_id,
                actor_user_id=1,
                event_type="POLICY_TEMPORARY_ACCESS_REMOVAL_FAILED",
                result_state="FAILED" if terminal else "RETRY_SCHEDULED",
                correlation_id=uuid4(),
                data={"attempt_count": attempts, "error": error[:160]},
                now=now,
            )
        return self._temporary_access(row)

    async def mark_temporary_plan_outcome(
        self, *, guild_id: int, plan_id: UUID, succeeded: bool, error: str | None = None
    ) -> None:
        now = datetime.now(UTC)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "UPDATE policy_temporary_access SET status=:status,last_error=:error,"
                            "completed_at=CASE WHEN :succeeded THEN :now ELSE completed_at END,"
                            "lease_owner=NULL,lease_expires_at=NULL,updated_at=:now "
                            "WHERE guild_id=:guild_id AND removal_plan_id=:plan_id "
                            "RETURNING policy_id"
                        ),
                        {
                            "guild_id": guild_id,
                            "plan_id": plan_id,
                            "status": "REMOVED" if succeeded else "INTERVENTION_REQUIRED",
                            "error": error,
                            "succeeded": succeeded,
                            "now": now,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return
            await self._temporary_access_audit(
                session,
                guild_id=guild_id,
                policy_id=UUID(str(row["policy_id"])),
                actor_user_id=1,
                event_type=(
                    "POLICY_TEMPORARY_ACCESS_REMOVED"
                    if succeeded
                    else "POLICY_TEMPORARY_ACCESS_REMOVAL_FAILED"
                ),
                result_state="SUCCEEDED" if succeeded else "FAILED",
                correlation_id=uuid4(),
                data={"plan_id": str(plan_id), **({} if error is None else {"error": error})},
                now=now,
            )

    async def assert_activation_plan(
        self,
        *,
        guild_id: int,
        policy_id: UUID,
        policy_revision: int,
        plan_id: UUID,
    ) -> dict[str, Any]:
        """Require a tenant-local, preflight-validated canonical Policy Plan."""

        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT id,status,plan_hash FROM plans WHERE guild_id=:guild_id "
                            "AND id=:plan_id AND origin_type='POLICY' "
                            "AND source_policy_id=:policy_id "
                            "AND source_policy_revision=:policy_revision "
                            "AND status IN ('VALIDATED','CONFIRMED','APPLYING','SUCCEEDED')"
                        ),
                        {
                            "guild_id": guild_id,
                            "plan_id": plan_id,
                            "policy_id": policy_id,
                            "policy_revision": policy_revision,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise PolicyLifecycleError(
                "Policy activation requires its preflight-validated canonical Plan"
            )
        return dict(row)

    async def assert_deletion_plan(
        self,
        *,
        guild_id: int,
        policy_id: UUID,
        policy_revision: int,
        plan_id: UUID,
    ) -> dict[str, Any]:
        """Require a tenant-local validated DISABLE Plan for this Policy revision."""

        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT id,status,plan_hash FROM plans WHERE guild_id=:guild_id "
                            "AND id=:plan_id AND origin_type='POLICY' "
                            "AND source_policy_id=:policy_id "
                            "AND source_policy_revision=:policy_revision "
                            "AND origin_metadata->>'simulate'='DISABLE' "
                            "AND status IN ('VALIDATED','CONFIRMED','APPLYING','SUCCEEDED')"
                        ),
                        {
                            "guild_id": guild_id,
                            "plan_id": plan_id,
                            "policy_id": policy_id,
                            "policy_revision": policy_revision,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise PolicyLifecycleError(
                "Policy deletion requires its preflight-validated DISABLE Plan"
            )
        return dict(row)

    async def plan_dependencies(self, guild_id: int, policy_id: UUID) -> tuple[dict[str, Any], ...]:
        """Return immutable Plan provenance without crossing the active tenant."""

        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT id,source_policy_revision,status,created_at FROM plans "
                            "WHERE guild_id=:guild_id AND source_policy_id=:policy_id "
                            "ORDER BY created_at,id"
                        ),
                        {"guild_id": guild_id, "policy_id": policy_id},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(dict(row) for row in rows)

    async def create(
        self,
        policy: Policy,
        *,
        idempotency_key: str,
        request_hash: str,
        correlation_id: UUID,
    ) -> Policy:
        now = datetime.now(UTC)
        async with tenant_transaction(self._factory, TenantContext(policy.guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "INSERT INTO policies (policy_id,guild_id,policy_type,contract_version,"
                            "name,description,lifecycle_state,revision,scope_type,scope_id,"
                            "priority,locked,"
                            "conditions_json,effects_json,metadata_json,created_by_user_id,"
                            "modified_by_user_id,create_idempotency_key,create_request_hash,"
                            "created_at,updated_at) VALUES (:policy_id,:guild_id,:policy_type,"
                            ":contract_version,:name,:description,:lifecycle_state,:revision,"
                            ":scope_type,:scope_id,:priority,:locked,CAST(:conditions AS jsonb),"
                            "CAST(:effects AS jsonb),"
                            "CAST(:metadata AS jsonb),:created_by,:modified_by,:idempotency_key,"
                            ":request_hash,:now,:now) ON CONFLICT "
                            "(guild_id,create_idempotency_key) "
                            "DO NOTHING RETURNING *"
                        ),
                        {
                            **self._write_params(policy),
                            "idempotency_key": idempotency_key,
                            "request_hash": request_hash,
                            "now": now,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                existing = (
                    (
                        await session.execute(
                            text(
                                "SELECT * FROM policies WHERE guild_id=:guild_id "
                                "AND create_idempotency_key=:idempotency_key"
                            ),
                            {"guild_id": policy.guild_id, "idempotency_key": idempotency_key},
                        )
                    )
                    .mappings()
                    .one()
                )
                if str(existing["create_request_hash"]) != request_hash:
                    raise PolicyIdempotencyConflict("idempotency key was used for another request")
                return self._policy(existing)
            created = self._policy(row)
            await self._record_change(
                session,
                created,
                change_kind="CREATE",
                actor_id=created.created_by_user_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                now=now,
            )
            return created

    async def update_draft(
        self,
        policy: Policy,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_hash: str,
        correlation_id: UUID,
    ) -> Policy:
        return await self._mutate(
            policy,
            expected_revision=expected_revision,
            expected_state=PolicyLifecycleState.DRAFT,
            change_kind="UPDATE",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            correlation_id=correlation_id,
        )

    async def transition(
        self,
        policy: Policy,
        *,
        expected_revision: int,
        expected_state: PolicyLifecycleState,
        change_kind: str,
        idempotency_key: str,
        request_hash: str,
        correlation_id: UUID,
    ) -> Policy:
        return await self._mutate(
            policy,
            expected_revision=expected_revision,
            expected_state=expected_state,
            change_kind=change_kind,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            correlation_id=correlation_id,
        )

    async def annotate(
        self,
        policy: Policy,
        *,
        expected_revision: int,
        expected_state: PolicyLifecycleState,
        idempotency_key: str,
        request_hash: str,
        correlation_id: UUID,
    ) -> Policy:
        """Persist a metadata-only revision (e.g. an accepted exception tag).

        Lifecycle state, conditions, effects and scope are unchanged; only
        ``metadata`` and ``revision`` move, matched against the same
        optimistic-concurrency (``expected_revision``/``expected_state``) and
        idempotency guarantees as any other Policy mutation.
        """
        return await self._mutate(
            policy,
            expected_revision=expected_revision,
            expected_state=expected_state,
            change_kind="ANNOTATE",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            correlation_id=correlation_id,
        )

    async def _mutate(
        self,
        policy: Policy,
        *,
        expected_revision: int,
        expected_state: PolicyLifecycleState,
        change_kind: str,
        idempotency_key: str,
        request_hash: str,
        correlation_id: UUID,
    ) -> Policy:
        now = datetime.now(UTC)
        async with tenant_transaction(self._factory, TenantContext(policy.guild_id)) as session:
            replay = await self._idempotent_replay(
                session,
                policy.guild_id,
                policy.policy_id,
                change_kind,
                idempotency_key,
                request_hash,
            )
            if replay is not None:
                current = await self._get_row(session, policy.guild_id, policy.policy_id)
                if current is None:
                    raise PolicyNotFound("Policy not found")
                return self._policy(current)
            update_sql = {
                "UPDATE": _UPDATE_POLICY_SQL,
                "ANNOTATE": _UPDATE_POLICY_SQL,
                "ACTIVATE": _UPDATE_POLICY_SQL.replace(
                    " WHERE guild_id", ", activated_at=:now WHERE guild_id"
                ),
                "DISABLE": _UPDATE_POLICY_SQL.replace(
                    " WHERE guild_id", ", disabled_at=:now WHERE guild_id"
                ),
                "RETIRE": _UPDATE_POLICY_SQL.replace(
                    " WHERE guild_id", ", retired_at=:now WHERE guild_id"
                ),
            }[change_kind]
            row = (
                (
                    await session.execute(
                        text(update_sql),
                        {
                            **self._write_params(policy),
                            "expected_revision": expected_revision,
                            "expected_state": expected_state.value,
                            "now": now,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                current = await self._get_row(session, policy.guild_id, policy.policy_id)
                if current is None:
                    raise PolicyNotFound("Policy not found")
                raise PolicyConflict("Policy revision or lifecycle state changed")
            changed = self._policy(row)
            await self._record_change(
                session,
                changed,
                change_kind=change_kind,
                actor_id=changed.modified_by_user_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                now=now,
            )
            return changed

    async def validate_target(
        self, guild_id: int, scope_type: PolicyScopeType, scope_id: str | None
    ) -> None:
        query: str
        value: object
        if scope_type is PolicyScopeType.GUILD:
            query, value = (
                "SELECT 1 FROM guild_installations "
                "WHERE guild_id=:guild_id AND guild_id=:target_id",
                guild_id,
            )
        elif scope_type is PolicyScopeType.LOGICAL_GROUP:
            query, value = (
                "SELECT 1 FROM logical_groups WHERE guild_id=:guild_id AND id=:target_id",
                UUID(str(scope_id)),
            )
        elif scope_type is PolicyScopeType.CATEGORY:
            query, value = (
                "SELECT 1 FROM discord_channels_cache "
                "WHERE guild_id=:guild_id AND channel_id=:target_id AND type=4",
                int(str(scope_id)),
            )
        elif scope_type is PolicyScopeType.CHANNEL:
            query, value = (
                "SELECT 1 FROM discord_channels_cache "
                "WHERE guild_id=:guild_id AND channel_id=:target_id AND type<>4",
                int(str(scope_id)),
            )
        elif scope_type is PolicyScopeType.ROLE:
            query, value = (
                "SELECT 1 FROM discord_roles_cache WHERE guild_id=:guild_id "
                "AND role_id=:target_id AND deleted_confirmed_at IS NULL",
                int(str(scope_id)),
            )
        elif scope_type is PolicyScopeType.MEMBER:
            query, value = (
                "SELECT 1 FROM discord_member_authorization_cache "
                "WHERE guild_id=:guild_id AND discord_user_id=:target_id",
                int(str(scope_id)),
            )
        elif scope_type is PolicyScopeType.BOT:
            query, value = (
                "SELECT 1 FROM discord_member_authorization_cache "
                "WHERE guild_id=:guild_id AND discord_user_id=:target_id AND is_bot",
                int(str(scope_id)),
            )
        else:
            raise PolicyTargetNotFound("scope target kind is not backed by this foundation lot")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            exists = await session.scalar(
                text(query),
                {"guild_id": guild_id, "target_id": value},
            )
        if exists is None:
            raise PolicyTargetNotFound("Policy scope target is absent from this Guild cache")

    async def validate_role_references(self, guild_id: int, role_ids: tuple[str, ...]) -> None:
        if not role_ids:
            return
        numeric = [int(role_id) for role_id in role_ids]
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            known = set(
                (
                    await session.execute(
                        text(
                            "SELECT role_id FROM discord_roles_cache WHERE guild_id=:guild_id "
                            "AND role_id = ANY(:role_ids) AND deleted_confirmed_at IS NULL"
                        ),
                        {"guild_id": guild_id, "role_ids": numeric},
                    )
                ).scalars()
            )
        if known != set(numeric):
            raise PolicyTargetNotFound("Policy references a role absent from this Guild cache")

    async def _exists(self, guild_id: int, policy_id: UUID) -> bool:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return (
                await session.scalar(
                    text(
                        "SELECT 1 FROM policies WHERE guild_id=:guild_id AND policy_id=:policy_id"
                    ),
                    {"guild_id": guild_id, "policy_id": policy_id},
                )
            ) is not None

    @staticmethod
    async def _get_row(session: AsyncSession, guild_id: int, policy_id: UUID) -> Any:
        return (
            (
                await session.execute(
                    text(
                        "SELECT * FROM policies WHERE guild_id=:guild_id AND policy_id=:policy_id"
                    ),
                    {"guild_id": guild_id, "policy_id": policy_id},
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    async def _idempotent_replay(
        session: AsyncSession,
        guild_id: int,
        policy_id: UUID,
        change_kind: str,
        idempotency_key: str,
        request_hash: str,
    ) -> Any:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT request_hash FROM policy_versions WHERE guild_id=:guild_id "
                        "AND policy_id=:policy_id AND change_kind=:change_kind "
                        "AND idempotency_key=:idempotency_key"
                    ),
                    {
                        "guild_id": guild_id,
                        "policy_id": policy_id,
                        "change_kind": change_kind,
                        "idempotency_key": idempotency_key,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is not None and str(row["request_hash"]) != request_hash:
            raise PolicyIdempotencyConflict("idempotency key was used for another request")
        return row

    async def _record_change(
        self,
        session: AsyncSession,
        policy: Policy,
        *,
        change_kind: str,
        actor_id: int,
        correlation_id: UUID,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
    ) -> None:
        snapshot = self._snapshot(policy)
        await session.execute(
            text(
                "INSERT INTO policy_versions (version_id,guild_id,policy_id,revision,change_kind,"
                "snapshot_json,author_user_id,correlation_id,idempotency_key,"
                "request_hash,created_at) "
                "VALUES (:version_id,:guild_id,:policy_id,:revision,:change_kind,"
                "CAST(:snapshot AS jsonb),:actor_id,:correlation_id,:idempotency_key,"
                ":request_hash,:now)"
            ),
            {
                "version_id": uuid4(),
                "guild_id": policy.guild_id,
                "policy_id": policy.policy_id,
                "revision": policy.revision,
                "change_kind": change_kind,
                "snapshot": json.dumps(snapshot, separators=(",", ":")),
                "actor_id": actor_id,
                "correlation_id": correlation_id,
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "now": now,
            },
        )
        await session.execute(
            text(
                "INSERT INTO internal_audit_events (id,guild_id,actor_user_id,source,event_type,"
                "target_type,target_id,correlation_id,result_state,data_json,occurred_at) VALUES "
                "(:id,:guild_id,:actor_id,'DASHBOARD',:event_type,'POLICY',:target_id,"
                ":correlation_id,'SUCCEEDED',CAST(:data AS jsonb),:now)"
            ),
            {
                "id": uuid4(),
                "guild_id": policy.guild_id,
                "actor_id": actor_id,
                "event_type": f"POLICY_{change_kind}D"
                if change_kind != "DISABLE"
                else "POLICY_DISABLED",
                "target_id": str(policy.policy_id),
                "correlation_id": correlation_id,
                "data": json.dumps(
                    {"policy_id": str(policy.policy_id), "revision": policy.revision},
                    separators=(",", ":"),
                ),
                "now": now,
            },
        )

    @staticmethod
    async def _temporary_access_audit(
        session: AsyncSession,
        *,
        guild_id: int,
        policy_id: UUID,
        actor_user_id: int,
        event_type: str,
        result_state: str,
        correlation_id: UUID,
        data: dict[str, Any],
        now: datetime,
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO internal_audit_events (id,guild_id,actor_user_id,source,event_type,"
                "target_type,target_id,correlation_id,result_state,data_json,occurred_at) VALUES "
                "(:id,:guild_id,:actor,'SYSTEM',:event_type,'POLICY',:target_id,"
                ":correlation_id,:result_state,CAST(:data AS jsonb),:now)"
            ),
            {
                "id": uuid4(),
                "guild_id": guild_id,
                "actor": actor_user_id,
                "event_type": event_type,
                "target_id": str(policy_id),
                "correlation_id": correlation_id,
                "result_state": result_state,
                "data": json.dumps(data, separators=(",", ":")),
                "now": now,
            },
        )

    @staticmethod
    def _write_params(policy: Policy) -> dict[str, object]:
        return {
            "policy_id": policy.policy_id,
            "guild_id": policy.guild_id,
            "policy_type": policy.policy_type,
            "contract_version": policy.contract_version,
            "name": policy.name,
            "description": policy.description,
            "lifecycle_state": policy.lifecycle_state.value,
            "revision": policy.revision,
            "scope_type": policy.scope_type.value,
            "scope_id": policy.scope_id,
            "priority": policy.priority,
            "locked": policy.locked,
            "conditions": json.dumps(policy.conditions, separators=(",", ":")),
            "effects": json.dumps(policy.effects, separators=(",", ":")),
            "metadata": json.dumps(policy.metadata, separators=(",", ":")),
            "created_by": policy.created_by_user_id,
            "modified_by": policy.modified_by_user_id,
        }

    @staticmethod
    def _snapshot(policy: Policy) -> dict[str, object]:
        return {
            "policy_id": str(policy.policy_id),
            "guild_id": policy.guild_id,
            "policy_type": policy.policy_type,
            "contract_version": policy.contract_version,
            "name": policy.name,
            "description": policy.description,
            "lifecycle_state": policy.lifecycle_state.value,
            "revision": policy.revision,
            "priority": policy.priority,
            "locked": policy.locked,
            "scope_type": policy.scope_type.value,
            "scope_id": policy.scope_id,
            "conditions": list(policy.conditions),
            "effects": list(policy.effects),
            "metadata": policy.metadata,
            "created_by_user_id": policy.created_by_user_id,
            "modified_by_user_id": policy.modified_by_user_id,
        }

    @staticmethod
    def _policy(row: Any) -> Policy:
        return Policy(
            policy_id=row["policy_id"],
            guild_id=int(row["guild_id"]),
            policy_type=str(row["policy_type"]),
            contract_version=int(row["contract_version"]),
            name=str(row["name"]),
            description=str(row["description"]),
            lifecycle_state=PolicyLifecycleState(str(row["lifecycle_state"])),
            revision=int(row["revision"]),
            priority=int(row["priority"]),
            locked=bool(row["locked"]),
            scope_type=PolicyScopeType(str(row["scope_type"])),
            scope_id=str(row["scope_id"]) if row["scope_id"] is not None else None,
            conditions=tuple(dict(item) for item in row["conditions_json"]),
            effects=tuple(dict(item) for item in row["effects_json"]),
            metadata=dict(row["metadata_json"]),
            created_by_user_id=int(row["created_by_user_id"]),
            modified_by_user_id=int(row["modified_by_user_id"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            activated_at=row["activated_at"],
            disabled_at=row["disabled_at"],
            retired_at=row["retired_at"],
        )

    @staticmethod
    def _temporary_access(row: Any) -> PolicyTemporaryAccess:
        return PolicyTemporaryAccess(
            guild_id=int(row["guild_id"]),
            policy_id=UUID(str(row["policy_id"])),
            expires_at=row["expires_at"],
            status=TemporaryAccessState(str(row["status"])),
            created_by_user_id=int(row["created_by_user_id"]),
            removal_plan_id=(
                UUID(str(row["removal_plan_id"]))
                if row.get("removal_plan_id") is not None
                else None
            ),
            attempt_count=int(row["attempt_count"]),
            last_error=str(row["last_error"]) if row.get("last_error") is not None else None,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            removal_started_at=row.get("removal_started_at"),
            completed_at=row.get("completed_at"),
        )

    @staticmethod
    def _version(row: Any) -> PolicyVersion:
        return PolicyVersion(
            version_id=row["version_id"],
            guild_id=int(row["guild_id"]),
            policy_id=row["policy_id"],
            revision=int(row["revision"]),
            change_kind=str(row["change_kind"]),
            snapshot=dict(row["snapshot_json"]),
            author_user_id=int(row["author_user_id"]),
            correlation_id=row["correlation_id"],
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _policy_snapshot(value: dict[str, Any]) -> Policy:
        return Policy(
            policy_id=UUID(str(value["policy_id"])),
            guild_id=int(value["guild_id"]),
            policy_type=str(value["policy_type"]),
            contract_version=int(value["contract_version"]),
            name=str(value["name"]),
            description=str(value["description"]),
            lifecycle_state=PolicyLifecycleState(str(value["lifecycle_state"])),
            revision=int(value["revision"]),
            priority=int(value.get("priority", 0)),
            locked=bool(value.get("locked", False)),
            scope_type=PolicyScopeType(str(value["scope_type"])),
            scope_id=str(value["scope_id"]) if value.get("scope_id") is not None else None,
            conditions=tuple(dict(item) for item in value["conditions"]),
            effects=tuple(dict(item) for item in value["effects"]),
            metadata=dict(value["metadata"]),
            created_by_user_id=int(value["created_by_user_id"]),
            modified_by_user_id=int(value["modified_by_user_id"]),
        )
