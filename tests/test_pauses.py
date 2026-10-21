"""«Pauza vocii» (the Owner, 2026-10-16): the silence at every cut is the pause this voice makes
at this kind of boundary, and the take is trimmed to its last letter so the planned pause is the
silence heard.

Measured before (the 55 kept ElevenLabs takes of 8 films): the trim cut 0.000 s from every take
(the vendor stretches the final "." to the end of its file and its clock vetoed the meter), and
0.4 s was added after every shot on top of the vendor's own 0.27-0.77 s, at every cut, even
between two words. These tests hold the rules (`app.media.pauses`, config/pause_rules.json), the
per-voice profile measured from the kept takes' sidecars, the trim on two real takes kept as
fixtures (tests/fixtures/pauses: Sarah's "Read it to me anyway, Marcus." and babcf272 scene 3),
the pads, the ladder's order and the wall. Nothing here calls a model or a vendor.
"""

from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path
from typing import Any

import pytest
from app.config import ROOT
from app.media import pauses
from app.media.assembler import _trimmed_take, spoken_words
from app.media.toolchain import EDGE_KEEP_SECONDS, SILENCE_THRESHOLD_DB, find_ffmpeg
from app.providers.media_base import TTSResult

FIXTURES = Path(__file__).parent / "fixtures" / "pauses"
FFMPEG = find_ffmpeg()
requires_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is not installed")

NARRATOR_ID = "CwhRBWXzGAHq8TQ4Fs17"
SARAH_ID = "EXAVITQu4vr4xnSDxMaL"


@pytest.fixture
def rules() -> pauses.PauseRules:
    return pauses.load_rules()


@pytest.fixture
def knobs(rules) -> pauses.ChannelPauses:
    return pauses.channel_pauses("factual", rules, look={})


def _rules_with(tmp_path: Path, **changes) -> Path:
    """A copy of the shipped rules with top-level keys or switches changed."""
    data = json.loads(pauses.RULES_FILE.read_text(encoding="utf-8"))
    for name, value in changes.items():
        if name in data["switches"]:
            data["switches"][name]["value"] = value
        else:
            data[name] = value
    path = tmp_path / "pause_rules.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _sidecar(
    voice_id: str,
    words: list[tuple[str, float]],
    *,
    letter: float = 0.07,
    model: str = "eleven_flash_v2",
    normalized_gap: float | None = None,
) -> dict:
    """A kept take's sidecar as `assembler.keep_narration` writes it: each letter ``letter``
    long, each word followed by its gap (seconds from its last letter to the next first)."""

    def timed(gap_scale: float | None) -> dict:
        chars, starts, ends = [], [], []
        clock = 0.0
        for index, (word, gap) in enumerate(words):
            if index:
                chars.append(" ")
                starts.append(clock)
                ends.append(clock)
            for char in word:
                chars.append(char)
                starts.append(clock)
                if char.isalnum():
                    clock += letter
                ends.append(clock)
            clock += gap if gap_scale is None else gap_scale
        return {
            "characters": chars,
            "character_start_times_seconds": starts,
            "character_end_times_seconds": ends,
        }

    raw = {
        "provider": "ELEVENLABS",
        "model": model,
        "voice_id": voice_id,
        "alignment": timed(None),
    }
    if normalized_gap is not None:
        raw["normalized_alignment"] = timed(normalized_gap)
    return {"format": "mp3", "duration_seconds": 1.0, "raw_response": raw}


def _sentences(count: int, gap: float) -> list[tuple[str, float]]:
    """``count`` sentence boundaries, each ``gap`` long, inside one take."""
    words: list[tuple[str, float]] = []
    for index in range(count + 1):
        words += [("one", 0.04), ("two", 0.04), (f"three{index}.", gap)]
    return words


# ------------------------------------------------------------------------------------ the rules


def test_the_rules_file_is_a_proposal_with_a_source_for_every_research_constant(rules):
    data = json.loads(pauses.RULES_FILE.read_text(encoding="utf-8"))
    assert data["status"] == "PROPOSED"
    assert data["use_until_the_owner_changes_it"] is True
    for name, entry in data["research"].items():
        assert entry.get("source"), name
    for name, entry in data["studio"].items():
        if name == "beat_marks":
            assert all(mark.get("why") for mark in entry.values())
        else:
            assert entry.get("why"), name
    assert rules.paragraph_ratio == 1.565
    assert rules.turn_seconds == 0.236
    assert rules.turn_floor_seconds == 0.12
    assert (rules.beat_floor_seconds, rules.beat_ceiling_seconds) == (0.7, 1.2)
    assert rules.join_ceiling_seconds == 1.2
    assert rules.wall_cap_seconds == 180.0
    assert rules.switch("trim_to_last_letter")
    assert not rules.switch("per_take_tempo")


def test_rules_not_in_use_or_missing_leave_the_legacy_timing(tmp_path):
    off = _rules_with(tmp_path, use_until_the_owner_changes_it=False)
    assert pauses.active_rules(off) is None
    assert not pauses.switch("trim_to_last_letter", off)
    with pytest.raises(pauses.PauseRulesError):
        pauses.load_rules(tmp_path / "missing.json")
    assert pauses.active_rules(tmp_path / "missing.json") is None


def test_the_channel_knobs_come_from_the_look_files_over_the_rules_defaults(rules):
    for channel in ("factual", "serial"):
        knobs = pauses.channel_pauses(channel, rules)
        assert (knobs.tempo, knobs.cut_in_pause, knobs.picture_slide_words) == (1.0, 1.0, 0)
        assert knobs.end_class == "PARAGRAPH"
        assert knobs.source == f"{channel} look"
    brisk = pauses.channel_pauses("factual", rules, look={"pauses": {"tempo": 0.85}})
    assert brisk.tempo == 0.85 and brisk.end_class == "PARAGRAPH"
    # A knob the look file gets wrong is never used: the defaults are.
    broken = pauses.channel_pauses("serial", rules, look={"pauses": {"cut_in_pause": 3}})
    assert broken.source == "rules" and broken.cut_in_pause == 1.0


# -------------------------------------------------------------------------------- the classifier


def _f(text, scene, purpose="DEVELOPMENT", **extra):
    return {"text": text, "scene": scene, "purpose": purpose, **extra}


FACTUAL_CASES = [
    # (out, inn, class, base)
    (_f("It froze.", 1), _f("Then it thawed.", 2), "SENTENCE", "SENTENCE"),
    (_f("It froze.", 1, "HOOK"), _f("Then it thawed.", 2, "SETUP"), "PARAGRAPH", "PARAGRAPH"),
    # The body alternates DEVELOPMENT and EVIDENCE scene by scene: no new section.
    (_f("It froze.", 1), _f("A log says so.", 2, "EVIDENCE"), "SENTENCE", "SENTENCE"),
    (_f("It froze.", 1, "EVIDENCE"), _f("So it ends.", 2, "PAYOFF"), "PARAGRAPH", "PARAGRAPH"),
    # The writer's mark at a scene's end: a real silence.
    (_f("And then…", 1), _f("It moved.", 2), "BEAT", "SENTENCE"),
    (_f("And then...", 1, "SETUP"), _f("It moved.", 2, "REVEAL"), "BEAT", "PARAGRAPH"),
    # A montage cut inside one take adds nothing.
    (_f("It froze and", 1, take="t1"), _f("then it thawed.", 1, take="t1"), "IN_TAKE", "IN_TAKE"),
    # Rows voiced one by one (no timestamps): the punctuation.
    (_f("It froze,", 1), _f("then it thawed.", 1), "CLAUSE", "CLAUSE"),
    (_f("It froze —", 1), _f("then it thawed.", 1), "DASH", "DASH"),
    (_f("It froze and", 1), _f("then it thawed.", 1), "WORD", "WORD"),
    # A title's stop ends no sentence.
    (_f("signed by Dr.", 1), _f("Ellen Harper.", 1), "WORD", "WORD"),
    (_f("It froze.", 1), {"text": "", "kind": "BLACK", "scene": 2}, "CARD", "CARD"),
    (_f("It froze.", 1), None, "END", "END"),
    # A legacy row with no tag: its punctuation.
    ({"text": "It froze."}, {"text": "Then it thawed."}, "SENTENCE", "SENTENCE"),
]


@pytest.mark.parametrize(("out", "inn", "cls", "base"), FACTUAL_CASES)
def test_factual_boundaries_are_classed_from_the_top(rules, out, inn, cls, base):
    found = pauses.boundary_class(out, inn, serial=False, rules=rules)
    assert (found.cls, found.base) == (cls, base)
    assert found.marked == (cls == "BEAT")


def _s(text, speaker, beat=1, **extra):
    return {"text": text, "speaker": speaker, "scene": beat, **extra}


SERIAL_CASES = [
    (_s("Fine.", "Sarah"), _s("Really?", "Marcus"), "TURN", "TURN"),
    (_s("Wait, I —", "Sarah"), _s("No.", "Marcus"), "INTERRUPT", "INTERRUPT"),
    (_s("Fine.", "Sarah"), _s("Really?", "Sarah"), "SENTENCE", "SENTENCE"),
    (_s("Fine.", "Sarah", 1), _s("Really?", "Marcus", 2), "PARAGRAPH", "PARAGRAPH"),
    (_s("The office was quiet.", None), _s("Really?", "Marcus"), "PARAGRAPH", "PARAGRAPH"),
    # «(beat)» where it stood: after the line, before the next, or splitting one line in two.
    (_s("Fine.", "Sarah", mark_after=True), _s("Really?", "Marcus"), "BEAT", "TURN"),
    (_s("Fine.", "Sarah"), _s("Really?", "Marcus", mark_before=True), "BEAT", "TURN"),
    (_s("Fine.", "Sarah", mark_after=True), _s("Do it.", "Sarah"), "BEAT", "SENTENCE"),
    # No position known: the direction of the line before.
    (_s("Fine.", "Sarah", direction="beat"), _s("Really?", "Marcus"), "BEAT", "TURN"),
    (_s("Fine.", "Sarah", direction="a long pause"), _s("No.", "Marcus"), "BEAT", "TURN"),
    (_s("Fine.", "Sarah", direction="dryly"), _s("Really?", "Marcus"), "TURN", "TURN"),
    # An interruption has no gap, marked or not.
    (_s("Wait —", "Sarah", mark_after=True), _s("No.", "Marcus"), "INTERRUPT", "INTERRUPT"),
    # Never a pause before a punchline.
    (_s("Fine.", "Sarah", mark_after=True), _s("Ha.", "Kael", punchline=True), "TURN", "TURN"),
    (_s("Fine.", "Sarah"), None, "END", "END"),
]


@pytest.mark.parametrize(("out", "inn", "cls", "base"), SERIAL_CASES)
def test_serial_boundaries_are_classed_from_the_top(rules, out, inn, cls, base):
    found = pauses.boundary_class(out, inn, serial=True, rules=rules)
    assert (found.cls, found.base) == (cls, base)


def test_a_mark_before_a_punchline_is_dropped_and_says_why(rules):
    found = pauses.boundary_class(
        _s("Fine.", "Sarah", mark_after=True),
        _s("Ha.", "Kael", punchline=True),
        serial=True,
        rules=rules,
    )
    assert found.marked and found.mark_dropped == "punchline"


def test_marks_are_plain_joins_while_marked_beats_are_switched_off(tmp_path, monkeypatch):
    off = pauses.load_rules(_rules_with(tmp_path, marked_beats=False))
    found = pauses.boundary_class(_f("And then…", 1), _f("It moved.", 2), serial=False, rules=off)
    assert found.cls == "SENTENCE" and not found.marked


# ---------------------------------------------------------------------------------- the profile


def test_the_profile_reads_the_vendors_alignment_never_the_normalized_one(rules):
    sidecar = _sidecar(NARRATOR_ID, _sentences(5, 0.5), normalized_gap=0.05)
    timing = pauses.take_timing(sidecar)
    assert timing is not None
    sentences = [gap for cls, gap in timing.gaps if cls == "SENTENCE"]
    assert sentences == pytest.approx([0.5] * 5)
    # A take with only the normalised timing measures nothing.
    only = _sidecar(NARRATOR_ID, _sentences(5, 0.5), normalized_gap=0.05)
    only["raw_response"].pop("alignment")
    assert pauses.take_timing(only) is None


def test_a_real_sidecar_is_timed_from_its_letters_not_its_stretched_stop():
    sidecar = json.loads((FIXTURES / "babcf272_scene_03.mp3.json").read_text(encoding="utf-8"))
    timing = pauses.take_timing(sidecar)
    assert timing is not None
    assert timing.voice == f"ELEVENLABS:eleven_flash_v2:{NARRATOR_ID}"
    # «In 1964, three separate teams published the same theory simultaneously.»: 1964 is said
    # as three words; the speech ends with the last "y" (5.016 s), not the "." (5.991 s).
    assert (
        timing.words
        == spoken_words("In 1964, three separate teams published the same theory simultaneously.")
        == 12
    )
    alignment = sidecar["raw_response"]["alignment"]
    first = alignment["character_start_times_seconds"][0]
    assert timing.speech_seconds == pytest.approx(5.016 - first, abs=1e-3)
    assert [cls for cls, _ in timing.gaps][:2] == ["WORD", "CLAUSE"]


def test_a_voice_uses_its_own_pause_from_min_samples_else_its_pool_else_the_config(rules):
    assert rules.min_samples == 5
    own = [_sidecar("voice-own", _sentences(5, 0.5))]
    few = [_sidecar("voice-few", _sentences(4, 0.2))]
    profiles = pauses.measure_profiles(own + few, rules=rules)
    mine = pauses.voice_profile(
        "ELEVENLABS:eleven_flash_v2:voice-own", rules=rules, profiles=profiles
    )
    assert (mine.sentence.median, mine.sentence.n, mine.sentence.source) == (0.5, 5, "own")
    # Four samples are too few: the narrator pool (both voices, nine samples) answers.
    pooled = pauses.voice_profile(
        "ELEVENLABS:eleven_flash_v2:voice-few", rules=rules, profiles=profiles
    )
    assert pooled.sentence.source == "pool" and pooled.sentence.n == 9
    assert pooled.sentence.median == pytest.approx(0.5)
    # A character's voice with no takes and a character pool with none: the config's pool.
    stranger = pauses.voice_profile(
        "ELEVENLABS:eleven_flash_v2:new", rules=rules, profiles=profiles, pool="character"
    )
    assert stranger.sentence == rules.fallback["character"]["SENTENCE"]
    assert stranger.sentence.source.startswith("config")
    assert stranger.rate_source == "config"
    nothing = pauses.voice_profile(None, rules=rules, profiles={})
    assert nothing.sentence == rules.fallback["narrator"]["SENTENCE"]


def test_the_character_pool_is_measured_from_the_casts_voices(rules):
    sidecars = [_sidecar(SARAH_ID, _sentences(5, 0.25)), _sidecar("narr", _sentences(5, 0.5))]
    profiles = pauses.measure_profiles(sidecars, rules=rules, characters={SARAH_ID})
    assert profiles["voices"][f"ELEVENLABS:eleven_flash_v2:{SARAH_ID}"]["pool"] == "character"
    assert profiles["pools"]["character"]["classes"]["SENTENCE"]["median"] == pytest.approx(0.25)
    assert profiles["pools"]["narrator"]["classes"]["SENTENCE"]["median"] == pytest.approx(0.5)


def test_the_speech_rate_high_end_is_the_takes_first_quartile_or_the_spread(rules):
    many = [_sidecar("fast", _sentences(1, 0.3), letter=0.05 + 0.005 * i) for i in range(5)]
    two = [_sidecar("slow", _sentences(1, 0.3), letter=0.08) for _ in range(2)]
    profiles = pauses.measure_profiles(many + two, rules=rules)
    fast = pauses.voice_profile("ELEVENLABS:eleven_flash_v2:fast", rules=rules, profiles=profiles)
    rate = profiles["voices"]["ELEVENLABS:eleven_flash_v2:fast"]["rate"]
    assert fast.rate_source == "own"
    assert fast.seconds_per_word_high == pytest.approx(
        1 / rate["take_p25_words_per_second"], abs=1e-4
    )
    assert fast.seconds_per_word_high >= fast.seconds_per_word
    slow = pauses.voice_profile("ELEVENLABS:eleven_flash_v2:slow", rules=rules, profiles=profiles)
    assert slow.rate_source.startswith("own (2 takes")
    assert slow.seconds_per_word_high > slow.seconds_per_word


@pytest.mark.measured_voices
def test_the_profiles_are_cached_beside_the_films_and_measured_again_when_a_take_is_kept(
    tmp_path, rules, monkeypatch
):
    folder = tmp_path / "film-1" / "narration"
    folder.mkdir(parents=True)
    (folder / "scene_01_a.mp3.json").write_text(
        json.dumps(_sidecar(NARRATOR_ID, _sentences(5, 0.5))), encoding="utf-8"
    )
    first = pauses.load_profiles(tmp_path, rules=rules)
    cache = tmp_path / pauses.PROFILE_CACHE_NAME
    assert cache.is_file() and first["takes"] == 1

    def must_not_measure(*_args, **_kwargs):
        raise AssertionError("the cache answers while no take was added")

    monkeypatch.setattr(pauses, "measure_profiles", must_not_measure)
    assert pauses.load_profiles(tmp_path, rules=rules)["key"] == first["key"]
    monkeypatch.undo()
    (folder / "scene_02_b.mp3.json").write_text(
        json.dumps(_sidecar(NARRATOR_ID, _sentences(5, 0.4))), encoding="utf-8"
    )
    second = pauses.load_profiles(tmp_path, rules=rules)
    assert second["takes"] == 2 and second["key"] != first["key"]
    # The cache is derived: never committed.
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert pauses.PROFILE_CACHE_NAME in ignored


@pytest.mark.measured_voices
def test_reading_without_write_leaves_no_cache(tmp_path, rules):
    folder = tmp_path / "film-1" / "narration"
    folder.mkdir(parents=True)
    (folder / "scene_01_a.mp3.json").write_text(
        json.dumps(_sidecar(NARRATOR_ID, _sentences(5, 0.5))), encoding="utf-8"
    )
    assert pauses.load_profiles(tmp_path, rules=rules, write=False)["takes"] == 1
    assert not (tmp_path / pauses.PROFILE_CACHE_NAME).exists()


# ------------------------------------------------------------------------- targets and the ladder


def _voices(rules):
    narrator = pauses.voice_profile("narrator", rules=rules, profiles={})
    character = pauses.voice_profile("sarah", rules=rules, profiles={}, pool="character")
    return narrator, character


def test_the_ladder_keeps_its_order_turn_sentence_paragraph_under_the_ceiling(rules, knobs):
    narrator, sarah = _voices(rules)

    def t(cls, out, inn=None, **extra):
        return pauses.target(
            cls, out=out, inn=inn, narrator=narrator, knobs=knobs, rules=rules, **extra
        )

    turn = t("TURN", sarah, narrator)
    sentence = t("SENTENCE", narrator, narrator)
    paragraph = t("PARAGRAPH", narrator, narrator)
    assert turn < sentence < paragraph <= rules.join_ceiling_seconds
    assert turn == pytest.approx(0.236)
    assert sentence == pytest.approx(0.49)
    assert paragraph == pytest.approx(round(1.565 * 0.49, 3))
    # The end: the narrator's PARAGRAPH pause, the serial's last speaker or not.
    assert t("END", sarah) == paragraph
    # A turn never outlasts the speaker's own sentence pause, nor falls under its floor.
    quick = pauses.VoiceProfile(
        "quick",
        "character",
        pauses.Stat(0.18, 0.1, 9, "own"),
        sarah.clause,
        sarah.dash,
        0.3,
        0.32,
        "own",
    )
    assert t("TURN", quick) == 0.18
    # The writer's beat: 1.4 x the join it lengthens, inside 0.70-1.20.
    assert t("BEAT", sarah, narrator, base="TURN") == 0.7
    assert t("BEAT", narrator, narrator, base="PARAGRAPH") == pytest.approx(
        round(1.4 * paragraph, 3), abs=0.002
    )
    for cls in ("INTERRUPT", "CARD", "WORD", "IN_TAKE"):
        assert t(cls, narrator) == 0.0
    # Two short sentences take the voice's first-quartile pause.
    assert t("SENTENCE", narrator, narrator, short=True) == pytest.approx(0.34)


def test_tempo_scales_every_pause_and_the_ceiling_holds(rules):
    narrator, sarah = _voices(rules)
    slow = pauses.channel_pauses("factual", rules, look={"pauses": {"tempo": 2.0}})
    paragraph = pauses.target(
        "PARAGRAPH", out=narrator, inn=narrator, narrator=narrator, knobs=slow, rules=rules
    )
    assert paragraph == rules.join_ceiling_seconds
    sentence = pauses.target(
        "SENTENCE", out=narrator, inn=None, narrator=narrator, knobs=slow, rules=rules
    )
    assert sentence == pytest.approx(0.98)


def test_the_short_guard_counts_syllables_of_the_two_neighbouring_sentences(rules):
    assert pauses.short_guard("It froze.", "Then it thawed.", rules)
    assert not pauses.short_guard(
        "It froze.", "The telescope's helium ran out in nineteen sixty-four.", rules
    )
    assert pauses.syllables("simultaneously") >= 5


# -------------------------------------------------------------------------- pads and the render


def test_the_pad_makes_the_heard_silence_the_planned_one_and_is_never_negative():
    for target, tail, head in [(0.49, 0.0, 0.03), (0.77, 0.046, 0.03), (0.24, 0.2, 0.08)]:
        pad = pauses.render_pad(target, tail, head)
        assert pad >= 0.0
        heard = tail + pad + head
        assert heard == pytest.approx(max(target, tail + head), abs=1e-4)
    # The vendor's own tail noise is kept, never replaced by digital zero.
    assert pauses.render_pad(0.49, 0.1, 0.0) == pytest.approx(0.39)


def test_cuts_snap_to_frames_on_the_cumulative_timeline_without_drift():
    fps = 24
    spans = [1.0 + 0.013 * (i % 7) for i in range(60)]
    snapped = pauses.snap_cumulative(spans, fps)
    total = 0.0
    exact = 0.0
    for span, cut in zip(spans, snapped, strict=True):
        total += cut
        exact += span
        assert round(total * fps) == pytest.approx(total * fps, abs=1e-6)
        assert abs(total - exact) <= 0.5 / fps + 1e-9
    assert sum(snapped) == pytest.approx(round(sum(spans) * fps) / fps)


def test_a_row_is_bought_for_its_words_and_its_share_of_the_pause(rules):
    narrator, _ = _voices(rules)
    words = 10
    holds = pauses.row_estimate(words, narrator, cut_in_pause=1.0, pause_out=0.77, margin=0.1)
    speech = words * narrator.seconds_per_word_high * 1.1
    assert holds >= speech + 0.77
    assert holds - (speech + 0.77) < 1 / 24 + 1e-6
    shows_first = pauses.row_estimate(words, narrator, cut_in_pause=0.0, pause_in=0.5)
    assert shows_first >= words * narrator.seconds_per_word_high + 0.5


# ----------------------------------------------------------------------------------- the wall


def _joins():
    return [
        {"class": "TURN", "seconds": 0.236, "floor": 0.12},
        {"class": "SENTENCE", "seconds": 0.49, "floor": 0.34},
        {"class": "PARAGRAPH", "seconds": 0.767, "floor": 0.532},
        {"class": "CLAUSE", "seconds": 0.2, "floor": 0.14},
        {"class": "BEAT", "seconds": 0.7, "floor": 0.7},
        {"class": "CARD", "seconds": 0.0, "floor": 0.0},
        {"class": "END", "seconds": 0.767, "floor": 0.34},
    ]


def test_a_film_under_its_wall_keeps_every_pause(rules):
    fit = pauses.fit_to_wall(_joins(), fixed_seconds=100.0, wall=180.0, rules=rules)
    assert fit.seconds == tuple(j["seconds"] for j in _joins())
    assert fit.fits and fit.factors == (1.0, 1.0)


def test_the_wall_compresses_the_row_voiced_pauses_first_then_the_ladder_in_order(rules):
    joins = _joins()
    planned = sum(j["seconds"] for j in joins)
    # Just over: the clause alone gives way.
    fit = pauses.fit_to_wall(joins, fixed_seconds=180.0 - planned + 0.03, wall=180.0, rules=rules)
    assert fit.fits
    assert fit.seconds[3] < 0.2 and fit.seconds[:3] == (0.236, 0.49, 0.767)
    # Further over: the clause at its floor, then one factor for the whole ladder.
    fit = pauses.fit_to_wall(joins, fixed_seconds=180.0 - planned + 0.4, wall=180.0, rules=rules)
    assert fit.fits and fit.total <= 180.0
    turn, sentence, paragraph, clause, beat, card, end = fit.seconds
    assert clause == 0.14
    assert turn < sentence < paragraph
    assert (beat, card) == (0.7, 0.0)  # never compressed
    assert 0 < fit.factors[1] < 1
    # Past every floor: still over, and it says by how much.
    fit = pauses.fit_to_wall(joins, fixed_seconds=180.0, wall=180.0, rules=rules)
    assert not fit.fits and fit.over_seconds > 0
    assert fit.seconds == (0.12, 0.34, 0.532, 0.14, 0.7, 0.0, 0.34)


def test_the_wall_is_the_channel_maximum_never_past_the_cap(rules):
    assert pauses.wall_seconds(160.0, rules) == 160.0
    assert pauses.wall_seconds(240.0, rules) == 180.0
    assert pauses.wall_seconds(None, rules) == 180.0


# --------------------------------------------------------------------------------- the freeze


def _factual_film(scenes: int) -> list[dict]:
    purposes = ["HOOK", "SETUP", "DEVELOPMENT", "EVIDENCE", "DEVELOPMENT", "PAYOFF"]
    sides = []
    for number in range(1, scenes + 1):
        purpose = purposes[min(number - 1, len(purposes) - 1)]
        text = "And the tank ran dry…" if number in (3, 4) else "The tank was full of helium."
        sides.append({"text": text, "scene": number, "purpose": purpose, "voice": "narr"})
    return sides


def test_freeze_plans_every_join_once_a_section_marks_one_beat(rules, knobs):
    frozen = pauses.freeze(
        _factual_film(6),
        serial=False,
        rules=rules,
        knobs=knobs,
        profiles={},
        narrator_voice="narr",
    )
    classes = [record["class"] for record in frozen.pauses]
    # HOOK|SETUP|DEV …|EVI …|DEV|PAYOFF: scenes 3 and 4 both end in «…» inside one section,
    # so only the first becomes a silence.
    assert classes == ["PARAGRAPH", "PARAGRAPH", "BEAT", "SENTENCE", "PARAGRAPH", "END"]
    assert frozen.pauses[3]["mark_dropped"] == "one_per_section"
    assert frozen.pauses[2]["unmarked_class"] == "SENTENCE"
    for record in frozen.pauses:
        assert record["rule_version"] == rules.version
        assert record["voice_key"] == "narr"
        assert 0 <= record["floor"] <= record["seconds"] <= rules.join_ceiling_seconds
    assert frozen.snapshot["rule_version"] == rules.version
    assert frozen.snapshot["knobs"]["tempo"] == 1.0
    assert set(frozen.snapshot["voices"]) == {"narr"}
    estimate = frozen.estimate
    assert estimate.seconds == pytest.approx(
        estimate.speech_seconds + sum(r["seconds"] for r in frozen.pauses)
    )


def test_freeze_under_a_tight_wall_compresses_and_the_estimate_agrees(rules, knobs):
    sides = _factual_film(6)
    free = pauses.freeze(
        sides, serial=False, rules=rules, knobs=knobs, profiles={}, narrator_voice="narr"
    )
    wall = free.estimate.seconds - 0.5
    tight = pauses.freeze(
        sides,
        serial=False,
        rules=rules,
        knobs=knobs,
        profiles={},
        narrator_voice="narr",
        wall=wall,
    )
    assert tight.wall is not None and tight.wall["fits"]
    assert tight.estimate.seconds <= wall
    assert tight.wall["estimate"] == tight.estimate.seconds
    beat = next(r for r in tight.pauses if r["class"] == "BEAT")
    assert "target" not in beat  # a marked silence is never compressed
    assert any("target" in r for r in tight.pauses)


def test_a_card_is_its_own_pause_and_a_legacy_row_has_no_frozen_pause(rules, knobs):
    sides = [
        {"text": "It froze.", "scene": 1, "purpose": "HOOK", "voice": "narr"},
        {"text": "", "scene": 2, "kind": "TITLE_CARD", "card_seconds": 2.5},
        {"text": "Then it thawed.", "scene": 3, "purpose": "SETUP", "voice": "narr"},
    ]
    frozen = pauses.freeze(
        sides, serial=False, rules=rules, knobs=knobs, profiles={}, narrator_voice="narr"
    )
    assert [r["class"] for r in frozen.pauses] == ["CARD", "CARD", "END"]
    assert frozen.estimate.card_seconds == 2.5
    assert pauses.frozen_pause({"scene_number": 1, "shot": 1, "of": 1}) is None
    assert pauses.frozen_pause({"pause_after": frozen.pauses[0]}) == frozen.pauses[0]


# --------------------------------------------------------------------------------- the trim


def _take(name: str) -> TTSResult:
    path = FIXTURES / f"{name}.mp3"
    sidecar = json.loads(Path(f"{path}.json").read_text(encoding="utf-8"))
    return TTSResult(
        audio_bytes=path.read_bytes(),
        format="mp3",
        duration_seconds=float(sidecar["duration_seconds"]),
        sample_rate=int(sidecar["sample_rate"]),
        word_timings=sidecar["word_timings"],
        raw_response=sidecar["raw_response"],
    )


def _decoded(tmp_path: Path, name: str) -> tuple[bytes, Any]:
    wav = tmp_path / f"{name}_full.wav"
    subprocess.run(  # noqa: S603 - argument list, no shell
        [
            FFMPEG,
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(FIXTURES / f"{name}.mp3"),
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s24le",
            str(wav),
        ],
        check=True,
        capture_output=True,
    )
    with wave.open(str(wav), "rb") as audio:
        return audio.readframes(audio.getnframes()), audio.getparams()


@requires_ffmpeg
def test_sarahs_take_keeps_its_final_s(tmp_path):
    said = _take("sarah_read_it_to_me_anyway")
    trimmed, record = _trimmed_take(FFMPEG, said, tmp_path, "sarah")
    assert record["rule"] == "last_letter"
    assert record["last_letter_seconds"] == pytest.approx(1.3)
    # The "s" of «Marcus» still sounds 23 ms after its letter ends + 0.03 s: the guard holds the
    # cut until the signal stays under -45 dBFS, so the s is not clipped.
    assert record["guard_seconds"] > 0.0
    frames, params = _decoded(tmp_path, "sarah_read_it_to_me_anyway")
    loud = pauses.loud_samples(frames, params.sampwidth, params.nchannels, SILENCE_THRESHOLD_DB)
    rate = params.framerate
    cut = record["tail_sample"]
    assert rate == 48000
    letter_cut = int(round((1.3 + EDGE_KEEP_SECONDS) * rate))
    assert loud[letter_cut:cut].any(), "a cut at the letter + 0.03 s would split the s"
    assert not loud[cut : cut + int(0.05 * rate)].any(), "the cut is where the sound has died"
    # Nothing of a letter is cut, and the vendor's stretched "." goes with the silence after.
    assert record["trail_seconds"] == pytest.approx(0.179, abs=0.002)
    assert record["seconds"] == pytest.approx(1.325, abs=0.002)
    assert record["kept_tail_seconds"] <= 0.001
    assert record["kept_head_seconds"] == pytest.approx(0.03, abs=0.002)
    alignment = trimmed.raw_response["alignment"]
    ends = dict(
        zip(
            range(len(alignment["characters"])),
            alignment["character_end_times_seconds"],
            strict=True,
        )
    )
    last_s = max(i for i, c in enumerate(alignment["characters"]) if c == "s")
    assert ends[last_s] <= trimmed.duration_seconds


@requires_ffmpeg
def test_babcf272_scene_3_is_cut_at_its_last_letter_not_at_the_end_of_its_stretched_stop(
    tmp_path,
):
    said = _take("babcf272_scene_03")
    _trimmed, record = _trimmed_take(FFMPEG, said, tmp_path, "babcf")
    # The "." runs from 5.016 to 5.991 s; the "y" before it is the last letter.
    assert record["rule"] == "last_letter"
    assert record["last_letter_seconds"] == pytest.approx(5.016)
    assert record["lead_seconds"] + record["seconds"] == pytest.approx(5.016 + 0.03, abs=0.001)
    assert not record["guard_moved"]
    # The head by the meter: its measured lead less the 0.03 s kept.
    assert record["lead_seconds"] == pytest.approx(
        record["measured_lead_seconds"] - EDGE_KEEP_SECONDS, abs=0.002
    )
    assert record["trail_seconds"] > 0.9  # the vendor's stretched stop is gone


@requires_ffmpeg
def test_with_the_switch_off_the_take_is_trimmed_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr(pauses, "RULES_FILE", _rules_with(tmp_path, trim_to_last_letter=False))
    _trimmed, record = _trimmed_take(FFMPEG, _take("babcf272_scene_03"), tmp_path, "old")
    assert record["rule"] == "meter"
    # The vendor's clock vetoes the meter: nothing of the tail is cut (the old defect).
    assert record["trail_seconds"] == 0.0


def test_the_trim_cut_never_splits_a_sound_and_drops_a_blip_after_a_silence():
    np = pytest.importorskip("numpy")
    rate = 1000
    loud = np.zeros(2000, dtype=bool)
    loud[100:1000] = True  # the words
    for start in range(1000, 1040, 8):  # a decay that dips under the threshold briefly
        loud[start : start + 4] = True
    loud[1500:1520] = True  # a click after a long silence
    cut = pauses.trim_cut(
        loud,
        rate,
        last_letter=(0.9, 0.98),
        lead_seconds=0.1,
        edge_keep=0.03,
        settle_seconds=0.05,
    )
    assert cut is not None
    # 0.98 + 0.03 = 1010 lies inside the decay: the cut waits for the signal to settle.
    assert cut.letter_cut == 1010
    assert cut.tail == 1036 and cut.guard_moved is False
    assert not loud[cut.tail : cut.tail + 50].any()
    assert cut.tail < 1500  # the click is cut away
    assert cut.head == 70 and cut.kept_head == pytest.approx(0.03)
    # The head never passes the first sound, whatever the meter said.
    early = pauses.trim_cut(
        loud,
        rate,
        last_letter=(0.9, 0.98),
        lead_seconds=0.5,
        edge_keep=0.03,
        settle_seconds=0.05,
    )
    assert early is not None and early.head == 100
    assert (
        pauses.trim_cut(
            np.zeros(100, dtype=bool),
            rate,
            last_letter=(0, 0.01),
            lead_seconds=0,
            edge_keep=0.03,
            settle_seconds=0.05,
        )
        is None
    )


def test_a_letter_cut_inside_speech_moves_on_to_the_next_settled_silence():
    np = pytest.importorskip("numpy")
    rate = 1000
    loud = np.zeros(1500, dtype=bool)
    loud[0:560] = True
    loud[620:700] = True  # after a breath of 60 ms, more sound: the letter's own
    cut = pauses.trim_cut(
        loud,
        rate,
        last_letter=(0.5, 0.6),
        lead_seconds=0.0,
        edge_keep=0.03,
        settle_seconds=0.05,
    )
    assert cut is not None
    assert cut.tail == 700  # never at 630, inside the sound
    assert cut.guard_moved


def test_a_fixture_take_is_a_real_kept_take():
    for name in ("sarah_read_it_to_me_anyway", "babcf272_scene_03"):
        sidecar = json.loads((FIXTURES / f"{name}.mp3.json").read_text(encoding="utf-8"))
        assert sidecar["raw_response"]["model"] == "eleven_flash_v2"
        assert "alignment" in sidecar["raw_response"]
        assert (FIXTURES / f"{name}.mp3").stat().st_size < 120_000  # the fixtures stay small
