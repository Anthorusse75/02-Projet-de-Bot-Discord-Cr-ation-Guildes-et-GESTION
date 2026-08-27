"""Harden STAGE 06 clone ownership, lifecycle and idempotent audit.

Revision ID: 0011_stage_06
Revises: 0010_stage_06
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0011_stage_06"
down_revision: str | None = "0010_stage_06"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "cross_guild_transfers",
        sa.Column("relationship_key", sa.String(64), nullable=True),
    )
    op.add_column(
        "cross_guild_transfers",
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_check_constraint(
        "ck_transfers_relationship_key",
        "cross_guild_transfers",
        "relationship_key IS NULL OR length(relationship_key) = 64",
    )
    op.create_check_constraint(
        "ck_transfers_state_version", "cross_guild_transfers", "state_version > 0"
    )
    op.create_table(
        "portable_clone_bindings",
        sa.Column("owner_discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("destination_guild_id", sa.BigInteger(), nullable=False),
        sa.Column("relationship_key", sa.String(64), nullable=False),
        sa.Column("logical_ref", sa.String(256), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("destination_resource_id", sa.BigInteger(), nullable=False),
        sa.Column("binding_origin", sa.String(24), nullable=False),
        sa.Column("source_artifact_hash", sa.String(64), nullable=False),
        sa.Column("transfer_id", sa.Uuid(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(relationship_key) = 64", name="ck_clone_bindings_relationship"),
        sa.CheckConstraint("length(source_artifact_hash) = 64", name="ck_clone_bindings_hash"),
        sa.CheckConstraint(
            "binding_origin IN ('CREATED','EXPLICIT','MANAGED_KEY')",
            name="ck_clone_bindings_origin",
        ),
        sa.ForeignKeyConstraint(
            ["owner_discord_user_id"], ["users.discord_user_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["transfer_id"], ["cross_guild_transfers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "owner_discord_user_id",
            "destination_guild_id",
            "relationship_key",
            "logical_ref",
            name="pk_portable_clone_bindings",
        ),
        sa.UniqueConstraint(
            "owner_discord_user_id",
            "destination_guild_id",
            "relationship_key",
            "resource_type",
            "destination_resource_id",
            name="uq_clone_binding_destination",
        ),
    )
    op.create_index(
        "ix_clone_bindings_scope",
        "portable_clone_bindings",
        ["owner_discord_user_id", "destination_guild_id", "relationship_key", "active"],
    )
    op.execute("ALTER TABLE portable_clone_bindings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE portable_clone_bindings FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY portable_clone_bindings_owner_isolation ON portable_clone_bindings "
        "USING (owner_discord_user_id = app.current_user_id()) "
        "WITH CHECK (owner_discord_user_id = app.current_user_id())"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON portable_clone_bindings TO did_app")
    op.execute(
        "DELETE FROM internal_audit_events a USING internal_audit_events b "
        "WHERE a.source='PORTABILITY' AND b.source='PORTABILITY' "
        "AND a.source=b.source AND a.event_type=b.event_type "
        "AND a.target_type=b.target_type AND a.target_id=b.target_id AND a.id>b.id"
    )
    op.create_index(
        "uq_portability_audit_boundary",
        "internal_audit_events",
        ["source", "event_type", "target_type", "target_id"],
        unique=True,
        postgresql_where=sa.text("source = 'PORTABILITY'"),
    )


def downgrade() -> None:
    op.drop_index("uq_portability_audit_boundary", table_name="internal_audit_events")
    op.drop_index("ix_clone_bindings_scope", table_name="portable_clone_bindings")
    op.drop_table("portable_clone_bindings")
    op.drop_constraint("ck_transfers_state_version", "cross_guild_transfers", type_="check")
    op.drop_constraint("ck_transfers_relationship_key", "cross_guild_transfers", type_="check")
    op.drop_column("cross_guild_transfers", "state_version")
    op.drop_column("cross_guild_transfers", "relationship_key")
