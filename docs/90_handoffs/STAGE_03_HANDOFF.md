# Handoff STAGE 03 — Runtime Discord, cache et réconciliation

| Champ | Valeur |
|---|---|
| Date | `2026-08-17` |
| Base main | `366e676880d0c3f4c7cf4f54105a117b2dcda3d8` |
| Branche | `stage/03-discord-runtime` |
| Draft PR | [#3](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/3) vers `main` |
| Commit code initial | `795f3904d72455ae2e79c1978cc30a42dbf36050` |
| Commit correctif runtime | `8127e80616fcd57247377386422eb5082003e527` |
| Commit format | `6a964642151a3fa048706c3c5753cfe8585ef287` |
| Migration | `0002_stage_02 -> 0003_stage_03 -> 0004_stage_03` |
| Statut | `CORRECTED_PR_OPEN` |

## Runtime Gateway et contrats

- `discord.py==2.7.1` est figé. Le process bot démarre `DiscordGatewayClient` quand `DISCORD_BOT_TOKEN` est configuré.
- Intents par défaut : `GUILDS` uniquement. `MESSAGE_CONTENT`, `PRESENCES` et `GUILD_MEMBERS` sont désactivés. L’opt-in membre explicite expose `FULL_MEMBER_EVENTS`; le mode normal reste `ON_DEMAND_MEMBER_LOOKUP`.
- Dispatches normalisés : `GUILD_CREATE/UPDATE/DELETE`, `CHANNEL_CREATE/UPDATE/DELETE`, `GUILD_ROLE_CREATE/UPDATE/DELETE`, `GUILD_MEMBER_UPDATE` lorsque la capability est activée.
- `EventEnvelope` version 1 porte `event_id`, Guild, type, séquence/session Discord, timestamps occurred/received, correlation/causation, profondeur, source/origin et payload normalisé borné à 1 MiB.
- `discord_gateway_inbox` déduplique par événement et par `(guild_id, session, sequence, type)`. Projection, audit et outbox partagent une transaction. L’ordre est gardé par session ; une nouvelle session peut repartir à une petite séquence sans bloquer le cache.
- `READY`, `RESUMED`, gap, disconnect et session non reprise sont distingués. Un `GAP_DETECTED`/`NON_RESUMED` est un défaut de connaissance persistant : les dispatches ultérieurs et snapshots REST ciblés ne rétablissent pas `FRESH`. Seul un reconcile structure complet réussi remet la couverture `FULL/FRESH/CONNECTED`. Le tracker n’émet qu’un incident par transition vers le gap.
- Un événement reçu hors ordre reste dans l’inbox pour diagnostic, mais le projector retourne « non appliqué » : aucun faux audit métier, aucune outbox `discord.cache.changed` et aucun rafraîchissement artificiel de couverture ne sont produits pour channel/role update, delete ou obfuscation stale.
- L’identité application/bot du `READY` est liée une seule fois et comparée fail-closed aux installations Stage 02. Une Guild `ACTIVE` réobservée reste `ACTIVE`; une vraie réinstallation `UNINSTALLED` revient à `PENDING_SETUP`.

## Cache durable et états

Tables RLS tenant-scopées :

- `discord_roles_cache`, `discord_channels_cache`, `channel_overwrites_cache`;
- `discord_channel_tombstones`, `discord_cache_coverage`, `discord_reconcile_checkpoints`;
- `discord_gateway_inbox`, `discord_outbox`, `discord_io_jobs`;
- `discord_member_authorization_cache`, `internal_audit_events`.

États de connaissance : `VISIBLE`, `OBFUSCATED`, `ACCESS_LOST`, `UNKNOWN`, `DELETED_CONFIRMED`, `USER_CONFIRMED_DELETED`; après purge, tombstone `PURGED_TOMBSTONE`. Fraîcheur : `FRESH`, `AGING`, `STALE`, `UNKNOWN`. Couverture : `FULL`, `PARTIAL`, `DEGRADED`.

Une omission de `Get Guild Channels`, un `403`, une perte de visibilité ou un payload obfusqué ne constitue jamais une suppression. Le dernier nom/topic/payload complet et les derniers overwrites fiables ne sont pas remplacés par les champs obfusqués. Seul `CHANNEL_DELETE` confirme directement une suppression.

La purge est locale DID, autorisée par `cache.purge`, précédée d’un preview et sans adapter Discord. `confirm_local_only` ne prétend pas que Discord a supprimé la ressource. Pour `OBFUSCATED`/`ACCESS_LOST`, une seconde confirmation `confirm_resource_deleted` est obligatoire et produit la transition/audit `USER_CONFIRMED_DELETED`; le tombstone porte alors l’acteur. Un vrai `CHANNEL_DELETE` conserve `DELETED_CONFIRMED` et aucun faux confirmateur utilisateur. Une réobservation Gateway **ou REST/reconcile** supprime le tombstone, reconstruit le cache et audite `PURGED_RESOURCE_REOBSERVED`; la variante REST porte `origin=RECONCILE` et `source=TARGETED_REST`.

## Channel Obfuscation

Contrat officiellement revalidé le 2026-08-17 dans le [Change Log — « Channel Obfuscation for Users and Bots », 12 août 2026](https://docs.discord.com/developers/change-log), [Channel Resource — « Obfuscated Channels »](https://docs.discord.com/developers/resources/channel) et [Gateway Events — « Gateway Capabilities »](https://docs.discord.com/developers/events/gateway-events) :

- flag Channel `CHANNEL_OBFUSCATED = 1 << 17`;
- capability Gateway de test `CHANNEL_OBFUSCATION = 1 << 15`;
- `name=___hidden___`, champs sensibles nuls/réduits, overwrite unique `@everyone` refusant `VIEW_CHANNEL`;
- `id/type/position/parent_id` restent fiables et un `CHANNEL_UPDATE` complet revient avec la visibilité;
- à compter du 2026-11-16, HTTP omet les salons inaccessibles; aucun opt-in HTTP anticipé.

Discord n’expose pas de commit/révision stable pour ces pages. Le JSON du 2026-08-12 testé dans le dépôt est une **fixture contractuelle dérivée de la documentation officielle**, pas une fixture officielle publiée. `discord.py 2.7.1` n’expose pas la capability de test dans son IDENTIFY : le modèle est prêt, mais la perte de visibilité live reste `CONTRACT_ONLY_NOT_LIVE_VERIFIED`. Aucun support live du flag n’est revendiqué avant capability disponible/rollout.

## Redis, API et WebSocket

- PostgreSQL est la seule vérité durable. Redis contient la projection hot, des wakeups perdables, les locks/results single-flight et Pub/Sub.
- Clés tenant : `did:guild:{guild_id}:cache:channels:<schema>`, `...:singleflight:{sha256}:lock` et `...:result:<generation>`, `...:events:<schema>`. Le lock porte un token de génération : les appels réellement concurrents partagent son résultat, mais un appel séquentiel terminé devient propriétaire d’une nouvelle génération et ne relit jamais l’ancien succès/échec.
- Routage : le zset Redis global ne contient que des `guild_id`. Les fonctions PostgreSQL bornées `app.runtime_job_guilds`, `runtime_outbox_guilds` et `runtime_reconcile_guilds` rétablissent le travail perdu. Elles retournent uniquement des identifiants; chaque accès métier suivant reste dans un `TenantContext` RLS.
- Un flush Redis laisse PostgreSQL intact; `rebuild_channels` restaure la projection et incrémente la métrique bornée de rebuild.
- Lecture API : Redis puis PostgreSQL seulement. Cache hit = zéro REST Discord. Refresh explicite = job durable `202`, sans fan-out HTTP. Purge = zéro appel Discord.
- Le WebSocket authentifie et autorise `structure.read` côté backend avant accept puis avant chaque payload. Une session révoquée ferme en `4401`, un RBAC révoqué en `4403`, sans envoyer l’événement. Un bail configurable `websocket_authorization_max_staleness_seconds` (300 s par défaut, borne 1–900 s) force périodiquement une redécouverte Discord fail-closed sans REST par message.

## I/O Worker, governor et reconcile

- Le vrai entrypoint `python -m did.worker` construit DB `did_app`, Redis, client HTTP `discord.py`, adapter, cache, single-flight, outbox, `DurableDiscordIOWorker` et **un unique Governor long-lived**. Le dispatcher lease au plus un job par Guild et par tour, soumet chaque opération au Governor, draine une seule fois par batch, réalise le réseau hors transaction, puis ack/retry dans une transaction tenant séparée. Lease expiré = reprise après crash. Un 401 halte ce vrai Governor.
- `DiscordWorkloadGovernor` gouverne priorité, aging, round-robin Guild, concurrence globale/par Guild, coalescing, backpressure, pause background et budget invalid requests glissant 10 minutes. Il décide quand un workload part; `discord.py` reste propriétaire des buckets, headers et délais protocolaires Discord, sans limite de route hardcodée.
- Priorités : `APPLY_CONTINUATION` P0, `UNKNOWN_OUTCOME_RECOVERY` P1, `CRITICAL_PREFLIGHT` P2, `USER_REFRESH` P3, `BACKGROUND_RECONCILE` P4, `LOW_MAINTENANCE` P5.
- Valeurs par défaut : concurrence globale 4, par Guild 1, queue 1000. Une erreur 401 arrête le governor; 403/404 ne sont pas retryés aveuglément; 429 conserve `Retry-After` et le signal global.
- Single-flight Redis tenant-scopé et générationnel : un owner effectif par génération, fan-out succès/erreur, timeout borné et reprise après expiration/crash du lock.
- Sync initiale : deux appels REST bornés (channels+overwrites, roles), puis persistance, couverture `FULL` et checkpoint. Les effets Redis sont exclusivement portés par l’outbox après commit.
- Le vrai entrypoint `python -m did.scheduler` exécute une boucle `ReconcileScheduler`. `AdaptiveReconcilePolicy` cible environ 6 h actif / 24 h inactif, jitter stable, priorité accrue sur gap/non-resume/drift/coverage/travail critique et extension sous pression rate-limit. Il découvre des Guilds par IDs bornés et **enqueue seulement** `RECONCILE_STRUCTURE`; aucun Discord REST ni cron massif synchrone.

## Audit, métriques et charge

- Audit DID durable distinct de l’audit natif Discord : source, Guild, acteur éventuel, correlation/causation, type, cible, résultat et timestamps. Les observations externes produisent des signaux drift exploitables ultérieurement sans anticiper Stage 04.
- L’outbox DB transactionnelle tourne dans le vrai worker : invalidation hot cache, wakeup de job, Pub/Sub puis ack. Échec Redis conserve `PENDING` avec backoff; crash publish-before-ack provoque une livraison dupliquée tolérée; le polling PostgreSQL reprend automatiquement et marque `PUBLISHED` seulement après tous les effets. Gateway, refresh/reconcile et purge suivent ce même chemin.
- Métriques sans labels `guild_id/channel_id/user_id` : queue depth/wait, priorité, concurrence, backpressure, coalescing, outcomes REST/429, budget invalid, gaps/duplicates, fraîcheur, rebuild, backlog outbox et âge reconcile. Event IDs de logs statiques et redaction Stage 01 restent obligatoires.
- Le benchmark in-memory A=500/B=21 est conservé. La preuve décisive est durable end-to-end : PostgreSQL `discord_io_jobs` → Redis routing/wakeup → durable worker → Governor long-lived → faux Discord → ack PostgreSQL. A=300, B=30; premier slot B=1; un A avant B; borne=2; backlog max=330; concurrence globale max=2; par Guild max=1; 330 jobs `SUCCEEDED`; starvation=false.

## Validation et preuves

| Commande/scénario | Résultat | Preuve |
|---|---|---|
| `python scripts/validate_stage.py 03` | PASS, 92 unit + 40 integration + 4 frontend | `artifacts/test-evidence/stage-03/20260816T224913851301Z-6a964642151a-local-docker/` et CI du nouveau HEAD |
| `python scripts/validate_stage.py 03 --profile load` | PASS, 4 load dont pipeline durable A=300/B=30 | `artifacts/test-evidence/stage-03/20260816T224954694458Z-6a964642151a-local-docker/load-fairness.json` et artifact CI `stage-03-load` |
| `python scripts/validate_stage.py 01` | PASS, régression complète | `artifacts/test-evidence/stage-01/20260816T224749379966Z-6a964642151a-local-docker/` |
| `python scripts/validate_stage.py 02` | PASS, régression complète | `artifacts/test-evidence/stage-02/20260816T224835595039Z-6a964642151a-local-docker/` |
| migrations `base/0001/0002/0003 -> 0004`, `0004 -> 0002 -> 0004` | PASS | JUnit/résumé Stage 03 final |
| vrais entrypoints worker/scheduler, wakeup présent/perdu, 401 Governor | PASS | `test_stage03_process_runtime.py` |
| Redis down/reprise, génération single-flight, hot-cache Gateway→API | PASS | `test_stage03_redis_runtime.py` |
| gap persistant, stale no-effect, purge/tombstone/reobserve REST, RLS | PASS | `test_stage03_postgres.py` et tests security/failure |

Live A/B lu sans mutation : Guild 1 = 62 salons / 39 rôles; Guild 2 = 24 salons / 11 rôles. Aucun identifiant de Guild, token ou secret n’est stocké dans la preuve. Les profils Stage 02 administrateur non propriétaire et non-administrateur restent `SKIPPED_NOT_VERIFIED`.

## Limites et prérequis Stage 04

- Non vérifié live : modification Discord externe observée par Gateway, RESUME/non-resume forcé et visibilité obfusquée. Ces skips ne sont pas des PASS.
- La capability obfuscation temporaire n’est pas émise par `discord.py 2.7.1`; réévaluer la bibliothèque ou le rollout officiel avant une revendication live.
- Le worker et le scheduler sont fonctionnels directement par leurs entrypoints. Le déploiement peut configurer/scaler les processus, mais n’a pas à inventer leur routage. Les fonctions de découverte ID-only bornées ne contournent pas les lectures métier RLS.
- Stage 04 peut consommer uniquement les caches/fraîcheurs exposés. Il ne doit ni considérer `ACCESS_LOST` comme delete, ni utiliser Redis comme vérité, ni ajouter du REST direct dans l’API.
- Aucun Permission Engine, View As, Why Access, Desired State, Plan ou mutation métier de Stage 04+ n’a été commencé.
