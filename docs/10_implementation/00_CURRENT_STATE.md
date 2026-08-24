# Etat courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_05_CORRECTIVE_REVIEW_LIVE_BLOCKED` |
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
| Tests status | PASS hors live mutatif : validate_stage 01, 02, 03, 03-load, 04, 05, 05-failure-injection et 05-load. Le profil complet compte 183 unit, 72 integration, 24 scenarios STAGE 05/failure-injection, 4 frontend et le DSG 500 noeuds. Ruff, format, mypy, migrations base/0001..0007 -> 0009 puis head -> 0007 -> head, RLS, docs et secrets PASS. |
| Discord live status | `BLOCKED_CAPABILITY_CONFIGURATION`: le preflight live sandbox B confirme l'absence de `MANAGE_CHANNELS` et `MANAGE_ROLES`; zero mutation. Le plan complet, crash window et cleanup ne sont pas verifies et ne sont pas PASS. |
| Required external configuration | Dans la seule Guild sandbox B, accorder au role bot `MANAGE_CHANNELS` + `MANAGE_ROLES`, sans `ADMINISTRATOR`, et placer le role bot au-dessus des fixtures. Invite minimale si reinstall: permissions `268435472`. |
| Known failures | Le live mutatif exact `validate_stage.py 05 --include-discord-live` echoue avec `BLOCKED_CAPABILITY_CONFIGURATION`; tous ses gates precedents sont verts. Le premier run Stage 01 avait revele une dependance OAuth indue au demarrage worker; elle est corrigee et le rerun complet est PASS. |
| Documentation status | PASS - 11 stages, 246/246 REQ et 35 ADR. Handoff, strategie, matrice sandbox, evidence live, decisions et tracabilite sont corriges; `REQ-UX-006/007` restent `PLANNED`. |
| GitHub publication | Draft PR #5 vers `main`, explicitement non mergee. Aucun push correctif tant que les validations et preuves requises ne sont pas terminees. |
| Evidence storage | Run Stage 05 complet hors live : `artifacts/test-evidence/stage-05/20260824T140603689891Z-f162a708f0e1-local-docker/`; failure-injection : `20260824T140812036729Z-f162a708f0e1-local-docker/`; load : `20260824T140832071303Z-f162a708f0e1-local-docker/`; live bloque : `20260824T140842339297Z-f162a708f0e1-local-docker/`. Preuve expurgee suivie dans `STAGE_05_LIVE_EVIDENCE.json`. |
| Next stage | `STAGE_06_FORBIDDEN_BEFORE_STAGE_05_MERGE` |

Le detail est dans [`STAGE_05_HANDOFF.md`](../90_handoffs/STAGE_05_HANDOFF.md). PR #5 reste Draft et non mergee. STAGE 06 n'a pas ete commencee.
