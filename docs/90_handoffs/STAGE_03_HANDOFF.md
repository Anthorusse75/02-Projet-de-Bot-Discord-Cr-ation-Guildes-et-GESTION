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
| Migration | `0002_stage_02 -> 0003_stage_03 -> 0004_stage_03 -> 0005_stage_03` |
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

- Le vrai entrypoint `python -m did.worker` construit DB `did_app`, Redis, client HTTP `discord.py`, adapter, cache, single-flight, outbox, `DurableDiscordIOWorker`, Governor local long-lived et coordinateur Redis distribué. Le dispatcher n’admet que les slots immédiatement démarrables : au plus la concurrence globale locale et la borne par Guild, puis drain par vagues. `dispatch_batch_size=512` ne signifie donc jamais 512 leases préchargés.
- Chaque lease job, pris juste avant son admission dans une vague, porte `lease_owner`, `lease_token`, `lease_generation` et `leased_until`. Un heartbeat démarre avant l’attente d’un permit Redis et renouvelle pendant tout l’I/O. Renewal/ack/retry sont atomiquement fenced par owner+token ; ack/retry exigent aussi un lease non expiré. Après crash, expiration permet la reprise et l’ancien token ne peut plus acquitter.
- Plusieurs workers actifs partagent des permits Redis globaux et par Guild avec TTL/token/renew/release compare-by-token. Ils partagent aussi budget invalid requests sur 10 minutes, pression 429 et halt 401. Les métriques distinguent les pics de concurrence locale et système. `discord.py` reste propriétaire des buckets, headers et délais protocolaires Discord ; DID ne réimplémente pas son limiteur protocolaire.
- Priorités : `APPLY_CONTINUATION` P0, `UNKNOWN_OUTCOME_RECOVERY` P1, `CRITICAL_PREFLIGHT` P2, `USER_REFRESH` P3, `BACKGROUND_RECONCILE` P4, `LOW_MAINTENANCE` P5.
- Valeurs par défaut : concurrence système globale 4, par Guild 1, queue locale 1000, lease job et permit 30 s renouvelables. Une erreur 401 arrête tous les workers via Redis; 403/404 ne sont pas retryés aveuglément; 429 conserve `Retry-After` et publie une pression partagée.
- Single-flight Redis tenant-scopé et générationnel : un Lua atomique `ACQUIRE OR OBSERVE CURRENT GENERATION` lie tout waiter concurrent à la génération observée, y compris si l’owner publie/libère avant le retour du waiter. Succès/erreur sont fan-out, timeout et crash sont bornés, et un appel séquentiel crée une nouvelle génération.
- Sync initiale : deux appels REST bornés (channels+overwrites, roles), puis persistance, couverture `FULL` et checkpoint. Les effets Redis sont exclusivement portés par l’outbox après commit.
- La pression workload est publiée par reporter pendant le drain, agrégée par maximum avec TTL, et ne peut plus être écrasée à zéro par un autre worker. Le scheduler diffère un reconcile de fond sous pression >= 0,5, mais conserve les urgences `GAP_DETECTED`/`NON_RESUMED`.
- Le vrai entrypoint `python -m did.scheduler` exécute une boucle `ReconcileScheduler`. `AdaptiveReconcilePolicy` cible environ 6 h actif / 24 h inactif, jitter stable, priorité accrue sur gap/non-resume/drift/coverage/travail critique et extension sous pression. Il découvre des Guilds par IDs bornés et **enqueue seulement** `RECONCILE_STRUCTURE`; aucun Discord REST ni cron massif synchrone.

## Audit, métriques et charge

- Audit DID durable distinct de l’audit natif Discord : source, Guild, acteur éventuel, correlation/causation, type, cible, résultat et timestamps. Les observations externes produisent des signaux drift exploitables ultérieurement sans anticiper Stage 04.
- L’outbox DB transactionnelle tourne dans le vrai worker avec lease owner/token/expiration et candidats `FOR UPDATE SKIP LOCKED`. Les lignes sont leasées just-in-time une par une et renouvelées pendant leurs effets : deux publishers vivants ne produisent pas de tempête sur le même event. Échec Redis conserve `PENDING` avec backoff; crash réel publish-before-ack autorise une rediffusion bornée après expiration, conformément au contrat at-least-once.
- Métriques sans labels `guild_id/channel_id/user_id` : queue depth/wait, priorité, concurrence locale/système, backpressure, coalescing, outcomes REST/429 et attente rate-limit, cache hit ratio, budget invalid partagé, gaps/duplicates, fraîcheur, rebuild, backlog outbox et âge reconcile.
- Le benchmark in-memory A=500/B=21 est conservé. La preuve durable A=300/B=30 passe désormais par vagues de deux leases maximum (un par Guild), avec 330 jobs `SUCCEEDED`, premier slot B=1 et starvation=false. Une preuve additionnelle lance deux runtimes, lease/permit 150 ms, faux Discord 180 ms, queue 10/batch 512 : concurrence système max 2, par Guild 1, chaque workload read-only appelé exactement une fois, recovery du lease/permit crashé, zéro `LEASED` final et processus vivants.

## Validation et preuves

La traçabilité RATE est auditée exigence par exigence : `REQ-RATE-001` `IMPLEMENTED` (limites de route dynamiques déléguées à discord.py), `002` `IMPLEMENTED` (gouvernance commune Redis), `003` `IMPLEMENTED` (`Retry-After`), `004` `IMPLEMENTED` (budget/401/429 partagé), `005` **`PLANNED`** (Plan Compiler Stage 05 absent), `006` `IMPLEMENTED` (429, attente, queue, cache hit ratio et invalid requests). L’audit sémantique laisse aussi `REQ-GW-006`, `REQ-CACHE-004`, `REQ-CACHE-007`, `REQ-AUD-002`, `REQ-AUD-003` et `REQ-TEN-008` à `PLANNED`; aucune famille Stage 03 n’est plus promue par range aveugle.

| Commande/scénario | Résultat | Preuve |
|---|---|---|
| `python scripts/validate_stage.py 03` | PASS, 93 unit + 43 integration + 4 frontend | `artifacts/test-evidence/stage-03/20260817T071529972512Z-b98ca5d281aa-local-docker/` ; CI du commit correctif à renseigner après push |
| `python scripts/validate_stage.py 03 --profile load` | PASS, 5 load dont pipeline durable A=300/B=30 et deux workers lease court | `artifacts/test-evidence/stage-03/20260817T071612528383Z-b98ca5d281aa-local-docker/` puis `stage-03-load` CI |
| `python scripts/validate_stage.py 01` | PASS, régression complète | `artifacts/test-evidence/stage-01/20260817T071409786205Z-b98ca5d281aa-local-docker/` |
| `python scripts/validate_stage.py 02` | PASS, régression complète | `artifacts/test-evidence/stage-02/20260817T071453459051Z-b98ca5d281aa-local-docker/` |
| migrations `base/0001/0002/0003/0004 -> 0005`, `0005 -> 0002 -> 0005` | PASS | résumé Stage 03 `20260817T071529972512Z` |
| PR #3 checks `stage-01`, `stage-02`, `stage-03`, `stage-03-load` | PASS sur le HEAD publié, PR toujours Draft | GitHub Actions, deux runs complets déclenchés par la publication |
| vrais entrypoints worker/scheduler, wakeup présent/perdu, 401 Governor | PASS | `test_stage03_process_runtime.py` |
| Redis down/reprise, single-flight Lua forced race, coordination failure/outbox multi-worker, hot-cache Gateway→API | PASS | `test_stage03_redis_runtime.py` |
| gap persistant, stale no-effect, purge/tombstone/reobserve REST, RLS | PASS | `test_stage03_postgres.py` et tests security/failure |
| `pytest -m "security and not load"` / `failure_injection and not load` | PASS, 39 / 6 | exécution locale corrective |

Live A/B lu sans mutation : Guild 1 = 62 salons / 39 rôles; Guild 2 = 24 salons / 11 rôles. Aucun identifiant de Guild, token ou secret n’est stocké dans la preuve. Les profils Stage 02 administrateur non propriétaire et non-administrateur restent `SKIPPED_NOT_VERIFIED`.

## Limites et prérequis Stage 04

- Non vérifié live : modification Discord externe observée par Gateway, RESUME/non-resume forcé et visibilité obfusquée. Ces skips ne sont pas des PASS.
- La capability obfuscation temporaire n’est pas émise par `discord.py 2.7.1`; réévaluer la bibliothèque ou le rollout officiel avant une revendication live.
- Le worker et le scheduler sont fonctionnels directement par leurs entrypoints. Le déploiement peut configurer/scaler les processus, mais n’a pas à inventer leur routage. Les fonctions de découverte ID-only bornées ne contournent pas les lectures métier RLS.
- Stage 04 peut consommer uniquement les caches/fraîcheurs exposés. Il ne doit ni considérer `ACCESS_LOST` comme delete, ni utiliser Redis comme vérité, ni ajouter du REST direct dans l’API.
- Aucun Permission Engine, View As, Why Access, Desired State, Plan ou mutation métier de Stage 04+ n’a été commencé.
