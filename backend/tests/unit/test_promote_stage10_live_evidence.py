from __future__ import annotations

import json
from pathlib import Path

import pytest
from backend.tests.unit.stage10_live_evidence_helpers import (
    COMMIT,
    create_valid_closure,
    write_valid_reports,
)
from scripts import promote_stage10_live_evidence as promotion


def read_report(directory: Path, name: str) -> dict[str, object]:
    return json.loads((directory / name).read_text(encoding="utf-8"))


def write_report(directory: Path, name: str, payload: dict[str, object]) -> None:
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def test_eight_green_same_run_reports_produce_redacted_aggregate(tmp_path: Path) -> None:
    directory, commit, run_id, aggregate_path = create_valid_closure(tmp_path)

    closure = promotion.validate_aggregate_proof(
        aggregate_path,
        expected_commit=commit,
        expected_run_id=run_id,
    )
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))

    assert closure.commit == commit
    assert closure.run_id == directory.name
    assert [report.name for report in closure.reports] == list(promotion.EXPECTED_REPORTS)
    assert [report.status for report in closure.reports[:3]] == [
        "PASS_WITH_APPROVED_LIMITATION",
    ] * 3
    assert [report.status for report in closure.reports[3:6]] == ["PASS"] * 3
    assert aggregate["result"] == "PASS"
    assert aggregate["guilds_verified"] == 2
    assert aggregate["secrets_recorded"] is False
    assert aggregate["discord_identifiers_recorded"] is False
    assert str(directory.resolve()) not in aggregate_path.read_text(encoding="utf-8")


def test_missing_report_is_rejected(tmp_path: Path) -> None:
    directory, commit, run_id = write_valid_reports(tmp_path)
    (directory / "discord-live-06.json").unlink()

    with pytest.raises(promotion.PromotionError, match="missing"):
        promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)


@pytest.mark.parametrize(
    "status", ["FAIL", "BLOCKED", "SKIPPED", "SKIPPED_NOT_VERIFIED", "NOT VERIFIED"]
)
def test_non_terminally_green_status_is_rejected(tmp_path: Path, status: str) -> None:
    directory, commit, run_id = write_valid_reports(tmp_path)
    report = read_report(directory, "discord-live-05.json")
    report["status"] = status
    write_report(directory, "discord-live-05.json", report)

    with pytest.raises(promotion.PromotionError, match="status"):
        promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)


@pytest.mark.parametrize(
    "report_name",
    [
        "discord-live-03.json",
        "discord-live-05.json",
        "discord-live-06.json",
    ],
)
def test_approved_limitations_are_exact(tmp_path: Path, report_name: str) -> None:
    directory, commit, run_id = write_valid_reports(tmp_path)
    report = read_report(directory, report_name)
    skipped = report["skipped_not_verified"]
    assert isinstance(skipped, list)
    skipped.append("new unapproved limitation")
    write_report(directory, report_name, report)

    with pytest.raises(promotion.PromotionError, match="limitation"):
        promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)


def test_stage05_and_stage06_keep_pass_status_with_exact_approved_limitations(
    tmp_path: Path,
) -> None:
    directory, commit, run_id = write_valid_reports(tmp_path)

    stage05 = read_report(directory, "discord-live-05.json")
    stage06 = read_report(directory, "discord-live-06.json")

    assert stage05["status"] == "PASS"
    assert set(stage05["skipped_not_verified"]) == promotion.APPROVED_LIMITATIONS["05"]
    assert stage06["status"] == "PASS"
    assert set(stage06["skipped_not_verified"]) == promotion.APPROVED_LIMITATIONS["06"]

    promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)


def test_clean_sandbox_hygiene_counters_may_be_zero(tmp_path: Path) -> None:
    directory, commit, run_id = write_valid_reports(tmp_path)

    stage05 = read_report(directory, "discord-live-05.json")
    stage05_counts = stage05["counts"]
    assert isinstance(stage05_counts, dict)
    for field in (
        "abandoned_fixture_jobs_resumed",
        "terminal_fixture_jobs_acknowledged",
        "preexisting_fixtures_cleaned",
    ):
        stage05_counts[field] = 0
    write_report(directory, "discord-live-05.json", stage05)

    stage06 = read_report(directory, "discord-live-06.json")
    stage06_counts = stage06["counts"]
    assert isinstance(stage06_counts, dict)
    stage06_counts["resumed_portability_jobs"] = 0
    write_report(directory, "discord-live-06.json", stage06)

    promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)


@pytest.mark.parametrize(
    ("report_name", "field"),
    [
        ("discord-live-05.json", "abandoned_fixture_jobs_resumed"),
        ("discord-live-05.json", "terminal_fixture_jobs_acknowledged"),
        ("discord-live-05.json", "preexisting_fixtures_cleaned"),
        ("discord-live-06.json", "resumed_portability_jobs"),
    ],
)
def test_hygiene_counters_reject_negative_values(
    tmp_path: Path,
    report_name: str,
    field: str,
) -> None:
    directory, commit, run_id = write_valid_reports(tmp_path)
    report = read_report(directory, report_name)
    counts = report["counts"]
    assert isinstance(counts, dict)
    counts[field] = -1
    write_report(directory, report_name, report)

    with pytest.raises(promotion.PromotionError, match="negative Stage"):
        promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)


@pytest.mark.parametrize(
    ("report_name", "field"),
    [
        ("discord-live-05.json", "plans_succeeded"),
        ("discord-live-06.json", "source_fixture_resources"),
    ],
)
def test_required_stage05_stage06_proof_counters_still_require_positive_values(
    tmp_path: Path,
    report_name: str,
    field: str,
) -> None:
    directory, commit, run_id = write_valid_reports(tmp_path)
    report = read_report(directory, report_name)
    counts = report["counts"]
    assert isinstance(counts, dict)
    counts[field] = 0
    write_report(directory, report_name, report)

    with pytest.raises(promotion.PromotionError, match="non-positive"):
        promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)


def test_recorded_secret_is_rejected(tmp_path: Path) -> None:
    directory, commit, run_id = write_valid_reports(tmp_path)
    report = read_report(directory, "discord-live-03.json")
    report["secrets_recorded"] = True
    write_report(directory, "discord-live-03.json", report)

    with pytest.raises(promotion.PromotionError, match="privacy"):
        promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)


def test_recorded_discord_identifiers_are_rejected(tmp_path: Path) -> None:
    directory, commit, run_id = write_valid_reports(tmp_path)
    report = read_report(directory, "discord-live-08.json")
    report["discord_identifiers_recorded"] = True
    write_report(directory, "discord-live-08.json", report)

    with pytest.raises(promotion.PromotionError, match="identifier assertion"):
        promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)


def test_raw_discord_identifier_is_rejected_even_with_false_flag(tmp_path: Path) -> None:
    directory, commit, run_id = write_valid_reports(tmp_path)
    report = read_report(directory, "discord-live-08.json")
    report["unexpected"] = "123456789012345678"
    write_report(directory, "discord-live-08.json", report)

    with pytest.raises(promotion.PromotionError, match="raw Discord identifier"):
        promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)


def test_invalid_json_is_rejected(tmp_path: Path) -> None:
    directory, commit, run_id = write_valid_reports(tmp_path)
    (directory / "discord-live-04.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(promotion.PromotionError, match="invalid JSON"):
        promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)


@pytest.mark.parametrize(
    ("field", "value"),
    [("stage", "04"), ("profile", "discord-live-unexpected")],
)
def test_unexpected_stage_or_profile_is_rejected(tmp_path: Path, field: str, value: str) -> None:
    directory, commit, run_id = write_valid_reports(tmp_path)
    report = read_report(directory, "discord-live-03.json")
    report[field] = value
    write_report(directory, "discord-live-03.json", report)

    with pytest.raises(promotion.PromotionError, match=f"unexpected {field}"):
        promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)


def test_wrong_commit_or_run_is_rejected_when_encoded_in_run_id(tmp_path: Path) -> None:
    directory, _, run_id = write_valid_reports(tmp_path)

    with pytest.raises(promotion.PromotionError, match="commit prefix"):
        promotion.promote(directory, expected_commit="b" * 40, expected_run_id=run_id)
    with pytest.raises(promotion.PromotionError, match="run id"):
        promotion.promote(
            directory,
            expected_commit=COMMIT,
            expected_run_id=f"20200101T000000000000Z-{COMMIT[:12]}-other",
        )


def test_old_bundle_outside_requested_directory_is_never_selected(tmp_path: Path) -> None:
    old_parent = tmp_path / "old"
    current_parent = tmp_path / "current"
    old_parent.mkdir()
    current_parent.mkdir()
    create_valid_closure(old_parent)
    directory, commit, run_id = write_valid_reports(
        current_parent,
        run_id=f"20200101T000000000000Z-{COMMIT[:12]}-current",
    )
    (directory / "discord-live-02.json").unlink()

    with pytest.raises(promotion.PromotionError, match="missing"):
        promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)


def test_incomplete_full_chain_is_rejected(tmp_path: Path) -> None:
    directory, commit, run_id = write_valid_reports(tmp_path)
    report = read_report(directory, "discord-live-09-full-chain.json")
    scenarios = report["scenarios"]
    assert isinstance(scenarios, dict)
    scenarios.pop(next(iter(scenarios)))
    write_report(directory, "discord-live-09-full-chain.json", report)

    with pytest.raises(promotion.PromotionError, match="incomplete"):
        promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)


def test_corrupt_aggregate_or_changed_source_report_is_rejected(tmp_path: Path) -> None:
    directory, commit, run_id, aggregate_path = create_valid_closure(tmp_path)
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["reports"][0]["sha256"] = "0" * 64
    aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")

    with pytest.raises(promotion.PromotionError, match="corrupt"):
        promotion.validate_aggregate_proof(
            aggregate_path,
            expected_commit=commit,
            expected_run_id=run_id,
        )

    promotion.promote(directory, expected_commit=commit, expected_run_id=run_id)
    report = read_report(directory, "discord-live-02.json")
    report["status"] = "FAIL"
    write_report(directory, "discord-live-02.json", report)
    with pytest.raises(promotion.PromotionError, match="status"):
        promotion.validate_aggregate_proof(
            aggregate_path,
            expected_commit=commit,
            expected_run_id=run_id,
        )
