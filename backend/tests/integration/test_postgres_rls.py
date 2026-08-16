import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from did.infrastructure.database import (
    create_database_engine,
    create_session_factory,
    tenant_transaction,
)
from did.tenancy import TenantContext

pytestmark = pytest.mark.integration

APP_URL = os.environ.get(
    "DID_DATABASE_URL",
    "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test",
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
GUILD_A = 111111111111111111
GUILD_B = 222222222222222222


async def _reset_canaries() -> None:
    admin = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with admin.begin() as connection:
            await connection.execute(text("DELETE FROM tenant_canaries"))
    finally:
        await admin.dispose()


async def _insert(factory: async_sessionmaker[AsyncSession], guild_id: int, label: str) -> None:
    async with tenant_transaction(factory, TenantContext(guild_id=guild_id)) as session:
        await session.execute(
            text(
                "INSERT INTO tenant_canaries (id, guild_id, label) VALUES (:id, :guild_id, :label)"
            ),
            {"id": uuid4(), "guild_id": guild_id, "label": label},
        )


async def test_rls_a_b_and_absent_context_are_fail_closed() -> None:
    await _reset_canaries()
    engine = create_database_engine(APP_URL, pool_size=1)
    factory = create_session_factory(engine)
    try:
        await _insert(factory, GUILD_A, "tenant-a")
        await _insert(factory, GUILD_B, "tenant-b")

        with pytest.raises(DBAPIError):
            async with tenant_transaction(factory, TenantContext(guild_id=GUILD_A)) as session:
                await session.execute(
                    text(
                        "INSERT INTO tenant_canaries (id, guild_id, label) "
                        "VALUES (:id, :guild_id, :label)"
                    ),
                    {"id": uuid4(), "guild_id": GUILD_B, "label": "cross-tenant-denied"},
                )

        async with tenant_transaction(factory, TenantContext(guild_id=GUILD_A)) as session:
            labels_a = (
                (await session.execute(text("SELECT label FROM tenant_canaries"))).scalars().all()
            )
        async with tenant_transaction(factory, TenantContext(guild_id=GUILD_B)) as session:
            labels_b = (
                (await session.execute(text("SELECT label FROM tenant_canaries"))).scalars().all()
            )
        async with tenant_transaction(factory, None) as session:
            labels_without_context = (
                (await session.execute(text("SELECT label FROM tenant_canaries"))).scalars().all()
            )

        assert labels_a == ["tenant-a"]
        assert labels_b == ["tenant-b"]
        assert labels_without_context == []
    finally:
        await engine.dispose()


async def test_pool_reuse_resets_transaction_local_tenant_context() -> None:
    await _reset_canaries()
    engine = create_database_engine(APP_URL, pool_size=1)
    factory = create_session_factory(engine)
    try:
        await _insert(factory, GUILD_A, "only-a")
        async with tenant_transaction(factory, TenantContext(guild_id=GUILD_A)) as session:
            backend_a = await session.scalar(text("SELECT pg_backend_pid()"))
            assert await session.scalar(text("SELECT count(*) FROM tenant_canaries")) == 1
        async with tenant_transaction(factory, TenantContext(guild_id=GUILD_B)) as session:
            backend_b = await session.scalar(text("SELECT pg_backend_pid()"))
            assert await session.scalar(text("SELECT count(*) FROM tenant_canaries")) == 0
        async with tenant_transaction(factory, None) as session:
            backend_none = await session.scalar(text("SELECT pg_backend_pid()"))
            assert await session.scalar(text("SELECT count(*) FROM tenant_canaries")) == 0

        assert backend_a == backend_b == backend_none
    finally:
        await engine.dispose()
