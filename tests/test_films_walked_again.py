"""Films the studio left standing are walked on again, once, by itself (2026-10-10).

babcf272: his LOCAL_MOVE choice for scene 5 walked nothing (the choice predates the fix in
`set_scene_model`), and once walked, its assembly died on an encoder filter that crashed; the
fixed code ran after a restart and nothing walked the film again. The watchdog pass
`owner_choice_continuation` queues FILM_CONTINUE for both, once, and buys nothing itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.media.production_policy import LOCAL_MOVE
from app.media.shooting_sheet import SCENE_MODEL_EVENT
from app.models import OwnerPolicy
from app.services import FILM_CONTINUE_TASK, append_event
from app.workflows.models import TaskQueueItem
from app.workflows.passes import WatchdogContext
from app.workflows.passes import owner_choice_continuation as walk
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import a_film


def production(engine) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"


def run(engine) -> list[str]:
    return walk.queue_missed_continuations(WatchdogContext(engine, None, str(uuid4())))["queued"]


def continuations(engine) -> list[TaskQueueItem]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(TaskQueueItem).where(TaskQueueItem.task_type == FILM_CONTINUE_TASK)
            )
        )
        session.expunge_all()
        return rows


def event(engine, kind: str, aggregate: str, payload: dict) -> None:
    with Session(engine) as session, session.begin():
        append_event(session, kind, "storyboard", aggregate, 1, payload, str(uuid4()))


def test_his_choice_recorded_before_the_fix_is_walked_once(engine, tmp_path):
    film = a_film(engine, tmp_path, scenes=2)
    production(engine)
    event(
        engine,
        SCENE_MODEL_EVENT,
        film,
        {"scene_index": 2, "model_id": LOCAL_MOVE, "decided_by": "owner", "note": None},
    )

    assert run(engine) == [film]
    assert run(engine) == [], "once"
    (task,) = continuations(engine)
    assert task.payload["cause"] == f"scene_model:2:{LOCAL_MOVE}:missed"


def test_a_choice_already_walked_is_left_alone(engine, tmp_path):
    film = a_film(engine, tmp_path, scenes=2)
    production(engine)
    event(
        engine, SCENE_MODEL_EVENT, film, {"scene_index": 2, "model_id": None, "decided_by": "owner"}
    )
    event(engine, "runbook.film_continued", film, {"status": "SKIPPED", "reason": "x"})

    assert run(engine) == []


def test_a_render_failed_before_this_start_is_walked_once_after_it(engine, tmp_path, monkeypatch):
    film = a_film(engine, tmp_path, scenes=2)
    production(engine)
    event(engine, "media.render_failed", str(uuid4()), {"storyboard_id": film, "reason": "x"})
    event(engine, "runbook.film_continued", film, {"status": "SKIPPED", "reason": "render"})

    # The failure and the walk happened in this process: nothing is owed yet.
    assert run(engine) == []

    # The studio restarted (new code): the failure is from before the start.
    monkeypatch.setattr(walk, "STARTED_AT", datetime.now(UTC) + timedelta(seconds=1))
    assert run(engine) == [film]
    assert run(engine) == [], "once per start"
    (task,) = continuations(engine)
    assert task.payload["cause"] == "render_failed_before_start"


def test_a_render_failed_in_test_queues_nothing(engine, tmp_path, monkeypatch):
    film = a_film(engine, tmp_path, scenes=2)
    event(engine, "media.render_failed", str(uuid4()), {"storyboard_id": film, "reason": "x"})
    monkeypatch.setattr(walk, "STARTED_AT", datetime.now(UTC) + timedelta(seconds=1))

    assert run(engine) == []
    assert continuations(engine) == []
