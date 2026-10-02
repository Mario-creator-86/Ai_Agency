"""Editorial quality: how a short ends, and what quality control can see of its editing.

The zero-credit Nepal rehearsal of 2026-10-01 ended on 4.3 seconds of near-black (signalstats
YAVG 16-17.3) with only the closing question as a caption, because the writer's brief offered
a black screen "for the closing call to action". Shorts are watched in a loop; an ending that
fades out invites the swipe, and an ending that leads back into the opening counts twice.
The same film had five dead-air gaps, a 4.65 s average shot and captions that broke in the
middle of a phrase, and quality control passed all of it, because none of its checks looked
at the editing.

Here:
- the writer's brief and the story checks refuse a script that ends on BLACK, allow BLACK only
  as a beat of one second at most, and flag (advisory) an ending that does not loop back;
- the card compositor refuses a pure black card longer than 1.5 s in a short;
- ``qc.editorial_problems`` measures a film's editing on synthetic films made here with the
  local FFmpeg: dead air inside the narration, a black or frozen ending, the average shot
  length, a static first half-second, captions that end on a function word, and a missing
  music bed. Advisory by default; blocking only when the Owner turns it on.

Every film here is made locally; no provider is called.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from app.factual.editorial import (
    BLACK_BEAT_SECONDS,
    FUNCTION_WORDS,
    dangles,
    story_checks,
)
from app.factual.story_review import ADVISORY_CHECKS
from app.media import qc
from app.media.cards import MAX_SHORT_BLACK_SECONDS, CardError, card_spec_from_json, compose_card
from app.media.toolchain import find_ffmpeg

FFMPEG = find_ffmpeg()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="no FFmpeg on this machine")

SCENES = [
    {
        "scene_number": 1,
        "purpose": "HOOK",
        "scene_kind": "LIVE",
        "narration": "There is one web address nobody on earth is allowed to buy.",
        "claim_ids": ["c1"],
    },
    {
        "scene_number": 2,
        "purpose": "SETUP",
        "scene_kind": "LIVE",
        "narration": "It looks ordinary, but every registrar refuses it.",
        "claim_ids": ["c1"],
    },
    {
        "scene_number": 3,
        "purpose": "REVEAL",
        "scene_kind": "LIVE",
        "narration": "The registry reserved the address itself, so no company can hold it.",
        "claim_ids": ["c2"],
    },
    {
        "scene_number": 4,
        "purpose": "ENDING",
        "scene_kind": "LIVE",
        "narration": "So which address would you try to buy, if nobody on earth is allowed?",
        "claim_ids": ["c1"],
    },
]
STORY = {
    "core_message": "One web address is reserved so nobody can ever own it.",
    "hook": "There is one web address nobody on earth is allowed to buy.",
    "ending": "Reserved on purpose, by the registry itself.",
    "cta": "So which address would you try to buy?",
    "cta_kind": "COMMENT",
}


def checks_for(scenes: list[dict]) -> dict:
    return story_checks(
        title="The address nobody may buy", scenes=scenes, story=STORY, target_seconds=20
    )


# --------------------------------------------------------------------------- the ending


def test_a_script_that_ends_on_a_black_screen_is_sent_back():
    black_end = [*SCENES[:-1], {**SCENES[-1], "scene_kind": "BLACK"}]
    checks = checks_for(black_end)
    assert checks["ending_is_not_black"]["passed"] is False
    assert "negru" in checks["ending_is_not_black"]["reason"]
    # A refusal, not a flag: the story review sends it back for a rewrite.
    assert "ending_is_not_black" not in ADVISORY_CHECKS

    # The same film ending on a filmed picture passes.
    assert checks_for(SCENES)["ending_is_not_black"]["passed"] is True
    # The writer's own word "kind" is read too, not only the stored "scene_kind".
    legacy = [*SCENES[:-1], {**SCENES[-1], "scene_kind": None, "kind": "BLACK"}]
    assert checks_for(legacy)["ending_is_not_black"]["passed"] is False


def test_a_black_scene_is_only_a_silent_beat_of_one_second():
    spoken_black = [
        SCENES[0],
        {**SCENES[1], "scene_kind": "BLACK", "narration": "And then the screen went dark for us."},
        *SCENES[2:],
    ]
    checks = checks_for(spoken_black)
    assert checks["black_is_a_beat"]["passed"] is False
    assert (
        "1 s" in checks["black_is_a_beat"]["reason"]
        or "o secundă" in (checks["black_is_a_beat"]["reason"])
    )
    beat = [SCENES[0], {**SCENES[1], "scene_kind": "BLACK", "narration": "Silence."}, *SCENES[2:]]
    assert checks_for(beat)["black_is_a_beat"]["passed"] is True
    assert BLACK_BEAT_SECONDS == 1.0


def test_an_ending_that_loops_back_to_the_hook_is_an_advisory_flag():
    assert "ending_loops_to_hook" in ADVISORY_CHECKS
    assert checks_for(SCENES)["ending_loops_to_hook"]["passed"] is True
    unrelated = [*SCENES[:-1], {**SCENES[-1], "narration": "Thanks for watching today, friends."}]
    flagged = checks_for(unrelated)["ending_loops_to_hook"]
    assert flagged["passed"] is False
    assert "început" in flagged["reason"]


def test_the_brief_no_longer_offers_black_for_the_closing_call_and_asks_for_a_loop():
    from app.factual.agent_pipeline import _write_instructions

    brief = _write_instructions(30)
    assert "pentru o tăcere sau pentru îndemnul final" not in brief
    assert "niciodată ca ultimă scenă" in brief
    assert "cel mult o secundă" in brief
    assert "buclă" in brief
    # The existing promises of the brief stay.
    assert "ULTIMA scenă închide filmul" in brief


# --------------------------------------------------------------------------- the black card


def test_a_pure_black_card_longer_than_a_beat_is_refused_for_a_short(tmp_path):
    spec = card_spec_from_json("BLACK", {"cta": "Care adresă ai cumpăra?"})
    assert MAX_SHORT_BLACK_SECONDS == 1.5
    with pytest.raises(CardError, match="negru"):
        compose_card(spec, tmp_path / "black.mp4", duration=4.3, short=True, ffmpeg="unused")


@needs_ffmpeg
def test_a_short_black_beat_is_still_composed(tmp_path):
    spec = card_spec_from_json("BLACK", None)
    card = compose_card(spec, tmp_path / "beat.mp4", duration=1.0, short=True, ffmpeg=FFMPEG)
    assert card.path.is_file() and card.kind == "BLACK"


# --------------------------------------------------------------------------- synthetic films


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True, timeout=300)  # noqa: S603


def _film(
    path: Path,
    video: list[tuple[str, float]],
    audio: list[tuple[str, float]],
) -> Path:
    """A small synthetic film: each video segment is a lavfi source at 270x480, 24 fps, and
    each audio segment a tone or silence, joined end to end."""
    assert FFMPEG is not None
    args = [FFMPEG, "-v", "error", "-y"]
    for source, seconds in video:
        base, _, after = source.partition(",")
        joiner = ":" if "=" in base else "="
        chain = f"{base}{joiner}s=270x480:r=24:d={seconds}" + (f",{after}" if after else "")
        args += ["-f", "lavfi", "-i", chain]
    for source, seconds in audio:
        if source == "tone":
            args += ["-f", "lavfi", "-i", f"sine=f=220:sample_rate=48000:d={seconds}"]
        else:
            args += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono:d={seconds}"]
    v = len(video)
    graph = "".join(f"[{i}:v]format=yuv420p,setsar=1[v{i}];" for i in range(v))
    graph += "".join(f"[v{i}]" for i in range(v)) + f"concat=n={v}:v=1:a=0[vout];"
    graph += "".join(f"[{v + i}:a]aformat=channel_layouts=mono[a{i}];" for i in range(len(audio)))
    graph += "".join(f"[a{i}]" for i in range(len(audio))) + f"concat=n={len(audio)}:v=0:a=1[aout]"
    args += [
        "-filter_complex",
        graph,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        str(path),
    ]
    _run(args)
    return path


def _cues(*texts: str, step: float = 1.5) -> list[dict]:
    return [
        {"index": i + 1, "start": i * step, "end": (i + 1) * step, "lines": [text]}
        for i, text in enumerate(texts)
    ]


BED = {"audio": {"bed": {"track": "calm-01", "measured_lu_under_voice": 20.0}}}


@needs_ffmpeg
def test_a_well_edited_film_has_no_editorial_problem(tmp_path):
    film = _film(
        tmp_path / "good.mp4",
        [
            ("testsrc2", 2.5),
            ("testsrc2,negate", 2.5),
            ("testsrc2,hue=h=180", 2.5),
            ("testsrc2,negate,hue=h=90", 2.5),
        ],
        [("tone", 10.0)],
    )
    report = qc.editorial_problems(
        film,
        BED,
        ffmpeg=FFMPEG,
        cues=_cues("Nepal is paying", "for a crisis", "it did not create."),
    )
    assert report["status"] == "PASSED", report
    assert report["problems"] == []
    measured = report["measurements"]
    assert measured["cuts"] == 3
    assert measured["average_shot_seconds"] == pytest.approx(2.5, abs=0.1)
    assert measured["longest_silence_seconds"] <= qc.MAX_NARRATION_SILENCE_SECONDS
    assert measured["black_end_seconds"] == 0.0
    assert measured["opening_motion"] >= qc.MIN_OPENING_YDIF


@needs_ffmpeg
def test_the_rehearsal_faults_are_each_measured_and_named_in_romanian(tmp_path):
    """A static opening, one long shot, dead air inside the narration, a black ending, a
    dangling caption and no bed: the Nepal rehearsal's faults, on a 12-second film."""
    film = _film(
        tmp_path / "bad.mp4",
        [("color=c=gray", 1.0), ("testsrc2", 7.0), ("color=c=black", 4.0)],
        [("tone", 3.0), ("silence", 0.6), ("tone", 3.0), ("silence", 5.4)],
    )
    report = qc.editorial_problems(
        film,
        {"audio": {}},
        ffmpeg=FFMPEG,
        cues=_cues("Nepal is paying for a", "crisis it did not create."),
    )
    codes = {problem["code"] for problem in report["problems"]}
    assert codes == {
        "dead_air",
        "black_ending",
        "frozen_ending",
        "long_shots",
        "static_opening",
        "dangling_caption",
        "no_music_bed",
    }, report["problems"]
    # Advisory by default: the film is not refused, the reasons are reported.
    assert report["status"] == "ADVISORY" and report["passed"] is True
    reasons = " ".join(report["reasons_ro"])
    for words in ("tăcere", "negru", "încremenit", "cadru", "începe", "«a»", "muzică"):
        assert words in reasons, words
    measured = report["measurements"]
    assert measured["longest_silence_seconds"] == pytest.approx(0.6, abs=0.1)
    assert measured["black_end_seconds"] >= 2.9
    assert measured["average_shot_seconds"] > qc.MAX_AVERAGE_SHOT_SECONDS
    assert measured["dangling_captions"] == [{"cue": 1, "word": "a"}]

    # When the Owner makes the check blocking, the same film fails it.
    blocking = qc.editorial_problems(
        film,
        {"audio": {}},
        ffmpeg=FFMPEG,
        cues=_cues("Nepal is paying for a", "crisis it did not create."),
        blocking=True,
    )
    assert blocking["status"] == "FAILED" and blocking["passed"] is False


@needs_ffmpeg
def test_a_frozen_ending_that_is_not_black_is_still_named(tmp_path):
    film = _film(
        tmp_path / "frozen.mp4",
        [("testsrc2", 2.0), ("testsrc2,negate", 2.0), ("color=c=0x707070", 2.5)],
        [("tone", 6.5)],
    )
    report = qc.editorial_problems(film, BED, ffmpeg=FFMPEG, cues=[])
    codes = {problem["code"] for problem in report["problems"]}
    assert "frozen_ending" in codes and "black_ending" not in codes


@needs_ffmpeg
def test_a_silent_card_beat_is_not_dead_air(tmp_path):
    """A silent composed scene is a deliberate beat: its silence is not counted."""
    film = _film(
        tmp_path / "beat.mp4",
        [("testsrc2", 2.0), ("testsrc2,negate", 1.0), ("testsrc2,hue=h=90", 2.0)],
        [("tone", 2.0), ("silence", 1.0), ("tone", 2.0)],
    )
    production = {
        **BED,
        "timeline": {
            "spans": [
                {"scene_index": 1, "start": 0.0, "end": 2.0, "kind": "LIVE"},
                {
                    "scene_index": 2,
                    "start": 2.0,
                    "end": 3.0,
                    "kind": "BLACK",
                    "composed": True,
                    "spoken_seconds": 0.0,
                },
                {"scene_index": 3, "start": 3.0, "end": 5.0, "kind": "LIVE"},
            ]
        },
    }
    report = qc.editorial_problems(film, production, ffmpeg=FFMPEG, cues=[])
    assert "dead_air" not in {problem["code"] for problem in report["problems"]}


def test_without_an_encoder_nothing_is_certified():
    report = qc.editorial_problems(Path("missing.mp4"), {}, ffmpeg=None, cues=[])
    assert report["status"] == "NOT_MEASURED" and report["passed"] is None


# --------------------------------------------------------------------------- function words


def test_the_function_words_are_shared_in_english_and_romanian():
    for word in ("a", "the", "for", "to", "do", "is", "it", "of"):
        assert word in FUNCTION_WORDS
    for word in ("și", "de", "la", "în", "pe", "cu", "un", "o", "că", "să", "nu"):
        assert word in FUNCTION_WORDS
    assert dangles("for") and dangles("A") and not dangles("crisis")
    # A word that closes a sentence or a clause is not left hanging.
    assert not dangles("it.") and not dangles("for,")


def test_qc_names_a_caption_that_ends_on_a_function_word_when_asked():
    cues = qc.parse_srt(
        "1\n00:00:00,000 --> 00:00:01,500\nNepal is paying for a\n\n"
        "2\n00:00:01,500 --> 00:00:03,000\ncrisis it did not create.\n"
    )
    assert qc.caption_problems(cues) == []  # the delivery check is unchanged
    problems = qc.caption_problems(cues, dangling=True)
    assert problems == ["cue 1 ends on the function word 'a'"]


# --------------------------------------------------------------------------- the Owner's report


def _report(editorial: dict) -> dict:
    return {"status": "PASSED", "score": 1.0, "checks_json": {"editorial_qc": editorial}}


def test_the_owners_report_lists_advisory_editing_notes_apart_from_failures():
    from app.media.qc_report import EDITORIAL_HEADING, qc_summary_ro

    advisory = {
        "passed": True,
        "status": "ADVISORY",
        "reasons_ro": ["Filmul se încheie pe negru: 3,0 s de negru în ultimele 3 s."],
    }
    text = qc_summary_ro(_report(advisory), None)
    assert "Ce a picat: nimic din ce s-a măsurat." in text
    assert EDITORIAL_HEADING in text
    assert "- Filmul se încheie pe negru" in text

    blocking = {**advisory, "passed": False, "status": "FAILED"}
    failed = qc_summary_ro({**_report(blocking), "status": "FAILED"}, None)
    assert "- Montaj: Filmul se încheie pe negru" in failed
    assert EDITORIAL_HEADING not in failed


def test_editorial_blocking_follows_the_owners_setting_then_the_look():
    class Settings:
        editorial_qc_blocking = True

    assert qc.editorial_blocking(Settings()) is True
    assert qc.editorial_blocking(None) is False  # the look file says advisory
