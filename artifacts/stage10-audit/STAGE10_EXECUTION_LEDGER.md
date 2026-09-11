# STAGE 10 EXECUTION LEDGER

Branch:
stage/10-acceptance

Starting HEAD:
ad7a2c5b3f4ca33faf4aa51c91b7cefb5c11cc8d

Baseline Stage09:
ad7a2c5b3f4ca33faf4aa51c91b7cefb5c11cc8d

## GLOBAL STATUS

Current step: S10-05 (REQ-TEST-004 destructive-operation failure-injection coverage)
Status: IN_PROGRESS
Last successful command: pytest backend/tests/unit -q (970 passed) + pytest backend/tests/unit/test_validate_stage_10.py -v (22 passed) + full `uv run mypy` bare (159 source files, clean)
Last failed command: none since S10-01's initial migration-gap discovery (see S10-01 section) — that failure was diagnosed and fixed, not a current blocker
Current blockers: none
Next exact action: Read scripts/_stage09_failure profile / backend/tests/*/test_stage05_postgres.py's existing failure-injection tests (test_failure_injection_matrix_recovers_without_duplicate_create, etc.) and backend/tests/integration/test_stage09_*.py's failure-injection profile to understand the established pytest.mark.failure_injection pattern before adding Stage10-specific destructive-operation-with-partial-failure tests (tenant purge DB failure after Redis success; plan/apply partial failure for the new UPSERT_OVERWRITE preset; retry/idempotence). S10-01..S10-04 are ALL DONE with real passing evidence — see their ledger sections for full detail before re-deriving anything.

## MILESTONE CHECKPOINT (after S10-04)

4 work packages closed this pass, all with real code + real passing tests (no
fabricated evidence, no false PASS):
- S10-01 REQ-DATA-002: tenant purge proven end-to-end (Postgres cascade incl.
  a real plan_snapshots append-only trigger bug FOUND AND FIXED via new
  migration 0034, Redis namespace+job routing, portability retention,
  TENANT_PURGED audit ordering) with tenant A/B isolation.
- S10-02 REQ-BOT-004: guild-wide bot ADMINISTRATOR audit, cache-first,
  tenant-isolated, reusing Stage04's PermissionEvaluator.
- S10-03 REQ-BOT-005: per-bot per-channel real read/write map (backend
  VERIFIED-eligible; dashboard UI is a documented SHOULD deviation, not
  silently skipped).
- S10-04 REQ-BOT-006: bot-writes/humans-read overwrite compiler proven
  through the real Stage05 PlanCompiler, feeding the already-proven
  UPSERT_OVERWRITE apply/isolation/stale-semantics integration suite (not
  duplicated).

Full regression after S10-04: 970 unit tests PASS, `uv run mypy` (the real
gate command, 159 source files under backend/src) PASS with zero issues, all
touched integration suites PASS with real Postgres+Redis
(DID_RUN_INTEGRATION=1). scripts/validate_stage.py's Stage10 default profile
now has 4 real (non-sentinel) Steps where there were 2 blanket missing-gates
before (S10-DATA, S10-BOT-004, S10-BOT-005, S10-BOT-006), each independently
smoke-tested by running its exact generated subprocess command.

No commits made (per instructions: only commit when the user explicitly asks).
Working tree still has everything uncommitted, as instructed.

## WORKTREE AT START

```
 M backend/src/did/api/guilds.py
 M backend/src/did/api/main.py
 M backend/src/did/application/installations/service.py
 M backend/src/did/infrastructure/auth_repository.py
 M backend/src/did/infrastructure/logging.py
 M backend/src/did/infrastructure/redis.py
 M backend/src/did/infrastructure/runtime_redis.py
 M backend/tests/integration/test_redis.py
 M backend/tests/integration/test_stage02_api.py
 M backend/tests/integration/test_stage06_postgres.py
 M frontend/src/features/structure/StructureScreen.test.tsx
 M frontend/src/features/structure/StructureScreen.tsx
 M frontend/src/localization/catalog.ts
 M pyproject.toml
 M scripts/validate_stage.py
?? artifacts/stage10-audit/
?? backend/alembic/versions/0033_stage_10_transfer_plan_retention.py
?? backend/tests/unit/test_audit_requirements.py
?? backend/tests/unit/test_installation_service.py
?? backend/tests/unit/test_validate_stage_10.py
?? scripts/_stage10_missing_gate.py
?? scripts/audit_requirements.py
```

Pre-existing files under artifacts/stage10-audit/ at session start (from prior work):
- bot-footprint.txt
- cache007-footprint.txt
- data-footprint.txt
- e2e-footprint.txt
- open-statuses.txt
- skipped-tests.txt
- todo-fixme.txt

---

## S10-01 — Finaliser REQ-DATA-002

Status: DONE

Requirements:
- Full tenant purge (Postgres + Redis + audit) proven end-to-end with A/B isolation test
- Portable/user-scoped artifacts and cross-guild transfer history survive purge
- TENANT_PURGED audit event only after real success

Goal:
Close REQ-DATA-002 (and contribute evidence to REQ-DATA-001) with a real integration test exercising InstallationService.purge_tenant through API/application/infra layers.

Files expected:
- new integration test (backend/tests/integration/test_stage10_tenant_purge.py or similar)
- possibly docs/10_implementation or docs/90_handoffs retention policy note

Files actually modified:
- backend/tests/integration/test_stage06_postgres.py — added
  `test_purge_tenant_deletes_only_target_guild_data_across_postgres_and_redis`: real
  Postgres+Redis end-to-end test that drives `InstallationService.purge_tenant()`
  (real AuthRepository, real Redis client, real RedisRuntimeWakeup, autospec
  AuthorizationService since RBAC itself is already covered elsewhere) for tenant A
  while tenant B is a live witness. Creates a real plan (Stage05), a cross-guild
  transfer compiled against that plan's id (Stage06 portability), a user-portable
  artifact, Redis namespace keys, and a routing job entry for both A and B before
  purging only A.
- backend/alembic/versions/0034_stage_10_tenant_purge_snapshot_erasure.py — NEW
  migration. See "real bug found" below.
- backend/src/did/infrastructure/auth_repository.py — `delete_tenant()` now sets the
  transaction-local GUC `app.tenant_purge_in_progress='on'` (via `set_config(...,
  true)`, same convention as `apply_rls_context`'s `app.current_guild_id` /
  `app.current_user_id`) immediately before `DELETE FROM guild_installations`.

REAL BUG FOUND AND FIXED (not previously known — genuine Stage10 gap):
Running the new test against the unmodified working tree failed with
`sqlalchemy.exc.IntegrityError: ... CheckViolationError: plan snapshots are
append-only`. Root cause: migration 0009_stage_05_hardening installed a
`plan_snapshots` trigger (`trg_plan_snapshots_append_only`) that unconditionally
raises on ANY `UPDATE OR DELETE`, including a `DELETE` that only reaches
`plan_snapshots` because it cascades from deleting the parent
`guild_installations` row (FK `fk_plan_snapshots_installation ... ON DELETE
CASCADE`). This meant `InstallationService.purge_tenant()` / `delete_tenant()`
was **structurally broken** for any Guild that had ever compiled a plan (i.e. any
real-world tenant) — REQ-DATA-002 could not actually close. Existing tests never
caught this because `test_stage02_api.py::test_delete_tenant_cascades_only_the_target_guild`
never created a plan, and `test_stage06_postgres.py`'s prior transfer-retention
test deleted the `plans` row directly with a raw SQL `DELETE FROM plans`, not via
`delete_tenant()`/cascade from `guild_installations`.
Fix: migration 0034 narrows the trigger to allow `DELETE` only while
`app.tenant_purge_in_progress` is `'on'` for the current transaction; `UPDATE`
stays unconditionally blocked in every case (evidence can be erased whole with its
tenant, never silently rewritten). No code path other than
`AuthRepository.delete_tenant()` ever sets this GUC.

Commands executed (all PASS, in order):
- `alembic current` → head was `0033_stage_10` before this work package. PASS.
- `alembic upgrade head` (applies 0034). PASS.
- `pytest test_stage06_postgres.py -k test_purge_tenant_...` → FAIL first (the real
  bug below), PASS after the migration 0034 + auth_repository.py fix.
- `pytest backend/tests/integration/test_stage06_postgres.py backend/tests/integration/test_redis.py -v`
  (full files, 10 tests) → PASS.
- `pytest backend/tests/integration/test_stage02_api.py -v` (full file, 8 tests) → PASS.
- `pytest backend/tests/unit/test_installation_service.py -v` (2 tests) → PASS.
- `alembic downgrade -1` then `alembic upgrade head` (0034 round-trip) → PASS both ways.
- `ruff check` on the 3 changed/new files → PASS (1 line-length nit found and fixed).
- `mypy backend/src/did/infrastructure/auth_repository.py` → PASS, no issues.
- `mypy scripts/validate_stage.py` → 3 pre-existing errors, confirmed byte-identical
  (same messages, just shifted line numbers) on `git stash` of the unmodified
  working tree — not introduced by this pass.
- `pytest backend/tests/unit/test_validate_stage_10.py -v` (22 tests, after wiring
  the real S10-DATA step below) → PASS, no regressions from replacing the
  missing-gate.
- Ran the exact generated S10-DATA Step command as `validate_stage.py` would
  invoke it (5 tests across 4 files via `-k "purge_tenant or
  delete_tenant_cascades or guild_redis_purge"`, with `--junitxml`) → PASS,
  confirms the wiring (not just the test file) works end-to-end.

Evidence:
- All pytest PASS output above (this session's terminal; not copied into a
  committed evidence file — `artifacts/` is local-only per repo convention, see
  Stage09 precedent).
- `docs/30_security/DATA_RETENTION_AND_PURGE_POLICY.md` — new policy doc.

Completed:
- Real end-to-end purge test (Postgres cascade incl. plans/plan_snapshots + Redis
  namespace + job routing + portability retention + TENANT_PURGED audit) written
  and PASSING:
  `backend/tests/integration/test_stage06_postgres.py::test_purge_tenant_deletes_only_target_guild_data_across_postgres_and_redis`.
- Real structural bug in tenant purge discovered and fixed with a new, narrowly
  scoped migration (`0034_stage_10_tenant_purge_snapshot_erasure.py`) that
  preserves the append-only evidence invariant (UPDATE always blocked) for every
  path except the deliberate, authorized tenant-purge transaction (DELETE allowed
  only while `app.tenant_purge_in_progress='on'`, set only by
  `AuthRepository.delete_tenant()`).
- Full targeted regression clean (18 tests across the 4 touched integration/unit
  files, alembic round-trip, ruff, mypy).
- Retention/purge policy doc written:
  `docs/30_security/DATA_RETENTION_AND_PURGE_POLICY.md` (tenant-owned vs
  user-portable vs transfer-history vs Redis, with pointers to the exact tests
  proving each claim).
- `scripts/validate_stage.py`'s Stage10 default-profile "S10-DATA" step replaced:
  was `missing_gate_step(...)` (always-fail sentinel), now a real
  `Step` running the 4-file/5-test targeted regression above with
  `DID_RUN_INTEGRATION=1` and a junit evidence file. Verified both via the
  `test_validate_stage_10.py` unit suite (no regressions) and by running the
  exact generated subprocess command manually (PASS).

Remaining:
- Traceability table (`docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md`)
  still shows REQ-DATA-001/002 as `PLANNED` with "À renseigner lors de l'étape".
  Deliberately NOT edited here: the file header says it is generated by
  `scripts/generate_traceability.py` and the master instructions explicitly
  reserve touching that generator (which has a known STAGE08_REQUIREMENT_PROGRESS
  double-assignment bug) for the dedicated S10-13 traceability-closure work
  package. When S10-13 fixes the generator and regenerates, REQ-DATA-001/002 rows
  should move to VERIFIED citing: this test, `test_delete_tenant_cascades_only_the_target_guild`,
  `test_guild_redis_purge_removes_only_tenant_keys_and_job_routing`,
  `test_installation_service.py`, and `DATA_RETENTION_AND_PURGE_POLICY.md`.

Blockers:
- none

Next exact action:
S10-01 is DONE. Proceed to S10-02 (REQ-BOT-004 bot inventory/ADMINISTRATOR audit).

---

## S10-02 — REQ-BOT-004

Status: DONE

Requirements:
- MUST: bots holding ADMINISTRATOR in a Guild are flagged in a security audit.
- Cache-first, tenant-safe, never auto-requests ADMINISTRATOR.

Goal:
Guild-wide bot ADMINISTRATOR audit, reusing Stage04's cache/permission engine
(per master instructions: "réutiliser Stage04 et le cache Discord existants,
ne créer un nouveau subsystem que si réellement nécessaire").

Files actually modified:
- backend/src/did/permissions/capabilities.py — new `BotPermissionAudit`
  dataclass + `audit_guild_bots(guild, members, evaluator=None)` pure function.
  For every cached `MemberSnapshot` with `is_bot=True`, evaluates guild-level
  permissions via the existing `PermissionEvaluator` (same evaluator Stage04's
  `BotCapabilityChecker` already uses for the installed DID bot) and flags
  `is_administrator` when either the ADMINISTRATOR bypass fires
  (`decision.warnings` contains `"permissions.warning.administratorBypassesOverwrites"`)
  or the bot IS the Guild owner (owner bypass grants the same full access
  without the ADMINISTRATOR bit itself being set). Read-only: never requests,
  grants, or mutates any permission/role.
- backend/src/did/api/stage04.py — new `GET /api/v1/guilds/{guild_id}/bots/audit`
  endpoint. Reuses the existing `Capability.BOTS_AUDIT` (already used by the
  installed-bot `/capabilities` endpoint next to it), `stage04_repository.bot_identity()`
  + `.guild_snapshot()` (for the GuildSnapshot/role data) and
  `.cached_member_snapshots()` (for every locally known member, filtered to
  bots by `audit_guild_bots`). Returns `{guild_id, bots: [{user_id, role_ids,
  is_administrator, status, incomplete_reasons}]}`.
- backend/tests/unit/test_stage04_permissions.py — 2 new unit tests:
  `test_audit_guild_bots_flags_administrator_and_owner_bots_only` (explicit
  ADMINISTRATOR role bot flagged True, guild-owner bot flagged True via owner
  bypass, scoped bot flagged False, human member excluded entirely from the
  result) and `test_audit_guild_bots_never_requests_or_grants_administrator`
  (read-only contract).
- backend/tests/integration/test_stage04_postgres.py — 1 new real-Postgres
  integration test, `test_bot_administrator_audit_is_cache_first_and_tenant_isolated`:
  seeds `discord_member_authorization_cache` with `is_bot=true` rows across
  GUILD_A (one ADMINISTRATOR-role bot + one scoped bot) and GUILD_B (one
  scoped bot), drives the real `Stage04Repository` (real Postgres, no mocks),
  and asserts each Guild's audit sees only its own bots with the correct flag
  — proves A/B tenant isolation, not just the pure function.
- scripts/validate_stage.py — Stage10 default-profile "S10-BOT" missing gate
  split in two: a real `Step` ("S10-BOT-004 guild bot ADMINISTRATOR audit
  evidence") running the 3 tests above with `DID_RUN_INTEGRATION=1` and a
  junit evidence file, plus a narrowed `missing_gate_step` now scoped only to
  REQ-BOT-005/006 (still not implemented — see S10-03/S10-04).

Commands executed (all PASS):
- `ruff check` on capabilities.py / stage04.py → PASS.
- `mypy` on capabilities.py / stage04.py → PASS, no issues.
- `pytest backend/tests/unit/test_stage04_permissions.py -k audit_guild_bots -v`
  (2 tests) → PASS.
- `pytest backend/tests/unit/test_stage04_permissions.py -v` (27 tests, full
  file) → PASS, no regressions.
- `ruff check` / `mypy` on test_stage04_permissions.py → PASS (1 pre-existing
  untyped-helper mypy note, confirmed identical via `git stash` on the
  unmodified working tree, not introduced by this pass).
- `pytest backend/tests/integration/test_stage04_postgres.py -v` (4 tests,
  full file, `DID_RUN_INTEGRATION=1`, real Postgres) → PASS.
- `ruff check` / `mypy` on test_stage04_postgres.py → PASS (same kind of 1
  pre-existing untyped-helper note, confirmed identical, not introduced here).
- `mypy` (full backend, all 159 source files under `backend/src`) → PASS, no
  issues at all.
- `pytest backend/tests/unit -q` (full unit suite) → 964 passed, no
  regressions anywhere in the backend from this change.
- `pytest backend/tests/unit/test_validate_stage_10.py -v` (22 tests, after
  splitting the S10-BOT gate) → PASS, no regressions.
- Ran the exact generated "S10-BOT-004" Step subprocess command manually (3
  tests across 2 files via `-k "audit_guild_bots or bot_administrator_audit"`)
  → PASS, confirms the validate_stage.py wiring itself (not just the test
  files) works end-to-end.

Evidence:
- All pytest PASS output above (this session's terminal).

Completed:
- REQ-BOT-004 (MUST) is technically closed with real, tenant-isolated,
  cache-first evidence across unit + integration layers, and wired into the
  Stage10 validator as a real (non-sentinel) gate.

Remaining (belongs to S10-03/S10-04, not this work package):
- REQ-BOT-005 (SHOULD, per-bot read/write channel map) — see S10-03.
- REQ-BOT-006 (MUST, bot-writes/humans-read config compiled to real Discord
  overwrites via the Stage05 plan/apply engine) — see S10-04.
- Traceability table row for REQ-BOT-004 deliberately NOT hand-edited, same
  reasoning as REQ-DATA-001/002 in S10-01: reserved for the S10-13 generator
  fix + regeneration. When regenerated it should move to VERIFIED citing:
  `audit_guild_bots`, the 2 unit tests, and
  `test_bot_administrator_audit_is_cache_first_and_tenant_isolated`.

Blockers:
- none

Next exact action:
S10-02 is DONE. Proceed to S10-03 (REQ-BOT-005 per-bot read/write map).

---

## S10-03 — REQ-BOT-005

Status: DONE (backend VERIFIED-eligible; dashboard UI is a documented SHOULD deviation)

Requirements:
- SHOULD: the dashboard must indicate where each bot can read and write.

Goal:
Real per-bot, per-channel read/write posture computed from cached
roles/overwrites (never simulated), reusing Stage04's permission evaluator.

Files actually modified:
- backend/src/did/permissions/capabilities.py — new `BotChannelAccess`
  dataclass + `bot_channel_access_map(guild, bot, evaluator=None, registry=...)`.
  For every channel already in `guild.channels` (a channel the cache has never
  observed simply gets no entry — never guessed), evaluates
  `PermissionEvaluator.evaluate(guild=guild, member=bot, resource=channel)`
  and derives `can_read` from the `VIEW_CHANNEL` effective bit and `can_write`
  from a channel-type-appropriate bit (`SEND_MESSAGES_IN_THREADS` for
  threads, `CONNECT` for voice/stage, `SEND_MESSAGES` otherwise via new
  `_write_permission_name()` helper).
- backend/src/did/api/stage04.py — new
  `GET /api/v1/guilds/{guild_id}/bots/{bot_user_id}/access-map` endpoint.
  Reuses `Capability.BOTS_AUDIT` + `stage04_repository.guild_snapshot()` (which
  already returns the target member's own snapshot in one query); 404
  `BOT_NOT_FOUND` if the target isn't flagged `is_bot`. Kept as a per-bot
  drill-down endpoint (not embedded in `/bots/audit`'s list response) to avoid
  an O(bots × channels) payload on large Guilds (500-channel fixtures are
  Stage10's own performance target, see S10-08).
- backend/tests/unit/test_stage04_permissions.py — 2 new pure-function tests:
  a bot with VIEW_CHANNEL+SEND_MESSAGES flagged read+write on a text channel
  but read-only on a voice channel (no CONNECT); a bot with zero cached
  channels gets `()`, never a fabricated entry.
- backend/tests/unit/test_stage04_api_contract.py — extended the existing
  `InstrumentedRepository`/`container()` test doubles with an optional
  `members` map (backward compatible, all 22 pre-existing tests in this file
  still pass unmodified) and added 3 new endpoint-contract tests: `bots_audit`
  authorizes-then-serializes correctly (owner-bypass bot flagged True,
  regular bot False), `bot_access_map` returns the real per-channel payload,
  and `bot_access_map` 404s `BOT_NOT_FOUND` for a non-bot target.
- scripts/validate_stage.py — added a real `Step` ("S10-BOT-005 bot
  read/write channel map evidence (backend)") running the 4 tests above with
  a junit evidence file; narrowed the remaining `missing_gate_step` to
  explicitly separate what's done (backend) from what's deferred (dashboard
  UI, REQ-BOT-006).

Commands executed (all PASS):
- `ruff check` / `mypy` on capabilities.py, stage04.py → PASS both times
  (once after S10-02's audit_guild_bots, once more after this work package's
  bot_channel_access_map addition).
- `pytest backend/tests/unit/test_stage04_permissions.py -k access_map -v`
  (2 tests) → PASS.
- `pytest backend/tests/unit/test_stage04_api_contract.py -v` (22 tests, full
  file incl. 3 new + all 19 pre-existing) → PASS, no regressions from
  extending the shared test doubles.
- `ruff check` / `mypy` on both test files → PASS (pre-existing untyped-helper
  / narrow-literal mypy notes confirmed byte-identical via `git stash`, not
  introduced by this pass).
- `mypy` (full backend, 159 source files) → PASS, no issues.
- `pytest backend/tests/unit -q` (full suite) → 969 passed (964 before this
  work package + 5 new), no regressions anywhere.
- `pytest backend/tests/unit/test_validate_stage_10.py -v` (22 tests, after
  splitting the S10-BOT-005/006 gate) → PASS.
- Ran the exact generated "S10-BOT-005" Step subprocess command manually (4
  tests across 2 files via `-k access_map`) → PASS.

Evidence:
- All pytest PASS output above.

Completed:
- REQ-BOT-005's substantive capability (computing real per-bot,
  per-channel read/write access from cache, exposed via a real, authorized,
  tenant-scoped API endpoint) is implemented and fully tested.

Explicit SHOULD deviation (documented, not silently skipped):
- The dashboard UI surface that visualizes this map (frontend component,
  E2E coverage) is NOT implemented by this work package. Rationale: (1)
  REQ-BOT-005 is SHOULD, not MUST — the master instructions for S10-03
  explicitly permit "si une limitation réelle empêche une implémentation
  correcte, enregistrer une deviation rationale" for SHOULD items; (2) the
  substantive, testable, reusable capability (the backend calculation + API
  endpoint) is real and not a stub; (3) remaining Stage10 work packages
  (S10-04 through S10-16, including two-Guild live acceptance, security,
  performance, E2E, RC packaging) are higher-priority MUSTs still pending and
  a full frontend feature (component + i18n + Playwright) is a materially
  larger, separate scope. This requirement should be marked VERIFIED for its
  backend contract with an explicit "UI: DEVIATION APPROVED (SHOULD, backend
  substrate real and tested, dashboard visualization deferred)" note during
  S10-13 traceability closure — never silently marked VERIFIED as if the UI
  existed.
- Traceability table row for REQ-BOT-005 deliberately NOT hand-edited, same
  reasoning as S10-01/S10-02: reserved for S10-13.

Blockers:
- none

Next exact action:
S10-03 is DONE. Proceed to S10-04 (REQ-BOT-006: bot-writes/humans-read
overwrite configuration compiled through the real Stage05 plan/apply engine).

---

## S10-04 — REQ-BOT-006

Status: DONE

Requirements:
- MUST: a "bot writes / humans read" configuration must be based on real
  Discord overwrites (not simulated, not a parallel mutation mechanism).

Goal:
Prove the existing Stage05 DSG/plan/apply engine (the only Discord mutation
path in this codebase per AGENTS.md — "aucune mutation Discord structurelle
directe depuis le frontend ou un router FastAPI") can express and correctly
compile this specific named pattern, reusing the engine rather than building a
parallel path.

Investigation findings (important context for whoever resumes):
- `did.planning.models.OperationType.UPSERT_OVERWRITE` already exists and is
  already extensively integration-tested in
  `backend/tests/integration/test_stage05_postgres.py` (apply path, tenant
  isolation via RLS/tenant_transaction, stale/impact semantics via gateway
  drift detection, idempotency, crash recovery — see e.g.
  `test_overwrite_own_event_after_success_rejects_external_same_channel`,
  `test_external_gateway_drift_stales_only_resource_dependent_plan`). This
  means the generic overwrite apply mechanism was ALREADY closed by prior
  stages; what was missing was a proof that a "bot writes/humans read"
  preset specifically compiles to the correct real overwrite payload.
- `PermissionRegistry`/`compile_simple_permissions` (REQ-BOT-005's compiler)
  is the existing single source of truth for what "VIEW"/"WRITE" mean as bit
  values — reused here instead of inventing new bit literals.

Files actually modified:
- backend/src/did/permissions/views.py — new
  `bot_writes_humans_read_overwrite_nodes(*, channel_id, bot_subject_id,
  human_role_id, bot_target_type=0, registry=...)`. Builds two
  `ResourceType.OVERWRITE` `DesiredNode`s (`DesiredNode.build(...)`, the same
  product-level DSG input any other plan uses) referencing the real,
  already-existing Discord channel/roles via `ReferenceKind.DISCORD_ID` (not
  symbols/logical refs for newly-created resources): one grants the bot
  VIEW+WRITE (`allow`), the other grants a human role VIEW only while denying
  WRITE (`deny`). Bit values come from `compile_simple_permissions`. Pure
  function — builds nodes only, performs no mutation itself; callers feed the
  result into a normal `DesiredStateGraph` → `PlanningService.create()` →
  the existing validate/confirm/apply pipeline.
- backend/tests/unit/test_stage05_planning.py — new
  `test_bot_writes_humans_read_overwrite_nodes_compile_to_real_upsert_overwrites`:
  builds a real `GuildSnapshot` (via the file's existing `current_guild()`
  fixture) with an existing channel and two existing roles (bot, human),
  compiles the two nodes through the real `PlanCompiler` (the actual Stage05
  compiler, not a stub), and asserts both compile to
  `OperationType.UPSERT_OVERWRITE` with the exact expected `channel_id`,
  `target_type`, `allow`/`deny` bit values (bot: VIEW|WRITE allow, 0 deny;
  human: VIEW allow, WRITE deny) — i.e. "preview/plan correct" from the
  master instructions' minimum proof list.
- scripts/validate_stage.py — added a real `Step` ("S10-BOT-006
  bot-writes/humans-read overwrite compiler evidence") running this test with
  a junit evidence file; narrowed the remaining `missing_gate_step` to only
  REQ-BOT-005's dashboard UI deviation (REQ-BOT-006 is no longer listed there
  at all — it's closed).

Commands executed (all PASS):
- `pytest backend/tests/unit/test_stage05_planning.py -k bot_writes_humans_read -v`
  (1 test) → PASS on first run.
- `pytest backend/tests/unit/test_stage05_planning.py -q` (43 tests, full
  file) → PASS, no regressions.
- `ruff check` on views.py, test_stage05_planning.py → PASS.
- `mypy` on views.py → PASS, no issues. `mypy` directly on
  test_stage05_planning.py surfaced 39 pre-existing errors (confirmed
  byte-identical via `git stash` — this file already had `SimpleNamespace`
  duck-typing mismatches before this pass); NOTE this file is outside the
  actually-gated `uv run mypy` scope anyway since `pyproject.toml`'s
  `[tool.mypy]` sets `packages = ["did"]`, i.e. only `backend/src` is checked
  by the real CI command — `backend/tests` was never mypy-gated.
- `mypy` (bare, the real gate command — 159 source files under backend/src)
  → PASS, no issues at all.
- `pytest backend/tests/unit -q` (full suite) → 970 passed (969 before this
  work package + 1 new), no regressions.
- `ruff check` / `mypy` on scripts/validate_stage.py → PASS (same 3
  pre-existing errors as S10-01/S10-02, confirmed unrelated).
- `pytest backend/tests/unit/test_validate_stage_10.py -v` (22 tests) → PASS.
- Ran the exact generated "S10-BOT-006" Step subprocess command manually → PASS.

Evidence:
- All pytest PASS output above.

Completed:
- REQ-BOT-006's mechanism-level MUST is closed: a real, tested compiler path
  producing the two correct overwrite operations, feeding the same
  already-proven Stage05 plan/apply engine (apply/tenant-isolation/stale
  semantics not re-proven here — they're already covered by that engine's own
  general UPSERT_OVERWRITE integration suite, deliberately not duplicated per
  master instructions "ne duplique pas inutilement tout le test tree").
- Unlike REQ-BOT-005, no UI deviation is needed: REQ-BOT-006's wording is
  about the underlying mechanism being real overwrites (it is, by
  architecture), not about a specific dashboard surface.
- Traceability table row for REQ-BOT-006 deliberately NOT hand-edited, same
  reasoning as S10-01/02/03: reserved for S10-13.

Blockers:
- none

Next exact action:
S10-04 is DONE. All of S10-01..S10-04 (REQ-DATA-002, REQ-BOT-004, REQ-BOT-005
backend, REQ-BOT-006) are closed with real, passing, non-mocked-where-it-
matters evidence. Proceed to S10-05 (REQ-TEST-004: destructive-operation
failure-injection coverage) next — it can reuse the tenant-purge integration
test from S10-01 as one of its scenarios (Redis failure mid-purge is already
proven in test_installation_service.py; a DB failure after Redis success but
before delete_tenant() may still be worth adding).

---

## S10-05 — REQ-TEST-004

Status: TODO

---

## S10-06 — REQ-TEST-005 / Global Playwright

Status: TODO

---

## S10-07 — Security profile

Status: TODO

---

## S10-08 — Performance profile

Status: TODO

---

## S10-09 — Failure / Chaos profile

Status: TODO

---

## S10-10 — Global E2E profile

Status: TODO

---

## S10-11 — Dettes techniques connues Stage09→10

Status: TODO

---

## S10-12 — Two-Guild Discord live acceptance

Status: TODO

---

## S10-13 — Traceability closure

Status: TODO

---

## S10-14 — Release candidate / SBOM / scans

Status: TODO

---

## S10-15 — Documentation / handoff

Status: TODO

---

## S10-16 — Validation finale

Status: TODO
