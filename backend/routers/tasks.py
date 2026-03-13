from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from database import get_session
from services.task_service import (
    list_tasks,
    create_task,
    get_task,
    update_task,
    delete_task,
    broadcast_task,
)
from services.thread_service import get_project_by_slug

router = APIRouter(prefix="/api/v1/projects/{slug}/tasks", tags=["tasks"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[int] = None
    pr_url: Optional[str] = None


class TaskOut(BaseModel):
    id: str
    project_id: str
    title: str
    description: Optional[str]
    status: str
    agent_id: Optional[str]
    progress: int
    pr_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[TaskOut])
def get_tasks(
    slug: str,
    status: Optional[str] = Query(default=None, description="Comma-separated status values"),
    session: Session = Depends(get_session),
):
    project = get_project_by_slug(session, slug)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    statuses = [s.strip() for s in status.split(",")] if status else None
    return list_tasks(session, project.id, statuses=statuses)


@router.post("/", response_model=TaskOut, status_code=201)
def add_task(
    slug: str,
    body: TaskCreate,
    session: Session = Depends(get_session),
):
    project = get_project_by_slug(session, slug)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return create_task(session, project.id, body.title, body.description)


@router.patch("/{task_id}", response_model=TaskOut)
async def patch_task(
    slug: str,
    task_id: str,
    body: TaskUpdate,
    session: Session = Depends(get_session),
):
    project = get_project_by_slug(session, slug)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    task = get_task(session, task_id, project.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    updates = body.model_dump(exclude_none=True)
    task = update_task(session, task, **updates)
    await broadcast_task(slug, task)
    return task


@router.delete("/{task_id}", status_code=204)
def remove_task(
    slug: str,
    task_id: str,
    session: Session = Depends(get_session),
):
    project = get_project_by_slug(session, slug)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    task = get_task(session, task_id, project.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    delete_task(session, task)
