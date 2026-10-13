"""The Owner's S3-compatible bucket, reached only through presigned URLs the studio signs.

RunPod keeps a /run result for 30 minutes only, so every paid output is written to the
Owner's bucket (Cloudflare R2 or any S3-compatible store he configures in the vault). The
studio never loads boto3: it signs AWS Signature Version 4 query-string URLs with the
standard library (hmac, hashlib) and sends them through the same injectable transport as
every other vendor request, so tests never reach a bucket.

* Path-style addresses, ``https://<endpoint-host>/<bucket>/<key>``: they work on R2, MinIO
  and AWS alike without a DNS name per bucket.
* ``UNSIGNED-PAYLOAD`` and only the ``host`` header signed: the URL is the whole credential,
  so it can be handed to the worker (inputs) and to the downloader (outputs).
* SigV4 presigned URLs live at most 7 days (604800 s); a longer lifetime is refused.

Source: AWS S3 API reference, "Authenticating Requests: Using Query Parameters (AWS
Signature Version 4)"; its published GET example is pinned in tests/test_runpod_s3.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote, urlsplit

from app.providers.media_http import MediaProviderError
from app.providers.runpod.errors import RunPodProtocolError

if TYPE_CHECKING:
    from app.providers.runpod.client import Transport
    from app.providers.runpod.config import BucketConfig

#: SigV4's own ceiling for a presigned URL.
MAX_EXPIRES = 604800
ALGORITHM = "AWS4-HMAC-SHA256"
REQUEST_TIMEOUT = 60.0
MAX_RETRIES = 3


def _uri(value: str, *, slash: bool) -> str:
    # RFC 3986 unreserved characters stay; everything else is percent-encoded (SigV4 rule).
    return quote(value, safe="-_.~/" if slash else "-_.~")


def _signing_key(secret: str, day: str, region: str) -> bytes:
    key = hmac.new(("AWS4" + secret).encode(), day.encode(), hashlib.sha256).digest()
    for part in (region, "s3", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    return key


def presign_url(
    *,
    host: str,
    path: str,
    method: str,
    region: str,
    access_key_id: str,
    secret_access_key: str,
    expires: int,
    now: datetime | None = None,
) -> str:
    """A SigV4 query-string signed URL for ``method`` on ``https://host/path``.

    ``path`` is the raw (unencoded) object path starting with '/'. Only ``host`` is signed and
    the payload is UNSIGNED-PAYLOAD, as the AWS presigned-URL examples do."""
    if not 1 <= int(expires) <= MAX_EXPIRES:
        raise ValueError("A presigned URL lives between 1 s and 7 days")
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    stamp = moment.strftime("%Y%m%dT%H%M%SZ")
    day = moment.strftime("%Y%m%d")
    scope = f"{day}/{region}/s3/aws4_request"
    params = {
        "X-Amz-Algorithm": ALGORITHM,
        "X-Amz-Credential": f"{access_key_id}/{scope}",
        "X-Amz-Date": stamp,
        "X-Amz-Expires": str(int(expires)),
        "X-Amz-SignedHeaders": "host",
    }
    query = "&".join(
        f"{_uri(k, slash=False)}={_uri(v, slash=False)}" for k, v in sorted(params.items())
    )
    canonical_path = _uri(path, slash=True)
    canonical = "\n".join(
        [method, canonical_path, query, f"host:{host}\n", "host", "UNSIGNED-PAYLOAD"]
    )
    to_sign = "\n".join([ALGORITHM, stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    signature = hmac.new(
        _signing_key(secret_access_key, day, region), to_sign.encode(), hashlib.sha256
    ).hexdigest()
    return f"https://{host}{canonical_path}?{query}&X-Amz-Signature={signature}"


def _safe_key(key: str) -> str:
    if (
        not key
        or key.startswith("/")
        or len(key) > 1024
        or ".." in key.split("/")
        or any(ord(c) < 32 or c in "\\?#" for c in key)
    ):
        raise ValueError("Unsafe bucket object key")
    return key


def presign(
    cfg: BucketConfig,
    method: Literal["GET", "PUT", "HEAD"],
    key: str,
    expires: int,
    *,
    now: datetime | None = None,
) -> str:
    """A presigned path-style URL for one object of the Owner's bucket."""
    host = urlsplit(cfg.endpoint_url).hostname
    if not host:
        raise ValueError("The bucket endpoint has no host")
    return presign_url(
        host=host,
        path="/" + cfg.bucket + "/" + _safe_key(key),
        method=method,
        region=cfg.region,
        access_key_id=cfg.access_key_id,
        secret_access_key=cfg.secret_access_key.get_secret_value(),
        expires=expires,
        now=now,
    )


def _split(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return str(parts.hostname), parts.path + ("?" + parts.query if parts.query else "")


async def _send(
    transport: Transport,
    url: str,
    method: str,
    headers: dict[str, str],
    body: bytes | None,
    *,
    expect_json: bool,
    idempotent: bool = True,
) -> tuple[Any, bytes, str]:
    host, path = _split(url)
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await asyncio.to_thread(
                transport,
                host,
                method,
                path,
                headers,
                body,
                timeout=REQUEST_TIMEOUT,
                total_seconds=REQUEST_TIMEOUT * 2,
                expect_json=expect_json,
                allowed_statuses=(200,),
            )
        except MediaProviderError as exc:
            transient = exc.unsent or exc.unanswered or exc.http_status in (429, 500, 502, 503)
            # PUT of a content-addressed object and GET are idempotent: retried on a transient
            # failure. The bucket costs nothing per GPU second, so this never buys anything.
            if not (idempotent and transient) or attempt >= MAX_RETRIES:
                raise
            await asyncio.sleep(min(8.0, 0.5 * 2**attempt))
    raise AssertionError("unreachable")


async def put_bytes(
    cfg: BucketConfig, key: str, data: bytes, mime: str, transport: Transport
) -> None:
    """Upload ``data`` to ``key`` through a short-lived presigned PUT."""
    url = presign(cfg, "PUT", key, 900)
    await _send(transport, url, "PUT", {"Content-Type": mime}, data, expect_json=False)


async def get_json(cfg: BucketConfig, key: str, transport: Transport) -> dict[str, Any] | None:
    """The JSON object at ``key`` (a manifest), or None when the bucket has no such object."""
    url = presign(cfg, "GET", key, 900)
    try:
        value, _raw, _kind = await _send(transport, url, "GET", {}, None, expect_json=True)
    except MediaProviderError as exc:
        if exc.http_status == 404 and not exc.unanswered:
            # NoSuchKey: not written yet. A 403 (a wrong key) is NOT read as "missing".
            return None
        raise
    if not isinstance(value, dict):
        raise RunPodProtocolError("Bucket manifest is not a JSON object")
    return value
