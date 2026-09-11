#!/usr/bin/env python3
"""Audit the requirements registry against the generated traceability table.

Two independent sources are compared:

- the normative source registry (`# 53. Registre normatif des exigences` in
  `docs/00_reference/01_SPECIFICATIONS_FONCTIONNELLES_DISCORD_INFRA_DESIGNER.md`);
- the generated traceability table (`docs/10_implementation/
  00_REQUIREMENTS_TRACEABILITY.md`, produced by `scripts/generate_traceability.py`).

Normal mode (default) is informational: it reports structure, counts and every
non-VERIFIED/PLANNED requirement without failing the run. `--strict-closure`
is the gate used for final Stage 10 acceptance: every MUST must be VERIFIED
with non-placeholder evidence, and every SHOULD must be either VERIFIED or
carry an explicit documented deviation (evidence text containing the literal
marker `DEVIATION APPROVED`, followed by the rationale). Structural defects
(duplicate/missing/unknown IDs, modality mismatches) fail in both modes,
since they are integrity bugs rather than closure gaps.

This script never edits the traceability table and never assigns VERIFIED
state to a requirement — it only reports what the current committed table
says.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/00_reference/01_SPECIFICATIONS_FONCTIONNELLES_DISCORD_INFRA_DESIGNER.md"
TRACE = ROOT / "docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md"

REGISTRY_HEADING = "# 53. Registre normatif des exigences"
REQ_LINE = re.compile(r"^- \*\*(REQ-[A-Z0-9-]+) — (MUST|SHOULD|MAY)\*\* : (.+)$")
TRACE_ROW_START = re.compile(r"^\| (REQ-[A-Z0-9-]+) \|")
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
DEVIATION_MARKER = "DEVIATION APPROVED"
TRACE_COLUMN_COUNT = 8
PLACEHOLDER_PREFIXES = ("à renseigner", "a renseigner", "tbd", "todo", "n/a")


@dataclass(frozen=True, slots=True)
class SourceRequirement:
    req_id: str
    modality: str
    summary: str


@dataclass(frozen=True, slots=True)
class TraceRow:
    req_id: str
    summary: str
    modality: str
    primary_stage: str
    secondary_stages: str
    tests: str
    state: str
    evidence: str


@dataclass(frozen=True, slots=True)
class RequirementAudit:
    req_id: str
    modality: str
    state: str
    evidence: str
    closed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class AuditReport:
    total_source: int
    total_traced: int
    duplicate_source_ids: tuple[str, ...]
    duplicate_trace_ids: tuple[str, ...]
    missing_from_traceability: tuple[str, ...]
    unknown_in_traceability: tuple[str, ...]
    modality_mismatches: tuple[tuple[str, str, str], ...]
    counts_by_modality: dict[str, int]
    counts_by_state: dict[str, int]
    audits: tuple[RequirementAudit, ...]
    structural_errors: tuple[str, ...]


def unescape_cell(value: str) -> str:
    return value.replace("\\|", "|").strip()


def parse_source_registry(text: str) -> list[SourceRequirement]:
    if REGISTRY_HEADING not in text:
        raise ValueError(f"source registry heading not found: {REGISTRY_HEADING!r}")
    _, _, registry = text.partition(REGISTRY_HEADING)
    requirements: list[SourceRequirement] = []
    for line in registry.splitlines():
        match = REQ_LINE.match(line)
        if match:
            req_id, modality, summary = match.groups()
            requirements.append(SourceRequirement(req_id, modality, summary.strip()))
    return requirements


def parse_traceability_table(text: str) -> list[TraceRow]:
    rows: list[TraceRow] = []
    for line in text.splitlines():
        if not TRACE_ROW_START.match(line):
            continue
        parts = UNESCAPED_PIPE.split(line)
        cells = [unescape_cell(part) for part in parts[1:-1]]
        if len(cells) != TRACE_COLUMN_COUNT:
            raise ValueError(
                f"malformed traceability row: expected {TRACE_COLUMN_COUNT} columns, "
                f"got {len(cells)}: {line!r}"
            )
        req_id, summary, modality, primary_stage, secondary_stages, tests, state, evidence = cells
        rows.append(
            TraceRow(
                req_id=req_id,
                summary=summary,
                modality=modality,
                primary_stage=primary_stage,
                secondary_stages=secondary_stages,
                tests=tests,
                state=state,
                evidence=evidence,
            )
        )
    return rows


def find_duplicates(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for req_id in ids:
        if req_id in seen:
            duplicates.add(req_id)
        seen.add(req_id)
    return sorted(duplicates)


def is_placeholder_evidence(text: str) -> bool:
    normalized = text.strip().casefold()
    if not normalized:
        return True
    return any(normalized.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def has_documented_deviation(evidence: str) -> bool:
    return DEVIATION_MARKER in evidence.upper()


def closure_status(row: TraceRow) -> tuple[bool, str]:
    state = row.state.strip().upper()
    if state == "VERIFIED":
        if is_placeholder_evidence(row.evidence):
            return False, "state is VERIFIED but evidence is empty or a placeholder"
        return True, "VERIFIED with concrete evidence"
    if row.modality == "SHOULD" and has_documented_deviation(row.evidence):
        return True, "SHOULD with a documented deviation (DEVIATION APPROVED marker)"
    if row.modality == "MAY":
        return True, "MAY — closure is not mandatory"
    return False, f"{row.modality} is not VERIFIED (state={row.state or 'MISSING'})"


def build_report(source: list[SourceRequirement], trace: list[TraceRow]) -> AuditReport:
    source_ids = [item.req_id for item in source]
    trace_ids = [item.req_id for item in trace]
    duplicate_source_ids = tuple(find_duplicates(source_ids))
    duplicate_trace_ids = tuple(find_duplicates(trace_ids))

    source_by_id = {item.req_id: item for item in source}
    trace_by_id = {item.req_id: item for item in trace}

    missing_from_traceability = tuple(sorted(set(source_by_id) - set(trace_by_id)))
    unknown_in_traceability = tuple(sorted(set(trace_by_id) - set(source_by_id)))

    modality_mismatches = tuple(
        (req_id, source_by_id[req_id].modality, trace_by_id[req_id].modality)
        for req_id in sorted(set(source_by_id) & set(trace_by_id))
        if source_by_id[req_id].modality != trace_by_id[req_id].modality
    )

    counts_by_modality: dict[str, int] = {}
    counts_by_state: dict[str, int] = {}
    audits: list[RequirementAudit] = []
    for row in trace:
        counts_by_modality[row.modality] = counts_by_modality.get(row.modality, 0) + 1
        counts_by_state[row.state] = counts_by_state.get(row.state, 0) + 1
        closed, reason = closure_status(row)
        audits.append(
            RequirementAudit(
                req_id=row.req_id,
                modality=row.modality,
                state=row.state,
                evidence=row.evidence,
                closed=closed,
                reason=reason,
            )
        )

    structural_errors: list[str] = []
    if duplicate_source_ids:
        structural_errors.append(
            f"duplicate source requirement IDs: {', '.join(duplicate_source_ids)}"
        )
    if duplicate_trace_ids:
        structural_errors.append(
            f"duplicate traceability requirement IDs: {', '.join(duplicate_trace_ids)}"
        )
    if missing_from_traceability:
        structural_errors.append(
            f"source requirements missing from traceability: {', '.join(missing_from_traceability)}"
        )
    if unknown_in_traceability:
        structural_errors.append(
            "unknown requirements in traceability (absent from the source registry): "
            f"{', '.join(unknown_in_traceability)}"
        )
    if modality_mismatches:
        structural_errors.append(
            "modality mismatch between source and traceability: "
            + ", ".join(
                f"{req_id} (source={src}, traceability={trc})"
                for req_id, src, trc in modality_mismatches
            )
        )

    return AuditReport(
        total_source=len(source),
        total_traced=len(trace),
        duplicate_source_ids=duplicate_source_ids,
        duplicate_trace_ids=duplicate_trace_ids,
        missing_from_traceability=missing_from_traceability,
        unknown_in_traceability=unknown_in_traceability,
        modality_mismatches=modality_mismatches,
        counts_by_modality=counts_by_modality,
        counts_by_state=counts_by_state,
        audits=tuple(audits),
        structural_errors=tuple(structural_errors),
    )


def strict_failures(
    report: AuditReport,
) -> tuple[list[RequirementAudit], list[RequirementAudit]]:
    must_not_closed = [a for a in report.audits if a.modality == "MUST" and not a.closed]
    should_not_closed = [a for a in report.audits if a.modality == "SHOULD" and not a.closed]
    return must_not_closed, should_not_closed


def print_human(report: AuditReport, *, strict: bool) -> None:
    print(f"Source requirements: {report.total_source}")
    print(f"Traceability requirements: {report.total_traced}")
    print()

    print("By modality:")
    for modality in sorted(report.counts_by_modality):
        print(f"  {modality}: {report.counts_by_modality[modality]}")
    print("By state:")
    for state in sorted(report.counts_by_state):
        print(f"  {state}: {report.counts_by_state[state]}")
    print()

    if report.structural_errors:
        print("STRUCTURAL ERRORS:")
        for error in report.structural_errors:
            print(f"  - {error}")
    else:
        print(
            "Structural integrity: OK (unique IDs, full source coverage, "
            "no unknown IDs, matching modalities)"
        )
    print()

    non_verified = [a for a in report.audits if a.state.strip().upper() != "VERIFIED"]
    print(f"Non-VERIFIED requirements: {len(non_verified)} / {report.total_traced}")
    for modality in sorted({a.modality for a in non_verified}):
        ids = [a.req_id for a in non_verified if a.modality == modality]
        print(f"  {modality} ({len(ids)}): {', '.join(ids)}")
    print()

    planned = [a for a in report.audits if a.state.strip().upper() == "PLANNED"]
    print(f"PLANNED requirements: {len(planned)}")
    for audit in planned:
        print(f"  {audit.req_id} [{audit.modality}]: {audit.evidence}")
    print()

    if strict:
        must_not_closed, should_not_closed = strict_failures(report)
        print(f"STRICT CLOSURE — MUST not closed: {len(must_not_closed)}")
        for audit in must_not_closed:
            print(f"  {audit.req_id}: {audit.reason}")
        print(
            f"STRICT CLOSURE — SHOULD not closed (no VERIFIED, no documented deviation): "
            f"{len(should_not_closed)}"
        )
        for audit in should_not_closed:
            print(f"  {audit.req_id}: {audit.reason}")
        print()
        if report.structural_errors or must_not_closed or should_not_closed:
            print("STAGE 10 STRICT CLOSURE: FAIL")
        else:
            print("STAGE 10 STRICT CLOSURE: PASS")
    else:
        print(
            "Normal audit mode complete (informational only; "
            "run with --strict-closure for final Stage 10 acceptance gating)."
        )


def report_to_dict(report: AuditReport, *, strict: bool) -> dict[str, object]:
    data: dict[str, object] = asdict(report)
    if strict:
        must_not_closed, should_not_closed = strict_failures(report)
        data["strict_closure"] = {
            "must_not_closed": [asdict(a) for a in must_not_closed],
            "should_not_closed": [asdict(a) for a in should_not_closed],
            "result": (
                "FAIL"
                if report.structural_errors or must_not_closed or should_not_closed
                else "PASS"
            ),
        }
    else:
        data["mode"] = "normal"
    return data


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict-closure",
        action="store_true",
        help="Gate mode for final Stage 10 acceptance: fail unless every MUST is "
        "VERIFIED with concrete evidence and every SHOULD is VERIFIED or carries "
        "an explicit documented deviation.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable JSON report instead of the human-readable summary.",
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=SPEC,
        help="Path to the normative specification containing the requirement registry.",
    )
    parser.add_argument(
        "--traceability",
        type=Path,
        default=TRACE,
        help="Path to the generated requirements traceability table.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    source_text = args.spec.read_text(encoding="utf-8-sig")
    trace_text = args.traceability.read_text(encoding="utf-8-sig")

    source = parse_source_registry(source_text)
    trace = parse_traceability_table(trace_text)
    report = build_report(source, trace)

    if args.json:
        print(json.dumps(report_to_dict(report, strict=args.strict_closure), indent=2))
    else:
        print_human(report, strict=args.strict_closure)

    if report.structural_errors:
        return 1
    if args.strict_closure:
        must_not_closed, should_not_closed = strict_failures(report)
        if must_not_closed or should_not_closed:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
