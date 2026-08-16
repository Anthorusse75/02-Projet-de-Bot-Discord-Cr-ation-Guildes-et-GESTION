#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

cleanup() {
  docker compose -f compose.test.yaml down --volumes
}
trap cleanup EXIT

docker compose -f compose.test.yaml up -d --wait
python scripts/validate_stage.py 01
