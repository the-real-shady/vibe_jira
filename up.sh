#!/usr/bin/env bash
# up.sh — start AgentBoard backend (and optionally frontend)
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="/tmp/agentboard-backend.pid"
LOGFILE="/tmp/agentboard-backend.log"

# ── load .env ────────────────────────────────────────────────────────────────
ENV_FILE="$REPO/backend/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. Copy backend/.env.example and set API_KEY." >&2
  exit 1
fi
set -a; source "$ENV_FILE"; set +a
PORT="${PORT:-8000}"

# ── check if already running ─────────────────────────────────────────────────
if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then
  echo "AgentBoard already running (pid $(cat "$PIDFILE"))"
  echo "Backend → http://localhost:$PORT"
  exit 0
fi

# ── find uvicorn ──────────────────────────────────────────────────────────────
UVICORN="$REPO/.venv/bin/uvicorn"
if [[ ! -x "$UVICORN" ]]; then
  echo "ERROR: venv not found at $REPO/.venv" >&2
  echo "Run: cd backend && pip install -r requirements.txt" >&2
  exit 1
fi

# ── start backend ─────────────────────────────────────────────────────────────
echo "Starting AgentBoard backend…"
cd "$REPO/backend"
nohup "$UVICORN" main:app \
  --host "${HOST:-0.0.0.0}" \
  --port "$PORT" \
  > "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
echo "Backend PID $(cat "$PIDFILE") → http://localhost:$PORT  (log: $LOGFILE)"

# ── wait for ready ────────────────────────────────────────────────────────────
echo -n "Waiting for backend"
for i in $(seq 1 20); do
  if curl -sf "http://localhost:$PORT/health" > /dev/null 2>&1; then
    echo " ready ✓"
    break
  fi
  echo -n "."
  sleep 0.5
done

# ── optional frontend ─────────────────────────────────────────────────────────
FRONTEND_DIR="$REPO/frontend"
FRONTEND_PIDFILE="/tmp/agentboard-frontend.pid"
FRONTEND_LOGFILE="/tmp/agentboard-frontend.log"

if [[ "${1:-}" == "--with-frontend" ]]; then
  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    echo "Installing frontend dependencies…"
    cd "$FRONTEND_DIR" && npm install --silent
  fi
  echo "Starting frontend…"
  cd "$FRONTEND_DIR"
  nohup npm run dev > "$FRONTEND_LOGFILE" 2>&1 &
  echo $! > "$FRONTEND_PIDFILE"
  echo "Frontend PID $(cat "$FRONTEND_PIDFILE") → http://localhost:5173  (log: $FRONTEND_LOGFILE)"
fi

echo ""
echo "AgentBoard is up."
echo "  API docs → http://localhost:$PORT/docs"
if [[ "${1:-}" == "--with-frontend" ]]; then
  echo "  Web UI   → http://localhost:5173"
fi
