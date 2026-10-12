"""RunPod GPU control (phase 1, 2026-10-08): configuration, the endpoint's management calls,
the GPU session around a paid step, the guard that switches a forgotten GPU off, the Owner's
«Oprește GPU acum» and the launcher's off. Every RunPod call goes to a fake transport; no test
reaches RunPod, a bucket or Hugging Face."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.integrations.models import Integration
from app.integrations.services import SaveIntegration, save
from app.integrations.vault import CredentialVault
from app.media.mode_guard import PurchaseGuard
from app.models import DomainEvent
from app.providers.media_http import MediaProviderError
from app.providers.runpod import endpoint as endpoint_module
from app.providers.runpod import gpu_guard, gpu_session
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.endpoint import (
    EndpointAccessDenied,
    EndpointControl,
    EndpointHealth,
    EndpointSettings,
    SettingsNotApplied,
    is_off,
)
from app.providers.runpod.errors import RunPodProtocolError
from app.providers.runpod.gpu_session import (
    GpuForcedOff,
    GpuSessionRefused,
    GpuSessionRow,
    StepPermit,
    close_session,
    force_off,
    gpu_status,
    open_session,
)
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

KEY = "fake-runpod-key"  # pragma: allowlist secret - synthetic test value
S3_ID = "fake-access-id"  # pragma: allowlist secret - synthetic test value
S3_SECRET = "fake-s3-secret"  # pragma: allowlist secret - synthetic test value


def config(**values: Any) -> RunPodConfig:
    base: dict[str, Any] = {
        "enabled": True,
        "mode": "serverless",
        "api_key": KEY,
        "stills_endpoint_id": "ep-stills",
        "motion_endpoint_id": "ep-motion",
        "s3_endpoint_url": "https://bucket.example",
        "s3_bucket": "amn-out",
        "s3_access_key_id": S3_ID,
        "s3_secret_access_key": S3_SECRET,
        "off_poll_seconds": 0.01,
        "off_grace_seconds": 0,
        "max_retries": 1,
    }
    return RunPodConfig(_env_file=None, **(base | values))


# ------------------------------------------------------------------------------- configuration


def test_serverless_defaults_follow_the_owner_rules():
    c = RunPodConfig(_env_file=None)
    assert c.mode == "serverless"
    assert c.serverless_cost_per_hour == Decimal("4.00")
    assert c.gpu_cost_per_hour == Decimal("2.09")
    assert c.idle_timeout_seconds == 1 and c.max_workers == 1
    assert c.flashboot == "FLASHBOOT" and c.endpoint_timeout_ms == 2_400_000
    assert c.url_ttl_seconds == 604800 and c.s3_prefix == "amn/" and c.s3_region == "auto"
    assert c.model_routes["VIDEO_QUALITY"] == "LTX-2.5"
    assert c.model_routes["VIDEO_HERO"] == "LTX-2.5"
    assert c.model_routes["IMAGE_QUALITY"] == "Qwen-Image-2512"


def test_hourly_rate_is_the_serverless_rate_in_serverless_and_the_pod_rate_on_a_pod():
    assert config().hourly_rate == Decimal("4.00")
    assert config(mode="pod", generation_base_url="https://x.example").hourly_rate == Decimal(
        "2.09"
    )


def test_endpoint_for_purpose_falls_back_to_the_legacy_endpoint():
    c = config()
    assert c.endpoint_for("image") == "ep-stills" and c.endpoint_for("video") == "ep-motion"
    legacy = config(stills_endpoint_id=None, motion_endpoint_id=None, endpoint_id="ep-one")
    assert legacy.endpoint_for("image") == legacy.endpoint_for("video") == "ep-one"
    assert legacy.configured


def test_bucket_needs_every_part_and_keeps_the_secret_hidden():
    bucket = config().bucket()
    assert bucket is not None
    assert bucket.endpoint_url == "https://bucket.example" and bucket.bucket == "amn-out"
    assert bucket.secret_access_key.get_secret_value() == S3_SECRET
    assert S3_SECRET not in repr(bucket)
    assert config(s3_bucket=None).bucket() is None
    assert config().ready_for_generation
    assert not config(s3_secret_access_key="").ready_for_generation
    assert config(mock=True, s3_bucket=None).ready_for_generation


@pytest.mark.parametrize(
    "values",
    [
        {"max_workers": 2},
        {"max_workers": 0},
        {"idle_timeout_seconds": 0},
        {"idle_timeout_seconds": 3601},
        {"cold_start_seconds": 901},
        {"flashboot": "ALWAYS"},
        {"url_ttl_seconds": 604801},
        {"s3_endpoint_url": "http://bucket.example"},
        {"s3_endpoint_url": "https://key:secret@bucket.example"},  # pragma: allowlist secret
        {"s3_endpoint_url": "https://bucket.example/?x=1"},
        {"s3_bucket": "Up"},
        {"s3_bucket": "a" * 64},
        {"s3_prefix": "amn"},
        {"s3_prefix": "/amn/"},
        {"stills_endpoint_id": "bad id"},
        {"motion_endpoint_id": "x" * 101},
    ],
)
def test_invalid_new_fields_are_refused(values):
    with pytest.raises(ValidationError):
        config(**values)


def test_auto_start_without_permission_is_a_pod_only_rule():
    config(auto_start=True)  # serverless: no Pod to start, never raises
    with pytest.raises(ValidationError):
        config(mode="pod", auto_start=True, generation_base_url="https://x.example")


def test_from_integration_reads_the_vault_secrets_and_never_raises_on_env_junk(monkeypatch):
    monkeypatch.setenv("RUNPOD_AUTO_START", "true")
    monkeypatch.setenv("RUNPOD_MODE", "pod")
    monkeypatch.setenv("RUNPOD_REQUEST_TIMEOUT", "not-a-number")
    c = RunPodConfig.from_integration(
        {"enabled": "true", "stills_endpoint_id": "ep-s", "s3_bucket": "amn-out"},
        {"api_key": KEY, "s3_access_key_id": S3_ID, "s3_secret_access_key": S3_SECRET},
    )
    assert c.api_key.get_secret_value() == KEY
    assert c.s3_access_key_id.get_secret_value() == S3_ID
    assert c.stills_endpoint_id == "ep-s"
    # The integration's own junk is still refused: that is what its form typed.
    with pytest.raises(ValidationError):
        RunPodConfig.from_integration({"max_workers": "3"}, {})
    # The legacy wrapper keeps working.
    assert RunPodConfig.connection({"endpoint_id": "ep"}, KEY).api_key.get_secret_value() == KEY


def test_runpod_auto_start_alone_does_not_break_pricing(monkeypatch, engine, tmp_path):
    from app.media.shooting_sheet import price_table_for

    monkeypatch.setenv("RUNPOD_AUTO_START", "true")
    vault = CredentialVault(tmp_path / "v.key")
    identifier = str(uuid4())
    save(
        engine,
        vault,
        identifier,
        SaveIntegration(kind="runpod", name="RunPod", config={"mock": "true"}),
    )
    price_table_for(engine, identifier)


# --------------------------------------------------------------------------- endpoint control


class Fake:
    """RunPod's two hosts: the management API and the queue. Answers by (method, path)."""

    def __init__(self, *, workers_max: int = 0, running: int = 0, in_queue: int = 0) -> None:
        self.calls: list[tuple[str, str, str, dict[str, str], Any, dict[str, Any]]] = []
        self.settings: dict[str, dict[str, Any]] = {}
        self.health_answers: dict[str, list[dict[str, Any]]] = {}
        self.default_health = {
            "jobs": {
                "completed": 1,
                "failed": 0,
                "inProgress": 0,
                "inQueue": in_queue,
                "retried": 0,
            },
            "workers": {"idle": 1, "running": running},
        }
        self.workers_max = workers_max
        self.fail: dict[tuple[str, str], list[Exception]] = {}
        self.patch_answer: dict[str, Any] | None = None

    def endpoint(self, identifier: str) -> dict[str, Any]:
        return self.settings.setdefault(
            identifier,
            {
                "id": identifier,
                "name": "amn",
                "workers": {"min": 0, "max": self.workers_max, "idleTimeout": 1},
                "timeout": 2_400_000,
                "flashboot": "FLASHBOOT",
                "image": "registry/amn:1",
                "gpu": {"pools": ["RTX_PRO_6000"], "count": 1},
            },
        )

    def __call__(self, host, method, path, headers, body=None, **kwargs):
        data = json.loads(body) if body else None
        self.calls.append((host, method, path, dict(headers), data, kwargs))
        queued = self.fail.get((method, path))
        if queued:
            raise queued.pop(0)
        if host == "api.runpod.io":
            identifier = path.rsplit("/", 1)[-1]
            row = self.endpoint(identifier)
            if method == "PATCH":
                for key, value in data.items():
                    row[key] = {**row.get(key, {}), **value} if isinstance(value, dict) else value
                if self.patch_answer is not None:
                    return self.patch_answer, b"", "application/json"
            return json.loads(json.dumps(row)), b"", "application/json"
        assert host == "api.runpod.ai", host
        parts = path.split("/")
        identifier, verb = parts[2], parts[3]
        if verb == "health":
            answers = self.health_answers.get(identifier)
            if answers:
                return answers.pop(0), b"", "application/json"
            health = json.loads(json.dumps(self.default_health))
            if self.endpoint(identifier)["workers"]["max"] == 0:
                health["workers"]["running"] = 0
                health["jobs"]["inProgress"] = 0
            return health, b"", "application/json"
        if verb == "purge-queue":
            return {"removed": 2, "status": "completed"}, b"", "application/json"
        if verb == "cancel":
            return {"id": parts[4], "status": "CANCELLED"}, b"", "application/json"
        raise AssertionError(path)

    def patched(self) -> list[dict[str, Any]]:
        return [c[4] for c in self.calls if c[1] == "PATCH"]

    def verbs(self) -> list[str]:
        out = []
        for host, method, path, *_ in self.calls:
            if host == "api.runpod.io":
                out.append(method)
            else:
                out.append(path.split("/")[3])
        return out


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(endpoint_module, "backoff_seconds", lambda attempt: 0)
    monkeypatch.setattr(gpu_session, "BUSY_POLL_SECONDS", 0.01)
    gpu_session.forget_readings()


@pytest.fixture(autouse=True)
def running_studio(request):
    """The suite's studio is born with the autonomy stop set; these tests run his studio as it
    runs (no stop). A test that needs the stop sets it itself."""
    if "engine" not in request.fixturenames:
        return
    from app.models import OwnerPolicy

    engine = request.getfixturevalue("engine")
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False


def control(fake: Fake, identifier: str = "ep-stills", **values: Any) -> EndpointControl:
    return EndpointControl(config(**values), identifier, transport=fake)


def test_get_reads_the_settings_with_bearer_auth_and_no_key_in_logs(caplog):
    fake = Fake(workers_max=1)
    settings = asyncio.run(control(fake).get())
    assert settings == EndpointSettings(
        endpoint_id="ep-stills",
        workers_min=0,
        workers_max=1,
        idle_timeout=1,
        timeout_ms=2_400_000,
        flashboot="FLASHBOOT",
        image="registry/amn:1",
        gpu_pools=("RTX_PRO_6000",),
    )
    host, method, path, headers, *_ = fake.calls[0]
    assert (host, method, path) == ("api.runpod.io", "GET", "/v2/serverless/ep-stills")
    assert headers["Authorization"] == "Bearer " + KEY
    assert KEY not in caplog.text


def test_set_workers_sends_exactly_the_workers_block_and_checks_the_answer():
    fake = Fake()
    answer = asyncio.run(control(fake).set_workers(1))
    assert fake.patched() == [{"workers": {"min": 0, "max": 1, "idleTimeout": 1}}]
    assert answer.workers_max == 1
    with pytest.raises(ValueError):
        asyncio.run(control(fake).set_workers(2))
    fake.patch_answer = {"id": "ep-stills", "workers": {"min": 0, "max": 3, "idleTimeout": 1}}
    with pytest.raises(SettingsNotApplied):
        asyncio.run(control(fake).set_workers(0))


def test_apply_baseline_is_explicit_and_leaves_the_gpu_pool_alone():
    fake = Fake(workers_max=1)
    fake.endpoint("ep-stills")["flashboot"] = "OFF"
    asyncio.run(control(fake).apply_baseline())
    assert fake.patched() == [
        {
            "workers": {"min": 0, "max": 0, "idleTimeout": 1},
            "timeout": 2_400_000,
            "flashboot": "FLASHBOOT",
        }
    ]


def test_health_purge_and_cancel_use_the_queue_host():
    fake = Fake(running=1, in_queue=2, workers_max=1)
    c = control(fake)
    health = asyncio.run(c.health())
    assert health == EndpointHealth(
        in_queue=2, in_progress=0, running=1, idle=1, completed=1, failed=0
    )
    assert asyncio.run(c.purge_queue()) == 2
    assert asyncio.run(c.cancel("job-9:3")) == "CANCELLED"
    paths = [(c[0], c[1], c[2]) for c in fake.calls]
    assert paths == [
        ("api.runpod.ai", "GET", "/v2/ep-stills/health"),
        ("api.runpod.ai", "POST", "/v2/ep-stills/purge-queue"),
        ("api.runpod.ai", "POST", "/v2/ep-stills/cancel/job-9"),
    ]


def test_missing_workers_block_is_a_protocol_error():
    fake = Fake()
    fake.settings["ep-stills"] = {"id": "ep-stills", "name": "x"}
    with pytest.raises(RunPodProtocolError):
        asyncio.run(control(fake).get())


def test_access_denied_keeps_the_status_and_transient_errors_are_retried():
    fake = Fake()
    fake.fail[("GET", "/v2/serverless/ep-stills")] = [
        MediaProviderError("busy", http_status=503),
    ]
    asyncio.run(control(fake).get())
    assert len(fake.calls) == 2
    fake.fail[("PATCH", "/v2/serverless/ep-stills")] = [MediaProviderError("x", unanswered=True)]
    asyncio.run(control(fake).set_workers(0))
    fake.fail[("GET", "/v2/serverless/ep-stills")] = [MediaProviderError("no", http_status=403)]
    with pytest.raises(EndpointAccessDenied) as caught:
        asyncio.run(control(fake).get())
    assert caught.value.http_status == 403


def test_is_off_ignores_idle_workers():
    settings = EndpointSettings("e", 0, 0, 1, None, None, None, ())
    assert is_off(settings, EndpointHealth(0, 0, 0, 3, 0, 0))
    assert not is_off(settings, EndpointHealth(0, 0, 1, 0, 0, 0))
    assert not is_off(settings, EndpointHealth(1, 0, 0, 0, 0, 0))
    assert not is_off(settings, EndpointHealth(0, 1, 0, 0, 0, 0))
    assert not is_off(
        EndpointSettings("e", 0, 1, 1, None, None, None, ()), EndpointHealth(0, 0, 0, 0, 0, 0)
    )


def test_verify_off_polls_until_off_or_the_deadline():
    fake = Fake()
    busy = {
        "jobs": {"inProgress": 1, "inQueue": 0, "completed": 0, "failed": 0},
        "workers": {"idle": 0, "running": 1},
    }
    fake.health_answers["ep-stills"] = [busy, busy]
    reading = asyncio.run(control(fake).verify_off(deadline_seconds=5))
    assert reading.off and reading.running == 0 and reading.idle == 1
    fake.health_answers["ep-stills"] = [busy] * 1000
    late = asyncio.run(control(fake).verify_off(deadline_seconds=0.05))
    assert not late.off and late.running == 1 and late.reason_ro
    assert late.as_dict()["endpoint_id"] == "ep-stills"


# ------------------------------------------------------------------------------- GPU session


def studio_integration(
    engine,
    tmp_path,
    monkeypatch,
    *,
    allow: bool = True,
    secrets: dict[str, str] | None = None,
    **values: str,
) -> tuple[CredentialVault, str]:
    """A saved RunPod integration (its keys in the vault), as the Owner's form makes it."""
    monkeypatch.setenv("RUNPOD_ENABLED", "true")
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    identifier = str(uuid4())
    form = {
        "stills_endpoint_id": "ep-stills",
        "motion_endpoint_id": "ep-motion",
        "s3_endpoint_url": "https://bucket.example",
        "s3_bucket": "amn-out",
    } | values
    keys = (
        {"api_key": KEY, "s3_access_key_id": S3_ID, "s3_secret_access_key": S3_SECRET}
        if secrets is None
        else secrets
    )
    save(
        engine,
        vault,
        identifier,
        SaveIntegration(
            kind="runpod",
            name="RunPod",
            config=form,
            secrets=keys,  # type: ignore[arg-type]
        ),
    )
    if allow:
        with Session(engine) as session, session.begin():
            row = session.get(Integration, identifier)
            row.config = {**row.config, "allow_infra_actions": "true"}
    return vault, identifier


def adapter(identifier: str | None, **values: Any) -> SimpleNamespace:
    return SimpleNamespace(config=config(**values), integration_id=identifier)


def permit(identifier: str | None, **values: Any) -> StepPermit:
    base: dict[str, Any] = {
        "action": "media.stills_purchase",
        "step": "stills",
        "storyboard_id": "film-1",
        "plan_hash": "plan-1",
        "requester": "director",
        "approval_id": None,
        "owner_press": True,
        "correlation_id": str(uuid4()),
        "integration_id": identifier,
    }
    return StepPermit(**(base | values))


def rows(engine) -> list[GpuSessionRow]:
    with Session(engine) as session:
        found = list(session.scalars(select(GpuSessionRow).order_by(GpuSessionRow.opened_at)))
        for row in found:
            session.expunge(row)
        return found


def events(engine, kind: str) -> list[DomainEvent]:
    with Session(engine) as session:
        return list(session.scalars(select(DomainEvent).where(DomainEvent.event_type == kind)))


def owner_letters(engine) -> list[str]:
    from app.agents.models import AgentMessage

    with Session(engine) as session:
        return [m.subject for m in session.scalars(select(AgentMessage))]


def stop_autonomy(engine) -> None:
    from app.models import OwnerPolicy

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True


def test_a_paid_step_switches_one_gpu_on_and_off_and_verifies_it(engine, tmp_path, monkeypatch):
    vault, identifier = studio_integration(engine, tmp_path, monkeypatch)
    fake = Fake()
    session = open_session(
        engine, adapter(identifier), purpose="image", permit=permit(identifier), transport=fake
    )
    assert fake.patched() == [{"workers": {"min": 0, "max": 1, "idleTimeout": 1}}]
    assert session.endpoint_id == "ep-stills" and session.workers_max == 1 and not session.mock
    (row,) = rows(engine)
    assert row.status == "OPEN" and row.step == "stills" and row.storyboard_id == "film-1"
    assert row.process_token == gpu_session.PROCESS_TOKEN
    session.renew()
    session.note_job("job-1")
    fake.calls.clear()
    reading = close_session(engine, session, reason="STEP_DONE", transport=fake)
    assert reading is not None and reading.off
    verbs = fake.verbs()
    assert verbs[:3] == ["purge-queue", "cancel", "PATCH"]
    assert fake.patched() == [{"workers": {"min": 0, "max": 0, "idleTimeout": 1}}]
    (row,) = rows(engine)
    assert row.status == "CLOSED" and row.close_reason == "STEP_DONE" and row.verified_off
    assert row.remote_job_ids == ["job-1"] and row.off_reading["off"] is True
    assert len(events(engine, "runpod.gpu_session_opened")) == 1
    assert len(events(engine, "runpod.gpu_off_verified")) == 1


def test_a_simulated_session_makes_no_call_and_reads_no_policy(engine):
    def refuse(*args, **kwargs):
        raise AssertionError("a simulation must not reach the network")

    stop_autonomy(engine)  # the kernel would refuse; a simulation never asks it
    session = open_session(
        engine, adapter(None, mock=True), purpose="video", permit=permit(None), transport=refuse
    )
    assert session.mock and session.endpoint_id == "mock"
    assert close_session(engine, session, reason="STEP_DONE", transport=refuse) is None
    assert rows(engine)[0].status == "CLOSED"


@pytest.mark.parametrize(
    ("allow", "stopped", "values", "code"),
    [
        (False, False, {}, "BLOCKED_INFRA_DISABLED"),
        (True, True, {}, "BLOCKED_STOP"),
        (
            True,
            False,
            {"step": "assemble", "action": "media.paid_generation"},
            "BLOCKED_NOT_IN_STEP",
        ),
        (True, False, {"owner_press": False}, "BLOCKED_NOT_IN_STEP"),
    ],
)
def test_the_kernel_refuses_before_anything_is_sent(
    engine, tmp_path, monkeypatch, allow, stopped, values, code
):
    _, identifier = studio_integration(engine, tmp_path, monkeypatch, allow=allow)
    if stopped:
        stop_autonomy(engine)
    fake = Fake()
    with pytest.raises(GpuSessionRefused) as caught:
        open_session(
            engine,
            adapter(identifier),
            purpose="image",
            permit=permit(identifier, **values),
            transport=fake,
        )
    assert caught.value.code == code and caught.value.unsent and caught.value.reason_ro
    assert fake.calls == [] and rows(engine) == []


def test_no_bucket_is_refused_before_the_gpu_is_switched_on(engine, tmp_path, monkeypatch):
    _, identifier = studio_integration(engine, tmp_path, monkeypatch)
    fake = Fake()
    with pytest.raises(GpuSessionRefused) as caught:
        open_session(
            engine,
            adapter(identifier, s3_bucket=None),
            purpose="image",
            permit=permit(identifier),
            transport=fake,
        )
    assert caught.value.code == "NOT_CONFIGURED" and fake.calls == []


def test_a_failed_switch_on_sends_nothing_and_switches_back_off(engine, tmp_path, monkeypatch):
    _, identifier = studio_integration(engine, tmp_path, monkeypatch)
    fake = Fake()
    fake.fail[("PATCH", "/v2/serverless/ep-stills")] = [
        MediaProviderError("bad request", http_status=400)
    ]
    with pytest.raises(GpuSessionRefused) as caught:
        open_session(
            engine, adapter(identifier), purpose="image", permit=permit(identifier), transport=fake
        )
    assert caught.value.code == "COMPUTE_NOT_READY" and caught.value.unsent
    assert fake.patched()[-1] == {"workers": {"min": 0, "max": 0, "idleTimeout": 1}}
    (row,) = rows(engine)
    assert row.status == "FAILED_OPEN" and row.close_reason == "OPEN_FAILED"
    assert not [c for c in fake.calls if "/run" in c[2]]


def test_an_unverified_off_is_told_once_and_never_breaks_the_step(engine, tmp_path, monkeypatch):
    _, identifier = studio_integration(engine, tmp_path, monkeypatch)
    fake = Fake()
    session = open_session(
        engine, adapter(identifier), purpose="image", permit=permit(identifier), transport=fake
    )
    busy = {
        "jobs": {"inProgress": 1, "inQueue": 0},
        "workers": {"idle": 0, "running": 1},
    }
    fake.health_answers["ep-stills"] = [busy] * 100_000
    reading = close_session(engine, session, reason="STEP_DONE", transport=fake)
    assert reading is not None and not reading.off
    (row,) = rows(engine)
    assert row.status == "CLOSED" and row.verified_off is False
    assert len(events(engine, "runpod.gpu_off_unverified")) == 1
    assert any("GPU" in subject for subject in owner_letters(engine))


def test_a_close_whose_off_request_fails_is_logged_not_raised(engine, tmp_path, monkeypatch):
    _, identifier = studio_integration(engine, tmp_path, monkeypatch)
    fake = Fake()
    session = open_session(
        engine, adapter(identifier), purpose="image", permit=permit(identifier), transport=fake
    )
    fake.fail[("PATCH", "/v2/serverless/ep-stills")] = [
        MediaProviderError("down", http_status=500)
    ] * 5
    fake.fail[("POST", "/v2/ep-stills/purge-queue")] = [MediaProviderError("x", http_status=400)]
    reading = close_session(engine, session, reason="STEP_DONE", transport=fake)
    assert reading is not None and not reading.off
    (row,) = rows(engine)
    assert row.status == "CLOSED" and row.verified_off is False and row.error_code


def test_two_sessions_on_one_endpoint_share_the_gpu(engine, tmp_path, monkeypatch):
    _, identifier = studio_integration(engine, tmp_path, monkeypatch)
    fake = Fake()
    first = open_session(
        engine, adapter(identifier), purpose="image", permit=permit(identifier), transport=fake
    )
    second = open_session(
        engine, adapter(identifier), purpose="image", permit=permit(identifier), transport=fake
    )
    assert len(fake.patched()) == 1
    assert close_session(engine, first, reason="STEP_DONE", transport=fake) is None
    assert len(fake.patched()) == 1
    last = close_session(engine, second, reason="STEP_DONE", transport=fake)
    assert last is not None and last.off
    assert fake.patched()[-1]["workers"]["max"] == 0


def test_one_gpu_at_once_across_endpoints(engine, tmp_path, monkeypatch):
    _, identifier = studio_integration(engine, tmp_path, monkeypatch)
    fake = Fake()
    open_session(
        engine, adapter(identifier), purpose="image", permit=permit(identifier), transport=fake
    )
    with pytest.raises(GpuSessionRefused) as caught:
        open_session(
            engine,
            adapter(identifier, gpu_busy_wait_seconds=0),
            purpose="video",
            permit=permit(identifier, action="media.motion_purchase", step="motion"),
            transport=fake,
        )
    assert caught.value.code == "GPU_BUSY"
    assert len(fake.patched()) == 1


def test_the_step_context_closes_on_failure_and_reraises(engine, tmp_path, monkeypatch):
    _, identifier = studio_integration(engine, tmp_path, monkeypatch)
    fake = Fake()
    with (
        pytest.raises(RuntimeError),
        gpu_session.gpu_session(
            engine,
            adapter(identifier),
            purpose="image",
            permit=permit(identifier),
            transport=fake,
        ),
    ):
        raise RuntimeError("the step broke")
    (row,) = rows(engine)
    assert row.status == "CLOSED" and row.close_reason == "STEP_FAILED"
    assert fake.patched()[-1]["workers"]["max"] == 0


def test_the_owner_off_works_under_stop_and_ends_the_running_step(engine, tmp_path, monkeypatch):
    vault, identifier = studio_integration(engine, tmp_path, monkeypatch)
    fake = Fake()
    session = open_session(
        engine, adapter(identifier), purpose="image", permit=permit(identifier), transport=fake
    )
    session.note_job("job-7")
    with Session(engine) as s, s.begin():
        s.execute(
            text(
                "INSERT INTO cloud_generation_job (id, idempotency_key, payload_hash, provider, "
                "target, project_id, scene_id, attempt, operation, model, gpu, hourly_rate, "
                "status, request, output, created_at, poll_count, batch_remote_id, "
                "gpu_session_id) VALUES ('j1', :key, 'h', 'RUNPOD', 't', 'film-1', '1', 1, "
                "'image', 'Qwen-Image-2512', 'g', '4.00', 'RUNNING', '{}', '{}', 'now', 0, "
                "'job-7', :sid)"
            ),
            {"key": "k" * 64, "sid": session.id},
        )
    stop_autonomy(engine)
    fake.calls.clear()
    readings = force_off(engine, vault, reason="OWNER_OFF", transport=fake)
    assert {r.endpoint_id for r in readings} == {"ep-stills", "ep-motion"}
    assert all(r.off for r in readings)
    cancelled = [c[2] for c in fake.calls if "/cancel/" in c[2]]
    assert cancelled == ["/v2/ep-stills/cancel/job-7"]
    (row,) = rows(engine)
    assert row.status == "FORCED_OFF" and row.close_reason == "OWNER_OFF"
    with pytest.raises(GpuForcedOff):
        session.renew()
    with pytest.raises(GpuForcedOff):
        session.check()
    # The step's own close afterwards changes nothing and sends nothing.
    fake.calls.clear()
    assert close_session(engine, session, reason="STEP_FAILED", transport=fake) is None
    assert fake.calls == []
    # Idempotent: a second press reads OFF again.
    assert all(r.off for r in force_off(engine, vault, reason="OWNER_OFF", transport=fake))


def test_the_window_close_off_is_fast_purge_and_patch_only(engine, tmp_path, monkeypatch):
    vault, _ = studio_integration(engine, tmp_path, monkeypatch)
    fake = Fake(workers_max=1)
    readings = force_off(engine, vault, reason="LAUNCHER_STOP", fast=True, transport=fake)
    assert sorted(fake.verbs()) == ["PATCH", "PATCH", "purge-queue", "purge-queue"]
    assert all(c[5]["timeout"] <= 2 for c in fake.calls)
    assert len(readings) == 2 and not any(r.off for r in readings)


def test_status_shape_for_the_page(engine, tmp_path, monkeypatch):
    vault, identifier = studio_integration(engine, tmp_path, monkeypatch)
    gpu_session.forget_readings()
    fake = Fake(workers_max=0)
    empty = gpu_status(engine, vault, transport=fake)
    assert empty["configured"] and not empty["mock"] and empty["rate_usd_per_hour"] == "4.00"
    assert fake.calls == []  # not fresh: served from the guard's last reading
    assert {e["state"] for e in empty["endpoints"]} == {"UNKNOWN"}
    session = open_session(
        engine, adapter(identifier), purpose="image", permit=permit(identifier), transport=fake
    )
    live = gpu_status(engine, vault, fresh=True, transport=fake)
    by_purpose = {e["purpose"]: e for e in live["endpoints"]}
    assert by_purpose["image"]["state"] == "ON" and by_purpose["image"]["workers_max"] == 1
    assert by_purpose["video"]["state"] == "OFF"
    # the session is said in the Owner's words since c529061 («imaginile»), its step stays its code
    assert live["sessions"][0]["step"] == "stills" and "imaginile" in live["words_ro"]
    calls = len(fake.calls)
    gpu_status(engine, vault, fresh=True, transport=fake)
    assert len(fake.calls) == calls  # one live read per endpoint per 10 s
    close_session(engine, session, reason="STEP_DONE", transport=fake)
    after = gpu_status(engine, vault, transport=fake)
    assert after["last_off"]["reason"] == "STEP_DONE" and after["last_off"]["verified"] is True


def test_status_without_runpod_is_not_configured(engine, tmp_path):
    vault = CredentialVault(tmp_path / "none.key")
    status = gpu_status(engine, vault)
    assert status["configured"] is False and status["endpoints"] == []


def test_step_permit_from_the_purchase_guard(engine):
    guard = PurchaseGuard.after(
        engine,
        {"allowed": True, "approval_id": "a-1"},
        action="media.motion_purchase",
        step="motion",
        storyboard_id="film-2",
        requester="director",
        cost_usd=3.0,
        context={"plan_hash": "p2"},
        unasked=True,
        correlation_id="c-2",
    )
    made = StepPermit.from_guard(
        guard,
        {"allowed": True, "approval_id": "a-1"},
        action="media.motion_purchase",
        step="motion",
        storyboard_id="film-2",
        plan_hash="p2",
        requester="director",
        correlation_id="c-2",
        integration_id="i-1",
        unasked=True,
    )
    assert made.approval_id == "a-1" and made.owner_press is False and made.cost_usd == 3.0
    assert made.context() == {
        "step_action": "media.motion_purchase",
        "plan_hash": "p2",
        "approval_id": "a-1",
        "owner_press": False,
        "integration_id": "i-1",
    }


# ------------------------------------------------------------------------------- the guard


def orphan(engine, identifier: str, endpoint: str = "ep-stills", **values: Any) -> str:
    row_id = str(uuid4())
    base = {
        "id": row_id,
        "integration_id": identifier,
        "endpoint_id": endpoint,
        "purpose": "image",
        "step": "stills",
        "storyboard_id": "film-1",
        "correlation_id": "c",
        "process_token": "another-process",
        "status": "OPEN",
        "workers_max": 1,
        "opened_at": "2026-10-08T00:00:00+00:00",
        "renewed_at": "2026-10-08T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "remote_job_ids": [],
    } | values
    with Session(engine) as session, session.begin():
        session.add(GpuSessionRow(**base))
    return row_id


def test_boot_forces_an_old_process_session_off_and_switches_the_gpu_off(
    engine, tmp_path, monkeypatch
):
    vault, identifier = studio_integration(engine, tmp_path, monkeypatch)
    orphan(engine, identifier)
    fake = Fake(workers_max=1, running=1)
    summary = gpu_guard.run_gpu_guard(engine, vault, reason="BOOT", transport=fake)
    (row,) = rows(engine)
    assert row.status == "FORCED_OFF" and row.close_reason == "GUARD_ORPHAN"
    assert fake.endpoint("ep-stills")["workers"]["max"] == 0
    assert "ep-stills" in summary["turned_off"]
    assert events(engine, "runpod.gpu_guard_off")
    assert any("GPU" in s for s in owner_letters(engine))


def test_a_tick_leaves_a_live_session_alone(engine, tmp_path, monkeypatch):
    vault, identifier = studio_integration(engine, tmp_path, monkeypatch)
    fake = Fake()
    open_session(
        engine, adapter(identifier), purpose="image", permit=permit(identifier), transport=fake
    )
    fake.calls.clear()
    summary = gpu_guard.run_gpu_guard(engine, vault, reason="TICK", transport=fake)
    assert "ep-stills" not in summary["turned_off"]
    assert not [c for c in fake.calls if c[2] == "/v2/serverless/ep-stills" and c[1] == "PATCH"]
    assert rows(engine)[0].status == "OPEN"


def test_a_tick_forces_stale_and_expired_sessions_off(engine, tmp_path, monkeypatch):
    vault, identifier = studio_integration(engine, tmp_path, monkeypatch)
    stale = orphan(engine, identifier, process_token=gpu_session.PROCESS_TOKEN)
    expired = orphan(
        engine,
        identifier,
        endpoint="ep-motion",
        purpose="video",
        process_token=gpu_session.PROCESS_TOKEN,
        renewed_at="2999-01-01T00:00:00+00:00",
        expires_at="2000-01-01T00:00:00+00:00",
    )
    fake = Fake(workers_max=1)
    gpu_guard.run_gpu_guard(engine, vault, reason="TICK", transport=fake)
    found = {row.id: row for row in rows(engine)}
    assert found[stale].close_reason == "GUARD_STALE" and found[stale].status == "FORCED_OFF"
    assert found[expired].close_reason == "GUARD_TTL"
    assert fake.endpoint("ep-stills")["workers"]["max"] == 0
    assert fake.endpoint("ep-motion")["workers"]["max"] == 0


def test_drift_is_put_back_to_the_baseline(engine, tmp_path, monkeypatch):
    vault, _ = studio_integration(engine, tmp_path, monkeypatch)
    fake = Fake()
    fake.endpoint("ep-stills")["workers"]["idleTimeout"] = 30
    gpu_guard.run_gpu_guard(engine, vault, reason="TICK", transport=fake)
    baseline = {
        "workers": {"min": 0, "max": 0, "idleTimeout": 1},
        "timeout": 2_400_000,
        "flashboot": "FLASHBOOT",
    }
    assert baseline in fake.patched()
    assert events(engine, "runpod.endpoint_settings_drift")


def test_three_unreadable_ticks_are_told(engine, tmp_path, monkeypatch):
    vault, _ = studio_integration(engine, tmp_path, monkeypatch)
    gpu_guard.reset_counters()
    fake = Fake()
    fake.fail[("GET", "/v2/serverless/ep-stills")] = [MediaProviderError("no", http_status=403)] * 3
    for _ in range(3):
        gpu_guard.run_gpu_guard(engine, vault, reason="TICK", transport=fake)
    assert len(events(engine, "runpod.gpu_guard_unreadable")) == 1
    assert any("Nu pot verifica" in s for s in owner_letters(engine))


def test_the_guard_skips_a_studio_without_runpod_and_a_simulation(engine, tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("no call")

    vault = CredentialVault(tmp_path / "none.key")
    assert (
        gpu_guard.run_gpu_guard(engine, vault, reason="TICK", transport=refuse)["endpoints"] == []
    )
    vault, _ = studio_integration(engine, tmp_path, monkeypatch, mock="true")
    assert (
        gpu_guard.run_gpu_guard(engine, vault, reason="TICK", transport=refuse)["endpoints"] == []
    )


def test_next_interval_is_short_while_a_session_is_open(engine, tmp_path, monkeypatch):
    assert gpu_guard.next_interval(engine, (60, 600)) == 600
    _, identifier = studio_integration(engine, tmp_path, monkeypatch)
    orphan(engine, identifier)
    assert gpu_guard.next_interval(engine, (60, 600)) == 60


# ---------------------------------------------------------------------------- the launcher


def test_the_launcher_off_prints_one_line_and_always_answers_zero(engine, tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "runpod_gpu_off", Path(__file__).resolve().parents[1] / "scripts/runpod_gpu_off.py"
    )
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    empty_vault = CredentialVault(tmp_path / "none.key")
    assert script.run(engine, empty_vault, reason="LAUNCHER_STOP", fast=False) is None
    vault, _ = studio_integration(engine, tmp_path, monkeypatch)
    fake = Fake(workers_max=1)
    line = script.run(engine, vault, reason="LAUNCHER_STOP", fast=False, transport=fake)
    assert line == "GPU RunPod: oprit și verificat."
    fake.fail[("PATCH", "/v2/serverless/ep-stills")] = [MediaProviderError("x", http_status=400)]
    line = script.run(engine, vault, reason="LAUNCHER_STOP", fast=True, transport=fake)
    assert line.startswith("GPU RunPod: oprirea nu a putut fi verificată")

    def broken(*args, **kwargs):
        raise RuntimeError("no studio")

    monkeypatch.setattr(script, "studio", broken)
    assert script.main(["--reason", "LAUNCHER_STOP"]) == 0


def _start_module():
    import sys

    from app.config import ROOT

    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    import start

    return start


def test_start_switches_the_gpu_off_after_the_server_and_the_graphics_stop():
    from test_live_graphics import FakeServer, FakeSupervisor

    start = _start_module()
    server = FakeServer(interrupts=1)
    graphics = FakeSupervisor(server.events)
    code = start.serve(
        ["python", "run.py"],
        graphics=graphics,
        popen=lambda *a, **k: server,
        port_busy=lambda: False,
        port_open=lambda: True,
        assign=lambda pid: None,
        install_close_handler=lambda callback: None,
        gpu_off=lambda fast: server.events.append(f"gpu off fast={fast}"),
    )
    assert code == 0
    assert server.events == ["server exited", "graphics stopped", "gpu off fast=False"]


def test_closing_the_window_sends_the_fast_gpu_off_first():
    from test_live_graphics import FakeServer, FakeSupervisor

    start = _start_module()
    server = FakeServer()
    graphics = FakeSupervisor(server.events)
    handlers: list[Any] = []
    start.serve(
        ["python", "run.py"],
        graphics=graphics,
        popen=lambda *a, **k: server,
        port_busy=lambda: False,
        port_open=lambda: True,
        assign=lambda pid: None,
        install_close_handler=handlers.append,
        gpu_off=lambda fast: server.events.append(f"gpu off fast={fast}"),
    )
    server.events.clear()
    handlers[0]()
    assert server.events[:2] == ["gpu off fast=True", "graphics stopped"]


def test_the_launcher_runs_the_off_script_with_its_own_interpreter(monkeypatch):
    start = _start_module()
    seen: list[tuple[list[str], dict[str, Any]]] = []

    def run(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(start.subprocess, "run", run)
    start.runpod_gpu_off(False)
    start.runpod_gpu_off(True)
    (slow, slow_kw), (fast, fast_kw) = seen
    assert slow[1].endswith("runpod_gpu_off.py") and "--fast" not in slow
    assert slow_kw["timeout"] == 45 and fast_kw["timeout"] == 4 and fast[-1] == "--fast"
    assert slow[slow.index("--reason") + 1] == "LAUNCHER_STOP"

    def late(command, **kwargs):
        raise start.subprocess.TimeoutExpired(command, 4)

    monkeypatch.setattr(start.subprocess, "run", late)
    start.runpod_gpu_off(True)  # never raises: a stopping launcher is never held


def _check_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_runpod", Path(__file__).resolve().parents[1] / "scripts/check_runpod.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_offline_check_reads_the_new_fields_and_never_the_network():
    check = _check_module()
    report = check.config_check(config())
    assert report["mode"] == "serverless" and report["rate_usd_per_hour"] == "4.00"
    assert report["endpoints"] == {"image": "ep-stills", "video": "ep-motion"}
    assert report["bucket_configured"] and report["idle_timeout_seconds"] == 1
    assert report["max_workers"] == 1 and report["problems"] == []
    text_report = json.dumps(report)
    assert KEY not in text_report and S3_SECRET not in text_report and S3_ID not in text_report
    missing = check.config_check(
        config(s3_bucket=None, stills_endpoint_id=None, motion_endpoint_id=None)
    )
    assert len(missing["problems"]) == 2 and not missing["ready"]


def test_an_unreadable_vault_is_said_not_hidden(engine, tmp_path, monkeypatch):
    studio_integration(engine, tmp_path, monkeypatch)
    other = CredentialVault(tmp_path / "another-machine.key")

    def refuse(*args, **kwargs):
        raise AssertionError("no key, no call")

    status = gpu_status(engine, other, fresh=True, transport=refuse)
    assert status["configured"] and {e["state"] for e in status["endpoints"]} == {"UNKNOWN"}
    assert all("seif" in e["problem_ro"] for e in status["endpoints"])
    readings = force_off(engine, other, reason="LAUNCHER_STOP", transport=refuse)
    assert len(readings) == 2 and not any(r.off for r in readings)
