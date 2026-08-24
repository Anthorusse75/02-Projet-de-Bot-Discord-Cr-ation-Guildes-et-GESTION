# Etat courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_06_READY_NOT_STARTED` |
| Last completed stage | `STAGE_05_PLAN_ENGINE` |
| Documentation baseline commit | `c285ac81afb0ec7a3c3197085ceff821a5d1c446` |
| STAGE 01 merge commit | `28774bf26f2fe590562021f567f0e67f623ff7f5` |
| STAGE 02 merge commit | `5b962a24058e399c3703095f2162e1f38e1bfd60` |
| STAGE 03 merge commit | `12ec64c0dda973ad245880aeb28d88c03a9c03b5` |
| STAGE 03 completion tag | `stage-03-complete` -> `12ec64c0dda973ad245880aeb28d88c03a9c03b5` |
| STAGE 04 merge commit | `67f8281bd6b759329c5036fbc9cbd6164b6e5b3c` |
| STAGE 04 completion tag | `stage-04-complete` -> `67f8281bd6b759329c5036fbc9cbd6164b6e5b3c` |
| STAGE 05 base / branch | `f64c8253e6b7ec648d7161531344a2999b78ffe7` / `stage/05-plan-engine` |
| STAGE 05 approved head | `8d000b578f95793b42a84fb8e8a3aa01c296590a` |
| STAGE 05 merge commit | `c0ef8abe696e2f6caeb51840499751ef2fb36c83` ; parents `f64c8253e6b7ec648d7161531344a2999b78ffe7` et `8d000b578f95793b42a84fb8e8a3aa01c296590a` |
| STAGE 05 completion tag | `stage-05-complete` -> `c0ef8abe696e2f6caeb51840499751ef2fb36c83` |
| Last migration | `0009_stage_05` ; parent `0008_stage_05` ; une seule tete |
| Corrective implementation | Autorisation sensible API et worker avec targeted member refresh; confirmation liee a l'acteur; idempotence actor-scoped; operation PK plan-scoped; immutabilite SQL INSERT/UPDATE/DELETE et snapshot append-only; hash relu avant validation; preconditions par operation; recovery channel/role distinct; expected Gateway bulk/overwrite strict; index des plans concernes; Impact Engine STAGE 04; sequence atomique; lease-loss fence exact; hierarchie role globale et JIT strictement inferieure; gardes managed/@everyone; REORDER avec items REST explicites separes du segment final attendu |
| Tests status | Post-merge PASS sur `c0ef8abe696e` : validate_stage 01, 02, 03, 03-load, 04, 05, 05-failure-injection et 05-load. Ruff, format, mypy sur 89 fichiers, migrations base/0001..0007 -> 0009, RLS, docs, secrets et frontend lint/typecheck/tests/build PASS. Profil complet : 204 unit, 72 integration, 24 failure-injection, 4 frontend et DSG 500 noeuds. Aucune regression STAGE 01-04. |
| Discord live status | Post-merge `PASS` sur `c0ef8abe696e` : six plans reussis; CREATE/UPDATE/MOVE/REORDER/UPSERT/DELETE reels; crash apres reponse CREATE_ROLE recupere avec exactement un appel CREATE et symbol binding durable; ordre des roles restaure; cleanup audite complet; aucune fixture prefixee restante. |
| Required external configuration | Satisfaite dans la Guild sandbox B : `MANAGE_CHANNELS` et `MANAGE_ROLES` sont presents, `ADMINISTRATOR` n'est pas requis. Aucune action restante. |
| Known failures | Aucune regression post-merge. Les limites volontaires restent la non-provocation d'un 429 live et d'un doublon CREATE ambigu; leurs contrats fail-safe sont testes localement. |
| Documentation status | PASS - 11 stages, 246/246 REQ et 35 ADR. Handoff, strategie, matrice sandbox, evidence live, decisions et tracabilite sont corriges; `REQ-UX-006/007` restent `PLANNED`. |
| GitHub publication | PR #5 mergee le `2026-08-24T18:31:24Z` par merge commit normal; branche `stage/05-plan-engine` conservee. |
| Evidence storage | Post-merge sur `c0ef8abe696e` : Stage 01 `20260824T183204169014Z-c0ef8abe696e-local-docker`; Stage 02 `20260824T183312135095Z-c0ef8abe696e-local-docker`; Stage 03 `20260824T183433777812Z-c0ef8abe696e-local-docker`; Stage 03 load `20260824T183555617865Z-c0ef8abe696e-local-docker`; Stage 04 `20260824T183623059349Z-c0ef8abe696e-local-docker`; Stage 05 `20260824T183756694877Z-c0ef8abe696e-local-docker`; failure-injection `20260824T183946011571Z-c0ef8abe696e-local-docker`; load `20260824T184002356291Z-c0ef8abe696e-local-docker`; exact live `20260824T184103337452Z-c0ef8abe696e-local-docker`. Preuve live expurgee suivie dans `docs/90_handoffs/STAGE_05_LIVE_EVIDENCE.json`. |
| Next stage | `STAGE_06_READY_NOT_STARTED` |

Le detail est dans [`STAGE_05_HANDOFF.md`](../90_handoffs/STAGE_05_HANDOFF.md). STAGE 05 est mergee et cloturee. STAGE 06 est autorisee mais n'a pas ete commencee.
