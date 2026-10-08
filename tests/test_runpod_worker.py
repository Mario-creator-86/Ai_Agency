"""The AMN RunPod worker (backend/runpod_worker), proven offline only.

Nothing here builds an image, pulls a weight, calls RunPod, a bucket or Hugging Face: the
handler runs against a fake ComfyUI and a fake bucket, the ComfyUI HTTP client against a
loopback fake server, the S3 port against a fake boto3 client, and the build plan is only
printed. The real image, the real models and the real timings are the paid bake-off's job.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import struct
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from runpod_worker import contract
from runpod_worker.contract import (
    CLIP_FPS,
    CLIP_SIZE,
    CONTRACT,
    MAX_ITEMS,
    STILL_SIZE,
    WORKFLOWS,
    ContractError,
    batch_key,
    claim_key,
    input_key,
    manifest_key,
    output_key,
    validate_input,
    validate_output,
)

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "backend" / "runpod_worker"
PREFIX = "amn/"


def _hex(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _ref(seed: str, data: bytes | None = None) -> dict[str, str]:
    digest = hashlib.sha256(data).hexdigest() if data is not None else _hex(seed)
    return {
        "url": f"https://bucket.example.test/amn/inputs/{digest}.png?X-Amz-Signature=abc",
        "sha256": digest,
        "mime": "image/png",
    }


def image_item(index: int, **extra: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "index": index,
        "idempotency_key": _hex(f"still-{index}"),
        "model": "Qwen-Image-2512",
        "workflow": "qwen_image_2512_seedvr2",
        "project_id": "film-1",
        "scene_id": f"scene-{index}",
        "prompt": f"A quiet harbour at dawn, frame {index}",
        "negative_prompt": None,
        "seed": 1000 + index,
        "width": STILL_SIZE[0],
        "height": STILL_SIZE[1],
        "reference_images": [],
    }
    item.update(extra)
    return item


def video_item(index: int, source: dict[str, str] | None = None, **extra: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "index": index,
        "idempotency_key": _hex(f"clip-{index}"),
        "model": "LTX-2.5",
        "workflow": "ltx_2_5_i2v",
        "project_id": "film-1",
        "scene_id": f"scene-{index}",
        "prompt": "The camera drifts slowly toward the harbour",
        "negative_prompt": "blur",
        "seed": 7 + index,
        "source_image": source or _ref(f"first-frame-{index}"),
        "duration": 5,
        "fps": CLIP_FPS,
    }
    item.update(extra)
    return item


def batch(items: list[dict[str, Any]], operation: str = "image", **extra: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "contract": CONTRACT,
        "operation": operation,
        "batch_key": batch_key(item["idempotency_key"] for item in items),
        "items": items,
        "output": {"prefix": PREFIX, "url_ttl_seconds": 604800},
        "time_budget_seconds": 2400,
    }
    raw.update(extra)
    return raw


# ---------------------------------------------------------------------------------- contract


def test_contract_constants_are_the_shared_ones():
    assert CONTRACT == "amn.batch.v1"
    assert contract.OPERATIONS == ("image", "video")
    assert MAX_ITEMS == 32
    assert STILL_SIZE == (1530, 2720)
    assert CLIP_SIZE == (1080, 1920)
    assert CLIP_FPS == 24
    assert contract.ITEM_STATES == ("COMPLETED", "FAILED", "SKIPPED_TIME", "CLAIMED_ELSEWHERE")
    assert WORKFLOWS == {
        "Qwen-Image-2512": ("image", "qwen_image_2512_seedvr2"),
        "LTX-2.5": ("video", "ltx_2_5_i2v"),
        "Wan-2.2-LightX2V": ("video", "wan_2_2_i2v_lightx2v"),
    }


def test_contract_imports_only_the_standard_library():
    source = (WORKER / "contract.py").read_text(encoding="utf-8")
    import ast

    tree = ast.parse(source)
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots <= set(sys.stdlib_module_names) | {"__future__"}


def test_keys_are_the_shared_layout():
    key = _hex("k")
    assert batch_key(["b", "a"]) == hashlib.sha256(b"a\nb").hexdigest()
    assert batch_key(["a", "b"]) == batch_key(["b", "a"])
    assert manifest_key(PREFIX, key) == f"amn/manifests/{key}.json"
    assert claim_key(PREFIX, key) == f"amn/claims/{key}.json"
    assert output_key(PREFIX, key, "png") == f"amn/outputs/{key}.png"
    assert input_key(PREFIX, key, "jpg") == f"amn/inputs/{key}.jpg"


def test_a_valid_image_batch_passes():
    raw = batch([image_item(0), image_item(1, reference_images=[_ref("r")])])
    checked = validate_input(raw)
    assert checked["operation"] == "image"
    assert [item["index"] for item in checked["items"]] == [0, 1]
    assert checked["items"][1]["reference_images"][0]["sha256"] == _hex("r")


def test_a_valid_video_batch_passes():
    raw = batch(
        [
            video_item(0),
            video_item(1, duration=10.0, model="Wan-2.2-LightX2V", workflow="wan_2_2_i2v_lightx2v"),
        ],
        "video",
    )
    checked = validate_input(raw)
    assert checked["items"][1]["duration"] == 10.0


def _set_item(index: int, key: str, value: Any):
    def change(raw: dict[str, Any]) -> None:
        raw["items"][index][key] = value

    return change


def _drop_item_key(index: int, key: str):
    def change(raw: dict[str, Any]) -> None:
        del raw["items"][index][key]

    return change


@pytest.mark.parametrize(
    "change",
    [
        lambda raw: raw.update(contract="amn.batch.v2"),
        lambda raw: raw.update(operation="audio"),
        lambda raw: raw.update(operation="video"),
        lambda raw: raw.update(batch_key=_hex("other")),
        lambda raw: raw.update(batch_key="ABC"),
        lambda raw: raw.update(items=[]),
        lambda raw: raw.update(time_budget_seconds=0),
        lambda raw: raw.update(time_budget_seconds=True),
        lambda raw: raw.update(output={"prefix": "amn", "url_ttl_seconds": 60}),
        lambda raw: raw.update(output={"prefix": "../x/", "url_ttl_seconds": 60}),
        lambda raw: raw.update(output={"prefix": PREFIX, "url_ttl_seconds": 604801}),
        lambda raw: raw.update(surprise=1),
    ],
)
def test_a_broken_batch_envelope_is_refused(change):
    raw = batch([image_item(0), image_item(1)])
    change(raw)
    with pytest.raises(ContractError):
        validate_input(raw)


@pytest.mark.parametrize(
    "change",
    [
        _set_item(1, "index", 0),
        _set_item(1, "index", 2),
        _set_item(1, "idempotency_key", _hex("still-0")),
        _set_item(0, "idempotency_key", "not-hex"),
        _set_item(0, "model", "FLUX.1-dev"),
        _set_item(0, "model", "LTX-2.5"),
        _set_item(0, "workflow", "ltx_2_5_i2v"),
        _set_item(0, "width", 1080),
        _set_item(0, "height", 1920),
        _set_item(0, "prompt", ""),
        _set_item(0, "prompt", "x" * 20001),
        _set_item(0, "negative_prompt", 5),
        _set_item(0, "seed", 2**32),
        _set_item(0, "seed", -1),
        _set_item(0, "seed", True),
        _set_item(0, "reference_images", [_ref(str(n)) for n in range(9)]),
        _set_item(0, "reference_images", [{**_ref("r"), "url": "http://plain.example/x"}]),
        _set_item(0, "reference_images", [{**_ref("r"), "sha256": "12"}]),
        _set_item(0, "reference_images", [{**_ref("r"), "url": "https://u:p@host/x"}]),
        _set_item(0, "reference_images", [{**_ref("r"), "mime": "text/html"}]),
        _set_item(0, "source_image", _ref("s")),
        _set_item(0, "duration", 5),
        _set_item(0, "unknown", 1),
        _set_item(0, "project_id", ""),
        _drop_item_key(0, "prompt"),
        _drop_item_key(0, "seed"),
    ],
)
def test_a_broken_image_item_is_refused(change):
    raw = batch([image_item(0), image_item(1)])
    change(raw)
    keys = [str(item.get("idempotency_key", "")) for item in raw["items"]]
    raw["batch_key"] = batch_key(keys)
    with pytest.raises(ContractError):
        validate_input(raw)


@pytest.mark.parametrize(
    "change",
    [
        _drop_item_key(0, "source_image"),
        _set_item(0, "duration", 0.5),
        _set_item(0, "duration", 11),
        _set_item(0, "fps", 30),
        _set_item(0, "width", 1088),
        _set_item(0, "model", "Qwen-Image-2512"),
        _set_item(0, "workflow", "wan_2_2_i2v_lightx2v"),
    ],
)
def test_a_broken_video_batch_is_refused(change):
    raw = batch([video_item(0)], "video")
    change(raw)
    raw["batch_key"] = batch_key(item["idempotency_key"] for item in raw["items"])
    with pytest.raises(ContractError):
        validate_input(raw)


def test_more_than_max_items_is_refused():
    items = [image_item(n) for n in range(MAX_ITEMS + 1)]
    with pytest.raises(ContractError):
        validate_input(batch(items))
    assert validate_input(batch(items[:MAX_ITEMS]))


def test_not_an_object_is_refused():
    for raw in (None, [], "x", 3):
        with pytest.raises(ContractError):
            validate_input(raw)
        with pytest.raises(ContractError):
            validate_output(raw)


def completed_result(index: int = 0, **extra: Any) -> dict[str, Any]:
    key = _hex(f"still-{index}")
    result: dict[str, Any] = {
        "index": index,
        "idempotency_key": key,
        "status": "COMPLETED",
        "url": "https://bucket.example.test/amn/outputs/x.png?X-Amz-Signature=1",
        "key": output_key(PREFIX, key, "png"),
        "sha256": _hex("png"),
        "bytes": 1234,
        "mime": "image/png",
        "width": 1530,
        "height": 2720,
        "duration": None,
        "fps": None,
        "model": "Qwen-Image-2512",
        "seed": 1000,
        "gpu_seconds": 41.5,
        "error": None,
        "reused": False,
        "provenance_boxes": [],
    }
    result.update(extra)
    return result


def output(items: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "contract": CONTRACT,
        "batch_key": _hex("batch"),
        "model_load_seconds": 12.0,
        "handler_seconds": 60.5,
        "gpu_seconds": 60.5,
        "items": items,
    }
    raw.update(extra)
    return raw


def test_a_valid_output_passes():
    failed = {
        "index": 1,
        "idempotency_key": _hex("still-1"),
        "status": "FAILED",
        "url": None,
        "error": "COMFY_FAILED",
        "reused": False,
    }
    checked = validate_output(output([completed_result(0), failed]))
    assert checked["items"][0]["sha256"] == _hex("png")
    assert checked["items"][1]["error"] == "COMFY_FAILED"


@pytest.mark.parametrize(
    "change",
    [
        lambda raw: raw.update(contract="other"),
        lambda raw: raw.update(gpu_seconds=-1),
        lambda raw: raw.update(handler_seconds="5"),
        lambda raw: raw["items"][0].update(status="DONE"),
        lambda raw: raw["items"][0].pop("sha256"),
        lambda raw: raw["items"][0].update(sha256="short"),
        lambda raw: raw["items"][0].update(bytes=0),
        lambda raw: raw["items"][0].update(mime="image/gif"),
        lambda raw: raw["items"][0].update(url="http://plain/x"),
        lambda raw: raw["items"][0].update(idempotency_key="x"),
        lambda raw: raw["items"].append(completed_result(0)),
        lambda raw: raw["items"].append(
            {"index": 1, "idempotency_key": _hex("f"), "status": "FAILED", "error": None}
        ),
    ],
)
def test_a_broken_output_is_refused(change):
    raw = output([completed_result(0)])
    change(raw)
    with pytest.raises(ContractError):
        validate_output(raw)


# ------------------------------------------------------------------------------ worker fakes

from runpod_worker import amn_handler, build, postprocess  # noqa: E402
from runpod_worker.comfy import (  # noqa: E402
    ComfyClient,
    ComfyFailed,
    ComfyUnavailable,
    find_output,
)
from runpod_worker.contract import validate_item_result  # noqa: E402
from runpod_worker.storage import (  # noqa: E402
    ConditionalPutUnsupported,
    PreconditionFailed,
    S3Storage,
    StorageError,
    StorageNotConfigured,
)

C2PA_UUID = bytes.fromhex("d8fec3d61b0e483c92975828877ec481")


def box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def tkhd(width: int, height: int) -> bytes:
    # version 0: flags, times, track id, reserved, duration, reserved, layer..matrix, w, h.
    body = b"\x00\x00\x00\x07" + b"\x00" * 16 + b"\x00" * 4 + b"\x00" * 8 + b"\x00" * 8
    body += b"\x00" * 36 + struct.pack(">II", width << 16, height << 16)
    return box(b"tkhd", body)


def mp4(width: int, height: int, *, c2pa: bool = False) -> bytes:
    data = box(b"ftyp", b"isom\x00\x00\x02\x00isom")
    data += box(b"moov", box(b"trak", tkhd(width, height)))
    if c2pa:
        data += box(b"uuid", C2PA_UUID + b"manifest")
    return data


def png(width: int, height: int, *, text: dict[str, str] | None = None) -> bytes:
    from PIL import Image, PngImagePlugin

    info = PngImagePlugin.PngInfo()
    for key, value in (text or {}).items():
        info.add_text(key, value)
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (40, 90, 160)).save(buffer, "PNG", pnginfo=info)
    return buffer.getvalue()


class FakeBucket:
    """The StoragePort in memory; a download URL answers only what the test registered."""

    def __init__(self, *, conditional: bool = True) -> None:
        self.objects: dict[str, bytes] = {}
        self.mimes: dict[str, str] = {}
        self.urls: dict[str, bytes] = {}
        self.puts: list[tuple[str, bool]] = []
        self.downloads: list[str] = []
        self.conditional = conditional

    def head(self, key: str) -> bool:
        return key in self.objects

    def get_json(self, key: str) -> dict[str, Any] | None:
        return json.loads(self.objects[key]) if key in self.objects else None

    def put_bytes(self, key: str, data: bytes, mime: str, *, if_none_match: bool = False) -> None:
        self.puts.append((key, if_none_match))
        if if_none_match:
            if not self.conditional:
                raise ConditionalPutUnsupported(key)
            if key in self.objects:
                raise PreconditionFailed(key)
        self.objects[key] = data
        self.mimes[key] = mime

    def presign_get(self, key: str, ttl: int) -> str:
        return f"https://bucket.example.test/{key}?X-Amz-Expires={ttl}&X-Amz-Signature=fake"

    def download_url(self, url: str) -> bytes:
        self.downloads.append(url)
        if url not in self.urls:
            raise StorageError("no such input")
        return self.urls[url]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeComfy:
    """The ComfyPort: records graphs, writes the 'saved' file into a temp output folder."""

    def __init__(self, tmp: Path, clock: Clock, *, down: bool = False) -> None:
        self.output_dir = tmp / "comfy-output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.down = down
        self.graphs: list[dict[str, Any]] = []
        self.uploads: dict[str, bytes] = {}
        self.ready_calls = 0
        self.fail_prompts: dict[int, Exception] = {}
        self.item_seconds = 40.0
        self.output_type = "output"
        self.make: Any = None

    def wait_ready(self, timeout: float) -> float:
        self.ready_calls += 1
        if self.down:
            raise ComfyUnavailable("down")
        return 3.0

    def upload_input(self, name: str, data: bytes) -> str:
        self.uploads[name] = data
        return name

    def queue(self, graph: dict[str, Any]) -> str:
        number = len(self.graphs)
        self.graphs.append(graph)
        if number in self.fail_prompts:
            raise self.fail_prompts[number]
        return f"prompt-{number}"

    def wait(self, prompt_id: str, timeout: float) -> dict[str, Any]:
        number = int(prompt_id.split("-")[1])
        self.clock.now += self.item_seconds
        graph = self.graphs[number]
        node, name, data = self.make(graph)
        (self.output_dir / name).write_bytes(data)
        entry = {"filename": name, "subfolder": "", "type": self.output_type}
        return {"outputs": {node: {"images": [entry]}}, "status": {"completed": True}}

    def output_path(self, history: dict[str, Any], node_id: str) -> Path:
        return find_output(history, node_id, self.output_dir)


def still_maker(graph: dict[str, Any]) -> tuple[str, str, bytes]:
    workflow = amn_handler.load_workflow("qwen_image_2512_seedvr2")
    # A SeedVR2-like 1530x2743 frame: the handler must deliver exactly 1530x2720.
    return workflow.output_node, f"still-{id(graph)}.png", png(1530, 2743, text={"prompt": "x"})


class SimpleWorker:
    def __init__(self, run: Any, comfy: FakeComfy, bucket: FakeBucket, clock: Clock) -> None:
        self.run = run
        self.comfy = comfy
        self.bucket = bucket
        self.clock = clock


@pytest.fixture
def worker(tmp_path, monkeypatch):
    clock = Clock()
    comfy = FakeComfy(tmp_path, clock)
    comfy.make = still_maker
    bucket = FakeBucket()
    monkeypatch.setattr(amn_handler, "wall_clock", lambda: 5_000_000.0)
    monkeypatch.setattr(amn_handler, "PROGRESS", None)

    def run(raw: dict[str, Any], job_id: str = "job-1") -> dict[str, Any]:
        job = {"id": job_id, "input": raw}
        return dict(amn_handler.handler(job, comfy=comfy, storage=bucket, clock=clock))

    return SimpleWorker(run, comfy, bucket, clock)


def _bound(graph: dict[str, Any], workflow_name: str, name: str) -> Any:
    workflow = amn_handler.load_workflow(workflow_name)
    node, _, field = workflow.bindings[name][0]
    return graph[node]["inputs"][field]


# ---------------------------------------------------------------------------- handler: stills


def test_a_still_batch_is_generated_uploaded_and_manifested(worker):
    out = worker.run(batch([image_item(0), image_item(1)]))
    checked = validate_output(out)
    assert [item["status"] for item in checked["items"]] == ["COMPLETED", "COMPLETED"]
    assert worker.comfy.ready_calls == 1  # ComfyUI is awaited once per job, not per item
    assert len(worker.comfy.graphs) == 2
    first = worker.comfy.graphs[0]
    assert _bound(first, "qwen_image_2512_seedvr2", "prompt") == image_item(0)["prompt"]
    assert _bound(first, "qwen_image_2512_seedvr2", "seed") == 1000
    assert _bound(first, "qwen_image_2512_seedvr2", "width") == 1530
    assert _bound(first, "qwen_image_2512_seedvr2", "height") == 2720
    from PIL import Image

    for n, item in enumerate(checked["items"]):
        key = image_item(n)["idempotency_key"]
        assert item["key"] == output_key(PREFIX, key, "png")
        data = worker.bucket.objects[item["key"]]
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
        assert item["bytes"] == len(data)
        assert Image.open(io.BytesIO(data)).size == STILL_SIZE
        assert (item["width"], item["height"], item["mime"]) == (1530, 2720, "image/png")
        assert item["url"] == worker.bucket.presign_get(item["key"], 604800)
        assert item["reused"] is False and item["error"] is None
        assert item["gpu_seconds"] == pytest.approx(40.0)
        assert "png:tEXt:prompt" in item["provenance_boxes"]
        manifest = json.loads(worker.bucket.objects[manifest_key(PREFIX, key)])
        assert manifest["created_at"]
        assert manifest["url"] is None  # a manifest never stores a URL that expires
        assert validate_item_result(manifest)["sha256"] == item["sha256"]
        assert (claim_key(PREFIX, key), True) in worker.bucket.puts
    assert out["model_load_seconds"] == pytest.approx(3.0)
    assert out["handler_seconds"] == pytest.approx(80.0)


def test_a_finished_item_is_reused_without_comfyui(worker):
    worker.run(batch([image_item(0)]))
    graphs = len(worker.comfy.graphs)
    again = {**image_item(0), "index": 1}
    out = worker.run(batch([{**image_item(1), "index": 0}, again]), job_id="job-2")
    reused = out["items"][1]
    assert reused["status"] == "COMPLETED" and reused["reused"] is True
    assert reused["index"] == 1
    assert reused["gpu_seconds"] == 0.0
    assert reused["url"].startswith("https://bucket.example.test/amn/outputs/")
    assert len(worker.comfy.graphs) == graphs + 1  # only the new item went to ComfyUI


def test_a_manifest_without_its_object_is_generated_again(worker):
    worker.run(batch([image_item(0)]))
    key = image_item(0)["idempotency_key"]
    del worker.bucket.objects[output_key(PREFIX, key, "png")]
    del worker.bucket.objects[claim_key(PREFIX, key)]
    out = worker.run(batch([image_item(0)]), job_id="job-2")
    assert out["items"][0]["reused"] is False
    assert len(worker.comfy.graphs) == 2


def _claim(bucket: FakeBucket, key: str, **fields: Any) -> None:
    body = {"job_id": "other-job", "claimed_at": 5_000_000.0 - 10, "released": False}
    body.update(fields)
    bucket.objects[claim_key(PREFIX, key)] = json.dumps(body).encode()


def test_a_young_claim_of_another_job_is_left_alone(worker):
    _claim(worker.bucket, image_item(0)["idempotency_key"])
    out = worker.run(batch([image_item(0), image_item(1)]))
    assert out["items"][0]["status"] == "CLAIMED_ELSEWHERE"
    assert out["items"][1]["status"] == "COMPLETED"
    assert len(worker.comfy.graphs) == 1
    validate_output(out)


@pytest.mark.parametrize(
    "fields",
    [
        {"claimed_at": 5_000_000.0 - 5000},  # older than the job's time budget
        {"job_id": "job-1"},  # RunPod retried this very job
        {"released": True},  # the other job failed the item and let it go
        {"claimed_at": "yesterday"},  # unreadable: never blocks the paid item
    ],
)
def test_a_stale_or_own_claim_is_taken_over(worker, fields):
    key = image_item(0)["idempotency_key"]
    _claim(worker.bucket, key, **fields)
    out = worker.run(batch([image_item(0)]))
    assert out["items"][0]["status"] == "COMPLETED"
    assert json.loads(worker.bucket.objects[claim_key(PREFIX, key)])["job_id"] == "job-1"


def test_a_store_without_conditional_put_falls_back_to_head_and_put(worker):
    worker.bucket.conditional = False
    key = image_item(0)["idempotency_key"]
    out = worker.run(batch([image_item(0)]))
    assert out["items"][0]["status"] == "COMPLETED"
    claims = [put for put in worker.bucket.puts if put[0] == claim_key(PREFIX, key)]
    assert claims == [(claim_key(PREFIX, key), True), (claim_key(PREFIX, key), False)]


def test_items_past_the_time_budget_are_skipped_before_they_are_claimed(worker):
    worker.comfy.item_seconds = 150.0
    raw = batch([image_item(0), image_item(1), image_item(2)], time_budget_seconds=400)
    out = worker.run(raw)
    assert [item["status"] for item in out["items"]] == ["COMPLETED", "COMPLETED", "SKIPPED_TIME"]
    skipped_key = image_item(2)["idempotency_key"]
    assert claim_key(PREFIX, skipped_key) not in worker.bucket.objects
    validate_output(out)


def test_the_first_items_model_load_does_not_skip_paid_items(worker, monkeypatch):
    # ComfyUI loads the models lazily, inside the first prompt; the studio budgets that
    # load separately (cold_start_seconds 120) and gives the job 120 + n x 180 - 15 s.
    # A 260 s first item (load + render) must not make the next 40 s item look 260 s long.
    seconds = iter([260.0, 40.0])
    plain_wait = worker.comfy.wait

    def wait(prompt_id: str, timeout: float) -> dict[str, Any]:
        worker.comfy.item_seconds = next(seconds)
        return plain_wait(prompt_id, timeout)

    monkeypatch.setattr(worker.comfy, "wait", wait)
    raw = batch([image_item(0), image_item(1)], time_budget_seconds=120 + 2 * 180 - 15)
    out = worker.run(raw)
    assert [item["status"] for item in out["items"]] == ["COMPLETED", "COMPLETED"]


def test_a_measured_slow_item_still_guards_the_next_one(worker, monkeypatch):
    # After the first (warm-up) item, the slowest real item is the guard's yardstick.
    seconds = iter([40.0, 300.0, 40.0])
    plain_wait = worker.comfy.wait

    def wait(prompt_id: str, timeout: float) -> dict[str, Any]:
        worker.comfy.item_seconds = next(seconds)
        return plain_wait(prompt_id, timeout)

    monkeypatch.setattr(worker.comfy, "wait", wait)
    raw = batch([image_item(0), image_item(1), image_item(2)], time_budget_seconds=600)
    out = worker.run(raw)
    assert [item["status"] for item in out["items"]] == ["COMPLETED", "COMPLETED", "SKIPPED_TIME"]


@pytest.mark.parametrize(
    ("workflow_name", "model", "operation"),
    [
        ("qwen_image_2512_seedvr2", "Qwen-Image-2512", "image"),
        ("ltx_2_5_i2v", "LTX-2.5", "video"),
        ("wan_2_2_i2v_lightx2v", "Wan-2.2-LightX2V", "video"),
    ],
)
def test_an_item_without_a_negative_prompt_keeps_the_templates_own(
    worker, fake_ffmpeg, workflow_name, model, operation
):
    raw_graph = json.loads(
        (WORKER / "workflows" / f"{workflow_name}.json").read_text(encoding="utf-8")
    )["graph"]
    node, _, field = amn_handler.load_workflow(workflow_name).bindings["negative_prompt"][0]
    default = raw_graph[node]["inputs"][field]
    assert isinstance(default, str) and default.strip()  # the official template's negative
    if operation == "image":
        item = image_item(0, negative_prompt=None)
    else:
        frame = png(1088, 1920)
        source = _ref("first", frame)
        worker.bucket.urls[source["url"]] = frame
        worker.comfy.make = clip_maker(workflow_name)
        item = video_item(0, source=source, model=model, workflow=workflow_name)
        item["negative_prompt"] = None
    worker.run(batch([item], operation))
    assert _bound(worker.comfy.graphs[0], workflow_name, "negative_prompt") == default


def test_a_failed_item_does_not_stop_the_batch_and_releases_its_claim(worker):
    worker.comfy.fail_prompts[0] = ComfyFailed("COMFY_FAILED", "out of memory")
    out = worker.run(batch([image_item(0), image_item(1)]))
    assert out["items"][0]["status"] == "FAILED"
    assert out["items"][0]["error"] == "COMFY_FAILED"
    assert out["items"][1]["status"] == "COMPLETED"
    claim = json.loads(worker.bucket.objects[claim_key(PREFIX, image_item(0)["idempotency_key"])])
    assert claim["released"] is True
    validate_output(out)


def test_comfyui_down_fails_the_rest_of_the_batch_once(worker):
    worker.comfy.down = True
    out = worker.run(batch([image_item(0), image_item(1), image_item(2)]))
    assert [item["error"] for item in out["items"]] == ["COMFY_DOWN"] * 3
    assert worker.comfy.ready_calls == 1


def test_comfyui_lost_mid_batch_fails_the_remaining_items(worker):
    worker.comfy.fail_prompts[1] = ComfyUnavailable("gone")
    out = worker.run(batch([image_item(0), image_item(1), image_item(2)]))
    assert [item["status"] for item in out["items"]] == ["COMPLETED", "FAILED", "FAILED"]
    assert [item["error"] for item in out["items"][1:]] == ["COMFY_DOWN", "COMFY_DOWN"]
    assert len(worker.comfy.graphs) == 2


def test_a_preview_output_is_never_the_delivered_take(worker):
    worker.comfy.output_type = "temp"
    out = worker.run(batch([image_item(0)]))
    assert out["items"][0]["error"] == "NO_OUTPUT"


def test_a_contract_error_fails_the_job_before_anything_is_touched(worker):
    raw = batch([image_item(0)])
    raw["items"][0]["width"] = 1080
    raw["batch_key"] = batch_key([raw["items"][0]["idempotency_key"]])
    with pytest.raises(ContractError):
        worker.run(raw)
    assert worker.bucket.puts == [] and worker.comfy.graphs == []


def test_a_still_reference_is_not_fetched_while_its_workflow_has_no_reference_input(worker):
    out = worker.run(batch([image_item(0, reference_images=[_ref("unregistered")])]))
    assert out["items"][0]["status"] == "COMPLETED"
    assert worker.bucket.downloads == []


def test_progress_is_best_effort(worker, monkeypatch):
    seen: list[str] = []

    def progress(job: dict[str, Any], message: str) -> None:
        seen.append(message)
        raise RuntimeError("progress endpoint down")

    monkeypatch.setattr(amn_handler, "PROGRESS", progress)
    out = worker.run(batch([image_item(0), image_item(1)]))
    assert [item["status"] for item in out["items"]] == ["COMPLETED", "COMPLETED"]
    assert seen == ["1/2", "2/2"]


# ----------------------------------------------------------------------------- handler: clips


def clip_maker(workflow_name: str, *, c2pa: bool = True):
    def make(graph: dict[str, Any]) -> tuple[str, str, bytes]:
        workflow = amn_handler.load_workflow(workflow_name)
        return workflow.output_node, f"clip-{id(graph)}.mp4", mp4(1088, 1920, c2pa=c2pa)

    return make


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    calls: list[list[str]] = []

    def run(args: list[str]) -> None:
        calls.append(args)
        Path(args[-1]).write_bytes(mp4(1080, 1920))

    monkeypatch.setattr(postprocess, "run_ffmpeg", run)
    return calls


def test_a_clip_batch_uploads_the_first_frame_and_delivers_1080x1920(worker, fake_ffmpeg):
    frame = png(1088, 1920)
    source = _ref("first", frame)
    worker.bucket.urls[source["url"]] = frame
    worker.comfy.make = clip_maker("ltx_2_5_i2v")
    out = worker.run(batch([video_item(0, source=source)], "video"))
    item = validate_output(out)["items"][0]
    assert item["status"] == "COMPLETED", item
    assert worker.comfy.uploads == {f"{source['sha256']}.png": frame}
    graph = worker.comfy.graphs[0]
    assert _bound(graph, "ltx_2_5_i2v", "source_image") == f"{source['sha256']}.png"
    assert _bound(graph, "ltx_2_5_i2v", "duration_frames") == 121  # 5 s at 24 fps, 8k+1
    assert _bound(graph, "ltx_2_5_i2v", "negative_prompt") == "blur"
    assert (item["mime"], item["width"], item["height"]) == ("video/mp4", 1080, 1920)
    assert (item["fps"], item["duration"]) == (24, 5.0)
    assert item["key"] == output_key(PREFIX, video_item(0)["idempotency_key"], "mp4")
    # The LTX-2.x licence forbids stripping provenance: what the encode lost is flagged.
    assert item["provenance_boxes"] == ["c2pa", "lost:c2pa"]
    args = fake_ffmpeg[0]
    for flag in ("-an", "libx264", "yuv420p", "-map_metadata"):
        assert flag in args


def test_wan_counts_frames_at_its_own_rate(worker, fake_ffmpeg):
    frame = png(720, 1280)
    source = _ref("first", frame)
    worker.bucket.urls[source["url"]] = frame
    worker.comfy.make = clip_maker("wan_2_2_i2v_lightx2v", c2pa=False)
    item = video_item(
        0, source=source, model="Wan-2.2-LightX2V", workflow="wan_2_2_i2v_lightx2v", duration=10
    )
    out = worker.run(batch([item], "video"))
    assert out["items"][0]["status"] == "COMPLETED"
    graph = worker.comfy.graphs[0]
    assert _bound(graph, "wan_2_2_i2v_lightx2v", "duration_frames") == 161  # 16 fps, 4k+1
    assert out["items"][0]["provenance_boxes"] == []


def test_a_first_frame_that_does_not_match_its_hash_fails_only_that_item(worker, fake_ffmpeg):
    good, bad = png(1088, 1920), png(1088, 1920, text={"x": "y"})
    first = _ref("a", good)
    second = {**_ref("b", good), "url": first["url"] + "&other=1"}
    worker.bucket.urls[first["url"]] = good
    worker.bucket.urls[second["url"]] = bad
    worker.comfy.make = clip_maker("ltx_2_5_i2v")
    out = worker.run(batch([video_item(0, source=second), video_item(1, source=first)], "video"))
    assert out["items"][0]["error"] == "INPUT_SHA256_MISMATCH"
    assert out["items"][1]["status"] == "COMPLETED"


def test_an_unreachable_first_frame_fails_its_item(worker, fake_ffmpeg):
    worker.comfy.make = clip_maker("ltx_2_5_i2v")
    out = worker.run(batch([video_item(0)], "video"))
    assert out["items"][0]["error"] == "INPUT_DOWNLOAD_FAILED"


def test_an_encode_that_misses_the_frame_fails_its_item(worker, monkeypatch):
    frame = png(1088, 1920)
    source = _ref("first", frame)
    worker.bucket.urls[source["url"]] = frame
    worker.comfy.make = clip_maker("ltx_2_5_i2v")
    monkeypatch.setattr(
        postprocess, "run_ffmpeg", lambda args: Path(args[-1]).write_bytes(mp4(1088, 1920))
    )
    out = worker.run(batch([video_item(0, source=source)], "video"))
    assert out["items"][0]["error"] == "POSTPROCESS_FAILED"


# --------------------------------------------------------------------------- handler: runtime


def test_the_handler_module_needs_neither_runpod_nor_boto3():
    import importlib.util

    # The studio's environment has neither; importing the handler must still work there.
    assert importlib.util.find_spec("runpod") is None
    assert importlib.util.find_spec("boto3") is None
    assert amn_handler.handler


def test_main_starts_the_runpod_loop_with_the_batch_handler(monkeypatch):
    import types

    started: list[dict[str, Any]] = []
    serverless = types.SimpleNamespace(
        start=lambda config: started.append(config), progress_update=lambda job, msg: None
    )
    monkeypatch.setitem(sys.modules, "runpod", types.SimpleNamespace(serverless=serverless))
    monkeypatch.setenv("AMN_START_COMFY", "0")
    monkeypatch.setattr(amn_handler, "PROGRESS", None)
    amn_handler.main()
    assert started and callable(started[0]["handler"])
    assert amn_handler.PROGRESS is serverless.progress_update


# ---------------------------------------------------------------------------- post-processing


def test_a_still_of_the_exact_size_is_kept_byte_for_byte():
    data = png(1530, 2720, text={"prompt": "kept"})
    finished = postprocess.finish_still(data)
    assert finished.data == data
    assert (finished.width, finished.height) == STILL_SIZE


def test_a_still_of_another_size_is_center_cropped_and_keeps_its_text():
    from PIL import Image

    finished = postprocess.finish_still(png(928, 1664, text={"prompt": "kept"}))
    image = Image.open(io.BytesIO(finished.data))
    assert image.size == STILL_SIZE and image.format == "PNG"
    assert image.text.get("prompt") == "kept"
    assert finished.provenance_boxes == ["png:tEXt:prompt"]


def test_png_provenance_names_c2pa_and_text_chunks():
    import zlib

    data = png(16, 16, text={"workflow": "{}"})
    chunk = b"caBX" + b"jumbf"  # a C2PA manifest in PNG, placed before IEND
    cabx = struct.pack(">I", 5) + chunk + struct.pack(">I", zlib.crc32(chunk))
    data = data[:-12] + cabx + data[-12:]
    assert postprocess.png_provenance(data) == ["png:tEXt:workflow", "png:caBX"]


def test_mp4_boxes_give_the_frame_and_the_provenance():
    data = mp4(1088, 1920, c2pa=True)
    assert postprocess.video_size(data) == (1088, 1920)
    assert postprocess.mp4_provenance(data) == ["c2pa"]
    other = box(b"uuid", b"\x01" * 16 + b"x")
    assert postprocess.mp4_provenance(mp4(8, 8) + other) == ["uuid:" + "01" * 16]
    assert postprocess.video_size(b"garbage") is None


def test_the_clip_encode_is_the_delivery_spec():
    args = postprocess.clip_args("ffmpeg", Path("in.mp4"), Path("out.mp4"), 5.0)
    joined = " ".join(args)
    assert "scale=1080:1920:force_original_aspect_ratio=increase" in joined
    assert "crop=1080:1920" in joined and "fps=24" in joined
    assert args[args.index("-t") + 1] == "5.000"
    assert args[args.index("-map_metadata") + 1] == "0"
    assert "-an" in args and args[-1] == str(Path("out.mp4"))
    assert args[args.index("-c:v") + 1] == "libx264"
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_the_real_encode_turns_a_portrait_1088_clip_into_1080x1920(tmp_path):
    import subprocess

    source = tmp_path / "ltx.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=1088x1920:r=24:d=0.25",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=120,
    )
    finished = postprocess.finish_clip(source, tmp_path / "out.mp4", 1.0)
    assert (finished.width, finished.height) == CLIP_SIZE
    assert postprocess.video_size(finished.data) == CLIP_SIZE


# ------------------------------------------------------------------------ ComfyUI HTTP client


class _FakeComfyServer(BaseHTTPRequestHandler):
    history_calls = 0
    state = "success"
    uploads: list[bytes] = []

    def log_message(self, *args: Any) -> None:
        pass

    def _answer(self, status: int, value: Any) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/system_stats":
            self._answer(200, {"system": {}})
        elif self.path == "/history/abc":
            type(self).history_calls += 1
            if type(self).history_calls < 2:
                self._answer(200, {})
                return
            saved = {"filename": "a.png", "subfolder": "amn", "type": "output"}
            entry = {
                "outputs": {"9": {"images": [saved]}},
                "status": {"status_str": type(self).state, "completed": True},
            }
            self._answer(200, {"abc": entry})
        else:
            self._answer(200, {})

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/prompt":
            graph = json.loads(body)["prompt"]
            if "bad" in graph:
                self._answer(400, {"error": "invalid", "node_errors": {"bad": "x"}})
            else:
                self._answer(200, {"prompt_id": "abc", "number": 1, "node_errors": {}})
        elif self.path == "/upload/image":
            type(self).uploads.append(body)
            self._answer(200, {"name": "x.png", "subfolder": "", "type": "input"})
        else:
            self._answer(200, {})


@pytest.fixture
def comfy_server():
    _FakeComfyServer.history_calls = 0
    _FakeComfyServer.state = "success"
    _FakeComfyServer.uploads = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeComfyServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_the_comfyui_client_queues_waits_and_finds_the_saved_file(comfy_server, tmp_path):
    client = ComfyClient(comfy_server, output_dir=tmp_path, poll_seconds=0.01)
    assert client.wait_ready(5) >= 0
    assert client.upload_input("x.png", b"PNGDATA") == "x.png"
    assert b"PNGDATA" in _FakeComfyServer.uploads[0]
    prompt_id = client.queue({"1": {"class_type": "SaveImage", "inputs": {}}})
    assert prompt_id == "abc"
    history = client.wait(prompt_id, timeout=5)
    assert client.output_path(history, "9") == (tmp_path / "amn" / "a.png").resolve()


def test_the_comfyui_client_names_its_failures(comfy_server, tmp_path):
    client = ComfyClient(comfy_server, output_dir=tmp_path, poll_seconds=0.01)
    with pytest.raises(ComfyFailed) as rejected:
        client.queue({"bad": {}})
    assert rejected.value.code == "COMFY_REJECTED"
    _FakeComfyServer.state = "error"
    with pytest.raises(ComfyFailed) as failed:
        client.wait("abc", timeout=5)
    assert failed.value.code == "COMFY_FAILED"


def test_the_comfyui_client_times_out_and_refuses_a_remote_host(comfy_server, tmp_path):
    client = ComfyClient(comfy_server, output_dir=tmp_path, poll_seconds=0.01)
    with pytest.raises(ComfyFailed) as timed_out:
        client.wait("never", timeout=0.05)
    assert timed_out.value.code == "COMFY_TIMEOUT"
    with pytest.raises(ValueError):
        ComfyClient("comfy.example.com:8188")


def test_an_unanswering_comfyui_is_unavailable(tmp_path):
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise ConnectionRefusedError("refused")

    client = ComfyClient(opener=refuse, output_dir=tmp_path, poll_seconds=0.0)
    with pytest.raises(ComfyUnavailable):
        client.wait_ready(0)
    with pytest.raises(ComfyUnavailable):
        client.queue({})


def test_find_output_refuses_temp_and_paths_outside_the_output_folder(tmp_path):
    temp = {"outputs": {"9": {"images": [{"filename": "a.png", "type": "temp"}]}}}
    with pytest.raises(ComfyFailed):
        find_output(temp, "9", tmp_path)
    outside = {"filename": "a.png", "subfolder": "../..", "type": "output"}
    with pytest.raises(ComfyFailed):
        find_output({"outputs": {"9": {"images": [outside]}}}, "9", tmp_path)
    with pytest.raises(ComfyFailed):
        find_output({"outputs": {}}, "9", tmp_path)


# --------------------------------------------------------------------------------- S3 storage


class FakeClientError(Exception):
    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}


class FakeS3Client:
    def __init__(self, conditional: str = "ok") -> None:
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.conditional = conditional

    def head_object(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("head", kw))
        if kw["Key"] not in self.objects:
            raise FakeClientError("404", 404)
        return {}

    def get_object(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("get", kw))
        if kw["Key"] not in self.objects:
            raise FakeClientError("NoSuchKey", 404)
        return {"Body": io.BytesIO(self.objects[kw["Key"]])}

    def put_object(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("put", kw))
        if "IfNoneMatch" in kw:
            if self.conditional == "unsupported":
                raise FakeClientError("NotImplemented", 501)
            if kw["Key"] in self.objects:
                raise FakeClientError("PreconditionFailed", 412)
        self.objects[kw["Key"]] = kw["Body"]
        return {}

    def generate_presigned_url(self, op: str, Params: dict[str, Any], ExpiresIn: int) -> str:  # noqa: N803
        self.calls.append(("presign", {"op": op, **Params, "ExpiresIn": ExpiresIn}))
        return (
            f"https://r2.example.test/{Params['Bucket']}/{Params['Key']}?X-Amz-Expires={ExpiresIn}"
        )


def test_the_bucket_port_maps_conditional_put_and_missing_objects():
    client = FakeS3Client()
    storage = S3Storage(client, "amn-films")
    assert storage.head("a") is False and storage.get_json("a") is None
    storage.put_bytes("a", b'{"x": 1}', "application/json", if_none_match=True)
    assert client.calls[-1][1]["IfNoneMatch"] == "*"
    assert storage.head("a") is True and storage.get_json("a") == {"x": 1}
    with pytest.raises(PreconditionFailed):
        storage.put_bytes("a", b"{}", "application/json", if_none_match=True)
    storage.put_bytes("a", b"{}", "application/json")
    assert "IfNoneMatch" not in client.calls[-1][1]
    with pytest.raises(ConditionalPutUnsupported):
        S3Storage(FakeS3Client("unsupported"), "b").put_bytes("k", b"", "x", if_none_match=True)
    assert storage.presign_get("a", 10**9).endswith("X-Amz-Expires=604800")
    assert repr(storage) == "S3Storage(bucket='amn-films')"


def test_the_bucket_port_reports_a_refusal_as_a_storage_error():
    client = FakeS3Client()

    def denied(**kw: Any) -> Any:
        raise FakeClientError("AccessDenied", 403)

    client.head_object = denied  # type: ignore[method-assign]
    with pytest.raises(StorageError):
        S3Storage(client, "b").head("a")


class _Answer(io.BytesIO):
    def __enter__(self) -> _Answer:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def test_the_bucket_port_downloads_https_inputs_only():
    opened: list[str] = []

    def opener(url: str, timeout: float) -> _Answer:
        opened.append(url)
        return _Answer(b"picture")

    storage = S3Storage(FakeS3Client(), "b", opener=opener, max_download_bytes=10)
    assert storage.download_url("https://r2.example.test/b/x?sig=1") == b"picture"
    for bad in ("http://r2.example.test/x", "https://u:p@r2.example.test/x", "file:///etc"):
        with pytest.raises(StorageError):
            storage.download_url(bad)
    big = S3Storage(FakeS3Client(), "b", opener=opener, max_download_bytes=3)
    with pytest.raises(StorageError):
        big.download_url("https://r2.example.test/b/x")
    assert len(opened) == 2


def test_the_bucket_comes_from_the_endpoint_secrets(monkeypatch):
    import types

    made: list[dict[str, Any]] = []

    def client(*args: Any, **kwargs: Any) -> str:
        made.append({"args": args, **kwargs})
        return "client"

    class Config:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, "botocore", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "botocore.config", types.SimpleNamespace(Config=Config))
    env = {
        "AMN_S3_ENDPOINT_URL": "https://acct.r2.cloudflarestorage.com",
        "AMN_S3_BUCKET": "amn-films",
        "AMN_S3_ACCESS_KEY_ID": "AKIDEXAMPLE",
        "AMN_S3_SECRET_ACCESS_KEY": "fake-secret-for-tests-EXAMPLEKEY",  # pragma: allowlist secret
    }
    storage = S3Storage.from_env(env)
    assert storage.bucket == "amn-films"
    call = made[0]
    assert call["args"] == ("s3",) and call["region_name"] == "auto"
    assert call["endpoint_url"] == env["AMN_S3_ENDPOINT_URL"]
    assert call["config"].kw["signature_version"] == "s3v4"
    assert call["config"].kw["s3"] == {"addressing_style": "path"}
    assert "EXAMPLEKEY" not in repr(storage)
    with pytest.raises(StorageNotConfigured):
        S3Storage.from_env({**env, "AMN_S3_BUCKET": ""})
    with pytest.raises(StorageNotConfigured):
        S3Storage.from_env({**env, "AMN_S3_ENDPOINT_URL": "http://plain.example"})


# ----------------------------------------------------------------------------------- workflows

MODEL_SUFFIXES = (".safetensors", ".pth", ".pt", ".ckpt", ".gguf", ".bin")
SAVE_NODES = {"SaveImage", "SaveVideo"}
EXCLUDED = ("flux.1-dev", "flux-dev", "qwen-image-2.1", "hunyuan", "minimax")


def _lock() -> list[dict[str, Any]]:
    return json.loads((WORKER / "models.lock.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("model", sorted(WORKFLOWS))
def test_every_workflow_template_is_complete_and_bound(model):
    operation, name = WORKFLOWS[model]
    raw = json.loads((WORKER / "workflows" / f"{name}.json").read_text(encoding="utf-8"))
    assert raw["name"] == name and raw["model"] == model and raw["operation"] == operation
    assert raw["status"] == "UNPROVEN"  # until the paid bake-off runs it on the real image
    graph = raw["graph"]
    assert graph[raw["output_node"]]["class_type"] in SAVE_NODES
    workflow = amn_handler.load_workflow(name)  # validates every binding path
    required = {"prompt", "negative_prompt", "seed"}
    if operation == "image":
        required |= {"width", "height"}
    else:
        required |= {"source_image", "duration_frames"}
    assert required <= set(workflow.bindings)
    if operation == "video":
        assert workflow.frames and workflow.frames["remainder"] == 1
    used = {
        value
        for node in graph.values()
        for value in node["inputs"].values()
        if isinstance(value, str) and value.endswith(MODEL_SUFFIXES)
    }
    assert used == set(raw["models"])
    image = "stills" if operation == "image" else "motion"
    locked = {Path(entry["file"]).name for entry in _lock() if entry["image"] == image}
    assert used <= locked


def test_frame_counts_follow_each_models_rule():
    ltx = {"fps": 24, "multiple": 8, "remainder": 1}
    wan = {"fps": 16, "multiple": 4, "remainder": 1}
    assert [amn_handler.frame_count(s, ltx) for s in (1, 5, 6.5, 10)] == [25, 121, 161, 241]
    assert [amn_handler.frame_count(s, wan) for s in (1, 5, 10)] == [17, 81, 161]


# ------------------------------------------------------- the graphs against ComfyUI's own nodes

# Every node the three graphs may use, read from ComfyUI's source at tag v0.39.2 (commit
# 3c1b7a17fdf239d35ce98cc777756f572d089795, github.com/comfyanonymous/ComfyUI): class_type ->
# (required inputs, optional inputs, number of outputs). Dotted names are a DynamicCombo's
# nested inputs as the API prompt spells them (comfy_api/latest/_io.py finalize_prefix).
# Sources: nodes.py (loaders, CLIPTextEncode, KSampler*, VAE*, ImageScale, Save/LoadImage,
# LoraLoaderModelOnly); comfy_extras/nodes_model_advanced.py (ModelSampling*); nodes_sd3.py;
# nodes_wan.py; nodes_video.py (CreateVideo, SaveVideo); nodes_custom_sampler.py;
# nodes_lt.py; nodes_lt_audio.py; nodes_lt_upsampler.py; nodes_hunyuan.py
# (LatentUpscaleModelLoader); nodes_seedvr.py; nodes_frame_interpolation.py. The official
# templates these graphs follow (github.com/Comfy-Org/workflow_templates, templates/):
# image_qwen_Image_2512.json, utility_seedvr2_7b_int8_upscale_image.json,
# video_ltx2_5_i2v.json, video_wan2_2_14B_i2v.json, utility_video_frame_interpolation.json.
COMFY_NODES: dict[str, tuple[frozenset[str], frozenset[str], int]] = {
    "UNETLoader": (frozenset({"unet_name", "weight_dtype"}), frozenset(), 1),
    "CLIPLoader": (frozenset({"clip_name", "type"}), frozenset({"device"}), 1),
    "VAELoader": (frozenset({"vae_name"}), frozenset(), 1),
    "LoraLoaderModelOnly": (frozenset({"model", "lora_name", "strength_model"}), frozenset(), 1),
    "CLIPTextEncode": (frozenset({"text", "clip"}), frozenset(), 1),
    "KSampler": (
        frozenset(
            {
                "model",
                "seed",
                "steps",
                "cfg",
                "sampler_name",
                "scheduler",
                "positive",
                "negative",
                "latent_image",
                "denoise",
            }
        ),
        frozenset(),
        1,
    ),
    "KSamplerAdvanced": (
        frozenset(
            {
                "model",
                "add_noise",
                "noise_seed",
                "steps",
                "cfg",
                "sampler_name",
                "scheduler",
                "positive",
                "negative",
                "latent_image",
                "start_at_step",
                "end_at_step",
                "return_with_leftover_noise",
            }
        ),
        frozenset(),
        1,
    ),
    "VAEDecode": (frozenset({"samples", "vae"}), frozenset(), 1),
    "VAEDecodeTiled": (
        frozenset({"samples", "vae", "tile_size", "overlap", "temporal_size", "temporal_overlap"}),
        frozenset(),
        1,
    ),
    "VAEEncodeTiled": (
        frozenset({"pixels", "vae", "tile_size", "overlap", "temporal_size", "temporal_overlap"}),
        frozenset(),
        1,
    ),
    "ImageScale": (
        frozenset({"image", "upscale_method", "width", "height", "crop"}),
        frozenset(),
        1,
    ),
    "SaveImage": (frozenset({"images", "filename_prefix"}), frozenset(), 0),
    "LoadImage": (frozenset({"image"}), frozenset(), 2),
    "ModelSamplingAuraFlow": (frozenset({"model", "shift"}), frozenset(), 1),
    "ModelSamplingSD3": (frozenset({"model", "shift"}), frozenset(), 1),
    "EmptySD3LatentImage": (frozenset({"width", "height", "batch_size"}), frozenset(), 1),
    "WanImageToVideo": (
        frozenset({"positive", "negative", "vae", "width", "height", "length", "batch_size"}),
        frozenset({"clip_vision_output", "start_image", "ref_pad_image"}),
        3,
    ),
    "CreateVideo": (
        frozenset({"images", "fps"}),
        frozenset({"audio", "bit_depth", "color_space", "codec"}),
        1,
    ),
    "SaveVideo": (
        frozenset({"video", "filename_prefix", "format", "format.codec"}),
        frozenset({"codec", "format.codec.encoding"}),
        1,
    ),
    "RandomNoise": (frozenset({"noise_seed"}), frozenset(), 1),
    "KSamplerSelect": (frozenset({"sampler_name"}), frozenset(), 1),
    "ManualSigmas": (frozenset({"sigmas"}), frozenset(), 1),
    "SamplerCustomAdvanced": (
        frozenset({"noise", "guider", "sampler", "sigmas", "latent_image"}),
        frozenset(),
        2,
    ),
    "EmptyLTXVLatentVideo": (
        frozenset({"width", "height", "length", "batch_size"}),
        frozenset(),
        1,
    ),
    "LTXVImgToVideoInplace": (
        frozenset({"vae", "image", "latent", "strength", "bypass"}),
        frozenset(),
        1,
    ),
    "LTXVConditioning": (frozenset({"positive", "negative", "frame_rate"}), frozenset(), 2),
    "LTXVPreprocess": (frozenset({"image", "img_compression"}), frozenset(), 1),
    "LTXVDualCFGGuider": (
        frozenset({"model", "positive", "negative", "video_cfg", "audio_cfg"}),
        frozenset(),
        1,
    ),
    "LTXVEmptyLatentAudio": (
        frozenset({"frames_number", "frame_rate", "batch_size", "audio_vae"}),
        frozenset(),
        1,
    ),
    "LTXVConcatAVLatent": (frozenset({"video_latent", "audio_latent"}), frozenset(), 1),
    "LTXVSeparateAVLatent": (frozenset({"av_latent"}), frozenset(), 2),
    "LatentUpscaleModelLoader": (frozenset({"model_name"}), frozenset(), 1),
    "LTXVLatentUpsampler": (frozenset({"samples", "upscale_model", "vae"}), frozenset(), 1),
    "SeedVR2Preprocess": (frozenset({"resized_images"}), frozenset(), 1),
    "SeedVR2Conditioning": (frozenset({"model", "vae_conditioning"}), frozenset(), 2),
    "SeedVR2PostProcessing": (
        frozenset({"images", "original_resized_images", "color_correction_method"}),
        frozenset(),
        1,
    ),
    "FrameInterpolationModelLoader": (frozenset({"model_name"}), frozenset(), 1),
    "FrameInterpolate": (frozenset({"interp_model", "images", "multiplier"}), frozenset(), 1),
}
#: The loader input that names a weight -> the ComfyUI models folder it is read from
#: (folder_paths.py at v0.39.2: diffusion_models, text_encoders, vae, loras,
#: latent_upscale_models, frame_interpolation).
LOADER_FOLDERS = {
    ("UNETLoader", "unet_name"): "models/diffusion_models",
    ("CLIPLoader", "clip_name"): "models/text_encoders",
    ("VAELoader", "vae_name"): "models/vae",
    ("LoraLoaderModelOnly", "lora_name"): "models/loras",
    ("LatentUpscaleModelLoader", "model_name"): "models/latent_upscale_models",
    ("FrameInterpolationModelLoader", "model_name"): "models/frame_interpolation",
}


def _graph(name: str) -> dict[str, Any]:
    raw = json.loads((WORKER / "workflows" / f"{name}.json").read_text(encoding="utf-8"))
    return dict(raw["graph"])


@pytest.mark.parametrize("model", sorted(WORKFLOWS))
def test_every_node_and_input_exists_in_the_verified_comfyui(model):
    graph = _graph(WORKFLOWS[model][1])
    for node_id, node in graph.items():
        kind = node["class_type"]
        assert kind in COMFY_NODES, f"{node_id}: {kind} is not a ComfyUI v0.39.2 core node"
        required, optional, _outputs = COMFY_NODES[kind]
        names = set(node["inputs"])
        assert required <= names, f"{node_id} {kind} misses {sorted(required - names)}"
        assert names <= required | optional, f"{node_id} {kind} has {sorted(names - required)}"
        for value in node["inputs"].values():
            if isinstance(value, list):  # a link: [source node, output slot]
                source, slot = value
                assert source in graph, f"{node_id} links to a missing node {source}"
                outputs = COMFY_NODES[graph[source]["class_type"]][2]
                assert 0 <= slot < outputs, f"{node_id} links to {source} slot {slot}"


@pytest.mark.parametrize("model", sorted(WORKFLOWS))
def test_every_weight_is_locked_where_its_loader_reads_it(model):
    operation, name = WORKFLOWS[model]
    image = "stills" if operation == "image" else "motion"
    folders = {
        Path(entry["file"]).name: entry["target_dir"]
        for entry in _lock()
        if entry["image"] == image
    }
    for node in _graph(name).values():
        for field, value in node["inputs"].items():
            folder = LOADER_FOLDERS.get((node["class_type"], field))
            if folder is not None:
                assert folders.get(value) == folder, f"{value} must be locked under {folder}"


def test_ltx_samples_video_with_its_audio_latent_and_delivers_no_audio():
    # LTX-2.5 is an audio-video model: the official template samples a video+audio latent
    # (LTXVConcatAVLatent) and separates it before decoding. The studio voices its own films,
    # so the audio latent is never decoded and the video carries no audio track.
    graph = _graph("ltx_2_5_i2v")
    kinds = [node["class_type"] for node in graph.values()]
    assert kinds.count("LTXVConcatAVLatent") == 2 and kinds.count("LTXVSeparateAVLatent") == 2
    assert "LTXVEmptyLatentAudio" in kinds and "LTXVAudioVAEDecode" not in kinds
    assert all(
        "audio" not in n["inputs"] for n in graph.values() if n["class_type"] == "CreateVideo"
    )
    sizes = [
        (n["inputs"]["width"], n["inputs"]["height"])
        for n in graph.values()
        if n["class_type"] == "EmptyLTXVLatentVideo"
    ]
    assert sizes == [(544, 960)]  # half of 1088x1920; the x2 latent upsampler doubles it
    loaders = {n["inputs"].get("type") for n in graph.values() if n["class_type"] == "CLIPLoader"}
    assert loaders == {"ltxv"}
    duration = amn_handler.load_workflow("ltx_2_5_i2v").bindings["duration_frames"]
    assert {(graph[node]["class_type"], field) for node, _, field in duration} == {
        ("EmptyLTXVLatentVideo", "length"),
        ("LTXVEmptyLatentAudio", "frames_number"),
    }


def test_the_still_route_ends_exactly_at_1530x2720_after_seedvr2():
    graph = _graph("qwen_image_2512_seedvr2")
    latent = [n for n in graph.values() if n["class_type"] == "EmptySD3LatentImage"]
    assert [(n["inputs"]["width"], n["inputs"]["height"]) for n in latent] == [(928, 1664)]
    kinds = {node["class_type"] for node in graph.values()}
    assert {"SeedVR2Preprocess", "SeedVR2Conditioning", "SeedVR2PostProcessing"} <= kinds
    workflow = amn_handler.load_workflow("qwen_image_2512_seedvr2")
    (w_node, _, _), (h_node, _, _) = workflow.bindings["width"][0], workflow.bindings["height"][0]
    assert graph[w_node]["inputs"]["width"] == STILL_SIZE[0]
    assert graph[h_node]["inputs"]["height"] == STILL_SIZE[1]


def test_the_lock_names_the_files_the_official_repos_hold():
    # File names as listed by huggingface.co/api/models/<repo>/tree/main on 2026-10-08.
    files = {(entry["repo"], entry["file"]) for entry in _lock()}
    ltx = "Lightricks/LTX-2.5"
    for wanted in (
        (ltx, "diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"),
        (ltx, "text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"),
        (ltx, "vae/ltx-2.5-video-vae-bf16.safetensors"),
        (ltx, "vae/ltx-2.5-audio-vae-bf16.safetensors"),
        (ltx, "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"),
        ("Comfy-Org/SeedVR2", "diffusion_models/seedvr2_7b_int8_convrot.safetensors"),
        ("Comfy-Org/SeedVR2", "vae/seedvr2_ema_vae_fp16.safetensors"),
        ("Comfy-Org/frame_interpolation", "frame_interpolation/rife_v4.26.safetensors"),
    ):
        assert wanted in files, wanted
    assert all(entry["repo"] for entry in _lock())  # every weight from a pinnable repo


# --------------------------------------------------------------------------------- lock files


def test_the_model_lock_names_every_weight_and_its_licence():
    entries = _lock()
    keys = {
        "name",
        "image",
        "repo",
        "revision",
        "file",
        "sha256",
        "size_bytes",
        "licence",
        "licence_url",
        "gated",
        "target_dir",
    }
    for entry in entries:
        assert keys <= set(entry), entry
        assert entry["image"] in ("stills", "motion")
        assert entry["licence"] and entry["licence_url"].startswith("https://")
        assert isinstance(entry["gated"], bool)
        assert not any(bad in json.dumps(entry).lower() for bad in EXCLUDED)
    text = json.dumps(entries)
    for wanted in ("Qwen-Image-2512", "SeedVR2", "LTX-2.5", "Wan2.2", "LightX2V", "RIFE"):
        assert wanted in text
    ltx = [entry for entry in entries if entry["name"].startswith("LTX-2.5")]
    assert ltx and all(entry["gated"] for entry in ltx)
    assert all("LTX-2" in entry["licence"] for entry in ltx)


def test_the_custom_node_lock_pins_repos_and_licences():
    # SeedVR2 and RIFE are ComfyUI core nodes since the verified release: no custom node is
    # needed today; any later one must name its GitHub repo, its commit and its licence.
    nodes = json.loads((WORKER / "custom_nodes.lock.json").read_text(encoding="utf-8"))
    assert isinstance(nodes, list)
    for node in nodes:
        assert {"name", "image", "repo", "commit", "licence"} <= set(node)
        assert node["repo"].startswith("https://github.com/")


# --------------------------------------------------------------------------------- build plan


def test_the_build_plan_refuses_while_anything_is_unpinned(monkeypatch):
    # The base, ComfyUI and the public weights are pinned (2026-10-08); the gated LTX-2.5
    # checksums wait for the Owner's token (`build resolve`), so motion still refuses.
    with pytest.raises(ValueError) as refused:
        build.plan("motion", "registry.example.test/amn", "v1")
    assert "LTX-2.5" in str(refused.value) and "sha256 not pinned" in str(refused.value)
    monkeypatch.setattr(build, "BASE_DIGEST", None)
    for target in ("stills", "motion"):
        with pytest.raises(ValueError) as refused:
            build.plan(target, "registry.example.test/amn", "v1")
        assert "BASE_DIGEST" in str(refused.value)


def _resolved(monkeypatch) -> None:
    monkeypatch.setattr(build, "BASE_DIGEST", "sha256:" + "a" * 64)
    monkeypatch.setattr(build, "COMFYUI_VERSION", "0.40.0")
    entries = [
        {**entry, "revision": "b" * 40, "sha256": "c" * 64, "size_bytes": 1} for entry in _lock()
    ]
    monkeypatch.setattr(build, "load_models_lock", lambda: entries)
    nodes = [
        {
            "name": "ExampleNode",
            "image": "stills",
            "repo": "https://github.com/example/ExampleNode",
            "commit": None,
            "licence": "MIT",
        }
    ]
    pinned = [{**node, "commit": "d" * 40} for node in nodes]
    monkeypatch.setattr(build, "load_nodes_lock", lambda: pinned)
    monkeypatch.setenv("AMN_WORKER_IMAGE", "stills")


def test_the_build_plan_once_pinned_builds_with_a_secret_and_pushes_only_when_asked(monkeypatch):
    _resolved(monkeypatch)
    commands = build.plan("motion", "registry.example.test/amn", "v1")
    assert len(commands) == 1
    command = commands[0]
    assert command[:3] == ["docker", "buildx", "build"]
    assert command[command.index("--target") + 1] == "motion"
    assert "BASE_DIGEST=sha256:" + "a" * 64 in command
    assert "COMFYUI_VERSION=0.40.0" in command
    assert command[command.index("--secret") + 1] == "id=hf_token,env=HF_TOKEN"
    assert "registry.example.test/amn/amn-motion:v1" in command
    pushed = build.plan("stills", "registry.example.test/amn", "v1", push=True)
    assert pushed[-1] == ["docker", "push", "registry.example.test/amn/amn-stills:v1"]
    with pytest.raises(ValueError):
        build.plan("stills", "https://registry.example.test", "v1")
    with pytest.raises(ValueError):
        build.plan("stills", "registry.example.test/amn", "v1; rm -rf /")


def test_the_build_plan_refuses_one_unresolved_weight(monkeypatch):
    _resolved(monkeypatch)
    entries = build.load_models_lock()
    entries[0] = {**entries[0], "sha256": None}
    monkeypatch.setattr(build, "load_models_lock", lambda: entries)
    with pytest.raises(ValueError) as refused:
        build.plan(entries[0]["image"], "registry.example.test/amn", "v1")
    assert entries[0]["name"] in str(refused.value)


def test_main_prints_and_never_executes_without_both_switches(monkeypatch, capsys):
    _resolved(monkeypatch)
    ran: list[Any] = []
    monkeypatch.setattr(build, "run_command", lambda args: ran.append(args))
    monkeypatch.delenv("AMN_BUILD_I_ACCEPT_60GB", raising=False)
    argv = ["plan", "stills", "--registry", "registry.example.test/amn", "--tag", "v1"]
    assert build.main(argv) == 0
    assert "docker buildx build" in capsys.readouterr().out
    assert build.main([*argv, "--execute"]) != 0  # the env switch is missing
    assert ran == []
    monkeypatch.setenv("AMN_BUILD_I_ACCEPT_60GB", "1")
    assert build.main([*argv, "--execute", "--push"]) == 0
    assert [args[:2] for args in ran] == [["docker", "buildx"], ["docker", "push"]]


def test_main_refuses_an_unpinned_plan(capsys):
    argv = ["plan", "motion", "--registry", "registry.example.test/amn", "--tag", "v1"]
    assert build.main(argv) != 0
    assert "sha256 not pinned" in capsys.readouterr().err


def test_fetch_verifies_every_weight_and_keeps_the_token_out_of_urls(monkeypatch, tmp_path):
    _resolved(monkeypatch)
    payload = b"weights"
    entries = [
        {**entry, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)}
        for entry in build.load_models_lock()
    ]
    monkeypatch.setattr(build, "load_models_lock", lambda: entries)
    token = tmp_path / "hf_token"
    token.write_text("hf_fake_token\n", encoding="utf-8")  # pragma: allowlist secret
    seen: list[Any] = []

    def opener(request: Any, timeout: float) -> _Answer:
        seen.append(request)
        return _Answer(payload)

    written = build.fetch("stills", tmp_path / "models", token_path=token, opener=opener)
    stills = [entry for entry in entries if entry["image"] == "stills"]
    assert len(written) == len(stills)
    for path in written:
        assert path.read_bytes() == payload
    for request in seen:
        assert "hf_fake_token" not in request.full_url
        assert request.get_header("Authorization") == "Bearer hf_fake_token"
    assert seen[0].full_url.startswith("https://huggingface.co/")
    assert "/resolve/" + "b" * 40 + "/" in seen[0].full_url

    def corrupt(request: Any, timeout: float) -> _Answer:
        return _Answer(b"not the weights")

    with pytest.raises(ValueError):
        build.fetch("stills", tmp_path / "other", token_path=token, opener=corrupt)
    leftovers = [p for p in (tmp_path / "other").rglob("*") if p.is_file()]
    assert leftovers == []


def test_fetch_refuses_unresolved_weights_before_any_download(tmp_path):
    opened: list[Any] = []
    with pytest.raises(ValueError):
        build.fetch("motion", tmp_path, opener=lambda *a, **k: opened.append(a))
    assert opened == []


def test_fetch_sends_the_token_to_hugging_face_only(monkeypatch, tmp_path):
    _resolved(monkeypatch)
    payload = b"weights"
    entries = [
        {
            **entry,
            "repo": None,
            "url": "https://github.com/example/releases/download/v1/model.safetensors",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        }
        for entry in build.load_models_lock()
        if entry["image"] == "stills"
    ][:1]
    monkeypatch.setattr(build, "load_models_lock", lambda: entries)
    token = tmp_path / "hf_token"
    token.write_text("hf_fake_token\n", encoding="utf-8")  # pragma: allowlist secret
    seen: list[Any] = []

    def opener(request: Any, timeout: float) -> _Answer:
        seen.append(request)
        return _Answer(payload)

    build.fetch("stills", tmp_path / "models", token_path=token, opener=opener)
    assert seen and all(request.get_header("Authorization") is None for request in seen)


def test_a_redirect_away_from_hugging_face_drops_the_token():
    import urllib.request

    handler = build.TokenSafeRedirect()
    request = urllib.request.Request(
        "https://huggingface.co/org/repo/resolve/" + "b" * 40 + "/file.safetensors",
        headers={"Authorization": "Bearer hf_fake_token"},  # pragma: allowlist secret
    )
    for target, kept in (
        ("https://cas-bridge.xethub.hf.co/xet/file?X-Amz-Signature=x", False),
        ("https://cdn-lfs.example.test/file", False),
        ("https://huggingface.co/api/resolve-cache/file", True),
    ):
        moved = handler.redirect_request(request, None, 302, "Found", {}, target)
        assert moved is not None
        assert (moved.get_header("Authorization") is not None) is kept, target


def test_fetch_and_nodes_run_only_inside_the_image_build(monkeypatch, tmp_path):
    _resolved(monkeypatch)
    monkeypatch.delenv("AMN_WORKER_IMAGE", raising=False)
    opened: list[Any] = []
    with pytest.raises(ValueError) as refused:
        build.fetch("stills", tmp_path, opener=lambda *a, **k: opened.append(a))
    assert "AMN_WORKER_IMAGE" in str(refused.value)
    ran: list[list[str]] = []
    with pytest.raises(ValueError):
        build.install_nodes("stills", tmp_path, run=lambda args: ran.append(args))
    monkeypatch.setenv("AMN_WORKER_IMAGE", "motion")  # the other image's stage
    with pytest.raises(ValueError):
        build.fetch("stills", tmp_path, opener=lambda *a, **k: opened.append(a))
    assert opened == [] and ran == []


def test_nodes_clone_each_pinned_commit(monkeypatch, tmp_path):
    _resolved(monkeypatch)
    ran: list[list[str]] = []
    build.install_nodes("stills", tmp_path, run=lambda args: ran.append(args))
    assert ran[0][:2] == ["git", "clone"]
    assert ["git", "-C", ran[0][-1], "checkout", "d" * 40] == ran[1]


# ------------------------------------------------------------------------------- image recipe


def test_the_dockerfile_pins_its_base_and_keeps_the_token_out_of_layers():
    text = (WORKER / "Dockerfile").read_text(encoding="utf-8")
    # The newest published base (5.11.0 has a GitHub tag but no image on Docker Hub).
    assert "ARG BASE_IMAGE=runpod/worker-comfyui:5.10.0-base" in text
    lines = [line.strip() for line in text.splitlines()]
    assert "ARG BASE_DIGEST" in lines and "ARG COMFYUI_VERSION" in lines  # no defaults
    assert "FROM ${BASE_IMAGE}@${BASE_DIGEST} AS base" in text
    assert "AS stills" in text and "AS motion" in text
    assert text.count("--mount=type=secret,id=hf_token") == 2
    assert "HF_TOKEN" not in text
    assert 'CMD ["python", "-u", "-m", "runpod_worker.amn_handler"]' in text
    requirements = (WORKER / "requirements.txt").read_text(encoding="utf-8")
    assert any(line.startswith("boto3==") for line in requirements.splitlines())
    ignore = (WORKER / ".dockerignore").read_text(encoding="utf-8")
    assert "__pycache__" in ignore
    # A stray credential next to the code never reaches a layer (the image is pushed).
    for pattern in (".env", ".env.*", "*.key", "hf_token", "*.pem"):
        assert pattern in ignore.splitlines(), pattern


def test_the_readme_tells_the_owner_the_endpoint_settings():
    text = (WORKER / "README.md").read_text(encoding="utf-8")
    for needle in (
        "AMN_S3_ENDPOINT_URL",
        "AMN_S3_BUCKET",
        "AMN_S3_REGION",
        "AMN_S3_ACCESS_KEY_ID",
        "AMN_S3_SECRET_ACCESS_KEY",
        "COMFY_HOST",
        "idleTimeout",
        "2400000",
        "RTX PRO 6000",
        "FlashBoot",
        "/v2/catalog/gpus",
        "UNPROVEN",
    ):
        assert needle in text, needle
