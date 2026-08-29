# Handoff STAGE 08 — Contenu multilingue et topologie de traduction

| Champ | Valeur |
|---|---|
| Date | `2026-08-29` |
| Base main | `252a4661195a3868acd04a2987453e23fc6ee4ff` |
| Branche | `stage/08-multilingual-topology` |
| PR | `#8`, Draft, non mergée |
| Migration | `0015_stage_08` après `0014_stage_08` et `0013_stage_07`; tête unique |
| Statut | `STAGE_08_COMPLETE_DRAFT_PR_OPEN` |
| Dernière étape intégrée | `STAGE_07_REACT_DASHBOARD_I18N_AND_INTERACTIONS` |
| Étape suivante | `STAGE_09_NOT_STARTED_FORBIDDEN_UNTIL_STAGE08_MERGED` |

## Architecture livrée

STAGE 08 sépare durablement Language Profile, Translation Group, Translation Channel Group, variant,
route, Visibility Scope et binding provider. Toutes les entités persistées portent `guild_id`, utilisent
des clés/FK composites tenant-safe et sont protégées par `ENABLE/FORCE RLS`. Les IDs logiques restent
stables quand un groupe ou un salon logique est renommé. La migration `0015_stage_08` ajoute précisément
le `display_name` renommable d’un Translation Channel Group sans changer son identité.

La couche application fournit les cas d’usage langues, groupes, variants, routes, visibilité, capacité,
provider, drift et clone multilingue. Les routers FastAPI autorisent avant lecture/écriture et délèguent
aux services/repositories. Le clone inter-Guild exige lecture sur la source puis création et écriture sur
la destination. Aucun router ou composant frontend n’appelle Discord pour muter la structure.

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
- Groupes : create/read/rename, deux groupes FR/EN restent indépendants.
- Routes : `HUB_AND_SPOKE`, `CUSTOM`, `FULL_MESH` seulement sur capacité provider connue et supportée.
- Ajout de langue : delta transactionnel ; les variants valides existants sont conservés.
- Retrait/unlink : non destructif par défaut ; aucune ressource Discord n’est supprimée implicitement.
- Link : sélection explicite confirmée, aucune inférence silencieuse par nom ou langue.
- Concurrence : CAS `expected_version` pour mutations groupe/routes et contraintes PostgreSQL pour les
  courses d’unicité.
- Drift : omission simple = observabilité incertaine ; seule une preuve positive marque le variant
  `MISSING`; la réparation est proposée par plan sans propagation destructive.

## Visibilité Scope × Language

Discord agrège les overwrites de rôles et ne fournit pas un opérateur logique AND entre deux rôles.
Le compiler n’utilise donc jamais « Scope Role + Language Role ». `SCOPE_AND_LANGUAGE` matérialise un
binding technique durable `(guild_id, visibility_scope_id, language_profile_id)` réutilisable entre
Translation Groups. Le salon reçoit un deny `VIEW_CHANNEL` pour `@everyone` et un allow pour ce rôle
dérivé. `LANGUAGE_FILTERED` utilise le même mécanisme avec son scope explicite ; `OPEN_ALL` n’ajoute
aucune restriction ; `CUSTOM` exige ses overwrites explicites.

Un rôle technique lazy possède `permissions=0`, `hoist=false`, `mentionable=false`. Le reconciler ne
crée que l’intersection entre langues visibles et scopes métier déjà acquis : un choix de langue ne peut
jamais accorder un scope. Il n’émet ni member overwrite ni rôle `ALL_LANGUAGES`. L’optimizer réutilise
les bindings et ne propose un cleanup que si le rôle n’est référencé par aucun overwrite ni membre.

Les preflights exposent compte courant, delta, réutilisation, limite, projection et reste. Le rôle 250+1
et l’overwrite 1000+1 sont bloqués avant plan.

## Matrice provider

| Situation | Décision |
|---|---|
| capacité connue et supportée | topologie autorisée, sous réserve du preflight d’accès |
| capacité inconnue ou non supportée | échec fermé, notamment pour `FULL_MESH` |
| bot absent | `NOT_INSTALLED`, aucune corruption de topologie |
| automation sûre disponible | préparation puis `PREPARED_NOT_VERIFIED`; jamais READY avant vérification |
| bot existant sans interface sûre | `MANUAL_CONFIGURATION_REQUIRED` avec instructions et `PENDING_MANUAL_VERIFICATION` |
| provider dégradé/échec après structure | état diagnostiquable, aucune suppression/rollback automatique |

`TranslationProvider` est un port réel. L’adapter du bot de traduction existant est non invasif : aucune
nouvelle API, aucun changement de schéma externe, aucun partage de token et aucune sérialisation de
secret. `requires_message_content` appartient aux capacités du provider ; DID n’active pas
`MESSAGE_CONTENT` pour gérer la topologie. Le preflight vérifie présence et permissions effectives
minimales sur chaque variant. `ADMINISTRATOR` produit un warning et n’est jamais recommandé. Les rôles
d’audience humaine ne sont pas utilisés comme accès principal du bot provider.

## Clone multilingue

Le format `did-portable-multilingual-v&#49;` exécute conceptuellement :

`PORTABLE_SNAPSHOT → LANGUAGE_EXPANSION → DEPENDENCY_GRAPH → VISIBILITY_RESOLVER → TRANSLATION_TOPOLOGY → PREFLIGHT → DESTINATION_PLAN`.

Chaque groupe source reçoit un nouvel ID de Translation Group destination. Deux groupes source partageant
FR/EN restent deux groupes distincts. Les mappings sont explicites, `live_source_link=false`, la source
reste inchangée et les bindings provider sont omis. Le scrub récursif retire token, secret, credential et
blob chiffré de provider avant toute sérialisation.

## API, UI et localisation

Les endpoints couvrent languages, member languages, policies/résolution, workspace, groups/channel
groups, add/remove/link/unlink, routes, visibilité/capacité, rôles membre, provider, drift, clone preview
et toutes les entrées de plan. Le snapshot OpenAPI et les types TypeScript sont régénérés.

La Translation Workspace affiche groupes, langues, variants, hiérarchie, routes, scope/policy,
drift/MISSING, état provider/manual et capacité. Ses queries restent scopées utilisateur+Guild et
réutilisent le nettoyage tenant de STAGE 07. Le même ActionRegistry expose
`CREATE_VARIANT`, `LINK_EXISTING_VARIANT`, `CLONE_UNLINKED` et `PREVIEW` dans les menus, Right Drag et
alternatives clavier. Un drag inter-Guild signifie clone/copy, jamais move.

Le catalogue immutable passe de `did-ui-v&#49;` à `did-ui-v&#50;`. Toutes les nouvelles clés visibles existent
en EN/FR/DE/ES ; aucun enum interne ni clé brute n’est rendu.

## Validation et preuves

| Gate | Résultat |
|---|---|
| `python scripts/validate_stage.py 08` | PASS : 294 unitaires backend, 88 intégrations PostgreSQL/Redis, 28 frontend, migrations, sécurité et docs |
| tests ciblés STAGE 08 | PASS : 27 unitaires et 11 PostgreSQL, dont auth A/B et ordre structurel |
| `python scripts/validate_stage.py 08 --profile e2e` | PASS : 39 Playwright, dont 8 scénarios STAGE 08, axe et EN/FR/DE/ES |
| `python scripts/validate_stage.py 08 --include-discord-live` | PASS sur deux Guilds sandbox réelles |
| qualité | Ruff, format, MyPy, ESLint, TypeScript, build, i18n, OpenAPI et secret scan PASS |

La validation live utilise seulement l’intent `GUILDS`, observe deux Guilds distinctes, vérifie les
budgets sur les comptes Discord réels, compile le rôle technique sûr et sa réutilisation, vérifie l’accès
provider sur quatre salons observés, couvre le provider absent, produit deux nouveaux IDs logiques B et
confirme zéro secret, zéro ID Discord dans le rapport, zéro mutation structurelle directe et zéro
`MESSAGE_CONTENT`. Le validator reste non destructif ; les mutations et cleanup Discord sont délégués
au Plan Engine STAGE 05, dont les régressions et preuves live sont conservées.

La matrice détaillée des 43 exigences se trouve dans
[`STAGE08_REQUIREMENTS_CHECKLIST_LOCAL.md`](../10_implementation/STAGE08_REQUIREMENTS_CHECKLIST_LOCAL.md).
Toutes sont `IMPLEMENTED`; aucune n’est promue à `VERIFIED` avant la qualification transverse prévue.

## État opérationnel et limites

- PostgreSQL/Redis de test peuvent être arrêtés avec `docker compose -f compose.test.yaml down`.
- Les secrets restent exclusivement dans `.env.local`/secret store ; seuls leurs noms sont documentés.
- Aucun secret, identifiant sandbox ou PII membre n’est conservé dans les preuves.
- Le provider existant reste en configuration manuelle tant qu’une interface d’automation sûre n’est pas
  disponible ; c’est un état supporté et non un blocage de STAGE 08.
- La candidate n’est pas mergée. Aucun travail STAGE 09 n’a commencé.
