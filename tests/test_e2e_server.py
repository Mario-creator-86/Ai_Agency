"""scripts/e2e_server.py never takes the Owner's port, his folders or his built page (PAGE-15)."""

from __future__ import annotations

import importlib.util
import json
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
    assert settings.local_auto_login is False  # the flows sign in through the form
    assert (
        str(tmp_path) in settings.database_url.replace("/", "\\")
        or str(tmp_path.as_posix()) in settings.database_url
    )


def test_original_art_identity_binding_is_refused_outside_the_test_folder(engine, tmp_path):
    with pytest.raises(SystemExit, match="disposable"):
        e2e_server.bind_scene_identities(engine, tmp_path / "different")


def test_fresh_fixture_hires_bind_original_art_and_preserve_immutable_history(engine):
    from app.agents.models import Agent
    from app.agents.services import seed_initial_workforce
    from app.models import DomainEvent
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session

    seed_initial_workforce(engine)
    with Session(engine) as session:
        previous = [(e.event_id, e.aggregate_id) for e in session.scalars(select(DomainEvent))]
    folder = Path(engine.url.database).parent
    e2e_server.bind_scene_identities(engine, folder)
    bible = json.loads(
        (ROOT / "frontend/tests/fixtures/pixel_actors_bible.json").read_text(encoding="utf-8")
    )
    with Session(engine) as session:
        assert set(session.scalars(select(Agent.id))) == {c["employee_id"] for c in bible}
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
        for event_id, aggregate_id in previous:
            assert (
                session.scalar(
                    select(DomainEvent).where(DomainEvent.event_id == event_id)
                ).aggregate_id
                == aggregate_id
            )
        for agent in session.scalars(select(Agent)):
            assert (
                session.scalar(
                    select(DomainEvent).where(DomainEvent.event_id == agent.event_id)
                ).aggregate_id
                == agent.id
            )
        agent.version = 2
        session.commit()
    with pytest.raises(SystemExit, match="fresh"):
        e2e_server.bind_scene_identities(engine, folder)
