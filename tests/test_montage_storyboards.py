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


#: A writer's short scene: one shot of its own (11 words, under a second shot's six).
SHORTS = [
    ("SETUP", "The registry reserved the address itself, and the reservation still stands."),
    ("DEVELOPMENT", "Nobody at the registry may sell it, not even to a friend."),
    ("REVEAL", "The reservation was written down before the first web page went live."),
    ("PAYOFF", "So the one address everybody wants is the one nobody will ever own."),
]


def test_a_factual_shot_after_a_cut_scene_reads_its_own_writers_scene(engine):
    """A writer's scene of one shot carries no tag, and its row number is no longer its
    writer's number once a scene before it was cut: row 4 is the writer's scene 2, never 4."""
    from app.media.prompt_agent import _film_facts
    from app.media.second_look import scene_intent
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
        }
    ] + [
        {
            "scene_number": number,
            "purpose": purpose,
            "narration": narration,
            "visual_description": f"Writer's picture {number}: a ledger on a wooden desk.",
            "claim_ids": ["c2"],
        }
        for number, (purpose, narration) in enumerate(SHORTS, start=2)
    ]
    script_id = a_script(engine, topic_id, scenes=scenes, story=GOOD_STORY)
    a_passed_review(engine, script_id)
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    write_shot_prompts(engine, None, board["id"], str(uuid4()))
    rows = _rows(engine, board["id"])
    # The first scene is three shots, every other one shot: rows 4-7 are the writer's 2-5.
    writer_of = {1: 1, 2: 1, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5}
    assert [row.scene_index for row in rows] == list(writer_of)
    with Session(engine) as session:
        facts = _film_facts(session, session.get(Storyboard, board["id"]))
        intents = {
            row.scene_index: scene_intent(session, board["id"], row.scene_index) for row in rows
        }
    by_index = {scene["scene_index"]: scene for scene in facts["scenes"]}
    for row in rows:
        own = scenes[writer_of[row.scene_index] - 1]
        assert by_index[row.scene_index]["writer_visual"] == own["visual_description"]
        assert by_index[row.scene_index]["story_purpose"] == own["purpose"]
        assert row.prompt_json["writer_visual"] == own["visual_description"], row.scene_index
        assert row.prompt_json["story_purpose"] == own["purpose"], row.scene_index
        assert intents[row.scene_index]["scene_picture"] == own["visual_description"]
        assert intents[row.scene_index]["purpose"] == own["purpose"]


#: A word of its own in each beat's first line, so every beat says something no other does.
BEAT_WORDS = ("window", "ledger", "queue", "render", "budget", "deadline")


def _serial_board(engine, monkeypatch) -> tuple[str, list[StoryboardScene], list[dict]]:
    """A six-beat episode cut into shots: its board, its rows and its script's entries."""
    _, ids = letters_day(engine)
    beats = beats_for(ids, [KAEL, SARAH])
    for beat, word in zip(beats, BEAT_WORDS, strict=True):
        beat["lines"][0]["text"] = f"Right, where are we with the {word} this morning, everyone?"
    episode = written(engine, monkeypatch, beats)
    decide_episode(engine, episode["id"], True, "")
    board_id = storyboard_from_episode(engine, episode["id"], str(uuid4()))
    rows = _rows(engine, board_id)
    with Session(engine) as session:
        board = session.get(Storyboard, board_id)
        entries = list(session.get(ScriptDraft, board.script_draft_id).scenes_json)
    assert len(rows) == len(entries) > len(beats)
    # Every shot is tagged with its beat (two speakers a beat, the first beat established),
    # and beats 2-6 are the shots the beat's number misread.
    assert all(beat_of(row.prompt_json) for row in rows)
    assert {beat_of(row.prompt_json)["scene_number"] for row in rows} == {1, 2, 3, 4, 5, 6}
    for row in rows:
        entry = entries[row.scene_index - 1]
        assert entry["scene_index"] == row.scene_index
        # The entry is the shot's own beat's (`beats_for` numbers each beat's scene line).
        assert f"scene {beat_of(row.prompt_json)['scene_number']}:" in entry["visual_description"]
    return board_id, rows, entries


def test_every_serial_shot_is_composed_from_its_own_script_entry(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
    monkeypatch,
):
    """The serial's script keeps one entry per shot (the speakers, voices and lines are the
    shot's own); a shot of beat 2 or later is composed from that entry, never from the entry
    at its beat's number, which is a shot of an earlier beat."""
    from app.media.prompt_agent import _film_facts, strip_on_screen_text
    from app.media.scene_rewrite import scene_context

    board_id, rows, entries = _serial_board(engine, monkeypatch)
    with Session(engine) as session:
        facts = _film_facts(session, session.get(Storyboard, board_id))
    by_index = {scene["scene_index"]: scene for scene in facts["scenes"]}
    for row in rows:
        entry = entries[row.scene_index - 1]
        own = entry["visual_description"]
        assert by_index[row.scene_index]["writer_visual"] == own, row.scene_index
        assert by_index[row.scene_index]["part"] == entry["part"], row.scene_index
        assert row.prompt_json["writer_visual"] == own, row.scene_index
        # Without a model the subject and the action are the shot's own beat's line.
        assert row.prompt_json["subject"] == strip_on_screen_text(own), row.scene_index
        assert row.prompt_json["action"].startswith(strip_on_screen_text(own)), row.scene_index
        # A rewrite of the shot reads the same line (`scene_rewrite` through `_film_facts`).
        context = scene_context(engine, board_id, row.scene_index)
        assert context is not None and context["scene"]["writer_visual"] == own, row.scene_index


def test_the_second_look_reads_every_serial_shots_own_script_entry(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
    monkeypatch,
):
    """The Director judges each shot's still beside its own entry's scene line, part and
    lines, never another shot's."""
    from app.media.second_look import scene_intent

    board_id, rows, entries = _serial_board(engine, monkeypatch)
    with Session(engine) as session:
        intents = {
            row.scene_index: scene_intent(session, board_id, row.scene_index) for row in rows
        }
    for row in rows:
        entry = entries[row.scene_index - 1]
        intent = intents[row.scene_index]
        assert intent["scene_picture"] == entry["visual_description"], row.scene_index
        assert intent["beat"]["part"] == entry["part"], row.scene_index
        assert (
            intent["beat"]["lines"]
            == [{"speaker": line["speaker"], "text": line["text"]} for line in entry["lines"]][:6]
        ), row.scene_index


def test_a_row_reads_its_own_entry_by_the_grain_its_script_keeps():
    """The serial's entry is the shot's own, checked against the entry's own number; the
    factual entry is the writer's scene, an untagged row the scene after the row before."""
    from app.media.script_entries import row_entries

    rows = [
        (1, {"beat": {"scene_number": 1, "shot": 1, "of": 2}}),
        (2, {"beat": {"scene_number": 1, "shot": 2, "of": 2}}),
        (3, None),
        (4, {"still_prompt": "a package with no tag"}),
    ]
    shots = [
        {"scene_index": 2, "visual_description": "shot two"},
        {"scene_index": 1, "visual_description": "shot one"},
        {"visual_description": "shot three"},
    ]
    serial = row_entries(shots, rows, serial=True)
    # An entry that names another shot is never read for this one: the one that names it is.
    assert serial[1]["visual_description"] == "shot one"
    assert serial[2]["visual_description"] == "shot two"
    assert serial[3]["visual_description"] == "shot three"  # no number stored: its place
    assert serial[4] == {}  # no entry of its own, never a neighbour's

    writer = [{"visual_description": name} for name in ("A", "B", "C")]
    factual = row_entries(writer, rows, serial=False)
    assert [factual[index].get("visual_description") for index in (1, 2, 3, 4)] == [
        "A",
        "A",
        "B",
        "C",
    ]
    # A board the montage never cut is read row for row, as before.
    uncut = row_entries(writer, [(1, None), (2, None), (3, None)], serial=False)
    assert [uncut[index]["visual_description"] for index in (1, 2, 3)] == ["A", "B", "C"]
