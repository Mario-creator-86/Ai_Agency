"""What a dead process left is taken up by the studio itself (2026-10-16 06:07:53Z): the
leases it held are given back on every worker pass, not only at the start whose own release
had failed on the database the stopping process still held; and a film's continuation it
interrupted is queued again, once, instead of waiting for the Owner's hand."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.models import DomainEvent
from app.workflows.models import TaskQueueItem
from app.workflows.services import (
    INTERRUPTED,
    TASK_RESUMED_EVENT,
    release_orphaned_claims,
    resume_interrupted_continuations,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


def _stamp(minutes_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


def _task(engine, *, status: str, updated_minutes_ago: float, storyboard: str, **extra) -> str:
    task_id = str(uuid4())
    stamp = _stamp(updated_minutes_ago)
    fields = {
        "id": task_id,
        "task_type": "FILM_CONTINUE",
        "payload": {"storyboard_id": storyboard},
        "priority": 0,
        "status": status,
        "attempts": 1,
        "max_attempts": 1,
        "backoff_seconds": 5,
        "next_attempt_at": stamp,
        "created_at": stamp,
        "updated_at": stamp,
        "idempotency_key": f"film-continue-{storyboard}-{task_id[:6]}",
    }
    fields.update(extra)
    with Session(engine) as session, session.begin():
        session.add(TaskQueueItem(**fields))
    return task_id


def _row(engine, task_id: str) -> TaskQueueItem:
    with Session(engine) as session:
        return session.get(TaskQueueItem, task_id)


def test_a_lease_from_before_this_process_began_is_given_back_on_the_pass(engine):
    started = _stamp(5)
    orphan = _task(
        engine,
        status="CLAIMED",
        updated_minutes_ago=10,
        storyboard="7c26a7ce",
        lease_token="worker_main:old",
        lease_expires_at=_stamp(-50),  # fifty minutes still to run on the lease
    )
    alive = _task(
        engine,
        status="CLAIMED",
        updated_minutes_ago=1,
        storyboard="87c05891",
        lease_token="worker_main:new",
        lease_expires_at=_stamp(-50),
    )

    assert release_orphaned_claims(engine, started_at=started) == 1

    freed = _row(engine, orphan)
    assert freed.status == "QUEUED" and freed.lease_token is None and freed.attempts == 1
    assert freed.next_attempt_at <= datetime.now(UTC).isoformat()
    assert _row(engine, alive).status == "CLAIMED"  # this process's own claim
    # Nothing to do the second time: no write for an empty answer.
    assert release_orphaned_claims(engine, started_at=started) == 0


def test_an_interrupted_continuation_is_queued_again_once_and_an_old_one_is_not(engine):
    recent = _task(
        engine,
        status="DEAD_LETTER",
        updated_minutes_ago=20,
        storyboard="7c26a7ce",
        error_detail=f"{INTERRUPTED}: procesul care rula sarcina s-a oprit",
    )
    walked_since = _task(
        engine,
        status="DEAD_LETTER",
        updated_minutes_ago=30,
        storyboard="2d276038",
        error_detail=f"{INTERRUPTED}: procesul care rula sarcina s-a oprit",
    )
    _task(engine, status="COMPLETED", updated_minutes_ago=10, storyboard="2d276038")
    ancient = _task(
        engine,
        status="DEAD_LETTER",
        updated_minutes_ago=60 * 24,
        storyboard="babcf272",
        error_detail=f"{INTERRUPTED}: procesul care rula sarcina s-a oprit",
    )
    failed = _task(
        engine,
        status="DEAD_LETTER",
        updated_minutes_ago=20,
        storyboard="aaaaaaaa",
        error_detail="FILM_BUSY: alt cumpărător",
    )

    assert resume_interrupted_continuations(engine) == 1

    row = _row(engine, recent)
    assert row.status == "QUEUED" and row.max_attempts == 2 and row.attempts == 1
    assert row.error_detail is None and row.lease_token is None
    assert _row(engine, walked_since).status == "DEAD_LETTER"  # its film was walked since
    assert _row(engine, ancient).status == "DEAD_LETTER"
    assert _row(engine, failed).status == "DEAD_LETTER"  # not an interruption
    with Session(engine) as session:
        (event,) = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == TASK_RESUMED_EVENT)
        )
        assert event.aggregate_id == recent
        assert event.payload["storyboard_id"] == "7c26a7ce" and event.payload["max_attempts"] == 2
    # Resumed once: the row is QUEUED now, not DEAD_LETTER, so nothing is resumed again.
    assert resume_interrupted_continuations(engine) == 0
