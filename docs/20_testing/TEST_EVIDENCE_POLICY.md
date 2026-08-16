# Politique des preuves de test

Une preuve lie : exigence, commit, environnement, commande exacte, horodatage, résultat et artefact. Les sorties doivent être reproductibles et expurgées ; jamais de token, cookie, URL signée, contenu personnel ou identifiant sensible inutile.

## Emplacements

```text
artifacts/test-evidence/stage-XX/<run-id>/summary.json
artifacts/test-evidence/stage-XX/<run-id>/junit.xml
artifacts/test-evidence/stage-XX/<run-id>/reports/...
docs/90_handoffs/STAGE_XX_HANDOFF.md
```

Les gros artefacts CI peuvent rester dans GitHub Actions avec URL/run ID et politique de rétention ; le résumé et l’identifiant restent dans le handoff. Ne pas committer captures ou dumps contenant des données Discord réelles.

## Statuts

- `PLANNED` : validation décrite, aucune implémentation prouvée ;
- `IMPLEMENTED` : code et test existent mais gate final non exécuté ou preuve incomplète ;
- `VERIFIED` : commande sur le commit livré, résultat vert, preuve référencée et revue des exceptions.

Une preuve manuelle indique opérateur, scénario, état avant/après et nettoyage. Un rerun rouge invalide `VERIFIED` jusqu’à résolution. Les flakes sont des échecs : ils sont diagnostiqués, pas relancés jusqu’au vert.

## Résumé minimal JSON

```json
{
  "stage": "03",
  "commit": "<sha>",
  "started_at": "<ISO-8601>",
  "environment": "local-docker|ci|discord-sandbox",
  "commands": ["python scripts/validate_stage.py 03"],
  "result": "PASS|FAIL",
  "requirements": ["REQ-GW-001"],
  "artifacts": ["<relative-path-or-ci-run-url>"],
  "redactions_checked": true
}
```
