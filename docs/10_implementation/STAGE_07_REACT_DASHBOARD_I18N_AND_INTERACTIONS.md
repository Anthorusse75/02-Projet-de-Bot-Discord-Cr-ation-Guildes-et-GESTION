# STAGE 07 — Dashboard React complet, i18n UI, UX avancée, menus et Drag & Drop

## A. Identité

| Champ | Valeur |
|---|---|
| Numéro / branche | `07` / `stage/07-dashboard` |
| Objectif | Livrer l’expérience d’administration cache-first accessible et intégralement localisée. |
| Résultat attendu | Application React complète pour les capacités 01–06, i18n EN/FR/DE/ES 100 %, ActionRegistry, menus, DnD/Right Drag et E2E. |
| Dépendances | 01–06 mergées ; contrats API/WS/permissions/plans/cloning stables. |
| Risque | Élevé : gestes ambigus, fuite cross-tenant dans state client et régression i18n/a11y. |

## B. Sources normatives

Spécifications §8–10, §17–24, §31–33, §39–40, §47, `REQ-STR-006..013`, `REQ-UX-*`, `REQ-UX-CTX-*`, `REQ-UI18N-*`. Architecture §19–22, §23.10, §49D, ADR-009/022/025/028/034, §65.9/71A/79.

## C. PRECHECK obligatoire

```bash
git status --short --branch
test "$(git branch --show-current)" = "main"
python scripts/validate_stage.py 06
npm.cmd --prefix frontend run typecheck
git log -1 --oneline
```

Lire handoff 06 et OpenAPI/contracts ; vérifier aucune mutation API directe hors plan, Snowflakes strings et events WS versionnés. Créer `stage/07-dashboard`. Refuser si l’ActionRegistry devrait contourner capabilities/authorization backend.

## D. Scope exact

Inclus : routing/session/tenant selection, query/server state, cache-first views, structure/roles/permissions/plans/audit/diagnostics/templates/library explorer, search/bulk, live progress, i18n runtime/catalog/locale packs, locale auto/override, typography/emoji/flags, global context menu, ActionRegistry, pointer gesture manager, left/right drag, multi-Guild drop, keyboard/a11y.

Exclus : fonctionnalités métier multilingues (08), Campaign Engine (09), écrans complémentaires finaux (10). L’UI peut fournir emplacements désactivés explicites seulement si non trompeurs et localisés.

Work packages : app/query shell ; design system/a11y ; i18n runtime ; core feature screens ; ActionRegistry/context ; pointer/DnD ; search/bulk/command palette ; Playwright/security/perf.

## E. Design d’implémentation détaillé

- Feature folders, typed API client generated/validated against OpenAPI, TanStack Query (ou choix consigné) for server state, minimal store for UI state. Query keys start user/Guild; tenant switch cancels/removes incompatible queries and closes WS.
- Snapshot REST local + incremental WS; gap/reconnect invalidates DID query only, jamais appel Discord direct. Optimistic UI uniquement pour état corrigible ; mutations de plan affichent job state until verified.
- Catalogue typed mandatory keys for navigation, actions, menus, toasts, tooltips, errors, ARIA, command palette and validation. No visible system literal outside allowlisted tests/dev data.
- Packs base EN/FR/DE/ES bundled complete and version-compatible. Runtime packs validated schema/catalog/params/no HTML, downloaded with integrity/cache, activated atomically only at 100 %. Missing/invalid override falls back to negotiated supported browser locale/bootstrap pack without mixed UI or raw key.
- Locale resolver uses `navigator.languages`/`Accept-Language`; nullable override `AUTOMATIC_BROWSER`; user can reset. Discord profile locale never default. Formatting via Intl and fonts Unicode; flags as reliable assets with accessible labels, emojis color support without assuming glyph.
- Backend errors expose code + params; frontend maps keys, never renders trusted HTML from pack. CSP compatible, interpolation escaped.
- `ActionRegistry` central definitions: resource types, selection/cardinality, source/destination Guild, required user capabilities, bot capabilities, risk, label/description/tooltip keys, execution command. Backend remains final authority.
- `GlobalContextMenuBoundary` prevents native `contextmenu` across dashboard and routes DID context or none. Right click no movement opens object menu; movement above pointer-type threshold enters Right Drag and opens Drop Context Menu on release; pointer capture/cancel/escape handled.
- Left drag same Guild proposes move/reorder plan; cross-Guild proposes copy/clone only. DropTargetResolver lists only compatible targets; all actions have keyboard/menu/dialog alternatives. No mutation on gesture alone before preview/confirmation contract.
- Accessibility : focus restoration, roving tabindex/tree semantics, screen reader announcements localisés, reduced motion, large targets. Search and command palette enforce tenant scope.
- Performance : virtualize large trees safely, memoized selectors, bundle budgets, no full reload, measurable interaction latency.

## F. Liste prévue de fichiers

`frontend/src/app/**`, `api/**`, `features/{auth,guilds,structure,permissions,plans,audit,diagnostics,templates,library,interaction,search}/**`, `localization/**`, base locale JSON/TS, design system, assets flags/fonts policy, Vitest/MSW/Playwright tests, i18n scanner/gate and CI updates.

## G. Stratégie de tests de l’étape

Unit/component : resolver, pack validation/atomic activation, all states, IDs, ActionRegistry filtering. Static gate 100 % keys/params and hardcoded strings. Pointer tests across mouse/touch/keyboard, threshold/cancel, native menu absent. API/MSW tenant switch and stale events. Playwright EN/FR/DE/ES critical flows, cross-Guild drag → clone preview, long plan progress and keyboard alternative. Security malicious locale content; a11y automated + manual matrix; performance large tree.

## H. Matrice de validation

| ID | Exigence | Test | Commande | Résultat attendu | Preuve |
|---|---|---|---|---|---|
| S07-STR / REQ-STR-006..013 | context/DnD semantics | component + Playwright | `python scripts/validate_stage.py 07` | right/left/inter-Guild rules exacts | videos/traces expurgés |
| S07-UX / REQ-UX-001..007, UX-CTX-001..005 | actions/a11y/progress | registry + E2E + axe | même commande | valid actions only, native menu absent | reports |
| S07-I18N / REQ-UI18N-001..021 | full UI localization | catalogue/runtime/security/E2E | même commande | 100 %, atomic, no raw key/mixed locale | coverage report |

## I. Commandes exactes de validation

```bash
docker compose -f compose.test.yaml up -d --wait
python scripts/validate_stage.py 07
python scripts/validate_stage.py 07 --profile e2e
docker compose -f compose.test.yaml down
```

Le validator appelle les scripts npm lockés réellement définis. Les captures E2E sont expurgées et ne contiennent pas de session/token.

## J. Tests Discord réels

Pas de mutation live spécifique supplémentaire : utiliser les sandboxes configurées via le backend pour un smoke E2E structure/plan/clone. Toute action reste contrôlée par les tests live des étapes 04–06 et crée des ressources préfixées nettoyées.

## K. Secrets / credentials nécessaires

| Nom | Obligatoire | Étape | Secret ? | Provenance | Stockage local | Stockage CI | Rotation |
|---|---:|---:|---:|---|---|---|---|
| Auth/session sandbox | smoke live seulement | 07 | oui | flux OAuth, jamais fixture | navigateur local sécurisé | environment E2E protégé | après test temporaire |
| Bot token | jamais frontend | 07 | oui | backend seulement | `.env.local` backend | backend environment | politique existante |

## L. Critères d’acceptation

Chaque écran critique fonctionne sans reload ; tenant switch ne laisse aucune donnée A en B ; aucune chaîne système non traduite ; quatre packs 100 % ; pack incomplet/HTML rejeté sans UI mixte ; native context menu absent ; clic droit et Right Drag distingués ; inter-Guild ne propose jamais move/delete source ; alternative clavier complète ; success only after accepted backend state.

## M. Definition of Done

UI/routes/features, i18n/a11y/perf/security, component/E2E, REQ/proofs, regressions 01–06, docs/handoff/state, commit/push/PR/merge.

## N. Handoff obligatoire

Créer `STAGE_07_HANDOFF.md` : route map, query keys/WS policy, catalogue version/coverage, pack security, ActionRegistry contract, gesture thresholds, E2E/a11y evidence and extension slots for 08–09.

## O. Prompt de démarrage d’un nouveau chat Codex

```text
Implémente uniquement STAGE 07 de Discord Infrastructure Designer.
Lis AGENTS.md, le contrat global, l’état courant et intégralement STAGE_07_REACT_DASHBOARD_I18N_AND_INTERACTIONS.md ; exécute le PRECHECK.
N’implémente aucune étape suivante. Exige 100 % i18n EN/FR/DE/ES, menus/Right Drag/DnD testés et alternatives clavier ; termine preuves, handoff, état/traçabilité, commit et PR.
```
