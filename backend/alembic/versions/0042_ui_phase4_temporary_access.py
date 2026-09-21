"""Add durable temporary Policy access schedules.

Revision ID: 0042_ui_phase4
Revises: 0041_ui_phase4
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0042_ui_phase4"
down_revision: str | None = "0041_ui_phase4"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "policy_temporary_access",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("removal_plan_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=160), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("removal_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["guild_id", "policy_id"],
            ["policies.guild_id", "policies.policy_id"],
            name="fk_policy_temporary_access_policy",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("guild_id", "policy_id", name="pk_policy_temporary_access"),
        sa.CheckConstraint(
            "status IN ('SCHEDULED','PROCESSING','REMOVAL_SCHEDULED','REMOVED','INTERVENTION_REQUIRED','CANCELLED')",
            name="ck_policy_temporary_access_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_policy_temporary_access_attempts"),
    )
    op.create_index(
        "ix_policy_temporary_access_due",
        "policy_temporary_access",
        ["status", "next_attempt_at"],
    )
    op.execute("ALTER TABLE policy_temporary_access ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE policy_temporary_access FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY policy_temporary_access_tenant_isolation ON policy_temporary_access "
        "USING (guild_id = app.current_guild_id()) "
        "WITH CHECK (guild_id = app.current_guild_id())"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON policy_temporary_access TO did_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT, INSERT, UPDATE ON policy_temporary_access FROM did_app")
    op.drop_index("ix_policy_temporary_access_due", table_name="policy_temporary_access")
    op.drop_table("policy_temporary_access")
