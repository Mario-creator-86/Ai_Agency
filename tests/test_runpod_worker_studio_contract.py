"""The studio's real /run body through the worker's real handler, and back.

``tests/test_runpod_batch.py`` fakes the worker's answers by hand and
``tests/test_runpod_worker.py`` feeds the handler hand-written jobs; here the two real halves
meet: the studio (``submit_batch``) writes the job, the worker (``amn_handler.handler``, a fake
ComfyUI, the same fake bucket) runs it, and the studio collects what the worker wrote, from
the manifests and from ``/status``. Nothing leaves the process.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from app.providers.runpod.adapters import RunPodVideoAdapter
from app.providers.runpod.jobs import GenerationJob
from runpod_worker import amn_handler, contract, postprocess
from runpod_worker.comfy import ComfyFailed, find_output
from runpod_worker.storage import PreconditionFailed, StorageError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_runpod_batch import Cloud, Session_, adapter, request
from test_runpod_worker import mp4, png

BUCKET_HOST = "account.r2.example"
BUCKET_PATH = "/amn-films/"


class CloudBucket:
    """The worker's StoragePort over the studio test's fake bucket (the same objects)."""

    def __init__(self, cloud: Cloud) -> None:
        self.cloud = cloud

    def _key(self, url: str) -> str:
        parts = urlsplit(url)
        assert parts.hostname == BUCKET_HOST
        return parts.path.removeprefix(BUCKET_PATH)

    def head(self, key: str) -> bool:
        return key in self.cloud.objects

    def get_json(self, key: str) -> dict[str, Any] | None:
        data = self.cloud.objects.get(key)
        return None if data is None else json.loads(data)

    def put_bytes(self, key: str, data: bytes, mime: str, *, if_none_match: bool = False) -> None:
        if if_none_match and key in self.cloud.objects:
            raise PreconditionFailed(key)
        self.cloud.objects[key] = data

    def presign_get(self, key: str, ttl: int) -> str:
        return f"https://{BUCKET_HOST}{BUCKET_PATH}{key}?X-Amz-Expires={ttl}&X-Amz-Signature=w"

    def download_url(self, url: str) -> bytes:
        data = self.cloud.objects.get(self._key(url))
        if data is None:
            raise StorageError("no such input")
        return bytes(data)


class Comfy:
    """A ComfyUI that 'renders' 928x1664 stills (SeedVR2 output is then exact) or clips."""

    def __init__(self, tmp: Path, *, fail: set[int] | None = None) -> None:
        self.out = tmp / "comfy-out"
        self.out.mkdir(parents=True, exist_ok=True)
        self.graphs: list[dict[str, Any]] = []
        self.uploads: dict[str, bytes] = {}
        self.fail = fail or set()

    def wait_ready(self, timeout: float) -> float:
        return 0.0

    def upload_input(self, name: str, data: bytes) -> str:
        self.uploads[name] = data
        return name

    def queue(self, graph: dict[str, Any]) -> str:
        self.graphs.append(graph)
        if len(self.graphs) - 1 in self.fail:
            raise ComfyFailed("COMFY_FAILED", "out of memory")
        return f"p{len(self.graphs) - 1}"

    def wait(self, prompt_id: str, timeout: float) -> dict[str, Any]:
        number = int(prompt_id[1:])
        graph = self.graphs[number]
        save = next(k for k, n in graph.items() if n["class_type"] in ("SaveImage", "SaveVideo"))
        if graph[save]["class_type"] == "SaveImage":
            name, data = f"s{number}.png", png(928, 1664)
        else:
            name, data = f"c{number}.mp4", mp4(1088, 1920)
        (self.out / name).write_bytes(data)
        entry = {"filename": name, "subfolder": "", "type": "output"}
        return {"outputs": {save: {"images": [entry]}}, "status": {"completed": True}}

    def output_path(self, history: dict[str, Any], node_id: str) -> Path:
        return find_output(history, node_id, self.out)


def _work(cloud: Cloud, job: str, comfy: Comfy) -> dict[str, Any]:
    raw = {"id": job, "input": cloud.jobs[job]["input"]}
    return dict(amn_handler.handler(raw, comfy=comfy, storage=CloudBucket(cloud)))


def _rows(engine: Any) -> list[GenerationJob]:
    with Session(engine) as s:
        return list(s.scalars(select(GenerationJob).order_by(GenerationJob.batch_index)).all())


def test_a_still_round_runs_on_the_worker_and_lands_in_the_studio(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    asked = [request("1", 0), request("1", 1)]
    run = made.submit_batch(asked, session=Session_(), on_submitted=lambda item: None)
    comfy = Comfy(tmp_path)
    out = _work(cloud, "job-1", comfy)
    contract.validate_output(out)
    assert [item["status"] for item in out["items"]] == ["COMPLETED", "COMPLETED"]
    # The item's own seed and prompt reached the graph (both samplers' seeds).
    for graph, wanted in zip(comfy.graphs, asked, strict=True):
        assert graph["3"]["inputs"]["seed"] == wanted.seed == graph["45"]["inputs"]["seed"]
        assert graph["6"]["inputs"]["text"] == wanted.prompt
    outcomes = run.poll()  # from the manifests the worker wrote
    assert [o.state for o in outcomes] == ["COMPLETED", "COMPLETED"] and run.done()
    for outcome, item in zip(outcomes, out["items"], strict=True):
        data = outcome.path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
        assert data.startswith(b"\x89PNG") and (item["width"], item["height"]) == (1530, 2720)
    rows = _rows(engine)
    assert [row.status for row in rows] == ["COMPLETED", "COMPLETED"]
    assert [row.output["seed"] for row in rows] == [r.seed for r in asked]
    assert all("url" not in row.output for row in rows)


def test_status_output_of_the_real_handler_is_collected_and_a_failed_item_stays_failed(
    engine, tmp_path
):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    run = made.submit_batch(
        [request("1", 0), request("1", 1)], session=Session_(), on_submitted=lambda item: None
    )
    out = _work(cloud, "job-1", Comfy(tmp_path, fail={1}))
    for key in [k for k in cloud.objects if "/manifests/" in f"/{k}"]:
        del cloud.objects[key]  # only /status remains (the manifests' bucket was emptied)
    cloud.status_answers["job-1"] = [
        {
            "id": "job-1",
            "status": "COMPLETED",
            "delayTime": 1000,
            "executionTime": 2000,
            "output": out,
        }
    ]
    states = {(o.state, o.error) for o in run.poll()}
    assert states == {("COMPLETED", None), ("FAILED", "COMFY_FAILED")}
    assert [row.status for row in _rows(engine)] == ["COMPLETED", "FAILED"]


def test_an_uncertain_round_resent_with_the_same_keys_is_reused_not_rendered_again(
    engine, tmp_path
):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.submit_batch([request("1", 0)], session=Session_(), on_submitted=lambda item: None)
    comfy = Comfy(tmp_path)
    first = _work(cloud, "job-1", comfy)
    # The same keys in a second job (what the studio sends after an uncertain /run).
    cloud.jobs["job-2"] = cloud.jobs["job-1"]
    again = _work(cloud, "job-2", comfy)
    assert len(comfy.graphs) == 1
    assert again["items"][0]["reused"] is True and again["items"][0]["gpu_seconds"] == 0.0
    assert again["items"][0]["sha256"] == first["items"][0]["sha256"]


def test_a_clip_round_uploads_the_first_frame_runs_and_lands_as_1080x1920(
    engine, tmp_path, monkeypatch
):
    def encode(args: list[str]) -> None:
        Path(args[-1]).write_bytes(mp4(1080, 1920))

    monkeypatch.setattr(postprocess, "run_ffmpeg", encode)
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud, cls=RunPodVideoAdapter)
    asked = request("1", 0, operation="video")
    run = made.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    comfy = Comfy(tmp_path)
    out = _work(cloud, "job-1", comfy)
    item = contract.validate_output(out)["items"][0]
    assert item["status"] == "COMPLETED", item
    frame_sha = hashlib.sha256(asked.source_image or b"").hexdigest()
    assert list(comfy.uploads) == [f"{frame_sha}.png"]
    graph = comfy.graphs[0]
    assert graph["20"]["inputs"]["image"] == f"{frame_sha}.png"
    assert graph["30"]["inputs"]["length"] == graph["32"]["inputs"]["frames_number"] == 121
    assert graph["34"]["inputs"]["noise_seed"] == asked.seed
    outcome = run.poll()[0]
    assert outcome.state == "COMPLETED" and outcome.mime == "video/mp4"
    row = _rows(engine)[0]
    assert (row.output["width"], row.output["height"], row.output["fps"]) == (1080, 1920, 24)


@pytest.mark.parametrize("negative", [None, "blur, text"])
def test_the_studios_negative_prompt_or_the_templates_reaches_the_graph(engine, tmp_path, negative):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.submit_batch(
        [request("1", 0, negative_prompt=negative)],
        session=Session_(),
        on_submitted=lambda item: None,
    )
    comfy = Comfy(tmp_path)
    _work(cloud, "job-1", comfy)
    text = comfy.graphs[0]["7"]["inputs"]["text"]
    assert text == negative if negative else text.strip()
