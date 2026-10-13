"""Abstract Publishing provider interface."""

from __future__ import annotations

import abc
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class UploadResult:
    remote_video_id: str
    remote_url: str
    #: CONFIRMED: the platform named the video. UNKNOWN: bytes may have reached it and the
    #: answer was lost; reconcile before anything else. RETRYABLE: nothing was created (the
    #: session never started, or the token could not be refreshed for a reason that passes),
    #: so a later attempt is safe. FAILED: nothing was created and asking again the same way
    #: gets the same answer.
    status: str
    error_detail: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)
    # True when the result came from a local simulator rather than a real platform.
    # The pipeline must never record a simulated result as a real publication.
    simulated: bool = False
    #: The platform refused the account itself (a 4xx from the token endpoint, a 401): the
    #: connection has to be renewed by the Owner before any upload can succeed.
    auth_refused: bool = False
    #: What the platform says the video is, from its own answer (``status.privacyStatus`` and
    #: ``status.uploadStatus``), never what was asked for. None when it did not say.
    privacy_status: str | None = None
    upload_status: str | None = None


class RemoteStateUnavailable(RuntimeError):
    """The platform could not be asked.

    Distinct from an answer of "no". A provider raises this when the question failed — no
    credentials, a network error, a rate limit, an expired token — so that no caller can read
    silence as evidence that a video is absent. Recording "not there" on the strength of a failed
    request is how a studio ends up uploading a second copy of a video that is already live.
    """


@dataclass
class RemoteVideoStatus:
    remote_video_id: str
    exists: bool
    privacy_status: str | None = None
    upload_status: str | None = None
    rejection_reason: str | None = None
    failure_reason: str | None = None


@dataclass
class PublishingHealthResult:
    # HEALTHY | NOT_CONFIGURED | AUTH_REQUIRED | RATE_LIMITED | OFFLINE | ERROR
    status: str
    channel_id: str | None = None
    channel_title: str | None = None
    detail: str = ""


class PublishingProvider(abc.ABC):
    """Base contract for video distribution platforms (YouTube, TikTok, etc.)."""

    ADAPTER_VERSION: str = "1.0.0"
    #: Simulated adapters produce no external state; only for tests and CI.
    IS_SIMULATED: bool = False

    @abc.abstractmethod
    async def health_check(self) -> PublishingHealthResult:
        """Verify API connectivity, credentials validity and quota health."""

    @abc.abstractmethod
    async def upload_video(
        self,
        file_path: Path,
        *,
        title: str,
        description: str,
        tags: list[str],
        privacy_status: str = "private",
        extra: dict[str, Any] | None = None,
    ) -> UploadResult:
        """Upload video file with metadata. Never pretend upload succeeded if failed."""

    @abc.abstractmethod
    async def get_video_status(self, remote_video_id: str) -> RemoteVideoStatus:
        """Query platform for authoritative remote publication state.

        Raises `RemoteStateUnavailable` when the platform could not be asked. Returning
        ``exists=False`` is a statement of fact and must be backed by an answer.
        """

    @abc.abstractmethod
    async def reconcile_upload(
        self, idempotency_key: str, expected_title: str
    ) -> UploadResult | None:
        """Reconcile in-flight or ambiguous uploads to prevent duplicate submissions.

        ``None`` means the platform was asked and holds no such upload. When it could not be
        asked, raise `RemoteStateUnavailable`: the caller's next step is to upload, and it must
        not take that step on the strength of a question that was never answered.

        An adapter that can use them also takes two keyword-only facts (`YouTubeProvider`):
        ``created_after``, when the publication was written (an upload of it cannot be older),
        and ``channel_id``, the remote channel it was meant for: a video of the same title made
        earlier, or on someone else's channel, is not this publication. Callers go through
        `ask_reconcile`, which passes them only to an adapter that takes them.
        """


def ask_reconcile(
    provider: PublishingProvider,
    idempotency_key: str,
    expected_title: str,
    *,
    created_after: str | None = None,
    channel_id: str | None = None,
) -> Any:
    """The coroutine of `provider.reconcile_upload`, with the two facts it can take.

    Adapters (and test stand-ins) written before 2026-10-02 take two arguments; they are asked
    with two. Judged on the signature, never by catching a TypeError, which could come from
    inside the adapter.
    """
    method = provider.reconcile_upload
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        parameters = {}  # type: ignore[assignment]
    accepts_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    extra: dict[str, Any] = {}
    if accepts_any or "created_after" in parameters:
        extra["created_after"] = created_after
    if accepts_any or "channel_id" in parameters:
        extra["channel_id"] = channel_id
    return method(idempotency_key, expected_title, **extra)
