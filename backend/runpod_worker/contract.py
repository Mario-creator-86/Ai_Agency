"""The batch contract between the studio and the AMN RunPod worker: ``amn.batch.v1``.

Standard library only: the studio (``app.providers.runpod.batch``) and the worker image both
import this module, and the worker image has no studio code in it.

One RunPod job carries one batch: every item of one paid round (or one chunk of it), so the
models load once per round (Owner, 2026-10-08: «trebuie sa se opreasca imediat dupa, nu la 30
sec. Sunt taxat la secunda, deci trebuie oprit imediat dupa generare»). The job's ``input`` is
a :class:`BatchInput`; its ``output`` is a :class:`BatchOutput`. Every finished item is also
written to the bucket as ``manifests/<idempotency_key>.json`` (an :class:`ItemResult` plus
``created_at``), because RunPod keeps a /run result only 30 minutes
(https://docs.runpod.io/serverless/endpoints/operation-reference.md).

Inputs and outputs travel as presigned bucket URLs, never as base64 in the body (RunPod's /run
body limit is 10 MB, and the studio's journal must not hold the pictures).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any, NotRequired, TypedDict, cast
from urllib.parse import urlsplit

CONTRACT = "amn.batch.v1"
OPERATIONS = ("image", "video")
#: At most this many items in one job: a round larger than this is chunked by the studio.
MAX_ITEMS = 32
#: A still is delivered at exactly this size (9:16, ~2K): Qwen-Image-2512 then SeedVR2.
STILL_SIZE = (1530, 2720)
#: A clip is delivered at exactly this size and rate (H.264, yuv420p, no audio).
CLIP_SIZE = (1080, 1920)
CLIP_FPS = 24
ITEM_STATES = ("COMPLETED", "FAILED", "SKIPPED_TIME", "CLAIMED_ELSEWHERE")
#: model id -> (operation, workflow template name under runpod_worker/workflows/).
WORKFLOWS: dict[str, tuple[str, str]] = {
    "Qwen-Image-2512": ("image", "qwen_image_2512_seedvr2"),
    # The reference route for locked characters (Owner, 2026-10-09): 1-3 reference pictures.
    "Qwen-Image-Edit-2511": ("image", "qwen_image_edit_2511_ref_seedvr2"),
    "LTX-2.5": ("video", "ltx_2_5_i2v"),
    "Wan-2.2-LightX2V": ("video", "wan_2_2_i2v_lightx2v"),
}

MAX_PROMPT = 20000
MAX_REFERENCES = 8
MAX_SEED = 2**32 - 1
MIN_DURATION = 1
MAX_DURATION = 10
#: SigV4 presigned URLs live at most 7 days.
MAX_URL_TTL = 604800
#: A job never runs longer than RunPod's per-job executionTimeout; one day is a sanity bound.
MAX_TIME_BUDGET = 86400
INPUT_MIMES = ("image/png", "image/jpeg", "image/webp")
OUTPUT_MIMES = ("image/png", "video/mp4")
PREFIX_PATTERN = re.compile(r"^[a-z0-9][a-z0-9/_-]{0,100}/$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ID_MAX = 100


class InputRef(TypedDict):
    url: str
    sha256: str
    mime: str


class BatchItem(TypedDict, total=False):
    index: int
    idempotency_key: str
    model: str
    workflow: str
    project_id: str
    scene_id: str
    prompt: str
    negative_prompt: str | None
    seed: int
    width: int
    height: int
    reference_images: list[InputRef]
    source_image: InputRef
    duration: float
    fps: int


class OutputSpec(TypedDict):
    prefix: str
    url_ttl_seconds: int


class BatchInput(TypedDict):
    contract: str
    operation: str
    batch_key: str
    items: list[BatchItem]
    output: OutputSpec
    time_budget_seconds: int


class ItemResult(TypedDict, total=False):
    index: int
    idempotency_key: str
    status: str
    url: str | None
    key: str
    sha256: str
    bytes: int
    mime: str
    width: int
    height: int
    duration: float | None
    fps: int | None
    model: str
    seed: int
    gpu_seconds: float
    error: str | None
    reused: bool
    provenance_boxes: list[str]
    #: The weights snapshot the item was made with (the mirror's commit, or "baked"); the
    #: studio compares it with the mirror revision it expects. Absent from an old worker.
    weights_revision: str | None
    #: Seconds this item waited for the weights check and ComfyUI before its prompt (the
    #: first item of a worker carries them; the lazy GPU load is inside gpu_seconds).
    model_load_seconds: float


class BatchOutput(TypedDict):
    contract: str
    batch_key: str
    items: list[ItemResult]
    model_load_seconds: float
    handler_seconds: float
    gpu_seconds: float
    #: The worker's weights snapshot for the whole job (as on each item); absent from an old
    #: worker's output.
    weights_revision: NotRequired[str | None]


class ContractError(ValueError):
    """The job input or output does not follow ``amn.batch.v1``."""


# -------------------------------------------------------------------------------------- keys


def batch_key(keys: Iterable[str]) -> str:
    """The batch's identity: sha256 of its items' idempotency keys, sorted, one per line."""
    return hashlib.sha256("\n".join(sorted(keys)).encode("utf-8")).hexdigest()


def manifest_key(prefix: str, key: str) -> str:
    return f"{prefix}manifests/{key}.json"


def claim_key(prefix: str, key: str) -> str:
    return f"{prefix}claims/{key}.json"


def output_key(prefix: str, key: str, ext: str) -> str:
    return f"{prefix}outputs/{key}.{ext}"


def input_key(prefix: str, sha256: str, ext: str) -> str:
    return f"{prefix}inputs/{sha256}.{ext}"


# ------------------------------------------------------------------------------------ checks

_IMAGE_ITEM_KEYS = frozenset(
    {
        "index",
        "idempotency_key",
        "model",
        "workflow",
        "project_id",
        "scene_id",
        "prompt",
        "negative_prompt",
        "seed",
        "width",
        "height",
        "reference_images",
    }
)
_VIDEO_ITEM_KEYS = _IMAGE_ITEM_KEYS | {"source_image", "duration", "fps"}
_REQUIRED_ITEM_KEYS = frozenset(
    {"index", "idempotency_key", "model", "workflow", "project_id", "scene_id", "prompt", "seed"}
)
_INPUT_KEYS = frozenset(
    {"contract", "operation", "batch_key", "items", "output", "time_budget_seconds"}
)


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{where} must be an object")
    return cast(Mapping[str, Any], value)


def _int(value: object, where: str, low: int, high: int) -> int:
    # bool is an int in Python; a True seed or index is a bug upstream, never a number.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{where} must be an integer")
    if not low <= value <= high:
        raise ContractError(f"{where} must be between {low} and {high}")
    return value


def _number(value: object, where: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{where} must be a number")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ContractError(f"{where} must be between {low} and {high}")
    return number


def _text(value: object, where: str, low: int, high: int) -> str:
    if not isinstance(value, str) or not low <= len(value) <= high:
        raise ContractError(f"{where} must be text of {low}..{high} characters")
    return value


def _hex64(value: object, where: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ContractError(f"{where} must be 64 lowercase hex characters")
    return value


def _https(value: object, where: str) -> str:
    if not isinstance(value, str) or len(value) > 8192:
        raise ContractError(f"{where} must be an https URL")
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
    ):
        raise ContractError(f"{where} must be an https URL without credentials or fragment")
    return value


def _input_ref(value: object, where: str) -> InputRef:
    raw = _mapping(value, where)
    if set(raw) != {"url", "sha256", "mime"}:
        raise ContractError(f"{where} must have exactly url, sha256 and mime")
    mime = raw["mime"]
    if mime not in INPUT_MIMES:
        raise ContractError(f"{where}.mime must be one of {INPUT_MIMES}")
    return {
        "url": _https(raw["url"], f"{where}.url"),
        "sha256": _hex64(raw["sha256"], f"{where}.sha256"),
        "mime": str(mime),
    }


def _item(value: object, operation: str, where: str) -> BatchItem:
    raw = _mapping(value, where)
    allowed = _IMAGE_ITEM_KEYS if operation == "image" else _VIDEO_ITEM_KEYS
    unknown = set(raw) - allowed
    if unknown:
        raise ContractError(f"{where} has unknown fields: {sorted(unknown)}")
    missing = _REQUIRED_ITEM_KEYS - set(raw)
    if operation == "image":
        missing |= {"width", "height"} - set(raw)
    else:
        missing |= {"source_image", "duration"} - set(raw)
    if missing:
        raise ContractError(f"{where} is missing {sorted(missing)}")
    model = raw["model"]
    if model not in WORKFLOWS:
        raise ContractError(f"{where}.model is not a known model")
    model_operation, workflow = WORKFLOWS[str(model)]
    if model_operation != operation:
        raise ContractError(f"{where}.model {model} does not make {operation}")
    if raw["workflow"] != workflow:
        raise ContractError(f"{where}.workflow must be {workflow} for {model}")
    negative = raw.get("negative_prompt")
    if negative is not None:
        _text(negative, f"{where}.negative_prompt", 0, MAX_PROMPT)
    references_raw = raw.get("reference_images", [])
    if not isinstance(references_raw, list) or len(references_raw) > MAX_REFERENCES:
        raise ContractError(f"{where}.reference_images must be a list of at most 8")
    item: BatchItem = {
        "index": _int(raw["index"], f"{where}.index", 0, MAX_ITEMS - 1),
        "idempotency_key": _hex64(raw["idempotency_key"], f"{where}.idempotency_key"),
        "model": str(model),
        "workflow": workflow,
        "project_id": _text(raw["project_id"], f"{where}.project_id", 1, ID_MAX),
        "scene_id": _text(raw["scene_id"], f"{where}.scene_id", 1, ID_MAX),
        "prompt": _text(raw["prompt"], f"{where}.prompt", 1, MAX_PROMPT),
        "negative_prompt": negative,
        "seed": _int(raw["seed"], f"{where}.seed", 0, MAX_SEED),
        "reference_images": [
            _input_ref(ref, f"{where}.reference_images[{n}]")
            for n, ref in enumerate(references_raw)
        ],
    }
    if operation == "image":
        width = _int(raw["width"], f"{where}.width", 1, 16384)
        height = _int(raw["height"], f"{where}.height", 1, 16384)
        if (width, height) != STILL_SIZE:
            raise ContractError(f"{where} must be exactly {STILL_SIZE[0]}x{STILL_SIZE[1]}")
        item["width"], item["height"] = width, height
        return item
    if "width" in raw or "height" in raw:
        size = (raw.get("width"), raw.get("height"))
        if size != CLIP_SIZE:
            raise ContractError(f"{where} clip size must be {CLIP_SIZE[0]}x{CLIP_SIZE[1]}")
        item["width"], item["height"] = CLIP_SIZE
    item["source_image"] = _input_ref(raw["source_image"], f"{where}.source_image")
    item["duration"] = _number(raw["duration"], f"{where}.duration", MIN_DURATION, MAX_DURATION)
    item["fps"] = _int(raw.get("fps", CLIP_FPS), f"{where}.fps", CLIP_FPS, CLIP_FPS)
    return item


def validate_input(raw: object) -> BatchInput:
    """The job input, checked whole; raises :class:`ContractError` (the job then FAILS)."""
    body = _mapping(raw, "input")
    unknown = set(body) - _INPUT_KEYS
    if unknown:
        raise ContractError(f"input has unknown fields: {sorted(unknown)}")
    missing = _INPUT_KEYS - set(body)
    if missing:
        raise ContractError(f"input is missing {sorted(missing)}")
    if body["contract"] != CONTRACT:
        raise ContractError(f"input.contract must be {CONTRACT}")
    operation = body["operation"]
    if operation not in OPERATIONS:
        raise ContractError(f"input.operation must be one of {OPERATIONS}")
    key = _hex64(body["batch_key"], "input.batch_key")
    items_raw = body["items"]
    if not isinstance(items_raw, list) or not 1 <= len(items_raw) <= MAX_ITEMS:
        raise ContractError(f"input.items must hold 1..{MAX_ITEMS} items")
    items = [_item(raw_item, str(operation), f"items[{n}]") for n, raw_item in enumerate(items_raw)]
    if sorted(item["index"] for item in items) != list(range(len(items))):
        raise ContractError("item indexes must be unique and run 0..n-1")
    keys = [item["idempotency_key"] for item in items]
    if len(set(keys)) != len(keys):
        raise ContractError("item idempotency keys must be unique")
    if key != batch_key(keys):
        raise ContractError("input.batch_key must be batch_key(the items' idempotency keys)")
    out = _mapping(body["output"], "input.output")
    if set(out) != {"prefix", "url_ttl_seconds"}:
        raise ContractError("input.output must have exactly prefix and url_ttl_seconds")
    prefix = out["prefix"]
    if not isinstance(prefix, str) or not PREFIX_PATTERN.fullmatch(prefix) or ".." in prefix:
        raise ContractError("input.output.prefix must look like 'amn/'")
    return {
        "contract": CONTRACT,
        "operation": str(operation),
        "batch_key": key,
        "items": items,
        "output": {
            "prefix": prefix,
            "url_ttl_seconds": _int(
                out["url_ttl_seconds"], "input.output.url_ttl_seconds", 1, MAX_URL_TTL
            ),
        },
        "time_budget_seconds": _int(
            body["time_budget_seconds"], "input.time_budget_seconds", 1, MAX_TIME_BUDGET
        ),
    }


def validate_item_result(raw: object, where: str = "item") -> ItemResult:
    """One item of a job's output, or one bucket manifest (extra fields such as
    ``created_at`` are allowed: an old worker's manifest stays readable)."""
    body = _mapping(raw, where)
    status = body.get("status")
    if status not in ITEM_STATES:
        raise ContractError(f"{where}.status must be one of {ITEM_STATES}")
    result: ItemResult = {
        "index": _int(body.get("index"), f"{where}.index", 0, MAX_ITEMS - 1),
        "idempotency_key": _hex64(body.get("idempotency_key"), f"{where}.idempotency_key"),
        "status": str(status),
        "url": None,
        "error": None,
        "reused": False,
        "provenance_boxes": [],
    }
    url = body.get("url")
    if url is not None:
        result["url"] = _https(url, f"{where}.url")
    error = body.get("error")
    if error is not None:
        result["error"] = _text(error, f"{where}.error", 1, 200)
    reused = body.get("reused", False)
    if not isinstance(reused, bool):
        raise ContractError(f"{where}.reused must be true or false")
    result["reused"] = reused
    boxes = body.get("provenance_boxes", [])
    if not isinstance(boxes, list) or not all(isinstance(box, str) for box in boxes):
        raise ContractError(f"{where}.provenance_boxes must be a list of text")
    result["provenance_boxes"] = list(boxes)
    if "gpu_seconds" in body and body["gpu_seconds"] is not None:
        result["gpu_seconds"] = _number(body["gpu_seconds"], f"{where}.gpu_seconds", 0, 1e7)
    if "weights_revision" in body:
        revision = body["weights_revision"]
        result["weights_revision"] = (
            None if revision is None else _text(revision, f"{where}.weights_revision", 1, ID_MAX)
        )
    if "model_load_seconds" in body:
        result["model_load_seconds"] = _number(
            body["model_load_seconds"], f"{where}.model_load_seconds", 0, 1e7
        )
    if status == "FAILED" and result["error"] is None:
        raise ContractError(f"{where} FAILED without an error code")
    if status != "COMPLETED":
        return result
    mime = body.get("mime")
    if mime not in OUTPUT_MIMES:
        raise ContractError(f"{where}.mime must be one of {OUTPUT_MIMES}")
    result["mime"] = str(mime)
    result["key"] = _text(body.get("key"), f"{where}.key", 1, 1024)
    result["sha256"] = _hex64(body.get("sha256"), f"{where}.sha256")
    result["bytes"] = _int(body.get("bytes"), f"{where}.bytes", 1, 2**40)
    result["width"] = _int(body.get("width"), f"{where}.width", 1, 16384)
    result["height"] = _int(body.get("height"), f"{where}.height", 1, 16384)
    result["model"] = _text(body.get("model"), f"{where}.model", 1, ID_MAX)
    result["seed"] = _int(body.get("seed"), f"{where}.seed", 0, MAX_SEED)
    result["gpu_seconds"] = _number(body.get("gpu_seconds"), f"{where}.gpu_seconds", 0, 1e7)
    duration = body.get("duration")
    fps = body.get("fps")
    result["duration"] = (
        None if duration is None else _number(duration, f"{where}.duration", 0, 3600)
    )
    result["fps"] = None if fps is None else _int(fps, f"{where}.fps", 1, 240)
    return result


def validate_output(raw: object) -> BatchOutput:
    """A job's output as the studio reads it; raises :class:`ContractError`."""
    body = _mapping(raw, "output")
    if body.get("contract") != CONTRACT:
        raise ContractError(f"output.contract must be {CONTRACT}")
    items_raw = body.get("items")
    if not isinstance(items_raw, list) or len(items_raw) > MAX_ITEMS:
        raise ContractError(f"output.items must hold at most {MAX_ITEMS} items")
    items = [validate_item_result(item, f"output.items[{n}]") for n, item in enumerate(items_raw)]
    indexes = [item["index"] for item in items]
    if len(set(indexes)) != len(indexes):
        raise ContractError("output item indexes must be unique")
    checked: BatchOutput = {
        "contract": CONTRACT,
        "batch_key": _hex64(body.get("batch_key"), "output.batch_key"),
        "items": items,
        "model_load_seconds": _number(
            body.get("model_load_seconds"), "output.model_load_seconds", 0, 1e7
        ),
        "handler_seconds": _number(body.get("handler_seconds"), "output.handler_seconds", 0, 1e7),
        "gpu_seconds": _number(body.get("gpu_seconds"), "output.gpu_seconds", 0, 1e7),
    }
    if "weights_revision" in body:
        revision = body["weights_revision"]
        checked["weights_revision"] = (
            None if revision is None else _text(revision, "output.weights_revision", 1, ID_MAX)
        )
    return checked
