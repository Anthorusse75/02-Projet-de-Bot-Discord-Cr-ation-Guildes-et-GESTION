from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from did.application.policies.planning import (
    AccessChange,
    ImpactAccuracy,
    PolicyPlanningService,
    drift_fingerprint,
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
    OverwriteSnapshot,
    RoleSnapshot,
)
from did.domain.read_model.models import ChannelType
from did.permissions import DEFAULT_PERMISSION_REGISTRY
from did.planning.models import DesiredStateGraph, PlanProvenance, ResourceType
from did.planning.preflight import PreflightResult
from did.policies.resolver import PolicyResolutionOutcome

GUILD = 996_001
ACTOR = 996_011
MEMBER = 996_021
ROLE = 996_031
CHANNEL = 996_101
NOW = datetime(2026, 9, 17, tzinfo=UTC)
VIEW_BIT = DEFAULT_PERMISSION_REGISTRY.value("VIEW_CHANNEL")


def _facts(*, real_overwrite_allow: int = 0) -> tuple[GuildSnapshot, MemberSnapshot]:
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
        members_complete=True,
        overwrites_complete=True,
    )
    overwrites = (
        (OverwriteSnapshot(GUILD, CHANNEL, MEMBER, 1, real_overwrite_allow, 0),)
        if real_overwrite_allow
        else ()
    )
    guild = GuildSnapshot(
        GUILD,
        ACTOR,
        (
            RoleSnapshot(GUILD, GUILD, "@everyone", 0, 0, False, fresh),
            RoleSnapshot(GUILD, ROLE, "managers", 1, 0, False, fresh),
        ),
        (
            ChannelSnapshot(
                GUILD,
                CHANNEL,
                ChannelType.GUILD_TEXT,
                0,
                None,
                "board",
                overwrites,
                True,
                ObservabilityState.VISIBLE,
                fresh,
            ),
        ),
        coverage,
        fresh,
        source_versions=("guild:1",),
    )
    member = MemberSnapshot(GUILD, MEMBER, (ROLE,), True, fresh)
    return guild, member


def _policy(
    *, locked: bool = False, state: PolicyLifecycleState = PolicyLifecycleState.ACTIVE
) -> Policy:
    return Policy(
        UUID(int=1),
        GUILD,
        "ACCESS_CONTROL",
        1,
        "Locked visibility",
        "",
        state,
        2,
        PolicyScopeType.CHANNEL,
        str(CHANNEL),
        ({"kind": "ROLE_MATCH", "match": "ANY", "role_ids": [str(ROLE)]},),
        ({"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"},),
        {"summary": "Locked visibility"},
        ACTOR,
        ACTOR,
        priority=0,
        locked=locked,
    )


def _services(
    policy: Policy, guild: GuildSnapshot, member: MemberSnapshot, *, planning: object | None = None
) -> PolicyPlanningService:
    repository = SimpleNamespace(
        list=AsyncMock(return_value=(policy,)),
        get=AsyncMock(return_value=policy),
        get_revision=AsyncMock(return_value=policy),
    )
    read_models = SimpleNamespace(
        guild_snapshot=AsyncMock(return_value=(guild, member)),
        list_logical_groups=AsyncMock(return_value=[]),
        cached_member_snapshots=AsyncMock(return_value=(member,)),
        member_snapshots=AsyncMock(return_value=(member,)),
        bot_identity=AsyncMock(return_value=(None, None)),
    )
    service = PolicyService(repository, read_models=read_models)  # type: ignore[arg-type]
    return PolicyPlanningService(policies=service, planning=planning, read_models=read_models)


@pytest.mark.asyncio
async def test_detect_drift_requires_an_active_policy() -> None:
    guild, member = _facts()
    draft_policy = _policy(state=PolicyLifecycleState.DRAFT)
    orchestration = _services(draft_policy, guild, member)

    with pytest.raises(PolicyLifecycleError):
        await orchestration.detect_drift(
            guild_id=GUILD, policy_id=draft_policy.policy_id, actor_user_id=ACTOR
        )


@pytest.mark.asyncio
async def test_detect_drift_finds_no_drift_when_discord_already_matches_the_policy() -> None:
    guild, member = _facts(real_overwrite_allow=VIEW_BIT)
    policy = _policy(locked=True)
    orchestration = _services(policy, guild, member)

    preview = await orchestration.detect_drift(
        guild_id=GUILD, policy_id=policy.policy_id, actor_user_id=ACTOR
    )

    assert all(entry.access_change is AccessChange.UNCHANGED for entry in preview.entries)
    assert preview.impact.access_gains == 0 and preview.impact.access_losses == 0
    assert preview.impact.accuracy is ImpactAccuracy.EXACT
    assert preview.lifecycle_state is PolicyLifecycleState.ACTIVE


@pytest.mark.asyncio
async def test_detect_drift_reveals_an_externally_removed_overwrite() -> None:
    guild, member = _facts(real_overwrite_allow=0)  # the real overwrite was externally deleted
    policy = _policy(locked=True)
    orchestration = _services(policy, guild, member)

    preview = await orchestration.detect_drift(
        guild_id=GUILD, policy_id=policy.policy_id, actor_user_id=ACTOR
    )

    entry = preview.entries[0]
    assert entry.current.outcome is PolicyResolutionOutcome.CANNOT
    assert entry.proposed.outcome is PolicyResolutionOutcome.CAN
    assert entry.access_change is AccessChange.GAINED
    assert preview.impact.access_gains == 1


@pytest.mark.asyncio
async def test_only_the_exact_accepted_drift_fingerprint_is_marked_documented() -> None:
    guild, member = _facts(real_overwrite_allow=0)
    policy = _policy(locked=False)
    initial = await _services(policy, guild, member).detect_drift(
        guild_id=GUILD, policy_id=policy.policy_id, actor_user_id=ACTOR
    )
    accepted = replace(
        policy,
        revision=policy.revision + 1,
        metadata={
            **policy.metadata,
            "tags": [f"drift-exception:{drift_fingerprint(initial)[:40]}"],
        },
    )

    documented = await _services(accepted, guild, member).detect_drift(
        guild_id=GUILD, policy_id=accepted.policy_id, actor_user_id=ACTOR
    )

    assert "policy.drift.exception_accepted" in documented.warnings


@pytest.mark.asyncio
async def test_create_drift_plan_compiles_the_correction_through_the_canonical_pipeline() -> None:
    guild, member = _facts(real_overwrite_allow=0)
    policy = _policy(locked=True)
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
    orchestration = _services(policy, guild, member, planning=planning)

    preview, plan, created, preflight = await orchestration.create_drift_plan(
        guild_id=GUILD,
        policy_id=policy.policy_id,
        actor_user_id=ACTOR,
        idempotency_key="drift-plan-once",
        correlation_id=uuid4(),
        expected_revision=2,
        auto_reconcile=True,
    )

    graph = captured["graph"]
    provenance = captured["provenance"]
    assert isinstance(graph, DesiredStateGraph)
    assert graph.nodes[0].resource_type is ResourceType.OVERWRITE
    assert isinstance(provenance, PlanProvenance)
    assert provenance.policy_id == policy.policy_id and provenance.policy_revision == 2
    assert provenance.metadata_map()["auto_reconcile"] is True
    assert plan["status"] == "VALIDATED" and created and preflight.allowed
    assert preview.entries[0].access_change is AccessChange.GAINED


@pytest.mark.asyncio
async def test_system_reassert_final_preflight_fails_closed_after_policy_is_unlocked() -> None:
    guild, member = _facts(real_overwrite_allow=0)
    policy = _policy(locked=False)
    orchestration = _services(policy, guild, member)
    provenance = PlanProvenance.policy(
        policy_id=policy.policy_id,
        policy_revision=policy.revision,
        metadata={
            "preview_accuracy": "EXACT",
            "preview_contexts": [],
            "simulate": "REASSERT",
            "auto_reconcile": True,
        },
    )

    result = await orchestration.evaluate_plan(
        guild_id=GUILD,
        provenance=provenance,
        require_active=True,
    )

    assert result.allowed is False
    assert "preflight.policy_not_locked" in result.errors
