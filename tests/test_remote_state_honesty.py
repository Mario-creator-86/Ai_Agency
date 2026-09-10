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
    assert "duplicate cannot be ruled out" in result["error_detail"].lower()


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
    assert "not found" not in (result["error_detail"] or "").lower()
    assert "could not be read" in result["error_detail"].lower()


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
