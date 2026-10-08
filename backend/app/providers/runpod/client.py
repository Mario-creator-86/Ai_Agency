from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlsplit

from app.providers.media_http import MediaProviderError, request
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.errors import RunPodProtocolError

Transport = Callable[..., tuple[Any, bytes, str]]
logger = logging.getLogger("studio.runpod")


def backoff_seconds(attempt: int) -> float:
    return min(30, 2**attempt) + random.uniform(0, 0.25)


class RunPodClient:
    def __init__(self, config: RunPodConfig, transport: Transport | None = None) -> None:
        self.config = config
        self.transport = transport or request

    async def call(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        *,
        key: str | None = None,
        control: bool = False,
    ) -> dict[str, Any]:
        base = (
            "https://api.runpod.ai/v2/" + str(self.config.endpoint_id)
            if self.config.mode == "serverless" and not control
            else self.config.generation_base_url
        )
        if not base:
            raise RunPodProtocolError("RunPod generation address is not configured")
        url = urlsplit(base)
        headers = {
            "Authorization": "Bearer " + self.config.api_key.get_secret_value(),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if key:
            headers["Idempotency-Key"] = key
        body = json.dumps(data, allow_nan=False).encode() if data is not None else None
        if body is not None and len(body) > 10 * 1024 * 1024:
            raise RunPodProtocolError("Cloud request exceeds 10 MB; reduce source images")
        for attempt in range(self.config.max_retries + 1):
            try:
                value, _, _ = await asyncio.to_thread(
                    self.transport,
                    str(url.hostname),
                    method,
                    url.path.rstrip("/") + path,
                    headers,
                    body,
                    timeout=self.config.request_timeout,
                    total_seconds=self.config.request_timeout,
                    allowed_statuses=(200, 202),
                    connect_before_send=method == "POST",
                )
                if not isinstance(value, dict):
                    raise RunPodProtocolError("RunPod returned a non-object response")
                return value
            except MediaProviderError as exc:
                safe = method == "GET" or exc.unsent
                transient = (
                    exc.unsent or exc.unanswered or exc.http_status in (429, 500, 502, 503, 504)
                )
                if not safe or not transient or attempt >= self.config.max_retries:
                    raise
                delay = max(backoff_seconds(attempt), exc.retry_after or 0)
                if delay > 30:
                    raise
                logger.warning(
                    "runpod_retry",
                    extra={
                        "operation": method,
                        "attempt": attempt + 1,
                        "http_status": exc.http_status,
                    },
                )
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def submit(self, operation: str, payload: dict[str, Any], key: str) -> dict[str, Any]:
        if self.config.mode == "serverless":
            return await self.call(
                "POST",
                "/run",
                {"input": {"operation": operation, **payload, "idempotency_key": key}},
                key=key,
            )
        path = "/finalize/video" if operation == "finalize" else "/generate/" + operation
        return await self.call("POST", path, {**payload, "idempotency_key": key}, key=key)

    async def status(self, remote_id: str) -> dict[str, Any]:
        family = "/status/" if self.config.mode == "serverless" else "/jobs/"
        return await self.call("GET", family + quote(remote_id, safe=""))

    async def cancel(self, remote_id: str) -> dict[str, Any]:
        if self.config.mode == "serverless":
            return await self.call("POST", "/cancel/" + quote(remote_id, safe=""))
        if self.config.pod_cancel_path:
            return await self.call(
                "POST", self.config.pod_cancel_path.replace("{job_id}", quote(remote_id, safe=""))
            )
        # Custom cancellation is optional. No speculative call to an unspecified cloud route.
        raise RunPodProtocolError("Custom Pod API has not declared a cancellation contract")

    async def health(self) -> dict[str, Any]:
        return await self.call("GET", "/health")

    async def models(self) -> dict[str, Any]:
        # Queue health does not prove installed models. /models must be a read-only backend
        # address in serverless mode; never submit a billable job to discover its catalogue.
        return await self.call("GET", "/models", control=True)

    async def download(self, url: str) -> tuple[bytes, str]:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.port not in (None, 443)
        ):
            raise RunPodProtocolError("RunPod returned an unsafe output address")
        # Signed CDN queries are used only here, never stored in logs or sent the API key.
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        for attempt in range(self.config.max_retries + 1):
            try:
                _, content, kind = await asyncio.to_thread(
                    self.transport,
                    parsed.hostname,
                    "GET",
                    path,
                    {},
                    expect_json=False,
                    public_only=True,
                    timeout=self.config.request_timeout,
                    total_seconds=self.config.request_timeout,
                )
                break
            except MediaProviderError as exc:
                if (
                    not (
                        exc.unsent or exc.unanswered or exc.http_status in (429, 500, 502, 503, 504)
                    )
                    or attempt >= self.config.max_retries
                ):
                    raise
                delay = max(backoff_seconds(attempt), exc.retry_after or 0)
                if delay > 30:
                    raise
                await asyncio.sleep(delay)
        if not content:
            raise RunPodProtocolError("RunPod returned an empty asset")
        return content, kind
