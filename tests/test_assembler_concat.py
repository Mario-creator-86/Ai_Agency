"""FFmpeg concat lists name every file so that an apostrophe in a path survives (SEC-09).

The concat demuxer reads ``file '<path>'``. A buyer whose install or media folder has an
apostrophe in it (C:/Users/O'Brien/...) got a broken list and a failed film: inside single quotes
nothing can be escaped, so a quote is written by closing the quotes, escaping it, and opening them
again: ``'\\''``. A backslash needs nothing inside quotes (it is taken as it is), so it is not
doubled; the lists use forward slashes anyway.
"""

from __future__ import annotations

import ast
import subprocess
import wave
from pathlib import Path

import pytest
from app.media import assembler
from app.media.assembler import concat_line
from app.media.toolchain import find_ffmpeg, find_ffprobe


def test_a_plain_path_is_quoted():
    assert concat_line(Path("C:/studio/media/a.wav")) == "file 'C:/studio/media/a.wav'\n"


def test_an_apostrophe_is_closed_escaped_and_reopened(tmp_path):
    path = tmp_path / "o'brien" / "a.mp4"
    assert concat_line(path) == f"file '{tmp_path.as_posix()}/o'\\''brien/a.mp4'\n"
    assert concat_line("it's") == "file 'it'\\''s'\n"
    assert concat_line("''") == "file ''\\'''\\'''\n"


def test_a_relative_name_stays_relative():
    assert concat_line("frame_001.png") == "file 'frame_001.png'\n"


def test_every_concat_list_in_the_assembler_is_written_through_the_helper():
    """No f-string ``file '...'`` is left beside the helper: one escaped writer, everywhere."""
    source = Path(assembler.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    raw = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        and any(
            isinstance(part, ast.Constant)
            and isinstance(part.value, str)
            and part.value.startswith("file '")
            for part in node.values
        )
    ]
    assert raw == [], f"concat lines written by hand at lines {raw}"


def _tone(path: Path, seconds: float = 0.4) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 16000
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x10" * int(rate * seconds))
    return path


@pytest.mark.skipif(find_ffmpeg() is None or find_ffprobe() is None, reason="ffmpeg not installed")
def test_ffmpeg_reads_a_list_whose_folder_has_an_apostrophe(tmp_path):
    folder = tmp_path / "O'Brien's studio"
    parts = [_tone(folder / f"part {n}'s.wav") for n in range(2)]
    listing = folder / "list.txt"
    listing.write_text("".join(concat_line(p.as_posix()) for p in parts), encoding="utf-8")
    output = tmp_path / "joined.wav"
    run = subprocess.run(  # noqa: S603
        [
            str(find_ffmpeg()),
            "-nostdin",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            str(output),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert run.returncode == 0, run.stderr[-800:]
    probe = subprocess.run(  # noqa: S603
        [
            str(find_ffprobe()),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert abs(float(probe.stdout.strip()) - 0.8) < 0.05
