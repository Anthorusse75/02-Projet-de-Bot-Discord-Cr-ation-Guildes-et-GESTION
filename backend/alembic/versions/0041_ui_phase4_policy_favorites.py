"""Add per-user, per-Guild Policy favorites.

Revision ID: 0041_ui_phase4
Revises: 0040_ui_phase4
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0041_ui_phase4"
down_revision: str | None = "0040_ui_phase4"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "policy_favorites",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("favorite_key", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_policy_favorites_installation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["discord_user_id"],
            ["users.discord_user_id"],
            name="fk_policy_favorites_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "guild_id", "discord_user_id", "favorite_key", name="pk_policy_favorites"
        ),
        sa.CheckConstraint(
            "favorite_key ~ '^(native:[a-z0-9_]{1,64}|custom:[0-9a-f-]{36})$'",
            name="ck_policy_favorites_key",
        ),
    )
    op.execute("ALTER TABLE policy_favorites ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE policy_favorites FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY policy_favorites_owner_tenant_isolation ON policy_favorites "
        "USING (guild_id = app.current_guild_id() "
        "AND discord_user_id = app.current_user_id()) "
        "WITH CHECK (guild_id = app.current_guild_id() "
        "AND discord_user_id = app.current_user_id())"
    )
    op.execute("GRANT SELECT, INSERT, DELETE ON policy_favorites TO did_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT, INSERT, DELETE ON policy_favorites FROM did_app")
    op.drop_table("policy_favorites")
