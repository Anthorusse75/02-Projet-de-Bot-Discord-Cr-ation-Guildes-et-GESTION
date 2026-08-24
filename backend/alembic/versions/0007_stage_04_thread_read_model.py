"""Correct Stage 04 active-thread and private-membership read projections.

Revision ID: 0007_stage_04
Revises: 0006_stage_04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_stage_04"
down_revision: str | None = "0006_stage_04"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "discord_cache_coverage",
        sa.Column(
            "active_threads_coverage",
            sa.String(length=40),
            server_default="UNKNOWN",
            nullable=False,
        ),
    )
    op.add_column(
        "discord_cache_coverage",
        sa.Column(
            "active_thread_parent_ids",
            postgresql.ARRAY(sa.BigInteger()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column(
        "discord_cache_coverage",
        sa.Column("last_active_threads_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_cache_active_threads_coverage",
        "discord_cache_coverage",
        "active_threads_coverage IN ('ACTIVE_VISIBLE_THREADS_FULL','PARTIAL','DEGRADED','UNKNOWN')",
    )

    op.add_column(
        "discord_channels_cache",
        sa.Column("thread_active_state", sa.String(length=24), nullable=True),
    )
    op.execute(
        "UPDATE discord_channels_cache SET thread_active_state=CASE "
        "WHEN COALESCE((last_full_payload->>'archived')::boolean, false) "
        "THEN 'ARCHIVED' ELSE 'ACTIVE' END WHERE type IN (10,11,12)"
    )
    op.create_check_constraint(
        "ck_channels_thread_active_state",
        "discord_channels_cache",
        "(type IN (10,11,12) AND thread_active_state IN "
        "('ACTIVE','ARCHIVED','NOT_IN_ACTIVE_SYNC','UNKNOWN')) OR "
        "(type NOT IN (10,11,12) AND thread_active_state IS NULL)",
    )

    op.create_table(
        "discord_current_thread_memberships",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("thread_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("membership_state", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state_version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "thread_id"],
            ["discord_channels_cache.guild_id", "discord_channels_cache.channel_id"],
            name="fk_current_thread_memberships_thread",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "membership_state IN ('MEMBER','NOT_MEMBER')",
            name="ck_current_thread_memberships_state",
        ),
        sa.CheckConstraint(
            "discord_user_id > 0 AND state_version > 0",
            name="ck_current_thread_memberships_values",
        ),
        sa.PrimaryKeyConstraint(
            "guild_id",
            "thread_id",
            "discord_user_id",
            name="pk_current_thread_memberships",
        ),
    )
    op.create_index(
        "ix_current_thread_memberships_user",
        "discord_current_thread_memberships",
        ["guild_id", "discord_user_id", "thread_id"],
    )
    op.execute("ALTER TABLE discord_current_thread_memberships ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE discord_current_thread_memberships FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY discord_current_thread_memberships_tenant_isolation "
        "ON discord_current_thread_memberships USING (guild_id = app.current_guild_id()) "
        "WITH CHECK (guild_id = app.current_guild_id())"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON discord_current_thread_memberships TO did_app"
    )

    op.create_check_constraint(
        "ck_visibility_scopes_logical_group_coupling",
        "visibility_scopes",
        "(scope_type='LOGICAL_GROUP' AND logical_group_id IS NOT NULL) OR "
        "(scope_type<>'LOGICAL_GROUP' AND logical_group_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_visibility_scopes_logical_group_coupling",
        "visibility_scopes",
        type_="check",
    )
    op.drop_index(
        "ix_current_thread_memberships_user",
        table_name="discord_current_thread_memberships",
    )
    op.drop_table("discord_current_thread_memberships")
    op.drop_constraint("ck_channels_thread_active_state", "discord_channels_cache", type_="check")
    op.drop_column("discord_channels_cache", "thread_active_state")
    op.drop_constraint("ck_cache_active_threads_coverage", "discord_cache_coverage", type_="check")
    op.drop_column("discord_cache_coverage", "last_active_threads_sync_at")
    op.drop_column("discord_cache_coverage", "active_thread_parent_ids")
    op.drop_column("discord_cache_coverage", "active_threads_coverage")
