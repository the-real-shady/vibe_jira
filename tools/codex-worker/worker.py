#!/usr/bin/env python3
"""
codex-worker — keeps Codex CLI running as an AgentBoard team member.

Connects to an AgentBoard project, polls for pending tasks, runs each task
via `codex exec`, and loops until there are no more tasks to process.

Usage:
    python worker.py --project my-project --api-key secret --agent-id codex-1 \\
                     --host http://localhost:8000 --work-dir ~/my-project

Environment variable equivalents (can replace any flag):
    AGENTBOARD_HOST, AGENTBOARD_PROJECT, AGENTBOARD_API_KEY, AGENTBOARD_AGENT_ID
"""

import argparse
import json
import os
import subprocess
import sys
import time
import textwrap
from typing import Any

try:
    import requests
except ImportError:
    sys.exit("requests is required: pip install requests")

# ──────────────────────────────────────────────────────────────────────────────
# AgentBoard client (REST + MCP JSON-RPC)
# ──────────────────────────────────────────────────────────────────────────────

class AgentBoard:
    def __init__(self, host: str, project: str, api_key: str, agent_id: str):
        self.rest = f"{host.rstrip('/')}/api/v1/projects/{project}"
        self.mcp  = f"{host.rstrip('/')}/mcp/projects/{project}/messages"
        self.headers = {"X-API-Key": api_key, "X-Agent-Id": agent_id}
        self.agent_id = agent_id
        self._mcp_id  = 0

    # ── REST helpers ──────────────────────────────────────────────────────────

    def list_tasks(self, status: list[str] | None = None) -> list[dict]:
        params = {}
        if status:
            params["status"] = ",".join(status)
        r = requests.get(f"{self.rest}/tasks/", headers=self.headers, params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    # ── MCP JSON-RPC helpers ──────────────────────────────────────────────────

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
        # unwrap MCP content envelope
        result = data.get("result", {})
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

    def instructions(self) -> dict:
        return self._call("instruction_get", {})

    def claim(self, task_id: str) -> dict:
        return self._call("task_claim", {"task_id": task_id})

    def update(self, task_id: str, status: str, progress: int | None = None, pr_url: str | None = None) -> dict:
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
# Prompt builder
# ──────────────────────────────────────────────────────────────────────────────

WORKFLOW_BLOCK = """
## AgentBoard workflow (follow strictly)

MCP server `agentboard` is already connected. Use these tools as you work:

- `file_lock(path)` — BEFORE editing any file
- `thread_post(tag="update", content="...")` — every ~10 min, report progress
- `task_update(task_id="{task_id}", status="in_progress", progress=N)` — update % as you go
- `thread_read()` — check for new instructions from the team lead

When finished:
- `task_update(task_id="{task_id}", status="done", progress=100)`
- `thread_post(tag="done", content="Completed: <one-line summary>")`
- `file_unlock(path)` for each locked file

If blocked:
- `task_update(task_id="{task_id}", status="blocked")`
- `thread_post(tag="blocked", content="Blocked: <reason>")`
"""

def build_prompt(task: dict, instructions_text: str, template_path: str | None) -> str:
    if template_path:
        tmpl = open(template_path).read()
        return tmpl.format(
            task_id=task["id"],
            task_title=task["title"],
            task_description=task.get("description") or "(no description)",
            instructions=instructions_text,
        )

    workflow = WORKFLOW_BLOCK.format(task_id=task["id"])
    instr_block = f"\n## Team lead instructions\n{instructions_text}\n" if instructions_text else ""

    return textwrap.dedent(f"""
        # Task: {task["title"]}

        **Task ID:** {task["id"]}
        **Description:** {task.get("description") or "(no description)"}
        {instr_block}
        {workflow}

        Work on this task now. When complete, update the task status via AgentBoard MCP tools.
    """).strip()


# ──────────────────────────────────────────────────────────────────────────────
# Codex runner
# ──────────────────────────────────────────────────────────────────────────────

def run_codex(prompt: str, work_dir: str, codex_bin: str, approval: str, extra_args: list[str]) -> tuple[int, str]:
    """Run `codex exec` and return (exit_code, stdout)."""
    cmd = [
        codex_bin, "exec",
        "--ask-for-approval", approval,
        "--output-last-message",
        *extra_args,
        prompt,
    ]
    print(f"  → Running codex exec in {work_dir}", flush=True)
    try:
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=False,   # let stderr stream live to terminal
            stdout=subprocess.PIPE,
            text=True,
            timeout=1800,           # 30 min max per task
        )
        return result.returncode, result.stdout or ""
    except subprocess.TimeoutExpired:
        return 124, "Timed out after 30 minutes"
    except FileNotFoundError:
        sys.exit(f"codex binary not found: {codex_bin}\nInstall: npm install -g @openai/codex")


# ──────────────────────────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="codex-worker: run Codex CLI as an AgentBoard agent in a task loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--host",      default=os.getenv("AGENTBOARD_HOST", "http://localhost:8000"), help="AgentBoard server URL")
    ap.add_argument("--project",   default=os.getenv("AGENTBOARD_PROJECT"),  required=not os.getenv("AGENTBOARD_PROJECT"), help="Project slug")
    ap.add_argument("--api-key",   default=os.getenv("AGENTBOARD_API_KEY"),  required=not os.getenv("AGENTBOARD_API_KEY"), help="AgentBoard API key (X-API-Key)")
    ap.add_argument("--agent-id",  default=os.getenv("AGENTBOARD_AGENT_ID", "codex-worker"), help="Unique agent name (default: codex-worker)")
    ap.add_argument("--work-dir",  default=os.getcwd(), help="Directory to run codex in (default: cwd)")
    ap.add_argument("--codex-bin", default=os.getenv("CODEX_BIN", "codex"), help="Path to codex binary (default: codex)")
    ap.add_argument("--approval",  default="never", choices=["never", "on-request", "untrusted"], help="codex --ask-for-approval value (default: never)")
    ap.add_argument("--poll",      type=int, default=30, help="Seconds to wait between polls when no tasks (default: 30)")
    ap.add_argument("--capabilities", nargs="*", default=["code", "bash"], help="Agent capabilities for agent_ping")
    ap.add_argument("--prompt-template", help="Path to a custom prompt template file (.txt). Placeholders: {task_id}, {task_title}, {task_description}, {instructions}")
    ap.add_argument("--codex-args", nargs=argparse.REMAINDER, default=[], help="Extra args passed directly to codex exec")
    ap.add_argument("--exit-when-empty", action="store_true", help="Exit instead of waiting when task queue is empty")
    args = ap.parse_args()

    ab = AgentBoard(args.host, args.project, args.api_key, args.agent_id)
    work_dir = os.path.expanduser(args.work_dir)

    print(f"[codex-worker] agent={args.agent_id}  project={args.project}  host={args.host}")
    print(f"[codex-worker] work_dir={work_dir}  poll={args.poll}s  approval={args.approval}")

    # ── Register ──────────────────────────────────────────────────────────────
    print("\n[codex-worker] Registering with AgentBoard...", flush=True)
    pong = ab.ping(args.capabilities)
    print(f"  agent_ping → {pong}")

    # ── Main loop ─────────────────────────────────────────────────────────────
    idle_rounds = 0
    while True:
        # Keep-alive ping
        ab.ping(args.capabilities)

        # Fetch team lead instructions (once per loop)
        instr = ab.instructions()
        instructions_text = ""
        if isinstance(instr, dict):
            messages = instr.get("messages") or instr.get("content") or []
            if isinstance(messages, list) and messages:
                instructions_text = "\n".join(
                    m.get("content", "") if isinstance(m, dict) else str(m)
                    for m in messages
                )
            elif isinstance(instr, dict) and "text" in instr:
                instructions_text = instr["text"]

        # Poll for pending tasks
        try:
            tasks = ab.list_tasks(status=["pending"])
        except requests.HTTPError as e:
            print(f"[codex-worker] Error fetching tasks: {e}", file=sys.stderr)
            time.sleep(args.poll)
            continue

        if not tasks:
            idle_rounds += 1
            if args.exit_when_empty:
                print("[codex-worker] No pending tasks. Exiting (--exit-when-empty).")
                break
            print(f"[codex-worker] No pending tasks. Waiting {args.poll}s... (idle rounds: {idle_rounds})", flush=True)
            time.sleep(args.poll)
            continue

        idle_rounds = 0
        print(f"\n[codex-worker] {len(tasks)} pending task(s) found.", flush=True)

        # Process tasks one by one
        for task in tasks:
            print(f"\n[codex-worker] Attempting to claim: [{task['id']}] {task['title']}", flush=True)
            claim_result = ab.claim(task["id"])

            if "error" in claim_result:
                print(f"  Claim failed: {claim_result['error']} — skipping", flush=True)
                continue

            print(f"  Claimed ✓  agent={claim_result.get('agent_id', args.agent_id)}", flush=True)

            # Announce in thread
            ab.post(f"Taking task: **{task['title']}**", tag="claim")
            ab.update(task["id"], "in_progress", progress=5)

            # Build prompt and run Codex
            prompt = build_prompt(task, instructions_text, args.prompt_template)
            exit_code, output = run_codex(prompt, work_dir, args.codex_bin, args.approval, args.codex_args)

            if exit_code == 0:
                summary = output.strip().splitlines()[-1] if output.strip() else "Task completed"
                ab.update(task["id"], "done", progress=100)
                ab.post(f"Completed: **{task['title']}**\n\n{summary[:500]}", tag="done")
                print(f"  Task done ✓", flush=True)
            elif exit_code == 124:
                ab.update(task["id"], "blocked")
                ab.post(f"Blocked: **{task['title']}** — timed out after 30 min", tag="blocked")
                print(f"  Task timed out ✗", flush=True)
            else:
                ab.update(task["id"], "blocked")
                last_line = output.strip().splitlines()[-1][:300] if output.strip() else f"exit code {exit_code}"
                ab.post(f"Blocked: **{task['title']}** — {last_line}", tag="blocked")
                print(f"  Task failed (exit {exit_code}) ✗", flush=True)

            # Ping after each task to stay alive
            ab.ping(args.capabilities)

        # Short pause between task batches
        time.sleep(5)


if __name__ == "__main__":
    main()
