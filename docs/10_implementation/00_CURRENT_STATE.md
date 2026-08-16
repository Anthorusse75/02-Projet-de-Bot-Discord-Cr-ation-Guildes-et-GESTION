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
| Last migration | `0004_stage_03` |
| Implemented subsystems | Stages 01–02 ; Gateway intents minimaux et événements normalisés ; inbox/dedup/projection no-effect stale ; cache Discord PostgreSQL RLS et Redis hot ; gap persistant/freshness/tombstones honnêtes ; API cache-first/purge locale confirmée ; vrais processus worker/scheduler ; routage ID-only borné + wakeup/recovery ; Governor long-lived équitable ; single-flight générationnel ; sync/reconcile adaptatif ; outbox opérationnelle/invalidation ; WebSocket reauthorization continue ; métriques bornées |
| Tests status | STAGE 01/02/03 local PASS au commit `6a964642151a3fa048706c3c5753cfe8585ef287` — 92 unit, 40 integration, 4 load, 4 frontend ; pipeline durable A=300/B=30 PASS ; migrations `base/0001/0002/0003 -> 0004` et retour `0004 -> 0002 -> 0004` PASS ; CI du nouveau HEAD requise avant rapport final |
| Discord live status | Stage 03 `PASS_WITH_APPROVED_LIMITATION` : sync réelle read-only A+B, PostgreSQL/Redis et isolation PASS, zéro mutation ; Gateway externe/reconnect et obfuscation live `SKIPPED_NOT_VERIFIED`/`CONTRACT_ONLY_NOT_LIVE_VERIFIED` |
| Profiles not verified live | administrateur non propriétaire ; non-administrateur — `SKIPPED_NOT_VERIFIED`, à ne pas considérer comme vérifiés en STAGE 03 |
| Documentation status | PASS — 11 stages, 246/246 REQ, 35 ADR ; IMP-001 revalidé le 2026-08-17 ; IMP-008 routage runtime ; handoff/preuve live Stage 03 conservés |
| GitHub publication | Stage 03 [Draft PR #3](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/3) ouverte vers `main`, non mergée ; Stage 02 PR #2 reste `MERGED` |
| GitHub repository | `Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION` |
| GitHub visibility | `PUBLIC_DURING_DEVELOPMENT` |
| Git remote | `origin` → `https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION.git` |
| Local GitHub CLI | Installée et authentifiée comme `Anthorusse75` ; protocole Git HTTPS |
| Known failures | Aucun échec local de code, test, migration, documentation ou secret scan ; CI du nouveau HEAD encore à exécuter ; skips live Stage 03 et deux profils hérités Stage 02 restent explicitement non vérifiés |
| Required external configuration | Variables Discord/OAuth et secrets locaux uniquement dans `.env.local` ignoré ; Docker Desktop pour les validations d’infrastructure |
| Discord sandbox status | Bot réinstallé dans Guild A et Guild B ; grants OAuth temporaires révoqués ; aucun serveur supprimé |
| Open blocking decisions | Aucune pour la Draft PR Stage 03 ; capability Channel Obfuscation temporaire non exposée par `discord.py 2.7.1`, sans faux support live |
| Evidence storage | Runs locaux ignorés sous `artifacts/test-evidence/stage-XX/<run-id>/` ; preuves live expurgées suivies dans `docs/90_handoffs/STAGE_02_LIVE_EVIDENCE.json` et `STAGE_03_LIVE_EVIDENCE.json` ; CI upload par stage/SHA/run/attempt |
| Next stage | STAGE 04 interdite avant merge et revue externe de la Draft PR Stage 03 |

Les preuves, contrats et limites détaillés sont conservés dans [`docs/90_handoffs/STAGE_03_HANDOFF.md`](../90_handoffs/STAGE_03_HANDOFF.md). Le HEAD courant est fourni par Git et n’est pas recopié ici de manière auto-référentielle.
