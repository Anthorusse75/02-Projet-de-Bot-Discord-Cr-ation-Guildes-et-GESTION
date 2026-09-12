# Stage 10 technical-debt disposition

The three non-blocking observations handed off by Stage 09 are dispositioned:

| Observation | Stage 10 disposition | Evidence |
|---|---|---|
| Four frontend dependency findings (2 moderate, 2 high) | Resolved by locked Vitest/Redocly/js-yaml updates | `npm audit --audit-level=moderate`: zero vulnerabilities |
| Frontend production chunk above 500 kB | Resolved by route-level lazy loading | largest production chunk: 485.50 kB; build emits no chunk warning |
| `logging.unstructured_rejected` during Discord live runs | Accepted security behavior, not data loss or leakage | `JsonFormatter` deliberately refuses to render free-form third-party messages; unit tests prove the payload is omitted and sensitive fields are recursively redacted |

The logging event remains intentionally visible: converting an unregistered
third-party message into a registered application event would create a false
semantic claim, while rendering it could leak identifiers or credentials. It
therefore remains a safe diagnostic and is not suppressed without a concrete
operational impact.

Repository scans found no executable-code TODO/FIXME. Integration and outbound
network skips are explicit environment gates only; canonical Stage 10 local
profiles set `DID_RUN_INTEGRATION=1`, while real network/live profiles remain
separately authorized.
