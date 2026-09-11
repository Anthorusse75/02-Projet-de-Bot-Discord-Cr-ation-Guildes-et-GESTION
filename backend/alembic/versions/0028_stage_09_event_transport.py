"""Stage 09: real Stage03 event transport for event-triggered campaigns.

Revision ID: 0028_stage_09
Revises: 0027_stage_09

External-review finding: did.campaigns.event_consumer.consume_event_for_trigger
is the real, tested decision function for one (trigger, event) pair, but no
code path ever fed it a real Stage03 event -- there was no durable cursor
over discord_gateway_inbox and no discovery of which Guilds have new
campaign-relevant events. This migration adds exactly that plumbing, for
every event_type Stage03's own gateway client actually captures (structural
dispatches -- GUILD_*/CHANNEL_*/THREAD_*/ROLE_*/MEMBER_* -- under its
minimal-intents architecture, ADR-008). MESSAGE_CREATE and other
message-content-bearing dispatches remain outside Stage03's own capture
surface entirely (no message intent is requested), so an event-triggered
campaign depending on message content stays gated by the existing
REQ-MSG-020 capability/blocker machinery -- this migration does not, and
cannot, change that.

message_campaign_event_cursor durably tracks, per Guild, the last
discord_gateway_inbox row the campaign engine has consumed (by
(received_at, event_id) ordering) -- a crash between reading a batch of
events and advancing the cursor simply means the next tick re-reads the
same batch; did.campaigns.event_consumer's own
message_campaign_trigger_consumptions dedup (WP1) is what makes that
replay safe, not this cursor.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0028_stage_09"
down_revision: str | None = "0027_stage_09"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "message_campaign_event_cursor",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("last_event_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["guild_id"],
            ["guild_installations.guild_id"],
            name="fk_message_campaign_event_cursor_installation",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "(last_event_received_at IS NULL) = (last_event_id IS NULL)",
            name="ck_message_campaign_event_cursor_pair",
        ),
        sa.PrimaryKeyConstraint("guild_id", name="pk_message_campaign_event_cursor"),
    )
    op.execute("ALTER TABLE message_campaign_event_cursor ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE message_campaign_event_cursor FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY message_campaign_event_cursor_tenant_isolation "
        "ON message_campaign_event_cursor "
        "USING (guild_id = app.current_guild_id()) "
        "WITH CHECK (guild_id = app.current_guild_id())"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON message_campaign_event_cursor TO did_app")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.runtime_campaign_event_guilds(p_limit integer DEFAULT 256)
        RETURNS TABLE(guild_id bigint)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT DISTINCT sources.guild_id
            FROM message_campaign_trigger_sources AS sources
            JOIN guild_installations AS installations
              ON installations.guild_id = sources.guild_id
            JOIN discord_gateway_inbox AS inbox
              ON inbox.guild_id = sources.guild_id
            LEFT JOIN message_campaign_event_cursor AS cursor
              ON cursor.guild_id = sources.guild_id
            WHERE installations.installation_status IN ('ACTIVE', 'DEGRADED', 'PENDING_SETUP')
              AND (
                    cursor.last_event_received_at IS NULL
                    OR (inbox.received_at, inbox.event_id)
                       > (cursor.last_event_received_at, cursor.last_event_id)
                  )
            LIMIT LEAST(GREATEST(p_limit, 1), 1000)
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.runtime_campaign_event_guilds(integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.runtime_campaign_event_guilds(integer) TO did_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.runtime_campaign_event_guilds(integer)")
    op.drop_table("message_campaign_event_cursor")
