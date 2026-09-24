"""Outbox dispatcher and WebSocket connection management."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models import DomainEvent
from app.schemas import EventView
from app.services import utc_now
from app.workflows.models import OutboxRecord

logger = logging.getLogger("studio.publisher")


class ConnectionManager:
    """Manages active WebSocket client connections for real-time event streaming."""

    def __init__(self) -> None:
        self._active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._active.append(websocket)

    def add(self, websocket: WebSocket) -> None:
        """Joins a socket already accepted and authenticated to the broadcast."""
        if websocket not in self._active:
            self._active.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._active:
            self._active.remove(websocket)

    @property
    def active_count(self) -> int:
        return len(self._active)

    async def broadcast(self, message: dict[str, Any]) -> int:
        """Send message to all connected clients; cleans up disconnected sockets."""
        stale: list[WebSocket] = []
        sent = 0
        text = json.dumps(message)
        for ws in self._active:
            try:
                await ws.send_text(text)
                sent += 1
            except Exception:
                stale.append(ws)

        for ws in stale:
            self.disconnect(ws)
        return sent


def publish_pending_outbox(
    engine: Engine,
    manager: ConnectionManager,
    limit: int = 100,
) -> int:
    """Read pending OutboxRecord entries, broadcast to WebSockets, and mark PUBLISHED."""
    now_str = utc_now()
    published_count = 0

    with Session(engine) as session, session.begin():
        records = session.scalars(
            select(OutboxRecord)
            .where(OutboxRecord.status == "PENDING")
            .order_by(OutboxRecord.sequence.asc())
            .limit(limit)
        ).all()

        if not records:
            return 0

        for r in records:
            msg = {"type": "event", "data": r.payload}
            try:
                # Run broadcast safely
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(manager.broadcast(msg))
                except RuntimeError:
                    asyncio.run(manager.broadcast(msg))
                r.status = "PUBLISHED"
                r.published_at = now_str
                published_count += 1
            except Exception as exc:
                logger.error("outbox_publish_failed", extra={"record_id": r.id, "error": str(exc)})
                r.status = "FAILED"

        session.flush()
    return published_count


def replay_events(
    engine: Engine,
    after_sequence: int = 0,
    limit: int = 100,
) -> list[dict]:
    """Retrieve historical events from domain_event starting after sequence cursor."""
    with Session(engine) as session:
        events = session.scalars(
            select(DomainEvent)
            .where(DomainEvent.sequence > after_sequence)
            .order_by(DomainEvent.sequence.asc())
            .limit(limit)
        ).all()
        return [EventView.model_validate(e).model_dump() for e in events]
