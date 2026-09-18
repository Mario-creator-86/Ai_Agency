"""Phase 10 — running the day, and recording what actually happened at each stage.

`../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` lays out the stages and the abort behaviour: a
hard gate failure blocks, a retryable failure retries within bounds, a P0 goes to safe mode.

The design pressure here is different from earlier phases. Nothing in a daily run invents a fact
about the world; the risk is a run that *reports* more than it did. A stage that could not run
because a provider is missing is not a stage that succeeded quietly, and a run that stopped at
step four is not a completed day. So:

- a stage is recorded with its real outcome and the reason for it, including SKIPPED;
- the run's status is derived from its stages, never written by a caller;
- the preflight verdict is stored with the run, because "the studio ran today" means something
  different on a day when half the capabilities were missing.
"""

from __future__ import annotations

import http.client
import logging
import re
import socket
import sqlite3
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import OwnerPolicy
from app.runbook.models import DailyRun, SafeModeRecord
from app.runbook.preflight import run_preflight
from app.services import append_event, utc_now
from app.story.services import business_date, close_daily_log, close_previous_day
from app.workflows.services import append_event_with_outbox, enqueue_task, list_queue_tasks

logger = logging.getLogger("studio.runbook")

#: The queue task type the daily run is executed under, by the schedule and by the Owner.
DAILY_RUN_TASK = "DAILY_RUN"

#: Queue states that mean a run is already on its way: starting a second one would have two
#: days running over each other on the same books.
PENDING_STATES = ("QUEUED", "RETRYING", "CLAIMED", "RUNNING")

#: The stages of the daily runbook, in order. The serial queue (runbook §12) runs before
#: the media stage rather than after the day's log: it writes the episode of the *previous*
#: day, whose log is closed at the start of the run, and leaves a storyboard that the same
#: run's media stage films, quality control measures and the publish stage routes to
#: Channel B. Last in the list it was a stage the day never rendered — the serial existed
#: as text only. The day's own log stays the last thing the run does.
STAGES = (
    "preflight",
    "performance_intake",
    "idea_generation",
    "research_and_verification",
    "selection",
    "script_and_storyboard",
    "serial_queue",
    "media",
    "edit_and_qc",
    "publish",
    "post_run",
    "daily_log",
)

COMPLETED = "COMPLETED"
SKIPPED = "SKIPPED"
BLOCKED = "BLOCKED"
FAILED = "FAILED"

#: The two kinds of fault a stage can fail on. TRANSIENT is the world being slow — a
#: timeout, a provider's 429 or 5xx, SQLite's "database is locked" — and is retried in
#: place; a run that still fails is FAILED without safe mode, because nothing about the
#: studio is wrong. HARD is everything else — a wrong value, a policy refusal, a bug —
#: and keeps the old behaviour: FAILED, safe mode, a person looks.
TRANSIENT = "TRANSIENT"
HARD = "HARD"

#: What a stage is told when the Owner's switch ends the day under it.
OWNER_STOP_REASON = "Oprit de AUTONOMIE OPRITĂ."

#: HTTP statuses that say "not now" rather than "not like that".
_TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}
_HTTP_IN_MESSAGE = re.compile(r"\bHTTP (\d{3})\b")


class RunbookError(RuntimeError):
    """The run could not start."""


class SafeModeActive(RunbookError):
    """The studio is in safe mode and will not act autonomously until a person clears it."""


class TransientStageError(RuntimeError):
    """A stage runner saying its failure is the world's, not the studio's: retry me.

    For the cases the classifier cannot see from the exception's shape — a provider job that
    reported "queued" for longer than the stage would wait, a vendor answering 200 with an
    error body. Raising this instead of a bare RuntimeError is what makes the difference
    between a retry twenty seconds later and safe mode until a person clears it.
    """


def _http_status(exc: BaseException) -> int | None:
    """The HTTP status an exception carries, wherever the raising code put it."""
    for attribute in ("http_status", "status", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    found = _HTTP_IN_MESSAGE.search(str(exc))
    return int(found.group(1)) if found else None


def _is_transient(exc: BaseException) -> bool:
    from app.providers.media_http import MediaProviderNotConfigured  # noqa: PLC0415
    from app.providers.publishing_base import RemoteStateUnavailable  # noqa: PLC0415

    if isinstance(exc, TransientStageError):
        return True
    if isinstance(exc, MediaProviderNotConfigured):
        return False  # no key is a configuration fact, and waiting will not produce one
    if isinstance(exc, OperationalError | sqlite3.OperationalError):
        return True  # "database is locked", "unable to open database file": try again
    if isinstance(exc, RemoteStateUnavailable):
        return True  # the platform could not be asked; asking again is safe, it is a read
    status = _http_status(exc)
    if status is not None:
        # A status is the provider's own word: 4xx other than the rate limit is our
        # request being wrong, and repeating it repeats the answer.
        return status in _TRANSIENT_HTTP
    if isinstance(exc, HTTPError):
        return False
    # Network shapes. Not OSError wholesale: a missing file or a full disk is an OSError too,
    # and no retry fills a disk.
    return isinstance(
        exc,
        TimeoutError
        | ConnectionError
        | socket.gaierror
        | socket.herror
        | URLError
        | http.client.HTTPException,
    )


def classify_fault(exc: BaseException) -> str:
    """TRANSIENT or HARD, from the exception and the chain it was raised from.

    The chain matters because the studio wraps: `media_http.request` raises
    `MediaProviderError("… could not be reached") from OSError`, and a stage may wrap that
    again. The walk follows what a traceback would print — the explicit cause, else the
    implicit context unless suppressed — and stops at the first transient link. Anything
    the walk cannot name is HARD, because retrying an unknown fault is how a studio spends
    a night repeating a bug.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if _is_transient(current):
            return TRANSIENT
        if current.__cause__ is not None:
            current = current.__cause__
        elif not current.__suppress_context__:
            current = current.__context__
        else:
            current = None
    return HARD


def stop_requested(engine: Engine) -> bool:
    """Has the Owner set AUTONOMIE OPRITĂ since the work started?

    For anything that runs long inside a stage and can stop cleanly between steps — the
    media loop between scenes, a render between shots, a publish loop between videos.
    Poll it between units of work, never mid-write, and on True stop where you are and
    return what was done so far (or raise; the run records the stage BLOCKED with
    `OWNER_STOP_REASON` either way). One short read of the policy row; cheap enough to
    call before every scene. The runbook itself calls it between stages, so a stage that
    does not poll still ends the day at its own boundary.
    """
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        return bool(policy is not None and policy.autonomy_stopped)


def retryable_outcome(status: str, preflight_status: str, fault_class: str | None) -> bool:
    """Whether a day that ended like this may be attempted again by the clock today.

    Yes for a BLOCKED preflight (a provider that was down at five may be up at six) and
    for a FAILED run whose fault was transient. No for a day that did work — COMPLETED or
    PARTIAL is one day's production, and a second is the Owner's decision — and no for a
    hard failure, which is in safe mode waiting for a person.
    """
    if status == "BLOCKED" and preflight_status == "BLOCKED":
        return True
    return status == "FAILED" and fault_class == TRANSIENT


def _run_with_retries(
    engine: Engine,
    settings: Settings,
    run_id: str,
    name: str,
    runner: Callable[[], dict[str, Any]],
    wait: Callable[[float], None],
    correlation: str,
) -> tuple[dict[str, Any] | None, BaseException | None, int]:
    """Run a stage; on a transient fault, again after a wait, up to the configured tries.

    Returns (outcome, error, attempts): exactly one of outcome and error is set. The
    backoff doubles from `stage_retry_backoff_seconds` (20, 40, 80 by default), and each
    retry is announced so the ledger shows a stage waiting rather than a stage hanging.
    The Owner's stop is read before each retry: a stop during the wait ends the retries,
    and the runbook then records the stage as it would any failed one.
    """
    attempts = 0
    while True:
        attempts += 1
        try:
            return runner(), None, attempts
        except Exception as exc:  # noqa: BLE001 - the stage's failure is the record
            retries_left = settings.stage_retry_attempts - (attempts - 1)
            if classify_fault(exc) != TRANSIENT or retries_left <= 0 or stop_requested(engine):
                return None, exc, attempts
            backoff = settings.stage_retry_backoff_seconds * (2 ** (attempts - 1))
            reason = (
                f"Etapa «{name}» a dat o eroare trecătoare ({type(exc).__name__}); "
                f"reîncerc în {backoff}s (încercarea {attempts + 1} din "
                f"{settings.stage_retry_attempts + 1})."
            )
            logger.warning(
                "stage_retrying",
                extra={"run_id": run_id, "stage": name, "attempt": attempts, "wait": backoff},
            )
            _announce(
                engine,
                "runbook.stage_retrying",
                run_id,
                {"stage": name, "attempt": attempts, "wait_seconds": backoff, "reason": reason},
                correlation,
            )
            wait(backoff)


def _announce(
    engine: Engine,
    event_type: str,
    run_id: str,
    payload: dict[str, Any],
    correlation_id: str,
) -> None:
    """Say what the day is doing, as it does it.

    A run used to be silent until it was over: one `runbook.daily_run_finished` event after
    ten minutes of work. The Owner watching the ledger saw employees talking with no idea
    which stage they were in. These go through the outbox, so they reach the open page live.
    """
    with Session(engine) as session, session.begin():
        append_event_with_outbox(
            session, event_type, "daily_run", run_id, 1, payload, correlation_id
        )


def _open_safe_mode(session: Session, reason: str, trigger: str, run_id: str | None) -> None:
    existing = session.scalars(
        select(SafeModeRecord).where(SafeModeRecord.cleared_at.is_(None))
    ).first()
    if existing is not None:
        return  # Already in safe mode; a second record would obscure when it began.
    identifier = str(uuid4())
    event = append_event(
        session,
        "runbook.safe_mode_entered",
        "safe_mode_record",
        identifier,
        1,
        {"trigger": trigger, "run_id": run_id},
        str(uuid4()),
    )
    session.add(
        SafeModeRecord(
            id=identifier,
            reason=reason[:2000],
            trigger=trigger,
            run_id=run_id,
            entered_at=utc_now(),
            cleared_at=None,
            cleared_notes=None,
            event_id=event.event_id,
        )
    )
    policy = session.get(OwnerPolicy, 1)
    if policy is not None:
        policy.autonomy_stopped = True
        policy.version += 1
        policy.updated_at = utc_now()


def safe_mode_state(engine: Engine) -> dict[str, Any]:
    with Session(engine) as session:
        current = session.scalars(
            select(SafeModeRecord)
            .where(SafeModeRecord.cleared_at.is_(None))
            .order_by(SafeModeRecord.entered_at.desc())
        ).first()
        return {
            "active": current is not None,
            "reason": current.reason if current else None,
            "trigger": current.trigger if current else None,
            "entered_at": current.entered_at if current else None,
            "record_id": current.id if current else None,
        }


def clear_safe_mode(engine: Engine, notes: str, correlation_id: str = "") -> dict[str, Any]:
    """Leave safe mode. Requires a note: a P0 is cleared by a person who looked at it.

    Autonomy is deliberately *not* restarted here. Leaving safe mode says the incident was
    examined; deciding the studio should act again is a separate choice, and folding the two
    together would let one click undo both.
    """
    if not notes.strip():
        raise RunbookError(
            "Scrie ce ai verificat înainte de a ieși din modul sigur; nota rămâne în istoric."
        )
    with Session(engine) as session, session.begin():
        current = session.scalars(
            select(SafeModeRecord).where(SafeModeRecord.cleared_at.is_(None))
        ).first()
        if current is None:
            raise RunbookError("Studioul nu este în mod sigur.")
        current.cleared_at = utc_now()
        current.cleared_notes = notes.strip()[:2000]
        current.event_id = append_event(
            session,
            "runbook.safe_mode_cleared",
            "safe_mode_record",
            current.id,
            2,
            {},
            correlation_id or str(uuid4()),
        ).event_id
        return {
            "cleared": True,
            "note": (
                "Modul sigur a fost închis. Autonomia rămâne oprită — pornește-o separat, "
                "când ești sigur că studioul poate lucra din nou."
            ),
        }


def _stage(
    name: str,
    status: str,
    reason: str,
    artefacts: dict | None = None,
    *,
    fault_class: str | None = None,
    attempts: int | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "stage": name,
        "status": status,
        "reason": reason,
        "artefacts": artefacts or {},
        "fault_class": fault_class,
        "at": utc_now(),
    }
    if attempts is not None:
        record["attempts"] = attempts
    return record


def _derive_status(stages: list[dict[str, Any]]) -> str:
    """A run's status is what its stages add up to, not what the caller hoped for."""
    if any(stage["status"] == FAILED for stage in stages):
        return "FAILED"
    if any(stage["status"] == BLOCKED for stage in stages):
        return "BLOCKED"
    if any(stage["status"] == SKIPPED for stage in stages):
        return "PARTIAL"
    return "COMPLETED"


def _close_the_day(
    stages: list[dict[str, Any]],
    engine: Engine,
    settings: Settings,
    date_iso: str,
    run_id: str,
    wait: Callable[[float], None],
    correlation: str,
) -> list[dict[str, Any]]:
    """Replace the ``daily_log`` stage with the real outcome of closing the day's log.

    The close is a stage like the others: a lock on the log table is retried in place, and
    what still fails carries its class, so a hard fault here opens safe mode as a hard fault
    anywhere does. It used to be FAILED with no class at all, which neither safe mode nor
    the clock's re-attempt could see — a run that failed at its last step slipped past both.
    """
    outcome, error, attempts = _run_with_retries(
        engine,
        settings,
        run_id,
        "daily_log",
        lambda: close_daily_log(engine, settings.timezone, date_iso, correlation),
        wait,
        correlation,
    )
    if error is not None:
        closed = _stage(
            "daily_log",
            FAILED,
            f"{type(error).__name__}: {error}"[:500],
            fault_class=classify_fault(error),
            attempts=attempts,
        )
    else:
        assert outcome is not None  # one of the two is always set
        closed = _stage(
            "daily_log",
            COMPLETED,
            f"Jurnalul zilei {outcome['business_date']} a fost închis.",
            {"log_id": outcome["id"], "total_events": outcome["total_events"]},
            attempts=attempts,
        )
    return [stage if stage["stage"] != "daily_log" else closed for stage in stages]


def _close_previous_day(
    engine: Engine,
    settings: Settings,
    run_id: str,
    wait: Callable[[float], None],
    correlation: str,
) -> dict[str, Any]:
    """Close the previous business date in full, retried like a stage; the log or the fault."""
    outcome, error, attempts = _run_with_retries(
        engine,
        settings,
        run_id,
        "previous_day_log",
        lambda: close_previous_day(engine, settings, correlation),
        wait,
        correlation,
    )
    if error is not None:
        reason = f"{type(error).__name__}: {error}"[:500]
        logger.warning(
            "previous_day_not_closed",
            extra={"run_id": run_id, "attempts": attempts, "fault_class": classify_fault(error)},
        )
        return {"error": reason, "fault_class": classify_fault(error), "attempts": attempts}
    assert outcome is not None  # one of the two is always set
    return {
        "id": outcome["id"],
        "business_date": outcome["business_date"],
        "status": outcome["status"],
        "total_events": outcome["total_events"],
        "event_counts": outcome["event_counts"],
        "closed_at": outcome["closed_at"],
        "attempts": attempts,
    }


def _finished(
    engine: Engine, run_id: str, stage: str, status: str, reason: str, correlation_id: str
) -> None:
    _announce(
        engine,
        "runbook.stage_finished",
        run_id,
        {"stage": stage, "status": status, "reason": reason[:300]},
        correlation_id,
    )


def pending_daily_run(engine: Engine) -> dict[str, Any] | None:
    """The queued or running daily run, if the studio has one on its way."""
    for task in list_queue_tasks(engine, limit=50):
        if task["task_type"] == DAILY_RUN_TASK and task["status"] in PENDING_STATES:
            return task
    return None


def _is_waiting_retry(task: dict[str, Any]) -> bool:
    """A same-day re-attempt that has not started yet.

    It is not "a run in progress" to the Owner: refusing his button for the half hour a
    retry waits would hold the studio to the clock's patience instead of his. The manual
    run goes ahead; when the retry's time comes it finds the day done and skips itself.
    """
    return task["status"] == "QUEUED" and bool((task.get("payload") or {}).get("retry_of"))


def start_daily_run(
    engine: Engine, settings: Settings, command_id: str, worker_enabled: bool = True
) -> dict[str, Any]:
    """Put today's run in the queue and return — the worker does the day.

    The run itself takes minutes: agents think, a render is waited on, quality control reads
    the file. Executing it inside the Owner's request meant the browser gave up long before
    the studio did and said the connection was unavailable, while the studio went on working.
    So the button queues the work and says so; what happens next is in the ledger, stage by
    stage, and in the runs list when the day is closed.
    """
    safe = safe_mode_state(engine)
    if safe["active"]:
        raise SafeModeActive(
            f"Studioul este în mod sigur din {safe['entered_at']}: {safe['reason']} "
            "Nu pornește nicio rulare până nu închizi modul sigur."
        )
    if not worker_enabled:
        raise RunbookError(
            "Lucrătorul de fundal este oprit în configurație, deci nimeni nu ar prelua "
            "rularea. Pornește-l (worker_enabled) și încearcă din nou."
        )
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        if policy is not None and policy.autonomy_stopped:
            raise RunbookError(
                "Autonomia este oprită: nimic nu pornește până nu o repornești de la "
                "comutatorul AUTONOMIE."
            )
    existing = pending_daily_run(engine)
    if existing is not None and not _is_waiting_retry(existing):
        raise RunbookError(
            f"O rulare zilnică este deja în lucru (pusă la coadă la {existing['created_at']}). "
            "Așteapt-o pe aceasta."
        )
    task = enqueue_task(
        engine,
        DAILY_RUN_TASK,
        {"manual": True, "requested_at": utc_now(), "date": business_date(settings.timezone)},
        priority=10,
        max_attempts=1,
        idempotency_key=f"manual-run-{command_id}",
    )
    return {
        "status": "QUEUED",
        "task_id": task["id"],
        "queued_at": task["created_at"],
        "message": (
            "Rularea de azi a fost pornită. Prima etapă începe în câteva secunde; "
            "urmărește-o în registrul din stânga."
        ),
    }


def finish_media_setup(engine: Engine, vault: Any) -> dict[str, Any] | None:
    """Fill the empty media defaults from the account's own catalogue, if any are empty."""
    from app.integrations.autoconfig import auto_configure  # noqa: PLC0415
    from app.media.factory import media_readiness  # noqa: PLC0415

    if all(item["status"] == "READY" for item in media_readiness(engine, vault).values()):
        return None
    try:
        return auto_configure(engine, vault)
    except Exception as exc:  # noqa: BLE001 - setup that cannot finish must not stop the day
        logger.info("media_setup_not_finished", extra={"error": type(exc).__name__})
        return None


def execute_daily_run(
    engine: Engine,
    settings: Settings,
    vault: Any,
    correlation_id: str = "",
    stage_runners: dict[str, Callable[[], dict[str, Any]]] | None = None,
    attempt: int = 1,
    attempts_allowed: int = 1,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Run the day, stage by stage, and record the truth about each.

    ``stage_runners`` lets a caller supply real work for a stage. A stage with no runner is
    recorded SKIPPED with the reason — it is not silently omitted, because a run that lists ten
    stages and performed three has told the Owner something false by arrangement of the page.

    A stage that raises is classified (`classify_fault`). A transient fault is retried in
    place, ``settings.stage_retry_attempts`` times with exponential backoff, and only then
    fails the run — without safe mode, because nothing about the studio is wrong. A hard
    fault fails the run at once and opens safe mode, as before. Between stages the Owner's
    stop is read again: a day already running stops where it is, the rest BLOCKED, with no
    safe mode and no letter — the Owner did it.

    ``attempt`` of ``attempts_allowed`` is where this run stands in the day's re-attempts.
    The Director's letter about a stopped day goes to the Owner only when no further attempt
    will follow: after the last one, or after a fault a re-attempt could not change.
    ``sleep`` is the backoff clock, injectable so a test does not wait a minute.
    """
    correlation = correlation_id or str(uuid4())
    runners = stage_runners or {}
    wait = sleep or time.sleep

    safe = safe_mode_state(engine)
    if safe["active"]:
        raise SafeModeActive(
            f"Studioul este în mod sigur din {safe['entered_at']}: {safe['reason']} "
            "Nu pornește nicio rulare până nu închizi modul sigur."
        )

    # A verified connection with no default model or voice is the studio's own unfinished
    # setup, not a fact about the world: the catalogue already says what the account can
    # do. The day fills what is empty before it judges itself, so an Owner who connected a
    # voice and an image service gets narration and stills, not a DEGRADED preflight about
    # a form in Settings.
    finish_media_setup(engine, vault)
    preflight = run_preflight(engine, settings, vault)
    date_iso = business_date(settings.timezone)
    run_id = str(uuid4())
    started_at = utc_now()
    stages: list[dict[str, Any]] = [
        _stage(
            "preflight",
            COMPLETED if preflight["status"] != "BLOCKED" else BLOCKED,
            preflight["summary"],
            {
                "status": preflight["status"],
                "failures": preflight["blocking_failures"],
                # Which stages this day was even allowed to attempt. Read back a week later,
                # a day of skipped stages says whether the studio lacked something or the
                # Owner had it on a shorter leash.
                "autonomy_mode": preflight["autonomy_mode"],
            },
        )
    ]

    stopped_at: str | None = None
    stop_reason: str | None = None
    fault_class: str | None = None
    owner_stopped = False

    _announce(
        engine,
        "runbook.daily_run_started",
        run_id,
        {
            "date": date_iso,
            "preflight": preflight["status"],
            "autonomy_mode": preflight["autonomy_mode"],
            "stages": len(STAGES),
            "attempt": attempt,
            "attempts_allowed": attempts_allowed,
        },
        correlation,
    )

    if preflight["status"] == "BLOCKED":
        stopped_at = "preflight"
        stop_reason = preflight["summary"]
        for name in STAGES[1:]:
            stages.append(_stage(name, BLOCKED, "Preflight blocant; etapa nu a fost încercată."))
    else:
        # Yesterday is closed first, with every event of its date. Measured live: the day's
        # log was frozen at the run's own hour (the morning of its date, 92 events, one of
        # them narratable), because the only close was the one at the end of this run. The
        # previous business date is over now, which is the one moment a full day can be
        # counted, and the serial stage below reads that log. A date already closed is
        # returned as it is — a closed log never changes. Today's close at the end of the
        # run is kept, so the day the run completes is still frozen at the run's hour; a
        # full-day log for every date needs that close moved, which is recorded as open.
        # A fault here is retried like a stage's and then recorded on the preflight line
        # rather than ending the day: yesterday's record is not today's work, and the
        # serial stage simply finds no closed day to tell.
        stages[0]["artefacts"]["previous_day_log"] = _close_previous_day(
            engine, settings, run_id, wait, correlation
        )
        for name in STAGES[1:]:
            if owner_stopped:
                stages.append(_stage(name, BLOCKED, OWNER_STOP_REASON))
                continue
            if stopped_at is not None:
                stages.append(_stage(name, BLOCKED, f"Rularea s-a oprit la etapa «{stopped_at}»."))
                continue
            # The switch is read again before every stage. It used to be read once, at the
            # gate: an Owner who pressed STOP at stage three watched the studio spend the
            # remaining nine anyway.
            if stop_requested(engine):
                owner_stopped = True
                stopped_at = name
                stop_reason = OWNER_STOP_REASON
                stages.append(_stage(name, BLOCKED, OWNER_STOP_REASON))
                _finished(engine, run_id, name, BLOCKED, OWNER_STOP_REASON, correlation)
                continue
            runner = runners.get(name)
            _announce(
                engine,
                "runbook.stage_started",
                run_id,
                {"stage": name, "index": STAGES.index(name) + 1, "total": len(STAGES)},
                correlation,
            )
            if runner is None:
                reason = "Nicio implementare conectată pentru această etapă în această rulare."
                stages.append(_stage(name, SKIPPED, reason))
                _finished(engine, run_id, name, SKIPPED, reason, correlation)
                continue
            outcome, error, attempts = _run_with_retries(
                engine, settings, run_id, name, runner, wait, correlation
            )
            if error is not None:
                reason = f"{type(error).__name__}: {error}"[:500]
                stopped_at = name
                if stop_requested(engine):
                    # A runner that polls `stop_requested` may raise to get out; a runner
                    # that does not may have been failed by the stop itself (a connection
                    # closed under it). Either way the Owner ended the day: BLOCKED, with
                    # what the stage said kept in the record, and no fault.
                    owner_stopped = True
                    stop_reason = OWNER_STOP_REASON
                    stages.append(
                        _stage(name, BLOCKED, f"{OWNER_STOP_REASON} ({reason})", attempts=attempts)
                    )
                    _finished(engine, run_id, name, BLOCKED, OWNER_STOP_REASON, correlation)
                    continue
                fault_class = classify_fault(error)
                stages.append(
                    _stage(name, FAILED, reason, fault_class=fault_class, attempts=attempts)
                )
                _finished(engine, run_id, name, FAILED, reason, correlation)
                if fault_class == TRANSIENT:
                    stop_reason = (
                        f"Etapa «{name}» a eșuat după {attempts} încercări, pe o eroare "
                        f"trecătoare: {type(error).__name__}"
                    )
                else:
                    stop_reason = f"Etapa «{name}» a eșuat: {type(error).__name__}"
                continue
            assert outcome is not None  # one of the two is always set
            status = str(outcome.get("status", COMPLETED))
            stage_fault = None
            if status == FAILED:
                # A runner that reports its own failure says which kind, or it is hard: a
                # stage that knows the fault is passing has to say so to be retried.
                stage_fault = str(outcome.get("fault_class") or HARD)
                fault_class = stage_fault
            stages.append(
                _stage(
                    name,
                    status,
                    str(outcome.get("reason", "")),
                    outcome.get("artefacts"),
                    fault_class=stage_fault,
                    attempts=attempts,
                )
            )
            _finished(engine, run_id, name, status, str(outcome.get("reason", "")), correlation)
            if status in (BLOCKED, FAILED):
                stopped_at = name
                stop_reason = str(outcome.get("reason", "")) or f"Etapa «{name}» s-a oprit."
                if status == BLOCKED and stop_requested(engine):
                    # The stage stopped itself because the Owner asked (the media loop
                    # between scenes): his decision, not a gate refusing.
                    owner_stopped = True

    # The day is closed from the event stream whenever the studio actually worked: a partial day
    # is still a day, and the log is what tomorrow's episode is checked against. A blocked
    # preflight is not a partial day — the studio did nothing, so there is nothing to close, and
    # writing a log for it would put an entry in the record for work that never happened. The
    # stage keeps the BLOCKED it was given. A day the Owner stopped before any stage ran is the
    # same: nothing happened, nothing to close.
    worked = any(s["status"] == COMPLETED for s in stages[1:])
    if preflight["status"] != "BLOCKED" and (worked or not owner_stopped):
        stages = _close_the_day(stages, engine, settings, date_iso, run_id, wait, correlation)
        closing = next(s for s in stages if s["stage"] == "daily_log")
        if closing["status"] == FAILED and stopped_at is None:
            # A day that went well until its last step: the close's fault is the run's, and
            # the Director says where it stopped, as for any stage.
            fault_class = closing["fault_class"]
            stopped_at = "daily_log"
            stop_reason = f"Etapa «daily_log» a eșuat: {closing['reason'].split(':', 1)[0]}"

    if owner_stopped:
        # Not FAILED, whatever the stages say: the Owner ended the day, nothing broke. PARTIAL
        # if the studio did some of it, BLOCKED if it did none.
        status = "PARTIAL" if worked else "BLOCKED"
    else:
        status = _derive_status(stages)
    if status != "FAILED":
        fault_class = None
    finished_at = utc_now()
    retryable = retryable_outcome(status, preflight["status"], fault_class)
    another_attempt = retryable and attempt < attempts_allowed
    if stopped_at is not None and not owner_stopped and not another_attempt:
        # A day that stopped is the Owner's to unblock: the Director says where and why —
        # once, after the day's last attempt, not after each of them.
        from app.agents.director import letter_to_owner  # noqa: PLC0415

        tried = f" Am încercat de {attempt} ori azi." if attempts_allowed > 1 and retryable else ""
        letter_to_owner(
            engine,
            f"Ziua s-a oprit la etapa «{stopped_at}»",
            f"Rularea din {date_iso} s-a oprit la etapa «{stopped_at}»: {stop_reason}. "
            f"Etapele de după ea nu au rulat.{tried} Spune-mi ce ai reparat și pornesc din "
            "nou. — Sarah",
            correlation,
        )

    with Session(engine) as session, session.begin():
        event = append_event(
            session,
            "runbook.daily_run_finished",
            "daily_run",
            run_id,
            1,
            {
                "status": status,
                "preflight": preflight["status"],
                "fault_class": fault_class,
                "attempt": attempt,
                "owner_stopped": owner_stopped,
            },
            correlation,
        )
        session.add(
            DailyRun(
                id=run_id,
                business_date=date_iso,
                preflight_status=preflight["status"],
                preflight_json=preflight,
                status=status,
                stages_json=stages,
                stages_total=len(stages),
                stages_completed=sum(1 for s in stages if s["status"] == COMPLETED),
                stopped_at_stage=stopped_at,
                stop_reason=stop_reason,
                fault_class=fault_class,
                started_at=started_at,
                finished_at=finished_at,
                event_id=event.event_id,
            )
        )
        # A hard failure is a P0 for an unattended studio: it stops rather than carrying on
        # to the next day's run with an unexamined fault behind it. A transient one is not:
        # measured on the live copy, one "database is locked" opened safe mode and set the
        # autonomy stop, and the studio stood still for days over a lock that was free a
        # second later.
        if status == "FAILED" and fault_class == HARD:
            _open_safe_mode(
                session,
                stop_reason or "O etapă a rulării zilnice a eșuat.",
                "STAGE_FAILURE",
                run_id,
            )

    return {
        "id": run_id,
        "business_date": date_iso,
        "preflight": preflight,
        "status": status,
        "stages": stages,
        "stages_total": len(stages),
        "stages_completed": sum(1 for s in stages if s["status"] == COMPLETED),
        "stopped_at_stage": stopped_at,
        "stop_reason": stop_reason,
        "fault_class": fault_class,
        "owner_stopped": owner_stopped,
        "attempt": attempt,
        "retryable": retryable,
        "started_at": started_at,
        "finished_at": finished_at,
        "safe_mode": safe_mode_state(engine),
    }


def list_runs(engine: Engine, limit: int = 20) -> list[dict[str, Any]]:
    with Session(engine) as session:
        return [
            {
                "id": run.id,
                "business_date": run.business_date,
                "preflight_status": run.preflight_status,
                "status": run.status,
                "stages_total": run.stages_total,
                "stages_completed": run.stages_completed,
                "stopped_at_stage": run.stopped_at_stage,
                "stop_reason": run.stop_reason,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "stages": run.stages_json,
            }
            for run in session.scalars(
                select(DailyRun).order_by(DailyRun.started_at.desc()).limit(limit)
            )
        ]
