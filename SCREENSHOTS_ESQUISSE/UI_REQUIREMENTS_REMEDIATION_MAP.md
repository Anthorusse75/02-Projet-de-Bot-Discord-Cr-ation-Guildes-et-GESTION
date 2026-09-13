# Refonte UI — affectation des écarts d'audit aux phases existantes

## But

Ce document relie les exigences `PARTIEL`, `ABSENT` et `NON DÉMONTRÉ` de l'audit étendu aux **9 phases UI existantes**.

**Règle ferme : aucune nouvelle phase UI n'est créée.** Les lots internes servent uniquement à ordonner le travail dans une phase.

Audit source : `docs/10_implementation/11_REQUIREMENTS_IMPLEMENTATION_AUDIT.md`.

Snapshot audité : 389 exigences, dont 265 conformes et 124 non totalement conformes au moment de l'audit.

---

## Phase 1 — Audit/baseline

**État : terminée.**

Aucune exigence n'est renvoyée dans cette phase. Le nouvel audit complète la connaissance du produit mais ne provoque pas une nouvelle Phase 1.

---

## Phase 2 — Runtime/onboarding/fondations visuelles

**État : implémentée.**

Pas de nouveau chantier structurel issu de l'audit. Les preuves live A/B globales seront consolidées en Phase 9 afin d'éviter des campagnes répétitives pendant la refonte.

---

## Phase 3 — Explorateur / structure / DnD

**État : terminée.**

La Phase 3 n'est pas rouverte. Les raffinements UX découverts après sa clôture sont absorbés par la Phase 8.

---

## Phase 4 — Rôles, permissions et politiques

### Exigences affectées

- **`REQ-POL-001` à `REQ-POL-053`** : toute la famille Policy est à fermer dans cette phase ; le moteur générique manque encore alors que quelques policies spécialisées existent déjà.
- **`REQ-WIZ-001` à `REQ-WIZ-014`** : le socle Wizard est construit ici, puis réutilisé en Phases 6/7 sans recréer un second framework.
- **`REQ-PERMX-010`** : raccord complet du moteur canonique de permissions au Policy Engine/Wizard.
- **`REQ-UXN-009`** : cohérence UI avec les rôles cumulés et le calcul réel des permissions.

### Résultat attendu

- Policy Engine générique et tenant-safe ;
- policies natives/personnalisées ;
- priorité/héritage/conflits/verrouillage ;
- explain/preview/remédiation ;
- Wizard avec rôle manquant et `+ Créer un rôle` ;
- sortie vers le Plan Engine, sans mutation Discord directe.

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

## Phase 8 — Diagnostics, paramètres et finition UX

### Exigences affectées

- **`REQ-BOT-005`** : visualisation dashboard de l'endroit où chaque bot peut lire/écrire.
- `REQ-UXN-003`
- `REQ-UXN-004`
- `REQ-UXN-005`
- `REQ-UXN-006`
- `REQ-UXN-007`
- `REQ-UXN-010`
- `REQ-UXN-011`
- `REQ-UXN-012`
- `REQ-UXN-013`
- `REQ-UXN-014`
- `REQ-UXN-015`
- `REQ-UXN-016`
- `REQ-UXN-017`
- **toutes les exigences `REQ-REUSE-*` non conformes** : `001`, `002`, `003`, `004`, `005`, `006`, `007`, `009`, `010`, `011`, `012`.

`REQ-UXN-001`, `002`, `008`, `018` et `REQ-REUSE-008` sont déjà conformes.

### Résultat attendu

- rename second clic/F2/contextuel ;
- naming/emoji lorsque prévu ;
- labels et concepts compréhensibles ;
- diagnostics actionnables ;
- bot capability/read-write visualisée ;
- primitives UI cohérentes ;
- réutilisation de bibliothèques existantes avant code maison ;
- i18n/a11y/responsive/polish final.

### Preuve minimale utile

Contrôle visuel + i18n/a11y + E2E uniquement pour les interactions critiques ajoutées. Pas de régression backend lourde pour du polish.

---

## Phase 9 — Acceptance produit réelle

### Exigences affectées

- **`REQ-TEST-003`** : preuve Discord sandbox A/B du commit final ;
- **`REQ-QA-001`, `REQ-QA-003` à `REQ-QA-012`** ;
- toute exigence encore `NON DÉMONTRÉ` après les Phases 4-8 ;
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
