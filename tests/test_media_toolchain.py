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
