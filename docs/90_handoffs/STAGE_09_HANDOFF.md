# Handoff STAGE 09 — Message & Campaign Engine, automatisations et traduction sûre

> **Statut :** `STAGE_09_IMPLEMENTATION_IN_PROGRESS`. Cinq passes cumulées : (1) fondations WP1-WP11
> réelles et testées, (2) remédiation externe 17 findings (§ dédiée ci-dessous), (3) root-cause de la
> corruption d'intégrité de traduction, fencing de bail strict, autorisation à la création pour
> targets/trigger sources, typage traduction/variables (REQ-MSG-013/018), dépendance `MESSAGE_CONTENT`
> explicite (REQ-MSG-020), worker de livraison réel câblé au `DiscordWorkloadGovernor` partagé (WP13),
> CI Stage09 réelle, (4) identité de job de livraison corrigée (défaut critique), résultat de fencing
> de finalisation honoré, classification réelle des exceptions discord.py, autorisation à la création
> complétée (appartenance topologique réelle), corpus de benchmark étendu de 6 à 26 classes/104 items
> avec requalification 100% réelle, et **l'orchestration WP12 réelle** (`fan_out_occurrence`,
> `run_scheduler_tick`, `consume_event_for_trigger`, `simulate_campaign`), (5) **cette passe** —
> **connexion au runtime réel** (`did.runtime.py` exécute désormais le Campaign Engine dans les
> process scheduler/worker existants — le plus gros écart resté après WP12), dispatch durable de
> livraison via un job nommé exécuté par le vrai `DurableDiscordIOWorker`, fencing de fan-out
> d'occurrence par heartbeat de bail, correction d'une faille critique (`event_type` jamais vérifié
> dans `should_trigger`), élimination d'un owner non fiable côté consommation d'événement, transport
> d'événement Stage03 réel (curseur durable sur `discord_gateway_inbox`), cibles de groupe logique
> (REQ-MSG-002), politique de rétention (REQ-MSG-019), sécurité anti double-traduction basée sur
> l'état réel de provider Stage08 (REQ-MSG-007), identité d'approbation de variante réelle
> (REQ-MSG-016). Reste : API (WP14, **construction en cours**), frontend (WP15), qualification live
> complète (WP16), taggage d'ancestry sur événement Discord réellement généré côté production
> (REQ-MSG-030 — **blocage externe documenté**, voir § dédiée). Aucune preuve n'est fabriquée : chaque
> affirmation ci-dessous renvoie à un test réel (PostgreSQL réel, réseau réel, sandbox Discord réel)
> ou est explicitement marquée comme non construite.

| Champ | Valeur |
|---|---|
| Date | `2026-09-01` |
| Base main (départ) | `c41b61ae96cdb1d767c8d924212a6466b768ed60` — le commit de `main` à partir duquel la branche `stage/09-campaigns` a divergé ; `main` a continué d'avancer depuis (voir `git log main` pour son HEAD courant), ce champ documente uniquement le point de divergence, pas un état encore à jour de `main` |
| Branche | `stage/09-campaigns` |
| Statut | `STAGE_09_IMPLEMENTATION_IN_PROGRESS` (Draft PR #9 ouverte, cinquième passe intégrée, CI push+PR verte sur `bfa5706fef4742c7038d78168108cc01d5edf2f2`) |
| Migration | `0021_stage_08 → 0028_stage_09` ; tête unique `0028_stage_09` ; rehearsal up/down/up validé sur PostgreSQL réel à chaque étape |
| Dernière étape intégrée | `STAGE_08_MULTILINGUAL_CONTENT_AND_TRANSLATION_TOPOLOGY` (`stage-08-complete`, inchangée) |

## Passe de remédiation externe (17 findings, intégrée)

Un premier checkpoint (HEAD `94b52a7`) a été publié en Draft PR #9 puis audité par une revue
externe. Toutes les remédiations ci-dessous ont été intégrées avec preuve réelle (jamais une
correction cosmétique) :

1. **Format** : `0022_stage_09_campaign_engine.py` reformaté.
2. **CRITIQUE — intégrité relationnelle DB** : chaque table enfant owner-scoped (schedules,
   triggers, glossaire, variantes approuvées, occurrences) référençait `message_campaigns.id` par
   simple FK, sans jamais prouver que son propre `owner_discord_user_id` correspondait au vrai
   propriétaire de cette campagne. `message_deliveries` prouvait `guild_id` cohérent avec sa cible
   mais jamais `campaign_id`. Migration `0023_stage_09` : FK composites `(owner_discord_user_id,
   campaign_id)` et `(guild_id, campaign_id, target_id)`/`(campaign_id, occurrence_id)`. 8 nouveaux
   tests PostgreSQL négatifs réels prouvent chaque cas cross-owner/cross-campaign nommé par la revue.
3. **Curseur scheduler naive/aware** : `last_cursor_at` était `TIMESTAMPTZ` alors que
   `evaluate_recurring()` le traite comme un curseur local naïf — bug réel de type. Renommé
   `last_cursor_local`, retypé `TIMESTAMP WITHOUT TIME ZONE` (migration `0023_stage_09`) ; le
   constructeur du domaine et `evaluate_recurring()` rejettent maintenant explicitement une valeur
   aware. Preuve : round-trip PostgreSQL réel (persist → claim → finalize → reload → re-evaluate)
   traversant la vraie transition DST 2026 Europe/Paris.
4. **Fencing de claim schedule** : `claim_due_schedules()` ignorait l'état de la campagne
   propriétaire. Joint maintenant `message_campaigns` et ne réclame que les schedules dont la
   campagne est `SCHEDULED_ARMED`/`ACTIVE_RUNNING`. `finalize_schedule_claim()` ajouté, fencé par
   `lease_token` — un worker ayant perdu son bail ne peut plus avancer le curseur.
5. **Fencing de claim delivery** : `message_deliveries` n'avait aucune colonne de bail ; le
   paramètre `lease_owner` de `claim_next_delivery` était silencieusement ignoré. Colonnes
   `lease_owner`/`lease_token`/`leased_until` ajoutées, `claim_next_delivery` reclame le travail
   `CLAIMED` expiré, `mark_delivery_sending()`/`finalize_delivery()` fencés par token — une fois
   `SENDING`, plus jamais réclamable par un claim frais.
6. **AST de condition** : `validate_condition_ast()` existait mais n'était jamais appelée avant
   persistance, et ne bornait ni profondeur ni taille. Appelée maintenant avant chaque
   `create_trigger()` ; profondeur/nombre de nœuds/clauses/longueur de chaîne bornés.
7. **CRITIQUE — `enforce_nonce` (REQ-MSG-029)** : l'affirmation initiale « indisponible dans
   discord.py==2.7.1 » était **FAUSSE** — un grep récursif avait silencieusement échoué sur le
   chemin accentué du dépôt. `discord/http.py::handle_message_parameters()` active
   automatiquement `enforce_nonce=True` dès qu'un nonce est fourni ; `DiscordPyMessageSender.send()`
   le fait déjà. Aucun contournement HTTP bas niveau n'était nécessaire. Preuve directe du payload
   exact + preuve live bout-en-bout via l'adaptateur réel.
8. **Version googletrans dans le benchmark** : `googletrans.__version__` (obsolète en amont,
   rapporte `3.4.0`) remplacé par `importlib.metadata.version("googletrans")` (`4.0.2`, autoritaire) ;
   les deux sont désormais enregistrés pour audit.
9. **Matrice de langues** : benchmark refait sur la matrice complète dirigée FR↔EN↔DE↔ES (12
   directions), avec un corpus rédigé nativement (pas traduit automatiquement) dans chacune des
   quatre langues.
10. **Comptage des appels** : `measurement_records` (une ligne par item×stratégie×direction) séparé
    de `provider_invocations` (le nombre réel d'appels réseau googletrans) — 516 appels réels au
    total sur la matrice complète.
11. **Cohérence de sélection de stratégie** : un seuil de 1500 caractères sans preuve (aucun
    échantillon multi-Ko dans le corpus) basculait vers `PARAGRAPH_GROUPING`. Retiré ;
    `select_translation_strategy()` sélectionne toujours `FULL_MASKED_MESSAGE` jusqu'à preuve
    contraire mesurée.
12. **CRITIQUE — validation structurelle renforcée (REQ-MSG-025)** : `validate_full_pipeline()`
    ajoute un reparse-et-comparaison contre la source originale, en plus de l'intégrité de
    l'ensemble des placeholders. Rejoué sur le benchmark, ce validateur plus rigoureux a **révélé
    une corruption réelle** que l'ancien validateur ne détectait pas : googletrans perd parfois
    l'espace séparant une URL restaurée du texte traduit adjacent, ce qui fait que la valeur
    restaurée se colle au texte voisin et se re-parse comme une URL différente (plus longue). Taux
    mesuré sur les 516 appels réels : 97.2% (FULL_MASKED_MESSAGE/PARAGRAPH_GROUPING/
    SENTENCE_GROUPING) / 66.7% (NAIVE_PER_TEXT_NODE). **Le mécanisme d'échec fermé reste fiable à
    100%** — chaque corruption a été détectée et bloquée, aucune publication silencieuse — mais
    l'affirmation initiale de « 100% d'intégrité » était fausse et a été corrigée partout
    (traçabilité, checklist, code). C'est une découverte réelle du processus de revue, pas une
    régression introduite par la remédiation : le corpus/comportement googletrans n'a pas changé,
    seule la rigueur du validateur a augmenté. **Suite (troisième passe)** : la cause racine a depuis
    été trouvée et corrigée à la source — voir « Root-cause de l'intégrité de traduction » plus bas ;
    la stratégie de production atteint désormais 100.0% d'intégrité réellement mesurée, pas
    seulement une détection fiable à 100%.
13. **Glossaire — tiers GUILD manquant (REQ-MSG-014)** : le texte normatif exige une priorité
    déterministe par « langue/scope/template » ; seuls CAMPAIGN (le tiers « template ») et
    GLOBAL_USER existaient. Tiers GUILD ajouté (migration `0024_stage_09`), avec une politique RLS
    à double condition : une ligne GUILD est visible sous le contexte tenant Guild
    (`app.current_guild_id()`), tandis que GLOBAL_USER/CAMPAIGN restent visibles sous le contexte
    owner — les deux GUC de session étant déjà posés ensemble par `apply_rls_context()` dès qu'un
    appelant ouvre un `TenantContext(guild_id, user_id=owner_id)`. Priorité : CAMPAIGN > GUILD >
    GLOBAL_USER. Preuve PostgreSQL réelle de la politique à double condition.
14. **`REPLACE_ALL`** : `to_discord_kwargs()` traitait silencieusement `REPLACE_ALL` exactement
    comme `PRESERVE_EXISTING` (aucun moyen de fournir un contenu de remplacement réel).
    `EditPayload` exige maintenant un `new_attachments` non vide pour `REPLACE_ALL` (rejeté à la
    construction sinon) ; `DiscordPyMessageSender.edit()` convertit chaque `NewAttachment` en vrai
    `discord.File` avant envoi. Preuve au niveau adaptateur.
15. **Requalification de traçabilité** : 10 lignes REQ-MSG re-auditées avec preuve mise à jour ;
    REQ-MSG-029 passe `PARTIALLY_IMPLEMENTED → IMPLEMENTED` (correction `enforce_nonce`) ;
    REQ-MSG-025 restait alors `PARTIALLY_IMPLEMENTED` avec la preuve honnête corrigée (pas 100%,
    avec fail-closed 100% fiable) — **passée `IMPLEMENTED` durant la troisième passe** une fois la
    cause racine corrigée (voir plus bas) ; REQ-MSG-014 confirmé `IMPLEMENTED` avec le tiers GUILD
    réel.
16. **`scripts/validate_stage.py 09`** : ajouté réellement (steps par défaut + profils
    `translation-benchmark --allow-network` et `failure-injection` + `--include-discord-live`) et
    **exécuté avec succès** (`python scripts/validate_stage.py 09` → PASS complet : build Docker,
    migrations 0022→0024 avec rehearsal, 126 tests d'intégration incluant Stage09, build frontend,
    secret scan, validation documentation, tests unitaires/PostgreSQL Stage09 dédiés, qualification
    live SKIPPED par défaut).
17. **Qualification live Stage09 réelle** : `scripts/validate_discord_live_stage09.py` créé et
    **exécuté avec `--include` sur le sandbox réel** : 5/5 scénarios PASS (envoi immédiat
    allowed_mentions=none, edit possédé, delete possédé, dédup même nonce, nonce différent crée un
    message distinct) via le vrai `DiscordPyMessageSender`. Preuve sanitisée committée
    (`docs/90_handoffs/evidence/stage09/discord-live-stage09.json`), portée explicitement limitée
    (pas la matrice complète, qui nécessite l'orchestration bout-en-bout absente).

## Quatrième passe — remédiation externe et orchestration WP12 réelle

1. **CRITIQUE — identité de job de livraison** : `submit_delivery_to_governor` construisait un
   `WorkloadJob` nommant `delivery_id=A`, mais son opération appelait
   `process_one_pending_delivery(guild_id)`, qui réclame N'IMPORTE QUELLE livraison `PENDING`
   suivante — un job retardé/rejoué/périmé pour A pouvait donc consommer B. Corrigé par
   `CampaignsRepository.claim_delivery` (identité nommée, même fencing que `claim_next_delivery`) et
   `did.campaigns.delivery_worker.process_delivery`. 9 tests PostgreSQL réels prouvent l'isolation A/B,
   le replay après SENT, et une vraie course concurrente.
2. **Résultat de fencing de finalisation ignoré** : `_send_and_finalize` ignorait le booléen retourné
   par `finalize_delivery()`. Vérifié maintenant sur chaque issue (SENT/FAILED/UNKNOWN) ; un nouveau
   `STALE_OUTCOME` est renvoyé au lieu de mentir sur un résultat durable quand le fencing a été perdu
   (ex. un reconciler vole le bail pendant que l'envoi original est encore en vol) — jamais de nonce
   neuf, jamais d'envoi en double. 3 tests PostgreSQL réels injectent la course exacte (vol de bail
   pendant `send()`) pour chacune des trois issues.
3. **Classification réelle des erreurs discord.py** : l'adaptateur ne traduisait jamais la vraie
   hiérarchie d'exceptions discord.py. Classifie maintenant par statut HTTP réel : 4xx (hors 429)
   devient `DiscordSendError` (échec définitivement connu) ; 429/5xx restent ambigus (propagent tels
   quels, cohérent avec le fait que discord.py gère déjà ses propres retries de rate-limit en
   interne). Preuve au niveau adaptateur (7 tests) et au niveau pipeline complet worker+adaptateur
   (3 tests).
4. **Autorisation à la création complétée** : `channel_belongs_to_guild`/`resource_type`/
   `translation_group_belongs_to_guild` prouvent maintenant l'appartenance réelle à la Guild via
   l'état Stage04/08 faisant autorité (pas seulement l'id fourni par l'appelant) ; le contrôle
   bot-can-send est explicitement un preflight non bloquant à la création (REQ-MSG-003 place
   l'application dure au moment de la livraison). 20 tests, cross-Guild channel/category/Translation
   Group négatifs, mauvais type dans les deux sens, preflight non bloquant.
5. **Orchestration WP12 réelle** — le plus gros écart signalé par les trois passes précédentes :
   - `did.campaigns.activation.fan_out_occurrence` : occurrence → livraisons, idempotent et
     restart-safe via un cycle de bail `CLAIMED → FANNED_OUT/FAILED` réutilisant des colonnes de bail
     provisionnées dès WP1 (migration `0022`) mais jamais câblées jusqu'à cette passe.
   - `did.campaigns.rendering` : pipeline de rendu à deux couches (variables de template puis
     glossaire), composant `did.messaging.protector`/`template_variables`/`glossary` sans dupliquer
     leur logique. A révélé et corrigé un vrai faux positif d'intégrité croisée entre couches (voir
     ci-dessous).
   - `did.campaigns.scheduler_loop.run_scheduler_tick` : cycle réel claim → évalue (RRULE/misfire) →
     fan-out par occurrence due → finalise le curseur, fencé de bout en bout par le même
     `lease_token`.
   - `did.campaigns.event_consumer.consume_event_for_trigger` : consomme la vraie forme
     `did.domain.discord_runtime.EventEnvelope`, câble `should_trigger`/déduplication/création
     d'occurrence.
   - `did.campaigns.simulation.simulate_campaign` : compose les trois modules précédents en une preview
     complète et non mutante (voir REQ-MSG-022 ci-dessous).
   Preuve PostgreSQL réelle avec de vrais scénarios de crash/redémarrage/course :
   `test_stage09_activation_postgres.py` (7 tests), `test_stage09_scheduler_loop_postgres.py`
   (3 tests), `test_stage09_event_consumer_postgres.py` (8 tests).
6. **Faux positif d'intégrité inter-couches (découvert en construisant `rendering.py`)** : la
   composition séquentielle protection-variables puis protection-glossaire partage la même forme de
   placeholder (`DIDPHxxxx...`) — la couche glossaire voyait les placeholders encore présents de la
   couche variables et les signalait à tort comme « inventés ». Corrigé par un nouveau paramètre
   `foreign_placeholders` sur `validate_and_restore`/`validate_full_pipeline`, permettant à une couche
   externe de déclarer les tokens qu'une couche interne ne doit jamais classer comme invention.
   10 tests dédiés (`test_stage09_rendering.py`).
7. **Corpus de benchmark étendu (REQ-MSG-024/025/026)** : de 6 à 26 classes normatives par langue
   (104 items au total, rédigés nativement — pas traduits automatiquement) — phrases courtes/longues,
   négation/pronoms, multi-phrases/multi-paragraphes, listes/emphase Markdown, URLs adversariales,
   texte `@everyone`/`@here` littéral, emoji statiques/animés, timestamps multiples, commandes slash,
   phrase dense multi-placeholders, terminologie/noms propres/acronymes, code mixte, styles
   embed/bouton, contenu long (multi-Ko). Rejoué en entier : voir « Requalification du benchmark »
   ci-dessous.
8. **Bug réel révélé en construisant `event_consumer.py`** : reconstruire un `TriggerSourceBinding`
   directement depuis une ligne DB brute (`source_scope_kind=row["source_scope_kind"]`, une chaîne)
   faisait silencieusement échouer la comparaison `is TriggerSourceScopeKind.GUILD` interne à
   `should_trigger` (une chaîne n'est jamais `is` un membre d'énumération, même si elle est égale en
   valeur). Corrigé par un cast explicite `TriggerSourceScopeKind(row["source_scope_kind"])`. Cette
   classe de bug est invisible à tout test unitaire pur construisant ses objets Python à la main —
   seul un aller-retour DB réel la révèle ; un test dédié le prouve explicitement.
9. **Bug réel révélé en construisant `scheduler_loop.py`** : la clause `RETURNING` de
   `claim_due_schedules` omettait `fire_at`, rendant l'assertion `schedule.fire_at is not None` de
   `evaluate_one_shot` invérifiable pour tout appelant reconstruisant le schedule depuis la ligne
   réclamée. Corrigé en ajoutant `s.fire_at` à la clause `RETURNING`.

## Cinquième passe — connexion au runtime réel, transport Stage03, groupes logiques, rétention

Le plus gros écart laissé par la quatrième passe était que l'orchestration WP12 (`fan_out_occurrence`,
`run_scheduler_tick`, `consume_event_for_trigger`, `simulate_campaign`) était réelle et testée, mais
**aucune transition n'était atteignable autrement qu'en appelant la fonction à la main depuis un
test** — `did.runtime.py` ne connaissait pas le Campaign Engine. Cette passe ferme cet écart et
plusieurs failles de fencing/sécurité découvertes en le fermant.

1. **Connexion au runtime réel (CRITIQUE)** : `did.campaigns.runtime.CampaignSchedulerRuntime`
   compose `run_scheduler_tick` (décision de schedule) + `event_transport.consume_new_events_for_guild`
   (décision d'événement) + `dispatch.route_pending_deliveries_to_jobs` (routage durable) en une
   boucle de polling unique (`tick()`/`run()`), exécutée dans le process "scheduler" existant, aux
   côtés de `ReconcileScheduler`, via `asyncio.gather` — jamais un second process, jamais un second
   bot/token Discord, jamais une politique de gouverneur parallèle. Côté worker, `DurableDiscordIOWorker`
   route désormais un `workload_type="SEND_CAMPAIGN_MESSAGE"` vers un nouveau `CampaignDeliveryExecutor`
   qui appelle `process_delivery(delivery_id=<identité exacte du job leasé>)` — jamais
   `process_one_pending_delivery` pour un job nommé. Preuve : `test_stage09_durable_dispatch_postgres.py`
   construit un vrai `DurableDiscordIOWorker` avec l'exécuteur branché et fait tourner
   `run_guild_once()` de bout en bout.
2. **Dispatch durable de livraison** : `did.campaigns.dispatch.enqueue_delivery_job` crée un
   `discord_io_job` durable dont l'identité logique est le `delivery_id` (jamais un identifiant
   synthétique) ; `route_pending_deliveries_to_jobs` route en lot les livraisons en attente. Fencing à
   deux niveaux documenté explicitement dans le code : le job durable est un signal grossier « tente
   maintenant » ; le bail/état propre de `message_deliveries` (`claim_delivery`/`mark_delivery_sending`/
   `finalize_delivery`) reste l'unique source de vérité — `CampaignDeliveryExecutor.execute_leased`
   complète toujours normalement le job quelle que soit l'issue réelle de la livraison, pour que le
   mécanisme de retry du job durable ne combatte jamais la réconciliation indépendante de
   `message_deliveries`. **Bug réel révélé en écrivant ce chemin pour la première fois** :
   `ck_discord_io_jobs_priority` (héritée de Stage03) bornait la priorité à `0..5` alors que
   `WorkloadPriority.SEND_CAMPAIGN_MESSAGE=6` existait déjà — jamais aucun test avant cette passe
   n'avait réellement inséré un job Stage09 dans `discord_io_jobs`. Corrigé par la migration
   `0026_stage_09` (élargissement `0..6`, réversible).
3. **Fencing de fan-out d'occurrence** : `fan_out_occurrence` ignorait le booléen retourné par
   `finalize_occurrence_fanout()`. Un heartbeat de renouvellement de bail (même pattern que
   `DurableDiscordIOWorker._execute_with_lease_heartbeat`) tourne désormais en parallèle de
   l'expansion des destinations ; une perte de bail lève `FanOutLeaseLostError` au lieu de rapporter
   un faux succès. Preuve : `TestFanOutLeaseFencing` — vol de bail réel via `UPDATE` SQL admin
   backdatant `leased_until` en plein rendu, et renouvellement à travers un fan-out volontairement
   ralenti.
4. **Faille `event_type` non vérifiée (CRITIQUE, sécurité)** : `TriggerEvaluationContext` ne portait
   pas `event_type`, et `should_trigger` ne comparait jamais `trigger.event_type` à celui de
   l'événement reçu — un trigger configuré sur `MEMBER_JOIN` aurait pu se déclencher sur n'importe
   quel autre type d'événement partageant la même source/condition. Corrigé en premier contrôle de
   `should_trigger` (avant binding, avant condition). Régression dédiée dans
   `test_stage09_causality.py` et `test_stage09_event_consumer_postgres.py` prouvant qu'un type
   d'événement erroné ne déclenche jamais, même avec binding/condition/payload par ailleurs valides.
5. **Owner non fiable côté consommation d'événement** : `consume_event_for_trigger` acceptait un
   `owner_discord_user_id` fourni par l'appelant au lieu de le dériver du trigger chargé durablement.
   Signature réécrite pour dériver l'appartenance exclusivement de `trigger.owner_discord_user_id` ;
   toutes les valeurs de contexte (`event_id`, `guild_id`, `event_type`, `causation_depth`, `payload`,
   `correlation_id`) sont désormais lues du vrai `EventEnvelope` de Stage03, jamais reconstruites à la
   main par l'appelant.
6. **Transport d'événement Stage03 réel** : `did.campaigns.event_transport.consume_new_events_for_guild`
   lit le vrai `discord_gateway_inbox` via un curseur durable par Guild
   (`message_campaign_event_cursor`, `(guild_id PK, last_event_received_at, last_event_id)`, migration
   `0028_stage_09`), reconstruit un `EventEnvelope` réel depuis la ligne brute, résout les triggers
   candidats par `event_type` exact (`CampaignsRepository.list_candidate_triggers_for_event`, jointure
   cross-authority admin-scoped `message_campaign_triggers` × `message_campaign_trigger_sources`), fait
   correspondre la source déclarée via `TriggerSourceBinding.matches` (GUILD scope matche sans
   ressource ; CHANNEL/CATEGORY exige l'id exact), déclenche le fan-out, et avance le curseur — sans
   second bus d'événements, sans logique de transport dupliquée. Prouvé pour survie à un crash avant
   consommation et à un rejeu du même événement (`test_stage09_event_transport_postgres.py`). Le
   contenu de message (MESSAGE_CREATE) reste hors périmètre captable par construction — voir la
   section blocage externe ADR-008 plus bas.
7. **Trois bugs réels supplémentaires trouvés et corrigés en écrivant les tests d'intégration
   PostgreSQL réels de cette passe** (aucun contourné, tous corrigés à la racine avec régression
   dédiée) :
   - **Traduction multi-langue** : `fan_out_occurrence` prenait un unique callable
     `translate_masked_text` réutilisé pour tout le fan-out, quelle que soit la langue de chaque
     destination — un vrai provider aurait silencieusement traduit toutes les destinations vers la
     même langue. Renommé `translate_masked_text_for_language: Callable[[str], TranslateMaskedText]`,
     invoqué une fois par destination avec sa propre langue résolue.
   - **Collision de `delivery_key` (LOGICAL_GROUP)** : plusieurs destinations LOGICAL_GROUP partagent
     `language_profile_id=None`, donc collisionnaient sur la même clé et `ON CONFLICT DO NOTHING`
     supprimait silencieusement les doublons apparents. Corrigé en ajoutant `discord_channel_id` à la
     clé.
   - **Troncature `VARCHAR(128)` de `delivery_key`** : après l'ajout du channel id, la clé brute d'une
     occurrence événementielle (deux UUID) dépassait la colonne `VARCHAR(128)`, provoquant un vrai
     `StringDataRightTruncationError` en production de test. Corrigé en hachant la clé entière
     (`hashlib.sha256(...).hexdigest()`, 64 caractères fixes) plutôt qu'en la concaténant brute.
8. **REQ-MSG-002 (groupes logiques)**, **REQ-MSG-019 (rétention)**, **REQ-MSG-007 (sécurité anti
   double-traduction)** et **REQ-MSG-016 (identité d'approbation de variante)** : voir le détail
   fichier:ligne + tests dans `docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md`. En résumé :
   `did.campaigns.logical_groups.expand_logical_group` réutilise l'abstraction Stage04 existante
   (jamais une hiérarchie Discord inventée) ; `did.campaigns.retention.RetentionPolicy` +
   `purge_expired_deliveries` sont bornés (1..3650 jours), scopés Guild/owner, et ne touchent jamais un
   état actif/UNKNOWN/intervention ; `did.campaigns.translation_group_safety
   .evaluate_translation_group_safety` utilise l'état réel de `translation_provider_bindings.status`
   Stage08 et échoue fermé (`MANUAL_CONFIGURATION_REQUIRED`) faute de garantie non-invasive qu'un
   provider externe lié ne re-traduit pas les propres publications de DID ; le raccourci
   `approve_fresh_translations` (auto-approbation au nom du owner, sans revue humaine réelle) est
   supprimé — `approve_variant` exige désormais un principal approbateur explicite et distinct.
9. **Gap d'autorisation à la création pour LOGICAL_GROUP** : découvert en fin de passe en préparant
   l'API — `create_authorized_campaign_target` ne branchait jamais sur `TargetKind.LOGICAL_GROUP`
   (ajouté plus tôt dans cette même passe pour REQ-MSG-002), ce qui aurait levé un `AssertionError` au
   premier essai de création réelle. Corrigé par
   `CampaignGuildAuthorizationChecker.logical_group_belongs_to_guild` + la branche manquante, avec 3
   tests dédiés (attache autorisée, groupe logique cross-Guild rejeté, id inconnu rejeté).

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

**`enforce_nonce` est réellement disponible et actif** (corrigé pendant la deuxième passe de
remédiation — voir finding 7 ci-dessous pour l'historique complet de la correction) :
`discord/http.py::handle_message_parameters()`, la fonction que traverse tout appel
`Messageable.send()` y compris `DiscordPyMessageSender.send()`, active automatiquement
`payload['enforce_nonce'] = True` dès qu'un nonce est fourni. Chaque envoi de campagne bénéficie
donc déjà du contrat de déduplication documenté par Discord ; aucun contournement HTTP bas niveau
n'est nécessaire. Preuve directe du payload exact (`test_stage09_discord_message_sender.py`) et
preuve live bout-en-bout via l'adaptateur réel contre le sandbox
(`docs/90_handoffs/evidence/stage09/nonce-reconciliation-probe.json`, zéro secret/id/PII) : même
nonce → un seul message ; nonce différent → message distinct.

`Message.nonce` reste absent de `fetch_message()`/`history()` (présent uniquement sur la réponse
immédiate d'envoi) — une réconciliation par recherche d'historique ne fonctionne donc toujours pas
contre l'API réelle et n'est pas utilisée. `did.campaigns.delivery_reconciliation
.decide_unknown_outcome_recovery()` renvoie avec le nonce déjà stocké et le `content_snapshot` déjà
stocké (jamais un contenu re-rendu), dans une fenêtre conservatrice bornée (Discord documente le
contrat comme couvrant « les quelques dernières minutes » sans borne exacte publiée — la fenêtre de
5 minutes est une interprétation prudente de ce contrat documenté-mais-imprécis, jamais présentée
comme la garantie exacte de Discord) et 3 tentatives ambiguës maximum, au-delà de quoi
`INTERVENTION_REQUIRED`. Cette décision est maintenant réellement câblée dans le worker de livraison
(WP13, voir plus bas) : `did.campaigns.delivery_worker.reconcile_one_stalled_delivery` récupère à la
fois le cas où le worker a crashé avant de finaliser (toujours `SENDING`) et le cas normal où le
worker a lui-même intercepté l'exception ambiguë et déjà finalisé en `UNKNOWN` — jamais un nonce
neuf n'est généré pour une reprise.

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

`scripts/run_translation_benchmark.py` a exécuté, sur le corpus étendu à 26 classes/104 items
(quatrième passe), **1 950 vrais appels réseau** googletrans sur la matrice complète dirigée
FR↔EN↔DE↔ES (12 directions, corpus rédigé nativement dans chacune des quatre langues, 4 stratégies) —
preuve committée `docs/90_handoffs/evidence/stage09/translation-benchmark.json`
(`generated_at: 2026-08-31T20:33:05Z`, `corpus_version: 3`). Résultat mesuré :

| Stratégie | Mesures | Appels provider | Erreurs | Intégrité | Latence moy. |
|---|---|---|---|---|---|
| `FULL_MASKED_MESSAGE` (production) | 312 | 312 | 0 | **100.0 %** (312/312) | 0.708 s |
| `PARAGRAPH_GROUPING` | 312 | 336 | 0 | **100.0 %** (312/312) | 0.748 s |
| `SENTENCE_GROUPING` | 312 | 534 | 0 | **100.0 %** (312/312) | 1.188 s |
| `NAIVE_PER_TEXT_NODE` (contrôle négatif) | 312 | 768 | 0 | 98.08 % (306/312) | 1.584 s |

`FULL_MASKED_MESSAGE` (la stratégie de production) atteint une intégrité technique réellement
mesurée de 100.0 % sur ce corpus élargi, avec le moins d'appels provider et la latence la plus
faible. `NAIVE_PER_TEXT_NODE` (jamais sélectionné pour la production) dégrade mesurablement sur ce
corpus plus large et plus divers — preuve empirique concrète, pas seulement théorique, de la mise en
garde contre la traduction fragment par fragment (REQ-MSG-023).
`select_translation_strategy()` choisit toujours `FULL_MASKED_MESSAGE` — aucun seuil de longueur ou
de classe de contenu n'est appliqué sans preuve mesurée qui le justifierait (voir REQ-MSG-026).

### WP11 — Variantes approuvées

`backend/src/did/campaigns/approved_variants.py`. `compute_source_fingerprint()` est un sha256 sur
le JSON canonique (clés triées) du `message_model` — insensible à l'ordre des clés.
`resolve_variant_for_delivery()` retourne `REUSABLE`/`STALE`/`MISSING` ; une campagne récurrente
inchangée reste `REUSABLE` à travers ses occurrences (testé), tandis qu'un changement de source
rend l'ancienne approbation `STALE` sans jamais la réutiliser silencieusement ni retraduire
silencieusement.

### WP13 — Worker de livraison réel (troisième passe)

`backend/src/did/campaigns/delivery_worker.py`. Implémente le pipeline réel
claim→mark SENDING→send→finalize : `process_one_pending_delivery` réclame une livraison
`PENDING`/`CLAIMED` expirée, persiste durablement un nonce frais dans la même transition fencée
`mark_delivery_sending`, envoie via le port `DiscordMessageSender` existant, puis finalise —
`SENT`/`FAILED` correctement distingués d'`UNKNOWN_OUTCOME` (toute exception qui n'est pas la
`DiscordSendError` propre à la librairie est traitée comme ambiguë, jamais comme un simple échec).
`reconcile_one_stalled_delivery` récupère à la fois le cas où le worker a crashé avant de finaliser
(toujours `SENDING`, via `claim_stalled_sending_for_reconciliation`) et le cas normal où le worker a
lui-même intercepté l'exception ambiguë et déjà finalisé en `UNKNOWN` (via la nouvelle
`claim_unknown_deliveries_for_reconciliation`) — les deux alimentent la décision de
`did.campaigns.delivery_reconciliation` à partir de l'horodatage réel de la tentative originale,
jamais un nonce neuf.

Un nouveau palier `WorkloadPriority.SEND_CAMPAIGN_MESSAGE` (ajouté en fin d'énumération, aucune
valeur existante renumérotée) route chaque envoi de campagne à travers le `DiscordWorkloadGovernor`
partagé — le fan-out en masse d'une campagne est donc soumis à l'équité par Guild et à la limite de
concurrence globale déjà en place pour tous les autres types de travail Discord. Prouvé par une
suite de fairness/charge dédiée (`tests/load/test_stage09_campaign_fairness_load.py`, en mémoire,
3 tests) montrant qu'un arriéré de 500 envois de campagne ne retarde jamais un apply structurel ou
un reconcile critique du même Guild, ni le partage équitable d'un autre Guild.

**Preuve PostgreSQL réelle** : `test_stage09_delivery_worker_postgres.py` (20 tests après la
quatrième passe), incluant une vraie course à deux workers concurrents (`asyncio.gather`) sur la
même livraison (exactement un seul envoi réel), l'isolation d'identité nommée à deux livraisons, et
une course de vol de bail pendant `send()` pour les trois issues (voir « Quatrième passe » ci-dessus).

Le service amont qui décide QUAND créer une ligne `message_deliveries` depuis un schedule dû ou un
événement accepté existe désormais et est prouvé de bout en bout — voir « Orchestration WP12 réelle »
dans la section « Quatrième passe » ci-dessus (`did.campaigns.activation.fan_out_occurrence`,
`did.campaigns.scheduler_loop.run_scheduler_tick`, `did.campaigns.event_consumer
.consume_event_for_trigger`).

## Root-cause de l'intégrité de traduction (troisième passe, REQ-MSG-025)

La benchmark renforcée (deuxième passe) avait mesuré 97.2% d'intégrité — un vrai finding, pas
accepté silencieusement. Cette passe en a trouvé et corrigé la cause racine : googletrans perd
régulièrement l'espace précédant une ponctuation finale de phrase (`.`, `,`, `;`, `:`, `!`, `?`)
quand un placeholder URL termine la phrase dans l'ordre des mots de la langue cible (reproduit en
direct : EN→DE, « ... unter DIDPH0000QxxxxZH. » sans espace avant le point). Comme la classe de
caractères de l'URL doit légitimement autoriser le point (domaines, chemins), la regex gourmande non
filtrée absorbait cette ponctuation collée lors du reparse, produisant une valeur différente de
l'originale — correctement détectée comme falsifiée par `validate_reparsed_structure`, mais évitable.

Corrigé à la source dans `did.messaging.parser.parse` : un match URL retire maintenant la
ponctuation finale de phrase un caractère à la fois (`_trim_url_trailing_punctuation`), à l'identique
au parse initial et au reparse — l'heuristique standard de « trim de ponctuation finale » des
auto-linkers de production (GitHub, Slack, Twitter), pas une astuce d'espacement autour du
placeholder. Jamais de suppression aveugle d'espaces : seule la ponctuation finale d'un match URL
est concernée, la grammaire/ponctuation légitime environnante n'est jamais touchée.

Testé par property/fuzz (`test_stage09_parser_protector.py::TestUrlTrailingPunctuationTrim`),
incluant une reproduction directe de la corruption observée en direct, un test Hypothesis fuzzant des
scénarios de collage MT, et (quatrième passe) 13 tests adversariaux supplémentaires
(`TestUrlTrailingPunctuationTrimAdversarialRobustness`) couvrant la ponctuation multiple, les URLs
avec query string/fragment se terminant par de la ponctuation légitime, et les parenthèses/guillemets
englobants. La matrice complète a d'abord été rejouée sur les 516 appels du corpus alors en vigueur
(72/72, 100.0% pour les trois stratégies non-naïves), puis **requalifiée en quatrième passe sur le
corpus étendu à 26 classes/104 items** (1 950 appels réels) — voir le tableau détaillé dans « WP10 —
Benchmark réel » ci-dessus. `FULL_MASKED_MESSAGE` (stratégie de production) reste à **100.0%
d'intégrité technique réellement mesurée** sur ce corpus élargi, plus divers, incluant de nouvelles
classes adversariales (312/312 mesures, 0 erreur) —
`docs/90_handoffs/evidence/stage09/translation-benchmark.json`. `NAIVE_PER_TEXT_NODE` (le contrôle
négatif délibérément non-production) mesure 98.08% sur ce corpus élargi (contre 66.7% sur l'ancien
corpus plus étroit — les deux chiffres ne sont pas directement comparables, chaque corpus mesure une
distribution de contenu différente) — attendu, sans effet sur l'exigence, que la stratégie de
production satisfait maintenant exactement sur le corpus normatif actuel.

## Suite de tests réelle (exécutée après cette cinquième passe)

| Gate | Résultat |
|---|---|
| `uv run pytest backend/tests/unit/` (régression complète) | **731 passed** |
| `DID_RUN_INTEGRATION=1 uv run pytest backend/tests/integration/` (régression complète, PostgreSQL réel) | **207 passed** |
| `uv run ruff check .` (tout le dépôt) | PASS, 0 finding |
| `uv run ruff format --check .` | PASS |
| `uv run mypy src/did` (mode strict) | PASS, 0 erreur, 157 fichiers |
| `uv run python scripts/check_secrets.py` | PASS, 428 fichiers vérifiés |
| `uv run python scripts/validate_documentation.py` | PASS — Stages 11, Source REQ 246, Traced REQ 246, ADR expected 35 |
| CI GitHub Actions (push + pull_request) sur `bfa5706fef4742c7038d78168108cc01d5edf2f2` | PASS, les deux déclencheurs |

Le corpus de benchmark de traduction (26 classes/104 items, 1 950 appels réels, intégrité 100%,
stratégie de production, 0 erreur) n'a pas été rejoué cette passe faute de modification du pipeline de
traduction/masquage lui-même ; voir la quatrième passe pour le détail complet et
`docs/90_handoffs/evidence/stage09/translation-benchmark.json` pour la preuve committée. Ces profils
`validate_stage.py` n'ont pas été relancés dans leur intégralité (Docker/migrations/build frontend)
durant cette cinquième passe faute de régression attendue dans leur périmètre propre ; la régression
réelle du code qu'ils couvrent est prouvée par les lignes ci-dessus (pytest direct, ruff, mypy, doc
validation, secret scan, CI réelle).

## Qualification live Discord réelle

`scripts/validate_discord_live_stage09.py` exécute le vrai `DiscordPyMessageSender` contre le
sandbox Guild A réel (salon temporaire créé/supprimé, contenu synthétique uniquement, zéro
secret/id/PII committé) : **5/5 scénarios PASS** (envoi immédiat allowed_mentions=none, edit
possédé, delete possédé, dédup même nonce, nonce différent crée un message distinct) — preuve
committée (`docs/90_handoffs/evidence/stage09/discord-live-stage09.json`). Skip par défaut sans
`--include`, comme tous les autres validateurs live du dépôt. La matrice complète (Guild A/B,
scheduler, Translation Groups, quatre langues, provider externe présent/absent) **n'a toujours pas
été exécutée** — l'orchestration bout-en-bout (WP12) existe désormais et est prouvée sur PostgreSQL,
mais l'exercer authentiquement bout-en-bout via la matrice complète nécessite encore l'API/frontend
(WP14/15), qui n'existent pas.

## Écarts connus (non dissimulés)

1. **WP14 (API)** : aucun router FastAPI Stage09 n'existait avant cette passe ; construction en
   cours (voir le champ Statut en tête de document pour l'état exact à la date indiquée).
2. **WP15 (Frontend)** : aucune UI Stage09.
3. **Taggage d'ancestry sur événement Discord réellement généré côté production (REQ-MSG-030) —
   BLOCAGE EXTERNE, PAS UN ÉCART DE CODE** : la garde anti-boucle côté consommation est désormais
   réelle et branchée sur le vrai transport Stage03 (voir « Cinquième passe » ci-dessus). Ce qui
   reste manquant est de tagger `did_campaign_ancestry` sur l'événement gateway résultant d'un envoi
   de campagne réel lorsqu'il ré-entre l'ingestion Stage03 — cela requiert que Stage03 capte
   effectivement cet événement, ce qui requiert un dispatch Gateway porteur de contenu de message
   (`MESSAGE_CREATE` au minimum). `did.bot.gateway.client.minimal_gateway_intents()` ne demande
   délibérément jamais aucun intent de message, conformément à `ADR-008` (« Intents minimaux » : ne
   jamais demander un intent privilégié avant d'avoir une fonctionnalité documentée qui en dépend) —
   `discord_gateway_inbox`/`SUPPORTED_DISPATCHES` ne peuvent donc structurellement pas contenir
   `MESSAGE_CREATE` aujourd'hui. Fermer cet écart exige une décision produit/architecture délibérée de
   demander l'intent privilégié `MESSAGE_CONTENT` (avec ses propres conséquences d'approbation/
   vérification sur le Discord Developer Portal) spécifiquement pour cette fonctionnalité — exactement
   le type de décision qu'`ADR-008` réserve à une fonctionnalité documentée, pas quelque chose qu'une
   session de code peut ou doit contourner silencieusement. En attendant cette décision, les événements
   externes ordinaires continuent de fonctionner correctement et les boucles cross-owner/cross-Guild/
   auto-déclenchement restent entièrement bloquées côté consommation ; seul l'auto-déclenchement d'une
   campagne sur son propre message envoyé ne peut pas encore être tagué à la source.
4. **WP16 (Live)** : 5 scénarios ciblés réels PASS (voir ci-dessus) ; pas la matrice complète (bloquée
   par l'absence d'API/frontend pour l'exercer authentiquement via le vrai chemin produit).
5. **Revue sémantique humaine** : aucune évaluation humaine n'a eu lieu ; aucun score n'est
   fabriqué. À marquer `PENDING_HUMAN_REVIEW` si/quand une rubrique est requise — dimension séparée
   de l'intégrité technique, qui elle est mesurée machine à 100%.
6. **REQ-MSG-007/016** : UI de sélection explicite des 4 modes de publication et de review/approbation
   de variantes non construite (le backend/la sécurité sous-jacente sont désormais réels — voir
   « Cinquième passe » — mais REQ-MSG-007/016 restent des exigences produit/UI, pas seulement backend).

Voir `docs/10_implementation/STAGE09_REQUIREMENTS_CHECKLIST_LOCAL.md` pour la matrice complète des
31 IDs et `docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md` pour la preuve fichier:ligne de
chacun.
