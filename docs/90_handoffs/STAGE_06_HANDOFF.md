# Handoff STAGE 06 — Clone, templates et Portable Artifacts

| Champ | Valeur |
|---|---|
| Date | `2026-08-24` |
| Base main | `f4dfc635ecc0de0697c034c26000638c3356a3fd` |
| Branche | `stage/06-portability` |
| Commit implémentation | `ab7a45b` — `feat(portability): implement portable artifact pipeline` |
| PR | Draft, à renseigner après publication |
| Statut | `IMPLEMENTED_VALIDATION_IN_PROGRESS` |
| Migration | `0010_stage_06` après `0009_stage_05` ; une seule tête attendue |

## Artifact, fichier et provenance

Le schéma immutable `did-portable-artifact-v&#49;` sépare le contenu canonique des métadonnées de
stockage. Le format fichier `did-portable-file-v&#49;` est un objet JSON UTF-8 strict contenant exactement
la version, le SHA-256 du contenu canonique et l'artifact. Le hash est stable face à l'ordre des
dictionnaires, de l'insertion et du processus ; il vérifie l'intégrité logique mais n'est ni une
signature ni une preuve de confiance. Les kinds owner-scopés sont `CLIPBOARD`, `LIBRARY`,
`EXPORT_BUNDLE` et `FILE_IMPORT`; les types d'artifact sont `CHANNEL`, `CATEGORY`, `LOGICAL_GROUP`,
`GUILD_CONFIG` et `CUSTOM_BUNDLE`.

La provenance autorise seulement un `source_guild_id` et des IDs source informatifs, triés, avec
`assertion=NON_AUTHORITATIVE`. Elle n'est jamais consultée pour résoudre une identité ou une
autorisation. Les logical keys et symboles sont les seules références structurelles compilables.

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
de la liste owner et ne consomment pas le quota. La suppression owner cascade les transferts associés.

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
MERGE combine uniquement des mappings explicites et ne supprime rien ; RECONCILE peut créer, mettre à
jour et supprimer seulement les ressources énumérées dans `ReconcileScope`, chaque DELETE apparaissant
comme `DELETE_CANDIDATE` destructif avant STAGE 05 ; MAXIMUM_COMPATIBLE rend chaque résultat
`CLONED/CREATED/REMAPPED/SKIPPED/IMPOSSIBLE/INTERVENTION_REQUIRED`. La matrice
`did-clone-support-v&#49;` expose les opérations réelles par type et mode.

Les catégories, channels et rôles deviennent des nœuds DSG destination. Un logical group reçoit une
nouvelle UUID DID déterministe par transfert et est créé seulement après succès du plan ; une policy
portable devient une nouvelle définition tenant B sans binding source. La finalisation est idempotente.

## Stockage, templates et transfert

`user_portable_artifacts` est un User Control Plane avec `FORCE RLS` sur
`owner_discord_user_id`. Clipboard et library utilisent le même stockage chiffré. `templates` et
`portable_policy_definitions` sont privés à la Guild, portent `FORCE RLS` sur `guild_id` et des clés
composites. Un template contient l'artifact portable et son apply le stocke chiffré pour appeler
exactement `compile_stored`, donc sans pipeline divergent.

`cross_guild_transfers` porte owner/actor, A, B, artifact/hash, mode, mapping, report, plan B,
correlation/idempotency, statut et résultat local. Une FK composite interdit de lier l'artifact d'un
autre owner. Les états explicites sont `CREATED`, `SOURCE_AUTHORIZED`, `EXPORTED`,
`MAPPING_REQUIRED`, `READY`, `COMPILED`, `FAILED`, `CANCELLED`; l'apply reste entièrement dans la
machine STAGE 05.

Le pipeline est unique : autoriser/lire A, fermer ce contexte, produire/stocker l'artifact, autoriser
B, lire B, construire graphe/mappings/DSG, créer un unique plan STAGE 05 B. Il n'existe ni transaction
A+B, ni lock A+B, ni adapter Discord mutable dans l'orchestrateur. L'artifact ou sa provenance ne
confère aucune capability. `STRUCTURE_READ` couvre A ; `PLANS_CREATE` + `STRUCTURE_WRITE` couvrent la
compilation B ; `TEMPLATES_READ/WRITE` couvrent les templates ; l'apply revalide `PLANS_APPLY` dans
STAGE 05. Cette décision est consignée dans IMP-013.

Les clés d'idempotence lient l'opération, l'owner, la sélection/artifact, B, le mode, le mapping et la
clé appelante. Les insertions concurrentes utilisent `ON CONFLICT`; un retry après mapping ou plan
retourne le même transfert/plan. Le même `transfer_id` relie audits source et destination. Les erreurs
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

Les tests unitaires couvrent canonicalisation, immutabilité, format hostile, graphe/fermeture/cycles,
mapping et ambiguïté, principals, observabilité live, scope RECONCILE, quatre modes, crypto/rotation,
API, architecture et confused deputy. PostgreSQL réel couvre encryption at rest, idempotence, quota,
TTL/purge, owner U/V, tenant A/B, FK cross-owner, RLS template/policy/transfert et cascade. Le test
destination-only appelle le reader exactement sur B et crée un seul DSG/plan B ; la compilation d'un
artifact stocké ne possède aucun reader A. Le load utilise 600 ressources.

Les run IDs finaux, le live, la preuve source inchangée, le cleanup et le statut CI seront ajoutés
après exécution sur un commit propre. Le live RECONCILE n'est pas requis s'il ne peut être borné sans
risque ; le test local prouve son scope exact. Les limites volontaires sont : aucune signature de
fichier (le hash n'est pas une authentification), pas d'installation automatique de bot/webhook,
pas de membres/messages/history/audit, et pas d'UI STAGE 07.

## Contrat transmis à STAGE 07

STAGE 07 pourra appeler les routes de preview/plan, afficher le report/mapping et réutiliser les
primitives clipboard/library/clone. Il ne doit pas recompiler côté frontend, traiter un ID source
comme une identité, cacher une décision manuelle ou muter Discord directement. STAGE 07 reste
interdite avant merge normal et revue externe de cette PR.
