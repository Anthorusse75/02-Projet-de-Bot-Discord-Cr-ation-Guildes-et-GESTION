import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from did.infrastructure.database import create_database_engine, create_session_factory
from did.infrastructure.runtime_repository import RuntimeRepository

pytestmark = pytest.mark.integration

APP_URL = os.environ.get(
    "DID_DATABASE_URL",
    "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test",
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_ID = 920202020202020201


async def test_phase02_audit_reader_uses_migrated_structured_plan_link() -> None:
    """Regression for the live /audit UndefinedColumnError found during Phase 2."""
    plan_id = uuid4()
    operation_id = uuid4()
    event_id = uuid4()
    correlation_id = uuid4()

    admin = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with admin.begin() as connection:
            await connection.execute(
                text("DELETE FROM guild_installations WHERE guild_id=:guild_id"),
                {"guild_id": GUILD_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO guild_installations (guild_id,name,installation_status) "
                    "VALUES (:guild_id,'Phase 2 Audit Guild','ACTIVE')"
                ),
                {"guild_id": GUILD_ID},
            )
            # Deliberately use the legacy Stage 05 write shape: plan/operation links
            # exist only inside data_json.  Migration 0035's compatibility trigger
            # must project them into the structured columns expected by the reader.
            await connection.execute(
                text(
                    "INSERT INTO internal_audit_events "
                    "(id,guild_id,source,event_type,target_type,target_id,correlation_id,"
                    "result_state,data_json,occurred_at) VALUES "
                    "(:id,:guild_id,'DASHBOARD','PLAN_CREATED','PLAN',:target_id,"
                    ":correlation_id,'DRAFT',CAST(:data AS jsonb),:occurred_at)"
                ),
                {
                    "id": event_id,
                    "guild_id": GUILD_ID,
                    "target_id": str(plan_id),
                    "correlation_id": correlation_id,
                    "data": json.dumps(
                        {"plan_id": str(plan_id), "operation_id": str(operation_id)}
                    ),
                    "occurred_at": datetime.now(UTC),
                },
            )
            linked = (
                (
                    await connection.execute(
                        text(
                            "SELECT plan_id,operation_id FROM internal_audit_events "
                            "WHERE id=:id"
                        ),
                        {"id": event_id},
                    )
                )
                .mappings()
                .one()
            )
            assert linked["plan_id"] == plan_id
            assert linked["operation_id"] == operation_id
    finally:
        await admin.dispose()

    engine = create_database_engine(APP_URL, pool_size=1)
    try:
        repository = RuntimeRepository(create_session_factory(engine))
        rows = await repository.audit_events(GUILD_ID, limit=10)
        row = next(item for item in rows if item["id"] == event_id)
        assert row["plan_id"] == plan_id
        assert row["correlation_id"] == correlation_id
    finally:
        await engine.dispose()
