"""The film's sound: no dead air between the words, and a licensed bed under them.

Measured on the rehearsal film (audit Q1, Q4): the narration sat over digital silence (-87 dB
between the words), and every cut carried 0.28-0.61 s of dead air, the vendor's own trailing
silence plus a fixed 0.35 s breath. A faceless documentary short runs a music bed ducked
under the voice, and cuts the dead air first.

The bed is chosen only from config/music_library.json, the Owner's own list: a track without
``commercial_ok``, without a licence, missing, or whose bytes are not the ones recorded, is
never used. The library ships empty; the film is then voice only and says so.

Every sound here is synthesised by FFmpeg (aevalsrc) or by the test; no provider is called.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import subprocess
import wave
from pathlib import Path
from uuid import uuid4

import pytest
from app.media import music_library, toolchain
from app.media.assembler import VOICE_TRACK_NAME, assemble_video_job
from app.media.toolchain import find_ffmpeg, measure_loudness

FFMPEG = find_ffmpeg()
requires_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is not installed")


def _tone(path: Path, expression: str, seconds: float, *, channels: int = 1) -> Path:
    layout = "mono" if channels == 1 else "stereo"
    subprocess.run(  # noqa: S603
        [
            FFMPEG,
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc={expression}:s=48000:d={seconds}:c={layout}",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _rms_db(path: Path, start: float, seconds: float) -> float:
    """The RMS level of ``path`` between ``start`` and ``start + seconds``, in dBFS."""
    with wave.open(str(path), "rb") as audio:
        rate, width, channels = audio.getframerate(), audio.getsampwidth(), audio.getnchannels()
        audio.setpos(int(start * rate))
        frames = audio.readframes(int(seconds * rate))
    step = width * channels
    total, count = 0.0, 0
    for offset in range(0, len(frames) - step + 1, step):
        sample = int.from_bytes(frames[offset : offset + width], "little", signed=True)
        total += (sample / float(1 << (8 * width - 1))) ** 2
        count += 1
    return 10 * math.log10(total / count) if total > 0 else -200.0


def _gaps(path: Path) -> list[tuple[float, float]]:
    """Every silence inside ``path`` at -45 dB for at least 50 ms, as (start, end); a silence
    running to the end of the file ends at its length."""
    spans = toolchain.silence_spans(FFMPEG, path, threshold_db=-45.0, min_seconds=0.05)
    assert spans is not None
    return spans


# --------------------------------------------------------------------------------- the bed --


@requires_ffmpeg
def test_the_bed_sits_18_to_22_lu_under_the_voice_and_fades_in_and_out(tmp_path: Path):
    # A voice that speaks and pauses (1.2 s on, 0.4 s off) and a steady stereo bed. The voice
    # is stereo here, as the master hears it, so the stems compare like for like.
    speech = "0.5*sin(2*PI*330*t)*lt(mod(t\\,1.6)\\,1.2)"
    voice = _tone(tmp_path / "voice.wav", f"{speech}|{speech}", 6.4, channels=2)
    bed = _tone(tmp_path / "bed.wav", "0.6*sin(2*PI*110*t)|0.6*sin(2*PI*112*t)", 9.0, channels=2)
    mixed = toolchain.mix_bed(
        FFMPEG,
        voice,
        tmp_path / "mixed.wav",
        bed=bed,
        duration=6.4,
        work_dir=tmp_path,
    )
    record = mixed["bed"]
    assert 18.0 <= record["measured_lu_under_voice"] <= 22.0, record
    # Measured again here, from the stems, not taken from the record.
    stem = Path(record["stem"])
    voice_lufs = float(measure_loudness(FFMPEG, voice)["integrated_lufs"])
    bed_lufs = float(measure_loudness(FFMPEG, stem)["integrated_lufs"])
    assert 18.0 <= voice_lufs - bed_lufs <= 22.0, (voice_lufs, bed_lufs)
    # Ducked under the words: the bed is lower while the voice speaks than in its pauses.
    assert _rms_db(stem, 0.5, 0.4) < _rms_db(stem, 1.3, 0.2) - 3.0
    # 0.3 s fade-in and 0.8 s fade-out.
    assert record["fade_in_seconds"] == pytest.approx(0.3)
    assert record["fade_out_seconds"] == pytest.approx(0.8)
    assert _rms_db(stem, 0.0, 0.03) < _rms_db(stem, 0.25, 0.05) - 10.0
    assert _rms_db(stem, 6.35, 0.04) < _rms_db(stem, 5.45, 0.05) - 10.0
    # The mixed stem is the voice plus that bed, as long as the film.
    with wave.open(str(mixed["path"]), "rb") as out:
        assert out.getnframes() / out.getframerate() == pytest.approx(6.4, abs=0.03)


@requires_ffmpeg
def test_without_a_bed_the_mix_is_the_voice_alone(tmp_path: Path):
    voice = _tone(tmp_path / "voice.wav", "0.5*sin(2*PI*330*t)", 2.0)
    mixed = toolchain.mix_bed(
        FFMPEG, voice, tmp_path / "mixed.wav", bed=None, duration=2.0, work_dir=tmp_path
    )
    assert mixed["bed"] is None
    assert Path(mixed["path"]) == voice


def _library(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "music_library.json"
    path.write_text(json.dumps({"tracks": entries}), encoding="utf-8")
    return path


def _entry(tmp_path: Path, track_id: str, *, data: bytes = b"RIFF-bed", **overrides) -> dict:
    file = tmp_path / f"{track_id}.wav"
    file.write_bytes(data)
    entry = {
        "id": track_id,
        "kind": "music",
        "file": file.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "licence": "Licență comercială a Proprietarului (test)",
        "commercial_ok": True,
        "redistributable": False,
        "attribution": None,
        "mood": ["calm"],
        "bpm": 80,
    }
    entry.update(overrides)
    return entry


def test_a_track_without_commercial_use_is_never_chosen(tmp_path: Path):
    tense = _entry(tmp_path, "tense-but-personal", commercial_ok=False, mood=["tense", "dark"])
    plain = _entry(tmp_path, "plain", data=b"RIFF-plain", mood=["calm"])
    library = music_library.load_library(_library(tmp_path, [tense, plain]))
    chosen = music_library.choose_bed(library, mood_text="a tense, dark night", seed="film")
    assert chosen is not None and chosen.id == "plain"
    # Alone, the perfect match is still never used.
    only = music_library.load_library(_library(tmp_path, [tense]))
    assert music_library.choose_bed(only, mood_text="a tense, dark night", seed="film") is None


@pytest.mark.parametrize(
    "broken",
    [
        {"commercial_ok": None},  # not stated is not a yes
        {"licence": ""},
        {"sha256": "0" * 64},  # the bytes are not the ones the Owner recorded
        {"file": "missing.wav"},
        {"file": "../outside.wav"},  # never outside the library's folder
    ],
)
def test_a_track_the_library_cannot_vouch_for_is_never_chosen(tmp_path: Path, broken: dict):
    library = music_library.load_library(_library(tmp_path, [_entry(tmp_path, "bed", **broken)]))
    assert music_library.choose_bed(library, mood_text="calm", seed="film") is None
    assert library.refused, "the refusal is recorded with its reason"


def test_the_bed_follows_the_films_mood(tmp_path: Path):
    calm = _entry(tmp_path, "calm", data=b"a", mood=["calm", "wonder"])
    tense = _entry(tmp_path, "tense", data=b"b", mood=["tense", "mystery"])
    library = music_library.load_library(_library(tmp_path, [calm, tense]))
    picked = music_library.choose_bed(
        library, mood_text="Un mister: cine a dispărut în noapte?", seed="f"
    )
    assert picked is not None and picked.id == "tense"
    picked = music_library.choose_bed(library, mood_text="the quiet wonder of space", seed="f")
    assert picked is not None and picked.id == "calm"


def test_the_shipped_library_is_empty_and_well_formed():
    library = music_library.load_library()
    assert library.tracks == [] and library.refused == []


# ------------------------------------------------------------------------- in a real render --


class EdgeSilenceVoice:
    """A narrator whose takes carry the vendor's silence: 0.40 s before the words and
    0.45 s after them, with character alignment timed from 0.40 s."""

    PROVIDER_NAME = "TEST_EDGE_VOICE"
    model = "test-voice"
    voice_id = "voice-1"
    integration_id = "conn-voice"
    LEAD, WORDS, TRAIL = 0.40, 1.20, 0.45

    async def synthesize(self, text, **_kwargs):
        from app.providers.media_base import TTSResult

        rate = 48000
        silence = lambda seconds: b"\x00\x00" * int(seconds * rate)  # noqa: E731
        tone = b"".join(
            int(9000 * math.sin(2 * math.pi * 220 * n / rate)).to_bytes(2, "little", signed=True)
            for n in range(int(self.WORDS * rate))
        )
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(silence(self.LEAD) + tone + silence(self.TRAIL))
        words = text.split()
        step = self.WORDS / len(words)
        characters, begin, end = [], [], []
        for position, word in enumerate(words):
            start = self.LEAD + position * step
            if position:
                characters.append(" ")
                begin.append(start - 0.01)
                end.append(start)
            for offset, char in enumerate(word):
                characters.append(char)
                begin.append(start + offset * step / (len(word) + 1))
                end.append(start + (offset + 1) * step / (len(word) + 1))
        return TTSResult(
            audio_bytes=buffer.getvalue(),
            format="wav",
            duration_seconds=self.LEAD + self.WORDS + self.TRAIL,
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


def _render(engine, tmp_path: Path, voice, scenes: int = 3) -> dict:
    from test_motion import StubImages
    from test_phase5_media import _seeded_storyboard

    sb_id, _ = _seeded_storyboard(engine, tmp_path, scenes=scenes)
    return assemble_video_job(
        engine,
        sb_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=StubImages(),
        tts_adapter=voice,
        environment="TEST",
    )


@requires_ffmpeg
def test_the_vendors_silence_is_trimmed_and_no_cut_carries_dead_air(
    engine, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(music_library, "LIBRARY_PATH", _library(tmp_path, []))
    render = _render(engine, tmp_path, EdgeSilenceVoice())
    production = render["production"]
    for scene in production["scenes"]:
        # The words and a few milliseconds kept either side, not the vendor's silence.
        assert 1.2 <= scene["audio_seconds"] <= 1.3, scene
        trimmed = scene["trimmed_silence"]
        assert trimmed["lead_seconds"] == pytest.approx(0.37, abs=0.03)
        # The tail is cut at the last letter, where the sound dies away (the pause rules'
        # trim_to_last_letter, 2026-10-16): all of the vendor's 0.45 s after the words goes,
        # and no silence is kept after the last sound for the join to add to.
        assert trimmed["trail_seconds"] == pytest.approx(0.45, abs=0.03)
        assert trimmed["takes"][-1]["rule"] == "last_letter"
        assert trimmed["takes"][-1]["kept_tail_seconds"] <= 0.03
    # The captions moved with the words: the first word now starts at the take's start.
    film = Path(render["file_path"])
    srt = (film.parent / "captions.srt").read_text(encoding="utf-8")
    assert srt.split("\n")[1].startswith("00:00:00,0")
    # The joined narration (the Owner's «pauza vocii», 2026-10-16): at each cut the pause
    # frozen for it when the film was built, heard to within a frame (the kept edges, the pad
    # and the frame rounding), and nothing more: the vendor's own silence (0.37 s before,
    # 0.45 s after) is gone, and no silence inside the voice runs past the 1.2 s ceiling.
    spans = production["timeline"]["spans"]
    joins = [span["pause"] for span in spans]
    assert all(pause is not None for pause in joins)
    for pause in joins:
        assert pause["heard"] == pytest.approx(pause["planned"], abs=1 / 24 + 1e-3), pause
    voice_track = film.parent / VOICE_TRACK_NAME
    with wave.open(str(voice_track), "rb") as out:
        length = out.getnframes() / out.getframerate()
    inside = [(a, b) for a, b in _gaps(voice_track) if b < length - 0.01 and a > 0.01]
    assert inside, "the cuts are measured"
    longest = max(pause["planned"] for pause in joins[:-1])
    assert all(b - a <= longest + 1 / 24 + 0.01 for a, b in inside), (inside, joins)
    assert all(b - a <= 1.2 for a, b in inside), inside
    # Measured on the voice track, never read back from the record: at every cut between two
    # takes the silence the meter hears is the pause planned there, to within a frame and the
    # detector's resolution, neither shorter nor longer (the voice's tone runs whole between
    # cuts, so each silence inside the track is one join).
    assert len(inside) == len(joins) - 1, (inside, joins)
    for pause, (start, end) in zip(joins[:-1], inside, strict=True):
        assert start - 0.01 <= pause["cut_at"] <= end + 1 / 24 + 0.01, (pause, start, end)
        assert end - start == pytest.approx(pause["planned"], abs=1 / 24 + 0.01), (pause, start)


@requires_ffmpeg
def test_an_empty_library_renders_the_voice_alone_and_says_so(engine, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(music_library, "LIBRARY_PATH", _library(tmp_path, []))
    from test_phase5_media import AlignedVoice

    production = _render(engine, tmp_path, AlignedVoice(aligned=True), scenes=2)["production"]
    audio = production["audio"]
    assert audio["bed"] is None
    assert "muzică" in audio["advisory"]


@requires_ffmpeg
def test_a_licensed_bed_is_mixed_under_the_film_and_recorded(engine, tmp_path: Path, monkeypatch):
    folder = tmp_path / "library"
    folder.mkdir()
    bed = _tone(folder / "bed.wav", "0.5*sin(2*PI*110*t)|0.5*sin(2*PI*111*t)", 20.0, channels=2)
    entry = {
        "id": "bed-1",
        "kind": "music",
        "file": "bed.wav",
        "sha256": hashlib.sha256(bed.read_bytes()).hexdigest(),
        "licence": "Licență comercială a Proprietarului (test)",
        "commercial_ok": True,
        "redistributable": False,
        "attribution": "Music: Test Bed by Nobody (CC BY 4.0)",
        "mood": ["calm"],
        "bpm": 70,
    }
    library = folder / "music_library.json"
    library.write_text(json.dumps({"tracks": [entry]}), encoding="utf-8")
    monkeypatch.setattr(music_library, "LIBRARY_PATH", library)
    from app.media.qc import audio_mix_verdict
    from test_phase5_media import AlignedVoice

    render = _render(engine, tmp_path, AlignedVoice(aligned=True), scenes=2)
    audio = render["production"]["audio"]
    assert audio["bed"]["track_id"] == "bed-1"
    assert audio["bed"]["licence"] == entry["licence"]
    assert audio["bed"]["attribution"] == entry["attribution"]
    assert 18.0 <= audio["bed"]["measured_lu_under_voice"] <= 22.0
    assert audio["attributions"] == [entry["attribution"]]
    assert audio_mix_verdict(render["production"])["passed"] is True
    # The film itself carries sound between the words now: no digital silence inside it.
    film = Path(render["file_path"])
    assert not [
        span
        for span in toolchain.silence_spans(FFMPEG, film, threshold_db=-70.0, min_seconds=0.2) or []
        if span[0] > 0.5
    ]
