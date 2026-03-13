import re
from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import Project, Agent

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectOut(BaseModel):
    id: str
    slug: str
    name: str
    description: Optional[str]
    archived: bool
    created_at: datetime
    online_agents: int = 0

    class Config:
        from_attributes = True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "project"


def _unique_slug(session: Session, base: str) -> str:
    slug = base
    counter = 1
    while session.exec(select(Project).where(Project.slug == slug)).first():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _project_out(project: Project, session: Session) -> ProjectOut:
    online = session.exec(
        select(Agent).where(
            Agent.project_id == project.id,
            Agent.online == True,
        )
    ).all()
    return ProjectOut(
        id=project.id,
        slug=project.slug,
        name=project.name,
        description=project.description,
        archived=project.archived,
        created_at=project.created_at,
        online_agents=len(list(online)),
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[ProjectOut])
def list_projects(session: Session = Depends(get_session)):
    projects = session.exec(select(Project).where(Project.archived == False)).all()
    return [_project_out(p, session) for p in projects]


@router.post("/", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, session: Session = Depends(get_session)):
    base_slug = _slugify(body.name)
    slug = _unique_slug(session, base_slug)
    project = Project(slug=slug, name=body.name, description=body.description)
    session.add(project)
    session.commit()
    session.refresh(project)
    return _project_out(project, session)


@router.get("/{slug}", response_model=ProjectOut)
def get_project(slug: str, session: Session = Depends(get_session)):
    project = session.exec(select(Project).where(Project.slug == slug)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_out(project, session)


@router.delete("/{slug}", status_code=204)
def archive_project(slug: str, session: Session = Depends(get_session)):
    project = session.exec(select(Project).where(Project.slug == slug)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.archived = True
    session.add(project)
    session.commit()
