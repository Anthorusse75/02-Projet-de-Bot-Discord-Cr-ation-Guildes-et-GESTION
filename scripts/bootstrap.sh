#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

command -v python >/dev/null
command -v uv >/dev/null
command -v node >/dev/null
command -v docker >/dev/null

uv sync --frozen --python 3.13
(cd frontend && npm ci)
docker compose -f compose.yaml config --quiet
echo "Bootstrap complete. No Discord credential is required for STAGE 01."
