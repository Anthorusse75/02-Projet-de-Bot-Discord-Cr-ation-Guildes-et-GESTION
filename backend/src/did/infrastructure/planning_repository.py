from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from did.infrastructure.database import tenant_transaction
from did.infrastructure.planning_metrics import PlanningMetrics
from did.planning.canonical import canonical_hash, canonical_json
from did.planning.models import (
    AttemptState,
    DesiredStateGraph,
    OperationState,
    OperationType,
    PlanOperation,
    PlanState,
    RiskLevel,
    thaw_json_object,
)
from did.planning.risk import RiskAssessment
from did.tenancy import TenantContext


class PlanNotFound(LookupError):
    pass


class PlanConflict(RuntimeError):
    pass


class PlanFencingError(RuntimeError):
    pass


class ConfirmationInvalid(RuntimeError):
    pass


class PlanningRepository:
    """Tenant-scoped durable plans; every method owns one short transaction."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        *,
        metrics: PlanningMetrics | None = None,
    ) -> None:
        self._factory = factory
        self.metrics = metrics or PlanningMetrics()

    async def create_plan(
        self,
        *,
        plan_id: UUID,
        guild_id: int,
        actor_user_id: int,
        idempotency_key: str,
        graph: DesiredStateGraph,
        operations: tuple[PlanOperation, ...],
        before_snapshot: dict[str, Any],
        base_structure_version: str,
        base_structure_hash: str,
        capability_version: str,
        plan_hash: str,
        risk: RiskAssessment,
        compiler_version: str,
        correlation_id: UUID,
    ) -> tuple[dict[str, Any], bool]:
        if not idempotency_key or len(idempotency_key) > 160:
            raise ValueError("idempotency key must be present and bounded")
        graph_json = canonical_json(graph)
        graph_hash = canonical_hash(graph)
        snapshot_id = uuid4()
        now = datetime.now(UTC)
        async with tenant_transaction(
            self._factory, TenantContext(guild_id, actor_user_id)
        ) as session:
            existing = await self._plan_by_idempotency(
                session, guild_id, actor_user_id, idempotency_key
            )
            if existing is not None:
                if str(existing["desired_graph_hash"]) != graph_hash:
                    raise PlanConflict("idempotency key reused with another desired graph")
                return dict(existing), False
            await session.execute(
                text(
                    "INSERT INTO plan_snapshots "
                    "(id,guild_id,snapshot_type,schema_version,structure_version,"
                    "snapshot_hash,payload,captured_at) VALUES "
                    "(:id,:guild_id,'BEFORE','did-guild-snapshot-v1',:version,:hash,"
                    "CAST(:payload AS jsonb),:captured_at)"
                ),
                {
                    "id": snapshot_id,
                    "guild_id": guild_id,
                    "version": base_structure_version,
                    "hash": base_structure_hash,
                    "payload": json.dumps(before_snapshot, separators=(",", ":")),
                    "captured_at": now,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO plans "
                    "(id,guild_id,actor_user_id,status,desired_graph_schema_version,"
                    "compiler_version,desired_graph,desired_graph_hash,before_snapshot_id,"
                    "base_structure_version,base_structure_hash,capability_version,plan_hash,"
                    "risk_level,risk_summary,impact_summary,confirmation_required,"
                    "idempotency_key) VALUES "
                    "(:id,:guild_id,:actor,'DRAFT',:schema,:compiler,CAST(:graph AS jsonb),"
                    ":graph_hash,:snapshot_id,:base_version,:base_hash,:capability_version,"
                    ":plan_hash,:risk_level,CAST(:risk AS jsonb),CAST(:impact AS jsonb),"
                    ":confirmation_required,:idempotency_key)"
                ),
                {
                    "id": plan_id,
                    "guild_id": guild_id,
                    "actor": actor_user_id,
                    "schema": graph.schema_version,
                    "compiler": compiler_version,
                    "graph": graph_json,
                    "graph_hash": graph_hash,
                    "snapshot_id": snapshot_id,
                    "base_version": base_structure_version,
                    "base_hash": base_structure_hash,
                    "capability_version": capability_version,
                    "plan_hash": plan_hash,
                    "risk_level": risk.level.value,
                    "risk": json.dumps(
                        {
                            "score": risk.score,
                            "reasons": list(risk.reasons),
                            "reinforced_confirmation_required": (
                                risk.reinforced_confirmation_required
                            ),
                        },
                        separators=(",", ":"),
                    ),
                    "impact": json.dumps(asdict(risk.impact), separators=(",", ":")),
                    "confirmation_required": risk.reinforced_confirmation_required,
                    "idempotency_key": idempotency_key,
                },
            )
            display_order = {
                operation.operation_id: index for index, operation in enumerate(operations)
            }
            for operation in operations:
                payload = thaw_json_object(operation.desired_payload)
                resource_id = payload.get("id") or payload.get("channel_id")
                await session.execute(
                    text(
                        "INSERT INTO plan_operations "
                        "(id,guild_id,plan_id,operation_type,execution_target,resource_type,"
                        "resource_ref,resource_discord_id,produces_symbol,consumes_symbols,"
                        "desired_payload,before_payload,required_capabilities,compensation_class,"
                        "risk_level,verification_strategy,recovery_strategy,"
                        "expected_gateway_events,preconditions,immutable_hash,display_order) "
                        "VALUES "
                        "(:id,:guild_id,:plan_id,:operation_type,:execution_target,:resource_type,"
                        ":resource_ref,:resource_id,:produces_symbol,:consumes_symbols,"
                        "CAST(:desired AS jsonb),CAST(:before AS jsonb),:capabilities,"
                        ":compensation,:risk,:verification,:recovery,:gateway_events,"
                        "CAST(:preconditions AS jsonb),"
                        ":immutable_hash,:display_order)"
                    ),
                    {
                        "id": operation.operation_id,
                        "guild_id": guild_id,
                        "plan_id": plan_id,
                        "operation_type": operation.operation_type.value,
                        "execution_target": operation.execution_target.value,
                        "resource_type": operation.resource_type.value,
                        "resource_ref": operation.resource_ref,
                        "resource_id": int(resource_id) if resource_id is not None else None,
                        "produces_symbol": operation.produces_symbol,
                        "consumes_symbols": list(operation.consumes_symbols),
                        "desired": canonical_json(operation.desired_payload),
                        "before": canonical_json(operation.before_payload),
                        "capabilities": list(operation.required_capabilities),
                        "compensation": operation.compensation.value,
                        "risk": operation.risk.value,
                        "verification": operation.verification.value,
                        "recovery": operation.recovery.value,
                        "gateway_events": list(operation.expected_gateway_events),
                        "preconditions": canonical_json(operation.preconditions),
                        "immutable_hash": canonical_hash(operation),
                        "display_order": display_order[operation.operation_id],
                    },
                )
                if operation.produces_symbol is not None:
                    await session.execute(
                        text(
                            "INSERT INTO plan_symbol_bindings "
                            "(guild_id,plan_id,symbol,resource_type,producer_operation_id) "
                            "VALUES (:guild_id,:plan_id,:symbol,:resource_type,:operation_id)"
                        ),
                        {
                            "guild_id": guild_id,
                            "plan_id": plan_id,
                            "symbol": operation.produces_symbol,
                            "resource_type": operation.resource_type.value,
                            "operation_id": operation.operation_id,
                        },
                    )
            for operation in operations:
                for predecessor in operation.predecessors:
                    await session.execute(
                        text(
                            "INSERT INTO plan_operation_dependencies "
                            "(guild_id,plan_id,operation_id,predecessor_operation_id) "
                            "VALUES (:guild_id,:plan_id,:operation_id,:predecessor_id)"
                        ),
                        {
                            "guild_id": guild_id,
                            "plan_id": plan_id,
                            "operation_id": operation.operation_id,
                            "predecessor_id": predecessor,
                        },
                    )
            await self._insert_resource_dependencies(
                session,
                guild_id=guild_id,
                plan_id=plan_id,
                operations=operations,
                before_snapshot=before_snapshot,
            )
            await self._append_audit(
                session,
                guild_id=guild_id,
                actor_user_id=actor_user_id,
                event_type="PLAN_CREATED",
                target_type="PLAN",
                target_id=str(plan_id),
                plan_id=plan_id,
                operation_id=None,
                correlation_id=correlation_id,
                result_state=PlanState.DRAFT.value,
                data={"plan_hash": plan_hash, "operation_count": len(operations)},
            )
            await self._append_progress(
                session,
                guild_id=guild_id,
                plan_id=plan_id,
                operation_id=None,
                plan_status=PlanState.DRAFT,
                operation_status=None,
                message_key="plans.progress.created",
                error_code=None,
                correlation_id=correlation_id,
            )
            row = await self._plan_row(session, guild_id, plan_id)
            assert row is not None
            self.metrics.plan_created(risk.level)
            return dict(row), True

    async def get_plan(self, guild_id: int, plan_id: UUID) -> dict[str, Any]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = await self._plan_row(session, guild_id, plan_id)
        if row is None:
            raise PlanNotFound("plan not found")
        return dict(row)

    async def operations(self, guild_id: int, plan_id: UUID) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT operations.*, COALESCE(array_agg(dependencies."
                            "predecessor_operation_id ORDER BY dependencies."
                            "predecessor_operation_id) FILTER (WHERE dependencies."
                            "predecessor_operation_id IS NOT NULL), '{}') AS predecessors "
                            "FROM plan_operations AS operations LEFT JOIN "
                            "plan_operation_dependencies AS dependencies ON "
                            "dependencies.guild_id=operations.guild_id AND "
                            "dependencies.plan_id=operations.plan_id AND "
                            "dependencies.operation_id=operations.id WHERE "
                            "operations.guild_id=:guild_id AND operations.plan_id=:plan_id "
                            "GROUP BY operations.guild_id,operations.plan_id,operations.id "
                            "ORDER BY operations.display_order"
                        ),
                        {"guild_id": guild_id, "plan_id": plan_id},
                    )
                )
                .mappings()
                .all()
            )
        if not rows and not await self._exists(guild_id, plan_id):
            raise PlanNotFound("plan not found")
        return [dict(row) for row in rows]

    async def symbol_bindings(self, guild_id: int, plan_id: UUID) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT symbol,resource_type,discord_id,status FROM "
                            "plan_symbol_bindings WHERE guild_id=:guild_id AND plan_id=:plan_id "
                            "ORDER BY symbol"
                        ),
                        {"guild_id": guild_id, "plan_id": plan_id},
                    )
                )
                .mappings()
                .all()
            )
        if not rows and not await self._exists(guild_id, plan_id):
            raise PlanNotFound("plan not found")
        return [dict(row) for row in rows]

    async def integrity_bundle(self, guild_id: int, plan_id: UUID) -> dict[str, Any]:
        """Read every immutable hash input in one tenant transaction."""
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            plan = await self._plan_row(session, guild_id, plan_id)
            if plan is None:
                raise PlanNotFound("plan not found")
            snapshot = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM plan_snapshots WHERE guild_id=:guild_id "
                            "AND id=:snapshot_id"
                        ),
                        {
                            "guild_id": guild_id,
                            "snapshot_id": plan["before_snapshot_id"],
                        },
                    )
                )
                .mappings()
                .one()
            )
            operation_rows = (
                (
                    await session.execute(
                        text(
                            "SELECT operations.*, COALESCE(array_agg(dependencies."
                            "predecessor_operation_id ORDER BY dependencies."
                            "predecessor_operation_id) FILTER (WHERE dependencies."
                            "predecessor_operation_id IS NOT NULL), '{}') AS predecessors "
                            "FROM plan_operations operations LEFT JOIN "
                            "plan_operation_dependencies dependencies ON "
                            "dependencies.guild_id=operations.guild_id AND "
                            "dependencies.plan_id=operations.plan_id AND "
                            "dependencies.operation_id=operations.id WHERE "
                            "operations.guild_id=:guild_id AND operations.plan_id=:plan_id "
                            "GROUP BY operations.guild_id,operations.plan_id,operations.id "
                            "ORDER BY operations.display_order"
                        ),
                        {"guild_id": guild_id, "plan_id": plan_id},
                    )
                )
                .mappings()
                .all()
            )
            symbol_rows = (
                (
                    await session.execute(
                        text(
                            "SELECT symbol,resource_type,producer_operation_id FROM "
                            "plan_symbol_bindings WHERE guild_id=:guild_id AND plan_id=:plan_id "
                            "ORDER BY symbol"
                        ),
                        {"guild_id": guild_id, "plan_id": plan_id},
                    )
                )
                .mappings()
                .all()
            )
        return {
            "plan": dict(plan),
            "snapshot": dict(snapshot),
            "operations": [dict(row) for row in operation_rows],
            "symbols": tuple(
                {
                    "symbol": str(row["symbol"]),
                    "resource_type": str(row["resource_type"]),
                    "producer_operation_id": str(row["producer_operation_id"]),
                }
                for row in symbol_rows
            ),
        }

    async def transition_plan(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        actor_user_id: int | None,
        expected: PlanState,
        target: PlanState,
        expected_version: int,
        correlation_id: UUID,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        timestamp_column = {
            PlanState.VALIDATED: "validated_at",
            PlanState.CONFIRMED: "confirmed_at",
            PlanState.APPLYING: "applying_at",
            PlanState.CANCEL_REQUESTED: "cancel_requested_at",
            PlanState.STALE: "drift_detected_at",
            PlanState.SUCCEEDED: "completed_at",
            PlanState.FAILED: "completed_at",
            PlanState.PARTIALLY_APPLIED: "completed_at",
            PlanState.VERIFICATION_FAILED: "completed_at",
            PlanState.CANCELLED: "completed_at",
            PlanState.INTERVENTION_REQUIRED: "completed_at",
        }.get(target)
        if timestamp_column is None:
            transition_sql = (
                "UPDATE plans SET status=:target,state_version=state_version+1,"
                "updated_at=now(),error_code=:error_code "
                "WHERE guild_id=:guild_id AND id=:plan_id AND status=:expected "
                "AND state_version=:version RETURNING *"
            )
        else:
            # Column names are a closed internal whitelist, never request data.
            timestamp_queries = {
                column: (
                    "UPDATE plans SET status=:target,state_version=state_version+1,"  # noqa: S608
                    f"updated_at=now(),error_code=:error_code,{column}=now() "
                    "WHERE guild_id=:guild_id AND id=:plan_id AND status=:expected "
                    "AND state_version=:version RETURNING *"
                )
                for column in (
                    "validated_at",
                    "confirmed_at",
                    "applying_at",
                    "cancel_requested_at",
                    "drift_detected_at",
                    "completed_at",
                )
            }
            transition_sql = timestamp_queries[timestamp_column]
        async with tenant_transaction(
            self._factory, TenantContext(guild_id, actor_user_id)
        ) as session:
            row = (
                (
                    await session.execute(
                        text(transition_sql),
                        {
                            "target": target.value,
                            "error_code": error_code,
                            "guild_id": guild_id,
                            "plan_id": plan_id,
                            "expected": expected.value,
                            "version": expected_version,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise PlanConflict("plan state compare-and-swap failed")
            await self._append_audit(
                session,
                guild_id=guild_id,
                actor_user_id=actor_user_id,
                event_type="PLAN_STATE_CHANGED",
                target_type="PLAN",
                target_id=str(plan_id),
                plan_id=plan_id,
                operation_id=None,
                correlation_id=correlation_id,
                result_state=target.value,
                data={"from": expected.value, "to": target.value, "error_code": error_code},
            )
            await self._append_progress(
                session,
                guild_id=guild_id,
                plan_id=plan_id,
                operation_id=None,
                plan_status=target,
                operation_status=None,
                message_key=f"plans.progress.{target.value.lower()}",
                error_code=error_code,
                correlation_id=correlation_id,
            )
            self.metrics.plan_transition(target)
            return dict(row)

    async def confirm(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        actor_user_id: int,
        idempotency_key: str,
        plan_hash: str,
        risk_level: RiskLevel,
        expires_at: datetime,
        expected_version: int,
        correlation_id: UUID,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        if expires_at <= now:
            raise ConfirmationInvalid("confirmation expiry must be in the future")
        async with tenant_transaction(
            self._factory, TenantContext(guild_id, actor_user_id)
        ) as session:
            plan = await self._plan_row(session, guild_id, plan_id)
            if plan is None:
                raise PlanNotFound("plan not found")
            if str(plan["plan_hash"]) != plan_hash or str(plan["risk_level"]) != risk_level.value:
                raise ConfirmationInvalid("confirmation does not match plan hash and risk")
            existing = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM plan_confirmations WHERE guild_id=:guild_id "
                            "AND plan_id=:plan_id AND actor_user_id=:actor "
                            "AND idempotency_key=:key"
                        ),
                        {
                            "guild_id": guild_id,
                            "plan_id": plan_id,
                            "actor": actor_user_id,
                            "key": idempotency_key,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                return dict(plan)
            if (
                str(plan["status"]) != PlanState.VALIDATED.value
                or int(plan["state_version"]) != expected_version
            ):
                raise PlanConflict("plan is not confirmable")
            await session.execute(
                text(
                    "INSERT INTO plan_confirmations "
                    "(id,guild_id,plan_id,actor_user_id,plan_hash,risk_level,"
                    "idempotency_key,confirmed_at,expires_at) VALUES "
                    "(:id,:guild_id,:plan_id,:actor,:hash,:risk,:key,:now,:expires)"
                ),
                {
                    "id": uuid4(),
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "actor": actor_user_id,
                    "hash": plan_hash,
                    "risk": risk_level.value,
                    "key": idempotency_key,
                    "now": now,
                    "expires": expires_at,
                },
            )
            updated = (
                (
                    await session.execute(
                        text(
                            "UPDATE plans SET status='CONFIRMED',confirmed_at=:now,"
                            "state_version=state_version+1,updated_at=:now WHERE "
                            "guild_id=:guild_id AND id=:plan_id AND status='VALIDATED' "
                            "AND state_version=:version RETURNING *"
                        ),
                        {
                            "now": now,
                            "guild_id": guild_id,
                            "plan_id": plan_id,
                            "version": expected_version,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if updated is None:
                raise PlanConflict("confirmation compare-and-swap failed")
            await self._append_audit(
                session,
                guild_id=guild_id,
                actor_user_id=actor_user_id,
                event_type="PLAN_CONFIRMED",
                target_type="PLAN",
                target_id=str(plan_id),
                plan_id=plan_id,
                operation_id=None,
                correlation_id=correlation_id,
                result_state=PlanState.CONFIRMED.value,
                data={"plan_hash": plan_hash, "risk_level": risk_level.value},
            )
            await self._append_progress(
                session,
                guild_id=guild_id,
                plan_id=plan_id,
                operation_id=None,
                plan_status=PlanState.CONFIRMED,
                operation_status=None,
                message_key="plans.progress.confirmed",
                error_code=None,
                correlation_id=correlation_id,
            )
            self.metrics.plan_transition(PlanState.CONFIRMED)
            return dict(updated)

    async def enqueue_apply(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        actor_user_id: int,
        correlation_id: UUID,
    ) -> UUID:
        job_id = uuid4()
        logical_key = f"apply-plan:{plan_id}"
        now = datetime.now(UTC)
        async with tenant_transaction(
            self._factory, TenantContext(guild_id, actor_user_id)
        ) as session:
            plan = await self._plan_row(session, guild_id, plan_id)
            if plan is None:
                raise PlanNotFound("plan not found")
            if str(plan["status"]) != PlanState.CONFIRMED.value:
                raise PlanConflict("only a confirmed plan can be enqueued")
            confirmation = await session.scalar(
                text(
                    "SELECT id FROM plan_confirmations WHERE guild_id=:guild_id "
                    "AND plan_id=:plan_id AND actor_user_id=:actor AND plan_hash=:hash "
                    "AND revoked_at IS NULL AND expires_at > :now "
                    "ORDER BY confirmed_at DESC LIMIT 1"
                ),
                {
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "actor": actor_user_id,
                    "hash": plan["plan_hash"],
                    "now": now,
                },
            )
            if confirmation is None:
                raise ConfirmationInvalid("plan confirmation is missing or expired")
            inserted = await session.scalar(
                text(
                    "INSERT INTO discord_io_jobs "
                    "(job_id,guild_id,workload_type,logical_key,priority,payload,requested_by,"
                    "correlation_id,available_at) VALUES "
                    "(:job_id,:guild_id,'APPLY_PLAN',:logical_key,0,CAST(:payload AS jsonb),"
                    ":actor,:correlation_id,:now) ON CONFLICT (guild_id,logical_key) "
                    "WHERE status IN ('PENDING','LEASED') DO NOTHING RETURNING job_id"
                ),
                {
                    "job_id": job_id,
                    "guild_id": guild_id,
                    "logical_key": logical_key,
                    "payload": json.dumps({"plan_id": str(plan_id)}, separators=(",", ":")),
                    "actor": actor_user_id,
                    "correlation_id": correlation_id,
                    "now": now,
                },
            )
            if inserted is None:
                existing = await session.scalar(
                    text(
                        "SELECT job_id FROM discord_io_jobs WHERE guild_id=:guild_id "
                        "AND logical_key=:logical_key AND status IN ('PENDING','LEASED') "
                        "ORDER BY created_at LIMIT 1"
                    ),
                    {"guild_id": guild_id, "logical_key": logical_key},
                )
                if existing is None:
                    raise PlanConflict("active apply idempotency conflict")
                return UUID(str(existing))
            await self._append_outbox(
                session,
                guild_id=guild_id,
                topic="discord.io.job.enqueued",
                payload={"job_id": str(job_id), "guild_id": str(guild_id), "plan_id": str(plan_id)},
                correlation_id=correlation_id,
            )
            await self._append_audit(
                session,
                guild_id=guild_id,
                actor_user_id=actor_user_id,
                event_type="PLAN_APPLY_ENQUEUED",
                target_type="PLAN",
                target_id=str(plan_id),
                plan_id=plan_id,
                operation_id=None,
                correlation_id=correlation_id,
                result_state="ENQUEUED",
                data={"job_id": str(job_id)},
            )
            return job_id

    async def request_cancel(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        actor_user_id: int,
        correlation_id: UUID,
    ) -> dict[str, Any]:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id, actor_user_id)
        ) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "UPDATE plans SET status=CASE WHEN status='APPLYING' THEN "
                            "'CANCEL_REQUESTED' ELSE 'CANCELLED' END, "
                            "cancel_requested_at=now(),state_version=state_version+1,"
                            "updated_at=now() "
                            "WHERE guild_id=:guild_id AND id=:plan_id AND status IN "
                            "('DRAFT','VALIDATED','CONFIRMED','APPLYING') RETURNING *"
                        ),
                        {"guild_id": guild_id, "plan_id": plan_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                current = await self._plan_row(session, guild_id, plan_id)
                if current is None:
                    raise PlanNotFound("plan not found")
                return dict(current)
            target = PlanState(str(row["status"]))
            await self._append_audit(
                session,
                guild_id=guild_id,
                actor_user_id=actor_user_id,
                event_type="PLAN_CANCEL_REQUESTED",
                target_type="PLAN",
                target_id=str(plan_id),
                plan_id=plan_id,
                operation_id=None,
                correlation_id=correlation_id,
                result_state=target.value,
                data={},
            )
            await self._append_progress(
                session,
                guild_id=guild_id,
                plan_id=plan_id,
                operation_id=None,
                plan_status=target,
                operation_status=None,
                message_key=f"plans.progress.{target.value.lower()}",
                error_code=None,
                correlation_id=correlation_id,
            )
            self.metrics.plan_transition(target)
            return dict(row)

    async def begin_apply(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        job_id: UUID,
        lease_owner: str,
        lease_token: UUID,
        lease_generation: int,
        actor_user_id: int,
        correlation_id: UUID,
    ) -> dict[str, Any]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await self._assert_job_fence(
                session,
                guild_id=guild_id,
                job_id=job_id,
                lease_owner=lease_owner,
                lease_token=lease_token,
                lease_generation=lease_generation,
            )
            plan = await self._plan_row(session, guild_id, plan_id)
            if plan is None:
                raise PlanNotFound("plan not found")
            if str(plan["status"]) == PlanState.APPLYING.value:
                return dict(plan)
            confirmation = await session.scalar(
                text(
                    "SELECT id FROM plan_confirmations WHERE guild_id=:guild_id AND "
                    "plan_id=:plan_id AND actor_user_id=:actor AND plan_hash=:hash "
                    "AND revoked_at IS NULL "
                    "AND expires_at > now() ORDER BY confirmed_at DESC LIMIT 1"
                ),
                {
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "actor": actor_user_id,
                    "hash": plan["plan_hash"],
                },
            )
            if confirmation is None:
                raise ConfirmationInvalid("confirmation expired before apply")
            requested_by = await session.scalar(
                text(
                    "SELECT requested_by FROM discord_io_jobs WHERE guild_id=:guild_id "
                    "AND job_id=:job_id"
                ),
                {"guild_id": guild_id, "job_id": job_id},
            )
            if requested_by is None or int(requested_by) != actor_user_id:
                raise PlanFencingError("apply actor does not match the durable job requester")
            row = (
                (
                    await session.execute(
                        text(
                            "UPDATE plans SET status='APPLYING',applying_at=now(),"
                            "state_version=state_version+1,updated_at=now() "
                            "WHERE guild_id=:guild_id "
                            "AND id=:plan_id AND status='CONFIRMED' RETURNING *"
                        ),
                        {"guild_id": guild_id, "plan_id": plan_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise PlanConflict("plan could not claim APPLYING state")
            await self._append_progress(
                session,
                guild_id=guild_id,
                plan_id=plan_id,
                operation_id=None,
                plan_status=PlanState.APPLYING,
                operation_status=None,
                message_key="plans.progress.applying",
                error_code=None,
                correlation_id=correlation_id,
            )
            self.metrics.plan_transition(PlanState.APPLYING)
            return dict(row)

    async def prepare_next_operation(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        job_id: UUID,
        lease_owner: str,
        lease_token: UUID,
        lease_generation: int,
    ) -> dict[str, Any] | None:
        attempt_id = uuid4()
        now = datetime.now(UTC)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await self._assert_job_fence(
                session,
                guild_id=guild_id,
                job_id=job_id,
                lease_owner=lease_owner,
                lease_token=lease_token,
                lease_generation=lease_generation,
            )
            plan_status = await session.scalar(
                text("SELECT status FROM plans WHERE guild_id=:guild_id AND id=:plan_id"),
                {"guild_id": guild_id, "plan_id": plan_id},
            )
            if plan_status != PlanState.APPLYING.value:
                return None
            abandoned = (
                (
                    await session.execute(
                        text(
                            "SELECT attempts.id FROM operation_attempts attempts JOIN "
                            "plan_operations operations ON operations.guild_id=attempts.guild_id "
                            "AND operations.plan_id=attempts.plan_id AND operations.id="
                            "attempts.operation_id WHERE attempts.guild_id=:guild_id AND "
                            "attempts.plan_id=:plan_id AND attempts.status='PREPARED' AND "
                            "operations.status='PENDING' FOR UPDATE OF attempts"
                        ),
                        {"guild_id": guild_id, "plan_id": plan_id},
                    )
                )
                .scalars()
                .all()
            )
            if abandoned:
                await session.execute(
                    text(
                        "UPDATE operation_attempts SET status='FAILED',completed_at=:now,"
                        "outcome_detail=CAST(:detail AS jsonb) "
                        "WHERE guild_id=:guild_id AND plan_id=:plan_id AND id=ANY(:ids)"
                    ),
                    {
                        "now": now,
                        "guild_id": guild_id,
                        "plan_id": plan_id,
                        "ids": abandoned,
                        "detail": json.dumps({"reason": "PREPARED_LEASE_RECOVERED"}),
                    },
                )
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT operations.* FROM plan_operations AS operations WHERE "
                            "operations.guild_id=:guild_id AND operations.plan_id=:plan_id "
                            "AND operations.status='PENDING' AND NOT EXISTS (SELECT 1 FROM "
                            "plan_operation_dependencies dependencies JOIN plan_operations "
                            "predecessors ON predecessors.guild_id=dependencies.guild_id AND "
                            "predecessors.plan_id=dependencies.plan_id AND predecessors.id="
                            "dependencies.predecessor_operation_id WHERE dependencies.guild_id="
                            "operations.guild_id AND dependencies.plan_id=operations.plan_id AND "
                            "dependencies.operation_id=operations.id AND predecessors.status<>"
                            "'SUCCEEDED') AND NOT EXISTS (SELECT 1 FROM unnest(operations."
                            "consumes_symbols) consumed(symbol) LEFT JOIN plan_symbol_bindings "
                            "bindings ON bindings.guild_id=operations.guild_id AND bindings."
                            "plan_id=operations.plan_id AND bindings.symbol=consumed.symbol "
                            "WHERE bindings.status IS DISTINCT FROM 'BOUND') ORDER BY "
                            "operations.display_order LIMIT 1 FOR UPDATE SKIP LOCKED"
                        ),
                        {"guild_id": guild_id, "plan_id": plan_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            attempt_number = int(row["attempt_count"]) + 1
            resolved_payload = await self._resolve_payload_symbols(
                session, guild_id, plan_id, dict(row["desired_payload"])
            )
            request_fingerprint = canonical_hash(
                {
                    "operation_type": str(row["operation_type"]),
                    "resource_ref": str(row["resource_ref"]),
                    "payload": resolved_payload,
                }
            )
            await session.execute(
                text(
                    "UPDATE plan_operations SET attempt_count=:attempt,state_version="
                    "state_version+1,updated_at=:now WHERE guild_id=:guild_id AND "
                    "plan_id=:plan_id AND id=:id AND status='PENDING'"
                ),
                {
                    "attempt": attempt_number,
                    "now": now,
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "id": row["id"],
                },
            )
            await session.execute(
                text(
                    "INSERT INTO operation_attempts "
                    "(id,guild_id,plan_id,operation_id,attempt_number,status,prepared_at,"
                    "in_flight_at,request_fingerprint,lease_owner,lease_token,lease_generation,"
                    "outcome_detail) VALUES "
                    "(:id,:guild_id,:plan_id,:operation_id,:attempt,'PREPARED',:now,NULL,"
                    ":fingerprint,:owner,:token,:generation,CAST(:detail AS jsonb))"
                ),
                {
                    "id": attempt_id,
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "operation_id": row["id"],
                    "attempt": attempt_number,
                    "now": now,
                    "fingerprint": request_fingerprint,
                    "owner": lease_owner,
                    "token": lease_token,
                    "generation": lease_generation,
                    "detail": json.dumps(
                        {"resolved_payload": resolved_payload}, separators=(",", ":")
                    ),
                },
            )
            result = dict(row)
            result.update(
                {
                    "attempt_id": attempt_id,
                    "attempt_number": attempt_number,
                    "request_fingerprint": request_fingerprint,
                    "resolved_payload": resolved_payload,
                }
            )
            return result

    async def mark_attempt_in_flight(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        operation_id: UUID,
        attempt_id: UUID,
        job_id: UUID,
        lease_owner: str,
        lease_token: UUID,
        lease_generation: int,
    ) -> None:
        now = datetime.now(UTC)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await self._assert_job_fence(
                session,
                guild_id=guild_id,
                job_id=job_id,
                lease_owner=lease_owner,
                lease_token=lease_token,
                lease_generation=lease_generation,
            )
            attempt_result = await session.execute(
                text(
                    "UPDATE operation_attempts SET status='IN_FLIGHT',in_flight_at=:now "
                    "WHERE guild_id=:guild_id AND plan_id=:plan_id AND id=:attempt_id "
                    "AND operation_id=:operation_id AND status='PREPARED'"
                ),
                {
                    "now": now,
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "attempt_id": attempt_id,
                    "operation_id": operation_id,
                },
            )
            operation_result = await session.execute(
                text(
                    "UPDATE plan_operations SET status='IN_FLIGHT',state_version="
                    "state_version+1,started_at=COALESCE(started_at,:now),updated_at=:now "
                    "WHERE guild_id=:guild_id AND plan_id=:plan_id AND id=:operation_id "
                    "AND status='PENDING'"
                ),
                {
                    "now": now,
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "operation_id": operation_id,
                },
            )
            if (
                getattr(attempt_result, "rowcount", 0) != 1
                or getattr(operation_result, "rowcount", 0) != 1
            ):
                raise PlanConflict("prepared attempt is no longer claimable")
            operation = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM plan_operations WHERE guild_id=:guild_id AND "
                            "plan_id=:plan_id AND id=:operation_id"
                        ),
                        {
                            "guild_id": guild_id,
                            "plan_id": plan_id,
                            "operation_id": operation_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            resolved_payload = await session.scalar(
                text(
                    "SELECT outcome_detail->'resolved_payload' FROM operation_attempts "
                    "WHERE guild_id=:guild_id AND plan_id=:plan_id AND id=:attempt_id"
                ),
                {"guild_id": guild_id, "plan_id": plan_id, "attempt_id": attempt_id},
            )
            if OperationType(str(operation["operation_type"])) in {
                OperationType.REORDER_ROLES,
                OperationType.MOVE_OR_REORDER_CHANNELS,
                OperationType.UPSERT_OVERWRITE,
                OperationType.DELETE_OVERWRITE,
            }:
                await self._register_expected_gateway(
                    session,
                    guild_id,
                    plan_id,
                    operation,
                    self._result_resource_id(operation, dict(resolved_payload or {})),
                    dict(resolved_payload or {}),
                    now,
                )

    async def reject_operation_precondition(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        operation_id: UUID,
        attempt_id: UUID,
        job_id: UUID,
        lease_owner: str,
        lease_token: UUID,
        lease_generation: int,
        outcome: str,
        correlation_id: UUID,
    ) -> None:
        if outcome not in {"CHANGED", "UNKNOWN"}:
            raise ValueError("precondition rejection requires CHANGED or UNKNOWN")
        code = f"OPERATION_PRECONDITION_{outcome}"
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await self._assert_job_fence(
                session,
                guild_id=guild_id,
                job_id=job_id,
                lease_owner=lease_owner,
                lease_token=lease_token,
                lease_generation=lease_generation,
            )
            attempt = await session.scalar(
                text(
                    "UPDATE operation_attempts SET status='FAILED',completed_at=now(),"
                    "error_classification=:code,outcome_detail=CAST(:detail AS jsonb) "
                    "WHERE guild_id=:guild_id AND plan_id=:plan_id AND id=:attempt_id "
                    "AND operation_id=:operation_id AND status='PREPARED' AND "
                    "lease_owner=:owner AND lease_token=:token AND lease_generation="
                    ":generation RETURNING id"
                ),
                {
                    "code": code,
                    "detail": json.dumps({"precondition_outcome": outcome}),
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "attempt_id": attempt_id,
                    "operation_id": operation_id,
                    "owner": lease_owner,
                    "token": lease_token,
                    "generation": lease_generation,
                },
            )
            if attempt is None:
                raise PlanFencingError("prepared precondition attempt is no longer current")
            operation = await session.scalar(
                text(
                    "UPDATE plan_operations SET status='INTERVENTION_REQUIRED',"
                    "error_code=:code,completed_at=now(),state_version=state_version+1,"
                    "updated_at=now() WHERE guild_id=:guild_id AND plan_id=:plan_id "
                    "AND id=:operation_id AND status='PENDING' AND attempt_count="
                    "(SELECT attempt_number FROM operation_attempts WHERE guild_id=:guild_id "
                    "AND plan_id=:plan_id AND id=:attempt_id) RETURNING id"
                ),
                {
                    "code": code,
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "operation_id": operation_id,
                    "attempt_id": attempt_id,
                },
            )
            if operation is None:
                raise PlanFencingError("operation precondition attempt was superseded")
            await session.execute(
                text(
                    "UPDATE plans SET status='INTERVENTION_REQUIRED',error_code=:code,"
                    "completed_at=now(),state_version=state_version+1,updated_at=now() "
                    "WHERE guild_id=:guild_id AND id=:plan_id AND status='APPLYING'"
                ),
                {"code": code, "guild_id": guild_id, "plan_id": plan_id},
            )
            await self._append_audit(
                session,
                guild_id=guild_id,
                actor_user_id=None,
                event_type="PLAN_OPERATION_PRECONDITION_REJECTED",
                target_type="PLAN_OPERATION",
                target_id=str(operation_id),
                plan_id=plan_id,
                operation_id=operation_id,
                correlation_id=correlation_id,
                result_state=OperationState.INTERVENTION_REQUIRED.value,
                data={"precondition_outcome": outcome},
            )
            await self._append_progress(
                session,
                guild_id=guild_id,
                plan_id=plan_id,
                operation_id=operation_id,
                plan_status=PlanState.INTERVENTION_REQUIRED,
                operation_status=OperationState.INTERVENTION_REQUIRED,
                message_key="plans.progress.preconditionRejected",
                error_code=code,
                correlation_id=correlation_id,
            )

    async def record_operation_success(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        operation_id: UUID,
        attempt_id: UUID,
        job_id: UUID,
        lease_owner: str,
        lease_token: UUID,
        lease_generation: int,
        discord_status: int,
        result_payload: dict[str, Any],
        correlation_id: UUID,
        audit_reason_fingerprint: str,
    ) -> None:
        now = datetime.now(UTC)
        result_fingerprint = canonical_hash(result_payload)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await self._assert_job_fence(
                session,
                guild_id=guild_id,
                job_id=job_id,
                lease_owner=lease_owner,
                lease_token=lease_token,
                lease_generation=lease_generation,
            )
            operation = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM plan_operations WHERE guild_id=:guild_id "
                            "AND plan_id=:plan_id AND id=:operation_id FOR UPDATE"
                        ),
                        {
                            "guild_id": guild_id,
                            "plan_id": plan_id,
                            "operation_id": operation_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if operation is None:
                raise PlanNotFound("operation not found")
            if str(operation["status"]) == OperationState.SUCCEEDED.value:
                return
            if str(operation["status"]) != OperationState.IN_FLIGHT.value:
                raise PlanConflict("operation is not in flight")
            attempt_updated = await session.scalar(
                text(
                    "UPDATE operation_attempts SET status='SUCCEEDED',completed_at=:now,"
                    "discord_status=:discord_status,result_fingerprint=:fingerprint,"
                    "outcome_detail=CAST(:detail AS jsonb) WHERE guild_id=:guild_id AND "
                    "plan_id=:plan_id AND operation_id=:operation_id AND id=:attempt_id "
                    "AND status='IN_FLIGHT' AND lease_owner=:owner AND lease_token=:token "
                    "AND lease_generation=:generation RETURNING id"
                ),
                {
                    "now": now,
                    "discord_status": discord_status,
                    "fingerprint": result_fingerprint,
                    "detail": json.dumps(
                        {"audit_reason_fingerprint": audit_reason_fingerprint},
                        separators=(",", ":"),
                    ),
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "operation_id": operation_id,
                    "attempt_id": attempt_id,
                    "owner": lease_owner,
                    "token": lease_token,
                    "generation": lease_generation,
                },
            )
            if attempt_updated is None:
                raise PlanFencingError("attempt fencing token is no longer current")
            resource_id = self._result_resource_id(operation, result_payload)
            persisted_resource_id = self._persisted_result_resource_id(operation, resource_id)
            await session.execute(
                text(
                    "UPDATE plan_operations SET status='SUCCEEDED',result_payload="
                    "CAST(:result AS jsonb),result_fingerprint=:fingerprint,"
                    "resource_discord_id=COALESCE(resource_discord_id,:resource_id),"
                    "completed_at=:now,state_version=state_version+1,updated_at=:now "
                    "WHERE guild_id=:guild_id AND plan_id=:plan_id AND id=:operation_id"
                ),
                {
                    "result": json.dumps(result_payload, separators=(",", ":")),
                    "fingerprint": result_fingerprint,
                    "resource_id": persisted_resource_id,
                    "now": now,
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "operation_id": operation_id,
                },
            )
            symbol = operation["produces_symbol"]
            if symbol is not None:
                if resource_id is None:
                    raise PlanConflict("successful CREATE did not return a resource ID")
                bound = await session.scalar(
                    text(
                        "UPDATE plan_symbol_bindings SET discord_id=:discord_id,status='BOUND',"
                        "binding_fingerprint=:fingerprint,bound_at=:now,binding_version="
                        "binding_version+1 WHERE guild_id=:guild_id AND plan_id=:plan_id "
                        "AND symbol=:symbol AND (discord_id IS NULL OR discord_id=:discord_id) "
                        "RETURNING symbol"
                    ),
                    {
                        "discord_id": resource_id,
                        "fingerprint": result_fingerprint,
                        "now": now,
                        "guild_id": guild_id,
                        "plan_id": plan_id,
                        "symbol": symbol,
                    },
                )
                if bound is None:
                    raise PlanConflict("symbol binding is ambiguous or already bound elsewhere")
            await self._write_through(
                session, guild_id, operation, result_payload, resource_id, now
            )
            await self._register_expected_gateway(
                session,
                guild_id,
                plan_id,
                operation,
                resource_id,
                result_payload,
                now,
            )
            await self._append_audit(
                session,
                guild_id=guild_id,
                actor_user_id=None,
                event_type="PLAN_OPERATION_SUCCEEDED",
                target_type=str(operation["resource_type"]),
                target_id=str(resource_id or operation["resource_ref"]),
                plan_id=plan_id,
                operation_id=operation_id,
                correlation_id=correlation_id,
                result_state=OperationState.SUCCEEDED.value,
                data={
                    "result_fingerprint": result_fingerprint,
                    "audit_reason_fingerprint": audit_reason_fingerprint,
                },
            )
            await self._append_progress(
                session,
                guild_id=guild_id,
                plan_id=plan_id,
                operation_id=operation_id,
                plan_status=PlanState.APPLYING,
                operation_status=OperationState.SUCCEEDED,
                message_key="plans.progress.operationSucceeded",
                error_code=None,
                correlation_id=correlation_id,
            )
            self.metrics.operation_transition(
                OperationType(str(operation["operation_type"])),
                OperationState.SUCCEEDED,
            )

    async def record_operation_failure(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        operation_id: UUID,
        attempt_id: UUID,
        job_id: UUID,
        lease_owner: str,
        lease_token: UUID,
        lease_generation: int,
        unknown_outcome: bool,
        discord_status: int | None,
        discord_error_code: int | None,
        error_classification: str,
        correlation_id: UUID,
        retryable_rejection: bool = False,
    ) -> None:
        now = datetime.now(UTC)
        attempt_state = AttemptState.UNKNOWN if unknown_outcome else AttemptState.FAILED
        operation_state = (
            OperationState.UNKNOWN_OUTCOME
            if unknown_outcome
            else OperationState.PENDING
            if retryable_rejection
            else OperationState.FAILED
        )
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await self._assert_job_fence(
                session,
                guild_id=guild_id,
                job_id=job_id,
                lease_owner=lease_owner,
                lease_token=lease_token,
                lease_generation=lease_generation,
            )
            updated = await session.scalar(
                text(
                    "UPDATE operation_attempts SET status=:attempt_status,completed_at=:now,"
                    "discord_status=:discord_status,discord_error_code=:error_code,"
                    "error_classification=:classification WHERE guild_id=:guild_id AND "
                    "plan_id=:plan_id AND operation_id=:operation_id AND id=:attempt_id "
                    "AND status='IN_FLIGHT' AND lease_owner=:owner AND lease_token=:token "
                    "AND lease_generation=:generation RETURNING id"
                ),
                {
                    "attempt_status": attempt_state.value,
                    "now": now,
                    "discord_status": discord_status,
                    "error_code": discord_error_code,
                    "classification": error_classification,
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "operation_id": operation_id,
                    "attempt_id": attempt_id,
                    "owner": lease_owner,
                    "token": lease_token,
                    "generation": lease_generation,
                },
            )
            if updated is None:
                raise PlanFencingError("attempt fencing token is no longer current")
            await session.execute(
                text(
                    "UPDATE plan_operations SET status=:status,error_code=:classification,"
                    "completed_at=:completed,"
                    "state_version=state_version+1,updated_at=:now WHERE "
                    "guild_id=:guild_id AND plan_id=:plan_id AND id=:operation_id "
                    "AND status='IN_FLIGHT'"
                ),
                {
                    "status": operation_state.value,
                    "classification": error_classification,
                    "completed": None if retryable_rejection or unknown_outcome else now,
                    "now": now,
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "operation_id": operation_id,
                },
            )
            await self._append_audit(
                session,
                guild_id=guild_id,
                actor_user_id=None,
                event_type=(
                    "PLAN_OPERATION_UNKNOWN"
                    if unknown_outcome
                    else "PLAN_OPERATION_RETRY_SCHEDULED"
                    if retryable_rejection
                    else "PLAN_OPERATION_FAILED"
                ),
                target_type="PLAN_OPERATION",
                target_id=str(operation_id),
                plan_id=plan_id,
                operation_id=operation_id,
                correlation_id=correlation_id,
                result_state=operation_state.value,
                data={"error_classification": error_classification},
            )
            await self._append_progress(
                session,
                guild_id=guild_id,
                plan_id=plan_id,
                operation_id=operation_id,
                plan_status=PlanState.APPLYING,
                operation_status=operation_state,
                message_key=(
                    "plans.progress.operationUnknown"
                    if unknown_outcome
                    else "plans.progress.operationRetryScheduled"
                    if retryable_rejection
                    else "plans.progress.operationFailed"
                ),
                error_code=error_classification,
                correlation_id=correlation_id,
            )
            operation_type = await session.scalar(
                text(
                    "SELECT operation_type FROM plan_operations WHERE guild_id=:guild_id "
                    "AND plan_id=:plan_id AND id=:operation_id"
                ),
                {
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "operation_id": operation_id,
                },
            )
            if operation_type is not None:
                self.metrics.operation_transition(
                    OperationType(str(operation_type)), operation_state
                )

    async def unresolved_operation(self, guild_id: int, plan_id: UUID) -> dict[str, Any] | None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM plan_operations WHERE guild_id=:guild_id "
                            "AND plan_id=:plan_id AND status='UNKNOWN_OUTCOME' "
                            "ORDER BY display_order LIMIT 1"
                        ),
                        {"guild_id": guild_id, "plan_id": plan_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    async def resolve_unknown(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        operation_id: UUID,
        outcome: str,
        resource_payload: dict[str, Any] | None,
        correlation_id: UUID,
    ) -> None:
        if outcome not in {"PROVED_CREATED", "PROVED_APPLIED", "PROVED_ABSENT", "AMBIGUOUS"}:
            raise ValueError("unsupported recovery outcome")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            operation = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM plan_operations WHERE guild_id=:guild_id "
                            "AND plan_id=:plan_id AND id=:operation_id FOR UPDATE"
                        ),
                        {
                            "guild_id": guild_id,
                            "plan_id": plan_id,
                            "operation_id": operation_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if operation is None:
                raise PlanNotFound("operation not found")
            if str(operation["status"]) != OperationState.UNKNOWN_OUTCOME.value:
                return
            if outcome in {"PROVED_CREATED", "PROVED_APPLIED"}:
                if resource_payload is None:
                    if OperationType(str(operation["operation_type"])) not in {
                        OperationType.DELETE_ROLE,
                        OperationType.DELETE_CHANNEL,
                        OperationType.DELETE_OVERWRITE,
                    }:
                        raise ValueError("proved recovery requires observed payload")
                    resource_payload = {
                        **dict(operation["desired_payload"]),
                        "deleted": True,
                    }
                resource_id = self._result_resource_id(operation, resource_payload)
                persisted_resource_id = self._persisted_result_resource_id(operation, resource_id)
                fingerprint = canonical_hash(resource_payload)
                await session.execute(
                    text(
                        "UPDATE plan_operations SET status='SUCCEEDED',result_payload="
                        "CAST(:payload AS jsonb),result_fingerprint=:fingerprint,"
                        "resource_discord_id=COALESCE(resource_discord_id,:resource_id),"
                        "completed_at=now(),state_version=state_version+1,updated_at=now() "
                        "WHERE guild_id=:guild_id AND plan_id=:plan_id AND id=:operation_id"
                    ),
                    {
                        "payload": json.dumps(resource_payload, separators=(",", ":")),
                        "fingerprint": fingerprint,
                        "resource_id": persisted_resource_id,
                        "guild_id": guild_id,
                        "plan_id": plan_id,
                        "operation_id": operation_id,
                    },
                )
                if operation["produces_symbol"] is not None:
                    if resource_id is None:
                        raise PlanConflict("recovered CREATE has no resource ID")
                    bound = await session.scalar(
                        text(
                            "UPDATE plan_symbol_bindings SET discord_id=:resource_id,"
                            "status='BOUND',binding_fingerprint=:fingerprint,bound_at=now(),"
                            "binding_version=binding_version+1 WHERE guild_id=:guild_id "
                            "AND plan_id=:plan_id AND symbol=:symbol AND discord_id IS NULL "
                            "RETURNING symbol"
                        ),
                        {
                            "resource_id": resource_id,
                            "fingerprint": fingerprint,
                            "guild_id": guild_id,
                            "plan_id": plan_id,
                            "symbol": operation["produces_symbol"],
                        },
                    )
                    if bound is None:
                        raise PlanConflict("recovered symbol binding is ambiguous")
                await self._write_through(
                    session,
                    guild_id,
                    operation,
                    resource_payload,
                    resource_id,
                    datetime.now(UTC),
                )
                state = OperationState.SUCCEEDED
            elif outcome == "PROVED_ABSENT":
                await session.execute(
                    text(
                        "UPDATE plan_operations SET status='PENDING',error_code=NULL,"
                        "completed_at=NULL,state_version=state_version+1,updated_at=now() "
                        "WHERE guild_id=:guild_id AND plan_id=:plan_id AND id=:operation_id"
                    ),
                    {"guild_id": guild_id, "plan_id": plan_id, "operation_id": operation_id},
                )
                state = OperationState.PENDING
            else:
                await session.execute(
                    text(
                        "UPDATE plan_operations SET status='INTERVENTION_REQUIRED',"
                        "error_code='UNKNOWN_OUTCOME_AMBIGUOUS',completed_at=now(),"
                        "state_version=state_version+1,updated_at=now() WHERE "
                        "guild_id=:guild_id AND plan_id=:plan_id AND id=:operation_id"
                    ),
                    {"guild_id": guild_id, "plan_id": plan_id, "operation_id": operation_id},
                )
                await session.execute(
                    text(
                        "UPDATE plans SET status='INTERVENTION_REQUIRED',"
                        "error_code='UNKNOWN_OUTCOME_AMBIGUOUS',completed_at=now(),"
                        "state_version=state_version+1,updated_at=now() WHERE "
                        "guild_id=:guild_id AND id=:plan_id AND status='APPLYING'"
                    ),
                    {"guild_id": guild_id, "plan_id": plan_id},
                )
                state = OperationState.INTERVENTION_REQUIRED
            await self._append_audit(
                session,
                guild_id=guild_id,
                actor_user_id=None,
                event_type="UNKNOWN_OUTCOME_RECOVERED",
                target_type="PLAN_OPERATION",
                target_id=str(operation_id),
                plan_id=plan_id,
                operation_id=operation_id,
                correlation_id=correlation_id,
                result_state=state.value,
                data={"recovery_outcome": outcome},
            )
            self.metrics.unknown_recovery(outcome)

    async def operation_counts(self, guild_id: int, plan_id: UUID) -> dict[str, int]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT status,count(*) AS count FROM plan_operations WHERE "
                            "guild_id=:guild_id AND plan_id=:plan_id GROUP BY status"
                        ),
                        {"guild_id": guild_id, "plan_id": plan_id},
                    )
                )
                .mappings()
                .all()
            )
        return {str(row["status"]): int(row["count"]) for row in rows}

    async def finalize_plan(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        status: PlanState,
        verification_summary: dict[str, Any],
        error_code: str | None,
        correlation_id: UUID,
    ) -> None:
        if status not in {
            PlanState.SUCCEEDED,
            PlanState.FAILED,
            PlanState.PARTIALLY_APPLIED,
            PlanState.VERIFICATION_FAILED,
            PlanState.CANCELLED,
            PlanState.INTERVENTION_REQUIRED,
        }:
            raise ValueError("finalize_plan requires a terminal state")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            current = await session.scalar(
                text("SELECT status FROM plans WHERE guild_id=:guild_id AND id=:plan_id"),
                {"guild_id": guild_id, "plan_id": plan_id},
            )
            if current in {
                PlanState.SUCCEEDED.value,
                PlanState.FAILED.value,
                PlanState.PARTIALLY_APPLIED.value,
                PlanState.VERIFICATION_FAILED.value,
                PlanState.CANCELLED.value,
                PlanState.INTERVENTION_REQUIRED.value,
            }:
                return
            await session.execute(
                text(
                    "UPDATE plans SET status=:status,verification_summary=CAST(:summary AS jsonb),"
                    "error_code=:error_code,completed_at=now(),state_version=state_version+1,"
                    "updated_at=now() WHERE guild_id=:guild_id AND id=:plan_id AND status IN "
                    "('APPLYING','CANCEL_REQUESTED')"
                ),
                {
                    "status": status.value,
                    "summary": json.dumps(verification_summary, separators=(",", ":")),
                    "error_code": error_code,
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                },
            )
            await self._append_audit(
                session,
                guild_id=guild_id,
                actor_user_id=None,
                event_type="PLAN_FINALIZED",
                target_type="PLAN",
                target_id=str(plan_id),
                plan_id=plan_id,
                operation_id=None,
                correlation_id=correlation_id,
                result_state=status.value,
                data={"verification": verification_summary, "error_code": error_code},
            )
            await self._append_progress(
                session,
                guild_id=guild_id,
                plan_id=plan_id,
                operation_id=None,
                plan_status=status,
                operation_status=None,
                message_key=f"plans.progress.{status.value.lower()}",
                error_code=error_code,
                correlation_id=correlation_id,
            )
            self.metrics.plan_transition(status)

    async def inflight_attempt_fence(self, guild_id: int, plan_id: UUID) -> dict[str, Any] | None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT attempts.lease_owner,attempts.lease_token,"
                            "attempts.lease_generation FROM operation_attempts attempts "
                            "JOIN plan_operations operations ON operations.guild_id="
                            "attempts.guild_id AND operations.plan_id=attempts.plan_id "
                            "AND operations.id=attempts.operation_id WHERE attempts.guild_id="
                            ":guild_id AND attempts.plan_id=:plan_id AND attempts.status="
                            "'IN_FLIGHT' AND operations.status='IN_FLIGHT' ORDER BY "
                            "attempts.attempt_number DESC LIMIT 1"
                        ),
                        {"guild_id": guild_id, "plan_id": plan_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    async def mark_inflight_unknown_after_lease_loss(
        self,
        guild_id: int,
        plan_id: UUID,
        *,
        lease_owner: str,
        lease_token: UUID,
        lease_generation: int,
        correlation_id: UUID,
    ) -> int:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "WITH lost AS (UPDATE operation_attempts SET status='UNKNOWN',"
                            "completed_at=now(),error_classification='WORKER_LEASE_LOST' "
                            "WHERE guild_id=:guild_id AND plan_id=:plan_id AND status="
                            "'IN_FLIGHT' AND lease_owner=:owner AND lease_token=:token "
                            "AND lease_generation=:generation RETURNING operation_id,"
                            "attempt_number) "
                            "UPDATE plan_operations operations SET status='UNKNOWN_OUTCOME',"
                            "error_code='WORKER_LEASE_LOST',state_version=state_version+1,"
                            "updated_at=now() FROM lost WHERE operations.guild_id=:guild_id "
                            "AND operations.plan_id=:plan_id AND operations.id="
                            "lost.operation_id AND operations.status='IN_FLIGHT' AND "
                            "operations.attempt_count=lost.attempt_number RETURNING "
                            "operations.id"
                        ),
                        {
                            "guild_id": guild_id,
                            "plan_id": plan_id,
                            "owner": lease_owner,
                            "token": lease_token,
                            "generation": lease_generation,
                        },
                    )
                )
                .scalars()
                .all()
            )
            if rows:
                for operation_id in rows:
                    await self._append_audit(
                        session,
                        guild_id=guild_id,
                        actor_user_id=None,
                        event_type="PLAN_OPERATION_UNKNOWN",
                        target_type="PLAN_OPERATION",
                        target_id=str(operation_id),
                        plan_id=plan_id,
                        operation_id=UUID(str(operation_id)),
                        correlation_id=correlation_id,
                        result_state=OperationState.UNKNOWN_OUTCOME.value,
                        data={"reason": "WORKER_LEASE_LOST"},
                    )
            return len(rows)

    async def progress_since(
        self, guild_id: int, plan_id: UUID, *, after_sequence: int = 0
    ) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM plan_progress_events WHERE guild_id=:guild_id "
                            "AND plan_id=:plan_id AND sequence>:after ORDER BY sequence LIMIT 1000"
                        ),
                        {"guild_id": guild_id, "plan_id": plan_id, "after": after_sequence},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def _exists(self, guild_id: int, plan_id: UUID) -> bool:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return (
                await session.scalar(
                    text("SELECT 1 FROM plans WHERE guild_id=:guild_id AND id=:plan_id"),
                    {"guild_id": guild_id, "plan_id": plan_id},
                )
            ) is not None

    @staticmethod
    async def _plan_row(session: AsyncSession, guild_id: int, plan_id: UUID) -> Any | None:
        return (
            (
                await session.execute(
                    text("SELECT * FROM plans WHERE guild_id=:guild_id AND id=:plan_id"),
                    {"guild_id": guild_id, "plan_id": plan_id},
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    async def _plan_by_idempotency(
        session: AsyncSession,
        guild_id: int,
        actor_user_id: int,
        idempotency_key: str,
    ) -> Any | None:
        return (
            (
                await session.execute(
                    text(
                        "SELECT * FROM plans WHERE guild_id=:guild_id "
                        "AND actor_user_id=:actor AND idempotency_key=:key"
                    ),
                    {"guild_id": guild_id, "actor": actor_user_id, "key": idempotency_key},
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    async def _insert_resource_dependencies(
        session: AsyncSession,
        *,
        guild_id: int,
        plan_id: UUID,
        operations: tuple[PlanOperation, ...],
        before_snapshot: dict[str, Any],
    ) -> None:
        dependencies: dict[tuple[str, int], str] = {}

        def remember(resource_type: str, value: object, reason: str) -> None:
            rendered = str(value)
            if value is None or not rendered.isdecimal() or int(rendered) <= 0:
                return
            normalized = "CHANNEL" if resource_type == "CATEGORY" else resource_type
            dependencies.setdefault((normalized, int(rendered)), reason)

        category_targets: set[int] = set()
        for operation in operations:
            payload = thaw_json_object(operation.desired_payload)
            before = thaw_json_object(operation.before_payload)
            target_type = operation.resource_type.value
            remember(target_type, payload.get("id") or before.get("id"), "TARGET")
            remember("CHANNEL", payload.get("parent_id") or before.get("parent_id"), "PARENT")
            remember("CHANNEL", payload.get("channel_id") or before.get("channel_id"), "TARGET")
            subject_id = payload.get("subject_id") or payload.get("target_id")
            if int(payload.get("target_type", before.get("target_type", 0)) or 0) == 0:
                remember("ROLE", subject_id, "SUBJECT")
            for item in payload.get("items", []):
                if isinstance(item, dict):
                    remember(target_type, item.get("id"), "TARGET")
                    remember("CHANNEL", item.get("parent_id"), "PARENT")
            if (
                operation.operation_type is OperationType.DELETE_CHANNEL
                and operation.resource_type.value == "CATEGORY"
            ):
                raw_id = payload.get("id") or before.get("id")
                if raw_id is not None:
                    category_targets.add(int(raw_id))
        for channel in before_snapshot.get("channels", []):
            if isinstance(channel, dict) and channel.get("parent_id") is not None:
                if int(channel["parent_id"]) in category_targets:
                    remember("CHANNEL", channel.get("id"), "CATEGORY_CHILD")
        for (resource_type, resource_id), reason in dependencies.items():
            await session.execute(
                text(
                    "INSERT INTO plan_resource_dependencies "
                    "(guild_id,plan_id,resource_type,discord_resource_id,reason) VALUES "
                    "(:guild_id,:plan_id,:resource_type,:resource_id,:reason) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "reason": reason,
                },
            )

    @staticmethod
    async def _assert_job_fence(
        session: AsyncSession,
        *,
        guild_id: int,
        job_id: UUID,
        lease_owner: str,
        lease_token: UUID,
        lease_generation: int,
    ) -> None:
        current = await session.scalar(
            text(
                "SELECT job_id FROM discord_io_jobs WHERE guild_id=:guild_id AND job_id=:job_id "
                "AND status='LEASED' AND lease_owner=:owner AND lease_token=:token "
                "AND lease_generation=:generation AND leased_until > now()"
            ),
            {
                "guild_id": guild_id,
                "job_id": job_id,
                "owner": lease_owner,
                "token": lease_token,
                "generation": lease_generation,
            },
        )
        if current is None:
            raise PlanFencingError("job lease fencing token is expired or replaced")

    @staticmethod
    async def _resolve_payload_symbols(
        session: AsyncSession, guild_id: int, plan_id: UUID, payload: dict[str, Any]
    ) -> dict[str, Any]:
        symbols = {
            value
            for key, value in payload.items()
            if key.endswith("_symbol") and isinstance(value, str)
        }
        bindings: dict[str, int] = {}
        if symbols:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT symbol,discord_id FROM plan_symbol_bindings WHERE "
                            "guild_id=:guild_id AND plan_id=:plan_id AND symbol=ANY(:symbols) "
                            "AND status='BOUND'"
                        ),
                        {"guild_id": guild_id, "plan_id": plan_id, "symbols": list(symbols)},
                    )
                )
                .mappings()
                .all()
            )
            bindings = {str(row["symbol"]): int(row["discord_id"]) for row in rows}
            if set(bindings) != symbols:
                raise PlanConflict("operation consumes an unresolved symbol")
        resolved = dict(payload)
        for key in list(resolved):
            if not key.endswith("_symbol"):
                continue
            symbol = str(resolved.pop(key))
            resolved[f"{key.removesuffix('_symbol')}_id"] = bindings[symbol]
        return resolved

    @staticmethod
    def _result_resource_id(operation: Any, result_payload: dict[str, Any]) -> int | None:
        operation_type = OperationType(str(operation["operation_type"]))
        value = result_payload.get("id") or operation["resource_discord_id"]
        if operation_type in {OperationType.UPSERT_OVERWRITE, OperationType.DELETE_OVERWRITE}:
            value = result_payload.get("channel_id") or value
        return int(value) if value is not None else None

    @staticmethod
    def _persisted_result_resource_id(operation: Any, resource_id: int | None) -> int | None:
        operation_type = OperationType(str(operation["operation_type"]))
        if operation_type not in {OperationType.CREATE_ROLE, OperationType.CREATE_CHANNEL}:
            return None
        return resource_id

    @staticmethod
    async def _write_through(
        session: AsyncSession,
        guild_id: int,
        operation: Any,
        payload: dict[str, Any],
        resource_id: int | None,
        now: datetime,
    ) -> None:
        operation_type = OperationType(str(operation["operation_type"]))
        if operation_type in {OperationType.CREATE_ROLE, OperationType.UPDATE_ROLE}:
            if resource_id is None:
                raise PlanConflict("role write-through requires resource ID")
            await session.execute(
                text(
                    "INSERT INTO discord_roles_cache "
                    "(guild_id,role_id,name,position,permissions_bits,managed,color,hoist,"
                    "mentionable,raw_json,last_mutation_confirmed_at,state_version,"
                    "cache_updated_at) "
                    "VALUES (:guild_id,:id,:name,:position,:permissions,false,:color,:hoist,"
                    ":mentionable,CAST(:raw AS jsonb),:now,1,:now) ON CONFLICT "
                    "(guild_id,role_id) DO UPDATE SET name=EXCLUDED.name,"
                    "position=EXCLUDED.position,"
                    "permissions_bits=EXCLUDED.permissions_bits,color=EXCLUDED.color,"
                    "hoist=EXCLUDED.hoist,mentionable=EXCLUDED.mentionable,raw_json=EXCLUDED.raw_json,"
                    "last_mutation_confirmed_at=EXCLUDED.last_mutation_confirmed_at,"
                    "deleted_confirmed_at=NULL,state_version=discord_roles_cache.state_version+1,"
                    "cache_updated_at=EXCLUDED.cache_updated_at"
                ),
                {
                    "guild_id": guild_id,
                    "id": resource_id,
                    "name": str(payload.get("name", "new role")),
                    "position": int(payload.get("position", 1)),
                    "permissions": int(payload.get("permissions", 0)),
                    "color": int(payload.get("color", 0)),
                    "hoist": bool(payload.get("hoist", False)),
                    "mentionable": bool(payload.get("mentionable", False)),
                    "raw": json.dumps(payload, separators=(",", ":")),
                    "now": now,
                },
            )
        elif operation_type is OperationType.DELETE_ROLE and resource_id is not None:
            await session.execute(
                text(
                    "UPDATE discord_roles_cache SET deleted_confirmed_at=:now,"
                    "last_mutation_confirmed_at=:now,state_version=state_version+1,"
                    "cache_updated_at=:now WHERE guild_id=:guild_id AND role_id=:id"
                ),
                {"now": now, "guild_id": guild_id, "id": resource_id},
            )
        elif operation_type in {OperationType.CREATE_CHANNEL, OperationType.UPDATE_CHANNEL}:
            if resource_id is None:
                raise PlanConflict("channel write-through requires resource ID")
            await session.execute(
                text(
                    "INSERT INTO discord_channels_cache "
                    "(guild_id,channel_id,type,name,topic,parent_id,position,nsfw,flags,"
                    "last_full_payload,observability_state,is_obfuscated,freshness_state,"
                    "last_full_observed_at,last_mutation_confirmed_at,state_version,"
                    "cache_updated_at) "
                    "VALUES (:guild_id,:id,:type,:name,:topic,:parent_id,:position,:nsfw,:flags,"
                    "CAST(:raw AS jsonb),'VISIBLE',false,'FRESH',:now,:now,1,:now) ON CONFLICT "
                    "(guild_id,channel_id) DO UPDATE SET type=EXCLUDED.type,name=EXCLUDED.name,"
                    "topic=EXCLUDED.topic,parent_id=EXCLUDED.parent_id,position=EXCLUDED.position,"
                    "nsfw=EXCLUDED.nsfw,flags=EXCLUDED.flags,last_full_payload=EXCLUDED.last_full_payload,"
                    "observability_state='VISIBLE',is_obfuscated=false,freshness_state='FRESH',"
                    "last_full_observed_at=EXCLUDED.last_full_observed_at,"
                    "last_mutation_confirmed_at=EXCLUDED.last_mutation_confirmed_at,"
                    "deleted_confirmed_at=NULL,state_version=discord_channels_cache.state_version+1,"
                    "cache_updated_at=EXCLUDED.cache_updated_at"
                ),
                {
                    "guild_id": guild_id,
                    "id": resource_id,
                    "type": int(payload.get("type", 0)),
                    "name": payload.get("name"),
                    "topic": payload.get("topic"),
                    "parent_id": payload.get("parent_id"),
                    "position": int(payload.get("position", 0)),
                    "nsfw": payload.get("nsfw"),
                    "flags": int(payload.get("flags", 0)),
                    "raw": json.dumps(payload, separators=(",", ":")),
                    "now": now,
                },
            )
            overwrites = payload.get("permission_overwrites")
            if isinstance(overwrites, list):
                await session.execute(
                    text(
                        "DELETE FROM channel_overwrites_cache WHERE guild_id=:guild_id "
                        "AND channel_id=:channel_id"
                    ),
                    {"guild_id": guild_id, "channel_id": resource_id},
                )
                for overwrite in overwrites:
                    if not isinstance(overwrite, dict):
                        continue
                    await PlanningRepository._upsert_overwrite(
                        session, guild_id, resource_id, overwrite, now
                    )
        elif operation_type is OperationType.DELETE_CHANNEL and resource_id is not None:
            await session.execute(
                text(
                    "UPDATE discord_channels_cache SET observability_state='DELETED_CONFIRMED',"
                    "deleted_confirmed_at=:now,last_mutation_confirmed_at=:now,"
                    "freshness_state='FRESH',state_version=state_version+1,cache_updated_at=:now "
                    "WHERE guild_id=:guild_id AND channel_id=:id"
                ),
                {"now": now, "guild_id": guild_id, "id": resource_id},
            )
        elif operation_type in {OperationType.UPSERT_OVERWRITE, OperationType.DELETE_OVERWRITE}:
            channel_id = payload.get("channel_id")
            target_id = payload.get("subject_id") or payload.get("target_id")
            if channel_id is None or target_id is None:
                raise PlanConflict("overwrite write-through requires channel and target IDs")
            if operation_type is OperationType.DELETE_OVERWRITE:
                await session.execute(
                    text(
                        "DELETE FROM channel_overwrites_cache WHERE guild_id=:guild_id "
                        "AND channel_id=:channel_id AND target_id=:target_id "
                        "AND target_type=:target_type"
                    ),
                    {
                        "guild_id": guild_id,
                        "channel_id": int(channel_id),
                        "target_id": int(target_id),
                        "target_type": int(payload.get("target_type", 0)),
                    },
                )
            else:
                await PlanningRepository._upsert_overwrite(
                    session,
                    guild_id,
                    int(channel_id),
                    {
                        "id": int(target_id),
                        "type": int(payload.get("target_type", 0)),
                        "allow": int(payload.get("allow", 0)),
                        "deny": int(payload.get("deny", 0)),
                    },
                    now,
                )

    @staticmethod
    async def _upsert_overwrite(
        session: AsyncSession,
        guild_id: int,
        channel_id: int,
        overwrite: dict[str, Any],
        now: datetime,
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO channel_overwrites_cache "
                "(guild_id,channel_id,target_id,target_type,allow_bits,deny_bits,"
                "last_full_observed_at,cache_updated_at) VALUES "
                "(:guild_id,:channel_id,:target_id,:target_type,:allow,:deny,:now,:now) "
                "ON CONFLICT (guild_id,channel_id,target_id,target_type) DO UPDATE SET "
                "allow_bits=EXCLUDED.allow_bits,deny_bits=EXCLUDED.deny_bits,"
                "last_full_observed_at=EXCLUDED.last_full_observed_at,"
                "cache_updated_at=EXCLUDED.cache_updated_at"
            ),
            {
                "guild_id": guild_id,
                "channel_id": channel_id,
                "target_id": int(overwrite["id"]),
                "target_type": int(overwrite.get("type", 0)),
                "allow": int(overwrite.get("allow", 0)),
                "deny": int(overwrite.get("deny", 0)),
                "now": now,
            },
        )

    @staticmethod
    async def _register_expected_gateway(
        session: AsyncSession,
        guild_id: int,
        plan_id: UUID,
        operation: Any,
        resource_id: int | None,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        operation_type = OperationType(str(operation["operation_type"]))
        expected_items: list[tuple[int, dict[str, Any]]] = []
        if operation_type in {
            OperationType.REORDER_ROLES,
            OperationType.MOVE_OR_REORDER_CHANNELS,
        }:
            operation_payload = dict(operation["desired_payload"])
            desired_items = operation_payload.get("items", [])
            if operation_type is OperationType.REORDER_ROLES:
                desired_items = operation_payload.get("expected_position_segment", desired_items)
            desired_ids = {
                int(item["id"])
                for item in desired_items
                if isinstance(item, dict) and item.get("id") is not None
            }
            for item in payload.get("items", []):
                if not isinstance(item, dict):
                    continue
                item_id = item.get("id") or item.get("role_id") or item.get("channel_id")
                if item_id is not None and int(item_id) in desired_ids:
                    expected_items.append((int(item_id), dict(item)))
        elif operation_type in {
            OperationType.UPSERT_OVERWRITE,
            OperationType.DELETE_OVERWRITE,
        }:
            expected_overwrite = {**dict(operation["desired_payload"]), **payload}
            channel_id = expected_overwrite.get("channel_id") or resource_id
            target_id = expected_overwrite.get("target_id") or expected_overwrite.get("subject_id")
            if channel_id is not None and target_id is not None:
                overwrite = {
                    "target_id": int(target_id),
                    "target_type": int(expected_overwrite.get("target_type", 0)),
                    "present": operation_type is OperationType.UPSERT_OVERWRITE,
                }
                if operation_type is OperationType.UPSERT_OVERWRITE:
                    overwrite.update(
                        {
                            "allow": int(expected_overwrite.get("allow", 0)),
                            "deny": int(expected_overwrite.get("deny", 0)),
                        }
                    )
                current_rows = (
                    (
                        await session.execute(
                            text(
                                "SELECT target_id,target_type,allow_bits,deny_bits FROM "
                                "channel_overwrites_cache WHERE guild_id=:guild_id AND "
                                "channel_id=:channel_id ORDER BY target_type,target_id"
                            ),
                            {"guild_id": guild_id, "channel_id": int(channel_id)},
                        )
                    )
                    .mappings()
                    .all()
                )
                full_overwrites = [
                    {
                        "id": int(row["target_id"]),
                        "type": int(row["target_type"]),
                        "allow": int(row["allow_bits"]),
                        "deny": int(row["deny_bits"]),
                    }
                    for row in current_rows
                    if not (
                        int(row["target_id"]) == int(target_id)
                        and int(row["target_type"]) == int(expected_overwrite.get("target_type", 0))
                    )
                ]
                if operation_type is OperationType.UPSERT_OVERWRITE:
                    full_overwrites.append(
                        {
                            "id": int(target_id),
                            "type": int(expected_overwrite.get("target_type", 0)),
                            "allow": int(expected_overwrite.get("allow", 0)),
                            "deny": int(expected_overwrite.get("deny", 0)),
                        }
                    )
                full_overwrites.sort(key=lambda item: (item["type"], item["id"]))
                expected_items.append(
                    (
                        int(channel_id),
                        {
                            "channel_id": int(channel_id),
                            "overwrite": overwrite,
                            "full_overwrites": full_overwrites,
                        },
                    )
                )
        elif resource_id is not None:
            expected_items.append((resource_id, payload))
        for event_type in operation["expected_gateway_events"]:
            for expected_resource_id, expected_payload in expected_items:
                await session.execute(
                    text(
                        "INSERT INTO plan_expected_mutations "
                        "(id,guild_id,plan_id,operation_id,event_type,resource_type,"
                        "discord_resource_id,expected_payload,expected_fingerprint,expires_at) "
                        "VALUES (:id,:guild_id,:plan_id,:operation_id,:event_type,:resource_type,"
                        ":resource_id,CAST(:payload AS jsonb),:fingerprint,:expires) ON CONFLICT "
                        "(guild_id,plan_id,operation_id,event_type,discord_resource_id) "
                        "DO NOTHING"
                    ),
                    {
                        "id": uuid4(),
                        "guild_id": guild_id,
                        "plan_id": plan_id,
                        "operation_id": operation["id"],
                        "event_type": str(event_type),
                        "resource_type": str(operation["resource_type"]),
                        "resource_id": expected_resource_id,
                        "payload": json.dumps(expected_payload, separators=(",", ":")),
                        "fingerprint": canonical_hash(expected_payload),
                        "expires": now + timedelta(minutes=5),
                    },
                )

    @staticmethod
    async def _append_progress(
        session: AsyncSession,
        *,
        guild_id: int,
        plan_id: UUID,
        operation_id: UUID | None,
        plan_status: PlanState,
        operation_status: OperationState | None,
        message_key: str,
        error_code: str | None,
        correlation_id: UUID,
    ) -> None:
        counts = (
            (
                await session.execute(
                    text(
                        "SELECT count(*) AS total,count(*) FILTER (WHERE status='SUCCEEDED') "
                        "AS completed FROM plan_operations WHERE guild_id=:guild_id "
                        "AND plan_id=:plan_id"
                    ),
                    {"guild_id": guild_id, "plan_id": plan_id},
                )
            )
            .mappings()
            .one()
        )
        allocated = await session.scalar(
            text(
                "UPDATE plans SET progress_sequence=progress_sequence+1 "
                "WHERE guild_id=:guild_id AND id=:plan_id RETURNING progress_sequence"
            ),
            {"guild_id": guild_id, "plan_id": plan_id},
        )
        if allocated is None:
            raise PlanNotFound("plan not found while allocating progress sequence")
        sequence = int(allocated)
        event_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO plan_progress_events "
                "(id,guild_id,plan_id,operation_id,sequence,plan_status,operation_status,"
                "completed_operations,total_operations,message_key,error_code,correlation_id) "
                "VALUES (:id,:guild_id,:plan_id,:operation_id,:sequence,:plan_status,"
                ":operation_status,:completed,:total,:message_key,:error_code,:correlation_id)"
            ),
            {
                "id": event_id,
                "guild_id": guild_id,
                "plan_id": plan_id,
                "operation_id": operation_id,
                "sequence": sequence,
                "plan_status": plan_status.value,
                "operation_status": operation_status.value if operation_status else None,
                "completed": int(counts["completed"]),
                "total": int(counts["total"]),
                "message_key": message_key,
                "error_code": error_code,
                "correlation_id": correlation_id,
            },
        )
        await PlanningRepository._append_outbox(
            session,
            guild_id=guild_id,
            topic="plan.progress.updated",
            payload={
                "type": "plan.progress.updated",
                "guild_id": str(guild_id),
                "plan_id": str(plan_id),
                "operation_id": str(operation_id) if operation_id else None,
                "plan_status": plan_status.value,
                "operation_status": operation_status.value if operation_status else None,
                "sequence": sequence,
                "completed_operations": int(counts["completed"]),
                "total_operations": int(counts["total"]),
                "message_key": message_key,
                "error_code": error_code,
                "correlation_id": str(correlation_id),
            },
            correlation_id=correlation_id,
        )

    @staticmethod
    async def _append_audit(
        session: AsyncSession,
        *,
        guild_id: int,
        actor_user_id: int | None,
        event_type: str,
        target_type: str,
        target_id: str,
        plan_id: UUID,
        operation_id: UUID | None,
        correlation_id: UUID,
        result_state: str,
        data: dict[str, Any],
    ) -> None:
        safe_data = {
            **data,
            "plan_id": str(plan_id),
            "operation_id": str(operation_id) if operation_id else None,
        }
        await session.execute(
            text(
                "INSERT INTO internal_audit_events "
                "(id,guild_id,actor_user_id,source,event_type,target_type,target_id,"
                "correlation_id,result_state,data_json,occurred_at) VALUES "
                "(:id,:guild_id,:actor,'DASHBOARD',:event_type,:target_type,:target_id,"
                ":correlation_id,:result,CAST(:data AS jsonb),:now)"
            ),
            {
                "id": uuid4(),
                "guild_id": guild_id,
                "actor": actor_user_id,
                "event_type": event_type,
                "target_type": target_type,
                "target_id": target_id,
                "correlation_id": correlation_id,
                "result": result_state,
                "data": json.dumps(safe_data, separators=(",", ":")),
                "now": datetime.now(UTC),
            },
        )

    @staticmethod
    async def _append_outbox(
        session: AsyncSession,
        *,
        guild_id: int,
        topic: str,
        payload: dict[str, Any],
        correlation_id: UUID,
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO discord_outbox "
                "(event_id,guild_id,topic,payload,correlation_id,status) VALUES "
                "(:id,:guild_id,:topic,CAST(:payload AS jsonb),:correlation_id,'PENDING')"
            ),
            {
                "id": uuid4(),
                "guild_id": guild_id,
                "topic": topic,
                "payload": json.dumps(payload, separators=(",", ":")),
                "correlation_id": correlation_id,
            },
        )
