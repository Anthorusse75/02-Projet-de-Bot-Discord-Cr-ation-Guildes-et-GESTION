# Checklist locale STAGE 08 — 43 exigences

## État de la candidate

- Statut global : `STAGE_08_COMPLETE_DRAFT_PR_OPEN`.
- Base `main` : `252a4661195a3868acd04a2987453e23fc6ee4ff`.
- Branche : `stage/08-multilingual-topology` ; PR #8 conservée en Draft.
- Les 43 IDs sont temporairement `IN_PROGRESS` pendant la correction des findings de deep review. Aucun ne reviendra à `IMPLEMENTED` sans preuve intégrée conforme ; `VERIFIED` reste réservé à la qualification transverse.
- STAGE 09 : `NOT_STARTED` et interdit avant merge de STAGE 08.

## Matrice des 43 IDs

| REQ ID | Implémentation principale | Test / preuve | Statut |
|---|---|---|---|
| REQ-I18N-001 | `translation_topology.py`, migration `0014_stage_08` : identités Language/Group/Scope séparées | preuve à réévaluer | IN_PROGRESS |
| REQ-I18N-002 | `translation_groups` tenant-scoped, clés composites et RLS | preuve à réévaluer | IN_PROGRESS |
| REQ-I18N-003 | variants/routes liés au groupe, aucune association implicite | isolation intra-Guild à corriger et prouver | IN_PROGRESS |
| REQ-I18N-004 | `translation_channel_groups.id` stable ; `display_name` renommable via migration `0015_stage_08` | isolation parent/enfant à corriger et prouver | IN_PROGRESS |
| REQ-I18N-005 | `ResourceLanguageResolver` SELF/CATEGORY/NONE, override explicite | preuve intégrée à réévaluer | IN_PROGRESS |
| REQ-I18N-006 | liaison explicite de variants indépendante du parent category | compatibilité et parentage à corriger | IN_PROGRESS |
| REQ-I18N-007 | `TranslationRouteCompiler` HUB/CUSTOM/FULL_MESH conditionné | autorité backend à corriger | IN_PROGRESS |
| REQ-I18N-008 | clone intégré au pipeline portable 06→05 | pipeline réel et live A→B requis | IN_PROGRESS |
| REQ-I18N-009 | `add_language_delta` transactionnel, sans recréation | langue disabled/version atomique à prouver | IN_PROGRESS |
| REQ-I18N-010 | retrait de langue non destructif par défaut | compiler métier→DSG requis | IN_PROGRESS |
| REQ-I18N-011 | `unlink_variant` retire uniquement l’association logique | isolation parent/enfant à corriger | IN_PROGRESS |
| REQ-I18N-012 | liaison manuelle confirmée et compatible | validation backend autoritative requise | IN_PROGRESS |
| REQ-I18N-013 | ActionRegistry exécute les intents réels | exécution backend et E2E réel requis | IN_PROGRESS |
| REQ-I18N-014 | déclaration de langue séparée de la visibilité, défaut OPEN_ALL | modèle sémantique unifié à réévaluer | IN_PROGRESS |
| REQ-I18N-015 | compiler OPEN_ALL/LANGUAGE_FILTERED/SCOPE_AND_LANGUAGE/CUSTOM explicite | contradiction LANGUAGE_FILTERED à corriger | IN_PROGRESS |
| REQ-I18N-016 | aucune approximation Discord « rôle Scope + rôle Language = AND » | lifecycle réel à prouver | IN_PROGRESS |
| REQ-I18N-017 | binding durable Visibility Scope × Language | write-through après vérification requis | IN_PROGRESS |
| REQ-I18N-018 | unicité/réutilisation du binding indépendante du Translation Group | concurrence et rôle réel requis | IN_PROGRESS |
| REQ-I18N-019 | rôle technique `permissions=0`, `hoist=false`, `mentionable=false` | création/vérification réelle requise | IN_PROGRESS |
| REQ-I18N-020 | optimizer et capacité protègent les plans réels | preflight autoritatif requis | IN_PROGRESS |
| REQ-I18N-021 | budget d’overwrites par salon | inventaire cache-first autoritatif requis | IN_PROGRESS |
| REQ-I18N-022 | aucun member overwrite comme stratégie standard | reconciler applicatif réel requis | IN_PROGRESS |
| REQ-I18N-023 | intersection langues visibles × scopes réellement acquis | chargement autoritatif requis | IN_PROGRESS |
| REQ-I18N-024 | aucun rôle universel ALL_LANGUAGES | lifecycle membre à réévaluer | IN_PROGRESS |
| REQ-I18N-025 | port abstrait `TranslationProvider` et registry | orchestration lifecycle requise | IN_PROGRESS |
| REQ-I18N-026 | capacités/health provider autoritatives | valeurs client non fiables à retirer | IN_PROGRESS |
| REQ-I18N-026A | adapter bot existant non invasif ; mode manuel | vérification de transition requise | IN_PROGRESS |
| REQ-I18N-027 | topologie DID sans intent MESSAGE_CONTENT | preuve live réelle à renouveler | IN_PROGRESS |
| REQ-I18N-028 | `requires_message_content` appartient aux capacités provider | preuve provider à réévaluer | IN_PROGRESS |
| REQ-I18N-029 | MISSING seulement sur preuve backend positive | intégration Gateway requise | IN_PROGRESS |
| REQ-I18N-030 | drift visible et réparation par plan | projector et plan réel requis | IN_PROGRESS |
| REQ-I18N-031 | clone A→B avec nouveaux IDs et aucune liaison live | clone destination réel requis | IN_PROGRESS |
| REQ-I18N-032 | aucun secret provider dans l’artifact | DTO allowlist et tests imbriqués requis | IN_PROGRESS |
| REQ-I18N-033 | état provider partiel diagnostiquable, sans rollback destructif | orchestration post-vérification requise | IN_PROGRESS |
| REQ-I18N-034 | Translation Workspace complète et arborescente | cibles/actions réelles à corriger | IN_PROGRESS |
| REQ-I18N-035 | audit des mutations STAGE 08 | nouveaux lifecycles à auditer | IN_PROGRESS |
| REQ-I18N-036 | preflight présence/permissions effectives provider | autorité cache/read-model requise | IN_PROGRESS |
| REQ-I18N-037 | ADMINISTRATOR jamais recommandé, seulement signalé | preuve autoritative à réévaluer | IN_PROGRESS |
| REQ-I18N-038 | accès provider séparé des rôles humains | preuve lifecycle à réévaluer | IN_PROGRESS |
| REQ-I18N-039 | choix de langue incapable d’accorder un scope métier | reconciler autoritatif requis | IN_PROGRESS |
| REQ-I18N-040 | source ONBOARDING et réconciliation déterministe | bridge applicatif réel requis | IN_PROGRESS |
| REQ-I18N-041 | ensemble zéro/une/plusieurs langues, aucun primary | preuve intégrée à réévaluer | IN_PROGRESS |
| REQ-I18N-042 | disable/retrait sans fallback silencieux | delta disabled/version à prouver | IN_PROGRESS |

## Gates de candidate

- `python scripts/validate_stage.py 08` : PASS.
- `python scripts/validate_stage.py 08 --profile e2e` : PASS, 39 scénarios cumulés dont 8 propres à STAGE 08.
- `python scripts/validate_stage.py 08 --include-discord-live` : PASS avec Guild A/B réelles, sans secret ni identifiant Discord dans la preuve.
- Migration réversible `0013_stage_07 → 0014_stage_08 → 0015_stage_08 → 0013_stage_07 → head` : PASS.
- Secret scan, docs, Ruff, format, MyPy, frontend lint/typecheck/build/i18n/OpenAPI : PASS.
