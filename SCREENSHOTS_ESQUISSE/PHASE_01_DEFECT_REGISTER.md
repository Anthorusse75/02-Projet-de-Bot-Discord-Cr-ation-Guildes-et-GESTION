# Phase 1 — Registre des défauts

Statut : **BASELINE TERMINÉE**  
Branche : `ui/complete-redesign`

Ce registre est le backlog obligatoire de la refonte. Un défaut P0/P1 ne peut pas disparaître parce qu'un test historique est vert : il doit être corrigé puis démontré par son use case.

## P0 — Bloquants produit

| ID | Défaut | Cause connue / état d'investigation | Correction propriétaire | Preuve de fermeture |
|---|---|---|---|---|
| P0-001 | A/B non découvertes automatiquement sur base vierge | Le chemin `READY -> GUILD_CREATE -> normalize -> RuntimeRepository.ingest_gateway_event -> PENDING_SETUP` existe, mais n'a pas matérialisé A/B dans l'essai réel. Le runtime bot a deux défauts de diagnostic : un bot sans token peut démarrer sans client, et un `GatewayContractError` incrémente seulement un compteur sans log exploitable. Cause exacte de l'essai à reproduire avec instrumentation. | Phase 2 | Base vide, démarrage normal, A/B deviennent PENDING_SETUP sans script manuel. |
| P0-002 | Assistant onboarding §5.4 absent | Cause exacte : frontend absent. `/bootstrap` existe mais `GuildSelectPage` ne l'oriente pas. | Phase 2 | Wizard vérifie bot, acteur, owner/admin, bot perms, import, audit, limites, dashboard, activation. |
| P0-003 | Structure réelle vide après contournement manuel | `_project_guild_create` sait projeter channels/threads/roles. Le fait que l'UI soit vide montre que la chaîne initiale n'a pas produit le cache attendu ou que la lecture n'accède pas à l'état projeté. À instrumenter avec P0-001. | Phase 2 | A affiche catégories/salons/threads réels immédiatement après onboarding, sans seed. |
| P0-004 | `GET /api/v1/guilds` a renvoyé 500 | Le code n'offre pas de cause statique unique certaine. Le chemin combine OAuth discovery, authorization et installation. Reproduction avec correlation id + traceback obligatoire. | Phase 2 | 200 déterministe ou Problem Details localisé; jamais 500 sur état utilisateur attendu. |
| P0-005 | `GET /api/v1/guilds/{id}/audit` a renvoyé 500 | Endpoint et repository existent. AuthorizationDenied est globalement mappé; le 500 provient donc d'une autre erreur runtime/DB/serialization à capturer. | Phase 2 puis Phase 8 pour UX | 200 avec audit ou erreur métier localisée, puis affichage lisible. |
| P0-006 | WebSocket Guild échoue et reconnecte en boucle | Backend ferme avant accept en 4401 si session absente ou 4403 si `STRUCTURE_READ` refusé; après accept il dépend du pubsub. Frontend ignore le close code et retry indéfiniment. En dev, l'absence de proxy WS officiel est aussi un défaut certain. | Phase 2 | Socket same-origin connecté; close code expliqué; backoff borné/état dégradé; live A n'ingère jamais B. |
| P0-007 | Démarrage local officiel incohérent | Cause exacte : README lance API sur 8000 puis Vite séparément; `vite.config.ts` ne proxy ni `/api`, ni `/auth`, ni `/ws`, alors que le frontend utilise des URLs relatives et OAuth redirige vers localhost:8000. | Phase 2 | Une procédure/commande documentée démarre services nécessaires sans `vite.local.config.ts` manuel. |

## P1 — Fonctions importantes incomplètes/cassées

| ID | Défaut | Cause / constat | Correction propriétaire | Preuve de fermeture |
|---|---|---|---|---|
| P1-001 | UI actuelle rejetée | Shell/CSS/rendu ne correspondent ni à `Esquisse 1.png` ni à l'objectif « administration visuelle qui simplifie radicalement ». Chevauchements constatés. | Phases 2 à 8 | Validation visuelle utilisateur écran par écran. |
| P1-002 | Roles est lecture seule | `RolesScreen` liste les rôles mais ne crée/modifie/supprime/réordonne rien. | Phase 4 | CRUD + reorder réels via plan, vérifiés Discord. |
| P1-003 | Permissions n'administre pas les permissions | `PermissionsScreen` est surtout un formulaire Explain/View As et exige des Snowflakes bruts. | Phase 4 | Mode simple humain + expert + édition + impact + apply + View As. |
| P1-004 | Diagnostics trop pauvre | Écran = couverture/fraîcheur alors que le backend expose user/bot capabilities, causes/remédiations. | Phase 2 + 8 | Une permission bot manquante donne cause exacte et remédiation. |
| P1-005 | Templates inutilisable comme gestionnaire | Écran = cartes lecture seule; 503 si portability non configurée. | Phase 6 | preview/create/use + configuration startup correcte. |
| P1-006 | Bibliothèque incomplète | Écran = liste + export; pas de workflow clair import/réutilisation; 503 sans portability. | Phase 6 | sauvegarde -> preview -> import/clone -> résultat. |
| P1-007 | Clone est technique, pas humain | L'utilisateur saisit un ID source brut et reçoit essentiellement un plan ID. | Phase 6 | sélection graphique source/destination, mappings, conflits, modes, preview. |
| P1-008 | Portability peut être exposée non configurée | `PORTABILITY_NOT_CONFIGURED` est un 503 backend légitime, mais le produit démarre tout de même en présentant les écrans comme disponibles. | Phase 2 + 6 | préflight startup + UI feature state explicite, aucune surprise 503. |
| P1-009 | Audit UI trop pauvre | L'écran ne valorise pas initiateur/plan/correlation/drift; endpoint a en plus le P0-005. | Phase 8 | timeline lisible + filtres + détail/plan/correlation. |
| P1-010 | Plans manque de diff/impact lisible | Pipeline présent mais expérience centrée sur boutons et statuts; pas de vraie lecture avant/après. | Phase 5 | diff, risque, opérations, dépendances et impact compréhensibles. |
| P1-011 | Drag & Drop visuellement insuffisant | `PointerGestureManager` est cohérent avec l'architecture §22; le problème est l'absence d'overlay/affordance/tri riche et de preuve live, pas l'existence du manager. `dnd-kit` peut compléter collision/overlay/clavier. | Phase 3 | drag gauche/droit + ghost/drop zone + clavier + plan + résultat. |
| P1-012 | Explorer ne ressemble pas à un explorateur moderne | Rendu actuel emploie `◇`/`#` et un panneau propriétés minimal. | Phase 3 | arborescence premium conforme Esquisse 1, icons/types/properties/actions. |
| P1-013 | Traductions : fonctionnalité riche mais UX à reconstruire | Beaucoup de fonctions présentes, mais densité/présentation non alignées avec le design cible et non requalifiées live. | Phase 7 | create/link/clone/preview/drift sur vrai tenant. |
| P1-014 | Campagnes : fonctionnalité riche mais écran monolithique | `CampaignCenter` concentre création, cibles, schedules, simulation, variantes, deliveries. | Phase 7 | wizard/workspace clair + use cases publication/simulation réels. |
| P1-015 | États erreur trop génériques | Plusieurs écrans retombent sur `ErrorState` générique et ne donnent pas toujours cause/remédiation métier. | Phases 2 à 8 | chaque erreur attendue a message localisé + action possible. |
| P1-016 | Tests historiques ne prouvent pas certains chemins utilisateur | Certaines fixtures préparent directement installations/états. | Phases 2 à 9 | E2E use-case part de l'état réel attendu, pas d'injection qui saute le sujet testé. |

## P2 — Finition / défauts visibles

| ID | Défaut | Cause exacte | Phase |
|---|---|---|---|
| P2-001 | `Àucun serveur Discord admissible trouvé.` | Typo littérale dans `frontend/src/localization/catalog.ts`, pas un problème d'encodage runtime. | 2 / 8 |
| P2-002 | Chevauchements / alignements | Design/CSS actuel non robuste à la largeur réelle. | 2..8 |
| P2-003 | États de connexion bruyants | `useGuildSocket` retry sans expliquer les close codes. | 2 / 8 |
| P2-004 | Vocabulaire trop technique | IDs bruts, concepts backend exposés trop tôt. | 3 / 4 / 6 / 7 |

---

# Ordre obligatoire de résolution

```text
P0-007 lancement local
    ↓
P0-001 découverte Gateway
    ↓
P0-003 structure initiale
    ↓
P0-002 onboarding complet
    ↓
P0-004 /guilds 500 + P0-005 /audit 500 + P0-006 WS
    ↓
Fondations visuelles Esquisse 1
    ↓
Explorer / Roles / Permissions / Plans / Portability / Traductions / Campagnes
```

L'ordre n'interdit pas des corrections parallèles évidentes, mais empêche de construire une superbe UI au-dessus d'une baseline qui ne sait toujours pas se découvrir elle-même.

# Politique de fermeture

Un défaut P0/P1 est fermé seulement lorsque :

1. la correction existe ;
2. le use case ciblé passe dans le navigateur ;
3. s'il mute Discord, le résultat réel est vérifié ;
4. un reload conserve l'état attendu ;
5. un E2E ciblé protège le parcours ;
6. pour les parcours critiques Discord, A/B servent de preuve réelle.
