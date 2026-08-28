# Checklist locale STAGE 08 — REQ-I18N-001..042 + REQ-I18N-026A

## État de référence

- Statut global : `STAGE_08_IMPLEMENTATION_IN_PROGRESS`
- Base main : `252a4661195a3868acd04a2987453e23fc6ee4ff`
- Stage 09 : `FORBIDDEN`
- Règle de traceability : aucune exigence n’est `IMPLEMENTED` tant que code + test + preuve réelle ne sont pas présents.

## Matrice 43 IDs

| REQ ID | Comportement requis | Couche d’implémentation | Test nécessaire | État actuel réel |
|---|---|---|---|---|
| REQ-I18N-001 | langue, group et scope distincts | domain + schema | unit/db | PARTIAL |
| REQ-I18N-002 | `translation_group_id` unique par tenant | schema + repo | db + test | PARTIAL |
| REQ-I18N-003 | groupes identiques ne partagent jamais routes/variants implicites | domain + validation | unit/db | PARTIAL |
| REQ-I18N-004 | `Translation Channel Group` stable et indépendant du nom | domain + schema | unit/db | PARTIAL |
| REQ-I18N-005 | héritage catégorie/salon et override explicite | domain + resolver | unit | PARTIAL |
| REQ-I18N-006 | salons dans catégories différentes | domain + API | unit/application | NOT_STARTED |
| REQ-I18N-007 | topologies `HUB_AND_SPOKE` et `CUSTOM`; `FULL_MESH` conditionné provider | domain + provider | unit + plan | PARTIAL |
| REQ-I18N-008 | clone multilingue pipeline complet | application + clone | integration + plan | NOT_STARTED |
| REQ-I18N-009 | ajout de langue ne recrée pas les variantes valides | application + plan | unit/integration | NOT_STARTED |
| REQ-I18N-010 | retrait de langue ne supprime pas Discord sans confirmation | plan + API | integration | NOT_STARTED |
| REQ-I18N-011 | dissociation sans suppression Discord | application + API | integration | NOT_STARTED |
| REQ-I18N-012 | liaison automatique confirmable uniquement | application + plan | integration | NOT_STARTED |
| REQ-I18N-013 | Right Drag actions `CREATE_VARIANT`, `LINK_EXISTING_VARIANT`, `CLONE_UNLINKED`, `PREVIEW` | frontend + action registry | e2e + unit | NOT_STARTED |
| REQ-I18N-014 | déclaration de langue n’active pas la restriction de visibilité | domain + policy | unit | PARTIAL |
| REQ-I18N-015 | `OPEN_ALL`, `LANGUAGE_FILTERED`, `SCOPE_AND_LANGUAGE`, `CUSTOM` | visibility compiler | unit + API | PARTIAL |
| REQ-I18N-016 | jamais compiler `Scope + Language` comme `AND` implicite | visibility compiler | unit | NOT_STARTED |
| REQ-I18N-017 | rôle technique explicite `Scope × Language` | visibility compiler + role reconciler | unit + db | NOT_STARTED |
| REQ-I18N-018 | réutilisation des rôles techniques via binding durable | db + reconciler | postgres + plan | NOT_STARTED |
| REQ-I18N-019 | rôle technique DID sans permissions dangereuses | role compiler | unit + sandbox | NOT_STARTED |
| REQ-I18N-020 | budget de rôles avant création | optimizer + plan | unit + db | NOT_STARTED |
| REQ-I18N-021 | budget d’overwrites / blocage 1000 | optimizer + plan | unit + db | NOT_STARTED |
| REQ-I18N-022 | pas d’overwrites membre comme stratégie standard | visibility policy | unit | NOT_STARTED |
| REQ-I18N-023 | visible languages seulement dans scopes réellement joinables | member reconciliation | unit + db | NOT_STARTED |
| REQ-I18N-024 | aucun `ALL_LANGUAGES` bypass | member reconciliation | unit + security | NOT_STARTED |
| REQ-I18N-025 | abstraction `TranslationProvider` port | provider port | unit + interface | PARTIAL |
| REQ-I18N-026 | capacités provider connues/testées, adapter bot existant non invasif | provider adapter + preflight | unit + api | PARTIAL |
| REQ-I18N-026A | `MANUAL_CONFIGURATION_REQUIRED` sans API/modif bot externe | provider adapter + docs | unit + provider check | PARTIAL |
| REQ-I18N-027 | pas de `MESSAGE_CONTENT` requis pour la topologie | provider + gateway | unit | PARTIAL |
| REQ-I18N-028 | exigence `MESSAGE_CONTENT` est portée par le provider | provider contract | unit | NOT_STARTED |
| REQ-I18N-029 | variante supprimée = `MISSING` sans pertes | drift + reconcile | integration | NOT_STARTED |
| REQ-I18N-030 | drift visible et réparable sans propagation destructive | drift projector + plan | integration | NOT_STARTED |
| REQ-I18N-031 | clone A→B crée nouveau groupe indépendant | clone expansion + DB | integration | NOT_STARTED |
| REQ-I18N-032 | aucun secret provider dans artifact portable | clone artifact | unit + security | NOT_STARTED |
| REQ-I18N-033 | config provider partiellement appliquée diagnostiquable | provider lifecycle | integration | NOT_STARTED |
| REQ-I18N-034 | Translation Workspace arbre explicit | frontend + api | e2e | NOT_STARTED |
| REQ-I18N-035 | audit interne trace toutes modifications | audit + repository | integration | NOT_STARTED |
| REQ-I18N-036 | preflight provider sur présence/permissions | provider capability + plan | unit + live | NOT_STARTED |
| REQ-I18N-037 | pas de recommandation `ADMINISTRATOR` | provider policy | unit + security | NOT_STARTED |
| REQ-I18N-038 | rôles humains `LANG_*` / `Scope × Language` ne servent pas au bot provider | visibility policy | unit + plan | NOT_STARTED |
| REQ-I18N-039 | choix langue utilisateur ne donne pas de scope supplémentaire | member reconciliation | unit + policy | NOT_STARTED |
| REQ-I18N-040 | onboarding bridge + réconciliation des rôles techniques | onboarding + reconciliation | integration | NOT_STARTED |
| REQ-I18N-041 | aucun `primary` obligatoire pour langue visible | member model | unit + db | PARTIAL |
| REQ-I18N-042 | disable/suppression ne choisit pas de fallback implicite | member reconciliation | unit + db | PARTIAL |

## Notes de travail

- Les IDs marquées `PARTIAL` ne sont pas encore considérées comme `IMPLEMENTED`.
- Les IDs `NOT_STARTED` doivent être traitées comme des travaux ouverts, sans autoconsommation ni documentation trompeuse.
- L’implémentation ne doit pas avancer vers Stage 09.
