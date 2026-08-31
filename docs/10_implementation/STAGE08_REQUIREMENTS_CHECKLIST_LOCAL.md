# Checklist locale STAGE 08 — 43 exigences

## État de la candidate

- Statut global : `STAGE_08_COMPLETE_DRAFT_PR_OPEN` — corrections deep-review intégrées et re-qualifiées non-live ; qualification live réelle PASS sur sandbox après correctif de l'accès control-plane du bot (`592b94b`).
- Base `main` : `252a4661195a3868acd04a2987453e23fc6ee4ff`.
- Branche : `stage/08-multilingual-topology` ; PR #8 conservée en Draft.
- Les 43 IDs sont `IMPLEMENTED` avec preuve intégrée réévaluée (fichier:ligne + test) ci-dessous ; `VERIFIED` reste réservé à la qualification transverse.
- STAGE 09 : `NOT_STARTED` et interdit avant merge de STAGE 08.

## Matrice des 43 IDs

| REQ ID | Implémentation principale | Test / preuve | Statut |
|---|---|---|---|
| REQ-I18N-001 | `translation_topology.py`, migration `0014_stage_08` : identités Language/Group/Scope séparées | isolation A/B PostgreSQL prouvée (test_stage08_application_postgres.py:277-382) | IMPLEMENTED |
| REQ-I18N-002 | `translation_groups` tenant-scoped, clés composites et RLS | RLS + composite keys PostgreSQL (test_postgres_rls.py, test_stage08_persistence.py) | IMPLEMENTED |
| REQ-I18N-003 | variants/routes liés au groupe, aucune association implicite | test_same_guild_nested_children_cannot_cross_translation_group_boundary (application_postgres.py:277-382) | IMPLEMENTED |
| REQ-I18N-004 | `translation_channel_groups.id` stable ; `display_name` renommable via migration `0015_stage_08` | migration 0015 rename + isolation A/B (idem REQ-I18N-003) | IMPLEMENTED |
| REQ-I18N-005 | `ResourceLanguageResolver` SELF/CATEGORY/NONE, override explicite | resolver SELF/CATEGORY/NONE (unit test_stage08_translation_topology.py) | IMPLEMENTED |
| REQ-I18N-006 | liaison explicite de variants indépendante du parent category | link compatibility service.py:716-729 + FK group-scoped (0014_stage_08) | IMPLEMENTED |
| REQ-I18N-007 | `TranslationRouteCompiler` HUB/CUSTOM/FULL_MESH conditionné | route compiler unit tests (test_stage08_translation_topology.py) | IMPLEMENTED |
| REQ-I18N-008 | clone intégré au pipeline portable 06→05 | clone Stage06 reel (test_stage06_postgres.py, test_stage06_portability.py) | IMPLEMENTED |
| REQ-I18N-009 | `add_language_delta` transactionnel, sans recréation | delta atomique + rejet langue disabled (application_postgres.py:218-226) | IMPLEMENTED |
| REQ-I18N-010 | retrait de langue non destructif par défaut | unlink non destructif (application_postgres.py) | IMPLEMENTED |
| REQ-I18N-011 | `unlink_variant` retire uniquement l’association logique | detach_variant isolation logique (idem REQ-I18N-003) | IMPLEMENTED |
| REQ-I18N-012 | liaison manuelle confirmée et compatible | link explicite requis, pas d'inference nom (api/stage08.py) | IMPLEMENTED |
| REQ-I18N-013 | ActionRegistry exécute les intents réels | dispatcher.ts:96-141 + stage08.spec.ts:52,63,69 | IMPLEMENTED |
| REQ-I18N-014 | déclaration de langue séparée de la visibilité, défaut OPEN_ALL | policy OPEN_ALL par defaut (unit test_stage08_authoritative_planning.py) | IMPLEMENTED |
| REQ-I18N-015 | compiler OPEN_ALL/LANGUAGE_FILTERED/SCOPE_AND_LANGUAGE/CUSTOM explicite | create_visibility_plan 4 politiques (planning.py:86-155) | IMPLEMENTED |
| REQ-I18N-016 | aucune approximation Discord « rôle Scope + rôle Language = AND » | binding unique derive, jamais deux roles ANDes (planning.py:86-155) | IMPLEMENTED |
| REQ-I18N-017 | binding durable Visibility Scope × Language | VisibilityScopeLanguageRepository durable (stage08_repository.py:1563+) | IMPLEMENTED |
| REQ-I18N-018 | unicité/réutilisation du binding indépendante du Translation Group | reuse binding group-independant (test_stage05_postgres.py concurrence) | IMPLEMENTED |
| REQ-I18N-019 | rôle technique `permissions=0`, `hoist=false`, `mentionable=false` | hoist=False/mentionable=False/permissions=0 (planning.py:167-268) | IMPLEMENTED |
| REQ-I18N-020 | optimizer et capacité protègent les plans réels | budget role sur cache reel (planning.py:123) | IMPLEMENTED |
| REQ-I18N-021 | budget d’overwrites par salon | budget overwrite 1000/salon (planning.py:133) | IMPLEMENTED |
| REQ-I18N-022 | aucun member overwrite comme stratégie standard | aucun member overwrite (planning.py:330-419) | IMPLEMENTED |
| REQ-I18N-023 | intersection langues visibles × scopes réellement acquis | intersection langues x scopes acquis (planning.py:330-419) | IMPLEMENTED |
| REQ-I18N-024 | aucun rôle universel ALL_LANGUAGES | aucun role ALL_LANGUAGES (planning.py:86-155) | IMPLEMENTED |
| REQ-I18N-025 | port abstrait `TranslationProvider` et registry | TranslationProvider Protocol (translation_topology.py:58) | IMPLEMENTED |
| REQ-I18N-026 | capacités/health provider autoritatives | capacites derivees cache+PermissionEvaluator, jamais client (provider_orchestration.py:36-178) | IMPLEMENTED |
| REQ-I18N-026A | adapter bot existant non invasif ; mode manuel | PROVIDER_PENDING/APPLIED_WITH_PENDING_PROVIDER (migration 0019) + verify_manual_configuration | IMPLEMENTED |
| REQ-I18N-027 | topologie DID sans intent MESSAGE_CONTENT | validate_discord_live_stage08.py: intents.members seul, message_content=false | IMPLEMENTED |
| REQ-I18N-028 | `requires_message_content` appartient aux capacités provider | requires_message_content sur capacites provider (translation_topology.py:276) | IMPLEMENTED |
| REQ-I18N-029 | MISSING seulement sur preuve backend positive | MISSING sur preuve positive seulement (service.py:432,890) | IMPLEMENTED |
| REQ-I18N-030 | drift visible et réparation par plan | repair=PLAN_REQUIRED, aucune suppression auto (service.py:432) | IMPLEMENTED |
| REQ-I18N-031 | clone A→B avec nouveaux IDs et aucune liaison live | nouveaux logical_key destination, live_source_link=false (cloning/builder.py) | IMPLEMENTED |
| REQ-I18N-032 | aucun secret provider dans l’artifact | allowlist + blacklist recursive (portability/artifact.py:85-411) | IMPLEMENTED |
| REQ-I18N-033 | état provider partiel diagnostiquable, sans rollback destructif | APPLIED_WITH_PENDING_PROVIDER diagnosticable, pas de rollback auto (migration 0019) | IMPLEMENTED |
| REQ-I18N-034 | Translation Workspace complète et arborescente | workspace cache-first (service.py:903-918) + stage08.spec.ts:38 | IMPLEMENTED |
| REQ-I18N-035 | audit des mutations STAGE 08 | internal_audit_events (stage08_repository.py:1667) | IMPLEMENTED |
| REQ-I18N-036 | preflight présence/permissions effectives provider | access_preflight presence+permissions par variant (provider_orchestration.py:36-178) | IMPLEMENTED |
| REQ-I18N-037 | ADMINISTRATOR jamais recommandé, seulement signalé | PROVIDER_HAS_ADMINISTRATOR warning seulement (service.py:358-359) | IMPLEMENTED |
| REQ-I18N-038 | accès provider séparé des rôles humains | preflight provider separe des roles humains (provider_orchestration.py:36-178) | IMPLEMENTED |
| REQ-I18N-039 | choix de langue incapable d’accorder un scope métier | intersection langues x scopes deja acquis (planning.py:330-419) | IMPLEMENTED |
| REQ-I18N-040 | source ONBOARDING et réconciliation déterministe | source ONBOARDING + reconciliation deterministe (translation_topology.py) | IMPLEMENTED |
| REQ-I18N-041 | ensemble zéro/une/plusieurs langues, aucun primary | member_language_set_is_valid zero/un/plusieurs (translation_topology.py:372-377) + stage08.spec.ts:46 | IMPLEMENTED |
| REQ-I18N-042 | disable/retrait sans fallback silencieux | rejet disabled preserve l'ensemble existant (application_postgres.py:218-226) | IMPLEMENTED |

## Gates de candidate

- `python scripts/validate_stage.py 08` : PASS.
- `python scripts/validate_stage.py 08 --profile e2e` : PASS, 40 scénarios Playwright cumulés dont 8 propres à STAGE 08.
- `python scripts/validate_stage.py 08 --include-discord-live` : **PASS** sur deux Guilds sandbox réelles (`docs/90_handoffs/evidence/stage08/discord-live-stage08.json`, testé sur `592b94b`). Une première tentative avait révélé un défaut de code réel : les salons clonés à visibilité restreinte (Scope × Language / LANGUAGE_FILTERED) refusaient `VIEW_CHANNEL` (et donc `MANAGE_CHANNELS`) au bot control-plane sur la Guild destination dépourvue d'Administrator, ce qui bloquait fermé le preflight Stage05 de nettoyage `DELETE_CHANNEL`. Corrigé par `592b94b` (grant explicite du control-plane bot, jamais Administrator, jamais rôle métier humain). La re-qualification sur sandbox nettoyée confirme le PASS complet.
- Migration réversible `0013_stage_07 → 0014_stage_08 → … → 0021_stage_08 → 0013_stage_07 → head`, tête unique `0021_stage_08` : PASS.
- Secret scan, docs, Ruff, format, MyPy, frontend lint/typecheck/build/i18n/OpenAPI : PASS.
