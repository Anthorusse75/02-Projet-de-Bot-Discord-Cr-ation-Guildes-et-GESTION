"""Add explicit Policy priority for deterministic resolution.

Revision ID: 0037_ui_phase4
Revises: 0036_ui_phase4
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0037_ui_phase4"
down_revision: str | None = "0036_ui_phase4"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "policies",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_policies_priority",
        "policies",
        "priority BETWEEN -1000000 AND 1000000",
    )


def downgrade() -> None:
    op.drop_constraint("ck_policies_priority", "policies", type_="check")
    op.drop_column("policies", "priority")
