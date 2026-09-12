# Stage 10 performance acceptance

Canonical command:

```text
python scripts/validate_stage.py 10 --profile performance
```

Passing evidence:
`artifacts/test-evidence/stage-10/20260911T203208291576Z-ca48bd8ebfbf-local-docker/summary.json`.

| Scenario | Scale | Budget | Observed |
|---|---:|---:|---:|
| Permission posture | 500 channels, 250 roles, one channel at 1,000 overwrites | < 5 s | 0.962308 s |
| Browser structure tree | 500 rendered tree items | < 5 s | 0.555 s test body |
| Plan compiler | 500 nodes/operations | < 3 s | 0.015975 s |
| Clone compiler | 600 portable resources | each phase < 10 s | slowest phase 0.004848 s |
| Durable governor | 300 noisy-Guild + 30 quiet-Guild jobs | no starvation; quiet Guild within 2 slots | first quiet slot 1; 330 succeeded |

The same 11-test load run also covers campaign backlog priority, critical
reconcile, bounded backpressure, two-worker distributed permits and stale-lease
recovery. Tests are deterministic and use synthetic/fake Discord work; the
durable governor scenarios use real local PostgreSQL and Redis.
