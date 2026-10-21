"""The walk that goes on after a settle under the renders cap is bounded (the dishonest-code
audit of 2026-10-16, SAFE-013).

`_film_staircase` walked a film again, with no bound, whenever its ladder settled a scene under
the cap, while it held the film's purchase lease; a settle that changed nothing (a still whose
file is no longer the one bought, approved again on every pass) turned it for ever. Now a
stop that did not move is not walked twice, and free walks in a row are capped. Faked walk and
ladder: nothing is bought.
"""

from __future__ import annotations

from app.runbook import stages
from test_film_costing import a_film


def test_the_walk_after_a_settle_under_the_cap_is_bounded(engine, settings, tmp_path, monkeypatch):
    board = a_film(engine, tmp_path, scenes=2)
    walks: list[int] = []

    def walk(*args, **kwargs):
        walks.append(1)
        if len(walks) > 50:
            raise RuntimeError("the walk turned on the same stop")
        return {
            "status": "WAITING",
            "step": "motion",
            "refusal": "NEEDS_OWNER",
            "scenes": [1],
            "reason": "x",
            "sheet": {},
            "bought": [],
        }

    def ladder(engine, storyboard_id, film, **kwargs):
        film.setdefault("settled_under_cap", []).append(1)  # «settled», changing nothing
        return []

    monkeypatch.setattr(stages, "_walk_staircase", walk)
    monkeypatch.setattr(stages, "_ladder_scenes", ladder)
    monkeypatch.setattr(stages, "stop_requested", lambda engine: False)
    film = stages._film_staircase(engine, settings, None, board, {}, "PRODUCTION", "c")
    assert len(walks) <= stages.FREE_WALKS + 1
    assert film["free_walks_stopped"] >= 1 and film["status"] == "WAITING"


def test_free_walks_that_settle_new_scenes_each_time_stop_at_the_bound(
    engine, settings, tmp_path, monkeypatch
):
    board = a_film(engine, tmp_path, scenes=2)
    walks: list[int] = []

    def walk(*args, **kwargs):
        walks.append(1)
        if len(walks) > 50:
            raise RuntimeError("the walk never stopped")
        return {"status": "WAITING", "step": "stills", "refusal": "NEEDS_OWNER", "bought": []}

    def ladder(engine, storyboard_id, film, **kwargs):
        film["settled_under_cap"] = [len(walks)]  # a different scene every time
        return []

    monkeypatch.setattr(stages, "_walk_staircase", walk)
    monkeypatch.setattr(stages, "_ladder_scenes", ladder)
    monkeypatch.setattr(stages, "stop_requested", lambda engine: False)
    film = stages._film_staircase(engine, settings, None, board, {}, "PRODUCTION", "c")
    assert len(walks) == stages.FREE_WALKS + 1
    assert film["free_walks_stopped"] == stages.FREE_WALKS + 1
