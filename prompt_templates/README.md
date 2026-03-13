# Prompt Templates

Ready-to-use prompt templates for AgentBoard agents and team leads.

## Files

| File | Use for |
|------|---------|
| `claude-agent.md` | Claude Code — paste into `CLAUDE.md` in your project |
| `codex-agent.md` | Codex CLI / Continue / Cursor — paste into `AGENTS.md` |
| `team-lead.md` | Team lead instructions — paste into AgentBoard UI or `instruction_set()` |

## How to use

1. Copy the relevant template
2. Replace all `{{ placeholder }}` values with your project specifics
3. Place in the correct location (see table above)

## Key principle: tasks are mandatory

All templates enforce the rule: **every piece of work must have a task**.

```
If task exists → task_claim() → work
If no task    → task_create() → task_claim() → work
Never         → start work without a claimed task
```

Thread messages alone are not enough — tasks provide structured tracking, progress visibility, and prevent duplicate work between agents.
