"""A film the Director's ladder left waiting is walked again by itself (2026-10-11).

The cyclotron film (aa170155), 14:20:57 UTC: quality control had refused a scene's clip, the
walk put the scene before the Director (`media.scene_rewrite.director_brief`), her brief came
back refused by its schema twice, and the walk stopped WAITING NEEDS_OWNER — the words of a
film waiting for the Owner, though nothing was his to decide. Nothing retried the ladder until
an unrelated take approval at 14:31 queued another continuation, whose brief validated, rewrote
the scene and bought a clip that passed. The Owner: «Nu trebuie să respingă un film, trebuie să
îl refacă până trece QC»; a film is never left waiting for quality, only money stops it.

So this pass finds each film in production (its storyboard APPROVED, not closed) whose newest
walk stopped WAITING on one of the ladder's refusals (`runbook.stages.LADDER_REFUSALS`: the
scenes wait on the sheet or cannot be cut in), whose refused scenes are quality control's to
answer (`media.scene_rewrite.quality_refused`), whose newest brief attempt for those scenes did
not rewrite the scene and is older than `RETRY_MINUTES`, with no continuation queued or at work
and no walk of the film in those minutes, and queues one FILM_CONTINUE
(`app.services.queue_film_continue`, cause `CAUSE`): the walk runs her ladder again — her brief,
his rewrite, the clip bought on the new words under the Owner's rule. Editorial retries have
no daily limit. The cooldown and one pending continuation prevent a busy retry loop.

A brief attempt is her BRIEF_EVENT for the scene, written since 2026-10-11 whether the brief
rewrote the scene or failed (`scene_rewrite._record_brief`). Before that day a failed brief left
no record, only her run of it: a run of `BRIEF_TASK` under one of the film's continuations (the
continuation's task id is the run's correlation) counts as the attempt when no record exists. A
brief being written right now, for whichever film, postpones every retry: its record comes when
it ends. PRODUCTION only (`queue_film_continue` refuses TEST); nothing here buys or decides —
the walk asks for anything paid under his rule, behind his stop, safe mode and his mode.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.workflows.passes import WatchdogContext, watchdog_pass

#: How long after her newest brief attempt (and the film's newest walk) the ladder is retried.
RETRY_MINUTES = 20
#: The continuation's cause: the walk records it on `runbook.film_continued`.
CAUSE = "director_ladder_retry"
#: Where a walk left a film (`runbook.stages`): its status and refusal.
FILM_STATE_EVENT = "runbook.film_state"
#: What counts as the film having been walked.
WALKED_EVENTS = ("runbook.film_continued", FILM_STATE_EVENT)
#: A continuation of the film already queued or at work: it runs the ladder itself.
PENDING_TASK_STATES = ("QUEUED", "RETRYING", "CLAIMED", "RUNNING")


def _when(stamp: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _retry_prefix(storyboard_id: str, day: str) -> str:
    """The idempotency keys of one film's retries of one day share it; the ordinal follows."""
    return f"film-continue-{storyboard_id}-ladder-retry-{day}-"


@watchdog_pass("ladder_retry", order=155, on_error={"queued": []})
def queue_ladder_retries(context: WatchdogContext) -> dict[str, Any]:
    from sqlalchemy import func, select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.agents.models import AgentRun  # noqa: PLC0415
    from app.db import lock_for_write  # noqa: PLC0415
    from app.media.models import Storyboard, StoryboardScene  # noqa: PLC0415
    from app.media.scene_rewrite import BRIEF_EVENT, BRIEF_TASK, quality_refused  # noqa: PLC0415
    from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415
    from app.models import DomainEvent, OwnerPolicy  # noqa: PLC0415
    from app.runbook.stages import LADDER_REFUSALS  # noqa: PLC0415 - runbook imports workflows
    from app.services import FILM_CONTINUE_TASK, queue_film_continue  # noqa: PLC0415
    from app.workflows.models import TaskQueueItem  # noqa: PLC0415

    now = datetime.now(UTC)
    fresh = now - timedelta(minutes=RETRY_MINUTES)
    day = now.date().isoformat()
    owed: list[tuple[str, str]] = []
    with Session(context.engine) as session:
        policy = session.get(OwnerPolicy, 1)
        if str(getattr(policy, "environment", None) or "TEST") != "PRODUCTION":
            return {"queued": []}
        writing = session.scalar(
            select(AgentRun.id)
            .where(AgentRun.task_type == BRIEF_TASK, AgentRun.status == "RUNNING")
            .limit(1)
        )
        if writing is not None:
            return {"queued": []}  # her brief is being written: its record comes when it ends

        # Where each film's newest walk left it.
        stood: dict[str, dict[str, Any]] = {}
        for event in session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == FILM_STATE_EVENT)
            .order_by(DomainEvent.sequence)
        ):
            stood[str(event.aggregate_id)] = dict(event.payload or {})
        busy = {
            str((task.payload or {}).get("storyboard_id") or "")
            for task in session.scalars(
                select(TaskQueueItem).where(
                    TaskQueueItem.task_type == FILM_CONTINUE_TASK,
                    TaskQueueItem.status.in_(PENDING_TASK_STATES),
                )
            )
        }

        def walked_since(storyboard_id: str, moment: datetime) -> bool:
            for event in session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type.in_(WALKED_EVENTS),
                    DomainEvent.aggregate_id == storyboard_id,
                    DomainEvent.timestamp >= moment.isoformat(),
                )
            ):
                when = _when(event.timestamp)
                if when is not None and when > moment:
                    return True
            return False

        def newest_attempt(storyboard_id: str, scenes: list[int]) -> tuple[datetime | None, bool]:
            """When she last tried a brief for one of ``scenes``, and whether it rewrote."""
            attempt: tuple[datetime | None, bool] = (None, False)
            for event in session.scalars(
                select(DomainEvent)
                .where(
                    DomainEvent.event_type == BRIEF_EVENT,
                    DomainEvent.aggregate_id == storyboard_id,
                )
                .order_by(DomainEvent.sequence)
            ):
                payload = dict(event.payload or {})
                if payload.get("scene_index") in scenes:
                    attempt = (_when(event.timestamp), bool(payload.get("rewritten")))
            if attempt[0] is not None:
                return attempt
            # No record: before 2026-10-11 a failed brief left only her run, under the film's
            # continuation (the task id is the run's correlation).
            walks = [
                str(task.id)
                for task in session.scalars(
                    select(TaskQueueItem).where(TaskQueueItem.task_type == FILM_CONTINUE_TASK)
                )
                if str((task.payload or {}).get("storyboard_id") or "") == storyboard_id
            ]
            if not walks:
                return attempt
            started = session.scalar(
                select(func.max(AgentRun.started_at)).where(
                    AgentRun.task_type == BRIEF_TASK, AgentRun.correlation_id.in_(walks)
                )
            )
            return (_when(started) if started else None, False)

        for storyboard_id, state in sorted(stood.items()):
            if state.get("status") != "WAITING" or state.get("refusal") not in LADDER_REFUSALS:
                continue
            if storyboard_id in busy:
                continue
            board = session.get(Storyboard, storyboard_id)
            if (
                board is None
                or board.status != "APPROVED"
                or film_is_closed(session, storyboard_id)
            ):
                continue
            scenes = [
                int(index)
                for index in session.scalars(
                    select(StoryboardScene.scene_index).where(
                        StoryboardScene.storyboard_id == storyboard_id
                    )
                )
            ]
            refused = quality_refused(context.engine, storyboard_id, scenes) if scenes else []
            if not refused:
                continue
            tried_at, rewritten = newest_attempt(storyboard_id, refused)
            if tried_at is None or rewritten or tried_at > fresh:
                continue
            if walked_since(storyboard_id, fresh):
                continue  # a walk ran in these minutes (his stop, his mode...): not again yet
            prefix = _retry_prefix(storyboard_id, day)
            made_today = int(
                session.scalar(
                    select(func.count(TaskQueueItem.id)).where(
                        TaskQueueItem.idempotency_key.like(prefix + "%")
                    )
                )
                or 0
            )
            owed.append((storyboard_id, f"{prefix}{made_today + 1}"))
    if not owed:
        return {"queued": []}
    done: list[str] = []
    with Session(context.engine) as session, session.begin():
        # Written only when something is owed, so a quiet pass takes no write lock.
        lock_for_write(session)
        for storyboard_id, key in owed:
            if queue_film_continue(session, storyboard_id, key=key, payload={"cause": CAUSE}):
                done.append(storyboard_id)
    return {"queued": done}
