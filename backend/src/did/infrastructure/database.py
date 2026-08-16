from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from did.tenancy.context import TenantContext


def create_database_engine(database_url: str, *, pool_size: int = 5) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=0,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def apply_rls_context(
    session: AsyncSession,
    context: TenantContext | None,
) -> None:
    """Apply transaction-local GUCs; blank values are deliberately fail-closed."""
    guild_id = "" if context is None else str(context.guild_id)
    user_id = "" if context is None or context.user_id is None else str(context.user_id)
    await session.execute(
        text("SELECT set_config('app.current_guild_id', :guild_id, true)"),
        {"guild_id": guild_id},
    )
    await session.execute(
        text("SELECT set_config('app.current_user_id', :user_id, true)"),
        {"user_id": user_id},
    )


@asynccontextmanager
async def tenant_transaction(
    factory: async_sessionmaker[AsyncSession],
    context: TenantContext | None,
) -> AsyncIterator[AsyncSession]:
    """Open a short transaction with an explicit, transaction-local RLS context."""
    async with factory() as session, session.begin():
        await apply_rls_context(session, context)
        yield session


async def database_is_ready(engine: AsyncEngine) -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:  # readiness translates backend failures to a boolean
        return False
