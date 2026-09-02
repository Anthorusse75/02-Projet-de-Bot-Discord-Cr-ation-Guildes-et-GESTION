"""Stage 09: REQ-MSG-002 logical group campaign targets.

Revision ID: 0027_stage_09
Revises: 0026_stage_09

External-review finding: REQ-MSG-002 requires a campaign to be able to
target a dashboard logical group (Stage04's own abstraction covering
channels/categories/roles) in addition to a single channel or a Translation
Group, but message_campaign_targets had no such kind and no column for it.
Reuses the existing Stage04 logical_groups table (composite FK on
(guild_id, id), the same pattern already used for translation_group_id)
rather than inventing a parallel Discord hierarchy -- resolution of a
logical group into its current real channels happens at execution time
(did.campaigns.logical_groups.expand_logical_group), never from a snapshot
taken when the target was created.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0027_stage_09"
down_revision: str | None = "0026_stage_09"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "message_campaign_targets",
        sa.Column("logical_group_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_message_campaign_targets_logical_group",
        "message_campaign_targets",
        "logical_groups",
        ["guild_id", "logical_group_id"],
        ["guild_id", "id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "ck_message_campaign_targets_kind", "message_campaign_targets", type_="check"
    )
    op.create_check_constraint(
        "ck_message_campaign_targets_kind",
        "message_campaign_targets",
        "target_kind IN ('CHANNEL','TRANSLATION_GROUP','LOGICAL_GROUP')",
    )
    op.drop_constraint(
        "ck_message_campaign_targets_shape", "message_campaign_targets", type_="check"
    )
    op.create_check_constraint(
        "ck_message_campaign_targets_shape",
        "message_campaign_targets",
        "(target_kind = 'CHANNEL' AND discord_channel_id > 0 "
        "AND translation_group_id IS NULL AND logical_group_id IS NULL) OR "
        "(target_kind = 'TRANSLATION_GROUP' AND translation_group_id IS NOT NULL "
        "AND discord_channel_id IS NULL AND logical_group_id IS NULL) OR "
        "(target_kind = 'LOGICAL_GROUP' AND logical_group_id IS NOT NULL "
        "AND discord_channel_id IS NULL AND translation_group_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_message_campaign_targets_shape", "message_campaign_targets", type_="check"
    )
    op.create_check_constraint(
        "ck_message_campaign_targets_shape",
        "message_campaign_targets",
        "(target_kind = 'CHANNEL' AND discord_channel_id > 0 "
        "AND translation_group_id IS NULL) OR "
        "(target_kind = 'TRANSLATION_GROUP' AND translation_group_id IS NOT NULL "
        "AND discord_channel_id IS NULL)",
    )
    op.drop_constraint(
        "ck_message_campaign_targets_kind", "message_campaign_targets", type_="check"
    )
    op.create_check_constraint(
        "ck_message_campaign_targets_kind",
        "message_campaign_targets",
        "target_kind IN ('CHANNEL','TRANSLATION_GROUP')",
    )
    op.drop_constraint(
        "fk_message_campaign_targets_logical_group", "message_campaign_targets", type_="foreignkey"
    )
    op.drop_column("message_campaign_targets", "logical_group_id")
