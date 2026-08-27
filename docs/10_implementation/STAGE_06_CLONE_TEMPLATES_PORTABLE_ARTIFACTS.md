# STAGE 06 — Clonage profond, templates, Portable Artifacts, bibliothèque et cross-Guild

## A. Identité

| Champ | Valeur |
|---|---|
| Numéro / branche | `06` / `stage/06-portability` |
| Objectif | Offrir une portabilité contrôlée sans créer de fédération ni réutiliser d’identités source. |
| Résultat attendu | Pipeline unique export → graph → mapping → plan destination pour clone, clipboard, library et import/export. |
| Dépendances | 01–05 mergées ; plans destination-only et Control Plane sûrs. |
| Risque | Critique : IDOR cross-Guild, confused deputy, mapping ambigu et artifacts hostiles. |

## B. Sources normatives

Spécifications §2.2.1–2.2.3, §9.5/9.8, §13, §25–26, `REQ-TEN-011..014`, `REQ-DUP-*`, `REQ-STR-008,011,013`, `REQ-PERM-009`. Architecture §7.15–7.16, §8.5, §13–17, §35.1, §49A, §50–51, §61, ADR-010/019/021/030.

## C. PRECHECK obligatoire

```bash
git status --short --branch
test "$(git branch --show-current)" = "main"
python scripts/validate_stage.py 05
python -m alembic current
git log -1 --oneline
```

Lire handoff 05 ; vérifier immutable snapshot, symbolic bindings, destination-only invariant, Control Plane owner context et double-authorize primitives. Créer `stage/06-portability`; arrêter si un plan peut muter deux Guilds ou si l’artifact confère une capability source.

## D. Scope exact

Inclus : Portable Artifact schemas/encryption, builder, Dependency Graph, Mapping Resolver, profiles/modes `COPY_AS_NEW`, `MERGE`, `RECONCILE`, `MAXIMUM_COMPATIBLE`, clone types, templates, clipboard personnel, library, file import/export, cross-Guild transfer state/audit, ACL policy portability sans principals, backend semantic copy/drag commands.

Exclus : gestures/UI complets (07), multilingual expansion (08), campaigns (09).

Work packages : artifact schema/security ; export authorization ; dependency graph ; mapping/modes ; templates/library/clipboard ; destination plan compilation ; APIs/cross-Guild orchestration ; sandbox/security.

## E. Design d’implémentation détaillé

- `PortableArtifact` versionné, immutable, canonical hash, provenance informative, resource logical keys, no source capability. Chiffrement envelope pour storage user-scopé, authenticated metadata, key_version, size/TTL/quota and owner RLS.
- Tables `templates`, `user_portable_artifacts`, `cross_guild_transfers`, `portable_clone_bindings`; tenant template private RLS vs user library/transfer/bindings owner RLS. Les quotas count/bytes sont sérialisés par owner en transaction. Import file passe schema/type/size/decompression limits, signature/hash policy et aucune URL fetch implicite (SSRF).
- Builder termine toutes lectures source sous authorization/export A, produit snapshot, puis aucune relire A pendant plan B. LIVE_CLONE exige source observable ; artifact import non.
- Dependency graph explicite pour roles, categories/channels, overwrites, bots/webhooks policies and logical groups. Cycles/unknown refs refusés ; historical messages/members/audit/IDs exclus.
- Mapping decisions `CREATE`, `MAP_EXISTING`, `SKIP`, `UNSUPPORTED`, `MANUAL`; candidates scored mais ambiguïté jamais auto-acceptée. Role/bot/webhook mappings et ACL principals exigent confirmation.
- Modes : COPY_AS_NEW crée ; MERGE conserve l'identité B mais applique les propriétés portables désirées ; RECONCILE dérive côté serveur un scope borné par relation de clone et liste chaque delete avant confirmation ; MAXIMUM_COMPATIBLE est report-only (`plan=null`, aucune mutation). Support annoncé par la matrice typée `did-clone-support-v&#50;`.
- Pipeline unique utilisé par copy/paste, inter-Guild drag semantic endpoint, context clone, library import et template apply. Toutes sorties compilent DSG/plan de STAGE 05 pour B seulement.
- ACL/policies peuvent transporter définitions, jamais binding user/role source. Translation secrets/provider secrets toujours exclus même avant STAGE 08.
- Orchestrator Control Plane valide user, source export, destination import/mutate et bot capabilities, persiste transfer, fan-out jobs Guild-scopés ; aucun lock A+B simultané.
- Audit double côté access boundary, errors ne révèlent pas B, idempotency sur export/compile/apply. Artifact sensitive data minimisée et purge/revocation testée.

## F. Liste prévue de fichiers

Migrations artifacts/transfers/templates, `did/portability/**`, `did/cloning/**`, `did/templates/**`, repositories Control Plane/tenant, mapping/dependency graph, API schemas/import validators, plan compilers, crypto integration, tests artifacts/property/A-B/sandbox.

## G. Stratégie de tests de l’étape

Unit/property : canonical artifact/hash, graph closure/cycles, mapping ambiguity, each mode/report. Security fuzz hostile import, zip bomb/size, owner isolation, ciphertext tamper. A/B matrices revoke export/import independently, source disappears after export, same Discord IDs malicious input. Integration plan B-only and no lock dual-Guild. Sandbox clone channel/category/group/config A→B, verify new IDs/source intact, reconcile deletes explicit. Failure during fan-out and key rotation.

## H. Matrice de validation

| ID | Exigence | Test | Commande | Résultat attendu | Preuve |
|---|---|---|---|---|---|
| S06-TEN / REQ-TEN-011..014 | explicit bridge/owner artifact | A/B/owner/RLS | `python scripts/validate_stage.py 06` | double auth, encrypted isolation, no federation | JUnit/security |
| S06-DUP / REQ-DUP-001..019 | clone pipeline/modes | graph+mapping+plan+live | même commande | new IDs, explicit skips/mappings, B-only | artifact/plan diff |
| S06-STR / REQ-STR-008,011,013 | inter-Guild copy semantics | API contracts | même commande | source never moved/deleted | JUnit |
| S06-PERM / REQ-PERM-009 | policy truthfulness | ACL portability test | même commande | no implicit source principals | report |

## I. Commandes exactes de validation

```bash
docker compose -f compose.test.yaml up -d --wait
python scripts/validate_stage.py 06
python scripts/validate_stage.py 06 --profile security
python scripts/validate_stage.py 06 --include-discord-live
docker compose -f compose.test.yaml down
```

## J. Tests Discord réels

A contient catégorie, channels, roles/overwrites et group ; B possède mappings partiels. Tester modes supportés, authorization removed on either side, bot absent source for stored artifact, LIVE_CLONE source invisible, new IDs B and A unchanged. Cleanup only B resources via audited plans; retain artifact test only until purge assertion.

## K. Secrets / credentials nécessaires

| Nom | Obligatoire | Étape | Secret ? | Provenance | Stockage local | Stockage CI | Rotation |
|---|---:|---:|---:|---|---|---|---|
| `ARTIFACT_ENCRYPTION_KEY` | oui | 06 | oui | CSPRNG/KMS | `.env.local` | protected environment | versionnée + re-encryption |
| Bot token + Guild A/B IDs | live | 06 | token oui | Portal/sandbox | `.env.local` | protected environment | sandbox policy |

## L. Critères d’acceptation

Sans export A ou import B, aucun plan/mutation ; artifact U inaccessible à V et tamper refusé ; after export no source read ; every B object has new ID unless explicit existing mapping ; ambiguity blocks ; all entry points use same pipeline ; reconcile delete visible/confirmed ; no source principal/secret imported ; A remains unchanged.

## M. Definition of Done

Migrations, schemas/modes/pipeline, security/fuzz/A-B/live, REQ/proofs, regressions 01–05, docs/handoff/state, commit/push/PR/merge.

## N. Handoff obligatoire

Créer `STAGE_06_HANDOFF.md` avec artifact schema/version, crypto/key rotation, supported clone matrix, mapping semantics, API, transfer states, sandbox mappings/cleanup et frontend contracts.

## O. Prompt de démarrage d’un nouveau chat Codex

```text
Implémente uniquement STAGE 06 de Discord Infrastructure Designer.
Lis AGENTS.md, le contrat global, l’état courant et intégralement STAGE_06_CLONE_TEMPLATES_PORTABLE_ARTIFACTS.md ; exécute le PRECHECK.
N’implémente aucune étape suivante. Prouve double autorisation, plan destination-only, absence de réutilisation d’identités/principals et pipeline unique ; termine tests, preuves, handoff, état/traçabilité, commit et PR.
```
