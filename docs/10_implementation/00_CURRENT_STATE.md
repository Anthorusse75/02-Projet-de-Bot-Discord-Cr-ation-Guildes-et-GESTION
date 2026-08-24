# Etat courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_05_CORRECTIVE_REVIEW_COMPLETE_PR_OPEN` |
| Last completed stage | `STAGE_04_READ_PERMISSIONS` |
| Documentation baseline commit | `c285ac81afb0ec7a3c3197085ceff821a5d1c446` |
| STAGE 01 merge commit | `28774bf26f2fe590562021f567f0e67f623ff7f5` |
| STAGE 02 merge commit | `5b962a24058e399c3703095f2162e1f38e1bfd60` |
| STAGE 03 merge commit | `12ec64c0dda973ad245880aeb28d88c03a9c03b5` |
| STAGE 03 completion tag | `stage-03-complete` -> `12ec64c0dda973ad245880aeb28d88c03a9c03b5` |
| STAGE 04 merge commit | `67f8281bd6b759329c5036fbc9cbd6164b6e5b3c` |
| STAGE 04 completion tag | `stage-04-complete` -> `67f8281bd6b759329c5036fbc9cbd6164b6e5b3c` |
| STAGE 05 base / branch | `f64c8253e6b7ec648d7161531344a2999b78ffe7` / `stage/05-plan-engine` |
| STAGE 05 reviewed head | Revue corrective en cours depuis `f162a708f0e17f0fcf17f776db16a903a891cd10` |
| Last migration | `0009_stage_05` ; parent `0008_stage_05` ; une seule tete |
| Corrective implementation | Autorisation sensible API et worker avec targeted member refresh; confirmation liee a l'acteur; idempotence actor-scoped; operation PK plan-scoped; immutabilite SQL INSERT/UPDATE/DELETE et snapshot append-only; hash relu avant validation; preconditions par operation; recovery channel/role distinct; expected Gateway bulk/overwrite strict; index des plans concernes; Impact Engine STAGE 04; sequence atomique; lease-loss fence exact |
| Tests status | PASS : validate_stage 01, 02, 03, 03-load, 04, 05, 05-failure-injection et 05-load, plus le scenario Discord live mutatif complet. Ruff, format, mypy, migrations base/0001..0007 -> 0009 puis head -> 0007 -> head, RLS, docs et secrets PASS. Les compteurs et nouveaux run IDs du HEAD correctif final sont consignes dans le handoff. |
| Discord live status | `PASS`: six plans reussis; CREATE/UPDATE/MOVE/REORDER/UPSERT/DELETE reels; crash apres reponse CREATE_ROLE recupere avec un seul appel CREATE et symbol binding durable; ordre des roles restaure; cleanup audite complet; aucune fixture prefixee restante. |
| Required external configuration | Satisfaite dans la Guild sandbox B : `MANAGE_CHANNELS` et `MANAGE_ROLES` sont presents, `ADMINISTRATOR` n'est pas requis. Aucune action restante. |
| Known failures | Aucune sur le perimetre STAGE 05 correctif. Les limites volontaires sont la non-provocation d'un 429 live et d'un doublon CREATE ambigu; leurs contrats fail-safe sont testes localement. |
| Documentation status | PASS - 11 stages, 246/246 REQ et 35 ADR. Handoff, strategie, matrice sandbox, evidence live, decisions et tracabilite sont corriges; `REQ-UX-006/007` restent `PLANNED`. |
| GitHub publication | Draft PR #5 vers `main`, explicitement non mergee. Corrections publiees sur `stage/05-plan-engine`; tous les checks du nouveau HEAD doivent rester verts avant revue humaine. |
| Evidence storage | Les runs initiaux hors live restent sous `artifacts/test-evidence/stage-05/`. La preuve live expurgee PASS est suivie dans `docs/90_handoffs/STAGE_05_LIVE_EVIDENCE.json`; le run exact final `--include-discord-live` est reference dans le handoff. |
| Next stage | `STAGE_06_FORBIDDEN_BEFORE_STAGE_05_MERGE` |

Le detail est dans [`STAGE_05_HANDOFF.md`](../90_handoffs/STAGE_05_HANDOFF.md). PR #5 reste Draft et non mergee. STAGE 06 n'a pas ete commencee.
