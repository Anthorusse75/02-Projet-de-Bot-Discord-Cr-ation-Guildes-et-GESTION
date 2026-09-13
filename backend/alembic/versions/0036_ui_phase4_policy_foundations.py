"""Add the tenant-isolated generic Policy aggregate and immutable versions.

Revision ID: 0036_ui_phase4
Revises: 0035_ui_phase2
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_ui_phase4"
down_revision: str | None = "0035_ui_phase2"
branch_labels: str | None = None
depends_on: str | None = None


def _guild_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (guild_id = app.current_guild_id()) "
        "WITH CHECK (guild_id = app.current_guild_id())"
    )


def upgrade() -> None:
    op.create_table(
        "policies",
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("policy_type", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("lifecycle_state", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.String(length=64), nullable=True),
        sa.Column("conditions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("effects_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("modified_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("create_idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("create_request_hash", sa.String(length=64), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_policies_installation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("policy_id", name="pk_policies"),
        sa.UniqueConstraint("guild_id", "policy_id", name="uq_policies_guild_policy"),
        sa.UniqueConstraint(
            "guild_id", "create_idempotency_key", name="uq_policies_create_idempotency"
        ),
        sa.CheckConstraint("contract_version > 0", name="ck_policies_contract_version"),
        sa.CheckConstraint("revision > 0", name="ck_policies_revision"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_policies_name"),
        sa.CheckConstraint(
            "lifecycle_state IN ('DRAFT','ACTIVE','DISABLED','RETIRED')",
            name="ck_policies_lifecycle",
        ),
        sa.CheckConstraint(
            "scope_type IN ('GUILD','LOGICAL_GROUP','CATEGORY','CHANNEL','ROLE',"
            "'MEMBER','BOT','CAMPAIGN','TEMPLATE')",
            name="ck_policies_scope_type",
        ),
        sa.CheckConstraint(
            "(scope_type = 'GUILD' AND scope_id IS NULL) OR "
            "(scope_type <> 'GUILD' AND length(trim(scope_id)) > 0)",
            name="ck_policies_scope_identity",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(conditions_json) = 'array'", name="ck_policies_conditions_array"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(effects_json) = 'array'", name="ck_policies_effects_array"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata_json) = 'object'", name="ck_policies_metadata_object"
        ),
    )
    op.create_index("ix_policies_guild_lifecycle", "policies", ["guild_id", "lifecycle_state"])
    op.create_index("ix_policies_guild_scope", "policies", ["guild_id", "scope_type", "scope_id"])

    op.create_table(
        "policy_versions",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("change_kind", sa.String(length=16), nullable=False),
        sa.Column("snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("author_user_id", sa.BigInteger(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id", "policy_id"],
            ["policies.guild_id", "policies.policy_id"],
            name="fk_policy_versions_policy",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("version_id", name="pk_policy_versions"),
        sa.UniqueConstraint(
            "guild_id", "policy_id", "revision", name="uq_policy_versions_revision"
        ),
        sa.CheckConstraint("revision > 0", name="ck_policy_versions_revision"),
        sa.CheckConstraint(
            "change_kind IN ('CREATE','UPDATE','ACTIVATE','DISABLE','RETIRE')",
            name="ck_policy_versions_change_kind",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot_json) = 'object'", name="ck_policy_versions_snapshot_object"
        ),
    )
    op.create_index(
        "ix_policy_versions_guild_policy_created",
        "policy_versions",
        ["guild_id", "policy_id", "created_at"],
    )
    op.create_index(
        "uq_policy_versions_idempotency",
        "policy_versions",
        ["guild_id", "policy_id", "change_kind", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    for table in ("policies", "policy_versions"):
        _guild_rls(table)
    op.execute("GRANT SELECT, INSERT, UPDATE ON policies TO did_app")
    # No UPDATE/DELETE grant: history is append-only for the application role.
    op.execute("GRANT SELECT, INSERT ON policy_versions TO did_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT, INSERT ON policy_versions FROM did_app")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON policies FROM did_app")
    op.drop_index("uq_policy_versions_idempotency", table_name="policy_versions")
    op.drop_index("ix_policy_versions_guild_policy_created", table_name="policy_versions")
    op.drop_table("policy_versions")
    op.drop_index("ix_policies_guild_scope", table_name="policies")
    op.drop_index("ix_policies_guild_lifecycle", table_name="policies")
    op.drop_table("policies")
