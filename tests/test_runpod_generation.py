"""RunPod contracts: all cloud traffic is replaced; no paid calls in this suite."""

import asyncio
import importlib
import importlib.util
import json
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session


def module(name):
    assert importlib.util.find_spec("app.providers.runpod") is not None, "RunPod provider missing"
    return importlib.import_module("app.providers.runpod." + name)


def config(**values):
    return module("config").RunPodConfig(_env_file=None, **values)


# Explicit routes: these tests check the router, not whichever default route is current.
ROUTES = {
    "IMAGE_QUALITY": "Qwen-Image-2512",
    "IMAGE_HERO": "Qwen-Image-2512",
    "VIDEO_QUALITY": "Wan-2.2",
    "VIDEO_HERO": "LTX-2.5",
    "VIDEO_AUTO": "AUTO",
}


def request(operation="image", **values):
    cls = module("models").ImageRequest if operation == "image" else module("models").VideoRequest
    return cls(
        **(
            {"project_id": "film-1", "scene_id": "scene-4", "prompt": "A mountain at sunrise"}
            | values
        )
    )


def test_disabled_and_infrastructure_safe_defaults():
    c = config()
    assert not c.enabled and not c.mock and not c.allow_infra_actions
    assert not c.auto_start and not c.auto_stop
    assert c.generation_base_url is None and c.endpoint_id is None
    assert c.api_key.get_secret_value() == ""


def test_environment_configuration_and_secrets(monkeypatch):
    monkeypatch.setenv("RUNPOD_ENABLED", "true")
    monkeypatch.setenv("RUNPOD_API_KEY", "test-secret-not-a-real-key")  # pragma: allowlist secret
    monkeypatch.setenv("RUNPOD_MODE", "serverless")
    c = config()
    assert c.enabled and c.mode == "serverless"
    assert "test-secret-not-a-real-key" not in repr(c)
    assert "test-secret-not-a-real-key" not in c.model_dump_json()


@pytest.mark.parametrize(
    "values",
    [
        {"mode": "unknown"},
        {"request_timeout": 0},
        {"poll_interval": 0},
        {"max_retries": -1},
        {"generation_base_url": "http://cloud.example"},
        {
            "generation_base_url": "https://user:password@cloud.example"  # pragma: allowlist secret
        },
        {"gpu_cost_per_hour": -1},
        {"auto_start": True, "mode": "pod"},
    ],
)
def test_invalid_configuration(values):
    with pytest.raises(ValidationError):
        config(**values)


def test_image_serialization_and_logical_router():
    r = request(negative_prompt="blur", quality="HERO", seed=9, qa_feedback=["bad hands"])
    data = r.model_dump(mode="json", exclude_none=True)
    assert data["aspect_ratio"] == "9:16"
    assert data["negative_prompt"] == "blur" and data["qa_feedback"] == ["bad hands"]
    assert config(model_routes=ROUTES).route("image", r.quality, None) == "Qwen-Image-2512"
    assert (
        config(model_routes={"IMAGE_HERO": "custom-qwen"}).route("image", "HERO", None)
        == "custom-qwen"
    )


def test_video_serialization_and_model_route():
    r = request(
        "video",
        source_image="https://assets.example/source.png",
        duration=5,
        fps=24,
        motion_strength=0.5,
        camera_motion="pan",
        quality="HERO",
        model="AUTO",
    )
    assert r.model_dump()["duration"] == 5
    routes = config(model_routes=ROUTES)
    assert routes.route("video", "HERO", "AUTO") == "LTX-2.5"
    assert routes.route("video", "QUALITY", None) == "Wan-2.2"
    assert routes.route("video", "AUTO", "AUTO") == "AUTO"


@pytest.mark.parametrize(
    "values",
    [
        {"width": -1},
        {"seed": -1},
        {"quality": "FAST"},
        {"project_id": ""},
        {"aspect_ratio": "oops"},
    ],
)
def test_invalid_image_request(values):
    with pytest.raises(ValidationError):
        module("models").ImageRequest(
            project_id=values.pop("project_id", "p"), scene_id="s", prompt="one", **values
        )


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, host, method, path, headers, body=None, **kwargs):
        self.calls.append(
            (host, method, path, dict(headers), json.loads(body) if body else None, kwargs)
        )
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value, b"", "application/json"


def provider(engine, transport=None, **values):
    return module("provider").RunPodGenerationProvider(
        config(
            **(
                {
                    "enabled": True,
                    # The per-job Pod contract; serverless tests pass mode="serverless".
                    "mode": "pod",
                    "api_key": "fake-key",  # pragma: allowlist secret — synthetic test value
                    "generation_base_url": "https://cloud.example",
                    "poll_interval": 0.01,
                }
                | values
            )
        ),
        engine,
        transport=transport,
    )


def test_pod_submission_restart_and_idempotency(engine):
    t = FakeTransport(
        [{"job_id": "remote-1", "status": "QUEUED"}, {"job_id": "remote-1", "status": "RUNNING"}]
    )
    p = provider(engine, t)
    first = asyncio.run(p.generate_image(request()))
    second = asyncio.run(provider(engine, t).generate_image(request()))
    assert first.remote_job_id == second.remote_job_id == "remote-1"
    assert sum(c[1] == "POST" for c in t.calls) == 1
    assert t.calls[0][2] == "/generate/image"
    assert t.calls[0][3]["Idempotency-Key"] == first.idempotency_key


def test_same_key_different_payload_refused(engine):
    p = provider(engine, FakeTransport([{"job_id": "remote-1", "status": "QUEUED"}]))
    asyncio.run(p.generate_image(request()))
    with pytest.raises(module("errors").IdempotencyConflict):
        asyncio.run(p.generate_image(request(prompt="different")))


def legacy_serverless_row(p, operation, req, remote_id):
    """A journal row as the per-request Serverless path wrote it before phase 1 (that path is
    closed now: a lone /run outside a round and a GPU session is refused unsent)."""
    payload = req.model_dump(mode="json", exclude_none=True)
    payload["model"] = p.config.route(operation, req.quality, req.model)
    row, _fresh = p.store.reserve(operation, payload, p.config, None)
    return p.store.update(row.id, remote_job_id=remote_id, status="QUEUED")


def test_serverless_official_async_transport(engine):
    from app.providers.media_http import MediaProviderError

    t = FakeTransport([{"id": "serverless-1", "status": "IN_PROGRESS", "executionTime": 1500}])
    p = provider(engine, t, mode="serverless", endpoint_id="configured-endpoint")
    video = request("video", source_image="https://assets.example/i.png")
    with pytest.raises(MediaProviderError) as refused:
        asyncio.run(p.generate_video(video))
    assert refused.value.unsent and refused.value.code == "NEEDS_GPU_ROUND" and not t.calls
    # A row an earlier version sent is still collected over the official /status route.
    job = legacy_serverless_row(p, "video", video, "serverless-1")
    running = asyncio.run(p.get_job(job.id))
    assert running.status == "RUNNING" and running.gpu_seconds == 1.5
    assert t.calls[0][0] == "api.runpod.ai"
    assert t.calls[0][2] == "/v2/configured-endpoint/status/serverless-1"


def test_ambiguous_submit_is_never_bought_again_after_restart(engine):
    from app.providers.media_http import MediaProviderError

    # The per-request contract (Pod); a Serverless round's ambiguity: test_runpod_batch.
    t = FakeTransport([MediaProviderError("unknown", unanswered=True)])
    p = provider(engine, t)
    with pytest.raises(module("errors").SubmissionUncertain):
        asyncio.run(p.generate_image(request()))
    with pytest.raises(module("errors").SubmissionUncertain):
        asyncio.run(provider(engine, t).generate_image(request()))
    assert len(t.calls) == 1


def test_network_retry_for_safe_read(engine, monkeypatch):
    from app.providers.media_http import MediaProviderError

    monkeypatch.setattr(module("client"), "backoff_seconds", lambda attempt: 0)
    t = FakeTransport(
        [MediaProviderError("503", http_status=503), {"status": "healthy", "authenticated": True}]
    )
    health = asyncio.run(provider(engine, t).health())
    assert health["cloud_backend_healthy"] and health["authenticated"]
    assert len(t.calls) == 2


def test_public_pod_health_is_not_authentication(engine):
    t = FakeTransport([{"status": "healthy"}])
    health = asyncio.run(provider(engine, t).health())
    assert health["endpoint_reachable"] and health["cloud_backend_healthy"]
    assert health["authenticated"] is False


SETTINGS = {"id": "ep", "workers": {"min": 0, "max": 0, "idleTimeout": 1}, "flashboot": "FLASHBOOT"}
HEALTH = {"jobs": {"inQueue": 0, "inProgress": 0}, "workers": {"idle": 0, "running": 0}}
BUCKET = {
    "s3_endpoint_url": "https://account.r2.example",
    "s3_bucket": "amn-films",
    "s3_access_key_id": "AKIDEXAMPLE",
    "s3_secret_access_key": "synthetic",  # pragma: allowlist secret — synthetic test value
}


def test_serverless_is_verified_scaled_to_zero_without_any_run(engine):
    # Serverless has no always-on server: the endpoint's settings and /health are read, and
    # an endpoint scaled to zero with its bucket configured is healthy. Nothing is POSTed.
    t = FakeTransport([SETTINGS, HEALTH])
    p = provider(engine, t, mode="serverless", endpoint_id="ep", generation_base_url=None, **BUCKET)
    health = asyncio.run(p.health())
    assert health["authenticated"] and health["endpoint_reachable"]
    assert health["cloud_backend_healthy"] is True
    assert health["gpu_backend_status"] == "SCALED_TO_ZERO"
    assert [c[1] for c in t.calls] == ["GET", "GET"]
    assert t.calls[0][0] == "api.runpod.io" and t.calls[0][2] == "/v2/serverless/ep"
    assert t.calls[1][0] == "api.runpod.ai" and t.calls[1][2] == "/v2/ep/health"


def test_serverless_always_on_worker_or_missing_bucket_is_not_healthy(engine):
    always_on = {**SETTINGS, "workers": {"min": 1, "max": 1, "idleTimeout": 1}}
    t = FakeTransport([always_on, HEALTH])
    p = provider(engine, t, mode="serverless", endpoint_id="ep", generation_base_url=None)
    health = asyncio.run(p.health())
    assert health["cloud_backend_healthy"] is False
    words = " ".join(health["problems_ro"])
    assert "min > 0" in words and "Bucketul" in words


def test_submit_retry_only_when_never_sent(engine, monkeypatch):
    from app.providers.media_http import MediaProviderError

    monkeypatch.setattr(module("client"), "backoff_seconds", lambda attempt: 0)
    t = FakeTransport(
        [MediaProviderError("connect", unsent=True), {"job_id": "r", "status": "QUEUED"}]
    )
    assert asyncio.run(provider(engine, t).generate_image(request())).remote_job_id == "r"
    assert len(t.calls) == 2


def test_unknown_job_state_is_error(engine):
    t = FakeTransport([{"job_id": "r", "status": "MAGIC"}])
    with pytest.raises(module("errors").RunPodProtocolError):
        asyncio.run(provider(engine, t).generate_image(request()))


def test_mock_image_qa_regeneration_and_cost(engine, tmp_path):
    p = module("provider").RunPodGenerationProvider(config(enabled=True, mock=True), engine)
    first = asyncio.run(p.generate_image(request(quality="HERO", seed=8)))
    assert first.status == "QUEUED"
    assert asyncio.run(p.get_job(first.id)).status == "RUNNING"
    done = asyncio.run(p.get_job(first.id))
    assert done.status == "COMPLETED" and done.estimated_cost_usd == Decimal("0")
    path = asyncio.run(p.persist_result(done.id, tmp_path))
    assert path.is_file() and path.read_bytes().startswith(b"\x89PNG")
    p.record_quality(done.id, accepted=False, reason="hand deformation")
    again = asyncio.run(p.regenerate(done.id, ["hand deformation"]))
    assert again.attempt == 2 and again.idempotency_key != first.idempotency_key
    assert again.request["previous_seed"] == 8
    assert again.request["previous_model"] == first.model
    assert again.request["qa_reason"] == "hand deformation"
    assert again.request["generation_history"][0]["job_id"] == first.id
    asyncio.run(p.get_job(again.id))
    asyncio.run(p.get_job(again.id))
    p.record_quality(again.id, accepted=True)
    report = p.metrics("film-1")
    assert report["regenerations"] == 1 and report["cost_per_accepted_scene_usd"] == "0"


def test_mock_failure_and_cancellation(engine):
    p = module("provider").RunPodGenerationProvider(config(enabled=True, mock=True), engine)
    job = asyncio.run(p.generate_image(request(mock_failure=True)))
    asyncio.run(p.get_job(job.id))
    assert asyncio.run(p.get_job(job.id)).status == "FAILED"
    other = asyncio.run(p.generate_image(request(attempt_number=2)))
    assert asyncio.run(p.cancel_job(other.id)).status == "CANCELLED"


def test_disabled_provider_health_without_network(engine):
    t = FakeTransport([])
    p = module("provider").RunPodGenerationProvider(config(), engine, transport=t)
    assert asyncio.run(p.health())["configured"] is False
    with pytest.raises(module("errors").RunPodDisabled):
        asyncio.run(p.generate_image(request()))
    assert not t.calls


def test_cost_includes_rejected_attempts(engine):
    jobs = module("jobs")
    for i, accepted in [(1, False), (2, False), (3, True)]:
        t = FakeTransport(
            [
                {"job_id": f"r{i}", "status": "QUEUED"},
                {"job_id": f"r{i}", "status": "COMPLETED", "gpu_seconds": 3600},
            ]
        )
        p = provider(engine, t)
        job = asyncio.run(p.generate_image(request(attempt_number=i)))
        asyncio.run(p.get_job(job.id))
        p.record_quality(job.id, accepted=accepted)
    report = p.metrics("film-1", finished=True)
    assert Decimal(report["cost_per_accepted_scene_usd"]) == Decimal("6.27")
    assert Decimal(report["gpu_minutes_per_short"]) == Decimal("180")
    assert report["regenerations"] == 2
    with Session(engine) as s:
        assert len(s.scalars(select(jobs.GenerationJob)).all()) == 3


def test_infra_hooks_refuse_by_default(engine):
    p = provider(engine, FakeTransport([]))
    for name in ["start_compute", "stop_compute", "ensure_compute_available"]:
        with pytest.raises(module("errors").InfrastructureDisabled):
            asyncio.run(getattr(p, name)())


def test_adapter_uses_existing_image_interface_and_submission_callback(engine, tmp_path):
    from app.providers.media_base import ImageProvider

    adapter = module("adapters").RunPodImageAdapter(
        config(enabled=True, mock=True), engine, model="Qwen-Image-2512", storage_root=tmp_path
    )
    assert isinstance(adapter, ImageProvider)
    adapter.bind_scene(project_id="film-1", scene_id="4", operation="image")
    submitted = []
    results = asyncio.run(
        adapter.generate_candidates(
            "A mountain", ratio="1080:1920", count=2, references=[], on_submitted=submitted.append
        )
    )
    assert len(results) == len(submitted) == 2
    assert len(set(submitted)) == 2
    assert all(r.raw_response["provider"] == "RUNPOD_MOCK" for r in results)
    assert all(r.raw_response["asset_path"] for r in results)
    assert all(r.image_bytes.startswith(b"\x89PNG") for r in results)


def test_adapter_refuses_missing_scene_identity(engine):
    adapter = module("adapters").RunPodImageAdapter(
        config(enabled=True, mock=True), engine, model="Qwen-Image-2512"
    )
    with pytest.raises(module("errors").RunPodProtocolError):
        asyncio.run(adapter.generate_image("A mountain"))


def test_local_timeout_remains_collectable_without_resubmit(engine):
    from app.providers.media_http import TaskStillOpen

    t = FakeTransport(
        [{"job_id": "r", "status": "QUEUED"}]
        + [{"job_id": "r", "status": "RUNNING"} for _ in range(50)]
    )
    p = provider(engine, t, job_timeout=0.025)
    job = asyncio.run(p.generate_image(request()))
    with pytest.raises(TaskStillOpen):
        asyncio.run(p.wait(job.id))
    assert p.store.read(job.id).status == "RUNNING"
    assert sum(c[1] == "POST" for c in t.calls) == 1


def test_safe_download_has_no_api_key_and_pins_public_address(engine):
    data = module("mock").png()

    def transport(host, method, path, headers, body=None, **kw):
        assert not headers and kw["public_only"] is True
        assert host == "cdn.example" and path == "/image.png?signature=temporary"
        return None, data, "image/png"

    client = module("client").RunPodClient(config(api_key="fake-key"), transport)
    assert (
        asyncio.run(client.download("https://cdn.example/image.png?signature=temporary"))[0] == data
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.example/image.png",
        "https://key:secret@cdn.example/i.png",  # pragma: allowlist secret
    ],
)
def test_download_rejects_unsafe_urls(url):
    client = module("client").RunPodClient(config(), FakeTransport([]))
    with pytest.raises(module("errors").RunPodProtocolError):
        asyncio.run(client.download(url))


def test_unknown_gpu_cost_is_reported_as_unknown(engine):
    p = provider(engine, FakeTransport([{"job_id": "r", "status": "COMPLETED"}]))
    job = asyncio.run(p.generate_image(request()))
    assert job.estimated_cost_usd is None
    p.record_quality(job.id, accepted=True)
    assert p.metrics("film-1")["cost_per_accepted_scene_usd"] is None


def test_parallel_submissions_share_one_remote_purchase(engine):
    t = FakeTransport([{"job_id": "r", "status": "QUEUED"}])
    p = provider(engine, t)

    async def run():
        return await asyncio.gather(
            p.generate_image(request()), p.generate_image(request()), return_exceptions=True
        )

    rows = asyncio.run(run())
    assert len(t.calls) == 1
    assert any(getattr(row, "remote_job_id", None) == "r" for row in rows)


def test_factory_selection_and_disabled_flag_preserve_other_providers(
    engine, monkeypatch, tmp_path
):
    from uuid import uuid4

    from app.integrations.models import MediaProductionConfig, ProviderResource
    from app.integrations.vault import CredentialVault
    from app.media.factory import image_provider
    from app.providers.openai_media import OpenAIImageAdapter
    from app.services import utc_now
    from test_media_selection import add_integration
    from test_media_selection import select as choose

    vault = CredentialVault(tmp_path / "key")
    identifier = add_integration(engine, vault, "runpod", "VERIFIED", {"mock": "true"}, {})
    with Session(engine) as s, s.begin():
        s.add(
            ProviderResource(
                id=str(uuid4()),
                integration_id=identifier,
                resource_type="MODEL",
                remote_id="Qwen-Image-2512",
                name="Qwen",
                api_available=True,
                last_seen_at=utc_now(),
                production_status="CANDIDATE",
                api_metadata={"tasks": ["text_to_image"]},
            )
        )
        s.add(
            MediaProductionConfig(
                integration_id=identifier,
                image_model_id="Qwen-Image-2512",
                version=1,
                updated_at=utc_now(),
            )
        )
    choose(engine, "image", identifier)
    monkeypatch.setenv("RUNPOD_ENABLED", "false")
    assert image_provider(engine, vault) is None
    monkeypatch.setenv("RUNPOD_ENABLED", "true")
    assert isinstance(image_provider(engine, vault), module("adapters").RunPodImageAdapter)
    other = add_integration(
        engine, vault, "openai_media", "ACCESS_VERIFIED", {"model": "image"}, {"api_key": "k"}
    )
    choose(engine, "image", other)
    assert isinstance(image_provider(engine, vault), OpenAIImageAdapter)


def test_runpod_keeps_paid_staircase_gate(engine):
    from app.media.factory import is_paid_vendor_adapter

    adapter = module("adapters").RunPodVideoAdapter(
        config(enabled=True, mock=True), engine, model="AUTO"
    )
    assert is_paid_vendor_adapter(adapter)


def test_serverless_models_come_from_the_pinned_catalogue_without_any_request(engine):
    t = FakeTransport([])
    p = module("provider").RunPodGenerationProvider(
        config(
            enabled=True,
            mode="serverless",
            api_key="fake-key",  # pragma: allowlist secret — synthetic test value
            stills_endpoint_id="stills-ep",
        ),
        engine,
        transport=t,
    )
    models = asyncio.run(p.available_models())
    assert [m["id"] for m in models] == ["Qwen-Image-2512"]  # no motion endpoint configured
    assert models[0]["gpu_seconds_per_image"] == 60 and models[0]["output"] == [1530, 2720]
    assert models[0]["licence"] == "Apache-2.0" and models[0]["quality_score"] is None
    assert not t.calls


# ------------------------------------------------------- the journal (migration 0056 rules)


def test_the_journal_keeps_picture_digests_never_base64(engine):
    import base64
    import hashlib

    picture = module("mock").png()
    inline = "data:image/png;base64," + base64.b64encode(picture).decode()
    t = FakeTransport([{"job_id": "r", "status": "QUEUED"}])
    row = asyncio.run(provider(engine, t).generate_video(request("video", source_image=inline)))
    assert t.calls[0][4]["source_image"] == inline  # the Pod still receives the picture
    assert row.request["source_image"] == {
        "sha256": hashlib.sha256(picture).hexdigest(),
        "bytes": len(picture),
        "mime": "image/png",
    }
    assert row.request_digest == row.payload_hash
    # The same request again is the same purchase, recognised by its digest.
    again = asyncio.run(provider(engine, t).generate_video(request("video", source_image=inline)))
    assert again.id == row.id and len(t.calls) == 1


def _legacy(engine, status):
    """A row from before 0056: no request_digest, its hash over the old (base64) payload."""
    jobs = module("jobs")
    t = FakeTransport([{"job_id": "legacy", "status": "QUEUED"}])
    row = asyncio.run(provider(engine, t).generate_image(request()))
    with Session(engine) as s, s.begin():
        saved = s.get(jobs.GenerationJob, row.id)
        saved.request_digest = None
        saved.payload_hash = "0" * 64
        saved.status = status
    return row


def test_a_finished_legacy_row_is_matched_by_its_key_alone(engine):
    old = _legacy(engine, "COMPLETED")
    t = FakeTransport([])
    again = asyncio.run(provider(engine, t).generate_image(request()))
    assert again.id == old.id and not t.calls


def test_an_open_legacy_row_that_differs_stays_a_conflict(engine):
    _legacy(engine, "RUNNING")
    with pytest.raises(module("errors").IdempotencyConflict):
        asyncio.run(provider(engine, FakeTransport([])).generate_image(request()))


def test_a_redo_without_a_verdict_never_reuses_a_collected_key(engine, tmp_path):
    adapter = module("adapters").RunPodImageAdapter(
        config(enabled=True, mock=True, poll_interval=0.01), engine, storage_root=tmp_path
    )
    adapter.bind_scene(project_id="film-1", scene_id="4", operation="image")
    first = asyncio.run(adapter.generate_image("A mountain", seed=5))
    assert first.raw_response["asset_path"]  # collected, no verdict yet
    second = asyncio.run(adapter.generate_image("A mountain", seed=5))
    rows = {first.raw_response["job_id"], second.raw_response["job_id"]}
    assert len(rows) == 2, "a collected job was taken for a new purchase"
    assert adapter.core.store.read(second.raw_response["job_id"]).attempt == 2
