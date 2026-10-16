"""«Pauza vocii», stage 2: the render says one take per voice group and lays the voice out by the
film's frozen pauses (the Owner, 2026-10-16).

A writer's scene cut into shots by the montage is said once, as one take, and the picture cuts
on the take's own word timing: the cut adds nothing. Between two takes the silence heard (the
take's kept tail, the pad, the next take's head) is the pause frozen when the storyboard was
built, to within a frame; every cut is on a frame of the cumulative timeline and the voice
never drifts from it. Every voice here is a local fake: nothing is bought from anyone.
"""

from __future__ import annotations

import io
import math
import wave
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.media import pause_plan, pauses
from app.media.assembler import TIMELINE_FPS, assemble_video_job, clip_fits, narration_to_buy
from app.media.toolchain import find_ffmpeg
from app.providers.media_base import TTSResult
from test_pause_freeze import LONG, _factual_board, _scene

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="FFmpeg is not installed")
FRAME = 1.0 / TIMELINE_FPS


class SpacedVoice:
    """A narrator whose takes sound like a vendor's: a tone for each word, silence between
    sentences, a lead before the first word and a long silence after the last, which the
    vendor's alignment covers with the final punctuation stretched to the file's end."""

    PROVIDER_NAME = "TEST_SPACED_VOICE"
    model = "test-voice"
    voice_id = "voice-1"
    integration_id = "conn-voice"

    def __init__(self) -> None:
        self.heard: list[str] = []
        self.asked: list[dict[str, Any]] = []

    async def synthesize(self, text: str, **kwargs: Any) -> TTSResult:
        self.heard.append(text)
        self.asked.append(dict(kwargs.get("extra") or {}))
        words = text.split()
        rate = 48000
        sounds: list[tuple[float, float]] = []
        clock = 0.12
        for position, word in enumerate(words):
            letters = sum(1 for char in word if char.isalnum()) or 1
            length = 0.05 * letters + 0.05
            sounds.append((clock, clock + length))
            clock += length
            if position < len(words) - 1:
                clock += 0.45 if word.endswith((".", "!", "?", "…")) else 0.03
        seconds = round(clock + 0.6, 3)
        samples = bytearray()
        for n in range(int(seconds * rate)):
            moment = n / rate
            loud = any(start <= moment < end for start, end in sounds)
            value = int(9000 * math.sin(2 * math.pi * 220 * moment)) if loud else 0
            samples += value.to_bytes(2, "little", signed=True)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(bytes(samples))
        characters: list[str] = []
        begin: list[float] = []
        end: list[float] = []
        for position, (word, (start, stop)) in enumerate(zip(words, sounds, strict=True)):
            if position:
                characters.append(" ")
                begin.append(start)
                end.append(start)
            letters = [char for char in word if char.isalnum()]
            step = (stop - start) / max(1, len(letters))
            placed = 0
            following = sounds[position + 1][0] if position + 1 < len(words) else seconds
            for char in word:
                if char.isalnum():
                    characters.append(char)
                    begin.append(start + step * placed)
                    end.append(start + step * (placed + 1))
                    placed += 1
                else:  # the vendor stretches punctuation over the pause after it
                    characters.append(char)
                    begin.append(stop)
                    end.append(following)
        return TTSResult(
            audio_bytes=buffer.getvalue(),
            format="wav",
            duration_seconds=seconds,
            sample_rate=rate,
            raw_response={
                "provider": self.PROVIDER_NAME,
                "alignment": {
                    "characters": characters,
                    "character_start_times_seconds": begin,
                    "character_end_times_seconds": end,
                },
            },
        )


# ------------------------------------------------------------------------- the pure layout


def _words(text: str, start: float = 0.1, gap: float = 0.4) -> list[pause_plan.Word]:
    found, clock = [], start
    for word in text.split():
        found.append(pause_plan.Word(word, clock, clock + 0.3, clock, clock + 0.3))
        clock += 0.3 + (gap if word.endswith(".") else 0.02)
    return found


def test_a_cut_inside_a_take_lands_on_the_next_units_first_letter():
    units = ["The probe slept for nine years.", "Then the signal came back."]
    words = _words(" ".join(units))
    cuts = pause_plan.take_cuts(units, 5.0, words, cut_in_pause=1.0)
    assert cuts.timed
    assert cuts.offsets[0] == 0.0
    # On "Then": the outgoing shot holds the voice's own full-stop pause.
    assert cuts.offsets[1] == pytest.approx(words[6].first)
    assert cuts.gaps[0] == pytest.approx(0.4)
    assert cuts.words[1][0]["start"] == pytest.approx(0.0)
    # At 0.0 the new picture comes with the end of the last word, the pause on the new shot.
    early = pause_plan.take_cuts(units, 5.0, words, cut_in_pause=0.0)
    assert early.offsets[1] == pytest.approx(words[5].last)
    # A vendor tag read before the words (an acting note on a tag model) is skipped.
    tagged = [pause_plan.Word("[surprised]", 0.0, 0.1, 0.0, 0.1), *words]
    assert pause_plan.take_cuts(units, 5.0, tagged, cut_in_pause=1.0).offsets == cuts.offsets
    # Words that do not match the text: the cuts fall at the units' share of the characters.
    shared = pause_plan.take_cuts(units, 5.0, words[:-1], cut_in_pause=1.0)
    assert not shared.timed
    assert shared.offsets[1] == pytest.approx(5.0 * len(units[0]) / sum(map(len, units)))


def test_the_layout_never_drifts_over_sixty_rows_and_a_card_is_its_own_pause():
    # Sixty rows: thirty takes of two units each, odd lengths that never fall on a frame.
    rows: list[Any] = []
    takes = []
    for k in range(30):
        first, second = 1.013 + 0.007 * k, 0.991 + 0.011 * k
        takes.append(pause_plan.TakeJoin(first + second, 0.4733))
        rows.append([pause_plan.Unit(k, 0.0, first)])
        rows.append([pause_plan.Unit(k, first, second)])
    layout = pause_plan.voice_layout(rows, takes, fps=TIMELINE_FPS, cut_in_pause=1.0)
    exact = sum(t.seconds + t.pad for t in takes)
    assert sum(layout.spans) == pytest.approx(exact, abs=FRAME / 2)
    for start in layout.starts:
        assert abs(start * TIMELINE_FPS - round(start * TIMELINE_FPS)) < 1e-6
    # Each take starts on its row's cut, and every pad is the planned one within a frame.
    for k in range(30):
        assert layout.take_starts[k] == pytest.approx(layout.starts[2 * k], abs=1e-4)
        assert layout.pads[k] == pytest.approx(0.4733, abs=FRAME)
    # A film that opens on a silent card: the voice waits for it.
    opened = pause_plan.voice_layout(
        [2.0, [pause_plan.Unit(0, 0.0, 1.5)]],
        [pause_plan.TakeJoin(1.5, 0.5)],
        fps=TIMELINE_FPS,
        cut_in_pause=1.0,
    )
    assert opened.lead == pytest.approx(2.0) and opened.spans[0] == pytest.approx(2.0)
    # A card between two takes is the pause: the next take starts when the card ends.
    middle = pause_plan.voice_layout(
        [[pause_plan.Unit(0, 0.0, 1.5)], 2.5, [pause_plan.Unit(1, 0.0, 1.0)]],
        [pause_plan.TakeJoin(1.5, 0.0), pause_plan.TakeJoin(1.0, 0.77)],
        fps=TIMELINE_FPS,
        cut_in_pause=1.0,
    )
    assert middle.take_starts[1] == pytest.approx(1.5 + 2.5)
    assert middle.pads[0] == pytest.approx(2.5)
    assert middle.spans[-1] == pytest.approx(round((1.0 + 0.77) * TIMELINE_FPS) / TIMELINE_FPS)


def test_a_pause_gives_up_whole_frames_toward_its_floor_before_a_clip_is_too_short():
    assert pause_plan.shrink_frames(5.0, 6.0, 0.5, TIMELINE_FPS, clip_fits) == 0
    need = 5.0 * 1.25 + 3 * FRAME  # three frames past what a 5 s clip may be slowed into
    frames = pause_plan.shrink_frames(5.0, need, 0.5, TIMELINE_FPS, clip_fits)
    assert frames == 3 or frames == 4
    assert clip_fits(5.0, need - frames / TIMELINE_FPS)
    assert pause_plan.shrink_frames(5.0, need, 2 * FRAME, TIMELINE_FPS, clip_fits) == -1


# -------------------------------------------------------------------------- the real render


def _render(engine, board: str, voice: SpacedVoice, tmp_path: Path) -> dict[str, Any]:
    from test_motion import StubImages

    return assemble_video_job(
        engine,
        board,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=StubImages(),
        tts_adapter=voice,
        environment="TEST",
    )


@requires_ffmpeg
@pytest.mark.montage
def test_a_writers_scene_is_said_once_and_every_join_is_heard_as_frozen(engine, tmp_path):
    board = _factual_board(
        engine,
        [_scene(1, "HOOK", LONG), _scene(2, "ENDING", "Reserved on purpose, by the registry.")],
    )
    voice = SpacedVoice()
    expected_characters = len(LONG) + len("Reserved on purpose, by the registry.")
    assert narration_to_buy(engine, board, tts_adapter=voice) == expected_characters

    render = _render(engine, board, voice, tmp_path)
    production = render["production"]
    # One take per writer's scene: the montage's shots are cut inside it, nothing is stitched.
    assert voice.heard == [LONG, "Reserved on purpose, by the registry."]
    timeline = production["timeline"]
    spans = timeline["spans"]
    assert len(spans) >= 3 and "spoken_tail_seconds" not in timeline
    assert timeline["pause_profile"]["rule_version"] == pauses.load_rules().version
    hook = [span for span in spans[:-1]]
    for span in hook[:-1]:
        assert span["pause"]["class"] == pauses.IN_TAKE and span["pause"]["pad"] == 0.0
    # Between the two takes, and after the last word: the silence heard is the pause frozen.
    for span in (hook[-1], spans[-1]):
        pause = span["pause"]
        assert pause["class"] in (pauses.PARAGRAPH, pauses.END)
        assert pause["heard"] == pytest.approx(pause["planned"], abs=FRAME)
        assert pause["keep_tail"] <= 0.06  # the vendor's long tail is trimmed to the letter
    # Every cut on a frame, and the film is its spans.
    clock = 0.0
    for span in spans:
        assert abs(span["start"] * TIMELINE_FPS - round(span["start"] * TIMELINE_FPS)) < 1e-4
        clock = span["end"]
    assert timeline["film_seconds"] == pytest.approx(clock)
    # The take is named on every row it is said over and paid once, on the first.
    records = production["scenes"]
    take_ids = {tuple(record["narration_takes"]) for record in records[: len(hook)]}
    assert len(take_ids) == 1
    assert records[0]["characters_bought"] == len(LONG)
    assert all(record["characters_bought"] == 0 for record in records[1 : len(hook)])
    # The row's words share the take: its audio adds up to the take, never more.
    assert sum(record["audio_seconds"] for record in records[: len(hook)]) > 0
    # The voice track is as long as the pictures.
    track = Path(render["file_path"]).parent / "master_audio.wav"
    with wave.open(str(track), "rb") as joined:
        assert joined.getnframes() / joined.getframerate() == pytest.approx(
            render["duration_seconds"], abs=0.1
        )

    # A second render buys nothing: the same words, the same voice, the same neighbours; and
    # the sheet prices every row of the take at 0, not only the row it is filed under.
    assert narration_to_buy(engine, board, tts_adapter=voice) == 0
    from app.media.assembler import scene_view, voiced_scenes
    from app.media.models import StoryboardScene
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        views = [
            scene_view(row)
            for row in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == board)
            )
        ]
        assert voiced_scenes(session, board, views) == {view["scene_index"] for view in views}
    again = SpacedVoice()
    _render(engine, board, again, tmp_path)
    assert again.heard == []


@requires_ffmpeg
def test_a_film_built_before_the_rules_keeps_the_legacy_breath(engine, tmp_path, monkeypatch):
    import json

    data = json.loads(pauses.RULES_FILE.read_text(encoding="utf-8"))
    data["use_until_the_owner_changes_it"] = False
    off = tmp_path / "pause_rules.json"
    off.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(pauses, "RULES_FILE", off)
    board = _factual_board(engine, [_scene(1, "HOOK", "One short scene, said once.")])
    render = _render(engine, board, SpacedVoice(), tmp_path)
    timeline = render["production"]["timeline"]
    assert timeline["spoken_tail_seconds"] == 0.4
    assert "pause" not in timeline["spans"][0]


@requires_ffmpeg
@pytest.mark.montage
def test_a_film_over_its_wall_at_the_render_gives_up_its_pauses_in_order(
    engine, tmp_path, monkeypatch
):
    """The Owner's decision 9 at the render: a film whose measured voice runs past its wall
    gives up its pauses toward their floors, one factor for the whole ladder, a marked beat
    and a card never; the film then fits the wall and the timeline says so (review of
    2026-10-16: nothing tested this at the render)."""
    board = _factual_board(
        engine,
        [
            _scene(1, "HOOK", LONG),
            _scene(2, "DEVELOPMENT", "The registry keeps a short list of names it never sells."),
            _scene(3, "ENDING", "Reserved on purpose, by the registry itself."),
        ],
    )
    first = _render(engine, board, SpacedVoice(), tmp_path)
    natural = float(first["production"]["timeline"]["film_seconds"])
    assert first["production"]["timeline"]["pause_profile"]["render_wall_factors"] is None
    wall = round(natural - 0.3, 3)
    monkeypatch.setattr(pause_plan, "board_wall", lambda session, board, rules: wall)
    again = SpacedVoice()
    render = _render(engine, board, again, tmp_path / "again")
    assert again.heard == []  # the takes are the ones paid for
    timeline = render["production"]["timeline"]
    assert timeline["film_seconds"] <= wall + 1e-6
    assert timeline["pause_profile"]["render_wall"] == wall
    factors = timeline["pause_profile"]["render_wall_factors"]
    assert factors is not None and min(factors) < 1.0
    squeezed = [span["pause"] for span in timeline["spans"] if span["pause"].get("wall_k")]
    assert squeezed, "the pauses gave the wall its seconds"
    for pause in squeezed:
        assert pause["class"] not in (pauses.BEAT, pauses.CARD, pauses.IN_TAKE)
        assert pause["floor"] - 1e-3 <= pause["planned"]
        assert pause["heard"] == pytest.approx(pause["planned"], abs=FRAME)
