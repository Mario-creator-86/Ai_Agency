"""«Pauza vocii»: what the adversarial review of 2026-10-16 found, each pinned so it stays fixed.

Each test names the finding it holds: a row said by two voices bought at its slowest voice's
rate, a rendered reading that counted its silences twice, an interruption read as dead air, the
render's pause room blind to ``cut_in_pause``, a writer's mark counted in the wrong beat, a kept
take read to the vendor's end of file, an L-cut that left its words on the next shot, a paid
take bought again when the rules changed, a wall computed and never enforced, the serial review
blind to its channel's maximum, the limits hard-coded in quality control, the in-take pause a
clip holds, and the sheet giving up pauses the render keeps. Every voice here is a local fake
or a number: nothing is bought from anyone, and no model is asked.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.media import assembler, film_length, pause_plan, pauses, qc
from app.media.assembler import (
    NARRATION_ESTIMATED,
    TIMELINE_FPS,
    clip_fits,
    narration_to_buy,
)
from app.media.toolchain import find_ffmpeg
from pause_timing import PINNED_VOICE_PROFILES
from sqlalchemy.orm import Session

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="FFmpeg is not installed")
FRAME = 1.0 / TIMELINE_FPS
FAST = "TEST:voice-model:fast"
SLOW = "TEST:voice-model:slow"
#: The montage on, as the studio ships it: four seconds a shot, at most three a scene.
MONTAGE_ON = SimpleNamespace(
    montage_enabled=True, montage_shot_seconds=4.0, montage_max_shots_per_scene=3
)


@pytest.fixture
def rules() -> pauses.PauseRules:
    return pauses.load_rules()


def _voice(median: float, p25_words_per_second: float, sentence: float) -> dict[str, Any]:
    """One voice's measured numbers in the derived cache's own shape, past min_samples."""
    return {
        "pool": "character",
        "takes": 9,
        "words": 90,
        "speech_seconds": round(90 * median, 3),
        "classes": {
            "SENTENCE": {"median": sentence, "p25": round(sentence * 0.8, 4), "n": 9},
            "CLAUSE": {"median": 0.2, "p25": 0.15, "n": 9},
            "DASH": {"median": 0.3, "p25": 0.2, "n": 9},
        },
        "rate": {
            "seconds_per_word": median,
            "take_median_seconds_per_word": median,
            "take_median_words_per_second": round(1 / median, 4),
            "take_p25_words_per_second": p25_words_per_second,
        },
    }


def _profiles() -> dict[str, Any]:
    """The pinned pools and two serial voices of their own: a quick one and a slow one."""
    measured = json.loads(json.dumps(PINNED_VOICE_PROFILES))
    measured["voices"] = {
        FAST: _voice(0.29, 3.2, 0.24),
        SLOW: _voice(0.42, 2.0, 0.43),
    }
    return measured


def _views(frozen: pauses.Frozen, rows: list[list[int]], texts: list[str], channel: str):
    """Storyboard rows as `assembler.scene_view` reads them, from a film frozen side by side:
    each row the sides it says (by index), its words, its pauses."""
    views = []
    for number, (owned, text) in enumerate(zip(rows, texts, strict=True), start=1):
        records = [frozen.pauses[i] for i in owned]
        view: dict[str, Any] = {
            "scene_index": number,
            "scene_kind": "LIVE",
            "duration_seconds": 3.0,
            "transition_in": "CUT",
            "voiceover_segment": text,
            "voice_group": None,
            "pause_after": records[-1],
            "inner_pauses": records[:-1],
            "prompt_json": {},
        }
        if number == 1:
            view["pause_profile"] = {**frozen.snapshot, "channel": channel}
        views.append(view)
    return views


# ---------------------------------------------------------- a row said by two voices (1, 9)

SARAH = "I read every letter you sent me and none of them said what you think they said today."
KAEL = "Then read it again."


def test_a_row_said_by_two_voices_is_bought_at_each_voices_own_rate(engine, rules):
    """Finding: a frozen serial row said by Sarah and then by a slow voice was bought as if
    every word were the slow voice's (12.96 s against the one estimate's 9.22 s)."""
    profiles = _profiles()
    lines = [{"speaker": "Sarah", "text": SARAH}, {"speaker": "Kael", "text": KAEL}]
    when = film_length.timing(
        film_length.SERIAL,
        speakers={"Sarah": FAST, "Kael": SLOW},
        rules=rules,
        profiles=profiles,
    )
    expected = film_length.shot_clip_seconds(lines, when=when)

    sides, _runs = pause_plan.serial_row_sides(lines, beat=1)
    sides = [{**side, "voice": {"Sarah": FAST, "Kael": SLOW}[side["speaker"]]} for side in sides]
    frozen = pauses.freeze(
        sides,
        serial=True,
        rules=rules,
        knobs=pauses.channel_pauses("serial", rules),
        profiles=profiles,
        narrator_voice=None,
    )
    assert [record["words"] for record in frozen.pauses] == [18, 4]
    views = _views(frozen, [[0, 1]], [f"{SARAH} {KAEL}"], "serial")
    (plan,) = film_length.frozen_rows(views)
    fast = pauses.voice_profile(FAST, rules=rules, profiles=profiles)
    slow = pauses.voice_profile(SLOW, rules=rules, profiles=profiles)
    assert plan.speech == pytest.approx(
        pauses.speech_seconds(18, fast, high=True) + pauses.speech_seconds(4, slow, high=True),
        abs=0.002,
    )
    with Session(engine) as session:
        asked = assembler.clip_plan(session, "no-such-board", views)[1]
    assert asked["source"] == NARRATION_ESTIMATED
    # The clip the motion plan buys is the one estimate's, never the slowest voice's for all.
    assert asked["seconds"] == pytest.approx(expected, abs=FRAME)
    slowest = assembler._voiced_clip_seconds(
        pauses.speech_seconds(22, slow, high=True), NARRATION_ESTIMATED, 0.0, pause=plan.share
    )
    assert asked["seconds"] < slowest - 1.0


def test_a_row_whose_words_changed_since_the_freeze_is_bought_at_its_slowest_voice(rules):
    profiles = _profiles()
    lines = [{"speaker": "Sarah", "text": SARAH}, {"speaker": "Kael", "text": KAEL}]
    sides, _runs = pause_plan.serial_row_sides(lines, beat=1)
    sides = [{**side, "voice": {"Sarah": FAST, "Kael": SLOW}[side["speaker"]]} for side in sides]
    frozen = pauses.freeze(
        sides,
        serial=True,
        rules=rules,
        knobs=pauses.channel_pauses("serial", rules),
        profiles=profiles,
        narrator_voice=None,
    )
    views = _views(frozen, [[0, 1]], [f"{SARAH} {KAEL} And again."], "serial")
    (plan,) = film_length.frozen_rows(views)
    slow = pauses.voice_profile(SLOW, rules=rules, profiles=profiles)
    assert plan.speech == pauses.speech_seconds(24, slow, high=True)


# ------------------------------------------------------- a rendered reading counted once (2)


def _two_take_row(beat: bool = False):
    """One serial row said in two takes (1.5 s and 1.0 s once trimmed), a turn or a marked
    beat between them, the film's end after."""
    inner = (
        {"class": "BEAT", "seconds": 0.9, "floor": 0.9, "voice_key": "S", "words": 3}
        if beat
        else {"class": "TURN", "seconds": 0.236, "floor": 0.12, "voice_key": "S", "words": 3}
    )
    end = {"class": "END", "seconds": 0.736, "floor": 0.27, "voice_key": "K", "words": 2}
    profile = {
        "knobs": {"cut_in_pause": 1.0, "picture_slide_words": 0},
        "channel": "serial",
        "voices": {},
    }
    scene = {
        "scene_index": 1,
        "duration_seconds": 3.0,
        "voiceover_segment": "One two three. Four five.",
        "scene_kind": "LIVE",
        "pause_after": end,
        "inner_pauses": [inner],
        "pause_profile": profile,
        "voice_group": "b1.1",
    }
    first, second = object(), object()
    parts = [
        (
            [
                {"text": "One two three.", "voice_group": "b1.1", "adapter": first},
                {"text": "Four five.", "voice_group": "b1.2", "adapter": second},
            ],
            True,
        )
    ]
    takes, rows = assembler.voice_takes([scene], parts, [first], grouped=True)
    for take, seconds in zip(takes, (1.5, 1.0), strict=True):
        take.said = SimpleNamespace(duration_seconds=seconds)
        take.trim = {"kept_tail_seconds": 0.04, "kept_head_seconds": 0.03}
        for unit in take.units:
            unit.offset, unit.seconds = 0.0, seconds
    return scene, takes, rows


@pytest.mark.parametrize("beat", [False, True])
def test_a_rendered_reading_adds_back_to_the_span_the_render_cut(rules, beat):
    """Finding: the render's ``audio_seconds`` already held the inner joins and the kept tail,
    and the readers added the row's share of the frozen pauses on top: 3.625 s for a 3.375 s
    span, 1.2 s over with a marked beat inside the row."""
    scene, takes, rows = _two_take_row(beat)
    timing = assembler._lay_out_voice(
        [scene], takes, rows, cut_in_pause=1.0, wall=None, rules=rules
    )
    (span,) = timing.layout.spans
    (reading,) = timing.readings
    assert reading is not None and reading < timing.audio[0]
    lengths = {1: (reading, assembler.NARRATION_RENDERED)}
    assert assembler.expected_shot_spans([scene], lengths)[1] == pytest.approx(span, abs=1e-6)


# ------------------------------------------------------- an interruption is its edges (3)


def test_an_interruption_is_planned_as_the_edges_it_is_heard_as(rules):
    """Finding: an INTERRUPT join was recorded planned 0.0 and heard as the kept edges (0.11 s),
    and quality control called it dead air (limit 0 x 1.2 + a frame)."""
    interrupt = {"class": "INTERRUPT", "seconds": 0.0, "floor": 0.0, "voice_key": "S"}
    end = {"class": "END", "seconds": 0.736, "floor": 0.27, "voice_key": "K"}
    scene = {
        "scene_index": 1,
        "duration_seconds": 3.0,
        "voiceover_segment": "I was going to say— No.",
        "scene_kind": "LIVE",
        "pause_after": end,
        "inner_pauses": [interrupt],
        "pause_profile": {"knobs": {"cut_in_pause": 1.0}, "channel": "serial", "voices": {}},
        "voice_group": "b1.1",
    }
    first, second = object(), object()
    parts = [
        (
            [
                {"text": "I was going to say—", "voice_group": "b1.1", "adapter": first},
                {"text": "No.", "voice_group": "b1.2", "adapter": second},
            ],
            True,
        )
    ]
    takes, rows = assembler.voice_takes([scene], parts, [first], grouped=True)
    for take, seconds in zip(takes, (1.5, 0.6), strict=True):
        take.said = SimpleNamespace(duration_seconds=seconds)
        take.trim = {"kept_tail_seconds": 0.08, "kept_head_seconds": 0.03}
        for unit in take.units:
            unit.offset, unit.seconds = 0.0, seconds
    timing = assembler._lay_out_voice(
        [scene], takes, rows, cut_in_pause=1.0, wall=None, rules=rules
    )
    (record,) = timing.pauses[0]["inner"]
    assert record["class"] == pauses.INTERRUPT
    assert record["planned"] == pytest.approx(0.11) == pytest.approx(record["heard"])
    production = {
        "timeline": {
            "fps": TIMELINE_FPS,
            "pause_profile": {"limits": {"dead_air_tolerance": 0.2, "join_ceiling_seconds": 1.2}},
            "spans": [{"scene_index": 1, "pause": timing.pauses[0]}],
        }
    }
    joins = qc._frozen_joins(production)
    at = record["cut_at"]
    limit, planned = qc._frozen_limit(at - record["heard"], at, joins, production)
    assert planned == pytest.approx(0.11) and limit > record["heard"]


# ---------------------------------------------------- the render's room and cut_in_pause (4)


def test_the_renders_room_is_never_more_than_the_share_of_the_pause_the_row_holds(rules):
    """Finding: with cut_in_pause 0.1 the outgoing row held 0.08 s of the pause but the render
    could take 0.32 s off it, the cut landing inside its last word, while the sheet said one
    frame."""
    paragraph = {"class": "PARAGRAPH", "seconds": 0.736, "floor": 0.419, "voice_key": None}
    end = {"class": "END", "seconds": 0.736, "floor": 0.27, "voice_key": None}
    profile = {"knobs": {"cut_in_pause": 0.1}, "channel": "factual", "voices": {}}
    first = {
        "scene_index": 1,
        "duration_seconds": 3.0,
        "voiceover_segment": "One two three.",
        "scene_kind": "LIVE",
        "pause_after": paragraph,
        "inner_pauses": [],
        "voice_group": "s1",
        "pause_profile": profile,
    }
    second = {**first, "scene_index": 2, "voiceover_segment": "Four five six."}
    second.update(pause_after=end, voice_group="s2")
    second.pop("pause_profile")
    voice = object()
    parts = [([{"text": "One two three."}], False), ([{"text": "Four five six."}], False)]
    takes, rows = assembler.voice_takes([first, second], parts, [voice, voice], grouped=True)
    for take in takes:
        take.said = SimpleNamespace(duration_seconds=2.0)
        take.trim = {"kept_tail_seconds": 0.05, "kept_head_seconds": 0.03}
        for unit in take.units:
            unit.offset, unit.seconds = 0.0, 2.0
    timing = assembler._lay_out_voice(
        [first, second], takes, rows, cut_in_pause=0.1, wall=None, rules=rules
    )
    # The row holds the take (its kept tail inside it) and a tenth of the pad: no more than
    # that tenth may go, or the cut would fall before the take's end, inside its last word.
    assert timing.room[0] <= 0.1 * timing.layout.pads[0] + 1e-9
    assert timing.room[0] <= timing.layout.spans[0] - 2.0 + 1e-9
    assert timing.room[0] == pytest.approx(film_length.frozen_rows([first, second])[0].room)


# --------------------------------------------------------------- a mark in its own beat (5)


def test_a_mark_before_a_beats_first_line_is_counted_in_that_beat(rules):
    """Finding: a «(beat)» before the first line of beat 2 was counted in beat 1 and dropped
    when beat 1 had a mark of its own; the storyboard's lines had kept both."""
    beats = [
        [
            {"speaker": "Kael", "text": "The render is late.", "pause_at": "end"},
            {"speaker": "Sarah", "text": "Then fix it."},
        ],
        [
            {"speaker": "Sarah", "text": "Well?", "pause_at": "start"},
            {"speaker": "Kael", "text": "It is fixed."},
        ],
    ]
    lines = pause_plan.serial_lines(beats, ["setup", "turn"], rules)
    assert lines[0][0].get("mark_after") and lines[1][0].get("mark_before")
    sides = []
    for number, said in enumerate(lines, start=1):
        found, _runs = pause_plan.serial_row_sides(said, beat=number)
        sides += found
    frozen = pauses.freeze(
        sides,
        serial=True,
        rules=rules,
        knobs=pauses.channel_pauses("serial", rules),
        profiles=PINNED_VOICE_PROFILES,
        narrator_voice=None,
    )
    classes = [record["class"] for record in frozen.pauses]
    assert classes == [pauses.BEAT, pauses.BEAT, pauses.TURN, pauses.END]
    assert not any(record.get("mark_dropped") for record in frozen.pauses)


# -------------------------------------------- a kept take read to its trimmed end (6, 12)


def test_a_kept_take_is_read_to_its_last_letter_never_to_the_vendors_end_of_file():
    """Finding: a take kept but not yet rendered was read to the vendor's end of file (6.06 s
    for babcf272 scene 3, whose final "." the vendor stretches over 0.98 s), and its frozen
    pause added on top: 1.07 s of clip bought beyond what the render cuts."""
    from app.media.toolchain import EDGE_KEEP_SECONDS

    fixture = Path(__file__).parent / "fixtures" / "pauses" / "babcf272_scene_03.mp3.json"
    kept = json.loads(fixture.read_text(encoding="utf-8"))
    text = " ".join("".join(kept["raw_response"]["alignment"]["characters"]).split())
    alignment = pauses.alignment_of(kept["raw_response"])
    letter = pauses.last_letter_times(alignment)
    tokens = pauses.alignment_tokens(alignment)
    head = max(0.0, tokens[0].start - EDGE_KEEP_SECONDS)
    (piece,) = assembler._take_pieces(kept, [text], float(kept["duration_seconds"]), 1.0)
    assert piece[0] == pytest.approx(letter[1] + EDGE_KEEP_SECONDS - head, abs=0.002)
    assert piece[0] < float(kept["duration_seconds"]) - 0.9
    assert piece[0] == piece[1]


# --------------------------------------------------- an L-cut's words are the shot's own (7)


def test_an_l_cuts_words_are_the_outgoing_shots_captions_and_clip(rules):
    """Finding: with picture_slide_words 1 the cut moved onto "it", but "Then" stayed in the
    next row's captions at 0.0 s, and the outgoing row's clip was bought without it."""
    units = ["The probe slept.", "Then it woke."]
    words, clock = [], 0.1
    for word in " ".join(units).split():
        words.append(pause_plan.Word(word, clock, clock + 0.3, clock, clock + 0.3))
        clock += 0.3 + (0.4 if word.endswith(".") else 0.02)
    cuts = pause_plan.take_cuts(units, 3.0, words, cut_in_pause=1.0, picture_slide_words=1)
    assert cuts.offsets[1] == pytest.approx(words[4].first)  # on "it"
    assert [w["word"] for w in cuts.words[0]] == ["The", "probe", "slept.", "Then"]
    assert [w["word"] for w in cuts.words[1]] == ["it", "woke."]
    assert cuts.words[1][0]["start"] == pytest.approx(0.0)
    assert all(w["end"] > w["start"] for unit in cuts.words for w in unit if unit)
    assert pause_plan.slid_units(units, [False, True], 1) == ["The probe slept. Then", "it woke."]
    assert pause_plan.slid_units(units, [False, False], 1) == units
    assert pause_plan.slid_units(["One.", "Two."], [False, True], 3) == ["One.", "Two."]


def test_the_estimate_counts_an_l_cuts_words_on_the_outgoing_row(rules, monkeypatch):
    from test_pause_freeze import LONG

    rows = film_length.factual_rows(
        [{"narration": LONG, "kind": "LIVE", "purpose": "HOOK"}], settings=MONTAGE_ON
    )
    assert len(rows) >= 2
    plain = film_length.timing(film_length.FACTUAL, rules=rules, profiles=PINNED_VOICE_PROFILES)
    knobs = pauses.ChannelPauses(1.0, 1.0, 2, pauses.PARAGRAPH, "test")
    slid = film_length.Timing(
        rules=rules, knobs=knobs, profiles=PINNED_VOICE_PROFILES, channel=film_length.FACTUAL
    )
    before = film_length.factual_clips(rows, when=plain)
    after = film_length.factual_clips(rows, when=slid)
    assert after[1] > before[1] and after[len(rows)] < before[len(rows)]


# ----------------------------------------------- a paid take is never bought again (8)


@requires_ffmpeg
@pytest.mark.montage
@pytest.mark.parametrize("change", ["voice_groups_off", "rules_off", "rules_unreadable"])
def test_a_film_voiced_in_groups_keeps_its_paid_takes_when_the_rules_change(
    engine, tmp_path, monkeypatch, change
):
    """Finding: whether a film was laid out by its frozen pauses and said in its voice groups
    was read from the rules as they are now, so switching the groups or the rules off (or a
    file that no longer reads) re-voiced it row by row and paid the vendor again."""
    from test_pause_freeze import LONG, _factual_board, _scene
    from test_pause_render import SpacedVoice, _render

    ending = "Reserved on purpose, by the registry."
    board = _factual_board(engine, [_scene(1, "HOOK", LONG), _scene(2, "ENDING", ending)])
    first = SpacedVoice()
    _render(engine, board, first, tmp_path)
    assert first.heard == [LONG, ending]

    changed = tmp_path / "pause_rules.json"
    if change == "rules_unreadable":
        changed.write_text("{ not json", encoding="utf-8")
    else:
        data = json.loads(pauses.RULES_FILE.read_text(encoding="utf-8"))
        if change == "voice_groups_off":
            data["switches"]["voice_groups"]["value"] = False
        else:
            data["use_until_the_owner_changes_it"] = False
        changed.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(pauses, "RULES_FILE", changed)

    assert narration_to_buy(engine, board, tts_adapter=SpacedVoice()) == 0
    again = SpacedVoice()
    render = _render(engine, board, again, tmp_path / "again")
    assert again.heard == []
    # Laid out by its own frozen pauses still, not the legacy breath.
    timeline = render["production"]["timeline"]
    assert "spoken_tail_seconds" not in timeline
    assert all(isinstance(span.get("pause"), dict) for span in timeline["spans"])


# --------------------------------------------------------------- the wall enforced (10)


def _channel_max(engine, kind: str, seconds: int) -> None:
    from app.publishing.models import ChannelRecord
    from app.publishing.services import seed_default_channels
    from sqlalchemy import select

    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        channels = list(
            session.scalars(select(ChannelRecord).where(ChannelRecord.channel_type == kind))
        )
        assert channels, kind
        for channel in channels:
            channel.shorts_max_seconds = seconds


@requires_ffmpeg
def test_a_film_frozen_over_its_wall_buys_no_still_no_clip_and_no_render(engine, tmp_path):
    """Finding: freeze_rows recorded fits=false and nothing read it: the stills, the voice and
    every clip were bought for a film quality control then refused at the wall."""
    from app.media.models import StoryboardScene
    from sqlalchemy import select
    from test_motion import StubImages
    from test_pause_freeze import LONG, _factual_board, _scene
    from test_pause_render import SpacedVoice, _render

    _channel_max(engine, "MAIN_FACTUAL", 12)
    board = _factual_board(
        engine,
        [_scene(1, "HOOK", LONG), _scene(2, "ENDING", "Reserved on purpose, by the registry.")],
    )
    with Session(engine) as session:
        views = [
            assembler.scene_view(row)
            for row in session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board)
                .order_by(StoryboardScene.scene_index)
            )
        ]
    profile = film_length._profile_of(views)
    assert profile["wall"]["fits"] is False and profile["wall"]["wall"] == 12.0
    refusal = film_length.wall_refusal(views)
    assert refusal and "zidul de 12 s" in refusal

    images = StubImages()
    bought = assembler.buy_stills(
        engine, board, "c", image_chain=[images], storage_root=tmp_path / "media"
    )
    assert all(entry["status"] in ("not_bought", "composed") for entry in bought["scenes"])
    assert all(entry.get("reason") == refusal for entry in bought["scenes"] if entry.get("reason"))

    voice = SpacedVoice()
    with pytest.raises(assembler.FilmOverTheWall):
        _render(engine, board, voice, tmp_path)
    assert voice.heard == []

    state = {"plan": {"plan_hash": "x", "lint_blocked": False}, "scenes": views}
    with pytest.raises(assembler.MotionStepRefused) as refused:
        assembler._refuse_before_buying(
            engine,
            state,
            assembler.MOTION_STEP,
            "x",
            environment="TEST",
            plan_hash_of=None,
            storyboard_id=board,
        )
    assert refused.value.status == assembler.OVER_THE_WALL


@requires_ffmpeg
def test_a_voice_measured_past_the_wall_stops_the_render_before_the_motion_pass(
    engine, tmp_path, monkeypatch
):
    """The film fitted when it was frozen, but its voice, measured, is longer than the wall
    even with every pause at its floor: the render stops there, before any clip."""
    from test_pause_freeze import _factual_board, _scene
    from test_pause_render import SpacedVoice, _render

    _channel_max(engine, "MAIN_FACTUAL", 12)
    words = "One registry keeps a list of names nobody may buy."
    board = _factual_board(engine, [_scene(1, "HOOK", words), _scene(2, "ENDING", words)])

    class SlowVoice(SpacedVoice):
        async def synthesize(self, text: str, **kwargs: Any):
            # Every word said three times as slowly as the estimate's: no pause can make up.
            return await super().synthesize(" ".join(w for w in text.split() for _ in range(3)))

    voice = SlowVoice()
    with pytest.raises(assembler.FilmOverTheWall) as refused:
        _render(engine, board, voice, tmp_path)
    assert "măsurat cu vocea înregistrată" in str(refused.value)
    assert len(voice.heard) == 2


# ------------------------------------------------- the serial review's wall is its channel's (11)


def test_the_serial_review_holds_an_episode_to_its_channels_own_wall(engine, rules):
    """Finding: the serial review held every episode to 180 s while its storyboard was frozen
    and its render fitted under the OFFICE_SERIAL channel's own maximum (say 150 s)."""
    from app.story import review

    _channel_max(engine, "OFFICE_SERIAL", 150)
    with Session(engine) as session:
        when = film_length.timing(film_length.SERIAL, rules=rules, profiles=PINNED_VOICE_PROFILES)
        wall = review._serial_wall(session, when)
        assert wall == 150.0 == pause_plan.channel_wall(session, "OFFICE_SERIAL", rules)
    film = film_length.FilmLength(
        seconds=165.0, rows=40, speaking_rows=40, spoken_seconds=150.0, wall_seconds=170.0
    )
    beats = [{"part": "hook"}] * 6
    held = review._length(beats, 100.0, film, when, wall)
    assert held["passed"] is False and held["ceiling_seconds"] == 150.0
    assert review._length(beats, 100.0, film, when)["passed"] is True  # the old 180 s wall


# ------------------------------------------------------------- nothing hard-coded (13)


def test_the_reviews_wall_is_the_rules_cap_and_qc_reads_the_films_own_limits(tmp_path):
    """Finding: the reviews' wall was a code constant beside the rules' cap, and quality
    control fell back to typed literals (0.2, 1.2, 1/24) when the rules could not be read."""
    data = json.loads(pauses.RULES_FILE.read_text(encoding="utf-8"))
    data["studio"]["wall_cap_seconds"]["value"] = 175.0
    capped = pauses.parse_rules(data)
    when = film_length.Timing(rules=capped, channel=film_length.FACTUAL)
    assert film_length.review_ceiling_seconds(180.0, when) == 175.0
    assert film_length.review_ceiling_seconds(150.0, when) == 150.0

    production = {
        "timeline": {
            "fps": 25,
            "pause_profile": {"limits": {"dead_air_tolerance": 0.5, "join_ceiling_seconds": 1.6}},
            "spans": [
                {"scene_index": 1, "pause": {"class": "SENTENCE", "planned": 0.4, "cut_at": 2.0}}
            ],
        }
    }
    assert qc._silence_limits(production) == (0.5, 1.6, 1 / 25)
    joins = qc._frozen_joins(production)
    limit, planned = qc._frozen_limit(1.7, 2.0, joins, production)
    assert planned == 0.4 and limit == pytest.approx(0.4 * 1.5 + 1 / 25)
    assert qc._frozen_limit(5.0, 5.3, joins, production) == (1.6, None)


def test_without_its_limits_or_readable_rules_a_film_is_read_as_a_legacy_one(tmp_path, monkeypatch):
    broken = tmp_path / "pause_rules.json"
    broken.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(pauses, "RULES_FILE", broken)
    production = {
        "timeline": {
            "fps": 24,
            "spans": [
                {"scene_index": 1, "pause": {"class": "SENTENCE", "planned": 0.4, "cut_at": 2.0}}
            ],
        }
    }
    assert qc._silence_limits(production) is None
    assert qc._frozen_joins(production) is None


def test_a_freeze_keeps_the_switches_and_the_limits_it_was_made_under(rules):
    frozen = pauses.freeze(
        [{"text": "One short scene.", "scene": 1, "purpose": "HOOK", "take": "s1"}],
        serial=False,
        rules=rules,
        knobs=pauses.channel_pauses("factual", rules),
        profiles=PINNED_VOICE_PROFILES,
        narrator_voice=None,
    )
    assert frozen.snapshot["switches"]["trim_to_last_letter"] is True
    assert frozen.snapshot["limits"] == {
        "dead_air_tolerance": rules.dead_air_tolerance,
        "join_ceiling_seconds": rules.join_ceiling_seconds,
    }


# ------------------------------------------------- the pause an in-take shot holds (14)


@pytest.mark.montage
def test_a_shot_cut_inside_its_take_is_bought_for_the_voices_own_pause_it_holds(rules):
    """Finding: a montage row cut inside its writer's scene was bought for its words alone
    (0.371 s a word, measured), yet under cut_in_pause 1.0 its shot holds the voice's own
    pause at the cut: 0.47 s at a full stop; one real row became a paid redo."""
    from test_pause_freeze import LONG

    rows = film_length.factual_rows(
        [{"narration": LONG, "kind": "LIVE", "purpose": "HOOK"}], settings=MONTAGE_ON
    )
    when = film_length.timing(film_length.FACTUAL, rules=rules, profiles=PINNED_VOICE_PROFILES)
    sides = film_length.factual_sides(rows, when)
    frozen = film_length._frozen(sides, when, serial=False)
    first = frozen.pauses[0]
    assert first["class"] == pauses.IN_TAKE and first["fallback"]["seconds"] > 0
    holds = film_length.in_take_holds(frozen.pauses, 1.0, 0)
    assert holds[0] == pytest.approx(first["fallback"]["seconds"])
    clips = film_length.factual_clips(rows, when=when)
    voice = film_length.voice_of(sides[0], when)
    words = pauses.speech_seconds(rows[0]["narration"], voice, high=True, margin=0.10)
    assert clips[1] >= words + first["fallback"]["seconds"] - 1e-6
    # At 0.1 most of the pause is the next shot's.
    shifted = film_length.in_take_holds(frozen.pauses, 0.1, 0)
    assert shifted[0] == pytest.approx(0.1 * first["fallback"]["seconds"], abs=1e-4)
    assert shifted[1] >= 0.9 * first["fallback"]["seconds"] - 1e-4


# ------------------------------------- the sheet gives up a pause only as the render does (15)


def test_a_pause_is_given_up_only_for_a_clip_that_cannot_be_slowed_into_its_span():
    """Finding: the sheet took every pause's room off every span; the render gives it up only
    for a clip past the 25% slow-down, so the sheet said 10% where the film was slowed 18%."""
    span, room = 5.917, 0.417
    assert clip_fits(5.0, span)
    assert pause_plan.shrink_frames(5.0, span, room, TIMELINE_FPS, clip_fits) == 0
    need = 5.0 * 1.25 + 3 * FRAME
    frames = pause_plan.shrink_frames(4.99, need, room, TIMELINE_FPS, clip_fits)
    assert 0 < frames <= 10
    # A span laid on the timeline is rounded to the microsecond (154 frames: 6.416667 s): it
    # gives up the 4 frames a 5 s clip needs, never a 5th for the rounding.
    assert pause_plan.shrink_frames(5.0, 6.416667, room, TIMELINE_FPS, clip_fits) == 4


@pytest.mark.parametrize(
    ("have", "how", "given"),
    [(5.2, "slowed", None), (5.0, "slowed", True), (4.0, None, None)],
)
def test_the_sheet_reads_a_clip_against_its_whole_span_and_the_room_only_when_needed(
    engine, monkeypatch, have, how, given
):
    span, room = 5.0 * 1.25 + 3 * FRAME, 10 * FRAME
    shot = SimpleNamespace(id="take-1", seconds=have)
    monkeypatch.setattr(
        assembler, "_shot_take", lambda s, b, i, f, least: shot if least <= have + 1e-9 else None
    )
    monkeypatch.setattr(assembler, "shot_clip_seconds", lambda take: take.seconds)
    monkeypatch.setattr(assembler, "clip_accepted", lambda s, take, env: (True, ""))
    monkeypatch.setattr(assembler, "_scene_clip_refusal", lambda s, b, i: ("", None))
    with Session(engine) as session:
        reading = assembler.clip_readiness(
            session,
            "board",
            {"scene_index": 1, "scene_kind": "LIVE", "prompt_json": {}},
            "sha",
            span=span,
            environment="TEST",
            room=room,
        )
    assert reading["span"] == pytest.approx(span, abs=1e-3)
    if how is None:
        assert reading["ok"] is False and reading["code"] == assembler.CLIP_SHORT
        return
    assert reading["ok"] is True and reading["how"] == how
    if given:
        frames = pause_plan.shrink_frames(have, span, room, TIMELINE_FPS, clip_fits)
        assert reading["pause_given_seconds"] == pytest.approx(frames * FRAME, abs=1e-4)
        assert reading["slowed_by"] == pytest.approx((span - frames * FRAME) / have, abs=1e-3)
    else:
        assert reading["pause_given_seconds"] is None
        assert reading["slowed_by"] == pytest.approx(span / have, abs=1e-3)


# ------------------------------------------- a paragraph is the larger voice's (20)


def test_a_paragraph_is_the_ratio_times_the_larger_of_the_two_voices_pauses(rules):
    """Finding: nothing tested that PARAGRAPH takes the LARGER of the two voices' pauses: a
    beat end from Sarah into the narrator would have planned 0.376 s instead of 0.767 s."""
    profiles = _profiles()
    knobs = pauses.channel_pauses("serial", rules)
    narrator = pauses.voice_profile(None, rules=rules, profiles=profiles)
    quick = pauses.voice_profile(FAST, rules=rules, profiles=profiles)
    assert quick.sentence.median < narrator.sentence.median
    out_quick = pauses.target(
        pauses.PARAGRAPH, out=quick, inn=narrator, narrator=narrator, knobs=knobs, rules=rules
    )
    into_quick = pauses.target(
        pauses.PARAGRAPH, out=narrator, inn=quick, narrator=narrator, knobs=knobs, rules=rules
    )
    larger = rules.paragraph_ratio * narrator.sentence.median
    assert out_quick == pytest.approx(round(min(larger, rules.join_ceiling_seconds), 3))
    assert into_quick == out_quick
    # Frozen at a beat's end from Sarah to the narrator: the narrator's (larger) pause.
    sides = [
        {"text": "Fine.", "scene": 1, "speaker": "Sarah", "voice": FAST, "take": "b1.1"},
        {"text": "Later that night.", "scene": 2, "speaker": None, "voice": None, "take": "b2.1"},
    ]
    frozen = pauses.freeze(
        sides,
        serial=True,
        rules=rules,
        knobs=knobs,
        profiles=profiles,
        narrator_voice=None,
    )
    assert frozen.pauses[0]["class"] == pauses.PARAGRAPH
    assert frozen.pauses[0]["seconds"] == pytest.approx(out_quick)
