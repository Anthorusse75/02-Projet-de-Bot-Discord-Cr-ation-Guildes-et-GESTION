"""Add Stage 04 logical groups, visibility scopes and membership rules.

Revision ID: 0006_stage_04
Revises: 0005_stage_03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_stage_04"
down_revision: str | None = "0005_stage_03"
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
        "logical_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id"], ["guild_installations.guild_id"],
            name="fk_logical_groups_installation", ondelete="CASCADE"
        ),
        sa.CheckConstraint("version > 0", name="ck_logical_groups_version"),
        sa.PrimaryKeyConstraint("id", name="pk_logical_groups"),
        sa.UniqueConstraint("guild_id", "id", name="uq_logical_groups_guild_id"),
        sa.UniqueConstraint("guild_id", "slug", name="uq_logical_groups_slug"),
    )
    op.create_table(
        "logical_group_resources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("logical_group_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(length=16), nullable=False),
        sa.Column("discord_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("discord_role_id", sa.BigInteger(), nullable=True),
        sa.Column("semantic_role", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id", "logical_group_id"], ["logical_groups.guild_id", "logical_groups.id"],
            name="fk_logical_group_resources_group", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "discord_channel_id"],
            ["discord_channels_cache.guild_id", "discord_channels_cache.channel_id"],
            name="fk_logical_group_resources_channel", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "discord_role_id"],
            ["discord_roles_cache.guild_id", "discord_roles_cache.role_id"],
            name="fk_logical_group_resources_role", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "(resource_type IN ('CATEGORY','CHANNEL') AND discord_channel_id IS NOT NULL "
            "AND discord_role_id IS NULL) OR "
            "(resource_type='ROLE' AND discord_role_id IS NOT NULL "
            "AND discord_channel_id IS NULL)",
            name="ck_logical_group_resources_target",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_logical_group_resources"),
    )
    op.create_index(
        "uq_logical_group_resource_channel", "logical_group_resources",
        ["guild_id", "logical_group_id", "resource_type", "discord_channel_id"],
        unique=True, postgresql_where=sa.text("discord_channel_id IS NOT NULL")
    )
    op.create_index(
        "uq_logical_group_resource_role", "logical_group_resources",
        ["guild_id", "logical_group_id", "resource_type", "discord_role_id"],
        unique=True, postgresql_where=sa.text("discord_role_id IS NOT NULL")
    )
    op.create_table(
        "visibility_scopes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("logical_group_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id"], ["guild_installations.guild_id"],
            name="fk_visibility_scopes_installation", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "logical_group_id"], ["logical_groups.guild_id", "logical_groups.id"],
            name="fk_visibility_scopes_logical_group", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "scope_type IN ('GLOBAL','LOGICAL_GROUP','STAFF','PROJECT','CUSTOM')",
            name="ck_visibility_scopes_type",
        ),
        sa.CheckConstraint("version > 0", name="ck_visibility_scopes_version"),
        sa.PrimaryKeyConstraint("id", name="pk_visibility_scopes"),
        sa.UniqueConstraint("guild_id", "id", name="uq_visibility_scopes_guild_id"),
        sa.UniqueConstraint("guild_id", "scope_key", name="uq_visibility_scopes_key"),
    )
    op.create_table(
        "scope_membership_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("visibility_scope_id", sa.Uuid(), nullable=False),
        sa.Column("rule_type", sa.String(length=32), nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="ACTIVE", nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id", "visibility_scope_id"],
            ["visibility_scopes.guild_id", "visibility_scopes.id"],
            name="fk_scope_membership_rules_scope", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "rule_type IN ('DISCORD_ROLE','ANY_DISCORD_ROLE','ALL_DISCORD_ROLES',"
            "'EXPLICIT_DID_MEMBERSHIP','CUSTOM')",
            name="ck_scope_membership_rules_type",
        ),
        sa.CheckConstraint("priority >= 0", name="ck_scope_membership_rules_priority"),
        sa.CheckConstraint("status IN ('ACTIVE','DISABLED')", name="ck_scope_membership_rules_status"),
        sa.CheckConstraint("version > 0", name="ck_scope_membership_rules_version"),
        sa.PrimaryKeyConstraint("id", name="pk_scope_membership_rules"),
        sa.UniqueConstraint("guild_id", "id", name="uq_scope_membership_rules_guild_id"),
        sa.UniqueConstraint(
            "guild_id", "visibility_scope_id", "priority", name="uq_scope_membership_rules_priority"
        ),
    )
    op.create_table(
        "scope_explicit_memberships",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("visibility_scope_id", sa.Uuid(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id", "visibility_scope_id"],
            ["visibility_scopes.guild_id", "visibility_scopes.id"],
            name="fk_scope_explicit_memberships_scope", ondelete="CASCADE"
        ),
        sa.CheckConstraint("discord_user_id > 0", name="ck_scope_explicit_memberships_user"),
        sa.CheckConstraint("version > 0", name="ck_scope_explicit_memberships_version"),
        sa.PrimaryKeyConstraint(
            "guild_id", "visibility_scope_id", "discord_user_id",
            name="pk_scope_explicit_memberships"
        ),
    )

    tables = (
        "logical_groups",
        "logical_group_resources",
        "visibility_scopes",
        "scope_membership_rules",
        "scope_explicit_memberships",
    )
    for table in tables:
        _guild_rls(table)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON " + ", ".join(tables) + " TO did_app")


def downgrade() -> None:
    op.drop_table("scope_explicit_memberships")
    op.drop_table("scope_membership_rules")
    op.drop_table("visibility_scopes")
    op.drop_index("uq_logical_group_resource_role", table_name="logical_group_resources")
    op.drop_index("uq_logical_group_resource_channel", table_name="logical_group_resources")
    op.drop_table("logical_group_resources")
    op.drop_table("logical_groups")
