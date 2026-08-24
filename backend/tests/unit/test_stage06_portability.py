from __future__ import annotations

import ast
import json
from dataclasses import replace
from datetime import UTC, datetime
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starlette.requests import Request

from did.api.main import create_app
from did.api.stage06 import LiveTransferInput, create_live_transfer
from did.application.auth.service import AuthorizationDenied
from did.application.portability import PortabilityService
from did.cloning import (
    ArtifactSelection,
    DestinationPlanCompiler,
    PortableArtifactBuilder,
    ReconcileScope,
    support_matrix,
)
from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
from did.domain.read_model import (
    ChannelSnapshot,
    CoverageSnapshot,
    FreshnessSnapshot,
    GuildSnapshot,
    OverwriteSnapshot,
    RoleSnapshot,
)
from did.domain.read_model.models import ChannelType
from did.portability import (
    ArtifactCipher,
    ArtifactType,
    CloneMode,
    DependencyGraph,
    DependencyGraphError,
    DestinationCandidate,
    ExplicitMapping,
    InMemoryKeyProvider,
    KeyUnavailable,
    MappingDecision,
    MappingResolver,
    PortableArtifact,
    PortableDependency,
    PortableProvenance,
    PortableResource,
    PortableResourceType,
    TransferState,
    artifact_from_bytes,
    artifact_to_bytes,
    assert_transfer_transition,
)

GUILD_A = 123456789012345678
GUILD_B = 223456789012345678
NOW = datetime(2026, 8, 24, tzinfo=UTC)


def artifact(*resources: PortableResource) -> PortableArtifact:
    return PortableArtifact(
        ArtifactType.CUSTOM_BUNDLE,
        resources,
        roots=tuple(item.logical_key for item in resources),
        provenance=PortableProvenance(str(GUILD_A)),
    )


def role_resource(name: str = "Staff") -> PortableResource:
    return PortableResource.build(
        "role.staff",
        PortableResourceType.ROLE,
        {
            "name": name,
            "permissions": "0",
            "position": 1,
            "color": 0,
            "hoist": False,
            "mentionable": False,
            "managed": False,
        },
    )


def live_snapshot(*, visible: bool = True) -> GuildSnapshot:
    fresh = FreshnessSnapshot(FreshnessState.FRESH, "GATEWAY", 1, NOW, NOW, NOW)
    category_id = 323456789012345678
    channel_id = 423456789012345678
    role_id = 523456789012345678
    roles = (
        RoleSnapshot(GUILD_A, GUILD_A, "@everyone", 0, 0, False, fresh),
        RoleSnapshot(GUILD_A, role_id, "Staff", 1, 8, False, fresh),
    )
    category = ChannelSnapshot(
        GUILD_A,
        category_id,
        ChannelType.GUILD_CATEGORY,
        0,
        None,
        "Ops",
        (),
        True,
        ObservabilityState.VISIBLE,
        fresh,
    )
    channel = ChannelSnapshot(
        GUILD_A,
        channel_id,
        ChannelType.GUILD_TEXT,
        1,
        category_id,
        "staff",
        (OverwriteSnapshot(GUILD_A, channel_id, role_id, 0, 8, 0, NOW),),
        True,
        ObservabilityState.VISIBLE if visible else ObservabilityState.OBFUSCATED,
        fresh,
        topic="private",
        nsfw=False,
    )
    coverage = CoverageSnapshot(
        GUILD_A,
        CoverageMode.FULL,
        FreshnessState.FRESH,
        "GATEWAY",
        1,
        known_channels=2,
        visible_channels=2 if visible else 1,
        obfuscated_channels=0 if visible else 1,
        known_roles=2,
        overwrites_complete=True,
    )
    return GuildSnapshot(GUILD_A, 9, roles, (category, channel), coverage, fresh)


def destination_snapshot() -> GuildSnapshot:
    source = live_snapshot()
    fresh = source.freshness
    coverage = replace(
        source.coverage,
        guild_id=GUILD_B,
        known_channels=0,
        visible_channels=0,
        known_roles=1,
    )
    everyone = RoleSnapshot(GUILD_B, GUILD_B, "@everyone", 0, 0, False, fresh)
    return GuildSnapshot(GUILD_B, 19, (everyone,), (), coverage, fresh)


def test_artifact_is_canonical_immutable_and_round_trips_for_all_input_orders() -> None:
    resources = (
        role_resource(),
        PortableResource.build(
            "channel.staff", PortableResourceType.CHANNEL, {"name": "staff", "type": 0}
        ),
    )
    hashes = {artifact(*ordered).content_hash for ordered in permutations(resources)}
    assert len(hashes) == 1
    encoded = artifact_to_bytes(artifact(*resources))
    assert artifact_from_bytes(encoded) == artifact(*resources)
    assert json.loads(encoded)["content_hash"] == next(iter(hashes))


@pytest.mark.security
@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda value: value.update({"unexpected": True}), "envelope"),
        (lambda value: value.update({"file_schema_version": "future"}), "schema"),
        (lambda value: value.update({"content_hash": "0" * 64}), "hash"),
        (
            lambda value: value["artifact"]["resources"][0]["attributes"].update(
                {"webhook_token": "sensitive"}
            ),
            "forbidden",
        ),
    ],
)
def test_hostile_file_fields_and_tamper_are_rejected(mutation: object, match: str) -> None:
    value = json.loads(artifact_to_bytes(artifact(role_resource())))
    assert callable(mutation)
    mutation(value)
    with pytest.raises(ValueError, match=match):
        artifact_from_bytes(json.dumps(value).encode())


@pytest.mark.security
def test_parser_rejects_oversize_binary_zip_and_does_not_contain_network_fetch() -> None:
    with pytest.raises(ValueError, match="size"):
        artifact_from_bytes(b"x" * 2_000_001)
    with pytest.raises(ValueError, match="UTF-8 JSON"):
        artifact_from_bytes(b"PK\x03\x04not-a-portable-json")
    source = Path("backend/src/did/portability/artifact.py").read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "requests" not in source
    assert "urlopen" not in source


@pytest.mark.security
@pytest.mark.parametrize(
    "raw,match",
    [
        (
            b'{"file_schema_version":"did-portable-file-v1",'
            b'"file_schema_version":"did-portable-file-v1","content_hash":"x",'
            b'"artifact":{}}',
            "duplicate",
        ),
        (
            json.dumps(
                {
                    **json.loads(artifact_to_bytes(artifact(role_resource()))),
                    "artifact": {
                        **json.loads(artifact_to_bytes(artifact(role_resource())))["artifact"],
                        "resources": [
                            {
                                "logical_key": "role.staff",
                                "resource_type": "FUTURE_RESOURCE",
                                "attributes": {},
                            }
                        ],
                    },
                }
            ).encode(),
            "FUTURE_RESOURCE",
        ),
    ],
)
def test_hostile_duplicate_fields_and_unknown_resource_type_are_rejected(
    raw: bytes, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        artifact_from_bytes(raw)


@pytest.mark.security
@pytest.mark.parametrize(
    "forbidden",
    [
        {"capabilities": ["STRUCTURE_WRITE"]},
        {"principal_bindings": [{"discord_user_id": "1"}]},
        {"destination_resource_id": "223456789012345678"},
        {"url": "https://example.invalid/portable-fetch-must-never-run"},
    ],
)
def test_hostile_operational_fields_and_urls_never_produce_a_plan(
    forbidden: dict[str, object],
) -> None:
    value = json.loads(artifact_to_bytes(artifact(role_resource())))
    value["artifact"]["resources"][0]["attributes"].update(forbidden)
    with pytest.raises(ValueError):
        artifact_from_bytes(json.dumps(value).encode())


def test_dependency_graph_orders_closure_and_rejects_cycles() -> None:
    channel = PortableResource.build(
        "channel.staff", PortableResourceType.CHANNEL, {"name": "staff", "type": 0}
    )
    role = role_resource()
    overwrite = PortableResource.build(
        "overwrite.staff",
        PortableResourceType.OVERWRITE,
        {"target_type": 0, "allow": "8", "deny": "0"},
    )
    value = PortableArtifact(
        ArtifactType.CHANNEL,
        (overwrite, channel, role),
        (
            PortableDependency("overwrite.staff", "channel.staff", "channel"),
            PortableDependency("overwrite.staff", "role.staff", "principal"),
        ),
        ("overwrite.staff",),
    )
    graph = DependencyGraph.build(value)
    assert graph.closure(("overwrite.staff",)) == (
        "channel.staff",
        "role.staff",
        "overwrite.staff",
    )
    cyclic = PortableArtifact(
        ArtifactType.CUSTOM_BUNDLE,
        (channel, role),
        (
            PortableDependency("channel.staff", "role.staff", "parent"),
            PortableDependency("role.staff", "channel.staff", "subject"),
        ),
        ("channel.staff",),
    )
    with pytest.raises(DependencyGraphError, match="cycle"):
        DependencyGraph.build(cyclic)


@pytest.mark.security
def test_mapping_never_uses_source_id_or_name_as_identity_and_requires_confirmation() -> None:
    value = artifact(role_resource())
    graph = DependencyGraph.build(value)
    same_source_id = DestinationCandidate(
        GUILD_B,
        PortableResourceType.ROLE,
        "523456789012345678",
        "different",
    )
    same_name = DestinationCandidate(
        GUILD_B, PortableResourceType.ROLE, "623456789012345678", "Staff"
    )
    resolver = MappingResolver()
    copy = resolver.resolve(
        graph,
        destination_guild_id=GUILD_B,
        mode=CloneMode.COPY_AS_NEW,
        candidates=(same_source_id, same_name),
    )
    assert copy[0].decision is MappingDecision.CREATE
    merge = resolver.resolve(
        graph,
        destination_guild_id=GUILD_B,
        mode=CloneMode.MERGE,
        candidates=(same_source_id, same_name),
    )
    assert merge[0].decision is MappingDecision.MANUAL
    assert merge[0].candidate_refs == (same_name.destination_ref,)


@pytest.mark.security
def test_mapping_rejects_foreign_wrong_type_and_unconfirmed_explicit_targets() -> None:
    value = artifact(role_resource())
    graph = DependencyGraph.build(value)
    candidate = DestinationCandidate(
        GUILD_B, PortableResourceType.ROLE, "623456789012345678", "Staff"
    )
    resolver = MappingResolver()
    unconfirmed = resolver.resolve(
        graph,
        destination_guild_id=GUILD_B,
        mode=CloneMode.MERGE,
        candidates=(candidate,),
        explicit=(
            ExplicitMapping(
                "role.staff",
                GUILD_B,
                candidate.destination_ref,
                PortableResourceType.ROLE,
                False,
            ),
        ),
    )
    assert unconfirmed[0].decision is MappingDecision.MANUAL
    with pytest.raises(ValueError, match="foreign or incompatible"):
        resolver.resolve(
            graph,
            destination_guild_id=GUILD_B,
            mode=CloneMode.MERGE,
            candidates=(candidate,),
            explicit=(
                ExplicitMapping(
                    "role.staff",
                    GUILD_A,
                    candidate.destination_ref,
                    PortableResourceType.ROLE,
                    True,
                ),
            ),
        )


def test_policy_principal_requires_confirmed_destination_role_mapping() -> None:
    requirement = PortableResource.build(
        "principal.moderator",
        PortableResourceType.PRINCIPAL_REQUIREMENT,
        {"kind": "ROLE", "name": "Moderators"},
    )
    policy = PortableResource.build(
        "policy.review",
        PortableResourceType.POLICY,
        {"name": "Review", "rules": ["review.read"]},
    )
    value = PortableArtifact(
        ArtifactType.CUSTOM_BUNDLE,
        (requirement, policy),
        (PortableDependency("policy.review", "principal.moderator", "principal"),),
        ("policy.review",),
    )
    candidate = DestinationCandidate(
        GUILD_B, PortableResourceType.ROLE, "623456789012345678", "Moderators"
    )
    resolver = MappingResolver()
    automatic = resolver.resolve(
        DependencyGraph.build(value),
        destination_guild_id=GUILD_B,
        mode=CloneMode.MERGE,
        candidates=(candidate,),
    )
    assert (
        next(
            item for item in automatic if item.source_logical_ref == "principal.moderator"
        ).decision
        is MappingDecision.MANUAL
    )
    confirmed = resolver.resolve(
        DependencyGraph.build(value),
        destination_guild_id=GUILD_B,
        mode=CloneMode.MERGE,
        candidates=(candidate,),
        explicit=(
            ExplicitMapping(
                "principal.moderator",
                GUILD_B,
                candidate.destination_ref,
                PortableResourceType.PRINCIPAL_REQUIREMENT,
                True,
            ),
        ),
    )
    compiled = DestinationPlanCompiler().compile(
        value,
        destination_guild_id=GUILD_B,
        mode=CloneMode.MERGE,
        resolutions=confirmed,
        candidates=(candidate,),
    )
    assert compiled.local_resources == ("policy.review",)
    assert support_matrix()[PortableResourceType.POLICY.value][CloneMode.MERGE.value] == (
        "CREATE_DEFINITION_WITHOUT_BINDINGS",
        "REPORT",
    )


def test_everyone_is_rebound_and_managed_principals_are_not_created() -> None:
    everyone = PortableResource.build(
        "principal.everyone", PortableResourceType.SYSTEM_PRINCIPAL, {"kind": "EVERYONE"}
    )
    managed = PortableResource.build(
        "role.bot",
        PortableResourceType.ROLE,
        {"name": "bot", "managed": True, "permissions": "0"},
    )
    resolutions = MappingResolver().resolve(
        DependencyGraph.build(artifact(everyone, managed)),
        destination_guild_id=GUILD_B,
        mode=CloneMode.COPY_AS_NEW,
    )
    by_ref = {item.source_logical_ref: item for item in resolutions}
    assert by_ref["principal.everyone"].destination_ref == str(GUILD_B)
    assert by_ref["role.bot"].decision is MappingDecision.MANUAL


def test_bot_webhook_and_member_requirements_are_always_visible_manual_mappings() -> None:
    requirements = (
        PortableResource.build(
            "principal.member", PortableResourceType.PRINCIPAL_REQUIREMENT, {"kind": "MEMBER"}
        ),
        PortableResource.build("bot.audit", PortableResourceType.BOT_REFERENCE, {"name": "audit"}),
        PortableResource.build(
            "webhook.audit", PortableResourceType.WEBHOOK_REFERENCE, {"name": "audit"}
        ),
    )
    resolutions = MappingResolver().resolve(
        DependencyGraph.build(artifact(*requirements)),
        destination_guild_id=GUILD_B,
        mode=CloneMode.MAXIMUM_COMPATIBLE,
    )
    assert {item.decision for item in resolutions} == {MappingDecision.MANUAL}
    assert all(item.confirmation_required for item in resolutions)


def test_live_builder_closes_category_roles_and_overwrites_without_operational_ids() -> None:
    value = PortableArtifactBuilder().build_live(
        live_snapshot(),
        ArtifactSelection(
            ArtifactType.CATEGORY,
            category_ids=(323456789012345678,),
        ),
    )
    types = {resource.resource_type for resource in value.resources}
    assert {
        PortableResourceType.CATEGORY,
        PortableResourceType.CHANNEL,
        PortableResourceType.ROLE,
        PortableResourceType.OVERWRITE,
    } <= types
    payload = value.canonical_payload()
    attributes = json.dumps([item["attributes"] for item in payload["resources"]])
    assert "523456789012345678" not in attributes
    assert "423456789012345678" not in attributes
    with pytest.raises(ValueError, match="stale, hidden or inaccessible"):
        PortableArtifactBuilder().build_live(
            live_snapshot(visible=False),
            ArtifactSelection(
                ArtifactType.CHANNEL,
                channel_ids=(423456789012345678,),
            ),
        )


def test_live_builder_ignores_unrelated_obfuscated_channels_outside_the_closed_selection() -> None:
    source = live_snapshot()
    unrelated = replace(
        source.channels[1],
        channel_id=623456789012345678,
        name="unrelated-hidden",
        parent_id=None,
        overwrites=(),
        observability=ObservabilityState.OBFUSCATED,
    )
    source = replace(source, channels=(*source.channels, unrelated))
    value = PortableArtifactBuilder().build_live(
        source,
        ArtifactSelection(
            ArtifactType.CATEGORY,
            category_ids=(323456789012345678,),
        ),
    )
    assert "unrelated-hidden" not in artifact_to_bytes(value).decode("utf-8")


def test_compiler_targets_only_destination_and_reconcile_deletes_need_explicit_scope() -> None:
    value = artifact(role_resource())
    resolutions = MappingResolver().resolve(
        DependencyGraph.build(value),
        destination_guild_id=GUILD_B,
        mode=CloneMode.RECONCILE,
    )
    compiled = DestinationPlanCompiler().compile(
        value,
        destination_guild_id=GUILD_B,
        mode=CloneMode.RECONCILE,
        resolutions=resolutions,
    )
    assert compiled.graph.guild_id == GUILD_B
    assert all(node.discord_id is None for node in compiled.graph.nodes)
    assert not any(entry.destructive for entry in compiled.report.entries)

    related = DestinationCandidate(
        GUILD_B, PortableResourceType.ROLE, "723456789012345678", "old-clone-role"
    )
    unrelated = DestinationCandidate(
        GUILD_B, PortableResourceType.CHANNEL, "823456789012345678", "unrelated"
    )
    scoped = DestinationPlanCompiler().compile(
        value,
        destination_guild_id=GUILD_B,
        mode=CloneMode.RECONCILE,
        resolutions=resolutions,
        candidates=(related, unrelated),
        reconcile_scope=ReconcileScope((related,)),
    )
    deletes = [entry.destination_ref for entry in scoped.report.entries if entry.destructive]
    assert deletes == [related.destination_ref]
    assert unrelated.destination_ref not in deletes


def test_transfer_state_machine_is_explicit_and_does_not_duplicate_plan_apply_states() -> None:
    assert TransferState.READY.can_transition_to(TransferState.COMPILED)
    assert_transfer_transition(TransferState.READY, TransferState.COMPILED)
    with pytest.raises(ValueError, match="invalid transfer state"):
        assert_transfer_transition(TransferState.COMPILED, TransferState.READY)
    assert not {"CONFIRMED", "APPLYING", "SUCCEEDED"} & {state.value for state in TransferState}


@pytest.mark.security
def test_envelope_encryption_detects_tamper_and_supports_key_rotation() -> None:
    key_v1 = b"1" * 32
    key_v2 = b"2" * 32
    artifact_id = uuid4()
    value = artifact(role_resource())
    old_cipher = ArtifactCipher(InMemoryKeyProvider({1: key_v1}, current_version=1))
    encrypted = old_cipher.encrypt(value, artifact_id=artifact_id, owner_user_id=99)
    rotated = ArtifactCipher(InMemoryKeyProvider({1: key_v1, 2: key_v2}, current_version=2))
    assert (
        rotated.decrypt(
            encrypted,
            artifact_id=artifact_id,
            owner_user_id=99,
            schema_version=value.schema_version,
        )
        == value
    )
    reencrypted = rotated.reencrypt(
        encrypted,
        artifact_id=artifact_id,
        owner_user_id=99,
        schema_version=value.schema_version,
    )
    assert reencrypted.key_version == 2
    with pytest.raises(ValueError, match="integrity"):
        rotated.decrypt(
            replace(encrypted, ciphertext=encrypted.ciphertext[:-1] + b"x"),
            artifact_id=artifact_id,
            owner_user_id=99,
            schema_version=value.schema_version,
        )
    for changed in (
        replace(encrypted, wrapped_dek=encrypted.wrapped_dek[:-1] + b"x"),
        replace(encrypted, nonce=b"0" * 12),
        replace(encrypted, wrap_nonce=b"1" * 12),
        replace(encrypted, content_hash="0" * 64),
    ):
        with pytest.raises(ValueError, match="integrity"):
            rotated.decrypt(
                changed,
                artifact_id=artifact_id,
                owner_user_id=99,
                schema_version=value.schema_version,
            )
    with pytest.raises(ValueError, match="integrity"):
        rotated.decrypt(
            encrypted,
            artifact_id=uuid4(),
            owner_user_id=99,
            schema_version=value.schema_version,
        )
    with pytest.raises(ValueError, match="integrity"):
        rotated.decrypt(
            encrypted,
            artifact_id=artifact_id,
            owner_user_id=100,
            schema_version=value.schema_version,
        )
    with pytest.raises(KeyUnavailable):
        ArtifactCipher(InMemoryKeyProvider({2: key_v2}, current_version=2)).decrypt(
            encrypted,
            artifact_id=artifact_id,
            owner_user_id=99,
            schema_version=value.schema_version,
        )


def test_stage06_routes_are_registered_including_bounded_file_import() -> None:
    application = create_app()
    contract = application.openapi()
    expected = {
        "/api/v1/guilds/{guild_id}/exports/portable",
        "/api/v1/me/portable-artifacts",
        "/api/v1/me/portable-artifacts/{artifact_id}/clone",
        "/api/v1/guilds/{guild_id}/imports/plan",
        "/api/v1/transfers",
        "/api/v1/transfers/{transfer_id}",
        "/api/v1/me/portable-artifacts/import",
    }
    assert expected <= set(contract["paths"])


@pytest.mark.security
def test_portability_architecture_has_no_transport_persistence_network_or_mutation_backdoor() -> (
    None
):
    forbidden_domain = ("fastapi", "sqlalchemy", "redis", "discord", "did.infrastructure")
    violations: list[str] = []
    for path in Path("backend/src/did/portability").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import) and node.names:
                module = node.names[0].name
            if module and module.startswith(forbidden_domain):
                violations.append(f"{path}:{node.lineno}:{module}")
    assert violations == []
    orchestrator = Path("backend/src/did/application/portability/service.py").read_text(
        encoding="utf-8"
    )
    assert "DiscordPyMutableAdapter" not in orchestrator
    assert "ApplyPlanExecutor" not in orchestrator
    assert "RedisGuildMutationLock" not in orchestrator
    parser = Path("backend/src/did/portability/artifact.py").read_text(encoding="utf-8")
    assert not any(client in parser for client in ("httpx", "aiohttp", "requests", "urlopen"))


@pytest.mark.asyncio
@pytest.mark.security
async def test_live_transfer_requires_source_before_export_and_destination_before_compile() -> None:
    body = LiveTransferInput.model_validate(
        {
            "source_guild_id": str(GUILD_A),
            "destination_guild_id": str(GUILD_B),
            "selection": {
                "artifact_type": "CHANNEL",
                "channel_ids": ["423456789012345678"],
            },
        }
    )
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.correlation_id = str(uuid4())
    session = SimpleNamespace(discord_user_id=99)
    service = SimpleNamespace(export_live=AsyncMock(), compile_stored=AsyncMock())

    source_denied = SimpleNamespace(
        authorization=SimpleNamespace(authorize=AsyncMock(side_effect=AuthorizationDenied())),
        portability=service,
        portability_repository=object(),
    )
    with pytest.raises(AuthorizationDenied):
        await create_live_transfer(
            body,
            request,
            "source-denied",
            cast(Any, session),
            cast(Any, source_denied),
        )
    service.export_live.assert_not_awaited()
    service.compile_stored.assert_not_awaited()

    artifact_id = uuid4()
    service.export_live.return_value = ({"id": artifact_id}, True)

    async def authorize_destination_denied(**kwargs: object) -> None:
        if kwargs["guild_id"] == GUILD_B:
            raise AuthorizationDenied()

    destination_denied = SimpleNamespace(
        authorization=SimpleNamespace(
            authorize=AsyncMock(side_effect=authorize_destination_denied)
        ),
        portability=service,
        portability_repository=object(),
    )
    with pytest.raises(AuthorizationDenied):
        await create_live_transfer(
            body,
            request,
            "destination-denied",
            cast(Any, session),
            cast(Any, destination_denied),
        )
    service.export_live.assert_awaited_once()
    service.compile_stored.assert_not_awaited()


@pytest.mark.asyncio
async def test_stored_artifact_compile_reads_destination_only_and_builds_one_stage05_plan() -> None:
    artifact_id = uuid4()
    plan_id = uuid4()
    transfer_id = uuid4()
    value = artifact(role_resource())
    repository = SimpleNamespace(
        get_artifact=AsyncMock(return_value=({"source_guild_id": GUILD_A}, value)),
        create_transfer=AsyncMock(
            return_value=(
                {
                    "id": transfer_id,
                    "destination_guild_id": GUILD_B,
                    "portable_artifact_id": artifact_id,
                    "source_guild_id": GUILD_A,
                },
                True,
            )
        ),
        compile_transfer=AsyncMock(
            return_value={
                "id": transfer_id,
                "destination_guild_id": GUILD_B,
                "portable_artifact_id": artifact_id,
                "source_guild_id": GUILD_A,
                "destination_plan_id": plan_id,
            }
        ),
        audit_boundary=AsyncMock(),
    )
    read_models = SimpleNamespace(
        guild_snapshot=AsyncMock(return_value=(destination_snapshot(), None))
    )
    planning = SimpleNamespace(create=AsyncMock(return_value=({"id": plan_id}, True)))
    service = PortabilityService(
        cast(Any, repository),
        cast(Any, read_models),
        cast(Any, planning),
        cast(Any, SimpleNamespace()),
    )
    transfer, plan, created = await service.compile_stored(
        actor_user_id=99,
        artifact_id=artifact_id,
        destination_guild_id=GUILD_B,
        mode=CloneMode.COPY_AS_NEW,
        explicit_mappings=(),
        idempotency_key="stored-no-source",
        correlation_id=uuid4(),
    )
    assert created is True
    assert transfer["destination_plan_id"] == plan_id
    assert plan["id"] == plan_id
    read_models.guild_snapshot.assert_awaited_once_with(GUILD_B, 99)
    planning.create.assert_awaited_once()
    graph = planning.create.await_args.kwargs["graph"]
    assert graph.guild_id == GUILD_B
