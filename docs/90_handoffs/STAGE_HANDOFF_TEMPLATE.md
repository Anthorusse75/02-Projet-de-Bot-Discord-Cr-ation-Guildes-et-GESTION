# Handoff STAGE XX — <nom>

| Champ | Valeur |
|---|---|
| Date | `<YYYY-MM-DD>` |
| Commit main | `<sha>` |
| Branche / PR | `<branch>` / `<URL ou N/A justifié>` |
| Statut | `COMPLETE` ou `BLOCKED` |

## Livré

- modules et comportements ;
- migrations (revision précédente → nouvelle) ;
- API/events/jobs/keys Redis ;
- documentation et décisions.

## Validation et preuves

| Commande/scénario | Résultat | Preuve | REQ couverts |
|---|---|---|---|
| `python scripts/validate_stage.py XX` | `<PASS/FAIL>` | `<path/run>` | `<REQ-...>` |

## État opérationnel

- containers et versions ;
- dernière migration appliquée ;
- Guild sandbox A/B avant/après et nettoyage ;
- secrets/configuration encore requis (noms uniquement) ;
- jobs/queues/locks résiduels : aucun ou liste justifiée.

## Écarts, risques et bugs connus

- écarts entre document prévu et dépôt réel avec décision ;
- limitations non bloquantes ;
- bugs connus et tickets ;
- vérification qu’aucun TODO bloquant n’est masqué.

## Prérequis exacts de l’étape suivante

- branche et SHA attendus ;
- modules/migrations/tags attendus ;
- commande de baseline ;
- actions humaines ou configuration externe à demander au moment utile.
