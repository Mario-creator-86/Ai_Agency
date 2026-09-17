"""The studio running without the browser: scheduler, queue and worker, joined.

Before this the scheduler could be ticked and the queue could be claimed, and nothing did either
on its own. A daily job would sit with `next_run_at` in the past forever. These tests drive the
worker by hand — the background loop is off under test — and hold it to what makes autonomy safe:

  * a due job becomes exactly one queued task, however many ticks or restarts see it;
  * a missed slot fires once, and the policy decides only what the cadence is afterwards;
  * nothing fires while the Owner's autonomy stop is set;
  * the scheduled daily run runs at most once per business date;
  * a task nobody can execute is dead-lettered with the reason, not retried into the ground.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.integrations.vault import CredentialVault
from app.models import OwnerPolicy
from app.runbook.models import DailyRun
from app.runbook.services import SafeModeActive
from app.runbook.weekly import WEEKLY_JOB_NAME
from app.workflows.models import ScheduledJob, TaskQueueItem
from app.workflows.services import (
    enqueue_task,
    ensure_scheduled_job,
    next_run_after,
    scheduler_tick,
)
from app.workflows.worker import (
    DAILY_JOB_NAME,
    DAILY_RUN,
    DIRECTOR_LOOP,
    DIRECTOR_LOOP_JOB_NAME,
    MODEL_RESEARCH,
    MODEL_RESEARCH_JOB_NAME,
    MODEL_REVIEW,
    MODEL_REVIEW_JOB_NAME,
    TRENDS_JOB_NAME,
    TRENDS_REFRESH,
    NonRetryable,
    build_task_handlers,
    work_once,
    worker_pass,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def _autonomy(engine, stopped: bool) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = stopped


def _due_job(engine, *, name: str = "daily_main", policy: str = "CATCH_UP", late_by=None) -> str:
    job = ensure_scheduled_job(
        engine, name=name, workflow_type=DAILY_RUN, interval_seconds=86400, missed_policy=policy
    )
    late = late_by if late_by is not None else timedelta(minutes=5)
    with Session(engine) as session, session.begin():
        session.get(ScheduledJob, job["id"]).next_run_at = (datetime.now(UTC) - late).isoformat()
    return job["id"]


def _tasks(engine) -> list[TaskQueueItem]:
    with Session(engine) as session:
        return list(session.scalars(select(TaskQueueItem)))


@pytest.fixture
def vault(engine):
    return CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))


# ------------------------------------------------------------------------- the tick --


def test_a_due_job_becomes_exactly_one_task_however_many_ticks_see_it(engine):
    _autonomy(engine, False)
    _due_job(engine)

    first = scheduler_tick(engine)
    assert len(first) == 1
    assert first[0]["task_id"]

    # The job has moved on to tomorrow, so a second tick fires nothing...
    assert scheduler_tick(engine) == []
    # ...and even if a restart put the same slot back, the idempotency key holds the line.
    with Session(engine) as session, session.begin():
        job = session.get(ScheduledJob, first[0]["job_id"])
        job.next_run_at = first[0]["due_at"]
    scheduler_tick(engine, leader_id="scheduler_after_restart")
    tasks = _tasks(engine)
    assert len(tasks) == 1
    assert tasks[0].idempotency_key == f"scheduled:{first[0]['job_id']}:{first[0]['due_at']}"
    assert tasks[0].task_type == DAILY_RUN


def test_nothing_fires_while_the_autonomy_stop_is_set(engine):
    _autonomy(engine, True)
    _due_job(engine)
    assert scheduler_tick(engine) == []
    assert _tasks(engine) == []


def test_a_missed_slot_fires_once_and_the_policy_only_sets_the_cadence(engine):
    """Three days offline is one run today, never three in a row."""
    _autonomy(engine, False)
    _due_job(engine, late_by=timedelta(days=3, hours=2))

    triggered = scheduler_tick(engine)
    assert len(triggered) == 1
    assert scheduler_tick(engine) == []
    with Session(engine) as session:
        job = session.get(ScheduledJob, triggered[0]["job_id"])
        assert job.next_run_at > datetime.now(UTC).isoformat()


def test_catch_up_keeps_the_original_anchor_and_skip_re_anchors_to_now():
    now = datetime(2026, 9, 11, 14, 0, tzinfo=UTC)
    due = datetime(2026, 9, 9, 8, 0, tzinfo=UTC)  # two days and six hours late
    day = 86400

    caught_up = next_run_after(due, now, day, "CATCH_UP")
    assert caught_up == datetime(2026, 9, 12, 8, 0, tzinfo=UTC)  # tomorrow, same 08:00 anchor

    skipped = next_run_after(due, now, day, "SKIP")
    assert skipped == now + timedelta(days=1)  # tomorrow at 14:00, the lateness kept


def test_ensure_is_idempotent_and_records_the_decision_once(engine):
    from app.models import DomainEvent

    first = ensure_scheduled_job(engine, name="x", workflow_type=DAILY_RUN, interval_seconds=60)
    second = ensure_scheduled_job(engine, name="x", workflow_type=DAILY_RUN, interval_seconds=60)
    assert first["id"] == second["id"]
    with Session(engine) as session:
        events = session.scalar(
            select(func.count())
            .select_from(DomainEvent)
            .where(DomainEvent.event_type == "workflow.job_scheduled")
        )
    assert events == 1


# ----------------------------------------------------------------------- the worker --


def test_the_worker_runs_the_day_once_per_business_date(engine, settings, vault, monkeypatch):
    _autonomy(engine, False)
    _due_job(engine)
    calls: list[str] = []

    def fake_run(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs["correlation_id"])
        # What a real run leaves behind: a DailyRun row for today.
        from app.story.services import business_date

        run_id = str(uuid4())
        with Session(engine) as session, session.begin():
            session.add(
                DailyRun(
                    id=run_id,
                    business_date=business_date(settings.timezone),
                    preflight_status="READY",
                    preflight_json={},
                    status="PARTIAL",
                    stages_json=[],
                    stages_total=12,
                    stages_completed=8,
                    stopped_at_stage=None,
                    stop_reason=None,
                    started_at="2026-09-11T00:00:00+00:00",
                    finished_at="2026-09-11T00:01:00+00:00",
                    event_id=None,
                )
            )
        return {"id": run_id, "status": "PARTIAL"}

    monkeypatch.setattr("app.workflows.worker.execute_daily_run", fake_run)
    handlers = build_task_handlers(engine, settings, vault, None)

    first = worker_pass(engine, handlers)
    assert len(first["triggered"]) == 1
    assert first["ran"][0]["status"] == "COMPLETED"
    assert first["ran"][0]["outcome"]["status"] == "PARTIAL"
    assert len(calls) == 1

    # The job fires again the same day (a restart, a short interval): the run is not repeated.
    _due_job(engine)
    second = worker_pass(engine, handlers)
    assert second["ran"][0]["status"] == "COMPLETED"
    assert second["ran"][0]["outcome"]["status"] == "SKIPPED"
    assert "a rulat deja" in second["ran"][0]["outcome"]["reason"]
    assert len(calls) == 1


def test_a_task_nobody_can_execute_is_dead_lettered_with_the_reason(engine, settings, vault):
    _autonomy(engine, False)
    enqueue_task(engine, "NO_SUCH_WORK", {})

    result = work_once(engine, build_task_handlers(engine, settings, vault, None))

    assert result is not None
    assert result["status"] == "DEAD_LETTER"
    assert "NO_SUCH_WORK" in result["reason"]
    task = _tasks(engine)[0]
    assert task.status == "DEAD_LETTER"
    assert task.error_detail and "NO_SUCH_WORK" in task.error_detail


def test_safe_mode_dead_letters_rather_than_retrying_until_a_person_clears_it(
    engine, settings, vault, monkeypatch
):
    _autonomy(engine, False)
    enqueue_task(engine, DAILY_RUN, {})

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise SafeModeActive("Studioul este în mod sigur.")

    monkeypatch.setattr("app.workflows.worker.execute_daily_run", refuse)
    result = work_once(engine, build_task_handlers(engine, settings, vault, None))

    assert result is not None
    assert result["status"] == "DEAD_LETTER"
    assert "mod sigur" in result["reason"]


def test_an_ordinary_failure_is_retried_and_recorded(engine, settings, vault, monkeypatch):
    _autonomy(engine, False)
    enqueue_task(engine, DAILY_RUN, {}, max_attempts=3)

    def explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("the database went away")

    monkeypatch.setattr("app.workflows.worker.execute_daily_run", explode)
    result = work_once(engine, build_task_handlers(engine, settings, vault, None))

    assert result is not None
    assert result["status"] == "RETRYING"
    assert "the database went away" in result["reason"]


def test_the_queue_hands_out_nothing_while_the_stop_is_set(engine, settings, vault):
    _autonomy(engine, True)
    enqueue_task(engine, DAILY_RUN, {})
    assert work_once(engine, build_task_handlers(engine, settings, vault, None)) is None


def test_non_retryable_is_a_runtime_error():
    assert issubclass(NonRetryable, RuntimeError)


# ------------------------------------------------------------------- the application --


def test_the_application_seeds_the_daily_job_only_when_the_worker_is_on(settings, engine):
    from app.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)):
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(ScheduledJob)) == 0

    with TestClient(create_app(settings.model_copy(update={"worker_enabled": True}))):
        pass
    with Session(engine) as session:
        jobs = {job.name: job for job in session.scalars(select(ScheduledJob))}
    # Seven standing jobs: the day (dormant until the Owner starts it), the Director's weekly
    # performance review, the daily reading of what people search for, the stewards' weekly
    # reading of their vendors' pages, the daily re-judging of every model's standing, the
    # Director's own pass over the company four times a day, and the watchdog every ten
    # minutes — all but the day active from birth, behind the autonomy stop.
    from app.workflows.worker import WATCHDOG, WATCHDOG_JOB_NAME

    assert set(jobs) == {
        DAILY_JOB_NAME,
        WEEKLY_JOB_NAME,
        TRENDS_JOB_NAME,
        MODEL_RESEARCH_JOB_NAME,
        MODEL_REVIEW_JOB_NAME,
        DIRECTOR_LOOP_JOB_NAME,
        WATCHDOG_JOB_NAME,
    }
    assert jobs[WATCHDOG_JOB_NAME].workflow_type == WATCHDOG
    assert jobs[WATCHDOG_JOB_NAME].is_active
    assert jobs[WATCHDOG_JOB_NAME].interval_seconds == settings.watchdog_interval_seconds == 600
    # The day is on the studio's own wall clock, at the configured hour, not on the moment
    # the process happened to start.
    assert jobs[DAILY_JOB_NAME].run_at_local == settings.daily_run_hour_local == "05:00"
    assert jobs[DAILY_JOB_NAME].timezone == settings.timezone
    assert jobs[DIRECTOR_LOOP_JOB_NAME].workflow_type == DIRECTOR_LOOP
    assert jobs[DIRECTOR_LOOP_JOB_NAME].is_active
    assert jobs[DIRECTOR_LOOP_JOB_NAME].interval_seconds == 21600
    assert jobs[MODEL_REVIEW_JOB_NAME].workflow_type == MODEL_REVIEW
    assert jobs[MODEL_REVIEW_JOB_NAME].is_active
    assert jobs[MODEL_REVIEW_JOB_NAME].interval_seconds == 86400
    assert jobs[TRENDS_JOB_NAME].workflow_type == TRENDS_REFRESH
    assert jobs[TRENDS_JOB_NAME].is_active and jobs[TRENDS_JOB_NAME].interval_seconds == 86400
    assert jobs[MODEL_RESEARCH_JOB_NAME].workflow_type == MODEL_RESEARCH
    assert jobs[MODEL_RESEARCH_JOB_NAME].interval_seconds == 7 * 86400
    daily = jobs[DAILY_JOB_NAME]
    assert daily.workflow_type == DAILY_RUN
    assert daily.missed_policy == "CATCH_UP"
    # Dormant: a schedule that fired within seconds of first start-up would begin a real day —
    # agents, tokens, renders — on a decision nobody took.
    assert daily.is_active is False
    weekly = jobs[WEEKLY_JOB_NAME]
    assert weekly.workflow_type == "WEEKLY_REVIEW"
    assert weekly.missed_policy == "CATCH_UP"
    assert weekly.is_active is True
    assert weekly.interval_seconds == 7 * 86400


def test_a_dormant_schedule_fires_nothing_and_activation_is_a_recorded_decision(engine):
    from app.models import DomainEvent
    from app.workflows.services import set_job_active

    _autonomy(engine, False)
    job = ensure_scheduled_job(
        engine, name="dormant", workflow_type=DAILY_RUN, interval_seconds=86400, active=False
    )
    with Session(engine) as session, session.begin():
        session.get(ScheduledJob, job["id"]).next_run_at = "2020-01-01T00:00:00+00:00"
    assert scheduler_tick(engine) == []

    woken = set_job_active(engine, job["id"], True, str(uuid4()))
    assert woken["is_active"] is True
    # Waking does not fire the stale slot on the spot; the clock starts from now.
    assert woken["next_run_at"] > datetime.now(UTC).isoformat()
    assert scheduler_tick(engine) == []
    with Session(engine) as session:
        kinds = list(
            session.scalars(
                select(DomainEvent.event_type).where(DomainEvent.aggregate_id == job["id"])
            )
        )
    assert "workflow.job_activated" in kinds
    # The same state again is not a second decision.
    set_job_active(engine, job["id"], True, str(uuid4()))
    with Session(engine) as session:
        count = session.scalar(
            select(func.count())
            .select_from(DomainEvent)
            .where(DomainEvent.event_type == "workflow.job_activated")
        )
    assert count == 1


# --------------------------------------------------------------- a task that waits --


def test_a_task_with_not_before_is_not_handed_out_before_its_time(engine, settings, vault):
    from app.workflows.services import claim_task

    _autonomy(engine, False)
    later = (datetime.now(UTC) + timedelta(seconds=1800)).isoformat()
    queued = enqueue_task(engine, "ANY", {}, not_before=later)
    assert queued["next_attempt_at"] == later
    assert claim_task(engine, "w") is None

    with Session(engine) as session, session.begin():
        session.get(TaskQueueItem, queued["id"]).next_attempt_at = utc_iso(-1)
    claimed = claim_task(engine, "w")
    assert claimed is not None and claimed["id"] == queued["id"]


def utc_iso(seconds_from_now: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds_from_now)).isoformat()


# ------------------------------------------------------------ the same day, again --


def _fake_day(engine, settings, outcomes: list[dict[str, Any]], calls: list[dict[str, Any]]):
    """A stand-in for execute_daily_run that leaves what a real run leaves: a DailyRun row."""
    from app.story.services import business_date

    def fake_run(*args: Any, **kwargs: Any) -> dict[str, Any]:
        outcome = outcomes[min(len(calls), len(outcomes) - 1)]
        calls.append(dict(kwargs))
        run_id = str(uuid4())
        with Session(engine) as session, session.begin():
            session.add(
                DailyRun(
                    id=run_id,
                    business_date=business_date(settings.timezone),
                    preflight_status=outcome.get("preflight", "READY"),
                    preflight_json={},
                    status=outcome["status"],
                    stages_json=[],
                    stages_total=12,
                    stages_completed=0,
                    stopped_at_stage=None,
                    stop_reason=None,
                    fault_class=outcome.get("fault_class"),
                    started_at=utc_iso(0),
                    finished_at=utc_iso(0),
                    event_id=None,
                )
            )
        return {
            "id": run_id,
            "status": outcome["status"],
            "fault_class": outcome.get("fault_class"),
            "retryable": outcome.get("retryable", False),
        }

    return fake_run


def _fire_now(engine, task_id: str) -> None:
    with Session(engine) as session, session.begin():
        session.get(TaskQueueItem, task_id).next_attempt_at = utc_iso(-1)


def test_a_blocked_day_is_re_attempted_later_and_gives_up_after_the_limit(
    engine, settings, vault, monkeypatch
):
    """A BLOCKED preflight at 05:00 used to lose the whole day. Now it is tried again."""
    from app.story.services import business_date

    _autonomy(engine, False)
    settings.daily_max_attempts = 3
    settings.daily_retry_seconds = 1800
    calls: list[dict[str, Any]] = []
    fake = _fake_day(
        engine, settings, [{"status": "BLOCKED", "preflight": "BLOCKED", "retryable": True}], calls
    )
    monkeypatch.setattr("app.workflows.worker.execute_daily_run", fake)
    handlers = build_task_handlers(engine, settings, vault, None)
    today = business_date(settings.timezone)

    _due_job(engine)
    first = worker_pass(engine, handlers)
    assert first["ran"][0]["outcome"]["status"] == "BLOCKED"
    assert calls[0]["attempt"] == 1 and calls[0]["attempts_allowed"] == 3
    retry = next(t for t in _tasks(engine) if t.idempotency_key == f"daily-retry-{today}-2")
    assert retry.task_type == DAILY_RUN and retry.status == "QUEUED"
    assert retry.payload["attempt"] == 2 and retry.payload["date"] == today
    assert retry.next_attempt_at > utc_iso(1700), "half an hour on, not at once"
    assert first["ran"][0]["outcome"]["retry_task_id"] == retry.id

    # Not due yet: the worker finds nothing to do.
    assert worker_pass(engine, handlers)["ran"] == []

    _fire_now(engine, retry.id)
    second = worker_pass(engine, handlers)
    assert second["ran"][0]["outcome"]["status"] == "BLOCKED"
    assert calls[1]["attempt"] == 2
    third_task = next(t for t in _tasks(engine) if t.idempotency_key == f"daily-retry-{today}-3")
    _fire_now(engine, third_task.id)
    third = worker_pass(engine, handlers)
    assert calls[2]["attempt"] == 3
    assert third["ran"][0]["outcome"].get("retry_task_id") is None, "the third is the last"
    assert not any(t.idempotency_key == f"daily-retry-{today}-4" for t in _tasks(engine))

    # The clock firing again today is told the day has had its attempts.
    _due_job(engine)
    fourth = worker_pass(engine, handlers)
    assert fourth["ran"][0]["outcome"]["status"] == "SKIPPED"
    assert "încercări" in fourth["ran"][0]["outcome"]["reason"]
    assert len(calls) == 3


def test_a_transient_failure_is_re_attempted_but_a_day_that_did_work_is_not(
    engine, settings, vault, monkeypatch
):
    from app.story.services import business_date

    _autonomy(engine, False)
    calls: list[dict[str, Any]] = []
    fake = _fake_day(
        engine,
        settings,
        [
            {"status": "FAILED", "fault_class": "TRANSIENT", "retryable": True},
            {"status": "PARTIAL"},
        ],
        calls,
    )
    monkeypatch.setattr("app.workflows.worker.execute_daily_run", fake)
    handlers = build_task_handlers(engine, settings, vault, None)
    today = business_date(settings.timezone)

    _due_job(engine)
    worker_pass(engine, handlers)
    retry = next(t for t in _tasks(engine) if t.idempotency_key == f"daily-retry-{today}-2")
    _fire_now(engine, retry.id)
    second = worker_pass(engine, handlers)
    assert second["ran"][0]["outcome"]["status"] == "PARTIAL"
    assert second["ran"][0]["outcome"].get("retry_task_id") is None

    # The day did work: neither the clock nor a stray retry repeats it.
    _due_job(engine)
    third = worker_pass(engine, handlers)
    assert third["ran"][0]["outcome"]["status"] == "SKIPPED"
    assert "a rulat deja" in third["ran"][0]["outcome"]["reason"]
    assert len(calls) == 2


def test_a_hard_failure_is_not_re_attempted_by_the_clock(engine, settings, vault, monkeypatch):
    from app.story.services import business_date

    _autonomy(engine, False)
    calls: list[dict[str, Any]] = []
    fake = _fake_day(
        engine, settings, [{"status": "FAILED", "fault_class": "HARD", "retryable": False}], calls
    )
    monkeypatch.setattr("app.workflows.worker.execute_daily_run", fake)
    handlers = build_task_handlers(engine, settings, vault, None)
    _due_job(engine)
    worker_pass(engine, handlers)
    today = business_date(settings.timezone)
    assert not any(
        (t.idempotency_key or "").startswith(f"daily-retry-{today}") for t in _tasks(engine)
    )


def test_a_retry_left_over_from_another_day_is_skipped(engine, settings, vault, monkeypatch):
    _autonomy(engine, False)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "app.workflows.worker.execute_daily_run",
        _fake_day(engine, settings, [{"status": "PARTIAL"}], calls),
    )
    handlers = build_task_handlers(engine, settings, vault, None)
    enqueue_task(
        engine, DAILY_RUN, {"retry_of": "old", "attempt": 2, "date": "2020-01-01"}, max_attempts=1
    )
    result = work_once(engine, handlers)
    assert result is not None and result["outcome"]["status"] == "SKIPPED"
    assert "2020-01-01" in result["outcome"]["reason"]
    assert calls == []


def test_no_re_attempt_is_queued_when_the_stop_lands_during_the_day(
    engine, settings, vault, monkeypatch
):
    """The Owner presses STOP while attempt one is running and it ends re-attemptable (the
    preflight reads the stop as BLOCKED). Nothing autonomous may start after the switch: no
    retry is queued, and a retry already waiting is not handed out."""
    from app.story.services import business_date

    _autonomy(engine, False)
    calls: list[dict[str, Any]] = []
    fake = _fake_day(
        engine, settings, [{"status": "BLOCKED", "preflight": "BLOCKED", "retryable": True}], calls
    )

    def stop_then_run(*args: Any, **kwargs: Any) -> dict[str, Any]:
        _autonomy(engine, True)
        return fake(*args, **kwargs)

    monkeypatch.setattr("app.workflows.worker.execute_daily_run", stop_then_run)
    handlers = build_task_handlers(engine, settings, vault, None)
    today = business_date(settings.timezone)

    _due_job(engine)
    first = worker_pass(engine, handlers)
    assert first["ran"][0]["outcome"]["status"] == "BLOCKED"
    assert first["ran"][0]["outcome"].get("retry_task_id") is None
    assert not any(
        (t.idempotency_key or "").startswith(f"daily-retry-{today}") for t in _tasks(engine)
    )

    # A retry that was already waiting when the stop came stays in the queue, untouched.
    waiting = enqueue_task(
        engine,
        DAILY_RUN,
        {"retry_of": "earlier", "attempt": 2, "date": today},
        max_attempts=1,
        idempotency_key=f"daily-retry-{today}-2",
    )
    _fire_now(engine, waiting["id"])
    assert worker_pass(engine, handlers) == {
        "triggered": [],
        "ran": [],
        "mail": {"answered": [], "refused": []},
    }
    assert len(calls) == 1


# ------------------------------------------------------------------ the fixed hour --


def test_the_next_occurrence_of_a_local_hour_is_dst_safe():
    """Bucharest leaves summer time on 2026-10-25 and enters it on 2026-03-29. Five in the
    morning stays five in the morning on the wall clock, whatever UTC does."""
    from zoneinfo import ZoneInfo

    from app.workflows.services import next_local_occurrence

    zone = ZoneInfo("Europe/Bucharest")
    # Just after 05:00 on the day before the autumn change: next is tomorrow 05:00 EET.
    now = datetime(2026, 10, 24, 5, 0, 1, tzinfo=zone)
    nxt = next_local_occurrence("05:00", "Europe/Bucharest", now)
    assert nxt.astimezone(zone).strftime("%Y-%m-%d %H:%M") == "2026-10-25 05:00"
    assert nxt - now.replace(second=0, microsecond=0) == timedelta(hours=25)
    assert nxt.astimezone(UTC).hour == 3

    # Just before 05:00 the same day: today, not tomorrow.
    now = datetime(2026, 10, 24, 4, 59, tzinfo=zone)
    assert (
        next_local_occurrence("05:00", "Europe/Bucharest", now)
        .astimezone(zone)
        .strftime("%Y-%m-%d %H:%M")
        == "2026-10-24 05:00"
    )

    # The spring change: a 23-hour day, and the hour still reads 05:00 locally.
    now = datetime(2026, 3, 28, 5, 0, 1, tzinfo=zone)
    nxt = next_local_occurrence("05:00", "Europe/Bucharest", now)
    assert nxt.astimezone(zone).strftime("%Y-%m-%d %H:%M") == "2026-03-29 05:00"
    assert nxt - now.replace(second=0, microsecond=0) == timedelta(hours=23)

    # The answer is a UTC instant, comparable with everything else the scheduler stores.
    assert nxt.tzinfo is UTC
    # Exactly on the minute counts as passed: the slot is the *next* one.
    now = datetime(2026, 9, 17, 5, 0, 0, tzinfo=zone)
    assert next_local_occurrence("05:00", "Europe/Bucharest", now).astimezone(zone).day == 18


def test_an_hour_inside_the_ambiguous_hour_fires_once_when_the_clocks_go_back():
    """On 2026-10-25 Bucharest reads 03:00–03:59 twice. An hour set inside it must fire once,
    at the first reading, and not again during the second: two aware datetimes sharing one
    ZoneInfo compare as wall-clock time, so a naive "is the slot past?" said no at the second
    03:30 and handed out a slot forty-five minutes in the past — a fire on every tick until the
    wall clock passed the hour again."""
    from zoneinfo import ZoneInfo

    from app.workflows.services import next_local_occurrence

    zone = ZoneInfo("Europe/Bucharest")
    # 02:30 EEST: the first 03:45 (00:45Z) is still ahead.
    first = next_local_occurrence(
        "03:45", "Europe/Bucharest", datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    )
    assert first == datetime(2026, 10, 25, 0, 45, tzinfo=UTC)
    # Exactly at it: passed, the next is tomorrow's 03:45 EET (01:45Z on the 26th).
    at = next_local_occurrence("03:45", "Europe/Bucharest", first)
    assert at == datetime(2026, 10, 26, 1, 45, tzinfo=UTC)
    # 03:30 EET, the second reading of the hour: the slot must not be in the past.
    second_reading = datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    assert second_reading.astimezone(zone).fold == 1, "the probe is the ambiguous reading"
    nxt = next_local_occurrence("03:45", "Europe/Bucharest", second_reading)
    assert nxt > second_reading, "a slot in the past is a fire on every tick"
    assert nxt == datetime(2026, 10, 26, 1, 45, tzinfo=UTC)

    # The spring gap: 03:30 does not exist on 2026-03-29; the slot lands once, on the first
    # instant after the gap, and tomorrow's 03:30 is a real 03:30 again.
    gap = next_local_occurrence(
        "03:30", "Europe/Bucharest", datetime(2026, 3, 29, 0, 0, tzinfo=UTC)
    )
    assert (
        datetime(2026, 3, 29, 0, 59, tzinfo=UTC) < gap <= datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
    )
    after = next_local_occurrence("03:30", "Europe/Bucharest", gap)
    assert after.astimezone(zone).strftime("%Y-%m-%d %H:%M") == "2026-03-30 03:30"

    # The minute the Owner wakes the job decides the day: 04:59 → today at 05:00; 05:01 →
    # tomorrow. Never a fire on the spot.
    for local_now, expected_day in (
        (datetime(2026, 9, 17, 4, 59, tzinfo=zone), 17),
        (datetime(2026, 9, 17, 5, 1, tzinfo=zone), 18),
    ):
        slot = next_local_occurrence("05:00", "Europe/Bucharest", local_now).astimezone(zone)
        assert (slot.day, slot.hour, slot.minute) == (expected_day, 5, 0)
        assert slot > local_now


def test_a_job_with_a_fixed_hour_moves_to_the_next_occurrence_when_it_fires(engine):
    from zoneinfo import ZoneInfo

    _autonomy(engine, False)
    job = ensure_scheduled_job(
        engine,
        name="at_five",
        workflow_type=DAILY_RUN,
        interval_seconds=86400,
        run_at_local="05:00",
        timezone="Europe/Bucharest",
    )
    assert job["next_run_at"] > datetime.now(UTC).isoformat()
    with Session(engine) as session:
        row = session.get(ScheduledJob, job["id"])
        assert row.run_at_local == "05:00" and row.timezone == "Europe/Bucharest"
        first_slot = datetime.fromisoformat(row.next_run_at).astimezone(ZoneInfo(row.timezone))
    assert (first_slot.hour, first_slot.minute) == (5, 0)

    # Two days late: fires once, and the next slot is the next 05:00 — not "now + a day".
    with Session(engine) as session, session.begin():
        session.get(ScheduledJob, job["id"]).next_run_at = (
            datetime.now(UTC) - timedelta(days=2)
        ).isoformat()
    fired = scheduler_tick(engine)
    assert len(fired) == 1
    assert scheduler_tick(engine) == []
    with Session(engine) as session:
        row = session.get(ScheduledJob, job["id"])
    nxt = datetime.fromisoformat(row.next_run_at)
    assert nxt > datetime.now(UTC)
    local = nxt.astimezone(ZoneInfo("Europe/Bucharest"))
    assert (local.hour, local.minute) == (5, 0)
    assert nxt - datetime.now(UTC) <= timedelta(hours=24)


def test_waking_a_fixed_hour_job_schedules_the_next_occurrence_not_now(engine):
    from zoneinfo import ZoneInfo

    from app.workflows.services import set_job_active

    _autonomy(engine, False)
    job = ensure_scheduled_job(
        engine,
        name="dormant_five",
        workflow_type=DAILY_RUN,
        interval_seconds=86400,
        run_at_local="05:00",
        timezone="Europe/Bucharest",
        active=False,
    )
    # Whatever the dormant row says — a stale past slot, or a future one from another hour.
    for stale in (
        "2020-01-01T00:00:00+00:00",
        (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    ):
        with Session(engine) as session, session.begin():
            row = session.get(ScheduledJob, job["id"])
            row.is_active = False
            row.next_run_at = stale
        woken = set_job_active(engine, job["id"], True, str(uuid4()))
        assert woken["is_active"] is True
        nxt = datetime.fromisoformat(woken["next_run_at"])
        assert nxt > datetime.now(UTC)
        local = nxt.astimezone(ZoneInfo("Europe/Bucharest"))
        assert (local.hour, local.minute) == (5, 0)
        assert scheduler_tick(engine) == [], "activation is not a fire"


def test_the_seeded_hour_follows_the_setting(engine):
    """The hour is configuration: a changed STUDIO_DAILY_RUN_HOUR_LOCAL reaches the row."""
    from zoneinfo import ZoneInfo

    first = ensure_scheduled_job(
        engine,
        name="daily_x",
        workflow_type=DAILY_RUN,
        interval_seconds=86400,
        run_at_local="05:00",
        timezone="Europe/Bucharest",
        active=False,
    )
    second = ensure_scheduled_job(
        engine,
        name="daily_x",
        workflow_type=DAILY_RUN,
        interval_seconds=86400,
        run_at_local="06:30",
        timezone="Europe/Bucharest",
        active=False,
    )
    assert second["id"] == first["id"]
    with Session(engine) as session:
        row = session.get(ScheduledJob, first["id"])
        assert row.run_at_local == "06:30"
        assert row.is_active is False, "following the hour is not activating the job"
        local = datetime.fromisoformat(row.next_run_at).astimezone(ZoneInfo("Europe/Bucharest"))
    assert (local.hour, local.minute) == (6, 30)


def test_the_daily_run_hour_setting_is_a_wall_clock_time(settings):
    from app.config import Settings

    assert settings.daily_run_hour_local == "05:00"
    with pytest.raises(ValueError):
        Settings.model_validate({**settings.model_dump(), "daily_run_hour_local": "25:00"})
    with pytest.raises(ValueError):
        Settings.model_validate({**settings.model_dump(), "daily_run_hour_local": "5am"})


# -------------------------------------------------------------------- the watchdog --


def test_the_watchdog_task_is_dispatched_to_its_module(engine, settings, vault, monkeypatch):
    import sys
    import types

    from app.workflows.worker import WATCHDOG, WATCHDOG_JOB_NAME

    assert (WATCHDOG, WATCHDOG_JOB_NAME) == ("WATCHDOG", "watchdog")
    seen: list[Any] = []
    module = types.ModuleType("app.workflows.watchdog")
    module.WATCHDOG = "WATCHDOG"  # type: ignore[attr-defined]
    module.WATCHDOG_JOB_NAME = "watchdog"  # type: ignore[attr-defined]

    def run_watchdog(eng: Any, cfg: Any, correlation_id: str) -> dict[str, Any]:
        seen.append((eng, cfg, correlation_id))
        return {"status": "COMPLETED", "incidents": []}

    module.run_watchdog = run_watchdog  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.workflows.watchdog", module)

    handlers = build_task_handlers(engine, settings, vault, None)
    assert WATCHDOG in handlers
    outcome = handlers[WATCHDOG]({"id": "task-1", "payload": {}})
    assert outcome["status"] == "COMPLETED"
    assert seen == [(engine, settings, "task-1")]


def test_activation_is_owner_only_and_reachable(client, headers, engine):
    job = ensure_scheduled_job(
        engine, name="api", workflow_type=DAILY_RUN, interval_seconds=86400, active=False
    )
    body = {"command_id": str(uuid4()), "active": True}
    assert client.post(f"/api/v1/scheduler/jobs/{job['id']}/active", json=body).status_code == 401
    ok = client.post(f"/api/v1/scheduler/jobs/{job['id']}/active", json=body, headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["is_active"] is True


def test_the_scheduled_job_view_shows_the_fixed_hour_and_its_timezone(client, headers, engine):
    """The panel could not say "05:00 Europe/Bucharest": the view exposed only the interval,
    so a job on the wall clock read like one anchored to the moment it was activated."""
    _autonomy(engine, False)
    job = ensure_scheduled_job(
        engine,
        name="daily_at_five",
        workflow_type=DAILY_RUN,
        interval_seconds=86400,
        run_at_local="05:00",
        timezone="Europe/Bucharest",
    )
    assert job["run_at_local"] == "05:00"
    assert job["timezone"] == "Europe/Bucharest"

    listed = client.get("/api/v1/scheduler/jobs", headers=headers).json()
    (row,) = [entry for entry in listed if entry["id"] == job["id"]]
    assert row["run_at_local"] == "05:00" and row["timezone"] == "Europe/Bucharest"

    # A job anchored to its interval says so: the fields are there, and empty.
    plain = ensure_scheduled_job(
        engine, name="every_hour", workflow_type=DAILY_RUN, interval_seconds=3600
    )
    assert plain["run_at_local"] is None and plain["timezone"] is None
