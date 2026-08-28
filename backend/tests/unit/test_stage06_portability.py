from __future__ import annotations

import ast
import json
from dataclasses import replace
from datetime import UTC, datetime
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY, AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from starlette.requests import Request

from did.api.main import create_app
from did.api.stage06 import LiveTransferInput, create_live_transfer
from did.application.auth.service import AuthorizationDenied
from did.application.portability import MappingRequired, PortabilityService
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
from did.infrastructure.portability_repository import TransferConflict
from did.planning.compiler import PlanCompiler
from did.planning.diff import DiffEngine
from did.planning.models import DiffAction, NodePresence, OperationType
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


def destination_snapshot_with_roles(
    *roles: tuple[int, str, int],
) -> GuildSnapshot:
    base = destination_snapshot()
    return replace(
        base,
        roles=(
            base.roles[0],
            *(
                RoleSnapshot(GUILD_B, role_id, name, 1, permissions, False, base.freshness)
                for role_id, name, permissions in roles
            ),
        ),
        coverage=replace(base.coverage, known_roles=1 + len(roles)),
    )


def service_repository(
    value: PortableArtifact,
    *,
    artifact_id: UUID,
    transfer_id: UUID,
    relationship_id: UUID | None = None,
    bindings: list[dict[str, object]] | None = None,
) -> tuple[SimpleNamespace, UUID, dict[str, object]]:
    """Stateful repository double that preserves the Stage 06 transfer lifecycle."""

    relation_id = relationship_id or uuid4()
    row: dict[str, object] = {
        "id": transfer_id,
        "destination_guild_id": GUILD_B,
        "portable_artifact_id": artifact_id,
        "artifact_content_hash": value.content_hash,
        "source_guild_id": GUILD_A,
        "relationship_id": relation_id,
        "status": TransferState.CREATED.value,
        "mapping_hash": None,
        "destination_plan_id": None,
    }
    created = True

    async def create_transfer(**kwargs: object) -> tuple[dict[str, object], bool]:
        nonlocal created
        result = (dict(row), created)
        created = False
        return result

    async def transition_transfer(**kwargs: object) -> dict[str, object]:
        expected = cast(TransferState, kwargs["expected"])
        target = cast(TransferState, kwargs["target"])
        assert row["status"] == expected.value
        row["status"] = target.value
        if "mapping" in kwargs:
            row["mapping_json"] = kwargs["mapping"]
        return dict(row)

    async def freeze_transfer_mapping(**kwargs: object) -> dict[str, object]:
        expected = cast(TransferState, kwargs["expected"])
        assert row["status"] == expected.value
        row["status"] = TransferState.READY.value
        row["mapping_json"] = kwargs["mapping"]
        row["mapping_hash"] = kwargs["mapping_hash"]
        return dict(row)

    async def compile_transfer(**kwargs: object) -> dict[str, object]:
        assert row["status"] == TransferState.READY.value
        row["status"] = TransferState.COMPILED.value
        row["destination_plan_id"] = kwargs["destination_plan_id"]
        row["report_json"] = kwargs["report"]
        return dict(row)

    repository = SimpleNamespace(
        get_artifact=AsyncMock(return_value=({"source_guild_id": GUILD_A}, value)),
        create_clone_relationship=AsyncMock(
            return_value=(
                {
                    "relationship_id": relation_id,
                    "destination_guild_id": GUILD_B,
                    "status": "ACTIVE",
                },
                True,
            )
        ),
        get_clone_relationship=AsyncMock(
            return_value={
                "relationship_id": relation_id,
                "destination_guild_id": GUILD_B,
                "status": "ACTIVE",
            }
        ),
        create_transfer=AsyncMock(side_effect=create_transfer),
        transition_transfer=AsyncMock(side_effect=transition_transfer),
        freeze_transfer_mapping=AsyncMock(side_effect=freeze_transfer_mapping),
        compile_transfer=AsyncMock(side_effect=compile_transfer),
        reconcile_bindings=AsyncMock(return_value=bindings or []),
        audit_boundary=AsyncMock(),
    )
    return repository, relation_id, row


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
    with pytest.raises(ValueError, match="must be confirmed"):
        resolver.resolve(
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


def test_live_builder_excludes_confirmed_deleted_children_from_category_generations() -> None:
    source = live_snapshot()
    deleted = replace(
        source.channels[1],
        observability=ObservabilityState.DELETED_CONFIRMED,
        overwrites_complete=False,
    )
    value = PortableArtifactBuilder().build_live(
        replace(source, channels=(source.channels[0], deleted)),
        ArtifactSelection(
            ArtifactType.CATEGORY,
            category_ids=(source.channels[0].channel_id,),
        ),
    )
    assert all(
        resource.attribute_map().get("name") != source.channels[1].name
        for resource in value.resources
    )


def test_live_builder_logical_refs_survive_reorder_removal_addition_and_attribute_change() -> None:
    source = live_snapshot()
    survivor_id = source.roles[1].role_id
    removed_id = 623456789012345671
    added_id = 623456789012345672
    generation_one = replace(
        source,
        roles=(
            *source.roles,
            RoleSnapshot(GUILD_A, removed_id, "Remove me", 2, 0, False, source.freshness),
        ),
    )
    generation_two = replace(
        source,
        roles=(
            source.roles[0],
            RoleSnapshot(GUILD_A, added_id, "Added", 3, 4, False, source.freshness),
            replace(source.roles[1], name="Staff renamed", position=2, permissions=16),
        ),
    )
    builder = PortableArtifactBuilder()
    first = builder.build_live(
        generation_one,
        ArtifactSelection(ArtifactType.CUSTOM_BUNDLE, role_ids=(survivor_id, removed_id)),
    )
    second = builder.build_live(
        generation_two,
        ArtifactSelection(ArtifactType.CUSTOM_BUNDLE, role_ids=(added_id, survivor_id)),
    )
    first_refs = {item.logical_key for item in first.resources}
    second_refs = {item.logical_key for item in second.resources}
    survivor_refs = first_refs & second_refs
    assert len(survivor_refs) == 1
    survivor_ref = survivor_refs.pop()
    assert survivor_ref.startswith("role.k")
    first_resource = next(item for item in first.resources if item.logical_key == survivor_ref)
    second_resource = next(item for item in second.resources if item.logical_key == survivor_ref)
    assert first_resource.attributes != second_resource.attributes
    assert not first_refs - {survivor_ref} & second_refs
    assert all(str(survivor_id) not in ref and str(added_id) not in ref for ref in second_refs)


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


def test_merge_keeps_destination_identity_but_emits_portable_role_and_channel_updates() -> None:
    role_id = 623456789012345678
    channel_id = 723456789012345678
    fresh = destination_snapshot().freshness
    destination = replace(
        destination_snapshot(),
        roles=(
            destination_snapshot().roles[0],
            RoleSnapshot(GUILD_B, role_id, "Old Staff", 1, 0, False, fresh),
        ),
        channels=(
            ChannelSnapshot(
                GUILD_B,
                channel_id,
                ChannelType.GUILD_TEXT,
                0,
                None,
                "old-room",
                (),
                True,
                ObservabilityState.VISIBLE,
                fresh,
                topic="old topic",
                nsfw=False,
                rate_limit_per_user=0,
                default_auto_archive_duration=60,
            ),
        ),
    )
    value = artifact(
        role_resource("New Staff"),
        PortableResource.build(
            "channel.staff",
            PortableResourceType.CHANNEL,
            {
                "name": "new-room",
                "type": 0,
                "position": 0,
                "topic": "portable topic",
                "nsfw": False,
                "flags": 0,
                "rate_limit_per_user": 15,
                "default_auto_archive_duration": 1440,
            },
        ),
    )
    candidates = PortabilityService._destination_candidates(destination)
    mappings = (
        ExplicitMapping("role.staff", GUILD_B, str(role_id), PortableResourceType.ROLE, True),
        ExplicitMapping(
            "channel.staff", GUILD_B, str(channel_id), PortableResourceType.CHANNEL, True
        ),
    )
    resolutions = MappingResolver().resolve(
        DependencyGraph.build(value),
        destination_guild_id=GUILD_B,
        mode=CloneMode.MERGE,
        candidates=candidates,
        explicit=mappings,
    )
    compiled = DestinationPlanCompiler().compile(
        value,
        destination_guild_id=GUILD_B,
        mode=CloneMode.MERGE,
        resolutions=resolutions,
        candidates=candidates,
    )
    assert compiled.graph is not None
    role_node = compiled.graph.node("role.staff")
    channel_node = compiled.graph.node("channel.staff")
    assert role_node is not None and role_node.discord_id == role_id
    assert role_node.property_map()["name"] == "New Staff"
    assert channel_node is not None and channel_node.discord_id == channel_id
    assert channel_node.property_map()["rate_limit_per_user"] == 15
    diffs = DiffEngine().compare(destination, compiled.graph)
    assert {entry.action for entry in diffs} == {DiffAction.UPDATE}
    operations = PlanCompiler().compile(destination, compiled.graph, plan_id=uuid4())
    assert {item.operation_type for item in operations} == {
        OperationType.UPDATE_ROLE,
        OperationType.UPDATE_CHANNEL,
    }


def test_maximum_compatible_is_truthful_report_only_with_no_destination_graph() -> None:
    value = artifact(
        role_resource(),
        PortableResource.build(
            "channel.forum",
            PortableResourceType.CHANNEL,
            {"name": "forum", "type": 15, "position": 0},
        ),
    )
    resolutions = MappingResolver().resolve(
        DependencyGraph.build(value),
        destination_guild_id=GUILD_B,
        mode=CloneMode.MAXIMUM_COMPATIBLE,
    )
    compiled = DestinationPlanCompiler().compile(
        value,
        destination_guild_id=GUILD_B,
        mode=CloneMode.MAXIMUM_COMPATIBLE,
        resolutions=resolutions,
    )
    assert compiled.graph is None
    assert compiled.no_mutation is True
    outcomes = {entry.logical_ref: entry.outcome.value for entry in compiled.report.entries}
    assert outcomes == {"channel.forum": "IMPOSSIBLE", "role.staff": "CLONED"}


def test_mapping_rejects_duplicate_unknown_and_duplicate_destination_claims() -> None:
    value = artifact(
        role_resource(),
        PortableResource.build(
            "role.other", PortableResourceType.ROLE, {"name": "Other", "permissions": "0"}
        ),
    )
    graph = DependencyGraph.build(value)
    candidate = DestinationCandidate(
        GUILD_B, PortableResourceType.ROLE, "623456789012345678", "Staff"
    )
    duplicate = ExplicitMapping(
        "role.staff", GUILD_B, candidate.destination_ref, PortableResourceType.ROLE, True
    )
    with pytest.raises(ValueError, match="duplicate explicit"):
        MappingResolver().resolve(
            graph,
            destination_guild_id=GUILD_B,
            mode=CloneMode.MERGE,
            candidates=(candidate,),
            explicit=(duplicate, duplicate),
        )
    with pytest.raises(ValueError, match="unknown source"):
        MappingResolver().resolve(
            graph,
            destination_guild_id=GUILD_B,
            mode=CloneMode.MERGE,
            candidates=(candidate,),
            explicit=(replace(duplicate, source_logical_ref="role.unknown"),),
        )
    with pytest.raises(ValueError, match="cannot claim"):
        MappingResolver().resolve(
            graph,
            destination_guild_id=GUILD_B,
            mode=CloneMode.MERGE,
            candidates=(candidate,),
            explicit=(duplicate, replace(duplicate, source_logical_ref="role.other")),
        )


def test_portable_attribute_schemas_fail_closed_and_channel_matrix_is_explicit() -> None:
    with pytest.raises(ValueError, match="unsupported portable attributes"):
        PortableResource.build(
            "role.bad", PortableResourceType.ROLE, {"name": "bad", "mystery": True}
        )
    matrix = support_matrix()
    assert matrix["version"]["value"] == ("did-clone-support-v2",)
    assert matrix["CHANNEL_TYPES"]["0_TEXT"][0] == "PARTIAL"
    assert "flags_update_only_reported_on_create" in matrix["CHANNEL_TYPES"]["0_TEXT"]
    assert matrix["CHANNEL_TYPES"]["15_FORUM"][0] == "UNSUPPORTED"


@pytest.mark.parametrize(
    ("resource_type", "attributes", "match"),
    [
        (PortableResourceType.ROLE, {"name": ["staff"]}, "bounded string"),
        (PortableResourceType.ROLE, {"permissions": {}}, "decimal string"),
        (
            PortableResourceType.CHANNEL,
            {"name": "text", "type": True},
            "type must be an integer",
        ),
        (
            PortableResourceType.CHANNEL,
            {"name": "text", "type": 0, "rate_limit_per_user": 21_601},
            "bounded integer",
        ),
        (
            PortableResourceType.CHANNEL,
            {"name": "text", "type": 0, "bitrate": 64_000},
            "voice-only",
        ),
        (
            PortableResourceType.OVERWRITE,
            {"target_type": 2, "allow": "0", "deny": "0"},
            "target_type",
        ),
    ],
)
def test_portable_attribute_types_and_bounds_reject_hostile_values(
    resource_type: PortableResourceType,
    attributes: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        PortableResource.build("hostile.value", resource_type, attributes)


def test_full_caller_idempotency_material_is_hashed_without_prefix_truncation_collision() -> None:
    artifact_id = uuid4()
    prefix = "x" * 159
    first = PortabilityService._planning_idempotency_key(
        artifact_id, GUILD_B, CloneMode.MERGE, "1" * 64, prefix + "a"
    )
    second = PortabilityService._planning_idempotency_key(
        artifact_id, GUILD_B, CloneMode.MERGE, "1" * 64, prefix + "b"
    )
    repeated = PortabilityService._planning_idempotency_key(
        artifact_id, GUILD_B, CloneMode.MERGE, "1" * 64, prefix + "a"
    )
    assert first != second
    assert first == repeated
    assert len(first) <= 160


def test_semantic_mapping_hash_includes_intent_and_excludes_diagnostics() -> None:
    explicit = (
        ExplicitMapping(
            "role.staff", GUILD_B, "623456789012345678", PortableResourceType.ROLE, True
        ),
    )
    resolved = [
        {
            "source_logical_ref": "role.staff",
            "resource_type": "ROLE",
            "decision": "MAP_EXISTING",
            "destination_ref": "623456789012345678",
            "confirmation_required": False,
            "reason": "mapping.explicit_confirmed",
            "score": 100,
            "candidate_refs": ["623456789012345678"],
            "confirmed_by": "99",
            "confirmed_at": "TRANSFER_CREATED_AT",
        }
    ]
    expected = PortabilityService._semantic_mapping_hash(explicit, resolved)
    diagnostics_changed = [
        {
            **resolved[0],
            "reason": "different wording",
            "score": 1,
            "candidate_refs": ["999999999999999999"],
            "confirmed_by": "100",
            "confirmed_at": "different timestamp",
        }
    ]
    assert PortabilityService._semantic_mapping_hash(explicit, diagnostics_changed) == expected
    assert (
        PortabilityService._semantic_mapping_hash(
            explicit,
            [{**resolved[0], "destination_ref": "723456789012345678"}],
        )
        != expected
    )
    assert PortabilityService._semantic_mapping_hash((), resolved) != expected


def test_transfer_state_machine_is_explicit_and_does_not_duplicate_plan_apply_states() -> None:
    assert TransferState.READY.can_transition_to(TransferState.COMPILED)
    assert_transfer_transition(TransferState.READY, TransferState.COMPILED)
    with pytest.raises(ValueError, match="invalid transfer state"):
        assert_transfer_transition(TransferState.COMPILED, TransferState.READY)
    assert not {"CONFIRMED", "APPLYING", "SUCCEEDED"} & {state.value for state in TransferState}


@pytest.mark.security
def test_envelope_encryption_detects_tamper_and_supports_key_rotation() -> None:
    def flip_last_byte(value: bytes) -> bytes:
        return value[:-1] + bytes((value[-1] ^ 0x01,))

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
            replace(encrypted, ciphertext=flip_last_byte(encrypted.ciphertext)),
            artifact_id=artifact_id,
            owner_user_id=99,
            schema_version=value.schema_version,
        )
    for changed in (
        replace(encrypted, wrapped_dek=flip_last_byte(encrypted.wrapped_dek)),
        replace(encrypted, nonce=flip_last_byte(encrypted.nonce)),
        replace(encrypted, wrap_nonce=flip_last_byte(encrypted.wrap_nonce)),
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
    relationship_id = uuid4()
    transfer_id = uuid4()
    service = SimpleNamespace(
        find_live_export=AsyncMock(return_value=None),
        find_resumable_transfer=AsyncMock(return_value=None),
        export_live=AsyncMock(),
        prepare_stored_transfer=AsyncMock(),
        compile_stored=AsyncMock(),
    )

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
    service.prepare_stored_transfer.return_value = (
        {
            "id": transfer_id,
            "relationship_id": relationship_id,
            "artifact_content_hash": "a" * 64,
        },
        True,
        object(),
    )

    async def authorize_destination_denied(**kwargs: object) -> None:
        if kwargs["guild_id"] == GUILD_B:
            raise AuthorizationDenied()

    destination_denied = SimpleNamespace(
        authorization=SimpleNamespace(
            authorize=AsyncMock(side_effect=authorize_destination_denied)
        ),
        portability=service,
        portability_repository=SimpleNamespace(audit_boundary=AsyncMock()),
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
    service.prepare_stored_transfer.assert_awaited_once()
    service.compile_stored.assert_not_awaited()

    service.find_live_export.return_value = {"id": artifact_id}
    service.find_resumable_transfer.return_value = {
        "id": transfer_id,
        "status": TransferState.EXPORTED.value,
    }
    service.compile_stored.side_effect = RuntimeError("reached destination compile")
    retry_authorization = AsyncMock()
    retry = SimpleNamespace(
        authorization=SimpleNamespace(authorize=retry_authorization),
        portability=service,
        portability_repository=SimpleNamespace(audit_boundary=AsyncMock()),
    )
    with pytest.raises(RuntimeError, match="reached destination compile"):
        await create_live_transfer(
            body,
            request,
            "destination-denied",
            cast(Any, session),
            cast(Any, retry),
        )
    assert service.export_live.await_count == 1
    assert retry_authorization.await_count == 2
    assert all(call.kwargs["guild_id"] == GUILD_B for call in retry_authorization.await_args_list)


@pytest.mark.asyncio
async def test_stored_artifact_compile_reads_destination_only_and_builds_one_stage05_plan() -> None:
    artifact_id = uuid4()
    plan_id = uuid4()
    transfer_id = uuid4()
    value = artifact(role_resource())
    repository, _, _ = service_repository(value, artifact_id=artifact_id, transfer_id=transfer_id)
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
    repository.transition_transfer.assert_any_await(
        actor_user_id=99,
        transfer_id=transfer_id,
        expected=TransferState.CREATED,
        target=TransferState.EXPORTED,
    )
    repository.freeze_transfer_mapping.assert_awaited_once()
    graph = planning.create.await_args.kwargs["graph"]
    assert graph.guild_id == GUILD_B


@pytest.mark.asyncio
async def test_product_reconcile_derives_owned_delete_scope_and_never_targets_unrelated_b() -> None:
    artifact_id = uuid4()
    transfer_id = uuid4()
    plan_id = uuid4()
    staff_id = 623456789012345671
    owned_extra_id = 623456789012345672
    unrelated_id = 623456789012345673
    value = artifact(role_resource("Portable Staff"))
    relationship_id = uuid4()
    base = destination_snapshot()
    destination = replace(
        base,
        roles=(
            base.roles[0],
            RoleSnapshot(GUILD_B, staff_id, "Diverged Staff", 1, 0, False, base.freshness),
            RoleSnapshot(GUILD_B, owned_extra_id, "Old clone", 2, 0, False, base.freshness),
            RoleSnapshot(GUILD_B, unrelated_id, "Native B", 3, 0, False, base.freshness),
        ),
    )
    repository, _, _ = service_repository(
        value,
        artifact_id=artifact_id,
        transfer_id=transfer_id,
        relationship_id=relationship_id,
        bindings=[
            {
                "logical_ref": "role.staff",
                "resource_type": "ROLE",
                "destination_resource_id": staff_id,
            },
            {
                "logical_ref": "role.removed",
                "resource_type": "ROLE",
                "destination_resource_id": owned_extra_id,
            },
        ],
    )
    read_models = SimpleNamespace(guild_snapshot=AsyncMock(return_value=(destination, None)))
    planning = SimpleNamespace(create=AsyncMock(return_value=({"id": plan_id}, True)))
    service = PortabilityService(
        cast(Any, repository),
        cast(Any, read_models),
        cast(Any, planning),
        cast(Any, SimpleNamespace()),
    )

    preview = await service.preview_stored(
        actor_user_id=99,
        artifact_id=artifact_id,
        destination_guild_id=GUILD_B,
        mode=CloneMode.RECONCILE,
        explicit_mappings=(),
        relationship_id=relationship_id,
    )
    assert preview["delete_candidates"] == [
        {
            "logical_ref": "reconcile.delete.role.removed",
            "resource_type": "ROLE",
            "outcome": "DELETE_CANDIDATE",
            "reason": "clone.reconcile_explicit_scope_extra",
            "destination_ref": str(owned_extra_id),
            "destructive": True,
        }
    ]

    await service.compile_stored(
        actor_user_id=99,
        artifact_id=artifact_id,
        destination_guild_id=GUILD_B,
        mode=CloneMode.RECONCILE,
        explicit_mappings=(),
        idempotency_key="server-derived-reconcile",
        correlation_id=uuid4(),
        relationship_id=relationship_id,
    )
    graph = planning.create.await_args.kwargs["graph"]
    assert graph.node("role.staff").discord_id == staff_id
    deletion = graph.node("reconcile.delete.role.removed")
    assert deletion is not None and deletion.presence is NodePresence.ABSENT
    assert deletion.discord_id == owned_extra_id
    assert all(node.discord_id != unrelated_id for node in graph.nodes)
    read_models.guild_snapshot.assert_awaited_with(GUILD_B, 99)


@pytest.mark.asyncio
async def test_maximum_compatible_service_persists_null_plan_and_never_calls_planning() -> None:
    artifact_id = uuid4()
    transfer_id = uuid4()
    value = artifact(role_resource())
    repository, _, _ = service_repository(value, artifact_id=artifact_id, transfer_id=transfer_id)
    planning = SimpleNamespace(create=AsyncMock())
    service = PortabilityService(
        cast(Any, repository),
        cast(
            Any,
            SimpleNamespace(guild_snapshot=AsyncMock(return_value=(destination_snapshot(), None))),
        ),
        cast(Any, planning),
        cast(Any, SimpleNamespace()),
    )
    transfer, plan, created = await service.compile_stored(
        actor_user_id=99,
        artifact_id=artifact_id,
        destination_guild_id=GUILD_B,
        mode=CloneMode.MAXIMUM_COMPATIBLE,
        explicit_mappings=(),
        idempotency_key="report-only",
        correlation_id=uuid4(),
    )
    assert created is True and plan is None
    assert transfer["destination_plan_id"] is None
    planning.create.assert_not_awaited()
    assert repository.compile_transfer.await_args.kwargs["destination_plan_id"] is None


@pytest.mark.asyncio
async def test_mapping_required_is_durable_and_same_transfer_resumes_without_source_read() -> None:
    artifact_id = uuid4()
    transfer_id = uuid4()
    plan_id = uuid4()
    role_id = 623456789012345678
    value = artifact(role_resource())
    base = destination_snapshot()
    destination = replace(
        base,
        roles=(
            base.roles[0],
            RoleSnapshot(GUILD_B, role_id, "Staff", 1, 0, False, base.freshness),
        ),
    )
    repository, _, _ = service_repository(value, artifact_id=artifact_id, transfer_id=transfer_id)
    read_models = SimpleNamespace(guild_snapshot=AsyncMock(return_value=(destination, None)))
    planning = SimpleNamespace(create=AsyncMock(return_value=({"id": plan_id}, True)))
    service = PortabilityService(
        cast(Any, repository),
        cast(Any, read_models),
        cast(Any, planning),
        cast(Any, SimpleNamespace()),
    )
    with pytest.raises(MappingRequired):
        await service.compile_stored(
            actor_user_id=99,
            artifact_id=artifact_id,
            destination_guild_id=GUILD_B,
            mode=CloneMode.MERGE,
            explicit_mappings=(),
            idempotency_key="resume-me",
            correlation_id=uuid4(),
        )
    mapping_transition = next(
        call
        for call in repository.transition_transfer.await_args_list
        if call.kwargs["target"] is TransferState.MAPPING_REQUIRED
    )
    assert mapping_transition.kwargs["mapping"][0]["candidate_refs"] == [str(role_id)]
    await service.compile_stored(
        actor_user_id=99,
        artifact_id=artifact_id,
        destination_guild_id=GUILD_B,
        mode=CloneMode.MERGE,
        explicit_mappings=(
            ExplicitMapping("role.staff", GUILD_B, str(role_id), PortableResourceType.ROLE, True),
        ),
        idempotency_key="resume-me",
        correlation_id=uuid4(),
    )
    create_calls = repository.create_transfer.await_args_list
    assert create_calls[0].kwargs["idempotency_key"] == create_calls[1].kwargs["idempotency_key"]
    repository.freeze_transfer_mapping.assert_awaited_once_with(
        actor_user_id=99,
        transfer_id=transfer_id,
        expected=TransferState.MAPPING_REQUIRED,
        mapping=ANY,
        mapping_hash=ANY,
    )
    assert all(call.args[0] == GUILD_B for call in read_models.guild_snapshot.await_args_list)


@pytest.mark.asyncio
async def test_source_authorized_transfer_resumes_to_exported_without_source_read() -> None:
    artifact_id = uuid4()
    transfer_id = uuid4()
    value = artifact(role_resource())
    repository, _, row = service_repository(value, artifact_id=artifact_id, transfer_id=transfer_id)
    row["status"] = TransferState.SOURCE_AUTHORIZED.value
    service = PortabilityService(
        cast(Any, repository),
        cast(Any, SimpleNamespace(guild_snapshot=AsyncMock())),
        cast(Any, SimpleNamespace(create=AsyncMock())),
        cast(Any, SimpleNamespace()),
    )
    transfer, _, _ = await service.prepare_stored_transfer(
        actor_user_id=99,
        artifact_id=artifact_id,
        destination_guild_id=GUILD_B,
        mode=CloneMode.COPY_AS_NEW,
        idempotency_key="resume-source-authorized",
        correlation_id=uuid4(),
        source_authorized=True,
    )
    assert transfer["status"] == TransferState.EXPORTED.value
    repository.transition_transfer.assert_awaited_once_with(
        actor_user_id=99,
        transfer_id=transfer_id,
        expected=TransferState.SOURCE_AUTHORIZED,
        target=TransferState.EXPORTED,
    )


async def _freeze_ready_then_crash_before_planning(
    *,
    first_destination: GuildSnapshot,
    bindings: list[dict[str, object]],
    key: str,
) -> tuple[
    PortabilityService,
    SimpleNamespace,
    SimpleNamespace,
    dict[str, object],
    dict[str, object],
]:
    artifact_id = uuid4()
    transfer_id = uuid4()
    repository, _, row = service_repository(
        artifact(role_resource()),
        artifact_id=artifact_id,
        transfer_id=transfer_id,
        bindings=bindings,
    )
    read_models = SimpleNamespace(guild_snapshot=AsyncMock(return_value=(first_destination, None)))
    planning = SimpleNamespace(create=AsyncMock())
    service = PortabilityService(
        cast(Any, repository),
        cast(Any, read_models),
        cast(Any, planning),
        cast(Any, SimpleNamespace()),
    )
    service._compiler = cast(
        Any,
        SimpleNamespace(compile=Mock(side_effect=RuntimeError("crash after READY"))),
    )
    common: dict[str, object] = {
        "actor_user_id": 99,
        "artifact_id": artifact_id,
        "destination_guild_id": GUILD_B,
        "mode": CloneMode.MERGE,
        "explicit_mappings": (),
        "idempotency_key": key,
        "correlation_id": uuid4(),
    }
    with pytest.raises(RuntimeError, match="crash after READY"):
        await service.compile_stored(**cast(Any, common))
    assert row["status"] == TransferState.READY.value
    planning.create.assert_not_awaited()
    frozen = {
        "mapping_json": json.loads(json.dumps(row["mapping_json"])),
        "mapping_hash": row["mapping_hash"],
    }
    service._compiler = DestinationPlanCompiler()
    return service, read_models, planning, row, {**common, "frozen": frozen}


@pytest.mark.asyncio
async def test_ready_retry_keeps_automatic_map_existing_target_and_frozen_intent() -> None:
    target = 623456789012345678
    destination = destination_snapshot_with_roles((target, "Staff", 8))
    service, read_models, planning, row, context = await _freeze_ready_then_crash_before_planning(
        first_destination=destination,
        bindings=[
            {
                "logical_ref": "role.staff",
                "resource_type": "ROLE",
                "destination_resource_id": target,
            }
        ],
        key="ready-auto-unchanged",
    )
    frozen = cast(dict[str, object], context.pop("frozen"))
    read_models.guild_snapshot.return_value = (destination, None)
    planning.create.return_value = ({"id": uuid4()}, True)
    await service.compile_stored(**cast(Any, context))
    assert row["mapping_json"] == frozen["mapping_json"]
    assert row["mapping_hash"] == frozen["mapping_hash"]
    assert cast(list[dict[str, object]], row["mapping_json"])[0]["destination_ref"] == str(target)
    planning.create.assert_awaited_once()
    assert planning.create.await_args.kwargs[
        "idempotency_key"
    ] == PortabilityService._planning_idempotency_key(
        cast(UUID, context["artifact_id"]),
        GUILD_B,
        CloneMode.MERGE,
        cast(str, frozen["mapping_hash"]),
        cast(str, context["idempotency_key"]),
    )


@pytest.mark.asyncio
async def test_ready_retry_rejects_deleted_automatic_target_before_planning() -> None:
    target = 623456789012345678
    service, read_models, planning, row, context = await _freeze_ready_then_crash_before_planning(
        first_destination=destination_snapshot_with_roles((target, "Staff", 8)),
        bindings=[
            {
                "logical_ref": "role.staff",
                "resource_type": "ROLE",
                "destination_resource_id": target,
            }
        ],
        key="ready-auto-deleted",
    )
    frozen = cast(dict[str, object], context.pop("frozen"))
    read_models.guild_snapshot.return_value = (destination_snapshot(), None)
    with pytest.raises(TransferConflict, match="mapping is stale"):
        await service.compile_stored(**cast(Any, context))
    assert row["mapping_json"] == frozen["mapping_json"]
    assert row["mapping_hash"] == frozen["mapping_hash"]
    planning.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_ready_retry_never_remaps_to_new_same_name_candidate() -> None:
    target = 623456789012345678
    alternative = 723456789012345678
    service, read_models, planning, row, context = await _freeze_ready_then_crash_before_planning(
        first_destination=destination_snapshot_with_roles((target, "Staff", 8)),
        bindings=[
            {
                "logical_ref": "role.staff",
                "resource_type": "ROLE",
                "destination_resource_id": target,
            }
        ],
        key="ready-auto-alternative",
    )
    frozen = cast(dict[str, object], context.pop("frozen"))
    read_models.guild_snapshot.return_value = (
        destination_snapshot_with_roles(
            (target, "Staff", 8),
            (alternative, "Staff", 8),
        ),
        None,
    )
    planning.create.return_value = ({"id": uuid4()}, True)
    await service.compile_stored(**cast(Any, context))
    persisted = cast(list[dict[str, object]], row["mapping_json"])
    assert persisted == frozen["mapping_json"]
    assert persisted[0]["destination_ref"] == str(target)
    assert persisted[0]["destination_ref"] != str(alternative)


@pytest.mark.asyncio
async def test_ready_retry_rejects_create_to_same_name_manual_drift() -> None:
    service, read_models, planning, row, context = await _freeze_ready_then_crash_before_planning(
        first_destination=destination_snapshot(),
        bindings=[],
        key="ready-create-drift",
    )
    frozen = cast(dict[str, object], context.pop("frozen"))
    assert cast(list[dict[str, object]], frozen["mapping_json"])[0]["decision"] == "CREATE"
    read_models.guild_snapshot.return_value = (
        destination_snapshot_with_roles((723456789012345678, "Staff", 8)),
        None,
    )
    with pytest.raises(TransferConflict, match="mapping is stale"):
        await service.compile_stored(**cast(Any, context))
    assert row["mapping_json"] == frozen["mapping_json"]
    assert row["mapping_hash"] == frozen["mapping_hash"]
    planning.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_ready_retry_rejects_explicit_mapping_change_before_destination_read() -> None:
    first_target = 623456789012345678
    second_target = 723456789012345678
    artifact_id = uuid4()
    repository, _, row = service_repository(
        artifact(role_resource()), artifact_id=artifact_id, transfer_id=uuid4()
    )
    destination = destination_snapshot_with_roles(
        (first_target, "Staff", 8),
        (second_target, "Staff", 8),
    )
    read_models = SimpleNamespace(guild_snapshot=AsyncMock(return_value=(destination, None)))
    planning = SimpleNamespace(create=AsyncMock())
    service = PortabilityService(
        cast(Any, repository),
        cast(Any, read_models),
        cast(Any, planning),
        cast(Any, SimpleNamespace()),
    )
    service._compiler = cast(
        Any,
        SimpleNamespace(compile=Mock(side_effect=RuntimeError("crash after READY"))),
    )
    common = {
        "actor_user_id": 99,
        "artifact_id": artifact_id,
        "destination_guild_id": GUILD_B,
        "mode": CloneMode.MERGE,
        "idempotency_key": "ready-explicit-change",
        "correlation_id": uuid4(),
    }
    with pytest.raises(RuntimeError, match="crash after READY"):
        await service.compile_stored(
            explicit_mappings=(
                ExplicitMapping(
                    "role.staff",
                    GUILD_B,
                    str(first_target),
                    PortableResourceType.ROLE,
                    True,
                ),
            ),
            **cast(Any, common),
        )
    frozen_mapping = json.loads(json.dumps(row["mapping_json"]))
    frozen_hash = row["mapping_hash"]
    with pytest.raises(TransferConflict, match="mapping is already frozen"):
        await service.compile_stored(
            explicit_mappings=(
                ExplicitMapping(
                    "role.staff",
                    GUILD_B,
                    str(second_target),
                    PortableResourceType.ROLE,
                    True,
                ),
            ),
            **cast(Any, common),
        )
    assert read_models.guild_snapshot.await_count == 1
    assert row["mapping_json"] == frozen_mapping
    assert row["mapping_hash"] == frozen_hash
    planning.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_created_before_transfer_compile_is_reused_from_ready_state() -> None:
    artifact_id = uuid4()
    transfer_id = uuid4()
    plan_id = uuid4()
    value = artifact(role_resource())
    repository, _, row = service_repository(value, artifact_id=artifact_id, transfer_id=transfer_id)
    successful_compile = repository.compile_transfer.side_effect
    compile_attempt = 0

    async def crash_then_compile(**kwargs: object) -> dict[str, object]:
        nonlocal compile_attempt
        compile_attempt += 1
        if compile_attempt == 1:
            raise RuntimeError("crash after plan persistence")
        return await successful_compile(**kwargs)

    repository.compile_transfer.side_effect = crash_then_compile
    planning = SimpleNamespace(
        create=AsyncMock(side_effect=[({"id": plan_id}, True), ({"id": plan_id}, False)])
    )
    service = PortabilityService(
        cast(Any, repository),
        cast(
            Any,
            SimpleNamespace(guild_snapshot=AsyncMock(return_value=(destination_snapshot(), None))),
        ),
        cast(Any, planning),
        cast(Any, SimpleNamespace()),
    )
    kwargs = {
        "actor_user_id": 99,
        "artifact_id": artifact_id,
        "destination_guild_id": GUILD_B,
        "mode": CloneMode.COPY_AS_NEW,
        "explicit_mappings": (),
        "idempotency_key": "plan-before-compiled",
        "correlation_id": uuid4(),
    }
    with pytest.raises(RuntimeError, match="crash after plan persistence"):
        await service.compile_stored(**kwargs)
    assert row["status"] == TransferState.READY.value
    transfer, plan, created = await service.compile_stored(**kwargs)
    assert transfer["status"] == TransferState.COMPILED.value
    assert plan == {"id": plan_id}
    assert created is False
    assert planning.create.await_count == 2
    first_key = planning.create.await_args_list[0].kwargs["idempotency_key"]
    assert planning.create.await_args_list[1].kwargs["idempotency_key"] == first_key


@pytest.mark.asyncio
async def test_compiled_transfer_retry_is_read_only_and_different_mapping_conflicts() -> None:
    artifact_id = uuid4()
    transfer_id = uuid4()
    plan_id = uuid4()
    value = artifact(role_resource())
    repository, _, _ = service_repository(value, artifact_id=artifact_id, transfer_id=transfer_id)
    planning = SimpleNamespace(create=AsyncMock(return_value=({"id": plan_id}, True)))
    planning_repository = SimpleNamespace(
        get_plan=AsyncMock(return_value={"id": plan_id, "status": "DRAFT"})
    )
    service = PortabilityService(
        cast(Any, repository),
        cast(
            Any,
            SimpleNamespace(guild_snapshot=AsyncMock(return_value=(destination_snapshot(), None))),
        ),
        cast(Any, planning),
        cast(Any, planning_repository),
    )
    common = {
        "actor_user_id": 99,
        "artifact_id": artifact_id,
        "destination_guild_id": GUILD_B,
        "mode": CloneMode.COPY_AS_NEW,
        "idempotency_key": "compiled-immutable",
        "correlation_id": uuid4(),
    }
    await service.compile_stored(explicit_mappings=(), **common)
    replay, plan, created = await service.compile_stored(explicit_mappings=(), **common)
    assert replay["status"] == TransferState.COMPILED.value
    assert plan == {"id": plan_id, "status": "DRAFT"}
    assert created is False
    assert planning.create.await_count == 1
    with pytest.raises(TransferConflict, match="mapping is already frozen"):
        await service.compile_stored(
            explicit_mappings=(
                ExplicitMapping(
                    "role.staff",
                    GUILD_B,
                    "999999999999999999",
                    PortableResourceType.ROLE,
                    True,
                ),
            ),
            **common,
        )


@pytest.mark.asyncio
async def test_natural_a1_a2_reconcile_cycle_uses_only_finalized_relationship_bindings() -> None:
    source = live_snapshot()
    survivor_source_id = source.roles[1].role_id
    removed_source_id = 623456789012345671
    added_source_id = 623456789012345672
    generation_one = replace(
        source,
        roles=(
            *source.roles,
            RoleSnapshot(
                GUILD_A, removed_source_id, "Removed in A2", 2, 0, False, source.freshness
            ),
        ),
    )
    generation_two = replace(
        source,
        roles=(
            source.roles[0],
            replace(source.roles[1], name="Survivor changed", permissions=16),
            RoleSnapshot(GUILD_A, added_source_id, "Added in A2", 3, 4, False, source.freshness),
        ),
    )
    builder = PortableArtifactBuilder()
    a1 = builder.build_live(
        generation_one,
        ArtifactSelection(
            ArtifactType.CUSTOM_BUNDLE,
            role_ids=(survivor_source_id, removed_source_id),
        ),
    )
    a2 = builder.build_live(
        generation_two,
        ArtifactSelection(
            ArtifactType.CUSTOM_BUNDLE,
            role_ids=(added_source_id, survivor_source_id),
        ),
    )
    a1_refs = {item.logical_key for item in a1.resources}
    a2_refs = {item.logical_key for item in a2.resources}
    survivor_ref = (a1_refs & a2_refs).pop()
    removed_ref = (a1_refs - a2_refs).pop()
    added_ref = (a2_refs - a1_refs).pop()
    relationship_id = uuid4()
    a1_artifact_id, a1_transfer_id, a1_plan_id = uuid4(), uuid4(), uuid4()
    a2_artifact_id, a2_transfer_id, a2_plan_id = uuid4(), uuid4(), uuid4()
    survivor_destination_id = 723456789012345671
    removed_destination_id = 723456789012345672
    added_destination_id = 723456789012345673
    unrelated_destination_id = 723456789012345674
    finalized_generations: list[list[dict[str, object]]] = []

    base_destination = destination_snapshot()
    destination_before_a1 = base_destination
    repository_a1, _, row_a1 = service_repository(
        a1,
        artifact_id=a1_artifact_id,
        transfer_id=a1_transfer_id,
        relationship_id=relationship_id,
    )

    async def save_a1_bindings(**kwargs: object) -> None:
        finalized_generations.append(cast(list[dict[str, object]], kwargs["bindings"]))

    async def record_a1_result(*args: object, **kwargs: object) -> dict[str, object]:
        row_a1["local_result_json"] = args[2] if len(args) == 3 else kwargs["result"]
        return dict(row_a1)

    repository_a1.get_transfer = AsyncMock(side_effect=lambda *_: dict(row_a1))
    repository_a1.save_clone_bindings = AsyncMock(side_effect=save_a1_bindings)
    repository_a1.record_local_result = AsyncMock(side_effect=record_a1_result)
    planning_a1 = SimpleNamespace(create=AsyncMock(return_value=({"id": a1_plan_id}, True)))
    planning_repository_a1 = SimpleNamespace(
        get_plan=AsyncMock(return_value={"id": a1_plan_id, "status": "SUCCEEDED"}),
        symbol_bindings=AsyncMock(
            return_value=[
                {
                    "symbol": f"portable:{survivor_ref}",
                    "discord_id": survivor_destination_id,
                    "status": "BOUND",
                },
                {
                    "symbol": f"portable:{removed_ref}",
                    "discord_id": removed_destination_id,
                    "status": "BOUND",
                },
            ]
        ),
    )
    service_a1 = PortabilityService(
        cast(Any, repository_a1),
        cast(
            Any,
            SimpleNamespace(guild_snapshot=AsyncMock(return_value=(destination_before_a1, None))),
        ),
        cast(Any, planning_a1),
        cast(Any, planning_repository_a1),
    )
    await service_a1.compile_stored(
        actor_user_id=99,
        artifact_id=a1_artifact_id,
        destination_guild_id=GUILD_B,
        mode=CloneMode.COPY_AS_NEW,
        explicit_mappings=(),
        idempotency_key="natural-a1",
        correlation_id=uuid4(),
    )
    await service_a1.finalize_transfer(
        actor_user_id=99, transfer_id=a1_transfer_id, correlation_id=uuid4()
    )
    assert {item["logical_ref"] for item in finalized_generations[0]} == a1_refs

    destination_after_a1 = replace(
        base_destination,
        roles=(
            base_destination.roles[0],
            RoleSnapshot(
                GUILD_B,
                survivor_destination_id,
                "Survivor from A1",
                1,
                0,
                False,
                base_destination.freshness,
            ),
            RoleSnapshot(
                GUILD_B,
                removed_destination_id,
                "Removed from A1",
                2,
                0,
                False,
                base_destination.freshness,
            ),
            RoleSnapshot(
                GUILD_B,
                unrelated_destination_id,
                "Native B control",
                3,
                0,
                False,
                base_destination.freshness,
            ),
        ),
    )
    repository_a2, _, row_a2 = service_repository(
        a2,
        artifact_id=a2_artifact_id,
        transfer_id=a2_transfer_id,
        relationship_id=relationship_id,
        bindings=finalized_generations[0],
    )

    async def save_a2_bindings(**kwargs: object) -> None:
        finalized_generations.append(cast(list[dict[str, object]], kwargs["bindings"]))

    async def record_a2_result(*args: object, **kwargs: object) -> dict[str, object]:
        row_a2["local_result_json"] = args[2] if len(args) == 3 else kwargs["result"]
        return dict(row_a2)

    repository_a2.get_transfer = AsyncMock(side_effect=lambda *_: dict(row_a2))
    repository_a2.save_clone_bindings = AsyncMock(side_effect=save_a2_bindings)
    repository_a2.record_local_result = AsyncMock(side_effect=record_a2_result)
    planning_a2 = SimpleNamespace(create=AsyncMock(return_value=({"id": a2_plan_id}, True)))
    planning_repository_a2 = SimpleNamespace(
        get_plan=AsyncMock(return_value={"id": a2_plan_id, "status": "SUCCEEDED"}),
        symbol_bindings=AsyncMock(
            return_value=[
                {
                    "symbol": f"portable:{added_ref}",
                    "discord_id": added_destination_id,
                    "status": "BOUND",
                }
            ]
        ),
    )
    service_a2 = PortabilityService(
        cast(Any, repository_a2),
        cast(
            Any,
            SimpleNamespace(guild_snapshot=AsyncMock(return_value=(destination_after_a1, None))),
        ),
        cast(Any, planning_a2),
        cast(Any, planning_repository_a2),
    )
    await service_a2.compile_stored(
        actor_user_id=99,
        artifact_id=a2_artifact_id,
        destination_guild_id=GUILD_B,
        mode=CloneMode.RECONCILE,
        explicit_mappings=(),
        idempotency_key="natural-a2",
        correlation_id=uuid4(),
        relationship_id=relationship_id,
    )
    graph = planning_a2.create.await_args.kwargs["graph"]
    survivor = graph.node(survivor_ref)
    assert survivor is not None and survivor.discord_id == survivor_destination_id
    deletion = graph.node(f"reconcile.delete.{removed_ref}")
    assert deletion is not None and deletion.presence is NodePresence.ABSENT
    assert deletion.discord_id == removed_destination_id
    assert all(node.discord_id != unrelated_destination_id for node in graph.nodes)
    await service_a2.finalize_transfer(
        actor_user_id=99, transfer_id=a2_transfer_id, correlation_id=uuid4()
    )
    assert {item["logical_ref"] for item in finalized_generations[1]} == a2_refs
    assert removed_ref not in {item["logical_ref"] for item in finalized_generations[1]}
