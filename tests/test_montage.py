"""Montage (the Owner, 2026-10-16): a scene cut into shots of about four seconds, each an
ordinary storyboard scene; the serial cuts with its dialogue and shows the listener."""

from __future__ import annotations

import pytest
from app.media import montage

pytestmark = pytest.mark.montage

ON = {"montage_enabled": True, "montage_shot_seconds": 4.0, "montage_max_shots_per_scene": 3}


class _Settings:
    def __init__(self, **values):
        self.__dict__.update(ON)
        self.__dict__.update(values)


NARRATION = (
    "In 1931 Ernest Lawrence built a machine no wider than his hand, and it spun protons "
    "faster than anything before it. The idea was simple: push the particle a little on "
    "every turn, and let a magnet bring it round again. By the summer it reached eighty "
    "thousand volts, and the lab had a new kind of instrument."
)


def test_a_long_narration_is_cut_into_three_shots_on_its_clauses():
    shots = montage.factual_shots(NARRATION, 1, live=True, settings=_Settings())
    assert [s["shot"] for s in shots] == [1, 2, 3] and all(s["of"] == 3 for s in shots)
    assert [s["size"] for s in shots] == ["wide", "medium", "detail"]
    # Every word once, in order, and every cut on a clause end.
    assert " ".join(s["narration"] for s in shots) == NARRATION
    assert all(s["narration"].rstrip()[-1] in ".,:;!?" for s in shots[:-1])
    assert all(len(s["narration"].split()) >= montage.MIN_SHOT_WORDS for s in shots)


def test_a_short_narration_a_card_and_a_montage_off_stay_one_shot():
    short = "Lawrence built a machine no wider than his hand."
    assert montage.factual_shots(short, 2, live=True, settings=_Settings()) == [
        {"narration": short, "size": None, "shot": 1, "of": 1}
    ]
    (card,) = montage.factual_shots(NARRATION, 3, live=False, settings=_Settings())
    assert card["of"] == 1 and card["size"] is None
    (off,) = montage.factual_shots(
        NARRATION, 1, live=True, settings=_Settings(montage_enabled=False)
    )
    assert off["narration"] == NARRATION


def test_the_next_beat_starts_where_the_beat_before_stopped():
    assert montage.factual_sizes(3, 1) == ["wide", "medium", "detail"]
    assert montage.factual_sizes(2, 2) == ["medium", "detail"]
    assert montage.factual_sizes(2, 3) == ["detail", "wide"]


def test_the_shot_count_follows_the_words_and_never_makes_a_flicker():
    assert montage.shot_count(5, shot_seconds=4.0, max_shots=3) == 1
    assert montage.shot_count(20, shot_seconds=4.0, max_shots=3) == 2
    assert montage.shot_count(40, shot_seconds=4.0, max_shots=3) == 3
    assert montage.shot_count(11, shot_seconds=4.0, max_shots=3) == 1  # two shots of 5 words
    assert montage.shot_count(40, shot_seconds=4.0, max_shots=1) == 1


def test_a_beat_of_dialogue_cuts_with_its_speakers_and_shows_the_listener():
    lines = [
        {
            "speaker": "Sarah",
            "text": "The render bay is dark again, and nobody told me.",
            "direction": "dry",
        },
        {"speaker": "Marcus", "text": "Told you what?", "direction": ""},
        {
            "speaker": "Sarah",
            "text": (
                "That the whole queue stopped at six, that the stills never came back, and "
                "that the Accountant is already asking me where the money went this morning."
            ),
            "direction": "rising",
        },
    ]
    shots = montage.serial_shots(lines, 1, part="situation", first_beat=True, settings=_Settings())
    assert [s["size"] for s in shots] == ["establishing", "single", "reaction"]
    # Marcus's four words join Sarah's opening shot; the first shot establishes the room.
    assert [line["speaker"] for line in shots[0]["lines"]] == ["Sarah", "Marcus"]
    # Sarah's long run is cut in two: her single, then Marcus listening while she goes on.
    assert shots[1]["on"] == "Sarah" and shots[2]["on"] == "Marcus"
    assert all(line["speaker"] == "Sarah" for line in shots[2]["lines"])
    assert shots[2]["lines"][0]["direction"] == "rising"
    spoken = " ".join(line["text"] for s in shots for line in s["lines"])
    assert spoken == " ".join(line["text"] for line in lines)
    assert [(s["shot"], s["of"]) for s in shots] == [(1, 3), (2, 3), (3, 3)]


def test_the_button_ends_on_a_close_up_and_a_switched_off_montage_keeps_the_beat():
    lines = [
        {"speaker": "Marcus", "text": "So we are publishing it anyway, every single flaw of it."},
        {"speaker": "Sarah", "text": "We are publishing what we have. That was always the rule."},
    ]
    shots = montage.serial_shots(lines, 6, part="button", first_beat=False, settings=_Settings())
    assert [s["size"] for s in shots] == ["single", "close"]
    (whole,) = montage.serial_shots(
        lines, 6, part="button", first_beat=False, settings=_Settings(montage_enabled=False)
    )
    assert whole["lines"] == lines and whole["size"] is None


def test_the_beat_tag_names_the_writers_scene_and_the_shot():
    tag = montage.beat_tag(4, 2, 3, "medium", on="Sarah", ignored=None)
    assert tag == {"scene_number": 4, "shot": 2, "of": 3, "size": "medium", "on": "Sarah"}
    assert montage.beat_of({"beat": tag}) == tag and montage.beat_of(None) == {}
