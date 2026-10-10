"""Films the studio left standing: walked on again, once, by itself (2026-10-10).

Two ways a film stopped with nothing left to ask the Owner:

- His sheet choice that never walked its film. Film babcf272: he chose LOCAL_MOVE for scene 5
  at 08:46 UTC on a studio whose `shooting_sheet.set_scene_model` did not queue FILM_CONTINUE
  yet (it does since the same day), so his choice stayed recorded and the film waited for a
  daily run that was not coming. His newest scene-model choice of the last days that has
  neither its continuation queued (the key `set_scene_model` uses now) nor a walk of the film
  after it gets that continuation, once.
- A render the studio's own code failed. The same film, the same day: its assembly died
  because an interpolation filter crashed in the encoder (scene 3, slowed), and nothing walked
  it again once the fixed code ran. A film whose newest render failed before this studio
  process started, with no render done since and no walk since the start, is walked once
  after each start: a restart usually brings the code that fixes what made it fail (the rule
  the sheet repair keeps, `blocker_repair.STUDIO_STARTED_AT`). The Owner: «studioul trebuie
  să rezolve singur, fără intervenții».

Nothing here buys: the walk asks for anything paid under his rule, behind his stop, safe mode
and his mode; PRODUCTION only (`app.services.queue_film_continue`).
"""

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
#: When this studio process loaded the pass (the first watchdog after the start).
STARTED_AT = datetime.now(UTC)


@watchdog_pass("owner_choice_continuation", order=150, on_error={"queued": []})
def queue_missed_continuations(context: WatchdogContext) -> dict[str, Any]:
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.db import lock_for_write  # noqa: PLC0415
    from app.media.models import VideoRenderJob  # noqa: PLC0415
    from app.media.shooting_sheet import SCENE_MODEL_EVENT, film_is_closed  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415
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
