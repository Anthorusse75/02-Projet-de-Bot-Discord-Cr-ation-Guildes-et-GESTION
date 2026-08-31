# Checklist locale STAGE 09 — 31 exigences (REQ-MSG-001..031)

## État de la candidate

- Statut global : `STAGE_09_IMPLEMENTATION_IN_PROGRESS` — fondations durables réelles (schéma/domaine/scheduler/causalité/parser-protector/glossaire/traduction/réconciliation/résolution de cibles) implémentées et testées ; pas de service d'orchestration bout-en-bout (activation de campagne → occurrence → fan-out → delivery worker), pas d'API HTTP, pas de frontend, pas de qualification live complète des 15+ scénarios attendus.
- Base `main` : `c41b61ae96cdb1d767c8d924212a6466b768ed60`.
- Branche : `stage/09-campaigns`.
- **Passe de remédiation externe intégrée** (17 findings) : intégrité relationnelle DB (FK composites owner+campaign, campaign+target, campaign+occurrence), persistance du curseur scheduler (naive/aware corrigé, round-trip PostgreSQL réel), fencing de bail schedule/delivery, bornage de l'AST de condition, correction majeure `enforce_nonce` (disponible, pas absent — erreur d'investigation antérieure corrigée), benchmark refait sur la matrice complète FR/EN/DE/ES (516 appels réels), validateur d'intégrité renforcé (`validate_full_pipeline`, révèle une corruption réelle d'espacement autour des URLs précédemment non détectée), tiers de glossaire GUILD manquant ajouté, correctif `REPLACE_ALL`, entrée `validate_stage.py 09` réelle, qualification live Stage09 ciblée réelle (5/5 scénarios PASS).
- 16 IDs `IMPLEMENTED`, 12 IDs `PARTIALLY_IMPLEMENTED`, 3 IDs `NOT_STARTED` — aucun promu au-delà de la preuve réelle disponible ; `VERIFIED` non applicable, réservé à une qualification transverse qui n'a pas eu lieu.
- Toute promotion est appuyée par fichier:ligne + test dans `00_REQUIREMENTS_TRACEABILITY.md`.

## Matrice des 31 IDs

| REQ ID | Implémentation principale | Test / preuve | Statut |
|---|---|---|---|
| REQ-MSG-001 | `PublicationMode`/`LifecycleStatus` (domain/campaigns.py) ; `evaluate_schedule` (scheduling.py) | test_stage09_campaign_domain.py, test_stage09_scheduling.py | PARTIALLY_IMPLEMENTED |
| REQ-MSG-002 | `CampaignTarget` CHANNEL/TRANSLATION_GROUP ; `resolve_target` | test_stage09_target_resolution.py | PARTIALLY_IMPLEMENTED |
| REQ-MSG-003 | `TargetAuthorizationChecker` réinvoqué à chaque résolution | test_authorization_is_always_rechecked_not_cached | PARTIALLY_IMPLEMENTED |
| REQ-MSG-004 | `validate_message_model` limites Discord réelles | test_stage09_message_safety.py::TestMessageModelLimits | IMPLEMENTED |
| REQ-MSG-005 | UNIQUE(guild_id, delivery_key) + ON CONFLICT DO NOTHING + fencing de bail réel | test_stage09_campaigns_postgres.py::TestDeliveryLeaseFencing (PostgreSQL réel) | PARTIALLY_IMPLEMENTED |
| REQ-MSG-006 | `AllowedMentionsCompiler` défaut aucune mention | test_stage09_message_safety.py::TestAllowedMentionsCompiler | IMPLEMENTED |
| REQ-MSG-007 | `TranslationPublicationMode` + gate publication-mode | test_stage09_target_resolution.py::TestTranslationGroupResolution | PARTIALLY_IMPLEMENTED |
| REQ-MSG-008 | structurel : aucune dépendance au bot existant | — | IMPLEMENTED |
| REQ-MSG-009 | `googletrans_adapter.py` seul importeur ; port de domaine | tests unitaires + réseau réel (backend/tests/network) | IMPLEMENTED |
| REQ-MSG-010 | `parser.parse` avant tout appel de traduction | test_stage09_parser_protector.py | IMPLEMENTED |
| REQ-MSG-011 | URL/mentions/timestamps/emoji/code/commandes/variables préservés | fuzz/property tests + benchmark réel 516 appels (voir REQ-MSG-025 pour le taux exact) | IMPLEMENTED |
| REQ-MSG-012 | `validate_full_pipeline` échoue fermé (placeholder + reparse + structure) | test_stage09_parser_protector.py::TestCorruptionFailsClosed/TestFullPipelineValidator | IMPLEMENTED |
| REQ-MSG-013 | aucun typage champ-par-champ embed/composant | — | NOT_STARTED |
| REQ-MSG-014 | `GlossaryEntry.specificity` (3 tiers CAMPAIGN>GUILD>GLOBAL_USER) + `resolve_applicable_entries` | test_stage09_glossary.py + test_stage09_campaigns_postgres.py::TestGlossaryGuildScopeRls (PostgreSQL réel) | IMPLEMENTED |
| REQ-MSG-015 | glossaire protégé via même mécanisme que tokens techniques + `validate_full_pipeline` | test_full_pipeline_with_mentions_and_glossary_term | IMPLEMENTED |
| REQ-MSG-016 | `ApprovedVariant` + `resolve_variant_for_delivery` ; aucune UI review | test_stage09_approved_variants.py | PARTIALLY_IMPLEMENTED |
| REQ-MSG-017 | décision REUSABLE/STALE/MISSING ; non câblée à un service bout-en-bout | test_recurring_campaign_reuses_unchanged_variant_across_occurrences | PARTIALLY_IMPLEMENTED |
| REQ-MSG-018 | `TEMPLATE_VARIABLE` toujours protégé ; pas de typage 3 états complet | test_stage09_parser_protector.py | PARTIALLY_IMPLEMENTED |
| REQ-MSG-019 | colonnes delivery complètes + colonnes de bail réelles ; pas de politique de rétention | test_stage09_campaigns_postgres.py | PARTIALLY_IMPLEMENTED |
| REQ-MSG-020 | aucun champ/mécanisme de déclaration `MESSAGE_CONTENT` | — | NOT_STARTED |
| REQ-MSG-021 | AST conditions allowlist bornée + RRULE/IANA/DST réels + curseur naive/aware corrigé | test_stage09_causality.py, test_stage09_campaigns_postgres.py::TestScheduleCursorPersistenceRoundTrip (DST réel + PostgreSQL réel) | IMPLEMENTED |
| REQ-MSG-022 | `summarize_simulation` sans effet de bord | test_stage09_target_resolution.py::TestSimulationSummary | PARTIALLY_IMPLEMENTED |
| REQ-MSG-023 | TEXT jamais fragmenté artificiellement autour des tokens protégés | benchmark réel : NAIVE_PER_TEXT_NODE dégrade nettement l'intégrité (preuve empirique renforcée) | IMPLEMENTED |
| REQ-MSG-024 | benchmark réel 516 appels googletrans, 4 stratégies, matrice complète FR↔EN↔DE↔ES (12 directions) | docs/90_handoffs/evidence/stage09/translation-benchmark.json | IMPLEMENTED |
| REQ-MSG-025 | **corrigé** : validateur renforcé révèle une corruption réelle (espacement autour des URLs) non détectée par l'ancien validateur plus faible | translation-benchmark.json : 97.2% (3 stratégies) / 66.7% (naïve) ; échec fermé 100% fiable (aucun faux négatif) | PARTIALLY_IMPLEMENTED |
| REQ-MSG-026 | preuve mesurée insuffisante pour justifier une variation par classe | translation-benchmark.json (seuil arbitraire précédent retiré, aucune preuve ne le justifiait) | NOT_STARTED |
| REQ-MSG-027 | `should_trigger` exige un `TriggerSourceBinding` explicite | test_unbound_guild_b_cannot_trigger_guild_a_campaign | IMPLEMENTED |
| REQ-MSG-028 | `source_language_code` indépendant, testé explicitement | test_stage09_campaign_domain.py::TestSourceLanguageIndependentOfUiLocale | IMPLEMENTED |
| REQ-MSG-029 | **corrigé** : nonce + `enforce_nonce` réellement soumis (discord.py l'active automatiquement dès qu'un nonce est fourni) | test_stage09_discord_message_sender.py (preuve payload directe) + qualification live réelle (5/5 PASS) | IMPLEMENTED |
| REQ-MSG-030 | garde anti-boucle ancêtre + profondeur ; non câblée à un émetteur d'événements réel | test_stage09_causality.py::TestShouldTrigger | PARTIALLY_IMPLEMENTED |
| REQ-MSG-031 | `EditPayload.to_discord_kwargs` fournit toujours allowed_mentions + politique d'attachments réelle (REPLACE_ALL corrigé) | test_stage09_message_safety.py + test_stage09_discord_message_sender.py::TestEditReplaceAllAttachmentConversion | IMPLEMENTED |

## Corrections majeures issues de la revue externe (non dissimulées)

1. **`enforce_nonce` (REQ-MSG-029)** : l'affirmation initiale « indisponible dans discord.py==2.7.1 » était FAUSSE — causée par un grep récursif échouant silencieusement sur le chemin accentué du dépôt, pas par une vraie limitation de la librairie. `discord/http.py` l'active automatiquement dès qu'un nonce est fourni. Corrigé dans le code, les preuves et cette checklist.
2. **Intégrité de traduction (REQ-MSG-025)** : un validateur plus rigoureux (`validate_full_pipeline`, avec reparse-et-comparaison) a révélé une corruption réelle (perte d'espace autour d'URLs restaurées) que l'ancien validateur plus faible ne détectait pas. Le taux d'intégrité réel mesuré est 97.2% (bonnes stratégies) / 66.7% (stratégie naïve), pas 100% — mais l'échec fermé reste fiable à 100% (zéro faux négatif, zéro publication silencieuse de contenu corrompu).
3. **Intégrité relationnelle DB (WP1)** : FK composites owner+campaign et campaign+target/occurrence ajoutées (migration `0023_stage_09`) avec preuves PostgreSQL négatives réelles pour chaque cas cross-owner/cross-campaign.
4. **Curseur scheduler naive/aware** : bug réel corrigé (migration `0023_stage_09`), prouvé par un round-trip PostgreSQL réel traversant la transition DST 2026 réelle.
5. **Glossaire GUILD (REQ-MSG-014)** : tiers manquant ajouté (migration `0024_stage_09`), politique RLS à double condition prouvée sur PostgreSQL réel.
6. **`REPLACE_ALL`** : corrigé — n'est plus silencieusement équivalent à `PRESERVE_EXISTING`.

## Écarts connus (non dissimulés)

1. **Orchestration bout-en-bout absente** : aucun service ne relie encore activation de campagne → création d'occurrence → fan-out de cibles → job `discord_io_jobs` → delivery worker → statut final. Chaque brique (WP1–WP11) est réelle et testée isolément (y compris contre PostgreSQL réel et le vrai réseau/sandbox Discord) mais n'est pas câblée en pipeline complet.
2. **Governor/worker (WP13)** : décision architecturale prise et documentée (réutiliser `discord_io_jobs` + `DiscordWorkloadGovernor` via un nouveau `workload_type`), mais le branchement réel dans `worker.py`/`scheduler/__main__.py` n'est pas fait ; aucun test de charge/fairness Stage09 n'existe.
3. **API (WP14)** : aucun router FastAPI Stage09 n'existe.
4. **Frontend (WP15)** : aucune UI Stage09 (éditeur de campagne, aperçu, historique) n'existe.
5. **Qualification live (WP16)** : `scripts/validate_discord_live_stage09.py` exécute réellement 5 scénarios ciblés (envoi immédiat allowed_mentions=none, edit possédé, delete possédé, dédup nonce, nonce distinct) — 5/5 PASS sur sandbox réelle. La matrice complète de scénarios (envoi planifié, retry après crash, Translation Group publication, quatre langues, provider externe présent/absent) reste non exécutée car l'orchestration bout-en-bout n'existe pas encore pour la produire.
6. **Corruption résiduelle de traduction (REQ-MSG-025)** : la perte d'espacement autour des URLs restaurées reste un problème réel non résolu au niveau du format de placeholder ; toujours détectée et bloquée, jamais publiée silencieusement, mais nécessite une amélioration future du format de placeholder pour atteindre 100% de non-corruption (pas seulement 100% de détection).
7. **REQ-MSG-013/018/020/026** : gaps réels documentés ci-dessus, non dissimulés.

Voir `docs/90_handoffs/STAGE_09_HANDOFF.md` pour le détail complet, les décisions d'architecture et les preuves.
