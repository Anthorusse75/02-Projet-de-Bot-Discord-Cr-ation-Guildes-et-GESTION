# État courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_03_READY_NOT_STARTED` |
| Last completed stage | `STAGE_02_OAUTH_SESSIONS_TENANCY_RBAC_INSTALLATION` |
| Documentation baseline commit | `c285ac81afb0ec7a3c3197085ceff821a5d1c446` |
| Initial publication-state commit | `677d2d5d1782930c3030a867549ea1601cbc2b05` |
| STAGE 01 implementation commit | `96f545a249e330906bf941e088dd8d63d6f856a6` |
| STAGE 01 merge commit | `28774bf26f2fe590562021f567f0e67f623ff7f5` |
| STAGE 02 base `main` | `f2d422d68a8f33661b37f17df1b013bffcba132d` |
| STAGE 02 implementation commit | `ccf44308dbef1124718cf1f841ef06b8b3cf8c47` |
| STAGE 02 status | `MERGED` |
| STAGE 02 merge commit | `5b962a24058e399c3703095f2162e1f38e1bfd60` |
| Last migration | `0002_stage_02` |
| Implemented subsystems | Fondations STAGE 01 ; OAuth2 Discord backend avec `state` one-shot lié au navigateur ; grants chiffrés ; sessions opaques Redis ; CSRF ; découverte et sélection de tenant sans fuite d’installation ; modèle installation à transitions conservatrices ; RBAC/capabilities réellement porté `GUILD`/`LOGICAL_GROUP`/`VISIBILITY_SCOPE` ; OWNER protégé et revoke de role binding ; bootstrap owner/admin rafraîchi ; RLS utilisateur et guilde ; endpoints auth/me/guilds ; frontend auth et sélecteur de guilde ; validation Discord live expurgée |
| Tests status | STAGE 02 local PASS — 49 unit, 17 integration, 4 frontend, 23/23 gates ; migrations `base -> head`, `0001 -> head`, `0002 -> 0001 -> 0002` PASS ; STAGE 01 regression PASS, 19/19 gates |
| Discord live status | `PASS_WITH_APPROVED_LIMITATION` avec un compte propriétaire : identité, OAuth exact, install/uninstall/reinstall A+B, membre ciblé et révocation PASS ; profils administrateur non propriétaire et non-administrateur `SKIPPED_NOT_VERIFIED` |
| Profiles not verified live | administrateur non propriétaire ; non-administrateur — `SKIPPED_NOT_VERIFIED`, à ne pas considérer comme vérifiés en STAGE 03 |
| Documentation status | PASS — 11 stages, 246/246 REQ, 35 ADR ; handoff et preuve live STAGE 02 présents |
| GitHub publication | [PR #2](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/2) `MERGED` vers `main` par merge normal ; branche `stage/02-auth-tenancy` conservée |
| GitHub repository | `Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION` |
| GitHub visibility | `PUBLIC_DURING_DEVELOPMENT` |
| Git remote | `origin` → `https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION.git` |
| Local GitHub CLI | Installée et authentifiée comme `Anthorusse75` ; protocole Git HTTPS |
| Known failures | Aucun échec local de code, test, migration ou secret scan ; deux profils Discord live explicitement non vérifiés et conservés comme limitation approuvée |
| Required external configuration | Variables Discord/OAuth et secrets locaux uniquement dans `.env.local` ignoré ; Docker Desktop pour les validations d’infrastructure |
| Discord sandbox status | Bot réinstallé dans Guild A et Guild B ; grants OAuth temporaires révoqués ; aucun serveur supprimé |
| Open blocking decisions | Aucune pour clôturer STAGE 02 ; STAGE 03 est autorisée mais non démarrée |
| Evidence storage | Runs locaux ignorés sous `artifacts/test-evidence/stage-XX/<run-id>/` ; preuve live expurgée suivie dans `docs/90_handoffs/STAGE_02_LIVE_EVIDENCE.json` ; runs CI uploadés avec stage/SHA/run/attempt |
| Next stage | STAGE 03 autorisée mais `NOT_STARTED` ; commencer par son PRECHECK depuis le `main` final et conserver les deux profils live sautés comme non vérifiés |

Les preuves, contrats et limites détaillés sont conservés dans [`docs/90_handoffs/STAGE_02_HANDOFF.md`](../90_handoffs/STAGE_02_HANDOFF.md). Le HEAD courant est fourni par Git et n’est pas recopié ici de manière auto-référentielle.
