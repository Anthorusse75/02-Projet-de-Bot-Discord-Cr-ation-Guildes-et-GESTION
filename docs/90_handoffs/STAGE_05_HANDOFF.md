# Handoff STAGE 05 - Desired State, Plan et Mutation Engine

| Champ | Valeur |
|---|---|
| Date | `2026-08-24` |
| Base main | `f64c8253e6b7ec648d7161531344a2999b78ffe7` |
| Branche | `stage/05-plan-engine` |
| PR | Draft PR #5 vers `main`, non mergee |
| Statut | `CORRECTIVE_REVIEW_COMPLETE_PR_OPEN` |
| Migration | `0009_stage_05` apres `0008_stage_05` ; une seule tete Alembic |

## Contrats Discord revalides

La documentation officielle Discord a ete relue le 2026-08-24 : Channel Resource,
Guild Resource, Permissions, Rate Limits, Gateway Events et HTTP Reference. Les
contraintes retenues sont notamment : audit reason borne a 512 octets UTF-8, roles
managed et hierarchie, suppression d'une categorie sans suppression automatique de
ses enfants, endpoints bulk de positions, au plus un changement de `parent_id` par
requete bulk et omission HTTP d'un salon qui ne constitue jamais une preuve de
suppression. `discord.py 2.7.1` est le transport epingle, pas la source normative.

## DSG, hash et immutabilite

- Le DSG `did-dsg-v&#49;` est immutable et canonique. La correction de canonicalisation
  traite les objets/tableaux geles avant les dataclasses generiques : le JSON persiste
  des objets reels, jamais une enveloppe interne `items` accidentelle.
- Le `plan_hash` lie le DSG/hash, le compiler et le registre de capacites, le snapshot
  complet et sa version/hash, les operations et leurs preconditions, les dependances
  et les symboles.
- Avant `DRAFT -> VALIDATED`, un bundle relu dans une transaction recalcule tous ces
  hashes depuis les lignes persistantes. Un tamper SQL d'un DRAFT est refuse.
- Apres validation, les triggers PostgreSQL refusent `INSERT`, `UPDATE` et `DELETE`
  des operations, symboles et dependances. Un snapshot reference est append-only,
  pour `did_app` comme pour l'administrateur de test.
- Les operation UUID restent deterministes, mais incluent le `plan_id`. La cle
  primaire finale est `(guild_id, plan_id, id)`.

## Autorisation, confirmation et idempotence

- Les commandes sensibles STAGE 05 passent `sensitive=True` au moteur STAGE 02.
  Validate transmet explicitement la preuve `actor_authorization_fresh`; confirm et
  apply sont egalement sensibles. Cancel est sensible afin de ne pas contourner une
  revocation pendant un apply.
- Le worker lit le `requested_by` durable et, avant tout side effect, appelle le meme
  `AuthorizationService` avec `PLANS_APPLY`, scope `GUILD`, installation `ACTIVE` et
  targeted `Get Guild Member`. Il n'utilise jamais `List Guild Members` et ne depend
  pas d'une session OAuth utilisateur. Perte de membership ou de capability termine
  le plan sans appel mutable.
- `begin_apply` exige une confirmation valide pour l'acteur exact du job. La
  confirmation de B ne peut jamais remplacer celle de A.
- La cle plan est unique par `(guild_id, actor_user_id, idempotency_key)`. Create et
  confirm exposent `Idempotency-Key`; apply reutilise atomiquement le job actif par
  logical key et cancel reutilise l'etat/version. Les routes apply/cancel ne pretendent
  donc pas accepter un header absent de leur contrat public.

## Preconditions juste-a-temps et preflight

Chaque operation persiste `did-operation-precondition-v&#49;` : mode, type et ID de
ressource, identite, before state/fingerprint et couverture. Les bulk portent leur
liste d'etats avant; les overwrites portent channel, target, type, allow/deny. Apres
`PREPARED` et immediatement avant `IN_FLIGHT`/REST, l'adapter relit la cible via le
Governor. `CHANGED` ou `UNKNOWN` produit un audit/progress explicite et
`INTERVENTION_REQUIRED`, sans appel mutable.

Le preflight global reutilise le Capability Checker et le Permission Evaluator STAGE
04. Il controle tenant, installation, acteur, capacites bot, hierarchy/managed,
structure version/hash, couverture/fraicheur, symboles, topologie et limites. Le
worker refait ce preflight apres l'autorisation acteur reelle.

## Impact Engine

Le resume d'impact simule les permissions effectives avant/apres avec le
`PermissionEvaluator` STAGE 04 et les membres deja en cache. Il calcule sujets
affectes, bits ajoutes/retires, pertes `VIEW_CHANNEL` et grants `ADMINISTRATOR`.
Categories et enfants augmentent le blast radius. Une couverture membres incomplete
reste `incomplete_or_unknown=true`; elle n'est jamais transformee en zero. Elle ajoute
30 points de risque et tout plan `HIGH`/`CRITICAL` incertain exige une confirmation
renforcee liee au hash avant que le preflight ne l'autorise avec un warning explicite.

## Worker, progression et fencing

- Toutes les mutations passent par plan, job durable, lock Guild, Governor distribue
  et mutable adapter; aucun router ou frontend ne mute Discord.
- Les attempts `PREPARED`, `IN_FLIGHT`, `SUCCEEDED|FAILED|UNKNOWN` et leurs resultats
  sont fences par owner, token et generation.
- La perte de lease ne marque UNKNOWN que l'attempt portant exactement l'ancien
  fence. Un callback tardif A ne peut pas modifier l'attempt courant B.
- `plans.progress_sequence` est incremente par un `UPDATE ... RETURNING` atomique.
  Les progress events concurrents sont uniques, continus et sans perte.
- Le modele reste effectively-once : un crash peut laisser un outcome inconnu; aucune
  garantie exactly-once n'est annoncee.

## Recovery operation-specific

Les preuves ne sont pas interchangeables :

- `CREATE_CHANNEL`: un candidat unique visible ou une reponse CREATE deja persistee
  peut prouver la creation. L'absence dans `Get Guild Channels` ne prouve jamais
  l'absence; sans event durable ou ID permettant une lecture ciblee, le resultat est
  `AMBIGUOUS` puis intervention, sans second CREATE.
- `DELETE_CHANNEL`: une reponse DELETE persistee, un `CHANNEL_DELETE` durable correle
  ou une autre preuve ciblee forte peut prouver l'effet. Une omission, `ACCESS_LOST`
  ou obfuscation ne donne jamais `PROVED_APPLIED`.
- `CREATE_ROLE`/`DELETE_ROLE`: la reponse complete de `Get Guild Roles` est un signal
  exhaustif distinct. Un candidat unique prouve un create; zero candidat permet de
  prouver l'absence create ou l'application delete selon l'operation.
- UPDATE, bulk et overwrite comparent strictement l'etat avant/desire. Toute ambiguite
  devient intervention; aucun retry aveugle n'est effectue.

## Gateway et plans concernes

- Reorder roles/channels enregistre une expected mutation par item et ressource.
- Upsert/delete overwrite enregistre le channel, la target, le type, la presence,
  allow/deny et l'ensemble complet trie des overwrites. L'expected mutation reste
  observable apres le commit `SUCCEEDED` de l'operation.
- Les matchers sont operation-specific et exigent tous les champs discriminants. Un
  autre update du meme channel n'est pas classe own par simple egalite d'ID.
- `plan_resource_dependencies` indexe les ressources lues ou mutees. Un drift externe
  ne stale/interrompt que les plans concernes; un plan de role independant reste
  valide lors d'un drift de channel.

## API, audit et securite

Les routes versionnees create/read/operations/progress/validate/confirm/apply/cancel
restent session+CSRF+RBAC, RLS et authorization-before-repository. Le motif
`X-Audit-Log-Reason` lie plan, operation et correlation sans texte utilisateur; seule
son empreinte est persistee. Les logs/metriques gardent des labels bornes sans secret
ni identifiant tenant.

## Preuves automatisees correctives

- 183 tests unitaires passent, dont authorization worker membership/capability,
  recovery channel/role, matchers Gateway et impacts permissions.
- 24 tests d'integration STAGE 05 passent sur PostgreSQL/Redis reels, dont actor
  binding, idempotence cross-actor, deux plans de meme DSG, immutabilite SQL,
  precondition entre deux operations, expected mutations bulk/overwrite, plan
  resource dependency, progression concurrente et late old-worker fencing.
- Ruff, format et mypy passent. Les validateurs 01, 02, 03, 03-load, 04, 05,
  05-failure-injection et 05-load sont PASS. Le profil complet compte 183 unit,
  72 integration, 24 scenarios STAGE 05, 4 frontend et un DSG 500 noeuds.
- Preuve Stage 05 hors live :
  `artifacts/test-evidence/stage-05/20260824T140603689891Z-f162a708f0e1-local-docker/`.
  Failure-injection : `20260824T140812036729Z-f162a708f0e1-local-docker/`; load :
  `20260824T140832071303Z-f162a708f0e1-local-docker/`.

## Live sandbox et cleanup

Statut actuel : `PASS`. Le bot de la Guild sandbox B dispose de `MANAGE_CHANNELS` et
`MANAGE_ROLES`; aucune elevation `ADMINISTRATOR` n'a ete necessaire. Le runner opt-in
a execute six plans reussis : CREATE_ROLE avec crash apres reponse puis recovery et
symbol binding, creation categorie/channel/role d'ancrage, updates + move parent +
reorder + upsert overwrite, delete overwrite, restauration auditee de l'ordre des
roles, puis suppression auditee de toutes les fixtures `DID-STAGE05-TEST-`.

La fenetre de crash prouve un seul appel CREATE et aucune duplication. Les mutations
passent toutes par API/plan, preflight, worker, Governor et adapter. La verification
REST ciblee relit l'intention finale, y compris apres une reponse intermediaire de
channel move. Les segments role bulk incluent les items Discord intermediaires tout
en verifiant les cibles explicites du DSG apres normalisation des roles managed.

Le cleanup est `COMPLETE_NO_PREFIXED_FIXTURES`; aucun identifiant Discord ni secret
n'est conserve dans la preuve suivie `STAGE_05_LIVE_EVIDENCE.json`. Les seuls cas non
forces contre Discord sont un 429 volontaire et un doublon CREATE ambigu; les deux
restent couverts par contrats/failure injection locaux.

## Tracabilite et limite de livraison

`REQ-PLAN-001..016`, `REQ-GW-006`, `REQ-AUD-002/003`, `REQ-STR-004/005` et
`REQ-RATE-005` sont audites ligne par ligne dans la matrice. `REQ-UX-006/007` restent
`PLANNED`. La revue corrective STAGE 05 est complete; la decision de merge reste une
revue humaine distincte.

PR #5 reste Draft et non mergee. STAGE 06 n'a pas ete commencee et reste interdite.
