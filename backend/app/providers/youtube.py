"""Official YouTube Data API v3 publishing adapter.

Follows Section 25 of Master Prompt & 22_PROVIDER_INTEGRATION_CONTRACTS.md:
- Official Google OAuth2 token exchange and refresh.
- Resumable video upload (videos.insert).
- AI / synthetic content disclosure flag.
- Authoritative remote status queries and reconciliation before retry.
- Never fabricates external state; returns NOT_CONFIGURED if credentials missing.
- Every way an upload ends is an `UploadResult` (2026-10-02, PUB-01): a token Google refuses
  is FAILED with ``auth_refused``, a session that never started is RETRYABLE (no video
  exists), bytes that may have landed are UNKNOWN. Nothing raises past the adapter.
- The insert answer's own ``status.privacyStatus`` / ``uploadStatus`` are returned (PUB-05): an
  unaudited API project's uploads are kept private by Google whatever was asked for.
- Reconciliation reads the channel's own uploads playlist (``playlistItems.list``), matching the
  exact title, the channel and the time (PUB-03); ``search.list`` has no ``mine`` parameter.
- Bounded retries on 429, 5xx and unopened connections (`app.providers.retry`); a chunk is
  re-sent with its Content-Range, so a repeat never makes a second video.
- A scheduled release is a private upload with ``status.publishAt`` (videos.insert), and a
  visibility change is ``videos.update`` on the status part, re-declaring the synthetic
  media flag because an update reverts what it does not mention.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import UTC, datetime, timedelta
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
from app.providers.retry import SAFE_TO_RESEND_STATUSES, call_with_retries

logger = logging.getLogger("studio.publishing.youtube")

ADAPTER_VERSION = "1.2.0"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024

#: YouTube's own limits for videos.insert (developers.google.com/youtube/v3/docs/videos, read
#: 2026-10-02): a title of at most 100 characters without '<' or '>'; a description of at most
#: 5000 *bytes*; tags of at most 500 characters in all, the commas between them counting and a
#: tag holding a space counting its quotation marks. Over any of them YouTube answers 400,
#: which after a paid film is a publication that failed for good (audit PUB-06).
TITLE_LIMIT = 100
DESCRIPTION_LIMIT_BYTES = 5000
TAGS_LIMIT = 500
#: What a title becomes when neither the Publisher nor the script gave one: never empty.
UNTITLED = "Video"
#: The category every upload carried before channels had their own (Science & Technology).
DEFAULT_CATEGORY_ID = "28"

#: The disclosure this adapter writes only when a description reaches it with none at all (a
#: direct call). On every studio road the studio's footer (publishing.services) is the one
#: source, and the adapter never writes a second line beside it (audit PUB-07). No studio is
#: named here: a buyer's films must not say this Owner's studio made them.
DEFAULT_DISCLOSURE = "Disclosure: this video was produced with generative AI."
#: Where the studio's own block begins in a description: a line starting with a known
#: disclosure. English is known here; publishing.services registers the other languages and
#: the Owner's own sentences (`register_footer_marker`).
FOOTER_MARKER = "Disclosure: this video was produced with generative AI"
_FOOTER_MARKERS: set[str] = {FOOTER_MARKER}

_CUT_MARK = "…"
_TRIM_TAIL = " ,;:-–—|/"
#: A cut moves back to the last space only when one is this close; a body with no space for
#: that long (a URL, a run of hashtags) is cut where the limit falls.
_WORD_SEARCH = 80


def register_footer_marker(marker: str) -> None:
    """Make a disclosure's opening words known as the start of the studio's block."""
    text = " ".join(str(marker or "").split())
    if len(text) >= 8:
        _FOOTER_MARKERS.add(text)


def footer_start(description: str) -> int:
    """Where the studio's block begins: the first line that opens with a known disclosure, or
    -1 when the description has none."""
    text = description or ""
    found = -1
    for marker in tuple(_FOOTER_MARKERS):
        for match in re.finditer(re.escape(marker), text):
            at = match.start()
            if at == 0 or text[at - 1] == "\n":
                if found < 0 or at < found:
                    found = at
                break
    return found


def _safe_text(text: Any) -> str:
    """No '<' or '>' (YouTube refuses them) and no control characters but line breaks."""
    value = str(text or "").replace("\r\n", "\n").replace("<", "‹").replace(">", "›")
    kept = (ch for ch in value if ch in "\n\t" or unicodedata.category(ch) != "Cc")
    return "".join(kept).replace("\t", " ")


def _cut_at_word(text: str, room: int) -> str:
    """``text`` shortened to fit ``room`` characters with the cut mark, at a word when one is
    near, never inside a character."""
    if room <= len(_CUT_MARK):
        return ""
    head = text[: room - len(_CUT_MARK)]
    rest = text[len(head) :]
    if rest and not rest[0].isspace():
        space = max(head.rfind(" "), head.rfind("\n"))
        if space > 0 and len(head) - space <= _WORD_SEARCH:
            head = head[:space]
    head = head.rstrip().rstrip(_TRIM_TAIL)
    return f"{head}{_CUT_MARK}" if head else ""


def fit_bytes(text: str, limit: int) -> str:
    """``text`` within ``limit`` UTF-8 bytes, cut at a word and marked when it had to be."""
    if len(text.encode("utf-8")) <= limit:
        return text
    room = limit - len(_CUT_MARK.encode("utf-8"))
    if room <= 0:
        return ""
    head = text.encode("utf-8")[:room].decode("utf-8", errors="ignore")
    # The character-level cut on the decoded head: its length in characters is what fits.
    return _cut_at_word(text, len(head) + len(_CUT_MARK))


def tag_budget(tags: list[str]) -> int:
    """What YouTube counts against its 500: each tag, two quotes for a tag with a space, and
    a comma between tags."""
    return sum(len(t) + 2 if " " in t else len(t) for t in tags) + max(0, len(tags) - 1)


def _safe_title(title: str, fallback: str) -> str:
    for candidate in (title, fallback):
        text = " ".join(_safe_text(candidate).split())
        if text:
            return text if len(text) <= TITLE_LIMIT else _cut_at_word(text, TITLE_LIMIT)
    return UNTITLED


def _safe_tags(tags: list[str] | None) -> list[str]:
    kept: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        tag = " ".join(_safe_text(raw).replace(",", " ").split())
        key = tag.casefold()
        if not tag or key in seen:
            continue
        if tag_budget([*kept, tag]) > TAGS_LIMIT:
            continue
        seen.add(key)
        kept.append(tag)
    return kept


def _safe_description(description: str, *, disclose: bool) -> str:
    text = _safe_text(description).strip()
    if disclose and footer_start(text) < 0:
        text = f"{text}\n\n{DEFAULT_DISCLOSURE}" if text else DEFAULT_DISCLOSURE
    if len(text.encode("utf-8")) <= DESCRIPTION_LIMIT_BYTES:
        return text
    cut = footer_start(text)
    head, foot = (text[:cut].rstrip(), text[cut:]) if cut >= 0 else (text, "")
    foot = fit_bytes(foot, DESCRIPTION_LIMIT_BYTES)
    room = DESCRIPTION_LIMIT_BYTES - len(foot.encode("utf-8")) - (2 if foot else 0)
    head = fit_bytes(head, room) if room > 0 else ""
    return "\n\n".join(part for part in (head, foot) if part)


def youtube_safe_metadata(
    title: str,
    description: str,
    tags: list[str] | None,
    *,
    fallback_title: str = "",
    disclose: bool = False,
) -> tuple[str, str, list[str]]:
    """The title, description and tags as YouTube accepts them (audit PUB-06).

    '<' and '>' become '‹' and '›'; the title is one line of at most 100 characters, cut at
    a word, and never empty (``fallback_title``, then "Video"); the description fits 5000
    UTF-8 bytes with the studio's block (`footer_start`) kept whole and the text above it
    cut at a word; tags are cleaned of commas, deduplicated and dropped, in order, until
    they fit the 500-character budget. ``disclose`` adds `DEFAULT_DISCLOSURE` to a
    description that carries no known disclosure. Making metadata safe twice changes
    nothing, so what the studio stores is what the adapter sends.
    """
    return (
        _safe_title(title, fallback_title),
        _safe_description(description, disclose=disclose),
        _safe_tags(tags),
    )


#: Google's own words when the account itself is refused at the token endpoint; anything else
#: from it (a 5xx, a 429, a dropped connection) is a moment, not the account.
AUTH_REFUSED_STATUSES = frozenset({400, 401, 403})

#: The reasons YouTube gives for a 403 that is a quota or a rate, not the account: they pass
#: with time (the daily quota resets at midnight Pacific), and a session that never started
#: created no video, so asking again later is safe.
QUOTA_REASONS = frozenset(
    {"quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded", "uploadLimitExceeded"}
)

#: How far back of the publication's own creation an upload may be stamped and still be it:
#: Google's clock and the studio's are not the same clock.
RECONCILE_CLOCK_SKEW = timedelta(minutes=2)
#: Pages of the uploads playlist read before the question is called unanswerable (50 each,
#: newest first; 1 quota unit a page).
RECONCILE_MAX_PAGES = 4

#: What the Owner reads when Google refuses the account. SELL-07: a Google app left in
#: "Testing" gives refresh tokens that expire after seven days, then answers invalid_grant.
AUTH_REFUSED_WORDS = (
    "Google a refuzat reînnoirea accesului la YouTube ({answer}): conexiunea a expirat sau a "
    "fost revocată. Reconectează contul YouTube. Dacă aplicația Google OAuth este în modul "
    "Testing, Google face tokenurile să expire după 7 zile: trece ecranul de consimțământ în "
    "„In production” ca să nu se mai întâmple."
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


def _google_word(exc: HTTPError) -> str:
    """Google's own short word for a refusal («invalid_grant», «quotaExceeded»), never more:
    the body may quote the request, and nothing of it but the code is kept."""
    try:
        raw = exc.read()
        body = json.loads(raw.decode("utf-8", errors="replace")) if raw else {}
    except (OSError, ValueError, AttributeError):
        return ""
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if isinstance(error, str):
        return error[:60]
    if isinstance(error, dict):
        for item in error.get("errors") or []:
            if isinstance(item, dict) and item.get("reason"):
                return str(item["reason"])[:60]
        return str(error.get("status") or "")[:60]
    return ""


def _moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip()
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _same_title(left: str, right: str) -> bool:
    """The title as YouTube keeps it, compared whole: as `youtube_safe_metadata` sends it
    since 2026-10-02, or, for an upload made before, its first 100 characters with the
    spacing folded."""
    if _safe_title(str(left), "") == _safe_title(str(right), ""):
        return True
    return " ".join(str(left)[:100].split()) == " ".join(str(right)[:100].split())


def _not_uploaded(detail: str, *, status: str, auth_refused: bool = False) -> UploadResult:
    return UploadResult(
        remote_video_id="",
        remote_url="",
        status=status,
        error_detail=detail,
        auth_refused=auth_refused,
    )


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
        uploads_playlist_id: str | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.channel_id = channel_id
        #: The channel's uploads playlist (channels.list contentDetails.relatedPlaylists),
        #: read at connection time; asked for once when it was not stored.
        self.uploads_playlist_id = uploads_playlist_id
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
            return _not_uploaded(
                "Contul YouTube nu are acreditările OAuth complete; nimic nu a fost încărcat.",
                status="FAILED",
            )
        if not file_path.is_file():
            return _not_uploaded(
                f"Fișierul filmului lipsește de pe disc ({file_path.name}); nimic nu a fost "
                "încărcat.",
                status="FAILED",
            )

        # A scheduled release: YouTube takes a publishAt only on a private upload and makes
        # the video public at that time. The pair comes from `resolve_publish_visibility`;
        # the adapter checks the form of the timestamp and refuses to send a bad one.
        publish_at = (extra or {}).get("publish_at")
        if publish_at:
            try:
                publish_at = rfc3339(publish_at)
            except (TypeError, ValueError):
                return _not_uploaded(
                    f"Data lansării programate nu este o dată RFC 3339: {publish_at!r}; "
                    "nimic nu a fost încărcat.",
                    status="FAILED",
                )
            if privacy_status != "private":
                return _not_uploaded(
                    "O lansare programată se încarcă privat; YouTube refuză o dată de lansare "
                    f"pe o încărcare „{privacy_status}”. Nimic nu a fost încărcat.",
                    status="FAILED",
                )

        # The token first, inside the guard: Google's 400 invalid_grant (a revoked grant, or
        # a Testing-mode grant seven days old) used to escape from here after the caller had
        # written STARTED, and the row stayed STARTED for good.
        refused = self._token_or_refusal()
        if isinstance(refused, UploadResult):
            return refused
        token = refused
        # Synthetic/altered content disclosure is mandatory for AI-generated uploads. The API's
        # containsSyntheticMedia is the label; the description carries one human-readable
        # line, the studio's own (``extra["disclosed"]``), or this adapter's when a direct
        # call brought none. No filler tags: "ai generated" took tag budget for no reach.
        settings = extra or {}
        title, description, tags = youtube_safe_metadata(
            title, description, tags, disclose=not settings.get("disclosed")
        )
        category = str(settings.get("category_id") or DEFAULT_CATEGORY_ID)
        if not re.fullmatch(r"\d{1,3}", category):
            category = DEFAULT_CATEGORY_ID
        language = str(settings.get("default_language") or "").strip()

        status: dict[str, Any] = {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": bool(settings.get("made_for_kids", False)),
            "containsSyntheticMedia": True,
        }
        if publish_at:
            status["publishAt"] = publish_at
        snippet: dict[str, Any] = {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category,
        }
        if re.fullmatch(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})?", language):
            # What the title and description are written in, and what the film says.
            snippet["defaultLanguage"] = language
            snippet["defaultAudioLanguage"] = language
        metadata = {"snippet": snippet, "status": status}

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

        # The session creates no video: whatever goes wrong here, nothing is on the channel.
        # A moment (429, 5xx, a quota, the network) is RETRYABLE; Google refusing the token
        # is the account; any other refusal is the request and would be refused again.
        try:
            with _open(init_req, timeout=30) as resp:
                upload_uri = resp.headers.get("Location")
                if not upload_uri:
                    return _not_uploaded(
                        "Serverul de încărcare Google nu a dat adresa sesiunii; filmul nu a "
                        "fost încărcat, se reîncearcă.",
                        status="RETRYABLE",
                    )
        except HTTPError as exc:
            word = _google_word(exc)
            answer = " ".join(part for part in (f"HTTP {exc.code}", word) if part)
            if exc.code == 401:
                return _not_uploaded(
                    AUTH_REFUSED_WORDS.format(answer=answer), status="FAILED", auth_refused=True
                )
            if exc.code in SAFE_TO_RESEND_STATUSES or exc.code >= 500 or word in QUOTA_REASONS:
                return _not_uploaded(
                    f"YouTube nu a deschis sesiunea de încărcare acum ({answer}); filmul nu a "
                    "fost încărcat, se reîncearcă.",
                    status="RETRYABLE",
                )
            return _not_uploaded(
                f"YouTube a refuzat sesiunea de încărcare ({answer}); filmul nu a fost încărcat.",
                status="FAILED",
            )
        except Exception as exc:  # noqa: BLE001 - nothing was created; every fault is a moment
            return _not_uploaded(
                f"YouTube nu a putut fi contactat pentru încărcare ({type(exc).__name__}); "
                "filmul nu a fost încărcat, se reîncearcă.",
                status="RETRYABLE",
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
                    error_detail=(
                        "Încărcarea s-a terminat, dar YouTube nu a numit videoclipul; se verifică "
                        "pe canal înainte de orice reîncercare."
                    ),
                )
            # What YouTube made of it, in its own words: an unaudited API project's upload
            # comes back private whatever was asked for (PUB-05).
            remote_status = res_body.get("status") if isinstance(res_body, dict) else None
            remote_status = remote_status if isinstance(remote_status, dict) else {}
            return UploadResult(
                remote_video_id=video_id,
                remote_url=f"https://youtube.com/shorts/{video_id}",
                status="CONFIRMED",
                raw_response=res_body,
                privacy_status=remote_status.get("privacyStatus"),
                upload_status=remote_status.get("uploadStatus"),
            )
        except Exception as exc:  # noqa: BLE001
            # UNKNOWN, not FAILED: the video may exist remotely. Reconcile before any retry.
            return UploadResult(
                remote_video_id="",
                remote_url="",
                status="UNKNOWN",
                error_detail=(
                    f"Încărcarea s-a întrerupt după ce a început ({type(exc).__name__}); "
                    "videoclipul poate exista pe canal, se verifică înainte de orice reîncercare."
                ),
            )

    def _token_or_refusal(self) -> str | UploadResult:
        """A fresh access token, or the upload's result when Google would not give one."""
        try:
            return self._get_access_token()
        except HTTPError as exc:
            word = _google_word(exc)
            answer = " ".join(part for part in (f"HTTP {exc.code}", word) if part)
            if exc.code in AUTH_REFUSED_STATUSES:
                return _not_uploaded(
                    AUTH_REFUSED_WORDS.format(answer=answer), status="FAILED", auth_refused=True
                )
            return _not_uploaded(
                f"Google nu a reînnoit accesul acum ({answer}); filmul nu a fost încărcat, se "
                "reîncearcă.",
                status="RETRYABLE",
            )
        except ValueError:
            return _not_uploaded(
                "Google nu a dat un token de acces pentru această conexiune; filmul nu a fost "
                "încărcat. Reconectează contul YouTube.",
                status="FAILED",
                auth_refused=True,
            )
        except Exception as exc:  # noqa: BLE001 - the network: nothing was sent
            return _not_uploaded(
                f"Google nu a putut fi contactat pentru token ({type(exc).__name__}); filmul nu "
                "a fost încărcat, se reîncearcă.",
                status="RETRYABLE",
            )

    async def get_video_status(self, remote_video_id: str) -> RemoteVideoStatus:
        if not self.is_configured:
            raise RemoteStateUnavailable(
                "No YouTube credentials are configured, so the channel cannot be asked "
                "whether this video exists."
            )
        try:
            token = self._get_access_token()
        except Exception as exc:  # noqa: BLE001 - a refused or unreachable token is no answer
            raise RemoteStateUnavailable(
                f"YouTube could not be asked: no access token ({type(exc).__name__})."
            ) from None
        url = f"{YOUTUBE_API_BASE}/videos?{urlencode({'part': 'status', 'id': remote_video_id})}"
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
                    failure_reason=st.get("failureReason"),
                )
        except Exception as exc:  # noqa: BLE001
            # An empty `items` list above is YouTube saying no. This is YouTube saying nothing.
            raise RemoteStateUnavailable(f"YouTube could not be queried: {exc}") from None

    async def update_visibility(
        self, remote_video_id: str, privacy_status: str, *, made_for_kids: bool = False
    ) -> RemoteVideoStatus:
        """Change a video's visibility with videos.update on the status part.

        The status part is replaced whole: a property the request does not mention reverts
        to its default, so the synthetic-media declaration and the made-for-kids answer are
        sent again with the new privacy. The answer is the video resource; an answer that does
        not name the video is YouTube saying nothing, raised as `RemoteStateUnavailable`
        like every other unanswered question here, and a 404 is YouTube saying the video is
        not there. Repeatable: sending the same status twice leaves the same status.
        ``made_for_kids`` is the channel's own answer (its upload settings, migration 0053).
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
                    "selfDeclaredMadeForKids": bool(made_for_kids),
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
        self,
        idempotency_key: str,
        expected_title: str,
        *,
        created_after: str | None = None,
        channel_id: str | None = None,
    ) -> UploadResult | None:
        """Whether this publication's video is already on the studio's own channel.

        Read from the channel's uploads playlist (``playlistItems.list``, parts snippet and
        status, 1 quota unit a page), which lists the owner's private uploads too; the search
        index may not hold a fresh private upload, and ``search.list`` has no ``mine``
        parameter, so the old query searched all of YouTube. A video is this publication only
        when its title is exactly the title uploaded, it belongs to the channel
        (``channel_id``, else this account's channel) and it was uploaded no earlier than the
        publication was written (``created_after``, with two minutes for the two clocks).
        ``None`` is the channel answering that it holds no such video; a question that could
        not be put or answered raises `RemoteStateUnavailable`.
        """
        if not self.is_configured:
            raise RemoteStateUnavailable(
                "No YouTube credentials are configured, so a previous upload cannot be ruled out."
            )
        owner = channel_id or self.channel_id
        if not owner:
            raise RemoteStateUnavailable(
                "The channel this publication belongs to is not known, so a video found by its "
                "title cannot be told from another channel's."
            )
        since = _moment(created_after)
        if since is not None:
            since -= RECONCILE_CLOCK_SKEW
        try:
            token = self._get_access_token()
            playlist = self.uploads_playlist_id or self._uploads_playlist(token, owner)
            page_token: str | None = None
            for _page in range(RECONCILE_MAX_PAGES):
                query: dict[str, Any] = {
                    "part": "snippet,status",
                    "playlistId": playlist,
                    "maxResults": 50,
                }
                if page_token:
                    query["pageToken"] = page_token
                req = Request(
                    f"{YOUTUBE_API_BASE}/playlistItems?{urlencode(query)}",
                    headers={"Authorization": f"Bearer {token}"},
                    method="GET",
                )
                with _open(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items") or []
                older = 0
                for item in items:
                    snippet = item.get("snippet") or {}
                    when = _moment(snippet.get("publishedAt"))
                    if since is not None and when is not None and when < since:
                        older += 1
                        continue
                    video_owner = snippet.get("videoOwnerChannelId") or snippet.get("channelId")
                    video_id = (snippet.get("resourceId") or {}).get("videoId")
                    if (
                        video_id
                        and video_owner == owner
                        and _same_title(snippet.get("title", ""), expected_title)
                    ):
                        status = item.get("status") or {}
                        return UploadResult(
                            remote_video_id=video_id,
                            remote_url=f"https://youtube.com/shorts/{video_id}",
                            status="CONFIRMED",
                            privacy_status=status.get("privacyStatus"),
                        )
                page_token = data.get("nextPageToken")
                # Newest first: a page whose every item is older than the publication ends
                # the question, and so does the last page.
                if not page_token or (items and older == len(items)):
                    return None
        except RemoteStateUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RemoteStateUnavailable(
                f"The channel's uploads could not be read: {type(exc).__name__}"
            ) from None
        raise RemoteStateUnavailable(
            f"The channel's last {RECONCILE_MAX_PAGES * 50} uploads were read without reaching "
            "the time this publication was written; whether it is there is not decided."
        )

    def _uploads_playlist(self, token: str, owner: str) -> str:
        """The channel's uploads playlist, asked of channels.list when it was not stored."""
        req = Request(
            f"{YOUTUBE_API_BASE}/channels?{urlencode({'part': 'contentDetails', 'id': owner})}",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        with _open(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("items") or []
        playlist = (
            ((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
            if items
            else None
        )
        if not playlist:
            raise RemoteStateUnavailable("The channel's uploads playlist could not be found.")
        self.uploads_playlist_id = str(playlist)
        return self.uploads_playlist_id
