# Phase 2 — compte rendu d'implémentation

## Statut

**Implémentation : TERMINÉE**  
**Gate ciblé automatisé : VERT**  
**Validation produit réelle sur Guilds A/B : EN COURS**

La Phase 2 ne doit pas être déclarée « acceptée produit » tant que le parcours réel sur Discord n'a pas été rejoué depuis l'environnement local avec les vraies Guilds sandbox. Les anciens statuts Stage 10 ne constituent pas cette preuve.

## Ce qui a été réalisé

### 1. Démarrage local reproductible

- `scripts/dev.sh` vérifie la présence de `.env.local` et des paramètres Discord/OAuth obligatoires ;
- démarrage PostgreSQL + Redis ;
- migrations Alembic ;
- démarrage API, bot Gateway, worker, scheduler et frontend ;
- arrêt coordonné des processus ;
- Vite proxifie officiellement `/api`, `/auth`, `/health` et `/ws` vers le backend local ;
- absence de `ARTIFACT_ENCRYPTION_KEY` signalée comme fonctionnalité optionnelle indisponible et non comme panne opaque ;
- le process API local est lancé avec un runtime WebSocket explicite (`websockets==15.0.1`) afin que les upgrades `/ws` soient réellement supportés par Uvicorn sans modifier `uv.lock` au démarrage.

### 2. Découverte Gateway et diagnostic

- le bot échoue immédiatement si le token obligatoire manque ;
- la connexion Gateway, l'identité application/bot, `READY`, `GUILD_CREATE`, les paquets rejetés et les erreurs de projection sont journalisés explicitement ;
- la création `PENDING_SETUP` et la projection du `GUILD_CREATE` existantes sont maintenant observables au lieu d'échouer silencieusement.

### 3. Parcours d'onboarding réel

Backend :

- `GET /api/v1/guilds` expose l'état d'installation, l'accès dashboard, l'éligibilité au bootstrap et la cause de blocage ;
- `GET /api/v1/guilds/{id}/onboarding` expose les vérifications de setup ;
- `POST /api/v1/guilds/{id}/onboarding/import` programme le vrai `INITIAL_SYNC` durable ;
- `POST /api/v1/guilds/{id}/onboarding/activate` n'active le tenant que si les préconditions sont satisfaites ;
- la structure initiale passe par le worker/synchroniseur Discord normal, pas par une injection de fixtures.

Frontend :

- écran de sélection des Guilds complètement refait ;
- distinction ACTIVE / PENDING_SETUP / BLOQUÉ ;
- Guild non administrable : bouton désactivé + cause compréhensible ;
- assistant de première configuration avec les étapes bot, identité configurateur, permissions, import, audit, configuration dashboard et activation ;
- progression d'import et comptage salons/threads/rôles ;
- affichage des opérations bot `CAN / CANNOT / UNKNOWN` ;
- activation puis ouverture de la vue serveur.

### 4. Nouveau socle visuel basé sur `Esquisse 1.png`

- nouveau design system dark navy / bleu-violet ;
- nouveau login ;
- nouvelle sélection de serveurs ;
- nouveau shell desktop premium ;
- sidebar structurée ;
- serveur actif + serveurs récents ;
- recherche globale / palette de commandes ;
- header avec état de connexion et langue ;
- nouvelle vue d'ensemble serveur ;
- cartes structure / rôles / couverture / connexion ;
- résumé des capabilities du bot ;
- harmonisation visuelle des surfaces historiques présentes dans le shell.

Cette phase pose la direction visuelle commune. La reconstruction profonde de l'explorateur de structure et de son Drag & Drop reste volontairement en Phase 3.

### 5. WebSocket et fonctionnement dégradé

- états `live`, `reconnecting`, `offline`, `unauthorized` ;
- aucune reconnexion infinie sur fermeture serveur `4401` / `4403` ;
- arrêt des retries lorsque le navigateur est hors ligne ;
- reprise à l'événement `online` ;
- backoff borné pour les vraies coupures temporaires ;
- événement invalide : invalidation sûre du cache plutôt qu'un crash du client ;
- correction live du 13/09/2026 : Uvicorn était lancé sans moteur WebSocket, ce qui produisait `Unsupported upgrade request`, un faux `GET /ws/...` en HTTP, des `404` et des `ECONNABORTED` dans Vite. `scripts/dev.sh` fournit maintenant explicitement `websockets==15.0.1` au process API.

### 6. Portability / fonctionnalités optionnelles

- nouveau `GET /health/features` sans secret ;
- le dashboard sait si OAuth, live events et portability sont disponibles ;
- Templates / Ma bibliothèque / Clone sont désactivés dans la navigation lorsque portability n'est pas configurée ;
- `.env.example` documente `ARTIFACT_ENCRYPTION_KEY` sans fournir de secret.

### 7. Localisation

- nouveaux écrans Phase 2 disponibles en EN / FR / DE / ES ;
- la chaîne française `Aucun serveur Discord admissible trouvé.` est correctement rendue par le pack Phase 2 ;
- contrôle des littéraux visibles conservé ; seuls le logo `D` / `DID` et les glyphes de raccourci non linguistiques sont autorisés hors catalogue.

### 8. Audit — correction du défaut de schéma découvert en live

Le test réel du 13/09/2026 a reproduit le P0 `/audit` avec :

`UndefinedColumnError: column "plan_id" does not exist`

La cause était structurelle : `RuntimeRepository.audit_events()` lisait `plan_id`, mais `internal_audit_events` avait été créé en Stage 03 sans les colonnes structurées prévues par l'architecture (`plan_id`, `operation_id`, `request_id`). Le Plan Engine avait ensuite conservé `plan_id` et `operation_id` uniquement dans `data_json`.

Correction :

- migration `0035_ui_phase2` ;
- ajout de `plan_id`, `operation_id`, `request_id` en UUID nullable ;
- backfill des identifiants UUID historiques déjà présents dans `data_json` ;
- index tenant + plan et tenant + opération ;
- trigger de compatibilité qui projette automatiquement les anciens writers `data_json` vers les colonnes structurées ;
- aucune suppression des payloads historiques ;
- test PostgreSQL ciblé qui reproduit l'ancien shape d'écriture et appelle réellement `RuntimeRepository.audit_events()`.

## Gate ciblé — pas de « 50 000 tests »

Le workflow dédié `.github/workflows/ui-phase2.yml` lance uniquement les contrôles utiles à cette phase.

### UI

1. `npm ci` ;
2. `npm run typecheck` ;
3. contrôle i18n des chaînes visibles ;
4. Chromium ;
5. **2 use cases Playwright Phase 2 seulement**.

Les deux use cases sont :

- `PENDING_SETUP -> Configure -> import -> activation -> overview` ;
- utilisateur non owner/admin -> setup bloqué et aucune action exécutable.

### Régressions runtime ajoutées après le test live

1. PostgreSQL + Redis réels ;
2. `alembic upgrade head` jusqu'à `0035_ui_phase2` ;
3. résolution réelle du runtime `websockets==15.0.1` ;
4. **un seul test PostgreSQL ciblé** : `test_phase02_audit_runtime.py`.

Le job `phase2-runtime-regressions` du run GitHub Actions `34747098419` est **SUCCESS** : migration PASS, runtime WebSocket PASS, régression audit PASS.

## Relecture des défauts Phase 1

| Défaut | Situation après Phase 2 | Preuve actuelle |
|---|---|---|
| P0-001 découverte A/B | mécanisme Gateway instrumenté + projection `GUILD_CREATE` utilisée | code + live à confirmer |
| P0-002 onboarding absent | **corrigé** | code + E2E ciblé |
| P0-003 structure réelle vide | onboarding programme le vrai `INITIAL_SYNC` | code + live à confirmer |
| P0-004 `/api/v1/guilds` 500 | route de découverte/état remaniée, sans bootstrap manuel côté UI | code + live à confirmer |
| P0-005 `/audit` 500 | **corrigé après reproduction live** par migration 0035 + compatibilité audit | PostgreSQL ciblé PASS + live à revalider |
| P0-006 boucle WebSocket | **corrigée côté client et runtime local** : 4401/4403/offline + backoff + moteur WS Uvicorn | runtime gate PASS + live à revalider |
| P0-007 lancement local incohérent | **corrigé** | script + proxy versionnés |
| P1-010 portability non configurée | **corrigé côté UX** par préflight + désactivation explicite | code + E2E shell |
| P2-001 `Àucun serveur` | **corrigé à l'affichage** par le catalogue Phase 2 | i18n gate |

## Ce qu'il manque réellement

Il ne manque plus de chantier d'implémentation prévu dans la Phase 2. Il manque la fin de la **preuve sur l'environnement Discord réel** :

1. redémarrer avec la branche à jour pour appliquer `0035_ui_phase2` et le runtime WebSocket ;
2. OAuth réel ;
3. vérifier que Guild A et Guild B apparaissent sans script manuel ;
4. prendre une Guild `PENDING_SETUP` et faire tout l'assistant si nécessaire ;
5. vérifier que le vrai import restitue les salons/rôles ;
6. vérifier l'activation ;
7. recharger la page et vérifier session/contexte ;
8. vérifier `/api/v1/guilds` et `/audit` sans HTTP 500 ;
9. vérifier que le WebSocket passe réellement en `live` sans `Unsupported upgrade request` / `404` / `ECONNABORTED` ;
10. valider visuellement le nouveau shell contre `Esquisse 1.png`.

Tout nouveau défaut trouvé pendant ce parcours reste bloquant pour la fermeture de Phase 2 et doit être corrigé sur cette branche avant Phase 3.

## Décision de sortie

La branche reste en **validation utilisateur Phase 2**. Les deux défauts concrets découverts lors du premier passage live ont été corrigés et couverts par un gate ciblé. La Phase 2 ne sera marquée complètement close qu'après le prochain passage A/B réel sans P0 restant.

## 9. Complément post-audit ciblé — REQ-WIZ-011 / REQ-WIZ-012

Ce complément réinspecte le code de `ui/complete-redesign` après l'audit réalisé sur `stage/10-acceptance`. Il ne crée ni second Wizard ni nouvelle phase.

### REQ-WIZ-011 — neuf contrôles du premier setup

Statut audit antérieur : **NON DÉMONTRÉ**. Statut après réinspection et correction : **CONFORME**.

| # | Contrôle | Implémentation réelle réinspectée | Correction ciblée |
|---:|---|---|---|
| 1 | Bot présent | `guilds.py` produit `bot_present` depuis l'installation/cache réel. | Ligne dédiée rendue dans l'onboarding. |
| 2 | Identité du configurateur | La session `/me` fournit l'utilisateur Discord authentifié. | Ligne distincte avec nom et snowflake, au lieu de la confondre avec le bootstrap. |
| 3 | Droit de bootstrap | `can_bootstrap` / `configurator_verified` sont calculés côté backend. | Ligne dédiée et état bloqué explicite. |
| 4 | Capabilities bot réelles | `bot_operations` expose les décisions par opération. | Ligne dédiée et détail de chaque décision. |
| 5 | Import initial | `structure_imported` suit le job `INITIAL_SYNC`. | Déjà explicite, conservé. |
| 6 | Audit initial | `initial_audit_complete` suit l'audit initial des capabilities bot, distinct de l'état d'import. | Ligne dédiée, conservée. |
| 7 | Limites / contraintes | Les opérations non `CAN`, causes et remédiations étaient déjà renvoyées. | Ligne dédiée avec nombre de contraintes et explications humaines. |
| 8 | Configuration proposée | `dashboard_configuration_ready` matérialise la configuration utilisable. | Ligne dédiée, conservée. |
| 9 | Activation tenant | `complete` et l'action d'activation pilotent le passage à `ACTIVE`. | Ligne dédiée, conservée. |

L'écart réel était donc principalement de présentation : l'UI montrait sept lignes et fusionnait identité/bootstrap ainsi que permissions/contraintes. `OnboardingPage.tsx` expose désormais exactement neuf contrôles distincts, adossés au snapshot backend existant.

### REQ-WIZ-012 — moindre privilège explicable

Statut audit antérieur : **PARTIEL**. Statut après réinspection et correction : **CONFORME**.

Le moteur existant `permissions/capabilities.py` associait déjà chaque `BotOperation` aux seules permissions Discord requises et propageait `CAN`, `CANNOT` ou `UNKNOWN` sans demander `ADMINISTRATOR`. Une incapacité restait limitée à l'opération concernée. Le manque réel était l'explication utilisateur : chips techniques, causes en attribut `title`, pas de justification lisible des permissions.

L'onboarding affiche maintenant, opération par opération :

- le résultat `CAN` / `CANNOT` / `UNKNOWN` et sa signification ;
- les permissions précises et leur finalité fonctionnelle ;
- une cause compréhensible pour permission, contexte salon/rôle, intent ou installation manquante ;
- une remédiation lorsque le backend en fournit une ;
- l'engagement explicite de moindre privilège et l'absence de demande `ADMINISTRATOR` par commodité.

Une permission absente ne rend indisponibles que les opérations dont la décision n'est pas `CAN`; les autres restent détaillées et utilisables.

### Preuves ciblées

- `npm run typecheck` : PASS ;
- `npm run i18n:check` : PASS, scan des littéraux visibles et 3 tests catalogue ;
- ESLint limité aux fichiers Phase 2/3 modifiés : PASS ;
- `phase02-redesign.spec.ts` : 2 scénarios PASS, dont neuf lignes de setup, moindre privilège, permissions expliquées, causes lisibles et blocage d'un non-administrateur ;
- aucune API, règle d'autorisation, migration ou mutation Discord live n'a été modifiée pour ce complément.
