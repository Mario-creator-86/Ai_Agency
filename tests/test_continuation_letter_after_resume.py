"""The studio says it resumes an interrupted film only once it has (the audit of 2026-10-16,
SAFE-007).

A film's continuation a dead process cut off is queued again by the studio itself, once
(`resume_interrupted_continuations`), and the Owner gets no letter about it. The worker used to
decide «the studio resumes it» before the resume ran: if the resume failed (a warning in the
log), the pass still reported it resumed, and if it kept failing until the continuation left
its six-hour window, it was never resumed and nobody was told. Now the pass reports a resume
only after it happened; one still waiting is reported as waiting, with no letter; and one the
studio was to resume that is still not resumed when the window closes is a note for the
developer — his letters rule (2026-10-12) keeps the Owner's letters for accounts,
authorisations and security — written once.

No model is called and nothing is bought.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.agents.director import DEVELOPER_DEFECT_KIND
from app.agents.messages import is_for_owner
from app.agents.models import AgentMessage
from app.agents.services import seed_initial_workforce
from app.workflows import worker
from app.workflows.models import TaskQueueItem
from app.workflows.services import INTERRUPTED, RESUME_CONTINUATION_HOURS
from app.workflows.worker import worker_pass
from sqlalchemy import select
from sqlalchemy.orm import Session


def _stamp(minutes_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


def _continuation(engine, *, storyboard: str, minutes_ago: float, **fields) -> str:
    task_id = str(uuid4())
    stamp = _stamp(minutes_ago)
    row = {
        "id": task_id,
        "task_type": "FILM_CONTINUE",
        "payload": {"storyboard_id": storyboard},
        "priority": 0,
        "status": "DEAD_LETTER",
        "attempts": 1,
        "max_attempts": 1,
        "backoff_seconds": 5,
        "next_attempt_at": stamp,
        "created_at": stamp,
        "updated_at": stamp,
        "idempotency_key": f"film-continue-{storyboard}-{task_id[:6]}",
        "error_detail": f"{INTERRUPTED}: procesul care rula sarcina s-a oprit",
    }
    row.update(fields)
    with Session(engine) as session, session.begin():
        session.add(TaskQueueItem(**row))
    return task_id


def _cut_off_now(engine, storyboard: str) -> str:
    """A continuation whose process died: leased, its lease lapsed, no attempt left."""
    return _continuation(
        engine,
        storyboard=storyboard,
        minutes_ago=30,
        status="RUNNING",
        error_detail=None,
        # Renewed by this process (a lease from before it began is given back instead).
        updated_at=_stamp(0),
        lease_token="worker_main:dead",
        lease_expires_at=_stamp(5),
    )


def _status(engine, task_id: str) -> str:
    with Session(engine) as session:
        return session.get(TaskQueueItem, task_id).status


def _letters(engine) -> list[AgentMessage]:
    with Session(engine) as session:
        rows = list(session.scalars(select(AgentMessage)))
        session.expunge_all()
        return rows


def test_a_resume_that_failed_is_not_reported_as_resumed_and_no_letter_is_written(
    engine, monkeypatch
):
    seed_initial_workforce(engine)
    task_id = _cut_off_now(engine, "7c26a7ce")

    def broken(*_args, **_kwargs):
        raise RuntimeError("database is locked")

    real = worker.resume_interrupted_continuations
    monkeypatch.setattr(worker, "resume_interrupted_continuations", broken)

    first = worker_pass(engine, {})

    (record,) = [item for item in first["interrupted"] if item["id"] == task_id]
    assert not record.get("resumes"), record
    assert record.get("resume_pending") is True and "letter_id" not in record
    assert _status(engine, task_id) == "DEAD_LETTER"
    assert not any(is_for_owner(row) for row in _letters(engine))

    # The next pass resumes it (queued again; the autonomy stop of a fresh studio keeps the
    # queue from running it here).
    monkeypatch.setattr(worker, "resume_interrupted_continuations", real)
    worker_pass(engine, {})
    assert _status(engine, task_id) == "QUEUED"


def test_a_resume_that_happened_is_reported_with_the_task_queued_again(engine):
    seed_initial_workforce(engine)
    task_id = _cut_off_now(engine, "87c05891")

    result = worker_pass(engine, {})

    (record,) = [item for item in result["interrupted"] if item["id"] == task_id]
    assert record.get("resumes") is True and "letter_id" not in record
    assert _status(engine, task_id) == "QUEUED"
    assert not any(is_for_owner(row) for row in _letters(engine))


def test_a_continuation_never_resumed_in_its_window_is_a_note_for_the_developer(engine):
    seed_initial_workforce(engine)
    window = RESUME_CONTINUATION_HOURS * 60
    missed = _continuation(engine, storyboard="babcf272", minutes_ago=window + 20)
    # Older than the scan, or walked by a later continuation: neither is a defect.
    _continuation(engine, storyboard="0ld0ld00", minutes_ago=3 * window)
    walked = _continuation(engine, storyboard="f06808c9", minutes_ago=window + 20)
    _continuation(
        engine,
        storyboard="f06808c9",
        minutes_ago=window,
        status="COMPLETED",
        error_detail=None,
    )

    worker_pass(engine, {})
    worker_pass(engine, {})  # written once

    notes = [
        row
        for row in _letters(engine)
        if (row.body_json or {}).get("kind") == DEVELOPER_DEFECT_KIND
    ]
    assert len(notes) == 1, [row.subject for row in notes]
    (note,) = notes
    assert note.body_json["task_id"] == missed and note.body_json["storyboard_id"] == "babcf272"
    assert note.intent == "STATUS" and note.status == "RESOLVED"
    assert not is_for_owner(note)
    assert f"{RESUME_CONTINUATION_HOURS} ore" in note.body_text
    assert walked not in {row.body_json.get("task_id") for row in notes}
    assert not any(is_for_owner(row) for row in _letters(engine))
