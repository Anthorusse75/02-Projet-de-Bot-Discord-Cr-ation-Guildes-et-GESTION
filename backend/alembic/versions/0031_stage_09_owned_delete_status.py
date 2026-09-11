"""Stage 09: DELETED terminal delivery status for the owned-delete product flow.

Revision ID: 0031_stage_09
Revises: 0030_stage_09

REQ-MSG owned edit/delete (mission section 8): a delivery's own product
surface must be able to record that its message was genuinely deleted from
Discord -- a distinct terminal state from FAILED (which means the message
was never sent at all). Widens ck_message_deliveries_status
(0022_stage_09) to add 'DELETED', reached only from SENT
(did.domain.campaigns._DELIVERY_TRANSITIONS).
"""

from alembic import op

revision: str = "0031_stage_09"
down_revision: str | None = "0030_stage_09"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("ck_message_deliveries_status", "message_deliveries", type_="check")
    op.create_check_constraint(
        "ck_message_deliveries_status",
        "message_deliveries",
        "status IN "
        "('PENDING','CLAIMED','SENDING','SENT','FAILED','UNKNOWN','INTERVENTION_REQUIRED',"
        "'DELETED')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_message_deliveries_status", "message_deliveries", type_="check")
    op.create_check_constraint(
        "ck_message_deliveries_status",
        "message_deliveries",
        "status IN "
        "('PENDING','CLAIMED','SENDING','SENT','FAILED','UNKNOWN','INTERVENTION_REQUIRED')",
    )
