# Phase 2 — compte rendu d'implémentation

## Statut

**Implémentation : TERMINÉE**  
**Gate ciblé automatisé : VERT**  
**Validation produit réelle sur Guilds A/B : À FAIRE**

La Phase 2 ne doit pas être déclarée « acceptée produit » tant que le parcours réel sur Discord n'a pas été rejoué depuis l'environnement local avec les vraies Guilds sandbox. Les anciens statuts Stage 10 ne constituent pas cette preuve.

## Ce qui a été réalisé

### 1. Démarrage local reproductible

- `scripts/dev.sh` vérifie la présence de `.env.local` et des paramètres Discord/OAuth obligatoires ;
- démarrage PostgreSQL + Redis ;
- migrations Alembic ;
- démarrage API, bot Gateway, worker, scheduler et frontend ;
- arrêt coordonné des processus ;
- Vite proxifie officiellement `/api`, `/auth`, `/health` et `/ws` vers le backend local ;
- absence de `ARTIFACT_ENCRYPTION_KEY` signalée comme fonctionnalité optionnelle indisponible et non comme panne opaque.

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
- événement invalide : invalidation sûre du cache plutôt qu'un crash du client.

### 6. Portability / fonctionnalités optionnelles

- nouveau `GET /health/features` sans secret ;
- le dashboard sait si OAuth, live events et portability sont disponibles ;
- Templates / Ma bibliothèque / Clone sont désactivés dans la navigation lorsque portability n'est pas configurée ;
- `.env.example` documente `ARTIFACT_ENCRYPTION_KEY` sans fournir de secret.

### 7. Localisation

- nouveaux écrans Phase 2 disponibles en EN / FR / DE / ES ;
- la chaîne française `Aucun serveur Discord admissible trouvé.` est correctement rendue par le pack Phase 2 ;
- contrôle des littéraux visibles conservé ; seuls le logo `D` / `DID` et les glyphes de raccourci non linguistiques sont autorisés hors catalogue.

## Gate ciblé — pas de « 50 000 tests »

Un workflow dédié `.github/workflows/ui-phase2.yml` ne lance que :

1. `npm ci` ;
2. `npm run typecheck` ;
3. le contrôle i18n des chaînes visibles ;
4. Chromium ;
5. **2 use cases Playwright Phase 2 seulement**.

Les deux use cases sont :

- `PENDING_SETUP -> Configure -> import -> activation -> overview` ;
- utilisateur non owner/admin -> setup bloqué et aucune action exécutable.

Dernier gate exécuté sur le code Phase 2 : **SUCCESS** (`aae56c0c72ea5e0c18fcd3d12138c0d08154a874`). TypeScript : PASS. i18n : PASS. Playwright Phase 2 : 2/2 PASS.

## Relecture des défauts Phase 1

| Défaut | Situation après Phase 2 | Preuve actuelle |
|---|---|---|
| P0-001 découverte A/B | mécanisme Gateway instrumenté + projection `GUILD_CREATE` utilisée | code + live à confirmer |
| P0-002 onboarding absent | **corrigé** | code + E2E ciblé |
| P0-003 structure réelle vide | onboarding programme le vrai `INITIAL_SYNC` | code + live à confirmer |
| P0-004 `/api/v1/guilds` 500 | route de découverte/état remaniée, sans bootstrap manuel côté UI | code + live à confirmer |
| P0-005 `/audit` 500 | endpoint et dépôt restent cohérents statiquement ; cause baseline non reproduite | **reste à confirmer/reproduire en live** |
| P0-006 boucle WebSocket | **corrigée côté client** pour 4401/4403/offline + backoff | code + typecheck + comportement live à confirmer |
| P0-007 lancement local incohérent | **corrigé** | script + proxy versionnés |
| P1-010 portability non configurée | **corrigé côté UX** par préflight + désactivation explicite | code + E2E shell |
| P2-001 `Àucun serveur` | **corrigé à l'affichage** par le catalogue Phase 2 | i18n gate |

## Ce qu'il manque réellement

Il ne manque plus de chantier d'implémentation prévu dans la Phase 2. Il manque la **preuve sur l'environnement Discord réel** :

1. partir de l'état local voulu et démarrer avec `scripts/dev.sh` ;
2. OAuth réel ;
3. vérifier que Guild A et Guild B apparaissent sans script manuel ;
4. prendre une Guild `PENDING_SETUP` et faire tout l'assistant ;
5. vérifier que le vrai import restitue les salons/rôles ;
6. vérifier l'activation ;
7. recharger la page et vérifier session/contexte ;
8. vérifier `/api/v1/guilds` et `/audit` sans HTTP 500 ;
9. vérifier la connexion WebSocket ou son état dégradé propre ;
10. valider visuellement le nouveau shell contre `Esquisse 1.png`.

Si `/audit` ou `/guilds` reproduit encore un 500, il devra rester P0 et être corrigé à partir du traceback réel avant de fermer définitivement la Phase 2.

## Décision de sortie

La branche peut passer en **validation utilisateur Phase 2**, mais pas encore en Phase 3 comme si la preuve live était déjà acquise. Une fois le parcours A/B validé ou les derniers P0 live corrigés, la Phase 2 pourra être marquée complètement close.
