# Handoff STAGE 07 — Dashboard et localisation UI runtime

| Champ | Valeur |
|---|---|
| Date | `2026-08-28` |
| Base main | `d644015903953ef1dc46626562004746f2208c1c` |
| Branche | `stage/07-dashboard` |
| Code testé | `9220921314489eb59a90b33bc50e9a78793c6874` |
| Migration | `0013_stage_07` après `0012_stage_06`; tête unique |
| PR | [#7](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/7), Draft, non mergée |
| Statut | `STAGE_07_COMPLETE_DRAFT_PR_OPEN` |

## Architecture et API

Le dashboard React est un client strict des routes backend existantes. TanStack Query emploie les clés
tenant `['did', userId, guildId, feature, ...detail]`. Un changement de Guild annule les requêtes,
purge seulement le namespace quitté et efface sélection, drag, contexte et palette avant la sélection
serveur suivante. Les Snowflakes restent des strings typées. Le WebSocket ferme la connexion au switch,
ignore une autre Guild ou version inconnue, invalide le domaine ciblé et tout le tenant sur trou de
séquence.

Le client OpenAPI est généré depuis FastAPI dans `frontend/openapi.json` et
`frontend/src/api/openapi.d.ts`; `scripts/check_openapi.py` bloque toute dérive. Toutes les mutations
cookie-authenticated utilisent CSRF. Un `401` efface la session et les enveloppes
`code/message_key/params/request_id` restent typées.

`GET /api/v&#49;/guilds/{id}/dashboard-capabilities` agrège l’autorité utilisateur réellement résolue et
les diagnostics bot Stage 04 depuis le cache local. Les décisions sont explicites (`CAN`, `CANNOT`,
`UNKNOWN`), globales et liées à la ressource quand elle est fournie. La route est read-only,
cache-first, effectue zéro REST Discord et ne remplace jamais l’autorisation finale des commandes.

| Écran | Routes principales | Sémantique |
|---|---|---|
| Auth / Guilds | `GET /api/v&#49;/me`, `GET /api/v&#49;/guilds`, `POST /api/v&#49;/guilds/{id}/select` | Login localisé, sélection fail-closed |
| Structure | `GET /api/v&#49;/guilds/{id}/structure` | Cache catégorie/channel/thread, recherche, multi-sélection, contexte et drag |
| Rôles | `GET /api/v&#49;/guilds/{id}/roles` | Hiérarchie et permissions observées |
| Permissions | `POST /api/v&#49;/guilds/{id}/permissions/explain` | View As membre/rôle/newcomer, simple/expert, Why Access |
| Plans | `GET /plans`, `POST /validate`, `/confirm`, `/apply`, `/cancel`, `GET /progress` | Preview, confirmation et jobs réels, aucun succès optimiste |
| Diagnostics | `GET /api/v&#49;/guilds/{id}/coverage` | Couverture et fraîcheur cache-first |
| Audit | `GET /api/v&#49;/guilds/{id}/audit` | Audit interne local, dates selon locale |
| Templates | `GET /api/v&#49;/guilds/{id}/templates` | Templates privés à la Guild |
| Library | `GET /api/v&#49;/me/portable-artifacts`, `GET /file` | Control plane utilisateur |
| Clone | `POST /api/v&#49;/transfers` | Clone cross-Guild Stage 06, jamais move/delete source |

Les nouvelles lectures `GET /plans` et `GET /audit` autorisent avant repository et lisent PostgreSQL
local. Aucune mutation Discord structurelle, aucun REST bot-token et aucune mutation directe depuis le
frontend ou un router n'ont été ajoutés.

## Interaction unifiée

L'ActionRegistry contient 7 actions : open, move, copy, clone, export, explain et bulk. Chaque entrée
déclare types, cardinalité, mode same/cross Guild, capabilities utilisateur/bot, risque, intention et
clés i18n. Menu objet, Drop Context Menu, palette et dialogues réutilisent ce registre. Le
`contextmenu` natif est intercepté globalement.

Le moteur Pointer Events utilise mouse=6 px, pen=8 px, touch=12 px et sépare clic droit, Right Drag,
Left Drag et annulation. Left Drag same-Guild propose move ; cross-Guild propose copy/clone sans toucher
la source ; Right Drag ouvre les actions valides. Menus, dialogues et `Ctrl/Cmd+K` sont les alternatives
clavier.

Le dispatcher commun conserve l’intention complète source/destination. Un move same-Guild crée un vrai
DSG `did-dsg-v&#49;`, crée le plan Stage 05 puis lance son preflight avant navigation. Un drop cross-Guild
préremplit Clone et n’envoie le transfert Stage 06 qu’après validation de la prévisualisation. Un `403`
backend reste l’autorité finale : aucun succès n’est affiché et le contexte de capacités est invalidé.
La progression provient du journal REST durable `/progress`, avec polling jusqu’à un état terminal et
relecture complète après reconnexion/trou de séquence WebSocket.

## Localisation UI

Le catalogue immutable `did-ui-v&#49;` contient 239 clés et quatre packs bootstrap EN/FR/DE/ES complets.
La résolution BCP-47 suit l'override puis `navigator.languages`, avec EN déterministe. Le changement de
langue navigateur est suivi seulement en AUTO ; la locale Discord est indépendante. Login et dashboard
utilisent le même catalogue.

Les quatre objets bootstrap sont désormais exigés comme `MessagePack` complets au compile-time : aucun
spread anglais ne peut masquer une traduction absente. Le scanner `scripts/check_frontend_i18n.py`
parcourt réellement les `*.ts` et `*.tsx`; un test injectant `<button>Delete now</button>` prouve que la
CI échoue sur une chaîne visible hardcodée. Les enums, clés techniques et raisons backend sont rendus
via des allowlists de présentation localisées avec fallback humain fermé.

Les packs runtime publics ont ETag/cache-control et proviennent de `ui_catalog_versions` et
`ui_locale_packs`. Activation atomique seulement si version, couverture exacte, valeurs, paramètres et
absence de HTML/script sont valides ; sinon le bootstrap complet reste actif. `did_app` a SELECT
seulement. `user_ui_preferences` de Stage 02 conserve sa RLS owner. Le provisioning opérateur passe par
backend/DB validé, sans route admin publique.

Il n'existe aucune Application Command utilisateur enregistrée : `NOT_APPLICABLE`, compteur 0. Aucune
localisation de commande Discord ni aucun travail Stage 08 n'a été commencé.

## Tests et preuves

- Correctif Stage 06 `94ad842` : altération déterministe du dernier octet crypto ; test ciblé répété
  100 fois.
- Stage 07 : 266 unitaires, 77 intégrations, RLS catalogue, migrations, 22 tests frontend dans 6
  fichiers, MSW 200/401/403/404/409/422/offline/session/in-flight, cache A/B, WebSocket tenant/version/gap, gestes et
  20 000 résolutions d'actions sous 500 ms.
- E2E : 21 Playwright PASS, EN/FR/DE/ES fonctionnels, axe sans violation serious/critical, menus/Tree/Dialog
  clavier, drag gauche/droit/same/cross, Clone prérempli, payload A/B exact, progression longue/succès/échec,
  dérive 403, préférence serveur et rejet atomique d’un pack runtime invalide.
- Stage 07 principal `20260828T132815447492Z`; E2E `20260828T132943504806Z`, PASS.
- Régressions : Stage 01 `20260828T131722746925Z`, 02 `20260828T131859038332Z`, 03
  `20260828T132028730185Z`, 03 load `20260828T132200789993Z`, 04 `20260828T132222994697Z`, 05
  `20260828T132400072127Z`, failure `20260828T132550907967Z`, load `20260828T132607088033Z`, 06
  `20260828T132615917382Z`, security `20260828T132802880393Z`; toutes PASS sur `9220921`.

Les smokes Discord live restent sans nouvelle preuve Stage 07 : opt-in sandbox non demandé et aucune nouvelle
capacité Discord. Les 246 REQ et 35 ADR sont tracés. `REQ-STR-006..013`, `REQ-UX-001..007`,
`REQ-UX-CTX-001..005`, `REQ-UI18N-001..021` sont individuellement auditées et `IMPLEMENTED`; vérification finale Stage 10. Les
`REQ-I18N-*` restent Stage 08 et ne sont pas modifiées. Stage 08 n'est pas commencée.
