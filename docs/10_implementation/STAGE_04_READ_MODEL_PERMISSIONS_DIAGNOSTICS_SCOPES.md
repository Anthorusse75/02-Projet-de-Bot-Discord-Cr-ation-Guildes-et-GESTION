# STAGE 04 — Read model, Permission Engine, diagnostics, groupes logiques et Visibility Scopes

## A. Identité

| Champ | Valeur |
|---|---|
| Numéro / branche | `04` / `stage/04-read-permissions` |
| Objectif | Transformer le cache Discord en projections fidèles et explications de permissions fiables. |
| Résultat attendu | Structure/rôles cache-first, View As/Why Access, coverage/capabilities, groupes logiques et scopes utilisables sans mutation. |
| Dépendances | STAGE 03 mergée ; cache, observability et refresh ciblé fonctionnels. |
| Risque | Critique : une permission mal calculée peut autoriser ou bloquer une mutation future. |

## B. Sources normatives

Spécifications §8, §11, §14–24, §31–32, §44–45, `REQ-STR-001..005`, `REQ-PERM-*`, `REQ-BOT-003..006`, `REQ-AUTH-013..014`. Architecture §7.8–7.9/7.18–7.20B, §12, §15–16, §21, §23–24, §35, §48–49, §53–54, ADR-007/009/012/016–017/022/032/035.

## C. PRECHECK obligatoire

```bash
git status --short --branch
test "$(git branch --show-current)" = "main"
python scripts/validate_stage.py 03
python -m alembic current
git log -1 --oneline
```

Vérifier handoff 03, cache states et version d’envelope attendus, governor disponible et aucune décision Channel Obfuscation non représentée. Créer `stage/04-read-permissions`; refuser si la projection devrait appeler REST en lecture normale.

## D. Scope exact

Inclus : read repositories/projections structure/rôles/overwrites, vues active et masqués/supprimés, métadonnées fraîcheur/couverture, Permission Evaluator conforme, simple/expert read models, View As/Why Access, impact read-only, bot capability checker, logical groups/membership, Visibility Scopes et Scope Membership Resolver, targeted actor refresh policy, diagnostics.

Exclus : compiler/appliquer des mutations (05), clone (06), dashboard complet (07), matérialisation Scope × Language (08).

Work packages : projections ; evaluator ; explain/simulation ; capabilities/coverage ; logical groups ; scopes/membership ; API/WS ; tests officiels/live.

## E. Design d’implémentation détaillé

- Modèle domaine immutable : Guild/Role/Member/Channel/Overwrite snapshots avec observability/freshness explicites. Threads et channel types supportés selon capability registry ; aucune sous-catégorie inventée.
- Permission bitfields restent `int` Python arbitraire et string API. Algorithme : owner/ADMINISTRATOR, base @everyone + roles, overwrites @everyone, agrégation deny/allow roles, member overwrite, implicit permissions et héritage threads conformément aux docs officielles versionnées.
- `PermissionDecision` contient effective bits, unknown/incomplete coverage, ordered explain trace et sources ; ne jamais conclure allow lorsque données critiques manquent. `Why Access` distingue Discord réel et policy dashboard.
- `View As` accepte member, role ou newcomer synthétique explicitement ; aucune permission inventée. Impact compare current/proposed input sans mutation.
- Tables `logical_groups`, `logical_group_resources`, `visibility_scopes`, `scope_membership_rules`; uniques/FK composites/RLS. Aucun logical group récursif. Membership rules compilées avec diagnostic et cache versionné.
- Capability checker combine permissions bot, hiérarchie, intents, channel access et limites registry ; produit causes/remédiations sans proposer `ADMINISTRATOR` par défaut.
- Autorisation sensible : si rôles acteur dépassent safety TTL, demander un refresh ciblé via STAGE 03 avant décision ; fraîcheur UI peut rester aging.
- API `/structure`, `/roles`, `/permissions/evaluate|explain|simulate`, `/coverage`, `/capabilities`, `/logical-groups`, `/visibility-scopes`; lecture cache-first, Snowflakes strings, tenant guard avant repositories.
- Observabilité : evaluator duration, incomplete decisions, targeted refresh, coverage gaps ; aucune explosion de labels user/channel.

## F. Liste prévue de fichiers

Migrations groupes/scopes, `did/permissions/**`, `did/domain/read_model/**`, projectors/query services, capabilities/coverage, logical_groups/scopes resolvers, routers/schemas, fixtures vecteurs permission et tests property/integration/sandbox.

## G. Stratégie de tests de l’étape

Unit/table-driven sur vecteurs officiels : owner, ADMINISTRATOR, role collision, member override, implicit, threads, synced/desynced. Property tests invariants bitfields/trace. DB/API A/B. Cache states : stale/obfuscated entraîne inconnu visible. Targeted actor refresh vs display age. Sandbox compare membres/rôles et channel permissions réels. Capability hierarchy et no-ADMINISTRATOR recommendation. Logical groups non récursifs et scope resolution deterministic.

## H. Matrice de validation

| ID | Exigence | Test | Commande | Résultat attendu | Preuve |
|---|---|---|---|---|---|
| S04-STR / REQ-STR-001..005 | structure fidèle | projection + sandbox | `python scripts/validate_stage.py 04` | types/parents/suppression réels | snapshot diff |
| S04-PERM / REQ-PERM-001..009 | evaluator/explain | official vectors + property + live | même commande | bitfields exacts et trace stable | JUnit/live |
| S04-BOT / REQ-BOT-003..006 | capabilities | hierarchy/overwrite tests | même commande | diagnostic précis et configuration réelle | evidence |
| S04-AUTH / REQ-AUTH-013..014 | refresh acteur | cache age integration | même commande | lookup ciblé pour action sensible | trace adapter |

## I. Commandes exactes de validation

```bash
docker compose -f compose.test.yaml up -d --wait
python scripts/validate_stage.py 04
python scripts/validate_stage.py 04 --include-discord-live
docker compose -f compose.test.yaml down
```

## J. Tests Discord réels

Dans A, créer rôles/overwrites couvrant allow/deny, member override, ADMINISTRATOR, thread et bot hierarchy ; comparer résultat DID aux observations Discord documentées. B sert aux refus tenant. Inventorier et nettoyer toutes ressources préfixées.

## K. Secrets / credentials nécessaires

| Nom | Obligatoire | Étape | Secret ? | Provenance | Stockage local | Stockage CI | Rotation |
|---|---:|---:|---:|---|---|---|---|
| Bot token + Guild A/B IDs | live seulement | 04 | token oui | handoff 03/Portal | `.env.local` | environment protégé | politique 03 |

## L. Critères d’acceptation

Les vecteurs officiels sont exacts, y compris ADMINISTRATOR/overwrites ; toute donnée insuffisante produit inconnu explicite ; View As n’invente rien ; un cache acteur aging déclenche un seul lookup ciblé ; structure ne montre aucune fausse hiérarchie ; A/B isolés ; capacités expliquent permissions/intents/hiérarchie manquants.

## M. Definition of Done

Migration/code/API/tests/live, sécurité et performance, traceability/preuves, régression 01–03, docs/handoff/état, commit/push/PR/merge.

## N. Handoff obligatoire

Créer `STAGE_04_HANDOFF.md` avec algorithme/version docs Discord, vecteurs, schémas, endpoints, policy de fraîcheur, limites connues et contrat d’entrée pour Desired State Graph.

## O. Prompt de démarrage d’un nouveau chat Codex

```text
Implémente uniquement STAGE 04 de Discord Infrastructure Designer.
Lis AGENTS.md, le contrat global, l’état courant et intégralement STAGE_04_READ_MODEL_PERMISSIONS_DIAGNOSTICS_SCOPES.md ; exécute le PRECHECK et vérifie les permissions Discord officielles.
N’implémente aucune étape suivante. Termine code, migrations, tests/vecteurs/live, preuves, handoff, état/traçabilité, commit et PR.
```

## P. Revue corrective du 2026-08-24

La revue post-livraison conserve strictement le périmètre STAGE 04 et le caractère read-only vis-à-vis de Discord. La migration `0007_stage_04` ajoute la couverture des threads actifs, l’état `ACTIVE/ARCHIVED/NOT_IN_ACTIVE_SYNC/UNKNOWN`, les preuves d’adhésion du bot par thread et le check de couplage des Visibility Scopes.

Le consumer normalise et projette désormais `THREAD_LIST_SYNC`, `THREAD_MEMBER_UPDATE` et `THREAD_MEMBERS_UPDATE`. Les synchronisations scoped et Guild entière ne transforment jamais une absence en suppression ; elles préservent le dernier payload et rendent l’observabilité inconnue. L’évaluateur contrôle séparément fraîcheur/observabilité du thread et du parent, utilise une preuve privée par thread, et applique le verrouillage à `SEND_MESSAGES_IN_THREADS` ainsi qu’à ses dépendances.

Les frontières API rejettent explicitement permissions inconnues, rôles View As absents, cibles capability manquantes ou inexistantes, cibles d’overwrite non résolues et scopes incohérents. Une preuve PostgreSQL traverse le Gateway normalisé, le projecteur durable, le repository STAGE 04 et le Permission Evaluator. La décision normative complète est `IMP-011`.
