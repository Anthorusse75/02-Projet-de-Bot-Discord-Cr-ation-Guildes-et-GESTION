"""Add Stage 08 multilingual topology, language profiles and translation groups.

Revision ID: 0014_stage_08
Revises: 0013_stage_07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_stage_08"
down_revision: str | None = "0013_stage_07"
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
        "language_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_language_profiles_installation",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("length(trim(code)) > 0", name="ck_language_profiles_code"),
        sa.PrimaryKeyConstraint("id", name="pk_language_profiles"),
        sa.UniqueConstraint("guild_id", "id", name="uq_language_profiles_guild_id"),
        sa.UniqueConstraint("guild_id", "code", name="uq_language_profiles_code"),
    )
    op.create_table(
        "member_visible_languages",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("language_profile_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), server_default="EXPLICIT", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "language_profile_id"],
            ["language_profiles.guild_id", "language_profiles.id"],
            name="fk_member_visible_languages_language",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("discord_user_id > 0", name="ck_member_visible_languages_user"),
        sa.CheckConstraint(
            "source IN ('EXPLICIT','ONBOARDING','SYNC','MANUAL')",
            name="ck_member_visible_languages_source",
        ),
        sa.PrimaryKeyConstraint(
            "guild_id", "discord_user_id", "language_profile_id", name="pk_member_visible_languages"
        ),
    )
    op.create_table(
        "resource_language_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("resource_type", sa.String(length=16), nullable=False),
        sa.Column("discord_resource_id", sa.BigInteger(), nullable=False),
        sa.Column("explicit_language_profile_id", sa.Uuid(), nullable=True),
        sa.Column(
            "inherit_language", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "visibility_policy",
            sa.String(length=32),
            server_default="OPEN_ALL",
            nullable=False,
        ),
        sa.Column("visibility_scope_id", sa.Uuid(), nullable=True),
        sa.Column("custom_policy_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_resource_language_policies_installation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "explicit_language_profile_id"],
            ["language_profiles.guild_id", "language_profiles.id"],
            name="fk_resource_language_policies_language",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "visibility_scope_id"],
            ["visibility_scopes.guild_id", "visibility_scopes.id"],
            name="fk_resource_language_policies_scope",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "resource_type IN ('CATEGORY','CHANNEL')", name="ck_resource_language_policies_type"
        ),
        sa.CheckConstraint(
            "visibility_policy IN ('OPEN_ALL','LANGUAGE_FILTERED','SCOPE_AND_LANGUAGE','CUSTOM')",
            name="ck_resource_language_policies_visibility",
        ),
        sa.CheckConstraint(
            "discord_resource_id > 0", name="ck_resource_language_policies_resource"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_resource_language_policies"),
        sa.UniqueConstraint(
            "guild_id", "resource_type", "discord_resource_id", name="uq_resource_language_policies"
        ),
    )
    op.create_table(
        "translation_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("root_kind", sa.String(length=32), nullable=False),
        sa.Column("visibility_scope_id", sa.Uuid(), nullable=True),
        sa.Column("source_language_profile_id", sa.Uuid(), nullable=True),
        sa.Column(
            "routing_mode",
            sa.String(length=32),
            server_default="HUB_AND_SPOKE",
            nullable=False,
        ),
        sa.Column("provider_binding_id", sa.Uuid(), nullable=True),
        sa.Column(
            "structure_sync_mode",
            sa.String(length=32),
            server_default="MANUAL",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_translation_groups_installation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "visibility_scope_id"],
            ["visibility_scopes.guild_id", "visibility_scopes.id"],
            name="fk_translation_groups_scope",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "source_language_profile_id"],
            ["language_profiles.guild_id", "language_profiles.id"],
            name="fk_translation_groups_source_language",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "root_kind IN ('CATEGORY_SET','CHANNEL_SET')", name="ck_translation_groups_root_kind"
        ),
        sa.CheckConstraint(
            "routing_mode IN ('HUB_AND_SPOKE','FULL_MESH','CUSTOM')",
            name="ck_translation_groups_routing_mode",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','DEGRADED','PROVIDER_ERROR','DETACHED')",
            name="ck_translation_groups_status",
        ),
        sa.CheckConstraint(
            "structure_sync_mode IN ('MANUAL','PROMPT_ON_DRIFT','TEMPLATE_SYNC')",
            name="ck_translation_groups_structure_sync_mode",
        ),
        sa.CheckConstraint("version > 0", name="ck_translation_groups_version"),
        sa.PrimaryKeyConstraint("id", name="pk_translation_groups"),
        sa.UniqueConstraint("guild_id", "id", name="uq_translation_groups_guild_id"),
    )
    op.create_table(
        "translation_group_languages",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("translation_group_id", sa.Uuid(), nullable=False),
        sa.Column("language_profile_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["guild_id", "translation_group_id"],
            ["translation_groups.guild_id", "translation_groups.id"],
            name="fk_translation_group_languages_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "language_profile_id"],
            ["language_profiles.guild_id", "language_profiles.id"],
            name="fk_translation_group_languages_language",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "guild_id",
            "translation_group_id",
            "language_profile_id",
            name="pk_translation_group_languages",
        ),
    )
    op.create_table(
        "translation_category_variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("translation_group_id", sa.Uuid(), nullable=False),
        sa.Column("language_profile_id", sa.Uuid(), nullable=False),
        sa.Column("discord_category_id", sa.BigInteger(), nullable=False),
        sa.Column("is_source", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "state",
            sa.String(length=16),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "translation_group_id"],
            ["translation_groups.guild_id", "translation_groups.id"],
            name="fk_translation_category_variants_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "language_profile_id"],
            ["language_profiles.guild_id", "language_profiles.id"],
            name="fk_translation_category_variants_language",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "translation_group_id", "language_profile_id"],
            [
                "translation_group_languages.guild_id",
                "translation_group_languages.translation_group_id",
                "translation_group_languages.language_profile_id",
            ],
            name="fk_translation_category_variants_group_language",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "discord_category_id > 0", name="ck_translation_category_variants_category"
        ),
        sa.CheckConstraint(
            "state IN ('ACTIVE','MISSING','DRIFTED','DETACHED')",
            name="ck_translation_category_variants_state",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_translation_category_variants"),
        sa.UniqueConstraint("guild_id", "id", name="uq_translation_category_variants_guild_id"),
        sa.UniqueConstraint(
            "guild_id",
            "translation_group_id",
            "language_profile_id",
            name="uq_translation_category_variants_group_language",
        ),
        sa.UniqueConstraint(
            "guild_id", "discord_category_id", name="uq_translation_category_variants_category"
        ),
    )
    op.create_table(
        "translation_channel_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("translation_group_id", sa.Uuid(), nullable=False),
        sa.Column("logical_key", sa.String(length=256), nullable=False),
        sa.Column("source_language_profile_id", sa.Uuid(), nullable=True),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "translation_group_id"],
            ["translation_groups.guild_id", "translation_groups.id"],
            name="fk_translation_channel_groups_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "source_language_profile_id"],
            ["language_profiles.guild_id", "language_profiles.id"],
            name="fk_translation_channel_groups_language",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "length(trim(logical_key)) > 0", name="ck_translation_channel_groups_key"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_translation_channel_groups"),
        sa.UniqueConstraint("guild_id", "id", name="uq_translation_channel_groups_guild_id"),
        sa.UniqueConstraint(
            "guild_id",
            "translation_group_id",
            "logical_key",
            name="uq_translation_channel_group_key",
        ),
        sa.UniqueConstraint(
            "guild_id",
            "translation_group_id",
            "id",
            name="uq_translation_channel_groups_group_id",
        ),
    )
    op.create_table(
        "translation_channel_variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("translation_group_id", sa.Uuid(), nullable=False),
        sa.Column("translation_channel_group_id", sa.Uuid(), nullable=False),
        sa.Column("language_profile_id", sa.Uuid(), nullable=False),
        sa.Column("discord_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("translation_category_variant_id", sa.Uuid(), nullable=True),
        sa.Column(
            "state",
            sa.String(length=16),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "translation_channel_group_id"],
            ["translation_channel_groups.guild_id", "translation_channel_groups.id"],
            name="fk_translation_channel_variants_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "translation_group_id", "translation_channel_group_id"],
            [
                "translation_channel_groups.guild_id",
                "translation_channel_groups.translation_group_id",
                "translation_channel_groups.id",
            ],
            name="fk_translation_channel_variants_group_channel_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "language_profile_id"],
            ["language_profiles.guild_id", "language_profiles.id"],
            name="fk_translation_channel_variants_language",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "translation_category_variant_id"],
            ["translation_category_variants.guild_id", "translation_category_variants.id"],
            name="fk_translation_channel_variants_category",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "translation_group_id", "language_profile_id"],
            [
                "translation_group_languages.guild_id",
                "translation_group_languages.translation_group_id",
                "translation_group_languages.language_profile_id",
            ],
            name="fk_translation_channel_variants_group_language",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "discord_channel_id > 0", name="ck_translation_channel_variants_channel"
        ),
        sa.CheckConstraint(
            "state IN ('ACTIVE','MISSING','DRIFTED','DETACHED')",
            name="ck_translation_channel_variants_state",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_translation_channel_variants"),
        sa.UniqueConstraint(
            "guild_id",
            "translation_group_id",
            "translation_channel_group_id",
            "language_profile_id",
            name="uq_translation_channel_variants_group_language",
        ),
        sa.UniqueConstraint(
            "guild_id", "discord_channel_id", name="uq_translation_channel_variants_channel"
        ),
    )
    op.create_table(
        "translation_routes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("translation_group_id", sa.Uuid(), nullable=False),
        sa.Column("source_language_profile_id", sa.Uuid(), nullable=False),
        sa.Column("destination_language_profile_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("provider_route_ref", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "translation_group_id"],
            ["translation_groups.guild_id", "translation_groups.id"],
            name="fk_translation_routes_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "source_language_profile_id"],
            ["language_profiles.guild_id", "language_profiles.id"],
            name="fk_translation_routes_source_language",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "destination_language_profile_id"],
            ["language_profiles.guild_id", "language_profiles.id"],
            name="fk_translation_routes_destination_language",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_translation_routes"),
        sa.UniqueConstraint(
            "guild_id",
            "translation_group_id",
            "source_language_profile_id",
            "destination_language_profile_id",
            name="uq_translation_routes_group_language_pair",
        ),
    )
    op.create_table(
        "translation_provider_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("provider_instance_key", sa.String(length=128), nullable=False),
        sa.Column("provider_discord_user_id", sa.BigInteger(), nullable=True),
        sa.Column("config_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("capabilities_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="READY",
            nullable=False,
        ),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_translation_provider_bindings_installation",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('READY','DEGRADED','ERROR','DISABLED','UNKNOWN','MANUAL_CONFIGURATION_REQUIRED')",
            name="ck_translation_provider_bindings_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_translation_provider_bindings"),
        sa.UniqueConstraint("guild_id", "id", name="uq_translation_provider_bindings_guild_id"),
        sa.UniqueConstraint(
            "guild_id", "provider_instance_key", name="uq_translation_provider_bindings_key"
        ),
    )
    op.create_table(
        "visibility_scope_language_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("visibility_scope_id", sa.Uuid(), nullable=False),
        sa.Column("language_profile_id", sa.Uuid(), nullable=False),
        sa.Column("discord_role_id", sa.BigInteger(), nullable=False),
        sa.Column("managed_by_did", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "role_state",
            sa.String(length=16),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "visibility_scope_id"],
            ["visibility_scopes.guild_id", "visibility_scopes.id"],
            name="fk_visibility_scope_language_roles_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "language_profile_id"],
            ["language_profiles.guild_id", "language_profiles.id"],
            name="fk_visibility_scope_language_roles_language",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("discord_role_id > 0", name="ck_visibility_scope_language_roles_role"),
        sa.CheckConstraint(
            "role_state IN ('ACTIVE','DRIFTED','MISSING','DETACHED')",
            name="ck_visibility_scope_language_roles_state",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_visibility_scope_language_roles"),
        sa.UniqueConstraint(
            "guild_id",
            "visibility_scope_id",
            "language_profile_id",
            name="uq_visibility_scope_language_roles_scope_language",
        ),
        sa.UniqueConstraint(
            "guild_id", "discord_role_id", name="uq_visibility_scope_language_roles_role"
        ),
    )
    op.create_foreign_key(
        "fk_translation_groups_provider_binding",
        "translation_groups",
        "translation_provider_bindings",
        ["guild_id", "provider_binding_id"],
        ["guild_id", "id"],
        ondelete="SET NULL",
    )

    tables = (
        "language_profiles",
        "member_visible_languages",
        "translation_group_languages",
        "resource_language_policies",
        "translation_groups",
        "translation_category_variants",
        "translation_channel_groups",
        "translation_channel_variants",
        "translation_routes",
        "translation_provider_bindings",
        "visibility_scope_language_roles",
    )
    for table in tables:
        _guild_rls(table)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON " + ", ".join(tables) + " TO did_app")


def downgrade() -> None:
    op.drop_table("visibility_scope_language_roles")
    op.drop_constraint(
        "fk_translation_groups_provider_binding", "translation_groups", type_="foreignkey"
    )
    op.drop_table("translation_provider_bindings")
    op.drop_table("translation_routes")
    op.drop_table("translation_channel_variants")
    op.drop_table("translation_channel_groups")
    op.drop_table("translation_category_variants")
    op.execute("DROP TABLE IF EXISTS translation_group_languages")
    op.drop_table("translation_groups")
    op.drop_table("resource_language_policies")
    op.drop_table("member_visible_languages")
    op.drop_table("language_profiles")
