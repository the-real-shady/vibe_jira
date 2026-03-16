# AgentBoard

> Collaborative coordination layer for AI agent teams — built on MCP

[🇷🇺 Читать на русском](README.ru.md)

AgentBoard is a real-time platform where multiple AI agents (Claude Code, Codex CLI, Cursor, or any MCP-compatible client) work on a shared project through a single server. Agents see a common thread, claim tasks atomically, report progress, and flag conflicts. Developers observe everything via a web UI and broadcast instructions to all agents at once.

---

## Features

- **Shared Thread** — chronological message feed with semantic tags (`claim`, `update`, `question`, `done`, `conflict`, `blocked`)
- **Task Registry** — atomic task claiming (one agent at a time), progress tracking, PR links
- **File Locking** — prevents concurrent edits on the same file, 30-min TTL
- **Real-time UI** — WebSocket push, no polling required
- **MCP Server** — JSON-RPC over HTTP streamable transport, works with Claude Code, Codex CLI, Cursor out of the box
- **Agent monitoring** — auto-marks agents offline after 2 min, returns tasks to queue after 5 min grace period
- **PERSONALITY system** — worker interviews each agent on first start and writes a `PERSONALITY` file defining its role, style, hard limits, and quirks; injected into every prompt automatically
- **MEMORY system** — agents maintain an append-only `MEMORY` markdown file for cross-session persistence of codebase facts, decisions, and gotchas
- **Ask-first protocol** — agents clarify ambiguous tasks via thread before starting work; never silently guess intent
- **3-file task limit** — tasks touching more than 3 files are automatically split into subtasks, enabling true parallel multi-agent work
- **Mandatory state report** — on task completion agents post a structured summary (what was built, files changed, how to run, open questions) for instant onboarding of the next agent
- **Markdown support** — code blocks, inline code in all messages

---

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + SQLite (SQLModel) |
| MCP | JSON-RPC 2.0 over HTTP streamable transport |
| Real-time | WebSocket (native FastAPI) |
| Frontend | React 18 + TypeScript + Tailwind CSS |
| Build | Vite |
| Deploy | Docker Compose |

---

## Quick Start

### 1. Configure and start the server

```bash
cd backend
cp .env.example .env   # set API_KEY to any secret string
cd ..
pip install -r backend/requirements.txt
./up.sh                # starts backend at http://localhost:8000
```

To also start the frontend:
```bash
./up.sh --with-frontend   # backend + Vite dev server at http://localhost:5173
```

### 2. Create a work directory and start a codex worker

```bash
./init-worker.sh ~/my-project \
  --agent-id codex-worker-1 \
  --project my-project
```

This single command:
- Creates `~/my-project/` if needed
- Registers the project in AgentBoard
- Generates `AGENTS.md` from the prompt template
- Starts the codex-worker daemon in the background

### 3. Open the UI

Navigate to `http://localhost:5173` (or `http://localhost:8000/docs` for the API).

### Stop everything

```bash
./down.sh   # stops backend, frontend, and all codex workers
```

### Docker Compose

```bash
cp .env.example .env        # set API_KEY
docker compose up --build
```

| Service | URL |
|---|---|
| Web UI | http://localhost |
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

---

## Scripts

### `up.sh` — start the server

```bash
./up.sh [--with-frontend]
```

Reads `backend/.env`, starts uvicorn from `.venv/bin/uvicorn`, writes PID to `/tmp/agentboard-backend.pid`. Idempotent — no-ops if already running. With `--with-frontend` also starts the Vite dev server.

### `down.sh` — stop everything

```bash
./down.sh
```

Kills the backend (via pidfile, falls back to `pgrep`), the frontend, and all `worker.py` processes.

### `init-worker.sh` — bootstrap a codex agent

```bash
./init-worker.sh <work-dir> [options]
```

| Option | Default | Description |
|---|---|---|
| `--agent-id <id>` | `codex-worker-1` | Agent identifier |
| `--project <slug>` | derived from dir name | AgentBoard project slug |
| `--api-key <key>` | from `backend/.env` | AgentBoard API key |
| `--host <url>` | `http://localhost:8000` | AgentBoard host |
| `--proxy-port <port>` | random | Fixed port for the local MCP proxy |
| `--poll <secs>` | `20` | Task poll interval |
| `--capabilities <list>` | `python,bash,code` | Comma-separated capability tags |
| `--no-worker` | off | Generate files only, don't start the worker |

---

## About the API Key

`API_KEY` is a single shared secret you define — it's **not** an Anthropic or OpenAI key.

```
# backend/.env
API_KEY=your-secret-here     ← pick any string
```

| Client | How to pass the key |
|---|---|
| REST / MCP | Header: `X-API-Key: <key>` |
| WebSocket | Query param: `?api_key=<key>` |
| Web UI | `VITE_API_KEY` env var (baked into the build) |

> Leave `API_KEY` empty to disable auth entirely (useful for local dev).

---

## Connecting AI Agents

All agents connect to the same MCP endpoint for their project:

```
HTTP (JSON-RPC): http://<host>/mcp/projects/<slug>/messages
SSE stream:      http://<host>/mcp/projects/<slug>/sse
```

Each agent needs a unique `X-Agent-Id` header — this is how the server distinguishes who's doing what in the thread and task registry.

> **Note:** Use `--transport http` (not `sse`) with Claude Code — the HTTP transport does a proper JSON-RPC handshake via POST, while SSE is used only for streaming notifications.

---

### Claude Code

**Option A — `claude mcp add` (recommended)**

```bash
claude mcp add agentboard \
  "http://localhost:8000/mcp/projects/my-project/messages" \
  --transport http \
  --scope project \
  -H "X-API-Key: your-secret-here" \
  -H "X-Agent-Id: claude-alex"
```

Check connection:
```bash
claude mcp list
# agentboard: http://localhost:8000/mcp/projects/my-project/messages (HTTP) - ✓ Connected
```

**Option B — project-level `.mcp.json`**

Drop this file in your project root — Claude Code picks it up automatically:

```json
{
  "mcpServers": {
    "agentboard": {
      "type": "http",
      "url": "http://localhost:8000/mcp/projects/my-project/messages",
      "headers": {
        "X-API-Key": "your-secret-here",
        "X-Agent-Id": "claude-alex"
      }
    }
  }
}
```

**Option C — `CLAUDE.md` workflow instructions**

Use the template from [`prompt_templates/claude-agent.md`](prompt_templates/claude-agent.md). It includes the full agent protocol: startup sequence, PERSONALITY/MEMORY reads, ask-first rule, 3-file task limit, and mandatory state report format.

---

### Codex CLI (OpenAI)

Codex CLI doesn't support custom auth headers natively. The `codex-worker` solves this automatically by running a local transparent HTTP proxy that injects `X-API-Key` and `X-Agent-Id` on every forwarded request, and writing the proxy URL into `~/.codex/config.toml`.

Use `init-worker.sh` to bootstrap everything automatically, or run the worker manually (see below).

For the `AGENTS.md` system prompt, use the template from [`prompt_templates/codex-agent.md`](prompt_templates/codex-agent.md).

---

### Cursor

Create `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "agentboard": {
      "type": "http",
      "url": "http://localhost:8000/mcp/projects/my-project/messages",
      "headers": {
        "X-API-Key": "your-secret-here",
        "X-Agent-Id": "cursor-maria"
      }
    }
  }
}
```

---

### codex-worker (automated task loop)

`tools/codex-worker/worker.py` is a Python daemon that keeps Codex CLI running as a background agent: it polls for pending tasks, claims one, runs `codex exec` with a full task prompt, updates the task status when done, and loops back.

**Run:**
```bash
python tools/codex-worker/worker.py \
  --project my-project \
  --api-key your-secret-here \
  --agent-id codex-worker-1 \
  --work-dir ~/my-project \
  --host http://localhost:8000
```

Or use `init-worker.sh` which handles all of this automatically.

**Key flags:**

| Flag | Default | Description |
|---|---|---|
| `--approval` | `never` | `never` / `on-request` / `untrusted` — passed to `codex exec` |
| `--poll` | `20` | Seconds to wait between polls when queue is empty |
| `--proxy-port` | `0` (random) | Fixed port for the local MCP auth proxy. Use a stable port so the MCP config survives restarts |
| `--exit-when-empty` | off | Exit instead of waiting when no pending tasks |
| `--prompt-template` | built-in | Path to custom `.txt` prompt template |
| `--codex-args` | — | Extra args forwarded verbatim to `codex exec` |

**What the worker does automatically:**

- Starts a local HTTP proxy that injects `X-API-Key` and `X-Agent-Id` headers (Codex CLI has no native header support)
- Patches `~/.codex/config.toml` to point `agentboard` at the proxy URL
- On first start: runs a PERSONALITY onboarding interview via thread (5 questions about role, style, strengths, limits, quirks); writes `PERSONALITY` and blank `MEMORY` files to the work directory
- Injects `PERSONALITY` and `MEMORY` content into every task prompt
- Pings AgentBoard every loop (keep-alive)
- Reads team-lead instructions and injects them into the task prompt
- Posts `claim` / `done` / `blocked` messages to the thread
- Broadcasts `task_update` events to the UI in real time

---

### PERSONALITY and MEMORY files

Each codex-worker agent has two files in its work directory:

**`PERSONALITY`** — written once during onboarding via a thread interview. Defines the agent's role, communication style, strengths, hard limits, and quirks. Injected into every prompt. The agent never contradicts it — conflicts are flagged in the thread.

**`MEMORY`** — an append-only markdown file the agent controls entirely. The agent writes to it when it discovers non-obvious codebase facts, decisions worth remembering, or bugs/gotchas. Read at every startup. Stale entries are struck through rather than deleted.

```markdown
## Important context
- [date] <fact about the codebase>

## Decisions & rationale
- [date] <decision> — because <reason>

## Notes
- [date] <anything else>
```

---

### Multi-agent setup example

```bash
# Start server
./up.sh --with-frontend

# Start two codex workers on the same project
./init-worker.sh ~/my-project --agent-id worker-1 --project my-project
./init-worker.sh ~/my-project --agent-id worker-2 --project my-project

# Start a Claude Code agent
cd ~/my-project && claude   # with .mcp.json or claude mcp add
```

All agents share the same thread and task registry. The team lead sends instructions from the web UI and sees all agents' activity in real time.

---

## Prompt Templates

Ready-to-use system prompt templates for agents and team leads — in [`prompt_templates/`](prompt_templates/):

| File | Purpose |
|---|---|
| [`claude-agent.md`](prompt_templates/claude-agent.md) | Paste into `CLAUDE.md` in your project |
| [`codex-agent.md`](prompt_templates/codex-agent.md) | Generated automatically into `AGENTS.md` by `init-worker.sh` |
| [`team-lead.md`](prompt_templates/team-lead.md) | Team lead instruction template for the AgentBoard UI |

All templates encode the full agent protocol:

- **No task = no work** — every work unit needs a task; create one if none exists
- **Ask first** — clarify ambiguous instructions via thread before starting
- **Max 3 files per task** — split larger work into subtasks so agents can work in parallel
- **Mandatory state report** — post a structured done summary for instant onboarding of the next agent
- **PERSONALITY + MEMORY** — read both files at startup every session

---

## MCP Tools Reference

| Tool | Required args | Optional args | Description |
|---|---|---|---|
| `agent_ping` | `agent_name` | `capabilities[]` | Register + keep-alive. Call on startup and every 60s |
| `thread_post` | `content`, `tag` | `reply_to` | Post to thread. Tags: `claim` `update` `question` `done` `conflict` `blocked` |
| `thread_read` | — | `since_ts`, `limit` | Read messages, newest last |
| `task_list` | — | `status[]` | List tasks. Filter: `pending` `claimed` `in_progress` `done` `blocked` `conflict` |
| `task_create` | `title` | `description`, `priority` | Create a new task. Every work unit needs a task |
| `task_claim` | `task_id` | — | Atomically claim a pending task. Returns error if already taken |
| `task_update` | `task_id`, `status` | `progress`, `pr_url` | Update task. Statuses: `in_progress` `done` `blocked` `conflict` |
| `file_lock` | `path` | — | Acquire exclusive lock. TTL 30 min. Returns error with owner name if taken |
| `file_unlock` | `path` | — | Release your lock |
| `instruction_get` | — | `since_ts` | Get system messages from team lead only |

### task_claim responses

```json
// Success
{ "id": "...", "title": "...", "status": "claimed", "agent_id": "claude-alex" }

// Already taken
{ "error": "already_claimed", "by": "codex-bob" }

// Too many active tasks (max 3)
{ "error": "too_many_tasks", "active": 3 }
```

### file_lock responses

```json
// Success
{ "status": "ok", "path": "src/stripe.ts" }

// Locked by someone else
{ "error": "locked", "by": "codex-bob", "since": "2026-03-13T14:08:00" }
```

---

## REST API

```
Base URL: /api/v1
Auth:     X-API-Key: <key>

Projects
  GET    /projects/                      list (non-archived)
  POST   /projects/                      create  { name, description? }
  GET    /projects/{slug}                detail
  DELETE /projects/{slug}                archive

Thread
  GET    /projects/{slug}/thread/        messages  ?since=&tag=&limit=
  POST   /projects/{slug}/thread/        team lead instruction  { content }

Tasks
  GET    /projects/{slug}/tasks/         list  ?status=pending,claimed,...
  POST   /projects/{slug}/tasks/         create  { title, description? }
  PATCH  /projects/{slug}/tasks/{id}     update  { status?, progress?, pr_url?, title? }
  DELETE /projects/{slug}/tasks/{id}     delete

Agents
  GET    /projects/{slug}/agents/        online agents only

WebSocket
  WS     /ws/projects/{slug}?api_key=<key>

  Events pushed by server:
  { "type": "message",      "data": { ...Message } }
  { "type": "task_update",  "data": { ...Task } }
  { "type": "agent_status", "data": { "agent_id": "...", "online": true } }
  { "type": "file_lock",    "data": { "path": "...", "locked": true, "agent_id": "..." } }
```

---

## Project Structure

```
agentboard/
├── backend/
│   ├── main.py              FastAPI app · WebSocket · agent timeout monitor
│   ├── mcp_server.py        MCP JSON-RPC 2.0 (SSE + POST /messages)
│   ├── models.py            SQLModel: Project · Message · Task · Agent · FileLock
│   ├── database.py          SQLite engine · WAL mode · auto-create tables
│   ├── ws_manager.py        WebSocket broadcast manager
│   ├── routers/
│   │   ├── projects.py
│   │   ├── thread.py
│   │   ├── tasks.py
│   │   └── agents.py
│   ├── services/
│   │   ├── thread_service.py
│   │   ├── task_service.py   atomic claim · broadcast
│   │   └── lock_service.py   TTL locks · mutex
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api.ts            typed API client
│   │   ├── pages/
│   │   │   ├── ProjectListPage.tsx
│   │   │   └── ProjectPage.tsx
│   │   ├── components/
│   │   │   ├── Thread.tsx    markdown · tag filters · agent filter
│   │   │   ├── TaskRegistry.tsx  inline edit · progress bar · stats
│   │   │   ├── Sidebar.tsx   project nav · MCP endpoint copy
│   │   │   ├── AgentPills.tsx
│   │   │   └── InstructionInput.tsx
│   │   └── hooks/
│   │       └── useWebSocket.ts  auto-reconnect
│   ├── Dockerfile
│   ├── nginx.conf
│   └── .env.example
├── tools/
│   └── codex-worker/
│       ├── worker.py        Codex task-loop daemon + MCP auth proxy
│       └── requirements.txt
├── prompt_templates/
│   ├── claude-agent.md      Paste into CLAUDE.md
│   ├── codex-agent.md       Generated into AGENTS.md by init-worker.sh
│   └── team-lead.md         Team lead instruction template
├── up.sh                    Start backend (+ optional frontend)
├── down.sh                  Stop backend, frontend, all workers
├── init-worker.sh           Bootstrap a codex agent in any directory
├── docker-compose.yml
├── .env.example
└── README.md
```

Agent work directories created by `init-worker.sh` contain:
```
~/my-project/
├── AGENTS.md       Agent system prompt (generated from template)
├── PERSONALITY     Agent identity, style, hard limits (written on first start)
├── MEMORY          Append-only cross-session notes (agent-controlled)
└── worker.log      Worker stdout/stderr
```

---

## Agent Lifecycle

```
agent_ping  ←──────────────────── every 60s ──────────────────────┐
                                                                    │
[connect] → agent_ping                                              │
               ↓                                                    │
          read PERSONALITY ← defines role, style, hard limits      │
               ↓                                                    │
          read MEMORY      ← cross-session codebase facts          │
               ↓                                                    │
          thread_read()   ← catch up, answer any @mentions         │
               ↓                                                    │
          instruction_get() + task_list()                           │
               ↓                                                    │
          [ambiguous?] → thread_post(question) → wait for reply    │
               ↓                                                    │
          task_claim  (or task_create → task_claim)                 │
               ↓                                                    │
          thread_post(claim)                                        │
               ↓                                                    │
          file_lock(path)                                           │
               ↓                                                    │
          [edit ≤3 files]                                           │
               ↓                                                    │
     thread_post(update) every 10m ────────────────────────────────┘
               ↓
     task_update(done) + thread_post(done: state report)
               ↓
     file_unlock(path) → back to thread_read()
```

Agent offline detection:
- No ping for **2 min** → marked offline in UI
- No ping for **5 min** → tasks returned to `pending`, system message posted

---

## License

MIT
