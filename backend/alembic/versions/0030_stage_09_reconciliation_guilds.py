"""Stage 09: durable discovery for delivery reconciliation.

Revision ID: 0030_stage_09
Revises: 0029_stage_09

External-review finding: did.campaigns.delivery_worker
.reconcile_one_stalled_delivery (safe SENDING/UNKNOWN recovery via
did.campaigns.delivery_reconciliation.decide_unknown_outcome_recovery) is a
complete, tested function that no real long-lived process ever called --
exactly the same class of gap 0026_stage_09's runtime_campaign_delivery_guilds
closed for routing. This migration adds the guild-discovery counterpart for
reconciliation specifically, mirroring 0026's SECURITY DEFINER,
guild-id-only cross-tenant pattern: a Guild appears in the result only while
it genuinely has a delivery reconcile_one_stalled_delivery could act on --
a SENDING row stalled well past any realistic Discord round-trip
(STALLED_SENDING_THRESHOLD_SECONDS, did.campaigns.delivery_worker) or an
UNKNOWN row (a released lease with no live worker to race with, no stall
requirement). Re-running the sweep once a Guild's reconcilable deliveries
are all resolved is always a safe, cheap no-op -- it simply drops out of
this list.
"""

from alembic import op

revision: str = "0030_stage_09"
down_revision: str | None = "0029_stage_09"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.runtime_campaign_reconciliation_guilds(
            p_limit integer DEFAULT 256, p_stall_after_seconds double precision DEFAULT 120.0
        )
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
              AND (
                    deliveries.status = 'UNKNOWN'
                    OR (
                        deliveries.status = 'SENDING'
                        AND deliveries.updated_at
                            < now() - make_interval(secs => GREATEST(p_stall_after_seconds, 0))
                    )
                  )
            GROUP BY deliveries.guild_id
            ORDER BY min(deliveries.updated_at), deliveries.guild_id
            LIMIT LEAST(GREATEST(p_limit, 1), 1000)
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION app.runtime_campaign_reconciliation_guilds(integer, double precision) "
        "FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.runtime_campaign_reconciliation_guilds(integer, double precision) "
        "TO did_app"
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS app.runtime_campaign_reconciliation_guilds(integer, double precision)"
    )
