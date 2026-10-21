"""The publish policy the Owner sets, per channel.

What was measured before this work: the daily run hardcoded ``privacy_status="private"`` and
took the first bound slot whatever film it held; ``ChannelRecord.upload_privacy_default`` was
read by nobody on a publish path; ``scheduled_publish_time`` was stored on the intent and
never sent; the YouTube adapter had no ``publishAt`` and no ``videos.update``; and analytics
measured every publication through whichever slot was bound first.

Tests here:
- the policy command is Owner-only, versioned, idempotent and recorded as a ledger event;
- "public" is refused while the studio is in TEST, and without the per-channel flag, and
  the flag alone cannot bring a policy back to public in TEST;
- an unlisted or public policy resolves private outside PRODUCTION (an unlisted film is a
  release anyone with the link can watch);
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
        assert channel["director_may_approve_episodes"] is False
        assert channel["policy_version"] == 1
        assert channel["policy_changed_event_id"] is None


def test_the_director_approves_episodes_only_under_the_owners_command(engine):
    """Measured before this: `director_may_approve_episodes` was read from Channel B's
    `series_rules_json`, and nothing wrote it there — the production-policy validator would
    have refused the key — so every episode the Director passed stayed DRAFT for the Owner.
    The flag is a column of the publish policy now, set by the same versioned command."""
    from app.story.review import director_may_approve_episodes

    channels = _channels(engine)
    serial, factual = channels["OFFICE_SERIAL"], channels["MAIN_FACTUAL"]

    # A fresh channel leaves the episodes to the Owner.
    with Session(engine) as session:
        assert director_may_approve_episodes(session) is False

    command = _command(director_may_approve_episodes=True)
    result = change_publish_policy(engine, serial["id"], command)
    assert result["status"] == "COMMITTED"
    assert result["channel"]["director_may_approve_episodes"] is True
    assert result["channel"]["policy_version"] == 2
    events = _events(engine, "publishing.channel_policy_changed")
    assert len(events) == 1
    payload = events[0].payload
    assert payload["changed"] == ["director_may_approve_episodes"]
    assert payload["old"]["director_may_approve_episodes"] is False
    assert payload["new"]["director_may_approve_episodes"] is True
    assert payload["old"]["autonomous_privacy"] == payload["new"]["autonomous_privacy"]
    with Session(engine) as session:
        assert director_may_approve_episodes(session) is True
        row = session.get(ChannelRecord, serial["id"])
        assert row.director_may_approve_episodes is True
        # The flag lives in its own column; the production rules are untouched.
        assert row.series_rules_json == {}

    # The same command again is the same answer, and nothing happens a second time.
    assert change_publish_policy(engine, serial["id"], command) == result
    assert len(_events(engine, "publishing.channel_policy_changed")) == 1

    # A stale version is refused: the screen must look at the row it is changing.
    with pytest.raises(CommandConflict):
        change_publish_policy(engine, serial["id"], _command(director_may_approve_episodes=False))

    # Asking for what is already the case is NO_CHANGE: no version bump, no event.
    same = change_publish_policy(
        engine, serial["id"], _command(expected_version=2, director_may_approve_episodes=True)
    )
    assert same["status"] == "NO_CHANGE" and same["event_id"] is None
    assert same["channel"]["policy_version"] == 2
    assert len(_events(engine, "publishing.channel_policy_changed")) == 1

    # A field left out keeps its value: changing the privacy does not clear the flag.
    other = change_publish_policy(
        engine, serial["id"], _command(expected_version=2, autonomous_privacy="unlisted")
    )
    assert other["status"] == "COMMITTED"
    assert other["channel"]["director_may_approve_episodes"] is True
    assert other["channel"]["policy_version"] == 3

    # The Owner takes the flag back through the same command, recorded like the grant.
    revoked = change_publish_policy(
        engine, serial["id"], _command(expected_version=3, director_may_approve_episodes=False)
    )
    assert revoked["status"] == "COMMITTED"
    assert (
        _events(engine, "publishing.channel_policy_changed")[-1].payload["new"][
            "director_may_approve_episodes"
        ]
        is False
    )
    with Session(engine) as session:
        assert director_may_approve_episodes(session) is False

    # The flag on the factual channel is not the serial's policy: only Channel B is read.
    change_publish_policy(engine, factual["id"], _command(director_may_approve_episodes=True))
    with Session(engine) as session:
        assert director_may_approve_episodes(session) is False
    flags = {c["channel_type"]: c["director_may_approve_episodes"] for c in list_channels(engine)}
    assert flags == {"OFFICE_SERIAL": False, "MAIN_FACTUAL": True}


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
    # W34: the refusal says what to do on the page, not the field name (the page's switch
    # for the public release is the same command's second field).
    assert "public_publish_enabled" not in no_flag.json()["detail"]
    assert "public" in no_flag.json()["detail"]

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
        (_policy("unlisted"), "TEST", "private", False),
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

    # A storyboard produced for the serial names its channel and carries the serial's key
    # (`storyboard_from_episode` writes both); the film follows it there, and an unbound
    # serial slot is a refusal even though the main slot could publish. A pin that
    # contradicts the key goes nowhere (tests/test_phase_bc_adversary.py).
    with Session(engine) as session, session.begin():
        board = session.scalars(
            select(Storyboard).where(Storyboard.script_draft_id == bundle["script_id"])
        ).one()
        board_id = board.id
        board.channel_id = channels["OFFICE_SERIAL"]["id"]
        board.series_key = "office_serial"
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
    # An unlisted release, like a public one, exists only in PRODUCTION.
    _to_production(engine)
    change_publish_policy(engine, channel["id"], _command(autonomous_privacy="unlisted"))
    with Session(engine) as session:
        row = session.get(ChannelRecord, channel["id"])
        assert row.policy_version == 2
        resolved = resolve_publish_visibility(row, "PRODUCTION")
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
    assert stale["reason_codes"] == ["POLICY_VERSION_STALE"]

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
    assert "privat" in verdict["reasons"][0] and "nelistat" in verdict["reasons"][0]
    assert verdict["reason_codes"] == ["POLICY_VISIBILITY_EXCEEDED"]
    assert (sixth["data"]["requested"], sixth["data"]["authorised"]) == ("unlisted", "private")

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
    assert scheduled["checks"][5]["data"]["requested"] == "public"


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


# ------------------------------------------------- YouTube's own visibility (2026-10-02) --
#
# PUB-05 / SELL-07: Google keeps every upload from an unaudited API project (created after
# 28 July 2020) private until the project passes the YouTube API Services audit. The adapter
# read only the video id from the insert answer, and the record said what was asked for: a
# «public, PUBLISHED» film nobody but the Owner could see. The answer's status is now kept.

from app.agents.models import AgentMessage  # noqa: E402
from app.providers.publishing_base import UploadResult  # noqa: E402
from app.publishing.services import LOCKED_PRIVATE_LETTER  # noqa: E402


def test_the_upload_result_carries_the_visibility_youtube_gave(monkeypatch, tmp_path):
    video = tmp_path / "film.mp4"
    video.write_bytes(b"x" * 8)
    provider, _ = _youtube(
        monkeypatch,
        [
            _response({}, {"Location": "https://www.googleapis.com/upload/session"}),
            _response(
                {"id": "vid-9", "status": {"privacyStatus": "private", "uploadStatus": "uploaded"}}
            ),
        ],
    )

    result = asyncio.run(
        provider.upload_video(video, title="t", description="d", tags=[], privacy_status="public")
    )

    assert result.status == "CONFIRMED"
    assert result.privacy_status == "private"
    assert result.upload_status == "uploaded"


class LockedPrivate(DeterministicPublishingAdapter):
    """A real-looking platform that answers every upload private, as Google does for an
    unaudited project."""

    IS_SIMULATED = False

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    async def upload_video(self, file_path: Path, **kwargs: Any) -> Any:
        self.count += 1
        return UploadResult(
            remote_video_id=f"yt-{self.count}",
            remote_url=f"https://youtube.com/shorts/yt-{self.count}",
            status="CONFIRMED",
            privacy_status="private",
            upload_status="uploaded",
        )


def _letters(engine) -> list[AgentMessage]:
    with Session(engine) as session:
        return [
            row
            for row in session.scalars(
                select(AgentMessage).where(AgentMessage.intent == "ESCALATE")
            )
            if row.to_agent_id is None and (row.body_json or {}).get("to") == "Owner"
        ]


def test_a_film_youtube_kept_private_is_recorded_as_private_with_one_letter(engine, tmp_path):
    channel = _channels(engine)["MAIN_FACTUAL"]
    _bind(engine, channel["id"], _connect(engine))
    _to_production(engine)
    change_publish_policy(engine, channel["id"], _command(autonomous_privacy="unlisted"))
    platform = LockedPrivate()
    for name in ("one", "two"):
        bundle = _create_verified_asset_bundle(engine, tmp_path / name)
        published = publish_media_asset(
            engine,
            media_asset_id=bundle["asset_id"],
            channel_id=channel["id"],
            title=f"Film {name}",
            description="",
            tags=[],
            privacy_status="unlisted",
            provider=platform,
            policy_version=2,
        )
        assert published["status"] == "PUBLISHED"
        with Session(engine) as session:
            record = session.get(PublicationRecord, published["id"])
            assert record.privacy_status == "unlisted"
            assert record.remote_privacy_status == "private"
            assert "auditul" in (record.error_detail or "")

    assert len(_events(engine, "publishing.visibility_locked_private")) == 2
    letters = _letters(engine)
    assert len(letters) == 1, [letter.subject for letter in letters]
    assert LOCKED_PRIVATE_LETTER in (letters[0].body_text or "")


def test_a_private_upload_answered_private_is_no_lock(engine, tmp_path):
    channel = _channels(engine)["MAIN_FACTUAL"]
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    published = publish_media_asset(
        engine,
        media_asset_id=bundle["asset_id"],
        channel_id=channel["id"],
        title="Private film",
        description="",
        tags=[],
        privacy_status="private",
        provider=LockedPrivate(),
    )
    assert published["status"] == "PUBLISHED"
    assert _events(engine, "publishing.visibility_locked_private") == []
    assert _letters(engine) == []


def test_the_preflight_warns_after_the_first_locked_upload_until_one_goes_out_visible(
    engine, tmp_path
):
    from app.runbook.preflight import _youtube_visibility_check  # noqa: PLC0415

    channel = _channels(engine)["MAIN_FACTUAL"]
    _bind(engine, channel["id"], _connect(engine, name="Studio account"))
    with Session(engine) as session:
        assert _youtube_visibility_check(session)["ok"] is True

    _to_production(engine)
    change_publish_policy(engine, channel["id"], _command(autonomous_privacy="unlisted"))
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    publish_media_asset(
        engine,
        media_asset_id=bundle["asset_id"],
        channel_id=channel["id"],
        title="Locked film",
        description="",
        tags=[],
        privacy_status="unlisted",
        provider=LockedPrivate(),
        policy_version=2,
    )
    with Session(engine) as session:
        line = _youtube_visibility_check(session)
    assert line["ok"] is False
    assert line["severity"] == "DEGRADING"
    assert line["code"] == "youtube_visibility.locked_private"
    assert "Studio account" in line["message"] and "auditul" in line["message"]


# ------------------------------------------- the disclosure and the upload's own settings --
# Audit PUB-07 / PUB-09 / Q9 (2026-10-02). Before: the services added "… by the <brand> studio
# pipeline." and the adapter cut the description at 4800 characters, then added its own
# "… by an autonomous studio pipeline." when that exact line was missing: a long description
# lost the studio's block, a short one carried two disclosure lines. The upload hard-coded
# categoryId 28 for both channels, selfDeclaredMadeForKids False, no language at all, and two
# filler tags ("ai generated", "synthetic media") the containsSyntheticMedia flag already says.

from app.providers.youtube import DEFAULT_DISCLOSURE  # noqa: E402
from app.publishing import services as publishing_services  # noqa: E402
from app.publishing.services import (  # noqa: E402
    AI_DISCLOSURE,
    disclosure_sentence,
    publication_footer,
)


def _studio(**fields: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "content_language": "en",
        "studio_display_name": None,
        "ai_disclosure_texts": {},
    }
    base.update(fields)
    return SimpleNamespace(**base)


def _sent(requests: list[Any]) -> dict[str, Any]:
    return json.loads(requests[0].data.decode("utf-8"))


def _two_answers() -> list[Any]:
    return [
        _response({}, {"Location": "https://www.googleapis.com/upload/session"}),
        _response({"id": "vid-1", "status": {"privacyStatus": "private"}}),
    ]


def _disclosure_lines(description: str) -> list[str]:
    return [line for line in description.splitlines() if "generative AI" in line]


def test_a_short_description_carries_exactly_one_disclosure_line(monkeypatch, tmp_path):
    video = tmp_path / "film.mp4"
    video.write_bytes(b"x" * 8)
    footer = publication_footer(None, None, None, settings=_studio())
    provider, requests = _youtube(monkeypatch, _two_answers())
    asyncio.run(
        provider.upload_video(
            video, title="t", description=f"What the film shows.\n\n{footer}", tags=[]
        )
    )
    description = _sent(requests)["snippet"]["description"]
    assert len(_disclosure_lines(description)) == 1
    assert description == f"What the film shows.\n\n{footer}"


def test_a_direct_upload_with_no_disclosure_gets_one_line(monkeypatch, tmp_path):
    video = tmp_path / "film.mp4"
    video.write_bytes(b"x" * 8)
    provider, requests = _youtube(monkeypatch, _two_answers())
    asyncio.run(provider.upload_video(video, title="t", description="d", tags=[]))
    description = _sent(requests)["snippet"]["description"]
    assert _disclosure_lines(description) == [DEFAULT_DISCLOSURE]


def test_a_studio_disclosure_in_another_language_is_not_doubled(monkeypatch, tmp_path):
    video = tmp_path / "film.mp4"
    video.write_bytes(b"x" * 8)
    footer = publication_footer(None, None, None, settings=_studio(content_language="ro"))
    provider, requests = _youtube(monkeypatch, _two_answers())
    asyncio.run(
        provider.upload_video(
            video,
            title="t",
            description=f"Despre film.\n\n{footer}",
            tags=[],
            extra={"disclosed": True},
        )
    )
    description = _sent(requests)["snippet"]["description"]
    assert description == f"Despre film.\n\n{footer}"
    assert "Disclosure:" not in description


def test_a_long_description_keeps_the_footer_inside_five_thousand_bytes(monkeypatch, tmp_path):
    video = tmp_path / "film.mp4"
    video.write_bytes(b"x" * 8)
    footer = publication_footer(None, "https://example.org/ai", None, settings=_studio())
    body = "Știință și țară " * 400  # about 7,600 bytes of Romanian
    provider, requests = _youtube(monkeypatch, _two_answers())
    asyncio.run(provider.upload_video(video, title="t", description=f"{body}\n\n{footer}", tags=[]))
    description = _sent(requests)["snippet"]["description"]
    assert len(description.encode("utf-8")) <= 5000
    assert description.endswith(footer)
    assert len(_disclosure_lines(description)) == 1


def test_the_disclosure_text_comes_from_the_settings_per_content_language():
    assert AI_DISCLOSURE == "Disclosure: this video was produced with generative AI."
    assert disclosure_sentence(_studio()) == AI_DISCLOSURE
    assert disclosure_sentence(_studio(studio_display_name="Nexus Films")) == (
        "Disclosure: this video was produced with generative AI by Nexus Films."
    )
    romanian = disclosure_sentence(_studio(content_language="ro", studio_display_name="Nexus"))
    assert romanian.startswith("Mențiune:") and romanian.endswith("de Nexus.")
    # A language the studio has no sentence for reads the English one.
    assert disclosure_sentence(_studio(content_language="de")) == AI_DISCLOSURE
    # The Owner's own words for a language win, with the studio's name put in.
    configured = _studio(
        content_language="de",
        studio_display_name="Nexus",
        ai_disclosure_texts={"de": "Hinweis: mit generativer KI erstellt von {studio}."},
    )
    assert disclosure_sentence(configured) == "Hinweis: mit generativer KI erstellt von Nexus."
    footer = publication_footer(None, "https://example.org/ai", None, settings=configured)
    assert footer == "Hinweis: mit generativer KI erstellt von Nexus. https://example.org/ai"


def test_the_studio_brand_is_never_written_in_the_disclosure_code():
    """A buyer's films must not say this Owner's studio made them."""
    import inspect

    from app.providers import youtube

    assert "AMN" not in inspect.getsource(youtube)
    for function in (
        disclosure_sentence,
        publication_footer,
        publishing_services.with_footer,
        publishing_services.create_publication_intent,
    ):
        assert "AMN" not in inspect.getsource(function)
    assert "AMN" not in AI_DISCLOSURE and "AMN" not in DEFAULT_DISCLOSURE


def test_the_daily_footer_reads_the_studio_settings_when_none_are_given(monkeypatch):
    """The day's stage passes only the site and the creator; the language and the name are
    read from the studio's configuration, not hard-coded."""
    monkeypatch.setattr(
        publishing_services,
        "studio_settings",
        lambda: _studio(content_language="ro", studio_display_name="Studio Test"),
    )
    footer = publication_footer(None, None, None)
    assert footer.startswith("Mențiune:") and "de Studio Test." in footer


def test_the_upload_carries_the_channels_category_language_and_audience(
    engine, tmp_path, monkeypatch
):
    channel = _channels(engine)["MAIN_FACTUAL"]
    result = change_publish_policy(
        engine,
        channel["id"],
        _command(youtube_category_id="27", made_for_kids=True, default_language="en-GB"),
    )
    assert result["status"] == "COMMITTED"
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    provider, requests = _youtube(monkeypatch, _two_answers())
    published = publish_media_asset(
        engine,
        media_asset_id=bundle["asset_id"],
        channel_id=channel["id"],
        title="Webb sees the first galaxies",
        description="What the film shows.",
        tags=["webb", "galaxies"],
        privacy_status="private",
        provider=provider,
        footer=publication_footer(engine, None, None, settings=_studio()),
    )
    assert published["status"] == "PUBLISHED"
    sent = _sent(requests)
    snippet, status = sent["snippet"], sent["status"]
    assert snippet["categoryId"] == "27"
    assert snippet["defaultLanguage"] == "en-GB"
    assert snippet["defaultAudioLanguage"] == "en-GB"
    assert status["selfDeclaredMadeForKids"] is True
    assert status["containsSyntheticMedia"] is True
    # No filler tags: the flag above is the label.
    assert snippet["tags"] == ["webb", "galaxies"]
    # What was stored is what was sent.
    assert snippet["description"] == published["description"]
    assert snippet["title"] == published["title"]
    assert len(_disclosure_lines(snippet["description"])) == 1


def test_a_seeded_channel_keeps_todays_category_and_speaks_the_content_language(
    engine, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        publishing_services, "studio_settings", lambda: _studio(content_language="en")
    )
    channels = _channels(engine)
    factual, serial = channels["MAIN_FACTUAL"], channels["OFFICE_SERIAL"]
    assert factual["youtube_category_id"] == "28" and serial["youtube_category_id"] == "28"
    assert factual["made_for_kids"] is False and factual["default_language"] is None
    assert factual["shorts_max_seconds"] == 180 and serial["shorts_max_seconds"] == 180
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    provider, requests = _youtube(monkeypatch, _two_answers())
    publish_media_asset(
        engine,
        media_asset_id=bundle["asset_id"],
        channel_id=factual["id"],
        title="A film",
        description="",
        tags=[],
        privacy_status="private",
        provider=provider,
    )
    sent = _sent(requests)
    assert sent["snippet"]["categoryId"] == "28"
    assert sent["snippet"]["defaultLanguage"] == "en"
    assert sent["snippet"]["defaultAudioLanguage"] == "en"
    assert sent["status"]["selfDeclaredMadeForKids"] is False
    assert "ai generated" not in sent["snippet"].get("tags", [])


def test_the_upload_settings_are_part_of_the_versioned_policy(engine):
    channel = _channels(engine)["OFFICE_SERIAL"]
    result = change_publish_policy(
        engine,
        channel["id"],
        _command(youtube_category_id="24", shorts_max_seconds=150, default_language="ro"),
    )
    assert result["status"] == "COMMITTED"
    assert result["channel"]["policy_version"] == 2
    assert result["channel"]["youtube_category_id"] == "24"
    assert result["channel"]["shorts_max_seconds"] == 150
    event = _events(engine, "publishing.channel_policy_changed")[-1]
    assert set(event.payload["changed"]) == {
        "youtube_category_id",
        "shorts_max_seconds",
        "default_language",
    }
    # The same values again change nothing.
    again = change_publish_policy(
        engine,
        channel["id"],
        _command(expected_version=2, youtube_category_id="24", shorts_max_seconds=150),
    )
    assert again["status"] == "NO_CHANGE"
    # An empty language goes back to the studio's content language.
    cleared = change_publish_policy(
        engine, channel["id"], _command(expected_version=2, default_language="")
    )
    assert cleared["channel"]["default_language"] is None


@pytest.mark.parametrize(
    "fields",
    [
        {"youtube_category_id": "science"},
        {"youtube_category_id": "1234"},
        {"shorts_max_seconds": 181},
        {"shorts_max_seconds": 5},
        {"default_language": "English"},
    ],
)
def test_a_wrong_upload_setting_is_refused_before_it_is_stored(fields):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _command(**fields)


# ------------------------------------------------------------- the Publisher's own answer --
# Audit Q9 / PUB-06: the Publisher was told only "a title under 100 characters, a description
# and up to 15 tags", and an answer one character or one tag over those numbers was refused
# whole (ReviewError), so the film did not go out that day. Her answer is now made safe in
# code, and she is told what a Short's metadata needs.

from app.providers.youtube import tag_budget  # noqa: E402
from test_publication_metadata_per_film import (  # noqa: E402
    PublisherModel,
    _prepare,
    studio,  # noqa: F401 - the fixture
)


def test_the_publishers_rough_answer_is_made_safe_and_she_is_told_the_shorts_rules(
    engine,
    studio,  # noqa: F811
):
    answer = {
        "verdict": "READY",
        "title": "Webb <sees> " + "the earliest galaxies anyone has found " * 5,
        "description": "What the film shows.",
        "tags": [f"webb galaxy fact {n}" for n in range(28)],
        "hold_reasons": [],
    }
    model = PublisherModel(for_episode=answer, for_factual=answer)
    prepared = _prepare(engine, studio, model, "factual")
    assert prepared["verdict"] == "READY"
    assert len(prepared["title"]) <= 100 and "<" not in prepared["title"]
    assert prepared["title"].startswith("Webb ‹sees› the earliest galaxies")
    assert len(prepared["tags"]) <= 15 and tag_budget(prepared["tags"]) <= 500
    prompt = model.prompts[0]
    assert "60 characters" in prompt
    assert "ALL CAPS" in prompt
    assert "hashtags" in prompt
    assert "above the fold" in prompt


def test_migration_0053_gives_existing_channels_todays_settings_and_takes_them_back(tmp_path):
    """A channel written before 0053 keeps what its uploads carried (category 28, not made
    for kids, no language of its own) and the length quality control allowed its films: 60 s
    for factual films, 70 s for the serial's episodes."""
    import sqlite3

    from app.db import create_db_engine, migrate
    from test_migrations_0049 import _downgrade

    path = tmp_path / "studio.db"
    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    migrate(engine)
    _downgrade(engine, "0052_publication_remote_state")
    with sqlite3.connect(path) as raw:
        for name, kind in (("A", "MAIN_FACTUAL"), ("B", "OFFICE_SERIAL")):
            raw.execute(
                "INSERT INTO channel_record (id, channel_name, channel_type, platform, "
                "upload_privacy_default, autonomous_privacy, public_publish_enabled, "
                "publish_delay_minutes, director_may_approve_episodes, policy_version, "
                "status, production_defaults_json, series_rules_json, "
                "allow_production_override, created_at) VALUES (?, ?, ?, 'YOUTUBE', "
                "'private', 'private', 0, 0, 0, 1, 'NOT_CONFIGURED', '{}', '{}', 1, "
                "'2026-10-01T00:00:00+00:00')",
                (name, name, kind),
            )
    migrate(engine)

    def rows() -> dict[str, tuple]:
        with sqlite3.connect(path) as raw:
            return {
                row[0]: row[1:]
                for row in raw.execute(
                    "SELECT channel_type, youtube_category_id, made_for_kids, default_language, "
                    "shorts_max_seconds FROM channel_record"
                )
            }

    # 0053 gave them 60 and 70; 0058 (2026-10-16, the Owner's 180 s) raised both.
    assert rows() == {
        "MAIN_FACTUAL": ("28", 0, None, 180),
        "OFFICE_SERIAL": ("28", 0, None, 180),
    }
    _downgrade(engine, "0052_publication_remote_state")
    with sqlite3.connect(path) as raw:
        columns = {row[1] for row in raw.execute("PRAGMA table_info(channel_record)")}
    assert not {"youtube_category_id", "made_for_kids", "default_language"} & columns
    assert "shorts_max_seconds" not in columns
    migrate(engine)
    engine.dispose()
