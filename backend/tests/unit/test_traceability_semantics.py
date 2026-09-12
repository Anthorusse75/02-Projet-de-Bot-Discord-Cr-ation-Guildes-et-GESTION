import subprocess
import sys
from pathlib import Path
from runpy import run_path

from backend.tests.unit.stage10_live_evidence_helpers import create_valid_closure
from scripts import audit_requirements as audit
from scripts import generate_traceability


def test_stage03_traceability_does_not_promote_future_subsystems() -> None:
    root = Path(__file__).resolve().parents[3]
    namespace = run_path(str(root / "scripts/generate_traceability.py"))
    progress = namespace["STAGE03_REQUIREMENT_PROGRESS"]

    assert progress["REQ-RATE-005"][0] == "PLANNED"
    assert progress["REQ-GW-006"][0] == "PLANNED"
    assert progress["REQ-CACHE-004"][0] == "PLANNED"
    assert progress["REQ-CACHE-007"][0] == "PLANNED"
    assert progress["REQ-AUD-002"][0] == "PLANNED"
    assert progress["REQ-AUD-003"][0] == "PLANNED"
    assert progress["REQ-TEN-008"][0] == "PLANNED"

    assert progress["REQ-RATE-002"][0] == "IMPLEMENTED"
    assert progress["REQ-RATE-004"][0] == "IMPLEMENTED"
    assert progress["REQ-RATE-006"][0] == "IMPLEMENTED"
    assert len(progress) == 38


def test_req_test_003_remains_implemented_without_explicit_live_proof() -> None:
    progress = generate_traceability.requirement_progress()

    assert progress["REQ-TEST-003"][0] == "IMPLEMENTED"


def test_valid_explicit_live_proof_promotes_req_test_003_without_global_mutation(
    tmp_path: Path,
) -> None:
    _, commit, run_id, aggregate = create_valid_closure(tmp_path)

    rendered = generate_traceability.render(
        stage10_live_closure=aggregate,
        expected_commit=commit,
        expected_run_id=run_id,
    )
    rows = audit.parse_traceability_table(rendered)
    requirement = next(row for row in rows if row.req_id == "REQ-TEST-003")

    assert requirement.state == "VERIFIED"
    assert commit in requirement.evidence
    assert run_id in requirement.evidence
    assert generate_traceability.REQUIREMENT_PROGRESS["REQ-TEST-003"][0] == "IMPLEMENTED"


def test_traceability_cli_accepts_valid_explicit_live_proof(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    _, commit, run_id, aggregate = create_valid_closure(tmp_path)
    output = tmp_path / "traceability.md"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/generate_traceability.py",
            "--stage10-live-closure",
            str(aggregate),
            "--expected-commit",
            commit,
            "--expected-run-id",
            run_id,
            "--output",
            str(output),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    requirement = next(
        row
        for row in audit.parse_traceability_table(output.read_text(encoding="utf-8"))
        if row.req_id == "REQ-TEST-003"
    )
    assert requirement.state == "VERIFIED"
