# État courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_05_READY_NOT_STARTED` |
| Last completed stage | `STAGE_04_READ_MODEL_PERMISSIONS_DIAGNOSTICS_SCOPES` |
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
| Last migration | `0007_stage_04` |
| Implemented subsystems | Stages 01–03 ; read model Discord immutable et cache-first ; projection threads actifs `GUILD_CREATE`/CRUD/`THREAD_LIST_SYNC` sans fausse suppression ; preuves privées bot par thread ; structure/category/thread diagnostics ; Permission Registry versionné et bitfields arbitraires ; moteur pur permissions/overwrites/implicites/threads avec fraîcheur thread+parent ; `PermissionDecision` fail-safe et trace déterministe ; Why Access, View As, simple/expert et simulation read-only ; Capability Checker et hiérarchie avec cibles obligatoires ; groupes logiques non récursifs ; Visibility Scopes couplés API/domaine/DB et resolver central ; refresh acteur ciblé single-flight ; API/RLS/audit/métriques bornées |
| Tests status | Correction `6abe938` : validation STAGE 04 complète PASS — 158 unit, 48 integration, 4 frontend, benchmark 400 décisions en `0.096676 s`, secret scan et répétitions de migrations depuis `base/0001/0002/0003/0004/0005` vers `0007` PASS. Les 6 tests load complets passent également. Preuve : `artifacts/test-evidence/stage-04/20260824T071804368665Z-6abe93847432-local-docker/`. Les dix checks du HEAD final `1c3f368` étaient verts avant le merge; les GitHub Checks de `main` restent la source de vérité post-merge. |
| Discord live status | STAGE 04 `PASS_WITH_APPROVED_LIMITATION` : Guild A/B observées en lecture seule, 53/18 channels, 39/11 rôles, zéro mismatch sur les actions applicables et zéro mutation Discord. La documentation officielle est normative ; `discord.py 2.7.1` est un oracle secondaire. |
| Discord live not verified | Threads actifs/publics/privés contrôlés ; fixtures category synced/desynced ; hiérarchie managed/égale — `SKIPPED_NOT_VERIFIED`, car le runner read-only ne crée pas ces fixtures. Limitations STAGE 03 héritées : modification Gateway et reconnect forcé `SKIPPED_NOT_VERIFIED`, Channel Obfuscation `CONTRACT_ONLY_NOT_LIVE_VERIFIED`. |
| Human profiles not verified live | Administrateur non propriétaire ; non-administrateur — `SKIPPED_NOT_VERIFIED`, conservés honnêtement depuis STAGE 02. |
| Documentation status | PASS — 11 stages, 246/246 REQ, 35 ADR ; `IMP-010` consigne le calcul permissions et `IMP-011` la projection des threads actifs/memberships ; traceabilité et handoff STAGE 04 corrigés. |
| GitHub publication | [PR #4](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/4) passée de Draft à Ready après revue externe, puis `MERGED` par merge commit normal le `2026-08-24`; branche source conservée. |
| GitHub repository | `Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION` |
| GitHub visibility | `PUBLIC_DURING_DEVELOPMENT` |
| Git remote | `origin` → `https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION.git` |
| Known failures | Aucun échec local de code, test, migration, documentation, secret scan ou diff dans la revue corrective. Le live correctif non opt-in est `SKIPPED_NOT_VERIFIED` et ne remplace pas la preuve read-only A/B suivie ; les scénarios live explicitement sautés ne sont pas considérés comme vérifiés. |
| Required external configuration | Variables Discord/OAuth et secrets locaux uniquement dans `.env.local` ignoré ; Docker Desktop pour les validations d’infrastructure. |
| Open blocking decisions | Aucune pour STAGE 04. `REQ-STR-004/005`, `REQ-BOT-004/005/006` et `REQ-CACHE-007` restent honnêtement `PLANNED` pour leur portée mutation, inventaire ou UI future. |
| Evidence storage | Dernière validation corrective : `artifacts/test-evidence/stage-04/20260824T071804368665Z-6abe93847432-local-docker/` ; runs locaux ignorés sous `artifacts/test-evidence/stage-XX/<run-id>/` ; preuve live expurgée suivie dans `docs/90_handoffs/STAGE_04_LIVE_EVIDENCE.json` ; CI upload par stage/SHA/run/attempt. |
| Next stage | `STAGE_05_READY_NOT_STARTED` — autorisée, mais aucune implémentation ni branche STAGE 05 n’a été commencée. |

Les preuves, contrats et limites détaillés sont conservés dans [`docs/90_handoffs/STAGE_04_HANDOFF.md`](../90_handoffs/STAGE_04_HANDOFF.md). STAGE 04 est intégrée dans `main`; STAGE 05 est autorisée mais n’a pas été commencée.
