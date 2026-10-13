"""A question the platform never answered must not be recorded as a "no".

The defect these cover was real. `YouTubeProvider.get_video_status` returned ``exists=False``
whenever the request raised, and `reconcile_upload` returned ``None`` — meaning "no previous
upload" — for the same reason. A rate limit, an expired token or a dropped connection therefore
became evidence that a video was absent, and the caller's next step is to upload. That is how a
studio publishes a second copy of a video that is already live, and how a publication record
comes to state something nobody established.

Both now raise `RemoteStateUnavailable`, and these tests hold the callers to it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.providers.deterministic_pub import DeterministicPublishingAdapter
from app.providers.publishing_base import RemoteStateUnavailable, UploadResult
from app.providers.youtube import YouTubeProvider
from app.publishing.models import PublicationRecord
from app.publishing.services import (
    create_publication_intent,
    execute_publication,
    list_channels,
    reconcile_publication,
    seed_default_channels,
)
from sqlalchemy.orm import Session
from test_phase6_publishing import _create_verified_asset_bundle


class SilentPlatform(DeterministicPublishingAdapter):
    """A platform that cannot be reached, and an upload counter to prove nothing was sent."""

    def __init__(self) -> None:
        super().__init__()
        self.uploads = 0

    async def get_video_status(self, remote_video_id: str) -> Any:
        raise RemoteStateUnavailable("the channel could not be reached")

    async def reconcile_upload(self, idempotency_key: str, expected_title: str) -> Any:
        raise RemoteStateUnavailable("the channel's uploads could not be searched")

    async def upload_video(self, file_path: Path, **kwargs: Any) -> UploadResult:
        self.uploads += 1
        return await super().upload_video(file_path, **kwargs)


def _publication_in_retry(engine, tmp_path):
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    seed_default_channels(engine)
    channel_id = list_channels(engine)[0]["id"]
    asset_id = bundle["asset_id"]
    publication = create_publication_intent(
        engine,
        channel_id=channel_id,
        media_asset_id=asset_id,
        title="Un videoclip care poate exista deja",
        description="Retry after an ambiguous failure",
        tags=["#test"],
        privacy_status="private",
        idempotency_key=str(uuid4()),
        correlation_id=str(uuid4()),
    )
    with Session(engine) as session, session.begin():
        record = session.get(PublicationRecord, publication["id"])
        record.status = "FAILED_RETRYABLE"
    return publication["id"]


def test_a_retry_does_not_upload_when_duplicates_cannot_be_ruled_out(engine, tmp_path):
    publication_id = _publication_in_retry(engine, tmp_path)
    platform = SilentPlatform()

    result = execute_publication(
        engine,
        publication_id=publication_id,
        publisher=platform,
        correlation_id=str(uuid4()),
    )

    # The whole point: no second upload was attempted.
    assert platform.uploads == 0
    assert result["status"] == "FAILED_RETRYABLE"
    assert result["error_detail"] == (
        "Reîncercarea s-a oprit înainte de încărcare: starea de pe platformă nu a putut fi "
        "citită. Un duplicat nu poate fi exclus."
    )


def test_unreadable_remote_state_stays_unknown_instead_of_becoming_not_found(engine, tmp_path):
    publication_id = _publication_in_retry(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.get(PublicationRecord, publication_id).remote_video_id = "some_remote_id"

    result = reconcile_publication(
        engine,
        publication_id=publication_id,
        provider=SilentPlatform(),
        correlation_id=str(uuid4()),
    )

    assert result["status"] == "REMOTE_UNKNOWN"
    # The old behaviour said "Video not found on remote channel"; nobody had established that.
    assert "nu a fost găsit" not in (result["error_detail"] or "")
    assert result["error_detail"] == (
        "Starea de pe platformă nu a putut fi citită; publicarea rămâne necunoscută, nu absentă."
    )


@pytest.mark.parametrize(
    "call",
    [
        lambda provider: provider.get_video_status("any_id"),
        lambda provider: provider.reconcile_upload("key", "title"),
    ],
)
def test_the_real_provider_refuses_to_answer_without_credentials(call):
    """An unconfigured provider knows nothing about a channel, including whether a
    given video is on it."""
    provider = YouTubeProvider(client_id="", client_secret="", refresh_token="", channel_id="")
    assert not provider.is_configured
    with pytest.raises(RemoteStateUnavailable):
        asyncio.run(call(provider))


def test_the_real_provider_turns_a_failed_request_into_unavailable(monkeypatch):
    """A transport failure is not an answer of "no"."""
    provider = YouTubeProvider(
        client_id="client",
        client_secret="secret",  # pragma: allowlist secret
        refresh_token="refresh",
        channel_id="UC_test",
    )
    monkeypatch.setattr(provider, "_get_access_token", lambda: "token")

    def explode(*args: Any, **kwargs: Any) -> Any:
        raise OSError("connection reset")

    monkeypatch.setattr("app.providers.youtube.urlopen", explode)

    with pytest.raises(RemoteStateUnavailable):
        asyncio.run(provider.get_video_status("video"))
    with pytest.raises(RemoteStateUnavailable):
        asyncio.run(provider.reconcile_upload("key", "title"))


# ------------------------------------------------------------ PUBLISHING_TRUTH (2026-10-02) --
#
# PUB-01: the token refresh ran outside every guard. Google answers 400 invalid_grant once a
# Testing-mode grant is seven days old; the exception escaped `execute_publication` after it
# had committed STARTED, the row stayed STARTED for good, and the gate then refused the film as
# its own duplicate. PUB-03: reconciliation searched all of YouTube (`search.list mine=true`,
# a parameter that does not exist) and adopted any video whose title contained the first 50
# characters. Every request below goes to a faked transport; nothing leaves the machine.

import io  # noqa: E402
import json  # noqa: E402
from urllib.error import HTTPError, URLError  # noqa: E402
from urllib.parse import parse_qs, urlsplit  # noqa: E402

from app.agents.models import AgentMessage  # noqa: E402
from app.models import DomainEvent  # noqa: E402
from app.publishing.models import ChannelRecord  # noqa: E402
from app.publishing.services import evaluate_publishing_gate  # noqa: E402
from app.services import utc_now  # noqa: E402
from app.youtube.models import YouTubeConnection  # noqa: E402
from sqlalchemy import select  # noqa: E402

OWN_CHANNEL = "UC_own_channel_0001"
UPLOADS = "UU_own_channel_0001"


class Answer:
    """A urlopen answer: a JSON body and headers, usable as a context manager."""

    def __init__(self, body: Any, headers: dict[str, str] | None = None) -> None:
        self.body = json.dumps(body).encode()
        self.headers = headers or {}

    def __enter__(self) -> Answer:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def http_error(url: str, code: int, body: dict | None = None) -> HTTPError:
    payload = io.BytesIO(json.dumps(body or {}).encode())
    return HTTPError(url, code, "refused", {}, payload)  # type: ignore[arg-type]


class Transport:
    """The faked Google: each request goes to `answer(req)`; every request is kept."""

    def __init__(self, monkeypatch, answer) -> None:
        self.requests: list[Any] = []
        self.answer = answer
        monkeypatch.setattr("app.providers.youtube.urlopen", self)
        monkeypatch.setattr("app.providers.retry.sleep", lambda seconds: None)

    def __call__(self, req: Any, timeout: float | None = None) -> Any:
        self.requests.append(req)
        outcome = self.answer(req)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def paths(self) -> list[str]:
        return [urlsplit(r.full_url).path for r in self.requests]


def _provider(**overrides: Any) -> YouTubeProvider:
    fields: dict[str, Any] = {
        "client_id": "client",
        "client_secret": "secret",  # pragma: allowlist secret
        "refresh_token": "refresh",
        "channel_id": OWN_CHANNEL,
        "uploads_playlist_id": UPLOADS,
    }
    fields.update(overrides)
    return YouTubeProvider(**fields)


def _token(req: Any) -> Any:
    return Answer({"access_token": "token-1", "expires_in": 3600})


def _video(tmp_path: Path) -> Path:
    video = tmp_path / "film.mp4"
    video.write_bytes(b"x" * 16)
    return video


def test_a_refused_token_refresh_is_a_failed_upload_with_a_reason_in_romanian(
    monkeypatch, tmp_path
):
    def answer(req: Any) -> Any:
        assert "oauth2" in req.full_url, "nothing but the token may be asked"
        return http_error(req.full_url, 400, {"error": "invalid_grant"})

    transport = Transport(monkeypatch, answer)
    result = asyncio.run(
        _provider().upload_video(_video(tmp_path), title="t", description="d", tags=[])
    )

    assert result.status == "FAILED"
    assert result.auth_refused is True
    assert "7 zile" in (result.error_detail or "") and "Testing" in (result.error_detail or "")
    assert "invalid_grant" in (result.error_detail or "")
    assert len(transport.requests) == 1


def test_a_connection_check_google_refuses_with_invalid_grant_says_why_in_romanian(monkeypatch):
    """SELL-07: the Settings check and the reconnect read Google's own words. invalid_grant
    from a Testing-mode app is a seven-day token, and the Owner is told so, not shown JSON."""
    from app.youtube import services as connections  # noqa: PLC0415

    def refuse(req: Any, timeout: float | None = None) -> Any:
        raise http_error(req.full_url, 400, {"error": "invalid_grant", "error_description": "x"})

    monkeypatch.setattr("app.youtube.services.urllib.request.urlopen", refuse)
    with pytest.raises(connections.YouTubeConnectionError) as refused:
        connections._post_form("https://oauth2.googleapis.com/token", {"grant_type": "x"})

    words = str(refused.value)
    assert "invalid_grant" in words
    assert "Reconectează" in words
    assert "Testing" in words and "7 zile" in words
    assert "{" not in words, "Google's JSON is not the Owner's reading"


@pytest.mark.parametrize(
    "fault",
    [
        lambda url: http_error(url, 503),
        lambda url: http_error(url, 429),
        lambda url: URLError("no route"),
        lambda url: http_error(url, 403, {"error": {"errors": [{"reason": "quotaExceeded"}]}}),
    ],
)
def test_a_session_that_could_not_start_is_retryable_because_no_video_exists(
    monkeypatch, tmp_path, fault
):
    def answer(req: Any) -> Any:
        if "oauth2" in req.full_url:
            return _token(req)
        return fault(req.full_url)

    Transport(monkeypatch, answer)
    result = asyncio.run(
        _provider().upload_video(_video(tmp_path), title="t", description="d", tags=[])
    )
    assert result.status == "RETRYABLE"
    assert result.auth_refused is False
    assert result.error_detail and "nu a fost încărcat" in result.error_detail


def _bound_publication(engine, tmp_path, *, status: str = "VALIDATED") -> tuple[str, str]:
    """A publication on Channel A, bound to a CONNECTED account."""
    publication_id = _publication_in_retry(engine, tmp_path)
    connection_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            YouTubeConnection(
                id=connection_id,
                name="Studio account",
                client_id="client-id",
                redirect_uri="http://localhost/callback",
                encrypted_secrets="opaque",  # pragma: allowlist secret
                secret_fields=["client_secret", "refresh_token"],
                status="CONNECTED",
                remote_channel_id=OWN_CHANNEL,
                remote_channel_title="Studio account",
                channel_snapshot={"uploads_playlist_id": UPLOADS},
                created_at=utc_now(),
            )
        )
        record = session.get(PublicationRecord, publication_id)
        record.status = status
        session.get(
            ChannelRecord, record.channel_id
        ).credentials_ref = f"youtube_connection:{connection_id}"
    return publication_id, connection_id


def _owner_letters(engine) -> list[AgentMessage]:
    with Session(engine) as session:
        return [
            row
            for row in session.scalars(
                select(AgentMessage).where(AgentMessage.intent == "ESCALATE")
            )
            if row.to_agent_id is None and (row.body_json or {}).get("to") == "Owner"
        ]


def test_a_token_refusal_during_execution_never_leaves_the_row_started(
    engine, tmp_path, monkeypatch
):
    publication_id, connection_id = _bound_publication(engine, tmp_path)
    Transport(
        monkeypatch,
        lambda req: http_error(req.full_url, 400, {"error": "invalid_grant"}),
    )

    result = execute_publication(engine, _provider(), publication_id, str(uuid4()))

    assert result["status"] == "FAILED_FINAL"
    assert "7 zile" in (result["error_detail"] or "")
    with Session(engine) as session:
        connection = session.get(YouTubeConnection, connection_id)
        assert connection.status == "ERROR"
        assert "Reconectează" in (connection.last_error or "")
        refusal = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "youtube.token_refresh_failed")
        ).one()
        assert refusal.payload["connection_id"] == connection_id
        assert refusal.payload["auth_refused"] is True
        record = session.get(PublicationRecord, publication_id)
        asset_id, channel_id = record.media_asset_id, record.channel_id
    letters = _owner_letters(engine)
    assert len(letters) == 1 and "Reconectează" in (letters[0].body_text or "")
    # The film is not its own duplicate: nothing reached the channel.
    assert evaluate_publishing_gate(engine, asset_id, channel_id)["eligible"] is True


@pytest.mark.parametrize(
    ("raised", "expected"),
    [(URLError("dns"), "FAILED_RETRYABLE"), (RuntimeError("adapter bug"), "FAILED_FINAL")],
)
def test_an_exception_from_the_provider_is_recorded_never_started(
    engine, tmp_path, raised, expected
):
    publication_id, _ = _bound_publication(engine, tmp_path)

    class Exploding(DeterministicPublishingAdapter):
        async def upload_video(self, file_path: Path, **kwargs: Any) -> UploadResult:
            raise raised

    result = execute_publication(engine, Exploding(), publication_id, str(uuid4()))

    assert result["status"] == expected
    with Session(engine) as session:
        assert session.get(PublicationRecord, publication_id).status == expected


def _playlist_item(
    video_id: str, title: str, *, channel: str = OWN_CHANNEL, at: str, privacy: str = "private"
) -> dict:
    return {
        "snippet": {
            "title": title,
            "publishedAt": at,
            "channelId": channel,
            "videoOwnerChannelId": channel,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        },
        "status": {"privacyStatus": privacy},
    }


def _uploads(monkeypatch, items: list[dict]) -> Transport:
    def answer(req: Any) -> Any:
        if "oauth2" in req.full_url:
            return _token(req)
        assert "/playlistItems" in req.full_url, req.full_url
        return Answer({"items": items})

    return Transport(monkeypatch, answer)


TITLE = "How the James Webb telescope sees heat from the first galaxies"


def test_reconciliation_reads_the_channels_own_uploads_playlist(monkeypatch):
    transport = _uploads(monkeypatch, [_playlist_item("own-1", TITLE, at="2026-10-02T08:05:00Z")])

    found = asyncio.run(
        _provider().reconcile_upload("key", TITLE, created_after="2026-10-02T08:00:00+00:00")
    )

    assert found is not None and found.status == "CONFIRMED"
    assert found.remote_video_id == "own-1"
    assert found.privacy_status == "private"
    asked = [r for r in transport.requests if "oauth2" not in r.full_url]
    assert len(asked) == 1
    query = parse_qs(urlsplit(asked[0].full_url).query)
    assert urlsplit(asked[0].full_url).path.endswith("/playlistItems")
    assert query["playlistId"] == [UPLOADS]
    assert "snippet" in query["part"][0] and "status" in query["part"][0]
    assert all("/search" not in path for path in transport.paths())


@pytest.mark.parametrize(
    "item",
    [
        # Another channel's video with the very same title.
        _playlist_item("theirs", TITLE, channel="UC_someone_else", at="2026-10-02T08:05:00Z"),
        # The first fifty characters are not the title.
        _playlist_item("prefix", TITLE[:50] + " (reupload)", at="2026-10-02T08:05:00Z"),
        # An older video of the studio's own with the same title is not this publication.
        _playlist_item("older", TITLE, at="2026-09-01T08:05:00Z"),
    ],
)
def test_reconciliation_never_adopts_a_video_that_is_not_this_publication(monkeypatch, item):
    _uploads(monkeypatch, [item])
    found = asyncio.run(
        _provider().reconcile_upload("key", TITLE, created_after="2026-10-02T08:00:00+00:00")
    )
    assert found is None


def test_reconciliation_finds_the_uploads_playlist_when_none_is_stored(monkeypatch):
    def answer(req: Any) -> Any:
        if "oauth2" in req.full_url:
            return _token(req)
        if "/channels" in req.full_url:
            assert parse_qs(urlsplit(req.full_url).query)["id"] == [OWN_CHANNEL]
            return Answer(
                {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": UPLOADS}}}]}
            )
        assert parse_qs(urlsplit(req.full_url).query)["playlistId"] == [UPLOADS]
        return Answer({"items": [_playlist_item("own-2", TITLE, at="2026-10-02T09:00:00Z")]})

    Transport(monkeypatch, answer)
    found = asyncio.run(
        _provider(uploads_playlist_id=None).reconcile_upload(
            "key", TITLE, created_after="2026-10-02T08:00:00Z"
        )
    )
    assert found is not None and found.remote_video_id == "own-2"


def test_reconciliation_without_a_channel_to_compare_is_unavailable(monkeypatch):
    _uploads(monkeypatch, [])
    with pytest.raises(RemoteStateUnavailable):
        asyncio.run(_provider(channel_id=None).reconcile_upload("key", TITLE))


def test_a_retry_finds_its_own_private_upload_and_uploads_nothing(engine, tmp_path, monkeypatch):
    publication_id, _ = _bound_publication(engine, tmp_path, status="FAILED_RETRYABLE")
    with Session(engine) as session:
        title = session.get(PublicationRecord, publication_id).title
    transport = _uploads(monkeypatch, [_playlist_item("own-3", title, at="2099-01-01T00:00:00Z")])

    result = execute_publication(engine, _provider(), publication_id, str(uuid4()))

    assert result["status"] == "PUBLISHED"
    assert result["remote_video_id"] == "own-3"
    assert not [r for r in transport.requests if "/upload/" in r.full_url]
