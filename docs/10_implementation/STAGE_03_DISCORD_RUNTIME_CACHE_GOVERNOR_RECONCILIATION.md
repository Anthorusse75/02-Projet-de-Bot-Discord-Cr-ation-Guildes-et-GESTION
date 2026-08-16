# STAGE 03 — Runtime Discord, cache durable, obfuscation, rate limits et réconciliation

## A. Identité

| Champ | Valeur |
|---|---|
| Numéro / branche | `03` / `stage/03-discord-runtime` |
| Objectif | Construire le runtime Gateway et la connaissance locale fiable de Discord sous gouvernance REST. |
| Résultat attendu | Événements normalisés → cache PG/Redis, I/O Worker équitable, reconcile adaptatif, outbox/audit/observabilité et états d’observabilité sûrs. |
| Dépendances | 01–02 mergées ; installation, tenancy, Redis/RLS opérationnels. |
| Risque | Critique : état externe, rollout Discord futur, charge partagée et faux deletes. |

## B. Sources normatives

Spécifications §5.5–5.6, §30–31, §37–45, `REQ-GW-*`, `REQ-CACHE-*`, `REQ-RATE-*`, `REQ-AUD-*`, `REQ-INST-006`, `REQ-AUTH-013`, `REQ-TEN-005..009`. Architecture §10–11, §17–18, §20, §23–25, §28–33, §44–47, §52–56, §62, ADR-003/008/016–018/022–023/032/035, §71/74–79. Revalider IMP-001.

## C. PRECHECK obligatoire

```bash
git status --short --branch
test "$(git branch --show-current)" = "main"
python scripts/validate_stage.py 02
python -m alembic current
docker compose -f compose.test.yaml up -d --wait
git log -1 --oneline
```

Lire handoff 02 et IMP-001. Consulter changelog/docs Discord officiels pour `CHANNEL_OBFUSCATED`, payloads Gateway, intents et `GET Guild Channels`; enregistrer URL/date/contrat testé. Si la future annonce n’est toujours pas vérifiable, implémenter le modèle tolérant et fixtures contractuelles marquées, mais ne pas prétendre au live support du flag.

## D. Scope exact

Inclus : bot Gateway, intents minimaux, event envelope/dedup, channel/role/overwrite/member-authorization cache, observability/freshness/tombstones, Redis hot cache, I/O Worker/Workload Governor, REST adapter/protocol limiter integration, initial sync, adaptive reconcile, coalescing/single-flight/fairness, outbox, normalized audit/drift, tenant WS/pubsub isolation et metrics/traces.

Exclus : moteur permission complet (04), plan apply (05), UI produit (07), campaign REST workloads (09).

Work packages : contrats Gateway ; cache schema ; projectors/write-through ; obfuscation/purge ; REST worker/governor ; scheduler/reconcile ; outbox/audit/WS ; load/failure/live.

## E. Design d’implémentation détaillé

- Event envelope : `event_id`, `guild_id`, type, Discord sequence/session, occurred/received timestamps, correlation/causation, schema version et payload normalisé. Inbox/dedup durable ; consumers idempotents.
- Tables `discord_roles_cache`, `discord_channels_cache`, `channel_overwrites_cache`, tombstones, coverage/reconcile state et outbox/inbox. Colonnes `observability_state`, `last_observed_at`, `last_gateway_seq`, `version`, raw minimal versioned fields ; FK composites + RLS/index Guild/type/status.
- États `VISIBLE`, `OBFUSCATED`, `ACCESS_LOST`, `UNKNOWN`, `DELETED_CONFIRMED`, `USER_CONFIRMED_DELETED`; HTTP omission seule ne confirme jamais delete. Purge retire détail actif, garde tombstone minimal, ne fait aucun DELETE Discord ; réobservation prévaut.
- Cache read policy : PG durable, Redis projection hot namespacée et invalidable ; Gateway/mutation response write-through. Redis loss ne détruit pas la connaissance ; rebuild depuis PG.
- Discord adapter expose ports et erreurs métier, audit reason et headers de rate limit. Un seul owner logique du bot-token REST ; si library gère buckets, le Governor orchestre workload sans limiter concurrent incompatible.
- Priorités : apply continuation > unknown recovery > critical preflight > user refresh > background. Queue/lease durables, concurrency globale/type/Guild, round-robin/weighted fairness avec borne testée, backpressure et pause reconcile.
- Single-flight par Guild/resource/query ; jitter. 429 suit `Retry-After`; 401 stop token; 403/404 non retry aveugle; invalid request rolling budget/alerts.
- Scheduler utilise activité, age, gaps, plan pending, drift, coverage et budget ; aucun cron synchronisé de toutes les Guilds. Reconnect non-resumed marque stale puis job ciblé.
- API sert cache uniquement et peut enqueue refresh explicite ; WebSocket diffuse canal Guild autorisé. Logs sans secret, high-cardinality maîtrisée, metrics normatives.
- Transactions courtes : network hors transaction, persistence ensuite. Outbox atomique DB→Redis ; consumer ack après commit.

## F. Liste prévue de fichiers

Migrations cache/outbox, `did/bot/gateway/**`, `did/domain/cache/**`, `did/infrastructure/discord/**`, `did/worker/io/**`, `did/application/reconciliation/**`, `did/infrastructure/redis/**`, projectors, scheduler, audit/telemetry, API cache visibility/purge/refresh, tests contracts/load/failure et fixtures versionnées.

## G. Stratégie de tests de l’étape

Contract : Gateway create/update/delete, duplicates/out-of-order, reconnect, obfuscation versionnée. PG/Redis : RLS, projection, eviction/rebuild, stale/tombstone/reobservation. Governor : 429/global/shared, headers, invalid budget, backpressure, coalescing et fairness avec Guild très active. Failure : outbox publish fail, worker crash avant/after persistence, Redis down. API/WS : cache-hit zéro REST et isolation A/B. Sandbox : initial sync, external drift, visibility loss si officiellement testable.

## H. Matrice de validation

| ID | Exigence | Test | Commande | Résultat attendu | Preuve |
|---|---|---|---|---|---|
| S03-GW / REQ-GW-001..008 | intents/events/obfuscation | contracts + reconnect + live | `python scripts/validate_stage.py 03` | normalisé, idempotent, pas faux delete | JUnit/contracts |
| S03-CACHE / REQ-CACHE-001..013 | durable cache/reconcile | PG/Redis/failure | même commande | cache-first, tombstone sûr, rebuild | reports |
| S03-RATE / REQ-RATE-001..006 | governor | load/429/fairness | même commande | headers respectés, Guild bruyante bornée | benchmark |
| S03-AUD / REQ-AUD-001..006 | audit/drift/redaction | outbox/log tests | même commande | initiateur/correlation et aucun secret | JUnit/log scan |
| S03-TEN / REQ-TEN-005..009 | WS/cache/jobs isolation | A/B instrumenté | même commande | aucun événement/clé/job croisé | evidence |

## I. Commandes exactes de validation

```bash
docker compose -f compose.test.yaml up -d --wait
python scripts/validate_stage.py 03
python scripts/validate_stage.py 03 --profile load
python scripts/validate_stage.py 03 --include-discord-live  # variables présentes uniquement
docker compose -f compose.test.yaml down
```

Les profils sont créés dans cette étape ; absence de credentials = `SKIPPED_NOT_VERIFIED`, jamais PASS live.

## J. Tests Discord réels

A : sync catégories/salons/rôles/overwrites, modifications externes, reconnect et reprise. B : charge/refresh concurrent pour fairness et isolation. Retirer/rendre une visibilité seulement si le comportement officiel est disponible ; sinon conserver test contractuel marqué et décision ouverte pour STAGE 10. Nettoyer préfixes, ne jamais provoquer volontairement le seuil invalid requests.

## K. Secrets / credentials nécessaires

| Nom | Obligatoire | Étape | Secret ? | Provenance | Stockage local | Stockage CI | Rotation |
|---|---:|---:|---:|---|---|---|---|
| `DISCORD_BOT_TOKEN` | live | 03 | oui critique | Portal | `.env.local` | environment protégé | après test temporaire/exposition |
| Guild A/B IDs | live | 03 | non secret sensible | sandbox | `.env.local` | variables protégées | à recréation |
| credentials OAuth | non pour contracts, déjà 02 | 03 | oui selon champ | handoff 02 | secret store | environment | politique 02 |

## L. Critères d’acceptation

Un cache-hit dashboard effectue zéro GET Discord ; duplicate Gateway ne double pas l’effet ; perte Redis reconstruit depuis PG ; absence HTTP ne supprime pas ; purge n’appelle pas Discord ; 429 suit réponse ; 403 n’est pas retry ; trois refresh identiques font un appel ; sous charge A, B progresse dans la borne ; outbox résiste au publish fail ; WS A ne reçoit jamais B.

## M. Definition of Done

Migrations/code/tests/load/live applicable, metrics, official-doc revalidation, lint/typecheck/security, REQ/proofs, régressions 01–02, handoff/état, commit/push/PR/merge.

## N. Handoff obligatoire

Créer `STAGE_03_HANDOFF.md` avec schémas, intents, payload versions, cache states, keys/streams, governor parameters, benchmark fairness, statut exact Channel Obfuscation, sandbox et prérequis read model.

## O. Prompt de démarrage d’un nouveau chat Codex

```text
Implémente uniquement STAGE 03 de Discord Infrastructure Designer.
Lis AGENTS.md, le contrat global, l’état courant et intégralement STAGE_03_DISCORD_RUNTIME_CACHE_GOVERNOR_RECONCILIATION.md ; exécute le PRECHECK. Revalide les contrats Discord officiels, notamment Channel Obfuscation.
N’implémente aucune étape suivante. Termine code, migrations, tests de charge/panne/live applicables, preuves, handoff, état/traçabilité, commit et PR. Demande seulement les secrets requis au test live.
```
