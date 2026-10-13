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
(`runbook.services.resume_runners`). One task per interrupted run (the key); a resumed run
cut off again is resumed again, within the day's attempts. Nothing is queued while the studio
stops or shuts down, in safe mode, or while a DAILY_RUN task is queued or at work.
"""

from __future__ import annotations

from typing import Any

from app.workflows.passes import WatchdogContext, watchdog_pass

#: A DAILY_RUN already queued or at work: the day is in hands.
PENDING_TASK_STATES = ("QUEUED", "RETRYING", "CLAIMED", "RUNNING")


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
    with Session(engine) as session:
        pending = session.scalar(
            select(TaskQueueItem.id)
            .where(
                TaskQueueItem.task_type == DAILY_RUN_TASK,
                TaskQueueItem.status.in_(PENDING_TASK_STATES),
            )
            .limit(1)
        )
    if pending is not None:
        return {"queued": [], "held": run.id}
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
        idempotency_key=f"daily-resume-{run.id}",
    )
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
