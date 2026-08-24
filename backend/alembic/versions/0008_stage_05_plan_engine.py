"""Add STAGE 05 desired-state plans, DAG, attempts and progress.

Revision ID: 0008_stage_05
Revises: 0007_stage_04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_stage_05"
down_revision: str | None = "0007_stage_04"
branch_labels: str | None = None
depends_on: str | None = None

PLAN_STATES = (
    "DRAFT",
    "VALIDATED",
    "STALE",
    "CONFIRMED",
    "APPLYING",
    "PARTIALLY_APPLIED",
    "SUCCEEDED",
    "FAILED",
    "VERIFICATION_FAILED",
    "CANCEL_REQUESTED",
    "CANCELLED",
    "INTERVENTION_REQUIRED",
)
OPERATION_STATES = (
    "PENDING",
    "IN_FLIGHT",
    "SUCCEEDED",
    "FAILED",
    "UNKNOWN_OUTCOME",
    "INTERVENTION_REQUIRED",
    "CANCELLED",
)
ATTEMPT_STATES = ("PREPARED", "IN_FLIGHT", "SUCCEEDED", "FAILED", "UNKNOWN")
OPERATION_TYPES = (
    "CREATE_ROLE",
    "UPDATE_ROLE",
    "DELETE_ROLE",
    "REORDER_ROLES",
    "CREATE_CHANNEL",
    "UPDATE_CHANNEL",
    "MOVE_OR_REORDER_CHANNELS",
    "DELETE_CHANNEL",
    "UPSERT_OVERWRITE",
    "DELETE_OVERWRITE",
)


def _values(column: str, values: tuple[str, ...], name: str) -> sa.CheckConstraint:
    allowed = ",".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=name)


def _guild_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (guild_id = app.current_guild_id()) "
        "WITH CHECK (guild_id = app.current_guild_id())"
    )


def _installation_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["guild_id"],
        ["guild_installations.guild_id"],
        name=name,
        ondelete="CASCADE",
    )


def upgrade() -> None:
    op.create_table(
        "plan_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_type", sa.String(24), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("structure_version", sa.String(256), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        _installation_fk("fk_plan_snapshots_installation"),
        sa.CheckConstraint(
            "snapshot_type IN ('BEFORE','VERIFICATION','RECOVERY')",
            name="ck_plan_snapshots_type",
        ),
        sa.CheckConstraint("length(snapshot_hash)=64", name="ck_plan_snapshots_hash"),
        sa.PrimaryKeyConstraint("id", name="pk_plan_snapshots"),
        sa.UniqueConstraint("guild_id", "id", name="uq_plan_snapshots_guild_id"),
    )
    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(32), server_default="DRAFT", nullable=False),
        sa.Column("desired_graph_schema_version", sa.String(64), nullable=False),
        sa.Column("compiler_version", sa.String(64), nullable=False),
        sa.Column("desired_graph", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("desired_graph_hash", sa.String(64), nullable=False),
        sa.Column("before_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("base_structure_version", sa.String(256), nullable=False),
        sa.Column("base_structure_hash", sa.String(64), nullable=False),
        sa.Column("capability_version", sa.String(128), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("risk_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("impact_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confirmation_required", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("state_version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applying_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("drift_detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("verification_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _installation_fk("fk_plans_installation"),
        sa.ForeignKeyConstraint(
            ["guild_id", "before_snapshot_id"],
            ["plan_snapshots.guild_id", "plan_snapshots.id"],
            name="fk_plans_before_snapshot",
            ondelete="RESTRICT",
        ),
        _values("status", PLAN_STATES, "ck_plans_status"),
        sa.CheckConstraint("actor_user_id > 0", name="ck_plans_actor"),
        sa.CheckConstraint("state_version > 0", name="ck_plans_state_version"),
        sa.CheckConstraint(
            "risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="ck_plans_risk"
        ),
        sa.CheckConstraint(
            "length(desired_graph_hash)=64 AND length(base_structure_hash)=64 "
            "AND length(plan_hash)=64",
            name="ck_plans_hashes",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plans"),
        sa.UniqueConstraint("guild_id", "id", name="uq_plans_guild_id"),
        sa.UniqueConstraint("guild_id", "idempotency_key", name="uq_plans_idempotency"),
    )
    op.create_index(
        "uq_plans_one_applying_per_guild",
        "plans",
        ["guild_id"],
        unique=True,
        postgresql_where=sa.text("status='APPLYING'"),
    )
    op.create_index("ix_plans_guild_status_updated", "plans", ["guild_id", "status", "updated_at"])

    op.create_table(
        "plan_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("operation_type", sa.String(48), nullable=False),
        sa.Column("execution_target", sa.String(16), nullable=False),
        sa.Column("resource_type", sa.String(24), nullable=False),
        sa.Column("resource_ref", sa.String(256), nullable=False),
        sa.Column("resource_discord_id", sa.BigInteger(), nullable=True),
        sa.Column("produces_symbol", sa.String(256), nullable=True),
        sa.Column("consumes_symbols", postgresql.ARRAY(sa.String(256)), nullable=False),
        sa.Column("desired_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("before_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("required_capabilities", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("compensation_class", sa.String(40), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("verification_strategy", sa.String(64), nullable=False),
        sa.Column("recovery_strategy", sa.String(64), nullable=False),
        sa.Column("expected_gateway_events", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("immutable_hash", sa.String(64), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), server_default="PENDING", nullable=False),
        sa.Column("state_version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_fingerprint", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "plan_id"],
            ["plans.guild_id", "plans.id"],
            name="fk_plan_operations_plan",
            ondelete="CASCADE",
        ),
        _values("operation_type", OPERATION_TYPES, "ck_plan_operations_type"),
        _values("status", OPERATION_STATES, "ck_plan_operations_status"),
        sa.CheckConstraint("execution_target='DISCORD'", name="ck_plan_operations_target"),
        sa.CheckConstraint(
            "resource_type IN ('ROLE','CATEGORY','CHANNEL','OVERWRITE')",
            name="ck_plan_operations_resource_type",
        ),
        sa.CheckConstraint(
            "compensation_class IN ('REVERSIBLE','RECREATABLE_NOT_RESTORABLE','NON_COMPENSABLE')",
            name="ck_plan_operations_compensation",
        ),
        sa.CheckConstraint(
            "risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_plan_operations_risk",
        ),
        sa.CheckConstraint(
            "display_order >= 0 AND state_version > 0 AND attempt_count >= 0",
            name="ck_plan_operations_counters",
        ),
        sa.CheckConstraint("length(immutable_hash)=64", name="ck_plan_operations_hash"),
        sa.PrimaryKeyConstraint("id", name="pk_plan_operations"),
        sa.UniqueConstraint("guild_id", "plan_id", "id", name="uq_plan_operations_scope"),
        sa.UniqueConstraint(
            "guild_id", "plan_id", "display_order", name="uq_plan_operations_display_order"
        ),
    )
    op.create_index(
        "ix_plan_operations_ready",
        "plan_operations",
        ["guild_id", "plan_id", "status", "display_order"],
    )

    op.create_table(
        "plan_operation_dependencies",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("predecessor_operation_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id", "plan_id", "operation_id"],
            ["plan_operations.guild_id", "plan_operations.plan_id", "plan_operations.id"],
            name="fk_plan_dependencies_operation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "plan_id", "predecessor_operation_id"],
            ["plan_operations.guild_id", "plan_operations.plan_id", "plan_operations.id"],
            name="fk_plan_dependencies_predecessor",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "operation_id <> predecessor_operation_id", name="ck_plan_dependencies_not_self"
        ),
        sa.PrimaryKeyConstraint(
            "guild_id",
            "plan_id",
            "operation_id",
            "predecessor_operation_id",
            name="pk_plan_operation_dependencies",
        ),
    )

    op.create_table(
        "plan_symbol_bindings",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(256), nullable=False),
        sa.Column("resource_type", sa.String(24), nullable=False),
        sa.Column("producer_operation_id", sa.Uuid(), nullable=False),
        sa.Column("discord_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(16), server_default="UNRESOLVED", nullable=False),
        sa.Column("binding_fingerprint", sa.String(64), nullable=True),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("binding_version", sa.BigInteger(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id", "plan_id", "producer_operation_id"],
            ["plan_operations.guild_id", "plan_operations.plan_id", "plan_operations.id"],
            name="fk_plan_symbols_producer",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("status IN ('UNRESOLVED','BOUND')", name="ck_plan_symbols_status"),
        sa.CheckConstraint(
            "(status='UNRESOLVED' AND discord_id IS NULL AND bound_at IS NULL) OR "
            "(status='BOUND' AND discord_id IS NOT NULL AND bound_at IS NOT NULL)",
            name="ck_plan_symbols_binding",
        ),
        sa.CheckConstraint("binding_version > 0", name="ck_plan_symbols_version"),
        sa.PrimaryKeyConstraint("guild_id", "plan_id", "symbol", name="pk_plan_symbol_bindings"),
    )
    op.create_index(
        "uq_plan_symbol_discord_binding",
        "plan_symbol_bindings",
        ["guild_id", "plan_id", "resource_type", "discord_id"],
        unique=True,
        postgresql_where=sa.text("discord_id IS NOT NULL"),
    )

    op.create_table(
        "operation_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("in_flight_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("result_fingerprint", sa.String(64), nullable=True),
        sa.Column("discord_status", sa.Integer(), nullable=True),
        sa.Column("discord_error_code", sa.Integer(), nullable=True),
        sa.Column("error_classification", sa.String(64), nullable=True),
        sa.Column("lease_owner", sa.String(128), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=False),
        sa.Column("lease_generation", sa.BigInteger(), nullable=False),
        sa.Column("outcome_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id", "plan_id", "operation_id"],
            ["plan_operations.guild_id", "plan_operations.plan_id", "plan_operations.id"],
            name="fk_operation_attempts_operation",
            ondelete="CASCADE",
        ),
        _values("status", ATTEMPT_STATES, "ck_operation_attempts_status"),
        sa.CheckConstraint(
            "attempt_number > 0 AND lease_generation > 0", name="ck_operation_attempts_counters"
        ),
        sa.CheckConstraint(
            "length(request_fingerprint)=64", name="ck_operation_attempts_request_hash"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_operation_attempts"),
        sa.UniqueConstraint(
            "guild_id",
            "plan_id",
            "operation_id",
            "attempt_number",
            name="uq_operation_attempts_number",
        ),
        sa.UniqueConstraint("guild_id", "plan_id", "id", name="uq_operation_attempts_scope"),
    )

    op.create_table(
        "plan_confirmations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["guild_id", "plan_id"],
            ["plans.guild_id", "plans.id"],
            name="fk_plan_confirmations_plan",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("actor_user_id > 0", name="ck_plan_confirmations_actor"),
        sa.CheckConstraint("expires_at > confirmed_at", name="ck_plan_confirmations_expiry"),
        sa.CheckConstraint("length(plan_hash)=64", name="ck_plan_confirmations_hash"),
        sa.CheckConstraint(
            "risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_plan_confirmations_risk",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_confirmations"),
        sa.UniqueConstraint(
            "guild_id",
            "plan_id",
            "actor_user_id",
            "idempotency_key",
            name="uq_plan_confirmations_idempotency",
        ),
    )
    op.create_index(
        "ix_plan_confirmations_current",
        "plan_confirmations",
        ["guild_id", "plan_id", "expires_at"],
    )

    op.create_table(
        "plan_progress_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("plan_status", sa.String(32), nullable=False),
        sa.Column("operation_status", sa.String(32), nullable=True),
        sa.Column("completed_operations", sa.Integer(), nullable=False),
        sa.Column("total_operations", sa.Integer(), nullable=False),
        sa.Column("message_key", sa.String(160), nullable=False),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "plan_id"],
            ["plans.guild_id", "plans.id"],
            name="fk_plan_progress_plan",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "plan_id", "operation_id"],
            ["plan_operations.guild_id", "plan_operations.plan_id", "plan_operations.id"],
            name="fk_plan_progress_operation",
            ondelete="CASCADE",
        ),
        _values("plan_status", PLAN_STATES, "ck_plan_progress_plan_status"),
        sa.CheckConstraint(
            "operation_status IS NULL OR operation_status IN "
            "('PENDING','IN_FLIGHT','SUCCEEDED','FAILED','UNKNOWN_OUTCOME',"
            "'INTERVENTION_REQUIRED','CANCELLED')",
            name="ck_plan_progress_operation_status",
        ),
        sa.CheckConstraint(
            "sequence > 0 AND completed_operations >= 0 AND total_operations >= 0 "
            "AND completed_operations <= total_operations",
            name="ck_plan_progress_counts",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_progress_events"),
        sa.UniqueConstraint("guild_id", "plan_id", "sequence", name="uq_plan_progress_sequence"),
    )

    op.create_table(
        "plan_expected_mutations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(24), nullable=False),
        sa.Column("discord_resource_id", sa.BigInteger(), nullable=False),
        sa.Column("expected_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="EXPECTED", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["guild_id", "plan_id", "operation_id"],
            ["plan_operations.guild_id", "plan_operations.plan_id", "plan_operations.id"],
            name="fk_plan_expected_mutations_operation",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('EXPECTED','OBSERVED','EXPIRED')", name="ck_plan_expected_status"
        ),
        sa.CheckConstraint("length(expected_fingerprint)=64", name="ck_plan_expected_hash"),
        sa.PrimaryKeyConstraint("id", name="pk_plan_expected_mutations"),
        sa.UniqueConstraint(
            "guild_id", "plan_id", "operation_id", "event_type", name="uq_plan_expected_event"
        ),
    )
    op.create_index(
        "ix_plan_expected_match",
        "plan_expected_mutations",
        ["guild_id", "event_type", "discord_resource_id", "status", "expires_at"],
    )

    tables = (
        "plan_snapshots",
        "plans",
        "plan_operations",
        "plan_operation_dependencies",
        "plan_symbol_bindings",
        "operation_attempts",
        "plan_confirmations",
        "plan_progress_events",
        "plan_expected_mutations",
    )
    for table in tables:
        _guild_rls(table)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON " + ", ".join(tables) + " TO did_app")

    op.execute(
        """
        CREATE FUNCTION app.guard_plan_immutable() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
        BEGIN
          IF OLD.status <> 'DRAFT' AND (
            NEW.guild_id IS DISTINCT FROM OLD.guild_id OR
            NEW.actor_user_id IS DISTINCT FROM OLD.actor_user_id OR
            NEW.desired_graph_schema_version IS DISTINCT FROM OLD.desired_graph_schema_version OR
            NEW.compiler_version IS DISTINCT FROM OLD.compiler_version OR
            NEW.desired_graph IS DISTINCT FROM OLD.desired_graph OR
            NEW.desired_graph_hash IS DISTINCT FROM OLD.desired_graph_hash OR
            NEW.before_snapshot_id IS DISTINCT FROM OLD.before_snapshot_id OR
            NEW.base_structure_version IS DISTINCT FROM OLD.base_structure_version OR
            NEW.base_structure_hash IS DISTINCT FROM OLD.base_structure_hash OR
            NEW.capability_version IS DISTINCT FROM OLD.capability_version OR
            NEW.plan_hash IS DISTINCT FROM OLD.plan_hash OR
            NEW.risk_level IS DISTINCT FROM OLD.risk_level OR
            NEW.risk_summary IS DISTINCT FROM OLD.risk_summary OR
            NEW.impact_summary IS DISTINCT FROM OLD.impact_summary OR
            NEW.confirmation_required IS DISTINCT FROM OLD.confirmation_required OR
            NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
          ) THEN RAISE EXCEPTION 'validated plan is immutable' USING ERRCODE='23514'; END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_plans_immutable BEFORE UPDATE ON plans "
        "FOR EACH ROW EXECUTE FUNCTION app.guard_plan_immutable()"
    )
    op.execute(
        """
        CREATE FUNCTION app.guard_plan_child_immutable() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
        DECLARE v_status text; v_plan uuid; v_guild bigint;
        BEGIN
          v_plan := COALESCE(NEW.plan_id, OLD.plan_id);
          v_guild := COALESCE(NEW.guild_id, OLD.guild_id);
          SELECT status INTO v_status FROM plans WHERE id=v_plan AND guild_id=v_guild;
          IF v_status <> 'DRAFT' THEN RAISE EXCEPTION 'validated plan graph is immutable' USING ERRCODE='23514'; END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$
        """
    )
    for table in ("plan_operation_dependencies",):
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION app.guard_plan_child_immutable()"
        )
    op.execute(
        """
        CREATE FUNCTION app.guard_operation_immutable() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
        DECLARE v_status text;
        BEGIN
          SELECT status INTO v_status FROM plans WHERE id=OLD.plan_id AND guild_id=OLD.guild_id;
          IF v_status <> 'DRAFT' AND (
            NEW.guild_id IS DISTINCT FROM OLD.guild_id OR NEW.plan_id IS DISTINCT FROM OLD.plan_id OR
            NEW.operation_type IS DISTINCT FROM OLD.operation_type OR
            NEW.execution_target IS DISTINCT FROM OLD.execution_target OR
            NEW.resource_type IS DISTINCT FROM OLD.resource_type OR
            NEW.resource_ref IS DISTINCT FROM OLD.resource_ref OR
            (OLD.produces_symbol IS NULL AND
             NEW.resource_discord_id IS DISTINCT FROM OLD.resource_discord_id) OR
            NEW.produces_symbol IS DISTINCT FROM OLD.produces_symbol OR
            NEW.consumes_symbols IS DISTINCT FROM OLD.consumes_symbols OR
            NEW.desired_payload IS DISTINCT FROM OLD.desired_payload OR
            NEW.before_payload IS DISTINCT FROM OLD.before_payload OR
            NEW.required_capabilities IS DISTINCT FROM OLD.required_capabilities OR
            NEW.compensation_class IS DISTINCT FROM OLD.compensation_class OR
            NEW.risk_level IS DISTINCT FROM OLD.risk_level OR
            NEW.verification_strategy IS DISTINCT FROM OLD.verification_strategy OR
            NEW.recovery_strategy IS DISTINCT FROM OLD.recovery_strategy OR
            NEW.expected_gateway_events IS DISTINCT FROM OLD.expected_gateway_events OR
            NEW.immutable_hash IS DISTINCT FROM OLD.immutable_hash OR
            NEW.display_order IS DISTINCT FROM OLD.display_order
          ) THEN RAISE EXCEPTION 'validated operation is immutable' USING ERRCODE='23514'; END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_plan_operations_immutable BEFORE UPDATE ON plan_operations "
        "FOR EACH ROW EXECUTE FUNCTION app.guard_operation_immutable()"
    )
    op.execute(
        """
        CREATE FUNCTION app.guard_symbol_immutable() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
        DECLARE v_status text;
        BEGIN
          SELECT status INTO v_status FROM plans WHERE id=OLD.plan_id AND guild_id=OLD.guild_id;
          IF v_status <> 'DRAFT' AND (
            NEW.guild_id IS DISTINCT FROM OLD.guild_id OR
            NEW.plan_id IS DISTINCT FROM OLD.plan_id OR
            NEW.symbol IS DISTINCT FROM OLD.symbol OR
            NEW.resource_type IS DISTINCT FROM OLD.resource_type OR
            NEW.producer_operation_id IS DISTINCT FROM OLD.producer_operation_id
          ) THEN RAISE EXCEPTION 'validated symbol definition is immutable' USING ERRCODE='23514'; END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_plan_symbols_immutable BEFORE UPDATE ON plan_symbol_bindings "
        "FOR EACH ROW EXECUTE FUNCTION app.guard_symbol_immutable()"
    )
    op.execute(
        """
        CREATE FUNCTION app.guard_symbol_rebinding() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
        BEGIN
          IF OLD.discord_id IS NOT NULL AND NEW.discord_id IS DISTINCT FROM OLD.discord_id THEN
            RAISE EXCEPTION 'symbol binding cannot be changed' USING ERRCODE='23505';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_plan_symbols_no_rebind BEFORE UPDATE ON plan_symbol_bindings "
        "FOR EACH ROW EXECUTE FUNCTION app.guard_symbol_rebinding()"
    )
    op.execute(
        """
        CREATE FUNCTION app.guard_plan_dag_cycle() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
        DECLARE creates_cycle boolean;
        BEGIN
          WITH RECURSIVE ancestors(id) AS (
            SELECT NEW.predecessor_operation_id
            UNION
            SELECT d.predecessor_operation_id
            FROM plan_operation_dependencies d JOIN ancestors a ON d.operation_id=a.id
            WHERE d.guild_id=NEW.guild_id AND d.plan_id=NEW.plan_id
          ) SELECT EXISTS(SELECT 1 FROM ancestors WHERE id=NEW.operation_id) INTO creates_cycle;
          IF creates_cycle THEN RAISE EXCEPTION 'plan dependency cycle' USING ERRCODE='23514'; END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_plan_dependencies_cycle BEFORE INSERT OR UPDATE "
        "ON plan_operation_dependencies FOR EACH ROW EXECUTE FUNCTION app.guard_plan_dag_cycle()"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.guard_plan_dag_cycle() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS app.guard_symbol_rebinding() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS app.guard_symbol_immutable() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS app.guard_operation_immutable() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS app.guard_plan_child_immutable() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS app.guard_plan_immutable() CASCADE")
    op.drop_table("plan_expected_mutations")
    op.drop_table("plan_progress_events")
    op.drop_table("plan_confirmations")
    op.drop_table("operation_attempts")
    op.drop_index("uq_plan_symbol_discord_binding", table_name="plan_symbol_bindings")
    op.drop_table("plan_symbol_bindings")
    op.drop_table("plan_operation_dependencies")
    op.drop_table("plan_operations")
    op.drop_index("ix_plans_guild_status_updated", table_name="plans")
    op.drop_index("uq_plans_one_applying_per_guild", table_name="plans")
    op.drop_table("plans")
    op.drop_table("plan_snapshots")
