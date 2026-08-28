from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
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
                    "SELECT * FROM member_visible_languages "
                    "WHERE guild_id=:guild_id AND discord_user_id=:user_id "
                    "ORDER BY language_profile_id"
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

    async def create_channel_group(
        self,
        *,
        guild_id: int,
        translation_group_id: UUID,
        logical_key: str,
        source_language_profile_id: UUID | None = None,
        config: dict[str, Any] | None = None,
        channel_group_id: UUID | None = None,
    ) -> dict[str, Any]:
        record_id = channel_group_id or uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            return await _fetch_one(
                session,
                "INSERT INTO translation_channel_groups "
                "(id,guild_id,translation_group_id,logical_key,source_language_profile_id,"
                "config_json) "
                "VALUES (:id,:guild_id,:group_id,:logical_key,:language_id,CAST(:config AS jsonb)) "
                "RETURNING *",
                {
                    "id": record_id,
                    "guild_id": guild_id,
                    "group_id": translation_group_id,
                    "logical_key": logical_key,
                    "language_id": source_language_profile_id,
                    "config": json.dumps(config or {}, separators=(",", ":")),
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
