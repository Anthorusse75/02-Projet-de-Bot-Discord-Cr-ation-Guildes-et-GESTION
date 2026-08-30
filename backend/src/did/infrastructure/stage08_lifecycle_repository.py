from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from did.infrastructure.database import tenant_transaction
from did.tenancy import TenantContext


class Stage08LifecycleConflict(RuntimeError):
    pass


class Stage08LifecycleRepository:
    """Tenant-scoped lifecycle state that becomes authoritative only after verification."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def language_binding(
        self, *, guild_id: int, language_profile_id: UUID
    ) -> dict[str, Any] | None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM language_profile_roles WHERE guild_id=:guild_id "
                            "AND language_profile_id=:language_id"
                        ),
                        {"guild_id": guild_id, "language_id": language_profile_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            return dict(row) if row is not None else None

    async def list_language_bindings(self, *, guild_id: int) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM language_profile_roles WHERE guild_id=:guild_id "
                            "ORDER BY language_profile_id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .all()
            )
            return [dict(row) for row in rows]

    async def reserve_role(
        self,
        *,
        guild_id: int,
        binding_kind: str,
        binding_key: str,
        language_profile_id: UUID,
        symbol: str,
        visibility_scope_id: UUID | None = None,
    ) -> tuple[dict[str, Any], bool]:
        reservation_id = uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            inserted = (
                (
                    await session.execute(
                        text(
                            "INSERT INTO stage08_role_reservations "
                            "(id,guild_id,binding_kind,binding_key,visibility_scope_id,"
                            "language_profile_id,symbol) VALUES "
                            "(:id,:guild_id,:kind,:key,:scope_id,:language_id,:symbol) "
                            "ON CONFLICT (guild_id,binding_key) DO NOTHING RETURNING *"
                        ),
                        {
                            "id": reservation_id,
                            "guild_id": guild_id,
                            "kind": binding_kind,
                            "key": binding_key,
                            "scope_id": visibility_scope_id,
                            "language_id": language_profile_id,
                            "symbol": symbol,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if inserted is not None:
                return dict(inserted), True
            existing = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM stage08_role_reservations WHERE guild_id=:guild_id "
                            "AND binding_key=:key FOR UPDATE"
                        ),
                        {"guild_id": guild_id, "key": binding_key},
                    )
                )
                .mappings()
                .one()
            )
            return dict(existing), False

    async def attach_role_plan(
        self,
        *,
        guild_id: int,
        reservation_id: UUID,
        plan_id: UUID,
        intent_type: str,
        payload: dict[str, Any],
    ) -> None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            updated = await session.execute(
                text(
                    "UPDATE stage08_role_reservations SET plan_id=:plan_id,status='PLANNED',"
                    "updated_at=:now WHERE guild_id=:guild_id AND id=:id "
                    "AND status='RESERVED' AND plan_id IS NULL"
                ),
                {
                    "guild_id": guild_id,
                    "id": reservation_id,
                    "plan_id": plan_id,
                    "now": datetime.now(UTC),
                },
            )
            if getattr(updated, "rowcount", 0) != 1:
                raise Stage08LifecycleConflict("role reservation is no longer attachable")
            await session.execute(
                text(
                    "INSERT INTO stage08_plan_intents "
                    "(id,guild_id,plan_id,intent_key,intent_type,payload_json) VALUES "
                    "(:id,:guild_id,:plan_id,:intent_key,:intent_type,CAST(:payload AS jsonb))"
                ),
                {
                    "id": uuid4(),
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "intent_key": str(reservation_id),
                    "intent_type": intent_type,
                    "payload": json.dumps(payload, separators=(",", ":")),
                },
            )

    async def add_plan_intent(
        self,
        *,
        guild_id: int,
        plan_id: UUID,
        intent_key: str,
        intent_type: str,
        payload: dict[str, Any],
    ) -> None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await session.execute(
                text(
                    "INSERT INTO stage08_plan_intents "
                    "(id,guild_id,plan_id,intent_key,intent_type,payload_json) VALUES "
                    "(:id,:guild_id,:plan_id,:intent_key,:intent_type,CAST(:payload AS jsonb)) "
                    "ON CONFLICT (guild_id,plan_id,intent_key) DO NOTHING"
                ),
                {
                    "id": uuid4(),
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "intent_key": intent_key,
                    "intent_type": intent_type,
                    "payload": json.dumps(payload, separators=(",", ":")),
                },
            )

    async def attach_scope_role_cleanup(
        self,
        *,
        guild_id: int,
        binding_id: UUID,
        plan_id: UUID,
        discord_role_id: int,
        binding_key: str,
    ) -> None:
        """Fence a proven-unused binding and attach its post-verification cleanup."""
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            binding = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM visibility_scope_language_roles "
                            "WHERE guild_id=:guild_id AND id=:binding_id FOR UPDATE"
                        ),
                        {"guild_id": guild_id, "binding_id": binding_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if binding is None or int(binding["discord_role_id"]) != discord_role_id:
                raise Stage08LifecycleConflict("technical role binding is unavailable")
            if str(binding["role_state"]) == "PENDING_DELETE":
                existing_plan = await session.scalar(
                    text(
                        "SELECT plan_id FROM stage08_plan_intents WHERE guild_id=:guild_id "
                        "AND intent_type='DELETE_SCOPE_LANGUAGE_ROLE_BINDING' "
                        "AND intent_key=:intent_key"
                    ),
                    {"guild_id": guild_id, "intent_key": f"cleanup:{binding_id}"},
                )
                if existing_plan == plan_id:
                    return
                raise Stage08LifecycleConflict("technical role cleanup is already planned")
            if str(binding["role_state"]) != "ACTIVE" or not bool(binding["managed_by_did"]):
                raise Stage08LifecycleConflict("technical role binding is not cleanable")
            referenced = await session.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM resource_language_policies p "
                    "WHERE p.guild_id=:guild_id AND p.visibility_policy='SCOPE_AND_LANGUAGE' "
                    "AND p.visibility_scope_id=:scope_id "
                    "AND p.explicit_language_profile_id=:language_id)"
                ),
                {
                    "guild_id": guild_id,
                    "scope_id": binding["visibility_scope_id"],
                    "language_id": binding["language_profile_id"],
                },
            )
            if bool(referenced):
                raise Stage08LifecycleConflict("technical role is still required by topology")
            updated = await session.execute(
                text(
                    "UPDATE visibility_scope_language_roles SET role_state='PENDING_DELETE',"
                    "updated_at=:now WHERE guild_id=:guild_id AND id=:binding_id "
                    "AND role_state='ACTIVE'"
                ),
                {
                    "guild_id": guild_id,
                    "binding_id": binding_id,
                    "now": datetime.now(UTC),
                },
            )
            if getattr(updated, "rowcount", 0) != 1:
                raise Stage08LifecycleConflict("technical role cleanup lost its reservation")
            await session.execute(
                text(
                    "INSERT INTO stage08_plan_intents "
                    "(id,guild_id,plan_id,intent_key,intent_type,payload_json) VALUES "
                    "(:id,:guild_id,:plan_id,:intent_key,"
                    "'DELETE_SCOPE_LANGUAGE_ROLE_BINDING',CAST(:payload AS jsonb))"
                ),
                {
                    "id": uuid4(),
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "intent_key": f"cleanup:{binding_id}",
                    "payload": json.dumps(
                        {
                            "binding_id": str(binding_id),
                            "binding_key": binding_key,
                            "discord_role_id": str(discord_role_id),
                        },
                        separators=(",", ":"),
                    ),
                },
            )

    async def apply_verified_intents(self, *, guild_id: int, plan_id: UUID) -> tuple[int, bool]:
        """Materialize every pending intent in one transaction after targeted REST verification."""
        now = datetime.now(UTC)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            intents = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM stage08_plan_intents WHERE guild_id=:guild_id "
                            "AND plan_id=:plan_id AND status='PENDING' "
                            "ORDER BY intent_key FOR UPDATE"
                        ),
                        {"guild_id": guild_id, "plan_id": plan_id},
                    )
                )
                .mappings()
                .all()
            )
            provider_pending = False
            for intent in intents:
                payload = dict(intent["payload_json"])
                intent_type = str(intent["intent_type"])
                if intent_type in {"BIND_LANGUAGE_ROLE", "BIND_SCOPE_LANGUAGE_ROLE"}:
                    role_id = await self._bound_role_id(
                        session,
                        guild_id=guild_id,
                        plan_id=plan_id,
                        symbol=str(payload["symbol"]),
                    )
                    reservation_id = UUID(str(payload["reservation_id"]))
                    if intent_type == "BIND_LANGUAGE_ROLE":
                        await session.execute(
                            text(
                                "INSERT INTO language_profile_roles "
                                "(id,guild_id,language_profile_id,discord_role_id) VALUES "
                                "(:id,:guild_id,:language_id,:role_id) "
                                "ON CONFLICT (guild_id,language_profile_id) DO UPDATE SET "
                                "discord_role_id=EXCLUDED.discord_role_id,role_state='ACTIVE',"
                                "updated_at=:now"
                            ),
                            {
                                "id": uuid4(),
                                "guild_id": guild_id,
                                "language_id": UUID(str(payload["language_profile_id"])),
                                "role_id": role_id,
                                "now": now,
                            },
                        )
                    else:
                        await session.execute(
                            text(
                                "INSERT INTO visibility_scope_language_roles "
                                "(id,guild_id,visibility_scope_id,language_profile_id,"
                                "discord_role_id) "
                                "VALUES (:id,:guild_id,:scope_id,:language_id,:role_id) "
                                "ON CONFLICT (guild_id,visibility_scope_id,language_profile_id) "
                                "DO UPDATE SET discord_role_id=EXCLUDED.discord_role_id,"
                                "role_state='ACTIVE',updated_at=:now"
                            ),
                            {
                                "id": uuid4(),
                                "guild_id": guild_id,
                                "scope_id": UUID(str(payload["visibility_scope_id"])),
                                "language_id": UUID(str(payload["language_profile_id"])),
                                "role_id": role_id,
                                "now": now,
                            },
                        )
                    await session.execute(
                        text(
                            "UPDATE stage08_role_reservations SET status='BOUND',"
                            "discord_role_id=:role_id,updated_at=:now WHERE guild_id=:guild_id "
                            "AND id=:id AND plan_id=:plan_id AND status='PLANNED'"
                        ),
                        {
                            "guild_id": guild_id,
                            "id": reservation_id,
                            "plan_id": plan_id,
                            "role_id": role_id,
                            "now": now,
                        },
                    )
                elif intent_type == "DELETE_SCOPE_LANGUAGE_ROLE_BINDING":
                    binding_id = UUID(str(payload["binding_id"]))
                    role_id = int(payload["discord_role_id"])
                    deleted = await session.execute(
                        text(
                            "DELETE FROM visibility_scope_language_roles "
                            "WHERE guild_id=:guild_id AND id=:binding_id "
                            "AND discord_role_id=:role_id AND role_state IN "
                            "('PENDING_DELETE','MISSING')"
                        ),
                        {
                            "guild_id": guild_id,
                            "binding_id": binding_id,
                            "role_id": role_id,
                        },
                    )
                    if getattr(deleted, "rowcount", 0) != 1:
                        raise Stage08LifecycleConflict(
                            "verified technical role binding is no longer cleanable"
                        )
                    await session.execute(
                        text(
                            "DELETE FROM stage08_role_reservations WHERE guild_id=:guild_id "
                            "AND binding_key=:binding_key AND discord_role_id=:role_id "
                            "AND status='BOUND'"
                        ),
                        {
                            "guild_id": guild_id,
                            "binding_key": str(payload["binding_key"]),
                            "role_id": role_id,
                        },
                    )
                elif intent_type == "VERIFY_PROVIDER":
                    status = str(payload["verified_status"])
                    if status not in {"READY", "MANUAL_CONFIGURATION_REQUIRED"}:
                        raise Stage08LifecycleConflict("invalid verified provider state")
                    result = await session.execute(
                        text(
                            "UPDATE translation_provider_bindings b SET "
                            "status=CAST(:status AS varchar),"
                            "last_validated_at=CASE WHEN CAST(:status AS varchar)='READY' "
                            "THEN :now "
                            "ELSE b.last_validated_at END,updated_at=:now "
                            "WHERE b.guild_id=:guild_id AND b.id=:binding_id AND EXISTS ("
                            "SELECT 1 FROM translation_groups g WHERE g.guild_id=b.guild_id "
                            "AND g.id=:group_id AND g.provider_binding_id=b.id)"
                        ),
                        {
                            "guild_id": guild_id,
                            "binding_id": UUID(str(payload["binding_id"])),
                            "group_id": UUID(str(payload["translation_group_id"])),
                            "status": status,
                            "now": now,
                        },
                    )
                    if getattr(result, "rowcount", 0) != 1:
                        raise Stage08LifecycleConflict("provider binding is unavailable")
                    group_status = "ACTIVE" if status == "READY" else "PROVIDER_PENDING"
                    group_result = await session.execute(
                        text(
                            "UPDATE translation_groups SET status=:group_status,"
                            "updated_at=:now WHERE guild_id=:guild_id AND id=:group_id "
                            "AND provider_binding_id=:binding_id AND status<>'DETACHED'"
                        ),
                        {
                            "guild_id": guild_id,
                            "group_id": UUID(str(payload["translation_group_id"])),
                            "binding_id": UUID(str(payload["binding_id"])),
                            "group_status": group_status,
                            "now": now,
                        },
                    )
                    if getattr(group_result, "rowcount", 0) != 1:
                        raise Stage08LifecycleConflict("provider group is unavailable")
                    provider_pending = provider_pending or status == (
                        "MANUAL_CONFIGURATION_REQUIRED"
                    )
                elif intent_type in {
                    "MATERIALIZE_CATEGORY_VARIANT",
                    "MATERIALIZE_CHANNEL_VARIANT",
                    "REPAIR_CATEGORY_VARIANT",
                    "REPAIR_CHANNEL_VARIANT",
                }:
                    expected_type = "CATEGORY" if "CATEGORY" in intent_type else "CHANNEL"
                    resource_id = await self._bound_resource_id(
                        session,
                        guild_id=guild_id,
                        plan_id=plan_id,
                        symbol=str(payload["symbol"]),
                        resource_type=expected_type,
                    )
                    if intent_type == "MATERIALIZE_CATEGORY_VARIANT":
                        await session.execute(
                            text(
                                "INSERT INTO translation_category_variants "
                                "(id,guild_id,translation_group_id,language_profile_id,"
                                "discord_category_id,is_source,state) VALUES "
                                "(:id,:guild_id,:group_id,:language_id,:resource_id,false,'ACTIVE')"
                            ),
                            {
                                "id": UUID(str(payload["variant_id"])),
                                "guild_id": guild_id,
                                "group_id": UUID(str(payload["translation_group_id"])),
                                "language_id": UUID(str(payload["language_profile_id"])),
                                "resource_id": resource_id,
                            },
                        )
                    elif intent_type == "MATERIALIZE_CHANNEL_VARIANT":
                        await session.execute(
                            text(
                                "INSERT INTO translation_channel_variants "
                                "(id,guild_id,translation_group_id,translation_channel_group_id,"
                                "language_profile_id,discord_channel_id,"
                                "translation_category_variant_id,state) VALUES "
                                "(:id,:guild_id,:group_id,:channel_group_id,:language_id,"
                                ":resource_id,:category_variant_id,'ACTIVE')"
                            ),
                            {
                                "id": UUID(str(payload["variant_id"])),
                                "guild_id": guild_id,
                                "group_id": UUID(str(payload["translation_group_id"])),
                                "channel_group_id": UUID(
                                    str(payload["translation_channel_group_id"])
                                ),
                                "language_id": UUID(str(payload["language_profile_id"])),
                                "resource_id": resource_id,
                                "category_variant_id": (
                                    UUID(str(payload["translation_category_variant_id"]))
                                    if payload.get("translation_category_variant_id")
                                    else None
                                ),
                            },
                        )
                    else:
                        table, id_column = (
                            ("translation_category_variants", "discord_category_id")
                            if expected_type == "CATEGORY"
                            else ("translation_channel_variants", "discord_channel_id")
                        )
                        # Closed internal table/column pair; request data is always bound.
                        result = await session.execute(
                            text(
                                f"UPDATE {table} SET {id_column}=:resource_id,state='ACTIVE',"  # noqa: S608
                                "updated_at=:now WHERE guild_id=:guild_id "
                                "AND translation_group_id=:group_id AND id=:variant_id "
                                "AND state='MISSING'"
                            ),
                            {
                                "guild_id": guild_id,
                                "group_id": UUID(str(payload["translation_group_id"])),
                                "variant_id": UUID(str(payload["variant_id"])),
                                "resource_id": resource_id,
                                "now": now,
                            },
                        )
                        if getattr(result, "rowcount", 0) != 1:
                            raise Stage08LifecycleConflict(
                                "missing variant is no longer repairable"
                            )
                elif intent_type == "MATERIALIZE_CLONE":
                    raise Stage08LifecycleConflict("clone materializer is unavailable")
                else:  # guarded by the database CHECK, kept fail-closed for corrupted rows
                    raise Stage08LifecycleConflict("unsupported Stage 08 plan intent")
                await session.execute(
                    text(
                        "UPDATE stage08_plan_intents SET status='APPLIED',verified_at=:now,"
                        "updated_at=:now,error_code=NULL WHERE guild_id=:guild_id AND id=:id"
                    ),
                    {"guild_id": guild_id, "id": intent["id"], "now": now},
                )
            return len(intents), provider_pending

    @staticmethod
    async def _bound_role_id(
        session: AsyncSession, *, guild_id: int, plan_id: UUID, symbol: str
    ) -> int:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT discord_id FROM plan_symbol_bindings WHERE guild_id=:guild_id "
                        "AND plan_id=:plan_id AND symbol=:symbol AND resource_type='ROLE' "
                        "AND status='BOUND' FOR SHARE"
                    ),
                    {"guild_id": guild_id, "plan_id": plan_id, "symbol": symbol},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["discord_id"] is None:
            raise Stage08LifecycleConflict("verified role symbol is not bound")
        return int(row["discord_id"])

    @staticmethod
    async def _bound_resource_id(
        session: AsyncSession,
        *,
        guild_id: int,
        plan_id: UUID,
        symbol: str,
        resource_type: str,
    ) -> int:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT discord_id FROM plan_symbol_bindings WHERE guild_id=:guild_id "
                        "AND plan_id=:plan_id AND symbol=:symbol AND resource_type=:resource_type "
                        "AND status='BOUND' FOR SHARE"
                    ),
                    {
                        "guild_id": guild_id,
                        "plan_id": plan_id,
                        "symbol": symbol,
                        "resource_type": resource_type,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["discord_id"] is None:
            raise Stage08LifecycleConflict("verified resource symbol is not bound")
        return int(row["discord_id"])

    async def fail_pending_intents(self, *, guild_id: int, plan_id: UUID, error_code: str) -> None:
        now = datetime.now(UTC)
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await session.execute(
                text(
                    "UPDATE stage08_plan_intents SET status='FAILED',error_code=:error_code,"
                    "updated_at=:now WHERE guild_id=:guild_id AND plan_id=:plan_id "
                    "AND status='PENDING'"
                ),
                {
                    "guild_id": guild_id,
                    "plan_id": plan_id,
                    "error_code": error_code,
                    "now": now,
                },
            )
            await session.execute(
                text(
                    "UPDATE stage08_role_reservations SET status='FAILED',updated_at=:now "
                    "WHERE guild_id=:guild_id AND plan_id=:plan_id AND status='PLANNED'"
                ),
                {"guild_id": guild_id, "plan_id": plan_id, "now": now},
            )
            await session.execute(
                text(
                    "UPDATE visibility_scope_language_roles b SET role_state='ACTIVE',"
                    "updated_at=:now WHERE b.guild_id=:guild_id AND b.role_state='PENDING_DELETE' "
                    "AND EXISTS (SELECT 1 FROM stage08_plan_intents i "
                    "WHERE i.guild_id=b.guild_id AND i.plan_id=:plan_id "
                    "AND i.intent_type='DELETE_SCOPE_LANGUAGE_ROLE_BINDING' "
                    "AND i.payload_json->>'binding_id'=CAST(b.id AS text))"
                ),
                {"guild_id": guild_id, "plan_id": plan_id, "now": now},
            )
