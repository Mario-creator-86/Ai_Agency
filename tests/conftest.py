import secrets
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from app.config import Settings
from app.db import create_db_engine, migrate
from app.main import create_app
from app.services import bootstrap_studio
from fastapi.testclient import TestClient


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        owner_token=secrets.token_urlsafe(48),
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        allowed_hosts=["testserver", "127.0.0.1"],
        # A background loop that starts the day on its own would make every other test's
        # timing a coincidence. The worker has its own tests, which drive it by hand.
        worker_enabled=False,
        provider_catalog_refresh_enabled=False,
    )


@pytest.fixture
def engine(settings):
    engine = create_db_engine(settings.database_url)
    migrate(engine)
    bootstrap_studio(engine, settings)
    yield engine
    engine.dispose()


@pytest.fixture
def headers(settings):
    return {"Authorization": f"Bearer {settings.owner_token.get_secret_value()}"}


@pytest.fixture
def client(engine, settings):
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def elevenlabs_api(monkeypatch):
    """Stub only the HTTPS boundary; IDs are test-generated, not real provider claims."""
    from app.providers import elevenlabs

    fake = SimpleNamespace(
        models=[
            {
                "model_id": f"test-model-{uuid4()}",
                "name": "Test TTS model",
                "can_do_text_to_speech": True,
            }
        ],
        voices=[
            {"voice_id": f"test-voice-{uuid4()}", "name": "Test voice one"},
            {"voice_id": f"test-voice-{uuid4()}", "name": "Test voice two"},
        ],
        calls=[],
        fail=None,
        before_response=None,
    )

    def transport(host, method, path, headers, *args, **kwargs):
        assert host == "api.elevenlabs.io" and method == "GET"
        assert headers["xi-api-key"]
        fake.calls.append(path)
        if fake.before_response:
            fake.before_response(path)
        if fake.fail:
            fake.fail(path)
        parsed = urlsplit(path)
        if parsed.path == "/v1/user":
            payload = {"user_id": "test-account"}
        elif parsed.path == "/v1/models":
            payload = fake.models
        elif parsed.path == "/v2/voices":
            second = parse_qs(parsed.query).get("next_page_token") == ["second-page"]
            payload = {
                "voices": fake.voices[1:] if second else fake.voices[:1],
                "has_more": not second and len(fake.voices) > 1,
                "next_page_token": "second-page" if not second and len(fake.voices) > 1 else None,
            }
        else:
            raise AssertionError(path)
        return payload, b"", "application/json"

    monkeypatch.setattr(elevenlabs, "request", transport)
    return fake


@pytest.fixture
def runway_api(monkeypatch):
    """Stub Runway's HTTPS boundary: the organization endpoint and the published contract.

    Model ids are test-generated. The stub account has two video models and one image model,
    and the stubbed contract says which task each serves, as the real one does.
    """
    import json

    from app.providers import runway
    from app.providers.media_http import MediaProviderError

    video_a, video_b = f"test-video-{uuid4()}", f"test-video-{uuid4()}"
    image = f"test-image-{uuid4()}"
    fake = SimpleNamespace(
        models={
            video_a: {"maxConcurrentGenerations": 2, "maxDailyGenerations": 50},
            video_b: {"maxConcurrentGenerations": 1, "maxDailyGenerations": 20},
            image: {"maxConcurrentGenerations": 4, "maxDailyGenerations": 500},
        },
        usage={video_a: {"dailyGenerations": 2}},
        tasks={
            video_a: ["text_to_video", "image_to_video"],
            video_b: ["image_to_video"],
            image: ["text_to_image"],
        },
        video_models=[video_a, video_b],
        image_model=image,
        calls=[],
        bodies=[],
        task=None,
        fail=None,
        spec_fail=False,
    )

    def contract():
        paths = {}
        for model_id, tasks in fake.tasks.items():
            for task in tasks:
                branch = {
                    "properties": {
                        "model": {"const": model_id},
                        "ratio": {"enum": ["1280:720", "720:1280"]},
                        "duration": {"enum": [5, 10]},
                    }
                }
                schema = paths.setdefault(
                    f"/v1/{task}", {"post": {"requestBody": {"content": {}}}}
                )["post"]["requestBody"]["content"].setdefault(
                    "application/json", {"schema": {"oneOf": []}}
                )["schema"]["oneOf"]
                schema.append(branch)
        return {"openapi": "3.1.0", "paths": paths}

    def transport(host, method, path, headers, body=None, **kwargs):
        fake.calls.append((host, method, path))
        if fake.fail:
            fake.fail(host, path)
        if host == "docs.dev.runwayml.com":
            assert method == "GET" and path == "/openapi.json"
            if fake.spec_fail:
                raise MediaProviderError("docs.dev.runwayml.com could not be reached")
            return contract(), b"", "application/json"
        if host == "files.test":
            if path.split("?", 1)[0].endswith(".png"):
                # A 720x1280 PNG header: enough for the adapter to measure, nothing more.
                import struct

                png = (
                    b"\x89PNG\r\n\x1a\n"
                    + b"\x00\x00\x00\x0dIHDR"
                    + struct.pack(">II", 720, 1280)
                    + b"\x08\x06\x00\x00\x00"
                )
                return None, png, "image/png"
            return None, b"MP4BYTES", "video/mp4"
        assert host == "api.dev.runwayml.com", host
        assert headers["Authorization"].startswith("Bearer ") and headers["X-Runway-Version"]
        if method == "GET" and path == "/v1/organization":
            payload = {
                "creditBalance": 1200,
                "tier": {"maxMonthlyCreditSpend": 100000, "models": fake.models},
                "usage": {"models": fake.usage},
            }
        elif method == "POST" and path in (
            "/v1/text_to_video",
            "/v1/image_to_video",
            "/v1/text_to_image",
        ):
            fake.bodies.append(json.loads(body))
            payload = {"id": "task-1", "estimatedCost": {"credits": 25}}
        elif method == "GET" and path.startswith("/v1/tasks/"):
            payload = fake.task or {
                "id": path.rsplit("/", 1)[1],
                "status": "PENDING",
                "createdAt": "2026-09-11T00:00:00Z",
                "estimatedCost": {"credits": 25},
            }
        else:
            raise AssertionError((method, path))
        return payload, b"", "application/json"

    monkeypatch.setattr(runway, "request", transport)
    return fake


@pytest.fixture
def connect_youtube(engine, monkeypatch):
    """Build CONNECTED YouTube connections through the real OAuth code path.

    Only the HTTP transport to Google is replaced. The state, the token exchange, the channel
    read and the vault write are the code that runs in production, so a test binding to one of
    these is binding to something the real flow could have produced.

    Returns ``connect(name=..., channel_id=..., title=...) -> (connection_id, vault)``.
    """
    from pathlib import Path
    from urllib.parse import parse_qs, urlparse
    from uuid import uuid4

    from app.integrations.vault import CredentialVault
    from app.youtube import services as youtube

    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))

    def connect(*, name, channel_id, title):
        def post_form(url, form, timeout=20):
            if url != youtube.GOOGLE_TOKEN_URL:
                return {}
            return {
                "access_token": "test-access-token",
                "refresh_token": f"test-refresh-{channel_id}",
                "scope": youtube.SCOPES,
            }

        def get_json(url, access_token, timeout=20):
            return {
                "items": [
                    {
                        "id": channel_id,
                        "snippet": {"title": title, "customUrl": "@" + channel_id.lower()},
                        "contentDetails": {"relatedPlaylists": {"uploads": "UU" + channel_id[2:]}},
                        "statistics": {
                            "subscriberCount": "1",
                            "videoCount": "1",
                            "viewCount": "1",
                        },
                    }
                ]
            }

        monkeypatch.setattr(youtube, "_post_form", post_form)
        monkeypatch.setattr(youtube, "_get_json", get_json)

        connection = youtube.create_connection(
            engine,
            vault,
            name=name,
            client_id=name.lower().replace(" ", "-") + ".apps.googleusercontent.com",
            client_secret=secrets.token_urlsafe(32),
            redirect_uri="http://127.0.0.1:8000/auth/youtube/callback",
            correlation_id=str(uuid4()),
        )
        started = youtube.begin_authorization(engine, connection["id"], correlation_id=str(uuid4()))
        state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]
        youtube.complete_authorization(
            engine, vault, code="test-code", state=state, correlation_id=str(uuid4())
        )
        return connection["id"], vault

    return connect
