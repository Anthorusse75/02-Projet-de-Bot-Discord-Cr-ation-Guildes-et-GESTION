# Bunny Server Assistant — MASTER EXECUTION PROMPT — UI Phase 1

> **STATUS: CANONICAL EXECUTION PROMPT**
>
> This file is intended to be read by Codex, Claude, or any future coding AI before
> doing work on UI Phase 1.
>
> **Do not create another roadmap, another phase structure, another master prompt, or
> another handoff system.**
>
> The operational source of truth is:
>
> `SCREENSHOTS_ESQUISSE/UI_IMPLEMENTATION_LIVE_STATE.md`

---

# 0. Your mission

You are implementing **Phase 1 — RESET VISUEL ET COMPRÉHENSION IMMÉDIATE** of
**Bunny Server Assistant**.

The product is for a normal Discord user who wants to create or manage a complex
Discord server **without needing to understand Discord internals**.

The previous UI was rejected by the user because it was:

- too technical;
- too verbose;
- too dark;
- too monochrome;
- visually flat;
- full of `UNKNOWN`, cache/freshness/provenance data and internal concepts;
- structured like an IAM/admin console instead of a friendly server builder;
- especially poor on mobile.

Your job is **not** to invent another design.

Your job is to implement the **exact visual direction already approved by the user**
and versioned in `SCREENSHOTS_ESQUISSE/`.

---

# 1. Branch and repository rules

Work only on:

`ui/complete-redesign`

At the beginning of every coding session, run:

```bash
git status
git branch --show-current
git rev-parse HEAD
git pull --ff-only origin ui/complete-redesign
```

Then re-run:

```bash
git status
git rev-parse HEAD
```

Do not start coding on another branch.

Do not reset, rebase, amend, force-push, or discard someone else's work unless the
user explicitly asks.

If the worktree is not clean, inspect the changes before doing anything.

---

# 2. Mandatory reading order

Before changing code, read these files completely:

1. `SCREENSHOTS_ESQUISSE/UI_PHASE1_MASTER_EXECUTION_PROMPT.md` — this file.
2. `SCREENSHOTS_ESQUISSE/UI_IMPLEMENTATION_LIVE_STATE.md`
3. `SCREENSHOTS_ESQUISSE/UI_UX_CANONICAL_REFERENCE.md`
4. `SCREENSHOTS_ESQUISSE/UI_IMPLEMENTATION_3_PHASES.md`

Then inspect all 9 approved screenshots:

1. `SCREENSHOTS_ESQUISSE/tableau_de_bord_discord_pastel_en_français.png`
2. `SCREENSHOTS_ESQUISSE/assistant_de_création_de_serveur_discord.png`
3. `SCREENSHOTS_ESQUISSE/assistant_discord_gestion_des_accès.png`
4. `SCREENSHOTS_ESQUISSE/constructeur_discord_pastel_en_français.png`
5. `SCREENSHOTS_ESQUISSE/tableau_de_bord_français_des_accès_serveur.png`
6. `SCREENSHOTS_ESQUISSE/gestion_pastel_des_rôles_discord.png`
7. `SCREENSHOTS_ESQUISSE/modifications_prêtes_pour_votre_serveur.png`
8. `SCREENSHOTS_ESQUISSE/centre_des_opérations_discord_pastel.png`
9. `SCREENSHOTS_ESQUISSE/maquette_mobile_bunny_server_assistant_francais.png`

These 9 images are **not loose inspiration**.

They are the approved visual target.

When in doubt, prefer the screenshots over your own aesthetic preference.

---

# 3. Product branding — non-negotiable

The product name is:

**Bunny Server Assistant**

Short UI name:

**Bunny**

Mascot / helper:

**Bunny**

The historical technical name `DID` may remain in code paths, Python modules,
database names, migrations, internal identifiers, or repository history when
renaming it would create unnecessary technical risk.

But `DID` is **forbidden in all user-facing UI**.

Do not introduce `DID` into:

- page titles;
- app header;
- logo text;
- wizard copy;
- notifications;
- help;
- mobile UI;
- screenshots;
- user-visible error messages.

If an approved screenshot still visually contains old `DID` branding, replace only
that branding with **Bunny Server Assistant** or **Bunny** while preserving the
approved visual layout.

---

# 4. Visual target — exact direction

The user explicitly approved the screenshots and said:

> "JE VEUX EXACTEMENT CET UI"

Treat that as a product requirement.

The implementation must preserve the approved characteristics:

- luminous interface;
- predominantly light surfaces;
- pastel palette;
- strong visual separation between zones;
- clearly differentiated cards;
- generous spacing;
- rounded surfaces;
- soft shadows/elevation;
- simple iconography;
- visually pleasant accents;
- low cognitive density;
- very little permanent explanatory text;
- obvious primary CTA;
- human labels;
- clear wizard steps;
- approachable visual hierarchy;
- mobile layout designed for mobile, not compressed desktop;
- friendly but not childish;
- colorful without looking chaotic.

Do **not** regress to:

- navy/dark blue everywhere;
- purple as the only accent;
- one-color cards;
- thin nearly invisible borders;
- technical dashboards;
- walls of text;
- giant checkbox grids;
- 8 disabled buttons;
- raw Discord IDs;
- raw bitfields;
- raw internal state names;
- raw cache diagnostics;
- permanent technical panels.

A dark theme may exist because the canonical reference allows it, but Phase 1's
approved visual target is the light/pastel UI shown in the screenshots. The default
experience must match that visual language first.

---

# 5. Target navigation

The novice navigation is:

- **Accueil**
- **Construire**
- **Accès**
- **Automatiser**
- **Activité**

Do not expose all technical modules as first-level navigation.

The user must not need to choose between:

- Roles
- Permissions
- Policies
- Matrix
- Plans
- Diagnostics
- Audit

as if these were separate products.

Technical screens/routes may continue to exist internally, but the novice shell must
organize them by user intention.

---

# 6. UX doctrine

## 6.1 Novice first

Assume the user does not know:

- permissions bitfields;
- Discord overwrites;
- inheritance details;
- scopes;
- policy resolution;
- cache freshness;
- Discord IDs;
- Plan state machine internals.

Do not make the user learn these concepts to use the product.

## 6.2 Progressive disclosure

Default reading order:

1. What is happening?
2. What can I do?
3. What will happen if I do it?
4. Optional "Why?" / "Details"
5. Technical details only if requested.

## 6.3 Verbosity budget

In the normal novice flow:

- no explanatory paragraph over 2 lines;
- no repeated metadata;
- no repeated server name on every card;
- no raw internal identifiers;
- no "documentation inside the page";
- no permanent debug/provenance information.

Use:

- short labels;
- icons;
- concise helper text;
- tooltip;
- popover;
- accordion;
- drawer;
- "Détails techniques".

## 6.4 Human status labels

Never make these the main user-facing status:

- `UNKNOWN`
- `FULL`
- `FRESH`
- `BLOCKED`
- `CANNOT`

Use human outcomes such as:

- **À vérifier**
- **À jour**
- **Action nécessaire**
- **Indisponible pour le moment**
- **Bunny a besoin d'une autorisation**
- **Actualiser**

If the user can fix the problem, show a direct remediation action.

## 6.5 Disabled controls

Do not create rows of disabled gray buttons.

If an action is irrelevant, hide it.

If the user needs to understand why it is unavailable, keep it only when useful and
explain the reason via tooltip/popover with a remediation path if possible.

---

# 7. Approved UI stack

The current frontend historically used too many custom primitives.

Phase 1 must standardize the UI instead of recreating common components.

Use **Mantine 9** as the primary component library.

Approved packages:

- `@mantine/core`
- `@mantine/hooks`
- `@mantine/form`
- `@mantine/modals`
- `@mantine/notifications`
- `@mantine/dates`
- `@mantine/spotlight`
- `@mantine/nprogress`
- `lucide-react`
- `motion`
- `@tanstack/react-table` when a real rich table is required
- `@tanstack/react-virtual` when virtualization is genuinely needed
- `@dnd-kit/*` for new/refactored drag-and-drop behavior where appropriate
- `dayjs` for Mantine date components
- existing React Query / Zustand / i18next remain approved

Do not add multiple competing UI libraries.

Do not write a custom replacement for an existing standard component unless there is
a documented technical reason.

Examples that should normally come from Mantine:

- modal;
- drawer;
- menu;
- tooltip;
- popover;
- select;
- combobox;
- date picker;
- toast/notification;
- tabs;
- accordion;
- stepper;
- loader;
- skeleton;
- scroll area;
- form controls;
- spotlight/command palette.

---

# 8. Phase 1 atomic tasks

The current atomic source of truth is
`UI_IMPLEMENTATION_LIVE_STATE.md`.

At the time this master prompt was created:

- `UX1-T011` visual prototypes is DONE and human-approved.
- `UX1-T001` through `UX1-T010` remain the Phase 1 implementation work unless
  the live tracker says otherwise.

Do not trust this static summary over the tracker.

Always resume the task that the live tracker marks `IN_PROGRESS`.

If no task is `IN_PROGRESS`, follow the current `NEXT EXACT ACTION` in the tracker.

At creation time, that means beginning with:

**UX1-T009 — standardize the UI stack / inventory custom primitives**

and then implementing the approved shell/tokens and the rest of UX1 tasks without
visual drift.

---

# 9. Implementation order inside Phase 1

This is **not a new phase breakdown**. It is execution guidance inside the single
Phase 1.

A practical order is:

1. audit current frontend primitives and package usage;
2. install the approved UI foundation;
3. add Mantine providers/theme/tokens;
4. implement the shared AppShell/navigation;
5. implement desktop shell;
6. implement mobile shell;
7. rewrite the overview/home screen;
8. rewrite roles presentation;
9. rewrite Access experience;
10. humanize internal states;
11. reduce verbosity globally;
12. fix local OAuth hostname consistency;
13. verify the affected screens in the real app;
14. update tracker and stop for human Phase 1 visual approval when the gate is met.

Do not create labels like "Phase 1.1", "Phase 1A", "Lot A", or "Sprint 1".

Atomic task IDs in the tracker are sufficient.

---

# 10. Existing backend behavior must be preserved

The previous work built substantial backend/domain logic.

Do not throw it away because the UI is being simplified.

The UI should translate complex backend capabilities into human-friendly flows.

Do not introduce a parallel mutation path.

For real Discord changes, preserve the canonical domain/Plan/Apply architecture.

A simpler UI does not mean weaker safety.

If a backend capability is currently unavailable or genuinely ambiguous, represent it
humanly in the UI instead of inventing a false success state.

---

# 11. Testing doctrine — IMPORTANT

The user explicitly does **not** want test volume for the sake of test volume.

Quality is measured by:

- correct behavior;
- correct UI;
- relevant evidence;
- human visual acceptance.

Not by the number of tests executed.

## 11.1 Pure visual / CSS / layout / wording change

Normally run only what is useful:

- TypeScript typecheck;
- targeted ESLint for touched frontend code, or the normal frontend lint if it is
  fast enough;
- i18n check if text keys/catalogs changed;
- actual visual verification in the browser.

Do **not** run backend regression suites.

Do **not** create backend tests.

## 11.2 Shared theme/provider/shell change

Run:

- typecheck;
- build;
- relevant lint;
- only targeted frontend tests that cover behavior actually changed.

Then visually inspect real desktop and mobile rendering.

## 11.3 Frontend interaction logic

Add or update a focused unit/component test only when it catches a meaningful
behavioral regression.

Do not write a test merely because a component was touched.

## 11.4 Backend/domain change

Only if Phase 1 truly needs a backend change:

- run the smallest relevant unit/integration tests for the modified behavior;
- DB/RLS/RBAC changes require targeted integration proof;
- Discord mutation logic requires the canonical Plan/Apply path test.

Do not run unrelated suites.

## 11.5 E2E

Use focused E2E only for critical user journeys directly affected.

One good scenario is better than five redundant ones.

Do not fake the product-created state when the product behavior itself is what must
be proven.

## 11.6 Broad regression

Do not run hundreds of tests after every atomic UI task.

Broad regression belongs only at a real checkpoint, especially the end of Phase 1
if the shared shell changed significantly, and the final Phase 3 acceptance.

## 11.7 Visual acceptance beats test count

Playwright finding a button does not prove the page is beautiful or understandable.

Automated screenshots are useful evidence.

They do not replace the user's explicit visual approval.

---

# 12. Real visual verification

For meaningful UI work, verify the real result.

Preferred local URL:

`http://localhost:8000`

Do not tell the user to use `127.0.0.1:8000` for the OAuth flow.

The project previously reproduced an OAuth binding failure because the login started
on `127.0.0.1` while Discord returned to `localhost`.

That is tracked as `UX1-T010`.

When visually checking:

- desktop width representative of normal use;
- mobile around 390x844 or equivalent;
- inspect spacing;
- inspect colors;
- inspect overflow;
- inspect menu/drawer behavior;
- inspect touch-friendly controls;
- inspect whether a novice can understand the page immediately.

Compare the result against the 9 approved screenshots.

If it looks technically correct but visually unlike them, the task is not done.

---

# 13. Mobile rules

The approved mobile screenshot is mandatory guidance.

Do not use a permanently visible desktop sidebar on mobile.

Use a mobile-appropriate pattern such as:

- compact top bar;
- drawer;
- bottom navigation where appropriate.

The content should use nearly the full viewport width.

Do not compress a wide desktop table until it becomes unreadable.

Use cards/lists or an explicit horizontal interaction only when truly appropriate.

Menus and popovers must remain inside the viewport.

Primary actions should be reachable and obvious.

---

# 14. Accessibility

Keep accessibility solid, but do not turn the UI into a visually sterile audit tool.

Requirements:

- keyboard navigation;
- visible focus states;
- sufficient contrast;
- color not being the only information channel;
- proper labels;
- reduced motion support;
- touch target sizing on mobile.

Accessibility is a constraint on the approved design, not a reason to abandon it.

---

# 15. i18n

The frontend supports:

- FR
- EN
- DE
- ES

Do not hardcode new product copy in one language if the existing architecture expects
translation keys.

Keep normal user-facing wording simple.

Do not translate internal technical terms into equally technical localized jargon
when the novice UI can avoid the term entirely.

---

# 16. Live tracker protocol — mandatory for every AI

The single operational handoff file is:

`SCREENSHOTS_ESQUISSE/UI_IMPLEMENTATION_LIVE_STATE.md`

This file must make it possible to switch from Codex to Claude or another AI with
zero dependency on chat history.

## Before starting an atomic task

Update the task:

- `Status: IN_PROGRESS`
- implementation intent;
- files expected to change;
- exact `NEXT EXACT ACTION`.

Commit/push this state when useful, especially before a large change.

## During the task

Keep the tracker current after meaningful milestones.

Do not wait until the very end of a multi-hour task.

Record:

- what is actually implemented;
- exact files changed;
- packages added;
- commands/tests actually executed;
- their real result;
- visual evidence actually inspected;
- limitations still present.

Never write "tests pass" if they were not run.

Never write "visual validated" if nobody actually looked at it.

## When a task is DONE

Fill every field:

- Status: DONE
- Purpose
- User problem
- Requirements
- Implementation
- Files
- Packages
- Tests executed
- Visual evidence
- Commit
- Known limitations
- NEXT EXACT ACTION

A task is not DONE just because code compiles.

For UI work it must have meaningful visual verification.

## Before stopping for ANY reason

Especially before:

- token/context exhaustion;
- switching AI;
- user pause;
- unexpected blocker;
- end of coding session.

You MUST:

1. update `UI_IMPLEMENTATION_LIVE_STATE.md`;
2. record current HEAD;
3. record worktree state;
4. record the active task;
5. record what is already done;
6. record what remains;
7. record tests actually run;
8. record visual checks actually done;
9. write one precise `NEXT EXACT ACTION`;
10. commit safe work;
11. push the branch when possible.

No critical state may exist only in your conversation.

---

# 17. Commit discipline

Prefer understandable atomic commits.

Examples:

- `feat(ui): add Bunny visual foundation`
- `feat(ui): replace technical navigation with novice shell`
- `feat(ui): rebuild overview for novice users`
- `feat(ui): simplify access workspace`
- `fix(dev): use one canonical OAuth local hostname`
- `docs(ui): update phase 1 live handoff`

Do not create a commit for every tiny CSS line.

Do not accumulate an enormous uncommitted rewrite for hours.

Tracker and code commits should make recovery obvious.

Push regularly enough that another AI can continue from the remote branch.

---

# 18. Things you must NOT do

Do not:

- invent a new visual style;
- make the app dark by default;
- use a single accent color everywhere;
- return to the old UI;
- surface raw `UNKNOWN` as a primary state;
- expose raw IDs/bitfields to novice users;
- add walls of permanent help text;
- add another left-nav item for every technical feature;
- recreate standard UI components from scratch when Mantine covers them;
- add competing UI frameworks;
- create Phase 1.1 / 1.2 / 1A / Lot A / Sprint A;
- start Phase 2;
- start Phase 3;
- mark tasks DONE from tests alone;
- run huge unrelated backend suites for CSS changes;
- claim a test ran when it did not;
- claim visual acceptance without actual inspection;
- rely on conversation memory instead of the tracker;
- leave an AI handoff only in chat.

---

# 19. If the screenshots and existing functionality conflict

Do not silently remove capability.

Use this priority:

1. preserve functional/business truth from canonical product specs;
2. preserve safety/security boundaries;
3. preserve the approved visual language;
4. simplify how the capability is exposed;
5. place technical complexity behind progressive disclosure.

If a real functional requirement cannot fit the exact screenshot literally, adapt the
layout minimally and document the reason in the live tracker.

Do not use this as an excuse to redesign the whole page.

---

# 20. Phase 1 completion gate

Do not declare Phase 1 complete on your own.

Phase 1 requires user visual approval.

Before asking for that approval, the implemented app must provide at least:

- approved-style Home desktop;
- approved-style Build/Structure desktop;
- approved-style Access desktop;
- approved-style Roles presentation where relevant;
- approved-style mobile shell;
- human error/status states;
- Bunny Server Assistant branding;
- no user-facing DID;
- consistent colors/tokens;
- significantly reduced verbosity;
- no permanent mobile sidebar;
- local OAuth hostname issue resolved;
- relevant targeted tests only;
- real browser visual evidence.

Then stop and ask for human validation.

Do not continue into Phase 2 until the user explicitly approves.

---

# 21. First action for a fresh AI session

After reading this file and the other canonical references:

1. inspect `UI_IMPLEMENTATION_LIVE_STATE.md`;
2. find any `IN_PROGRESS` task and resume it;
3. if none is active, follow its `NEXT EXACT ACTION`;
4. at the current baseline, begin with `UX1-T009` unless the tracker has advanced;
5. inventory current custom UI primitives and current package.json;
6. update the tracker before implementation;
7. implement using the approved stack and exact screenshot direction;
8. verify visually;
9. update tracker + commit + push.

Do not ask the user to restate the plan unless there is a real product ambiguity not
covered by the canonical files.

---

# 22. Final reminder

This project previously spent substantial effort proving technical behavior while the
actual UI remained unpleasant.

Do not repeat that failure mode.

For Phase 1:

**visual quality + simplicity + novice comprehension are first-class product
requirements.**

Tests support those requirements.

Tests do not replace them.

The 9 approved screenshots are the visual contract.

The live tracker is the operational contract.

