# État courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_03_CORRECTED_PR_OPEN` |
| Last completed stage | `STAGE_03_DISCORD_RUNTIME_CACHE_GOVERNOR_RECONCILIATION` |
| Documentation baseline commit | `c285ac81afb0ec7a3c3197085ceff821a5d1c446` |
| Initial publication-state commit | `677d2d5d1782930c3030a867549ea1601cbc2b05` |
| STAGE 01 implementation commit | `96f545a249e330906bf941e088dd8d63d6f856a6` |
| STAGE 01 merge commit | `28774bf26f2fe590562021f567f0e67f623ff7f5` |
| STAGE 02 base `main` | `f2d422d68a8f33661b37f17df1b013bffcba132d` |
| STAGE 02 implementation commit | `ccf44308dbef1124718cf1f841ef06b8b3cf8c47` |
| STAGE 02 status | `MERGED` |
| STAGE 02 merge commit | `5b962a24058e399c3703095f2162e1f38e1bfd60` |
| STAGE 03 base `main` | `366e676880d0c3f4c7cf4f54105a117b2dcda3d8` |
| STAGE 03 code commit | `795f3904d72455ae2e79c1978cc30a42dbf36050` |
| STAGE 03 corrective runtime commit | `8127e80616fcd57247377386422eb5082003e527` |
| STAGE 03 distributed-runtime correction commit | `275afb3b3a41b4f8dc11c137a559bca7c6dcf406` |
| Last migration | `0005_stage_03` |
| Implemented subsystems | Stages 01–02 ; Gateway intents minimaux et événements normalisés ; inbox/dedup/projection no-effect stale ; cache Discord PostgreSQL RLS et Redis hot ; gap persistant/freshness/tombstones honnêtes ; API cache-first/purge locale confirmée ; vrais processus worker/scheduler ; routage ID-only borné + wakeup/recovery ; admission JIT par vagues et leases renouvelables fenced ; permits/budget/401/429/pression Redis multi-worker ; single-flight acquire-or-observe Lua ; reconcile adaptatif sous pression ; outbox multi-publisher leasée ; WebSocket reauthorization continue ; métriques locales/système bornées |
| Tests status | Correctif local Stage 01/02/03 PASS sur `275afb3b3a41` : 93 unit, 43 integration, 5 load, 4 frontend, 39 security et 6 failure-injection ; pipeline durable A=300/B=30 et deux workers lease court PASS ; migrations `base/0001/0002/0003/0004 -> 0005` et retour `0005 -> 0002 -> 0005` PASS. Preuves finales : Stage 01 `20260817T071822769059Z`, Stage 02 `20260817T071855550704Z`, Stage 03 `20260817T071933724741Z`, load `20260817T072015088196Z`. Deux runs GitHub Actions complets `stage-01/02/03/03-load` PASS sur `e78cd4c91172`. |
| Discord live status | Stage 03 `PASS_WITH_APPROVED_LIMITATION` : sync réelle read-only A+B, PostgreSQL/Redis et isolation PASS, zéro mutation ; Gateway externe/reconnect et obfuscation live `SKIPPED_NOT_VERIFIED`/`CONTRACT_ONLY_NOT_LIVE_VERIFIED` |
| Profiles not verified live | administrateur non propriétaire ; non-administrateur — `SKIPPED_NOT_VERIFIED`, à ne pas considérer comme vérifiés en STAGE 03 |
| Documentation status | PASS — 11 stages, 246/246 REQ, 35 ADR ; IMP-001 revalidé le 2026-08-17 ; IMP-008 routage runtime ; handoff/preuve live Stage 03 conservés |
| GitHub publication | Stage 03 [Draft PR #3](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/3) ouverte vers `main`, non mergée ; body actualisé après CI corrective verte ; Stage 02 PR #2 reste `MERGED` |
| GitHub repository | `Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION` |
| GitHub visibility | `PUBLIC_DURING_DEVELOPMENT` |
| Git remote | `origin` → `https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION.git` |
| Local GitHub CLI | Installée et authentifiée comme `Anthorusse75` ; protocole Git HTTPS |
| Known failures | Aucun échec local ou CI de code, test, migration, documentation ou secret scan ; skips live Stage 03 et deux profils hérités Stage 02 restent explicitement non vérifiés |
| Required external configuration | Variables Discord/OAuth et secrets locaux uniquement dans `.env.local` ignoré ; Docker Desktop pour les validations d’infrastructure |
| Discord sandbox status | Bot réinstallé dans Guild A et Guild B ; grants OAuth temporaires révoqués ; aucun serveur supprimé |
| Open blocking decisions | Aucune pour la Draft PR Stage 03 ; capability Channel Obfuscation temporaire non exposée par `discord.py 2.7.1`, sans faux support live ; exigences futures `REQ-GW-006`, `CACHE-004/007`, `RATE-005`, `AUD-002/003`, `TEN-008` honnêtement `PLANNED` |
| Evidence storage | Runs locaux ignorés sous `artifacts/test-evidence/stage-XX/<run-id>/` ; preuves live expurgées suivies dans `docs/90_handoffs/STAGE_02_LIVE_EVIDENCE.json` et `STAGE_03_LIVE_EVIDENCE.json` ; CI upload par stage/SHA/run/attempt |
| Next stage | STAGE 04 interdite avant merge et revue externe de la Draft PR Stage 03 |

Les preuves, contrats et limites détaillés sont conservés dans [`docs/90_handoffs/STAGE_03_HANDOFF.md`](../90_handoffs/STAGE_03_HANDOFF.md). Le HEAD courant est fourni par Git et n’est pas recopié ici de manière auto-référentielle.
