from datetime import datetime
from typing import Optional, List
from sqlmodel import Session, select

from models import Message, Project
from ws_manager import manager


VALID_TAGS = {"system", "claim", "update", "question", "done", "conflict", "blocked"}


def get_project_by_slug(session: Session, slug: str) -> Optional[Project]:
    return session.exec(select(Project).where(Project.slug == slug, Project.archived == False)).first()


def create_message(
    session: Session,
    project_id: str,
    agent_id: str,
    content: str,
    tag: str,
    reply_to: Optional[str] = None,
) -> Message:
    msg = Message(
        project_id=project_id,
        agent_id=agent_id,
        content=content,
        tag=tag,
        reply_to=reply_to,
    )
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return msg


def list_messages(
    session: Session,
    project_id: str,
    since: Optional[datetime] = None,
    limit: int = 50,
    tag: Optional[str] = None,
) -> List[Message]:
    query = select(Message).where(Message.project_id == project_id)
    if since:
        query = query.where(Message.created_at > since)
    if tag:
        query = query.where(Message.tag == tag)
    query = query.order_by(Message.created_at.asc()).limit(min(limit, 200))
    return list(session.exec(query).all())


async def broadcast_message(slug: str, message: Message) -> None:
    await manager.broadcast(slug, {
        "type": "message",
        "data": {
            "id": message.id,
            "project_id": message.project_id,
            "agent_id": message.agent_id,
            "content": message.content,
            "tag": message.tag,
            "reply_to": message.reply_to,
            "created_at": message.created_at.isoformat(),
        },
    })
