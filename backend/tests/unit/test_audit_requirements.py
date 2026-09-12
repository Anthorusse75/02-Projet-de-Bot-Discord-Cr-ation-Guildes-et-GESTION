from __future__ import annotations

import json

import pytest
from scripts import audit_requirements as audit

SPEC_HEADER = "# Some preamble\n\n# 53. Registre normatif des exigences\n\n"


def make_spec(*lines: str) -> str:
    return SPEC_HEADER + "\n".join(lines) + "\n"


def make_trace_row(
    req_id: str,
    modality: str = "MUST",
    state: str = "IMPLEMENTED",
    evidence: str = "some real evidence text",
    summary: str = "summary",
) -> str:
    return (
        f"| {req_id} | {summary} | {modality} | 10 | 09, 10 | "
        f"unit + integration | {state} | {evidence} |"
    )


def make_trace(*rows: str) -> str:
    header = (
        "# Traçabilité des exigences\n\n"
        "| REQ ID | Résumé normatif | Modalité | Étape principale | "
        "Étapes secondaires | Tests attendus | État | Preuve/test/commit |\n"
        "|---|---|---|---:|---|---|---|---|\n"
    )
    return header + "\n".join(rows) + "\n"


class TestParseSourceRegistry:
    def test_extracts_id_modality_and_summary(self) -> None:
        spec = make_spec(
            "- **REQ-FOO-001 — MUST** : does the foo thing.",
            "- **REQ-FOO-002 — SHOULD** : does the bar thing.",
        )

        requirements = audit.parse_source_registry(spec)

        assert [r.req_id for r in requirements] == ["REQ-FOO-001", "REQ-FOO-002"]
        assert requirements[0].modality == "MUST"
        assert requirements[0].summary == "does the foo thing."
        assert requirements[1].modality == "SHOULD"

    def test_ignores_lines_before_registry_heading(self) -> None:
        spec = "- **REQ-BEFORE-001 — MUST** : should not be picked up.\n" + make_spec(
            "- **REQ-FOO-001 — MUST** : real requirement."
        )

        requirements = audit.parse_source_registry(spec)

        assert [r.req_id for r in requirements] == ["REQ-FOO-001"]

    def test_missing_heading_raises(self) -> None:
        with pytest.raises(ValueError, match="registry heading not found"):
            audit.parse_source_registry("no registry heading here")


class TestParseTraceabilityTable:
    def test_extracts_all_columns(self) -> None:
        text = make_trace(make_trace_row("REQ-FOO-001", state="VERIFIED", evidence="proof text"))

        rows = audit.parse_traceability_table(text)

        assert len(rows) == 1
        row = rows[0]
        assert row.req_id == "REQ-FOO-001"
        assert row.modality == "MUST"
        assert row.state == "VERIFIED"
        assert row.evidence == "proof text"

    def test_ignores_header_and_separator_rows(self) -> None:
        text = make_trace(make_trace_row("REQ-FOO-001"))

        rows = audit.parse_traceability_table(text)

        assert [r.req_id for r in rows] == ["REQ-FOO-001"]

    def test_unescapes_escaped_pipes_in_cells(self) -> None:
        row = make_trace_row("REQ-FOO-001", evidence="A \\| B token preserved")
        text = make_trace(row)

        rows = audit.parse_traceability_table(text)

        assert rows[0].evidence == "A | B token preserved"

    def test_malformed_row_raises(self) -> None:
        text = make_trace("| REQ-FOO-001 | only two columns |")

        with pytest.raises(ValueError, match="malformed traceability row"):
            audit.parse_traceability_table(text)


class TestStructuralIntegrity:
    def test_duplicate_source_ids_detected(self) -> None:
        source = [
            audit.SourceRequirement("REQ-FOO-001", "MUST", "a"),
            audit.SourceRequirement("REQ-FOO-001", "MUST", "a again"),
        ]
        trace = [
            audit.TraceRow("REQ-FOO-001", "a", "MUST", "10", "10", "t", "IMPLEMENTED", "e"),
        ]

        report = audit.build_report(source, trace)

        assert report.duplicate_source_ids == ("REQ-FOO-001",)
        assert any("duplicate source" in e for e in report.structural_errors)

    def test_duplicate_traceability_ids_detected(self) -> None:
        source = [audit.SourceRequirement("REQ-FOO-001", "MUST", "a")]
        trace = [
            audit.TraceRow("REQ-FOO-001", "a", "MUST", "10", "10", "t", "IMPLEMENTED", "e"),
            audit.TraceRow("REQ-FOO-001", "a", "MUST", "10", "10", "t", "IMPLEMENTED", "e"),
        ]

        report = audit.build_report(source, trace)

        assert report.duplicate_trace_ids == ("REQ-FOO-001",)
        assert any("duplicate traceability" in e for e in report.structural_errors)

    def test_missing_source_requirement_detected(self) -> None:
        source = [
            audit.SourceRequirement("REQ-FOO-001", "MUST", "a"),
            audit.SourceRequirement("REQ-FOO-002", "MUST", "b"),
        ]
        trace = [
            audit.TraceRow("REQ-FOO-001", "a", "MUST", "10", "10", "t", "IMPLEMENTED", "e"),
        ]

        report = audit.build_report(source, trace)

        assert report.missing_from_traceability == ("REQ-FOO-002",)
        assert any("missing from traceability" in e for e in report.structural_errors)

    def test_unknown_traceability_requirement_detected(self) -> None:
        source = [audit.SourceRequirement("REQ-FOO-001", "MUST", "a")]
        trace = [
            audit.TraceRow("REQ-FOO-001", "a", "MUST", "10", "10", "t", "IMPLEMENTED", "e"),
            audit.TraceRow("REQ-GHOST-001", "x", "MUST", "10", "10", "t", "IMPLEMENTED", "e"),
        ]

        report = audit.build_report(source, trace)

        assert report.unknown_in_traceability == ("REQ-GHOST-001",)
        assert any("unknown requirements" in e for e in report.structural_errors)

    def test_modality_mismatch_detected(self) -> None:
        source = [audit.SourceRequirement("REQ-FOO-001", "MUST", "a")]
        trace = [
            audit.TraceRow("REQ-FOO-001", "a", "SHOULD", "10", "10", "t", "IMPLEMENTED", "e"),
        ]

        report = audit.build_report(source, trace)

        assert report.modality_mismatches == (("REQ-FOO-001", "MUST", "SHOULD"),)
        assert any("modality mismatch" in e for e in report.structural_errors)

    def test_clean_input_has_no_structural_errors(self) -> None:
        source = [
            audit.SourceRequirement("REQ-FOO-001", "MUST", "a"),
            audit.SourceRequirement("REQ-FOO-002", "SHOULD", "b"),
        ]
        trace = [
            audit.TraceRow("REQ-FOO-001", "a", "MUST", "10", "10", "t", "IMPLEMENTED", "e"),
            audit.TraceRow("REQ-FOO-002", "b", "SHOULD", "10", "10", "t", "IMPLEMENTED", "e"),
        ]

        report = audit.build_report(source, trace)

        assert report.structural_errors == ()


class TestClosureSemantics:
    def test_must_verified_with_evidence_is_closed(self) -> None:
        row = audit.TraceRow("REQ-X-001", "s", "MUST", "10", "10", "t", "VERIFIED", "real proof")

        closed, reason = audit.closure_status(row)

        assert closed is True
        assert "VERIFIED" in reason

    def test_must_verified_with_placeholder_evidence_is_not_closed(self) -> None:
        row = audit.TraceRow(
            "REQ-X-001", "s", "MUST", "10", "10", "t", "VERIFIED", "À renseigner lors de l'étape"
        )

        closed, reason = audit.closure_status(row)

        assert closed is False
        assert "placeholder" in reason

    def test_must_verified_with_empty_evidence_is_not_closed(self) -> None:
        row = audit.TraceRow("REQ-X-001", "s", "MUST", "10", "10", "t", "VERIFIED", "")

        closed, _ = audit.closure_status(row)

        assert closed is False

    def test_must_implemented_but_not_verified_is_not_closed(self) -> None:
        row = audit.TraceRow(
            "REQ-X-001", "s", "MUST", "10", "10", "t", "IMPLEMENTED", "real work done"
        )

        closed, reason = audit.closure_status(row)

        assert closed is False
        assert "MUST is not VERIFIED" in reason

    def test_must_planned_is_not_closed(self) -> None:
        row = audit.TraceRow("REQ-X-001", "s", "MUST", "10", "10", "t", "PLANNED", "not started")

        closed, _ = audit.closure_status(row)

        assert closed is False

    def test_should_implemented_without_deviation_is_not_closed(self) -> None:
        row = audit.TraceRow(
            "REQ-X-001", "s", "SHOULD", "10", "10", "t", "IMPLEMENTED", "real work done"
        )

        closed, reason = audit.closure_status(row)

        assert closed is False
        assert "SHOULD is not VERIFIED" in reason

    def test_should_with_documented_deviation_is_closed(self) -> None:
        row = audit.TraceRow(
            "REQ-X-001",
            "s",
            "SHOULD",
            "10",
            "10",
            "t",
            "IMPLEMENTED",
            "DEVIATION APPROVED: intentionally not pursued because X; see IMP-020",
        )

        closed, reason = audit.closure_status(row)

        assert closed is True
        assert "deviation" in reason

    def test_should_with_deviation_marker_case_insensitive(self) -> None:
        row = audit.TraceRow(
            "REQ-X-001", "s", "SHOULD", "10", "10", "t", "IMPLEMENTED", "deviation approved: ok"
        )

        closed, _ = audit.closure_status(row)

        assert closed is True

    def test_must_is_never_closed_by_deviation_marker(self) -> None:
        row = audit.TraceRow(
            "REQ-X-001",
            "s",
            "MUST",
            "10",
            "10",
            "t",
            "IMPLEMENTED",
            "DEVIATION APPROVED: not doing this",
        )

        closed, reason = audit.closure_status(row)

        assert closed is False
        assert "MUST is not VERIFIED" in reason

    def test_may_is_always_closed(self) -> None:
        row = audit.TraceRow("REQ-X-001", "s", "MAY", "10", "10", "t", "PLANNED", "")

        closed, reason = audit.closure_status(row)

        assert closed is True
        assert "MAY" in reason


class TestStrictClosure:
    def _report(self, rows: list[audit.TraceRow]) -> audit.AuditReport:
        source = [audit.SourceRequirement(r.req_id, r.modality, r.summary) for r in rows]
        return audit.build_report(source, rows)

    def test_strict_closure_fails_while_must_is_planned(self) -> None:
        report = self._report(
            [audit.TraceRow("REQ-X-001", "s", "MUST", "10", "10", "t", "PLANNED", "x")]
        )

        must_not_closed, should_not_closed = audit.strict_failures(report)

        assert len(must_not_closed) == 1
        assert should_not_closed == []

    def test_strict_closure_fails_while_must_is_implemented_not_verified(self) -> None:
        report = self._report(
            [audit.TraceRow("REQ-X-001", "s", "MUST", "10", "10", "t", "IMPLEMENTED", "x")]
        )

        must_not_closed, _ = audit.strict_failures(report)

        assert len(must_not_closed) == 1

    def test_strict_closure_passes_when_all_must_verified_and_should_closed(self) -> None:
        report = self._report(
            [
                audit.TraceRow("REQ-X-001", "s", "MUST", "10", "10", "t", "VERIFIED", "proof"),
                audit.TraceRow(
                    "REQ-X-002",
                    "s",
                    "SHOULD",
                    "10",
                    "10",
                    "t",
                    "IMPLEMENTED",
                    "DEVIATION APPROVED: rationale",
                ),
            ]
        )

        must_not_closed, should_not_closed = audit.strict_failures(report)

        assert must_not_closed == []
        assert should_not_closed == []


class TestMainCli:
    def _write(self, tmp_path, spec_lines: list[str], trace_rows: list[str]):
        spec_path = tmp_path / "spec.md"
        trace_path = tmp_path / "trace.md"
        spec_path.write_text(make_spec(*spec_lines), encoding="utf-8")
        trace_path.write_text(make_trace(*trace_rows), encoding="utf-8")
        return spec_path, trace_path

    def test_normal_mode_exits_zero_even_with_planned_requirements(self, tmp_path) -> None:
        spec_path, trace_path = self._write(
            tmp_path,
            ["- **REQ-X-001 — MUST** : do the thing."],
            [make_trace_row("REQ-X-001", state="PLANNED", evidence="not started")],
        )

        exit_code = audit.main(["--spec", str(spec_path), "--traceability", str(trace_path)])

        assert exit_code == 0

    def test_strict_closure_exits_nonzero_with_planned_must(self, tmp_path) -> None:
        spec_path, trace_path = self._write(
            tmp_path,
            ["- **REQ-X-001 — MUST** : do the thing."],
            [make_trace_row("REQ-X-001", state="PLANNED", evidence="not started")],
        )

        exit_code = audit.main(
            [
                "--spec",
                str(spec_path),
                "--traceability",
                str(trace_path),
                "--strict-closure",
            ]
        )

        assert exit_code == 1

    def test_strict_closure_exits_zero_when_fully_verified(self, tmp_path) -> None:
        spec_path, trace_path = self._write(
            tmp_path,
            ["- **REQ-X-001 — MUST** : do the thing."],
            [make_trace_row("REQ-X-001", state="VERIFIED", evidence="real proof of the thing")],
        )

        exit_code = audit.main(
            [
                "--spec",
                str(spec_path),
                "--traceability",
                str(trace_path),
                "--strict-closure",
            ]
        )

        assert exit_code == 0

    def test_structural_error_exits_nonzero_even_in_normal_mode(self, tmp_path) -> None:
        spec_path, trace_path = self._write(
            tmp_path,
            ["- **REQ-X-001 — MUST** : do the thing."],
            [
                make_trace_row("REQ-X-001", state="IMPLEMENTED"),
                make_trace_row("REQ-GHOST-001", state="IMPLEMENTED"),
            ],
        )

        exit_code = audit.main(["--spec", str(spec_path), "--traceability", str(trace_path)])

        assert exit_code == 1

    def test_json_output_is_valid_and_matches_text_result(self, tmp_path, capsys) -> None:
        spec_path, trace_path = self._write(
            tmp_path,
            ["- **REQ-X-001 — MUST** : do the thing."],
            [make_trace_row("REQ-X-001", state="PLANNED", evidence="not started")],
        )

        exit_code = audit.main(
            [
                "--spec",
                str(spec_path),
                "--traceability",
                str(trace_path),
                "--strict-closure",
                "--json",
            ]
        )

        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 1
        assert payload["strict_closure"]["result"] == "FAIL"
        assert len(payload["strict_closure"]["must_not_closed"]) == 1
        assert payload["total_source"] == 1
        assert payload["total_traced"] == 1


class TestAgainstRepositoryDocuments:
    """Guards the real registry/traceability pair stay parseable and structurally sound."""

    def test_repository_registry_and_traceability_are_structurally_consistent(self) -> None:
        source_text = audit.SPEC.read_text(encoding="utf-8-sig")
        trace_text = audit.TRACE.read_text(encoding="utf-8-sig")

        source = audit.parse_source_registry(source_text)
        trace = audit.parse_traceability_table(trace_text)
        report = audit.build_report(source, trace)

        assert report.structural_errors == ()
        assert report.total_source == report.total_traced
        assert report.total_source > 0

    def test_stage10_closure_state_is_complete_except_current_live_blocker(self) -> None:
        source = audit.parse_source_registry(audit.SPEC.read_text(encoding="utf-8-sig"))
        trace = audit.parse_traceability_table(audit.TRACE.read_text(encoding="utf-8-sig"))
        report = audit.build_report(source, trace)

        must_not_closed, should_not_closed = audit.strict_failures(report)
        assert [item.req_id for item in must_not_closed] == ["REQ-TEST-003"]
        assert should_not_closed == []
        assert report.counts_by_state == {"VERIFIED": 244, "IMPLEMENTED": 2}
        bot_map = next(item for item in report.audits if item.req_id == "REQ-BOT-005")
        assert bot_map.closed is True
        assert "DEVIATION APPROVED" in bot_map.evidence
