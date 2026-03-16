from typing import Optional
from datetime import datetime
from uuid import uuid4
from sqlmodel import SQLModel, Field


class Project(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    description: Optional[str] = None
    archived: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Message(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    agent_id: str
    content: str
    tag: str  # system, claim, update, question, done, conflict, blocked
    reply_to: Optional[str] = Field(default=None, foreign_key="message.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Task(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    title: str
    description: Optional[str] = None
    status: str = "pending"  # pending, claimed, in_progress, done, blocked, conflict
    agent_id: Optional[str] = None
    progress: int = 0
    pr_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Agent(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    agent_key: str = Field(index=True)   # X-Agent-Id value; unique per project
    name: str
    capabilities: Optional[str] = None  # JSON array
    last_ping: Optional[datetime] = None
    online: bool = False


class FileLock(SQLModel, table=True):
    __tablename__ = "file_locks"
    path: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="project.id", primary_key=True)
    agent_id: str
    locked_at: datetime = Field(default_factory=datetime.utcnow)
