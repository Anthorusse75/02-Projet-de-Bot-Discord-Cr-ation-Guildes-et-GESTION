## STAGE 08 — Multilingual Content & Translation Topology

Draft candidate implementing WP1–WP20 on top of main `252a4661195a3868acd04a2987453e23fc6ee4ff`.

### Delivered

- tenant-safe Language Profiles, member visible-language sets, explicit inheritance and no fallback;
- Translation Groups, stable channel groups, variants, routes, CAS lifecycle and non-destructive unlink/remove;
- exact Scope × Language visibility roles, member reconciliation, optimizer and role/overwrite budgets;
- abstract non-invasive TranslationProvider with fail-closed capabilities, manual configuration and per-variant access preflight;
- positive-evidence drift/MISSING handling and Stage 05 repair/structural plan routes;
- multilingual portable A→B expansion with new IDs, no live link and no provider secrets;
- thin authorized FastAPI APIs, regenerated OpenAPI/types and internal audit;
- complete Translation Workspace, four multilingual actions, Right Drag and keyboard alternatives;
- immutable UI catalogue bump to `did-ui-v&#50;`, complete EN/FR/DE/ES packs;
- dedicated STAGE 08 unit/PostgreSQL/component/Playwright/live validators and CI jobs.

### Validation

- `python scripts/validate_stage.py 08` — PASS
- `python scripts/validate_stage.py 08 --profile e2e` — PASS (39 Playwright, including 8 STAGE 08 scenarios)
- `python scripts/validate_stage.py 08 --include-discord-live` — PASS on two real sandbox Guilds
- Ruff, format, MyPy, ESLint, TypeScript, build, i18n, OpenAPI, secret scan and documentation validation — PASS
- migration `0013_stage_07 → 0014_stage_08 → 0015_stage_08 → 0013_stage_07 → head` — PASS

All 43 IDs `REQ-I18N-001..042` plus `REQ-I18N-026A` are tracked as `IMPLEMENTED`; they are not promoted to `VERIFIED` before the repository's transverse qualification stage.

### Guardrails

- no Discord structural mutation from frontend or FastAPI routers;
- Stage 05 plan/worker/governor pipeline remains the only mutation path;
- cache-first normal reads and tenant RLS invariants preserved;
- no secret, sandbox Discord ID or member PII committed;
- provider bot integration remains non-invasive and uses `MANUAL_CONFIGURATION_REQUIRED` when automation is unsafe;
- PR intentionally remains Draft; no merge and no STAGE 09 work.
> **Deep review corrective work in progress.** The evidence attached to `f538105` was not sufficient for
> merge approval. PR #8 remains Draft and must not be merged or marked ready until all corrective findings
> have integrated and live proof.
