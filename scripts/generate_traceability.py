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
        "INST": "02",
        "AUTH": "02",
        "GW": "03",
        "CACHE": "03",
        "RATE": "03",
        "PERM": "04",
        "PLAN": "05",
        "DUP": "06",
        "UX": "07",
        "UI18N": "07",
        "I18N": "08",
        "MSG": "09",
        "DATA": "10",
        "TEST": "10",
        "AUD": "03",
    }.get(family, "10")
    if family == "TEN":
        primary = "06" if number >= 11 else "02"
    if family == "STR":
        primary = "04" if number <= 5 else "07"
    if family == "BOT":
        primary = "02" if number in {1, 2, 3, 7} else "10"
    secondary_map = {
        "INST": "03, 10",
        "AUTH": "03, 10",
        "GW": "04, 05, 10",
        "CACHE": "04, 05, 10",
        "RATE": "05, 09, 10",
        "AUD": "01, 05, 09, 10",
        "PERM": "05, 07, 10",
        "PLAN": "06, 08, 09, 10",
        "DUP": "07, 08, 10",
        "STR": "05, 06, 10",
        "UX": "05, 06, 10",
        "UI18N": "10",
        "I18N": "06, 07, 09, 10",
        "MSG": "08, 10",
        "BOT": "01, 03, 04, 10",
        "DATA": "03",
        "TEST": "toutes",
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
    "001": "02, toutes",
    "002": "01, toutes",
    "003": "03–10",
    "004": "05–10",
    "005": "01–11",
    "006": "01–10",
    "007": "04, 05, 10",
    "008": "03, 10",
    "009": "01, 04, 07",
    "010": "05, 06, 10",
    "011": "08, 09",
    "012": "08",
    "013": "08",
    "014": "08, 09",
    "015": "08",
    "016": "03–10",
    "017": "03, 04",
    "018": "03, 05, 09",
    "019": "02, 06, 09",
    "020": "08, 09",
    "021": "05, 06",
    "022": "03, 04, 07",
    "023": "03, 04",
    "024": "08",
    "025": "07",
    "026": "09",
    "027": "09",
    "028": "07",
    "029": "02",
    "030": "06, 09",
    "031": "09",
    "032": "02, 04",
    "033": "09",
    "034": "07",
    "035": "02, 04, 05",
}

REQUIREMENT_PROGRESS = {
    "REQ-TEN-001": (
        "IMPLEMENTED",
        "STAGE 01 foundation: migration 0001_stage_01 + PostgreSQL A/B integration evidence",
    ),
    "REQ-TEN-007": (
        "IMPLEMENTED",
        "STAGE 01 Redis namespace builder + unit/real Redis tests; extend through later features and verify finally in STAGE 10",
    ),
    "REQ-TEN-010": (
        "IMPLEMENTED",
        "STAGE 01 canary RLS: A/B, absent context, cross-write denial and pool reuse; later tenant tables remain to cover before STAGE 10 verification",
    ),
    "REQ-AUD-004": (
        "IMPLEMENTED",
        "STAGE 01 static event registry, fail-safe formatter, recursive redaction and secret scan; all later emitters remain to cover before STAGE 10 verification",
    ),
    "REQ-BOT-001": (
        "IMPLEMENTED",
        "STAGE 01 boundary: no Discord credential dependency; frontend secret-name scan PASS",
    ),
    "REQ-TEST-001": (
        "IMPLEMENTED",
        "STAGE 02 tenant endpoints have cross-tenant, foreign-ID and zero-forbidden-repository-call tests; future endpoint families remain to cover",
    ),
    "REQ-TEST-002": (
        "PLANNED",
        "STAGE 01 test harness delivered; Permission Engine is out of scope",
    ),
    "REQ-TEST-003": (
        "IMPLEMENTED",
        "STAGE 02 exercised two independent Discord sandbox Guilds with redacted evidence; final transverse verification remains STAGE 10",
    ),
    "REQ-TEST-004": (
        "PLANNED",
        "STAGE 01 test harness delivered; destructive operations are out of scope",
    ),
    "REQ-TEST-005": (
        "PLANNED",
        "Frontend unit/build baseline delivered; product Playwright flows remain STAGE 10",
    ),
}

for requirement_id in (f"REQ-INST-{index:03d}" for index in range(1, 8)):
    REQUIREMENT_PROGRESS[requirement_id] = (
        "IMPLEMENTED",
        "STAGE 02 migration 0002 + conservative installation transition matrix, identity mismatch refusal, bootstrap/RBAC integration tests and Discord A/B live evidence; later event-driven lifecycle work remains before VERIFIED",
    )

for requirement_id in (f"REQ-AUTH-{index:03d}" for index in range(1, 15)):
    REQUIREMENT_PROGRESS[requirement_id] = (
        "IMPLEMENTED",
        "STAGE 02 browser-bound one-shot OAuth state, session/CSRF/crypto and scoped fresh-authorization implementation with unit, Redis and API integration tests; transverse final verification remains required",
    )

for requirement_id in (
    "REQ-TEN-001",
    "REQ-TEN-002",
    "REQ-TEN-003",
    "REQ-TEN-004",
    "REQ-TEN-007",
    "REQ-TEN-010",
):
    REQUIREMENT_PROGRESS[requirement_id] = (
        "IMPLEMENTED",
        "STAGE 02 guild/user RLS, scoped RBAC, authorization-before-installation-disclosure, A/B IDOR zero-call and pool-context integration tests; later tenant resource families remain independently gated",
    )

REQUIREMENT_PROGRESS["REQ-BOT-001"] = (
    "IMPLEMENTED",
    "STAGE 02 bot token remains backend-only; frontend scan, redacted adapters and security gates PASS",
)
REQUIREMENT_PROGRESS["REQ-BOT-002"] = (
    "IMPLEMENTED",
    "STAGE 02 install link requests zero bot permissions and bootstrap tests distinguish user ADMINISTRATOR from bot permissions",
)
REQUIREMENT_PROGRESS["REQ-BOT-007"] = (
    "IMPLEMENTED",
    "STAGE 02 accepts only official OAuth2 bearer grants and a backend bot token; no self-bot/user-token path exists",
)

STAGE03_REQUIREMENT_PROGRESS = {
    "REQ-GW-001": ("IMPLEMENTED", "STAGE 03 minimal GUILDS intent contract and tests"),
    "REQ-GW-002": ("IMPLEMENTED", "STAGE 03 MESSAGE_CONTENT-disabled contract tests"),
    "REQ-GW-003": ("IMPLEMENTED", "STAGE 03 explicit member-event capability model"),
    "REQ-GW-004": ("IMPLEMENTED", "STAGE 03 normalized versioned EventEnvelope tests"),
    "REQ-GW-005": ("IMPLEMENTED", "STAGE 03 durable inbox deduplication tests"),
    "REQ-GW-006": (
        "PLANNED",
        "Plan invalidation requires the Stage 05 Plan Engine; Stage 03 only emits durable drift",
    ),
    "REQ-GW-007": ("IMPLEMENTED", "STAGE 03 obfuscation contract and no-false-delete tests"),
    "REQ-GW-008": ("IMPLEMENTED", "STAGE 03 explicit GUILD_MEMBERS opt-in and degraded mode"),
    "REQ-CACHE-001": ("IMPLEMENTED", "STAGE 03 cache-only dashboard read tests"),
    "REQ-CACHE-002": ("IMPLEMENTED", "STAGE 03 PostgreSQL durable structure cache with RLS"),
    "REQ-CACHE-003": ("IMPLEMENTED", "STAGE 03 idempotent Gateway projection tests"),
    "REQ-CACHE-004": (
        "PLANNED",
        "Discord mutation write-through belongs to the Stage 05 mutation engine",
    ),
    "REQ-CACHE-005": (
        "IMPLEMENTED",
        "STAGE 03 observable/current versus last-known metadata model",
    ),
    "REQ-CACHE-006": ("IMPLEMENTED", "STAGE 03 ACCESS_LOST/OBFUSCATED transition tests"),
    "REQ-CACHE-007": (
        "PLANNED",
        "The explicit Structure UI visibility option belongs to Stages 04/07",
    ),
    "REQ-CACHE-008": ("IMPLEMENTED", "STAGE 03 authorized individual/bulk purge contracts"),
    "REQ-CACHE-009": ("IMPLEMENTED", "STAGE 03 local-only purge and auditable tombstone tests"),
    "REQ-CACHE-010": ("IMPLEMENTED", "STAGE 03 Gateway and REST reobservation tests"),
    "REQ-CACHE-011": ("IMPLEMENTED", "STAGE 03 purge preview count/list and durable audit tests"),
    "REQ-CACHE-012": ("IMPLEMENTED", "STAGE 03 adaptive jitter/dedupe/priority/backpressure tests"),
    "REQ-CACHE-013": ("IMPLEMENTED", "STAGE 03 atomic Redis generation single-flight tests"),
    "REQ-RATE-001": ("IMPLEMENTED", "STAGE 03 delegates dynamic buckets to pinned discord.py"),
    "REQ-RATE-002": (
        "IMPLEMENTED",
        "STAGE 03 Redis-coordinated system/global and per-Guild permits",
    ),
    "REQ-RATE-003": ("IMPLEMENTED", "STAGE 03 typed 429 Retry-After handling tests"),
    "REQ-RATE-004": (
        "IMPLEMENTED",
        "STAGE 03 shared Redis invalid budget, 401 halt and pressure tests",
    ),
    "REQ-RATE-005": (
        "PLANNED",
        "Bulk endpoint selection requires the Stage 05 Plan Compiler, which does not exist yet",
    ),
    "REQ-RATE-006": ("IMPLEMENTED", "STAGE 03 bounded 429/wait/queue/cache-ratio/invalid metrics"),
    "REQ-AUD-001": ("IMPLEMENTED", "Stage 03 dashboard cache purge audit records the actor"),
    "REQ-AUD-002": ("PLANNED", "plan_id audit requires the Stage 05 Plan Engine"),
    "REQ-AUD-003": ("PLANNED", "Discord mutation audit reasons require Stage 05 mutation adapters"),
    "REQ-AUD-004": ("IMPLEMENTED", "Stage 01/03 redaction and secret-scan gates"),
    "REQ-AUD-005": ("IMPLEMENTED", "STAGE 03 durable internal_audit_events ledger"),
    "REQ-AUD-006": ("IMPLEMENTED", "STAGE 03 external-origin durable drift signals"),
    "REQ-TEN-005": ("IMPLEMENTED", "STAGE 03 tenant Pub/Sub and continuously authorized WS tests"),
    "REQ-TEN-006": ("IMPLEMENTED", "STAGE 03 guild-scoped durable jobs and bounded ID routing"),
    "REQ-TEN-007": ("IMPLEMENTED", "STAGE 03 tenant Redis cache/single-flight/permit keys"),
    "REQ-TEN-008": ("PLANNED", "Private templates belong to Stage 06 and do not exist yet"),
    "REQ-TEN-009": ("IMPLEMENTED", "STAGE 03 RLS-isolated internal audit integration tests"),
}

REQUIREMENT_PROGRESS.update(STAGE03_REQUIREMENT_PROGRESS)

STAGE04_REQUIREMENT_PROGRESS = {
    "REQ-CACHE-007": (
        "PLANNED",
        "STAGE 04 exposes explicit include_hidden_deleted structure API semantics; the user-facing Structure control remains STAGE 07",
    ),
    "REQ-STR-001": (
        "IMPLEMENTED",
        "STAGE 04 immutable Guild/category/channel/thread projection and cache-first structure API tests",
    ),
    "REQ-STR-002": (
        "IMPLEMENTED",
        "STAGE 04 rejects category parent_id and projects only one real Discord category level",
    ),
    "REQ-STR-003": (
        "IMPLEMENTED",
        "STAGE 04 tenant-safe logical groups are explicitly DID_LOGICAL_RESOURCE and non-recursive",
    ),
    "REQ-STR-004": (
        "PLANNED",
        "STAGE 04 models and diagnoses real parent_id read-only; move validation/execution belongs to STAGE 05",
    ),
    "REQ-STR-005": (
        "PLANNED",
        "STAGE 04 preserves real category/child topology read-only; deletion behavior is enforced with STAGE 05 plans",
    ),
    "REQ-PERM-001": (
        "IMPLEMENTED",
        "STAGE 04 arbitrary-precision registry/evaluator/API decimal-string and >2^53 unknown-bit tests",
    ),
    "REQ-PERM-002": (
        "IMPLEMENTED",
        "STAGE 04 owner and ADMINISTRATOR bypass vectors including channel/member denies",
    ),
    "REQ-PERM-003": (
        "IMPLEMENTED",
        "STAGE 04 pure simple-concept compiler emits only registry-backed Discord bits and never persists",
    ),
    "REQ-PERM-004": (
        "IMPLEMENTED",
        "STAGE 04 expert model exposes calculated/effective flags, raw overwrites, unknown bits and coverage",
    ),
    "REQ-PERM-005": (
        "IMPLEMENTED",
        "STAGE 04 View As member/role/newcomer uses known roles only and exposes incomplete knowledge",
    ),
    "REQ-PERM-006": (
        "IMPLEMENTED",
        "STAGE 04 deterministic ordered PermissionTraceEntry vectors cover every resolution phase",
    ),
    "REQ-PERM-007": (
        "IMPLEMENTED",
        "STAGE 04 ADMINISTRATOR bypass emits a stable visible warning and ignores overwrites",
    ),
    "REQ-PERM-008": (
        "IMPLEMENTED",
        "STAGE 04 read-only current/proposed overwrite simulation returns per-subject added/removed bits",
    ),
    "REQ-PERM-009": (
        "IMPLEMENTED",
        "STAGE 04 explain API separates Discord-native permission from DID dashboard authorization",
    ),
    "REQ-BOT-003": (
        "IMPLEMENTED",
        "STAGE 04 capability checker reports exact missing minimum permission, coverage, intent and hierarchy causes",
    ),
    "REQ-BOT-004": (
        "PLANNED",
        "STAGE 04 flags ADMINISTRATOR for the installed bot capability check; guild-wide bot security audit remains STAGE 10",
    ),
    "REQ-BOT-005": (
        "PLANNED",
        "STAGE 04 evaluates the installed bot for an explicit channel/operation; all-bot read/write inventory remains STAGE 10",
    ),
    "REQ-BOT-006": (
        "PLANNED",
        "STAGE 04 can simulate real overwrite inputs read-only; applying this configuration belongs to STAGE 05/10",
    ),
    "REQ-AUTH-013": (
        "IMPLEMENTED",
        "STAGE 02 targeted member lookup, strengthened in STAGE 04 with tenant single-flight and three-consumer integration test",
    ),
    "REQ-AUTH-014": (
        "IMPLEMENTED",
        "STAGE 02 display/authorization freshness split, with STAGE 04 stale fail-closed and coalesced refresh tests",
    ),
    "REQ-TEST-002": (
        "IMPLEMENTED",
        "STAGE 04 official table-driven vectors, permutation invariants, incomplete/security and deterministic benchmark",
    ),
}

REQUIREMENT_PROGRESS.update(STAGE04_REQUIREMENT_PROGRESS)

STAGE05_REQUIREMENT_PROGRESS = {
    **{
        f"REQ-PLAN-{index:03d}": (
            "IMPLEMENTED",
            "STAGE 05 immutable DSG/plan snapshot, explicit persisted DAG and symbols, final preflight, fenced worker attempts, UNKNOWN_OUTCOME reconciliation, targeted verification and failure-injection integration evidence",
        )
        for index in range(1, 17)
    },
    "REQ-STR-004": (
        "IMPLEMENTED",
        "STAGE 05 deterministic channel move/reorder compilation and mutable-adapter contract; bulk requests contain at most one parent_id change",
    ),
    "REQ-STR-005": (
        "IMPLEMENTED",
        "STAGE 05 explicit category-child effects and dependency/preflight checks prevent implicit destructive topology changes",
    ),
    "REQ-GW-006": (
        "IMPLEMENTED",
        "STAGE 05 Gateway drift classification marks pre-apply plans STALE and active plans intervention-required unless an expected own mutation is proven",
    ),
    "REQ-CACHE-004": (
        "IMPLEMENTED",
        "STAGE 05 persists successful operation results, symbol bindings, expected events and structural write-through atomically",
    ),
    "REQ-RATE-005": (
        "IMPLEMENTED",
        "STAGE 05 compiler selects closed mutation operations and splits channel parent changes to respect the official bulk endpoint constraint",
    ),
    "REQ-AUD-001": (
        "IMPLEMENTED",
        "STAGE 05 plan lifecycle audit records preserve the authenticated actor for create, validate, confirm, apply and cancel",
    ),
    "REQ-AUD-002": (
        "IMPLEMENTED",
        "STAGE 05 durable plan/operation/attempt/progress records correlate guild, plan, operation, job and request without exposing secrets",
    ),
    "REQ-AUD-003": (
        "IMPLEMENTED",
        "STAGE 05 mutation adapter emits bounded stable Discord audit reasons with plan/operation correlation and no user-provided text",
    ),
}

REQUIREMENT_PROGRESS.update(STAGE05_REQUIREMENT_PROGRESS)

STAGE06_REQUIREMENT_PROGRESS = {
    "REQ-TEN-008": (
        "IMPLEMENTED",
        "STAGE 06 tenant-keyed templates with FORCE RLS, composite primary key and real A/B PostgreSQL isolation test",
    ),
    "REQ-TEN-011": (
        "IMPLEMENTED",
        "STAGE 06 creates only actor-requested transfers with explicit source/destination IDs; no discovery, sharing or federation path exists",
    ),
    "REQ-TEN-012": (
        "IMPLEMENTED",
        "STAGE 06 API separately authorizes STRUCTURE_READ on A then PLANS_CREATE+STRUCTURE_WRITE on B; confused-deputy denial tests assert zero export/plan",
    ),
    "REQ-TEN-013": (
        "IMPLEMENTED",
        "STAGE 06 immutable portable snapshot ends source reads before mapping and destination DSG; stored-artifact fail-if-source-called test",
    ),
    "REQ-TEN-014": (
        "IMPLEMENTED",
        "STAGE 06 clipboard/library artifacts use owner FORCE RLS, bounded TTL/quota and AES-256-GCM envelope encryption with U/V PostgreSQL tests",
    ),
    "REQ-DUP-001": (
        "IMPLEMENTED",
        "STAGE 06 category builder closes real category children/roles/overwrites and compiles only STAGE 05 category/channel primitives",
    ),
    "REQ-DUP-002": (
        "IMPLEMENTED",
        "STAGE 06 strict schema has no message/history resource and rejects message IDs and secret/operational fields",
    ),
    "REQ-DUP-003": (
        "IMPLEMENTED",
        "STAGE 06 logical-group artifact resolves structural mappings then finalizes a new deterministic destination DID UUID after plan success",
    ),
    "REQ-DUP-004": (
        "IMPLEMENTED",
        "STAGE 06 COPY_AS_NEW ignores same-name/source-ID identity and creates roles unless a visible confirmed mapping is supplied",
    ),
    "REQ-DUP-005": (
        "IMPLEMENTED",
        "STAGE 06 artifacts/templates use bounded logical keys, dependency references and destination symbols; source IDs are provenance-only",
    ),
    "REQ-DUP-006": (
        "IMPLEMENTED",
        "STAGE 06 template apply reuses strict artifact validation, mapping and STAGE 05 preflight; unresolved/incompatible resources block",
    ),
    "REQ-DUP-007": (
        "IMPLEMENTED",
        "STAGE 06 DependencyGraph validates references and topological acyclicity before DestinationPlanCompiler",
    ),
    "REQ-DUP-008": (
        "IMPLEMENTED",
        "STAGE 06 source builder converts Discord structural IDs to generated logical keys and symbols; hostile direct destination ID keys reject",
    ),
    "REQ-DUP-009": (
        "IMPLEMENTED",
        "Same-name suggestions stay MANUAL; READY freezes a SHA-256 of explicit intent plus complete resolved semantics and PostgreSQL/unit crash-window tests reject deleted targets, alternative candidates, CREATE drift and explicit M1→M2 before planning",
    ),
    "REQ-DUP-010": (
        "IMPLEMENTED",
        "STAGE 06 MAXIMUM_COMPATIBLE produces stable CREATED/REMAPPED/SKIPPED/IMPOSSIBLE/INTERVENTION report entries",
    ),
    "REQ-DUP-011": (
        "IMPLEMENTED",
        "STAGE 06 live API checks A and B independently; source observability and destination STAGE 05 capability preflight fail closed",
    ),
    "REQ-DUP-012": (
        "IMPLEMENTED",
        "STAGE 06 file/artifact contract explicitly excludes members, messages, audit, ownership, secrets and original operational IDs",
    ),
    "REQ-DUP-013": (
        "IMPLEMENTED",
        "STAGE 06 export, clipboard, library/file clone and template apply converge on PortableArtifact→DependencyGraph→MappingResolver→DSG→PlanningService",
    ),
    "REQ-DUP-014": (
        "IMPLEMENTED",
        "STAGE 06 stored compile test asserts the only read-model call and resulting DSG guild_id are destination B; no mutable adapter or dual lock import",
    ),
    "REQ-DUP-015": (
        "IMPLEMENTED",
        "STAGE 06 exposes four CloneMode values plus a versioned per-resource operation support matrix",
    ),
    "REQ-DUP-016": (
        "IMPLEMENTED",
        "STAGE 06 persisted mapping/report JSON lists manual, unsupported, skipped, remapped, created and impossible outcomes before apply",
    ),
    "REQ-DUP-017": (
        "IMPLEMENTED",
        "STAGE 06 RECONCILE creates destructive DSG nodes only from an explicit ReconcileScope and reports each exact destination ref",
    ),
    "REQ-DUP-018": (
        "IMPLEMENTED",
        "STAGE 06 LIVE export requires FULL/FRESH/visible complete source; stored compilation has a source-reader fail-if-called proof",
    ),
    "REQ-DUP-019": (
        "IMPLEMENTED",
        "STAGE 06 persists portable dashboard policy definitions separately with no active source bindings; principal mapping must be explicit and confirmed",
    ),
}

REQUIREMENT_PROGRESS.update(STAGE06_REQUIREMENT_PROGRESS)


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
        state, proof = REQUIREMENT_PROGRESS.get(req_id, ("PLANNED", "À renseigner lors de l’étape"))
        lines.append(
            f"| {req_id} | {escape_cell(summary)} | {modality} | {primary} | {secondary} | "
            f"{tests_for(req_id)} | {state} | {proof} |"
        )
    lines.extend(
        [
            "",
            "## ADR → étapes",
            "",
            "| ADR | Décision | Étapes concernées |",
            "|---|---|---|",
        ]
    )
    for adr_id, title in adrs:
        lines.append(f"| {adr_id} | {escape_cell(title)} | {ADR_STAGES[adr_id[-3:]]} |")
    lines.extend(
        [
            "",
            "## Règle de mise à jour",
            "",
            "Une exigence ne passe à `IMPLEMENTED` que lorsque le code et son test existent sur la branche de l’étape. Elle passe à `VERIFIED` uniquement après exécution verte sur le commit livré et ajout d’une preuve précise. STAGE 10 refuse sa clôture si une exigence MUST reste `PLANNED`/`IMPLEMENTED` sans déviation approuvée impossible, ou si une preuve ne permet pas de reproduire la validation.",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    OUTPUT.write_text(render(), encoding="utf-8", newline="\n")
    print(
        f"Wrote {OUTPUT.relative_to(ROOT)} with {len(extract_requirements())} requirements and {len(extract_adrs())} ADRs"
    )
