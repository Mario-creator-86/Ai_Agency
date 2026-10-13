"""The motion prompt the Director's ladder rewrote is the one the video model is sent, on the
test-shot step and on the motion step (2026-10-13, the Owner: «la fel și la video, aceeași
logică; promptul trebuie schimbat»).

Offline, with faked vendors and scripted agents: after a motion-layer rewrite the hold on the
refused scene is lifted and the request handed to the video vendor is exactly the rendering of
the rewritten package (`prompt_agent.motion_prompt_for`), never the old words."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.media.assembler import MOTION_HOLD_EVENT, decide_take, motion_plan
from app.media.models import SceneTake, StoryboardScene
from app.media.prompt_agent import motion_prompt_for
from app.media.scene_rewrite import MOTION, rewrite_failed_scene
from app.media.toolchain import find_ffmpeg
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_clip_qc_wiring import ScriptedCheck, events, shots
from test_director_rewrites_failed_scene import (  # noqa: F401 - the studio fixture
    PLAN,
    SHOT,
    Agents,
    a_planned_film,
    agents_say,
    refused_twice,
    scene,
    studio,
)
from test_film_costing import SEEDANCE, Account, Models, SpyVideo, a_film, approved

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


def test_the_test_shot_is_bought_on_the_rewritten_motion_prompt(
    engine,
    tmp_path,
    studio,  # noqa: F811 - the fixture imported from test_director_rewrites_failed_scene
):
    storyboard_id = a_planned_film(engine, tmp_path)
    models, account, spy = refused_twice(engine, storyboard_id, tmp_path)
    before = scene(engine, storyboard_id)

    outcome = rewrite_failed_scene(
        engine, agents_say(studio, Agents()), storyboard_id, 1, str(uuid4())
    )

    assert outcome["rewritten"] is True and outcome["layer"] == MOTION, outcome
    after = scene(engine, storyboard_id)
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])["steps"]["test_shot"]
    assert plan["held"] == [] and plan["to_buy"] == [1]
    summary = approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=ScriptedCheck("PASSED"),
    )
    (entry,) = summary["scenes"]
    assert entry["status"] == "PAID"
    expected, _negative = motion_prompt_for(after.prompt_json, "seedance2_5", None)
    old, _negative = motion_prompt_for(before.prompt_json, "seedance2_5", None)
    assert spy.asked[0]["prompt"] == old
    assert spy.asked[-1]["prompt"] == expected
    assert "from left to right" in expected and "from left to right" not in old


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


def test_the_motion_step_is_bought_on_the_rewritten_motion_prompt(
    engine,
    tmp_path,
    studio,  # noqa: F811 - the fixture imported from test_director_rewrites_failed_scene
):
    storyboard_id = a_film(engine, tmp_path, scenes=2)
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        ):
            row.prompt_json = {**dict(row.prompt_json or {}), **PLAN}
        for take in session.scalars(
            select(SceneTake).where(SceneTake.storyboard_id == storyboard_id)
        ):
            take.approved_by = "owner"
    account = Account(10_000)
    spy = SpyVideo("seedance2_5", account)
    models = Models(spy)
    # The hero (scene 1) passes and the Owner approves it.
    approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=ScriptedCheck("PASSED"),
    )
    (hero,) = [t for t in shots(engine, storyboard_id) if t.status == "PAID"]
    decide_take(engine, hero.id, "APPROVED", decided_by="owner")
    # The motion step: scene 2's clip fails clip QC, and its retry too — the scene is held.
    approved(
        engine,
        storyboard_id,
        tmp_path,
        "motion",
        models,
        account,
        clip_check=ScriptedCheck("FAILED"),
    )
    assert {t.status for t in shots(engine, storyboard_id) if t.scene_number == 2} == {"REJECTED"}
    held = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])["steps"]["motion"]
    assert held["held"] == [2] and held["to_buy"] == [], held
    assert [
        e.payload["scene_number"] for e in events(engine, MOTION_HOLD_EVENT, storyboard_id)
    ] == [2]
    posts_before = models.posts()
    old_sent = spy.asked[-1]["prompt"]
    before = _scene(engine, storyboard_id, 2)

    outcome = rewrite_failed_scene(
        engine,
        agents_say(studio, Agents(shot={**SHOT, "scene_index": 2})),
        storyboard_id,
        2,
        str(uuid4()),
    )

    assert outcome["rewritten"] is True and outcome["layer"] == MOTION, outcome
    after = _scene(engine, storyboard_id, 2)
    assert after.prompt_json["camera_move"] == "slow pan right"
    assert after.prompt_json["motion_intent"] != before.prompt_json["motion_intent"]
    lifted = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])["steps"]["motion"]
    assert lifted["held"] == [] and lifted["to_buy"] == [2], lifted

    summary = approved(
        engine,
        storyboard_id,
        tmp_path,
        "motion",
        models,
        account,
        clip_check=ScriptedCheck("PASSED"),
    )

    assert models.posts() == posts_before + 1
    by_scene = {e["scene_index"]: e for e in summary["scenes"]}
    assert by_scene[2]["status"] == "PAID", by_scene
    expected, _negative = motion_prompt_for(after.prompt_json, "seedance2_5", None)
    sent = spy.asked[-1]["prompt"]
    assert sent == expected and sent != old_sent
    assert "from left to right" in sent and "from left to right" not in old_sent
