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
