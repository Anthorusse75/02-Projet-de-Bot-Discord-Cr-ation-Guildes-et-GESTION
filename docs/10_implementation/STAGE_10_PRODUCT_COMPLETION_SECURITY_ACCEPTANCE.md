# STAGE 10 — Complétion produit, intégration globale, sécurité, performance et acceptance closure

## A. Identité

| Champ | Valeur |
|---|---|
| Numéro / branche | `10` / `stage/10-acceptance` |
| Objectif | Livrer le Release Candidate technique complet et fermer chaque exigence obligatoire avec preuve. |
| Résultat attendu | Toutes fonctions sources présentes, migrations finales, hardening, E2E/pannes/charge/sandboxes verts, aucun MUST sans preuve. |
| Dépendances | 01–09 mergées avec handoffs et traçabilité actualisée. |
| Risque | Critique : scope gaps masqués, régressions transverses et fausse acceptation. |

## B. Sources normatives

Lire intégralement les deux sources, avec focus spécifications §5, §12, §21–26, §29–37, §39–49 et tout registre §53 ; architecture §34–46, §50–66, §70–80. Exigences principales : `REQ-BOT-004..006`, `REQ-DATA-*`, `REQ-TEST-*`; secondaires : **tous les `REQ-*`**. Tous ADR-001..035 et décisions IMP ouvertes.

## C. PRECHECK obligatoire

```bash
git status --short --branch
test "$(git branch --show-current)" = "main"
for stage in 01 02 03 04 05 06 07 08 09; do python scripts/validate_stage.py "$stage"; done
python scripts/validate_documentation.py
python -m alembic current
git log -1 --oneline
```

Lire les neuf handoffs, exporter la liste des exigences non `VERIFIED`, des TODO/FIXME/skips/xfailed, décisions ouvertes, migrations et incidents connus. Créer `stage/10-acceptance` seulement si les baselines sont vertes. Un live test non exécuté requis n’est pas un PASS et doit être planifié ici.

## D. Scope exact

Inclus : gap analysis source→code ; fonctions restantes (onboarding Discord, membres, bots, webhooks, synchronisation par modèle, commandes Discord localisées, snapshots/versioning, audit/diagnostics/recherche et fonctions complémentaires obligatoires) ; migrations finales ; hardening ; privacy/purge ; observabilité ; performance/cache/rate-limit ; global E2E ; failure/chaos ; two-Guild acceptance ; traceability closure ; release manifest/SBOM/images candidate.

Exclus : choix/déploiement production, DNS/TLS/reverse proxy et opérations réelles (11). Aucun ajout opportuniste hors sources sans décision.

Work packages : (1) inventory/gap map ; (2) remaining product features ; (3) migration/data lifecycle ; (4) security/tenant audit ; (5) performance/governor/scale ; (6) global E2E/failure/live ; (7) traceability/audit docs ; (8) RC packaging and handoff.

## E. Design d’implémentation détaillé

- Générer inventaire machine-readable des routes, use cases, tables/RLS, jobs, streams/keys, UI routes/actions/keys et map aux REQ. Chaque gap devient work item lié, jamais TODO caché.
- Onboarding : vérifier capabilities réelles et ne pas simuler fonctions Discord non supportées. Members dépend explicitement de `GUILD_MEMBERS` ou mode dégradé ciblé ; aucune dépendance MESSAGE_CONTENT structurelle.
- Bots : inventory/cache, fiche permissions, over-permission audit, where read/write and real overwrite compiler; ADMINISTRATOR signalé, jamais auto-demandé.
- Webhooks : inventory metadata/permissions and secret-safe handling; tokens/URLs jamais front/log/export. Synchronisation par modèle passe DSG/plan/stale/impact, pas mutation parallèle.
- Application commands : slash/user/message only when source demands and capability supports; localization and permission checks; interaction handlers use application layer and tenant context.
- Snapshots/audit/search/diagnostics are tenant-safe, cache-first, paginated and do not collect message content generally. Tenant delete policy orchestrates revoke, jobs, RLS data purge, user artifacts per ownership policy, cache/Redis/tombstones and auditable retention.
- Migrations upgrade from every supported prior stage state, constraints validated, rollback only where honest. Seed never fakes Discord resources.
- Security audit : OAuth/session/CSRF/SSRF/CSP/CORS, IDOR endpoint-by-endpoint, RLS policies, pool context, Redis/WS/jobs, supply chain, locale/artifact/parser inputs, secrets/log redaction, backups assumptions documented but not deployed.
- Performance : representative 500 channels/250 roles/overwrite boundary fixtures, large tree/UI, plan/clone/campaign load, reconcile pressure and multi-Guild fairness. No hardcoded Discord mutable limits outside capabilities registry; revalidate official docs.
- Failure matrix : DB/Redis/provider/Discord timeouts, 429, reconnect, worker crash windows, duplicate/out-of-order events, partial apply, restore of queues. Recovery preserves audit and no duplicate external action.
- Global Playwright spans login→tenant→read→permission→plan/apply→clone→languages→campaign, EN/FR/DE/ES, keyboard and errors. Sandbox A/B verifies critical semantic behaviors and cleanup.
- Traceability checker requires source IDs exactly once and each MUST/SHOULD disposition: VERIFIED proof or SHOULD deviation with rationale. MUST cannot be waived silently. `REQ-TEST-*` validate the validation system itself.
- RC artifacts pin versions, generate SBOM/checksums, scan dependencies/images and record immutable Git tag candidate (tag only after gates). No production secrets/config assumptions.

## F. Liste prévue de fichiers

Modules/migrations for remaining features based on gap inventory, API/UI/tests, `scripts/audit_requirements.py`, acceptance suites, performance/failure harness, `docs/acceptance/` concise reports if justified, RC manifest/SBOM workflow and updates to every traceability/handoff/state document. Exact list must be derived from repository at PRECHECK.

## G. Stratégie de tests de l’étape

Run every previous suite plus new unit/integration/DB/Redis/API/frontend/E2E. Endpoint-by-endpoint A/B matrix, RLS role audit and WS/cache/queue isolation. Migration from staged snapshots. Load and 429/fairness. Failure injection across external-success windows. Real Discord A/B for permissions, lifecycle, clone, topology and campaigns. Manual accessibility/security review with evidence. Scan for skips/xfailed/TODO/secrets/dependencies. Validate every REQ proof resolves to current commit/run.

## H. Matrice de validation

| ID | Exigence | Test | Commande | Résultat attendu | Preuve |
|---|---|---|---|---|---|
| S10-ALL / all REQ-* | full traceability | requirement audit + all stage validators | `python scripts/validate_stage.py 10` | every MUST verified exactly once | closure report |
| S10-BOT / REQ-BOT-004..006 | bot audit/overwrites | unit+cache+live | même commande | real access and over-permission diagnosis | live report |
| S10-DATA / REQ-DATA-001..002 | minimization/purge | privacy + purge integration | même commande | no general content collection, documented deletion | evidence |
| S10-TEST / REQ-TEST-001..005 | test obligations | meta-tests + CI/live | même commande | unit/integration/A-B/sandbox/failure all present | test inventory |
| S10-SEC | tenant/security global | A/B endpoint/RLS/Redis/WS | même commande | zero cross-tenant access/leak | security report |
| S10-RC | release candidate | build/SBOM/scan/smoke | même commande | reproducible clean RC, no production deploy | checksums/reports |

## I. Commandes exactes de validation

```bash
docker compose -f compose.test.yaml up -d --wait
python scripts/validate_stage.py 10
python scripts/validate_stage.py 10 --profile security
python scripts/validate_stage.py 10 --profile performance
python scripts/validate_stage.py 10 --profile failure-injection
python scripts/validate_stage.py 10 --profile e2e
python scripts/validate_stage.py 10 --include-discord-live
python scripts/validate_documentation.py
docker compose -f compose.test.yaml down
git diff --check
```

Le validator 10 doit appeler les validations antérieures pertinentes sur le même commit, pas se contenter de leurs anciens résultats.

## J. Tests Discord réels

Deux Guilds obligatoires. Exécuter toute la matrice sandbox avec état initial inventorié, identifiants expurgés, permissions minimales and cleanup verified. Revalider official docs/date for Channel Obfuscation and any limits/intents. Toute sémantique critique non testable est un blocker ou une limitation explicitement acceptée par le propriétaire, jamais VERIFIED.

## K. Secrets / credentials nécessaires

| Nom | Obligatoire | Étape | Secret ? | Provenance | Stockage local | Stockage CI | Rotation |
|---|---:|---:|---:|---|---|---|---|
| Discord OAuth/bot/Guild A/B | oui live | 10 | tokens oui | Portal/sandboxes | `.env.local` | protected environment | après validation temporaire |
| crypto/session/artifact/provider keys | selon subsystems | 10 | oui | prior handoffs | secret store | protected environment | verify version/rotation |
| production credentials | non | 10 | — | — | — | — | STAGE 11 uniquement |

## L. Critères d’acceptation

Chaque MUST a test/commande/preuve/commit current ; no blocking TODO/skip/xfailed; all migrations from supported bases; all stage validators green; A/B live clean; endpoint isolation proves zero forbidden repository calls; failure tests no duplicate external actions; performance budgets documented/met; four locales complete; secret/vulnerability gates dispositioned; reproducible RC built but not deployed.

## M. Definition of Done

Produit complet selon sources, migrations, tests/lint/type/security/perf/live, matrix entirely closed, no regression/debt hidden, handoff/state/docs, clean commit, pushed PR reviewed/merged, RC tag/checksums only after green gates.

## N. Handoff obligatoire

Créer `STAGE_10_HANDOFF.md` particulièrement exhaustif : RC SHA/tag, actual topology/processes, containers/Dockerfiles, migration chain, env var inventory names, CI, SBOM/scans, every command/run, A/B state/cleanup, known non-blocking limits and exact evidence required to rewrite STAGE 11.

## O. Prompt de démarrage d’un nouveau chat Codex

```text
Implémente uniquement STAGE 10 de Discord Infrastructure Designer.
Lis AGENTS.md, le contrat global, l’état courant, tous les handoffs 01–09 et intégralement STAGE_10_PRODUCT_COMPLETION_SECURITY_ACCEPTANCE.md ; exécute le PRECHECK et relis les deux sources.
N’effectue aucun déploiement production. Ferme chaque REQ obligatoire par une preuve actuelle, exécute sécurité/performance/pannes/E2E/deux Guilds, produis le RC, handoff, état/traçabilité, commit et PR. Ne masque aucun gap ou test non exécuté.
```
