# Handoff STAGE 08 — Contenu multilingue et topologie de traduction

> **Statut :** corrections de deep review intégrées et re-vérifiées contre le code actuel (voir
> `docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md`). La première qualification live sur sandbox
> réelle (commit `9240cb1`) a révélé un défaut de code réel — pas un problème de sandbox — décrit et
> corrigé dans la section « Défaut réel découvert par la qualification live » ci-dessous (commit
> `592b94b`). Une nouvelle qualification live sur sandbox nettoyée a ensuite PASS intégralement. Après
> audit externe indépendant final, la PR #8 (head approuvé `4227483`) a été mergée dans `main` par un vrai
> merge commit et taguée `stage-08-complete`. STAGE 08 est `STAGE_08_INTEGRATED_IN_MAIN`.

| Champ | Valeur |
|---|---|
| Date | `2026-08-31` |
| Base main (avant merge) | `252a4661195a3868acd04a2987453e23fc6ee4ff` |
| Branche | `stage/08-multilingual-topology` (conservée après merge) |
| PR | [#8](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/8), merged |
| Statut | `STAGE_08_INTEGRATED_IN_MAIN` |
| Functional tested code | `592b94bdee713cfb51e236e29cb979ba60e53ac9` (qualification live PASS testée sur ce commit, code inchangé jusqu'au head approuvé) |
| Approved final head | `42274836256d2af449678c239c2db4d8e5e6d01d` |
| Merge commit | `d6a8425cff6606cace2ac89705b71519b6a308b1` (deux parents : `252a466…` et `4227483…`, pas de squash/rebase) |
| Tag | `stage-08-complete` -> `d6a8425cff6606cace2ac89705b71519b6a308b1` |
| Migration | `0013_stage_07 → 0014_stage_08 → … → 0021_stage_08` ; tête unique `0021_stage_08` ; rehearsal down/up validé |
| Dernière étape intégrée | `STAGE_07_REACT_DASHBOARD_I18N_AND_INTERACTIONS` |
| Étape suivante | `STAGE_09_READY_NOT_STARTED`; autorisée mais non commencée |

## Architecture livrée

STAGE 08 sépare durablement Language Profile, Translation Group, Translation Channel Group, variant,
route, Visibility Scope et binding provider. Toutes les entités persistées portent `guild_id`, utilisent
des clés/FK composites tenant-safe et sont protégées par `ENABLE/FORCE RLS`. Les IDs logiques restent
stables quand un groupe ou un salon logique est renommé. L'isolation intra-Guild entre deux Translation
Groups (rename, unlink variant/catégorie, link avec groupe étranger) est prouvée par PostgreSQL
(`backend/tests/integration/test_stage08_application_postgres.py:277-382`).

La couche application fournit les cas d'usage langues, groupes, variants, routes, visibilité, capacité,
provider, drift et clone multilingue. Les routers FastAPI autorisent avant lecture/écriture et délèguent
aux services/repositories. Aucune route Stage08 n'accepte de DSG arbitraire construit côté client : le
serveur compile les intents métier lui-même. Le clone inter-Guild exige lecture sur la source puis création
et écriture sur la destination via le vrai moteur Stage06 (Portable Artifact, Dependency Graph, Clone
compiler, Planning Service, Destination Plan, matérialisation post-vérification).

Les changements Discord passent par le DSG et le Plan Engine STAGE 05 : plan, preflight, confirmation,
job durable, worker, governor, adapter, vérification et audit. Les routes de plan couvrent création de
structure/variant, ajout-retrait de langue, link/unlink, routes, visibilité, provider et réparation de
drift. Les garanties effectively-once, `UNKNOWN_OUTCOME` et récupération restent celles de STAGE 05.

## Langues, topologie et cycle de vie

- Language Profiles : create/read/update/enable/disable, ID stable, aucune langue principale.
- Langues visibles membre : ensemble zéro/une/plusieurs, opérations set/add/remove, source
  `EXPLICIT`, `ONBOARDING`, `SYNC` ou `MANUAL`, aucun fallback implicite.
- Résolution ressource : `SELF`, `CATEGORY`, `NONE`; override salon prioritaire, héritage seulement si
  demandé, profil disabled/missing refusé.
- Groupes : create/read/rename, deux groupes FR/EN restent indépendants et isolés (preuve PostgreSQL A/B).
- Routes : `HUB_AND_SPOKE`, `CUSTOM`, `FULL_MESH` seulement sur capacité provider connue et supportée.
- Ajout de langue : delta transactionnel ; une langue désactivée est rejetée avant toute mutation, sans
  incrément de version CAS ; les variants valides existants sont conservés.
- Retrait/unlink : non destructif par défaut ; aucune ressource Discord n'est supprimée implicitement ;
  scopé strictement au groupe propriétaire (isolation A/B).
- Link : sélection explicite confirmée, aucune inférence silencieuse par nom ou langue.
- Concurrence : CAS `expected_version` pour mutations groupe/routes et contraintes PostgreSQL pour les
  courses d'unicité.
- Drift : omission simple = observabilité incertaine ; seule une preuve positive marque le variant
  `MISSING`; la réparation est proposée par plan sans propagation destructive.

## Visibilité Scope × Language

Discord agrège les overwrites de rôles et ne fournit pas un opérateur logique AND entre deux rôles.
Le compiler n'utilise donc jamais « Scope Role + Language Role ». `SCOPE_AND_LANGUAGE` matérialise un
binding technique durable `(guild_id, visibility_scope_id, language_profile_id)` réutilisable entre
Translation Groups, via un binding kind `SCOPE_LANGUAGE` distinct. `LANGUAGE_FILTERED` utilise un rôle
technique global de langue (binding kind `LANGUAGE`), sémantiquement séparé de `SCOPE_AND_LANGUAGE`.
`OPEN_ALL` n'ajoute aucune restriction ; `CUSTOM` exige ses overwrites explicites.

`Stage08StructuralPlanningService` compile ces plans depuis la topologie durable et le cache Discord
autoritatif : réservation concurrent-safe, rôle lazy, budget rôle (`DISCORD_ROLE_LIMIT` contre le cache
réel `guild.roles`), budget overwrites (`DISCORD_OVERWRITE_LIMIT` contre le cache réel des overwrites de
salon), DSG Stage05, plan, matérialisation après vérification, réutilisation, et cleanup fail-closed (le
cleanup du rôle technique exige une preuve de couverture membre complète — `coverage.mode=FULL`,
`freshness=FRESH`, `members_complete`/`roles_complete`/`channels_complete` — sinon il échoue fermé sans
bloquer le reste de la plateforme).

Un rôle technique lazy possède `permissions=0`, `hoist=false`, `mentionable=false`. Le reconciler
(`create_member_role_plan`) recharge les langues visibles durables, résout les scopes via
`ScopeMembershipResolver`, recharge les bindings techniques et lit les rôles membre depuis le cache Discord
autoritatif — jamais depuis des données fournies par le client. Il ne crée que l'intersection entre langues
visibles et scopes métier déjà acquis : un choix de langue ne peut jamais accorder un scope. Il n'émet ni
member overwrite ni rôle `ALL_LANGUAGES`.

**Exception control-plane (REQ-I18N-022) :** REQ-I18N-022 (« les member-specific overwrites ne sont pas
utilisés comme stratégie normale de visibilité multilingue ») reste intégralement vraie pour la visibilité
métier humaine. Un unique overwrite de type membre est ajouté, uniquement pour le clone multilingue
Stage06→05 et uniquement sur les salons destination qui portent un deny `VIEW_CHANNEL`, ciblant le
`bot_identity()` durable de la Guild destination — jamais Administrator, jamais un rôle métier humain. C'est
une exception service-principal/control-plane étroitement bornée nécessaire pour que le bot DID conserve
l'administration des salons qu'il vient de créer ; elle ne doit jamais être généralisée aux utilisateurs
humains. Voir la section « Défaut réel découvert par la qualification live » ci-dessous.

## Matrice provider

| Situation | Décision |
|---|---|
| capacité connue et supportée | topologie autorisée, sous réserve du preflight d'accès |
| capacité inconnue ou non supportée | échec fermé, notamment pour `FULL_MESH` |
| bot absent | `NOT_INSTALLED`, aucune corruption de topologie |
| automation sûre disponible | préparation puis `PREPARED_NOT_VERIFIED`; jamais READY avant vérification |
| bot existant sans interface sûre | `MANUAL_CONFIGURATION_REQUIRED` avec instructions et `PENDING_MANUAL_VERIFICATION` / `PROVIDER_PENDING` |
| provider dégradé/échec après structure | `APPLIED_WITH_PENDING_PROVIDER`, état diagnostiquable, aucune suppression/rollback automatique |

`TranslationProvider` est un port réel (`Protocol`). `Stage08ProviderOrchestrationService.access_preflight`
dérive les capacités/permissions depuis le Translation Group durable, le Provider Binding durable, le cache
Stage04 et un `PermissionEvaluator` — le navigateur ne peut plus déclarer lui-même des capacités ou
permissions autoritatives. `READY` reste prouvablement inatteignable avant `verify_manual_configuration`.
L'adapter du bot de traduction existant est non invasif : aucune nouvelle API, aucun changement de schéma
externe, aucun partage de token et aucune sérialisation de secret. `requires_message_content` appartient
aux capacités du provider ; DID n'active pas `MESSAGE_CONTENT` pour gérer la topologie. Le preflight vérifie
présence et permissions effectives minimales sur chaque variant. `ADMINISTRATOR` produit un warning et
n'est jamais recommandé. Les rôles d'audience humaine ne sont pas utilisés comme accès principal du bot
provider.

## Clone multilingue

Le vrai moteur Stage06 exécute :

`PORTABLE_SNAPSHOT → LANGUAGE_EXPANSION → DEPENDENCY_GRAPH → VISIBILITY_RESOLVER → TRANSLATION_TOPOLOGY → PREFLIGHT → DESTINATION_PLAN`.

Chaque groupe source reçoit un nouvel ID de Translation Group destination (`cloning/builder.py`). Deux
groupes source partageant FR/EN restent deux groupes distincts. Les mappings sont explicites,
`live_source_link=false`, la source reste inchangée et les bindings provider sont omis. Le Portable
Artifact utilise un schéma allowlist typé par type de ressource et un scrub récursif (`_walk_keys`) qui
retire token, secret, credential et blob chiffré de provider avant toute sérialisation, y compris dans les
structures imbriquées.

## Gateway et preuve d'exhaustivité membre

Stage03 Gateway/runtime persiste durablement le fait Discord `user.bot` (migration `0021_stage_08`) et
suit la complétude membre (`discord_cache_coverage` : `known_members`, `member_count`,
`members_complete`, migration `0020_stage_08`) pour les opérations qui ont besoin d'une preuve
exhaustive, notamment le cleanup sûr de rôle technique. Cette exigence de couverture est locale à ce
chemin d'appel ; le cœur Stage08 ne dépend pas d'un intent `GUILD_MEMBERS` global permanent.

## API, UI et localisation

Les endpoints couvrent languages, member languages, policies/résolution, workspace, groups/channel
groups, add/remove/link/unlink, routes, visibilité/capacité, rôles membre, provider, drift, clone preview
et toutes les entrées de plan. Le snapshot OpenAPI et les types TypeScript sont régénérés.

La Translation Workspace (lecture cache-first, zéro appel REST Discord par requête) affiche groupes,
langues, variants, hiérarchie, routes, scope/policy, drift/MISSING, état provider/manual et capacité. Ses
queries restent scopées utilisateur+Guild et réutilisent le nettoyage tenant de STAGE 07. Le même
ActionRegistry expose `CREATE_VARIANT` (→ `/variants/plan`), `LINK_EXISTING_VARIANT` (→ `/link`),
`CLONE_UNLINKED` (→ `/multilingual-clone/plan`) et `PREVIEW` (lecture réelle du groupe) dans les menus,
Right Drag (avec cibles `LANGUAGE_TARGET` et Guild destination) et alternatives clavier. Un drag inter-Guild
signifie clone/copy, jamais move.

Le catalogue immutable passe de `did-ui-v&#49;` à `did-ui-v&#50;`. Toutes les nouvelles clés visibles existent
en EN/FR/DE/ES ; aucun enum interne ni clé brute n'est rendu.

## Validation et preuves

| Gate | Résultat |
|---|---|
| `python scripts/validate_stage.py 01/03/05/06/07` (régression) | PASS |
| `python scripts/validate_stage.py 08` | PASS : unitaires backend, intégrations PostgreSQL/Redis, frontend lint/typecheck/build, migrations, sécurité et docs |
| tests ciblés STAGE 08 | PASS : 27 unitaires (`test_stage08_translation_topology.py`, `test_stage08_services.py`), 14 PostgreSQL (`test_stage08_persistence.py`, `test_stage08_application_postgres.py`), dont isolation A/B et ordre structurel |
| `python scripts/validate_stage.py 08 --profile e2e` | PASS : 40 Playwright, dont 8 scénarios STAGE 08 (right-drag, ActionRegistry, workspace a11y, member languages), axe et EN/FR/DE/ES |
| `python scripts/validate_stage.py 08 --include-discord-live` | **PASS** sur deux Guilds sandbox réelles (`docs/90_handoffs/evidence/stage08/discord-live-stage08.json`, testé sur `592b94b`) ; voir section dédiée ci-dessous |
| qualité | Ruff, format, MyPy, ESLint, TypeScript, build, i18n, OpenAPI et secret scan PASS |
| Alembic | rehearsal `0013_stage_07 → head → 0013_stage_07 → head` PASS, tête unique `0021_stage_08` |

La matrice détaillée des 43 exigences se trouve dans
[`STAGE08_REQUIREMENTS_CHECKLIST_LOCAL.md`](../10_implementation/STAGE08_REQUIREMENTS_CHECKLIST_LOCAL.md)
et [`00_REQUIREMENTS_TRACEABILITY.md`](../10_implementation/00_REQUIREMENTS_TRACEABILITY.md), avec preuve
fichier:ligne et test pour chaque ID. Toutes sont `IMPLEMENTED`; aucune n'est promue à `VERIFIED` avant la
qualification transverse prévue.

## Défaut réel découvert par la qualification live et correctif (commit `592b94b`)

La première tentative de qualification live (sur commit `9240cb1`, sandbox Guild B nettoyée des anciens
salons résiduels) a révélé un **défaut de code réel**, pas un problème de sandbox : la topologie Stage08 à
visibilité managée (`LANGUAGE_FILTERED` / `SCOPE_AND_LANGUAGE`) produit un overwrite final refusant
`VIEW_CHANNEL` à `@everyone` et l'accordant au rôle langue/Scope × Language dérivé, mais ne préserve
explicitement l'accès d'aucun principal pour le bot control-plane DID lui-même. Sur la sandbox Guild A, ce
défaut restait invisible parce que le bot y détient accidentellement `Administrator` (accordé hors du code
DID, qui ne l'accorde jamais), ce qui contourne tous les overwrites de salon. La Guild B, correctement
dépourvue d'`Administrator`, expose donc le défaut : les salons fraîchement clonés par Stage06→05 refusaient
`VIEW_CHANNEL` au bot — ce qui, par la règle Discord de déni implicite déjà implémentée dans
`PermissionEvaluator`, rend aussi `MANAGE_CHANNELS` inopérant sur ces salons — et le preflight Stage05 du
`DELETE_CHANNEL` de nettoyage échouait fermé (`LiveCapabilityBlocked` / `BLOCKED_CAPABILITY_CONFIGURATION`).
L'ordre d'écriture des overwrites (le correctif antérieur grant-before-deny) n'était pas en cause : l'état
overwrite final ne contenait tout simplement jamais d'octroi pour le bot.

**Correctif (`592b94b`) :** `PortabilityService.compile_stored` augmente désormais le graphe désiré de
destination, uniquement pour les clones multilingues Stage08, d'un overwrite explicite de type membre
accordant `VIEW_CHANNEL` au `bot_identity()` durable de la Guild destination, pour chaque salon portant un
deny `VIEW_CHANNEL`. Il ne touche ni la visibilité humaine, ni `PermissionEvaluator`, ni l'ordre des
mutations, ni le provider. Il n'accorde jamais `Administrator` ni un rôle métier humain — c'est une
exception service-principal/control-plane étroitement bornée (voir section Scope × Language ci-dessus).
Régression PostgreSQL dédiée :
`test_multilingual_clone_preserves_control_plane_bot_access_on_restricted_channel`
(`backend/tests/integration/test_stage06_postgres.py`), vérifiée en échec sur le code pré-correctif et en
succès après, prouvant via le vrai `PermissionEvaluator` : accès bot préservé, humain sans le rôle dérivé
toujours refusé, preflight `DELETE_CHANNEL` autorisé, aucun `Administrator`, aucune fuite de secret/binding
provider dans l'artifact.

Une amélioration diagnostique séparée (`592b94b` puis ce commit) a par ailleurs corrigé la propagation des
noms de capacité manquants sanitisés (ex. `MANAGE_CHANNELS`) dans le rapport JSON du validateur live
STAGE 08, testée par `backend/tests/unit/test_stage08_live_diagnostics.py`.

**Re-qualification live :** après suppression manuelle par l'opérateur des anciens salons résiduels de
Guild B et application du correctif, `uv run python scripts/validate_discord_live_stage08.py --include` sur
commit `592b94b` a produit un `status: PASS` complet sur les deux Guilds sandbox réelles. La preuve
sanitisée (zéro secret, zéro identifiant Discord, zéro PII) est committée dans
[`evidence/stage08/discord-live-stage08.json`](evidence/stage08/discord-live-stage08.json).

## État opérationnel et limites

- PostgreSQL/Redis de test peuvent être arrêtés avec `docker compose -f compose.test.yaml down`.
- Les secrets restent exclusivement dans `.env.local`/secret store ; seuls leurs noms sont documentés.
- Aucun secret, identifiant sandbox ou PII membre n'est conservé dans les preuves.
- Le provider existant reste en configuration manuelle tant qu'une interface d'automation sûre n'est pas
  disponible ; c'est un état supporté et non un blocage de STAGE 08.
- La candidate est mergée dans `main` (commit `d6a8425`, tag `stage-08-complete`). Aucun travail STAGE 09
  n'a commencé.
