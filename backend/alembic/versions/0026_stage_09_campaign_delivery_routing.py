"""Stage 09: durable campaign-delivery routing discovery for the shared
worker runtime.

Revision ID: 0026_stage_09
Revises: 0025_stage_09

External-review finding: did.campaigns.activation.fan_out_occurrence
creates message_deliveries rows, but nothing durably guaranteed the shared
Stage01-08 discord_io_jobs worker runtime would ever discover and execute
them -- a process crash between create_delivery's commit and an in-memory
governor submission could silently strand a delivery forever. This mirrors
0004_stage_03's runtime_job_guilds/runtime_outbox_guilds/
runtime_reconcile_guilds pattern exactly: a SECURITY DEFINER, guild-id-only
cross-tenant discovery function, re-opened under RLS for every subsequent
read. Combined with the durable discord_io_jobs enqueue's own
UNIQUE(guild_id, logical_key) coalescing (logical_key = the delivery id
itself), a repeated routing sweep is always a safe, cheap no-op once a
delivery already has a live job -- the actual crash-recovery mechanism is
"call this sweep again", not a bespoke reconciliation state machine.

Also widens ``ck_discord_io_jobs_priority`` (0003_stage_03) from
``BETWEEN 0 AND 5`` to ``BETWEEN 0 AND 6``: a real defect this pass's own
integration testing caught -- ``WorkloadPriority.SEND_CAMPAIGN_MESSAGE``
(value 6, added in an earlier Stage09 pass for the in-memory Governor path)
had never actually been inserted into the durable ``discord_io_jobs`` table
until this pass tried to durably enqueue one, at which point the original
Stage03-era CHECK constraint -- written before Stage09's priority tier
existed -- rejected every such row outright.
"""

from alembic import op

revision: str = "0026_stage_09"
down_revision: str | None = "0025_stage_09"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("ck_discord_io_jobs_priority", "discord_io_jobs", type_="check")
    op.create_check_constraint(
        "ck_discord_io_jobs_priority", "discord_io_jobs", "priority BETWEEN 0 AND 6"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.runtime_campaign_delivery_guilds(p_limit integer DEFAULT 256)
        RETURNS TABLE(guild_id bigint)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT deliveries.guild_id
            FROM message_deliveries AS deliveries
            JOIN guild_installations AS installations
              ON installations.guild_id = deliveries.guild_id
            WHERE installations.installation_status IN ('ACTIVE', 'DEGRADED', 'PENDING_SETUP')
              AND deliveries.status = 'PENDING'
              AND NOT EXISTS (
                    SELECT 1 FROM discord_io_jobs AS jobs
                    WHERE jobs.guild_id = deliveries.guild_id
                      AND jobs.logical_key = deliveries.id::text
                      AND jobs.status IN ('PENDING', 'LEASED')
                  )
            GROUP BY deliveries.guild_id
            ORDER BY min(deliveries.created_at), deliveries.guild_id
            LIMIT LEAST(GREATEST(p_limit, 1), 1000)
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.runtime_campaign_delivery_guilds(integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.runtime_campaign_delivery_guilds(integer) TO did_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.runtime_campaign_delivery_guilds(integer)")
    op.drop_constraint("ck_discord_io_jobs_priority", "discord_io_jobs", type_="check")
    op.create_check_constraint(
        "ck_discord_io_jobs_priority", "discord_io_jobs", "priority BETWEEN 0 AND 5"
    )
