# Phase 4 — Rapport initial et réouverture post-audit

**Branche :** `ui/complete-redesign`  
**Statut actuel :** 🚧 **RÉOUVERTE — matrice/bulk livrés, politiques avancées encore ouvertes**

**Référence visuelle :** `SCREENSHOTS_ESQUISSE/Esquisse 1.png`  
**Plan maître :** `SCREENSHOTS_ESQUISSE/UI_REDESIGN_PHASES.md`

## 1. Historique

La première implémentation de la Phase 4 a livré un vrai poste de travail **Rôles & Permissions** : hiérarchie, CRUD de rôles, mode simple, mode expert, permissions effectives, `View As`, explication des décisions, simulation d'impact et préparation de plans.

Le gate automatisé initial était vert sur le commit `7589d05f4a75cb31613077cf0333ec620e8d49a2`, run `34754635374`.

Cette clôture initiale reste une preuve valable du **socle livré**, mais elle n'est plus une clôture de la Phase 4 complète. Les clarifications produit sur les politiques d'accès puis l'audit étendu des 389 exigences ont montré que plusieurs fonctions nécessaires à l'expérience finale n'existent pas encore, principalement le **Policy Engine générique** et le **socle Wizard**.

## 2. Socle déjà livré et conservé

### Hiérarchie et administration des rôles

- hiérarchie Discord réelle triée par position ;
- création, renommage, suppression et réordonnancement ;
- gestion des rôles gérés et de `@everyone` ;
- diagnostic de hiérarchie bot/cible ;
- toutes les modifications passent par des propositions/plans, jamais par une mutation Discord directe depuis l'écran.

### Permissions simples et expertes

Le mode simple expose des intentions humaines (`voir`, `écrire`, `gérer`, `rejoindre`, `parler`, etc.) compilées par le moteur backend vers de vrais bits Discord.

Le mode expert expose :

- bitfields et flags réels ;
- bits inconnus conservés ;
- permissions effectives ;
- couverture/fraîcheur du read model ;
- trace détaillée de résolution ;
- overwrites et transitions avant/après.

### `View As` / « Pourquoi cet accès ? »

Le diagnostic peut cibler un rôle, un membre/bot ou un nouvel arrivant. Le résultat provient du moteur de permissions backend et non d'une approximation frontend.

### Simulation et impact

Avant proposition d'overwrite, l'UI peut afficher l'allow/deny compilé et, pour un membre connu, simuler les permissions effectives avant/après.

### Séparation DID / Discord

L'autorisation dashboard de l'utilisateur et la capacité réelle du bot Discord restent deux décisions distinctes.

## 3. Pourquoi la Phase 4 est rouverte

Deux constats imposent la réouverture :

1. un état réel `Capacité du bot inconnue` a été observé avec des actions désactivées sans cause/remédiation suffisamment précise ;
2. l'audit étendu conclut que le moteur de permissions historique est solide, mais qu'un **Policy Engine générique**, les politiques natives/personnalisées et les Wizards associés ne sont pas encore implémentés comme produit complet.

La Phase 4 doit donc être terminée sur son intention réelle : **administrer les accès en langage humain, avec conflits, héritage, explication et préparation sûre d'un plan**.

## 4. Travail restant dans la Phase 4 — sans créer de nouvelles phases

Tout le travail ci-dessous appartient à la **Phase 4 existante** :

- diagnostiquer/corriger les causes persistantes de `UNKNOWN` ;
- modèle Policy générique tenant-scopé ;
- scopes et compatibilité par type de ressource ;
- lifecycle/versionnement ;
- stockage, RLS et RBAC ;
- resolver déterministe : priorité, héritage, exception locale, conflits ;
- verrouillage et comportement face au drift ;
- politiques natives DID ;
- politiques personnalisées : créer, renommer, dupliquer, modifier, supprimer avec stratégie explicite ;
- whitelist/blacklist de visibilité et d'écriture ;
- zones/audiences, vocal, threads/réactions/mentions, bots et accès temporaires selon les exigences produit ;
- détection de conflits multi-rôles jusqu'au membre concerné ;
- explication de la source réelle du conflit ;
- remédiations prévisualisées avant plan ;
- matrice d'accès / opérations massives prévues ;
- socle Wizard réutilisable ;
- gestion du rôle manquant avec `+ Créer un rôle` dans le parcours ;
- détails Discord maintenus dans le niveau expert/contextuel ;
- aucun chemin de mutation parallèle au Plan Engine.

## 5. Use cases de sortie désormais obligatoires

La Phase 4 ne pourra être refermée que lorsque les parcours suivants fonctionneront réellement :

1. modifier une permission en mode simple et inspecter le résultat Discord calculé ;
2. passer en mode expert et comprendre la résolution ;
3. `CAN / CANNOT / UNKNOWN` affiche une cause utile et, lorsqu'elle existe, une remédiation ;
4. préparer une policy whitelist ;
5. préparer une policy blacklist qui détecte un membre en conflit à cause d'un autre rôle ;
6. afficher la source exacte du conflit et prévisualiser une résolution ;
7. policy de catégorie héritée -> exception locale clairement visible ;
8. policy verrouillée -> drift externe détecté avec stratégie explicite de remise en conformité/intervention ;
9. rôle requis absent -> le Wizard permet de proposer sa création sans quitter le parcours ;
10. sortie du parcours = intention validée + plan prêt, jamais mutation Discord directe.

## 6. Exigences permissions historiques déjà couvertes

| Exigence | État du socle | Preuve principale |
|---|---|---|
| REQ-PERM-001 | ✅ | bitfields sans perte de précision |
| REQ-PERM-002 | ✅ | ADMINISTRATOR correctement pris en compte |
| REQ-PERM-003 | ✅ | mode simple -> compilateur backend |
| REQ-PERM-004 | ✅ | mode expert expose la réalité Discord |
| REQ-PERM-005 | ✅ | View As rôle/membre/nouvel arrivant |
| REQ-PERM-006 | ✅ | trace explicable |
| REQ-PERM-007 | ✅ | état incomplet/unknown traité fail-closed |
| REQ-PERM-008 | ✅ | explication visible |
| REQ-PERM-009 | ✅ | View As complet |

Les nouvelles familles `REQ-POL-*`, `REQ-WIZ-*` et `REQ-PERMX-010` constituent l'essentiel de la complétion restante de cette Phase 4.

## 7. Stratégie de tests Phase 4

La Phase 4 ne doit pas devenir une campagne de tests permanente.

### Obligatoire

- tests unitaires **ciblés** du resolver Policy : priorité, héritage, conflits, lifecycle ;
- intégration **ciblée** pour RLS/RBAC/persistance des policies ;
- test du pipeline Policy -> preview/preflight -> plan ;
- E2E ciblé sur quelques parcours critiques : whitelist, blacklist avec conflit, Wizard avec rôle absent ;
- checkpoint de fin de phase sur le socle permissions/policies affecté.

### Inutile et donc à éviter

- relancer tout le backend pour une retouche CSS ou un wording ;
- dupliquer le même parcours dans cinq couches de tests ;
- rejouer Discord A/B après chaque changement local ;
- écrire des tests uniquement pour augmenter un compteur.

La preuve Discord réelle de l'apply reste attachée à la Phase 5 puis à l'acceptance finale Phase 9.

## 8. Frontière avec la Phase 5

La Phase 4 couvre :

```text
intention humaine
   ↓
policy / permission
   ↓
diagnostic / conflit / remédiation
   ↓
preview / impact
   ↓
plan prêt et validable
```

La Phase 5 couvre ensuite :

```text
confirmation
   ↓
apply Discord
   ↓
progression persistante
   ↓
retry / intervention / UNKNOWN_OUTCOME
   ↓
verification post-apply
   ↓
audit de l'opération
```

La Phase 4 n'implémente donc pas un second moteur d'apply.

## 9. Statut actuel

Le **socle Rôles & Permissions initial est livré et reste valide**. La Phase 4 elle-même reste **ouverte** jusqu'à complétion du Policy Engine générique, du Wizard de base, des conflits/héritages/remédiations et des use cases ci-dessus.

Une fois cette complétion faite et le checkpoint ciblé vert, on passera à la **Phase 5 existante**. Aucune nouvelle phase UI n'est créée.

## 10. Lot backend « fondations Policy » — 2026-09-14

Le socle générique backend est désormais présent :

- agrégat `Policy` tenant-scopé, UUID stable, type/contrat versionné, cible,
  conditions, effets et métadonnées humaines ;
- registre fermé `ACCESS_CONTROL` v1, revalidation avant activation et refus de
  tout champ/opérateur/code arbitraire ;
- lifecycle strict `DRAFT → ACTIVE → DISABLED → RETIRED` ;
- tables `policies` et `policy_versions`, RLS activée/forcée, historique
  append-only et audit atomique ;
- idempotence create/activate/disable, CAS sur révision/état et validation des
  cibles/rôles contre le cache du tenant ;
- API CRUD/lifecycle minimale protégée par cinq capabilities Policies ;
- ADR `POLICY_ENGINE_RULE_VALIDATION_ADR.md` : Pydantic fermé retenu pour la
  validation ; aucun DSL ou moteur d'expressions ajouté prématurément.

Preuves ciblées : 16 tests unitaires et 6 tests PostgreSQL réels passent ; le
round-trip Alembic `0036 → 0035 → 0036` passe. Aucun test Playwright, apply
Discord ou suite backend complète n'a été exécuté, conformément au périmètre.

Cette livraison ne referme pas la Phase 4. Elle ne contient ni resolver,
priorité/héritage/conflits, preview/impact, préflight/Plan, UI/Wizard, ni
enforcement Discord. Les helpers `message_content_policy.py` et
`translation_policy.py` restent spécialisés et séparés du moteur générique.

## 11. Correctif ciblé « capacité bot UNKNOWN » — 2026-09-14

Le chemin du défaut a été isolé dans les deux couches qui perdaient
l'information utile :

- `dashboard_capabilities()` arrêtait tout calcul si l'utilisateur n'avait pas
  `bots.audit` et fabriquait un `UNKNOWN` avec
  `capability.user.bot_audit_required`, avant même la lecture de l'identité et
  du snapshot du bot ;
- l'écran Rôles appliquait `?? 'UNKNOWN'` aussi bien pendant le chargement
  qu'après une erreur HTTP, puis remplaçait presque toutes les causes
  structurées par un texte générique.

La dépendance `bots.audit` a été retirée uniquement de la projection minimale
de capacité opérationnelle du bot DID installé. Cette projection reste
autorisée par `tenant.read`, tenant-scopée, cache-first, sans appel REST Discord
et sans valeur d'autorité pour une mutation : chaque commande conserve son
RBAC et son préflight. Les véritables surfaces d'audit global
`/{guild_id}/bots/audit` et d'access-map d'un bot arbitraire restent protégées
par `bots.audit` et marquées sensibles.

Le résultat reste fail-closed : une identité bot absente, des rôles bot
incomplets, un snapshot incomplet ou non actuel produisent toujours
`UNKNOWN`. L'API renvoie désormais une remédiation structurée pour actualiser
les données. Une permission `MANAGE_ROLES` absente, une installation inactive,
un rôle géré ou une hiérarchie trop basse produisent `CANNOT`; les deux cas
actionnables proposent respectivement d'accorder `MANAGE_ROLES` ou de placer le
rôle du bot au-dessus du rôle cible. Ces règles correspondent aux exigences
Discord officielles de gestion des rôles et de hiérarchie :
<https://docs.discord.com/developers/resources/guild#modify-guild-role> et
<https://docs.discord.com/developers/platform/server-and-channel-management>.

L'UI distingue maintenant cinq états de transport/produit : `LOADING`,
`ERROR`, `CAN`, `CANNOT` et `UNKNOWN`. Les causes et remédiations backend sont
présentées via un helper réutilisable, avec textes EN/FR/DE/ES. Une erreur HTTP
est explicitement affichée comme erreur de requête avec bouton de retry et
n'est plus assimilée à un `UNKNOWN` Discord.

Preuves ciblées : 3 tests du checker de capacités, 2 tests de la projection API
(dont `roles.write` + `plans.create` sans `bots.audit`) et 6 tests montés de
l'écran Rôles passent. Le typecheck, ESLint ciblé, Ruff ciblé et le contrôle
i18n passent également. Aucun Playwright, Discord live A/B ni suite backend
complète n'a été exécuté pour ce correctif localisé. Le statut global de la
Phase 4 et les statuts Policy Foundation ne changent pas.

## 12. Lot backend « resolver Policy générique » — 2026-09-14

Le resolver `ACCESS_CONTROL` v1 est livré comme service de domaine pur, appelé
par `PolicyService.resolve_access()` à partir du read model cache-first. La route
de lecture `POST /api/v1/guilds/{guild_id}/policy-resolution`, protégée par
`policies.read`, expose exactement le même résultat ; aucune logique de
résolution n'est dupliquée dans l'API ou le frontend.

La règle normative est :

```text
priorité explicite décroissante
  puis, à priorité égale, spécificité dans une hiérarchie déclarée
  puis conflit BLOCKED si les effets maximaux restent incompatibles
```

La hiérarchie ressource est `GUILD → LOGICAL_GROUP → CATEGORY → CHANNEL`. La
hiérarchie sujet est `GUILD → ROLE → MEMBER/BOT`. Un scope ressource et un scope
sujet sont incomparables à priorité égale : l'UUID stable ordonne uniquement
l'explication, jamais la décision. Une règle héritée reste visible avec son
scope source, sa révision et sa contribution ; une exception locale ne supprime
donc pas l'historique hérité.

Le résultat structuré contient décision `CAN/CANNOT/BLOCKED/UNKNOWN`, cible,
fraîcheur, coverage, Policies applicables, conditions `TRUE/FALSE/UNKNOWN`,
contributions, scopes sources, trace de priorité, conflits et diagnostics. Un
conflit départagé par priorité ou spécificité indique la règle gagnante. Une
opposition de rang égal/incomparable devient `BLOCKED`. Une cible supprimée ou
inaccessible devient également `BLOCKED`; une cible stale/unknown ou une
condition critique dépendant de rôles incomplets devient `UNKNOWN`, avec une
recommandation de refresh/reconcile déjà supportée par le système.

La priorité est désormais un champ durable borné de la Policy, inclus dans les
snapshots de version via la migration `0037_ui_phase4`. Les conditions `ANY` et
`ALL` évaluent l'ensemble complet des rôles Discord du membre. Le moteur de
permissions Discord natif, le Plan Engine, les Visibility Scopes et les helpers
message/traduction restent canoniques dans leurs responsabilités respectives et
n'ont pas été dupliqués.

Preuves ciblées : 43 tests unitaires Policy passent, dont permutation de l'ordre
d'entrée, priorité/spécificité, héritage complet, exception locale, composition,
matrice de conflits, `ANY`/`ALL`, drift et fail-closed. Les 7 tests PostgreSQL
passent, dont persistance/versionnement de la priorité et isolation A/B. Le
round-trip Alembic `0037 → 0036 → 0037`, Ruff ciblé et mypy (167 modules) passent.
Aucun Playwright, Discord live A/B, APPLY ni suite backend complète n'a été
exécuté, car aucun de ces chemins n'est modifié par ce lot.

Ce lot ferme le resolver générique, pas la Phase 4 : preview/impact,
préflight/Plan, enforcement des mutations, UI Policies et Wizards restent dans
les lots suivants de la même Phase 4.

## 13. Lot backend « Policy vers Plan canonique » — 2026-09-15

Une Policy `DRAFT` peut désormais être simulée sans persistance ni mutation.
La preview construit les contextes depuis le read model cache-first, appelle
exactement `PolicyResolver` pour l'état courant puis pour la proposition, et
retourne décisions avant/après, contributions gagnées/perdues, conflits,
diagnostics, fraîcheur et couverture. L'impact expose des compteurs de
ressources, rôles, membres, gains, pertes et cibles impossibles avec une
précision explicite `EXACT`, `BOUNDED` ou `INCOMPLETE`.

La compilation traduit uniquement les décisions Discord matérialisables vers
les nœuds `OVERWRITE` du Desired State Graph existant, puis délègue au
`PlanningService`, au compilateur, au moteur de risque et au preflight
canoniques. Aucun resolver, preview de mutation ou moteur de Plan parallèle
n'est introduit. Les routes minimales sont :

- `POST /api/v1/guilds/{guild_id}/policies/{policy_id}/preview` ;
- `POST /api/v1/guilds/{guild_id}/policies/{policy_id}/plan`.

Le Plan persiste une provenance immuable typée `POLICY` : `policy_id`, révision,
scope, contextes/fingerprint de preview, versions sources et `correlation_id`.
Les opérations existantes référencent ce Plan ; la chaîne
`Operation → Plan → Policy/version` est donc requêtable sans dupliquer les
opérations. Cette provenance participe au hash et à la comparaison
d'idempotence du Plan.

Le point d'enforcement se situe dans `PlanningService.recheck()`. Le preflight
canonique y fusionne la décision de capacité Discord avec la réévaluation de la
Policy par le même resolver. `BLOCKED`, `UNKNOWN`, une définition révisée ou une
preview non exacte refusent le Plan. Le worker réexécute ce contrôle après le
fencing `APPLYING` et avant toute opération ; il exige en plus que la Policy soit
`ACTIVE`. L'activation elle-même exige un Plan Policy tenant-local déjà
`VALIDATED` (ou plus avancé) et la capability sensible existante. La réponse
distingue explicitement `Policy ACTIVE` du Plan réellement `SUCCEEDED`, seul
état déclaré appliqué et vérifié.

Évolution prouvée : `REQ-POL-021`, `022`, `023`, `026`, `028`, `044`, `045` et
`046` passent d'**ABSENT** à **CONFORME**. `REQ-POL-050` reste **PARTIEL** : les
capabilities et l'isolation PostgreSQL A/B sont testées, mais pas une réponse
HTTP 403 complète. `REQ-POL-051` passe d'**ABSENT** à **PARTIEL** : la chaîne
persistance → preview → preflight → Plan → activation/provenance et les retries
sont couverts, pas encore la chaîne CI complète jusqu'à audit/désactivation.

Preuves ciblées : 117 tests unitaires du resolver, de la Policy, du Plan, des
contrats API et du runtime passent ; 8 tests PostgreSQL Policy passent. Ruff ciblé et mypy sur
les sept modules source concernés passent. Le round-trip Alembic
`0038 → 0037 → 0038` passe et la base termine sur `0038_ui_phase4 (head)`.
Aucun Playwright, Discord live A/B, APPLY Discord réel ni suite backend complète
n'a été exécuté. La Phase 4 reste ouverte pour l'UI Policies et les Wizards.

## 14. Lot UI « Politiques d'accès » — 2026-09-15

La navigation contient désormais une vraie entrée localisée vers un espace
Policies en dark navy et à divulgation progressive. L'architecture conserve un
catalogue DID versionné côté application et ne crée en base que les Policies
personnalisées `ACCESS_CONTROL v1` tenant-scopées.

Les sept natives disponibles sont :

1. Visible uniquement par…
2. Visible par tous sauf…
3. Seuls … peuvent écrire
4. Tout le monde peut écrire sauf…
5. Lecture ouverte, publication limitée à…
6. Espace privé — visible uniquement par…
7. Staff uniquement

Le contrat fermé accepte une audience de rôles `INCLUDE/EXCLUDE` par effet.
Cette extension additive est évaluée par l'unique `PolicyResolver`; elle permet
notamment de laisser `VIEW` ouvert tout en limitant `WRITE`, sans logique de
permission parallèle dans React.

Les Policies personnalisées peuvent être créées depuis une native, renommées
et modifiées tant qu'elles sont `DRAFT`, dupliquées depuis une native ou une
personnalisée, et recréées depuis une révision connue sous forme d'un nouveau
brouillon. La suppression n'est volontairement pas exposée : le backend ne
porte pas encore le contrat de dépendances nécessaire pour proposer sans risque
« détacher / remplacer / annuler ».

Le mode simple montre cible, audiences multi-rôles et intentions humaines
Voir/Écrire/Rejoindre. Le mode expert expose sans autre calcul l'ID, la
révision, la priorité, le scope, les conditions, effets et résolutions. La
preview backend affiche avant/après, gains, pertes, membres, rôles, ressources,
conflits et précision `EXACT/BOUNDED/INCOMPLETE`. Les remédiations de conflit
n'appliquent rien et ne retirent aucun rôle automatiquement.

« Pourquoi ce résultat ? » appelle la route Explain existante. « Préparer le
plan » appelle l'endpoint Policy→Plan canonique puis redirige vers Plans. Aucun
Apply n'est ajouté dans ce lot.

Exigences : `REQ-POL-006`, `025`, `032`, `041` et `042` passent respectivement
de **PARTIEL/ABSENT** à **CONFORME**. `REQ-POL-043` reste **ABSENT** pour le lot
Wizard. Les autres statuts ne sont pas relevés sans preuve supplémentaire.

Tests exécutés : 57 tests backend Policy, 5 tests unitaires catalogue/UI, trois
Playwright ciblés dont axe sur `#main`, typecheck, lint, i18n EN/FR/DE/ES,
Ruff/format et OpenAPI. Tests non exécutés : campagne globale, PostgreSQL/RLS,
Discord live A/B et tout APPLY. Aucun fichier de migration n'est ajouté.

## 15. Lot frontend « Socle Wizard générique + assistant Configurer l'accès à un espace » — 2026-09-15

Ce lot est **frontend seul** : le backend (Policy, resolver, Plan/DSG,
capabilities) était déjà suffisant pour porter un vrai assistant de bout en
bout et n'a pas été modifié.

### Entrée dédiée et catalogue

Une entrée localisée **Assistants** apparaît dans la navigation principale,
distincte de Politiques d'accès, Plans et Templates (`/guild/:id/wizards`).
L'écran catalogue liste, pour chaque assistant, objectif, portée, ce qu'il
peut proposer, prérequis et complexité approximative. Le catalogue contient
volontairement deux entrées seulement : **Configurer l'accès à un espace**
(disponible, démarre le Wizard) et **Construire un gabarit** (marqué non
disponible avec sa raison — prévu pour la Phase 6 Templates). Aucune entrée
n'est un faux catalogue : ce qui n'est pas construit est explicitement dit
indisponible.

### Socle Wizard réutilisable

Trois primitives génériques, indépendantes de tout domaine métier, vivent
dans `frontend/src/features/wizards/core/` :

- `reducer.ts` : reducer pur `createWizardReducer(steps, initialAnswers)` —
  navigation `NEXT/BACK/GOTO/RESET`, `furthestIndex` (steps déjà atteints),
  et invalidation explicite (`UPDATE` avec `resetKeys`) qui réinitialise les
  réponses dépendantes et ramène `furthestIndex` à l'étape courante ;
- `useWizard.ts` : hook React (`useReducer`) exposant l'état et les actions ;
- `WizardShell.tsx` : présentation générique (barre de progression cliquable
  uniquement sur les étapes atteintes, titre d'étape focus au changement,
  boutons Précédent/Suivant/Quitter) ;
- `RoleMultiSelect.tsx` : sélecteur de rôles multi-sélection réutilisable
  (rôles gérés visibles mais désactivés avec explication, jamais masqués ;
  bloc « rôle suggéré » ; « + Créer un rôle » ouvrant une proposition locale).

Le socle ne contient aucun appel réseau et aucune logique de résolution : les
étapes concrètes (dans `features/wizards/accessSpace/`) sont seules
responsables des appels Policy/Plan existants. Il est explicitement conçu
pour être réutilisé tel quel par un futur Wizard Templates (Phase 6) ou
Traduction/Campagnes (Phase 7).

### Assistant « Configurer l'accès à un espace »

Sept étapes guidées, retour arrière libre : Cible → Intention → Rôles →
Conflits → Ajuster → Preview/Impact → Plan.

- **Cible/Intention** réutilisent exactement le catalogue de politiques
  natives et le calcul de compatibilité déjà utilisés par l'espace Policies
  (`features/policies/catalog.ts`, `targets.ts` désormais extrait et partagé
  par les deux écrans).
- **Rôles** propose tous les rôles existants du read model tenant courant
  (aucune recréation aveugle) via `RoleMultiSelect`. Si aucun rôle n'est
  encore sélectionné, une suggestion contextuelle (« Rôle suggéré : Membres
  confirmés — sera créé ») ouvre `+ Créer un rôle`, toujours modifiable, qui
  n'ajoute qu'une **proposition locale** (nom validé par
  `validateDiscordResourceName` de la Phase 3). Un rôle proposé seul, sans
  aucun rôle réel sélectionné, bloque explicitement l'étape avec un état
  `CANNOT` expliqué (« le rôle n'existe pas encore ») plutôt qu'un bouton
  désactivé sans cause.
- **Conflits** affiche, en lecture seule, les politiques existantes déjà
  compatibles avec la cible choisie — purement informatif, avec un rappel
  explicite que les conflits exacts viennent du même resolver canonique à
  l'étape Preview.
- **Preview/Impact** réutilise mot pour mot les routes Policy existantes
  (`POST .../policies` puis `POST .../policies/{id}/preview`) : décision
  avant/après, gains/pertes, membres impactés, conflits, précision
  `EXACT/BOUNDED/INCOMPLETE`. Aucune logique de résolution React parallèle.
  La création du brouillon est explicite (bouton « Créer le brouillon et
  prévisualiser », bandeau « Discord n'a pas été modifié ») : REQ-WIZ-013 est
  respecté puisque la Policy créée reste toujours `DRAFT`.
- **Plan** ne propose que « Préparer le plan » (jamais « Appliquer »). S'il
  existe un rôle proposé, un plan de rôle séparé (DSG existant, `symbol` sans
  `discord_id`, **validé mais jamais appliqué**) peut être préparé en plus ;
  la Policy elle-même ne référence que des rôles réellement existants, car le
  contrat `ACCESS_CONTROL` valide les `role_ids` contre le tenant à la
  création — un rôle encore proposé ne peut donc pas y figurer avant d'avoir
  été réellement créé via son propre Plan/Preflight/Apply (Phase 5).

### Annulation

Avant la moindre création de brouillon, « Quitter sans enregistrer » ne
déclenche aucun appel réseau. Une fois un brouillon `DRAFT` créé (action
explicite et disclosée, jamais silencieuse), le bouton devient « Quitter
(brouillon conservé) » : le brouillon existe déjà côté serveur mais reste
`DRAFT`, donc sans effet — la distinction est réelle, pas décorative,
puisqu'elle reflète exactement si un appel réseau a eu lieu ou non.

### Exigences fermées

`REQ-WIZ-001` à `010`, `013`, `014` passent d'**ABSENT** à **CONFORME**.
`REQ-POL-043` passe d'**ABSENT** à **CONFORME** (Policy proposée par un
Wizard, visible/éditable/previewable avant activation, jamais activée
silencieusement). `REQ-PERMX-010` passe de **PARTIEL** à **CONFORME** : le
Wizard consomme le même `PolicyResolver`/Plan Engine que le reste du produit,
sans calcul frontend autorisant une mutation. `REQ-WIZ-011`/`012`
(onboarding Phase 2) ne sont pas retouchés.

### Tests exécutés

- Unitaires (Vitest) : navigation avant/arrière et invalidation des étapes
  dépendantes (`reducer.test.ts`, 6 tests) ; rôle suggéré/créé reste une
  proposition locale, jamais un appel réseau (`RoleMultiSelect.test.tsx`,
  2 tests) ; annulation avant brouillon ne déclenche aucune mutation, et
  aucune affordance « Apply » n'existe sur la page
  (`AccessSpaceWizardScreen.test.tsx`, 2 tests).
- E2E Playwright ciblés (`e2e/phase04-wizard-access-space.spec.ts`, 2 tests
  au lieu de 3 en fusionnant un cas `CANNOT`) :
  1. parcours nominal avec axe sur `#main` — Assistants → Configurer l'accès
     → cible existante → « Visible uniquement par… » → rôle existant →
     Preview → Policy DRAFT → Préparer le plan, zéro requête `apply` ;
  2. rôle manquant — `+ Créer un rôle`, étape bloquée en `CANNOT` tant
     qu'aucun rôle réel n'est sélectionné, plan de rôle validé (jamais
     appliqué), Policy créée ne référence que le rôle réellement existant.
- Suite complète frontend (`npm run test`, `typecheck`, `lint`,
  `i18n:check`) et E2E Policies existant (`phase04-policies.spec.ts`)
  rejoués sans régression : un seul échec pré-existant et sans rapport
  (`StructureScreen.test.tsx`) reproduit identiquement sur `HEAD` avant ce
  lot.

### Tests volontairement non exécutés

Campagne backend complète, PostgreSQL/RLS (aucune table modifiée), Discord
live A/B, tout APPLY réel, Operations Center, matrice d'accès globale,
édition en masse, Templates (Phase 6) — aucun de ces éléments n'est concerné
par ce lot.

### Fichiers ajoutés/modifiés

Nouveaux : `features/wizards/core/{reducer,useWizard,WizardShell,
RoleMultiSelect}.tsx?`, `features/wizards/{catalog.ts,AssistantsScreen.tsx,
wizards.css}`, `features/wizards/accessSpace/AccessSpaceWizardScreen.tsx`,
`features/policies/{targets.ts,errors.ts}`, `localization/
phase4WizardCatalog.ts`, `e2e/phase04-wizard-access-space.spec.ts`, tests
unitaires associés. Modifiés : `app/App.tsx`, `app/AppShell.tsx`,
`localization/runtime.tsx`, `main.tsx`, `features/policies/PoliciesScreen.tsx`
(extraction de `buildPolicyTargets`/`targetKey`/`apiProblem` vers des modules
partagés, comportement inchangé). Aucune migration base de données.

## 16. Lot « Matrice d’accès simplifiée + édition massive » — 2026-09-15

### Architecture et source de vérité

Une entrée **Matrice d’accès** (`/guild/:guildId/matrix`) présente les rôles
non gérés en lignes et les catégories/salons du read model local en colonnes.
Le frontend émet une unique requête bornée (50 rôles × 150 ressources maximum)
vers `POST /api/v1/guilds/{guild_id}/access-matrix/resolve`. Il ne recalcule ni
bitfield, ni héritage, ni conflit.

Le service batch charge une seule fois le snapshot de Guild, les Policies et
les groupes logiques, puis délègue chaque cellule aux moteurs canoniques :

- `PermissionEvaluator` fournit l’accès Discord effectif ;
- `PolicyResolver` fournit intention, provenance héritée, exception et conflit ;
- une donnée stale/incomplète produit une synthèse `UNKNOWN`, jamais un faux
  « Aucun accès ».

La grille propose les filtres Tous, Conflits, Exceptions et Zones privées. Les
cellules sont des boutons accessibles au clavier (flèches, activation native),
avec libellé complet rôle × ressource × synthèse. Le clic ouvre d’abord un
éditeur d’intention humaine ; les détails Discord structurés restent repliés
derrière une action secondaire.

### Bulk, DRAFTs et Plans

Les cases d’en-tête permettent une sélection multiple de catégories et salons.
Le catalogue ne propose que les Policies compatibles avec au moins une cible ;
pour la Policy choisie, toutes les ressources incompatibles restent listées
avec leur raison. Les compteurs sélectionné/compatible/exclu sont séparés.

Deux commandes HTTP batch bornées évitent tout N×M ou N appels depuis React :

1. `POST .../policies/bulk-preview` crée une Policy `DRAFT` explicite par
   ressource compatible et renvoie la Preview canonique de chacune ;
2. `POST .../policies/bulk-plan` crée un Plan Policy canonique par DRAFT et
   retourne le nombre réel de Plans préparés.

Le service de Preview partage un seul chargement Policy/read-model pour le lot.
Chaque Policy porte un tag commun `bulk-operation:*`; chaque DRAFT et chaque
Plan reçoit une clé enfant déterministe dérivée de l’`Idempotency-Key` du geste.
Un retry après timeout retrouve donc les mêmes agrégats. La chaîne durable
reste strictement `ressource → Policy → révision → Plan`; aucun mega-payload,
second Plan Engine, endpoint Apply ou appel Discord direct n’a été ajouté.

L’écran agrège uniquement les compteurs de présentation des Previews :
différences avant/après, conflits, `BLOCKED`, `UNKNOWN` et précision
`EXACT/BOUNDED/INCOMPLETE`. Un lot non exact ou contenant `BLOCKED/UNKNOWN` ne
peut pas préparer de Plans.

Le menu contextuel canonique existant porte une action bulk de déplacement de
salons exigeant une catégorie destination ; il ne représente pas une sélection
mixte catégorie/salon ni une Policy. Aucun second menu concurrent n’a été créé :
`REQ-AP-BULK-004` (SHOULD) reste ouvert.

### Couverture de ce lot

- `REQ-AP-MAT-001` à `REQ-AP-MAT-006` : **couverts par ce lot** ;
- `REQ-AP-BULK-001` à `REQ-AP-BULK-003` : **couverts par ce lot** ;
- `REQ-AP-BULK-004` : **encore à faire**.

### Tests exécutés

- backend : `test_phase04_access_matrix.py`, 13 tests (déterminisme,
  PermissionEvaluator/PolicyResolver canoniques, conflit, tenant refusé avant
  lecture, stale/unknown, absence de mutation, limites et idempotence) ;
- backend Policy existant : 30 tests fondations + planning ;
- frontend : 4 tests unitaires ciblés (synthèse, filtres, exclusion motivée,
  sélection multiple) ;
- Playwright : 2 parcours ciblés, dont un refetch et un contrôle axe, avec zéro
  requête `/apply` ; le harness navigateur vérifie le contrat et les
  interactions, tandis que le calcul canonique lui-même est prouvé par les
  tests backend et non par la valeur mockée du harness ;
- Ruff, format Ruff, mypy ciblé, TypeScript, ESLint, i18n EN/FR/DE/ES, OpenAPI
  et `git diff --check`.

Tests non exécutés : campagne globale backend/frontend, PostgreSQL/RLS (aucune
table ni migration), Discord live A/B et tout APPLY réel.

### Inventaire factuel après ce lot — Phase 4 toujours ouverte

Déjà couvert : matrice et bulk ci-dessus ; socle intention-first, sept Policies
natives initiales, Policy générique/versionnée, resolver déterministe,
héritage visible, Preview/Impact, Explain, DRAFT→Plan canonique et Wizard accès.

Encore à faire ou à fermer complètement :

- contradictions/remédiations transverses : `REQ-AP-004` à `007` restent
  partiels jusqu’à la résolution complète des conflits ci-dessous ;
- visibilité/écriture avancées : `REQ-AP-VIS-004`, `011` à `014`, `016`, `017`,
  `REQ-AP-WRI-011` et `REQ-AP-WRI-022` ;
- menu contextuel Policy : `REQ-AP-BULK-004`, `REQ-AP-UX-004` ;
- vocal : `REQ-AP-VOC-001`, `010`, `020`, `021`, `030` ;
- threads/réactions/mentions : `REQ-AP-THR-001`, `REQ-AP-REA-001`,
  `REQ-AP-MEN-001` à `004`, ainsi que `REQ-AP-WRI-022` et `REQ-AP-PRS-013` ;
- bots : `REQ-AP-BOT-001` à `004` ;
- accès temporaires : `REQ-AP-TMP-001` à `006` ;
- politique maître de catégorie : socle catégorie/héritage présent, mais
  `REQ-AP-INH-003` (réappliquer aux exceptions) reste ouvert ;
- politique verrouillée, drift et auto-remédiation : `REQ-AP-LOCK-001` à `006`
  et leurs preuves `REQ-AP-TST-005` ;
- zones/audiences avancées : `REQ-AP-ZONE-001` à `003`, `010` à `012`, `020` à
  `023`, `030` à `032`, `040` à `041`, `050` à `052`, `060` à `061` ;
- presets encore absents/incomplets : `REQ-AP-PRS-001`, `010` à `013`, `020` à
  `022` ;
- résolution/optimisation de conflits complète : `REQ-AP-CFL-001` à `006`
  restent au minimum partiels tant que les causes rôle par rôle, remédiations
  valides et impacts collatéraux/plan séparé ne sont pas tous livrés ;
- lifecycle personnalisé : `REQ-AP-014` (suppression avec stratégie explicite)
  reste ouvert ; exemples logiques/favoris : `REQ-AP-UX-002` et `007` restent
  ouverts, et `REQ-AP-UX-006` devra être vérifié transversalement sur les
  fonctions restantes ;
- validation finale de ces fonctions : les `REQ-AP-TST-*` correspondantes ne
  seront fermées qu’avec les primitives concernées, sans extrapoler les deux
  parcours de ce lot.

Les `REQ-AP-*` restent des clarifications produit séparées : aucun statut de
l’audit historique des 389 exigences n’a changé dans ce lot, donc
`docs/10_implementation/11_REQUIREMENTS_IMPLEMENTATION_AUDIT.md` n’est pas
modifié.
