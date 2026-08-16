"""Add bounded tenant-safe routing discovery for the Stage 03 runtimes.

Revision ID: 0004_stage_03
Revises: 0003_stage_03
"""

from alembic import op

revision: str = "0004_stage_03"
down_revision: str | None = "0003_stage_03"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # These SECURITY DEFINER functions are the only cross-tenant reads granted to the
    # application role.  They return guild identifiers only; all data access that
    # follows is reopened under app.current_guild_id and remains protected by RLS.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.runtime_job_guilds(p_limit integer DEFAULT 256)
        RETURNS TABLE(guild_id bigint)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT jobs.guild_id
            FROM discord_io_jobs AS jobs
            JOIN guild_installations AS installations
              ON installations.guild_id = jobs.guild_id
            WHERE installations.installation_status IN ('ACTIVE', 'DEGRADED', 'PENDING_SETUP')
              AND jobs.available_at <= now()
              AND (
                    jobs.status = 'PENDING'
                    OR (jobs.status = 'LEASED' AND jobs.leased_until < now())
                  )
            GROUP BY jobs.guild_id
            ORDER BY min(jobs.priority), min(jobs.available_at), jobs.guild_id
            LIMIT LEAST(GREATEST(p_limit, 1), 1000)
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.runtime_outbox_guilds(p_limit integer DEFAULT 256)
        RETURNS TABLE(guild_id bigint)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT outbox.guild_id
            FROM discord_outbox AS outbox
            WHERE outbox.status = 'PENDING'
              AND outbox.next_attempt_at <= now()
            GROUP BY outbox.guild_id
            ORDER BY min(outbox.next_attempt_at), outbox.guild_id
            LIMIT LEAST(GREATEST(p_limit, 1), 1000)
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.runtime_reconcile_guilds(p_limit integer DEFAULT 256)
        RETURNS TABLE(guild_id bigint)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT installations.guild_id
            FROM guild_installations AS installations
            LEFT JOIN discord_reconcile_checkpoints AS checkpoints
              ON checkpoints.guild_id = installations.guild_id
             AND checkpoints.resource_type = 'STRUCTURE'
            LEFT JOIN discord_cache_coverage AS coverage
              ON coverage.guild_id = installations.guild_id
            WHERE installations.installation_status IN ('ACTIVE', 'DEGRADED', 'PENDING_SETUP')
            ORDER BY
                CASE WHEN coverage.coverage_mode = 'DEGRADED' THEN 0 ELSE 1 END,
                checkpoints.last_success_at NULLS FIRST,
                installations.guild_id
            LIMIT LEAST(GREATEST(p_limit, 1), 1000)
        $$
        """
    )
    for function_name in (
        "runtime_job_guilds(integer)",
        "runtime_outbox_guilds(integer)",
        "runtime_reconcile_guilds(integer)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION app.{function_name} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{function_name} TO did_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app.runtime_reconcile_guilds(integer)")
    op.execute("DROP FUNCTION IF EXISTS app.runtime_outbox_guilds(integer)")
    op.execute("DROP FUNCTION IF EXISTS app.runtime_job_guilds(integer)")
