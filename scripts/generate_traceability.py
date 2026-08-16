#!/usr/bin/env python3
"""Generate the requirements/ADR traceability document from immutable references."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/00_reference/01_SPECIFICATIONS_FONCTIONNELLES_DISCORD_INFRA_DESIGNER.md"
ARCH = ROOT / "docs/00_reference/02_ARCHITECTURE_TECHNIQUE_DISCORD_INFRA_DESIGNER.md"
OUTPUT = ROOT / "docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md"

REQ_LINE = re.compile(r"^- \*\*(REQ-[A-Z0-9-]+) — (MUST|SHOULD|MAY)\*\* : (.+)$")
ADR_HEAD = re.compile(r"^## (ADR-\d{3}) — (.+)$")


def stage_for(req_id: str) -> tuple[str, str]:
    family = req_id.split("-")[1]
    number_match = re.search(r"(\d+)", req_id.rsplit("-", 1)[-1])
    number = int(number_match.group(1)) if number_match else 0
    primary = {
        "INST": "02", "AUTH": "02", "GW": "03", "CACHE": "03", "RATE": "03",
        "PERM": "04", "PLAN": "05", "DUP": "06", "UX": "07", "UI18N": "07",
        "I18N": "08", "MSG": "09", "DATA": "10", "TEST": "10", "AUD": "03",
    }.get(family, "10")
    if family == "TEN":
        primary = "06" if number >= 11 else "02"
    if family == "STR":
        primary = "04" if number <= 5 else "07"
    if family == "BOT":
        primary = "02" if number in {1, 2, 3, 7} else "10"
    secondary_map = {
        "INST": "03, 10", "AUTH": "03, 10", "GW": "04, 05, 10", "CACHE": "04, 05, 10",
        "RATE": "05, 09, 10", "AUD": "01, 05, 09, 10", "PERM": "05, 07, 10",
        "PLAN": "06, 08, 09, 10", "DUP": "07, 08, 10", "STR": "05, 06, 10",
        "UX": "05, 06, 10", "UI18N": "10", "I18N": "06, 07, 09, 10",
        "MSG": "08, 10", "BOT": "01, 03, 04, 10", "DATA": "03", "TEST": "toutes",
        "TEN": "01, 03, 05, 10",
    }
    return primary, secondary_map.get(family, "10")


def tests_for(req_id: str) -> str:
    family = req_id.split("-")[1]
    return {
        "INST": "API + PostgreSQL/RLS + Discord sandbox",
        "TEN": "isolation A/B + RLS + Redis/WS + IDOR",
        "STR": "domaine/cache + API + composant/E2E + sandbox",
        "PERM": "vecteurs officiels + property tests + sandbox",
        "PLAN": "domaine + DB/DAG + worker + failure injection",
        "DUP": "graph/mapping + A/B + artifact + sandbox",
        "BOT": "security + capability + hierarchy sandbox",
        "AUTH": "OAuth contract + session/CSRF + API/RLS",
        "GW": "event contract + cache + reconnect/sandbox",
        "AUD": "DB/outbox + redaction + correlation",
        "DATA": "privacy + purge/rétention + security",
        "UX": "component + pointer/keyboard + Playwright/a11y",
        "I18N": "domain/DB + topology + A/B + sandbox",
        "CACHE": "PostgreSQL/Redis + stale/reconcile + load",
        "RATE": "429/backpressure/fairness + metrics",
        "UI18N": "catalogue 100 % + runtime/security + E2E",
        "MSG": "scheduler/idempotence + parser/fuzz + corpus réel + sandbox",
        "TEST": "meta-validation + CI + live acceptance",
    }.get(family, "unit + integration + acceptance")


def extract_requirements() -> list[tuple[str, str, str]]:
    requirements: list[tuple[str, str, str]] = []
    in_registry = False
    for line in SPEC.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("# 53. Registre normatif"):
            in_registry = True
        if not in_registry:
            continue
        match = REQ_LINE.match(line)
        if match:
            requirements.append(match.groups())
    return requirements


def extract_adrs() -> list[tuple[str, str]]:
    lines = ARCH.read_text(encoding="utf-8-sig").splitlines()
    return [match.groups() for line in lines if (match := ADR_HEAD.match(line))]


ADR_STAGES = {
    "001": "02, toutes", "002": "01, toutes", "003": "03–10", "004": "05–10",
    "005": "01–11", "006": "01–10", "007": "04, 05, 10", "008": "03, 10",
    "009": "01, 04, 07", "010": "05, 06, 10", "011": "08, 09", "012": "08",
    "013": "08", "014": "08, 09", "015": "08", "016": "03–10", "017": "03, 04",
    "018": "03, 05, 09", "019": "02, 06, 09", "020": "08, 09", "021": "05, 06",
    "022": "03, 04, 07", "023": "03, 04", "024": "08", "025": "07",
    "026": "09", "027": "09", "028": "07", "029": "02", "030": "06, 09",
    "031": "09", "032": "02, 04", "033": "09", "034": "07", "035": "02, 04, 05",
}


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def render() -> str:
    requirements = extract_requirements()
    adrs = extract_adrs()
    lines = [
        "# Traçabilité des exigences",
        "",
        f"Source : registre §53 des spécifications. Total extrait : **{len(requirements)} exigences uniques**. ",
        "Cette table est générée par `python scripts/generate_traceability.py`; modifier le mapping dans le script, pas une ligne isolée. Le validateur compare les IDs à la source.",
        "",
        "## Exigences",
        "",
        "| REQ ID | Résumé normatif | Modalité | Étape principale | Étapes secondaires | Tests attendus | État | Preuve/test/commit |",
        "|---|---|---|---:|---|---|---|---|",
    ]
    seen: set[str] = set()
    for req_id, modality, summary in requirements:
        if req_id in seen:
            raise ValueError(f"Duplicate requirement in source registry: {req_id}")
        seen.add(req_id)
        primary, secondary = stage_for(req_id)
        lines.append(
            f"| {req_id} | {escape_cell(summary)} | {modality} | {primary} | {secondary} | "
            f"{tests_for(req_id)} | PLANNED | À renseigner lors de l’étape |"
        )
    lines.extend([
        "", "## ADR → étapes", "",
        "| ADR | Décision | Étapes concernées |", "|---|---|---|",
    ])
    for adr_id, title in adrs:
        lines.append(f"| {adr_id} | {escape_cell(title)} | {ADR_STAGES[adr_id[-3:]]} |")
    lines.extend([
        "", "## Règle de mise à jour", "",
        "Une exigence ne passe à `IMPLEMENTED` que lorsque le code et son test existent sur la branche de l’étape. Elle passe à `VERIFIED` uniquement après exécution verte sur le commit livré et ajout d’une preuve précise. STAGE 10 refuse sa clôture si une exigence MUST reste `PLANNED`/`IMPLEMENTED` sans déviation approuvée impossible, ou si une preuve ne permet pas de reproduire la validation.",
        "",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    OUTPUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} with {len(extract_requirements())} requirements and {len(extract_adrs())} ADRs")
