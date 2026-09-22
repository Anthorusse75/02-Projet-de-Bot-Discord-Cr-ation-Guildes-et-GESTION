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

Le screenshot fixe la **direction visuelle**. Les documents `docs/00_reference` fixent le **comportement produit**. En cas de conflit, le comportement fonctionnel prime ; l'UI est adaptée sans dénaturer la direction visuelle validée.

L'audit étendu porte le périmètre à **389 exigences**. Il ne crée **aucune phase UI supplémentaire**. Une exigence découverte tardivement reste rattachée à la phase fonctionnelle qui aurait dû la couvrir. Une phase déjà livrée peut recevoir un **complément post-audit ciblé** sans être rejouée intégralement.

---

## Principe de validation — tests utiles, pas de tests pour les tests

L'objectif est de prouver les **use cases utilisateur et les frontières de sécurité réellement affectés**, sans relancer des suites massives sans rapport avec le changement.

1. **CSS / layout / wording** : typecheck/lint/i18n pertinent + vérification visuelle ciblée ; aucune régression backend complète.
2. **Logique métier** : tests unitaires ciblés lorsque la règle modifiée le justifie.
3. **DB / RLS / RBAC / isolation tenant** : test d'intégration ciblé obligatoire.
4. **Mutation Discord / Plan** : test du chemin réel concerné `intention -> plan -> apply/verification` ; aucune voie parallèle créée pour tester.
5. **Parcours utilisateur critique** : E2E ciblé ; ne pas dupliquer le même scénario sans raison.
6. **Discord sandbox A/B** : uniquement lorsque la preuve réelle Discord est nécessaire, aux checkpoints utiles et en Phase 9.
7. **Régression large** : uniquement si un socle partagé est modifié, à un checkpoint de phase, puis une fois en Phase 9.
8. Aucun test ne peut déclarer conforme un onboarding, une découverte, une mutation ou une réconciliation en injectant directement l'état que le produit est censé créer.

La qualité est mesurée par la pertinence des preuves, pas par leur quantité.

---

# Phase 1 — Audit de conformité et baseline réellement exécutable

**Statut : ✅ TERMINÉE — méthode renforcée par l'audit 389 exigences**

### Objectif

Établir la différence exacte entre les références et le produit réel, puis définir une baseline lançable/testable sans contournement manuel.

### Travail

- audit des exigences ayant un impact UI ou parcours utilisateur ;
- mapping écrans/routes -> exigences ;
- relevé des fonctions absentes, partielles, cassées ou seulement simulées ;
- audit du parcours `base vierge -> démarrage -> OAuth -> découverte Guild -> onboarding -> import structure -> dashboard` ;
- audit erreurs HTTP/WebSocket et lancement local ;
- registre des défauts P0/P1/P2 ;
- direction visuelle figée sur `Esquisse 1.png`.

### Exigences post-audit rattachées

- `REQ-QA-001` appartient à la doctrine de preuve de cette phase ; sa fermeture finale est vérifiée en Phase 9.
- `REQ-QA-002` est déjà conforme.

Aucun chantier produit n'est à rejouer en Phase 1.

---

# Phase 2 — Runtime, onboarding et fondations visuelles

**Statut : 🟡 SOCLE IMPLÉMENTÉ — complément post-audit ciblé**

### Objectif

Obtenir une application lançable proprement et une première expérience cohérente avec l'esquisse validée.

### Travail livré

- démarrage local reproductible ;
- OAuth Discord ;
- découverte automatique des Guilds où le bot est présent ;
- assistant de première configuration ;
- import initial réel de la structure ;
- état d'installation et diagnostics de permissions bot ;
- correction des erreurs runtime/WebSocket ;
- préflight des dépendances ;
- design system dark premium ;
- shell, navigation, header, recherche globale, serveurs récents, utilisateur ;
- accueil / sélection des serveurs / vue d'ensemble ;
- états loading / empty / error propres.

### Complément post-audit

- `REQ-WIZ-011` — vérifier/compléter le **premier setup 9 étapes** ;
- `REQ-WIZ-012` — vérifier/compléter le **moindre privilège** et l'explication des permissions bot demandées.

Ces deux exigences appartiennent à la Phase 2, pas à la Phase 4. Le rapport Phase 2 démontre déjà un assistant réel ; il faut d'abord le réinspecter sur `ui/complete-redesign` avant de décider qu'il manque du code.

### Use cases obligatoires

- base vierge -> connexion Discord -> A/B visibles sans script manuel ;
- onboarding d'une Guild -> neuf contrôles -> import -> activation ;
- permissions bot demandées expliquées sans imposer `ADMINISTRATOR` ;
- Guild non administrable -> explication claire ;
- refresh navigateur -> session/contexte conservés ;
- WebSocket live ou état dégradé expliqué.

### Tests utiles

Un E2E onboarding ciblé. Tests API/intégration seulement si la correction touche réellement le backend.

---

# Phase 3 — Explorateur de serveur, arborescence et Drag & Drop

**Statut : 🟡 SOCLE STRUCTURE/DnD TERMINÉ — complément UX post-audit ciblé**  
**Rapport initial :** `SCREENSHOTS_ESQUISSE/PHASE_03_REPORT.md`

### Objectif

Construire le cœur de l'administration de structure et rendre son interaction naturelle.

### Socle déjà livré

- arborescence fidèle catégories / salons / threads ;
- distinction objets Discord / groupes logiques ;
- expand/collapse, sélection simple et multiple ;
- panneau de propriétés contextuel ;
- recherche et filtres ;
- menus contextuels ;
- drag gauche avec preview ;
- right-drag avec Drop Context Menu ;
- copie/clonage inter-Guild sans suppression implicite ;
- ghost/cible/drop explicites ;
- `PointerGestureManager` comme couche de geste ;
- synchronisation structure réelle et drift.

### Complément post-audit

- `REQ-UXN-003` — libellé configurable des groupes logiques ;
- `REQ-UXN-004` — aucune confusion groupe logique / Guild Discord ;
- `REQ-UXN-005` — renommage inline au second clic lent ;
- `REQ-UXN-006` — renommage par `F2` ;
- `REQ-UXN-007` — `Renommer` dans le menu contextuel canonique ;
- `REQ-UXN-012` — Unicode/emoji dans les noms ;
- `REQ-UXN-013` — emoji picker réutilisable ;
- `REQ-UXN-014` — suggestions de noms stylés sobres ;
- `REQ-UXN-015` — validation Discord du nom avant plan.

`REQ-UXN-001` et `REQ-UXN-002` sont déjà conformes. On **ne rejoue pas** les tests DnD/synchronisation déjà prouvés si ces composants ne sont pas modifiés.

### Use cases obligatoires

- déplacer/réordonner/copier/cloner comme déjà livré ;
- renommer par second clic, `F2` ou menu contextuel via la même intention canonique ;
- groupe logique clairement distinct d'une Guild ;
- création/édition d'un nom Unicode/emoji valide ;
- nom invalide bloqué avant plan.

### Tests utiles

Tests d'interaction ciblés sur rename, menu contextuel, emoji/naming et validation. Pas de replay complet du gate DnD si le moteur de gestes n'est pas touché.

---

# Phase 4 — Rôles, permissions et politiques d'accès

**Statut : ✅ TERMINÉE**
**Preuve détaillée :** `SCREENSHOTS_ESQUISSE/PHASE_04_REPORT.md`
**Exigences produit :** `docs/40_decisions/ACCESS_POLICIES_PRODUCT_REQUIREMENTS.md`

### Objectif

Permettre d'administrer les accès en exprimant une intention humaine plutôt que des bitfields/overwrites, tout en gardant la réalité Discord inspectable et explicable.

### Travail livré

- hiérarchie, création, édition, réordonnancement et suppression sûre des rôles via Plans ;
- modes simple et expert, permissions effectives, `View As`, « Pourquoi cet accès ? », simulation d'impact et diagnostic des capacités du bot ;
- **Policy Engine générique** tenant-scopé avec RLS/RBAC, scopes, lifecycle, versions, audit et resolver déterministe ;
- décisions explicites `CAN / CANNOT / UNKNOWN / BLOCKED`, priorité, héritage, exceptions locales et explications actionnables ;
- policies natives DID et personnalisées, favoris par Guild, audiences nommées, zones et combinaisons `ANY / ALL / NOT` ;
- intentions de visibilité, écriture, vocal, threads, réactions, mentions et accès bot minimal, sans inventer de capacité Discord ;
- conflits multi-rôles jusqu'au membre concerné, causes, impact collatéral, remédiations bornées et exceptions documentées ;
- Access Matrix, édition par cellule, sélection et opérations bulk avec preview avant Plan ;
- socle Wizard réutilisable (`REQ-WIZ-001..010`, `013`, `014`), parcours d'espace d'accès et proposition de création d'un rôle manquant ;
- presets simples et composés, catégories et exceptions locales avec réapplication de la policy de catégorie ;
- verrouillage, détection de drift, reconciler durable et états d'intervention explicites ;
- accès temporaires durables avec échéance, retry, retrait par Plan canonique et reprise après redémarrage ;
- actions « Gérer l'accès » dans les menus contextuels simple et multiple ;
- suppression logique de Policy avec dépendances, stratégie explicite et historique immuable ;
- pipeline unique `intention -> preview/explain -> Plan` : aucune mutation Discord structurelle directe depuis l'UI ou l'API.

### Use cases obligatoires validés

- permission simple -> traduction Discord inspectable ;
- `CAN / CANNOT / UNKNOWN` avec cause exploitable ;
- policy whitelist ;
- blacklist avec conflit multi-rôles ;
- conflit -> membre + source + remédiation ;
- héritage + exception locale ;
- policy verrouillée + drift ;
- Wizard -> rôle absent -> création proposée ;
- sortie Phase 4 = intention validée + plan prêt, pas apply direct.

### Validation réalisée

Les use cases obligatoires ci-dessus sont validés. Les preuves couvrent le
resolver, les conflits et lifecycles, la persistance PostgreSQL/RLS/RBAC, le
scheduler/reconciler, les parcours E2E critiques, l'accessibilité et
l'acceptation visuelle desktop/mobile. Le détail des scénarios, commandes,
résultats et commits est conservé dans
`SCREENSHOTS_ESQUISSE/PHASE_04_REPORT.md`.

Aucun APPLY Discord live n'a été exécuté pendant cette clôture. La Phase 5
n'est pas commencée.

---

# Phase 5 — Plans, preview, apply, progression et opérations persistantes

**Statut : ⏳ À FAIRE**

### Objectif

Rendre `INTENTION -> VALIDATION -> PLAN -> IMPACT -> CONFIRMATION -> APPLY -> VERIFICATION -> AUDIT` visible, persistant et compréhensible.

### Travail

- preview/diff/risques/impact ;
- confirmation normale / renforcée ;
- apply Discord canonique ;
- progression ;
- annulation lorsque possible ;
- succès seulement après vérification ;
- états partiels, retry, `UNKNOWN_OUTCOME`, intervention ;
- audit lié à l'opération ;
- Operations Center ;
- reprise après refresh/logout-login/nouvelle session ;
- drafts persistants ;
- **Apply / Discard** ;
- lien opération/plan/ressources/erreurs.

### Tests utiles

Intégration ciblée persistance/worker/crash/retry + E2E reprise d'opération et draft. Failure injection large seulement au checkpoint de phase et en Phase 9.

---

# Phase 6 — Modèles, bibliothèque, portabilité et clonage inter-serveurs

**Statut : ⏳ À FAIRE**

### Objectif

Transformer le moteur de portabilité existant en expérience produit réellement utilisable.

### Travail

- templates privés et bibliothèque ;
- catalogue de templates d'infrastructure prêts à l'emploi ;
- version métier/révision sélectionnable ;
- export/import ;
- copie/clonage A -> B ;
- mappings ;
- COPY_AS_NEW / MERGE / RECONCILE ;
- adaptation à la Guild cible ;
- suggestions rôles/mappings manquants ;
- réutilisation du Wizard Phase 4 ;
- preview créé/remappé/ignoré/impossible ;
- diagnostic de chiffrement/configuration.

### Tests utiles

Tests ciblés mapping/portabilité/RLS + E2E template et clone A->B. Pas de replay systématique du backend.

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
- ciblage, planification, statuts ;
- preview Discord-safe ;
- progression/erreurs explicites ;
- réutilisation des Wizards/primitives existants.

### Tests utiles

E2E ciblés sur les parcours réellement modifiés et tests métier seulement si la logique backend change.

---

# Phase 8 — Audit, diagnostics, paramètres et finition produit

**Statut : ⏳ À FAIRE**

### Objectif

Finir les surfaces transverses et vérifier la cohérence globale sans déplacer artificiellement ici les exigences qui appartiennent aux phases précédentes.

### Travail

- audit lisible ;
- diagnostics actionnables ;
- visualisation dashboard bot lecture/écriture (`REQ-BOT-005`) ;
- paramètres ;
- recherche globale / palette ;
- états connexion/reconnexion ;
- EN / FR / DE / ES ;
- accessibilité clavier ;
- responsive ;
- `REQ-UXN-016` : jargon/acronyme DID non imposé sans explication ;
- `REQ-UXN-017` : aide contextuelle ;
- consolidation `REQ-REUSE-*` ;
- contrôle transverse final des UX des Phases 2-7 ;
- cohérence avec `Esquisse 1.png`.

### Tests utiles

Contrôles visuels, i18n/a11y et E2E uniquement sur les interactions critiques ajoutées. Pas de campagne backend lourde pour le polish.

---

# Phase 9 — Acceptance produit réelle

**Statut : ⏳ À FAIRE**

### Objectif

Prouver le produit final de bout en bout et fermer l'audit 389 exigences.

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
onboarding / setup
        ↓
import structure réelle
        ↓
explorateur + naming + DnD
        ↓
rôles + permissions + policies
        ↓
plan / apply / reprise / vérification
        ↓
clone A -> B + templates
        ↓
traduction / campagne
        ↓
audit / diagnostics / finition UX
```

### Preuves finales

- aucun défaut P0/P1 connu ;
- use cases critiques réellement passants ;
- aucune étape dépend d'un script manuel caché ;
- Discord sandbox A/B qualifiée sur le commit final (`REQ-TEST-003`) ;
- sécurité/RLS/RBAC des nouvelles surfaces ;
- E2E des parcours critiques ;
- régression finale globale **une fois**, adaptée au risque ;
- aucun skip critique inexpliqué ;
- audit 389 exigences : objectif `CONFORME=389`, `PARTIEL=0`, `ABSENT=0`, `NON DÉMONTRÉ=0` ;
- validation visuelle utilisateur ;
- proposition de merge seulement après cette validation.

---

## Règle de pilotage

Il reste **9 phases UI, pas davantage**. Les sous-tâches servent seulement à ordonner le travail.

Une exigence découverte tardivement reste rattachée à sa phase naturelle. Cela peut nécessiter un complément ciblé sur une phase déjà livrée, mais **jamais le replay automatique de toute la phase** ni la création d'une Phase 10/10R.

Lorsqu'une exigence est corrigée, son statut est mis à jour dans l'audit et son rattachement dans `UI_REQUIREMENTS_REMEDIATION_MAP.md`.
