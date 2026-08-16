# Handoff STAGE 03 — Runtime Discord, cache et réconciliation

| Champ | Valeur |
|---|---|
| Date | `2026-08-16` |
| Base main | `366e676880d0c3f4c7cf4f54105a117b2dcda3d8` |
| Branche | `stage/03-discord-runtime` |
| Commit code | `795f3904d72455ae2e79c1978cc30a42dbf36050` |
| Migration | `0002_stage_02 -> 0003_stage_03` |
| Statut | `COMPLETE_PR_PREPARATION` |

## Runtime Gateway et contrats

- `discord.py==2.7.1` est figé. Le process bot démarre `DiscordGatewayClient` quand `DISCORD_BOT_TOKEN` est configuré.
- Intents par défaut : `GUILDS` uniquement. `MESSAGE_CONTENT`, `PRESENCES` et `GUILD_MEMBERS` sont désactivés. L’opt-in membre explicite expose `FULL_MEMBER_EVENTS`; le mode normal reste `ON_DEMAND_MEMBER_LOOKUP`.
- Dispatches normalisés : `GUILD_CREATE/UPDATE/DELETE`, `CHANNEL_CREATE/UPDATE/DELETE`, `GUILD_ROLE_CREATE/UPDATE/DELETE`, `GUILD_MEMBER_UPDATE` lorsque la capability est activée.
- `EventEnvelope` version 1 porte `event_id`, Guild, type, séquence/session Discord, timestamps occurred/received, correlation/causation, profondeur, source/origin et payload normalisé borné à 1 MiB.
- `discord_gateway_inbox` déduplique par événement et par `(guild_id, session, sequence, type)`. Projection, audit et outbox partagent une transaction. L’ordre est gardé par session ; une nouvelle session peut repartir à une petite séquence sans bloquer le cache.
- `READY`, `RESUMED`, gap, disconnect et session non reprise sont distingués. Un gap/non-resume marque couverture et cache stale, sans effacement.
- L’identité application/bot du `READY` est liée une seule fois et comparée fail-closed aux installations Stage 02. Une Guild `ACTIVE` réobservée reste `ACTIVE`; une vraie réinstallation `UNINSTALLED` revient à `PENDING_SETUP`.

## Cache durable et états

Tables RLS tenant-scopées :

- `discord_roles_cache`, `discord_channels_cache`, `channel_overwrites_cache`;
- `discord_channel_tombstones`, `discord_cache_coverage`, `discord_reconcile_checkpoints`;
- `discord_gateway_inbox`, `discord_outbox`, `discord_io_jobs`;
- `discord_member_authorization_cache`, `internal_audit_events`.

États de connaissance : `VISIBLE`, `OBFUSCATED`, `ACCESS_LOST`, `UNKNOWN`, `DELETED_CONFIRMED`, `USER_CONFIRMED_DELETED`; après purge, tombstone `PURGED_TOMBSTONE`. Fraîcheur : `FRESH`, `AGING`, `STALE`, `UNKNOWN`. Couverture : `FULL`, `PARTIAL`, `DEGRADED`.

Une omission de `Get Guild Channels`, un `403`, une perte de visibilité ou un payload obfusqué ne constitue jamais une suppression. Le dernier nom/topic/payload complet et les derniers overwrites fiables ne sont pas remplacés par les champs obfusqués. Seul `CHANNEL_DELETE` confirme directement une suppression.

La purge est locale DID, autorisée par `cache.purge`, précédée d’un preview et sans adapter Discord. Elle retire le détail actif et conserve le tombstone minimal hashé. Une réobservation supprime le tombstone, reconstruit le cache et audite `PURGED_RESOURCE_REOBSERVED`.

## Channel Obfuscation

Contrat officiellement confirmé le 2026-08-16 dans le [changelog Discord](https://docs.discord.com/developers/change-log), [Channel Resource](https://docs.discord.com/developers/resources/channel) et [Gateway Events](https://docs.discord.com/developers/events/gateway-events) :

- flag Channel `CHANNEL_OBFUSCATED = 1 << 17`;
- capability Gateway de test `CHANNEL_OBFUSCATION = 1 << 15`;
- `name=___hidden___`, champs sensibles nuls/réduits, overwrite unique `@everyone` refusant `VIEW_CHANNEL`;
- `id/type/position/parent_id` restent fiables et un `CHANNEL_UPDATE` complet revient avec la visibilité;
- à compter du 2026-11-16, HTTP omet les salons inaccessibles; aucun opt-in HTTP anticipé.

La fixture officielle du 2026-08-12 est testée. `discord.py 2.7.1` n’expose pas la capability de test dans son IDENTIFY : le modèle est prêt, mais la perte de visibilité live reste `CONTRACT_ONLY_NOT_LIVE_VERIFIED`. Aucun support live du flag n’est revendiqué avant capability disponible/rollout.

## Redis, API et WebSocket

- PostgreSQL est la seule vérité durable. Redis contient la projection hot, leases/results single-flight et Pub/Sub.
- Clés : `did:guild:{guild_id}:cache:channels:<schema>`, `...:singleflight:{sha256}:lock|result`, `...:events:<schema>`, avec suffixe de schéma numérique égal à un. Toute clé inclut le namespace Guild.
- Un flush Redis laisse PostgreSQL intact; `rebuild_channels` restaure la projection et incrémente la métrique bornée de rebuild.
- Lecture API : Redis puis PostgreSQL seulement. Cache hit = zéro REST Discord. Refresh explicite = job durable `202`, sans fan-out HTTP. Purge = zéro appel Discord.
- Le WebSocket authentifie et autorise `structure.read` côté backend. Le handler surveille concurremment déconnexion et Pub/Sub. Tests A/B stricts couvrent canal, payload forgé et absence de fuite croisée.

## I/O Worker, governor et reconcile

- `DurableDiscordIOWorker` lease un job par Guild, commit le lease, réalise le réseau hors transaction, puis ack/retry dans une nouvelle transaction. Lease expiré = reprise après crash. `403/404/401` sont terminaux; seuls 429/transient sont retryables selon erreur normalisée.
- `DiscordWorkloadGovernor` gouverne priorité, aging, round-robin Guild, concurrence globale/par Guild, coalescing, backpressure, pause background et budget invalid requests glissant 10 minutes. `discord.py` reste propriétaire des buckets, headers et délais protocolaires Discord; aucune limite de route n’est hardcodée.
- Priorités : `APPLY_CONTINUATION` P0, `UNKNOWN_OUTCOME_RECOVERY` P1, `CRITICAL_PREFLIGHT` P2, `USER_REFRESH` P3, `BACKGROUND_RECONCILE` P4, `LOW_MAINTENANCE` P5.
- Valeurs par défaut : concurrence globale 4, par Guild 1, queue 1000. Une erreur 401 arrête le governor; 403/404 ne sont pas retryés aveuglément; 429 conserve `Retry-After` et le signal global.
- Single-flight Redis tenant-scopé : un owner effectif, fan-out succès/erreur, timeout borné et reprise après expiration du lock.
- Sync initiale : deux workloads bornés (channels+overwrites, roles), interruptibles, puis persistance, couverture `FULL`, checkpoint et rebuild Redis.
- `AdaptiveReconcilePolicy` cible environ 6 h actif / 24 h inactif, jitter stable, priorité accrue sur gap/non-resume/drift/coverage/travail critique et extension sous pression rate-limit. Le scheduler enqueue seulement; aucun cron global synchronisé.

## Audit, métriques et charge

- Audit DID durable distinct de l’audit natif Discord : source, Guild, acteur éventuel, correlation/causation, type, cible, résultat et timestamps. Les observations externes produisent des signaux drift exploitables ultérieurement sans anticiper Stage 04.
- Outbox DB transactionnelle : échec Redis conserve `PENDING`; crash publish-before-ack provoque une livraison dupliquée tolérée; reprise marque `PUBLISHED` seulement après publication.
- Métriques sans labels `guild_id/channel_id/user_id` : queue depth/wait, priorité, concurrence, backpressure, coalescing, outcomes REST/429, budget invalid, gaps/duplicates, fraîcheur, rebuild, backlog outbox et âge reconcile. Event IDs de logs statiques et redaction Stage 01 restent obligatoires.
- Benchmark déterministe : A=500 jobs, B=21; premier slot B=1; un dispatch A avant B; borne=2 slots; backlog maximal=521; concurrence globale observée=2; par Guild=1; coalescing=2; B progresse dans la borne.

## Validation et preuves

| Commande/scénario | Résultat | Preuve |
|---|---|---|
| `python scripts/validate_stage.py 03 --include-discord-live` | PASS, 92 unit + 30 integration + 4 frontend; live `PASS_WITH_APPROVED_LIMITATION` | `artifacts/test-evidence/stage-03/20260816T213935777741Z-31914869fbf5-local-docker/` et `STAGE_03_LIVE_EVIDENCE.json` |
| `python scripts/validate_stage.py 03 --profile load` | PASS, 3 load | `artifacts/test-evidence/stage-03/20260816T214016834401Z-31914869fbf5-local-docker/` |
| `python scripts/validate_stage.py 01` | PASS, régression | `artifacts/test-evidence/stage-01/20260816T214024110883Z-31914869fbf5-local-docker/` |
| `python scripts/validate_stage.py 02` | PASS, régression | `artifacts/test-evidence/stage-02/20260816T214056090951Z-31914869fbf5-local-docker/` |
| migrations `base/0001/0002 -> head`, `head -> 0002 -> head` | PASS | JUnit/résumé Stage 03 |
| Redis loss, single-flight owner crash, outbox down/publish-before-ack, worker lease crash | PASS | tests integration/failure |
| RLS, Redis, queue, Pub/Sub et WebSocket A/B | PASS | tests security Stage 03 |

Live A/B lu sans mutation : Guild 1 = 62 salons / 39 rôles; Guild 2 = 24 salons / 11 rôles. Aucun identifiant de Guild, token ou secret n’est stocké dans la preuve. Les profils Stage 02 administrateur non propriétaire et non-administrateur restent `SKIPPED_NOT_VERIFIED`.

## Limites et prérequis Stage 04

- Non vérifié live : modification Discord externe observée par Gateway, RESUME/non-resume forcé et visibilité obfusquée. Ces skips ne sont pas des PASS.
- La capability obfuscation temporaire n’est pas émise par `discord.py 2.7.1`; réévaluer la bibliothèque ou le rollout officiel avant une revendication live.
- Le worker durable est un composant par-Guild testable; son déploiement doit fournir les wakeups/partitions de Guild sans introduire de lecture cross-tenant. Aucun bypass RLS global n’a été ajouté.
- Stage 04 peut consommer uniquement les caches/fraîcheurs exposés. Il ne doit ni considérer `ACCESS_LOST` comme delete, ni utiliser Redis comme vérité, ni ajouter du REST direct dans l’API.
- Aucun Permission Engine, View As, Why Access, Desired State, Plan ou mutation métier de Stage 04+ n’a été commencé.
