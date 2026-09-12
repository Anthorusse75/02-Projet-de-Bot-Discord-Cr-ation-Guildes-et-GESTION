# Phase 1 — Audit de conformité et baseline exécutable

Statut : **TERMINÉE**  
Branche : `ui/complete-redesign`  
Référence visuelle : `SCREENSHOTS_ESQUISSE/Esquisse 1.png`

## 1. Livrables Phase 1

La Phase 1 produit désormais quatre références de travail :

- `SCREENSHOTS_ESQUISSE/UI_REDESIGN_PHASES.md` — plan des 9 phases et politique de tests use-case ;
- `SCREENSHOTS_ESQUISSE/PHASE_01_REQUIREMENTS_MATRIX.md` — conformité `docs/00_reference` par famille d'exigences et phase propriétaire ;
- `SCREENSHOTS_ESQUISSE/PHASE_01_ROUTE_USECASE_MAP.md` — audit de chaque route/écran existant ;
- `SCREENSHOTS_ESQUISSE/PHASE_01_DEFECT_REGISTER.md` — P0/P1/P2, cause ou investigation, phase et preuve de fermeture.

Les documents normatifs restent exclusivement :

- `docs/00_reference/01_SPECIFICATIONS_FONCTIONNELLES_DISCORD_INFRA_DESIGNER.md`
- `docs/00_reference/02_ARCHITECTURE_TECHNIQUE_DISCORD_INFRA_DESIGNER.md`

`docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md` reste une trace historique utile, mais **un statut historique VERIFIED n'est plus une preuve produit suffisante**.

---

## 2. Conclusion générale

Le constat Phase 1 n'est pas « le projet ne contient rien ». Au contraire : le backend et certains écrans contiennent beaucoup de logique utile.

Le vrai problème est le suivant :

```text
moteurs/backend importants
        +
interfaces frontend fonctionnelles par morceaux
        +
beaucoup de tests techniques
        ≠
produit réellement utilisable de bout en bout
```

Les défauts observés dans le navigateur prouvent qu'un parcours réel n'a pas été suffisamment utilisé comme gate d'acceptance.

La stratégie retenue est donc :

1. conserver les moteurs/backend qui passent la requalification ;
2. réparer d'abord le chemin d'exécution réel ;
3. reconstruire complètement l'expérience visuelle selon `Esquisse 1.png` ;
4. tester les **use cases**, pas le nombre de tests ;
5. utiliser A/B comme preuve réelle pour les parcours Discord critiques.

---

## 3. Baseline frontend auditée

Routes actuelles :

```text
/login
/guilds
/guild/:guildId/structure
/guild/:guildId/roles
/guild/:guildId/permissions
/guild/:guildId/plans
/guild/:guildId/diagnostics
/guild/:guildId/audit
/guild/:guildId/templates
/guild/:guildId/library
/guild/:guildId/clone
/guild/:guildId/translations
/guild/:guildId/campaigns
```

Aucune route n'est déclarée « finie » sur sa seule existence.

### Logique substantielle à préserver derrière une nouvelle UI

- Plans / progression ;
- ActionRegistry ;
- Pointer gesture / right-drag ;
- une partie de Structure ;
- TranslationWorkspace ;
- CampaignCenter ;
- backend cache, planning, portability, permissions, translations/campaigns.

### Écrans trop partiels pour être conservés comme produit final

- GuildSelect / onboarding ;
- Roles ;
- Permissions ;
- Diagnostics ;
- Audit ;
- Templates ;
- Library ;
- Clone ;
- shell général.

---

## 4. Défauts bloquants confirmés

### P0-001 — Découverte automatique A/B non fiable

Le code possède bien le chemin :

```text
Discord READY
 -> GUILD_CREATE
 -> normalize_gateway_dispatch
 -> RuntimeRepository.ingest_gateway_event
 -> guild_installations = PENDING_SETUP
 -> projection channels / threads / roles
```

Il est donc incorrect de dire que `did.bot` « ne sait pas enregistrer une installation ».

En revanche, **ce chemin n'a pas produit A/B dans l'essai réel**. Le contournement manuel a été nécessaire.

Deux défauts de diagnostic ont aussi été identifiés statiquement :

- `run_process("bot")` ne fail-fast pas si `DISCORD_BOT_TOKEN` est absent ; il peut démarrer sans client Gateway ;
- un `GatewayContractError` est compté comme rejet mais n'est pas journalisé avec une cause exploitable.

Ces points ne prouvent pas à eux seuls la cause de l'essai A/B, mais expliquent pourquoi le démarrage est difficile à diagnostiquer.

**Phase propriétaire : 2.**

### P0-002 — Onboarding §5.4 absent

L'API `/api/v1/guilds/{guild_id}/bootstrap` existe, mais le frontend ne fournit pas l'assistant imposé par la référence : bot présent, identité, owner/admin, permissions bot, import structure, audit initial, limites, configuration dashboard, activation.

**Phase propriétaire : 2.**

### P0-003 — Structure réelle vide

`_project_guild_create()` sait projeter les ressources, mais l'écran testé a affiché aucune catégorie/salon après le workaround d'installation.

La baseline doit donc prouver :

```text
GUILD_CREATE reçu
-> installation créée
-> cache structure alimenté
-> /structure retourne les données
-> explorer les affiche
```

**Phase propriétaire : 2 puis 3.**

### P0-004 — `/api/v1/guilds` HTTP 500

Le code statique ne permet pas d'attribuer honnêtement ce 500 à une cause unique. Le chemin combine OAuth discovery, authorization et repository installation.

**Investigation explicitement obligatoire Phase 2** : reproduction base propre avec correlation id + traceback, puis mapping de toute erreur attendue en Problem Details localisé.

### P0-005 — `/audit` HTTP 500

L'endpoint et le repository existent. `AuthorizationDenied` est déjà pris en charge globalement ; le 500 observé vient donc d'un autre défaut runtime qui doit être capturé lors du scénario réel.

**Phase propriétaire : 2 pour stabilité, 8 pour l'expérience Audit.**

### P0-006 — WebSocket en échec/reconnexion

Le backend :

- ferme 4401 si session absente ;
- ferme 4403 si `STRUCTURE_READ` est refusé ;
- accepte ensuite et dépend du pubsub tenant.

Le frontend, lui, ne traite pas le close code : il repasse en `reconnecting` et recommence avec backoff, ce qui produit le bruit vu dans la console.

Le proxy WebSocket officiel manque aussi dans Vite.

**Phase propriétaire : 2.**

### P0-007 — Lancement local officiel incohérent

Le README demande API sur 8000 puis `npm run dev`, mais `vite.config.ts` ne proxy pas `/api`, `/auth`, `/ws`. Le frontend appelle pourtant ces chemins relativement et l'OAuth dépend d'une origine exacte.

Le `vite.local.config.ts` créé manuellement pendant le diagnostic ne peut pas être la solution produit.

**Phase propriétaire : 2.**

---

## 5. Écarts UI fonctionnels importants

### Rôles

`RolesScreen` est une liste en lecture seule. Il n'administre pas réellement les rôles.

**Phase 4.**

### Permissions

`PermissionsScreen` fournit View As/Explain mais exige des IDs Discord bruts et ne propose pas le vrai workflow de mutation simple/expert demandé.

**Phase 4.**

### Plans

Le pipeline est significatif et doit être conservé, mais le diff avant/après, l'impact et les dépendances ne sont pas assez compréhensibles.

**Phase 5.**

### Templates / Bibliothèque / Clone

Les écrans existent mais ne forment pas un parcours utilisateur complet. Le clone demande un ID source brut. Templates/Bibliothèque ont renvoyé 503 lorsque portability n'était pas configurée.

**Phase 6.**

### Traductions

Le substrat est riche et mérite d'être conservé : groupes, variantes, langues, providers, routes, drift, create/link/clone/preview et gestes contextuels.

La présentation et les parcours live doivent être requalifiés.

**Phase 7.**

### Campagnes

Le substrat est également riche : création/édition, targets multi-Guild, scheduling, simulation, variantes, deliveries/interventions.

L'écran actuel est trop dense et doit être reconstruit sans supprimer ces use cases.

**Phase 7.**

### Diagnostics

L'écran ne montre que couverture/fraîcheur alors que le backend possède davantage d'information capability/remediation.

**Phases 2 et 8.**

### Audit

Vue actuelle minimale + endpoint cassé dans le parcours réel.

**Phases 2 et 8.**

---

## 6. Correction importante sur Drag & Drop

La première version de cet audit avait classé le `PointerGestureManager` maison comme non conforme parce que `dnd-kit` n'est pas installé.

Cette conclusion était trop simpliste.

L'architecture de référence §22 demande explicitement :

- Pointer Events comme source de vérité ;
- un `PointerGestureManager` ;
- distinction clic droit / Right Drag par seuil ;
- possibilité d'utiliser `dnd-kit` pour collision/overlay/tri avec un custom sensor/gesture layer.

Donc :

- le `PointerGestureManager` actuel est **aligné avec l'architecture** ;
- `dnd-kit` reste absent et pourra être ajouté pour améliorer overlay, tri, collision et accessibilité clavier ;
- le défaut réel est surtout la qualité visuelle, la richesse des drop targets et l'absence de preuve live du use case complet.

**Phase propriétaire : 3.**

---

## 7. Conformités code intéressantes identifiées

Ces éléments ne sont pas « validés produit », mais ils méritent d'être préservés :

- `GlobalContextMenuBoundary` désactive bien le menu contextuel natif globalement ;
- `ActionRegistry` utilise des `labelKey`/`descriptionKey`/`tooltipKey` et filtre selon type/capabilities ;
- left/right drag ont un seuil explicite ;
- les actions structure produisent une preview/intention avant mutation ;
- cross-Guild copy/clone possède des contrôles source/destination dans l'ActionRegistry ;
- Plans possède progression et confirmations ;
- i18n runtime/catalog existe ;
- cache structure, obfuscation et `includeHiddenDeleted` existent ;
- TranslationWorkspace et CampaignCenter possèdent un périmètre fonctionnel conséquent.

Le principe est **ne pas jeter la logique correcte uniquement parce que l'ancienne UI est mauvaise**.

---

## 8. Défauts visuels / i18n exacts

L'anomalie vue à l'écran n'est pas un mystérieux encodage : le catalogue FR contient littéralement :

```text
Àucun serveur Discord admissible trouvé.
```

C'est une faute source à corriger.

Les chevauchements/alignements observés sont enregistrés comme défauts du design/layout actuel. Le shell est remplacé au lieu d'être rafistolé.

---

## 9. Politique de tests décidée

On ne repart pas sur « 1000 tests à chaque modification ».

Pour chaque fonctionnalité UI :

```text
Use case utilisateur
 -> navigateur
 -> backend réel
 -> Discord réel si mutation
 -> résultat vérifié
 -> reload
 -> E2E ciblé
```

Les tests backend exhaustifs restent là où ils ont de la valeur : permissions critiques, isolation tenant, sécurité, plan engine. Ils ne sont pas relancés pour chaque changement de couleur, spacing ou icône.

Les Guilds sandbox A/B deviennent la preuve centrale des parcours Discord réels.

---

## 10. Gate de sortie Phase 1

| Critère | Résultat |
|---|---|
| Sources `docs/00_reference` identifiées comme autorité | ✅ |
| Exigences à impact UI/use case mappées à une phase | ✅ `PHASE_01_REQUIREMENTS_MATRIX.md` |
| Routes frontend auditées | ✅ `PHASE_01_ROUTE_USECASE_MAP.md` |
| P0/P1/P2 recensés | ✅ `PHASE_01_DEFECT_REGISTER.md` |
| Chaque P0/P1 a une cause ou une investigation précise | ✅ |
| Use cases critiques définis | ✅ |
| Tests historiques cessent d'être preuve suffisante | ✅ |
| Direction visuelle figée | ✅ `Esquisse 1.png` |
| Corrections runtime implémentées | ❌ **hors Phase 1, début Phase 2** |

# Décision

**PHASE 1 TERMINÉE.**

La Phase 2 peut démarrer immédiatement, avec cet ordre :

```text
1. lancement local propre
2. instrumentation/fail-fast du bot
3. découverte A/B depuis base vierge
4. structure initiale réelle
5. onboarding §5.4
6. correction 500 /guilds et /audit
7. WebSocket stable et explicable
8. portability/config prerequisites
9. design system + shell + accueil conformes à Esquisse 1
```

Aucun P0/P1 n'est oublié : chacun possède une phase propriétaire et une preuve de fermeture attendue.
