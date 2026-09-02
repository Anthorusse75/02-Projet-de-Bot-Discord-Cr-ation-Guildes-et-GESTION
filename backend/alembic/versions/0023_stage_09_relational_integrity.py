"""Stage 09 remediation: composite ownership/campaign FKs, delivery lease
fencing, and a naive-local schedule cursor column.

Revision ID: 0023_stage_09
Revises: 0022_stage_09

External-review findings addressed:
- an owner-scoped child row (schedule/trigger/glossary/approved variant/
  occurrence) could previously reference a campaign owned by a DIFFERENT
  user: only a plain FK to message_campaigns.id existed, with no proof the
  child's own owner_discord_user_id matched that campaign's real owner.
- a delivery's campaign_id was not proven to match its target's campaign_id
  or its occurrence's campaign_id -- only guild_id was proven consistent
  via the existing (guild_id, target_id) composite FK.
- message_deliveries had no lease fields at all, so claim_next_delivery's
  ``lease_owner`` parameter was silently discarded.
- message_campaign_schedules.last_cursor_at was TIMESTAMPTZ (absolute
  instant) while did.campaigns.scheduling treats it as a naive local
  civil-time cursor alongside ``starts_at`` -- a real aware/naive mismatch.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0023_stage_09"
down_revision: str | None = "0022_stage_09"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Composite unique targets needed by the new composite FKs below.
    # ------------------------------------------------------------------
    op.create_unique_constraint(
        "uq_message_campaigns_owner_id", "message_campaigns", ["owner_discord_user_id", "id"]
    )
    op.create_unique_constraint(
        "uq_message_occurrences_campaign_id", "message_occurrences", ["campaign_id", "id"]
    )
    op.create_unique_constraint(
        "uq_message_campaign_targets_guild_campaign_id",
        "message_campaign_targets",
        ["guild_id", "campaign_id", "id"],
    )

    # ------------------------------------------------------------------
    # Replace plain campaign_id FKs with composite (owner, campaign_id) FKs
    # on every owner-scoped child table -- a child's own
    # owner_discord_user_id must now provably match its campaign's real
    # owner; Postgres MATCH SIMPLE lets a NULL campaign_id (GLOBAL_USER
    # glossary scope) bypass the check, which is the intended behavior.
    # ------------------------------------------------------------------
    op.drop_constraint(
        "fk_message_campaign_schedules_campaign", "message_campaign_schedules", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_message_campaign_schedules_owner_campaign",
        "message_campaign_schedules",
        "message_campaigns",
        ["owner_discord_user_id", "campaign_id"],
        ["owner_discord_user_id", "id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "fk_message_campaign_triggers_campaign", "message_campaign_triggers", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_message_campaign_triggers_owner_campaign",
        "message_campaign_triggers",
        "message_campaigns",
        ["owner_discord_user_id", "campaign_id"],
        ["owner_discord_user_id", "id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "fk_message_glossary_entries_campaign", "message_glossary_entries", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_message_glossary_entries_owner_campaign",
        "message_glossary_entries",
        "message_campaigns",
        ["owner_discord_user_id", "campaign_id"],
        ["owner_discord_user_id", "id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "fk_message_approved_variants_campaign", "message_approved_variants", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_message_approved_variants_owner_campaign",
        "message_approved_variants",
        "message_campaigns",
        ["owner_discord_user_id", "campaign_id"],
        ["owner_discord_user_id", "id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("fk_message_occurrences_campaign", "message_occurrences", type_="foreignkey")
    op.create_foreign_key(
        "fk_message_occurrences_owner_campaign",
        "message_occurrences",
        "message_campaigns",
        ["owner_discord_user_id", "campaign_id"],
        ["owner_discord_user_id", "id"],
        ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # message_deliveries: prove campaign_id matches BOTH its target's and
    # its occurrence's campaign_id, not only that guild_id matches.
    # ------------------------------------------------------------------
    op.drop_constraint("fk_message_deliveries_target", "message_deliveries", type_="foreignkey")
    op.create_foreign_key(
        "fk_message_deliveries_target_campaign",
        "message_deliveries",
        "message_campaign_targets",
        ["guild_id", "campaign_id", "target_id"],
        ["guild_id", "campaign_id", "id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("fk_message_deliveries_occurrence", "message_deliveries", type_="foreignkey")
    op.create_foreign_key(
        "fk_message_deliveries_occurrence_campaign",
        "message_deliveries",
        "message_occurrences",
        ["campaign_id", "occurrence_id"],
        ["campaign_id", "id"],
        ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # message_deliveries: durable lease fencing (was previously discarded).
    # ------------------------------------------------------------------
    op.add_column(
        "message_deliveries", sa.Column("lease_owner", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "message_deliveries", sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("message_deliveries", sa.Column("lease_token", sa.Uuid(), nullable=True))

    # ------------------------------------------------------------------
    # message_campaign_schedules: split the tz-aware absolute next_fire_at
    # (kept) from a naive-local wall-clock cursor (renamed + retyped).
    # ------------------------------------------------------------------
    op.alter_column(
        "message_campaign_schedules", "last_cursor_at", new_column_name="last_cursor_local"
    )
    op.alter_column(
        "message_campaign_schedules",
        "last_cursor_local",
        type_=sa.DateTime(timezone=False),
        postgresql_using="last_cursor_local AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    op.alter_column(
        "message_campaign_schedules",
        "last_cursor_local",
        type_=sa.DateTime(timezone=True),
        postgresql_using="last_cursor_local AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "message_campaign_schedules", "last_cursor_local", new_column_name="last_cursor_at"
    )

    op.drop_column("message_deliveries", "lease_token")
    op.drop_column("message_deliveries", "leased_until")
    op.drop_column("message_deliveries", "lease_owner")

    op.drop_constraint(
        "fk_message_deliveries_occurrence_campaign", "message_deliveries", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_message_deliveries_occurrence",
        "message_deliveries",
        "message_occurrences",
        ["occurrence_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "fk_message_deliveries_target_campaign", "message_deliveries", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_message_deliveries_target",
        "message_deliveries",
        "message_campaign_targets",
        ["guild_id", "target_id"],
        ["guild_id", "id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "fk_message_occurrences_owner_campaign", "message_occurrences", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_message_occurrences_campaign",
        "message_occurrences",
        "message_campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "fk_message_approved_variants_owner_campaign",
        "message_approved_variants",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_message_approved_variants_campaign",
        "message_approved_variants",
        "message_campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "fk_message_glossary_entries_owner_campaign", "message_glossary_entries", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_message_glossary_entries_campaign",
        "message_glossary_entries",
        "message_campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "fk_message_campaign_triggers_owner_campaign",
        "message_campaign_triggers",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_message_campaign_triggers_campaign",
        "message_campaign_triggers",
        "message_campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "fk_message_campaign_schedules_owner_campaign",
        "message_campaign_schedules",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_message_campaign_schedules_campaign",
        "message_campaign_schedules",
        "message_campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "uq_message_campaign_targets_guild_campaign_id",
        "message_campaign_targets",
        type_="unique",
    )
    op.drop_constraint("uq_message_occurrences_campaign_id", "message_occurrences", type_="unique")
    op.drop_constraint("uq_message_campaigns_owner_id", "message_campaigns", type_="unique")
