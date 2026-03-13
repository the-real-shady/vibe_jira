"""
AgentBoard MCP server.

Mounted under /mcp/projects/{slug} as FastAPI routes.
Each tool receives project context from the URL and agent identity
from the X-Agent-Id request header.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import Agent, FileLock, Message, Project, Task
from services.lock_service import acquire_lock, release_lock
from services.task_service import broadcast_task, claim_task
from services.thread_service import (
    VALID_TAGS,
    broadcast_message,
    create_message,
    get_project_by_slug,
    list_messages,
)
from ws_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp/projects/{slug}", tags=["mcp"])


# ─────────────────────────────────────────────────────────────────────────────
# Helper: resolve project or 404
# ─────────────────────────────────────────────────────────────────────────────

def _get_project(session: Session, slug: str) -> Project:
    project = get_project_by_slug(session, slug)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _get_or_create_agent(
    session: Session,
    project_id: str,
    agent_id: Optional[str],
    agent_name: Optional[str] = None,
) -> str:
    """Return a stable agent_id, creating an agent record if needed."""
    if not agent_id:
        agent_id = str(uuid4())

    agent = session.exec(
        select(Agent).where(Agent.id == agent_id, Agent.project_id == project_id)
    ).first()

    if not agent:
        agent = Agent(
            id=agent_id,
            project_id=project_id,
            name=agent_name or agent_id[:8],
            online=True,
            last_ping=datetime.utcnow(),
        )
        session.add(agent)
        session.commit()

    return agent_id


# ─────────────────────────────────────────────────────────────────────────────
# JSON-RPC helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ok(result: Any, request_id: Any = None) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _err(code: int, message: str, request_id: Any = None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _text(value: Any) -> dict:
    return {"type": "text", "text": json.dumps(value, default=str)}


# ─────────────────────────────────────────────────────────────────────────────
# Tool catalogue (returned on tools/list)
# ─────────────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "thread_post",
        "description": "Post a message to the project thread.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Message body"},
                "tag": {
                    "type": "string",
                    "enum": ["claim", "update", "question", "done", "conflict", "blocked"],
                    "description": "Message tag",
                },
                "reply_to": {
                    "type": "string",
                    "description": "ID of message being replied to",
                },
            },
            "required": ["content", "tag"],
        },
    },
    {
        "name": "thread_read",
        "description": "Read recent messages from the project thread.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "since_ts": {
                    "type": "string",
                    "description": "ISO datetime; return only messages newer than this",
                },
                "limit": {"type": "integer", "default": 20, "maximum": 100},
            },
        },
    },
    {
        "name": "task_list",
        "description": "List tasks in the project, optionally filtered by status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by one or more status values",
                }
            },
        },
    },
    {
        "name": "task_claim",
        "description": "Claim a pending task for this agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID to claim"}
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "task_update",
        "description": "Update the status or progress of a task owned by this agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["in_progress", "done", "blocked", "conflict"],
                },
                "progress": {"type": "integer", "minimum": 0, "maximum": 100},
                "pr_url": {"type": "string"},
            },
            "required": ["task_id", "status"],
        },
    },
    {
        "name": "file_lock",
        "description": "Acquire an exclusive lock on a file path.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path to lock"}},
            "required": ["path"],
        },
    },
    {
        "name": "file_unlock",
        "description": "Release a file lock held by this agent.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "agent_ping",
        "description": "Register this agent and update its heartbeat.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "capabilities": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["agent_name"],
        },
    },
    {
        "name": "instruction_get",
        "description": "Retrieve system instructions posted by the team lead.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "since_ts": {
                    "type": "string",
                    "description": "Return only messages newer than this ISO datetime",
                }
            },
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Tool handlers
# ─────────────────────────────────────────────────────────────────────────────

async def _handle_thread_post(
    params: dict,
    slug: str,
    project: Project,
    agent_id: str,
    session: Session,
) -> Any:
    content = params.get("content", "").strip()
    tag = params.get("tag", "")
    reply_to = params.get("reply_to")

    if not content:
        return {"error": "content is required"}
    if tag not in VALID_TAGS - {"system"}:
        return {"error": f"invalid tag '{tag}'; must be one of: claim, update, question, done, conflict, blocked"}

    msg = create_message(session, project.id, agent_id, content, tag, reply_to)
    await broadcast_message(slug, msg)
    return {
        "id": msg.id,
        "project_id": msg.project_id,
        "agent_id": msg.agent_id,
        "content": msg.content,
        "tag": msg.tag,
        "reply_to": msg.reply_to,
        "created_at": msg.created_at.isoformat(),
    }


async def _handle_thread_read(
    params: dict,
    project: Project,
    session: Session,
) -> Any:
    since_ts_str = params.get("since_ts")
    limit = min(int(params.get("limit", 20)), 100)
    since = None
    if since_ts_str:
        try:
            since = datetime.fromisoformat(since_ts_str.replace("Z", "+00:00"))
        except ValueError:
            return {"error": "invalid since_ts format"}

    messages = list_messages(session, project.id, since=since, limit=limit)
    return [
        {
            "id": m.id,
            "agent_id": m.agent_id,
            "content": m.content,
            "tag": m.tag,
            "reply_to": m.reply_to,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]


async def _handle_task_list(params: dict, project: Project, session: Session) -> Any:
    from services.task_service import list_tasks
    statuses = params.get("status")
    tasks = list_tasks(session, project.id, statuses=statuses)
    return [
        {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "agent_id": t.agent_id,
            "progress": t.progress,
            "pr_url": t.pr_url,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat(),
        }
        for t in tasks
    ]


async def _handle_task_claim(
    params: dict,
    slug: str,
    project: Project,
    agent_id: str,
    session: Session,
) -> Any:
    task_id = params.get("task_id")
    if not task_id:
        return {"error": "task_id is required"}

    result = await claim_task(session, project.id, task_id, agent_id)
    if "error" in result:
        return result

    task = result["task"]
    await broadcast_task(slug, task)
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "agent_id": task.agent_id,
        "progress": task.progress,
        "updated_at": task.updated_at.isoformat(),
    }


async def _handle_task_update(
    params: dict,
    slug: str,
    project: Project,
    agent_id: str,
    session: Session,
) -> Any:
    from services.task_service import get_task, update_task

    task_id = params.get("task_id")
    status = params.get("status")
    progress = params.get("progress")
    pr_url = params.get("pr_url")

    if not task_id or not status:
        return {"error": "task_id and status are required"}

    task = get_task(session, task_id, project.id)
    if not task:
        return {"error": "task not found"}
    if task.agent_id != agent_id:
        return {"error": "not_owner", "message": "You do not own this task"}

    updates: dict = {"status": status}
    if progress is not None:
        updates["progress"] = progress
    if pr_url is not None:
        updates["pr_url"] = pr_url

    task = update_task(session, task, **updates)
    await broadcast_task(slug, task)
    return {
        "id": task.id,
        "status": task.status,
        "progress": task.progress,
        "pr_url": task.pr_url,
        "updated_at": task.updated_at.isoformat(),
    }


async def _handle_file_lock(
    params: dict,
    slug: str,
    project: Project,
    agent_id: str,
    session: Session,
) -> Any:
    path = params.get("path", "").strip()
    if not path:
        return {"error": "path is required"}

    result = await acquire_lock(session, project.id, path, agent_id)
    if result.get("status") == "ok":
        await manager.broadcast(slug, {
            "type": "file_lock",
            "data": {"path": path, "locked": True, "agent_id": agent_id},
        })
    return result


async def _handle_file_unlock(
    params: dict,
    slug: str,
    project: Project,
    agent_id: str,
    session: Session,
) -> Any:
    path = params.get("path", "").strip()
    if not path:
        return {"error": "path is required"}
    return await release_lock(session, project.id, path, agent_id, slug)


async def _handle_agent_ping(
    params: dict,
    slug: str,
    project: Project,
    agent_id: str,
    session: Session,
) -> Any:
    agent_name = params.get("agent_name", "").strip()
    capabilities = params.get("capabilities", [])

    if not agent_name:
        return {"error": "agent_name is required"}

    agent = session.exec(
        select(Agent).where(Agent.id == agent_id, Agent.project_id == project.id)
    ).first()

    if agent:
        agent.name = agent_name
        agent.online = True
        agent.last_ping = datetime.utcnow()
        if capabilities:
            agent.capabilities = json.dumps(capabilities)
    else:
        agent = Agent(
            id=agent_id,
            project_id=project.id,
            name=agent_name,
            capabilities=json.dumps(capabilities) if capabilities else None,
            online=True,
            last_ping=datetime.utcnow(),
        )

    session.add(agent)
    session.commit()
    return {"status": "ok", "agent_id": agent_id}


async def _handle_instruction_get(
    params: dict,
    project: Project,
    session: Session,
) -> Any:
    since_ts_str = params.get("since_ts")
    since = None
    if since_ts_str:
        try:
            since = datetime.fromisoformat(since_ts_str.replace("Z", "+00:00"))
        except ValueError:
            return {"error": "invalid since_ts format"}

    messages = list_messages(session, project.id, since=since, limit=100, tag="system")
    return [
        {
            "id": m.id,
            "agent_id": m.agent_id,
            "content": m.content,
            "tag": m.tag,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────────────────────────────────────

async def _dispatch(
    method: str,
    params: dict,
    slug: str,
    project: Project,
    agent_id: str,
    session: Session,
) -> Any:
    if method == "thread_post":
        return await _handle_thread_post(params, slug, project, agent_id, session)
    elif method == "thread_read":
        return await _handle_thread_read(params, project, session)
    elif method == "task_list":
        return await _handle_task_list(params, project, session)
    elif method == "task_claim":
        return await _handle_task_claim(params, slug, project, agent_id, session)
    elif method == "task_update":
        return await _handle_task_update(params, slug, project, agent_id, session)
    elif method == "file_lock":
        return await _handle_file_lock(params, slug, project, agent_id, session)
    elif method == "file_unlock":
        return await _handle_file_unlock(params, slug, project, agent_id, session)
    elif method == "agent_ping":
        return await _handle_agent_ping(params, slug, project, agent_id, session)
    elif method == "instruction_get":
        return await _handle_instruction_get(params, project, session)
    else:
        raise ValueError(f"Unknown tool: {method}")


# ─────────────────────────────────────────────────────────────────────────────
# SSE endpoint (MCP client connects here first)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/sse")
async def mcp_sse(slug: str, request: Request):
    """
    Server-Sent Events stream that tells MCP clients where to POST messages.
    Sends a single 'endpoint' event and then keeps the connection alive.
    """
    messages_url = str(request.url).replace("/sse", "/messages")

    async def event_stream():
        # Send the endpoint event as required by MCP SSE transport
        yield f"event: endpoint\ndata: {json.dumps({'url': messages_url})}\n\n"
        # Keep-alive: ping every 15 s
        import asyncio as _asyncio
        while True:
            await _asyncio.sleep(15)
            yield ": ping\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Messages endpoint (JSON-RPC over HTTP POST)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/messages")
async def mcp_messages(
    slug: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """
    Handle MCP JSON-RPC 2.0 messages.

    Supports:
      - initialize
      - tools/list
      - tools/call
    """
    agent_id = request.headers.get("X-Agent-Id") or str(uuid4())

    try:
        body = await request.json()
    except Exception:
        return _err(-32700, "Parse error")

    rpc_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params") or {}

    # ── initialize ────────────────────────────────────────────────────────────
    if method == "initialize":
        return _ok(
            {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "agentboard", "version": "1.0.0"},
                "capabilities": {"tools": {}},
            },
            rpc_id,
        )

    # ── notifications (no response needed) ───────────────────────────────────
    if method.startswith("notifications/"):
        return {}

    # ── tools/list ────────────────────────────────────────────────────────────
    if method == "tools/list":
        return _ok({"tools": TOOLS}, rpc_id)

    # ── tools/call ────────────────────────────────────────────────────────────
    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {}

        project = get_project_by_slug(session, slug)
        if not project:
            return _err(-32602, "Project not found", rpc_id)

        # Ensure agent record exists
        _get_or_create_agent(session, project.id, agent_id)

        try:
            result = await _dispatch(tool_name, tool_args, slug, project, agent_id, session)
        except ValueError as exc:
            return _err(-32601, str(exc), rpc_id)
        except Exception as exc:
            logger.exception("Tool %s failed", tool_name)
            return _err(-32603, f"Internal error: {exc}", rpc_id)

        return _ok({"content": [_text(result)]}, rpc_id)

    return _err(-32601, f"Method not found: {method}", rpc_id)
