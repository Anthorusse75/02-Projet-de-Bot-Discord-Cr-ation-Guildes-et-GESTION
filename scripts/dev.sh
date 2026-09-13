#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ ! -f .env.local ]]; then
  echo "[DID] .env.local is required for the live local stack." >&2
  echo "[DID] Copy .env.example to .env.local and configure Discord/OAuth secrets locally (never commit them)." >&2
  exit 2
fi

uv run python - <<'PY'
from did.settings import Settings

settings = Settings()
missing = []
if settings.discord_bot_token is None:
    missing.append("DISCORD_BOT_TOKEN")
if not settings.discord_client_id:
    missing.append("DISCORD_CLIENT_ID")
if settings.discord_client_secret is None:
    missing.append("DISCORD_CLIENT_SECRET")
if not settings.discord_oauth_redirect_uri:
    missing.append("DISCORD_REDIRECT_URI")
if settings.session_secret is None:
    missing.append("SESSION_SECRET")
if settings.oauth_token_encryption_key is None:
    missing.append("OAUTH_TOKEN_ENCRYPTION_KEY")
if missing:
    raise SystemExit("[DID] Missing required local settings: " + ", ".join(missing))

if settings.artifact_encryption_key is None:
    print("[DID] Optional feature warning: ARTIFACT_ENCRYPTION_KEY is not configured; templates/library/clone will be disabled in the UI.")
PY

echo "[DID] Starting PostgreSQL and Redis..."
docker compose -f compose.yaml up -d --wait

echo "[DID] Applying migrations..."
uv run alembic upgrade head

pids=()
cleanup() {
  local status=$?
  trap - INT TERM EXIT
  echo
  echo "[DID] Stopping local processes..."
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  exit "$status"
}
trap cleanup INT TERM EXIT

start() {
  local name=$1
  shift
  echo "[DID] Starting $name..."
  "$@" &
  pids+=("$!")
}

start api uv run uvicorn did.api.main:app --host 127.0.0.1 --port 8001 --reload
start bot uv run python -m did.bot
start worker uv run python -m did.worker
start scheduler uv run python -m did.scheduler

(
  cd frontend
  npm run dev -- --host 127.0.0.1 --port 8000
) &
pids+=("$!")

echo "[DID] Dashboard: http://localhost:8000"
echo "[DID] Backend:   http://127.0.0.1:8001"
echo "[DID] Ctrl+C stops API, bot, worker, scheduler and frontend."

# Fail the stack when one of its required processes exits unexpectedly.
while true; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid"
      exit $?
    fi
  done
  sleep 1
done
