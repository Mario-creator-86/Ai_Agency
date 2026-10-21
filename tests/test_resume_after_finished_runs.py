"""A day cut off after other runs of its date is still resumed, and asked for once per start.

Measured 2026-10-15 (01:47–04:40 Bucharest) on the live studio: the run fd287887 was cut off
by two restarts, with two finished runs already on its date. Its one resume task was refused
by the worker («și-a folosit cele 3 încercări»: the cap on the day's re-attempts counted the
finished runs), and from then on every watchdog tick found that finished task under the key
`daily-resume-<run>`, wrote «daily run resume queued» again — eighteen times — and resumed
nothing; the 05:00 clock run then refused the cut-off day too. The Owner's letter had promised
«o reiau singur». Now a resume is bounded by how many times the day was cut off, not by how
many runs its date has, and the pass asks once per interrupted run per start of the studio,
announcing only a task that is new. Every provider is faked; the stages are counters.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import uuid4

import pytest
from app.models import DomainEvent
from app.runbook.models import DailyRun
from app.runbook.services import (
    COMPLETED,
    DAILY_RUN_TASK,
    DAY_RESUME_QUEUED_EVENT,
    INTERRUPTED,
    clear_shutdown,
    execute_daily_run,
)
from app.workflows.models import TaskQueueItem
from app.workflows.passes import WatchdogContext
from app.workflows.passes import resume_interrupted_day as pass_module
from app.workflows.passes.resume_interrupted_day import resume_interrupted_days
from app.workflows.services import enqueue_task
from app.workflows.worker import build_task_handlers
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_resume_interrupted_day import run_queue, runners, runs_of_today
from test_shutdown import studio, vault  # noqa: F401


def _finished_run(session: Session, date_iso: str, started_at: str, status: str) -> str:
    """An earlier run of the same date, as the clock or the Owner's button leaves one."""
    run_id = str(uuid4())
    session.add(
        DailyRun(
            id=run_id,
            business_date=date_iso,
            preflight_status="DEGRADED",
            preflight_json={},
            status=status,
            stages_json=[],
            stages_total=13,
            stages_completed=13 if status == COMPLETED else 6,
            started_at=started_at,
            finished_at=started_at,
        )
    )
    return run_id


def _resume_events(engine) -> list[DomainEvent]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == DAY_RESUME_QUEUED_EVENT)
            )
        )
        session.expunge_all()
        return rows


def test_a_day_cut_off_after_finished_runs_of_its_date_is_still_resumed(
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
    clear_shutdown()
    # Enough runs of the same date finished before it that, with the cut-off one, the day's
    # attempts are all used as they were counted before (measured: the clock's at 05:00 and
    # one from the Owner's button, with daily_max_attempts at its default of 3).
    with Session(engine) as session, session.begin():
        for hour in range(settings.daily_max_attempts - 1):
            _finished_run(
                session, cut["business_date"], f"2000-01-01T0{hour}:00:00+00:00", COMPLETED
            )

    queued = resume_interrupted_days(WatchdogContext(engine, settings, "wd-1"))
    assert queued["queued"] == [cut["id"]]

    handlers = build_task_handlers(
        engine, settings, vault, runners(engine, calls, shutdown_in_media=False), None
    )
    (ran,) = run_queue(engine, handlers)

    assert ran["status"] == "COMPLETED", ran
    assert ran["outcome"]["status"] == COMPLETED, ran["outcome"]
    assert ran["outcome"]["resumed_from"] == cut["id"]
    assert "încercări" not in str(ran["outcome"].get("reason", ""))
    resumed = runs_of_today(engine)[-1]
    assert resumed.status == COMPLETED and resumed.id != cut["id"]
    assert calls["media"] == 2  # the stage it stopped in ran again, the earlier ones did not
    assert resume_interrupted_days(WatchdogContext(engine, settings, "wd-2"))["queued"] == []


def test_a_day_cut_off_more_times_than_the_day_has_attempts_is_still_resumed(
    engine,
    settings,
    vault,  # noqa: F811
    studio,  # noqa: F811
):
    calls: dict[str, int] = defaultdict(int)
    cut = execute_daily_run(
        engine, settings, vault, stage_runners=runners(engine, calls, shutdown_in_media=True)
    )
    clear_shutdown()
    with Session(engine) as session, session.begin():
        for hour in range(settings.daily_max_attempts):
            _finished_run(
                session, cut["business_date"], f"2000-01-01T0{hour}:00:00+00:00", INTERRUPTED
            )
    enqueue_task(
        engine,
        DAILY_RUN_TASK,
        {"resume_of": cut["id"], "date": cut["business_date"]},
        priority=8,
        max_attempts=1,
        idempotency_key=f"daily-resume-{cut['id']}-test",
    )
    (ran,) = run_queue(
        engine,
        build_task_handlers(
            engine, settings, vault, runners(engine, calls, shutdown_in_media=False), None
        ),
    )
    # 2026-10-15 17:17Z: the day's fifth cut (a developer restart) was refused «reluarea ei
    # este decizia Owner-ului» and the day stood still; the Owner's rule is that the day
    # ends on its goal, and a resume is asked once per start, so the cuts are no cap.
    assert ran["status"] == "COMPLETED", ran
    assert ran["outcome"]["status"] != "SKIPPED", ran["outcome"]
    assert ran["outcome"].get("resumed_from") == cut["id"]
    assert calls["media"] == 2  # the cut stage ran again; the finished ones were replayed


def test_a_finished_resume_task_is_not_announced_again_until_the_next_start(
    engine,
    settings,
    vault,  # noqa: F811
    studio,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    calls: dict[str, int] = defaultdict(int)
    cut = execute_daily_run(
        engine, settings, vault, stage_runners=runners(engine, calls, shutdown_in_media=True)
    )
    clear_shutdown()
    monkeypatch.setattr(pass_module, "START_TOKEN", "start-one")

    first = resume_interrupted_days(WatchdogContext(engine, settings, "wd-1"))
    assert first["queued"] == [cut["id"]]
    # The worker took it and answered (here: it finished without resuming, as a refusal does).
    with Session(engine) as session, session.begin():
        task = session.get(TaskQueueItem, first["task_id"])
        assert task.idempotency_key == f"daily-resume-{cut['id']}-start-one"
        task.status = "COMPLETED"
        task.attempts = 1

    for tick in ("wd-2", "wd-3", "wd-4"):
        held = resume_interrupted_days(WatchdogContext(engine, settings, tick))
        assert held["queued"] == [] and held.get("asked") == first["task_id"], held
    assert len(_resume_events(engine)) == 1
    with Session(engine) as session:
        days = session.scalars(
            select(TaskQueueItem.id).where(TaskQueueItem.task_type == DAILY_RUN_TASK)
        ).all()
        assert days == [first["task_id"]]

    # The studio starts again: one more resume of the same run, announced once more.
    monkeypatch.setattr(pass_module, "START_TOKEN", "start-two")
    again = resume_interrupted_days(WatchdogContext(engine, settings, "wd-5"))
    assert again["queued"] == [cut["id"]] and again["task_id"] != first["task_id"]
    assert len(_resume_events(engine)) == 2
    assert resume_interrupted_days(WatchdogContext(engine, settings, "wd-6"))["queued"] == []
    assert len(_resume_events(engine)) == 2
