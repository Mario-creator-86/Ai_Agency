"""Hold new production while approved films still owe repair or publication."""

from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.media.models import Storyboard


def new_production_wait(engine: Engine, settings: Any) -> dict[str, Any] | None:
    if not getattr(settings, "finish_existing_films_first", True):
        return None
    from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415

    with Session(engine) as session:
        boards = session.scalars(
            select(Storyboard)
            .where(Storyboard.status.in_(("APPROVED", "RENDERED", "NEEDS_SHOT_PLAN", "REJECTED")))
            .order_by(Storyboard.created_at)
        ).all()
        unfinished = [b for b in boards if not film_is_closed(session, b.id)]
        if not unfinished:
            return None
        return {
            "status": "SKIPPED",
            "reason": (
                "Întâi reparăm și publicăm filmele existente; producția nouă așteaptă: "
                + "; ".join(str(b.title) for b in unfinished)
                + "."
            ),
            "artefacts": {"unfinished_storyboards": [b.id for b in unfinished]},
        }
