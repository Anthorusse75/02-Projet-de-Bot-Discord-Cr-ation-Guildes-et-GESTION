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

- **`REQ-POL-001` à `REQ-POL-053`** : toute la famille Policy est à fermer dans cette phase ; le moteur générique manque encore alors que quelques policies spécialisées existent déjà.
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
