from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from itertools import permutations
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from did.application.auth.service import AuthorizationDenied
from did.application.planning.authorization import ApplyActorAuthorizer
from did.application.planning.service import PlanningService
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
    MemberSnapshot,
    RoleSnapshot,
)
from did.domain.read_model.models import ChannelType
from did.infrastructure.discord.mutations import (
    DiscordPyMutableAdapter,
    MutableDiscordError,
    PreconditionOutcome,
    RecoveryOutcome,
    RecoveryResult,
    audit_reason,
)
from did.infrastructure.planning_repository import PlanningRepository
from did.infrastructure.runtime_repository import RuntimeRepository
from did.permissions import DEFAULT_PERMISSION_REGISTRY
from did.planning.canonical import canonical_hash, canonical_json
from did.planning.compiler import PlanCompiler
from did.planning.dag import DagValidationError, topological_order
from did.planning.diff import DiffEngine
from did.planning.models import (
    CompensationClass,
    DesiredNode,
    DesiredStateGraph,
    DiffAction,
    NodePresence,
    OperationType,
    PlanOperation,
    RecoveryStrategy,
    ReferenceKind,
    ResourceReference,
    ResourceType,
    RiskLevel,
    VerificationStrategy,
    freeze_json_object,
    thaw_json_object,
)
from did.planning.preflight import PreflightContext, PreflightEngine
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
    plan_id = uuid4()
    first = PlanCompiler().compile(guild, graph, plan_id=plan_id)
    second = PlanCompiler().compile(guild, graph, plan_id=plan_id)
    assert first == second
    role_create = next(item for item in first if item.operation_type is OperationType.CREATE_ROLE)
    channel_create = next(
        item for item in first if item.operation_type is OperationType.CREATE_CHANNEL
    )
    assert role_create.operation_id in channel_create.predecessors
    assert topological_order(first).index(role_create.operation_id) < topological_order(
        first
    ).index(channel_create.operation_id)


def test_operation_ids_are_deterministic_within_and_distinct_across_plans() -> None:
    graph = DesiredStateGraph(GUILD, (create_role_node(),))
    first_plan = uuid4()
    second_plan = uuid4()
    first = PlanCompiler().compile(current_guild(), graph, plan_id=first_plan)
    repeated = PlanCompiler().compile(current_guild(), graph, plan_id=first_plan)
    second = PlanCompiler().compile(current_guild(), graph, plan_id=second_plan)
    assert first[0].operation_id == repeated[0].operation_id
    assert first[0].operation_id != second[0].operation_id


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
        for item in PlanCompiler().compile(
            observed, DesiredStateGraph(GUILD, nodes), plan_id=uuid4()
        )
        if item.operation_type is OperationType.MOVE_OR_REORDER_CHANNELS
    ]
    assert len(moves) == 2
    assert all(len(item.desired_payload.items) == 1 for item in moves)


def test_role_reorder_separates_rest_targets_from_expected_position_segment() -> None:
    base = current_guild()
    target = RoleSnapshot(GUILD, 100, "target", 1, 0, False, base.freshness)
    middle = RoleSnapshot(GUILD, 200, "managed", 2, 0, True, base.freshness)
    top = RoleSnapshot(GUILD, 300, "top", 3, 0, False, base.freshness)
    observed = replace(base, roles=(*base.roles, target, middle, top))
    graph = DesiredStateGraph(
        GUILD,
        (
            DesiredNode.build(
                logical_key="role.target",
                resource_type=ResourceType.ROLE,
                discord_id=target.role_id,
                properties={"name": target.name, "permissions": "0", "position": 3},
            ),
        ),
    )

    operations = PlanCompiler().compile(observed, graph, plan_id=uuid4())
    reorder = next(
        item for item in operations if item.operation_type is OperationType.REORDER_ROLES
    )
    payload = thaw_json_object(reorder.desired_payload)

    assert payload["items"] == [
        {"id": 100, "position": 4, "resource_ref": "role.target"},
    ]
    assert payload["expected_position_segment"] == [
        {"id": 200, "position": 1, "resource_ref": "discord.role.200"},
        {"id": 300, "position": 2, "resource_ref": "discord.role.300"},
        {"id": 100, "position": 3, "resource_ref": "role.target"},
    ]


def test_delete_everyone_is_rejected_by_preflight() -> None:
    base = current_guild()
    manage_roles = DEFAULT_PERMISSION_REGISTRY.value("MANAGE_ROLES")
    bot_role = RoleSnapshot(GUILD, 900, "bot", 10, manage_roles, False, base.freshness)
    observed = replace(base, roles=(*base.roles, bot_role))
    bot = MemberSnapshot(GUILD, 999, (GUILD, bot_role.role_id), True, base.freshness, True)
    graph = DesiredStateGraph(
        GUILD,
        (
            DesiredNode.build(
                logical_key="role.everyone",
                resource_type=ResourceType.ROLE,
                discord_id=GUILD,
                presence=NodePresence.ABSENT,
            ),
        ),
    )
    operations = PlanCompiler().compile(observed, graph, plan_id=uuid4())
    risk = RiskEngine().assess(operations, ImpactSummary(1))

    result = PreflightEngine().check(
        graph=graph,
        operations=operations,
        context=PreflightContext(
            guild=observed,
            bot=bot,
            installation_active=True,
            actor_authorization_fresh=True,
            base_structure_version="same",
            current_structure_version="same",
        ),
        risk=risk,
    )

    assert not result.allowed
    assert "preflight.default_role_delete_forbidden" in result.errors


@pytest.mark.parametrize(
    ("observability", "expected_error"),
    [
        (ObservabilityState.VISIBLE, True),
        (ObservabilityState.DELETED_CONFIRMED, False),
    ],
)
def test_category_delete_ignores_only_children_confirmed_deleted(
    observability: ObservabilityState, expected_error: bool
) -> None:
    base = current_guild()
    category = replace(
        base.channels[0],
        channel_id=700,
        channel_type=ChannelType.GUILD_CATEGORY,
        parent_id=None,
        name="category",
    )
    child = replace(
        base.channels[0],
        channel_id=701,
        parent_id=category.channel_id,
        name="child",
        observability=observability,
    )
    graph = DesiredStateGraph(
        GUILD,
        (
            DesiredNode.build(
                logical_key="category.deleted",
                resource_type=ResourceType.CATEGORY,
                discord_id=category.channel_id,
                presence=NodePresence.ABSENT,
            ),
        ),
    )
    errors: list[str] = []

    PreflightEngine._check_topology(graph, replace(base, channels=(category, child)), errors)

    assert ("preflight.category_delete_child_effect_implicit" in errors) is expected_error


def test_preflight_accepts_overwrite_on_channel_created_by_the_same_symbolic_plan() -> None:
    base = current_guild()
    permissions = DEFAULT_PERMISSION_REGISTRY.value(
        "MANAGE_CHANNELS"
    ) | DEFAULT_PERMISSION_REGISTRY.value("MANAGE_ROLES")
    bot_role = RoleSnapshot(GUILD, 900, "bot", 10, permissions, False, base.freshness)
    observed = replace(base, roles=(*base.roles, bot_role))
    bot = MemberSnapshot(GUILD, 999, (GUILD, bot_role.role_id), True, base.freshness, True)
    graph = DesiredStateGraph(
        GUILD,
        (
            DesiredNode.build(
                logical_key="role.future",
                resource_type=ResourceType.ROLE,
                symbol="symbol.role.future",
                properties={"name": "future", "permissions": "0"},
            ),
            DesiredNode.build(
                logical_key="channel.future",
                resource_type=ResourceType.CHANNEL,
                symbol="symbol.channel.future",
                properties={"name": "future", "type": 0},
            ),
            DesiredNode.build(
                logical_key="overwrite.future",
                resource_type=ResourceType.OVERWRITE,
                properties={"target_type": 0, "allow": "1024", "deny": "0"},
                relations={
                    "channel": ResourceReference(ReferenceKind.LOGICAL, "channel.future"),
                    "subject": ResourceReference(ReferenceKind.LOGICAL, "role.future"),
                },
            ),
        ),
    )
    operations = PlanCompiler().compile(observed, graph, plan_id=uuid4())
    overwrite = next(
        operation
        for operation in operations
        if operation.operation_type is OperationType.UPSERT_OVERWRITE
    )
    assert "symbol.channel.future" in overwrite.consumes_symbols

    result = PreflightEngine().check(
        graph=graph,
        operations=operations,
        context=PreflightContext(
            guild=observed,
            bot=bot,
            installation_active=True,
            actor_authorization_fresh=True,
            base_structure_version="same",
            current_structure_version="same",
        ),
        risk=RiskEngine().assess(operations, ImpactSummary(0)),
    )

    assert result.allowed
    assert "capability.channel_required" not in result.errors


def test_consumed_overwrite_channel_id_is_not_persisted_as_operation_identity() -> None:
    assert (
        PlanningRepository._persisted_result_resource_id(
            {"operation_type": OperationType.UPSERT_OVERWRITE.value},
            223456789012345678,
        )
        is None
    )
    assert (
        PlanningRepository._persisted_result_resource_id(
            {"operation_type": OperationType.CREATE_CHANNEL.value},
            223456789012345678,
        )
        == 223456789012345678
    )


@pytest.mark.parametrize(
    ("target_id", "target_position", "managed", "allowed", "expected_error"),
    [
        (901, 4, False, True, None),
        (902, 5, False, False, "capability.hierarchy.bot_role_not_above_target"),
        (903, 6, False, False, "capability.hierarchy.bot_role_not_above_target"),
        (904, 1, True, False, "capability.hierarchy.target_managed"),
        (GUILD, 0, False, False, "preflight.default_role_reorder_forbidden"),
    ],
)
def test_reorder_roles_preflight_checks_each_explicit_target(
    target_id: int,
    target_position: int,
    managed: bool,
    allowed: bool,
    expected_error: str | None,
) -> None:
    base = current_guild()
    manage_roles = DEFAULT_PERMISSION_REGISTRY.value("MANAGE_ROLES")
    bot_role = RoleSnapshot(GUILD, 900, "bot", 5, manage_roles, False, base.freshness)
    target = (
        base.roles[0]
        if target_id == GUILD
        else RoleSnapshot(
            GUILD,
            target_id,
            "target",
            target_position,
            0,
            managed,
            base.freshness,
        )
    )
    observed = replace(
        base, roles=(*base.roles, bot_role, *((target,) if target_id != GUILD else ()))
    )
    bot = MemberSnapshot(GUILD, 999, (GUILD, bot_role.role_id), True, base.freshness, True)
    operation = PlanOperation(
        uuid4(),
        OperationType.REORDER_ROLES,
        ResourceType.ROLE,
        "bulk:roles",
        freeze_json_object({"items": [{"id": target_id, "position": 2}]}),
        freeze_json_object({"items": [{"id": target_id, "position": target_position}]}),
        ("MANAGE_ROLES",),
        CompensationClass.REVERSIBLE,
        RiskLevel.MEDIUM,
        VerificationStrategy.TARGETED_LIST_AND_MATCH,
        RecoveryStrategy.UPDATE_COMPARE_BEFORE_DESIRED,
        ("GUILD_ROLE_UPDATE",),
    )
    graph = DesiredStateGraph(GUILD, ())
    risk = RiskEngine().assess((operation,), ImpactSummary(1))

    result = PreflightEngine().check(
        graph=graph,
        operations=(operation,),
        context=PreflightContext(
            guild=observed,
            bot=bot,
            installation_active=True,
            actor_authorization_fresh=True,
            base_structure_version="same",
            current_structure_version="same",
        ),
        risk=risk,
    )

    assert result.allowed is allowed
    if expected_error is not None:
        assert expected_error in result.errors


def test_reorder_roles_preflight_rejects_destination_at_bot_level() -> None:
    base = current_guild()
    manage_roles = DEFAULT_PERMISSION_REGISTRY.value("MANAGE_ROLES")
    bot_role = RoleSnapshot(GUILD, 900, "bot", 5, manage_roles, False, base.freshness)
    target = RoleSnapshot(GUILD, 901, "target", 2, 0, False, base.freshness)
    observed = replace(base, roles=(*base.roles, bot_role, target))
    bot = MemberSnapshot(GUILD, 999, (GUILD, bot_role.role_id), True, base.freshness, True)
    operation = PlanOperation(
        uuid4(),
        OperationType.REORDER_ROLES,
        ResourceType.ROLE,
        "bulk:roles",
        freeze_json_object({"items": [{"id": target.role_id, "position": 5}]}),
        freeze_json_object({"items": [{"id": target.role_id, "position": 2}]}),
        ("MANAGE_ROLES",),
        CompensationClass.REVERSIBLE,
        RiskLevel.MEDIUM,
        VerificationStrategy.TARGETED_LIST_AND_MATCH,
        RecoveryStrategy.UPDATE_COMPARE_BEFORE_DESIRED,
        ("GUILD_ROLE_UPDATE",),
    )

    result = PreflightEngine().check(
        graph=DesiredStateGraph(GUILD, ()),
        operations=(operation,),
        context=PreflightContext(
            guild=observed,
            bot=bot,
            installation_active=True,
            actor_authorization_fresh=True,
            base_structure_version="same",
            current_structure_version="same",
        ),
        risk=RiskEngine().assess((operation,), ImpactSummary(1)),
    )

    assert not result.allowed
    assert "preflight.role_reorder_destination_not_below_bot" in result.errors


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
    operation = PlanCompiler().compile(current_guild(), graph, plan_id=uuid4())[0]
    assessment = RiskEngine().assess((operation,), ImpactSummary(1))
    assert assessment.level is RiskLevel.HIGH
    unknown = RiskEngine().assess((operation,), ImpactSummary(1, incomplete_or_unknown=True))
    assert unknown.level is RiskLevel.HIGH
    assert unknown.reinforced_confirmation_required
    assert "risk.impact_unknown" in unknown.reasons

    create_graph = DesiredStateGraph(
        GUILD,
        (
            DesiredNode.build(
                logical_key="role.new",
                resource_type=ResourceType.ROLE,
                symbol="role.new",
                properties={"name": "new", "permissions": "0"},
            ),
        ),
    )
    create_operation = PlanCompiler().compile(current_guild(), create_graph, plan_id=uuid4())[0]
    uncertain_create = RiskEngine().assess(
        (create_operation, create_operation, create_operation),
        ImpactSummary(3, incomplete_or_unknown=True),
    )
    assert uncertain_create.level is RiskLevel.HIGH
    assert uncertain_create.reinforced_confirmation_required
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


@pytest.mark.asyncio
async def test_member_role_adapter_uses_discord_role_endpoints_and_rest_verification() -> None:
    class MemberRoleHTTP:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int, int, int]] = []

        async def add_role(
            self, guild_id: int, member_id: int, role_id: int, **kwargs: Any
        ) -> None:
            del kwargs
            self.calls.append(("ADD", guild_id, member_id, role_id))

        async def remove_role(
            self, guild_id: int, member_id: int, role_id: int, **kwargs: Any
        ) -> None:
            del kwargs
            self.calls.append(("REMOVE", guild_id, member_id, role_id))

    http = MemberRoleHTTP()
    adapter = DiscordPyMutableAdapter(SimpleNamespace(http=http))  # type: ignore[arg-type]
    common = {
        "guild_id": GUILD,
        "plan_id": uuid4(),
        "correlation_id": uuid4(),
        "payload": {"id": 800, "member_id": 800, "role_id": 900},
    }
    await adapter.execute(
        **common,
        operation_id=uuid4(),
        operation_type=OperationType.ADD_MEMBER_ROLE,
    )
    await adapter.execute(
        **common,
        operation_id=uuid4(),
        operation_type=OperationType.REMOVE_MEMBER_ROLE,
    )
    assert http.calls == [("ADD", GUILD, 800, 900), ("REMOVE", GUILD, 800, 900)]

    adapter._reads = SimpleNamespace(  # type: ignore[assignment]
        fetch_member=AsyncMock(return_value={"role_ids": [GUILD, 900]})
    )
    recovered = await adapter.recover(
        guild_id=GUILD,
        operation_type=OperationType.ADD_MEMBER_ROLE,
        payload={"id": 800, "member_id": 800, "role_id": 900},
        before_payload={"assigned": False},
    )
    assert recovered.outcome is RecoveryOutcome.PROVED_APPLIED


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
    authorization = SimpleNamespace(authorize_apply=AsyncMock())
    plan_id = uuid4()
    executor = ApplyPlanExecutor(
        repository,
        adapter,
        ImmediateLock(),
        worker_id="worker-test",
        authorization=authorization,
        preflight=preflight,
    )
    await executor.execute_leased(
        123,
        {
            "payload": {"plan_id": str(plan_id)},
            "job_id": str(uuid4()),
            "lease_token": str(uuid4()),
            "lease_generation": 1,
            "requested_by": 456,
            "correlation_id": str(uuid4()),
        },
        None,
    )
    repository.begin_apply.assert_awaited_once()
    authorization.authorize_apply.assert_awaited_once_with(guild_id=123, actor_user_id=456)
    preflight.recheck.assert_awaited_once_with(
        guild_id=123, plan_id=plan_id, actor_authorization_fresh=True
    )
    repository.finalize_plan.assert_awaited_once()
    assert repository.finalize_plan.await_args.kwargs["error_code"] == ("FINAL_PREFLIGHT_FAILED")
    adapter.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("denial_code", ["GUILD_MEMBERSHIP_REQUIRED", "CAPABILITY_REQUIRED"])
async def test_worker_revalidates_durable_actor_before_any_mutation(denial_code: str) -> None:
    class ImmediateLock:
        async def run(self, guild_id: int, operation: Any) -> None:
            del guild_id
            await operation()

    repository = SimpleNamespace(begin_apply=AsyncMock(), finalize_plan=AsyncMock())
    adapter = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError("Discord I/O")))
    authorization = SimpleNamespace(
        authorize_apply=AsyncMock(side_effect=AuthorizationDenied(denial_code))
    )
    executor = ApplyPlanExecutor(
        repository,
        adapter,
        ImmediateLock(),
        worker_id="authorization-worker",
        authorization=authorization,
    )
    await executor.execute_leased(
        GUILD,
        {
            "payload": {"plan_id": str(uuid4())},
            "job_id": str(uuid4()),
            "lease_token": str(uuid4()),
            "lease_generation": 1,
            "requested_by": 999,
            "correlation_id": str(uuid4()),
        },
        None,
    )
    authorization.authorize_apply.assert_awaited_once_with(guild_id=GUILD, actor_user_id=999)
    assert repository.finalize_plan.await_args.kwargs["error_code"] == (
        "ACTOR_AUTHORIZATION_REVOKED"
    )
    adapter.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_authorization_port_reuses_sensitive_stage02_service() -> None:
    authorization = SimpleNamespace(authorize=AsyncMock())
    await ApplyActorAuthorizer(authorization).authorize_apply(  # type: ignore[arg-type]
        guild_id=GUILD, actor_user_id=999
    )
    authorization.authorize.assert_awaited_once()
    call = authorization.authorize.await_args.kwargs
    assert call["discord_user_id"] == 999
    assert call["guild_id"] == GUILD
    assert call["sensitive"] is True
    assert call["require_active_installation"] is True
    assert call["require_discovery"] is False
    assert call["scope"].kind.value == "GUILD"
    assert call["capability"].value == "plans.apply"


@pytest.mark.asyncio
async def test_channel_listing_omission_is_never_create_or_delete_absence_proof() -> None:
    adapter = object.__new__(DiscordPyMutableAdapter)
    adapter._reads = SimpleNamespace(  # type: ignore[attr-defined]
        fetch_channels=AsyncMock(return_value=[]),
        fetch_roles=AsyncMock(return_value=[]),
    )
    create = await adapter.recover(
        guild_id=GUILD,
        operation_type=OperationType.CREATE_CHANNEL,
        payload={"name": "hidden", "type": 0},
        before_payload={},
    )
    delete = await adapter.recover(
        guild_id=GUILD,
        operation_type=OperationType.DELETE_CHANNEL,
        payload={"id": 42},
        before_payload={"id": 42, "observability": "ACCESS_LOST"},
    )
    assert create.outcome is RecoveryOutcome.AMBIGUOUS
    assert delete.outcome is RecoveryOutcome.AMBIGUOUS


@pytest.mark.asyncio
async def test_role_listing_absence_has_operation_specific_strong_recovery_semantics() -> None:
    adapter = object.__new__(DiscordPyMutableAdapter)
    adapter._reads = SimpleNamespace(  # type: ignore[attr-defined]
        fetch_channels=AsyncMock(return_value=[]),
        fetch_roles=AsyncMock(return_value=[]),
    )
    create = await adapter.recover(
        guild_id=GUILD,
        operation_type=OperationType.CREATE_ROLE,
        payload={"name": "missing", "permissions": 0},
        before_payload={},
    )
    delete = await adapter.recover(
        guild_id=GUILD,
        operation_type=OperationType.DELETE_ROLE,
        payload={"id": 42},
        before_payload={"id": 42},
    )
    assert create.outcome is RecoveryOutcome.PROVED_ABSENT
    assert delete.outcome is RecoveryOutcome.PROVED_APPLIED


@pytest.mark.asyncio
async def test_role_create_recovery_normalizes_structure_role_id_for_symbol_binding() -> None:
    adapter = object.__new__(DiscordPyMutableAdapter)
    adapter._reads = SimpleNamespace(  # type: ignore[attr-defined]
        fetch_channels=AsyncMock(return_value=[]),
        fetch_roles=AsyncMock(
            return_value=[
                {
                    "role_id": 42,
                    "name": "DID recovered",
                    "permissions": 0,
                    "position": 1,
                }
            ]
        ),
    )
    recovered = await adapter.recover(
        guild_id=GUILD,
        operation_type=OperationType.CREATE_ROLE,
        payload={"name": "DID recovered", "permissions": "0"},
        before_payload={},
    )
    assert recovered.outcome is RecoveryOutcome.PROVED_CREATED
    assert recovered.payload is not None and recovered.payload["id"] == 42


def test_mutation_matcher_distinguishes_nullable_fields_from_missing_fields() -> None:
    observed = {"channel_id": 123, "topic": None, "parent_id": None, "name": "general"}

    assert DiscordPyMutableAdapter._matches(
        observed, {"id": 123, "topic": None, "parent_id": None, "name": "general"}
    )
    assert not DiscordPyMutableAdapter._matches(observed, {"nsfw": None})


@pytest.mark.asyncio
async def test_role_reorder_verifies_explicit_target_after_managed_normalization() -> None:
    adapter = object.__new__(DiscordPyMutableAdapter)
    adapter._reads = SimpleNamespace(  # type: ignore[assignment]
        fetch_roles=AsyncMock(
            return_value=[
                {"role_id": 10, "position": 2},
                {"role_id": 20, "position": 11},
            ]
        ),
        fetch_channels=AsyncMock(return_value=[]),
    )

    recovered = await adapter.recover(
        guild_id=GUILD,
        operation_type=OperationType.REORDER_ROLES,
        payload={
            "items": [{"id": 20, "position": 12, "resource_ref": "role.target"}],
            "expected_position_segment": [
                {"id": 10, "position": 1, "resource_ref": "discord.role.10"},
                {"id": 20, "position": 11, "resource_ref": "role.target"},
            ],
        },
        before_payload={},
    )

    assert recovered.outcome is RecoveryOutcome.PROVED_APPLIED


@pytest.mark.asyncio
async def test_role_reorder_jit_rechecks_current_bot_hierarchy() -> None:
    adapter = object.__new__(DiscordPyMutableAdapter)
    adapter._client = SimpleNamespace(user=SimpleNamespace(id=999))  # type: ignore[attr-defined]
    adapter._reads = SimpleNamespace(  # type: ignore[attr-defined]
        fetch_roles=AsyncMock(
            return_value=[
                {"role_id": GUILD, "position": 0, "managed": False},
                {"role_id": 50, "position": 4, "managed": False},
                {"role_id": 60, "position": 4, "managed": False},
            ]
        ),
        fetch_member=AsyncMock(return_value={"role_ids": [GUILD, 60]}),
    )

    outcome = await adapter.check_preconditions(
        guild_id=GUILD,
        operation_type=OperationType.REORDER_ROLES,
        payload={"items": [{"id": 50, "position": 2}]},
        preconditions={
            "schema_version": "did-operation-precondition-v1",
            "before": {"items": [{"id": 50, "position": 4}]},
        },
    )

    assert outcome is PreconditionOutcome.CHANGED
    adapter._reads.fetch_member.assert_awaited_once_with(GUILD, 999)


@pytest.mark.asyncio
async def test_role_reorder_jit_allows_normal_target_strictly_below_bot() -> None:
    adapter = object.__new__(DiscordPyMutableAdapter)
    adapter._client = SimpleNamespace(user=SimpleNamespace(id=999))  # type: ignore[attr-defined]
    adapter._reads = SimpleNamespace(  # type: ignore[attr-defined]
        fetch_roles=AsyncMock(
            return_value=[
                {"role_id": GUILD, "position": 0, "managed": False},
                {"role_id": 50, "position": 3, "managed": False},
                {"role_id": 60, "position": 5, "managed": False},
            ]
        ),
        fetch_member=AsyncMock(return_value={"role_ids": [GUILD, 60]}),
    )

    outcome = await adapter.check_preconditions(
        guild_id=GUILD,
        operation_type=OperationType.REORDER_ROLES,
        payload={"items": [{"id": 50, "position": 2}]},
        preconditions={
            "schema_version": "did-operation-precondition-v1",
            "before": {"items": [{"id": 50, "position": 3}]},
        },
    )

    assert outcome is PreconditionOutcome.SATISFIED


@pytest.mark.asyncio
async def test_role_reorder_jit_rejects_destination_at_bot_level_without_rest() -> None:
    adapter = object.__new__(DiscordPyMutableAdapter)
    adapter._client = SimpleNamespace(user=SimpleNamespace(id=999))  # type: ignore[attr-defined]
    adapter._reads = SimpleNamespace(  # type: ignore[attr-defined]
        fetch_roles=AsyncMock(
            return_value=[
                {"role_id": GUILD, "position": 0, "managed": False},
                {"role_id": 50, "position": 3, "managed": False},
                {"role_id": 60, "position": 5, "managed": False},
            ]
        ),
        fetch_member=AsyncMock(return_value={"role_ids": [GUILD, 60]}),
    )

    outcome = await adapter.check_preconditions(
        guild_id=GUILD,
        operation_type=OperationType.REORDER_ROLES,
        payload={"items": [{"id": 50, "position": 5}]},
        preconditions={
            "schema_version": "did-operation-precondition-v1",
            "before": {"items": [{"id": 50, "position": 3}]},
        },
    )

    assert outcome is PreconditionOutcome.CHANGED


@pytest.mark.asyncio
async def test_role_reorder_rest_payload_contains_only_explicit_safe_targets() -> None:
    http = SimpleNamespace(move_role_position=AsyncMock(return_value=[]))
    adapter = DiscordPyMutableAdapter(  # type: ignore[arg-type]
        SimpleNamespace(http=http, user=SimpleNamespace(id=999))
    )
    await adapter.execute(
        guild_id=GUILD,
        plan_id=uuid4(),
        operation_id=uuid4(),
        correlation_id=uuid4(),
        operation_type=OperationType.REORDER_ROLES,
        payload={
            "items": [{"id": 50, "position": 2, "resource_ref": "role.target"}],
            "expected_position_segment": [
                {"id": 70, "position": 1, "resource_ref": "discord.role.70"},
                {"id": 50, "position": 2, "resource_ref": "role.target"},
            ],
        },
    )

    assert http.move_role_position.await_args is not None
    assert http.move_role_position.await_args.args[1] == [{"id": 50, "position": 2}]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation_type", [OperationType.DELETE_ROLE, OperationType.REORDER_ROLES])
async def test_mutable_adapter_fences_default_role_without_rest(
    operation_type: OperationType,
) -> None:
    http = SimpleNamespace(delete_role=AsyncMock(), move_role_position=AsyncMock())
    adapter = DiscordPyMutableAdapter(  # type: ignore[arg-type]
        SimpleNamespace(http=http, user=SimpleNamespace(id=999))
    )
    payload = (
        {"id": GUILD}
        if operation_type is OperationType.DELETE_ROLE
        else {"items": [{"id": GUILD, "position": 1}]}
    )

    with pytest.raises(MutableDiscordError) as caught:
        await adapter.execute(
            guild_id=GUILD,
            plan_id=uuid4(),
            operation_id=uuid4(),
            correlation_id=uuid4(),
            operation_type=operation_type,
            payload=payload,
        )

    assert caught.value.failure.kind is DiscordErrorKind.CONTRACT_ERROR
    assert not caught.value.outcome_unknown
    http.delete_role.assert_not_awaited()
    http.move_role_position.assert_not_awaited()


def test_overwrite_precondition_treats_channel_id_as_selected_context() -> None:
    outcome = DiscordPyMutableAdapter._overwrite_precondition(
        [
            {
                "channel_id": 42,
                "permission_overwrites": [{"id": 99, "type": 0, "allow": 1024, "deny": 0}],
            }
        ],
        {"channel_id": 42, "subject_id": 99, "target_type": 0},
        {
            "before": {
                "channel_id": 42,
                "target_id": 99,
                "target_type": 0,
                "allow": 1024,
                "deny": 0,
            }
        },
    )

    assert outcome is PreconditionOutcome.SATISFIED


@pytest.mark.asyncio
async def test_final_verification_uses_desired_state_not_intermediate_result() -> None:
    adapter = object.__new__(DiscordPyMutableAdapter)
    recover = AsyncMock(return_value=RecoveryResult(RecoveryOutcome.PROVED_APPLIED))
    adapter.recover = recover  # type: ignore[method-assign]

    verified = await adapter.verify(
        guild_id=GUILD,
        operation_type=OperationType.UPDATE_CHANNEL,
        payload={"id": 42, "topic": "final", "parent_id": 99},
        result_payload={"id": 42, "topic": "final", "parent_id": None},
    )

    assert verified
    assert recover.await_args is not None
    assert recover.await_args.kwargs["payload"] == {
        "id": 42,
        "topic": "final",
        "parent_id": 99,
    }


@pytest.mark.asyncio
async def test_jit_precondition_detects_out_of_band_target_change() -> None:
    adapter = object.__new__(DiscordPyMutableAdapter)
    adapter._reads = SimpleNamespace(  # type: ignore[attr-defined]
        fetch_roles=AsyncMock(
            return_value=[
                {
                    "role_id": 42,
                    "name": "externally changed",
                    "position": 1,
                    "permissions": 0,
                    "managed": False,
                    "color": 0,
                    "hoist": False,
                    "mentionable": False,
                }
            ]
        ),
        fetch_channels=AsyncMock(return_value=[]),
    )
    outcome = await adapter.check_preconditions(
        guild_id=GUILD,
        operation_type=OperationType.UPDATE_ROLE,
        payload={"id": 42, "name": "planned"},
        preconditions={
            "schema_version": "did-operation-precondition-v1",
            "mode": "MATCH_BEFORE",
            "before": {"id": 42, "name": "before"},
            "resource_id": 42,
        },
    )
    assert outcome is PreconditionOutcome.CHANGED


def test_gateway_overwrite_matcher_requires_full_expected_channel_state() -> None:
    expected = {
        "channel_id": 10,
        "overwrite": {
            "target_id": 20,
            "target_type": 0,
            "present": True,
            "allow": 1,
            "deny": 2,
        },
        "full_overwrites": [
            {"id": 20, "type": 0, "allow": 1, "deny": 2},
        ],
    }
    own = {
        "channel_id": 10,
        "permission_overwrites": [{"id": 20, "type": 0, "allow": 1, "deny": 2}],
    }
    external_same_channel = {
        "channel_id": 10,
        "permission_overwrites": [
            {"id": 20, "type": 0, "allow": 1, "deny": 2},
            {"id": 21, "type": 0, "allow": 4, "deny": 0},
        ],
    }
    assert RuntimeRepository._matches_expected_gateway(
        "UPSERT_OVERWRITE", "CHANNEL_UPDATE", expected, own
    )
    assert not RuntimeRepository._matches_expected_gateway(
        "UPSERT_OVERWRITE", "CHANNEL_UPDATE", expected, external_same_channel
    )


@pytest.mark.asyncio
async def test_real_impact_counts_visibility_removal_and_administrator_grant() -> None:
    view = DEFAULT_PERMISSION_REGISTRY.value("VIEW_CHANNEL")
    fresh = current_guild().freshness
    base = current_guild()
    everyone = replace(base.roles[0], permissions=view)
    role = RoleSnapshot(GUILD, 900, "subject", 1, 0, False, fresh)
    coverage = replace(base.coverage, members_complete=True)
    guild = replace(base, roles=(everyone, role), coverage=coverage)
    member = MemberSnapshot(GUILD, 901, (900,), True, fresh)
    reads = SimpleNamespace(cached_member_snapshots=AsyncMock(return_value=(member,)))
    service = PlanningService(SimpleNamespace(), reads)
    overwrite = PlanOperation(
        uuid4(),
        OperationType.UPSERT_OVERWRITE,
        ResourceType.OVERWRITE,
        "overwrite.visibility",
        freeze_json_object(
            {
                "channel_id": guild.channels[0].channel_id,
                "subject_id": 900,
                "target_type": 0,
                "allow": 0,
                "deny": view,
            }
        ),
        freeze_json_object({}),
        ("MANAGE_ROLES",),
        CompensationClass.REVERSIBLE,
        RiskLevel.MEDIUM,
        VerificationStrategy.TARGETED_GET,
        RecoveryStrategy.UPDATE_COMPARE_BEFORE_DESIRED,
        ("CHANNEL_UPDATE",),
    )
    visibility = await service._impact(guild, (overwrite,))
    assert visibility.affected_subjects == 1
    assert visibility.permission_removals > 0
    assert visibility.visibility_losses == 1

    grant_admin = PlanOperation(
        uuid4(),
        OperationType.UPDATE_ROLE,
        ResourceType.ROLE,
        "role.subject",
        freeze_json_object({"id": 900, "permissions": str(1 << 3)}),
        freeze_json_object({"id": 900, "permissions": 0}),
        ("MANAGE_ROLES",),
        CompensationClass.REVERSIBLE,
        RiskLevel.CRITICAL,
        VerificationStrategy.TARGETED_GET,
        RecoveryStrategy.UPDATE_COMPARE_BEFORE_DESIRED,
        ("GUILD_ROLE_UPDATE",),
    )
    administrator = await service._impact(guild, (grant_admin,))
    assert administrator.permission_additions > 0
    assert administrator.administrator_grants == 1


@pytest.mark.asyncio
async def test_category_children_expand_impact_and_unknown_coverage_is_not_zeroed() -> None:
    base = current_guild()
    category = replace(
        base.channels[0],
        channel_id=700,
        channel_type=ChannelType.GUILD_CATEGORY,
        name="category",
    )
    children = (
        replace(base.channels[0], channel_id=701, parent_id=700, name="one"),
        replace(base.channels[0], channel_id=702, parent_id=700, name="two"),
    )
    guild = replace(base, channels=(category, *children))
    reads = SimpleNamespace(cached_member_snapshots=AsyncMock(return_value=()))
    service = PlanningService(SimpleNamespace(), reads)
    deletion = PlanOperation(
        uuid4(),
        OperationType.DELETE_CHANNEL,
        ResourceType.CATEGORY,
        "category.delete",
        freeze_json_object({"id": 700}),
        freeze_json_object({"id": 700}),
        ("MANAGE_CHANNELS",),
        CompensationClass.RECREATABLE_NOT_RESTORABLE,
        RiskLevel.HIGH,
        VerificationStrategy.ABSENCE_WITH_OBSERVABILITY,
        RecoveryStrategy.DELETE_PROVE_ABSENCE,
        ("CHANNEL_DELETE",),
    )
    impact = await service._impact(guild, (deletion,))
    assert impact.affected_resources == 3
    assert impact.incomplete_or_unknown is True
