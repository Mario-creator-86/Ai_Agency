"""The background worker: the part of the studio that runs without the browser.

Until now the studio had a scheduler that could be ticked and a task queue that could be claimed,
and nothing that did either on its own. A `ScheduledJob` for the daily run would sit with its
`next_run_at` in the past forever; "autonomous" meant the Owner pressing a button each day.

One pass of the worker does two things, in order: it ticks the scheduler, which turns every due
job into a queued task, and then it claims tasks and runs them through a dispatch table. A task
type with no handler is dead-lettered with that reason rather than retried into the ground.

What the worker will not do. It fires nothing while the Owner's autonomy stop is set — the
scheduler and the queue both refuse — and it does at most one *successful* day per business
date, however many times the job fires or the process restarts: a day that did work
(COMPLETED or PARTIAL) is not repeated, and a second one is the Owner's decision to make from
the panel, not the clock's. A day that could not run — a BLOCKED preflight, a stage that
failed on a transient fault — is attempted again after `daily_retry_seconds`, up to
`daily_max_attempts` times; measured on the live copy, the old rule ("any run today means
skip") lost whole days to one "database is locked".
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.runbook.models import DailyRun
from app.runbook.services import (
    DAILY_RUN_TASK,
    SafeModeActive,
    execute_daily_run,
    stop_requested,
)
from app.runbook.weekly import (
    WEEKLY_REVIEW_TASK,
    WeeklyReviewError,
    execute_weekly_review,
)
from app.story.services import business_date
from app.workflows.services import (
    claim_task,
    complete_task,
    enqueue_task,
    fail_task,
    scheduler_tick,
)

logger = logging.getLogger("studio.worker")

#: The workflow type the scheduled daily run is registered under. The Owner's own button
#: queues the same task type, so both go through this handler and the same lease.
DAILY_RUN = DAILY_RUN_TASK

#: The job that starts the day. Seeded at start-up when the worker is enabled, so a fresh studio
#: has its schedule without the Owner having to know the API for one.
DAILY_JOB_NAME = "daily_main"

#: The Director's weekly performance review, as a scheduled workflow type and a job name.
#: Active from the first start-up — the Owner ordered the weekly check as standing policy —
#: but still behind the autonomy stop like every other scheduled work, and a week that
#: already had its review is skipped inside the task itself.
WEEKLY_REVIEW = WEEKLY_REVIEW_TASK

#: The outside signal, read once a day, and the stewards' reading of their vendors' pages,
#: once a week. Both active from the first start-up and both behind the autonomy stop.
TRENDS_REFRESH = "TRENDS_REFRESH"
TRENDS_JOB_NAME = "trends_daily"
MODEL_RESEARCH = "MODEL_RESEARCH"
MODEL_RESEARCH_JOB_NAME = "model_research_weekly"

#: The standing of every model, re-judged on what it has delivered. Daily and light: it
#: reads `model_outcome` and moves models between stations, and generates nothing, so it
#: costs nothing. The weekly research above is the full review — it reads the vendors' pages
#: as well — and both are behind the autonomy stop like every other scheduled work.
MODEL_REVIEW = "MODEL_REVIEW"
MODEL_REVIEW_JOB_NAME = "model_review_daily"

#: The Director's management of the company, on the studio's own clock. Not a report: one
#: pass reads the state, takes the matters the measurements raise, and hands work to the
#: department that can act on it. Behind the autonomy stop like every other scheduled thing.
DIRECTOR_LOOP = "DIRECTOR_LOOP"
DIRECTOR_LOOP_JOB_NAME = "director_loop"

#: The watchdog: every ten minutes, work that is stuck — a task past its lease, a run that
#: never finished, a provider job never collected — is found and named. The names match
#: what `app.workflows.watchdog` exports; the module itself is imported only when a task
#: fires, like the Director's loop, so the worker builds without it.
WATCHDOG = "WATCHDOG"
WATCHDOG_JOB_NAME = "watchdog"

#: What a day's daily-run status means for the clock: a day that did work is done.
DAY_DONE_STATES = ("COMPLETED", "PARTIAL")

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
    engine: Engine,
    settings: Settings,
    vault: Any,
    stage_runners: dict[str, Any] | None,
    registry: Any = None,
) -> dict[str, TaskHandler]:
    """The dispatch table: task type to the function that performs it."""

    def daily_run(task: dict[str, Any]) -> dict[str, Any]:
        today = business_date(settings.timezone)
        payload = task.get("payload") or {}
        # A run the Owner asked for is a decision already taken: it repeats a day that has
        # run, because that is what the button in the panel is for. Only the clock is held
        # to one successful run per day.
        manual = bool(payload.get("manual"))
        retry_for = payload.get("date") if payload.get("retry_of") else None
        if retry_for is not None and retry_for != today:
            # A re-attempt queued yesterday and only claimed now (the studio was off, or
            # stopped): that day is over, and today's own clock will fire today's run.
            return {
                "status": "SKIPPED",
                "reason": f"Reîncercarea era pentru ziua {retry_for}, care a trecut.",
            }
        with Session(engine) as session:
            runs_today = session.scalars(
                select(DailyRun)
                .where(DailyRun.business_date == today)
                .order_by(DailyRun.started_at)
            ).all()
            done = next((run for run in runs_today if run.status in DAY_DONE_STATES), None)
            done_id = done.id if done is not None else None
        attempt = len(runs_today) + 1
        if not manual:
            if done_id is not None:
                # Fired again on a day that did its work — a restart, a manual run earlier,
                # a retry that outlived its reason. The scheduled run does not repeat a day.
                return {
                    "status": "SKIPPED",
                    "reason": f"Ziua {today} a rulat deja (rularea {done_id}).",
                    "run_id": done_id,
                }
            if attempt > settings.daily_max_attempts:
                return {
                    "status": "SKIPPED",
                    "reason": (
                        f"Ziua {today} și-a folosit cele {settings.daily_max_attempts} "
                        "încercări; o nouă rulare azi este decizia Owner-ului."
                    ),
                }
        try:
            result = execute_daily_run(
                engine,
                settings,
                vault,
                correlation_id=task["id"],
                stage_runners=stage_runners,
                attempt=attempt,
                attempts_allowed=settings.daily_max_attempts,
            )
        except SafeModeActive as exc:
            # Safe mode is cleared by a person. Retrying would only add noise until they do.
            raise NonRetryable(str(exc)) from exc
        outcome = {
            "status": result["status"],
            "run_id": result["id"],
            "date": today,
            "attempt": attempt,
        }
        if (
            result.get("retryable")
            and attempt < settings.daily_max_attempts
            and not stop_requested(engine)
        ):
            # The day could not run and nothing about that is final: try again in a while.
            # Keyed on the date and the attempt number, so a restart between now and then
            # queues nothing twice; held with `not_before`, so it waits its half hour in the
            # queue rather than in a sleeping thread that a restart would lose.
            following = attempt + 1
            not_before = (
                datetime.now(UTC) + timedelta(seconds=settings.daily_retry_seconds)
            ).isoformat()
            retry = enqueue_task(
                engine,
                DAILY_RUN,
                {
                    "retry_of": result["id"],
                    "attempt": following,
                    "date": today,
                    "scheduled_job_id": payload.get("scheduled_job_id"),
                    "job_name": payload.get("job_name"),
                },
                priority=5,
                max_attempts=1,
                idempotency_key=f"daily-retry-{today}-{following}",
                not_before=not_before,
            )
            outcome["retry_task_id"] = retry["id"]
            outcome["retry_at"] = retry["next_attempt_at"]
            outcome["reason"] = (
                f"Ziua nu a putut rula (încercarea {attempt} din "
                f"{settings.daily_max_attempts}); reîncerc la {retry['next_attempt_at'][:16]}."
            )
        return outcome

    def weekly_review(task: dict[str, Any]) -> dict[str, Any]:
        if registry is None:
            raise NonRetryable("Revizia săptămânală are nevoie de registrul de furnizori.")
        try:
            result = execute_weekly_review(
                engine,
                registry,
                correlation_id=task["id"],
                geo=settings.trends_geo if settings.trends_enabled else None,
            )
        except WeeklyReviewError as exc:
            raise NonRetryable(str(exc)) from exc
        return result

    def trends_refresh(task: dict[str, Any]) -> dict[str, Any]:
        from app.analytics.trends import refresh_trends  # noqa: PLC0415

        return refresh_trends(engine, settings, correlation_id=task["id"])

    def director_loop(task: dict[str, Any]) -> dict[str, Any]:
        from app.agents.command import direct_company  # noqa: PLC0415

        result = direct_company(engine, registry, settings, correlation_id=task["id"])
        # The state is large and the queue keeps every result: what the task returns is what
        # the Director did, not the whole company as data.
        return {
            "status": result["status"],
            "reason": result["reason"],
            "assignments": result.get("assignments", []),
            "escalated": result.get("escalated", []),
            "maturity": result.get("maturity"),
        }

    def model_review(task: dict[str, Any]) -> dict[str, Any]:
        from app.integrations.lifecycle import review_models  # noqa: PLC0415

        return review_models(engine, settings, full=False, correlation_id=task["id"])

    def model_research(task: dict[str, Any]) -> dict[str, Any]:
        if registry is None:
            raise NonRetryable("Cercetarea de modele are nevoie de registrul de furnizori.")
        from app.media.model_research import research_all  # noqa: PLC0415

        return research_all(engine, registry, settings, correlation_id=task["id"])

    def watchdog(task: dict[str, Any]) -> dict[str, Any]:
        try:
            from app.workflows.watchdog import run_watchdog  # noqa: PLC0415
        except ImportError as exc:
            # The job is seeded with the schedule; a build without the module must say so
            # once per fire rather than retry an import into the ground.
            raise NonRetryable("Supraveghetorul nu este instalat în această versiune.") from exc

        return run_watchdog(engine, settings, correlation_id=task["id"])

    return {
        DAILY_RUN: daily_run,
        WEEKLY_REVIEW: weekly_review,
        TRENDS_REFRESH: trends_refresh,
        MODEL_RESEARCH: model_research,
        MODEL_REVIEW: model_review,
        DIRECTOR_LOOP: director_loop,
        WATCHDOG: watchdog,
    }


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
    registry: Any = None,
) -> dict[str, Any]:
    """One pass: fire what is due, run what is queued, then answer the mail.

    The mail comes last and only with a registry to run models through: a letter to an
    employee is answered by that employee within the pass, so an exchange the Director
    starts in the evening is a conversation by the next pass, not a note that waits a day.
    """
    triggered = scheduler_tick(engine, leader_id=worker_id)
    ran: list[dict[str, Any]] = []
    for _ in range(TASKS_PER_PASS):
        result = work_once(engine, handlers, worker_id)
        if result is None:
            break
        ran.append(result)
    mail: dict[str, Any] = {"answered": [], "refused": []}
    if registry is not None:
        from app.agents.mail import correspondence_round  # noqa: PLC0415

        mail = correspondence_round(engine, registry)
    return {"triggered": triggered, "ran": ran, "mail": mail}
