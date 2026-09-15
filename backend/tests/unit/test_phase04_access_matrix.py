from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import ValidationError

from did.api.main import create_app
from did.api.policies import (
    MAX_BULK_POLICIES,
    MAX_MATRIX_ROLES,
    AccessMatrixRequest,
    BulkPolicyPreviewRequest,
    PolicyCreate,
    resolve_access_matrix,
)
from did.application.auth.service import AuthorizationDenied
from did.application.policies.service import BulkPolicyDraftDefinition, PolicyService
from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
from did.domain.policies import Policy, PolicyLifecycleState, PolicyScopeType
from did.domain.read_model import (
    ChannelSnapshot,
    CoverageSnapshot,
    FreshnessSnapshot,
    GuildSnapshot,
    RoleSnapshot,
)
from did.domain.read_model.models import ChannelType
from did.permissions import DEFAULT_PERMISSION_REGISTRY
from did.permissions.views import AccessSynthesis
from did.policies.resolver import PolicyResolutionOutcome

GUILD = 993_001
ACTOR = 993_011
ROLE_A = 993_201
ROLE_B = 993_202
CHANNEL = 993_301
NOW = datetime(2026, 9, 15, tzinfo=UTC)


def _guild() -> GuildSnapshot:
    fresh = FreshnessSnapshot(FreshnessState.FRESH, "CACHE", 1, NOW, NOW, NOW)
    coverage = CoverageSnapshot(
        GUILD,
        CoverageMode.FULL,
        FreshnessState.FRESH,
        "CACHE",
        1,
        known_channels=1,
        visible_channels=1,
        known_roles=3,
        members_complete=True,
        overwrites_complete=True,
    )
    view_bit = DEFAULT_PERMISSION_REGISTRY.value("VIEW_CHANNEL")
    return GuildSnapshot(
        GUILD,
        ACTOR,
        (
            RoleSnapshot(GUILD, GUILD, "@everyone", 0, 0, False, fresh),
            RoleSnapshot(GUILD, ROLE_A, "role-a", 1, view_bit, False, fresh),
            RoleSnapshot(GUILD, ROLE_B, "role-b", 2, 0, False, fresh),
        ),
        (
            ChannelSnapshot(
                GUILD,
                CHANNEL,
                ChannelType.GUILD_TEXT,
                0,
                None,
                "general",
                (),
                True,
                ObservabilityState.VISIBLE,
                fresh,
            ),
        ),
        coverage,
        fresh,
        source_versions=("guild:1",),
    )


def _policy(number: int, *, role_id: int, decision: str, access: str = "VIEW") -> Policy:
    return Policy(
        policy_id=UUID(int=number),
        guild_id=GUILD,
        policy_type="ACCESS_CONTROL",
        contract_version=1,
        name=f"Policy {number}",
        description="",
        lifecycle_state=PolicyLifecycleState.ACTIVE,
        revision=1,
        scope_type=PolicyScopeType.CHANNEL,
        scope_id=str(CHANNEL),
        conditions=({"kind": "ROLE_MATCH", "match": "ANY", "role_ids": [str(role_id)]},),
        effects=({"kind": "SET_ACCESS", "access": access, "decision": decision},),
        metadata={"summary": f"Policy {number}"},
        created_by_user_id=ACTOR,
        modified_by_user_id=ACTOR,
        priority=0,
    )


def _services(
    policies: tuple[Policy, ...], guild: GuildSnapshot | None = None
) -> tuple[PolicyService, SimpleNamespace]:
    guild = guild or _guild()
    repository = SimpleNamespace(
        list=AsyncMock(return_value=policies),
        create=AsyncMock(side_effect=AssertionError("resolve_matrix must never mutate")),
        update_draft=AsyncMock(side_effect=AssertionError("resolve_matrix must never mutate")),
    )
    read_models = SimpleNamespace(
        guild_snapshot=AsyncMock(return_value=(guild, None)),
        list_logical_groups=AsyncMock(return_value=[]),
    )
    service = PolicyService(repository, read_models=read_models)  # type: ignore[arg-type]
    return service, repository


@pytest.mark.asyncio
async def test_resolve_matrix_synthesizes_discord_access_from_the_canonical_evaluator() -> None:
    service, repository = _services(())

    result = await service.resolve_matrix(
        guild_id=GUILD, actor_user_id=ACTOR, role_ids=(ROLE_A, ROLE_B), resource_ids=(CHANNEL,)
    )

    cell_a = next(cell for cell in result.cells if cell.role_id == ROLE_A)
    cell_b = next(cell for cell in result.cells if cell.role_id == ROLE_B)
    assert cell_a.synthesis is AccessSynthesis.VIEW
    assert cell_b.synthesis is AccessSynthesis.NONE
    repository.create.assert_not_awaited()
    repository.update_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_matrix_flags_conflict_from_resolver_independently_of_discord_bits() -> None:
    # Role A's Discord bit still grants VIEW (fixed on the role itself) even though the two
    # equal-rank Policies covering it are mutually exclusive -- the two engines are independent
    # sources feeding the same cell, exactly as the product requirement expects.
    allow = _policy(1, role_id=ROLE_A, decision="ALLOW")
    deny = _policy(2, role_id=ROLE_A, decision="DENY")
    service, _ = _services((allow, deny))

    result = await service.resolve_matrix(
        guild_id=GUILD, actor_user_id=ACTOR, role_ids=(ROLE_A, ROLE_B), resource_ids=(CHANNEL,)
    )

    cell_a = next(cell for cell in result.cells if cell.role_id == ROLE_A)
    cell_b = next(cell for cell in result.cells if cell.role_id == ROLE_B)
    assert cell_a.synthesis is AccessSynthesis.VIEW
    assert cell_a.policy_outcome is PolicyResolutionOutcome.BLOCKED
    assert cell_a.conflict is True
    assert set(cell_a.conflict_policy_ids) == {UUID(int=1), UUID(int=2)}
    assert cell_b.conflict is False


@pytest.mark.asyncio
async def test_resolve_matrix_does_not_hide_a_write_only_policy_conflict() -> None:
    allow = _policy(1, role_id=ROLE_A, decision="ALLOW", access="WRITE")
    deny = _policy(2, role_id=ROLE_A, decision="DENY", access="WRITE")
    service, _ = _services((allow, deny))

    result = await service.resolve_matrix(
        guild_id=GUILD, actor_user_id=ACTOR, role_ids=(ROLE_A,), resource_ids=(CHANNEL,)
    )

    assert result.cells[0].synthesis is AccessSynthesis.VIEW
    assert result.cells[0].conflict is True
    assert result.cells[0].policy_outcome is PolicyResolutionOutcome.BLOCKED


@pytest.mark.asyncio
async def test_resolve_matrix_marks_an_unknown_role_as_unknown_not_a_guess() -> None:
    service, _ = _services(())
    unknown_role = 993_999

    result = await service.resolve_matrix(
        guild_id=GUILD, actor_user_id=ACTOR, role_ids=(unknown_role,), resource_ids=(CHANNEL,)
    )

    cell = result.cells[0]
    assert cell.role_known is False
    assert cell.permission_status == "UNKNOWN"
    assert cell.policy_outcome is PolicyResolutionOutcome.UNKNOWN
    assert cell.synthesis is AccessSynthesis.UNKNOWN


@pytest.mark.asyncio
async def test_resolve_matrix_marks_an_unknown_resource_as_unknown_not_a_guess() -> None:
    service, _ = _services(())
    unknown_resource = 993_888

    result = await service.resolve_matrix(
        guild_id=GUILD, actor_user_id=ACTOR, role_ids=(ROLE_A,), resource_ids=(unknown_resource,)
    )

    cell = result.cells[0]
    assert cell.role_known is True
    assert cell.resource_known is False
    assert cell.permission_status == "UNKNOWN"
    assert cell.synthesis is AccessSynthesis.UNKNOWN


@pytest.mark.asyncio
async def test_resolve_matrix_turns_stale_permission_facts_into_unknown_synthesis() -> None:
    guild = _guild()
    stale = replace(guild.freshness, state=FreshnessState.STALE)
    stale_channel = replace(guild.channels[0], freshness=stale)
    guild = replace(
        guild,
        channels=(stale_channel,),
        freshness=stale,
        coverage=replace(guild.coverage, freshness=FreshnessState.STALE),
    )
    service, _ = _services((), guild)

    result = await service.resolve_matrix(
        guild_id=GUILD, actor_user_id=ACTOR, role_ids=(ROLE_A,), resource_ids=(CHANNEL,)
    )

    assert result.cells[0].permission_status != "COMPLETE"
    assert result.cells[0].synthesis is AccessSynthesis.UNKNOWN


@pytest.mark.asyncio
async def test_foreign_tenant_is_rejected_before_matrix_data_is_read() -> None:
    authorization = SimpleNamespace(
        authorize=AsyncMock(side_effect=AuthorizationDenied("TENANT_ACCESS_DENIED"))
    )
    policies = SimpleNamespace(resolve_matrix=AsyncMock())
    container = SimpleNamespace(authorization=authorization, policies=policies)
    foreign_session = SimpleNamespace(discord_user_id=994_011)

    with pytest.raises(AuthorizationDenied, match="TENANT_ACCESS_DENIED"):
        await resolve_access_matrix(
            str(GUILD),
            AccessMatrixRequest(role_ids=[str(ROLE_A)], resource_ids=[str(CHANNEL)]),
            foreign_session,
            container,
        )

    policies.resolve_matrix.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_matrix_is_deterministic_for_the_same_inputs() -> None:
    allow = _policy(1, role_id=ROLE_A, decision="ALLOW")
    service, _ = _services((allow,))

    first = await service.resolve_matrix(
        guild_id=GUILD, actor_user_id=ACTOR, role_ids=(ROLE_A, ROLE_B), resource_ids=(CHANNEL,)
    )
    second = await service.resolve_matrix(
        guild_id=GUILD, actor_user_id=ACTOR, role_ids=(ROLE_A, ROLE_B), resource_ids=(CHANNEL,)
    )

    assert first.cells == second.cells


def test_access_matrix_request_rejects_batches_above_the_documented_role_bound() -> None:
    with pytest.raises(ValidationError):
        AccessMatrixRequest(
            role_ids=[str(value) for value in range(MAX_MATRIX_ROLES + 1)],
            resource_ids=[str(CHANNEL)],
        )


def test_matrix_and_bulk_endpoints_are_present_in_the_openapi_contract() -> None:
    paths = create_app().openapi()["paths"]
    matrix = "/api/v1/guilds/{guild_id}/access-matrix/resolve"
    bulk_preview = "/api/v1/guilds/{guild_id}/policies/bulk-preview"
    bulk_plan = "/api/v1/guilds/{guild_id}/policies/bulk-plan"
    assert matrix in paths
    for path in (bulk_preview, bulk_plan):
        assert path in paths
        assert any(
            parameter["name"] == "Idempotency-Key"
            for parameter in paths[path]["post"]["parameters"]
        )


def test_bulk_policy_request_rejects_batches_above_the_bound() -> None:
    definition = PolicyCreate(
        policy_type="ACCESS_CONTROL",
        contract_version=1,
        name="Bulk",
        scope_type=PolicyScopeType.CHANNEL,
        scope_id=str(CHANNEL),
        conditions=[{"kind": "ALWAYS"}],
        effects=[{"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"}],
        metadata={"summary": "Bulk"},
    )
    with pytest.raises(ValidationError):
        BulkPolicyPreviewRequest(definitions=[definition] * (MAX_BULK_POLICIES + 1))


@pytest.mark.asyncio
async def test_bulk_draft_retry_uses_the_same_per_resource_idempotency_keys() -> None:
    repository = SimpleNamespace(
        validate_target=AsyncMock(),
        validate_role_references=AsyncMock(),
        create=AsyncMock(side_effect=lambda policy, **_: policy),
    )
    service = PolicyService(repository)  # type: ignore[arg-type]
    definitions = (
        BulkPolicyDraftDefinition(
            policy_type="ACCESS_CONTROL",
            contract_version=1,
            name="Bulk",
            description="",
            scope_type=PolicyScopeType.CHANNEL,
            scope_id=str(CHANNEL),
            conditions=({"kind": "ALWAYS"},),
            effects=({"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"},),
            metadata={"summary": "Bulk"},
        ),
    )

    await service.create_bulk_drafts(
        guild_id=GUILD, actor_id=ACTOR, definitions=definitions, idempotency_key="gesture-1"
    )
    await service.create_bulk_drafts(
        guild_id=GUILD, actor_id=ACTOR, definitions=definitions, idempotency_key="gesture-1"
    )

    keys = [call.kwargs["idempotency_key"] for call in repository.create.await_args_list]
    assert keys[0] == keys[1]
    assert keys[0].startswith("policy-bulk:")
    metadata = [call.args[0].metadata for call in repository.create.await_args_list]
    assert metadata[0]["tags"] == metadata[1]["tags"]
    assert metadata[0]["tags"][0].startswith("bulk-operation:")


def test_bulk_plan_child_key_is_stable_per_policy_revision() -> None:
    policy_id = UUID(int=42)
    first = PolicyService.bulk_child_key("prepare-gesture", "plan", str(policy_id), "1")
    retry = PolicyService.bulk_child_key("prepare-gesture", "plan", str(policy_id), "1")
    next_revision = PolicyService.bulk_child_key("prepare-gesture", "plan", str(policy_id), "2")
    assert first == retry
    assert first != next_revision
