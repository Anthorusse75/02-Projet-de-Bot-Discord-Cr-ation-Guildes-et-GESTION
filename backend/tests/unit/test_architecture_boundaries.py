import ast
from pathlib import Path

FORBIDDEN_DOMAIN_IMPORTS = ("fastapi", "sqlalchemy", "redis", "discord", "did.infrastructure")


def find_forbidden_domain_imports(domain_root: Path) -> list[str]:
    violations: list[str] = []
    for path in domain_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.startswith(FORBIDDEN_DOMAIN_IMPORTS):
                    violations.append(f"{path}:{node.lineno}:{name}")
    return violations


def test_domain_has_no_infrastructure_or_transport_imports() -> None:
    domain_root = Path("backend/src/did/domain")
    violations = find_forbidden_domain_imports(domain_root)
    assert violations == []


def test_domain_guard_detects_violation_in_nested_subpackage(tmp_path: Path) -> None:
    nested = tmp_path / "domain" / "policies" / "nested"
    nested.mkdir(parents=True)
    violating_module = nested / "policy.py"
    violating_module.write_text("from sqlalchemy import select\n", encoding="utf-8")

    violations = find_forbidden_domain_imports(tmp_path / "domain")

    assert violations == [f"{violating_module}:1:sqlalchemy"]


def test_application_code_uses_only_the_safe_logging_entrypoint() -> None:
    source_root = Path("backend/src/did")
    logging_module = source_root / "infrastructure" / "logging.py"
    forbidden_methods = {"debug", "info", "warning", "error", "exception", "critical", "log"}
    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        if path == logging_module:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in forbidden_methods
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id.endswith("logger")
            ):
                violations.append(f"{path}:{node.lineno}:{node.func.attr}")
    assert violations == []


def test_redis_prefix_is_owned_by_the_namespace_builder() -> None:
    source_root = Path("backend/src/did")
    owners = [
        path.as_posix()
        for path in source_root.rglob("*.py")
        if "did:guild:" in path.read_text(encoding="utf-8")
    ]
    assert owners == ["backend/src/did/infrastructure/redis.py"]


def test_stage04_permission_engine_is_transport_and_persistence_independent() -> None:
    permission_root = Path("backend/src/did/permissions")
    forbidden = ("fastapi", "sqlalchemy", "redis", "discord", "did.infrastructure")
    violations: list[str] = []
    for path in permission_root.rglob("*.py"):
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


def test_stage04_api_router_has_no_discord_transport_or_mutation_engine_dependency() -> None:
    path = Path("backend/src/did/api/stage04.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(
        module.startswith(("discord", "did.infrastructure.discord", "did.application.plans"))
        for module in imported
    )
    assert "DiscordMemberClient" not in source
