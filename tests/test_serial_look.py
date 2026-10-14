"""S8, the series look and the shot prompts of the office serial.

Measured before this step (2026-09-24): the serial's visual style was a database label
("CHARACTER_ANIMATION") that never reached the image or video model, so every still was drawn
in the model's default look; the vendor was handed the showrunner's raw scene line with the
bibles appended; and the prompt agent that describes every factual shot never saw a serial
board. Now one versioned style block (config/serial_series_look.json, a proposal the Owner
can change) opens every serial shot prompt, the storyboard's visual bible is that look and is
never re-decided per episode, and the prompt agent writes each shot from the beat through the
same `write_shot_prompts` path the factual films use, with a serial brief.

Every model here is a fake that answers from memory: nothing is sent to a vendor.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.media.models import CharacterBible, Storyboard, StoryboardScene
from app.media.prompt_agent import (
    _TEXT_REQUEST,
    ShotPlanUnusable,
    strip_on_screen_text,
    write_shot_prompts,
)
from app.media.series_look import load_series_look
from app.story.services import decide_episode
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_serial_pipeline import (
    KAEL,
    SARAH,
    YESTERDAY_NOON,
    a_factual_storyboard,
    allow_director_approval,
    beats_for,
    episode_answer,
    fake_director,
    fake_showrunner,
    letters_day,
    written,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def staffed(engine):
    """The staffed studio of the serial tests: workforce, bibles, channels, autonomy on."""
    from app.agents.services import seed_initial_workforce
    from app.media.services import seed_default_character_bibles
    from app.models import OwnerPolicy
    from app.publishing.services import seed_default_channels

    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    return engine


def models():
    return SimpleNamespace(registered_ids=lambda: ["fake-provider"])


def fake_editor(monkeypatch, answer: Any, calls: list | None = None) -> None:
    """The video editor's model: returns ``answer`` (a dict is sent as JSON), records prompts."""
    from app.agents import services

    text = json.dumps(answer) if isinstance(answer, dict) else str(answer)

    def fake_run(_engine, _registry, agent_id, task_type, prompt, *args, **kwargs):
        if calls is not None:
            calls.append({"task": task_type, "prompt": prompt, "template": args[0]})
        return {"id": str(uuid4()), "status": "SUCCEEDED", "output_text": text}

    monkeypatch.setattr(services, "run_agent_task", fake_run)


def serial_board(engine, monkeypatch, beats=None) -> str:
    """An approved episode where Kael speaks first and Sarah answers, as a storyboard."""
    from app.media.serial_storyboard import storyboard_from_episode

    _, ids = letters_day(engine)
    episode = written(engine, monkeypatch, beats or beats_for(ids, [KAEL, SARAH]))
    decide_episode(engine, episode["id"], True, "")
    return storyboard_from_episode(engine, episode["id"], str(uuid4()))


def scenes_of(engine, board_id: str) -> list[StoryboardScene]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board_id)
                .order_by(StoryboardScene.scene_index)
            )
        )


def use_look(monkeypatch, tmp_path: Path, **changes: Any) -> dict:
    """The shipped proposal with ``changes``, written where the loader reads it."""
    from app.media import series_look

    body = json.loads((ROOT / "config" / "serial_series_look.json").read_text(encoding="utf-8"))
    body.update(changes)
    path = tmp_path / "serial_series_look.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(series_look, "SERIES_LOOK_FILE", path)
    return body


#: A shot plan as a model might write it, with a sign asked for in scene 1.
SHOT = {
    "subject": "Kael and Sarah at the render desk",
    "action": "Kael swivels his chair toward Sarah and taps the monitor; a sign reads 'RENDER 91%'",
    "environment": "the render bay, three curved monitors",
    "camera": "medium two-shot, 35mm, slow push-in",
    "lighting": "harsh noon sunlight",
    "composition": "both in the upper half of a vertical frame",
    "motion": "the chair turns, the screens flicker",
    "emotion": "Kael tense, Sarah amused",
    "background": "Elena at her desk behind the glass",
    "continuity": "same seats as the previous shot",
}


#: The plan as the model wrote it for the first episode's scene 4 (f06808c9, 2026-10-11): the
#: camera a path over time, the action a chain of moments; both stills came back as the same
#: picture three times, stacked.
SEQUENCE_SHOT = {
    **SHOT,
    "camera": (
        "Medium close-up on Nadia, a slow tilt down from her face to the ledger and back up "
        "as she speaks, ending on her eyes behind the tortoiseshell glasses"
    ),
    "action": (
        "Nadia taps the brass pen once against the green ledger, pauses before the number, "
        "then lays the pen flat; Sarah leans in a fraction as she asks her question"
    ),
}


def shot_pack(count: int) -> dict:
    return {
        "shots": [
            {"scene_index": index, "story_purpose": "HOOK" if index == 1 else "SETUP", **SHOT}
            for index in range(1, count + 1)
        ]
    }


# ---------------------------------------------------------------------------
# The look itself
# ---------------------------------------------------------------------------


def test_the_shipped_look_is_one_versioned_block_that_asks_for_no_writing():
    look = load_series_look()

    assert look["status"] == "PROPOSED" and look["version"] == 2 and look["in_use"]
    assert look["series_key"] == "office_serial"
    block = look["block"]
    assert block.startswith("Warm hand-drawn 2D animation")
    assert "9:16" in block and "studio house" in block
    assert "No written words, letters or logos anywhere" in block
    # The retry of a degenerate still strips every clause that asks for writing: the look
    # must survive that strip whole, or the retry would be drawn in the model's own style.
    assert strip_on_screen_text(block) == block
    assert _TEXT_REQUEST.search(block) is None
    # Room for the room, the people, the action and the camera under the cap.
    assert len(block) <= look["max_prompt_chars"] // 2
    assert look["max_prompt_chars"] == 980


def test_a_look_switched_off_is_no_look(monkeypatch, tmp_path):
    use_look(monkeypatch, tmp_path, use_until_the_owner_changes_it=False)
    look = load_series_look()
    assert look["in_use"] is False and look["block"] == ""
    assert look["proposed_block"].startswith("Warm hand-drawn 2D animation")


def test_a_missing_look_proposes_nothing(monkeypatch, tmp_path):
    from app.media import series_look

    monkeypatch.setattr(series_look, "SERIES_LOOK_FILE", tmp_path / "missing.json")
    look = load_series_look()
    assert look["status"] == "MISSING" and look["block"] == "" and look["in_use"] is False


# ---------------------------------------------------------------------------
# The storyboard, before any model
# ---------------------------------------------------------------------------


def test_every_serial_shot_opens_with_the_look_and_names_its_room(engine, staffed, monkeypatch):
    block = load_series_look()["block"]
    board_id = serial_board(engine, monkeypatch)

    scenes = scenes_of(engine, board_id)
    assert scenes
    for scene in scenes:
        assert scene.visual_prompt.startswith(block), scene.visual_prompt[:200]
        assert len(scene.visual_prompt) <= 980
        assert "Location: Content, floor 2" in scene.visual_prompt
        assert _TEXT_REQUEST.search(scene.visual_prompt) is None
        # The people in frame, from their bibles, facing the viewer.
        assert "facing the viewer" in scene.visual_prompt
        assert "Kael" in scene.visual_prompt and "Sandy blonde spiky hair" in scene.visual_prompt
        assert (scene.prompt_json or {}).get("series_look_version") == 2
    with Session(engine) as session:
        board = session.get(Storyboard, board_id)
        bible = dict(board.visual_bible_json or {})
    # The look is the series', read from the proposal and never decided by a model.
    assert bible["source"] == "series look"
    assert bible["style"] == block
    assert bible["version"] == 2


def test_the_shot_sizes_vary_from_establishing_to_singles(engine, staffed, monkeypatch):
    board_id = serial_board(engine, monkeypatch)
    scenes = scenes_of(engine, board_id)
    cameras = [(scene.prompt_json or {}).get("camera", "") for scene in scenes]

    assert cameras[0].startswith("Establishing wide shot")
    assert any(c.startswith("Medium two-shot") for c in cameras)
    assert any(c.startswith(("Medium close-up single", "Close-up")) for c in cameras)
    assert len({scene.shot_type for scene in scenes}) >= 3


def test_a_direction_becomes_the_action_and_a_sign_in_the_beat_is_taken_out(
    engine, staffed, monkeypatch
):
    _, ids = letters_day(engine)
    beats = beats_for(ids, [KAEL, SARAH])
    beats[0]["scene"] = "Kael at the render desk. A sticky note reads: 'SHIP IT'."
    beats[0]["lines"][0]["direction"] = "leaning back, arms crossed"
    board_id = serial_board(engine, monkeypatch, beats)

    first = scenes_of(engine, board_id)[0]
    assert "SHIP IT" not in first.visual_prompt
    assert "Kael at the render desk" in first.visual_prompt
    assert "leaning back, arms crossed" in first.visual_prompt
    # What they say is spoken, never drawn.
    assert "number this morning" not in first.visual_prompt


def test_a_look_switched_off_leaves_the_shots_without_a_series_style(
    engine, staffed, monkeypatch, tmp_path
):
    body = use_look(monkeypatch, tmp_path, use_until_the_owner_changes_it=False)
    board_id = serial_board(engine, monkeypatch)
    for scene in scenes_of(engine, board_id):
        assert not scene.visual_prompt.startswith(body["style_block"][:40])
        assert "Location: Content, floor 2" in scene.visual_prompt


# ---------------------------------------------------------------------------
# The prompt agent
# ---------------------------------------------------------------------------


def test_the_prompt_agent_writes_the_serial_shots_with_the_look_and_the_room(
    engine, staffed, monkeypatch
):
    block = load_series_look()["block"]
    board_id = serial_board(engine, monkeypatch)
    count = len(scenes_of(engine, board_id))
    calls: list = []
    fake_editor(monkeypatch, shot_pack(count), calls)

    result = write_shot_prompts(engine, models(), board_id, str(uuid4()))

    # One call: the look is the series', so no visual bible is asked of the model.
    assert [c["task"] for c in calls] == ["shot_prompts"]
    assert calls[0]["template"] == "serial-shot-prompts-v3"
    assert "Do not repeat that description in action" in calls[0]["prompt"]
    prompt = calls[0]["prompt"]
    assert "office serial" in prompt and "facing the viewer" in prompt
    assert block in prompt and "Content, floor 2" in prompt
    assert all(shot["from_model"] for shot in result["shots"])
    for scene in scenes_of(engine, board_id):
        assert scene.visual_prompt.startswith(block)
        assert len(scene.visual_prompt) <= 980
        assert "Location: Content, floor 2" in scene.visual_prompt
        assert "RENDER 91%" not in scene.visual_prompt
        assert _TEXT_REQUEST.search(scene.visual_prompt) is None
        assert "swivels his chair" in scene.visual_prompt
        # The light is the series', not the model's idea of the day.
        assert "noon sunlight" not in scene.visual_prompt
        assert scene.prompt_json["from_model"] is True
        assert scene.prompt_json["series_look_version"] == 2


def test_an_unreadable_answer_leaves_the_shots_the_studio_composed(engine, staffed, monkeypatch):
    block = load_series_look()["block"]
    board_id = serial_board(engine, monkeypatch)
    fake_editor(monkeypatch, "I would rather not.")

    write_shot_prompts(engine, models(), board_id, str(uuid4()))

    for scene in scenes_of(engine, board_id):
        assert scene.visual_prompt.startswith(block)
        assert "Location: Content, floor 2" in scene.visual_prompt
        assert scene.prompt_json["from_model"] is False


def test_a_factual_film_keeps_its_own_look(engine, staffed, monkeypatch):
    block = load_series_look()["block"]
    from app.factual import story_review

    board = a_factual_storyboard(engine)
    # The factual story gate is not what this test is about (test_editorial holds it).
    monkeypatch.setattr(story_review, "story_gate", lambda _session, _script_id: (True, ""))
    calls: list = []
    fake_editor(monkeypatch, "not json", calls)

    # An unreadable plan is asked for once more and then waits as NEEDS_SHOT_PLAN
    # (SHOT_PLAN_PARSE, 2026-09-27); what was composed meanwhile still keeps its own look.
    with pytest.raises(ShotPlanUnusable):
        write_shot_prompts(engine, models(), board["id"], str(uuid4()))

    assert [c["task"] for c in calls] == ["visual_bible", "shot_prompts", "shot_prompts"]
    assert all(block not in c["prompt"] for c in calls)
    for scene in scenes_of(engine, board["id"]):
        assert not scene.visual_prompt.startswith(block[:40])


def test_the_serial_stage_has_the_shots_described_once(engine, staffed, settings, monkeypatch):
    from app.media.serial_storyboard import describe_serial_shots
    from app.story.serial_stage import run_serial_stage

    allow_director_approval(engine)
    _, ids = letters_day(engine, YESTERDAY_NOON())
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, [KAEL, SARAH])))
    fake_director(monkeypatch, "PASS")
    calls: list = []
    fake_editor(monkeypatch, shot_pack(6), calls)

    outcome = run_serial_stage(engine, models(), settings)

    board_id = outcome["artefacts"]["storyboard_id"]
    assert board_id, outcome
    assert [c["task"] for c in calls] == ["shot_prompts"]
    assert outcome["artefacts"]["shots_described"] == 6
    assert all(scene.prompt_json["from_model"] for scene in scenes_of(engine, board_id))
    # Asked again (the media stage asks before it films), the shots are not described twice.
    assert describe_serial_shots(engine, models(), board_id, str(uuid4()))["skipped"] is True
    assert len(calls) == 1


def test_a_new_look_version_has_the_shots_described_again(engine, staffed, monkeypatch, tmp_path):
    from app.media.serial_storyboard import describe_serial_shots

    board_id = serial_board(engine, monkeypatch)
    calls: list = []
    fake_editor(monkeypatch, shot_pack(6), calls)
    describe_serial_shots(engine, models(), board_id, str(uuid4()))
    assert len(calls) == 1

    use_look(monkeypatch, tmp_path, version=3, style_block="Claymation, warm light. Vertical 9:16.")
    describe_serial_shots(engine, models(), board_id, str(uuid4()))

    assert len(calls) == 2
    for scene in scenes_of(engine, board_id):
        assert scene.visual_prompt.startswith("Claymation, warm light. Vertical 9:16.")
        assert scene.prompt_json["series_look_version"] == 3


def test_a_serial_still_is_one_moment_in_a_fixed_frame(engine, staffed, monkeypatch):
    """2026-10-11 (f06808c9): scenes 3, 4 and 7 came back as the same picture three times,
    stacked, on both candidates — their stills described a camera path and a chain of
    moments, which an image model draws as panels; scenes 1 and 2, one moment each, were
    fine. The still now carries the look's fixed framing for the shot's size, how one picture
    fills the tall frame, and the first moment of each person's action; the path's move and
    the whole chain are the motion prompt's."""
    from app.media.prompt_agent import (
        SERIAL_BLANK_SENTENCE,
        SERIAL_FRAME_SENTENCE,
        _still_moment,
    )
    from app.media.prompt_lint import CAMERA_MOVES, _panels_in, _sequence_in
    from app.media.serial_storyboard import describe_serial_shots

    # A chain joined by commas alone is a chain (scene 3 of f06808c9, 2026-10-12): each
    # person's first moment, nothing after the comma that begins the next one.
    chain = (
        "Marcus opens both hands as if starting a pitch, the gesture stalls halfway and dies, "
        "he restarts his sentence with a small head shake; Sarah holds still, then lets one "
        "dry corner of her mouth move as she answers"
    )
    assert _still_moment(chain) == (
        "Marcus opens both hands as if starting a pitch; Sarah holds still"
    )
    assert _still_moment(
        "Nadia taps the brass pen once against the green ledger, pauses before the number, "
        "then lays the pen flat; Sarah leans in a fraction as she asks her question"
    ) == (
        "Nadia taps the brass pen once against the green ledger; "
        "Sarah leans in a fraction as she asks her question"
    )
    # A descriptive tail of the same moment is not a next moment.
    for same in (
        "Kael leaning back, arms crossed, eyes on the monitor",
        "Sarah stands by the window, hands on hips, a brass pen in hand",
    ):
        assert _still_moment(same) == same

    board_id = serial_board(engine, monkeypatch)
    pack = {
        "shots": [
            {"scene_index": index, "story_purpose": "SETUP", **SEQUENCE_SHOT}
            for index in range(1, 7)
        ]
    }
    fake_editor(monkeypatch, pack)
    describe_serial_shots(engine, models(), board_id, str(uuid4()))
    look = load_series_look()
    scenes = scenes_of(engine, board_id)
    assert scenes
    for scene in scenes:
        package = dict(scene.prompt_json or {})
        still = package["still_prompt"]
        assert still == scene.visual_prompt
        # The look's framing for the shot's size, the focus named; never the plan's path.
        before_name = str(look["shot_sizes"][package["shot_size"]]).split("{name}")[0]
        assert before_name.strip() in still, (before_name, still)
        for path in ("tilt down", "back up", "ending on", "as she speaks"):
            assert path not in still, (path, still)
        assert SERIAL_FRAME_SENTENCE in still and SERIAL_BLANK_SENTENCE in still, still
        # The first moment of each person's action, the chain left to the motion — and no
        # «number» for the model to write on the ledger.
        assert "taps the brass pen once against the green ledger" in still
        assert "pauses before the number" not in still and "then lays the pen flat" not in still
        assert "Sarah leans in a fraction as she asks her question" in still
        assert _sequence_in(still) == "" and _panels_in(still) == ""
        # No description cut in the middle of a phrase.
        assert not re.search(r"\b(?:wearing|with|in|and|a)[;.]", still), still
        assert len(still) <= look["max_prompt_chars"]
        motion = package["motion_prompt"]
        assert "then lays the pen flat" in motion
        assert package["camera_move"] in CAMERA_MOVES and package["camera_move"] != "static"
    assert scenes[0].prompt_json["camera_move"] == "tilt down", "the plan's own move, first"


def test_a_characters_description_is_whole_clauses_never_cut_mid_phrase():
    from app.media.prompt_agent import _identity

    marcus = {
        "name": "Marcus",
        "face_hair": "Tousled wavy dark hair; warm brown eyes",
        "outfit": "comfortable royal purple fleece hoodie over grey crew tee, dark jeans",
    }
    assert _identity(marcus, 60) == "Marcus: Tousled wavy dark hair"
    whole = _identity(marcus, 130)
    assert "wearing comfortable royal purple fleece hoodie over grey crew tee" in whole
    assert not whole.endswith(("wearing", "with", "over"))


def test_without_a_model_the_describer_leaves_the_composed_shots(engine, staffed, monkeypatch):
    from app.media.serial_storyboard import describe_serial_shots

    board_id = serial_board(engine, monkeypatch)
    calls: list = []
    fake_editor(monkeypatch, shot_pack(6), calls)

    result = describe_serial_shots(
        engine, SimpleNamespace(registered_ids=list), board_id, str(uuid4())
    )

    assert result["skipped"] is True and calls == []


# ---------------------------------------------------------------------------
# The look beyond the shots
# ---------------------------------------------------------------------------


def test_a_characters_reference_sheet_is_drawn_in_the_series_rendering(engine, staffed):
    from app.media.services import _reference_prompt

    look = load_series_look()
    with Session(engine) as session:
        kael = session.scalar(
            select(CharacterBible).where(CharacterBible.canonical_name.like("Kael%"))
        )
        prompt = _reference_prompt(kael, "portrait")
    assert look["rendering"] in prompt
    assert "Sandy blonde spiky hair" in prompt
    assert _TEXT_REQUEST.search(prompt) is None


def test_the_video_editors_contract_carries_the_serial_shots():
    contracts = json.loads((ROOT / "config" / "role_contracts.json").read_text(encoding="utf-8"))
    editor = contracts["roles"]["VideoEditor"]
    assert any("series look" in line for line in editor["watch_for"])


def test_the_composed_serial_shots_pass_the_prompt_check_and_carry_their_own_movement(
    engine, staffed, monkeypatch
):
    """2026-10-11, the first episode ever approved (f06808c9): every composed still carried
    «Camera:» and «Action:», the sheet's prompt check refused them (TEMPLATE_LABEL) on every
    rewrite, and the Director and the Video Editor went round in circles. The still is now
    said in sentences, and the shot has a motion prompt of its own (the shot's own camera
    move, the beat's action), so the motion step no longer sends the still's words again. The
    same evening a serial given «static» everywhere was BLOCKed SAME_CAMERA_EVERY_SCENE on
    every rewrite: the moves vary from shot to shot, as a factual film's do."""
    from app.media.prompt_agent import motion_prompt_for
    from app.media.prompt_lint import BLOCK, CAMERA_MOVES, LintScene, camera_moves, lint_scene
    from app.media.series_look import series_bible

    board_id = serial_board(engine, monkeypatch)
    bible = series_bible(load_series_look(), "9:16")
    scenes = scenes_of(engine, board_id)
    assert scenes
    moves_seen: list[str] = []
    for scene in scenes:
        package = dict(scene.prompt_json or {})
        still = scene.visual_prompt
        for label in ("Camera:", "Action:", "Avoid:", "Expression:", "Background:"):
            assert label not in still, (label, still)
        assert package["still_prompt"] == still
        motion, _negative = motion_prompt_for(package, "LTX-2.5")
        move = package["camera_move"]
        assert motion and move in CAMERA_MOVES and move != "static"
        assert [found for found, _ in camera_moves(motion)] == [move]
        moves_seen.append(move)
        assert motion.endswith("No subtitles, no on-screen text.")
        findings = lint_scene(
            LintScene(
                scene=scene.scene_index,
                kind="LIVE",
                still_prompt=still,
                motion_prompt=motion,
                model_id="LTX-2.5",
            ),
            bible=bible,
        )
        blocks = [f.as_dict() for f in findings if f.severity == BLOCK]
        assert blocks == [], blocks
