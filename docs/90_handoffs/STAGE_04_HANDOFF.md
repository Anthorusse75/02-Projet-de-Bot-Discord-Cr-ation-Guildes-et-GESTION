# Handoff STAGE 04 — Read model, permissions, diagnostics et scopes

| Champ | Valeur |
|---|---|
| Date | `2026-08-17` |
| Base main | `1f7e4cd7f2ebe92e6c63ede0738731c5bcc3b6ee` |
| Branche | `stage/04-read-permissions` |
| PR | Draft PR à publier vers `main`; ne pas merger avant revue externe |
| Commits code | `ce7558676250`, `7e154bc`, `05d11c1`, `5721fdc`, `29561b18f71f` |
| Migration | `0005_stage_03 -> 0006_stage_04` |
| Statut | `STAGE_04_COMPLETE_PR_OPEN` après publication de la Draft PR |

## Contrat livré

STAGE 04 reste strictement read-only vis-à-vis de Discord. Il expose la structure locale, les rôles et overwrites, les décisions de permissions, Why Access, View As, la compilation simple pure, le modèle expert, la simulation d’impact, le Capability Checker du bot, les groupes logiques et Visibility Scopes. Les seules mutations sont des configurations DID locales, autorisées, RLS et auditées. Aucun Desired State, Plan Engine, exécuteur de mutation, clone ou fonctionnalité STAGE 05+ n’a été créé.

Le read model domaine est immutable et ne dépend ni de FastAPI, SQLAlchemy, Redis, `discord.py` ni d’un transport. `GuildSnapshot`, `RoleSnapshot`, `MemberSnapshot`, `ChannelSnapshot`, `OverwriteSnapshot`, `CoverageSnapshot` et `FreshnessSnapshot` portent IDs, versions, provenance, fraîcheur, observabilité et couverture. Les états `FRESH/AGING/STALE/UNKNOWN`, `FULL/PARTIAL/DEGRADED` et `VISIBLE/OBFUSCATED/ACCESS_LOST/...` restent visibles.

La structure représente une Guild, ses catégories réelles, leurs channels, les channels racine et les threads sous leur parent réel. Une catégorie avec `parent_id` est refusée. Un groupe logique est toujours `DID_LOGICAL_RESOURCE`, jamais une sous-catégorie Discord. `SYNCED` signifie que les overwrites complets observés du channel et de sa catégorie sont canoniquement identiques; couverture insuffisante donne `UNKNOWN`, sans héritage inventé.

## Sources Discord et Permission Registry

Documentation officielle consultée le `2026-08-17` :

- [Permissions](https://docs.discord.com/developers/topics/permissions) : entier variable sérialisé en string, owner/`ADMINISTRATOR`, ordre des overwrites, implicites, threads, sync et hiérarchie;
- [Threads](https://docs.discord.com/developers/topics/threads) : parent, threads publics/privés, membership, archive/lock et `MANAGE_THREADS`;
- [Channel Resource](https://docs.discord.com/developers/resources/channel) : types, `parent_id`, overwrites string et metadata thread;
- [Guild Resource](https://docs.discord.com/developers/resources/guild) : `owner_id`, rôles et permissions guild;
- [Server and Channel Management](https://docs.discord.com/developers/platform/server-and-channel-management) : contraintes de gestion;
- [Change Log](https://docs.discord.com/developers/change-log) : permissions récentes, dont `SET_VOICE_CHANNEL_STATUS`, `PIN_MESSAGES` et `BYPASS_SLOWMODE`.

Le registry `discord-permissions-2026-08-17` contient les bits officiels 0–52, bit 47 non assigné. Chaque flag porte nom, bit, applicabilité de channel et clé de diagnostic. Le domaine utilise `int` arbitraire; l’API utilise exclusivement des strings décimales. `known_bits` et `unknown_bits` sont séparés; tout bit futur observé, notamment au-delà de `2^53`, traverse parsing, calcul, overwrites et sérialisation sans perte.

## Algorithme de permissions

La base commence par `@everyone`, puis OR de chaque rôle connu du membre dans un ordre déterministe. L’owner obtient le bypass `OWNER_BYPASS`. Sinon, `ADMINISTRATOR` obtenu par `@everyone` ou un rôle produit `ADMINISTRATOR_BYPASS`, tous les flags connus, les bits futurs déjà observés et un avertissement stable; aucun overwrite de channel ou membre ne le restreint.

Sans bypass, l’ordre exact est : everyone deny, everyone allow, OR de tous les role deny, OR de tous les role allow, member deny, member allow. La position des rôles n’intervient pas. Ainsi, si un rôle refuse `VIEW_CHANNEL` et un autre l’autorise, l’agrégat allow gagne, quelle que soit leur position ou l’ordre des entrées.

`calculated_bits` conserve le bitfield explicite après overwrites. `effective_bits` applique séparément l’applicabilité du type de channel et les règles implicites : sans `VIEW_CHANNEL`, les actions channel sont indisponibles; sans `SEND_MESSAGES`, les quatre dépendances documentées sont indisponibles; sans `CONNECT`, les actions voice/stage dépendantes sont indisponibles. Chaque retrait reste visible dans `implicit_denials` et la trace.

Les threads utilisent les overwrites du parent observé, exigent `VIEW_CHANNEL`, utilisent `SEND_MESSAGES_IN_THREADS` plutôt que `SEND_MESSAGES`, et traitent la membership d’un thread privé. `MANAGE_THREADS` permet la visibilité modérateur. Une membership privée inconnue ou une couverture threads incomplète produit `INCOMPLETE/UNKNOWN`; elle n’est jamais fabriquée. Archive/lock produit un diagnostic, et un thread locked sans `MANAGE_THREADS` rend l’envoi effectivement indisponible.

Un type de channel futur inconnu est conservé comme entier et rend la décision `UNKNOWN`, plutôt que d’inventer une applicabilité.

## PermissionDecision, Why Access et View As

`PermissionDecision` contient Guild, sujet, ressource, `calculated_bits`, `effective_bits`, `unknown_bits`, `COMPLETE/INCOMPLETE/UNKNOWN`, outcome demandé `ALLOWED/DENIED/UNKNOWN`, couverture, fraîcheur, raisons incomplètes, avertissements, versions de source, assertion `CURRENT_CONFIRMED/LAST_KNOWN`, denials implicites et trace.

La trace ordonnée et stable utilise les étapes `BASE_EVERYONE`, `BASE_ROLE`, `BASE_ROLES_OR`, `OWNER_BYPASS`, `ADMINISTRATOR_BYPASS`, everyone deny/allow, role deny/allow agrégés, member deny/allow, `THREAD_INHERITANCE`, `IMPLICIT_DENIAL` et `COVERAGE_INCOMPLETE`. Chaque entrée porte type/ID source, allow/deny, before/after et `reason_key`, sans texte UI en dur.

L’endpoint Explain retourne deux sections impossibles à confondre : `discord_native_permission` et `did_dashboard_authorization`; un scope DID n’est jamais présenté comme une restriction Discord native.

View As supporte : membre réel avec ses rôles connus; rôle synthétique avec `@everyone + ce rôle`; newcomer synthétique avec `@everyone` seul. Les identités synthétiques ne peuvent pas déclencher le bypass owner. Une connaissance membre stale/incomplète reste explicite.

Le mode simple compile `VIEW`, `WRITE`, `MANAGE`, `VOICE_JOIN`, `VOICE_SPEAK` et `VOICE_STREAM` vers des bits réels du registry, avec diagnostics contextuels, sans persistance. Le modèle expert expose bitfields, flags connus, bits inconnus, overwrites normalisés, sync, fraîcheur et couverture. La simulation compare current/proposed pour jusqu’à 500 sujets, refuse les threads/targets dupliqués/cross-tenant, retourne ajouts/retraits et ne persiste rien (`discord_mutations=0`).

## Capability Checker et hiérarchie

Le checker retourne `CAN/CANNOT/UNKNOWN`, permissions minimales requises, causes, remédiations et diagnostic de hiérarchie pour gestion/attribution de rôle. Il couvre installation, permission, accès channel, intent/capability, couverture et hiérarchie. Il ne recommande jamais `ADMINISTRATOR` par défaut.

Le rôle le plus haut du bot doit être strictement au-dessus de la cible; à position identique, le tri Discord par Snowflake est appliqué. Une cible égale, supérieure ou managed est refusée. Cette hiérarchie n’est jamais utilisée pour résoudre des overwrites.

## Groupes logiques et Visibility Scopes

La migration `0006_stage_04` crée `logical_groups`, `logical_group_resources`, `visibility_scopes`, `scope_membership_rules` et `scope_explicit_memberships`. Toutes sont `guild_id`-scopées, avec RLS forcée, grants minimaux, FK composites, uniques/index et checks. Les cibles de groupe sont exclusivement CATEGORY/CHANNEL/ROLE réels de la même Guild; le schéma ne permet aucune référence groupe→groupe, donc aucune récursion, cycle ou self-membership. Les doublons et types incohérents sont refusés. CRUD local groupe/scope est RBAC, RLS et audité.

Le Scope Membership Resolver central et déterministe implémente réellement `DISCORD_ROLE`, `ANY_DISCORD_ROLE`, `ALL_DISCORD_ROLES` et `EXPLICIT_DID_MEMBERSHIP`. Le type de stockage canonique `CUSTOM`, correspondant au `CUSTOM_RULE` produit, reste volontairement non exécutable et retourne `UNKNOWN`; aucun `eval`, SQL brut ou code utilisateur n’est interprété. Les IDs de rôles API sont des strings, validés contre les rôles locaux de la Guild en une requête batch. Aucun profil de langue n’accorde un scope.

La sortie est `MATCH/NO_MATCH/UNKNOWN`, avec trace par règle, diagnostics, fraîcheur et `cache_version` dépendant des versions du scope, des règles et du snapshot membre. Les rôles absents/incomplets/stale et les configs invalides donnent `UNKNOWN`.

## Fraîcheur, cache et observabilité

Les lectures normales `/structure`, `/roles`, `/coverage`, evaluate et View As consomment seulement les projections locales batchées; les tests instrumentés constatent authorization avant repository et zéro REST Discord. Le router Stage 04 ne dépend d’aucun transport Discord ou mutation engine.

La fraîcheur d’affichage reste distincte de la fraîcheur d’autorisation. Pour une autorisation sensible et un acteur stale, le lookup individuel existant est coalescé par le single-flight Redis tenant-scopé Stage 03. Trois consumers concurrents produisent un seul appel `Get Guild Member`; tous reçoivent la même observation. Un échec est fan-out et fail-closed, sans fallback stale et sans `List Guild Members`.

Les métriques bornées couvrent durée/count des évaluations, décisions incomplete/unknown, refresh acteur ciblé, gaps de couverture, outcomes capability et scope. Aucun label non borné `guild_id/channel_id/role_id/user_id` n’est utilisé.

## API

- version d’API `1` : `GET guilds/{guild_id}/structure`, `/roles`, `/coverage`, `/capabilities`;
- `POST .../permissions/evaluate`, `/explain`, `/simple/compile`, `/simulate`;
- `GET/POST/PATCH/DELETE .../logical-groups[/id]`;
- `GET/POST/PATCH/DELETE .../visibility-scopes[/id]` et `POST .../visibility-scopes/{id}/resolve`.

Les Snowflakes/bitfields sortent en strings. Toute lecture autorise avant la projection; toute mutation locale exige CSRF, capability sensible, RLS et audit. Aucune route ne mute Discord. Les changements locaux ne sont pas diffusés en WebSocket en Stage 04; le système tenant-isolé Stage 03 reste l’unique transport WS.

## Tests, performance et preuves

Sur le commit `29561b18f71f9464fe84cf6edcb0eb01f558e26a` :

| Validation | Résultat | Preuve locale |
|---|---|---|
| STAGE 01 | PASS, 144 unit, 47 integration, 4 frontend | `artifacts/test-evidence/stage-01/20260817T084726827356Z-29561b18f71f-local-docker/` |
| STAGE 02 | PASS, même régression + migrations/live opt-in honnête | `artifacts/test-evidence/stage-02/20260817T084810209767Z-29561b18f71f-local-docker/` |
| STAGE 03 | PASS, runtime/cache/WS/races | `artifacts/test-evidence/stage-03/20260817T084849864193Z-29561b18f71f-local-docker/` |
| STAGE 03 load | PASS, 6 tests load | `artifacts/test-evidence/stage-03/20260817T084933877787Z-29561b18f71f-local-docker/` |
| STAGE 04 + live | PASS, 144 unit, 47 integration, 4 frontend, migration rehearsal, benchmark, live | `artifacts/test-evidence/stage-04/20260817T084616476276Z-29561b18f71f-local-docker/` |
| Documentation | PASS, 246/246 REQ, 35 ADR | même preuve Stage 04 |
| Secret scan | PASS, 205 fichiers | même preuve Stage 04 |

Le benchmark pur construit 400 channels, 41 rôles et 12 overwrites/channel : 400 décisions, zéro requête DB, `0.086–0.092 s` sur la machine locale, seuil reproductible 3 s. Les tests officiels/table-driven et invariants couvrent everyone, OR rôles, owner, administrator, collisions, member overwrite, implicit permissions, category sync, threads, permutations, bits futurs, trace finale, fail-safe et JS precision.

Le live A/B est `PASS_WITH_APPROVED_LIMITATION` : 53/18 channels et 39/11 rôles observés, 0 mismatch sur le sous-ensemble d’actions applicables, zéro mutation. La documentation officielle est l’oracle normatif; `discord.py==2.7.1` est un oracle secondaire. Threads actifs/privés, sync/desync fabriquée, hiérarchie managed/égale et profils humains administrateur non-owner/non-administrateur restent `SKIPPED_NOT_VERIFIED`, car le runner read-only ne crée pas ces fixtures. Voir `STAGE_04_LIVE_EVIDENCE.json`.

## Security review

Revue ciblée et tests de non-régression : aucune troncature/float/JS Number; unknown bits conservés; owner/admin sans faux négatif ni fausse restriction; collision role agrégée sans position; member overwrite en dernier; stale/obfuscated/access-lost/private-thread-unknown jamais transformé en allow; type channel futur fail-safe; IDs API string; cross-tenant groupe/scope/role refusé; CUSTOM non exécuté; managed role diagnostiqué; aucune confusion RBAC DID/Discord; aucun REST router; snapshots batch sans N+1; aucune récursion de groupe; aucune recommandation administrator par défaut; aucun besoin `MESSAGE_CONTENT` ou `GUILD_MEMBERS` par défaut.

## Exigences encore PLANNED et contrat d’entrée STAGE 05

- `REQ-STR-004/005` : la topologie et les diagnostics read-only existent, mais le respect des mouvements/suppressions doit être appliqué par les Plans STAGE 05.
- `REQ-BOT-004` : le bot installé signale `ADMINISTRATOR`, mais l’audit de tous les bots de la Guild reste STAGE 10.
- `REQ-BOT-005` : le bot installé est évalué pour une opération/channel explicite; l’inventaire de chaque bot reste STAGE 10.
- `REQ-BOT-006` : la configuration bot-écrit/humains-lisent est simulable avec de vrais overwrites, mais son application appartient aux STAGE 05/10.
- `REQ-CACHE-007` : l’API `include_hidden_deleted` existe; son contrôle UI appartient à STAGE 07.

Le contrat d’entrée Stage 05 est `GuildSnapshot` + versions de source + `PermissionDecision` + Capability Checker + groupes/scopes locaux. Stage 05 devra construire Desired State/Plan sans modifier le calculateur pur, revalider versions/fraîcheur/capabilities juste avant exécution, conserver RLS/audit/outbox/governor, et traduire toute incertitude en blocage. **STAGE 05 est interdite avant merge et revue externe de la Draft PR Stage 04.**
