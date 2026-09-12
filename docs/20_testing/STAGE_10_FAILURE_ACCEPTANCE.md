# Stage 10 failure and chaos acceptance

Canonical command:

```text
python scripts/validate_stage.py 10 --profile failure-injection
```

Passing evidence:
`artifacts/test-evidence/stage-10/20260911T203345229287Z-ca48bd8ebfbf-local-docker/summary.json`.

The repository-wide `failure_injection` matrix ran without a name filter:
191 passed, 1,085 deselected. It covers transaction rollback, Redis outage,
Discord 401/403/5xx and ambiguous transport outcomes, worker and scheduler crash
windows, leases/fencing, duplicate and replayed events, ordering/cycle guards,
tenant purge recovery, targeted-refresh coalescing, campaign fan-out/delivery,
unknown-outcome reconciliation and no-duplicate external actions.

The profile also requires lock synchronization, repository-wide Ruff and mypy,
and migration to the current Alembic head before executing the matrix.
