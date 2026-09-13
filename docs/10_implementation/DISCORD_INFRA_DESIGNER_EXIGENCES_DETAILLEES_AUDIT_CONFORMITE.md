# Discord Infrastructure Designer — Exigences détaillées consolidées et audit de conformité

> Version 1.0 — audit conservateur sur la branche `stage/10-acceptance` — 13 septembre 2026.

## 1. Objet

Ce document consolide le référentiel fonctionnel/technique existant, les décisions produit prises lors de la revue utilisateur et un audit conservateur du code actuel. Il **ne modifie pas** les documents gelés de `docs/00_reference`.

Le socle historique contient **246 exigences uniques** dans `docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md`. Elles restent normatives. Le présent document ajoute des exigences atomiques là où les décisions produit étaient plus précises que le registre historique, notamment le futur **Policy Engine**, les **Assistants/Wizards**, la persistance UX des opérations et la doctrine de réutilisation de packages/outils.

## 2. Règle d’audit

- Un fichier, une classe ou un écran n’est jamais une preuve suffisante à lui seul.
- Une exigence partiellement commencée reste **PARTIEL**.
- Les mentions `VERIFIED` du registre historique sont prises comme **preuve existante à vérifier**, pas comme vérité recopiée automatiquement.
- `NON DÉMONTRÉ` signifie “preuve indépendante insuffisante dans cet audit”, pas nécessairement “bug”.
- Pour les décisions de sécurité, l’absence de données doit conduire à `UNKNOWN/BLOCKED`, jamais à une hypothèse permissive.

### Légende

- **CONFORME** — Comportement démontré par code inspecté et preuve pertinente.
- **PARTIEL** — Une partie substantielle existe, mais un ou plusieurs critères restent manquants/non prouvés.
- **ABSENT** — Fonction exigée non trouvée dans le code audité ou seulement présente dans le référentiel.
- **NON DÉMONTRÉ** — Éléments plausibles présents, mais preuve insuffisante pour créditer la conformité.

## 3. Socle historique — 246 exigences

| Famille | Nb | Domaine | Audit indépendant | Observation |
|---|---:|---|---|---|
| REQ-INST | 7 | Installation / bootstrap | **NON DÉMONTRÉ** | Traçabilité existante riche, mais code d’installation/bootstrap non réinspecté intégralement dans cet audit. |
| REQ-TEN | 14 | Isolation multi-tenant / cross-Guild | **NON DÉMONTRÉ** | RLS et scoping sont documentés; inspection indépendante exhaustive de chaque endpoint non reproduite. |
| REQ-STR | 13 | Structure / arbre / drag & drop | **PARTIEL** | StructureScreen et ActionRegistry existent; absence d’audit ligne-à-ligne de tous les scénarios. |
| REQ-PERM | 9 | Moteur de permissions | **CONFORME** | PermissionEvaluator et views.py inspectés: OR des rôles, ordre des overwrites, owner/ADMINISTRATOR, View As, simple/expert, simulation. |
| REQ-PLAN | 16 | Planification / preflight / exécution | **CONFORME** | PlanningService et planning/models.py inspectés: persistance, DAG, preflight, auth, locks, états, risques et impacts. |
| REQ-DUP | 19 | Portabilité / clonage | **NON DÉMONTRÉ** | Arborescence et registre de traçabilité indiquent une implémentation importante, mais pipeline complet non réinspecté ici. |
| REQ-BOT | 7 | Gestion/capacités bot | **PARTIEL** | Quelques primitives et exigences sont visibles; couverture UI complète non prouvée. |
| REQ-AUTH | 14 | OAuth2 / session / autorisation | **NON DÉMONTRÉ** | Présence de modules auth/oauth, mais audit sécurité indépendant complet non reproduit. |
| REQ-GW | 8 | Gateway / intents / événements | **NON DÉMONTRÉ** | Modules runtime/gateway présents; conformité détaillée non réinspectée. |
| REQ-AUD | 6 | Audit / corrélation | **PARTIEL** | Plan lifecycle et journaux existent; couverture de toutes mutations non revalidée. |
| REQ-DATA | 2 | Données / rétention | **NON DÉMONTRÉ** | Politique référencée, mais tests de purge non réexécutés dans cet audit. |
| REQ-UX | 7 | UX générique | **PARTIEL** | Rôles, membres, permissions, plans et outbox ont des écrans; nouveaux besoins UX non couverts. |
| REQ-UX-CTX | 5 | Menus contextuels | **NON DÉMONTRÉ** | Déclaré vérifié par le registre; pas de réinspection approfondie des gestes/pointeurs ici. |
| REQ-I18N | 43 | Topologie multilingue | **NON DÉMONTRÉ** | Modules et exigences nombreuses, mais audit de conformité complet non reproduit. |
| REQ-CACHE | 13 | Cache / réconciliation | **NON DÉMONTRÉ** | Modules runtime/cache présents; tests de cohérence non réexécutés. |
| REQ-RATE | 6 | Rate limiting / backpressure | **NON DÉMONTRÉ** | Gouvernance runtime présente; comportement global non réinspecté. |
| REQ-UI18N | 21 | Internationalisation UI | **PARTIEL** | Catalogue/localization présents et usages de traduction observés; couverture 100 % non recalculée. |
| REQ-MSG | 31 | Campaigns / messagerie | **PARTIEL** | Sous-système très développé; policies spécialisées inspectées, mais 31 exigences non réauditées individuellement. |
| REQ-TEST | 5 | Tests / acceptation | **PARTIEL** | Suite Stage10 importante, mais skipped-tests et absence d’agrégat live A/B courant interdisent une validation globale sans réserve. |

## 4. Constats exécutifs

1. **Moteur de permissions : point fort.** L’inspection directe confirme les rôles cumulatifs, la priorité Discord des overwrites, owner/ADMINISTRATOR, View As, mode simple/expert et simulation avant/après.
2. **Planning : point fort.** Plans/opérations ont des identités et états persistants, préflight, impact, autorisation, locks et gestion d’outcome inconnu.
3. **Policy Engine générique : écart majeur.** Deux policies spécialisées existent (`message_content_policy.py`, `translation_policy.py`) mais aucun moteur de Policy administrable, versionné, scoped, composable et explicable n’est démontré.
4. **Wizards : écart majeur.** La recherche `wizard` dans le dépôt remonte le référentiel, pas une implémentation frontend dédiée.
5. **Templates : backend partiel, expérience produit incomplète.** La portabilité/template technique existe, mais le catalogue de modèles d’infrastructure préconstruits et adaptatifs du §25 n’est pas démontré comme UX complète.
6. **Opérations persistantes : backend solide, reprise UX inter-session à compléter/prouver.**
7. **Stage10 : couverture importante mais pas clôture absolue.** Des tests/scans optionnels sont encore conditionnellement skip et le registre indique qu’un agrégat Discord A/B courant n’était pas fourni pour REQ-TEST-003.

## 5. Exigences atomiques consolidées / ajoutées

### 5.1 Policies — gouvernance générique

| ID | Exigence atomique | Critère d’acceptation | Source | Statut | Preuve / écart |
|---|---|---|---|---|---|
| REQ-POL-001 | **Concept de premier rang** — Une Policy de gouvernance doit être un objet de domaine explicite, et non une condition métier dispersée dans les contrôleurs. | Une policy est sérialisable, résolue par un service de domaine et référencée par identifiant. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Aucun PolicyDefinition/Policy aggregate générique trouvé; seulement des helpers spécialisés. |
| REQ-POL-002 | **Identifiant stable** — Chaque Policy doit posséder un identifiant stable indépendant de son nom. | Renommer la policy ne change pas son ID ni ses références. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de modèle générique démontré. |
| REQ-POL-003 | **Type explicite** — Chaque Policy doit déclarer un type de policy supporté. | Le type est validé contre un registre fermé/versionné; un type inconnu est refusé. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de registre de policy générique démontré. |
| REQ-POL-004 | **Version** — Chaque Policy activable doit être versionnée. | Toute modification sémantique crée une nouvelle version ou révision traçable. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de versionnement générique démontré. |
| REQ-POL-005 | **Cycle de vie** — Le cycle de vie minimal doit distinguer DRAFT, ACTIVE, DISABLED et RETIRED. | Une transition invalide est refusée côté serveur. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de state machine générique trouvée. |
| REQ-POL-006 | **Métadonnées humaines** — Une Policy doit porter un nom et une description localisables/compréhensibles. | L’UI n’oblige pas l’administrateur à raisonner sur un ID technique. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas d’écran Policies générique. |
| REQ-POL-007 | **Scoping tenant par défaut** — Toute Policy métier est tenant-scopée par défaut. | guild_id obligatoire pour toute policy tenant, sauf type explicitement User Control Plane/global. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de stockage générique de policy démontré. |
| REQ-POL-008 | **Cible explicite** — Une Policy doit déclarer sa cible ou son scope applicable. | Les types de cibles autorisés sont validés selon le type de policy. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de mécanisme générique. |
| REQ-POL-009 | **Scopes supportés** — Le modèle doit pouvoir représenter, selon le type, Guild, groupe logique, catégorie, salon, rôle, membre, bot, campagne ou template. | Une cible non supportée pour un type est refusée. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de modèle générique. |
| REQ-POL-010 | **Conditions typées** — Les conditions d’une Policy doivent être typées et validées. | Un champ/operateur inconnu ou incompatible est rejeté avant activation. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de DSL/AST générique démontré. |
| REQ-POL-011 | **Effets typés** — Les effets d’une Policy doivent être typés et validés. | Un effet non supporté ne peut pas être persisté comme actif. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de moteur générique. |
| REQ-POL-012 | **Pas de code arbitraire** — Une Policy enregistrée ne doit jamais contenir de code exécutable arbitraire. | Les expressions sont déclaratives et évaluées par un moteur borné. | Décision produit + REF-ARCH (Domain/Policies) | **NON DÉMONTRÉ** | Aucun moteur générique présent; exigence à imposer avant implémentation. |
| REQ-POL-013 | **Déterminisme** — À données d’entrée identiques, la résolution des Policies doit produire le même résultat. | Tests répétés et ordre de stockage variable produisent la même décision. | Décision produit + REF-ARCH (Domain/Policies) | **PARTIEL** | Les policies spécialisées inspectées sont déterministes; pas de moteur générique. |
| REQ-POL-014 | **Héritage explicite** — Les règles d’héritage entre scopes doivent être définies par famille de Policy. | L’UI peut expliquer de quel scope provient une règle héritée. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de résolution générique. |
| REQ-POL-015 | **Priorité explicite** — Chaque famille de Policy doit définir sa sémantique de priorité. | La priorité ne dépend jamais accidentellement de l’ordre SQL ou de création. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de résolveur générique. |
| REQ-POL-016 | **Spécificité explicite** — Le rapport entre spécificité du scope et priorité explicite doit être défini. | Les cas Guild→groupe→catégorie→salon ont un résultat normatif testé. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de résolveur générique. |
| REQ-POL-017 | **Détection de conflit** — Le moteur doit détecter les Policies incompatibles applicables à une même décision. | Le conflit est retourné comme résultat structuré avec les policies impliquées. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de moteur générique. |
| REQ-POL-018 | **Résolution de conflit déterministe** — Un conflit résoluble doit suivre une règle documentée et déterministe. | Le résultat indique la règle de résolution utilisée. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de moteur générique. |
| REQ-POL-019 | **Conflit non résoluble** — Un conflit sans règle de résolution doit bloquer l’action ou demander une intervention. | Aucune préférence implicite permissive. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de moteur générique. |
| REQ-POL-020 | **Composition** — Plusieurs Policies applicables doivent pouvoir se composer sans perte d’information. | Le résultat expose la contribution de chaque policy. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de moteur générique. |
| REQ-POL-021 | **Enforcement serveur** — L’UI ne doit jamais être la seule barrière d’une Policy. | Toute mutation/use-case sensible appelle le résolveur serveur avant effet. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Les checks actuels sont spécialisés; pas de point d’enforcement générique. |
| REQ-POL-022 | **Préflight** — Le preflight d’un plan doit évaluer toutes les Policies pertinentes. | Une violation bloquante empêche l’autorisation/APPLY. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Planning preflight existe, mais intégration d’un moteur générique de policies non trouvée. |
| REQ-POL-023 | **Même moteur simulation/APPLY** — La simulation et APPLY doivent utiliser le même moteur de Policies. | Aucune logique approximative parallèle côté frontend. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de moteur générique. |
| REQ-POL-024 | **Explicabilité** — Toute décision de Policy doit être explicable. | Réponse: policies appliquées, scope source, conditions vraies/fausses, priorité et effet final. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas d’API Explain Policy générique. |
| REQ-POL-025 | **Pourquoi autorisé/refusé** — L’UI doit pouvoir répondre “Pourquoi cette action est-elle autorisée/refusée ?”. | La réponse vient de la décision serveur structurée. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas d’écran Policies générique. |
| REQ-POL-026 | **Impact avant/après** — Une modification de Policy doit produire une analyse d’impact avant activation. | Le nombre et type de cibles/décisions affectées sont calculés ou bornés. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de simulation de policy générique. |
| REQ-POL-027 | **Brouillon** — Une Policy doit pouvoir être créée/modifiée en DRAFT sans effet actif. | Sauvegarder un brouillon n’altère aucune décision active. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de lifecycle générique. |
| REQ-POL-028 | **Preview** — Une Policy en brouillon doit pouvoir être simulée. | La preview compare décision actuelle et proposée sur un échantillon/cible explicite. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de preview générique. |
| REQ-POL-029 | **Activation autorisée** — Activer une Policy exige une capability dédiée. | L’API refuse l’activation sans capability, indépendamment de l’UI. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de capability Policies démontrée. |
| REQ-POL-030 | **Désactivation autorisée** — Désactiver une Policy exige une capability dédiée. | La désactivation est auditée et idempotente. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de capability Policies démontrée. |
| REQ-POL-031 | **Historique immuable** — Les changements de Policy doivent produire un historique auditable immuable. | Auteur, date, ancienne/nouvelle version et motif/corrélation sont conservés. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Audit générique de policy non trouvé. |
| REQ-POL-032 | **Rollback/reapply** — Une version connue doit pouvoir être réappliquée quand cela est techniquement sûr. | Le système ne promet pas un rollback des effets Discord irréversibles. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de version générique. |
| REQ-POL-033 | **Cibles supprimées** — Une cible de Policy supprimée/inaccessible doit produire un état explicite. | Aucune policy orpheline n’est silencieusement considérée comme valide. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de modèle générique. |
| REQ-POL-034 | **Drift** — Un drift Discord affectant l’évaluation d’une Policy doit être diagnostiquable. | La décision expose fraîcheur/UNKNOWN ou déclenche réconciliation selon criticité. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Mécanismes de drift existent ailleurs, pas reliés à un moteur générique. |
| REQ-POL-035 | **RBAC Policies** — Les droits de lire/créer/modifier/activer/retirer des Policies doivent être séparables. | Capabilities indépendantes et testées cross-tenant. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de module Policies. |
| REQ-POL-036 | **Aucun cross-tenant** — Une Policy tenant-scopée ne peut jamais cibler une ressource d’une autre Guild. | Validation applicative + RLS/contraintes empêchent la référence. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de stockage générique. |
| REQ-POL-037 | **Isolation RLS** — Les tables de Policies tenant-scopées doivent utiliser les mêmes défenses RLS que les autres données tenant. | Test A/B réel: policy A inaccessible depuis tenant B. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de table générique trouvée. |
| REQ-POL-038 | **Idempotence** — Créer/activer/désactiver une Policy doit tolérer les retries. | Clé/idempotency semantics empêche double activation ou versions incohérentes. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de workflow générique. |
| REQ-POL-039 | **Concurrence** — Deux éditions concurrentes ne doivent pas s’écraser silencieusement. | Optimistic locking/version check ou équivalent produit un conflit explicite. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de workflow générique. |
| REQ-POL-040 | **Fail closed critique** — Une Policy de sécurité non évaluée faute de données ne doit pas devenir permissive. | Résultat UNKNOWN/BLOCKED; aucune autorisation implicite. | Décision produit + REF-ARCH (Domain/Policies) | **PARTIEL** | Permission engine actuel sait représenter incomplete/unknown; pas de policy engine générique. |
| REQ-POL-041 | **Mode simple** — L’éditeur simple de Policy doit utiliser un vocabulaire humain. | L’administrateur peut configurer sans connaître un DSL ni les bits Discord. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas d’UI Policies. |
| REQ-POL-042 | **Mode expert** — Un mode expert doit exposer conditions, scopes, priorités et résultat de résolution. | Tous les détails normatifs sont inspectables sans modifier le mode simple. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas d’UI Policies. |
| REQ-POL-043 | **Proposition par assistant** — Un Wizard peut proposer une Policy en brouillon. | La policy proposée est visible/éditable avant activation. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de Wizard implémenté. |
| REQ-POL-044 | **Pas d’activation silencieuse** — Un Wizard/template ne doit jamais activer silencieusement une Policy à impact significatif. | Activation passe par impact, confirmation et capability. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de workflow générique. |
| REQ-POL-045 | **Lien Plan** — Une Policy modifiant indirectement Discord doit produire ou alimenter le plan canonique. | Plan_id et policy_version sont corrélés. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas d’intégration générique. |
| REQ-POL-046 | **Lien Opération** — Les opérations générées par une Policy doivent indiquer leur origine. | Chaque opération permet de remonter à la policy/version déclenchante. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de provenance générique. |
| REQ-POL-047 | **Tests résolveur** — Le résolveur doit avoir des tests unitaires de vérité. | Matrice allow/deny/unknown/priorité/spécificité couverte. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de suite générique. |
| REQ-POL-048 | **Tests conflits** — Une matrice de conflits doit couvrir les combinaisons critiques. | Chaque combinaison a un résultat déterministe attendu. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de suite générique. |
| REQ-POL-049 | **Tests héritage** — Les règles d’héritage doivent être testées sur au moins Guild→groupe→catégorie→salon. | Tests prouvent override et héritage sans dépendre de l’ordre de création. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de suite générique. |
| REQ-POL-050 | **Tests isolation/API** — CRUD et activation Policies doivent avoir tests d’autorisation et cross-tenant. | 403/404 non révélateur et zéro effet cross-tenant. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas d’API générique. |
| REQ-POL-051 | **Tests persistance/preflight/E2E** — Le sous-système Policies doit avoir tests persistance, preflight, E2E et failure/retry. | CI couvre au moins création→preview→activation→enforcement→audit→désactivation. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Pas de sous-système générique. |
| REQ-POL-052 | **Réutilisation d’un moteur mature** — Avant de développer un DSL/rules engine maison, l’équipe doit évaluer des bibliothèques maintenues compatibles. | Décision ADR documente maintenance, licence, sécurité, expressivité, déterminisme, sandboxing et abstraction interne. | Décision produit + REF-ARCH (Domain/Policies) | **ABSENT** | Aucune décision spécifique de moteur générique de Policies trouvée. |
| REQ-POL-053 | **Distinction policies spécialisées** — Les policies message-content/translation existantes ne doivent pas être présentées comme un moteur de gouvernance générique. | Documentation/UI distingue helpers spécialisés et Policy Engine générique. | Décision produit + REF-ARCH (Domain/Policies) | **PARTIEL** | message_content_policy.py et translation_policy.py inspectés; absence de moteur générique confirmée. |

### 5.2 Assistants / Wizards

| ID | Exigence atomique | Critère d’acceptation | Source | Statut | Preuve / écart |
|---|---|---|---|---|---|
| REQ-WIZ-001 | **Entrée dédiée** — Le dashboard doit proposer une entrée visible “Assistants” ou “Wizards”. | L’entrée est accessible depuis la navigation principale et localisée. | REF-FONC §5.4 + décisions produit | **ABSENT** | Recherche code “wizard” ne retourne que le référentiel, pas d’implémentation frontend. |
| REQ-WIZ-002 | **Catalogue d’assistants** — Les assistants disponibles doivent être listés avec objectif, portée et prérequis. | L’utilisateur sait ce que chaque assistant modifiera avant de démarrer. | REF-FONC §5.4 + décisions produit | **ABSENT** | Aucun module frontend wizard identifié. |
| REQ-WIZ-003 | **Étapes guidées** — Un assistant est un flux multi-étapes explicite avec retour arrière. | Changer une réponse recalcule les étapes dépendantes sans mutation Discord. | REF-FONC §5.4 + décisions produit | **ABSENT** | Aucun wizard implémenté trouvé. |
| REQ-WIZ-004 | **Adaptation à l’état réel** — Les questions et propositions d’un assistant doivent dépendre de l’état actuel de la Guild. | Les rôles/catégories/salons existants sont proposés plutôt que recréés aveuglément. | REF-FONC §5.4 + décisions produit | **ABSENT** | Pas d’orchestrateur wizard. |
| REQ-WIZ-005 | **Rôles existants** — Toute étape demandant un rôle doit proposer les rôles compatibles existants. | Liste issue du read-model tenant courant; rôles inaccessibles signalés. | REF-FONC §5.4 + décisions produit | **ABSENT** | Pas de wizard. |
| REQ-WIZ-006 | **Rôles manquants suggérés** — Si un rôle pertinent n’existe pas, l’assistant doit proposer sa création. | La suggestion est marquée “sera créé” et n’est pas confondue avec un rôle existant. | REF-FONC §5.4 + décisions produit | **ABSENT** | Pas de wizard. |
| REQ-WIZ-007 | **Création libre +** — Les sélecteurs de rôle des assistants doivent offrir “+ Créer un rôle”. | L’utilisateur peut définir nom/couleur/propriétés minimales sans quitter le flux. | REF-FONC §5.4 + décisions produit | **ABSENT** | Pas de wizard. |
| REQ-WIZ-008 | **Édition avant plan** — Toute ressource suggérée doit être éditable avant compilation du plan. | Aucun nom/permission suggéré n’est imposé sans possibilité de correction. | REF-FONC §5.4 + décisions produit | **ABSENT** | Pas de wizard. |
| REQ-WIZ-009 | **Plan canonique** — Un assistant ne doit jamais appeler Discord par une voie parallèle. | Toutes les mutations se compilent dans le même Plan/Preflight/Impact/Confirmation/APPLY. | REF-FONC §5.4 + décisions produit | **ABSENT** | Planning canonique existe, mais aucun wizard branché dessus. |
| REQ-WIZ-010 | **Annulation sûre** — Annuler un assistant avant APPLY ne doit produire aucune mutation Discord. | Aucun effet autre que brouillon/audit minimal local. | REF-FONC §5.4 + décisions produit | **ABSENT** | Pas de wizard. |
| REQ-WIZ-011 | **Premier setup 9 étapes** — L’assistant de première configuration doit couvrir les neuf contrôles du §5.4 fonctionnel. | Bot présent, identité, droit bootstrap, perms bot, import, audit initial, limites, config proposée, activation tenant. | REF-FONC §5.4 + décisions produit | **NON DÉMONTRÉ** | Référentiel l’exige; aucun écran Wizard/setup dédié démontré dans l’inventaire frontend. |
| REQ-WIZ-012 | **Moindre privilège** — Le setup doit expliquer chaque permission bot demandée et éviter ADMINISTRATOR par commodité. | Une permission manquante désactive seulement les capacités concernées. | REF-FONC §5.4 + décisions produit | **PARTIEL** | Principe présent dans le référentiel et capability checks existants; flux Wizard non démontré. |
| REQ-WIZ-013 | **Policies proposées** — Un assistant peut proposer des Policies en DRAFT uniquement. | Activation séparée si impact significatif. | REF-FONC §5.4 + décisions produit | **ABSENT** | Ni Wizard ni Policy Engine générique. |
| REQ-WIZ-014 | **Localisation/a11y** — Tous les textes, erreurs et contrôles Wizard doivent suivre i18n et accessibilité du dashboard. | Aucune chaîne visible hardcodée; navigation clavier complète. | REF-FONC §5.4 + décisions produit | **ABSENT** | Pas de wizard à tester. |

### 5.3 UX, groupes, rôles, nommage

| ID | Exigence atomique | Critère d’acceptation | Source | Statut | Preuve / écart |
|---|---|---|---|---|---|
| REQ-UXN-001 | **Groupes logiques multiples** — Une Guild Discord doit pouvoir contenir plusieurs groupes logiques indépendants. | Création de deux groupes sans collision; mêmes catégories/rôles ne sont liés que selon règles explicites. | Décisions produit + REF-FONC §19/21/22 | **PARTIEL** | Concept Logical Group présent; multiplicité complète non réinspectée. |
| REQ-UXN-002 | **Identité interne stable** — Le concept interne doit rester `logical_group` indépendamment du vocabulaire UI. | Changer le libellé utilisateur n’altère ni ID ni API. | Décisions produit + REF-FONC §19/21/22 | **PARTIEL** | Logical Group est un concept existant; personnalisation du label non trouvée. |
| REQ-UXN-003 | **Libellé configurable** — L’administrateur peut choisir comment appeler les groupes: Équipe, Guilde, Clan, Projet ou libellé personnalisé. | Le choix s’applique aux libellés UI sans renommer le concept technique. | Décisions produit + REF-FONC §19/21/22 | **ABSENT** | Aucun paramètre de terminologie configurable identifié. |
| REQ-UXN-004 | **Aucune confusion Guild** — L’UI ne doit jamais confondre un groupe logique avec une Guild Discord réelle. | Les écrans multi-Guild gardent un vocabulaire non ambigu. | Décisions produit + REF-FONC §19/21/22 | **PARTIEL** | Référentiel distingue les concepts; conformité de chaque écran non auditée. |
| REQ-UXN-005 | **Renommage second clic** — Un élément sélectionné doit pouvoir entrer en renommage inline après un second clic lent sur son libellé. | Premier clic sélectionne; second clic non-double-clic ouvre édition inline. | Décisions produit + REF-FONC §19/21/22 | **ABSENT** | Aucun comportement de type Windows démontré. |
| REQ-UXN-006 | **Alternative F2** — F2 doit pouvoir déclencher le renommage quand le composant a le focus. | Même validation et même plan que l’édition inline. | Décisions produit + REF-FONC §19/21/22 | **ABSENT** | Pas de preuve trouvée. |
| REQ-UXN-007 | **Alternative menu** — Le menu contextuel doit proposer Renommer quand l’action est autorisée. | Action issue du registre canonique, pas d’implémentation parallèle. | Décisions produit + REF-FONC §19/21/22 | **NON DÉMONTRÉ** | Menus contextuels existent; action rename spécifique non auditée. |
| REQ-UXN-008 | **Rôles cumulatifs** — Le calcul d’accès d’un membre doit agréger tous ses rôles Discord. | OR des permissions de base; overwrites de rôles agrégés selon l’ordre Discord. | Décisions produit + REF-FONC §19/21/22 | **CONFORME** | permissions/calculator.py inspecté: BASE_ROLES_OR + rôle denies/allows agrégés. |
| REQ-UXN-009 | **Pas de profil mono-rôle** — Aucune UI métier ne doit présenter un membre comme appartenant à un seul rôle exclusif si Discord en autorise plusieurs. | Les sélecteurs/analyses montrent un ensemble de rôles. | Décisions produit + REF-FONC §19/21/22 | **PARTIEL** | Moteur multi-rôles conforme; audit de toutes les UIs non réalisé. |
| REQ-UXN-010 | **Règle ANY** — Les conditions multi-rôles doivent pouvoir exprimer “au moins un de ces rôles”. | Résultat testé avec zéro, un et plusieurs rôles correspondants. | Décisions produit + REF-FONC §19/21/22 | **NON DÉMONTRÉ** | Pas de moteur de règles générique démontré. |
| REQ-UXN-011 | **Règle ALL** — Les conditions multi-rôles doivent pouvoir exprimer “tous ces rôles”. | Résultat testé avec ensembles incomplets/complets. | Décisions produit + REF-FONC §19/21/22 | **NON DÉMONTRÉ** | Pas de moteur de règles générique démontré. |
| REQ-UXN-012 | **Unicode noms** — Les noms de catégories/salons proposés doivent supporter Unicode/emoji autorisé par Discord. | Round-trip API/DB/UI sans corruption. | Décisions produit + REF-FONC §19/21/22 | **PARTIEL** | Pile UI i18n/Unicode existe; workflow de nommage dédié non démontré. |
| REQ-UXN-013 | **Emoji picker** — Les champs de nom pertinents doivent proposer un sélecteur d’emoji réutilisable. | Clavier/souris, recherche et insertion au curseur. | Décisions produit + REF-FONC §19/21/22 | **ABSENT** | Aucun emoji picker dédié identifié dans l’inventaire. |
| REQ-UXN-014 | **Noms stylés** — Le produit doit proposer des styles de noms sobres optionnels (emoji, séparateurs, symboles). | Suggestions non destructives, aperçu et validation des limites Discord. | Décisions produit + REF-FONC §19/21/22 | **ABSENT** | Aucun générateur/preset de naming identifié. |
| REQ-UXN-015 | **Validation Discord** — Toute suggestion de nom doit respecter les contraintes Discord applicables au type de ressource. | Nom invalide bloqué avant plan. | Décisions produit + REF-FONC §19/21/22 | **PARTIEL** | Validation structurelle existe globalement; suggestions de naming non implémentées. |
| REQ-UXN-016 | **Acronyme produit** — L’acronyme interne DID ne doit pas être imposé sans explication dans l’UI utilisateur. | Première occurrence = nom complet ou libellé métier; jargon interne masqué. | Décisions produit + REF-FONC §19/21/22 | **NON DÉMONTRÉ** | Le code utilise did comme package; usage visible global non audité exhaustivement. |
| REQ-UXN-017 | **Aide contextuelle** — Les décisions complexes doivent offrir une aide contextuelle proche du contrôle. | Tooltip/explication localisée sans obliger à consulter la documentation externe. | Décisions produit + REF-FONC §19/21/22 | **NON DÉMONTRÉ** | Tooltips existent dans le socle i18n, couverture métier non auditée. |
| REQ-UXN-018 | **Progressive disclosure** — Le mode simple doit être par défaut et le mode expert révéler les détails natifs sans supprimer de puissance. | Même décision de fond, deux niveaux de présentation. | Décisions produit + REF-FONC §19/21/22 | **CONFORME** | permissions/views.py expose SimplePermissionConcept et ExpertPermissionModel sur le même moteur. |

### 5.4 Opérations persistantes et brouillons

| ID | Exigence atomique | Critère d’acceptation | Source | Statut | Preuve / écart |
|---|---|---|---|---|---|
| REQ-OPS-001 | **Identité durable opération** — Toute opération longue doit avoir un identifiant serveur durable. | L’ID permet de relire l’état après reconnexion. | Décisions produit + REF-FONC §20 | **CONFORME** | Plan/Operation IDs et états persistés existent dans planning models/service. |
| REQ-OPS-002 | **État serveur** — La vérité d’une opération ne doit pas dépendre de l’onglet navigateur. | Rafraîchir/fermer l’onglet ne perd pas l’état serveur. | Décisions produit + REF-FONC §20 | **CONFORME** | Plans et opérations persistés côté backend. |
| REQ-OPS-003 | **Reprise après reconnexion** — Après logout/login ou reconnexion, l’utilisateur doit retrouver les opérations qu’il a lancées et est autorisé à voir. | Liste/reprise via API; aucune dépendance à mémoire JS locale. | Décisions produit + REF-FONC §20 | **PARTIEL** | Persistance backend démontrée; UX de reprise après nouvelle session non démontrée. |
| REQ-OPS-004 | **Centre d’opérations** — Le dashboard doit disposer d’un endroit persistant pour suivre les opérations récentes/en cours. | Affiche statut, progression, résultat, erreurs et actions possibles. | Décisions produit + REF-FONC §20 | **PARTIEL** | OutboxScreen/PlanDrawer existent; sémantique “centre d’opérations” et reprise session non totalement prouvées. |
| REQ-OPS-005 | **États utilisateur** — Les opérations doivent exposer au minimum queued/in progress/completed/failed/cancelled/blocked ou équivalents. | Mapping stable entre états techniques et libellés localisés. | Décisions produit + REF-FONC §20 | **PARTIEL** | PlanState/OperationState riches existent; équivalence UX complète non auditée. |
| REQ-OPS-006 | **Erreur persistante** — Une erreur finale doit rester consultable après disparition d’un toast. | Code, message localisable, request/plan/op ID et étape sont disponibles. | Décisions produit + REF-FONC §20 | **PARTIEL** | Persistance des résultats/erreurs plan présente; UX globale non démontrée. |
| REQ-OPS-007 | **Actions de reprise** — Quand techniquement possible, l’UI doit proposer retry/reconcile/intervention plutôt qu’un simple échec opaque. | Action permise uniquement selon état et risque. | Décisions produit + REF-FONC §20 | **PARTIEL** | UNKNOWN_OUTCOME/reconciliation existent; UI complète non auditée. |
| REQ-OPS-008 | **Brouillon explicite** — Une configuration non appliquée doit être identifiée comme brouillon et non comme état actif. | Étiquette/état DRAFT visible. | Décisions produit + REF-FONC §20 | **PARTIEL** | PlanState.DRAFT existe; usage universel hors plan non démontré. |
| REQ-OPS-009 | **Appliquer brouillon** — Un brouillon validable doit pouvoir être compilé/appliqué via le pipeline canonique. | Preflight et confirmation avant mutation. | Décisions produit + REF-FONC §20 | **PARTIEL** | Pipeline plan existe; tous types de brouillons non unifiés. |
| REQ-OPS-010 | **Abandonner brouillon** — L’utilisateur doit pouvoir abandonner explicitement un brouillon. | Action distincte de l’échec et de l’annulation d’une opération en cours. | Décisions produit + REF-FONC §20 | **NON DÉMONTRÉ** | Pas de sémantique unifiée “Discard draft” démontrée. |
| REQ-OPS-011 | **Suppression payload brouillon** — Après abandon confirmé, le payload métier du brouillon doit être supprimé selon la politique de rétention. | Une relecture ne restitue pas le contenu abandonné. | Décisions produit + REF-FONC §20 | **NON DÉMONTRÉ** | Pas de preuve de purge du payload de draft. |
| REQ-OPS-012 | **Audit minimal abandon** — Un événement minimal peut subsister pour audit sans conserver inutilement le contenu du brouillon. | Conserve ID/auteur/date/type, pas les données sensibles non nécessaires. | Décisions produit + REF-FONC §20 | **NON DÉMONTRÉ** | Pas de politique dédiée démontrée. |
| REQ-OPS-013 | **Pas de succès optimiste** — Une opération n’est affichée comme réussie qu’après état serveur appliqué/vérifié accepté. | Aucun toast “succès” basé uniquement sur 202/queue. | Décisions produit + REF-FONC §20 | **CONFORME** | REQ-UX-007 et architecture plan; état terminal backend utilisé. |
| REQ-OPS-014 | **Progression par étape** — Les opérations longues doivent afficher leur progression durable par étape. | Progression relisible et non seulement animation locale. | Décisions produit + REF-FONC §20 | **PARTIEL** | REQ-UX-006 et plan progress existent; persistance inter-session UI non complètement prouvée. |

### 5.5 Templates d’infrastructure

| ID | Exigence atomique | Critère d’acceptation | Source | Statut | Preuve / écart |
|---|---|---|---|---|---|
| REQ-TPL-001 | **Catalogue infrastructure** — Le produit doit proposer un catalogue de modèles d’infrastructure Discord. | Au minimum les familles prévues au §25: gaming, professionnel, communauté, éducatif ou équivalents. | REF-FONC §25 + décisions produit | **PARTIEL** | Stage06 possède des templates portables; aucun catalogue UX préconstruit clairement démontré. |
| REQ-TPL-002 | **Adaptation Guild** — Un template doit s’adapter à la Guild sélectionnée. | Analyse existants/capacités/limites avant proposition. | REF-FONC §25 + décisions produit | **PARTIEL** | Pipeline portable/preflight existe; UX d’adaptation préconstruite non prouvée. |
| REQ-TPL-003 | **Aperçu** — Le template doit produire une preview/diff avant mutation. | Ressources créées/réutilisées/remappées/ignorées/impossibles visibles. | REF-FONC §25 + décisions produit | **PARTIEL** | Portabilité rapporte mappings; écran dédié de template infrastructure non prouvé. |
| REQ-TPL-004 | **Rôles suggérés** — Un template peut suggérer des rôles absents sans les créer immédiatement. | Suggestion éditable et confirmable. | REF-FONC §25 + décisions produit | **PARTIEL** | COPY_AS_NEW sait créer; expérience de suggestion non démontrée. |
| REQ-TPL-005 | **Références symboliques** — Un template portable ne doit pas dépendre d’IDs Discord source comme identité cible. | Mappings/symboles explicites utilisés. | REF-FONC §25 + décisions produit | **CONFORME** | REQ-DUP-005/008 et architecture portabilité existante. |
| REQ-TPL-006 | **Validation capacités** — Un template incompatible avec les capacités/limites Discord ne peut pas être appliqué. | Preflight bloque avant mutation. | REF-FONC §25 + décisions produit | **CONFORME** | REQ-DUP-006 + planning preflight. |
| REQ-TPL-007 | **Policies en brouillon** — Un template peut inclure des définitions de Policies, mais les bindings/activations sensibles exigent mapping et confirmation. | Aucune activation cross-tenant ou binding implicite. | REF-FONC §25 + décisions produit | **PARTIEL** | REQ-DUP-019 couvre portabilité de définitions; moteur générique de Policy absent. |
| REQ-TPL-008 | **Bibliothèque privée** — Les templates privés doivent être isolés par tenant/utilisateur selon leur portée. | RLS et ACL testées. | REF-FONC §25 + décisions produit | **NON DÉMONTRÉ** | Traceabilité indique REQ-TEN-008 vérifié; non réaudité indépendamment. |
| REQ-TPL-009 | **Version de template** — Les templates publiés doivent être versionnés pour rendre les plans reproductibles. | Une application enregistre template_id + version/hash. | REF-FONC §25 + décisions produit | **NON DÉMONTRÉ** | Pas de preuve indépendante suffisante. |
| REQ-TPL-010 | **Même pipeline** — Wizard, template, import et drag/clonage doivent converger vers les mêmes primitives de plan. | Aucun “fast path” de mutation directe. | REF-FONC §25 + décisions produit | **PARTIEL** | Portabilité converge sur planning; Wizard absent. |

### 5.6 Réutilisation packages/outils

| ID | Exigence atomique | Critère d’acceptation | Source | Statut | Preuve / écart |
|---|---|---|---|---|---|
| REQ-REUSE-001 | **Principe de réutilisation** — Ne pas redévelopper une fonctionnalité générique déjà correctement résolue par une bibliothèque/outil mature, maintenu et compatible. | Toute décision de build générique est justifiée par une courte évaluation buy/use/build. | Décision d’architecture produit | **PARTIEL** | Architecture recommande dnd-kit, Radix/shadcn, i18next, discord.py, etc.; processus formel non démontré. |
| REQ-REUSE-002 | **Recherche préalable** — Avant développement d’un composant générique, rechercher des solutions existantes adaptées. | Trace ADR/issue des options évaluées pour composants significatifs. | Décision d’architecture produit | **NON DÉMONTRÉ** | Pas de gate formel trouvé. |
| REQ-REUSE-003 | **Maintenance** — Une dépendance retenue doit avoir une maintenance/activité compatible avec le risque. | Critère documenté: cadence, bus factor, compatibilité runtime. | Décision d’architecture produit | **NON DÉMONTRÉ** | Pas de checklist formelle trouvée. |
| REQ-REUSE-004 | **Licence** — La licence doit être compatible avec le projet avant intégration. | Licence et obligations documentées. | Décision d’architecture produit | **NON DÉMONTRÉ** | Pas de gate formel trouvé. |
| REQ-REUSE-005 | **Sécurité** — Les dépendances à surface sensible doivent être évaluées côté sécurité. | Version pinning, audit de vulnérabilités et politique de mise à jour. | Décision d’architecture produit | **PARTIEL** | uv.lock/npm audit et Stage10 existent; règle universelle non prouvée. |
| REQ-REUSE-006 | **Adéquation** — Une bibliothèque n’est retenue que si elle couvre le besoin sans tordre le modèle métier. | Limites connues documentées; pas de dépendance pour contourner une contrainte fondamentale. | Décision d’architecture produit | **NON DÉMONTRÉ** | Pas de dossier d’évaluation systématique. |
| REQ-REUSE-007 | **Abstraction interne** — Les bibliothèques structurantes doivent être encapsulées derrière une abstraction interne lorsque le couplage serait coûteux. | Le domaine ne dépend pas directement du fournisseur pour les ports critiques. | Décision d’architecture produit | **PARTIEL** | discord.py et TranslationProvider sont abstraits; pratique à généraliser. |
| REQ-REUSE-008 | **Logique métier maison** — Le code custom doit se concentrer sur la logique propre au produit. | Permissions Discord, planning, mapping, policy semantics restent dans domaine/application. | Décision d’architecture produit | **CONFORME** | Architecture en couches et moteur permissions/planning custom démontrés. |
| REQ-REUSE-009 | **UI générique** — Sélecteurs emoji, DnD, arbres, dialogues, virtualisation et composants a11y doivent privilégier des bibliothèques éprouvées. | Choix réutilisables et accessibles; pas de widget artisanal sans justification. | Décision d’architecture produit | **PARTIEL** | dnd-kit et primitives UI sont prévus/utilisés; emoji picker pas encore présent. |
| REQ-REUSE-010 | **Jobs/résilience** — Queue, retry/backoff, locks et streams doivent réutiliser des primitives éprouvées derrière interfaces internes. | Pas de protocole distribué ad hoc non testé si une primitive mature convient. | Décision d’architecture produit | **PARTIEL** | Redis/streams/locks et abstractions existent; audit exhaustif non réalisé. |
| REQ-REUSE-011 | **Validation/règles** — JSON schema/validation/rules expression doivent réutiliser des outils matures si adaptés. | L’équipe compare explicitement avant de bâtir un DSL maison. | Décision d’architecture produit | **NON DÉMONTRÉ** | À appliquer au futur Policy Engine. |
| REQ-REUSE-012 | **Reversibilité fournisseur** — Une dépendance structurante ne doit pas dicter le modèle métier. | Ports/adapters permettent remplacement raisonnable quand pertinent. | Décision d’architecture produit | **PARTIEL** | TranslationProvider/Discord adapter sont de bons exemples; pas prouvé partout. |

### 5.7 Permission analysis — exigences renforcées

| ID | Exigence atomique | Critère d’acceptation | Source | Statut | Preuve / écart |
|---|---|---|---|---|---|
| REQ-PERMX-001 | **Règles Discord fidèles** — L’analyse des permissions doit suivre l’algorithme Discord réel, jamais une heuristique approximative. | Vecteurs owner/admin/base roles/overwrites/threads validés. | REF-FONC §19 + décisions produit | **CONFORME** | PermissionEvaluator inspecté. |
| REQ-PERMX-002 | **Données incomplètes** — Si les données nécessaires sont incomplètes/obsolètes, la décision doit être UNKNOWN/INCOMPLETE plutôt qu’inventée. | Coverage/freshness visibles dans résultat. | REF-FONC §19 + décisions produit | **CONFORME** | PermissionDecision expose coverage/freshness/status/unknown bits. |
| REQ-PERMX-003 | **Explication ordonnée** — “Pourquoi a-t-il accès ?” doit fournir les étapes de résolution dans l’ordre effectif. | Trace structurée et stable. | REF-FONC §19 + décisions produit | **CONFORME** | Trace/reasons dans evaluator; REF §19. |
| REQ-PERMX-004 | **View As membre** — Simulation d’un membre réel. | Utilise ses rôles connus et ses overwrites; pas de mutation. | REF-FONC §19 + décisions produit | **CONFORME** | ViewAsMode.MEMBER inspecté. |
| REQ-PERMX-005 | **View As rôle** — Simulation d’un rôle synthétique. | Évite owner bypass accidentel et respecte règles Discord. | REF-FONC §19 + décisions produit | **CONFORME** | ViewAsMode.ROLE inspecté. |
| REQ-PERMX-006 | **View As nouvel arrivant** — Simulation d’un newcomer. | Sujet synthétique minimal et résultats explicables. | REF-FONC §19 + décisions produit | **CONFORME** | ViewAsMode.NEWCOMER inspecté. |
| REQ-PERMX-007 | **Avant/après** — Toute modification de permissions proposée doit pouvoir comparer avant/après. | Added/removed bits et sujets incomplets retournés. | REF-FONC §19 + décisions produit | **CONFORME** | simulate_overwrites inspecté. |
| REQ-PERMX-008 | **Simple humain** — Le mode simple compile des concepts humains vers flags réels. | VIEW/WRITE/MANAGE/VOICE* reposent sur registry officielle. | REF-FONC §19 + décisions produit | **CONFORME** | compile_simple_permissions inspecté. |
| REQ-PERMX-009 | **Expert réel** — Le mode expert montre bits/flags/overwrites réels, y compris inconnus. | Aucune “permission simplifiée” présentée comme native. | REF-FONC §19 + décisions produit | **CONFORME** | ExpertPermissionModel inspecté. |
| REQ-PERMX-010 | **Même moteur partout** — Wizard, Policy, membre et plan doivent consommer le moteur canonique de permissions. | Aucun calcul séparé frontend ne peut autoriser une mutation. | REF-FONC §19 + décisions produit | **PARTIEL** | Moteur canonique existe; Wizard/Policy Engine absents. |

### 5.8 Qualité, tests et preuve de conformité

| ID | Exigence atomique | Critère d’acceptation | Source | Statut | Preuve / écart |
|---|---|---|---|---|---|
| REQ-QA-001 | **Critère de conformité** — Un fichier, une classe ou un écran ne suffit pas à déclarer une exigence conforme. | Preuve porte sur le comportement bout-en-bout nécessaire. | Méthode audit + Stage10 | **PARTIEL** | Règle d’audit adoptée ici; traçabilité historique parfois plus large que preuve réinspectée. |
| REQ-QA-002 | **Partiel non conforme** — Une fonctionnalité commencée mais incomplète doit être marquée PARTIEL, pas CONFORME. | Tous critères d’acceptation obligatoires sont cochés avant statut conforme. | Méthode audit + Stage10 | **CONFORME** | Méthode de ce document. |
| REQ-QA-003 | **Tests unité** — La logique déterministe critique doit avoir des tests unitaires. | Permissions/policies/planning ont matrices de vérité adaptées. | Méthode audit + Stage10 | **PARTIEL** | Permissions/planning fortement testés; futur Policy Engine absent. |
| REQ-QA-004 | **Tests intégration DB** — Les invariants tenant/persistance doivent être testés sur PostgreSQL réel lorsque pertinent. | RLS, contraintes et transactions incluses. | Méthode audit + Stage10 | **PARTIEL** | Historique Stage10 affirme couverture; pas tout réexécuté. |
| REQ-QA-005 | **Tests API** — Les autorisations/erreurs critiques doivent avoir des tests API. | Inclut cross-tenant et absence d’effet secondaire. | Méthode audit + Stage10 | **PARTIEL** | Suite importante déclarée; audit indépendant exhaustif non reproduit. |
| REQ-QA-006 | **Tests E2E** — Les flows critiques doivent avoir E2E navigateur. | Flux utilisateur réel jusqu’au résultat serveur. | Méthode audit + Stage10 | **PARTIEL** | Stage07-10 E2E existent; nouveaux Wizards/Policies non couverts. |
| REQ-QA-007 | **Tests reconnect** — Les opérations persistantes doivent être testées après reload/logout-login/reconnexion. | Le même job/plan est retrouvable et son état final cohérent. | Méthode audit + Stage10 | **ABSENT** | Aucune preuve spécifique identifiée. |
| REQ-QA-008 | **Tests brouillons** — Apply/Discard doit être testé, y compris purge du payload. | Après discard, payload non récupérable; audit minimal conforme. | Méthode audit + Stage10 | **ABSENT** | Fonction non démontrée. |
| REQ-QA-009 | **Tests Policies** — Le futur Policy Engine doit avoir matrice conflit/héritage/priority/unknown. | Couverture de branches critique mesurable. | Méthode audit + Stage10 | **ABSENT** | Moteur absent. |
| REQ-QA-010 | **A11y sans skip critique** — Les scans d’accessibilité critiques ne doivent pas rester optionnels pour la release cible. | Aucun skip sérieux/critique inexpliqué dans la gate finale. | Méthode audit + Stage10 | **PARTIEL** | artifacts/stage10-audit/skipped-tests.txt montre des scans conditionnels/skip. |
| REQ-QA-011 | **Live A/B actuel** — La clôture acceptance doit disposer d’un agrégat live A/B courant quand l’exigence le requiert. | Rapports corrélés au commit/branche audité. | Méthode audit + Stage10 | **PARTIEL** | REQ-TEST-003 dans registre: implémenté mais agrégat courant non fourni à ce rendu. |
| REQ-QA-012 | **Preuve reproductible** — Chaque preuve de conformité doit pointer vers code/test/commande ou artifact reproductible. | Un simple “VERIFIED” sans preuve ciblée n’est pas suffisant pour audit indépendant. | Méthode audit + Stage10 | **PARTIEL** | Registre contient preuves, mais leur réexécution indépendante n’a pas été exhaustive ici. |

## 6. Synthèse chiffrée des exigences ajoutées

Nombre d’exigences atomiques ajoutées/raffinées dans ce document : **143**.

| Statut | Nombre |
|---|---:|
| CONFORME | 18 |
| PARTIEL | 39 |
| ABSENT | 69 |
| NON DÉMONTRÉ | 17 |

### Par famille

| Famille | Total | Conforme | Partiel | Absent | Non démontré |
|---|---:|---:|---:|---:|---:|
| POL — Policies — gouvernance générique | 53 | 0 | 3 | 49 | 1 |
| WIZ — Assistants / Wizards | 14 | 0 | 1 | 12 | 1 |
| UXN — UX, groupes, rôles, nommage | 18 | 2 | 6 | 5 | 5 |
| OPS — Opérations persistantes et brouillons | 14 | 3 | 8 | 0 | 3 |
| TPL — Templates d’infrastructure | 10 | 2 | 6 | 0 | 2 |
| REUSE — Réutilisation packages/outils | 12 | 1 | 6 | 0 | 5 |
| PERMX — Permission analysis — exigences renforcées | 10 | 9 | 1 | 0 | 0 |
| QA — Qualité, tests et preuve de conformité | 12 | 1 | 8 | 3 | 0 |

## 7. Backlog recommandé

### P0 — fondations à faire avant d’étendre encore le produit
- Créer le **Policy Engine générique** : aggregate, stockage/RLS, resolver déterministe, héritage/priorité/conflits, explain, preflight, simulation, audit, RBAC, tests.
- Brancher toute Policy impactante sur le **pipeline de plan canonique**, sans voie de mutation parallèle.
- Verrouiller la règle **fail-closed** sur les décisions de sécurité/policy à données incomplètes.
- Formaliser la doctrine **reuse-first** pour le futur moteur de règles/expressions avant d’écrire un DSL maison.

### P1 — simplicité produit à très forte valeur
- Créer l’espace **Assistants/Wizards** et le Wizard de première configuration.
- Ajouter suggestions de rôles manquants + `+ Créer un rôle` + édition avant plan.
- Construire l’UI **Policies** simple/expert avec preview, impact et “Pourquoi ?”.
- Construire un **Centre d’opérations** réellement persistant après reconnexion/login.
- Compléter le **catalogue de templates d’infrastructure** préconstruits/adaptatifs.

### P2 — finition UX
- Renommage inline second clic + F2 + menu contextuel.
- Libellé configurable des groupes logiques sans changer le concept technique.
- Emoji picker + presets de noms stylés validés selon Discord.
- Aide contextuelle systématique et suppression du jargon/acronymes internes inexpliqués.

## 8. Preuves techniques inspectées directement

- `backend/src/did/permissions/calculator.py` — calcul réel des permissions, cumul des rôles, overwrite order, owner/ADMINISTRATOR, unknown/freshness.
- `backend/src/did/permissions/views.py` — View As, simple/expert, simulation before/after.
- `backend/src/did/application/planning/service.py` — create/compile/preview/preflight/impact/authorize, tenant scope, lock/rate budget.
- `backend/src/did/planning/models.py` — états Plan/Operation, risques, types d’opérations, impact/checklist.
- `frontend/src/features/roles/RolesScreen.tsx` — CRUD/duplication/reorder/drag-drop/permission editor.
- `backend/src/did/campaigns/message_content_policy.py` — policy spécialisée de capture de contenu.
- `backend/src/did/messaging/translation_policy.py` — policy spécialisée de forwarding/traduction.
- Inventaire frontend — modules roles/members/permissions/plans/audit/outbox/...; pas de module Wizard ou Policies générique identifié.
- `artifacts/stage10-audit/skipped-tests.txt` — scans E2E/accessibility conditionnels.
- `docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md` — registre historique de 246 exigences, utilisé comme source de couverture mais pas comme validation automatique.

## 9. Limites de cet audit

Cet audit est volontairement conservateur. L’inventaire des sources backend/frontend/tests a été parcouru et plusieurs modules critiques ont été inspectés directement, mais **tous les fichiers du dépôt n’ont pas été relus ligne par ligne ni tous les tests réexécutés localement**. Le connecteur GitHub permet l’inspection du dépôt, pas l’exécution complète de son environnement CI/Discord. En conséquence, tout point non suffisamment prouvé est classé PARTIEL ou NON DÉMONTRÉ plutôt que crédité par hypothèse.

## 10. Décision de gouvernance documentaire

Le dossier `docs/00_reference` reste inchangé. Ce document doit vivre dans `docs/10_implementation/` tant que les nouvelles exigences n’ont pas été officiellement intégrées au référentiel. Après validation produit, les nouvelles familles doivent être ajoutées au registre canonique/générateur de traçabilité afin de devenir des exigences de release au même niveau que les 246 exigences historiques.