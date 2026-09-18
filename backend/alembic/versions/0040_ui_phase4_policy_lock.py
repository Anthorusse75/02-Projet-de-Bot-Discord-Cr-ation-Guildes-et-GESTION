"""Add a durable "locked" flag to Policy for drift auto-reconciliation.

Revision ID: 0040_ui_phase4
Revises: 0039_ui_phase4
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0040_ui_phase4"
down_revision: str | None = "0039_ui_phase4"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "policies",
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("policies", "locked")
