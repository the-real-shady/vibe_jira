# Team Lead — Instructions Template

Use this as the content for `instruction_set()` or paste into the AgentBoard UI instruction field.
Replace placeholders in `{{ }}`.

---

## Project: {{ project_name }}

You are directing a multi-agent engineering team via AgentBoard. Agents will read these instructions on every session startup via `instruction_get()`.

---

## Current Sprint Goal

{{ Describe the current sprint goal or milestone in 2-3 sentences. Example: "Ship v1.0 of the auth module. All endpoints must have tests. Deploy to staging by end of week." }}

---

## Active Agents

| Agent | Capabilities | Status |
|-------|-------------|--------|
| claude-1 | typescript, python, fullstack, code-review | active |
| codex-1 | python, backend, testing, infrastructure | active |

Add agents as they join. Remove when they go offline permanently.

---

## Task management rules (enforce strictly)

- **Every piece of work needs a task.** Agents MUST create a task before starting work if one doesn't exist.
- Tasks must have a clear title, description, and priority.
- Agents must update task progress every ~10 minutes.
- Completed tasks must be marked `done` with a summary.
- No task → no code. This is non-negotiable.

---

## Coordination rules

- Agents MUST lock files before editing them.
- Max 3 tasks per agent at a time.
- Agents MUST post to thread on claim, update (every 10 min), and done.
- Agents MUST respond to `@mentions` before picking up new work.
- If an agent is blocked >10 min, escalate to team lead.

---

## Current priorities

```
1. {{ highest priority item }}
2. {{ second priority }}
3. {{ third priority }}
```

---

## Off-limits / do not touch

```
{{ List files or modules agents should NOT modify without explicit permission }}
Example:
- production database migrations (ask team-lead first)
- .env files (never commit secrets)
- main/master branch (PR only)
```

---

## How to escalate

If blocked or uncertain → post to thread with tag `blocked` or `question`, mention `@team-lead`.
Team lead monitors the web UI and will respond.

---

## Notes

{{ Any additional context, architectural decisions, or constraints agents should know about. }}
