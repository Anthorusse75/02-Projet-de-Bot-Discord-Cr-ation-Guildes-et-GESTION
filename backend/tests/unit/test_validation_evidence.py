import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import validate_stage


def test_default_evidence_run_id_is_unambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DID_EVIDENCE_RUN_ID", raising=False)
    monkeypatch.setenv("DID_VALIDATION_ENVIRONMENT", "local-docker")
    started_at = datetime(2026, 8, 16, 12, 34, 56, 123456, tzinfo=UTC)

    run_id = validate_stage.evidence_run_id(commit="a" * 40, started_at=started_at)

    assert run_id == "20260816T123456123456Z-aaaaaaaaaaaa-local-docker"


def test_evidence_directory_never_overwrites_a_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(validate_stage, "EVIDENCE_ROOT", tmp_path)
    first = validate_stage.create_evidence_directory(stage="02", run_id="run-123")

    with pytest.raises(FileExistsError):
        validate_stage.create_evidence_directory(stage="02", run_id="run-123")

    assert first == tmp_path / "stage-02" / "run-123"


def test_summary_contains_policy_metadata_and_detailed_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(validate_stage, "ROOT", tmp_path)
    monkeypatch.setenv("DID_EVIDENCE_ARTIFACT_ID", "stage-02-evidence-run-123")
    evidence_directory = tmp_path / "artifacts" / "test-evidence" / "stage-02" / "run-123"
    evidence_directory.mkdir(parents=True)
    (evidence_directory / "backend-unit.xml").write_text("<testsuites />", encoding="utf-8")
    step = validate_stage.Step("unit", ("python", "-m", "pytest"), cwd=tmp_path)
    gate = validate_stage.Result("unit", "python -m pytest", ".", "PASS", 1.25, 0)
    definition = validate_stage.StageDefinition(
        steps=lambda _path, _include_live: (step,),
        requirements=("REQ-EXAMPLE-001",),
    )

    summary = validate_stage.write_summary(
        stage="02",
        definition=definition,
        steps=(step,),
        results=[gate],
        commit="b" * 40,
        dirty=False,
        environment="ci",
        run_id="run-123",
        started_at=datetime(2026, 8, 16, tzinfo=UTC),
        evidence_directory=evidence_directory,
    )

    persisted = json.loads((evidence_directory / "summary.json").read_text(encoding="utf-8"))
    assert persisted == summary
    assert str(tmp_path) not in json.dumps(summary)
    assert summary["stage"] == "02"
    assert summary["commit"] == "b" * 40
    assert summary["repository_dirty"] is False
    assert summary["environment"] == "ci"
    assert summary["result"] == "PASS"
    assert summary["requirements"] == ["REQ-EXAMPLE-001"]
    assert summary["redactions_checked"] is False
    assert summary["gates"] == [
        {
            "name": "unit",
            "command": "python -m pytest",
            "cwd": ".",
            "status": "PASS",
            "duration_seconds": 1.25,
            "return_code": 0,
        }
    ]
    assert summary["artifacts"] == [
        "artifacts/test-evidence/stage-02/run-123/summary.json",
        "artifacts/test-evidence/stage-02/run-123/backend-unit.xml",
        "github-actions-artifact:stage-02-evidence-run-123",
    ]
