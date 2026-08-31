# Checklist locale STAGE 09 — 31 exigences (REQ-MSG-001..031)

## État de la candidate

- Statut global : `STAGE_09_IMPLEMENTATION_IN_PROGRESS` — fondations durables réelles (schéma/domaine/scheduler/causalité/parser-protector/glossaire/traduction/réconciliation/résolution de cibles) implémentées et testées ; pas de service d'orchestration bout-en-bout (activation de campagne → occurrence → fan-out → delivery worker), pas d'API HTTP, pas de frontend, pas de qualification live complète des 15+ scénarios attendus.
- Base `main` : `c41b61ae96cdb1d767c8d924212a6466b768ed60`.
- Branche : `stage/09-campaigns`.
- 15 IDs `IMPLEMENTED`, 13 IDs `PARTIALLY_IMPLEMENTED`, 3 IDs `NOT_STARTED` — aucun promu au-delà de la preuve réelle disponible ; `VERIFIED` non applicable, réservé à une qualification transverse qui n'a pas eu lieu.
- Toute promotion est appuyée par fichier:ligne + test dans `00_REQUIREMENTS_TRACEABILITY.md`.

## Matrice des 31 IDs

| REQ ID | Implémentation principale | Test / preuve | Statut |
|---|---|---|---|
| REQ-MSG-001 | `PublicationMode`/`LifecycleStatus` (domain/campaigns.py) ; `evaluate_schedule` (scheduling.py) | test_stage09_campaign_domain.py, test_stage09_scheduling.py | PARTIALLY_IMPLEMENTED |
| REQ-MSG-002 | `CampaignTarget` CHANNEL/TRANSLATION_GROUP ; `resolve_target` | test_stage09_target_resolution.py | PARTIALLY_IMPLEMENTED |
| REQ-MSG-003 | `TargetAuthorizationChecker` réinvoqué à chaque résolution | test_authorization_is_always_rechecked_not_cached | PARTIALLY_IMPLEMENTED |
| REQ-MSG-004 | `validate_message_model` limites Discord réelles | test_stage09_message_safety.py::TestMessageModelLimits | IMPLEMENTED |
| REQ-MSG-005 | UNIQUE(guild_id, delivery_key) + ON CONFLICT DO NOTHING | test_stage09_campaigns_postgres.py (PostgreSQL réel) | PARTIALLY_IMPLEMENTED |
| REQ-MSG-006 | `AllowedMentionsCompiler` défaut aucune mention | test_stage09_message_safety.py::TestAllowedMentionsCompiler | IMPLEMENTED |
| REQ-MSG-007 | `TranslationPublicationMode` + gate publication-mode | test_stage09_target_resolution.py::TestTranslationGroupResolution | PARTIALLY_IMPLEMENTED |
| REQ-MSG-008 | structurel : aucune dépendance au bot existant | — | IMPLEMENTED |
| REQ-MSG-009 | `googletrans_adapter.py` seul importeur ; port de domaine | tests unitaires + réseau réel (backend/tests/network) | IMPLEMENTED |
| REQ-MSG-010 | `parser.parse` avant tout appel de traduction | test_stage09_parser_protector.py | IMPLEMENTED |
| REQ-MSG-011 | URL/mentions/timestamps/emoji/code/commandes/variables préservés | fuzz/property tests + benchmark réel 100% intégrité | IMPLEMENTED |
| REQ-MSG-012 | `validate_and_restore` échoue fermé | test_stage09_parser_protector.py::TestCorruptionFailsClosed | IMPLEMENTED |
| REQ-MSG-013 | aucun typage champ-par-champ embed/composant | — | NOT_STARTED |
| REQ-MSG-014 | `GlossaryEntry.specificity` + `resolve_applicable_entries` | test_stage09_glossary.py::TestResolveApplicableEntries | IMPLEMENTED |
| REQ-MSG-015 | glossaire protégé via même mécanisme que tokens techniques | test_full_pipeline_with_mentions_and_glossary_term | IMPLEMENTED |
| REQ-MSG-016 | `ApprovedVariant` + `resolve_variant_for_delivery` ; aucune UI review | test_stage09_approved_variants.py | PARTIALLY_IMPLEMENTED |
| REQ-MSG-017 | décision REUSABLE/STALE/MISSING ; non câblée à un service bout-en-bout | test_recurring_campaign_reuses_unchanged_variant_across_occurrences | PARTIALLY_IMPLEMENTED |
| REQ-MSG-018 | `TEMPLATE_VARIABLE` toujours protégé ; pas de typage 3 états complet | test_stage09_parser_protector.py | PARTIALLY_IMPLEMENTED |
| REQ-MSG-019 | colonnes delivery complètes (migration 0022) ; pas de politique de rétention | test_stage09_campaigns_postgres.py | PARTIALLY_IMPLEMENTED |
| REQ-MSG-020 | aucun champ/mécanisme de déclaration `MESSAGE_CONTENT` | — | NOT_STARTED |
| REQ-MSG-021 | AST conditions allowlist + RRULE/IANA/DST réels | test_stage09_causality.py, test_stage09_scheduling.py (DST Europe/Paris 2026 réel) | IMPLEMENTED |
| REQ-MSG-022 | `summarize_simulation` sans effet de bord | test_stage09_target_resolution.py::TestSimulationSummary | PARTIALLY_IMPLEMENTED |
| REQ-MSG-023 | TEXT jamais fragmenté artificiellement autour des tokens protégés | benchmark réel : NAIVE_PER_TEXT_NODE dégrade l'espacement (preuve empirique) | IMPLEMENTED |
| REQ-MSG-024 | benchmark réel 288 appels googletrans, 4 stratégies, EN→FR/DE/ES | docs/90_handoffs/evidence/stage09/translation-benchmark.json | IMPLEMENTED |
| REQ-MSG-025 | 100% intégrité sur 288 appels réels + corpus fuzz | translation-benchmark.json + test_stage09_parser_protector.py | IMPLEMENTED |
| REQ-MSG-026 | preuve mesurée insuffisante pour justifier une variation par classe | translation-benchmark.json (aucune divergence significative observée) | NOT_STARTED |
| REQ-MSG-027 | `should_trigger` exige un `TriggerSourceBinding` explicite | test_unbound_guild_b_cannot_trigger_guild_a_campaign | IMPLEMENTED |
| REQ-MSG-028 | `source_language_code` indépendant, testé explicitement | test_stage09_campaign_domain.py::TestSourceLanguageIndependentOfUiLocale | IMPLEMENTED |
| REQ-MSG-029 | nonce généré/câblé ; `enforce_nonce` absent de discord.py==2.7.1 (vérifié) | docs/90_handoffs/evidence/stage09/nonce-reconciliation-probe.json (sonde live réelle) | PARTIALLY_IMPLEMENTED |
| REQ-MSG-030 | garde anti-boucle ancêtre + profondeur ; non câblée à un émetteur d'événements réel | test_stage09_causality.py::TestShouldTrigger | PARTIALLY_IMPLEMENTED |
| REQ-MSG-031 | `EditPayload.to_discord_kwargs` fournit toujours allowed_mentions + politique d'attachments | test_stage09_message_safety.py::TestEditPayloadAttachmentPolicy | IMPLEMENTED |

## Écarts connus (non dissimulés)

1. **Orchestration bout-en-bout absente** : aucun service ne relie encore activation de campagne → création d'occurrence → fan-out de cibles → job `discord_io_jobs` → delivery worker → statut final. Chaque brique (WP1–WP11) est réelle et testée isolément (y compris contre PostgreSQL réel et le vrai réseau/sandbox Discord) mais n'est pas câblée en pipeline complet.
2. **Governor/worker (WP13)** : décision architecturale prise et documentée (réutiliser `discord_io_jobs` + `DiscordWorkloadGovernor` via un nouveau `workload_type`), mais le branchement réel dans `worker.py`/`scheduler/__main__.py` n'est pas fait ; aucun test de charge/fairness Stage09 n'existe.
3. **API (WP14)** : aucun router FastAPI Stage09 n'existe.
4. **Frontend (WP15)** : aucune UI Stage09 (éditeur de campagne, aperçu, historique) n'existe.
5. **Qualification live (WP16)** : deux sondes live réelles et ciblées ont été exécutées (persistance du nonce, dédup par défaut) avec preuve committée et nettoyage complet ; la matrice complète de scénarios (envoi immédiat/planifié, edit/delete réels via un delivery bout-en-bout, Translation Group publication, quatre langues, provider externe présent/absent) n'a pas été exécutée car l'orchestration bout-en-bout n'existe pas encore pour la produire.
6. **REQ-MSG-013/018/020/026** : gaps réels documentés ci-dessus, non dissimulés.

Voir `docs/90_handoffs/STAGE_09_HANDOFF.md` pour le détail complet, les décisions d'architecture et les preuves.
