"""The background worker: the part of the studio that runs without the browser.

Until now the studio had a scheduler that could be ticked and a task queue that could be claimed,
and nothing that did either on its own. A `ScheduledJob` for the daily run would sit with its
`next_run_at` in the past forever; "autonomous" meant the Owner pressing a button each day.

One pass of the worker does two things, in order: it ticks the scheduler, which turns every due
job into a queued task, and then it claims tasks and runs them through a dispatch table. A task
type with no handler is dead-lettered with that reason rather than retried into the ground.

What the worker will not do. It fires nothing while the Owner's autonomy stop is set — the
scheduler and the queue both refuse — and it runs the scheduled daily run at most once per
business date, however many times the job fires or the process restarts: a second run on the same
day is the Owner's decision to make from the panel, not the clock's.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.runbook.models import DailyRun
from app.runbook.services import DAILY_RUN_TASK, SafeModeActive, execute_daily_run
from app.story.services import business_date
from app.workflows.services import claim_task, complete_task, fail_task, scheduler_tick

logger = logging.getLogger("studio.worker")

#: The workflow type the scheduled daily run is registered under. The Owner's own button
#: queues the same task type, so both go through this handler and the same lease.
DAILY_RUN = DAILY_RUN_TASK

#: The job that starts the day. Seeded at start-up when the worker is enabled, so a fresh studio
#: has its schedule without the Owner having to know the API for one.
DAILY_JOB_NAME = "daily_main"

#: A daily run can take minutes — agents, a render, quality control. The lease has to outlast it,
#: or the queue would hand the same run to the next pass while this one is still rendering.
TASK_LEASE_SECONDS = 3600

#: One pass claims at most this many tasks. The loop comes round again in seconds anyway, and a
#: bounded pass keeps a burst of queued work from holding the worker for an hour.
TASKS_PER_PASS = 3

TaskHandler = Callable[[dict[str, Any]], dict[str, Any]]


class NonRetryable(RuntimeError):
    """A failure that a retry could not change: the task is dead-lettered with this reason."""


def build_task_handlers(
    engine: Engine, settings: Settings, vault: Any, stage_runners: dict[str, Any] | None
) -> dict[str, TaskHandler]:
    """The dispatch table: task type to the function that performs it."""

    def daily_run(task: dict[str, Any]) -> dict[str, Any]:
        today = business_date(settings.timezone)
        # A run the Owner asked for is a decision already taken: it repeats a day that has
        # run, because that is what the button in the panel is for. Only the clock is held
        # to one run per day.
        manual = bool((task.get("payload") or {}).get("manual"))
        with Session(engine) as session:
            already = session.scalars(
                select(DailyRun).where(DailyRun.business_date == today).limit(1)
            ).first()
        if already is not None and not manual:
            # Fired again on a day that already ran — a restart, a manual run earlier, a job
            # interval shorter than a day. The scheduled run does not repeat a day.
            return {
                "status": "SKIPPED",
                "reason": f"Ziua {today} a rulat deja (rularea {already.id}).",
                "run_id": already.id,
            }
        try:
            result = execute_daily_run(
                engine,
                settings,
                vault,
                correlation_id=task["id"],
                stage_runners=stage_runners,
            )
        except SafeModeActive as exc:
            # Safe mode is cleared by a person. Retrying would only add noise until they do.
            raise NonRetryable(str(exc)) from exc
        return {"status": result["status"], "run_id": result["id"], "date": today}

    return {DAILY_RUN: daily_run}


def work_once(
    engine: Engine,
    handlers: dict[str, TaskHandler],
    worker_id: str = "worker_main",
) -> dict[str, Any] | None:
    """Claim one task and run it to a recorded outcome. None when the queue has nothing."""
    task = claim_task(engine, worker_id, lease_duration_seconds=TASK_LEASE_SECONDS)
    if task is None:
        return None

    handler = handlers.get(task["task_type"])
    if handler is None:
        detail = f"Niciun executant pentru sarcini de tip {task['task_type']!r}."
        fail_task(engine, task["id"], worker_id, detail, retryable=False)
        logger.warning("task_unhandled", extra={"task_id": task["id"], "type": task["task_type"]})
        return {"task_id": task["id"], "status": "DEAD_LETTER", "reason": detail}

    try:
        outcome = handler(task)
    except NonRetryable as exc:
        fail_task(engine, task["id"], worker_id, str(exc), retryable=False)
        logger.warning("task_dead_lettered", extra={"task_id": task["id"], "reason": str(exc)})
        return {"task_id": task["id"], "status": "DEAD_LETTER", "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 - the failure is the record
        detail = f"{type(exc).__name__}: {exc}"[:2000]
        failed = fail_task(engine, task["id"], worker_id, detail, retryable=True)
        logger.error("task_failed", extra={"task_id": task["id"], "reason": detail})
        return {"task_id": task["id"], "status": failed["status"], "reason": detail}

    complete_task(engine, task["id"], worker_id)
    return {"task_id": task["id"], "status": "COMPLETED", "outcome": outcome}


def worker_pass(
    engine: Engine,
    handlers: dict[str, TaskHandler],
    worker_id: str = "worker_main",
) -> dict[str, Any]:
    """One pass: fire what is due, then run what is queued."""
    triggered = scheduler_tick(engine, leader_id=worker_id)
    ran: list[dict[str, Any]] = []
    for _ in range(TASKS_PER_PASS):
        result = work_once(engine, handlers, worker_id)
        if result is None:
            break
        ran.append(result)
    return {"triggered": triggered, "ran": ran}
