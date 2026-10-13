"""Owner choice continuation: existing local-first media checks.

Private production traces omitted; implementation unchanged."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.workflows.passes import WatchdogContext, watchdog_pass

#: How far back a choice or a failed render is looked for.
LOOKBACK_DAYS = 7
#: What counts as the film having been walked.
WALKED_EVENTS = ("runbook.film_continued", "runbook.film_state")
#: The event a failed render is recorded under (its payload names the film).
RENDER_FAILED_EVENT = "media.render_failed"
#: Where a walk left a film (`runbook.stages`): its status, refusal and reason.
FILM_STATE_EVENT = "runbook.film_state"
#: The states of a film stopped in production, and the refusals that are not the Owner's yet
#: are not the studio's to walk past either: a story the Director refused goes back to its
#: writer (the sheet's story repair), not to the staircase.
STOPPED_STATES = ("WAITING", "HELD")
NOT_WALKED_PAST = frozenset({"STORY_GATE"})
#: When this studio process loaded the pass (the first watchdog after the start).
STARTED_AT = datetime.now(UTC)


@watchdog_pass("owner_choice_continuation", order=150, on_error={"queued": []})
def queue_missed_continuations(context: WatchdogContext) -> dict[str, Any]:
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.db import lock_for_write  # noqa: PLC0415
    from app.media.models import Storyboard, VideoRenderJob  # noqa: PLC0415
    from app.media.shooting_sheet import SCENE_MODEL_EVENT, film_is_closed  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415
    from app.runbook.stages import OWNER_DECIDES  # noqa: PLC0415 - runbook imports workflows
    from app.services import queue_film_continue  # noqa: PLC0415
    from app.workflows.models import TaskQueueItem  # noqa: PLC0415

    since = (datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    started = STARTED_AT.isoformat()
    owed: list[tuple[str, str, str]] = []
    with Session(context.engine) as session:

        def queued(key: str) -> bool:
            return (
                session.scalar(select(TaskQueueItem.id).where(TaskQueueItem.idempotency_key == key))
                is not None
            )

        def walked_after(storyboard_id: str, moment: str) -> bool:
            return (
                session.scalar(
                    select(DomainEvent.event_id)
                    .where(
                        DomainEvent.event_type.in_(WALKED_EVENTS),
                        DomainEvent.aggregate_id == storyboard_id,
                        DomainEvent.timestamp > moment,
                    )
                    .limit(1)
                )
                is not None
            )

        # His choices that never walked their film.
        newest: dict[str, DomainEvent] = {}
        for event in session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == SCENE_MODEL_EVENT, DomainEvent.timestamp >= since)
            .order_by(DomainEvent.sequence)
        ):
            if (event.payload or {}).get("decided_by") == "owner":
                newest[str(event.aggregate_id)] = event
        for storyboard_id, event in newest.items():
            key = f"film-continue-{storyboard_id}-scene-model-{event.event_id}"
            if queued(key) or walked_after(storyboard_id, str(event.timestamp)):
                continue
            if film_is_closed(session, storyboard_id):
                continue
            payload = event.payload or {}
            scene = payload.get("scene_index")
            cause = f"scene_model:{scene}:{payload.get('model_id') or 'auto'}:missed"
            owed.append((storyboard_id, key, cause))

        # Renders the studio's own code failed before this start.
        failed: dict[str, str] = {}
        for event in session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == RENDER_FAILED_EVENT, DomainEvent.timestamp >= since)
            .order_by(DomainEvent.sequence)
        ):
            film = str((event.payload or {}).get("storyboard_id") or "")
            if film:
                failed[film] = str(event.timestamp)
        for storyboard_id, moment in failed.items():
            if moment >= started or any(film == storyboard_id for film, _, _ in owed):
                continue
            key = f"film-continue-{storyboard_id}-after-start-{started}"
            if queued(key) or walked_after(storyboard_id, started):
                continue
            rendered_since = session.scalar(
                select(VideoRenderJob.id)
                .where(
                    VideoRenderJob.storyboard_id == storyboard_id,
                    VideoRenderJob.status == "COMPLETED",
                    VideoRenderJob.finished_at > moment,
                )
                .limit(1)
            )
            if rendered_since is not None or film_is_closed(session, storyboard_id):
                continue
            owed.append((storyboard_id, key, "render_failed_before_start"))

        # Films a walk left stopped before this start on something of the studio's own.
        stood: dict[str, dict[str, Any]] = {}
        for event in session.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.event_type == FILM_STATE_EVENT,
                DomainEvent.timestamp >= since,
                DomainEvent.timestamp < started,
            )
            .order_by(DomainEvent.sequence)
        ):
            stood[str(event.aggregate_id)] = dict(event.payload or {})
        for storyboard_id, state in stood.items():
            refusal = str(state.get("refusal") or "")
            if state.get("status") not in STOPPED_STATES:
                continue
            if refusal in OWNER_DECIDES or refusal in NOT_WALKED_PAST:
                continue
            if any(film == storyboard_id for film, _, _ in owed):
                continue
            key = f"film-continue-{storyboard_id}-unfinished-after-start-{started}"
            if queued(key) or walked_after(storyboard_id, started):
                continue
            board = session.get(Storyboard, storyboard_id)
            if board is None or board.status != "APPROVED":
                continue  # rendered, closed or gone: nothing of it is unfinished on the sheet
            if film_is_closed(session, storyboard_id):
                continue
            cause = f"unfinished_before_start:{refusal or state.get('status')}"
            owed.append((storyboard_id, key, cause))
    if not owed:
        return {"queued": []}
    done: list[str] = []
    with Session(context.engine) as session, session.begin():
        # Written only when something is owed, so a quiet pass takes no write lock.
        lock_for_write(session)
        for storyboard_id, key, cause in owed:
            if queue_film_continue(session, storyboard_id, key=key, payload={"cause": cause}):
                done.append(storyboard_id)
    return {"queued": done}
