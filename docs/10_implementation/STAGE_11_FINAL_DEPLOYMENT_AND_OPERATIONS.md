# STAGE 11 — Déploiement final et exploitation — SQUELETTE À RÉÉCRIRE

> **Statut obligatoire : `SKELETON_ONLY`.** Ce fichier n’est pas un guide de déploiement. Au démarrage réel de STAGE 11, il doit être réécrit intégralement à partir du Release Candidate et des ressources effectivement présentes. Aucune commande, architecture cloud, variable, image, migration, proxy ou procédure hypothétique ne doit être conservée comme vérité.

## A. Identité

| Champ | Valeur |
|---|---|
| Numéro / branche | `11` / `stage/11-final-deployment` |
| Objectif | Dériver, tester et exécuter le déploiement final depuis le dépôt réel. |
| Résultat attendu | Guide production exact, environnement déployé, smoke/live/backup/restore/rollback et runbook prouvés. |
| Dépendances | STAGE 10 mergée, RC immutable et toutes exigences produit vérifiées. |
| Risque | Critique maximal : production, secrets, données et disponibilité. |

## B. Sources normatives

À la réécriture : deux sources intégrales, architecture §36–43/57–58/66, ADR et décisions, **dépôt réel**, `STAGE_10_HANDOFF.md`, Dockerfiles/Compose/manifests, migrations, lockfiles, CI/CD, env access code, monitoring and chosen infrastructure. Les faits du code prévalent sur tout exemple ancien non normatif ; toute divergence exige décision.

## C. PRECHECK obligatoire

À exécuter avant toute réécriture/déploiement :

```bash
git status --short --branch
test "$(git branch --show-current)" = "main"
python scripts/validate_stage.py 10
python scripts/validate_documentation.py
git log -1 --oneline
```

Puis inventorier sans hypothèse : commit/tag RC, Dockerfiles/images, services réels (frontend/API/bot/worker/scheduler), healthchecks, ports, DB/Redis, migrations, variables référencées, secrets names, CI environments, storage, telemetry, reverse proxy/TLS choices, backup tooling and host/cloud constraints. Vérifier `STAGE_10_HANDOFF.md` and clean sandbox. Créer `stage/11-final-deployment`; obtenir l’autorisation humaine explicite avant toute mutation production ou DNS.

## D. Scope exact

Inclus après réécriture : architecture production réelle, machine/cloud prerequisites, DNS, TLS, reverse proxy, secrets, Discord Portal/redirect URIs, GitHub environments, build/publish, migrations, initial deploy, smoke/live validation, PostgreSQL backup/restore, Redis policy, observability/alerts, rotation, rollback/upgrade, incident/DR/uninstall, operational runbook, go-live/post-deploy checklists.

Exclus : fonctionnalités produit nouvelles, infrastructure supposée, changement architectural opportuniste non validé. Toute lacune produit retourne à une décision/PR dédiée avant go-live.

Work packages à remplacer par les vrais lots : inventory/design approval ; provisioning ; secret/config ; build/release ; data migration ; deploy ; smoke/live ; backup/restore/rollback drill ; monitoring/incident/DR ; handoff.

## E. Design d’implémentation détaillé

**À réécrire, ne pas compléter par imagination aujourd’hui.** Le document final doit nommer chaque service/image/tag, réseau/port/volume, table de variables avec source/consumer, secret manager, identity/permissions, topology/HA, DB pool/migration order, Redis durability/eviction, proxy/TLS/DNS, health/readiness, resource limits, scaling/sharding, queue draining, telemetry/SLI/SLO/alerts, backup retention/encryption/restore, rollback compatibility and failure domains réellement choisis.

## F. Liste prévue de fichiers

À dériver par `rg --files`, CI and code imports at STAGE 11. Modifier uniquement les manifests/runbooks/configs nécessaires réellement identifiés. Ne pas précréer aujourd’hui de faux `docker-compose.prod.yml`, Helm chart, Terraform ou proxy config.

## G. Stratégie de tests de l’étape

À réécrire avec commandes réelles : image scans/checksums, config validation, migration rehearsal on restored copy, smoke each process, OAuth redirect, Gateway, worker/scheduler, API/UI/WS, tenant isolation, Discord sandbox/live controlled, backup+restore, rollback, secret rotation, upgrade and incident/DR tabletop plus technical drills. Production data must never be copied unsafely to test.

## H. Matrice de validation

| ID | Exigence | Test | Commande | Résultat attendu | Preuve |
|---|---|---|---|---|---|
| S11-REWRITE | guide derived from RC | inventory review | `À REMPLACER` | zero hypothetical resource/command | reviewed diff |
| S11-DEPLOY | initial deployment | actual smoke suite | `À REMPLACER` | all real services healthy | deployment evidence |
| S11-DATA | migration/backup/restore | rehearsal + restore | `À REMPLACER` | integrity and measured RPO/RTO | drill report |
| S11-ROLLBACK | rollback/upgrade | actual drill | `À REMPLACER` | tested recovery path | drill report |
| S11-LIVE | Discord/OAuth/tenant | controlled live tests | `À REMPLACER` | critical flows and isolation pass | expurgated report |

Ces placeholders sont intentionnels et doivent tous disparaître lors de la réécriture.

## I. Commandes exactes de validation

Non définissables avant le RC réel. Le futur document doit remplacer cette section par les commandes existantes et vérifiées, puis fournir `python scripts/validate_stage.py 11` orchestrant les contrôles non destructifs et guidant explicitement les drills nécessitant approbation.

## J. Tests Discord réels

À détailler depuis les Guilds sandbox et l’environnement production réels. Exiger au minimum OAuth redirect réel, installation/Gateway, cache/reconcile, plan contrôlé, WS isolation et nettoyage. Toute action sur une Guild non sandbox nécessite autorisation explicite et plan de retour.

## K. Secrets / credentials nécessaires

| Nom | Obligatoire | Étape | Secret ? | Provenance | Stockage local | Stockage CI | Rotation |
|---|---:|---:|---:|---|---|---|---|
| Inventaire réel | à déterminer | 11 | à classifier | code + fournisseurs réels | secret store approuvé | GitHub environment réel | procédure testée |

Le futur tableau doit énumérer chaque nom consommé par le code, son propriétaire, injection, accès minimal, rotation/revocation and disaster access. Ne jamais placer de valeur.

## L. Critères d’acceptation

Le squelette est accepté aujourd’hui si aucune infrastructure finale n’est inventée. STAGE 11 réel n’est accepté que si le guide est entièrement réécrit, toutes commandes testées, deploy/smoke/live verts, backup restauré, rollback/rotation exercés, monitoring/alerts actifs, DNS/TLS/redirects exacts et checklists signées.

## M. Definition of Done

Après réécriture seulement : documentation exacte, manifests/code ops, migrations appliquées, tests/scans/drills verts, secrets protégés, production validée, handoff/état/traceability, clean commit/push/PR and operations ownership. Le présent squelette ne satisfait pas cette DoD.

## N. Handoff obligatoire

Créer `docs/90_handoffs/STAGE_11_HANDOFF.md` avec production commit/image digests, actual topology, migration, deploy/smoke/live results, backups/restore/rollback evidence, DNS/TLS, alerts, secret names/rotation status, incidents/risks, operations owner and post-deploy state—sans aucune valeur secrète.

## O. Prompt de démarrage d’un nouveau chat Codex

```text
Implémente uniquement STAGE 11 de Discord Infrastructure Designer.
Avant toute modification, lis AGENTS.md, le contrat global, l’état courant, STAGE_10_HANDOFF.md et intégralement le présent squelette ; exécute le PRECHECK.
Commence par inventorier le repository réel, puis réécris intégralement STAGE_11_FINAL_DEPLOYMENT_AND_OPERATIONS.md depuis les Dockerfiles, services, migrations, variables, CI/CD, DB/Redis, proxy/TLS et monitoring réellement présents. N’invente aucune commande ou infrastructure.
Après validation humaine des choix et avant toute mutation production/DNS, demande l’autorisation minimale requise. Termine déploiement, smoke/live, backup-restore, rollback, runbook, preuves, handoff, état/traçabilité, commit et PR.
```
