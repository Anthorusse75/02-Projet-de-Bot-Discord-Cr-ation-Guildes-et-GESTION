import ast
from pathlib import Path


def test_domain_has_no_infrastructure_or_transport_imports() -> None:
    domain_root = Path("backend/src/did/domain")
    forbidden = ("fastapi", "sqlalchemy", "redis", "discord", "did.infrastructure")
    violations: list[str] = []
    for path in domain_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.startswith(forbidden):
                    violations.append(f"{path}:{node.lineno}:{name}")
    assert violations == []


def test_redis_prefix_is_owned_by_the_namespace_builder() -> None:
    source_root = Path("backend/src/did")
    owners = [
        path.as_posix()
        for path in source_root.rglob("*.py")
        if "did:guild:" in path.read_text(encoding="utf-8")
    ]
    assert owners == ["backend/src/did/infrastructure/redis.py"]
