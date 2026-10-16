"""The montage's cuts keep every line with its speaker, never leave a shot under a take or
over a clip, and never cut between a title and its name (review of 2026-10-16)."""

from __future__ import annotations

import pytest
from app.media import montage

pytestmark = pytest.mark.montage

ON = {"montage_enabled": True, "montage_shot_seconds": 4.0, "montage_max_shots_per_scene": 3}


class _Settings:
    def __init__(self, **values):
        self.__dict__.update(ON)
        self.__dict__.update(values)


def _said(count: int, word: str = "word") -> str:
    """``count`` spoken words, one sentence."""
    return " ".join(f"{word}{i}" for i in range(count)) + "."


def _seconds(shot: dict) -> float:
    words = sum(len(line["text"].split()) for line in shot["lines"])
    return words * montage.SECONDS_PER_SPOKEN_WORD


def _shots(lines: list[dict], *, first_beat: bool = False, part: str = "turn") -> list[dict]:
    return montage.serial_shots(lines, 2, part=part, first_beat=first_beat, settings=_Settings())


def _kept_whole(lines: list[dict], **how) -> list[dict]:
    """The beat's shots, checked: every line's words are said once, in order, by its own
    speaker with its own note (the parts of a line cut across shots put back together are
    that line again), and no shot passes the clip."""
    tagged = [{**line, "line": index} for index, line in enumerate(lines)]
    shots = _shots(tagged, **how)
    rebuilt: list[dict] = []
    for piece in (part for shot in shots for part in shot["lines"]):
        if rebuilt and rebuilt[-1]["line"] == piece["line"]:
            rebuilt[-1] = {**rebuilt[-1], "text": f"{rebuilt[-1]['text']} {piece['text']}"}
        else:
            rebuilt.append(dict(piece))
    assert rebuilt == [{**line, "text": " ".join(line["text"].split())} for line in tagged]
    assert all(_seconds(shot) <= montage.MAX_SHOT_SECONDS for shot in shots), [
        _seconds(shot) for shot in shots
    ]
    return shots


def test_a_two_shot_cut_in_pieces_never_gives_one_speakers_words_to_another():
    # Sarah's two words are too short for a shot of their own, so they join Kael's long line
    # as a two-shot; the clip cuts that shot, and her reply must stay hers, in her voice.
    kael = {
        "speaker": "Kael",
        "text": (
            "I checked the queue twice this morning and the render bay is still dark, so we "
            "wait until the night shift wakes up."
        ),
        "direction": "firmly",
    }
    sarah = {"speaker": "Sarah", "text": "Fine, go.", "direction": "sighs"}
    shots = _shots([kael, sarah])

    assert len(shots) >= 2
    _kept_whole([kael, sarah])
    replies = [line for shot in shots for line in shot["lines"] if "Fine, go." in line["text"]]
    assert replies == [sarah]
    # The shot with her reply is on both of them; no shot is a reaction on someone talking.
    (with_reply,) = [shot for shot in shots if sarah in shot["lines"]]
    assert with_reply["size"] == "two_shot"
    for shot in shots:
        if shot["size"] == "reaction":
            assert shot["on"] not in {line["speaker"] for line in shot["lines"]}

    # Forced pieces beyond the lines (a run far past the clip) keep the speakers too.
    long_kael = {**kael, "text": f"{kael['text']} {_said(30)}"}
    _kept_whole([long_kael, sarah])


def test_a_short_first_line_joins_the_next_speaking_shot_never_the_narrator():
    morning = {"speaker": "Kael", "text": "Morning."}
    answer = {"speaker": "Sarah", "text": _said(14)}
    narrator = {"speaker": None, "text": _said(12, "n")}

    # The beat opens on one word: no shot of under a second, it is heard in her shot.
    (shot,) = _shots([morning, answer])
    assert shot["lines"] == [morning, answer] and shot["size"] == "two_shot"

    # The first words after the narrator join the next speaking shot, not the narrator's.
    opening, shared = _shots([narrator, morning, answer])
    assert opening["lines"] == [narrator] and opening["size"] == "establishing"
    assert shared["lines"] == [morning, answer] and shared["size"] == "two_shot"

    # Before the narrator, nothing speaks after it in the room: it stays its own shot, and the
    # narrator's shot stays his.
    alone, closing = _shots([morning, narrator], part="button")
    assert alone["lines"] == [morning] and closing["lines"] == [narrator]

    # A beat whose only line is short is one shot.
    (only,) = _shots([morning])
    assert only["lines"] == [morning]


def test_whole_lines_too_long_for_one_clip_are_cut_below_it():
    # A narrator opening written as three lines, then a short exchange: 45 narrated words
    # are more than one clip, and no shot may pass MAX_SHOT_SECONDS.
    opening = [{"speaker": None, "text": _said(n, "n")} for n in (15, 16, 14)]
    exchange = [{"speaker": "Kael", "text": _said(8)}, {"speaker": "Sarah", "text": _said(12)}]
    shots = _kept_whole([*opening, *exchange], first_beat=True, part="hook")
    narrated = [shot for shot in shots if shot["on"] is None]
    # Each narrated line fits a clip, so they are cut between lines, never inside one.
    assert [[line["text"] for line in shot["lines"]] for shot in narrated] == [
        [line["text"]] for line in opening
    ]

    # Unequal lines of one speaker: ten words, then twenty-five.
    beat = [
        {"speaker": "Sarah", "text": _said(8, "s")},
        {"speaker": "Kael", "text": _said(10, "a")},
        {"speaker": "Kael", "text": _said(25, "b")},
        {"speaker": "Sarah", "text": _said(8, "t")},
    ]
    _kept_whole(beat)


@pytest.mark.parametrize(
    "sizes",
    [(40,), (23, 2), (2, 23), (5, 30, 3), (12, 12, 12, 12), (50, 1), (3, 3, 3), (9, 28, 9)],
)
def test_every_cut_keeps_the_speakers_and_stays_within_the_clip(sizes):
    speakers = ["Kael", "Sarah", None, "Kael"]
    lines = [
        {"speaker": speakers[i % len(speakers)], "text": _said(n, f"w{i}x"), "direction": f"d{i}"}
        for i, n in enumerate(sizes)
    ]
    shots = _kept_whole(lines)
    for shot in shots:
        voices = {line["speaker"] for line in shot["lines"]}
        assert None not in voices or voices == {None}  # the narrator never shares a shot


def test_a_title_or_an_abbreviation_is_never_where_a_shot_cuts():
    doctor = (
        "The order that changed the whole programme in the spring was signed by Dr. Ellen "
        "Harper and sent on to the board that very night."
    )
    navy = (
        "The sealed order that reached the base before the storm came straight from the U.S. "
        "Navy and nobody on the island was allowed to read it."
    )
    for text, title in ((doctor, "Dr."), (navy, "U.S.")):
        fragments = montage.split_words(text, 2)
        assert len(fragments) == 2 and " ".join(fragments) == text
        assert not any(fragment.endswith(title) for fragment in fragments), fragments

    shots = montage.factual_shots(doctor, 1, live=True, settings=_Settings())
    assert not any(shot["narration"].endswith("Dr.") for shot in shots)


def test_a_sentence_ends_where_a_sentence_ends():
    from app.story.lines import ends_sentence, sentence_count

    assert sentence_count("Dr. Aris, for once, has nothing left to count.") == 1
    assert (
        sentence_count(
            "This is the research floor of AMN-AI. Dr. Aris guards his numbers. Today Kael "
            "wants them."
        )
        == 3
    )
    assert sentence_count("The order came from the U.S. Navy, e.g. a sealed note.") == 1
    assert sentence_count("Mr. and Mrs. Hale left at six. St. Clair stayed, vs. the rule.") == 2
    assert sentence_count("J. Robert Oppenheimer ran it. The budget grew 3.5 times.") == 2
    assert sentence_count('So did I. "Go." Then nothing') == 3
    assert sentence_count("... !") == 0 and sentence_count("") == 0
    assert ends_sentence("night.") and ends_sentence('go."') and ends_sentence("now?!")
    assert not ends_sentence("Dr.") and not ends_sentence("U.S.") and not ends_sentence("J.")
