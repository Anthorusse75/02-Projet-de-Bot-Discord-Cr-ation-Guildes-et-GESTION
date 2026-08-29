# Checklist locale STAGE 08 — 43 exigences

## État de la candidate

- Statut global : `STAGE_08_COMPLETE_DRAFT_PR_OPEN`.
- Base `main` : `252a4661195a3868acd04a2987453e23fc6ee4ff`.
- Branche : `stage/08-multilingual-topology` ; PR #8 conservée en Draft.
- Les 43 IDs sont `IMPLEMENTED`. Ils ne sont pas promus à `VERIFIED`, statut réservé à la qualification transverse prévue par la politique du dépôt.
- STAGE 09 : `NOT_STARTED` et interdit avant merge de STAGE 08.

## Matrice des 43 IDs

| REQ ID | Implémentation principale | Test / preuve | Statut |
|---|---|---|---|
| REQ-I18N-001 | `translation_topology.py`, migration `0014_stage_08` : identités Language/Group/Scope séparées | `test_stage08_translation_topology.py`, PostgreSQL A/B | IMPLEMENTED |
| REQ-I18N-002 | `translation_groups` tenant-scoped, clés composites et RLS | `test_stage08_persistence.py` | IMPLEMENTED |
| REQ-I18N-003 | variants/routes liés au groupe, aucune association implicite | unitaires + preuve PostgreSQL de deux groupes FR/EN indépendants | IMPLEMENTED |
| REQ-I18N-004 | `translation_channel_groups.id` stable ; `display_name` renommable via migration `0015_stage_08` | `test_stage08_application_postgres.py` | IMPLEMENTED |
| REQ-I18N-005 | `ResourceLanguageResolver` SELF/CATEGORY/NONE, override explicite | `test_inheritance_requires_intent_and_never_returns_a_disabled_profile` + E2E | IMPLEMENTED |
| REQ-I18N-006 | liaison explicite de variants indépendante du parent category | FKs same-group PostgreSQL et API `link` | IMPLEMENTED |
| REQ-I18N-007 | `TranslationRouteCompiler` HUB/CUSTOM/FULL_MESH conditionné | tests topologies et capability unknown/unsupported | IMPLEMENTED |
| REQ-I18N-008 | `TranslationCloneExpander` avec pipeline portable en sept phases | test clone unitaire + Playwright A→B | IMPLEMENTED |
| REQ-I18N-009 | `add_language_delta` transactionnel, sans recréation | test application PostgreSQL | IMPLEMENTED |
| REQ-I18N-010 | retrait de langue non destructif par défaut | service/API + test PostgreSQL | IMPLEMENTED |
| REQ-I18N-011 | `unlink_variant` retire uniquement l’association logique | service/API + test PostgreSQL | IMPLEMENTED |
| REQ-I18N-012 | `link_existing_variant` exige `confirmed_explicit_selection` | test application et schéma API | IMPLEMENTED |
| REQ-I18N-013 | ActionRegistry : CREATE_VARIANT/LINK_EXISTING_VARIANT/CLONE_UNLINKED/PREVIEW | tests composant et Playwright Right Drag/clavier | IMPLEMENTED |
| REQ-I18N-014 | déclaration de langue séparée de la visibilité, défaut OPEN_ALL | tests resolver/compiler | IMPLEMENTED |
| REQ-I18N-015 | compiler OPEN_ALL/LANGUAGE_FILTERED/SCOPE_AND_LANGUAGE/CUSTOM explicite | `test_visibility_compiler_*` | IMPLEMENTED |
| REQ-I18N-016 | aucune approximation Discord « rôle Scope + rôle Language = AND » | test exact des deux overwrites et du rôle dérivé unique | IMPLEMENTED |
| REQ-I18N-017 | binding durable Visibility Scope × Language | migration `0014`, repository et tests RLS | IMPLEMENTED |
| REQ-I18N-018 | unicité/réutilisation du binding indépendante du Translation Group | tests optimizer, concurrence PostgreSQL et live | IMPLEMENTED |
| REQ-I18N-019 | rôle technique `permissions=0`, `hoist=false`, `mentionable=false` | test unitaire et validator live | IMPLEMENTED |
| REQ-I18N-020 | `RoleOptimizer` et `RoleCapacityEngine` pré-plan | tests limite et limite+1 | IMPLEMENTED |
| REQ-I18N-021 | budget d’overwrites par salon, blocage au-delà de 1000 | tests limite et live counts | IMPLEMENTED |
| REQ-I18N-022 | aucun member overwrite comme stratégie standard | test `MemberTechnicalRoleReconciler.diff` | IMPLEMENTED |
| REQ-I18N-023 | intersection langues visibles × scopes réellement acquis | test reconciler | IMPLEMENTED |
| REQ-I18N-024 | aucun rôle universel ALL_LANGUAGES | test reconciler et scan de sortie | IMPLEMENTED |
| REQ-I18N-025 | port abstrait `TranslationProvider` et registry | `translation_provider.py`, tests de contrat | IMPLEMENTED |
| REQ-I18N-026 | capacités connues/inconnues/supportées/non supportées et health | tests provider/route preflight | IMPLEMENTED |
| REQ-I18N-026A | adapter bot existant non invasif, sans token/API/schema ; mode manuel | test `NonInvasiveExistingBotProvider` | IMPLEMENTED |
| REQ-I18N-027 | topologie DID sans intent MESSAGE_CONTENT | validator live : `message_content_intent=0` | IMPLEMENTED |
| REQ-I18N-028 | `requires_message_content` appartient aux capacités provider | test provider non invasif | IMPLEMENTED |
| REQ-I18N-029 | MISSING seulement sur preuve positive de suppression | test drift GATEWAY_DELETE vs omission | IMPLEMENTED |
| REQ-I18N-030 | drift visible, réparation `PLAN_REQUIRED`, aucune propagation destructive | test drift, UI et route repair/plan | IMPLEMENTED |
| REQ-I18N-031 | clone A→B avec nouveaux IDs et aucune liaison live | test unitaire, autorisation A/B et Playwright | IMPLEMENTED |
| REQ-I18N-032 | aucun token/secret/blob provider dans l’artifact | test inspection artifact + secret scan | IMPLEMENTED |
| REQ-I18N-033 | état provider partiel diagnostiquable, pas de rollback destructif | tests manual/pending verification et UI | IMPLEMENTED |
| REQ-I18N-034 | Translation Workspace complète et arborescente | 4 tests composant + 8 scénarios STAGE 08 Playwright | IMPLEMENTED |
| REQ-I18N-035 | audit création/link/unlink/routes/langues/visibilité/provider | routes Stage 08 + `Stage08AuditRepository` | IMPLEMENTED |
| REQ-I18N-036 | preflight présence et permissions effectives de chaque variant | test provider + live sur 4 variants | IMPLEMENTED |
| REQ-I18N-037 | ADMINISTRATOR jamais recommandé, seulement signalé | test `PROVIDER_HAS_ADMINISTRATOR` | IMPLEMENTED |
| REQ-I18N-038 | accès bot provider séparé des rôles d’audience humaine | coordinator/compiler séparés + tests | IMPLEMENTED |
| REQ-I18N-039 | choix de langue incapable d’accorder un scope métier | test intersection du reconciler | IMPLEMENTED |
| REQ-I18N-040 | source ONBOARDING persistée et réconciliation déterministe | services member languages + tests PostgreSQL | IMPLEMENTED |
| REQ-I18N-041 | ensemble de zéro/une/plusieurs langues, aucun primary | tests unitaires, PostgreSQL et E2E API | IMPLEMENTED |
| REQ-I18N-042 | disable/retrait sans fallback ni changement silencieux des autres langues | tests application PostgreSQL | IMPLEMENTED |

## Gates de candidate

- `python scripts/validate_stage.py 08` : PASS.
- `python scripts/validate_stage.py 08 --profile e2e` : PASS, 39 scénarios cumulés dont 8 propres à STAGE 08.
- `python scripts/validate_stage.py 08 --include-discord-live` : PASS avec Guild A/B réelles, sans secret ni identifiant Discord dans la preuve.
- Migration réversible `0013_stage_07 → 0014_stage_08 → 0015_stage_08 → 0013_stage_07 → head` : PASS.
- Secret scan, docs, Ruff, format, MyPy, frontend lint/typecheck/build/i18n/OpenAPI : PASS.
