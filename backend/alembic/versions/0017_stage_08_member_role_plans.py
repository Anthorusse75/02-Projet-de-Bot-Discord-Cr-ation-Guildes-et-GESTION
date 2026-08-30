"""Allow authoritative member-role operations in the Stage 05 plan engine.

Revision ID: 0017_stage_08
Revises: 0016_stage_08
"""

from alembic import op

revision: str = "0017_stage_08"
down_revision: str | None = "0016_stage_08"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("ck_plan_operations_type", "plan_operations", type_="check")
    op.create_check_constraint(
        "ck_plan_operations_type",
        "plan_operations",
        "operation_type IN ('CREATE_ROLE','UPDATE_ROLE','DELETE_ROLE','REORDER_ROLES',"
        "'CREATE_CHANNEL','UPDATE_CHANNEL','MOVE_OR_REORDER_CHANNELS','DELETE_CHANNEL',"
        "'UPSERT_OVERWRITE','DELETE_OVERWRITE','ADD_MEMBER_ROLE','REMOVE_MEMBER_ROLE')",
    )
    op.drop_constraint("ck_plan_operations_resource_type", "plan_operations", type_="check")
    op.create_check_constraint(
        "ck_plan_operations_resource_type",
        "plan_operations",
        "resource_type IN ('ROLE','CATEGORY','CHANNEL','OVERWRITE','MEMBER_ROLE')",
    )
    op.drop_constraint(
        "ck_plan_resource_dependencies_type", "plan_resource_dependencies", type_="check"
    )
    op.create_check_constraint(
        "ck_plan_resource_dependencies_type",
        "plan_resource_dependencies",
        "resource_type IN ('ROLE','CATEGORY','CHANNEL','OVERWRITE','MEMBER')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_plan_resource_dependencies_type", "plan_resource_dependencies", type_="check"
    )
    op.create_check_constraint(
        "ck_plan_resource_dependencies_type",
        "plan_resource_dependencies",
        "resource_type IN ('ROLE','CATEGORY','CHANNEL','OVERWRITE')",
    )
    op.drop_constraint("ck_plan_operations_resource_type", "plan_operations", type_="check")
    op.create_check_constraint(
        "ck_plan_operations_resource_type",
        "plan_operations",
        "resource_type IN ('ROLE','CATEGORY','CHANNEL','OVERWRITE')",
    )
    op.drop_constraint("ck_plan_operations_type", "plan_operations", type_="check")
    op.create_check_constraint(
        "ck_plan_operations_type",
        "plan_operations",
        "operation_type IN ('CREATE_ROLE','UPDATE_ROLE','DELETE_ROLE','REORDER_ROLES',"
        "'CREATE_CHANNEL','UPDATE_CHANNEL','MOVE_OR_REORDER_CHANNELS','DELETE_CHANNEL',"
        "'UPSERT_OVERWRITE','DELETE_OVERWRITE')",
    )
