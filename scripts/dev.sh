#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

docker compose -f compose.yaml up -d --wait
uv run alembic upgrade head
exec uv run uvicorn did.api.main:app --reload --port 8000
