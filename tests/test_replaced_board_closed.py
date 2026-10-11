"""A board a story repair replaced is closed, so a film has one storyboard (2026-10-11).

The Owner saw two «How NASA Keeps a Space Telescope Alive With Frozen Fuel» in his media list:
«De ce există 2 Storyboard? Trebuie doar 1!». The story repair wrote 6fe6a577 for 223fac3a and
left the old board APPROVED. The repair now closes the board it replaces, and a watchdog pass
closes those it left before; never one with a purchase in flight or a finished render.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.media.models import FilmPurchaseLease, Storyboard, VideoRenderJob
from app.media.sheet_story_repair import (
    retire_replaced,
    retire_replaced_boards,
    save_progress,
)
from app.models import DomainEvent
from app.services import utc_now
from app.workflows.passes import registered_passes
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from test_film_costing import a_film


def replaced_pair(engine: Engine, tmp_path: Path) -> tuple[str, str]:
    (tmp_path / "old").mkdir()
    (tmp_path / "new").mkdir()
    old = a_film(engine, tmp_path / "old", scenes=2)
    new = a_film(engine, tmp_path / "new", scenes=2)
    save_progress(engine, old, {"replacement_storyboard_id": new}, str(uuid4()))
    return old, new


def status(engine: Engine, storyboard_id: str) -> str:
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        assert board is not None
        return str(board.status)


def retirements(engine: Engine, storyboard_id: str) -> list[DomainEvent]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == "runbook.film_retired",
                    DomainEvent.aggregate_id == storyboard_id,
                )
            )
        )


def test_the_board_a_repair_replaced_is_closed_once_and_the_new_one_kept(
    engine: Engine, tmp_path: Path
) -> None:
    old, new = replaced_pair(engine, tmp_path)

    assert retire_replaced_boards(engine, str(uuid4())) == [old]

    assert status(engine, old) == "REJECTED" and status(engine, new) == "APPROVED"
    (event,) = retirements(engine, old)
    assert event.payload["retired_by"] == "Director"
    assert event.payload["replaced_by"] == new
    assert "Înlocuit de storyboardul nou" in event.payload["reason"]
    # Once closed, never again: the pass finds nothing more.
    assert retire_replaced_boards(engine, str(uuid4())) == []
    assert len(retirements(engine, old)) == 1


def test_a_board_with_a_purchase_in_flight_or_a_finished_render_stays(
    engine: Engine, tmp_path: Path
) -> None:
    old, new = replaced_pair(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.add(
            FilmPurchaseLease(
                storyboard_id=old,
                holder="day",
                step="stills",
                acquired_at=utc_now(),
                expires_at=(datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
            )
        )
    assert retire_replaced(engine, old, new, str(uuid4())) is None
    assert status(engine, old) == "APPROVED"

    with Session(engine) as session, session.begin():
        session.delete(session.get(FilmPurchaseLease, old))
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=old,
                status="COMPLETED",
                started_at=utc_now(),
                finished_at=utc_now(),
            )
        )
    assert retire_replaced(engine, old, new, str(uuid4())) is None
    assert status(engine, old) == "APPROVED"


def test_nothing_is_closed_for_a_replacement_that_is_closed_itself(
    engine: Engine, tmp_path: Path
) -> None:
    old, new = replaced_pair(engine, tmp_path)
    with Session(engine) as session, session.begin():
        board = session.get(Storyboard, new)
        assert board is not None
        board.status = "REJECTED"
    assert retire_replaced_boards(engine, str(uuid4())) == []
    assert status(engine, old) == "APPROVED"


def test_the_watchdog_closes_replaced_boards() -> None:
    assert "replaced_boards" in {item.name for item in registered_passes()}
