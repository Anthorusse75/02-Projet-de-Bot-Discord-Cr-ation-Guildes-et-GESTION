"""Bootstrap tenant context, application role, and RLS canary.

Revision ID: 0001_stage_01
Revises: None
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0001_stage_01"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'did_app') THEN
                CREATE ROLE did_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$
        """
    )
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.current_guild_id()
        RETURNS bigint
        LANGUAGE sql
        STABLE
        AS $$
            SELECT NULLIF(current_setting('app.current_guild_id', true), '')::bigint
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.current_user_id()
        RETURNS bigint
        LANGUAGE sql
        STABLE
        AS $$
            SELECT NULLIF(current_setting('app.current_user_id', true), '')::bigint
        $$
        """
    )
    op.create_table(
        "tenant_canaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_canaries"),
        sa.UniqueConstraint("guild_id", "label", name="uq_tenant_canaries_guild_label"),
    )
    op.execute("ALTER TABLE tenant_canaries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_canaries FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_canaries_isolation ON tenant_canaries
        USING (guild_id = app.current_guild_id())
        WITH CHECK (guild_id = app.current_guild_id())
        """
    )
    op.execute("REVOKE ALL ON SCHEMA app FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA app, public TO did_app")
    op.execute("GRANT EXECUTE ON FUNCTION app.current_guild_id() TO did_app")
    op.execute("GRANT EXECUTE ON FUNCTION app.current_user_id() TO did_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_canaries TO did_app")


def downgrade() -> None:
    op.drop_table("tenant_canaries")
    op.execute("DROP FUNCTION IF EXISTS app.current_user_id()")
    op.execute("DROP FUNCTION IF EXISTS app.current_guild_id()")
    op.execute("DROP SCHEMA IF EXISTS app")
