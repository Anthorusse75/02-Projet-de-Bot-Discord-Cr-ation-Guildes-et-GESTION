# ADR — Validation des règles du Policy Engine

- Statut : accepté pour les fondations backend de la Phase 4
- Date : 2026-09-14
- Exigence : `REQ-POL-052`

## Contexte et frontière

Ce lot doit stocker des Policies génériques déclaratives, typées, versionnées et
tenant-safe. Il ne livre ni resolver multi-policy, ni langage d'expressions, ni
compilation vers un Plan, ni mutation Discord. Les policies spécialisées
`message_content_policy.py` et `translation_policy.py` restent des composants
métier distincts et ne sont pas adaptées ou présentées comme ce moteur générique.

Une Policy persistée ne doit accepter ni callback, ni source Python/JavaScript,
ni SQL, ni opérateur fourni par l'utilisateur. L'absence actuelle de resolver ne
doit pas conduire à inventer prématurément un DSL maison.

## Options évaluées

| Option | Maintenance / runtime | Licence | Expressivité et déterminisme | Sécurité / sandboxing | Décision |
|---|---|---|---|---|---|
| Pydantic 2, déjà verrouillé dans le dépôt | Projet actif, Python 3.13 supporté par le paquet actuel | MIT | Schémas fermés, unions discriminées, bornes et normalisation déterministes ; pas de langage d'expressions | Aucun code de Policy n'est exécuté ; `extra="forbid"` refuse les champs libres | **Retenu pour ce lot** |
| `rule-engine` | Bibliothèque Python maintenue, Python ≥ 3.10 | BSD-3-Clause | Langage d'expressions riche et typable ; utile quand un vrai resolver nécessitera calculs/opérateurs | Plus grande surface de grammaire et d'évaluation à borner ; exige un adaptateur et un threat model avant usage | Candidat futur, non requis maintenant |
| `json-rules-engine` | Projet Node.js, donc second runtime dans ce backend Python | ISC | Modèle JSON `all`/`any`, faits et opérateurs extensibles | Pas d'`eval`, mais callbacks/faits/opérateurs extensibles et frontière inter-runtime à sécuriser | Rejeté pour ce lot |
| DSL/AST maison | Maintenance entièrement interne | Interne | Contrôle maximal mais coût élevé de grammaire, compatibilité et tests | Risque de créer un interpréteur insuffisamment audité | Rejeté |

Sources de l'évaluation :

- Pydantic : <https://github.com/pydantic/pydantic/blob/main/pyproject.toml> et
  <https://github.com/pydantic/pydantic/releases> ;
- rule-engine : <https://github.com/zeroSteiner/rule-engine> et
  <https://github.com/zeroSteiner/rule-engine/blob/master/pyproject.toml> ;
- json-rules-engine : <https://github.com/CacheControl/json-rules-engine>.

## Décision

Les fondations utilisent Pydantic 2, dépendance déjà présente, uniquement pour
un registre interne versionné de contrats fermés. Le premier contrat est
`ACCESS_CONTROL` version 1. Ses conditions et effets sont des modèles connus à
la compilation. Tout type, version, opérateur ou champ non enregistré est refusé
à la création, à l'édition et de nouveau avant activation.

Aucun moteur d'expressions externe n'est ajouté et aucun DSL n'est construit
dans ce lot. Ce choix minimise la surface d'attaque et les dépendances tout en
répondant au besoin réel de validation. Il ne préjuge pas du choix du futur
resolver : son entrée est abstraite par `PolicyTypeRegistry` et
`ValidatedPolicyDefinition`, ce qui permet d'introduire ultérieurement un
adaptateur vers `rule-engine` ou une autre bibliothèque sans modifier le format
persisté ni exposer la bibliothèque aux couches API/domaine.

## Garde-fous obligatoires pour une évolution

Avant d'ajouter un moteur d'évaluation, une nouvelle ADR devra démontrer :

1. un ensemble fermé d'opérateurs et de faits, sans import, I/O, réseau, SQL ni
   callback utilisateur ;
2. des limites de taille, profondeur, temps et mémoire ;
3. une évaluation pure et déterministe avec ordre explicite ;
4. une sémantique fail-closed (`UNKNOWN`/`BLOCKED`) pour toute donnée critique
   absente ;
5. une abstraction interne empêchant les objets de bibliothèque de devenir un
   contrat API ou de persistance ;
6. des tests de sécurité, propriété, conflits et ressources adversariales.

## Conséquences

- Les déclarations actuelles sont sérialisables, bornées et non exécutables.
- Le resolver, le preview, les conflits, l'héritage et l'enforcement restent
  explicitement hors de ce lot et ne sont pas revendiqués comme conformes.
- Le registre peut évoluer par ajout explicite d'un couple `(type, version)` ;
  une ancienne version reste lisible et validable sans modification silencieuse.
