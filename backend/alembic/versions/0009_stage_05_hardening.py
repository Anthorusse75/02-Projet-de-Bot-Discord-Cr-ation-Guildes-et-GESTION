"""Harden STAGE 05 authorization, immutability and execution evidence.

Revision ID: 0009_stage_05
Revises: 0008_stage_05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_stage_05"
down_revision: str | None = "0008_stage_05"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("uq_plans_idempotency", "plans", type_="unique")
    op.create_unique_constraint(
        "uq_plans_actor_idempotency",
        "plans",
        ["guild_id", "actor_user_id", "idempotency_key"],
    )
    op.add_column(
        "plans",
        sa.Column("progress_sequence", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.create_check_constraint("ck_plans_progress_sequence", "plans", "progress_sequence >= 0")

    # Operation UUIDs remain deterministic, but their identity is scoped to a plan.
    op.drop_constraint("pk_plan_operations", "plan_operations", type_="primary")
    op.create_primary_key("pk_plan_operations", "plan_operations", ["guild_id", "plan_id", "id"])
    op.add_column(
        "plan_operations",
        sa.Column(
            "preconditions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    op.drop_constraint("uq_plan_expected_event", "plan_expected_mutations", type_="unique")
    op.create_unique_constraint(
        "uq_plan_expected_event_item",
        "plan_expected_mutations",
        ["guild_id", "plan_id", "operation_id", "event_type", "discord_resource_id"],
    )

    op.create_table(
        "plan_resource_dependencies",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(24), nullable=False),
        sa.Column("discord_resource_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id", "plan_id"],
            ["plans.guild_id", "plans.id"],
            name="fk_plan_resource_dependencies_plan",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "resource_type IN ('ROLE','CATEGORY','CHANNEL','OVERWRITE')",
            name="ck_plan_resource_dependencies_type",
        ),
        sa.CheckConstraint("discord_resource_id > 0", name="ck_plan_resource_dependencies_id"),
        sa.CheckConstraint(
            "reason IN ('TARGET','PARENT','SUBJECT','CATEGORY_CHILD','SNAPSHOT')",
            name="ck_plan_resource_dependencies_reason",
        ),
        sa.PrimaryKeyConstraint(
            "guild_id",
            "plan_id",
            "resource_type",
            "discord_resource_id",
            name="pk_plan_resource_dependencies",
        ),
    )
    op.create_index(
        "ix_plan_resource_dependency_match",
        "plan_resource_dependencies",
        ["guild_id", "resource_type", "discord_resource_id", "plan_id"],
    )
    op.execute("ALTER TABLE plan_resource_dependencies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE plan_resource_dependencies FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY plan_resource_dependencies_tenant_isolation "
        "ON plan_resource_dependencies USING (guild_id = app.current_guild_id()) "
        "WITH CHECK (guild_id = app.current_guild_id())"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON plan_resource_dependencies TO did_app")
    op.execute(
        """
        INSERT INTO plan_resource_dependencies
          (guild_id,plan_id,resource_type,discord_resource_id,reason)
        SELECT guild_id,plan_id,
               CASE WHEN resource_type IN ('CATEGORY','CHANNEL','OVERWRITE')
                    THEN 'CHANNEL' ELSE resource_type END,
               COALESCE(resource_discord_id,
                        CASE WHEN operation_type IN ('UPSERT_OVERWRITE','DELETE_OVERWRITE')
                             THEN NULLIF(desired_payload->>'channel_id','')::bigint END),
               'TARGET'
        FROM plan_operations
        WHERE resource_discord_id IS NOT NULL OR
              (operation_type IN ('UPSERT_OVERWRITE','DELETE_OVERWRITE') AND
               desired_payload ? 'channel_id')
        ON CONFLICT DO NOTHING
        """
    )

    # Child graph definitions can change only while the parent plan is DRAFT.
    op.execute("DROP TRIGGER trg_plan_operations_immutable ON plan_operations")
    op.execute("DROP TRIGGER trg_plan_symbols_immutable ON plan_symbol_bindings")
    op.execute("DROP FUNCTION app.guard_operation_immutable()")
    op.execute("DROP FUNCTION app.guard_symbol_immutable()")
    op.execute(
        """
        CREATE FUNCTION app.guard_operation_immutable() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
        DECLARE v_status text; v_plan uuid; v_guild bigint;
        BEGIN
          v_plan := COALESCE(NEW.plan_id, OLD.plan_id);
          v_guild := COALESCE(NEW.guild_id, OLD.guild_id);
          SELECT status INTO v_status FROM plans WHERE id=v_plan AND guild_id=v_guild;
          IF v_status <> 'DRAFT' AND TG_OP IN ('INSERT','DELETE') THEN
            RAISE EXCEPTION 'validated operation set is immutable' USING ERRCODE='23514';
          END IF;
          IF v_status <> 'DRAFT' AND TG_OP='UPDATE' AND (
            NEW.guild_id IS DISTINCT FROM OLD.guild_id OR
            NEW.plan_id IS DISTINCT FROM OLD.plan_id OR
            NEW.operation_type IS DISTINCT FROM OLD.operation_type OR
            NEW.execution_target IS DISTINCT FROM OLD.execution_target OR
            NEW.resource_type IS DISTINCT FROM OLD.resource_type OR
            NEW.resource_ref IS DISTINCT FROM OLD.resource_ref OR
            (NEW.resource_discord_id IS DISTINCT FROM OLD.resource_discord_id AND NOT (
              OLD.operation_type IN ('CREATE_ROLE','CREATE_CHANNEL') AND
              OLD.resource_discord_id IS NULL AND NEW.resource_discord_id IS NOT NULL AND
              OLD.status IN ('IN_FLIGHT','UNKNOWN_OUTCOME') AND NEW.status='SUCCEEDED'
            )) OR
            NEW.produces_symbol IS DISTINCT FROM OLD.produces_symbol OR
            NEW.consumes_symbols IS DISTINCT FROM OLD.consumes_symbols OR
            NEW.desired_payload IS DISTINCT FROM OLD.desired_payload OR
            NEW.before_payload IS DISTINCT FROM OLD.before_payload OR
            NEW.preconditions IS DISTINCT FROM OLD.preconditions OR
            NEW.required_capabilities IS DISTINCT FROM OLD.required_capabilities OR
            NEW.compensation_class IS DISTINCT FROM OLD.compensation_class OR
            NEW.risk_level IS DISTINCT FROM OLD.risk_level OR
            NEW.verification_strategy IS DISTINCT FROM OLD.verification_strategy OR
            NEW.recovery_strategy IS DISTINCT FROM OLD.recovery_strategy OR
            NEW.expected_gateway_events IS DISTINCT FROM OLD.expected_gateway_events OR
            NEW.immutable_hash IS DISTINCT FROM OLD.immutable_hash OR
            NEW.display_order IS DISTINCT FROM OLD.display_order
          ) THEN
            RAISE EXCEPTION 'validated operation is immutable' USING ERRCODE='23514';
          END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_plan_operations_immutable BEFORE INSERT OR UPDATE OR DELETE "
        "ON plan_operations FOR EACH ROW EXECUTE FUNCTION app.guard_operation_immutable()"
    )
    op.execute(
        """
        CREATE FUNCTION app.guard_symbol_immutable() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
        DECLARE v_status text; v_plan uuid; v_guild bigint;
        BEGIN
          v_plan := COALESCE(NEW.plan_id, OLD.plan_id);
          v_guild := COALESCE(NEW.guild_id, OLD.guild_id);
          SELECT status INTO v_status FROM plans WHERE id=v_plan AND guild_id=v_guild;
          IF v_status <> 'DRAFT' AND TG_OP IN ('INSERT','DELETE') THEN
            RAISE EXCEPTION 'validated symbol set is immutable' USING ERRCODE='23514';
          END IF;
          IF v_status <> 'DRAFT' AND TG_OP='UPDATE' AND (
            NEW.guild_id IS DISTINCT FROM OLD.guild_id OR
            NEW.plan_id IS DISTINCT FROM OLD.plan_id OR
            NEW.symbol IS DISTINCT FROM OLD.symbol OR
            NEW.resource_type IS DISTINCT FROM OLD.resource_type OR
            NEW.producer_operation_id IS DISTINCT FROM OLD.producer_operation_id
          ) THEN
            RAISE EXCEPTION 'validated symbol definition is immutable' USING ERRCODE='23514';
          END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_plan_symbols_immutable BEFORE INSERT OR UPDATE OR DELETE "
        "ON plan_symbol_bindings FOR EACH ROW EXECUTE FUNCTION app.guard_symbol_immutable()"
    )
    op.execute(
        "CREATE TRIGGER trg_plan_resource_dependencies_immutable "
        "BEFORE INSERT OR UPDATE OR DELETE ON plan_resource_dependencies FOR EACH ROW "
        "EXECUTE FUNCTION app.guard_plan_child_immutable()"
    )

    # Snapshots are an append-only evidence ledger for both app and administrative roles.
    op.execute(
        """
        CREATE FUNCTION app.guard_plan_snapshot_append_only() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
        BEGIN
          RAISE EXCEPTION 'plan snapshots are append-only' USING ERRCODE='23514';
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_plan_snapshots_append_only BEFORE UPDATE OR DELETE "
        "ON plan_snapshots FOR EACH ROW EXECUTE FUNCTION app.guard_plan_snapshot_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.guard_plan_snapshot_append_only() CASCADE")
    op.execute(
        "DROP TRIGGER trg_plan_resource_dependencies_immutable ON plan_resource_dependencies"
    )
    op.execute("DROP TRIGGER trg_plan_symbols_immutable ON plan_symbol_bindings")
    op.execute("DROP TRIGGER trg_plan_operations_immutable ON plan_operations")
    op.execute("DROP FUNCTION app.guard_symbol_immutable()")
    op.execute("DROP FUNCTION app.guard_operation_immutable()")
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
            NEW.guild_id IS DISTINCT FROM OLD.guild_id OR NEW.plan_id IS DISTINCT FROM OLD.plan_id OR
            NEW.symbol IS DISTINCT FROM OLD.symbol OR NEW.resource_type IS DISTINCT FROM OLD.resource_type OR
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

    op.drop_index("ix_plan_resource_dependency_match", table_name="plan_resource_dependencies")
    op.drop_table("plan_resource_dependencies")
    op.drop_constraint("uq_plan_expected_event_item", "plan_expected_mutations", type_="unique")
    op.create_unique_constraint(
        "uq_plan_expected_event",
        "plan_expected_mutations",
        ["guild_id", "plan_id", "operation_id", "event_type"],
    )
    op.drop_column("plan_operations", "preconditions")
    op.drop_constraint("pk_plan_operations", "plan_operations", type_="primary")
    op.create_primary_key("pk_plan_operations", "plan_operations", ["id"])
    op.drop_constraint("ck_plans_progress_sequence", "plans", type_="check")
    op.drop_column("plans", "progress_sequence")
    op.drop_constraint("uq_plans_actor_idempotency", "plans", type_="unique")
    op.create_unique_constraint("uq_plans_idempotency", "plans", ["guild_id", "idempotency_key"])
