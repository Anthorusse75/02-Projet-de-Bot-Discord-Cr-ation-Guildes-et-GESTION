from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from did.application.planning import PlanningService
from did.application.portability import ArtifactKind, PortabilityService
from did.cloning import DestinationPlanCompiler
from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
from did.domain.read_model import (
    ChannelSnapshot,
    CoverageSnapshot,
    FreshnessSnapshot,
    GuildSnapshot,
    MemberSnapshot,
    OverwriteSnapshot,
    RoleSnapshot,
)
from did.domain.read_model.models import ChannelType
from did.infrastructure.database import (
    create_database_engine,
    create_session_factory,
    tenant_transaction,
)
from did.infrastructure.discord.mutations import (
    MutationResult,
    PreconditionOutcome,
    RecoveryOutcome,
    RecoveryResult,
)
from did.infrastructure.planning_repository import PlanningRepository
from did.infrastructure.portability_repository import (
    PortabilityRepository,
    PortableArtifactNotFound,
    PortableQuotaExceeded,
    TransferConflict,
    TransferNotFound,
)
from did.infrastructure.runtime_metrics import RuntimeMetrics
from did.infrastructure.runtime_repository import RuntimeRepository
from did.infrastructure.stage08_lifecycle_repository import Stage08LifecycleRepository
from did.infrastructure.stage08_repository import (
    LanguageProfileRepository,
    ResourceLanguagePolicyRepository,
    TranslationGroupRepository,
    TranslationProviderBindingRepository,
)
from did.planning.models import OperationType
from did.portability import (
    ArtifactCipher,
    ArtifactType,
    CloneMode,
    InMemoryKeyProvider,
    PortableArtifact,
    PortableProvenance,
    PortableResource,
    PortableResourceType,
    TransferState,
    artifact_to_bytes,
)
from did.tenancy import TenantContext
from did.worker.io.governor import DiscordWorkloadGovernor
from did.worker.io.plan_executor import ApplyPlanExecutor

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
SOURCE_CATEGORY = 660606060606060610
SOURCE_CHANNEL = 660606060606060611
SOURCE_ROLE = 660606060606060612
DESTINATION_CATEGORY = 660606060606060620
DESTINATION_CHANNEL = 660606060606060621
DESTINATION_ROLE = 660606060606060622


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


def destination_mapping_snapshot(*role_ids: int) -> GuildSnapshot:
    now = datetime.now(UTC)
    freshness = FreshnessSnapshot(FreshnessState.FRESH, "GATEWAY", 1, now, now, now)
    coverage = CoverageSnapshot(
        GUILD_B,
        CoverageMode.FULL,
        FreshnessState.FRESH,
        "GATEWAY",
        1,
        known_channels=0,
        visible_channels=0,
        obfuscated_channels=0,
        known_roles=1 + len(role_ids),
        overwrites_complete=True,
    )
    return GuildSnapshot(
        GUILD_B,
        1,
        (
            RoleSnapshot(GUILD_B, GUILD_B, "@everyone", 0, 0, False, freshness),
            *(
                RoleSnapshot(
                    GUILD_B,
                    role_id,
                    "Stage Six Secret Staff",
                    1,
                    8,
                    False,
                    freshness,
                )
                for role_id in role_ids
            ),
        ),
        (),
        coverage,
        freshness,
    )


def translation_source_snapshot() -> GuildSnapshot:
    now = datetime.now(UTC)
    fresh = FreshnessSnapshot(FreshnessState.FRESH, "GATEWAY", 1, now, now, now)
    roles = (
        RoleSnapshot(GUILD_A, GUILD_A, "@everyone", 0, 0, False, fresh),
        RoleSnapshot(
            GUILD_A,
            SOURCE_ROLE,
            "DID Language FR",
            1,
            0,
            False,
            fresh,
            hoist=False,
            mentionable=False,
        ),
    )
    category = ChannelSnapshot(
        GUILD_A,
        SOURCE_CATEGORY,
        ChannelType.GUILD_CATEGORY,
        0,
        None,
        "Support FR",
        (),
        True,
        ObservabilityState.VISIBLE,
        fresh,
    )
    channel = ChannelSnapshot(
        GUILD_A,
        SOURCE_CHANNEL,
        ChannelType.GUILD_TEXT,
        1,
        SOURCE_CATEGORY,
        "support-fr",
        (OverwriteSnapshot(GUILD_A, SOURCE_CHANNEL, SOURCE_ROLE, 0, 1024, 0, now),),
        True,
        ObservabilityState.VISIBLE,
        fresh,
    )
    coverage = CoverageSnapshot(
        GUILD_A,
        CoverageMode.FULL,
        FreshnessState.FRESH,
        "GATEWAY",
        1,
        known_channels=2,
        visible_channels=2,
        known_roles=2,
        overwrites_complete=True,
    )
    return GuildSnapshot(GUILD_A, USER_U, roles, (category, channel), coverage, fresh)


def translation_destination_snapshot() -> tuple[GuildSnapshot, MemberSnapshot]:
    now = datetime.now(UTC)
    fresh = FreshnessSnapshot(FreshnessState.FRESH, "GATEWAY", 1, now, now, now)
    admin_role = BOT + 100
    roles = (
        RoleSnapshot(GUILD_B, GUILD_B, "@everyone", 0, 0, False, fresh),
        RoleSnapshot(GUILD_B, admin_role, "DID Bot", 1, 8, False, fresh),
    )
    coverage = CoverageSnapshot(
        GUILD_B,
        CoverageMode.FULL,
        FreshnessState.FRESH,
        "GATEWAY",
        1,
        known_channels=0,
        visible_channels=0,
        known_roles=2,
        overwrites_complete=True,
    )
    guild = GuildSnapshot(GUILD_B, USER_U, roles, (), coverage, fresh)
    member = MemberSnapshot(GUILD_B, BOT, (GUILD_B, admin_role), True, fresh)
    return guild, member


class PassLock:
    async def run(self, guild_id: int, operation: Any) -> Any:
        del guild_id
        return await operation()


class AllowApply:
    async def authorize_apply(self, *, guild_id: int, actor_user_id: int) -> None:
        assert guild_id == GUILD_B
        assert actor_user_id == USER_U


class CloneMutationAdapter:
    def __init__(self) -> None:
        self.executed: list[tuple[OperationType, dict[str, Any]]] = []

    async def check_preconditions(self, **kwargs: Any) -> PreconditionOutcome:
        del kwargs
        return PreconditionOutcome.SATISFIED

    async def execute(self, **kwargs: Any) -> MutationResult:
        operation_type = OperationType(kwargs["operation_type"])
        payload = dict(kwargs["payload"])
        self.executed.append((operation_type, payload))
        if operation_type is OperationType.CREATE_ROLE:
            result = {"id": DESTINATION_ROLE, **payload}
        elif operation_type is OperationType.CREATE_CHANNEL:
            resource_id = (
                DESTINATION_CATEGORY if int(payload.get("type", 0)) == 4 else DESTINATION_CHANNEL
            )
            result = {"id": resource_id, **payload}
        else:
            result = payload
        return MutationResult(201, result, "c" * 64)

    async def recover(self, **kwargs: Any) -> RecoveryResult:
        del kwargs
        return RecoveryResult(RecoveryOutcome.PROVED_ABSENT, None)

    async def verify(self, **kwargs: Any) -> bool:
        del kwargs
        return True


@pytest.mark.asyncio
async def test_multilingual_clone_uses_stage06_stage05_and_materializes_after_success() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=4)
    factory = create_session_factory(engine)
    languages = LanguageProfileRepository(factory)
    groups = TranslationGroupRepository(factory)
    providers = TranslationProviderBindingRepository(factory)
    policies = ResourceLanguagePolicyRepository(factory)
    lifecycle = Stage08LifecycleRepository(factory)
    planning_repository = PlanningRepository(factory)
    runtime = RuntimeRepository(factory)
    portability_repository = PortabilityRepository(
        factory,
        ArtifactCipher(InMemoryKeyProvider({1: b"t" * 32}, current_version=1)),
    )
    try:
        fr = await languages.create(guild_id=GUILD_A, code="fr", display_name="French")
        en = await languages.create(guild_id=GUILD_A, code="en", display_name="English")
        provider = await providers.create(
            guild_id=GUILD_A,
            provider_type="existing_translation_bot",
            provider_instance_key="source-only-provider",
            capabilities={
                "supports_hub_and_spoke": True,
                "requires_message_content": False,
            },
            status="READY",
        )
        source_group = await groups.create_with_languages(
            guild_id=GUILD_A,
            name="Portable Support",
            root_kind="CATEGORY_SET",
            routing_mode="HUB_AND_SPOKE",
            language_profile_ids=(UUID(str(fr["id"])), UUID(str(en["id"]))),
            source_language_profile_id=UUID(str(fr["id"])),
            provider_binding_id=UUID(str(provider["id"])),
        )
        category = await groups.create_category_variant(
            guild_id=GUILD_A,
            translation_group_id=UUID(str(source_group["id"])),
            language_profile_id=UUID(str(fr["id"])),
            discord_category_id=SOURCE_CATEGORY,
        )
        channel_group = await groups.create_channel_group(
            guild_id=GUILD_A,
            translation_group_id=UUID(str(source_group["id"])),
            logical_key="support",
            display_name="Support",
            source_language_profile_id=UUID(str(fr["id"])),
        )
        await groups.create_channel_variant(
            guild_id=GUILD_A,
            translation_group_id=UUID(str(source_group["id"])),
            translation_channel_group_id=UUID(str(channel_group["id"])),
            language_profile_id=UUID(str(fr["id"])),
            discord_channel_id=SOURCE_CHANNEL,
            translation_category_variant_id=UUID(str(category["id"])),
        )
        await groups.create_route(
            guild_id=GUILD_A,
            translation_group_id=UUID(str(source_group["id"])),
            source_language_profile_id=UUID(str(fr["id"])),
            destination_language_profile_id=UUID(str(en["id"])),
        )
        await policies.upsert(
            guild_id=GUILD_A,
            resource_type="CATEGORY",
            discord_resource_id=SOURCE_CATEGORY,
            explicit_language_profile_id=UUID(str(fr["id"])),
            visibility_policy="OPEN_ALL",
        )
        await policies.upsert(
            guild_id=GUILD_A,
            resource_type="CHANNEL",
            discord_resource_id=SOURCE_CHANNEL,
            explicit_language_profile_id=UUID(str(fr["id"])),
            visibility_policy="LANGUAGE_FILTERED",
        )
        async with tenant_transaction(factory, TenantContext(GUILD_A)) as session:
            await session.execute(
                text(
                    "INSERT INTO language_profile_roles "
                    "(id,guild_id,language_profile_id,discord_role_id) "
                    "VALUES (:id,:guild_id,:language_id,:role_id)"
                ),
                {
                    "id": uuid4(),
                    "guild_id": GUILD_A,
                    "language_id": fr["id"],
                    "role_id": SOURCE_ROLE,
                },
            )

        source_snapshot = translation_source_snapshot()
        destination_snapshot, bot_member = translation_destination_snapshot()

        async def guild_snapshot(guild_id: int, actor_user_id: int) -> tuple[Any, Any]:
            del actor_user_id
            return (
                (source_snapshot, None)
                if guild_id == GUILD_A
                else (destination_snapshot, bot_member)
            )

        read_models = SimpleNamespace(
            guild_snapshot=AsyncMock(side_effect=guild_snapshot),
            cached_member_snapshots=AsyncMock(return_value=[]),
            bot_identity=AsyncMock(return_value=(BOT, "ACTIVE")),
        )
        planning = PlanningService(planning_repository, cast(Any, read_models))
        portability = PortabilityService(
            portability_repository,
            cast(Any, read_models),
            planning,
            planning_repository,
            translation_groups=groups,
            translation_policies=policies,
            translation_providers=providers,
            translation_lifecycle=lifecycle,
        )
        artifact, artifact_created = await portability.export_live_translation_group(
            source_guild_id=GUILD_A,
            translation_group_id=UUID(str(source_group["id"])),
            actor_user_id=USER_U,
            kind=ArtifactKind.EXPORT_BUNDLE,
            name="stage08-real-clone",
            idempotency_key="stage08-real-clone-export",
            correlation_id=uuid4(),
        )
        assert artifact_created
        _, decrypted_artifact = await portability_repository.get_artifact(
            USER_U, UUID(str(artifact["id"]))
        )
        serialized_artifact = repr(decrypted_artifact.canonical_payload())
        assert "source-only-provider" not in serialized_artifact
        assert "provider_binding_id" not in serialized_artifact
        assert "config_encrypted" not in serialized_artifact
        transfer, plan, plan_created = await portability.compile_stored(
            actor_user_id=USER_U,
            artifact_id=UUID(str(artifact["id"])),
            destination_guild_id=GUILD_B,
            mode=CloneMode.COPY_AS_NEW,
            explicit_mappings=(),
            idempotency_key="stage08-real-clone-compile",
            correlation_id=uuid4(),
            source_authorized=True,
        )
        assert plan_created and plan is not None and plan["status"] == "DRAFT"
        plan_id = UUID(str(plan["id"]))
        validated, preflight = await planning.validate(
            guild_id=GUILD_B,
            plan_id=plan_id,
            actor_user_id=USER_U,
            expected_version=int(plan["state_version"]),
            correlation_id=uuid4(),
            actor_authorization_fresh=True,
        )
        assert preflight.allowed
        confirmed = await planning.confirm(
            guild_id=GUILD_B,
            plan_id=plan_id,
            actor_user_id=USER_U,
            idempotency_key="stage08-real-clone-confirm",
            expected_version=int(validated["state_version"]),
            supplied_plan_hash=str(validated["plan_hash"]),
            reinforced_acknowledgement=True,
            correlation_id=uuid4(),
        )
        await planning.apply(
            guild_id=GUILD_B,
            plan_id=plan_id,
            actor_user_id=USER_U,
            correlation_id=uuid4(),
        )
        leased = await runtime.lease_next_job(
            GUILD_B,
            lease_owner="stage08-real-clone-worker",
            lease_seconds=30,
        )
        assert leased is not None and confirmed["status"] == "CONFIRMED"
        adapter = CloneMutationAdapter()
        governor = DiscordWorkloadGovernor()
        executor = ApplyPlanExecutor(
            planning_repository,
            adapter,
            PassLock(),  # type: ignore[arg-type]
            worker_id="stage08-real-clone-worker",
            authorization=AllowApply(),
            preflight=planning,
        )
        await executor.execute_leased(GUILD_B, leased, governor)
        assert (await planning_repository.get_plan(GUILD_B, plan_id))["status"] == "SUCCEEDED"

        finalized = await portability.finalize_transfer(
            actor_user_id=USER_U,
            transfer_id=UUID(str(transfer["id"])),
            correlation_id=uuid4(),
        )
        destination_groups = await groups.workspace(GUILD_B)
        assert len(destination_groups) == 1
        destination_group = destination_groups[0]
        assert destination_group["id"] != source_group["id"]
        assert int(destination_group["category_variants"][0]["discord_category_id"]) == (
            DESTINATION_CATEGORY
        )
        assert int(destination_group["channel_variants"][0]["discord_channel_id"]) == (
            DESTINATION_CHANNEL
        )
        destination_binding = await lifecycle.language_binding(
            guild_id=GUILD_B,
            language_profile_id=UUID(
                str(
                    next(row["id"] for row in destination_group["languages"] if row["code"] == "fr")
                )
            ),
        )
        assert destination_binding is not None
        assert int(destination_binding["discord_role_id"]) == DESTINATION_ROLE
        assert await providers.list_bindings(GUILD_B) == []
        source_after = await groups.workspace_group(
            guild_id=GUILD_A,
            group_id=UUID(str(source_group["id"])),
        )
        assert int(source_after["channel_variants"][0]["discord_channel_id"]) == SOURCE_CHANNEL
        local_result = dict(finalized["local_result_json"])["translation_topology"]
        assert local_result["provider_bindings_omitted"] is True
        assert local_result["source_translation_group_id_propagated"] is False
        role_payload = next(
            payload
            for operation, payload in adapter.executed
            if operation is OperationType.CREATE_ROLE
        )
        assert role_payload["permissions"] == "0"
        assert role_payload["hoist"] is False
        assert role_payload["mentionable"] is False
    finally:
        await engine.dispose()


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
            relationship, _ = await repository.create_clone_relationship(
                actor_user_id=USER_U,
                destination_guild_id=GUILD_B,
                creation_key="b" * 64,
                source_descriptor={"source_guild_id": GUILD_A},
            )
            await repository.create_transfer(
                transfer_id=uuid4(),
                actor_user_id=USER_V,
                source_guild_id=None,
                destination_guild_id=GUILD_B,
                artifact_id=row["id"],
                artifact_content_hash=portable().content_hash,
                mode="COPY_AS_NEW",
                mapping=[],
                status="CREATED",
                correlation_id=uuid4(),
                idempotency_key="cross-owner-forbidden",
                relationship_id=relationship["relationship_id"],
                request_hash="c" * 64,
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

        transfer_relationship, _ = await repository.create_clone_relationship(
            actor_user_id=USER_U,
            destination_guild_id=GUILD_B,
            creation_key="d" * 64,
            source_descriptor={"source_guild_id": GUILD_A},
        )
        transfer, _ = await repository.create_transfer(
            transfer_id=uuid4(),
            actor_user_id=USER_U,
            source_guild_id=GUILD_A,
            destination_guild_id=GUILD_B,
            artifact_id=row["id"],
            artifact_content_hash=portable().content_hash,
            mode="COPY_AS_NEW",
            mapping=[],
            status="CREATED",
            correlation_id=uuid4(),
            idempotency_key="transfer",
            relationship_id=transfer_relationship["relationship_id"],
            request_hash="e" * 64,
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
async def test_ready_semantic_mapping_drift_is_rejected_before_stage05_plan() -> None:
    await seed()
    engine = create_database_engine(APP_URL, pool_size=2)
    try:
        repository = PortabilityRepository(
            create_session_factory(engine),
            ArtifactCipher(InMemoryKeyProvider({1: b"m" * 32}, current_version=1)),
        )
        artifact_row, _ = await repository.create_artifact(
            owner_user_id=USER_U,
            kind="LIBRARY",
            artifact=portable(),
            name="semantic-mapping",
            expires_at=None,
            idempotency_operation="SEMANTIC_MAPPING",
            idempotency_key="artifact",
        )
        relationship, _ = await repository.create_clone_relationship(
            actor_user_id=USER_U,
            destination_guild_id=GUILD_B,
            creation_key="9" * 64,
            source_descriptor={"source_guild_id": GUILD_A},
        )
        relationship_id = relationship["relationship_id"]
        target = 770606060606060601
        seed_transfer_id = uuid4()
        await repository.create_transfer(
            transfer_id=seed_transfer_id,
            actor_user_id=USER_U,
            source_guild_id=GUILD_A,
            destination_guild_id=GUILD_B,
            artifact_id=artifact_row["id"],
            artifact_content_hash=portable().content_hash,
            mode="COPY_AS_NEW",
            mapping=[],
            status="CREATED",
            correlation_id=uuid4(),
            idempotency_key="semantic-binding-seed",
            relationship_id=relationship_id,
            request_hash="8" * 64,
        )
        await repository.save_clone_bindings(
            actor_user_id=USER_U,
            transfer_id=seed_transfer_id,
            destination_guild_id=GUILD_B,
            relationship_id=relationship_id,
            artifact_hash=portable().content_hash,
            bindings=[
                {
                    "logical_ref": "role.staff",
                    "resource_type": "ROLE",
                    "destination_resource_id": target,
                    "binding_origin": "CREATED",
                }
            ],
        )
        read_models = SimpleNamespace(
            guild_snapshot=AsyncMock(return_value=(destination_mapping_snapshot(target), None))
        )
        planning = SimpleNamespace(create=AsyncMock())
        service = PortabilityService(
            repository,
            cast(Any, read_models),
            cast(Any, planning),
            cast(Any, SimpleNamespace()),
        )
        service._compiler = cast(
            Any,
            SimpleNamespace(compile=Mock(side_effect=RuntimeError("crash after READY"))),
        )
        caller_key = "postgres-ready-drift"
        common = {
            "actor_user_id": USER_U,
            "artifact_id": artifact_row["id"],
            "destination_guild_id": GUILD_B,
            "mode": CloneMode.MERGE,
            "explicit_mappings": (),
            "idempotency_key": caller_key,
            "correlation_id": uuid4(),
            "relationship_id": relationship_id,
        }
        with pytest.raises(RuntimeError, match="crash after READY"):
            await service.compile_stored(**cast(Any, common))
        transfer_key = service._stored_transfer_idempotency_key(
            artifact_row["id"], GUILD_B, CloneMode.MERGE, caller_key
        )
        frozen = await repository.find_transfer_by_idempotency(USER_U, transfer_key)
        assert frozen is not None and frozen["status"] == TransferState.READY.value
        assert len(frozen["mapping_hash"]) == 64
        assert frozen["mapping_json"][0]["decision"] == "MAP_EXISTING"
        assert frozen["mapping_json"][0]["destination_ref"] == str(target)

        read_models.guild_snapshot.return_value = (destination_mapping_snapshot(), None)
        service._compiler = DestinationPlanCompiler()
        with pytest.raises(TransferConflict, match="mapping is stale"):
            await service.compile_stored(**cast(Any, common))
        unchanged = await repository.find_transfer_by_idempotency(USER_U, transfer_key)
        assert unchanged is not None
        assert unchanged["status"] == TransferState.READY.value
        assert unchanged["mapping_json"] == frozen["mapping_json"]
        assert unchanged["mapping_hash"] == frozen["mapping_hash"]
        planning.create.assert_not_awaited()
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
        relationship, relationship_created = await repository.create_clone_relationship(
            actor_user_id=USER_U,
            destination_guild_id=GUILD_B,
            creation_key="a" * 64,
            source_descriptor={"source_guild_id": GUILD_A, "authority": "INFORMATIVE_ONLY"},
        )
        relationship_id = relationship["relationship_id"]
        assert relationship_created
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
            relationship_id=relationship_id,
            request_hash="1" * 64,
        )
        assert created and transfer["state_version"] == 1
        for expected, target in (
            (TransferState.CREATED, TransferState.SOURCE_AUTHORIZED),
            (TransferState.SOURCE_AUTHORIZED, TransferState.EXPORTED),
        ):
            transfer = await repository.transition_transfer(
                actor_user_id=USER_U,
                transfer_id=transfer_id,
                expected=expected,
                target=target,
            )
        transfer = await repository.freeze_transfer_mapping(
            actor_user_id=USER_U,
            transfer_id=transfer_id,
            expected=TransferState.EXPORTED,
            mapping=[],
            mapping_hash="2" * 64,
        )
        same_ready = await repository.freeze_transfer_mapping(
            actor_user_id=USER_U,
            transfer_id=transfer_id,
            expected=TransferState.EXPORTED,
            mapping=[],
            mapping_hash="2" * 64,
        )
        assert same_ready["state_version"] == transfer["state_version"]
        with pytest.raises(TransferConflict, match="already frozen"):
            await repository.freeze_transfer_mapping(
                actor_user_id=USER_U,
                transfer_id=transfer_id,
                expected=TransferState.EXPORTED,
                mapping=[{"source_logical_ref": "role.other"}],
                mapping_hash="3" * 64,
            )
        transfer = await repository.compile_transfer(
            actor_user_id=USER_U,
            transfer_id=transfer_id,
            destination_plan_id=None,
            report=[{"outcome": "CLONED", "destructive": False}],
            mapping_hash="2" * 64,
            report_hash="4" * 64,
        )
        assert transfer["status"] == "COMPILED"
        assert transfer["destination_plan_id"] is None
        same_compiled = await repository.compile_transfer(
            actor_user_id=USER_U,
            transfer_id=transfer_id,
            destination_plan_id=None,
            report=[{"outcome": "CLONED", "destructive": False}],
            mapping_hash="2" * 64,
            report_hash="4" * 64,
        )
        assert same_compiled["state_version"] == transfer["state_version"]
        with pytest.raises(TransferConflict, match="immutable"):
            await repository.compile_transfer(
                actor_user_id=USER_U,
                transfer_id=transfer_id,
                destination_plan_id=None,
                report=[{"outcome": "DIFFERENT", "destructive": False}],
                mapping_hash="2" * 64,
                report_hash="6" * 64,
            )

        await repository.save_clone_bindings(
            actor_user_id=USER_U,
            transfer_id=transfer_id,
            destination_guild_id=GUILD_B,
            relationship_id=relationship_id,
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
        owned = await repository.reconcile_bindings(USER_U, GUILD_B, relationship_id)
        foreign = await repository.reconcile_bindings(USER_V, GUILD_B, relationship_id)
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

        await repository.delete_artifact(USER_U, artifact_row["id"])
        with pytest.raises(TransferNotFound):
            await repository.get_transfer(USER_U, transfer_id)
        assert [
            item["logical_ref"]
            for item in await repository.reconcile_bindings(USER_U, GUILD_B, relationship_id)
        ] == ["role.staff"]
        assert (await repository.get_clone_relationship(USER_U, GUILD_B, relationship_id))[
            "relationship_id"
        ] == relationship_id

        expired_artifact, _ = await repository.create_artifact(
            owner_user_id=USER_U,
            kind="CLIPBOARD",
            artifact=portable(),
            name="expired-after-binding",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            idempotency_operation="LIFECYCLE",
            idempotency_key="expired-after-binding",
        )
        expired_transfer_id = uuid4()
        await repository.create_transfer(
            transfer_id=expired_transfer_id,
            actor_user_id=USER_U,
            source_guild_id=GUILD_A,
            destination_guild_id=GUILD_B,
            artifact_id=expired_artifact["id"],
            artifact_content_hash=portable().content_hash,
            mode="RECONCILE",
            mapping=[],
            status="CREATED",
            correlation_id=uuid4(),
            idempotency_key="expired-transfer",
            relationship_id=relationship_id,
            request_hash="5" * 64,
        )
        await repository.save_clone_bindings(
            actor_user_id=USER_U,
            transfer_id=expired_transfer_id,
            destination_guild_id=GUILD_B,
            relationship_id=relationship_id,
            artifact_hash=portable().content_hash,
            bindings=[],
        )
        await repository.list_artifacts(USER_U)
        with pytest.raises(TransferNotFound):
            await repository.get_transfer(USER_U, expired_transfer_id)
        assert await repository.reconcile_bindings(USER_U, GUILD_B, relationship_id) == []
        async with admin.connect() as connection:
            tombstone = (
                (
                    await connection.execute(
                        text(
                            "SELECT active,tombstoned_at FROM portable_clone_bindings "
                            "WHERE relationship_id=:relationship_id AND logical_ref='role.staff'"
                        ),
                        {"relationship_id": relationship_id},
                    )
                )
                .mappings()
                .one()
            )
        assert tombstone["active"] is False and tombstone["tombstoned_at"] is not None
    finally:
        await engine.dispose()
        await admin.dispose()
