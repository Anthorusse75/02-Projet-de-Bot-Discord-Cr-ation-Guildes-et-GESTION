#!/usr/bin/env python3
"""Validate the implementation dossier without executing product code."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
REFERENCE = DOCS / "00_reference"
IMPLEMENTATION = DOCS / "10_implementation"

EXPECTED_HASHES = {
    "01_SPECIFICATIONS_FONCTIONNELLES_DISCORD_INFRA_DESIGNER.md": "8d7b1bc94909693310e32eef892da6e2bc5b1dcc2d755d34ba484af2fc9f021e",
    "02_ARCHITECTURE_TECHNIQUE_DISCORD_INFRA_DESIGNER.md": "bfa7d9dc712dbc3e70ecab89b5b747989b530cbb73be7bad47b6820c2c046e71",
}

REQUIRED_PATHS = [
    "README.md", "AGENTS.md", ".gitignore", ".github/pull_request_template.md",
    ".github/ISSUE_TEMPLATE/implementation-stage.md",
    "docs/00_reference/REFERENCE_MANIFEST.md",
    "docs/10_implementation/00_MASTER_IMPLEMENTATION_INDEX.md",
    "docs/10_implementation/00_GLOBAL_IMPLEMENTATION_CONTRACT.md",
    "docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md",
    "docs/10_implementation/00_CURRENT_STATE.md",
    "docs/20_testing/TEST_STRATEGY.md", "docs/20_testing/TEST_EVIDENCE_POLICY.md",
    "docs/20_testing/DISCORD_SANDBOX_TEST_MATRIX.md",
    "docs/30_security/SECRETS_AND_CREDENTIALS.md",
    "docs/30_security/THREAT_VALIDATION_CHECKLIST.md",
    "docs/30_security/TENANT_ISOLATION_TEST_POLICY.md",
    "docs/40_decisions/IMPLEMENTATION_DECISIONS.md",
    "docs/90_handoffs/README.md", "docs/90_handoffs/STAGE_HANDOFF_TEMPLATE.md",
    "scripts/generate_traceability.py", "scripts/validate_documentation.py",
]

STAGE_HEADINGS = [
    "## A. Identité", "## B. Sources normatives", "## C. PRECHECK obligatoire",
    "## D. Scope exact", "## E. Design d’implémentation détaillé",
    "## F. Liste prévue de fichiers", "## G. Stratégie de tests de l’étape",
    "## H. Matrice de validation", "## I. Commandes exactes de validation",
    "## J. Tests Discord réels", "## K. Secrets / credentials nécessaires",
    "## L. Critères d’acceptation", "## M. Definition of Done",
    "## N. Handoff obligatoire", "## O. Prompt de démarrage d’un nouveau chat Codex",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_requirements() -> list[str]:
    text = (REFERENCE / "01_SPECIFICATIONS_FONCTIONNELLES_DISCORD_INFRA_DESIGNER.md").read_text(encoding="utf-8-sig")
    registry = text.split("# 53. Registre normatif des exigences", 1)[1]
    return re.findall(r"^- \*\*(REQ-[A-Z0-9-]+) — (?:MUST|SHOULD|MAY)\*\* :", registry, re.MULTILINE)


def trace_requirements() -> list[str]:
    text = (IMPLEMENTATION / "00_REQUIREMENTS_TRACEABILITY.md").read_text(encoding="utf-8")
    return re.findall(r"^\| (REQ-[A-Z0-9-]+) \|", text, re.MULTILINE)


def markdown_links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    return re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", text)


def main(check_git_clean: bool) -> int:
    errors: list[str] = []
    warnings: list[str] = []

    for relative in REQUIRED_PATHS:
        if not (ROOT / relative).exists():
            errors.append(f"missing required path: {relative}")

    stages = sorted(IMPLEMENTATION.glob("STAGE_[0-9][0-9]_*.md"))
    if len(stages) != 11:
        errors.append(f"expected exactly 11 stages, found {len(stages)}")
    expected_numbers = [f"{number:02d}" for number in range(1, 12)]
    actual_numbers = [path.name[6:8] for path in stages]
    if actual_numbers != expected_numbers:
        errors.append(f"stage numbering mismatch: {actual_numbers}")

    for stage in stages:
        text = stage.read_text(encoding="utf-8-sig")
        for heading in STAGE_HEADINGS:
            if heading not in text:
                errors.append(f"{stage.name}: missing heading {heading}")
        for token in ("PRECHECK", "Stratégie de tests", "Critères d’acceptation", "Handoff", "Prompt de démarrage"):
            if token.lower() not in text.lower():
                errors.append(f"{stage.name}: missing required content token {token}")
        if "```text" not in text or "Implémente uniquement STAGE" not in text:
            errors.append(f"{stage.name}: missing new-chat prompt block")
    if stages:
        stage11 = stages[-1].read_text(encoding="utf-8-sig")
        if "SKELETON_ONLY" not in stage11 or "réécrit intégralement" not in stage11:
            errors.append("STAGE 11 is not an explicit rewrite-only skeleton")

    source = source_requirements()
    traced = trace_requirements()
    if len(source) != len(set(source)):
        errors.append("duplicate REQ IDs in source registry")
    if len(traced) != len(set(traced)):
        errors.append("duplicate REQ IDs in traceability")
    missing = sorted(set(source) - set(traced))
    extra = sorted(set(traced) - set(source))
    if missing:
        errors.append(f"requirements missing from traceability: {missing}")
    if extra:
        errors.append(f"unknown requirements in traceability: {extra}")
    if len(source) != 246:
        warnings.append(f"source requirement count changed from imported baseline 246 to {len(source)}")

    manifest = (REFERENCE / "REFERENCE_MANIFEST.md").read_text(encoding="utf-8-sig")
    for filename, expected in EXPECTED_HASHES.items():
        actual = sha256(REFERENCE / filename)
        if actual != expected:
            errors.append(f"reference hash mismatch for {filename}: {actual}")
        if expected not in manifest:
            errors.append(f"manifest does not contain hash for {filename}")

    generated_docs = [ROOT / "README.md", ROOT / "AGENTS.md"] + [
        path for path in DOCS.rglob("*.md") if REFERENCE not in path.parents
    ]
    version_pattern = re.compile(r"\bV[123]\b", re.IGNORECASE)
    for path in generated_docs:
        text = path.read_text(encoding="utf-8-sig")
        if version_pattern.search(text):
            errors.append(f"forbidden product-version token V1/V2/V3 in {path.relative_to(ROOT)}")

    secret_patterns = [
        re.compile(r"(?i)(discord_(?:bot_token|client_secret)|session_secret|encryption_key)[ \t]*=[ \t]*[^<\s][^\r\n\s]{8,}"),
        re.compile(r"(?i)authorization:\s*(?:bot|bearer)\s+[A-Za-z0-9._-]{12,}"),
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ]
    for path in [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]:
        if path.suffix.lower() not in {".md", ".py", ".yml", ".yaml", ".json", ".txt", ""}:
            continue
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        if any(pattern.search(text) for pattern in secret_patterns):
            errors.append(f"possible real secret in {path.relative_to(ROOT)}")

    for path in [ROOT / "README.md", *DOCS.rglob("*.md")]:
        for link in markdown_links(path):
            target = link.split("#", 1)[0].strip()
            if not target or re.match(r"(?:https?|mailto):", target):
                continue
            target = target.strip("<>").replace("%20", " ")
            if not (path.parent / target).resolve().exists():
                errors.append(f"broken local link in {path.relative_to(ROOT)}: {link}")

    if check_git_clean:
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=False
        )
        if status.returncode != 0:
            errors.append(f"git status failed: {status.stderr.strip()}")
        elif status.stdout.strip():
            errors.append("git worktree is not clean")

    print(f"Stages: {len(stages)} | Source REQ: {len(source)} | Traced REQ: {len(traced)} | ADR expected: 35")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"Documentation validation FAILED with {len(errors)} error(s).")
        return 1
    print("Documentation validation PASSED.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-git-clean", action="store_true")
    args = parser.parse_args()
    sys.exit(main(args.check_git_clean))
