"""The automatic sheet repair never runs forever (the Owner, 2026-10-03, on a card: "Repară te
rog. Și pune și o siguranță să nu meargă la infinit").

Measured on his studio the same morning: the worker's scan queued a new repair of the LHC film's
sheet every five minutes, from 08:04 to 09:07 UTC and on, each one UNRESOLVED, because every
call on the language-model connection failed. The repair still continues without asking him,
as it was built to; what changes:

- the first retry of the same blockers is immediate, then each one waits twice as long as the
  one before (one scan interval, two, four...), never more than six hours;
- at most five attempts a day on the same blockers; a changed sheet starts again from zero;
- no attempt while the language model is failing: the last runs all failed at the provider;
- when the repair pauses, ONE letter tells the Owner why and what unblocks it; it is closed by
  itself when the repair resumes.

The model is never called here; the queue, the letters and the runs are read from the database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentMessage, AgentRun
from app.media import blocker_repair as repair
from app.workflows.models import TaskQueueItem
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_sheet_blocker_repair import film, sheet  # noqa: F401 - the fixture is used by name


@pytest.fixture(autouse=True)
def a_studio_running_since_long_ago(monkeypatch):
    """These tests date attempts hours back; the studio has been running all that time."""
    monkeypatch.setattr(repair, "STUDIO_STARTED_AT", datetime(2000, 1, 1, tzinfo=UTC))


def unresolved(engine, dispatched: dict, *, minutes_ago: float = 0) -> None:
    """The worker ran the task and the repair did not clear the blockers."""
    with Session(engine) as session, session.begin():
        task_row = session.get(TaskQueueItem, dispatched["task_id"])
        task_row.status = "COMPLETED"
        report = session.get(AgentMessage, dispatched["message_id"])
        body = dict(report.body_json)
        if minutes_ago:
            now = datetime.now(UTC)
            when = now - timedelta(minutes=minutes_ago)
            task_row.created_at = when.isoformat()
            # The dispatch key carries the day the attempt was made: a task moved back across
            # midnight (UTC) keeps its own day, and stays unique, as one really made then would.
            # Without this the tests failed every morning before 10:00 UTC (attempt 1's key
            # came back and the old, finished task was answered instead of a new attempt).
            today = f"-{now.date().isoformat()}-"
            then = f"-{when.date().isoformat()}-{task_row.id[:8]}-"
            task_row.idempotency_key = str(task_row.idempotency_key).replace(today, then)
            body["dispatch_key"] = str(body.get("dispatch_key", "")).replace(today, then)
        report.body_json = {
            **body,
            "repair_result": {"status": "UNRESOLVED", "reason": "Instrumentul a eșuat."},
        }


def repair_tasks(engine) -> int:
    with Session(engine) as session:
        return len(
            list(
                session.scalars(
                    select(TaskQueueItem).where(TaskQueueItem.task_type == repair.REPAIR_TASK)
                )
            )
        )


def paused_letters(engine, *, open_only: bool = True) -> list[AgentMessage]:
    with Session(engine) as session:
        letters = [
            m
            for m in session.scalars(select(AgentMessage))
            if (m.body_json or {}).get("kind") == repair.PAUSED_KIND
            and (m.status == "OPEN" or not open_only)
        ]
        session.expunge_all()
        return letters


def model_runs(engine, *statuses: str, detail: str = "ProviderHTTPError: HTTP 401") -> None:
    """The studio's latest model runs, newest last."""
    with Session(engine) as session, session.begin():
        agent = session.scalars(select(Agent)).first()
        start = datetime.now(UTC) - timedelta(seconds=len(statuses))
        for n, status in enumerate(statuses):
            session.add(
                AgentRun(
                    id=str(uuid4()),
                    agent_id=agent.id,
                    task_type="t",
                    objective="o",
                    prompt_template_version="v1",
                    model_name="m",
                    provider_name="p",
                    status=status,
                    error_detail=detail if status == "FAILED" else None,
                    correlation_id=str(uuid4()),
                    started_at=(start + timedelta(seconds=n)).isoformat(),
                    context_json={},
                )
            )


def test_the_first_retry_is_immediate_and_the_next_ones_wait_longer(engine, film):  # noqa: F811
    reading = sheet(engine, film)
    first = repair.submit_sheet_issues(engine, reading)
    unresolved(engine, first)
    second = repair.submit_sheet_issues(engine, reading)
    assert second["task_id"] != first["task_id"]

    unresolved(engine, second)
    waiting = repair.submit_sheet_issues(engine, reading)

    assert waiting["status"] == "BACKING_OFF" and waiting.get("retry_after")
    assert repair_tasks(engine) == 2


def test_once_the_wait_has_passed_the_repair_continues(engine, film):  # noqa: F811
    reading = sheet(engine, film)
    first = repair.submit_sheet_issues(engine, reading)
    unresolved(engine, first, minutes_ago=30)
    second = repair.submit_sheet_issues(engine, reading)
    unresolved(engine, second, minutes_ago=20)

    third = repair.submit_sheet_issues(engine, reading)

    assert third.get("task_id") and third["task_id"] not in (first["task_id"], second["task_id"])


def test_five_attempts_a_day_on_the_same_blockers_then_one_letter_and_a_pause(
    engine,
    film,  # noqa: F811
):
    reading = sheet(engine, film)
    for n in range(repair.MAX_SAME_ISSUES_PER_DAY):
        dispatched = repair.submit_sheet_issues(engine, reading)
        assert dispatched.get("task_id"), (n, dispatched)
        unresolved(engine, dispatched, minutes_ago=600 - n)

    paused = repair.submit_sheet_issues(engine, reading)
    again = repair.submit_sheet_issues(engine, reading)

    assert paused["status"] == "PAUSED" and again["status"] == "PAUSED"
    assert repair_tasks(engine) == repair.MAX_SAME_ISSUES_PER_DAY
    (letter,) = paused_letters(engine)
    assert letter.body_json.get("owner_attention") is True
    assert "de 5 ori" in letter.body_text and "foaia se schimbă" in letter.body_text


def test_a_changed_sheet_starts_again_from_zero(engine, film):  # noqa: F811
    reading = sheet(engine, film)
    for n in range(repair.MAX_SAME_ISSUES_PER_DAY):
        dispatched = repair.submit_sheet_issues(engine, reading)
        unresolved(engine, dispatched, minutes_ago=600 - n)
    assert repair.submit_sheet_issues(engine, reading)["status"] == "PAUSED"

    changed = repair.submit_sheet_issues(engine, {**reading, "sheet_hash": str(uuid4())})

    assert changed.get("task_id")
    assert paused_letters(engine) == [], "the pause letter is closed when the repair resumes"


def test_no_attempt_while_the_language_model_is_failing_and_one_letter_says_so(
    engine,
    film,  # noqa: F811
):
    reading = sheet(engine, film)
    first = repair.submit_sheet_issues(engine, reading)
    unresolved(engine, first, minutes_ago=60)
    model_runs(engine, "FAILED", "FAILED", "FAILED", "FAILED")

    paused = repair.submit_sheet_issues(engine, reading)
    repair.submit_sheet_issues(engine, reading)

    assert paused["status"] == "PAUSED" and paused["cause"] == "LANGUAGE_MODEL_DOWN"
    assert repair_tasks(engine) == 1
    (letter,) = paused_letters(engine)
    assert "modelul de limbaj" in letter.body_text and "HTTP 401" in letter.body_text


def test_after_the_model_answers_again_the_repair_resumes(engine, film):  # noqa: F811
    reading = sheet(engine, film)
    first = repair.submit_sheet_issues(engine, reading)
    unresolved(engine, first, minutes_ago=60)
    model_runs(engine, "FAILED", "FAILED", "FAILED")
    assert repair.submit_sheet_issues(engine, reading)["status"] == "PAUSED"

    model_runs(engine, "SUCCEEDED")
    resumed = repair.submit_sheet_issues(engine, reading)

    assert resumed.get("task_id") and resumed["task_id"] != first["task_id"]
    assert paused_letters(engine) == []
    (closed,) = paused_letters(engine, open_only=False)
    assert closed.status != "OPEN"


def test_after_a_restart_the_repair_gets_its_attempts_back(engine, film, monkeypatch):  # noqa: F811
    """The Owner, 2026-10-03: "Trebuie să înțelegem de ce problema nu se rezolvă, să reparăm,
    și să îi lăsăm pe ei să rezolve." A repair paused on a cause that was in the studio's code
    (the chart highlight that refused every rewrite) must try again once the fixed studio runs,
    without him; within one run of the studio the ceiling still holds."""
    reading = sheet(engine, film)
    for n in range(repair.MAX_SAME_ISSUES_PER_DAY):
        dispatched = repair.submit_sheet_issues(engine, reading)
        unresolved(engine, dispatched, minutes_ago=600 - n)
    assert repair.submit_sheet_issues(engine, reading)["status"] == "PAUSED"

    monkeypatch.setattr(repair, "STUDIO_STARTED_AT", datetime.now(UTC) - timedelta(minutes=1))
    resumed = repair.submit_sheet_issues(engine, reading)

    assert resumed.get("task_id"), resumed
    assert paused_letters(engine) == []


def test_a_scene_with_no_model_in_the_catalogue_says_so_instead_of_an_empty_list():
    """The Owner's LHC sheet read "Niciun model din setul aprobat nu poate filma această scenă:
    ." on every scene: the reasons were the excluded models', and none had been considered."""
    from app.media.production_policy import need_from_scene, plan_scene_models

    need = need_from_scene(
        {
            "scene_index": 1,
            "scene_kind": "LIVE",
            "duration_seconds": 5.0,
            "prompt_json": {
                "still_prompt": "A wide shot of a dark valley at dawn, mist over the river.",
                "motion_prompt": "Slow push-in over the valley.",
            },
        },
        1,
    )

    plan = plan_scene_models([need], [])

    (entry,) = plan["scenes"]
    assert entry["status"] == "NEEDS_OWNER"
    assert ": ." not in entry["reason_ro"]
    assert "catalog" in entry["reason_ro"].lower()
