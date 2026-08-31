"""Add a renameable display name to stable translation channel groups.

Revision ID: 0015_stage_08
Revises: 0014_stage_08
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0015_stage_08"
down_revision: str | None = "0014_stage_08"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "translation_channel_groups",
        sa.Column("display_name", sa.String(length=128), nullable=True),
    )
    op.execute(
        "UPDATE translation_channel_groups SET display_name=logical_key WHERE display_name IS NULL"
    )
    op.alter_column("translation_channel_groups", "display_name", nullable=False)
    op.create_check_constraint(
        "ck_translation_channel_groups_display_name",
        "translation_channel_groups",
        "length(trim(display_name)) > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_translation_channel_groups_display_name",
        "translation_channel_groups",
        type_="check",
    )
    op.drop_column("translation_channel_groups", "display_name")
