from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import validate_stage as validation


def _live_step(
    *,
    label: str,
    script: str,
    evidence_directory: Path,
    timeout: int = 3600,
) -> validation.Step:
    uv = validation.executable("uv")
    return validation.Step(
        f"Stage 10 Discord live A/B matrix — Stage {label}",
        (
            uv,
            "run",
            "python",
            script,
            "--include",
            "--report",
            validation.relative_path(evidence_directory / f"discord-live-{label}.json"),
        ),
        timeout,
        environment={**validation.TEST_ENV, "DID_RUN_INTEGRATION": "1"},
    )


def _write_progress(
    *,
    evidence_directory: Path,
    commit: str,
    run_id: str,
    started_at: datetime,
    status: str,
    results: list[validation.Result],
) -> Path:
    path = evidence_directory / "stage10-unattended-progress.json"
    payload = {
        "schema_version": 1,
        "status": status,
        "commit": commit,
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(),
        "evidence_directory": f"stage-10/{run_id}",
        "completed_results": [asdict(result) for result in results],
        "next_action": (
            "Run interactive Stage 02 later against this exact evidence directory, "
            "then promote the eight-report live closure."
        ),
        "secrets_recorded": False,
        "discord_identifiers_recorded": False,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    started_at = datetime.now(UTC)
    commit = validation.tested_commit()
    dirty = validation.repository_dirty()
    if dirty:
        print("Refusing unattended Stage 10 from a dirty working tree.")
        return 2

    environment = validation.evidence_environment()
    del environment
    run_id = validation.evidence_run_id(commit=commit, started_at=started_at)
    try:
        evidence_directory = validation.create_evidence_directory(stage="10", run_id=run_id)
    except FileExistsError:
        print(f"Evidence run already exists and will not be overwritten: stage-10/{run_id}")
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

    steps = (*base_steps, *automatic_live_steps)
    results: list[validation.Result] = []
    for step in steps:
        result = validation.run_step(step)
        results.append(result)
        print(f"[{result.status}] {result.name} ({result.duration_seconds:.3f}s)", flush=True)
        if result.status != "PASS":
            progress = _write_progress(
                evidence_directory=evidence_directory,
                commit=commit,
                run_id=run_id,
                started_at=started_at,
                status="FAILED_BEFORE_STAGE02",
                results=results,
            )
            print(
                "\nStage 10 unattended phase: FAIL — progress: "
                f"{validation.relative_path(progress)}"
            )
            return 1

    progress = _write_progress(
        evidence_directory=evidence_directory,
        commit=commit,
        run_id=run_id,
        started_at=started_at,
        status="AWAITING_STAGE02",
        results=results,
    )
    evidence_path = validation.relative_path(evidence_directory)
    print("\n" + "=" * 78)
    print("UNATTENDED PHASE COMPLETE")
    print("All long work and live Stages 03/04/05/06/08/09 completed successfully.")
    print("Interactive Stage 02 was deliberately NOT started and can be done later.")
    print(f"Preserved evidence directory: {evidence_path}")
    print(f"Progress file: {validation.relative_path(progress)}")
    print("You can safely leave the computer unattended; this process is finished.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
