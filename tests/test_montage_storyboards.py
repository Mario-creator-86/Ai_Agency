"""The montage in the storyboards (the Owner, 2026-10-16): a writer's scene becomes several
ordinary scenes of the storyboard, tagged with the beat they came from; the serial cuts with
its dialogue and shows the listener while the words go on."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.factual.models import ScriptDraft
from app.media.models import CharacterBible, Storyboard, StoryboardScene
from app.media.montage import beat_of
from app.media.prompt_agent import SERIAL_LIFE_SENTENCE, SERIAL_LISTEN_TAIL, write_shot_prompts
from app.media.serial_storyboard import storyboard_from_episode
from app.media.services import generate_storyboard_from_script
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_editorial_quality import GOOD_STORY, a_passed_review, a_script, a_topic
from test_serial_pipeline import (  # noqa: F401 - staffed is a fixture
    KAEL,
    SARAH,
    beats_for,
    decide_episode,
    letters_day,
    staffed,
    written,
)

pytestmark = pytest.mark.montage

LONG = (
    "There is one web address on earth that nobody is allowed to buy, and every registrar "
    "refuses it the moment you type it in. The address was reserved long before the web "
    "grew up, set aside by the registry itself, and that old reservation still holds: the "
    "address cannot be registered by anyone, however much they offer."
)
SHORT = "The registry reserved the address itself, and the reservation still stands."


def _rows(engine, board_id: str) -> list[StoryboardScene]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board_id)
                .order_by(StoryboardScene.scene_index)
            )
        )


def test_a_factual_scene_becomes_three_shots_that_read_the_writers_scene(engine):
    from app.models import OwnerPolicy

    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        if policy:
            policy.autonomy_stopped = False
    topic_id = a_topic(engine)
    scenes = [
        {
            "scene_number": 1,
            "purpose": "HOOK",
            "narration": LONG,
            "visual_description": "A brass cyclotron the size of a hand on a wooden bench.",
            "claim_ids": ["c1"],
        },
        {
            "scene_number": 2,
            "purpose": "SETUP",
            "narration": SHORT,
            "visual_description": "A notebook page of figures under a desk lamp.",
            "claim_ids": ["c2"],
        },
    ]
    script_id = a_script(engine, topic_id, scenes=scenes, story=GOOD_STORY)
    a_passed_review(engine, script_id)

    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    rows = _rows(engine, board["id"])

    assert [row.scene_index for row in rows] == [1, 2, 3, 4]
    assert board["total_scenes"] == 4 if "total_scenes" in board else True
    tags = [beat_of(row.prompt_json) for row in rows]
    assert [(t.get("scene_number"), t.get("shot"), t.get("of")) for t in tags[:3]] == [
        (1, 1, 3),
        (1, 2, 3),
        (1, 3, 3),
    ]
    assert [t.get("size") for t in tags[:3]] == ["wide", "medium", "detail"]
    assert [row.shot_type for row in rows[:3]] == ["WIDE", "MEDIUM", "DETAIL"]
    # The writer's words once, in order, cut on clause ends; the short scene is one shot.
    assert " ".join(row.voiceover_segment for row in rows[:3]) == LONG
    assert tags[3] == {} and rows[3].voiceover_segment == SHORT
    assert all(row.claim_ids_json == ["c1"] for row in rows[:3])
    assert all(3.0 <= row.duration_seconds <= 9.0 for row in rows)
    with Session(engine) as session:
        script = session.get(ScriptDraft, script_id)
        assert len(script.scenes_json) == 2  # the fact-checked script is never rewritten
        assert session.get(Storyboard, board["id"]).total_scenes == 4

    # The shot plan (no model: the template) keeps the tag and reads the writer's scene.
    write_shot_prompts(engine, None, board["id"], str(uuid4()))
    rows = _rows(engine, board["id"])
    for row in rows[:3]:
        assert row.prompt_json["beat"]["scene_number"] == 1
        assert row.prompt_json["writer_visual"] == scenes[0]["visual_description"]
        assert row.prompt_json["story_purpose"] == "HOOK"
    assert rows[3].prompt_json["writer_visual"] == scenes[1]["visual_description"]
    assert rows[3].prompt_json["beat"] is None


def test_a_serial_beat_cuts_with_its_dialogue_and_shows_the_listener(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
    monkeypatch,
):
    _, ids = letters_day(engine)
    beats = beats_for(ids, [KAEL, SARAH])
    beats[1]["lines"][0]["text"] = (
        "The render is late because the stills came back dark, every one of them, and I "
        "sent them again at six with the lamps turned up, so the bay will be busy until "
        "noon and nobody should touch the queue before I say so."
    )
    beats[1]["lines"][0]["direction"] = "firmly"
    episode = written(engine, monkeypatch, beats)
    decide_episode(engine, episode["id"], True, "")

    board_id = storyboard_from_episode(engine, episode["id"], str(uuid4()))
    rows = _rows(engine, board_id)

    assert len(rows) > len(beats)
    assert beat_of(rows[0].prompt_json).get("size") == "establishing"
    reactions = [row for row in rows if row.shot_type == "CLOSEUP_REACTION"]
    assert reactions, [row.shot_type for row in rows]
    reaction = reactions[0]
    tag = beat_of(reaction.prompt_json)
    assert tag["scene_number"] == 2 and tag["size"] == "reaction" and tag["on"] == SARAH
    # Kael's words go on, heard from beside the frame; the picture is Sarah's.
    assert "nobody should touch the queue" in reaction.voiceover_segment
    with Session(engine) as session:
        sarah = session.scalar(
            select(CharacterBible).where(CharacterBible.canonical_name.like("Sarah%"))
        )
        board = session.get(Storyboard, board_id)
        script = session.get(ScriptDraft, board.script_draft_id)
        assert reaction.character_ids_json[0] == sarah.id
        entry = script.scenes_json[reaction.scene_index - 1]
        assert all(line["speaker"] == KAEL for line in entry["lines"])
        assert all(line["direction"] == "firmly" for line in entry["lines"])
        assert entry["beat"]["on"] == SARAH
        assert board.total_scenes == len(rows)
    # Composed without a model: the listener's sentence in the still and the clip, and the
    # speakers' life sentence left to the shots where someone speaks.
    package = reaction.prompt_json
    assert package["beat"] == tag
    assert SERIAL_LISTEN_TAIL in package["still_prompt"]
    assert SERIAL_LISTEN_TAIL in package["motion_prompt"]
    assert SERIAL_LIFE_SENTENCE not in package["motion_prompt"]
    single = next(row for row in rows if beat_of(row.prompt_json).get("size") == "single")
    assert SERIAL_LISTEN_TAIL not in single.prompt_json["still_prompt"]
