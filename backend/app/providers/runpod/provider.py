from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from app.providers.media_http import MediaProviderError, TaskStillOpen, image_dimensions
from app.providers.runpod.client import RunPodClient, Transport
from app.providers.runpod.compute import ComputeControl
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.errors import (
    InfrastructureDisabled,
    RunPodDisabled,
    RunPodProtocolError,
    SubmissionUncertain,
)
from app.providers.runpod.jobs import GenerationJob, JobStore, now, target_identity
from app.providers.runpod.mock import MockRunPodClient
from app.providers.runpod.models import (
    STATUSES,
    TERMINAL,
    FinalizeRequest,
    GenerationRequest,
    ImageRequest,
    VideoRequest,
)
from app.providers.runpod.telemetry import generation_metrics

logger = logging.getLogger("studio.runpod")
#: What a model row may carry into the catalogue (ProviderResource.api_metadata).
MODEL_FIELDS = frozenset(
    {
        "id",
        "name",
        "tasks",
        "purpose",
        "ratios",
        "durations",
        "max_seconds",
        "gpu_seconds_per_image",
        "gpu_seconds_per_video_second",
        "per_image_usd",
        "per_second_usd",
        "output",
        "native_resolution",
        "quality_score",
        "quality_source",
        "licence",
        "licence_url",
        "endpoint",
        "workflow",
    }
)
SERVERLESS_STATES = {"IN_QUEUE": "QUEUED", "IN_PROGRESS": "RUNNING", "TIMED_OUT": "TIMEOUT"}


class RunPodGenerationProvider:
    PROVIDER_NAME = "RUNPOD"

    def __init__(
        self,
        config: RunPodConfig,
        engine: Engine,
        *,
        transport: Transport | None = None,
        integration_id: str | None = None,
    ) -> None:
        self.config = config
        self.store = JobStore(engine)
        self.integration_id = integration_id
        self.transport = transport
        #: The adapter's media root (`RunPodConnection.storage_root`), for batch collection.
        self.media_root: Path | None = None
        self.target = target_identity(config, integration_id)
        self.client = (
            MockRunPodClient(self.store) if config.mock else RunPodClient(config, transport)
        )

    def require_enabled(self) -> None:
        if not self.config.configured:
            raise RunPodDisabled("RunPod is disabled or needs credentials and an endpoint")

    async def generate_image(self, request: ImageRequest) -> GenerationJob:
        return await self._submit("image", request)

    async def generate_video(self, request: VideoRequest) -> GenerationJob:
        return await self._submit("video", request)

    async def finalize_video(self, request: FinalizeRequest) -> GenerationJob:
        return await self._submit("finalize", request)

    async def _submit(self, operation: str, request: GenerationRequest) -> GenerationJob:
        self.require_enabled()
        if self.config.mode == "serverless" and not self.config.mock:
            # On Serverless a paid request is bought only as an item of a round (`batch`),
            # inside the step's GPU session (`gpu_session`): outside it workers.max is 0, so a
            # lone /run would wait in RunPod's queue and be served, and billed, by the next
            # step's worker; and the studio's worker reads amn.batch.v1 only. Nothing is sent.
            raise MediaProviderError(
                "RunPod Serverless buys only in rounds inside a GPU session",
                code="NEEDS_GPU_ROUND",
                unsent=True,
            )
        if request.mock_failure and not self.config.mock:
            raise RunPodProtocolError("Mock controls cannot be sent to a paid provider")
        payload = request.model_dump(mode="json", exclude_none=True)
        if not self.config.mock:
            payload.pop("mock_failure", None)
        payload["model"] = self.config.route(
            "image" if operation == "image" else "video", request.quality, request.model
        )
        if len(json.dumps(payload, allow_nan=False).encode()) > 10 * 1024 * 1024 - 1024:
            raise RunPodProtocolError("Cloud request exceeds 10 MB; reduce source images")
        row, fresh = self.store.reserve(operation, payload, self.config, self.integration_id)
        if not fresh:
            if not row.remote_job_id:
                raise SubmissionUncertain(
                    "Existing submit needs remote reconciliation; nothing was resubmitted"
                )
            return row
        if self.config.auto_start:
            try:
                await self.ensure_compute_available()
            except (MediaProviderError, TimeoutError) as exc:
                # No generation POST was made. Keep the creative key reusable.
                self.store.update(
                    row.id,
                    status="FAILED",
                    error_code="UNSENT",
                    finished_at=now(),
                    cost_value="0",
                    gpu_seconds_value="0",
                )
                raise MediaProviderError(
                    "Compute readiness failed before generation submission",
                    unsent=True,
                    code="COMPUTE_NOT_READY",
                ) from exc
        try:
            data = await self.client.submit(operation, payload, row.idempotency_key)
            remote = data.get("job_id", data.get("id"))
            if not isinstance(remote, str) or not remote or len(remote) > 100:
                raise RunPodProtocolError("RunPod did not return a valid job id")
            # Save the id BEFORE parsing any other field or invoking application callbacks.
            self.store.update(row.id, remote_job_id=remote)
            logger.info(
                "runpod_job_submitted",
                extra={
                    "job_id": row.id,
                    "operation": operation,
                    "attempt": row.attempt,
                    "mock": self.config.mock,
                },
            )
            return self._status(row.id, data, polled=False)
        except MediaProviderError as exc:
            saved = self.store.read(row.id, target=self.target)
            if not saved.remote_job_id and (
                exc.unsent
                or (exc.http_status in (400, 401, 403, 404, 413, 422) and not exc.unanswered)
            ):
                self.store.update(
                    row.id,
                    status="FAILED",
                    finished_at=now(),
                    error_code="UNSENT" if exc.unsent else f"HTTP_{exc.http_status}",
                    cost_value="0",
                    gpu_seconds_value="0",
                )
                raise
            self.store.update(row.id, error_code="SUBMISSION_UNCERTAIN")
            if isinstance(exc, RunPodProtocolError):
                raise
            raise SubmissionUncertain(
                "RunPod submit outcome is unknown; reconciliation required",
                http_status=exc.http_status,
                unanswered=True,
            ) from exc

    def _status(
        self, identifier: str, data: dict[str, Any], *, polled: bool = True
    ) -> GenerationJob:
        raw = data.get("status")
        state = SERVERLESS_STATES.get(str(raw), str(raw))
        if state not in STATUSES:
            raise RunPodProtocolError("RunPod returned an unknown job state")
        old = self.store.read(identifier, target=self.target)
        values: dict[str, Any] = {"status": state, "poll_count": old.poll_count + int(polled)}
        if state in ("RUNNING", "UPLOADING", "COMPLETED") and not old.started_at:
            values["started_at"] = now()
        if state in TERMINAL:
            values["finished_at"] = now()
        seconds = data.get("gpu_seconds")
        if (
            seconds is None
            and self.config.mode == "serverless"
            and data.get("executionTime") is not None
        ):
            try:
                seconds = Decimal(str(data["executionTime"])) / 1000
            except InvalidOperation as exc:
                raise RunPodProtocolError("RunPod returned invalid execution duration") from exc
        if seconds is not None:
            try:
                measured = Decimal(str(seconds))
                if not measured.is_finite() or measured < 0:
                    raise ValueError("invalid GPU duration")
            except (ValueError, InvalidOperation) as exc:
                raise RunPodProtocolError("RunPod returned invalid GPU duration") from exc
            values["gpu_seconds_value"] = str(measured)
            values["cost_value"] = str(
                Decimal(0) if self.config.mock else measured * Decimal(old.hourly_rate) / 3600
            )
        if isinstance(data.get("output"), dict):
            # Only the generation contract's output fields; never persist echoed request headers.
            values["output"] = {
                k: v
                for k, v in data["output"].items()
                if k in ("url", "image_url", "video_url", "model", "seed", "sha256")
            }
        selected_model = data.get("model") or values.get("output", {}).get("model")
        if selected_model:
            values["model"] = str(selected_model)[:100]
        if state in ("FAILED", "TIMEOUT", "CANCELLED"):
            values["error_code"] = state
        updated = self.store.update(identifier, **values)
        if old.status != updated.status:
            logger.info(
                "runpod_job_state",
                extra={"job_id": updated.id, "status": updated.status, "mock": self.config.mock},
            )
        return updated

    async def get_job(self, identifier: str) -> GenerationJob:
        self.require_enabled()
        row = self.store.read(identifier, target=self.target)
        if row.status in TERMINAL:
            return row
        if not row.remote_job_id:
            raise SubmissionUncertain("No verified remote id; reconcile the saved intent")
        if row.batch_remote_id:
            # One item of a batch job (amn.batch.v1): its manifest, then /status of the job.
            await self.collect_batch_item(row)
            return self.store.read(row.id, target=self.target)
        return self._status(row.id, await self.client.status(row.remote_job_id))

    async def collect_batch_item(
        self, row: GenerationJob, storage_root: Path | None = None
    ) -> None:
        """Collect one batch item (the watchdog's path after a restart, too)."""
        from app.providers.runpod.batch import collect_row  # noqa: PLC0415

        if self.config.mock:
            from app.providers.runpod.batch import BatchRun, SubmittedItem  # noqa: PLC0415

            run = BatchRun(
                config=self.config,
                engine=self.store.engine,
                integration_id=self.integration_id,
                storage_root=storage_root or self.storage_root(),
                transport=self.transport,
                session_id=row.gpu_session_id,
            )
            run.items.append(
                SubmittedItem(_stand_in(row), row.id, row.idempotency_key, row.remote_job_id)
            )
            run.poll()
            return
        endpoint = self.config.endpoint_for("video" if row.operation == "video" else "image")
        client = RunPodClient(
            self.config.model_copy(update={"mode": "serverless", "endpoint_id": endpoint}),
            self.transport,
        )
        await collect_row(
            self.config,
            self.store.engine,
            row,
            None,
            client=client,
            bucket=self.config.bucket(),
            storage_root=storage_root or self.storage_root(),
            transport=self.transport,
        )

    def storage_root(self) -> Path:
        """Where collected assets go: the adapter's media root, else the studio's."""
        if self.media_root is not None:
            return Path(self.media_root)
        from app.media.assembler import DEFAULT_STORAGE_ROOT  # noqa: PLC0415

        return Path(DEFAULT_STORAGE_ROOT)

    async def recover_submission(self, identifier: str, remote_id: str) -> GenerationJob:
        """Explicitly reconcile a lost submit only when the backend proves the saved key."""
        self.require_enabled()
        row = self.store.read(identifier, target=self.target)
        if row.remote_job_id:
            raise RunPodProtocolError("Submission already has a verified remote job id")
        if not remote_id or len(remote_id) > 100:
            raise RunPodProtocolError("Invalid remote job id")
        data = await self.client.status(remote_id)
        output = data.get("output")
        proof = data.get("idempotency_key") or (
            output.get("idempotency_key") if isinstance(output, dict) else None
        )
        if proof != row.idempotency_key:
            raise RunPodProtocolError(
                "Backend did not prove the remote job belongs to the saved intent"
            )
        self.store.update(row.id, remote_job_id=remote_id, error_code=None)
        return self._status(row.id, data)

    async def stop_if_idle(self) -> bool:
        """Optional hook for the existing scheduler; never installs another background loop."""
        from datetime import UTC, datetime, timedelta  # noqa: PLC0415

        from sqlalchemy import select  # noqa: PLC0415
        from sqlalchemy.orm import Session  # noqa: PLC0415

        if not self.config.auto_stop:
            return False
        cutoff = (
            datetime.now(UTC) - timedelta(minutes=self.config.idle_shutdown_minutes)
        ).isoformat()
        with Session(self.store.engine) as session:
            recent = session.scalar(
                select(GenerationJob.id).where(
                    GenerationJob.target == self.target,
                    (GenerationJob.status.not_in(TERMINAL)) | (GenerationJob.finished_at > cutoff),
                )
            )
        if recent:
            return False
        await self.stop_compute()
        return True

    async def wait(self, identifier: str) -> GenerationJob:
        async def poll() -> GenerationJob:
            while True:
                row = await self.get_job(identifier)
                if row.status in TERMINAL:
                    return row
                await asyncio.sleep(self.config.poll_interval)

        try:
            return await asyncio.wait_for(poll(), timeout=self.config.job_timeout)
        except TimeoutError as exc:
            row = self.store.read(identifier)
            raise TaskStillOpen(
                "RunPod job timed out locally and remains recoverable",
                task_id=str(row.remote_job_id or row.id),
            ) from exc

    async def cancel_job(self, identifier: str) -> GenerationJob:
        self.require_enabled()
        row = self.store.read(identifier, target=self.target)
        if row.status in TERMINAL:
            return row
        if not row.remote_job_id:
            raise SubmissionUncertain("Cannot cancel a job without its verified remote id")
        data = await self.client.cancel(row.remote_job_id)
        # A cancellation acknowledgement may still leave the worker in progress.
        return self._status(row.id, data)

    async def result_bytes(self, identifier: str) -> tuple[bytes, str]:
        self.require_enabled()
        row = self.store.read(identifier, target=self.target)
        if row.status != "COMPLETED":
            raise RunPodProtocolError("Only completed RunPod jobs have downloadable results")
        if row.batch_remote_id and not self.config.mock:
            # A batch item keeps its bucket key, never a signed URL: the studio signs a GET.
            from app.providers.runpod import s3  # noqa: PLC0415

            bucket = self.config.bucket()
            key = row.output.get("key")
            if bucket is None or not isinstance(key, str):
                raise RunPodProtocolError("RunPod batch result needs the bucket to be downloaded")
            content, kind = await self.client.download(s3.presign(bucket, "GET", key, 900))
            if hashlib.sha256(content).hexdigest() != row.output.get("sha256"):
                raise RunPodProtocolError("RunPod result checksum does not match")
            return content, str(row.output.get("mime") or kind)
        url = row.output.get("url") or row.output.get("image_url") or row.output.get("video_url")
        if not isinstance(url, str):
            raise RunPodProtocolError("RunPod completed without an output address")
        content, kind = await self.client.download(url)
        if row.operation == "image":
            image_dimensions(content, kind)
        elif kind != "video/mp4" or b"ftyp" not in content[:32]:
            raise RunPodProtocolError("RunPod result is not an MP4 file")
        expected = row.output.get("sha256")
        if expected and hashlib.sha256(content).hexdigest() != expected:
            raise RunPodProtocolError("RunPod result checksum does not match")
        return content, kind

    async def persist_result(self, identifier: str, storage_root: Path) -> Path:
        row = self.store.read(identifier, target=self.target)
        root = Path(storage_root).resolve()
        if row.asset_path:
            cached = Path(row.asset_path)
            if cached.resolve().is_relative_to(root) and cached.is_file():
                if hashlib.sha256(cached.read_bytes()).hexdigest() == row.asset_sha256:
                    return cached
        content, kind = await self.result_bytes(identifier)
        extension = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
            "video/mp4": "mp4",
        }.get(kind)
        if not extension:
            raise RunPodProtocolError("Unsupported cloud asset type")
        directory = root / "runpod"
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.resolve().is_relative_to(root):
            raise RunPodProtocolError("RunPod output folder escapes the media root")
        target = directory / (row.id + "." + extension)
        temporary = target.with_suffix(target.suffix + ".part")
        if target.is_symlink() or temporary.is_symlink():
            raise RunPodProtocolError("RunPod output destination is a link")
        temporary.write_bytes(content)
        temporary.replace(target)
        self.store.update(
            row.id, asset_path=str(target), asset_sha256=hashlib.sha256(content).hexdigest()
        )
        return target

    def record_quality(self, identifier: str, *, accepted: bool, reason: str = "") -> None:
        row = self.store.read(identifier, target=self.target)
        if row.status != "COMPLETED":
            raise RunPodProtocolError("QA cannot accept an unfinished generation")
        self.store.update(row.id, accepted=accepted, quality_result=reason[:4000])

    async def regenerate(self, identifier: str, feedback: list[str]) -> GenerationJob:
        row = self.store.read(identifier, target=self.target)
        if row.accepted is not False:
            raise RunPodProtocolError("Regeneration requires the existing QA's rejection")
        pictures = [*row.request.get("reference_images", []), row.request.get("source_image")]
        if row.batch_remote_id or any(isinstance(p, dict) for p in pictures):
            # The journal keeps pictures by digest only: the step that owns them buys again.
            raise RunPodProtocolError("Regeneration of this request belongs to its paid step")
        payload = {
            **row.request,
            "attempt_number": row.attempt + 1,
            "previous_seed": row.request.get("seed"),
            "previous_model": row.model,
            "qa_reason": "; ".join(feedback),
            "qa_feedback": feedback,
            "generation_history": [
                *row.request.get("generation_history", []),
                {
                    "job_id": row.id,
                    "model": row.model,
                    "seed": row.request.get("seed"),
                    "accepted": False,
                    "qa_reason": row.quality_result,
                },
            ],
        }
        request_models: dict[str, type[GenerationRequest]] = {
            "image": ImageRequest,
            "video": VideoRequest,
            "finalize": FinalizeRequest,
        }
        cls = request_models[row.operation]
        return await self._submit(row.operation, cls.model_validate(payload))

    async def health(self) -> dict[str, Any]:
        reading: dict[str, Any] = {
            "configured": self.config.configured,
            "enabled": self.config.enabled,
            "mock": self.config.mock,
            "authenticated": False,
            "endpoint_reachable": False,
            "cloud_backend_healthy": None,
            "gpu_backend_status": None,
        }
        if not self.config.configured:
            return reading
        if self.config.mode == "serverless" and not self.config.mock:
            return await self._serverless_health(reading)
        try:
            data = await self.client.health()
            reading.update(
                endpoint_reachable=True,
                authenticated=not self.config.mock
                and (self.config.mode == "serverless" or data.get("authenticated") is True),
                cloud_backend_healthy=data.get("status") in ("HEALTHY", "healthy", "ok"),
                gpu_backend_status=data.get("gpu_backend_status", data.get("workers")),
            )
            if self.config.mode == "serverless" and not self.config.mock:
                reading["cloud_backend_healthy"] = None
                if self.config.generation_base_url:
                    client = RunPodClient(
                        self.config.model_copy(update={"mode": "pod"}), self.transport
                    )
                    custom = await client.health()
                    reading["authenticated"] = custom.get("authenticated") is True
                    reading["cloud_backend_healthy"] = custom.get("status") in (
                        "HEALTHY",
                        "healthy",
                        "ok",
                    )
        except MediaProviderError as exc:
            reading.update(
                endpoint_reachable=exc.http_status is not None, http_status=exc.http_status
            )
        return reading

    async def _serverless_health(self, reading: dict[str, Any]) -> dict[str, Any]:
        """Serverless is verified without an always-on server and without /run: each
        configured endpoint read (GET settings + /health), min 0 (an always-on worker bills
        every second), its image the pinned one, and the output bucket configured. An endpoint
        scaled to zero is healthy: that is the Owner's normal OFF."""
        from app.providers.runpod.endpoint import (  # noqa: PLC0415
            EndpointAccessDenied,
            EndpointControl,
        )
        from app.providers.runpod.models import serverless_catalogue  # noqa: PLC0415

        pinned = serverless_catalogue().get("worker_images") or {}
        problems: list[str] = []
        endpoints: list[dict[str, Any]] = []
        for purpose, endpoint_id in self.config.endpoints():
            control = EndpointControl(self.config, endpoint_id, self.transport)
            try:
                settings = await control.get()
                health = await control.health()
            except EndpointAccessDenied as exc:
                reading.update(endpoint_reachable=True, http_status=exc.http_status)
                problems.append(
                    f"Cheia RunPod nu are acces la endpointul {endpoint_id} "
                    f"(HTTP {exc.http_status}); pune o cheie cu acces la Serverless."
                )
                continue
            except MediaProviderError as exc:
                reading["http_status"] = exc.http_status
                problems.append(f"Endpointul RunPod {endpoint_id} nu a putut fi citit.")
                continue
            reading.update(endpoint_reachable=True, authenticated=True)
            if settings.workers_min != 0:
                problems.append(
                    f"Endpointul {endpoint_id} ține {settings.workers_min} worker(i) porniți "
                    "mereu (min > 0) și se plătește fiecare secundă; pune min 0 în consola RunPod."
                )
            image = pinned.get("stills" if purpose == "image" else "motion")
            if image and settings.image != image:
                problems.append(
                    f"Endpointul {endpoint_id} rulează altă imagine decât cea fixată de studio."
                )
            endpoints.append(
                {
                    "purpose": purpose,
                    "endpoint_id": endpoint_id,
                    "workers_min": settings.workers_min,
                    "workers_max": settings.workers_max,
                    "idle_timeout": settings.idle_timeout,
                    "running": health.running,
                    "in_queue": health.in_queue,
                }
            )
        if self.config.bucket() is None:
            problems.append(
                "Bucketul de rezultate (S3 / Cloudflare R2) nu este configurat; RunPod păstrează "
                "un rezultat doar 30 de minute."
            )
        reading.update(
            cloud_backend_healthy=not problems and bool(endpoints),
            gpu_backend_status="SCALED_TO_ZERO"
            if endpoints and all(e["workers_max"] == 0 and e["running"] == 0 for e in endpoints)
            else "ON"
            if endpoints
            else None,
            endpoints=endpoints,
            problems_ro=problems,
        )
        return reading

    async def available_models(self) -> list[dict[str, Any]]:
        self.require_enabled()
        if self.config.mode == "serverless" and not self.config.mock:
            # The pinned catalogue, for the endpoints that exist: nothing is sent to RunPod
            # (a /run to discover models would start a paid worker).
            from app.providers.runpod.models import serverless_models  # noqa: PLC0415

            return [
                {k: v for k, v in row.items() if k in MODEL_FIELDS}
                for row in serverless_models(
                    {
                        "stills": bool(self.config.endpoint_for("image")),
                        "motion": bool(self.config.endpoint_for("video")),
                    }
                )
            ]
        data = await self.client.models()
        rows = data.get("models")
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not row.get("id") for row in rows
        ):
            raise RunPodProtocolError("RunPod did not return its model catalogue")
        return [{k: v for k, v in row.items() if k in MODEL_FIELDS} for row in rows]

    def metrics(self, project_id: str, *, finished: bool = False) -> dict[str, Any]:
        return generation_metrics(self.store.engine, project_id, finished=finished)

    async def get_compute_status(self) -> dict[str, Any]:
        resource = None
        if (
            self.config.enabled
            and not self.config.mock
            and self.config.pod_id
            and self.config.api_key.get_secret_value()
        ):
            resource = await ComputeControl(self.config, self.transport).status()
        return {
            "infrastructure_actions_enabled": self.config.allow_infra_actions,
            "auto_start": self.config.auto_start,
            "auto_stop": self.config.auto_stop,
            "pod": resource,
        }

    async def ensure_compute_available(self) -> None:
        await ComputeControl(self.config, self.transport).ensure()

    async def start_compute(self) -> dict[str, Any]:
        return await ComputeControl(self.config, self.transport).action("start")

    async def stop_compute(self) -> dict[str, Any]:
        from sqlalchemy import select  # noqa: PLC0415
        from sqlalchemy.orm import Session  # noqa: PLC0415

        with Session(self.store.engine) as session:
            active = session.scalar(
                select(GenerationJob.id).where(
                    GenerationJob.target == self.target, GenerationJob.status.not_in(TERMINAL)
                )
            )
        if active:
            raise InfrastructureDisabled("Cannot stop compute while a generation may be running")
        return await ComputeControl(self.config, self.transport).action("stop")


def _stand_in(row: GenerationJob) -> Any:
    from app.providers.runpod.batch import _request_of  # noqa: PLC0415

    return _request_of(row)
