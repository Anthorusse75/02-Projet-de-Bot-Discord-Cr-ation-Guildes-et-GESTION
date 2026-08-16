# STAGE 05 — Desired State Graph, Plan Engine et moteur de mutations

## A. Identité

| Champ | Valeur |
|---|---|
| Numéro / branche | `05` / `stage/05-plan-engine` |
| Objectif | Compiler des intentions en plans persistés sûrs et les appliquer de manière effectivement-once. |
| Résultat attendu | DAG immuable, symbolic bindings, preflight/risk/impact, apply worker, UNKNOWN_OUTCOME, vérification et progression live. |
| Dépendances | 01–04 mergées ; state/version, evaluator et governor stables. |
| Risque | Critique maximal : mutations externes non transactionnelles et crash windows. |

## B. Sources normatives

Spécifications §2.3–2.4, §12, §20, §27–30, §38–39, `REQ-PLAN-*`, `REQ-UX-006..007`, `REQ-AUD-001..003`, `REQ-GW-006`. Architecture §13–18, §20, §25, §28–30, §45–49, §60–62, ADR-004/010/018/021, §71/73–77.

## C. PRECHECK obligatoire

```bash
git status --short --branch
test "$(git branch --show-current)" = "main"
python scripts/validate_stage.py 04
python -m alembic current
git log -1 --oneline
```

Lire handoff 04 ; vérifier versioning cache, permission/capability APIs, worker/governor et outbox. Créer `stage/05-plan-engine`. Refuser si un router peut déjà muter Discord directement ou si les opérations externes ne peuvent être instrumentées aux crash points.

## D. Scope exact

Inclus : intention commands, Desired State Graph (DSG), diff, immutable plans/operations, persistent DAG, symbols, preflight, risk/impact/confirmation, apply/attempt state machines, guild lock, idempotence, compensation réaliste, stale detection, unknown recovery, post-apply verification, write-through cache, audit et live progress.

Exclus : clone-specific graph (06), UI drag (07), multilingual compilers (08), campaigns (09).

Work packages : DSG/diff ; schema/state machines ; DAG/symbols ; preflight/risk/impact ; API/confirmation ; worker apply ; crash recovery/verify ; live progress/load.

## E. Design d’implémentation détaillé

- DSG versionné représente catégories, channels, roles, overwrites et propriétés avec logical refs ; séparé du snapshot observé. Diff déterministe et stable sous ordering canonical.
- Tables `plans`, `plan_operations`, `plan_operation_dependencies`, `plan_symbol_bindings`, `operation_attempts`, snapshots et confirmation records. Plan destination Guild unique ; hashes `base_structure_version`, desired graph, capability version ; operations immuables après validation, sauf état/résultat.
- DAG validé acyclique ; scheduling seulement si prédécesseurs réussis. CREATE produit symbol → destination ID atomiquement après succès prouvé. Aucun ordre numérique implicite.
- State machines explicites : draft/validated/stale/confirmed/applying/partial/succeeded/failed/verification_failed; attempts prepared/in_flight/succeeded/failed/unknown. Transitions compare-and-swap et contraintes DB.
- Preflight revalide actor auth freshness, bot capabilities, hierarchy, Discord limits, observed versions, mapping et reversibility. Risk engine explique blast radius ; HIGH/CRITICAL confirmation renforcée liée au plan hash et expirante.
- API crée/simule/confirme/enqueue ; jamais REST mutation. Outbox plan+job atomique. Worker lock `did:guild:{guild_id}:mutation`, charge state puis ferme transaction avant Discord.
- Chaque appel porte idempotency metadata interne/audit reason quand supporté. Pour CREATE : persist `IN_FLIGHT` avant appel ; crash/succès non commit → `UNKNOWN_OUTCOME` au lease recovery ; rechercher déterministement via correlation/audit/propriétés ; ambiguïté = intervention, jamais retry aveugle.
- Compensation décrit `REVERSIBLE`, `RECREATABLE_NOT_RESTORABLE`, `NON_COMPENSABLE`; aucun faux rollback. Bulk reorder seulement si endpoint adapté.
- Succès REST écrit immédiatement cache/result/symbol/audit ; vérification ciblée compare desired/observed et marque drift. WebSocket tenant diffuse transition/progress après commit.
- Concurrency : un plan applying/Guild, cancellation uniquement aux frontières sûres, stale on relevant Gateway external change, backpressure du governor.

## F. Liste prévue de fichiers

Migrations plans/DAG/attempts/snapshots, `did/planning/{dsg,diff,compiler,preflight,risk,impact,state_machine,symbols}/**`, apply/recovery/verification workers, APIs/schemas/events, cache projectors, tests state/property/failure/live et extensions evidence.

## G. Stratégie de tests de l’étape

Unit/property : canonical diff, DAG cycles/topological order, state transitions, symbolic refs, risk/compensation. DB : immutability/constraints/concurrent claim/stale CAS. API A/B/CSRF/confirmation hash. Worker contracts for every Discord error. Failure injection at before call, after Discord success before DB, after result commit before ack, during verify. Assert no duplicate CREATE. Load fairness and progress ordering. Sandbox actual create/update/reorder/delete with cleanup and honest recreation semantics.

## H. Matrice de validation

| ID | Exigence | Test | Commande | Résultat attendu | Preuve |
|---|---|---|---|---|---|
| S05-PLAN / REQ-PLAN-001..016 | plan/DAG/apply/recovery | domain+DB+failure+live | `python scripts/validate_stage.py 05` | stale blocked, results persisted, unknown reconciled | JUnit/fault trace |
| S05-UX / REQ-UX-006..007 | progress/truthful success | WS/API E2E contract | même commande | ordered progress, success after accepted state | event log |
| S05-AUD / REQ-AUD-001..003 | actor/plan/audit reason | integration/live | même commande | every mutation correlated | audit evidence |
| S05-GW / REQ-GW-006 | external drift stales plan | Gateway→plan integration | même commande | relevant plan `STALE` before REST | JUnit |

## I. Commandes exactes de validation

```bash
docker compose -f compose.test.yaml up -d --wait
python scripts/validate_stage.py 05
python scripts/validate_stage.py 05 --profile failure-injection
python scripts/validate_stage.py 05 --include-discord-live
docker compose -f compose.test.yaml down
```

## J. Tests Discord réels

Guild A : plans create category/channel/role, reorder, overwrite, destructive confirmed operation ; injecter arrêt contrôlé après réponse Discord avant commit, redémarrer, réconcilier et prouver absence de doublon. Guild B : refus IDOR et fairness. Nettoyage par plan distinct audité ; documenter ce qui ne restaure pas ID/historique.

## K. Secrets / credentials nécessaires

| Nom | Obligatoire | Étape | Secret ? | Provenance | Stockage local | Stockage CI | Rotation |
|---|---:|---:|---:|---|---|---|---|
| Bot token + Guild A/B IDs | live | 05 | token oui | handoff 03 | `.env.local` | protected environment | politique sandbox |

## L. Critères d’acceptation

Toute mutation significative a plan/preflight/confirmation ; DAG cycle refusé ; plan sur version modifiée devient stale sans REST ; crash après succès create produit unknown puis un unique objet prouvé ou intervention ; aucun retry ambigu ; résultats/actor/audit persistés ; write-through visible ; 403/429 conformes ; succès UI non prématuré.

## M. Definition of Done

Migrations et state machines, tests y compris fault injection/live, sécurité/concurrence, REQ/preuves, régressions 01–04, docs/handoff/état, commit/push/PR/merge.

## N. Handoff obligatoire

Créer `STAGE_05_HANDOFF.md` avec schemas/hashes, state diagrams, operation catalog, crash points/results, compensation table, APIs/events, sandbox cleanup et extension points clone.

## O. Prompt de démarrage d’un nouveau chat Codex

```text
Implémente uniquement STAGE 05 de Discord Infrastructure Designer.
Lis AGENTS.md, le contrat global, l’état courant et intégralement STAGE_05_DESIRED_STATE_PLAN_AND_MUTATION_ENGINE.md ; exécute le PRECHECK.
N’implémente aucune étape suivante. Va jusqu’aux tests de crash entre succès Discord et commit DB, preuves, handoff, état/traçabilité, commit et PR. Ne retry jamais un UNKNOWN_OUTCOME ambigu.
```
