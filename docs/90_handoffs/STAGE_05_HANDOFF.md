# Handoff STAGE 05 — Desired State, Plan et Mutation Engine

| Champ | Valeur |
|---|---|
| Date | `2026-08-24` |
| Base main | `f64c8253e6b7ec648d7161531344a2999b78ffe7` |
| Branche | `stage/05-plan-engine` |
| PR | [Draft PR #5](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/5) vers `main`, non mergée |
| Statut | `COMPLETE_PR_OPEN` |
| Migration | `0008_stage_05` ; parent `0007_stage_04` ; une seule tête |

## Contrats Discord revalidés

Documentation officielle consultée le 2026-08-24 : [Channel Resource](https://docs.discord.com/developers/resources/channel), [Guild Resource](https://docs.discord.com/developers/resources/guild), [Permissions](https://docs.discord.com/developers/topics/permissions), [Rate Limits](https://docs.discord.com/developers/topics/rate-limits), [Gateway Events](https://docs.discord.com/developers/events/gateway-events) et [HTTP Reference](https://docs.discord.com/developers/reference).

Les points appliqués sont : audit reason UTF-8 de 1 à 512 caractères ; rôles managed et hiérarchie ; suppression de catégorie sans suppression automatique des enfants ; endpoints create/update/delete rôles, salons et overwrites ; bulk positions ; au plus un changement de `parent_id` par requête bulk ; `Retry-After`/scope des 429 ; événements structurels Gateway. `discord.py 2.7.1` est le transport épinglé, jamais la source normative.

## DSG, canonicalisation et diff

- Schéma immuable `did-dsg-v&#49;` : Guild, category, channel, role et overwrite ; présence `PRESENT/ABSENT`, logical key, ID Discord optionnel, symbole et relations typées.
- Les objets JSON sont gelés récursivement. La canonicalisation encode du JSON UTF-8, clés triées, séparateurs compacts, sans valeurs non JSON ; hash SHA-256 hexadécimal.
- Le hash plan lie schéma, compiler `did-plan-compiler-v&#49;`, capability registry, version/hash du snapshot de base, hash DSG et opérations.
- Le diff est déterministe sous permutation, produit le no-op vide, conserve `before` et `desired`, et refuse les formes non supportées.

## Plan persistant et state machines

Tables RLS : `plan_snapshots`, `plans`, `plan_operations`, `plan_operation_dependencies`, `plan_symbol_bindings`, `operation_attempts`, `plan_confirmations`, `plan_progress_events`, `plan_expected_mutations`. Toutes les relations tenant critiques utilisent `guild_id` et des FK composites. Les triggers rendent snapshot/graph/opérations/dépendances immuables, empêchent le rebind d'un symbole et refusent les cycles.

Plan : `DRAFT → VALIDATED → CONFIRMED → APPLYING → SUCCEEDED|FAILED|PARTIALLY_APPLIED|VERIFICATION_FAILED|INTERVENTION_REQUIRED`; `STALE`, `CANCEL_REQUESTED` et `CANCELLED` ont des transitions explicites. Opération : `PENDING → IN_FLIGHT → SUCCEEDED|FAILED|UNKNOWN_OUTCOME`, puis recovery vers `PENDING|SUCCEEDED|INTERVENTION_REQUIRED`. Attempt : `PREPARED → IN_FLIGHT → SUCCEEDED|FAILED|UNKNOWN`. `PREPARED` et `IN_FLIGHT` sont deux commits distincts.

Le DAG est persisté par arêtes, topologiquement validé et planifié seulement lorsque tous les prédécesseurs sont `SUCCEEDED`. Les CREATE produisent un symbole ; les consommateurs attendent un binding `BOUND`. Le binding ID/fingerprint et le résultat CREATE sont committés atomiquement.

## Catalogue et compilation

Catalogue fermé : `CREATE_ROLE`, `UPDATE_ROLE`, `DELETE_ROLE`, `REORDER_ROLES`, `CREATE_CHANNEL`, `UPDATE_CHANNEL`, `MOVE_OR_REORDER_CHANNELS`, `DELETE_CHANNEL`, `UPSERT_OVERWRITE`, `DELETE_OVERWRITE`. Les changements de parent sont séparés afin qu'une requête bulk n'en porte jamais plus d'un. La suppression d'une catégorie exige des effets enfants explicites et les dépendances adéquates.

## Preflight, risque et confirmation

Le preflight réutilise le Capability Checker STAGE 04 et vérifie : tenant, installation active, autorisation acteur fraîche au point API, identité/capacités bot, hiérarchie/managed, version de structure, version du registry, fraîcheur et couverture cache, symboles, topologie, limites salons/rôles/enfants/overwrites et impact destructif inconnu. La validation marque une base modifiée `STALE`. Le worker refait le preflight après le fencing `APPLYING` et avant de sélectionner une opération ; un refus terminal ne produit aucun REST.

Le risque `LOW/MEDIUM/HIGH/CRITICAL` dépend du type, caractère destructif, blast radius et connaissance de l'impact. Le résumé d'impact est renvoyé avec le plan. HIGH/CRITICAL exige la phrase renforcée liée au hash complet. Une confirmation est idempotente, actor-scopée, expirante (10 minutes par défaut), non réutilisable sur un plan modifié et recontrôlée au début de l'apply.

## Worker, verrou et Discord adapter

- L'API ne fait aucune mutation Discord : elle persiste et enqueue atomiquement `APPLY_PLAN`.
- Un index unique n'autorise qu'un plan `APPLYING` par Guild. Le lock Redis `did:guild:{guild}:mutation:lock:v&#49;` utilise token propriétaire, TTL, renouvellement et compare-delete.
- Le job PostgreSQL fournit owner/token/generation. Tous les commits d'attempt/résultat vérifient ce fence ; un ancien worker est refusé après takeover.
- L'I/O Discord se déroule hors transaction DB et passe par le Governor existant. Le mutable adapter est isolé dans `did.infrastructure.discord.mutations`.
- Le motif `X-Audit-Log-Reason` est stable, borné, composé d'identifiants techniques et sans texte utilisateur ; seule son empreinte est persistée. Request/result payloads ont des fingerprints SHA-256.
- Classification : 401 halt, 403 connu, 404 interprété par opération/recovery et jamais universellement comme suppression, 429 retryable avec `Retry-After`, timeout/connexion/5xx après émission comme outcome inconnu. Un 429 `shared` est mesuré mais exclu du budget invalid-request.

## UNKNOWN_OUTCOME et compensation

Un lease repris transforme tout `IN_FLIGHT` en `UNKNOWN_OUTCOME` avant nouvelle sélection. CREATE liste et compare les propriétés/fingerprint : un candidat unique prouve la création, zéro candidat prouve l'absence et autorise une nouvelle tentative explicite, plusieurs candidats donnent `INTERVENTION_REQUIRED`. UPDATE compare état courant, état avant et état désiré. DELETE exige une absence observable. Move/reorder/overwrite utilisent une comparaison ciblée. Aucun CREATE ambigu n'est retry.

Compensation : `REVERSIBLE` lorsque l'inverse est prouvable ; `RECREATABLE_NOT_RESTORABLE` quand une recréation perd ID/historique/liens ; `NON_COMPENSABLE` sinon. Le moteur ne présente jamais une suppression Discord comme rollback parfait et n'annonce pas de rollback automatique inexistant.

## Résultat, cache, Gateway, vérification et annulation

Le succès committe résultat/fingerprint, symbole, audit, progression, expected mutation et write-through structure cache dans une transaction. Un événement Gateway au fingerprint attendu est marqué `OBSERVED`. Une correspondance unique avec une opération réellement `IN_FLIGHT` peut être attribuée conservativement ; aucune corrélation native Discord de plan n'est inventée. Un drift externe pertinent marque DRAFT/VALIDATED/CONFIRMED `STALE` et un apply actif en intervention/cancel sûr.

La vérification finale utilise des GET/list ciblés et distingue `SUCCEEDED` de `VERIFICATION_FAILED`. Les erreurs partielles donnent `FAILED` ou `PARTIALLY_APPLIED`. Une annulation en apply devient `CANCEL_REQUESTED` et s'arrête seulement entre opérations ; les effets déjà prouvés restent visibles.

Les progress events ont un `sequence` monotone par plan, les états, compteurs, message key, erreur et correlation ID. Ils sont durables, rejouables via API et publiés par outbox après commit. Redis/PubSub n'est jamais la vérité durable.

## API et sécurité

Routes : création, lecture plan, lecture opérations, replay progression, validate, confirm, apply et cancel sous l'API versionnée `/api/v&#49;/guilds/{guild_id}/plans`. Mutations : session+CSRF+RBAC frais ; lectures : session+RBAC. `Idempotency-Key` est obligatoire et borné. Les payloads Pydantic interdisent les champs inconnus, bornent graph/nœuds/propriétés et sérialisent Snowflakes/bitfields en chaînes décimales.

La preuve architecture scanne récursivement : `did.planning` n'importe ni FastAPI, SQLAlchemy, Redis, discord.py ni infrastructure ; aucun router n'importe le mutable adapter. RLS `ENABLE/FORCE`, authorization-before-repository et tests Guild A/B couvrent l'isolation. Logs/métriques ont des labels bornés sans Guild/plan/resource IDs ni secrets.

## Failure injection A–I

| Point | Résultat prouvé |
|---|---|
| A avant commit PREPARED | zéro appel Discord ; reprise normale |
| B PREPARED committé avant IN_FLIGHT | attempt abandonné marqué FAILED ; reprise sûre, zéro appel préalable |
| C IN_FLIGHT avant réseau | lease recovery → UNKNOWN ; absence prouvée avant un unique CREATE |
| D timeout après émission | `UNKNOWN_OUTCOME` durable avant reconciliation |
| E succès Discord avant commit résultat | UNKNOWN au takeover ; rôle et salon retrouvés ; CREATE total = 1 |
| F résultat+symbole committés avant ack | reprise finalise sans répéter l'effet |
| G pendant vérification | vérification reprise ; aucun nouvel effet Discord |
| H Redis indisponible après commit | résultat PostgreSQL conservé ; outbox retryable |
| I crash avec lock/lease | TTL libère le lock ; ancien owner/token/generation est fenced |

## Validation et performance

| Validation | Résultat |
|---|---|
| `python scripts/validate_stage.py 05 --include-discord-live` | PASS : 172 unit, 61 integration, 13 failure-injection, 4 frontend, migrations, lint/type/build/secrets/docs et garde live |
| `python scripts/validate_stage.py 05 --profile failure-injection` | PASS : 13 scénarios A–I |
| charge DSG 500 nœuds | PASS, déterministe, sous la borne 3 s |
| docs | PASS : 246/246 REQ, 35 ADR |
| secret scan et diff checks | PASS |

Preuve locale propre sur le commit de code validé `a8e8bcc7b3b648eab23186c245415e2c9048a12c` : `artifacts/test-evidence/stage-05/20260824T101948193363Z-a8e8bcc7b3b6-local-docker/`. La matrice failure-injection dédiée est aussi conservée sous `artifacts/test-evidence/stage-05/20260824T101546797719Z-c8b66d3569c2-local-docker/`. Les preuves du HEAD final de la PR sont les artifacts GitHub du workflow.

## Live sandbox et cleanup

Statut : `PASS_WITH_APPROVED_LIMITATION`. Un snapshot live et un plan persisté ont été produits, puis le preflight a refusé les mutations : le bot sandbox n'a ni `MANAGE_CHANNELS` ni `MANAGE_ROLES`. Mutations exécutées : 0. Crash window live : `SKIPPED_NOT_VERIFIED` pour la même raison. Cleanup : `NOT_REQUIRED_ZERO_MUTATIONS`; aucune fixture STAGE 05 n'a été créée. Preuve expurgée : `STAGE_05_LIVE_EVIDENCE.json`.

Les limites héritées ne sont pas réécrites : fixtures threads/category/hierarchy STAGE 04, profils humains non-owner/non-admin STAGE 02, modification/reconnect Gateway et Channel Obfuscation restent à leur statut antérieur.

## Traçabilité et limites

`REQ-PLAN-001..016`, `REQ-GW-006`, `REQ-AUD-001..003`, `REQ-STR-004/005`, `REQ-RATE-005` et `REQ-CACHE-004` sont `IMPLEMENTED` avec preuves STAGE 05. `REQ-UX-006/007` restent `PLANNED` : le backend durable/rejouable est livré, mais l'expérience UI live et le contrat de succès visible appartiennent aux étapes UI ultérieures. Le live mutatif reste non vérifié faute de permissions sandbox ; ce n'est pas masqué par les tests fake.

## Contrat STAGE 06

STAGE 06 est interdite avant revue externe et merge normal de la Draft PR STAGE 05. Après merge seulement, elle pourra consommer le DSG, le compiler, le DAG, les symbols et l'apply worker comme API stable. Elle ne doit ni contourner plan/preflight/confirmation, ni muter Discord depuis API/frontend, ni importer un ID source comme ID destination, ni affaiblir RLS/Governor/UNKNOWN recovery. Aucun code clone, artifact portable, clipboard, library, `COPY_AS_NEW`, `MERGE`, `RECONCILE` ou `MAXIMUM_COMPATIBLE` n'a été commencé ici.
