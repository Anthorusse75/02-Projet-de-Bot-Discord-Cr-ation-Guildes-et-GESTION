# Checklist locale STAGE 09 — 31 exigences (REQ-MSG-001..031)

## État de la candidate

- Statut global : `STAGE_09_IMPLEMENTATION_IN_PROGRESS` — trois passes cumulées de travail réel et testé (fondations WP1-WP11, remédiation externe 17 findings, puis cette troisième passe : root-cause d'intégrité, fencing strict, autorisation à la création, typage traduction/variables, dépendance MESSAGE_CONTENT, worker de livraison réel câblé au governor, CI Stage09). Restent absents : le service d'orchestration/activation de campagne qui décide QUAND créer une occurrence/livraison, l'event consumer Stage03→trigger réel, l'API HTTP, le frontend, la matrice de qualification live complète.
- Base `main` : `c41b61ae96cdb1d767c8d924212a6466b768ed60`.
- Branche : `stage/09-campaigns`.
- 22 IDs `IMPLEMENTED`, 9 IDs `PARTIALLY_IMPLEMENTED`, 0 ID `NOT_STARTED` — aucun promu au-delà de la preuve réelle disponible ; `VERIFIED` non applicable, réservé à une qualification transverse qui n'a pas eu lieu.
- Toute promotion est appuyée par fichier:ligne + test dans `00_REQUIREMENTS_TRACEABILITY.md`.

## Matrice des 31 IDs

| REQ ID | Implémentation principale | Test / preuve | Statut |
|---|---|---|---|
| REQ-MSG-001 | `PublicationMode`/`LifecycleStatus` (domain/campaigns.py) ; `evaluate_schedule` (scheduling.py) ; pas de service d'activation bout-en-bout | test_stage09_campaign_domain.py, test_stage09_scheduling.py | PARTIALLY_IMPLEMENTED |
| REQ-MSG-002 | `CampaignTarget` CHANNEL/TRANSLATION_GROUP ; `resolve_target` | test_stage09_target_resolution.py | PARTIALLY_IMPLEMENTED |
| REQ-MSG-003 | `TargetAuthorizationChecker` réinvoqué à chaque résolution, maintenant implémenté réellement (`CampaignGuildAuthorizationChecker` contre le vrai `AuthorizationService`/`PermissionEvaluator`) ; autorisation à la création (1E) ajoutée | test_authorization_is_always_rechecked_not_cached, test_stage09_authorization.py (8 tests cross-owner/cross-Guild) | IMPLEMENTED |
| REQ-MSG-004 | `validate_message_model` limites Discord réelles | test_stage09_message_safety.py::TestMessageModelLimits | IMPLEMENTED |
| REQ-MSG-005 | UNIQUE(guild_id, delivery_key) + ON CONFLICT DO NOTHING + fencing de bail strict (expiration + lifecycle au commit) + **worker réel** (`delivery_worker.py`, WP13) câblé au governor | test_stage09_campaigns_postgres.py::TestDeliveryLeaseFencing, test_stage09_delivery_worker_postgres.py (8 tests, PostgreSQL réel, race à deux workers) | PARTIALLY_IMPLEMENTED |
| REQ-MSG-006 | `AllowedMentionsCompiler` défaut aucune mention | test_stage09_message_safety.py::TestAllowedMentionsCompiler | IMPLEMENTED |
| REQ-MSG-007 | `TranslationPublicationMode` + gate publication-mode | test_stage09_target_resolution.py::TestTranslationGroupResolution | PARTIALLY_IMPLEMENTED |
| REQ-MSG-008 | structurel : aucune dépendance au bot existant | — | IMPLEMENTED |
| REQ-MSG-009 | `googletrans_adapter.py` seul importeur ; port de domaine | tests unitaires + réseau réel (backend/tests/network) | IMPLEMENTED |
| REQ-MSG-010 | `parser.parse` avant tout appel de traduction | test_stage09_parser_protector.py | IMPLEMENTED |
| REQ-MSG-011 | URL/mentions/timestamps/emoji/code/commandes/variables préservés, benchmark réel 516 appels à 100% (stratégie de production) | fuzz/property tests + translation-benchmark.json | IMPLEMENTED |
| REQ-MSG-012 | `validate_full_pipeline` échoue fermé (placeholder + reparse + structure) | test_stage09_parser_protector.py::TestCorruptionFailsClosed/TestFullPipelineValidator | IMPLEMENTED |
| REQ-MSG-013 | `did.messaging.translation_policy` — typage champ-par-champ explicite (content/embed fields/button labels), champs techniques jamais exposés au traducteur | test_stage09_translation_policy.py (8 tests) | IMPLEMENTED |
| REQ-MSG-014 | `GlossaryEntry.specificity` (3 tiers CAMPAIGN>GUILD>GLOBAL_USER) + `resolve_applicable_entries` | test_stage09_glossary.py + test_stage09_campaigns_postgres.py::TestGlossaryGuildScopeRls (PostgreSQL réel) | IMPLEMENTED |
| REQ-MSG-015 | glossaire protégé via même mécanisme que tokens techniques + `validate_full_pipeline` | test_full_pipeline_with_mentions_and_glossary_term | IMPLEMENTED |
| REQ-MSG-016 | `ApprovedVariant` + `resolve_variant_for_delivery` ; aucune UI review | test_stage09_approved_variants.py | PARTIALLY_IMPLEMENTED |
| REQ-MSG-017 | décision REUSABLE/STALE/MISSING ; non câblée à un service bout-en-bout | test_recurring_campaign_reuses_unchanged_variant_across_occurrences | PARTIALLY_IMPLEMENTED |
| REQ-MSG-018 | `did.messaging.template_variables` — 4 types (TRANSLATABLE_TEXT/NON_TRANSLATABLE/LOCALIZED_VALUE/PROTECTED) à sémantique réellement distincte | test_stage09_template_variables.py (14 tests) | IMPLEMENTED |
| REQ-MSG-019 | colonnes delivery complètes + colonnes de bail réelles ; pas de politique de rétention | test_stage09_campaigns_postgres.py | PARTIALLY_IMPLEMENTED |
| REQ-MSG-020 | `CampaignTrigger.requires_message_content` (migration 0025) + capability blocker + avertissement simulation + fail-closed runtime | test_stage09_message_content_policy.py, test_stage09_causality.py | IMPLEMENTED |
| REQ-MSG-021 | AST conditions allowlist bornée + RRULE/IANA/DST réels + curseur naive/aware corrigé | test_stage09_causality.py, test_stage09_campaigns_postgres.py::TestScheduleCursorPersistenceRoundTrip (DST réel + PostgreSQL réel) | IMPLEMENTED |
| REQ-MSG-022 | `summarize_simulation` sans effet de bord ; n'expose pas encore l'état variante approuvée/traduction | test_stage09_target_resolution.py::TestSimulationSummary | PARTIALLY_IMPLEMENTED |
| REQ-MSG-023 | TEXT jamais fragmenté artificiellement autour des tokens protégés | benchmark réel : NAIVE_PER_TEXT_NODE dégrade nettement l'intégrité | IMPLEMENTED |
| REQ-MSG-024 | benchmark réel 516 appels googletrans, 4 stratégies, matrice complète FR↔EN↔DE↔ES (12 directions) | docs/90_handoffs/evidence/stage09/translation-benchmark.json | IMPLEMENTED |
| REQ-MSG-025 | **root-cause corrigé** : trim de ponctuation finale en fin d'URL dans `parser.py` — la stratégie de production atteint 100% d'intégrité réelle mesurée, pas seulement 100% de détection | translation-benchmark.json : 100.0% (FULL_MASKED_MESSAGE/PARAGRAPH_GROUPING/SENTENCE_GROUPING) ; test_stage09_parser_protector.py::TestUrlTrailingPunctuationTrim | IMPLEMENTED |
| REQ-MSG-026 | requalifié : SHOULD conditionnel, satisfait par la non-variation appuyée sur preuve (aucune divergence d'intégrité/latence mesurée entre stratégies après le correctif REQ-MSG-025) | translation-benchmark.json + segmentation.py::select_translation_strategy docstring | IMPLEMENTED |
| REQ-MSG-027 | `should_trigger` exige un `TriggerSourceBinding` explicite | test_unbound_guild_b_cannot_trigger_guild_a_campaign | IMPLEMENTED |
| REQ-MSG-028 | `source_language_code` indépendant, testé explicitement | test_stage09_campaign_domain.py::TestSourceLanguageIndependentOfUiLocale | IMPLEMENTED |
| REQ-MSG-029 | nonce + `enforce_nonce` réellement soumis (discord.py l'active automatiquement dès qu'un nonce est fourni) ; réconciliation UNKNOWN_OUTCOME câblée dans le worker réel | test_stage09_discord_message_sender.py + qualification live réelle (5/5 PASS) + test_stage09_delivery_worker_postgres.py | IMPLEMENTED |
| REQ-MSG-030 | garde anti-boucle ancêtre + profondeur ; non câblée à un émetteur d'événements réel | test_stage09_causality.py::TestShouldTrigger | PARTIALLY_IMPLEMENTED |
| REQ-MSG-031 | `EditPayload.to_discord_kwargs` fournit toujours allowed_mentions + politique d'attachments réelle (REPLACE_ALL corrigé) | test_stage09_message_safety.py + test_stage09_discord_message_sender.py::TestEditReplaceAllAttachmentConversion | IMPLEMENTED |

## Corrections majeures de cette troisième passe (non dissimulées)

1. **Root-cause de l'intégrité de traduction (REQ-MSG-025)** : googletrans perd régulièrement l'espace précédant une ponctuation finale de phrase quand un placeholder URL termine la phrase dans la langue cible ; la regex URL non filtrée absorbait cette ponctuation collée lors du reparse. Corrigé à la source (`parser.py::_trim_url_trailing_punctuation`), appliqué identiquement au parse initial et au reparse. La matrice complète 516 appels re-exécutée après correctif : 100.0% d'intégrité réelle pour la stratégie de production (avant : 97.2%, un progrès honnêtement mesuré, pas supposé).
2. **Fencing de bail strict** : `finalize_schedule_claim` exige maintenant un bail non expiré ET une campagne toujours éligible au commit (pas seulement au moment du claim) ; `mark_delivery_sending` exige un bail non expiré avant de démarrer la mutation externe irréversible ; `finalize_delivery` reste volontairement fencé par token (pas par fraîcheur du bail), avec justification documentée.
3. **Autorisation à la création (1E)** : `did.campaigns.authorization` prouve que l'appelant possède réellement la campagne/le trigger (rechargement RLS-scopé) ET est autorisé pour la Guild destination/source avant toute persistance d'une ligne Guild-scoped — 8 tests cross-owner/cross-Guild.
4. **Worker de livraison réel (WP13)** : `did.campaigns.delivery_worker` implémente le pipeline claim→SENDING→send→finalize fencé et la réconciliation UNKNOWN_OUTCOME (retry même nonce, jamais un nonce neuf), câblé au `DiscordWorkloadGovernor` partagé sous un nouveau palier `WorkloadPriority.SEND_CAMPAIGN_MESSAGE` — prouvé par une vraie course à deux workers concurrents (exactement un seul envoi).
5. **REQ-MSG-013/018/020** : les trois gaps `NOT_STARTED` de la passe précédente sont maintenant réellement implémentés et testés (voir matrice ci-dessus).

## Écarts connus (non dissimulés)

1. **Orchestration/activation de campagne (WP12) absente** : aucun service ne décide encore QUAND créer une occurrence/livraison depuis un schedule dû ou un événement accepté — le dispatch/idempotency (WP13) qui en découlerait est réel et testé, mais rien ne l'alimente encore automatiquement.
2. **Event consumer Stage03 réel absent** : `did.campaigns.causality.should_trigger` est réel et testé, mais aucun code ne consomme encore un vrai `EventEnvelope` Stage03 pour l'invoquer.
3. **API (WP14)** : aucun router FastAPI Stage09 n'existe.
4. **Frontend (WP15)** : aucune UI Stage09 (éditeur de campagne, aperçu, historique) n'existe.
5. **Qualification live (WP16)** : `scripts/validate_discord_live_stage09.py` exécute réellement 5 scénarios ciblés — 5/5 PASS sur sandbox réelle. La matrice complète (Guild A/B, scheduler, Translation Groups, quatre langues, provider externe) reste non exécutée car l'orchestration bout-en-bout n'existe pas encore pour la produire.
6. **Sécurité anti double-traduction Translation Group** : les modes de publication existent et sont testés au niveau résolution de cible, mais aucun service ne prouve encore bout-en-bout qu'un mode EXISTING_PROVIDER empêche réellement DID de re-traduire un contenu déjà localisé par le provider existant.
7. **Revue sémantique humaine** : aucune évaluation humaine n'a eu lieu ; aucun score n'est fabriqué. À documenter comme `PENDING_HUMAN_REVIEW` si une rubrique est un jour requise, séparément de l'intégrité technique (qui, elle, est mesurée à 100% et validée machine).

Voir `docs/90_handoffs/STAGE_09_HANDOFF.md` pour le détail complet, les décisions d'architecture et les preuves.
