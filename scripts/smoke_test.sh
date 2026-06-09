#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -x "$ROOT_DIR/.venv312/bin/python" ]; then
  DEFAULT_PYTHON_BIN="$ROOT_DIR/.venv312/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  DEFAULT_PYTHON_BIN="python3"
else
  DEFAULT_PYTHON_BIN="python"
fi

PYTHON_BIN="${PYTHON_BIN:-$DEFAULT_PYTHON_BIN}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
START_SERVER="${START_SERVER:-auto}"
RUN_COLLECT="${RUN_COLLECT:-true}"
SMOKE_TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-30}"

log() {
  printf '[smoke] %s\n' "$*"
}

fail() {
  printf '[smoke] ERROR %s\n' "$*" >&2
  exit 1
}

fetch() {
  local path="$1"
  "$PYTHON_BIN" - "$BASE_URL$path" <<'PY'
import sys
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

url = sys.argv[1]
try:
    with urlopen(url, timeout=5) as resp:
        body = resp.read(2048).decode("utf-8", "replace")
        print(body)
except HTTPError as exc:
    print(f"HTTP {exc.code}: {url}", file=sys.stderr)
    sys.exit(1)
except URLError as exc:
    print(f"NETWORK {exc.reason}: {url}", file=sys.stderr)
    sys.exit(1)
PY
}

wait_for_api() {
  local deadline=$((SECONDS + SMOKE_TIMEOUT_SECONDS))
  until fetch "/api/health" >/dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      return 1
    fi
    sleep 1
  done
}

log "initialize database"
"$PYTHON_BIN" run.py --init-db

started_by_smoke=false
if ! fetch "/api/health" >/dev/null 2>&1; then
  if [ "$START_SERVER" = "false" ]; then
    fail "server is not reachable at $BASE_URL"
  fi
  log "start background server"
  ./manage.sh start
  started_by_smoke=true
fi

wait_for_api || fail "health endpoint not reachable at $BASE_URL"

if [ "$RUN_COLLECT" = "true" ]; then
  log "run one real collection"
  "$PYTHON_BIN" - <<'PY'
import asyncio
from app.scheduler import collect_job

asyncio.run(collect_job())
PY
fi

log "check health"
health_payload="$(fetch "/api/health")"
printf '%s' "$health_payload" | grep -q '"app"' || fail "health payload missing app status"

log "check current price"
current_payload="$(fetch "/api/price/current")"
printf '%s' "$current_payload" | grep -Eq 'price_cny_per_gram|price' || fail "current price payload missing price"

log "check source quality"
source_payload="$(fetch "/api/price/sources/latest")"
printf '%s' "$source_payload" | grep -Eq 'primary_source|sources' || fail "source payload missing source fields"

log "check indicators"
indicator_payload="$(fetch "/api/analysis/indicators")"
printf '%s' "$indicator_payload" | grep -Eq 'items|status' || fail "indicator payload missing fields"

log "check frontend"
frontend_payload="$(fetch "/")"
printf '%s' "$frontend_payload" | grep -q 'GoldPrice' || fail "frontend HTML did not load"

if [ "$started_by_smoke" = "true" ]; then
  log "server was started by smoke test and is left running for inspection"
fi

log "smoke test passed"
