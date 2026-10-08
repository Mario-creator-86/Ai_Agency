"""RunPod reaches the existing selection, QA, SceneTake and watchdog paths offline."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.integrations.discovery import ProductionCommand, refresh_catalog, save_production
from app.integrations.models import Integration, ProviderResource, ServiceSelection
from app.integrations.services import SaveIntegration, save, select_service
from app.integrations.vault import CredentialVault
from app.media import assembler, stills_stage
from app.media.factory import image_provider, video_provider_for
from app.media.models import SceneTake
from app.media.shooting_sheet import (
    _read_balance,
    connection_account,
    connection_capabilities,
    price_table_for,
)
from app.models import OwnerPolicy
from app.providers.media_http import MediaProviderError, TaskStillOpen
from app.providers.runpod.adapters import RunPodImageAdapter, RunPodVideoAdapter
from app.providers.runpod.errors import InfrastructureDisabled, RunPodProtocolError
from app.providers.runpod.jobs import GenerationJob
from app.workflows.watchdog import _default_collector_for
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_runpod_generation import FakeTransport, config, module, provider, request
from test_scene_takes import nepal_like


def connect(engine, tmp_path, monkeypatch):
    monkeypatch.setenv("RUNPOD_ENABLED", "true")
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    identifier = str(uuid4())
    save(
        engine,
        vault,
        identifier,
        SaveIntegration(kind="runpod", name="RunPod offline", config={"mock": "true"}),
    )
    result = refresh_catalog(
        engine, vault, identifier, interval_seconds=600, retry_seconds=60, force=True
    )
    assert result["status"] == "VERIFIED"
    save_production(
        engine,
        identifier,
        ProductionCommand(
            expected_version=0,
            model_id="LTX-2.5",
            image_model_id="Qwen-Image-2512",
            allow_production_override=False,
        ),
    )
    for purpose in ("image", "video"):
        with Session(engine) as session:
            current = session.get(ServiceSelection, purpose)
            version = current.version if current else 0
        select_service(engine, purpose, identifier, version)
    return vault, identifier


def test_discovery_factory_cost_and_capability_routing(engine, tmp_path, monkeypatch):
    vault, identity = connect(engine, tmp_path, monkeypatch)
    assert isinstance(image_provider(engine, vault), RunPodImageAdapter)
    assert isinstance(
        video_provider_for(
            engine, vault, {"valid": True, "integration_id": identity, "model_id": "LTX-2.5"}
        ),
        RunPodVideoAdapter,
    )
    table = price_table_for(engine, identity)
    assert table.stills_model == "Qwen-Image-2512"
    assert table.row("LTX-2.5", "1080x1920").credits_per_second == 0
    caps = connection_capabilities(engine, identity)
    hero = next(c for c in caps if c.model_id == "LTX-2.5")
    assert hero.owner_allowed and hero.selected_default
    assert hero.admitted and hero.quality == 0.5  # explicit Owner choice; no fabricated experience
    assert hero.seconds == {"min": 1, "max": 5}
    balance = _read_balance(connection_account(engine, vault, identity))
    assert balance["credits"] is None and not balance["applicable"]
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"
    assert image_provider(engine, vault) is None  # mock never reaches production


def test_real_prices_need_backend_estimates_and_zero_is_not_free_cloud(
    engine, tmp_path, monkeypatch
):
    _vault, identity = connect(engine, tmp_path, monkeypatch)
    with Session(engine) as session, session.begin():
        session.get(Integration, identity).config = {"mock": "false"}
        resource = session.scalar(
            select(ProviderResource).where(
                ProviderResource.integration_id == identity, ProviderResource.remote_id == "LTX-2.5"
            )
        )
        resource.pricing = {"per_second_usd": 0.12}
    table = price_table_for(engine, identity)
    assert table.row("LTX-2.5", "1080x1920").credits_per_second * table.credit_usd == pytest.approx(
        0.12
    )
    from app.media.cost_plan import UnpricedError

    with pytest.raises(UnpricedError):
        table.row("Qwen-Image-2512", "1080x1920")


def test_gpu_step_keeps_owner_approval_with_positive_cap_and_no_runway_balance(engine, tmp_path):
    from dataclasses import replace

    from app.media.cost_plan import DOCUMENTED, PriceRow, load_price_table
    from app.media.shooting_sheet import SheetStepRefused, build_sheet, run_sheet_step
    from test_shooting_sheet import SEEDANCE, film_without_stills

    board = film_without_stills(engine, tmp_path)
    adapter = RunPodImageAdapter(config(enabled=True, mock=True), engine, model="Qwen-Image-2512")
    table = load_price_table()
    table = replace(
        table,
        stills_model=adapter.model,
        rows=(
            *table.rows,
            PriceRow(
                adapter.model,
                "image",
                "*",
                "test estimate",
                "2026-10-07",
                DOCUMENTED,
                credits_per_image=9,
            ),
        ),
    )
    sheet = build_sheet(
        engine,
        board,
        capabilities=[SEEDANCE],
        table=table,
        account=adapter,
        stills_model=adapter.model,
        read_live=False,
    )
    with pytest.raises(SheetStepRefused) as asked:
        run_sheet_step(
            engine,
            board,
            "stills",
            sheet["sheet_hash"],
            correlation_id=str(uuid4()),
            capabilities=[SEEDANCE],
            table=table,
            account=adapter,
            image_adapter=adapter,
        )
    assert asked.value.status == "NEEDS_APPROVAL"
    assert asked.value.cap_credits > 0
    with Session(engine) as session:
        assert session.scalar(select(GenerationJob)) is None


def test_estimated_purchase_books_runpod_without_a_bill_or_runway_balance(engine):
    from app.economy.models import ProviderCostRecord
    from app.media.shooting_sheet import book_purchase

    result = book_purchase(
        engine,
        storyboard_id="p",
        step="stills",
        reference="runpod-test",
        credits=20,
        measured=False,
        credit_usd=0.01,
        correlation_id=str(uuid4()),
        billing_provider="runpod",
    )
    assert result["usd"] == 0.2
    with Session(engine) as session:
        row = session.scalar(
            select(ProviderCostRecord).where(ProviderCostRecord.external_reference == "runpod-test")
        )
        assert row.provider == "runpod" and row.status == "ESTIMATED"
        assert row.transaction_id is None


def test_existing_stills_verdict_preserves_feedback_on_new_attempt(engine, tmp_path):
    board = nepal_like(engine, tmp_path)
    adapter = RunPodImageAdapter(
        config(enabled=True, mock=True, poll_interval=0.01),
        engine,
        model="Qwen-Image-2512",
        storage_root=tmp_path,
    )
    adapter.bind_scene(project_id=board, scene_id="1", operation="image")
    results, _quote = stills_stage._buy(adapter, "Original scene prompt", [], 2)
    takes = []
    for index, result in enumerate(results):
        takes.append(
            assembler.record_take(
                engine,
                storyboard_id=board,
                scene_number=1,
                kind="still",
                prompt_hash="original",
                model_id=adapter.model,
                resolution="9:16",
                status="PAID",
                correlation_id=str(uuid4()),
                path=Path(result.raw_response["asset_path"]),
                remote_task_id=result.raw_response["task_id"],
                sha256=str(index),
            )
        )
    report = SimpleNamespace(decision="BLOCKED", reasons_ro=("hand deformation",))
    stills_stage._set_verdicts(engine, [(take, report) for take in takes], None)
    new = asyncio.run(adapter.generate_image("Corrected hands", seed=9))
    row = adapter.core.store.read(new.raw_response["job_id"])
    assert row.attempt == 2 and row.request["qa_feedback"] == ["hand deformation"]
    assert row.request["original_prompt"] == "Original scene prompt"
    assert row.request["previous_model"] == "Qwen-Image-2512"
    assert row.request["generation_history"][0]["accepted"] is False


def test_owner_rejection_and_watchdog_use_original_connection(engine, tmp_path, monkeypatch):
    vault, identity = connect(engine, tmp_path, monkeypatch)
    board = nepal_like(engine, tmp_path)
    adapter = image_provider(engine, vault)
    adapter.storage_root = tmp_path
    adapter.bind_scene(project_id=board, scene_id="1", operation="image")
    remote = asyncio.run(adapter.core.generate_image(request(project_id=board, scene_id="1")))
    take_id = assembler.record_take(
        engine,
        storyboard_id=board,
        scene_number=1,
        kind="still",
        prompt_hash="p",
        model_id=adapter.model,
        resolution="9:16",
        status="SUBMITTED",
        correlation_id=str(uuid4()),
        remote_task_id=remote.remote_job_id,
    )
    # Change selection while the job is pending. Recovery must keep the originating account.
    with Session(engine) as session:
        version = session.get(ServiceSelection, "image").version
    select_service(engine, "image", None, version)
    with Session(engine) as session:
        take = session.get(SceneTake, take_id)
        session.expunge(take)
    recovered = _default_collector_for(engine)(take)
    recovered.storage_root = tmp_path
    assert recovered.integration_id == identity

    def collector(unused):
        return recovered

    assembler.collect_submitted_takes(
        engine, collector_for=collector, correlation_id=str(uuid4()), storage_root=tmp_path
    )
    assembler.collect_submitted_takes(
        engine, collector_for=collector, correlation_id=str(uuid4()), storage_root=tmp_path
    )
    with Session(engine) as session:
        assert session.get(SceneTake, take_id).status == "PAID"
    assembler.decide_take(
        engine, take_id, "REJECTED", decided_by=assembler.TAKE_DECIDER, note="identity drift"
    )
    row = adapter.core.store.read(remote.id)
    assert row.accepted is False and row.quality_result == "identity drift"
    with Session(engine) as session:
        assert (
            len(
                session.scalars(
                    select(GenerationJob).where(GenerationJob.project_id == board)
                ).all()
            )
            == 1
        )


def test_image_poll_failure_remains_submitted_and_does_not_buy_again(engine, tmp_path):
    transport = FakeTransport(
        [{"id": "remote", "status": "QUEUED"}, MediaProviderError("unanswered", unanswered=True)]
    )
    adapter = RunPodImageAdapter(
        config(
            enabled=True,
            mode="pod",
            api_key="fake-key",  # pragma: allowlist secret — synthetic test value
            max_retries=0,
            generation_base_url="https://cloud.example",
        ),
        engine,
        storage_root=tmp_path,
    )
    adapter.core.client.transport = transport
    adapter.bind_scene(project_id="p", scene_id="1", operation="image")
    submitted = []
    with pytest.raises(TaskStillOpen):
        asyncio.run(
            adapter.generate_candidates(
                "p", ratio="1080:1920", count=1, on_submitted=submitted.append
            )
        )
    assert submitted == ["remote"]
    assert adapter.core.store.read("remote").status == "QUEUED"
    assert sum(call[1] == "POST" for call in transport.calls) == 1


def test_changed_endpoint_cannot_poll_or_download_old_job(engine):
    p = provider(engine, mock=True)
    job = asyncio.run(p.generate_image(request()))
    other = module("provider").RunPodGenerationProvider(
        config(enabled=True, mock=True, mode="pod", generation_base_url="https://other.example"),
        engine,
    )
    with pytest.raises(RunPodProtocolError):
        asyncio.run(other.get_job(job.id))
    with pytest.raises(RunPodProtocolError):
        asyncio.run(other.result_bytes(job.id))


def test_partial_http_post_write_never_retries_a_paid_submit(engine, monkeypatch):
    from app.providers import media_http

    sent = []

    class PartialSend:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self):
            pass

        def request(self, method, path, body, headers):
            sent.append(method)
            raise OSError("Connection lost after part of the body")

        def close(self):
            pass

    monkeypatch.setattr(media_http.http.client, "HTTPSConnection", PartialSend)
    p = provider(engine)
    with pytest.raises(module("errors").SubmissionUncertain):
        asyncio.run(p.generate_image(request()))
    with pytest.raises(module("errors").SubmissionUncertain):
        asyncio.run(p.generate_image(request()))
    assert sent == ["POST"]


def test_proven_authentication_refusal_can_retry_same_creative_attempt(engine):
    t = FakeTransport(
        [
            MediaProviderError("bad credentials", http_status=401),
            {"id": "remote", "status": "QUEUED"},
        ]
    )
    p = provider(engine, t)
    with pytest.raises(MediaProviderError):
        asyncio.run(p.generate_image(request()))
    with Session(engine) as session:
        first = session.scalar(select(GenerationJob))
        key, identity = first.idempotency_key, first.id
        assert first.status == "FAILED" and first.cost_value == "0"
    recovered = asyncio.run(p.generate_image(request()))
    assert recovered.id == identity and recovered.idempotency_key == key and recovered.attempt == 1


def test_serverless_invalid_execution_duration_is_a_protocol_error(engine):
    from test_runpod_generation import legacy_serverless_row

    t = FakeTransport([{"id": "r", "status": "COMPLETED", "executionTime": "bad"}])
    p = provider(engine, t, mode="serverless", endpoint_id="ep")
    row = legacy_serverless_row(p, "video", request("video"), "r")
    with pytest.raises(RunPodProtocolError):
        asyncio.run(p.get_job(row.id))


def test_oversized_source_payload_creates_no_intent_and_sends_nothing(engine):
    t = FakeTransport([])
    p = provider(engine, t)
    with pytest.raises(RunPodProtocolError):
        asyncio.run(p.generate_video(request("video", source_image="x" * (11 * 1024 * 1024))))
    with Session(engine) as session:
        assert session.scalar(select(GenerationJob)) is None
    assert not t.calls


def test_lost_submission_reconciliation_requires_backend_key_proof(engine):
    t = FakeTransport([MediaProviderError("lost", unanswered=True)])
    p = provider(engine, t)
    with pytest.raises(module("errors").SubmissionUncertain):
        asyncio.run(p.generate_image(request()))
    with Session(engine) as session:
        row = session.scalar(select(GenerationJob))
        identifier, key = row.id, row.idempotency_key
    t.responses += [{"id": "remote", "status": "RUNNING", "idempotency_key": "wrong"}]
    with pytest.raises(RunPodProtocolError):
        asyncio.run(p.recover_submission(identifier, "remote"))
    t.responses += [{"id": "remote", "status": "RUNNING", "idempotency_key": key}]
    recovered = asyncio.run(p.recover_submission(identifier, "remote"))
    assert recovered.remote_job_id == "remote"
    assert sum(call[1] == "POST" for call in t.calls) == 1


def test_finalize_contract_and_qa_regeneration(engine):
    p = provider(engine, mock=True)
    r = module("models").FinalizeRequest(
        project_id="p", scene_id="1", prompt="finalize", source_video="https://cdn.example/clip.mp4"
    )
    job = asyncio.run(p.finalize_video(r))
    asyncio.run(p.wait(job.id))
    p.record_quality(job.id, accepted=False, reason="bad finish")
    second = asyncio.run(p.regenerate(job.id, ["remove artifacts"]))
    assert second.operation == "finalize" and second.attempt == 2
    assert second.request["source_video"] == r.source_video


def test_optional_official_rest_v2_actions_are_gated_and_sanitized(engine):
    t = FakeTransport(
        [
            {
                "id": "pod",
                "status": "EXITED",
                "actions": ["start"],
                "env": {
                    "password": "never-expose"  # pragma: allowlist secret — synthetic test value
                },
            },
            {
                "id": "pod",
                "status": "STARTING",
                "env": {"secret": "never-expose"},  # pragma: allowlist secret
            },
        ]
    )
    p = provider(engine, t, pod_id="pod", allow_infra_actions=True)
    result = asyncio.run(p.start_compute())
    assert result["status"] == "STARTING" and "env" not in result
    assert t.calls[0][0] == "api.runpod.io"
    assert t.calls[1][2] == "/v2/pods/pod/action" and t.calls[1][4] == {"action": "start"}
    assert not config().auto_start and not config().auto_stop


def test_stop_is_refused_while_remote_work_is_pending(engine):
    t = FakeTransport([{"id": "job", "status": "QUEUED"}])
    p = provider(engine, t, pod_id="pod", allow_infra_actions=True)
    asyncio.run(p.generate_image(request()))
    with pytest.raises(InfrastructureDisabled):
        asyncio.run(p.stop_compute())
    assert len(t.calls) == 1


def test_mock_video_is_decodable_five_seconds_and_survives_restart(engine, tmp_path):
    import json
    import subprocess

    from app.media.toolchain import find_ffmpeg

    ffmpeg = find_ffmpeg()
    assert ffmpeg is not None
    adapter = RunPodVideoAdapter(
        config(enabled=True, mock=True, poll_interval=0.01),
        engine,
        model="AUTO",
        storage_root=tmp_path,
    )
    adapter.bind_scene(project_id="p", scene_id="1", operation="video")
    identifier = asyncio.run(adapter.create_generation("synthetic motion", duration_seconds=5))
    assert adapter.core.store.read(identifier).model == "AUTO"
    restarted = RunPodVideoAdapter(adapter.config, engine, model="AUTO", storage_root=tmp_path)
    asyncio.run(restarted.core.wait(identifier))
    result = asyncio.run(restarted.get_generation_status(identifier))
    probe = subprocess.run(
        [
            str(Path(ffmpeg).with_name("ffprobe.exe")),
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(result.video_path),
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    parsed = json.loads(probe.stdout)
    assert float(parsed["format"]["duration"]) == pytest.approx(5, abs=0.1)
    assert parsed["streams"][0]["width"] * 16 == parsed["streams"][0]["height"] * 9


# ------------------------------------------- serverless: verified without a /run, bucket on


def serverless_connection(engine, monkeypatch, *, workers_min=0):
    """A real-looking serverless RunPod integration whose management API is faked."""
    from app.integrations.discovery import refresh_catalog
    from app.providers.runpod import endpoint as endpoint_module

    monkeypatch.setenv("RUNPOD_ENABLED", "true")
    calls = []

    def transport(host, method, path, headers, body=None, **kwargs):
        calls.append((host, method, path))
        assert method == "GET", "verification never sends anything that could start a worker"
        if path.startswith("/v2/serverless/"):
            endpoint = path.rsplit("/", 1)[1]
            return (
                {"id": endpoint, "workers": {"min": workers_min, "max": 0, "idleTimeout": 1}},
                b"",
                "application/json",
            )
        return (
            {"jobs": {"inQueue": 0, "inProgress": 0}, "workers": {"idle": 0, "running": 0}},
            b"",
            "application/json",
        )

    monkeypatch.setattr(endpoint_module, "request", transport)
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    identifier = str(uuid4())
    save(
        engine,
        vault,
        identifier,
        SaveIntegration(
            kind="runpod",
            name="RunPod Serverless",
            config={
                "mode": "serverless",
                "stills_endpoint_id": "stills-ep",
                "motion_endpoint_id": "motion-ep",
                "s3_endpoint_url": "https://account.r2.example",
                "s3_bucket": "amn-films",
            },
            secrets={
                "api_key": "fake-key",  # pragma: allowlist secret — synthetic test value
                "s3_access_key_id": "AKIDEXAMPLE",  # pragma: allowlist secret
                "s3_secret_access_key": "synthetic",  # pragma: allowlist secret
            },
        ),
    )
    result = refresh_catalog(
        engine, vault, identifier, interval_seconds=600, retry_seconds=60, force=True
    )
    return vault, identifier, result, calls


def test_serverless_is_verified_from_its_endpoints_and_the_pinned_catalogue(engine, monkeypatch):
    vault, identifier, result, calls = serverless_connection(engine, monkeypatch)
    assert result["status"] == "VERIFIED"
    assert {c[2] for c in calls} == {
        "/v2/serverless/stills-ep",
        "/v2/stills-ep/health",
        "/v2/serverless/motion-ep",
        "/v2/motion-ep/health",
    }
    with Session(engine) as session:
        models = {
            r.remote_id: r
            for r in session.scalars(
                select(ProviderResource).where(ProviderResource.integration_id == identifier)
            )
        }
    assert set(models) == {"Qwen-Image-2512", "LTX-2.5", "Wan-2.2-LightX2V"}
    assert models["LTX-2.5"].api_metadata["output"] == [1080, 1920]
    assert models["LTX-2.5"].api_metadata["licence_url"].startswith("https://huggingface.co/")
    # The adapter built from the vault has its bucket: the stills step may switch the GPU on.
    from app.providers.runpod.wiring import connection

    with Session(engine) as session:
        row = session.get(Integration, identifier)
    built = connection(engine, vault, row, "Qwen-Image-2512", "image")
    assert built.config.bucket() is not None and built.supports_batch()


def test_an_always_on_worker_fails_verification_in_the_owners_words(engine, monkeypatch):
    from app.integrations.models import ProviderDiscovery

    _vault, identifier, result, _calls = serverless_connection(engine, monkeypatch, workers_min=1)
    assert result["status"] == "FAILED"
    with Session(engine) as session:
        assert "min > 0" in session.get(ProviderDiscovery, identifier).last_error


def test_serverless_prices_at_the_budget_rate_with_a_gpu_start_per_round(engine, monkeypatch):
    _vault, identifier, _result, _calls = serverless_connection(engine, monkeypatch)
    table = price_table_for(engine, identifier)
    still = table.row("Qwen-Image-2512", "2K")
    # 60 GPU-s a still x 4.00 USD/h.
    assert still.credits_per_image * table.credit_usd == pytest.approx(60 * 4.00 / 3600)
    clip = table.row("LTX-2.5", "1080p")
    assert clip.credits_per_second * table.credit_usd == pytest.approx(24 * 4.00 / 3600)
    assert table.overhead_credits_per_round["image"] * table.credit_usd == pytest.approx(
        121 * 4.00 / 3600
    )
    assert table.round_overhead("video", "LTX-2.5") > 0
    assert table.round_overhead("video", "seedance2_5") == 0


def test_media_readiness_needs_the_selected_model_and_the_bucket(engine, monkeypatch):
    from app.media.factory import media_readiness

    vault, identifier, _result, _calls = serverless_connection(engine, monkeypatch)
    save_production(
        engine,
        identifier,
        ProductionCommand(
            expected_version=0,
            model_id="LTX-2.5",
            image_model_id="Qwen-Image-2512",
            allow_production_override=False,
        ),
    )
    with Session(engine) as session:
        current = session.get(ServiceSelection, "image")
        version = current.version if current else 0
    select_service(engine, "image", identifier, version)
    assert media_readiness(engine, vault)["image"]["status"] == "READY"
    with Session(engine) as session, session.begin():
        row = session.get(Integration, identifier)
        row.config = {k: v for k, v in row.config.items() if k != "s3_bucket"}
    readiness = media_readiness(engine, vault)["image"]
    assert readiness["status"] == "NO_DEFAULT" and "bucketul" in readiness["message"]
