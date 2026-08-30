"""Add authoritative member coverage and verified technical-role cleanup.

Revision ID: 0020_stage_08
Revises: 0019_stage_08
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0020_stage_08"
down_revision: str | None = "0019_stage_08"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "discord_cache_coverage",
        sa.Column("known_members", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "discord_cache_coverage",
        sa.Column("member_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "discord_cache_coverage",
        sa.Column("members_complete", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "discord_cache_coverage",
        sa.Column("last_full_member_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_cache_member_coverage_counts",
        "discord_cache_coverage",
        "known_members >= 0 AND member_count >= 0 AND known_members <= member_count",
    )
    op.drop_constraint(
        "ck_visibility_scope_language_roles_state",
        "visibility_scope_language_roles",
        type_="check",
    )
    op.create_check_constraint(
        "ck_visibility_scope_language_roles_state",
        "visibility_scope_language_roles",
        "role_state IN ('ACTIVE','PENDING_DELETE','DRIFTED','MISSING','DETACHED')",
    )
    op.drop_constraint("ck_stage08_plan_intents_type", "stage08_plan_intents", type_="check")
    op.create_check_constraint(
        "ck_stage08_plan_intents_type",
        "stage08_plan_intents",
        "intent_type IN ('BIND_LANGUAGE_ROLE','BIND_SCOPE_LANGUAGE_ROLE',"
        "'DELETE_SCOPE_LANGUAGE_ROLE_BINDING','VERIFY_PROVIDER','MATERIALIZE_CLONE',"
        "'MATERIALIZE_CATEGORY_VARIANT','MATERIALIZE_CHANNEL_VARIANT',"
        "'REPAIR_CATEGORY_VARIANT','REPAIR_CHANNEL_VARIANT')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE visibility_scope_language_roles SET role_state='ACTIVE' "
        "WHERE role_state='PENDING_DELETE'"
    )
    op.drop_constraint("ck_stage08_plan_intents_type", "stage08_plan_intents", type_="check")
    op.create_check_constraint(
        "ck_stage08_plan_intents_type",
        "stage08_plan_intents",
        "intent_type IN ('BIND_LANGUAGE_ROLE','BIND_SCOPE_LANGUAGE_ROLE',"
        "'VERIFY_PROVIDER','MATERIALIZE_CLONE','MATERIALIZE_CATEGORY_VARIANT',"
        "'MATERIALIZE_CHANNEL_VARIANT','REPAIR_CATEGORY_VARIANT',"
        "'REPAIR_CHANNEL_VARIANT')",
    )
    op.drop_constraint(
        "ck_visibility_scope_language_roles_state",
        "visibility_scope_language_roles",
        type_="check",
    )
    op.create_check_constraint(
        "ck_visibility_scope_language_roles_state",
        "visibility_scope_language_roles",
        "role_state IN ('ACTIVE','DRIFTED','MISSING','DETACHED')",
    )
    op.drop_constraint(
        "ck_cache_member_coverage_counts", "discord_cache_coverage", type_="check"
    )
    op.drop_column("discord_cache_coverage", "last_full_member_sync_at")
    op.drop_column("discord_cache_coverage", "members_complete")
    op.drop_column("discord_cache_coverage", "member_count")
    op.drop_column("discord_cache_coverage", "known_members")
