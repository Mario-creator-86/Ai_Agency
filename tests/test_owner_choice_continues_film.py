"""His free choice on the sheet walks the film on, as his paid yes and his take decisions do.

2026-10-10 (film babcf272): he chose LOCAL_MOVE for scene 5 (held for him after its clip came
out as three stacked panels) at 08:46 UTC, and nothing moved: only an approved paid step and an
approved take queued FILM_CONTINUE, so the film waited for a daily run that was not coming.
Choosing a scene's model (LOCAL_MOVE included) now queues the continuation in the same
transaction. Nothing is bought by the choice: the walk asks for anything paid under his rule.
"""

from __future__ import annotations

from app.media.production_policy import LOCAL_MOVE
from app.media.shooting_sheet import set_scene_model
from app.models import OwnerPolicy
from app.services import FILM_CONTINUE_TASK
from app.workflows.models import TaskQueueItem
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import a_film


def continuations(engine) -> list[TaskQueueItem]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(TaskQueueItem).where(TaskQueueItem.task_type == FILM_CONTINUE_TASK)
            )
        )
        session.expunge_all()
        return rows


def production(engine) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"


def test_his_local_move_choice_queues_the_continuation(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=2)
    production(engine)

    chosen = set_scene_model(engine, storyboard_id, 2, LOCAL_MOVE, issued_by="owner")

    (task,) = continuations(engine)
    assert chosen["continue_task_id"] == task.id
    assert task.payload["storyboard_id"] == storyboard_id
    assert task.payload["cause"] == f"scene_model:2:{LOCAL_MOVE}"
    assert task.status == "QUEUED"


def test_each_choice_is_its_own_continuation_and_test_queues_none(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=2)

    in_test = set_scene_model(engine, storyboard_id, 2, LOCAL_MOVE, issued_by="owner")
    assert in_test["continue_task_id"] is None and continuations(engine) == []

    production(engine)
    set_scene_model(engine, storyboard_id, 2, LOCAL_MOVE, issued_by="owner")
    set_scene_model(engine, storyboard_id, 2, None, issued_by="owner")

    causes = sorted(task.payload["cause"] for task in continuations(engine))
    assert causes == [f"scene_model:2:{LOCAL_MOVE}", "scene_model:2:auto"]
