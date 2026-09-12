"""Runway video generation adapter.

Uses the documented REST API at https://docs.dev.runwayml.com/ (API version 2024-11-06):

  GET  /v1/organization     -> credit balance, and per-model tier limits and usage for this key
  POST /v1/text_to_video    -> a generation task from a prompt
  POST /v1/image_to_video   -> a generation task from a first frame and a prompt
  GET  /v1/tasks/{id}       -> task status and, once finished, the output URLs

Runway has no model-listing endpoint. The models this account may call are the keys of
``tier.models`` in the organization response. Which task endpoint each model serves, and the
ratios and durations it accepts, come from the vendor's published OpenAPI contract for the
same API version (``https://docs.dev.runwayml.com/openapi.json``). No model name, ratio or
duration is written in this file: a model the account gains or loses appears or disappears at
the next catalog refresh, and a model whose contract changed is generated with the new terms.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote, urlsplit

from app.providers.media_base import (
    ImageProvider,
    ImageResult,
    VideoGenerationResult,
    VideoProvider,
)
from app.providers.media_http import (
    MediaProviderError,
    MediaProviderNotConfigured,
    image_dimensions,
    request,
)

HOST = "api.dev.runwayml.com"
DOCS_HOST = "docs.dev.runwayml.com"
CONTRACT_PATH = "/openapi.json"
API_VERSION = "2024-11-06"

#: Task endpoints whose output is a video clip. Endpoint names are part of the API contract
#: (the paths above), not model names; a model serves a task only if the contract says so.
VIDEO_TASKS = ("text_to_video", "image_to_video", "video_to_video", "character_performance")
#: Task endpoints whose output is a still image.
IMAGE_TASKS = ("text_to_image",)
#: How long a still may take. Runway queues tasks; polling stops at the deadline, and a task
#: still running then is reported as such rather than waited for indefinitely.
IMAGE_DEADLINE_SECONDS = 240
IMAGE_POLL_SECONDS = 3.0

#: Runway task states -> the studio's VideoGenerationResult states.
TASK_STATES = {
    "PENDING": "PENDING",
    "THROTTLED": "PENDING",
    "RUNNING": "PROCESSING",
    "SUCCEEDED": "COMPLETED",
    "FAILED": "FAILED",
    "CANCELLED": "FAILED",
}


def _deref(spec: dict, node: Any) -> Any:
    """Follow ``$ref`` pointers in the document; a cycle or a bad pointer is a contract error."""
    for _ in range(32):
        if not isinstance(node, dict) or "$ref" not in node:
            return node
        cursor: Any = spec
        for part in str(node["$ref"]).lstrip("#/").split("/"):
            if not isinstance(cursor, dict) or part not in cursor:
                raise MediaProviderError("Runway's API contract has an unresolved reference")
            cursor = cursor[part]
        node = cursor
    raise MediaProviderError("Runway's API contract references itself without end")


def _branches(spec: dict, schema: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    """Yield every concrete request shape of a schema (its oneOf/anyOf alternatives)."""
    schema = _deref(spec, schema)
    if not isinstance(schema, dict) or depth > 8:
        return
    alternatives = [s for key in ("oneOf", "anyOf") for s in schema.get(key, [])]
    if alternatives:
        for alternative in alternatives:
            yield from _branches(spec, alternative, depth + 1)
        return
    if "allOf" in schema:
        merged: dict[str, Any] = {}
        for part in schema["allOf"]:
            for branch in _branches(spec, part, depth + 1):
                merged.update(branch.get("properties", {}))
        yield {"properties": merged}
        return
    if isinstance(schema.get("properties"), dict):
        yield schema


def _values(spec: dict, node: Any) -> list[Any]:
    node = _deref(spec, node)
    if not isinstance(node, dict):
        return []
    if "const" in node:
        return [node["const"]]
    if isinstance(node.get("enum"), list):
        return list(node["enum"])
    return [v for key in ("oneOf", "anyOf") for s in node.get(key, []) for v in _values(spec, s)]


def parse_model_contract(spec: Any) -> dict[str, dict[str, Any]]:
    """Which task endpoint accepts each model, and the ratios and durations it takes.

    Read from the OpenAPI document Runway publishes for the API version the adapter sends.
    Only single-segment ``/v1/{task}`` POST endpoints count as tasks; per model the result is
    ``{"tasks": [...], "ratios": {task: [...]}, "durations": {task: [...] | {"min","max"}}}``.
    """
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise MediaProviderError("Runway's API contract could not be read")
    contract: dict[str, dict[str, Any]] = {}
    for path, operations in spec["paths"].items():
        if not isinstance(path, str) or not path.startswith("/v1/") or path.count("/") != 2:
            continue
        post = operations.get("post") if isinstance(operations, dict) else None
        if not isinstance(post, dict):
            continue
        content = post.get("requestBody", {}).get("content", {}).get("application/json", {})
        if not isinstance(content, dict) or "schema" not in content:
            continue
        task = path[len("/v1/") :]
        for branch in _branches(spec, content["schema"]):
            properties = branch.get("properties", {})
            if not isinstance(properties, dict) or "model" not in properties:
                continue
            models = [m for m in _values(spec, properties["model"]) if isinstance(m, str) and m]
            if not models:
                continue
            ratios = [r for r in _values(spec, properties.get("ratio")) if isinstance(r, str)]
            duration_node = _deref(spec, properties.get("duration"))
            durations: Any = [d for d in _values(spec, duration_node) if isinstance(d, int | float)]
            if not durations and isinstance(duration_node, dict):
                bounds = {
                    key: duration_node[field]
                    for key, field in (("min", "minimum"), ("max", "maximum"))
                    if isinstance(duration_node.get(field), int | float)
                }
                durations = bounds or None
            # What the model must be given besides words. gen4_image_turbo lists
            # referenceImages as required: an editing model, not a text-to-image one, and a
            # studio that generates stills from a prompt alone cannot use it — a fact the
            # contract states per model, and the choice of a model has to read.
            required = branch.get("required")
            needs_references = isinstance(required, list) and "referenceImages" in required
            for model in models:
                entry = contract.setdefault(
                    model, {"tasks": [], "ratios": {}, "durations": {}, "needs_references": {}}
                )
                if task not in entry["tasks"]:
                    entry["tasks"].append(task)
                if ratios:
                    entry["ratios"][task] = sorted(set(ratios) | set(entry["ratios"].get(task, [])))
                if durations and task not in entry["durations"]:
                    entry["durations"][task] = durations
                entry.setdefault("needs_references", {})[task] = needs_references
    for entry in contract.values():
        entry["tasks"].sort()
    return contract


def pick_ratio(ratios: list[str] | None, aspect_ratio: str) -> str:
    """The contract ratio closest to the requested aspect ("9:16", "16:9", "1:1")."""
    if not ratios:
        raise MediaProviderError(
            "The ratios this Runway model accepts are not known; refresh the catalog first"
        )
    try:
        w, h = (float(part) for part in str(aspect_ratio).replace("x", ":").split(":", 1))
        wanted = w / h
    except (ValueError, ZeroDivisionError):
        raise MediaProviderError(f"Unrecognised aspect ratio {aspect_ratio!r}") from None
    scored = []
    for ratio in ratios:
        try:
            rw, rh = (float(part) for part in ratio.split(":", 1))
            scored.append((abs(rw / rh - wanted), ratio))
        except (ValueError, ZeroDivisionError):
            continue
    if not scored:
        raise MediaProviderError("The Runway contract lists no usable ratios for this model")
    return min(scored)[1]


def pick_duration(durations: Any, seconds: float) -> int:
    """The contract duration nearest to the request, or the request clamped to its bounds."""
    wanted = max(1, int(round(float(seconds))))
    if isinstance(durations, list) and durations:
        return int(min(durations, key=lambda d: (abs(float(d) - wanted), d)))
    if isinstance(durations, dict):
        low = durations.get("min")
        high = durations.get("max")
        if isinstance(low, int | float):
            wanted = max(wanted, int(low))
        if isinstance(high, int | float):
            wanted = min(wanted, int(high))
    return wanted


def _image_data_uri(image: bytes) -> str:
    if image[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif image[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise MediaProviderError("The first frame must be a PNG, JPEG or WebP image")
    return f"data:{mime};base64," + base64.b64encode(image).decode("ascii")


class _RunwayClient:
    """What every Runway adapter shares: the key, the model's contract, the task plumbing."""

    PROVIDER_NAME = "RUNWAY"
    ADAPTER_VERSION = "1.0.0"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        model_metadata: dict[str, Any] | None = None,
    ) -> None:
        if not api_key:
            raise MediaProviderNotConfigured("Runway needs an API key")
        self.api_key = api_key
        self.model = model or ""
        #: The discovered contract for `model` (tasks, ratios, durations), from the catalog.
        self.model_metadata: dict[str, Any] = dict(model_metadata or {})
        #: Set by list_models() when the account answered but the contract could not be read.
        self.capabilities_warning: str | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self.api_key,
            "X-Runway-Version": API_VERSION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _require_task(self, task: str) -> None:
        if not self.model:
            raise MediaProviderNotConfigured("Select a Runway model in Settings")
        tasks = self.model_metadata.get("tasks")
        if isinstance(tasks, list) and task not in tasks:
            raise MediaProviderError(
                f"Model {self.model} does not serve {task} according to Runway's contract"
            )

    def _ratio_for(self, task: str, aspect_ratio: str) -> str:
        ratios = self.model_metadata.get("ratios", {})
        return pick_ratio(ratios.get(task) if isinstance(ratios, dict) else None, aspect_ratio)

    async def _submit(self, task: str, body: dict[str, Any]) -> str:
        data, _, _ = await asyncio.to_thread(
            request,
            HOST,
            "POST",
            f"/v1/{task}",
            self._headers(),
            json.dumps(body).encode("utf-8"),
            timeout=60,
        )
        task_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(task_id, str) or not task_id:
            raise MediaProviderError("Runway did not return a task id")
        return task_id

    async def _task(self, job_id: str) -> dict[str, Any]:
        data, _, _ = await asyncio.to_thread(
            request, HOST, "GET", f"/v1/tasks/{quote(job_id, safe='')}", self._headers(), timeout=30
        )
        if not isinstance(data, dict) or not isinstance(data.get("status"), str):
            raise MediaProviderError("Runway did not return the task status")
        return data

    async def _download(self, url: str) -> tuple[bytes, str]:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            raise MediaProviderError("Runway returned an output that is not an HTTPS URL")
        path = parts.path + ("?" + parts.query if parts.query else "")
        _, payload, content_type = await asyncio.to_thread(
            request, parts.hostname, "GET", path, {}, timeout=120, expect_json=False
        )
        if not payload:
            raise MediaProviderError("Runway's output could not be downloaded")
        return payload, content_type


class RunwayImageAdapter(_RunwayClient, ImageProvider):
    """Stills through Runway's text_to_image task, with the model's contract for the ratio.

    A task is queued and polled; the still comes back as the bytes Runway served, measured
    from those bytes. A task that has not finished by the deadline raises — nothing invents
    a picture for a scene.
    """

    PROVIDER_NAME = "RUNWAY_IMAGES"

    async def health_check(self) -> dict[str, Any]:
        try:
            data, _, _ = await asyncio.to_thread(
                request, HOST, "GET", "/v1/organization", self._headers(), timeout=20
            )
        except MediaProviderError as exc:
            return {"status": "OFFLINE", "detail": str(exc), "code": exc.code}
        if not isinstance(data, dict) or not isinstance(data.get("tier"), dict):
            return {"status": "OFFLINE", "detail": "Runway did not describe the organization"}
        return {"status": "HEALTHY", "detail": ""}

    async def generate_image(
        self,
        prompt: str,
        *,
        width: int = 1080,
        height: int = 1920,
        style: str | None = None,
        seed: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ImageResult:
        task = "text_to_image"
        self._require_task(task)
        needs = self.model_metadata.get("needs_references", {})
        if isinstance(needs, dict) and needs.get(task):
            # Known from the contract before any call: gen4_image_turbo edits pictures it is
            # given and cannot draw one from words alone. Runway answered HTTP 400 to every
            # scene of a day before this was read.
            raise MediaProviderError(
                f"{self.model} needs reference images and cannot generate a still from a "
                "prompt alone; choose a text-to-image model in Settings",
                code="reference_images_required",
            )
        described = " ".join(f"{prompt} {style or ''}".split())[:1000]
        if not described:
            raise MediaProviderError("There is no prompt to generate an image from")
        body: dict[str, Any] = {
            "model": self.model,
            "promptText": described,
            "ratio": self._ratio_for(task, f"{width}:{height}"),
        }
        if isinstance(seed, int):
            body["seed"] = seed
        job_id = await self._submit(task, body)
        deadline = time.monotonic() + IMAGE_DEADLINE_SECONDS
        while True:
            data = await self._task(job_id)
            remote = data["status"]
            if remote == "SUCCEEDED":
                break
            if remote in ("FAILED", "CANCELLED"):
                code = data.get("failureCode")
                raise MediaProviderError(
                    f"Runway image task {remote.lower()}",
                    code=code if isinstance(code, str) else None,
                )
            if time.monotonic() >= deadline:
                raise MediaProviderError("Runway image task did not finish before the deadline")
            await asyncio.sleep(IMAGE_POLL_SECONDS)
        outputs = data.get("output")
        url = outputs[0] if isinstance(outputs, list) and outputs else None
        if not isinstance(url, str):
            raise MediaProviderError("Runway reported success without an output")
        image, content_type = await self._download(url)
        fmt, actual_width, actual_height = image_dimensions(image, content_type)
        return ImageResult(
            image_bytes=image,
            format=fmt,
            width=actual_width,
            height=actual_height,
            seed=seed if isinstance(seed, int) else None,
            prompt=described,
            raw_response={
                "provider": self.PROVIDER_NAME,
                "model": self.model,
                "task_id": job_id,
                "ratio": body["ratio"],
                "content_type": content_type,
                "bytes": len(image),
            },
        )


class RunwayVideoAdapter(_RunwayClient, VideoProvider):
    async def organization(self) -> dict[str, Any]:
        data, _, _ = await asyncio.to_thread(
            request, HOST, "GET", "/v1/organization", self._headers(), timeout=20
        )
        if not isinstance(data, dict) or not isinstance(data.get("tier"), dict):
            raise MediaProviderError("Runway did not describe the organization")
        return data

    async def health_check(self) -> dict[str, Any]:
        """Ask the API which organization this key belongs to. Reachability is never assumed."""
        try:
            data = await self.organization()
        except MediaProviderError as exc:
            return {
                "status": "OFFLINE",
                "detail": str(exc),
                "code": exc.code,
                "http_status": exc.http_status,
            }
        return {"status": "HEALTHY", "detail": "", "credit_balance": data.get("creditBalance")}

    async def model_contract(self) -> dict[str, dict[str, Any]]:
        data, _, _ = await asyncio.to_thread(
            request, DOCS_HOST, "GET", CONTRACT_PATH, {"Accept": "application/json"}, timeout=30
        )
        return parse_model_contract(data)

    async def list_models(self) -> list[dict[str, Any]]:
        """The models this organization may call, with their limits, usage and contract."""
        data = await self.organization()
        tier_models = data["tier"].get("models")
        if not isinstance(tier_models, dict):
            raise MediaProviderError("Runway did not return the organization's model limits")
        usage = data["usage"].get("models", {}) if isinstance(data.get("usage"), dict) else {}
        try:
            contract = await self.model_contract()
            self.capabilities_warning = None
        except MediaProviderError:
            contract = {}
            self.capabilities_warning = (
                "Contractul API Runway nu a putut fi citit, așa că sarcinile și formatele "
                "modelelor nu sunt cunoscute încă; reîncearcă actualizarea mai târziu."
            )
        items: list[dict[str, Any]] = []
        for model_id, limits in tier_models.items():
            if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 200:
                raise MediaProviderError("Runway returned a model without a valid ID")
            limits = limits if isinstance(limits, dict) else {}
            used = usage.get(model_id) if isinstance(usage, dict) else None
            item: dict[str, Any] = {
                "model_id": model_id,
                "name": model_id,
                "max_concurrent_generations": limits.get("maxConcurrentGenerations"),
                "max_daily_generations": limits.get("maxDailyGenerations"),
                "daily_generations": (
                    used.get("dailyGenerations") if isinstance(used, dict) else None
                ),
            }
            if model_id in contract:
                item.update(contract[model_id])
            items.append(item)
        return items

    async def create_generation(
        self,
        prompt: str,
        *,
        image_ref: bytes | None = None,
        duration_seconds: float = 4.0,
        aspect_ratio: str = "9:16",
        extra: dict[str, Any] | None = None,
    ) -> str:
        text = " ".join(str(prompt).split())[:1000]
        if not self.model:
            raise MediaProviderNotConfigured("Select a Runway video model in Settings")
        task = "image_to_video" if image_ref else "text_to_video"
        self._require_task(task)
        durations = self.model_metadata.get("durations", {})
        task_durations = durations.get(task) if isinstance(durations, dict) else None
        body: dict[str, Any] = {
            "model": self.model,
            "promptText": text,
            "ratio": self._ratio_for(task, aspect_ratio),
            "duration": pick_duration(task_durations, duration_seconds),
        }
        if not text and task == "text_to_video":
            raise MediaProviderError("There is no prompt text to generate a video from")
        if image_ref:
            body["promptImage"] = _image_data_uri(image_ref)
        if isinstance(extra, dict) and isinstance(extra.get("seed"), int):
            body["seed"] = extra["seed"]
        return await self._submit(task, body)

    async def get_generation_status(self, job_id: str) -> VideoGenerationResult:
        data = await self._task(job_id)
        remote = data["status"]
        status = TASK_STATES.get(remote)
        if status is None:
            raise MediaProviderError(f"Runway returned an unknown task state {remote!r}")
        raw = {
            "provider": self.PROVIDER_NAME,
            "model": self.model,
            "task_id": job_id,
            "task_status": remote,
            "failure_code": data.get("failureCode"),
        }
        video: bytes | None = None
        if status == "COMPLETED":
            outputs = data.get("output")
            url = outputs[0] if isinstance(outputs, list) and outputs else None
            if not isinstance(url, str):
                raise MediaProviderError("Runway reported success without an output")
            video, content_type = await self._download(url)
            raw["content_type"] = content_type
            raw["bytes"] = len(video)
        return VideoGenerationResult(
            job_id=job_id,
            status=status,
            video_bytes=video,
            # Not measured here: the assembler probes the file it writes, and a number derived
            # from the request would describe what was asked for, not what came back.
            duration_seconds=None,
            raw_response=raw,
        )
