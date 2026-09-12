from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import validate_stage as validation
from run_stage10_unattended_until_stage02 import _live_step


def _load_progress(evidence_directory: Path) -> dict[str, Any]:
    path = evidence_directory / "stage10-unattended-progress.json"
    if not path.is_file():
        raise ValueError("Stage 10 unattended progress file is missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Stage 10 unattended progress root must be an object")
    if payload.get("status") != "AWAITING_STAGE02":
        raise ValueError("Stage 10 run is not waiting for deferred Stage 02")
    if payload.get("evidence_directory") != f"stage-10/{evidence_directory.name}":
        raise ValueError("Stage 10 progress evidence directory mismatch")
    return payload


def _final_steps(
    *,
    evidence_directory: Path,
    commit: str,
    run_id: str,
) -> tuple[validation.Step, ...]:
    aggregate = evidence_directory / "stage10-discord-live-closure.json"
    return (
        validation.Step(
            "Stage 10 Discord live A/B evidence promotion",
            (
                sys.executable,
                "scripts/promote_stage10_live_evidence.py",
                "--evidence-directory",
                validation.relative_path(evidence_directory),
                "--expected-commit",
                commit,
                "--expected-run-id",
                run_id,
            ),
        ),
        validation.Step(
            "Stage 10 traceability regeneration from validated live evidence",
            (
                sys.executable,
                "scripts/generate_traceability.py",
                "--stage10-live-closure",
                validation.relative_path(aggregate),
                "--expected-commit",
                commit,
                "--expected-run-id",
                run_id,
            ),
        ),
        validation.Step(
            "Stage 10 promoted traceability documentation validation",
            (sys.executable, "scripts/validate_documentation.py"),
        ),
        validation.Step(
            "STAGE 10 requirement audit (strict closure)",
            (sys.executable, "scripts/audit_requirements.py", "--strict-closure"),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resume a Stage 10 run deferred before interactive Stage 02"
    )
    parser.add_argument("--evidence-directory", type=Path, required=True)
    arguments = parser.parse_args()

    evidence_directory = arguments.evidence_directory.resolve()
    try:
        progress = _load_progress(evidence_directory)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Cannot resume Stage 10: {exc}")
        return 2

    commit = progress.get("commit")
    run_id = progress.get("run_id")
    started_at_raw = progress.get("started_at")
    completed_results = progress.get("completed_results")
    if not isinstance(commit, str) or not isinstance(run_id, str):
        print("Cannot resume Stage 10: invalid commit/run metadata")
        return 2
    if run_id != evidence_directory.name:
        print("Cannot resume Stage 10: run id does not match evidence directory")
        return 2
    if validation.tested_commit() != commit:
        print("Cannot resume Stage 10: current HEAD differs from the qualified run commit")
        return 2
    if validation.repository_dirty():
        print("Cannot resume Stage 10 from a dirty working tree")
        return 2
    if not isinstance(started_at_raw, str) or not isinstance(completed_results, list):
        print("Cannot resume Stage 10: progress metadata is incomplete")
        return 2

    try:
        started_at = datetime.fromisoformat(started_at_raw)
        results = [validation.Result(**item) for item in completed_results]
    except (TypeError, ValueError):
        print("Cannot resume Stage 10: stored result metadata is invalid")
        return 2

    base_steps = tuple(
        step
        for step in validation.stage_10(
            evidence_directory,
            include_discord_live=False,
            profile="default",
            expected_commit=commit,
            expected_run_id=run_id,
        )
        if step.name != "STAGE 10 requirement audit (strict closure)"
    )
    automatic_live_steps = (
        _live_step(
            label="03",
            script="scripts/validate_discord_live_stage03.py",
            evidence_directory=evidence_directory,
        ),
        _live_step(
            label="04",
            script="scripts/validate_discord_live_stage04.py",
            evidence_directory=evidence_directory,
        ),
        _live_step(
            label="05",
            script="scripts/validate_discord_live_stage05.py",
            evidence_directory=evidence_directory,
        ),
        _live_step(
            label="06",
            script="scripts/validate_discord_live_stage06.py",
            evidence_directory=evidence_directory,
        ),
        _live_step(
            label="08",
            script="scripts/validate_discord_live_stage08.py",
            evidence_directory=evidence_directory,
        ),
        _live_step(
            label="09-primitives",
            script="scripts/validate_discord_live_stage09.py",
            evidence_directory=evidence_directory,
        ),
        _live_step(
            label="09-full-chain",
            script="scripts/validate_discord_live_stage09_full_chain.py",
            evidence_directory=evidence_directory,
        ),
    )
    expected_completed = len(base_steps) + len(automatic_live_steps)
    if len(results) != expected_completed or any(result.status != "PASS" for result in results):
        print("Cannot resume Stage 10: unattended phase is incomplete or non-green")
        return 2

    stage02 = _live_step(
        label="02",
        script="scripts/validate_discord_live_stage02.py",
        evidence_directory=evidence_directory,
    )
    final_steps = _final_steps(
        evidence_directory=evidence_directory,
        commit=commit,
        run_id=run_id,
    )
    continuation_steps = (stage02, *final_steps)
    for step in continuation_steps:
        result = validation.run_step(step)
        results.append(result)
        print(f"[{result.status}] {result.name} ({result.duration_seconds:.3f}s)", flush=True)
        if result.status != "PASS":
            break

    steps = (*base_steps, *automatic_live_steps, *continuation_steps)
    summary = validation.write_summary(
        stage="10",
        definition=validation.STAGES["10"],
        steps=steps,
        results=results,
        commit=commit,
        dirty=False,
        environment=validation.evidence_environment(),
        run_id=run_id,
        started_at=started_at,
        evidence_directory=evidence_directory,
        include_discord_live=True,
        profile="default",
    )
    print(
        "\nStage 10 resumed closure: "
        f"{summary['result']} — summary: "
        f"{validation.relative_path(evidence_directory / 'summary.json')}"
    )
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
