"""Restore structured audit links required by the reference architecture.

The Stage 03 audit table predates the Stage 05 plan engine and was created without
plan_id / operation_id / request_id columns.  Later plan code preserved plan and
operation identifiers inside data_json, while the dashboard audit reader expected
a real plan_id column.  A live Phase 2 acceptance run therefore failed with
UndefinedColumnError on /api/v1/guilds/{guild_id}/audit.

This migration adds the nullable structured columns, backfills UUID values already
preserved in data_json, and installs a small compatibility trigger so legacy audit
writers that still put these identifiers only in data_json continue to populate the
structured fields.  Existing audit payloads remain unchanged.

Revision ID: 0035_ui_phase2
Revises: 0034_stage_10
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0035_ui_phase2"
down_revision: str | None = "0034_stage_10"
branch_labels: str | None = None
depends_on: str | None = None

_UUID_RE = (
    "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    "[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def upgrade() -> None:
    op.add_column("internal_audit_events", sa.Column("plan_id", sa.Uuid(), nullable=True))
    op.add_column("internal_audit_events", sa.Column("operation_id", sa.Uuid(), nullable=True))
    op.add_column("internal_audit_events", sa.Column("request_id", sa.Uuid(), nullable=True))

    # Stage 05 already preserved these identifiers inside data_json.  Recover them
    # without touching malformed / non-UUID historical values.
    op.execute(
        f"""
        UPDATE internal_audit_events
        SET plan_id = (data_json->>'plan_id')::uuid
        WHERE plan_id IS NULL
          AND data_json ? 'plan_id'
          AND COALESCE(data_json->>'plan_id', '') ~ '{_UUID_RE}'
        """
    )
    op.execute(
        f"""
        UPDATE internal_audit_events
        SET operation_id = (data_json->>'operation_id')::uuid
        WHERE operation_id IS NULL
          AND data_json ? 'operation_id'
          AND COALESCE(data_json->>'operation_id', '') ~ '{_UUID_RE}'
        """
    )
    op.execute(
        f"""
        UPDATE internal_audit_events
        SET request_id = (data_json->>'request_id')::uuid
        WHERE request_id IS NULL
          AND data_json ? 'request_id'
          AND COALESCE(data_json->>'request_id', '') ~ '{_UUID_RE}'
        """
    )

    op.create_index(
        "ix_audit_guild_plan",
        "internal_audit_events",
        ["guild_id", "plan_id"],
        postgresql_where=sa.text("plan_id IS NOT NULL"),
    )
    op.create_index(
        "ix_audit_guild_operation",
        "internal_audit_events",
        ["guild_id", "operation_id"],
        postgresql_where=sa.text("operation_id IS NOT NULL"),
    )

    # Keep old writers compatible while progressively moving callers to explicit
    # structured columns.  Explicit values always win over data_json fallbacks.
    op.execute(
        f"""
        CREATE FUNCTION app.populate_internal_audit_links() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
        BEGIN
          IF NEW.plan_id IS NULL
             AND COALESCE(NEW.data_json->>'plan_id', '') ~ '{_UUID_RE}' THEN
            NEW.plan_id := (NEW.data_json->>'plan_id')::uuid;
          END IF;
          IF NEW.operation_id IS NULL
             AND COALESCE(NEW.data_json->>'operation_id', '') ~ '{_UUID_RE}' THEN
            NEW.operation_id := (NEW.data_json->>'operation_id')::uuid;
          END IF;
          IF NEW.request_id IS NULL
             AND COALESCE(NEW.data_json->>'request_id', '') ~ '{_UUID_RE}' THEN
            NEW.request_id := (NEW.data_json->>'request_id')::uuid;
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_internal_audit_links BEFORE INSERT OR UPDATE OF data_json,"
        "plan_id,operation_id,request_id ON internal_audit_events FOR EACH ROW "
        "EXECUTE FUNCTION app.populate_internal_audit_links()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_internal_audit_links ON internal_audit_events")
    op.execute("DROP FUNCTION IF EXISTS app.populate_internal_audit_links()")
    op.drop_index("ix_audit_guild_operation", table_name="internal_audit_events")
    op.drop_index("ix_audit_guild_plan", table_name="internal_audit_events")
    op.drop_column("internal_audit_events", "request_id")
    op.drop_column("internal_audit_events", "operation_id")
    op.drop_column("internal_audit_events", "plan_id")
