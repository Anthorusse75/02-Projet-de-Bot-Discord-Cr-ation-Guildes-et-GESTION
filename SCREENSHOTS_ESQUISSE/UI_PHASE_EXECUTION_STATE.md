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

Status: IN_PROGRESS

Branch: ui/complete-redesign

Phase baseline SHA: 8b77bb9 (feat(ui): add access policies workspace — first
Phase 4 reopening commit after the initial permissions socle)

Current verified SHA: 80c1535b4e2c0fc4dcf21c418b3d2a6622ced91f

Session start: 2026-09-16, working tree clean, HEAD == expected SHA.

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
Partial (documented, not over-claimed): REQ-AP-ZONE-030/031/032 (real OR
composition + live re-evaluation; no continuous re-verification of an
already-generated Plan without a reconciler), REQ-AP-ZONE-050 (covered),
REQ-AP-ZONE-051/052 (exact translation only at Plan-generation time; no
continuously-maintained combination role — deliberately not built to avoid
prohibited unmaintained hacks; needs the future reconciler, see P4-T014/T015),
REQ-AP-VIS-004 (role-vs-role cause covered; ADMINISTRATOR/raw member
overwrite/category inheritance not yet unified in the same explanation — see
P4-T016).
Still open, not attempted this lot: REQ-AP-ZONE-001/002/003 (public zone +
linked staff space via Logical Group — see P4-T010), REQ-AP-PRS-*
(composed presets — see P4-T011), REQ-AP-CFL-005/006 (role optimization —
see P4-T016).
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
Status: TODO
Purpose: Compare the real running UI for all Phase 4 screens against
`Esquisse 1.png`, at the sizes required by the closure checkpoint, and log
genuine defects as atomic P4-UI-* tasks. Do NOT log cosmetic nitpicks that
aren't real defects.
NEXT EXACT ACTION:
1. Start the frontend dev server (and backend if screens need live data) via
   the `run` skill or documented dev commands.
2. Screenshot: Roles, Permissions (simple+expert), Policies list, Policies
   editor (simple+expert), Access Matrix, Wizard catalog, Wizard access-space
   flow, conflict/remediation panel, Named Audience editor.
3. Compare each against Esquisse 1.png direction (dark navy, progressive
   disclosure, intention-first, calm density).
4. For each real defect, create a `P4-UI-0xx` task below with a concrete
   description, not a vague "make it nicer".

### P4-T010 — Zone publique + espace staff associé (Logical Group link)
Status: TODO
Purpose: REQ-AP-ZONE-001/002/003 — let an admin declare "this public space
has an associated staff space" using the existing Stage04 `logical_groups`
primitive, never a fake Discord sub-category.
Requirements: REQ-AP-ZONE-001 (MUST, no fake Discord subcategory — already
true by construction if we only ever compose existing resources),
REQ-AP-ZONE-002 (MUST, two valid Discord structures + a clearly identified
DID logical-group abstraction), REQ-AP-ZONE-003 (MUST, public part follows
its own policy, staff part follows Staff-only).
Already implemented (reusable): `logical_groups` (Stage04), Staff named
audience (P4-T009), Policies/Plan pipeline.
Remaining: no UI exists to (a) pick/create a logical group linking a public
category/channel to a staff category/channel, (b) show the pair together
with "Public: <policy>" / "Staff: Staff uniquement" summary, (c) make the
DID-grouping-vs-real-Discord-structure distinction visually unambiguous
(REQ-UXN-004 territory).
Files likely touched: `frontend/src/features/policies/` (or a small
dedicated `zones/` UI module), Stage04 logical_groups API (read/link only,
reuse existing endpoints — check before adding any route).
Tests already executed: none yet.
NEXT EXACT ACTION:
1. Re-confirm Stage04 logical_groups CRUD/link API surface (endpoint names)
   via Explore or Grep before writing any UI.
2. Design the minimal "Public + Staff pairing" panel: pick an existing
   logical group OR create one from two existing resources, apply "Staff
   uniquement" to the staff side, show both under one card.
3. Wire Preview/Plan through existing Policy pipeline only.
4. i18n EN/FR/DE/ES, targeted unit test, 1 Playwright happy path.

### P4-T011 — Composed presets: Confidentiel, Salon d'annonces, Zone support
Status: TODO
Purpose: REQ-AP-PRS-001, 010-013, 020-022. A preset must show its sub-rules
before Plan (no opaque alias) and must not be offered if its primitives
aren't real yet.
Requirements: REQ-AP-PRS-001 (Confidentiel shows every activated sub-rule
before validation), REQ-AP-PRS-010/011/012 (Salon d'annonces — applicable to
existing or new channel, persistent by default, separate reader/publisher
choice), REQ-AP-PRS-013 (SHOULD, reactions/threads options), REQ-AP-PRS-020/021
(Zone support — persistent or existing zone, visibility/write/support group),
REQ-AP-PRS-022 (SHOULD, ticket integration as a separate option, only if a
ticket engine exists — check before assuming one does; if none exists, this
sub-item is N/A and must be documented as such, not built).
Already implemented (reusable primitives): visibility/writing policies,
voice/thread/reaction/mention families (P4-T008), named audiences (P4-T009).
Remaining: a preset is a *composition* of existing native policies with a
guided "show sub-rules before Plan" UI — needs a small composition layer
(likely a list of {catalog_key, params} the Wizard or Policies screen
resolves into one or more DRAFT Policies with a shared tag, same pattern as
`createNewcomerAreaDefinitions()` in P4-T009).
Files likely touched: `features/policies/catalog.ts` (add preset
definitions), a new `presets.ts` composition helper mirroring
`createNewcomerAreaDefinitions()`, PoliciesScreen/Wizard UI to show expanded
sub-rules pre-Plan.
Tests already executed: none yet.
NEXT EXACT ACTION:
1. Check whether a ticket engine exists anywhere in the product (grep
   "ticket"); if not, document REQ-AP-PRS-022 as N/A in this task, not built.
2. Implement `presets.ts`: Confidentiel = visibility whitelist + management
   whitelist + mention control, composed the same way as newcomer-area.
3. Implement Salon d'annonces and Zone support presets similarly, reusing
   existing catalog entries — no new PolicyResolver capability.
4. UI: preset picker expands to show every sub-rule (native policy name +
   plain-language summary) before "Prepare the plan".
5. i18n EN/FR/DE/ES, targeted unit tests, 1 Playwright per preset family (or
   one combined if scenarios overlap defensibly).

### P4-T012 — Temporary access (grant until date/duration)
Status: TODO
Purpose: REQ-AP-TMP-001..006. Full implementation, not a frontend-only
simulation — this is explicitly forbidden ("ne jamais simuler l'expiration
uniquement côté frontend").
Requirements: REQ-AP-TMP-001 (grant until date/duration), 002 (bot/service
drives expiration + produces the removal operation), 003 (durable, survives
restarts), 004 (expiry+removal audited), 005 (failed removal → actionable
state, never shown as succeeded), 006 (SHOULD — 1h/24h/7d/until shortcuts +
custom date).
Depends on: findings from the reconciler/worker/scheduler research
(in progress — see NEXT EXACT ACTION).
Remaining: everything. Needs a durable expiry record tied to a Policy or
binding, a scheduler/worker firing the removal Plan at/after expiry, retry,
and a "needs intervention" actionable state on failure.
Files: TBD pending research agent findings (reuse existing worker/scheduler
primitive if one exists — likely Stage 09 campaign automation, or Stage 03/05
reconciliation loop; do not build a second architecture).
Tests already executed: none yet.
NEXT EXACT ACTION:
1. Read the findings from the backgrounded Explore agent (dispatched this
   session) on existing worker/scheduler/reconciliation infrastructure
   before writing any code.
2. Decide storage: likely a durable field/table for temporary Policy
   bindings (expires_at, removal status) — reuse `policies`/`policy_versions`
   metadata if sufficient, else a minimal new table with RLS + migration.
3. Wire expiry firing through the canonical Plan/Apply pipeline only (no
   parallel mutation path) — removal = a Plan like any other.
4. UI: duration shortcuts (1h/24h/7j/jusqu'à…) + custom date in the relevant
   Policy creation/Wizard flow; visible countdown/expiry badge; actionable
   "needs intervention" state on failed removal.
5. Targeted unit tests (expiry calc, removal Plan compilation), integration
   test (durable persistence across simulated restart), 1 E2E ciblé, 1
   scheduler/worker test for retry + failure state per REQ-AP-TST-005-style
   doctrine.

### P4-T013 — Reapply category master policy to exceptions
Status: TODO
Purpose: REQ-AP-INH-003 — "réappliquer la politique de catégorie" on one or
more local exceptions, always via Preview → Plan.
Already implemented: category master policy + Inherited/Exception
local/Conflict display (per PHASE_04_REPORT.md §16 inventory — verify exact
current state before coding, it may already partly exist).
Remaining: the actual "Reapply" action + multi-select + Preview + Plan.
NEXT EXACT ACTION:
1. Grep the frontend/backend for existing category-inheritance exception UI
   to confirm exactly what exists today (do not assume from the report
   alone).
2. Add the "Reapply category policy" action (single + multi-select) that
   creates a Preview then a Plan removing the local exception's diverging
   effect, reusing the existing Policy Preview/Plan pipeline.
3. Targeted unit + 1 Playwright.

### P4-T014 — Locked policy / drift / reconciler
Status: TODO
Purpose: REQ-AP-LOCK-001..006 — the largest remaining architectural piece.
Depends on: reconciler/worker Explore agent findings (in progress).
Remaining: everything — "locked" flag on Policy, event-driven drift
detection (Discord gateway event → check locked policies affected → auto
repair via canonical Plan/Apply, no manual confirmation needed as long as
capabilities remain valid), periodic reconciliation as a safety net, audit
with initiator `POLICY_RECONCILER`, fail-closed "needs intervention" state
when auto-repair impossible, and for NON-locked policies: drift shown with
"Repair" / "Accept exception" actions.
NEXT EXACT ACTION:
1. Read the findings from the backgrounded Explore agent on existing
   gateway-event/reconciliation-loop/worker infrastructure before designing
   anything.
2. Add `locked: bool` to the Policy aggregate (migration) if not already
   representable.
3. Reuse the existing Discord gateway event pipeline (if one exists) to
   trigger a targeted re-resolution of affected locked Policies; compile any
   drift-correcting effect through the canonical Plan/Apply path with
   initiator `POLICY_RECONCILER`.
4. Add the periodic safety-net job on the existing worker/scheduler (not a
   new one).
5. UI: locked badge, drift banner, "Repair"/"Accept exception" for unlocked,
   "Needs intervention" actionable state for failed auto-repair on locked.
6. Tests per REQ-AP-TST-005: mutation externe → détection → remise en
   conformité, and a reconciliation-failure test.

### P4-T015 — ALL-role continuous maintenance (depends on P4-T014)
Status: DEFERRED
Purpose: REQ-AP-ZONE-051/052 — once the reconciler exists, re-evaluate
whether a continuously-maintained technical combination role is actually
needed, or whether periodic Plan regeneration via the reconciler is enough.
Depends on: P4-T014 must land first (explicit instruction: "quand le
reconciler existe, réévaluer la bonne architecture").
NEXT EXACT ACTION: do not start before P4-T014 is DONE. When ready: decide
with evidence whether a hidden technical role is truly necessary; if not,
close as "not needed, reconciler + Plan regeneration suffices" with
justification; if yes, build via Plan only, hidden from the normal flow,
visible only in expert diagnostic.

### P4-T016 — Complete conflict resolution (CFL family + VIS-004 unification)
Status: TODO
Purpose: Close REQ-AP-CFL-001..006 and finish REQ-AP-VIS-004 (currently
role-vs-role only; ADMINISTRATOR/raw overwrite/category inheritance not
unified in the same explanation).
Already implemented: `conflict_explanations.py` (role-vs-role cause +
blacklist regrant), "Accept exception" flow (P4-T009).
Remaining: REQ-AP-CFL-001 (list members whose roles produce a result
contrary to declared policy intent — broader than the current blacklist-only
detection), REQ-AP-CFL-002 (who/resource/policy/granting-rule/denying-rule
for every observable cause, not just role-vs-role), REQ-AP-CFL-003/004
("Régler ce conflit" only valid solutions + collateral impact before any
mutation, role removal always shows what else is lost), REQ-AP-CFL-005
(SHOULD — detect redundant/contradictory/unused/compensating roles),
REQ-AP-CFL-006 (MUST — role optimization is always a separate previewable
Plan, never implicit from conflict resolution).
NEXT EXACT ACTION:
1. Extend `conflict_explanations.py` to unify ADMINISTRATOR and raw member
   overwrite causes (category inheritance already partly signaled via
   `AccessMatrixCell.inherited`) into the same explanation shape used by the
   UI panel.
2. Build "Régler ce conflict" remediation list: only real valid actions,
   each showing collateral impact (other things lost) before Preview/Plan.
3. REQ-AP-CFL-005/006 (role optimization) as a clearly separate, explicitly
   labeled "Optimiser les rôles" Plan-only flow — do not build if it would
   require guessing without solid signal; if deferred, document why.
4. Targeted unit tests for each new cause type + REQ-AP-TST-004 (two
   contradictory roles on one member) + 1 Playwright on the extended panel.

### P4-T017 — Custom policy deletion with explicit strategy
Status: TODO
Purpose: REQ-AP-014 — deletion of an in-use custom Policy must be blocked
until an explicit strategy (detach / replace / delete bindings) is chosen,
with Preview/Impact, tenant-safe.
Already implemented: everything except deletion (P4-T005 explicitly
deferred this: "la suppression n'est volontairement pas exposée").
Remaining: dependency-usage check (what currently references this Policy:
Plans, bulk tags, bindings), the three strategies UI, Preview/Impact before
commit, tenant isolation test.
NEXT EXACT ACTION:
1. Grep for existing Policy-usage/dependency queries (Plan provenance
   already links Plan→Policy per P4-T004 — reuse that instead of building a
   new dependency graph).
2. Design "Supprimer" flow: if in use, force strategy choice
   (detach/replace/delete-bindings) with Preview before commit.
3. Backend: deletion endpoint with strategy parameter, tenant-safe, RLS
   test.
4. UI: enable "Supprimer" in the policy list/editor with the strategy modal.
5. Targeted unit + integration (tenant A/B) + 1 Playwright.

### P4-T018 — Context menus: "Gérer l'accès" + bulk policy actions
Status: TODO
Purpose: REQ-AP-BULK-004 (SHOULD), REQ-AP-UX-004 (MUST). Reuse the existing
Action Registry — do not build a second context-menu system.
Requirements: REQ-AP-UX-004 (from a category/channel, "Gérer l'accès" must
appear before technical role/permission entries in the context menu),
REQ-AP-BULK-004 (from a multi-selection, frequent Policy actions if
genuinely compatible).
Already implemented: canonical Action Registry (Phase 3) with a structural
bulk "move channels" action; Access Matrix bulk policy pipeline (P4-T007).
Remaining: register "Gérer l'accès" as a high-priority entry in the existing
category/channel context menu (opens Policies scoped to that target); for
multi-selection, only surface bulk Policy actions when the current
selection is a valid category/channel mix the Matrix bulk pipeline already
supports — reuse it, don't duplicate.
NEXT EXACT ACTION:
1. Locate the canonical Action Registry (Phase 3 structure explorer) and its
   ordering/priority mechanism.
2. Add "Gérer l'accès" entry (single target) navigating to Policies
   pre-scoped to that target, ordered before technical entries.
3. Add a multi-selection entry that opens the existing Access Matrix bulk
   flow pre-seeded with the current selection, reusing bulk-preview/bulk-plan
   — no new bulk engine.
4. Targeted unit/interaction test + 1 Playwright for each entry point.

### P4-T019 — Policy favorites (per Guild)
Status: TODO
Purpose: REQ-AP-UX-007 (SHOULD). Explicitly not prioritized above UI,
locking, temporary access or conflicts — do last, only if it stays light.
NEXT EXACT ACTION: implement only after P4-T010..T018 (or explicitly
DEFERRED with justification if session time runs out) — a simple per-Guild
pinned-policy-ids preference, surfaced at the top of the catalog/list.

### P4-T020 — Writing advanced: reactions/threads/replies completion
Status: TODO (currently PARTIAL per P4-T008)
Purpose: Close REQ-AP-WRI-022 and REQ-AP-PRS-013 fully — re-inspect exactly
what the reply/thread primitives can honestly support before promising
anything.
NEXT EXACT ACTION:
1. Re-inspect current reaction/thread option coverage in the catalog
   (`features/policies/catalog.ts`) and backend registry to see precisely
   what's missing for "replies" specifically (Discord has no granular
   "reply" permission separate from SEND_MESSAGES_IN_THREADS — verify this
   before promising a control that Discord cannot express).
2. Close only what the primitives genuinely allow; if a sub-option cannot be
   honestly built (Discord limitation), document it the same way
   REQ-AP-REA-001/MEN-001 were documented in P4-T008, not silently dropped.

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

Last updated: 2026-09-16, session start.

Current HEAD: `80c1535b4e2c0fc4dcf21c418b3d2a6622ced91f`

Worktree state: clean.

Task IN_PROGRESS: P4-UI-000 (visual acceptance pass) — not yet started,
about to launch the frontend.

Just done: reconstructed full Phase 4 history (P4-T001..P4-T009) from
`PHASE_04_REPORT.md`/`UI_REQUIREMENTS_REMEDIATION_MAP.md`/git log; drafted
the open backlog (P4-T010..P4-T020) from
`docs/40_decisions/ACCESS_POLICIES_PRODUCT_REQUIREMENTS.md` cross-referenced
against PHASE_04_REPORT.md §16-18 gap lists; dispatched a background Explore
agent for reconciler/worker/scheduler research needed by P4-T012/P4-T014.

Files modified this session so far: `SCREENSHOTS_ESQUISSE/UI_PHASE_EXECUTION_STATE.md` (new).

Tests already run this session: none yet (pure documentation/reconstruction step).

Tests remaining: all — nothing implemented yet this session.

NEXT EXACT ACTION:
1. Launch the frontend (and backend if needed for live data) to perform the
   mandatory visual audit (P4-UI-000) against `Esquisse 1.png`.
2. Log any genuine visual defects as `P4-UI-0xx` tasks in this file.
3. Check on the background Explore agent; incorporate its findings into
   P4-T012 and P4-T014.
4. Start implementing the open backlog in the order listed, updating this
   file's status and evidence after every meaningful step, committing
   atomically, and pushing to `origin/ui/complete-redesign` regularly.
