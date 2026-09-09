"""Abstract Publishing provider interface."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class UploadResult:
    remote_video_id: str
    remote_url: str
    status: str  # CONFIRMED | UNKNOWN | FAILED
    error_detail: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)
    # True when the result came from a local simulator rather than a real platform.
    # The pipeline must never record a simulated result as a real publication.
    simulated: bool = False


@dataclass
class RemoteVideoStatus:
    remote_video_id: str
    exists: bool
    privacy_status: str | None = None
    upload_status: str | None = None
    rejection_reason: str | None = None


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
        """Query platform for authoritative remote publication state."""

    @abc.abstractmethod
    async def reconcile_upload(
        self, idempotency_key: str, expected_title: str
    ) -> UploadResult | None:
        """Reconcile in-flight or ambiguous uploads to prevent duplicate submissions."""
