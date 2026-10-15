"""A day cut off under the studio is resumed by itself after the start (2026-10-12).

The Owner, 07:40: «de acum încolo, să dai singur restart la proiect, nu mă aștepta pe mine!» —
the studio is restarted for every code change, without him. A restart during the day ends it
at its boundary, INTERRUPTED (REL-10), and until today nothing ran it again: the clock skips a
day that was cut off (running it whole would choose a second subject and buy a second film),
and the Director's letter told the Owner to press «Pornește rularea de azi». A day cut off
before its log closed left the serial without its next episode.

So this pass, on every watchdog tick, finds today's newest run when it is INTERRUPTED and
nothing ran after it (`runbook.services.resumable_run`) and queues one DAILY_RUN with
``resume_of``: the worker replays the stages that run completed from their record (nothing
done again, no second film) and runs the stage it stopped in and the rest
(`runbook.services.resume_runners`). One task per interrupted run and per start of the
studio (the key); a resumed run cut off again is resumed again, within the day's attempts.
Nothing is queued while the studio stops or shuts down, in safe mode, or while a DAILY_RUN
task is queued or at work.

Measured 2026-10-15, 01:47–04:40 Bucharest: the run fd287887 was cut off by two restarts,
its one resume task ran at 01:47 and was refused by the worker (the day's attempts were
counted as used), and from then on every tick found that finished task under its key,
announced «daily run resume queued» again — eighteen times — and resumed nothing. So the
key now names the start of this process too (one try per start, as the docstring says), and
the event is written only when the task is new: a task the queue already holds, finished or
not, is never announced twice.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.workflows.passes import WatchdogContext, watchdog_pass

#: A DAILY_RUN already queued or at work: the day is in hands.
PENDING_TASK_STATES = ("QUEUED", "RETRYING", "CLAIMED", "RUNNING")

#: This process's start, as far as the queue is concerned: a resume is asked once per
#: interrupted run per start of the studio, never again within the same process.
START_TOKEN = uuid4().hex[:8]


def resume_task_key(run_id: str, start_token: str | None = None) -> str:
    """The idempotency key of the one resume task of ``run_id`` in this start of the studio."""
    return f"daily-resume-{run_id}-{start_token or START_TOKEN}"


@watchdog_pass("resume_interrupted_day", order=20, on_error={"queued": []})
def resume_interrupted_days(context: WatchdogContext) -> dict[str, Any]:
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.runbook.services import (  # noqa: PLC0415 - the runbook imports the studio
        DAILY_RUN_TASK,
        DAY_RESUME_QUEUED_EVENT,
        RESUME_CAUSE,
        resumable_run,
        safe_mode_state,
        stop_requested,
    )
    from app.services import append_event  # noqa: PLC0415
    from app.story.services import business_date  # noqa: PLC0415
    from app.workflows.models import TaskQueueItem  # noqa: PLC0415
    from app.workflows.services import enqueue_task  # noqa: PLC0415

    engine = context.engine
    today = business_date(str(getattr(context.settings, "timezone", "") or "UTC"))
    run = resumable_run(engine, today)
    if run is None:
        return {"queued": []}
    if stop_requested(engine) or safe_mode_state(engine).get("active"):
        return {"queued": [], "held": run.id}
    key = resume_task_key(run.id)
    with Session(engine) as session:
        pending = session.scalar(
            select(TaskQueueItem.id)
            .where(
                TaskQueueItem.task_type == DAILY_RUN_TASK,
                TaskQueueItem.status.in_(PENDING_TASK_STATES),
            )
            .limit(1)
        )
        # The resume this start already asked for, whatever became of it: the worker's answer
        # stands (it resumed the day, or said why not) and asking again would only repeat it.
        asked = session.scalar(
            select(TaskQueueItem.id).where(TaskQueueItem.idempotency_key == key).limit(1)
        )
    if pending is not None:
        return {"queued": [], "held": run.id}
    if asked is not None:
        return {"queued": [], "held": run.id, "asked": asked}
    task = enqueue_task(
        engine,
        DAILY_RUN_TASK,
        {
            "resume_of": run.id,
            "date": today,
            "cause": RESUME_CAUSE,
            "stage": run.stopped_at_stage,
        },
        priority=8,
        max_attempts=1,
        idempotency_key=key,
    )
    if task.get("status") not in PENDING_TASK_STATES:
        # Never expected (the key is new to this start); if it ever is, the task is not new.
        return {"queued": [], "held": run.id, "asked": task["id"]}
    with Session(engine) as session, session.begin():
        append_event(
            session,
            DAY_RESUME_QUEUED_EVENT,
            "daily_run",
            run.id,
            1,
            {
                "business_date": today,
                "stage": run.stopped_at_stage,
                "task_id": task["id"],
                "cause": RESUME_CAUSE,
            },
            context.correlation_id,
        )
    return {"queued": [run.id], "task_id": task["id"]}
