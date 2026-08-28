# Etat courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_08_IMPLEMENTATION_IN_PROGRESS` |
| Last completed/integrated stage | `STAGE_07_REACT_DASHBOARD_I18N_AND_INTERACTIONS` |
| Base main | `252a4661195a3868acd04a2987453e23fc6ee4ff` |
| Branch | `stage/08-multilingual-topology` |
| Last migration | `0014_stage_08`; parent `0013_stage_07`; migration corrected for composite-FK tenant-safe constraints and group-scoped validation remains incomplete. |
| Implementation | Stage 08 currently contains an initial domain model and migration scaffold only. The implementation is still in progress and does not yet satisfy the full Stage 08 scope. |
| Data model | `language_profiles`, `member_visible_languages`, `resource_language_policies`, `translation_groups`, category/channel variants/groups, `translation_routes`, `translation_provider_bindings`, and `visibility_scope_language_roles` are present, but must still complete the full service/repository/API/provider/visibility/budget/live surface. |
| Tests status | Local Stage 08 unit proof is partial and intentionally not claimed as complete. The migration and route isolation regressions have been corrected locally; full Stage 08 completion remains pending. |
| Traceability | `REQ-I18N-001..042` + `REQ-I18N-026A` are tracked as not yet all implemented until code, tests, and live evidence exist. The validator and requirement list are still a work-in-progress. |
| Discord live status | `NOT_RUN` / `BLOCKED_LIVE_CREDENTIALS` for Stage 08 until real Discord sandbox credentials and the Stage 08 live gate are prepared. |
| GitHub publication | Draft PR remains in progress; no claim of full Stage 08 completion or green CI is made. |
| Next stage | `STAGE_09_CAMPAIGN_ENGINE_FORBIDDEN` |
| Known limitations | The current branch still does not provide the full application/service/repository/API/UI/visibility/provider/budget/live Stage 08 scope; additional work packages remain open. |

Le détail est dans [`STAGE_08_HANDOFF.md`](../90_handoffs/STAGE_08_HANDOFF.md). Stage 08 est actuellement en cours d’implémentation, sur branche `stage/08-multilingual-topology`, sans prétendre à une candidate complète ni à un merge dans `main`.
