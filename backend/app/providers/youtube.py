"""Official YouTube Data API v3 publishing adapter.

Follows Section 25 of Master Prompt & 22_PROVIDER_INTEGRATION_CONTRACTS.md:
- Official Google OAuth2 token exchange and refresh.
- Resumable video upload (videos.insert).
- AI / synthetic content disclosure flag.
- Authoritative remote status queries and reconciliation before retry.
- Never fabricates external state; returns NOT_CONFIGURED if credentials missing.
- Bounded retries on 429, 5xx and unopened connections (`app.providers.retry`); a chunk is
  re-sent with its Content-Range, so a repeat never makes a second video.
- A scheduled release is a private upload with ``status.publishAt`` (videos.insert), and a
  visibility change is ``videos.update`` on the status part, re-declaring the synthetic
  media flag because an update reverts what it does not mention.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from app.providers.publishing_base import (
    PublishingHealthResult,
    PublishingProvider,
    RemoteStateUnavailable,
    RemoteVideoStatus,
    UploadResult,
)
from app.providers.retry import call_with_retries

logger = logging.getLogger("studio.publishing.youtube")

ADAPTER_VERSION = "1.1.0"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024

SYNTHETIC_DISCLOSURE = (
    "Disclosure: this video was produced with generative AI by an autonomous studio pipeline."
)

#: The values YouTube's status.privacyStatus takes. Anything else is refused before a request
#: is made: the platform would answer 400, and a 400 is a wrong request, not a wrong moment.
PRIVACY_STATUSES = ("private", "unlisted", "public")


def rfc3339(value: datetime | str) -> str:
    """The form `status.publishAt` takes: UTC, whole seconds, a trailing Z.

    A string is checked, not trusted: an unreadable timestamp is a wrong request and is
    raised here as `ValueError` rather than sent for YouTube to refuse.
    """
    if isinstance(value, str):
        text = value.strip()
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        value = parsed
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open(req: Request, *, timeout: float) -> Any:
    """`urlopen` with the studio's retry policy (429, 5xx, a connection that never opened).

    Every request here may be repeated: a token refresh yields the same token, the session
    initiation creates no video, a chunk carries its Content-Range so Google keeps one copy,
    and the reads are reads. Google's 308 checkpoint is not an error to the policy and reaches
    the uploader untouched. `urlopen` is looked up at call time so tests keep replacing it.
    """
    return call_with_retries(
        lambda: urlopen(req, timeout=timeout),
        repeatable=True,
        what=f"youtube {req.get_method()} {urlsplit(req.full_url).path}",
    )


def youtube_provider_from_settings(settings: Any) -> YouTubeProvider:
    """Build the official adapter from application Settings.

    Returns an adapter that reports ``is_configured is False`` when credentials are absent;
    callers must refuse to publish rather than substituting a simulated adapter.
    """
    secret = getattr(settings, "youtube_client_secret", None)
    refresh = getattr(settings, "youtube_refresh_token", None)
    return YouTubeProvider(
        client_id=getattr(settings, "youtube_client_id", None),
        client_secret=secret.get_secret_value() if secret is not None else None,
        refresh_token=refresh.get_secret_value() if refresh is not None else None,
        channel_id=getattr(settings, "youtube_channel_id", None),
    )


class YouTubeProvider(PublishingProvider):
    """Official YouTube Data API v3 adapter."""

    ADAPTER_VERSION = ADAPTER_VERSION

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        channel_id: str | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.channel_id = channel_id
        self._access_token: str | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def _get_access_token(self) -> str:
        if not self.is_configured:
            raise ValueError("YouTube OAuth credentials not configured")
        data = urlencode(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")
        req = Request(GOOGLE_TOKEN_URL, data=data, method="POST")
        try:
            with _open(req, timeout=15) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                token = res_data.get("access_token")
                if not token:
                    raise ValueError("Failed to obtain access_token from Google OAuth")
                self._access_token = token
                return token
        except (URLError, HTTPError) as exc:
            logger.error("youtube_token_refresh_failed", extra={"error": str(exc)})
            raise

    async def health_check(self) -> PublishingHealthResult:
        if not self.is_configured:
            return PublishingHealthResult(
                status="NOT_CONFIGURED",
                detail=(
                    "YouTube OAuth credentials (client_id, secret, refresh_token) "
                    "not configured in environment."
                ),
            )
        try:
            token = self._get_access_token()
            url = f"{YOUTUBE_API_BASE}/channels?part=snippet&mine=true"
            req = Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
            with _open(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                if items:
                    ch = items[0]
                    return PublishingHealthResult(
                        status="HEALTHY",
                        channel_id=ch.get("id"),
                        channel_title=ch.get("snippet", {}).get("title"),
                    )
                return PublishingHealthResult(
                    status="AUTH_REQUIRED", detail="No channel associated with account"
                )
        except Exception as exc:  # noqa: BLE001
            return PublishingHealthResult(status="ERROR", detail=str(exc))

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
        if not self.is_configured:
            return UploadResult(
                remote_video_id="",
                remote_url="",
                status="FAILED",
                error_detail="YouTube OAuth credentials not configured",
            )
        if not file_path.is_file():
            return UploadResult(
                remote_video_id="",
                remote_url="",
                status="FAILED",
                error_detail=f"File {file_path} does not exist on disk",
            )

        # A scheduled release: YouTube takes a publishAt only on a private upload and makes
        # the video public at that time. The pair comes from `resolve_publish_visibility`;
        # the adapter checks the form of the timestamp and refuses to send a bad one.
        publish_at = (extra or {}).get("publish_at")
        if publish_at:
            try:
                publish_at = rfc3339(publish_at)
            except (TypeError, ValueError):
                return UploadResult(
                    remote_video_id="",
                    remote_url="",
                    status="FAILED",
                    error_detail=f"publish_at is not an RFC 3339 timestamp: {publish_at!r}",
                )
            if privacy_status != "private":
                return UploadResult(
                    remote_video_id="",
                    remote_url="",
                    status="FAILED",
                    error_detail=(
                        "A scheduled release must be uploaded private; YouTube refuses a "
                        f"publishAt on a {privacy_status} upload."
                    ),
                )

        token = self._get_access_token()
        # Synthetic/altered content disclosure is mandatory for AI-generated uploads.
        # It is declared both in the API status block and in human-readable description text,
        # because the API field alone is not visible to viewers.
        disclosed_description = description[:4800]
        if SYNTHETIC_DISCLOSURE not in disclosed_description:
            disclosed_description = f"{disclosed_description}\n\n{SYNTHETIC_DISCLOSURE}"
        disclosure_tags = list(dict.fromkeys([*tags, "ai generated", "synthetic media"]))

        status: dict[str, Any] = {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        }
        if publish_at:
            status["publishAt"] = publish_at
        metadata = {
            "snippet": {
                "title": title[:100],
                "description": disclosed_description[:5000],
                "tags": disclosure_tags[:50],
                "categoryId": "28",  # Science & Technology
            },
            "status": status,
        }

        # 1. Initiate resumable upload session
        init_url = f"{YOUTUBE_UPLOAD_URL}?uploadType=resumable&part=snippet,status"
        init_body = json.dumps(metadata).encode("utf-8")
        init_req = Request(
            init_url,
            data=init_body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(file_path.stat().st_size),
            },
            method="POST",
        )

        try:
            with _open(init_req, timeout=30) as resp:
                upload_uri = resp.headers.get("Location")
                if not upload_uri:
                    return UploadResult(
                        remote_video_id="",
                        remote_url="",
                        status="FAILED",
                        error_detail="Google upload server did not return Location header",
                    )
        except Exception as exc:  # noqa: BLE001
            return UploadResult(
                remote_video_id="", remote_url="", status="FAILED", error_detail=str(exc)
            )

        # 2. Upload the bytes in resumable chunks. Google answers 308 for each accepted
        #    chunk and 200/201 with the video resource once the last chunk lands.
        total = file_path.stat().st_size
        offset = 0
        try:
            with file_path.open("rb") as handle:
                while offset < total:
                    chunk = handle.read(UPLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    end = offset + len(chunk) - 1
                    chunk_req = Request(
                        upload_uri,
                        data=chunk,
                        headers={
                            "Content-Type": "video/mp4",
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {offset}-{end}/{total}",
                        },
                        method="PUT",
                    )
                    try:
                        with _open(chunk_req, timeout=300) as resp:
                            body = resp.read().decode("utf-8")
                            res_body = json.loads(body) if body.strip() else {}
                    except HTTPError as http_exc:
                        if http_exc.code != 308:
                            raise
                        # 308 Resume Incomplete: continue from the byte range Google confirmed.
                        rng = http_exc.headers.get("Range")
                        offset = int(rng.split("-")[-1]) + 1 if rng else end + 1
                        handle.seek(offset)
                        continue
                    offset = end + 1

            video_id = res_body.get("id")
            if not video_id:
                return UploadResult(
                    remote_video_id="",
                    remote_url="",
                    status="UNKNOWN",
                    error_detail="Upload finished but video ID missing in response",
                )
            return UploadResult(
                remote_video_id=video_id,
                remote_url=f"https://youtube.com/shorts/{video_id}",
                status="CONFIRMED",
                raw_response=res_body,
            )
        except Exception as exc:  # noqa: BLE001
            # UNKNOWN, not FAILED: the video may exist remotely. Reconcile before any retry.
            return UploadResult(
                remote_video_id="",
                remote_url="",
                status="UNKNOWN",
                error_detail=f"Upload stream interrupted: {exc}",
            )

    async def get_video_status(self, remote_video_id: str) -> RemoteVideoStatus:
        if not self.is_configured:
            raise RemoteStateUnavailable(
                "No YouTube credentials are configured, so the channel cannot be asked "
                "whether this video exists."
            )
        token = self._get_access_token()
        url = f"{YOUTUBE_API_BASE}/videos?part=status&id={remote_video_id}"
        req = Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
        try:
            with _open(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                if not items:
                    return RemoteVideoStatus(remote_video_id=remote_video_id, exists=False)
                st = items[0].get("status", {})
                return RemoteVideoStatus(
                    remote_video_id=remote_video_id,
                    exists=True,
                    privacy_status=st.get("privacyStatus"),
                    upload_status=st.get("uploadStatus"),
                    rejection_reason=st.get("rejectionReason"),
                )
        except Exception as exc:  # noqa: BLE001
            # An empty `items` list above is YouTube saying no. This is YouTube saying nothing.
            raise RemoteStateUnavailable(f"YouTube could not be queried: {exc}") from None

    async def update_visibility(
        self, remote_video_id: str, privacy_status: str
    ) -> RemoteVideoStatus:
        """Change a video's visibility with videos.update on the status part.

        The status part is replaced whole: a property the request does not mention reverts
        to its default, so the synthetic-media declaration and the made-for-kids answer are
        sent again with the new privacy. The answer is the video resource; an answer that does
        not name the video is YouTube saying nothing, raised as `RemoteStateUnavailable`
        like every other unanswered question here, and a 404 is YouTube saying the video is
        not there. Repeatable: sending the same status twice leaves the same status.
        """
        if privacy_status not in PRIVACY_STATUSES:
            raise ValueError(
                f"privacy_status must be one of {PRIVACY_STATUSES}, not {privacy_status!r}"
            )
        if not self.is_configured:
            raise RemoteStateUnavailable(
                "No YouTube credentials are configured, so the video's visibility cannot "
                "be changed."
            )
        body = json.dumps(
            {
                "id": remote_video_id,
                "status": {
                    "privacyStatus": privacy_status,
                    "selfDeclaredMadeForKids": False,
                    "containsSyntheticMedia": True,
                },
            }
        ).encode("utf-8")
        try:
            token = self._get_access_token()
            req = Request(
                f"{YOUTUBE_API_BASE}/videos?{urlencode({'part': 'status'})}",
                data=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                method="PUT",
            )
            with _open(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 404:
                return RemoteVideoStatus(remote_video_id=remote_video_id, exists=False)
            raise RemoteStateUnavailable(
                f"YouTube refused the visibility change (HTTP {exc.code})."
            ) from None
        except Exception as exc:  # noqa: BLE001
            raise RemoteStateUnavailable(
                f"YouTube could not be asked to change the visibility: {exc}"
            ) from None
        if not isinstance(data, dict) or data.get("id") != remote_video_id:
            raise RemoteStateUnavailable(
                "YouTube answered the visibility change without naming the video; whether "
                "it changed is unknown."
            )
        st = data.get("status", {})
        return RemoteVideoStatus(
            remote_video_id=remote_video_id,
            exists=True,
            privacy_status=st.get("privacyStatus"),
            upload_status=st.get("uploadStatus"),
            rejection_reason=st.get("rejectionReason"),
        )

    async def reconcile_upload(
        self, idempotency_key: str, expected_title: str
    ) -> UploadResult | None:
        """Search channel uploads by title to prevent duplicate submission."""
        if not self.is_configured:
            raise RemoteStateUnavailable(
                "No YouTube credentials are configured, so a previous upload cannot be ruled out."
            )
        token = self._get_access_token()
        params = urlencode(
            {"part": "snippet", "mine": "true", "type": "video", "q": expected_title[:50]}
        )
        url = f"{YOUTUBE_API_BASE}/search?{params}"
        req = Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
        try:
            with _open(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for item in data.get("items", []):
                    title = item.get("snippet", {}).get("title", "")
                    if expected_title[:50].lower() in title.lower():
                        vid_id = item.get("id", {}).get("videoId")
                        if vid_id:
                            return UploadResult(
                                remote_video_id=vid_id,
                                remote_url=f"https://youtube.com/shorts/{vid_id}",
                                status="CONFIRMED",
                            )
        except Exception as exc:  # noqa: BLE001
            raise RemoteStateUnavailable(
                f"The channel's uploads could not be searched: {exc}"
            ) from None
        # Asked and answered: nothing on the channel matches this title.
        return None
