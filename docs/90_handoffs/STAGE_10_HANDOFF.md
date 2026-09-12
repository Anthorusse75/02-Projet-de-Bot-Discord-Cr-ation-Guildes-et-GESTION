# Handoff STAGE 10 — Product completion, security and acceptance

## État actuel (vérité unique)

| Champ | Valeur |
|---|---|
| Date | `2026-09-11` |
| Base intégrée | `ad7a2c5b3f4ca33faf4aa51c91b7cefb5c11cc8d` (`main`, tag `stage-09-complete`) |
| Branche | `stage/10-acceptance` |
| HEAD | `ca48bd8ebfbf7561ae3926ee221001d45aa9654e` |
| Publication | aucune PR, aucun push additionnel, aucun tag Stage 10, aucun déploiement production dans cette passe, conformément à l'instruction explicite |
| Statut | `BLOCKED_EXTERNAL_LIVE_CREDENTIALS` : tout le périmètre offline est implémenté ; la qualification Discord A/B obligatoire ne peut pas être certifiée |
| Traçabilité | 246/246 identifiants exacts ; 244 `VERIFIED`, `REQ-BOT-005` `IMPLEMENTED` avec `DEVIATION APPROVED`, `REQ-TEST-003` `IMPLEMENTED` mais non `VERIFIED` faute de live A/B |

Ce document décrit le worktree Stage 10 complet : S10-01–S10-04 sont contenus
dans le checkpoint HEAD ci-dessus ; S10-05–S10-16 restent volontairement non
committés. Le journal chronologique complet, y compris les premiers échecs et
leurs corrections, est
[`artifacts/stage10-audit/STAGE10_EXECUTION_LEDGER.md`](../../artifacts/stage10-audit/STAGE10_EXECUTION_LEDGER.md).

## Livré

- purge tenant réelle et isolée : données PostgreSQL et namespaces/routage
  Redis du seul tenant ciblé, ordre d'audit `TENANT_PURGED`, conservation des
  artefacts portables utilisateur et de l'historique de transfert ;
- audit cache-first de tous les bots d'une Guild détenant `ADMINISTRATOR`, puis
  carte effective lecture/écriture par bot et par salon ;
- compilation du pattern « bots écrivent, humains lisent » dans le moteur de
  plan existant, sans mutation Discord depuis FastAPI ou le frontend ;
- fermeture sécurité globale des routes, sessions/CSRF/CORS/OAuth, RLS forcée,
  isolation Redis/WebSocket et scans de secrets/dépendances ;
- tests de panne globaux, charge aux volumes contractuels et parcours Playwright
  complet dans quatre locales ;
- lazy-loading par route des surfaces Guild, ramenant le plus gros chunk de
  production à 485,50 kB sans avertissement ;
- génération de traçabilité reproductible et audit strict ;
- paquet RC local avec image backend, build frontend, SBOM CycloneDX, SARIF,
  manifeste et sommes SHA-256, sans tag ni déploiement.

## Topologie et processus réels

| Plan | Processus / composant | Responsabilité et limite |
|---|---|---|
| API | `uv run uvicorn did.api.main:app --host 0.0.0.0 --port 8000` | OAuth/session, API tenant-scopée, lecture cache-first, création d'intentions/jobs durables ; aucune mutation Discord structurelle directe |
| Worker | `uv run python -m did.worker` | consomme les jobs durables, réévalue autorisation/préflight, applique via adaptateurs Discord sous Discord REST Workload Governor, réconcilie les issues ambiguës |
| Scheduler | `uv run python -m did.scheduler` | réconciliation et campagnes différées/récurrentes/event-driven ; publication de travail durable seulement |
| Frontend | Vite/React, sortie `frontend/dist` | client session/CSRF ; routes Guild lazy-loadées ; aucune possession de bot token et aucune mutation Discord directe |
| PostgreSQL | `postgres:18.4-alpine` en test | source durable, RLS activée et forcée pour toutes les tables tenant/utilisateur, rôle runtime sans superuser ni `BYPASSRLS` |
| Redis | `redis:8.8.1-alpine` en test | cache Discord, wakeups/routage et coordination ; clés tenant-scopées et purge ciblée |
| Backend image | `python:3.13.14-slim-trixie` | installation `uv==0.12.5`, environnement verrouillé `--no-dev`, paquets Debian mis à jour, installateur global retiré |

`compose.test.yaml` ne lance volontairement que PostgreSQL et Redis : API,
worker, scheduler et frontend sont lancés par les validateurs/tests. Les
frontières de mutation restent inchangées : frontend → API → stockage/job
durable → worker gouverné → Discord.

## Migrations et cycle de données

- Tête unique : `0034_stage_10`.
- Chaîne Stage 10 : `0032_stage_09 → 0033_stage_10 → 0034_stage_10`.
- `0033_stage_10_transfer_plan_retention.py` conserve l'historique de transfert
  lorsque son plan destination disparaît.
- `0034_stage_10_tenant_purge_snapshot_erasure.py` permet la suppression des
  snapshots append-only uniquement dans la transaction de purge autorisée ;
  toute mise à jour reste interdite.
- Le downgrade/re-upgrade de `0034` et les tests A/B PostgreSQL/Redis ont passé.
- Aucun job, lock ou ressource Discord n'a été créé par la sonde live Stage 10,
  qui a échoué avant le premier check.

## Configuration requise (noms uniquement)

Configuration de base : `DID_APP_ENV`, `DID_DATABASE_URL`,
`DID_DATABASE_ADMIN_URL`, `DID_REDIS_URL`, `DID_LOG_LEVEL`,
`DID_HEALTH_TIMEOUT_SECONDS`.

OAuth, session et chiffrement : `DISCORD_CLIENT_ID`,
`DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI`, `SESSION_SECRET`,
`OAUTH_TOKEN_ENCRYPTION_KEY`, `DID_OAUTH_TOKEN_KEY_VERSION`,
`ARTIFACT_ENCRYPTION_KEY`, `ARTIFACT_PREVIOUS_ENCRYPTION_KEYS` (les alias
préfixés `DID_` acceptés par `Settings` restent valides).

Runtime/live sandbox : `DISCORD_BOT_TOKEN`, `DISCORD_TEST_GUILD_A_ID`,
`DISCORD_TEST_GUILD_B_ID`. Les deux Guild IDs doivent être des Snowflakes
distincts et le bot doit être membre autorisé des deux Guilds. Aucun nom ici
n'implique qu'une valeur soit fournie ou valide ; aucune valeur n'est consignée.

## CI, validation et preuves

`.github/workflows/ci.yml` couvre actuellement les validateurs et profils
Stage 01–09 sur push/PR `main` et `stage/**`, avec PostgreSQL/Redis réels et
publication des preuves. Il ne contient pas encore de job Stage 10. Ajouter un
job vert avant merge est requis après restauration du sandbox : le profil par
défaut Stage 10 est intentionnellement rouge tant que `REQ-TEST-003` ne peut
pas devenir `VERIFIED`; ne jamais rendre ce gate optionnel pour obtenir une CI
verte.

| Commande / scénario | Résultat actuel | Preuve |
|---|---|---|
| `python scripts/validate_stage.py 10` | FAIL attendu uniquement au dernier audit strict : toutes les régressions Stage 01–09, gates Stage 10 et RC passent ; `REQ-TEST-003` reste non vérifié | `artifacts/test-evidence/stage-10/20260911T211214731649Z-ca48bd8ebfbf-local-docker/summary.json` |
| `python scripts/validate_stage.py 10 --profile security` | PASS : 853 tests backend sécurité, 21 contrats ciblés, 7 tests frontend, audit npm et secrets | `artifacts/test-evidence/stage-10/20260911T213206165968Z-ca48bd8ebfbf-local-docker/summary.json` |
| `python scripts/validate_stage.py 10 --profile performance` | PASS : 11 tests de charge ; budgets Guild/plan/clone/campagne/gouverneur et navigateur respectés | `artifacts/test-evidence/stage-10/20260911T213336039045Z-ca48bd8ebfbf-local-docker/summary.json` |
| `python scripts/validate_stage.py 10 --profile failure-injection` | PASS : 191 passés, 1 088 désélectionnés, aucun filtre de nom | `artifacts/test-evidence/stage-10/20260911T213410648077Z-ca48bd8ebfbf-local-docker/summary.json` |
| `python scripts/validate_stage.py 10 --profile e2e` | PASS : 60/60 Playwright | `artifacts/test-evidence/stage-10/20260911T213504767592Z-ca48bd8ebfbf-local-docker/summary.json` |
| `uv run python scripts/validate_discord_live_stage02.py --include --report artifacts/test-evidence/stage-10/s10-12-credential-probe-stage02.json` | FAIL bloquant : `PermissionError` expurgé avant tout check | rapport indiqué, `secrets_recorded=false` |
| `python scripts/audit_requirements.py --strict` | FAIL attendu uniquement sur le MUST `REQ-TEST-003` | 246/246 IDs ; 244 `VERIFIED`, deux `IMPLEMENTED` |
| construction/import/scan `did-stage10-backend:rc-candidate` | PASS import ; 0 critique, 1 high sans correctif publié | `artifacts/stage10-audit/backend-image-cves.sarif` |
| `python scripts/package_stage10_rc.py --output-dir artifacts/stage10-audit --image did-stage10-backend:rc-candidate` | PASS : 61 checksums, manifeste/SBOMs ; aucun tag/déploiement | `artifacts/stage10-audit/release-manifest.json`, `SHA256SUMS` |

Les rapports lisibles sont :

- [`STAGE_10_SECURITY_ACCEPTANCE.md`](../30_security/STAGE_10_SECURITY_ACCEPTANCE.md) ;
- [`STAGE_10_PERFORMANCE_ACCEPTANCE.md`](../20_testing/STAGE_10_PERFORMANCE_ACCEPTANCE.md) ;
- [`STAGE_10_FAILURE_ACCEPTANCE.md`](../20_testing/STAGE_10_FAILURE_ACCEPTANCE.md) ;
- [`STAGE_10_TECHNICAL_DEBT_DISPOSITION.md`](../20_testing/STAGE_10_TECHNICAL_DEBT_DISPOSITION.md) ;
- [`STAGE_10_RELEASE_CANDIDATE.md`](../20_testing/STAGE_10_RELEASE_CANDIDATE.md) ;
- [`STAGE_10_DISCORD_LIVE_STATUS.md`](../20_testing/STAGE_10_DISCORD_LIVE_STATUS.md).

## RC, SBOM et scans

- Source enregistrée dans le manifeste :
  `ca48bd8ebfbf7561ae3926ee221001d45aa9654e`, avec
  `source_worktree_dirty=true` ; ce n'est donc pas encore un artefact de release
  immuable.
- Image locale : `did-stage10-backend:rc-candidate`, digest
  `sha256:98ac0b0437421dcb8ec506718f6b738ebefd53fb56f221121075d3bf5d6929c1`,
  `linux/amd64`, 72 MB, 180 paquets indexés.
- SBOMs : `backend-image.cdx.json` et `frontend.cdx.json` (CycloneDX).
- Scan : `backend-image-cves.sarif`, zéro critique ; un high Debian zlib
  `CVE-2026-85091`, `Fixed version: not fixed`, accepté comme risque connu à
  rescanner dès publication d'un correctif.
- Le frontend verrouillé rapporte zéro vulnérabilité au seuil moderate.
- `release-manifest.json` fixe `git_tag_created=false` et
  `production_deployed=false`. Aucun tag Stage 10 ne doit être créé avant un
  strict PASS live puis un commit explicitement autorisé.

## État Guild A/B et nettoyage

La configuration locale contient deux IDs distincts de forme Snowflake et des
credentials non-placeholder, sans valeur imprimée. La plus petite sonde Stage
02 a toutefois échoué avant tout check. Le reste de la matrice live n'a donc
pas été lancé, afin d'éviter des mutations avec une identité non autorisée.
Zéro fixture Stage 10 a été créée ; aucun nettoyage live Stage 10 n'est
nécessaire. Les preuves offline A/B PostgreSQL, Redis, API et navigateur ne
remplacent pas la preuve Discord réelle.

Action externe exacte : restaurer/remplacer le token du bot et ses permissions
dans les deux Guilds sandbox configurées, confirmer la sonde minimale, puis
exécuter :

```text
python scripts/validate_stage.py 10 --include-discord-live
```

Ce mode orchestre directement les huit validateurs live existants Stage
02/03/04/05/06/08/09 (primitives et chaîne complète), sans sentinel. Il ne doit
jamais utiliser de credentials production.

## Écarts, risques et bugs connus

- `REQ-TEST-003` est le seul MUST encore non `VERIFIED`; le strict audit et le
  statut Stage 10 doivent rester rouges jusqu'au PASS Discord A/B réel.
- `REQ-BOT-005` est implémenté et testé au backend. Sa visualisation dashboard
  est différée sous `DEVIATION APPROVED` car l'exigence est SHOULD ; l'API
  réelle n'est pas simulée ni supprimée.
- La CI n'a pas encore de job Stage 10, tel que décrit plus haut.
- Le high zlib sans version corrigée reste visible dans le SARIF ; il n'est ni
  filtré ni reclassé.
- Les événements `logging.unstructured_rejected` sont une protection fail-closed
  de redaction : le message libre tiers est omis. Ils restent visibles comme
  diagnostic et ne constituent pas un TODO caché.
- Aucun TODO/FIXME exécutable bloquant n'a été trouvé ; les skips restants sont
  exclusivement les gates explicites d'intégration/réseau.

## Prérequis exacts pour réécrire STAGE 11

STAGE 11 reste `SKELETON_ONLY` et ne doit pas commencer tant que tous les
points suivants ne sont pas satisfaits :

1. restaurer les credentials/permissions sandbox, exécuter
   `python scripts/validate_stage.py 10 --include-discord-live` et conserver les
   preuves A/B/nettoyage expurgées ;
2. régénérer la traçabilité pour promouvoir `REQ-TEST-003`, obtenir 246/246
   exigences acceptées et `python scripts/audit_requirements.py --strict` PASS ;
3. rejouer tous les profils Stage 10 et la validation documentaire sur un
   worktree propre ;
4. sur autorisation explicite seulement, committer/pousser, faire passer la CI
   Stage 10, revue externe et merge ;
5. reconstruire les SBOMs/manifeste/checksums sur le SHA propre mergé, rescanner
   les vulnérabilités puis créer le tag RC/Stage 10 autorisé ;
6. vérifier la tête Alembic `0034_stage_10`, les commandes API/worker/scheduler,
   les images/digests retenus et l'inventaire de variables ci-dessus ;
7. seulement alors, remplacer intégralement le squelette Stage 11 à partir de
   la topologie et des preuves de ce handoff. Aucun déploiement production n'est
   autorisé par ce handoff.
