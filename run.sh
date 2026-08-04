#!/usr/bin/env bash
# AutoAgent Test — start / restart helper
#
# Usage:
#   ./run.sh                  # restart (kill existing + rebuild SPA + start in background)
#   ./run.sh restart          # same as above
#   ./run.sh start            # start only (no kill)
#   ./run.sh stop             # kill running uvicorn
#   ./run.sh build            # rebuild SPA only
#
# Options:
#   --no-build                skip the SPA rebuild (faster restart for backend-only changes)
#   --reload                  pass --reload to uvicorn (dev mode; auto-reloads on file change)
#   --fg                      run uvicorn in foreground (Ctrl-C to stop); otherwise daemonized
#
# Env vars (with defaults):
#   PYTHON=python3.11         interpreter to use
#   HOST=0.0.0.0              uvicorn host
#   PORT=8000                 uvicorn port
#   LOG_FILE=logs/uvicorn.log where backgrounded uvicorn writes stdout/stderr

set -euo pipefail

cd "$(dirname "$0")"
ROOT=$(pwd)

APP="autoagent.main:app"
# Prefer the project venv's interpreter (deps are installed there via `uv sync`)
# so restarts — including the self-update restart — don't need the caller to
# `source .venv/bin/activate` and don't fall back to a system python missing deps.
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON="python3.11"
  fi
fi
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8000}
LOG_FILE=${LOG_FILE:-$ROOT/logs/uvicorn.log}
PID_PATTERN="uvicorn.*${APP}"

BUILD=true
RELOAD=false
FOREGROUND=false

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

cmd=${1:-restart}
[[ $# -gt 0 ]] && shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build) BUILD=false ;;
    --reload)   RELOAD=true ;;
    --fg)       FOREGROUND=true ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

log() { printf '\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*"; }

stop_uvicorn() {
  local pids
  pids=$(pgrep -f "$PID_PATTERN" || true)
  if [[ -z "$pids" ]]; then
    log "no running uvicorn matching '${PID_PATTERN}'"
    return 0
  fi
  log "stopping uvicorn pid(s): $pids"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    sleep 0.5
    pgrep -f "$PID_PATTERN" >/dev/null || { log "stopped cleanly"; return 0; }
  done
  warn "still alive after SIGTERM, sending SIGKILL"
  pids=$(pgrep -f "$PID_PATTERN" || true)
  # shellcheck disable=SC2086
  [[ -n "$pids" ]] && kill -9 $pids 2>/dev/null || true
}

build_spa() {
  if [[ ! -d web ]]; then
    warn "no web/ directory; skipping SPA build"
    return 0
  fi
  log "building SPA (web/)"
  # Install deps before building — a pull that added a frontend dependency
  # leaves node_modules stale, and `pnpm build` then fails with "Cannot find
  # module ...". --frozen-lockfile is a fast no-op when already in sync.
  (cd web && pnpm install --frozen-lockfile && pnpm build)
}

start_uvicorn() {
  local args=(-m uvicorn --app-dir src "$APP" --host "$HOST" --port "$PORT")
  $RELOAD && args+=(--reload)
  if $FOREGROUND; then
    log "starting uvicorn (foreground) on http://${HOST}:${PORT}"
    exec "$PYTHON" "${args[@]}"
  fi
  mkdir -p "$(dirname "$LOG_FILE")"
  log "starting uvicorn on http://${HOST}:${PORT} (log: ${LOG_FILE})"
  nohup "$PYTHON" "${args[@]}" >>"$LOG_FILE" 2>&1 &
  local pid=$!
  echo "pid=$pid"
  # Give it a moment so an immediate import error surfaces here, not silently.
  sleep 1
  if ! kill -0 "$pid" 2>/dev/null; then
    warn "uvicorn died within 1s. last log lines:"
    tail -20 "$LOG_FILE" >&2 || true
    exit 1
  fi
}

case "$cmd" in
  start)
    $BUILD && build_spa
    start_uvicorn
    ;;
  stop)
    stop_uvicorn
    ;;
  restart)
    stop_uvicorn
    $BUILD && build_spa
    start_uvicorn
    ;;
  build)
    build_spa
    ;;
  *)
    echo "unknown command: $cmd" >&2
    echo "use: start | stop | restart | build (or --help)" >&2
    exit 2
    ;;
esac
