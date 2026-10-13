"""Finding the encoder, including the half of it that is not on PATH.

The Owner's machine had FFmpeg installed through WinGet, which puts `ffmpeg.exe` on PATH and
leaves `ffprobe.exe` beside it in the package folder. Three different pieces of the studio
resolved the toolchain three different ways: the renderer looked at an environment variable and
PATH, quality control and the preflight check looked at PATH alone, and the router passed the
configured path to the renderer but to nothing else.

The result was a studio that reported "media inspection unavailable" with ffprobe sitting next to
its own configured ffmpeg, and five media tests that skipped themselves on a machine with a
working encoder — hiding, as it turned out, nothing broken, but hiding it all the same.

There is one resolver now, and these tests hold it to the order it promises.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from app.media.toolchain import find_ffmpeg, find_ffprobe


@pytest.fixture
def fake_toolchain(tmp_path, monkeypatch):
    """A folder holding both binaries, with neither of them on PATH."""
    folder = tmp_path / "bin"
    folder.mkdir()
    suffix = ".exe" if os.name == "nt" else ""
    ffmpeg = folder / f"ffmpeg{suffix}"
    ffprobe = folder / f"ffprobe{suffix}"
    ffmpeg.write_bytes(b"")
    ffprobe.write_bytes(b"")
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.delenv("STUDIO_FFPROBE_PATH", raising=False)
    return ffmpeg, ffprobe


def test_ffprobe_is_found_beside_the_configured_encoder(fake_toolchain, monkeypatch):
    ffmpeg, ffprobe = fake_toolchain
    # Nothing on PATH and no explicit ffprobe setting: the only clue is where ffmpeg lives.
    monkeypatch.setattr("app.media.toolchain._configured_ffmpeg", lambda: str(ffmpeg))

    assert find_ffprobe(str(ffmpeg)) == str(ffprobe)
    assert find_ffprobe() == str(ffprobe)


def test_an_explicit_ffprobe_setting_wins(fake_toolchain, tmp_path, monkeypatch):
    ffmpeg, beside = fake_toolchain
    chosen = tmp_path / "chosen-ffprobe"
    chosen.write_bytes(b"")
    monkeypatch.setenv("STUDIO_FFPROBE_PATH", str(chosen))

    assert find_ffprobe(str(ffmpeg)) == str(chosen)


def test_a_configured_path_that_is_not_there_falls_back_rather_than_being_believed(
    tmp_path, monkeypatch
):
    """A stale setting must not stop the studio using an encoder that is on PATH."""
    on_path = tmp_path / "path-ffmpeg"
    on_path.write_bytes(b"")
    monkeypatch.setattr("shutil.which", lambda name: str(on_path) if name == "ffmpeg" else None)

    assert find_ffmpeg(str(tmp_path / "does-not-exist")) == str(on_path)


def test_nothing_anywhere_reads_as_nothing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("app.media.toolchain._configured_ffmpeg", lambda: None)
    monkeypatch.delenv("STUDIO_FFPROBE_PATH", raising=False)

    assert find_ffmpeg() is None
    assert find_ffprobe() is None


def test_the_renderer_and_the_inspector_agree(monkeypatch, tmp_path):
    """One resolver, so a render cannot succeed while inspection reports no toolchain."""
    from app.media.assembler import resolve_ffmpeg_path

    marker = tmp_path / "ffmpeg"
    marker.write_bytes(b"")
    monkeypatch.setattr("app.media.toolchain._configured_ffmpeg", lambda: str(marker))
    monkeypatch.setattr("shutil.which", lambda name: None)

    assert resolve_ffmpeg_path() == find_ffmpeg() == str(marker)


def test_the_studios_own_encoder_is_discoverable_here():
    """A live check on this machine: whatever is configured, both halves resolve together.

    Skipped where no encoder exists at all, because then there is nothing to be consistent about.
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        pytest.skip("no FFmpeg on this machine")
    probe = find_ffprobe()
    assert probe is not None, f"ffmpeg at {ffmpeg} but no ffprobe found"
    assert Path(probe).is_file()


# --------------------------------------------------------------------------- loudness
# The renderer normalises and quality control measures with the same reading of the same
# filter, so the two can never disagree about how loud a film is. Before this, nothing
# measured loudness at all (grep loudnorm: none) and a film left at whatever the voice
# vendor returned was a film the platform turned down or up on its own terms.

LOUDNORM_STDERR = """
[graph 0 input from stream 0:0 @ 0x1] tb:1/48000 samplefmt:s16 samplerate:48000 chlayout:mono
[Parsed_loudnorm_0 @ 0x2]
{
\t"input_i" : "-23.10",
\t"input_tp" : "-5.20",
\t"input_lra" : "6.30",
\t"input_thresh" : "-33.40",
\t"output_i" : "-14.02",
\t"output_tp" : "-1.00",
\t"output_lra" : "6.10",
\t"output_thresh" : "-24.10",
\t"normalization_type" : "linear",
\t"target_offset" : "0.02"
}
size=N/A time=00:00:12.00 bitrate=N/A speed= 105x
"""


def test_the_loudnorm_report_is_read_out_of_the_encoders_chatter():
    from app.media.toolchain import parse_loudnorm_json

    measured = parse_loudnorm_json(LOUDNORM_STDERR)
    assert measured is not None
    assert measured["integrated_lufs"] == -23.1
    assert measured["true_peak_dbtp"] == -5.2
    assert measured["loudness_range_lu"] == 6.3
    assert measured["threshold_lufs"] == -33.4
    assert measured["target_offset_lu"] == 0.02
    # Chatter without a report reads as nothing measured, never as a number.
    assert parse_loudnorm_json("size=N/A time=00:00:12.00") is None
    # Silence measures as -inf, which is a reading too: the film has no sound to normalise.
    silent = parse_loudnorm_json(LOUDNORM_STDERR.replace('"-23.10"', '"-inf"'))
    assert silent is not None and silent["integrated_lufs"] == float("-inf")


def test_the_normalising_filter_is_two_pass_when_measured_and_one_pass_otherwise():
    from app.media.toolchain import (
        LOUDNESS_RANGE_LU,
        LOUDNESS_TARGET_LUFS,
        TRUE_PEAK_TARGET_DBTP,
        loudnorm_filter,
        parse_loudnorm_json,
    )

    assert LOUDNESS_TARGET_LUFS == -14.0
    one_pass = loudnorm_filter(None)
    assert one_pass.startswith("loudnorm=")
    assert f"I={LOUDNESS_TARGET_LUFS:.1f}" in one_pass
    assert f"TP={TRUE_PEAK_TARGET_DBTP:.1f}" in one_pass
    assert f"LRA={LOUDNESS_RANGE_LU:.1f}" in one_pass
    assert "measured_I" not in one_pass

    two_pass = loudnorm_filter(parse_loudnorm_json(LOUDNORM_STDERR))
    assert "measured_I=-23.10" in two_pass
    assert "measured_TP=-5.20" in two_pass
    assert "measured_LRA=6.30" in two_pass
    assert "measured_thresh=-33.40" in two_pass
    assert "offset=0.02" in two_pass
    assert "linear=true" in two_pass

    # A silent measurement cannot steer a second pass: it falls back to the one-pass filter.
    assert loudnorm_filter(parse_loudnorm_json(LOUDNORM_STDERR.replace('"-23.10"', '"-inf"'))) == (
        one_pass
    )


@pytest.mark.skipif(find_ffmpeg() is None, reason="no FFmpeg on this machine")
def test_a_synthetic_tone_is_measured_by_the_encoder(tmp_path):
    """A live measurement: a tone at a known level reads back at about that level."""
    import subprocess

    from app.media.toolchain import has_filter, measure_loudness

    ffmpeg = find_ffmpeg()
    tone = tmp_path / "tone.wav"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=4",
            "-af",
            "volume=0.1",
            str(tone),
        ],
        check=True,
        capture_output=True,
    )
    measured = measure_loudness(ffmpeg, tone)
    assert measured is not None, "the encoder has loudnorm and the tone is four seconds long"
    # The generator's sine and the volume filter put the tone around -42 LUFS on this
    # encoder; the assertion is loose because the point is that a number came back.
    assert -60.0 < measured["integrated_lufs"] < -20.0
    assert measured["true_peak_dbtp"] < -20.0
    assert measure_loudness(ffmpeg, tmp_path / "missing.wav") is None
    assert has_filter(ffmpeg, "loudnorm") is True
    assert has_filter(ffmpeg, "no_such_filter_anywhere") is False


# --------------------------------------------------------------------------- the master
# The Nepal film peaked at -0.93 dBTP after a loudnorm that aimed at -1.0 exactly, and quality
# control refused it for 0.07 dB. The target now sits a full dB under the ceiling, a sample
# limiter holds whatever the loudness filter lets through, and the AAC encode happens once.


def test_the_master_aims_two_db_under_a_ceiling_that_stays_at_minus_one():
    from app.media.toolchain import (
        LIMITER_LIMIT,
        TRUE_PEAK_CEILING_DBTP,
        TRUE_PEAK_TARGET_DBTP,
        loudnorm_filter,
        master_audio_filter,
        parse_loudnorm_json,
    )

    assert TRUE_PEAK_TARGET_DBTP == -2.0
    assert TRUE_PEAK_CEILING_DBTP == -1.0
    one_pass = loudnorm_filter(None)
    two_pass = loudnorm_filter(parse_loudnorm_json(LOUDNORM_STDERR))
    for chain in (one_pass, two_pass):
        assert "TP=-2.0" in chain and "linear=true" in chain and "I=-14.0" in chain

    master = master_audio_filter(parse_loudnorm_json(LOUDNORM_STDERR))
    steps = master.split(",")
    # Loudness first, then back to 48 kHz, then the limiter; auto-level off, or the limiter
    # would lift the whole film back up to its limit.
    assert steps[0].startswith("loudnorm=") and "measured_I=-23.10" in steps[0]
    assert steps.index("aresample=48000") > 0
    limiter = next(step for step in steps if step.startswith("alimiter="))
    assert steps.index(limiter) > steps.index("aresample=48000")
    assert "level=0" in limiter.split("=", 1)[1].split(":")
    assert f"limit={LIMITER_LIMIT:.2f}" in limiter
    # 0.79 of full scale is -2.05 dBFS: the limiter holds the target, not the ceiling.
    assert -2.1 < 20 * __import__("math").log10(LIMITER_LIMIT) < -2.0

    # Padded to the picture and cut there, so the audio never outlasts the film.
    padded = master_audio_filter(None, duration=12.5)
    assert padded.endswith("apad=whole_dur=12.500,atrim=duration=12.500")
    # An encoder without loudnorm still gets the resample and the limiter.
    bare = master_audio_filter(None, normalise=False)
    assert not bare.startswith("loudnorm") and "alimiter=" in bare


def test_the_audio_is_encoded_once_as_aac_lc_256k_stereo_48k():
    from app.media.toolchain import AUDIO_CODEC_ARGS

    args = list(AUDIO_CODEC_ARGS)
    assert args[args.index("-c:a") + 1] == "aac"
    assert args[args.index("-profile:a") + 1] == "aac_low"
    assert args[args.index("-b:a") + 1] == "256k"
    assert args[args.index("-ac") + 1] == "2"
    assert args[args.index("-ar") + 1] == "48000"


def test_a_dynamic_loudnorm_pass_is_a_warning_for_the_owner():
    from app.media.toolchain import loudnorm_warning, parse_loudnorm_json

    linear = parse_loudnorm_json(LOUDNORM_STDERR)
    assert loudnorm_warning(linear) is None
    dynamic = parse_loudnorm_json(LOUDNORM_STDERR.replace('"linear"', '"dynamic"'))
    warning = loudnorm_warning(dynamic)
    assert warning is not None
    # Romanian, and it names what happened and what he should do.
    assert "dinamic" in warning and "ascultați" in warning.lower()
    # No report means nothing is known: no warning is invented.
    assert loudnorm_warning(None) is None


def _hot_fixture(ffmpeg: str, target: Path, expression: str, seconds: float = 6.0) -> None:
    import subprocess

    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc='{expression}':s=48000:d={seconds}",
            "-c:a",
            "pcm_s24le",
            str(target),
        ],
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )


@pytest.mark.skipif(find_ffmpeg() is None, reason="no FFmpeg on this machine")
@pytest.mark.parametrize(
    ("name", "expression", "expected_type"),
    [
        # A steady sine peaking at -3 dBTP: loudnorm cannot use a linear gain on a signal
        # with no loudness range and falls back to dynamic mode.
        ("steady", "0.708*sin(2*PI*997*t)", "dynamic"),
        # The same peak with a slow swell: a range, so the second pass is one linear gain.
        ("swelling", "0.708*(0.3+0.7*abs(sin(2*PI*0.4*t)))*sin(2*PI*997*t)", "linear"),
    ],
)
def test_a_hot_tone_mastered_and_aac_encoded_lands_under_the_ceiling(
    tmp_path, name, expression, expected_type
):
    from app.media.toolchain import encode_master_audio, measure_loudness

    ffmpeg = find_ffmpeg()
    assert ffmpeg is not None
    source = tmp_path / f"{name}.wav"
    _hot_fixture(ffmpeg, source, expression)
    before = measure_loudness(ffmpeg, source)
    assert before is not None and -3.2 <= before["true_peak_dbtp"] <= -2.8

    target = tmp_path / f"{name}.m4a"
    result = encode_master_audio(ffmpeg, source, target)
    assert result["passes"] == 2
    assert result["normalization_type"] == expected_type
    # The fallback to dynamic mode is written down for the Owner, the linear pass is not.
    assert (result["warning"] is not None) == (expected_type == "dynamic")

    # Measured on the delivered AAC file, not taken from the filter's own report.
    delivered = measure_loudness(ffmpeg, target)
    assert delivered is not None
    assert delivered["true_peak_dbtp"] <= -1.5, delivered
    assert -15.0 <= delivered["integrated_lufs"] <= -13.0, delivered
    assert result["delivered"]["true_peak_dbtp"] == pytest.approx(delivered["true_peak_dbtp"])


#: Narration-like: quiet syllables with short hot consonants. ElevenLabs takes measure like
#: this (the six Nepal voices: -23 to -25 LUFS with true peaks of -3 to -6 dBTP), so reaching
#: -14 LUFS by one gain would push the peaks far over -2 dBTP.
SPEECH_LIKE = (
    "0.06*sin(2*PI*180*t)*(0.5+0.5*sin(2*PI*4*t))*(gt(sin(2*PI*2.3*t),-0.3))"
    " + 0.55*sin(2*PI*900*t)*lt(mod(t,0.37),0.004)"
)


@pytest.mark.skipif(find_ffmpeg() is None, reason="no FFmpeg on this machine")
def test_quiet_narration_with_hot_peaks_is_limited_first_and_lands_in_the_band(tmp_path):
    """The zero-credit Nepal rehearsal (2026-10-01): the real narration measured -23.97 LUFS
    with -3.31 dBTP peaks. loudnorm could not use one linear gain, fell back to dynamic mode
    and delivered -15.57 LUFS, outside QC's -15..-13 band: every real film would have failed
    audio QC after its credits were spent. The peaks are now limited before the gain, so one
    linear gain reaches -14 LUFS under the -2.0 dBTP target."""
    from app.media.toolchain import encode_master_audio, measure_loudness

    ffmpeg = find_ffmpeg()
    assert ffmpeg is not None
    source = tmp_path / "narration.wav"
    _hot_fixture(ffmpeg, source, SPEECH_LIKE, seconds=26.0)
    before = measure_loudness(ffmpeg, source)
    assert before is not None
    gain = -14.0 - before["integrated_lufs"]
    assert before["true_peak_dbtp"] + gain > -2.0, "the fixture must leave no room for one gain"

    target = tmp_path / "narration.m4a"
    result = encode_master_audio(ffmpeg, source, target)

    delivered = measure_loudness(ffmpeg, target)
    assert delivered is not None
    assert -14.5 <= delivered["integrated_lufs"] <= -13.5, delivered
    assert delivered["true_peak_dbtp"] <= -1.5, delivered
    # A mono narration is made stereo before it is limited, at full level on both sides:
    # the default upmix lowers each side 3 dB, which the limiter would have paid for in
    # 3 dB more limiting and the film would never have used.
    assert delivered["true_peak_dbtp"] >= -3.0, delivered
    assert result["normalization_type"] == "linear"
    assert result["warning"] is None
    assert result["prelimit"]["gain_db"] > 0


@pytest.mark.skipif(find_ffmpeg() is None, reason="no FFmpeg on this machine")
def test_a_master_that_cannot_be_encoded_raises_rather_than_returning_silence(tmp_path):
    from app.media.toolchain import AudioMasterError, encode_master_audio

    ffmpeg = find_ffmpeg()
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not audio at all")
    with pytest.raises(AudioMasterError):
        encode_master_audio(ffmpeg, broken, tmp_path / "out.m4a")


# ------------------------------------------------- the encoder in a film folder of any depth


def _deep_folder(base: Path, length: int = 300) -> Path:
    """A film folder whose path is longer than ``length`` characters (Windows MAX_PATH is
    260): a buyer with a deep install folder or a long user name has one. Measured
    2026-10-01: a 258-character folder given to CreateProcess as the working directory
    failed with NotADirectoryError (WinError 267) and the rehearsal route answered 500."""
    folder = base
    while len(str(folder)) <= length:
        folder = folder / ("f" * 40)
    folder.mkdir(parents=True)
    return folder


@pytest.mark.skipif(find_ffmpeg() is None, reason="no FFmpeg on this machine")
def test_a_shot_is_built_in_a_film_folder_deeper_than_max_path(tmp_path):
    from app.media.assembler import _shot_command, run_encoder

    ffmpeg = find_ffmpeg()
    folder = _deep_folder(tmp_path)
    assert len(str(folder)) > 260
    still = folder / "frame_01.png"
    made = run_encoder(
        [
            ffmpeg,
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:s=320x568:d=1",
            "-frames:v",
            "1",
            str(still),
        ],
        folder,
    )
    assert made.returncode == 0, made.stderr
    target = folder / "shot_01.mp4"

    built = run_encoder(_shot_command(ffmpeg, still, None, 0.5, target, fps=24), folder)

    assert built.returncode == 0, built.stderr
    assert target.is_file() and target.stat().st_size > 0
    # Nothing the encoder needed was left beside the film, and nothing was left behind.
    assert sorted(p.name for p in folder.iterdir()) == ["frame_01.png", "shot_01.mp4"]


@pytest.mark.skipif(find_ffmpeg() is None, reason="no FFmpeg on this machine")
def test_captions_named_relative_to_a_deep_film_folder_are_burnt(tmp_path):
    """The caption filter names its ASS script and font folder relative to the encoder's
    working directory (an absolute Windows path would need escaping twice over); they are
    carried beside the encoder into a short folder, so a deep film folder burns them too."""
    from app.media.assembler import (
        CAPTION_FONTS_DIR,
        CAPTIONS_ASS_NAME,
        ass_captions_filter,
        ass_from_cues,
        has_filter,
        install_caption_fonts,
        run_encoder,
    )

    ffmpeg = find_ffmpeg()
    if not has_filter(ffmpeg, "subtitles"):
        pytest.skip("this FFmpeg has no subtitles filter")
    folder = _deep_folder(tmp_path)
    cues = [{"start": 0.0, "end": 0.9, "lines": ["Everestul crește"], "scene_index": 1}]
    (folder / CAPTIONS_ASS_NAME).write_text(ass_from_cues(cues), encoding="utf-8")
    install_caption_fonts(folder)
    out = folder / "captioned.mp4"

    burnt = run_encoder(
        [
            ffmpeg,
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1080x1920:d=1",
            "-vf",
            ass_captions_filter(),
            "-frames:v",
            "12",
            str(out),
        ],
        folder,
        carry=(CAPTIONS_ASS_NAME, CAPTION_FONTS_DIR),
    )

    assert burnt.returncode == 0, burnt.stderr
    assert out.is_file() and out.stat().st_size > 0


def test_an_encoder_that_cannot_start_is_a_render_engine_reason_in_romanian(tmp_path, monkeypatch):
    """An OSError when the encoder is launched (WinError 267, a missing binary, no memory) is
    RenderEngineUnavailable with words, which the routes answer as 503 rather than a bare 500."""
    from app.media import assembler

    def refuse(*_args, **_kwargs):
        raise NotADirectoryError(267, "The directory name is invalid")

    monkeypatch.setattr(assembler.subprocess, "run", refuse)
    with pytest.raises(assembler.RenderEngineUnavailable) as caught:
        assembler.run_encoder(["ffmpeg", "-version"], tmp_path)
    assert "FFmpeg nu a putut porni" in str(caught.value)
    assert not isinstance(caught.value, OSError)


def test_an_encoder_past_its_time_is_a_render_engine_reason_in_romanian(tmp_path, monkeypatch):
    import subprocess

    from app.media import assembler

    def stall(*_args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=kwargs.get("timeout"))

    monkeypatch.setattr(assembler.subprocess, "run", stall)
    with pytest.raises(assembler.RenderEngineUnavailable) as caught:
        assembler.run_encoder(["ffmpeg", "-version"], tmp_path, timeout=7)
    assert "7 secunde" in str(caught.value)


def test_only_the_encoder_runner_chooses_a_working_directory():
    """A ``cwd=`` naming the film folder is what broke on a deep folder; the assembler's
    encodes all go through run_encoder, which runs them from a short temporary folder."""
    import ast

    from app.media import assembler

    tree = ast.parse(Path(assembler.__file__).read_text(encoding="utf-8"))
    owners = set()
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and any(k.arg == "cwd" for k in node.keywords):
                owners.add(function.name)
    assert owners == {"run_encoder"}, owners
