from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from did.infrastructure.database import (
    create_database_engine,
    create_session_factory,
    tenant_transaction,
)
from did.infrastructure.portability_repository import (
    PortabilityRepository,
    PortableArtifactNotFound,
    PortableQuotaExceeded,
    TransferNotFound,
)
from did.infrastructure.runtime_metrics import RuntimeMetrics
from did.portability import (
    ArtifactCipher,
    ArtifactType,
    InMemoryKeyProvider,
    PortableArtifact,
    PortableProvenance,
    PortableResource,
    PortableResourceType,
    TransferState,
    artifact_to_bytes,
)
from did.tenancy import TenantContext

pytestmark = [pytest.mark.integration, pytest.mark.security]

APP_URL = os.environ.get(
    "DID_DATABASE_URL",
    "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test",
)
ADMIN_URL = os.environ.get(
    "DID_DATABASE_ADMIN_URL",
    "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test",
)
USER_U = 660606060606060601
USER_V = 660606060606060602
GUILD_A = 660606060606060603
GUILD_B = 660606060606060604
BOT = 660606060606060605


async def seed() -> None:
    engine = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE users, guild_installations CASCADE"))
            await connection.execute(
                text(
                    "INSERT INTO users (discord_user_id,username) VALUES "
                    "(:u,'stage06-u'),(:v,'stage06-v')"
                ),
                {"u": USER_U, "v": USER_V},
            )
            await connection.execute(
                text(
                    "INSERT INTO guild_installations "
                    "(guild_id,name,owner_id,installation_status,application_id,bot_user_id) "
                    "VALUES (:a,'A',:u,'ACTIVE',:bot,:bot),"
                    "(:b,'B',:u,'ACTIVE',:bot,:bot)"
                ),
                {"a": GUILD_A, "b": GUILD_B, "u": USER_U, "bot": BOT},
            )
    finally:
        await engine.dispose()


def portable() -> PortableArtifact:
    return PortableArtifact(
        ArtifactType.CUSTOM_BUNDLE,
        (
            PortableResource.build(
                "role.staff",
                PortableResourceType.ROLE,
                {"name": "Stage Six Secret Staff", "permissions": "0"},
            ),
        ),
        roots=("role.staff",),
        provenance=PortableProvenance(str(GUILD_A), ("777777777777777777",)),
    )


@pytest.mark.asyncio
async def test_artifact_owner_rls_ciphertext_idempotency_templates_and_purge() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=2)
    admin = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        metrics = RuntimeMetrics()
        repository = PortabilityRepository(
            create_session_factory(engine),
            ArtifactCipher(InMemoryKeyProvider({1: b"k" * 32}, current_version=1)),
            max_artifacts_per_owner=3,
            metrics=metrics,
        )
        row, created = await repository.create_artifact(
            owner_user_id=USER_U,
            kind="LIBRARY",
            artifact=portable(),
            name="portable",
            expires_at=datetime.now(UTC) + timedelta(days=1),
            idempotency_operation="TEST",
            idempotency_key="same",
        )
        repeated, repeated_created = await repository.create_artifact(
            owner_user_id=USER_U,
            kind="LIBRARY",
            artifact=portable(),
            name="ignored-on-retry",
            expires_at=None,
            idempotency_operation="TEST",
            idempotency_key="same",
        )
        assert created is True
        assert repeated_created is False
        assert repeated["id"] == row["id"]
        metadata, decrypted = await repository.get_artifact(USER_U, row["id"])
        assert metadata["content_hash"] == portable().content_hash
        assert decrypted == portable()
        with pytest.raises(PortableArtifactNotFound):
            await repository.get_artifact(USER_V, row["id"])
        expired, _ = await repository.create_artifact(
            owner_user_id=USER_U,
            kind="CLIPBOARD",
            artifact=portable(),
            name="expired",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            idempotency_operation="TEST",
            idempotency_key="expired",
        )
        assert all(item["id"] != expired["id"] for item in await repository.list_artifacts(USER_U))
        assert metrics.artifact_purges == 1
        async with admin.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT id FROM user_portable_artifacts WHERE id=:id"),
                    {"id": expired["id"]},
                )
                is None
            )
        for key in ("second", "third"):
            await repository.create_artifact(
                owner_user_id=USER_U,
                kind="LIBRARY",
                artifact=portable(),
                name=key,
                expires_at=None,
                idempotency_operation="TEST",
                idempotency_key=key,
            )
        with pytest.raises(PortableQuotaExceeded):
            await repository.create_artifact(
                owner_user_id=USER_U,
                kind="LIBRARY",
                artifact=portable(),
                name="over-quota",
                expires_at=None,
                idempotency_operation="TEST",
                idempotency_key="over-quota",
            )
        with pytest.raises(DBAPIError):
            await repository.create_transfer(
                transfer_id=uuid4(),
                actor_user_id=USER_V,
                source_guild_id=None,
                destination_guild_id=GUILD_B,
                artifact_id=row["id"],
                artifact_content_hash=portable().content_hash,
                mode="COPY_AS_NEW",
                mapping=[],
                status="READY",
                correlation_id=uuid4(),
                idempotency_key="cross-owner-forbidden",
            )

        async with admin.connect() as connection:
            raw = (
                (
                    await connection.execute(
                        text(
                            "SELECT content_ciphertext,content_nonce,wrapped_dek,wrap_nonce "
                            "FROM user_portable_artifacts WHERE id=:id"
                        ),
                        {"id": row["id"]},
                    )
                )
                .mappings()
                .one()
            )
        assert b"Stage Six Secret Staff" not in bytes(raw["content_ciphertext"])
        assert len(raw["content_nonce"]) == 12
        assert len(raw["wrap_nonce"]) == 12
        assert len(raw["wrapped_dek"]) > 32

        template = await repository.create_template(
            guild_id=GUILD_A,
            actor_user_id=USER_U,
            template_id=uuid4(),
            name="tenant-private",
            artifact=portable(),
        )
        assert len(await repository.list_templates(GUILD_A, USER_U)) == 1
        assert await repository.list_templates(GUILD_B, USER_U) == []
        with pytest.raises(PortableArtifactNotFound):
            await repository.get_template(GUILD_B, USER_U, template["id"])

        policy_id = await repository.create_policy_definition(
            guild_id=GUILD_A,
            actor_user_id=USER_U,
            definition_id=uuid4(),
            logical_key="policy.review",
            name="Review",
            definition={"rules": ["review.read"]},
            principal_mappings=[],
            artifact_hash=portable().content_hash,
        )
        async with tenant_transaction(
            create_session_factory(engine), TenantContext(GUILD_B, USER_U)
        ) as session:
            hidden_policy = await session.scalar(
                text("SELECT id FROM portable_policy_definitions WHERE id=:id"),
                {"id": policy_id},
            )
        assert hidden_policy is None

        transfer, _ = await repository.create_transfer(
            transfer_id=uuid4(),
            actor_user_id=USER_U,
            source_guild_id=GUILD_A,
            destination_guild_id=GUILD_B,
            artifact_id=row["id"],
            artifact_content_hash=portable().content_hash,
            mode="COPY_AS_NEW",
            mapping=[],
            status="READY",
            correlation_id=uuid4(),
            idempotency_key="transfer",
        )
        with pytest.raises(TransferNotFound):
            await repository.get_transfer(USER_V, transfer["id"])
        await repository.delete_artifact(USER_U, row["id"])
        with pytest.raises(TransferNotFound):
            await repository.get_transfer(USER_U, transfer["id"])
    finally:
        await engine.dispose()
        await admin.dispose()


@pytest.mark.asyncio
async def test_owner_quota_is_atomic_for_count_and_bytes_under_concurrency() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=4)
    try:
        count_repository = PortabilityRepository(
            create_session_factory(engine),
            ArtifactCipher(InMemoryKeyProvider({1: b"q" * 32}, current_version=1)),
            max_artifacts_per_owner=1,
        )

        async def create(repository: PortabilityRepository, key: str) -> object:
            try:
                return await repository.create_artifact(
                    owner_user_id=USER_U,
                    kind="LIBRARY",
                    artifact=portable(),
                    name=key,
                    expires_at=None,
                    idempotency_operation="QUOTA",
                    idempotency_key=key,
                )
            except Exception as exc:  # the assertion below checks the exact loser type
                return exc

        count_results = await asyncio.gather(
            create(count_repository, "count-a"), create(count_repository, "count-b")
        )
        assert sum(isinstance(item, PortableQuotaExceeded) for item in count_results) == 1
        assert sum(isinstance(item, tuple) for item in count_results) == 1

        await seed()
        encoded_size = len(artifact_to_bytes(portable()))
        byte_repository = PortabilityRepository(
            create_session_factory(engine),
            ArtifactCipher(InMemoryKeyProvider({1: b"b" * 32}, current_version=1)),
            max_artifacts_per_owner=10,
            max_total_bytes_per_owner=encoded_size,
        )
        byte_results = await asyncio.gather(
            create(byte_repository, "bytes-a"), create(byte_repository, "bytes-b")
        )
        assert sum(isinstance(item, PortableQuotaExceeded) for item in byte_results) == 1
        assert sum(isinstance(item, tuple) for item in byte_results) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_transfer_lifecycle_clone_bindings_rls_and_audit_are_durable_and_idempotent() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=2)
    admin = create_database_engine(ADMIN_URL, pool_size=1)
    try:
        repository = PortabilityRepository(
            create_session_factory(engine),
            ArtifactCipher(InMemoryKeyProvider({1: b"l" * 32}, current_version=1)),
        )
        artifact_row, _ = await repository.create_artifact(
            owner_user_id=USER_U,
            kind="LIBRARY",
            artifact=portable(),
            name="lifecycle",
            expires_at=None,
            idempotency_operation="LIFECYCLE",
            idempotency_key="artifact",
        )
        transfer_id = uuid4()
        relationship_key = "a" * 64
        transfer, created = await repository.create_transfer(
            transfer_id=transfer_id,
            actor_user_id=USER_U,
            source_guild_id=GUILD_A,
            destination_guild_id=GUILD_B,
            artifact_id=artifact_row["id"],
            artifact_content_hash=portable().content_hash,
            mode="MAXIMUM_COMPATIBLE",
            mapping=[],
            status="CREATED",
            correlation_id=uuid4(),
            idempotency_key="lifecycle-transfer",
            relationship_key=relationship_key,
        )
        assert created and transfer["state_version"] == 1
        for expected, target in (
            (TransferState.CREATED, TransferState.EXPORTED),
            (TransferState.EXPORTED, TransferState.READY),
        ):
            transfer = await repository.transition_transfer(
                actor_user_id=USER_U,
                transfer_id=transfer_id,
                expected=expected,
                target=target,
            )
        transfer = await repository.compile_transfer(
            actor_user_id=USER_U,
            transfer_id=transfer_id,
            destination_plan_id=None,
            report=[{"outcome": "CLONED", "destructive": False}],
        )
        assert transfer["status"] == "COMPILED"
        assert transfer["destination_plan_id"] is None

        await repository.save_clone_bindings(
            actor_user_id=USER_U,
            transfer_id=transfer_id,
            destination_guild_id=GUILD_B,
            relationship_key=relationship_key,
            artifact_hash=portable().content_hash,
            bindings=[
                {
                    "logical_ref": "role.staff",
                    "resource_type": "ROLE",
                    "destination_resource_id": 770606060606060601,
                    "binding_origin": "CREATED",
                }
            ],
        )
        owned = await repository.reconcile_bindings(USER_U, GUILD_B, relationship_key)
        foreign = await repository.reconcile_bindings(USER_V, GUILD_B, relationship_key)
        assert [item["logical_ref"] for item in owned] == ["role.staff"]
        assert foreign == []

        correlation = uuid4()
        for _ in range(2):
            await repository.audit_boundary(
                guild_id=GUILD_B,
                actor_user_id=USER_U,
                transfer_id=transfer_id,
                event_type="PORTABLE_ARTIFACT_COMPILED",
                artifact_hash=portable().content_hash,
                correlation_id=correlation,
            )
        async with admin.connect() as connection:
            count = await connection.scalar(
                text(
                    "SELECT count(*) FROM internal_audit_events WHERE source='PORTABILITY' "
                    "AND event_type='PORTABLE_ARTIFACT_COMPILED' AND target_id=:target"
                ),
                {"target": str(transfer_id)},
            )
        assert count == 1
    finally:
        await engine.dispose()
        await admin.dispose()
