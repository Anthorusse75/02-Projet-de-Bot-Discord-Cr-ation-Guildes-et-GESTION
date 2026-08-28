# Handoff STAGE 08 — Multilingual Content & Translation Topology

| Champ | Valeur |
|---|---|
| Date | `2026-08-28` |
| Base main | `d644015903953ef1dc46626562004746f2208c1c` |
| Branche | `stage/08-multilingual-topology` |
| Migration | `0014_stage_08` après `0013_stage_07` |
| Statut | `STAGE_08_IMPLEMENTATION_IN_PROGRESS` |
| PR | `draft retained, not complete and not ready for merge` |

## Scope livré

Le Stage 08 n’est pas terminé. Le dépôt contient actuellement un socle initial de domaine/migration/tests, mais il manque encore la majeure partie du périmètre canonique attendu.

- `language_profiles` : modèle initial et exigence de tenant-safe présent.
- `member_visible_languages` : logique initiale de set sans langue principale obligatoire.
- `resource_language_policies` : résolution d’héritage explicite sans fallback implicite.
- `translation_groups` : identité indépendante du langage est en place dans le domaine.
- `translation_routes` : validation de base a été corrigée pour contraindre les variantes au même `translation_group_id`.
- `translation_provider_bindings` : contrat initial de provider, mais pas l’implémentation complète du port/service/registry attendu.
- `visibility_scope_language_roles` : racine de rôle technique `Scope × Language`, sans la couverture complète de la sécurité/budget/live requise.

Les fichiers principaux sont `backend/src/did/domain/translation_topology.py` et `backend/alembic/versions/0014_stage_08_multilingual_topology.py`.

## Invariants corrigés

- Les FKs composites vers `language_profiles` et les FK sur `translation_group_id` doivent référencer une clé unique correspondante `(guild_id, id)`.
- Les routes ne doivent accepter que des variantes du même `translation_group_id`.
- Deux groupes partageant les mêmes langues restent indépendants, sans route ni variante implicite partagée.
- L’état courant du document n’annonce plus une candidate complète ni une validation terminée.

## Blocages restants

1. Migration PostgreSQL réelle et composite FK restantes à vérifier sur l’ensemble du schéma Stage 08.
2. Validation de routes/variants strictement par groupe à couvrir par les tests de domaine puis API/application.
3. Application/service/repository/API/provider/visibility/budget/live surface encore largement absente.
4. Frontend Stage 08, E2E Stage 08 et live Discord obligatoires restent non remplis.
5. La preuve Github CI/PR ne peut pas être déclarée verte tant que ces work packages ne sont pas complétés.

## Preuves actuelles

### Validation locale exécutée

```bash
uv run pytest backend/tests/unit/test_stage08_translation_topology.py -q
uv run alembic upgrade head
```

Résultat attendu courant : le correctif de groupe/route et de migration est localement vérifié à mesure que les tests sont réajustés ; ce n’est pas une validation de fin de Stage 08.

## Fichiers ajoutés / modifiés

- `backend/src/did/domain/translation_topology.py`
- `backend/alembic/versions/0014_stage_08_multilingual_topology.py`
- `backend/tests/unit/test_stage08_translation_topology.py`
- `docs/10_implementation/00_CURRENT_STATE.md`
- `docs/90_handoffs/STAGE_08_HANDOFF.md`

## Prochaine étape

Poursuivre le work package réel Stage 08 en respectant la checklist locale 43 IDs, sans déclarer la candidate complète ni avancer vers Stage 09.
