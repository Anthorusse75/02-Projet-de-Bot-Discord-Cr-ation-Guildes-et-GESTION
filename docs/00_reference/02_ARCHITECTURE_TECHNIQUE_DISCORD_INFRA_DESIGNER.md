# Discord Infrastructure Designer
## Architecture technique détaillée

**Document :** 02 — Architecture technique  
**Statut :** Architecture cible initiale  
**Cible :** Codex / VS Code / développement local Windows 11  
**Frontend :** React + TypeScript  
**Backend / Bot :** Python  
**Architecture :** monolithe modulaire distribué en plusieurs processus + PostgreSQL + Redis  
**Date de référence :** 2026-08-16

---

# 1. Objectifs d'architecture

L'architecture doit satisfaire simultanément :

1. installation d'une application Discord unique sur de nombreux serveurs ;
2. isolation stricte des serveurs les uns des autres ;
3. dashboard Web réactif ;
4. moteur de permissions fiable ;
5. mutations Discord planifiées et auditables ;
6. capacité de monter en charge sans réécriture complète ;
7. environnement de développement simple sous Windows 11 ;
8. backend Python ;
9. frontend React ;
10. architecture suffisamment explicite pour être développée progressivement avec Codex ;
11. copie/clonage contrôlés entre Guilds indépendantes lorsqu'un même utilisateur est autorisé sur la source et la destination ;
12. Drag & Drop inter-Guild avec menu de drop contextuel au bouton droit ;
13. désactivation globale du menu contextuel natif du navigateur au profit du moteur de contexte applicatif ;
14. topologie multilingue tenant-scopée, avec Translation Groups indépendants, visibilité `Scope × Language` et Translation Providers interchangeables ;
15. internationalisation complète du dashboard, avec packs UI activables à chaud et zéro chaîne système non localisée ;
16. moteur de campagnes/message multi-Guild, planifié/événementiel et multilingue avec traduction Discord-safe.

Le choix initial est volontairement un **monolithe modulaire**, mais déployé en processus séparés :

- API Web ;
- Bot / Gateway Discord ;
- Worker de jobs ;
- Scheduler durable ;
- Frontend.

On évite une constellation prématurée de microservices.

---

# 2. Vue d'ensemble

```text
                           ┌──────────────────────────────┐
                           │           DISCORD            │
                           │ Gateway WS        REST API   │
                           └───────┬──────────────┬───────┘
                                   │              │
                          bot token│              │bot token
                                   │              │
                    ┌──────────────▼──────┐  ┌────▼─────────────────────┐
                    │     BOT PROCESS     │  │ DISCORD I/O WORKER      │
                    │ discord.py Gateway │  │ Apply / refresh/reconcile│
                    │ event ingestion    │  │ REST rate-limit owner    │
                    │ interactions*      │  │ Plan operation executor  │
                    └──────────┬──────────┘  └──────────┬───────────────┘
                               │                         │
                               └────────────┬────────────┘
                                            │
                         ┌──────────────────▼──────────────────┐
                         │               REDIS                 │
                         │ jobs / locks / streams / hot cache  │
                         │ pubsub / single-flight / backpressure│
                         └──────────────┬──────────────────────┘
                                        │
                           ┌────────────▼────────────┐
                           │      API PROCESS        │
                           │ FastAPI / OAuth / REST  │
                           │ WebSocket DID           │
                           │ reads local cache       │
                           └────────────┬────────────┘
                                        │
                              ┌─────────▼─────────┐
                              │   PostgreSQL      │
                              │ durable cache     │
                              │ plans/snapshots   │
                              │ audit/RBAC        │
                              └─────────┬─────────┘
                                        │
                              ┌─────────▼─────────┐
                              │ React + TypeScript│
                              │ Dashboard         │
                              └───────────────────┘
```

`*` Le bot process évite les appels REST bot-token génériques. Les réponses d'interactions utilisent uniquement les mécanismes nécessaires au traitement des interactions.

---

# 3. Décisions technologiques

## 3.1 Python

Cible recommandée : **Python 3.13** pour le dépôt initial.

Raison :

- maturité suffisante ;
- bon support async ;
- éviter de prendre une version Python toute récente tant que l'écosystème n'est pas validé.

La version doit être fixée dans le projet et CI.

## 3.2 Discord

Bibliothèque recommandée : **discord.py 2.x**, version exacte épinglée.

Ne pas coder directement un client Gateway maison ; utiliser la bibliothèque retenue derrière une interface interne.

Le code Discord doit toutefois dépendre d'une **interface interne**, afin de pouvoir isoler la bibliothèque.

## 3.3 API

**FastAPI**.

Utilisations :

- OAuth callback ;
- REST ;
- WebSocket/SSE ;
- OpenAPI ;
- validation Pydantic.

## 3.4 Frontend

- React 19.x ;
- TypeScript strict ;
- Vite ;
- React Router ;
- TanStack Query ;
- Zustand ou équivalent léger pour état purement UI ;
- dnd-kit pour drag & drop ;
- Radix UI / shadcn/ui ou primitives accessibles similaires ;
- Tailwind CSS si retenu pour accélérer l'UI ;
- `i18next` + `react-i18next` pour l'internationalisation ;
- chargement HTTP/runtime des locale packs depuis DID ;
- `Intl` navigateur pour dates/nombres/pluriels/relatifs ;
- stratégie emoji explicite + composant de drapeau normalisé.

Aucune chaîne système visible ne doit être codée directement dans JSX/TSX. Les actions, toasts, tooltips, erreurs et menus référencent des clés i18n typées.

Pile de fontes recommandée : texte Unicode complet + fallbacks emoji (`Segoe UI Emoji`, `Noto Color Emoji`, `Apple Color Emoji`). Les drapeaux des sélecteurs de locale utilisent en plus un composant d'icône normalisé afin de ne pas dépendre du support variable des séquences de drapeau par l'OS.

React 19.2 est la version documentée comme courante à la date de référence.

## 3.5 Base de données

PostgreSQL.

Utiliser :

- SQLAlchemy 2 ;
- asyncpg ;
- Alembic.

## 3.6 Redis

Usages :

- locks distribués ;
- queue / streams ;
- cache ;
- diffusion d'événements live ;
- anti-thundering herd.

Redis ne doit pas être source de vérité durable.

## 3.7 Jobs

Deux options acceptables :

### Option retenue

Worker Python dédié avec **Redis Streams** + abstraction interne de jobs.

Avantages :

- async naturel ;
- contrôle total ;
- moins de magie ;
- bonne adéquation avec les plans Discord.

Éviter de coupler la logique métier directement à Celery ; conserver l'abstraction `JobQueue`.

Une migration vers Celery/Dramatiq/autre reste possible derrière l'interface `JobQueue`.

## 3.7A Traduction de campagnes

Implémentation demandée pour la traduction directe DID : **`googletrans`**, épinglé à une version validée dans le lockfile. À la date de référence du document, la version PyPI observée est `4.0.2`.

`googletrans` est encapsulé derrière un port interne `CampaignTranslationEngine` afin que :

- le domaine ne dépende pas directement de la librairie ;
- les protections Discord soient appliquées avant tout appel ;
- les erreurs réseau/5xx soient typées ;
- le batching soit contrôlé ;
- les retries soient bornés ;
- un changement ultérieur de moteur ne réécrive pas le Campaign Engine.

La librairie n'est jamais autorisée à recevoir un `DiscordMessageModel` brut. `DiscordSafeMessageParser` construit d'abord une représentation protégée, puis `TranslationContextBuilder` produit des **unités masquées conservant le maximum de contexte linguistique**. Les tokens techniques sont remplacés par des placeholders validés ; le texte autour reste groupé en message/paragraphe/bloc cohérent autant que possible. Le découpage en petits fragments n'est pas la stratégie par défaut.

## 3.8 Conteneurs

Docker Compose recommandé pour :

- PostgreSQL ;
- Redis ;
- éventuellement backend/bot.

Sous Windows 11 :

- développement possible avec Python/Node natifs ;
- services d'infrastructure via Docker Desktop / WSL2.

La production cible doit privilégier des conteneurs Linux.

---

# 4. Organisation du dépôt

Monorepo :

```text
discord-infra-designer/
│
├── README.md
├── .env.example
├── .gitignore
├── docker-compose.yml
├── pyproject.toml
├── package.json                 # optionnel workspace root
│
├── docs/
│   ├── 01_SPECIFICATIONS_FONCTIONNELLES_DISCORD_INFRA_DESIGNER.md
│   └── 02_ARCHITECTURE_TECHNIQUE_DISCORD_INFRA_DESIGNER.md
│
├── backend/
│   ├── pyproject.toml           # si découpage Python autonome
│   ├── src/
│   │   └── did/
│   │       ├── api/
│   │       ├── bot/
│   │       ├── worker/              # Discord I/O Worker + jobs domaine
│   │       ├── discord_io/          # governor, REST adapter orchestration, cache refresh
│   │       ├── domain/
│   │       ├── application/
│   │       ├── infrastructure/
│   │       ├── security/
│   │       ├── tenancy/
│   │       ├── permissions/
│   │       ├── planning/
│   │       ├── translation/
│   │       ├── audit/
│   │       └── settings/
│   ├── tests/
│   └── alembic/
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── src/
│       ├── app/
│       ├── pages/
│       ├── features/
│       ├── entities/
│       ├── shared/
│       └── api/
│
└── scripts/
    ├── dev.sh
    ├── lint.sh
    ├── test.sh
    └── seed_dev.py
```

---

# 5. Architecture backend en couches

```text
┌──────────────────────────────────────────────┐
│ API / Bot handlers / Worker handlers        │
├──────────────────────────────────────────────┤
│ Application services / Use cases            │
├──────────────────────────────────────────────┤
│ Domain models / Policies / Permission engine│
├──────────────────────────────────────────────┤
│ Ports / interfaces                          │
├──────────────────────────────────────────────┤
│ Infrastructure                              │
│ Discord / PostgreSQL / Redis / Crypto       │
└──────────────────────────────────────────────┘
```

## 5.1 Domain

Aucune dépendance directe à :

- FastAPI ;
- discord.py ;
- SQLAlchemy ;
- Redis.

Contient :

- Tenant/Guild identifiers ;
- policies ;
- permission calculations ;
- plans ;
- operations ;
- risk levels ;
- diff models ;
- authorization concepts ;
- Language Profiles ;
- Translation Groups / Channel Groups ;
- Visibility Scopes ;
- Scope × Language bindings ;
- translation routing policies ;
- Translation Provider capabilities.

## 5.2 Application

Use cases :

```text
InitializeGuild
RefreshGuildStructure
CreatePlan
ValidatePlan
ApplyPlan
DuplicateCategory
CreateLogicalGroup
SimulateMemberAccess
ExplainPermission
ReconcileGuild
GrantDashboardAccess
CreateTranslationGroup
AddTranslationLanguage
LinkTranslationVariant
UnlinkTranslationVariant
CreateMultilingualClonePlan
ReconcileTranslationTopology
SetMemberLanguagePreferences
PrepareTranslationProviderConfiguration
```

## 5.3 Infrastructure

Adapters :

```text
DiscordGatewayAdapter
DiscordRestAdapter
PostgresGuildRepository
PostgresPlanRepository
RedisLockManager
RedisEventBus
DiscordOAuthClient
TranslationProviderAdapter
TranslationProviderRegistry
```

---

# 6. Multi-tenancy

## 6.1 Tenant

```python
TenantId = DiscordGuildId
```

Pas de tenant numérique interne remplaçant le `guild_id` dans la logique métier.

Un UUID interne peut exister, mais le `guild_id` reste une clé métier unique.

## 6.2 Colonnes obligatoires

Toute table tenant-scopée inclut :

```text
guild_id BIGINT / NUMERIC compatible Snowflake
```

Préférer un type SQL capable de contenir un Snowflake Discord sans ambiguïté.

Dans Python : `int`.

Dans API JSON : souvent string pour éviter les problèmes de précision JavaScript.

## 6.3 Clés uniques

Exemple :

```text
UNIQUE(guild_id, discord_channel_id)
UNIQUE(guild_id, discord_role_id)
```

Même si les IDs Discord sont globalement uniques, garder le `guild_id` dans les contraintes tenant importantes facilite l'intégrité et les requêtes sûres.

## 6.4 Repository tenant-aware

Interdit :

```python
channel_repo.get(channel_id)
```

Préféré :

```python
channel_repo.get(guild_id, channel_id)
```

## 6.5 PostgreSQL Row Level Security

Recommandé en défense en profondeur.

Principe :

- l'application positionne le tenant courant dans la transaction ;
- les policies RLS filtrent `guild_id`.

Ne pas considérer RLS comme remplacement des contrôles applicatifs.

### 6.5.1 User Control Plane

Toutes les données ne sont pas tenant-scopées.

Deux security domains :

```text
TENANT DATA PLANE
  key = guild_id
  ex. channels, roles, plans, translation groups

USER CONTROL PLANE
  key = discord_user_id
  ex. clipboard personnel, bibliothèque personnelle
```

Le User Control Plane doit utiliser ses propres policies d'autorisation/RLS basées sur `owner_discord_user_id`.

`source_guild_id` dans un artifact personnel est une provenance et ne doit jamais être utilisé comme bypass d'autorisation.

## 6.6 Redis

Toutes les clés tenant-scopées :

```text
did:guild:{guild_id}:...
```

## 6.7 Logs

Toujours inclure lorsque pertinent :

```text
guild_id
user_id
request_id
plan_id
operation_id
```

Sans publier de secrets.

---

# 7. Modèle de données principal

## 7.1 users

```text
users
-----
discord_user_id PK
username
global_name
avatar_hash
created_at
updated_at
```

## 7.1A discord_oauth_grants

Grant OAuth2 utilisateur appartenant au **User Control Plane**. Il n'est pas tenant-scopé.

```text
discord_oauth_grants
--------------------
discord_user_id BIGINT PK
scopes_json JSONB NOT NULL
access_token_ciphertext BYTEA NULL
access_token_expires_at TIMESTAMPTZ NULL
refresh_token_ciphertext BYTEA NULL      # présent pour grant actif; NULL après révocation/purge
key_version INTEGER NOT NULL
last_refreshed_at TIMESTAMPTZ NULL
revoked_at TIMESTAMPTZ NULL
created_at
updated_at
```

Règles :

- tokens chiffrés AEAD, clé hors DB ;
- aucune valeur de token dans logs/audit/frontend ;
- pour tout grant actif utilisé par une session durable, le refresh token est persisté côté serveur sous forme chiffrée ; cette persistance fait partie du modèle cible et n'est pas laissée au choix de l'implémentation ;
- `revoked_at` empêche tout refresh ultérieur ;
- scopes reçus vérifiés contre les scopes attendus.

## 7.2 guild_installations

```text
guild_installations
-------------------
guild_id PK
name
icon_hash
owner_id
installation_status
installed_at
activated_at
uninstalled_at
last_gateway_seen_at
last_reconciled_at
settings_json
version
```

## 7.3 guild_user_access

```text
guild_user_access
-----------------
guild_id
discord_user_id
platform_role
status
created_by
created_at
updated_at

PK(guild_id, discord_user_id)
```

## 7.4 guild_role_bindings

Pour l’accès par rôle Discord :

```text
guild_role_bindings
-------------------
guild_id
discord_role_id
dashboard_role
logical_group_id NULL
```

## 7.5 discord_roles_cache

```text
guild_id
role_id
name
position
permissions_bits
managed
color
hoist
mentionable
raw_json
discord_updated_at
cache_updated_at
```

## 7.6 discord_channels_cache

```text
guild_id
channel_id
type
name                         # dernière valeur complète connue
parent_id
position
topic                        # dernière valeur complète connue
nsfw
raw_json                     # dernier payload complet connu lorsque disponible
access_state                 # VISIBLE | OBFUSCATED | ACCESS_LOST | UNKNOWN | DELETED_CONFIRMED | USER_CONFIRMED_DELETED
is_obfuscated
last_full_observed_at
last_gateway_seen_at
last_rest_seen_at
last_mutation_confirmed_at
access_lost_at
obfuscated_at
deleted_confirmed_at
state_version
cache_updated_at
```

Important : après Channel Obfuscation, `name/topic/overwrites` peuvent n'être que des **dernières valeurs connues**. Les champs actuellement observables doivent être distinguables par `access_state` et timestamps.

## 7.7 channel_overwrites_cache

```text
guild_id
channel_id
target_id
target_type
allow_bits
deny_bits
last_full_observed_at
cache_updated_at
```

Ces lignes représentent le **dernier jeu complet connu**. Lorsqu'un channel devient obfusqué, le payload obfusqué n'écrase pas ce cache. Le Permission Engine doit vérifier `discord_channels_cache.access_state` avant de présenter ces overwrites comme état actuel.

## 7.7A discord_channel_tombstones

Une purge manuelle ne doit pas perdre toute trace d'identité ni permettre une résurrection locale ambiguë.

```text
discord_channel_tombstones
--------------------------
guild_id BIGINT NOT NULL
channel_id BIGINT NOT NULL
resource_type VARCHAR NOT NULL      # CATEGORY | CHANNEL | THREAD/... selon objet Discord
reason VARCHAR NOT NULL             # DISCORD_DELETE | USER_CONFIRMED_DELETED | CACHE_PURGE
confirmed_by_user_id BIGINT NULL
confirmed_at TIMESTAMPTZ NOT NULL
purged_at TIMESTAMPTZ NOT NULL
last_known_parent_id BIGINT NULL
last_known_type INTEGER NULL
last_known_position INTEGER NULL
metadata_hash VARCHAR NULL

PRIMARY KEY(guild_id, channel_id)
```

Le tombstone ne conserve pas le nom/topic/overwrites détaillés après purge, sauf si une politique d'audit/rétention distincte l'exige.

Une observation Discord non ambiguë du même `channel_id` :

1. invalide/supprime le tombstone ;
2. recrée/met à jour `discord_channels_cache` ;
3. produit `PURGED_RESOURCE_REOBSERVED` ;
4. réévalue la couverture et les plans dépendants.

## 7.8 logical_groups

```text
id UUID PK
guild_id
name
slug
description
created_at
updated_at
```

## 7.9 logical_group_resources

```text
logical_group_id
guild_id
resource_type
discord_resource_id
semantic_role
```

`resource_type` :

- CATEGORY
- CHANNEL
- ROLE

## 7.10 templates

```text
id UUID
guild_id NULL           # NULL = système
visibility
name
type
schema_version
definition_json
created_by
```

## 7.11 plans

```text
id UUID
guild_id
created_by
status
risk_level
base_snapshot_id
summary
created_at
validated_at
applied_at
version
```

## 7.12 plan_operations

```text
id UUID
plan_id
guild_id
sequence                         # ordre d'affichage/exécution possible, pas la seule dépendance
operation_type
execution_target                 # DISCORD | DID_LOCAL | PROVIDER
resource_type
resource_ref                     # référence symbolique ou référence à une ressource Discord existante
discord_resource_id NULL         # rempli lorsque la cible/production est résolue
desired_state_json
before_state_json
preconditions_json
compensation_json
risk_level
status
error_code
error_detail
started_at
finished_at
```

`resource_ref` permet à un plan de référencer une ressource future avant que Discord lui ait attribué un Snowflake.

## 7.12A plan_operation_dependencies

Le DAG de plan doit être persistant et ne pas dépendre seulement de `sequence`.

```text
plan_operation_dependencies
---------------------------
guild_id
operation_id
depends_on_operation_id

PK(guild_id, operation_id, depends_on_operation_id)
```

`sequence` reste une optimisation/présentation possible ; la dépendance logique est le DAG.

## 7.12B plan_symbol_bindings

Résolution des ressources dont l'ID Discord n'existe pas encore au moment de compiler le plan :

```text
plan_symbol_bindings
--------------------
guild_id
plan_id
symbol_key                 # ROLE:ALPHA:FR, CHANNEL:GUIDES:EN...
resource_type
producer_operation_id NULL
discord_resource_id NULL
state                      # UNRESOLVED | RESOLVED | AMBIGUOUS
resolved_at NULL

UNIQUE(guild_id, plan_id, symbol_key)
```

Les opérations consomment des `symbol_key`; l'ID réel n'est injecté qu'après résolution.

## 7.12C operation_attempts

```text
operation_attempts
------------------
id UUID PK
guild_id
operation_id
attempt_no
request_fingerprint
started_at
response_received_at NULL
http_status NULL
result_fingerprint NULL
outcome_state              # FAILED_CONFIRMED | SUCCEEDED_CONFIRMED | UNKNOWN_OUTCOME
error_detail NULL
```

Cette table couvre le cas : appel Discord réussi, process crashé avant commit local.

Une création à `UNKNOWN_OUTCOME` doit être réconciliée avant tout retry.

## 7.13 snapshots

```text
id UUID
guild_id
kind
schema_version
content_json/compressed_blob
created_at
created_by
source
```

## 7.14 internal_audit_events

```text
id UUID
guild_id
actor_user_id
event_type
target_type
target_id
plan_id
operation_id
request_id
data_json
created_at
```

## 7.15 user_portable_artifacts

Stockage user-scopé pour clipboard, bibliothèque personnelle et bundles portables.

```text
user_portable_artifacts
-----------------------
id UUID PK
owner_discord_user_id
kind                    # CLIPBOARD | LIBRARY | EXPORT_BUNDLE
artifact_type           # CHANNEL | CATEGORY | LOGICAL_GROUP | GUILD_CONFIG | CUSTOM_BUNDLE
source_guild_id NULL    # provenance seulement
schema_version
name NULL
content_ciphertext BYTEA
content_nonce BYTEA
encryption_key_version
dependency_manifest_json        # métadonnées non sensibles minimales, sinon incluses dans le ciphertext
capability_manifest_json
content_hash
created_at
expires_at NULL
```

Règles :

- `source_guild_id` n'autorise jamais une lecture future de la source ;
- le payload doit contenir des références symboliques portables, pas des IDs Discord considérés comme valides sur une autre Guild ;
- le payload portable user-scopé est chiffré au repos via AEAD avec version de clé ;
- un clipboard temporaire a une expiration obligatoire et une purge scheduler ;
- une entrée de bibliothèque peut être persistante selon politique de rétention ;
- la taille maximale d'un artifact est bornée ;
- le schéma est validé avant import ;
- aucun secret, token, binding d'utilisateur ou token de webhook n'est inclus ;
- le contrôle d'accès se fait par `owner_discord_user_id`, pas par `guild_id`.

## 7.16 cross_guild_transfers

Table d'orchestration des transferts explicites entre deux tenants.

```text
cross_guild_transfers
---------------------
id UUID PK
actor_discord_user_id
source_guild_id
destination_guild_id
portable_artifact_id
destination_plan_id NULL
transfer_mode             # COPY_AS_NEW | MERGE | RECONCILE | MAXIMUM_COMPATIBLE
mapping_json
status
created_at
validated_at NULL
applied_at NULL
```

Cette table n'est **pas** une relation de fédération permanente entre Guilds. Elle trace une action utilisateur ponctuelle.

Le `destination_plan_id` référence un plan strictement tenant-scopé sur `destination_guild_id`.

## 7.17 language_profiles

```text
language_profiles
-----------------
id UUID PK
guild_id BIGINT NOT NULL
code VARCHAR NOT NULL           # BCP 47 canonicalisé: fr, en, pt-BR...
display_name VARCHAR NOT NULL
emoji VARCHAR NULL
enabled BOOLEAN NOT NULL
created_at
updated_at

UNIQUE(guild_id, code)
```

La langue est une métadonnée tenant-scopée. Elle n'identifie ni un Translation Group ni une audience.

## 7.18 visibility_scopes

```text
visibility_scopes
-----------------
id UUID PK
guild_id BIGINT NOT NULL
scope_type VARCHAR NOT NULL      # GLOBAL | LOGICAL_GROUP | STAFF | PROJECT | CUSTOM
scope_key VARCHAR NOT NULL
logical_group_id UUID NULL
name VARCHAR NOT NULL
config_json JSONB NOT NULL
created_at
updated_at

UNIQUE(guild_id, scope_key)
```

Un scope représente la dimension métier de l'accès.

## 7.19 visibility_scope_language_roles

Binding entre une intersection d'audience et une langue et un vrai rôle Discord.

```text
visibility_scope_language_roles
-------------------------------
id UUID PK
guild_id BIGINT NOT NULL
visibility_scope_id UUID NOT NULL
language_profile_id UUID NOT NULL
discord_role_id BIGINT NOT NULL
managed_by_did BOOLEAN NOT NULL
role_state VARCHAR NOT NULL       # ACTIVE | DRIFTED | MISSING | DETACHED
created_at
updated_at

UNIQUE(guild_id, visibility_scope_id, language_profile_id)
UNIQUE(guild_id, discord_role_id)
```

Les rôles créés par DID utilisent par défaut :

```text
permissions = 0
hoist = false
mentionable = false
```

Ils doivent être situés sous le rôle du bot pour permettre l'attribution/retrait.

## 7.20 member_visible_languages

Un membre ne possède pas de « langue principale » obligatoire. Son intention linguistique est un ensemble de zéro, une ou plusieurs langues visibles.

```text
member_visible_languages
------------------------
guild_id BIGINT NOT NULL
discord_user_id BIGINT NOT NULL
language_profile_id UUID NOT NULL
source VARCHAR NOT NULL
created_at
updated_at

PRIMARY KEY(guild_id, discord_user_id, language_profile_id)
```

Cette table décrit l'intention DID. Les vrais rôles Discord restent vérifiés par réconciliation.

Règles de cycle de vie :

- un Language Profile désactivé n'est plus compilé en nouveaux bindings actifs ;
- une référence utilisateur vers une langue désactivée peut être conservée comme préférence inactive jusqu'à nettoyage explicite ;
- la suppression définitive d'un Language Profile passe par Dependency Graph + Plan ;
- aucun fallback vers une autre langue n'est créé automatiquement ;
- une langue supprimée ne modifie pas les autres lignes `member_visible_languages` du membre.

## 7.20A resource_language_policies

Une ressource peut porter une langue sans appartenir à un Translation Group.

```text
resource_language_policies
--------------------------
id UUID PK
guild_id BIGINT NOT NULL
resource_type VARCHAR NOT NULL      # CATEGORY | CHANNEL
discord_resource_id BIGINT NOT NULL
explicit_language_profile_id UUID NULL
inherit_language BOOLEAN NOT NULL
visibility_policy VARCHAR NOT NULL  # OPEN_ALL | LANGUAGE_FILTERED | SCOPE_AND_LANGUAGE | CUSTOM
visibility_scope_id UUID NULL
custom_policy_json JSONB NULL
created_at
updated_at

UNIQUE(guild_id, resource_type, discord_resource_id)
```

Le Language Inheritance Resolver lit cette table ; il ne dépend pas uniquement des Translation Variants.

## 7.20B scope_membership_rules

```text
scope_membership_rules
----------------------
id UUID PK
guild_id BIGINT NOT NULL
visibility_scope_id UUID NOT NULL
rule_type VARCHAR NOT NULL          # DISCORD_ROLE | ANY_DISCORD_ROLE | ALL_DISCORD_ROLES | EXPLICIT_DID_MEMBERSHIP | CUSTOM
config_json JSONB NOT NULL
priority INTEGER NOT NULL
status VARCHAR NOT NULL
created_at
updated_at
```

Un `ScopeMembershipResolver` central compile ces règles. Le frontend ne déduit jamais lui-même l'appartenance ALPHA/STAFF/PROJECT.

## 7.21 translation_groups

```text
translation_groups
------------------
id UUID PK
guild_id BIGINT NOT NULL
name VARCHAR NOT NULL
root_kind VARCHAR NOT NULL          # CATEGORY_SET | CHANNEL_SET
visibility_scope_id UUID NULL
source_language_profile_id UUID NULL
routing_mode VARCHAR NOT NULL       # HUB_AND_SPOKE | FULL_MESH | CUSTOM
provider_binding_id UUID NULL
structure_sync_mode VARCHAR NOT NULL # MANUAL | PROMPT_ON_DRIFT | TEMPLATE_SYNC
status VARCHAR NOT NULL             # ACTIVE | DEGRADED | PROVIDER_ERROR | DETACHED
created_at
updated_at
```

Invariant : `id` est la seule identité de la famille de traduction. Les langues et noms ne servent jamais à déduire une appartenance.

## 7.22 translation_category_variants

```text
translation_category_variants
-----------------------------
id UUID PK
guild_id BIGINT NOT NULL
translation_group_id UUID NOT NULL
language_profile_id UUID NOT NULL
discord_category_id BIGINT NOT NULL
is_source BOOLEAN NOT NULL
state VARCHAR NOT NULL              # ACTIVE | MISSING | DRIFTED | DETACHED
created_at
updated_at

UNIQUE(guild_id, translation_group_id, language_profile_id)
UNIQUE(guild_id, discord_category_id)
```

## 7.23 translation_channel_groups

```text
translation_channel_groups
--------------------------
id UUID PK
guild_id BIGINT NOT NULL
translation_group_id UUID NOT NULL
logical_key VARCHAR NOT NULL
source_language_profile_id UUID NULL
config_json JSONB NOT NULL
created_at
updated_at

UNIQUE(guild_id, translation_group_id, logical_key)
```

`logical_key` est stable et ne dépend pas du nom localisé du salon.

## 7.24 translation_channel_variants

```text
translation_channel_variants
----------------------------
id UUID PK
guild_id BIGINT NOT NULL
translation_channel_group_id UUID NOT NULL
language_profile_id UUID NOT NULL
discord_channel_id BIGINT NOT NULL
translation_category_variant_id UUID NULL
state VARCHAR NOT NULL
created_at
updated_at

UNIQUE(guild_id, translation_channel_group_id, language_profile_id)
UNIQUE(guild_id, discord_channel_id)
```

## 7.25 translation_routes

Utilisé principalement pour `CUSTOM`; peut aussi matérialiser le résultat compilé d'un `HUB_AND_SPOKE`.

```text
translation_routes
------------------
id UUID PK
guild_id BIGINT NOT NULL
translation_group_id UUID NOT NULL
source_language_profile_id UUID NOT NULL
destination_language_profile_id UUID NOT NULL
enabled BOOLEAN NOT NULL
provider_route_ref VARCHAR NULL
created_at
updated_at

UNIQUE(guild_id, translation_group_id, source_language_profile_id, destination_language_profile_id)
```

## 7.26 translation_provider_bindings

```text
translation_provider_bindings
-----------------------------
id UUID PK
guild_id BIGINT NOT NULL
provider_type VARCHAR NOT NULL
provider_instance_key VARCHAR NOT NULL
provider_discord_user_id BIGINT NULL   # si le provider est un bot Discord présent dans la Guild
config_encrypted BYTEA NULL
capabilities_json JSONB NOT NULL
status VARCHAR NOT NULL             # READY | DEGRADED | ERROR | DISABLED
last_validated_at TIMESTAMPTZ NULL
created_at
updated_at

UNIQUE(guild_id, provider_instance_key)
```

Les secrets ne sont jamais exposés dans les artifacts portables ni au frontend.

## 7.27 translated_message_links (optionnel)

À activer uniquement si le provider expose un mapping message-à-message utile.

```text
translated_message_links
------------------------
id UUID PK
guild_id BIGINT NOT NULL
translation_channel_group_id UUID NOT NULL
logical_message_id UUID NOT NULL
language_profile_id UUID NOT NULL
discord_channel_id BIGINT NOT NULL
discord_message_id BIGINT NOT NULL
origin_language_profile_id UUID NULL
created_at
updated_at

UNIQUE(guild_id, discord_message_id)
```

Cette table n'est pas une archive générale du contenu des messages.

## 7.28 Intégrité tenant au niveau SQL

Les références entre agrégats tenant-scopés doivent utiliser des contraintes qui empêchent les croisements de Guilds.

Principe :

```text
UNIQUE(guild_id, id)
FK (guild_id, translation_group_id)
  -> translation_groups(guild_id, id)

FK (guild_id, language_profile_id)
  -> language_profiles(guild_id, id)
```

Même règle pour `visibility_scope_id`, `logical_group_id`, `provider_binding_id`, etc.

Une FK uniquement sur `id` n'est pas suffisante comme protection d'intégrité pour les relations tenant-scopées.

## 7.29 ui_catalog_versions

Catalogue global des clés UI attendues par une version du frontend.

```text
ui_catalog_versions
-------------------
id UUID PK
catalog_version VARCHAR UNIQUE
key_manifest_json JSONB NOT NULL
key_count INTEGER NOT NULL
content_hash VARCHAR NOT NULL
created_at
activated_at
```

Le manifest décrit les clés, namespaces, paramètres/interpolations et contraintes de pluralisation attendues.

## 7.30 ui_locale_packs

Les locales UI sont globales au produit et ne sont pas des `Language Profiles` de Guild.

```text
ui_locale_packs
---------------
id UUID PK
locale_code VARCHAR NOT NULL          # en, fr, de, es, pt-BR...
display_name VARCHAR NOT NULL
flag_code VARCHAR NULL                 # icône représentative, pas identité de langue
direction VARCHAR NOT NULL             # LTR | RTL
catalog_version VARCHAR NOT NULL
status VARCHAR NOT NULL                # DRAFT | VALID | ACTIVE | INCOMPLETE | DISABLED
payload_json JSONB NOT NULL
coverage_count INTEGER NOT NULL
coverage_percent NUMERIC NOT NULL
content_hash VARCHAR NOT NULL
created_at
updated_at
activated_at NULL

UNIQUE(locale_code, catalog_version)
```

Une locale `ACTIVE` a obligatoirement 100 % des clés requises du catalogue courant.

Packs de base obligatoires :

```text
🇬🇧 English   en
🇫🇷 Français  fr
🇩🇪 Deutsch   de
🇪🇸 Español   es
```

## 7.31 user_ui_preferences

```text
user_ui_preferences
-------------------
discord_user_id BIGINT PK
ui_locale_override_code VARCHAR NULL   # NULL = AUTO_BROWSER
timezone VARCHAR NULL
created_at
updated_at
```

`ui_locale_override_code` est indépendant de toute langue de contenu Discord. `NULL` signifie **Automatique (langue du navigateur)** et non « anglais ».

## 7.32 message_campaigns

Une campagne peut cibler plusieurs Guilds ; son en-tête appartient donc au **User Control Plane**, pas à une Guild unique.

```text
message_campaigns
-----------------
id UUID PK
owner_discord_user_id BIGINT NOT NULL
name VARCHAR NOT NULL
status VARCHAR NOT NULL             # DRAFT | ACTIVE | PAUSED | COMPLETED | CANCELLED
execution_mode VARCHAR NOT NULL     # MANUAL_NOW | SCHEDULED_ONCE | RECURRING | EVENT_TRIGGERED | EVENT_TRIGGERED_WITH_DELAY
source_content_language_tag VARCHAR NULL  # BCP 47, indépendant du UI Locale
translation_mode VARCHAR NOT NULL   # SOURCE_ONLY | PROVIDER_HANDLES | DID_FANOUT | MANUAL_VARIANTS
review_policy VARCHAR NOT NULL      # AUTO_TECH_VALIDATED | REVIEW_ON_WARNING | ALWAYS_REVIEW | APPROVED_ONLY
message_model_json JSONB NOT NULL
allowed_mentions_policy_json JSONB NOT NULL
created_at
updated_at
```

Le `message_model_json` est un modèle structuré DID, jamais seulement un bloc de texte brut.

## 7.33 message_campaign_targets

```text
message_campaign_targets
------------------------
id UUID PK
campaign_id UUID NOT NULL
guild_id BIGINT NOT NULL
selector_type VARCHAR NOT NULL      # CHANNEL | CHANNEL_SET | LOGICAL_GROUP | TRANSLATION_GROUP | LANGUAGE_VARIANTS | DEFAULT_BROADCAST
selector_json JSONB NOT NULL
resolution_mode VARCHAR NOT NULL    # SNAPSHOT | RESOLVE_EACH_OCCURRENCE
created_at
updated_at
```

Cette table est une association cross-control-plane explicite. L'accès nécessite à la fois la propriété/ACL campagne et l'autorisation sur `guild_id`.

## 7.34 message_campaign_schedules

```text
message_campaign_schedules
--------------------------
id UUID PK
campaign_id UUID NOT NULL
schedule_type VARCHAR NOT NULL       # ONCE | RRULE | EVENT
timezone VARCHAR NOT NULL             # IANA
start_at TIMESTAMPTZ NULL
rrule VARCHAR NULL                     # canonical recurrence representation
end_at TIMESTAMPTZ NULL
max_occurrences INTEGER NULL
next_run_at TIMESTAMPTZ NULL
enabled BOOLEAN NOT NULL
created_at
updated_at
```

La source de vérité du planning est PostgreSQL ; le scheduler ne conserve pas un planning critique uniquement en mémoire.

## 7.35 message_event_triggers

```text
message_event_triggers
----------------------
id UUID PK
campaign_id UUID NOT NULL
event_type VARCHAR NOT NULL
condition_ast_json JSONB NOT NULL
delay_seconds INTEGER NULL
debounce_seconds INTEGER NULL
enabled BOOLEAN NOT NULL
created_at
updated_at
```

`condition_ast_json` représente des conditions `AND/OR/NOT` validées par schéma, jamais du Python/SQL arbitraire.

## 7.35A message_event_trigger_sources

Sources tenant-scopées explicitement autorisées à déclencher un trigger.

```text
message_event_trigger_sources
-----------------------------
id UUID PK
trigger_id UUID NOT NULL
guild_id BIGINT NOT NULL
source_selector_json JSONB NOT NULL   # Guild entière, logical scope, resource selector...
source_selector_hash VARCHAR NOT NULL
created_at
updated_at

UNIQUE(trigger_id, guild_id, source_selector_hash)
```

Une campagne cross-Guild ne peut jamais être déclenchée par un événement d'une Guild non liée explicitement au trigger. L'autorisation de la source et celles des destinations sont indépendantes.

## 7.36 message_occurrences

```text
message_occurrences
-------------------
id UUID PK
campaign_id UUID NOT NULL
occurrence_key VARCHAR NOT NULL
trigger_type VARCHAR NOT NULL
trigger_event_id VARCHAR NULL
scheduled_for TIMESTAMPTZ NULL
status VARCHAR NOT NULL              # PENDING | RUNNING | PARTIAL | SUCCEEDED | FAILED | CANCELLED
created_at
started_at NULL
finished_at NULL

UNIQUE(campaign_id, occurrence_key)
```

## 7.37 message_deliveries

Chaque livraison est tenant-scopée.

```text
message_deliveries
------------------
id UUID PK
occurrence_id UUID NOT NULL
campaign_id UUID NOT NULL
guild_id BIGINT NOT NULL
discord_channel_id BIGINT NOT NULL
language_profile_id UUID NULL
translation_group_id UUID NULL
idempotency_key VARCHAR NOT NULL
content_snapshot_json JSONB NOT NULL
technical_fingerprint_json JSONB NOT NULL
translation_status VARCHAR NOT NULL
review_status VARCHAR NOT NULL
delivery_status VARCHAR NOT NULL
discord_message_id BIGINT NULL
attempt_count INTEGER NOT NULL DEFAULT 0
last_error_code VARCHAR NULL
created_at
sent_at NULL
updated_at

UNIQUE(idempotency_key)
```

Les snapshots concernent uniquement les publications DID, pas les conversations générales Discord.

## 7.38 message_translation_glossaries

```text
message_translation_glossaries
------------------------------
id UUID PK
guild_id BIGINT NOT NULL
name VARCHAR NOT NULL
logical_group_id UUID NULL
translation_group_id UUID NULL
template_key VARCHAR NULL
enabled BOOLEAN NOT NULL
created_at
updated_at
```

```text
message_translation_terms
-------------------------
id UUID PK
glossary_id UUID NOT NULL
match_type VARCHAR NOT NULL           # EXACT | CASE_INSENSITIVE | REGEX
source_term VARCHAR NOT NULL
policy VARCHAR NOT NULL               # DO_NOT_TRANSLATE | FORCE_TRANSLATION
target_translations_json JSONB NULL
priority INTEGER NOT NULL
enabled BOOLEAN NOT NULL
```

Les regex sont bornées, validées et protégées contre les patterns pathologiques.

Ordre de résolution des glossaires applicables :

```text
TEMPLATE > TRANSLATION_GROUP > LOGICAL_GROUP > GUILD
```

Au même niveau : `priority` décroissante puis identifiant stable. Deux `FORCE_TRANSLATION` contradictoires de même priorité produisent `GLOSSARY_CONFLICT` et bloquent la variante jusqu'à résolution.

## 7.39 approved_message_variants

```text
approved_message_variants
-------------------------
id UUID PK
campaign_id UUID NULL
template_key VARCHAR NULL
guild_id BIGINT NULL
content_language_tag VARCHAR NOT NULL
message_model_json JSONB NOT NULL
technical_fingerprint_json JSONB NOT NULL
approved_by BIGINT NOT NULL
approved_at TIMESTAMPTZ NOT NULL
source_content_hash VARCHAR NOT NULL
glossary_version_hash VARCHAR NOT NULL
```

Une variante approuvée devient invalide si la source ou le glossaire auquel elle est liée change.

---

# 8. OAuth2

## 8.1 Flow d'authentification

Le dashboard utilise le **Discord OAuth2 Authorization Code Grant** avec backend confidentiel.

```text
Browser
  │ GET /auth/discord/login
  ▼
Backend
  │ generate state cryptographically random / single-use / TTL
  │ redirect Discord /oauth2/authorize
  ▼
Discord OAuth2
  │ scopes: identify guilds
  ▼
/auth/discord/callback?code=...&state=...
  │ validate + consume state
  │ exchange code server-side with client credentials
  │ GET /users/@me
  │ GET /users/@me/guilds
  ▼
Opaque DID session
```

Décisions :

- Authorization Code Grant uniquement pour le login dashboard ;
- pas d'Implicit Grant ;
- `client_secret` uniquement backend ;
- échange token en `application/x-www-form-urlencoded` selon le contrat Discord ;
- redirect URI issue d'une allowlist de configuration exacte ;
- `state` obligatoire, usage unique et expirant ;
- scopes initiaux `identify guilds`.

## 8.2 Tokens utilisateur et refresh

Les tokens ne sont jamais renvoyés au frontend après le callback.

Le refresh token est conservé côté serveur pour les grants actifs afin de permettre les sessions durables et les revalidations OAuth sans consentement interactif répété :

- stockage AEAD avec `key_version` ;
- `expires_at` calculé depuis la réponse Discord, jamais hardcodé ;
- scopes persistés ;
- refresh backend on-demand ;
- un seul refresh concurrent par utilisateur via single-flight/lock ;
- sur 401/token invalid, au plus un refresh contrôlé avant échec ;
- pas de boucle de retry OAuth.

La déconnexion ordinaire détruit la session locale. La révocation Discord est une action explicite distincte, car elle invalide le grant OAuth de l'utilisateur.

## 8.3 Session navigateur

Session normative :

- identifiant opaque ;
- cookie `HttpOnly` ;
- `Secure` en production ;
- cookie host-only (`__Host-...` lorsque le déploiement HTTPS le permet) ;
- `SameSite=Lax` ou politique stricte compatible avec le redirect OAuth ;
- rotation de l'ID de session après authentification ;
- expiration idle + absolute configurables ;
- état serveur Redis/DB selon stratégie de durabilité ;
- jamais de JWT longue durée dans `localStorage`.

Les routes mutantes basées sur cookie utilisent une protection CSRF dédiée ; OAuth `state` protège le callback OAuth, pas toutes les mutations de l'application.

## 8.4 Liste des Guilds et cache OAuth

`GET /users/@me/guilds` avec le scope `guilds` fournit notamment `id`, `owner` et `permissions`.

Le résultat est mis en cache côté serveur avec :

```text
fetched_at
expires/stale policy
source = DISCORD_OAUTH
```

Il n'est pas rechargé à chaque changement de page. Le `DiscordOAuthClient` a sa propre gouvernance de requêtes et ne contourne jamais les rate limits Discord.

Cette liste sert à la découverte et comme preuve fraîche lorsqu'elle est requise ; elle ne remplace pas le RBAC/ACL DID ni les contrôles tenant.

## 8.5 Autorisation cross-Guild

Une opération source A → destination B est autorisée par deux décisions indépendantes :

```text
authorize_export(user, guild_A, resource)
authorize_import(user, guild_B, requested_actions)
```

Le backend ne doit jamais déduire l'autorisation destination à partir de l'autorisation source ni l'inverse.

Flux obligatoire :

```text
1. authorize source
2. pour LIVE_CLONE : vérifier DID installé et source suffisamment observable
3. read source depuis cache local + refresh ciblé seulement si nécessaire
4. build immutable portable artifact
5. terminate source read context
6. authorize destination
7. compile destination-only plan
8. preflight destination
9. revalidate destination authorization immediately before APPLY
10. apply destination
```

Si l'accès de l'utilisateur à A ou B est révoqué avant l'étape qui l'exige, l'opération est refusée.

Le `source_guild_id` conservé dans un artifact est une provenance et non une capability.

## 8.6 Séparation login / installation

Le flow de login OAuth2 utilisateur et le flow d'installation serveur du bot sont séparés conceptuellement :

```text
LOGIN DASHBOARD
Authorization Code Grant + identify/guilds

INSTALLATION GUILD
Discord application install / GUILD_INSTALL + permissions bot
```

Une réussite du login ne signifie jamais que le bot est installé ; une installation du bot ne crée jamais implicitement une session dashboard.

---

# 9. Installation Discord

## 9.1 Server install

Utiliser le contexte `GUILD_INSTALL`.

## 9.2 Discord vs politique interne

Discord exige au minimum `MANAGE_GUILD` pour autoriser une installation serveur.

Politique de bootstrap :

```text
owner == true
OR
permissions contains ADMINISTRATOR
```

pour activer/configurer le tenant.

## 9.3 Installation event / détection

Le bot reçoit la guild via Gateway après installation.

Créer ou mettre à jour :

```text
guild_installations.status = PENDING_SETUP
```

## 9.4 Désinstallation

Sur Guild Delete/removal :

```text
status = UNINSTALLED
```

Ne pas supprimer immédiatement toutes les données sans politique de rétention.

---

# 10. Bot process

## 10.1 Responsabilités

Le process bot :

- maintient la connexion Gateway ;
- reçoit les événements ;
- normalise les événements ;
- met à jour/invalide le cache ;
- publie des événements internes ;
- enregistre l'état de connexion ;
- gère les interactions Discord définies.

Il ne doit pas contenir la majorité de la logique métier.

## 10.2 Intents

Commencer au minimum.

Évaluer séparément :

```text
GUILDS
GUILD_MEMBERS          privileged
GUILD_MODERATION
GUILD_WEBHOOKS
...
```

Ne pas activer :

- `GUILD_PRESENCES` si inutile ;
- `MESSAGE_CONTENT` pour des fonctions de structure.

Discord impose une approbation des intents privilégiés lorsque l'application atteint les conditions de vérification applicables.

### 10.2.1 Décision `GUILD_MEMBERS`

Le socle structure/categories/roles ne dépend pas obligatoirement de `GUILD_MEMBERS`.

En revanche, les fonctionnalités suivantes peuvent en dépendre :

- suivi fiable join/leave/update de tous les membres ;
- cache complet des appartenances de rôles ;
- réconciliation automatique `Scope × Language` à l'échelle de toute la Guild ;
- certaines analyses « qui possède ce rôle ? » exhaustives ;
- onboarding/automatisations basées sur l'arrivée/départ de membres.

L'architecture doit donc définir un **Member Data Capability** :

```text
FULL_MEMBER_EVENTS
ON_DEMAND_MEMBER_LOOKUP
DEGRADED_NO_PRIVILEGED_INTENT
```

`ON_DEMAND_MEMBER_LOOKUP` sert notamment à l'autorisation du dashboard :

```text
Actor role cache fresh -> use cache
else -> Discord REST Get Guild Member(actor_user_id)
     -> update only actor membership cache
```

Ne jamais lancer `List Guild Members` seulement pour connaître les rôles de l'acteur connecté. Cela permet de conserver un chemin d'autorisation précis même lorsque le cache complet des membres n'est pas disponible, tout en minimisant les requêtes.

### 10.2.2 Fraîcheur du cache d'autorisation acteur

Le cache d'appartenance/rôles de l'acteur conserve au minimum :

```text
observed_at
source = GATEWAY | TARGETED_REST | RECONCILE
validity = FRESH | STALE | INVALIDATED | UNKNOWN
```

La policy distingue :

```text
DISPLAY_FRESHNESS       # lecture/UI ; stale contrôlé possible
AUTHORIZATION_FRESHNESS # action sensible ; fenêtre plus stricte
```

Les événements `Guild Member Update`/changements de rôles observables invalident immédiatement les décisions d'autorisation dépendantes. Si ces événements ne sont pas disponibles ou si `AUTHORIZATION_FRESHNESS` est dépassée, une action HIGH/CRITICAL, un changement de permissions ou une publication sensible force un `Get Guild Member(actor_user_id)` ciblé avant autorisation. La fenêtre est configurable et observée par métriques ; elle ne doit pas provoquer un lookup REST à chaque clic lorsque le cache vient d'être rafraîchi.

Si `GUILD_MEMBERS` n'est pas activé/autorisé, l'UI ne prétend pas disposer d'une vue exhaustive des membres et désactive/dégrade les fonctions concernées.

À la date de référence, Discord indique que la revue des intents privilégiés devient nécessaire au-delà de **10 000 utilisateurs uniques pouvant voir l'application**, avec réexamen annuel des accès accordés. Cette valeur est une contrainte opérationnelle à revalider dans la documentation, pas une constante métier.

## 10.3 Event envelope interne

```json
{
  "event_id": "uuid",
  "event_type": "discord.channel.updated",
  "guild_id": "123456789012345678",
  "discord_event_id": null,
  "origin": "DISCORD_EXTERNAL|DID_PLAN|DID_CAMPAIGN|DID_TRANSLATION|SYSTEM",
  "correlation_id": "uuid",
  "causation_id": "uuid|null",
  "causation_depth": 0,
  "occurred_at": "2026-08-16T09:00:00Z",
  "payload": {}
}
```

## 10.4 Déduplication

Les consumers doivent tolérer des événements répétés.

## 10.5 Localisation des Application Commands

Les définitions de commandes maintiennent un catalogue stable et compilent vers les champs Discord `name_localizations` / `description_localizations` ainsi que les localisations des options/choices supportées.

Principes :

- EN/FR/DE/ES fournis ;
- mapping explicite UI locale -> locale Discord supportée ;
- les réponses d'interaction utilisent `interaction.locale` pour leur texte applicatif ;
- une locale UI non supportée n'est pas poussée comme clé invalide à Discord ;
- les mises à jour de commandes sont coalescées et ne sont pas déclenchées à chaque chargement d'un locale pack afin de respecter les limites de création/synchronisation Discord.

---

# 11. Discord REST adapter

## 11.1 Interface

Exemples :

```python
class DiscordGuildPort(Protocol):
    async def fetch_guild(...)
    async def fetch_channels(...)
    async def fetch_roles(...)
    async def create_channel(...)
    async def modify_channel(...)
    async def create_role(...)
    async def modify_role(...)
    async def set_channel_overwrite(...)
```

## 11.2 Audit reason

Toutes les routes Discord compatibles doivent recevoir un `X-Audit-Log-Reason`.

Exemple logique :

```text
DID plan 0f3c... by user 1234: duplicate category ALPHA -> BETA
```

Respecter la limite de longueur Discord.

## 11.3 Rate Limit Governor

Discord applique des limites **par route/bucket** et **globales**. Les valeurs de route sont dynamiques et ne doivent pas être hardcodées.

L'adapter doit observer :

```text
X-RateLimit-Bucket
X-RateLimit-Remaining
X-RateLimit-Reset-After
X-RateLimit-Scope
Retry-After / retry_after
X-RateLimit-Global
```

La bibliothèque Discord peut gérer les limites localement, mais cela ne suffit pas si plusieurs processus utilisent le même bot token sans coordination.

### Décision : propriétaire central du REST bot-token

La majorité des appels REST bot-token sont centralisés dans un **Discord I/O Worker** :

```text
API / Bot Gateway / Scheduler
          ↓ jobs/intents
Discord I/O Worker
          ↓
Discord REST Adapter
          ↓
Discord API
```

Le Bot Gateway privilégie la réception d'événements et évite les GET opportunistes. Les interactions peuvent utiliser leur chemin de réponse dédié.

Si plusieurs workers REST sont nécessaires pour la montée en charge, ils partagent obligatoirement une coordination Redis des budgets/buckets et de la concurrence.

### Invalid request budget

Suivre sur fenêtre glissante les `401`, `403`, `429` et autres erreurs pertinentes. Les `403` prévisibles doivent être éliminés par le Capability/Permission Engine avant l'appel.

### Backpressure

Le governor expose au Plan Worker :

```text
READY
WAIT_BUCKET
WAIT_GLOBAL
DEGRADED
```

Un plan massif ralentit proprement au lieu de générer des 429 en rafale.

### Réduction du nombre d'appels

Le Plan Compiler utilise les primitives bulk lorsqu'elles correspondent à l'intention, notamment :

- `Modify Guild Channel Positions` pour plusieurs positions de channels ;
- `Modify Guild Role Positions` pour plusieurs positions de rôles.

Il ne remplace pas artificiellement un endpoint unitaire par une rafale parallèle.

---

# 12. Moteur de permissions

## 12.1 Module critique

Créer un module autonome :

```text
backend/src/did/permissions/
├── bits.py
├── calculator.py
├── explain.py
├── simulate.py
├── diff.py
└── models.py
```

## 12.2 Entrées

- permissions `@everyone` ;
- rôles du membre ;
- positions ;
- permission overwrites du channel ;
- owner ;
- `ADMINISTRATOR`.

## 12.3 Sorties

```text
effective_permissions
visibility
explanation_trace
decisive_rules
warnings
```

## 12.4 Tests

Créer des fixtures couvrant :

- @everyone ;
- un rôle ;
- plusieurs rôles ;
- deny everyone ;
- allow rôle ;
- deny rôle ;
- overwrite membre ;
- Administrator ;
- owner ;
- threads.

## 12.5 Conformité

Le moteur doit être testé contre des guildes Discord de test réelles.

---

# 13. Moteur d'intentions

## 13.1 Entrée métier

```json
{
  "visibility": ["ROLE:ALPHA"],
  "writers": ["ROLE:ALPHA_OFFICER", "BOT:STATBOT"],
  "everyone_else": "deny"
}
```

## 13.2 Compilation

```text
Intention
→ resolve symbolic references
→ calculate target overwrites
→ compare existing state
→ produce plan operations
```

## 13.3 Desired State Graph — représentation intermédiaire commune

Les fonctionnalités complexes ne doivent pas produire chacune leur propre format de mutations.

Toutes convergent vers un **Desired State Graph (DSG)** :

```text
User Intent / Template / Clone / Right Drag / Multilingual
                         ↓
                 Desired State Graph
                 ├── RESOURCE nodes
                 ├── SYMBOLIC refs
                 ├── DEPENDENCIES
                 ├── LOCAL metadata
                 └── PROVIDER requirements
                         ↓
                  Current State Cache
                         ↓
                       Diff
                         ↓
                       Plan
```

Le DSG est une représentation logique sans appels réseau. Il permet de partager le même compilateur final entre :

- duplication ;
- clonage cross-Guild ;
- templates ;
- intentions de permissions ;
- création multilingue ;
- synchronisation/reconcile.

Un nœud peut cibler :

```text
DISCORD_RESOURCE
DID_LOCAL_RESOURCE
PROVIDER_REQUIREMENT
```

## 13.4 Pas d'application directe

Le compilateur ne fait aucun appel Discord.

---

# 14. Plan engine

## 14.1 Architecture

```text
Desired State
    ↓
Diff Engine
    ↓
Plan Builder
    ↓
Preflight
    ↓
Risk Engine
    ↓
Persisted Plan
```

## 14.2 Opérations

Exemples :

```text
CREATE_ROLE
UPDATE_ROLE
MOVE_ROLE
DELETE_ROLE
CREATE_CATEGORY
CREATE_CHANNEL
UPDATE_CHANNEL
MOVE_CHANNEL
DELETE_CHANNEL
SET_OVERWRITE
DELETE_OVERWRITE
ASSIGN_MEMBER_ROLE
REMOVE_MEMBER_ROLE
CREATE_LANGUAGE_PROFILE
CREATE_VISIBILITY_SCOPE
CREATE_SCOPE_LANGUAGE_ROLE
BIND_SCOPE_LANGUAGE_ROLE
CREATE_TRANSLATION_GROUP
CREATE_TRANSLATION_CHANNEL_GROUP
BIND_TRANSLATION_CATEGORY_VARIANT
BIND_TRANSLATION_CHANNEL_VARIANT
UNBIND_TRANSLATION_VARIANT
CREATE_TRANSLATION_ROUTE
DELETE_TRANSLATION_ROUTE
CONFIGURE_TRANSLATION_PROVIDER
RECONCILE_TRANSLATION_TOPOLOGY
SET_MEMBER_LANGUAGE_PREFERENCE
```

Le champ `execution_target` évite de confondre :

```text
DISCORD   -> CREATE_CHANNEL, SET_OVERWRITE, ASSIGN_MEMBER_ROLE...
DID_LOCAL -> CREATE_TRANSLATION_GROUP, BIND_TRANSLATION_VARIANT...
PROVIDER  -> uniquement si l'adapter supporte réellement une configuration automatique
```

Un provider manuel génère une opération/local state `PROVIDER_CONFIGURATION_PENDING`, pas un faux appel `CONFIGURE_TRANSLATION_PROVIDER`.

## 14.3 Dépendances

Exemple duplication :

```text
CREATE_ROLE Beta
       ↓
CREATE_CATEGORY Beta
       ↓
CREATE_CHANNEL beta-general
       ↓
SET_OVERWRITE @Beta
```

## 14.4 DAG persistant

Pour les opérations complexes, représenter les dépendances explicitement dans `plan_operation_dependencies`.

L'exécution peut être séquentielle tant que le DAG est respecté et que `sequence` n'est jamais considérée comme la seule vérité de dépendance.

Les créations utilisent des références symboliques :

```text
CREATE_ROLE -> produit ROLE:ALPHA:FR
CREATE_CATEGORY -> produit CATEGORY:GUIDES:EN
SET_OVERWRITE -> consomme ROLE:ALPHA:FR + CATEGORY:GUIDES:EN
```

`plan_symbol_bindings` résout les symboles vers les IDs Discord créés.

## 14.5 Idempotence et outcome inconnu

Chaque opération doit pouvoir répondre :

> Si le worker redémarre après succès Discord mais avant commit local, peut-on prouver si l'état désiré existe déjà ?

États minimum :

```text
PENDING
RUNNING
APPLIED
FAILED_CONFIRMED
UNKNOWN_OUTCOME
NEEDS_RECONCILIATION
```

### Règle pour les CREATE

Un `CREATE_*` en `UNKNOWN_OUTCOME` **n'est jamais retry directement**.

Flux :

```text
UNKNOWN_OUTCOME
   ↓
reconcile ciblé
   ├─ correspondance unique prouvée -> RESOLVE + APPLIED
   ├─ aucune ressource créée prouvée -> retry autorisable
   └─ ambigu -> NEEDS_INTERVENTION
```

Le nom seul ne constitue pas forcément une preuve d'identité suffisante si plusieurs ressources identiques peuvent exister.

---

# 15. Preflight engine

Vérifications :

```text
tenant active
bot present
bot permissions
role hierarchy
resource existence
resource tenant membership
Discord capacity limits
template validity
operation conflicts
plan base version
stale state
```

## 15.1 Optimistic concurrency

Le plan garde :

```text
base_snapshot_id
base_structure_version
```

Avant apply :

- vérifier que la structure critique n'a pas changé ;
- sinon passer le plan en `STALE`.

---


### 15.2 Vérifications multilingues

Pour tout plan multilingue, vérifier également :

```text
language profile exists/enabled
translation_group_id belongs to destination guild
no duplicate language variant in group
no channel/category already bound to another incompatible group
visibility scope valid
scope×language role reusable or creatable
projected role count <= Discord capability
projected overwrites <= Discord capability
bot can manage derived roles
provider binding exists when translation is requested
provider presence valid when provider_discord_user_id is required
provider effective channel permissions sufficient
provider supports requested routing mode
provider max language count not exceeded
no route creates an invalid self-loop unless provider explicitly supports it
all mappings are tenant-local
```

Un provider indisponible peut autoriser un plan `STRUCTURE_ONLY` si l'utilisateur le choisit explicitement, mais le résultat doit être marqué `PROVIDER_PENDING`/`DEGRADED` et non `READY`.

# 16. Risk engine

Niveaux :

```text
LOW
MEDIUM
HIGH
CRITICAL
```

Exemples CRITICAL :

- donner Administrator ;
- rendre public un salon privé ;
- supprimer une catégorie ;
- supprimer un rôle massif ;
- retirer l'accès du bot nécessaire au reste du plan.

---

# 17. Discord I/O Worker

Ce process est **à la fois** l'exécuteur des plans Discord et le propriétaire principal des appels REST bot-token. Il exécute également les refresh/reconcile Discord.

Cette centralisation évite d'avoir plusieurs limiteurs indépendants dans plusieurs processus.

## 17.1 Job

```json
{
  "job_id": "...",
  "type": "APPLY_PLAN",
  "guild_id": "...",
  "plan_id": "...",
  "requested_by": "..."
}
```

### 17.1A Jobs User Control Plane multi-Guild

Un job d'orchestration user-scopé peut ne pas avoir de `guild_id` unique :

```json
{
  "job_id": "...",
  "scope_type": "USER_CONTROL_PLANE",
  "type": "CREATE_CAMPAIGN_OCCURRENCE",
  "actor_user_id": "...",
  "campaign_id": "..."
}
```

Invariant : ce job ne peut pas appeler un adapter Discord mutable directement. Il produit des jobs enfants :

```json
{
  "scope_type": "TENANT",
  "type": "SEND_CAMPAIGN_DELIVERY",
  "guild_id": "...",
  "delivery_id": "..."
}
```

Toute interaction REST Discord appartient donc à un contexte tenant explicite même lorsqu'une campagne est multi-Guild.

## 17.2 Lock tenant

Une mutation structurelle majeure par guild à la fois :

```text
lock:did:guild:{guild_id}:mutation
```

## 17.3 Exécution

```text
lock
↓
reload plan
↓
preflight final
↓
operation 1
↓
persist result
↓
operation 2
↓
...
↓
verify Discord state
↓
snapshot
↓
unlock
```

## 17.4 Résilience

Sur crash :

- opérations déjà confirmées restent `APPLIED` ;
- toute opération `RUNNING` au moment du crash devient candidate `UNKNOWN_OUTCOME` ;
- un GET/UPDATE/DELETE peut être requalifié selon sa sémantique et l'état observé ;
- un CREATE n'est pas retry avant réconciliation ciblée ;
- le job reprend ou passe en intervention selon la preuve disponible.

L'objectif n'est pas une « exactly once delivery » impossible à garantir vis-à-vis de Discord, mais une **effectively-once mutation observable** grâce aux attempts, symbol bindings et reconcile.

---

# 18. Redis Streams

Streams proposés :

```text
did:jobs
did:domain-events
did:discord-events
```

Consumer groups :

```text
worker-apply
worker-reconcile
api-live
```

Ne pas créer un bus d'événements générique complexe si des streams typés couvrent correctement les besoins.

---

# 19. API FastAPI

## 19.1 Versioning

```text
/api/v1/...
```

## 19.2 Routes

```text
# Auth/session
GET  /auth/discord/login
GET  /auth/discord/callback
POST /auth/logout
POST /api/v1/me/oauth/discord/revoke

# User Control Plane
GET   /api/v1/me
GET   /api/v1/me/preferences
PATCH /api/v1/me/preferences          # ui_locale_override_code: null = AUTO_BROWSER

GET  /api/v1/guilds
GET  /api/v1/guilds/{guild_id}
GET  /api/v1/guilds/{guild_id}/structure
GET  /api/v1/guilds/{guild_id}/roles
GET  /api/v1/guilds/{guild_id}/members
GET  /api/v1/guilds/{guild_id}/bots

POST /api/v1/guilds/{guild_id}/plans
GET  /api/v1/guilds/{guild_id}/plans/{plan_id}
POST /api/v1/guilds/{guild_id}/plans/{plan_id}/validate
POST /api/v1/guilds/{guild_id}/plans/{plan_id}/apply
POST /api/v1/guilds/{guild_id}/simulate
POST /api/v1/guilds/{guild_id}/permissions/explain


# Portabilité user-scopée / inter-Guild
POST   /api/v1/guilds/{guild_id}/exports/portable
GET    /api/v1/me/portable-artifacts
POST   /api/v1/me/portable-artifacts/{artifact_id}/clone
DELETE /api/v1/me/portable-artifacts/{artifact_id}
POST   /api/v1/guilds/{guild_id}/imports/plan
POST   /api/v1/transfers
GET    /api/v1/transfers/{transfer_id}

# Multilingue / traduction
GET    /api/v1/guilds/{guild_id}/languages
POST   /api/v1/guilds/{guild_id}/languages
PATCH  /api/v1/guilds/{guild_id}/languages/{language_id}
GET    /api/v1/guilds/{guild_id}/translation-groups
POST   /api/v1/guilds/{guild_id}/translation-groups
GET    /api/v1/guilds/{guild_id}/translation-groups/{group_id}
POST   /api/v1/guilds/{guild_id}/translation-groups/{group_id}/variants/plan
POST   /api/v1/guilds/{guild_id}/translation-groups/{group_id}/link/plan
POST   /api/v1/guilds/{guild_id}/translation-groups/{group_id}/unlink/plan
POST   /api/v1/guilds/{guild_id}/translation-groups/{group_id}/reconcile/plan
POST   /api/v1/guilds/{guild_id}/translation-groups/{group_id}/routes/plan
GET    /api/v1/guilds/{guild_id}/translation-groups/{group_id}/drift
GET    /api/v1/guilds/{guild_id}/visibility-scopes
POST   /api/v1/guilds/{guild_id}/visibility-scopes
PUT    /api/v1/guilds/{guild_id}/members/{user_id}/languages
GET    /api/v1/guilds/{guild_id}/translation-providers
POST   /api/v1/guilds/{guild_id}/translation-providers/{provider_key}/validate
```

## 19.3 Réponse d'erreur localisable

Le transport HTTP ne choisit jamais la langue finale du message UX. Format :

```json
{
  "error": {
    "code": "DISCORD_ROLE_HIERARCHY",
    "message_key": "errors.discord.roleHierarchy",
    "params": {
      "roleName": "Officier"
    },
    "request_id": "..."
  }
}
```

Le frontend résout `message_key` dans la locale effective. Un éventuel `debug_detail` brut est réservé aux logs/audits/panneaux experts explicitement identifiés et ne remplace jamais le texte UX localisé.

## 19.4 Pydantic

Schémas API séparés des modèles SQLAlchemy.

---

## 19.8 Cache visibility / purge endpoints

Exemples d'API tenant-scopées :

```text
GET  /api/v1/guilds/{guild_id}/channels?include_hidden_deleted=true|false
POST /api/v1/guilds/{guild_id}/cache/channels/confirm-deleted
POST /api/v1/guilds/{guild_id}/cache/channels/purge
POST /api/v1/guilds/{guild_id}/cache/channels/purge-bulk
```

Les endpoints de purge ne doivent appeler aucun endpoint Discord de suppression. Ils exigent une capability dédiée (`cache.purge`) et produisent un audit interne.

---

# 20. WebSocket / live updates

## 20.1 Endpoint

```text
/ws/v1/guilds/{guild_id}
```

## 20.2 Auth

Session utilisateur + ACL tenant.

## 20.3 Événements

```json
{
  "type": "plan.operation.updated",
  "guild_id": "...",
  "payload": {}
}
```

## 20.4 Isolation

Le serveur ne subscribe jamais un socket à un channel Redis sans avoir validé le tenant.

---

# 21. Frontend React

## 21.1 Arborescence par features

```text
src/
├── app/
│   ├── router/
│   ├── providers/
│   └── layout/
├── pages/
│   ├── guild-select/
│   ├── setup/
│   ├── structure/
│   ├── permissions/
│   ├── members/
│   ├── bots/
│   ├── translations/
│   ├── campaigns/
│   ├── plans/
│   └── audit/
├── features/
│   ├── move-channel/
│   ├── duplicate-category/
│   ├── simulate-access/
│   ├── explain-permission/
│   ├── multilingual-clone/
│   ├── link-translation-variant/
│   ├── language-visibility/
│   ├── translation-drift/
│   ├── campaign-composer/
│   ├── campaign-targeting/
│   ├── message-translation-preview/
│   └── apply-plan/
├── entities/
│   ├── guild/
│   ├── channel/
│   ├── role/
│   ├── member/
│   ├── language-profile/
│   ├── translation-group/
│   ├── visibility-scope/
│   ├── campaign/
│   ├── message-delivery/
│   └── plan/
└── shared/
    ├── ui/
    ├── api/
    ├── hooks/
    ├── i18n/
    └── lib/
```

## 21.2 Server state

TanStack Query.

## 21.3 UI state

Zustand léger :

- sélection ;
- panneaux ;
- préférences ;
- multi-sélection.

Ne pas dupliquer le server state dans Zustand.

## 21.4 Permission bits

API les renvoie sous forme de strings.

Frontend :

```typescript
const permissions = BigInt(raw.permissions);
```

Ne pas convertir en `number`.

## 21.5 Architecture i18n frontend

```text
React component
   ↓ t(key, params)
react-i18next
   ↓
i18next runtime
   ↓
LocalePackBackend
   ↓
GET /api/v1/ui/locales/{locale}/catalog/{version}
```

Le frontend embarque les **quatre packs complets de base EN/FR/DE/ES** comme ressources/chunks versionnés exactement avec son catalogue. Ils garantissent un bootstrap, un login et des écrans d'erreur entièrement localisés même si l'API de locale packs est indisponible. Le backend reste la source de distribution/versionnement des packs runtime et permet d'ajouter toute locale supplémentaire sans rebuild ; un pack runtime compatible peut remplacer atomiquement la ressource embarquée correspondante.

Namespaces recommandés :

```text
common
navigation
actions
contextMenus
structure
permissions
members
bots
translations
campaigns
plans
audit
errors
toasts
tooltips
wizards
accessibility
```

## 21.6 Catalogue de clés typé

La source de vérité des clés UI est extraite/validée en CI.

Les clés doivent être typées lorsque possible afin d'éviter :

```typescript
t('permisisons.mangeRole') // typo silencieuse interdite
```

Le pipeline utilise l'outillage officiel i18next approprié ou un validateur équivalent pour extraction/lint/synchronisation des clés.

## 21.7 Interdiction des chaînes UI hardcodées

Un contrôle ESLint/AST interne doit détecter au minimum les chaînes littérales humainement visibles dans :

- JSX text ;
- `title` ;
- `aria-label` ;
- `placeholder` ;
- définitions de menu ;
- toasts ;
- tooltips ;
- dialogues ;
- actions du `ActionRegistry`.

Des exceptions bornées existent pour identifiants techniques, symboles, noms Discord bruts et données utilisateur.

## 21.8 Activation atomique des locale packs

Une locale n'est publiée que si :

```text
schema valid
AND catalog_version compatible
AND required key coverage == 100%
AND required interpolations valid
AND plural forms valid
```

Le frontend ne mélange pas deux versions de catalogue dans une même session. Un `content_hash` permet cache HTTP/ETag et invalidation.

## 21.9 Choix de locale

La valeur persistée est uniquement un **override explicite**. L'absence d'override signifie `AUTO_BROWSER`.

Résolution :

```text
if user_ui_preferences.ui_locale_override_code != NULL
   AND override pack is ACTIVE + catalog-compatible:
    use explicit override
else:
    # NULL = AUTO_BROWSER ; non-NULL mais indisponible = temporary fallback
    candidates = navigator.languages
    match exact active BCP47 locale
    else match active base language
    else use en bootstrap fallback
```

Avant login, la même résolution est faite sans préférence DB. `Accept-Language` peut fournir le bootstrap serveur mais `navigator.languages` reste la source navigateur la plus précise pour le SPA.

Exemples :

```text
fr-FR,fr,en-US -> fr        si fr-FR absent et fr actif
de-CH,de,en    -> de        si de-CH absent et de actif
ja-JP          -> en        si aucune locale japonaise active
```

Le fallback `en` choisit une **locale complète** ; il ne masque jamais une clé manquante dans une locale active.

`en` est le fallback bootstrap non désactivable par défaut. Une autre locale ne peut le remplacer dans ce rôle qu'après validation explicite de sa couverture complète et de sa compatibilité avec le catalogue courant. Un override devenu indisponible reste mémorisable mais son état est exposé comme `UNAVAILABLE_OVERRIDE`; il n'est jamais utilisé pour rendre une interface partielle.

Le sélecteur UI expose :

```text
Automatique (langue du navigateur)
English
Français
Deutsch
Español
... locales ACTIVE
```

Choisir `Automatique` met `ui_locale_override_code = NULL`. En mode AUTO, `window.languagechange` peut déclencher une nouvelle résolution immédiate.

La locale retournée par le User Object Discord n'est pas utilisée comme défaut produit. Cette locale ne doit jamais être dérivée non plus des rôles/langues Discord du membre.

## 21.10 Emoji et drapeaux

Le rendu doit combiner :

- font stack Unicode ;
- color emoji fallbacks ;
- renderer/icône normalisé pour les drapeaux de sélecteur ;
- éventuellement un renderer Twemoji-compatible pour homogénéiser certains emojis.

Le locale code reste l'identité (`en`, `fr`, `de`, `es`), jamais l'emoji drapeau.

## 21.11 Erreurs et ActionRegistry localisés

Le domaine/backend renvoie des codes stables :

```text
DISCORD_ROLE_HIERARCHY
CAMPAIGN_TARGET_UNAUTHORIZED
TRANSLATION_TOKEN_CORRUPTED
```

Le frontend résout :

```text
error code -> i18n message key -> localized message
```

Le `ActionRegistry` expose `labelKey`, `descriptionKey`, `tooltipKey`, jamais un label humain figé.

---

# 22. Drag & Drop, clic droit et moteur d'actions

## 22.1 Principe

Le Drag & Drop ne réalise jamais directement un appel Discord structurel.

```text
Gesture
↓
Action Resolution
↓
Portable Snapshot si nécessaire
↓
local proposed change / destination plan
↓
preview + preflight
↓
confirm
↓
worker apply
```

## 22.2 Ne pas utiliser le menu contextuel natif du navigateur

Le frontend installe au niveau `document` un listener `contextmenu` en phase de capture :

```typescript
document.addEventListener(
  "contextmenu",
  (event) => event.preventDefault(),
  { capture: true },
);
```

L'implémentation réelle doit être encapsulée dans un composant/service `GlobalContextMenuBoundary` avec nettoyage du listener au démontage.

Règle : **aucune zone du dashboard ne doit laisser apparaître le menu contextuel natif du navigateur**.

Cela inclut :

- texte ;
- inputs ;
- tableaux ;
- arborescences ;
- modales ;
- panneaux vides ;
- overlays de drag ;
- menus applicatifs eux-mêmes.

## 22.3 Pointer Gesture Manager

Pour supporter correctement bouton gauche, bouton droit et Right Drag, utiliser les **Pointer Events** comme source de vérité du geste plutôt que le Drag & Drop HTML5 natif.

Composant recommandé :

```text
PointerGestureManager
├── pointerdown
├── pointermove
├── pointerup
├── pointercancel
├── contextmenu suppression
└── drag threshold / capture
```

État minimal :

```typescript
type PointerDragState = {
  pointerId: number;
  button: 0 | 2;
  source: DragSource;
  startX: number;
  startY: number;
  currentX: number;
  currentY: number;
  dragging: boolean;
  target?: DropTarget;
};
```

Le frontend peut utiliser `dnd-kit` pour les primitives de collision/overlay/tri, mais le support du bouton droit doit être encapsulé dans un **custom sensor / gesture layer** contrôlé par l'application.

## 22.4 Clic droit simple vs Right Drag

Algorithme :

```text
pointerdown button=2
        ↓
movement < threshold
        ↓ pointerup
Context Menu classique

pointerdown button=2
        ↓
movement >= threshold
        ↓
RIGHT_DRAG
        ↓ pointerup sur cible
Drop Context Menu
```

Le `contextmenu` navigateur est empêché dans les deux cas.

## 22.5 Action Registry unique

Les actions ne doivent pas être codées séparément dans chaque menu.

Créer un registre :

```text
ActionRegistry
├── action id
├── label / icon
├── source types
├── target types
├── required dashboard capability
├── required Discord capability
├── same-guild / cross-guild support
├── risk level
├── plan compiler
└── presentation adapters
```

Ce registre alimente :

- menu clic droit ;
- Drop Context Menu ;
- Command Palette ;
- toolbar ;
- menus `...` ;
- raccourcis clavier ;
- actions de multi-sélection.

## 22.6 Drag gauche

Règle par défaut :

```text
même Guild + cible compatible     => MOVE / REORDER proposé
Guild différente                  => COPY / CLONE proposé
bibliothèque personnelle          => EXPORT PORTABLE ARTIFACT
```

Un drag inter-Guild ne supprime jamais la source.

## 22.7 Right Drag

Au `pointerup` sur une cible valide, ouvrir un `DropContextMenu` à la position du curseur.

Exemple inter-Guild :

```text
Copier ici
Cloner structure + paramètres
Cloner avec permissions...
Cloner avec rôles nécessaires...
Clonage maximum compatible...
Créer un modèle dans ma bibliothèque
Prévisualiser uniquement
Annuler
```

Actions linguistiques ajoutées au même `ActionRegistry` :

```text
CREATE_TRANSLATION_VARIANT
LINK_TRANSLATION_VARIANT
ADD_VARIANT_TO_TRANSLATION_GROUP
CLONE_AS_UNLINKED_LANGUAGE_RESOURCE
MOVE_VARIANT_BETWEEN_GROUPS
COMPARE_TRANSLATION_STRUCTURES
CREATE_MULTILINGUAL_TEMPLATE
```

Ces actions ne sont proposées que si la source/cible et les ACL le permettent.

Exemples :

```text
CATEGORY(fr) -> LANGUAGE_TARGET(en)
    => CREATE_TRANSLATION_VARIANT

CATEGORY(en, unlinked) -> CATEGORY(fr, group=TG-42)
    => ADD_VARIANT_TO_TRANSLATION_GROUP

CHANNEL(en) -> CHANNEL(fr)
    => LINK_TRANSLATION_VARIANT
```

Une action `MOVE_VARIANT_BETWEEN_GROUPS` est HIGH RISK et exige un diff explicite. Elle ne fusionne jamais automatiquement les groupes.


Aucune action n'est exécutée avant sélection explicite.

## 22.8 Drop Target Resolver

Chaque cible expose :

```typescript
type DropTarget = {
  guildId?: string;
  resourceType: "GUILD" | "CATEGORY" | "CHANNEL" | "LOGICAL_GROUP" | "USER_LIBRARY";
  resourceId?: string;
  acceptedSourceTypes: string[];
};
```

`DropTargetResolver` calcule ensuite les actions possibles via `ActionRegistry` + ACL + Capability Engine.

## 22.9 Multi-Guild Resource Explorer

Le dashboard doit supporter au moins l'une de ces vues, idéalement les deux :

1. plusieurs Guild trees ouvertes côte à côte ;
2. arbre courant + sélecteur de Guild jouant le rôle de cible de drop.

Exemple :

```text
┌──────────── Guild A ────────────┐    ┌──────────── Guild B ────────────┐
│ 📁 ALPHA                        │    │ 📁 BETA                         │
│   # general                     │───►│   [drop target]                 │
│   # staff                       │    │                                 │
└─────────────────────────────────┘    └─────────────────────────────────┘
```

## 22.10 Cross-Guild DnD pipeline

```text
source resource A
      ↓
authorize_export(A)
      ↓
PortableArtifactBuilder
      ↓
DependencyGraphBuilder
      ↓
right/left drop action chosen
      ↓
authorize_import(B)
      ↓
MappingResolver
      ↓
DestinationPlanCompiler(guild=B)
      ↓
PREFLIGHT / IMPACT / APPLY
```

Le plan ne contient que des mutations destination B.

## 22.11 Option rapide

Un mode « apply immediately for low risk » peut être proposé pour les actions explicitement classées LOW. Il passe toujours par le Plan Engine, conserve l’audit et ne s’applique jamais à un clonage cross-Guild complexe ni à une action destructive sans prévisualisation suffisante.

---

# 23. Local State Cache

Le cache local est un **sous-système de premier rang**, pas une simple optimisation.

Objectifs :

1. servir les lectures dashboard sans appel Discord systématique ;
2. limiter fortement les GET REST ;
3. conserver le dernier état complet connu ;
4. détecter perte/reprise d'accès ;
5. permettre simulation/diff/impact ;
6. absorber les événements Gateway ;
7. protéger le budget rate-limit.

## 23.1 PostgreSQL durable cache

PostgreSQL conserve :

```text
guild_installations
discord_channels_cache
channel_overwrites_cache
discord_roles_cache
member cache minimal selon capabilities
reconcile checkpoints
coverage state
```

Une entrée cache ne signifie pas « actuellement visible ». Elle porte son `access_state` et sa fraîcheur.

## 23.2 Redis hot cache

Redis peut contenir :

- vues chaudes sérialisées ;
- invalidation/version keys ;
- single-flight locks ;
- refresh jobs ;
- rate-limit coordination ;
- pub/sub temps réel.

Redis n'est jamais la seule copie durable du dernier état connu.

## 23.3 Cache read policy

```text
API read
  ↓
Redis hot hit ? -> return
  ↓ non
PostgreSQL cache -> return + hydrate Redis
  ↓
si donnée absente/stale critique -> enqueue/perform targeted refresh selon policy
```

Une requête utilisateur ne doit pas déclencher un `full guild fetch` simplement parce qu'une page a été ouverte.

## 23.4 Gateway write-through

À chaque événement pertinent :

```text
Gateway event
  ↓ normalize
  ↓ tenant guard
  ↓ update durable cache
  ↓ increment resource/guild version
  ↓ invalidate Redis view
  ↓ publish UI event
```

## 23.5 Mutation write-through

Une mutation DID réussie utilise la réponse REST comme nouvelle observation et met à jour le cache immédiatement.

Le Gateway event correspondant peut arriver ensuite ; les consumers doivent le rendre idempotent/dédupliqué.

## 23.6 Freshness model

```text
FRESH
AGING
STALE
UNKNOWN
```

La classification dépend du type de ressource et du dernier événement/refresh, pas d'un TTL universel unique.

## 23.7 Single-flight / request coalescing

Une seule opération de refresh active par clé logique :

```text
refresh:guild:{guild_id}:channels
refresh:guild:{guild_id}:roles
refresh:guild:{guild_id}:member:{user_id}
```

Les autres callers attendent/réutilisent le résultat.

## 23.8 Channel observability state

À compter du comportement Channel Obfuscation Discord :

```text
VISIBLE
OBFUSCATED
ACCESS_LOST
UNKNOWN
DELETED_CONFIRMED
USER_CONFIRMED_DELETED
```

Pour un channel obfusqué, conserver séparément :

- `id`, `type`, `position`, `parent_id` actuellement observables via Gateway ;
- dernière métadonnée complète connue ;
- timestamp du dernier état complet ;
- timestamp de perte d'accès.

Ne jamais écraser un `last_known_name` par la valeur obfusquée `___hidden___`.

De même, le `permission_overwrites` minimal d'un channel obfusqué **ne remplace jamais** le dernier jeu complet d'overwrites connu ; il est stocké comme observation obfusquée séparée si nécessaire.

## 23.9 Coverage state

Par Guild :

```text
coverage_mode = FULL | PARTIAL | DEGRADED
known_channels
visible_channels
obfuscated_channels
last_gateway_event_at
last_full_reconcile_at
last_successful_rest_sync_at
```

Le dashboard expose cette couverture.

## 23.10 View projection : masquer les ressources non actives par défaut

Le cache durable et la projection UI sont deux choses différentes. Le cache peut conserver un objet connu sans que l'arborescence normale l'affiche.

Projection par défaut :

```text
VISIBLE                         -> affiché
UNKNOWN                         -> affichage selon diagnostic/filtre
OBFUSCATED                      -> masqué par défaut
ACCESS_LOST                     -> masqué par défaut
DELETED_CONFIRMED               -> masqué par défaut
USER_CONFIRMED_DELETED          -> masqué par défaut
TOMBSTONE                       -> jamais dans l'arbre normal
```

Préférence user-scopée :

```text
show_hidden_or_deleted_channels = false | true
```

Le `ActionRegistry` expose :

- `SHOW_HIDDEN_OR_DELETED_RESOURCES` ;
- `HIDE_HIDDEN_OR_DELETED_RESOURCES` ;
- `CONFIRM_RESOURCE_DELETED` ;
- `PURGE_RESOURCE_CACHE` ;
- `BULK_PURGE_RESOURCE_CACHE`.

Le libellé UX privilégié est **« Afficher les salons et catégories masqués ou supprimés »**.

## 23.11 Cache purge service

`CachePurgeService` est distinct du Discord mutation adapter. Il ne possède aucune opération de suppression Discord.

Pipeline :

```text
authorize cache.purge
→ resolve selected cached resources
→ preview count + IDs + states
→ optional user confirmation of deletion
→ transaction DB
   - create/upsert tombstones
   - delete detailed cached overwrites
   - delete/compact detailed cached channel metadata
   - append internal audit events
→ invalidate Redis projections
→ publish UI cache events
```

Le bulk purge fonctionne par lots bornés afin de ne pas garder une transaction énorme et doit être idempotent.

---

# 24. Réconciliation et refresh scheduler

## 24.1 Stratégie hybride

```text
Gateway incremental updates     -> principal
Mutation write-through          -> immédiat
Targeted REST refresh           -> à la demande contrôlée
Periodic reconciliation         -> vérification de fond
```

## 24.2 Scheduler adaptatif

Les jobs de reconcile utilisent :

- jitter par Guild ;
- priorité ;
- last-reconcile age ;
- activité récente ;
- état Gateway/resume ;
- plans en attente ;
- drift connu ;
- rate-limit pressure ;
- coverage state.

Pas de cron qui lance toutes les Guilds simultanément.

Politique initiale recommandée, exposée en configuration et ajustable par le scheduler :

```text
Gateway sain / Guild active       -> reconcile structure complet cible <= 6 h
Gateway sain / Guild peu active   -> cible <= 24 h
Gateway gap/non-resume            -> reconcile prioritaire
Plan HIGH/CRITICAL sur cache âgé  -> refresh ciblé avant apply
```

Le scheduler peut ralentir ces objectifs lorsque le governor signale une pression rate-limit. Les membres ne font pas l'objet d'un full-list périodique par défaut.

## 24.3 Gap / reconnect

Si la session Gateway ne peut pas être reprise proprement ou si l'état local risque d'avoir manqué des événements :

```text
mark cache possibly stale
→ enqueue high-priority reconcile
```

## 24.4 Channel Obfuscation

À partir du 16 novembre 2026, `GET Guild Channels` omet les channels non visibles au bot, tandis que le Gateway les fournit sous forme obfusquée.

Conséquences :

- absence HTTP != suppression ;
- le Gateway est nécessaire pour conserver l'existence/position des channels obfusqués ;
- les derniers champs complets connus restent historisés ;
- `CHANNEL_OBFUSCATED` est détecté via son flag, jamais par le nom ;
- lorsqu'un `CHANNEL_UPDATE` complet revient, `access_state` repasse à `VISIBLE`.

## 24.5 Deletion proof

Passer à `DELETED_CONFIRMED` seulement avec une preuve non ambiguë :

- event `CHANNEL_DELETE` pertinent ;
- résultat d'une mutation de suppression DID confirmée ;
- autre mécanisme explicitement validé par l'adapter.

Une omission d'une liste HTTP n'est pas une preuve.

Un utilisateur autorisé peut fournir une confirmation explicite lorsque DID ne peut pas prouver automatiquement la suppression. Cela crée `USER_CONFIRMED_DELETED`, puis éventuellement un tombstone après purge.

## 24.5A Tombstone re-observation

Avant de traiter un `CHANNEL_CREATE` / `CHANNEL_UPDATE` / observation REST complète, vérifier l'existence d'un tombstone `(guild_id, channel_id)`.

Si l'événement prouve l'existence actuelle de l'objet :

```text
tombstone
  -> invalidate
  -> rebuild cache observation
  -> event PURGED_RESOURCE_REOBSERVED
  -> invalidate dependent analyses/plans
```

Le système privilégie toujours la nouvelle observation Discord à une ancienne confirmation manuelle.

## 24.6 Drift events

Créer notamment :

```text
CHANNEL_CREATED_OUTSIDE_PLATFORM
CHANNEL_PERMISSION_CHANGED
CHANNEL_ACCESS_LOST
CHANNEL_ACCESS_RESTORED
CHANNEL_OBFUSCATED
CHANNEL_USER_CONFIRMED_DELETED
CHANNEL_CACHE_PURGED
PURGED_RESOURCE_REOBSERVED
ROLE_MOVED
ROLE_DELETED
CACHE_STALE_AFTER_GATEWAY_GAP
...
```

## 24.7 REST efficiency

Préférer :

- données déjà présentes dans l'événement Gateway ;
- réponses d'opérations Discord ;
- endpoints list/bulk lorsqu'ils évitent N appels unitaires ;
- refresh ciblés ;
- cache de counts lorsque possible.

Éviter les boucles `for channel: GET channel` si une vue agrégée/cachée suffit.

## 24.8 Source acteur

Utiliser l'audit log lorsque disponible pour enrichir l'acteur, sans effectuer un fetch audit log pour chaque petit événement si cela n'apporte pas de valeur suffisante ; préférer batching/cache/récupération ciblée.

---

# 25. Audit interne

Chaque event :

```json
{
  "guild_id": "...",
  "actor_user_id": "...",
  "source": "DASHBOARD|DISCORD|SYSTEM",
  "type": "...",
  "target": {},
  "before": {},
  "after": {},
  "plan_id": "...",
  "request_id": "..."
}
```

Ne pas enregistrer de secrets dans `before/after`.

---

# 26. Sécurité

## 26.1 Secrets

`.env` local uniquement.

Production :

- secret manager ;
- rotation.

Secrets :

```text
DISCORD_BOT_TOKEN
DISCORD_CLIENT_SECRET
DATABASE_URL
REDIS_URL
SESSION_SECRET
ENCRYPTION_KEY
```

## 26.2 Frontend

Seules variables publiques préfixées explicitement.

## 26.3 CORS

Liste stricte des origins.

## 26.4 CSP

Politique de sécurité de contenu en production.

## 26.5 CSRF

OAuth `state`.

Pour mutations basées sur cookie, protéger contre CSRF selon architecture.

## 26.6 SSRF

Pas d'URL arbitraire serveur sans validation.

## 26.7 IDOR

Toutes les ressources vérifiées par tenant.

---

# 27. Chiffrement

Pour tokens OAuth persistés :

```text
plaintext token
↓
AEAD encryption
↓
ciphertext + nonce + key_version
```

Clé hors DB.

Prévoir rotation `key_version`.

---

# 28. Rate limits Discord

Discord applique des rate limits par route/ressource ainsi qu'un budget global partagé par le bot. La stratégie DID repose sur **deux couches complémentaires**, pas sur un remplacement du mécanisme de la bibliothèque Discord.

Architecture :

```text
Plans / targeted refresh / reconcile
              ↓
      DiscordWorkloadGovernor
      - priority queues
      - per-Guild fairness
      - concurrency budgets
      - coalescing/single-flight
      - backpressure
              ↓
         Discord adapter
              ↓
    library protocol limiter
    - buckets / headers / 429
              ↓
           Discord REST
```

## 28.1 DiscordWorkloadGovernor

Le Governor contrôle **quand** DID soumet du travail au client Discord ; le limiteur de la bibliothèque contrôle **quand la requête HTTP peut réellement partir** selon les règles Discord.

Le Governor doit :

- empêcher une parallélisation massive des créations/modifications ;
- imposer des plafonds de concurrence globaux et par classe de tâche ;
- utiliser une file équitable entre Guilds (weighted/fair queue ou équivalent) ;
- empêcher un clone massif d'une Guild de bloquer indéfiniment les autres tenants ;
- retarder la réconciliation de fond lorsque les mutations utilisateur consomment le budget ;
- coalescer les refresh identiques ;
- appliquer du jitter aux tâches périodiques ;
- pouvoir mettre une Guild fautive en cooldown local en cas de série anormale de `403/429` sans arrêter les autres Guilds ;
- publier des métriques de queue et de pression.

## 28.2 Priorités de travail

Ordre indicatif :

```text
P0  continuation d'un plan APPLY déjà engagé / état de sécurité
P1  verify post-apply / reconcile UNKNOWN_OUTCOME
P2  targeted refresh requis par preflight ou action utilisateur
P3  refresh utilisateur explicite non critique
P4  reconcile périodique / audit enrichissement
```

La priorité ne doit pas créer de starvation : une politique de vieillissement des jobs remonte progressivement les tâches anciennes.

## 28.3 Limiteur protocolaire

Si `discord.py` (ou la bibliothèque retenue) gère les buckets et `429`, DID s'appuie sur ce comportement au lieu de dupliquer un second algorithme de buckets couplé aux détails internes de la librairie.

Si un adapter REST direct est introduit, il devient responsable de respecter les headers et `retry_after` documentés par Discord.

## 28.4 Cache comme première défense

Le meilleur appel Discord est celui qui n'est pas nécessaire. Les vues du dashboard lisent le cache local ; une lecture `AGING` peut être servie immédiatement avec un refresh asynchrone coalescé (**stale-while-revalidate**). Les refresh synchrones sont réservés aux cache misses réellement nécessaires et aux décisions critiques dont la fraîcheur doit être garantie.

Métriques minimales :

```text
discord_rest_requests_total{route,status}
discord_rate_limit_wait_seconds{bucket}
discord_429_total{scope}
discord_invalid_requests_10m
cache_hit_ratio{resource_type}
cache_age_seconds{resource_type}
rest_queue_depth
reconcile_requests_total
singleflight_saved_requests_total
rest_queue_wait_seconds{priority}
rest_requests_by_guild_total
workload_governor_throttled_total{reason}
```

Le système doit alerter sur une hausse anormale de `403/429` avant qu'elle ne devienne un risque de restriction Cloudflare.

---

# 29. Erreurs Discord

Mapper :

```text
403 Missing Permissions
403 Missing Access
404 Unknown Channel
429 Rate Limited
400 Invalid Form Body
...
```

vers des erreurs de domaine.

Exemple :

```text
DiscordMissingPermission
DiscordHierarchyViolation
DiscordResourceNotFound
DiscordRateLimited
DiscordValidationFailure
```

---

# 30. Limites de capacité

Centraliser :

```python
class DiscordCapabilities:
    max_channels_per_guild
    max_roles_per_guild
    max_channels_per_category
    max_permission_overwrites_per_channel
```

Valeurs de référence actuelles :

```text
500 channels/guild
250 roles/guild
1000 permission overwrites/channel
50 child channels/category
```

Ne pas définir `max_categories_per_guild = 50` sans source officielle distincte ; les catégories font partie du budget global de channels.

Ne pas dupliquer ces nombres dans l'UI.

Exposer via :

```text
GET /api/v1/capabilities
```

---

# 31. Sharding et montée en charge

## 31.1 Topologie de runtime

L'architecture supporte un ou plusieurs shards/processus Gateway selon la charge. Aucun état tenant critique ne dépend d'un nombre fixe de processus.

## 31.2 Invariant d'état partagé

Aucun état de tenant important ne doit vivre uniquement en mémoire du bot.

## 31.3 Sharding

Lorsque le nombre de guildes le justifie :

```text
Bot Shard 0
Bot Shard 1
Bot Shard 2
...
      ↓
Redis / PostgreSQL commun
```

discord.py dispose d'un client sharded ; l'architecture doit rester compatible.

## 31.4 Routing

Le Discord I/O Worker n'a pas besoin d'être sur le même shard que l'événement Gateway pour appeler Discord REST avec le bot token. Les shards publient des intents/jobs ; ils ne doivent pas chacun recréer un limiteur REST indépendant.

---

# 32. Scalabilité API

API stateless autant que possible.

Sessions :

- Redis.

WebSockets :

- pub/sub tenant-aware.

Plusieurs instances API derrière reverse proxy possibles.

---

# 33. Observabilité

## 33.1 Logs JSON

Exemple :

```json
{
  "level": "INFO",
  "event": "plan_operation_applied",
  "guild_id": "...",
  "plan_id": "...",
  "operation_id": "...",
  "duration_ms": 183
}
```

## 33.2 Métriques

- guilds active ;
- gateway latency ;
- reconnects ;
- Discord API errors ;
- 429 ;
- job queue depth ;
- plan duration ;
- partial failures ;
- reconcile drift count ;
- HTTP latency.

## 33.3 Tracing

OpenTelemetry est recommandé pour la production afin d’unifier traces, métriques et corrélation inter-processus.

---

# 34. Tests

## 34.1 Unit tests

Pytest.

Modules prioritaires :

- permissions ;
- tenancy ;
- authorization ;
- planner ;
- risk engine ;
- Discord payload mapping.

## 34.2 Integration tests

PostgreSQL + Redis réels via Docker.

## 34.3 Contract tests Discord adapter

Mock HTTP contrôlé.

## 34.4 Guild sandbox

Créer au moins deux vrais serveurs Discord de test :

```text
DID-SANDBOX-A
DID-SANDBOX-B
```

Objectif : vérifier l'isolation et les comportements réels.

## 34.5 E2E frontend

Playwright.

Scénarios :

- login ;
- select guild ;
- plan ;
- validation ;
- apply ;
- websocket update.

---

# 35. Tests multi-tenant obligatoires

## 35.1 Tests cross-Guild autorisés

Le test de sécurité doit couvrir à la fois le refus cross-tenant et le transfert explicitement autorisé.

Cas minimum :

1. User U admin A, pas autorisé B → export A possible, import B interdit ;
2. User U autorisé A+B → transfert A→B possible ;
3. User U autorisé B seulement → aucune lecture A ;
4. artifact appartenant à User U inaccessible à User V ;
5. plan destination B ne contient aucune opération ciblant A ;
6. révocation d'accès B avant APPLY → plan refusé ;
7. bot absent ou capacités insuffisantes sur B → preflight bloqué/dégradé ;
8. source supprimée après création de l'artifact → import toujours basé sur l'artifact immutable, sans lecture implicite de A ;
9. mapping ambigu → APPLY interdit tant que non résolu.

## 35.2 Isolation endpoint par endpoint

Chaque endpoint tenant-scopé doit avoir un test :

```text
User A + Guild A resource -> 200
User A + Guild B resource -> 403/404
User B + Guild B resource -> 200
```

Même chose pour :

- WebSocket ;
- jobs ;
- repositories ;
- templates ;
- audit ;
- snapshots.

---


## 35.3 Tests de cloisonnement Translation Group

Dans une même Guild :

```text
TG-A = FR/EN
TG-B = FR/EN
```

Un changement de `TG-A` ne doit jamais :

- ajouter une variante à `TG-B` ;
- créer une route dans `TG-B` ;
- modifier ses scopes ;
- réutiliser ses Channel Groups par erreur.

## 35.4 Tests Scope × Language

Cas minimum :

```text
Paul  : ALPHA + FR
Julie : ALPHA + FR + EN
Marc  : BETA + FR
```

Vérifier que les rôles et la visibilité effectifs respectent exactement les intersections attendues.

## 35.5 Tests Translation Provider

Chaque adapter doit passer des contract tests :

- capabilities ;
- validate ;
- apply idempotent ;
- retry ;
- provider unavailable ;
- route unsupported ;
- loop-prevention contract si messages traduits.

# 36. Développement Windows 11

## 36.1 Pré-requis

- Git for Windows / Git Bash ;
- VS Code ;
- Python 3.13 ;
- Node.js LTS compatible avec Vite retenu ;
- Docker Desktop ;
- WSL2 recommandé pour Docker ;
- PostgreSQL/Redis via Compose.

## 36.2 Clonage

```bash
git clone <repo>
cd discord-infra-designer
```

## 36.3 Python

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
pip install -e "backend[dev]"
```

Sous Git Bash, le chemin d'activation est généralement :

```bash
source .venv/Scripts/activate
```

## 36.4 Infrastructure

```bash
docker compose up -d postgres redis
```

## 36.5 Migrations

```bash
alembic upgrade head
```

ou script wrapper :

```bash
./scripts/db-upgrade.sh
```

## 36.6 Frontend

```bash
cd frontend
npm install
npm run dev
```

## 36.7 API

```bash
uvicorn did.api.main:app --reload --port 8000
```

## 36.8 Bot

```bash
python -m did.bot
```

## 36.9 Worker

```bash
python -m did.worker
```

---

# 37. Fichier .env.example

```dotenv
APP_ENV=development
APP_BASE_URL=http://localhost:5173
API_BASE_URL=http://localhost:8000

DISCORD_CLIENT_ID=
DISCORD_CLIENT_SECRET=
DISCORD_BOT_TOKEN=
DISCORD_REDIRECT_URI=http://localhost:8000/auth/discord/callback

DATABASE_URL=postgresql+asyncpg://did:did@localhost:5432/did
REDIS_URL=redis://localhost:6379/0

SESSION_SECRET=
TOKEN_ENCRYPTION_KEY=
LOG_LEVEL=INFO
```

Ne jamais mettre de vraies valeurs dans `.env.example`.

---

# 38. Qualité Python

Outils recommandés :

- Ruff ;
- mypy ou Pyright ;
- pytest ;
- pytest-asyncio ;
- coverage.

`pyproject.toml` centralise.

Règles :

- type hints obligatoires sur le code métier ;
- pas de `Any` gratuit ;
- async cohérent ;
- pas d'appels blocking dans l'event loop.

---

# 39. Qualité frontend

- TypeScript `strict: true` ;
- ESLint ;
- Prettier si retenu ;
- Vitest ;
- Testing Library ;
- Playwright.

---

# 40. Git

## 40.1 Branches

Suggestion simple :

```text
main
feature/...
fix/...
```

## 40.2 Commits

Conventional Commits recommandés :

```text
feat(plans): add category duplication planner
fix(tenancy): reject cross-guild plan lookup
test(permissions): cover administrator bypass
```

## 40.3 Hooks

Pre-commit optionnel :

- ruff ;
- mypy subset ;
- frontend lint ;
- tests rapides.

---

# 41. CI

Pipeline minimum :

```text
backend lint
backend typecheck
backend unit tests
frontend lint
frontend typecheck
frontend unit tests
build frontend
DB migration smoke test
security scan dependencies
```

E2E sur environnement dédié selon secrets disponibles.

---

# 42. Production

## 42.1 Containers

```text
frontend
api
bot
worker
postgres
redis
reverse-proxy
```

PostgreSQL/Redis managés sont recommandés en production lorsque l’environnement d’hébergement le permet.

## 42.2 Bot

Un seul replica bot avant sharding explicite.

Ne pas lancer deux copies identiques du bot Gateway sans stratégie de sharding/session.

## 42.3 API

Plusieurs replicas possibles.

## 42.4 Worker

Plusieurs workers possibles, mais lock par guild pour mutations structurelles.

---

# 43. Sauvegardes

Sauvegarder :

- PostgreSQL ;
- configuration ;
- encryption key via secret manager séparé.

Redis n'est pas le backup principal.

---

# 44. Désinstallation d'une guild

Flow :

```text
Guild Remove
↓
installation = UNINSTALLED
↓
revoke active jobs
↓
invalidate live sessions tenant
↓
start retention timer
↓
purge selon politique
```

Le retour ultérieur du bot doit être traité explicitement :

- réactivation ;
- re-import ;
- nouveaux diffs.

---

# 45. Concurrence

Cas :

- admin A crée un plan ;
- admin B modifie directement Discord ;
- admin A applique.

Solution :

```text
base version != current version
→ plan STALE
→ recompute required
```

Pas de last-write-wins silencieux.

---

# 46. Suppressions

## 46.1 Soft delete interne

Pour :

- templates ;
- logical groups ;
- ACL.

## 46.2 Discord delete

Action réelle et potentiellement irréversible.

Double confirmation pour risque HIGH/CRITICAL.

---

# 47. Architecture des snapshots

Format versionné :

```json
{
  "schema_version": 1,
  "guild_id": "...",
  "captured_at": "...",
  "roles": [],
  "channels": [],
  "overwrites": [],
  "logical_groups": []
}
```

Compression possible au-delà d'une taille seuil.

---

# 48. Permission explain trace

Exemple de modèle :

```json
{
  "permission": "VIEW_CHANNEL",
  "result": true,
  "trace": [
    {
      "step": "BASE_EVERYONE",
      "value": false
    },
    {
      "step": "ROLE_COMBINATION",
      "role_ids": ["..."],
      "value": true
    },
    {
      "step": "CHANNEL_ROLE_OVERWRITE",
      "target_id": "...",
      "value": true
    }
  ]
}
```

Cette trace alimente :

- « Pourquoi ? » ;
- UI debug ;
- tests.

---

# 49. API de simulation

```text
POST /api/v1/guilds/{guild_id}/simulate
```

Input :

```json
{
  "member_id": "123",
  "proposed_changes": []
}
```

Output :

```json
{
  "visible_channels_before": [],
  "visible_channels_after": [],
  "gained": [],
  "lost": [],
  "permission_changes": []
}
```

---

# 49A. Moteur de clonage profond et portabilité

Le clonage est un sous-système applicatif partagé par duplication, copier/coller, DnD inter-Guild, bibliothèque et clone de configuration.

## 49A.1 Modules

```text
CloneEngine
├── PortableArtifactBuilder
├── DependencyGraphBuilder
├── SymbolicReferenceEncoder
├── MappingResolver
├── CapabilityAnalyzer
├── CloneModeCompiler
├── DestinationPlanCompiler
├── CloneReportBuilder
└── PortableArtifactStore
```

## 49A.2 PortableArtifactBuilder

Entrée : ressources source déjà autorisées.

Sortie : snapshot immutable et portable :

```json
{
  "schema_version": 1,
  "artifact_type": "CATEGORY",
  "source": {
    "guild_id": "...",
    "resource_id": "..."
  },
  "resources": [],
  "dependencies": [],
  "symbol_table": {},
  "capability_requirements": []
}
```

Les IDs source servent uniquement à la provenance et au diagnostic. Toute référence portable entre objets passe par une clé symbolique.

## 49A.3 DependencyGraphBuilder

Nœuds possibles :

- CATEGORY ;
- CHANNEL ;
- ROLE ;
- PERMISSION_OVERWRITE ;
- BOT_REFERENCE ;
- WEBHOOK_REFERENCE ;
- LOGICAL_GROUP ;
- PLATFORM_AUTOMATION ;
- PLATFORM_POLICY ;
- ONBOARDING_RESOURCE lorsque supporté.

Arêtes :

```text
CHANNEL --parent--> CATEGORY
OVERWRITE --target--> ROLE
CHANNEL --bot dependency--> BOT_REFERENCE
LOGICAL_GROUP --contains--> CHANNEL/ROLE/CATEGORY
AUTOMATION --targets--> CHANNEL/ROLE
```

## 49A.4 MappingResolver

Résolution destination :

```text
symbolic ref
   ├── MAP_EXISTING
   ├── CREATE_NEW
   ├── SKIP
   ├── DEFER
   └── IMPOSSIBLE
```

Les correspondances automatiques peuvent proposer des résultats, mais un mapping ambigu n'est jamais appliqué silencieusement.

## 49A.5 Clone modes

```text
COPY_AS_NEW
MERGE
RECONCILE
MAXIMUM_COMPATIBLE
```

`RECONCILE` produit un diff source portable / destination et compile les mutations nécessaires. Les suppressions restent explicitement confirmées.

## 49A.6 Clone complet de configuration

Le clone de Guild est un clone de **configuration**, pas une duplication d'identité Discord.

Jamais considérer clonables à l'identique :

- IDs Discord ;
- membres ;
- historiques de messages ;
- audit log ;
- identité réelle des bots tiers ;
- tokens de webhook.

Les éléments liés aux bots/webhooks sont traités par mapping, présence destination, ou recréation lorsque l'API et les droits le permettent.

## 49A.7 Destination-only plan invariant

Même pour A → B :

```text
READ PHASE          PORTABLE PHASE          MUTATION PHASE
Guild A       →     Artifact user-owned  →  Plan(guild_id = B)
```

Le Plan Engine n'exécute aucune mutation sur A lors d'un clone vers B.

---

# 49B. Architecture multilingue et Translation Providers

## 49B.1 Objectifs

Le sous-système doit résoudre simultanément :

1. déclaration de la langue d'une catégorie/salon ;
2. liaison explicite de variantes linguistiques ;
3. clonage d'une structure dans N langues ;
4. visibilité globale ou `Scope AND Language` ;
5. attribution/retrait automatique des rôles techniques ;
6. configuration d'un bot/provider de traduction ;
7. synchronisation structurelle et détection de drift ;
8. isolation stricte entre plusieurs Translation Groups d'une même Guild ;
9. portabilité inter-Guild sans liaison live implicite.

## 49B.2 Modules

```text
TranslationDomain
├── LanguageProfileService
├── TranslationTopologyService
├── TranslationGroupRepository
├── TranslationLinkResolver
├── TranslationRouteCompiler
├── LanguageVisibilityCompiler
├── ScopeMembershipResolver
├── ScopeLanguageRoleResolver
├── TechnicalRoleReconciler
├── TranslationDriftDetector
├── TranslationCloneExpander
├── TranslationProviderRegistry
├── TranslationProviderCoordinator
└── TranslationAuditService
```

## 49B.3 Invariant d'identité

La relation de traduction est définie uniquement par les IDs internes :

```text
translation_group_id
translation_channel_group_id
```

Jamais par :

- langue ;
- nom de catégorie ;
- nom de salon ;
- position ;
- préfixe ;
- rôle linguistique.

Cela empêche :

```text
TG-GUIDES(FR,EN) + TG-NEWS(FR,EN)
```

de devenir accidentellement un réseau unique à quatre ressources.

## 49B.4 Modèle de topologie

```text
TranslationGroup
│
├── CategoryVariant[FR]
├── CategoryVariant[EN]
├── CategoryVariant[DE]
│
├── ChannelGroup GENERAL
│   ├── ChannelVariant[FR]
│   ├── ChannelVariant[EN]
│   └── ChannelVariant[DE]
│
└── ChannelGroup HELP
    ├── ChannelVariant[FR]
    ├── ChannelVariant[EN]
    └── ChannelVariant[DE]
```

Pour `CHANNEL_SET`, les CategoryVariants sont absentes.

## 49B.5 Language inheritance resolver

Résolution :

```text
channel.explicit_language != null
    => explicit language
else if parent_category.language != null
    => inherited language
else
    => UNSPECIFIED
```

L'héritage linguistique ne doit pas être confondu avec `Permission Syncing` Discord.

## 49B.6 Routing modes

### HUB_AND_SPOKE

```text
hub FR
├── EN
├── DE
├── ES
└── IT
```

Le `TranslationRouteCompiler` génère les routes supportées par le provider.

### FULL_MESH

Toutes les paires nécessaires sont générées uniquement si le provider le supporte.

### CUSTOM

Les routes viennent directement de `translation_routes`.

## 49B.7 Translation Provider Port

Le domaine dépend d'un port, pas du bot existant. Le port doit aussi représenter le fait qu'un provider peut **ne pas être configurable automatiquement**.

```python
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

class ProviderConfigurationMode(str, Enum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL_CONFIGURATION_REQUIRED = "MANUAL_CONFIGURATION_REQUIRED"
    OBSERVATION_ONLY = "OBSERVATION_ONLY"

@dataclass(frozen=True)
class TranslationProviderCapabilities:
    supports_hub_and_spoke: bool
    supports_full_mesh: bool
    supports_custom_routes: bool
    supports_message_edits: bool
    supports_message_deletes: bool
    supports_attachments: bool
    supports_embeds: bool
    supports_threads: bool
    max_languages_per_group: int | None
    configuration_mode: ProviderConfigurationMode

class TranslationProvider(Protocol):
    async def capabilities(self, guild_id: int) -> TranslationProviderCapabilities: ...
    async def validate_group(self, desired_group) -> list[dict]: ...
    async def prepare_configuration(self, desired_group) -> dict: ...
    async def observe_health(self, guild_id: int) -> dict: ...
```

Pour un provider `AUTOMATIC`, un adapter concret **peut** exposer en plus des opérations d'apply/reconcile idempotentes. Elles ne font pas partie du minimum imposé au bot existant.

Règles obligatoires :

- capabilities explicites côté adapter ;
- erreurs typées ;
- aucun token Discord tiers exposé au frontend ;
- validation avant de considérer la traduction READY ;
- aucun changement du bot tiers exigé par l'abstraction.

## 49B.8 Adapter du bot de traduction existant

### Décision : zéro modification obligatoire du bot existant

Le premier adapter cible le comportement **actuel** du bot de traduction.

Il ne faut pas demander au bot existant :

- d'ajouter une API au bot ;
- de modifier son schéma DB ;
- de modifier ses événements internes ;
- de partager son token Discord.

Le travail initial de l'adapter est donc :

1. inventorier les surfaces existantes réellement utilisables sans modification ;
2. déclarer les capacités connues/testées ;
3. permettre à DID de construire la topologie Discord ;
4. si aucune configuration automatique sûre n'est disponible, retourner `MANUAL_CONFIGURATION_REQUIRED` avec la configuration attendue ;
5. observer si possible la présence et les permissions Discord du bot.

Éviter :

- piloter une UI de manière fragile ;
- dépendre de noms de salons comme seules identités ;
- partager le token Discord du bot de traduction ;
- écrire directement dans des tables internes non documentées.

## 49B.9 Provider Registry

```text
TranslationProviderRegistry
├── existing_translation_bot
├── mock_translation_provider       # tests
└── provider_x
```

Chaque binding est guild-scopé.

Un même tenant peut éventuellement avoir plusieurs providers, mais un Translation Group doit savoir explicitement quel provider le gère.

## 49B.10 Language Visibility Compiler

Entrée :

```text
resource language
visibility policy
visibility scope
member scope memberships
member language preferences
existing scope-language role bindings
```

Sortie :

```text
roles_to_reuse
roles_to_create
member_role_assignments
category/channel overwrites
warnings
capacity impact
```

## 49B.11 Pourquoi le moteur doit compiler l'intersection

Discord applique les overwrites des rôles par agrégation des denies puis des allows de rôles. Il n'existe pas d'opérateur `AND` entre `@ALPHA` et `@LANG_FR`.

Le moteur doit donc matérialiser l'intersection quand elle est nécessaire :

```text
SCOPE(ALPHA) × LANGUAGE(FR) -> ROLE(DID_ALPHA_FR)
```

La logique ne doit pas être réimplémentée dans React.

## 49B.12 ScopeLanguageRoleResolver

Pseudo-algorithme :

```python
def resolve_scope_language_role(guild_id, scope_id, language_id):
    binding = repo.find_binding(guild_id, scope_id, language_id)
    if binding and discord_role_is_usable(binding.discord_role_id):
        return Reuse(binding)

    capacity.ensure_role_budget(1)
    role_name = naming.build_technical_role_name(scope_id, language_id)
    return CreateTechnicalRole(
        name=role_name,
        permissions=0,
        hoist=False,
        mentionable=False,
    )
```

Le nom est une présentation ; l'identité durable est le binding DB.

## 49B.13 Technical Role Reconciler

Responsabilités :

- détecter rôle supprimé ;
- détecter rôle déplacé au-dessus du bot ;
- détecter permissions Guild ajoutées manuellement ;
- détecter `hoist`/`mentionable` modifiés ;
- calculer membres manquants/excédentaires ;
- proposer `RECONCILE`, `ADOPT`, `DETACH`.

Ne jamais reprendre silencieusement une permission dangereuse ajoutée manuellement.

## 49B.14 Member Language Assignment

État désiré :

```text
member scopes: ALPHA, PROJECT_X
visible languages: FR, EN
```

Bindings nécessaires :

```text
ALPHA × FR
ALPHA × EN
PROJECT_X × FR
PROJECT_X × EN
```

Les bindings ne sont créés que si une ressource/politique du scope les utilise réellement, afin d'éviter une explosion de rôles.

Le `MemberLanguageRoleReconciler` compare ensuite l'état désiré aux rôles Discord réels.

## 49B.14A Discord Onboarding bridge

Le choix de langue peut provenir :

```text
Dashboard DID
Application command / interaction
Discord Onboarding role selection
Admin assignment
Import
```

Normaliser toutes ces sources vers `member_visible_languages`, puis exécuter le même `MemberLanguageRoleReconciler`.

Si Discord Onboarding attribue `@LANG_FR`, l'événement de rôle peut être utilisé comme signal de préférence, mais l'accès `ALPHA × FR` n'est accordé que si le membre possède déjà le scope ALPHA selon le domaine.

## 49B.15 Lazy technical role creation

Décision : création **lazy**.

Ne pas créer automatiquement toutes les combinaisons :

```text
20 scopes × 10 langues = 200 rôles
```

Créer seulement une combinaison `scope × language` lorsqu'une politique de visibilité active l'exige.

Cela est essentiel avec la limite Discord actuelle de 250 rôles par Guild.

## 49B.16 Overwrite strategy

Priorité :

```text
1. category-level overwrite + synced child channels
2. channel-level role overwrite pour exception/mixed category
3. member-specific overwrite uniquement cas explicite exceptionnel
```

Le Capacity Engine doit connaître la limite actuelle de 1000 overwrites par salon.

## 49B.16A Translation Provider Access Compiler

Si le provider est un bot Discord, calculer ses permissions effectives avec le même Permission Engine central.

Entrée :

```text
provider Discord user id
provider roles
category/channel overwrites
desired provider features
```

Sortie :

```text
missing_permissions
minimal_overwrites_to_add
unfixable_constraints
administrator_warning
```

Principe de moindre privilège :

```text
TRANSLATE_TEXT
  -> VIEW_CHANNEL + READ_MESSAGE_HISTORY + SEND_MESSAGES

TRANSLATE_THREADS
  -> + SEND_MESSAGES_IN_THREADS

COPY_ATTACHMENTS
  -> + ATTACH_FILES

RICH_OUTPUT
  -> + EMBED_LINKS
```

La liste exacte est compilée à partir des capacités réellement utilisées par le provider ; ne pas accorder de permissions inutiles.

Si le provider possède déjà `ADMINISTRATOR`, afficher un warning de sécurité car les overwrites de salons ne peuvent plus l'isoler.

## 49B.17 Multilingual Clone Expander

Entrée : Portable Artifact d'une catégorie/salon + langues cibles.

Sortie : graph logique étendu :

```text
SOURCE_CATEGORY
  ↓
VARIANT[EN]
VARIANT[DE]
VARIANT[ES]
  ↓
CHANNEL_GROUP mappings
  ↓
visibility bindings
  ↓
provider routes
```

Toutes les nouvelles ressources utilisent des symboles temporaires avant création Discord :

```text
CATEGORY:GUIDES:EN
CHANNEL:GENERAL:EN
ROLE:SCOPE_ALPHA:EN
```

Les IDs Discord réels ne sont injectés qu'après succès des opérations de création correspondantes.

## 49B.18 Linking existing resources

Pour lier deux catégories existantes :

1. authorize read/manage ;
2. vérifier qu'elles ne sont pas déjà liées de manière incompatible ;
3. comparer structures ;
4. proposer mapping de salons ;
5. créer group/channel-group records dans un plan ;
6. configurer visibilité si demandé ;
7. valider provider ;
8. APPLY.

Un mapping automatique est un **suggestion score**, jamais une autorité.

## 49B.19 Translation Drift Detector

Détecte :

```text
MISSING_VARIANT
EXTRA_VARIANT
CHANNEL_MAPPING_MISSING
LANGUAGE_METADATA_DRIFT
VISIBILITY_ROLE_DRIFT
OVERWRITE_DRIFT
PROVIDER_ROUTE_DRIFT
PROVIDER_UNAVAILABLE
```

Chaque drift doit avoir :

- sévérité ;
- source observée ;
- état désiré ;
- actions correctives possibles.

## 49B.20 Gateway integration

Les événements Gateway de création/update/delete de salons/rôles invalident les Translation Groups concernés via les index DB :

```text
discord_channel_id -> translation variant

discord_role_id -> scope-language binding
```

Aucun scan global de tous les groups ne doit être nécessaire à chaque événement.

## 49B.21 Message translation event ownership

Si le Translation Provider est un bot séparé, **DID n'est pas propriétaire du pipeline MESSAGE_CREATE** de traduction.

DID peut :

- configurer la topologie ;
- recevoir des status/webhooks/events du provider ;
- afficher sa santé ;
- conserver un mapping message optionnel.

DID ne demande pas `MESSAGE_CONTENT` pour le simple fait d'exister avec un provider.

## 49B.22 Loop prevention contract

Le provider doit documenter comment il évite :

```text
FR original
 -> EN translated bot message
 -> detected as new original
 -> FR translated again
 -> infinite loop
```

Tests contractuels obligatoires pour chaque adapter.

## 49B.23 Plan phases

Un plan multilingue complexe doit distinguer les phases :

```text
PHASE A - DISCORD PREREQUISITES
  roles / categories / channels / overwrites

PHASE B - DID TOPOLOGY
  groups / variants / routes / bindings

PHASE C - PROVIDER CONFIGURATION
  validate adapter capabilities
  AUTOMATIC -> apply via adapter si une interface existante sûre le permet
  MANUAL_CONFIGURATION_REQUIRED -> produire les instructions/config attendue

PHASE D - VERIFY
  Discord reconcile + provider health/validation observable
```

La persistance des bindings de l'étape DID Topology doit être transactionnelle par rapport à l'état local, mais elle ne rend pas les appels Discord atomiques.

## 49B.24 Partial failure / provider pending

Deux situations distinctes :

### Échec d'une configuration automatique réellement supportée

```text
Discord resources: CREATED
DID topology:       ACTIVE_LOCAL
Provider:           ERROR
Translation group:  DEGRADED
Plan:               PARTIALLY_APPLIED
```

### Provider non configurable automatiquement

```text
Discord resources: CREATED
DID topology:       ACTIVE_LOCAL
Provider:           MANUAL_CONFIGURATION_REQUIRED
Translation group:  PROVIDER_PENDING
Plan:               APPLIED_WITH_PENDING_PROVIDER
```

Ce second cas n'est pas une panne : c'est un état prévu tant que le bot existant n'offre pas une surface d'automatisation que nous souhaitons utiliser sans le modifier.

Actions possibles :

- fournir/afficher la configuration attendue ;
- valider manuellement quand la liaison externe est faite ;
- retry uniquement si l'adapter supporte réellement l'automatisation ;
- désactiver traduction en conservant structure ;
- rollback explicite par nouveau plan si l'utilisateur le demande.

Aucune suppression automatique de ressources Discord créées.

## 49B.25 Portable Artifact multilingue

Extension de schéma :

```json
{
  "multilingual": {
    "languages": ["fr", "en", "de"],
    "translation_groups": [],
    "channel_groups": [],
    "visibility_scopes": [],
    "scope_language_requirements": [],
    "routing": {
      "mode": "HUB_AND_SPOKE",
      "hub": "fr"
    },
    "provider_requirement": {
      "capabilities": ["supports_hub_and_spoke"]
    }
  }
}
```

Interdits :

- provider secret ;
- bot token ;
- IDs destination présumés ;
- lien live vers source.

## 49B.26 Cross-Guild clone

```text
Guild A TG-42
     ↓ export
Portable multilingual artifact
     ↓ import
Guild B TG-NEW-17
```

`TG-NEW-17` est indépendant.

Le plan destination remappe/crée :

- languages ;
- scopes ;
- technical roles ;
- categories ;
- channels ;
- provider binding.

## 49B.27 Frontend Translation Workspace

Écran recommandé :

```text
┌──────────────────────┬──────────────────────────────────────┬──────────────────────┐
│ GROUPS               │ TOPOLOGY                             │ PROPERTIES           │
│                      │                                      │                      │
│ ▼ GUIDES             │ FR ─────► EN                         │ Group: TG-42         │
│   FR ✓               │  │       DE                         │ Scope: ALPHA         │
│   EN ✓               │  └──────► ES                         │ Provider: Translator │
│   DE ✓               │                                      │ Mode: HUB/SPOKE      │
│                      │ GENERAL: FR EN DE ES                  │ Drift: 0             │
│ ▼ NEWS               │ HELP:    FR EN DE ES                  │                      │
└──────────────────────┴──────────────────────────────────────┴──────────────────────┘
```

Actions DnD et contextuelles utilisent le `ActionRegistry` global.

## 49B.28 Frontend language targets

Créer des Drop Targets virtuels :

```text
LANGUAGE_TARGET(fr)
LANGUAGE_TARGET(en)
TRANSLATION_GROUP_TARGET(TG-42)
```

Ils n'existent pas dans Discord ; ce sont des cibles UX compilant des plans réels.

## 49B.29 Search index

Indexer :

```text
language_code
translation_group_id
translation_group_name
translation_channel_group_id
visibility_scope_key
provider_status
drift_type
```

## 49B.30 Security boundaries

Toutes les entités multilingues possèdent `guild_id`.

Aucun `group_id` seul ne suffit pour charger une ressource :

```text
get_translation_group(guild_id, group_id)
```

RLS doit s'appliquer aux tables multilingues tenant-scopées.

## 49B.31 Tests unitaires minimum

- groupes FR/EN indépendants ;
- héritage catégorie -> salon ;
- override langue salon ;
- route HUB_AND_SPOKE ;
- route CUSTOM ;
- compilation `GLOBAL × FR` ;
- compilation `ALPHA × FR` ;
- réutilisation rôle existant ;
- limite de rôles ;
- limite d'overwrites ;
- rôle technique supprimé ;
- provider capability mismatch ;
- provider Discord absent ;
- provider sans VIEW_CHANNEL/SEND_MESSAGES ;
- provider possédant ADMINISTRATOR (warning) ;
- provider partial failure ;
- clone inter-Guild ;
- absence de lien live après clone.

## 49B.32 Tests d'intégration sandbox

Au minimum deux Guilds et deux Translation Groups dans une même Guild :

```text
Guild A
  TG-GUIDES FR/EN
  TG-NEWS   FR/EN

Guild B
  destination clone
```

Vérifier :

- aucun événement de GUIDES n'affecte NEWS ;
- Alpha/FR n'autorise pas Beta/FR ;
- membre FR+EN obtient les deux rôles nécessaires ;
- clone A -> B recrée une topologie indépendante ;
- suppression d'une variante ne supprime pas les autres.

---

# 49C. Message & Campaign Engine

## 49C.1 Objectifs

Le Campaign Engine doit permettre une publication contrôlée vers plusieurs Guilds/salons/langues sans transformer les tenants en fédération permanente.

Il réutilise les briques existantes :

```text
Authorization
Target Resolver
Scheduler / Event Bus
Local Cache
Translation Topology
Discord I/O Worker
Rate Limit Governor
Audit / Outbox
```

## 49C.2 Modules

```text
CampaignDomain
├── CampaignService
├── CampaignAuthorizationService
├── CampaignTargetResolver
├── CampaignScheduleCompiler
├── CampaignEventTriggerEvaluator
├── CampaignOccurrenceService
├── CampaignDeliveryCompiler
├── CampaignPreviewService
├── MessageTemplateRenderer
├── AllowedMentionsCompiler
├── DiscordSafeMessageParser
├── MessageTranslationCoordinator
├── TranslationGlossaryService
├── TechnicalIntegrityValidator
├── ApprovedVariantService
├── MessageDeliveryRepository
└── CampaignAuditService
```

## 49C.3 Séparation Control Plane / Tenant deliveries

Une campagne multi-Guild est user-scopée :

```text
User Control Plane
     Campaign C
       /   |   \
      /    |    \
Guild A  Guild B Guild C
Delivery Delivery Delivery
 tenant   tenant  tenant
 scoped   scoped  scoped
```

Le header campagne ne permet jamais de charger directement des données d'une Guild sans autorisation de cette Guild.

Chaque destination est résolue et revalidée indépendamment à l'exécution.

## 49C.4 Target Resolver

Entrée :

```text
selector_type
selector_json
actor
campaign
occurrence
```

Sortie :

```text
ResolvedTarget[]
  guild_id
  channel_id
  language_profile_id?
  translation_group_id?
  required_permissions
  resolution_reason
```

Le resolver travaille d'abord sur le cache DID. Un refresh Discord ciblé n'est demandé que si la fraîcheur/couverture est insuffisante pour une décision critique.

Une catégorie cible est développée en salons éligibles ; elle n'est jamais envoyée telle quelle à Discord.

## 49C.5 Autorisation multi-Guild

Pour chaque `ResolvedTarget` :

```text
authorize campaign owner
AND authorize publish on guild
AND authorize target selector scope
AND bot SEND_MESSAGES effective
AND target observable/current enough
```

Un échec sur Guild B ne donne aucune donnée supplémentaire sur Guild C et peut produire une occurrence `PARTIAL` plutôt que dupliquer les envois déjà réussis.

## 49C.6 Scheduler durable

Le scheduler scanne `next_run_at` via une requête bornée/indexée, claim les occurrences avec verrouillage/advisory lock ou `FOR UPDATE SKIP LOCKED`, puis crée des jobs durables.

Principes :

- PostgreSQL = source de vérité ;
- aucune campagne critique uniquement en mémoire ;
- timezone IANA stockée ;
- RRULE = représentation canonique unique des récurrences temporelles ;
- aucun second moteur CRON concurrent en base ;
- conversion en UTC pour `next_run_at` ;
- prise en compte DST via moteur calendrier ;
- occurrence key déterministe ;
- jitter possible pour campagnes massives non strictes ;
- backpressure par DiscordWorkloadGovernor.

## 49C.7 Event triggers

Les événements Gateway/domain sont normalisés puis évalués contre les triggers **dont la source tenant est explicitement liée**.

```text
DomainEvent(guild_id, event_type)
   ↓
EventTriggerSourceIndex(guild_id, event_type)
   ↓
source selector authorization/match
   ↓
Condition AST evaluator
   ↓
matching Campaigns
   ↓
Occurrence creation
```

L'index évite de scanner toutes les campagnes à chaque event et empêche qu'un événement de Guild A soit consommé par un trigger non autorisé pour A.

L'autorisation de la source est distincte de l'autorisation de chaque target/delivery.

Le `condition_ast_json` est interprété par un moteur borné ; jamais `eval`, SQL brut ou Python injecté.

### 49C.7A Causation / loop guard

Avant de créer une occurrence :

```text
if event_id already consumed by trigger -> ignore duplicate
if event.causation chain contains same campaign -> block/reject according policy
if event.causation_depth >= configured hard limit -> block
if trigger graph contains known direct cycle -> refuse activation or require explicit safe break condition
```

Toute occurrence créée hérite `correlation_id`, référence `trigger_event_id` et incrémente la profondeur de causalité pour les événements qu'elle générera ensuite.

Les cycles cross-Guild sont traités exactement comme les cycles intra-Guild.

## 49C.8 Idempotence delivery

Clé logique :

```text
sha256(campaign_id | occurrence_id | guild_id | channel_id | language_variant)
```

Avant envoi : réservation atomique de la delivery.

Après envoi : persistance `discord_message_id`.

Pour les créations de message de campagne, l'adapter utilise un `nonce` déterministe (<= limite Discord courante) avec `enforce_nonce=true` lorsque le endpoint `Create Message` le supporte. Le nonce est dérivé de la clé d'idempotence de delivery et reste stable lors des retries.

Le mécanisme Discord ne remplace pas le ledger local : la fenêtre de déduplication Discord est bornée.

Si le résultat réseau est ambigu : état `UNKNOWN_OUTCOME`, tentative de résolution via nonce/Gateway/cache lorsque possible, puis réconciliation ciblée avant nouvelle tentative.

## 49C.9 Allowed Mentions Compiler

Par défaut : politique restrictive.

```text
allowed_mentions = explicit policy
```

Le parser peut conserver textuellement `<@...>` ou `@everyone`, mais les notifications sont décidées séparément.

Le `AllowedMentionsCompiler` vérifie :

- mentions users autorisées ;
- mentions roles autorisées ;
- `everyone/here` explicitement autorisé ;
- permissions Discord du bot ;
- limites de listes ;
- policy campagne.

La traduction n'est jamais autorisée à modifier cette policy.

Lors d'un `Edit Message`, le Discord adapter fournit également explicitement `allowed_mentions`; il ne s'appuie jamais sur le comportement par défaut de Discord. Les attachments existants à conserver sont reconstruits explicitement dans la requête d'édition.

## 49C.10 MessageModel structuré

Exemple conceptuel :

```json
{
  "content": {
    "kind": "rich_text",
    "source": "Maintenance à 22h <@&123> https://status.example.com"
  },
  "embeds": [
    {
      "title": "Maintenance",
      "description": "Le service sera indisponible.",
      "url": "https://status.example.com"
    }
  ],
  "components": [],
  "attachments": [],
  "variables": {}
}
```

Ce modèle passe par validation Discord avant compilation REST.

## 49C.11 Publication dans Translation Channel Group

Le `CampaignTargetResolver` sait qu'un channel appartient à `translation_channel_group_id`.

Le `MessageTranslationCoordinator` propose/compile l'un des modes :

```text
SOURCE_ONLY
SOURCE_ONLY_PROVIDER_HANDLES_TRANSLATION
DID_TRANSLATE_AND_FANOUT
MANUAL_LANGUAGE_VARIANTS
```

`SOURCE_ONLY_PROVIDER_HANDLES_TRANSLATION` ne suppose aucune modification du bot de traduction existant.

`DID_TRANSLATE_AND_FANOUT` est une fonctionnalité du Campaign Engine DID et ne modifie pas le provider existant.

## 49C.12 Double-translation safety

Un paramètre par Guild/Translation Group décrit le comportement connu du provider :

```text
ignores_bot_messages = TRUE | FALSE | UNKNOWN
```

Lorsque `UNKNOWN`, DID ne prétend pas qu'un fan-out est sans risque. L'admin choisit explicitement le mode sûr correspondant à la configuration réelle de son bot existant.

Aucune automatisation n'est créée en modifiant le bot tiers.

## 49C.13 `googletrans` adapter

Port interne :

```python
from typing import Protocol

class CampaignTranslationEngine(Protocol):
    async def translate_units(
        self,
        *,
        source_language: str | None,
        target_language: str,
        units: list["MaskedTranslationUnit"],
        request_id: str,
    ) -> list["TranslatedUnit"]: ...
```

Adapter :

```text
GoogletransCampaignTranslationAdapter
```

Il gère :

- session async ;
- batching borné ;
- timeouts ;
- retry réseau borné ;
- circuit breaker ;
- métriques ;
- mapping code langue DID -> code supporté ;
- aucune logique Discord dans l'adapter.

## 49C.14 DiscordSafeMessageParser

Le parser transforme le texte en AST/token stream :

```text
TEXT("Maintenance à ")
DISCORD_TIMESTAMP("<t:178...:F>")
TEXT(" pour ")
ROLE_MENTION("<@&123>")
TEXT(" - ")
URL("https://status.example.com")
```

Nœuds minimum :

```text
TRANSLATABLE_TEXT
PLAIN_URL
MARKDOWN_LINK_LABEL
MARKDOWN_LINK_URL
USER_MENTION
ROLE_MENTION
CHANNEL_MENTION
SLASH_COMMAND_MENTION
CUSTOM_EMOJI
ANIMATED_CUSTOM_EMOJI
DISCORD_TIMESTAMP
GUILD_NAVIGATION
INLINE_CODE
CODE_BLOCK
MARKDOWN_DELIMITER
TEMPLATE_VARIABLE
PROTECTED_TERM
RAW_TECHNICAL_TOKEN
```

Le lexer/parser doit privilégier la conservation exacte sur la volonté de traduire davantage.

## 49C.15 Translation Protector

La stratégie privilégie le contexte :

1. parser le message en nœuds traduisibles et protégés ;
2. remplacer les nœuds non traduisibles par des placeholders contrôlés **dans une copie masquée du contexte complet**, plutôt que retirer le texte environnant ;
3. envoyer à `googletrans` l'unité masquée la plus large et cohérente possible (message, paragraphe ou bloc) ;
4. ne subdiviser davantage que si une contrainte technique l'impose ou si les benchmarks réels démontrent une meilleure qualité ;
5. restaurer les placeholders puis appliquer une validation stricte fail-closed.

Tout placeholder possède :

```text
placeholder_id
original_bytes/string
kind
restore_policy
```

La restauration exige une correspondance exacte.

## 49C.15A TranslationContextBuilder et benchmark réel `googletrans`

`TranslationContextBuilder` est responsable de la création des unités envoyées au moteur. Il ne doit pas confondre **tokenisation syntaxique** et **segmentation linguistique** : l'AST peut être très fin pour protéger Discord, tandis que la chaîne envoyée à `googletrans` doit conserver le contexte le plus large possible.

Exemple :

```text
AST :
TEXT("Salut ")
ROLE_MENTION("<@&123>")
TEXT(", le raid commence à 21h. Préviens-moi si tu seras en retard.")

Payload masqué proposé :
"Salut ⟦DID_P0001⟧, le raid commence à 21h. Préviens-moi si tu seras en retard."
```

Le traducteur reçoit donc **la phrase/paragraphe complet**, pas les deux nœuds `TEXT` traduits séparément.

### Stratégies à benchmarker

Le dépôt doit fournir un harness d'intégration permettant de comparer au minimum :

```text
WHOLE_MASKED_MESSAGE
MASKED_PARAGRAPH_BLOCKS
MASKED_STRUCTURAL_BLOCKS
SAFE_SENTENCE_SPLIT        # fallback/test, pas choix implicite
```

Les placeholders eux-mêmes doivent aussi être testés empiriquement avec plusieurs encodages candidats. Aucun format n'est déclaré sûr uniquement par hypothèse ; il doit démontrer qu'il survit aux traductions FR/EN/DE/ES et aux combinaisons de ponctuation/Markdown du corpus.

### Corpus de référence

Créer `tests/integration/googletrans_corpus/` avec :

- cas simples ;
- phrases dépendant d'un contexte précédent ;
- pronoms/genre/négation ;
- messages multiligne ;
- Markdown imbriqué ;
- URLs/mentions/emojis/timestamps/command mentions ;
- code inline/blocs de code ;
- embeds ;
- glossaires/DO_NOT_TRANSLATE ;
- plusieurs placeholders dans une même proposition ;
- vocabulaire métier Hero Wars et noms propres.

Chaque cas stocke :

```text
source
source_language
target_language
protected_tokens_expected
terminology_constraints
human_review_notes / expected intent where useful
```

### Critères de choix

La stratégie de production est celle qui maximise, dans cet ordre :

1. intégrité technique (obligatoirement 100 % sur le corpus de conformité) ;
2. fidélité linguistique/contextuelle observée ;
3. respect du glossaire ;
4. stabilité entre exécutions ;
5. coût/latence et nombre d'appels.

Une sortie ayant une meilleure fluidité linguistique mais une corruption technique est toujours rejetée.

Les tests mocks restent utilisés pour les tests unitaires, mais ils ne remplacent pas la suite d'intégration réelle `googletrans`. Cette suite peut être séparée des tests CI rapides si l'accès réseau n'est pas garanti, mais elle fait partie de la qualification d'une version de l'adapter et de toute modification du parser/protector/placeholder strategy.

Le résultat du benchmark (stratégie gagnante, version `googletrans`, date, corpus/hash, métriques) doit être conservé dans un rapport versionné du dépôt afin que Codex ne change pas arbitrairement la segmentation plus tard.

## 49C.16 Technical fingerprint

Avant traduction :

```text
fingerprint = {
  urls: [...],
  user_mentions: [...],
  role_mentions: [...],
  channel_mentions: [...],
  commands: [...],
  custom_emojis: [...],
  timestamps: [...],
  code_blocks_hashes: [...],
  variables: [...],
  component_custom_ids: [...],
  embed_urls: [...]
}
```

Après reconstruction, `TechnicalIntegrityValidator` recalcule l'empreinte.

Critères obligatoires :

```text
same protected token count
same token kind sequence where required
same exact IDs
same exact URLs
same exact code blocks
same exact template variables
valid Discord markup
valid embed/component schema
```

Échec => `TRANSLATION_TECHNICAL_INTEGRITY_FAILED`, aucune publication de la variante.

## 49C.17 Markdown policy

Règles :

- blocs de code : jamais traduits ;
- inline code : jamais traduit ;
- URL d'un lien Markdown : jamais traduite ;
- label d'un lien Markdown : traduisible ;
- marqueurs gras/italique/strike/spoiler : structure préservée ;
- contenu humain à l'intérieur : traduisible si AST valide ;
- mention/emoji/timestamp : token atomique.

Le parser doit être testé sur les syntaxes Discord officielles et sur les combinaisons Markdown imbriquées supportées.

## 49C.18 Glossary pipeline

Ordre :

```text
load applicable glossaries
→ normalize rules
→ detect DO_NOT_TRANSLATE spans
→ apply forced target terminology policy
→ translate remaining language spans
→ reapply/validate forced terms
→ technical integrity validation
```

Scopes possibles :

```text
GLOBAL PRODUCT
GUILD
LOGICAL_GROUP
TRANSLATION_GROUP
CAMPAIGN/TEMPLATE
```

Plus spécifique gagne, avec conflit visible au preview.

## 49C.19 Force translation without corrupting grammar

Une `FORCE_TRANSLATION` ne doit pas être un simple `str.replace()` aveugle après traduction.

Le moteur conserve l'alignement du terme protégé et vérifie la présence du terme canonique cible. Les remplacements post-traduction sont limités à des spans explicitement identifiés.

## 49C.20 Embed translation model

Le modèle sépare :

```text
TRANSLATABLE
  title
  description
  fields[].name
  fields[].value
  footer.text
  author.name

PROTECTED
  url
  thumbnail.url
  image.url
  footer.icon_url
  author.url
  author.icon_url
  timestamp structured value
  color
```

Chaque champ traduit est validé contre les limites Discord avant delivery.

## 49C.21 Components

Pour les composants supportés :

```text
button.label       translatable
button.url         protected
custom_id          protected
select placeholder translatable
select value       protected by default
```

Toute extension future passe par un schema explicitant `TRANSLATABLE` vs `PROTECTED`.

## 49C.22 Template variable types

```python
class VariableKind(str, Enum):
    TRANSLATABLE_TEXT = "TRANSLATABLE_TEXT"
    NON_TRANSLATABLE = "NON_TRANSLATABLE"
    LOCALIZED_VALUE = "LOCALIZED_VALUE"
    URL = "URL"
    DISCORD_TOKEN = "DISCORD_TOKEN"
    CODE = "CODE"
```

Une variable inconnue est `NON_TRANSLATABLE` par défaut.

## 49C.23 Approved Variants

Pour récurrence/automation :

```text
source template hash
+ glossary hash
+ target locale
= approved variant identity
```

Si le hash source/glossaire change, la variante passe `STALE_REVIEW_REQUIRED` selon policy.

Cela évite de reconsommer `googletrans` et de réintroduire des variations linguistiques sur un texte statique déjà validé.

## 49C.24 Semantic quality policy

Aucune API de traduction statistique/neuronale n'est traitée comme preuve de vérité linguistique.

Le système offre :

```text
AUTO_PUBLISH_AFTER_TECHNICAL_VALIDATION
REVIEW_ON_WARNING
ALWAYS_REVIEW_NEW_TRANSLATION
APPROVED_VARIANTS_ONLY
```

Pour contenus critiques : `APPROVED_VARIANTS_ONLY` recommandé.

Une back-translation peut éventuellement produire un score/avertissement heuristique, jamais une garantie.

## 49C.25 Preview

Le preview expose :

- source ;
- variantes ;
- différence ;
- glossaire appliqué ;
- tokens protégés ;
- mentions/pings ;
- limites Discord ;
- warnings ;
- statut de revue.

L'admin peut éditer une variante ; une édition déclenche à nouveau la validation technique.

## 49C.26 Rate limiting

Les publications passent par `DiscordWorkloadGovernor`.

Une campagne massive est décomposée en deliveries. Le governor assure :

- équité inter-Guild ;
- respect buckets ;
- priorité configurable ;
- pause/reprise ;
- backpressure ;
- progression visible.

`googletrans` possède séparément son propre limiteur/circuit breaker afin qu'une panne de traduction ne surcharge pas Discord ni l'inverse.

## 49C.27 Observabilité

Métriques minimum :

```text
campaign_occurrences_total
campaign_deliveries_total
campaign_delivery_failures_total
campaign_delivery_latency
campaign_partial_occurrences
translation_requests_total
translation_failures_total
translation_integrity_failures_total
translation_review_required_total
glossary_conflicts_total
```

Aucun contenu sensible complet n'est injecté dans les logs métriques.

## 49C.28 Tests de corpus Discord-safe

Maintenir un corpus de messages comprenant :

- toutes les syntaxes Discord documentées ;
- Markdown imbriqué ;
- URLs avec query/fragment ;
- IP/ports ;
- code blocks multi-langages ;
- placeholders ;
- emojis custom ;
- mentions ;
- timestamps ;
- embeds ;
- composants ;
- termes de glossaire ;
- langues avec accents/non latin/RTL.

Property tests : tout token marqué `PROTECTED` doit être identique avant/après quel que soit le résultat du faux moteur de traduction.

## 49C.29 Fuzzing du parser

Le parser de message est une frontière de sécurité/intégrité. Ajouter des tests fuzz/property-based afin de vérifier :

- pas de crash ;
- round-trip des tokens protégés ;
- pas de perte de texte ;
- refus fail-closed des structures invalides.

## 49C.30 API Campaigns

Endpoints indicatifs :

```text
GET    /api/v1/campaigns
POST   /api/v1/campaigns
GET    /api/v1/campaigns/{campaign_id}
PATCH  /api/v1/campaigns/{campaign_id}
POST   /api/v1/campaigns/{campaign_id}/preview
POST   /api/v1/campaigns/{campaign_id}/simulate
POST   /api/v1/campaigns/{campaign_id}/activate
POST   /api/v1/campaigns/{campaign_id}/pause
POST   /api/v1/campaigns/{campaign_id}/send-now
GET    /api/v1/campaigns/{campaign_id}/occurrences
GET    /api/v1/campaigns/{campaign_id}/deliveries
POST   /api/v1/campaigns/{campaign_id}/variants/{language}/approve
```

Chaque endpoint multi-Guild effectue les contrôles User Control Plane + tenants concernés.

---

# 49D. Dashboard Localization Runtime

## 49D.1 Séparation du domaine de contenu

```text
UI Locale Pack          Language Profile
----------------        ----------------
fr                      fr
Global DID UI           tenant-scopé
1 active locale/user    0..N visible languages/member/Guild
traduit l'application   décrit/cible le contenu Discord
```

Même code ISO possible, agrégats distincts.

## 49D.2 Runtime loading

Endpoints de lecture :

```text
GET /api/v1/ui/catalog/version
GET /api/v1/ui/locales
GET /api/v1/ui/locales/{locale}/catalog/{catalog_version}
```

Ces endpoints de lecture doivent être utilisables **avant authentification** afin que l'écran « Connexion avec Discord » soit lui-même entièrement localisé. Ils ne renvoient aucune donnée utilisateur/tenant et appliquent cache/CDN/ETag.

Les endpoints d'administration permettant upload/activation d'un pack restent authentifiés, capability-scopés et audités.

Headers : ETag/content hash + cache-control approprié.

Le pack est lazy-loaded et mis en cache navigateur. Changement de locale déclenche le chargement du pack complet compatible puis swap atomique.

## 49D.3 Locale pack manager

Le système doit permettre à un opérateur autorisé d'ajouter une locale :

```text
upload/register JSON bundle
→ schema validation
→ missing/extra keys report
→ interpolation validation
→ plural validation
→ preview
→ activate
```

Aucune modification du bundle frontend n'est nécessaire.

## 49D.4 Catalogue obligatoire

Le catalogue référence :

```text
key
namespace
required_params
pluralization metadata
rich-text capability
notes/context
```

Une locale active doit satisfaire toutes les clés `required`.

## 49D.5 Backend errors

Les erreurs de domaine exposent :

```json
{
  "code": "CAMPAIGN_TARGET_UNAUTHORIZED",
  "message_key": "errors.campaign.targetUnauthorized",
  "params": {
    "guildName": "Example"
  }
}
```

Le backend peut stocker un `debug_detail` séparé pour audit ; il ne devient pas une chaîne UX à traduire.

## 49D.6 Dynamic content

Ne pas traduire via i18next :

- nom de Guild Discord ;
- nom de catégorie/salon ;
- pseudo utilisateur ;
- rôle Discord créé par l'utilisateur ;
- contenu de messages ;
- texte template utilisateur.

Ces données sont rendues telles quelles, sauf fonction explicite de traduction de contenu.

## 49D.7 Build/CI gate

Le pipeline de build :

```text
extract UI keys
→ generate catalog version/hash
→ validate en/fr/de/es packs
→ fail if missing
→ type generation
→ frontend tests
→ E2E locale smoke tests
```

Les locale packs dynamiques supplémentaires sont validés contre le même catalogue avant activation. Une release modifiant le catalogue est bloquée si une locale `ACTIVE` n'est plus complète, sauf désactivation explicite de cette locale avant release.

## 49D.8 Font/emoji strategy

Ne pas embarquer une hypothèse « la fonte système affiche tous les drapeaux ».

Utiliser :

```text
Primary text font
 + Unicode fallback fonts
 + color emoji fallback fonts
 + normalized flag component
 + optional Twemoji-compatible renderer
```

Le drapeau est une aide visuelle ; `locale_code` reste la vérité.

## 49D.9 RTL readiness

Même si les packs initiaux sont LTR, l'architecture stocke `direction` et doit permettre :

```text
<html dir="rtl">
```

et des composants utilisant logical CSS properties (`margin-inline`, `padding-inline`, etc.) lorsque possible.

## 49D.10 Tests runtime

- changement EN -> FR sans reload complet ;
- ajout d'une locale dynamique ;
- pack incomplet refusé ;
- ETag/cache invalidation ;
- erreur backend localisée ;
- menu contextuel localisé ;
- toast localisé ;
- tooltip localisé ;
- ARIA localisée ;
- absence de clé brute ;
- drapeaux/emojis visibles sous Windows 11.

## 49D.11 Sécurité du contenu localisé

Les locale packs dynamiques sont considérés comme **données non fiables** jusqu'à validation.

Interdictions :

- HTML arbitraire ;
- `<script>`/event handlers ;
- `dangerouslySetInnerHTML` avec une valeur venant d'un pack ;
- URL `javascript:`/schémas non autorisés ;
- interpolation non échappée.

Pour le texte riche, utiliser une représentation structurée ou les composants sûrs de `Trans`/équivalent avec une allowlist de composants React connus. Les paramètres utilisateurs restent échappés.

La validation d'un pack vérifie également la compatibilité de ses marqueurs rich-text avec le catalogue.

---

# 50. Architecture des templates

Ne pas stocker des IDs Discord source non résolus comme vérité portable.

Utiliser des références symboliques :

```json
{
  "roles": [
    {
      "key": "MEMBER_ROLE",
      "name": "{{GROUP_NAME}}"
    }
  ],
  "channels": [
    {
      "key": "GENERAL",
      "name": "{{GROUP_SLUG}}-general",
      "permissions": [
        {
          "target": "ROLE:MEMBER_ROLE",
          "allow": ["VIEW_CHANNEL", "SEND_MESSAGES"]
        }
      ]
    }
  ]
}
```

---

# 51. Moteur de mapping

Lors de duplication :

```text
symbolic source
   ↓
source Discord ID
   ↓
mapping UI
   ↓
destination Discord ID/new resource
```

Aucun overwrite ne doit être recopié naïvement avec un rôle source appartenant à un autre concept.

Pour les templates multilingues, utiliser aussi :

```text
LANGUAGE:fr
VISIBILITY_SCOPE:ALPHA
SCOPE_LANGUAGE_ROLE:ALPHA:fr
TRANSLATION_GROUP:GUIDES
TRANSLATION_CHANNEL_GROUP:GENERAL
```

Jamais le nom localisé d'un salon comme clé de relation.

---

# 52. Audit Discord

Le fetch audit nécessite `VIEW_AUDIT_LOG`.

Discord conserve les entrées 45 jours.

Le backend doit :

- paginer ;
- corréler ;
- stocker ce qui est utile ;
- ne pas supposer que l'audit Discord est un historique éternel.

---

# 53. Permissions bot de moindre privilège

Créer un `CapabilityService`.

Exemple :

```python
capabilities.can_create_channel
capabilities.can_manage_overwrites
capabilities.can_manage_roles
capabilities.can_view_audit
```

Le frontend consomme ces capabilities pour désactiver les actions impossibles.

---

# 54. Discord capability checker

Avant chaque plan :

```text
Requested feature
↓
required Discord capabilities
↓
current bot capabilities
↓
possible / degraded / impossible
```

Exemple :

```text
Dupliquer catégorie
✓ MANAGE_CHANNELS
✗ MANAGE_ROLES

Résultat :
Possible sans recopier les overwrites
OU
Bloqué si l'utilisateur a demandé les permissions
```

---

# 55. Feature flags

Utiliser des feature flags pour :

- onboarding ;
- webhooks ;
- automatisations ;
- nouveaux types de salons ;
- fonctionnalités Discord récentes.

Flags :

- global ;
- tenant opt-in ;
- environment.

---

# 56. Compatibilité Discord

Créer une couche :

```text
discord_capabilities/
  channel_types.py
  permissions.py
  limits.py
  features.py
```

Objectif : centraliser les différences et évolutions Discord.

---

# 57. Dépendances et versions

Ne pas utiliser de ranges larges non contrôlés en production.

Backend :

- lockfile via `uv` ou Poetry/PDM selon choix final ;
- versions pinées.

Frontend :

- `package-lock.json` ou lockfile équivalent versionné.

FastAPI recommande explicitement de pinner une version connue fonctionnelle pour une application.

---

# 58. Gestion des migrations

Alembic.

Règles :

- migration backward compatible lorsque possible ;
- ne jamais modifier une migration déjà déployée ;
- nom clair ;
- tests de migration.

---

# 59. Seed développement

`scripts/seed_dev.py` ne crée pas de fausses ressources Discord.

Il peut créer :

- ACL locales ;
- templates ;
- comptes de test internes ;
- snapshots fixtures.

Pour tester Discord, utiliser la sandbox réelle.

---

# 60. Flux complet : première installation

```text
Admin clique "Ajouter à Discord"
            ↓
Discord OAuth/install
            ↓
Bot rejoint Guild A
            ↓
Gateway GUILD_CREATE
            ↓
guild_installation=PENDING_SETUP
            ↓
Admin se connecte au Dashboard
            ↓
OAuth identify+guilds
            ↓
Backend confirme owner/admin
            ↓
Capability check
            ↓
Import channels/roles/overwrites
            ↓
Snapshot initial
            ↓
Audit initial
            ↓
Admin valide
            ↓
guild_installation=ACTIVE
```

---

# 61. Flux complet : duplication catégorie

```text
UI : clic droit "Dupliquer"
            ↓
POST create plan
            ↓
Backend fetch state/cache
            ↓
Resolve role mapping
            ↓
Build operations
            ↓
Preflight
            ↓
Impact
            ↓
UI confirmation
            ↓
POST /apply
            ↓
Job Redis
            ↓
Worker lock guild
            ↓
Discord REST operations
            ↓
Persist each result
            ↓
Verify
            ↓
Snapshot
            ↓
WebSocket update UI
```

---

# 62. Flux complet : drift externe

```text
Admin modifie Discord directement
            ↓
Gateway event
            ↓
Bot emits normalized event
            ↓
Cache updated
            ↓
guild_structure_version++
            ↓
Plans based on old version become stale
            ↓
Audit/drift event
            ↓
Dashboard notification
```

---

# 63. Flux complet : tentative cross-tenant

```text
User A logged on Guild A
GET /guilds/B/plans/XYZ
            ↓
Session user resolved
            ↓
authorize_guild(B)
            ↓
DENY
            ↓
403/404
```

Aucun repository ne doit être consulté avant d'avoir établi la politique d'accès tenant lorsque cela risquerait une fuite d'existence.

---

# 64. Ordre technique recommandé pour l'implémentation complète

La cible est **l'implémentation complète du présent document**. Il n'existe aucun découpage fonctionnel par versions de produit. L'ordre ci-dessous décrit seulement les dépendances techniques permettant à Codex de construire l'ensemble sans introduire de raccourcis temporaires incompatibles avec la cible.

## 64.1 Fondations obligatoires

1. repository / settings / conventions ;
2. PostgreSQL + migrations + RLS ;
3. Redis ;
4. OAuth / sessions ;
5. tenancy + User Control Plane ;
6. Guild installation / bootstrap / RBAC ;
7. bot Gateway / intents ;
8. durable local cache ;
9. Channel Obfuscation + tombstones/purge ;
10. Discord REST Governor / I/O Worker ;
11. import structure ;
12. adaptive reconcile scheduler ;
13. audit / outbox / observabilité.

## 64.2 Lecture, permissions et projections

1. structure depuis cache ;
2. rôles depuis cache ;
3. vue normale + vue « masqués ou supprimés » ;
4. Permission Evaluator ;
5. bot capabilities ;
6. coverage diagnostics ;
7. groupes logiques ;
8. Visibility Scopes + Scope Membership Resolver.

## 64.3 Moteur de mutations et portabilité

1. Desired State Graph ;
2. plans ;
3. DAG + symbolic bindings ;
4. operation attempts / `UNKNOWN_OUTCOME` ;
5. preflight / risk / impact ;
6. worker apply ;
7. write-through cache ;
8. live updates ;
9. Clone Engine / Portable Artifacts ;
10. cache purge service ;
11. templates / bibliothèque / cross-Guild.

## 64.4 UX, i18n et administration avancée

1. UI message catalog + locale packs EN/FR/DE/ES ;
2. i18next runtime + chargement à chaud ;
3. CI anti-chaînes hardcodées / couverture 100 % ;
4. fonts/emoji/flags strategy ;
5. ActionRegistry localisé ;
6. menus contextuels globaux ;
7. drag & drop / Right Drag ;
8. Permission Intent Compiler ;
9. simulation / explain / impact ;
10. RBAC fin / role bindings ;
11. recherche universelle / bulk actions.

## 64.5 Multilingue et traduction

1. Language Profiles ;
2. `member_visible_languages` sans langue principale obligatoire ;
3. resource language policies ;
4. Translation Groups / Channel Groups ;
5. manual linking ;
6. Translation Workspace ;
7. Scope × Language role resolver ;
8. adapter non invasif du bot de traduction existant ;
9. `MANUAL_CONFIGURATION_REQUIRED` lorsque nécessaire ;
10. multilingual clone ;
11. drift/reconcile ;
12. Right Drag language targets.

## 64.6 Campaign Engine et automatisations de communication

1. modèle `message_campaigns` / targets / schedules / occurrences / deliveries ;
2. Target Resolver multi-Guild ;
3. scheduler durable et event triggers ;
4. Allowed Mentions Compiler ;
5. DiscordSafeMessageParser ;
6. glossaires et règles terminologiques ;
7. adapter `googletrans` pour Campaign Engine ;
8. Technical Integrity Validator fail-closed ;
9. preview multilingue / variantes approuvées ;
10. idempotence deliveries / simulation / audit ;
11. intégration Translation Channel Groups sans modification obligatoire du bot existant.

## 64.7 Fonctions complémentaires obligatoires du périmètre

- onboarding ;
- bots ;
- membres ;
- webhooks ;
- automatisations ;
- synchronisation par modèle ;
- multi-Guild explicitement autorisé ;
- observabilité et outils d'exploitation.

Aucune section de cet ordre ne doit être interprétée comme un produit livrable incomplet ou une version fonctionnelle distincte.

---

# 65. Directives Codex

Codex doit respecter les règles suivantes.

## 65.1 Ne pas contourner l'architecture

Ne pas appeler discord.py directement depuis un router FastAPI.

Passer par :

```text
Router
→ Application Service
→ Port
→ Discord Adapter
```

## 65.2 Tenant obligatoire

Toute nouvelle feature tenant-scopée doit inclure un test cross-tenant.

## 65.3 Pas de mutation cachée

Toute mutation structurelle significative doit passer par le plan engine.

## 65.4 Pas d'ADMINISTRATOR par facilité

Ne jamais résoudre un problème de permission en proposant automatiquement `ADMINISTRATOR`.

## 65.5 Pas de MESSAGE_CONTENT sans justification

Ne pas activer l'intent pour simplifier une feature non liée au contenu des messages.

## 65.6 Types

Pas d'ID Discord en `number` JavaScript.

Utiliser string côté API/frontend.

## 65.7 Sources

Lorsqu'une fonction Discord semble incertaine :

1. vérifier la documentation Discord officielle ;
2. documenter l'endpoint/permission/intent ;
3. ajouter un test sandbox.

---


## 65.8 Multilingue

Avant d'implémenter une fonctionnalité de traduction/langue, Codex doit identifier explicitement :

```text
language_profile_id
translation_group_id
translation_channel_group_id éventuel
visibility_scope_id
visibility_policy
provider capability
Discord mutations requises
role/overwrite capacity impact
```

Interdictions :

- déduire les liens par nom ;
- déduire les liens uniquement par langue ;
- utiliser `@Scope + @Language` comme AND implicite ;
- créer un rôle `TranslationGroup × Language` sans démontrer qu'un scope mutualisable n'existe pas ;
- stocker un secret provider dans un artifact portable ;
- demander `MESSAGE_CONTENT` dans DID uniquement pour configurer une topologie.

## 65.9 UI i18n obligatoire

Codex ne doit pas introduire une chaîne système visible sans clé i18n.

Avant merge :

```text
key exists
EN complete
FR complete
DE complete
ES complete
params typed/validated
no raw key visible
```

Toute nouvelle action du `ActionRegistry` fournit ses clés label/description/tooltip au lieu de texte humain figé.

## 65.10 Messages et traduction

Pour toute publication traduite, Codex doit identifier :

```text
translatable spans
protected spans
glossary scope
allowed_mentions
embed/component protected fields
technical fingerprint
review policy
delivery idempotency key
```

Interdiction absolue :

```python
translated = await translator.translate(raw_discord_message)
await channel.send(translated.text)
```

Un tel chemin contourne le parseur et le validateur et ne doit pas exister dans le dépôt.

# 66. Définition de Done technique

Une feature n'est terminée que si :

- use case codé ;
- contrôle tenant ;
- permissions dashboard ;
- capabilities Discord ;
- erreurs mappées ;
- audit ;
- tests unitaires ;
- test cross-tenant ;
- UI loading/error states ;
- clés i18n et traductions EN/FR/DE/ES pour toute nouvelle chaîne système ;
- tests d'intégrité technique pour toute traduction de message concernée ;
- documentation ;
- aucune fuite de secret ;
- aucun comportement Discord supposé sans vérification.

---

# 67. Références techniques

Discord :

- https://docs.discord.com/developers/resources/application
- https://docs.discord.com/developers/topics/oauth2
- https://docs.discord.com/developers/resources/user
- https://docs.discord.com/developers/resources/guild
- https://docs.discord.com/developers/resources/channel
- https://docs.discord.com/developers/topics/permissions
- https://docs.discord.com/developers/events/gateway
- https://docs.discord.com/developers/resources/audit-log
- https://docs.discord.com/developers/interactions/application-commands
- https://docs.discord.com/developers/topics/rate-limits
- https://docs.discord.com/developers/resources/message
- https://docs.discord.com/developers/reference#message-formatting
- https://docs.discord.com/developers/gateway/getting-started-with-privileged-intent-review
- https://docs.discord.com/developers/change-log

Python / Discord :

- https://discordpy.readthedocs.io/en/latest/

FastAPI :

- https://fastapi.tiangolo.com/
- https://fastapi.tiangolo.com/deployment/
- https://fastapi.tiangolo.com/deployment/docker/
- https://fastapi.tiangolo.com/deployment/versions/

Frontend :

- https://react.dev/
- https://vite.dev/guide/
- https://www.i18next.com/
- https://react.i18next.com/

Traduction campagnes :

- https://pypi.org/project/googletrans/
- https://github.com/ssut/py-googletrans

`googletrans` doit rester derrière l'adapter de campagne et son caractère non officiel/instable doit être traité par timeouts, circuit breaker, validation fail-closed et variantes approuvées.

---

# 68. Résumé d'architecture

```text
ONE DISCORD APP
      │
      ├── Guild A = Tenant A
      ├── Guild B = Tenant B
      └── Guild C = Tenant C

NO CROSS-TENANT VISIBILITY

React Dashboard
      ↓
FastAPI
      ↓
Application Services
      ↓
Domain
      ↓
Ports
      ├── PostgreSQL
      ├── Redis
      └── Discord Adapter

Discord Gateway
      ↓
Bot Process
      ↓
Normalized Events
      ↓
Cache / Reconcile / Audit

Mutations
      ↓
PLAN
      ↓
PREFLIGHT
      ↓
IMPACT
      ↓
WORKER
      ↓
DISCORD REST
      ↓
VERIFY
```

Cette architecture doit rester la référence tant qu'une décision d'architecture formelle ne la remplace pas.
---

# 69. Décisions d'architecture formelles

Les décisions suivantes sont normatives pour le dépôt initial. Toute modification importante doit être documentée dans un ADR dédié.

## ADR-001 — Tenant = Guild Discord

**Décision :** le tenant primaire est une Guild Discord identifiée par `guild_id`.

**Conséquence :** aucune table ou job métier relatif à un serveur ne peut être tenant-agnostic. Les artifacts personnels explicitement user-scopés relèvent du User Control Plane défini par ADR-019 et ne sont pas des données de Guild.

## ADR-002 — Monolithe modulaire, plusieurs processus

**Décision :** un seul codebase backend, avec processus API, bot et worker séparés.

**Motivation :**

- isolation opérationnelle ;
- simplicité du domaine ;
- pas de contrats réseau internes prématurés ;
- extraction en services séparés reste possible sans casser le domaine.

## ADR-003 — Discord comme source de vérité externe

**Décision :** l'état réel des catégories, salons, rôles et overwrites est celui de Discord.

La base locale conserve une représentation synchronisée pour :

- performance ;
- planification ;
- diff ;
- audit ;
- simulation.

## ADR-004 — Plans avant mutations

**Décision :** une mutation significative n'appelle pas directement Discord depuis l'UI/API.

Elle produit d'abord un plan persistant.

## ADR-005 — PostgreSQL source de vérité interne

**Décision :** PostgreSQL contient l'état durable propre à l'application.

Redis reste un composant éphémère de coordination.

## ADR-006 — Isolation tenant applicative + RLS

**Décision :** double défense :

1. autorisation applicative ;
2. PostgreSQL RLS lorsque techniquement applicable.

## ADR-007 — Permission engine propriétaire et testé

**Décision :** ne pas disperser le calcul de permissions dans les composants UI ou handlers bot.

Un moteur de domaine centralisé doit reproduire les règles Discord nécessaires à la simulation.

## ADR-008 — Intents minimaux

**Décision :** ne pas demander un intent privilégié avant d'avoir une fonctionnalité documentée qui en dépend.

## ADR-009 — IDs Discord sérialisés en strings pour le frontend

**Décision :** les Snowflakes restent `int` en Python, mais sont sérialisés en chaîne dans l'API publique.

## ADR-010 — Pas de faux rollback

**Décision :** le modèle d'opération connaît sa stratégie de compensation et son caractère réellement réversible ou non.

---


## ADR-011 — Langue, topologie et visibilité séparées

**Décision :** `Language Profile`, `Translation Group` et `Visibility Scope` sont trois agrégats/concepts distincts.

**Motivation :** empêcher toute contamination entre des groupes utilisant les mêmes langues et permettre plusieurs politiques d'accès pour une même langue.

## ADR-012 — Intersection de visibilité matérialisée

**Décision :** lorsqu'une ressource exige `Scope AND Language`, DID matérialise explicitement cette intersection via un binding technique, normalement un rôle Discord `Scope × Language`.

**Motivation :** les overwrites de rôles Discord ne fournissent pas un opérateur AND entre deux rôles.

## ADR-013 — Rôles techniques créés à la demande

**Décision :** les combinaisons `Scope × Language` sont créées lazy et mutualisées entre Translation Groups.

**Motivation :** maîtriser la limite de 250 rôles par Guild et limiter le bruit Discord.

## ADR-014 — Translation Provider abstrait

**Décision :** le moteur DID dépend d'un port `TranslationProvider`. Le bot de traduction existant est un adapter, pas une dépendance de domaine.

**Motivation :** testabilité, évolutivité, changement de provider et absence de partage de token.

## ADR-015 — Translation Groups tenant-scopés

**Décision :** un Translation Group appartient à une seule Guild. Un clone cross-Guild produit un nouveau groupe indépendant.

**Motivation :** préserver l'isolation multi-tenant et éviter toute fédération implicite.

## ADR-016 — Cache local durable, Gateway-first

**Décision :** les lectures dashboard sont cache-first ; Gateway et réponses de mutations alimentent le cache, REST sert principalement à la synchronisation/réconciliation ciblée.

**Motivation :** réduire les requêtes, protéger les rate limits, améliorer la latence et conserver un dernier état connu.

## ADR-017 — Observabilité distincte de l'existence

**Décision :** une ressource Discord connue peut exister localement tout en étant `OBFUSCATED/ACCESS_LOST`. Une omission HTTP n'implique pas une suppression.

**Motivation :** Channel Obfuscation Discord du 16 novembre 2026.

## ADR-018 — Discord REST bot-token centralisé

**Décision :** un Discord I/O Worker centralise la majorité des appels REST bot-token et la gouvernance des rate limits.

**Motivation :** éviter plusieurs limiteurs par-processus ignorant le budget global commun.

## ADR-019 — User Control Plane séparé

**Décision :** clipboard/bibliothèque user-scopés ne sont pas soumis au RLS `guild_id`, mais à une autorisation/RLS `owner_discord_user_id` distincte.

## ADR-020 — Adapter traduction non invasif

**Décision :** le bot de traduction existant n'est pas modifié comme prérequis. L'adapter peut fonctionner en `MANUAL_CONFIGURATION_REQUIRED`.

## ADR-021 — DAG persistant et effectively-once

**Décision :** les dépendances de plan, références symboliques et attempts sont persistées. Une création `UNKNOWN_OUTCOME` est réconciliée avant retry.

## ADR-022 — Cache durable distinct de la projection UI

**Décision :** la présence d'une ressource dans le cache ne signifie pas qu'elle doit être affichée dans l'arborescence normale. `OBFUSCATED`, `ACCESS_LOST` et les états supprimés sont masqués par défaut et exposés via une vue utilisateur explicite.

**Motivation :** préserver la connaissance historique nécessaire au diagnostic sans dégrader la lisibilité quotidienne.

## ADR-023 — Purge locale avec tombstone minimal

**Décision :** la purge d'une ressource cache ne déclenche aucune mutation Discord et conserve un tombstone minimal. Une observation Discord ultérieure prévaut toujours sur le tombstone.

**Motivation :** permettre à l'utilisateur de nettoyer un historique qu'il sait obsolète tout en gardant une protection contre les résurrections locales ambiguës.

## ADR-024 — Aucun concept de langue principale utilisateur

**Décision :** les membres ont un ensemble de `member_visible_languages`, sans langue principale obligatoire.

**Motivation :** le profil utilisateur ne doit pas dépendre d'une langue de contenu susceptible d'être désactivée/supprimée et aucune langue ne doit devenir implicitement un fallback.

## ADR-025 — Dashboard i18n runtime obligatoire

**Décision :** toute chaîne système visible passe par le catalogue i18n ; les locale packs sont versionnés, chargés au runtime et activables uniquement avec couverture obligatoire complète.

**Motivation :** garantir une interface intégralement traduite, permettre l'ajout de langues sans rebuild et empêcher les mélanges de langues/fallbacks visibles.

## ADR-026 — Campaign header user-scopé, deliveries tenant-scopées

**Décision :** une campagne multi-Guild appartient au User Control Plane ; chaque target/delivery est néanmoins autorisé et tracé avec son `guild_id`.

**Motivation :** permettre une action utilisateur multi-Guild sans créer de tenant multi-Guild ni casser l'isolation.

## ADR-027 — Traduction de campagne fail-closed

**Décision :** `googletrans` reçoit des unités masquées conservant le maximum de contexte linguistique, construites à partir d’un AST Discord-safe ; les tokens techniques restent protégés par placeholders/empreintes et toute corruption bloque la variante avant publication. La granularité de segmentation est déterminée par benchmarks réels, pas par découpage systématique des nœuds `TEXT`.

**Motivation :** protéger URLs, mentions, commandes, emojis custom, timestamps, code, variables, embeds et composants contre toute modification accidentelle du moteur de traduction.

## ADR-028 — Locale dashboard automatique basée navigateur

**Décision :** sans override utilisateur, DID négocie la locale depuis `navigator.languages`/`Accept-Language`; l'override persistant est nullable et l'utilisateur peut revenir au mode automatique. La locale Discord du profil OAuth n'est pas utilisée comme défaut.

**Motivation :** respecter la préférence réelle du navigateur tout en permettant un choix manuel durable sans figer la langue au premier login.

## ADR-029 — Login Discord OAuth2 Authorization Code Grant

**Décision :** le dashboard utilise Authorization Code Grant avec échange backend, `state` obligatoire, scopes initiaux `identify guilds`, tokens côté serveur et session opaque cookie. L'Implicit Grant est interdit.

**Motivation :** garder les secrets/tokens hors du navigateur et séparer proprement identité utilisateur, session DID et installation du bot.

## ADR-030 — Orchestration multi-Guild sans mutation cross-tenant directe

**Décision :** les jobs User Control Plane peuvent orchestrer plusieurs Guilds mais toute lecture/mutation Discord est fan-out vers un job enfant tenant-scopé avec `guild_id`.

**Motivation :** conserver l'isolation tenant sans empêcher campagnes et opérations utilisateur multi-Guild.

## ADR-031 — Sources de triggers de campagne explicitement tenant-scopées

**Décision :** un trigger événementiel possède des bindings de source explicites par Guild/scope. `event_type` seul ne peut jamais déclencher une campagne multi-Guild.

**Motivation :** empêcher une contamination cross-tenant par le bus d'événements.

## ADR-032 — Autorisation acteur cache-first avec lookup membre ciblé

**Décision :** les bindings de rôles Discord du dashboard utilisent le cache membre lorsqu'il est frais, puis un `Get Guild Member` ciblé pour l'acteur si nécessaire ; jamais un full member list uniquement pour un login/action.

**Motivation :** réduire la dépendance à `GUILD_MEMBERS` et les coûts REST tout en gardant une autorisation fraîche.

## ADR-033 — Propagation de causalité des automatisations

**Décision :** chaque événement/occurrence conserve correlation/causation/origin/depth et les triggers appliquent un loop guard avant création d'une nouvelle occurrence.

**Motivation :** empêcher les boucles de campagnes intra-Guild et cross-Guild.

## ADR-034 — Packs UI de base embarqués et fallback résilient

**Décision :** EN/FR/DE/ES sont embarqués comme packs complets compatibles avec le frontend ; les locales supplémentaires restent runtime. Un override indisponible déclenche un fallback navigateur/bootstrap sans rendu partiel.

**Motivation :** garantir l'exigence de traduction intégrale même pendant une indisponibilité du service de locale packs ou après désactivation d'une locale.

## ADR-035 — Fraîcheur d'autorisation distincte de la fraîcheur d'affichage

**Décision :** les décisions sensibles utilisent une fenêtre de fraîcheur acteur plus stricte que les lectures UI et déclenchent au besoin un lookup membre ciblé, jamais un full member list par défaut.

**Motivation :** réduire les appels Discord sans autoriser une mutation critique sur un cache de rôles trop ancien.

# 70. Matrice composant / responsabilité

| Composant | Lit Discord | Écrit Discord | PostgreSQL | Redis | Expose HTTP |
|---|---:|---:|---:|---:|---:|
| Frontend | Non | Non | Non | Non | Non |
| API | Indirect | Non direct | Oui | Oui | Oui |
| Bot Gateway | Oui/Gateway | Interactions limitées | Oui via service | Oui | Non |
| Discord I/O Worker | Oui/REST | Oui | Oui | Oui | Non |
| Scheduler | Non | Via jobs vers I/O Worker | Oui | Oui | Non |

Règle : **l'API ne réalise pas directement les mutations structurelles Discord**. Elle crée un plan/job.

---

# 71. Invariants de code

Ces invariants doivent faire l'objet de tests ou de contrôles statiques lorsque possible.

1. Une entité **tenant-scopée** n'existe jamais sans `guild_id`; les entités user-scopées appartiennent explicitement au User Control Plane.
2. Une opération de plan ne mute jamais deux Guilds.
3. Un plan de mutation est rattaché à une seule Guild destination ; un artifact portable peut conserver une provenance source sans transformer le plan en plan multi-tenant.
4. Un WebSocket tenant est abonné à une seule Guild active par contexte.
5. Un repository tenant-scopé exige `guild_id`.
6. Un repository user-scopé exige `owner_discord_user_id`/current user context.
7. Un token bot n'est accessible qu'aux adapters/processus backend autorisés.
8. Le frontend ne reçoit jamais de secret Discord.
9. Une permission bitfield ne transite jamais sous forme de JS `number`.
10. Une opération Discord a toujours un mapping d'erreur métier.
11. Une variante de traduction appartient à exactement un Translation Group compatible dans une Guild donnée.
12. La langue d'une ressource ne suffit jamais à déterminer son Translation Group.
13. Un binding `Scope × Language` est unique par Guild/Scope/Langue.
14. Un Translation Provider secret n'est jamais sérialisé dans un Portable Artifact.
15. Un clone multilingue cross-Guild crée de nouveaux Translation Group IDs sur la destination.
16. Une action critique a toujours un audit interne.
17. Une absence HTTP d'un channel connu n'est jamais seule suffisante pour passer la ressource à `DELETED_CONFIRMED`.
18. Un `CREATE_*` en `UNKNOWN_OUTCOME` n'est jamais retry sans réconciliation.
19. Les bindings de principals d'ACL dashboard ne sont jamais importés cross-Guild implicitement.
20. Une chaîne système visible du frontend possède une clé i18n ; aucune action/menu/toast/tooltip système ne dépend d'un texte hardcodé.
21. Une locale UI `ACTIVE` couvre 100 % du catalogue obligatoire de sa version.
22. Une campagne multi-Guild ne déduit jamais l'autorisation d'une Guild à partir d'une autre.
23. Un job User Control Plane ne mute jamais Discord directement ; chaque opération Discord dérivée porte un `guild_id`.
24. Un trigger événementiel ne consomme qu'un événement provenant d'une source Guild/scope explicitement liée.
25. `ui_locale_override_code = NULL` signifie AUTO_BROWSER ; la locale Discord du User Object ne devient jamais implicitement l'override.
26. Aucun pack UI ne produit de HTML arbitraire ou d'interpolation non échappée.
27. Une campagne ne consomme jamais deux fois le même `event_id` pour le même trigger.
28. Une chaîne de causalité de campagne ne peut pas dépasser la profondeur maximale ni contenir un cycle non explicitement cassé.
29. Toute édition de message de campagne fournit explicitement `allowed_mentions`.
23. Un token `PROTECTED` d'un message traduit est strictement identique avant/après ; sinon la variante n'est pas publiée.
24. Une livraison de campagne possède une clé d'idempotence unique et ne doit pas être publiée deux fois sur retry normal.

---

# 71A. Convention frontend pour gestes et contexte

Packages/features recommandés :

```text
src/features/interaction/
├── context-menu/
│   ├── GlobalContextMenuBoundary.tsx
│   ├── ContextMenuHost.tsx
│   └── action-context.ts
├── pointer-gestures/
│   ├── PointerGestureManager.ts
│   ├── RightDragSensor.ts
│   └── drag-threshold.ts
├── dnd/
│   ├── DropTargetResolver.ts
│   ├── DragOverlay.tsx
│   └── MultiGuildDropZone.tsx
└── actions/
    ├── ActionRegistry.ts
    ├── ActionCapabilityResolver.ts
    └── action-types.ts
```

Tests frontend obligatoires :

- `contextmenu` natif toujours empêché ;
- clic droit sans mouvement → menu contextuel applicatif ;
- clic droit + drag → Drop Context Menu ;
- bouton gauche même Guild → move proposé ;
- bouton gauche autre Guild → copy/clone proposé ;
- actions interdites absentes du menu ;
- annulation `pointercancel` sans mutation ;
- clavier/menu alternatif disponible pour les actions essentielles.

---

# 72. Convention de nommage des packages Python

```text
did.domain.*          logique pure
did.application.*     use cases
did.infrastructure.* adapters externes
did.api.*             transport HTTP/WS
did.bot.*             transport Gateway/interactions
did.worker.*          exécution asynchrone
did.tenancy.*         tenant context + guards
did.permissions.*     moteur de permissions
did.planning.*        plans/diff/preflight/risk
did.audit.*           événements audit
did.campaigns.*       campagnes, occurrences, deliveries, ciblage
did.oauth.*           OAuth2 Discord, grants, sessions/auth helpers
did.localization.*    catalogue UI, locale resolver, pack validation
did.messaging.*       modèle Discord-safe, embeds, mentions, templates
did.localization.*    UI locale packs/catalogue utilisateur
did.translation.*     traduction de contenu, glossaires, intégrité technique
```

Un import de `did.infrastructure` depuis `did.domain` est interdit.

---

# 73. Convention des use cases

Forme recommandée :

```python
@dataclass(frozen=True)
class DuplicateCategoryCommand:
    guild_id: int
    actor_user_id: int
    source_category_id: int
    destination_name: str

class DuplicateCategory:
    async def execute(
        self,
        command: DuplicateCategoryCommand,
    ) -> Plan:
        ...
```

Le use case retourne un résultat de domaine, pas un objet discord.py ni SQLAlchemy.

---

# 74. Convention transactionnelle

## 74.1 API

Une requête :

```text
authorize
↓
transaction DB
↓
persist command/plan
↓
outbox/event
↓
commit
```

## 74.2 Worker

Ne jamais garder une transaction DB ouverte pendant une longue série d'appels réseau Discord.

Préférer :

```text
load state
commit/close
call Discord
open transaction
persist operation result
commit
```

---

# 75. Outbox

Pour les commandes/jobs de mutation et les événements dont la perte casserait la cohérence, utiliser un **transactional outbox pattern**.

Implémentation obligatoire :

- persist job + outbox en même transaction ;
- dispatcher publie dans Redis ;
- marque l'outbox envoyée.

Cela évite :

```text
DB commit OK
Redis publish FAIL
=> job perdu
```

---

# 76. Locks et ordre

Lock principal :

```text
did:guild:{guild_id}:mutation
```

Ordre de lock fixe si plusieurs locks internes sont nécessaires.

Ne jamais acquérir deux locks de Guilds différentes pour une feature standard.

Cette règle participe directement à l'isolation des tenants.

---

# 77. Politique de retry

## Discord 429

Respecter le mécanisme de retry/rate limit officiel.

## Erreur réseau transitoire

Retry borné avec backoff + jitter.

## 4xx permissions/validation

Pas de retry aveugle.

## 404 cible

Reconcile avant décision éventuelle.

## Erreur interne

Marquer l'opération et préserver le diagnostic.

---

# 78. Versionnement API et schémas

Trois versions différentes :

```text
API version          /api/v1
DB migrations        Alembic revision
Snapshot schema      schema_version
Template schema      schema_version
```

Ne pas les confondre.

---

# 79. Stratégie de données live

Le frontend ne lit jamais Discord directement. Il charge :

```text
REST snapshot DID depuis cache local
+
WebSocket DID incremental events
```

Le backend met son cache à jour via :

```text
Discord Gateway
+
Discord mutation responses
+
rate-limit-aware reconciliation
```

Si perte de séquence frontend ou reconnexion :

```text
invalidate query
→ REST refresh DID (cache local)
```

Si perte de continuité **Gateway backend** :

```text
mark affected cache stale
→ enqueue reconcile Discord prioritaire
```

Ne pas confondre refresh du frontend avec refresh Discord.

---

# 80. Garde-fou Codex final

Avant de générer du code pour une fonctionnalité Discord, Codex doit produire ou vérifier mentalement cette fiche :

```text
FEATURE:
TENANT SCOPE:
DISCORD OBJECT:
DISCORD ENDPOINT/EVENT:
BOT PERMISSION:
GATEWAY INTENT:
PRIVILEGED INTENT:
ROLE HIERARCHY CONSTRAINT:
RATE LIMIT CONCERN:
PLAN REQUIRED:
REVERSIBLE:
AUDIT:
TEST SANDBOX:
```

Si une ligne essentielle est inconnue, Codex doit consulter la documentation Discord officielle plutôt que d'inventer un comportement.
