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
