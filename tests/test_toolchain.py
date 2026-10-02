"""STUDIO_FFPROBE_PATH is read from .env like every other setting (REL-13).

The preflight told the Owner to set STUDIO_FFPROBE_PATH, and the setting only worked as a
process environment variable: `find_ffprobe` and `scripts/start.py` read ``os.environ`` and
never the .env file the preflight sends him to. Every .env here is a tmp file.
"""

from __future__ import annotations

import importlib.util
import os
import secrets
import sys

import pytest
from app.config import ROOT, Settings
from app.media import toolchain
from app.runbook.preflight import run_preflight


@pytest.fixture
def chosen_ffprobe(tmp_path, monkeypatch):
    """An ffprobe named only in a .env file: not on PATH, not beside any ffmpeg, not in the
    process environment."""
    suffix = ".exe" if os.name == "nt" else ""
    probe = tmp_path / "tools" / f"ffprobe-chosen{suffix}"
    probe.parent.mkdir()
    probe.write_bytes(b"")
    env = tmp_path / ".env"
    env.write_text(f'STUDIO_FFPROBE_PATH="{probe.as_posix()}"\n', encoding="utf-8")
    monkeypatch.delenv("STUDIO_FFPROBE_PATH", raising=False)
    monkeypatch.delenv("STUDIO_FFMPEG_PATH", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(toolchain, "ENV_FILE", env)
    return probe, env


def test_an_ffprobe_path_in_the_env_file_is_used_by_find_ffprobe(chosen_ffprobe):
    probe, _env = chosen_ffprobe
    assert toolchain.find_ffprobe() == probe.as_posix()


def test_the_settings_carry_it_and_the_preflight_uses_it(chosen_ffprobe, engine, tmp_path):
    probe, env = chosen_ffprobe
    settings = Settings(
        _env_file=env,
        owner_token=secrets.token_urlsafe(48),
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        worker_enabled=False,
    )
    assert settings.ffprobe_path == probe.as_posix()
    assert toolchain.find_ffprobe(None, configured=settings.ffprobe_path) == probe.as_posix()

    line = next(
        check
        for check in run_preflight(engine, settings, None)["checks"]
        if check["name"] == "media_inspection"
    )
    assert line["ok"] is True, line
    assert line["technical"]["paths"] == [probe.as_posix()]


def test_start_reports_the_ffprobe_the_settings_name(chosen_ffprobe, tmp_path):
    probe, env = chosen_ffprobe
    spec = importlib.util.spec_from_file_location("start_script", ROOT / "scripts/start.py")
    start = importlib.util.module_from_spec(spec)
    sys.modules["start_script"] = start
    spec.loader.exec_module(start)
    settings = Settings(_env_file=env, owner_token=secrets.token_urlsafe(48))
    _ffmpeg, ffprobe = start.toolchain_paths(settings)
    assert ffprobe == probe.as_posix()
    source = (ROOT / "scripts/start.py").read_text(encoding="utf-8")
    assert 'os.environ.get("STUDIO_FFPROBE_PATH")' not in source
