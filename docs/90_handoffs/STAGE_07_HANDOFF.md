# Handoff STAGE 07 — Dashboard et localisation UI runtime

| Champ | Valeur |
|---|---|
| Date | `2026-08-28` |
| Base main | `d644015903953ef1dc46626562004746f2208c1c` |
| Branche | `stage/07-dashboard` |
| Code testé | `50832be79c390d03f2bdb62570f61ccd2835925e` |
| Migration | `0013_stage_07` après `0012_stage_06`; tête unique |
| Statut | `STAGE_07_COMPLETE_DRAFT_PR_PENDING` |

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

## Localisation UI

Le catalogue immutable `did-ui-v&#49;` contient 153 clés et quatre packs bootstrap EN/FR/DE/ES complets.
La résolution BCP-47 suit l'override puis `navigator.languages`, avec EN déterministe. Le changement de
langue navigateur est suivi seulement en AUTO ; la locale Discord est indépendante. Login et dashboard
utilisent le même catalogue.

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
- Stage 07 : 264 unitaires, 77 intégrations, RLS catalogue, migrations, 14 tests frontend dans 5
  fichiers, MSW 200/401/403/404/409/422/offline, cache A/B, WebSocket tenant/version/gap, gestes et
  20 000 résolutions d'actions sous 500 ms.
- E2E : 5 Playwright PASS, EN/FR/DE/ES, axe sans violation serious/critical, contexte, palette, langue
  et switch A/B.
- Stage 07 principal `20260827T061400436298Z`; E2E `20260827T061540292917Z`, PASS.
- Régressions : Stage 01 `20260828T071516042704Z`, 02 `071636393675Z`, 03 `071803634463Z`, 03 load
  `071927903446Z`, 04 `071946070510Z`, 05 `072109881090Z`, failure `072243274173Z`, load
  `072255467506Z`, 06 `072257952506Z`, security `072437423798Z`; toutes PASS sur `50832be`.

Les smokes Discord live sont `SKIPPED_NOT_VERIFIED` : opt-in sandbox non demandé et aucune nouvelle
capacité Discord. Les 246 REQ et 35 ADR sont tracés. `REQ-STR-006..013`, `REQ-UX-001..007`,
`REQ-UX-CTX-001..005`, `REQ-UI18N-001..021` sont `IMPLEMENTED`; vérification finale Stage 10. Les
`REQ-I18N-*` restent Stage 08 et ne sont pas modifiées. Stage 08 n'est pas commencée.
