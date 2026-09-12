# Stage 10 Discord-live status

Status: `PASS_QUALIFIED`.

## Canonical qualification

Qualified product commit:

```text
0d9a913cd8171827fd896b16608eb1d583eadb08
```

Canonical evidence run:

```text
20260912T160140123082Z-0d9a913cd817-local-docker
```

Canonical evidence directory:

```text
artifacts/test-evidence/stage-10/
20260912T160140123082Z-0d9a913cd817-local-docker/
```

Required reports and outcomes:

| Report | Outcome |
|---|---|
| `discord-live-02.json` | `PASS_WITH_APPROVED_LIMITATION` |
| `discord-live-03.json` | `PASS_WITH_APPROVED_LIMITATION` |
| `discord-live-04.json` | `PASS_WITH_APPROVED_LIMITATION` |
| `discord-live-05.json` | `PASS` |
| `discord-live-06.json` | `PASS` |
| `discord-live-08.json` | `PASS` |
| `discord-live-09-primitives.json` | `PASS` |
| `discord-live-09-full-chain.json` | `PASS` |

The eight reports belong to the same run and are bound to the same qualified
commit. The promoter generated:

```text
stage10-discord-live-closure.json
```

and the promoted traceability then produced:

```text
245 VERIFIED
1 IMPLEMENTED (REQ-BOT-005, SHOULD)
0 PLANNED
0 MUST not closed
STAGE 10 STRICT CLOSURE: PASS
```

## Execution shape

To avoid keeping the product owner present during the long-running phase, the
same Stage 10 evidence run was executed in two parts:

1. unattended/offline + live 03/04/05/06/08/09 work completed first and wrote
   reports into the canonical run directory;
2. Stage 02 was completed interactively later against the same run directory;
3. the eight-report promotion, qualified traceability render, documentation
   validation and strict requirement closure were then executed against that
   same run.

This split did not fabricate or copy reports from another run.

## Cleanup

Stage 09 full-chain completed all 11 groups and all 60 scenarios. Its cleanup
proof recorded:

```text
created: 42
deletion_attempted: 42
deleted_or_already_absent: 42
failed: 0
remaining: 0
```

Stage 06 purged the two ephemeral portability artifacts and the disposable live
fixtures were removed. No production Guild was involved.

## Approved limitations

Stage 02:

- live administrator non-owner profile;
- live non-administrator profile.

Stage 03:

- external Discord mutation observed through Gateway;
- forced Gateway reconnect/RESUME/non-resumed;
- Channel Obfuscation live visibility change remains contract-only;
- inherited Stage 02 profile limitations.

Stage 04:

- controlled thread membership matrix not created by the read-only runner;
- category synced/desynced mutation fixtures not created by the read-only runner;
- managed/equal hierarchy mutation fixtures not created by the read-only runner;
- inherited Stage 02 human-profile limitations.

Stage 05:

- 429 behavior is contract-tested rather than forced against Discord;
- ambiguous duplicate CREATE is not forced through an unsafe manual live fixture.

Stage 06:

- bot/webhook incompatibilities are security-tested without unsafe live fixtures.

Any other or incomplete limitation set is rejected by the promoter.

## Post-qualification promoter correction

The source live reports were already green, but promotion initially failed on
Stage 05 and then Stage 06 because the promoter incorrectly required strictly
positive values for hygiene counters that are legitimately zero on a clean
sandbox.

The promotion-only rules were corrected without changing any source report:

- Stage 05 allows zero, but never negative, for
  `abandoned_fixture_jobs_resumed`, `terminal_fixture_jobs_acknowledged`, and
  `preexisting_fixtures_cleaned`;
- Stage 06 allows zero, but never negative, for `resumed_portability_jobs`.

The permanent correction is:

```text
16a2e2ce624a088741e6c096c4a827eab7adf4f2
fix(stage10): align promotion counters with clean live sandboxes
```

It adds regression tests proving zero is accepted only for those hygiene
counters while negative values and zero-valued proof counters remain rejected.

This post-qualification tooling commit is not presented as a new Discord-live
qualified commit. The qualified product SHA remains `0d9a913`.

See also:

- [`STAGE_10_HANDOFF.md`](../90_handoffs/STAGE_10_HANDOFF.md)
- [`00_CURRENT_STATE.md`](../10_implementation/00_CURRENT_STATE.md)
