from __future__ import annotations

import sys
from datetime import UTC, datetime

import validate_stage as validation


def _live_step(*, label: str, script: str, evidence_directory, timeout: int = 3600):
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


def main() -> int:
    started_at = datetime.now(UTC)
    commit = validation.tested_commit()
    dirty = validation.repository_dirty()
    environment = validation.evidence_environment()
    run_id = validation.evidence_run_id(commit=commit, started_at=started_at)
    try:
        evidence_directory = validation.create_evidence_directory(stage="10", run_id=run_id)
    except FileExistsError:
        print(f"Evidence run already exists and will not be overwritten: stage-10/{run_id}")
        return 2

    # Run the canonical Stage 10 non-live work, but deliberately defer strict
    # closure until the live matrix has been promoted.
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

    # The live stages that depend on the bot retaining its current sandbox
    # capabilities run BEFORE destructive Stage 02. Stage 02 is intentionally
    # deferred until the operator is back, so its uninstall/reinstall cannot
    # break later live qualification stages.
    automatic_live_steps = (
        _live_step(label="03", script="scripts/validate_discord_live_stage03.py", evidence_directory=evidence_directory),
        _live_step(label="04", script="scripts/validate_discord_live_stage04.py", evidence_directory=evidence_directory),
        _live_step(label="05", script="scripts/validate_discord_live_stage05.py", evidence_directory=evidence_directory),
        _live_step(label="06", script="scripts/validate_discord_live_stage06.py", evidence_directory=evidence_directory),
        _live_step(label="08", script="scripts/validate_discord_live_stage08.py", evidence_directory=evidence_directory),
        _live_step(label="09-primitives", script="scripts/validate_discord_live_stage09.py", evidence_directory=evidence_directory),
        _live_step(label="09-full-chain", script="scripts/validate_discord_live_stage09_full_chain.py", evidence_directory=evidence_directory),
    )

    manual_stage02 = _live_step(
        label="02",
        script="scripts/validate_discord_live_stage02.py",
        evidence_directory=evidence_directory,
        timeout=3600,
    )

    aggregate = evidence_directory / "stage10-discord-live-closure.json"
    final_steps = (
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

    steps = base_steps + automatic_live_steps + (manual_stage02,) + final_steps
    results: list[validation.Result] = []

    for step in base_steps + automatic_live_steps:
        result = validation.run_step(step)
        results.append(result)
        print(f"[{result.status}] {result.name} ({result.duration_seconds:.3f}s)", flush=True)
        if result.status != "PASS":
            break

    if len(results) == len(base_steps) + len(automatic_live_steps) and all(
        result.status == "PASS" for result in results
    ):
        print("\n" + "=" * 78)
        print("AUTOMATIC PHASE COMPLETE — YOU CAN BE AWAY AS LONG AS NEEDED")
        print("All long/non-interactive Stage 10 work and live Stages 03/04/05/06/08/09 are done.")
        print("When you are back at the computer, press ENTER to start the only interactive Stage 02.")
        print("The process waits here indefinitely; there is no Stage 02 timeout while you are away.")
        print("=" * 78, flush=True)
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            print("Interactive Stage 02 was not started; existing evidence is preserved.")
            return 130

        for step in (manual_stage02,) + final_steps:
            result = validation.run_step(step)
            results.append(result)
            print(f"[{result.status}] {result.name} ({result.duration_seconds:.3f}s)", flush=True)
            if result.status != "PASS":
                break

    summary = validation.write_summary(
        stage="10",
        definition=validation.STAGES["10"],
        steps=steps,
        results=results,
        commit=commit,
        dirty=dirty,
        environment=environment,
        run_id=run_id,
        started_at=started_at,
        evidence_directory=evidence_directory,
        include_discord_live=True,
        profile="default",
    )
    summary_path = validation.relative_path(evidence_directory / "summary.json")
    print(f"\nStage 10 deferred-interactive run: {summary['result']} — summary: {summary_path}")
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
