from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from did.application.planning.service import PlanningService
from did.application.policies.planning import (
    AccessChange,
    ImpactAccuracy,
    PolicyPlanningService,
)
from did.application.policies.service import PolicyService
from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
from did.domain.policies import Policy, PolicyLifecycleError, PolicyLifecycleState, PolicyScopeType
from did.domain.read_model import (
    ChannelSnapshot,
    CoverageSnapshot,
    FreshnessSnapshot,
    GuildSnapshot,
    MemberSnapshot,
    RoleSnapshot,
)
from did.domain.read_model.models import ChannelType
from did.permissions import DEFAULT_PERMISSION_REGISTRY
from did.planning.canonical import canonical_hash
from did.planning.models import DesiredStateGraph, PlanProvenance, ResourceType
from did.planning.preflight import PolicyPreflightResult, PreflightResult
from did.policies.resolver import PolicyResolutionOutcome, PolicyResolver

GUILD = 991_001
OTHER_GUILD = 991_002
ACTOR = 991_011
BOT = 991_012
CHANNEL = 991_101
ROLE = 991_201
NOW = datetime(2026, 9, 14, tzinfo=UTC)


def _facts(
    *,
    members_complete: bool = True,
    member_roles_complete: bool = True,
) -> tuple[GuildSnapshot, MemberSnapshot, MemberSnapshot]:
    fresh = FreshnessSnapshot(FreshnessState.FRESH, "CACHE", 1, NOW, NOW, NOW)
    coverage = CoverageSnapshot(
        GUILD,
        CoverageMode.FULL,
        FreshnessState.FRESH,
        "CACHE",
        1,
        known_channels=1,
        visible_channels=1,
        known_roles=2,
        members_complete=members_complete,
        overwrites_complete=True,
    )
    guild = GuildSnapshot(
        GUILD,
        ACTOR,
        (
            RoleSnapshot(GUILD, GUILD, "@everyone", 0, 0, False, fresh),
            RoleSnapshot(GUILD, ROLE, "staff", 1, 0, False, fresh),
        ),
        (
            ChannelSnapshot(
                GUILD,
                CHANNEL,
                ChannelType.GUILD_TEXT,
                0,
                None,
                "staff",
                (),
                True,
                ObservabilityState.VISIBLE,
                fresh,
            ),
        ),
        coverage,
        fresh,
        source_versions=("guild:1", "coverage:1"),
    )
    actor = MemberSnapshot(
        GUILD,
        ACTOR,
        (ROLE,),
        member_roles_complete,
        fresh if member_roles_complete else replace(fresh, state=FreshnessState.UNKNOWN),
    )
    bot = MemberSnapshot(GUILD, BOT, (), True, fresh, is_bot=True)
    return guild, actor, bot


def _policy(
    number: int,
    *,
    state: PolicyLifecycleState = PolicyLifecycleState.DRAFT,
    decision: str = "ALLOW",
    priority: int = 0,
    conditions: tuple[dict[str, object], ...] = ({"kind": "ALWAYS"},),
    effects: tuple[dict[str, object], ...] | None = None,
) -> Policy:
    return Policy(
        UUID(int=number),
        GUILD,
        "ACCESS_CONTROL",
        1,
        f"Policy {number}",
        "",
        state,
        1,
        PolicyScopeType.CHANNEL,
        str(CHANNEL),
        conditions,
        effects or ({"kind": "SET_ACCESS", "access": "VIEW", "decision": decision},),
        {"summary": f"Policy {number}"},
        ACTOR,
        ACTOR,
        priority,
    )


def _services(
    policies: tuple[Policy, ...],
    *,
    members_complete: bool = True,
    member_roles_complete: bool = True,
    resolver: PolicyResolver | None = None,
    planning: object | None = None,
) -> tuple[PolicyPlanningService, SimpleNamespace, PolicyService]:
    guild, member, bot = _facts(
        members_complete=members_complete,
        member_roles_complete=member_roles_complete,
    )
    by_id = {value.policy_id: value for value in policies}
    repository = SimpleNamespace(
        list=AsyncMock(return_value=policies),
        get=AsyncMock(side_effect=lambda guild_id, policy_id: by_id[policy_id]),
        get_revision=AsyncMock(side_effect=lambda guild_id, policy_id, revision: by_id[policy_id]),
    )
    read_models = SimpleNamespace(
        guild_snapshot=AsyncMock(
            side_effect=lambda guild_id, subject_id: (
                guild,
                bot if subject_id == BOT else member,
            )
        ),
        list_logical_groups=AsyncMock(return_value=[]),
        cached_member_snapshots=AsyncMock(return_value=(member,)),
        member_snapshots=AsyncMock(
            side_effect=lambda guild_id, ids: tuple(
                bot if value == BOT else member for value in ids
            )
        ),
        bot_identity=AsyncMock(return_value=(BOT, "ACTIVE")),
    )
    service = PolicyService(repository, read_models=read_models, resolver=resolver)  # type: ignore[arg-type]
    orchestration = PolicyPlanningService(
        policies=service,
        planning=planning,
        read_models=read_models,
    )
    return orchestration, read_models, service


@pytest.mark.asyncio
async def test_draft_preview_is_non_persistent_and_shows_access_gain() -> None:
    draft = _policy(1)
    orchestration, _, _ = _services((draft,))

    preview = await orchestration.preview(
        guild_id=GUILD, policy_id=draft.policy_id, actor_user_id=ACTOR
    )

    assert draft.lifecycle_state is PolicyLifecycleState.DRAFT
    assert preview.persisted is False and preview.discord_mutations == 0
    assert preview.entries[0].current.outcome is PolicyResolutionOutcome.CANNOT
    assert preview.entries[0].proposed.outcome is PolicyResolutionOutcome.CAN
    assert preview.entries[0].access_change is AccessChange.GAINED
    assert preview.impact.access_gains == 1
    assert preview.impact.accuracy is ImpactAccuracy.EXACT


@pytest.mark.asyncio
async def test_preview_calls_the_injected_canonical_resolver_for_before_and_after() -> None:
    resolver = PolicyResolver()
    resolver.resolve = MagicMock(wraps=resolver.resolve)  # type: ignore[method-assign]
    draft = _policy(2)
    orchestration, _, _ = _services((draft,), resolver=resolver)

    await orchestration.preview(guild_id=GUILD, policy_id=draft.policy_id, actor_user_id=ACTOR)

    assert resolver.resolve.call_count == 2  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_preview_reports_access_loss_and_winning_contribution_change() -> None:
    active_allow = _policy(3, state=PolicyLifecycleState.ACTIVE, decision="ALLOW", priority=1)
    draft_deny = _policy(4, decision="DENY", priority=2)
    orchestration, _, _ = _services((active_allow, draft_deny))

    preview = await orchestration.preview(
        guild_id=GUILD, policy_id=draft_deny.policy_id, actor_user_id=ACTOR
    )

    entry = preview.entries[0]
    assert entry.current.outcome is PolicyResolutionOutcome.CAN
    assert entry.proposed.outcome is PolicyResolutionOutcome.CANNOT
    assert entry.access_change is AccessChange.LOST
    assert entry.gained_contributions and entry.lost_contributions


@pytest.mark.asyncio
async def test_preview_surfaces_unresolved_conflict_as_blocked() -> None:
    active = _policy(5, state=PolicyLifecycleState.ACTIVE, decision="ALLOW")
    draft = _policy(6, decision="DENY")
    orchestration, _, _ = _services((active, draft))

    preview = await orchestration.preview(
        guild_id=GUILD, policy_id=draft.policy_id, actor_user_id=ACTOR
    )

    assert preview.entries[0].proposed.outcome is PolicyResolutionOutcome.BLOCKED
    assert preview.entries[0].access_change is AccessChange.BLOCKED
    assert preview.entries[0].conflicts_created
    assert preview.impact.impossible_or_incomplete_targets == 1


@pytest.mark.asyncio
async def test_preview_marks_critical_incomplete_member_facts_unknown() -> None:
    draft = _policy(
        7,
        conditions=({"kind": "ROLE_MATCH", "match": "ANY", "role_ids": [str(ROLE)]},),
    )
    orchestration, _, _ = _services((draft,), members_complete=False, member_roles_complete=False)

    preview = await orchestration.preview(
        guild_id=GUILD, policy_id=draft.policy_id, actor_user_id=ACTOR
    )

    assert preview.entries[0].proposed.outcome is PolicyResolutionOutcome.UNKNOWN
    assert preview.impact.accuracy is ImpactAccuracy.INCOMPLETE
    assert "policy.member_roles_incomplete" in preview.entries[0].diagnostics


@pytest.mark.asyncio
async def test_preview_disable_requires_an_active_policy() -> None:
    draft = _policy(70)  # DRAFT by default
    orchestration, _, _ = _services((draft,))

    with pytest.raises(PolicyLifecycleError):
        await orchestration.preview_disable(
            guild_id=GUILD, policy_id=draft.policy_id, actor_user_id=ACTOR
        )


@pytest.mark.asyncio
async def test_preview_disable_reveals_the_inherited_policy_reasserting_itself() -> None:
    # REQ-AP-INH-003: an ACTIVE, lower-priority "category" policy that ALLOWs,
    # overridden by an ACTIVE, higher-priority "channel exception" that DENYs.
    # Disabling the exception should let the category policy win again.
    category_allow = _policy(71, state=PolicyLifecycleState.ACTIVE, decision="ALLOW", priority=0)
    exception_deny = _policy(72, state=PolicyLifecycleState.ACTIVE, decision="DENY", priority=5)
    orchestration, _, _ = _services((category_allow, exception_deny))

    preview = await orchestration.preview_disable(
        guild_id=GUILD, policy_id=exception_deny.policy_id, actor_user_id=ACTOR
    )

    entry = preview.entries[0]
    assert entry.current.outcome is PolicyResolutionOutcome.CANNOT
    assert entry.proposed.outcome is PolicyResolutionOutcome.CAN
    assert entry.access_change is AccessChange.GAINED
    assert preview.lifecycle_state is PolicyLifecycleState.ACTIVE
    assert preview.persisted is False and preview.discord_mutations == 0


@pytest.mark.asyncio
async def test_preview_disable_of_the_only_policy_leaves_nothing_to_fall_back_to() -> None:
    only_policy = _policy(73, state=PolicyLifecycleState.ACTIVE, decision="ALLOW")
    orchestration, _, _ = _services((only_policy,))

    preview = await orchestration.preview_disable(
        guild_id=GUILD, policy_id=only_policy.policy_id, actor_user_id=ACTOR
    )

    entry = preview.entries[0]
    assert entry.current.outcome is PolicyResolutionOutcome.CAN
    assert entry.proposed.outcome is PolicyResolutionOutcome.CANNOT
    assert entry.access_change is AccessChange.LOST


@pytest.mark.asyncio
async def test_create_disable_plan_compiles_through_the_same_canonical_pipeline() -> None:
    category_allow = _policy(74, state=PolicyLifecycleState.ACTIVE, decision="ALLOW", priority=0)
    exception_deny = _policy(75, state=PolicyLifecycleState.ACTIVE, decision="DENY", priority=5)
    plan_id = uuid4()
    captured: dict[str, object] = {}

    async def create(**kwargs: object):
        captured.update(kwargs)
        return {"id": plan_id, "status": "DRAFT", "state_version": 1}, True

    planning = SimpleNamespace(
        create=AsyncMock(side_effect=create),
        validate=AsyncMock(
            return_value=(
                {"id": plan_id, "status": "VALIDATED", "state_version": 2},
                PreflightResult(True),
            )
        ),
    )
    orchestration, _, _ = _services((category_allow, exception_deny), planning=planning)

    preview, plan, created, preflight = await orchestration.create_disable_plan(
        guild_id=GUILD,
        policy_id=exception_deny.policy_id,
        actor_user_id=ACTOR,
        idempotency_key="policy-disable-plan",
        correlation_id=uuid4(),
        expected_revision=1,
    )

    graph = captured["graph"]
    provenance = captured["provenance"]
    assert isinstance(graph, DesiredStateGraph)
    assert graph.nodes[0].resource_type is ResourceType.OVERWRITE
    assert isinstance(provenance, PlanProvenance)
    # Provenance still points at the Policy being disabled, not the one it
    # falls back to -- assert_activation_plan() keys on exactly this pair.
    assert provenance.policy_id == exception_deny.policy_id and provenance.policy_revision == 1
    assert plan["status"] == "VALIDATED" and created and preflight.allowed
    assert preview.entries[0].access_change is AccessChange.GAINED


@pytest.mark.asyncio
async def test_policy_compiles_to_existing_dsg_and_plan_with_typed_provenance() -> None:
    draft = _policy(8)
    plan_id = uuid4()
    captured: dict[str, object] = {}

    async def create(**kwargs: object):
        captured.update(kwargs)
        return {
            "id": plan_id,
            "status": "DRAFT",
            "state_version": 1,
        }, True

    planning = SimpleNamespace(
        create=AsyncMock(side_effect=create),
        validate=AsyncMock(
            return_value=(
                {"id": plan_id, "status": "VALIDATED", "state_version": 2},
                PreflightResult(True),
            )
        ),
    )
    orchestration, _, _ = _services((draft,), planning=planning)

    _, plan, created, preflight = await orchestration.create_plan(
        guild_id=GUILD,
        policy_id=draft.policy_id,
        actor_user_id=ACTOR,
        idempotency_key="policy-plan",
        correlation_id=uuid4(),
        expected_revision=1,
    )

    graph = captured["graph"]
    provenance = captured["provenance"]
    assert isinstance(graph, DesiredStateGraph)
    assert graph.nodes[0].resource_type is ResourceType.OVERWRITE
    assert isinstance(provenance, PlanProvenance)
    assert provenance.policy_id == draft.policy_id and provenance.policy_revision == 1
    assert plan["status"] == "VALIDATED" and created and preflight.allowed


@pytest.mark.asyncio
async def test_new_text_intentions_compile_through_canonical_preview_into_dsg_bits() -> None:
    accesses = (
        "CREATE_THREAD",
        "PARTICIPATE_THREAD",
        "REACT",
        "MENTION_EVERYONE_HERE",
    )
    draft = _policy(
        81,
        effects=tuple(
            {"kind": "SET_ACCESS", "access": access, "decision": "ALLOW"} for access in accesses
        ),
    )
    captured: dict[str, object] = {}
    plan_id = uuid4()

    async def create(**kwargs: object):
        captured.update(kwargs)
        return {"id": plan_id, "status": "DRAFT", "state_version": 1}, True

    planning = SimpleNamespace(
        create=AsyncMock(side_effect=create),
        validate=AsyncMock(
            return_value=(
                {"id": plan_id, "status": "VALIDATED", "state_version": 2},
                PreflightResult(True),
            )
        ),
    )
    orchestration, _, _ = _services((draft,), planning=planning)

    preview, _, _, _ = await orchestration.create_plan(
        guild_id=GUILD,
        policy_id=draft.policy_id,
        actor_user_id=ACTOR,
        idempotency_key="policy-new-intentions",
        correlation_id=uuid4(),
        expected_revision=1,
    )

    graph = captured["graph"]
    assert isinstance(graph, DesiredStateGraph)
    assert {entry.target.requested_access for entry in preview.entries} == set(accesses)
    expected_allow = sum(
        DEFAULT_PERMISSION_REGISTRY.value(permission)
        for permission in (
            "CREATE_PUBLIC_THREADS",
            "CREATE_PRIVATE_THREADS",
            "SEND_MESSAGES_IN_THREADS",
            "ADD_REACTIONS",
            "MENTION_EVERYONE",
        )
    )
    properties = dict(graph.nodes[0].properties.items)
    assert properties["allow"] == str(expected_allow)
    assert properties["deny"] == "0"


@pytest.mark.asyncio
async def test_policy_guard_blocks_conflict_and_preserves_resolver_explanation() -> None:
    active = _policy(9, state=PolicyLifecycleState.ACTIVE, decision="ALLOW")
    draft = _policy(10, decision="DENY")
    orchestration, _, _ = _services((active, draft))
    preview = await orchestration.preview(
        guild_id=GUILD, policy_id=draft.policy_id, actor_user_id=ACTOR
    )
    metadata = {
        "preview_accuracy": "EXACT",
        "preview_contexts": [
            {
                "subject_id": str(ACTOR),
                "target_scope_type": "CHANNEL",
                "target_scope_id": str(CHANNEL),
                "requested_access": "VIEW",
                "expected_outcome": preview.entries[0].proposed.outcome.value,
            }
        ],
    }

    result = await orchestration.evaluate_plan(
        guild_id=GUILD,
        provenance=PlanProvenance.policy(
            policy_id=draft.policy_id, policy_revision=1, metadata=metadata
        ),
        require_active=False,
    )

    assert not result.allowed
    assert "preflight.policy_blocked" in result.errors
    assert result.explanations[0]["outcome"] == "BLOCKED"


@pytest.mark.asyncio
async def test_policy_guard_allows_matching_can_resolution() -> None:
    draft = _policy(11)
    orchestration, _, _ = _services((draft,))
    result = await orchestration.evaluate_plan(
        guild_id=GUILD,
        provenance=PlanProvenance.policy(
            policy_id=draft.policy_id,
            policy_revision=1,
            metadata={
                "preview_accuracy": "EXACT",
                "preview_contexts": [
                    {
                        "subject_id": str(ACTOR),
                        "target_scope_type": "CHANNEL",
                        "target_scope_id": str(CHANNEL),
                        "requested_access": "VIEW",
                        "expected_outcome": "CAN",
                    }
                ],
            },
        ),
        require_active=False,
    )

    assert result.allowed
    assert result.explanations[0]["outcome"] == "CAN"


@pytest.mark.asyncio
async def test_canonical_recheck_merges_policy_failure_fail_closed() -> None:
    guild, _, bot = _facts()
    provenance = PlanProvenance.policy(
        policy_id=UUID(int=12),
        policy_revision=1,
        metadata={"preview_accuracy": "EXACT", "preview_contexts": []},
    )
    repository = SimpleNamespace(
        get_plan=AsyncMock(
            return_value={
                "id": uuid4(),
                "status": "DRAFT",
                "desired_graph": {
                    "guild_id": str(GUILD),
                    "schema_version": "did-dsg-v1",
                    "nodes": [],
                },
                "base_structure_version": PlanningService.structure_version(guild),
                "capability_version": DEFAULT_PERMISSION_REGISTRY.version,
                "origin_type": "POLICY",
                "source_policy_id": provenance.policy_id,
                "source_policy_revision": 1,
                "origin_metadata": provenance.metadata_map(),
            }
        ),
        operations=AsyncMock(return_value=[]),
    )
    read_models = SimpleNamespace(
        bot_identity=AsyncMock(return_value=(BOT, "ACTIVE")),
        guild_snapshot=AsyncMock(return_value=(guild, bot)),
        cached_member_snapshots=AsyncMock(return_value=()),
    )
    guard = SimpleNamespace(
        evaluate_plan=AsyncMock(
            return_value=PolicyPreflightResult(
                False,
                ("preflight.policy_unknown",),
                explanations=({"outcome": "UNKNOWN"},),
            )
        )
    )
    service = PlanningService(repository, read_models, policy_preflight=guard)  # type: ignore[arg-type]

    result = await service.recheck(guild_id=GUILD, plan_id=uuid4(), actor_authorization_fresh=True)

    assert not result.allowed
    assert "preflight.policy_unknown" in result.errors
    assert result.policy_explanations == ({"outcome": "UNKNOWN"},)


@pytest.mark.asyncio
async def test_foreign_tenant_policy_is_not_previewable() -> None:
    draft = _policy(13)
    orchestration, _, service = _services((draft,))
    repository = object.__getattribute__(service, "_repository")
    repository.get = AsyncMock(side_effect=LookupError("not found"))

    with pytest.raises(LookupError):
        await orchestration.preview(
            guild_id=OTHER_GUILD,
            policy_id=draft.policy_id,
            actor_user_id=ACTOR,
        )


def test_manual_plan_hash_contract_remains_backward_compatible() -> None:
    graph = DesiredStateGraph(GUILD, ())
    snapshot = {"schema_version": "did-guild-snapshot-v1", "guild_id": str(GUILD)}
    expected = canonical_hash(
        {
            "desired_graph": graph,
            "desired_graph_hash": canonical_hash(graph),
            "compiler_version": "compiler-v1",
            "capability_version": "capability-v1",
            "before_snapshot": {
                "schema_version": "snapshot-v1",
                "structure_version": "guild:1",
                "snapshot_hash": "a" * 64,
                "payload": snapshot,
            },
            "operations": (),
            "dependencies": (),
            "symbols": (),
        }
    )

    actual = PlanningService._plan_hash(
        graph=graph,
        operations=(),
        snapshot=snapshot,
        snapshot_schema_version="snapshot-v1",
        compiler_version="compiler-v1",
        capability_version="capability-v1",
        base_structure_version="guild:1",
        base_structure_hash="a" * 64,
        symbols=(),
        provenance=PlanProvenance(),
    )

    assert actual == expected
