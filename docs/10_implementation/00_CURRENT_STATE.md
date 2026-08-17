# État courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_04_COMPLETE_PR_OPEN` |
| Last completed stage | `STAGE_04_READ_MODEL_PERMISSIONS_DIAGNOSTICS_SCOPES` |
| Documentation baseline commit | `c285ac81afb0ec7a3c3197085ceff821a5d1c446` |
| STAGE 01 merge commit | `28774bf26f2fe590562021f567f0e67f623ff7f5` |
| STAGE 02 merge commit | `5b962a24058e399c3703095f2162e1f38e1bfd60` |
| STAGE 03 merge commit | `12ec64c0dda973ad245880aeb28d88c03a9c03b5` |
| STAGE 03 completion tag | `stage-03-complete` → `12ec64c0dda973ad245880aeb28d88c03a9c03b5` |
| STAGE 04 base `main` | `1f7e4cd7f2ebe92e6c63ede0738731c5bcc3b6ee` |
| STAGE 04 branch | `stage/04-read-permissions` |
| STAGE 04 delivery commits | `ce7558676250`, `7e154bc`, `05d11c1`, `5721fdc`, `29561b18f71f`, `b90065a203f5` |
| Last migration | `0006_stage_04` |
| Implemented subsystems | Stages 01–03 ; read model Discord immutable et cache-first ; structure/category/thread diagnostics ; Permission Registry versionné et bitfields arbitraires ; moteur pur permissions/overwrites/implicites/threads ; `PermissionDecision` fail-safe et trace déterministe ; Why Access, View As, simple/expert et simulation read-only ; Capability Checker et hiérarchie ; groupes logiques non récursifs ; Visibility Scopes et resolver central ; refresh acteur ciblé single-flight ; API/RLS/audit/métriques bornées |
| Tests status | Sur le commit code `29561b18f71f` : 144 unit, 47 integration, 4 frontend et 6 load PASS. STAGE 04 avec live PASS ; benchmark 400 décisions, 41 rôles et 12 overwrites/channel en environ 0,09 s, zéro requête DB. Migrations `base/0001/0002/0003/0004/0005 -> 0006`, puis `0006 -> 0005 -> 0006`, PASS. Régressions STAGE 01, 02, 03 et STAGE 03 load PASS. Les GitHub Checks de la Draft PR font autorité pour le dernier commit documentaire. |
| Discord live status | STAGE 04 `PASS_WITH_APPROVED_LIMITATION` : Guild A/B observées en lecture seule, 53/18 channels, 39/11 rôles, zéro mismatch sur les actions applicables et zéro mutation Discord. La documentation officielle est normative ; `discord.py 2.7.1` est un oracle secondaire. |
| Discord live not verified | Threads actifs/publics/privés contrôlés ; fixtures category synced/desynced ; hiérarchie managed/égale — `SKIPPED_NOT_VERIFIED`, car le runner read-only ne crée pas ces fixtures. Limitations STAGE 03 héritées : modification Gateway et reconnect forcé `SKIPPED_NOT_VERIFIED`, Channel Obfuscation `CONTRACT_ONLY_NOT_LIVE_VERIFIED`. |
| Human profiles not verified live | Administrateur non propriétaire ; non-administrateur — `SKIPPED_NOT_VERIFIED`, conservés honnêtement depuis STAGE 02. |
| Documentation status | PASS — 11 stages, 246/246 REQ, 35 ADR ; `IMP-010` consigne les décisions de modélisation permissions ; handoff et preuve live expurgée STAGE 04 suivis. |
| GitHub publication | [Draft PR #4](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/4) ouverte vers `main`, non mergée ; revue externe requise. |
| GitHub repository | `Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION` |
| GitHub visibility | `PUBLIC_DURING_DEVELOPMENT` |
| Git remote | `origin` → `https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION.git` |
| Known failures | Aucun échec local de code, test, migration, documentation, secret scan ou diff ; les scénarios live explicitement sautés ne sont pas considérés comme vérifiés. |
| Required external configuration | Variables Discord/OAuth et secrets locaux uniquement dans `.env.local` ignoré ; Docker Desktop pour les validations d’infrastructure. |
| Open blocking decisions | Aucune pour STAGE 04. `REQ-STR-004/005`, `REQ-BOT-004/005/006` et `REQ-CACHE-007` restent honnêtement `PLANNED` pour leur portée mutation, inventaire ou UI future. |
| Evidence storage | Runs locaux ignorés sous `artifacts/test-evidence/stage-XX/<run-id>/` ; preuve live expurgée suivie dans `docs/90_handoffs/STAGE_04_LIVE_EVIDENCE.json` ; CI upload par stage/SHA/run/attempt. |
| Next stage | `STAGE 05 INTERDITE AVANT MERGE.` |

Les preuves, contrats et limites détaillés sont conservés dans [`docs/90_handoffs/STAGE_04_HANDOFF.md`](../90_handoffs/STAGE_04_HANDOFF.md). STAGE 05 n’a pas été commencée.
