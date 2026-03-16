#!/usr/bin/env python3
"""
codex-worker — keeps Codex CLI running as an AgentBoard team member.

Message priority queue (never interrupts a running task):
  P0 — system instruction from team-lead  → injected into next prompt
  P1 — @{agent_id} direct question        → answered by codex exec after current task
  P2 — conflict / blocked from teammate   → acknowledged + offered help
  P3 — pending task from registry         → claimed and executed

Usage:
    python worker.py --project my-project --api-key secret --agent-id codex-1 \\
                     --host http://localhost:8000 --work-dir ~/my-project

Env var equivalents:
    AGENTBOARD_HOST, AGENTBOARD_PROJECT, AGENTBOARD_API_KEY, AGENTBOARD_AGENT_ID
"""

import argparse
import heapq
import json
import logging
import os
import subprocess
import sys
import textwrap
import threading
import time
from typing import Any

try:
    import requests
except ImportError:
    sys.exit("requests is required: pip install requests")

# ──────────────────────────────────────────────────────────────────────────────
# Logging — stdout + file in work_dir
# ──────────────────────────────────────────────────────────────────────────────

log = logging.getLogger("codex-worker")


def setup_logging(work_dir: str, verbose: bool = False) -> str:
    log_path = os.path.join(work_dir, "worker.log")
    level = logging.DEBUG if verbose else logging.INFO
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    log.setLevel(level)

    # Always write to file
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)

    # Write to stdout only when it's a TTY (interactive) — avoids duplication
    # when the process is launched with `>> worker.log 2>&1`
    if sys.stdout.isatty():
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        log.addHandler(sh)

    return log_path


# ──────────────────────────────────────────────────────────────────────────────
# Priority queue item
# ──────────────────────────────────────────────────────────────────────────────

# P0 = system instruction, P1 = @mention question, P2 = conflict/blocked, P3 = task
PRIO_SYSTEM   = 0
PRIO_MENTION  = 1
PRIO_CONFLICT = 2
PRIO_TASK     = 3

_PRIO_LABELS = {0: "SYSTEM", 1: "MENTION", 2: "CONFLICT", 3: "TASK"}


class QueueItem:
    __slots__ = ("priority", "ts", "kind", "payload")

    def __init__(self, priority: int, kind: str, payload: dict):
        self.priority = priority
        self.ts = time.monotonic()
        self.kind = kind
        self.payload = payload

    # heapq compares tuples; we only need priority + ts
    def __lt__(self, other: "QueueItem") -> bool:
        return (self.priority, self.ts) < (other.priority, other.ts)

    def __repr__(self) -> str:
        label = _PRIO_LABELS.get(self.priority, str(self.priority))
        return f"QueueItem({label}, {self.kind})"


# ──────────────────────────────────────────────────────────────────────────────
# AgentBoard client
# ──────────────────────────────────────────────────────────────────────────────

class AgentBoard:
    def __init__(self, host: str, project: str, api_key: str, agent_id: str):
        self.rest     = f"{host.rstrip('/')}/api/v1/projects/{project}"
        self.mcp      = f"{host.rstrip('/')}/mcp/projects/{project}/messages"
        self.headers  = {"X-API-Key": api_key, "X-Agent-Id": agent_id}
        self.agent_id = agent_id
        self._mcp_id  = 0

    # ── REST ──────────────────────────────────────────────────────────────────

    def list_tasks(self, status: list[str] | None = None) -> list[dict]:
        params = {}
        if status:
            params["status"] = ",".join(status)
        r = requests.get(f"{self.rest}/tasks/", headers=self.headers, params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    # ── MCP JSON-RPC ──────────────────────────────────────────────────────────

    def _call(self, tool: str, args: dict) -> Any:
        self._mcp_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._mcp_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }
        r = requests.post(self.mcp, json=payload, headers=self.headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            return {"error": data["error"].get("message", str(data["error"]))}
        result  = data.get("result", {})
        content = result.get("content", [{}])
        if content and isinstance(content[0], dict):
            raw = content[0].get("text", "{}")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"text": raw}
        return result

    def ping(self, capabilities: list[str] | None = None) -> dict:
        return self._call("agent_ping", {
            "agent_name": self.agent_id,
            "capabilities": capabilities or ["code", "bash"],
        })

    def thread_read(self, since_ts: str | None = None, limit: int = 50) -> list[dict]:
        args: dict = {"limit": limit}
        if since_ts:
            args["since_ts"] = since_ts
        result = self._call("thread_read", args)
        return result if isinstance(result, list) else []

    def instructions(self) -> list[dict]:
        result = self._call("instruction_get", {})
        return result if isinstance(result, list) else []

    def claim(self, task_id: str) -> dict:
        return self._call("task_claim", {"task_id": task_id})

    def update(self, task_id: str, status: str,
               progress: int | None = None, pr_url: str | None = None) -> dict:
        args: dict = {"task_id": task_id, "status": status}
        if progress is not None:
            args["progress"] = progress
        if pr_url:
            args["pr_url"] = pr_url
        return self._call("task_update", args)

    def post(self, content: str, tag: str, reply_to: str | None = None) -> dict:
        args: dict = {"content": content, "tag": tag}
        if reply_to:
            args["reply_to"] = reply_to
        return self._call("thread_post", args)


# ──────────────────────────────────────────────────────────────────────────────
# Thread feed poller (runs in background, never interrupts codex)
# ──────────────────────────────────────────────────────────────────────────────

class FeedPoller(threading.Thread):
    """
    Polls thread_read() every `interval` seconds and pushes new messages
    into the shared priority queue. Does NOT interrupt any running codex
    process — the main loop drains the queue between tasks.
    """

    def __init__(self, ab: AgentBoard, queue: list, queue_lock: threading.Lock,
                 seen_ids: set, agent_id: str, interval: int = 20):
        super().__init__(daemon=True, name="feed-poller")
        self.ab         = ab
        self.queue      = queue
        self.lock       = queue_lock
        self.seen_ids   = seen_ids
        self.agent_id   = agent_id
        self.interval   = interval
        self._last_ts: str | None = None

    def run(self):
        while True:
            try:
                self._poll()
            except Exception as exc:
                log.debug("FeedPoller error: %s", exc)
            time.sleep(self.interval)

    def _poll(self):
        msgs = self.ab.thread_read(since_ts=self._last_ts, limit=50)
        if not msgs:
            return

        new_msgs = [m for m in msgs if m.get("id") not in self.seen_ids]
        if not new_msgs:
            return

        # Advance the timestamp cursor
        latest_ts = max(m.get("created_at", "") for m in new_msgs)
        if latest_ts:
            self._last_ts = latest_ts

        for msg in new_msgs:
            self.seen_ids.add(msg.get("id"))
            self._classify_and_enqueue(msg)

    def _classify_and_enqueue(self, msg: dict):
        tag      = msg.get("tag", "")
        content  = msg.get("content", "")
        agent_id = msg.get("agent_id", "")
        mention  = f"@{self.agent_id}"

        # Ignore own messages
        if agent_id == self.agent_id:
            return

        item: QueueItem | None = None

        if tag == "system":
            log.info("📋 SYSTEM instruction received from %s", agent_id)
            item = QueueItem(PRIO_SYSTEM, "system_instruction", msg)

        elif mention in content and tag in ("question", "update", "claim", "done", "blocked", "conflict"):
            log.info("📣 @MENTION from %s: %s", agent_id, content[:80])
            item = QueueItem(PRIO_MENTION, "mention", msg)

        elif tag in ("conflict", "blocked"):
            log.info("⚠️  %s from %s: %s", tag.upper(), agent_id, content[:80])
            item = QueueItem(PRIO_CONFLICT, tag, msg)

        if item is not None:
            with self.lock:
                heapq.heappush(self.queue, item)
                log.debug("Enqueued %s (queue size=%d)", item, len(self.queue))


# ──────────────────────────────────────────────────────────────────────────────
# Prompt builders
# ──────────────────────────────────────────────────────────────────────────────

_WORKFLOW = """
## AgentBoard workflow (mandatory)

MCP server `agentboard` is connected. Use these tools:

- `file_lock(path)` — BEFORE editing any file
- `task_update(task_id="{task_id}", status="in_progress", progress=N)` — update % as you go
- `thread_post(tag="update", content="...")` — progress every ~10 min
- `thread_read()` — check for new messages from team

When finished:
- `task_update(task_id="{task_id}", status="done", progress=100)`
- `thread_post(tag="done", content="Done: <one-line summary>")`
- `file_unlock(path)` for every locked file

If blocked:
- `task_update(task_id="{task_id}", status="blocked")`
- `thread_post(tag="blocked", content="Blocked: <reason>")`
"""

def _fmt_messages(messages: list[dict], max_chars: int = 2000) -> str:
    lines = []
    for m in messages[-20:]:  # last 20 messages
        ts  = m.get("created_at", "")[:16].replace("T", " ")
        who = m.get("agent_id", "?")
        tag = m.get("tag", "")
        txt = m.get("content", "")
        lines.append(f"[{ts}] {who} ({tag}): {txt}")
    block = "\n".join(lines)
    return block[-max_chars:] if len(block) > max_chars else block


def build_task_prompt(task: dict, instructions: list[dict],
                      thread_feed: list[dict], template_path: str | None,
                      pending_system: list[str]) -> str:
    instructions_text = "\n".join(m.get("content", "") for m in instructions)
    feed_text         = _fmt_messages(thread_feed)
    system_notes      = "\n".join(pending_system)

    if template_path:
        tmpl = open(template_path).read()
        return tmpl.format(
            task_id=task["id"],
            task_title=task["title"],
            task_description=task.get("description") or "(no description)",
            instructions=instructions_text,
            thread_feed=feed_text,
        )

    workflow    = _WORKFLOW.format(task_id=task["id"])
    instr_block = f"\n## Team lead instructions\n{instructions_text}\n" if instructions_text else ""
    feed_block  = f"\n## Recent thread activity\n```\n{feed_text}\n```\n" if feed_text else ""
    sys_block   = f"\n## Pending system notes\n{system_notes}\n" if system_notes else ""

    return textwrap.dedent(f"""
        # Task: {task["title"]}

        **Task ID:** {task["id"]}
        **Description:** {task.get("description") or "(no description)"}
        {instr_block}{sys_block}{feed_block}{workflow}

        Work on this task. Update status via AgentBoard MCP tools when done.
    """).strip()


def build_system_prompt(msg: dict, thread_feed: list[dict]) -> str:
    feed_text = _fmt_messages(thread_feed)
    content   = msg.get("content", "")
    sender    = msg.get("agent_id", "team-lead")
    msg_id    = msg.get("id", "")
    feed_block = f"\n## Recent thread context\n```\n{feed_text}\n```\n" if feed_text else ""

    return textwrap.dedent(f"""
        # System instruction from @{sender} — execute immediately

        **Message ID:** {msg_id}
        **Instruction:** {content}
        {feed_block}

        ## What to do

        Follow the instruction above right now. Use AgentBoard MCP tools as needed:
        - `thread_read()` — get more context if required
        - `thread_post(tag="update", content="<your response/result>", reply_to="{msg_id}")`

        Respond in the thread when done. Be concise.
        Do NOT start unrelated coding work — only act on this instruction.
    """).strip()


def build_mention_prompt(msg: dict, instructions: list[dict],
                         thread_feed: list[dict]) -> str:
    feed_text = _fmt_messages(thread_feed)
    instr_text = "\n".join(m.get("content", "") for m in instructions)
    content   = msg.get("content", "")
    sender    = msg.get("agent_id", "someone")
    msg_id    = msg.get("id", "")

    feed_block  = f"\n## Recent thread context\n```\n{feed_text}\n```\n" if feed_text else ""
    instr_block = f"\n## Team lead instructions\n{instr_text}\n" if instr_text else ""

    return textwrap.dedent(f"""
        # Direct message that requires your response

        **From:** @{sender}
        **Message ID:** {msg_id}
        **Message:** {content}
        {instr_block}{feed_block}

        ## Instructions

        Use AgentBoard MCP tools to respond:
        - `thread_read()` to get full context if needed
        - `thread_post(tag="question", content="@{sender} <your answer>", reply_to="{msg_id}")`

        Answer the question or address the request above. Be concise.
        Do NOT start any new coding work — only respond to this message.
    """).strip()


# ──────────────────────────────────────────────────────────────────────────────
# MCP header-injection proxy
# Sits between codex and AgentBoard; codex connects with no auth,
# proxy adds X-API-Key + X-Agent-Id before forwarding to the real backend.
# ──────────────────────────────────────────────────────────────────────────────

import http.server
import socketserver
import urllib.request
import urllib.error


class _ProxyHandler(http.server.BaseHTTPRequestHandler):
    # Set by start_mcp_proxy()
    target_url: str = ""
    inject_headers: dict = {}

    def log_message(self, fmt, *args):  # silence default access log
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length else b""

        req = urllib.request.Request(self.target_url, data=body, method="POST")
        # Forward safe headers from the client
        for key in ("Content-Type", "Accept"):
            if key in self.headers:
                req.add_header(key, self.headers[key])
        # Always inject auth headers (override whatever codex sent)
        for k, v in self.inject_headers.items():
            req.add_header(k, v)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                ct = resp.headers.get("Content-Type", "application/json")
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as exc:
            body_err = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_err)))
            self.end_headers()
            self.wfile.write(body_err)
        except Exception as exc:
            msg = str(exc).encode()
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)


def start_mcp_proxy(target_url: str, api_key: str, agent_id: str) -> int:
    """
    Start a background HTTP proxy on a random free port.
    Returns the port number — use this as the MCP URL for codex.
    """
    # Find a free port
    import socket as _socket
    with _socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    handler = type("Handler", (_ProxyHandler,), {
        "target_url":     target_url,
        "inject_headers": {"X-API-Key": api_key, "X-Agent-Id": agent_id},
    })

    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True

    t = threading.Thread(target=server.serve_forever, daemon=True, name="mcp-proxy")
    t.start()
    log.info("MCP proxy started → http://127.0.0.1:%d  (forwarding to %s)", port, target_url)
    return port


def setup_codex_mcp(codex_bin: str, proxy_url: str) -> None:
    """Register the proxy URL via `codex mcp add`. Idempotent."""
    result = subprocess.run(
        [codex_bin, "mcp", "add", "agentboard", "--url", proxy_url],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        log.info("codex mcp add agentboard → %s ✓", proxy_url)
    else:
        log.debug("codex mcp add (already exists?): %s",
                  (result.stdout + result.stderr).strip()[:200])


def setup_codex_config(work_dir: str, proxy_url: str) -> str:
    """
    Write .codex/config.toml inside work_dir pointing codex at the local
    MCP proxy (no auth headers needed — the proxy injects them).
    Also enables network_access so the MCP client can reach localhost.
    """
    config_dir  = os.path.join(work_dir, ".codex")
    config_path = os.path.join(config_dir, "config.toml")
    os.makedirs(config_dir, exist_ok=True)

    config_content = (
        "# Generated by codex-worker — do not edit by hand\n\n"
        'approval_policy = "never"\n\n'
        "# Enable network access so MCP client can reach the local proxy\n"
        "[sandbox_workspace_write]\n"
        "network_access = true\n\n"
        "[mcp_servers.agentboard]\n"
        f'url = "{proxy_url}"\n'
    )

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(config_content)

    log.info("Wrote project codex config → %s  (proxy: %s)", config_path, proxy_url)
    return config_path


# ──────────────────────────────────────────────────────────────────────────────
# Codex runner
# ──────────────────────────────────────────────────────────────────────────────

_APPROVAL_FLAG = {
    "full-auto":   ["--full-auto"],
    # dangerously-bypass removes ALL sandbox (approval + network + fs)
    # -s danger-full-access is redundant but explicit
    "never":       ["--dangerously-bypass-approvals-and-sandbox"],
    "bypass":      ["--dangerously-bypass-approvals-and-sandbox"],
}


def run_codex(prompt: str, work_dir: str, codex_bin: str,
              approval: str, extra_args: list[str]) -> tuple[int, str]:
    approval_flags = _APPROVAL_FLAG.get(approval, ["--full-auto"])
    # Pass prompt via stdin ("-") — avoids shell-quoting issues with long/multiline prompts
    cmd = [
        codex_bin, "exec",
        *approval_flags,
        "--output-last-message",
        *extra_args,
        "-",
    ]
    codex_log_path = os.path.join(work_dir, "codex.log")
    log.info("→ codex exec  cwd=%s  (live output → %s)", work_dir, codex_log_path)
    try:
        with open(codex_log_path, "a", encoding="utf-8", errors="replace") as codex_log_f:
            codex_log_f.write(f"\n{'─'*60}\n[{time.strftime('%H:%M:%S')}] PROMPT:\n{prompt[:400]}\n{'─'*60}\n")
            codex_log_f.flush()
            result = subprocess.run(
                cmd,
                input=prompt,
                cwd=work_dir,
                stdout=codex_log_f,   # codex stdout (final message) → codex.log
                stderr=codex_log_f,   # codex progress/thinking    → codex.log
                text=True,
                timeout=1800,
            )
        log.info("← codex exit=%d", result.returncode)
        # Read the last non-empty line from codex.log as the "output summary"
        try:
            with open(codex_log_path, encoding="utf-8", errors="replace") as f:
                lines = [l.strip() for l in f.readlines() if l.strip() and not l.startswith("─")]
            last_line = lines[-1] if lines else ""
        except Exception:
            last_line = ""
        return result.returncode, last_line
    except subprocess.TimeoutExpired:
        return 124, "Timed out after 30 minutes"
    except FileNotFoundError:
        sys.exit(f"codex binary not found: {codex_bin}\nInstall: npm install -g @openai/codex")


# ──────────────────────────────────────────────────────────────────────────────
# Queue drainer — processes P0/P1/P2 items before next task
# ──────────────────────────────────────────────────────────────────────────────

def drain_queue(queue: list, lock: threading.Lock, ab: AgentBoard,
                work_dir: str, codex_bin: str, approval: str,
                extra_args: list[str], thread_feed: list[dict],
                instructions: list[dict]) -> list[str]:
    """
    Drains all queued messages in priority order (highest first).
    Returns a list of system-instruction texts to inject into the next task prompt.
    Never called while codex is running — always between tasks.
    """
    pending_system: list[str] = []

    while True:
        with lock:
            if not queue:
                break
            item: QueueItem = heapq.heappop(queue)

        log.info("Processing queued %s", item)

        if item.kind == "system_instruction":
            msg    = item.payload
            text   = msg.get("content", "")
            sender = msg.get("agent_id", "team-lead")
            log.info("  Executing system instruction from %s: %s", sender, text[:120])
            prompt = build_system_prompt(msg, thread_feed)
            rc, _  = run_codex(prompt, work_dir, codex_bin, approval, extra_args)
            if rc != 0:
                ab.post(
                    f"@{sender} Acknowledged. Could not fully execute via codex (exit {rc}). "
                    f"I am **{ab.agent_id}** — online and ready.",
                    tag="update",
                    reply_to=msg.get("id"),
                )
            # Also carry the text forward so it's injected into the next task prompt
            pending_system.append(text)

        elif item.kind == "mention":
            msg    = item.payload
            sender = msg.get("agent_id", "?")
            log.info("  Answering @mention from %s …", sender)
            prompt = build_mention_prompt(msg, instructions, thread_feed)
            rc, _  = run_codex(prompt, work_dir, codex_bin, approval, extra_args)
            if rc != 0:
                # Codex failed — post a plain acknowledgement
                ab.post(
                    f"@{sender} Got your message. Will address it shortly. "
                    f"(codex exit {rc})",
                    tag="question",
                    reply_to=msg.get("id"),
                )

        elif item.kind in ("conflict", "blocked"):
            msg    = item.payload
            sender = msg.get("agent_id", "?")
            log.info("  Acknowledging %s from %s", item.kind, sender)
            ab.post(
                f"@{sender} Noted your `{item.kind}`. "
                f"I'll check if I can help after my current task.",
                tag="question",
                reply_to=msg.get("id"),
            )

    return pending_system


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="codex-worker: Codex CLI as an AgentBoard agent (priority message queue)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--host",      default=os.getenv("AGENTBOARD_HOST", "http://localhost:8000"))
    ap.add_argument("--project",   default=os.getenv("AGENTBOARD_PROJECT"),
                    required=not os.getenv("AGENTBOARD_PROJECT"))
    ap.add_argument("--api-key",   default=os.getenv("AGENTBOARD_API_KEY"),
                    required=not os.getenv("AGENTBOARD_API_KEY"))
    ap.add_argument("--agent-id",  default=os.getenv("AGENTBOARD_AGENT_ID", "codex-worker"))
    ap.add_argument("--work-dir",  default=os.getcwd())
    ap.add_argument("--codex-bin", default=os.getenv("CODEX_BIN", "codex"))
    ap.add_argument("--approval",  default="bypass",
                    choices=["full-auto", "never", "bypass"],
                    help="bypass (default) = --dangerously-bypass-approvals-and-sandbox | full-auto = sandboxed")
    ap.add_argument("--poll",      type=int, default=30,
                    help="Seconds between task queue polls when idle (default: 30)")
    ap.add_argument("--feed-poll", type=int, default=20,
                    help="Seconds between thread feed polls (default: 20)")
    ap.add_argument("--capabilities", nargs="*", default=["code", "bash"])
    ap.add_argument("--prompt-template", help="Custom prompt template file")
    ap.add_argument("--codex-args", nargs=argparse.REMAINDER, default=[])
    ap.add_argument("--exit-when-empty", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    work_dir = os.path.expanduser(args.work_dir)
    log_path = setup_logging(work_dir, args.verbose)

    log.info("╔══════════════════════════════════════════════")
    log.info("║ codex-worker  agent=%s", args.agent_id)
    log.info("║ project=%s  host=%s", args.project, args.host)
    log.info("║ work_dir=%s", work_dir)
    log.info("║ log=%s", log_path)
    log.info("╚══════════════════════════════════════════════")

    ab = AgentBoard(args.host, args.project, args.api_key, args.agent_id)

    # Start local MCP proxy — intercepts codex requests and injects auth headers
    real_mcp_url = f"{args.host.rstrip('/')}/mcp/projects/{args.project}/messages"
    proxy_port   = start_mcp_proxy(real_mcp_url, args.api_key, args.agent_id)
    proxy_url    = f"http://127.0.0.1:{proxy_port}"

    # Register proxy URL via `codex mcp add` (no auth needed — proxy handles it)
    setup_codex_mcp(args.codex_bin, proxy_url)

    # Write project-level .codex/config.toml pointing codex at the proxy
    setup_codex_config(work_dir, proxy_url)

    # Register
    pong = ab.ping(args.capabilities)
    log.info("agent_ping → %s", pong)

    # Shared state
    prio_queue: list[QueueItem] = []
    queue_lock                  = threading.Lock()
    seen_ids: set[str]          = set()

    # Start background feed poller
    poller = FeedPoller(ab, prio_queue, queue_lock, seen_ids,
                        args.agent_id, interval=args.feed_poll)
    poller.start()
    log.info("Feed poller started (every %ds)", args.feed_poll)

    idle_rounds = 0

    while True:
        ab.ping(args.capabilities)

        # Snapshot current thread feed + instructions for prompt building
        thread_feed  = ab.thread_read(limit=30)
        instructions = ab.instructions()

        # ── Drain message queue BEFORE picking next task ───────────────────
        pending_system = drain_queue(
            prio_queue, queue_lock, ab,
            work_dir, args.codex_bin, args.approval, args.codex_args,
            thread_feed, instructions,
        )

        # ── Poll task registry ─────────────────────────────────────────────
        try:
            tasks = ab.list_tasks(status=["pending"])
        except requests.HTTPError as exc:
            log.error("Error fetching tasks: %s", exc)
            time.sleep(args.poll)
            continue

        if not tasks:
            idle_rounds += 1
            if args.exit_when_empty:
                log.info("No pending tasks. Exiting (--exit-when-empty).")
                break
            log.info("No pending tasks — waiting %ds (idle #%d)", args.poll, idle_rounds)
            time.sleep(args.poll)
            continue

        idle_rounds = 0
        log.info("%d pending task(s) found", len(tasks))

        for task in tasks:
            log.info("Attempting to claim [%s] %s", task["id"][:8], task["title"])
            claim_result = ab.claim(task["id"])

            if "error" in claim_result:
                log.info("  Claim failed: %s — skipping", claim_result["error"])
                continue

            log.info("  Claimed ✓  agent=%s", claim_result.get("agent_id", args.agent_id))
            ab.post(f"Taking task: **{task['title']}**", tag="claim")
            ab.update(task["id"], "in_progress", progress=5)

            prompt = build_task_prompt(
                task, instructions, thread_feed,
                args.prompt_template, pending_system,
            )
            pending_system = []  # consumed

            exit_code, output = run_codex(
                prompt, work_dir, args.codex_bin, args.approval, args.codex_args
            )

            if exit_code == 0:
                summary = output.strip().splitlines()[-1] if output.strip() else "Task completed"
                ab.update(task["id"], "done", progress=100)
                ab.post(f"Done: **{task['title']}**\n\n{summary[:500]}", tag="done")
                log.info("  Task done ✓")
            elif exit_code == 124:
                ab.update(task["id"], "blocked")
                ab.post(f"Blocked: **{task['title']}** — timed out after 30 min", tag="blocked")
                log.warning("  Task timed out ✗")
            else:
                ab.update(task["id"], "blocked")
                last_line = output.strip().splitlines()[-1][:300] if output.strip() else f"exit {exit_code}"
                ab.post(f"Blocked: **{task['title']}** — {last_line}", tag="blocked")
                log.warning("  Task failed (exit %d) ✗", exit_code)

            ab.ping(args.capabilities)

            # Drain queue again after each task (new messages may have arrived)
            pending_system = drain_queue(
                prio_queue, queue_lock, ab,
                work_dir, args.codex_bin, args.approval, args.codex_args,
                ab.thread_read(limit=30), instructions,
            )

        time.sleep(5)


if __name__ == "__main__":
    main()
