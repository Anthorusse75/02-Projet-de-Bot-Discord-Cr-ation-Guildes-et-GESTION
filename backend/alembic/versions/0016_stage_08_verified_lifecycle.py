"""Persist Stage 08 role reservations and post-verification intents.

Revision ID: 0016_stage_08
Revises: 0015_stage_08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_stage_08"
down_revision: str | None = "0015_stage_08"
branch_labels: str | None = None
depends_on: str | None = None


def _guild_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (guild_id = app.current_guild_id()) "
        "WITH CHECK (guild_id = app.current_guild_id())"
    )


def upgrade() -> None:
    op.create_table(
        "language_profile_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("language_profile_id", sa.Uuid(), nullable=False),
        sa.Column("discord_role_id", sa.BigInteger(), nullable=False),
        sa.Column("managed_by_did", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("role_state", sa.String(length=16), server_default="ACTIVE", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "language_profile_id"],
            ["language_profiles.guild_id", "language_profiles.id"],
            name="fk_language_profile_roles_language",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("discord_role_id > 0", name="ck_language_profile_roles_role"),
        sa.CheckConstraint(
            "role_state IN ('ACTIVE','DRIFTED','MISSING','DETACHED')",
            name="ck_language_profile_roles_state",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_language_profile_roles"),
        sa.UniqueConstraint(
            "guild_id", "language_profile_id", name="uq_language_profile_roles_language"
        ),
        sa.UniqueConstraint("guild_id", "discord_role_id", name="uq_language_profile_roles_role"),
    )
    op.create_table(
        "stage08_role_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("binding_kind", sa.String(length=24), nullable=False),
        sa.Column("binding_key", sa.String(length=192), nullable=False),
        sa.Column("visibility_scope_id", sa.Uuid(), nullable=True),
        sa.Column("language_profile_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=True),
        sa.Column("symbol", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="RESERVED", nullable=False),
        sa.Column("discord_role_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "visibility_scope_id"],
            ["visibility_scopes.guild_id", "visibility_scopes.id"],
            name="fk_stage08_role_reservations_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "language_profile_id"],
            ["language_profiles.guild_id", "language_profiles.id"],
            name="fk_stage08_role_reservations_language",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "plan_id"],
            ["plans.guild_id", "plans.id"],
            name="fk_stage08_role_reservations_plan",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "binding_kind IN ('LANGUAGE','SCOPE_LANGUAGE')",
            name="ck_stage08_role_reservations_kind",
        ),
        sa.CheckConstraint(
            "(binding_kind='LANGUAGE' AND visibility_scope_id IS NULL) OR "
            "(binding_kind='SCOPE_LANGUAGE' AND visibility_scope_id IS NOT NULL)",
            name="ck_stage08_role_reservations_shape",
        ),
        sa.CheckConstraint(
            "status IN ('RESERVED','PLANNED','BOUND','FAILED')",
            name="ck_stage08_role_reservations_status",
        ),
        sa.CheckConstraint(
            "(status='BOUND' AND discord_role_id IS NOT NULL) OR "
            "(status<>'BOUND' AND discord_role_id IS NULL)",
            name="ck_stage08_role_reservations_binding",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stage08_role_reservations"),
        sa.UniqueConstraint("guild_id", "binding_key", name="uq_stage08_role_reservations_key"),
    )
    op.create_table(
        "stage08_plan_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("intent_key", sa.String(length=192), nullable=False),
        sa.Column("intent_type", sa.String(length=40), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "plan_id"],
            ["plans.guild_id", "plans.id"],
            name="fk_stage08_plan_intents_plan",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "intent_type IN ('BIND_LANGUAGE_ROLE','BIND_SCOPE_LANGUAGE_ROLE',"
            "'VERIFY_PROVIDER','MATERIALIZE_CLONE')",
            name="ck_stage08_plan_intents_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','APPLIED','FAILED')",
            name="ck_stage08_plan_intents_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stage08_plan_intents"),
        sa.UniqueConstraint(
            "guild_id", "plan_id", "intent_key", name="uq_stage08_plan_intents_key"
        ),
    )
    op.create_index(
        "ix_stage08_plan_intents_pending",
        "stage08_plan_intents",
        ["guild_id", "plan_id", "status"],
    )
    tables = ("language_profile_roles", "stage08_role_reservations", "stage08_plan_intents")
    for table in tables:
        _guild_rls(table)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON " + ", ".join(tables) + " TO did_app")


def downgrade() -> None:
    op.drop_table("stage08_plan_intents")
    op.drop_table("stage08_role_reservations")
    op.drop_table("language_profile_roles")
