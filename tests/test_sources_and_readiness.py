"""Two things the Owner asked for after seeing the preflight.

1. "We have an image and a voice provider" — and the preflight said none was verified. The
   connections were verified; what was missing was a default model and voice. The preflight
   now says exactly that, and Runway (which the Owner connected) can make stills.
2. Authorised sites must be addable from the interface and testable: a site the studio
   cannot actually read is not a source.

Stubbed HTTPS throughout; nothing here proves live access to any vendor or site.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.integrations.vault import CredentialVault
from app.media.factory import image_provider, media_readiness
from app.providers.runway import RunwayImageAdapter
from app.research.retrieval import RetrievalError, RetrievedSource
from app.research.service import allowed_hosts, retrieve_and_ingest
from app.runbook.preflight import run_preflight


def a_source(url: str) -> RetrievedSource:
    return RetrievedSource(
        requested_url=url,
        url=url,
        title="Example Domains",
        publisher="www.nasa.gov",
        text="Example domains are reserved for use in documentation.",
        retrieved_at=datetime.now(UTC).isoformat(),
        body_sha256="b" * 64,
        content_sha256="c" * 64,
        content_type="text/html",
    )


class StubRetriever:
    """Stands in for the network: returns a page, or fails the way a real site would."""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result, self.error, self.calls = result, error, []

    def fetch(self, url: str) -> RetrievedSource:
        self.calls.append(url)
        if self.error:
            raise self.error
        return self.result or a_source(url)


def settings_allowing(settings, *hosts: str):
    return settings.model_copy(update={"research_allowed_hosts": list(hosts)})


def inner(client):
    """The FastAPI application, behind the TrustedHostMiddleware that wraps it."""
    return client.app.app


def vault_for(engine):
    return CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))


def connect(client, headers, kind, name):
    identifier = str(uuid4())
    response = client.put(
        f"/api/v1/settings/integrations/{identifier}",
        headers=headers,
        json={"kind": kind, "name": name, "secrets": {"api_key": f"test-key-{uuid4()}"}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "VERIFIED"
    return identifier


def select(client, headers, purpose, identifier):
    response = client.put(
        f"/api/v1/settings/selections/{purpose}",
        headers=headers,
        json={"integration_id": identifier, "expected_version": 0},
    )
    assert response.status_code == 200, response.text


def check(preflight, name):
    return next(c for c in preflight["checks"] if c["name"] == name)


# --------------------------------------------------------------------------- readiness


def test_preflight_names_the_missing_step_not_a_missing_provider(
    client, headers, engine, settings, elevenlabs_api
):
    vault = vault_for(engine)
    nothing = media_readiness(engine, vault)
    assert nothing["voice"]["status"] == "NO_SELECTION"
    assert "Niciun serviciu ales" in nothing["voice"]["message"]

    voice = connect(client, headers, "elevenlabs", "Voice account")
    select(client, headers, "voice", voice)
    # Verified and selected, no default yet: the case the Owner hit.
    ready = media_readiness(engine, vault)
    assert ready["voice"]["status"] == "NO_DEFAULT"
    assert "verificat și ales" in ready["voice"]["message"]
    assert "model și o voce implicită" in ready["voice"]["message"]
    preflight = run_preflight(engine, settings, vault)
    voice_check = check(preflight, "voice_provider")
    assert not voice_check["ok"] and voice_check["detail"] == "NO_DEFAULT"
    assert "Voice account este verificat" in voice_check["message"]
    assert check(preflight, "image_provider")["detail"] == "NO_SELECTION"

    client.put(
        f"/api/v1/settings/integrations/{voice}/production",
        headers=headers,
        json={
            "model_id": elevenlabs_api.models[0]["model_id"],
            "voice_id": elevenlabs_api.voices[0]["voice_id"],
            "expected_version": 0,
        },
    )
    assert media_readiness(engine, vault)["voice"]["status"] == "READY"
    assert check(run_preflight(engine, settings, vault), "voice_provider")["ok"]


def test_runway_makes_stills_once_an_image_default_is_chosen(
    client, headers, engine, settings, runway_api
):
    vault = vault_for(engine)
    runway = connect(client, headers, "runway", "Runway account")
    select(client, headers, "image", runway)
    assert media_readiness(engine, vault)["image"]["status"] == "NO_DEFAULT"
    assert "model imagine implicit" in media_readiness(engine, vault)["image"]["message"]
    assert image_provider(engine, vault) is None

    path = f"/api/v1/settings/integrations/{runway}/production"
    # A video-only model is not an image default, and the catalog says which is which.
    wrong = client.put(
        path,
        headers=headers,
        json={"image_model_id": runway_api.video_models[1], "expected_version": 0},
    )
    assert wrong.status_code == 422
    catalog = client.get("/api/v1/settings", headers=headers).json()["provider_catalogs"][runway]
    by_id = {m["remote_id"]: m for m in catalog["models"]}
    assert by_id[runway_api.image_model]["usable_purposes"] == ["image"]
    assert by_id[runway_api.video_models[0]]["usable_purposes"] == ["video"]
    assert catalog["kind_info"]["image_model_label"] == "Model imagine implicit"

    saved = client.put(
        path,
        headers=headers,
        json={"image_model_id": runway_api.image_model, "expected_version": 0},
    )
    assert saved.status_code == 200, saved.text
    assert media_readiness(engine, vault)["image"]["status"] == "READY"
    adapter = image_provider(engine, vault)
    assert isinstance(adapter, RunwayImageAdapter) and adapter.model == runway_api.image_model
    assert check(run_preflight(engine, settings, vault), "image_provider")["ok"]

    runway_api.task = {
        "id": "task-1",
        "status": "SUCCEEDED",
        "output": ["https://files.test/still.png?sig=1"],
    }
    result = asyncio.run(adapter.generate_image("A calm office at dawn", width=1080, height=1920))
    assert (result.format, result.width, result.height) == ("png", 720, 1280)
    assert runway_api.bodies[-1] == {
        "model": runway_api.image_model,
        "promptText": "A calm office at dawn",
        "ratio": "720:1280",
    }
    assert result.raw_response["provider"] == "RUNWAY_IMAGES"


# --------------------------------------------------------------------------- allowlist


def test_owner_adds_tests_and_removes_authorised_sites(client, headers, engine, settings):
    app = inner(client)
    app.state.settings = settings_allowing(settings, "www.iana.org")
    listed = client.get("/api/v1/factual/sources", headers=headers).json()
    assert listed["allowed_hosts"] == ["www.iana.org"]
    assert listed["allowed_host_rows"][0] == {
        "host": "www.iana.org",
        "source": "env",
        "added_at": None,
        "last_test_at": None,
        "last_test_status": None,
        "last_test_detail": None,
    }

    for bad in ("localhost", "www.nasa.gov:443", "127.0.0.1", "NASA.gov", "*.gov"):
        response = client.put(f"/api/v1/factual/sources/allowed-hosts/{bad}", headers=headers)
        assert response.status_code == 422, bad
    added = client.put("/api/v1/factual/sources/allowed-hosts/www.nasa.gov", headers=headers)
    assert added.status_code == 200, added.text
    assert added.json()["source"] == "owner" and added.json()["last_test_status"] is None
    assert allowed_hosts(app.state.settings, engine) == ("www.iana.org", "www.nasa.gov")

    # The test fetches the front page through the real retriever path and records the outcome.
    app.state.source_retriever = StubRetriever(a_source("https://www.nasa.gov/"))
    passed = client.post(
        "/api/v1/factual/sources/allowed-hosts/www.nasa.gov/test", headers=headers
    ).json()
    assert passed["status"] == "PASSED" and passed["summary"]["title"] == "Example Domains"
    app.state.source_retriever = StubRetriever(error=RetrievalError("Source returned HTTP 403"))
    failed = client.post(
        "/api/v1/factual/sources/allowed-hosts/www.nasa.gov/test", headers=headers
    ).json()
    assert failed["status"] == "FAILED" and "HTTP 403" in failed["detail"]
    rows = client.get("/api/v1/factual/sources/allowed-hosts", headers=headers).json()["hosts"]
    nasa = next(r for r in rows if r["host"] == "www.nasa.gov")
    assert nasa["last_test_status"] == "FAILED" and "HTTP 403" in nasa["last_test_detail"]
    # An unauthorised host cannot be tested: the test is not a way around the allowlist.
    assert (
        client.post(
            "/api/v1/factual/sources/allowed-hosts/www.example.com/test", headers=headers
        ).status_code
        == 404
    )

    # Retrieval honours the merged list, and the preflight reports the tested count.
    app.state.source_retriever = StubRetriever(a_source("https://www.nasa.gov/news"))
    stored = retrieve_and_ingest(
        engine,
        app.state.settings,
        "https://www.nasa.gov/news",
        str(uuid4()),
        retriever=app.state.source_retriever,
    )
    assert stored["source"]["url"] == "https://www.nasa.gov/news"
    sources = check(
        run_preflight(engine, app.state.settings, vault_for(engine)), "research_sources"
    )
    assert sources["ok"] and "2 site-uri autorizate" in sources["message"]
    assert "0 testate cu succes" in sources["message"]
    assert "www.nasa.gov" in sources["detail"]

    removed = client.delete("/api/v1/factual/sources/allowed-hosts/www.nasa.gov", headers=headers)
    assert removed.status_code == 200
    assert allowed_hosts(app.state.settings, engine) == ("www.iana.org",)
    # A host from .env is not the interface's to remove.
    assert (
        client.delete(
            "/api/v1/factual/sources/allowed-hosts/www.iana.org", headers=headers
        ).status_code
        == 404
    )


def test_without_any_site_the_message_points_to_the_interface(client, headers):
    response = client.post(
        "/api/v1/factual/sources/retrieve",
        headers=headers,
        json={"command_id": str(uuid4()), "url": "https://www.iana.org/"},
    )
    assert response.status_code == 503
    assert "Cercetare → Surse" in response.json()["detail"]
