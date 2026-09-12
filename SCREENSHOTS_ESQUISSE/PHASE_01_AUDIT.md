# Phase 1 — Audit de conformité et baseline exécutable

Statut : **EN COURS**  
Branche : `ui/complete-redesign`  
Référence visuelle : `SCREENSHOTS_ESQUISSE/Esquisse 1.png`

## 1. Règle d'audit

Les documents suivants sont la source de vérité :

- `docs/00_reference/01_SPECIFICATIONS_FONCTIONNELLES_DISCORD_INFRA_DESIGNER.md`
- `docs/00_reference/02_ARCHITECTURE_TECHNIQUE_DISCORD_INFRA_DESIGNER.md`

Le fichier `docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md` est traité comme une **trace historique à ré-auditer**, pas comme une preuve suffisante en soi.

Une exigence UI/use case ne sera considérée conforme que si l'implémentation et un parcours réel ou un E2E pertinent démontrent le comportement attendu.

## 2. Inventaire frontend actuel

Routes actuellement exposées par `frontend/src/app/App.tsx` :

- `/login`
- `/guilds`
- `/guild/:guildId/structure`
- `/guild/:guildId/roles`
- `/guild/:guildId/permissions`
- `/guild/:guildId/plans`
- `/guild/:guildId/diagnostics`
- `/guild/:guildId/audit`
- `/guild/:guildId/templates`
- `/guild/:guildId/library`
- `/guild/:guildId/clone`
- `/guild/:guildId/translations`
- `/guild/:guildId/campaigns`

Les surfaces existent donc, mais leur existence ne vaut pas conformité fonctionnelle.

## 3. Écarts critiques déjà confirmés

### P0-001 — Première découverte des Guilds cassée dans le parcours réel

**Référence** : spécifications §5, notamment assistant de première configuration.  
**Constat réel** : après OAuth sur une base neuve, les Guilds A/B n'apparaissaient pas. Il a fallu exécuter un script manuel pour créer/activer les `guild_installations`.

**Relecture code importante** : le runtime possède bien un chemin automatique prévu. `DiscordGatewayClient.on_socket_response()` ingère les dispatches Gateway ; `RuntimeRepository.ingest_gateway_event()` traite `GUILD_CREATE`, crée/actualise `guild_installations` en `PENDING_SETUP`, puis `_project_guild_create()` projette catégories/salons/threads/rôles. L'absence d'un appel à `record_detected()` dans `on_ready()` n'est donc **pas** à elle seule la cause du défaut.

**Conclusion actuelle** : le mécanisme existe dans le code mais **n'a pas produit le résultat attendu lors du lancement réel**. La cause exacte doit être reproduite avec les logs du process bot : dispatch `GUILD_CREATE` non reçu, normalisation rejetée, transaction/projection en échec, identité bot non liée, ou autre erreur runtime.

**Impact** : le parcours `installation bot -> découverte -> PENDING_SETUP` n'est pas fiable dans les conditions réellement testées.

**Statut** : NON CONFORME EN PRATIQUE / CAUSE RACINE À ISOLER — Phase 1.

---

### P0-002 — Assistant de première configuration absent de l'UI

**Référence** : spécifications §5.4. L'assistant doit vérifier bot, configurateur, owner/ADMINISTRATOR, permissions bot, importer la structure, effectuer un audit initial, présenter les limitations, configurer le dashboard puis activer le tenant.

**Constat code** : `GuildSelectPage.tsx` affiche un badge `pending` mais ne propose qu'une action de sélection. Il n'existe pas de parcours visuel complet d'onboarding dans cette page.

**Impact** : même lorsqu'une installation existe en `PENDING_SETUP`, le produit n'accompagne pas l'utilisateur dans le bootstrap prévu par la référence.

**Statut** : NON CONFORME — correction obligatoire Phase 2.

---

### P0-003 — Structure réelle non disponible dans le parcours testé

**Référence** : REQ-STR-001 et §8 : arborescence fidèle catégories/salons/threads.

**Constat réel** : après création/activation manuelle des installations A/B, l'écran Structure affichait `Aucune catégorie ou salon visible` sur un serveur Discord qui contient pourtant une structure réelle.

**Relecture code** : `_project_guild_create()` sait projeter directement `channels`, `threads` et `roles` du dispatch initial. L'absence de structure est donc probablement liée au même défaut de chaîne Gateway observé pour P0-001, ou à un échec ultérieur de lecture/projection. Le worker n'est pas requis pour cette projection initiale : elle est faite dans `RuntimeRepository.ingest_gateway_event()`.

**Impact** : le cœur du produit n'est pas exploitable dans le parcours réel actuel.

**Statut** : NON CONFORME / cause racine à isoler en Phase 1.

---

### P0-004 — Erreurs serveur sur parcours réel

Erreurs observées dans le navigateur :

- `GET /api/v1/guilds` -> HTTP 500 ;
- `GET /api/v1/guilds/{guild_id}/audit` -> HTTP 500 ;
- WebSocket `/ws/v1/guilds/{guild_id}` -> échec/reconnexion en boucle.

**Impact** : navigation non fiable et bruit permanent côté navigateur.

**Action Phase 1** : reproduire chaque erreur, capturer le traceback backend, corriger la cause racine avant de considérer les écrans concernés fonctionnels.

**Statut** : NON CONFORME — P0.

---

### P0-005 — Lancement local non cohérent avec l'OAuth et l'API

**Référence architecture** : environnement de développement simple Windows 11, frontend React, API/Bot/Worker/Scheduler en processus séparés mais orchestrables proprement.

**Constat code** : `frontend/vite.config.ts` contient seulement le plugin React et aucun proxy `/api`, `/auth`, `/ws`. Le frontend appelle pourtant les API sur des chemins relatifs.

**Constat réel** : il a fallu créer manuellement un `vite.local.config.ts` temporaire pour lancer l'UI sur `localhost:8000` et proxyfier FastAPI sur `127.0.0.1:8001`.

**Impact** : le dépôt n'offre pas actuellement un parcours de développement local reproductible sans bricolage.

**Statut** : NON CONFORME — correction Phase 2.

---

### P1-001 — Architecture Drag & Drop non conforme à la pile cible

**Référence architecture §3.4** : `dnd-kit` pour le drag & drop ; Radix UI / shadcn/ui ou primitives accessibles similaires.

**Constat package** : `frontend/package.json` n'inclut ni `dnd-kit`, ni Radix/shadcn.

**Constat code** : `StructureScreen.tsx` repose sur un `PointerGestureManager` maison et des calculs `document.elementFromPoint(...)`.

**Impact** : la sémantique de drag existe partiellement, mais la qualité visuelle, les overlays, les drop zones, les interactions clavier et la maintenabilité ne correspondent pas à la direction produit validée.

**Statut** : PARTIEL / NON CONFORME TECHNIQUEMENT — migration Phase 3.

---

### P1-002 — UI actuelle rejetée et non conforme à l'objectif produit

**Référence §1** : plateforme d'administration visuelle destinée à `simplifier radicalement` la création, restructuration et exploitation de serveurs Discord complexes.

**Constat réel** : interface rejetée visuellement ; alignements et chevauchements observés ; hiérarchie pauvre ; faible affordance ; très loin de l'expérience explorateur/desktop souhaitée.

**Décision produit** : l'UI actuelle n'est pas conservée comme direction graphique. `Esquisse 1.png` devient la référence visuelle de la branche.

**Statut** : NON CONFORME VISUELLEMENT — refonte complète Phases 2 à 8.

---

### P1-003 — Portabilité exposée alors que le runtime local n'est pas configuré

**Constat réel** :

- `/api/v1/guilds/{guild_id}/templates` -> 503 ;
- `/api/v1/me/portable-artifacts` -> 503.

**Cause code connue** : la couche portability lève `PORTABILITY_NOT_CONFIGURED` si la clé de chiffrement artifact n'est pas configurée.

**Impact** : l'UI expose des fonctions qui semblent cassées au lieu de guider l'utilisateur ou de garantir la configuration requise au démarrage.

**Statut** : NON CONFORME AU PARCOURS PRODUIT — correction Phase 6, prérequis de configuration Phase 2.

---

### P1-004 — Les tests historiques ont court-circuité certains use cases

**Constat** : plusieurs tests d'intégration créent directement les installations ou préparent des états backend avant de tester le reste du parcours.

**Impact** : un test peut prouver qu'une brique fonctionne après initialisation sans prouver que le vrai produit sait atteindre cet état depuis une installation vierge.

**Nouvelle règle** : les tests d'acceptance onboarding ne doivent pas appeler directement `record_installation()` / `record_detected()` pour simuler la découverte qui doit être produite par le runtime Gateway.

**Statut** : stratégie de test à remplacer par les use cases définis dans `UI_REDESIGN_PHASES.md`.

---

### P1-005 — États WebSocket trop bruyants / non dégradés proprement

`useGuildSocket.ts` reconnecte automatiquement avec backoff. Le comportement est correct comme primitive, mais l'échec réel actuel produit de nombreuses erreurs console et laisse l'UI en `reconnecting`.

**À déterminer** :

- le proxy WS local est-il correct ?
- l'autorisation STRUCTURE_READ est-elle correcte après bootstrap manuel ?
- l'abonnement Redis/pubsub est-il disponible ?
- l'UI doit-elle désactiver/reporter proprement les fonctions live quand le socket est indisponible ?

**Statut** : investigation Phase 1, correction au plus tard Phase 2/3.

## 4. Conformité initiale par domaine

| Domaine | État initial | Commentaire |
|---|---|---|
| OAuth | PARTIELLEMENT CONFORME | Flux réel fonctionne après correction d'hôte localhost/127.0.0.1 ; configuration locale à fiabiliser. |
| Découverte Guild | PRÉVUE DANS LE CODE MAIS CASSÉE/NON PROUVÉE EN LIVE | `GUILD_CREATE` doit créer `PENDING_SETUP`, mais le lancement testé n'a pas produit A/B. |
| Onboarding | NON CONFORME | Assistant §5.4 absent. |
| Structure | NON PROUVÉE / CASSÉE EN LIVE | Projection GUILD_CREATE existe mais la structure réelle n'est pas apparue dans le parcours testé. |
| Drag & Drop | PARTIEL | Sémantique codée, UX non conforme, pile `dnd-kit` absente, live non validé. |
| Menus contextuels | PARTIEL | ActionRegistry présent ; à revalider dans la nouvelle UI et en use case réel. |
| Rôles/permissions | À AUDITER | Routes présentes ; conformité simple/expert et mutations réelles à rejouer. |
| Plans/apply | À AUDITER | Backend avancé, expérience réelle à rejouer depuis l'UI. |
| Templates/library/clone | NON FONCTIONNEL EN BASELINE LOCALE | 503 observés sans clé artifact. |
| Traductions | À AUDITER | Route présente, use cases réels non encore rejoués. |
| Campagnes | À AUDITER | Route présente, use cases réels non encore rejoués. |
| Audit | CASSÉ EN LIVE | HTTP 500 observé. |
| Diagnostics | À AUDITER | Route présente ; utilité et exactitude à vérifier. |
| i18n | PARTIELLEMENT CONFORME | Catalogue présent, mais anomalie d'affichage/encodage observée et qualité visuelle à reprendre. |
| Layout / responsive | NON CONFORME | Chevauchements observés dans l'UI actuelle. |
| Lancement dev | NON CONFORME | Proxy et orchestration manuels nécessaires. |

## 5. Use cases de référence à ne plus contourner

### UC-001 — Première utilisation

```text
base vierge
-> démarrage normal
-> OAuth
-> liste des Guilds
-> Guild A/B détectées automatiquement
-> choisir Guild
-> onboarding
-> import structure
-> écran principal fonctionnel
```

### UC-002 — Administration structure

```text
ouvrir Guild A
-> structure réelle visible
-> sélectionner un salon
-> modifier une propriété
-> preview
-> confirmer
-> mutation Discord
-> vérification
-> reload
-> état identique
```

### UC-003 — Drag & Drop

```text
sélectionner salon
-> drag vers catégorie
-> indication visuelle destination
-> preview plan
-> confirmer
-> Discord modifié
-> audit visible
```

### UC-004 — Cross-Guild

```text
Guild A + Guild B accessibles
-> sélectionner une ressource A
-> drag/copie vers B
-> autorisations source/destination vérifiées
-> snapshot portable
-> preview destination
-> apply B
-> source A inchangée
```

### UC-005 — Permissions

```text
sélectionner rôle/membre
-> mode simple
-> comprendre accès
-> changer permission
-> preview
-> apply
-> vérifier permission Discord effective
```

### UC-006 — Portabilité

```text
sauvegarder dans bibliothèque
-> retrouver artifact
-> prévisualiser
-> importer/cloner
-> vérifier résultat
```

## 6. Prochaines investigations Phase 1

Ordre de travail :

1. reproduire la chaîne Gateway réelle et déterminer pourquoi `GUILD_CREATE` n'a pas créé/projeté A/B lors du lancement testé ;
2. reproduire et expliquer le HTTP 500 `/api/v1/guilds` ;
3. reproduire et expliquer le HTTP 500 `/audit` ;
4. valider la cause du WebSocket ;
5. inventorier chaque exigence UI/UX de `docs/00_reference` et la mapper à une phase ;
6. auditer chaque route frontend existante afin de décider : conserver logique / réécrire UI / corriger backend ;
7. terminer la matrice de conformité avant le démarrage de la Phase 2.

## 7. Politique de défauts

- **P0** : empêche le parcours principal ou rend une fonction critique inutilisable. Correction avant toute progression dépendante.
- **P1** : fonction importante incomplète, incorrecte ou trompeuse. Correction dans la phase qui la possède.
- **P2** : défaut de finition, ergonomie secondaire ou amélioration non bloquante.

Aucun P0/P1 découvert n'est volontairement laissé derrière en avançant les phases sans être affecté à une correction précise.
