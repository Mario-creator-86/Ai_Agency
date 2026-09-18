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
        "last_test_reason": None,
        "search_template": None,
        "discovered_search_template": None,
        "discovered_at": None,
        "search_template_origin": None,
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
    # The preflight now reports whether the studio can find pages at all, not merely whether
    # a row exists: two authorised sites none of which has passed its test is DEGRADED, and
    # the reasons say why rather than counting rows and calling it ready.
    sources = check(
        run_preflight(engine, app.state.settings, vault_for(engine)), "research_sources"
    )
    assert sources["ok"] is False
    assert "niciun site autorizat nu a trecut testul" in sources["message"].lower()

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


# ------------------------------------------------------------------- health of the sources


def test_owner_reads_the_health_report_and_forces_a_retest(client, headers, engine, settings):
    """The two things the Owner cannot see from the host list alone.

    The health report is the preflight's own verdict on whether the studio can find and read
    pages at all, and the forced retest is the "now" the weekly pass does not offer. Both go
    through a stub retriever: conftest refuses every non-loopback socket, so a real front page
    is never fetched here.
    """
    app = inner(client)
    app.state.settings = settings_allowing(settings, "www.iana.org")

    first = client.get("/api/v1/factual/research/health", headers=headers)
    assert first.status_code == 200, first.text
    report = first.json()
    assert set(report) == {
        "hosts_total",
        "hosts_tested_ok",
        "hosts_with_template",
        "hosts_failing",
        "search_provider",
        "claims_available",
        "status",
        "degraded_reasons",
    }
    # One authorised host, never tested, no search address, no engine, no claims.
    assert (report["hosts_total"], report["hosts_tested_ok"], report["hosts_with_template"]) == (
        1,
        0,
        0,
    )
    assert report["search_provider"] == "NONE" and report["claims_available"] == 0
    assert report["status"] == "DEGRADED" and report["hosts_failing"] == []
    assert any("nu a trecut testul" in reason for reason in report["degraded_reasons"])

    # A failing host is named with its reason code, not merely counted.
    app.state.source_retriever = StubRetriever(error=RetrievalError("Source returned HTTP 403"))
    failed = client.post("/api/v1/factual/research/allowed-hosts/retest", headers=headers)
    assert failed.status_code == 200, failed.text
    assert [r["status"] for r in failed.json()["tested"]] == ["FAILED"]
    assert client.get("/api/v1/factual/research/health", headers=headers).json()[
        "hosts_failing"
    ] == [
        {
            "host": "www.iana.org",
            "reason": "HTTP_403",
            "detail": "Source returned HTTP 403",
        }
    ]

    # Forced means now: a host tested a second ago is tested again, which is the point of the
    # button — the weekly pass would leave it alone for seven days.
    app.state.source_retriever = StubRetriever(a_source("https://www.iana.org/"))
    again = client.post("/api/v1/factual/research/allowed-hosts/retest", headers=headers)
    assert again.status_code == 200, again.text
    tested = again.json()["tested"]
    assert [(r["host"], r["status"]) for r in tested] == [("www.iana.org", "PASSED")]
    healthy = client.get("/api/v1/factual/research/health", headers=headers).json()
    assert healthy["hosts_tested_ok"] == 1 and healthy["hosts_failing"] == []
    # Still DEGRADED, and honestly so: nothing can find pages and there are no claims.
    assert healthy["status"] == "DEGRADED"
    assert len(healthy["degraded_reasons"]) == 2


def test_the_sources_screen_is_given_the_origin_and_the_reason_it_shows(
    client, headers, engine, settings
):
    """The three fields the Cercetare → Surse table now prints for each host.

    There is no test runner for main.js (frontend/package.json runs node --test over
    frontend/tests, and main.js touches the document at import), so what the screen renders is
    pinned here, at the API that feeds it: the discovered address, whose address is in force,
    and why the last test failed.
    """
    app = inner(client)
    app.state.settings = settings_allowing(settings)
    added = client.put("/api/v1/factual/sources/allowed-hosts/www.nasa.gov", headers=headers)
    assert added.status_code == 200, added.text

    app.state.source_retriever = StubRetriever(error=RetrievalError("Page needs JavaScript"))
    client.post("/api/v1/factual/research/allowed-hosts/retest", headers=headers)
    row = client.get("/api/v1/factual/sources/allowed-hosts", headers=headers).json()["hosts"][0]
    assert row["last_test_reason"] == "SCRIPT_ONLY"
    assert "JavaScript" in row["last_test_detail"]
    assert row["search_template_origin"] is None and row["discovered_search_template"] is None

    # The Owner's address is a decision and wins the origin, whatever discovery found.
    client.put(
        "/api/v1/factual/sources/allowed-hosts/www.nasa.gov/search",
        headers=headers,
        json={"template": "https://www.nasa.gov/search?q={query}&format=json"},
    )
    owned = client.get("/api/v1/factual/sources/allowed-hosts", headers=headers).json()["hosts"][0]
    assert owned["search_template_origin"] == "OWNER"


# ------------------------------------------------------ a studio configured like his copy


def test_a_studio_shaped_like_the_owners_copy_reads_what_the_rehearsal_audit_found(
    engine, settings, tmp_path
):
    """The 2026-09-18 rehearsal ran on a copy of the Owner's studio and its preflight said
    «Canal YouTube conectat» and «2 sloturi legate» with a green tick. The copy's shape: TEST,
    AUTONOMOUS_CEO, a DAILY budget of 15 USD, both seeded slots bound to CONNECTED accounts —
    Nexus Curiosity and Inside The Nexus, connected 2026-09-11 with youtube.readonly and
    youtube.upload and not yt-analytics.readonly. Rebuilt here on a temporary database, it
    must now say what the audit said, from the database alone."""
    from datetime import timedelta

    from app.agents.models import ModelRecord
    from app.agents.services import seed_initial_workforce
    from app.economy.budget import BudgetCommand, set_budget
    from app.models import DomainEvent, OwnerPolicy
    from app.publishing.models import ChannelRecord
    from app.publishing.services import seed_default_channels
    from app.youtube.models import YouTubeConnection
    from sqlalchemy import select as query
    from sqlalchemy.orm import Session

    vault = CredentialVault(tmp_path / "copy.credentials.key")
    seed_initial_workforce(engine)
    seed_default_channels(engine)
    settings.ffmpeg_path = settings.ffmpeg_path or "ffmpeg-test-stub"
    granted = datetime(2026, 9, 11, 9, 30, tzinfo=UTC)
    morning = datetime(2026, 9, 18, 19, 44, tzinfo=UTC)
    accounts = {}
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = False
        policy.environment = "TEST"
        policy.autonomy_mode = "AUTONOMOUS_CEO"
        session.scalars(query(ModelRecord)).first().is_available = True
        for channel_type, name in (
            ("MAIN_FACTUAL", "Nexus Curiosity"),
            ("OFFICE_SERIAL", "Inside The Nexus"),
        ):
            identifier = str(uuid4())
            accounts[name] = identifier
            session.add(
                YouTubeConnection(
                    id=identifier,
                    name=name,
                    client_id="client.apps.googleusercontent.com",
                    redirect_uri="http://127.0.0.1:8000/auth/youtube/callback",
                    encrypted_secrets="opaque",
                    secret_fields=["client_secret", "refresh_token"],
                    status="CONNECTED",
                    remote_channel_id=f"UC-{identifier[:6]}",
                    remote_channel_title=name.upper(),
                    channel_snapshot={},
                    granted_scopes=(
                        "https://www.googleapis.com/auth/youtube.readonly "
                        "https://www.googleapis.com/auth/youtube.upload"
                    ),
                    connected_at=granted.isoformat(),
                    last_checked_at=granted.isoformat(),
                    created_at=granted.isoformat(),
                )
            )
            session.scalar(
                query(ChannelRecord).where(ChannelRecord.channel_type == channel_type)
            ).credentials_ref = f"youtube_connection:{identifier}"
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="15"))

    preflight = run_preflight(engine, settings, vault, now=morning)
    assert preflight["status"] == "DEGRADED"

    # The binding and the publishing lines no longer read as a verdict on the token.
    assert check(preflight, "youtube_channel_binding")["ok"] is True
    assert "starea stocată" in check(preflight, "youtube_channel_binding")["message"]
    assert "starea stocată" in check(preflight, "publishing")["message"]

    # Statistics: both slots lack the scope; the words say what to do.
    statistics = check(preflight, "youtube_statistics_access")
    assert statistics["ok"] is False and statistics["severity"] == "DEGRADING"
    for name in ("Nexus Curiosity", "Inside The Nexus"):
        assert name in statistics["message"]
    assert "yt-analytics.readonly" in statistics["message"]
    assert (
        "Reconectează canalul din Setări, acordând accesul la statistici" in (statistics["message"])
    )

    # Upload: granted, no refusal recorded — and seven days old, which he is told.
    upload = check(preflight, "youtube_upload_access")
    assert upload["ok"] is True and upload["severity"] == "BLOCKING"
    assert "7 zile" in upload["message"] and "Testing" in upload["message"]
    assert "poate fi deja expirat" in upload["message"]

    # The budget: two TEST films fit today; PRODUCTION would refuse the serial.
    films = check(preflight, "daily_budget_films")
    assert films["ok"] is False and films["severity"] == "INFORMATIONAL"
    assert "PRODUCTION" in films["message"] and "episodul serialului" in films["message"]

    # The morning Google refuses his token, the preflight says the day stops, and where.
    with Session(engine) as session, session.begin():
        session.add(
            DomainEvent(
                event_id=str(uuid4()),
                event_type="youtube.token_refresh_failed",
                timestamp=(morning - timedelta(minutes=5)).isoformat(),
                aggregate_type="youtube_connection",
                aggregate_id=accounts["Nexus Curiosity"],
                aggregate_version=1,
                correlation_id=str(uuid4()),
                causation_id=None,
                schema_version=1,
                visibility="OWNER",
                payload={
                    "connection_id": accounts["Nexus Curiosity"],
                    "during": "token_refresh",
                    "error_class": "HTTPError",
                    "http_status": 400,
                    "oauth_error": "invalid_grant",
                    "auth_refused": True,
                },
            )
        )
    refused = run_preflight(engine, settings, vault, now=morning)
    assert refused["status"] == "BLOCKED"
    assert refused["first_stop"] == "youtube_upload_access"
    assert "Studioul poate rula" not in refused["summary"]
    assert "Nexus Curiosity" in refused["summary"]
