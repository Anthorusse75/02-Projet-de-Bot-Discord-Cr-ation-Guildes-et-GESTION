# Phase 4 — Rapport initial et réouverture post-audit

**Branche :** `ui/complete-redesign`  
**Statut actuel :** 🚧 **RÉOUVERTE — socle initial livré, complétion Policy/Wizard requise**  
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
