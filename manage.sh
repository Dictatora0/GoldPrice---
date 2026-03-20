#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
PID_FILE="$LOG_DIR/server.pid"
LOG_FILE="$LOG_DIR/server.out"
APP_ENTRY="$ROOT_DIR/run.py"

if [ -x "$ROOT_DIR/.venv312/bin/python" ]; then
  DEFAULT_PYTHON_BIN="$ROOT_DIR/.venv312/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  DEFAULT_PYTHON_BIN="python3"
else
  DEFAULT_PYTHON_BIN="python"
fi

PYTHON_BIN="${PYTHON_BIN:-$DEFAULT_PYTHON_BIN}"
HOST="${HOST:-127.0.0.1}"
DEBUG_FLAG_RAW="${DEBUG:-false}"
PORT_START="${PORT_START:-8000}"
PORT_END="${PORT_END:-8100}"
STARTUP_WAIT_SECONDS="${STARTUP_WAIT_SECONDS:-2}"
STOP_TIMEOUT_SECONDS="${STOP_TIMEOUT_SECONDS:-10}"

if [ -t 1 ]; then
  COLOR_INFO="$(printf '\033[36m')"
  COLOR_WARN="$(printf '\033[33m')"
  COLOR_ERROR="$(printf '\033[31m')"
  COLOR_SUCCESS="$(printf '\033[32m')"
  COLOR_RESET="$(printf '\033[0m')"
else
  COLOR_INFO=""
  COLOR_WARN=""
  COLOR_ERROR=""
  COLOR_SUCCESS=""
  COLOR_RESET=""
fi

timestamp() {
  date "+%Y-%m-%d %H:%M:%S"
}

log_info() {
  printf "%s[%s] INFO  %s%s\n" "$COLOR_INFO" "$(timestamp)" "$*" "$COLOR_RESET"
}

log_warn() {
  printf "%s[%s] WARN  %s%s\n" "$COLOR_WARN" "$(timestamp)" "$*" "$COLOR_RESET"
}

log_error() {
  printf "%s[%s] ERROR %s%s\n" "$COLOR_ERROR" "$(timestamp)" "$*" "$COLOR_RESET" >&2
}

log_success() {
  printf "%s[%s] OK    %s%s\n" "$COLOR_SUCCESS" "$(timestamp)" "$*" "$COLOR_RESET"
}

normalize_bool_flag() {
  local normalized
  normalized="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"

  case "$normalized" in
    true|1|yes|on)
      echo "true"
      ;;
    false|0|no|off)
      echo "false"
      ;;
    *)
      return 1
      ;;
  esac
}

if DEBUG_FLAG="$(normalize_bool_flag "$DEBUG_FLAG_RAW")"; then
  :
else
  log_warn "Invalid DEBUG value '$DEBUG_FLAG_RAW'; defaulting to false."
  DEBUG_FLAG="false"
fi

usage() {
  cat <<EOF
Usage: $0 <command> [options]

Commands:
  start                 Start the server in background mode
  stop                  Stop the server gracefully
  status                Show server status, PID and port information
  restart               Restart the server
  logs [N] [--no-follow]
                        Show latest N lines (default: 80), follow by default
  test [pytest args...] Run tests (default: tests/ -v)
  init-db               Initialize database
  cleanup-backfill      Clean orphan history + malformed signals in a created_at window
  config                Print resolved runtime configuration
  doctor                Run runtime health checks and dependency hints
  help                  Show this help message

Environment variables:
  PYTHON_BIN            Python executable path or command
  HOST                  Bind host (default: 127.0.0.1)
  DEBUG                 DEBUG flag passed to run.py (default: false)
  PORT_START            Port scan start for process detection (default: 8000)
  PORT_END              Port scan end for process detection (default: 8100)
  STARTUP_WAIT_SECONDS  Seconds to wait after startup (default: 2)
  STOP_TIMEOUT_SECONDS  Graceful stop timeout in seconds (default: 10)

Examples:
  $0 start
  $0 logs 200 --no-follow
  $0 test tests/test_api.py -q
  $0 cleanup-backfill --created-after 2026-03-20T20:22:50 --created-before 2026-03-20T20:22:53 --dry-run
  PYTHON_BIN=.venv312/bin/python DEBUG=true $0 restart

Tips:
  - Use '$0 doctor' before first run if startup fails unexpectedly.
  - Use '$0 status' to verify PID/port before running repeated start commands.
  - Use '$0 logs 120 --no-follow' for quick startup failure diagnostics.
EOF
}

resolve_python_bin() {
  if [[ "$PYTHON_BIN" == */* ]]; then
    [ -x "$PYTHON_BIN" ]
    return $?
  fi
  command -v "$PYTHON_BIN" >/dev/null 2>&1
}

is_running() {
  local pid="$1"
  if [ -z "$pid" ]; then
    return 1
  fi
  kill -0 "$pid" >/dev/null 2>&1
}

detect_pid_by_port() {
  ROOT_DIR="$ROOT_DIR" HOST="$HOST" PORT_START="$PORT_START" PORT_END="$PORT_END" "$PYTHON_BIN" - <<'PY' 2>/dev/null
import os
import sys

try:
    from app.port_manager import PortManager
except Exception:
    sys.exit(1)

root = os.environ.get("ROOT_DIR", os.getcwd())
host = os.environ.get("HOST", "127.0.0.1")
start = int(os.environ.get("PORT_START", "8000"))
end = int(os.environ.get("PORT_END", "8100"))

manager = PortManager(project_root=root, host=host)
for port in range(start, end + 1):
    if manager.is_port_in_use(port):
        info = manager.get_process_using_port(port)
        if info and manager.belongs_to_project(info.cmdline):
            print(f"{info.pid} {port}")
            sys.exit(0)
sys.exit(1)
PY
}

ensure_runtime_prerequisites() {
  if ! resolve_python_bin; then
    log_error "Cannot find PYTHON_BIN: $PYTHON_BIN"
    log_error "Hint: set PYTHON_BIN=/path/to/python or create .venv312 first."
    return 1
  fi

  if [ ! -f "$APP_ENTRY" ]; then
    log_error "Entry file not found: $APP_ENTRY"
    return 1
  fi

  mkdir -p "$LOG_DIR"
}

find_running_instance() {
  local pid=""
  local port=""

  if [ -f "$PID_FILE" ]; then
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if is_running "$pid"; then
      echo "$pid"
      return 0
    fi
  fi

  local detected
  detected="$(detect_pid_by_port || true)"
  if [ -n "$detected" ]; then
    read -r pid port <<<"$detected"
    if is_running "$pid"; then
      echo "$pid"
      return 0
    fi
  fi

  return 1
}

start_server() {
  ensure_runtime_prerequisites

  local running_pid
  running_pid="$(find_running_instance || true)"
  if [ -n "$running_pid" ]; then
    log_warn "Server already running (PID $running_pid)."
    log_info "Use '$0 status' or '$0 logs' for details."
    return 0
  fi

  rm -f "$PID_FILE"
  log_info "Starting server..."
  log_info "Python: $PYTHON_BIN"
  log_info "Host: $HOST  Debug: $DEBUG_FLAG"
  log_info "Log file: $LOG_FILE"

  (
    cd "$ROOT_DIR"
    nohup env DEBUG="$DEBUG_FLAG" HOST="$HOST" "$PYTHON_BIN" "$APP_ENTRY" >"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
  )

  sleep "$STARTUP_WAIT_SECONDS"
  local new_pid
  new_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if is_running "$new_pid"; then
    log_success "Server started (PID $new_pid)."
    local detected
    detected="$(detect_pid_by_port || true)"
    if [ -n "$detected" ]; then
      local pid port
      read -r pid port <<<"$detected"
      log_info "Detected listening port: $port"
    fi
    log_info "Next steps: '$0 status' or '$0 logs 120 --no-follow'"
    return 0
  fi

  log_error "Failed to start server."
  if [ -f "$LOG_FILE" ]; then
    log_error "Last 30 log lines:"
    tail -n 30 "$LOG_FILE" >&2 || true
  fi
  rm -f "$PID_FILE"
  return 1
}

stop_server() {
  local pid
  pid="$(find_running_instance || true)"
  if [ -z "$pid" ]; then
    log_info "No running server found."
    rm -f "$PID_FILE"
    return 0
  fi

  log_info "Stopping server (PID $pid)..."
  kill -TERM "$pid" >/dev/null 2>&1 || true

  local deadline=$((SECONDS + STOP_TIMEOUT_SECONDS))
  while is_running "$pid" && [ "$SECONDS" -lt "$deadline" ]; do
    sleep 0.2
  done

  if is_running "$pid"; then
    log_warn "Graceful stop timed out. Sending SIGKILL..."
    kill -KILL "$pid" >/dev/null 2>&1 || true
    sleep 0.2
  fi

  if is_running "$pid"; then
    log_error "Failed to stop PID $pid. Please terminate it manually."
    return 1
  fi

  rm -f "$PID_FILE"
  log_success "Server stopped."
}

status_server() {
  local pid
  pid="$(find_running_instance || true)"
  if [ -z "$pid" ]; then
    log_warn "Server not running."
    log_info "Hint: run '$0 start' to start the service."
    return 1
  fi

  local detected port=""
  detected="$(detect_pid_by_port || true)"
  if [ -n "$detected" ]; then
    read -r _ port <<<"$detected"
  fi

  log_success "Server is running."
  if [ -n "$port" ]; then
    log_info "PID: $pid  Port: $port"
  else
    log_info "PID: $pid"
  fi
  log_info "Process:"
  ps -o pid,ppid,etime,command -p "$pid" || true
  log_info "Log file: $LOG_FILE"
}

show_logs() {
  local lines="80"
  local follow="true"

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --no-follow)
        follow="false"
        shift
        ;;
      *)
        lines="$1"
        shift
        ;;
    esac
  done

  if [ ! -f "$LOG_FILE" ]; then
    log_error "Log file not found: $LOG_FILE"
    log_info "Hint: run '$0 start' first to create logs."
    return 1
  fi

  if ! [[ "$lines" =~ ^[0-9]+$ ]]; then
    log_error "Invalid line count: $lines"
    return 1
  fi

  log_info "Showing last $lines lines from $LOG_FILE"
  if [ "$follow" = "true" ]; then
    log_info "Press Ctrl+C to exit."
    tail -n "$lines" -f "$LOG_FILE"
  else
    tail -n "$lines" "$LOG_FILE"
  fi
}

run_tests() {
  ensure_runtime_prerequisites
  cd "$ROOT_DIR"
  if [ "$#" -eq 0 ]; then
    set -- tests/ -v
  fi
  log_info "Running tests: $PYTHON_BIN -m pytest $*"
  "$PYTHON_BIN" -m pytest "$@"
}

init_database() {
  ensure_runtime_prerequisites
  cd "$ROOT_DIR"
  log_info "Initializing database..."
  env DEBUG="$DEBUG_FLAG" "$PYTHON_BIN" "$APP_ENTRY" --init-db
  log_success "Database initialized successfully."
}

run_cleanup_backfill() {
  ensure_runtime_prerequisites

  local created_after=""
  local created_before=""
  local dry_run="false"

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --created-after)
        shift
        created_after="${1:-}"
        ;;
      --created-before)
        shift
        created_before="${1:-}"
        ;;
      --dry-run)
        dry_run="true"
        ;;
      *)
        log_error "Unknown cleanup-backfill option: $1"
        log_info "Usage: $0 cleanup-backfill --created-after <ISO_DATETIME> --created-before <ISO_DATETIME> [--dry-run]"
        return 1
        ;;
    esac
    shift
  done

  if [ -z "$created_after" ] || [ -z "$created_before" ]; then
    log_error "cleanup-backfill requires --created-after and --created-before"
    log_info "Example: $0 cleanup-backfill --created-after 2026-03-20T20:22:50 --created-before 2026-03-20T20:22:53 --dry-run"
    return 1
  fi

  cd "$ROOT_DIR"
  log_info "Running cleanup-backfill for created_at in [$created_after, $created_before]"
  if [ "$dry_run" = "true" ]; then
    log_info "Dry run enabled; no rows will be deleted."
    env DEBUG="$DEBUG_FLAG" "$PYTHON_BIN" "$APP_ENTRY" \
      --cleanup-backfill \
      --created-after "$created_after" \
      --created-before "$created_before" \
      --dry-run
  else
    env DEBUG="$DEBUG_FLAG" "$PYTHON_BIN" "$APP_ENTRY" \
      --cleanup-backfill \
      --created-after "$created_after" \
      --created-before "$created_before"
  fi
}

show_config() {
  cat <<EOF
Resolved configuration:
  ROOT_DIR             $ROOT_DIR
  APP_ENTRY            $APP_ENTRY
  LOG_DIR              $LOG_DIR
  PID_FILE             $PID_FILE
  LOG_FILE             $LOG_FILE
  PYTHON_BIN           $PYTHON_BIN
  HOST                 $HOST
  DEBUG                $DEBUG_FLAG
  PORT_START           $PORT_START
  PORT_END             $PORT_END
  STARTUP_WAIT_SECONDS $STARTUP_WAIT_SECONDS
  STOP_TIMEOUT_SECONDS $STOP_TIMEOUT_SECONDS
EOF
}

run_doctor() {
  ensure_runtime_prerequisites
  log_info "Running environment checks..."
  log_info "Python executable: $PYTHON_BIN"
  "$PYTHON_BIN" --version || true

  local missing_modules
  missing_modules="$("$PYTHON_BIN" - <<'PY'
import importlib.util
required = [
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "pydantic_settings",
    "pytest",
]
missing = [m for m in required if importlib.util.find_spec(m) is None]
print(",".join(missing))
PY
)"

  if [ -n "$missing_modules" ]; then
    log_warn "Missing Python modules: $missing_modules"
    log_info "Hint: run '$PYTHON_BIN -m pip install -r requirements.txt'"
  else
    log_success "Core Python dependencies look good."
  fi

  if [ -w "$LOG_DIR" ]; then
    log_success "Log directory writable: $LOG_DIR"
  else
    log_warn "Log directory is not writable: $LOG_DIR"
  fi

  if status_server; then
    log_success "Runtime check complete."
  else
    log_info "Server is currently stopped."
    log_info "Hint: run '$0 start' and then '$0 logs 100 --no-follow'."
  fi
}

COMMAND="${1:-help}"
if [ "$#" -gt 0 ]; then
  shift
fi

case "$COMMAND" in
  start)
    start_server "$@"
    ;;
  stop)
    stop_server "$@"
    ;;
  status)
    status_server "$@"
    ;;
  restart)
    stop_server
    start_server
    ;;
  logs)
    show_logs "$@"
    ;;
  test)
    run_tests "$@"
    ;;
  init-db)
    init_database "$@"
    ;;
  cleanup-backfill)
    run_cleanup_backfill "$@"
    ;;
  config)
    show_config
    ;;
  doctor)
    run_doctor
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    log_error "Unknown command: $COMMAND"
    usage
    exit 1
    ;;
esac
