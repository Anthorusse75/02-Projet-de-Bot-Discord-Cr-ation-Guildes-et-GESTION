"""Add STAGE 06 portable artifacts, templates and cross-Guild transfers.

Revision ID: 0010_stage_06
Revises: 0009_stage_05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_stage_06"
down_revision: str | None = "0009_stage_05"
branch_labels: str | None = None
depends_on: str | None = None

ARTIFACT_KINDS = ("CLIPBOARD", "LIBRARY", "EXPORT_BUNDLE", "FILE_IMPORT")
ARTIFACT_TYPES = ("CHANNEL", "CATEGORY", "LOGICAL_GROUP", "GUILD_CONFIG", "CUSTOM_BUNDLE")
TRANSFER_MODES = ("COPY_AS_NEW", "MERGE", "RECONCILE", "MAXIMUM_COMPATIBLE")
TRANSFER_STATES = (
    "CREATED",
    "SOURCE_AUTHORIZED",
    "EXPORTED",
    "MAPPING_REQUIRED",
    "READY",
    "COMPILED",
    "FAILED",
    "CANCELLED",
)


def _values(column: str, values: tuple[str, ...], name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        f"{column} IN ({','.join(repr(value) for value in values)})", name=name
    )


def _user_rls(table: str, column: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_owner_isolation ON {table} "
        f"USING ({column} = app.current_user_id()) "
        f"WITH CHECK ({column} = app.current_user_id())"
    )


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
        "user_portable_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("source_guild_id", sa.BigInteger(), nullable=True),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=True),
        sa.Column("content_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("content_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("wrap_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_key_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content_size_bytes", sa.Integer(), nullable=False),
        sa.Column("idempotency_operation", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        _values("kind", ARTIFACT_KINDS, "ck_portable_artifacts_kind"),
        _values("artifact_type", ARTIFACT_TYPES, "ck_portable_artifacts_type"),
        sa.CheckConstraint("encryption_key_version > 0", name="ck_artifacts_key_version"),
        sa.CheckConstraint("content_size_bytes > 0", name="ck_artifacts_content_size"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_artifacts_content_hash"),
        sa.ForeignKeyConstraint(
            ["owner_discord_user_id"],
            ["users.discord_user_id"],
            name="fk_portable_artifacts_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_portable_artifacts"),
        sa.UniqueConstraint("owner_discord_user_id", "id", name="uq_portable_artifacts_owner_id"),
        sa.UniqueConstraint(
            "owner_discord_user_id",
            "idempotency_operation",
            "idempotency_key",
            name="uq_portable_artifacts_idempotency",
        ),
    )
    op.create_table(
        "templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("artifact_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _values("artifact_type", ARTIFACT_TYPES, "ck_templates_artifact_type"),
        sa.CheckConstraint("version > 0", name="ck_templates_version"),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_templates_installation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.discord_user_id"], name="fk_templates_creator"
        ),
        sa.PrimaryKeyConstraint("guild_id", "id", name="pk_templates"),
        sa.UniqueConstraint("guild_id", "name", name="uq_templates_guild_name"),
    )
    op.create_table(
        "cross_guild_transfers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("source_guild_id", sa.BigInteger(), nullable=True),
        sa.Column("destination_guild_id", sa.BigInteger(), nullable=False),
        sa.Column("portable_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_content_hash", sa.String(64), nullable=False),
        sa.Column("destination_plan_id", sa.Uuid(), nullable=True),
        sa.Column("transfer_mode", sa.String(32), nullable=False),
        sa.Column("mapping_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("local_result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _values("transfer_mode", TRANSFER_MODES, "ck_transfers_mode"),
        _values("status", TRANSFER_STATES, "ck_transfers_status"),
        sa.ForeignKeyConstraint(
            ["actor_discord_user_id"],
            ["users.discord_user_id"],
            name="fk_transfers_actor",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_discord_user_id", "portable_artifact_id"],
            ["user_portable_artifacts.owner_discord_user_id", "user_portable_artifacts.id"],
            name="fk_transfers_owned_artifact",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["destination_guild_id", "destination_plan_id"],
            ["plans.guild_id", "plans.id"],
            name="fk_transfers_destination_plan",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cross_guild_transfers"),
        sa.UniqueConstraint(
            "actor_discord_user_id", "id", name="uq_cross_guild_transfers_owner_id"
        ),
        sa.UniqueConstraint(
            "actor_discord_user_id", "idempotency_key", name="uq_transfers_idempotency"
        ),
    )
    op.create_table(
        "portable_policy_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("logical_key", sa.String(256), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("definition_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "principal_mappings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("source_artifact_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_portable_policy_installation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.discord_user_id"], name="fk_portable_policy_creator"
        ),
        sa.PrimaryKeyConstraint("guild_id", "id", name="pk_portable_policy_definitions"),
        sa.UniqueConstraint(
            "guild_id", "logical_key", "source_artifact_hash", name="uq_portable_policy_source"
        ),
        sa.CheckConstraint("length(source_artifact_hash) = 64", name="ck_portable_policy_hash"),
    )
    op.create_index(
        "ix_portable_artifacts_owner_created",
        "user_portable_artifacts",
        ["owner_discord_user_id", "created_at"],
    )
    op.create_index("ix_portable_artifacts_expiry", "user_portable_artifacts", ["expires_at"])
    op.create_index("ix_templates_guild_updated", "templates", ["guild_id", "updated_at"])
    op.create_index(
        "ix_transfers_actor_updated",
        "cross_guild_transfers",
        ["actor_discord_user_id", "updated_at"],
    )
    op.create_index(
        "ix_portable_policy_guild_created",
        "portable_policy_definitions",
        ["guild_id", "created_at"],
    )
    _user_rls("user_portable_artifacts", "owner_discord_user_id")
    _user_rls("cross_guild_transfers", "actor_discord_user_id")
    _guild_rls("templates")
    _guild_rls("portable_policy_definitions")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON user_portable_artifacts, templates, "
        "cross_guild_transfers, portable_policy_definitions TO did_app"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_portable_policy_guild_created")
    op.drop_index("ix_transfers_actor_updated", table_name="cross_guild_transfers")
    op.drop_index("ix_templates_guild_updated", table_name="templates")
    op.drop_index("ix_portable_artifacts_expiry", table_name="user_portable_artifacts")
    op.drop_index("ix_portable_artifacts_owner_created", table_name="user_portable_artifacts")
    op.execute("DROP TABLE IF EXISTS portable_policy_definitions")
    op.drop_table("cross_guild_transfers")
    op.drop_table("templates")
    op.drop_table("user_portable_artifacts")
