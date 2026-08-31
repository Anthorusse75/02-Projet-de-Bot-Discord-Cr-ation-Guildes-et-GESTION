"""Stage 09 remediation: explicit MESSAGE_CONTENT dependency declaration on
event triggers.

Revision ID: 0025_stage_09
Revises: 0024_stage_09

External-review finding (REQ-MSG-020): an event-triggered campaign must
explicitly declare whether its condition reads raw Discord message content,
so the platform can expose a capability requirement, a configuration
blocker, a simulation warning and fail-closed runtime behavior for it --
never inferred from event_type/condition_ast, and never a global
MESSAGE_CONTENT enablement for the whole Campaign Engine (time-based
campaigns stay entirely independent of this column). See
did.campaigns.message_content_policy for the application-layer logic this
column feeds.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0025_stage_09"
down_revision: str | None = "0024_stage_09"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "message_campaign_triggers",
        sa.Column(
            "requires_message_content",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("message_campaign_triggers", "requires_message_content")
