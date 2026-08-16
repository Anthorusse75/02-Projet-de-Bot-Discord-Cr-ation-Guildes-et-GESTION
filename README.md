# Discord Infrastructure Designer

Ce dépôt contient la source de vérité et le dossier d’exécution du projet **Discord Infrastructure Designer**. À ce stade, aucun code fonctionnel du produit n’est présent : le dépôt prépare onze étapes d’implémentation indépendantes et vérifiables.

## Point d’entrée

1. Lire [`AGENTS.md`](AGENTS.md).
2. Lire [`docs/10_implementation/00_GLOBAL_IMPLEMENTATION_CONTRACT.md`](docs/10_implementation/00_GLOBAL_IMPLEMENTATION_CONTRACT.md).
3. Consulter [`docs/10_implementation/00_CURRENT_STATE.md`](docs/10_implementation/00_CURRENT_STATE.md).
4. Ouvrir l’étape active depuis [`docs/10_implementation/00_MASTER_IMPLEMENTATION_INDEX.md`](docs/10_implementation/00_MASTER_IMPLEMENTATION_INDEX.md).

Les deux documents conservés dans [`docs/00_reference/`](docs/00_reference/) sont les sources de vérité fonctionnelle et technique. La matrice [`00_REQUIREMENTS_TRACEABILITY.md`](docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md) relie chaque `REQ-*` à une étape et à des preuves attendues.

## Validation documentaire

Depuis Git Bash sous Windows 11 :

```bash
python scripts/validate_documentation.py
```

La validation contrôle notamment les 11 étapes, la couverture des exigences, les rubriques obligatoires, les liens et chemins locaux, les empreintes des références et l’absence de motifs de secrets évidents.

## État initial

- phase courante : préparation de STAGE 01 ;
- code applicatif : absent par conception ;
- repository GitHub : [`Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION`](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION), publié sur `main` ;
- visibilité : dépôt volontairement public pendant le développement ;
- prochaine étape : STAGE 01, qui n’a pas encore commencé ;
- secrets Discord : aucun requis pour la phase documentaire.
