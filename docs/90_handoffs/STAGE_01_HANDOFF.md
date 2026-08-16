# Handoff STAGE 01 — Repository, environnement local et fondations techniques

| Champ | Valeur |
|---|---|
| Date | `2026-08-16` |
| Base `main` | `5f27d043c0e3f3f1d38fda361720113c4e9f67db` (`implementation-baseline^{}`) |
| Commit d’implémentation | `96f545a249e330906bf941e088dd8d63d6f856a6` |
| Branche / PR | `stage/01-foundations` / [draft PR #1](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/1) |
| Statut | `COMPLETE` ; branche publiée et draft PR ouverte |

## Livré

- monorepo `backend/` + `frontend/`, lockfiles `uv.lock` et `frontend/package-lock.json` ;
- backend modulaire `did.domain`, `did.application`, `did.infrastructure`, `did.api`, `did.bot`, `did.worker`, `did.scheduler`, `did.tenancy` et `did.settings` ;
- API FastAPI limitée à `/health/live` et `/health/ready`, probes PostgreSQL/Redis bornées, middleware de correlation ID et logs JSON expurgés ;
- processus bot/worker/scheduler à lifecycle propre, sans import Discord ni credential ;
- PostgreSQL 18.4, Redis 8.8.1, Compose dev/test isolés et image backend Python 3.13.14 ;
- migration Alembic `0001_stage_01` : rôle applicatif, fonctions de contexte transactionnel, table canari, policy RLS `USING` + `WITH CHECK`, `FORCE ROW LEVEL SECURITY` ;
- transactions SQLAlchemy async courtes avec contexte `SET LOCAL` via `set_config(..., true)` ;
- constructeur Redis obligatoire `did:guild:{guild_id}:...` ;
- frontend React/Vite minimal, TypeScript strict et Snowflakes sous forme de strings ;
- scripts Git Bash Windows 11, orchestrateur déclaratif, scan de secrets et CI GitHub Actions ;
- événements de log fermés dans un registre statique, valeurs dynamiques sous `fields`, redaction
  récursive et rejet sans rendu du message pour tout log non structuré ;
- preuves immuables sous `artifacts/test-evidence/stage-XX/<run-id>/`, ignorées localement et
  uploadées en CI ; aucun JUnit local ni hostname de poste n’est committé ;
- garde d’architecture récursif sur tous les sous-packages de `did.domain` ; traçabilité STAGE 01
  actualisée exclusivement par le générateur.

## Versions réellement pinées

Backend direct : Python `3.13`, `uv 0.12.5`, FastAPI `0.141.1`, Uvicorn `0.52.3`, Pydantic `2.13.4`, Pydantic Settings `2.15.0`, SQLAlchemy `2.0.52`, asyncpg `0.31.0`, Alembic `1.19.1`, redis-py `8.1.0`, Ruff `0.16.3`, mypy `2.3.1`, pytest `9.1.1`, pytest-asyncio `1.4.0` et pytest-cov `7.1.0`.

Frontend direct : Node `24.13.0` en CI, React/React DOM `19.2.8`, React Router DOM `7.18.2`, Vite `8.2.1`, TypeScript `5.9.3`, Vitest `4.1.10`, ESLint `10.8.1`, typescript-eslint `8.67.0`, Testing Library React `16.3.2` et jsdom `29.0.1`.

Images : `python:3.13.14-slim-trixie`, `postgres:18.4-alpine`, `redis:8.8.1-alpine`.

Actions CI vérifiées depuis les tags de leurs dépôts officiels :
`actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803` (`v6.1.0`),
`actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1` (`v6.3.0`),
`astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9` (`v9.0.0`),
`actions/setup-node@249970729cb0ef3589644e2896645e5dc5ba9c38` (`v6.5.0`) et
`actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f` (`v6.0.0`).

## Validation et preuves

| Commande/scénario | Résultat | Preuve | REQ couverts |
|---|---|---|---|
| PRECHECK Git Bash complet | PASS | sortie locale du 2026-08-16 | prérequis STAGE 01 |
| `python scripts/validate_stage.py 01` | PASS, 19/19 gates | résumé local immuable ignoré ; résumé/JUnit de la CI dans l’artefact `stage-01-test-evidence-<sha>-<run-id>-attempt-<n>` | matrice S01 complète |
| backend unit | 30 PASS | JUnit du même run ; inclut architecture récursive, logging sûr et framework de preuves | TEN-001, TEN-007, AUD-004, BOT-001 |
| PostgreSQL/Redis integration | 4 PASS | JUnit du même run | TEN-001, TEN-007, TEN-010 |
| RLS A/B + absence contexte | PASS : A ne lit pas B, contexte absent retourne 0 ligne | test `test_rls_a_b_and_absent_context_are_fail_closed` | TEN-001, TEN-010 |
| RLS écriture cross-tenant | PASS : violation policy attendue | même test d’intégration | TEN-001, TEN-010 |
| pool reuse | PASS : même `pg_backend_pid()` pour A, B et contexte absent, sans fuite | test `test_pool_reuse_resets_transaction_local_tenant_context` | TEN-010 |
| Redis réel | PASS : PING, SET/GET/DELETE avec namespace Guild | test `test_real_redis_uses_tenant_namespace` | TEN-007 |
| frontend lint/typecheck/tests/build | PASS ; 3 tests | résumé de validation | baseline TEST-005 |
| Docker build + Compose dev/test | PASS ; services healthy | résumé de validation | fondations infrastructure |
| `python scripts/validate_documentation.py` | PASS ; 11 stages, 246/246 REQ, 35 ADR | résumé de validation | traçabilité |
| Git Bash `bash -n` + `./scripts/bootstrap.sh` | PASS | sortie locale du 2026-08-16 | compatibilité Windows 11 |
| `python scripts/check_secrets.py` | PASS | gate détaillée et `redactions_checked=true` dans `summary.json` | AUD-004, BOT-001 |
| `git diff --check` | PASS | contrôle local avant commit | qualité dépôt |
| GitHub Actions CI | PASS sur `cec914d` | [run 31950389082](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/actions/runs/31950389082) | matrice S01 complète |

Le run ci-dessus est une preuve représentative historique liée à son SHA. Pour le HEAD courant de
la PR #1, l’onglet Checks de la PR est la source de vérité. Chaque CI produit un artefact nommé avec
le SHA, le run ID et la tentative ; le handoff n’est pas recommitté pour recopier chaque nouveau run
ID. Après merge seulement, le PRECHECK de l’étape suivante enregistrera et vérifiera le SHA intégré.

## État opérationnel

- stack test : PostgreSQL `18.4` et Redis `8.8.1` étaient healthy pendant la validation, puis la stack a été arrêtée proprement avec `docker compose -f compose.test.yaml down` ;
- dernière migration : `0001_stage_01` (Alembic head) ;
- Guild sandbox : non requise et non configurée pour STAGE 01 ;
- secrets/configuration encore requis : aucun secret Discord ; uniquement les URLs locales factices de Compose ;
- jobs/queues/locks résiduels : aucun ; aucune fonctionnalité Discord, OAuth, cache métier, plan ou campagne n’existe ;
- CI : workflow livré ; run représentatif `31950389082` PASS sur `cec914d`, tandis que les checks de
  la PR #1 font autorité pour tout HEAD plus récent.

## Écarts, risques et bugs connus

- PostgreSQL 18 exige le montage `/var/lib/postgresql` plutôt que l’ancien `/var/lib/postgresql/data`; les deux fichiers Compose suivent cette contrainte officielle ;
- `scripts/validate_documentation.py` énumère désormais les seuls fichiers committables afin de ne pas scanner `.venv`/`node_modules`, tout en conservant le scan des fichiers trackés et non trackés non ignorés ;
- les exigences `REQ-TEST-001..005` restent `PLANNED` pour leurs comportements produit/live ; STAGE 01 livre seulement leur harnais de test ;
- `REQ-TEN-001`, `REQ-TEN-007`, `REQ-TEN-010`, `REQ-AUD-004` et `REQ-BOT-001` restent
  `IMPLEMENTED` : STAGE 01 prouve leurs fondations, mais les tables, caches, emitters et frontières
  des étapes futures peuvent encore les violer ; leur vérification transverse finale reste STAGE 10 ;
- les artefacts locaux bruts sont ignorés, les artefacts CI sont conservés par GitHub Actions et le
  dépôt ne suit que la convention et ce handoff ;
- aucun TODO bloquant, test désactivé, faux objet Discord ou secret tracké n’a été identifié ;
- STAGE 02 n’a pas été commencé.

## Prérequis exacts de l’étape suivante

- merger la PR STAGE 01 sur `main`, puis repartir de son SHA final ;
- vérifier `alembic heads` = `0001_stage_01` et `python scripts/validate_stage.py 01` vert ;
- conserver les modules de settings, tenancy, sessions DB et RLS comme fondations ;
- exécuter le PRECHECK de `STAGE_02_OAUTH_SESSIONS_TENANCY_RBAC_INSTALLATION.md` ;
- demander les credentials OAuth2 Discord uniquement lorsque les tests de STAGE 02 les exigent, jamais les placer dans Git ou dans un prompt.
