"""Phase 7 — analytics and the continuous learning loop, wired into the application.

The loop reads its own stored numbers back and turns them into editorial recommendations, so a
fabricated figure would not merely be displayed: it would change what the studio decides to make.
These tests therefore cover the honesty of the intake path as closely as the arithmetic:

- with no analytics provider configured, ingestion refuses instead of inventing an audience;
- a publication with no real video on the platform has nothing to measure;
- a provider failure stores nothing;
- the stored snapshot carries the provider's own response for audit;
- a recommendation needs at least three observations and can never move a weight beyond ±0.20,
  enforced by the service and again by the database.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.analytics.models import AnalyticsSnapshot, ContentStrategy, DirectorRecommendation
from app.analytics.services import (
    MetricsUnavailable,
    apply_director_recommendation,
    generate_director_recommendations,
    get_active_strategy,
    ingest_publication_metrics,
    seed_default_strategy,
)
from app.media.models import MediaAsset
from app.providers.analytics_base import AnalyticsProvider, VideoMetrics
from app.publishing.models import ChannelRecord, PublicationRecord
from app.publishing.services import seed_default_channels
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session


class RecordingProvider(AnalyticsProvider):
    """A stand-in for the platform. It reports exactly what the test tells it to."""

    PROVIDER_NAME = "TEST_RECORDING"

    def __init__(self, **metrics: float) -> None:
        self.metrics = metrics
        self.calls: list[tuple[str, str]] = []

    async def fetch_video_metrics(
        self, remote_video_id: str, window: str = "LIFETIME"
    ) -> VideoMetrics:
        self.calls.append((remote_video_id, window))
        return VideoMetrics(
            remote_video_id=remote_video_id,
            views=int(self.metrics.get("views", 1000)),
            watch_time_seconds=float(self.metrics.get("watch_time_seconds", 20000.0)),
            average_view_percentage=float(self.metrics.get("retention", 55.0)),
            impressions=int(self.metrics.get("impressions", 10000)),
            ctr_percentage=float(self.metrics.get("ctr", 7.0)),
            likes=int(self.metrics.get("likes", 40)),
            comments=int(self.metrics.get("comments", 5)),
            shares=int(self.metrics.get("shares", 2)),
            subscribers_gained=int(self.metrics.get("subs_gained", 8)),
            subscribers_lost=int(self.metrics.get("subs_lost", 1)),
            window=window,
            raw={"provider": "TEST_RECORDING", "rows_returned": 1},
        )

    async def fetch_channel_metrics(self, remote_channel_id: str, window: str = "LIFETIME"):  # type: ignore[no-untyped-def]
        raise NotImplementedError


class UnreachableProvider(AnalyticsProvider):
    PROVIDER_NAME = "TEST_UNREACHABLE"

    async def fetch_video_metrics(
        self, remote_video_id: str, window: str = "LIFETIME"
    ) -> VideoMetrics:
        raise RuntimeError("YouTube Analytics API request failed")

    async def fetch_channel_metrics(self, remote_channel_id: str, window: str = "LIFETIME"):  # type: ignore[no-untyped-def]
        raise NotImplementedError


@pytest.fixture
def channel(engine):
    seed_default_channels(engine)
    seed_default_strategy(engine)
    with Session(engine) as session:
        return session.scalar(
            select(ChannelRecord).where(ChannelRecord.channel_type == "MAIN_FACTUAL")
        ).id


def make_publication(engine, channel_id, *, status="PUBLISHED", remote_video_id="yt_real_abc"):
    """A publication row with a real media asset behind it, as the pipeline produces."""
    publication_id = str(uuid4())
    asset_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{asset_id}/final_short_9_16.mp4",
                file_size_bytes=1024,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=45.0,
                provider_name="STUDIO_INTERNAL",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=utc_now(),
                event_id=None,
            )
        )
        session.flush()
        event = append_event(
            session,
            "publishing.intent_created",
            "publication_record",
            publication_id,
            1,
            {},
            str(uuid4()),
        )
        session.add(
            PublicationRecord(
                id=publication_id,
                channel_id=channel_id,
                media_asset_id=asset_id,
                title="Test publication",
                description="",
                tags_json=[],
                privacy_status="private",
                status=status,
                idempotency_key=str(uuid4()),
                remote_video_id=remote_video_id,
                remote_url=None,
                scheduled_publish_time=None,
                published_at=utc_now(),
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
    return publication_id


# ---------------------------------------------------------------------------
# Honesty of the intake path
# ---------------------------------------------------------------------------


def test_ingestion_refuses_when_no_analytics_provider_is_configured(
    client, headers, channel, engine
):
    """No provider means no audience data. It must refuse, not fall back to a simulator."""
    publication_id = make_publication(engine, channel)

    response = client.post(f"/api/v1/analytics/ingest/{publication_id}", headers=headers)

    assert response.status_code == 503, response.text
    assert "nu estimează și nu simulează" in response.json()["detail"]
    with Session(engine) as session:
        assert session.scalars(select(AnalyticsSnapshot)).all() == []


def test_no_simulated_analytics_adapter_exists():
    """The only analytics adapter in the tree is the one that asks a real platform.

    The deterministic adapter that manufactured audience figures was deleted; this fails if
    any provider module reintroduces one, under any name.
    """
    import importlib
    import inspect
    import pkgutil

    import app.providers
    from app.providers.analytics_base import AnalyticsProvider
    from app.providers.youtube_analytics import YouTubeAnalyticsProvider

    found = set()
    for info in pkgutil.iter_modules(app.providers.__path__):
        module = importlib.import_module(f"app.providers.{info.name}")
        for _, member in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(member, AnalyticsProvider)
                and member is not AnalyticsProvider
                and not inspect.isabstract(member)
            ):
                found.add(member)

    assert found == {YouTubeAnalyticsProvider}, (
        f"unexpected analytics adapter(s): {sorted(c.__name__ for c in found)}"
    )


def test_a_publication_with_no_real_video_has_nothing_to_measure(engine, channel):
    for status, remote in [
        ("PUBLISHED_SIMULATED", "yt_sim_1"),
        ("PUBLISHED", None),
        ("BLOCKED", None),
    ]:
        publication_id = make_publication(engine, channel, status=status, remote_video_id=remote)
        provider = RecordingProvider()
        with pytest.raises(MetricsUnavailable):
            ingest_publication_metrics(engine, publication_id, provider)
        assert provider.calls == [], "the provider must not be asked about a video that isn't live"

    with Session(engine) as session:
        assert session.scalars(select(AnalyticsSnapshot)).all() == []


def test_a_provider_failure_stores_nothing(engine, channel):
    publication_id = make_publication(engine, channel)

    with pytest.raises(RuntimeError):
        ingest_publication_metrics(engine, publication_id, UnreachableProvider())

    with Session(engine) as session:
        assert session.scalars(select(AnalyticsSnapshot)).all() == []


def test_a_snapshot_records_the_requested_window_and_the_providers_own_response(engine, channel):
    publication_id = make_publication(engine, channel)
    provider = RecordingProvider(views=4321, retention=61.5, ctr=8.25)

    result = ingest_publication_metrics(engine, publication_id, provider, window="7d")

    assert provider.calls == [("yt_real_abc", "7d")], "the real remote id and window are used"
    assert result["views"] == 4321
    with Session(engine) as session:
        snapshot = session.scalars(select(AnalyticsSnapshot)).one()
    assert snapshot.window == "7d"
    assert snapshot.average_view_percentage == 61.5
    # The provider's answer is kept verbatim, so any stored figure is traceable.
    assert snapshot.raw_metrics_json["provider"] == "TEST_RECORDING"


def test_the_database_refuses_an_impossible_measurement(engine, channel):
    """Defence in depth: a retention above 100% could not come from a real report."""
    import sqlalchemy.exc

    publication_id = make_publication(engine, channel)
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        with Session(engine) as session, session.begin():
            session.add(
                AnalyticsSnapshot(
                    id=str(uuid4()),
                    publication_id=publication_id,
                    channel_id=channel,
                    window="LIFETIME",
                    views=10,
                    watch_time_seconds=1.0,
                    average_view_percentage=180.0,
                    impressions=10,
                    ctr_percentage=1.0,
                    likes=0,
                    comments=0,
                    shares=0,
                    subscribers_gained=0,
                    subscribers_lost=0,
                    raw_metrics_json={},
                    snapshot_at=utc_now(),
                    event_id=None,
                )
            )


# ---------------------------------------------------------------------------
# The learning loop
# ---------------------------------------------------------------------------


def test_the_baseline_strategy_expresses_no_preference(engine, channel):
    strategy = get_active_strategy(engine, channel)

    assert strategy is not None
    assert strategy["version"] == 1
    weights = [
        *strategy["topic_weights_json"].values(),
        *strategy["hook_weights_json"].values(),
    ]
    assert weights and all(w == 1.0 for w in weights), (
        "a seeded strategy must not prefer a topic before anything has been measured"
    )


def test_seeding_the_strategy_twice_creates_one_version(engine, channel):
    assert seed_default_strategy(engine) == 0  # the fixture already seeded it
    with Session(engine) as session:
        versions = session.scalars(
            select(ContentStrategy.version).where(ContentStrategy.channel_id == channel)
        ).all()
    assert list(versions) == [1]


def test_no_recommendation_is_made_without_enough_evidence(engine, channel):
    """One or two observations are an anecdote. The Director needs at least three."""
    for _ in range(2):
        publication_id = make_publication(engine, channel)
        ingest_publication_metrics(engine, publication_id, RecordingProvider(retention=72.0))

    assert generate_director_recommendations(engine, channel) == []
    with Session(engine) as session:
        assert session.scalars(select(DirectorRecommendation)).all() == []


def test_an_applied_recommendation_moves_the_weight_within_its_bound(engine, channel):
    before = get_active_strategy(engine, channel)
    assert before is not None

    with Session(engine) as session, session.begin():
        recommendation_id = str(uuid4())
        session.add(
            DirectorRecommendation(
                id=recommendation_id,
                channel_id=channel,
                strategy_id=before["id"],
                recommendation_type="BOOST_TOPIC",
                target_entity="space",
                suggested_weight_change=0.15,
                sample_size=4,
                mean_retention=68.0,
                mean_ctr=8.0,
                confidence_score=0.9,
                evidence_summary="N=4 publications above the retention threshold.",
                status="PROPOSED",
                created_at=utc_now(),
            )
        )

    after = apply_director_recommendation(engine, recommendation_id)

    assert after["version"] == before["version"] + 1
    assert after["topic_weights_json"]["space"] == 1.15
    # Every other weight is untouched: applying one recommendation changes one thing.
    assert after["topic_weights_json"]["physics"] == before["topic_weights_json"]["physics"]
    with Session(engine) as session:
        assert session.get(DirectorRecommendation, recommendation_id).status == "APPLIED"
        active = session.scalars(
            select(ContentStrategy).where(
                ContentStrategy.channel_id == channel, ContentStrategy.is_active.is_(True)
            )
        ).all()
    assert len(active) == 1, "exactly one strategy version is active at a time"


def test_the_database_refuses_a_recommendation_without_evidence(engine, channel):
    """Defence in depth: the service gate is not the only thing standing between an anecdote
    and a change of editorial direction."""
    import sqlalchemy.exc

    strategy = get_active_strategy(engine, channel)
    for sample_size, change in [(1, 0.15), (5, 0.75)]:
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            with Session(engine) as session, session.begin():
                session.add(
                    DirectorRecommendation(
                        id=str(uuid4()),
                        channel_id=channel,
                        strategy_id=strategy["id"],
                        recommendation_type="BOOST_TOPIC",
                        target_entity="space",
                        suggested_weight_change=change,
                        sample_size=sample_size,
                        mean_retention=68.0,
                        mean_ctr=8.0,
                        confidence_score=0.9,
                        evidence_summary="insufficient",
                        status="PROPOSED",
                        created_at=utc_now(),
                    )
                )


# ---------------------------------------------------------------------------
# The adapter's credentials are one account's, never a mixture
# ---------------------------------------------------------------------------
# Measured before this work: the constructor read STUDIO_YOUTUBE_* for every argument left
# None, so an adapter built from a channel's bound account still took an access token from
# the environment — another account's numbers attributed to this channel — and it had no
# channel identity of its own.


def test_explicit_analytics_credentials_never_mix_with_the_environment(monkeypatch):
    from app.providers.youtube_analytics import YouTubeAnalyticsProvider

    monkeypatch.setenv("STUDIO_YOUTUBE_CLIENT_ID", "env-client")
    monkeypatch.setenv("STUDIO_YOUTUBE_CLIENT_SECRET", "env-secret")  # pragma: allowlist secret
    monkeypatch.setenv("STUDIO_YOUTUBE_REFRESH_TOKEN", "env-refresh")  # pragma: allowlist secret
    monkeypatch.setenv("STUDIO_YOUTUBE_ACCESS_TOKEN", "env-access")  # pragma: allowlist secret

    explicit = YouTubeAnalyticsProvider(
        client_id="own-client",
        client_secret="own-secret",  # pragma: allowlist secret
        refresh_token="own-refresh",  # pragma: allowlist secret
        channel_id="UC_own",
    )
    assert explicit.client_id == "own-client"
    assert explicit.client_secret == "own-secret"  # pragma: allowlist secret
    assert explicit.refresh_token == "own-refresh"  # pragma: allowlist secret
    # The environment's token would have been used before the refresh; it is not this
    # account's, so it is not read at all.
    assert explicit.access_token is None
    assert explicit.channel_id == "UC_own"
    assert explicit.is_configured()

    # One explicit credential is still an explicit set: nothing is completed from the
    # environment, and the adapter honestly says it is not configured.
    partial = YouTubeAnalyticsProvider(client_id="own-client")
    assert partial.client_secret is None and partial.refresh_token is None
    assert partial.access_token is None and not partial.is_configured()

    # With nothing given the pre-Settings path stands: the environment is the account.
    from_env = YouTubeAnalyticsProvider()
    assert from_env.client_id == "env-client" and from_env.access_token == "env-access"
    assert from_env.channel_id is None


def _bind_connection(engine, channel_id: str, name: str = "Main account") -> str:
    """A CONNECTED account named by the slot, the way the Owner's two accounts are bound."""
    from app.youtube.models import YouTubeConnection

    connection_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            YouTubeConnection(
                id=connection_id,
                name=name,
                client_id="client-id",
                redirect_uri="http://localhost/callback",
                encrypted_secrets="opaque",
                secret_fields=["client_secret", "refresh_token"],
                status="CONNECTED",
                remote_channel_id="UC_main",
                remote_channel_title=name,
                channel_snapshot={},
                created_at=utc_now(),
            )
        )
        session.get(
            ChannelRecord, channel_id
        ).credentials_ref = f"youtube_connection:{connection_id}"
    return connection_id


class _Vault:
    def decrypt(self, value: str) -> dict:
        return {
            "client_secret": "the-client-secret",  # pragma: allowlist secret
            "refresh_token": "the-refresh-token",  # pragma: allowlist secret
        }


def test_the_channels_adapter_carries_its_channel_and_ignores_the_environment(
    engine, channel, monkeypatch
):
    from app.analytics.services import analytics_provider_for_channel

    monkeypatch.setenv("STUDIO_YOUTUBE_ACCESS_TOKEN", "env-access")  # pragma: allowlist secret
    connection_id = _bind_connection(engine, channel)

    class Vault:
        def decrypt(self, value: str) -> dict:
            return {"client_secret": "s", "refresh_token": "r"}  # pragma: allowlist secret

    provider, reason = analytics_provider_for_channel(engine, Vault(), channel)
    assert provider.connection_id == connection_id
    assert provider is not None and reason == ""
    assert provider.channel_id == "UC_main"
    assert provider.access_token is None
    assert (provider.client_id, provider.client_secret, provider.refresh_token) == (
        "client-id",
        "s",
        "r",
    )


# ---------------------------------------------------------------------------
# A statistics read that cannot be made is "no data", never the day's fault
# ---------------------------------------------------------------------------
# Measured on the Owner's copy on 2026-09-18: the refresh of the analytics token sat outside
# every try, so a refused DNS lookup of oauth2.googleapis.com failed performance intake four
# times over 140 s and the runbook blocked every stage after it. A revoked refresh token
# answers HTTP 400 invalid_grant, which the runbook read as HARD and turned into safe mode.


def _google_refuses(code: int, body: bytes):
    import io
    from urllib.error import HTTPError

    def urlopen(request, timeout=None):
        raise HTTPError(request.full_url, code, "Bad Request", {}, io.BytesIO(body))  # type: ignore[arg-type]

    return urlopen


def _unreachable(request, timeout=None):
    from urllib.error import URLError

    raise URLError("[Errno 11001] getaddrinfo failed")


INVALID_GRANT = b'{"error": "invalid_grant", "error_description": "Token has been revoked."}'


def _provider():
    from app.providers.youtube_analytics import YouTubeAnalyticsProvider

    return YouTubeAnalyticsProvider(
        client_id="client-id",
        client_secret="the-client-secret",  # pragma: allowlist secret
        refresh_token="the-refresh-token",  # pragma: allowlist secret
        channel_id="UC_main",
    )


def test_a_revoked_refresh_token_is_no_data_and_says_the_connection_needs_reconnecting(
    monkeypatch,
):
    import asyncio

    import app.providers.youtube_analytics as module

    monkeypatch.setattr(module, "urlopen", _google_refuses(400, INVALID_GRANT))

    with pytest.raises(MetricsUnavailable) as refused:
        asyncio.run(_provider().fetch_video_metrics("yt_real_abc"))

    exc = refused.value
    assert exc.auth_refused is True
    assert exc.during == "token_refresh"
    assert exc.oauth_error == "invalid_grant"
    assert exc.http_status == 400 and exc.error_class == "HTTPError"
    assert "reconect" in str(exc).lower()
    # The token and the secret never travel in what the studio says about the refusal.
    assert "the-refresh-token" not in str(exc) and "the-client-secret" not in str(exc)


def test_an_unreachable_token_service_is_no_data_not_an_exception_out_of_the_read(monkeypatch):
    import asyncio

    import app.providers.youtube_analytics as module

    monkeypatch.setattr(module, "urlopen", _unreachable)

    with pytest.raises(MetricsUnavailable) as refused:
        asyncio.run(_provider().fetch_video_metrics("yt_real_abc"))

    assert refused.value.auth_refused is False
    assert refused.value.error_class == "URLError"
    assert refused.value.during == "token_refresh"


def test_a_report_google_refuses_is_no_data_and_an_impression_refusal_still_falls_back(
    monkeypatch,
):
    import asyncio
    import io
    import json

    import app.providers.youtube_analytics as module
    from app.providers.youtube_analytics import YouTubeAnalyticsProvider

    token = "a"  # pragma: allowlist secret
    reader = YouTubeAnalyticsProvider(access_token=token, channel_id="UC_main")
    monkeypatch.setattr(module, "urlopen", _google_refuses(403, b'{"error": {"code": 403}}'))
    with pytest.raises(MetricsUnavailable) as forbidden:
        asyncio.run(reader.fetch_video_metrics("yt_real_abc"))
    assert forbidden.value.auth_refused is True and forbidden.value.during == "report"

    monkeypatch.setattr(module, "urlopen", _unreachable)
    with pytest.raises(MetricsUnavailable) as unreachable:
        asyncio.run(reader.fetch_video_metrics("yt_real_abc"))
    assert unreachable.value.auth_refused is False

    # The one refusal the adapter has always answered by asking again: an account for which
    # impressions are not reported. That stays a second, smaller question, not "no data".
    calls: list[str] = []

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def impressions_refused(request, timeout=None):
        calls.append(request.full_url)
        if len(calls) == 1:
            return _google_refuses(400, b'{"error": {"code": 400}}')(request, timeout)
        body = {"columnHeaders": [{"name": "views"}], "rows": [[12]]}
        return Answer(json.dumps(body).encode("utf-8"))

    monkeypatch.setattr(module, "urlopen", impressions_refused)
    metrics = asyncio.run(reader.fetch_video_metrics("yt_real_abc"))
    assert metrics.views == 12 and metrics.raw["impressions_reported"] is False
    assert len(calls) == 2


def test_measuring_a_channel_whose_token_google_refuses_records_no_data_and_tells_the_preflight(
    engine, channel, monkeypatch
):
    """Both of the channel's real publications are listed as without data, with the words the
    Owner acts on; the token is asked for once, not once per film; and the refusal is in the
    ledger where the preflight reads it without calling anyone."""
    import app.providers.youtube_analytics as module
    from app.analytics.services import (
        TOKEN_REFRESH_FAILED,
        analytics_provider_for_channel,
        measure_channel_publications,
    )
    from app.models import DomainEvent

    connection_id = _bind_connection(engine, channel, name="Nexus Curiosity")
    make_publication(engine, channel, remote_video_id="yt_real_1")
    make_publication(engine, channel, remote_video_id="yt_real_2")
    calls: list[str] = []
    refuse = _google_refuses(400, INVALID_GRANT)

    def counted(request, timeout=None):
        calls.append(request.full_url)
        return refuse(request, timeout)

    monkeypatch.setattr(module, "urlopen", counted)
    provider, _ = analytics_provider_for_channel(engine, _Vault(), channel)

    result = measure_channel_publications(engine, channel, provider, limit=5)

    assert result["candidates"] == 2 and result["measured"] == 0
    assert len(result["unavailable"]) == 2
    for line in result["unavailable"]:
        assert "Nexus Curiosity" in line and "Reconectează" in line, line
        assert "Setări → Conturi și e-mail" in line and "Settings" not in line, line
        assert "the-refresh-token" not in line
    assert calls == ["https://oauth2.googleapis.com/token"], "one refusal is the channel's answer"
    with Session(engine) as session:
        events = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == TOKEN_REFRESH_FAILED)
        ).all()
        assert session.scalars(select(AnalyticsSnapshot)).all() == []
    assert TOKEN_REFRESH_FAILED == "youtube.token_refresh_failed"
    (event,) = events
    assert event.aggregate_type == "youtube_connection" and event.aggregate_id == connection_id
    payload = event.payload
    assert payload["connection_id"] == connection_id
    assert payload["channel_id"] == channel and payload["channel_slot"] == "MAIN_FACTUAL"
    assert payload["error_class"] == "HTTPError" and payload["http_status"] == 400
    assert payload["oauth_error"] == "invalid_grant" and payload["auth_refused"] is True
    flat = str(payload)
    assert "the-refresh-token" not in flat and "the-client-secret" not in flat


def test_an_unreachable_google_is_no_data_for_the_channel_and_not_an_authentication_refusal(
    engine, channel, monkeypatch
):
    import app.providers.youtube_analytics as module
    from app.analytics.services import (
        TOKEN_REFRESH_FAILED,
        analytics_provider_for_channel,
        measure_channel_publications,
    )
    from app.models import DomainEvent

    _bind_connection(engine, channel)
    make_publication(engine, channel)
    monkeypatch.setattr(module, "urlopen", _unreachable)
    provider, _ = analytics_provider_for_channel(engine, _Vault(), channel)

    result = measure_channel_publications(engine, channel, provider)

    assert result["measured"] == 0 and len(result["unavailable"]) == 1
    assert "Reconectează" not in result["unavailable"][0]
    with Session(engine) as session:
        (event,) = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == TOKEN_REFRESH_FAILED)
        ).all()
    assert event.payload["auth_refused"] is False
    assert event.payload["error_class"] == "URLError"
