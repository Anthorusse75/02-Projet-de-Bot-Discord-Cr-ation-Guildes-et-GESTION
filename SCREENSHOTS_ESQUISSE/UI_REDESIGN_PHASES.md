# Refonte UI — phases de travail

## Références obligatoires

- **Branche dédiée** : `ui/complete-redesign`
- **Référence visuelle validée** : `SCREENSHOTS_ESQUISSE/Esquisse 1.png`
- **Sources de vérité fonctionnelles et techniques** :
  - `docs/00_reference/01_SPECIFICATIONS_FONCTIONNELLES_DISCORD_INFRA_DESIGNER.md`
  - `docs/00_reference/02_ARCHITECTURE_TECHNIQUE_DISCORD_INFRA_DESIGNER.md`

Le screenshot fixe la **direction visuelle**. Les documents `docs/00_reference` fixent le **comportement produit**. En cas de conflit, le comportement fonctionnel de `docs/00_reference` prime ; l'UI est adaptée sans dénaturer la direction visuelle validée.

## Principe de validation

L'objectif n'est plus de maximiser le nombre de tests. L'objectif est de prouver que les **use cases utilisateur fonctionnent réellement**.

Pour chaque fonctionnalité livrée :

1. le parcours utilisateur principal doit fonctionner dans le navigateur ;
2. les erreurs et refus d'autorisation doivent être compréhensibles dans l'UI ;
3. toute mutation Discord doit être vérifiée jusqu'à son résultat réel ;
4. l'état doit rester correct après rechargement de la page ;
5. un test E2E ciblé couvre le use case ;
6. les use cases Discord critiques sont rejoués sur les Guilds sandbox A/B ;
7. aucun test ne peut déclarer un onboarding ou une découverte conforme en injectant directement l'état que le produit est censé créer lui-même.

Les tests unitaires/composants restent utiles pour la logique complexe, mais **aucune régression backend complète n'est lancée pour une simple modification visuelle**. Une régression large n'est exécutée qu'à un checkpoint de phase pertinent, lorsqu'un socle backend partagé est modifié, et avant la validation finale.

---

# Phase 1 — Audit de conformité et baseline réellement exécutable

**Statut : ✅ TERMINÉE**

### Objectif

Établir la différence exacte entre `docs/00_reference` et le produit actuel, puis définir une baseline que l'on peut démarrer et tester sans contournement manuel.

### Travail réalisé

- audit des exigences ayant un impact UI ou parcours utilisateur ;
- mapping des écrans/routes existants aux exigences ;
- relevé des fonctions absentes, partielles, cassées ou seulement simulées par les tests ;
- audit du parcours `base vierge -> démarrage -> OAuth -> découverte Guild -> onboarding -> import structure -> dashboard` ;
- audit des erreurs actuellement observées : HTTP 500, HTTP 503 et WebSocket ;
- audit du lancement local ;
- registre des défauts P0/P1/P2 et phases de correction.

### Livrables

- `PHASE_01_AUDIT.md` ;
- `PHASE_01_REQUIREMENTS_MATRIX.md` ;
- `PHASE_01_ROUTE_USECASE_MAP.md` ;
- `PHASE_01_DEFECT_REGISTER.md`.

### Gate de sortie

- matrice de conformité initiale disponible : ✅ ;
- chaque défaut P0/P1 connu possède une cause ou une investigation explicitement planifiée : ✅ ;
- aucun statut `VERIFIED` historique n'est accepté comme preuve sans relecture : ✅ ;
- use cases critiques listés : ✅ ;
- direction visuelle figée sur `Esquisse 1.png` : ✅.

---

# Phase 2 — Runtime, onboarding et fondations visuelles

### Objectif

Obtenir une application que l'on peut lancer proprement et une première expérience cohérente avec l'esquisse validée.

### Travail

- démarrage local reproductible des composants nécessaires ;
- OAuth Discord ;
- découverte automatique des Guilds où le bot est présent ;
- assistant de première configuration conforme au §5.4 des spécifications ;
- import initial réel de la structure ;
- état d'installation et diagnostics de permissions bot ;
- correction des HTTP 500 et de la boucle WebSocket observés dans la baseline ;
- préflight des dépendances optionnelles/obligatoires (dont portability) ;
- nouveau design system dark premium ;
- nouveau shell : navigation, header, recherche globale, serveurs récents, utilisateur ;
- accueil / sélection des serveurs / vue d'ensemble serveur ;
- états loading / empty / error propres.

### Use cases obligatoires

- base vierge -> connexion Discord -> A/B visibles sans script manuel ;
- onboarding d'une Guild -> import -> activation ;
- Guild non administrable -> explication claire ;
- refresh navigateur -> session et contexte conservés correctement ;
- WebSocket live ou état dégradé expliqué sans boucle console incontrôlée.

---

# Phase 3 — Explorateur de serveur, arborescence et Drag & Drop

**Statut : ✅ TERMINÉE**  
**Rapport de clôture :** `SCREENSHOTS_ESQUISSE/PHASE_03_REPORT.md`

### Objectif

Construire le cœur du produit : l'administration de structure la plus simple possible.

### Travail

- arborescence fidèle catégories / salons / threads ;
- distinction claire entre objets Discord et groupes logiques DID ;
- expand/collapse, sélection simple et multiple ;
- panneau de propriétés contextuel ;
- recherche et filtres ;
- menus contextuels ;
- drag gauche avec preview ;
- right-drag avec Drop Context Menu ;
- drag inter-Guild avec copie/clonage, jamais suppression implicite de la source ;
- ghost, indicateur de cible et états de drop explicites ;
- **conserver les Pointer Events/`PointerGestureManager` comme couche de geste conformément à l'architecture §22** ;
- intégrer `dnd-kit` lorsque pertinent pour collision, overlay, tri et accessibilité clavier, avec custom sensor/gesture layer DID pour le bouton droit ;
- synchronisation structure réelle et gestion du drift.

### Use cases obligatoires

- déplacer un salon dans une catégorie ;
- réordonner ;
- copier/cloner vers A/B ;
- action impossible bloquée avec raison ;
- Discord modifié directement -> changement visible/reconcilié ;
- reload -> structure identique.

---

# Phase 4 — Rôles et permissions

**Statut : ✅ TERMINÉE**  
**Rapport de clôture :** `SCREENSHOTS_ESQUISSE/PHASE_04_REPORT.md`

### Objectif

Permettre d'administrer les accès sans exiger de connaître les bitfields Discord.

### Travail

- hiérarchie des rôles ;
- création, modification, suppression et réordonnancement ;
- mode simple avec vocabulaire humain ;
- mode expert exposant la réalité Discord ;
- aperçu des permissions effectives ;
- explication `pourquoi cet utilisateur/rôle peut ou ne peut pas` ;
- gestion des overwrites et conflits ;
- panneau d'impact avant mutation.

### Use cases obligatoires

- modifier une permission en mode simple ;
- vérifier le résultat réel Discord ;
- passer en mode expert ;
- diagnostiquer un refus ;
- permissions bot insuffisantes -> mutation bloquée avant l'appel Discord.

### Frontière de phase

La Phase 4 couvre l'administration, le diagnostic, la simulation d'impact et la préparation sûre de plans validés. La confirmation, l'apply Discord, la progression, la vérification post-apply et l'audit lié à l'opération sont traités par la Phase 5 afin qu'une seule chaîne de mutation soit utilisée par le produit. La preuve A/B de mutation réelle est donc attachée au pipeline Phase 5 puis rejouée en Phase 9 ; la Phase 4 n'introduit aucune mutation directe parallèle pour satisfaire artificiellement son gate.

---

# Phase 5 — Plans, preview, apply, progression et sécurité des mutations

### Objectif

Rendre le pipeline `INTENTION -> VALIDATION -> PLAN -> IMPACT -> CONFIRMATION -> APPLY -> VERIFICATION -> AUDIT` totalement visible et compréhensible.

### Travail

- preview claire ;
- diff avant/après ;
- risques et impact ;
- confirmation normale / renforcée ;
- progression étape par étape ;
- annulation lorsqu'elle est encore possible ;
- succès uniquement après état réellement accepté/vérifié ;
- états partiels, retry et intervention manuelle ;
- audit lié à l'opération.

### Use cases obligatoires

- mutation simple ;
- mutation à risque ;
- échec Discord ;
- retry ;
- résultat partiel ;
- vérification post-apply.

---

# Phase 6 — Modèles, bibliothèque, portabilité et clonage inter-serveurs

### Objectif

Rendre utilisables les fonctions de portabilité prévues par les spécifications.

### Travail

- templates ;
- bibliothèque personnelle ;
- export/import ;
- copie et clonage A -> B ;
- mappings de dépendances ;
- modes COPY_AS_NEW / MERGE / RECONCILE lorsque pertinents ;
- configuration de chiffrement requise au démarrage ;
- UI de prévisualisation et de résolution des conflits.

### Use cases obligatoires

- sauvegarder une sélection ;
- la réutiliser ;
- cloner A -> B ;
- source et destination autorisées séparément ;
- source inchangée après copie ;
- erreur de configuration jamais exposée comme écran cassé/503 incompréhensible.

---

# Phase 7 — Traductions et campagnes

### Objectif

Décliner la même qualité d'UX sur les fonctions multilingues et de messaging.

### Travail

- Language Profiles ;
- Translation Groups / Channel Groups ;
- Visibility Scope × Language ;
- création/lien/clonage de variantes ;
- providers de traduction ;
- campagnes ;
- ciblage, planification et statuts ;
- preview Discord-safe ;
- progression et erreurs explicites.

### Use cases obligatoires

- créer une variante de langue ;
- lier une variante existante ;
- cloner une variante ;
- créer et prévisualiser une campagne ;
- envoyer/planifier dans la sandbox sans casser mentions, liens ou éléments Discord protégés.

---

# Phase 8 — Audit, diagnostics, paramètres, i18n et finition produit

### Objectif

Finir toutes les surfaces qui rendent le produit exploitable et agréable au quotidien.

### Travail

- audit lisible ;
- diagnostics actionnables ;
- paramètres ;
- recherche globale / palette de commandes ;
- états de connexion/reconnexion ;
- EN / FR / DE / ES ;
- suppression de toute chaîne mal encodée ou non localisée ;
- accessibilité clavier ;
- responsive desktop raisonnable et aucune superposition ;
- cohérence exacte avec la direction visuelle `Esquisse 1.png`.

### Use cases obligatoires

- retrouver l'origine d'un changement ;
- comprendre une capability manquante ;
- changer de langue sans mélange de locales ;
- utiliser les parcours importants au clavier ;
- redimensionner la fenêtre sans chevauchement.

---

# Phase 9 — Acceptance produit réelle

### Objectif

Prouver que le produit fonctionne de bout en bout, pas que les mocks fonctionnent.

### Parcours d'acceptance

```text
PostgreSQL/Redis propres
        ↓
démarrage documenté
        ↓
OAuth Discord
        ↓
découverte automatique A/B
        ↓
onboarding d'une Guild
        ↓
import de la structure réelle
        ↓
administration structure + rôles + permissions
        ↓
plan / apply / vérification
        ↓
clone A -> B
        ↓
templates / bibliothèque
        ↓
traduction / campagne
        ↓
audit / diagnostics
```

### Done final

- aucun défaut P0/P1 connu ;
- tous les use cases critiques passent réellement ;
- aucune étape ne nécessite un script manuel caché ;
- screenshots de référence conformes ;
- validation visuelle utilisateur ;
- tests ciblés E2E verts ;
- une régression finale raisonnable du socle affecté ;
- `main` n'est proposé au merge qu'après cette validation.
