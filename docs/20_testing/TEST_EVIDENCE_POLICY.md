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

## Conservation et identifiants de run

- `<run-id>` est immuable et non ambigu. Localement, le format par défaut est
  `<UTC avec microsecondes>-<SHA court>-<environnement>` ; en CI il est
  `gha-<run-id>-attempt-<run-attempt>-<SHA complet>`.
- Un répertoire déjà présent provoque un échec : aucune preuve précédente n’est écrasée.
- Les répertoires de runs locaux sont ignorés par Git. Les JUnit bruts peuvent contenir hostname,
  chemins ou timestamps de machine et ne sont jamais committés.
- La CI publie le répertoire du run comme artefact GitHub Actions nommé avec stage, SHA, run ID et
  tentative. `summary.json` contient aussi cet identifiant d’artefact.
- Le handoff conserve un run représentatif et son SHA testé. Pour le HEAD courant d’une PR ouverte,
  l’onglet Checks de la PR est la source de vérité ; le handoff n’est pas modifié après chaque run,
  afin d’éviter une boucle commit → CI → nouveau run ID → commit.
- Après merge seulement, l’étape suivante recopie dans son PRECHECK le SHA final intégré et vérifie
  les checks associés. Cette convention ne transforme pas un ancien run représentatif en preuve du
  HEAD courant.

## Statuts

- `PLANNED` : validation décrite, aucune implémentation prouvée ;
- `IMPLEMENTED` : code et test existent mais gate final non exécuté ou preuve incomplète ;
- `VERIFIED` : commande sur le commit livré, résultat vert, preuve référencée et revue des exceptions.

Une preuve manuelle indique opérateur, scénario, état avant/après et nettoyage. Un rerun rouge invalide `VERIFIED` jusqu’à résolution. Les flakes sont des échecs : ils sont diagnostiqués, pas relancés jusqu’au vert.

## Résumé minimal JSON

```json
{
  "stage": "03",
  "run_id": "<immutable-run-id>",
  "commit": "<sha>",
  "repository_dirty": false,
  "started_at": "<ISO-8601>",
  "generated_at": "<ISO-8601>",
  "environment": "local-docker|ci|discord-sandbox",
  "commands": ["python scripts/validate_stage.py 03"],
  "result": "PASS|FAIL",
  "requirements": ["REQ-GW-001"],
  "artifacts": ["<relative-path-or-ci-run-url>"],
  "redactions_checked": true
}
```

Le résumé réel ajoute `gates`, une liste détaillée contenant pour chaque gate son nom, sa commande,
son répertoire de travail relatif, sa durée, son code retour et son statut. Un environnement autre
que les trois profils usuels est permis uniquement comme identifiant explicite non sensible.

## Preuve live mutative STAGE 05

Un preflight fail-closed à zéro mutation est une preuve de sécurité, pas une preuve du moteur mutatif.
Il porte `BLOCKED_CAPABILITY_CONFIGURATION` et invalide tout statut live `PASS`. Le PASS live STAGE 05
exige le plan complet, le crash-window avec un seul CREATE, le binding symbolique récupéré, la
vérification ciblée et le cleanup par plan sans fixture préfixée restante. Le JSON suivi ne contient
ni token ni identifiant Discord; les données brutes restent dans les artifacts locaux ignorés.
