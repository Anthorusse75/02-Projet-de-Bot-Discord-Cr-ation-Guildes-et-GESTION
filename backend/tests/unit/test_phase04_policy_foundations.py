from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from did.api.main import create_app
from did.api.policies import (
    PolicyCreate,
    PolicyResolutionRequest,
    create_policy,
    list_policies,
    resolve_policy,
)
from did.domain.auth import READ_ONLY_CAPABILITIES, Capability
from did.domain.discord_runtime import CoverageMode, FreshnessState
from did.domain.policies import (
    Policy,
    PolicyLifecycleError,
    PolicyLifecycleState,
    PolicyScopeType,
)
from did.policies.registry import POLICY_TYPE_REGISTRY, PolicyDefinitionValidationError
from did.policies.resolver import PolicyResolution, PolicyResolutionOutcome, PolicyTargetState


def _policy(state: PolicyLifecycleState = PolicyLifecycleState.DRAFT) -> Policy:
    return Policy(
        policy_id=uuid4(),
        guild_id=123,
        policy_type="ACCESS_CONTROL",
        contract_version=1,
        name="Private staff channel",
        description="",
        lifecycle_state=state,
        revision=1,
        scope_type=PolicyScopeType.GUILD,
        scope_id=None,
        conditions=({"kind": "ALWAYS"},),
        effects=({"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"},),
        metadata={"summary": "Allow viewing"},
        created_by_user_id=456,
        modified_by_user_id=456,
        created_at=datetime.now(UTC),
    )


def test_policy_lifecycle_is_strict_and_versioned() -> None:
    draft = _policy()
    active = draft.transition_to(PolicyLifecycleState.ACTIVE)
    disabled = active.transition_to(PolicyLifecycleState.DISABLED)
    retired = disabled.transition_to(PolicyLifecycleState.RETIRED)

    assert [draft.revision, active.revision, disabled.revision, retired.revision] == [1, 2, 3, 4]
    with pytest.raises(PolicyLifecycleError):
        draft.transition_to(PolicyLifecycleState.DISABLED)
    with pytest.raises(PolicyLifecycleError):
        active.transition_to(PolicyLifecycleState.RETIRED)
    with pytest.raises(PolicyLifecycleError):
        retired.transition_to(PolicyLifecycleState.ACTIVE)


def test_closed_registry_normalizes_supported_declaration_and_references() -> None:
    validated = POLICY_TYPE_REGISTRY.validate(
        policy_type="ACCESS_CONTROL",
        contract_version=1,
        scope_type=PolicyScopeType.CHANNEL,
        conditions=[{"kind": "ROLE_MATCH", "match": "ANY", "role_ids": ["10", "20"]}],
        effects=[{"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"}],
        metadata={"summary": "Staff access", "tags": ["staff"]},
    )

    assert validated.conditions[0]["kind"] == "ROLE_MATCH"
    assert tuple(reference.scope_id for reference in validated.references) == ("10", "20")
    assert validated.metadata == {"summary": "Staff access", "tags": ["staff"], "reason": None}


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"policy_type": "UNKNOWN"}, "unknown Policy type"),
        ({"contract_version": 2}, "unknown Policy type"),
        ({"conditions": [{"kind": "ROLE_MATCH", "match": "ANY", "role_ids": []}]}, "role_ids"),
        ({"effects": []}, "at least 1 item"),
        ({"metadata": {}}, "summary"),
        ({"scope_type": PolicyScopeType.CAMPAIGN}, "not supported"),
        ({"conditions": [{"kind": "ALWAYS"}] * 101}, "100 items"),
    ],
)
def test_registry_rejects_unknown_or_invalid_contracts(overrides, fragment: str) -> None:
    values = {
        "policy_type": "ACCESS_CONTROL",
        "contract_version": 1,
        "scope_type": PolicyScopeType.GUILD,
        "conditions": [{"kind": "ALWAYS"}],
        "effects": [{"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"}],
        "metadata": {"summary": "Valid"},
    }
    values.update(overrides)
    with pytest.raises(PolicyDefinitionValidationError, match=fragment):
        POLICY_TYPE_REGISTRY.validate(**values)


@pytest.mark.security
@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "ALWAYS", "expression": "__import__('os').system('whoami')"},
        {"kind": "ALWAYS", "sql": "DROP TABLE policies"},
        {"kind": "ALWAYS", "callback": "https://attacker.invalid"},
        {"kind": "PYTHON", "source": "lambda: 1"},
    ],
)
def test_registry_refuses_arbitrary_code_or_open_ended_operators(payload) -> None:
    with pytest.raises(PolicyDefinitionValidationError):
        POLICY_TYPE_REGISTRY.validate(
            policy_type="ACCESS_CONTROL",
            contract_version=1,
            scope_type=PolicyScopeType.GUILD,
            conditions=[payload],
            effects=[{"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"}],
            metadata={"summary": "Closed schema"},
        )


def test_policy_api_and_distinct_rbac_capabilities_are_declared() -> None:
    contract = create_app().openapi()
    base = "/api/v1/guilds/{guild_id}/policies"
    assert base in contract["paths"]
    assert f"{base}/{{policy_id}}" in contract["paths"]
    assert f"{base}/{{policy_id}}/versions" in contract["paths"]
    assert "/api/v1/guilds/{guild_id}/policy-resolution" in contract["paths"]
    for action in ("activate", "disable", "retire"):
        path = f"{base}/{{policy_id}}/{action}"
        assert path in contract["paths"]
        assert any(
            parameter["name"] == "Idempotency-Key"
            for parameter in contract["paths"][path]["post"]["parameters"]
        )
    assert Capability.POLICIES_READ in READ_ONLY_CAPABILITIES
    assert Capability.POLICIES_CREATE not in READ_ONLY_CAPABILITIES
    assert (
        len(
            {
                Capability.POLICIES_READ,
                Capability.POLICIES_CREATE,
                Capability.POLICIES_UPDATE,
                Capability.POLICIES_ACTIVATE,
                Capability.POLICIES_RETIRE,
            }
        )
        == 5
    )


def test_policy_foundations_have_no_discord_mutation_or_expression_execution() -> None:
    forbidden_imports = ("discord", "did.infrastructure.discord")
    forbidden_calls = {"eval", "exec", "compile", "__import__"}
    violations: list[str] = []
    roots = (
        Path("backend/src/did/domain/policies.py"),
        Path("backend/src/did/policies/registry.py"),
        Path("backend/src/did/application/policies/service.py"),
        Path("backend/src/did/policies/resolver.py"),
    )
    for path in roots:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                forbidden_imports
            ):
                violations.append(f"{path}:{node.lineno}:import")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in forbidden_calls:
                    violations.append(f"{path}:{node.lineno}:{node.func.id}")
    assert violations == []


@pytest.mark.asyncio
async def test_api_calls_distinct_read_and_create_authorization_capabilities() -> None:
    authorization = SimpleNamespace(authorize=AsyncMock())
    policy_service = SimpleNamespace(list=AsyncMock(return_value=()), create_draft=AsyncMock())
    policy_service.create_draft.return_value = _policy()
    container = SimpleNamespace(authorization=authorization, policies=policy_service)
    session = SimpleNamespace(discord_user_id=456)

    await list_policies("123", session, container)
    assert authorization.authorize.await_args.kwargs["capability"] is Capability.POLICIES_READ
    assert authorization.authorize.await_args.kwargs.get("sensitive", False) is False

    authorization.authorize.reset_mock()
    await create_policy(
        "123",
        PolicyCreate(
            policy_type="ACCESS_CONTROL",
            contract_version=1,
            name="Policy",
            scope_type=PolicyScopeType.GUILD,
            conditions=[{"kind": "ALWAYS"}],
            effects=[{"kind": "SET_ACCESS", "access": "VIEW", "decision": "ALLOW"}],
            metadata={"summary": "Policy"},
        ),
        "create-key",
        session,
        container,
    )
    assert authorization.authorize.await_args.kwargs["capability"] is Capability.POLICIES_CREATE
    assert authorization.authorize.await_args.kwargs["sensitive"] is True
    assert policy_service.create_draft.await_args.kwargs["priority"] == 0


@pytest.mark.asyncio
async def test_explain_api_uses_read_capability_and_serializes_canonical_result() -> None:
    resolution = PolicyResolution(
        guild_id=123,
        subject_id=456,
        decision="ACCESS_CONTROL:VIEW",
        outcome=PolicyResolutionOutcome.CANNOT,
        target_scope_type=PolicyScopeType.GUILD,
        target_scope_id=None,
        target_state=PolicyTargetState.CURRENT,
        target_freshness=FreshnessState.FRESH,
        coverage=CoverageMode.FULL,
        applicable_policies=(),
        contributions=(),
        conflicts=(),
        source_scopes=(),
        priority_trace=(),
        conditions=(),
        incomplete_reasons=(),
        warnings=(),
        source_versions=("guild:1",),
    )
    authorization = SimpleNamespace(authorize=AsyncMock())
    policy_service = SimpleNamespace(resolve_access=AsyncMock(return_value=resolution))
    container = SimpleNamespace(authorization=authorization, policies=policy_service)
    session = SimpleNamespace(discord_user_id=456)

    response = await resolve_policy(
        "123",
        PolicyResolutionRequest(
            subject_id="456",
            target_scope_type=PolicyScopeType.GUILD,
            target_scope_id=None,
            requested_access="VIEW",
        ),
        session,
        container,
    )

    assert response["outcome"] == "CANNOT"
    assert response["target_state"] == "CURRENT"
    assert authorization.authorize.await_args.kwargs["capability"] is Capability.POLICIES_READ
    policy_service.resolve_access.assert_awaited_once_with(
        guild_id=123,
        subject_id=456,
        target_scope_type=PolicyScopeType.GUILD,
        target_scope_id=None,
        requested_access="VIEW",
    )
