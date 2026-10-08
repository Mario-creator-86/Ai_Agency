"""Local, asynchronous ComfyUI jobs. No cloud fallback and no implicit model downloads."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import http.client
import json
import math
import struct
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from app.providers.local_memory import MIN_START_BYTES, available_memory, watch_job
from app.providers.media_base import (
    ImageProvider,
    ImageResult,
    VideoGenerationResult,
    VideoProvider,
)
from app.providers.media_http import MAX_MEDIA_BYTES, MediaProviderError, TaskStillOpen

DEFAULT_MANIFEST = Path(__file__).resolve().parents[3] / "config" / "local_media.json"
LOCAL_SOURCE = "https://github.com/Comfy-Org/ComfyUI"


def local_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("ComfyUI trebuie să aibă o adresă HTTP locală, fără cale sau token.")
    host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    return f"http://{host}:{parsed.port or 8188}"


def _local_landscape(ratio: str) -> bool | None:
    """True for a 16:9 landscape ratio, False for 9:16 portrait, None for any other shape.

    The stills step asks for "1530:2720" — exactly 9:16, but spelled by its pixels: a ratio
    is read by its aspect, not by matching strings, or the local profile refused the Owner's
    picture before the GPU was ever asked (LOCAL_FORMAT, 2026-10-05)."""
    try:
        width, height = (int(part) for part in str(ratio).split(":"))
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    aspect = width / height
    if math.isclose(aspect, 9 / 16, abs_tol=0.01):
        return False
    if math.isclose(aspect, 16 / 9, abs_tol=0.01):
        return True
    return None


def _request(
    base: str,
    method: str,
    route: str,
    body: bytes | None = None,
    content_type: str = "application/json",
) -> bytes:
    parsed = urlsplit(local_url(base))
    connection = http.client.HTTPConnection(str(parsed.hostname), parsed.port, timeout=60)
    try:
        connection.request(method, route, body=body, headers={"Content-Type": content_type})
        response = connection.getresponse()
        payload = response.read(MAX_MEDIA_BYTES + 1)
        if len(payload) > MAX_MEDIA_BYTES:
            raise MediaProviderError("Răspuns ComfyUI prea mare", code="LOCAL_OUTPUT_LIMIT")
        if not 200 <= response.status < 300:
            # Do not follow redirects: pictures and prompts stay on this computer.
            raise MediaProviderError(
                "ComfyUI a refuzat cererea",
                http_status=response.status,
                code="LOCAL_HTTP_ERROR",
                unsent=response.status < 500,
            )
        return payload
    except (OSError, http.client.HTTPException) as exc:
        raise MediaProviderError(
            "ComfyUI nu răspunde. Verifică Studio local.",
            code="LOCAL_CONNECTION",
            unanswered=method == "POST",
        ) from exc
    finally:
        connection.close()


def load_manifest(path: str | Path | None = None) -> dict[str, Any]:
    manifest_path = Path(path or DEFAULT_MANIFEST).resolve()
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if raw.get("version") != 1 or not isinstance(raw.get("models"), list):
        raise ValueError("Manifest Studio local invalid")
    for model in raw["models"]:
        workflow = (manifest_path.parent / model["workflow"]).resolve()
        if not workflow.is_relative_to(manifest_path.parent):
            raise ValueError("Workflow-ul trebuie să rămână în folderul manifestului")
        content = workflow.read_bytes()
        if hashlib.sha256(content).hexdigest() != model["workflow_sha256"]:
            raise ValueError("Workflow local modificat: verifică-l înainte de utilizare")
        model["graph"] = json.loads(content)
    return raw


class ComfyConnection:
    provider_name = "comfyui"
    billing_mode = "local"
    last_estimated_credits = 0.0

    def __init__(self, config: dict[str, Any], model: str | None = None) -> None:
        self.base_url = local_url(str(config.get("base_url") or "http://127.0.0.1:8188"))
        self.manifest = load_manifest(config.get("manifest_path"))
        self.model = model or ""
        self.poll_seconds = float(self.manifest.get("poll_seconds", 2))
        self.timeout_seconds = float(self.manifest.get("timeout_seconds", 21600))

    async def _json(self, method: str, route: str, data: Any = None) -> Any:
        body = json.dumps(data).encode() if data is not None else None
        return json.loads(await asyncio.to_thread(_request, self.base_url, method, route, body))

    def profile(self) -> dict[str, Any]:
        found = next((m for m in self.manifest["models"] if m["model_id"] == self.model), None)
        if found is None:
            raise MediaProviderError("Profil local necunoscut", code="LOCAL_MODEL", unsent=True)
        return found

    async def health_check(self) -> dict[str, Any]:
        await self._json("GET", "/system_stats")
        return {"status": "HEALTHY", "billing_mode": "local"}

    async def list_models(self) -> list[dict[str, Any]]:
        nodes = await self._json("GET", "/object_info")
        found = []
        for model in self.manifest["models"]:
            graph = model["graph"]
            available = all(node["class_type"] in nodes for node in graph.values())
            for node in graph.values():
                required = nodes.get(node["class_type"], {}).get("input", {}).get("required", {})
                for field, value in node["inputs"].items():
                    spec = required.get(field)
                    if spec and isinstance(spec[0], list) and not isinstance(value, list):
                        available = available and value in spec[0]
            if not available:
                continue
            task = "text_to_image" if model["purpose"] == "image" else "image_to_video"
            found.append(
                {k: v for k, v in model.items() if k != "graph"}
                | {
                    "tasks": [task],
                    "local_generation": True,
                    "native_resolution": [model["width"], model["height"]],
                    "ratios": {task: [f"{model['width']}:{model['height']}"]},
                    "durations": {task: {"min": 1, "max": model.get("max_seconds", 4)}},
                }
            )
        return found

    async def _submit(self, graph: dict[str, Any], operation: str) -> str:
        free = available_memory()
        if free is not None and free < MIN_START_BYTES:
            raise MediaProviderError(
                "Studio local așteaptă cel puțin 8 GB RAM liberi.",
                code="LOCAL_LOW_RAM",
                unsent=True,
            )
        queue = await self._json("GET", "/queue")
        if queue.get("queue_running") or queue.get("queue_pending"):
            raise MediaProviderError(
                "Studio local este ocupat. Așteaptă lucrarea curentă.",
                code="LOCAL_BUSY",
                unsent=True,
            )
        # Comfy's prompt_id is chosen before sending: an ambiguous response can be recovered
        # by that ID, instead of submitting the same GPU job again.
        prompt_id = str(uuid4())
        try:
            result = await self._json(
                "POST",
                "/prompt",
                {
                    "prompt": graph,
                    "prompt_id": prompt_id,
                    "client_id": "amn-ai",
                    "extra_data": {"studio_operation": operation, "studio_model": self.model},
                },
            )
        except MediaProviderError as exc:
            if exc.unanswered:
                raise TaskStillOpen(
                    "Trimitere locală neconfirmată; verifică lucrarea existentă.",
                    task_id=prompt_id,
                    code="LOCAL_UNCONFIRMED",
                ) from exc
            raise
        if not result.get("prompt_id") or result.get("node_errors"):
            raise MediaProviderError("Workflow refuzat de ComfyUI", code="LOCAL_WORKFLOW")
        accepted_id = str(result["prompt_id"])
        watch_job(
            accepted_id,
            lambda: json.loads(_request(self.base_url, "GET", f"/history/{accepted_id}")),
            lambda: _request(
                self.base_url, "POST", "/interrupt", json.dumps({"prompt_id": accepted_id}).encode()
            ),
            self.timeout_seconds,
        )
        return accepted_id

    async def collect_task(self, task_id: str) -> dict[str, Any]:
        # UUID only, never interpolate an arbitrary supplied path into the local API.
        from uuid import UUID

        UUID(task_id)
        history = await self._json("GET", f"/history/{task_id}")
        entry = history.get(task_id)
        if not entry:
            return {
                "state": "RUNNING",
                "status": "RUNNING",
                "outputs": [],
                "images": [],
                "video_bytes": None,
            }
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            return {
                "state": "FAILED",
                "status": "FAILED",
                "outputs": [],
                "images": [],
                "video_bytes": None,
                "failure_code": "LOCAL_GENERATION_FAILED",
                "failure_detail": "Generarea locală a eșuat. Consultă jurnalul ComfyUI.",
            }
        if not status.get("completed"):
            return {
                "state": "RUNNING",
                "status": "RUNNING",
                "outputs": [],
                "images": [],
                "video_bytes": None,
            }
        images, videos = [], []
        for output in entry.get("outputs", {}).values():
            for key in ("images", "video", "gifs"):
                for file in output.get(key, []):
                    query = urlencode(
                        {k: file[k] for k in ("filename", "subfolder", "type") if k in file}
                    )
                    data = await asyncio.to_thread(_request, self.base_url, "GET", "/view?" + query)
                    if str(file.get("filename", "")).lower().endswith((".mp4", ".webm")):
                        videos.append(data)
                    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
                        width, height = struct.unpack(">II", data[16:24])
                        images.append(
                            ImageResult(
                                image_bytes=data,
                                format="png",
                                width=width,
                                height=height,
                                cost_vr="0",
                                raw_response={"task_id": task_id, "provider": "comfyui"},
                            )
                        )
        if not images and not videos:
            raise MediaProviderError(
                "ComfyUI a terminat fără fișier utilizabil", code="LOCAL_EMPTY"
            )
        return {
            "state": "SUCCEEDED",
            "status": "SUCCEEDED",
            "images": images,
            "outputs": [(im.image_bytes, "image/png") for im in images]
            + [(video, "video/mp4") for video in videos],
            "video_bytes": videos[0] if videos else None,
            "raw_response": {"task_id": task_id, "provider": "comfyui", "api_cost_usd": 0},
        }

    async def _wait(self, task_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            try:
                result = await self.collect_task(task_id)
            except MediaProviderError as exc:
                if exc.code in ("LOCAL_GENERATION_FAILED", "LOCAL_EMPTY"):
                    raise
                raise TaskStillOpen(
                    "Lucrarea locală poate fi recuperată după reconectare.", task_id=task_id
                ) from exc
            if result["status"] == "SUCCEEDED":
                return result
            if result["status"] == "FAILED":
                raise MediaProviderError(result["failure_detail"], code=result["failure_code"])
            await asyncio.sleep(self.poll_seconds)
        raise TaskStillOpen(
            "Generarea locală continuă; rezultatul va fi recuperat ulterior.", task_id=task_id
        )


class ComfyImageAdapter(ComfyConnection, ImageProvider):
    PROVIDER_NAME = "COMFYUI_IMAGES"
    supports_reference_image = False

    async def generate_image(
        self,
        prompt: str,
        *,
        width: int = 1080,
        height: int = 1920,
        style: str | None = None,
        seed: int | None = None,
        extra: dict | None = None,
    ) -> ImageResult:
        del style
        if extra and extra.get("reference_image"):
            raise MediaProviderError(
                "Profilul SDXL local nu fixează identitatea din referințe.",
                code="LOCAL_REFERENCE_UNSUPPORTED",
                unsent=True,
            )
        results = await self.generate_candidates(
            prompt, ratio=f"{width}:{height}", count=1, seed=seed
        )
        return results[0]

    async def generate_candidates(
        self,
        prompt: str,
        *,
        ratio: str,
        count: int,
        references: list[bytes] | None = None,
        on_submitted: Callable[[str], None] | None = None,
        seed: int | None = None,
    ) -> list[ImageResult]:
        if references:
            raise MediaProviderError(
                "Profilul local nu acceptă imagini de referință.",
                code="LOCAL_REFERENCE_UNSUPPORTED",
                unsent=True,
            )
        landscape = _local_landscape(ratio)
        if not 1 <= count <= 4 or landscape is None:
            raise MediaProviderError("Format local nesuportat", code="LOCAL_FORMAT", unsent=True)
        profile = self.profile()
        results = []
        for index in range(count):
            graph = copy.deepcopy(profile["graph"])
            graph["2"]["inputs"]["text"] = prompt
            width, height = profile["width"], profile["height"]
            if landscape:
                width, height = height, width
            graph["4"]["inputs"].update(width=width, height=height, batch_size=1)
            graph["5"]["inputs"]["seed"] = (
                seed if seed is not None else uuid4().int % 2**32
            ) + index
            graph["7"]["inputs"]["filename_prefix"] = f"AMN_AI/stills/{uuid4().hex}"
            task_id = await self._submit(graph, "image")
            if on_submitted:
                on_submitted(task_id)
            result = await self._wait(task_id)
            results.extend(result["images"])
        return results


class ComfyVideoAdapter(ComfyConnection, VideoProvider):
    PROVIDER_NAME = "COMFYUI_VIDEO"

    async def create_generation(
        self,
        prompt: str,
        *,
        image_ref: bytes | None = None,
        duration_seconds: float = 4,
        aspect_ratio: str = "9:16",
        extra: dict | None = None,
    ) -> str:
        profile = self.profile()
        if not image_ref or len(image_ref) > MAX_MEDIA_BYTES:
            raise MediaProviderError(
                "Video local necesită imaginea de început.",
                code="LOCAL_IMAGE_REQUIRED",
                unsent=True,
            )
        if (
            not math.isfinite(duration_seconds)
            or not 0 < duration_seconds <= profile["max_seconds"]
            or aspect_ratio not in ("9:16", "1080:1920", "16:9", "1920:1080")
        ):
            raise MediaProviderError(
                "Profilul testat acceptă cadre de cel mult 4 secunde.",
                code="LOCAL_DURATION",
                unsent=True,
            )
        boundary = uuid4().hex
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
            f'filename="amn-{uuid4().hex}.png"\r\nContent-Type: image/png\r\n\r\n'
        ).encode()
        body += image_ref + f"\r\n--{boundary}--\r\n".encode()
        uploaded = json.loads(
            await asyncio.to_thread(
                _request,
                self.base_url,
                "POST",
                "/upload/image",
                body,
                f"multipart/form-data; boundary={boundary}",
            )
        )
        graph = copy.deepcopy(profile["graph"])
        graph["1"]["inputs"]["image"] = str(uploaded["name"])
        inputs = graph["2"]["inputs"]
        inputs["prompt"] = prompt
        # Keep the tested full-context frame count. Assembly trims shorter scenes.
        if aspect_ratio in ("16:9", "1920:1080"):
            inputs["width"], inputs["height"] = inputs["height"], inputs["width"]
        if extra and isinstance(extra.get("seed"), int):
            inputs["seed"] = extra["seed"] % 2**32
        graph["4"]["inputs"]["filename_prefix"] = f"AMN_AI/video/{uuid4().hex}"
        return await self._submit(graph, "video")

    async def get_generation_status(self, job_id: str) -> VideoGenerationResult:
        result = await self.collect_task(job_id)
        return VideoGenerationResult(
            job_id=job_id,
            status="COMPLETED" if result["status"] == "SUCCEEDED" else result["status"],
            video_bytes=result["video_bytes"],
            cost_vr="0",
            raw_response=result.get("raw_response", {}),
        )
