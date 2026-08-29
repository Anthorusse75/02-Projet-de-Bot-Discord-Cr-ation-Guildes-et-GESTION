# État courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_08_IMPLEMENTATION_IN_PROGRESS` |
| Last completed/integrated stage | `STAGE_07_REACT_DASHBOARD_I18N_AND_INTERACTIONS` |
| Base main | `252a4661195a3868acd04a2987453e23fc6ee4ff` |
| Branch | `stage/08-multilingual-topology` |
| Pull request | `#8`, Draft, non mergée |
| Last migration | `0015_stage_08`; parent `0014_stage_08`, puis `0013_stage_07`; tête unique et downgrade/re-upgrade PostgreSQL validés |
| Implementation | Correctifs de deep review en cours : autorité backend, isolation intra-Guild, lifecycle Scope × Language, clone 06→05, drift Gateway, actions UI et preuve live réelle |
| Data model | Tables STAGE 08 tenant-scoped avec clés/FK composites, FORCE RLS, IDs logiques stables et CAS groupe/routes |
| Tests status | Les anciens gates restent historiquement verts mais leurs preuves sont jugées insuffisantes par la deep review ; nouvelle qualification complète requise |
| Traceability | Les 43 IDs `REQ-I18N-001..042` + `REQ-I18N-026A` sont repassés `IN_PROGRESS` pendant la réévaluation de l’implémentation et des preuves |
| Discord live status | Preuve précédente invalidée : elle ne mutait pas réellement les Guilds via le pipeline DID ; nouveau scénario A/B et cleanup par plans requis |
| GitHub publication | Draft PR #8 ouverte, non approuvée au merge ; correctifs à publier sans rebase, squash ni force-push |
| Next stage | `STAGE_09_NOT_STARTED_FORBIDDEN_UNTIL_STAGE08_MERGED` |
| Known limitations | Findings externes 1–23 ouverts ; le provider manuel reste un état supporté mais son orchestration et sa vérification doivent être prouvées |

Le détail d’architecture, les invariants et les preuves sont dans
[`STAGE_08_HANDOFF.md`](../90_handoffs/STAGE_08_HANDOFF.md). STAGE 08 est de nouveau en implémentation
active sur sa branche et sa Draft PR. `main` reste au dernier stage intégré STAGE 07 ; STAGE 09 n’a
pas commencé.
