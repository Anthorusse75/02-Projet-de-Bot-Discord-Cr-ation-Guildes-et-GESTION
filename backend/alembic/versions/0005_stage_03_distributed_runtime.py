"""Fence runtime jobs and lease outbox publication across workers.

Revision ID: 0005_stage_03
Revises: 0004_stage_03
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0005_stage_03"
down_revision: str | None = "0004_stage_03"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("discord_io_jobs", sa.Column("lease_token", sa.Uuid(), nullable=True))
    op.add_column(
        "discord_io_jobs",
        sa.Column("lease_generation", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_discord_io_jobs_lease_generation",
        "discord_io_jobs",
        "lease_generation >= 0",
    )

    op.add_column("discord_outbox", sa.Column("lease_owner", sa.String(128), nullable=True))
    op.add_column("discord_outbox", sa.Column("lease_token", sa.Uuid(), nullable=True))
    op.add_column(
        "discord_outbox", sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_outbox_lease_recovery",
        "discord_outbox",
        ["status", "next_attempt_at", "leased_until"],
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.runtime_outbox_guilds(p_limit integer DEFAULT 256)
        RETURNS TABLE(guild_id bigint)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT outbox.guild_id
            FROM discord_outbox AS outbox
            WHERE outbox.status = 'PENDING'
              AND outbox.next_attempt_at <= now()
              AND (outbox.leased_until IS NULL OR outbox.leased_until < now())
            GROUP BY outbox.guild_id
            ORDER BY min(outbox.next_attempt_at), outbox.guild_id
            LIMIT LEAST(GREATEST(p_limit, 1), 1000)
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.runtime_outbox_guilds(p_limit integer DEFAULT 256)
        RETURNS TABLE(guild_id bigint)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT outbox.guild_id
            FROM discord_outbox AS outbox
            WHERE outbox.status = 'PENDING' AND outbox.next_attempt_at <= now()
            GROUP BY outbox.guild_id
            ORDER BY min(outbox.next_attempt_at), outbox.guild_id
            LIMIT LEAST(GREATEST(p_limit, 1), 1000)
        $$
        """
    )
    op.drop_index("ix_outbox_lease_recovery", table_name="discord_outbox")
    op.drop_column("discord_outbox", "leased_until")
    op.drop_column("discord_outbox", "lease_token")
    op.drop_column("discord_outbox", "lease_owner")
    op.drop_constraint("ck_discord_io_jobs_lease_generation", "discord_io_jobs", type_="check")
    op.drop_column("discord_io_jobs", "lease_generation")
    op.drop_column("discord_io_jobs", "lease_token")
