# Handoff STAGE 08 — Multilingual Content & Translation Topology

| Champ | Valeur |
|---|---|
| Date | `2026-08-28` |
| Base main | `252a4661195a3868acd04a2987453e23fc6ee4ff` |
| Branche | `stage/08-multilingual-topology` |
| Migration | `0014_stage_08` après `0013_stage_07` |
| Statut | `STAGE_08_IMPLEMENTATION_IN_PROGRESS` |
| PR | `draft retained, not complete and not ready for merge` |

## Scope livré

Le Stage 08 n’est pas terminé. WP1 livre la persistence tenant-safe et les preuves PostgreSQL, mais il manque encore la majeure partie du périmètre canonique attendu.

- `language_profiles` : modèle initial et exigence de tenant-safe présent.
- `member_visible_languages` : logique initiale de set sans langue principale obligatoire.
- `resource_language_policies` : résolution d’héritage explicite sans fallback implicite.
- `translation_groups` : identité indépendante du langage est en place dans le domaine.
- `translation_routes` : validation de base a été corrigée pour contraindre les variantes au même `translation_group_id`.
- `translation_provider_bindings` : contrat initial de provider, mais pas l’implémentation complète du port/service/registry attendu.
- `visibility_scope_language_roles` : racine de rôle technique `Scope × Language`, sans la couverture complète de la sécurité/budget/live requise.
- `translation_group_languages` : membership durable d’un groupe vers ses langues, utilisée par les FKs composites des variantes.
- repositories Stage 08 : writes tenant-scoped et CAS `translation_groups.version` sont disponibles et câblés au `ServiceContainer`.

Les fichiers principaux sont `backend/src/did/domain/translation_topology.py` et `backend/alembic/versions/0014_stage_08_multilingual_topology.py`.

## Invariants corrigés

- Les FKs composites vers `language_profiles` et les FK sur `translation_group_id` doivent référencer une clé unique correspondante `(guild_id, id)`.
- Les routes ne doivent accepter que des variantes du même `translation_group_id`.
- Les données de route doivent déclarer explicitement leur `translation_group_id`; l’absence est rejetée.
- Deux groupes partageant les mêmes langues restent indépendants, sans route ni variante implicite partagée.
- Les bindings provider et les variants channel/category sont protégés par des FKs composites tenant-safe.
- Toutes les nouvelles tables ont RLS activé et forcé avec `USING` et `WITH CHECK` sur `guild_id`.
- L’état courant du document n’annonce plus une candidate complète ni une validation terminée.

## Blocages restants

1. Application/service/API/provider/visibility/budget/live surface encore largement absente.
2. Frontend Stage 08, E2E Stage 08 et live Discord obligatoires restent non remplis.
3. Provider adapter complet, clone multilingue, drift et plan integration restent hors WP1.
4. La preuve Github CI/PR ne peut pas être déclarée verte tant que ces work packages ne sont pas complétés.

## Preuves actuelles

### Validation locale exécutée

```bash
uv run pytest backend/tests/unit/test_stage08_translation_topology.py -q
DID_RUN_INTEGRATION=1 uv run pytest backend/tests/integration/test_stage08_persistence.py -q
python scripts/validate_stage.py 01
python scripts/validate_stage.py 07
python scripts/validate_stage.py 08
```

Résultat courant : Stage 01 PASS, Stage 07 PASS, Stage 08 PASS, dont le gate PostgreSQL WP1 et la rehearsal Alembic `0013 -> 0014 -> 0013 -> 0014` ; ce n’est pas une validation de fin de Stage 08.

## Fichiers ajoutés / modifiés

- `backend/src/did/domain/translation_topology.py`
- `backend/alembic/versions/0014_stage_08_multilingual_topology.py`
- `backend/tests/unit/test_stage08_translation_topology.py`
- `backend/src/did/infrastructure/stage08_repository.py`
- `backend/tests/integration/test_stage08_persistence.py`
- `backend/src/did/api/dependencies.py`
- `backend/src/did/api/main.py`
- `scripts/validate_stage.py`
- `docs/10_implementation/STAGE08_REQUIREMENTS_CHECKLIST_LOCAL.md`
- `docs/10_implementation/00_CURRENT_STATE.md`
- `docs/90_handoffs/STAGE_08_HANDOFF.md`

## Prochaine étape

Faire contrôler WP1, puis attendre l’autorisation avant WP2. Ne pas déclarer la candidate complète ni avancer vers Stage 09.
