"""His sheet choice that never walked its film: the continuation, queued once (2026-10-10).

Film babcf272: the Owner chose LOCAL_MOVE for scene 5 at 08:46 UTC on a studio whose
`shooting_sheet.set_scene_model` did not queue FILM_CONTINUE yet (it does since the same day),
so his choice stayed recorded and the film waited for a daily run that was not coming. This
pass finds, for each film, his newest scene-model choice of the last days that has neither its
continuation queued (the key `set_scene_model` uses now) nor a walk of the film after it, and
queues that continuation once. It buys nothing: the walk asks for anything paid under his rule,
behind his stop, safe mode and his mode; PRODUCTION only (`app.services.queue_film_continue`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.workflows.passes import WatchdogContext, watchdog_pass

#: How far back a choice is looked for: older ones were walked by a day long since.
LOOKBACK_DAYS = 7
#: What counts as the film having been walked after his choice.
WALKED_EVENTS = ("runbook.film_continued", "runbook.film_state")


@watchdog_pass("owner_choice_continuation", order=150, on_error={"queued": []})
def queue_missed_continuations(context: WatchdogContext) -> dict[str, Any]:
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.db import lock_for_write  # noqa: PLC0415
    from app.media.shooting_sheet import SCENE_MODEL_EVENT, film_is_closed  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415
    from app.services import queue_film_continue  # noqa: PLC0415
    from app.workflows.models import TaskQueueItem  # noqa: PLC0415

    since = (datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    queued: list[str] = []
    with Session(context.engine) as session:
        newest: dict[str, DomainEvent] = {}
        for event in session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == SCENE_MODEL_EVENT, DomainEvent.timestamp >= since)
            .order_by(DomainEvent.sequence)
        ):
            if (event.payload or {}).get("decided_by") == "owner":
                newest[str(event.aggregate_id)] = event
        missed: list[tuple[str, str, str]] = []
        for storyboard_id, event in newest.items():
            key = f"film-continue-{storyboard_id}-scene-model-{event.event_id}"
            if session.scalar(select(TaskQueueItem.id).where(TaskQueueItem.idempotency_key == key)):
                continue
            walked = session.scalar(
                select(DomainEvent.event_id)
                .where(
                    DomainEvent.event_type.in_(WALKED_EVENTS),
                    DomainEvent.aggregate_id == storyboard_id,
                    DomainEvent.timestamp > event.timestamp,
                )
                .limit(1)
            )
            if walked is None and not film_is_closed(session, storyboard_id):
                payload = event.payload or {}
                cause = (
                    f"scene_model:{payload.get('scene_index')}:{payload.get('model_id') or 'auto'}"
                )
                missed.append((storyboard_id, key, cause))
    if not missed:
        return {"queued": queued}
    with Session(context.engine) as session, session.begin():
        # Written only when something is owed, so a quiet pass takes no write lock.
        lock_for_write(session)
        for storyboard_id, key, cause in missed:
            if queue_film_continue(
                session, storyboard_id, key=key, payload={"cause": f"{cause}:missed"}
            ):
                queued.append(storyboard_id)
    return {"queued": queued}
