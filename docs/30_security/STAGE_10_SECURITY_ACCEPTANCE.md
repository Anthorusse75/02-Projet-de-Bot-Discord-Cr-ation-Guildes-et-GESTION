# Stage 10 security acceptance

## Verdict

The local-docker security profile passes without a placeholder gate. The
canonical command is:

```text
python scripts/validate_stage.py 10 --profile security
```

Successful evidence:
`artifacts/test-evidence/stage-10/20260911T202543813419Z-ca48bd8ebfbf-local-docker/summary.json`.

## Covered boundaries

- API traversal verifies that every private operation below the versioned API prefix carries the
  authenticated-session dependency and every mutation carries the CSRF
  dependency. The small read-only POST allow-list is asserted exactly.
- Real ASGI requests verify security headers plus credentialed CORS acceptance
  and rejection. Settings reject wildcard, malformed, user-info-bearing, or
  non-HTTP(S) origins; production CORS and OAuth redirects require HTTPS.
- PostgreSQL catalog inspection verifies that every tenant/user-scoped table has
  enabled and forced RLS and at least one policy. The runtime `did_app` role is
  neither superuser nor `BYPASSRLS`.
- The global backend security suite covers tenant A/B isolation, Redis and
  WebSocket boundaries, IDOR, OAuth/session/CSRF, SSRF, redaction and CSP.
- Validation subprocesses never inherit `NODE_TLS_REJECT_UNAUTHORIZED=0`.
  The locked frontend dependency tree has zero audit findings at the moderate
  threshold.
- Frontend API-client and localization tests verify session isolation and safe
  rendering behavior.

## Result summary

- Backend security suite: 853 passed, 423 deselected.
- OAuth/session/logging/settings contracts: 21 passed.
- Frontend session/locale safety tests: 7 passed.
- Secret scan: 487 repository files checked, passed.
- Frontend dependency audit: zero vulnerabilities.

Discord-live assertions remain separate and require the two authorized sandbox
Guilds defined by the Stage 10 live acceptance procedure.
