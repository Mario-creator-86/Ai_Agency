"""A shot the montage cut from a scene is judged as that shot (audit finding 27, 2026-10-16).

The montage cuts a factual writer's scene into up to three storyboard rows, wide, medium and
detail, each tagged ``prompt_json["beat"] = {scene_number, shot, of, size}``. The stills gate
judged every row's still against the writer's line for the WHOLE scene, so a right «detail:
hands on the ledger» of a scene written as «a slow drift through a dark detector cavern» failed
shows_scene and the Director's ladder bought it again. The gate is now given the shot's form
(shot k of n at its size) and the shot's own picture (the Editor's subject and the first moment
of its action) with the shot's own narration fragment; a scene that is its own one shot is
asked exactly as before. Clip QC reads the same picture (`assembler._clip_plan`).

Every provider is faked: the looker is a scripted transport and the still is never decoded.
"""

from __future__ import annotations

import json
import re
from uuid import uuid4

import pytest
from app.agents.models import AgentRun
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media import picture_qc, stills_stage
from app.media.models import StoryboardScene
from app.media.montage import beat_tag
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_picture_qc import (  # noqa: F401 - staffed is a fixture
    a_still_answer,
    give_vision,
    registry_with,
    staffed,
)
from test_stills_stage import NO_FACE
from test_stills_stage import a_film as stills_film

pytestmark = pytest.mark.montage

#: The writer's line for the whole scene the shots were cut from.
CAVERN = (
    "A slow drift through a dark particle-detector cavern, steel rings glinting under work "
    "lights, cables running into the dark."
)
#: The Editor's words for the scene's third shot, a detail.
LEDGER_SUBJECT = "Gloved hands resting on an open paper ledger on a steel desk"
LEDGER_ACTION = "a gloved hand turns one page of the ledger, then the pen lifts from the paper"
LEDGER_WORDS = (
    "Detail shot: gloved hands resting on an open paper ledger on a steel desk, a gloved hand "
    "turning one page. Muted steel blue and amber, fine film grain."
)
#: The detail's part of the scene's narration (`montage.split_words`).
FRAGMENT = "and every collision of that first night was copied out by hand."


def _payload(prompt: str) -> dict:
    found = re.search(
        r'<untrusted_source_evidence hash="the-still">\n(.*)\n</untrusted_source_evidence>',
        prompt,
        re.DOTALL,
    )
    assert found is not None, "the still's data travels inside the inert boundary"
    return json.loads(found.group(1))


def _set_scene(engine, storyboard_id: str, index: int, *, narration: str, **package) -> None:
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id,
                StoryboardScene.scene_index == index,
            )
        )
        row.voiceover_segment = narration
        row.prompt_json = {**dict(row.prompt_json or {}), **package}


def _plan(engine, storyboard_id: str, index: int):
    _bible, scenes = stills_stage._read_scenes(engine, storyboard_id)
    scene = next(scene for scene in scenes if scene.index == index)
    return stills_stage._still_plan(scene, faces_forbidden=True, rules=("No human faces appear",))


def _look(engine, staffed, monkeypatch, plan, scene: int):  # noqa: F811 - the fixture's value
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry, model = registry_with(staffed, lambda p: a_still_answer(scene=scene))
    # The still is never decoded: the look's prompt is what is asserted.
    monkeypatch.setattr(picture_qc, "still_image", lambda *args, **kwargs: "ZmFrZQ==")
    judged = picture_qc.judge_still(engine, registry, NO_FACE[0], plan, str(uuid4()))
    assert judged.status == "MEASURED"
    assert len(model.calls) == 1
    return model.calls[0]["prompt"]


def test_a_detail_shot_is_judged_against_its_own_picture_and_fragment(
    engine,
    staffed,  # noqa: F811 - the fixture
    tmp_path,
    monkeypatch,
):
    storyboard_id = stills_film(engine, tmp_path)
    _set_scene(
        engine,
        storyboard_id,
        3,
        narration=FRAGMENT,
        still_prompt=LEDGER_WORDS,
        writer_visual=CAVERN,
        subject=LEDGER_SUBJECT,
        action=LEDGER_ACTION,
        beat=beat_tag(2, 3, 3, "detail"),
    )

    plan = _plan(engine, storyboard_id, 3)

    # The stills step gives the gate the shot's own picture and form, never the scene's line.
    assert plan.scene_picture == (
        "Gloved hands resting on an open paper ledger on a steel desk. "
        "A gloved hand turns one page of the ledger."
    )
    assert plan.narration == FRAGMENT
    assert plan.shot_form == {"shot": 3, "of": 3, "size": "detail"}

    prompt = _look(engine, staffed, monkeypatch, plan, 3)
    shown = _payload(prompt)
    assert shown["shot"] == {"shot": 3, "of": 3, "size": "detail"}
    assert shown["scene_picture"] == plan.scene_picture
    assert shown["narration"] == FRAGMENT
    assert "cavern" not in prompt.lower()
    # The look is told what the shot is, and how a detail answers shows_scene.
    assert "This still is shot 3 of 3 of the scene below, a detail view" in prompt
    assert "plausible detail view of that scene" in prompt
    assert "against this shot's own narration fragment" in prompt
    # The verdict is attributable to the template that asked it this way.
    assert picture_qc.STILL_TEMPLATE_VERSION != "still-qc-v4"
    with Session(engine) as session:
        versions = [
            run.prompt_template_version
            for run in session.scalars(
                select(AgentRun).where(AgentRun.task_type == picture_qc.STILL_TASK)
            )
        ]
    assert versions == [picture_qc.STILL_TEMPLATE_VERSION]


def test_a_wide_shot_is_told_its_size_without_the_detail_rule(
    engine,
    staffed,  # noqa: F811 - the fixture
    tmp_path,
    monkeypatch,
):
    storyboard_id = stills_film(engine, tmp_path)
    _set_scene(
        engine,
        storyboard_id,
        1,
        narration="Deep under the border, a ring of steel waits in the dark,",
        writer_visual=CAVERN,
        subject="The dark detector cavern, steel rings under work lights",
        action="the work lights hum over the rings",
        beat=beat_tag(2, 1, 3, "wide"),
    )

    plan = _plan(engine, storyboard_id, 1)
    prompt = _look(engine, staffed, monkeypatch, plan, 1)

    assert "This still is shot 1 of 3 of the scene below, a wide view" in prompt
    assert "plausible wide view of that scene" in prompt
    assert "narration fragment" not in prompt
    assert _payload(prompt)["scene_picture"] == (
        "The dark detector cavern, steel rings under work lights. "
        "The work lights hum over the rings."
    )


def test_a_scene_that_is_its_own_one_shot_is_asked_exactly_as_before(
    engine,
    staffed,  # noqa: F811 - the fixture
    tmp_path,
    monkeypatch,
):
    storyboard_id = stills_film(engine, tmp_path)
    _set_scene(
        engine,
        storyboard_id,
        3,
        narration="Scene 3.",
        writer_visual=CAVERN,
        subject=LEDGER_SUBJECT,
        action=LEDGER_ACTION,
    )

    plan = _plan(engine, storyboard_id, 3)
    assert plan.scene_picture == CAVERN  # the writer's line, as before the montage
    assert plan.shot_form is None

    prompt = _look(engine, staffed, monkeypatch, plan, 3)
    # Word for word the prompt of the template before the montage's shots were told apart.
    shown = {
        "scene": 3,
        "plan": plan.still_prompt,
        "scene_picture": CAVERN,
        "narration": "Scene 3.",
        "purpose": plan.purpose,
        "look": plan.look_block,
        "camera_move": plan.camera_move,
        "faces_forbidden": True,
        "bible_rules": ["No human faces appear"],
    }
    assert not plan.must_fix and not plan.expected_markings
    assert prompt == picture_qc._STILL_INSTRUCTIONS.format(scene=3) + wrap_in_inert_boundary(
        json.dumps(shown, ensure_ascii=False), "the-still"
    )


def test_a_montage_shot_form_is_read_only_from_a_factual_beat_tag():
    detail = {"beat": beat_tag(4, 3, 3, "detail"), "subject": "Hands", "action": "hands rest"}
    assert stills_stage.montage_shot(detail) == {"shot": 3, "of": 3, "size": "detail"}
    # One shot of its own, no tag, a size the factual montage never gives: no form.
    assert stills_stage.montage_shot({"beat": beat_tag(4, 1, 1, None)}) is None
    assert stills_stage.montage_shot({}) is None
    assert stills_stage.montage_shot(None) is None
    assert stills_stage.montage_shot({"beat": beat_tag(4, 2, 3, "reaction")}) is None
    # A serial beat already has its own picture (`serial_scene_picture`): no form.
    serial = {
        "beat": beat_tag(4, 2, 3, "detail"),
        "in_frame": [{"name": "Kael Video Editor"}],
        "shot_size": "single",
    }
    assert stills_stage.montage_shot(serial) is None
    # A template plan (the writer's line as subject and action) is said once.
    template = {"beat": beat_tag(1, 2, 3, "medium"), "subject": CAVERN, "action": CAVERN}
    assert stills_stage._scene_picture(template, "", "") == CAVERN


def test_the_clip_plan_of_a_detail_shot_reads_its_own_picture():
    from app.media.assembler import _clip_plan

    package = {
        "still_prompt": LEDGER_WORDS,
        "writer_visual": CAVERN,
        "subject": LEDGER_SUBJECT,
        "action": LEDGER_ACTION,
        "beat": beat_tag(2, 3, 3, "detail"),
    }
    plan = _clip_plan(
        {
            "scene_index": 3,
            "prompt_json": package,
            "visual_prompt": LEDGER_WORDS,
            "voiceover_segment": FRAGMENT,
        },
        {},
    )
    assert "cavern" not in plan.scene_picture.lower()
    assert plan.scene_picture.startswith("Gloved hands resting on an open paper ledger")
    assert plan.narration == FRAGMENT
    # Without the tag, the clip reads the writer's line as before.
    alone = _clip_plan(
        {
            "scene_index": 3,
            "prompt_json": {key: value for key, value in package.items() if key != "beat"},
            "visual_prompt": LEDGER_WORDS,
            "voiceover_segment": FRAGMENT,
        },
        {},
    )
    assert alone.scene_picture == CAVERN
