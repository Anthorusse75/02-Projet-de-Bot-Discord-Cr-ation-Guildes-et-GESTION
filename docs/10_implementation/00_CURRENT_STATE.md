# Etat courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_08_IMPLEMENTATION_IN_PROGRESS` |
| Last completed/integrated stage | `STAGE_07_REACT_DASHBOARD_I18N_AND_INTERACTIONS` |
| Base main | `252a4661195a3868acd04a2987453e23fc6ee4ff` |
| Branch | `stage/08-multilingual-topology` |
| Last migration | `0014_stage_08`; parent `0013_stage_07`; composite tenant FKs, group-language membership, RLS and reversible downgrade are validated in PostgreSQL. |
| Implementation | WP1 persistence/repository foundation is delivered; Stage 08 remains in progress and does not yet satisfy the full scope. |
| Data model | Stage 08 tables now include durable `translation_group_languages`, explicit group-scoped variants, provider binding linkage, and tenant-safe constraints; API/provider/visibility/budget/live surface remains open. |
| Tests status | 11 focused unit tests and 5 real PostgreSQL WP1 tests pass; full Stage 08 completion remains pending. |
| Traceability | `REQ-I18N-001..042` + `REQ-I18N-026A` are tracked as not yet all implemented until code, tests, and live evidence exist. The validator and requirement list are still a work-in-progress. |
| Discord live status | `NOT_RUN` / `BLOCKED_LIVE_CREDENTIALS` for Stage 08 until real Discord sandbox credentials and the Stage 08 live gate are prepared. |
| GitHub publication | Draft PR remains in progress; no claim of full Stage 08 completion or green CI is made. |
| Next stage | `STAGE_09_CAMPAIGN_ENGINE_FORBIDDEN` |
| Known limitations | The current branch still does not provide the full application/service/repository/API/UI/visibility/provider/budget/live Stage 08 scope; additional work packages remain open. |

Le détail est dans [`STAGE_08_HANDOFF.md`](../90_handoffs/STAGE_08_HANDOFF.md). Stage 08 est actuellement en cours d’implémentation, sur branche `stage/08-multilingual-topology`, sans prétendre à une candidate complète ni à un merge dans `main`.
