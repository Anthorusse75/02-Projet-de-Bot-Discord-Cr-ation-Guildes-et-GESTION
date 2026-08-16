# STAGE 02 — OAuth2 Discord, sessions, tenancy, Control Plane, RBAC et installation Guild

## A. Identité

| Champ | Valeur |
|---|---|
| Numéro / branche | `02` / `stage/02-auth-tenancy` |
| Objectif | Établir identité utilisateur, sessions sûres, autorisation tenant et cycle d’installation/bootstrap. |
| Résultat attendu | Login Discord officiel et sessions opaques, Guild selector autorisé, RLS data/control planes, RBAC/capabilities et installation testables. |
| Dépendances | STAGE 01 mergée, migration head et baseline verte. |
| Risque | Critique : auth, IDOR, confused deputy et chiffrement de tokens. |

## B. Sources normatives

Spécifications §2.2, §5–7, §41–43, registre `REQ-INST-*`, `REQ-TEN-001..010`, `REQ-AUTH-*`, `REQ-BOT-001..003,007`. Architecture §6–9, §19–20, §26–27, §35, §44, §60, §63, §69 ADR-001/006/008/019/029/032/035, §71/74.

## C. PRECHECK obligatoire

```bash
git status --short --branch
test "$(git branch --show-current)" = "main"
python scripts/validate_stage.py 01
docker compose -f compose.test.yaml up -d --wait
python -m alembic current
git log -1 --oneline
```

Confirmer le handoff 01, le SHA `main`, la migration attendue, RLS/pool tests verts et aucun secret tracké. Créer `stage/02-auth-tenancy`. Les credentials Discord ne sont demandés qu’avant le premier test live, jamais pour les tests contractuels.

## D. Scope exact

Inclus : Authorization Code Grant `identify guilds`, state one-shot, callback backend, grants/token refresh chiffrés, sessions Redis opaques, CSRF, logout/revoke séparés, users/preferences, tenant context, Control Plane owner context, `guild_installations`, `guild_user_access`, role bindings, capabilities, Guild discovery freshness, install/bootstrap/uninstall state machine, targeted member lookup policy et cross-tenant guards.

Exclus : Gateway runtime complet/cache structure (03), permission evaluator Discord complet (04), plans/mutations (05), UI riche (07).

Work packages : schema/RLS ; crypto/key versioning ; OAuth/session/CSRF ; tenancy repositories ; RBAC/capability resolver ; installation/bootstrap ; API/contracts ; sandbox ; hardening/handoff.

## E. Design d’implémentation détaillé

- Tables : `users`, `discord_oauth_grants` (ciphertext, nonce/metadata, key_version, scopes, expiry, revoked_at), `user_ui_preferences`, `guild_installations` (guild_id unique, status, bot/app identity, timestamps), `guild_user_access`, `guild_role_bindings`, session/state stores Redis. FK/unique composites empêchent associations cross-Guild ; RLS distincte pour `guild_id` et `owner_discord_user_id`.
- OAuth service construit allowlisted redirect URI, nonce CSPRNG hashé/TTL/single-use, échange code backend, scope exact et refresh rotation-safe. Ne jamais renvoyer tokens au navigateur.
- Cookie contient un ID opaque aléatoire, rotation après auth, Secure en production, HttpOnly, politique SameSite documentée. CSRF synchronizer/double-submit choisi explicitement et testé indépendamment du state OAuth.
- `TenantContext` n’est créé qu’après session + membership/capability ; switch Guild revalide. Authorization avant repository lorsqu’une fuite d’existence est possible.
- Guild discovery `/users/@me/guilds` est un cache borné, pas une ACL éternelle. Les bindings de rôle utilisent cache membre frais puis `Get Guild Member` ciblé ; aucun full member list pour login/action.
- Bootstrap : installation Gateway/REST détectée `PENDING_SETUP`; seul owner ou `ADMINISTRATOR` initialise ; ensuite délégations RBAC. Uninstall invalide toute mutation et réinstall n’associe aucun autre tenant.
- API versionnée : auth start/callback/logout/revoke, `/me`, guild discovery, select tenant, installation/bootstrap/RBAC. Snowflakes en chaînes, erreurs localisables, aucune mutation structurelle Discord.
- Audit auth/authorization sans token ; métriques login, refresh, deny, state reuse, CSRF et targeted lookup. Concurrence : refresh grant lock/version optimiste, session revoke atomique, bootstrap idempotent.

## F. Liste prévue de fichiers

`did/oauth/**`, `did/tenancy/**`, `did/application/auth/**`, `did/application/installations/**`, modèles/repositories/migrations, routers `auth`, `me`, `guilds`, middleware session/CSRF/tenant, adapters Discord OAuth/member lookup, tests auth/RLS/IDOR, fixtures OAuth contract et extensions du validator.

## G. Stratégie de tests de l’étape

Unit : state, cookie policy, scopes, crypto envelope, capability decisions. DB/RLS : A/B, owner Control Plane, FK composites, pool reuse. Redis : session TTL/rotation/revoke/state replay. API : callback mismatch/expiry/replay, CSRF, switch Guild, IDOR et zéro repository B. Contract : OAuth token/refresh errors. Live : login, owner/admin bootstrap et install/uninstall sur A/B. Failure injection : refresh concurrent, Redis loss, callback replay, transaction rollback.

## H. Matrice de validation

| ID | Exigence | Test | Commande | Résultat attendu | Preuve |
|---|---|---|---|---|---|
| S02-AUTH / REQ-AUTH-001..014 | OAuth/session/fresh auth | contract + API + Redis + live | `python scripts/validate_stage.py 02` | tokens backend, replay/CSRF refusés, lookup ciblé | JUnit/live summary |
| S02-INST / REQ-INST-001..007 | install/bootstrap lifecycle | DB/API + sandbox | même commande | isolation, owner/admin bootstrap, uninstall invalidant | sandbox report |
| S02-TEN / REQ-TEN-001..010 | tenant/RLS/Control Plane | A/B + instrumentation | même commande | 403/404 et zéro accès B | JUnit/SQL evidence |
| S02-BOT / REQ-BOT-001..003,007 | secret/minimal auth | scan + capability tests | même commande | aucun token frontend/self-bot/admin par facilité | reports |

## I. Commandes exactes de validation

```bash
docker compose -f compose.test.yaml up -d --wait
python scripts/validate_stage.py 02
# Seulement quand les variables sandbox ont été placées dans .env.local :
python scripts/validate_stage.py 02 --include-discord-live
docker compose -f compose.test.yaml down
```

L’option live doit être implémentée dans cette étape et skip explicitement sans variables, jamais produire un faux PASS live.

## J. Tests Discord réels

Guild A et B dédiées ; même application, bot permissions minimales. Tester login `identify guilds`, owner/admin/non-admin, bootstrap A, refus B, switch revalidé, suppression/réinstallation et targeted member fetch. État attendu et nettoyage suivent la matrice sandbox ; ne supprimer aucune Guild.

## K. Secrets / credentials nécessaires

| Nom | Obligatoire | Étape | Secret ? | Provenance | Stockage local | Stockage CI | Rotation |
|---|---:|---:|---:|---|---|---|---|
| `DISCORD_CLIENT_ID` | live | 02 | non | Developer Portal | `.env.local` | variable protégée | app remplacée |
| `DISCORD_CLIENT_SECRET` | live | 02 | oui | Developer Portal | `.env.local` | environment protégé | après exposition/test temporaire |
| `DISCORD_BOT_TOKEN` | install/live | 02 | oui critique | Developer Portal | `.env.local` | environment protégé | idem |
| Guild A/B IDs + redirect URI | live | 02 | IDs non secrets | sandbox/Portal | `.env.local` | variables | à changement |
| `SESSION_SECRET`, `OAUTH_TOKEN_ENCRYPTION_KEY` | oui | 02 | oui | CSPRNG/KMS | `.env.local` | secrets | versionnée/périodique |

Demander ces valeurs uniquement juste avant le live test, en demandant à l’utilisateur de les placer lui-même dans le stockage prévu.

## L. Critères d’acceptation

State réutilisé/expiré est refusé ; aucun token n’atteint JS/log ; cookie tourne après login ; mutation sans CSRF échoue ; User A autorisé A et non B reçoit 403/404 avant repository B ; RLS confirme ; bootstrap respecte owner/admin ; uninstall bloque les capacités ; auth sensible rafraîchit uniquement l’acteur lorsque nécessaire.

## M. Definition of Done

Migrations, code, tests, lint/typecheck, sécurité, live requis, preuves/REQ, régressions 01, docs/handoff/état, commit/push/PR et merge avant 03.

## N. Handoff obligatoire

Créer `STAGE_02_HANDOFF.md` : schémas/migrations, politique cookie/CSRF/crypto, endpoints, RBAC, état installations A/B expurgé, tests, secrets encore nécessaires, prérequis Gateway et décisions ouvertes.

## O. Prompt de démarrage d’un nouveau chat Codex

```text
Implémente uniquement STAGE 02 de Discord Infrastructure Designer.
Lis AGENTS.md, le contrat global, l’état courant et intégralement STAGE_02_OAUTH_SESSIONS_TENANCY_RBAC_INSTALLATION.md ; exécute le PRECHECK et consulte les deux références.
N’implémente aucune étape suivante. Termine code, migrations, tests, preuves, handoff, état/traçabilité, commit et PR. Ne demande les credentials Discord qu’au premier test live réellement nécessaire et ne les affiche jamais.
```
