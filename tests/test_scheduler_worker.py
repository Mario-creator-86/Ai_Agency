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
    # Eight standing jobs: the day (dormant until the Owner starts it), the Director's weekly
    # performance review, the daily reading of what people search for, the stewards' weekly
    # reading of their vendors' pages, the daily re-judging of every model's standing, the
    # Director's own pass over the company four times a day, the watchdog every ten
    # minutes and the database's daily backup (2026-10-02, REL-04) — all but the day active
    # from birth, behind the autonomy stop.
    from app.workflows.worker import BACKUP, BACKUP_JOB_NAME, WATCHDOG, WATCHDOG_JOB_NAME

    assert set(jobs) == {
        DAILY_JOB_NAME,
        WEEKLY_JOB_NAME,
        TRENDS_JOB_NAME,
        MODEL_RESEARCH_JOB_NAME,
        MODEL_REVIEW_JOB_NAME,
        DIRECTOR_LOOP_JOB_NAME,
        WATCHDOG_JOB_NAME,
        BACKUP_JOB_NAME,
    }
    assert jobs[BACKUP_JOB_NAME].workflow_type == BACKUP and jobs[BACKUP_JOB_NAME].is_active
    assert jobs[BACKUP_JOB_NAME].run_at_local == settings.backup_hour_local == "03:30"
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
        "interrupted": [],
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


def test_the_watchdog_releases_the_money_a_dead_process_left_held(engine, settings, vault):
    """The fourth thing a killed process leaves behind. A film holds what it is about to
    spend; a process that dies under the hold leaves the day's budget pledged to a film
    nobody is making, and every later film is refused for money never spent."""
    from datetime import UTC, datetime, timedelta

    from app.economy.budget import reserve_spend
    from app.economy.models import SpendReservation
    from app.workflows.watchdog import WATCHDOG, run_watchdog

    _autonomy(engine, False)
    fresh = reserve_spend(engine, 4_000_000, "film de azi", str(uuid4()))
    stale = reserve_spend(engine, 4_000_000, "film abandonat", str(uuid4()))
    old = (datetime.now(UTC) - timedelta(seconds=settings.reservation_ttl_seconds + 60)).isoformat()
    with Session(engine) as session, session.begin():
        session.get(SpendReservation, stale["reservation_id"]).reserved_at = old

    result = run_watchdog(engine, settings, correlation_id=str(uuid4()))

    assert result["reservations"]["released"] == [stale["reservation_id"]]
    assert result["reservations"]["ttl_seconds"] == settings.reservation_ttl_seconds
    with Session(engine) as session:
        assert session.get(SpendReservation, stale["reservation_id"]).status == "RELEASED"
        assert session.get(SpendReservation, fresh["reservation_id"]).status == "RESERVED"

    # And nothing at all while the Owner's switch is set: a stopped studio does not move,
    # including to repair itself.
    _autonomy(engine, True)
    stopped = run_watchdog(engine, settings, correlation_id=str(uuid4()))
    assert stopped["status"] == "SKIPPED"
    assert stopped["reservations"]["released"] == []
    assert WATCHDOG == "WATCHDOG"


def test_a_run_past_the_days_token_ceiling_is_blocked_and_the_owner_is_told(engine, monkeypatch):
    """The Policy Kernel's first gate. Measured on a copy of the live database: 391 runs on
    Ollama Cloud went through the Director's loop and the mail rounds under no ceiling."""
    from types import SimpleNamespace

    from app.agents import services as agent_services
    from app.agents.models import Agent, AgentMessage, AgentRun, ModelRecord
    from app.agents.services import run_agent_task, seed_initial_workforce
    from app.providers.base import GenerateResult, HealthResult
    from app.providers.registry import ProviderRegistry

    class Model:
        async def health_check(self):
            return HealthResult("HEALTHY")

        async def list_models(self):
            return []

        async def generate(self, model, prompt, **kwargs):
            return GenerateResult("un răspuns", 400, 400, None)

    _autonomy(engine, False)
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        for record in session.scalars(select(ModelRecord)):
            record.is_available = True
    with Session(engine) as session:
        agent = session.scalars(select(Agent)).first()
        agent_id, provider_id = agent.id, agent.provider_id
    registry = ProviderRegistry()
    registry.register(provider_id, Model())
    monkeypatch.setattr(
        agent_services, "_studio_settings", lambda: SimpleNamespace(agent_daily_token_budget=500)
    )

    first = run_agent_task(engine, registry, agent_id, "t", "spune ceva", "v1", str(uuid4()))
    assert first["status"] == "SUCCEEDED", first  # 800 tokens: the ceiling was not reached yet
    second = run_agent_task(engine, registry, agent_id, "t", "spune altceva", "v1", str(uuid4()))

    assert second["status"] == "BLOCKED_BUDGET", second
    assert "plafonul zilnic" in (second["error_detail"] or "").lower()
    with Session(engine) as session:
        runs = list(session.scalars(select(AgentRun)))
        letters = [
            message
            for message in session.scalars(
                select(AgentMessage).where(AgentMessage.to_agent_id.is_(None))
            )
            if (message.body_json or {}).get("kind") == "token_ceiling"
        ]
    assert [run.status for run in runs].count("BLOCKED_BUDGET") == 1
    assert len(letters) == 1, "the Owner was not told, or was told twice"

    # A blocked run costs nothing and is refused again, and the letter is still one.
    third = run_agent_task(engine, registry, agent_id, "t", "și încă ceva", "v1", str(uuid4()))
    assert third["status"] == "BLOCKED_BUDGET"
    with Session(engine) as session:
        again = [
            message
            for message in session.scalars(
                select(AgentMessage).where(AgentMessage.to_agent_id.is_(None))
            )
            if (message.body_json or {}).get("kind") == "token_ceiling"
        ]
    assert len(again) == 1


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


# ------------------------------------------ a re-attempt only for a day that lost its films --


@pytest.fixture
def started_studio(engine, settings):
    """A studio whose preflight is not BLOCKED, so the real runbook runs its stages."""
    import shutil

    from app.agents.models import ModelRecord
    from app.agents.services import seed_initial_workforce

    seed_initial_workforce(engine)
    _autonomy(engine, False)
    with Session(engine) as session, session.begin():
        session.scalars(select(ModelRecord)).first().is_available = True
    settings.ffmpeg_path = settings.ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg-test-stub"
    settings.stage_retry_attempts = 0
    settings.daily_max_attempts = 3
    return engine


def _stub_day(failing: str) -> dict[str, Any]:
    from app.runbook.services import STAGES

    def fails() -> dict[str, Any]:
        raise TimeoutError(f"{failing}: the other side did not answer")

    runners: dict[str, Any] = {
        name: (lambda: {"status": "COMPLETED", "reason": "ok"}) for name in STAGES[1:-1]
    }
    runners[failing] = fails
    return runners


def test_a_transient_fault_at_performance_intake_queues_no_re_attempt_of_the_day(
    engine, settings, vault, started_studio, monkeypatch
):
    """Measured on the Owner's copy: a refused statistics read failed the day TRANSIENT and a
    retry was queued for half an hour on — a whole day of paid work again, to recover a read.
    The films went through, so the day is done and the clock is told so."""
    from app.story.services import business_date

    monkeypatch.setattr("app.agents.director.letter_to_owner", lambda *a, **k: "id")
    handlers = build_task_handlers(engine, settings, vault, _stub_day("performance_intake"))
    today = business_date(settings.timezone)

    _due_job(engine)
    first = worker_pass(engine, handlers)

    assert first["ran"][0]["outcome"]["status"] == "PARTIAL"
    assert first["ran"][0]["outcome"].get("retry_task_id") is None
    assert not any(
        (t.idempotency_key or "").startswith(f"daily-retry-{today}") for t in _tasks(engine)
    )
    _due_job(engine)
    again = worker_pass(engine, handlers)
    assert again["ran"][0]["outcome"]["status"] == "SKIPPED"
    assert "a rulat deja" in again["ran"][0]["outcome"]["reason"]


def test_a_transient_fault_that_cost_the_films_queues_the_re_attempt(
    engine, settings, vault, started_studio, monkeypatch
):
    from app.story.services import business_date

    monkeypatch.setattr("app.agents.director.letter_to_owner", lambda *a, **k: "id")
    handlers = build_task_handlers(engine, settings, vault, _stub_day("media"))
    today = business_date(settings.timezone)

    _due_job(engine)
    first = worker_pass(engine, handlers)

    assert first["ran"][0]["outcome"]["status"] == "FAILED"
    retry = next(t for t in _tasks(engine) if t.idempotency_key == f"daily-retry-{today}-2")
    assert first["ran"][0]["outcome"]["retry_task_id"] == retry.id


# ------------------------------------------- a crashed day (QUEUE_LEASE_SHUTDOWN, REL-03) --
#
# 2026-10-02. The queue re-claimed a lapsed CLAIMED/RUNNING task whatever its attempts
# (probe: max_attempts=1, claimed, lease lapsed, claimed again -> (True, 2, 1)), and the
# DailyRun row was written only at the very end of the day, so a crash left no trace and the
# whole day ran again an hour later. Now a lapsed task with no attempts left is
# DEAD_LETTER INTERRUPTED, the day writes its row RUNNING at the start, and the Owner is told
# once; no second day starts that date without his command.


class Killed(BaseException):
    """What a killed process looks like from inside: nothing below it gets to clean up."""


def _letters(engine, kind: str) -> list[Any]:
    from app.agents.models import AgentMessage

    with Session(engine) as session:
        rows = [
            row
            for row in session.scalars(select(AgentMessage))
            if isinstance(row.body_json, dict) and row.body_json.get("kind") == kind
        ]
        session.expunge_all()
        return rows


def _lapse(engine, task_id: str) -> None:
    with Session(engine) as session, session.begin():
        session.get(TaskQueueItem, task_id).lease_expires_at = (
            datetime.now(UTC) - timedelta(minutes=5)
        ).isoformat()


def test_a_lapsed_task_with_no_attempts_left_is_interrupted_not_reclaimed_and_told_once(
    engine, settings, vault, monkeypatch
):
    from app.models import DomainEvent
    from app.workflows.services import claim_task

    _autonomy(engine, False)
    calls: list[Any] = []
    monkeypatch.setattr(
        "app.workflows.worker.execute_daily_run", lambda *a, **k: calls.append(k) or {}
    )
    queued = enqueue_task(engine, DAILY_RUN, {"manual": True}, max_attempts=1)
    claimed = claim_task(engine, "worker_that_died", lease_duration_seconds=1)
    assert claimed is not None and claimed["id"] == queued["id"]
    _lapse(engine, queued["id"])

    # The queue never hands it out again: it had its one attempt.
    assert claim_task(engine, "worker_after_restart", lease_duration_seconds=60) is None

    handlers = build_task_handlers(engine, settings, vault, None)
    first = worker_pass(engine, handlers)
    second = worker_pass(engine, handlers)

    assert calls == [], "the day is not run again"
    assert first["ran"] == [] and second["ran"] == []
    assert [item["id"] for item in first["interrupted"]] == [queued["id"]]
    assert second["interrupted"] == []
    (task,) = _tasks(engine)
    assert task.status == "DEAD_LETTER"
    assert task.error_detail and task.error_detail.startswith("INTERRUPTED")
    assert task.lease_token is None
    with Session(engine) as session:
        events = list(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == "workflow.task_interrupted")
            )
        )
    assert len(events) == 1 and events[0].aggregate_id == queued["id"]
    told = _letters(engine, "day_interrupted")
    assert len(told) == 1, "one letter, not one per pass"
    letter = f"{told[0].subject} {told[0].body_text}"
    assert "întreruptă" in letter and "nu o repornesc singur" in letter


def test_a_lapsed_task_with_attempts_left_is_still_reclaimed_by_the_queue(engine):
    from app.workflows.services import claim_task

    _autonomy(engine, False)
    queued = enqueue_task(engine, "ANY", {}, max_attempts=3)
    assert claim_task(engine, "worker_that_died", lease_duration_seconds=1) is not None
    _lapse(engine, queued["id"])

    again = claim_task(engine, "worker_after_restart", lease_duration_seconds=60)
    assert again is not None and again["id"] == queued["id"] and again["attempts"] == 2


def test_a_killed_day_is_left_interrupted_and_the_clock_starts_no_second_one(
    engine, settings, vault, started_studio, monkeypatch
):
    from app.runbook.services import execute_daily_run
    from app.workflows.services import claim_task

    queued = enqueue_task(engine, DAILY_RUN, {"job_name": "daily_main"}, max_attempts=1)
    task = claim_task(engine, "worker_main", lease_duration_seconds=600)
    assert task is not None and task["id"] == queued["id"]

    def killed() -> dict[str, Any]:
        raise Killed()

    with pytest.raises(Killed):
        execute_daily_run(
            engine,
            settings,
            vault,
            correlation_id=task["id"],
            stage_runners={"media": killed},
        )

    # The row was written when the day began, and says where it was.
    with Session(engine) as session:
        (run,) = session.scalars(select(DailyRun)).all()
        assert run.status == "RUNNING"
        assert run.finished_at is None
        assert run.stages_json[-1]["stage"] == "media"
        assert run.stages_json[-1]["status"] == "RUNNING"
        run_id = run.id

    # The process is gone; its lease lapses; the next pass finds it.
    _lapse(engine, task["id"])
    calls: list[Any] = []

    def counted(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return execute_daily_run(*args, **kwargs)

    monkeypatch.setattr("app.workflows.worker.execute_daily_run", counted)
    handlers = build_task_handlers(engine, settings, vault, None)
    worker_pass(engine, handlers)

    with Session(engine) as session:
        run = session.get(DailyRun, run_id)
        assert run.status == "INTERRUPTED"
        assert run.stopped_at_stage == "media"
        assert run.finished_at
        by_name = {stage["stage"]: stage for stage in run.stages_json}
        assert by_name["media"]["status"] == "INTERRUPTED"
        # Every stage of the day is named, the ones it never reached included.
        assert by_name["serial_next"]["status"] == "BLOCKED"
    told = _letters(engine, "day_interrupted")
    assert len(told) == 1
    assert "«" in told[0].body_text and "nu o repornesc singur" in told[0].body_text

    # The clock fires again today (a restart, the slot put back): no second day.
    _due_job(engine)
    fired = worker_pass(engine, handlers)
    assert fired["ran"][0]["outcome"]["status"] == "SKIPPED"
    assert "întreruptă" in fired["ran"][0]["outcome"]["reason"]
    assert calls == []

    # His own command is the decision the clock may not take: it runs.
    manual = handlers[DAILY_RUN]({"id": str(uuid4()), "payload": {"manual": True}})
    assert len(calls) == 1 and manual["run_id"] != run_id

    # The interrupted day stays in the runs list, closed, with its headline.
    from app.runbook.services import list_runs

    listed = {item["id"]: item for item in list_runs(engine)}
    assert listed[run_id]["status"] == "INTERRUPTED"
    assert listed[run_id]["finished_at"]


def test_the_watchdog_closes_a_running_day_nobody_is_running_any_more(
    engine, settings, vault, started_studio
):
    from app.runbook.services import execute_daily_run
    from app.workflows.services import claim_task
    from app.workflows.watchdog import run_watchdog

    # A day running under a live lease is left alone, however old it is.
    alive_task = enqueue_task(engine, DAILY_RUN, {"manual": True}, max_attempts=1)
    alive = claim_task(engine, "worker_main", lease_duration_seconds=3600)
    assert alive is not None and alive["id"] == alive_task["id"]

    def killed() -> dict[str, Any]:
        raise Killed()

    for correlation in (alive["id"], "rehearsal-with-no-task"):
        with pytest.raises(Killed):
            execute_daily_run(
                engine, settings, vault, correlation_id=correlation, stage_runners={"media": killed}
            )
    long_ago = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    with Session(engine) as session, session.begin():
        for run in session.scalars(select(DailyRun)):
            run.started_at = long_ago
            run.stages_json = [{**stage, "at": long_ago} for stage in run.stages_json]

    first = run_watchdog(engine, settings)
    second = run_watchdog(engine, settings)

    assert len(first["days"]["interrupted"]) == 1
    assert second["days"]["interrupted"] == []
    with Session(engine) as session:
        statuses = sorted(run.status for run in session.scalars(select(DailyRun)))
    assert statuses == ["INTERRUPTED", "RUNNING"]
    assert len(_letters(engine, "day_interrupted")) == 1


def test_a_continuation_cut_off_by_a_crash_is_told_once_and_not_run_again(engine, settings, vault):
    from app.workflows.services import claim_task
    from app.workflows.worker import FILM_CONTINUE

    _autonomy(engine, False)
    queued = enqueue_task(
        engine, FILM_CONTINUE, {"storyboard_id": "board-7", "cause": "approval:x"}, max_attempts=1
    )
    assert claim_task(engine, "worker_main", lease_duration_seconds=1) is not None
    _lapse(engine, queued["id"])

    handlers = build_task_handlers(engine, settings, vault, None)
    worker_pass(engine, handlers)
    worker_pass(engine, handlers)

    (task,) = [t for t in _tasks(engine) if t.id == queued["id"]]
    assert task.status == "DEAD_LETTER"
    told = _letters(engine, "film_continue_interrupted")
    assert len(told) == 1
    assert "nu o repornesc singur" in told[0].body_text


# ------------------------------------------------- dead Workflow rows (AR-14) --


def test_a_scheduled_fire_creates_no_workflow_row_that_would_never_move(engine):
    from app.models import DomainEvent
    from app.workflows.models import Workflow

    _autonomy(engine, False)
    _due_job(engine)

    (fired,) = scheduler_tick(engine)

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Workflow)) == 0
        task = session.get(TaskQueueItem, fired["task_id"])
        assert task.workflow_id is None
        assert "workflow_id" not in task.payload
        events = list(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == "workflow.job_fired")
            )
        )
    assert "workflow_id" not in fired
    assert len(events) == 1
    assert events[0].payload["job_name"] == "daily_main"
    assert events[0].payload["task_id"] == fired["task_id"]
