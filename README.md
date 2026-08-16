# Discord Infrastructure Designer

Ce dépôt contient la source de vérité et l’implémentation de **Discord Infrastructure Designer**. STAGE 02 ajoute l’authentification OAuth2 Discord backend, les sessions opaques, la sélection de Guild, l’isolation RLS, le bootstrap d’installation et le RBAC interne. Le runtime Gateway, le cache structurel et les mutations Discord restent hors scope jusqu’aux étapes suivantes.

## Point d’entrée

1. Lire [`AGENTS.md`](AGENTS.md).
2. Lire le [contrat global](docs/10_implementation/00_GLOBAL_IMPLEMENTATION_CONTRACT.md).
3. Consulter [l’état courant](docs/10_implementation/00_CURRENT_STATE.md).
4. Ouvrir l’étape active depuis [l’index d’implémentation](docs/10_implementation/00_MASTER_IMPLEMENTATION_INDEX.md).

Les deux documents de [`docs/00_reference/`](docs/00_reference/) restent les sources de vérité fonctionnelle et technique.

## Prérequis locaux

- Windows 11 avec Git for Windows / Git Bash ;
- Python 3.13 (géré automatiquement par `uv` si nécessaire) ;
- Node.js 24 ;
- Docker Desktop avec Docker Compose ;
- `uv`.

WSL n’est pas requis. Aucun secret Discord n’est nécessaire pour les validations contractuelles et d’intégration. Le profil live explicite utilise uniquement les noms documentés dans `.env.example`; les valeurs réelles restent dans `.env.local`, ignoré par Git.

## Bootstrap et développement

Depuis Git Bash :

```bash
./scripts/bootstrap.sh
docker compose -f compose.yaml up -d --wait
./scripts/db-upgrade.sh
uv run uvicorn did.api.main:app --reload --port 8000
```

Les processus techniques sans connexion Discord démarrent avec :

```bash
uv run python -m did.bot
uv run python -m did.worker
uv run python -m did.scheduler
```

Le frontend démarre avec `cd frontend && npm run dev`. Les endpoints livrés sont `/health/live`, `/health/ready`, le flow `/auth/discord/*`, ainsi que les routes versionnées `me` et `guilds` pour la découverte, la sélection, le bootstrap, la désinstallation et le RBAC. Les Snowflakes Discord sont transportés en chaînes.

## Validation STAGE 02

```bash
docker compose -f compose.test.yaml up -d --wait
python scripts/validate_stage.py 02
# Après configuration volontaire des deux sandboxes et des secrets dans .env.local :
python scripts/validate_stage.py 02 --include-discord-live
docker compose -f compose.test.yaml down --volumes
python scripts/validate_documentation.py
git diff --check
```

Cette validation utilise de vrais services PostgreSQL et Redis, répète les migrations base vide → `0002_stage_02` et `0001_stage_01` → `0002_stage_02`, vérifie RLS A/B, IDOR, sessions/CSRF/OAuth, concurrence et rollback, puis exécute tous les gates backend/frontend et les scans de secrets. Sans l’option live, le rapport Discord porte explicitement le statut `SKIPPED_NOT_VERIFIED`.
