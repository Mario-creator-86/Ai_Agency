"""One film, one look: a film-level grade toward the hero still, and free second framings.

The Nepal stills jumped between a cold storm blue, saturated orange mud and a sunny sky: every
shot went through nothing but the BT.709 conversion, so the image model's and the motion
model's colours were joined as they came. And one picture per scene at about five seconds
(4.65 s measured on the rehearsal) is slow for a short.

Here, all at 0 credits:
- ``measure_picture`` reads luma percentiles, mean chroma and saturation (signalstats);
- ``grade_toward`` pulls a shot part of the way toward the hero's numbers (bounded), and the
  film records the inter-shot colour distance (Delta E) before and after;
- ``plan_second_framings`` splits a long spoken scene at a caption boundary into two shots
  of the same take, the second a 1.15x punch-in centred where the editor asked;
- the shot plan may carry that ``second_framing`` without costing a purchase;
- a whole render records the grade, the framings, the cover and the closing card.

Every picture here is made by the local FFmpeg; no provider is called.
"""

from __future__ import annotations

import io
import json
import math
import subprocess
import wave
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.factual.models import FactualClaim, ScriptDraft, TopicIdea
from app.media import assembler
from app.media.assembler import (
    SECOND_FRAMING_ZOOM,
    _dissolve_command,
    delta_e,
    grade_toward,
    measure_picture,
    plan_second_framings,
)
from app.media.qc import editorial_cut_times as qc_cut_times
from app.media.services import generate_storyboard_from_script
from app.media.toolchain import find_ffmpeg, has_filter
from app.models import OwnerPolicy
from app.providers.media_base import ImageResult, TTSResult
from app.services import utc_now
from sqlalchemy.orm import Session

FFMPEG = find_ffmpeg()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="no FFmpeg on this machine")

COOL = "colorchannelmixer=rr=0.55:gg=0.65:bb=0.85"
WARM = "colorchannelmixer=rr=1.0:gg=0.62:bb=0.22,eq=brightness=0.08"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, capture_output=True, timeout=300)  # noqa: S603


def _still(path: Path, tint: str, size: str = "1080x1920") -> Path:
    assert FFMPEG is not None
    _run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s={size},format=rgb24,{tint}",
            "-frames:v",
            "1",
            str(path),
        ]
    )
    return path


def _shot(path: Path, still: Path, seconds: float = 2.0) -> Path:
    """A still made into a shot the way the assembler makes one (a slow push)."""
    assert FFMPEG is not None
    _run(assembler._shot_command(FFMPEG, still, None, seconds, path))
    return path


# --------------------------------------------------------------------------- measuring


@needs_ffmpeg
def test_the_picture_is_measured_from_the_file(tmp_path):
    cool = measure_picture(FFMPEG, _still(tmp_path / "cool.png", COOL))
    warm = measure_picture(FFMPEG, _still(tmp_path / "warm.png", WARM))
    assert cool is not None and warm is not None
    for stats in (cool, warm):
        assert 16 <= stats["y_low"] < stats["y_avg"] < stats["y_high"] <= 235
        assert stats["sat_avg"] > 0
    # Warm reads red (V above 128) and yellow (U below 128); cool reads blue.
    assert warm["v_avg"] > cool["v_avg"] and warm["u_avg"] < cool["u_avg"]
    assert delta_e(cool, cool) == pytest.approx(0.0, abs=1e-6)
    assert delta_e(cool, warm) == pytest.approx(delta_e(warm, cool))
    assert delta_e(cool, warm) > 10


def test_the_grade_moves_part_of_the_way_and_stays_bounded():
    hero = {"y_low": 40.0, "y_high": 200.0, "y_avg": 110.0, "u_avg": 132.0, "v_avg": 124.0,
            "sat_avg": 18.0}  # fmt: skip
    shot = {"y_low": 60.0, "y_high": 230.0, "y_avg": 150.0, "u_avg": 110.0, "v_avg": 150.0,
            "sat_avg": 40.0}  # fmt: skip
    grade = grade_toward(shot, hero, strength=0.6)
    assert grade is not None
    after = grade["predicted"]
    for key in ("y_low", "y_high", "y_avg", "u_avg", "v_avg", "sat_avg"):
        assert abs(after[key] - hero[key]) < abs(shot[key] - hero[key]), key
    assert delta_e(after, hero) < delta_e(shot, hero)
    params = grade["params"]
    assert 0.8 <= params["gain"] <= 1.25 and 0.75 <= params["saturation"] <= 1.25
    assert abs(params["u_shift"]) <= 6 and abs(params["v_shift"]) <= 6
    assert grade["filter"].startswith("lutyuv=")
    # A shot already like the hero needs no grade.
    assert grade_toward(hero, hero) is None


@needs_ffmpeg
def test_a_graded_shot_measures_closer_to_the_hero(tmp_path):
    hero = measure_picture(FFMPEG, _shot(tmp_path / "hero.mp4", _still(tmp_path / "c.png", COOL)))
    shot = _shot(tmp_path / "warm.mp4", _still(tmp_path / "w.png", WARM))
    before = measure_picture(FFMPEG, shot)
    assert hero is not None and before is not None
    grade = grade_toward(before, hero)
    assert grade is not None
    graded = tmp_path / "graded.mp4"
    _run([FFMPEG, "-v", "error", "-y", "-i", str(shot), "-vf", grade["filter"], str(graded)])
    after = measure_picture(FFMPEG, graded)
    assert after is not None
    assert delta_e(after, hero) < delta_e(before, hero) - 3
    # The prediction the film records is what the file then measures.
    assert delta_e(after, grade["predicted"]) < 4


# --------------------------------------------------------------------------- second framings


def _scene(index: int, said: float, *, kind: str = "LIVE", text: str | None = None) -> dict:
    words = (text or " ".join(f"word{i}" for i in range(14))).split()
    step = said / len(words)
    return {
        "scene_index": index,
        "duration_seconds": said + 0.12,
        "audio_seconds": said,
        "scene_kind": kind,
        "voiceover_segment": " ".join(words),
        "word_timings": [
            {"word": w, "start": round(i * step, 3), "end": round((i + 1) * step, 3)}
            for i, w in enumerate(words)
        ],
        "prompt_json": {},
    }


def test_a_long_spoken_scene_gets_a_second_framing_at_a_caption_boundary():
    scenes = [
        _scene(1, 5.0),
        _scene(2, 2.8),
        _scene(3, 5.0, kind="DATA_CARD"),
        {**_scene(4, 6.0), "prompt_json": {"second_framing": {"centre_x": 0.3, "centre_y": 0.6}}},
    ]
    cues = assembler.caption_cues(scenes)
    framings = plan_second_framings(scenes, cues, assembler.film_finish())
    assert framings[1] is None  # under 3.2 s of words
    assert framings[2] is None  # a card is never reframed
    first, last = framings[0], framings[3]
    assert first is not None and last is not None
    starts = {round(c["start"], 6) for c in cues if c["scene_index"] == 1}
    assert round(first["at"], 6) in starts  # cut where a caption card starts
    assert 1.2 <= first["at"] <= 5.0 - 1.2
    assert first["zoom"] == SECOND_FRAMING_ZOOM and 1.12 <= SECOND_FRAMING_ZOOM <= 1.2
    assert first["source"] == "default"
    assert last["source"] == "model" and last["centre"] == [0.3, 0.6]
    # The crop stays inside the frame and at least 900 px wide before it is scaled back.
    x, y, w, h = last["crop"]
    assert w >= 900 and 0 <= x <= 1080 - w and 0 <= y <= 1920 - h


@needs_ffmpeg
def test_the_edit_cuts_to_the_second_framing_inside_the_shot(tmp_path):
    shot = _shot(tmp_path / "shot.mp4", _still(tmp_path / "s.png", COOL), seconds=4.0)
    _run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=4:sample_rate=48000",
         "-c:a", "aac", str(tmp_path / "voice.m4a")]
    )  # fmt: skip
    film = tmp_path / "film.mp4"
    framing = {"at": 2.0, "zoom": 1.15, "centre": [0.5, 0.5], "crop": [70, 124, 940, 1672]}
    _run(
        _dissolve_command(
            FFMPEG,
            [shot],
            [{"duration_seconds": 4.0}],
            tmp_path / "voice.m4a",
            film,
            audio_filter=None,
            framings=[framing],
        )
    )
    from app.media.qc import picture_trace

    trace = picture_trace(FFMPEG, film)
    assert trace is not None
    # One frame changes against its neighbours: the punch-in, at 2.0 s. A 15% punch-in on a
    # flat test pattern is a small score (scdet), so it is found as a spike, not by threshold.
    peak = max(range(len(trace.scores)), key=lambda i: trace.scores[i])
    assert trace.times[peak] == pytest.approx(2.0, abs=0.05)
    others = sorted(trace.scores)[-2]
    assert trace.scores[peak] > 5 * max(others, 0.1)
    # And the editorial check counts it, because the timeline recorded it.
    production = {"timeline": {"spans": [{"start": 0.0, "second_framing": framing}]}}
    assert qc_cut_times(trace, production) == [pytest.approx(2.0, abs=0.05)]


def test_the_shot_plan_may_ask_for_a_second_framing_at_no_cost():
    from app.media.prompt_agent import ShotPrompt, _validated_package

    scene = {"narration": "The river rose", "writer_visual": "A river in flood", "seconds": 5}
    shot = ShotPrompt(
        scene_index=1,
        subject="a river in flood",
        second_framing={"subject": "the bank giving way", "centre_x": 0.7, "centre_y": 2.0},
    )
    package, _notes = _validated_package(shot, scene, {}, "", "")
    assert package["second_framing"] == {
        "subject": "the bank giving way",
        "centre_x": 0.7,
        "centre_y": 1.0,
    }
    # Garbage is dropped; the shot itself is kept.
    rough = ShotPrompt(scene_index=1, subject="a river", second_framing="closer please")
    package, _notes = _validated_package(rough, scene, {}, "", "")
    assert "second_framing" not in package and package["subject"] == "a river"
    from app.media.prompt_agent import _SHOTS_INSTRUCTIONS

    assert "second_framing" in _SHOTS_INSTRUCTIONS


# --------------------------------------------------------------------------- a whole render


class TintedImages:
    """Stills drawn locally: the first cool, the next warm, as two models might return them."""

    PROVIDER_NAME = "TEST_IMAGE_PROVIDER"
    model = "test-stills"
    integration_id = "conn-1"

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.calls = 0

    async def health_check(self) -> dict:
        return {"status": "HEALTHY"}

    async def generate_image(self, prompt: str, **_kwargs: Any) -> ImageResult:
        self.calls += 1
        tint = COOL if self.calls == 1 else WARM
        path = _still(self.folder / f"still_{self.calls}.png", tint, size="1024x1536")
        return ImageResult(
            image_bytes=path.read_bytes(), format="png", width=1024, height=1536, prompt=prompt
        )


class TimedVoice:
    """A narrator that speaks a tone for every word, with ElevenLabs-shaped alignment."""

    PROVIDER_NAME = "TEST_TIMED_VOICE"
    model = "test-voice"
    voice_id = "voice-1"
    integration_id = "conn-voice"

    async def synthesize(self, text: str, **_kwargs: Any) -> TTSResult:
        words = text.split()
        starts = [round(0.05 + 0.38 * i, 3) for i in range(len(words))]
        seconds = round(starts[-1] + 0.4, 3)
        rate = 48000
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(
                b"".join(
                    int(9000 * math.sin(2 * math.pi * 220 * n / rate)).to_bytes(
                        2, "little", signed=True
                    )
                    for n in range(int(seconds * rate))
                )
            )
        characters: list[str] = []
        begin: list[float] = []
        end: list[float] = []
        for position, word in enumerate(words):
            if position:
                characters.append(" ")
                begin.append(starts[position] - 0.01)
                end.append(starts[position])
            for offset, char in enumerate(word):
                characters.append(char)
                begin.append(starts[position] + 0.03 * offset)
                end.append(starts[position] + 0.03 * (offset + 1))
        return TTSResult(
            audio_bytes=buffer.getvalue(),
            format="wav",
            duration_seconds=seconds,
            sample_rate=rate,
            raw_response={
                "alignment": {
                    "characters": characters,
                    "character_start_times_seconds": begin,
                    "character_end_times_seconds": end,
                }
            },
        )


def _storyboard(engine) -> str:
    now = utc_now()
    script_id, claim_id, topic_id = str(uuid4()), str(uuid4()), str(uuid4())
    narration = [
        "The river rose for nine days and the whole valley slowly went under the brown water.",
        "Nobody here burned the coal that warmed the air above the mountains, yet they paid.",
        "So who pays when the river rises again?",
    ]
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        if policy:
            policy.autonomy_stopped = False
        session.add(
            TopicIdea(
                id=topic_id,
                title="Grade fixture",
                topic="climate",
                angle="fixture",
                target_audience="test",
                novelty_score=0.9,
                status="SELECTED",
                created_at=now,
            )
        )
        session.add(
            FactualClaim(
                id=claim_id,
                topic_id=topic_id,
                claim_text="Fixture claim used by the grade tests.",
                claim_type="SCIENTIFIC_FACT",
                importance="CRITICAL",
                status="SUPPORTED",
                confidence=0.99,
                created_at=now,
            )
        )
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title="Who pays when the river rises",
                target_duration_seconds=20,
                voiceover_full_text=" ".join(narration),
                scenes_json=[
                    {
                        "scene_index": 1,
                        "visual_prompt": "A valley under brown flood water",
                        "duration_seconds": 6.0,
                        "voiceover_segment": narration[0],
                        "shot_type": "WIDE",
                        "claim_ids": [claim_id],
                    },
                    {
                        "scene_index": 2,
                        "visual_prompt": "Mountains above a village",
                        "duration_seconds": 6.0,
                        "voiceover_segment": narration[1],
                        "shot_type": "WIDE",
                        "claim_ids": [claim_id],
                    },
                    {
                        "scene_index": 3,
                        "visual_prompt": "A black screen, silent and still.",
                        "duration_seconds": 3.0,
                        "voiceover_segment": narration[2],
                        "scene_kind": "BLACK",
                        "card": {"cta": "Cine plătește când râul crește din nou?"},
                        "claim_ids": [claim_id],
                    },
                ],
                status="APPROVED",
                claim_ids_json=[claim_id],
                unverified_claim_ids_json=[],
                story_json={"hook": "The river rose for nine days."},
                created_at=now,
            )
        )
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    return board["id"]


def _yavg(film: Path, at: float) -> float:
    result = _run(
        [FFMPEG, "-v", "error", "-ss", f"{at:.3f}", "-i", str(film), "-frames:v", "1",
         "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
         "-f", "null", "-"]
    )  # fmt: skip
    line = next(x for x in result.stdout.decode().splitlines() if "YAVG=" in x)
    return float(line.split("=")[1])


@needs_ffmpeg
@pytest.mark.skipif(
    FFMPEG is None or not has_filter(FFMPEG, "subtitles"), reason="no libass in the local ffmpeg"
)
def test_a_render_records_its_grade_framings_cover_and_closing_card(engine, tmp_path):
    board = _storyboard(engine)
    images = TintedImages(tmp_path)
    render = assembler.assemble_video_job(
        engine,
        board,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=images,
        tts_adapter=TimedVoice(),
        environment="TEST",
    )
    production = render["production"]
    film = Path(render["file_path"])

    # The grade: scene 2 (warm) was pulled toward scene 1 (the hero), and the distance shrank.
    grade = production["grade"]
    assert grade["reference_scene"] == 1
    graded = {entry["scene_index"]: entry for entry in grade["shots"]}
    assert graded[2]["delta_e_after"] < graded[2]["delta_e_before"]
    assert graded[2]["filter"].startswith("lutyuv=")
    assert 3 not in graded or graded[3].get("filter") is None  # the card keeps its palette
    assert grade["delta_e_max_after"] <= grade["delta_e_max_before"]

    # The framings: both spoken scenes run over 3.2 s and are cut at a caption boundary.
    spans = production["timeline"]["spans"]
    assert spans[0]["second_framing"] is not None and spans[1]["second_framing"] is not None
    assert spans[2].get("second_framing") is None
    assert production["timeline"]["shots_on_screen"] == 5
    assert production["timeline"]["average_shot_seconds"] < 3.5

    # The captions highlight the spoken word.
    script = Path(production["captions"]["ass"]).read_text(encoding="utf-8")
    assert "\\t(" in script and production["captions"]["style"]["highlight"] is True

    # The closing call is spoken over the hook's picture, not over black.
    card = next(s["card"] for s in production["scenes"] if s.get("card"))
    assert card["closing"] is True and card["background"]
    duration = float(render["duration_seconds"])
    assert _yavg(film, duration - 0.3) > 30

    # The cover: the hero still and the hook, composed locally, kept beside the film.
    cover = production["cover"]
    assert Path(cover["path"]).is_file() and cover["hook"] == "The river rose for nine days."
    assert cover["credits"] == 0

    # Nothing was bought twice, and nothing beyond the two stills was asked for.
    assert images.calls == 2
    json.dumps(production)  # the whole record stays JSON

    # Quality control reads the editing of this film too: it does not end on black, its
    # shots are short, and its captions keep their phrases (advisory notes only).
    from app.media.qc import evaluate_media_qc

    report = evaluate_media_qc(engine, render["output_asset_id"], str(uuid4()))
    editorial = report["checks_json"]["editorial_qc"]
    codes = {problem["code"] for problem in editorial["problems"]}
    assert not codes & {"black_ending", "frozen_ending", "long_shots", "dangling_caption"}, codes
    assert editorial["measurements"]["cuts"] >= 4
    assert editorial["passed"] is True  # advisory: no music library in a test studio
