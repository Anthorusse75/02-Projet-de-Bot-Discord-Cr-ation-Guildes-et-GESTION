from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from did.infrastructure.database import create_database_engine

pytestmark = [pytest.mark.integration, pytest.mark.security]
APP_URL = os.environ.get(
    "DID_DATABASE_URL", "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)


async def test_catalog_is_public_read_only_for_the_application_role() -> None:
    admin = create_database_engine(ADMIN_URL, pool_size=1)
    app = create_database_engine(APP_URL, pool_size=1)
    try:
        async with admin.begin() as connection:
            await connection.execute(text("DELETE FROM ui_locale_packs"))
            await connection.execute(text("DELETE FROM ui_catalog_versions"))
            await connection.execute(
                text(
                    "INSERT INTO ui_catalog_versions "
                    "(catalog_version,key_manifest_json,key_count,content_hash) "
                    "VALUES ('test-v1','{\"hello\":[]}',1,:hash)"
                ),
                {"hash": "a" * 64},
            )
        async with app.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT key_count FROM ui_catalog_versions WHERE catalog_version='test-v1'"
                    )
                )
                == 1
            )
            with pytest.raises(DBAPIError):
                await connection.execute(
                    text("DELETE FROM ui_catalog_versions WHERE catalog_version='test-v1'")
                )
    finally:
        await app.dispose()
        await admin.dispose()
