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

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import OwnerPolicy
from app.runbook.models import DailyRun, SafeModeRecord
from app.runbook.preflight import run_preflight
from app.services import append_event, utc_now
from app.story.services import business_date, close_daily_log
from app.workflows.services import append_event_with_outbox, enqueue_task, list_queue_tasks

#: The queue task type the daily run is executed under, by the schedule and by the Owner.
DAILY_RUN_TASK = "DAILY_RUN"

#: Queue states that mean a run is already on its way: starting a second one would have two
#: days running over each other on the same books.
PENDING_STATES = ("QUEUED", "RETRYING", "CLAIMED", "RUNNING")

#: The stages of the daily runbook, in order.
STAGES = (
    "preflight",
    "performance_intake",
    "idea_generation",
    "research_and_verification",
    "selection",
    "script_and_storyboard",
    "media",
    "edit_and_qc",
    "publish",
    "post_run",
    "daily_log",
    "serial_queue",
)

COMPLETED = "COMPLETED"
SKIPPED = "SKIPPED"
BLOCKED = "BLOCKED"
FAILED = "FAILED"


class RunbookError(RuntimeError):
    """The run could not start."""


class SafeModeActive(RunbookError):
    """The studio is in safe mode and will not act autonomously until a person clears it."""


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


def _stage(name: str, status: str, reason: str, artefacts: dict | None = None) -> dict[str, Any]:
    return {
        "stage": name,
        "status": status,
        "reason": reason,
        "artefacts": artefacts or {},
        "at": utc_now(),
    }


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
    correlation: str,
) -> list[dict[str, Any]]:
    """Replace the ``daily_log`` stage with the real outcome of closing the day's log."""
    try:
        log = close_daily_log(engine, settings.timezone, date_iso, correlation)
    except Exception as exc:  # noqa: BLE001 - the failure to close is itself the record
        closed = _stage("daily_log", FAILED, f"{type(exc).__name__}: {exc}"[:500])
    else:
        closed = _stage(
            "daily_log",
            COMPLETED,
            f"Jurnalul zilei {log['business_date']} a fost închis.",
            {"log_id": log["id"], "total_events": log["total_events"]},
        )
    return [stage if stage["stage"] != "daily_log" else closed for stage in stages]


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
    if existing is not None:
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


def execute_daily_run(
    engine: Engine,
    settings: Settings,
    vault: Any,
    correlation_id: str = "",
    stage_runners: dict[str, Callable[[], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run the day, stage by stage, and record the truth about each.

    ``stage_runners`` lets a caller supply real work for a stage. A stage with no runner is
    recorded SKIPPED with the reason — it is not silently omitted, because a run that lists ten
    stages and performed three has told the Owner something false by arrangement of the page.
    """
    correlation = correlation_id or str(uuid4())
    runners = stage_runners or {}

    safe = safe_mode_state(engine)
    if safe["active"]:
        raise SafeModeActive(
            f"Studioul este în mod sigur din {safe['entered_at']}: {safe['reason']} "
            "Nu pornește nicio rulare până nu închizi modul sigur."
        )

    preflight = run_preflight(engine, settings, vault)
    date_iso = business_date(settings.timezone)
    run_id = str(uuid4())
    started_at = utc_now()
    stages: list[dict[str, Any]] = [
        _stage(
            "preflight",
            COMPLETED if preflight["status"] != "BLOCKED" else BLOCKED,
            preflight["summary"],
            {"status": preflight["status"], "failures": preflight["blocking_failures"]},
        )
    ]

    stopped_at: str | None = None
    stop_reason: str | None = None

    _announce(
        engine,
        "runbook.daily_run_started",
        run_id,
        {"date": date_iso, "preflight": preflight["status"], "stages": len(STAGES)},
        correlation,
    )

    if preflight["status"] == "BLOCKED":
        stopped_at = "preflight"
        stop_reason = preflight["summary"]
        for name in STAGES[1:]:
            stages.append(_stage(name, BLOCKED, "Preflight blocant; etapa nu a fost încercată."))
    else:
        for name in STAGES[1:]:
            if stopped_at is not None:
                stages.append(_stage(name, BLOCKED, f"Rularea s-a oprit la etapa «{stopped_at}»."))
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
            try:
                outcome = runner()
            except Exception as exc:  # noqa: BLE001 - the stage's failure is the record
                reason = f"{type(exc).__name__}: {exc}"[:500]
                stages.append(_stage(name, FAILED, reason))
                _finished(engine, run_id, name, FAILED, reason, correlation)
                stopped_at = name
                stop_reason = f"Etapa «{name}» a eșuat: {type(exc).__name__}"
                continue
            status = str(outcome.get("status", COMPLETED))
            stages.append(
                _stage(name, status, str(outcome.get("reason", "")), outcome.get("artefacts"))
            )
            _finished(engine, run_id, name, status, str(outcome.get("reason", "")), correlation)
            if status in (BLOCKED, FAILED):
                stopped_at = name
                stop_reason = str(outcome.get("reason", "")) or f"Etapa «{name}» s-a oprit."

    # The day is closed from the event stream whenever the studio actually worked: a partial day
    # is still a day, and the log is what tomorrow's episode is checked against. A blocked
    # preflight is not a partial day — the studio did nothing, so there is nothing to close, and
    # writing a log for it would put an entry in the record for work that never happened. The
    # stage keeps the BLOCKED it was given.
    if preflight["status"] != "BLOCKED":
        stages = _close_the_day(stages, engine, settings, date_iso, correlation)

    status = _derive_status(stages)
    finished_at = utc_now()

    with Session(engine) as session, session.begin():
        event = append_event(
            session,
            "runbook.daily_run_finished",
            "daily_run",
            run_id,
            1,
            {"status": status, "preflight": preflight["status"]},
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
                started_at=started_at,
                finished_at=finished_at,
                event_id=event.event_id,
            )
        )
        # A failed stage is a P0 for an unattended studio: it stops rather than carrying on to
        # the next day's run with an unexamined fault behind it.
        if status == "FAILED":
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
