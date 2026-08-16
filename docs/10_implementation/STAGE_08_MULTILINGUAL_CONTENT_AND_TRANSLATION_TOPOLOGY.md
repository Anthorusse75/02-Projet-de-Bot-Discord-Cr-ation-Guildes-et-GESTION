# STAGE 08 — Multilingual Content & Translation Topology

## A. Identité

| Champ | Valeur |
|---|---|
| Numéro / branche | `08` / `stage/08-multilingual-topology` |
| Objectif | Modéliser langues, topologies et visibilité sans confondre identité, audience ou provider. |
| Résultat attendu | Profiles, Groups/variants/routes, policies, Scope × Language, workspace, clone multilingue et provider non invasif. |
| Dépendances | 01–07 mergées ; scopes, plans, clone pipeline et UI i18n disponibles. |
| Risque | Critique : fuites de visibilité, explosion de rôles/overwrites, liaisons implicites et bot externe. |

## B. Sources normatives

Spécifications §3.6–3.9, §26A, §40 (séparation UI/content), `REQ-I18N-*`. Architecture §7.17–7.27, §15.2, §35.3–35.5, §49B, ADR-011–015/020/024, §65.8/71.

## C. PRECHECK obligatoire

```bash
git status --short --branch
test "$(git branch --show-current)" = "main"
python scripts/validate_stage.py 07
python -m alembic current
git log -1 --oneline
```

Lire handoff 07, vérifier Visibility Scope resolver, role/overwrite capability budgets, clone extensions and i18n action keys. Créer `stage/08-multilingual-topology`. Refuser si une langue est utilisée comme identity de Translation Group ou si provider secret devrait entrer dans artifact.

## D. Scope exact

Inclus : Language Profiles, member visible language set sans primary, resource inheritance/override, Translation Groups/Category/Channel Groups/variants/routes, topologies HUB_AND_SPOKE/FULL_MESH/CUSTOM, manual link/unlink/add/remove language, drift/reconcile plans, visibility policies, Scope × Language compiler/lazy roles/budget optimizer, onboarding bridge, TranslationProvider port/registry/binding, adapter existing bot non invasif, manual configuration state, multilingual clone and workspace/right-drag targets.

Exclus : traduction DID de campagnes/messages avec googletrans (09), modification obligatoire du bot externe, production operations.

Work packages : schema/domain ; language policy/inheritance ; topology/routes ; visibility compiler/budget ; provider abstraction ; lifecycle/drift ; clone expansion ; API/UI/workspace ; sandbox/security.

## E. Design d’implémentation détaillé

- Tables from architecture: `language_profiles`, `member_visible_languages` (set, no primary), `resource_language_policies`, `translation_groups`, category/channel variants/groups, routes, provider bindings, optional message links, `visibility_scope_language_roles`. Every topology entity tenant-scoped with composite FK and stable IDs independent of names/language.
- Language inheritance resolver outputs explicit effective source (`SELF`, `CATEGORY`, `NONE`); deleting/disabling a language never silently picks another primary. A channel override can differ in same category.
- Translation Group contains independent identity, topology and route graph. Same language pair in two groups shares nothing implicitly. Linking existing resources is manual/confirmed with compatibility checks; no name/language inference.
- Route validator handles HUB_AND_SPOKE/FULL_MESH/CUSTOM, loops, missing variants, source ownership and provider capabilities. Structural plan phases order categories→channels→roles/overwrites→provider config.
- Visibility policies OPEN_ALL/LANGUAGE_FILTERED/SCOPE_AND_LANGUAGE/CUSTOM compile through existing scopes. Discord roles do not express AND: bind unique Guild/Scope/Language role, created lazy and reusable across groups. Reconciler assigns member intersections and cleans only provably unused technical roles.
- Budget preflight calculates Guild roles, channel overwrites and provider access; optimizer explains reuse/alternatives and blocks overflow. No `TranslationGroup × Language` role unless documented exception proves scope cannot be shared.
- TranslationProvider port exposes capability discovery/config/health without secret serialization. Existing bot adapter uses safe documented interface if present; otherwise state `MANUAL_CONFIGURATION_REQUIRED` with exact instructions and verification, never fake configured. DID does not require MESSAGE_CONTENT merely for topology.
- Provider access compiler grants minimum visible/source/destination permissions consistent with human visibility; provider absent/degraded does not corrupt topology state.
- Multilingual clone creates all new Group IDs in B, maps scopes/languages/resources explicitly, omits provider secrets/bindings unless destination mapping confirmed, and uses pipeline 06 → plan 05.
- Gateway detects structural drift, not cross-tenant translation. UI Translation Workspace/tree badges/right drag language target all use ActionRegistry and localized keys.
- Concurrency/idempotence : unique variant/route constraints, CAS group version, reconciler plan idempotency, manual config transitions audited.

## F. Liste prévue de fichiers

Migrations multilingual tables, `did/languages/**`, `did/translation_topology/**`, visibility compiler/role reconciler, provider port/registry/adapters, clone expander, drift projectors, APIs, frontend Translation Workspace/actions, tests topology/property/budget/A-B/provider/sandbox.

## G. Stratégie de tests de l’étape

Unit/property : inheritance, route graphs, independent identical language groups, no primary fallback, role uniqueness/reuse and budgets. DB RLS/composite FK A/B. Plan integration add/remove/link/unlink/drift. Provider contract supported/unsupported/absent/manual, no token sharing. Clone A→B new IDs/no secrets. Sandbox validate roles/overwrites visibility for multiple languages/scopes and provider access if safely available. UI E2E workspace/right drag/accessibility/localization.

## H. Matrice de validation

| ID | Exigence | Test | Commande | Résultat attendu | Preuve |
|---|---|---|---|---|---|
| S08-I18N / REQ-I18N-001..042 | domain/topology/visibility/provider | unit+DB+plan+UI+live | `python scripts/validate_stage.py 08` | identities separated, visibility exact, fail safe | JUnit/plan/live |
| S08-TEN | group/provider isolation | A/B RLS/IDOR | même commande | no implicit cross-Guild links/routes | security report |
| S08-CAP | role/overwrite budget | boundary/property | même commande | lazy reuse or preflight block | benchmark/report |

## I. Commandes exactes de validation

```bash
docker compose -f compose.test.yaml up -d --wait
python scripts/validate_stage.py 08
python scripts/validate_stage.py 08 --profile e2e
python scripts/validate_stage.py 08 --include-discord-live
docker compose -f compose.test.yaml down
```

## J. Tests Discord réels

Guild A : scopes Alpha/Beta, languages FR/EN/DE/ES subsets, categories/channels inheritance and two independent groups sharing same languages. Verify member with multiple languages, no language, view-all, provider present/absent and budget. Guild B : multilingual clone yields new IDs and no route to A. Cleanup through plans; preserve evidence without member PII.

## K. Secrets / credentials nécessaires

| Nom | Obligatoire | Étape | Secret ? | Provenance | Stockage local | Stockage CI | Rotation |
|---|---:|---:|---:|---|---|---|---|
| Bot token + Guild A/B | live | 08 | token oui | Portal/sandbox | `.env.local` | protected environment | sandbox policy |
| Translation provider credential | seulement si safe interface l’exige | 08 | oui | provider owner | `.env.local`/secret store | protected environment | provider policy |

Ne jamais demander le token du bot externe si une intégration documentée/configuration manuelle suffit ; ne jamais partager le token DID.

## L. Critères d’acceptation

Deux groups FR/EN restent indépendants ; no primary language fallback ; inheritance/override exact ; Scope AND Language invisible sans both memberships ; technical roles lazy/reused and budget-blocked; absent unsupported provider = manual required; no secret in artifact; clone B new IDs; UI actions localized and only valid targets.

## M. Definition of Done

Migrations/domain/compiler/provider/UI, budgets/security/A-B/live, all assigned REQ proofs, regressions 01–07, docs/handoff/state, commit/push/PR/merge.

## N. Handoff obligatoire

Créer `STAGE_08_HANDOFF.md` avec schemas/invariants, topology/provider capability matrix, role budget results, manual configuration states, clone mappings, sandbox visibility and contracts for Campaign Engine.

## O. Prompt de démarrage d’un nouveau chat Codex

```text
Implémente uniquement STAGE 08 de Discord Infrastructure Designer.
Lis AGENTS.md, le contrat global, l’état courant et intégralement STAGE_08_MULTILINGUAL_CONTENT_AND_TRANSLATION_TOPOLOGY.md ; exécute le PRECHECK.
N’implémente aucune étape suivante. Ne confonds jamais langue, Translation Group et Visibility Scope ; n’impose aucune modification du bot externe. Termine tests/budgets/live, preuves, handoff, état/traçabilité, commit et PR.
```
