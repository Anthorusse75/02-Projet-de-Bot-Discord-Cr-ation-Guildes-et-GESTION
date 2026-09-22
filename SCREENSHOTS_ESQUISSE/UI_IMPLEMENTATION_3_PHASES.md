# Bunny Server Assistant — Plan d'implémentation UI en 3 phases

> **Statut : CANONIQUE**
>
> Ce document remplace le plan historique en 9 phases pour toute nouvelle
> implémentation UI/UX.
>
> Il y a exactement **3 grandes phases**. Aucune phase 1.1/1.2, aucun "Lot A/B",
> aucune Phase 4R, aucune Phase 10.
>
> La granularité existe uniquement dans le tracker atomique
> `UI_IMPLEMENTATION_LIVE_STATE.md`.

## Références obligatoires

1. `SCREENSHOTS_ESQUISSE/UI_UX_CANONICAL_REFERENCE.md`
2. `SCREENSHOTS_ESQUISSE/UI_IMPLEMENTATION_LIVE_STATE.md`
3. `docs/00_reference/01_SPECIFICATIONS_FONCTIONNELLES_DISCORD_INFRA_DESIGNER.md`
4. `docs/00_reference/02_ARCHITECTURE_TECHNIQUE_DISCORD_INFRA_DESIGNER.md`
5. `docs/10_implementation/11_REQUIREMENTS_IMPLEMENTATION_AUDIT.md`

Les documents fonctionnels restent la vérité métier.
La référence UI canonique fixe comment cette complexité doit être présentée.

---

# Règle de pilotage

## Une phase = un seul prompt maître

Chaque grande phase est exécutée avec **un prompt maître unique**.

Si Claude, Codex ou une autre IA arrive en limite de contexte :

- elle met à jour le tracker atomique ;
- elle commit/push ce qui est sûr ;
- elle écrit `NEXT EXACT ACTION` ;
- l'IA suivante reprend sans nouveau découpage de phase.

Un changement d'IA ne crée jamais une nouvelle phase.

## Les tâches atomiques ne sont pas des sous-phases

Le tracker peut contenir 10, 30 ou 100 tâches atomiques.
Ce ne sont pas des phases et elles ne nécessitent pas un nouveau cahier des charges.

Format :

- `UX1-T001`
- `UX1-T002`
- `UX2-T001`
- `UX3-T001`

Statuts :

- TODO
- IN_PROGRESS
- DONE
- BLOCKED
- DEFERRED

## UI d'abord

Quand une tâche a une dimension UI, la séquence normale est :

1. regarder l'écran réel ;
2. déterminer l'intention utilisateur ;
3. simplifier ;
4. utiliser les composants de la stack approuvée ;
5. implémenter ;
6. vérifier visuellement ;
7. seulement ensuite compléter les tests ciblés utiles.

Le projet ne doit plus faire 800 tests pour découvrir ensuite qu'un écran est
désagréable à utiliser.

---

# Phase 1 — RESET VISUEL ET COMPRÉHENSION IMMÉDIATE

**Statut : EN COURS — direction visuelle validée le 22/09/2026**

## Objectif

Faire disparaître l'impression de console technique.

À la fin de cette phase, un utilisateur novice doit pouvoir ouvrir l'application et
comprendre en moins d'une minute :

- où il est ;
- ce qu'il peut faire ;
- où créer/modifier son serveur ;
- où gérer les accès ;
- où voir ses changements.

## Gate de départ — ✅ VALIDÉ LE 22/09/2026

La direction visuelle a été validée explicitement par l'utilisateur.

Les 9 screenshots présents dans `SCREENSHOTS_ESQUISSE/` sont désormais la cible
visuelle exacte définie dans `UI_UX_CANONICAL_REFERENCE.md`.

Il n'est plus nécessaire de produire d'autres propositions avant de coder.
L'implémentation doit partir de ces captures et leur rester fidèle.

## Travail obligatoire

### Fondation UI

- installer Mantine 9 et les packages approuvés nécessaires ;
- créer le thème multi-accent ;
- supporter clair/sombre/système ;
- standardiser boutons, badges, cards, modals, drawers, menus, tooltips,
  notifications, forms, stepper, loaders, skeletons ;
- supprimer progressivement les primitives UI maison redondantes ;
- normaliser spacing, typography, radius, elevation, focus, motion.

### Shell / navigation

Refondre la navigation autour de :

- Accueil ;
- Construire ;
- Accès ;
- Automatiser ;
- Activité.

Les anciennes routes techniques peuvent rester mais ne doivent plus saturer la
navigation novice.

### Accueil

Supprimer du premier niveau :

- cache local ;
- FULL/FRESH ;
- murs de UNKNOWN ;
- capacités du bot détaillées.

Remplacer par :

- santé simple ;
- raccourcis d'action ;
- alertes réellement utiles ;
- continuation d'une tâche en cours ;
- activité récente concise.

### Construire

Transformer Structure/Rôles/Permissions en expérience cohérente :

- structure visuelle claire ;
- sélection simple ;
- propriétés utiles ;
- édition contextuelle ;
- rôles présentés humainement ;
- détails Discord repliés ;
- DnD via package standard lorsque possible sans régression métier.

### Accès

Fusionner conceptuellement le labyrinthe actuel Rôles / Permissions /
Politiques d'accès / Matrice en une expérience orientée intention.

Par défaut :

- qui voit ?
- qui écrit ?
- qui gère ?
- accès temporaire ?
- espace privé/public/staff ?

La matrice et les traces de résolution deviennent des outils avancés.

### Mobile

- supprimer la sidebar permanente ;
- utiliser Drawer/navigation compacte ;
- aucune vue desktop simplement compressée ;
- CTA principal accessible ;
- menus/popovers dans viewport ;
- tables remplacées par cartes/listes ou horizontal scroll explicite quand nécessaire.

### Auth local

Corriger la confusion `localhost` / `127.0.0.1` dans le démarrage local afin
qu'un utilisateur développeur ne puisse pas déclencher involontairement
`OAUTH_STATE_INVALID` en cliquant l'URL affichée.

## Gate de sortie Phase 1

La phase ne peut être déclarée DONE que si l'utilisateur valide visuellement :

- Accueil desktop/mobile ;
- Construire desktop/mobile ;
- Accès desktop/mobile ;
- navigation ;
- états loading/empty/error/à vérifier ;
- thème/couleurs ;
- densité/verbosité.

Aucun passage en Phase 2 sur la seule base de Playwright.

---

# Phase 2 — CRÉATION GUIDÉE DE BOUT EN BOUT

**Statut initial : À FAIRE**

## Objectif

Permettre à une personne qui ne maîtrise pas Discord de construire un serveur
complexe sans devoir apprendre l'architecture interne de Discord Infrastructure
Designer.

Le produit doit guider par intention et générer derrière les rôles, règles et Plans
nécessaires.

## Parcours cible principal

```text
Je veux créer / modifier mon serveur
        ↓
Quel type d'espace ?
        ↓
Qui doit y accéder ?
        ↓
Que peuvent-ils faire ?
        ↓
Options utiles
        ↓
Aperçu visuel du résultat
        ↓
Résumé simple de l'impact
        ↓
Préparer les changements
```

## Travail obligatoire

- assistants unifiés ;
- création de catégories/salons ;
- presets réellement compréhensibles ;
- rôles manquants créés/proposés dans le flow ;
- accès public/privé/staff/membres confirmés ;
- ANY/ALL/NOT masqués derrière formulations humaines ;
- accès temporaires avec choix de durée convivial ;
- conflits expliqués avec une phrase et des solutions concrètes ;
- suggestions intelligentes mais jamais appliquées sans confirmation ;
- preview visuelle avant Plan ;
- recherche/multi-select moderne au lieu de murs de checkboxes ;
- duplication/réutilisation de configurations ;
- templates de départ lorsque le backend le permet ;
- contexte d'aide court et local ;
- onboarding réécrit pour montrer le bénéfice, pas l'infrastructure.

## Progressive disclosure obligatoire

Le flow novice ne montre pas :

- Policy IDs ;
- scopes ;
- overwrite decimals ;
- bitfields ;
- provenance ;
- states internes.

Un bouton « Détails techniques » expose ces informations sans changer la décision.

## Gate de sortie Phase 2

Validation humaine réelle de plusieurs parcours :

- serveur simple ;
- espace privé ;
- espace staff ;
- accès temporaire ;
- conflit de rôles ;
- mobile ;
- retour arrière/reprise.

Critère essentiel :

> une personne qui ne connaît pas les permissions Discord doit pouvoir expliquer ce
> qu'elle vient de configurer.

---

# Phase 3 — OPÉRATIONS, FONCTIONS AVANCÉES ET ACCEPTATION FINALE

**Statut initial : À FAIRE**

## Objectif

Rendre tout le reste du produit cohérent avec la nouvelle expérience et fermer le
produit sur une vraie validation humaine + fonctionnelle.

## Travail obligatoire

### Changements / Plans / Apply

Transformer le pipeline technique :

`INTENTION → PLAN → APPLY → VERIFICATION`

en expérience lisible :

- « Modifications prêtes » ;
- résumé humain ;
- impact ;
- risques seulement si utiles ;
- confirmation ;
- progression ;
- succès vérifié ;
- retry ;
- intervention requise ;
- reprise après refresh/session.

### Activité / Operations Center

Une seule zone compréhensible pour :

- modifications prêtes ;
- opérations en cours ;
- erreurs ;
- historique ;
- audit.

Les détails de Plan restent disponibles, mais ne sont pas le niveau principal.

### Bibliothèque / clonage / portabilité

Rendre utilisables :

- templates ;
- bibliothèque ;
- clone serveur A → B ;
- mappings ;
- import/export ;
- adaptation à la cible.

### Automatisations

Refondre :

- traductions ;
- groupes de langues ;
- campagnes ;
- planification ;
- statuts ;
- erreurs.

Même design system, même langage, mêmes patterns.

### Diagnostics et paramètres

Les diagnostics deviennent actionnables :

- problème ;
- conséquence ;
- action recommandée ;
- détail technique facultatif.

### Finition globale

- accessibilité clavier ;
- contrastes ;
- thèmes ;
- responsive ;
- i18n EN/FR/DE/ES ;
- command palette ;
- notifications ;
- micro-interactions ;
- cohérence iconographique ;
- suppression des derniers composants UI maison inutiles.

## Acceptation finale

Une seule vraie campagne finale large :

- parcours local complet ;
- OAuth réel ;
- serveur sandbox ;
- création/modification ;
- accès ;
- Plan ;
- Apply ;
- vérification ;
- reprise ;
- templates/clone ;
- traduction/campagne ;
- audit/activité ;
- desktop ;
- mobile.

Puis validation visuelle humaine explicite.

---

# Doctrine de tests

## Ce qu'on teste

- logique métier modifiée ;
- sécurité/RLS/RBAC ;
- persistance ;
- mutation Discord ;
- parcours utilisateur critique ;
- régression d'un composant partagé.

## Ce qu'on ne fait plus

- relancer des centaines de tests backend pour un changement de padding ;
- considérer une page belle parce que Playwright trouve les boutons ;
- écrire trois tests différents qui prouvent la même chose ;
- remplacer la validation humaine par un score axe ou un screenshot automatisé.

## Minimum UI utile

Pour un changement purement visuel :

- typecheck ;
- lint pertinent ;
- i18n si wording ;
- screenshot réel desktop/mobile ;
- validation visuelle.

## Régression large

Une seule fois à un checkpoint réellement utile :

- fin Phase 1 si le shell partagé a fortement changé ;
- fin Phase 3 pour l'acceptation finale.

Pas une campagne massive après chaque tâche atomique.

---

# Règle de commit / handoff

Après chaque tâche atomique significative :

- mettre à jour `UI_IMPLEMENTATION_LIVE_STATE.md` ;
- commit atomique ;
- push régulier.

Avant toute interruption :

- HEAD ;
- worktree ;
- tâche active ;
- fichiers ;
- ce qui est fait ;
- tests déjà exécutés ;
- tests restants ;
- captures/validation visuelle ;
- `NEXT EXACT ACTION`.

Une nouvelle IA ne doit jamais avoir besoin du chat précédent pour reprendre.

