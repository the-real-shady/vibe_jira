#!/usr/bin/env bash
# down.sh — stop AgentBoard backend, frontend, and all codex workers
set -euo pipefail

stopped=0

# ── backend ───────────────────────────────────────────────────────────────────
PIDFILE="/tmp/agentboard-backend.pid"
if [[ -f "$PIDFILE" ]]; then
  PID="$(cat "$PIDFILE")"
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "Stopped backend (pid $PID)"
    stopped=$((stopped + 1))
  else
    echo "Backend pid $PID not running (stale pidfile)"
  fi
  rm -f "$PIDFILE"
else
  # fallback: find by pattern
  PIDS=$(pgrep -f "uvicorn main:app" 2>/dev/null || true)
  if [[ -n "$PIDS" ]]; then
    echo "$PIDS" | xargs kill
    echo "Stopped backend (pids $PIDS)"
    stopped=$((stopped + 1))
  fi
fi

# ── frontend ──────────────────────────────────────────────────────────────────
FRONTEND_PIDFILE="/tmp/agentboard-frontend.pid"
if [[ -f "$FRONTEND_PIDFILE" ]]; then
  PID="$(cat "$FRONTEND_PIDFILE")"
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "Stopped frontend (pid $PID)"
    stopped=$((stopped + 1))
  fi
  rm -f "$FRONTEND_PIDFILE"
fi

# ── codex workers ─────────────────────────────────────────────────────────────
WORKER_PIDS=$(pgrep -f "worker\.py" 2>/dev/null || true)
if [[ -n "$WORKER_PIDS" ]]; then
  echo "$WORKER_PIDS" | xargs kill
  COUNT=$(echo "$WORKER_PIDS" | wc -w | tr -d ' ')
  echo "Stopped $COUNT codex worker(s) (pids $WORKER_PIDS)"
  stopped=$((stopped + COUNT))
fi

if [[ $stopped -eq 0 ]]; then
  echo "Nothing was running."
else
  echo "All done."
fi
