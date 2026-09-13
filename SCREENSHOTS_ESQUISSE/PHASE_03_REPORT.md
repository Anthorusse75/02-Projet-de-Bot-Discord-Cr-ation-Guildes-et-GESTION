# Phase 3 — Rapport de clôture

**Branche :** `ui/complete-redesign`  
**Statut :** ✅ TERMINÉE  
**Référence visuelle :** `SCREENSHOTS_ESQUISSE/Esquisse 1.png`

## 1. Objectif livré

La Phase 3 transforme la vue Structure en explorateur de serveur utilisable comme poste de travail : arborescence Discord lisible, inspecteur contextuel, recherche, sélection, menus d'actions et Drag & Drop orienté **proposition** plutôt que mutation cachée.

La couche de geste reste basée sur les Pointer Events et `PointerGestureManager`, conformément à l'architecture §22.3. Les gestes gauche/droit, les seuils, l'annulation, la cible de drop et les actions disponibles sont séparés de la logique métier d'autorisation.

## 2. Ce qui est livré

### Explorateur de structure

- catégories, salons et threads rendus selon la hiérarchie Discord observée ;
- aucune sous-catégorie Discord fictive créée par l'UI ;
- expand/collapse ;
- sélection simple et multiple ;
- recherche ;
- filtre des ressources masquées/supprimées ;
- inspecteur de sélection à droite ;
- état de fraîcheur visible ;
- rechargement de page conservant une structure cohérente avec le read model.

Les groupes logiques DID ne sont pas présentés comme des catégories Discord : quand une abstraction logique est exposée par une surface produit, elle doit rester visuellement typée comme abstraction DID. La route Structure courante expose les objets Discord projetés (`categories` / `root_channels`) et ne fabrique donc aucune pseudo-hiérarchie logique.

### Interaction et Drag & Drop

- clic droit sans déplacement -> menu contextuel objet ;
- clic droit + déplacement au-delà du seuil -> Drop Context Menu ;
- drag gauche -> preview d'une proposition ;
- ghost de déplacement ;
- cible valide matérialisée par l'état `drop-hover` ;
- déplacement salon -> catégorie compilé avec le `parent_id` Discord attendu ;
- réordonnancement catégorie -> catégorie compilé en position, sans créer de parent de catégorie ;
- inter-Guild -> seules les actions de copie/clonage sûres sont proposées ;
- aucune suppression implicite de la source en inter-Guild ;
- une action refusée reste bloquée et expose une raison compréhensible ;
- les menus/dialogues fournissent l'alternative accessible aux gestes DnD.

### Synchronisation / drift

Le WebSocket de Guild invalide le namespace TanStack Query correspondant lorsque l'état Structure change. Un événement `structure.updated` provoque donc un refetch du read model et met l'arbre à jour sans rechargement complet de la page. Les événements d'une autre Guild ou d'une version non supportée sont ignorés ; un gap de séquence déclenche une invalidation complète du tenant concerné.

## 3. Correction du right-drag inter-Guild

Le dernier défaut du gate n'était pas dans `resolveActions` ni dans l'autorisation A/B. Le test Playwright utilisait la largeur desktop par défaut alors que le responsive place le panneau de destinations sous le workbench sous 1380 px. La cible Guild B se retrouvait donc hors de la zone réellement parcourable par le pointeur du test.

Le scénario inter-Guild est désormais exécuté dans un viewport de poste de travail (`1600 × 1000`), ce qui garde source et destination simultanément visibles. Le test vérifie réellement :

1. le survol `drop-hover` de Guild B ;
2. l'ouverture du Drop Context Menu au relâchement du bouton droit ;
3. `Copy as new` et `Clone with dependencies` disponibles ;
4. l'absence de `Propose move` en inter-Guild ;
5. aucune mutation/plan créé simplement par l'ouverture du menu.

## 4. Décision d'architecture sur `dnd-kit`

L'architecture liste `dnd-kit` dans le stack frontend, tout en précisant en §22.3 que le frontend **peut** l'utiliser pour collision/overlay/tri et que le bouton droit doit rester géré par une couche custom contrôlée par DID.

Pour la Phase 3, l'ajout de `dnd-kit` n'apporte pas de capacité fonctionnelle manquante au parcours actuellement livré :

- collision : résolution déterministe via `elementFromPoint` + `data-drop-*` ;
- overlay : ghost DID déjà contrôlé par la couche de geste ;
- tri/déplacement : intention compilée par le moteur d'actions, jamais mutation implicite ;
- clavier/accessibilité : alternative menu/dialogue disponible pour les actions DnD ;
- bouton droit : nécessite de toute façon `PointerGestureManager` / custom gesture layer.

**Décision Phase 3 : ne pas ajouter une dépendance `dnd-kit` uniquement pour cocher le stack.** Son introduction reste pertinente si une future évolution a besoin de primitives de sortable clavier/collision plus complexes. Ce choix évite deux moteurs de geste concurrents sans bénéfice produit démontré.

## 5. Exigences Structure couvertes

| Exigence | État Phase 3 | Preuve principale |
|---|---|---|
| REQ-STR-001 | ✅ | arbre catégories / salons / threads + scénario navigateur |
| REQ-STR-002 | ✅ | reorder catégorie sans `parent_id` fictif |
| REQ-STR-003 | ✅ sur la surface Structure actuelle | aucune abstraction DID présentée comme catégorie Discord |
| REQ-STR-004 | ✅ | déplacement de salon compilé avec le `parent_id` cible |
| REQ-STR-005 | hors mutation directe de Phase 3 | la Phase 3 ne supprime pas silencieusement ; suppression effective reste dans pipeline plan/apply |
| REQ-STR-006 | ✅ | menu contextuel objet |
| REQ-STR-007 | ✅ | DnD ouvre une proposition/preview, pas une mutation immédiate |
| REQ-STR-008 | ✅ | inter-Guild sans suppression source |
| REQ-STR-009 | ✅ | right-drag -> Drop Context Menu filtré |
| REQ-STR-010 | ✅ | alternative menu/dialogue aux actions DnD |
| REQ-STR-011 | ✅ | drag gauche inter-Guild compile copie/clonage uniquement |
| REQ-STR-012 | ✅ | clic droit et right-drag distingués par seuil déterministe |
| REQ-STR-013 | ✅ | destination inter-Guild visible et autorisée séparément |

`REQ-STR-005` n'est pas revendiquée comme preuve d'une suppression Discord réelle dans cette phase : les mutations effectives et leur vérification appartiennent au pipeline Plans/Apply de la Phase 5 et à l'acceptance réelle de Phase 9. La Phase 3 garantit ici qu'aucun geste de structure ne contourne ce pipeline.

## 6. Gate ciblé de sortie

Workflow : `.github/workflows/ui-phase3.yml`

Le gate de Phase 3 couvre uniquement ce qui est pertinent pour cette phase :

- TypeScript ;
- garde i18n des chaînes visibles ;
- contrat du moteur d'interaction ;
- scénarios navigateur Structure.

Scénarios navigateur de clôture :

1. hiérarchie fidèle + inspecteur + reload ;
2. déplacement salon -> catégorie -> proposition avec `parent_id` correct ;
3. réordonnancement catégorie -> catégorie sans fausse sous-catégorie ;
4. right-drag inter-Guild -> seulement copie/clonage sûrs ;
5. action impossible -> bloquée avec raison ;
6. événement Structure live -> changement externe réconcilié sans reload complet.

Le gate est vert sur le commit fonctionnel `2922d25f4740b2b53f8ea429e06382f0daeb07eb` (run `34751612719`).

## 7. Ce que cette clôture ne prétend pas

La Phase 3 prouve le comportement de l'explorateur et la compilation des intentions. Elle ne prétend pas qu'une mutation Discord complète a été appliquée et vérifiée par cette seule phase. La confirmation, l'apply, la progression, les échecs partiels et la vérification post-apply sont explicitement traités en Phase 5, puis rejoués sur les Guilds sandbox A/B dans l'acceptance produit de Phase 9.

Aucune fusion vers `main` et aucun démarrage de Phase 4 ne font partie de cette clôture.

## 8. Conclusion

La Phase 3 est fermée : l'explorateur de structure, les gestes gauche/droit, la sécurité inter-Guild, les refus d'autorisation et la réconciliation live disposent chacun d'une preuve ciblée. Le prochain chantier prévu par le plan est la Phase 4 — rôles et permissions — uniquement sur instruction explicite.

## 9. Complément post-audit ciblé — exigences UX Structure

Ce complément ferme uniquement les écarts `REQ-UXN-003/004/005/006/007/012/013/014/015` constatés sur l'ancien snapshot. L'explorateur, `PointerGestureManager`, le right-drag, l'inter-Guild, la synchronisation live et la compilation existante n'ont pas été réécrits.

| Exigence | Statut avant | Existant réinspecté | Écart réel et correction | Statut après |
|---|---|---|---|---|
| REQ-UXN-003 | ABSENT | CRUD tenant-safe, RLS et audité des `logical_groups`; `name` séparé de `id`/`slug`. | Ajout du panneau Structure et édition du seul libellé `name`; le `logical_group`, son UUID, son slug et ses ressources restent inchangés. | **CONFORME** |
| REQ-UXN-004 | PARTIEL | Modèle backend distinct et `resource_kind=DID_LOGICAL_RESOURCE`. | Présentation dédiée « groupes logiques DID », badge « abstraction DID », aide « dashboard uniquement, pas serveur/catégorie Discord » et identité interne visible. | **CONFORME** |
| REQ-UXN-005 | ABSENT | Sélection et couche Pointer Events existaient. | Premier clic sur le libellé = sélection; second clic lent entre 350 et 1 400 ms = éditeur inline. La détection tient compte de la capture de pointeur sans modifier le moteur DnD. | **CONFORME** |
| REQ-UXN-006 | ABSENT | Navigation clavier de l'arbre existante. | `F2` sur catégorie/salon sélectionné ouvre le même éditeur inline. | **CONFORME** |
| REQ-UXN-007 | NON DÉMONTRÉ | Menu contextuel et Action Registry existaient. | Action canonique `rename`, filtrée par type et capabilities, proposée dans le menu. | **CONFORME** |
| REQ-UXN-012 | PARTIEL | React/i18n, JSON HTTP, modèles plan JSONB/PostgreSQL n'imposaient aucune normalisation destructrice. | Éditeur et validation comptent les points de code Unicode; le test navigateur prouve `📣 annonces-été` inchangé de l'UI au payload DSG validé. | **CONFORME** |
| REQ-UXN-013 | ABSENT | Aucun picker. | `emoji-picker-react` 4.20.9, bibliothèque MIT mature, chargée paresseusement dans le composant de nom uniquement, style emoji natif. | **CONFORME** |
| REQ-UXN-014 | ABSENT | Aucun style de nom. | Suggestions sobres et optionnelles (emoji, séparateur, symbole), aperçu et restauration du nom original; aucune transformation automatique. | **CONFORME** |
| REQ-UXN-015 | PARTIEL | Stage 5 validait déjà les noms DSG à 1–100 caractères. | Validation réutilisable côté UI avant dispatch; vide et >100 points de code bloquent le bouton et tout POST de plan; les suggestions sont filtrées par le même validateur. | **CONFORME** |

### Mécanisme métier unique de renommage

Le clic lent, `F2` et « Renommer » appellent tous `beginRename`, puis `submitRename`. Celui-ci crée l'intention `rename` de l'Action Registry, compile un DSG portant le même `discord_id`, POSTe le plan et demande sa validation. Il n'existe aucune mutation Discord directe ni endpoint parallèle de renommage.

### Preuves ciblées

- 3 tests unitaires de nommage : Unicode/emoji, bornes vide/100, suggestions non destructives ;
- 11 tests de contrat d'interaction existants + nouvelle action `rename` : PASS dans la sélection ciblée (14 tests Vitest au total avec le nommage) ;
- 11 scénarios Structure Playwright : PASS, dont clic lent, `F2`, menu contextuel, emoji/Unicode, invalidation avant plan, groupe logique et non-régression des gestes touchés par le routage du clic ;
- 2 scénarios onboarding Playwright exécutés dans le même gate ciblé : PASS ;
- TypeScript, i18n et ESLint ciblé : PASS ;
- aucune migration, modification backend ni mutation Discord live.
