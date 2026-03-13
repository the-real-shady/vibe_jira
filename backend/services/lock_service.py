import asyncio
from datetime import datetime, timedelta
from typing import Optional
from sqlmodel import Session, select

from models import FileLock, Agent
from ws_manager import manager

LOCK_EXPIRY_MINUTES = 30

_lock_mutex = asyncio.Lock()


def _get_lock(session: Session, path: str, project_id: str) -> Optional[FileLock]:
    return session.exec(
        select(FileLock).where(FileLock.path == path, FileLock.project_id == project_id)
    ).first()


async def acquire_lock(
    session: Session,
    project_id: str,
    path: str,
    agent_id: str,
) -> dict:
    """Try to acquire a file lock. Returns success or error dict."""
    async with _lock_mutex:
        existing = _get_lock(session, path, project_id)

        if existing:
            # Check if it's expired
            expiry = existing.locked_at + timedelta(minutes=LOCK_EXPIRY_MINUTES)
            if datetime.utcnow() < expiry:
                if existing.agent_id == agent_id:
                    # Refresh own lock
                    existing.locked_at = datetime.utcnow()
                    session.add(existing)
                    session.commit()
                    return {"status": "ok", "path": path, "refreshed": True}

                # Find agent name
                owner = session.exec(
                    select(Agent).where(Agent.id == existing.agent_id, Agent.project_id == project_id)
                ).first()
                by_name = owner.name if owner else existing.agent_id
                return {
                    "error": "locked",
                    "by": by_name,
                    "since": existing.locked_at.isoformat(),
                }
            else:
                # Expired – remove and let fall through to create
                session.delete(existing)
                session.flush()

        lock = FileLock(path=path, project_id=project_id, agent_id=agent_id)
        session.add(lock)
        session.commit()
        return {"status": "ok", "path": path}


async def release_lock(
    session: Session,
    project_id: str,
    path: str,
    agent_id: str,
    slug: str,
) -> dict:
    """Release a lock owned by this agent and broadcast the event."""
    async with _lock_mutex:
        existing = _get_lock(session, path, project_id)
        if not existing:
            return {"error": "not_found"}
        if existing.agent_id != agent_id:
            return {"error": "not_owner"}

        session.delete(existing)
        session.commit()

    await manager.broadcast(slug, {
        "type": "file_lock",
        "data": {"path": path, "locked": False, "agent_id": agent_id},
    })
    return {"status": "ok", "path": path}


def release_agent_locks(session: Session, project_id: str, agent_id: str) -> int:
    """Release all locks held by an agent (called on timeout). Returns count released."""
    locks = list(session.exec(
        select(FileLock).where(
            FileLock.project_id == project_id,
            FileLock.agent_id == agent_id,
        )
    ).all())
    for lock in locks:
        session.delete(lock)
    if locks:
        session.commit()
    return len(locks)


def purge_expired_locks(session: Session) -> int:
    """Remove locks older than LOCK_EXPIRY_MINUTES. Returns count purged."""
    cutoff = datetime.utcnow() - timedelta(minutes=LOCK_EXPIRY_MINUTES)
    locks = list(session.exec(
        select(FileLock).where(FileLock.locked_at < cutoff)
    ).all())
    for lock in locks:
        session.delete(lock)
    if locks:
        session.commit()
    return len(locks)
