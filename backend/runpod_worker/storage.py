"""The worker's port to the Owner's S3-compatible bucket (e.g. Cloudflare R2).

``boto3`` lives only in the worker image (requirements.txt); it is imported inside
:meth:`S3Storage.from_env`, so the studio's environment, which does not have it, can import
this module. The bucket is reached path-style with SigV4, which every S3-compatible store
accepts. Keys and the endpoint come from the endpoint's RunPod secrets:
AMN_S3_ENDPOINT_URL, AMN_S3_BUCKET, AMN_S3_REGION, AMN_S3_ACCESS_KEY_ID,
AMN_S3_SECRET_ACCESS_KEY. Nothing here ever logs them.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

#: SigV4 presigned URLs live at most 7 days.
MAX_PRESIGN_SECONDS = 604800
#: An input picture (a reference or a first frame) is never larger than this.
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
ENV_KEYS = (
    "AMN_S3_ENDPOINT_URL",
    "AMN_S3_BUCKET",
    "AMN_S3_ACCESS_KEY_ID",
    "AMN_S3_SECRET_ACCESS_KEY",
)


class StorageError(RuntimeError):
    """The bucket refused or did not answer."""


class StorageNotConfigured(StorageError):
    """The endpoint's AMN_S3_* secrets are missing."""


class PreconditionFailed(StorageError):
    """``If-None-Match: *`` found the object already there (someone holds the claim)."""


class ConditionalPutUnsupported(StorageError):
    """The store does not implement conditional PUT (HTTP 501 NotImplemented)."""


def _error_code(exc: BaseException) -> tuple[str, int | None]:
    # botocore's ClientError carries `response`; duck-typed so this module needs no botocore.
    response = getattr(exc, "response", None)
    if not isinstance(response, Mapping):
        return "", None
    error = response.get("Error") or {}
    meta = response.get("ResponseMetadata") or {}
    code = str(error.get("Code", "")) if isinstance(error, Mapping) else ""
    status = meta.get("HTTPStatusCode") if isinstance(meta, Mapping) else None
    return code, status if isinstance(status, int) else None


def _missing(code: str, status: int | None) -> bool:
    return status == 404 or code in ("404", "NoSuchKey", "NotFound")


class S3Storage:
    """The real port, over a boto3 S3 client (or any object with the same four methods)."""

    def __init__(
        self,
        client: Any,
        bucket: str,
        *,
        opener: Callable[..., Any] | None = None,
        max_download_bytes: int = MAX_DOWNLOAD_BYTES,
    ) -> None:
        self._client = client
        self.bucket = bucket
        self._opener = opener or urllib.request.urlopen
        self.max_download_bytes = max_download_bytes

    def __repr__(self) -> str:
        return f"S3Storage(bucket={self.bucket!r})"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> S3Storage:
        values = os.environ if env is None else env
        missing = [name for name in ENV_KEYS if not values.get(name)]
        if missing:
            raise StorageNotConfigured("bucket secrets missing: " + ", ".join(missing))
        endpoint = values["AMN_S3_ENDPOINT_URL"]
        if urlsplit(endpoint).scheme != "https":
            raise StorageNotConfigured("AMN_S3_ENDPOINT_URL must be https")
        import boto3  # type: ignore[import-not-found,unused-ignore]
        from botocore.config import Config  # type: ignore[import-not-found,unused-ignore]

        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=values.get("AMN_S3_REGION") or "auto",
            aws_access_key_id=values["AMN_S3_ACCESS_KEY_ID"],
            aws_secret_access_key=values["AMN_S3_SECRET_ACCESS_KEY"],
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 5, "mode": "standard"},
            ),
        )
        return cls(client, values["AMN_S3_BUCKET"])

    def head(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as exc:
            code, status = _error_code(exc)
            if _missing(code, status):
                return False
            raise StorageError(f"HEAD failed ({code or type(exc).__name__})") from exc

    def get_json(self, key: str) -> dict[str, Any] | None:
        try:
            answer = self._client.get_object(Bucket=self.bucket, Key=key)
            raw = answer["Body"].read(MAX_JSON_BYTES + 1)
        except Exception as exc:
            code, status = _error_code(exc)
            if _missing(code, status):
                return None
            raise StorageError(f"GET failed ({code or type(exc).__name__})") from exc
        if len(raw) > MAX_JSON_BYTES:
            raise StorageError("JSON object too large")
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def put_bytes(self, key: str, data: bytes, mime: str, *, if_none_match: bool = False) -> None:
        extra: dict[str, str] = {"IfNoneMatch": "*"} if if_none_match else {}
        try:
            self._client.put_object(
                Bucket=self.bucket, Key=key, Body=data, ContentType=mime, **extra
            )
        except Exception as exc:
            code, status = _error_code(exc)
            if if_none_match and (
                status in (409, 412) or code in ("PreconditionFailed", "ConditionalRequestConflict")
            ):
                raise PreconditionFailed(key) from exc
            if if_none_match and (status == 501 or code == "NotImplemented"):
                raise ConditionalPutUnsupported(key) from exc
            raise StorageError(f"PUT failed ({code or type(exc).__name__})") from exc

    def presign_get(self, key: str, ttl: int) -> str:
        seconds = max(1, min(int(ttl), MAX_PRESIGN_SECONDS))
        try:
            url = self._client.generate_presigned_url(
                "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=seconds
            )
        except Exception as exc:
            raise StorageError(f"presign failed ({type(exc).__name__})") from exc
        return str(url)

    def download_url(self, url: str) -> bytes:
        """An input the studio uploaded and presigned (https only, size-capped)."""
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise StorageError("input URL must be https without credentials")
        try:
            with self._opener(url, timeout=60) as response:
                data = response.read(self.max_download_bytes + 1)
        except Exception as exc:
            raise StorageError(f"input download failed ({type(exc).__name__})") from exc
        if len(data) > self.max_download_bytes:
            raise StorageError("input too large")
        if not isinstance(data, bytes) or not data:
            raise StorageError("input is empty")
        return data
