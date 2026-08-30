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

    async def apply_verified_intents(self, *, guild_id: int, plan_id: UUID) -> int:
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
                elif intent_type == "VERIFY_PROVIDER":
                    status = str(payload["verified_status"])
                    if status not in {"READY", "MANUAL_CONFIGURATION_REQUIRED"}:
                        raise Stage08LifecycleConflict("invalid verified provider state")
                    result = await session.execute(
                        text(
                            "UPDATE translation_provider_bindings SET status=:status,"
                            "last_validated_at=:now,updated_at=:now WHERE guild_id=:guild_id "
                            "AND id=:binding_id"
                        ),
                        {
                            "guild_id": guild_id,
                            "binding_id": UUID(str(payload["binding_id"])),
                            "status": status,
                            "now": now,
                        },
                    )
                    if getattr(result, "rowcount", 0) != 1:
                        raise Stage08LifecycleConflict("provider binding is unavailable")
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
            return len(intents)

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

    async def fail_pending_intents(
        self, *, guild_id: int, plan_id: UUID, error_code: str
    ) -> None:
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
