from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class LocalizationRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def active_locales(self, catalog_version: str) -> list[dict[str, Any]]:
        async with self._factory() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT locale_code,display_name,flag_code,direction,"
                            "catalog_version,status,coverage_count,coverage_percent,"
                            "content_hash FROM ui_locale_packs WHERE "
                            "catalog_version=:version AND status='ACTIVE' "
                            "ORDER BY locale_code"
                        ),
                        {"version": catalog_version},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def active_pack(self, locale: str, catalog_version: str) -> dict[str, Any] | None:
        async with self._factory() as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT locale_code,catalog_version,payload_json,content_hash,"
                            "coverage_count,coverage_percent FROM ui_locale_packs WHERE "
                            "locale_code=:locale AND catalog_version=:version "
                            "AND status='ACTIVE'"
                        ),
                        {"locale": locale, "version": catalog_version},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None
