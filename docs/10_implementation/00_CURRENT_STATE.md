# État courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_02_COMPLETE_PR_OPEN` |
| Last completed stage | `STAGE_02_OAUTH_SESSIONS_TENANCY_RBAC_INSTALLATION` |
| Documentation baseline commit | `c285ac81afb0ec7a3c3197085ceff821a5d1c446` |
| Initial publication-state commit | `677d2d5d1782930c3030a867549ea1601cbc2b05` |
| STAGE 01 implementation commit | `96f545a249e330906bf941e088dd8d63d6f856a6` |
| STAGE 01 merge commit | `28774bf26f2fe590562021f567f0e67f623ff7f5` |
| STAGE 02 base `main` | `f2d422d68a8f33661b37f17df1b013bffcba132d` |
| STAGE 02 implementation commit | `ccf44308dbef1124718cf1f841ef06b8b3cf8c47` |
| Last migration | `0002_stage_02` |
| Implemented subsystems | Fondations STAGE 01 ; OAuth2 Discord backend avec `state` one-shot lié au navigateur ; grants chiffrés ; sessions opaques Redis ; CSRF ; découverte et sélection de tenant sans fuite d’installation ; modèle installation à transitions conservatrices ; RBAC/capabilities réellement porté `GUILD`/`LOGICAL_GROUP`/`VISIBILITY_SCOPE` ; OWNER protégé et revoke de role binding ; bootstrap owner/admin rafraîchi ; RLS utilisateur et guilde ; endpoints auth/me/guilds ; frontend auth et sélecteur de guilde ; validation Discord live expurgée |
| Tests status | STAGE 02 local PASS — 49 unit, 17 integration, 4 frontend, 23/23 gates ; migrations `base -> head`, `0001 -> head`, `0002 -> 0001 -> 0002` PASS ; STAGE 01 regression PASS, 19/19 gates |
| Discord live status | `PASS_WITH_APPROVED_LIMITATION` avec un compte propriétaire : identité, OAuth exact, install/uninstall/reinstall A+B, membre ciblé et révocation PASS ; profils administrateur non propriétaire et non-administrateur `SKIPPED_NOT_VERIFIED` |
| Documentation status | PASS — 11 stages, 246/246 REQ, 35 ADR ; handoff et preuve live STAGE 02 présents |
| GitHub publication | [Draft PR #2](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/2) ouverte vers `main` depuis `stage/02-auth-tenancy` ; ne pas merger automatiquement |
| GitHub repository | `Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION` |
| GitHub visibility | `PUBLIC_DURING_DEVELOPMENT` |
| Git remote | `origin` → `https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION.git` |
| Local GitHub CLI | Installée et authentifiée comme `Anthorusse75` ; protocole Git HTTPS |
| Known failures | Aucun échec local de code, test, migration ou secret scan ; deux profils Discord live explicitement non vérifiés et conservés comme limitation approuvée |
| Required external configuration | Variables Discord/OAuth et secrets locaux uniquement dans `.env.local` ignoré ; Docker Desktop pour les validations d’infrastructure |
| Discord sandbox status | Bot réinstallé dans Guild A et Guild B ; grants OAuth temporaires révoqués ; aucun serveur supprimé |
| Open blocking decisions | Aucune pour terminer STAGE 02 ; STAGE 03 interdite avant merge normal de la PR #2 |
| Evidence storage | Runs locaux ignorés sous `artifacts/test-evidence/stage-XX/<run-id>/` ; preuve live expurgée suivie dans `docs/90_handoffs/STAGE_02_LIVE_EVIDENCE.json` ; runs CI uploadés avec stage/SHA/run/attempt |
| Next stage | Après merge seulement : PRECHECK de STAGE 03 depuis le SHA final de `main` ; aucune implémentation STAGE 03 n’est commencée |

Les preuves, contrats et limites détaillés sont conservés dans [`docs/90_handoffs/STAGE_02_HANDOFF.md`](../90_handoffs/STAGE_02_HANDOFF.md). Le HEAD courant est fourni par Git et n’est pas recopié ici de manière auto-référentielle.
