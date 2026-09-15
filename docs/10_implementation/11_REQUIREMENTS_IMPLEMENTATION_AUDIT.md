# Discord Infrastructure Designer — Audit d’implémentation

> Snapshot audité : `ui/complete-redesign` — HEAD du lot UI Policies
> Périmètre : **389 exigences** — 246 historiques + 143 détaillées.

## Méthode

`CONFORME` = comportement et preuves suffisants; `PARTIEL` = une partie existe mais un critère manque; `ABSENT` = comportement non trouvé; `NON DÉMONTRÉ` = éléments plausibles mais preuve insuffisante. Un fichier/classe/écran seul ne vaut pas conformité.

Libellés canoniques : `00_REQUIREMENTS_TRACEABILITY.md` (246 historiques) et `DISCORD_INFRA_DESIGNER_EXIGENCES_DETAILLEES_AUDIT_CONFORMITE.md` (143 détaillées).

## Résultat

| Statut | Nb |
|---|---:|
| CONFORME | 328 |
| PARTIEL | 35 |
| ABSENT | 16 |
| NON DÉMONTRÉ | 10 |
| **Total** | **389** |

Le socle historique est à **244 CONFORME / 2 PARTIEL** (`REQ-BOT-005`, `REQ-TEST-003`). Les écarts nouveaux portent surtout sur Policies, Wizards, UX nouvelle, reprise inter-session et templates produit.

### Complément ciblé `ui/complete-redesign` — Phases 2 et 3

L'audit initial portait sur un autre snapshot. La réinspection du code courant, les corrections ciblées et leurs preuves font passer uniquement les IDs suivants à **CONFORME** :

| ID | Preuve complémentaire |
|---|---|
| REQ-WIZ-011 | Snapshot backend réel mappé sur neuf lignes distinctes du premier setup; E2E onboarding vérifie les neuf contrôles jusqu'à l'activation. |
| REQ-WIZ-012 | Mapping par opération au moindre privilège, sans `ADMINISTRATOR`; permissions, `CAN/CANNOT/UNKNOWN`, causes et remédiations visibles; E2E autorisé et bloqué. |
| REQ-UXN-003 | Édition du `name` d'un groupe logique via la route tenant-safe existante, sans changement d'UUID, de slug ni de ressources. |
| REQ-UXN-004 | Panneau explicitement typé abstraction DID/dashboard, séparé de la Guild et de l'arbre Discord. |
| REQ-UXN-005 | E2E premier clic de sélection puis second clic lent vers le rename inline. |
| REQ-UXN-006 | E2E `F2` vers le même éditeur et le même payload plan. |
| REQ-UXN-007 | Action `rename` de l'Action Registry exposée par le menu contextuel; E2E vers le même payload plan. |
| REQ-UXN-012 | Validation par points de code et E2E `📣 annonces-été` inchangé jusqu'au DSG envoyé pour validation. |
| REQ-UXN-013 | `emoji-picker-react` chargé à la demande uniquement dans l'éditeur de nom pertinent; parcours E2E représentatif. |
| REQ-UXN-014 | Suggestions optionnelles validées, aperçu et reset; test unitaire de non-mutation. |
| REQ-UXN-015 | Vide et plus de 100 points de code bloqués avant tout POST de plan; test unitaire et E2E. |

### Complément ciblé `ui/complete-redesign` — Phase 4, fondations Policy backend

Ce lot ne ferme pas la Phase 4 : resolver, conflits/héritage, preview/impact,
préflight/Plan, UI/Wizard et enforcement Discord restent explicitement hors
périmètre. Les statuts sont relevés uniquement lorsque les critères backend du
lot sont entièrement prouvés.

| ID | Avant | Preuve complémentaire | Après |
|---|---|---|---|
| REQ-POL-001 | ABSENT | Agrégat `Policy` explicite, sérialisable et référencé par UUID ; aucun resolver livré dans ce lot. | PARTIEL |
| REQ-POL-002 | ABSENT | `policy_id` stable ; une édition modifie la révision, jamais l'identité. | CONFORME |
| REQ-POL-003 | ABSENT | `PolicyTypeRegistry` fermé et versionné ; type/version inconnus refusés. | CONFORME |
| REQ-POL-004 | ABSENT | Révision CAS et snapshot immuable à chaque création, édition ou transition. | CONFORME |
| REQ-POL-005 | ABSENT | Machine d'état stricte `DRAFT → ACTIVE → DISABLED → RETIRED`, transitions invalides testées. | CONFORME |
| REQ-POL-006 | ABSENT | Nom, description et métadonnées humaines persistés ; aucune UI livrée. | PARTIEL |
| REQ-POL-007 | ABSENT | `guild_id` obligatoire, FK tenant, requêtes tenant-scopées et RLS forcée. | CONFORME |
| REQ-POL-008 | ABSENT | Scope explicite et compatibilité validée par contrat de type. | CONFORME |
| REQ-POL-009 | ABSENT | Enum générique des neuf scopes ; le contrat `ACCESS_CONTROL` n'autorise que ses sept scopes pertinents. | CONFORME |
| REQ-POL-010 | ABSENT | Conditions discriminées/fermées, bornées et revalidées avant activation. | CONFORME |
| REQ-POL-011 | ABSENT | Effets fermés/typés ; effet inconnu impossible à persister ou activer. | CONFORME |
| REQ-POL-012 | NON DÉMONTRÉ | Champs libres/code/SQL/callback refusés et absence d'`eval` testée ; resolver borné non livré. | PARTIEL |
| REQ-POL-027 | ABSENT | Création/édition en DRAFT uniquement, sans resolver, plan ni mutation Discord. | CONFORME |
| REQ-POL-029 | ABSENT | Route d'activation protégée par `policies.activate`, test API ciblé. | CONFORME |
| REQ-POL-030 | ABSENT | Désactivation protégée, transactionnelle, auditée et idempotente. | CONFORME |
| REQ-POL-031 | ABSENT | `policy_versions` append-only : auteur, date, snapshots, motif de changement et corrélation ; UPDATE/DELETE refusés au rôle applicatif. | CONFORME |
| REQ-POL-035 | ABSENT | Capabilities séparées read/create/update/activate/retire ; lecture seule limitée à read. | CONFORME |
| REQ-POL-036 | ABSENT | Validation applicative cache-first et test réel d'une cible du tenant B refusée depuis A. | CONFORME |
| REQ-POL-037 | ABSENT | RLS activée et forcée sur les deux tables ; test PostgreSQL A/B sans filtre applicatif. | CONFORME |
| REQ-POL-038 | ABSENT | Clés et empreintes d'idempotence ; retries create/activate/disable sans doublon de version. | CONFORME |
| REQ-POL-039 | ABSENT | Verrou optimiste par révision/état ; une seule de deux éditions concurrentes gagne. | CONFORME |
| REQ-POL-040 | PARTIEL | Invariant fail-closed conservé ; aucun resolver générique n'est encore livré. | PARTIEL |
| REQ-POL-050 | ABSENT | Routes, capabilities et isolation 404/non-divulgation au dépôt testées ; pas encore de test HTTP 403 complet ni d'enforcement. | PARTIEL |
| REQ-POL-052 | ABSENT | ADR comparative Pydantic/rule-engine/json-rules-engine/DSL maison ; registre Pydantic fermé retenu sans nouveau moteur d'expressions. | CONFORME |
| REQ-POL-053 | PARTIEL | ADR et modules distinguent explicitement le moteur générique des helpers message/translation existants. | CONFORME |

### Complément ciblé `ui/complete-redesign` — Phase 4, resolver Policy backend

Ce second lot conserve le registre fermé et ajoute un unique resolver de domaine,
une priorité explicite persistée et une route Explain déléguant au même service.
Il ne livre ni preview/impact, ni enforcement, ni Plan/APPLY, ni UI/Wizard.

| ID | Avant | Preuve complémentaire | Après |
|---|---|---|---|
| REQ-POL-001 | PARTIEL | `PolicyResolver` résout réellement les Policies actives via `PolicyService.resolve_access`; la route Explain délègue au même resolver. | CONFORME |
| REQ-POL-012 | PARTIEL | Resolver borné aux conditions/effets validés par le contrat `ACCESS_CONTROL` version 1, sans callback, expression, SQL ou exécution arbitraire. | CONFORME |
| REQ-POL-013 | PARTIEL | Tri canonique sans `created_at`; permutations de la liste d'entrée strictement égales. | CONFORME |
| REQ-POL-014 | ABSENT | Provenance et booléen d'héritage conservés pour chaque contribution. | CONFORME |
| REQ-POL-015 | ABSENT | Champ `priority` explicite, borné, persisté et versionné; priorité décroissante normative. | CONFORME |
| REQ-POL-016 | ABSENT | À priorité égale, spécificité ressource `GUILD→LOGICAL_GROUP→CATEGORY→CHANNEL`; hiérarchie sujet séparée, axes incomparables bloquants. | CONFORME |
| REQ-POL-017 | ABSENT | Effets `ALLOW/DENY` opposés détectés et retournés avec IDs, révisions, scopes et effets. | CONFORME |
| REQ-POL-018 | ABSENT | Conflits départagés uniquement par `HIGHER_PRIORITY` ou `MORE_SPECIFIC_SCOPE`, règle gagnante exposée. | CONFORME |
| REQ-POL-019 | ABSENT | Même rang ou scopes incomparables avec effets opposés = `BLOCKED`, sans préférence par UUID/date. | CONFORME |
| REQ-POL-020 | ABSENT | Contributions compatibles conservées individuellement, y compris les règles héritées et dépassées. | CONFORME |
| REQ-POL-024 | ABSENT | Réponse structurée : cible/état, Policies, conditions, contributions, sources, priorité, conflits, diagnostic et résultat. | CONFORME |
| REQ-POL-033 | ABSENT | Cible supprimée ou inaccessible explicitement identifiée et décision `BLOCKED`. | CONFORME |
| REQ-POL-034 | ABSENT | Freshness/coverage/source versions et recommandation refresh/reconcile exposées; cible stale = `UNKNOWN`. | CONFORME |
| REQ-POL-040 | PARTIEL | Rôle/target critique incomplet ou inconnu ne peut pas produire `CAN`; cas dépendants retournent `UNKNOWN/BLOCKED`. | CONFORME |
| REQ-POL-047 | ABSENT | Tests de vérité ciblés sur allow/deny/unknown, priorité, spécificité et ordre aléatoire. | CONFORME |
| REQ-POL-048 | ABSENT | Matrice paramétrée : priorité, spécificité, rang égal et axes incomparables. | CONFORME |
| REQ-POL-049 | ABSENT | Test complet `GUILD→LOGICAL_GROUP→CATEGORY→CHANNEL`, héritage et exception locale. | CONFORME |
| REQ-UXN-010 | NON DÉMONTRÉ | `ROLE_MATCH ANY` testé avec zéro, un et plusieurs rôles correspondants. | CONFORME |
| REQ-UXN-011 | NON DÉMONTRÉ | `ROLE_MATCH ALL` testé avec ensemble incomplet, complet et sur-ensemble. | CONFORME |

### Complément ciblé `ui/complete-redesign` — Phase 4, Policy vers Plan canonique

Ce troisième lot ajoute une preview non mutante, une analyse d'impact bornée,
la compilation vers le DSG/Plan existant et un garde Policy dans le preflight
canonique puis dans le recheck worker juste avant opération. Preview, preflight
et futur APPLY délèguent tous au même `PolicyResolver`.

| ID | Avant | Preuve complémentaire | Après |
|---|---|---|---|
| REQ-POL-021 | ABSENT | Enforcement serveur dans `PlanningService.recheck`; le worker le répète après fencing `APPLYING` et avant opération, en refusant les états critiques. | CONFORME |
| REQ-POL-022 | ABSENT | Le preflight canonique évalue les Policies pertinentes du Plan, fusionne leurs erreurs et conserve les explications du resolver. | CONFORME |
| REQ-POL-023 | ABSENT | Preview et garde pré-APPLY appellent tous deux `PolicyService.resolve_loaded`, donc l'unique `PolicyResolver`; aucune logique frontend/parallèle. | CONFORME |
| REQ-POL-026 | ABSENT | Avant/après explicite et compteurs ressources/rôles/membres/gains/pertes/conflits, marqués `EXACT`, `BOUNDED` ou `INCOMPLETE`. | CONFORME |
| REQ-POL-028 | ABSENT | Une `DRAFT` est simulée sans persistance ni effet actif, sur des cibles cache-first explicites. | CONFORME |
| REQ-POL-044 | ABSENT | L'activation exige capability sensible et Plan Policy tenant-local préflighté; l'état Policy actif reste distinct du Plan `SUCCEEDED` appliqué/vérifié. | CONFORME |
| REQ-POL-045 | ABSENT | Les effets résolus alimentent le DSG puis le Plan Engine existants; Plan, Policy ID et révision sont corrélés. | CONFORME |
| REQ-POL-046 | ABSENT | FK opération→Plan existante plus provenance immuable du Plan; test PostgreSQL de la remontée opération→Plan→Policy/révision. | CONFORME |
| REQ-POL-050 | PARTIEL | Contrats preview/plan, capabilities read/sensibles et isolation PostgreSQL A/B testés. La preuve HTTP 403 complète manque encore. | PARTIEL |
| REQ-POL-051 | ABSENT | Test PostgreSQL persistance→preview→preflight→Plan→activation/provenance et retry sans doublon; chaîne CI complète audit→désactivation non démontrée. | PARTIEL |

### Complément ciblé `ui/complete-redesign` — Phase 4, expérience Policies

Ce quatrième lot livre l'entrée de navigation et l'espace de travail Policies
en langage humain. Le catalogue DID est versionné côté application et n'est pas
dupliqué dans chaque tenant. Les objets persistés restent exclusivement des
Policies personnalisées `ACCESS_CONTROL v1`; leur preview, leur explication et
leur Plan utilisent les routes et moteurs canoniques existants.

Le contrat fermé accepte désormais une audience de rôles optionnelle par effet.
Cette extension additive du même registre et du même `PolicyResolver` permet de
représenter correctement une inclusion, une exclusion et une lecture ouverte
avec publication limitée sans créer de logique de résolution frontend.

| ID | Avant | Preuve complémentaire | Après |
|---|---|---|---|
| REQ-POL-006 | PARTIEL | Catalogue et liste affichent nom, explication, famille, cible, origine DID/personnalisée, lifecycle, révision, héritage et état d'analyse des conflits sans UUID en mode normal. | CONFORME |
| REQ-POL-025 | ABSENT | Depuis chaque ligne de preview, « Why this result? » appelle `POST /policy-resolution` et rend décision, source, héritage, exception et causes backend; E2E ciblé. | CONFORME |
| REQ-POL-032 | ABSENT | L'historique append-only propose « Create a new draft from this revision » via la route de création DRAFT; aucun rollback Discord n'est promis. | CONFORME |
| REQ-POL-041 | ABSENT | Le mode simple manipule cible, audiences multi-rôles et intentions Voir/Écrire/Rejoindre sans flags, bitfield, overwrite, UUID ni Snowflake demandé. | CONFORME |
| REQ-POL-042 | ABSENT | Le mode expert expose le même objet : ID, révision, priorité, scope, conditions, effets et résolution canonique, sans second calcul. | CONFORME |
| REQ-POL-043 | ABSENT | Aucun Wizard générique n'est livré par ce lot; le statut reste inchangé. | ABSENT |

Preuves ciblées : 57 tests backend Policy, 5 tests unitaires catalogue/UI, trois
parcours Playwright (nominal Policy→Plan, conflit multi-rôles + historique,
refus capability), typecheck, lint, i18n EN/FR/DE/ES, axe sur `#main`, Ruff et
contrat OpenAPI. Aucun APPLY, Discord live, test PostgreSQL ou campagne globale
n'a été exécuté pour ce lot.

## PARTIEL — ce qui est fait / ce qui manque

| ID | Implémenté | Manque |
|---|---|---|
| REQ-BOT-005 | API backend réelle par bot/salon (lecture/écriture), cache-derived, testée. | La visualisation dashboard demandée reste différée. |
| REQ-TEST-003 | Harness et rapports live A/B prévus/intégrés dans Stage10. | Pas d’agrégat live A/B valide du run courant: credentials sandbox externes indisponibles. |
| REQ-POL-050 | Contrats preview/plan, capabilities et tests PostgreSQL cross-tenant ciblés. | Test HTTP 403 complet encore absent. |
| REQ-POL-051 | Chaîne PostgreSQL persistance, preview, preflight, Plan, activation/provenance et retry testée. | Chaîne CI complète jusqu'à audit puis désactivation non démontrée. |
| REQ-UXN-009 | Moteur multi-rôles conforme | audit de toutes les UIs non réalisé. |
| REQ-OPS-003 | Persistance backend démontrée | UX de reprise après nouvelle session non démontrée. |
| REQ-OPS-004 | OutboxScreen/PlanDrawer existent | sémantique “centre d’opérations” et reprise session non totalement prouvées. |
| REQ-OPS-005 | PlanState/OperationState riches existent | équivalence UX complète non auditée. |
| REQ-OPS-006 | Persistance des résultats/erreurs plan présente | UX globale non démontrée. |
| REQ-OPS-007 | UNKNOWN_OUTCOME/reconciliation existent | UI complète non auditée. |
| REQ-OPS-008 | PlanState.DRAFT existe | usage universel hors plan non démontré. |
| REQ-OPS-009 | Pipeline plan existe | tous types de brouillons non unifiés. |
| REQ-OPS-014 | REQ-UX-006 et plan progress existent | persistance inter-session UI non complètement prouvée. |
| REQ-TPL-001 | Stage06 possède des templates portables | aucun catalogue UX préconstruit clairement démontré. |
| REQ-TPL-002 | Pipeline portable/preflight existe | UX d’adaptation préconstruite non prouvée. |
| REQ-TPL-003 | Portabilité rapporte mappings | écran dédié de template infrastructure non prouvé. |
| REQ-TPL-004 | COPY_AS_NEW sait créer | expérience de suggestion non démontrée. |
| REQ-TPL-007 | REQ-DUP-019 couvre portabilité de définitions et le moteur générique Policy existe. | Portabilité des Policies via template non démontrée. |
| REQ-TPL-009 | `template_id`, `schema_version` et `content_hash` donnent identité et empreinte reproductible. | Pas de révision métier publiée/sélectionnable (versions 1/2 immuables) démontrée. |
| REQ-TPL-010 | Portabilité converge sur planning | Wizard absent. |
| REQ-REUSE-001 | Architecture recommande dnd-kit, Radix/shadcn, i18next, discord.py, etc. | processus formel non démontré. |
| REQ-REUSE-005 | uv.lock/npm audit et Stage10 existent | règle universelle non prouvée. |
| REQ-REUSE-007 | discord.py et TranslationProvider sont abstraits | pratique à généraliser. |
| REQ-REUSE-009 | dnd-kit et primitives UI sont prévus/utilisés | emoji picker pas encore présent. |
| REQ-REUSE-010 | Redis/streams/locks et abstractions existent | audit exhaustif non réalisé. |
| REQ-REUSE-012 | TranslationProvider/Discord adapter sont de bons exemples | pas prouvé partout. |
| REQ-PERMX-010 | Moteurs canoniques permissions/Policy et raccord au Plan existent. | Wizard Policies absent. |
| REQ-QA-001 | Règle d’audit adoptée ici | traçabilité historique parfois plus large que preuve réinspectée. |
| REQ-QA-003 | Permissions/planning et pipeline Policy backend fortement testés. | UI/Wizard et chaîne CI Policy complète restent à démontrer. |
| REQ-QA-004 | Historique Stage10 affirme couverture | pas tout réexécuté. |
| REQ-QA-005 | Suite importante déclarée | audit indépendant exhaustif non reproduit. |
| REQ-QA-006 | Stage07-10 E2E existent | nouveaux Wizards/Policies non couverts. |
| REQ-QA-010 | artifacts/stage10-audit/skipped-tests.txt montre des scans conditionnels/skip. | Critère restant non prouvé: Aucun skip sérieux/critique inexpliqué dans la gate finale. |
| REQ-QA-011 | REQ-TEST-003 dans registre: implémenté | agrégat courant non fourni à ce rendu. |
| REQ-QA-012 | Registre contient preuves, | leur réexécution indépendante n’a pas été exhaustive ici. |

## Matrice exhaustive de statut

### CONFORME

- `REQ-INST-001`, `REQ-INST-002`, `REQ-INST-003`, `REQ-INST-004`, `REQ-INST-005`, `REQ-INST-006`, `REQ-INST-007`, `REQ-TEN-001`, `REQ-TEN-002`, `REQ-TEN-003`, `REQ-TEN-004`, `REQ-TEN-005`, `REQ-TEN-006`, `REQ-TEN-007`, `REQ-TEN-008`, `REQ-TEN-009`, `REQ-TEN-010`, `REQ-TEN-011`, `REQ-TEN-012`, `REQ-TEN-013`
- `REQ-TEN-014`, `REQ-STR-001`, `REQ-STR-002`, `REQ-STR-003`, `REQ-STR-004`, `REQ-STR-005`, `REQ-STR-006`, `REQ-STR-007`, `REQ-STR-008`, `REQ-STR-009`, `REQ-STR-010`, `REQ-STR-011`, `REQ-STR-012`, `REQ-STR-013`, `REQ-PERM-001`, `REQ-PERM-002`, `REQ-PERM-003`, `REQ-PERM-004`, `REQ-PERM-005`, `REQ-PERM-006`
- `REQ-PERM-007`, `REQ-PERM-008`, `REQ-PERM-009`, `REQ-PLAN-001`, `REQ-PLAN-002`, `REQ-PLAN-003`, `REQ-PLAN-004`, `REQ-PLAN-005`, `REQ-PLAN-006`, `REQ-PLAN-007`, `REQ-PLAN-008`, `REQ-PLAN-009`, `REQ-PLAN-010`, `REQ-PLAN-011`, `REQ-PLAN-012`, `REQ-PLAN-013`, `REQ-PLAN-014`, `REQ-PLAN-015`, `REQ-PLAN-016`, `REQ-DUP-001`
- `REQ-DUP-002`, `REQ-DUP-003`, `REQ-DUP-004`, `REQ-DUP-005`, `REQ-DUP-006`, `REQ-DUP-007`, `REQ-DUP-008`, `REQ-DUP-009`, `REQ-DUP-010`, `REQ-DUP-011`, `REQ-DUP-012`, `REQ-DUP-013`, `REQ-DUP-014`, `REQ-DUP-015`, `REQ-DUP-016`, `REQ-DUP-017`, `REQ-DUP-018`, `REQ-DUP-019`, `REQ-BOT-001`, `REQ-BOT-002`
- `REQ-BOT-003`, `REQ-BOT-004`, `REQ-BOT-006`, `REQ-BOT-007`, `REQ-AUTH-001`, `REQ-AUTH-002`, `REQ-AUTH-003`, `REQ-AUTH-004`, `REQ-AUTH-005`, `REQ-AUTH-006`, `REQ-AUTH-007`, `REQ-AUTH-008`, `REQ-AUTH-009`, `REQ-AUTH-010`, `REQ-AUTH-011`, `REQ-AUTH-012`, `REQ-AUTH-013`, `REQ-AUTH-014`, `REQ-GW-001`, `REQ-GW-002`
- `REQ-GW-003`, `REQ-GW-004`, `REQ-GW-005`, `REQ-GW-006`, `REQ-GW-007`, `REQ-GW-008`, `REQ-AUD-001`, `REQ-AUD-002`, `REQ-AUD-003`, `REQ-AUD-004`, `REQ-AUD-005`, `REQ-AUD-006`, `REQ-DATA-001`, `REQ-DATA-002`, `REQ-UX-001`, `REQ-UX-002`, `REQ-UX-003`, `REQ-UX-004`, `REQ-UX-005`, `REQ-UX-006`
- `REQ-UX-007`, `REQ-UX-CTX-001`, `REQ-UX-CTX-002`, `REQ-UX-CTX-003`, `REQ-UX-CTX-004`, `REQ-UX-CTX-005`, `REQ-I18N-001`, `REQ-I18N-002`, `REQ-I18N-003`, `REQ-I18N-004`, `REQ-I18N-005`, `REQ-I18N-006`, `REQ-I18N-007`, `REQ-I18N-008`, `REQ-I18N-009`, `REQ-I18N-010`, `REQ-I18N-011`, `REQ-I18N-012`, `REQ-I18N-013`, `REQ-I18N-014`
- `REQ-I18N-015`, `REQ-I18N-016`, `REQ-I18N-017`, `REQ-I18N-018`, `REQ-I18N-019`, `REQ-I18N-020`, `REQ-I18N-021`, `REQ-I18N-022`, `REQ-I18N-023`, `REQ-I18N-024`, `REQ-I18N-025`, `REQ-I18N-026`, `REQ-I18N-026A`, `REQ-I18N-027`, `REQ-I18N-028`, `REQ-I18N-029`, `REQ-I18N-030`, `REQ-I18N-031`, `REQ-I18N-032`, `REQ-I18N-033`
- `REQ-I18N-034`, `REQ-I18N-035`, `REQ-I18N-036`, `REQ-I18N-037`, `REQ-I18N-038`, `REQ-I18N-039`, `REQ-I18N-040`, `REQ-I18N-041`, `REQ-I18N-042`, `REQ-CACHE-001`, `REQ-CACHE-002`, `REQ-CACHE-003`, `REQ-CACHE-004`, `REQ-CACHE-005`, `REQ-CACHE-006`, `REQ-CACHE-007`, `REQ-CACHE-008`, `REQ-CACHE-009`, `REQ-CACHE-010`, `REQ-CACHE-011`
- `REQ-CACHE-012`, `REQ-CACHE-013`, `REQ-RATE-001`, `REQ-RATE-002`, `REQ-RATE-003`, `REQ-RATE-004`, `REQ-RATE-005`, `REQ-RATE-006`, `REQ-UI18N-001`, `REQ-UI18N-002`, `REQ-UI18N-003`, `REQ-UI18N-004`, `REQ-UI18N-005`, `REQ-UI18N-006`, `REQ-UI18N-007`, `REQ-UI18N-008`, `REQ-UI18N-009`, `REQ-UI18N-010`, `REQ-UI18N-011`, `REQ-UI18N-012`
- `REQ-UI18N-013`, `REQ-UI18N-014`, `REQ-UI18N-015`, `REQ-UI18N-016`, `REQ-UI18N-017`, `REQ-UI18N-018`, `REQ-UI18N-019`, `REQ-UI18N-020`, `REQ-UI18N-021`, `REQ-MSG-001`, `REQ-MSG-002`, `REQ-MSG-003`, `REQ-MSG-004`, `REQ-MSG-005`, `REQ-MSG-006`, `REQ-MSG-007`, `REQ-MSG-008`, `REQ-MSG-009`, `REQ-MSG-010`, `REQ-MSG-011`
- `REQ-MSG-012`, `REQ-MSG-013`, `REQ-MSG-014`, `REQ-MSG-015`, `REQ-MSG-016`, `REQ-MSG-017`, `REQ-MSG-018`, `REQ-MSG-019`, `REQ-MSG-020`, `REQ-MSG-021`, `REQ-MSG-022`, `REQ-MSG-023`, `REQ-MSG-024`, `REQ-MSG-025`, `REQ-MSG-026`, `REQ-MSG-027`, `REQ-MSG-028`, `REQ-MSG-029`, `REQ-MSG-030`, `REQ-MSG-031`
- `REQ-TEST-001`, `REQ-TEST-002`, `REQ-TEST-004`, `REQ-TEST-005`, `REQ-UXN-001`, `REQ-UXN-002`, `REQ-UXN-008`, `REQ-UXN-018`, `REQ-OPS-001`, `REQ-OPS-002`, `REQ-OPS-013`, `REQ-TPL-005`, `REQ-TPL-006`, `REQ-TPL-008`, `REQ-REUSE-008`, `REQ-PERMX-001`, `REQ-PERMX-002`, `REQ-PERMX-003`, `REQ-PERMX-004`, `REQ-PERMX-005`
- `REQ-PERMX-006`, `REQ-PERMX-007`, `REQ-PERMX-008`, `REQ-PERMX-009`, `REQ-QA-002`
- `REQ-POL-002`, `REQ-POL-003`, `REQ-POL-004`, `REQ-POL-005`, `REQ-POL-007`, `REQ-POL-008`, `REQ-POL-009`, `REQ-POL-010`, `REQ-POL-011`, `REQ-POL-027`, `REQ-POL-029`, `REQ-POL-030`, `REQ-POL-031`, `REQ-POL-035`, `REQ-POL-036`, `REQ-POL-037`, `REQ-POL-038`, `REQ-POL-039`, `REQ-POL-052`, `REQ-POL-053`
- `REQ-POL-001`, `REQ-POL-012`, `REQ-POL-013`, `REQ-POL-014`, `REQ-POL-015`, `REQ-POL-016`, `REQ-POL-017`, `REQ-POL-018`, `REQ-POL-019`, `REQ-POL-020`, `REQ-POL-024`, `REQ-POL-033`, `REQ-POL-034`, `REQ-POL-040`, `REQ-POL-047`, `REQ-POL-048`, `REQ-POL-049`, `REQ-UXN-010`, `REQ-UXN-011`
- `REQ-POL-021`, `REQ-POL-022`, `REQ-POL-023`, `REQ-POL-025`, `REQ-POL-026`, `REQ-POL-028`, `REQ-POL-032`, `REQ-POL-041`, `REQ-POL-042`, `REQ-POL-044`, `REQ-POL-045`, `REQ-POL-046`
- `REQ-POL-006`
- `REQ-WIZ-011`, `REQ-WIZ-012`, `REQ-UXN-003`, `REQ-UXN-004`, `REQ-UXN-005`, `REQ-UXN-006`, `REQ-UXN-007`, `REQ-UXN-012`, `REQ-UXN-013`, `REQ-UXN-014`, `REQ-UXN-015`

### PARTIEL

- `REQ-BOT-005`, `REQ-TEST-003`, `REQ-POL-050`, `REQ-POL-051`, `REQ-UXN-009`, `REQ-OPS-003`, `REQ-OPS-004`, `REQ-OPS-005`, `REQ-OPS-006`, `REQ-OPS-007`, `REQ-OPS-008`, `REQ-OPS-009`, `REQ-OPS-014`, `REQ-TPL-001`, `REQ-TPL-002`
- `REQ-TPL-003`, `REQ-TPL-004`, `REQ-TPL-007`, `REQ-TPL-009`, `REQ-TPL-010`, `REQ-REUSE-001`, `REQ-REUSE-005`, `REQ-REUSE-007`, `REQ-REUSE-009`, `REQ-REUSE-010`, `REQ-REUSE-012`, `REQ-PERMX-010`, `REQ-QA-001`, `REQ-QA-003`, `REQ-QA-004`, `REQ-QA-005`, `REQ-QA-006`, `REQ-QA-010`, `REQ-QA-011`, `REQ-QA-012`

### ABSENT

- `REQ-POL-043`
- `REQ-WIZ-001`, `REQ-WIZ-002`, `REQ-WIZ-003`, `REQ-WIZ-004`, `REQ-WIZ-005`, `REQ-WIZ-006`, `REQ-WIZ-007`, `REQ-WIZ-008`, `REQ-WIZ-009`, `REQ-WIZ-010`, `REQ-WIZ-013`
- `REQ-WIZ-014`, `REQ-QA-007`, `REQ-QA-008`, `REQ-QA-009`

### NON DÉMONTRÉ

- `REQ-UXN-016`, `REQ-UXN-017`, `REQ-OPS-010`, `REQ-OPS-011`, `REQ-OPS-012`, `REQ-REUSE-002`, `REQ-REUSE-003`, `REQ-REUSE-004`, `REQ-REUSE-006`, `REQ-REUSE-011`

## Preuves principales réinspectées

- Tenancy/RLS : `tenancy/context.py`, `infrastructure/database.py`, migrations/repositories RLS, tests A/B/IDOR.
- Permissions : moteur de permissions, tests unit/property; rôles cumulatifs, overwrites, owner/admin, View As, simple/expert, simulation.
- Planning : service planning, modèles, persistance/DAG/preflight/impact/UNKNOWN_OUTCOME, failure-injection.
- Portabilité/templates : service/repository/API Stage06, tests PostgreSQL/E2E; template privé RLS démontré.
- Stage10 : large couverture backend/Playwright; `REQ-TEST-003` reste partiel car l’agrégat live A/B du run courant manque.
- Policies/Wizards : fondations, resolver, preview/impact, compilation DSG/Plan, provenance, enforcement et UI Policies sont démontrés ; le Wizard reste ouvert. Les policies message/traduction demeurent spécialisées et séparées.

## Priorités

1. **Suite du Policy Engine** : Wizard et preuves HTTP/CI restantes dans la Phase UI 4 existante.
2. **Wizards** : socle en Phase UI 4, réutilisé ensuite.
3. **Operations Center inter-session + drafts** : Phase UI 5.
4. **Templates adaptatifs** : Phase UI 6.
5. **UX/REUSE** : Phase UI 8.
6. **REQ-TEST-003 + QA + clôture** : Phase UI 9.

Aucune phase UI supplémentaire n'est créée à partir de cet audit.

## Maintenance

Une exigence `PARTIEL` ne passe à `CONFORME` qu’après satisfaction de **tous** ses critères avec preuve adaptée au risque. Les tests sont ciblés pendant les phases ; la campagne complète est réservée à la Phase 9.
