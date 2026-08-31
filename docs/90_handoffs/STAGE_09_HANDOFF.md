# Handoff STAGE 09 — Message & Campaign Engine, automatisations et traduction sûre

> **Statut :** `STAGE_09_IMPLEMENTATION_IN_PROGRESS`. Ce handoff documente honnêtement ce qui est
> réellement construit et prouvé (schéma/domaine/scheduler/causalité/parser-protecteur/glossaire/
> traduction/réconciliation/résolution de cibles/variantes approuvées — 11 des 16 work packages
> internes), et ce qui reste (orchestration bout-en-bout, worker/governor, API, frontend,
> qualification live complète — WP12 partiel/WP13/WP14/WP15/WP16). Aucune preuve n'est fabriquée :
> chaque affirmation ci-dessous renvoie à un test réel (PostgreSQL réel, réseau réel, sandbox
> Discord réel) ou est explicitement marquée comme non construite.

| Champ | Valeur |
|---|---|
| Date | `2026-08-31` |
| Base main (départ) | `c41b61ae96cdb1d767c8d924212a6466b768ed60` |
| Branche | `stage/09-campaigns` |
| Statut | `STAGE_09_IMPLEMENTATION_IN_PROGRESS` (pas de PR ouverte à ce stade de la session) |
| Migration | `0021_stage_08 → 0022_stage_09` ; tête unique `0022_stage_09` ; rehearsal up/down/up validé sur PostgreSQL réel |
| Dernière étape intégrée | `STAGE_08_MULTILINGUAL_CONTENT_AND_TRANSLATION_TOPOLOGY` (`stage-08-complete`, inchangée) |

## Ce qui est construit et prouvé

### WP1 — Schéma / domaine

Migration `0022_stage_09` (`backend/alembic/versions/0022_stage_09_campaign_engine.py`) ajoute :
Control-Plane / user-owned (RLS `owner_discord_user_id = app.current_user_id()`, précédent exact
`portable_clone_bindings` de Stage06) : `message_campaigns`, `message_campaign_schedules`,
`message_campaign_triggers`, `message_glossary_entries`, `message_approved_variants`,
`message_occurrences`. Guild tenant-scoped (RLS `guild_id = app.current_guild_id()`, composite FK
via `guild_id`) : `message_campaign_targets`, `message_campaign_trigger_sources`,
`message_campaign_trigger_consumptions`, `message_deliveries`.

Un campagne header ne porte jamais `guild_id` — elle peut cibler plusieurs Guilds ; seules les
tables enfants (targets/deliveries) sont scopées tenant et RLS-protégées. Un delivery référence son
target par FK composite `(guild_id, target_id) → message_campaign_targets(guild_id, id)`, rendant
structurellement impossible qu'une delivery `guild_id=A` pointe vers un target `guild_id=B` (prouvé
PostgreSQL, voir ci-dessous).

`backend/src/did/domain/campaigns.py` modélise chaque entité en dataclass frozen/slotted avec
`__post_init__` de validation, suivant exactement la convention Stage08. `LifecycleStatus` est une
machine à états explicite (`DRAFT → SCHEDULED_ARMED/ACTIVE_RUNNING → PAUSED/CANCELLED/COMPLETED/
FAILED_INTERVENTION`) avec CAS (`version` incrémenté à chaque transition acceptée) ; toute
transition non listée lève `CampaignLifecycleError`. `DeliveryStatus` est une seconde machine à
états qui interdit structurellement le renvoi aveugle après un envoi ambigu (`UNKNOWN` ne mène
jamais directement à `PENDING`).

`backend/src/did/infrastructure/campaigns_repository.py` (`CampaignsRepository`) suit exactement le
style Stage03/08 (SQL brut paramétré, `tenant_transaction`, `FOR UPDATE SKIP LOCKED`, `ON CONFLICT
DO NOTHING` comme primitive d'idempotence).

**Preuve PostgreSQL réelle** (`backend/tests/integration/test_stage09_campaigns_postgres.py`, 7
tests, exécutés sur `docker compose -f compose.test.yaml`) : isolation RLS owner-scoped entre deux
utilisateurs (même requête non filtrée), isolation RLS guild-scoped entre deux Guilds (même
requête non filtrée), rejet FK composite d'une delivery croisant Guild A/B, no-op silencieux sur
occurrence/delivery dupliquée (`ON CONFLICT DO NOTHING`), et concurrence réelle : deux appels
`claim_due_schedules` simultanés (`asyncio.gather`, deux connexions admin distinctes) sur le même
schedule dû produisent exactement un gagnant.

### WP2 — Scheduler RRULE/IANA/DST/misfire

`backend/src/did/campaigns/scheduling.py`. `localize_wall_clock()` résout chaque instant local
candidat via PEP 495 `fold` : instant ordinaire (`fold0 == fold1`), doublon fall-back authentique
(les deux folds re-convergent vers le même wall-clock demandé → `dst_ambiguous_policy` choisit
EARLIEST/LATEST), ou trou spring-forward (aucun fold ne re-converge → `SKIP` abandonne l'occurrence,
`SHIFT_FORWARD` prend l'interprétation dont le retour local est postérieur à l'instant demandé).
`evaluate_recurring()` expanse la RRULE en temps civil local, borne le rattrapage
(`catch_up_bound` ; `SKIP_MISSED` garde les N plus récentes, `FIRE_ONCE_IMMEDIATELY` réduit tout
retard à une seule occurrence). La clé d'occurrence (`schedule:{id}:{instant_local_iso}`) est
déterministe — jamais dérivée de `now()` — donc reproductible après un redémarrage du scheduler.

**Preuve réelle (pas fixture)** : `backend/tests/unit/test_stage09_scheduling.py` exécute les
transitions DST réelles Europe/Paris 2026 (spring-forward 29 mars, fall-back 25 octobre) via le
vrai module `zoneinfo`/`tzdata` du système, pas une horloge simulée.

### WP3 — Causalité / AST de condition allowlist

`backend/src/did/campaigns/causality.py`. `should_trigger()` est l'unique porte REQ-MSG-027/030 :
liaison de source explicite (`TriggerSourceBinding.matches`), profondeur de causation bornée, garde
anti-boucle ancêtre (`with_campaign_ancestry`/`read_campaign_ancestry`, taguant l'id de campagne
dans le payload de l'événement plutôt que d'étendre le `EventEnvelope` partagé de Stage03), et AST
de condition allowlist (`ALWAYS/EQUALS/NOT_EQUALS/CONTAINS/AND/OR/NOT` uniquement — aucun `eval`/
`exec`/`compile` nulle part dans le module).

### WP4 — Résolution de cibles / réautorisation / simulation

`backend/src/did/campaigns/target_resolution.py`. Chaque résolution réinvoque
`TargetAuthorizationChecker` (port à câbler au `PermissionEvaluator` Stage04 réel — non fait) ;
l'autorisation de création n'est jamais mise en cache (test dédié : deux résolutions du même
target déclenchent deux vérifications fraîches). Le gate de mode de publication WP12 vit ici :
`SOURCE_ONLY`/`EXISTING_PROVIDER` ne résolvent que le salon source (aucun fan-out DID-traduit),
`DID_TRANSLATED_FANOUT` résout source + tous les variants, `SELECTED_LANGUAGES` résout uniquement
la sélection. `summarize_simulation()` est une preview pure sans effet de bord.

### WP5 — MessageModel / AllowedMentionsCompiler / edit-delete sûr

`backend/src/did/messaging/message_model.py` valide les vraies limites Discord (2000 caractères,
10 embeds, budget combiné 6000 caractères, 25 champs, 5 rangées/5 boutons). `AllowedMentionsCompiler`
(`allowed_mentions.py`) est par défaut aucune mention ; `everyone`/`here` exige un capability grant
explicite non auto-dérivé ; une liste explicite d'utilisateurs/rôles n'est jamais combinée avec
l'entrée `parse` correspondante (donc un contenu traduit contenant des mentions ne peut jamais
devenir un ping réel). `EditPayload.to_discord_kwargs()` (`edit_payload.py`) fournit toujours
`allowed_mentions` et une politique d'attachments explicite (`PRESERVE_EXISTING` omet la clé
`attachments`, `REMOVE_ALL` envoie `[]`). `authorize_owned_message_mutation()`
(`mutation_guard.py`) vérifie propriété de campagne, statut `SENT`, lien de message stocké, et
correspondance Guild/salon avant toute mutation.

### WP6 — Sender Discord réel / réconciliation nonce

`backend/src/did/infrastructure/discord_message_sender.py` (`DiscordPyMessageSender`) est construit
et vérifié contre les vraies signatures `discord.py==2.7.1` installées (`Messageable.send`,
`Message.edit`, `AllowedMentions`, méthodes de construction d'`Embed`).

**Découverte réelle en cours de construction** (deux sondes live contre le sandbox réel, preuve
committée dans `docs/90_handoffs/evidence/stage09/nonce-reconciliation-probe.json`, zéro secret/id/
PII) : `Message.nonce` n'est présent que sur la réponse immédiate d'envoi — absent de
`fetch_message()`/`history()` — donc une réconciliation par recherche d'historique ne fonctionne
pas contre l'API réelle et n'a pas été livrée. `discord.py==2.7.1` n'expose pas du tout le champ
REST `enforce_nonce` de Discord (zéro occurrence dans le paquet installé). En revanche, un renvoi
immédiat avec le même nonce + même contenu a retourné le même id de message les deux fois (une
seule vraie création) — le déduplication par défaut de Discord (sans `enforce_nonce`) fonctionne
pour un renvoi proche dans le temps. `did.campaigns.delivery_reconciliation
.decide_unknown_outcome_recovery()` recommande donc de renvoyer avec le nonce déjà stocké et le
`content_snapshot` déjà stocké (jamais un contenu re-rendu), borné à 5 minutes et 3 tentatives
ambiguës, au-delà de quoi `INTERVENTION_REQUIRED`. Combler `enforce_nonce` nécessiterait de
contourner `Messageable.send()` via l'`HTTPClient`/`Route` interne — esquissé, non implémenté (voir
« Écarts »).

### WP7 — Parseur/protecteur Discord-safe

`backend/src/did/messaging/parser.py` + `protector.py`. AST TEXT/PROTECTED (URL, mentions
utilisateur/rôle/salon, timestamps, emoji custom, blocs de code/code inline, mentions de commande
slash, variables de template). Décision documentée : les marqueurs Markdown d'emphase restent du
texte ordinaire (protéger chaque délimiteur fragmenterait les phrases) ; un contrôle structurel
séparé (comptage équilibré) existe. Les placeholders sont collision-résistants
(`DIDPH{index}Q{nonce_hex}ZH`) ; la restauration vérifie l'ensemble exact des placeholders
(manquant/dupliqué/inventé → `IntegrityViolation`, échec fermé) ; l'ordre est enregistré mais n'est
pas un gate dur (une traduction légitime réordonne les mots selon la grammaire cible).

**Preuve** : 41 tests unit/property/fuzz (`hypothesis`, nouvelle dépendance dev), incluant deux
propriétés fuzzées (round-trip sur messages synthétiques aléatoires ; détection garantie de toute
suppression d'un seul token protégé).

### WP8 — Glossaire

`backend/src/did/campaigns/glossary.py`. Les termes de glossaire sont protégés via le même
mécanisme de placeholder que les tokens techniques (`ProtectedKind.GLOSSARY_TERM`) — jamais une
substitution brute post-traduction. Priorité documentée : `CAMPAIGN` > `GLOBAL_USER` ; langue
spécifique > agnostique ; terme le plus long départage. Correspondance par frontière de mot
(`\b...\b`) pour ne jamais matcher à l'intérieur d'un mot non lié.

### WP9 — Adapter googletrans

`backend/src/did/translation/googletrans_adapter.py` est le seul module du dépôt qui importe
`googletrans` — vérifié : `googletrans==4.0.2` (metadata réel du paquet), API async
`Translator.translate(text, src, dest)`, aucune clé API requise, dépend de `httpx[http2]>=0.27.2`
(résolu proprement contre le `httpx==0.28.1` déjà épinglé). `CircuitBreaker`
(`translation/circuit_breaker.py`, CLOSED/OPEN/HALF_OPEN, sans dépendance) + timeout borné + retry
avec backoff enveloppent chaque appel ; toute panne échoue fermé (`TranslationProviderError`),
jamais une traduction corrompue ou partielle.

### WP10 — Benchmark réel

`scripts/run_translation_benchmark.py` a exécuté **288 vrais appels réseau** googletrans (12 items
du corpus `backend/tests/fixtures/translation_corpus/stage09_corpus.json`, EN→FR/DE/ES, 4
stratégies) — preuve committée `docs/90_handoffs/evidence/stage09/translation-benchmark.json`.
Résultat mesuré : **100 % d'intégrité de placeholder sur les 4 stratégies** ;
`FULL_MASKED_MESSAGE` la plus rapide/à égalité, avec espacement inter-token correctement préservé,
tandis que le contrôle négatif `NAIVE_PER_TEXT_NODE` a visiblement perdu l'espacement autour des
placeholders dans les échantillons allemands enregistrés — preuve empirique concrète, pas
seulement théorique, de la mise en garde contre la traduction fragment par fragment.
`select_translation_strategy()` choisit `FULL_MASKED_MESSAGE` par défaut (repli
`PARAGRAPH_GROUPING` au-delà de 1500 caractères masqués) directement à partir de cette preuve
mesurée.

### WP11 — Variantes approuvées

`backend/src/did/campaigns/approved_variants.py`. `compute_source_fingerprint()` est un sha256 sur
le JSON canonique (clés triées) du `message_model` — insensible à l'ordre des clés.
`resolve_variant_for_delivery()` retourne `REUSABLE`/`STALE`/`MISSING` ; une campagne récurrente
inchangée reste `REUSABLE` à travers ses occurrences (testé), tandis qu'un changement de source
rend l'ancienne approbation `STALE` sans jamais la réutiliser silencieusement ni retraduire
silencieusement.

## Suite de tests réelle (exécutée cette session)

| Gate | Résultat |
|---|---|
| `uv run pytest backend/tests/unit/ -k stage09` | **211 passed** |
| `uv run pytest backend/tests/unit/` (régression complète) | **538 passed** |
| `uv run pytest backend/tests/integration/test_stage09_campaigns_postgres.py` (PostgreSQL réel) | **7 passed** |
| `uv run pytest backend/tests/integration/` (régression complète) | **107 passed** |
| `uv run pytest backend/tests/network/` (`DID_ALLOW_NETWORK=1`, googletrans réel) | **2 passed** |
| `uv run ruff check` / `ruff format --check` (tout le dépôt) | PASS |
| `uv run mypy` (139 fichiers, mode strict) | PASS, 0 erreur |
| `uv run python scripts/check_secrets.py` | PASS (383 fichiers) |
| `uv run python scripts/validate_documentation.py` | PASS (246/246 REQ tracées) |
| `python scripts/validate_stage.py 08` | PASS (régression Stage08 confirmée avant de commencer) |

Le pipeline `python scripts/validate_stage.py 09` complet (nouvelle entrée `STAGES["09"]`,
profils `translation-benchmark`/`failure-injection`/`--include-discord-live`) n'a **pas** été
ajouté à `scripts/validate_stage.py` — écart explicite, voir ci-dessous.

## Qualification live Discord réelle (ciblée, pas la matrice complète)

Deux sondes réelles contre le sandbox Guild A (salon temporaire créé/supprimé, contenu synthétique
uniquement, zéro secret/id/PII committé) ont directement informé la conception WP6 (voir ci-dessus)
— preuve : `docs/90_handoffs/evidence/stage09/nonce-reconciliation-probe.json`. La matrice complète
demandée en section J de la spécification (envoi immédiat/planifié réel bout-en-bout, retry après
crash réel, allowed_mentions none/explicite réel, edit/delete réel, quatre variantes de langue,
Translation Group publication, provider externe présent/absent, exactement un message par
delivery) **n'a pas été exécutée** car elle nécessite le service d'orchestration bout-en-bout
(WP12 restant + WP13) qui n'existe pas encore.

## Écarts connus (non dissimulés)

1. **Orchestration bout-en-bout** : aucun service ne relie encore activation de campagne →
   création d'occurrence → fan-out → delivery. Chaque brique existe et est prouvée isolément.
2. **WP13 (Governor/worker)** : décision prise et documentée — réutiliser `discord_io_jobs` +
   `DiscordWorkloadGovernor` via un nouveau `workload_type` (`SEND_CAMPAIGN_MESSAGE`), jamais un
   worker parallèle — mais le branchement réel dans `worker.py` n'est pas fait ; aucun test de
   charge/fairness Stage09.
3. **WP14 (API)** : aucun router FastAPI Stage09.
4. **WP15 (Frontend)** : aucune UI Stage09.
5. **WP16 (Live)** : deux sondes ciblées réelles seulement, pas la matrice complète.
6. **REQ-MSG-013** : aucun typage champ-par-champ (embed/composant) distinguant ce qui est
   traduisible.
7. **REQ-MSG-018** : les variables de template sont protégées de façon uniforme et sûre, mais pas
   typées `TRANSLATABLE_TEXT`/`NON_TRANSLATABLE`/`LOCALIZED_VALUE` séparément.
8. **REQ-MSG-020** : aucune déclaration explicite de dépendance `MESSAGE_CONTENT` sur un trigger.
9. **REQ-MSG-026** : la preuve mesurée ne justifie pas (pour l'instant) une stratégie différenciée
   par classe de contenu ; décision honnête, pas un oubli.
10. **`enforce_nonce`** : indisponible dans `discord.py==2.7.1`, vérifié et documenté (§ WP6) ; le
    contournement via `HTTPClient`/`Route` brut est esquissé mais non implémenté.
11. **`scripts/validate_stage.py`** : pas d'entrée Stage09 ajoutée cette session.

Voir `docs/10_implementation/STAGE09_REQUIREMENTS_CHECKLIST_LOCAL.md` pour la matrice complète des
31 IDs et `docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md` pour la preuve fichier:ligne de
chacun.
