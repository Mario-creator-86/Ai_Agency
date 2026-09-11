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
    # Two standing jobs: the day (dormant until the Owner starts it) and the Director's
    # weekly performance review (active standing policy, first fire an hour after birth).
    assert set(jobs) == {DAILY_JOB_NAME, WEEKLY_JOB_NAME}
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


def test_activation_is_owner_only_and_reachable(client, headers, engine):
    job = ensure_scheduled_job(
        engine, name="api", workflow_type=DAILY_RUN, interval_seconds=86400, active=False
    )
    body = {"command_id": str(uuid4()), "active": True}
    assert client.post(f"/api/v1/scheduler/jobs/{job['id']}/active", json=body).status_code == 401
    ok = client.post(f"/api/v1/scheduler/jobs/{job['id']}/active", json=body, headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["is_active"] is True
