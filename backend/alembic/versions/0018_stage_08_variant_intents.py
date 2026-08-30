"""Add verified materialization intents for translation variants.

Revision ID: 0018_stage_08
Revises: 0017_stage_08
"""

from alembic import op

revision: str = "0018_stage_08"
down_revision: str | None = "0017_stage_08"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("ck_stage08_plan_intents_type", "stage08_plan_intents", type_="check")
    op.create_check_constraint(
        "ck_stage08_plan_intents_type",
        "stage08_plan_intents",
        "intent_type IN ('BIND_LANGUAGE_ROLE','BIND_SCOPE_LANGUAGE_ROLE',"
        "'VERIFY_PROVIDER','MATERIALIZE_CLONE','MATERIALIZE_CATEGORY_VARIANT',"
        "'MATERIALIZE_CHANNEL_VARIANT','REPAIR_CATEGORY_VARIANT',"
        "'REPAIR_CHANNEL_VARIANT')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_stage08_plan_intents_type", "stage08_plan_intents", type_="check")
    op.create_check_constraint(
        "ck_stage08_plan_intents_type",
        "stage08_plan_intents",
        "intent_type IN ('BIND_LANGUAGE_ROLE','BIND_SCOPE_LANGUAGE_ROLE',"
        "'VERIFY_PROVIDER','MATERIALIZE_CLONE')",
    )
