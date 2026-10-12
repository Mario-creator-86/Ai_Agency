"""A day cut off under the studio is resumed by itself after the start (2026-10-12).

The Owner, 07:40: «de acum încolo, să dai singur restart la proiect, nu mă aștepta pe mine!».
A restart during the day ends it INTERRUPTED at its boundary (REL-10), and until today the
clock never ran it again (a whole second run would choose a second subject and buy a second
film) and the letter asked the Owner to press «Pornește rularea de azi». Now the watchdog's
`resume_interrupted_day` pass queues one DAILY_RUN with ``resume_of``: the worker replays the
stages the cut run completed from their record — nothing done again — and runs the stage it
stopped in and the rest. Every provider is faked; the stages are counters; nothing is bought.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import uuid4

from app.models import DomainEvent, OwnerPolicy
from app.runbook.models import DailyRun
from app.runbook.services import (
    BLOCKED,
    COMPLETED,
    DAILY_RUN_TASK,
    DAY_RESUME_QUEUED_EVENT,
    INTERRUPTED,
    STAGES,
    clear_shutdown,
    execute_daily_run,
    request_shutdown,
)
from app.workflows.models import TaskQueueItem
from app.workflows.passes import WatchdogContext
from app.workflows.passes.resume_interrupted_day import resume_interrupted_days
from app.workflows.services import enqueue_task
from app.workflows.worker import build_task_handlers, work_once
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_shutdown import _letters, studio, vault  # noqa: F401

WORK = STAGES[1:]
BEFORE_MEDIA = STAGES[1 : STAGES.index("media")]
FROM_MEDIA = STAGES[STAGES.index("media") :]


def runners(engine, calls: dict[str, int], *, shutdown_in_media: bool) -> dict[str, Any]:
    """Counting stage runners; the media stage of the first day asks the studio to stop."""

    def runner_for(name: str):
        def run() -> dict[str, Any]:
            calls[name] += 1
            if name == "media" and shutdown_in_media:
                request_shutdown(engine)
                return {
                    "status": BLOCKED,
                    "reason": "Oprit înainte de scena 2.",
                    "artefacts": {"bought": [1]},
                }
            return {"status": COMPLETED, "reason": f"{name} gata", "artefacts": {"made": name}}

        return run

    return {name: runner_for(name) for name in WORK}


def run_queue(engine, handlers) -> list[dict[str, Any]]:
    ran = []
    while (result := work_once(engine, handlers)) is not None:
        ran.append(result)
    return ran


def runs_of_today(engine) -> list[DailyRun]:
    with Session(engine) as session:
        rows = list(session.scalars(select(DailyRun).order_by(DailyRun.started_at)))
        session.expunge_all()
        return rows


def test_a_day_cut_off_by_a_shutdown_is_resumed_from_its_stage_and_nothing_is_done_twice(
    engine,
    settings,
    vault,  # noqa: F811
    studio,  # noqa: F811
):
    calls: dict[str, int] = defaultdict(int)
    cut = execute_daily_run(
        engine, settings, vault, stage_runners=runners(engine, calls, shutdown_in_media=True)
    )
    assert cut["status"] == INTERRUPTED and cut["stopped_at_stage"] == "media"
    assert all(calls[name] == 1 for name in BEFORE_MEDIA) and calls["media"] == 1
    assert all(calls[name] == 0 for name in FROM_MEDIA[1:])
    (letter,) = _letters(engine, "day_interrupted")
    assert "o reiau singur" in letter.body_text and "pornești tu" not in letter.body_text
    # The studio shuts down and starts again: the shutdown request is gone with the process.
    clear_shutdown()

    queued = resume_interrupted_days(WatchdogContext(engine, settings, "wd-1"))

    assert queued["queued"] == [cut["id"]]
    # Once: the next tick finds the task queued, the one after finds the day resumed.
    assert resume_interrupted_days(WatchdogContext(engine, settings, "wd-2"))["queued"] == []
    with Session(engine) as session:
        (task,) = session.scalars(
            select(TaskQueueItem).where(TaskQueueItem.task_type == DAILY_RUN_TASK)
        ).all()
        assert task.payload["resume_of"] == cut["id"] and task.payload["stage"] == "media"
        (event,) = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == DAY_RESUME_QUEUED_EVENT)
        ).all()
        assert event.payload["stage"] == "media" and event.aggregate_id == cut["id"]

    handlers = build_task_handlers(
        engine, settings, vault, runners(engine, calls, shutdown_in_media=False), None
    )
    ran = run_queue(engine, handlers)

    assert [r["status"] for r in ran] == ["COMPLETED"], ran
    first, resumed = runs_of_today(engine)
    assert first.status == INTERRUPTED and resumed.status == COMPLETED
    stages = {stage["stage"]: stage for stage in resumed.stages_json}
    for name in BEFORE_MEDIA:
        assert calls[name] == 1, name  # not run again
        assert stages[name]["status"] == COMPLETED
        assert "reluată din rularea întreruptă" in stages[name]["reason"], stages[name]
        assert stages[name]["artefacts"] == {"made": name}
    for name in FROM_MEDIA:
        assert stages[name]["status"] == COMPLETED
        assert "reluată" not in stages[name]["reason"], stages[name]
    assert calls["media"] == 2 and all(calls[name] == 1 for name in FROM_MEDIA[1:])
    assert resume_interrupted_days(WatchdogContext(engine, settings, "wd-3"))["queued"] == []
    assert len(_letters(engine, "day_interrupted")) == 1


def test_nothing_is_queued_while_the_studio_stops_or_a_run_is_already_in_hands(
    engine,
    settings,
    vault,  # noqa: F811
    studio,  # noqa: F811
):
    calls: dict[str, int] = defaultdict(int)
    cut = execute_daily_run(
        engine, settings, vault, stage_runners=runners(engine, calls, shutdown_in_media=True)
    )
    assert cut["status"] == INTERRUPTED
    # Still shutting down: nothing is queued.
    assert resume_interrupted_days(WatchdogContext(engine, settings, "wd-1"))["queued"] == []
    clear_shutdown()
    # His stop: nothing is queued either.
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True
    assert resume_interrupted_days(WatchdogContext(engine, settings, "wd-2"))["queued"] == []
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    # A DAILY_RUN already queued (his button): the day is in hands.
    enqueue_task(
        engine,
        DAILY_RUN_TASK,
        {"manual": True, "date": cut["business_date"]},
        priority=10,
        max_attempts=1,
        idempotency_key=f"manual-run-{uuid4()}",
    )
    assert resume_interrupted_days(WatchdogContext(engine, settings, "wd-3"))["queued"] == []


def test_a_resume_of_a_day_that_passed_or_was_finished_is_skipped(
    engine,
    settings,
    vault,  # noqa: F811
    studio,  # noqa: F811
):
    calls: dict[str, int] = defaultdict(int)
    done = execute_daily_run(
        engine, settings, vault, stage_runners=runners(engine, calls, shutdown_in_media=False)
    )
    assert done["status"] == COMPLETED
    with Session(engine) as session, session.begin():
        session.add(
            DailyRun(
                id=str(uuid4()),
                business_date="2026-10-11",
                preflight_status="OK",
                preflight_json={},
                status=INTERRUPTED,
                stages_json=[],
                stages_total=0,
                stages_completed=0,
                started_at="2026-10-11T02:00:00+00:00",
                finished_at="2026-10-11T02:30:00+00:00",
            )
        )
        yesterday = session.scalar(
            select(DailyRun.id).where(DailyRun.business_date == "2026-10-11")
        )
    for resume_of, words in (
        (done["id"], "nu mai are nimic de reluat"),
        (yesterday, "care a trecut"),
    ):
        enqueue_task(
            engine,
            DAILY_RUN_TASK,
            {"resume_of": resume_of, "date": done["business_date"]},
            priority=8,
            max_attempts=1,
            idempotency_key=f"daily-resume-{resume_of}",
        )
        (ran,) = run_queue(engine, build_task_handlers(engine, settings, vault, {}, None))
        assert ran["status"] == "COMPLETED", ran
        assert ran["outcome"]["status"] == "SKIPPED" and words in ran["outcome"]["reason"], ran
    assert len(runs_of_today(engine)) == 2  # the finished day and yesterday's row: no new run
    assert all(calls[name] == 1 for name in WORK)
