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
Status: TODO
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
Implementation: non commencée.
Files: à déterminer.
Packages: Mantine Core, Lucide React, Motion.
Tests executed: aucun.
Visual evidence: capture utilisateur 22/09/2026.
Commit: none.
Known limitations: none.
NEXT EXACT ACTION: inclure cet écran dans les prototypes visuels Phase 1 avant code.

### UX1-T002 — Simplifier radicalement l'écran Rôles
Status: TODO
Purpose: rendre les rôles compréhensibles sans connaissance Discord.
User problem: l'écran expose ID Discord, position brute, fraîcheur, bitfield, capacité
bot inconnue et une grille de boutons indisponibles.
Requirements:
- nom/couleur/membres/usage humain d'abord ;
- hiérarchie visuelle ;
- actions contextuelles ;
- détails Discord repliés ;
- boutons indisponibles masqués ou expliqués sans bruit.
Implementation: non commencée.
Files: à déterminer.
Packages: Mantine Core, Lucide.
Tests executed: aucun.
Visual evidence: capture utilisateur 22/09/2026.
Commit: none.
Known limitations: none.
NEXT EXACT ACTION: prototype Rôles dans la nouvelle vue "Construire" ou "Accès".

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
Status: TODO
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
Implementation: non commencée.
Files: à déterminer.
Packages: Mantine AppShell/NavLink/Drawer, Lucide.
Tests executed: aucun.
Visual evidence: captures desktop/mobile utilisateur.
Commit: none.
Known limitations: none.
NEXT EXACT ACTION: produire le nouveau shell desktop + mobile.

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
Status: TODO
Purpose: donner la priorité au contenu.
User problem: la capture mobile montre pratiquement uniquement la sidebar permanente.
Requirements:
- sidebar non permanente ;
- Drawer ou navigation compacte ;
- contenu plein écran ;
- CTA atteignables ;
- aucune table desktop compressée ;
- aucun menu hors viewport.
Implementation: non commencée.
Files: à déterminer.
Packages: Mantine AppShell/Drawer, hooks responsive.
Tests executed: aucun.
Visual evidence: capture mobile utilisateur 22/09/2026.
Commit: none.
Known limitations: none.
NEXT EXACT ACTION: prototype mobile obligatoire au gate de départ.

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
Status: IN_PROGRESS
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
Les anciens tokens `--did-*` sont temporairement mappés vers les nouveaux tokens
Bunny pour permettre une migration progressive sans casser les écrans métier.
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
Visual evidence: les 9 références canoniques ont été inspectées en résolution
originale avant modification. Tentative de vérification locale le 22/09/2026 :
frontend démarré sur `http://localhost:8000` et réponse HTTP 200, mais aucune
instance du navigateur intégré n'est disponible dans la session (`browsers.list()`
vide). Aucune validation visuelle n'est donc revendiquée ; elle reste obligatoire
avant DONE.
Commit: inventaire `469ec20`; fondation `2614f46`, poussée sur
`origin/ui/complete-redesign`.
Known limitations: migration progressive requise ; AppShell et écrans conservent
encore leur structure/CSS historiques jusqu'aux tâches dédiées. Preuve visuelle
locale bloquée par l'absence d'une instance navigateur, pas par l'application.
NEXT EXACT ACTION: démarrer l'application sur l'URL locale canonique, vérifier
visuellement la fondation sur desktop et mobile, corriger toute régression réelle,
puis commit/push avant de passer au shell canonique.

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
NEXT EXACT ACTION: UX1-T009 — inventorier les primitives UI maison puis installer la
stack canonique ; en parallèle préparer le shell correspondant exactement aux
captures validées.

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

Current implementation status: la fondation Mantine 9/Lucide/Motion et le thème
Bunny multi-accent sont intégrés et poussés au commit `2614f46`. Les primitives
standard partagées sont migrées vers Mantine ; build, lint ciblé et 9 tests ciblés
sont verts. La vérification visuelle réelle reste le dernier gate avant de fermer
UX1-T009. Le navigateur intégré n'est pas connecté dans cette session.

Active task: `UX1-T009` — standardisation de la stack UI, vérification visuelle en cours.

NEXT EXACT ACTION:

1. connecter une instance du navigateur intégré à cette session ;
2. redémarrer l'application sur `http://localhost:8000` si nécessaire ;
3. vérifier la fondation en navigateur desktop puis mobile ;
4. corriger toute régression visuelle ou interactionnelle observée ;
5. mettre à jour ce tracker avec les preuves, fermer UX1-T009 seulement si le rendu
   est valide, puis commencer le shell canonique desktop/mobile.
