"""The launcher tells a buyer the truth about his studio (SELL-06, SELL-18, SELL-03).

It used to read YouTube from STUDIO_YOUTUBE_* variables and print "YouTube publishing:
DISABLED" while a channel was connected in the page, and it said nothing about which FFmpeg
features a film would lose. It now reads the studio's own preflight from the database, lists
each filter and encoder a film needs, and starts the demo on its own folder.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from app.config import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import start  # noqa: E402

sys.path.remove(str(ROOT / "scripts"))


def test_the_report_reads_the_studio_not_the_environment(engine, settings, capsys):
    start.preflight_report(settings)
    out = capsys.readouterr().out
    # The studio's own preflight, in the Owner's words, from the database.
    assert "Autonomia studioului este oprită" in out
    assert "STUDIO_YOUTUBE_CLIENT_ID" not in out
    assert "Setări" in out
    assert "Cheia Proprietarului" in out


def test_every_missing_filter_and_encoder_is_named_with_what_the_film_loses(capsys):
    present = {"loudnorm", "xfade", "aac"}
    lines = start.toolchain_report(
        "ffmpeg-test",
        has_filter=lambda _ffmpeg, name: name in present,
        has_encoder=lambda _ffmpeg, name: name in present,
    )
    text = "\n".join(lines)
    assert "subtitles" in text and "subtitrările" in text
    assert "libx264" in text
    assert "loudnorm" not in text
    assert all(line.strip() for line in lines)


def test_a_complete_encoder_reports_nothing_lost():
    lines = start.toolchain_report(
        "ffmpeg-test", has_filter=lambda *_: True, has_encoder=lambda *_: True
    )
    assert len(lines) == 1 and "toate" in lines[0]


def test_no_encoder_says_how_to_install_one():
    text = "\n".join(start.toolchain_report(None))
    assert "winget install Gyan.FFmpeg" in text
    assert "apt install ffmpeg" in text and "brew install ffmpeg" in text


def test_the_demo_runs_on_its_own_folder_and_port(tmp_path):
    env = start.demo_environment(tmp_path / "demo", 8010)
    assert env["STUDIO_DEMO_MODE"] == "true"
    assert env["STUDIO_DATABASE_URL"] == f"sqlite:///{(tmp_path / 'demo' / 'demo.db').as_posix()}"
    assert env["STUDIO_MEDIA_ROOT"] == str(tmp_path / "demo" / "media")
    assert env["STUDIO_PORT"] == "8010"
    assert env["STUDIO_TRENDS_ENABLED"] == "false"
    for key in ("STUDIO_BACKUP_DIR", "STUDIO_LOG_DIR", "STUDIO_OFFICE_KEPT_FRAME_DIR"):
        assert Path(env[key]).is_relative_to(tmp_path / "demo"), key


def test_the_demo_refuses_the_studios_own_data_folder():
    with pytest.raises(SystemExit):
        start.demo_environment(ROOT / "data", 8010)


def test_the_demo_flag_is_offered():
    parser = start.build_parser()
    args = parser.parse_args(["--demo", "--demo-port", "8011"])
    assert args.demo is True and args.demo_port == 8011
    assert parser.parse_args([]).demo is False


def test_the_launcher_prints_romanian_on_a_redirected_cp1252_console(tmp_path):
    """The service sends the console to a file in the ANSI code page; ș must not end the start."""
    import subprocess

    out = tmp_path / "out.txt"
    code = (
        "import sys; sys.path.insert(0, r'" + str(ROOT / "scripts") + "'); import start; "
        "start.utf8_console(); print(start.toolchain_report(None)[0]); "
        "print(start.REQUIRED_FILTERS['zscale'])"
    )
    env = {**__import__("os").environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    with out.open("wb") as sink:
        done = subprocess.run([sys.executable, "-c", code], stdout=sink, env=env, check=False)
    assert done.returncode == 0
    assert "NU a fost găsit" in out.read_text(encoding="utf-8")
