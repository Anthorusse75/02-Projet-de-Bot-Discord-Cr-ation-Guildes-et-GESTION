# Etat courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_06_COMPLETE_PR_OPEN` |
| Last completed stage | `STAGE_06_CLONE_TEMPLATES_PORTABLE_ARTIFACTS` |
| Base main | `f4dfc635ecc0de0697c034c26000638c3356a3fd` |
| Branch | `stage/06-portability` |
| Tested implementation head | `65c735543e4c8e2579da97b8609559eeae4880aa` |
| Last migration | `0012_stage_06` ; parent `0011_stage_06` ; une seule tete |
| Implementation | Portable Artifact immutable et canonique; schemas d'attributs types/bornes fail-closed `did-portable-attributes-v&#50;`; identites logiques opaques stables entre generations; `portable_clone_relationships` owner-scoped et independante des artifacts/transfers; bindings actifs ou tombstones; lifecycle reprenable; mapping fige a READY et COMPILED immutable; MERGE/RECONCILE produisent exclusivement un plan STAGE 05 B. |
| Authorization | Lecture/export A via `STRUCTURE_READ`; compilation B via `PLANS_CREATE` + `STRUCTURE_WRITE`; templates via `TEMPLATES_READ/WRITE`; apply via `PLANS_APPLY` STAGE 05. Les autorisations A/B sont independantes et l'artifact ne confere aucune capability. |
| Tests status | Matrice corrective finale PASS le 2026-08-26 sur `65c735543e4c` : STAGE 01-06, profils load/failure-injection/security, 255 unitaires, 75 integration, 19 security, 24 failure-injection, migrations `base/0001..0011 -> 0012`, `0012 -> 0011`, tete unique, RLS, durabilite, lifecycle et frontend. Preuve STAGE 06 live : `20260826T053113447965Z-d438d05d1d92-local-docker` (worktree ensuite figee en `65c7355`). |
| Discord live status | PASS le 2026-08-26 : A1 COPY/finalize, suppression artifact A1 sans perte de relation, evolution source A2 via STAGE 05, RECONCILE naturel avec reference survivante stable, UPDATE sur le meme ID B, CREATE, DELETE exact, tombstone, temoin B non lie intact, source reader fail-if-called apres export, zero mutation A et cleanup audite de 9 fixtures. |
| Traceability | 246/246 REQ et 35 ADR. `REQ-TEN-008`, `REQ-TEN-011..014` et `REQ-DUP-001..019` sont `IMPLEMENTED`. `REQ-STR-008/011/013` restent `PLANNED` pour l'UI STAGE 07; `REQ-I18N-008` reste `PLANNED` pour STAGE 08. |
| GitHub publication | Draft PR [#6](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/6), non mergee; revue externe obligatoire. |
| Evidence storage | Matrice finale STAGE 06 + live `20260826T053113447965Z-d438d05d1d92-local-docker`; security `20260826T053101193803Z-d438d05d1d92-local-docker`; preuve live expurgee suivie dans `STAGE_06_LIVE_EVIDENCE.json`. Les preuves initiales restent conservees dans l'historique. |
| Known limitations | Hash sans signature/authenticite; aucun membre, message, historique ou audit Discord; aucun bot/webhook installe automatiquement; category `FULL`; text/voice/announcement/stage `PARTIAL` car les flags observes ne sont pas acceptes a la creation; forum/media/directory `UNSUPPORTED`; aucune UI STAGE 07. |
| Next stage | `STAGE_07_FORBIDDEN_BEFORE_STAGE_06_MERGE` |

Le detail est dans [`STAGE_06_HANDOFF.md`](../90_handoffs/STAGE_06_HANDOFF.md) et la preuve live expurgee dans [`STAGE_06_LIVE_EVIDENCE.json`](../90_handoffs/STAGE_06_LIVE_EVIDENCE.json). STAGE 06 est complete en Draft PR, non mergee. STAGE 07 n'a pas ete commencee et reste interdite avant merge normal et revue externe.
