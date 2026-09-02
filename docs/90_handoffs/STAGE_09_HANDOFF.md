# Handoff STAGE 09 — Message & Campaign Engine, automatisations et traduction sûre

> **Ce bandeau et la section « État actuel (vérité unique) » juste en dessous sont la SEULE source de
> vérité sur l'état courant de Stage09.** Toutes les sections « Nème passe » plus bas dans ce document
> sont un journal **historique** conservé pour la traçabilité de la démarche — elles décrivent l'état
> au moment où chaque passe a été écrite et peuvent contenir des chiffres, des têtes de migration ou
> des statuts depuis dépassés (ex. « `0029_stage_09` », « six passes », « surfaces d'authoring
> absentes »). En cas de divergence entre une section historique et cette section, **cette section fait
> foi**.

> **Statut :** `STAGE_09_BLOCKED_TRANSLATION_PROVIDER_UNAVAILABLE`. Un audit externe a trouvé un vrai
> défaut fail-open dans l'adaptateur de traduction de production (voir ci-dessous) — **corrigé** cette
> passe. Une fois corrigé, une tentative réelle a révélé que le provider `googletrans` réel est
> actuellement **indisponible** dans ce sandbox réseau (HTTP 429/403 réels contre l'endpoint Google).
> Ce n'est PAS un défaut de code DID — DID échoue désormais correctement fermé au lieu d'accepter
> silencieusement l'écho comme une traduction réussie — mais tant que le provider externe reste
> indisponible, **le canal d'acceptation de traduction réelle Stage09 n'est pas satisfait**, et
> Stage09 n'est PAS déclaré complet. **PR #9 reste Draft, `DO NOT MERGE — EXTERNAL AUDIT REQUIRED`.**

## État actuel (vérité unique)

| Champ | Valeur |
|---|---|
| Date | `2026-09-02` |
| HEAD final (cette passe de remédiation) | le commit qui contient exactement ce texte est par construction le dernier commit poussé de cette passe -- voir `git log -1 --format=%H` sur `stage/09-campaigns`, identique au head affiché sur PR #9 après le push de cette passe |
| Base main (départ) | `c41b61ae96cdb1d767c8d924212a6466b768ed60` — le commit de `main` à partir duquel la branche `stage/09-campaigns` a divergé ; `main` a continué d'avancer depuis (voir `git log main` pour son HEAD courant), ce champ documente uniquement le point de divergence, pas un état encore à jour de `main` |
| Branche | `stage/09-campaigns` |
| PR | #9, Draft, ouverte, non mergée |
| Statut `CURRENT_STATE` | `STAGE_09_BLOCKED_TRANSLATION_PROVIDER_UNAVAILABLE` (voir `docs/10_implementation/00_CURRENT_STATE.md`) — **régression délibérée depuis `STAGE_09_COMPLETE_DRAFT_PR_OPEN`** ; Stage09 n'est PAS déclaré complet tant que cette clause externe reste bloquée |
| Migration | `0021_stage_08 → 0032_stage_09` ; tête unique `0032_stage_09` (32 migrations Stage09, 33 fichiers avec `__init__.py`) ; rehearsal `downgrade base → upgrade head → downgrade 0001_stage_01 → upgrade head` validé sur PostgreSQL réel ; **inchangée cette passe** |
| REQ-MSG | 31/31 `IMPLEMENTED`, 0 `PARTIALLY_IMPLEMENTED`, 0 `NOT_STARTED` (inchangé -- REQ-MSG-009 reste structurellement `IMPLEMENTED`, l'exigence ne mande pas la disponibilité continue d'un tiers externe, mais le gate d'acceptation live Stage09 de traduction réelle est distinct et lui N'EST PAS satisfait tant que le provider est indisponible) |
| **Root cause corrigée (fail-open googletrans)** | `did.translation.googletrans_adapter.GoogletransCampaignTranslationProvider` construisait `googletrans.Translator()` avec ses défauts, dont `raise_exception=False` -- une réponse HTTP non-200 de l'endpoint de traduction renvoyait alors silencieusement le sentinel interne `DUMMY_DATA` de `googletrans`, dont le texte traduit est **l'entrée elle-même ré-échoïsée**, indiscernable d'une traduction réussie. **Corrigé** : `_production_translator()` construit désormais `Translator(raise_exception=True)`, plus une vérification défensive indépendante du statut HTTP réel attaché au résultat (`result._response.status_code`) avant de faire confiance à `result.text` -- une vraie panne échoue maintenant fermé (`TranslationProviderError`), plus jamais silencieusement acceptée comme une traduction |
| **Root cause du provider (externe, prouvée)** | Une fois le correctif en place, une tentative réelle contre `translate.googleapis.com` (l'endpoint gtx par défaut de googletrans) renvoie **HTTP 429** (page officielle « unusual traffic » de Google, capturée en brut) pour l'IP sortante de ce sandbox ; `translate.google.com` et ses variantes régionales renvoient **HTTP 403**. Prouvé stable sur plusieurs tentatives espacées et plusieurs endpoints/modes `http2` -- une vraie indisponibilité réseau externe de cette bibliothèque non officielle, pas un défaut DID |
| Runtime | `did.runtime.py` exécute le Campaign Engine réel (scheduler + worker + réconciliation de livraison, `GoogletransCampaignTranslationProvider` réel câblé, maintenant fail-closed) dans les process production -- inchangé structurellement, le comportement en cas de panne provider est ce qui a changé |
| API HTTP / UI (Campaign Center) | Inchangées cette passe -- surface Stage09 complète (WP14), toutes les surfaces d'authoring produit |
| Suite de tests | `pytest backend/tests/unit` + `integration` (régression complète, non filtrée par stage), `-k stage09` : 576+ tests collectés (15 nouveaux tests unitaires sur le fail-closed de l'adaptateur cette passe) ; voir « Validation canonique de la remédiation » ci-dessous pour les décomptes PASS exacts |
| Qualification live Discord (primitives + chaîne complète) | Point d'entrée canonique inchangé : `python scripts/validate_stage.py 09 --include-discord-live` exécute les deux scripts live dans la même exécution. **Résultat de cette passe : FAIL honnête**, pas un faux PASS -- 9 des 11 groupes de scénarios restent 100% PASS (rien lié à la traduction n'est affecté : IMMEDIATE/ONE_SHOT_DEFERRED/RECURRING/EVENT_TRIGGERED/LOGICAL_GROUP/édition-suppression/embed-bouton/équité Governor/rétention, plus SOURCE_ONLY et EXISTING_PROVIDER et le groupe frontière-provider qui n'ont jamais besoin d'une traduction réelle) ; seuls les échantillons de prose délibérément linguistique de DID_TRANSLATED_FANOUT/SELECTED_LANGUAGES/variante-approuvée-sœur échouent désormais **honnêtement**, avec la vraie erreur 429 du provider capturée dans les logs applicatifs (`campaign.schedule.evaluation_failed`, `reason: "unexpected error: translation provider error (attempt 3/3): Unexpected status code \"429\"..."`) -- jamais un contenu source ré-échoïsé accepté comme traduit |
| Preuve live committée | `docs/90_handoffs/evidence/stage09/discord-live-stage09.json` (primitives, inchangé, 5/5) et `docs/90_handoffs/evidence/stage09/discord-live-stage09-full-chain.json` (chaîne complète, **régénéré cette passe**, `"status": "FAIL"` honnête, voir détail ci-dessus, et incluant désormais un champ `"cleanup"` -- voir ligne dédiée ci-dessous) |
| **Nettoyage du sandbox live (merge-blocker séparé, corrigé cette même passe)** | Une revue externe indépendante a trouvé un vrai défaut de fuite de ressources dans `scripts/_stage09_full_chain_impl.py` : les salons Discord créés étaient enregistrés dans `ctx.temp_channels` immédiatement, mais la liste réellement utilisée par le `finally` de nettoyage n'était copiée depuis `ctx.temp_channels` qu'**après** que tous les groupes de scénarios aient terminé avec succès -- toute exception/timeout/annulation en cours de route laissait cette copie vide, donc le `finally` ne supprimait rien, même si de vrais salons avaient déjà été créés. C'est la cause racine exacte des dizaines de salons orphelins `did-s09-fc-...` accumulés dans le sandbox après les runs live interrompus (notamment ceux de cette passe même, avant correctif, pendant le diagnostic du blocage googletrans). **Corrigé** : un nouveau `CleanupRegistry` (`scripts/_stage09_cleanup_registry.py`) enregistre chaque ressource **immédiatement** à sa création et est référencé par identité (jamais copié) dans le `finally` -- correct sous toute sortie (succès, échec d'assertion, panne provider, timeout, annulation, exception avalée par le handler discord.py). Le nettoyage est best-effort (une suppression en échec n'empêche jamais les suivantes) et son résumé (`created`/`deletion_attempted`/`deleted_or_already_absent`/`failed`/`remaining`) est désormais dans le rapport JSON committé ; le validateur canonique rapporte FAIL (jamais un faux PASS) si `remaining > 0`. Preuve réelle : un run live complet avec le blocage googletrans actif (donc des groupes de traduction qui échouent réellement) a quand même nettoyé **42/42 salons créés, 0 restant**. |
| **Sweep des orphelins historiques (exécuté cette passe)** | `scripts/cleanup_stage09_orphan_fixtures.py` -- conservateur par construction : ne touche que les deux Guilds sandbox désignées (`DISCORD_TEST_GUILD_A_ID`/`B_ID`), exige une correspondance exacte du nom de fixture réservé Stage09 (jamais un préfixe/sous-chaîne large) **ET**, par défaut, une confirmation par le journal d'audit Discord que ce bot a bien créé le salon -- un simple nom correspondant ne suffit jamais si le journal d'audit est lisible. Dry-run par défaut, `--execute` explicite pour supprimer réellement. Exécuté réellement sur le sandbox : **121 salons scannés, 50 correspondant à la convention de nommage, 50/50 confirmés par le journal d'audit, 50/50 supprimés avec succès (0 échec)**. Vérifié après coup par un second scan : **0 salon Stage09 restant** (71 salons totaux restants, tous hors convention de nommage Stage09, jamais touchés). Preuve committée : `docs/90_handoffs/evidence/stage09/orphan-fixture-cleanup.json`. |
| Benchmark de traduction | `docs/90_handoffs/evidence/stage09/translation-benchmark.json` -- **rejoué cette passe** (le provider de production a changé -- fail-closed -- donc l'évidence précédente, mesurée contre l'ancien comportement fail-open, n'était plus valide). Nouveau statut : **`BLOCKED`**, 1248/1248 mesures en échec réel sur les 4 stratégies (312 chacune), 0 traduction obtenue -- jamais transformé en `PASS`. Le rapport distingue désormais explicitement succès provider/réseau, intégrité de tokens protégés, et sanité de traduction (`identical_to_source_count`, jamais un gate à lui seul) |
| Smoke réseau réel étendu | `backend/tests/network/test_stage09_translation_network.py` étendu à une matrice EN→FR/FR→EN/DE→ES/ES→DE de prose délibérément linguistique (plus le smoke de préservation de placeholder existant) ; rejoué réellement cette passe : **5/5 en échec réel** (429/circuit ouvert), jamais un faux succès. Ce smoke est désormais câblé comme étape bloquante avant le benchmark complet dans `validate_stage.py 09 --profile translation-benchmark --allow-network` |
| Limitations honnêtement externes restantes | (A) revue sémantique humaine : `PENDING_HUMAN_REVIEW` -- pack régénéré cette passe avec le statut machine réel `MACHINE_TRANSLATION_CURRENTLY_UNAVAILABLE` (jamais de sortie fabriquée), voir pack § dédiée ; (B) **provider de traduction propre à DID (`googletrans`) actuellement indisponible** : `GOOGLETRANS_PROVIDER_CURRENTLY_UNAVAILABLE`, HTTP 429/403 réels prouvés, hors du contrôle de cette passe technique -- c'est la clause bloquante principale de cette passe ; (C) participation live d'un provider de traduction tiers réel attaché à un Translation Group (distinct de (B)) : `EXTERNAL_SANDBOX_CAPABILITY_NOT_AVAILABLE`, inchangé ; (D) reproduction sûre d'un `UNKNOWN_OUTCOME` réel contre Discord : `NOT_SAFELY_REPRODUCIBLE_LIVE`, inchangé |

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

## Sixième passe — API HTTP Stage09 complète (WP14) et preuve de la chaîne runtime complète

La cinquième passe avait connecté le Campaign Engine au runtime réel, mais aucune surface HTTP
n'existait encore pour le piloter, et aucun test n'exerçait la chaîne complète du runtime à travers
ses vrais points d'entrée composés (chaque étage n'était prouvé qu'isolément). Cette passe ferme les
deux.

1. **API HTTP Stage09 complète (WP14)** : `did.api.stage09` — routeur mince au-dessus de la couche
   métier `did.campaigns.*` déjà testée, suivant exactement la convention `did.api.stage08` : chaque
   POST/PATCH mutant exige `CsrfSessionDep` + `Idempotency-Key`, chaque corps de requête est
   `extra="forbid"` sans aucun champ d'identité owner/approbateur qu'un client pourrait fournir, et une
   campagne/trigger étrangère ou inexistante renvoie systématiquement la même forme générique 404 via
   deux nouveaux handlers d'exception globaux (`CampaignNotOwnedByCaller`/`ForeignOrUnknownResourceError`)
   — jamais un split 403/404 qui divulguerait l'existence. Couvre : campagnes CRUD (création idempotente
   avec rejeu par `Idempotency-Key`, PATCH DRAFT-only en CAS de version), targets
   (CHANNEL/LOGICAL_GROUP/TRANSLATION_GROUP via `create_authorized_campaign_target`), schedule
   (validation RRULE anticipée avant persistance), simulation (expose `delivery_executable` comme son
   propre champ, jamais fondu dans `ready`), activate/pause/resume/cancel, historique de livraisons,
   preview/approve de variantes (`approving_discord_user_id` toujours la session authentifiée —
   `VariantApprovalInput` n'a même pas ce champ, une tentative de le fournir échoue à la validation
   Pydantic avant que le handler ne s'exécute), triggers/trigger-sources.
2. **Activation volontairement étroite (contrainte critique de la mission)** : l'activation ne fait que
   transitionner l'état de cycle de vie et, pour une campagne IMMEDIATE, appeler `fan_out_occurrence`
   (ne crée jamais que des lignes `message_deliveries`) et `route_pending_deliveries_to_jobs` (n'enfile
   jamais que des lignes durables `discord_io_jobs`) — jamais un appel Discord direct depuis l'API.
   Prouvé par deux moyens indépendants : `test_stage09_api_router_never_sends.py` (le texte source du
   module ne mentionne jamais l'adaptateur d'envoi, aucune instruction d'import ne le nomme, et
   l'importer ne le charge jamais dans `sys.modules`) et une activation IMMEDIATE réelle dans
   `test_stage09_api_postgres.py` assertée directement contre les lignes DB (`message_occurrences`
   FANNED_OUT, `message_deliveries` PENDING sans `discord_message_id`, `discord_io_jobs`
   `SEND_CAMPAIGN_MESSAGE`) — jamais seulement la réponse HTTP.
3. **REQ-MSG-016 promu à `IMPLEMENTED`** : l'exigence ne nomme aucune UI dans son texte ; l'API réelle
   fournit désormais preview/édition/approbation avec identité toujours authentifiée, bout-en-bout.
4. **Gaps de repository comblés en construisant l'API** : `CampaignsRepository` n'avait aucun moyen de
   persister une transition de cycle de vie ou une édition DRAFT — `update_campaign_lifecycle_status`
   (CAS sur `version`), `update_campaign_draft_fields` (CAS + fencé par `lifecycle_status='DRAFT'` dans
   la clause WHERE elle-même, jamais seulement vérifié avant l'écriture), `get_campaign_by_key`
   (rejeu idempotent), `list_deliveries_for_campaign` (lecture système admin-scoped, appartenance
   vérifiée dans la jointure de la requête, jamais fait confiance à l'appelant) ont été ajoutés.
   **Bug réel révélé en construisant l'endpoint d'activation** : rien dans le code ne mettait en
   œuvre "IMMEDIATE se déclenche directement à l'activation" — seul un message de refus dans
   `scheduling.evaluate_schedule` disait que cela devrait être le cas. Implémenté dans le endpoint
   `activate` avec les mêmes primitives que le scheduler d'arrière-plan.
5. **Preuve de la chaîne complète du runtime réel (sections 22/23 de la mission)** : chaque test de
   sécurité de bail précédent (fan-out, dispatch durable, worker de livraison) ne prouvait qu'un étage
   isolément. `test_stage09_runtime_chain_postgres.py` (nouveau, 3 tests PostgreSQL réels) prouve
   désormais `did.campaigns.runtime.CampaignSchedulerRuntime.tick()` — le vrai point d'entrée composé,
   pas un callback factice — suivi de `did.worker.io.DurableDiscordIOWorker.run_guild_once()` comme une
   seule chaîne continue (schedule dû → occurrence → fan-out → livraison → job durable → worker → envoi
   → finalisation) : (a) la séquence complète produit exactement un envoi pour une occurrence due, et un
   second tick ne redéclenche jamais le schedule déjà consommé ; (b) deux instances
   `CampaignSchedulerRuntime` indépendantes (simulant deux répliques de scheduler) qui tick concurremment
   sur le même schedule dû ne produisent jamais qu'une seule occurrence/livraison/job — la composition
   de fencing tient au niveau du vrai point d'entrée, pas seulement de la primitive `claim_due_schedules`
   isolée ; (c) un redémarrage complet de process en plein milieu de la chaîne — l'instance qui a mis le
   travail en file est abandonnée, une instance runtime + worker entièrement neuve (aucun état en
   mémoire partagé) termine le travail — prouvant que la durabilité ne dépend que de la base de données,
   jamais d'une instance de process survivante.
6. **Scope honnêtement différé (pas des omissions dissimulées)** : `/simulate` et l'activation IMMEDIATE
   passent `translation_provider=None` plutôt que de démarrer un vrai provider de traduction de façon
   synchrone dans une requête HTTP (appels réseau, latence, flakiness de test) — une destination
   nécessitant réellement une traduction sans variante approuvée rapportera
   `MISSING_NO_PROVIDER_CONFIGURED`/un échec de rendu même si un vrai provider existe ailleurs dans le
   système (le scheduler d'arrière-plan, lui, en câble un réel) ; seule la création de campagne dispose
   d'un registre de rejeu idempotent complet par `Idempotency-Key` — les autres endpoints mutants exigent
   l'en-tête sans registre de déduplication dédié (sûr au retry via les transitions CAS propres au
   domaine, mais pas une implémentation d'idempotence complète).

## Septième passe (clôture) — REQ-MSG-030 requalifié et complété, REQ-MSG-007 fermé côté frontend

Mission de clôture explicite requalifiant la revendication de blocage externe de la sixième passe
pour REQ-MSG-030, et fermant les deux dernières lignes `PARTIALLY_IMPLEMENTED` de la matrice
REQ-MSG-001..031.

1. **Requalification REQ-MSG-030 (CRITIQUE — auto-critique honnête)** : la sixième passe affirmait
   que le taggage d'ancestry côté production était bloqué par ADR-008 exigeant l'intent privilégié
   `MESSAGE_CONTENT`. C'était **une erreur d'analyse** du contrat Gateway réel de Discord : l'intent
   `GUILD_MESSAGES` (non privilégié) suffit à recevoir les dispatches `MESSAGE_CREATE`/`MESSAGE_UPDATE`/
   `MESSAGE_DELETE` ; `MESSAGE_CONTENT` (le seul réellement privilégié) ne fait que peupler les champs
   `content`/`embeds`/`attachments` de ces mêmes dispatches. ADR-008 (« ne jamais demander un intent
   privilégié avant qu'une fonctionnalité documentée en dépende ») ne gate donc que `MESSAGE_CONTENT`,
   jamais `GUILD_MESSAGES`. Cette revendication erronée est retirée de la documentation ; le blocage
   n'a jamais été réel.
2. **Contrat d'intents ajouté** : `Settings.discord_campaign_message_events_enabled` (bool, `False`
   par défaut — active `GUILD_MESSAGES`) et `discord_campaign_message_content_enabled` (bool, `False`
   par défaut — active le privilégié `MESSAGE_CONTENT`, **rejeté à la configuration** si le premier
   n'est pas également actif, `model_validator` dédié). `did.bot.gateway.client
   .minimal_gateway_intents()` accepte les deux nouveaux paramètres, câblés depuis `did.runtime.py`
   jusqu'à la construction de `DiscordGatewayClient`. 11 tests unitaires (`test_stage03_gateway_contract
   .py::TestCampaignMessageIntentContract`) + 4 (`test_settings.py
   ::TestCampaignMessageIntentSettings`) prouvent : comportement par défaut minimal explicite,
   `GUILD_MESSAGES` activable indépendamment, `MESSAGE_CONTENT` reste désactivé par défaut même avec
   `GUILD_MESSAGES` actif, l'intent membre reste contrôlé indépendamment.
3. **Capture structurelle seule, jamais le contenu** : `did.application.discord_runtime.gateway
   .SUPPORTED_DISPATCHES` gagne `MESSAGE_CREATE`/`MESSAGE_UPDATE`/`MESSAGE_DELETE`, normalisés par
   `_normalized_payload` en identité structurelle SEULE (`message_id`/`channel_id`/
   `author_discord_user_id`/`author_is_bot`) — `content`/`embeds`/`attachments`/`components` ne sont
   **jamais** extraits, y compris si le payload brut les contient (ex. le message est celui du bot
   lui-même, dont Discord inclut le contenu même sans `MESSAGE_CONTENT`). 4 tests dédiés
   (`TestMessageDispatchNormalization`) le prouvent explicitement, y compris un payload adverse
   contenant délibérément `content`/`embeds`/`attachments`/`components` pour vérifier qu'ils ne
   survivent jamais à la normalisation.
4. **Côté production de l'ancestry (le cœur de la fermeture)** : `did.domain.campaigns
   .MessageOccurrence` gagne `source_causation_depth: int = 0` et `source_ancestry: frozenset[str] =
   frozenset()`, persistés par migration `0029_stage_09` (colonnes `message_occurrences
   .source_causation_depth`/`source_ancestry` JSONB). Peuplés à la création de l'occurrence aux 3
   points d'entrée réels : `scheduler_loop.py` (SCHEDULE — son propre racine causale, profondeur 0,
   ancestry = `{son propre campaign_id}`), `event_consumer.py` (EVENT — hérite `event.causation_depth`
   et l'union de l'ancestry de l'événement causant avec son propre `campaign_id`, réutilisant
   `did.campaigns.causality.read_campaign_ancestry`, JAMAIS appelé auparavant en dehors de sa propre
   définition), `did.api.stage09.activate_campaign` (IMMEDIATE — même traitement que SCHEDULE).
   `CampaignsRepository.find_delivery_by_discord_message` (nouvelle lecture cross-authority admin
   factory) résout un `(guild_id, discord_channel_id, discord_message_id)` exact vers la livraison
   SENT et l'occurrence causale qui l'a produite. `did.campaigns.event_transport
   .consume_new_events_for_guild` corrèle chaque `MESSAGE_CREATE` auto-généré à cette résolution et
   construit l'événement dérivé avec `origin=DID_CAMPAIGN`, `payload[did_campaign_ancestry]` =
   l'ancestry réelle de l'occurrence, `causation_depth` = profondeur de l'occurrence + 1,
   `correlation_id`/`causation_id` hérités — AVANT toute évaluation de trigger, réutilisant
   entièrement le chemin de décision existant (`should_trigger`) sans dupliquer sa logique.
5. **Course Gateway/finalize gérée sans supposer d'ordre** : si la livraison est déjà `SENT` au moment
   où le `MESSAGE_CREATE` est consommé (ordre normal), la corrélation réussit immédiatement et le
   curseur avance dans le même tick. Si le `MESSAGE_CREATE` arrive avant que `finalize_delivery` n'ait
   persisté `discord_message_id` (la course), le curseur par Guild existant **n'avance simplement pas
   au-delà de cet événement** jusqu'à résolution — aucune nouvelle table durable, aucun état en
   mémoire : les timestamps déjà persistés de `discord_gateway_inbox` et le curseur
   `message_campaign_event_cursor` existant suffisent. Borné par `BOT_MESSAGE_CORRELATION_GRACE_SECONDS`
   (120s) : un message du bot qui ne se corrèlera jamais (envoyé par une autre fonctionnalité, par
   exemple) finit par être traité comme un événement ordinaire non attribué plutôt que de bloquer
   indéfiniment le traitement des événements de cette Guild.
6. **7 tests d'intégration PostgreSQL réels** (`test_stage09_ancestry_postgres.py`) prouvent chaque
   scénario nommé par la mission : auto-boucle directe bloquée (campagne A ne se re-déclenche jamais
   sur son propre message), A→B se déclenche mais B→A est bloqué (avec `source_causation_depth`/
   `source_ancestry`/`source_correlation_id`/`source_event_id` explicitement asserés à chaque saut),
   cycle cross-Guild A→B→C→A à travers 3 Guilds réelles bloqué au dernier saut, les deux ordres de
   course (finalize-avant-Gateway résout dans le même pass ; Gateway-avant-finalize diffère jusqu'à
   résolution, y compris une instance `RuntimeRepository` **fraîchement construite** au milieu de la
   course pour prouver qu'aucun état en mémoire n'est requis — simulant un redémarrage de process), et
   les deux cas d'expiration (un message non corrélable finit par avancer non attribué ; un message
   récent n'est pas expiré prématurément).
7. **REQ-MSG-007 fermé côté frontend** : `frontend/src/features/campaigns/CampaignCenter.tsx`
   remplace la note « pas encore disponible » par le sélecteur `target_kind` réel
   (CHANNEL/LOGICAL_GROUP/TRANSLATION_GROUP) et, pour TRANSLATION_GROUP, le sélecteur de mode de
   publication explicite (les 4 modes) plus, pour `SELECTED_LANGUAGES`, une sélection réelle de
   profils de langue Stage08 (case à cocher par langue) — aucun mode déduit, aucune liste codée en
   dur ; chaque requête (`/logical-groups`, `/translation-workspace`) n'est activée qu'une fois
   Guild + type de cible choisis. Nouveau test `@a11y` dans `frontend/e2e/stage09.spec.ts` exerçant
   les 4 modes de bout en bout à travers la vraie UI, avec scan axe.
8. **Écart honnêtement découvert et documenté, non fermé cette passe** : en auditant la réconciliation
   de livraison pour REQ-MSG-030/section 8 de la mission, `did.campaigns.delivery_worker
   .reconcile_one_stalled_delivery` (récupération sûre `SENDING`/`UNKNOWN` via
   `decide_unknown_outcome_recovery`) s'est avéré être une fonction complète et testée mais **jamais
   appelée par aucun process réel** — exactement le même type d'écart que `with_campaign_ancestry`
   avant cette passe. Documenté explicitement dans les écarts connus plutôt que dissimulé ou fermé à
   la hâte sans preuve réelle. **Fermé la passe suivante — voir item 4 de la section « Huitième
   passe » ci-dessous.**

### Huitième passe — deux bugs réels corrigés dans la production-side REQ-MSG-030, contrat MESSAGE_CONTENT rendu cohérent, réconciliation câblée dans le runtime réel

Un audit externe de la septième passe a trouvé deux bugs réels dans le mécanisme d'ancestry
producing-side ci-dessus (items 4-5) — **corrections apportées, items 2 et 5 ci-dessus sont
partiellement obsolètes, voir ci-dessous** :

1. **`_is_bot_authored_message_create` traitait N'IMPORTE QUEL bot comme candidat à la corrélation**,
   pas seulement le bot DID lui-même. Un `MESSAGE_CREATE` d'un bot tiers pouvait donc entrer dans le
   chemin d'attente de corrélation et retarder l'avancement du curseur d'une Guild sans raison.
   Corrigé : `_is_own_did_bot_message_create(envelope, *, our_bot_user_id)` exige que
   `author_discord_user_id` corresponde exactement à l'identité durable et faisant autorité du bot
   pour cette Guild, lue via `did.infrastructure.stage04_repository.Stage04Repository.bot_identity()`
   (jamais un snowflake codé en dur) une fois par appel de `consume_new_events_for_guild`. Un bot
   tiers ou un message humain n'entre plus jamais dans le chemin d'attente.
2. **Item 5 ci-dessus décrit un comportement fail-OPEN maintenant corrigé** : à l'expiration du délai
   de grâce (`BOT_MESSAGE_CORRELATION_GRACE_SECONDS`), un message du bot DID confirmé mais jamais
   corrélé n'est **plus jamais traité comme un événement ordinaire** — cela aurait pu rouvrir
   exactement la boucle self/cross-campaign que la garde anti-boucle ancêtre existe pour empêcher.
   Il est maintenant explicitement ignoré (le curseur avance quand même, pour que la Guild ne bloque
   jamais indéfiniment) via un nouveau diagnostic assaini (aucun id/contenu de message, seulement
   `guild_id`) : `EventId.CAMPAIGN_BOT_MESSAGE_UNCORRELATED_SKIPPED`. 3 nouveaux tests PostgreSQL
   (`TestOwnBotVsThirdPartyBotIdentity`) prouvent : bot tiers jamais différé/curseur avance
   normalement, message humain jamais différé, bot DID propre entre bien dans le chemin d'attente ;
   le test d'expiration existant est renommé/réécrit pour affirmer `fired == 0` et zéro occurrence
   créée (au lieu de l'ancienne assertion fail-open `fired == 1`).
3. **Contrat MESSAGE_CONTENT rendu cohérent (REQ-MSG-020, décision Option B)** : item 2 ci-dessus
   décrit `discord_campaign_message_content_enabled`, qui **n'existe plus** — c'était une capacité
   incohérente à moitié construite (activer le réglage aurait demandé le privilège Discord
   MESSAGE_CONTENT réel en Developer Portal, pour un bénéfice fonctionnel nul, puisqu'aucun chemin de
   code du Campaign Engine n'extrait jamais `content`/`embeds`/`attachments`, quel que soit l'intent
   actif). Décision explicite et définitive (pas provisoire) : **Stage09 ne supporte pas
   l'évaluation de trigger dépendante du contenu brut**. Le réglage est supprimé (`Settings`,
   `minimal_gateway_intents`, `DiscordGatewayClient`, `did.runtime.py`) ;
   `CampaignTrigger.requires_message_content` reste une dépendance déclarée honnête, maintenant
   réellement câblée aux deux moments prévus par REQ-MSG-020 mais jamais branchés jusqu'ici :
   `did.api.stage09.create_trigger` appelle `validate_message_content_capability` et rejette (422
   `CAMPAIGN_TRIGGER_MESSAGE_CONTENT_UNAVAILABLE`) toute tentative avant persistance ;
   `did.api.stage09.simulate` appelle `simulate_message_content_dependency` pour chaque trigger de la
   campagne et expose `message_content_warnings` dans la réponse. Nouvelle classe concrète
   `PermanentlyUnavailableMessageContentChecker` (toujours indisponible, `guild_id` accepté par le
   Protocol mais jamais consulté — conçu pour qu'une future passe Option A n'ait qu'à fournir une
   nouvelle implémentation). Preuve : nouveau test d'intégration API réel
   (`test_trigger_creation_message_content_dependency_is_blocked`, HTTP réel, 422 + zéro ligne
   persistée + un trigger sans la dépendance passe normalement) + assertion étendue sur la réponse de
   simulation existante.
4. **Écart de la septième passe fermé : réconciliation de livraison câblée dans le runtime réel
   (REQ-MSG-029)** : `did.campaigns.delivery_worker.reconcile_one_stalled_delivery` était complet et
   testé mais jamais appelé par aucun process réel (item 8 ci-dessus). Migration `0030_stage_09` ajoute
   `app.runtime_campaign_reconciliation_guilds` (fonction SECURITY DEFINER, même schéma que
   `runtime_campaign_delivery_guilds` de `0026_stage_09` : découvre les Guilds avec une livraison
   `SENDING` bloquée au-delà de `STALLED_SENDING_THRESHOLD_SECONDS` ou `UNKNOWN`). Nouvelle classe
   `did.campaigns.reconciliation_runtime.CampaignDeliveryReconciliationRuntime` (boucle bornée, même
   convention que `CampaignSchedulerRuntime` : une tick ratée n'arrête jamais le process, la suivante
   reprend le travail durable restant), câblée dans `did.runtime.py`'s process `worker` aux côtés du
   `DurableDiscordIOWorker` existant (`asyncio.gather` des deux boucles sous une seule tâche de fond),
   intervalle `discord_worker_recovery_seconds` réutilisé comme suggéré par la mission. 5 nouveaux
   tests PostgreSQL réels (`test_stage09_reconciliation_runtime_postgres.py`) prouvent : découverte
   (un Guild avec seulement une livraison PENDING n'est jamais découvert ; un Guild avec une livraison
   UNKNOWN l'est), `tick()` résout réellement la livraison et le Guild sort de la découverte ensuite,
   plusieurs Guilds réconciliés dans un seul tick, et la vraie boucle `run()` (pas seulement `tick()`)
   s'arrête proprement sur `stop_event` après avoir réconcilié.

### Neuvième passe — surfaces d'authoring produit complètes, section 19 de couverture Playwright vérifiée, et la matrice complète de chaîne live Discord (section 20)

Cette passe ferme l'intégralité des écarts de « Surfaces d'authoring Stage09 restantes en UI/API »
et de « WP16 (Live) — pas la matrice complète » listés dans les Écarts connus des passes
précédentes, plus la vérification explicite de couverture Playwright complète (section 19 de la
mission de clôture).

1. **Éditeur MessageModel complet (mission section 9)** : `MessageModelEditor.tsx` -- embeds
   (titre/description/url/couleur/footer/author/fields), boutons/composants supportés
   (label/style/custom_id/url avec protection technique -- LINK exige url, non-LINK exige
   custom_id, jamais les deux), limites Discord réelles appliquées côté UI. Bug de production réel
   trouvé et corrigé en écrivant le test Playwright : les boutons « Add embed »/« Add field »/etc.
   n'avaient pas `type="button"` et soumettaient prématurément le formulaire de création de
   campagne (défaut `type="submit"` du composant `Button` partagé). Écart backend distinct
   également trouvé et corrigé : `validate_message_model` n'était en réalité jamais appelé au
   create/update de campagne malgré sa propre docstring l'affirmant -- corrigé aux trois points
   d'entrée réels.
2. **Variables de gabarit typées en UI (mission section 10)** : `TemplateVariableEditor.tsx` --
   CRUD complet des 4 types (TRANSLATABLE_TEXT/NON_TRANSLATABLE/LOCALIZED_VALUE/PROTECTED),
   persistance durable déjà existante côté backend, intégration simulation/preview
   (`undeclared_template_variable_names` dans `CampaignSimulationReport`), parité EN/FR/DE/ES.
3. **Glossaire en UI (mission section 11)** : nouveaux endpoints `did.api.stage09` (create/list par
   les trois portées CAMPAIGN/GUILD/GLOBAL_USER, delete) avec autorisation indépendante par portée
   (GUILD ré-authentifie réellement contre `is_guild_authorized`, jamais seulement « appelant
   connecté ») ; `GlossaryEditor.tsx` ; nouvelle fonction pure `matched_source_terms` exposant dans
   `CampaignSimulationReport.matched_glossary_terms` quels termes de glossaire apparaissent
   réellement dans le contenu source, pour l'aperçu d'auteur.
4. **Déclencheur d'événement/source en UI (mission section 12)** : deux nouveaux endpoints de
   lecture `GET .../triggers` (owner-scoped) et `GET .../triggers/{id}/sources?guild_id=`
   (Guild-scoped, une source binding vit par Guild, pas par owner) ; `TriggerEditor.tsx` --
   constructeur de condition structuré et allowlisted uniquement (ALWAYS / une comparaison /
   ALL_OF·ANY_OF d'une liste de comparaisons, sérialisé exactement dans la forme AST que
   `did.campaigns.causality.validate_condition_ast` accepte -- aucun champ d'expression brute nulle
   part), avertissement + blocage réel 422 `CAMPAIGN_TRIGGER_MESSAGE_CONTENT_UNAVAILABLE` exposé de
   bout en bout côté UI si `requires_message_content` est coché.
5. **Surface produit de rétention, honnête plutôt qu'inventée (mission section 13)** : nouvel
   endpoint `GET .../retention-policy` -- rétention reste délibérément un paramètre
   système unique (`did.campaigns.retention.RetentionPolicy`), aucune configurabilité par
   campagne/Guild n'a été inventée puisque le modèle de données n'en a jamais eu ; l'UI affiche la
   politique réelle (jours de rétention, ce qui est purgé) à côté de l'historique de livraisons
   qu'elle décrit.
6. **Section 19 -- couverture Playwright de l'intégralité du Campaign Center vérifiée** : chaque
   nouvelle surface ci-dessus a reçu son propre test Playwright dédié au moment de sa construction ;
   cette passe a vérifié explicitement que les surfaces déjà construites précédemment (CHANNEL/
   LOGICAL_GROUP/TRANSLATION_GROUP et les 4 modes de publication, intervention/requeue sûrs,
   édition/suppression possédée, contrôles de cycle de vie, variantes approuvées) restent
   couvertes -- 53 tests Playwright passent sur l'ensemble des stages 07/08/09, 40 scénarios
   distincts sur Stage09 seul, zéro régression.
7. **Section 20 -- la matrice complète de chaîne live Discord** :
   `scripts/validate_discord_live_stage09_full_chain.py` (+ module d'implémentation), un nouveau
   validateur live distinct de `validate_discord_live_stage09.py` et jamais un substitut -- celui-ci
   traverse la chaîne production complète contre le vrai sandbox Discord : application/API →
   occurrence → fan-out → livraison durable → `discord_io_job` durable → un vrai
   `DurableDiscordIOWorker` → un vrai `DiscordWorkloadGovernor` → le vrai adaptateur
   `DiscordPyMessageSender` → Discord réel → résultat/réconciliation durable, chaque étape via les
   vrais points d'entrée production (la vraie app `create_app()` par `httpx.ASGITransport`,
   `CampaignSchedulerRuntime.tick()`, `DurableDiscordIOWorker.dispatch_guild_once` couplé à un vrai
   `DiscordWorkloadGovernor.drain()`). Neuf groupes de scénarios, exécutés en une seule passe
   continue de ~15-20s contre le sandbox réel (**40 vérifications individuelles, toutes PASS** --
   preuve committée `artifacts/test-evidence/stage-09/discord-live-full-chain.json`, gitignored,
   régénérée à chaque exécution) : IMMEDIATE+CHANNEL (le tronc commun), ONE_SHOT_DEFERRED et
   RECURRING via le vrai tick du scheduler, EVENT_TRIGGERED via une vraie ligne
   `discord_gateway_inbox` consommée par le vrai chemin de transport d'événement, LOGICAL_GROUP
   fan-out vers deux vrais salons, édition/suppression possédée à travers le chemin de job durable
   complet (pas seulement la primitive d'adaptateur déjà prouvée par le script à 5 scénarios),
   richesse embed/bouton vérifiée sur le message réellement envoyé, équité du Workload Governor
   par-Guild dispatchant deux vrais Guilds à travers un seul governor partagé, et purge de
   rétention prouvée pour ne retirer que la ligne d'historique durable en laissant le message
   Discord réel intact. Portée honnête documentée dans le docstring du script : les modes de
   publication TRANSLATION_GROUP au-delà de SOURCE_ONLY nécessitent un provider de traduction live
   que cette architecture n'a pas câblé (déjà couvert par les tests d'intégration à provider
   factice) ; forcer une livraison UNKNOWN_OUTCOME/INTERVENTION_REQUIRED réelle contre Discord
   n'est pas reproductible à la demande (déjà couvert par le double contrôlable de
   `test_stage09_delivery_worker_postgres.py`).
   Deux bugs réels trouvés et corrigés en construisant ce script contre le vrai sandbox, ni l'un ni
   l'autre auparavant détecté car rien avant ce script n'exerçait la composition
   `dispatch_guild_once`+`governor.drain()` de bout en bout hors de la couverture unitaire déjà
   passante de `did.worker.io.runtime` elle-même : (a) `dispatch_guild_once()` ne fait qu'empiler
   le job loué dans la file interne du Governor et renvoie un Future qui ne se résout que lorsque
   `governor.drain()` le traite réellement -- l'appeler sans piloter `drain()` en concurrence bloque
   indéfiniment, silencieusement avalé par la propre gestion d'exception des handlers d'événement de
   discord.py en un faux PASS vacuous depuis un dict de résultats vide ; corrigé en reproduisant le
   vrai motif dispatch-puis-drain de `did.worker.io.runtime.DiscordWorkerRuntime
   ._dispatch_fair_batch`, et en capturant/relançant explicitement toute exception survenant dans le
   handler `on_ready` de discord.py pour qu'un échec futur rapporte honnêtement BLOCKED au lieu d'un
   PASS silencieux ; (b) ne jamais appeler `governor.drain()` en concurrence depuis deux appelants
   `dispatch_guild_once` indépendants contre la même instance de governor partagée (`drain()` n'est
   pas réentrant contre son propre état de file interne partagé) -- corrigé via un helper dédié
   dispatch-plusieurs-puis-drain-une-fois pour le groupe d'équité du Governor.
8. **Balayage de validation finale de cette passe** : suite pytest backend complète (746 unit
   passants + 10 échecs pré-existants documentés, encodage de chemin Windows sans lien avec le code,
   confirmés inchangés par comparaison `git stash` ; 252 integration passants, PostgreSQL réel),
   `ruff format`/`ruff check` propres sur tout le dépôt backend touché, `mypy src/did` strict propre
   (158 fichiers), suite frontend complète (36 vitest + 53 Playwright, incl. axe, zéro régression
   sur les stages 07/08/09), `npm run build` propre, `npm run openapi:check` à jour, répétition
   complète de la rehearsal de migration (`alembic downgrade base` → `upgrade head` →
   `downgrade 0001_stage_01` → `upgrade head`, les 32 migrations, tête unique confirmée) suivie
   d'une nouvelle passe complète de la suite d'intégration contre le schéma fraîchement rejoué (252
   passants, identique).

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

## Suite de tests réelle (état courant, passe de remédiation fail-closed)

| Gate | Résultat |
|---|---|
| `uv run pytest backend/tests/unit/test_stage09_translation_adapter.py` | **15 passed** (9 préexistants + 6 nouveaux : construction fail-closed du provider de production, rejet 429/403 même sans exception levée par googletrans lui-même, passage 200 inchangé, absence de `_response` non pénalisée) |
| `python scripts/validate_stage.py 09` (défaut, sans réseau réel) | **PASS**, inchangé -- l'adaptateur corrigé n'affecte aucun test offline (les doubles factices n'exposent jamais `_response`, donc la vérification défensive ne se déclenche jamais pour eux) |
| `python scripts/validate_stage.py 08` | **PASS**, inchangé -- aucune régression |
| `python scripts/validate_stage.py 09 --profile failure-injection` | **PASS**, inchangé |
| `DID_ALLOW_NETWORK=1 uv run pytest backend/tests/network/test_stage09_translation_network.py` | **5 failed** (réel, honnête) -- 4 nouvelles directions de prose linguistique (EN→FR/FR→EN/DE→ES/ES→DE) + le smoke de préservation de placeholder existant, tous en échec réel avec `TranslationProviderError` (HTTP 429 réel ou disjoncteur ouvert), plus aucun ne peut silencieusement passer sur un écho |
| `python scripts/validate_stage.py 09 --profile translation-benchmark --allow-network` | **BLOCKED** (honnête, jamais transformé en PASS) -- la nouvelle étape de smoke réseau gate désormais le benchmark complet et échoue avant lui ; exécuté séparément en direct (voir ci-dessous), le benchmark complet confirme **1248/1248 mesures en échec réel** sur les 4 stratégies |
| `python scripts/validate_stage.py 09 --include-discord-live` | **FAIL** (honnête) -- voir « Qualification live Discord réelle » ci-dessous pour le détail exact des groupes qui échouent et de ceux qui restent 100% verts |

Le corpus de benchmark de traduction (26 classes/104 items) **a été rejoué** cette passe (contrairement
à la passe précédente) : le provider de production a changé de comportement (fail-closed), rendant
l'évidence précédente -- mesurée contre l'ancien comportement fail-open -- non représentative de
l'implémentation actuelle. Nouveau résultat committé : **`BLOCKED`**, 0 traduction réelle obtenue sur
les 1248 mesures (4 stratégies x 12 directions x 26 items), toutes en échec réel HTTP 429 ou disjoncteur
ouvert après 5 échecs consécutifs -- jamais compté comme une traduction réussie. Voir
`docs/90_handoffs/evidence/stage09/translation-benchmark.json` (`status: "BLOCKED"`,
`status_reason` détaillé, et le nouveau champ `identical_to_source_count` par stratégie, toujours à 0
ici puisque aucune mesure n'a atteint une sortie -- toutes ont `error` renseigné).

## Qualification live Discord réelle

`scripts/validate_discord_live_stage09.py` : **5/5 scénarios PASS**, inchangé (n'implique aucune
traduction) — preuve committée (`docs/90_handoffs/evidence/stage09/discord-live-stage09.json`).

**La matrice produit complète** (`scripts/validate_discord_live_stage09_full_chain.py`, 11 groupes)
donne un résultat honnêtement **mixte** cette passe -- exactement ce que le fail-closed doit produire
quand le provider externe est indisponible, jamais un faux PASS global :

- **9 groupes à 100% PASS, sans changement** : IMMEDIATE+CHANNEL, ONE_SHOT_DEFERRED, RECURRING,
  EVENT_TRIGGERED, LOGICAL_GROUP, édition/suppression possédée, embed/bouton, équité Workload
  Governor, rétention -- rien de tout cela ne dépend de la traduction.
- **`translation_group_did_fanout` -- PASS partiel, échec honnête sur ce qui dépend réellement du
  provider** : SOURCE_ONLY reste PASS (aucune traduction requise). Les quatre directions
  DID_TRANSLATED_FANOUT (EN/FR/DE/ES) échouent désormais correctement : le contenu source utilisé est
  déliberement de la prose linguistique (voir ci-dessous), et la vraie panne provider
  (`translation provider error (attempt 3/3): Unexpected status code "429"...`) empêche l'occurrence
  d'atteindre son fan-out complet -- capturé en toute transparence dans les logs applicatifs réels
  (`campaign.schedule.evaluation_failed`). SELECTED_LANGUAGES et la variante-approuvée-sœur DE échouent
  pour la même raison réelle.
- **`translation_group_provider_boundary` -- 100% PASS, inchangé** : ce groupe ne dépend jamais du
  provider `googletrans` propre à DID (il prouve l'inverse -- qu'un provider *externe* lié bloque
  correctement le fan-out), donc non affecté par cette indisponibilité.

**Changement de contenu et d'assertion (remédiation)** : les échantillons synthétiques utilisés par
`translation_group_did_fanout` sont désormais de la **prose délibérément linguistique**, native par
langue (jamais des chaînes technique-only du type « Full chain translation source EN (synthetic) »)
-- pour qu'une destination traduite identique au texte source soit objectivement un échec, pas une
zone grise. Et l'assertion elle-même est désormais un **vrai échec bloquant** (`routing_ok = False`)
quand une destination revient identique à la source, plus seulement une observation non bloquante --
corrigeant un vrai défaut de sévérité de test trouvé par l'audit externe : la version précédente ne
faisait qu'observer/logger un écho sans jamais faire échouer le scénario correspondant.

La reproduction à la demande d'un `UNKNOWN_OUTCOME`/`INTERVENTION_REQUIRED` réel contre Discord reste
non sûrement reproductible en live ; couverte par injection de panne déterministe, inchangé.

## Audit final Definition of Done — taxonomie à trois voies

**Ce tableau régresse délibérément** depuis la passe précédente : la clause de traduction live n'est
plus `TECHNICALLY_SATISFIED`, elle est `NOT_SATISFIED` (bloquée par une clause externe légitime, pas
par un défaut d'implémentation) tant que le provider `googletrans` réel reste indisponible.

| Clause | Statut | Preuve |
|---|---|---|
| Migrations | **TECHNICALLY_SATISFIED** | inchangé |
| Engine | **TECHNICALLY_SATISFIED** | inchangé -- le comportement fail-closed en cas de panne provider EST le comportement correct de l'Engine |
| UI | **TECHNICALLY_SATISFIED** | inchangé |
| Fuzz | **TECHNICALLY_SATISFIED** | inchangé |
| Failure | **TECHNICALLY_SATISFIED** | inchangé |
| Load | **TECHNICALLY_SATISFIED** | inchangé |
| Real corpus / benchmark de traduction | **NOT_SATISFIED (bloqué par une cause externe)** | `BLOCKED` -- 1248/1248 mesures en échec réel, 0 traduction obtenue ; le provider externe `googletrans` est indisponible dans ce sandbox (HTTP 429/403 réels, prouvés) -- pas un défaut d'implémentation DID, mais le gate d'acceptation lui-même n'est objectivement pas satisfait tant que cette indisponibilité dure |
| Live (primitives) | **TECHNICALLY_SATISFIED** | `validate_discord_live_stage09.py` 5/5, inchangé |
| Live (chaîne complète, hors traduction) | **TECHNICALLY_SATISFIED** | 9/11 groupes 100% PASS, aucun dépendant de la traduction |
| Live (chaîne complète, DID_TRANSLATED_FANOUT/SELECTED_LANGUAGES/variante-sœur) | **NOT_SATISFIED (bloqué par une cause externe)** | échec honnête, provider indisponible -- voir détail ci-dessus ; jamais transformé en PASS |
| Live (provider de traduction tiers réellement présent) | **EXTERNAL_ACCEPTANCE_ITEM** | inchangé, `EXTERNAL_SANDBOX_CAPABILITY_NOT_AVAILABLE` |
| Live (UNKNOWN_OUTCOME réel) | **EXTERNAL_ACCEPTANCE_ITEM** | inchangé, `NOT_SAFELY_REPRODUCIBLE_LIVE` |
| All REQ proofs | **TECHNICALLY_SATISFIED** | 31/31 REQ-MSG-001..031 `IMPLEMENTED`, inchangé -- REQ-MSG-009 exige structurellement l'existence d'un port/adaptateur de traduction, pas la disponibilité continue du tiers ; cette clause de traçabilité reste distincte du gate d'acceptation live de traduction réelle ci-dessus, qui lui n'est PAS satisfait |
| Regressions 01–08 | **TECHNICALLY_SATISFIED** | inchangé |
| Docs/handoff/state | **TECHNICALLY_SATISFIED** | ce document, `00_CURRENT_STATE.md` et le pack de revue humaine mis à jour honnêtement cette passe |
| Revue sémantique humaine | **EXTERNAL_ACCEPTANCE_ITEM** (bloquée en amont) | `PENDING_HUMAN_REVIEW`, et la sortie machine qu'elle devrait juger est elle-même `MACHINE_TRANSLATION_CURRENTLY_UNAVAILABLE` -- le pack documente cette double dépendance honnêtement plutôt que de fabriquer une sortie |
| Commit/push/PR/merge | Partiel, **EXTERNAL_ACCEPTANCE_ITEM** pour le merge | inchangé, `DO NOT MERGE — EXTERNAL AUDIT REQUIRED` |

**Résultat** : au moins une clause technique/canonique (`Real corpus` / `Live chaîne complète pour la
traduction`) est désormais `NOT_SATISFIED` -- même si la cause profonde est externe (provider tiers
indisponible), ce n'est **pas** une clause `EXTERNAL_ACCEPTANCE_ITEM` au sens de la Definition of
Done : le gate d'acceptation « traduction réelle » lui-même est un critère technique/canonique de
Stage09 (REQ-MSG-009/011/023/024), et il n'est objectivement pas rempli tant que le provider ne
répond pas réellement. `CURRENT_STATE` régresse donc à `STAGE_09_BLOCKED_TRANSLATION_PROVIDER_
UNAVAILABLE` -- Stage09 n'est PAS déclaré complet, conformément à l'instruction explicite de ne
jamais transformer un `NOT_SATISFIED` en `STAGE_09_COMPLETE_DRAFT_PR_OPEN`.

## Écarts connus (non dissimulés)

1. **Provider de traduction `googletrans` propre à DID, actuellement indisponible** (clause bloquante
   principale de cette passe) : `GOOGLETRANS_PROVIDER_CURRENTLY_UNAVAILABLE`. Root cause prouvée en
   direct : `translate.googleapis.com` (endpoint gtx par défaut) renvoie HTTP 429 (« unusual traffic »,
   page de blocage Google authentique) ; `translate.google.com` et ses variantes régionales renvoient
   HTTP 403. Stable sur plusieurs tentatives, plusieurs endpoints, les deux modes `http2`. Le défaut
   fail-open qui masquait auparavant cette panne (googletrans renvoyant silencieusement son sentinel
   `DUMMY_DATA` -- un écho de l'entrée -- quand `raise_exception=False`, son défaut) est **corrigé** :
   `GoogletransCampaignTranslationProvider` construit désormais son `Translator` avec
   `raise_exception=True` et vérifie défensivement le statut HTTP réel avant de faire confiance à la
   sortie. Une vraie panne échoue donc maintenant fermé, visible, jamais silencieusement acceptée.
2. **Revue sémantique humaine** : `PENDING_HUMAN_REVIEW`, bloquée en amont par (1) -- le pack
   d'échantillons documente honnêtement `MACHINE_TRANSLATION_CURRENTLY_UNAVAILABLE` plutôt que de
   fabriquer des sorties, voir `docs/90_handoffs/evidence/stage09/human-semantic-review-pack.md`.
3. **Provider de traduction tiers réellement présent dans le sandbox** (distinct de (1), un bot
   externe attaché à un Translation Group) : `EXTERNAL_SANDBOX_CAPABILITY_NOT_AVAILABLE`, inchangé --
   aucun bot externe de ce type n'existe dans ce sandbox ; l'état bloquant (provider lié, statut
   non-`DISABLED`) reste prouvé en live (`translation_group_provider_boundary`, non affecté par (1)).
4. **UNKNOWN_OUTCOME/INTERVENTION_REQUIRED réel non reproductible à la demande contre Discord** :
   `NOT_SAFELY_REPRODUCIBLE_LIVE`, inchangé, couvert par injection de panne déterministe.

Voir `docs/10_implementation/STAGE09_REQUIREMENTS_CHECKLIST_LOCAL.md` pour la matrice complète des
31 IDs et `docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md` pour la preuve fichier:ligne de
chacun.
