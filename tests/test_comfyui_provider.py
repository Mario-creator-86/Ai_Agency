"""Local adapter contracts; these tests never submit work to a real GPU."""

import asyncio
import json
import struct
from uuid import uuid4

import pytest
from app.providers import comfyui
from app.providers.comfyui import ComfyConnection, ComfyImageAdapter, ComfyVideoAdapter, local_url
from app.providers.media_http import MediaProviderError, TaskStillOpen


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(comfyui, "available_memory", lambda: 12 * 1024**3)
    monkeypatch.setattr(comfyui, "watch_job", lambda *a: None)
    return {"base_url": "http://localhost:8188"}


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://127.0.0.1.evil",
        "http://user@localhost",
        "http://localhost/path",
        "http://localhost?secret=1",
    ],
)
def test_only_loopback_without_secrets_or_redirect_targets(url):
    with pytest.raises(ValueError):
        local_url(url)


def test_missing_model_is_not_substituted(local):
    with pytest.raises(MediaProviderError, match="necunoscut"):
        ComfyVideoAdapter(local, "other-model").profile()


def test_busy_or_low_ram_does_not_submit(local, monkeypatch):
    calls = []

    def request(base, method, route, body=None, content_type=None):
        calls.append((method, route))
        return json.dumps({"queue_running": [[1, "someone-else"]]}).encode()

    monkeypatch.setattr(comfyui, "_request", request)
    c = ComfyConnection(local)
    with pytest.raises(MediaProviderError) as busy:
        asyncio.run(c._submit({}, "image"))
    assert busy.value.code == "LOCAL_BUSY"
    assert calls == [("GET", "/queue")]
    calls.clear()
    monkeypatch.setattr(comfyui, "available_memory", lambda: 2 * 1024**3)
    with pytest.raises(MediaProviderError) as memory:
        asyncio.run(c._submit({}, "image"))
    assert memory.value.code == "LOCAL_LOW_RAM"
    assert calls == []


def test_ambiguous_submit_keeps_client_job_id_and_never_resends(local, monkeypatch):
    posts = []

    def request(base, method, route, body=None, content_type=None):
        if route == "/queue":
            return b"{}"
        posts.append(json.loads(body))
        raise MediaProviderError("disconnected", unanswered=True)

    monkeypatch.setattr(comfyui, "_request", request)
    with pytest.raises(TaskStillOpen) as exc:
        asyncio.run(ComfyConnection(local)._submit({}, "image"))
    assert len(posts) == 1
    assert exc.value.task_id == posts[0]["prompt_id"]


def test_completed_video_and_failed_job_match_existing_collector(local, monkeypatch):
    identifier = str(uuid4())
    history = {
        identifier: {
            "status": {"completed": True},
            "outputs": {"4": {"images": [{"filename": "clip.mp4", "type": "output"}]}},
        }
    }

    def request(base, method, route, body=None, content_type=None):
        return b"actual-clip" if route.startswith("/view?") else json.dumps(history).encode()

    monkeypatch.setattr(comfyui, "_request", request)
    c = ComfyVideoAdapter(local, "I2V_HERO_RX9070")
    collected = asyncio.run(c.collect_task(identifier))
    assert collected["state"] == "SUCCEEDED"
    assert collected["outputs"] == [(b"actual-clip", "video/mp4")]
    assert asyncio.run(c.get_generation_status(identifier)).status == "COMPLETED"
    history[identifier]["status"] = {"status_str": "error"}
    assert asyncio.run(c.collect_task(identifier))["state"] == "FAILED"


def test_still_job_is_saved_before_poll_and_reports_native_dimensions(local, monkeypatch):
    submitted = []
    identifier = str(uuid4())
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 768, 1344)

    def request(base, method, route, body=None, content_type=None):
        if route == "/queue":
            return b"{}"
        if route == "/prompt":
            graph = json.loads(body)["prompt"]
            assert graph["2"]["inputs"]["text"] == "new scene"
            return json.dumps({"prompt_id": identifier}).encode()
        assert submitted == [identifier]
        if route.startswith("/history"):
            return json.dumps(
                {
                    identifier: {
                        "status": {"completed": True},
                        "outputs": {"7": {"images": [{"filename": "still.png", "type": "output"}]}},
                    }
                }
            ).encode()
        return png

    monkeypatch.setattr(comfyui, "_request", request)
    c = ComfyImageAdapter(local, "SDXL_LOCAL")
    images = asyncio.run(
        c.generate_candidates("new scene", ratio="9:16", count=1, on_submitted=submitted.append)
    )
    assert (images[0].width, images[0].height) == (768, 1344)
    assert images[0].cost_vr == "0"


def test_reference_and_long_shot_refused_before_network(local, monkeypatch):
    monkeypatch.setattr(comfyui, "_request", lambda *a: pytest.fail("must not call GPU"))
    with pytest.raises(MediaProviderError) as reference:
        asyncio.run(
            ComfyImageAdapter(local, "SDXL_LOCAL").generate_image(
                "person", extra={"reference_image": {"bytes": b"portrait"}}
            )
        )
    assert reference.value.code == "LOCAL_REFERENCE_UNSUPPORTED"
    with pytest.raises(MediaProviderError) as duration:
        asyncio.run(
            ComfyVideoAdapter(local, "I2V_HERO_RX9070").create_generation(
                "walk", image_ref=b"image", duration_seconds=8
            )
        )
    assert duration.value.code == "LOCAL_DURATION"
