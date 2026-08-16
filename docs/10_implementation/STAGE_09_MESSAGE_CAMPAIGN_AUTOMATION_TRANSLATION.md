# STAGE 09 — Message & Campaign Engine, automatisations et traduction sûre

## A. Identité

| Champ | Valeur |
|---|---|
| Numéro / branche | `09` / `stage/09-campaigns` |
| Objectif | Publier et automatiser des messages mono/multi-Guild sans boucle, doublon ni corruption technique. |
| Résultat attendu | Campagnes durables, scheduler/triggers, deliveries idempotentes, parser Discord-safe et traduction réelle benchmarkée/fail-closed. |
| Dépendances | 01–08 mergées ; Control Plane, worker/governor, plans/topologies et UI i18n stables. |
| Risque | Critique : spam, cross-tenant trigger, double publication/traduction et altération mentions/URLs/code. |

## B. Sources normatives

Spécifications §34, `REQ-MSG-*`, §38, §42–43. Architecture §3.7A, §7.32–7.39, §35, §49C, ADR-014/020/026–027/030–031/033, §65.10/71/75–77. `googletrans` reste un adapter non officiel/instable selon §67.

## C. PRECHECK obligatoire

```bash
git status --short --branch
test "$(git branch --show-current)" = "main"
python scripts/validate_stage.py 08
python -m alembic current
git log -1 --oneline
```

Lire handoff 08 ; vérifier provider ownership/double-translation contract, target authorization, Workload Governor priorities and correlation/causation event envelope. Créer `stage/09-campaigns`. Refuser si un event trigger ne peut pas être lié à des sources Guild explicites.

## D. Scope exact

Inclus : text/embed/component message model, campaign header Control Plane, Guild targets, target resolver, immediate/one-shot/RRULE+IANA recurring, explicit event triggers/conditions, occurrences/deliveries, causality loop guard, idempotency, allowed mentions, safe edits/deletes, parser/protector/fingerprint, glossary priority, googletrans adapter, empirical corpus/benchmark, integrity validator, preview/approved variants, Translation Channel Groups and double-translation protection, UI.

Exclus : unrelated product completion (10), production runbook (11).

Work packages : schema/model ; targets/auth ; scheduler ; triggers/causality ; delivery worker ; safe parser/mentions ; translation/glossary/benchmark ; preview/variants/UI ; load/failure/live.

## E. Design d’implémentation détaillé

- Tables exactly scoped: `message_campaigns` user-owned header, targets/schedules/triggers/sources, `message_occurrences`, tenant-scoped `message_deliveries`, glossaries and approved variants. Composite FK/RLS and unique idempotency keys; targets snapshot authorization at execution, not forever.
- Target resolver expands Guild/channel/logical group/Translation Group/language only after per-Guild authorization and bot capability; parent job never calls Discord, child delivery carries `guild_id`.
- Scheduler stores RRULE, IANA timezone, next fire, misfire policy, DST ambiguity choice and last cursor. Claims atomically, occurrence key deterministic; restart/catch-up bounded. One-shot/edit/cancel races use version/CAS.
- Trigger has explicit source bindings Guild/scope and condition AST allowlist. Event carries `event_id`, correlation_id, causation_id, origin, depth; unique trigger/event consumption, max depth and ancestor loop checks before occurrence. Campaign-sent events marked to prevent provider/DID double reactions.
- Delivery key derives occurrence/target/variant; state machine claimed/sending/sent/failed/unknown. Discord message ID persisted. Crash after send before commit reconciles via nonce/audit/known link when possible; ambiguous duplicate publication requires intervention, never blind send.
- `AllowedMentionsCompiler` defaults none, allowlists explicit users/roles/everyone only with capability and preview. Every create/edit supplies it. Safe edit verifies campaign ownership/message link and destination.
- `MessageModel` structured text/embeds/components. `DiscordSafeMessageParser` builds AST nodes TEXT/PROTECTED for URLs, user/role/channel mentions, timestamps, custom emoji, code blocks/inline code, commands, variables and Markdown boundaries.
- Protector replaces technical nodes with collision-resistant placeholders and fingerprints type/order/value; restores only exact set. Validator reparses output, compares fingerprints/structure/limits/allowed mentions and fails closed.
- TranslationContextBuilder preserves maximum context with placeholders. Benchmark real `googletrans` strategies: full masked message, paragraph/block groups, sentence-aware groups—not naive each TEXT node. Corpus FR/EN/DE/ES committed without private content; record dependency/version/date, latency/error, protected integrity and human semantic review rubric. Select via documented evidence.
- Glossaries have deterministic priority (campaign > Guild > global user or exact source order decided), longest/specific match and protected substitution; grammar override never raw replace after translation. Provider timeouts/circuit breaker/retry bounded; approved variants can bypass unstable live translation only when source fingerprint matches.
- Translation Channel Group publish coordinates with external bot ownership: DID-translated destination marked/route excluded according safe contract; otherwise manual config/block. No cross-tenant live translation implicit.
- Governor integrates campaign priority/backpressure and per-Guild fairness; bulk campaign exposes simulation/impact. Metrics exclude content and high-cardinality IDs.

## F. Liste prévue de fichiers

Migrations campaigns/deliveries/glossaries, `did/campaigns/**`, `did/messaging/**`, `did/translation/**`, scheduler/trigger/delivery workers, target resolver, googletrans adapter/circuit breaker, corpus/benchmark runner/reports, APIs/events, frontend campaign editor/preview/history, fuzz/property/load/live tests.

## G. Stratégie de tests de l’étape

Unit/property/fuzz parser and placeholder integrity; glossary priority; RRULE/DST/misfire; causality graphs/cycles; target auth. DB concurrency for claims/idempotency and A/B RLS. Failure injection crash after send, scheduler restart, provider timeouts/corruption. Real empirical corpus calls for each strategy/lang direction with human-scored sample; no mocked quality claim. Load multi-Guild fairness/backpressure. Sandbox safe mentions, immediate/scheduled/edit/retry, Translation Group publish, external bot no double translation. UI Playwright localized preview and errors.

## H. Matrice de validation

| ID | Exigence | Test | Commande | Résultat attendu | Preuve |
|---|---|---|---|---|---|
| S09-MSG / REQ-MSG-001..031 | campaigns/safety/translation | DB+scheduler+fuzz+corpus+live | `python scripts/validate_stage.py 09` | one delivery, safe technical tokens, real measured quality | JUnit/benchmark/live |
| S09-TEN | multi-Guild fan-out | A/B authorization/instrumentation | même commande | each child scoped, no inferred access | security report |
| S09-RATE | workload fairness | load/429/backpressure | même commande | campaigns cannot starve apply/reconcile bounds | benchmark |

## I. Commandes exactes de validation

```bash
docker compose -f compose.test.yaml up -d --wait
python scripts/validate_stage.py 09
python scripts/validate_stage.py 09 --profile translation-benchmark --allow-network
python scripts/validate_stage.py 09 --profile failure-injection
python scripts/validate_stage.py 09 --include-discord-live
docker compose -f compose.test.yaml down
```

Network benchmark records real result or fails/marks unverified; it never substitutes fixtures for linguistic proof.

## J. Tests Discord réels

A/B : targets with distinct rights, immediate and scheduled deliveries, retry/restart, allowed mentions none/explicit, edit/delete owned message, four language variants, external translation bot present/absent. Verify exactly one message per delivery and no double translation. Use test-only roles/users, no `@everyone` ping in live environment, cleanup messages/campaigns.

## K. Secrets / credentials nécessaires

| Nom | Obligatoire | Étape | Secret ? | Provenance | Stockage local | Stockage CI | Rotation |
|---|---:|---:|---:|---|---|---|---|
| Bot token + Guild A/B | live | 09 | token oui | Portal/sandbox | `.env.local` | protected environment | sandbox policy |
| googletrans/provider credential | adapter-dependent | 09 | à confirmer | actual provider | secret store only if needed | protected environment | provider policy |

Ne pas inventer ni demander une API key si la bibliothèque réelle n’en utilise pas ; revalider au lockfile. Aucun contenu privé dans corpus.

## L. Critères d’acceptation

RRULE/DST deterministic; event from unbound B cannot trigger A; loop/depth blocked; normal retry sends once; every edit has allowed_mentions; parser roundtrip preserves protected nodes; corruption blocks publish; glossary order deterministic; chosen segmentation backed by real corpus FR/EN/DE/ES; cross-Guild requires each auth; no double translation with external provider.

## M. Definition of Done

Migrations/engine/UI, fuzz/failure/load/real corpus/live, all REQ proofs, regressions 01–08, docs/handoff/state, commit/push/PR/merge.

## N. Handoff obligatoire

Créer `STAGE_09_HANDOFF.md` avec schemas/state machines, RRULE/misfire, causality, idempotency/recovery, parser grammar/fingerprints, exact benchmark/version/results, provider/double-translation contract, sandbox and remaining acceptance gaps.

## O. Prompt de démarrage d’un nouveau chat Codex

```text
Implémente uniquement STAGE 09 de Discord Infrastructure Designer.
Lis AGENTS.md, le contrat global, l’état courant et intégralement STAGE_09_MESSAGE_CAMPAIGN_AUTOMATION_TRANSLATION.md ; exécute le PRECHECK.
N’implémente aucune étape suivante. Mesure réellement googletrans sur le corpus FR/EN/DE/ES, protège chaque token technique et échoue fermé. Termine tests de panne/charge/live, preuves, handoff, état/traçabilité, commit et PR.
```
