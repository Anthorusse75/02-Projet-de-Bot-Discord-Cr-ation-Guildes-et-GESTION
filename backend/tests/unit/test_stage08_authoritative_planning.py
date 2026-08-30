from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from did.application.translation.planning import Stage08StructuralPlanningService
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
from did.planning import ResourceType

GUILD = 780000000000000001
ACTOR = 780000000000000002
CHANNEL = 780000000000000003
LANGUAGE = UUID("11111111-1111-4111-8111-111111111111")
GROUP = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 8, 30, tzinfo=UTC)


def snapshot(
    *, role_count: int, overwrite_count: int, protected_targets: tuple[int, ...]
) -> GuildSnapshot:
    fresh = FreshnessSnapshot(FreshnessState.FRESH, "GATEWAY", 1, NOW, NOW, NOW)
    roles = tuple(
        RoleSnapshot(
            GUILD,
            GUILD if index == 0 else 790000000000000000 + index,
            "@everyone" if index == 0 else f"role-{index}",
            index,
            0,
            False,
            fresh,
        )
        for index in range(role_count)
    )
    targets = list(protected_targets)
    next_target = 800000000000000001
    while len(targets) < overwrite_count:
        if next_target not in targets:
            targets.append(next_target)
        next_target += 1
    overwrites = tuple(
        OverwriteSnapshot(GUILD, CHANNEL, target, 0, 0, 0, NOW) for target in targets
    )
    channel = ChannelSnapshot(
        GUILD,
        CHANNEL,
        ChannelType.GUILD_TEXT,
        1,
        None,
        "fr-general",
        overwrites,
        True,
        ObservabilityState.VISIBLE,
        fresh,
    )
    coverage = CoverageSnapshot(
        GUILD,
        CoverageMode.FULL,
        FreshnessState.FRESH,
        "GATEWAY",
        1,
        known_channels=1,
        visible_channels=1,
        known_roles=role_count,
        overwrites_complete=True,
    )
    return GuildSnapshot(GUILD, ACTOR, roles, (channel,), coverage, fresh)


def service(
    guild: GuildSnapshot,
    *,
    existing_role_id: int | None = None,
) -> tuple[Stage08StructuralPlanningService, SimpleNamespace]:
    planning = AsyncMock()
    planning.create.return_value = (
        {"id": uuid4(), "guild_id": GUILD, "status": "DRAFT"},
        False,
    )
    read_models = AsyncMock()
    read_models.guild_snapshot.return_value = (guild, SimpleNamespace())
    groups = AsyncMock()
    groups.workspace_group.return_value = {
        "id": GROUP,
        "channel_variants": [
            {"discord_channel_id": CHANNEL, "state": "ACTIVE"},
        ],
        "category_variants": [],
    }
    languages = AsyncMock()
    languages.get.return_value = {"id": LANGUAGE, "code": "fr", "enabled": True}
    policies = AsyncMock()
    policies.get_optional.return_value = {
        "visibility_policy": "LANGUAGE_FILTERED",
        "explicit_language_profile_id": LANGUAGE,
        "visibility_scope_id": None,
        "inherit_language": False,
    }
    scope_roles = AsyncMock()
    lifecycle = AsyncMock()
    lifecycle.language_binding.return_value = (
        {
            "discord_role_id": existing_role_id,
            "role_state": "ACTIVE",
        }
        if existing_role_id is not None
        else None
    )
    lifecycle.reserve_role.return_value = (
        {"id": uuid4(), "status": "RESERVED"},
        True,
    )
    authority = Stage08StructuralPlanningService(
        planning=planning,
        read_models=read_models,
        groups=groups,
        languages=languages,
        policies=policies,
        scope_roles=scope_roles,
        lifecycle=lifecycle,
    )
    return authority, SimpleNamespace(planning=planning, lifecycle=lifecycle)


async def test_actual_budget_allows_999_plus_one_and_materializes_only_via_intent() -> None:
    guild = snapshot(role_count=249, overwrite_count=999, protected_targets=(GUILD,))
    authority, spies = service(guild)
    plan, replayed, budget = await authority.create_visibility_plan(
        guild_id=GUILD,
        group_id=GROUP,
        actor_user_id=ACTOR,
        resource_type="CHANNEL",
        discord_resource_id=CHANNEL,
        idempotency_key="boundary-999-plus-one",
        correlation_id=uuid4(),
    )
    assert not replayed and plan["status"] == "DRAFT"
    assert budget == {
        "source": "TRUSTED_CACHE_AND_DURABLE_TOPOLOGY",
        "role_count": 249,
        "role_delta": 1,
        "overwrite_count": 999,
        "overwrite_delta": 1,
    }
    graph = spies.planning.create.await_args.kwargs["graph"]
    assert [node.resource_type for node in graph.nodes].count(ResourceType.ROLE) == 1
    assert [node.resource_type for node in graph.nodes].count(ResourceType.OVERWRITE) == 2
    spies.lifecycle.attach_role_plan.assert_awaited_once()


async def test_actual_budget_blocks_999_plus_two_before_reserving_a_role() -> None:
    authority, spies = service(snapshot(role_count=249, overwrite_count=999, protected_targets=()))
    with pytest.raises(ValueError, match="OVERWRITE_CAPACITY_EXCEEDED"):
        await authority.create_visibility_plan(
            guild_id=GUILD,
            group_id=GROUP,
            actor_user_id=ACTOR,
            resource_type="CHANNEL",
            discord_resource_id=CHANNEL,
            idempotency_key="boundary-999-plus-two",
            correlation_id=uuid4(),
        )
    spies.lifecycle.reserve_role.assert_not_awaited()
    spies.planning.create.assert_not_awaited()


async def test_actual_budget_blocks_new_role_at_250_but_allows_reuse() -> None:
    full = snapshot(role_count=250, overwrite_count=1, protected_targets=(GUILD,))
    authority, spies = service(full)
    with pytest.raises(ValueError, match="ROLE_CAPACITY_EXCEEDED"):
        await authority.create_visibility_plan(
            guild_id=GUILD,
            group_id=GROUP,
            actor_user_id=ACTOR,
            resource_type="CHANNEL",
            discord_resource_id=CHANNEL,
            idempotency_key="role-new-blocked",
            correlation_id=uuid4(),
        )
    spies.planning.create.assert_not_awaited()

    reused_role = full.roles[-1].role_id
    authority, spies = service(full, existing_role_id=reused_role)
    _, _, budget = await authority.create_visibility_plan(
        guild_id=GUILD,
        group_id=GROUP,
        actor_user_id=ACTOR,
        resource_type="CHANNEL",
        discord_resource_id=CHANNEL,
        idempotency_key="role-reuse-allowed",
        correlation_id=uuid4(),
    )
    assert budget["role_delta"] == 0
    graph = spies.planning.create.await_args.kwargs["graph"]
    assert all(node.resource_type is not ResourceType.ROLE for node in graph.nodes)
