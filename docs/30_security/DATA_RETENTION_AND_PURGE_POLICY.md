# Politique de rétention et de purge des données (REQ-DATA-001 / REQ-DATA-002)

Ce document décrit le comportement RÉEL du système tel qu'implémenté et prouvé par
test, pas une politique aspirationnelle. Toute affirmation ci-dessous est
directement vérifiable dans le code cité et dans
`backend/tests/integration/test_stage06_postgres.py::test_purge_tenant_deletes_only_target_guild_data_across_postgres_and_redis`,
`backend/tests/integration/test_stage02_api.py::test_delete_tenant_cascades_only_the_target_guild`
et `backend/tests/integration/test_redis.py::test_guild_redis_purge_removes_only_tenant_keys_and_job_routing`.

## REQ-DATA-001 — Minimisation

- DID ne demande pas l'intent Discord `MESSAGE_CONTENT` dans le cadre normal.
- Le contenu général des événements `MESSAGE_CREATE`/`MESSAGE_UPDATE` n'est pas
  conservé.
- La politique Message Content (Stage08/09) bloque explicitement toute
  fonctionnalité qui nécessiterait ce contenu lorsqu'il n'est pas disponible
  (`MANUAL_CONFIGURATION_REQUIRED`/`BLOCKED`), plutôt que de le simuler.
- Les `content_snapshot` du Campaign Engine (Stage09) sont le contenu DID
  **sortant** (les campagnes que DID envoie sur Discord), jamais une collecte
  générale de conversations Discord existantes.

## REQ-DATA-002 — Purge tenant (droit à l'effacement au niveau Guild)

### Déclenchement

`InstallationService.purge_tenant()`
(`backend/src/did/application/installations/service.py`) est le seul point
d'entrée. Il est exposé par
`DELETE /api/v1/guilds/{guild_id}/installation/purge`
(`backend/src/did/api/guilds.py`), distinct de
`DELETE /api/v1/guilds/{guild_id}/installation` (désinstallation logique,
réversible). La route de purge exige `CsrfSessionDep` et l'autorisation
`RBAC_WRITE` sensible (`sensitive=True`).

### Séquence (ordre garanti, chaque étape doit réussir avant la suivante)

1. `authorize(..., capability=RBAC_WRITE, sensitive=True)`
2. `repository.mark_uninstalled(guild_id, actor_user_id)`
3. `runtime_wakeup.remove_job_guild(guild_id)` — retire l'entrée du ZSET
   `did:runtime:routing:jobs`
4. `purge_guild_namespace(redis, guild_id)` — `SCAN`/`UNLINK` de tout
   `did:guild:{guild_id}:*`
5. `repository.delete_tenant(guild_id)` — `DELETE FROM guild_installations
   WHERE guild_id=...`, qui cascade (`ON DELETE CASCADE`) sur toutes les
   tables tenant-owned rattachées à `guild_installations`

Une erreur à n'importe quelle étape empêche les étapes suivantes.
`EventId.TENANT_PURGED` n'est émis qu'après un `delete_tenant()` réussi
(`deleted is True`) — jamais avant, jamais en cas d'échec Redis ou DB (preuve :
`backend/tests/unit/test_installation_service.py`).

### Ce qui est supprimé (tenant-owned, cascade `ON DELETE CASCADE` depuis
`guild_installations`)

Toutes les lignes portant `guild_id = <Guild purgée>` dans les tables
rattachées via `_installation_fk(...)`/FK équivalente, notamment (liste non
exhaustive, dérivée du schéma réel) : `guild_user_access`,
`guild_role_bindings`, `plans` et toute sa descendance (`plan_operations`,
`plan_symbol_bindings`, `plan_resource_dependencies`, `plan_confirmations`,
`plan_progress_events`, `plan_expected_mutations`, `operation_attempts`,
`plan_snapshots`), tables de topologie/traduction Stage08/09 scoping sur
`guild_id`, etc.

**Correctif Stage10 (migration `0034_stage_10`)** : la table
`plan_snapshots` porte depuis Stage05
(`0009_stage_05_hardening`) un trigger d'immutabilité qui rejette
inconditionnellement tout `UPDATE`/`DELETE` — y compris un `DELETE` atteignant
la table uniquement par cascade depuis la suppression de
`guild_installations`. Cela rendait `delete_tenant()` **structurellement
impossible** dès qu'une Guild avait un jour compilé un plan (donc pour toute
Guild réelle). Le correctif restreint la garde : `DELETE` n'est permis que
pendant la transaction où le GUC local `app.tenant_purge_in_progress` vaut
`'on'` (positionné uniquement par `AuthRepository.delete_tenant()`, avec la
même convention que `apply_rls_context`). `UPDATE` reste bloqué
inconditionnellement dans tous les cas : le journal de preuve ne peut être
effacé qu'en bloc avec son tenant, jamais réécrit silencieusement.

### Ce qui est supprimé (Redis)

`purge_guild_namespace()` supprime tout `did:guild:{guild_id}:*` par
`SCAN`/`UNLINK` par lots de 256 clés. `RedisRuntimeWakeup.remove_job_guild()`
retire l'entrée `guild_id` du ZSET global de routage
`did:runtime:routing:jobs` sans jamais consommer/altérer les entrées des
autres tenants (aucune purge n'utilise `pop_job_guilds()` pour inspecter le
ZSET global).

### Ce qui SURVIT à la purge (user-owned, jamais tenant-owned)

- **`user_portable_artifacts`** : scope propriétaire =
  `owner_discord_user_id`, pas `guild_id`. Ces artefacts (bibliothèque
  personnelle de templates/rôles/permissions exportés par un utilisateur) ne
  sont rattachés à `guild_installations` par aucune FK `ON DELETE CASCADE` et
  survivent donc intacts à la purge de n'importe quelle Guild. Leur propre
  rétention (`expires_at`, quotas par owner) reste inchangée par cet événement.
- **`cross_guild_transfers`** (historique de transfert utilisateur) : la ligne
  de transfert elle-même n'est jamais supprimée par une purge de Guild. Seule
  sa référence au plan de destination est détachée :
  `destination_plan_id` devient `NULL` (migration `0033_stage_10`, FK
  `fk_transfers_destination_plan ... ON DELETE SET NULL (destination_plan_id)`)
  tandis que `destination_guild_id` est conservé comme trace historique
  (« ce transfert visait cette Guild, qui n'existe plus »).

### Ce qui n'est PAS couvert par ce document

- La purge d'un artefact portable individuel à la demande de son propriétaire
  (droit à l'effacement au niveau utilisateur) est un mécanisme distinct,
  déjà couvert par Stage06 (`PortabilityRepository`), inchangé par Stage10.
- Aucune donnée de production n'est déployée ou migrée par ce document —
  Stage10 reste hors scope de déploiement (voir STAGE 11).

## Preuve

- `backend/tests/integration/test_stage06_postgres.py::test_purge_tenant_deletes_only_target_guild_data_across_postgres_and_redis`
  — tenant A purgé end-to-end (Postgres cascade incluant un plan réel avec
  snapshot, Redis, routing job), tenant B témoin intact, artefact portable
  conservé, transfert conservé avec `destination_plan_id=NULL` et
  `destination_guild_id` préservé, `TENANT_PURGED` émis exactement une fois
  avec les bons champs.
- `backend/tests/integration/test_stage02_api.py::test_delete_tenant_cascades_only_the_target_guild`
  — cascade RBAC (accès/role bindings) A/B.
- `backend/tests/integration/test_redis.py::test_guild_redis_purge_removes_only_tenant_keys_and_job_routing`
  — isolation Redis A/B, y compris le routing job.
- `backend/tests/unit/test_installation_service.py` — ordre des opérations et
  fail-closed sur erreur Redis/DB, `TENANT_PURGED` uniquement après succès.
