# UI Redesign — Atomic Execution State

## Non-negotiable product goal

Primary objective: deliver the UI/UX redesign defined by:

- `SCREENSHOTS_ESQUISSE/Esquisse 1.png`
- `SCREENSHOTS_ESQUISSE/UI_REDESIGN_PHASES.md`

A backend/API-only implementation is not product-DONE. A feature is only DONE
when it is accessible from the UI, intention-first, visually consistent with
Esquisse 1, and covers loading/empty/error/CANNOT/UNKNOWN/BLOCKED states in
EN/FR/DE/ES.

## Active phase

Phase 4 — Roles / Permissions / Access Policies

Status: DONE

Branch: ui/complete-redesign

Phase baseline SHA: 8b77bb9 (feat(ui): add access policies workspace — first
Phase 4 reopening commit after the initial permissions socle)

Current product HEAD: 2f7b9d2 (fix(ui): keep context menus within viewport)

Current independently verified SHA: `2f7b9d2` (P4-UI-000 closure).
Phase 4 is complete. Do not start Phase 5 without an explicit instruction.

Session resumed: 2026-09-18 from checkpoint `04e4c8c`; P4-T014 was audited,
completed and independently revalidated on `ui/complete-redesign`.

## Allowed task statuses

TODO / IN_PROGRESS / DONE / BLOCKED / DEFERRED

## Rules

- Never redo a DONE task without evidence of regression.
- Every IN_PROGRESS task must contain NEXT EXACT ACTION.
- Every DONE task must contain evidence.
- Never leave critical state only in an AI conversation.
- Before stopping for any reason, update this file.
- UI acceptance is mandatory for product completion.
- No new phase, no new sub-phase label ("Lot A/B" is a commit-history label,
  not a phase). Always exactly 9 UI phases.

---

## Reconstructed history (already DONE before this session)

### P4-T001 — Policy foundations (generic tenant-scoped Policy aggregate)
Status: DONE
Purpose: Generic `Policy` aggregate so access rules stop being ad-hoc per-feature code.
Requirements: REQ-POL-002..005, 007..011, 027, 029..031, 035..039, 052, 053.
Implementation: Tenant-scoped `Policy` aggregate, stable UUID, versioned closed
registry `ACCESS_CONTROL` v1, lifecycle `DRAFT → ACTIVE → DISABLED → RETIRED`,
append-only `policy_versions`, RLS forced, CAS on revision/state, idempotent
create/activate/disable.
UI: none yet (backend-only lot, correctly not declared done for UI).
Files: `did/policies/registry.py`, `did/domain` policy aggregate, migration
`0036_ui_phase4`, `did/application/policies/service.py`, `api/policies.py`
(minimal CRUD/lifecycle), 5 policies capabilities.
Tests: 16 unit + 6 PostgreSQL real; Alembic round-trip 0036→0035→0036.
Commit: part of `41fa3ba feat(policies): add tenant-safe policy foundations`.
Known limitations: no resolver, no preview, no UI, no enforcement yet.

### P4-T002 — Deterministic Policy resolver
Status: DONE
Purpose: Single canonical decision engine (CAN/CANNOT/BLOCKED/UNKNOWN) for policies, with priority/specificity/inheritance/conflict rules.
Requirements: REQ-POL-001, 012..020, 024, 033, 034, 040, 047..049, REQ-UXN-010, REQ-UXN-011.
Implementation: `PolicyResolver` pure domain service; resource hierarchy
GUILD→LOGICAL_GROUP→CATEGORY→CHANNEL; subject hierarchy GUILD→ROLE→MEMBER/BOT;
priority field durable via migration 0037; ANY/ALL role conditions evaluate
full member role set; equal-rank/incomparable opposing effects → BLOCKED;
stale/incomplete → UNKNOWN with refresh/reconcile recommendation.
UI: read-only Explain route only, no screen yet.
Files: `did/policies/resolver.py`, `PolicyService.resolve_access()`, route
`POST /api/v1/guilds/{guild_id}/policy-resolution`, migration `0037_ui_phase4`.
Tests: 43 unit (permutation, priority/specificity, inheritance, exception,
composition, conflict matrix, ANY/ALL, drift, fail-closed) + 7 PostgreSQL;
Alembic round-trip 0037→0036→0037; mypy 167 modules.
Commit: `c02085e feat(policies): add deterministic policy resolver`.
Known limitations: no preview/plan, no UI.

### P4-T003 — Capability UNKNOWN root-cause fix (bot capability)
Status: DONE
Purpose: Stop showing an unexplained UNKNOWN for bot role-management capability.
Requirements: part of REQ-AP-BOT-004 / general fail-closed UX doctrine.
Implementation: Removed unnecessary `bots.audit` dependency from the minimal
operational bot-capability projection; UI distinguishes LOADING/ERROR/CAN/
CANNOT/UNKNOWN instead of collapsing everything into `?? 'UNKNOWN'`.
UI: Roles screen shows structured causes/remediation, EN/FR/DE/ES.
Files: dashboard capabilities projection, Roles screen capability helper.
Tests: 3 capability-checker + 2 API projection + 6 Roles screen mounted tests; typecheck/ESLint/Ruff/i18n.
Commit: `eaab623 fix(ui): explain role bot capability outcomes`.
Known limitations: none noted for this narrow fix.

### P4-T004 — Policy → Preview/Impact → canonical Plan
Status: DONE
Purpose: Let a DRAFT Policy be simulated and compiled into a real Plan without any parallel mutation path.
Requirements: REQ-POL-021, 022, 023, 026, 028, 044, 045, 046 (CONFORME); REQ-POL-050/051 (PARTIEL, documented).
Implementation: Preview compares current vs. proposed resolution via the same
`PolicyResolver`; impact counts with EXACT/BOUNDED/INCOMPLETE precision;
materializable effects compiled to DSG `OVERWRITE` nodes, then canonical
`PlanningService`/compiler/risk engine/preflight; Plan carries immutable
`POLICY` provenance (policy_id, revision, scope, fingerprint, correlation_id);
`PlanningService.recheck()` fuses Discord capability + Policy re-evaluation;
worker re-checks after `APPLYING` fencing; activation requires a
tenant-local VALIDATED+ Plan.
UI: none yet (backend-only lot).
Files: policy preview/plan service, `PlanningService.recheck()`, routes
`.../policies/{policy_id}/preview` and `.../plan`.
Tests: 117 unit + 8 PostgreSQL; Alembic 0038→0037→0038; Ruff/mypy targeted.
Commit: part of `e2e6013 feat(policies): connect previews to canonical plans`.
Known limitations: REQ-POL-050 missing full HTTP 403 proof; REQ-POL-051
missing full CI chain to audit/deactivation proof.

### P4-T005 — Policies workspace UI (catalog + simple/expert editor)
Status: DONE
Purpose: First real, intention-first UI surface for policies (not just backend).
Requirements: REQ-POL-006, 025, 032, 041, 042 (CONFORME); REQ-POL-043 deferred to Wizard lot.
Implementation: Dark-navy, progressive-disclosure "Politiques d'accès" nav
entry; 7 native policies catalog; custom policies creatable from native,
renamable, editable while DRAFT, duplicable, re-drafted from a known
revision (deletion intentionally NOT exposed — see P4-T017); simple mode
(target, cumulative role audiences, human intents); expert mode (id,
revision, priority, scope, conditions, effects, resolution); preview shows
before/after, gains/losses, members, roles, resources, conflicts, precision;
"Why this result?" calls Explain; "Prepare the plan" calls Policy→Plan then
redirects to Plans. No Apply.
UI: `frontend/src/features/policies/PoliciesScreen.tsx` + catalog.
Files: `features/policies/{PoliciesScreen.tsx,catalog.ts}`, localization
`phase4PoliciesCatalog.ts`.
Tests: 57 backend + 5 unit catalog/UI + 3 Playwright (axe on #main) + typecheck/lint/i18n EN-FR-DE-ES/Ruff/OpenAPI.
Commit: `8b77bb9 feat(ui): add access policies workspace`.
Known limitations: REQ-POL-043 (Wizard-created policy) not yet closed; no
deletion; no favorites; no context-menu entry point yet.

### P4-T006 — Generic Wizard core + "Configure access to a space" assistant
Status: DONE
Purpose: Reusable Wizard shell (for Phase 4 now, Phase 6/7 later) + first real assistant so a non-Discord-expert can grant access end-to-end.
Requirements: REQ-WIZ-001..010, 013, 014, REQ-POL-043, REQ-PERMX-010 (all → CONFORME).
Implementation: `features/wizards/core/` = pure reducer
(`createWizardReducer`, NEXT/BACK/GOTO/RESET, furthestIndex, dependent-answer
invalidation), `useWizard` hook, `WizardShell` presentation, `RoleMultiSelect`
(managed roles visible-but-disabled with explanation, suggested-role block,
"+ Create a role" as local-only proposal). "Configure access to a space"
assistant: Target → Intent → Roles → Conflicts(informative) → Adjust →
Preview/Impact → Plan. Missing role handled without leaving the flow, blocked
with explained CANNOT rather than a mysteriously disabled button, until a real
role exists. Draft creation is explicit and disclosed ("Discord has not been
modified" banner); "Prepare the plan" only, never "Apply".
UI: `/guild/:id/wizards` catalog screen (2 entries: available assistant +
explicitly-unavailable "Build a template" for Phase 6) +
`features/wizards/accessSpace/AccessSpaceWizardScreen.tsx`.
Files: `features/wizards/core/{reducer,useWizard,WizardShell,RoleMultiSelect}.tsx`,
`features/wizards/{catalog.ts,AssistantsScreen.tsx,wizards.css}`,
`features/wizards/accessSpace/AccessSpaceWizardScreen.tsx`,
`features/policies/{targets.ts,errors.ts}` (extracted, shared),
`localization/phase4WizardCatalog.ts`, `e2e/phase04-wizard-access-space.spec.ts`.
Tests: 10 unit (reducer 6, RoleMultiSelect 2, cancellation 2) + 2 Playwright
(nominal with axe on #main; missing-role/CANNOT path) + full frontend suite
+ typecheck/lint/i18n rerun without regression (1 pre-existing unrelated
failure in StructureScreen.test.tsx, reproduced identically on HEAD before
this lot).
Commit: `6ea84f1 feat(wizards): add generic Wizard core and access-space assistant`.
Known limitations: none declared for this lot's own scope.

### P4-T007 — Access Matrix + bulk policy planning
Status: DONE
Purpose: Let an admin see access at a glance across roles × resources and act on many resources at once, without a second resolution engine.
Requirements: REQ-AP-MAT-001..006, REQ-AP-BULK-001..003 (CONFORME). REQ-AP-BULK-004 (SHOULD) left open — see P4-T018.
Implementation: `/guild/:guildId/matrix`; single bounded batch request
(50 roles × 150 resources max) to
`POST /api/v1/guilds/{guild_id}/access-matrix/resolve`; batch service loads
Guild snapshot/Policies/logical groups once, delegates every cell to
`PermissionEvaluator` (Discord-effective) + `PolicyResolver` (intent/
inheritance/exception/conflict); stale/incomplete → UNKNOWN synthesis, never
a false "No access". Filters: All/Conflicts/Exceptions/Private zones.
Keyboard-accessible cells; click opens intent editor first, Discord details
folded behind a secondary action. Header checkboxes multi-select
categories/channels; catalog only offers Policies compatible with at least
one target; incompatible resources listed with reason; two bounded batch
HTTP commands (`policies/bulk-preview`, `policies/bulk-plan`) avoid N×M calls;
common tag `bulk-operation:*`; deterministic idempotency-derived child keys.
UI: Access Matrix screen with grid, filters, bulk selection panel.
Files: `access-matrix` backend service/route, `PolicyPlanningService`
bulk-preview/bulk-plan, frontend Matrix screen + bulk selection UI.
Tests: 13 backend (`test_phase04_access_matrix.py`) + 30 existing Policy
foundation/planning tests + 4 frontend unit + 2 Playwright (incl. refetch +
axe) + Ruff/mypy/TypeScript/ESLint/i18n EN-FR-DE-ES/OpenAPI/git diff --check.
Commit: `e73ad4c feat(policies): add access matrix and bulk planning`.
Known limitations: REQ-AP-BULK-004 open (no context-menu entry for bulk
policy actions on a mixed category/channel selection); existing canonical
context menu only knows a structural "move channels" bulk action.

### P4-T008 — Advanced access families: voice, threads, reactions, mentions, bots
Status: DONE
Purpose: Extend the intention-first catalog beyond visibility/writing to voice, threads, reactions, mentions and bot access, still through the single PolicyResolver.
Requirements: REQ-AP-VOC-001/010/020/021/030, REQ-AP-THR-001,
REQ-AP-MEN-002/003/004, REQ-AP-BOT-001..004 → CONFORME. REQ-AP-REA-001 and
REQ-AP-MEN-001 → covered with an explicit, honest Discord-limitation caveat
(cannot fully separate @everyone/@here; ADD_REACTIONS deny doesn't block
reacting with an already-present emoji). REQ-AP-WRI-022 and REQ-AP-PRS-013 →
PARTIAL (options exist, no complete preset, no reply-specific control yet —
see P4-T020).
Implementation: `ACCESS_CONTROL` v1 contract extended with intents
MANAGE_VOICE, CREATE_THREAD, PARTICIPATE_THREAD, REACT,
MENTION_EVERYONE_HERE, granular bot intents READ_HISTORY/SEND/MANAGE_CHANNEL,
and closed condition BOT_MATCH. `PolicyResolver` produces the Discord
translation (discord_permissions, allow/deny decimals + diagnostics)
consumed directly by DSG/Plan compilation — no parallel authorization
calculator. 8 new native policies. Voice-private has an explicit,
off-by-default staff toggle (no name-based inference). Reaction modes:
Everyone/Only.../Nobody. Mentions: Guild default + category/channel
exception. Bot capability check reuses `BotCapabilityChecker`, never
recommends ADMINISTRATOR.
UI: 8 new catalog entries in Policies + Matrix (only natives configurable
without losing information) + Wizard (same compatibility rule).
Files: registry/resolver/permissions/capabilities, Policy service/planning,
Stage04/Policies routes, catalog/screen, matrix/Wizard, types/OpenAPI, i18n.
Tests: 127 backend targeted + mypy/Ruff + 11 Vitest + i18n EN-FR-DE-ES + 3
Playwright (voice-private, Guild-default+mention exception, bot minimal with
CANNOT/UNKNOWN).
Commit: `65d3e0f feat(policies): add advanced access families`.
Known limitations: REQ-AP-WRI-022/PRS-013 partial (see P4-T020);
REQ-AP-PRS-001/010/011/012 (composed presets) not attempted this lot (see
P4-T011).

### P4-T009 — Named audiences (Staff/Confirmed), ANY/ALL/NOT, blacklist exceptions
Status: DONE
Purpose: Replace ad-hoc per-policy role guessing with guild-level persisted
"Staff"/"Confirmed member" definitions; add "has A but not B"; explain and
allow accepting a blacklist bypass as a documented exception.
Requirements covered: REQ-AP-ZONE-010/011/012, REQ-AP-ZONE-020/021/022/023,
REQ-AP-ZONE-040/041, REQ-AP-ZONE-060/061, REQ-AP-VIS-011/012/013,
REQ-AP-VIS-017, REQ-AP-WRI-011 → CONFORME.
The former P4-T009 limitation on `REQ-AP-ZONE-051/052` is closed by P4-T015:
fresh member-role Gateway projection plus locked-Policy reconciliation
regenerates the exact per-member overwrite Plan for ALL. No combination role
is needed. `REQ-AP-ZONE-030/031/032` benefits from the same reconciler path.
The former REQ-AP-VIS-004 limitation is closed by P4-T016: Policy-vs-Discord
mismatches now name role/base permission, ADMINISTRATOR/owner, raw
role/member/everyone overwrite, implicit denial and category inheritance in
one explanation shape.
Still open, not attempted this lot: REQ-AP-ZONE-001/002/003 (public zone +
linked staff space via Logical Group — see P4-T010), REQ-AP-PRS-*
(composed presets — see P4-T011). REQ-AP-CFL-005 is explicitly DEFERRED by
P4-T016; REQ-AP-CFL-006 is covered.
Implementation: Reuses Stage04 `visibility_scopes` +
`scope_membership_rules` (migration 0006) as-is — zero new tables for
Staff/Confirmed. Staff = scope_type STAFF, scope_key 'staff'. Confirmed =
scope_type CUSTOM, scope_key 'confirmed_member'. New condition kind
`ROLE_EXCLUDE` in the closed registry (mirrors existing RoleAudience.EXCLUDE
semantics, fail-closed UNKNOWN on incomplete data). "A but not B" =
`[ROLE_MATCH(ANY,[A]), ROLE_EXCLUDE(ANY,[B])]` (already-ANDed tuple, no new
connective). ANY/ALL reuse existing INCLUDE/ANY and INCLUDE/ALL audiences;
ALL is compiled per-real-member at Plan generation
(`PolicyPlanningService._compile_graph`). Newcomer area
(`createNewcomerAreaDefinitions()`) composes 1-2 independent Policies tied by
tag `newcomer-area:<id>`, using `PolicyResolver._maximal` OR-composition — no
new resolution capability. New pure module
`did/policies/conflict_explanations.py`: `explain_conflicts()` (exact
role(s) that made the winning Policy win) and `find_blacklist_regrants()`
(detects the common silent case: an EXCLUDE-audience Policy correctly
evaluates CONDITION_FALSE for a member who still has the resource via an
independent Policy — no PolicyConflict is emitted by the resolver itself, so
this recoups CONDITION_FALSE EXCLUDE contributions against the winning
Policy). `PolicyService.accept_exception()` records the accepted exception in
Policy metadata (`tags: exception_accepted:<policy_id>`) as an audited
`ANNOTATE` revision — first mutation path for an already-ACTIVE Policy;
migration `0039_ui_phase4_policy_exception_annotations.py` widened the
`policy_versions.change_kind` CHECK constraint to allow ANNOTATE (no new
table). `PolicyService.resolve_access_explained()` (additive, doesn't modify
`resolve_access()`) enriches `POST /policy-resolution` with
`conflict_explanations`/`blacklist_regrants`.
UI: inline named-audience panel in the simple editor for
staff_only/confirmed_members_only (shows current roles, unapplied
name-hint suggestion, mini role editor + "Save this definition"); 3 new
catalog natives (at_least_one_role, all_roles_required, role_but_not_role)
with concrete human-language examples; extended explanation panel naming the
exact bypass role with "Accept this exception" button.
Files: `did/policies/{registry.py,resolver.py,conflict_explanations.py}`,
`did/application/policies/service.py` (accept_exception,
resolve_access_explained), `did/infrastructure/policies_repository.py`
(annotate), `api/policies.py` (accept-exception, enriched policy-resolution),
migration `0039`, `frontend/src/features/policies/audiences.ts`,
`catalog.ts`, `PoliciesScreen.tsx`, `api/types.ts`,
`localization/phase4PoliciesCatalog.ts`, `e2e/phase04-zones-and-conflicts.spec.ts`.
Tests: 47 resolver + 5 conflict_explanations + 21 policy foundations backend
(incl. new accept-exception endpoint) + 11 real PostgreSQL integration
(3 new: CAS revision, tenant A/B isolation) — all PASS with migration 0039
applied then verified reversible; frontend strict typecheck + i18n
EN/FR/DE/ES structurally complete + 15 targeted Vitest + anti-literal guard;
Playwright: 3 new (Staff end-to-end; Confirmed members + live
re-evaluation; blacklist bypass → exact cause → accepted exception) + 14
existing Phase 4 journeys re-verified without regression — 0 APPLY calls.
Commit: `80c1535 feat(policies): named audiences, ANY/ALL/NOT zones, and blacklist exceptions` (HEAD at session start).
Known limitations: see "still open" list above — carried into P4-T010,
P4-T011, P4-T014/T015, P4-T016.

---

## Open backlog (this session must work through this list, atomically)

Priority order per master rule: **visual/UX correctness first**, then MUST
requirements, then SHOULD requirements. Visual audit tasks (P4-UI-*) are
added below once the real running frontend has been inspected against
Esquisse 1.

### P4-UI-000 — Visual acceptance pass (Roles/Permissions/Policies/Matrix/Wizard)
Status: DONE
Purpose: Compare the real running UI for all Phase 4 screens against
`Esquisse 1.png`, at the sizes required by the closure checkpoint, and log
genuine defects as atomic P4-UI-* tasks. Do NOT log cosmetic nitpicks that
aren't real defects.
Method used: a throwaway Playwright spec (`frontend/e2e/_visual_audit.spec.ts`,
deleted after use, not committed — recreate the same way if more screens
need screenshots) that mocks the same backend routes the existing
`phase04-*.spec.ts` harnesses use (see those files for the exact JSON
shapes) and screenshots each route at 1440x900 and 390x844 via
`page.screenshot({fullPage:false})`. Use `fullPage:false` — `fullPage:true`
produces a stitching artifact that duplicates the fixed header/sidebar and
is NOT a real bug (confirmed by comparing against a viewport screenshot
before logging anything).
Already covered this session: Roles, Permissions, Policies (list + target
selected + editor), Access Matrix, Wizards catalog, Wizard access-space
step 1 — each at desktop width, and Policies + Matrix at 390px mobile.
The P4-T014 locked/drift compliance panel was subsequently inspected at
1440x900 and 390x844: locked state, drift cause, automatic repair,
intervention, Repair/Accept actions and folded Discord details remain legible
and produce no page-level horizontal overflow.
The P4-T016 observable-conflict/remediation panel was also inspected at
1440x900 and 390x844. Cause, affected member/resource, collateral impact and
separate-Plan warning remain legible without page-level overflow; the mobile
heading/badge wrapping and text contrast defects found during inspection were
fixed, then the panel passed axe.
The P4-T017 deletion-strategy dialog was inspected at 1440x900 and 390x844.
Dependency counts, immutable-history warning, access impact and all strategy
descriptions remain readable in the internally scrollable modal; the page has
no horizontal overflow. A native modal `dialog` keeps the background inert,
and the Playwright scenario passes axe.
The P4-T012 temporary-access surface was inspected in real Chromium at
1440x900 and 390x844. Duration shortcuts, custom date, durable scheduled
state, expiry, queued/removal copy and intervention treatment remain readable.
The mobile page has exact `scrollWidth===clientWidth===390`; the off-canvas
sidebar is hidden, opens, and closes correctly, and the panel passes axe.
The final pass inspected the remaining observable conflict/remediation,
Named Audience inline editor, expert permission diagnosis, Matrix cell editor,
composed preset, single-resource context menu and bulk context menu at
1440x900 and 390x844. Their actionable content, hierarchy and controls remain
readable and consistent with Esquisse 1. Temporary screenshot instrumentation
and artifacts were removed after inspection.
Defects found and FIXED (see P4-T021, done, commit 2ce541f):
- body had `min-width:1180px` (src/shared/redesign.css) — forced horizontal
  scroll on literally every screen below 1180px, defeating every existing
  per-component responsive media query. Removed.
- several `@media` breakpoints collapsed grids with bare `1fr` instead of
  `minmax(0,1fr)`, so content min-size still blew out the track even after
  "collapsing to one column" (policy-layout/policy-target-panel in
  policies.css; roles-layout/permissions-layout/access-form-grid/
  role-meta-grid/overwrite-preview/role-action-grid in phase4-access.css;
  matrix-before-after in matrix.css). Fixed throughout.
- sidebar/topbar had zero mobile collapse behavior at all (no hamburger, no
  off-canvas). Added nav-toggle + off-canvas sidebar + backdrop + topbar
  wrap + connection-label visual collapse <480px (kept in a11y tree).
- Wizard step pills showed the step number twice ("1 1 · Target") because
  the i18n strings embedded their own number on top of WizardShell's own
  numbered badge. Stripped the redundant prefix in all 4 locales.
- the shared fixed-position context menu trusted the raw pointer coordinates,
  so a long single-resource menu could extend below a 390x844 viewport. The
  shared Menu now measures and clamps itself to an 8px viewport inset on mount
  and resize, caps its dimensions, and scrolls internally when necessary.
  A permanent Chromium regression asserts its complete bounding box and zero
  page-level overflow (`2f7b9d2`).
Verified clean after fix: scrollWidth===clientWidth===390 at mobile on both
Policies and Matrix (Matrix's own table still scrolls internally within its
own container, which is the explicitly allowed exception, not a page-level
scroll). All 17 Phase 4 Playwright specs still green, typecheck/i18n/lint
clean (3 pre-existing unrelated lint errors in untouched files, 1
pre-existing unrelated Vitest failure in StructureScreen.test.tsx — both
confirmed pre-existing via `git status` showing those files untouched).
Evidence: every screen in the closure checkpoint's 10-item minimum list was
screenshotted and compared. The final closure run passes all 99 frontend unit
tests and all 44 selected Phase 3 Structure + Phase 4 Chromium scenarios;
TypeScript/Vite, ESLint, i18n and diff checks pass. The earlier P4-T012 closure
also passes 145 targeted backend tests and 16 real PostgreSQL/runtime
integrations. No Discord live APPLY was run.
Commit: `2f7b9d2 fix(ui): keep context menus within viewport` (pushed).

### P4-T021 — Fix visual defects found in first acceptance pass
Status: DONE
Purpose: Fix the 3 real defects found by P4-UI-000's first pass before doing
any further functional backlog work, per the master rule that visual
correction is prioritized over adding secondary functions.
Requirements: general "responsive raisonnablement" / visual consistency
closure criteria for Phase 4 (not a REQ-AP-* item; a UI-quality gate).
Implementation: see P4-UI-000 above for the full list; in short: removed
`body{min-width:1180px}`, fixed 6 media-query rules from bare `1fr` to
`minmax(0,1fr)`, added a real off-canvas mobile sidebar with hamburger
toggle to AppShell, fixed wizard step-title number duplication in all 4
locales.
UI: Roles/Permissions/Policies/Matrix/Wizards all now usable at 390px
without page-level horizontal scroll; wizard progress pills show each
number once.
Files: `frontend/src/app/AppShell.tsx`, `frontend/src/shared/redesign.css`,
`frontend/src/shared/phase4-access.css`, `frontend/src/features/policies/policies.css`,
`frontend/src/features/matrix/matrix.css`, `frontend/src/localization/phase2Catalog.ts`
(shell.openNavigation/closeNavigation keys, 4 locales),
`frontend/src/localization/phase4WizardCatalog.ts` (step title fix, 4 locales).
Tests: typecheck PASS, i18n:check PASS, full Vitest suite 75/76 passed (1
pre-existing unrelated StructureScreen.test.tsx failure, confirmed
pre-existing — file untouched by this change), all 17 Phase 4 Playwright
specs PASS, manual overflow verification (scrollWidth===clientWidth===390
at mobile on Policies and Matrix).
Commit: `2ce541f fix(ui-phase4): fix mobile overflow, off-canvas nav, and wizard step duplication`.
Known limitations: only Roles/Permissions/Policies/Matrix/Wizards-catalog/
Wizard-step-1 were actually screenshotted; other Wizard steps and the
conflict panel/Named Audience editor still need a look (tracked back in
P4-UI-000's NEXT EXACT ACTION). The 3 pre-existing lint errors and 1
pre-existing test failure were NOT fixed — out of scope (unrelated files,
not touched by this task).

### P4-T010 — Zone publique + espace staff associé (Logical Group link)
Status: DONE
Purpose: REQ-AP-ZONE-001/002/003 — let an admin declare "this public space
has an associated staff space" using the existing Stage04 `logical_groups`
primitive, never a fake Discord sub-category.
Requirements: REQ-AP-ZONE-001/002/003 → CONFORME.
Implementation: reused the Stage04 `logical_groups` CRUD API as-is (full
create/read/update/delete already existed, `semantic_role` on a group
resource is a free-form ≤64-char string, so no backend change was needed).
Two existing resources get tagged `did-zone-public` / `did-zone-staff`.
New pure module `frontend/src/features/policies/zones.ts`:
`findPairedZones()` (identifies groups with both tags present),
`zoneResourceLabel()` (resolves a resource to its human target label),
`slugifyZoneName()`, `useCreatePairedZone()` (POST + invalidate). A
collapsible `<details className="zone-panel">` section on PoliciesScreen
(placed right after the target picker, before the catalog/editor) lists
existing pairings with an explicit "DID grouping, not a Discord structure"
badge (REQ-UXN-004) and a form to create a new one by picking two existing
CATEGORY/CHANNEL targets from the same target list already used everywhere
else. "Apply Staff only here" on the staff side jumps straight into the
existing `staff_only` native policy targeted at that specific resource
(REQ-AP-ZONE-003: each side keeps its own independent policy, the group
itself is never used as a policy target for this).
UI: `PoliciesScreen.tsx`, new `.zone-panel`/`.zone-list`/`.zone-card`/
`.zone-side`/`.zone-form` styles in `policies.css`, screenshotted and
visually consistent with the rest of the workspace (dark navy card,
progressive disclosure, badges).
Files: `frontend/src/features/policies/zones.ts` (new),
`frontend/src/api/types.ts` (extended `LogicalGroup` with `resources`, new
`LogicalGroupResource` type), `frontend/src/features/policies/PoliciesScreen.tsx`,
`frontend/src/features/policies/policies.css`,
`frontend/src/localization/phase4PoliciesCatalog.ts` (12 new keys × 4 locales).
Tests: 9 targeted Vitest unit tests (`zones.test.ts`, including a real bug
caught mid-implementation — see Known limitations), 1 Playwright E2E
(`phase04-zones-pairing.spec.ts`: nominal create flow, zero APPLY calls,
persists across `page.reload()`), typecheck/lint/i18n clean, full Vitest
suite and existing Phase 4 Playwright specs green (see P4-T021-style
doctrine — no unrelated regression).
Commit: `0ec4a55 feat(policies): link a public zone with its staff space (REQ-AP-ZONE-001/002/003)`.
Known limitations: while writing the Playwright test, found and fixed a
real edge case in `zoneResourceLabel()` — a resource with a missing/null id
could accidentally resolve to the GUILD target (whose `scopeId` is also
`null`), silently showing "Guild A" instead of the real resource or a clear
"not found" state. Fixed (`id === null` now short-circuits to `null`) and
covered by a dedicated unit test. No other known gaps for this task's own
scope; REQ-AP-CFL-005/006 (role optimization) and REQ-AP-PRS-* (composed
presets) remain separate open tasks below.

### P4-T011 — Composed presets: Confidentiel, Salon d'annonces, Zone support
Status: DONE
Purpose: REQ-AP-PRS-001, 010-013, 020-022. A preset must show its sub-rules
before Plan (no opaque alias) and must not be offered if its primitives
aren't real yet.
Requirements: REQ-AP-PRS-001/010/011/012/020/021 → CONFORME. REQ-AP-PRS-013
(SHOULD) → CONFORME for Announcement channel (reactions/threads options
present). REQ-AP-PRS-022 (SHOULD) → N/A, documented: grepped the entire
product for "ticket", nothing exists, so the option is deliberately not
offered rather than being a fake control.
Implementation: `frontend/src/features/policies/presets.ts` (new, pure
module) composes each preset from the SAME building-block helpers the
native catalog itself uses (`whitelist()`, `modeEffects()` — exported from
`catalog.ts`, previously module-private) into 1-4 independent DRAFT
`PolicyDraftDefinition`s sharing one `preset-group:<uuid>` tag, exactly the
`createNewcomerAreaDefinitions()` pattern from P4-T009. No new
PolicyResolver capability, no new endpoint, no bulk-mutation path — each
sub-rule becomes an ordinary Policy findable individually afterward in
"Custom policies". Confidential = visibility whitelist + management
whitelist + mention block + thread restriction (each independently
toggleable, only emitted if its audience is non-empty except the
always-meaningful mention block). Announcement channel = writer whitelist
+ optional reaction mode + optional thread mode — deliberately NEVER emits
a VIEW effect (REQ-AP-PRS-012, tested). Support zone = optional visibility
whitelist (OPEN by default) + optional writer whitelist (EVERYONE by
default) for a chosen support-group audience.
UI: third collapsible `<details className="preset-panel">` section on
PoliciesScreen (after the zone panel, before the catalog/editor). Selecting
a preset opens its specific config form (role-picker toggles reused from
existing `.policy-role-picker` pattern, mode selects reusing existing
`policies.mode.*` i18n). A live "Sub-rules this preset will activate" list
(pure `confidentialSubRules()`/`announcementSubRules()`/`supportZoneSubRules()`
functions) updates as the admin configures options, BEFORE any policy is
created — satisfies REQ-AP-PRS-001 literally, confirmed by a Playwright
assertion that the list is empty until roles are chosen. "Create the preset
policies" issues one POST per activated sub-rule sequentially, then
invalidates the policies query so all of them appear in Custom policies.
Files: `frontend/src/features/policies/presets.ts` (new),
`frontend/src/features/policies/presets.test.ts` (new),
`frontend/e2e/phase04-presets.spec.ts` (new),
`frontend/src/features/policies/catalog.ts` (exported `whitelist`/
`modeEffects`/`audience`, previously private),
`frontend/src/features/policies/PoliciesScreen.tsx`,
`frontend/src/features/policies/policies.css`,
`frontend/src/localization/phase4PoliciesCatalog.ts` (~35 keys × 4 locales).
Tests: 12 targeted Vitest unit tests (sub-rule activation logic + DRAFT
composition, all three presets, including "never emits VIEW" for
Announcement and "creates nothing when everything is off" for Confidential),
1 Playwright E2E (live sub-rule preview, 4 POST calls sharing one
preset-group tag, zero APPLY, all 4 created policies visible afterward).
Typecheck/lint(3 pre-existing unrelated errors, unchanged)/i18n clean, full
Vitest suite 96/97 (1 pre-existing unrelated failure), 16 existing Phase 4
Playwright specs re-verified green.
Commit: `2de80e5 feat(policies): composed presets — Confidential, Announcement, Support zone`.
Known limitations: none for this task's own declared scope beyond the
documented REQ-AP-PRS-022 N/A. Not yet screenshotted at mobile width — add
to P4-UI-000's remaining screens list.

### P4-T012 — Temporary access (grant until date/duration)
Status: DONE
Purpose: REQ-AP-TMP-001..006. Full implementation, not a frontend-only
simulation — this is explicitly forbidden ("ne jamais simuler l'expiration
uniquement côté frontend").
Requirements: REQ-AP-TMP-001 (grant until date/duration), 002 (bot/service
drives expiration + produces the removal operation), 003 (durable, survives
restarts), 004 (expiry+removal audited), 005 (failed removal → actionable
state, never shown as succeeded), 006 (SHOULD — 1h/24h/7d/until shortcuts +
custom date).
Implementation: migration `0042_ui_phase4` adds the tenant-scoped,
forced-RLS `policy_temporary_access` schedule with deadline, lifecycle,
retry count, lease fencing, canonical removal Plan reference and timestamps.
The normal scheduler process claims due rows across tenants with
`FOR UPDATE SKIP LOCKED`, bounded exponential retry and a terminal
`INTERVENTION_REQUIRED` state after repeated preparation failures. A restart
resumes either the schedule or its already-attached Plan.
Removal reuses `PolicyPlanningService.create_disable_plan`, normal Plan
validation/confirmation, `PlanningService.apply` queueing and the existing
`ApplyPlanExecutor`; the scheduler never calls Discord and the frontend never
calls APPLY. The reserved system actor is accepted only for a Policy-origin
`DISABLE` Plan whose tamper-checked metadata contains
`temporary_access=true`. Worker completion projects `REMOVED` only for the
canonical success states and projects every terminal failure to an actionable
state. Schedule, cancellation, retry/failure and successful removal are
audited durably.
API/UI: tenant-authorized GET/PUT/DELETE endpoints expose the persisted state.
The ACTIVE Policy detail offers 1h/24h/7d shortcuts, a custom local date/time,
reschedule/cancel, localized expiry/status badges, queued/running copy,
intervention reason and a link to the removal Plan. The interface is complete
in EN/FR/DE/ES and makes no optimistic frontend-only expiry claim.
Files: `0042_ui_phase4_temporary_access.py`, Policy domain/service/repository,
`application/policies/temporary_access.py`, runtime worker/scheduler wiring,
Policy API/OpenAPI, `PoliciesScreen.tsx`, styles/catalog and targeted tests.
Evidence: 145 targeted backend unit tests, 15 real PostgreSQL Policy
integrations plus the real scheduler-process integration, full frontend suite
99/99 and 16 Policies/Presets Chromium scenarios all pass. Ruff, mypy,
TypeScript/Vite, ESLint, i18n, OpenAPI and diff checks pass. Real desktop and
390px mobile Chromium inspection is accepted; axe has no serious/critical
finding and mobile has no page overflow.
Commit: `76396fa feat(policies): add durable temporary access` (pushed).
Known limitations: no live Discord APPLY was run; the implementation is
instead proven through the canonical worker boundary and real persistence.

### P4-T013 — Reapply category master policy to exceptions
Status: DONE
Purpose: REQ-AP-INH-003 — "réappliquer la politique de catégorie" on a local
exception, always via Preview → Plan.
Requirements: REQ-AP-INH-003 → CONFORME (single-target; see Known
limitations for the "multiple exceptions at once" variant).
Implementation: extended the EXISTING DRAFT-only Policy preview/plan
machinery (`PolicyPlanningService`) with a symmetric "disable" simulation
instead of a second pipeline. New `PreviewSimulation` enum (ACTIVATE|DISABLE)
controls whether `_preview_loaded()`'s proposed policy set forces the
target Policy ACTIVE (existing activate flow, byte-for-byte unchanged) or
excludes it entirely (new disable flow) — both share the identical
candidate/resolve/diff/compile-to-DSG code (`_compile_graph` is fully
generic, doesn't care why a resolution changed). `preview_disable()` and
`create_disable_plan()` reuse `_create_plan_from_preview()` verbatim.
`PolicyService.disable()` gained an optional `disable_plan_id`, validated
via the EXISTING `assert_activation_plan()` repository method (same SQL
`activate()` already relies on — no new query, no new migration, since the
check is generic: it just verifies a VALIDATED+ Plan tied to that exact
Policy+revision, regardless of activate-vs-disable direction).
Bug caught mid-implementation by the REAL PostgreSQL integration test (not
by unit tests, which mock around it): `evaluate_plan()` — the canonical
worker-side preflight recheck used by `PlanningService.recheck()`,
separate from the preview path — hardcoded "force target Policy ACTIVE"
for every Policy-provenance Plan, which would have wrongly rejected every
disable-plan with `preflight.policy_resolution_changed` (since the Policy
is still really ACTIVE at Plan-creation time for a disable, exactly the
mirror image of activate's still-DRAFT state at its own Plan-creation
time). Fixed by stamping which simulation a Plan represents into its own
tamper-checked provenance metadata (`simulate: "ACTIVATE"|"DISABLE"`) and
reading it back in `evaluate_plan()` to pick the matching evaluated-policy
set AND the matching terminal-state expectation (require DISABLED, not
ACTIVE, for a disable-plan's post-apply recheck).
UI: a "Reapply category policy" action appears next to Save
draft/Duplicate/History for any ACTIVE, CHANNEL-scoped custom Policy whose
parent category also carries an ACTIVE Policy (computed client-side from
already-fetched structure+policies data, no new read endpoint). Opens a
preview/impact panel reusing the exact same `.policy-impact-grid`/
`.policy-preview-entries` markup as the DRAFT preview, then "Prepare the
plan", then an explicit "Confirm: reapply the category policy" step —
nothing is disabled until that final explicit click.
Files: `backend/src/did/application/policies/planning.py` (PreviewSimulation,
preview_disable, create_disable_plan, evaluate_plan fix),
`backend/src/did/application/policies/service.py` (disable_plan_id param),
`backend/src/did/api/policies.py` (PolicyDisable model, disable-preview and
disable-plan routes, disable route now has its own handler instead of the
generic `_transition` helper), `backend/tests/unit/test_phase04_policy_planning.py`
(+4 tests), `backend/tests/integration/test_phase04_policies_postgres.py`
(+1 real end-to-end test — the one that caught the evaluate_plan() bug),
`frontend/src/features/policies/PoliciesScreen.tsx`,
`frontend/src/localization/phase4PoliciesCatalog.ts` (6 keys × 4 locales),
`frontend/openapi.json`/`openapi.d.ts` (regenerated),
`frontend/e2e/phase04-reapply-category-policy.spec.ts` (new).
Tests: 4 new backend unit tests + 1 new real PostgreSQL integration test,
Ruff/mypy clean, full backend Phase 4 policy suite green (84 unit + 12
integration), OpenAPI regenerated and checked, frontend
typecheck/lint(3 pre-existing unrelated errors)/i18n clean, full Vitest
suite (96 passed / 1 pre-existing unrelated failure), all 20 Phase 4
Playwright specs green (1 new).
Commit: `c21482f feat(policies): reapply category master policy to a channel exception (REQ-AP-INH-003)`.
Known limitations: implemented for a single target policy per action, not
literal multi-select ("une ou plusieurs" in the requirement text is
satisfied by "one", but "several at once" isn't built — would need a
bulk variant of disable-preview/disable-plan mirroring the Matrix's
bulk-preview/bulk-plan pattern; not attempted here, low priority since the
single-target flow already closes the MUST requirement). Docker/Postgres
test env (compose.test.yaml) was spun up locally for this task's
integration test and torn down afterward — future sessions must repeat
`docker compose -f compose.test.yaml up -d --wait` +
`DID_DATABASE_ADMIN_URL=...127.0.0.1:55432/did_test alembic upgrade head` +
`DID_RUN_INTEGRATION=1 DID_DATABASE_URL=...did_app...` before any
PostgreSQL integration test will run (see NEXT EXACT ACTION notes in the
handoff section for the exact commands — the default env var name is
`DID_DATABASE_ADMIN_URL`, NOT `DID_DATABASE_URL`, for alembic itself; this
cost real time to discover and is worth not rediscovering).

### P4-T014 — Locked policy / drift / reconciler
Status: DONE
Purpose: REQ-AP-LOCK-001..006 — the largest remaining architectural piece.
Checkpoint commit: `04e4c8c wip(phase4): checkpoint locked policy reconciler`.
Completion commit: `1eeb855 feat(policies): complete locked policy reconciliation`.
Implementation:
- migration `0040_ui_phase4_policy_lock.py` and persisted `Policy.locked`;
- lock/unlock application service and HTTP routes;
- desired Policy versus observed Discord drift detection, drift-preview and
  drift-plan routes;
- `PolicyPlanningService` REASSERT simulation, compiled through the existing
  DSG/Plan pipeline;
- external Gateway channel/role/member changes durably coalesce the existing
  `RECONCILE_STRUCTURE` job; expected Plan events are excluded to avoid loops,
  and the adaptive scheduler remains the periodic lost-event safety net;
- `PolicyReconcilerService` creates/confirms/queues only a canonical Policy
  Plan. The normal worker, workload governor, final preflight, mutation adapter
  and post-verification remain the sole Discord mutation path;
- automatic repair is restricted to locked Policies and uses explicit
  `auto_reconcile` provenance plus a closed internal actor shape. Unlocking
  before execution fails the final preflight closed;
- `repaired` is recorded only after the worker has durably finalized a
  verified-success Plan; terminal failure records `intervention_required`;
- exact unlocked-drift exceptions are fingerprinted, revisioned and audited;
- fail-closed handling for incomplete member inventories (a defect found and
  fixed while exercising the real integration path);
- Policies UI shows a prominent lock and honest compliance state, human drift
  causes, unlocked Repair/Accept-exception actions, locked automatic-repair
  and intervention states; raw Discord permissions stay secondary/collapsed;
  all visible copy is present in EN/FR/DE/ES.
Evidence:
- 31 targeted backend unit tests PASS;
- 16 real PostgreSQL Policy/reconciler integration tests PASS, including an
  external Gateway event through durable job creation and an actually executed
  canonical worker Plan before the `repaired` annotation;
- Ruff and targeted mypy PASS;
- frontend typecheck, i18n scan/catalog tests, OpenAPI snapshot/check and
  targeted ESLint PASS;
- 9 targeted Playwright scenarios PASS, including axe, lock/unlock, exact
  exception, unlocked Repair with zero APPLY, and intervention-required;
- desktop/mobile visual inspection against Esquisse 1 PASS as recorded in
  P4-UI-000. No Discord live APPLY was run.

### P4-T015 — ALL-role continuous maintenance (depends on P4-T014)
Status: DONE
Purpose: REQ-AP-ZONE-051/052 — once the reconciler exists, re-evaluate
whether a continuously-maintained technical combination role is actually
needed, or whether periodic Plan regeneration via the reconciler is enough.
Depends on: P4-T014 is DONE at `1eeb855`.
Decision: a technical combination role is not needed. `GUILD_MEMBER_UPDATE`
is projected into the canonical member-role cache before it coalesces the
durable reconciliation job. REASSERT then evaluates ALL against that fresh,
complete inventory and compiles the existing exact per-member overwrite Plan.
Adding a shadow role would duplicate membership state, require a second role
assignment reconciler and add Discord hierarchy/capability failure modes
without improving the supported result. The periodic scheduler remains the
lost-event fallback. If the inventory is incomplete or the exact preview is
bounded, the existing lock reconciler fails closed to intervention rather
than guessing or creating an unmaintained role.
UI/diagnostic consequence: none; because no technical role is created, there
is no hidden artifact to expose in expert diagnostics. The ordinary Policy
and Plan diagnostics remain the truthful source.
Evidence:
- real PostgreSQL integration projects an external `GUILD_MEMBER_UPDATE`,
  verifies the two-role cache value and durable `RECONCILE_STRUCTURE` job,
  then proves the locked ALL Policy schedules a canonical Plan containing
  only the target member overwrite;
- focused unit proof covers both directions: gaining the last required role
  produces `GAINED/CAN`, losing one required role produces `LOST/CANNOT`;
- 32 targeted reconciliation unit tests and 17 real PostgreSQL
  Policy/reconciler tests PASS; Ruff and `git diff --check` PASS.

### P4-T016 — Complete conflict resolution (CFL family + VIS-004 unification)
Status: DONE
Purpose: Close REQ-AP-CFL-001..006 and finish REQ-AP-VIS-004 by unifying the
previously separate ADMINISTRATOR/raw-overwrite/category-inheritance causes.
Implementation: `explain_observable_access_conflict()` consumes the canonical
`PermissionDecision` instead of creating a second resolver. It compares the
Policy intention with effective Discord access and returns the member,
resource, selected Policies, actual/expected outcome and exact cause family:
owner/ADMINISTRATOR, base role, role/member/everyone overwrite or implicit
denial. Synced category inheritance identifies the parent category.
`ConflictExplanation` now also returns validated remediations. Role removal
is never proposed for managed/@everyone roles and always exposes other base
permissions, allowed-overwrite permissions and affected resources that would
be lost. Overwrite and Policy revisions route to the existing Roles, Matrix
or Policies workspaces; each remediation is marked `requires_separate_plan`
and none mutates Discord from this explanation endpoint or UI.
Requirements: REQ-AP-VIS-004 and REQ-AP-CFL-001..004/006 → CONFORME.
REQ-AP-TST-004 is covered by the two-contradictory-roles test.
REQ-AP-CFL-005 (SHOULD) → DEFERRED: the only existing `RoleOptimizer` is
specialized for technical translation roles. The current read model has no
trustworthy generic signal that a business role is unused, redundant or
compensating; exposing deletion/merge advice would guess intent and risk
collateral access. No optimizer action is offered. This does not weaken
CFL-006: all offered conflict remedies are explicitly separate, previewable
Plan-producing flows and no optimization is implicit.
Evidence: 92 backend Policy unit tests, 12 real PostgreSQL integration tests,
Ruff, mypy, `git diff --check`, TypeScript, i18n, OpenAPI and targeted ESLint
PASS. Thirteen targeted Playwright scenarios PASS, including the observable
ADMINISTRATOR conflict and the two-role Policy conflict, with zero APPLY.
Desktop/mobile visual inspection and axe PASS. No migration or Discord live
mutation. Product commit: `9e62acd`.

### P4-T017 — Custom policy deletion with explicit strategy
Status: DONE
Purpose: REQ-AP-014 — deletion of an in-use custom Policy must be blocked
until an explicit strategy (detach / replace / delete bindings) is chosen,
with Preview/Impact, tenant-safe.
Implementation: deletion is an audited soft retirement, never a physical SQL
delete: Policy revisions and immutable Plan provenance remain intact. The
read-only dependency preview reuses `plans.source_policy_id`, current Policy
metadata references (`source-policy`/accepted exception), bulk-operation tags
and the Policy's own active scope binding; it also returns the canonical
disable impact for ACTIVE Policies. No second dependency graph was created.
The modal forces one explicit strategy: DETACH retires the declaration and
leaves current Discord state untouched; REPLACE accepts only an ACTIVE Policy
with the same type/version/scope and target; DELETE_BINDINGS removes the
managed effect. REPLACE and DELETE_BINDINGS require an exact disable preview
and a separately created, preflight-validated canonical DISABLE Plan. The
modal never applies it and navigates to Plans. Apply-time Policy preflight
accepts the intentional RETIRED terminal state for that exact DISABLE Plan.
The chosen strategy plus replacement/Plan identifiers are retained in the
RETIRE revision tags. The legacy `/retire` lifecycle route remains strict and
cannot bypass this strategy flow for DRAFT/ACTIVE Policies.
Requirements: REQ-AP-014 → CONFORME. Tenant A cannot select Guild B's Policy
as replacement through RLS; managed/@historical dependencies are preserved,
not reassigned or cascade-deleted. No migration and no direct Discord mutation.
Evidence: 93 backend Policy unit tests, 13 real PostgreSQL integration tests,
14 targeted Playwright scenarios, Ruff, mypy, `git diff --check`, TypeScript,
i18n, OpenAPI and targeted ESLint PASS. The deletion scenario proves dependency
display, strategy selection, separate Plan routing, axe, mobile overflow and
zero APPLY. Product commit: `d49c0f3`.

### P4-T018 — Context menus: "Gérer l'accès" + bulk policy actions
Status: DONE
Purpose: REQ-AP-BULK-004 (SHOULD), REQ-AP-UX-004 (MUST). Reuse the existing
Action Registry — do not build a second context-menu system.
Requirements: REQ-AP-UX-004 (from a category/channel, "Gérer l'accès" must
appear before technical role/permission entries in the context menu),
REQ-AP-BULK-004 (from a multi-selection, frequent Policy actions if
genuinely compatible).
Implementation: `manage_access` and `manage_access_bulk` are registered first
in the Phase 3 canonical Action Registry. A single category/channel navigates
to Policies with an exact tenant/type/id scope; the Policies target selector
applies that scope after its cache-first resources load. A selection of two
to 150 categories/channels from one Guild exposes the bulk entry and routes
to the existing Access Matrix, whose existing bulk-preview/bulk-plan UI is
pre-seeded with only valid resource IDs. Mixed selections containing another
resource kind and cross-Guild selections remain rejected. Capability checks
require `policies.read`, plus `permissions.read` for Matrix bulk. No second
menu, resolver, bulk engine, backend endpoint, Discord call or APPLY path was
introduced. Labels are complete in EN/FR/DE/ES.
Requirements: REQ-AP-UX-004 → CONFORME; REQ-AP-BULK-004 → CONFORME.
Evidence: 12 interaction unit tests including exact routes/order/mixed source;
the full frontend suite is 98/98 PASS. Twenty-seven Structure/Policies/Matrix
Playwright scenarios plus the reapply regression scenario PASS; the new cases
prove first-position single action, exact target scope, mixed category/channel
bulk-only menu and checked Matrix preselection. TypeScript production build,
ESLint, i18n and `git diff --check` PASS. Two pre-existing Phase 4 lint defects
(unsafe numeric Snowflake fixtures and non-null assertions) and one stale
Structure label assertion were corrected without weakening coverage. Product
commit: `a6f058b`.

### P4-T019 — Policy favorites (per Guild)
Status: DONE
Purpose: REQ-AP-UX-007 (SHOULD). Explicitly not prioritized above UI,
locking, temporary access or conflicts — do last, only if it stays light.
Delivered: a lightweight durable `policy_favorites` preference keyed by Guild,
user and validated native/custom Policy key. RLS requires both tenant and actor
GUCs; custom IDs are resolved through the existing tenant-scoped Policy
repository. The intention-first catalogue exposes accessible EN/FR/DE/ES
pin/unpin controls, moves compatible favorites into a first section without
duplication, persists across reloads and never calls APPLY or Discord.
Tests: 133 targeted Policy unit tests, 14 real PostgreSQL Policy integrations,
98 frontend unit tests and 24 Phase 4 Playwright scenarios pass. The focused
browser scenario proves pin, first position, reload persistence, axe and zero
APPLY. Ruff targeted, mypy targeted, TypeScript/Vite build, ESLint, i18n,
OpenAPI and diff check pass. Migration `0041_ui_phase4` applied successfully.
Product commit: `3fe438f`.

### P4-T020 — Writing advanced: reactions/threads/replies completion
Status: DONE
Purpose: Close REQ-AP-WRI-022 and REQ-AP-PRS-013 fully — re-inspect exactly
what the reply/thread primitives can honestly support before promising
anything.
Requirements: REQ-AP-WRI-022 and REQ-AP-PRS-013 → CONFORME within Discord's
real permission model. Discord exposes `ADD_REACTIONS`,
`CREATE_PUBLIC_THREADS`/`CREATE_PRIVATE_THREADS`, and
`SEND_MESSAGES_IN_THREADS`; it does not expose a distinct permission for a
reply sent in the main channel. The UI therefore labels the third control
"Replies in threads" and explicitly explains that main-channel replies still
follow the publishing permission. Official sources:
https://github.com/discord/discord-api-docs/blob/main/developers/topics/permissions.mdx
and
https://github.com/discord/discord-api-docs/blob/main/developers/resources/message.mdx.
Implementation: the native "Open reading, publishing limited to..." Policy
and the Announcement preset now expose three independent, intention-first
controls for reactions, thread creation and thread replies. The new reply
control reuses the canonical `PARTICIPATE_THREAD` access primitive, which the
existing backend registry and compiler already map to
`SEND_MESSAGES_IN_THREADS`; no backend capability, resolver or mutation path
was duplicated. `ONLY` preset sub-rules fail closed until at least one
publisher is selected, preventing an empty audience from producing an invalid
definition. All copy is available in EN/FR/DE/ES.
Evidence: full frontend suite 99/99 PASS; 40 targeted backend Policy
foundation/planning tests PASS; 15 Policies/Presets Playwright scenarios PASS,
including exact generated effects, axe and zero APPLY; focused new Playwright
tests 2/2 PASS. TypeScript/Vite build, ESLint, i18n and `git diff --check`
PASS. The new panel was visually inspected from a real Chromium render and is
legible and consistent with Esquisse 1. Product commit: `d94b1a0`.
Known limitation: Discord's main-channel reply is an ordinary message with a
message reference, so it cannot be permissioned separately from publishing.
The product states this limitation instead of presenting a fake control.

---

## Pending research (background agent)

An Explore agent was dispatched this session to investigate: existing
Discord gateway/reconciliation-loop infrastructure (Stage 3/5), existing
worker/scheduler used for Plan execution, audit-trail patterns for a
system-initiated actor, exact Policy aggregate/migration state, and any
existing durable-scheduled-action precedent (e.g. Stage 09 campaign
automation). Its findings must be read and incorporated into P4-T012 and
P4-T014 designs before writing code for those two tasks.

---

## Handoff notes (update before every stop)

Last updated: 2026-09-21, after P4-UI-000 and Phase 4 closure.

Current product HEAD: `2f7b9d2` (`fix(ui): keep context menus within viewport`).

Worktree state: only Phase 4 closure documentation is pending.

Tasks DONE: every functional P4 task and P4-UI-000. Phase 4 is DONE.

Docker/Postgres test env: currently running for the P4-T017 follow-on. Before
any future integration test if it has been torn down:
```
docker compose -f compose.test.yaml up -d --wait
DID_DATABASE_ADMIN_URL="postgresql+asyncpg://did_admin:local_admin_password@127.0.0.1:55432/did_test" uv run alembic upgrade head
export DID_RUN_INTEGRATION=1
export DID_DATABASE_ADMIN_URL="postgresql+asyncpg://did_admin:local_admin_password@127.0.0.1:55432/did_test"
export DID_DATABASE_URL="postgresql+asyncpg://did_app:local_app_password@127.0.0.1:55432/did_test"
uv run pytest backend/tests/integration/... -v
```
Notes that cost real time to discover this session: (a) `localhost` fails
to connect from Python/asyncio in this specific Windows sandbox even though
the port is genuinely reachable (raw socket/asyncpg/SQLAlchemy all connect
fine to `127.0.0.1` directly — always use `127.0.0.1`, never `localhost`,
for DB connections in this environment); (b) alembic's env.py reads
`DID_DATABASE_ADMIN_URL`, not `DID_DATABASE_URL` — using the wrong name
silently falls back to a default pointing at port 5432/db `did`, producing
a confusing connection-refused with no hint of the real cause; (c) the
`integration` pytest marker is skipped by default
(`backend/tests/integration/conftest.py`) unless `DID_RUN_INTEGRATION=1`.

P4-T014 evidence: 31 targeted unit tests, 16 real PostgreSQL integration
tests, 9 Playwright tests, Ruff, mypy, TypeScript, ESLint, i18n and OpenAPI all
PASS. Visual desktop/mobile pass also complete. See its dedicated section.

P4-T015 evidence: 32 targeted reconciliation unit tests and 17 real
PostgreSQL Policy/reconciler integration tests PASS. The technical-role
decision and exact behavior are recorded in its dedicated section.

P4-T016 evidence: 92 backend Policy unit tests, 12 real PostgreSQL integration
tests and 13 Playwright scenarios PASS, plus Ruff, mypy, TypeScript, i18n,
OpenAPI, targeted ESLint, diff check, desktop/mobile and axe. Product commit
`9e62acd` is pushed.

P4-T017 evidence: 93 backend Policy unit tests, 13 real PostgreSQL integration
tests and 14 targeted Playwright scenarios PASS, plus Ruff, mypy, TypeScript,
i18n, OpenAPI, targeted ESLint, diff check, desktop/mobile and axe. Product
commit `d49c0f3` is pushed.

P4-T018 evidence: 12 interaction unit tests and the full 98-test frontend
suite PASS; 27 Structure/Policies/Matrix Playwright scenarios plus one reapply
regression PASS. TypeScript production build, ESLint, i18n and diff check pass.
The single action is first and target-scoped; the mixed category/channel action
reuses the existing Matrix bulk flow with exact preselection. Product commit
`a6f058b` is pushed.

P4-T019 evidence: 133 targeted backend Policy unit tests, 14 real PostgreSQL
Policy integration tests, the full 98-test frontend suite and 24 targeted
Phase 4 Playwright scenarios PASS. The preference is durable, idempotent and
isolated by both Guild and user under forced RLS; compatible native/custom
favorites stay first after reload. TypeScript/Vite, ESLint, i18n, OpenAPI,
targeted Ruff/mypy and diff check pass. Product commit `3fe438f` is pushed.

P4-T020 evidence: full frontend suite 99/99, 40 targeted backend Policy tests,
15 Policies/Presets Playwright scenarios and the 2 focused new scenarios all
PASS. TypeScript/Vite, ESLint, i18n and diff check pass. The real Chromium
render is visually accepted, axe reports no serious/critical violation and
the scenarios make zero APPLY calls. Product commit `d94b1a0` is pushed.

P4-T012 evidence: 145 targeted backend unit tests, 15 real PostgreSQL Policy
integrations, the real scheduler-process integration, full frontend suite
99/99 and 16 Policies/Presets Playwright scenarios pass. Build, ESLint, i18n,
OpenAPI, Ruff, mypy and diff checks pass. Desktop/mobile Chromium and axe pass;
the mobile viewport has no page overflow and the scenario makes zero APPLY
calls. Product commit `76396fa` is pushed.

P4-UI-000 evidence: the 10-item minimum visual checklist is fully inspected at
desktop and mobile widths. The final pass covered conflict/remediation, Named
Audience inline editing, expert diagnosis, Matrix cell editing, composed
presets and both context-menu variants. It found and fixed one genuine defect:
long fixed menus now remain inside the mobile viewport. Full frontend 99/99,
44 selected Structure/Phase 4 Chromium scenarios, build, ESLint and i18n pass.
Product commit `2f7b9d2` is pushed.

NEXT EXACT ACTION: none inside Phase 4. Stop here and wait for an explicit
instruction before starting Phase 5 or any later phase.

## Reconciler/scheduler research findings (for P4-T012 and P4-T014)

A background Explore agent investigated existing infrastructure to reuse.
Summary (full detail was in the agent's report, not persisted verbatim —
re-verify file paths before use since this is a paraphrase):

- **Drift detection precedent**: `did/application/discord_runtime/gateway.py`
  (`normalize_gateway_dispatch`, `GatewaySessionTracker`) is the event-driven
  listener contract (CHANNEL_*, GUILD_ROLE_*, THREAD_* dispatches). Continuity
  states mark cache stale via `RuntimeRepository.record_gateway_discontinuity`
  (`did/infrastructure/runtime_repository.py`), which already writes audit
  rows with `source='SYSTEM'` — but this only detects cache staleness, NOT
  policy drift; the actual "does Discord still match what a locked Policy
  requires" comparison is net-new logic.
- **Periodic safety net precedent**: `did/application/reconciliation/scheduler.py`
  (`ReconcileScheduler`, `AdaptiveReconcilePolicy`) polls periodically and
  enqueues `WorkloadJob("RECONCILE_STRUCTURE", ...)` via
  `RuntimeRepository.enqueue_job`. This event-triggered-urgency +
  periodic-fallback shape, feeding one durable job queue, is exactly the
  pattern to reuse for locked-Policy drift — but it only refreshes the
  observed-state cache today, no Policy comparison.
- **Worker/scheduler process reuse point**: `did/runtime.py::run_process` has
  a `"scheduler"` branch (~line 273-344) that runs a `runners: list[Awaitable]`
  concurrently via `asyncio.gather(*runners)` — currently
  `ReconcileScheduler.run` + `CampaignSchedulerRuntime.run` (Stage 09). Add a
  new `PolicyDriftSchedulerRuntime`/`TemporaryAccessSchedulerRuntime` with the
  same `.run(stop_event)` contract and append to `runners` — no new process
  type needed.
- **Apply/repair path**: a repair Plan for drift should be created via the
  same `PlanningService`/`ApplyPlanExecutor` pipeline (provenance
  `PlanOriginType.POLICY` already exists) — `worker/io/plan_executor.py`
  (`ApplyPlanExecutor._execute`, `APPLYING`/lease fencing),
  `worker/io/worker.py` (`DurableDiscordIOWorker`),
  `worker/io/governor.py` (`DiscordWorkloadGovernor`). No new mutation path.
- **System-actor audit precedent**: `internal_audit_events`
  (migration `0003_stage_03_discord_runtime.py`) already has a nullable
  `actor_user_id` and an unconstrained `source` string already used as
  `'SYSTEM'` (event `CACHE_STALE_AFTER_GATEWAY_GAP`) — use `'POLICY_RECONCILER'`
  the same way, no migration needed for the audit row itself.
  `PolicyService.accept_exception()` (`did/application/policies/service.py`)
  already shows the append-only `policy_versions` pattern for a
  metadata-only system annotation (`change_kind='ANNOTATE'`) — reusable for
  a repair/needs-intervention annotation.
- **Policy aggregate**: `did/domain/policies.py` (`Policy`/`PolicyVersion`).
  Tables via migrations `0036`-`0039`. **No `locked` field exists anywhere**
  — confirmed absent. Needs a new migration adding `locked: bool` (or richer
  lock metadata) to `Policy`/`policies`.
- **Durable scheduled-action precedent (for P4-T012 temporary access)**:
  Stage 09's `message_campaign_schedules`
  (migration `0022_stage_09_campaign_engine.py`, columns `fire_at`/`rrule`/
  `misfire_policy`) with lease-based claim/finalize —
  `CampaignsRepository.claim_due_schedules`/`finalize_schedule_claim`, driven
  by `did/campaigns/scheduler_loop.py::run_scheduler_tick`. Restart-safe,
  retry-safe (only advances cursor if lease still held). Model temporary
  access expirations as a sibling table with the same claim/lease/finalize
  contract, add a `TemporaryAccessSchedulerRuntime.run(stop_event)` to the
  scheduler process's `runners`, fire removal through
  `PlanningService`/`ApplyPlanExecutor` (never direct Discord), mark
  `INTERVENTION_REQUIRED` on failure (mirrors `plan_executor.py::_finalize`'s
  existing terminal states) rather than silently showing success.

This research is NOT yet re-verified against the current file tree by a
human/AI reading the actual files — treat file paths as a strong lead, not
gospel; grep/read them before writing code that depends on exact function
signatures.
