# Phase 1 — Cartographie routes, écrans et use cases

Statut : **TERMINÉ**  
Branche : `ui/complete-redesign`

Cette cartographie répond à une question simple : **qu'est-ce qu'un utilisateur peut réellement faire aujourd'hui depuis chaque écran, et qu'est-ce qu'il manque pour satisfaire `docs/00_reference` ?**

---

## `/login`

**Rôle attendu** : OAuth2 Discord officiel, pré-auth i18n, origine locale cohérente.

**État actuel** :

- OAuth Authorization Code Grant fonctionne réellement ;
- state/cookie fonctionne si l'origine reste identique ;
- l'essai réel a échoué avec `OAUTH_STATE_INVALID` lorsque l'UI était ouverte sur `127.0.0.1` alors que Discord revenait sur `localhost`.

**Cause produit** : le dépôt ne fournit pas un montage dev same-origin officiel ; le frontend Vite n'a aucun proxy `/api`, `/auth`, `/ws`.

**Décision** : logique OAuth conservée ; bootstrap local et écran visuel refaits en Phase 2.

**Use case de sortie** : `base vierge -> une commande documentée -> http://localhost:<port> -> login -> callback -> /guilds`.

---

## `/guilds`

**Rôle attendu** : découverte des Guilds, distinction installable/configurable, état installation, démarrage onboarding.

**État actuel** :

- affiche uniquement les Guilds qui possèdent déjà une installation visible par le backend ;
- badge ACTIVE/PENDING ;
- seul bouton métier : sélectionner/ouvrir ;
- aucun assistant de bootstrap ;
- sur base vierge réelle : A/B absentes ;
- script manuel nécessaire pour créer/activer les installations.

**Écart majeur** : §5.4 non livré dans l'UI.

**Décision** : écran remplacé en Phase 2 par accueil/sélecteur premium + cartes de serveurs + états de santé + CTA onboarding.

**Use cases de sortie** :

1. bot présent + owner/admin -> « Configurer » ;
2. bot présent mais permissions incomplètes -> diagnostic avant activation ;
3. Guild non administrable -> visible uniquement si la politique produit le permet, avec cause claire ;
4. A/B visibles sans script manuel.

---

## `/guild/:guildId/structure`

**Rôle attendu** : cœur du produit, explorateur Discord fidèle et administration par gestes/actions.

**Ce qui existe** :

- lecture `useStructure` ;
- catégories/salons/threads ;
- option ressources masquées/supprimées ;
- recherche ;
- multi-sélection Ctrl/Cmd ;
- `PointerGestureManager` ;
- clic droit/right-drag ;
- ActionRegistry capability-aware ;
- preview avant action ;
- destinations inter-Guild.

**Ce qui ne va pas** :

- dans le test réel, aucune structure n'est apparue ;
- rendu arborescence rudimentaire (`◇`, `#`) ;
- panneau propriétés quasi vide ;
- aucun explorateur desktop premium ;
- drag visuel peu explicite ;
- pas de vraie édition contextuelle riche ;
- aucune preuve actuelle qu'un drag réel aboutit à Discord puis revient proprement dans l'UI.

**Décision** : logique d'actions réutilisable ; rendu et interaction reconstruits Phase 3 selon `Esquisse 1.png`.

**Use cases de sortie** : sélectionner, multi-sélectionner, renommer, déplacer, réordonner, créer, dupliquer, supprimer/recréer, drag gauche, right-drag, context menu, clone A->B, drift externe, reload.

---

## `/guild/:guildId/roles`

**Rôle attendu** : administrer la hiérarchie des rôles.

**État actuel** : **lecture seule**.

L'écran affiche nom, managed, permissions brutes et nombre de flags connus. Il ne permet pas :

- créer ;
- renommer/modifier ;
- supprimer ;
- réordonner ;
- comprendre l'impact de hiérarchie ;
- planifier/appliquer une mutation.

**Décision** : non conforme en tant qu'outil d'administration. Reconstruction Phase 4.

---

## `/guild/:guildId/permissions`

**Rôle attendu** : mode simple humain + mode expert Discord + View As + Pourquoi + édition.

**État actuel** :

- View As membre/rôle/nouveau ;
- endpoint explain ;
- trace en mode expert ;
- warning ADMINISTRATOR ;
- **saisie manuelle de Snowflake membre/rôle et ressource** ;
- aucune vraie édition de permissions/overwrites depuis l'écran.

**Décision** : moteur d'explication à conserver ; UI non conforme au principe « sans connaissance Discord ». Reconstruction Phase 4 avec sélecteurs humains, matrice et panneau impact.

---

## `/guild/:guildId/plans`

**Rôle attendu** : intention -> validation -> impact -> confirmation -> apply -> vérification -> audit.

**État actuel** :

- liste des plans ;
- validate/preflight ;
- confirm ;
- apply ;
- cancel ;
- confirmation renforcée ;
- progression ;
- erreurs conflit ;
- capability gating.

**Manques UI** :

- comparaison avant/après réellement lisible ;
- graphe/dépendances compréhensibles ;
- impact humain ;
- échec partiel/UNKNOWN_OUTCOME mieux expliqué ;
- passage audit direct.

**Décision** : logique largement conservable, UI reconstruite Phase 5.

---

## `/guild/:guildId/diagnostics`

**Rôle attendu** : dire **ce qui ne fonctionne pas et comment le corriger**.

**État actuel** : affiche seulement couverture et fraîcheur.

Le backend `dashboard-capabilities` possède davantage d'information (capacités utilisateur, opérations bot, causes/remédiations), mais l'écran ne l'exploite pas réellement.

**Décision** : écran actuel insuffisant. Phase 2 utilise les diagnostics pour onboarding ; Phase 8 crée le centre de diagnostic complet.

---

## `/guild/:guildId/audit`

**Rôle attendu** : initiateur, date, action, cible, plan, corrélation, résultat, drift et chemin vers le détail.

**État actuel** :

- date ;
- event type ;
- target type/id ;
- result state ;
- **HTTP 500 observé dans le parcours réel** ;
- initiateur/plan/corrélation ne sont pas réellement valorisés dans la vue.

**Décision** : endpoint/runtime à stabiliser Phase 2, expérience complète Phase 8.

---

## `/guild/:guildId/templates`

**Rôle attendu** : parcourir/prévisualiser/créer/utiliser des modèles.

**État actuel** : cartes lecture seule `name + type`.

**Problème runtime** : 503 `PORTABILITY_NOT_CONFIGURED` observé lorsque la couche de chiffrement artifact n'est pas configurée.

**Décision** : non fonctionnel comme use case produit. Phase 6.

---

## `/guild/:guildId/library`

**Rôle attendu** : bibliothèque personnelle user-scoped : sauvegarder, prévisualiser, importer, cloner, exporter, gérer.

**État actuel** :

- liste ;
- export fichier ;
- pas de vrai workflow de réutilisation/import depuis cet écran ;
- 503 observé sans portability configurée.

**Décision** : Phase 6.

---

## `/guild/:guildId/clone`

**Rôle attendu** : copie/clonage visuel source -> destination avec mappings/conflits/modes.

**État actuel** :

- type source ;
- **ID source saisi à la main** ;
- serveur destination ;
- preview ;
- résultat = plan ID.

**Écart** : ce n'est pas le « truc le plus simple pour créer et administrer un serveur ». Le pipeline backend peut rester, mais l'UI doit devenir un wizard visuel alimenté par l'explorateur.

**Décision** : Phase 6.

---

## `/guild/:guildId/translations`

**Rôle attendu** : topologie multilingue complète.

**État actuel** : écran fonctionnellement riche :

- langues ;
- groupes ;
- routes ;
- providers ;
- variantes ;
- drift ;
- targets langue ;
- right-drag ;
- create/link/clone/preview.

**Écart** : UX dense, peu visuelle, pas encore requalifiée live. Le code métier frontend a de la valeur et doit être préservé derrière une nouvelle présentation.

**Décision** : Phase 7.

---

## `/guild/:guildId/campaigns`

**Rôle attendu** : création et publication multi-Guild / planifiée / traduite / Discord-safe.

**État actuel** : substrat très large :

- create/edit ;
- allowed mentions ;
- embeds/components ;
- targets channel/logical/translation ;
- multi-Guild ;
- planning ;
- simulation ;
- variants ;
- deliveries ;
- intervention/requeue/edit/delete.

**Écart** : monolithe d'écran très complexe, à simplifier radicalement sans perdre les fonctions.

**Décision** : conserver logique/use cases, nouvelle UX Phase 7.

---

# Surfaces manquantes ou insuffisantes malgré l'existence des routes

## Onboarding §5.4

**ABSENT** comme vraie expérience. À créer Phase 2.

## Accueil / vue d'ensemble serveur

Le shell saute presque directement dans Structure. `Esquisse 1.png` prévoit une identité serveur et une expérience beaucoup plus riche. À créer Phase 2.

## Administration réelle des rôles

**ABSENTE** du frontend actuel. Phase 4.

## Édition réelle des permissions

**ABSENTE** du frontend actuel. Phase 4.

## Cartographie bots lecture/écriture (`REQ-BOT-005`)

**ABSENTE**. Phase 8.

## Preview/impact universels

Partiels et dispersés. Phase 5 doit unifier le langage visuel des plans.

## Gestion portable réellement utilisable

Présence d'API/écrans ≠ use case fini. Phase 6.

---

# Use cases d'acceptance cible par surface

| UC | Parcours | Écrans concernés | Phase |
|---|---|---|---|
| UC-001 | Base vierge -> OAuth -> A/B -> onboarding -> import -> ACTIVE | login, guilds, onboarding | 2 |
| UC-002 | Ouvrir A -> structure réelle -> sélectionner -> modifier -> plan -> apply -> vérifier -> reload | structure, plans, audit | 3 + 5 |
| UC-003 | Drag salon -> catégorie -> overlay/drop -> preview -> apply -> Discord -> UI | structure, plans | 3 + 5 |
| UC-004 | Right-drag -> menu valide filtré -> action -> résultat | structure / translation | 3 + 7 |
| UC-005 | Copier A -> B -> mapping -> preview -> apply B -> A inchangé | structure, clone, plans | 6 |
| UC-006 | Mode simple permissions -> modifier -> impact -> apply -> View As | roles/permissions/plans | 4 + 5 |
| UC-007 | Sauvegarder sélection -> bibliothèque -> réutiliser sur B | structure/library/clone | 6 |
| UC-008 | Translation group -> ajouter/lier/cloner variante -> vérifier topology | translations/plans | 7 |
| UC-009 | Campagne -> simulation -> preview langue -> planifier/envoyer -> delivery | campaigns | 7 |
| UC-010 | Changement direct Discord -> UI live/reconcile -> audit/drift | structure/audit/diagnostics | 3 + 8 |
| UC-011 | Perte permission bot -> action désactivée + cause/remédiation | diagnostics + écran concerné | 2 + 8 |
| UC-012 | Changer FR/EN/DE/ES -> aucun mélange/fallback silencieux | toutes | 8 |

# Décision Phase 1

Aucune route actuelle n'est considérée « finie » simplement parce qu'elle existe. Les écrans sont désormais classés en trois catégories :

1. **logique à conserver, présentation à refaire** : Plans, Translations, Campaigns, une partie de Structure/Interaction ;
2. **écran trop partiel pour être conservé tel quel** : GuildSelect, Roles, Permissions, Diagnostics, Audit, Templates, Library, Clone ;
3. **socle à réparer avant tout** : démarrage local, découverte Gateway, onboarding, structure initiale, WebSocket, portability config.
