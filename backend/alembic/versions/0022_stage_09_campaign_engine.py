"""Add Stage 09 message/campaign engine, deliveries, glossaries and approved variants.

Revision ID: 0022_stage_09
Revises: 0021_stage_08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_stage_09"
down_revision: str | None = "0021_stage_08"
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


def _owner_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_owner_isolation ON {table} "
        "USING (owner_discord_user_id = app.current_user_id()) "
        "WITH CHECK (owner_discord_user_id = app.current_user_id())"
    )


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Control-Plane / user-owned campaign header and its 1:1/1:N children.
    # These carry no guild_id: a campaign may fan out to many Guilds and
    # the header itself never authorizes a specific tenant.
    # ------------------------------------------------------------------
    op.create_table(
        "message_campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("logical_campaign_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_language_code", sa.String(length=16), nullable=False),
        sa.Column("message_model", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "allowed_mentions_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "attachment_policy",
            sa.String(length=32),
            server_default="PRESERVE_EXISTING",
            nullable=False,
        ),
        sa.Column("publication_mode", sa.String(length=24), nullable=False),
        sa.Column(
            "lifecycle_status", sa.String(length=24), server_default="DRAFT", nullable=False
        ),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["owner_discord_user_id"],
            ["users.discord_user_id"],
            name="fk_message_campaigns_owner",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_message_campaigns_name"),
        sa.CheckConstraint(
            "length(trim(source_language_code)) > 0", name="ck_message_campaigns_source_language"
        ),
        sa.CheckConstraint(
            "attachment_policy IN ('PRESERVE_EXISTING','REPLACE_ALL','REMOVE_ALL')",
            name="ck_message_campaigns_attachment_policy",
        ),
        sa.CheckConstraint(
            "publication_mode IN ('IMMEDIATE','ONE_SHOT_DEFERRED','RECURRING','EVENT_TRIGGERED')",
            name="ck_message_campaigns_publication_mode",
        ),
        sa.CheckConstraint(
            "lifecycle_status IN "
            "('DRAFT','SCHEDULED_ARMED','ACTIVE_RUNNING','PAUSED','CANCELLED',"
            "'COMPLETED','FAILED_INTERVENTION')",
            name="ck_message_campaigns_lifecycle_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_message_campaigns_version"),
        sa.PrimaryKeyConstraint("id", name="pk_message_campaigns"),
        sa.UniqueConstraint(
            "owner_discord_user_id", "logical_campaign_key", name="uq_message_campaigns_key"
        ),
    )

    op.create_table(
        "message_campaign_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_kind", sa.String(length=16), nullable=False),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rrule", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "misfire_policy", sa.String(length=24), server_default="SKIP_MISSED", nullable=False
        ),
        sa.Column(
            "dst_nonexistent_policy",
            sa.String(length=16),
            server_default="SHIFT_FORWARD",
            nullable=False,
        ),
        sa.Column(
            "dst_ambiguous_policy",
            sa.String(length=16),
            server_default="EARLIEST",
            nullable=False,
        ),
        sa.Column("catch_up_bound", sa.Integer(), server_default="1", nullable=False),
        sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_cursor_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occurrence_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["owner_discord_user_id"],
            ["users.discord_user_id"],
            name="fk_message_campaign_schedules_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["message_campaigns.id"],
            name="fk_message_campaign_schedules_campaign",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "schedule_kind IN ('IMMEDIATE','ONE_SHOT','RECURRING')",
            name="ck_message_campaign_schedules_kind",
        ),
        sa.CheckConstraint(
            "misfire_policy IN ('SKIP_MISSED','FIRE_ONCE_IMMEDIATELY')",
            name="ck_message_campaign_schedules_misfire",
        ),
        sa.CheckConstraint(
            "dst_nonexistent_policy IN ('SHIFT_FORWARD','SKIP')",
            name="ck_message_campaign_schedules_dst_nonexistent",
        ),
        sa.CheckConstraint(
            "dst_ambiguous_policy IN ('EARLIEST','LATEST')",
            name="ck_message_campaign_schedules_dst_ambiguous",
        ),
        sa.CheckConstraint(
            "catch_up_bound >= 0 AND catch_up_bound <= 50",
            name="ck_message_campaign_schedules_catch_up",
        ),
        sa.CheckConstraint(
            "(schedule_kind = 'ONE_SHOT' AND fire_at IS NOT NULL) OR "
            "(schedule_kind = 'RECURRING' AND rrule IS NOT NULL AND timezone IS NOT NULL "
            "AND starts_at IS NOT NULL) OR "
            "(schedule_kind = 'IMMEDIATE')",
            name="ck_message_campaign_schedules_shape",
        ),
        sa.CheckConstraint("version > 0", name="ck_message_campaign_schedules_version"),
        sa.PrimaryKeyConstraint("id", name="pk_message_campaign_schedules"),
        sa.UniqueConstraint("campaign_id", name="uq_message_campaign_schedules_campaign"),
    )

    op.create_table(
        "message_campaign_triggers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column(
            "condition_ast",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='{"op": "ALWAYS"}',
            nullable=False,
        ),
        sa.Column("max_causation_depth", sa.Integer(), server_default="8", nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["owner_discord_user_id"],
            ["users.discord_user_id"],
            name="fk_message_campaign_triggers_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["message_campaigns.id"],
            name="fk_message_campaign_triggers_campaign",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "length(trim(event_type)) > 0", name="ck_message_campaign_triggers_event_type"
        ),
        sa.CheckConstraint(
            "max_causation_depth >= 1 AND max_causation_depth <= 32",
            name="ck_message_campaign_triggers_depth",
        ),
        sa.CheckConstraint("version > 0", name="ck_message_campaign_triggers_version"),
        sa.PrimaryKeyConstraint("id", name="pk_message_campaign_triggers"),
        sa.UniqueConstraint("campaign_id", name="uq_message_campaign_triggers_campaign"),
    )

    op.create_table(
        "message_glossary_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("scope_kind", sa.String(length=16), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("source_term", sa.String(length=200), nullable=False),
        sa.Column("target_language_code", sa.String(length=16), nullable=True),
        sa.Column("behavior", sa.String(length=24), nullable=False),
        sa.Column("forced_translation", sa.String(length=400), nullable=True),
        sa.Column(
            "match_mode", sa.String(length=24), server_default="CASE_INSENSITIVE", nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["owner_discord_user_id"],
            ["users.discord_user_id"],
            name="fk_message_glossary_entries_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["message_campaigns.id"],
            name="fk_message_glossary_entries_campaign",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "length(trim(source_term)) > 0", name="ck_message_glossary_entries_term"
        ),
        sa.CheckConstraint(
            "scope_kind IN ('GLOBAL_USER','CAMPAIGN')", name="ck_message_glossary_entries_scope"
        ),
        sa.CheckConstraint(
            "(scope_kind = 'CAMPAIGN' AND campaign_id IS NOT NULL) OR "
            "(scope_kind = 'GLOBAL_USER' AND campaign_id IS NULL)",
            name="ck_message_glossary_entries_scope_shape",
        ),
        sa.CheckConstraint(
            "behavior IN ('DO_NOT_TRANSLATE','FORCED_TRANSLATION')",
            name="ck_message_glossary_entries_behavior",
        ),
        sa.CheckConstraint(
            "(behavior = 'FORCED_TRANSLATION' AND forced_translation IS NOT NULL) OR "
            "(behavior = 'DO_NOT_TRANSLATE' AND forced_translation IS NULL)",
            name="ck_message_glossary_entries_behavior_shape",
        ),
        sa.CheckConstraint(
            "match_mode IN ('EXACT','CASE_INSENSITIVE')",
            name="ck_message_glossary_entries_match_mode",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message_glossary_entries"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_message_glossary_entries_term ON message_glossary_entries "
        "(owner_discord_user_id, scope_kind, "
        "coalesce(campaign_id, '00000000-0000-0000-0000-000000000000'::uuid), "
        "lower(source_term), coalesce(target_language_code, ''))"
    )

    op.create_table(
        "message_approved_variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("target_language_code", sa.String(length=16), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "localized_message_model", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("approved_by_discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "approved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["owner_discord_user_id"],
            ["users.discord_user_id"],
            name="fk_message_approved_variants_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["message_campaigns.id"],
            name="fk_message_approved_variants_campaign",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "length(source_fingerprint) = 64", name="ck_message_approved_variants_fingerprint"
        ),
        sa.CheckConstraint(
            "length(trim(target_language_code)) > 0",
            name="ck_message_approved_variants_language",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message_approved_variants"),
        sa.UniqueConstraint(
            "campaign_id", "target_language_code", name="uq_message_approved_variants_language"
        ),
    )

    op.create_table(
        "message_occurrences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("occurrence_key", sa.String(length=128), nullable=False),
        sa.Column("occurrence_source", sa.String(length=16), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_event_id", sa.Uuid(), nullable=True),
        sa.Column("source_correlation_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status", sa.String(length=24), server_default="PENDING_FANOUT", nullable=False
        ),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["owner_discord_user_id"],
            ["users.discord_user_id"],
            name="fk_message_occurrences_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["message_campaigns.id"],
            name="fk_message_occurrences_campaign",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "occurrence_source IN ('SCHEDULE','EVENT')", name="ck_message_occurrences_source"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING_FANOUT','CLAIMED','FANNED_OUT','COMPLETED','FAILED')",
            name="ck_message_occurrences_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message_occurrences"),
        sa.UniqueConstraint(
            "campaign_id", "occurrence_key", name="uq_message_occurrences_key"
        ),
    )

    for table in (
        "message_campaigns",
        "message_campaign_schedules",
        "message_campaign_triggers",
        "message_glossary_entries",
        "message_approved_variants",
        "message_occurrences",
    ):
        _owner_rls(table)
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO did_app")

    # ------------------------------------------------------------------
    # Guild tenant-scoped tables: authorized destinations, event source
    # bindings, dedup ledger and the actual per-Guild deliveries.
    # ------------------------------------------------------------------
    op.create_table(
        "message_campaign_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("target_kind", sa.String(length=24), nullable=False),
        sa.Column("discord_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("translation_group_id", sa.Uuid(), nullable=True),
        sa.Column("translation_publication_mode", sa.String(length=24), nullable=True),
        sa.Column(
            "selected_language_profile_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "authorized_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_message_campaign_targets_installation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["message_campaigns.id"],
            name="fk_message_campaign_targets_campaign",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "translation_group_id"],
            ["translation_groups.guild_id", "translation_groups.id"],
            name="fk_message_campaign_targets_translation_group",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "target_kind IN ('CHANNEL','TRANSLATION_GROUP')",
            name="ck_message_campaign_targets_kind",
        ),
        sa.CheckConstraint(
            "(target_kind = 'CHANNEL' AND discord_channel_id > 0 "
            "AND translation_group_id IS NULL) OR "
            "(target_kind = 'TRANSLATION_GROUP' AND translation_group_id IS NOT NULL "
            "AND discord_channel_id IS NULL)",
            name="ck_message_campaign_targets_shape",
        ),
        sa.CheckConstraint(
            "translation_publication_mode IS NULL OR translation_publication_mode IN "
            "('SOURCE_ONLY','EXISTING_PROVIDER','DID_TRANSLATED_FANOUT','SELECTED_LANGUAGES')",
            name="ck_message_campaign_targets_publication_mode",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message_campaign_targets"),
        sa.UniqueConstraint("guild_id", "id", name="uq_message_campaign_targets_guild_id"),
    )

    op.create_table(
        "message_campaign_trigger_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("trigger_id", sa.Uuid(), nullable=False),
        sa.Column("source_scope_kind", sa.String(length=16), nullable=False),
        sa.Column("discord_resource_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "authorized_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_message_campaign_trigger_sources_installation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_id"],
            ["message_campaign_triggers.id"],
            name="fk_message_campaign_trigger_sources_trigger",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "source_scope_kind IN ('GUILD','CHANNEL','CATEGORY')",
            name="ck_message_campaign_trigger_sources_kind",
        ),
        sa.CheckConstraint(
            "(source_scope_kind = 'GUILD' AND discord_resource_id IS NULL) OR "
            "(source_scope_kind IN ('CHANNEL','CATEGORY') AND discord_resource_id > 0)",
            name="ck_message_campaign_trigger_sources_shape",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message_campaign_trigger_sources"),
        sa.UniqueConstraint(
            "guild_id",
            "trigger_id",
            "source_scope_kind",
            "discord_resource_id",
            name="uq_message_campaign_trigger_sources_binding",
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_message_campaign_trigger_sources_guild "
        "ON message_campaign_trigger_sources (guild_id, trigger_id) "
        "WHERE source_scope_kind = 'GUILD'"
    )

    op.create_table(
        "message_campaign_trigger_consumptions",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("trigger_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("occurrence_id", sa.Uuid(), nullable=True),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_message_campaign_trigger_consumptions_installation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_id"],
            ["message_campaign_triggers.id"],
            name="fk_message_campaign_trigger_consumptions_trigger",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "guild_id", "trigger_id", "event_id", name="pk_message_campaign_trigger_consumptions"
        ),
    )

    op.create_table(
        "message_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("occurrence_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("language_profile_id", sa.Uuid(), nullable=True),
        sa.Column("delivery_key", sa.String(length=128), nullable=False),
        sa.Column("discord_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="PENDING", nullable=False),
        sa.Column("discord_message_id", sa.BigInteger(), nullable=True),
        sa.Column("discord_nonce", sa.String(length=64), nullable=True),
        sa.Column("content_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "allowed_mentions_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_message_deliveries_installation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["message_campaigns.id"],
            name="fk_message_deliveries_campaign",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["occurrence_id"],
            ["message_occurrences.id"],
            name="fk_message_deliveries_occurrence",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "target_id"],
            ["message_campaign_targets.guild_id", "message_campaign_targets.id"],
            name="fk_message_deliveries_target",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("discord_channel_id > 0", name="ck_message_deliveries_channel"),
        sa.CheckConstraint(
            "status IN "
            "('PENDING','CLAIMED','SENDING','SENT','FAILED','UNKNOWN','INTERVENTION_REQUIRED')",
            name="ck_message_deliveries_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_message_deliveries_attempt_count"),
        sa.PrimaryKeyConstraint("id", name="pk_message_deliveries"),
        sa.UniqueConstraint(
            "guild_id", "delivery_key", name="uq_message_deliveries_delivery_key"
        ),
    )

    for table in (
        "message_campaign_targets",
        "message_campaign_trigger_sources",
        "message_campaign_trigger_consumptions",
        "message_deliveries",
    ):
        _guild_rls(table)
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO did_app")


def downgrade() -> None:
    op.drop_table("message_deliveries")
    op.drop_table("message_campaign_trigger_consumptions")
    op.execute(
        "DROP INDEX IF EXISTS uq_message_campaign_trigger_sources_guild"
    )
    op.drop_table("message_campaign_trigger_sources")
    op.drop_table("message_campaign_targets")
    op.drop_table("message_occurrences")
    op.drop_table("message_approved_variants")
    op.execute("DROP INDEX IF EXISTS uq_message_glossary_entries_term")
    op.drop_table("message_glossary_entries")
    op.drop_table("message_campaign_triggers")
    op.drop_table("message_campaign_schedules")
    op.drop_table("message_campaigns")
