"""Allow tenant purge to erase plan snapshot evidence for the deleted Guild only.

The plan_snapshots append-only guard (0009_stage_05_hardening) unconditionally blocks
UPDATE and DELETE, including a DELETE cascaded from removing the parent
guild_installations row. That made REQ-DATA-002 tenant purge fail with
"plan snapshots are append-only" whenever the Guild had ever compiled a plan.

This migration narrows the guard: DELETE is now permitted only while the
transaction-local GUC app.tenant_purge_in_progress is set to 'on' (mirrors the
existing app.current_guild_id / app.current_user_id RLS GUC convention in
did.infrastructure.database.apply_rls_context). UPDATE remains unconditionally
blocked in every case -- evidence can be erased as a whole with its tenant, never
silently rewritten. No application code path other than
AuthRepository.delete_tenant() ever sets this GUC.

Revision ID: 0034_stage_10
Revises: 0033_stage_10
"""

from alembic import op

revision: str = "0034_stage_10"
down_revision: str | None = "0033_stage_10"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("DROP TRIGGER trg_plan_snapshots_append_only ON plan_snapshots")
    op.execute("DROP FUNCTION app.guard_plan_snapshot_append_only()")
    op.execute(
        """
        CREATE FUNCTION app.guard_plan_snapshot_append_only() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND
             current_setting('app.tenant_purge_in_progress', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'plan snapshots are append-only' USING ERRCODE='23514';
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_plan_snapshots_append_only BEFORE UPDATE OR DELETE "
        "ON plan_snapshots FOR EACH ROW EXECUTE FUNCTION app.guard_plan_snapshot_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_plan_snapshots_append_only ON plan_snapshots")
    op.execute("DROP FUNCTION app.guard_plan_snapshot_append_only()")
    op.execute(
        """
        CREATE FUNCTION app.guard_plan_snapshot_append_only() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
        BEGIN
          RAISE EXCEPTION 'plan snapshots are append-only' USING ERRCODE='23514';
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_plan_snapshots_append_only BEFORE UPDATE OR DELETE "
        "ON plan_snapshots FOR EACH ROW EXECUTE FUNCTION app.guard_plan_snapshot_append_only()"
    )
