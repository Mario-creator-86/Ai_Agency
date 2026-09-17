"""The publish policy the Owner sets, per channel.

What was measured before this work: the daily run hardcoded ``privacy_status="private"`` and
took the first bound slot whatever film it held; ``ChannelRecord.upload_privacy_default`` was
read by nobody on a publish path; ``scheduled_publish_time`` was stored on the intent and
never sent; the YouTube adapter had no ``publishAt`` and no ``videos.update``; and analytics
measured every publication through whichever slot was bound first.

Tests here:
- the policy command is Owner-only, versioned, idempotent and recorded as a ledger event;
- "public" is refused while the studio is in TEST, and without the per-channel flag;
- ``resolve_publish_visibility`` truth table, including the private + publishAt pair;
- the upload metadata carries ``status.publishAt`` and the disclosure stays;
- ``update_visibility`` calls videos.update on a faked transport;
- per-channel routing refuses an unbound slot and never falls back to another channel;
- a public or unlisted publication carries the policy version that authorised it;
- performance intake asks each channel's own publications only.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.media.models import Storyboard
from app.models import DomainEvent, OwnerPolicy
from app.providers.analytics_base import AnalyticsProvider, VideoMetrics
from app.providers.deterministic_pub import DeterministicPublishingAdapter
from app.providers.publishing_base import RemoteStateUnavailable
from app.providers.youtube import YouTubeProvider
from app.publishing.models import ChannelRecord, PublicationRecord
from app.publishing.schemas import PublishPolicyCommand
from app.publishing.services import (
    PublishingGateError,
    change_publish_policy,
    evaluate_publishing_gate,
    list_channels,
    publish_media_asset,
    resolve_publish_visibility,
    seed_default_channels,
    select_channel_for,
)
from app.schemas import EnvironmentCommand
from app.services import CommandConflict, change_environment, utc_now
from app.youtube.models import YouTubeConnection
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_phase6_publishing import _create_verified_asset_bundle

# ----------------------------------------------------------------------------- helpers --


def _channels(engine) -> dict[str, dict]:
    seed_default_channels(engine)
    return {c["channel_type"]: c for c in list_channels(engine)}


def _to_production(engine) -> None:
    with Session(engine) as session:
        version = session.get(OwnerPolicy, 1).version
    change_environment(
        engine,
        EnvironmentCommand(command_id=uuid4(), expected_version=version, environment="PRODUCTION"),
    )


def _events(engine, event_type: str) -> list[DomainEvent]:
    with Session(engine) as session:
        return list(
            session.scalars(select(DomainEvent).where(DomainEvent.event_type == event_type))
        )


def _connect(engine, *, name: str = "Studio account") -> str:
    """A CONNECTED YouTube connection row, the way the OAuth flow leaves one (secrets are
    an opaque blob here; nothing in these tests decrypts it)."""
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
                remote_channel_id=f"UC_{connection_id[:8]}",
                remote_channel_title=name,
                channel_snapshot={},
                created_at=utc_now(),
            )
        )
    return connection_id


def _bind(engine, channel_id: str, connection_id: str) -> None:
    with Session(engine) as session, session.begin():
        channel = session.get(ChannelRecord, channel_id)
        channel.credentials_ref = f"youtube_connection:{connection_id}"


def _command(**fields: Any) -> PublishPolicyCommand:
    base: dict[str, Any] = {"command_id": uuid4(), "expected_version": 1}
    base.update(fields)
    return PublishPolicyCommand(**base)


def _response(body: dict, headers: dict[str, str] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.read = MagicMock(return_value=json.dumps(body).encode())
    resp.headers = headers or {}
    return resp


def _youtube(monkeypatch, outcomes: list[Any]) -> tuple[YouTubeProvider, list[Any]]:
    provider = YouTubeProvider(
        client_id="client",
        client_secret="secret",  # pragma: allowlist secret
        refresh_token="refresh",
        channel_id="UC_test",
    )
    monkeypatch.setattr(provider, "_get_access_token", lambda: "token")
    monkeypatch.setattr("app.providers.retry.sleep", lambda seconds: None)
    requests: list[Any] = []

    def urlopen(req: Any, timeout: float | None = None) -> Any:
        requests.append(req)
        if not outcomes:
            raise AssertionError("the adapter made more requests than the test expected")
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("app.providers.youtube.urlopen", urlopen)
    return provider, requests


# ---------------------------------------------------------------- the Owner's command --


def test_seeded_channels_start_private_with_the_flag_off(engine):
    channels = _channels(engine)
    for channel in channels.values():
        assert channel["autonomous_privacy"] == "private"
        assert channel["public_publish_enabled"] is False
        assert channel["publish_delay_minutes"] == 0
        assert channel["policy_version"] == 1
        assert channel["policy_changed_event_id"] is None


def test_the_policy_command_is_versioned_idempotent_and_recorded(client, headers, engine):
    channel = _channels(engine)["MAIN_FACTUAL"]
    url = f"/api/v1/publishing/channels/{channel['id']}/publish-policy"
    command_id = str(uuid4())
    body = {"command_id": command_id, "expected_version": 1, "autonomous_privacy": "unlisted"}

    assert client.post(url, json=body).status_code == 401

    first = client.post(url, json=body, headers=headers)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["status"] == "COMMITTED"
    assert result["channel"]["autonomous_privacy"] == "unlisted"
    assert result["channel"]["policy_version"] == 2
    assert result["channel"]["policy_changed_event_id"] == result["event_id"]

    events = _events(engine, "publishing.channel_policy_changed")
    assert len(events) == 1
    payload = events[0].payload
    assert payload["old"]["autonomous_privacy"] == "private"
    assert payload["new"]["autonomous_privacy"] == "unlisted"
    assert payload["old"]["policy_version"] == 1 and payload["new"]["policy_version"] == 2
    assert payload["environment"] == "TEST"

    # The same command again is the same answer, and nothing happens a second time.
    again = client.post(url, json=body, headers=headers)
    assert again.status_code == 200 and again.json() == result
    assert len(_events(engine, "publishing.channel_policy_changed")) == 1

    # The same id with different input is a mistake, refused rather than guessed about.
    conflicting = client.post(url, json={**body, "autonomous_privacy": "private"}, headers=headers)
    assert conflicting.status_code == 409

    # A stale version is refused: the screen must look at the row it is changing.
    stale = client.post(
        url,
        json={"command_id": str(uuid4()), "expected_version": 1, "autonomous_privacy": "private"},
        headers=headers,
    )
    assert stale.status_code == 409

    # Fields the command does not know are refused, not ignored.
    extra = client.post(
        url,
        json={"command_id": str(uuid4()), "expected_version": 2, "upload_privacy_default": "x"},
        headers=headers,
    )
    assert extra.status_code == 422

    # A command that changes nothing is NO_CHANGE: no version bump, no event.
    same = client.post(
        url,
        json={"command_id": str(uuid4()), "expected_version": 2, "autonomous_privacy": "unlisted"},
        headers=headers,
    )
    assert same.status_code == 200 and same.json()["status"] == "NO_CHANGE"
    assert same.json()["channel"]["policy_version"] == 2
    assert len(_events(engine, "publishing.channel_policy_changed")) == 1

    # Every mutation of the channel is reflected in the read model.
    assert client.get(url.rsplit("/", 1)[0], headers=headers).json()["autonomous_privacy"] == (
        "unlisted"
    )


def test_public_is_refused_in_test_and_without_its_own_flag(client, headers, engine):
    channel = _channels(engine)["MAIN_FACTUAL"]
    url = f"/api/v1/publishing/channels/{channel['id']}/publish-policy"

    # In TEST nothing may be told to go public, whatever the flag says.
    refused = client.post(
        url,
        json={
            "command_id": str(uuid4()),
            "expected_version": 1,
            "autonomous_privacy": "public",
            "public_publish_enabled": True,
        },
        headers=headers,
    )
    assert refused.status_code == 422
    assert "TEST" in refused.json()["detail"]
    assert "public" in refused.json()["detail"]

    _to_production(engine)

    # In PRODUCTION "public" still needs the flag in the same command.
    no_flag = client.post(
        url,
        json={"command_id": str(uuid4()), "expected_version": 1, "autonomous_privacy": "public"},
        headers=headers,
    )
    assert no_flag.status_code == 422
    assert "public_publish_enabled" in no_flag.json()["detail"]

    # Nothing above changed the channel.
    with Session(engine) as session:
        row = session.get(ChannelRecord, channel["id"])
        assert row.policy_version == 1 and row.autonomous_privacy == "private"
    assert _events(engine, "publishing.channel_policy_changed") == []

    allowed = client.post(
        url,
        json={
            "command_id": str(uuid4()),
            "expected_version": 1,
            "autonomous_privacy": "public",
            "public_publish_enabled": True,
            "publish_delay_minutes": 30,
        },
        headers=headers,
    )
    assert allowed.status_code == 200, allowed.text
    view = allowed.json()["channel"]
    assert view["autonomous_privacy"] == "public"
    assert view["public_publish_enabled"] is True
    assert view["publish_delay_minutes"] == 30
    assert view["policy_version"] == 2


def test_the_service_refuses_an_unknown_channel_and_a_stale_version(engine):
    channel = _channels(engine)["OFFICE_SERIAL"]
    with pytest.raises(LookupError):
        change_publish_policy(engine, str(uuid4()), _command(autonomous_privacy="unlisted"))
    with pytest.raises(CommandConflict):
        change_publish_policy(
            engine, channel["id"], _command(expected_version=7, autonomous_privacy="unlisted")
        )


# ------------------------------------------------------------ resolve_publish_visibility --


def _policy(
    privacy: str = "private", enabled: bool = False, delay: int = 0, version: int = 1
) -> SimpleNamespace:
    return SimpleNamespace(
        autonomous_privacy=privacy,
        public_publish_enabled=enabled,
        publish_delay_minutes=delay,
        policy_version=version,
    )


@pytest.mark.parametrize(
    ("channel", "environment", "privacy", "scheduled"),
    [
        (_policy(), "TEST", "private", False),
        (_policy(), "PRODUCTION", "private", False),
        (_policy("unlisted"), "TEST", "unlisted", False),
        (_policy("unlisted"), "PRODUCTION", "unlisted", False),
        (_policy("public", enabled=False), "PRODUCTION", "private", False),
        (_policy("public", enabled=True), "TEST", "private", False),
        (_policy("public", enabled=True), "PRODUCTION", "public", False),
        (_policy("public", enabled=True, delay=45), "PRODUCTION", "private", True),
        (_policy("public", enabled=True, delay=45), "TEST", "private", False),
        (_policy("unlisted", delay=45), "PRODUCTION", "unlisted", False),
    ],
)
def test_resolve_publish_visibility_truth_table(channel, environment, privacy, scheduled):
    now = datetime(2026, 9, 17, 5, 0, tzinfo=UTC)
    resolved = resolve_publish_visibility(channel, environment, now=now)
    assert resolved["privacy_status"] == privacy
    assert resolved["policy_version"] == 1
    assert resolved["reason"]
    if scheduled:
        # YouTube's scheduled release is a private upload with a publishAt: the pair is
        # what the resolver hands over, never a public upload with a delay attached.
        assert resolved["publish_at"] == "2026-09-17T05:45:00Z"
        assert resolved["release_privacy"] == "public"
    else:
        assert resolved["publish_at"] is None


def test_a_row_written_before_the_policy_existed_resolves_private():
    channel = SimpleNamespace(
        autonomous_privacy=None, public_publish_enabled=None, publish_delay_minutes=None
    )
    resolved = resolve_publish_visibility(channel, "PRODUCTION")
    assert resolved["privacy_status"] == "private" and resolved["publish_at"] is None


# ---------------------------------------------------------------- the YouTube adapter --


def test_upload_metadata_carries_publish_at_and_keeps_the_disclosure(monkeypatch, tmp_path):
    video = tmp_path / "film.mp4"
    video.write_bytes(b"x" * 8)
    provider, requests = _youtube(
        monkeypatch,
        [
            _response({}, {"Location": "https://www.googleapis.com/upload/session"}),
            _response({"id": "vid-9"}),
        ],
    )

    result = asyncio.run(
        provider.upload_video(
            video,
            title="t",
            description="d",
            tags=[],
            privacy_status="private",
            extra={"idempotency_key": "k", "publish_at": "2026-09-17T05:45:00Z"},
        )
    )

    assert result.status == "CONFIRMED" and result.remote_video_id == "vid-9"
    metadata = json.loads(requests[0].data.decode("utf-8"))
    assert metadata["status"]["privacyStatus"] == "private"
    assert metadata["status"]["publishAt"] == "2026-09-17T05:45:00Z"
    assert metadata["status"]["containsSyntheticMedia"] is True
    assert "generative AI" in metadata["snippet"]["description"]


def test_upload_metadata_has_no_publish_at_unless_asked(monkeypatch, tmp_path):
    video = tmp_path / "film.mp4"
    video.write_bytes(b"x" * 8)
    provider, requests = _youtube(
        monkeypatch,
        [
            _response({}, {"Location": "https://www.googleapis.com/upload/session"}),
            _response({"id": "vid-1"}),
        ],
    )
    asyncio.run(
        provider.upload_video(video, title="t", description="d", tags=[], privacy_status="unlisted")
    )
    metadata = json.loads(requests[0].data.decode("utf-8"))
    assert metadata["status"]["privacyStatus"] == "unlisted"
    assert "publishAt" not in metadata["status"]


def test_update_visibility_calls_videos_update_on_the_status_part(monkeypatch):
    provider, requests = _youtube(
        monkeypatch,
        [
            _response(
                {"id": "vid-9", "status": {"privacyStatus": "public", "uploadStatus": "processed"}}
            )
        ],
    )

    status = asyncio.run(provider.update_visibility("vid-9", "public"))

    assert status.exists and status.privacy_status == "public"
    request = requests[0]
    assert request.get_method() == "PUT"
    assert request.full_url.startswith("https://www.googleapis.com/youtube/v3/videos?")
    assert "part=status" in request.full_url
    body = json.loads(request.data.decode("utf-8"))
    assert body["id"] == "vid-9"
    assert body["status"]["privacyStatus"] == "public"
    # The disclosure is part of the status resource; an update must not clear it.
    assert body["status"]["containsSyntheticMedia"] is True
    assert request.get_header("Authorization") == "Bearer token"


def test_update_visibility_refuses_a_value_youtube_does_not_know(monkeypatch):
    provider, requests = _youtube(monkeypatch, [])
    with pytest.raises(ValueError):
        asyncio.run(provider.update_visibility("vid-9", "hidden"))
    assert requests == []


def test_update_visibility_is_unavailable_when_youtube_cannot_be_asked(monkeypatch):
    unconfigured = YouTubeProvider(client_id="", client_secret="", refresh_token="", channel_id="")
    with pytest.raises(RemoteStateUnavailable):
        asyncio.run(unconfigured.update_visibility("vid-9", "public"))

    provider, _ = _youtube(monkeypatch, [OSError("connection reset")] * 5)
    with pytest.raises(RemoteStateUnavailable):
        asyncio.run(provider.update_visibility("vid-9", "public"))

    # An answer without the video is not a change of visibility either.
    provider, _ = _youtube(monkeypatch, [_response({"items": []})])
    with pytest.raises(RemoteStateUnavailable):
        asyncio.run(provider.update_visibility("vid-9", "public"))


# ------------------------------------------------------------------ channel routing --


def test_routing_refuses_an_unbound_slot_and_never_falls_back(engine, tmp_path):
    channels = _channels(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path)

    # A factual film goes to MAIN_FACTUAL; with the slot unbound, it goes nowhere.
    unbound = select_channel_for(engine, bundle["asset_id"])
    assert unbound["status"] == "SKIPPED"
    assert unbound["channel_type"] == "MAIN_FACTUAL"
    assert unbound["channel_id"] == channels["MAIN_FACTUAL"]["id"]
    assert "legat" in unbound["reason"]

    # Binding the other slot changes nothing for this film: no fallback to another channel.
    serial_account = _connect(engine, name="Serial account")
    _bind(engine, channels["OFFICE_SERIAL"]["id"], serial_account)
    still = select_channel_for(engine, bundle["asset_id"])
    assert still["status"] == "SKIPPED" and still["channel_id"] == channels["MAIN_FACTUAL"]["id"]

    main_account = _connect(engine, name="Main account")
    _bind(engine, channels["MAIN_FACTUAL"]["id"], main_account)
    selected = select_channel_for(engine, bundle["asset_id"])
    assert selected["status"] == "SELECTED"
    assert selected["channel_id"] == channels["MAIN_FACTUAL"]["id"]
    assert selected["channel_type"] == "MAIN_FACTUAL"
    assert selected["youtube_connection_id"] == main_account
    assert selected["channel_name"] == channels["MAIN_FACTUAL"]["channel_name"]


def test_routing_follows_the_storyboard_channel_when_it_is_set(engine, tmp_path):
    channels = _channels(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    _bind(engine, channels["MAIN_FACTUAL"]["id"], _connect(engine, name="Main account"))

    # A storyboard produced for the serial names its channel; the film follows it there,
    # and an unbound serial slot is a refusal even though the main slot could publish.
    with Session(engine) as session, session.begin():
        board = session.scalars(
            select(Storyboard).where(Storyboard.script_draft_id == bundle["script_id"])
        ).one()
        board_id = board.id
        board.channel_id = channels["OFFICE_SERIAL"]["id"]
    routed = select_channel_for(engine, bundle["asset_id"])
    assert routed["status"] == "SKIPPED" and routed["channel_type"] == "OFFICE_SERIAL"

    # A revoked binding is not a binding.
    serial_account = _connect(engine, name="Serial account")
    _bind(engine, channels["OFFICE_SERIAL"]["id"], serial_account)
    with Session(engine) as session, session.begin():
        session.get(YouTubeConnection, serial_account).status = "ERROR"
    assert select_channel_for(engine, bundle["asset_id"])["status"] == "SKIPPED"

    with Session(engine) as session, session.begin():
        session.get(YouTubeConnection, serial_account).status = "CONNECTED"
    routed = select_channel_for(engine, bundle["asset_id"])
    assert routed["status"] == "SELECTED"
    assert routed["channel_type"] == "OFFICE_SERIAL"
    assert routed["youtube_connection_id"] == serial_account

    # The serial's series key routes the same way when no channel id is written.
    with Session(engine) as session, session.begin():
        board = session.get(Storyboard, board_id)
        board.channel_id = None
        board.series_key = "office_serial"
    assert select_channel_for(engine, bundle["asset_id"])["channel_type"] == "OFFICE_SERIAL"


def test_routing_reports_a_film_without_provenance(engine):
    _channels(engine)
    unknown = select_channel_for(engine, str(uuid4()))
    assert unknown["status"] == "SKIPPED" and unknown["channel_id"] is None


# ------------------------------------------------------- the sixth check and the stamp --


class RecordingPublisher(DeterministicPublishingAdapter):
    """The simulator, remembering what it was asked to upload."""

    def __init__(self) -> None:
        super().__init__()
        self.uploads: list[dict[str, Any]] = []

    async def upload_video(self, file_path: Path, **kwargs: Any) -> Any:
        self.uploads.append(dict(kwargs))
        return await super().upload_video(file_path, **kwargs)


def test_a_private_upload_keeps_the_five_gates(engine, tmp_path):
    channel = _channels(engine)["MAIN_FACTUAL"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    verdict = evaluate_publishing_gate(engine, bundle["asset_id"], channel["id"])
    assert verdict["eligible"] and len(verdict["checks"]) == 5


def test_an_unlisted_publication_carries_the_policy_version_that_authorised_it(engine, tmp_path):
    channel = _channels(engine)["MAIN_FACTUAL"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    change_publish_policy(engine, channel["id"], _command(autonomous_privacy="unlisted"))
    with Session(engine) as session:
        row = session.get(ChannelRecord, channel["id"])
        assert row.policy_version == 2
        resolved = resolve_publish_visibility(row, "TEST")
    assert resolved == {
        **resolved,
        "privacy_status": "unlisted",
        "publish_at": None,
        "policy_version": 2,
    }

    # Without the stamp the sixth check refuses; the five before it are untouched.
    unstamped = evaluate_publishing_gate(
        engine, bundle["asset_id"], channel["id"], privacy_status="unlisted"
    )
    assert not unstamped["eligible"]
    names = [c["check_name"] for c in unstamped["checks"]]
    assert names[:5] == [
        "AUTONOMY_GATE",
        "MEDIA_ASSET_ON_DISK",
        "QC_GATE",
        "FACTUAL_INTEGRITY_GATE",
        "DUPLICATE_PROTECTION_GATE",
    ]
    assert names[5] == "POLICY_AUTHORISATION_GATE"
    assert all(c["passed"] for c in unstamped["checks"][:5])

    # A stamp from a policy that has since changed is refused too.
    stale = evaluate_publishing_gate(
        engine, bundle["asset_id"], channel["id"], privacy_status="unlisted", policy_version=1
    )
    assert not stale["eligible"] and "1" in stale["reasons"][0]

    publisher = RecordingPublisher()
    with pytest.raises(PublishingGateError):
        publish_media_asset(
            engine,
            media_asset_id=bundle["asset_id"],
            channel_id=channel["id"],
            title="Unlisted film",
            description="",
            tags=[],
            privacy_status="unlisted",
            provider=publisher,
            policy_version=1,
        )
    assert publisher.uploads == []

    published = publish_media_asset(
        engine,
        media_asset_id=bundle["asset_id"],
        channel_id=channel["id"],
        title="Unlisted film",
        description="",
        tags=[],
        privacy_status=resolved["privacy_status"],
        provider=publisher,
        policy_version=resolved["policy_version"],
    )
    assert published["status"] == "PUBLISHED_SIMULATED"
    assert published["policy_version"] == 2
    assert published["privacy_status"] == "unlisted"
    with Session(engine) as session:
        record = session.get(PublicationRecord, published["id"])
        assert record.policy_version == 2
    assert publisher.uploads[-1]["privacy_status"] == "unlisted"


def test_a_visibility_the_policy_does_not_allow_is_refused_even_with_the_stamp(engine, tmp_path):
    """The stamp says which policy was in force; the policy still has to allow the release.

    An unlisted intent on a channel whose policy says private carries the current version
    and is refused all the same: visibility is decided in one place, the Owner's policy.
    """
    channel = _channels(engine)["MAIN_FACTUAL"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    verdict = evaluate_publishing_gate(
        engine, bundle["asset_id"], channel["id"], privacy_status="unlisted", policy_version=1
    )
    assert not verdict["eligible"]
    sixth = verdict["checks"][5]
    assert sixth["check_name"] == "POLICY_AUTHORISATION_GATE" and not sixth["passed"]
    assert "private" in verdict["reasons"][0] and "unlisted" in verdict["reasons"][0]

    # A scheduled release is judged as the public film it becomes, and refused the same way.
    scheduled = evaluate_publishing_gate(
        engine,
        bundle["asset_id"],
        channel["id"],
        privacy_status="private",
        policy_version=1,
        scheduled_publish_time="2026-09-17T05:45:00Z",
    )
    assert not scheduled["eligible"] and "public" in scheduled["reasons"][0]


def test_a_scheduled_release_is_sent_as_private_with_publish_at(engine, tmp_path):
    channel = _channels(engine)["MAIN_FACTUAL"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    # Only a public policy in PRODUCTION with a delay produces a scheduled release.
    _to_production(engine)
    change_publish_policy(
        engine,
        channel["id"],
        _command(
            autonomous_privacy="public", public_publish_enabled=True, publish_delay_minutes=45
        ),
    )
    with Session(engine) as session:
        resolved = resolve_publish_visibility(
            session.get(ChannelRecord, channel["id"]),
            "PRODUCTION",
            now=datetime(2026, 9, 17, 5, 0, tzinfo=UTC),
        )
    assert resolved["privacy_status"] == "private"
    assert resolved["publish_at"] == "2026-09-17T05:45:00Z"
    assert resolved["policy_version"] == 2

    publisher = RecordingPublisher()
    published = publish_media_asset(
        engine,
        media_asset_id=bundle["asset_id"],
        channel_id=channel["id"],
        title="Scheduled film",
        description="",
        tags=[],
        privacy_status=resolved["privacy_status"],
        provider=publisher,
        policy_version=resolved["policy_version"],
        scheduled_publish_time=resolved["publish_at"],
    )
    assert published["scheduled_publish_time"] == "2026-09-17T05:45:00Z"
    assert published["policy_version"] == 2
    assert publisher.uploads[-1]["privacy_status"] == "private"
    assert publisher.uploads[-1]["extra"]["publish_at"] == "2026-09-17T05:45:00Z"
    with Session(engine) as session:
        event = session.scalars(
            select(DomainEvent).where(
                DomainEvent.event_type == "publishing.video_published_simulated"
            )
        ).one()
    assert event.payload["publish_at"] == "2026-09-17T05:45:00Z"
    assert event.payload["policy_version"] == 2


# ------------------------------------------------------- analytics, per channel --


class RecordingAnalytics(AnalyticsProvider):
    PROVIDER_NAME = "TEST_RECORDING"

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def fetch_video_metrics(
        self, remote_video_id: str, window: str = "LIFETIME"
    ) -> VideoMetrics:
        self.asked.append(remote_video_id)
        return VideoMetrics(
            remote_video_id=remote_video_id,
            views=10,
            watch_time_seconds=100.0,
            average_view_percentage=50.0,
            impressions=100,
            ctr_percentage=5.0,
            likes=1,
            comments=0,
            shares=0,
            subscribers_gained=0,
            subscribers_lost=0,
            window=window,
        )

    async def fetch_channel_metrics(self, remote_channel_id: str, window: str = "LIFETIME"):  # type: ignore[no-untyped-def]
        raise NotImplementedError


def _published(engine, channel_id: str, asset_id: str, remote_id: str) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            PublicationRecord(
                id=str(uuid4()),
                channel_id=channel_id,
                media_asset_id=asset_id,
                title=remote_id,
                description="",
                tags_json=[],
                privacy_status="private",
                status="PUBLISHED",
                idempotency_key=str(uuid4()),
                remote_video_id=remote_id,
                remote_url=f"https://youtube.com/shorts/{remote_id}",
                created_at=utc_now(),
            )
        )


def test_performance_intake_measures_one_channel_through_its_own_publications(engine, tmp_path):
    from app.analytics.services import measure_channel_publications

    channels = _channels(engine)
    main, serial = channels["MAIN_FACTUAL"]["id"], channels["OFFICE_SERIAL"]["id"]
    asset_a = _create_verified_asset_bundle(engine, tmp_path / "a")["asset_id"]
    asset_b = _create_verified_asset_bundle(engine, tmp_path / "b")["asset_id"]
    _published(engine, main, asset_a, "main-video")
    _published(engine, serial, asset_b, "serial-video")

    provider = RecordingAnalytics()
    outcome = measure_channel_publications(engine, main, provider)

    assert provider.asked == ["main-video"]
    assert outcome["channel_id"] == main
    assert outcome["measured"] == 1 and outcome["unavailable"] == []


def test_analytics_provider_for_channel_refuses_an_unbound_slot(engine):
    from app.analytics.services import analytics_provider_for_channel

    channels = _channels(engine)
    main = channels["MAIN_FACTUAL"]["id"]

    class Vault:
        def decrypt(self, value: str) -> dict:
            return {"client_secret": "s", "refresh_token": "r"}  # pragma: allowlist secret

    provider, reason = analytics_provider_for_channel(engine, Vault(), main)
    assert provider is None and "legat" in reason

    # Another connected account in the studio is not this channel's account.
    _connect(engine, name="Somebody else")
    provider, reason = analytics_provider_for_channel(engine, Vault(), main)
    assert provider is None

    own = _connect(engine, name="Main account")
    _bind(engine, main, own)
    provider, reason = analytics_provider_for_channel(engine, Vault(), main)
    assert provider is not None and reason == ""
    assert provider.channel_id == f"UC_{own[:8]}"
