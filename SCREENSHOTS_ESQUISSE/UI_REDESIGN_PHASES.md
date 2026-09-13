# Refonte UI — phases de travail

## Références obligatoires

- **Branche dédiée** : `ui/complete-redesign`
- **Référence visuelle validée** : `SCREENSHOTS_ESQUISSE/Esquisse 1.png`
- **Sources de vérité fonctionnelles et techniques** :
  - `docs/00_reference/01_SPECIFICATIONS_FONCTIONNELLES_DISCORD_INFRA_DESIGNER.md`
  - `docs/00_reference/02_ARCHITECTURE_TECHNIQUE_DISCORD_INFRA_DESIGNER.md`
- **Clarification produit validée pendant la refonte** :
  - `docs/40_decisions/ACCESS_POLICIES_PRODUCT_REQUIREMENTS.md`
- **Audit d'implémentation étendu** :
  - `docs/10_implementation/11_REQUIREMENTS_IMPLEMENTATION_AUDIT.md`
- **Affectation des écarts d'audit aux phases UI existantes** :
  - `SCREENSHOTS_ESQUISSE/UI_REQUIREMENTS_REMEDIATION_MAP.md`

Le screenshot fixe la **direction visuelle**. Les documents `docs/00_reference` fixent le **comportement produit**. En cas de conflit, le comportement fonctionnel de `docs/00_reference` prime ; l'UI est adaptée sans dénaturer la direction visuelle validée.

Le document `ACCESS_POLICIES_PRODUCT_REQUIREMENTS.md` formalise la simplification de la gestion des accès validée avec l'utilisateur : intentions humaines d'abord, politiques prêtes à l'emploi/personnalisées, conflits multi-rôles explicites, héritage, verrouillage et matrice d'accès.

L'audit étendu porte le périmètre à **389 exigences**. Il ne crée **aucune phase UI supplémentaire** : les écarts `PARTIEL`, `ABSENT` et `NON DÉMONTRÉ` sont absorbés par les **Phases 4 à 9 existantes**. Les Phases 1 à 3 ne sont pas rouvertes sauf régression démontrée.

---

## Principe de validation — tests utiles, pas de tests pour les tests

L'objectif est de prouver les **use cases utilisateur et les frontières de sécurité réellement affectés**, sans relancer des suites massives sans rapport avec le changement.

### Règles obligatoires

1. **Modification purement visuelle / CSS / wording** : contrôle TypeScript/lint/i18n pertinent + vérification visuelle ciblée ; aucune régression backend complète.
2. **Logique métier pure** : tests unitaires ciblés sur les règles modifiées, seulement lorsqu'ils apportent une preuve utile.
3. **Persistance, RLS, RBAC, sécurité ou isolation tenant** : test d'intégration ciblé obligatoire sur la frontière touchée.
4. **Mutation Discord ou pipeline de planification** : test ciblé du chemin réel `intention -> plan -> apply/verification` concerné ; pas de mutation parallèle créée uniquement pour tester.
5. **Parcours utilisateur critique** : un E2E ciblé couvre le parcours de bout en bout ; on évite de dupliquer le même scénario à plusieurs niveaux sans raison.
6. **Discord sandbox A/B** : uniquement lorsque la fonctionnalité nécessite une preuve réelle Discord, aux checkpoints de phase pertinents et en Phase 9 ; pas à chaque retouche UI.
7. **Régression large** : uniquement lorsqu'un socle partagé est modifié, à un checkpoint de phase, et lors de l'acceptance finale Phase 9.
8. Aucun test ne peut déclarer conforme un onboarding, une découverte, une mutation ou une réconciliation en injectant directement l'état que le produit est censé créer lui-même.

La qualité est mesurée par la pertinence des preuves, pas par le nombre de tests exécutés.

---

# Phase 1 — Audit de conformité et baseline réellement exécutable

**Statut : ✅ TERMINÉE**

### Objectif

Établir la différence exacte entre les références et le produit actuel, puis définir une baseline que l'on peut démarrer et tester sans contournement manuel.

### Travail réalisé

- audit des exigences ayant un impact UI ou parcours utilisateur ;
- mapping des écrans/routes existants aux exigences ;
- relevé des fonctions absentes, partielles, cassées ou seulement simulées par les tests ;
- audit du parcours `base vierge -> démarrage -> OAuth -> découverte Guild -> onboarding -> import structure -> dashboard` ;
- audit des erreurs HTTP/WebSocket et du lancement local ;
- registre des défauts P0/P1/P2 ;
- direction visuelle figée sur `Esquisse 1.png`.

L'audit 389 exigences réalisé ensuite complète cette baseline mais **ne crée pas une nouvelle Phase 1**.

---

# Phase 2 — Runtime, onboarding et fondations visuelles

**Statut : 🟡 IMPLÉMENTÉE — validation produit réelle consolidée en Phase 9**

### Objectif

Obtenir une application lançable proprement et une première expérience cohérente avec l'esquisse validée.

### Travail

- démarrage local reproductible ;
- OAuth Discord ;
- découverte automatique des Guilds où le bot est présent ;
- assistant de première configuration ;
- import initial réel de la structure ;
- état d'installation et diagnostics de permissions bot ;
- correction des erreurs runtime/WebSocket ;
- préflight des dépendances optionnelles/obligatoires ;
- design system dark premium ;
- shell, navigation, header, recherche globale, serveurs récents, utilisateur ;
- accueil / sélection des serveurs / vue d'ensemble serveur ;
- états loading / empty / error propres.

### Use cases obligatoires

- base vierge -> connexion Discord -> A/B visibles sans script manuel ;
- onboarding d'une Guild -> import -> activation ;
- Guild non administrable -> explication claire ;
- refresh navigateur -> session et contexte conservés ;
- WebSocket live ou état dégradé expliqué.

---

# Phase 3 — Explorateur de serveur, arborescence et Drag & Drop

**Statut : ✅ TERMINÉE**  
**Rapport de clôture :** `SCREENSHOTS_ESQUISSE/PHASE_03_REPORT.md`

### Objectif

Construire le cœur de l'administration de structure.

### Travail

- arborescence fidèle catégories / salons / threads ;
- distinction objets Discord / groupes logiques ;
- expand/collapse, sélection simple et multiple ;
- panneau de propriétés contextuel ;
- recherche et filtres ;
- menus contextuels ;
- drag gauche avec preview ;
- right-drag avec Drop Context Menu ;
- drag inter-Guild avec copie/clonage, jamais suppression implicite de la source ;
- ghost, cible et états de drop explicites ;
- `PointerGestureManager` conservé comme couche de geste ;
- `dnd-kit` utilisé lorsque pertinent ;
- synchronisation structure réelle et drift.

### Use cases obligatoires

- déplacer un salon dans une catégorie ;
- réordonner ;
- copier/cloner vers A/B ;
- action impossible bloquée avec raison ;
- Discord modifié directement -> changement visible/reconcilié ;
- reload -> structure identique.

Les raffinements UX transverses découverts plus tard (rename second clic/F2, emoji/naming, polish) sont traités en Phase 8 afin de ne pas rouvrir artificiellement la Phase 3.

---

# Phase 4 — Rôles, permissions et politiques d'accès

**Statut : 🚧 EN COURS — réouverte après validation initiale et audit étendu**  
**Rapport initial :** `SCREENSHOTS_ESQUISSE/PHASE_04_REPORT.md`  
**Exigences produit :** `docs/40_decisions/ACCESS_POLICIES_PRODUCT_REQUIREMENTS.md`

### Objectif

Permettre d'administrer les accès en exprimant une intention humaine plutôt que des bitfields/overwrites, tout en gardant la réalité Discord inspectable et explicable.

### Socle déjà implémenté

- hiérarchie des rôles ;
- création/modification/suppression/réordonnancement par plans ;
- mode simple et mode expert ;
- aperçu des permissions effectives ;
- `View As` / « Pourquoi cet accès ? » ;
- simulation d'impact ;
- diagnostic capacité du bot ;
- séparation autorisation DID / capacité Discord.

### Travail restant intégré à cette même Phase 4

- corriger toute cause persistante de `UNKNOWN` et rendre la remédiation compréhensible ;
- construire le **Policy Engine générique** : modèle, scopes, lifecycle/version, stockage tenant-scopé, RLS/RBAC ;
- resolver déterministe : priorité, héritage, exception locale, conflits, verrouillage ;
- politiques natives DID et politiques personnalisées ;
- whitelist/blacklist visibilité et écriture, zones/audiences, vocal, threads/mentions/réactions, bots, temporaire ;
- détection explicite des conflits multi-rôles et membres concernés ;
- `explain`, `preview`, impact et remédiations avant plan ;
- matrice d'accès et édition massive lorsque prévue ;
- **socle Wizard réutilisable** avec sélecteurs, rôle manquant, `+ Créer un rôle`, validation et résumé ;
- reléguer les détails Discord au niveau expert/contextuel ;
- aucune mutation directe hors pipeline Plan.

### Use cases obligatoires de sortie

- modifier une permission en mode simple et inspecter sa traduction Discord ;
- diagnostiquer `CAN / CANNOT / UNKNOWN` avec cause exploitable ;
- appliquer/préparer une policy whitelist ;
- appliquer/préparer une policy blacklist avec conflit multi-rôles détecté ;
- conflit -> membre précis + source + remédiation prévisualisée ;
- policy de catégorie héritée -> exception locale visible ;
- policy verrouillée -> drift explicite et stratégie de remise en conformité/intervention ;
- Wizard : rôle absent -> création proposée sans quitter le parcours ;
- résultat final de la Phase 4 = intention validée + plan prêt, **pas apply Discord direct**.

### Tests Phase 4

- tests unitaires ciblés sur resolver/conflits/lifecycle ;
- intégration ciblée RLS/RBAC/persistance du Policy Engine ;
- quelques E2E sur les parcours whitelist, blacklist/conflit et Wizard ;
- pas de régression backend complète à chaque écran ; checkpoint ciblé en fermeture de phase.

### Frontière avec Phase 5

La Phase 4 définit, diagnostique, explique, prévisualise et prépare. La confirmation, l'apply, la progression, la reprise d'opérations et la vérification post-apply restent en Phase 5.

---

# Phase 5 — Plans, preview, apply, progression et opérations persistantes

**Statut : ⏳ À FAIRE**

### Objectif

Rendre le pipeline `INTENTION -> VALIDATION -> PLAN -> IMPACT -> CONFIRMATION -> APPLY -> VERIFICATION -> AUDIT` visible, persistant et compréhensible.

### Travail

- preview claire et diff avant/après ;
- risques et impact ;
- confirmation normale / renforcée ;
- apply Discord par le pipeline canonique ;
- progression étape par étape ;
- annulation lorsque possible ;
- succès uniquement après état accepté/vérifié ;
- états partiels, retry, `UNKNOWN_OUTCOME`, intervention manuelle ;
- audit lié à l'opération ;
- **Operations Center** : opérations en cours/terminées/échouées ;
- reprise après refresh, logout/login et nouvelle session ;
- brouillons persistants ;
- actions **Apply / Discard** avec suppression du payload de brouillon lorsque requis et conservation minimale d'audit ;
- lien entre opération, plan, ressources et erreurs.

### Use cases obligatoires

- mutation simple ;
- mutation à risque ;
- échec Discord ;
- retry/réconciliation ;
- résultat partiel ;
- refresh/logout/login pendant une opération -> état retrouvé ;
- draft -> Apply ; draft -> Discard ;
- vérification post-apply.

### Tests Phase 5

Tests d'intégration obligatoires sur les états persistants/worker/crash/retry concernés, plus E2E ciblés sur reprise d'opération et draft. Les campagnes de failure injection larges sont réservées au checkpoint de phase et à la Phase 9.

---

# Phase 6 — Modèles, bibliothèque, portabilité et clonage inter-serveurs

**Statut : ⏳ À FAIRE**

### Objectif

Transformer le moteur de portabilité déjà présent en expérience produit réellement utilisable.

### Travail

- templates privés existants et bibliothèque personnelle ;
- **catalogue de templates d'infrastructure prêts à l'emploi** ;
- version métier/révision sélectionnable des templates ;
- export/import ;
- copie et clonage A -> B ;
- mappings de dépendances ;
- modes COPY_AS_NEW / MERGE / RECONCILE lorsque pertinents ;
- adaptation à la Guild cible ;
- suggestions de rôles/mappings manquants ;
- réutilisation du socle Wizard de Phase 4 ;
- UI de preview : créé / remappé / ignoré / impossible ;
- configuration de chiffrement requise clairement diagnostiquée.

### Use cases obligatoires

- sauvegarder une sélection ;
- la réutiliser ;
- appliquer un template préconstruit et voir son adaptation avant plan ;
- cloner A -> B ;
- source et destination autorisées séparément ;
- source inchangée après copie ;
- conflit de mapping résolu explicitement ;
- erreur de configuration expliquée, jamais écran cassé/503 opaque.

### Tests Phase 6

Tests ciblés sur mapping/portabilité/RLS et E2E sur template + clone A->B. Pas de réexécution systématique de tout le backend.

---

# Phase 7 — Traductions et campagnes

**Statut : ⏳ À FAIRE**

### Objectif

Décliner la qualité de la refonte sur les fonctions multilingues et messaging, en réutilisant le backend historique déjà largement conforme.

### Travail

- Language Profiles ;
- Translation Groups / Channel Groups ;
- Visibility Scope × Language ;
- création/lien/clonage de variantes ;
- providers de traduction ;
- campagnes ;
- ciblage, planification et statuts ;
- preview Discord-safe ;
- progression et erreurs explicites ;
- réutilisation des Wizards/primitives UX lorsque nécessaire, sans recréer une seconde logique.

### Use cases obligatoires

- créer une variante de langue ;
- lier une variante existante ;
- cloner une variante ;
- créer et prévisualiser une campagne ;
- envoyer/planifier sans casser mentions, liens ou tokens protégés.

### Tests Phase 7

E2E ciblés sur les parcours réellement modifiés et tests métier uniquement si la logique backend est touchée.

---

# Phase 8 — Audit, diagnostics, paramètres et finition produit

**Statut : ⏳ À FAIRE**

### Objectif

Finir les surfaces transverses et les écarts UX qui ne justifient pas la réouverture des phases précédentes.

### Travail

- audit lisible ;
- diagnostics actionnables ;
- visualisation dashboard bot lecture/écriture (`REQ-BOT-005`) ;
- paramètres ;
- recherche globale / palette de commandes ;
- états connexion/reconnexion ;
- EN / FR / DE / ES ;
- accessibilité clavier ;
- responsive desktop raisonnable et absence de superposition ;
- second clic lent type Windows pour rename, F2 et action contextuelle cohérente ;
- labels de groupes logiques compréhensibles et configurables ;
- emoji picker / aide au naming lorsque prévu ;
- consolidation des exigences `REQ-UXN-*` restantes ;
- doctrine `REQ-REUSE-*` : réutiliser bibliothèques/primitives existantes avant de coder un équivalent maison ;
- cohérence finale avec `Esquisse 1.png`.

### Use cases obligatoires

- retrouver l'origine d'un changement ;
- comprendre une capability manquante ;
- visualiser où un bot peut lire/écrire ;
- renommer rapidement sans dialogue inutile ;
- changer de langue sans mélange ;
- utiliser les parcours importants au clavier ;
- redimensionner sans chevauchement.

### Tests Phase 8

Contrôles visuels, i18n/a11y et E2E ciblés uniquement sur les interactions critiques ajoutées. Pas de campagne backend lourde pour le polish.

---

# Phase 9 — Acceptance produit réelle

**Statut : ⏳ À FAIRE**

### Objectif

Prouver le produit final de bout en bout et fermer l'audit étendu, sans gonfler artificiellement le nombre de tests.

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
structure + rôles + permissions + policies
        ↓
plan / apply / reprise / vérification
        ↓
clone A -> B
        ↓
templates / bibliothèque
        ↓
traduction / campagne
        ↓
audit / diagnostics / finition UX
```

### Preuves obligatoires finales

- aucun défaut P0/P1 connu ;
- les use cases critiques passent réellement ;
- aucune étape ne nécessite un script manuel caché ;
- Discord sandbox A/B qualifiée sur le commit final (`REQ-TEST-003`) ;
- sécurité/RLS/RBAC sur les nouvelles surfaces ;
- E2E des parcours critiques ;
- régression backend/frontend **raisonnable et ciblée par risque**, puis suite finale globale une fois ;
- aucune exigence critique sautée/ignorée sans justification ;
- audit 389 exigences mis à jour : objectif `PARTIEL=0`, `ABSENT=0`, `NON DÉMONTRÉ=0` ;
- validation visuelle utilisateur ;
- `main` proposé au merge uniquement après cette validation.

---

## Règle de pilotage

Il reste **9 phases UI, pas davantage**. Les sous-tâches internes servent uniquement à ordonner le travail dans une phase et ne deviennent pas des phases officielles.

Lorsqu'une exigence de l'audit est corrigée, son statut est mis à jour dans le registre d'audit et sa phase de rattachement dans `UI_REQUIREMENTS_REMEDIATION_MAP.md`. Aucune nouvelle phase n'est créée pour une famille d'exigences.