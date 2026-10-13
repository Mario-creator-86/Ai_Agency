"""Restore retired takes: existing local-first media checks.

Private production traces omitted; implementation unchanged."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.workflows.passes import WatchdogContext, watchdog_pass

#: How far back a redo's retirements are looked for.
LOOKBACK_DAYS = 7


@watchdog_pass(
    "restore_retired_takes", order=140, on_error={"restored": [], "bound_to_picture": []}
)
def give_back_what_redos_left(context: WatchdogContext) -> dict[str, Any]:
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.media.assembler import (  # noqa: PLC0415 - media imports workflows
        TAKE_RESTORED_EVENT,
        TAKE_RETIRED_EVENT,
        give_back_retired_takes,
    )
    from app.media.models import FilmPurchaseLease  # noqa: PLC0415
    from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415

    now = datetime.now(UTC)
    since = (now - timedelta(days=LOOKBACK_DAYS)).isoformat()
    redos: dict[tuple[str, int, str], None] = {}
    with Session(context.engine) as session:
        given_back = {
            str((event.payload or {}).get("retired_event_id"))
            for event in session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == TAKE_RESTORED_EVENT, DomainEvent.timestamp >= since
                )
            )
        }
        for event in session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == TAKE_RETIRED_EVENT, DomainEvent.timestamp >= since)
            .order_by(DomainEvent.sequence)
        ):
            if event.event_id in given_back:
                continue
            payload = event.payload or {}
            storyboard_id = str(payload.get("storyboard_id") or "")
            scene = payload.get("scene_number")
            if not storyboard_id or isinstance(scene, bool) or not isinstance(scene, int):
                continue
            redos[(storyboard_id, scene, str(event.correlation_id))] = None
        if not redos:
            return {"restored": [], "bound_to_picture": []}
        films = sorted({storyboard_id for storyboard_id, _scene, _redo in redos})
        busy = {
            row.storyboard_id
            for row in session.scalars(
                select(FilmPurchaseLease).where(FilmPurchaseLease.storyboard_id.in_(films))
            )
            if str(row.expires_at) > now.isoformat()
        }
        closed = {film for film in films if film_is_closed(session, film)}
    restored: list[str] = []
    bound: list[str] = []
    packages: list[dict[str, Any]] = []
    for storyboard_id, scene, correlation_id in redos:
        if storyboard_id in busy or storyboard_id in closed:
            continue
        returned = give_back_retired_takes(
            context.engine,
            storyboard_id,
            scene,
            correlation_id=correlation_id,
            cause="watchdog",
        )
        restored.extend(returned["restored"])
        bound.extend(returned["bound_to_picture"])
        if returned["restored"] and returned["package"] in ("restored", "exact"):
            # What an older event could not put back stays the rewrite's, named.
            packages.append(
                {
                    "storyboard_id": storyboard_id,
                    "scene_index": scene,
                    "kept_from_rewrite": list(returned["kept_from_rewrite"]),
                }
            )
    return {"restored": restored, "bound_to_picture": bound, "packages": packages}
