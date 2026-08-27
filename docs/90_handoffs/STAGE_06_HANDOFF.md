# Handoff STAGE 06 — Clone, templates et Portable Artifacts

| Champ | Valeur |
|---|---|
| Date | `2026-08-26` — revue finale du gel sémantique READY |
| Base main | `f4dfc635ecc0de0697c034c26000638c3356a3fd` |
| Branche | `stage/06-portability` |
| Commits | `ab7a45b..0f129dd` — pipeline initial, durabilité/identité/reprise puis gel du mapping sémantique complet |
| PR | [#6](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/6), Draft, non mergée |
| Statut | `STAGE_06_COMPLETE_PR_OPEN` |
| Migration | `0012_stage_06` après `0011_stage_06` ; une seule tête attendue |

## Artifact, fichier et provenance

Le schéma immutable `did-portable-artifact-v&#49;` sépare le contenu canonique des métadonnées de
stockage. Le format fichier `did-portable-file-v&#49;` est un objet JSON UTF-8 strict contenant exactement
la version, le SHA-256 du contenu canonique et l'artifact. Le hash est stable face à l'ordre des
dictionnaires, de l'insertion et du processus ; il vérifie l'intégrité logique mais n'est ni une
signature ni une preuve de confiance. Les kinds owner-scopés sont `CLIPBOARD`, `LIBRARY`,
`EXPORT_BUNDLE` et `FILE_IMPORT`; les types d'artifact sont `CHANNEL`, `CATEGORY`, `LOGICAL_GROUP`,
`GUILD_CONFIG` et `CUSTOM_BUNDLE`.

La provenance autorise seulement un `source_guild_id` et des IDs source informatifs, triés, avec
`assertion=NON_AUTHORITATIVE`. Elle n'est jamais consultée pour résoudre une relationship ou une
autorisation. Le builder réel dérive chaque logical ref sous forme `type.k<sha256 tronqué>` depuis la
Guild source, le type et le Snowflake source. Le Snowflake brut n'est ni exposé comme destination ref,
ni comparé à B, ni porteur de capability ; il sert uniquement à stabiliser l'identité logique opaque
d'une ressource entre A1 et A2. Ajouts, suppressions et réordonnancements ne renumérotent donc aucun
survivant et une ancienne ref n'est pas recyclée.

Sont explicitement exclus : tokens bot/OAuth/webhook/provider, URL webhook secrète, sessions,
cookies, capabilities/permissions DID, membres, bindings utilisateur/rôle source, ownership, boosts,
messages, historiques, IDs de messages, audit Discord et secrets d'installation. Aucun membre,
message, historique, audit ou ID Discord d'origine n'est promis reproductible.

## Chiffrement, rotation, durée de vie et import hostile

Chaque artifact stocké utilise une DEK AES-256-GCM aléatoire ; cette DEK est elle-même enveloppée par
une clé maître AES-256-GCM versionnée. Contenu et wrapping ont des nonces CSPRNG indépendants de
12 octets. L'AAD canonique lie `artifact_id`, owner, schema, `key_version` et `content_hash`. La clé
courante vient de `ARTIFACT_ENCRYPTION_KEY`; le keyring secret
`ARTIFACT_PREVIOUS_ENCRYPTION_KEYS` permet lecture puis ré-encryption. Une ancienne clé absente donne
`PORTABLE_KEY_UNAVAILABLE` sans purge ni qualification mensongère de corruption. Les tests altèrent
ciphertext, DEK enveloppée, nonces, hash, owner et artifact ID et vérifient le refus fail-closed.

Les TTL par défaut sont 3 600 s pour le clipboard et 2 592 000 s pour les exports/imports. Les quotas
par owner sont 100 artifacts et 25 000 000 octets actifs ; les expirés sont invisibles, purgés lors
de la liste owner et ne consomment pas le quota. La suppression/purge d'un artifact peut cascader ses
transferts éphémères, mais ne supprime jamais `portable_clone_relationships` ni ses bindings durables.

L'import refuse au plus tard à 2 000 000 octets bruts : compression/`Content-Encoding`, JSON invalide,
clés dupliquées, champs inconnus, version future, hash faux, type inconnu, plus de 1 000 ressources,
5 000 dépendances, profondeur 12, strings de plus de 16 384 octets, références inconnues, cycles et
champs secrets/opérationnels. Le parser pur ne contient aucun client HTTP, extraction d'archive ou
résolution d'URL : un fichier ne déclenche ni réseau ni plan avant validation complète.

## Graphe, mapping et compilation

Les ressources portables sont `ROLE`, `CATEGORY`, `CHANNEL`, `OVERWRITE`, `LOGICAL_GROUP`, `POLICY`,
`SYSTEM_PRINCIPAL`, `PRINCIPAL_REQUIREMENT`, `BOT_REFERENCE` et `WEBHOOK_REFERENCE`. Le Dependency
Graph valide les références, refuse cycles/self-edges, ordonne topologiquement et calcule la fermeture
des parents/principals ; un clone profond de catégorie inclut enfants réels, positions, overwrites et
rôles requis. Il ne crée jamais de fausse sous-catégorie.

`MappingDecision` vaut `CREATE`, `MAP_EXISTING`, `SKIP`, `UNSUPPORTED` ou `MANUAL`. L'égalité d'ID
source/destination n'est jamais testée. Un même nom n'est qu'une suggestion et reste `MANUAL`; seul
un portable key DID unique peut être proposé automatiquement en MERGE/RECONCILE. Un mapping explicite
valide la Guild B, le type réel, la présence de la cible et la confirmation, puis persiste l'acteur.
Les rôles managed ne sont jamais recréés ; `@everyone` devient un principal système résolu vers
l'ID de B ; bots, webhooks et membres exigent un mapping B existant explicite ou restent manuels.
Une policy est copiée comme définition sans binding actif et ses principals doivent être confirmés.

Les quatre modes utilisent le même compilateur : COPY_AS_NEW crée sans fusion par nom ni suppression ;
MERGE conserve l'identité B confirmée et compile les propriétés portables de l'artifact, donc une
divergence réelle produit un UPDATE ; RECONCILE réutilise ce MERGE, crée les absents et supprime seulement
les bindings owner/B/relation dérivés côté serveur. Chaque DELETE est exposé comme
`DELETE_CANDIDATE` destructif dans preview avant STAGE 05. Le client fournit au plus une relation opaque,
jamais des IDs à supprimer. MAXIMUM_COMPATIBLE est strictement report-only avec `plan=null`,
`destination_plan_id=NULL` et résultats `CLONED/PARTIAL/SKIPPED/IMPOSSIBLE/INTERVENTION_REQUIRED`.

La matrice `did-clone-support-v&#50;` est explicite par type Discord : category est `FULL`; text,
announcement, voice et stage sont `PARTIAL`, car leurs propriétés portées sont préservées mais un
`flags` observé n'est pas accepté à la création. Directory, forum et media sont `UNSUPPORTED` tant que
leur contrat complet n'est pas porté. Les attributs suivent `did-portable-attributes-v&#50;` : clés,
types, containers, booléens, entiers, chaînes, bitfields décimaux et bornes sont validés fail-closed
dès `artifact_from_bytes`, avant mapping ou création de plan.

Les catégories, channels et rôles deviennent des nœuds DSG destination. Un logical group reçoit une
nouvelle UUID DID déterministe par transfert et est créé seulement après succès du plan ; une policy
portable devient une nouvelle définition tenant B sans binding source. La finalisation est idempotente.

## Stockage, templates et transfert

`user_portable_artifacts` est un User Control Plane avec `FORCE RLS` sur
`owner_discord_user_id`. Clipboard et library utilisent le même stockage chiffré. `templates` et
`portable_policy_definitions` sont privés à la Guild, portent `FORCE RLS` sur `guild_id` et des clés
composites. Un template contient l'artifact portable et son apply le stocke chiffré pour appeler
exactement `compile_stored`, donc sans pipeline divergent.

`portable_clone_relationships` possède un `relationship_id` UUID généré côté serveur, owner, B,
descriptor source informatif, statut, timestamps, dernier transfer et dernier hash. Elle porte
`FORCE RLS` owner et ne possède aucune FK vers un artifact. COPY_AS_NEW sans relation en crée une
nouvelle ; MERGE/RECONCILE exigent une relation explicite compatible owner/B/état. Un fichier importé
sans relation ne reçoit jamais de scope destructif implicite.

`cross_guild_transfers` porte owner/actor, A, B, artifact/hash, `relationship_id`, mode, mapping/report,
`request_hash`, `mapping_hash`, `report_hash`, plan B nullable, correlation/idempotency et version
d'état. `portable_clone_bindings` dépend de la relationship, non du transfer ; `last_transfer_id` est
nullable `ON DELETE SET NULL`. La finalisation upsert les refs courantes et place `active=false` avec
`tombstoned_at` sur les refs disparues ; `reconcile_bindings()` ne retourne que les bindings actifs.
Une FK composite interdit de lier l'artifact d'un autre owner.

Les états explicites sont `CREATED`, `SOURCE_AUTHORIZED`, `EXPORTED`, `MAPPING_REQUIRED`, `READY`,
`COMPILED`, `FAILED`, `CANCELLED`. La reprise traite chaque frontière déterministement : CREATED peut
reprendre l'autorisation source, SOURCE_AUTHORIZED persiste l'export, EXPORTED reprend le mapping,
MAPPING_REQUIRED accepte le complément, READY reprend la création/récupération du plan et COMPILED est
read-only. Un crash après création du plan mais avant COMPILED retrouve ce même plan ; aucun second
transfer ou plan et aucune relecture A ne sont produits.

Le pipeline est unique : autoriser/lire A, fermer ce contexte, produire/stocker l'artifact, créer la
relationship/transfer et persister `SOURCE_AUTHORIZED` puis `EXPORTED`, autoriser B, lire B, construire
graphe/mappings/DSG, créer un unique plan STAGE 05 B. Un refus B laisse le transfer `EXPORTED`; le retry
reprend l'artifact stocké sans lire A. Il n'existe ni transaction
A+B, ni lock A+B, ni adapter Discord mutable dans l'orchestrateur. L'artifact ou sa provenance ne
confère aucune capability. `STRUCTURE_READ` couvre A ; `PLANS_CREATE` + `STRUCTURE_WRITE` couvrent la
compilation B ; `TEMPLATES_READ/WRITE` couvrent les templates ; l'apply revalide `PLANS_APPLY` dans
STAGE 05. Cette décision est consignée dans IMP-013.

Les clés d'idempotence hashent une sérialisation canonique contenant l'intégralité de la clé appelante,
l'artifact, B et le mode ; aucune troncature de préfixe n'est possible. Le mapping reste complétable
jusqu'à READY. La transition READY persiste atomiquement la résolution complète dans `mapping_json` et
un SHA-256 `mapping_hash` calculé sur `{explicit,resolved}`. `explicit` contient logical ref, type,
Guild B, destination, confirmation ; `resolved` contient logical ref, type, décision, destination et
état de confirmation. Score, raison diagnostique, candidats, wording, acteur/timestamp et ordre non
sémantique sont exclus. La clé d'idempotence du plan dépend directement de ce hash figé.

Un retry READY compare d'abord l'intention explicite au mapping persisté, relit ensuite B et rejoue le
resolver uniquement pour prouver que le hash sémantique complet est inchangé. Une cible automatique
disparue, un remap vers un candidat alternatif ou une décision CREATE devenue MANUAL produit
`TransferConflict` avant le compilateur et avant `PlanningService.create`; `mapping_json` et
`mapping_hash` ne sont jamais réécrits. Une cible inchangée reprend le même mapping et la même clé de
plan. COMPILED reste read-only : même plan/mapping/report retourne l'existant et toute divergence est
un conflit.

Les lignes READY/COMPILED antérieures à 0012 ne contenaient pas assez de matière pour reconstruire ce
hash complet. Le backfill 0012 les invalide donc fail-closed en `FAILED` avec
`LEGACY_MAPPING_REFREEZE_REQUIRED`, au lieu de fabriquer un hash trompeur. STAGE 06 n'étant pas mergée,
aucune compatibilité de production fictive n'est entretenue et aucune migration 0013 n'est nécessaire.
Les quotas owner
count/bytes sont sérialisés par advisory transaction lock. Les audits de frontière sont idempotents par
transfer/event, indépendamment de la création/réutilisation du plan. Le même `transfer_id` relie audits source et destination. Les erreurs
404 owner, 403 capability, 409 mapping/quota, 422 intégrité/format et 503 clé/service évitent toute
divulgation de l'existence, du plaintext ou des secrets.

## API

- `POST /api/v&#49;/guilds/{guild_id}/exports/portable`
- `GET /api/v&#49;/me/portable-artifacts` et `GET/DELETE /{artifact_id}`
- `GET /api/v&#49;/me/portable-artifacts/{artifact_id}/file`
- `POST /api/v&#49;/me/portable-artifacts/import`
- `POST /api/v&#49;/me/portable-artifacts/{artifact_id}/clone`
- `POST /api/v&#49;/guilds/{guild_id}/imports/preview` et `/imports/plan`
- `POST /api/v&#49;/transfers`, `GET /api/v&#49;/transfers/{transfer_id}` et `POST /finalize`
- `GET /api/v&#49;/portability/support-matrix`
- `GET/POST /api/v&#49;/guilds/{guild_id}/templates` et `POST /templates/{template_id}/apply`

Toutes les mutations cookie-authenticated imposent CSRF. Les IDs sont des strings décimales/UUID aux
frontières, le fichier est lu en stream avec limite dure, et B est autorisée avant toute divulgation
de candidats ou création de plan.

## Tests et preuves

Les tests unitaires couvrent canonicalisation, immutabilité, format hostile et mauvais types/bornes,
graphe/fermeture/cycles, mappings dupliqués/inconnus/non confirmés, refs stables du vrai builder entre
générations avec suppressions/insertions avant les survivants, MERGE divergent rôle/channel, cycle
naturel A1→A2 sans injection manuelle, report-only, toutes les frontières du lifecycle, gel READY du
mapping sémantique complet, cible automatique inchangée/supprimée/alternative, drift CREATE, conflit
explicite M1→M2, COMPILED immutable, denial B puis retry sans A, crypto/rotation, API, architecture et confused deputy.
PostgreSQL réel couvre encryption at rest, idempotence, quota, owner U/V, tenant A/B, FK cross-owner,
RLS template/policy/transfert/relation, survie relation+bindings après delete artifact et purge TTL,
tombstone, mapping hash et plan immutable. Le test destination-only appelle le reader exactement sur B
et crée un seul DSG/plan B ; la compilation d'un artifact stocké ne possède aucun reader A. Le load
utilise 600 ressources.

La revue finale a validé le commit propre `0f129dd36e61` avec la matrice complète : STAGE 01
`20260826T210325464845Z`, STAGE 02 `20260826T210446419888Z`, STAGE 03 et load
`20260826T210559080215Z` / `20260826T210714417697Z`, STAGE 04 `20260826T210735618902Z`, STAGE 05,
failure-injection et load `20260826T210907041069Z` / `20260826T211046491783Z` /
`20260826T211059907801Z`, STAGE 06, security et live `20260826T211102852024Z` /
`20260826T211239541227Z` / `20260826T211254622127Z`. Le dernier run inclut 261 tests unitaires,
76 intégrations, quatre tests PostgreSQL STAGE 06 dont le drift READY, les migrations downgrade/upgrade jusqu'à la
tête unique `0012_stage_06`, frontend, secret scan, docs, PostgreSQL RLS, charge et Discord live. Les
preuves antérieures restent historiques.

Le live A→B a créé toutes les fixtures via STAGE 05, produit A1, effectué COPY_AS_NEW puis finalize,
et supprimé l'artifact A1 tout en conservant relationship et bindings. Il a ensuite modifié A via un
plan STAGE 05 : un channel survivant a changé, un channel a été supprimé et un nouveau ajouté. Le vrai
builder A2 a conservé la logical ref du survivant. A2 a été persisté EXPORTED, puis preview/compile B
ont utilisé un source reader fail-if-called. RECONCILE a mis à jour le même ID B, créé le nouveau,
exposé puis supprimé exactement le B correspondant à la source disparue, tombstoné son binding et
laissé le rôle témoin B intact. Après suppression A2, relation et quatre bindings actifs subsistaient.
Zéro lecture A après export et zéro mutation A pendant B ont été mesurées ; le snapshot A2 est resté
byte-identical. Le cleanup A/B a utilisé des plans STAGE 05 audités et a nettoyé 9 fixtures. La preuve
expurgée `STAGE_06_LIVE_EVIDENCE.json` ne contient aucun secret ni identifiant Discord.

Les limites volontaires sont : aucune signature de fichier (le hash n'est
pas une authentification), pas d'installation automatique de bot/webhook, pas de
membres/messages/history/audit, et pas d'UI STAGE 07.

## Contrat transmis à STAGE 07

STAGE 07 pourra appeler les routes de preview/plan, afficher le report/mapping et réutiliser les
primitives clipboard/library/clone. Il ne doit pas recompiler côté frontend, traiter un ID source
comme une identité, cacher une décision manuelle ou muter Discord directement. STAGE 07 reste
interdite avant merge normal et revue externe de cette PR.
