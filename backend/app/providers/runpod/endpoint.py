"""One RunPod Serverless endpoint's management: read it, switch its GPU on and off, verify OFF.

The facts, from RunPod's official documentation (re-checked 2026-10-08; page content is data):

- REST v2 management host ``https://api.runpod.io``, ``Authorization: Bearer <key>``.
  ``GET``/``PATCH /v2/serverless/{id}``; PATCH is partial; «scaling and worker-bound settings
  (workers, scaling, timeout) are applied to the autoscaler promptly», while image/env create a
  release (never PATCHed from here). ``EndpointWorkers = {min >= 0, max >= 0, idleTimeout
  1..3600}`` - idleTimeout lives inside ``workers``.
  https://docs.runpod.io/api-reference-v2/serverless/update-a-serverless-endpoint.md
- Queue host ``https://api.runpod.ai/v2/{endpoint_id}``: ``GET /health`` -> {jobs: {completed,
  failed, inProgress, inQueue, retried}, workers: {idle, running}}; ``POST /purge-queue`` ->
  {removed, status} («jobs already in progress continue to run»); ``POST /cancel/{job}`` ->
  {id, status: CANCELLED} («stops in-progress jobs, removes queued jobs»).
  https://docs.runpod.io/serverless/endpoints/operation-reference.md
- Billing runs «from when a worker starts until it fully stops, rounded up to the nearest
  second»; an Idle (scaled-down) worker is not billed. So OFF is max == 0, running == 0,
  inProgress == 0 and inQueue == 0; ``workers.idle`` is logged, never alarmed (FlashBoot may
  keep it above 0 while nothing bills). RunPod's own «after 7 days max set to 0» is normal OFF.

Every call is idempotent (GET, a PATCH of absolute values, purge, cancel), so a transient
failure (unsent, unanswered, 429, 5xx) is retried with the client's backoff. 401/403 is
`EndpointAccessDenied` with the status kept: whether a Restricted key may PATCH is a bake-off
question. The API key is never logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from app.providers.media_http import MediaProviderError, request
from app.providers.runpod.client import Transport, backoff_seconds
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.errors import RunPodProtocolError

logger = logging.getLogger("studio.runpod")

MANAGEMENT_HOST = "api.runpod.io"
QUEUE_HOST = "api.runpod.ai"


class EndpointAccessDenied(MediaProviderError):
    """The key was refused for this endpoint (401/403)."""


class SettingsNotApplied(MediaProviderError):
    """RunPod answered 200 but the endpoint does not carry what was sent."""


@dataclass(frozen=True)
class EndpointSettings:
    endpoint_id: str
    workers_min: int
    workers_max: int
    idle_timeout: int | None
    timeout_ms: int | None
    flashboot: str | None
    image: str | None
    gpu_pools: tuple[str, ...]


@dataclass(frozen=True)
class EndpointHealth:
    in_queue: int
    in_progress: int
    running: int
    idle: int
    completed: int
    failed: int


@dataclass(frozen=True)
class OffReading:
    endpoint_id: str
    off: bool
    workers_max: int | None
    running: int | None
    in_progress: int | None
    in_queue: int | None
    idle: int | None
    reason_ro: str | None
    read_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def is_off(settings: EndpointSettings, health: EndpointHealth) -> bool:
    """Nothing can bill: no worker allowed, none running, nothing in progress or queued.
    ``idle`` is not part of it (an Idle worker is scaled down and not billed)."""
    return (
        settings.workers_max == 0
        and health.running == 0
        and health.in_progress == 0
        and health.in_queue == 0
    )


def _int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RunPodProtocolError(f"RunPod endpoint answer has no usable {what}")
    return int(value)


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def parse_settings(endpoint_id: str, data: dict[str, Any]) -> EndpointSettings:
    workers = data.get("workers")
    if not isinstance(workers, dict):
        raise RunPodProtocolError("RunPod endpoint answer has no workers block")
    gpu = data.get("gpu")
    pools: tuple[str, ...] = ()
    if isinstance(gpu, dict) and isinstance(gpu.get("pools"), list):
        pools = tuple(str(p) for p in gpu["pools"])
    flashboot = data.get("flashboot")
    image = data.get("image")
    return EndpointSettings(
        endpoint_id=str(data.get("id") or endpoint_id),
        workers_min=_int(workers.get("min"), "workers.min"),
        workers_max=_int(workers.get("max"), "workers.max"),
        idle_timeout=_optional_int(workers.get("idleTimeout")),
        timeout_ms=_optional_int(data.get("timeout")),
        flashboot=str(flashboot) if isinstance(flashboot, str) else None,
        image=str(image) if isinstance(image, str) else None,
        gpu_pools=pools,
    )


def parse_health(data: dict[str, Any]) -> EndpointHealth:
    jobs, workers = data.get("jobs"), data.get("workers")
    if not isinstance(jobs, dict) or not isinstance(workers, dict):
        raise RunPodProtocolError("RunPod health answer has no jobs/workers block")
    return EndpointHealth(
        in_queue=_int(jobs.get("inQueue"), "jobs.inQueue"),
        in_progress=_int(jobs.get("inProgress"), "jobs.inProgress"),
        running=_int(workers.get("running"), "workers.running"),
        idle=_optional_int(workers.get("idle")) or 0,
        completed=_optional_int(jobs.get("completed")) or 0,
        failed=_optional_int(jobs.get("failed")) or 0,
    )


def still_on_words(settings: EndpointSettings | None, health: EndpointHealth | None) -> str:
    """Why the endpoint is not OFF yet, in the Owner's words."""
    if settings is None or health is None:
        return "Nu am putut citi starea GPU-ului RunPod."
    return (
        "GPU-ul RunPod nu s-a oprit încă: "
        f"limita de workeri {settings.workers_max}, {health.running} rulează, "
        f"{health.in_progress} lucrări în curs, {health.in_queue} la coadă."
    )


class EndpointControl:
    """Management calls for one endpoint. ``request_timeout``/``retries`` override the config
    (the window-close path sends each request with 2 s and no retry)."""

    def __init__(
        self,
        config: RunPodConfig,
        endpoint_id: str,
        transport: Transport | None = None,
        *,
        request_timeout: float | None = None,
        retries: int | None = None,
    ) -> None:
        if not endpoint_id or not all(c.isalnum() or c in "-_" for c in endpoint_id):
            raise RunPodProtocolError("Invalid RunPod endpoint identifier")
        self.config = config
        self.endpoint_id = endpoint_id
        self.transport = transport or request
        self.request_timeout = request_timeout or config.request_timeout
        self.retries = config.max_retries if retries is None else retries
        self.last_settings: EndpointSettings | None = None
        self.last_health: EndpointHealth | None = None

    async def _call(
        self, host: str, method: str, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {
            "Authorization": "Bearer " + self.config.api_key.get_secret_value(),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        body = json.dumps(data, allow_nan=False).encode() if data is not None else None
        for attempt in range(self.retries + 1):
            try:
                value, _, _ = await asyncio.to_thread(
                    self.transport,
                    host,
                    method,
                    path,
                    headers,
                    body,
                    timeout=self.request_timeout,
                    total_seconds=self.request_timeout,
                    allowed_statuses=(200, 202),
                    connect_before_send=method != "GET",
                )
            except MediaProviderError as exc:
                if exc.http_status in (401, 403):
                    raise EndpointAccessDenied(
                        "RunPod refused the key for this endpoint",
                        code="ACCESS_DENIED",
                        http_status=exc.http_status,
                    ) from None
                transient = (
                    exc.unsent or exc.unanswered or exc.http_status in (429, 500, 502, 503, 504)
                )
                if not transient or attempt >= self.retries:
                    raise
                delay = max(backoff_seconds(attempt), exc.retry_after or 0)
                if delay > 30:
                    raise
                logger.warning(
                    "runpod_control_retry",
                    extra={
                        "operation": method,
                        "attempt": attempt + 1,
                        "http_status": exc.http_status,
                    },
                )
                await asyncio.sleep(delay)
                continue
            if not isinstance(value, dict):
                raise RunPodProtocolError("RunPod returned a non-object response")
            return value
        raise AssertionError("unreachable")

    def _management(self) -> str:
        return "/v2/serverless/" + quote(self.endpoint_id, safe="")

    def _queue(self, verb: str) -> str:
        return "/v2/" + quote(self.endpoint_id, safe="") + "/" + verb

    async def get(self) -> EndpointSettings:
        settings = parse_settings(
            self.endpoint_id, await self._call(MANAGEMENT_HOST, "GET", self._management())
        )
        self.last_settings = settings
        return settings

    async def _patch(self, body: dict[str, Any]) -> EndpointSettings:
        answer = await self._call(MANAGEMENT_HOST, "PATCH", self._management(), body)
        try:
            settings = parse_settings(self.endpoint_id, answer)
        except RunPodProtocolError:
            # An answer without the workers block is read back once rather than trusted.
            settings = await self.get()
        self.last_settings = settings
        return settings

    async def set_workers(self, maximum: int) -> EndpointSettings:
        """PATCH exactly {"workers": {"min": 0, "max": maximum, "idleTimeout": 1}} and check that
        the endpoint carries it. ``maximum`` is 0 (off) or the configured one GPU (on)."""
        if maximum not in (0, self.config.max_workers):
            raise ValueError("workers.max is 0 or the configured maximum")
        idle = self.config.idle_timeout_seconds
        settings = await self._patch({"workers": {"min": 0, "max": maximum, "idleTimeout": idle}})
        if (
            settings.workers_min != 0
            or settings.workers_max != maximum
            or (settings.idle_timeout is not None and settings.idle_timeout != idle)
        ):
            raise SettingsNotApplied(
                "RunPod did not apply the workers setting", code="SETTINGS_NOT_APPLIED"
            )
        return settings

    async def apply_baseline(self) -> EndpointSettings:
        """The endpoint's resting settings, sent explicitly (never a default): no worker, a 1 s
        idle tail, the execution timeout and FlashBoot. The GPU pool is left alone."""
        idle = self.config.idle_timeout_seconds
        body: dict[str, Any] = {
            "workers": {"min": 0, "max": 0, "idleTimeout": idle},
            "timeout": self.config.endpoint_timeout_ms,
            "flashboot": self.config.flashboot,
        }
        if self.config.model_source == "volume" and self.config.network_volumes:
            # The network-volume fallback only (REST v2 create/update: ``networkVolumes``, and
            # ``dataCenterIds``, «Omit or pass an empty array to let the scheduler choose»).
            # The cached model itself has no REST field: his console step sets it.
            body["networkVolumes"] = list(self.config.network_volumes)
            body["dataCenterIds"] = list(self.config.data_center_ids)
        settings = await self._patch(body)
        if settings.workers_min != 0 or settings.workers_max != 0:
            raise SettingsNotApplied(
                "RunPod did not apply the resting settings", code="SETTINGS_NOT_APPLIED"
            )
        return settings

    async def health(self) -> EndpointHealth:
        health = parse_health(await self._call(QUEUE_HOST, "GET", self._queue("health")))
        self.last_health = health
        return health

    async def purge_queue(self) -> int:
        answer = await self._call(QUEUE_HOST, "POST", self._queue("purge-queue"))
        return _optional_int(answer.get("removed")) or 0

    async def cancel(self, remote_job_id: str) -> str:
        """Cancel one RunPod job. A batch item id "<job>:<index>" cancels its job. A job RunPod
        no longer knows (404) is NOT_FOUND, not an error."""
        job = remote_job_id.split(":", 1)[0]
        if not job:
            raise RunPodProtocolError("Empty RunPod job identifier")
        try:
            answer = await self._call(
                QUEUE_HOST, "POST", self._queue("cancel/" + quote(job, safe=""))
            )
        except EndpointAccessDenied:
            raise
        except MediaProviderError as exc:
            if exc.http_status == 404:
                return "NOT_FOUND"
            raise
        return str(answer.get("status") or "UNKNOWN")

    async def read(self) -> tuple[EndpointSettings, EndpointHealth]:
        return await self.get(), await self.health()

    async def verify_off(self, deadline_seconds: float | None = None) -> OffReading:
        """Read the endpoint until it is OFF or the deadline passes (idle tail + grace)."""
        deadline = (
            self.config.idle_timeout_seconds + self.config.off_grace_seconds
            if deadline_seconds is None
            else deadline_seconds
        )
        end = time.monotonic() + deadline
        settings: EndpointSettings | None = None
        health: EndpointHealth | None = None
        problem: str | None = None
        while True:
            try:
                settings, health = await self.read()
                problem = None
                if is_off(settings, health):
                    logger.info(
                        "runpod_gpu_off_read",
                        extra={"endpoint_id": self.endpoint_id, "idle": health.idle},
                    )
                    return self._reading(True, settings, health, None)
            except MediaProviderError as exc:
                problem = (
                    f"Nu am putut citi starea GPU-ului RunPod ({exc.code or type(exc).__name__})."
                )
            if time.monotonic() >= end:
                break
            await asyncio.sleep(self.config.off_poll_seconds)
        return self._reading(False, settings, health, problem or still_on_words(settings, health))

    def _reading(
        self,
        off: bool,
        settings: EndpointSettings | None,
        health: EndpointHealth | None,
        reason: str | None,
    ) -> OffReading:
        return OffReading(
            endpoint_id=self.endpoint_id,
            off=off,
            workers_max=settings.workers_max if settings else None,
            running=health.running if health else None,
            in_progress=health.in_progress if health else None,
            in_queue=health.in_queue if health else None,
            idle=health.idle if health else None,
            reason_ro=reason,
            read_at=utc_now(),
        )
