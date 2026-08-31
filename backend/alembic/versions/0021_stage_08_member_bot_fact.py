"""Persist the authoritative Discord bot fact for cached members.

Revision ID: 0021_stage_08
Revises: 0020_stage_08
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0021_stage_08"
down_revision: str | None = "0020_stage_08"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "discord_member_authorization_cache",
        sa.Column("is_bot", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("discord_member_authorization_cache", "is_bot")
