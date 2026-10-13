"""Deterministic Publishing Adapter for local testing and CI.

WARNING: this adapter performs no network call and creates no external video. It exists
only so automated tests can exercise the publishing state machine offline. It must never be
substituted for a real provider at runtime: every result it returns is flagged
``simulated=True`` and carries a ``sim:`` identifier with no platform URL, so that no layer
of the system or UI can present it as a real YouTube publication.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.providers.publishing_base import (
    PublishingHealthResult,
    PublishingProvider,
    RemoteVideoStatus,
    UploadResult,
)


class DeterministicPublishingAdapter(PublishingProvider):
    """Zero-paywall deterministic video publisher for tests and local verification."""

    ADAPTER_VERSION = "1.0.0-deterministic"
    IS_SIMULATED = True

    def __init__(self, channel_id: str = "UC_studio_main_sim") -> None:
        self.channel_id = channel_id
        self.channel_title = "AMN-AI - Main Shorts (Simulated)"
        self._published_videos: dict[str, dict[str, Any]] = {}

    async def health_check(self) -> PublishingHealthResult:
        return PublishingHealthResult(
            status="SIMULATED",
            channel_id=self.channel_id,
            channel_title=self.channel_title,
            detail="Simulated publisher: no external platform is contacted.",
        )

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
        if not file_path.is_file():
            return UploadResult(
                remote_video_id="",
                remote_url="",
                status="FAILED",
                error_detail=f"Video file not found at {file_path}",
            )

        file_bytes = file_path.read_bytes()
        if not file_bytes:
            return UploadResult(
                remote_video_id="",
                remote_url="",
                status="FAILED",
                error_detail="Video file is empty (0 bytes)",
            )

        idempotency_key = (extra or {}).get("idempotency_key", "")
        digest = hashlib.sha256(file_bytes[:1024] + idempotency_key.encode("utf-8")).hexdigest()
        # Deliberately not a youtube.com URL: a simulated upload has no public address.
        remote_video_id = f"sim:{digest[:11]}"
        remote_url = ""

        self._published_videos[remote_video_id] = {
            "title": title,
            "description": description,
            "tags": tags,
            "privacy_status": privacy_status,
            "idempotency_key": idempotency_key,
        }

        return UploadResult(
            remote_video_id=remote_video_id,
            remote_url=remote_url,
            status="CONFIRMED",
            simulated=True,
            raw_response={
                "id": remote_video_id,
                "simulated": True,
                "status": {"privacyStatus": privacy_status, "uploadStatus": "simulated"},
            },
        )

    async def get_video_status(self, remote_video_id: str) -> RemoteVideoStatus:
        if remote_video_id in self._published_videos:
            rec = self._published_videos[remote_video_id]
            return RemoteVideoStatus(
                remote_video_id=remote_video_id,
                exists=True,
                privacy_status=rec["privacy_status"],
                upload_status="uploaded",
            )
        return RemoteVideoStatus(remote_video_id=remote_video_id, exists=False)

    async def reconcile_upload(
        self, idempotency_key: str, expected_title: str
    ) -> UploadResult | None:
        for vid_id, data in self._published_videos.items():
            if data.get("idempotency_key") == idempotency_key:
                return UploadResult(
                    remote_video_id=vid_id,
                    remote_url="",
                    status="CONFIRMED",
                    simulated=True,
                )
        return None
