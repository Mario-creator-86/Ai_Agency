"""A serial storyboard at the PRODUCTION sheet's shot-plan gate (2026-10-11).

Measured live on 2026-10-11 (storyboard f06808c9, «The Zero Script Club», the serial's first
approved episode): the watchdog pass built the storyboard at 18:26:36 UTC, every scene
composed from the Owner-approved series look (`prompt_json.source == "series_look"`), and the
walk queued for it was refused NEEDS_SHOT_PLAN two seconds later, by the sheet itself
(`shooting_sheet._run_sheet_step`: «Scenele 1, 2, 3, 4, 5, 6, 7, 8 nu au promptul scris de model
din planul de cadre»). The sheet counts its gaps with `prompt_agent.shot_plan_gaps`, the factual
rule (a scene not written by the model is a gap), while the stills stage honours
`assembler.shot_plan_sources`, which accepts the series look for the serial. Three model
rewrites that evening left two scenes with the look's composition, so the gate held every time.
Nothing was bought; the serial had still made no public episode.

What is held here, every provider faked and no network:

- the sources a serial storyboard's scenes may be bought from in PRODUCTION are the model's
  and the series look's (`shot_plan_sources`), a factual film's the model's alone;
- a serial storyboard built the pass's way (no model) and the evening stage's way (the model
  unreachable) reads a PRODUCTION sheet with no shot-plan gap and no lint BLOCK, and a walk
  of it is stopped by neither. Both were measured live the same evening: the sheet's gap
  rule read the factual rule only (fixed: `shot_plan_gaps` reads `shot_plan_sources`), and
  with 8 of 8 shots from the model the repair stayed UNRESOLVED on SAME_CAMERA_EVERY_SCENE,
  because every serial shot was given the movement «static» whatever the model wrote
  (fixed: `prompt_agent._serial_camera_move`, a move of its own per shot).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.agents.services import seed_initial_workforce
from app.media.assembler import (
    SERIAL_SHOT_PLAN_SOURCES,
    SHOT_PLAN_SOURCES,
    shot_plan_sources,
)
from app.media.models import StoryboardScene
from app.media.services import seed_default_character_bibles
from app.media.shooting_sheet import build_sheet
from app.models import OwnerPolicy
from app.publishing.services import seed_default_channels
from app.runbook import stages
from app.story.serial_stage import ready_for_filming
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_serial_continuation import an_approved_episode_with_no_storyboard, production
from test_serial_pipeline import allow_director_approval, todays_episode


@pytest.fixture
def staffed(engine):
    """The staffed studio of the serial tests: workforce, bibles, channels, autonomy on."""
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    return engine


def scene_sources(engine, storyboard_id: str) -> dict[int, str]:
    with Session(engine) as session:
        return {
            int(scene.scene_index): str((scene.prompt_json or {}).get("source") or "")
            for scene in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
            )
        }


def a_pass_built_board(engine, monkeypatch, settings) -> str:
    """The storyboard as `serial_unfilmed` builds it: from the rows, with no model."""
    episode_id = an_approved_episode_with_no_storyboard(engine, monkeypatch, settings)
    board_id, refusal = ready_for_filming(engine, episode_id, str(uuid4()))
    assert board_id and refusal is None, refusal
    return board_id


def an_evening_stage_board(engine, monkeypatch, settings) -> str:
    """The storyboard as the evening's stage builds it: the model asked for the shots and, on
    fakes, unreachable, so the shots keep the look they were composed with."""
    allow_director_approval(engine)
    _, outcome, _, _ = todays_episode(engine, monkeypatch, settings)
    assert outcome["artefacts"]["storyboard_id"], outcome
    return str(outcome["artefacts"]["storyboard_id"])


def the_production_sheet(engine, storyboard_id: str) -> dict:
    sheet = build_sheet(engine, storyboard_id, environment="PRODUCTION")
    # The precondition of the gate: every scene composed from the series look, none by a model.
    assert set(scene_sources(engine, storyboard_id).values()) == {"series_look"}
    return sheet


def test_the_serials_scenes_may_come_from_the_model_or_the_series_look(
    engine, staffed, settings, monkeypatch
):
    board_id = a_pass_built_board(engine, monkeypatch, settings)

    assert shot_plan_sources(engine, board_id) == SERIAL_SHOT_PLAN_SOURCES
    assert "series_look" in SERIAL_SHOT_PLAN_SOURCES and SHOT_PLAN_SOURCES == ("model",)


def test_a_factual_films_scenes_come_from_the_model_alone(engine, tmp_path):
    from test_film_costing import a_film

    storyboard_id = a_film(engine, tmp_path, scenes=2)

    assert shot_plan_sources(engine, storyboard_id) == SHOT_PLAN_SOURCES == ("model",)


def test_a_pass_built_serial_board_has_no_shot_plan_gap_on_the_production_sheet(
    engine, staffed, settings, monkeypatch
):
    board_id = a_pass_built_board(engine, monkeypatch, settings)

    sheet = the_production_sheet(engine, board_id)

    assert sheet["shot_plan_gaps"] == [], sheet["shot_plan_gaps"]


def test_an_evening_stage_serial_board_has_no_shot_plan_gap_on_the_production_sheet(
    engine, staffed, settings, monkeypatch
):
    board_id = an_evening_stage_board(engine, monkeypatch, settings)

    sheet = the_production_sheet(engine, board_id)

    assert sheet["shot_plan_gaps"] == [], sheet["shot_plan_gaps"]


def test_a_serial_boards_camera_language_passes_the_film_lint(
    engine, staffed, settings, monkeypatch
):
    board_id = a_pass_built_board(engine, monkeypatch, settings)

    sheet = the_production_sheet(engine, board_id)

    assert [block["code"] for block in sheet["blocks"]] == [], sheet["lint_summary_ro"]
    assert sheet["lint_blocked"] is False


def test_a_walk_of_the_serial_board_is_not_stopped_by_the_sheets_own_gates(
    engine, staffed, settings, monkeypatch
):
    """The continuation the pass queues, walked on fakes: whatever stops it (his money, a buyer
    at work) is neither the shot plan nor the lint of a film whose scenes the look composed."""
    production(engine)
    board_id = a_pass_built_board(engine, monkeypatch, settings)

    outcome = stages.continue_film(engine, settings, None, None, board_id, cause="test")

    assert outcome["refusal"] not in ("NEEDS_SHOT_PLAN", "LINT_BLOCKED"), outcome
