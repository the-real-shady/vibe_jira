import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

load_dotenv()

from database import engine, init_db
from models import Agent, Message, Task
from ws_manager import manager

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("agentboard")

# ── Config ────────────────────────────────────────────────────────────────────

API_KEY = os.getenv("API_KEY", "")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")]

AGENT_OFFLINE_AFTER = timedelta(minutes=2)
AGENT_TASK_RELEASE_AFTER = timedelta(minutes=5)


# ── Background task: agent timeout detection ──────────────────────────────────

async def _check_agent_timeouts() -> None:
    """Run every 60 s; mark stale agents offline and return their tasks."""
    while True:
        await asyncio.sleep(60)
        try:
            _run_agent_timeout_check()
        except Exception:
            logger.exception("Agent timeout check failed")


def _run_agent_timeout_check() -> None:
    now = datetime.utcnow()
    with Session(engine) as session:
        stale_agents = session.exec(
            select(Agent).where(
                Agent.online == True,
                Agent.last_ping < now - AGENT_OFFLINE_AFTER,
            )
        ).all()

        for agent in stale_agents:
            agent.online = False
            session.add(agent)
            logger.info("Agent %s (%s) marked offline", agent.name, agent.id)

        if stale_agents:
            session.commit()

        # Return tasks for agents gone > 5 min
        very_stale = session.exec(
            select(Agent).where(
                Agent.online == False,
                Agent.last_ping < now - AGENT_TASK_RELEASE_AFTER,
            )
        ).all()

        for agent in very_stale:
            tasks = session.exec(
                select(Task).where(
                    Task.agent_id == agent.id,
                    Task.status.in_(["claimed", "in_progress"]),
                )
            ).all()

            for task in tasks:
                task.status = "pending"
                task.agent_id = None
                task.updated_at = now
                session.add(task)

                # Post system message about the released task
                msg = Message(
                    project_id=task.project_id,
                    agent_id="system",
                    content=(
                        f"Agent '{agent.name}' went offline. "
                        f"Task '{task.title}' (id={task.id}) returned to pending."
                    ),
                    tag="system",
                )
                session.add(msg)

        if very_stale:
            session.commit()


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialised")
    task = asyncio.create_task(_check_agent_timeouts())
    logger.info("Background timeout checker started")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AgentBoard",
    version="1.0.0",
    description="Coordination backend for multi-agent AI teams",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth middleware ────────────────────────────────────────────────────────────

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Skip auth for health check, docs, and openapi schema
    skip_paths = {"/health", "/docs", "/redoc", "/openapi.json"}
    if request.url.path in skip_paths:
        return await call_next(request)

    # Skip OPTIONS pre-flight
    if request.method == "OPTIONS":
        return await call_next(request)

    if API_KEY:
        provided = request.headers.get("X-API-Key", "")
        if provided != API_KEY:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})

    return await call_next(request)


# ── Routers ───────────────────────────────────────────────────────────────────

from routers import agents, projects, tasks, thread
from mcp_server import router as mcp_router

app.include_router(projects.router)
app.include_router(thread.router)
app.include_router(tasks.router)
app.include_router(agents.router)
app.include_router(mcp_router)


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "version": "1.0.0"}


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws/projects/{slug}")
async def websocket_endpoint(websocket: WebSocket, slug: str):
    # For WebSockets, auth via query param or skip if no API_KEY set
    if API_KEY:
        token = websocket.query_params.get("api_key", "")
        if token != API_KEY:
            await websocket.close(code=4001)
            return

    await manager.connect(slug, websocket)
    try:
        while True:
            # We don't expect messages from the client, but keep alive
            data = await websocket.receive_text()
            # Optionally handle ping
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(slug, websocket)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
