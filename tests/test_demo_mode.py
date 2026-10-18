"""A buyer can watch the studio make a film without an account anywhere (SELL-03).

The shipped demo ended PARTIAL 10/13 with no film: its stand-in language model answered
yesterday's schemas. The demo is now one switch, `scripts/start.py --demo`: an isolated
database and media folder, every vendor replaced by the local deterministic adapters and a
scripted language model (app.demo), a permanent banner on the page, and the publishing,
payment and connection routes refused. These tests hold it to that: a day runs to a local MP4
FFmpeg encoded, nothing is published, no provider is marked working, and no socket leaves
this machine (tests/conftest.py refuses one).
"""

from __future__ import annotations

import importlib
import shutil
from pathlib import Path

import pytest
from app.config import Settings
from app.db import create_db_engine, migrate
from app.media.toolchain import find_ffmpeg
from app.services import bootstrap_studio
from sqlalchemy import select
from sqlalchemy.orm import Session

requires_ffmpeg = pytest.mark.skipif(
    find_ffmpeg() is None, reason="FFmpeg not installed; a day cannot be filmed"
)


def _demo_settings(tmp_path: Path, **values) -> Settings:
    base = {
        "_env_file": None,
        "owner_token": "d" * 48,  # pragma: allowlist secret
        "database_url": f"sqlite:///{(tmp_path / 'demo' / 'demo.db').as_posix()}",
        "media_root": tmp_path / "demo" / "media",
        "demo_mode": True,
        "allowed_hosts": ["testserver"],
        "worker_enabled": False,
        "provider_catalog_refresh_enabled": False,
        "trends_enabled": False,
    }
    base.update(values)
    (tmp_path / "demo").mkdir(exist_ok=True)
    return Settings(**base)


def _demo_studio(settings: Settings):
    from app.demo import prepare_demo_studio

    engine = create_db_engine(settings.database_url)
    migrate(engine)
    bootstrap_studio(engine, settings)
    prepare_demo_studio(engine, settings)
    return engine


def test_the_demo_seams_are_exactly_the_days_vendor_boundaries():
    """The demo replaces the same boundaries the end-to-end day proves complete."""
    from app.demo import DEMO_VENDOR_SEAMS
    from test_autonomous_day_end_to_end import VENDOR_FAKES

    assert set(DEMO_VENDOR_SEAMS) == set(VENDOR_FAKES)


def test_demo_model_returns_complete_vendor_prompts_for_the_editor():
    """The demonstration must meet Kael's current shot-plan schema without paid vendors."""
    import json

    from app.demo import DemoModel
    from app.media.prompt_agent import _complete_editor_shot, parse_shot_plan

    brief = '"shots": [' + ", ".join(
        f'{{"scene_index": {index}}}' for index in range(1, 5)
    ) + "]"
    payload = json.loads(DemoModel()._shots(brief))
    parsed = parse_shot_plan(json.dumps(payload))
    assert sorted(parsed.shots) == [1, 2, 3, 4]
    assert all(_complete_editor_shot(shot) for shot in parsed.shots.values())
    assert len({shot.camera_move for shot in parsed.shots.values()}) == 4
    for shot in parsed.shots.values():
        assert shot.ending_frame in shot.motion_prompt
        assert shot.still_prompt and shot.motion_prompt and shot.negative_prompt


def test_director_demo_review_keeps_its_schema_when_a_report_mentions_pronunciation(tmp_path):
    from app.agents.director import director_review
    from app.agents.messages import post_message
    from app.agents.models import Agent, Role
    from app.demo import demo_registry

    engine = _demo_studio(_demo_settings(tmp_path))
    try:
        with Session(engine) as session, session.begin():
            voice_artist = session.scalar(
                select(Agent).join(Role, Agent.role_id == Role.id).where(Role.name == "VoiceArtist")
            )
            message = post_message(
                session,
                intent="STATUS",
                subject="Voice pronunciation check",
                from_agent_id=voice_artist.id,
                body_text="The pronunciation check passed; no further work is requested.",
            )
            message_id = message.id
        result = director_review(engine, demo_registry(engine))
        assert result["reviewed"] == 1
        assert result["applied"] == [{"message_id": message_id, "action": "ACKNOWLEDGE"}]
    finally:
        engine.dispose()


def test_installing_the_demo_vendors_is_undone_on_exit():
    from app.demo import DEMO_VENDOR_SEAMS, demo_vendors

    before = {
        (module, name): getattr(importlib.import_module(module), name)
        for module, name in DEMO_VENDOR_SEAMS
    }
    with demo_vendors():
        for (module, name), original in before.items():
            assert getattr(importlib.import_module(module), name) is not original, (module, name)
    for (module, name), original in before.items():
        assert getattr(importlib.import_module(module), name) is original, (module, name)


def test_the_demo_refuses_the_real_studios_database(tmp_path):
    from app.demo import DemoRefused, prepare_demo_studio
    from app.main import create_app

    real = _demo_settings(tmp_path, database_url="sqlite:///data/studio.db")
    with pytest.raises(DemoRefused, match="DEMO"):
        create_app(real)
    with pytest.raises(DemoRefused):
        prepare_demo_studio(None, real)  # type: ignore[arg-type]


def test_the_page_says_demo_and_publish_and_payment_routes_are_refused(tmp_path):
    from app.main import create_app
    from fastapi.testclient import TestClient

    settings = _demo_settings(tmp_path)
    _demo_studio(settings).dispose()
    headers = {"Authorization": f"Bearer {settings.owner_token.get_secret_value()}"}
    with TestClient(create_app(settings)) as client:
        snap = client.get("/api/v1/snapshot", headers=headers).json()
        assert snap["demo"] == {
            "active": True,
            "banner_ro": "DEMO — furnizori simulați, nimic nu se publică",
        }
        refused = [
            ("POST", "/api/v1/publishing/publish-asset/x"),
            ("POST", "/api/v1/publishing/publications/x/execute"),
            ("POST", "/api/v1/youtube/connections"),
            ("PUT", "/api/v1/economy/budget"),
            ("PUT", "/api/v1/economy/prices"),
            ("PUT", "/api/v1/settings/integrations/runway"),
            ("POST", "/api/v1/providers/x/sync-models"),
            ("POST", "/api/v1/owner/environment"),
            ("POST", "/api/v1/owner/paid-media-approval"),
            ("POST", "/api/v1/media/storyboards/x/steps/stills"),
            ("POST", "/api/v1/media/storyboards/x/redo"),
            ("POST", "/api/v1/media/characters/x/reference-set"),
            ("POST", "/api/v1/factual/sources/retrieve"),
            ("POST", "/api/v1/analytics/trends/refresh"),
        ]
        for method, path in refused:
            answer = client.request(method, path, headers=headers, json={})
            assert answer.status_code == 403, (method, path, answer.status_code)
            assert "DEMO" in answer.json()["detail"], (method, path)
        # Reading still works, and so does the run the buyer starts.
        assert client.get("/api/v1/publishing/channels", headers=headers).status_code == 200
        # A refusal never needs the key to be told: an anonymous call is still 401 first.
        assert client.put("/api/v1/economy/prices", json={}).status_code == 401


def test_a_real_studio_carries_no_demo_banner_and_no_demo_refusal(client, headers):
    assert client.get("/api/v1/snapshot", headers=headers).json()["demo"] is None
    answer = client.post("/api/v1/owner/environment", headers=headers, json={})
    assert answer.status_code == 422  # its own validation, not a demo refusal


def test_preparing_the_demo_twice_changes_nothing_and_marks_no_provider_working(tmp_path):
    from app.agents.models import ProviderRecord
    from app.demo import prepare_demo_studio
    from app.factual.models import TopicIdea
    from app.integrations.models import Integration
    from app.models import OwnerPolicy

    settings = _demo_settings(tmp_path)
    engine = _demo_studio(settings)
    try:
        prepare_demo_studio(engine, settings)
        with Session(engine) as session:
            policy = session.get(OwnerPolicy, 1)
            assert policy.environment == "TEST"
            assert policy.autonomy_stopped is False
            assert len(session.scalars(select(TopicIdea)).all()) == 1
            assert session.scalars(select(Integration)).all() == []
            for provider in session.scalars(select(ProviderRecord)):
                assert provider.status != "HEALTHY"
                assert provider.last_health_check is None
    finally:
        engine.dispose()


@requires_ffmpeg
def test_a_demo_day_makes_a_local_film_and_publishes_nothing(tmp_path):
    from app.agents.models import ProviderRecord
    from app.demo import demo_registry, demo_vendors, run_demo_day
    from app.integrations.models import Integration
    from app.integrations.vault import CredentialVault
    from app.media.models import MediaAsset
    from app.publishing.models import PublicationRecord

    settings = _demo_settings(tmp_path, ffmpeg_path=shutil.which("ffmpeg"))
    engine = _demo_studio(settings)
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    try:
        with demo_vendors():
            result = run_demo_day(engine, settings, vault, demo_registry(engine))
        stages = {stage["stage"]: stage for stage in result["stages"]}
        assert stages["media"]["status"] == "COMPLETED", stages["media"]["reason"]
        with Session(engine) as session:
            films = [
                asset
                for asset in session.scalars(select(MediaAsset))
                if asset.asset_type == "RENDERED_VIDEO" and asset.uri_or_path.endswith(".mp4")
            ]
            assert films, (
                [(a.asset_type, a.uri_or_path[-40:]) for a in session.scalars(select(MediaAsset))],
                [(s["stage"], s["status"], s["reason"][:400]) for s in result["stages"]],
            )
            film = Path(films[0].uri_or_path)
            assert film.is_file() and film.stat().st_size > 10_000
            # Inside the demo's own media folder, never the studio's.
            assert film.resolve().is_relative_to((tmp_path / "demo" / "media").resolve())
            published = [
                p.status
                for p in session.scalars(select(PublicationRecord))
                if p.status.startswith("PUBLISHED") or p.status == "SCHEDULED"
            ]
            assert published == []
            assert session.scalars(select(Integration)).all() == []
            for provider in session.scalars(select(ProviderRecord)):
                assert provider.status != "HEALTHY"
    finally:
        engine.dispose()


def test_the_demo_process_connects_to_nothing_beyond_this_machine():
    import socket

    from app.demo import DemoNetworkRefused, no_outbound_network

    before = socket.socket.connect
    with no_outbound_network():
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(DemoNetworkRefused, match="DEMO"):
                probe.connect(("93.184.215.14", 443))
        finally:
            probe.close()
    assert socket.socket.connect is before


@requires_ffmpeg
def test_the_shipped_demo_script_ends_with_a_film(tmp_path, capsys):
    """scripts/demo_daily_run.py ended PARTIAL 10/13 with nothing on disk; now it films."""
    import sys

    from app.config import ROOT

    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import demo_daily_run
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    result = demo_daily_run.run(tmp_path / "day")
    assert result["films"], capsys.readouterr().out[-2000:]
    film = Path(result["films"][0])
    assert film.is_file() and film.resolve().is_relative_to((tmp_path / "day").resolve())
    out = capsys.readouterr().out
    assert "Produse pe disc:" in out and "RENDERED_VIDEO" in out
