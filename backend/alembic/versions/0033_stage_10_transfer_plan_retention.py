"""Retain cross-Guild transfer history when its destination plan is deleted.

Revision ID: 0033_stage_10
Revises: 0032_stage_09
"""

from alembic import op

revision: str = "0033_stage_10"
down_revision: str | None = "0032_stage_09"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint(
        "fk_transfers_destination_plan",
        "cross_guild_transfers",
        type_="foreignkey",
    )
    op.execute(
        "ALTER TABLE cross_guild_transfers "
        "ADD CONSTRAINT fk_transfers_destination_plan "
        "FOREIGN KEY (destination_guild_id, destination_plan_id) "
        "REFERENCES plans (guild_id, id) "
        "ON DELETE SET NULL (destination_plan_id)"
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_transfers_destination_plan",
        "cross_guild_transfers",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_transfers_destination_plan",
        "cross_guild_transfers",
        "plans",
        ["destination_guild_id", "destination_plan_id"],
        ["guild_id", "id"],
        ondelete="RESTRICT",
    )
