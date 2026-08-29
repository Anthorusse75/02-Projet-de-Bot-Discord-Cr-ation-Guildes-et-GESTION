from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from did.infrastructure.database import tenant_transaction
from did.tenancy import TenantContext


class Stage08NotFound(LookupError):
    pass


class Stage08Conflict(RuntimeError):
    pass


KNOWN_UNIQUENESS_CONSTRAINTS = {
    "uq_language_profiles_code",
    "pk_member_visible_languages",
    "uq_translation_channel_group_key",
    "uq_translation_category_variants_group_language",
    "uq_translation_channel_variants_group_language",
    "uq_translation_routes_group_language_pair",
    "uq_translation_provider_bindings_key",
    "uq_visibility_scope_language_roles_scope_language",
}


def _raise_known_conflict(error: IntegrityError) -> None:
    constraint_name = getattr(error.orig, "constraint_name", None) or getattr(
        getattr(error.orig, "__cause__", None), "constraint_name", None
    )
    if constraint_name in KNOWN_UNIQUENESS_CONSTRAINTS:
        raise Stage08Conflict(f"Stage 08 uniqueness conflict: {constraint_name}") from error
    raise error


async def _execute(session: AsyncSession, statement: Any, parameters: dict[str, Any]) -> Any:
    try:
        return await session.execute(statement, parameters)
    except IntegrityError as error:
        _raise_known_conflict(error)


async def _fetch_one(
    session: AsyncSession, statement: str, parameters: dict[str, Any]
) -> dict[str, Any]:
    try:
        row = (await session.execute(text(statement), parameters)).mappings().one_or_none()
    except IntegrityError as error:
        _raise_known_conflict(error)
    if row is None:
        raise Stage08NotFound("Stage 08 record was not found")
    return dict(row)


class LanguageProfileRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def create(
        self,
        *,
        guild_id: int,
        code: str,
        display_name: str,
        emoji: str | None = None,
        language_id: UUID | None = None,
    ) -> dict[str, Any]:
        record_id = language_id or uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "INSERT INTO language_profiles "
                "(id,guild_id,code,display_name,emoji) "
                "VALUES (:id,:guild_id,:code,:display_name,:emoji) "
                "RETURNING *",
                {
                    "id": record_id,
                    "guild_id": guild_id,
                    "code": code,
                    "display_name": display_name,
                    "emoji": emoji,
                },
            )

    async def list_profiles(
        self, guild_id: int, *, enabled_only: bool = False
    ) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            statement = (
                "SELECT * FROM language_profiles WHERE guild_id=:guild_id AND enabled=true "
                "ORDER BY code"
                if enabled_only
                else "SELECT * FROM language_profiles WHERE guild_id=:guild_id ORDER BY code"
            )
            result = await _execute(
                session,
                text(statement),
                {"guild_id": guild_id},
            )
            return [dict(row) for row in result.mappings().all()]

    async def get_optional(self, guild_id: int, language_id: UUID) -> dict[str, Any] | None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text("SELECT * FROM language_profiles WHERE guild_id=:guild_id AND id=:id"),
                        {"guild_id": guild_id, "id": language_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            return dict(row) if row is not None else None

    async def get(self, guild_id: int, language_id: UUID) -> dict[str, Any]:
        row = await self.get_optional(guild_id, language_id)
        if row is None:
            raise Stage08NotFound("language profile was not found")
        return row

    async def update(
        self,
        *,
        guild_id: int,
        language_id: UUID,
        display_name: str | None,
        emoji: str | None,
        enabled: bool | None,
    ) -> dict[str, Any]:
        if display_name is None and emoji is None and enabled is None:
            return await self.get(guild_id, language_id)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "UPDATE language_profiles SET "
                "display_name=COALESCE(:display_name,display_name), "
                "emoji=CASE WHEN :set_emoji THEN :emoji ELSE emoji END, "
                "enabled=COALESCE(:enabled,enabled), updated_at=now() "
                "WHERE guild_id=:guild_id AND id=:id RETURNING *",
                {
                    "guild_id": guild_id,
                    "id": language_id,
                    "display_name": display_name,
                    "set_emoji": emoji is not None,
                    "emoji": emoji,
                    "enabled": enabled,
                },
            )

    async def remove_member_language(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        language_profile_id: UUID,
    ) -> bool:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await _execute(
                session,
                text(
                    "DELETE FROM member_visible_languages WHERE guild_id=:guild_id "
                    "AND discord_user_id=:user_id AND language_profile_id=:language_id"
                ),
                {
                    "guild_id": guild_id,
                    "user_id": discord_user_id,
                    "language_id": language_profile_id,
                },
            )
            return bool(result.rowcount)

    async def set_member_languages(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        language_profile_ids: Iterable[UUID],
        source: str = "EXPLICIT",
    ) -> None:
        language_ids = tuple(dict.fromkeys(language_profile_ids))
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await _execute(
                session,
                text(
                    "DELETE FROM member_visible_languages "
                    "WHERE guild_id=:guild_id AND discord_user_id=:user_id"
                ),
                {"guild_id": guild_id, "user_id": discord_user_id},
            )
            for language_id in language_ids:
                await _execute(
                    session,
                    text(
                        "INSERT INTO member_visible_languages "
                        "(guild_id,discord_user_id,language_profile_id,source) "
                        "VALUES (:guild_id,:user_id,:language_id,:source)"
                    ),
                    {
                        "guild_id": guild_id,
                        "user_id": discord_user_id,
                        "language_id": language_id,
                        "source": source,
                    },
                )

    async def add_member_language(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        language_profile_id: UUID,
        source: str = "EXPLICIT",
    ) -> None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await _execute(
                session,
                text(
                    "INSERT INTO member_visible_languages "
                    "(guild_id,discord_user_id,language_profile_id,source) "
                    "VALUES (:guild_id,:user_id,:language_id,:source)"
                ),
                {
                    "guild_id": guild_id,
                    "user_id": discord_user_id,
                    "language_id": language_profile_id,
                    "source": source,
                },
            )

    async def member_languages(self, guild_id: int, discord_user_id: int) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await _execute(
                session,
                text(
                    "SELECT mvl.*,lp.code,lp.display_name,lp.enabled "
                    "FROM member_visible_languages mvl JOIN language_profiles lp "
                    "ON lp.guild_id=mvl.guild_id AND lp.id=mvl.language_profile_id "
                    "WHERE mvl.guild_id=:guild_id AND mvl.discord_user_id=:user_id "
                    "ORDER BY lp.code"
                ),
                {"guild_id": guild_id, "user_id": discord_user_id},
            )
            return [dict(row) for row in result.mappings().all()]


class TranslationGroupRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def create(
        self,
        *,
        guild_id: int,
        name: str,
        root_kind: str,
        routing_mode: str,
        visibility_scope_id: UUID | None = None,
        source_language_profile_id: UUID | None = None,
        provider_binding_id: UUID | None = None,
        group_id: UUID | None = None,
    ) -> dict[str, Any]:
        record_id = group_id or uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "INSERT INTO translation_groups "
                "(id,guild_id,name,root_kind,routing_mode,visibility_scope_id,"
                "source_language_profile_id,provider_binding_id) "
                "VALUES (:id,:guild_id,:name,:root_kind,:routing_mode,:scope_id,"
                ":source_language_id,:provider_binding_id) RETURNING *",
                {
                    "id": record_id,
                    "guild_id": guild_id,
                    "name": name,
                    "root_kind": root_kind,
                    "routing_mode": routing_mode,
                    "scope_id": visibility_scope_id,
                    "source_language_id": source_language_profile_id,
                    "provider_binding_id": provider_binding_id,
                },
            )

    async def create_with_languages(
        self,
        *,
        guild_id: int,
        name: str,
        root_kind: str,
        routing_mode: str,
        language_profile_ids: tuple[UUID, ...],
        visibility_scope_id: UUID | None = None,
        source_language_profile_id: UUID | None = None,
        provider_binding_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Create a group and its enabled language membership atomically."""
        if not language_profile_ids:
            raise ValueError("a translation group requires at least one language")
        record_id = uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            enabled = await _execute(
                session,
                text(
                    "SELECT id FROM language_profiles WHERE guild_id=:guild_id "
                    "AND enabled=true AND id IN :language_ids"
                ).bindparams(bindparam("language_ids", expanding=True)),
                {"guild_id": guild_id, "language_ids": list(language_profile_ids)},
            )
            enabled_ids = {UUID(str(row[0])) for row in enabled.all()}
            if enabled_ids != set(language_profile_ids):
                raise ValueError("translation groups require enabled tenant language profiles")
            group = await _fetch_one(
                session,
                "INSERT INTO translation_groups "
                "(id,guild_id,name,root_kind,routing_mode,visibility_scope_id,"
                "source_language_profile_id,provider_binding_id) "
                "VALUES (:id,:guild_id,:name,:root_kind,:routing_mode,:scope_id,"
                ":source_language_id,:provider_binding_id) RETURNING *",
                {
                    "id": record_id,
                    "guild_id": guild_id,
                    "name": name,
                    "root_kind": root_kind,
                    "routing_mode": routing_mode,
                    "scope_id": visibility_scope_id,
                    "source_language_id": source_language_profile_id,
                    "provider_binding_id": provider_binding_id,
                },
            )
            for language_id in language_profile_ids:
                await _execute(
                    session,
                    text(
                        "INSERT INTO translation_group_languages "
                        "(guild_id,translation_group_id,language_profile_id) "
                        "VALUES (:guild_id,:group_id,:language_id)"
                    ),
                    {
                        "guild_id": guild_id,
                        "group_id": record_id,
                        "language_id": language_id,
                    },
                )
            return group

    async def update_name(
        self, *, guild_id: int, group_id: UUID, expected_version: int, name: str
    ) -> dict[str, Any]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await _execute(
                session,
                text(
                    "UPDATE translation_groups SET name=:name, version=version+1, "
                    "updated_at=now() WHERE guild_id=:guild_id AND id=:id "
                    "AND version=:expected_version RETURNING *"
                ),
                {
                    "guild_id": guild_id,
                    "id": group_id,
                    "expected_version": expected_version,
                    "name": name,
                },
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise Stage08Conflict("translation group version is stale")
            return dict(row)

    async def get(self, guild_id: int, group_id: UUID) -> dict[str, Any]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "SELECT * FROM translation_groups WHERE guild_id=:guild_id AND id=:id",
                {"guild_id": guild_id, "id": group_id},
            )

    async def list_groups(self, guild_id: int) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await _execute(
                session,
                text("SELECT * FROM translation_groups WHERE guild_id=:guild_id ORDER BY name,id"),
                {"guild_id": guild_id},
            )
            return [dict(row) for row in result.mappings().all()]

    async def bump_version(
        self, *, guild_id: int, group_id: UUID, expected_version: int
    ) -> dict[str, Any]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await _execute(
                session,
                text(
                    "UPDATE translation_groups SET version=version+1, updated_at=now() "
                    "WHERE guild_id=:guild_id AND id=:id AND version=:version RETURNING *"
                ),
                {
                    "guild_id": guild_id,
                    "id": group_id,
                    "version": expected_version,
                },
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise Stage08Conflict("translation group version is stale")
            return dict(row)

    async def update_routing(
        self,
        *,
        guild_id: int,
        group_id: UUID,
        expected_version: int,
        routing_mode: str,
        source_language_profile_id: UUID | None,
    ) -> dict[str, Any]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await _execute(
                session,
                text(
                    "UPDATE translation_groups SET routing_mode=:routing_mode, "
                    "source_language_profile_id=:source_id, version=version+1, updated_at=now() "
                    "WHERE guild_id=:guild_id AND id=:id AND version=:version RETURNING *"
                ),
                {
                    "guild_id": guild_id,
                    "id": group_id,
                    "version": expected_version,
                    "routing_mode": routing_mode,
                    "source_id": source_language_profile_id,
                },
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise Stage08Conflict("translation group version is stale")
            return dict(row)

    async def detach_language(
        self,
        *,
        guild_id: int,
        group_id: UUID,
        language_profile_id: UUID,
        expected_version: int,
    ) -> dict[str, Any]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            group = (
                (
                    await session.execute(
                        text(
                            "SELECT version FROM translation_groups WHERE guild_id=:guild_id "
                            "AND id=:id FOR UPDATE"
                        ),
                        {"guild_id": guild_id, "id": group_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if group is None:
                raise Stage08NotFound("translation group was not found")
            if int(group["version"]) != expected_version:
                raise Stage08Conflict("translation group version is stale")
            # Keep Discord resources while removing only DID associations.
            parameters = {
                "guild_id": guild_id,
                "group_id": group_id,
                "language_id": language_profile_id,
            }
            await session.execute(
                text(
                    "DELETE FROM translation_category_variants "
                    "WHERE guild_id=:guild_id AND translation_group_id=:group_id "
                    "AND language_profile_id=:language_id"
                ),
                parameters,
            )
            await session.execute(
                text(
                    "DELETE FROM translation_channel_variants "
                    "WHERE guild_id=:guild_id AND translation_group_id=:group_id "
                    "AND language_profile_id=:language_id"
                ),
                parameters,
            )
            await session.execute(
                text(
                    "DELETE FROM translation_routes WHERE guild_id=:guild_id "
                    "AND translation_group_id=:group_id AND "
                    "(source_language_profile_id=:language_id OR "
                    "destination_language_profile_id=:language_id)"
                ),
                {
                    "guild_id": guild_id,
                    "group_id": group_id,
                    "language_id": language_profile_id,
                },
            )
            await session.execute(
                text(
                    "DELETE FROM translation_group_languages WHERE guild_id=:guild_id "
                    "AND translation_group_id=:group_id AND language_profile_id=:language_id"
                ),
                {
                    "guild_id": guild_id,
                    "group_id": group_id,
                    "language_id": language_profile_id,
                },
            )
            updated = (
                (
                    await session.execute(
                        text(
                            "UPDATE translation_groups SET version=version+1, updated_at=now() "
                            "WHERE guild_id=:guild_id AND id=:id RETURNING *"
                        ),
                        {"guild_id": guild_id, "id": group_id},
                    )
                )
                .mappings()
                .one()
            )
            return dict(updated)

    async def detach_variant(
        self,
        *,
        guild_id: int,
        translation_group_id: UUID,
        variant_id: UUID,
        variant_type: str,
    ) -> dict[str, Any]:
        statements = {
            "CATEGORY": (
                "UPDATE translation_category_variants SET state='DETACHED', updated_at=now() "
                "WHERE guild_id=:guild_id AND translation_group_id=:group_id "
                "AND id=:id RETURNING *"
            ),
            "CHANNEL": (
                "UPDATE translation_channel_variants SET state='DETACHED', updated_at=now() "
                "WHERE guild_id=:guild_id AND translation_group_id=:group_id "
                "AND id=:id RETURNING *"
            ),
        }
        statement = statements.get(variant_type)
        if statement is None:
            raise ValueError("variant_type must be CATEGORY or CHANNEL")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                statement,
                {"guild_id": guild_id, "group_id": translation_group_id, "id": variant_id},
            )

    async def get_channel_group(
        self, *, guild_id: int, translation_group_id: UUID, channel_group_id: UUID
    ) -> dict[str, Any]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "SELECT * FROM translation_channel_groups WHERE guild_id=:guild_id "
                "AND translation_group_id=:group_id AND id=:id",
                {"guild_id": guild_id, "group_id": translation_group_id, "id": channel_group_id},
            )

    async def get_variant(
        self,
        *,
        guild_id: int,
        translation_group_id: UUID,
        variant_id: UUID,
        variant_type: str,
    ) -> dict[str, Any]:
        statements = {
            "CATEGORY": (
                "SELECT * FROM translation_category_variants WHERE guild_id=:guild_id "
                "AND translation_group_id=:group_id AND id=:id"
            ),
            "CHANNEL": (
                "SELECT * FROM translation_channel_variants WHERE guild_id=:guild_id "
                "AND translation_group_id=:group_id AND id=:id"
            ),
        }
        statement = statements.get(variant_type)
        if statement is None:
            raise ValueError("variant_type must be CATEGORY or CHANNEL")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                statement,
                {"guild_id": guild_id, "group_id": translation_group_id, "id": variant_id},
            )

    async def mark_variant_missing(
        self, *, guild_id: int, variant_id: UUID, variant_type: str
    ) -> dict[str, Any]:
        statements = {
            "CATEGORY": (
                "UPDATE translation_category_variants SET state='MISSING', updated_at=now() "
                "WHERE guild_id=:guild_id AND id=:id RETURNING *"
            ),
            "CHANNEL": (
                "UPDATE translation_channel_variants SET state='MISSING', updated_at=now() "
                "WHERE guild_id=:guild_id AND id=:id RETURNING *"
            ),
        }
        statement = statements.get(variant_type)
        if statement is None:
            raise ValueError("variant_type must be CATEGORY or CHANNEL")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                statement,
                {"guild_id": guild_id, "id": variant_id},
            )

    async def workspace(self, guild_id: int) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            groups = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM translation_groups WHERE guild_id=:guild_id "
                            "ORDER BY name,id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .all()
            )
            result: list[dict[str, Any]] = []
            for group in groups:
                group_id = group["id"]
                languages = (
                    (
                        await session.execute(
                            text(
                                "SELECT lp.id,lp.code,lp.display_name,lp.enabled "
                                "FROM translation_group_languages tgl JOIN language_profiles lp "
                                "ON lp.guild_id=tgl.guild_id AND lp.id=tgl.language_profile_id "
                                "WHERE tgl.guild_id=:guild_id AND tgl.translation_group_id=:id "
                                "ORDER BY lp.code"
                            ),
                            {"guild_id": guild_id, "id": group_id},
                        )
                    )
                    .mappings()
                    .all()
                )
                categories = (
                    (
                        await session.execute(
                            text(
                                "SELECT * FROM translation_category_variants "
                                "WHERE guild_id=:guild_id AND translation_group_id=:id "
                                "ORDER BY language_profile_id"
                            ),
                            {"guild_id": guild_id, "id": group_id},
                        )
                    )
                    .mappings()
                    .all()
                )
                channel_groups = (
                    (
                        await session.execute(
                            text(
                                "SELECT * FROM translation_channel_groups "
                                "WHERE guild_id=:guild_id AND translation_group_id=:id "
                                "ORDER BY logical_key"
                            ),
                            {"guild_id": guild_id, "id": group_id},
                        )
                    )
                    .mappings()
                    .all()
                )
                channel_variants = (
                    (
                        await session.execute(
                            text(
                                "SELECT * FROM translation_channel_variants "
                                "WHERE guild_id=:guild_id AND translation_group_id=:id "
                                "ORDER BY translation_channel_group_id,language_profile_id"
                            ),
                            {"guild_id": guild_id, "id": group_id},
                        )
                    )
                    .mappings()
                    .all()
                )
                routes = (
                    (
                        await session.execute(
                            text(
                                "SELECT * FROM translation_routes WHERE guild_id=:guild_id "
                                "AND translation_group_id=:id ORDER BY source_language_profile_id,"
                                "destination_language_profile_id"
                            ),
                            {"guild_id": guild_id, "id": group_id},
                        )
                    )
                    .mappings()
                    .all()
                )
                result.append(
                    {
                        **dict(group),
                        "languages": [dict(row) for row in languages],
                        "category_variants": [dict(row) for row in categories],
                        "channel_groups": [dict(row) for row in channel_groups],
                        "channel_variants": [dict(row) for row in channel_variants],
                        "routes": [dict(row) for row in routes],
                    }
                )
            return result

    async def add_language(
        self, *, guild_id: int, translation_group_id: UUID, language_profile_id: UUID
    ) -> None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await _execute(
                session,
                text(
                    "INSERT INTO translation_group_languages "
                    "(guild_id,translation_group_id,language_profile_id) "
                    "VALUES (:guild_id,:group_id,:language_id)"
                ),
                {
                    "guild_id": guild_id,
                    "group_id": translation_group_id,
                    "language_id": language_profile_id,
                },
            )

    async def add_language_delta(
        self,
        *,
        guild_id: int,
        group_id: UUID,
        language_profile_id: UUID,
        expected_version: int,
    ) -> dict[str, Any]:
        """Attach one language and advance the group CAS in one transaction."""
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            enabled = await session.scalar(
                text(
                    "SELECT enabled FROM language_profiles "
                    "WHERE guild_id=:guild_id AND id=:language_id FOR SHARE"
                ),
                {"guild_id": guild_id, "language_id": language_profile_id},
            )
            if enabled is not True:
                raise ValueError("translation groups require enabled tenant language profiles")
            result = await _execute(
                session,
                text(
                    "UPDATE translation_groups SET version=version+1, updated_at=now() "
                    "WHERE guild_id=:guild_id AND id=:id AND version=:version RETURNING *"
                ),
                {"guild_id": guild_id, "id": group_id, "version": expected_version},
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise Stage08Conflict("translation group version is stale")
            await _execute(
                session,
                text(
                    "INSERT INTO translation_group_languages "
                    "(guild_id,translation_group_id,language_profile_id) "
                    "VALUES (:guild_id,:group_id,:language_id)"
                ),
                {
                    "guild_id": guild_id,
                    "group_id": group_id,
                    "language_id": language_profile_id,
                },
            )
            return dict(row)

    async def replace_routes(
        self,
        *,
        guild_id: int,
        group_id: UUID,
        expected_version: int,
        routing_mode: str,
        source_language_profile_id: UUID | None,
        routes: tuple[tuple[UUID, UUID], ...],
    ) -> dict[str, Any]:
        """Replace one group's routes under the same group-level CAS lock."""
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await _execute(
                session,
                text(
                    "UPDATE translation_groups SET routing_mode=:routing_mode, "
                    "source_language_profile_id=:source_id, version=version+1, "
                    "updated_at=now() WHERE guild_id=:guild_id AND id=:id "
                    "AND version=:version RETURNING *"
                ),
                {
                    "guild_id": guild_id,
                    "id": group_id,
                    "version": expected_version,
                    "routing_mode": routing_mode,
                    "source_id": source_language_profile_id,
                },
            )
            row = result.mappings().one_or_none()
            if row is None:
                raise Stage08Conflict("translation group version is stale")
            await session.execute(
                text(
                    "DELETE FROM translation_routes WHERE guild_id=:guild_id "
                    "AND translation_group_id=:group_id"
                ),
                {"guild_id": guild_id, "group_id": group_id},
            )
            for source_id, destination_id in routes:
                await _execute(
                    session,
                    text(
                        "INSERT INTO translation_routes "
                        "(id,guild_id,translation_group_id,source_language_profile_id,"
                        "destination_language_profile_id) VALUES "
                        "(:id,:guild_id,:group_id,:source_id,:destination_id)"
                    ),
                    {
                        "id": uuid4(),
                        "guild_id": guild_id,
                        "group_id": group_id,
                        "source_id": source_id,
                        "destination_id": destination_id,
                    },
                )
            return dict(row)

    async def create_channel_group(
        self,
        *,
        guild_id: int,
        translation_group_id: UUID,
        logical_key: str,
        display_name: str | None = None,
        source_language_profile_id: UUID | None = None,
        config: dict[str, Any] | None = None,
        channel_group_id: UUID | None = None,
    ) -> dict[str, Any]:
        record_id = channel_group_id or uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "INSERT INTO translation_channel_groups "
                "(id,guild_id,translation_group_id,logical_key,display_name,"
                "source_language_profile_id,config_json) "
                "VALUES (:id,:guild_id,:group_id,:logical_key,:display_name,:language_id,"
                "CAST(:config AS jsonb)) "
                "RETURNING *",
                {
                    "id": record_id,
                    "guild_id": guild_id,
                    "group_id": translation_group_id,
                    "logical_key": logical_key,
                    "display_name": (display_name or logical_key).strip(),
                    "language_id": source_language_profile_id,
                    "config": json.dumps(config or {}, separators=(",", ":")),
                },
            )

    async def rename_channel_group(
        self,
        *,
        guild_id: int,
        translation_group_id: UUID,
        channel_group_id: UUID,
        display_name: str,
    ) -> dict[str, Any]:
        """Rename the presentation key without changing stable identity or variants."""
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "UPDATE translation_channel_groups SET display_name=:display_name, "
                "updated_at=now() WHERE guild_id=:guild_id "
                "AND translation_group_id=:group_id AND id=:id RETURNING *",
                {
                    "guild_id": guild_id,
                    "group_id": translation_group_id,
                    "id": channel_group_id,
                    "display_name": display_name,
                },
            )

    async def create_category_variant(
        self,
        *,
        guild_id: int,
        translation_group_id: UUID,
        language_profile_id: UUID,
        discord_category_id: int,
        variant_id: UUID | None = None,
    ) -> dict[str, Any]:
        record_id = variant_id or uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "INSERT INTO translation_category_variants "
                "(id,guild_id,translation_group_id,language_profile_id,discord_category_id) "
                "VALUES (:id,:guild_id,:group_id,:language_id,:discord_id) RETURNING *",
                {
                    "id": record_id,
                    "guild_id": guild_id,
                    "group_id": translation_group_id,
                    "language_id": language_profile_id,
                    "discord_id": discord_category_id,
                },
            )

    async def create_channel_variant(
        self,
        *,
        guild_id: int,
        translation_group_id: UUID,
        translation_channel_group_id: UUID,
        language_profile_id: UUID,
        discord_channel_id: int,
        translation_category_variant_id: UUID | None = None,
        variant_id: UUID | None = None,
    ) -> dict[str, Any]:
        record_id = variant_id or uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "INSERT INTO translation_channel_variants "
                "(id,guild_id,translation_group_id,translation_channel_group_id,language_profile_id,"
                "discord_channel_id,translation_category_variant_id) VALUES "
                "(:id,:guild_id,:group_id,:channel_group_id,:language_id,:discord_id,:category_id) "
                "RETURNING *",
                {
                    "id": record_id,
                    "guild_id": guild_id,
                    "group_id": translation_group_id,
                    "channel_group_id": translation_channel_group_id,
                    "language_id": language_profile_id,
                    "discord_id": discord_channel_id,
                    "category_id": translation_category_variant_id,
                },
            )

    async def create_route(
        self,
        *,
        guild_id: int,
        translation_group_id: UUID,
        source_language_profile_id: UUID,
        destination_language_profile_id: UUID,
        route_id: UUID | None = None,
    ) -> dict[str, Any]:
        record_id = route_id or uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "INSERT INTO translation_routes "
                "(id,guild_id,translation_group_id,source_language_profile_id,"
                "destination_language_profile_id) VALUES "
                "(:id,:guild_id,:group_id,:source_id,:destination_id) RETURNING *",
                {
                    "id": record_id,
                    "guild_id": guild_id,
                    "group_id": translation_group_id,
                    "source_id": source_language_profile_id,
                    "destination_id": destination_language_profile_id,
                },
            )


class TranslationProviderBindingRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def create(
        self,
        *,
        guild_id: int,
        provider_type: str,
        provider_instance_key: str,
        capabilities: dict[str, Any],
        status: str = "UNKNOWN",
        provider_discord_user_id: int | None = None,
        binding_id: UUID | None = None,
    ) -> dict[str, Any]:
        record_id = binding_id or uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "INSERT INTO translation_provider_bindings "
                "(id,guild_id,provider_type,provider_instance_key,provider_discord_user_id,"
                "capabilities_json,status) VALUES (:id,:guild_id,:provider_type,:instance_key,"
                ":discord_user_id,CAST(:capabilities AS jsonb),:status) RETURNING *",
                {
                    "id": record_id,
                    "guild_id": guild_id,
                    "provider_type": provider_type,
                    "instance_key": provider_instance_key,
                    "discord_user_id": provider_discord_user_id,
                    "capabilities": json.dumps(capabilities, separators=(",", ":")),
                    "status": status,
                },
            )

    async def list_bindings(self, guild_id: int) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await _execute(
                session,
                text(
                    "SELECT id,guild_id,provider_type,provider_instance_key,"
                    "provider_discord_user_id,capabilities_json,status,last_validated_at,"
                    "created_at,updated_at FROM translation_provider_bindings "
                    "WHERE guild_id=:guild_id ORDER BY provider_instance_key"
                ),
                {"guild_id": guild_id},
            )
            return [dict(row) for row in result.mappings().all()]

    async def set_status(
        self,
        *,
        guild_id: int,
        binding_id: UUID,
        status: str,
        verified: bool,
    ) -> dict[str, Any]:
        if status == "READY" and not verified:
            raise ValueError("provider cannot become READY before verification")
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "UPDATE translation_provider_bindings SET status=:status, "
                "last_validated_at=CASE WHEN :verified THEN now() ELSE last_validated_at END, "
                "updated_at=now() WHERE guild_id=:guild_id AND id=:id RETURNING *",
                {
                    "guild_id": guild_id,
                    "id": binding_id,
                    "status": status,
                    "verified": verified,
                },
            )


class ResourceLanguagePolicyRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def upsert(
        self,
        *,
        guild_id: int,
        resource_type: str,
        discord_resource_id: int,
        explicit_language_profile_id: UUID | None = None,
        inherit_language: bool = False,
        visibility_policy: str = "OPEN_ALL",
        visibility_scope_id: UUID | None = None,
        custom_policy: dict[str, Any] | None = None,
        policy_id: UUID | None = None,
    ) -> dict[str, Any]:
        record_id = policy_id or uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "INSERT INTO resource_language_policies "
                "(id,guild_id,resource_type,discord_resource_id,explicit_language_profile_id,"
                "inherit_language,visibility_policy,visibility_scope_id,custom_policy_json) "
                "VALUES (:id,:guild_id,:resource_type,:resource_id,:language_id,:inherit,"
                ":visibility_policy,:scope_id,CAST(:custom_policy AS jsonb)) "
                "ON CONFLICT (guild_id,resource_type,discord_resource_id) DO UPDATE SET "
                "explicit_language_profile_id=EXCLUDED.explicit_language_profile_id, "
                "inherit_language=EXCLUDED.inherit_language, "
                "visibility_policy=EXCLUDED.visibility_policy, "
                "visibility_scope_id=EXCLUDED.visibility_scope_id, "
                "custom_policy_json=EXCLUDED.custom_policy_json, updated_at=now() "
                "RETURNING *",
                {
                    "id": record_id,
                    "guild_id": guild_id,
                    "resource_type": resource_type,
                    "resource_id": discord_resource_id,
                    "language_id": explicit_language_profile_id,
                    "inherit": inherit_language,
                    "visibility_policy": visibility_policy,
                    "scope_id": visibility_scope_id,
                    "custom_policy": json.dumps(custom_policy or {}, separators=(",", ":")),
                },
            )

    async def get_optional(
        self, guild_id: int, resource_type: str, discord_resource_id: int
    ) -> dict[str, Any] | None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM resource_language_policies WHERE guild_id=:guild_id "
                            "AND resource_type=:resource_type AND discord_resource_id=:resource_id"
                        ),
                        {
                            "guild_id": guild_id,
                            "resource_type": resource_type,
                            "resource_id": discord_resource_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            return dict(row) if row is not None else None

    async def list_policies(self, guild_id: int) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await _execute(
                session,
                text(
                    "SELECT * FROM resource_language_policies WHERE guild_id=:guild_id "
                    "ORDER BY resource_type,discord_resource_id"
                ),
                {"guild_id": guild_id},
            )
            return [dict(row) for row in result.mappings().all()]


class VisibilityScopeLanguageRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def create(
        self,
        *,
        guild_id: int,
        visibility_scope_id: UUID,
        language_profile_id: UUID,
        discord_role_id: int,
        binding_id: UUID | None = None,
    ) -> dict[str, Any]:
        record_id = binding_id or uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "INSERT INTO visibility_scope_language_roles "
                "(id,guild_id,visibility_scope_id,language_profile_id,discord_role_id) "
                "VALUES (:id,:guild_id,:scope_id,:language_id,:role_id) RETURNING *",
                {
                    "id": record_id,
                    "guild_id": guild_id,
                    "scope_id": visibility_scope_id,
                    "language_id": language_profile_id,
                    "role_id": discord_role_id,
                },
            )

    async def list_bindings(self, guild_id: int) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            result = await _execute(
                session,
                text(
                    "SELECT * FROM visibility_scope_language_roles "
                    "WHERE guild_id=:guild_id ORDER BY visibility_scope_id, language_profile_id"
                ),
                {"guild_id": guild_id},
            )
            return [dict(row) for row in result.mappings().all()]

    async def find_binding(
        self, *, guild_id: int, visibility_scope_id: UUID, language_profile_id: UUID
    ) -> dict[str, Any] | None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM visibility_scope_language_roles "
                            "WHERE guild_id=:guild_id AND visibility_scope_id=:scope_id "
                            "AND language_profile_id=:language_id"
                        ),
                        {
                            "guild_id": guild_id,
                            "scope_id": visibility_scope_id,
                            "language_id": language_profile_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            return dict(row) if row is not None else None


class Stage08AuditRepository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def append(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        event_type: str,
        target_type: str,
        target_id: str,
        correlation_id: UUID,
        data: dict[str, Any] | None = None,
    ) -> None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await session.execute(
                text(
                    "INSERT INTO internal_audit_events "
                    "(id,guild_id,actor_user_id,source,event_type,target_type,target_id,"
                    "correlation_id,result_state,data_json,occurred_at) VALUES "
                    "(:id,:guild_id,:actor_id,'DASHBOARD',:event_type,:target_type,:target_id,"
                    ":correlation_id,'SUCCEEDED',CAST(:data AS jsonb),:occurred_at)"
                ),
                {
                    "id": uuid4(),
                    "guild_id": guild_id,
                    "actor_id": actor_user_id,
                    "event_type": event_type,
                    "target_type": target_type,
                    "target_id": target_id,
                    "correlation_id": correlation_id,
                    "data": json.dumps(data or {}, separators=(",", ":")),
                    "occurred_at": datetime.now(UTC),
                },
            )
