"""«Pauza vocii», stage 2: every cut classed and its pause frozen on the storyboard's rows when
the storyboard is built (the Owner, 2026-10-16).

The montage cuts the picture inside one voice take (the writer's scene, the speaker's run), and
the cut adds nothing: the class is IN_TAKE. Between two takes the join's class comes from the
punctuation, the story's purpose, the speakers and the writer's marks; its seconds from each
voice's own measured pauses; and it is frozen on the row's beat tag, beside the montage's tag,
never shown to a model. Nothing here calls a model, a vendor or the network.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.media import montage, pause_plan, pauses
from app.media.models import StoryboardScene
from app.media.montage import keep_frozen, shot_tag
from app.media.speaker_voices import line_runs, speaker_segments
from app.story.lines import clean_line, split_direction, split_direction_places
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_serial_pipeline import staffed  # noqa: F401 - the fixture


@pytest.fixture
def rules() -> pauses.PauseRules:
    return pauses.load_rules()


def _rows(engine, board_id: str) -> list[StoryboardScene]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board_id)
                .order_by(StoryboardScene.scene_index)
            )
        )


# ------------------------------------------------------------------------------ the lines


def test_a_direction_says_where_it_stood_among_the_words():
    said = "(beat) I told you (pause) it's gone (sighs)"
    spoken, directions, places = split_direction_places(said)
    assert spoken == "I told you it's gone"
    assert directions == "beat; pause; sighs"
    assert [p["at"] for p in places] == ["start", 3, "end"]
    # The old reading is unchanged.
    assert split_direction(said) == (spoken, directions)


def test_a_stored_line_keeps_where_its_beat_stood_and_nothing_for_another_note():
    assert clean_line("Kael", "I told you (beat) it is gone.", "", None)["pause_at"] == 3
    assert clean_line("Kael", "(beat) It is gone.", "", None)["pause_at"] == "start"
    assert clean_line("Kael", "It is gone. (long pause)", "", None)["pause_at"] == "end"
    sighed = clean_line("Kael", "(sighs) It is gone.", "", None)
    assert "pause_at" not in sighed and sighed["direction"] == "sighs"


# ---------------------------------------------------------------------------- the montage


def test_a_cut_inside_a_scene_says_its_class_and_the_ellipsis_is_a_full_stop():
    words = (
        "The probe slept for nine years in the cold dark between the planets… then the "
        "signal came back, faint, at four in the morning, and nobody in the room said a word."
    )
    cut = montage.split_words_classed(words, 2)
    assert [after for _f, after in cut] == ["SENTENCE", None]
    assert cut[0][0].endswith("planets…")
    assert montage.split_words(words, 2) == [fragment for fragment, _ in cut]


def test_factual_shots_carry_the_class_of_the_cut_after_them():
    class _Settings:
        montage_enabled = True
        montage_shot_seconds = 4.0
        montage_max_shots_per_scene = 3

    long = (
        "There is one web address on earth that nobody is allowed to buy, and every registrar "
        "refuses it the moment you type it in. The address was reserved long before the web "
        "grew up, set aside by the registry itself, and that old reservation still holds."
    )
    shots = montage.factual_shots(long, 1, live=True, settings=_Settings())
    assert len(shots) > 1
    assert shots[-1]["cut_after"] is None
    assert all(shot["cut_after"] in pauses.JOIN_CLASSES for shot in shots[:-1])
    (one,) = montage.factual_shots("Short.", 1, live=True, settings=_Settings())
    assert one["cut_after"] is None


def test_serial_shots_mark_what_happens_at_each_cut():
    shot = lambda *lines, size="single": {"lines": list(lines), "size": size}  # noqa: E731
    kael = {"speaker": "Kael", "text": "The render is late."}
    sarah = {"speaker": "Sarah", "text": "Then ship it."}
    narrator = {"speaker": None, "text": "The bay went quiet."}
    cut_off = {"speaker": "Kael", "text": "I was going to —"}
    assert montage.serial_cut(shot(kael), shot(sarah)) == montage.SPEAKER_CHANGE
    assert montage.serial_cut(shot(cut_off), shot(sarah)) == montage.INTERRUPT_CUT
    assert montage.serial_cut(shot(kael), shot(narrator)) == montage.NARRATOR_IN
    assert montage.serial_cut(shot(narrator), shot(kael)) == montage.NARRATOR_OUT
    assert montage.serial_cut(shot(kael), shot(kael, size="reaction")) == montage.REACTION_SPLIT
    assert montage.serial_cut(shot(kael), shot(kael)) == montage.SAME_SPEAKER
    assert montage.serial_cut(shot(kael), None) == montage.BEAT_END


# --------------------------------------------------------------------- the serial's marks


def test_a_mark_in_the_middle_cuts_the_line_and_each_run_is_named_for_its_take(rules):
    beats = [
        [
            {"speaker": "Kael", "text": "I told you it is gone.", "pause_at": 3},
            {"speaker": "Kael", "text": "Gone."},
            {"speaker": "Sarah", "text": "Then find it."},
            {"speaker": None, "text": "Nobody moved."},
        ],
        [
            {"speaker": "Sarah", "text": "Well?", "direction": "a long pause"},
            {"speaker": "Kael", "text": "Found it."},
        ],
    ]
    lines = pause_plan.serial_lines(beats, ["hook", "button"], rules)
    first, second = lines
    assert [line["text"] for line in first[:3]] == ["I told you", "it is gone.", "Gone."]
    assert first[0].get("mark_after") is True
    # One take until another voice or a mark: Kael's two lines after the mark are one take.
    assert [line["voice_group"] for line in first] == ["b1.1", "b1.2", "b1.2", "b1.3", "b1.4"]
    # «a long pause» says no place: after the line; but the punchline follows it, so no mark.
    assert second[-1].get("punchline") is True
    assert not second[0].get("mark_after")
    assert [line["voice_group"] for line in second] == ["b2.1", "b2.2"]


def test_at_most_one_mark_a_beat_the_first_one(rules):
    beats = [
        [
            {"speaker": "Kael", "text": "One.", "pause_at": "end"},
            {"speaker": "Sarah", "text": "Two.", "pause_at": "end"},
            {"speaker": "Kael", "text": "Three."},
        ]
    ]
    (lines,) = pause_plan.serial_lines(beats, ["situation"], rules)
    assert [bool(line.get("mark_after")) for line in lines] == [True, False, False]


def test_a_run_is_one_take_inside_its_group_only():
    lines = [
        {"speaker": "Kael", "text": "One.", "voice_group": "b1.1"},
        {"speaker": "Kael", "text": "Two.", "voice_group": "b1.2"},
        {"speaker": "Kael", "text": "Three.", "voice_group": "b1.2", "direction": "flat"},
        {"speaker": "Sarah", "text": "Four.", "voice_group": "b1.3"},
    ]
    assert [len(run) for run in line_runs(lines)] == [1, 2, 1]
    takes = speaker_segments(lines, {"Kael": "k"})
    assert [t["text"] for t in takes] == ["One.", "Two. Three.", "Four."]
    assert [t["voice_group"] for t in takes] == ["b1.1", "b1.2", "b1.3"]
    assert takes[1]["direction"] == "flat"
    # Lines without a group join as they always did.
    plain = [{"speaker": "Kael", "text": "A."}, {"speaker": "Kael", "text": "B."}]
    assert speaker_segments(plain) == [
        {"speaker": "Kael", "character_id": None, "text": "A. B.", "direction": ""}
    ]


# --------------------------------------------------------------------- the frozen beat tag


def test_keep_frozen_carries_the_pauses_over_a_new_package_and_shot_tag_hides_them():
    old = {
        "beat": {
            "scene_number": 2,
            "shot": 1,
            "of": 2,
            "voice_group": "s2",
            "pause_after": {"class": "IN_TAKE", "seconds": 0.0},
            "inner_pauses": [],
        }
    }
    new = {"still_prompt": "x", "beat": {"scene_number": 2, "shot": 1, "of": 2}}
    kept = keep_frozen(new, old)
    assert kept["beat"]["pause_after"] == {"class": "IN_TAKE", "seconds": 0.0}
    assert kept["still_prompt"] == "x" and new["beat"] == {"scene_number": 2, "shot": 1, "of": 2}
    assert shot_tag(kept) == {"scene_number": 2, "shot": 1, "of": 2}
    assert shot_tag({"beat": {"voice_group": "s1", "pause_after": {}}}) == {}
    assert keep_frozen(new, None) is new


# ------------------------------------------------------------------- the factual storyboard


def _factual_board(engine, scenes) -> str:
    from app.media.services import generate_storyboard_from_script
    from app.models import OwnerPolicy
    from test_editorial_quality import GOOD_STORY, a_passed_review, a_script, a_topic

    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        if policy:
            policy.autonomy_stopped = False
    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id, scenes=scenes, story=GOOD_STORY)
    a_passed_review(engine, script_id)
    return generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")["id"]


LONG = (
    "There is one web address on earth that nobody is allowed to buy, and every registrar "
    "refuses it the moment you type it in. The address was reserved long before the web "
    "grew up, set aside by the registry itself, and that old reservation still holds: the "
    "address cannot be registered by anyone, however much they offer."
)


def _scene(number: int, purpose: str, narration: str) -> dict:
    return {
        "scene_number": number,
        "purpose": purpose,
        "narration": narration,
        "visual_description": f"A desk lamp over a notebook, scene {number}.",
        "claim_ids": ["c1"],
    }


@pytest.mark.montage
def test_a_factual_scene_is_one_take_its_shots_cut_inside_it_and_every_join_frozen(engine):
    board = _factual_board(
        engine,
        [
            _scene(1, "HOOK", LONG),
            _scene(2, "DEVELOPMENT", "The registry keeps a short list of names it never sells."),
            _scene(3, "EVIDENCE", "The list has been public since nineteen eighty-seven…"),
            _scene(4, "ENDING", "Reserved on purpose, by the registry itself."),
        ],
    )
    rows = _rows(engine, board)
    tags = [montage.beat_of(row.prompt_json) for row in rows]
    hook = [t for t in tags if t.get("voice_group") == "s1"]
    assert len(hook) >= 2, "the long hook is cut into shots of one take"
    # The montage's tag is intact beside the pauses.
    numbers = [shot_tag(row.prompt_json).get("scene_number") for row in rows[: len(hook)]]
    assert numbers == [1] * len(hook)
    # Inside the take the cut adds nothing, and knows the join it would be voiced alone.
    for tag in hook[:-1]:
        after = tag["pause_after"]
        assert after["class"] == pauses.IN_TAKE and after["seconds"] == 0.0
        assert after["fallback"]["class"] in pauses.JOIN_CLASSES
    classes = [tag["pause_after"]["class"] for tag in tags]
    # HOOK -> DEVELOPMENT is a new section; DEVELOPMENT <-> EVIDENCE is the body's alternation.
    assert hook[-1]["pause_after"]["class"] == pauses.PARAGRAPH
    after_development = tags[len(hook)]["pause_after"]
    assert after_development["class"] == pauses.SENTENCE
    # The writer's «…» at the end of a scene is a real silence, in the beat band.
    evidence = tags[len(hook) + 1]["pause_after"]
    assert evidence["class"] == pauses.BEAT and evidence["marked"] is True
    rules = pauses.load_rules()
    assert rules.beat_floor_seconds <= evidence["seconds"] <= rules.beat_ceiling_seconds
    # The film's end is the narrator's PARAGRAPH pause.
    assert classes[-1] == pauses.END
    assert tags[-1]["pause_after"]["seconds"] == pytest.approx(
        hook[-1]["pause_after"]["seconds"], abs=0.002
    )
    # Every join says whose pause it is and under which rules; the first row holds the numbers.
    assert all(tag["pause_after"]["rule_version"] == rules.version for tag in tags)
    profile = tags[0]["pause_profile"]
    assert profile["rule_version"] == rules.version and profile["channel"] == "factual"
    assert profile["wall"]["fits"] is True and profile["wall"]["wall"] <= 180.0
    assert all("pause_profile" not in tag for tag in tags[1:])
    assert pause_plan.film_is_frozen([row.prompt_json for row in rows])


def test_a_film_built_without_the_rules_keeps_the_legacy_timing(engine, monkeypatch, tmp_path):
    import json

    data = json.loads(pauses.RULES_FILE.read_text(encoding="utf-8"))
    data["use_until_the_owner_changes_it"] = False
    off = tmp_path / "pause_rules.json"
    off.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(pauses, "RULES_FILE", off)
    board = _factual_board(engine, [_scene(1, "HOOK", "One short scene, said once.")])
    rows = _rows(engine, board)
    assert all(row.prompt_json is None for row in rows)
    assert not pause_plan.film_is_frozen([row.prompt_json for row in rows])


def test_the_shot_plan_keeps_the_pauses_and_never_shows_them_to_a_model(engine):
    from app.media.models import Storyboard
    from app.media.prompt_agent import _film_facts, write_shot_prompts

    board = _factual_board(
        engine,
        [
            _scene(1, "HOOK", "One web address is reserved and cannot be registered by anyone."),
            _scene(2, "ENDING", "The registry reserved the address itself, and it still stands."),
        ],
    )
    before = [montage.beat_of(row.prompt_json) for row in _rows(engine, board)]
    with Session(engine) as session:
        facts = _film_facts(session, session.get(Storyboard, board))
    # A scene of one shot shows no tag to the model, exactly as before the pauses.
    assert [scene["beat"] for scene in facts["scenes"]] == [None, None]
    write_shot_prompts(engine, None, board, str(uuid4()))
    after = [montage.beat_of(row.prompt_json) for row in _rows(engine, board)]
    for old, new in zip(before, after, strict=True):
        assert new["pause_after"] == old["pause_after"]
        assert new["voice_group"] == old["voice_group"]


def test_the_render_reads_the_frozen_pauses_from_its_view_of_a_row(engine):
    from app.media.assembler import scene_view

    board = _factual_board(engine, [_scene(1, "HOOK", "One short scene, said once.")])
    (row,) = _rows(engine, board)
    view = scene_view(row)
    assert view["pause_after"]["class"] == pauses.END
    assert view["voice_group"] == "s1" and view["inner_pauses"] == []


# --------------------------------------------------------------------- the serial storyboard


def test_a_serial_row_of_two_speakers_freezes_its_turn_and_its_beat_end(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
    monkeypatch,
):
    from app.media.serial_storyboard import storyboard_from_episode
    from app.story.services import decide_episode
    from test_serial_pipeline import KAEL, SARAH, beats_for, letters_day, written

    _, ids = letters_day(engine)
    beats = beats_for(ids, [KAEL, SARAH], count=3)
    beats[1]["lines"][0]["text"] = f"{beats[1]['lines'][0]['text']} (beat)"
    episode = written(engine, monkeypatch, beats)
    decide_episode(engine, episode["id"], True, "")
    board = storyboard_from_episode(engine, episode["id"], str(uuid4()))
    rows = _rows(engine, board)
    tags = [montage.beat_of(row.prompt_json) for row in rows]
    rules = pauses.load_rules()
    # With the montage off a beat is one row: Kael then Sarah, a turn between them inside it.
    first = tags[0]
    (turn,) = first["inner_pauses"]
    assert turn["class"] == pauses.TURN
    assert rules.turn_floor_seconds <= turn["seconds"] <= 1.2
    assert first["pause_after"]["class"] == pauses.PARAGRAPH  # the beat ends
    # The writer's «(beat)» after Kael's line in beat 2 is a real silence before Sarah.
    (marked,) = tags[1]["inner_pauses"]
    assert marked["class"] == pauses.BEAT and marked["unmarked_class"] == pauses.TURN
    assert tags[-1]["pause_after"]["class"] == pauses.END
    assert tags[0]["pause_profile"]["channel"] == "serial"
    assert pause_plan.film_is_frozen([row.prompt_json for row in rows])


@pytest.mark.montage
def test_a_speakers_run_cut_over_the_listener_is_one_take(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
    monkeypatch,
):
    from app.media.serial_storyboard import storyboard_from_episode
    from app.story.services import decide_episode
    from test_serial_pipeline import KAEL, SARAH, beats_for, letters_day, written

    _, ids = letters_day(engine)
    beats = beats_for(ids, [KAEL, SARAH], count=3)
    beats[1]["lines"][0]["text"] = (
        "The render is late because the stills came back dark, every one of them, and I "
        "sent them again at six with the lamps turned up, so the bay will be busy until "
        "noon and nobody should touch the queue before I say so."
    )
    episode = written(engine, monkeypatch, beats)
    decide_episode(engine, episode["id"], True, "")
    board = storyboard_from_episode(engine, episode["id"], str(uuid4()))
    rows = _rows(engine, board)
    tags = [montage.beat_of(row.prompt_json) for row in rows]
    kael_long = [t for t in tags if t.get("scene_number") == 2 and t.get("voice_group") == "b2.1"]
    assert len(kael_long) >= 2, tags
    assert kael_long[0]["pause_after"]["class"] == pauses.IN_TAKE
    assert kael_long[0]["pause_after"]["seconds"] == 0.0
