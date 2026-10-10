"""Takes a redo retired and then delivered nothing for, given back once (2026-10-10).

Film babcf272, «The Particle That Shouldn't Exist (But Does)»: the day's QC repair
(`runbook.stages._apply_repairs`) redid scenes 1 and 2 unasked. In the transaction that spent
the yes it retired the Owner's own approved takes (scene 1: still 76e59c5c REDO.OWNER and clip
405e87d8 REDO.STILL_REPLACED; scene 2: still 50fe4807 and his test shot 3685dd5b; each
``media.scene_take_retired`` event says ``previous_status`` APPROVED) and rewrote both
scenes' words (``media.prompts_rewritten``); then the GPU was forced off, every new candidate
ended REFUSED, and both scenes were left with nothing to assemble.

A redo that delivers nothing now gives back what it retired itself (`redo_scene`, through
`assembler.give_back_retired_takes`). This pass does the same for the redos that ended before
that code ran, or that died before they could (a killed process): each redo's retirements of
one scene (its correlation id) of the last days, not given back yet, are handed to
`give_back_retired_takes`, which gives them back only when nothing was delivered for the scene
since the retirement, never a take the Owner turned down himself, with the scene's words put
back when the redo had rewritten them. Once given back a retirement is never looked at again
(its ``media.scene_take_restored`` names it), so the pass is idempotent.

"Delivered" is read from the takes' history, not from what they are now (review 2026-10-10):
a take made since that came with its file counts whatever became of it. A redo that delivered
a still the gate, the clip QC or the Owner later turned down did deliver, so the takes it
retired (his own «Refă» included, ``owner_press`` on their events) never come back days later;
only REFUSED, LOST or never-sent takes leave a redo with nothing.

A film whose purchase lease is held is left alone (a redo may be retiring and buying right
now and gives back itself), and so is a film that is closed. Nothing here buys, asks the Owner
or decides in his name: it writes take statuses and a scene's words back, and their events.
"""

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
