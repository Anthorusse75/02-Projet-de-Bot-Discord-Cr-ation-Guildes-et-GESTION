from __future__ import annotations

import ast
import json
from dataclasses import replace
from datetime import UTC, datetime
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

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
    assert matrix["CHANNEL_TYPES"]["0_TEXT"][0] == "FULL"
    assert matrix["CHANNEL_TYPES"]["15_FORUM"][0] == "UNSUPPORTED"


def test_full_caller_idempotency_material_is_hashed_without_prefix_truncation_collision() -> None:
    artifact_id = uuid4()
    prefix = "x" * 159
    first = PortabilityService._planning_idempotency_key(
        artifact_id, GUILD_B, CloneMode.MERGE, [], prefix + "a"
    )
    second = PortabilityService._planning_idempotency_key(
        artifact_id, GUILD_B, CloneMode.MERGE, [], prefix + "b"
    )
    repeated = PortabilityService._planning_idempotency_key(
        artifact_id, GUILD_B, CloneMode.MERGE, [], prefix + "a"
    )
    assert first != second
    assert first == repeated
    assert len(first) <= 160


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
                    "status": "CREATED",
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
        transition_transfer=AsyncMock(return_value={"id": transfer_id, "status": "EXPORTED"}),
        reconcile_bindings=AsyncMock(return_value=[]),
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
    repository.transition_transfer.assert_any_await(
        actor_user_id=99,
        transfer_id=transfer_id,
        expected=TransferState.CREATED,
        target=TransferState.EXPORTED,
    )
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
    relationship_key = PortabilityService._relationship_key(value, GUILD_B)
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
    repository = SimpleNamespace(
        get_artifact=AsyncMock(return_value=({"source_guild_id": GUILD_A}, value)),
        reconcile_bindings=AsyncMock(
            return_value=[
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
            ]
        ),
        create_transfer=AsyncMock(
            return_value=(
                {
                    "id": transfer_id,
                    "status": "CREATED",
                    "relationship_key": relationship_key,
                },
                True,
            )
        ),
        transition_transfer=AsyncMock(return_value={"id": transfer_id}),
        compile_transfer=AsyncMock(
            return_value={
                "id": transfer_id,
                "status": "COMPILED",
                "destination_plan_id": plan_id,
            }
        ),
        audit_boundary=AsyncMock(),
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
    repository = SimpleNamespace(
        get_artifact=AsyncMock(return_value=({"source_guild_id": GUILD_A}, value)),
        reconcile_bindings=AsyncMock(return_value=[]),
        create_transfer=AsyncMock(return_value=({"id": transfer_id, "status": "CREATED"}, True)),
        transition_transfer=AsyncMock(return_value={"id": transfer_id}),
        compile_transfer=AsyncMock(
            return_value={
                "id": transfer_id,
                "status": "COMPILED",
                "destination_plan_id": None,
                "report_json": [{"outcome": "CLONED"}],
            }
        ),
        audit_boundary=AsyncMock(),
    )
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
    repository = SimpleNamespace(
        get_artifact=AsyncMock(return_value=({"source_guild_id": GUILD_A}, value)),
        reconcile_bindings=AsyncMock(return_value=[]),
        create_transfer=AsyncMock(
            side_effect=[
                ({"id": transfer_id, "status": "CREATED"}, True),
                ({"id": transfer_id, "status": "MAPPING_REQUIRED"}, False),
            ]
        ),
        transition_transfer=AsyncMock(return_value={"id": transfer_id}),
        compile_transfer=AsyncMock(
            return_value={"id": transfer_id, "status": "COMPILED", "destination_plan_id": plan_id}
        ),
        audit_boundary=AsyncMock(),
    )
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
    repository.transition_transfer.assert_any_await(
        actor_user_id=99,
        transfer_id=transfer_id,
        expected=TransferState.MAPPING_REQUIRED,
        target=TransferState.READY,
        mapping=ANY,
    )
    assert all(call.args[0] == GUILD_B for call in read_models.guild_snapshot.await_args_list)
