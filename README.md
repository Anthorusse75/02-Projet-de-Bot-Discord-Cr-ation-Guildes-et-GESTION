# Discord Infrastructure Designer

Ce dépôt contient la source de vérité et l’implémentation de **Discord Infrastructure Designer**. STAGE 01 fournit uniquement les fondations techniques ; aucune fonctionnalité Discord, OAuth2 ou dashboard métier n’est simulée.

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

WSL n’est pas requis. Aucun secret ou token Discord n’est nécessaire pour STAGE 01.

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

Le frontend minimal démarre avec `cd frontend && npm run dev`. Les seuls endpoints API sont `/health/live` et `/health/ready`.

## Validation STAGE 01

```bash
docker compose -f compose.test.yaml up -d --wait
python scripts/validate_stage.py 01
docker compose -f compose.test.yaml down --volumes
python scripts/validate_documentation.py
git diff --check
```

Cette validation utilise de vrais services PostgreSQL et Redis, applique Alembic jusqu’à `0001_stage_01`, vérifie RLS A/B et fail-closed, réutilise explicitement une connexion du pool, puis exécute tous les gates backend/frontend et le scan de secrets.
