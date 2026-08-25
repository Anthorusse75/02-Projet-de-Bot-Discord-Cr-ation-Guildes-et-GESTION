# Etat courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_06_COMPLETE_PR_OPEN` |
| Last completed stage | `STAGE_06_CLONE_TEMPLATES_PORTABLE_ARTIFACTS` |
| Base main | `f4dfc635ecc0de0697c034c26000638c3356a3fd` |
| Branch | `stage/06-portability` |
| Tested implementation head | `71faa95ff21ac4d990ccc6b89d3fa4b22e6ea305` |
| Last migration | `0011_stage_06` ; parent `0010_stage_06` ; une seule tete |
| Implementation | Portable Artifact immutable et canonique; schemas d'attributs fail-closed `did-portable-attributes-v&#50;`; stockage owner chiffre; relation de clone et bindings destination RLS; MERGE applique les proprietes portables sur l'identite B; RECONCILE derive son scope destructif uniquement des bindings serveur; MAXIMUM_COMPATIBLE est report-only avec `destination_plan_id=NULL`; plan STAGE 05 exclusivement B. |
| Authorization | Lecture/export A via `STRUCTURE_READ`; compilation B via `PLANS_CREATE` + `STRUCTURE_WRITE`; templates via `TEMPLATES_READ/WRITE`; apply via `PLANS_APPLY` STAGE 05. Les autorisations A/B sont independantes et l'artifact ne confere aucune capability. |
| Tests status | Matrice corrective finale PASS sur `71faa95ff21ac` : STAGE 01-06, profils load/failure-injection/security, 241 unitaires, 75 integration, migrations jusqu'a la tete unique `0011`, RLS, quotas count/bytes concurrents, audit idempotent, mapping/lifecycle et frontend. Preuve STAGE 06 finale : `20260825T061252707811Z-71faa95ff21a-local-docker`. |
| Discord live status | PASS correctif le 2026-08-25 dans la matrice officielle : COPY_AS_NEW, divergence role/channel B puis MERGE depuis artifact avec source reader fail-if-called, slowmode et auto-archive non par defaut, preview RECONCILE d'un seul binding possede, suppression exacte et controle B non lie intact; zero mutation A et cleanup audite de 9 fixtures. |
| Traceability | 246/246 REQ et 35 ADR. `REQ-TEN-008`, `REQ-TEN-011..014` et `REQ-DUP-001..019` sont `IMPLEMENTED`. `REQ-STR-008/011/013` restent `PLANNED` pour l'UI STAGE 07; `REQ-I18N-008` reste `PLANNED` pour STAGE 08. |
| GitHub publication | Draft PR [#6](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/6), non mergee; revue externe obligatoire. |
| Evidence storage | Matrice finale STAGE 06 + live `20260825T061252707811Z-71faa95ff21a-local-docker`; security `20260825T061237702152Z-71faa95ff21a-local-docker`; preuve live expurgee suivie dans `STAGE_06_LIVE_EVIDENCE.json`. Les preuves initiales restent conservees dans l'historique. |
| Known limitations | Hash sans signature/authenticite; aucun membre, message, historique ou audit Discord; aucun bot/webhook installe automatiquement; forum/media/directory declares `UNSUPPORTED`; flags de creation de channel peuvent etre `PARTIAL`; aucune UI STAGE 07. |
| Next stage | `STAGE_07_FORBIDDEN_BEFORE_STAGE_06_MERGE` |

Le detail est dans [`STAGE_06_HANDOFF.md`](../90_handoffs/STAGE_06_HANDOFF.md) et la preuve live expurgee dans [`STAGE_06_LIVE_EVIDENCE.json`](../90_handoffs/STAGE_06_LIVE_EVIDENCE.json). STAGE 06 est complete en Draft PR, non mergee. STAGE 07 n'a pas ete commencee et reste interdite avant merge normal et revue externe.
