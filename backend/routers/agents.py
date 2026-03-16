from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import Agent
from services.thread_service import get_project_by_slug

router = APIRouter(prefix="/api/v1/projects/{slug}/agents", tags=["agents"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class AgentOut(BaseModel):
    id: str
    agent_key: str
    project_id: str
    name: str
    capabilities: Optional[str]
    last_ping: Optional[datetime]
    online: bool

    class Config:
        from_attributes = True


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[AgentOut])
def list_agents(slug: str, session: Session = Depends(get_session)):
    project = get_project_by_slug(session, slug)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    agents = session.exec(
        select(Agent).where(Agent.project_id == project.id, Agent.online == True)
    ).all()
    return list(agents)
