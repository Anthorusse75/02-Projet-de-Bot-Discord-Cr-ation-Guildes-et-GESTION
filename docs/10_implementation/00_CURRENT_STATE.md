# État courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_05_COMPLETE_PR_OPEN` |
| Last completed stage | `STAGE_05_DESIRED_STATE_PLAN_AND_MUTATION_ENGINE` |
| Documentation baseline commit | `c285ac81afb0ec7a3c3197085ceff821a5d1c446` |
| STAGE 01 merge commit | `28774bf26f2fe590562021f567f0e67f623ff7f5` |
| STAGE 02 merge commit | `5b962a24058e399c3703095f2162e1f38e1bfd60` |
| STAGE 03 merge commit | `12ec64c0dda973ad245880aeb28d88c03a9c03b5` |
| STAGE 03 completion tag | `stage-03-complete` → `12ec64c0dda973ad245880aeb28d88c03a9c03b5` |
| STAGE 04 base `main` | `1f7e4cd7f2ebe92e6c63ede0738731c5bcc3b6ee` |
| STAGE 04 branch | `stage/04-read-permissions` |
| STAGE 04 final head | `1c3f3687d8fa26e044b864195c08cec7f01e770d` |
| STAGE 04 merge commit | `67f8281bd6b759329c5036fbc9cbd6164b6e5b3c` — parents `1f7e4cd7f2ebe92e6c63ede0738731c5bcc3b6ee` et `1c3f3687d8fa26e044b864195c08cec7f01e770d` |
| STAGE 04 completion tag | tag annoté `stage-04-complete` → `67f8281bd6b759329c5036fbc9cbd6164b6e5b3c` |
| STAGE 04 delivery commits | Historique conservé : `ce7558676250`, `7e154bc`, `05d11c1`, `5721fdc`, `29561b18f71f`, `b90065a203f5`, `a9ff510`, correction `6abe938`, clôture de branche `1c3f368` |
| STAGE 05 base / branch | `f64c8253e6b7ec648d7161531344a2999b78ffe7` / `stage/05-plan-engine` |
| Last migration | `0008_stage_05` |
| Implemented subsystems | Stages 01–04 ; DSG immuable et canonical SHA-256 ; diff/compiler déterministes ; plans/snapshots/opérations immuables ; DAG et symbols persistés ; risk/impact et confirmations hash-bound ; preflight final cache-first ; API sans REST mutable ; worker APPLY_PLAN, Governor, lock Guild, lease/fencing ; mutable Discord adapter borné ; attempts `PREPARED/IN_FLIGHT/UNKNOWN` ; reconciliation sans blind CREATE retry ; compensation honnête ; write-through, expected Gateway mutations, drift externe, vérification ciblée, cancellation sûre, progression durable/outbox et métriques bornées |
| Tests status | STAGE 05 complète PASS : 172 unit, 61 integration, 13 failure-injection A–I, 4 frontend et charge DSG 500 nœuds. Lint, format, mypy, build, RLS, secrets et migrations `base/0001/0002/0003/0004/0005/0006/0007 → 0008`, downgrade `0008 → 0007` puis upgrade PASS. Le profil de charge STAGE 03 passe 7/7 avec jobs et permis actifs protégés avant le premier heartbeat. Preuve locale propre : `artifacts/test-evidence/stage-05/20260824T101948193363Z-a8e8bcc7b3b6-local-docker/`. |
| Discord live status | STAGE 05 `PASS_WITH_APPROVED_LIMITATION` : snapshot et plan persisté, puis preflight fail-closed car le bot sandbox manque `MANAGE_CHANNELS` et `MANAGE_ROLES`; zéro mutation Discord. Crash window live et cleanup par plan `SKIPPED_NOT_VERIFIED`; cleanup non requis car aucune fixture créée. |
| Discord live not verified | Threads actifs/publics/privés contrôlés ; fixtures category synced/desynced ; hiérarchie managed/égale — `SKIPPED_NOT_VERIFIED`, car le runner read-only ne crée pas ces fixtures. Limitations STAGE 03 héritées : modification Gateway et reconnect forcé `SKIPPED_NOT_VERIFIED`, Channel Obfuscation `CONTRACT_ONLY_NOT_LIVE_VERIFIED`. |
| Human profiles not verified live | Administrateur non propriétaire ; non-administrateur — `SKIPPED_NOT_VERIFIED`, conservés honnêtement depuis STAGE 02. |
| Documentation status | PASS — 11 stages, 246/246 REQ, 35 ADR ; `IMP-012`, traceabilité, stratégie, sécurité, preuve live et handoff STAGE 05 à jour. `REQ-UX-006/007` restent honnêtement `PLANNED`. |
| GitHub publication | STAGE 04 : [PR #4](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/4) mergée. STAGE 05 : [Draft PR #5](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/5) vers `main`, explicitement non mergée. |
| GitHub repository | `Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION` |
| GitHub visibility | `PUBLIC_DURING_DEVELOPMENT` |
| Git remote | `origin` → `https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION.git` |
| Known failures | Aucun échec local de code, test, migration, documentation, secret scan ou diff. Limite non bloquante : aucune mutation live STAGE 05 n'a pu franchir le preflight avec les permissions actuelles du bot ; elle reste explicitement non vérifiée. |
| Required external configuration | Variables Discord/OAuth et secrets locaux uniquement dans `.env.local` ignoré ; Docker Desktop pour les validations d’infrastructure. |
| Open blocking decisions | Aucune pour la portée code STAGE 05. La preuve live mutative requiert une décision humaine d'accorder au bot sandbox `MANAGE_CHANNELS` et `MANAGE_ROLES`. `REQ-UX-006/007`, l'inventaire bot global et la portée UI restent futurs. |
| Evidence storage | Runs locaux ignorés sous `artifacts/test-evidence/stage-05/<run-id>/` ; preuve live expurgée suivie dans `docs/90_handoffs/STAGE_05_LIVE_EVIDENCE.json` ; CI upload par stage/SHA/run/attempt. |
| Next stage | `STAGE_06_FORBIDDEN_BEFORE_STAGE_05_MERGE` — ne pas commencer avant revue externe et merge normal de la Draft PR STAGE 05. |

Les preuves, contrats et limites détaillés sont conservés dans [`docs/90_handoffs/STAGE_05_HANDOFF.md`](../90_handoffs/STAGE_05_HANDOFF.md). La PR STAGE 05 reste Draft et non mergée. STAGE 06 n'a pas été commencée.
