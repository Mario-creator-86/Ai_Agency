"""scripts/e2e_server.py never takes the Owner's port, his folders or his built page (PAGE-15)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("e2e_server", ROOT / "scripts" / "e2e_server.py")
assert spec and spec.loader
e2e_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e2e_server)


@pytest.fixture
def page(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    return dist


def test_a_scratch_page_a_temp_folder_and_a_free_port_are_accepted(page, tmp_path):
    e2e_server.check_places(page, tmp_path / "world", e2e_server.free_port())


def test_the_studios_port_is_refused(page, tmp_path):
    with pytest.raises(SystemExit, match="8000"):
        e2e_server.check_places(page, tmp_path / "world", 8000)


@pytest.mark.parametrize("owned", ["data", "backend/storage", "frontend/dist"])
def test_the_studios_folders_are_refused_as_the_world(page, owned):
    with pytest.raises(SystemExit, match="temporar"):
        e2e_server.check_places(page, ROOT / owned / "e2e", e2e_server.free_port())


def test_the_studios_own_built_page_is_refused(tmp_path):
    with pytest.raises(SystemExit, match="frontend/dist"):
        e2e_server.check_places(ROOT / "frontend" / "dist", tmp_path / "w", e2e_server.free_port())


def test_a_folder_without_a_built_page_is_refused(tmp_path):
    with pytest.raises(SystemExit, match="index.html"):
        e2e_server.check_places(tmp_path, tmp_path / "w", e2e_server.free_port())


def test_the_settings_reach_nothing_beyond_the_machine(tmp_path):
    settings = e2e_server.build_settings(tmp_path, "t" * 48)
    assert settings.worker_enabled is False
    assert settings.trends_enabled is False
    assert settings.office_weather_host is None
    assert settings.office_unreal_remote_url is None
    assert settings.min_free_gb == 0
    assert (
        str(tmp_path) in settings.database_url.replace("/", "\\")
        or str(tmp_path.as_posix()) in settings.database_url
    )
