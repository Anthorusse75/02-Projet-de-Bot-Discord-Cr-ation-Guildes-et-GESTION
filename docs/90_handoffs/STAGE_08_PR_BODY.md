## STAGE 08 — Multilingual Content & Translation Topology

Draft candidate implementing WP1–WP20 on top of main `252a4661195a3868acd04a2987453e23fc6ee4ff`.
An external deep review found defects in the first candidate (`f538105`); all 23 findings have since
been remediated in code and re-verified against the current diff (see Findings below). A first real
sandbox live qualification attempt then found one more genuine code defect (control-plane bot access on
cloned restricted channels); it was corrected and re-qualification PASSed on real Discord sandboxes. Both
non-live and live validation are fully green. PR #8 remains Draft pending the external reviewer's final
independent audit before merge.

### Delivered

- tenant-safe Language Profiles, member visible-language sets, explicit inheritance and no fallback;
- Translation Groups, stable channel groups, variants, routes, CAS lifecycle and non-destructive unlink/remove;
- PostgreSQL-proven intra-Guild Translation Group isolation (rename, unlink, link never cross group boundaries);
- exact Scope × Language visibility roles compiled by `Stage08StructuralPlanningService` from durable topology
  plus the authoritative Discord cache: concurrency-safe reservation, lazy role creation, role/overwrite budgets,
  Stage 05 DSGs, post-verification materialization, reuse and fail-closed cleanup;
- member role reconciliation from durable visible languages, `ScopeMembershipResolver` and the authoritative
  Discord member cache — never from client-supplied data;
- `Stage08ProviderOrchestrationService` derives provider capabilities/permissions from durable state, Stage 04
  cache and a `PermissionEvaluator`; the browser can no longer declare authoritative capabilities;
- abstract non-invasive `TranslationProvider` with fail-closed capabilities, `PROVIDER_PENDING` /
  `APPLIED_WITH_PENDING_PROVIDER` partial states, and per-variant access preflight; `READY` is unreachable
  before explicit verification;
- Stage 03 Gateway persists the Discord `user.bot` fact durably and tracks member-completeness for operations
  that require exhaustive proof (e.g. safe technical-role cleanup, which fails closed without it);
- positive-evidence drift/MISSING handling and Stage 05 repair/structural plan routes;
- server-side intent compilers for Stage08 business operations — no router accepts an arbitrary client-built DSG;
- real Stage06 engine (Portable Artifact, Dependency Graph, Clone compiler, Planning Service, Destination Plan,
  post-verification materialization) for multilingual A→B expansion with new IDs, no live link and no provider
  secrets; the Portable Artifact schema is allowlist-typed and recursively rejects secret-shaped key families;
- a narrowly-scoped control-plane access grant on cloned visibility-restricted channels so the DID bot itself
  never loses the ability to manage what it just created — never Administrator, never a human business-scope
  role (see Findings below);
- thin authorized FastAPI APIs, regenerated OpenAPI/types and internal audit;
- complete Translation Workspace (cache-first reads), four multilingual ActionRegistry actions wired to real
  backend routes, Right Drag with `LANGUAGE_TARGET`/Guild-destination targets, and keyboard alternatives;
- immutable UI catalogue bump to `did-ui-v&#50;`, complete EN/FR/DE/ES packs;
- dedicated STAGE 08 unit/PostgreSQL/component/Playwright/live validators and CI jobs.

### Validation

- `python scripts/validate_stage.py 08` — PASS
- `python scripts/validate_stage.py 08 --profile e2e` — PASS (40 Playwright, including 8 STAGE 08 scenarios)
- `python scripts/validate_stage.py 08 --include-discord-live` — **PASS** on two real sandbox Guilds, tested on
  commit `592b94b` (sanitized evidence committed at
  `docs/90_handoffs/evidence/stage08/discord-live-stage08.json`: zero secret, zero Discord identifier, zero
  member PII, zero direct Discord mutation, zero `MESSAGE_CONTENT` intent)
- Ruff, format, MyPy, ESLint, TypeScript, build, i18n, OpenAPI, secret scan and documentation validation — PASS
- Migration rehearsal `0013_stage_07 → 0014_stage_08 → … → 0021_stage_08 → 0013_stage_07 → head`, single head
  `0021_stage_08` — PASS

All 43 IDs `REQ-I18N-001..042` plus `REQ-I18N-026A` are tracked as `IMPLEMENTED` with file:line and test
evidence in `docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md` and
`docs/10_implementation/STAGE08_REQUIREMENTS_CHECKLIST_LOCAL.md`; none are promoted to `VERIFIED` before the
repository's transverse qualification stage.

### Findings (external deep review, and the live-qualification defect)

All findings raised against candidate `f538105` are CLOSED against the current diff, each with dedicated
PostgreSQL/unit/Playwright coverage: intra-Guild Translation Group isolation, disabled-language delta
rejection, portable-artifact secret allowlisting, LANGUAGE_FILTERED/SCOPE_AND_LANGUAGE separation, the
Scope×Language structural planning lifecycle, member role reconciliation authority, provider capability
authority, provider partial-state lifecycle, Gateway `is_bot`/member-coverage drift tracking, business-intent
compilation (no client DSG), the real Stage06→05 clone pipeline, the real frontend ActionRegistry/Right Drag
wiring, and fail-closed safe technical-role cleanup.

The first real sandbox live qualification attempt (commit `9240cb1`) then surfaced one genuine code defect,
not previously caught by non-live tests or the first sandbox run: Stage08 managed-visibility channels
(`LANGUAGE_FILTERED` / `SCOPE_AND_LANGUAGE`) end up with a final overwrite state that denies `VIEW_CHANNEL`
to `@everyone` and allows it to the derived language/Scope×Language role, but never explicitly preserves
access for the DID control-plane bot itself. Sandbox Guild A masked this because its bot happens to hold
`ADMINISTRATOR` there (never granted by DID code, bypasses all overwrites); Guild B correctly has no
`ADMINISTRATOR`, so the freshly Stage06→05-cloned restricted channels denied the bot `VIEW_CHANNEL` — which,
by Discord's own implicit-denial rule, also made `MANAGE_CHANNELS` ineffective there — and the follow-up
Stage05 `DELETE_CHANNEL` cleanup preflight failed closed. Discord resolves permissions from the final
overwrite state, not write order, so the earlier grant-before-deny overwrite-ordering fix did not address
this: the desired graph simply never contained a grant for the bot at all.

Fixed in commit `592b94b`: `PortabilityService` augments the destination clone graph, for multilingual
clones only, with an explicit member-type `VIEW_CHANNEL` overwrite for the destination guild's own durable
`bot_identity()`, on every channel that carries a `VIEW_CHANNEL`-denying overwrite. It never grants
Administrator and never grants a human business-scope role — REQ-I18N-022 ("member-specific overwrites are
not the normal multilingual visibility strategy") still holds for human audience visibility; this is a
narrowly-scoped service-principal/control-plane exception required so DID keeps the ability to administer
its own managed channels. Regression:
`test_multilingual_clone_preserves_control_plane_bot_access_on_restricted_channel` in
`backend/tests/integration/test_stage06_postgres.py`, verified failing pre-fix and passing post-fix, proving
bot access, human denial, an allowed cleanup preflight, no Administrator, and no provider secret/binding
leakage. Re-qualification on a cleaned sandbox then PASSed completely (see Validation above).

No functional or security finding remains open.

### Guardrails

- no Discord structural mutation from frontend or FastAPI routers;
- Stage 05 plan/worker/governor pipeline remains the only mutation path;
- cache-first normal reads and tenant RLS invariants preserved;
- no secret, sandbox Discord ID or member PII committed;
- provider bot integration remains non-invasive and uses `MANUAL_CONFIGURATION_REQUIRED` when automation is unsafe;
- the Server Members Intent used by the live validator to prove technical-role cleanup safety is scoped to
  that sandbox validation only; the Stage08 core does not depend on a global `GUILD_MEMBERS` intent, and
  cleanup fails closed when member coverage is unavailable;
- the control-plane access grant on cloned restricted channels is a bounded service-principal exception,
  never Administrator, never a human business-scope role;
- PR intentionally remains Draft; no merge and no STAGE 09 work.
