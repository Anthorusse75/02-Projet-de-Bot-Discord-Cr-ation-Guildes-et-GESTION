import os

import pytest
from sqlalchemy import text

from did.infrastructure.database import create_database_engine

pytestmark = [pytest.mark.integration, pytest.mark.security]

ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)


async def test_every_tenant_or_owner_scoped_table_forces_rls_and_app_role_cannot_bypass() -> None:
    engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with engine.connect() as connection:
            tables = (
                (
                    await connection.execute(
                        text(
                            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                            "(SELECT count(*) FROM pg_policies p "
                            " WHERE p.schemaname='public' AND p.tablename=c.relname) "
                            "AS policy_count "
                            "FROM pg_class c "
                            "JOIN pg_namespace n ON n.oid=c.relnamespace "
                            "JOIN pg_attribute a ON a.attrelid=c.oid "
                            " AND a.attnum>0 AND NOT a.attisdropped "
                            "WHERE n.nspname='public' AND c.relkind='r' "
                            "GROUP BY c.relname,c.relrowsecurity,c.relforcerowsecurity "
                            "HAVING bool_or(a.attname IN "
                            " ('guild_id','owner_discord_user_id','actor_discord_user_id')) "
                            "ORDER BY c.relname"
                        )
                    )
                )
                .mappings()
                .all()
            )
            app_role = (
                await connection.execute(
                    text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='did_app'")
                )
            ).one()

        assert len(tables) >= 60
        assert not [
            row["relname"]
            for row in tables
            if not row["relrowsecurity"]
            or not row["relforcerowsecurity"]
            or int(row["policy_count"]) < 1
        ]
        assert app_role == (False, False)
    finally:
        await engine.dispose()
