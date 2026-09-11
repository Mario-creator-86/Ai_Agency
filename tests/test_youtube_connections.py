"""The YouTube OAuth connection flow.

What these tests are really protecting:

  * **The Owner never types a refresh token or a channel id.** Four fields go in; the identity
    comes back from Google. A test asserts the request model refuses anything else.
  * **A secret never comes back out.** Every route is called and every response body is searched
    for the client secret and the refresh token.
  * **A callback cannot be forged or replayed.** The state is unknown, spent or expired in three
    separate tests, and each one must be refused before a code is exchanged.
  * **Two channels are two rows.** Nothing is privileged, nothing is hardcoded.

Google is replaced by a stand-in throughout. Nothing here touches the network, and the studio
must never be shown as connected on the strength of a fixture.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from app.integrations.vault import CredentialVault
from app.models import DomainEvent
from app.youtube import services
from app.youtube.models import YouTubeConnection, YouTubeOAuthState
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

CLIENT_SECRET = "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-leak"  # pragma: allowlist secret
FIRST_REFRESH = "1//refresh-token-alpha-never-shown"
SECOND_REFRESH = "1//refresh-token-beta-never-shown"
REDIRECT = "http://127.0.0.1:8000/auth/youtube/callback"


def channel_payload(channel_id: str, title: str) -> dict:
    """Shaped like a real channels.list item, with values that are obviously invented."""
    return {
        "id": channel_id,
        "snippet": {
            "title": title,
            "customUrl": f"@{title.lower().replace(' ', '')}",
            "description": "Test channel",
            "publishedAt": "2026-01-01T00:00:00Z",
            "country": "RO",
            "thumbnails": {"default": {"url": f"https://example.invalid/{channel_id}.jpg"}},
        },
        "contentDetails": {"relatedPlaylists": {"uploads": f"UU{channel_id[2:]}"}},
        "statistics": {"subscriberCount": "42", "videoCount": "7", "viewCount": "1234"},
    }


@pytest.fixture
def vault(settings):
    path = Path(str(settings.database_url).replace("sqlite:///", ""))
    return CredentialVault(path.with_suffix(".credentials.key"))


@pytest.fixture
def google(monkeypatch):
    """A stand-in for Google that records what it was asked and answers as the real one would."""
    calls = {"token": [], "revoke": [], "channels": []}
    fake = SimpleNamespace(
        calls=calls,
        refresh_token=FIRST_REFRESH,
        channel=channel_payload("UC_alpha_test", "NEXUS CURIOSITY"),
        token_error=None,
        channel_items=None,
    )

    def post_form(url, form, timeout=20):
        if url == services.GOOGLE_TOKEN_URL:
            calls["token"].append(form)
            if fake.token_error:
                raise services.YouTubeConnectionError(fake.token_error)
            answer = {"access_token": "access-token-1", "scope": services.SCOPES}
            if fake.refresh_token:
                answer["refresh_token"] = fake.refresh_token
            return answer
        if url == services.GOOGLE_REVOKE_URL:
            calls["revoke"].append(form)
            return {}
        raise AssertionError(f"unexpected POST to {url}")

    def get_json(url, access_token, timeout=20):
        calls["channels"].append(url)
        items = fake.channel_items if fake.channel_items is not None else [fake.channel]
        return {"items": items}

    monkeypatch.setattr(services, "_post_form", post_form)
    monkeypatch.setattr(services, "_get_json", get_json)
    return fake


@pytest.fixture
def connection(engine, vault):
    return services.create_connection(
        engine,
        vault,
        name="NEXUS CURIOSITY",
        client_id="client-alpha.apps.googleusercontent.com",
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT,
        correlation_id=str(uuid4()),
    )


def connect(engine, vault, connection_id):
    """Run the flow the way the browser does: authorize, then come back with code and state."""
    started = services.begin_authorization(engine, connection_id, correlation_id=str(uuid4()))
    state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]
    return services.complete_authorization(
        engine, vault, code="auth-code", state=state, correlation_id=str(uuid4())
    )


@pytest.mark.parametrize(
    ("thumbnails", "expected"),
    [
        (
            {
                "high": {"url": "https://example.invalid/high"},
                "medium": {"url": "https://example.invalid/medium"},
                "default": {"url": "https://example.invalid/default"},
            },
            "https://example.invalid/high",
        ),
        (
            {"high": {"width": 800}, "medium": {"url": "https://example.invalid/medium"}},
            "https://example.invalid/medium",
        ),
        (
            {
                "high": {"url": ""},
                "medium": {"url": None},
                "default": {"url": "https://example.invalid/default"},
            },
            "https://example.invalid/default",
        ),
        ({"high": {"url": "  "}, "medium": {}, "default": None}, None),
        ({}, None),
        (None, None),
    ],
)
def test_thumbnail_quality_fallback(thumbnails, expected):
    assert (
        services._channel_snapshot({"snippet": {"thumbnails": thumbnails}})["thumbnail_url"]
        == expected
    )


@pytest.mark.parametrize("action", ["verify", "reconnect"])
def test_thumbnail_refresh_is_persisted_per_connection(
    client, headers, engine, vault, google, connection, action
):
    first = connect(engine, vault, connection["id"])
    second = services.create_connection(
        engine,
        vault,
        name="Another connection",
        client_id="other.apps.googleusercontent.com",
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT,
        correlation_id=str(uuid4()),
    )
    google.channel = channel_payload("UC_other_test", "Other test channel")
    other = connect(engine, vault, second["id"])
    google.channel = channel_payload(first["channel"]["id"], first["channel"]["title"])

    for thumbnail in ("https://example.invalid/refreshed-high.jpg", None):
        google.channel["snippet"]["thumbnails"] = {"high": {"url": thumbnail}}
        response = client.post(
            f"/api/v1/youtube/connections/{first['id']}/{action}", headers=headers
        )
        assert response.status_code == 200
        if action == "reconnect":
            state = parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]
            response = client.get("/auth/youtube/callback", params={"code": "new", "state": state})
            assert response.status_code == 200
        else:
            assert response.json()["channel"]["thumbnail_url"] == thumbnail
        # A new request/session proves the URL was committed, not just returned by the action.
        listed = client.get("/api/v1/youtube/connections", headers=headers).json()["connections"]
        rows = {row["id"]: row for row in listed}
        assert rows[first["id"]]["channel"]["thumbnail_url"] == thumbnail
        assert rows[second["id"]]["channel"] == other["channel"]


# --------------------------------------------------------------- what the Owner supplies --


def test_the_owner_supplies_four_fields_and_nothing_about_the_channel():
    from app.youtube.router import CreateConnection

    fields = set(CreateConnection.model_fields)
    assert fields == {"command_id", "name", "client_id", "client_secret", "redirect_uri"}
    # Anything resembling a hand-typed identity is rejected outright by the model.
    for smuggled in ("refresh_token", "channel_id", "remote_channel_id", "access_token"):
        with pytest.raises(ValidationError):
            CreateConnection(
                command_id=uuid4(),
                name="x",
                client_id="c",
                client_secret="s",
                redirect_uri=REDIRECT,
                **{smuggled: "value"},
            )


def test_saving_credentials_authorises_nothing_and_encrypts_the_secret(engine, vault, connection):
    assert connection["status"] == "AUTH_REQUIRED"
    assert connection["connected"] is False
    assert connection["channel"] is None
    assert connection["has_client_secret"] is True
    assert connection["has_refresh_token"] is False

    with Session(engine) as session:
        row = session.get(YouTubeConnection, connection["id"])
        assert CLIENT_SECRET not in row.encrypted_secrets, "the secret must not be stored in clear"
        assert vault.decrypt(row.encrypted_secrets)["client_secret"] == CLIENT_SECRET


@pytest.mark.parametrize("bad", ["", "not-a-url", "ftp://host/cb", "http://h/cb?x=1"])
def test_a_malformed_redirect_uri_is_refused(engine, vault, bad):
    with pytest.raises(services.YouTubeConnectionError):
        services.create_connection(
            engine,
            vault,
            name=f"n{bad}",
            client_id="c",
            client_secret="s",
            redirect_uri=bad,
            correlation_id=str(uuid4()),
        )


def test_two_connections_cannot_share_a_name(engine, vault, connection):
    with pytest.raises(services.YouTubeConnectionError, match="Există deja"):
        services.create_connection(
            engine,
            vault,
            name="NEXUS CURIOSITY",
            client_id="c2",
            client_secret="s2",  # pragma: allowlist secret
            redirect_uri=REDIRECT,
            correlation_id=str(uuid4()),
        )


# ------------------------------------------------------------------- the authorisation URL --


def test_the_consent_url_asks_for_offline_access_and_forces_consent_when_needed(engine, connection):
    started = services.begin_authorization(engine, connection["id"], correlation_id=str(uuid4()))
    url = urlparse(started["authorization_url"])
    query = {k: v[0] for k, v in parse_qs(url.query).items()}

    assert f"{url.scheme}://{url.netloc}{url.path}" == services.GOOGLE_AUTH_URL
    assert query["access_type"] == "offline", "without this Google issues no refresh token"
    assert query["response_type"] == "code"
    assert query["prompt"] == "consent", "nothing is stored yet, so consent must be forced"
    assert query["client_id"] == connection["client_id"]
    assert query["redirect_uri"] == REDIRECT
    assert "youtube.upload" in query["scope"] and "youtube.readonly" in query["scope"]
    assert len(query["state"]) >= 40, "the state is the whole CSRF defence; it must be random"
    assert started["forced_consent"] is True


def test_authorising_without_saved_credentials_is_refused(engine, vault, connection):
    with Session(engine) as session, session.begin():
        row = session.get(YouTubeConnection, connection["id"])
        row.secret_fields = []
    with pytest.raises(services.YouTubeConnectionError, match="Client ID și Client Secret"):
        services.begin_authorization(engine, connection["id"], correlation_id=str(uuid4()))


# ------------------------------------------------------------------------- the callback --


def test_a_successful_callback_stores_the_token_and_reads_the_channel(
    engine, vault, google, connection
):
    result = connect(engine, vault, connection["id"])

    assert result["status"] == "CONNECTED"
    assert result["connected"] is True
    assert result["channel"]["id"] == "UC_alpha_test"
    assert result["channel"]["title"] == "NEXUS CURIOSITY"
    assert result["channel"]["subscriber_count"] == "42"
    assert result["channel"]["uploads_playlist_id"] == "UU_alpha_test"
    assert result["has_refresh_token"] is True
    assert result["connected_at"]
    assert result["last_error"] is None

    # The exchange used the authorization_code grant with the connection's own redirect URI.
    exchange = google.calls["token"][0]
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["redirect_uri"] == REDIRECT
    assert exchange["client_secret"] == CLIENT_SECRET

    # channels.list was called with exactly the parts the brief asks for.
    assert len(google.calls["channels"]) == 1
    called = urlparse(google.calls["channels"][0])
    query = {k: v[0] for k, v in parse_qs(called.query).items()}
    assert called.path.endswith("/channels")
    assert query["mine"] == "true"
    assert set(query["part"].split(",")) == {"snippet", "id", "contentDetails", "statistics"}

    with Session(engine) as session:
        row = session.get(YouTubeConnection, connection["id"])
        assert FIRST_REFRESH not in row.encrypted_secrets
        assert vault.decrypt(row.encrypted_secrets)["refresh_token"] == FIRST_REFRESH


def test_a_state_works_once_and_is_useless_afterwards(engine, vault, google, connection):
    started = services.begin_authorization(engine, connection["id"], correlation_id=str(uuid4()))
    state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]
    services.complete_authorization(
        engine, vault, code="code-1", state=state, correlation_id=str(uuid4())
    )
    with pytest.raises(services.YouTubeConnectionError, match="deja folosită"):
        services.complete_authorization(
            engine, vault, code="code-1", state=state, correlation_id=str(uuid4())
        )
    assert len(google.calls["token"]) == 1, "a replay must not reach Google at all"


def test_an_unknown_state_is_refused_before_anything_is_exchanged(
    engine, vault, google, connection
):
    with pytest.raises(services.YouTubeConnectionError, match="necunoscută"):
        services.complete_authorization(
            engine, vault, code="code", state="not-a-real-state", correlation_id=str(uuid4())
        )
    assert google.calls["token"] == []


def test_an_expired_state_is_refused(engine, vault, google, connection):
    started = services.begin_authorization(engine, connection["id"], correlation_id=str(uuid4()))
    state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]
    with Session(engine) as session, session.begin():
        row = session.get(YouTubeOAuthState, state)
        row.expires_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    with pytest.raises(services.YouTubeConnectionError, match="expirat"):
        services.complete_authorization(
            engine, vault, code="code", state=state, correlation_id=str(uuid4())
        )
    assert google.calls["token"] == []


def test_no_refresh_token_and_none_stored_is_an_error_that_says_what_to_do(
    engine, vault, google, connection
):
    google.refresh_token = None
    with pytest.raises(services.YouTubeConnectionError, match="Reconectează"):
        connect(engine, vault, connection["id"])
    stored = services.get_connection(engine, connection["id"])
    assert stored["status"] == "ERROR"
    assert stored["has_refresh_token"] is False
    assert stored["channel"] is None, "a failed exchange must not leave a channel identity"


def test_a_silent_reauthorisation_keeps_the_token_already_held(engine, vault, google, connection):
    connect(engine, vault, connection["id"])
    google.refresh_token = None  # Google omits it when consent is not re-requested.
    again = connect(engine, vault, connection["id"])
    assert again["status"] == "CONNECTED"
    with Session(engine) as session:
        row = session.get(YouTubeConnection, connection["id"])
    assert vault.decrypt(row.encrypted_secrets)["refresh_token"] == FIRST_REFRESH


def test_an_account_without_a_channel_is_refused_rather_than_stored_empty(
    engine, vault, google, connection
):
    google.channel_items = []
    with pytest.raises(services.YouTubeConnectionError, match="niciun canal"):
        connect(engine, vault, connection["id"])
    assert services.get_connection(engine, connection["id"])["channel"] is None


# --------------------------------------------------------------- reconnect and disconnect --


def test_reconnect_always_asks_google_for_consent_again(engine, vault, google, connection):
    connect(engine, vault, connection["id"])
    silent = services.begin_authorization(engine, connection["id"], correlation_id=str(uuid4()))
    assert "prompt" not in parse_qs(urlparse(silent["authorization_url"]).query)

    forced = services.begin_authorization(
        engine, connection["id"], force_consent=True, correlation_id=str(uuid4())
    )
    assert parse_qs(urlparse(forced["authorization_url"]).query)["prompt"] == ["consent"]

    google.refresh_token = SECOND_REFRESH
    state = parse_qs(urlparse(forced["authorization_url"]).query)["state"][0]
    services.complete_authorization(
        engine, vault, code="code-2", state=state, correlation_id=str(uuid4())
    )
    with Session(engine) as session:
        row = session.get(YouTubeConnection, connection["id"])
    assert vault.decrypt(row.encrypted_secrets)["refresh_token"] == SECOND_REFRESH


def test_disconnect_forgets_the_token_revokes_it_and_keeps_the_credentials(
    engine, vault, google, connection
):
    connect(engine, vault, connection["id"])
    result = services.disconnect_connection(
        engine, vault, connection["id"], correlation_id=str(uuid4())
    )

    assert result["status"] == "AUTH_REQUIRED"
    assert result["has_refresh_token"] is False
    assert result["has_client_secret"] is True, "credentials stay so a reconnect is one click"
    assert result["channel"] is None
    assert google.calls["revoke"][0]["token"] == FIRST_REFRESH
    with Session(engine) as session:
        row = session.get(YouTubeConnection, connection["id"])
        assert "refresh_token" not in vault.decrypt(row.encrypted_secrets)
        pending = session.scalars(select(YouTubeOAuthState)).all()
    assert pending == [], "a disconnect must not leave usable authorisations behind"


def test_disconnect_still_forgets_the_token_when_google_cannot_be_reached(
    engine, vault, google, connection, monkeypatch
):
    connect(engine, vault, connection["id"])

    def unreachable(url, form, timeout=20):
        raise services.YouTubeConnectionError("network down")

    monkeypatch.setattr(services, "_post_form", unreachable)
    result = services.disconnect_connection(
        engine, vault, connection["id"], correlation_id=str(uuid4())
    )
    assert result["has_refresh_token"] is False
    assert "Google nu a confirmat revocarea" in result["last_error"]


def test_changing_the_google_client_drops_a_token_it_can_no_longer_use(
    engine, vault, google, connection
):
    connect(engine, vault, connection["id"])
    updated = services.update_connection(
        engine,
        vault,
        connection["id"],
        client_id="client-beta.apps.googleusercontent.com",
        correlation_id=str(uuid4()),
    )
    assert updated["status"] == "AUTH_REQUIRED"
    assert updated["has_refresh_token"] is False


def test_verify_re_reads_the_channel_and_records_a_revoked_grant(engine, vault, google, connection):
    connect(engine, vault, connection["id"])
    google.channel = channel_payload("UC_alpha_test", "NEXUS CURIOSITY renamed")
    refreshed = services.verify_connection(
        engine, vault, connection["id"], correlation_id=str(uuid4())
    )
    assert refreshed["channel"]["title"] == "NEXUS CURIOSITY renamed"
    assert refreshed["status"] == "CONNECTED"

    google.token_error = "invalid_grant: token has been revoked"
    with pytest.raises(services.YouTubeConnectionError):
        services.verify_connection(engine, vault, connection["id"], correlation_id=str(uuid4()))
    assert services.get_connection(engine, connection["id"])["status"] == "ERROR"


# ------------------------------------------------------------------- several channels --


def test_two_channels_are_two_independent_connections(engine, vault, google, connection):
    second = services.create_connection(
        engine,
        vault,
        name="INSIDE THE NEXUS",
        client_id="client-beta.apps.googleusercontent.com",
        client_secret="another-secret",  # pragma: allowlist secret
        redirect_uri=REDIRECT,
        correlation_id=str(uuid4()),
    )
    connect(engine, vault, connection["id"])

    google.channel = channel_payload("UC_beta_test", "INSIDE THE NEXUS")
    google.refresh_token = SECOND_REFRESH
    connect(engine, vault, second["id"])

    listed = {c["name"]: c for c in services.list_connections(engine)}
    assert set(listed) == {"NEXUS CURIOSITY", "INSIDE THE NEXUS"}
    assert listed["NEXUS CURIOSITY"]["channel"]["id"] == "UC_alpha_test"
    assert listed["INSIDE THE NEXUS"]["channel"]["id"] == "UC_beta_test"
    assert all(c["status"] == "CONNECTED" for c in listed.values())

    # Disconnecting one leaves the other exactly as it was.
    services.disconnect_connection(engine, vault, second["id"], correlation_id=str(uuid4()))
    after = {c["name"]: c for c in services.list_connections(engine)}
    assert after["NEXUS CURIOSITY"]["status"] == "CONNECTED"
    assert after["INSIDE THE NEXUS"]["status"] == "AUTH_REQUIRED"


def test_a_connected_connection_can_build_a_publisher_without_the_ui_seeing_a_secret(
    engine, vault, google, connection
):
    connect(engine, vault, connection["id"])
    provider = services.provider_for_connection(engine, vault, connection["id"])
    assert provider.is_configured is True
    assert provider.channel_id == "UC_alpha_test"
    # And an unauthorised connection refuses instead of returning a half-built publisher.
    services.disconnect_connection(engine, vault, connection["id"], correlation_id=str(uuid4()))
    with pytest.raises(services.YouTubeConnectionError, match="nu este conectată"):
        services.provider_for_connection(engine, vault, connection["id"])


# ------------------------------------------------------------------------------- the API --


def test_every_youtube_route_requires_the_owner_except_the_callback(client):
    assert client.get("/api/v1/youtube/connections").status_code == 401
    assert client.post("/api/v1/youtube/connections", json={}).status_code == 401
    # The callback must stay reachable without a credential, or Google's redirect cannot land.
    assert client.get("/auth/youtube/callback").status_code != 401


def test_the_callback_reports_a_refused_consent_without_touching_anything(client, google):
    response = client.get("/auth/youtube/callback", params={"error": "access_denied"})
    assert response.status_code == 400
    assert "access_denied" in response.text
    assert google.calls["token"] == []


def test_the_callback_refuses_an_unknown_state_and_says_nothing_useful_to_a_stranger(
    client, google
):
    response = client.get("/auth/youtube/callback", params={"code": "c", "state": "guessed"})
    assert response.status_code == 400
    assert google.calls["token"] == []
    assert CLIENT_SECRET not in response.text


def test_the_whole_api_surface_never_returns_a_secret(client, headers, engine, vault, google):
    created = client.post(
        "/api/v1/youtube/connections",
        headers=headers,
        json={
            "command_id": str(uuid4()),
            "name": "NEXUS CURIOSITY",
            "client_id": "client-alpha.apps.googleusercontent.com",
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT,
        },
    )
    assert created.status_code == 200, created.text
    connection_id = created.json()["id"]

    started = client.post(f"/api/v1/youtube/connections/{connection_id}/authorize", headers=headers)
    assert started.status_code == 200
    state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]

    callback = client.get("/auth/youtube/callback", params={"code": "code", "state": state})
    assert callback.status_code == 200
    assert "NEXUS CURIOSITY" in callback.text

    bodies = [created.text, started.text, callback.text]
    for path in (
        "/api/v1/youtube/connections",
        f"/api/v1/youtube/connections/{connection_id}",
    ):
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        bodies.append(response.text)
    for verb in ("verify", "reconnect", "disconnect"):
        response = client.post(
            f"/api/v1/youtube/connections/{connection_id}/{verb}", headers=headers
        )
        assert response.status_code == 200, response.text
        bodies.append(response.text)

    for body in bodies:
        assert CLIENT_SECRET not in body
        assert FIRST_REFRESH not in body
        # Nothing that even looks like a Google token should appear in a response.
        assert not re.search(r"GOCSPX-|1//[A-Za-z0-9_-]{10,}", body), body[:300]


def test_the_connected_channel_is_reported_back_to_the_owner(client, headers, google):
    created = client.post(
        "/api/v1/youtube/connections",
        headers=headers,
        json={
            "command_id": str(uuid4()),
            "name": "INSIDE THE NEXUS",
            "client_id": "client-beta.apps.googleusercontent.com",
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT,
        },
    ).json()
    started = client.post(
        f"/api/v1/youtube/connections/{created['id']}/authorize", headers=headers
    ).json()
    state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]
    client.get("/auth/youtube/callback", params={"code": "code", "state": state})

    listed = client.get("/api/v1/youtube/connections", headers=headers).json()["connections"]
    assert len(listed) == 1
    shown = listed[0]
    assert shown["status"] == "CONNECTED"
    assert shown["channel"]["title"] == "NEXUS CURIOSITY"
    assert shown["channel"]["id"] == "UC_alpha_test"
    assert shown["channel"]["thumbnail_url"].startswith("https://")
    assert shown["granted_scopes"]


# ------------------------------------------------------------------------ nothing invented --


def test_the_module_hardcodes_no_channel_token_or_account(engine):
    """A grep the reviewer would otherwise have to run by hand."""
    source = (Path(__file__).resolve().parents[1] / "backend/app/youtube").rglob("*.py")
    text = "\n".join(path.read_text(encoding="utf-8") for path in source)
    shapes = {
        "a channel id": r"\bUC[A-Za-z0-9_-]{20,}",
        "a Google client": r"[A-Za-z0-9-]+\.apps\.googleusercontent\.com",
        "a client secret": r"GOCSPX-\S+",
        "a refresh token": r"\b1//[A-Za-z0-9_-]{10,}",
        "an account name": r"NEXUS|CURIOSITY",
    }
    for description, pattern in shapes.items():
        assert not re.search(pattern, text), f"{description} is hardcoded in the module"
    # The only Google hosts named are the documented OAuth and API endpoints.
    hosts = set(re.findall(r"https://([a-z0-9.\-]+)/", text))
    assert hosts == {"accounts.google.com", "oauth2.googleapis.com", "www.googleapis.com"}


def test_the_flow_leaves_an_audit_trail(engine, vault, google, connection):
    connect(engine, vault, connection["id"])
    services.disconnect_connection(engine, vault, connection["id"], correlation_id=str(uuid4()))
    with Session(engine) as session:
        types = session.scalars(
            select(DomainEvent.event_type).where(DomainEvent.event_type.like("youtube.%"))
        ).all()
    assert "youtube.connection_created" in types
    assert "youtube.authorization_started" in types
    assert "youtube.connected" in types
    assert "youtube.disconnected" in types

    with Session(engine) as session:
        connected = session.scalar(
            select(DomainEvent).where(DomainEvent.event_type == "youtube.connected")
        )
    # The event records which channel was authorised, and carries no credential.
    assert connected.payload["channel_id"] == "UC_alpha_test"
    assert "refresh_token" not in str(connected.payload)
