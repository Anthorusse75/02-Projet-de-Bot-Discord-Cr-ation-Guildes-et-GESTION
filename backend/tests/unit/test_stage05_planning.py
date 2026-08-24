from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from itertools import permutations
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from did.domain.discord_runtime import (
    CoverageMode,
    DiscordErrorKind,
    DiscordFailure,
    FreshnessState,
    ObservabilityState,
)
from did.domain.read_model import (
    ChannelSnapshot,
    CoverageSnapshot,
    FreshnessSnapshot,
    GuildSnapshot,
    RoleSnapshot,
)
from did.domain.read_model.models import ChannelType
from did.infrastructure.discord.mutations import (
    DiscordPyMutableAdapter,
    MutableDiscordError,
    RecoveryOutcome,
    audit_reason,
)
from did.planning.canonical import canonical_hash, canonical_json
from did.planning.compiler import PlanCompiler
from did.planning.dag import DagValidationError, topological_order
from did.planning.diff import DiffEngine
from did.planning.models import (
    DesiredNode,
    DesiredStateGraph,
    DiffAction,
    NodePresence,
    OperationType,
    PlanOperation,
    ReferenceKind,
    ResourceReference,
    ResourceType,
    RiskLevel,
)
from did.planning.risk import ImpactSummary, RiskEngine
from did.worker.io.governor import DiscordWorkloadGovernor
from did.worker.io.plan_executor import ApplyPlanExecutor

GUILD = 123456789012345678
NOW = datetime(2026, 8, 24, tzinfo=UTC)


def current_guild() -> GuildSnapshot:
    fresh = FreshnessSnapshot(FreshnessState.FRESH, "GATEWAY", 1, NOW, NOW, NOW)
    role = RoleSnapshot(GUILD, GUILD, "@everyone", 0, 0, False, fresh)
    channel = ChannelSnapshot(
        GUILD,
        223456789012345678,
        ChannelType.GUILD_TEXT,
        1,
        None,
        "general",
        (),
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
        known_roles=1,
        overwrites_complete=True,
    )
    return GuildSnapshot(
        GUILD,
        323456789012345678,
        (role,),
        (channel,),
        coverage,
        fresh,
        source_versions=("guild:1", "coverage:1"),
    )


def create_role_node(key: str = "role.staff") -> DesiredNode:
    return DesiredNode.build(
        logical_key=key,
        resource_type=ResourceType.ROLE,
        symbol=f"sym.{key}",
        properties={"name": "Staff", "permissions": "0"},
    )


def test_dsg_is_immutable_versioned_and_canonical_across_input_orders() -> None:
    nodes = (
        create_role_node(),
        DesiredNode.build(
            logical_key="channel.ops",
            resource_type=ResourceType.CHANNEL,
            symbol="sym.channel.ops",
            properties={"name": "ops", "type": 0},
        ),
    )
    hashes = {
        canonical_hash(DesiredStateGraph(GUILD, tuple(order))) for order in permutations(nodes)
    }
    assert len(hashes) == 1
    graph = DesiredStateGraph(GUILD, nodes)
    source = {"name": "mutable"}
    node = DesiredNode.build(
        logical_key="role.copy",
        resource_type=ResourceType.ROLE,
        symbol="sym.role.copy",
        properties=source,
    )
    source["name"] = "changed"
    assert node.property_map()["name"] == "mutable"
    assert '"schema_version":"did-dsg-v1"' in canonical_json(graph)


def test_semantic_diff_and_compiler_are_deterministic_and_symbol_ordered() -> None:
    guild = current_guild()
    role_node = create_role_node()
    channel_node = DesiredNode.build(
        logical_key="channel.staff",
        resource_type=ResourceType.CHANNEL,
        symbol="sym.channel.staff",
        properties={"name": "staff", "type": 0},
        relations={"subject": ResourceReference(ReferenceKind.SYMBOL, "sym.role.staff")},
    )
    graph = DesiredStateGraph(GUILD, (channel_node, role_node))
    first = PlanCompiler().compile(guild, graph)
    second = PlanCompiler().compile(guild, graph)
    assert first == second
    role_create = next(item for item in first if item.operation_type is OperationType.CREATE_ROLE)
    channel_create = next(
        item for item in first if item.operation_type is OperationType.CREATE_CHANNEL
    )
    assert role_create.operation_id in channel_create.predecessors
    assert topological_order(first).index(role_create.operation_id) < topological_order(
        first
    ).index(channel_create.operation_id)


def test_diff_classifies_update_delete_and_no_change_without_side_effects() -> None:
    guild = current_guild()
    existing = guild.channels[0]
    unchanged = DesiredNode.build(
        logical_key="channel.general",
        resource_type=ResourceType.CHANNEL,
        discord_id=existing.channel_id,
        properties={"name": "general"},
    )
    updated = replace(
        unchanged,
        properties=DesiredNode.build(
            logical_key="x",
            resource_type=ResourceType.CHANNEL,
            discord_id=existing.channel_id,
            properties={"name": "renamed"},
        ).properties,
    )
    deleted = replace(unchanged, presence=NodePresence.ABSENT)
    assert (
        DiffEngine().compare(guild, DesiredStateGraph(GUILD, (unchanged,)))[0].action
        is DiffAction.NO_CHANGE
    )
    assert (
        DiffEngine().compare(guild, DesiredStateGraph(GUILD, (updated,)))[0].action
        is DiffAction.UPDATE
    )
    assert (
        DiffEngine().compare(guild, DesiredStateGraph(GUILD, (deleted,)))[0].action
        is DiffAction.DELETE
    )


def test_channel_parent_moves_are_split_to_one_per_discord_request() -> None:
    guild = current_guild()
    fresh = guild.freshness
    categories = (
        ChannelSnapshot(
            GUILD,
            400,
            ChannelType.GUILD_CATEGORY,
            0,
            None,
            "a",
            (),
            True,
            ObservabilityState.VISIBLE,
            fresh,
        ),
        ChannelSnapshot(
            GUILD,
            401,
            ChannelType.GUILD_CATEGORY,
            1,
            None,
            "b",
            (),
            True,
            ObservabilityState.VISIBLE,
            fresh,
        ),
    )
    channels = (
        replace(guild.channels[0], channel_id=500, parent_id=400, name="one"),
        replace(guild.channels[0], channel_id=501, parent_id=400, name="two"),
    )
    observed = replace(guild, channels=categories + channels)
    nodes = tuple(
        DesiredNode.build(
            logical_key=f"channel.{item.name}",
            resource_type=ResourceType.CHANNEL,
            discord_id=item.channel_id,
            properties={"name": item.name, "position": item.position},
            relations={"parent": ResourceReference(ReferenceKind.DISCORD_ID, "401")},
        )
        for item in channels
    )
    moves = [
        item
        for item in PlanCompiler().compile(observed, DesiredStateGraph(GUILD, nodes))
        if item.operation_type is OperationType.MOVE_OR_REORDER_CHANNELS
    ]
    assert len(moves) == 2
    assert all(len(item.desired_payload.items) == 1 for item in moves)


def test_dag_cycle_and_destructive_risk_fail_safe() -> None:
    graph = DesiredStateGraph(
        GUILD,
        (
            DesiredNode.build(
                logical_key="channel.general",
                resource_type=ResourceType.CHANNEL,
                discord_id=current_guild().channels[0].channel_id,
                presence=NodePresence.ABSENT,
            ),
        ),
    )
    operation = PlanCompiler().compile(current_guild(), graph)[0]
    assessment = RiskEngine().assess((operation,), ImpactSummary(1))
    assert assessment.level is RiskLevel.HIGH
    with pytest.raises((ValueError, DagValidationError)):
        PlanOperation(
            operation.operation_id,
            operation.operation_type,
            operation.resource_type,
            operation.resource_ref,
            operation.desired_payload,
            operation.before_payload,
            operation.required_capabilities,
            operation.compensation,
            operation.risk,
            operation.verification,
            operation.recovery,
            operation.expected_gateway_events,
            predecessors=(operation.operation_id,),
        )


class TimeoutHTTP:
    async def create_role(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        raise TimeoutError


class FakeClient:
    http = TimeoutHTTP()


async def test_mutation_timeout_is_unknown_and_audit_reason_is_stable() -> None:
    plan_id = uuid4()
    operation_id = uuid4()
    correlation_id = uuid4()
    reason, fingerprint = audit_reason(plan_id, operation_id, correlation_id)
    assert len(reason.encode()) <= 512
    assert fingerprint == audit_reason(plan_id, operation_id, correlation_id)[1]
    adapter = DiscordPyMutableAdapter(FakeClient())  # type: ignore[arg-type]
    with pytest.raises(MutableDiscordError) as caught:
        await adapter.execute(
            guild_id=GUILD,
            plan_id=plan_id,
            operation_id=operation_id,
            correlation_id=correlation_id,
            operation_type=OperationType.CREATE_ROLE,
            payload={"name": "DID"},
        )
    assert caught.value.outcome_unknown
    assert caught.value.failure.status_code is None
    assert RecoveryOutcome.AMBIGUOUS.value == "AMBIGUOUS"


def test_shared_scope_429_is_measured_but_not_counted_as_invalid_request() -> None:
    governor = DiscordWorkloadGovernor()
    governor.record_discord_failure(
        DiscordFailure(
            DiscordErrorKind.RATE_LIMITED,
            429,
            retry_after_seconds=1.5,
            rate_limit_scope="shared",
        )
    )
    assert governor.metrics.rate_limited == 1
    assert governor.metrics.rate_limit_wait_seconds == 1.5
    assert governor.metrics.invalid_requests_10m == 0


@pytest.mark.asyncio
async def test_worker_final_preflight_blocks_before_discord_mutation() -> None:
    class ImmediateLock:
        async def run(self, guild_id: int, operation: Any) -> None:
            del guild_id
            await operation()

    repository = SimpleNamespace(
        begin_apply=AsyncMock(),
        finalize_plan=AsyncMock(),
    )
    adapter = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError("Discord I/O")))
    preflight = SimpleNamespace(
        recheck=AsyncMock(
            return_value=SimpleNamespace(
                allowed=False,
                errors=("preflight.structure_stale",),
            )
        )
    )
    plan_id = uuid4()
    executor = ApplyPlanExecutor(
        repository,
        adapter,
        ImmediateLock(),
        worker_id="worker-test",
        preflight=preflight,
    )
    await executor.execute_leased(
        123,
        {
            "payload": {"plan_id": str(plan_id)},
            "job_id": str(uuid4()),
            "lease_token": str(uuid4()),
            "lease_generation": 1,
            "correlation_id": str(uuid4()),
        },
        None,
    )
    repository.begin_apply.assert_awaited_once()
    preflight.recheck.assert_awaited_once_with(guild_id=123, plan_id=plan_id)
    repository.finalize_plan.assert_awaited_once()
    assert repository.finalize_plan.await_args.kwargs["error_code"] == ("FINAL_PREFLIGHT_FAILED")
    adapter.execute.assert_not_awaited()
