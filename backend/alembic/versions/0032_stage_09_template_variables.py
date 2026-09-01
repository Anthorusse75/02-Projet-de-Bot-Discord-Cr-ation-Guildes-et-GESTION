"""Stage 09: durable persistence for typed template-variable definitions.

Revision ID: 0032_stage_09
Revises: 0031_stage_09

REQ-MSG-018 (mission section 10): did.messaging.template_variables already
implements the four typed semantics (TRANSLATABLE_TEXT/NON_TRANSLATABLE/
LOCALIZED_VALUE/PROTECTED) completely, but nothing ever durably stored an
author's declared definitions -- did.campaigns.runtime
.CampaignSchedulerRuntime always passed template_variable_definitions={}
to fan-out, so every {{variable}} in a campaign's message content fell
back to the module's own fail-safe default (NON_TRANSLATABLE) regardless
of what the author actually intended. This migration adds the missing
table; the wiring itself is in the same pass's application code.

Control-Plane/owner-scoped, same posture as message_campaign_triggers: a
template variable belongs to the campaign header, not to any one Guild the
campaign might target.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032_stage_09"
down_revision: str | None = "0031_stage_09"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "message_campaign_template_variables",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("variable_type", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("values_by_language", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["owner_discord_user_id"],
            ["users.discord_user_id"],
            name="fk_message_campaign_template_variables_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["message_campaigns.id"],
            name="fk_message_campaign_template_variables_campaign",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_message_campaign_template_variables_name"),
        sa.CheckConstraint(
            "variable_type IN "
            "('TRANSLATABLE_TEXT','NON_TRANSLATABLE','LOCALIZED_VALUE','PROTECTED')",
            name="ck_message_campaign_template_variables_type",
        ),
        # Mirrors did.messaging.template_variables.TemplateVariableDefinition
        # .__post_init__ exactly: LOCALIZED_VALUE carries values_by_language
        # only, every other type carries a single value only -- enforced
        # durably, not merely at the domain layer.
        sa.CheckConstraint(
            "(variable_type = 'LOCALIZED_VALUE' AND value IS NULL "
            "AND values_by_language IS NOT NULL) OR "
            "(variable_type <> 'LOCALIZED_VALUE' AND value IS NOT NULL "
            "AND values_by_language IS NULL)",
            name="ck_message_campaign_template_variables_shape",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message_campaign_template_variables"),
        sa.UniqueConstraint(
            "campaign_id", "name", name="uq_message_campaign_template_variables_name"
        ),
    )
    op.execute(
        "ALTER TABLE message_campaign_template_variables ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE message_campaign_template_variables FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "CREATE POLICY message_campaign_template_variables_owner_isolation "
        "ON message_campaign_template_variables "
        "USING (owner_discord_user_id = app.current_user_id()) "
        "WITH CHECK (owner_discord_user_id = app.current_user_id())"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON message_campaign_template_variables TO did_app"
    )


def downgrade() -> None:
    op.drop_table("message_campaign_template_variables")
