# Bunny Server Assistant — UI Implementation Live State

> **Statut : CANONIQUE — SOURCE DE VÉRITÉ OPÉRATIONNELLE**
>
> Ce fichier est le handoff temps réel entre Claude, Codex et toute autre IA.
>
> Aucun état critique ne doit rester uniquement dans une conversation.

## Références canoniques

- `SCREENSHOTS_ESQUISSE/UI_UX_CANONICAL_REFERENCE.md`
- `SCREENSHOTS_ESQUISSE/UI_IMPLEMENTATION_3_PHASES.md`
- `SCREENSHOTS_ESQUISSE/UI_PHASE1_MASTER_EXECUTION_PROMPT.md` — prompt maître obligatoire pour toute IA qui code la Phase 1

Les anciens documents `UI_REDESIGN_PHASES.md` et
`UI_PHASE_EXECUTION_STATE.md` sont historiques.

## Branche

`ui/complete-redesign`

## Baseline produit avant reset UX

`08ad925ce7dbc24e4fed9e8c8e470b953c0c6786`

Phase 4 historique était techniquement fermée à ce SHA, mais l'acceptation humaine
du 22/09/2026 a rejeté la qualité UX globale. Le nouveau chantier UI reprend donc
à partir de cette baseline sans nier le travail backend déjà livré.

## Grande phase active

**Phase 1 — RESET VISUEL ET COMPRÉHENSION IMMÉDIATE**

Status: IN_PROGRESS — VISUAL_DIRECTION_APPROVED

Aucune Phase 2 ou Phase 3 ne doit commencer avant validation humaine explicite du
gate Phase 1.

---

# Règles de suivi

## Statuts

- TODO
- IN_PROGRESS
- DONE
- BLOCKED
- DEFERRED

## Format obligatoire d'une tâche

```text
### UX1-Txxx — Titre
Status:
Purpose:
User problem:
Requirements:
Implementation:
Files:
Packages:
Tests executed:
Visual evidence:
Commit:
Known limitations:
NEXT EXACT ACTION:
```

## Mise à jour obligatoire

Mettre à jour ce fichier :

- avant de commencer une tâche ;
- après une tâche significative ;
- avant un commit important ;
- après validation ;
- avant toute interruption de tokens/contexte ;
- avant de passer d'une IA à une autre.

## Interdictions

- aucune nouvelle "phase 1.1" ;
- aucun "Lot A/B/C" ;
- aucun nouveau roadmap parallèle ;
- aucune tâche marquée DONE sur la seule base de tests ;
- aucune réécriture d'un composant standard si un package approuvé le couvre.

---

# Audit humain du 22/09/2026 — défauts initiaux

Les constats ci-dessous proviennent d'une validation manuelle réelle sur
`08ad925...`.

### UX1-T001 — Reconcevoir l'accueil pour un utilisateur novice
Status: DONE
Purpose: supprimer la première impression de console technique.
User problem: la première page affiche Structure, Rôles, couverture cache, connexion
temps réel et huit capacités bot en `UNKNOWN`. Un utilisateur lambda ne comprend
ni ce que cela signifie ni ce qu'il doit faire.
Requirements:
- aucune donnée cache/provenance au premier niveau ;
- aucun mur de UNKNOWN ;
- santé globale en langage humain ;
- 3 à 5 actions utiles maximum ;
- alertes actionnables ;
- détails techniques sur demande.
Implementation: l'Accueil canonique est intégré au shell Bunny. Il traduit les
lectures cache-first Structure/Rôles/capacités en un état de santé humain, cinq
actions rapides, quatre statistiques lisibles et un parcours de démarrage. La
provenance, la couverture et la fraîcheur ne sont plus exposées au premier niveau :
elles restent disponibles dans un Accordion « Détails techniques ». Le hero utilise
une illustration Bunny originale pastel, sans texte ni marque tierce.
Files: `frontend/src/features/overview/OverviewScreen.tsx`,
`frontend/src/shared/bunny-shell.css`, `frontend/src/assets/bunny-home-hero.png`,
`frontend/src/localization/phase2Catalog.ts`.
Packages: Mantine Core, Lucide React, Motion.
Tests executed: `npm.cmd run build` PASS ; `npm.cmd run i18n:check` PASS (scan des
libellés + 3 tests catalogue) ; ESLint ciblé des fichiers modifiés PASS ;
`npm.cmd run test -- --run src/app/App.test.tsx src/features/structure/StructureScreen.test.tsx src/features/wizards/core/RoleMultiSelect.test.tsx` PASS, 3 fichiers / 9 tests.
Visual evidence: capture Chromium réelle et inspection image par image de l'Accueil
en 1440x1000 et 390x844. Hero, actions rapides, santé, statistiques, checklist et
détails repliés sont lisibles ; aucune donnée interne brute au premier niveau ;
aucun débordement horizontal à 390 px. Le navigateur intégré n'étant pas disponible,
ce contrôle Playwright inspecté n'est pas présenté comme une validation humaine.
Commit: `0dd8646`.
Known limitations: les destinations ouvertes par l'Accueil conservent leur UI
historique jusqu'à leurs tâches Phase 1 dédiées.
NEXT EXACT ACTION: UX1-T002 — simplifier l'écran Rôles dans la direction canonique.

### UX1-T002 — Simplifier radicalement l'écran Rôles
Status: DONE
Purpose: rendre les rôles compréhensibles sans connaissance Discord.
User problem: l'écran expose ID Discord, position brute, fraîcheur, bitfield, capacité
bot inconnue et une grille de boutons indisponibles.
Requirements:
- nom/couleur/membres/usage humain d'abord ;
- hiérarchie visuelle ;
- actions contextuelles ;
- détails Discord repliés ;
- boutons indisponibles masqués ou expliqués sans bruit.
Implementation: l'ancien workbench sombre a été remplacé par la présentation
canonique claire : familles Administration/Modération/Communauté/Bots, cartes
pastel, recherche et filtres, usage humain déduit des permissions connues, sélection
visuelle, détail contextuel et actions réellement disponibles uniquement. ID,
position, fraîcheur, bitfield et flags sont désormais repliés dans un Accordion
« Détails Discord ». La création et les actions de renommage/réordonnancement/
suppression utilisent des composants Mantine et conservent intégralement le chemin
DSG/Plan existant. Le rôle bot historique est présenté comme Bunny, sans exposer DID.
La vue se recompose en une liste pleine largeur puis une fiche tactile sur mobile.
Files: `frontend/src/features/roles/RolesScreen.tsx`,
`frontend/src/shared/bunny-roles.css`,
`frontend/src/localization/bunnyRolesCatalog.ts`,
`frontend/src/localization/runtime.tsx`, `frontend/src/main.tsx`,
`frontend/src/features/roles/RolesScreen.test.tsx`,
`frontend/e2e/phase04-access.spec.ts`,
`frontend/e2e/ux1-roles-visual.spec.ts`, ce tracker.
Packages: Mantine Core, Lucide.
Tests executed: `npm.cmd run build` PASS avec
`NODE_OPTIONS=--max-old-space-size=8192` (le premier lancement sans cette limite a
seulement épuisé le heap Node local) ; ESLint ciblé des fichiers Rôles/i18n/E2E PASS ;
`npm.cmd run i18n:check` PASS (scan + 3 tests catalogue) ;
`npm.cmd run test -- --run src/features/roles/RolesScreen.test.tsx` PASS, 6/6 ;
`npx.cmd playwright test e2e/ux1-roles-visual.spec.ts --project=chromium` PASS, 1/1 ;
`npx.cmd playwright test e2e/phase04-access.spec.ts --project=chromium --grep
"role hierarchy prepares"` PASS, 1/1. Aucun test backend lancé.
Visual evidence: captures Chromium Playwright réelles générées puis inspectées en
1440x1000, 390x844 liste et 390x844 détail. Les familles pastel, la hiérarchie, les
libellés, le contraste, les actions, l'Accordion technique et la navigation basse
sont lisibles ; aucun débordement horizontal. Le navigateur intégré n'était pas
disponible ; cette inspection image par image n'est pas présentée comme une nouvelle
validation humaine utilisateur.
Commit: commit de code à renseigner après création.
Known limitations: l'endpoint cache-first Rôles ne fournit actuellement ni couleur
Discord ni compteur de membres. L'UI utilise donc des accents fonctionnels par
famille et n'invente aucun compteur ; aucune extension backend n'a été introduite
pour cette tâche visuelle.
NEXT EXACT ACTION: UX1-T003 — passer la tâche à IN_PROGRESS, inspecter l'écran Accès
actuel dans le shell canonique puis reconstruire le parcours d'intention selon les
maquettes, sans modifier les invariants Policy/Plan.

### UX1-T003 — Remplacer le mur "Politiques d'accès" par un parcours d'intention
Status: TODO
Purpose: permettre de configurer l'accès sans comprendre Policy/roles/scopes.
User problem: catalogue très dense, textes longs, métadonnées répétées, panneau
d'édition lourd et plus de vingt checkboxes de rôles visibles simultanément.
Requirements:
- intentions humaines ;
- recherche + multi-select + chips ;
- presets visuels ;
- phrase de résultat ;
- impact simple ;
- détails avancés repliés ;
- pas de répétition serveur/catalogue sur chaque carte.
Implementation: non commencée.
Files: à déterminer.
Packages: Mantine Core/Form, Spotlight/Combobox patterns, Lucide, Motion.
Tests executed: aucun.
Visual evidence: capture utilisateur 22/09/2026.
Commit: none.
Known limitations: none.
NEXT EXACT ACTION: inclure un prototype Accès complet au gate visuel de démarrage.

### UX1-T004 — Refaire la navigation principale par intention
Status: DONE
Purpose: supprimer le menu qui reflète l'architecture interne.
User problem: Vue d'ensemble, Structure, Rôles, Permissions, Politiques d'accès,
Matrice, Assistants, Plans, Diagnostics, Audit, Traductions et Campagnes apparaissent
comme autant de destinations de même niveau.
Requirements:
- Accueil ;
- Construire ;
- Accès ;
- Automatiser ;
- Activité ;
- mode expert pour raccourcis techniques.
Implementation: le shell Mantine expose désormais uniquement Accueil, Construire,
Accès, Automatiser et Activité dans la navigation principale. Les routes métier
existantes sont conservées et les raccourcis techniques sont regroupés dans
« Outils avancés ». La sidebar claire inclut le branding Bunny, le serveur actif,
l'aide et le compte ; la top bar conserve recherche, état de connexion, langue et
compte. Les invariants de session, tenant, capabilities et websocket sont préservés.
Files: `frontend/src/app/AppShell.tsx`, `frontend/src/shared/bunny-shell.css`,
`frontend/src/main.tsx`, catalogues i18n et libellés produit associés.
Packages: Mantine AppShell/NavLink/Drawer, Lucide.
Tests executed: mêmes contrôles ciblés que UX1-T001 ; aucun test backend.
Visual evidence: capture Chromium 1440x1000 inspectée : sidebar courte, état actif,
top bar et zone de contenu conformes à la hiérarchie des captures canoniques.
Commit: `0dd8646`.
Known limitations: les écrans métier non encore migrés restent accessibles dans ce
nouveau shell mais gardent temporairement leur présentation historique.
NEXT EXACT ACTION: UX1-T002 — migrer Rôles sans réintroduire la navigation technique.

### UX1-T005 — Introduire un vrai système visuel multi-couleur
Status: TODO
Purpose: sortir du bleu nuit/violet uniforme.
User problem: zones difficiles à distinguer, bordures trop faibles, presque aucune
couleur fonctionnelle, interface austère.
Requirements:
- palette multi-accent canonique ;
- surfaces nettement séparées ;
- clair/sombre/système ;
- contrastes accessibles ;
- couleurs par domaine ;
- statuts sémantiques lisibles.
Implementation: non commencée.
Files: à déterminer.
Packages: Mantine theme + CSS variables.
Tests executed: aucun.
Visual evidence: toutes les captures utilisateur 22/09/2026.
Commit: none.
Known limitations: none.
NEXT EXACT ACTION: définir les tokens et les intégrer aux prototypes.

### UX1-T006 — Réduire la verbosité et appliquer la divulgation progressive
Status: TODO
Purpose: éviter le sentiment de fourre-tout.
User problem: presque chaque carte explique tout en permanence.
Requirements:
- une phrase de contexte max ;
- tooltips/popovers/drawers pour explications ;
- détails techniques repliés ;
- suppression des métadonnées répétées ;
- maximum 3 actions principales/secondaires visibles au-dessus de la ligne de
  flottaison.
Implementation: non commencée.
Files: transversal.
Packages: Mantine Tooltip/Popover/Accordion/Drawer.
Tests executed: aucun.
Visual evidence: captures utilisateur 22/09/2026.
Commit: none.
Known limitations: none.
NEXT EXACT ACTION: appliquer lors de chaque refonte d'écran, pas via un composant
"info" supplémentaire.

### UX1-T007 — Refaire l'expérience mobile
Status: DONE
Purpose: donner la priorité au contenu.
User problem: la capture mobile montre pratiquement uniquement la sidebar permanente.
Requirements:
- sidebar non permanente ;
- Drawer ou navigation compacte ;
- contenu plein écran ;
- CTA atteignables ;
- aucune table desktop compressée ;
- aucun menu hors viewport.
Implementation: sous le breakpoint desktop, la sidebar disparaît au profit d'un
header compact, d'un Drawer Mantine et d'une navigation basse à cinq intentions.
L'Accueil passe en contenu plein écran, les CTA du hero s'empilent et les cartes se
recomposent sans table desktop comprimée.
Files: `frontend/src/app/AppShell.tsx`, `frontend/src/shared/bunny-shell.css`.
Packages: Mantine AppShell/Drawer, hooks responsive.
Tests executed: smoke Chromium Playwright ciblé PASS avec assertion explicite
`scrollWidth - clientWidth <= 1` à 390x844 ; mêmes build/lint/tests ciblés que
UX1-T001.
Visual evidence: captures Chromium 390x844 inspectées avec Drawer fermé puis ouvert :
contenu prioritaire, navigation basse lisible, Drawer entièrement dans le viewport,
aucun menu hors écran et aucun débordement horizontal.
Commit: `0dd8646`.
Known limitations: les contenus métier legacy pourront encore nécessiter leurs
propres adaptations mobiles lors de leur migration dédiée.
NEXT EXACT ACTION: UX1-T002 — appliquer ce responsive à l'écran Rôles refondu.

### UX1-T008 — Remplacer les états internes par des messages humains
Status: TODO
Purpose: supprimer UNKNOWN/FULL/FRESH/BLOCKED de l'UI novice.
User problem: les états internes deviennent le contenu principal au lieu d'aider.
Requirements:
- "À vérifier", "À jour", "Action nécessaire" ;
- cause courte ;
- action directe ;
- état interne uniquement dans Détails techniques.
Implementation: non commencée.
Files: transversal.
Packages: Mantine Alert/Badge/Tooltip.
Tests executed: aucun.
Visual evidence: accueil + rôles 22/09/2026.
Commit: none.
Known limitations: none.
NEXT EXACT ACTION: créer une table de mapping états internes -> états humains avant
migration des écrans.

### UX1-T009 — Standardiser la stack UI et supprimer les primitives maison
Status: DONE
Purpose: obtenir une qualité visuelle et interactionnelle homogène.
User problem: package.json contient très peu de composants UI dédiés ; beaucoup de
primitives sont faites à la main.
Requirements:
- Mantine 9 comme base ;
- Lucide React ;
- Motion ;
- TanStack Table/Virtual quand nécessaire ;
- dnd-kit pour drag/drop adapté ;
- aucune bibliothèque concurrente sans justification.
Implementation: inventaire initial terminé. `frontend/src/shared/components/ui.tsx`
réimplémentait en 82 lignes 17 exports standards. La fondation canonique est
maintenant installée : thème Bunny multi-accent, tokens clair/sombre, providers
Mantine/Modals/Notifications et styles packages au point d'entrée. Les adaptateurs
Button/IconButton, Input, Select, Badge, Skeleton, Empty/Error states, Progress,
Dialog/AlertDialog, Tooltip, Toast et Menu/MenuItem reposent désormais sur Mantine ;
les icônes de statut reposent sur Lucide. Tree/TreeItem restent volontairement
spécifiques pour préserver la navigation clavier et la hiérarchie Discord. Le menu
contextuel conserve son ancrage aux coordonnées tout en exposant un nom accessible.
Les tokens Bunny clairs restent la cible des nouveaux écrans. Le pont `--did-*`
conserve désormais des couples surface/texte cohérents pour les écrans sombres non
encore migrés, afin d'éviter les contrastes cassés pendant la transition. Les
adaptateurs Badge autorisent les libellés longs sans troncature et les contrôles
désactivés restent lisibles. Le statut sans libellé est masqué sur très petit écran.
Le `className` du Dialog est appliqué au contenu Mantine au lieu de la racine Modal,
ce qui supprime la barre vide qui apparaissait en bas des pages.
Files: `frontend/package.json`, `frontend/package-lock.json`,
`frontend/src/app/theme.ts`, `frontend/src/app/providers/AppProviders.tsx`,
`frontend/src/shared/bunny-theme.css`, `frontend/src/shared/components/ui.tsx`,
`frontend/src/main.tsx`, `frontend/src/test/setup.ts`,
`frontend/src/test/BunnyTestProvider.tsx`, tests Structure et RoleMultiSelect.
Packages: `@mantine/core`, `@mantine/hooks`, `@mantine/form`, `@mantine/modals`,
`@mantine/notifications`, `@mantine/dates`, `@mantine/spotlight`,
`@mantine/nprogress` 9.6.2 ; `lucide-react` 1.47.0 ; `motion` 13.4.0 ;
`dayjs` 1.11.23. React Query, Zustand et i18next sont conservés.
Tests executed: `npm.cmd run build` PASS ; ESLint ciblé des fondations/tests PASS ;
`npm.cmd run test -- --run src/app/App.test.tsx src/features/structure/StructureScreen.test.tsx src/features/wizards/core/RoleMultiSelect.test.tsx` PASS, 3 fichiers et 9 tests. Premier passage : 9 échecs dus à `matchMedia`/provider absents ; second passage : 7/9 après correction du harness ; troisième passage : 9/9 après correction du nom accessible du Menu. Aucune assertion affaiblie.
Après correction des régressions : nouveau `npm.cmd run build` PASS (typecheck +
build), `npx.cmd eslint src/shared/components/ui.tsx` PASS, mêmes 3 fichiers / 9
tests PASS. Smoke visuel Chromium ciblé sur sélection serveur, vue d'ensemble et
Rôles en 1440x1000 puis 390x844 : PASS ; aucune suite backend lancée.
Visual evidence: les 9 références canoniques ont été inspectées en résolution
originale avant modification. Une validation visuelle réelle a ensuite été fournie
par l'utilisateur le 22/09/2026 sur `http://localhost:8000` avec captures desktop
sélection serveur / vue d'ensemble / rôles et captures mobile vue d'ensemble / rôles.
Cette validation montre que la fondation est fonctionnelle mais **pas encore
visuellement acceptable pour clôturer UX1-T009**. Régressions/écarts observés à
corriger avant DONE :
- cartes de sélection serveur : noms et textes presque illisibles (texte sombre sur
  surface sombre), badge du second serveur tronqué ;
- top bar desktop : au moins un contrôle apparaît comme un rectangle blanc vide ;
- vue d'ensemble : plusieurs textes/valeurs ont un contraste insuffisant sur les
  cartes sombres ;
- rôles : panneau de détail et boutons désactivés héritent de styles gris/sombres
  difficilement lisibles ;
- mobile : header ancien encore très dégradé (recherche sur deux lignes, contrôle
  vert vide, densité excessive) et mise en page trop proche du shell historique.
Les éléments purement structurels de l'ancienne UI (UNKNOWN, navigation technique,
sidebar, cartes legacy) seront refondus par UX1-T001/T002/T004/T007/T008 ; ils ne
sont pas à traiter ici comme si UX1-T009 devait déjà reproduire les 9 maquettes.
En revanche, les défauts de contraste, contrôles vides et styles Mantine/legacy
cassés sont des régressions de fondation et doivent être corrigés maintenant.
La vérification corrective par inspection des captures générées confirme : noms et
valeurs lisibles sur les surfaces sombres, contrôle de déconnexion de nouveau
visible, badge long non tronqué, panneau Rôles lisible, aucun contrôle de statut vide
à 390 px et aucune barre Modal fantôme. Le navigateur intégré n'était pas disponible ;
la preuve a donc été produite avec le Chromium Playwright du projet et inspectée
image par image. Ce n'est pas présenté comme une nouvelle validation humaine
utilisateur.
Commit: inventaire `469ec20`; fondation `2614f46`; correctif final
`4206ed172c7579691fe199c4811bd6361d67f8d4`.
Known limitations: les écrans métier historiques restent à migrer tâche par tâche ;
le shell, le responsive global et l'Accueil sont désormais traités par
UX1-T004/UX1-T007/UX1-T001.
NEXT EXACT ACTION: aucune pour cette tâche fermée ; suivre la tâche active du handoff.

### UX1-T010 — Corriger l'URL canonique du dev OAuth
Status: TODO
Purpose: empêcher le faux échec `OAUTH_STATE_INVALID` en local.
User problem: `scripts/dev.sh` annonce `localhost:8000` mais Vite affiche
`127.0.0.1:8000`; le cookie de browser binding n'est pas partagé entre ces deux
hôtes.
Requirements:
- une seule URL locale canonique ;
- message de démarrage cohérent ;
- OAuth callback sur le même hostname ;
- test ciblé du comportement.
Implementation: cause reproduite et confirmée manuellement, correctif non commencé.
Files: probablement `frontend/vite.config.ts`, `scripts/dev.sh`.
Packages: aucun.
Tests executed: reproduction manuelle réelle.
Visual evidence: erreur `OAUTH_STATE_INVALID` puis succès via localhost.
Commit: none.
Known limitations: none.
NEXT EXACT ACTION: corriger dans Phase 1 sans créer de chantier séparé.

### UX1-T011 — Prototypes visuels de départ
Status: DONE
Purpose: figer la direction visuelle avant toute migration massive.
User problem: l'ancienne refonte avait été déclarée techniquement valide avant une
vraie validation humaine de l'expérience.
Requirements:
- plusieurs pages desktop ;
- Wizards ;
- Accueil ;
- Construire ;
- Accès ;
- Rôles ;
- Modifications prêtes ;
- Centre des opérations ;
- au moins une vraie proposition mobile ;
- palette multi-couleur ;
- navigation simplifiée ;
- faible verbosité.
Implementation: 9 maquettes réalistes produites puis validées explicitement par
l'utilisateur le 22/09/2026. Elles sont maintenant versionnées dans
`SCREENSHOTS_ESQUISSE/` et déclarées cible visuelle exacte par
`UI_UX_CANONICAL_REFERENCE.md`.
Files:
- tableau_de_bord_discord_pastel_en_français.png
- assistant_de_création_de_serveur_discord.png
- assistant_discord_gestion_des_accès.png
- constructeur_discord_pastel_en_français.png
- tableau_de_bord_français_des_accès_serveur.png
- gestion_pastel_des_rôles_discord.png
- modifications_prêtes_pour_votre_serveur.png
- centre_des_opérations_discord_pastel.png
- maquette_mobile_bunny_server_assistant_francais.png
Packages: la réalisation doit utiliser la stack canonique Mantine/Lucide/Motion
plutôt que recréer les primitives montrées.
Tests executed: n/a — gate humain de conception.
Visual evidence: validation utilisateur explicite : « C'est parfait ça » puis
« JE VEUX EXACTEMENT CET UI ».
Commit: captures poussées par l'utilisateur, documentation canonique synchronisée.
Known limitations: le branding textuel historique éventuellement visible dans une
capture doit être remplacé par Bunny Server Assistant / Bunny sans modifier la
direction graphique.
NEXT EXACT ACTION: aucune pour cette tâche fermée ; suivre la tâche active du handoff.

---

# Phase 1 — tâches à découvrir pendant l'implémentation

Les nouvelles tâches sont ajoutées ici uniquement si un défaut réel est observé.

Elles ne créent jamais une sous-phase.

---

# Phase 2 — backlog initial

Status global: NOT_STARTED

Les tâches atomiques détaillées ne seront créées qu'à l'approche de Phase 2 pour
éviter de figer prématurément une UX qui dépendra du résultat Phase 1.

Objectif déjà fixé : création guidée de bout en bout pour utilisateur novice.

---

# Phase 3 — backlog initial

Status global: NOT_STARTED

Objectif déjà fixé : opérations/Apply, fonctionnalités avancées, cohérence globale et
acceptation finale.

---

# Handoff courant

Last updated: 2026-09-22

Current product baseline: `08ad925ce7dbc24e4fed9e8c8e470b953c0c6786`

Current implementation status: UX1-T009, UX1-T004, UX1-T007, UX1-T001 et UX1-T002
sont fermées. La fondation, le shell canonique desktop/mobile, l'Accueil novice et
la vue Rôles canonique sont implémentés et vérifiés visuellement. Les routes métier,
lectures cache-first et chemins DSG/Plan existants sont préservés ; aucun backend
n'a été modifié.

Current code HEAD: `c8136a8` avant le commit UX1-T002 courant. Le HEAD publié final
sera le commit qui contient cette mise à jour et l'implémentation Rôles.
Worktree courant avant commit: modifications UX1-T002 listées dans la tâche.

Active task: aucune ; la prochaine tâche canonique est `UX1-T003`.

NEXT EXACT ACTION:

1. passer UX1-T003 à IN_PROGRESS avant toute modification ;
2. inspecter l'écran Accès/Politiques actuel dans le shell canonique en desktop et
   mobile ;
3. reconstruire le parcours par intention avec presets, recherche, chips, résultat
   humain, impact simple et détails avancés repliés ;
4. préserver strictement les lectures cache-first et les chemins Policy/Plan.
