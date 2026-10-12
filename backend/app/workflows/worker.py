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
(COMPLETED or PARTIAL) is not repeated, nor is a day that was cut off (INTERRUPTED: the studio
was stopped under it, or its process died), and a second one is the Owner's decision to make
from the panel, not the clock's. A day that could not run — a BLOCKED preflight, a stage that
failed on a transient fault — is attempted again after `daily_retry_seconds`, up to
`daily_max_attempts` times; measured on the live copy, the old rule ("any run today means
skip") lost whole days to one "database is locked".
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import IO, Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.backup import BACKUP_JOB_NAME as BACKUP_JOB
from app.backup import BACKUP_TASK
from app.config import Settings
from app.runbook.models import DailyRun
from app.runbook.services import (
    DAILY_RUN_TASK,
    INTERRUPTED,
    RUNNING,
    SafeModeActive,
    execute_daily_run,
    interrupt_task_day,
    resume_runners,
    shutdown_requested,
    stop_requested,
)
from app.runbook.weekly import (
    WEEKLY_REVIEW_TASK,
    WeeklyReviewError,
    execute_weekly_review,
)
from app.services import FILM_CONTINUE_TASK, append_event
from app.story.services import business_date
from app.workflows.services import (
    TASK_LEASE_LOST_EVENT,
    LeaseLost,
    claim_task,
    complete_task,
    enqueue_task,
    fail_task,
    heartbeat_task,
    scheduler_tick,
    sweep_interrupted_tasks,
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

#: One repair the Director chose in her loop (2026-10-11): queued by `app.agents.repairs.desk`
#: after the Policy Kernel allowed it, applied and recorded by its executor. Behind the
#: autonomy stop like every queued thing, and the kernel is asked again when it runs.
DIRECTOR_REPAIR = "DIRECTOR_REPAIR"

#: The watchdog: every ten minutes, work that is stuck — a task past its lease, a run that
#: never finished, a provider job never collected — is found and named. The names match
#: what `app.workflows.watchdog` exports; the module itself is imported only when a task
#: fires, like the Director's loop, so the worker builds without it.
WATCHDOG = "WATCHDOG"
WATCHDOG_JOB_NAME = "watchdog"

#: The database's daily backup (`app.backup.run_backup_job`): SQLite's online copy, its
#: check, the wrapped key beside it, then the pruning of old housekeeping rows. No network,
#: no cost; behind the autonomy stop like every other scheduled thing (REL-04, REL-15).
BACKUP = BACKUP_TASK
BACKUP_JOB_NAME = BACKUP_JOB

#: The Owner's yes on a paid step of a film, or his look approving one of its takes, walks that
#: film on at once (2026-10-02, A6 / AR-05): queued by the Policy Kernel when he answers and by
#: `app.media.assembler.decide_take` (both through `app.services.queue_film_continue`), run by
#: `app.runbook.stages.continue_film`. It is not a day: the scheduled day stays one per
#: business date, and nothing here writes a DailyRun.
FILM_CONTINUE = FILM_CONTINUE_TASK
#: A film whose purchase lease another buyer holds (the day, his own press) is continued again
#: this much later, at most `FILM_CONTINUE_DEFERRALS` times; after that the next daily run
#: walks it, and his yes, which stands for two days, is still there to be spent.
FILM_CONTINUE_DEFER_SECONDS = 600
FILM_CONTINUE_DEFERRALS = 3

#: What a day's daily-run status means for the clock: a day that did work is done.
DAY_DONE_STATES = ("COMPLETED", "PARTIAL")

#: A daily run can take minutes — agents, a render, quality control. The lease has to outlast it,
#: or the queue would hand the same run to the next pass while this one is still rendering.
#: A day can outlast it too (stills, a hero, six clips with clip QC, the assembly): the
#: handler's lease is renewed in the background every half lease while it runs
#: (`LeaseKeeper`, A16/AR-17, 2026-10-02), so only a process that died lets it lapse.
TASK_LEASE_SECONDS = 3600

#: Interrupted work the Owner hears about, with the ``kind`` of his letter. A day's letter is
#: `app.runbook.services.tell_day_interrupted`'s; the routine jobs (the watchdog, the reviews)
#: are recorded by their event and the log, and simply fire again on their schedule.
FILM_CONTINUE_INTERRUPTED_LETTER = "film_continue_interrupted"

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
        resume_of = str(payload.get("resume_of") or "") or None
        runners = stage_runners
        with Session(engine) as session:
            runs_today = session.scalars(
                select(DailyRun)
                .where(DailyRun.business_date == today)
                .order_by(DailyRun.started_at)
            ).all()
            done = next((run for run in runs_today if run.status in DAY_DONE_STATES), None)
            done_id = done.id if done is not None else None
            cut = next((run for run in runs_today if run.status in (INTERRUPTED, RUNNING)), None)
            cut_id = cut.id if cut is not None else None
            previous = session.get(DailyRun, resume_of) if resume_of else None
            previous_date = previous.business_date if previous is not None else None
            previous_status = previous.status if previous is not None else None
            previous_stages = (
                [dict(stage) for stage in (previous.stages_json or [])]
                if previous is not None
                else []
            )
            later = [
                run.id
                for run in runs_today
                if previous is not None and str(run.started_at) > str(previous.started_at)
            ]
        attempt = len(runs_today) + 1
        if resume_of is not None:
            # A day cut off under the studio (a shutdown, a crash), resumed after the start
            # (`passes.resume_interrupted_day`, 2026-10-12): the stages that run completed are
            # replayed from its record and the rest run — never a second subject or film.
            if previous is None or previous_date != today:
                return {
                    "status": "SKIPPED",
                    "reason": f"Reluarea era pentru ziua {previous_date or '?'}, care a trecut.",
                }
            if previous_status != INTERRUPTED or later:
                return {
                    "status": "SKIPPED",
                    "reason": (
                        f"Ziua {today} nu mai are nimic de reluat: rularea {resume_of[:8]} nu "
                        "mai este cea întreruptă."
                    ),
                    "run_id": later[-1] if later else resume_of,
                }
            if attempt > settings.daily_max_attempts:
                return {
                    "status": "SKIPPED",
                    "reason": (
                        f"Ziua {today} și-a folosit cele {settings.daily_max_attempts} "
                        "încercări; reluarea ei este decizia Owner-ului."
                    ),
                    "run_id": resume_of,
                }
            runners = resume_runners(previous_stages, stage_runners or {}, resume_of)
        elif not manual:
            if cut_id is not None:
                # A day cut off under the studio (a shutdown, a crash) — or one another
                # process is still running. Running it again would buy its films twice; the
                # Owner was told, and a second day today is his command (REL-03).
                return {
                    "status": "SKIPPED",
                    "reason": (
                        f"Ziua {today} a fost întreruptă (rularea {cut_id}); o nouă rulare azi "
                        "este decizia Owner-ului."
                    ),
                    "run_id": cut_id,
                }
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
                stage_runners=runners,
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
        if resume_of is not None:
            outcome["resumed_from"] = resume_of
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

    def film_continue(task: dict[str, Any]) -> dict[str, Any]:
        from app.runbook import stages  # noqa: PLC0415 - the stages import the whole studio

        payload = task.get("payload") or {}
        storyboard_id = str(payload.get("storyboard_id") or "")
        if not storyboard_id:
            raise NonRetryable("Continuarea nu numește filmul (storyboard_id lipsește).")
        outcome = stages.continue_film(
            engine,
            settings,
            vault,
            registry,
            storyboard_id,
            cause=str(payload.get("cause") or ""),
            correlation_id=task["id"],
        )
        deferred = int(payload.get("deferred") or 0)
        if (
            outcome.get("refusal") == "FILM_BUSY"
            and deferred < FILM_CONTINUE_DEFERRALS
            and not stop_requested(engine)
        ):
            # Someone else is buying for this film right now; the purchase is theirs, and
            # this continuation looks again once it has ended. Keyed per deferral, so a
            # restart queues nothing twice.
            following = deferred + 1
            again = enqueue_task(
                engine,
                FILM_CONTINUE,
                {**payload, "deferred": following},
                priority=4,
                max_attempts=1,
                idempotency_key=f"{task.get('idempotency_key') or task['id']}-later-{following}",
                not_before=(
                    datetime.now(UTC) + timedelta(seconds=FILM_CONTINUE_DEFER_SECONDS)
                ).isoformat(),
            )
            outcome = {**outcome, "deferred_task_id": again["id"]}
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
            "repairs": result.get("repairs", []),
            "escalated": result.get("escalated", []),
            "maturity": result.get("maturity"),
        }

    def director_repair(task: dict[str, Any]) -> dict[str, Any]:
        from app.agents.repairs.desk import execute_repair  # noqa: PLC0415

        return execute_repair(
            engine, registry, settings, task.get("payload") or {}, correlation_id=task["id"]
        )

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

    def backup(task: dict[str, Any]) -> dict[str, Any]:
        from app.backup import run_backup_job  # noqa: PLC0415

        result = run_backup_job(engine, settings, correlation_id=task["id"])
        if result["status"] != "COMPLETED":
            # Recorded as the failure it is (the event and the Owner's letter are written);
            # the next day's fire tries again, so the queue does not retry it now.
            raise NonRetryable(str(result["reason_ro"]))
        made = result["backup"]
        return {
            "status": "COMPLETED",
            "file": made["file"],
            "bytes": made["bytes"],
            "pruned": result["pruned"],
        }

    def sheet_repair(task: dict[str, Any]) -> dict[str, Any]:
        from app.media.blocker_repair import process_sheet_repair  # noqa: PLC0415

        if registry is None:
            raise NonRetryable("Remedierea foii are nevoie de furnizori AI conectați.")
        return process_sheet_repair(
            engine,
            registry,
            task["payload"],
            correlation_id=task["id"],
            settings=settings,
            sheet_context=repair_wiring(),
        )

    last_sheet_scan = 0.0

    def scan_sheets(_task: dict[str, Any]) -> dict[str, Any]:
        import time  # noqa: PLC0415

        from app.media.blocker_repair import allowed, scan_sheet_issues  # noqa: PLC0415

        nonlocal last_sheet_scan
        now = time.monotonic()
        if (
            now - last_sheet_scan < settings.sheet_blocker_scan_seconds
            or registry is None
            or not allowed(engine)
        ):
            return {"reported": []}
        last_sheet_scan = now
        return scan_sheet_issues(engine, read_live=True, settings=settings, **repair_wiring())

    def _environment() -> str:
        from app.models import OwnerPolicy  # noqa: PLC0415

        with Session(engine) as session:
            policy = session.get(OwnerPolicy, 1)
            return str(policy.environment) if policy else "TEST"

    def repair_wiring() -> dict[str, Any]:
        from app.runbook.stages import sheet_wiring  # noqa: PLC0415

        wiring = sheet_wiring(engine, vault, settings)
        return {
            "capabilities": wiring["capabilities"],
            "integration_id": wiring["integration_id"],
            "account": wiring["account"],
            "resolution": wiring["resolution"],
            "stills_model": getattr(wiring["image_adapter"], "model", None),
            "environment": _environment(),
        }

    return {
        "SCAN_FILM_SHEETS": scan_sheets,
        "FILM_SHEET_REPAIR": sheet_repair,
        DAILY_RUN: daily_run,
        FILM_CONTINUE: film_continue,
        WEEKLY_REVIEW: weekly_review,
        TRENDS_REFRESH: trends_refresh,
        MODEL_RESEARCH: model_research,
        MODEL_REVIEW: model_review,
        DIRECTOR_LOOP: director_loop,
        DIRECTOR_REPAIR: director_repair,
        WATCHDOG: watchdog,
        BACKUP: backup,
    }


class LeaseKeeper:
    """Renews a running handler's lease in the background, every half lease (A16, AR-17).

    `heartbeat_task` used to have no caller: a day longer than the lease was handed to the
    next claimer while it ran. The keeper stops when the handler returns; if the lease is no
    longer the holder's it says so in the log at once and stops renewing — the handler's
    outcome is then refused at completion (`LeaseLost`), never written over the new holder's.
    A failed renewal (a lock held elsewhere) is logged and tried again at the next beat.
    """

    def __init__(
        self,
        engine: Engine,
        task_id: str,
        lease_token: str,
        lease_seconds: int,
        every_seconds: float | None = None,
    ) -> None:
        self._engine = engine
        self._task_id = task_id
        self._token = lease_token
        self._lease = lease_seconds
        self._every = every_seconds if every_seconds is not None else max(1.0, lease_seconds / 2)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"lease-{task_id[:8]}", daemon=True)
        self.lost = False
        self.beats = 0

    def _run(self) -> None:
        while not self._stop.wait(self._every):
            try:
                held = heartbeat_task(
                    self._engine, self._task_id, self._token, extension_seconds=self._lease
                )
            except Exception as exc:  # noqa: BLE001 - one missed beat is not a lost lease
                logger.warning(
                    "task_heartbeat_failed",
                    extra={"task_id": self._task_id, "error_class": type(exc).__name__},
                )
                continue
            if not held:
                self.lost = True
                logger.error("task_lease_lost_while_running", extra={"task_id": self._task_id})
                return
            self.beats += 1

    def __enter__(self) -> LeaseKeeper:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stop.set()
        self._thread.join(timeout=30)


def _lease_lost(engine: Engine, task: dict[str, Any], outcome: str) -> dict[str, Any]:
    """The holder found its lease gone when it came to record the outcome: loud, recorded."""
    logger.error(
        "task_lease_lost",
        extra={"task_id": task["id"], "type": task["task_type"], "outcome": outcome},
    )
    with Session(engine) as session, session.begin():
        append_event(
            session,
            TASK_LEASE_LOST_EVENT,
            "task_queue",
            task["id"],
            1,
            {
                "task_type": task["task_type"],
                "outcome": outcome,
                "lease_token": task["lease_token"],
            },
            task["id"],
        )
    return {
        "task_id": task["id"],
        "status": "LEASE_LOST",
        "reason": (
            "Contractul sarcinii nu mai era al acestui lucrător la încheiere; rezultatul nu a "
            "fost scris peste al celui care o ține acum."
        ),
        "outcome": outcome,
    }


def work_once(
    engine: Engine,
    handlers: dict[str, TaskHandler],
    worker_id: str = "worker_main",
    *,
    lease_seconds: int = TASK_LEASE_SECONDS,
    heartbeat_seconds: float | None = None,
    observer: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Claim one task and run it to a recorded outcome. None when the queue has nothing.

    Nothing is claimed while the studio shuts down. The claim's own lease token (not the
    worker's id) is what completes or fails the task, and a `LeaseKeeper` renews the lease
    while the handler runs. ``observer`` (the process's ``app.state.operations``) holds the
    task being run under ``current_task`` while it runs, for /health/ready and the page.
    """
    if shutdown_requested(engine):
        return None
    task = claim_task(engine, worker_id, lease_duration_seconds=lease_seconds)
    if task is None:
        return None
    token = str(task["lease_token"])

    handler = handlers.get(task["task_type"])
    if handler is None:
        detail = f"Niciun executant pentru sarcini de tip {task['task_type']!r}."
        try:
            fail_task(engine, task["id"], token, detail, retryable=False)
        except LeaseLost:
            return _lease_lost(engine, task, "DEAD_LETTER")
        logger.warning("task_unhandled", extra={"task_id": task["id"], "type": task["task_type"]})
        return {"task_id": task["id"], "status": "DEAD_LETTER", "reason": detail}

    if observer is not None:
        observer["current_task"] = {
            "id": task["id"],
            "task_type": task["task_type"],
            "since": datetime.now(UTC).isoformat(),
        }
    with LeaseKeeper(engine, task["id"], token, lease_seconds, heartbeat_seconds):
        try:
            outcome = handler(task)
        except NonRetryable as exc:
            try:
                fail_task(engine, task["id"], token, str(exc), retryable=False)
            except LeaseLost:
                return _lease_lost(engine, task, "DEAD_LETTER")
            logger.warning("task_dead_lettered", extra={"task_id": task["id"], "reason": str(exc)})
            return {"task_id": task["id"], "status": "DEAD_LETTER", "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 - the failure is the record
            detail = f"{type(exc).__name__}: {exc}"[:2000]
            try:
                failed = fail_task(engine, task["id"], token, detail, retryable=True)
            except LeaseLost:
                return _lease_lost(engine, task, "FAILED")
            logger.error("task_failed", extra={"task_id": task["id"], "reason": detail})
            return {"task_id": task["id"], "status": failed["status"], "reason": detail}

    try:
        complete_task(engine, task["id"], token)
    except LeaseLost:
        return _lease_lost(engine, task, "COMPLETED")
    return {"task_id": task["id"], "status": "COMPLETED", "outcome": outcome}


def announce_interrupted(engine: Engine, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tell the Owner about interrupted work he cares for: a day, a film's continuation.

    Called with what `sweep_interrupted_tasks` just dead-lettered, so each is told once.
    """
    told: list[dict[str, Any]] = []
    for task in tasks:
        record: dict[str, Any] = {"id": task["id"], "task_type": task["task_type"]}
        try:
            if task["task_type"] == DAILY_RUN:
                record["day"] = interrupt_task_day(engine, task)
            elif task["task_type"] == FILM_CONTINUE:
                record["letter_id"] = _tell_continue_interrupted(engine, task)
        except Exception as exc:  # noqa: BLE001 - one letter must not lose the others
            logger.error(
                "interrupted_task_not_announced",
                extra={"task_id": task["id"], "error_class": type(exc).__name__},
            )
        told.append(record)
    return told


def _tell_continue_interrupted(engine: Engine, task: dict[str, Any]) -> str:
    from app.agents.memory import agent_for_role  # noqa: PLC0415 - agents import the runbook
    from app.agents.messages import post_message  # noqa: PLC0415

    storyboard_id = str((task.get("payload") or {}).get("storyboard_id") or "")
    film = f"filmului {storyboard_id[:8]}" if storyboard_id else "unui film"
    subject = f"Continuarea {film} a fost întreruptă"
    body = (
        f"Continuarea {film}, pornită de răspunsul tău, a fost întreruptă: procesul studioului "
        "s-a oprit în timpul ei (o repornire, o închidere forțată sau o cădere); nu o repornesc "
        "singur. Ce s-a cumpărat rămâne cumpărat și trecut în cărți, iar ce a acceptat un "
        "furnizor și nu a fost încă adus îl colectează supraveghetorul, fără să cumpere din nou. "
        "Următoarea rulare zilnică reia filmul de unde a rămas, iar aprobarea ta rămâne "
        "valabilă până expiră."
    )
    with Session(engine) as session, session.begin():
        director = agent_for_role(session, "Director")
        row = post_message(
            session,
            intent="ESCALATE",
            subject=subject,
            body={"kind": FILM_CONTINUE_INTERRUPTED_LETTER, "storyboard_id": storyboard_id},
            body_text=body,
            from_agent_id=director.id if director else None,
            to_owner=True,
            correlation_id=task["id"],
        )
        return row.id


def worker_pass(
    engine: Engine,
    handlers: dict[str, TaskHandler],
    worker_id: str = "worker_main",
    registry: Any = None,
    observer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One pass: close what died, fire what is due, run what is queued, then answer the mail.

    First the queue's dead are named: a task whose lease lapsed with no attempts left was
    being run by a process that is gone, and becomes DEAD_LETTER INTERRUPTED with a letter to
    the Owner when it was a day or a film's continuation — never run again on its own (REL-03).
    The mail comes last and only with a registry to run models through: a letter to an
    employee is answered by that employee within the pass, so an exchange the Director
    starts in the evening is a conversation by the next pass, not a note that waits a day.
    Nothing happens while the studio shuts down.
    """
    idle: dict[str, Any] = {"answered": [], "refused": []}
    if shutdown_requested(engine):
        return {"triggered": [], "ran": [], "mail": idle, "interrupted": []}
    interrupted = announce_interrupted(engine, sweep_interrupted_tasks(engine))
    if "SCAN_FILM_SHEETS" in handlers:
        try:
            handlers["SCAN_FILM_SHEETS"]({"payload": {}})
        except Exception as exc:
            logger.warning("sheet_blocker_scan_failed", extra={"error_class": type(exc).__name__})
    triggered = scheduler_tick(engine, leader_id=worker_id)
    ran: list[dict[str, Any]] = []
    for _ in range(TASKS_PER_PASS):
        result = work_once(engine, handlers, worker_id, observer=observer)
        if observer is not None:
            observer["current_task"] = None
        if result is None:
            break
        ran.append(result)
    mail: dict[str, Any] = idle
    if registry is not None and not shutdown_requested(engine):
        from app.agents.mail import correspondence_round  # noqa: PLC0415

        mail = correspondence_round(engine, registry)
    return {"triggered": triggered, "ran": ran, "mail": mail, "interrupted": interrupted}


# ------------------------------------------------------------ one worker per database --


class WorkerLock:
    """An OS lock on a file beside the database, held while this process runs the worker.

    The README's scheduled task plus a manual start could run two workers on one database,
    each claiming as 'worker_main' (AR-17). The lock is the operating system's: released when
    the holder releases it or its process ends, however it ends — no stale file to clean up.
    """

    def __init__(self, path: Path, handle: IO[str]) -> None:
        self.path = path
        self._handle: IO[str] | None = handle

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            _unlock(handle)
        except OSError:
            pass
        finally:
            handle.close()


def _lock(handle: IO[str]) -> None:
    """Lock the file's first byte without waiting; OSError when someone else holds it."""
    if sys.platform == "win32":
        import msvcrt  # noqa: PLC0415

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl  # noqa: PLC0415

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: IO[str]) -> None:
    if sys.platform == "win32":
        import msvcrt  # noqa: PLC0415

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl  # noqa: PLC0415

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def acquire_worker_lock(path: Path) -> WorkerLock | None:
    """Take the worker's lock at ``path``; None when another holder has it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+", encoding="utf-8")  # noqa: SIM115 - held until release()
    try:
        handle.seek(0)
        _lock(handle)
    except OSError:
        handle.close()
        return None
    return WorkerLock(path, handle)


def worker_lock_path(engine: Engine) -> Path | None:
    """``<database>.lock`` beside a database file (``data/studio.lock`` for the studio's own);
    None for a database that is not a file (in memory, a server), where a file lock beside it
    could not tell two hosts apart."""
    database = engine.url.database
    if engine.url.get_backend_name() != "sqlite" or not database or database == ":memory:":
        return None
    return Path(database).with_suffix(".lock")
