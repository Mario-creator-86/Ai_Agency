"""Outbox dispatcher and WebSocket connection management."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db import lock_for_write
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


def claim_pending_outbox(engine: Engine, limit: int = 100) -> list[dict[str, Any]]:
    """Mark the oldest PENDING outbox rows PUBLISHED, commit, and return their messages.

    The rows are marked and committed *before* anyone hears of them (REL-12, 2026-10-02). The
    old order broadcast first and updated after, in a deferred transaction without the write
    lock: when that commit failed beside another writer ("database is locked") the sockets had
    been told already and the rows stayed PENDING, so the next pass told them again. Now a
    failed commit raises here and nothing is sent; a socket that misses a message catches up
    through `replay_events`, which is what the page's reconnect reads.

    A plain read first: the dispatcher runs every second, and an empty outbox must not take
    the studio's write lock each time.
    """
    with Session(engine) as session:
        waiting = session.scalars(
            select(OutboxRecord.sequence).where(OutboxRecord.status == "PENDING").limit(1)
        ).first()
    if waiting is None:
        return []

    now_str = utc_now()
    messages: list[dict[str, Any]] = []
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        records = session.scalars(
            select(OutboxRecord)
            .where(OutboxRecord.status == "PENDING")
            .order_by(OutboxRecord.sequence.asc())
            .limit(limit)
        ).all()
        for record in records:
            record.status = "PUBLISHED"
            record.published_at = now_str
            messages.append({"type": "event", "data": record.payload})
    # Only here, after the commit, are the messages anybody's to send.
    return messages


async def _broadcast_all(manager: ConnectionManager, messages: list[dict[str, Any]]) -> None:
    for message in messages:
        try:
            await manager.broadcast(message)
        except Exception as exc:  # noqa: BLE001 - one message must not lose the rest
            logger.error("outbox_broadcast_failed", extra={"error": type(exc).__name__})


async def dispatch_pending_outbox(
    engine: Engine, manager: ConnectionManager, limit: int = 100
) -> int:
    """One pass of the server's dispatcher: claim in a thread, then broadcast on this loop.

    The database part runs off the event loop (`asyncio.to_thread`), so a write lock held
    elsewhere makes this pass wait, not every request the server is answering; the sockets
    belong to this loop, so the broadcasts stay here.
    """
    messages = await asyncio.to_thread(claim_pending_outbox, engine, limit)
    await _broadcast_all(manager, messages)
    return len(messages)


def publish_pending_outbox(
    engine: Engine,
    manager: ConnectionManager,
    limit: int = 100,
) -> int:
    """Claim the pending rows (`claim_pending_outbox`) and broadcast them; how many.

    For callers without a loop of their own (scripts, tests): the broadcasts run to the end
    here. Called from inside a running loop, they are scheduled on it — still only after the
    rows were committed. The server's dispatcher uses `dispatch_pending_outbox`.
    """
    messages = claim_pending_outbox(engine, limit)
    if not messages:
        return 0
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_broadcast_all(manager, messages))
    else:
        loop.create_task(_broadcast_all(manager, messages))
    return len(messages)


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
