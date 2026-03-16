#!/usr/bin/env bash
# init-worker.sh — set up a work directory and start a codex worker there
#
# Usage:
#   ./init-worker.sh <work-dir> [options]
#
# Options:
#   --agent-id   <id>       Agent identifier, e.g. codex-worker-1  (default: codex-worker-1)
#   --project    <slug>     AgentBoard project slug                 (default: derived from dir name)
#   --api-key    <key>      AgentBoard API key                      (default: from backend/.env)
#   --host       <url>      AgentBoard host                         (default: http://localhost:8000)
#   --proxy-port <port>     Fixed MCP proxy port                    (default: random)
#   --poll       <secs>     Task poll interval                      (default: 20)
#   --capabilities <list>   Comma-separated capabilities            (default: python,bash,code)
#   --no-worker             Generate files only, don't start worker
#
# Example:
#   ./init-worker.sh ~/my-project --agent-id coder-1 --project my-project
#
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"

# ── defaults ──────────────────────────────────────────────────────────────────
WORK_DIR=""
AGENT_ID="codex-worker-1"
PROJECT=""
HOST="http://localhost:8000"
PROXY_PORT="0"
POLL="20"
CAPABILITIES="python,bash,code"
NO_WORKER=false

# ── parse args ────────────────────────────────────────────────────────────────
if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <work-dir> [--agent-id ID] [--project SLUG] [--api-key KEY] ..." >&2
  exit 1
fi

WORK_DIR="$1"; shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent-id)    AGENT_ID="$2";      shift 2 ;;
    --project)     PROJECT="$2";       shift 2 ;;
    --api-key)     API_KEY="$2";       shift 2 ;;
    --host)        HOST="$2";          shift 2 ;;
    --proxy-port)  PROXY_PORT="$2";    shift 2 ;;
    --poll)        POLL="$2";          shift 2 ;;
    --capabilities) CAPABILITIES="$2"; shift 2 ;;
    --no-worker)   NO_WORKER=true;     shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ── load API key from .env if not passed ──────────────────────────────────────
if [[ -z "${API_KEY:-}" ]]; then
  ENV_FILE="$REPO/backend/.env"
  if [[ -f "$ENV_FILE" ]]; then
    API_KEY="$(grep -E '^API_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'")"
  fi
fi
if [[ -z "${API_KEY:-}" ]]; then
  echo "ERROR: --api-key not set and API_KEY not found in backend/.env" >&2
  exit 1
fi

# ── derive project slug from directory name if not given ─────────────────────
if [[ -z "$PROJECT" ]]; then
  PROJECT="$(basename "$WORK_DIR" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')"
fi

# ── create work directory ─────────────────────────────────────────────────────
mkdir -p "$WORK_DIR"
WORK_DIR="$(cd "$WORK_DIR" && pwd)"
echo "Work directory: $WORK_DIR"

# ── register project in AgentBoard ───────────────────────────────────────────
echo "Registering project '$PROJECT' in AgentBoard ($HOST)…"
RESPONSE=$(curl -sf -X POST "$HOST/api/v1/projects/" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$PROJECT\"}" 2>/dev/null || true)

if [[ -z "$RESPONSE" ]]; then
  # Project may already exist — fetch it
  RESPONSE=$(curl -sf "$HOST/api/v1/projects/$PROJECT" \
    -H "X-API-Key: $API_KEY" 2>/dev/null || true)
fi

if [[ -z "$RESPONSE" ]]; then
  echo "WARNING: Could not reach AgentBoard at $HOST — project not registered." >&2
  echo "Make sure the server is running: ./up.sh" >&2
else
  SLUG=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('slug','?'))" 2>/dev/null || echo "?")
  echo "Project slug: $SLUG"
  PROJECT="$SLUG"
fi

# ── write AGENTS.md ───────────────────────────────────────────────────────────
AGENTS_FILE="$WORK_DIR/AGENTS.md"
TEMPLATE="$REPO/prompt_templates/codex-agent.md"

if [[ -f "$AGENTS_FILE" ]]; then
  echo "AGENTS.md already exists — skipping."
else
  if [[ ! -f "$TEMPLATE" ]]; then
    echo "ERROR: template not found at $TEMPLATE" >&2
    exit 1
  fi

  # Build capabilities array string: "python,bash,code" → ["python","bash","code"]
  CAP_ARRAY=$(echo "$CAPABILITIES" | python3 -c "
import sys
caps = [c.strip() for c in sys.stdin.read().split(',') if c.strip()]
print('\"' + '\",\"'.join(caps) + '\"')
")

  sed \
    -e "s|{{ agent_name }}|$AGENT_ID|g" \
    -e "s|{{ project_name }}|$PROJECT|g" \
    -e "s|{{ capabilities (e.g. python, backend, testing, infrastructure) }}|$CAPABILITIES|g" \
    -e "s|\[{{ capabilities }}\]|[$CAP_ARRAY]|g" \
    "$TEMPLATE" \
    | grep -v '^# Codex / Continue / Cursor Agent — System Prompt Template' \
    | grep -v '^Copy this into' \
    > "$AGENTS_FILE"

  echo "Created AGENTS.md"
fi

# ── summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Initialised:"
echo "  Project   : $PROJECT"
echo "  Agent ID  : $AGENT_ID"
echo "  Work dir  : $WORK_DIR"
echo "  AGENTS.md : $AGENTS_FILE"
echo ""

if $NO_WORKER; then
  echo "Worker not started (--no-worker)."
  echo "To start it manually:"
  echo "  python3 $REPO/tools/codex-worker/worker.py \\"
  echo "    --project $PROJECT --api-key \$API_KEY --agent-id $AGENT_ID \\"
  echo "    --work-dir $WORK_DIR --host $HOST --proxy-port $PROXY_PORT --poll $POLL"
  exit 0
fi

# ── find python ───────────────────────────────────────────────────────────────
PYTHON="${PYTHON:-}"
for candidate in python3 python; do
  if command -v "$candidate" &>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "ERROR: python3 not found in PATH" >&2
  exit 1
fi

# ── start codex worker ────────────────────────────────────────────────────────
WORKER_LOG="$WORK_DIR/worker.log"
WORKER_PIDFILE="/tmp/agentboard-worker-${PROJECT}-${AGENT_ID}.pid"

if [[ -f "$WORKER_PIDFILE" ]] && kill -0 "$(cat "$WORKER_PIDFILE")" 2>/dev/null; then
  echo "Worker already running (pid $(cat "$WORKER_PIDFILE"))."
  exit 0
fi

echo "Starting codex worker…"
nohup "$PYTHON" "$REPO/tools/codex-worker/worker.py" \
  --project "$PROJECT" \
  --api-key  "$API_KEY" \
  --agent-id "$AGENT_ID" \
  --work-dir "$WORK_DIR" \
  --host     "$HOST" \
  --proxy-port "$PROXY_PORT" \
  --poll     "$POLL" \
  > "$WORKER_LOG" 2>&1 &

WORKER_PID=$!
echo $WORKER_PID > "$WORKER_PIDFILE"

echo "Worker PID $WORKER_PID"
echo "Worker log: $WORKER_LOG"
echo ""

# ── show startup output ───────────────────────────────────────────────────────
sleep 3
echo "--- worker.log (last 10 lines) ---"
tail -10 "$WORKER_LOG" 2>/dev/null || true
