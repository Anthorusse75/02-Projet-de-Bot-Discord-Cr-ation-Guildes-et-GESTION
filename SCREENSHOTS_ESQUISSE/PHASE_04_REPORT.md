# Phase 4 — Rapport de clôture

**Branche :** `ui/complete-redesign`  
**Statut :** ✅ TERMINÉE  
**Référence visuelle :** `SCREENSHOTS_ESQUISSE/Esquisse 1.png`

## 1. Objectif livré

La Phase 4 remplace les anciennes surfaces de lecture par un vrai poste de travail **Rôles & Permissions**. L'objectif est de permettre à un administrateur de raisonner avec des concepts humains (`voir`, `écrire`, `gérer`, `parler`, etc.) tout en conservant l'accès à la réalité Discord lorsque le mode expert est activé.

Aucune action d'édition ne contourne le pipeline de planification : l'UI prépare un Desired State Graph, crée un plan, le valide, puis bascule vers l'écran Plans. La confirmation, l'apply, la progression, les échecs partiels et la vérification post-apply restent la responsabilité explicite de la Phase 5.

## 2. Ce qui est livré

### Hiérarchie des rôles

- hiérarchie Discord réelle triée par position ;
- sélection et inspecteur d'un rôle ;
- affichage du Snowflake, de la position, de la fraîcheur et du bitfield réel ;
- affichage des permissions connues et des bits inconnus ;
- identification des rôles gérés par Discord/intégrations ;
- diagnostic de la capacité du bot à gérer la cible ;
- prise en compte de la hiérarchie Discord (`bot role > target role`) ;
- `@everyone` et rôles gérés non éditables depuis les actions incompatibles.

### Administration des rôles

Les opérations suivantes sont disponibles :

- création ;
- renommage ;
- suppression ;
- réordonnancement.

Chaque opération produit une **proposition**, puis un **plan validé**. Aucune mutation Discord directe n'est déclenchée depuis l'écran Rôles.

La création d'un rôle ne force volontairement aucune position artificielle : Discord choisit d'abord sa position initiale sûre, puis un réordonnancement peut être proposé séparément. Cela évite de demander une création au-dessus du rôle du bot, cas que Discord refuserait.

### Mode simple permissions

Le mode simple expose des intentions humaines :

- voir la ressource ;
- écrire / envoyer des messages ;
- gérer la ressource ;
- rejoindre un vocal ;
- parler en vocal ;
- diffuser en vocal.

Chaque intention possède trois états :

- Autoriser ;
- Hériter ;
- Refuser.

Ces intentions sont compilées par le moteur backend existant (`compile_simple_permissions`) vers de vrais bits Discord. Le frontend n'invente pas de bitmask local.

### Mode expert

Le mode expert expose :

- bitfields réels ;
- flags Discord reconnus ;
- bits inconnus conservés ;
- permissions effectives ;
- couverture et fraîcheur du read model ;
- trace détaillée de résolution ;
- sources rôle/overwrite utilisées par le moteur ;
- valeurs `allow` / `deny` et transitions avant/après.

### « Pourquoi cet accès ? » / View As

L'écran sait diagnostiquer :

- un rôle ;
- un membre ou bot ;
- un nouvel arrivant en mode diagnostic.

Le résultat vient du moteur de permissions backend. L'UI affiche la trace explicable et ne déduit pas une permission uniquement à partir d'une apparence visuelle.

### ADMINISTRATOR

Lorsqu'`ADMINISTRATOR` rend un overwrite inopérant, un avertissement explicite est affiché. L'UI ne laisse pas entendre qu'un deny de salon pourrait réellement restreindre ce sujet.

### Impact avant mutation

Avant de créer une proposition d'overwrite :

- les intentions humaines sont compilées ;
- l'allow/deny réel proposé est affiché ;
- les flags correspondants sont visibles ;
- le diagnostic courant est conservé ;
- pour un membre connu, le moteur de simulation calcule les permissions effectives avant/après et les bits ajoutés/retirés ;
- pour un rôle, l'UI n'invente pas un impact membre par membre non calculé : la vérification complète reste celle du plan/apply.

### Autorisation dashboard ≠ capacité Discord du bot

Deux couches distinctes sont conservées :

1. **délégation DID de l'utilisateur** (`permissions.write`, `roles.write`, `plans.create`) ;
2. **capacité réelle du bot Discord** (`MANAGE_ROLE`, `REORDER_ROLES`, `MANAGE_OVERWRITES`, etc.).

Une délégation dashboard n'est jamais présentée comme une restriction native Discord. Une action peut donc être refusée parce que l'utilisateur n'a pas la délégation DID nécessaire, ou parce que Discord interdit réellement l'opération au bot.

### Mutation impossible bloquée avant Discord

Les cas suivants sont bloqués avant création d'un plan applicable :

- délégation DID insuffisante ;
- permission bot manquante ;
- rôle géré ;
- rôle cible au-dessus/au même niveau que le rôle du bot ;
- capacité d'overwrite inconnue ou refusée.

Le refus affiche une raison utilisateur, pas uniquement un code backend.

## 3. Réconciliation live

Le routeur WebSocket frontend distingue désormais les événements de rôles des événements de structure. Les événements `role.*` ou les événements Gateway de type `GUILD_ROLE_*` invalident le read model `roles` afin que la hiérarchie se resynchronise sans rechargement complet.

Les gaps de séquence conservent le comportement de sécurité existant : invalidation globale du tenant concerné.

## 4. Localisation et design

Les nouvelles surfaces Phase 4 sont intégrées au design dark premium de la refonte et disposent des chaînes EN / FR / DE / ES pour les nouveaux parcours.

Les écrans utilisent les mêmes conventions visuelles que les Phases 2/3 : panneaux denses, hiérarchie lisible, inspecteur contextuel, appels à l'action explicites, états bloqués visibles et dialogues d'impact.

## 5. Exigences permissions couvertes

| Exigence | État Phase 4 | Preuve principale |
|---|---|---|
| REQ-PERM-001 | ✅ | bitfields transportés comme chaînes décimales, aucune conversion JS en entier flottant |
| REQ-PERM-002 | ✅ | moteur existant + warning visible ADMINISTRATOR |
| REQ-PERM-003 | ✅ | mode simple -> compilateur backend -> bits Discord réels |
| REQ-PERM-004 | ✅ | mode expert : flags, bitfields, trace et overwrites réels issus du moteur |
| REQ-PERM-005 | ✅ | View As rôle/membre/nouvel arrivant s'appuie sur le moteur backend |
| REQ-PERM-006 | ✅ | trace explicable « Pourquoi ? » |
| REQ-PERM-007 | ✅ | avertissement visible lorsque ADMINISTRATOR contourne les overwrites |
| REQ-PERM-008 | ✅ pour un membre connu ; plan/apply pour impact étendu | simulation avant/après via `/permissions/simulate` |
| REQ-PERM-009 | ✅ | délégation DID et capacité Discord du bot restent des décisions séparées |

## 6. Défauts Phase 1 traités

### P1-002 — Roles lecture seule

**Corrigé côté Phase 4 :** CRUD et reorder sont maintenant préparés depuis l'UI sous forme de plans validés, avec préflight de capacités.

La vérification de leur application réelle Discord appartient au pipeline de Phase 5 et à l'acceptance A/B de Phase 9 ; la Phase 4 ne contourne pas ce pipeline pour fabriquer une preuve artificielle.

### P1-003 — Permissions non administrables

**Corrigé côté Phase 4 :** mode simple humain, mode expert, View As, trace, compilation des intentions, simulation d'impact et proposition d'overwrite sont disponibles sans saisie de Snowflake pour le parcours rôle principal.

La saisie d'un Snowflake reste volontairement possible pour le diagnostic direct d'un membre/bot lorsque le read model utilisateur ne fournit pas encore de sélecteur complet de membres. Ce cas n'empêche pas le parcours rôle, qui est le parcours principal Phase 4.

## 7. Gate ciblé de sortie

Workflow : `.github/workflows/ui-phase4.yml`

Le gate couvre :

- TypeScript ;
- garde i18n des chaînes visibles ;
- routage live des événements de rôles ;
- scénarios navigateur ciblés Phase 4.

Scénarios de clôture :

1. création, renommage, réordonnancement et suppression de rôle compilés en plans validés, sans mutation directe ;
2. mode simple compilant des intentions humaines en overwrite Discord réel avant proposition ;
3. mode expert exposant la trace de résolution et l'avertissement ADMINISTRATOR ;
4. permission bot insuffisante bloquant la mutation avant création du plan.

Gate Phase 4 : **✅ VERT** sur le commit `7589d05f4a75cb31613077cf0333ec620e8d49a2`, run `34754635374`.

Les gates Phase 2 et Phase 3 ont également été rejoués sur ce même HEAD et restent verts, y compris le gate runtime Phase 2.

## 8. Frontière avec la Phase 5

La Phase 4 est terminée sur son périmètre : **définir, diagnostiquer, prévisualiser et préparer une modification de rôles/permissions de manière sûre**.

Elle ne duplique pas la Phase 5. Les éléments suivants restent volontairement au chantier suivant :

```text
plan validé
   ↓
confirmation normale / renforcée
   ↓
apply Discord
   ↓
progression
   ↓
verification post-apply
   ↓
audit lié à l'opération
```

La preuve de mutation Discord réelle A/B sera donc obtenue en Phase 5 à travers le même pipeline que celui utilisé en production, puis rejouée dans l'acceptance produit Phase 9.

## 9. Conclusion

La Phase 4 est fermée :

- les rôles sont administrables par propositions sûres ;
- le mode simple ne demande pas de connaître les bitfields Discord ;
- le mode expert montre la réalité Discord ;
- View As / Pourquoi expliquent les permissions effectives ;
- l'impact est visible avant proposition ;
- les restrictions DID et Discord restent distinguées ;
- les capacités insuffisantes bloquent avant mutation ;
- la réconciliation live des rôles est câblée ;
- le gate ciblé est vert ;
- aucune mutation Discord n'est exécutée silencieusement hors du pipeline Plans/Apply.

Le prochain chantier prévu est la **Phase 5 — Plans, preview, apply, progression et sécurité des mutations**. Aucune Phase 5 n'est démarrée par cette clôture.
