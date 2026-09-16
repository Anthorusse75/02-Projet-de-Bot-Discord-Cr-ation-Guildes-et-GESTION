# Refonte UI — affectation des écarts d'audit aux phases existantes

## But

Ce document relie les exigences `PARTIEL`, `ABSENT` et `NON DÉMONTRÉ` de l'audit étendu aux **9 phases UI existantes**.

**Règle ferme : aucune nouvelle phase UI n'est créée.** Une exigence reste rattachée à la phase fonctionnelle qui aurait dû la couvrir, même si l'écart n'a été découvert qu'après la clôture initiale de cette phase. Une phase déjà livrée peut donc recevoir un **complément post-audit ciblé** sans être rejouée intégralement.

Audit source : `docs/10_implementation/11_REQUIREMENTS_IMPLEMENTATION_AUDIT.md`.

Snapshot audité : 389 exigences, dont 265 conformes et 124 non totalement conformes au moment de l'audit.

---

## Phase 1 — Audit/baseline

**État : terminée sur son périmètre initial ; doctrine de preuve consolidée par l'audit 389 exigences.**

### Exigences concernées

- `REQ-QA-001` : la règle « un fichier/écran ne suffit pas à prouver la conformité » appartient à la méthode d'audit de Phase 1. Sa preuve finale reste contrôlée en Phase 9.
- `REQ-QA-002` est déjà conforme et matérialise la règle qu'une fonctionnalité partielle ne peut pas être déclarée conforme.

### Action

Aucun chantier produit à rejouer. Le nouvel audit remplace seulement les anciennes déclarations trop optimistes par une preuve plus stricte.

---

## Phase 2 — Runtime, onboarding et fondations visuelles

**État : socle implémenté ; complément post-audit ciblé terminé.**

### Exigences affectées

- `REQ-WIZ-011` — le **premier setup 9 étapes** appartient directement à l'onboarding de Phase 2.
- `REQ-WIZ-012` — le **moindre privilège** et l'explication des permissions bot demandées appartiennent également à l'onboarding de Phase 2.

La réinspection de `ui/complete-redesign` a confirmé le backend d'onboarding et de capabilities. L'écart UI a été fermé : neuf contrôles distincts et explication du moindre privilège, des permissions, des résultats `CAN/CANNOT/UNKNOWN`, des causes et remédiations. `REQ-WIZ-011` et `REQ-WIZ-012` sont désormais **CONFORME** avec preuve E2E ciblée.

### Résultat attendu

- les neuf contrôles de setup sont réellement présents ou complétés ;
- chaque permission bot demandée est expliquée ;
- aucune demande `ADMINISTRATOR` par commodité ;
- une permission manquante ne bloque que les capacités concernées ;
- le parcours reste utilisable après refresh/reconnexion.

### Preuve minimale utile

Un E2E onboarding ciblé et, uniquement si le backend est modifié, les tests API/intégration directement concernés. Pas de régression générale.

---

## Phase 3 — Explorateur / structure / DnD

**État : socle explorateur/DnD terminé ; complément UX post-audit ciblé terminé.**

### Exigences affectées

- `REQ-UXN-003` — libellé utilisateur configurable des groupes logiques ;
- `REQ-UXN-004` — absence de confusion entre groupe logique et Guild Discord ;
- `REQ-UXN-005` — renommage inline au second clic lent ;
- `REQ-UXN-006` — renommage par `F2` ;
- `REQ-UXN-007` — action `Renommer` dans le menu contextuel canonique ;
- `REQ-UXN-012` — Unicode/emoji dans les noms de catégories/salons ;
- `REQ-UXN-013` — emoji picker réutilisable ;
- `REQ-UXN-014` — suggestions de noms stylés sobres ;
- `REQ-UXN-015` — validation des contraintes Discord avant plan.

`REQ-UXN-001` et `REQ-UXN-002` sont déjà conformes et constituent le socle des groupes logiques. Les exigences Structure historiques restent fermées : on ne rejoue pas le DnD ni la synchronisation déjà prouvés si ces composants ne changent pas.

La réinspection et les corrections ciblées ferment les neuf IDs : libellé de groupe logique sans changement d'identité, distinction explicite avec une Guild Discord, trois entrées vers un unique rename planifié, Unicode/emoji, picker réutilisable, suggestions sobres avec aperçu et validation Discord avant plan. `REQ-UXN-003/004/005/006/007/012/013/014/015` sont désormais **CONFORME**; le détail des preuves se trouve dans `PHASE_03_REPORT.md`.

### Résultat attendu

- explorer et renommer les objets de structure de façon naturelle ;
- distinguer sans ambiguïté Guild Discord, objet Discord et groupe logique ;
- proposer un nom Unicode/emoji valide sans contourner les contraintes Discord ;
- toutes les voies de renommage compilent la même intention et le même plan.

### Preuve minimale utile

Quelques tests interaction/UI ciblés sur second clic, F2, menu contextuel et validation de nom. Aucun replay du gate DnD complet si le moteur de gestes n'est pas modifié.

---

## Phase 4 — Rôles, permissions et politiques

### Exigences affectées

- **`REQ-POL-001` à `REQ-POL-053`** : le backend générique, son resolver, son raccord Plan et l'UI Policies sont livrés ; le Wizard et les preuves de fermeture restantes restent ouverts dans cette phase.
- **`REQ-WIZ-001` à `REQ-WIZ-010`, `REQ-WIZ-013`, `REQ-WIZ-014`** : le socle Wizard générique est construit ici puis réutilisé en Phases 6/7. `REQ-WIZ-011` et `012` restent la propriété de la Phase 2 car ils décrivent le premier setup.
- **`REQ-PERMX-010`** : raccord complet du moteur canonique de permissions au Policy Engine/Wizard.
- **`REQ-UXN-009`** : aucune UI métier mono-rôle lorsque Discord autorise les rôles cumulés.
- **`REQ-UXN-010` / `REQ-UXN-011`** : règles multi-rôles `ANY` / `ALL` portées par le moteur de règles/Policies.

### Résultat attendu

- Policy Engine générique et tenant-safe ;
- policies natives/personnalisées ;
- priorité/héritage/conflits/verrouillage ;
- explain/preview/remédiation ;
- Wizard avec rôle manquant et `+ Créer un rôle` ;
- sortie vers le Plan Engine, sans mutation Discord directe.

### Lot backend fondations Policy — livré le 2026-09-14

Le premier lot backend est livré sans anticiper les lots resolver/UI : agrégat
tenant-scopé à identifiant stable, registre fermé/versionné, conditions et effets
typés, lifecycle `DRAFT → ACTIVE → DISABLED → RETIRED`, versions append-only,
idempotence, CAS, API minimale et capabilities distinctes. La migration
`0036_ui_phase4` force la RLS sur `policies` et `policy_versions`; les tests
PostgreSQL réels prouvent isolation A/B, refus d'une cible cross-tenant,
historique immuable et concurrence.

Couverture acquise : `REQ-POL-002` à `005`, `007` à `011`, `027`, `029` à
`031`, `035` à `039`, `052` et `053` sont conformes. `REQ-POL-001`, `006`,
`012`, `040` et `050` progressent mais restent partiels selon leurs critères
complets. Tous les autres `REQ-POL-*`, le resolver, la preview, le raccord Plan,
l'UI et les Wizards gardent leur statut antérieur.

### Lot backend resolver Policy — livré le 2026-09-14

Le resolver générique est désormais raccordé au read model cache-first et à une
route d'explication utilisant le même service. La priorité explicite persistée
domine ; à égalité, la spécificité s'applique uniquement dans les hiérarchies
`GUILD → LOGICAL_GROUP → CATEGORY → CHANNEL` et
`GUILD → ROLE → MEMBER/BOT`. Deux scopes incomparables ou de même rang qui
portent des effets opposés bloquent la décision. Toutes les contributions et
provenances héritées restent exposées.

Couverture acquise dans ce lot : `REQ-POL-001`, `012` à `020`, `024`, `033`,
`034`, `040`, `047` à `049`, ainsi que `REQ-UXN-010` et `REQ-UXN-011`, passent à
**CONFORME**. Les tests couvrent le déterminisme par permutation, la matrice de
conflits, l'héritage complet, les ensembles de rôles `ANY`/`ALL`, les données
incomplètes, le drift et les cibles supprimées/inaccessibles. Preview/impact,
préflight/Plan, enforcement, UI Policies et Wizards restent ouverts ; la Phase 4
n'est donc pas déclarée terminée.

### Lot backend Policy → preview/preflight → Plan — livré le 2026-09-15

La preview d'une Policy `DRAFT` compare maintenant la résolution courante à la
proposition avec l'unique `PolicyResolver`. Elle expose les changements d'accès,
contributions, conflits et une précision d'impact honnête
`EXACT/BOUNDED/INCOMPLETE`, sans écriture ni mutation Discord.

Les effets matérialisables sont compilés en nœuds `OVERWRITE` du DSG existant,
puis passent dans le Plan Engine et le preflight existants. Le Plan porte une
provenance immuable Policy/révision/scope/corrélation ; ses opérations permettent
ainsi de remonter au Plan puis à la Policy. Le recheck canonique fusionne les
capacités Discord et la décision Policy, conserve les explications et bloque
`BLOCKED`/`UNKNOWN`. Le worker répète ce contrôle avant toute opération. Une
activation exige désormais ce Plan tenant-local préflighté et ne prétend être
appliquée/vérifiée que lorsque le Plan est `SUCCEEDED`.

Couverture acquise : `REQ-POL-021`, `022`, `023`, `026`, `028`, `044`, `045` et
`046` passent à **CONFORME**. `REQ-POL-050` reste **PARTIEL** jusqu'à une preuve
HTTP 403 complète. `REQ-POL-051` devient **PARTIEL** jusqu'à la chaîne CI
complète incluant audit et désactivation. L'UI Policies et les Wizards restent
ouverts ; aucune Phase supplémentaire n'est créée.

### Lot UI catalogue et éditeur Policies — livré le 2026-09-15

Une entrée « Politiques d'accès » ouvre un espace intention-first en
EN/FR/DE/ES. Le catalogue DID versionné fournit sept natives : visibilité en
inclusion/exclusion, écriture en inclusion/exclusion, lecture ouverte avec
publication limitée, espace privé et staff uniquement. La cible choisie filtre
les natives et personnalisées incompatibles.

Les Policies personnalisées peuvent être créées depuis une native, renommées,
modifiées en `DRAFT`, dupliquées depuis toute Policy et recréées depuis une
révision historique. La suppression n'est pas exposée tant qu'un contrat
tenant-safe de dépendances ne permet pas de choisir détacher/remplacer/annuler.

Le mode simple ne montre que cible, audiences cumulatives et intentions. Le
mode expert expose le même modèle canonique. Preview/impact, conflits,
`CAN/CANNOT/BLOCKED/UNKNOWN`, Explain et préparation du Plan proviennent des
routes backend existantes. Aucun bouton Apply ni mutation Discord directe n'est
ajouté. L'audience optionnelle par effet a été ajoutée au contrat fermé et à
l'unique resolver afin d'exprimer correctement exclusion et lecture/écriture
distinctes sans calcul React parallèle.

`REQ-POL-006`, `025`, `032`, `041` et `042` passent à **CONFORME**.
`REQ-POL-043` reste **ABSENT**, réservé au lot Wizard.

Preuves : 57 tests backend ciblés, 5 tests catalogue, trois Playwright ciblés,
typecheck, lint, i18n quatre langues, axe sur l'espace principal, Ruff et
OpenAPI. Pas de campagne globale, PostgreSQL, Discord live ou APPLY.

### Lot frontend socle Wizard + assistant « Configurer l'accès à un espace » — livré le 2026-09-15

Backend inchangé : le Policy Engine, le resolver, le raccord Plan et les
capabilities existants étaient déjà suffisants. Une entrée « Assistants »
localisée rejoint la navigation, distincte de Politiques d'accès/Plans/
Templates, avec un catalogue à deux entrées (un assistant réellement
disponible, un marqué explicitement non disponible pour la Phase 6).

Le socle Wizard générique (`features/wizards/core/`) fournit un reducer pur
de navigation/invalidation, un hook React, une présentation d'étapes avec
focus géré et un sélecteur de rôles multi-sélection réutilisable (rôles
gérés visibles-mais-désactivés, suggestion de rôle manquant, « + Créer un
rôle » en proposition locale uniquement). Aucune logique de résolution ni
aucun appel Discord n'y vit : chaque étape concrète appelle uniquement les
routes Policy/Plan canoniques déjà existantes.

L'assistant « Configurer l'accès à un espace » guide sept étapes (cible,
intention, rôles, conflits informatifs, ajustement, Preview/Impact réel via
les routes Policy existantes, Plan) et ne peut produire qu'une Policy
`DRAFT`, jamais activée depuis le Wizard. Un rôle manquant reste une
proposition tant qu'il n'a pas son propre Plan de rôle validé (jamais
appliqué) ; la Policy ne référence que des rôles réellement existants, le
contrat `ACCESS_CONTROL` validant les `role_ids` contre le tenant à la
création. Sélectionner uniquement un rôle proposé bloque l'étape avec une
explication `CANNOT`, pas un bouton désactivé sans cause. L'annulation avant
toute création de brouillon ne déclenche aucun appel réseau ; après, le
brouillon `DRAFT` déjà créé (action explicite, jamais silencieuse) reste
sans effet.

`REQ-WIZ-001` à `010`, `013`, `014` et `REQ-POL-043` passent à **CONFORME**.
`REQ-PERMX-010` passe de **PARTIEL** à **CONFORME**. `REQ-WIZ-011`/`012`
restent inchangés (Phase 2).

Preuves : 10 tests unitaires frontend ciblés (reducer, sélecteur de rôles,
annulation), deux Playwright ciblés (parcours nominal avec axe sur `#main`,
parcours rôle manquant incluant le cas `CANNOT`), suite frontend complète,
typecheck, lint et i18n quatre langues rejoués sans régression (un seul
échec pré-existant sans rapport, déjà présent avant ce lot). Pas de campagne
backend, PostgreSQL, Discord live ni APPLY : rien de tout cela n'est modifié
par ce lot. Aucune migration.

### Lot Matrice d’accès + édition massive — livré le 2026-09-15

Une matrice rôle/audience × catégorie/salon consomme désormais un endpoint
batch cache-first borné, alimenté exclusivement par `PermissionEvaluator` et
`PolicyResolver`. Les cellules montrent synthèse humaine, `UNKNOWN`, héritage,
exception et conflit ; les filtres et l’édition intention-first sont accessibles
au clavier, avec détails Discord secondaires.

La sélection multiple prépare en une requête batch des DRAFTs tenant-safe, puis
leurs Previews ; une seconde requête batch prépare autant de Plans canoniques
qu’il existe de Policies compatibles. Les ressources incompatibles restent
explicitement exclues avec leur raison et les compteurs/avant-après/conflits/
précision sont affichés avant Plan. Les clés enfants stables rendent les retries
idempotents. Aucun APPLY ni appel Discord direct n’existe dans ce parcours.

`REQ-AP-MAT-001` à `006` et `REQ-AP-BULK-001` à `003` sont couverts.
`REQ-AP-BULK-004` reste ouvert : l’Action Registry actuel décrit un bulk de
déplacement structurel, pas une Policy sur sélection mixte, et aucun second
menu contextuel n’a été ajouté. La Phase 4 reste ouverte pour les familles
avancées inventoriées dans `PHASE_04_REPORT.md`.

### Preuve minimale utile

Tests unitaires ciblés resolver/lifecycle, intégration RLS/RBAC/persistance, E2E whitelist + blacklist/conflit + Wizard. Pas de régression générale à chaque changement UI.

---

## Phase 5 — Plans, apply, progression et opérations

### Exigences affectées

- **`REQ-OPS-003` à `REQ-OPS-012`** ;
- **`REQ-OPS-014`**.

`REQ-OPS-001`, `REQ-OPS-002` et `REQ-OPS-013` sont déjà conformes et servent de socle.

### Résultat attendu

- Operations Center persistant ;
- reprise après refresh/logout/login ;
- états complets et erreurs compréhensibles ;
- drafts persistants ;
- Apply / Discard ;
- retry, réconciliation, `UNKNOWN_OUTCOME`, intervention ;
- progression et vérification post-apply.

### Preuve minimale utile

Intégration ciblée sur persistance/worker/crash/retry et E2E sur reprise d'opération + draft. Failure injection large seulement au checkpoint de phase et en Phase 9.

---

## Phase 6 — Templates, bibliothèque, portabilité et clonage

### Exigences affectées

- `REQ-TPL-001`
- `REQ-TPL-002`
- `REQ-TPL-003`
- `REQ-TPL-004`
- `REQ-TPL-007`
- `REQ-TPL-009`
- `REQ-TPL-010`

`REQ-TPL-005`, `REQ-TPL-006` et `REQ-TPL-008` sont déjà conformes.

### Résultat attendu

- catalogue de templates prêts à l'emploi ;
- adaptation à la Guild cible ;
- version métier/révision de template ;
- preview créé/remappé/ignoré/impossible ;
- suggestions/mappings/rôles manquants ;
- réutilisation du Wizard Phase 4 ;
- clone A -> B sans mutation implicite de la source.

### Preuve minimale utile

Tests ciblés mapping/portabilité/RLS et E2E template + clone A/B.

---

## Phase 7 — Traductions et campagnes

L'audit ne révèle pas de nouveau moteur majeur à reconstruire ici : les familles historiques I18N/UI18N/MSG sont déjà conformes.

La Phase 7 doit surtout :

- appliquer la nouvelle qualité UX ;
- réutiliser les Wizards/primitives des Phases 4-6 ;
- vérifier les parcours traduction/campagne réellement touchés.

Aucun test backend massif si seule la présentation change.

---

## Phase 8 — Diagnostics, paramètres et finition UX transverse

### Exigences affectées

- **`REQ-BOT-005`** : visualisation dashboard de l'endroit où chaque bot peut lire/écrire ;
- `REQ-UXN-016` : ne pas imposer l'acronyme interne DID sans explication ;
- `REQ-UXN-017` : aide contextuelle proche des décisions complexes ;
- **toutes les exigences `REQ-REUSE-*` non conformes** : `001`, `002`, `003`, `004`, `005`, `006`, `007`, `009`, `010`, `011`, `012`.

La Phase 8 réalise aussi un **contrôle transverse** des exigences UX déjà affectées aux Phases 2-7, mais elle n'en devient pas artificiellement propriétaire.

### Résultat attendu

- audit et diagnostics actionnables ;
- bot capability/read-write visualisée ;
- jargon produit maîtrisé et aide contextuelle ;
- primitives UI cohérentes ;
- réutilisation de bibliothèques existantes avant code maison ;
- i18n/a11y/responsive/polish final.

### Preuve minimale utile

Contrôle visuel + i18n/a11y + E2E uniquement pour les interactions critiques ajoutées. Pas de régression backend lourde pour du polish.

---

## Phase 9 — Acceptance produit réelle

### Exigences affectées

- **`REQ-TEST-003`** : preuve Discord sandbox A/B du commit final ;
- **`REQ-QA-001`, `REQ-QA-003` à `REQ-QA-012`** : fermeture finale de la doctrine de preuve et des tests pertinents ;
- toute exigence encore `NON DÉMONTRÉ` après les Phases 2-8 ;
- toute exigence encore `PARTIEL` ou `ABSENT` à ce checkpoint.

`REQ-QA-002` est déjà conforme.

### Résultat attendu

```text
CONFORME: 389
PARTIEL: 0
ABSENT: 0
NON DÉMONTRÉ: 0
```

L'objectif n'est pas d'obtenir ce résultat par déclaration documentaire : chaque changement de statut doit disposer de la preuve minimale adaptée au risque.

### Validation finale utile

Une seule vraie campagne finale : parcours E2E critiques, RLS/RBAC/sécurité des nouvelles fonctions, mutation réelle A/B, failure injection pertinente, régression générale finale et audit des 389 exigences.

---

## Doctrine de tests pour toute la refonte

| Type de changement | Preuve attendue |
|---|---|
| CSS / layout / wording | typecheck/lint/i18n pertinent + contrôle visuel ciblé |
| logique métier | tests unitaires ciblés |
| DB / RLS / RBAC / tenant | intégration ciblée obligatoire |
| mutation Discord / Plan | chemin d'intégration réel ciblé |
| parcours critique | E2E ciblé |
| changement transverse risqué | checkpoint de phase |
| produit final | campagne complète Phase 9 |

Ne pas écrire ou exécuter des tests uniquement pour faire monter un compteur. Ne pas dupliquer sans raison la même preuve dans plusieurs couches.

## Addendum Phase 4 — familles d’accès avancées livrées le 2026-09-16

Le catalogue intention-first couvre maintenant vocal, threads, réactions,
mentions sensibles et accès bot minimal. Toutes ces intentions passent par le
`PolicyResolver`, la Preview et le Plan Engine canoniques ; les flags Discord
ne sont visibles que dans les détails secondaires.

- **couverts** : `REQ-AP-VOC-001/010/020/021/030`, `REQ-AP-THR-001`,
  `REQ-AP-MEN-002/003/004`, `REQ-AP-BOT-001/002/003/004` ;
- **limitation Discord explicitée** : `REQ-AP-REA-001` (`ADD_REACTIONS` ne
  bloque pas la réutilisation d’une réaction existante) et `REQ-AP-MEN-001`
  (`@everyone`/`@here` partagent un bit ; rôle mentionnable global) ;
- **partiels** : `REQ-AP-WRI-022`, `REQ-AP-PRS-013` ;
- **ouverts** : `REQ-AP-PRS-001/010/011/012` et les presets complets associés.

Preuve minimale obtenue : 127 tests backend ciblés, 11 tests Vitest ciblés,
contrôles Ruff/mypy/ESLint/typecheck/i18n/OpenAPI et exactement trois parcours
Playwright du lot. Pas de campagne globale, Discord live, APPLY ou migration.
