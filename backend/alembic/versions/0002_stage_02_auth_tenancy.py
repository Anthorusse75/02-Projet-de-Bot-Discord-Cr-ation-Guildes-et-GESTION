"""Add OAuth grants, opaque session ownership, installations and RBAC.

Revision ID: 0002_stage_02
Revises: 0001_stage_01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_stage_02"
down_revision: str | None = "0001_stage_01"
branch_labels: str | None = None
depends_on: str | None = None

INSTALLATION_STATES = (
    "DISCOVERED",
    "INSTALLED",
    "PENDING_SETUP",
    "ACTIVE",
    "DEGRADED",
    "REVOKED",
    "UNINSTALLED",
)
PLATFORM_ROLES = ("OWNER", "TENANT_ADMIN", "READ_ONLY")
ACCESS_STATES = ("ACTIVE", "REVOKED")
SCOPE_KINDS = ("GUILD", "LOGICAL_GROUP", "VISIBILITY_SCOPE")


def _user_rls(table: str, column: str = "discord_user_id") -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_owner_isolation ON {table} "
        f"USING ({column} = app.current_user_id()) "
        f"WITH CHECK ({column} = app.current_user_id())"
    )


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
        "users",
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("global_name", sa.Text(), nullable=True),
        sa.Column("avatar_hash", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("discord_user_id", name="pk_users"),
    )
    op.create_table(
        "discord_oauth_grants",
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("scopes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("access_token_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("access_token_nonce", sa.LargeBinary(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_token_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("refresh_token_nonce", sa.LargeBinary(), nullable=True),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("row_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("key_version > 0", name="ck_oauth_grants_key_version"),
        sa.CheckConstraint("row_version > 0", name="ck_oauth_grants_row_version"),
        sa.ForeignKeyConstraint(
            ["discord_user_id"],
            ["users.discord_user_id"],
            name="fk_oauth_grants_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("discord_user_id", name="pk_discord_oauth_grants"),
    )
    op.create_table(
        "user_ui_preferences",
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("ui_locale_override_code", sa.String(length=32), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["discord_user_id"],
            ["users.discord_user_id"],
            name="fk_user_preferences_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("discord_user_id", name="pk_user_ui_preferences"),
    )
    op.create_table(
        "guild_installations",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("icon_hash", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.BigInteger(), nullable=True),
        sa.Column("installation_status", sa.String(length=32), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=True),
        sa.Column("bot_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "installed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uninstalled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_gateway_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "settings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "installation_status IN ("
            + ",".join(f"'{state}'" for state in INSTALLATION_STATES)
            + ")",
            name="ck_guild_installations_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_guild_installations_version"),
        sa.PrimaryKeyConstraint("guild_id", name="pk_guild_installations"),
        sa.UniqueConstraint("guild_id", "application_id", name="uq_guild_installations_app"),
    )
    op.create_table(
        "guild_user_access",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("platform_role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scope_kind", sa.String(length=32), server_default="GUILD", nullable=False),
        sa.Column("scope_id", sa.Text(), server_default="*", nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("policy_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "platform_role IN (" + ",".join(f"'{role}'" for role in PLATFORM_ROLES) + ")",
            name="ck_guild_user_access_role",
        ),
        sa.CheckConstraint(
            "status IN (" + ",".join(f"'{state}'" for state in ACCESS_STATES) + ")",
            name="ck_guild_user_access_status",
        ),
        sa.CheckConstraint(
            "scope_kind IN (" + ",".join(f"'{scope}'" for scope in SCOPE_KINDS) + ")",
            name="ck_guild_user_access_scope_kind",
        ),
        sa.CheckConstraint(
            "(scope_kind = 'GUILD' AND scope_id = '*') OR "
            "(scope_kind <> 'GUILD' AND btrim(scope_id) <> '' AND scope_id <> '*')",
            name="ck_guild_user_access_scope_pair",
        ),
        sa.CheckConstraint("policy_version > 0", name="ck_guild_user_access_policy_version"),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_guild_user_access_installation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["discord_user_id"],
            ["users.discord_user_id"],
            name="fk_guild_user_access_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.discord_user_id"], name="fk_guild_user_access_creator"
        ),
        sa.PrimaryKeyConstraint(
            "guild_id",
            "discord_user_id",
            "scope_kind",
            "scope_id",
            name="pk_guild_user_access",
        ),
    )
    op.create_table(
        "guild_role_bindings",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_role_id", sa.BigInteger(), nullable=False),
        sa.Column("dashboard_role", sa.String(length=32), nullable=False),
        sa.Column("scope_kind", sa.String(length=32), server_default="GUILD", nullable=False),
        sa.Column("scope_id", sa.Text(), server_default="*", nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "dashboard_role IN (" + ",".join(f"'{role}'" for role in PLATFORM_ROLES) + ")",
            name="ck_guild_role_bindings_role",
        ),
        sa.CheckConstraint(
            "scope_kind IN (" + ",".join(f"'{scope}'" for scope in SCOPE_KINDS) + ")",
            name="ck_guild_role_bindings_scope_kind",
        ),
        sa.CheckConstraint(
            "(scope_kind = 'GUILD' AND scope_id = '*') OR "
            "(scope_kind <> 'GUILD' AND btrim(scope_id) <> '' AND scope_id <> '*')",
            name="ck_guild_role_bindings_scope_pair",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_guild_role_bindings_installation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.discord_user_id"], name="fk_guild_role_bindings_creator"
        ),
        sa.PrimaryKeyConstraint(
            "guild_id", "discord_role_id", "scope_kind", "scope_id", name="pk_guild_role_bindings"
        ),
    )
    op.create_index(
        "ix_oauth_grants_active", "discord_oauth_grants", ["revoked_at", "access_token_expires_at"]
    )
    op.create_index("ix_installations_status", "guild_installations", ["installation_status"])
    op.create_index("ix_guild_user_access_user", "guild_user_access", ["discord_user_id", "status"])

    for table in ("users", "discord_oauth_grants", "user_ui_preferences"):
        _user_rls(table)
    for table in ("guild_installations", "guild_user_access", "guild_role_bindings"):
        _guild_rls(table)
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON users, discord_oauth_grants, "
        "user_ui_preferences, guild_installations, guild_user_access, guild_role_bindings TO did_app"
    )


def downgrade() -> None:
    op.drop_index("ix_guild_user_access_user", table_name="guild_user_access")
    op.drop_index("ix_installations_status", table_name="guild_installations")
    op.drop_index("ix_oauth_grants_active", table_name="discord_oauth_grants")
    op.drop_table("guild_role_bindings")
    op.drop_table("guild_user_access")
    op.drop_table("guild_installations")
    op.drop_table("user_ui_preferences")
    op.drop_table("discord_oauth_grants")
    op.drop_table("users")
