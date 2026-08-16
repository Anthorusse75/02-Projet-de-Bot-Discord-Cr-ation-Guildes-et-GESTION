from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from argparse import ArgumentParser
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "artifacts" / "test-evidence"
IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}$")
GIT = shutil.which("git")
if GIT is None:
    raise RuntimeError("git executable is required for stage validation")
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
    command: str
    cwd: str
    status: str
    duration_seconds: float
    return_code: int | None


@dataclass(frozen=True, slots=True)
class StageDefinition:
    steps: Callable[[Path, bool, str], tuple[Step, ...]]
    requirements: tuple[str, ...]


def executable(name: str) -> str:
    if os.name == "nt" and name == "npm":
        return "npm.cmd"
    return name


def stage_01(
    evidence_directory: Path,
    include_discord_live: bool = False,
    profile: str = "default",
) -> tuple[Step, ...]:
    del include_discord_live, profile
    uv = executable("uv")
    npm = executable("npm")
    python = sys.executable
    junit_unit = evidence_directory / "backend-unit.xml"
    junit_integration = evidence_directory / "backend-integration.xml"
    junit_unit_argument = f"--junitxml={relative_path(junit_unit)}"
    junit_integration_argument = f"--junitxml={relative_path(junit_integration)}"
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
            (
                uv,
                "run",
                "pytest",
                "-m",
                "not integration and not load and not discord_live",
                junit_unit_argument,
            ),
        ),
        Step(
            "migration upgrade head",
            (uv, "run", "alembic", "upgrade", "head"),
            environment=TEST_ENV,
        ),
        Step(
            "PostgreSQL RLS and Redis integration",
            (
                uv,
                "run",
                "pytest",
                "-m",
                "integration",
                junit_integration_argument,
            ),
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


def stage_02(
    evidence_directory: Path,
    include_discord_live: bool = False,
    profile: str = "default",
) -> tuple[Step, ...]:
    del profile
    base_steps = list(stage_01(evidence_directory))
    migration_index = next(
        index for index, step in enumerate(base_steps) if step.name == "migration upgrade head"
    )
    uv = executable("uv")
    migration_rehearsal = [
        Step(
            "migration downgrade base on disposable database",
            (uv, "run", "alembic", "downgrade", "base"),
            environment=TEST_ENV,
        ),
        Step(
            "migration empty base to head",
            (uv, "run", "alembic", "upgrade", "head"),
            environment=TEST_ENV,
        ),
        Step(
            "migration downgrade to STAGE 01",
            (uv, "run", "alembic", "downgrade", "0001_stage_01"),
            environment=TEST_ENV,
        ),
        Step(
            "migration STAGE 01 to head",
            (uv, "run", "alembic", "upgrade", "head"),
            environment=TEST_ENV,
        ),
    ]
    base_steps[migration_index : migration_index + 1] = migration_rehearsal
    live_arguments = [
        uv,
        "run",
        "python",
        "scripts/validate_discord_live_stage02.py",
        "--report",
        relative_path(evidence_directory / "discord-live.json"),
    ]
    if include_discord_live:
        live_arguments.append("--include")
    base_steps.append(
        Step(
            "Discord live sandbox validation",
            tuple(live_arguments),
            timeout_seconds=1800,
        )
    )
    return tuple(base_steps)


def stage_03(
    evidence_directory: Path,
    include_discord_live: bool = False,
    profile: str = "default",
) -> tuple[Step, ...]:
    uv = executable("uv")
    python = sys.executable
    if profile == "load":
        return (
            Step("python lock sync", (uv, "sync", "--frozen", "--python", "3.13"), 600),
            Step("backend lint", (uv, "run", "ruff", "check", ".")),
            Step("backend typecheck", (uv, "run", "mypy")),
            Step(
                "deterministic Discord workload load and fairness",
                (
                    uv,
                    "run",
                    "pytest",
                    "-m",
                    "load",
                    f"--junitxml={relative_path(evidence_directory / 'backend-load.xml')}",
                ),
                environment={
                    "DID_LOAD_REPORT": relative_path(evidence_directory / "load-fairness.json")
                },
            ),
            Step("secret scan", (python, "scripts/check_secrets.py")),
            Step("documentation validation", (python, "scripts/validate_documentation.py")),
        )
    base_steps = list(stage_02(evidence_directory, include_discord_live=False))
    last_migration = max(
        index for index, step in enumerate(base_steps) if step.name.startswith("migration ")
    )
    base_steps[last_migration + 1 : last_migration + 1] = [
        Step(
            "migration downgrade STAGE 03 to STAGE 02",
            (uv, "run", "alembic", "downgrade", "0002_stage_02"),
            environment=TEST_ENV,
        ),
        Step(
            "migration STAGE 02 to STAGE 03 head",
            (uv, "run", "alembic", "upgrade", "head"),
            environment=TEST_ENV,
        ),
    ]
    live_arguments = [
        uv,
        "run",
        "python",
        "scripts/validate_discord_live_stage03.py",
        "--report",
        relative_path(evidence_directory / "discord-live-stage03.json"),
    ]
    if include_discord_live:
        live_arguments.append("--include")
    base_steps.append(
        Step("Discord live STAGE 03 safe sandbox validation", tuple(live_arguments), 600)
    )
    return tuple(base_steps)


STAGES: dict[str, StageDefinition] = {
    "01": StageDefinition(
        steps=stage_01,
        requirements=(
            "REQ-TEN-001",
            "REQ-TEN-007",
            "REQ-TEN-010",
            "REQ-AUD-004",
            "REQ-BOT-001",
        ),
    ),
    "02": StageDefinition(
        steps=stage_02,
        requirements=(
            *(f"REQ-INST-{index:03d}" for index in range(1, 8)),
            *(f"REQ-AUTH-{index:03d}" for index in range(1, 15)),
            *(f"REQ-TEN-{index:03d}" for index in range(1, 11)),
            "REQ-BOT-001",
            "REQ-BOT-002",
            "REQ-BOT-003",
            "REQ-BOT-007",
        ),
    ),
    "03": StageDefinition(
        steps=stage_03,
        requirements=(
            *(f"REQ-GW-{index:03d}" for index in range(1, 9)),
            *(f"REQ-CACHE-{index:03d}" for index in range(1, 14)),
            *(f"REQ-RATE-{index:03d}" for index in range(1, 7)),
            *(f"REQ-AUD-{index:03d}" for index in range(1, 7)),
            *(f"REQ-TEN-{index:03d}" for index in range(5, 10)),
            "REQ-INST-006",
            "REQ-AUTH-013",
        ),
    ),
}


def command_text(command: tuple[str, ...]) -> str:
    portable = tuple("python" if item == sys.executable else item for item in command)
    return subprocess.list2cmdline(portable) if os.name == "nt" else " ".join(portable)


def relative_path(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def tested_commit() -> str:
    completed = subprocess.run(
        [GIT, "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def repository_dirty() -> bool:
    completed = subprocess.run(
        [GIT, "status", "--porcelain"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(completed.stdout.strip())


def evidence_environment() -> str:
    value = os.environ.get("DID_VALIDATION_ENVIRONMENT")
    if value is None:
        value = "ci" if os.environ.get("CI") else "local-docker"
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError("DID_VALIDATION_ENVIRONMENT must be a safe, non-secret identifier")
    return value


def evidence_run_id(*, commit: str, started_at: datetime) -> str:
    configured = os.environ.get("DID_EVIDENCE_RUN_ID")
    if configured is not None:
        run_id = configured
    else:
        timestamp = started_at.strftime("%Y%m%dT%H%M%S%fZ")
        run_id = f"{timestamp}-{commit[:12]}-{evidence_environment()}"
    if not IDENTIFIER_PATTERN.fullmatch(run_id):
        raise ValueError("DID_EVIDENCE_RUN_ID must be a safe, non-secret identifier")
    return run_id


def create_evidence_directory(*, stage: str, run_id: str) -> Path:
    directory = EVIDENCE_ROOT / f"stage-{stage}" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def run_step(step: Step) -> Result:
    printable = command_text(step.command)
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
        return Result(
            step.name,
            printable,
            relative_path(step.cwd) or ".",
            status,
            duration,
            completed.returncode,
        )
    except subprocess.TimeoutExpired:
        duration = round(time.monotonic() - started, 3)
        return Result(
            step.name,
            printable,
            relative_path(step.cwd) or ".",
            "TIMEOUT",
            duration,
            None,
        )


def evidence_artifacts(evidence_directory: Path) -> list[str]:
    artifacts = [relative_path(evidence_directory / "summary.json")]
    artifacts.extend(
        relative_path(path)
        for path in sorted(evidence_directory.iterdir())
        if path.is_file() and path.name != "summary.json"
    )
    artifact_identifier = os.environ.get("DID_EVIDENCE_ARTIFACT_ID")
    if artifact_identifier:
        if not IDENTIFIER_PATTERN.fullmatch(artifact_identifier):
            raise ValueError("DID_EVIDENCE_ARTIFACT_ID must be a safe, non-secret identifier")
        artifacts.append(f"github-actions-artifact:{artifact_identifier}")
    return artifacts


def write_summary(
    *,
    stage: str,
    definition: StageDefinition,
    steps: tuple[Step, ...],
    results: list[Result],
    commit: str,
    dirty: bool,
    environment: str,
    run_id: str,
    started_at: datetime,
    evidence_directory: Path,
    include_discord_live: bool = False,
    profile: str = "default",
) -> dict[str, object]:
    result = (
        "PASS"
        if len(results) == len(steps) and all(gate.status == "PASS" for gate in results)
        else "FAIL"
    )
    redactions_checked = any(
        gate.name == "secret scan" and gate.status == "PASS" for gate in results
    )
    summary: dict[str, object] = {
        "stage": stage,
        "run_id": run_id,
        "commit": commit,
        "repository_dirty": dirty,
        "started_at": started_at.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": environment,
        "commands": [
            "python scripts/validate_stage.py "
            f"{stage}{' --profile load' if profile == 'load' else ''}"
            f"{' --include-discord-live' if include_discord_live else ''}",
            *(gate.command for gate in results),
        ],
        "result": result,
        "requirements": list(definition.requirements),
        "artifacts": evidence_artifacts(evidence_directory),
        "redactions_checked": redactions_checked,
        "gates": [asdict(gate) for gate in results],
    }
    summary_path = evidence_directory / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = ArgumentParser(description="Validate one implementation stage")
    parser.add_argument("stage", choices=sorted(STAGES))
    parser.add_argument("--include-discord-live", action="store_true")
    parser.add_argument("--profile", choices=("default", "load"), default="default")
    arguments = parser.parse_args()
    if arguments.stage not in STAGES:
        known = ", ".join(sorted(STAGES))
        print(f"Usage: python scripts/validate_stage.py <stage>; known stages: {known}")
        return 2

    stage = arguments.stage
    definition = STAGES[stage]
    started_at = datetime.now(UTC)
    commit = tested_commit()
    dirty = repository_dirty()
    environment = evidence_environment()
    run_id = evidence_run_id(commit=commit, started_at=started_at)
    try:
        evidence_directory = create_evidence_directory(stage=stage, run_id=run_id)
    except FileExistsError:
        print(f"Evidence run already exists and will not be overwritten: stage-{stage}/{run_id}")
        return 2

    if arguments.profile == "load" and stage != "03":
        print("The load profile is defined only for STAGE 03")
        return 2
    steps = definition.steps(evidence_directory, arguments.include_discord_live, arguments.profile)
    results: list[Result] = []
    for step in steps:
        result = run_step(step)
        results.append(result)
        print(f"[{result.status}] {result.name} ({result.duration_seconds:.3f}s)", flush=True)
        if result.status != "PASS":
            break

    summary = write_summary(
        stage=stage,
        definition=definition,
        steps=steps,
        results=results,
        commit=commit,
        dirty=dirty,
        environment=environment,
        run_id=run_id,
        started_at=started_at,
        evidence_directory=evidence_directory,
        include_discord_live=arguments.include_discord_live,
        profile=arguments.profile,
    )
    summary_path = relative_path(evidence_directory / "summary.json")
    print(f"\nStage {stage}: {summary['result']} — summary: {summary_path}")
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
