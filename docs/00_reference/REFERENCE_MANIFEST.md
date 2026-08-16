# Manifeste des sources de vérité

Date d’import dans le dépôt : **2026-08-16**.

| Fichier | SHA-256 | Statut |
|---|---|---|
| `01_SPECIFICATIONS_FONCTIONNELLES_DISCORD_INFRA_DESIGNER.md` | `8d7b1bc94909693310e32eef892da6e2bc5b1dcc2d755d34ba484af2fc9f021e` | `SOURCE_OF_TRUTH` |
| `02_ARCHITECTURE_TECHNIQUE_DISCORD_INFRA_DESIGNER.md` | `bfa7d9dc712dbc3e70ecab89b5b747989b530cbb73be7bad47b6820c2c046e71` | `SOURCE_OF_TRUTH` |

Toute modification ultérieure de l’un de ces fichiers exige, avant merge, une nouvelle empreinte, une analyse d’impact sur tous les documents d’implémentation, une mise à jour de `docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md` et une nouvelle exécution de `python scripts/validate_documentation.py`. Une source ne doit pas être reformulée silencieusement : les clarifications sont consignées dans `docs/40_decisions/IMPLEMENTATION_DECISIONS.md`.
