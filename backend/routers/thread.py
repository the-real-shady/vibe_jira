from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from database import get_session
from models import Project
from services.thread_service import (
    get_project_by_slug,
    create_message,
    list_messages,
    broadcast_message,
    VALID_TAGS,
)

router = APIRouter(prefix="/api/v1/projects/{slug}/thread", tags=["thread"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class MessageCreate(BaseModel):
    content: str


class MessageOut(BaseModel):
    id: str
    project_id: str
    agent_id: str
    content: str
    tag: str
    reply_to: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[MessageOut])
def get_thread(
    slug: str,
    since: Optional[datetime] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    tag: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
):
    project = get_project_by_slug(session, slug)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return list_messages(session, project.id, since=since, limit=limit, tag=tag)


@router.post("/", response_model=MessageOut, status_code=201)
async def post_instruction(
    slug: str,
    body: MessageCreate,
    session: Session = Depends(get_session),
):
    """Team lead posts a system instruction."""
    project = get_project_by_slug(session, slug)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    msg = create_message(
        session,
        project_id=project.id,
        agent_id="team-lead",
        content=body.content,
        tag="system",
    )
    await broadcast_message(slug, msg)
    return msg
