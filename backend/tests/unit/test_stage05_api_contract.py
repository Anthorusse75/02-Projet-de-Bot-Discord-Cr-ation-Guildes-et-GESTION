from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from did.api.main import create_app
from did.api.stage05 import ConfirmationCommand, DesiredNodeInput, PlanCreate
from did.planning.models import ResourceType


def test_stage05_routes_are_registered_with_async_apply_boundary() -> None:
    paths = set(create_app().openapi()["paths"])
    base = "/api/v1/guilds/{guild_id}/plans"
    assert base in paths
    assert f"{base}/{{plan_id}}/validate" in paths
    assert f"{base}/{{plan_id}}/confirm" in paths
    assert f"{base}/{{plan_id}}/apply" in paths
    assert f"{base}/{{plan_id}}/cancel" in paths
    assert f"{base}/{{plan_id}}/progress" in paths


@pytest.mark.security
def test_stage05_api_rejects_unknown_fields_unsupported_properties_and_numeric_ids() -> None:
    with pytest.raises(ValidationError):
        PlanCreate.model_validate({"nodes": [], "unexpected": True})
    with pytest.raises(ValidationError):
        DesiredNodeInput.model_validate(
            {
                "logical_key": "role.test",
                "resource_type": "ROLE",
                "symbol": "sym.role.test",
                "properties": {"not_a_discord_role_field": True},
            }
        )
    with pytest.raises(ValidationError):
        DesiredNodeInput.model_validate(
            {
                "logical_key": "role.test",
                "resource_type": "ROLE",
                "discord_id": 123456789012345678,
            }
        )
    with pytest.raises(ValidationError):
        PlanCreate.model_validate({"nodes": []})
    with pytest.raises(ValidationError):
        DesiredNodeInput.model_validate(
            {
                "logical_key": "role.test",
                "resource_type": "ROLE",
                "relations": [{"name": "parent", "kind": "DISCORD_ID", "value": "123"}],
            }
        )


def test_confirmation_contract_binds_full_hash_and_bounded_acknowledgement() -> None:
    value = ConfirmationCommand(
        expected_version=2,
        plan_hash="a" * 64,
        acknowledgement=f"CONFIRM DESTRUCTIVE {'a' * 64}",
    )
    assert value.plan_hash == "a" * 64
    with pytest.raises(ValidationError):
        ConfirmationCommand(expected_version=2, plan_hash="short")


def test_planning_core_has_no_transport_or_persistence_imports() -> None:
    forbidden = ("fastapi", "sqlalchemy", "redis", "discord", "did.infrastructure")
    violations: list[str] = []
    for path in Path("backend/src/did/planning").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import) and node.names:
                module = node.names[0].name
            if module and module.startswith(forbidden):
                violations.append(f"{path}:{node.lineno}:{module}")
    assert violations == []


def test_api_layer_cannot_import_mutable_discord_adapter() -> None:
    violations = []
    for path in Path("backend/src/did/api").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "did.infrastructure.discord":
                violations.append(f"{path}:{node.lineno}")
    assert violations == []
    assert ResourceType.ROLE.value == "ROLE"
