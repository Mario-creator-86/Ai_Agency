"""The outbox dispatcher: a row is marked PUBLISHED and committed before anyone hears of it.

2026-10-02 (QUEUE_LEASE_SHUTDOWN, REL-12). `publish_pending_outbox` used to schedule the
broadcasts first and update the rows afterwards, in a deferred transaction without the write
lock. When that commit failed ("database is locked" beside another writer) the sockets had
already been told and the rows stayed PENDING, so the next second told them again. Now the
rows are claimed under `lock_for_write`, marked, committed, and only then broadcast; the
database part runs in a thread, off the server's event loop.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from app.workflows import publisher
from app.workflows.models import OutboxRecord
from app.workflows.publisher import (
    ConnectionManager,
    dispatch_pending_outbox,
    publish_pending_outbox,
    replay_events,
)
from app.workflows.services import append_event_with_outbox
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


class Recorder(ConnectionManager):
    """A connection manager that keeps what it was asked to send."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[dict[str, Any]] = []

    async def broadcast(self, message: dict[str, Any]) -> int:
        self.sent.append(message)
        return 1


def _pending(engine, count: int = 2) -> list[str]:
    ids: list[str] = []
    with Session(engine) as session, session.begin():
        for index in range(count):
            event_row, _ = append_event_with_outbox(
                session, "test.outbox", "test", str(index), 1, {"n": index}, str(uuid4())
            )
            ids.append(event_row.event_id)
    return ids


def _statuses(engine) -> list[str]:
    with Session(engine) as session:
        return [row.status for row in session.scalars(select(OutboxRecord))]


@pytest.fixture
def failing_commit_once():
    """Once armed, the next commit of any session fails, as one beside another writer can."""
    state = {"left": 0}

    def refuse(_session: Session) -> None:
        if state["left"] > 0:
            state["left"] -= 1
            raise OperationalError("COMMIT", {}, Exception("database is locked"))

    event.listen(Session, "before_commit", refuse)
    try:
        yield state
    finally:
        event.remove(Session, "before_commit", refuse)


def test_a_failed_outbox_commit_broadcasts_nothing_and_a_later_success_sends_each_once(
    engine, failing_commit_once
):
    ids = _pending(engine, 2)
    manager = Recorder()
    failing_commit_once["left"] = 1

    with pytest.raises(OperationalError):
        publish_pending_outbox(engine, manager)

    assert manager.sent == [], "nobody hears of an event whose row was not committed"
    assert _statuses(engine) == ["PENDING", "PENDING"]

    assert publish_pending_outbox(engine, manager) == 2
    assert [message["data"]["event_id"] for message in manager.sent] == ids
    assert _statuses(engine) == ["PUBLISHED", "PUBLISHED"]

    # And never again: the rows are PUBLISHED, so the next pass sends nothing.
    assert publish_pending_outbox(engine, manager) == 0
    assert len(manager.sent) == 2


def test_the_async_dispatch_claims_in_a_thread_and_broadcasts_after_the_commit(engine):
    ids = _pending(engine, 3)
    manager = Recorder()

    sent = asyncio.run(dispatch_pending_outbox(engine, manager))

    assert sent == 3
    assert [message["data"]["event_id"] for message in manager.sent] == ids
    assert asyncio.run(dispatch_pending_outbox(engine, manager)) == 0
    assert len(manager.sent) == 3


def test_the_claim_takes_the_write_lock_and_an_empty_outbox_takes_none(engine, monkeypatch):
    taken: list[int] = []
    real = publisher.lock_for_write

    def spy(session: Session) -> None:
        taken.append(1)
        real(session)

    monkeypatch.setattr(publisher, "lock_for_write", spy)
    manager = Recorder()

    # Nothing pending: one cheap read, and the studio's write lock is left alone. The
    # dispatcher runs every second; taking the lock each time would queue every writer.
    assert publish_pending_outbox(engine, manager) == 0
    assert taken == []

    _pending(engine, 1)
    assert publish_pending_outbox(engine, manager) == 1
    assert taken == [1]


def test_live_event_and_replay_preserve_the_committed_agent_version(engine):
    with Session(engine) as session, session.begin():
        row, outbox = append_event_with_outbox(
            session,
            "agent.state_changed",
            "agent",
            "employee",
            17,
            {"runtime_state": "WORKING"},
            str(uuid4()),
        )
        event_id = row.event_id
        assert row.aggregate_version == 17
        assert outbox.payload["aggregate_version"] == 17
    manager = Recorder()
    assert publish_pending_outbox(engine, manager) == 1
    live = manager.sent[0]["data"]
    replay = next(e for e in replay_events(engine) if e["event_id"] == event_id)
    for field in ("aggregate_id", "aggregate_version", "event_type", "payload"):
        assert live[field] == replay[field]
    assert live["aggregate_version"] == 17
