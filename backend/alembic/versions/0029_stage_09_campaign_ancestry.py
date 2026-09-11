"""Stage 09: producing-side campaign event ancestry (REQ-MSG-030).

Revision ID: 0029_stage_09
Revises: 0028_stage_09

did.campaigns.causality.with_campaign_ancestry/read_campaign_ancestry
already implement the CONSUMING side's ancestor-loop guard (should_trigger
refuses to fire when its own campaign_id is already present in an event's
did_campaign_ancestry payload), but nothing ever called with_campaign_ancestry
to durably record which campaign(s) causally led to a given occurrence --
so there was no way, when the message that occurrence sent later re-enters
Gateway ingestion as its own MESSAGE_CREATE, to know what ancestry set (or
causation depth) to attach to the resulting event before evaluating it
against triggers.

message_occurrences gains two columns, populated at occurrence-creation time
(did.campaigns.scheduler_loop/event_consumer/api.stage09.activate_campaign):

* source_causation_depth: the causation_depth of whatever caused this
  occurrence (0 for a SCHEDULE/IMMEDIATE-fired occurrence, which is its own
  causal root; the causing event's own causation_depth for an EVENT-sourced
  one). The occurrence's own resulting Discord message, if any, causes an
  event one hop deeper than this.
* source_ancestry: the full set of campaign ids that causally contributed to
  this occurrence -- always includes the occurrence's own campaign_id, plus
  (for an EVENT-sourced occurrence) everything already in the causing
  event's own ancestry.

Both are read back by did.campaigns.event_transport when a Gateway
MESSAGE_CREATE authored by the bot itself is durably correlated (by exact
guild_id/discord_channel_id/discord_message_id) to the SENT message_deliveries
row it came from, to correctly tag the resulting derived event before any
trigger evaluation -- see event_transport.py's own module docstring for the
full correlation/deferral design (no new table is needed for that: an
as-yet-unresolved recent bot-authored MESSAGE_CREATE simply is not advanced
past by the existing per-Guild event cursor until it resolves or ages out,
which is already fully durable and restart-safe on its own).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_stage_09"
down_revision: str | None = "0028_stage_09"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "message_occurrences",
        sa.Column("source_causation_depth", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "message_occurrences",
        sa.Column(
            "source_ancestry",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_message_occurrences_source_causation_depth",
        "message_occurrences",
        "source_causation_depth >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_message_occurrences_source_causation_depth",
        "message_occurrences",
        type_="check",
    )
    op.drop_column("message_occurrences", "source_ancestry")
    op.drop_column("message_occurrences", "source_causation_depth")
