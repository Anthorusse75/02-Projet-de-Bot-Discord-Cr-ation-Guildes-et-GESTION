# STAGE 01 — Repository, environnement local et fondations techniques

## A. Identité

| Champ | Valeur |
|---|---|
| Numéro / branche | `01` / `stage/01-foundations` |
| Objectif | Produire un monorepo exécutable et testable, sans fonctionnalité métier, avec fondations DB/Redis/RLS/CI. |
| Résultat attendu | API, bot, worker, scheduler et frontend démarrent en squelette ; PostgreSQL/Redis et migrations fonctionnent ; gates de qualité reproductibles. |
| Dépendances | Commit documentaire initial sur `main`; aucune migration ni code préalable. |
| Risque | Élevé : les choix de packaging, transactions et tenancy conditionnent toutes les étapes. |

## B. Sources normatives

- Spécifications : §2.2, §41–46, §52–53 (notamment `REQ-TEN-001`, `REQ-TEN-007`, `REQ-TEN-010`, `REQ-AUD-004`, `REQ-BOT-001`, `REQ-TEST-*`).
- Architecture : §2–7, §23, §26–27, §31–43, §57–59, §64.1, §69–80.
- ADR : ADR-002, 005, 006, 009, 016, 018, 019, 022.

## C. PRECHECK obligatoire

Depuis Git Bash :

```bash
git status --short --branch
test "$(git branch --show-current)" = "main"
git log -1 --oneline
python --version
node --version
npm.cmd --version
docker version
docker compose version
python scripts/validate_documentation.py
```

Vérifier un worktree propre, les deux SHA du manifeste, aucun code produit, aucun secret, Docker Desktop démarré et `main` au commit documentaire. Créer ensuite `stage/01-foundations`. Refuser de continuer si la validation documentaire ou Docker requis échoue. Git Bash invoque normalement `npm`; `npm.cmd` est l’alternative documentée si PowerShell bloque `npm.ps1`.

## D. Scope exact

Inclus : monorepo `backend/` + `frontend/`, `pyproject.toml`/lock Python, npm lockfile, settings typés, `.env.example`, Compose dev/test, PostgreSQL, Redis, Alembic initial, contexte tenant et RLS minimal, sessions DB, health endpoints sans métier, processus skeleton, logs/correlation, lint/typecheck/test baseline, CI et orchestrateur de validation.

Exclus : OAuth réel, connexion Gateway, imports Discord, permissions métier, plans, UI produit et déploiement production.

Work packages : (1) choix/pin des versions et layout ; (2) backend en couches et settings ; (3) PostgreSQL/Redis/Compose ; (4) Alembic + helpers RLS ; (5) frontend Vite minimal ; (6) scripts Git Bash ; (7) qualité/tests/CI ; (8) documentation/handoff.

## E. Design d’implémentation détaillé

- `backend/src/did/{domain,application,infrastructure,api,bot,worker,scheduler,tenancy}` avec règles d’import ; objets de transport externes interdits dans le domaine.
- SQLAlchemy async + PostgreSQL ; convention PK UUID interne, Snowflakes `bigint` côté DB/Python et chaînes à la frontière HTTP. Créer une migration bootstrap pour extensions réellement nécessaires, rôles DB applicatifs/test, fonctions de contexte `app.current_guild_id`/`app.current_user_id` et une table canari tenant-scopée uniquement si elle est utile aux tests RLS ; ne pas anticiper toutes les tables métier.
- Le pool initialise puis réinitialise le contexte RLS par transaction ; contexte absent = deny. Test dédié contre fuite de contexte lors de réutilisation de connexion.
- Redis fournit clients namespacés, health check et primitives testables ; aucune clé métier sans builder explicite.
- Settings Pydantic : profils `development`, `test`, `production`; validation fail-fast ; représentation redacted. `.env.example` contient noms/valeurs factices, `.env.local` reste ignoré.
- API `/health/live` et `/health/ready` ; ready vérifie DB/Redis avec délais bornés. Aucun endpoint Discord.
- Processus bot/worker/scheduler démarrent et s’arrêtent proprement sans token en mode test ; contrats de lifecycle, logs JSON et correlation ID.
- Frontend React/TypeScript/Vite strict, route shell et test minimal ; IDs Discord typés string. Pas de fausse interface produit.
- Compose sépare volumes/réseaux dev/test et expose healthchecks. Les scripts attendent Docker Desktop sans WSL.
- CI : backend lint/format/type/tests, frontend lint/type/tests/build, migration smoke, PostgreSQL/Redis intégration, validation documentaire et secret scan raisonnable.
- `scripts/validate_stage.py` créé ici : registry déclaratif par étape, exécution sans shell-specific fragile, codes de sortie, timeouts et résumé de preuve.

## F. Liste prévue de fichiers

`pyproject.toml`, lock Python, `backend/src/did/**`, `backend/tests/**`, `alembic.ini`, `backend/alembic/**`, `frontend/package.json`, lock npm, `frontend/src/**`, `compose.yaml`, `compose.test.yaml`, `.env.example`, `scripts/{bootstrap.sh,dev.sh,test.sh,validate_stage.py}`, `.github/workflows/ci.yml`, configs Ruff/mypy/pytest/ESLint/TypeScript/Vitest. Tout écart est justifié dans le handoff.

## G. Stratégie de tests de l’étape

Unit : settings/redaction, key builders, tenant context et boundaries. Intégration : PostgreSQL/Redis réels, migrations base vide→head, RLS A/B et pool reuse, health. Frontend : typecheck/build/component shell. Process : startup/shutdown et signal. CI : mêmes commandes sur Windows-compatible paths et Linux runner. Security : secret scan, `.env.local` non tracké. Aucun test Discord live.

## H. Matrice de validation

| ID | Exigence | Test | Commande | Résultat attendu | Preuve |
|---|---|---|---|---|---|
| S01-01 / REQ-TEN-001,010 | contexte/RLS foundation | PostgreSQL A/B + absence contexte | `python scripts/validate_stage.py 01` | deny cross-tenant et contexte absent | JUnit + summary |
| S01-02 / REQ-TEN-007 | namespace Redis | unit + Redis réel | même commande | aucune clé tenant sans Guild | JUnit |
| S01-03 / REQ-AUD-004, BOT-001 | secrets/redaction | tests + scan | même commande | aucune valeur sensible exposée | rapport scan |
| S01-04 / REQ-TEST-001..005 | testability baseline | CI complète | même commande | tous gates verts | run CI |

## I. Commandes exactes de validation

À créer durant WP6 puis exécuter depuis Git Bash :

```bash
docker compose -f compose.test.yaml up -d --wait
python scripts/validate_stage.py 01
docker compose -f compose.test.yaml down
git diff --check
git status --short
```

La commande orchestre les outils réellement retenus ; le document ne présume pas leurs sous-commandes avant création des lockfiles.

## J. Tests Discord réels

Non requis. Aucun credential Discord ne doit être demandé. Les ports Discord restent non connectés et contractuellement testables.

## K. Secrets / credentials nécessaires

| Nom | Obligatoire | Étape | Secret ? | Provenance | Stockage local | Stockage CI | Rotation |
|---|---:|---:|---:|---|---|---|---|
| `DATABASE_URL` test | oui | 01 | oui | Compose | `.env.local` ou défaut test non sensible | service CI | recréation stack |
| `REDIS_URL` test | oui | 01 | selon config | Compose | `.env.local` | service CI | recréation stack |
| Discord credentials | non | 01 | — | — | — | — | — |

## L. Critères d’acceptation

Un clone propre peut être bootstrapé depuis Git Bash ; Compose devient healthy ; migration head s’applique ; test RLS prouve que A ne lit pas B et qu’un contexte absent refuse ; chaque processus skeleton démarre sans fonction métier ; frontend build ; CI et `validate_stage.py 01` verts ; aucun secret ou faux objet Discord.

## M. Definition of Done

Code foundation complet, lockfiles, migration appliquée/testée, lint/format/typecheck/tests verts, CI verte, sécurité vérifiée, docs/traceability actualisées, aucun REQ assigné sans preuve, régression documentaire verte, handoff et état courant mis à jour, commit propre, branche poussée et PR ouverte si GitHub disponible.

## N. Handoff obligatoire

Créer `docs/90_handoffs/STAGE_01_HANDOFF.md` avec SHA/PR, versions pinées, commandes, migration head, containers, modules, écarts, configs et prérequis exacts OAuth/RLS de STAGE 02.

## O. Prompt de démarrage d’un nouveau chat Codex

```text
Implémente uniquement STAGE 01 de Discord Infrastructure Designer.
Avant toute modification : lis AGENTS.md, le contrat global, l’état courant et intégralement STAGE_01_REPOSITORY_ENVIRONMENT_AND_FOUNDATIONS.md ; exécute son PRECHECK et consulte les sources pour toute ambiguïté.
N’implémente aucune étape suivante. Va jusqu’au code, tests, preuves, handoff, mise à jour d’état/traçabilité, commit et PR. Demande seulement le secret ou l’action externe réellement nécessaire au moment utile.
```
