"""Fit RunPod into the existing media interfaces and SceneTake collection protocol."""

from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.providers.media_base import (
    ImageProvider,
    ImageResult,
    VideoGenerationResult,
    VideoProvider,
)
from app.providers.media_http import MediaProviderError, TaskStillOpen, image_dimensions
from app.providers.runpod.batch import BatchRequest, BatchRun, SubmittedItem, submit_round
from app.providers.runpod.client import Transport
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.errors import RunPodProtocolError
from app.providers.runpod.jobs import GenerationJob
from app.providers.runpod.models import ImageRequest, VideoRequest, reference_spec
from app.providers.runpod.provider import RunPodGenerationProvider

if TYPE_CHECKING:
    from app.providers.runpod.gpu_session import GpuSession


def inline_image(content: bytes) -> str:
    if len(content) > 5 * 1024 * 1024:
        raise RunPodProtocolError("Source image exceeds the cloud request limit")
    if content.startswith(b"\x89PNG"):
        mime = "image/png"
    elif content.startswith(b"\xff\xd8"):
        mime = "image/jpeg"
    elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise RunPodProtocolError("Source image must be PNG, JPEG or WebP")
    return "data:" + mime + ";base64," + base64.b64encode(content).decode("ascii")


class RunPodConnection:
    PROVIDER_NAME = "RUNPOD"
    ADAPTER_VERSION = "1.0.0"
    billing_mode = "gpu"

    def __init__(
        self,
        config: RunPodConfig,
        engine: Engine,
        *,
        model: str | None = None,
        integration_id: str | None = None,
        storage_root: Path | None = None,
    ) -> None:
        self.core = RunPodGenerationProvider(config, engine, integration_id=integration_id)
        self.config = config
        self.model = model or "AUTO"
        self.integration_id = integration_id
        self.PROVIDER_NAME = "RUNPOD_MOCK" if config.mock else "RUNPOD"
        if storage_root is None:
            from app.media.assembler import DEFAULT_STORAGE_ROOT  # noqa: PLC0415

            storage_root = DEFAULT_STORAGE_ROOT
        self.storage_root = storage_root
        self.core.media_root = storage_root
        self.timeout_seconds = config.job_timeout
        self.context: dict[str, Any] = {}
        self.model_metadata = {
            "tasks": ["text_to_image", "image_to_video"],
            "needs_references": {"text_to_image": False},
        }
        self.last_estimated_credits: float | None = None
        self.capabilities_warning = (
            "MOCK: API cloud neautentificat, fișiere sintetice, fără GPU; exclus din PRODUCTION."
            if config.mock
            else None
        )

    def bind_scene(
        self, *, project_id: str, scene_id: str, operation: str, quality: str | None = None
    ) -> None:
        if operation == "video" and self.model == "AUTO":
            quality = quality or "AUTO"
        self.context = {
            "project_id": project_id,
            "scene_id": scene_id,
            "quality": quality
            or (
                "HERO"
                if self.model
                == self.config.model_routes.get(
                    "VIDEO_HERO" if operation == "video" else "IMAGE_HERO"
                )
                else "QUALITY"
            ),
        }

    def _request_context(
        self, operation: str, prompt: str, seed: int | None, candidate: int = 0
    ) -> dict[str, Any]:
        if not self.context:
            raise RunPodProtocolError("RunPod needs the existing film and scene identity")
        with Session(self.core.store.engine) as s:
            old = s.scalar(
                select(GenerationJob)
                .where(
                    GenerationJob.project_id == self.context["project_id"],
                    GenerationJob.scene_id == self.context["scene_id"],
                    GenerationJob.integration_id == self.integration_id,
                    GenerationJob.operation == operation,
                    GenerationJob.request["candidate_index"].as_integer() == candidate,
                )
                .order_by(GenerationJob.attempt.desc(), GenerationJob.created_at.desc())
            )
            context = {
                **self.context,
                "candidate_index": candidate,
                "attempt_number": 1,
                "original_prompt": prompt,
            }
            if old is not None:
                if old.status not in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
                    # A pending purchase is recovered, not replaced by a differently priced prompt.
                    context.update(
                        {
                            k: v
                            for k, v in old.request.items()
                            if k
                            in (
                                "attempt_number",
                                "original_prompt",
                                "previous_seed",
                                "previous_model",
                                "qa_reason",
                                "qa_feedback",
                                "generation_history",
                            )
                        }
                    )
                elif (
                    # A finished job is taken over only when nobody judged or collected it: a
                    # redo with no verdict never reuses a spent key (2026-10-08).
                    old.status == "COMPLETED"
                    and old.accepted is None
                    and not old.asset_path
                    and old.request.get("prompt") == prompt
                    and old.request.get("seed") == seed
                ):
                    context.update(
                        {
                            k: v
                            for k, v in old.request.items()
                            if k
                            in (
                                "attempt_number",
                                "original_prompt",
                                "previous_seed",
                                "previous_model",
                                "qa_reason",
                                "qa_feedback",
                                "generation_history",
                            )
                        }
                    )
                else:
                    context.update(
                        attempt_number=old.attempt + 1,
                        original_prompt=old.request.get("original_prompt") or old.request["prompt"],
                        previous_seed=old.request.get("seed"),
                        previous_model=old.model,
                        qa_reason=old.quality_result,
                        qa_feedback=[old.quality_result] if old.quality_result else [],
                        generation_history=[
                            *old.request.get("generation_history", []),
                            {
                                "job_id": old.id,
                                "seed": old.request.get("seed"),
                                "model": old.model,
                                "accepted": old.accepted,
                                "qa_reason": old.quality_result,
                            },
                        ],
                    )
        return context

    def supports_batch(self) -> bool:
        """A paid step buys in rounds of batches on RunPod Serverless (or its mock)."""
        return self.config.mode == "serverless" and self.config.configured

    def round_overhead_usd(self) -> Decimal:
        """What one round costs besides its items: the cold start (the models loading) and
        the idle tail, priced at the budget rate (`RunPodConfig.hourly_rate`)."""
        if self.config.mock:
            return Decimal(0)
        seconds = Decimal(self.config.cold_start_seconds + self.config.idle_timeout_seconds)
        return seconds * self.config.hourly_rate / 3600

    def submit_batch(
        self,
        requests: Sequence[BatchRequest],
        *,
        session: GpuSession,
        on_submitted: Callable[[SubmittedItem], None],
        transport: Transport | None = None,
    ) -> BatchRun:
        """One round as ONE batch job (or back-to-back chunks): `batch.submit_round`."""
        return submit_round(
            self.config,
            self.core.store.engine,
            requests,
            integration_id=self.integration_id,
            storage_root=self.storage_root,
            session=session,
            on_submitted=on_submitted,
            transport=transport or self.core.transport,
        )

    async def health_check(self) -> dict[str, Any]:
        reading = await self.core.health()
        return {
            **reading,
            "status": "HEALTHY"
            if reading["cloud_backend_healthy"] and (reading["authenticated"] or self.config.mock)
            else "NOT_CONFIGURED",
        }

    async def list_models(self) -> list[dict[str, Any]]:
        return [{**row, "model_id": row["id"]} for row in await self.core.available_models()]

    async def collect_task(self, task_id: str) -> dict[str, Any]:
        row = await self.core.get_job(task_id)
        result: dict[str, Any] = {
            "task_id": task_id,
            "task_status": row.status,
            "state": "SUCCEEDED"
            if row.status == "COMPLETED"
            else "FAILED"
            if row.status in ("FAILED", "TIMEOUT", "CANCELLED")
            else "RUNNING",
            "outputs": [],
            "failure_code": row.error_code,
            "failure_detail": None,
            "estimated_credits": None,
        }
        if row.status == "COMPLETED":
            path = await self.core.persist_result(row.id, self.storage_root)
            kind = (
                "video/mp4"
                if row.operation != "image"
                else {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}[path.suffix]
            )
            result["outputs"] = [(path.read_bytes(), kind)]
        return result

    def _raw(self, row: GenerationJob, path: Path) -> dict[str, Any]:
        return {
            "provider": self.PROVIDER_NAME,
            "task_id": row.remote_job_id,
            "job_id": row.id,
            "model": row.model,
            "asset_path": str(path),
            "mock": self.config.mock,
            "gpu_seconds": row.gpu_seconds,
            "estimated_cost_usd": str(row.estimated_cost_usd)
            if row.estimated_cost_usd is not None
            else None,
        }


class RunPodImageAdapter(RunPodConnection, ImageProvider):
    #: What a reference picture really did is proven by the Owner's paid test, never by the
    #: catalogue's declaration (the stills step reports such stills as unverified).
    REFERENCE_IMAGE_VERIFIED = False

    @property
    def ACCEPTS_REFERENCE_IMAGE(self) -> bool:  # noqa: N802 - the studio's capability name
        """True only when the selected model of config/runpod_models.json declares a
        reference binding (the 2511 route, 2026-10-09); every other model is handed none."""
        return reference_spec(self.model) is not None

    @property
    def MAX_REFERENCES(self) -> int:  # noqa: N802
        """How many pictures the selected model binds (0 when it takes none)."""
        spec = reference_spec(self.model)
        return int(spec.get("max") or 0) if spec else 0

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
        extras = extra or {}
        refs = extras.get("reference_images", [])
        reference = extras.get("reference_image")
        if isinstance(reference, dict) and isinstance(reference.get("bytes"), bytes):
            refs = [*refs, inline_image(reference["bytes"])]
        context = self._request_context("image", prompt, seed)
        return await self._image(
            ImageRequest(
                **context,
                prompt=prompt,
                width=width,
                height=height,
                style=style,
                seed=seed,
                model=self.model,
                reference_images=refs,
                negative_prompt=extras.get("negative_prompt"),
            )
        )

    async def _image(
        self, request: ImageRequest, on_submitted: Callable[[str], None] | None = None
    ) -> ImageResult:
        row = await self.core.generate_image(request)
        if on_submitted:
            on_submitted(str(row.remote_job_id))
        try:
            row = await self.core.wait(row.id)
            if row.status == "COMPLETED":
                path = await self.core.persist_result(row.id, self.storage_root)
        except (MediaProviderError, OSError) as exc:
            raise TaskStillOpen(
                "RunPod image has a saved remote job; collect it later",
                task_id=str(row.remote_job_id),
            ) from exc
        if row.status != "COMPLETED":
            raise MediaProviderError("RunPod image job did not complete", code=row.status)
        content = path.read_bytes()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}[path.suffix]
        fmt, w, h = image_dimensions(content, mime)
        return ImageResult(
            content,
            fmt,
            w,
            h,
            seed=request.seed,
            prompt=request.prompt,
            raw_response=self._raw(row, path),
        )

    async def generate_candidates(
        self,
        prompt: str,
        *,
        ratio: str,
        count: int,
        references: list[bytes] | None = None,
        on_submitted: Callable[[str], None] | None = None,
    ) -> list[ImageResult]:
        if not 1 <= count <= 8:
            raise RunPodProtocolError("Invalid RunPod image candidate count")
        w, h = map(int, ratio.split(":"))
        results = []
        for candidate in range(count):
            context = self._request_context("image", prompt, None, candidate)
            results.append(
                await self._image(
                    ImageRequest(
                        **context,
                        prompt=prompt,
                        width=w,
                        height=h,
                        model=self.model,
                        reference_images=[inline_image(b) for b in references or []],
                    ),
                    on_submitted,
                )
            )
        return results


class RunPodVideoAdapter(RunPodConnection, VideoProvider):
    async def create_generation(
        self,
        prompt: str,
        *,
        image_ref: bytes | None = None,
        duration_seconds: float = 4,
        aspect_ratio: str = "9:16",
        extra: dict[str, Any] | None = None,
    ) -> str:
        extras = extra or {}
        seed = extras.get("seed")
        context = self._request_context("video", prompt, seed)
        row = await self.core.generate_video(
            VideoRequest(
                **context,
                prompt=prompt,
                source_image=inline_image(image_ref) if image_ref else None,
                duration=duration_seconds,
                aspect_ratio=aspect_ratio,
                model=self.model,
                seed=seed,
                negative_prompt=extras.get("negative_prompt"),
                camera_motion=extras.get("camera_motion"),
                motion_strength=extras.get("motion_strength"),
                fps=extras.get("fps", 24),
            )
        )
        return str(row.remote_job_id)

    async def get_generation_status(self, job_id: str) -> VideoGenerationResult:
        row = await self.core.get_job(job_id)
        if row.status == "COMPLETED":
            path = await self.core.persist_result(row.id, self.storage_root)
            return VideoGenerationResult(
                job_id,
                "COMPLETED",
                video_bytes=path.read_bytes(),
                video_path=str(path),
                duration_seconds=float(row.request.get("duration", 5)),
                raw_response=self._raw(row, path),
            )
        status = "FAILED" if row.status in ("FAILED", "CANCELLED", "TIMEOUT") else "PROCESSING"
        return VideoGenerationResult(job_id, status, raw_response={"status": row.status})
