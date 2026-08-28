"""Add the STAGE 07 UI catalogue and runtime locale packs.

Revision ID: 0013_stage_07
Revises: 0012_stage_06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_stage_07"
down_revision: str | None = "0012_stage_06"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "ui_catalog_versions",
        sa.Column("catalog_version", sa.String(64), nullable=False),
        sa.Column("key_manifest_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("key_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="ACTIVE", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("key_count > 0", name="ck_ui_catalog_key_count"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_ui_catalog_hash"),
        sa.CheckConstraint("status IN ('ACTIVE','RETIRED')", name="ck_ui_catalog_status"),
        sa.PrimaryKeyConstraint("catalog_version", name="pk_ui_catalog_versions"),
    )
    op.create_table(
        "ui_locale_packs",
        sa.Column("locale_code", sa.String(32), nullable=False),
        sa.Column("catalog_version", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(96), nullable=False),
        sa.Column("flag_code", sa.String(32), nullable=False),
        sa.Column("direction", sa.String(3), server_default="ltr", nullable=False),
        sa.Column("status", sa.String(16), server_default="INCOMPLETE", nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("coverage_count", sa.Integer(), nullable=False),
        sa.Column("coverage_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("direction IN ('ltr','rtl')", name="ck_ui_locale_direction"),
        sa.CheckConstraint(
            "status IN ('ACTIVE','INCOMPLETE','INVALID','DISABLED')", name="ck_ui_locale_status"
        ),
        sa.CheckConstraint(
            "coverage_percent >= 0 AND coverage_percent <= 100", name="ck_ui_locale_coverage"
        ),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_ui_locale_hash"),
        sa.ForeignKeyConstraint(
            ["catalog_version"], ["ui_catalog_versions.catalog_version"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("locale_code", "catalog_version", name="pk_ui_locale_packs"),
    )
    op.create_index("ix_ui_locale_active", "ui_locale_packs", ["catalog_version", "status"])
    op.execute("GRANT SELECT ON ui_catalog_versions, ui_locale_packs TO did_app")


def downgrade() -> None:
    op.drop_index("ix_ui_locale_active", table_name="ui_locale_packs")
    op.drop_table("ui_locale_packs")
    op.drop_table("ui_catalog_versions")
