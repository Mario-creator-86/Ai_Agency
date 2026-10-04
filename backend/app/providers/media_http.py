"""Shared HTTPS plumbing for the media provider adapters.

Every adapter here talks to a documented vendor endpoint over TLS and returns what came back.
The rules are the same as everywhere else in the studio: a request that fails raises, a response
that is not what the contract promised raises, and nothing invents a plausible substitute. An
adapter that quietly produced a fallback asset would put a file into the pipeline that QC and the
publishing gate would then reason about as if a provider had made it.
"""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import struct
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from app.providers.retry import SAFE_TO_RESEND_STATUSES, call_with_retries, parse_retry_after


class MediaProviderError(RuntimeError):
    """The provider did not return a usable result, so the caller must not continue.

    `code` is the vendor's own short error identifier when the response carried one (for
    ElevenLabs, `detail.status`, e.g. ``missing_permissions``); it is a closed-vocabulary
    slug, never free text, so it can be shown to the Owner and matched by callers.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        http_status: int | None = None,
        retry_after: float | None = None,
        unsent: bool = False,
        unanswered: bool = False,
        detail: str | None = None,
        issues: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        #: The vendor's own reason, sanitised (no keys, pictures, signed URLs) and capped at
        #: `MAX_DETAIL_CHARS`. Runway's 400 names the field it refused; dropped, the studio
        #: could only guess and changed the model instead of fixing the request.
        self.detail = detail
        #: The vendor's per-field complaints as {"path", "message"}, sanitised, at most ten.
        self.issues: list[dict[str, str]] = list(issues or [])
        #: Seconds the vendor asked the studio to wait (its Retry-After), when it answered.
        self.retry_after = retry_after
        #: The request never left this machine (refused connection, DNS, TLS handshake).
        #: Always safe to send again.
        self.unsent = unsent
        #: The request left and no answer came back. The vendor may have served it, so a
        #: billed request is not sent again on this alone (see `app.providers.retry`).
        self.unanswered = unanswered


class MediaProviderNotConfigured(MediaProviderError):
    """Credentials for this provider are absent, so it cannot be called at all."""


class TaskStillOpen(MediaProviderError):
    """The vendor accepted a task (and may bill it), and its output was not collected: the
    poll ran out of time, the vendor did not answer the poll, or the download failed.

    Not a refusal. The task is collected later by ``task_id`` (a GET, free), and the scene is
    never bought again while it is open. A task the vendor itself reported FAILED is a plain
    MediaProviderError, never this.
    """

    def __init__(self, message: str, *, task_id: str, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.task_id = task_id


#: A generated still or a narration segment is large; a short is not. These caps stop a
#: mistaken endpoint from streaming an unbounded body into memory.
#: A generated shot is the largest thing a vendor hands back: eight seconds of 1080x1920
#: came to nearly forty megabytes, and two scenes of a premium film were lost to a
#: thirty-two megabyte cap. The cap exists so a stray response cannot fill memory, not to
#: judge a film's weight.
MAX_MEDIA_BYTES = 96 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to an address checked beforehand: the socket goes to that IP, TLS still
    authenticates the host name. A second lookup at connect time could answer differently
    (DNS rebinding); pinning the checked address leaves it no say."""

    def __init__(self, host: str, address: str, timeout: float | None = None) -> None:
        self.tls_context = ssl.create_default_context()
        super().__init__(host, timeout=timeout, context=self.tls_context)
        self.address = address

    def connect(self) -> None:
        sock = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self.tls_context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def public_address(host: str) -> str:
    """One public address of ``host``, or MediaProviderError (``unsent``) when the name does
    not resolve or any of its addresses is private, loopback, link-local or reserved.

    The same rule the research retriever applies to a source (`resolve_public`): every
    address must be global, so a name with one public and one internal address is refused.
    """
    try:
        found = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise MediaProviderError(f"{host} could not be resolved", unsent=True) from exc
    addresses = {str(item[4][0]) for item in found}
    try:
        public = bool(addresses) and all(
            ipaddress.ip_address(address.split("%", 1)[0]).is_global for address in addresses
        )
    except ValueError:
        public = False
    if not public:
        raise MediaProviderError(f"{host} does not resolve to a public address", unsent=True)
    return sorted(addresses, key=lambda address: (":" in address, address))[0]


def request(
    host: str,
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes | None = None,
    *,
    timeout: float = 120,
    expect_json: bool = True,
    public_only: bool = False,
    total_seconds: float | None = None,
) -> tuple[Any, bytes, str]:
    """Make one HTTPS request and return (parsed json | None, raw body, content type).

    Only HTTPS, only the host named by the adapter, and a hard cap on the response size. A
    non-200 status raises rather than returning an empty result that a caller might store.
    ``public_only`` is for a host the vendor's answer named rather than the code (an output
    URL): the name must resolve to public addresses only, and the socket is pinned to the
    one checked.

    ``timeout`` bounds each socket operation, never the whole answer: a server that keeps
    sending a byte now and then holds the caller for as long as it likes. ``total_seconds``
    is the whole request's end (2026-10-03: a still redo of the Owner's waited past fifteen
    minutes with nothing recorded): the body is read in pieces and, once it has passed, the
    request raises as unanswered - the vendor may have served it, so a purchase is never
    sent again on this.
    """
    deadline = time.monotonic() + float(total_seconds) if total_seconds else None
    if deadline is not None:
        timeout = max(0.1, min(float(timeout), float(total_seconds or timeout)))
    if public_only:
        connection: http.client.HTTPSConnection = PinnedHTTPSConnection(
            host, public_address(host), timeout=timeout
        )
    else:
        connection = http.client.HTTPSConnection(host, timeout=timeout)
    try:
        # Two failure phases, told apart for the retry policy. `request` connects and sends:
        # a failure here means the vendor never saw the request. From `getresponse` on, it
        # did, and a billed request that then goes quiet may have been served.
        try:
            connection.request(method, path, body, headers)
        except (OSError, http.client.HTTPException) as exc:
            raise MediaProviderError(f"{host} could not be reached", unsent=True) from exc
        # The overall end is enforced on the socket itself: a read blocks until it has the
        # bytes it asked for, and a vendor that sends one byte inside every socket timeout
        # (in its headers or its body) would hold a check made between reads for ever. At
        # the deadline the guard shuts the socket down and the answer counts as unanswered.
        guard = _DeadlineGuard(connection, deadline) if deadline is not None else None
        try:
            response = connection.getresponse()
            limit = MAX_JSON_BYTES if expect_json else MAX_MEDIA_BYTES
            payload = (
                response.read(limit + 1)
                if deadline is None
                else _read_until(connection, response, limit + 1, deadline, host, total_seconds)
            )
        except (OSError, http.client.HTTPException) as exc:
            if guard is not None and guard.fired:
                raise _past_deadline(host, total_seconds) from exc
            raise MediaProviderError(f"{host} did not answer", unanswered=True) from exc
        finally:
            if guard is not None:
                guard.cancel()
        if guard is not None and guard.fired:
            # A body cut by the guard may look complete; it is never taken for the answer.
            raise _past_deadline(host, total_seconds)
        if len(payload) > limit:
            raise MediaProviderError(f"{host} returned more data than the adapter accepts")
        if response.status != 200:
            # The message stays the status alone. The vendor's reason travels beside it,
            # sanitised and capped (`error_details`): it can echo request details, so keys,
            # inline pictures and signed URLs are cut out before anything keeps it. The
            # vendor's short error identifier and the wait it asked for travel too, so a
            # rate limit is honoured rather than guessed at.
            detail, issues = error_details(payload)
            raise MediaProviderError(
                f"{host} refused the request (HTTP {response.status})",
                code=error_code(payload),
                http_status=response.status,
                retry_after=parse_retry_after(response.getheader("Retry-After")),
                detail=detail,
                issues=issues,
                # A server error the vendor does not call safe to retry may come after the
                # work was done: for a purchase it is possibly charged, never "nothing".
                unanswered=possibly_served(response.status),
            )
        content_type = response.headers.get_content_type()
        if not expect_json:
            return None, payload, content_type
        try:
            return json.loads(payload), payload, content_type
        except json.JSONDecodeError as exc:
            raise MediaProviderError(f"{host} returned a malformed response") from exc
    finally:
        connection.close()


#: The piece a bounded answer is read in: small enough that its deadline is checked often.
_READ_CHUNK = 64 * 1024


def _read_until(
    connection: http.client.HTTPSConnection,
    response: Any,
    limit: int,
    deadline: float,
    host: str,
    total_seconds: float | None,
) -> bytes:
    """The body, read in pieces until it ends, ``limit`` bytes are in, or ``deadline`` passes
    (raised as unanswered: the vendor may have served the request)."""
    parts: list[bytes] = []
    size = 0
    while size < limit:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _past_deadline(host, total_seconds)
        sock = getattr(connection, "sock", None)
        if sock is not None:
            # Each wait for the next piece ends with the request's own end at the latest.
            sock.settimeout(max(0.1, min(remaining, sock.gettimeout() or remaining)))
        piece = response.read(min(_READ_CHUNK, limit - size))
        if not piece:
            break
        parts.append(piece)
        size += len(piece)
    return b"".join(parts)


def _past_deadline(host: str, total_seconds: float | None) -> MediaProviderError:
    """The error of an answer that did not end by the request's overall deadline: unanswered,
    because the vendor may have served (and billed) the request."""
    return MediaProviderError(
        f"{host} did not finish its answer within {float(total_seconds or 0):.0f} s",
        unanswered=True,
    )


class _DeadlineGuard:
    """Shuts a request's socket down when its overall deadline passes, whatever read is
    blocked on it then (a status line, a header, a body piece)."""

    def __init__(self, connection: Any, deadline: float) -> None:
        import threading  # noqa: PLC0415

        self._connection = connection
        self.fired = False
        self._timer = threading.Timer(max(0.0, deadline - time.monotonic()), self._fire)
        self._timer.daemon = True
        self._timer.start()

    def _fire(self) -> None:
        self.fired = True
        sock = getattr(self._connection, "sock", None)
        if sock is None:
            return
        with contextlib.suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)

    def cancel(self) -> None:
        self._timer.cancel()


def possibly_served(status: int) -> bool:
    """Whether an error status may have come after the vendor did (and billed) the work: any
    5xx except the ones it documents as "not served, try again" (`SAFE_TO_RESEND_STATUSES`)."""
    return 500 <= int(status) <= 599 and int(status) not in SAFE_TO_RESEND_STATUSES


def retrying(
    transport: Callable[..., tuple[Any, bytes, str]],
    host: str,
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes | None = None,
    *,
    repeatable: bool | None = None,
    **kwargs: Any,
) -> tuple[Any, bytes, str]:
    """`transport(host, method, path, ...)` with the studio's retry policy around it.

    The transport is passed in rather than named here so each adapter resolves `request`
    from its own module at call time — which is where the tests replace it with a recorder.
    `repeatable` defaults to "not a POST": a POST to these vendors is a purchase (a narration,
    a still, a task), and a purchase that got no answer, or a 5xx the vendor does not call
    safe, is not made twice.
    """
    if repeatable is None:
        repeatable = method.upper() != "POST"
    return call_with_retries(
        lambda: transport(host, method, path, headers, body, **kwargs),
        repeatable=repeatable,
        what=f"{host} {method} {path.split('?', 1)[0]}",
    )


_CODE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def error_code(payload: bytes) -> str | None:
    """The vendor's error identifier from an error body, if it is a plain slug.

    Accepts ``{"detail": {"status": "missing_permissions"}}`` (ElevenLabs) and
    ``{"detail": "slug"}`` / ``{"error": {"code": "slug"}}`` shapes; anything else is None.
    """
    try:
        body = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    candidates = []
    detail = body.get("detail")
    if isinstance(detail, dict):
        candidates.append(detail.get("status"))
        candidates.append(detail.get("code"))
    else:
        candidates.append(detail)
    error = body.get("error")
    if isinstance(error, dict):
        candidates.append(error.get("code"))
    for candidate in candidates:
        if isinstance(candidate, str) and _CODE.match(candidate):
            return candidate
    return None


#: The most of a vendor's reason the studio keeps, in characters.
MAX_DETAIL_CHARS = 500
MAX_ISSUES = 10
_REDACTED = "[…]"
#: What must never be kept from a vendor's text, in the order it is cut: an inline picture
#: (a data URI is the whole first frame), an Authorization value, a URL (a signed output
#: URL is a credential in its query), a key-shaped token, and any long opaque run that
#: could be one.
_SECRET_PATTERNS = (
    re.compile(r"data:[\w.+/-]*;base64,[A-Za-z0-9+/=_-]*"),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[^\s\"',;]+"),
    re.compile(r"(?i)\b(?:https?|wss?)://[^\s\"'<>]+"),
    re.compile(r"(?i)\b(?:key|sk|pk|api[_-]?key|token|secret)[_-][A-Za-z0-9._-]{8,}"),
    re.compile(r"[A-Za-z0-9+/=_-]{32,}"),
)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def sanitise_vendor_text(text: Any, limit: int = MAX_DETAIL_CHARS) -> str:
    """A vendor's free text made safe to keep and to show: secrets cut, one line, capped."""
    cleaned = _CONTROL.sub(" ", str(text))
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub(_REDACTED, cleaned)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > limit:
        cleaned = cleaned[: max(0, limit - 1)].rstrip() + "…"
    return cleaned


def _issue_path(path: Any) -> str:
    if isinstance(path, list | tuple):
        return ".".join(str(part) for part in path)
    return str(path) if path is not None else ""


def error_details(payload: bytes) -> tuple[str | None, list[dict[str, str]]]:
    """(sanitised reason, per-field issues) from an error body, or (None, []) if unreadable.

    Reads Runway's ``{"error": str, "issues": [{"path": [...], "message": str}]}`` and the
    ``{"error": {"message"}}`` / ``{"detail": str | {"message"}}`` shapes other vendors use.
    """
    try:
        body = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return None, []
    if not isinstance(body, dict):
        return None, []
    parts: list[str] = []
    for key in ("error", "detail", "message"):
        value = body.get(key)
        if isinstance(value, dict):
            value = value.get("message") or value.get("status") or value.get("code")
        if isinstance(value, str) and value.strip():
            parts.append(value)
            break
    issues: list[dict[str, str]] = []
    raw_issues = body.get("issues")
    if isinstance(raw_issues, list):
        for issue in raw_issues[:MAX_ISSUES]:
            if not isinstance(issue, dict):
                continue
            path = sanitise_vendor_text(_issue_path(issue.get("path")), 80)
            message = sanitise_vendor_text(issue.get("message") or "", 200)
            if not (path or message):
                continue
            issues.append({"path": path, "message": message})
            parts.append(f"{path}: {message}" if path else message)
    if not parts:
        return None, issues
    return sanitise_vendor_text("; ".join(parts)), issues


def host_of(base_url: str, default: str) -> str:
    parsed = urlsplit(base_url or "")
    if parsed.scheme and parsed.scheme != "https":
        raise MediaProviderError("Media providers are only called over HTTPS")
    return parsed.hostname or default


def png_dimensions(data: bytes) -> tuple[int, int]:
    """Read width and height out of a PNG header.

    Measured from the bytes that arrived, never taken from what was requested: a provider that
    returns a different size than asked for must not be recorded as having honoured the request.
    """
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise MediaProviderError("The provider did not return a PNG image")
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width <= 8192 and 0 < height <= 8192):
        raise MediaProviderError("The returned image has implausible dimensions")
    return int(width), int(height)


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Read width and height from a JPEG's first frame header (SOF marker)."""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise MediaProviderError("The provider did not return a JPEG image")
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        (length,) = struct.unpack(">H", data[index + 2 : index + 4])
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            if not (0 < width <= 8192 and 0 < height <= 8192):
                raise MediaProviderError("The returned image has implausible dimensions")
            return int(width), int(height)
        index += 2 + length
    raise MediaProviderError("The JPEG image has no readable frame header")


def image_dimensions(data: bytes, content_type: str) -> tuple[str, int, int]:
    """(format, width, height) measured from the bytes; the content type only picks the parser."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" or "png" in content_type:
        width, height = png_dimensions(data)
        return "png", width, height
    if data[:3] == b"\xff\xd8\xff" or "jpeg" in content_type or "jpg" in content_type:
        width, height = jpeg_dimensions(data)
        return "jpeg", width, height
    raise MediaProviderError("The provider returned an image format the studio cannot measure")


def mp3_duration_seconds(data: bytes) -> float:
    """Estimate an MP3's duration by walking its frame headers.

    Constant-bitrate MP3 has no duration field, so the only honest way to know how long the
    audio is, is to count its frames. The alternative — assuming the length the text "should"
    take — would put a number into the render job that nothing measured.
    """
    bitrates = [
        0,
        32,
        40,
        48,
        56,
        64,
        80,
        96,
        112,
        128,
        160,
        192,
        224,
        256,
        320,
        0,
    ]  # MPEG-1 Layer III, kbps
    rates = {0: 44100, 1: 48000, 2: 32000}
    index = 0
    duration = 0.0
    frames = 0
    limit = len(data) - 4

    # Skip an ID3v2 tag if present; its size is a 28-bit synchsafe integer.
    if data[:3] == b"ID3" and len(data) > 10:
        size = 0
        for byte in data[6:10]:
            size = (size << 7) | (byte & 0x7F)
        index = 10 + size

    while index < limit and frames < 200_000:
        if data[index] != 0xFF or (data[index + 1] & 0xE0) != 0xE0:
            index += 1
            continue
        header = data[index : index + 4]
        version_bits = (header[1] >> 3) & 0x03
        layer_bits = (header[1] >> 1) & 0x03
        bitrate_index = (header[2] >> 4) & 0x0F
        rate_index = (header[2] >> 2) & 0x03
        padding = (header[2] >> 1) & 0x01
        if version_bits != 0x03 or layer_bits != 0x01 or rate_index == 0x03:
            index += 1
            continue
        bitrate = bitrates[bitrate_index] * 1000
        sample_rate = rates[rate_index]
        if not bitrate:
            index += 1
            continue
        frame_length = int(144 * bitrate / sample_rate) + padding
        if frame_length <= 4:
            index += 1
            continue
        duration += 1152 / sample_rate
        frames += 1
        index += frame_length

    if not frames:
        raise MediaProviderError("The provider did not return decodable MP3 audio")
    return round(duration, 3)


def wav_duration_seconds(data: bytes) -> float:
    """Read a RIFF/WAVE header and compute the duration from its own fields."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise MediaProviderError("The provider did not return a WAV file")
    index = 12
    sample_rate = channels = bits = 0
    while index + 8 <= len(data):
        chunk_id = data[index : index + 4]
        (chunk_size,) = struct.unpack("<I", data[index + 4 : index + 8])
        payload = data[index + 8 : index + 8 + chunk_size]
        if chunk_id == b"fmt " and len(payload) >= 16:
            channels, sample_rate = struct.unpack("<HI", payload[2:8])
            (bits,) = struct.unpack("<H", payload[14:16])
        elif chunk_id == b"data":
            if not (sample_rate and channels and bits):
                raise MediaProviderError("The WAV file has no readable format header")
            frame_size = channels * (bits // 8)
            if frame_size <= 0:
                raise MediaProviderError("The WAV file declares an unusable frame size")
            return round(len(payload) / frame_size / sample_rate, 3)
        index += 8 + chunk_size + (chunk_size & 1)
    raise MediaProviderError("The WAV file contains no audio data")
