# Etat courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_07_READY_NOT_STARTED` |
| Last completed stage | `STAGE_06_CLONE_TEMPLATES_PORTABLE_ARTIFACTS` |
| STAGE 06 approved head | `505a052e397bbb7eb881cfc7111fb2831c573130` |
| STAGE 06 tested code | `0f129dd36e618b4774621379b6f7c38b613b2064` |
| STAGE 06 merge commit | `5eb4215e4ca8307230fb7fc4f253e2878eb3d8b0` |
| Tag | `stage-06-complete` -> `5eb4215e4ca8307230fb7fc4f253e2878eb3d8b0` |
| Branch | `main` ; `stage/06-portability` conservee a `505a052e397bbb7eb881cfc7111fb2831c573130` |
| Last migration | `0012_stage_06` ; parent `0011_stage_06` ; une seule tete |
| Implementation | Portable Artifact immutable et canonique; schemas d'attributs types/bornes fail-closed `did-portable-attributes-v&#50;`; identites logiques opaques stables entre generations; `portable_clone_relationships` owner-scoped et independante des artifacts/transfers; bindings actifs ou tombstones; lifecycle reprenable; READY fige le mapping semantique complet (intent explicite + decisions resolues) et refuse tout drift B avant planification; COMPILED immutable; MERGE/RECONCILE produisent exclusivement un plan STAGE 05 B. |
| Authorization | Lecture/export A via `STRUCTURE_READ`; compilation B via `PLANS_CREATE` + `STRUCTURE_WRITE`; templates via `TEMPLATES_READ/WRITE`; apply via `PLANS_APPLY` STAGE 05. Les autorisations A/B sont independantes et l'artifact ne confere aucune capability. |
| Tests status | Matrice post-merge PASS le 2026-08-27 sur `5eb4215e4ca8` : STAGE 01-06, profils load/failure-injection/security, 261 unitaires, 76 integration, 20 security, 24 failure-injection, migrations `base/0001..0011 -> 0012`, `0012 -> 0011`, current/head unique `0012_stage_06`, RLS, durabilite, lifecycle, drift READY et frontend. |
| Discord live status | PASS post-merge le 2026-08-27 sur `5eb4215e4ca8`, run `20260827T050419752517Z-5eb4215e4ca8-local-docker` : A1 COPY/finalize, suppression artifact A1 sans perte de relation, evolution source A2 via STAGE 05, RECONCILE naturel avec reference survivante stable, UPDATE sur le meme ID B, CREATE, DELETE exact, tombstone, temoin B non lie intact, source reader fail-if-called apres export, zero mutation A et cleanup audite de 9 fixtures. |
| Traceability | 246/246 REQ et 35 ADR. `REQ-TEN-008`, `REQ-TEN-011..014` et `REQ-DUP-001..019` sont `IMPLEMENTED`. `REQ-STR-008/011/013` restent `PLANNED` pour l'UI STAGE 07; `REQ-I18N-008` reste `PLANNED` pour STAGE 08. |
| GitHub publication | PR [#6](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/6) mergee normalement dans `main` le 2026-08-27 a `04:53:35Z`; branche STAGE 06 conservee. |
| Evidence storage | Post-merge : STAGE 01 `20260827T045410656182Z-5eb4215e4ca8-local-docker`; STAGE 02 `20260827T045523031060Z-5eb4215e4ca8-local-docker`; STAGE 03 `20260827T045641530287Z-5eb4215e4ca8-local-docker`; STAGE 03 load `20260827T045803864793Z-5eb4215e4ca8-local-docker`; STAGE 04 `20260827T045829453010Z-5eb4215e4ca8-local-docker`; STAGE 05 `20260827T045952522005Z-5eb4215e4ca8-local-docker`; failure-injection `20260827T050128813057Z-5eb4215e4ca8-local-docker`; STAGE 05 load `20260827T050144214941Z-5eb4215e4ca8-local-docker`; STAGE 06 `20260827T050151339773Z-5eb4215e4ca8-local-docker`; security `20260827T050327056485Z-5eb4215e4ca8-local-docker`; live `20260827T050419752517Z-5eb4215e4ca8-local-docker`. Les preuves approuvees anterieures restent conservees dans l'historique. |
| Known limitations | Hash sans signature/authenticite; aucun membre, message, historique ou audit Discord; aucun bot/webhook installe automatiquement; category `FULL`; text/voice/announcement/stage `PARTIAL` car les flags observes ne sont pas acceptes a la creation; forum/media/directory `UNSUPPORTED`; aucune UI STAGE 07. |
| Next stage | `STAGE_07_READY_NOT_STARTED` |

Le detail est dans [`STAGE_06_HANDOFF.md`](../90_handoffs/STAGE_06_HANDOFF.md) et la preuve live expurgee dans [`STAGE_06_LIVE_EVIDENCE.json`](../90_handoffs/STAGE_06_LIVE_EVIDENCE.json). STAGE 06 est integree dans `main`. STAGE 07 est autorisee mais n'a pas ete commencee.
