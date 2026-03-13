import asyncio
import logging
from collections import defaultdict
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections per project slug."""

    def __init__(self) -> None:
        # slug -> set of active WebSocket connections
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, slug: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[slug].add(websocket)
        logger.info("WS connected: project=%s total=%d", slug, len(self._connections[slug]))

    async def disconnect(self, slug: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[slug].discard(websocket)
            if not self._connections[slug]:
                del self._connections[slug]
        logger.info("WS disconnected: project=%s", slug)

    async def broadcast(self, slug: str, message: dict) -> None:
        """Send a JSON message to all connections for the given project."""
        async with self._lock:
            connections = set(self._connections.get(slug, set()))

        if not connections:
            return

        dead: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        # Clean up dead connections
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections[slug].discard(ws)


manager = ConnectionManager()
