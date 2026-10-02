"""Captions a phone can read: phrase-aware cards, the spoken word highlighted, numbers marked.

The Nepal rehearsal (2026-10-01) burnt "Nepal is paying for a" / "crisis it did not create."
and "Which other country do you" / "think is being asked to": cards closed at five words
whatever the last word was, in one white Inter Bold 66 with no shadow and nothing that
followed the voice, although the voice's own word timings were there.

Now:
- a card never ends on a function word (EN and RO, one shared list): the word moves on to the
  next card;
- the burnt ASS highlights the word being spoken (a colour change timed from the word
  timings), gives numbers a third colour, carries a soft shadow, and is set larger (72-80)
  while keeping its bottom at y 1500 and clear of the right 120 px;
- the colours are a look setting in config/factual_look.json, which the Owner may change;
- an on-screen hook headline is possible, and off by default.

Every burn here is the local FFmpeg with libass; no provider is called.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from app.factual.editorial import dangles
from app.media import assembler, cards
from app.media.assembler import (
    CAPTION_BOTTOM_Y,
    CAPTION_FONT_SIZE,
    CAPTION_MARGIN_V,
    ass_captions_filter,
    ass_from_cues,
    caption_cards,
    caption_cues,
    film_finish,
    install_caption_fonts,
)
from app.media.toolchain import find_ffmpeg, has_filter

FFMPEG = find_ffmpeg()
requires_libass = pytest.mark.skipif(
    FFMPEG is None or not has_filter(FFMPEG, "subtitles"),
    reason="the local ffmpeg has no libass (subtitles filter)",
)


def texts(groups: list[list[str]]) -> list[str]:
    return [" ".join(group) for group in groups]


# --------------------------------------------------------------------------- the cards


def test_the_nepal_line_breaks_at_the_phrase_not_in_the_middle_of_it():
    groups = caption_cards("Nepal is paying for a crisis it did not create.".split())
    assert texts(groups)[0] == "Nepal is paying"
    assert texts(groups)[1].startswith("for a crisis")
    assert " ".join(texts(groups)) == "Nepal is paying for a crisis it did not create."


@pytest.mark.parametrize(
    "line",
    [
        "Which other country do you think is being asked to pay a bill it never ran up?",
        "Nepal is paying for a crisis it did not create.",
        "Țara plătește o factură pe care nu a făcut-o niciodată, iar lumea privește în altă parte.",
        "The money was promised to the poorest countries and most of it never came at all.",
    ],
)
def test_no_card_but_the_last_ends_on_a_function_word(line):
    groups = caption_cards(line.split())
    assert " ".join(texts(groups)) == line, "no word is lost or moved out of order"
    for group in groups[:-1]:
        assert not dangles(group[-1]), (group, texts(groups))
        assert 2 <= len(group) <= assembler.CAPTION_MAX_WORDS


@pytest.mark.parametrize(
    "line",
    [
        "Promisiunea a fost de o sută de miliarde de dolari pe an pentru țările sărace.",
        "Right, where are we with the number this morning, everyone?",
    ],
)
def test_a_line_no_cut_can_clear_of_function_words_keeps_its_cards_and_dangles_once(line):
    """'Promisiunea a fost de o' / 'Right, where are we with': every card of two to five
    words from the first word ends on a function word, so one card must; the contract the
    render records (two to five words) is kept, and only that one card dangles."""
    groups = caption_cards(line.split())
    assert " ".join(texts(groups)) == line
    assert all(2 <= len(group) <= assembler.CAPTION_MAX_WORDS for group in groups)
    assert sum(dangles(group[-1]) for group in groups[:-1]) == 1, texts(groups)


# --------------------------------------------------------------------------- the ASS


def _timed_scene() -> dict:
    words = "Nepal received 83 billion dollars of the promised money".split()
    timings = [
        {"word": word, "start": round(0.2 + 0.4 * i, 3), "end": round(0.5 + 0.4 * i, 3)}
        for i, word in enumerate(words)
    ]
    return {
        "scene_index": 1,
        "duration_seconds": 5.0,
        "audio_seconds": 4.5,
        "voiceover_segment": " ".join(words),
        "word_timings": timings,
    }


def _dialogues(script: str) -> list[str]:
    return [line for line in script.splitlines() if line.startswith("Dialogue:")]


def _ass_colour(hex_colour: str) -> str:
    red, green, blue = hex_colour[1:3], hex_colour[3:5], hex_colour[5:7]
    return f"&H{blue}{green}{red}&".upper().replace("&H", "&H", 1)


def test_the_spoken_word_is_highlighted_from_the_word_timings():
    finish = film_finish()
    cues = caption_cues([_timed_scene()])
    # The cues carry each word's own time.
    first = cues[0]
    assert [w["word"] for w in first["words"]] == " ".join(first["lines"]).split()
    assert first["words"][0]["start"] == pytest.approx(0.2)

    script = ass_from_cues(cues, finish=finish)
    dialogues = _dialogues(script)
    assert dialogues
    active = _ass_colour(finish["captions"]["active"])
    body = dialogues[0].split(",,", 1)[1]
    # One timed colour change per word: on at its start, off at its end, in ms from the cue.
    switches = re.findall(r"\\t\((\d+),(\d+),\\1c(&H[0-9A-F]{6}&)\)", body)
    assert len(switches) == 2 * len(first["words"])
    on = [int(start) for start, _end, colour in switches if colour == active]
    starts = [round((w["start"] - first["start"]) * 1000) for w in first["words"]]
    assert on == starts


def test_numbers_carry_the_emphasis_colour():
    finish = film_finish()
    script = ass_from_cues(caption_cues([_timed_scene()]), finish=finish)
    emphasis = _ass_colour(finish["captions"]["emphasis"])
    number_card = next(line for line in _dialogues(script) if "83" in line)
    # The number is written in the emphasis colour, its neighbours in the text colour.
    assert re.search(r"\\1c" + re.escape(emphasis) + r"[^}]*\}83", number_card)
    text = _ass_colour(finish["captions"]["text"])
    assert re.search(r"\\1c" + re.escape(text) + r"[^}]*\}received", number_card)


def test_the_caption_style_is_larger_with_a_soft_shadow_and_the_same_safe_bottom():
    script = ass_from_cues(caption_cues([_timed_scene()]), finish=film_finish())
    style = next(line for line in script.splitlines() if line.startswith("Style: Caption"))
    fields = style.split(",")
    assert 72 <= float(fields[2]) <= 80 and float(fields[2]) == CAPTION_FONT_SIZE
    back = fields[6]
    assert back.startswith("&H") and int(back[2:4], 16) in range(0x55, 0x70)  # ~60% black
    assert 2.0 <= float(fields[17]) <= 3.0  # shadow
    assert int(fields[21]) == CAPTION_MARGIN_V and CAPTION_BOTTOM_Y == 1500


def test_the_colours_are_the_owners_look_setting(tmp_path):
    look = json.loads(Path("config/factual_look.json").read_text(encoding="utf-8"))
    assert {"text", "active", "emphasis"} <= set(look["finish"]["captions"])
    own = tmp_path / "look.json"
    look["finish"]["captions"]["active"] = "#12AB34"
    own.write_text(json.dumps(look), encoding="utf-8")
    finish = film_finish(own)
    assert finish["captions"]["active"] == "#12AB34"
    script = ass_from_cues(caption_cues([_timed_scene()]), finish=finish)
    assert "\\1c&H34AB12&" in script

    # A colour that is not a colour is not used; the studio's default stands, with a note.
    look["finish"]["captions"]["active"] = "yellow"
    own.write_text(json.dumps(look), encoding="utf-8")
    broken = film_finish(own)
    assert broken["captions"]["active"] == film_finish()["captions"]["active"]
    assert broken["notes"]


def test_the_hook_headline_is_off_by_default_and_on_when_the_look_asks():
    cues = caption_cues([_timed_scene()])
    finish = film_finish()
    assert finish["headline"]["show"] is False
    plain = ass_from_cues(cues, finish=finish, headline="Who pays for a crisis?")
    assert "Headline" not in "\n".join(_dialogues(plain))

    shown = {**finish, "headline": {**finish["headline"], "show": True, "seconds": 2.2}}
    script = ass_from_cues(cues, finish=shown, headline="Who pays for a crisis?")
    assert any(line.startswith("Style: Headline") for line in script.splitlines())
    headline = next(line for line in _dialogues(script) if ",Headline," in line)
    assert headline.startswith("Dialogue: 1,0:00:00.00,0:00:02.20,Headline")
    assert "Who pays for a crisis?" in headline


@requires_libass
def test_the_highlighted_word_is_burnt_in_its_colour_inside_the_safe_area(tmp_path):
    finish = film_finish()
    cues = caption_cues([_timed_scene()])
    (tmp_path / "captions.ass").write_text(ass_from_cues(cues, finish=finish), encoding="utf-8")
    install_caption_fonts(tmp_path)
    word = cues[0]["words"][1]
    moment = (word["start"] + word["end"]) / 2
    raw = subprocess.run(  # noqa: S603 - argument list, no shell
        [
            FFMPEG,
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:size=1080x1920:rate=24:duration=5",
            "-vf",
            f"{ass_captions_filter('captions.ass')},select='eq(n\\,{int(moment * 24)})',"
            "format=rgb24",
            "-fps_mode",
            "passthrough",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
        timeout=120,
    ).stdout
    assert len(raw) == 1080 * 1920 * 3
    active = finish["captions"]["active"]
    want = tuple(int(active[i : i + 2], 16) for i in (1, 3, 5))
    lit: list[tuple[int, int]] = []
    coloured = 0
    for index in range(0, len(raw), 3):
        r, g, b = raw[index], raw[index + 1], raw[index + 2]
        if max(r, g, b) > 60:
            pixel = index // 3
            lit.append((pixel % 1080, pixel // 1080))
            if abs(r - want[0]) < 40 and abs(g - want[1]) < 40 and abs(b - want[2]) < 40:
                coloured += 1
    assert coloured > 200, "the spoken word is drawn in the active colour"
    xs = [x for x, _ in lit]
    ys = [y for _, y in lit]
    assert min(xs) >= cards.SAFE_RECT[0] and max(xs) <= 1080 - 120, (min(xs), max(xs))
    assert min(ys) >= cards.SAFE_RECT[1] and max(ys) <= CAPTION_BOTTOM_Y, (min(ys), max(ys))


@pytest.mark.parametrize(
    "line",
    [
        "The evidence first, then the opinion, and never the reverse.",
        "Which other country do you think is being asked to pay a bill it never ran up?",
        "Nepal is paying for a crisis it did not create.",
        "Țara plătește o factură pe care nu a făcut-o niciodată, iar lumea privește în altă parte.",
        "The money was promised to the poorest countries and most of it never came at all.",
    ],
)
def test_every_card_keeps_two_to_five_words_and_none_ends_on_a_function_word(line):
    """The contract the render records (words_per_card [2, 5]) holds even on a line heavy
    with function words: moving them on may not leave a word alone ("Right,") or make a
    six-word card ("where are we with the number"); the cards are cut again instead."""
    groups = caption_cards(line.split())
    assert " ".join(texts(groups)) == line
    for group in groups:
        assert assembler.CAPTION_MIN_WORDS <= len(group) <= assembler.CAPTION_MAX_WORDS, texts(
            groups
        )
    for group in groups[:-1]:
        assert not dangles(group[-1]), texts(groups)
