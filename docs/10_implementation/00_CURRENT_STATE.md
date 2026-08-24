# Etat courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_06_COMPLETE_PR_OPEN` |
| Last completed stage | `STAGE_06_CLONE_TEMPLATES_PORTABLE_ARTIFACTS` |
| Base main | `f4dfc635ecc0de0697c034c26000638c3356a3fd` |
| Branch | `stage/06-portability` |
| Tested implementation head | `559ad52785fe0aadc34a1181fecf31204a0024e8` |
| Last migration | `0010_stage_06` ; parent `0009_stage_05` ; une seule tete |
| Implementation | Portable Artifact immutable et canonique; stockage owner chiffre AES-256-GCM avec envelope et rotation; import fichier hostile borne; Dependency Graph; Mapping Resolver explicite; COPY_AS_NEW, MERGE, RECONCILE et MAXIMUM_COMPATIBLE; templates tenant-prives; clipboard/library owner-prives; transferts A vers B sans federation; plan STAGE 05 exclusivement B. |
| Authorization | Lecture/export A via `STRUCTURE_READ`; compilation B via `PLANS_CREATE` + `STRUCTURE_WRITE`; templates via `TEMPLATES_READ/WRITE`; apply via `PLANS_APPLY` STAGE 05. Les autorisations A/B sont independantes et l'artifact ne confere aucune capability. |
| Tests status | PASS sur `559ad52785fe` : STAGE 01, 02, 03, 03-load, 04, 05, 05-failure-injection, 05-load, 06 default et 06 security. STAGE 06 default couvre 233 tests unitaires, 73 integration, matrice migrations, RLS PostgreSQL, frontend et charge; security couvre 17 cas hostiles. |
| Discord live status | PASS sur `559ad52785fe` : export A, graph/mapping, deux plans B, nouveaux IDs COPY_AS_NEW, mapping role explicite, artifact stocke sans relecture A, snapshot A identique, zero mutation A et cleanup audite complet. Live RECONCILE non force; scope exact prouve en integration. |
| Traceability | 246/246 REQ et 35 ADR. `REQ-TEN-008`, `REQ-TEN-011..014` et `REQ-DUP-001..019` sont `IMPLEMENTED`. `REQ-STR-008/011/013` restent `PLANNED` pour l'UI STAGE 07; `REQ-I18N-008` reste `PLANNED` pour STAGE 08. |
| GitHub publication | Draft PR [#6](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/6), non mergee; revue externe obligatoire. |
| Evidence storage | STAGE 01 `20260824T213842023114Z-559ad52785fe-local-docker`; STAGE 02 `20260824T213953257903Z-559ad52785fe-local-docker`; STAGE 03 `20260824T214105559854Z-559ad52785fe-local-docker`; STAGE 03 load `20260824T214228432404Z-559ad52785fe-local-docker`; STAGE 04 `20260824T214256436671Z-559ad52785fe-local-docker`; STAGE 05 `20260824T214436666098Z-559ad52785fe-local-docker`; failure-injection `20260824T214610074205Z-559ad52785fe-local-docker`; load `20260824T214625261146Z-559ad52785fe-local-docker`; STAGE 06 default `20260824T214705015922Z-559ad52785fe-local-docker`; security `20260824T213832331816Z-559ad52785fe-local-docker`; live `20260824T213355960201Z-559ad52785fe-local-docker`. |
| Known limitations | Hash sans signature/authenticite; aucun membre, message, historique ou audit; aucun bot/webhook installe automatiquement; RECONCILE live non force; aucune UI STAGE 07. |
| Next stage | `STAGE_07_FORBIDDEN_BEFORE_STAGE_06_MERGE` |

Le detail est dans [`STAGE_06_HANDOFF.md`](../90_handoffs/STAGE_06_HANDOFF.md) et la preuve live expurgee dans [`STAGE_06_LIVE_EVIDENCE.json`](../90_handoffs/STAGE_06_LIVE_EVIDENCE.json). STAGE 06 est complete en Draft PR, non mergee. STAGE 07 n'a pas ete commencee et reste interdite avant merge normal et revue externe.
