#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT_DIR/logs/server.pid"
LOG_FILE="$ROOT_DIR/logs/server.out"
PYTHON_BIN="${PYTHON_BIN:-python}"
HOST="${HOST:-127.0.0.1}"
DEBUG_FLAG="${DEBUG:-false}"
PORT_START="${PORT_START:-8000}"
PORT_END="${PORT_END:-8100}"

usage() {
  cat <<EOF
Usage: $0 {start|stop|status|restart|logs|test|init-db}

Commands:
  start       Start the server
  stop        Stop the server
  status      Check server status
  restart     Restart the server
  logs        Show server logs (tail -f)
  test        Run all tests
  init-db     Initialize database

Environment variables:
  PYTHON_BIN  Python executable (default: python)
  HOST        Bind host (default: 127.0.0.1)
  DEBUG       DEBUG flag (default: false)
EOF
}

is_running() {
  local pid="$1"
  if [ -z "$pid" ]; then
    return 1
  fi
  if kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

detect_pid_by_port() {
  "$PYTHON_BIN" - <<'PY' 2>/dev/null
import os
import sys

try:
    from app.port_manager import PortManager
except Exception:
    sys.exit(1)

root = os.getcwd()
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

start_server() {
  mkdir -p "$ROOT_DIR/logs"

  if [ -f "$PID_FILE" ]; then
    local existing_pid
    existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if is_running "$existing_pid"; then
      echo "Server already running (PID $existing_pid)."
      return 0
    fi
    rm -f "$PID_FILE"
  fi

  echo "Starting server..."
  (
    cd "$ROOT_DIR"
    nohup env DEBUG="$DEBUG_FLAG" HOST="$HOST" "$PYTHON_BIN" run.py > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
  )

  sleep 1
  local new_pid
  new_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if is_running "$new_pid"; then
    echo "Server started (PID $new_pid)."
    echo "Log: $LOG_FILE"
    return 0
  fi

  echo "Failed to start server. Check log: $LOG_FILE"
  rm -f "$PID_FILE"
  return 1
}

stop_server() {
  if [ -f "$PID_FILE" ]; then
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if is_running "$pid"; then
      echo "Stopping server (PID $pid)..."
      kill -TERM "$pid" >/dev/null 2>&1 || true

      local deadline=$((SECONDS + 10))
      while is_running "$pid" && [ $SECONDS -lt $deadline ]; do
        sleep 0.2
      done

      if is_running "$pid"; then
        echo "Server did not stop within timeout. Please stop manually."
        return 1
      fi
      echo "Server stopped."
    fi
    rm -f "$PID_FILE"
    return 0
  fi

  # No PID file; try to detect by ports using PortManager
  local detected
  detected="$(detect_pid_by_port || true)"
  if [ -n "$detected" ]; then
    local pid port
    read -r pid port <<<"$detected"
    if is_running "$pid"; then
      echo "Stopping server (PID $pid, port $port)..."
      kill -TERM "$pid" >/dev/null 2>&1 || true
      echo "Stop signal sent."
      return 0
    fi
  fi

  # Fallback: try to find a matching process by path
  local matches
  matches="$(pgrep -f "run.py" || true)"
  if [ -z "$matches" ]; then
    echo "No running server found."
    return 0
  fi

  echo "Stopping server instances from run.py: $matches"
  for pid in $matches; do
    if is_running "$pid"; then
      kill -TERM "$pid" >/dev/null 2>&1 || true
    fi
  done
  echo "Stop signal sent."
}

status_server() {
  if [ -f "$PID_FILE" ]; then
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if is_running "$pid"; then
      echo "Server running (PID $pid)."
      return 0
    fi
    echo "PID file exists but process not running."
    return 1
  fi

  local detected
  detected="$(detect_pid_by_port || true)"
  if [ -n "$detected" ]; then
    local pid port
    read -r pid port <<<"$detected"
    echo "Server running (PID $pid) on port $port without PID file."
    return 0
  fi

  local matches
  matches="$(pgrep -f "run.py" || true)"
  if [ -n "$matches" ]; then
    echo "Server running (PID(s) $matches) without PID file."
    return 0
  fi

  echo "Server not running."
  return 1
}

show_logs() {
  if [ ! -f "$LOG_FILE" ]; then
    echo "Log file not found: $LOG_FILE"
    return 1
  fi
  echo "Showing logs from: $LOG_FILE"
  echo "Press Ctrl+C to exit"
  tail -f "$LOG_FILE"
}

run_tests() {
  echo "Running tests..."
  cd "$ROOT_DIR"
  "$PYTHON_BIN" -m pytest tests/ -v
}

init_database() {
  echo "Initializing database..."
  cd "$ROOT_DIR"
  "$PYTHON_BIN" run.py --init-db
  echo "Database initialized successfully."
}

case "${1:-}" in
  start)
    start_server
    ;;
  stop)
    stop_server
    ;;
  restart)
    stop_server
    start_server
    ;;
  status)
    status_server
    ;;
  logs)
    show_logs
    ;;
  test)
    run_tests
    ;;
  init-db)
    init_database
    ;;
  *)
    usage
    exit 1
    ;;
esac
