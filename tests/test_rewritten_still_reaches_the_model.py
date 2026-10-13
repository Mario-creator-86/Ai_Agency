"""The still prompt the Director's ladder rewrote is the one the image model is sent
(2026-10-13, the Owner: «noua imagine ar trebui refăcută cu noul prompt»).

Offline, with faked vendors and scripted agents. After a still-layer rewrite the stills plan
names the new words, the scene is to be bought (not held), and the request handed to the image
vendor begins with them; a scene the gate held for the Owner is bought again, on the ladder's
new words, once her ladder rewrote it. Nothing here proves a live vendor."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.media.models import StoryboardScene
from app.media.prompt_lint import still_motion
from app.media.scene_rewrite import STILL, rewrite_failed_scene
from app.media.stills_stage import stills_plan
from app.media.toolchain import find_ffmpeg
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_clip_qc_wiring import ScriptedCheck
from test_director_rewrites_failed_scene import (  # noqa: F401 - the studio fixture
    BRIEF,
    PLAN,
    STILL_SHOT,
    Agents,
    a_planned_film,
    agents_say,
    refused_twice,
    scene,
    studio,
)
from test_film_costing import approved
from test_fix_is_verified import fix, verdict
from test_stills_stage import (
    FACE,
    NO_FACE,
    SUBJECTS,
    SpyJudge,
    SpyStills,
    a_film,
    approved_run,
    takes,
)

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


def _words(text: str) -> str:
    return " ".join(text.split())


class AnsweringJudge:
    """The vision model, faked: the still is right, and every mistake the words were
    rewritten to correct (`StillPlan.must_fix`) is gone from it."""

    def __init__(self):
        self.looked_at: list[str] = []

    def __call__(self, engine, registry, path, plan, correlation_id, *, ffmpeg_path=None):
        self.looked_at.append(str(path))
        gone = [fix(n, "gone", "the scene as rewritten") for n in range(1, len(plan.must_fix) + 1)]
        return verdict(plan.scene, fixes=gone)


def test_after_a_still_rewrite_the_stills_step_buys_the_new_words(
    engine,
    tmp_path,
    studio,  # noqa: F811 - the fixture imported from test_director_rewrites_failed_scene
):
    storyboard_id = a_planned_film(engine, tmp_path, still_by="still_gate")
    models, account, _spy = refused_twice(engine, storyboard_id, tmp_path)
    first = rewrite_failed_scene(
        engine, agents_say(studio, Agents()), storyboard_id, 1, str(uuid4())
    )
    assert first["rewritten"] is True
    # The movement, rewritten once, fails again: the picture's turn.
    approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=ScriptedCheck("FAILED"),
    )
    before = scene(engine, storyboard_id)
    agents = Agents(brief={**BRIEF, "layer": "still"}, shot=STILL_SHOT)

    outcome = rewrite_failed_scene(
        engine, agents_say(studio, agents), storyboard_id, 1, str(uuid4())
    )

    assert outcome["rewritten"] is True and outcome["layer"] == STILL, outcome
    after = scene(engine, storyboard_id)
    assert after.visual_prompt != before.visual_prompt
    assert "terraced rice fields" in after.visual_prompt.lower()
    plan = stills_plan(engine, storyboard_id)
    (row,) = plan["scenes"]
    assert row["still_prompt"] == _words(after.visual_prompt)
    assert plan["to_buy"] == [1] and plan["held"] == [], (plan["to_buy"], plan["held"], row)

    images = SpyStills(balance=1_000)
    result = approved_run(engine, storyboard_id, tmp_path, images, AnsweringJudge())

    (asked,) = images.asked
    assert asked["prompt"].startswith(_words(after.visual_prompt))
    assert "terraced rice fields" in asked["prompt"].lower()
    assert _words(before.visual_prompt) not in asked["prompt"]
    # And the picture's words carry no movement (2026-10-13).
    assert still_motion(asked["prompt"]) == ""
    entry = next(e for e in result["scenes"] if e["scene_index"] == 1)
    assert entry["status"] == "APPROVED", entry


def _plan_scene(engine, storyboard_id: str, index: int) -> None:
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id,
                StoryboardScene.scene_index == index,
            )
        )
        row.prompt_json = {**dict(row.prompt_json or {}), **PLAN, "scene_index": index}


def _scene(engine, storyboard_id: str, index: int) -> StoryboardScene:
    with Session(engine) as session:
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id,
                StoryboardScene.scene_index == index,
            )
        )
        session.expunge(row)
        return row


def test_a_scene_the_gate_held_is_bought_again_once_her_ladder_rewrote_it(
    engine,
    tmp_path,
    studio,  # noqa: F811 - the fixture imported from test_director_rewrites_failed_scene
):
    storyboard_id = a_film(engine, tmp_path)
    for index in SUBJECTS:
        _plan_scene(engine, storyboard_id, index)

    def faces_in_two(prompt, call):
        return [FACE, FACE] if SUBJECTS[2] in prompt else list(NO_FACE)

    approved_run(engine, storyboard_id, tmp_path, SpyStills(pictures=faces_in_two), SpyJudge())
    plan = stills_plan(engine, storyboard_id)
    assert plan["held"] == [2] and plan["to_buy"] == []
    before = _scene(engine, storyboard_id, 2)
    agents = Agents(brief={**BRIEF, "layer": "still"}, shot={**STILL_SHOT, "scene_index": 2})

    outcome = rewrite_failed_scene(
        engine, agents_say(studio, agents), storyboard_id, 2, str(uuid4())
    )

    assert outcome["rewritten"] is True and outcome["layer"] == STILL, outcome
    after = _scene(engine, storyboard_id, 2)
    assert after.visual_prompt != before.visual_prompt
    plan = stills_plan(engine, storyboard_id)
    (row,) = [entry for entry in plan["scenes"] if entry["scene_index"] == 2]
    assert row["still_prompt"] == _words(after.visual_prompt)
    assert plan["to_buy"] == [2] and plan["held"] == []

    images = SpyStills(balance=1_000)
    result = approved_run(engine, storyboard_id, tmp_path, images, AnsweringJudge())

    (sent,) = [asked["prompt"] for asked in images.asked]
    assert sent.startswith(_words(after.visual_prompt))
    entry = next(e for e in result["scenes"] if e["scene_index"] == 2)
    assert entry["status"] == "APPROVED", entry
    bought = [t for t in takes(engine, storyboard_id) if t.scene_number == 2]
    assert len({t.prompt_hash for t in bought}) == 2, "the new words are a new take identity"
