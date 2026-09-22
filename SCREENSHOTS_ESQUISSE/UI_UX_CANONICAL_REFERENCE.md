# Discord Infrastructure Designer — Référence UI/UX canonique

> **Statut : CANONIQUE**
>
> Ce document remplace la direction UI historique basée sur `UI_REDESIGN_PHASES.md`
> et `Esquisse 1.png` comme référence d'implémentation visuelle.
>
> Les spécifications fonctionnelles et techniques de `docs/00_reference/` restent
> les sources de vérité sur le comportement du produit. Ce document fixe la manière
> dont ce comportement doit être présenté à un utilisateur réel.

## 1. Vision produit

Discord Infrastructure Designer doit permettre à une personne qui **ne connaît pas
l'administration Discord** de créer et gérer un serveur complexe à son image.

L'interface ne doit pas demander à l'utilisateur de comprendre :

- bitfields ;
- overwrites ;
- scopes ;
- états internes du cache ;
- identifiants Discord ;
- provenance technique ;
- moteur Policy ;
- états de réconciliation ;
- noms internes comme `CAN/CANNOT/UNKNOWN/BLOCKED`.

Ces notions peuvent exister dans le produit, mais elles sont **secondaires** et
accessibles uniquement à la demande dans un mode avancé ou un panneau
« Détails techniques ».

La question principale de chaque écran doit être formulée dans le langage de
l'utilisateur :

- « Que voulez-vous créer ? »
- « Qui peut voir cet espace ? »
- « Qui peut publier ici ? »
- « Qui peut gérer cet espace ? »
- « Voulez-vous appliquer ces changements ? »
- « Quel résultat souhaitez-vous obtenir ? »

Le produit doit ressembler à un assistant de création et d'administration moderne,
pas à une console IAM ou à un explorateur de structures internes.

---

## 2. Règles UX non négociables

### 2.1 Utilisateur novice d'abord

Le parcours par défaut est conçu pour quelqu'un qui ne connaît ni Discord en
profondeur ni DID.

Le mode expert existe, mais il n'est jamais le parcours par défaut.

### 2.2 Divulgation progressive

Une information technique n'est visible que lorsqu'elle aide à prendre une décision.

Ordre de présentation obligatoire :

1. **résultat humain** ;
2. **action principale** ;
3. explication courte si nécessaire ;
4. « Pourquoi ? » / « En savoir plus » ;
5. détails Discord et diagnostics techniques.

Aucune page ne doit afficher en permanence tout ce qu'elle sait.

### 2.3 Une page = un objectif principal

Au-dessus de la ligne de flottaison :

- un titre clair ;
- une phrase maximum de contexte ;
- une action principale ;
- au plus deux actions secondaires ;
- les informations utiles à la décision courante.

Les détails complémentaires passent dans des drawers, accordéons, popovers,
onglets secondaires ou vues expertes.

### 2.4 Budget de verbosité

Dans le parcours normal :

- aucun paragraphe explicatif de plus de 2 lignes ;
- pas de répétition du nom du serveur sur chaque carte ;
- pas de liste de métadonnées techniques répétée ;
- pas d'identifiants bruts visibles par défaut ;
- pas d'explication détaillée tant qu'il n'y a pas d'erreur ou de demande
  explicite de l'utilisateur.

Un texte long doit être remplacé par :

- un libellé court ;
- une icône ;
- une couleur sémantique ;
- un tooltip ou « Pourquoi ? » ;
- un panneau de détails sur demande.

### 2.5 Aucun état technique brut dans l'interface novice

Exemples interdits comme information principale :

- `UNKNOWN`
- `FULL`
- `FRESH`
- `BLOCKED`
- `Bitfield brut`
- `Source : cache local DID`

Traductions attendues :

- `UNKNOWN` → « À vérifier » + action adaptée ;
- `FRESH` → « À jour » ;
- `FULL` → ne rien afficher sauf si utile ;
- `BLOCKED` → « Action nécessaire » avec cause humaine ;
- cache/provenance → panneau « Détails techniques ».

Si l'utilisateur peut résoudre le problème, une action doit être proposée :
« Actualiser », « Corriger », « Réessayer », « Configurer ».

### 2.6 Les boutons désactivés ne doivent pas former un cimetière

Un bouton indisponible qui n'est pas utile immédiatement est masqué.

S'il doit rester visible pour compréhension :

- il explique sa raison via tooltip/popover ;
- il ne crée pas une ligne entière de contrôles gris inactifs ;
- une remédiation est proposée si possible.

### 2.7 Le jargon doit disparaître du premier niveau

Termes préférés :

- « Accès » plutôt que « Policies » ;
- « Règles d'accès » plutôt que « Policy Engine » ;
- « Qui peut voir ? » plutôt que « Visibility scope » ;
- « Qui peut écrire ? » plutôt que « Write policy » ;
- « À vérifier » plutôt que « UNKNOWN » ;
- « Modifications prêtes » plutôt que « Plan VALIDATED ».

Le vocabulaire Discord réel reste disponible dans le mode expert.

---

## 3. Nouvelle architecture de navigation

La navigation principale doit être organisée par **intention utilisateur**, pas par
modules techniques.

### Navigation principale cible

1. **Accueil**
   - état global simple ;
   - raccourcis « Continuer », « Créer », « Corriger » ;
   - événements importants ;
   - aucun tableau de diagnostics bruts.

2. **Construire**
   - structure ;
   - catégories/salons ;
   - organisation ;
   - rôles quand ils sont nécessaires au parcours.

3. **Accès**
   - qui voit ;
   - qui écrit ;
   - qui gère ;
   - espaces privés/publics ;
   - règles avancées sous divulgation progressive.

4. **Automatiser**
   - assistants ;
   - traductions ;
   - campagnes ;
   - automatisations disponibles.

5. **Activité**
   - changements prêts ;
   - opérations en cours ;
   - historique ;
   - audit simplifié.

Les pages techniques existantes peuvent continuer d'exister comme routes internes,
mais **Rôles / Permissions / Policies / Matrix / Plans / Diagnostics / Audit ne
doivent plus être autant d'entrées de premier niveau pour l'utilisateur novice**.

Le mode expert peut exposer davantage de raccourcis.

---

## 4. Direction visuelle canonique

### 4.1 Le produit ne doit plus être monochrome

Le design actuel « bleu nuit + violet partout » est abandonné.

La nouvelle interface utilise une palette multi-accent cohérente :

- **violet** : actions principales / création ;
- **bleu** : structure / organisation ;
- **cyan ou turquoise** : accès / collaboration ;
- **rose ou magenta** : automatisations / assistants ;
- **vert** : succès / synchronisé / prêt ;
- **ambre** : attention / à vérifier ;
- **corail / rouge doux** : erreur / action destructive ;
- neutres chauds ou froids pour les surfaces.

La couleur sert à :

- distinguer les zones fonctionnelles ;
- rendre les statuts lisibles immédiatement ;
- guider le regard ;
- créer une identité visuelle mémorable.

Elle ne doit jamais être le seul porteur d'information.

### 4.2 Séparation visuelle forte des zones

Les surfaces doivent se distinguer au premier regard grâce à plusieurs leviers :

- contraste de fond ;
- elevation légère ;
- bordures réellement perceptibles ;
- espaces blancs ;
- titres de section ;
- accents de couleur ;
- icônes ;
- regroupements visuels.

Une zone principale, un panneau secondaire et un détail contextuel ne peuvent pas
avoir pratiquement le même fond et la même bordure.

### 4.3 Thèmes

Le produit doit supporter :

- thème clair ;
- thème sombre ;
- préférence système.

Aucun thème ne doit être une simple inversion monochrome de l'autre.

### 4.4 Typographie et densité

- texte principal confortable, pas miniature ;
- hiérarchie claire entre page, section, carte, métadonnée ;
- densité réduite sur les écrans novice ;
- densité plus forte autorisée uniquement dans les vues expertes ;
- grands tableaux/matrices virtualisés et lisibles.

### 4.5 Motion et micro-interactions

Les animations servent la compréhension :

- ouverture de drawer ;
- changement d'étape ;
- confirmation ;
- déplacement ;
- apparition d'une erreur ;
- succès.

Aucune animation décorative qui ralentit l'action.

Respect obligatoire de `prefers-reduced-motion`.

---

## 5. Stack UI standardisée — ne plus réinventer les composants

Le projet doit utiliser des bibliothèques maintenues pour les composants standards.

### Fondation principale

**Mantine 9** devient la bibliothèque de composants UI de référence :

- `@mantine/core`
- `@mantine/hooks`
- `@mantine/form`
- `@mantine/modals`
- `@mantine/notifications`
- `@mantine/dates`
- `@mantine/spotlight`
- `@mantine/nprogress`

Utiliser les composants Mantine pour :

- boutons ;
- inputs ;
- selects ;
- switches ;
- checkboxes ;
- menus ;
- popovers ;
- tooltips ;
- drawers ;
- modals ;
- tabs ;
- accordéons ;
- stepper ;
- notifications ;
- loaders ;
- skeletons ;
- scroll areas ;
- command palette ;
- dates.

### Compléments approuvés

- **Lucide React** : iconographie cohérente ;
- **Motion** : transitions et micro-interactions ;
- **TanStack Table** : matrices et tables riches ;
- **TanStack Virtual** : grosses listes/matrices ;
- **dnd-kit React** : interactions drag & drop nouvelles ou refactorisées ;
- **dayjs** : dates liées à Mantine Dates ;
- **React Query** : données serveur — déjà présent ;
- **Zustand** : état UI local partagé — déjà présent ;
- **i18next** : EN/FR/DE/ES — déjà présent.

### Règle anti-réinvention

Il est interdit de créer un nouveau composant maison de type :

- modal ;
- drawer ;
- menu ;
- tooltip ;
- popover ;
- select ;
- date picker ;
- toast ;
- tabs ;
- accordion ;
- stepper ;
- table de base ;
- command palette ;

si le composant équivalent existe dans la stack approuvée.

Une exception exige une justification écrite dans le tracker.

### Règle anti-bazar de dépendances

« Utiliser les packages » ne signifie pas empiler plusieurs bibliothèques
concurrentes.

Mantine est la base unique. Une bibliothèque supplémentaire n'est ajoutée que pour
un besoin que Mantine ne couvre pas bien.

---

## 6. Règles spécifiques aux écrans observés le 22/09/2026

### Accueil

L'accueil actuel expose des concepts comme cache, FULL/FRESH et huit capacités du bot
en UNKNOWN. Cela disparaît du premier niveau.

Accueil cible :

- salutation / serveur courant ;
- 3 à 5 cartes d'action maximum ;
- santé globale sous forme simple ;
- « Tout va bien » ou « 2 points demandent votre attention » ;
- raccourcis « Modifier la structure », « Gérer les accès », « Continuer les
  changements » ;
- diagnostics techniques accessibles via « Détails ».

### Rôles

Ne pas afficher par défaut :

- ID Discord ;
- bitfield ;
- fraîcheur ;
- position numérique brute ;
- quatre gros boutons désactivés.

Afficher plutôt :

- nom + couleur du rôle ;
- nombre de membres ;
- résumé humain de ce qu'il permet ;
- position visuelle dans la hiérarchie ;
- actions contextuelles disponibles ;
- bloc « Détails Discord » replié.

### Accès

L'écran actuel mélange catalogue, détails, métadonnées répétées et dizaines de rôles.

Cible :

1. choisir une intention :
   - privé ;
   - public ;
   - staff ;
   - lecture seule ;
   - publication limitée ;
   - personnalisé ;
2. choisir les personnes/groupes concernés via recherche et chips ;
3. afficher une phrase de résultat ;
4. montrer l'impact ;
5. préparer les changements.

Les rôles ne doivent pas apparaître sous forme d'un mur de 20+ checkboxes si une
recherche, un multi-select avec chips et des groupes peuvent suffire.

### Mobile

La sidebar permanente visible sur la capture mobile est interdite.

Cible :

- top bar compacte ;
- navigation via drawer/bottom navigation selon contexte ;
- contenu utilisant presque toute la largeur ;
- aucune table desktop compressée ;
- action principale accessible au pouce ;
- aucun menu hors viewport.

---

## 7. États et erreurs

Chaque écran doit disposer d'états dédiés :

- loading ;
- vide ;
- succès ;
- erreur ;
- accès insuffisant ;
- données à actualiser ;
- opération en cours ;
- action impossible.

Un état ne doit jamais être seulement un badge technique.

Format recommandé :

**Titre humain**
Phrase courte.
[Action principale] [Détails]

Exemple :

> **Certaines informations doivent être actualisées**
> Nous ne pouvons pas encore confirmer ce que le bot peut modifier.
> [Actualiser] [Pourquoi ?]

---

## 8. Mode expert

Le mode expert est explicite et persistant par utilisateur.

Il peut afficher :

- IDs ;
- bitfields ;
- noms techniques Discord ;
- provenance ;
- scopes ;
- cache/freshness ;
- traces de résolution ;
- Policy IDs ;
- détails du Plan.

Le mode novice ne doit jamais être une version du mode expert avec quelques champs
masqués. Ce sont deux niveaux de lecture du même produit.

---

## 9. Critères d'acceptation visuelle

Une tâche UI n'est pas DONE uniquement parce que les tests passent.

Elle est DONE si :

1. elle est vérifiée dans le produit réel ;
2. desktop et mobile ont été regardés ;
3. l'utilisateur comprend l'écran sans documentation ;
4. les zones se distinguent immédiatement ;
5. les couleurs servent la lecture ;
6. aucun jargon interne n'est imposé ;
7. aucune information longue n'est visible sans nécessité ;
8. l'action principale est évidente ;
9. l'état d'erreur propose une sortie ;
10. les détails techniques sont disponibles sans polluer le parcours normal.

### Gate humain obligatoire

À la fin de chaque grande phase d'implémentation :

- captures desktop ;
- captures mobile ;
- parcours réel local ;
- **validation humaine explicite avant de passer à la phase suivante**.

Les tests automatiques ne remplacent jamais ce gate.

---

## 10. Ce qui n'est plus une référence visuelle

À partir de ce document :

- `SCREENSHOTS_ESQUISSE/Esquisse 1.png` devient une **archive d'intention
  historique**, pas une cible visuelle canonique ;
- `SCREENSHOTS_ESQUISSE/UI_REDESIGN_PHASES.md` devient un document historique ;
- les anciens rapports de phases restent des preuves techniques, pas des
  prescriptions UI.

La nouvelle référence est le triptyque :

1. `UI_UX_CANONICAL_REFERENCE.md` — ce document ;
2. `UI_IMPLEMENTATION_3_PHASES.md` — plan d'exécution ;
3. `UI_IMPLEMENTATION_LIVE_STATE.md` — état atomique temps réel.

