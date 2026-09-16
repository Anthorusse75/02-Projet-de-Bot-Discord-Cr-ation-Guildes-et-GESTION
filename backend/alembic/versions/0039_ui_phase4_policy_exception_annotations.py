"""Allow a metadata-only Policy revision to document an accepted exception.

"Accepter l'exception" (REQ-AP-VIS-017) reuses the existing Policy metadata
contract (tags/reason) instead of a second exceptions store: it must persist
as a new, audited revision without touching lifecycle_state, conditions,
effects or scope. The `policy_versions.change_kind` CHECK constraint only
allowed CREATE/UPDATE/ACTIVATE/DISABLE/RETIRE; this widens it to also allow
ANNOTATE for that metadata-only revision kind. No new table.

Revision ID: 0039_ui_phase4
Revises: 0038_ui_phase4
"""

from alembic import op

revision: str = "0039_ui_phase4"
down_revision: str | None = "0038_ui_phase4"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("ck_policy_versions_change_kind", "policy_versions", type_="check")
    op.create_check_constraint(
        "ck_policy_versions_change_kind",
        "policy_versions",
        "change_kind IN ('CREATE','UPDATE','ACTIVATE','DISABLE','RETIRE','ANNOTATE')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_policy_versions_change_kind", "policy_versions", type_="check")
    op.create_check_constraint(
        "ck_policy_versions_change_kind",
        "policy_versions",
        "change_kind IN ('CREATE','UPDATE','ACTIVATE','DISABLE','RETIRE')",
    )
