"""The AMN batch handler: one RunPod job = one batch of stills or clips (``amn.batch.v1``).

It replaces worker-comfyui's stock handler. Per item, in index order:

1. reuse - the item's manifest and its object are already in the bucket: answer them again
   with a fresh presigned URL, ComfyUI untouched (an uncertain /run re-sent with the same keys
   is a free reuse, never a second generation);
2. time guard - not enough of ``time_budget_seconds`` left for one more item: SKIPPED_TIME
   (checked before the claim, so a skipped item never leaves a claim behind);
3. claim - ``claims/<key>.json`` written with ``If-None-Match: *``; a claim of another job
   younger than the time budget means CLAIMED_ELSEWHERE; an older one, a released one or our
   own job's (RunPod retried it) is taken over. A store without conditional PUT falls back to
   HEAD then PUT, which is safe only because the endpoint runs one worker (workers.max=1);
4. generate - inputs downloaded and sha256-checked, the workflow template filled through its
   ``bindings``, queued on the local ComfyUI, the declared Save node's file read;
5. deliver - exact size (postprocess), sha256, upload to ``outputs/<key>.<ext>``, then the
   manifest ``manifests/<key>.json`` (the item result plus ``created_at``; written last, so a
   manifest always names a complete object).

One item's failure is that item's FAILED with an error code (its claim is released) and the
batch goes on. ComfyUI unreachable fails the remaining items ``COMFY_DOWN``. A contract error
raises: RunPod marks the job FAILED and nothing was touched.

``runpod`` and ``boto3`` are imported lazily (in :func:`main` and ``S3Storage.from_env``):
the studio's environment has neither and imports ``runpod_worker.contract`` only.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from runpod_worker import postprocess
from runpod_worker.comfy import ComfyClient, ComfyFailed, ComfyUnavailable
from runpod_worker.contract import (
    CLIP_FPS,
    CONTRACT,
    BatchInput,
    BatchItem,
    BatchOutput,
    ContractError,
    InputRef,
    ItemResult,
    claim_key,
    manifest_key,
    output_key,
    validate_input,
    validate_item_result,
)
from runpod_worker.storage import (
    ConditionalPutUnsupported,
    PreconditionFailed,
    S3Storage,
    StorageError,
)

logger = logging.getLogger("amn.worker")

WORKFLOW_DIR = Path(__file__).resolve().parent / "workflows"
#: Seconds one item may take, by operation; mirrors the studio's still_item_budget_seconds and
#: clip_item_budget_seconds (the studio sizes time_budget_seconds from the same figures).
ITEM_BUDGET_SECONDS = {"image": 180.0, "video": 900.0}
#: The longest the handler waits for its ComfyUI to answer at the start of a job.
READY_SECONDS = 600.0
#: Kept back from the time budget for the encode and the upload after ComfyUI finished.
FINISH_MARGIN_SECONDS = 30.0
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}

#: Wall time for claims (they are compared across workers, so not monotonic). A test sets it.
wall_clock: Callable[[], float] = time.time
#: runpod.serverless.progress_update once main() runs; best-effort, never fails a job.
PROGRESS: Callable[[dict[str, Any], str], None] | None = None


class StoragePort(Protocol):
    def head(self, key: str) -> bool: ...

    def get_json(self, key: str) -> dict[str, Any] | None: ...

    def put_bytes(
        self, key: str, data: bytes, mime: str, *, if_none_match: bool = False
    ) -> None: ...

    def presign_get(self, key: str, ttl: int) -> str: ...

    def download_url(self, url: str) -> bytes: ...


class ComfyPort(Protocol):
    def wait_ready(self, timeout: float) -> float: ...

    def upload_input(self, name: str, data: bytes) -> str: ...

    def queue(self, graph: dict[str, Any]) -> str: ...

    def wait(self, prompt_id: str, timeout: float) -> dict[str, Any]: ...

    def output_path(self, history: dict[str, Any], node_id: str) -> Path: ...


class ItemFailed(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------------- workflows

BindingPath = tuple[str, str, str]


@dataclass(frozen=True)
class Workflow:
    name: str
    model: str
    operation: str
    output_node: str
    bindings: dict[str, list[BindingPath]]
    frames: dict[str, int] | None
    graph: dict[str, Any]


def _paths(name: str, raw: object) -> list[BindingPath]:
    # A binding is one [node, "inputs", field] or a list of them (e.g. both samplers' seeds).
    if isinstance(raw, list) and raw and all(isinstance(part, str) for part in raw):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"binding {name} must be a path or a list of paths")
    paths: list[BindingPath] = []
    for path in raw:
        if not (isinstance(path, list) and len(path) == 3 and path[1] == "inputs"):
            raise ValueError(f"binding {name} must look like [node, 'inputs', field]")
        paths.append((str(path[0]), "inputs", str(path[2])))
    return paths


@functools.cache
def load_workflow(name: str) -> Workflow:
    """A template from workflows/, with every binding checked against its graph."""
    raw = json.loads((WORKFLOW_DIR / f"{name}.json").read_text(encoding="utf-8"))
    graph = raw["graph"]
    bindings = {key: _paths(key, value) for key, value in raw["bindings"].items()}
    for key, paths in bindings.items():
        for node, _, field_name in paths:
            if node not in graph or field_name not in graph[node].get("inputs", {}):
                raise ValueError(f"{name}: binding {key} points at a missing input")
    if raw["output_node"] not in graph:
        raise ValueError(f"{name}: output node missing")
    frames = raw.get("frames")
    return Workflow(
        name=str(raw["name"]),
        model=str(raw["model"]),
        operation=str(raw["operation"]),
        output_node=str(raw["output_node"]),
        bindings=bindings,
        frames={str(k): int(v) for k, v in frames.items()} if frames else None,
        graph=graph,
    )


def frame_count(duration: float, rule: Mapping[str, int]) -> int:
    """Frames for ``duration`` seconds at the model's own rate, the first count ≥ duration×fps
    + 1 that the model accepts (LTX: 8k+1; Wan: 4k+1)."""
    frames = round(duration * rule["fps"]) + 1
    while frames % rule["multiple"] != rule["remainder"] % rule["multiple"]:
        frames += 1
    return frames


def bind(workflow: Workflow, values: Mapping[str, Any]) -> dict[str, Any]:
    graph = copy.deepcopy(workflow.graph)
    for key, value in values.items():
        for node, _, field_name in workflow.bindings.get(key, []):
            graph[node]["inputs"][field_name] = value
    return graph


# ------------------------------------------------------------------------------------ the job


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class _Batch:
    def __init__(
        self,
        job_id: str,
        batch: BatchInput,
        comfy: ComfyPort,
        storage: StoragePort,
        clock: Callable[[], float],
    ) -> None:
        self.job_id = job_id
        self.batch = batch
        self.comfy = comfy
        self.storage = storage
        self.clock = clock
        self.started = clock()
        self.prefix = batch["output"]["prefix"]
        self.ttl = batch["output"]["url_ttl_seconds"]
        self.operation = batch["operation"]
        self.comfy_ready = False
        self.comfy_down = False
        self.model_load_seconds = 0.0
        self.slowest = 0.0
        #: True once a prompt finished on ComfyUI: the models are loaded. The first prompt
        #: loads them lazily, a time the studio budgets apart as cold_start_seconds.
        self.models_warm = False

    def elapsed(self) -> float:
        return self.clock() - self.started

    def _base(self, item: BatchItem) -> ItemResult:
        return {
            "index": item["index"],
            "idempotency_key": item["idempotency_key"],
            "model": item["model"],
            "seed": item["seed"],
            "url": None,
            "error": None,
            "reused": False,
            "provenance_boxes": [],
        }

    def _ended(self, item: BatchItem, status: str, error: str | None) -> ItemResult:
        result = self._base(item)
        result["status"] = status
        result["error"] = error
        return result

    # ------------------------------------------------------------------------------- steps

    def reuse(self, item: BatchItem) -> ItemResult | None:
        key = item["idempotency_key"]
        manifest = self.storage.get_json(manifest_key(self.prefix, key))
        if manifest is None:
            return None
        try:
            checked = validate_item_result(manifest, "manifest")
        except ContractError:
            return None
        if (
            checked["status"] != "COMPLETED"
            or checked["idempotency_key"] != key
            or checked.get("model") != item["model"]
            or not self.storage.head(checked["key"])
        ):
            return None
        result: ItemResult = dict(checked)  # type: ignore[assignment]
        result["index"] = item["index"]
        result["reused"] = True
        result["gpu_seconds"] = 0.0
        result["error"] = None
        result["url"] = self.storage.presign_get(checked["key"], self.ttl)
        return result

    def _claim_body(self, released: bool = False) -> bytes:
        return json.dumps(
            {
                "job_id": self.job_id,
                "batch_key": self.batch["batch_key"],
                "claimed_at": wall_clock(),
                "released": released,
            }
        ).encode()

    def _held_elsewhere(self, claim: Mapping[str, Any]) -> bool:
        claimed_at = claim.get("claimed_at")
        if claim.get("released") is True or claim.get("job_id") == self.job_id:
            return False
        if isinstance(claimed_at, bool) or not isinstance(claimed_at, (int, float)):
            return False  # unreadable: never blocks a paid item
        return wall_clock() - float(claimed_at) < self.batch["time_budget_seconds"]

    def claim(self, item: BatchItem) -> bool:
        key = claim_key(self.prefix, item["idempotency_key"])
        body = self._claim_body()
        try:
            self.storage.put_bytes(key, body, "application/json", if_none_match=True)
            return True
        except PreconditionFailed:
            existing = self.storage.get_json(key)
        except ConditionalPutUnsupported:
            # HEAD then PUT is not atomic; safe only while the endpoint runs one worker.
            existing = self.storage.get_json(key) if self.storage.head(key) else None
        if existing is not None and self._held_elsewhere(existing):
            return False
        self.storage.put_bytes(key, body, "application/json")
        return True

    def release(self, item: BatchItem) -> None:
        key = claim_key(self.prefix, item["idempotency_key"])
        try:
            self.storage.put_bytes(key, self._claim_body(released=True), "application/json")
        except StorageError:
            logger.warning("claim_release_failed", extra={"index": item["index"]})

    def ensure_comfy(self) -> None:
        if self.comfy_down:
            raise ItemFailed("COMFY_DOWN")
        if self.comfy_ready:
            return
        left = self.batch["time_budget_seconds"] - self.elapsed()
        try:
            self.model_load_seconds += self.comfy.wait_ready(max(1.0, min(READY_SECONDS, left)))
        except ComfyUnavailable as exc:
            self.comfy_down = True
            raise ItemFailed("COMFY_DOWN") from exc
        self.comfy_ready = True

    def fetch_input(self, ref: InputRef) -> str:
        try:
            data = self.storage.download_url(ref["url"])
        except StorageError as exc:
            raise ItemFailed("INPUT_DOWNLOAD_FAILED") from exc
        if hashlib.sha256(data).hexdigest() != ref["sha256"]:
            raise ItemFailed("INPUT_SHA256_MISMATCH")
        name = f"{ref['sha256']}.{EXTENSIONS.get(ref['mime'], 'png')}"
        return self.comfy.upload_input(name, data)

    def generate(self, item: BatchItem, started: float) -> ItemResult:
        try:
            workflow = load_workflow(item["workflow"])
        except (OSError, ValueError, KeyError) as exc:
            raise ItemFailed("WORKFLOW_INVALID") from exc
        self.ensure_comfy()
        key = item["idempotency_key"]
        values: dict[str, Any] = {
            "prompt": item["prompt"],
            "seed": item["seed"],
            "filename_prefix": f"amn/{key[:16]}",
        }
        if item.get("negative_prompt"):
            # Without one, the graph keeps its official template's own negative prompt.
            values["negative_prompt"] = item["negative_prompt"]
        if self.operation == "image":
            values["width"], values["height"] = item["width"], item["height"]
        references = item.get("reference_images") or []
        if references and "reference_image" in workflow.bindings:
            # Only a workflow that has a reference input receives one (none does yet).
            values["reference_image"] = self.fetch_input(references[0])
        if self.operation == "video":
            values["source_image"] = self.fetch_input(item["source_image"])
            if workflow.frames is None:
                raise ItemFailed("WORKFLOW_INVALID")
            values["duration_frames"] = frame_count(item["duration"], workflow.frames)
        prompt_id = self.comfy.queue(bind(workflow, values))
        left = self.batch["time_budget_seconds"] - self.elapsed() - FINISH_MARGIN_SECONDS
        history = self.comfy.wait(prompt_id, max(30.0, left))
        self.models_warm = True
        path = self.comfy.output_path(history, workflow.output_node)
        result = self._base(item)
        try:
            if self.operation == "image":
                still = postprocess.finish_still(path.read_bytes())
                data, mime, ext = still.data, "image/png", "png"
                result["width"], result["height"] = still.width, still.height
                result["duration"], result["fps"] = None, None
                result["provenance_boxes"] = still.provenance_boxes
            else:
                with tempfile.TemporaryDirectory(prefix="amn-clip-") as work:
                    clip = postprocess.finish_clip(path, Path(work) / "clip.mp4", item["duration"])
                data, mime, ext = clip.data, "video/mp4", "mp4"
                result["width"], result["height"] = clip.width, clip.height
                result["duration"], result["fps"] = clip.duration, CLIP_FPS
                result["provenance_boxes"] = clip.provenance_boxes
        except OSError as exc:
            raise ItemFailed("NO_OUTPUT") from exc
        except postprocess.PostprocessError as exc:
            raise ItemFailed("POSTPROCESS_FAILED") from exc
        key_out = output_key(self.prefix, key, ext)
        result["status"] = "COMPLETED"
        result["key"] = key_out
        result["sha256"] = hashlib.sha256(data).hexdigest()
        result["bytes"] = len(data)
        result["mime"] = mime
        try:
            self.storage.put_bytes(key_out, data, mime)
            result["gpu_seconds"] = round(self.clock() - started, 3)
            manifest = {**result, "url": None, "created_at": _now_iso()}
            self.storage.put_bytes(
                manifest_key(self.prefix, key), json.dumps(manifest).encode(), "application/json"
            )
            result["url"] = self.storage.presign_get(key_out, self.ttl)
        except StorageError as exc:
            raise ItemFailed("UPLOAD_FAILED") from exc
        try:
            path.unlink(missing_ok=True)  # the container disk is billed; the bucket keeps it
        except OSError:
            pass
        return result

    def run_item(self, item: BatchItem) -> ItemResult:
        try:
            reused = self.reuse(item)
        except StorageError:
            return self._ended(item, "FAILED", "STORAGE_FAILED")
        if reused is not None:
            return reused
        budget = max(ITEM_BUDGET_SECONDS[self.operation], self.slowest)
        if self.elapsed() + budget > self.batch["time_budget_seconds"]:
            return self._ended(item, "SKIPPED_TIME", "TIME_BUDGET")
        if self.comfy_down:
            return self._ended(item, "FAILED", "COMFY_DOWN")
        try:
            if not self.claim(item):
                return self._ended(item, "CLAIMED_ELSEWHERE", None)
        except StorageError:
            return self._ended(item, "FAILED", "STORAGE_FAILED")
        started = self.clock()
        warm = self.models_warm
        code: str
        try:
            return self.generate(item, started)
        except ItemFailed as exc:
            code = exc.code
        except ComfyUnavailable:
            self.comfy_down = True
            code = "COMFY_DOWN"
        except ComfyFailed as exc:
            code = exc.code
        except Exception as exc:  # one item never takes the batch down
            logger.exception("item_failed", extra={"index": item["index"]})
            code = "WORKER_ERROR" if not isinstance(exc, StorageError) else "STORAGE_FAILED"
        finally:
            if warm:
                # The time guard's yardstick is a warm item: the one that loaded the models
                # would otherwise skip items the studio priced and sent.
                self.slowest = max(self.slowest, self.clock() - started)
        self.release(item)
        return self._ended(item, "FAILED", code)


def _progress(job: dict[str, Any], message: str) -> None:
    if PROGRESS is None:
        return
    try:
        PROGRESS(job, message)
    except Exception:
        logger.debug("progress_update_failed")


def handler(
    job: dict[str, Any],
    *,
    comfy: ComfyPort | None = None,
    storage: StoragePort | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> BatchOutput:
    started = clock()
    batch = validate_input(job.get("input") if isinstance(job, Mapping) else None)
    job_id = str(job.get("id") or "local")
    run = _Batch(
        job_id,
        batch,
        comfy if comfy is not None else ComfyClient.from_env(),
        storage if storage is not None else S3Storage.from_env(),
        clock,
    )
    items = sorted(batch["items"], key=lambda item: item["index"])
    results: list[ItemResult] = []
    for item in items:
        results.append(run.run_item(item))
        _progress(job, f"{len(results)}/{len(items)}")
    handler_seconds = round(clock() - started, 3)
    logger.info(
        "batch_done",
        extra={
            "items": len(results),
            "completed": sum(1 for r in results if r.get("status") == "COMPLETED"),
            "seconds": handler_seconds,
        },
    )
    return {
        "contract": CONTRACT,
        "batch_key": batch["batch_key"],
        "items": results,
        "model_load_seconds": round(run.model_load_seconds, 3),
        "handler_seconds": handler_seconds,
        # The worker holds the GPU for the whole handler; billing adds start-up and idle tail.
        "gpu_seconds": handler_seconds,
    }


# ---------------------------------------------------------------------------- the entrypoint

_shared: dict[str, Any] = {}


def _entry(job: dict[str, Any]) -> BatchOutput:
    # One ComfyUI client and one bucket client per worker process; the bucket is built at
    # the first job, so missing secrets fail that job with a clear error, not a crash loop.
    if "comfy" not in _shared:
        _shared["comfy"] = ComfyClient.from_env()
    if "storage" not in _shared:
        _shared["storage"] = S3Storage.from_env()
    return handler(job, comfy=_shared["comfy"], storage=_shared["storage"])


def main() -> None:
    import runpod  # type: ignore[import-not-found,unused-ignore]

    from runpod_worker.comfy import start_server

    logging.basicConfig(level=os.environ.get("AMN_LOG_LEVEL", "INFO"))
    start_server()
    global PROGRESS
    PROGRESS = runpod.serverless.progress_update
    runpod.serverless.start({"handler": _entry})


if __name__ == "__main__":
    main()
