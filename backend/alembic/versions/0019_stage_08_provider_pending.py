"""Represent a structurally applied plan with manual provider work pending.

Revision ID: 0019_stage_08
Revises: 0018_stage_08
"""

from alembic import op

revision: str = "0019_stage_08"
down_revision: str | None = "0018_stage_08"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("ck_plans_status", "plans", type_="check")
    op.create_check_constraint(
        "ck_plans_status",
        "plans",
        "status IN ('DRAFT','VALIDATED','STALE','CONFIRMED','APPLYING',"
        "'APPLIED_WITH_PENDING_PROVIDER','PARTIALLY_APPLIED','SUCCEEDED','FAILED',"
        "'VERIFICATION_FAILED','CANCEL_REQUESTED','CANCELLED',"
        "'INTERVENTION_REQUIRED')",
    )
    op.drop_constraint("ck_plan_progress_plan_status", "plan_progress_events", type_="check")
    op.create_check_constraint(
        "ck_plan_progress_plan_status",
        "plan_progress_events",
        "plan_status IN ('DRAFT','VALIDATED','STALE','CONFIRMED','APPLYING',"
        "'APPLIED_WITH_PENDING_PROVIDER','PARTIALLY_APPLIED','SUCCEEDED','FAILED',"
        "'VERIFICATION_FAILED','CANCEL_REQUESTED','CANCELLED',"
        "'INTERVENTION_REQUIRED')",
    )
    op.drop_constraint("ck_translation_groups_status", "translation_groups", type_="check")
    op.create_check_constraint(
        "ck_translation_groups_status",
        "translation_groups",
        "status IN ('ACTIVE','PROVIDER_PENDING','DEGRADED','PROVIDER_ERROR','DETACHED')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE plan_progress_events SET plan_status='SUCCEEDED',error_code=NULL "
        "WHERE plan_status='APPLIED_WITH_PENDING_PROVIDER'"
    )
    op.execute(
        "UPDATE plans SET status='SUCCEEDED',error_code=NULL "
        "WHERE status='APPLIED_WITH_PENDING_PROVIDER'"
    )
    op.execute("UPDATE translation_groups SET status='ACTIVE' WHERE status='PROVIDER_PENDING'")
    op.drop_constraint("ck_translation_groups_status", "translation_groups", type_="check")
    op.create_check_constraint(
        "ck_translation_groups_status",
        "translation_groups",
        "status IN ('ACTIVE','DEGRADED','PROVIDER_ERROR','DETACHED')",
    )
    op.drop_constraint("ck_plan_progress_plan_status", "plan_progress_events", type_="check")
    op.create_check_constraint(
        "ck_plan_progress_plan_status",
        "plan_progress_events",
        "plan_status IN ('DRAFT','VALIDATED','STALE','CONFIRMED','APPLYING',"
        "'PARTIALLY_APPLIED','SUCCEEDED','FAILED','VERIFICATION_FAILED',"
        "'CANCEL_REQUESTED','CANCELLED','INTERVENTION_REQUIRED')",
    )
    op.drop_constraint("ck_plans_status", "plans", type_="check")
    op.create_check_constraint(
        "ck_plans_status",
        "plans",
        "status IN ('DRAFT','VALIDATED','STALE','CONFIRMED','APPLYING',"
        "'PARTIALLY_APPLIED','SUCCEEDED','FAILED','VERIFICATION_FAILED',"
        "'CANCEL_REQUESTED','CANCELLED','INTERVENTION_REQUIRED')",
    )
