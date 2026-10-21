"""What a dead process left is taken up by the studio itself (2026-10-16 06:07:53Z): the
leases it held are given back on every worker pass, not only at the start whose own release
had failed on the database the stopping process still held; and a film's continuation it
interrupted is queued again, once, instead of waiting for the Owner's hand. A day it left
after its run began is never given back (run again whole it would buy a second film): it is
closed INTERRUPTED, for its run to be resumed from its stage; one it left before its run began
bought nothing and has no run to resume, so it is given back like any task (review
2026-10-16)."""

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


def _run_begun(engine, task_id: str) -> None:
    """The day's start event, carrying its task's id, as `runbook.services._begin_run` writes
    it with the run's row after the free preflight: what a process killed after that leaves."""
    from app.services import append_event

    with Session(engine) as session, session.begin():
        append_event(
            session,
            "runbook.daily_run_started",
            "daily_run",
            str(uuid4()),
            1,
            {"date": datetime.now(UTC).date().isoformat()},
            task_id,
        )


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


def test_a_day_a_dead_process_left_claimed_is_closed_not_given_back(engine):
    """Review 2026-10-16: the release gave a DAILY_RUN back to the queue like any task, and a
    day run again from its start chooses a second subject and buys a second film. It is
    closed INTERRUPTED instead — at the start (every leased task is an orphan) and on the
    pass (one leased before this process began) — for its run to be resumed from its stage.
    A day killed before its run began is given back instead: closed, nothing would resume it,
    though the letter about it says it will."""
    started = _stamp(5)
    day = _task(
        engine,
        status="CLAIMED",
        updated_minutes_ago=10,
        storyboard="",
        task_type="DAILY_RUN",
        payload={"manual": True},
        lease_token="worker_main:dead",
        lease_expires_at=_stamp(-50),
    )
    walk = _task(
        engine,
        status="CLAIMED",
        updated_minutes_ago=10,
        storyboard="7c26a7ce",
        lease_token="worker_main:dead-too",
        lease_expires_at=_stamp(-50),
    )
    alive = _task(
        engine,
        status="CLAIMED",
        updated_minutes_ago=1,
        storyboard="",
        task_type="DAILY_RUN",
        payload={"manual": True},
        lease_token="worker_main:this-process",
        lease_expires_at=_stamp(-50),
    )
    # Killed in the preflight: the GO had bought nothing and written no run.
    unbegun = _task(
        engine,
        status="CLAIMED",
        updated_minutes_ago=10,
        storyboard="",
        task_type="DAILY_RUN",
        payload={"manual": True},
        lease_token="worker_main:dead-in-preflight",
        lease_expires_at=_stamp(-50),
    )
    _run_begun(engine, day)
    _run_begun(engine, alive)

    assert release_orphaned_claims(engine, started_at=started) == 2
    assert _row(engine, walk).status == "QUEUED"
    assert _row(engine, day).status == "CLAIMED", "a day whose run began is never queued again"
    given_back = _row(engine, unbegun)
    assert given_back.status == "QUEUED" and given_back.lease_token is None
    assert given_back.attempts == 1
    with Session(engine) as session:
        released = {
            event.aggregate_id: event.payload["reason"]
            for event in session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == "workflow.task_released")
            )
        }
    assert set(released) == {walk, unbegun} and "înainte ca ziua să înceapă" in released[unbegun]

    from app.workflows.services import TASK_INTERRUPTED_EVENT, interrupt_orphaned_claims

    (closed,) = interrupt_orphaned_claims(engine, started_at=started)

    assert closed["id"] == day
    row = _row(engine, day)
    assert row.status == "DEAD_LETTER" and row.lease_token is None and row.attempts == 1
    assert str(row.error_detail).startswith(INTERRUPTED)
    assert _row(engine, alive).status == "CLAIMED"  # this process's own day
    with Session(engine) as session:
        (event,) = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == TASK_INTERRUPTED_EVENT)
        )
        assert event.aggregate_id == day and event.payload["orphaned"] is True
    assert interrupt_orphaned_claims(engine, started_at=started) == []
    # At the start every leased task is an orphan: the day this process had not yet claimed
    # is closed too, and the release still gives none back.
    assert release_orphaned_claims(engine) == 0
    assert [item["id"] for item in interrupt_orphaned_claims(engine)] == [alive]


def test_a_continuation_resumed_once_and_cut_off_again_is_left_to_the_next_daily_run(engine):
    """Resumed once, a continuation cut off again is not queued a second time: a crash loop
    cannot walk a film without end, and the letter that says so is then true. Asked before
    the Owner is told (`continuation_resumes`), the answer is the resume's own."""
    from app.services import append_event

    fresh = _task(
        engine,
        status="DEAD_LETTER",
        updated_minutes_ago=2,
        storyboard="7c26a7ce",
        error_detail=f"{INTERRUPTED}: procesul care rula sarcina s-a oprit",
    )
    again = _task(
        engine,
        status="DEAD_LETTER",
        updated_minutes_ago=2,
        storyboard="87c05891",
        attempts=2,
        max_attempts=2,
        error_detail=f"{INTERRUPTED}: procesul care rula sarcina s-a oprit",
    )
    with Session(engine) as session, session.begin():
        # Its first resume, before this second cut.
        append_event(
            session,
            TASK_RESUMED_EVENT,
            "task_queue",
            again,
            1,
            {"task_type": "FILM_CONTINUE", "storyboard_id": "87c05891", "max_attempts": 2},
            str(uuid4()),
        )

    assert resume_interrupted_continuations(engine) == 1

    assert _row(engine, fresh).status == "QUEUED"
    assert _row(engine, again).status == "DEAD_LETTER"

    from app.workflows.services import continuation_resumes

    later = _task(
        engine,
        status="DEAD_LETTER",
        updated_minutes_ago=1,
        storyboard="babcf272",
        error_detail=f"{INTERRUPTED}: procesul care rula sarcina s-a oprit",
    )
    assert continuation_resumes(engine, later) is True
    assert continuation_resumes(engine, again) is False
    assert continuation_resumes(engine, fresh) is False  # queued again already
    assert continuation_resumes(engine, str(uuid4())) is False  # not a dead continuation
