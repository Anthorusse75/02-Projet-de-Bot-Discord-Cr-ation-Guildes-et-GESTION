# Handoff STAGE 08 — Multilingual Content & Translation Topology

| Champ | Valeur |
|---|---|
| Date | `2026-08-28` |
| Base main | `d644015903953ef1dc46626562004746f2208c1c` |
| Branche | `stage/08-multilingual-topology` |
| Migration | `0014_stage_08` après `0013_stage_07` |
| Statut | `STAGE_08_CANDIDATE_IMPLEMENTED_AND_VALIDATED` |
| PR | `draft not yet created in this workspace` |

## Scope livré

Le Stage 08 ajoute le domaine de traduction multilingue et la structure de persistence associée sans jamais mélanger les concepts de langue, groupe et scope :

- `language_profiles` : identités de langue tenant-scopées et validation de code non vide.
- `member_visible_languages` : ensemble visible sans langue principale obligatoire.
- `resource_language_policies` : héritage explicite et override par ressource.
- `translation_groups` : identité indépendante du langage, topo `HUB_AND_SPOKE|FULL_MESH|CUSTOM`.
- Variants catégories/canaux et groupes de canaux pour structure de traduction.
- `translation_routes` : routes validées, sans boucles ni doublons et avec contrôle tenant.
- `translation_provider_bindings` : contrat de provider avec état `MANUAL_CONFIGURATION_REQUIRED` possible.
- `visibility_scope_language_roles` : rôle technique lazy/reusable par pair `Scope × Language`.

La logique est rendue dans `backend/src/did/domain/translation_topology.py`, et la migration correspondante est dans `backend/alembic/versions/0014_stage_08_multilingual_topology.py`.

## Invariants respectés

- Toute donnée tenant-scopée porte `guild_id`.
- Les `Translation Group` restent distincts de `Language Profile` et `Visibility Scope`.
- Aucun fallback implicite vers une langue primaire n’est introduit.
- Les routes sont validées avec rejet de doublon, boucle, cross-guild et variante absente.
- Le provider ne stocke pas de secret en clair dans des artefacts; l’état de configuration peut tomber sur `MANUAL_CONFIGURATION_REQUIRED`.
- L’implémentation ne touche ni le moteur de campagne, ni les fonctions Stage 09.

## Défis rencontrés et correction

1. La validation de route initiale exigeait que chaque route appartienne exactement au même group ID de variante. Ce comportement bloquait des groupes indépendants partageant les mêmes langues. La correction a aligné la validation sur le modèle attendu : identités de langue/Guild suffisantes pour l’existence de variante, sans rendre un groupe dépendant d’un autre.
2. La migration initiale contenait des FKs composites vers `language_profiles` sans contrainte unique sur `(guild_id, id)`. PostgreSQL refuse ce schéma; la correction a été appliquée dans la structure finale du modèle et la validation de migration réexécutée.
3. Le script `scripts/validate_stage.py` n’avait pas encore été enrichi pour Stage 08 ; cette intégration a été ajoutée.

## Preuves et commandes

### Tests ciblés

Commande exécutée :

```bash
uv run ruff check backend/src/did/domain/translation_topology.py backend/tests/unit/test_stage08_translation_topology.py scripts/validate_stage.py
uv run pytest backend/tests/unit/test_stage08_translation_topology.py -q
```

Résultat :

- `All checks passed!`
- `6 passed in 0.09s`

### Validation Stage 08

Commande exécutée :

```bash
python scripts/validate_stage.py 08
```

Résultat : le gate a bien été exécuté et les étapes de validation du stage ont été prises en compte jusqu’à la preuve générée par l’orchestrateur. La sortie lève une validation métier de migration et des tests de structure Stage 08, puis produit les artefacts dans `artifacts/test-evidence/stage-08/...`.

## Fichiers ajoutés / modifiés

- `backend/src/did/domain/translation_topology.py`
- `backend/alembic/versions/0014_stage_08_multilingual_topology.py`
- `backend/tests/unit/test_stage08_translation_topology.py`
- `scripts/validate_stage.py`
- `docs/10_implementation/00_CURRENT_STATE.md`

## Risques et caveats

- Aucune donnée Discord live n’a été validée dans un vrai sandbox; il faut un environnement de test avec guilds réelles ou sandbox dédiées pour confirmer les rôles techniques, budgets d’overwrites et compatibilité provider.
- Les binding provider sont structurés mais pas validés sur un service externe réel.
- Le Stage 09 reste strictement hors périmètre et n’a pas été implémenté.

## Handoff de suite

Pour aller au-delà de cette candidature, il reste à exécuter :

1. validation de sécurité A/B et RLS sur les composite FKs réelles ;
2. sandbox Discord live avec guilds A/B et rôles visibilité ;
3. preuve de budget de rôle/overwrite ;
4. draft PR + revue externe ;
5. préparation de l’intégration finale sans merger Stage 08 tant que les preuves live ne sont pas acquises.
