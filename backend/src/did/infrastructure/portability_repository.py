from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from did.infrastructure.database import tenant_transaction
from did.infrastructure.runtime_metrics import RuntimeMetrics
from did.portability.artifact import PortableArtifact, artifact_from_dict, artifact_to_bytes
from did.portability.crypto import ArtifactCipher, EncryptedArtifact, KeyUnavailable
from did.portability.transfer import TransferState, assert_transfer_transition
from did.tenancy import TenantContext, UserContext


class PortableArtifactNotFound(LookupError):
    pass


class PortableQuotaExceeded(ValueError):
    pass


class PortableArtifactIntegrityError(RuntimeError):
    pass


class TransferNotFound(LookupError):
    pass


class PortabilityRepository:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        cipher: ArtifactCipher,
        *,
        max_artifacts_per_owner: int = 100,
        max_total_bytes_per_owner: int = 25_000_000,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        self._factory = factory
        self._cipher = cipher
        self._max_artifacts = max_artifacts_per_owner
        self._max_total_bytes = max_total_bytes_per_owner
        self._metrics = metrics

    async def create_artifact(
        self,
        *,
        owner_user_id: int,
        kind: str,
        artifact: PortableArtifact,
        name: str | None,
        expires_at: datetime | None,
        idempotency_operation: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        artifact_id = uuid4()
        encrypted = self._cipher.encrypt(
            artifact, artifact_id=artifact_id, owner_user_id=owner_user_id
        )
        if self._metrics is not None:
            self._metrics.portability_outcome("artifact_crypto", "encrypt_success")
        size = len(artifact_to_bytes(artifact))
        async with tenant_transaction(self._factory, UserContext(owner_user_id)) as session:
            await session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended('did:portable:quota:' || CAST(:owner AS text),0))"
                ),
                {"owner": str(owner_user_id)},
            )
            existing = await self._artifact_by_idempotency(
                session, owner_user_id, idempotency_operation, idempotency_key
            )
            if existing is not None:
                return dict(existing), False
            quota = (
                (
                    await session.execute(
                        text(
                            "SELECT count(*) AS item_count, "
                            "coalesce(sum(content_size_bytes), 0) AS total_bytes "
                            "FROM user_portable_artifacts "
                            "WHERE owner_discord_user_id=:owner AND "
                            "(expires_at IS NULL OR expires_at > now())"
                        ),
                        {"owner": owner_user_id},
                    )
                )
                .mappings()
                .one()
            )
            if int(quota["item_count"]) >= self._max_artifacts or (
                int(quota["total_bytes"]) + size > self._max_total_bytes
            ):
                if self._metrics is not None:
                    self._metrics.quota_rejections += 1
                raise PortableQuotaExceeded("portable artifact owner quota exceeded")
            row = (
                (
                    await session.execute(
                        text(
                            "INSERT INTO user_portable_artifacts "
                            "(id,owner_discord_user_id,kind,artifact_type,source_guild_id,"
                            "schema_version,name,content_ciphertext,content_nonce,wrapped_dek,"
                            "wrap_nonce,encryption_key_version,content_hash,content_size_bytes,"
                            "idempotency_operation,idempotency_key,expires_at) VALUES "
                            "(:id,:owner,:kind,:artifact_type,:source_guild_id,:schema_version,"
                            ":name,:ciphertext,:nonce,:wrapped_dek,:wrap_nonce,:key_version,"
                            ":content_hash,:content_size,:operation,:idempotency_key,:expires_at) "
                            "ON CONFLICT (owner_discord_user_id,idempotency_operation,"
                            "idempotency_key) DO NOTHING RETURNING "
                            "id,owner_discord_user_id,kind,artifact_type,source_guild_id,"
                            "schema_version,name,encryption_key_version,content_hash,"
                            "content_size_bytes,created_at,expires_at"
                        ),
                        {
                            "id": artifact_id,
                            "owner": owner_user_id,
                            "kind": kind,
                            "artifact_type": artifact.artifact_type.value,
                            "source_guild_id": (
                                int(artifact.provenance.source_guild_id)
                                if artifact.provenance.source_guild_id
                                else None
                            ),
                            "schema_version": artifact.schema_version,
                            "name": name,
                            "ciphertext": encrypted.ciphertext,
                            "nonce": encrypted.nonce,
                            "wrapped_dek": encrypted.wrapped_dek,
                            "wrap_nonce": encrypted.wrap_nonce,
                            "key_version": encrypted.key_version,
                            "content_hash": encrypted.content_hash,
                            "content_size": size,
                            "operation": idempotency_operation,
                            "idempotency_key": idempotency_key,
                            "expires_at": expires_at,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                existing = await self._artifact_by_idempotency(
                    session, owner_user_id, idempotency_operation, idempotency_key
                )
                if existing is None:
                    raise RuntimeError("idempotent artifact insert lost without a winner")
                return dict(existing), False
            return dict(row), True

    async def list_artifacts(self, owner_user_id: int) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, UserContext(owner_user_id)) as session:
            purged = (
                await session.execute(
                    text(
                        "DELETE FROM user_portable_artifacts "
                        "WHERE owner_discord_user_id=:owner AND expires_at <= now() "
                        "RETURNING id"
                    ),
                    {"owner": owner_user_id},
                )
            ).all()
            if self._metrics is not None:
                self._metrics.artifact_purges += len(purged)
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT id,owner_discord_user_id,kind,artifact_type,source_guild_id,"
                            "schema_version,name,encryption_key_version,content_hash,content_size_bytes,"
                            "created_at,expires_at FROM user_portable_artifacts "
                            "WHERE owner_discord_user_id=:owner AND "
                            "(expires_at IS NULL OR expires_at > now()) ORDER BY created_at DESC"
                        ),
                        {"owner": owner_user_id},
                    )
                )
                .mappings()
                .all()
            )
            return [dict(row) for row in rows]

    async def get_artifact(
        self, owner_user_id: int, artifact_id: UUID
    ) -> tuple[dict[str, Any], PortableArtifact]:
        async with tenant_transaction(self._factory, UserContext(owner_user_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM user_portable_artifacts WHERE id=:id "
                            "AND owner_discord_user_id=:owner AND "
                            "(expires_at IS NULL OR expires_at > now())"
                        ),
                        {"id": artifact_id, "owner": owner_user_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise PortableArtifactNotFound("portable artifact unavailable")
        metadata = dict(row)
        try:
            artifact = self._cipher.decrypt(
                EncryptedArtifact(
                    bytes(row["content_ciphertext"]),
                    bytes(row["content_nonce"]),
                    bytes(row["wrapped_dek"]),
                    bytes(row["wrap_nonce"]),
                    int(row["encryption_key_version"]),
                    str(row["content_hash"]),
                ),
                artifact_id=artifact_id,
                owner_user_id=owner_user_id,
                schema_version=str(row["schema_version"]),
            )
        except KeyUnavailable:
            if self._metrics is not None:
                self._metrics.portability_outcome("artifact_crypto", "key_unavailable")
            raise
        except ValueError:
            if self._metrics is not None:
                self._metrics.portability_outcome("artifact_crypto", "tamper")
            raise PortableArtifactIntegrityError("portable artifact integrity failure") from None
        if self._metrics is not None:
            self._metrics.portability_outcome("artifact_crypto", "decrypt_success")
        return metadata, artifact

    async def delete_artifact(self, owner_user_id: int, artifact_id: UUID) -> None:
        async with tenant_transaction(self._factory, UserContext(owner_user_id)) as session:
            deleted = (
                await session.execute(
                    text(
                        "DELETE FROM user_portable_artifacts WHERE id=:id "
                        "AND owner_discord_user_id=:owner RETURNING id"
                    ),
                    {"id": artifact_id, "owner": owner_user_id},
                )
            ).scalar_one_or_none()
            if deleted is None:
                raise PortableArtifactNotFound("portable artifact unavailable")
            if self._metrics is not None:
                self._metrics.artifact_purges += 1

    async def reencrypt_artifact(self, owner_user_id: int, artifact_id: UUID) -> None:
        metadata, artifact = await self.get_artifact(owner_user_id, artifact_id)
        encrypted = self._cipher.encrypt(
            artifact, artifact_id=artifact_id, owner_user_id=owner_user_id
        )
        async with tenant_transaction(self._factory, UserContext(owner_user_id)) as session:
            await session.execute(
                text(
                    "UPDATE user_portable_artifacts SET content_ciphertext=:ciphertext,"
                    "content_nonce=:nonce,wrapped_dek=:wrapped_dek,wrap_nonce=:wrap_nonce,"
                    "encryption_key_version=:key_version WHERE id=:id AND "
                    "owner_discord_user_id=:owner AND content_hash=:content_hash"
                ),
                {
                    "ciphertext": encrypted.ciphertext,
                    "nonce": encrypted.nonce,
                    "wrapped_dek": encrypted.wrapped_dek,
                    "wrap_nonce": encrypted.wrap_nonce,
                    "key_version": encrypted.key_version,
                    "id": artifact_id,
                    "owner": owner_user_id,
                    "content_hash": metadata["content_hash"],
                },
            )

    async def create_template(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        template_id: UUID,
        name: str,
        artifact: PortableArtifact,
    ) -> dict[str, Any]:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id, actor_user_id)
        ) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "INSERT INTO templates (id,guild_id,name,artifact_type,schema_version,"
                            "content_hash,artifact_json,created_by) VALUES "
                            "(:id,:guild_id,:name,:artifact_type,:schema_version,:content_hash,"
                            ":artifact_json,:actor) RETURNING *"
                        ),
                        {
                            "id": template_id,
                            "guild_id": guild_id,
                            "name": name,
                            "artifact_type": artifact.artifact_type.value,
                            "schema_version": artifact.schema_version,
                            "content_hash": artifact.content_hash,
                            "artifact_json": json.dumps(artifact.canonical_payload()),
                            "actor": actor_user_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            return dict(row)

    async def create_policy_definition(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        definition_id: UUID,
        logical_key: str,
        name: str,
        definition: dict[str, Any],
        principal_mappings: list[dict[str, str]],
        artifact_hash: str,
    ) -> UUID:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id, actor_user_id)
        ) as session:
            await session.execute(
                text(
                    "INSERT INTO portable_policy_definitions "
                    "(id,guild_id,logical_key,name,definition_json,principal_mappings_json,"
                    "source_artifact_hash,created_by) VALUES "
                    "(:id,:guild_id,:logical_key,:name,:definition,:mappings,:hash,:actor) "
                    "ON CONFLICT (guild_id,id) DO NOTHING"
                ),
                {
                    "id": definition_id,
                    "guild_id": guild_id,
                    "logical_key": logical_key,
                    "name": name,
                    "definition": json.dumps(definition),
                    "mappings": json.dumps(principal_mappings),
                    "hash": artifact_hash,
                    "actor": actor_user_id,
                },
            )
        return definition_id

    async def list_templates(self, guild_id: int, actor_user_id: int) -> list[dict[str, Any]]:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id, actor_user_id)
        ) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT id,guild_id,name,artifact_type,schema_version,content_hash,"
                            "created_by,version,created_at,updated_at FROM templates "
                            "WHERE guild_id=:guild_id ORDER BY updated_at DESC"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .all()
            )
            return [dict(row) for row in rows]

    async def get_template(
        self, guild_id: int, actor_user_id: int, template_id: UUID
    ) -> tuple[dict[str, Any], PortableArtifact]:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id, actor_user_id)
        ) as session:
            row = (
                (
                    await session.execute(
                        text("SELECT * FROM templates WHERE guild_id=:guild_id AND id=:id"),
                        {"guild_id": guild_id, "id": template_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise PortableArtifactNotFound("template unavailable")
        return dict(row), artifact_from_dict(dict(row["artifact_json"]))

    async def create_transfer(
        self,
        *,
        transfer_id: UUID,
        actor_user_id: int,
        source_guild_id: int | None,
        destination_guild_id: int,
        artifact_id: UUID,
        artifact_content_hash: str,
        mode: str,
        mapping: list[dict[str, Any]],
        status: str,
        correlation_id: UUID,
        idempotency_key: str,
        relationship_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        async with tenant_transaction(self._factory, UserContext(actor_user_id)) as session:
            existing = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM cross_guild_transfers WHERE "
                            "actor_discord_user_id=:actor AND idempotency_key=:key"
                        ),
                        {"actor": actor_user_id, "key": idempotency_key},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                return dict(existing), False
            row = (
                (
                    await session.execute(
                        text(
                            "INSERT INTO cross_guild_transfers "
                            "(id,actor_discord_user_id,source_guild_id,destination_guild_id,"
                            "portable_artifact_id,artifact_content_hash,transfer_mode,mapping_json,"
                            "status,correlation_id,idempotency_key,relationship_key) VALUES "
                            "(:id,:actor,:source,:destination,:artifact,:hash,:mode,:mapping,"
                            ":status,:correlation,:key,:relationship_key) ON CONFLICT "
                            "(actor_discord_user_id,idempotency_key) DO NOTHING RETURNING *"
                        ),
                        {
                            "id": transfer_id,
                            "actor": actor_user_id,
                            "source": source_guild_id,
                            "destination": destination_guild_id,
                            "artifact": artifact_id,
                            "hash": artifact_content_hash,
                            "mode": mode,
                            "mapping": json.dumps(mapping),
                            "status": status,
                            "correlation": correlation_id,
                            "key": idempotency_key,
                            "relationship_key": relationship_key,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                existing = (
                    (
                        await session.execute(
                            text(
                                "SELECT * FROM cross_guild_transfers WHERE "
                                "actor_discord_user_id=:actor AND idempotency_key=:key"
                            ),
                            {"actor": actor_user_id, "key": idempotency_key},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is None:
                    raise RuntimeError("idempotent transfer insert lost without a winner")
                return dict(existing), False
            return dict(row), True

    async def compile_transfer(
        self,
        *,
        actor_user_id: int,
        transfer_id: UUID,
        destination_plan_id: UUID | None,
        report: list[dict[str, Any]],
    ) -> dict[str, Any]:
        assert_transfer_transition(TransferState.READY, TransferState.COMPILED)
        async with tenant_transaction(self._factory, UserContext(actor_user_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "UPDATE cross_guild_transfers SET destination_plan_id=:plan_id,"
                            "report_json=:report,status='COMPILED',updated_at=now() "
                            "WHERE id=:id AND actor_discord_user_id=:actor "
                            "AND status IN ('READY','COMPILED') "
                            "RETURNING *"
                        ),
                        {
                            "plan_id": destination_plan_id,
                            "report": json.dumps(report),
                            "id": transfer_id,
                            "actor": actor_user_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise TransferNotFound("transfer unavailable")
            return dict(row)

    async def transition_transfer(
        self,
        *,
        actor_user_id: int,
        transfer_id: UUID,
        expected: TransferState,
        target: TransferState,
        mapping: list[dict[str, Any]] | None = None,
        report: list[dict[str, Any]] | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        if expected is not target:
            assert_transfer_transition(expected, target)
        async with tenant_transaction(self._factory, UserContext(actor_user_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "UPDATE cross_guild_transfers SET status=:target,"
                            "mapping_json=COALESCE(CAST(:mapping AS jsonb),mapping_json),"
                            "report_json=COALESCE(CAST(:report AS jsonb),report_json),"
                            "error_code=:error_code,state_version=state_version+1,updated_at=now() "
                            "WHERE id=:id AND actor_discord_user_id=:actor AND status=:expected "
                            "RETURNING *"
                        ),
                        {
                            "target": target.value,
                            "mapping": json.dumps(mapping) if mapping is not None else None,
                            "report": json.dumps(report) if report is not None else None,
                            "error_code": error_code,
                            "id": transfer_id,
                            "actor": actor_user_id,
                            "expected": expected.value,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                existing = await session.execute(
                    text(
                        "SELECT * FROM cross_guild_transfers WHERE id=:id "
                        "AND actor_discord_user_id=:actor"
                    ),
                    {"id": transfer_id, "actor": actor_user_id},
                )
                current = existing.mappings().one_or_none()
                if current is not None and str(current["status"]) == target.value:
                    return dict(current)
                raise TransferNotFound("transfer state changed or transfer unavailable")
            return dict(row)

    async def reconcile_bindings(
        self, actor_user_id: int, destination_guild_id: int, relationship_key: str
    ) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, UserContext(actor_user_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT logical_ref,resource_type,destination_resource_id,"
                            "binding_origin,source_artifact_hash,transfer_id "
                            "FROM portable_clone_bindings WHERE owner_discord_user_id=:actor "
                            "AND destination_guild_id=:destination AND relationship_key=:key "
                            "AND active ORDER BY logical_ref"
                        ),
                        {
                            "actor": actor_user_id,
                            "destination": destination_guild_id,
                            "key": relationship_key,
                        },
                    )
                )
                .mappings()
                .all()
            )
            return [dict(row) for row in rows]

    async def save_clone_bindings(
        self,
        *,
        actor_user_id: int,
        transfer_id: UUID,
        destination_guild_id: int,
        relationship_key: str,
        artifact_hash: str,
        bindings: list[dict[str, Any]],
    ) -> None:
        async with tenant_transaction(self._factory, UserContext(actor_user_id)) as session:
            for item in bindings:
                await session.execute(
                    text(
                        "INSERT INTO portable_clone_bindings "
                        "(owner_discord_user_id,destination_guild_id,relationship_key,logical_ref,"
                        "resource_type,destination_resource_id,binding_origin,source_artifact_hash,"
                        "transfer_id,active) VALUES (:actor,:destination,:key,:logical_ref,"
                        ":resource_type,:resource_id,:origin,:hash,:transfer_id,true) "
                        "ON CONFLICT (owner_discord_user_id,destination_guild_id,"
                        "relationship_key,logical_ref) "
                        "DO UPDATE SET resource_type=excluded.resource_type,"
                        "destination_resource_id=excluded.destination_resource_id,"
                        "binding_origin=excluded.binding_origin,source_artifact_hash=excluded.source_artifact_hash,"
                        "transfer_id=excluded.transfer_id,active=true,updated_at=now()"
                    ),
                    {
                        "actor": actor_user_id,
                        "destination": destination_guild_id,
                        "key": relationship_key,
                        "logical_ref": item["logical_ref"],
                        "resource_type": item["resource_type"],
                        "resource_id": int(item["destination_resource_id"]),
                        "origin": item["binding_origin"],
                        "hash": artifact_hash,
                        "transfer_id": transfer_id,
                    },
                )

    async def get_transfer(self, actor_user_id: int, transfer_id: UUID) -> dict[str, Any]:
        async with tenant_transaction(self._factory, UserContext(actor_user_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM cross_guild_transfers WHERE id=:id "
                            "AND actor_discord_user_id=:actor"
                        ),
                        {"id": transfer_id, "actor": actor_user_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise TransferNotFound("transfer unavailable")
            return dict(row)

    async def record_local_result(
        self, actor_user_id: int, transfer_id: UUID, result: dict[str, Any]
    ) -> dict[str, Any]:
        async with tenant_transaction(self._factory, UserContext(actor_user_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "UPDATE cross_guild_transfers SET local_result_json=:result,"
                            "finalized_at=coalesce(finalized_at,now()),updated_at=now() "
                            "WHERE id=:id AND actor_discord_user_id=:actor "
                            "AND status='COMPILED' RETURNING *"
                        ),
                        {
                            "result": json.dumps(result),
                            "id": transfer_id,
                            "actor": actor_user_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise TransferNotFound("transfer unavailable")
            return dict(row)

    async def audit_boundary(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        transfer_id: UUID,
        event_type: str,
        artifact_hash: str,
        correlation_id: UUID,
        destination_plan_id: UUID | None = None,
        target_type: str = "TRANSFER",
    ) -> None:
        async with tenant_transaction(
            self._factory, TenantContext(guild_id, actor_user_id)
        ) as session:
            await session.execute(
                text(
                    "INSERT INTO internal_audit_events "
                    "(id,guild_id,actor_user_id,source,event_type,target_type,target_id,"
                    "correlation_id,result_state,data_json,occurred_at) VALUES "
                    "(:id,:guild_id,:actor,'PORTABILITY',:event_type,:target_type,:target_id,"
                    ":correlation,'SUCCEEDED',:data,now()) ON CONFLICT DO NOTHING"
                ),
                {
                    "id": uuid4(),
                    "guild_id": guild_id,
                    "actor": actor_user_id,
                    "event_type": event_type,
                    "target_id": str(transfer_id),
                    "target_type": target_type,
                    "correlation": correlation_id,
                    "data": json.dumps(
                        {
                            "artifact_hash": artifact_hash,
                            "destination_plan_id": (
                                str(destination_plan_id) if destination_plan_id else None
                            ),
                        }
                    ),
                },
            )

    @staticmethod
    async def _artifact_by_idempotency(
        session: AsyncSession,
        owner_user_id: int,
        operation: str,
        idempotency_key: str,
    ) -> Any:
        return (
            (
                await session.execute(
                    text(
                        "SELECT id,owner_discord_user_id,kind,artifact_type,source_guild_id,"
                        "schema_version,name,encryption_key_version,content_hash,content_size_bytes,"
                        "created_at,expires_at FROM user_portable_artifacts WHERE "
                        "owner_discord_user_id=:owner AND idempotency_operation=:operation "
                        "AND idempotency_key=:key"
                    ),
                    {"owner": owner_user_id, "operation": operation, "key": idempotency_key},
                )
            )
            .mappings()
            .one_or_none()
        )
