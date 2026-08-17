"""Add the durable Discord runtime, cache, workload and event ledger.

Revision ID: 0003_stage_03
Revises: 0002_stage_02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_stage_03"
down_revision: str | None = "0002_stage_02"
branch_labels: str | None = None
depends_on: str | None = None

OBSERVABILITY_STATES = (
    "VISIBLE",
    "OBFUSCATED",
    "ACCESS_LOST",
    "UNKNOWN",
    "DELETED_CONFIRMED",
    "USER_CONFIRMED_DELETED",
)
FRESHNESS_STATES = ("FRESH", "AGING", "STALE", "UNKNOWN")
COVERAGE_MODES = ("FULL", "PARTIAL", "DEGRADED")
JOB_STATES = ("PENDING", "LEASED", "SUCCEEDED", "FAILED", "CANCELLED")
OUTBOX_STATES = ("PENDING", "PUBLISHED")
INBOX_STATES = ("RECEIVED", "PROJECTED", "REJECTED")


def _check_values(column: str, values: tuple[str, ...], name: str) -> sa.CheckConstraint:
    allowed = ",".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=name)


def _guild_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (guild_id = app.current_guild_id()) "
        "WITH CHECK (guild_id = app.current_guild_id())"
    )


def _installation_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["guild_id"],
        ["guild_installations.guild_id"],
        name=name,
        ondelete="CASCADE",
    )


def upgrade() -> None:
    op.create_table(
        "discord_roles_cache",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("permissions_bits", sa.Numeric(precision=40, scale=0), nullable=False),
        sa.Column("managed", sa.Boolean(), nullable=False),
        sa.Column("color", sa.Integer(), nullable=False),
        sa.Column("hoist", sa.Boolean(), nullable=False),
        sa.Column("mentionable", sa.Boolean(), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_gateway_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_gateway_session_id", sa.String(length=256), nullable=True),
        sa.Column("last_gateway_sequence", sa.BigInteger(), nullable=True),
        sa.Column("last_rest_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_mutation_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "cache_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("role_id > 0", name="ck_discord_roles_cache_role_id"),
        sa.CheckConstraint("position >= 0", name="ck_discord_roles_cache_position"),
        sa.CheckConstraint("permissions_bits >= 0", name="ck_discord_roles_cache_permissions"),
        sa.CheckConstraint("state_version > 0", name="ck_discord_roles_cache_version"),
        _installation_fk("fk_discord_roles_cache_installation"),
        sa.PrimaryKeyConstraint("guild_id", "role_id", name="pk_discord_roles_cache"),
    )
    op.create_table(
        "discord_channels_cache",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("nsfw", sa.Boolean(), nullable=True),
        sa.Column("flags", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_full_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("payload_schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("observability_state", sa.String(length=32), nullable=False),
        sa.Column("is_obfuscated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "freshness_state", sa.String(length=16), server_default="UNKNOWN", nullable=False
        ),
        sa.Column("last_full_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_gateway_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_rest_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_mutation_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_lost_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("obfuscated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("last_gateway_sequence", sa.BigInteger(), nullable=True),
        sa.Column("last_gateway_session_id", sa.String(length=256), nullable=True),
        sa.Column(
            "cache_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        _check_values("observability_state", OBSERVABILITY_STATES, "ck_channels_observability"),
        _check_values("freshness_state", FRESHNESS_STATES, "ck_channels_freshness"),
        sa.CheckConstraint("channel_id > 0", name="ck_discord_channels_cache_channel_id"),
        sa.CheckConstraint("position >= 0", name="ck_discord_channels_cache_position"),
        sa.CheckConstraint("state_version > 0", name="ck_discord_channels_cache_version"),
        sa.CheckConstraint(
            "(is_obfuscated AND observability_state IN ('OBFUSCATED','ACCESS_LOST')) OR "
            "(NOT is_obfuscated)",
            name="ck_channels_obfuscation_state",
        ),
        _installation_fk("fk_discord_channels_cache_installation"),
        sa.PrimaryKeyConstraint("guild_id", "channel_id", name="pk_discord_channels_cache"),
    )
    op.create_table(
        "channel_overwrites_cache",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("target_type", sa.Integer(), nullable=False),
        sa.Column("allow_bits", sa.Numeric(precision=40, scale=0), nullable=False),
        sa.Column("deny_bits", sa.Numeric(precision=40, scale=0), nullable=False),
        sa.Column("last_full_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "cache_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("target_id > 0", name="ck_channel_overwrites_target_id"),
        sa.CheckConstraint("target_type IN (0,1)", name="ck_channel_overwrites_target_type"),
        sa.CheckConstraint("allow_bits >= 0 AND deny_bits >= 0", name="ck_channel_overwrites_bits"),
        sa.ForeignKeyConstraint(
            ["guild_id", "channel_id"],
            ["discord_channels_cache.guild_id", "discord_channels_cache.channel_id"],
            name="fk_channel_overwrites_channel",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "guild_id", "channel_id", "target_id", "target_type", name="pk_channel_overwrites_cache"
        ),
    )
    op.create_table(
        "discord_channel_tombstones",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="PURGED_TOMBSTONE", nullable=False),
        sa.Column("confirmed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_known_parent_id", sa.BigInteger(), nullable=True),
        sa.Column("last_known_type", sa.Integer(), nullable=True),
        sa.Column("last_known_position", sa.Integer(), nullable=True),
        sa.Column("metadata_hash", sa.String(length=64), nullable=True),
        sa.CheckConstraint("state = 'PURGED_TOMBSTONE'", name="ck_channel_tombstones_state"),
        _installation_fk("fk_discord_channel_tombstones_installation"),
        sa.PrimaryKeyConstraint("guild_id", "channel_id", name="pk_discord_channel_tombstones"),
    )
    op.create_table(
        "discord_cache_coverage",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("coverage_mode", sa.String(length=16), nullable=False),
        sa.Column("freshness_state", sa.String(length=16), nullable=False),
        sa.Column("known_channels", sa.Integer(), server_default="0", nullable=False),
        sa.Column("visible_channels", sa.Integer(), server_default="0", nullable=False),
        sa.Column("obfuscated_channels", sa.Integer(), server_default="0", nullable=False),
        sa.Column("known_roles", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_gateway_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_full_reconcile_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_rest_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "gateway_continuity", sa.String(length=32), server_default="CONNECTED", nullable=False
        ),
        sa.Column("state_version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _check_values("coverage_mode", COVERAGE_MODES, "ck_cache_coverage_mode"),
        _check_values("freshness_state", FRESHNESS_STATES, "ck_cache_coverage_freshness"),
        sa.CheckConstraint(
            "known_channels >= 0 AND visible_channels >= 0 AND obfuscated_channels >= 0 "
            "AND known_roles >= 0",
            name="ck_cache_coverage_counts",
        ),
        _installation_fk("fk_discord_cache_coverage_installation"),
        sa.PrimaryKeyConstraint("guild_id", name="pk_discord_cache_coverage"),
    )
    op.create_table(
        "discord_reconcile_checkpoints",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED')", name="ck_reconcile_status"
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_reconcile_attempt_count"),
        _installation_fk("fk_discord_reconcile_installation"),
        sa.PrimaryKeyConstraint(
            "guild_id", "resource_type", name="pk_discord_reconcile_checkpoints"
        ),
    )
    op.create_table(
        "discord_gateway_inbox",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("discord_sequence", sa.BigInteger(), nullable=True),
        sa.Column("discord_session_id", sa.String(length=256), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("causation_id", sa.Uuid(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("causation_depth", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="RECEIVED", nullable=False),
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_code", sa.String(length=64), nullable=True),
        _check_values("status", INBOX_STATES, "ck_gateway_inbox_status"),
        sa.CheckConstraint("schema_version > 0", name="ck_gateway_inbox_schema_version"),
        sa.CheckConstraint("causation_depth BETWEEN 0 AND 32", name="ck_gateway_inbox_depth"),
        _installation_fk("fk_discord_gateway_inbox_installation"),
        sa.PrimaryKeyConstraint("event_id", name="pk_discord_gateway_inbox"),
        sa.UniqueConstraint(
            "guild_id",
            "discord_session_id",
            "discord_sequence",
            "event_type",
            name="uq_gateway_inbox_dispatch",
        ),
    )
    op.create_table(
        "discord_outbox",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("topic", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("causation_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        _check_values("status", OUTBOX_STATES, "ck_discord_outbox_status"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_discord_outbox_attempt_count"),
        _installation_fk("fk_discord_outbox_installation"),
        sa.PrimaryKeyConstraint("event_id", name="pk_discord_outbox"),
    )
    op.create_table(
        "discord_io_jobs",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("workload_type", sa.String(length=64), nullable=False),
        sa.Column("logical_key", sa.String(length=256), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _check_values("status", JOB_STATES, "ck_discord_io_jobs_status"),
        sa.CheckConstraint("priority BETWEEN 0 AND 5", name="ck_discord_io_jobs_priority"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_discord_io_jobs_attempt_count"),
        _installation_fk("fk_discord_io_jobs_installation"),
        sa.PrimaryKeyConstraint("job_id", name="pk_discord_io_jobs"),
    )
    op.create_table(
        "discord_member_authorization_cache",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_user_id", sa.BigInteger(), nullable=False),
        sa.Column("role_ids", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("validity", sa.String(length=16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cache_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "validity IN ('FRESH','STALE','INVALIDATED','UNKNOWN')", name="ck_member_auth_validity"
        ),
        _installation_fk("fk_member_auth_cache_installation"),
        sa.PrimaryKeyConstraint(
            "guild_id", "discord_user_id", name="pk_member_authorization_cache"
        ),
    )
    op.create_table(
        "internal_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("causation_id", sa.Uuid(), nullable=True),
        sa.Column("result_state", sa.String(length=64), nullable=False),
        sa.Column("data_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _installation_fk("fk_internal_audit_events_installation"),
        sa.PrimaryKeyConstraint("id", name="pk_internal_audit_events"),
    )

    op.create_index(
        "ix_roles_cache_guild_position", "discord_roles_cache", ["guild_id", "position"]
    )
    op.create_index(
        "ix_channels_cache_guild_state_type",
        "discord_channels_cache",
        ["guild_id", "observability_state", "type"],
    )
    op.create_index(
        "ix_channels_cache_parent", "discord_channels_cache", ["guild_id", "parent_id", "position"]
    )
    op.create_index(
        "ix_tombstones_reason", "discord_channel_tombstones", ["guild_id", "reason", "purged_at"]
    )
    op.create_index("ix_reconcile_due", "discord_reconcile_checkpoints", ["status", "next_due_at"])
    op.create_index(
        "ix_gateway_inbox_received", "discord_gateway_inbox", ["guild_id", "received_at"]
    )
    op.create_index("ix_outbox_pending", "discord_outbox", ["status", "next_attempt_at"])
    op.create_index(
        "ix_io_jobs_dispatch",
        "discord_io_jobs",
        ["status", "priority", "available_at", "guild_id"],
    )
    op.create_index(
        "uq_io_jobs_active_logical_key",
        "discord_io_jobs",
        ["guild_id", "logical_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING','LEASED')"),
    )
    op.create_index("ix_audit_guild_time", "internal_audit_events", ["guild_id", "created_at"])

    tables = (
        "discord_roles_cache",
        "discord_channels_cache",
        "channel_overwrites_cache",
        "discord_channel_tombstones",
        "discord_cache_coverage",
        "discord_reconcile_checkpoints",
        "discord_gateway_inbox",
        "discord_outbox",
        "discord_io_jobs",
        "discord_member_authorization_cache",
        "internal_audit_events",
    )
    for table in tables:
        _guild_rls(table)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON " + ", ".join(tables) + " TO did_app")


def downgrade() -> None:
    op.drop_index("ix_audit_guild_time", table_name="internal_audit_events")
    op.drop_index("ix_io_jobs_dispatch", table_name="discord_io_jobs")
    op.drop_index("uq_io_jobs_active_logical_key", table_name="discord_io_jobs", if_exists=True)
    op.drop_index("ix_outbox_pending", table_name="discord_outbox")
    op.drop_index("ix_gateway_inbox_received", table_name="discord_gateway_inbox")
    op.drop_index("ix_reconcile_due", table_name="discord_reconcile_checkpoints")
    op.drop_index("ix_tombstones_reason", table_name="discord_channel_tombstones")
    op.drop_index("ix_channels_cache_parent", table_name="discord_channels_cache")
    op.drop_index("ix_channels_cache_guild_state_type", table_name="discord_channels_cache")
    op.drop_index("ix_roles_cache_guild_position", table_name="discord_roles_cache")
    op.drop_table("internal_audit_events")
    op.drop_table("discord_member_authorization_cache")
    op.drop_table("discord_io_jobs")
    op.drop_table("discord_outbox")
    op.drop_table("discord_gateway_inbox")
    op.drop_table("discord_reconcile_checkpoints")
    op.drop_table("discord_cache_coverage")
    op.drop_table("discord_channel_tombstones")
    op.drop_table("channel_overwrites_cache")
    op.drop_table("discord_channels_cache")
    op.drop_table("discord_roles_cache")
