"""Connect Policy provenance to the canonical Plan Engine.

Revision ID: 0038_ui_phase4
Revises: 0037_ui_phase4
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_ui_phase4"
down_revision: str | None = "0037_ui_phase4"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "plans",
        sa.Column("origin_type", sa.String(length=24), nullable=False, server_default="MANUAL"),
    )
    op.add_column("plans", sa.Column("source_policy_id", sa.Uuid(), nullable=True))
    op.add_column("plans", sa.Column("source_policy_revision", sa.BigInteger(), nullable=True))
    op.add_column(
        "plans",
        sa.Column(
            "origin_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("plans", sa.Column("correlation_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        "ck_plans_origin_type",
        "plans",
        "origin_type IN ('MANUAL','POLICY')",
    )
    op.create_check_constraint(
        "ck_plans_policy_origin",
        "plans",
        "(origin_type='MANUAL' AND source_policy_id IS NULL AND "
        "source_policy_revision IS NULL) OR (origin_type='POLICY' AND "
        "source_policy_id IS NOT NULL AND source_policy_revision > 0)",
    )
    op.create_check_constraint(
        "ck_plans_origin_metadata_object",
        "plans",
        "jsonb_typeof(origin_metadata) = 'object'",
    )
    op.create_foreign_key(
        "fk_plans_policy_version",
        "plans",
        "policy_versions",
        ["guild_id", "source_policy_id", "source_policy_revision"],
        ["guild_id", "policy_id", "revision"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_plans_policy_provenance",
        "plans",
        ["guild_id", "source_policy_id", "source_policy_revision", "created_at"],
        postgresql_where=sa.text("source_policy_id IS NOT NULL"),
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.guard_plan_immutable() RETURNS trigger
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
            NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key OR
            NEW.origin_type IS DISTINCT FROM OLD.origin_type OR
            NEW.source_policy_id IS DISTINCT FROM OLD.source_policy_id OR
            NEW.source_policy_revision IS DISTINCT FROM OLD.source_policy_revision OR
            NEW.origin_metadata IS DISTINCT FROM OLD.origin_metadata OR
            NEW.correlation_id IS DISTINCT FROM OLD.correlation_id
          ) THEN RAISE EXCEPTION 'validated plan is immutable' USING ERRCODE='23514'; END IF;
          RETURN NEW;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.guard_plan_immutable() RETURNS trigger
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
    op.drop_index("ix_plans_policy_provenance", table_name="plans")
    op.drop_constraint("fk_plans_policy_version", "plans", type_="foreignkey")
    op.drop_constraint("ck_plans_origin_metadata_object", "plans", type_="check")
    op.drop_constraint("ck_plans_policy_origin", "plans", type_="check")
    op.drop_constraint("ck_plans_origin_type", "plans", type_="check")
    op.drop_column("plans", "correlation_id")
    op.drop_column("plans", "origin_metadata")
    op.drop_column("plans", "source_policy_revision")
    op.drop_column("plans", "source_policy_id")
    op.drop_column("plans", "origin_type")
