import asyncio
from datetime import datetime
from typing import Optional, List
from sqlmodel import Session, select

from models import Task, Agent
from ws_manager import manager

# Global lock to make task_claim atomic
_claim_lock = asyncio.Lock()


def list_tasks(
    session: Session,
    project_id: str,
    statuses: Optional[List[str]] = None,
) -> List[Task]:
    query = select(Task).where(Task.project_id == project_id)
    if statuses:
        query = query.where(Task.status.in_(statuses))
    query = query.order_by(Task.created_at.asc())
    return list(session.exec(query).all())


def create_task(session: Session, project_id: str, title: str, description: Optional[str]) -> Task:
    task = Task(project_id=project_id, title=title, description=description)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def get_task(session: Session, task_id: str, project_id: str) -> Optional[Task]:
    return session.exec(
        select(Task).where(Task.id == task_id, Task.project_id == project_id)
    ).first()


def update_task(session: Session, task: Task, **kwargs) -> Task:
    for key, value in kwargs.items():
        if value is not None and hasattr(task, key):
            setattr(task, key, value)
    task.updated_at = datetime.utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def delete_task(session: Session, task: Task) -> None:
    session.delete(task)
    session.commit()


async def claim_task(
    session: Session,
    project_id: str,
    task_id: str,
    agent_id: str,
) -> dict:
    """Atomically claim a task. Returns the task dict or an error dict."""
    async with _claim_lock:
        task = get_task(session, task_id, project_id)
        if task is None:
            return {"error": "not_found"}

        if task.status != "pending":
            # Find agent name if possible
            owner_agent = session.exec(
                select(Agent).where(Agent.id == task.agent_id, Agent.project_id == project_id)
            ).first()
            by_name = owner_agent.name if owner_agent else (task.agent_id or "unknown")
            return {"error": "already_claimed", "by": by_name}

        # Check agent doesn't already have 3+ active tasks
        active_count = len(list(session.exec(
            select(Task).where(
                Task.project_id == project_id,
                Task.agent_id == agent_id,
                Task.status.in_(["claimed", "in_progress"]),
            )
        ).all()))
        if active_count >= 3:
            return {"error": "too_many_tasks", "active": active_count}

        task.status = "claimed"
        task.agent_id = agent_id
        task.updated_at = datetime.utcnow()
        session.add(task)
        session.commit()
        session.refresh(task)
        return {"task": task}


async def broadcast_task(slug: str, task: Task, event_type: str = "task_update") -> None:
    await manager.broadcast(slug, {
        "type": event_type,
        "data": {
            "id": task.id,
            "project_id": task.project_id,
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "agent_id": task.agent_id,
            "progress": task.progress,
            "pr_url": task.pr_url,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
        },
    })
