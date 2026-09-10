"""Bounded HTTPS retrieval with exact-host policy and DNS-pinned TLS connections."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import socket
import ssl
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import uuid4

from app.factual.schemas import IngestSourceCommand


class RetrievalError(ValueError):
    """A retrieval failed; callers must not manufacture source evidence."""


class RateLimited(RetrievalError):
    def __init__(self, retry_after: str | None) -> None:
        super().__init__("Source rate limited the request; no automatic retry performed")
        self.retry_after = retry_after


@dataclass(frozen=True)
class RetrievalPolicy:
    allowed_hosts: tuple[str, ...]
    timeout_seconds: float = 15
    max_bytes: int = 2_000_000
    max_text_chars: int = 100_000
    max_redirects: int = 3
    cache_seconds: float = 300
    cache_entries: int = 32

    def __post_init__(self) -> None:
        if not self.allowed_hosts or any(
            not host or host != host.lower() or any(c in host for c in "/:*@")
            for host in self.allowed_hosts
        ):
            raise ValueError("Configure explicit lowercase DNS hostnames")
        # An allowlist naming an internal address defeats its own purpose. `resolve_public`
        # already refuses to connect to one, but catching it here means a mistyped or hostile
        # configuration fails when the policy is built rather than on the first fetch — and it
        # closes the case where a name resolves publicly at check time and internally later.
        for host in self.allowed_hosts:
            if host in ("localhost", "localhost.localdomain") or host.endswith(".localhost"):
                raise ValueError("The allowlist names public sources, not this machine")
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                continue  # A DNS name; resolve_public checks where it actually points.
            if not address.is_global:
                raise ValueError("The allowlist names public sources, not internal addresses")
        if not (0 < self.timeout_seconds <= 120 and 10 <= self.max_bytes <= 10_000_000):
            raise ValueError("Invalid timeout or response size limit")
        if not (10 <= self.max_text_chars <= 100_000 and 0 <= self.max_redirects <= 5):
            raise ValueError("Invalid text or redirect limit")
        if not (0 <= self.cache_seconds <= 3600 and 1 <= self.cache_entries <= 128):
            raise ValueError("Invalid cache limits")


@dataclass(frozen=True)
class RetrievedSource:
    requested_url: str
    url: str
    title: str
    publisher: str
    text: str
    retrieved_at: str
    body_sha256: str
    content_sha256: str
    content_type: str

    def ingest_command(self, topic_id: str | None = None) -> IngestSourceCommand:
        # Retrieval does not establish publisher identity, credibility or claim correctness.
        return IngestSourceCommand(
            command_id=uuid4(),
            topic_id=topic_id,
            url=self.url,
            title=self.title,
            publisher=self.publisher,
            author=None,
            raw_content=self.text,
            credibility_score=0,
        )

    def receipt(self) -> dict:
        return {key: value for key, value in asdict(self).items() if key != "text"}


class _PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.excluded: list[str] = []
        self.in_title = False
        self.title: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self.excluded.append(tag)
        if tag == "title":
            self.in_title = True
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "article", "section"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.excluded and tag == self.excluded[-1]:
            self.excluded.pop()
        if tag == "title":
            self.in_title = False
        if tag in {"p", "div", "li", "h1", "h2", "h3", "article", "section"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.excluded:
            return
        if self.in_title:
            self.title.append(data)
        else:
            self.parts.append(data)


def validate_url(url: str, policy: RetrievalPolicy) -> tuple[str, str]:
    if len(url) > 1000 or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise RetrievalError("URL contains invalid characters or exceeds the length limit")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or host not in policy.allowed_hosts
            or "\\" in url
        ):
            raise RetrievalError("Only configured public HTTPS hosts on port 443 are allowed")
        host.encode("ascii")
        normalized = urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
        normalized.encode("ascii")
    except (ValueError, UnicodeError) as exc:
        raise RetrievalError("Invalid or disallowed source URL") from exc
    return normalized, host


def resolve_public(host: str) -> str:
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    ips = {str(item[4][0]) for item in addresses}
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise RetrievalError("Source DNS must resolve exclusively to public addresses")
    return sorted(ips, key=lambda ip: (":" in ip, ip))[0]


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, timeout: float) -> None:
        self.tls_context = ssl.create_default_context()
        super().__init__(host, timeout=timeout, context=self.tls_context)
        self.address = address

    def connect(self) -> None:
        # The socket connects to the validated IP, but TLS authenticates the original hostname.
        sock = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self.tls_context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class SourceRetriever:
    def __init__(self, policy: RetrievalPolicy) -> None:
        self.policy = policy
        self._cache: OrderedDict[str, tuple[float, RetrievedSource]] = OrderedDict()

    def fetch(self, url: str) -> RetrievedSource:
        requested, _ = validate_url(url, self.policy)
        cached = self._cache.get(requested)
        if cached and time.monotonic() - cached[0] < self.policy.cache_seconds:
            self._cache.move_to_end(requested)
            return cached[1]
        self._cache.pop(requested, None)
        deadline = time.monotonic() + self.policy.timeout_seconds
        current = requested
        try:
            for hop in range(self.policy.max_redirects + 1):
                current, host = validate_url(current, self.policy)
                address = resolve_public(host)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RetrievalError("Source retrieval exceeded its deadline")
                connection = _PinnedHTTPS(host, address, remaining)
                try:
                    parsed = urlsplit(current)
                    target = parsed.path + ("?" + parsed.query if parsed.query else "")
                    connection.request(
                        "GET",
                        target,
                        headers={
                            "Accept": "text/html, text/plain",
                            "Accept-Encoding": "identity",
                            "User-Agent": "AutonomousAIStudio-SourceRetriever/1.0",
                        },
                    )
                    response = connection.getresponse()
                    if response.status == 429:
                        raise RateLimited(response.getheader("Retry-After"))
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.getheader("Location")
                        if not location or hop == self.policy.max_redirects:
                            raise RetrievalError("Source redirect is missing or exceeds the limit")
                        current = urljoin(current, location)
                        continue
                    if response.status != 200:
                        raise RetrievalError(f"Source returned HTTP {response.status}")
                    mime = response.headers.get_content_type()
                    if mime not in ("text/html", "text/plain"):
                        raise RetrievalError("Source is not supported HTML or plain text")
                    if response.getheader("Content-Encoding", "identity").lower() != "identity":
                        raise RetrievalError("Compressed responses are not supported")
                    body = bytearray()
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise RetrievalError("Source retrieval exceeded its deadline")
                        if connection.sock:
                            connection.sock.settimeout(remaining)
                        chunk = response.read1(min(65536, self.policy.max_bytes + 1 - len(body)))
                        if not chunk:
                            if response.length not in (None, 0):
                                raise RetrievalError("Source response ended before Content-Length")
                            break
                        body.extend(chunk)
                        if len(body) > self.policy.max_bytes:
                            raise RetrievalError("Source exceeds the response size limit")
                    charset = response.headers.get_content_charset() or "utf-8"
                    decoded = bytes(body).decode(charset, errors="replace")
                    title = host
                    if mime == "text/html":
                        parser = _PageText()
                        parser.feed(decoded)
                        decoded = "".join(parser.parts)
                        title = " ".join("".join(parser.title).split()) or host
                    text = "\n".join(
                        line for part in decoded.splitlines() if (line := " ".join(part.split()))
                    ).strip()
                    if not 10 <= len(text) <= self.policy.max_text_chars:
                        raise RetrievalError(
                            "Extracted source text is empty, too short or too large"
                        )
                    source = RetrievedSource(
                        requested,
                        current,
                        title[:300],
                        host,
                        text,
                        datetime.now(UTC).isoformat(),
                        hashlib.sha256(body).hexdigest(),
                        hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        mime,
                    )
                    self._cache[requested] = (time.monotonic(), source)
                    while len(self._cache) > self.policy.cache_entries:
                        self._cache.popitem(last=False)
                    return source
                finally:
                    connection.close()
        except (OSError, http.client.HTTPException, LookupError) as exc:
            raise RetrievalError("Source network, TLS or decoding operation failed") from exc
        raise RetrievalError("Source retrieval did not produce a document")
