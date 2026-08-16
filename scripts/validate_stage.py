from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "stage-01"
TEST_ENV = {
    "DID_APP_ENV": "test",
    "DID_DATABASE_URL": (
        "postgresql+asyncpg://did_app:local_app_password@localhost:55432/did_test"
    ),
    "DID_DATABASE_ADMIN_URL": (
        "postgresql+asyncpg://did_admin:local_admin_password@localhost:55432/did_test"
    ),
    "DID_REDIS_URL": "redis://localhost:56379/0",
}


@dataclass(frozen=True, slots=True)
class Step:
    name: str
    command: tuple[str, ...]
    timeout_seconds: int = 300
    cwd: Path = ROOT
    environment: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class Result:
    name: str
    status: str
    duration_seconds: float
    return_code: int | None


def executable(name: str) -> str:
    if os.name == "nt" and name == "npm":
        return "npm.cmd"
    return name


def stage_01() -> tuple[Step, ...]:
    uv = executable("uv")
    npm = executable("npm")
    python = sys.executable
    junit_unit = ARTIFACTS / "backend-unit.xml"
    junit_integration = ARTIFACTS / "backend-integration.xml"
    integration_env = {**TEST_ENV, "DID_RUN_INTEGRATION": "1"}
    return (
        Step(
            "compose development config",
            ("docker", "compose", "-f", "compose.yaml", "config", "--quiet"),
        ),
        Step(
            "compose test config",
            ("docker", "compose", "-f", "compose.test.yaml", "config", "--quiet"),
        ),
        Step(
            "backend container build",
            (
                "docker",
                "build",
                "--file",
                "backend/Dockerfile",
                "--tag",
                "did-stage01-backend:validation",
                ".",
            ),
            600,
        ),
        Step(
            "PostgreSQL service healthy",
            (
                "docker",
                "compose",
                "-f",
                "compose.test.yaml",
                "exec",
                "-T",
                "postgres",
                "pg_isready",
                "-U",
                "did_admin",
                "-d",
                "did_test",
            ),
        ),
        Step(
            "Redis service healthy",
            (
                "docker",
                "compose",
                "-f",
                "compose.test.yaml",
                "exec",
                "-T",
                "redis",
                "redis-cli",
                "ping",
            ),
        ),
        Step("python lock sync", (uv, "sync", "--frozen", "--python", "3.13"), 600),
        Step("backend lint", (uv, "run", "ruff", "check", ".")),
        Step("backend format", (uv, "run", "ruff", "format", "--check", ".")),
        Step("backend typecheck", (uv, "run", "mypy")),
        Step(
            "backend unit tests",
            (uv, "run", "pytest", "-m", "not integration", f"--junitxml={junit_unit}"),
        ),
        Step(
            "migration upgrade head",
            (uv, "run", "alembic", "upgrade", "head"),
            environment=TEST_ENV,
        ),
        Step(
            "PostgreSQL RLS and Redis integration",
            (uv, "run", "pytest", "-m", "integration", f"--junitxml={junit_integration}"),
            environment=integration_env,
        ),
        Step("frontend lock install", (npm, "ci"), 600, ROOT / "frontend"),
        Step("frontend lint", (npm, "run", "lint"), cwd=ROOT / "frontend"),
        Step("frontend typecheck", (npm, "run", "typecheck"), cwd=ROOT / "frontend"),
        Step("frontend tests", (npm, "run", "test"), cwd=ROOT / "frontend"),
        Step("frontend build", (npm, "run", "build"), cwd=ROOT / "frontend"),
        Step("secret scan", (python, "scripts/check_secrets.py")),
        Step("documentation validation", (python, "scripts/validate_documentation.py")),
    )


STAGES: dict[str, tuple[Step, ...]] = {"01": stage_01()}


def run_step(step: Step) -> Result:
    printable = " ".join(step.command)
    print(f"\n[{step.name}] {printable}", flush=True)
    environment = os.environ.copy()
    if step.environment:
        environment.update(step.environment)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(step.command),
            cwd=step.cwd,
            env=environment,
            timeout=step.timeout_seconds,
            check=False,
        )
        duration = round(time.monotonic() - started, 3)
        status = "PASS" if completed.returncode == 0 else "FAIL"
        return Result(step.name, status, duration, completed.returncode)
    except subprocess.TimeoutExpired:
        duration = round(time.monotonic() - started, 3)
        return Result(step.name, "TIMEOUT", duration, None)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in STAGES:
        known = ", ".join(sorted(STAGES))
        print(f"Usage: python scripts/validate_stage.py <stage>; known stages: {known}")
        return 2
    stage = sys.argv[1]
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    results: list[Result] = []
    for step in STAGES[stage]:
        result = run_step(step)
        results.append(result)
        print(f"[{result.status}] {result.name} ({result.duration_seconds:.3f}s)", flush=True)
        if result.status != "PASS":
            break

    summary = {
        "stage": stage,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS"
        if len(results) == len(STAGES[stage]) and all(result.status == "PASS" for result in results)
        else "FAIL",
        "results": [asdict(result) for result in results],
    }
    summary_path = ARTIFACTS / "validation-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\nStage {stage}: {summary['status']} — summary: {summary_path.relative_to(ROOT)}")
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
