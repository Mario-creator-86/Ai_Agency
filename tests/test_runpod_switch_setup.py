"""The Owner's «RunPod pornit» switch and the read-only «Pașii configurării» checklist
(2026-10-09, his card: the switch replaces editing RUNPOD_ENABLED in .env).

- The switch is stored with the RunPod integration (an event recorded); the effective value is
  the switch when set, else the environment's RUNPOD_ENABLED, else false, and every reader of
  ``RunPodConfig.enabled`` sees it without a restart.
- ON needs a VERIFIED connection and the Owner's key; OFF is always allowed and switches the
  GPU off at once (purge, cancel, workers.max=0) and stops a running copy pod.
- The checklist only reads (GET an endpoint's settings, HEAD the bucket), never creates,
  PATCHes or POSTs, and never returns a secret.

Every RunPod and bucket call goes to a fake transport; nothing reaches the internet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.integrations.models import Integration
from app.integrations.services import SaveIntegration, save
from app.integrations.vault import CredentialVault
from app.models import DomainEvent
from app.providers.media_http import MediaProviderError
from app.providers.runpod import endpoint as endpoint_module
from app.providers.runpod import gpu_session, pods, setup_steps
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.gpu_session import runpod_targets
from sqlalchemy import select
from sqlalchemy.orm import Session

KEY = "fake-runpod-key"  # pragma: allowlist secret - synthetic test value
S3_ID = "fake-access-id"  # pragma: allowlist secret - synthetic test value
S3_SECRET = "fake-s3-secret"  # pragma: allowlist secret - synthetic test value
HF = "hf_fakefakefakefakefakefake"  # pragma: allowlist secret - synthetic test value
REV = "a" * 40


class Fake:
    """RunPod's management API, its queue, and the bucket. Answers by (host, method, path)."""

    def __init__(self, *, workers: dict[str, Any] | None = None, bucket_status: int = 200):
        self.calls: list[tuple[str, str, str]] = []
        self.workers = {"min": 0, "max": 0, "idleTimeout": 1} | (workers or {})
        self.bucket_status = bucket_status
        self.endpoint_status: dict[str, int] = {}
        self.max: dict[str, int] = {}

    def __call__(self, host, method, path, headers, body=None, **kwargs):
        self.calls.append((host, method, path))
        if host == "api.runpod.io":
            identifier = path.split("?")[0].rsplit("/", 1)[-1]
            status = self.endpoint_status.get(identifier)
            if status:
                raise MediaProviderError("refused", http_status=status)
            if method == "PATCH":
                self.max[identifier] = json.loads(body)["workers"]["max"]
            workers = dict(self.workers)
            if identifier in self.max:
                workers["max"] = self.max[identifier]
            return (
                {
                    "id": identifier,
                    "workers": workers,
                    "timeout": 2_400_000,
                    "flashboot": "FLASHBOOT",
                    "image": "registry/amn:1",
                },
                b"",
                "application/json",
            )
        if host == "api.runpod.ai":
            verb = path.split("/")[3]
            if verb == "health":
                return (
                    {
                        "jobs": {"inQueue": 0, "inProgress": 0, "completed": 0, "failed": 0},
                        "workers": {"idle": 0, "running": 0},
                    },
                    b"",
                    "application/json",
                )
            if verb == "purge-queue":
                return {"removed": 0, "status": "completed"}, b"", "application/json"
            raise AssertionError(path)
        assert host == "bucket.example", host
        assert method == "HEAD"
        if self.bucket_status != 200:
            raise MediaProviderError("bucket", http_status=self.bucket_status)
        return None, b"", ""

    def methods(self) -> set[str]:
        return {method for _, method, _ in self.calls}


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(endpoint_module, "backoff_seconds", lambda attempt: 0)
    gpu_session.forget_readings()
    monkeypatch.setattr(pods, "watch_copies", lambda *a, **k: {"terminated": []})


def connection(
    engine,
    monkeypatch,
    *,
    env: str = "false",
    status: str = "VERIFIED",
    secrets: dict[str, str] | None = None,
    **values: str,
) -> tuple[CredentialVault, str]:
    """A saved real RunPod Serverless connection, as his form makes it."""
    monkeypatch.setenv("RUNPOD_ENABLED", env)
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
        SaveIntegration(kind="runpod", name="RunPod", config=form, secrets=keys),  # type: ignore[arg-type]
    )
    with Session(engine) as session, session.begin():
        row = session.get(Integration, identifier)
        row.status = status
        row.config = {**row.config, "off_grace_seconds": "0", "off_poll_seconds": "0.01"}
    return vault, identifier


def effective(engine, vault) -> bool:
    [target] = runpod_targets(engine, vault)
    assert target.config is not None
    return target.config.enabled


# ------------------------------------------------------------------- the effective value


def test_the_switch_wins_then_the_environment_then_false(engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch, env="false")
    assert effective(engine, vault) is False
    monkeypatch.setenv("RUNPOD_ENABLED", "true")
    assert effective(engine, vault) is True  # no switch yet: the environment decides
    state = setup_steps.switch_state(engine, identifier)
    assert state["on"] is True and state["source"] == "environment"
    setup_steps.set_switch(engine, vault, identifier, on=False, transport=Fake())
    assert effective(engine, vault) is False  # his OFF beats RUNPOD_ENABLED=true
    assert setup_steps.switch_state(engine, identifier)["source"] == "switch"
    monkeypatch.delenv("RUNPOD_ENABLED")
    # His real .env is never read by the suite: "neither" means no environment at all.
    without_env_file = {**RunPodConfig.model_config, "env_file": None}
    monkeypatch.setattr(RunPodConfig, "model_config", without_env_file)
    with Session(engine) as session, session.begin():
        row = session.get(Integration, identifier)
        row.config = {k: v for k, v in row.config.items() if k != "enabled"}
    assert effective(engine, vault) is False  # neither: false


def test_on_needs_a_verified_connection_and_says_why_in_romanian(engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch, status="SAVED")
    with pytest.raises(setup_steps.SwitchRefused) as refused:
        setup_steps.set_switch(engine, vault, identifier, on=True)
    assert "verificat" in refused.value.reason_ro
    assert effective(engine, vault) is False
    with Session(engine) as session:
        assert "enabled" not in session.get(Integration, identifier).config


def test_on_records_an_event_and_every_reader_sees_it_without_a_restart(engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch, env="false")
    with Session(engine) as session:
        version = session.get(Integration, identifier).version
    answer = setup_steps.set_switch(engine, vault, identifier, on=True)
    assert answer["on"] is True and answer["words_ro"]
    assert effective(engine, vault) is True
    config = RunPodConfig.from_integration(
        dict(session_config(engine, identifier)), {"api_key": KEY}
    )
    assert config.enabled and config.configured
    with Session(engine) as session:
        row = session.get(Integration, identifier)
        assert row.config["enabled"] == "true" and row.version == version + 1
        event = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "runpod.switch_changed")
        ).one()
        assert event.payload["on"] is True and event.payload["by"] == "owner"


def session_config(engine, identifier: str) -> dict[str, Any]:
    with Session(engine) as session:
        return dict(session.get(Integration, identifier).config)


def test_off_is_always_allowed_and_switches_both_endpoints_off_and_the_copy_pod(
    engine, monkeypatch
):
    vault, identifier = connection(engine, monkeypatch, env="true", status="FAILED")
    copies: list[str] = []
    monkeypatch.setattr(
        pods,
        "watch_copies",
        lambda engine, vault, *, reason, transport=None: copies.append(reason) or {},
    )
    fake = Fake(workers={"max": 1})
    answer = setup_steps.set_switch(engine, vault, identifier, on=False, transport=fake)
    assert answer["on"] is False
    assert fake.max == {"ep-stills": 0, "ep-motion": 0}
    assert {r["endpoint_id"] for r in answer["readings"]} == {"ep-stills", "ep-motion"}
    assert copies == ["SHUTDOWN"]
    assert effective(engine, vault) is False


def test_a_form_save_keeps_the_switch(engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch)
    setup_steps.set_switch(engine, vault, identifier, on=True)
    with Session(engine) as session:
        version = session.get(Integration, identifier).version
    save(
        engine,
        vault,
        identifier,
        SaveIntegration(
            kind="runpod",
            name="RunPod",
            expected_version=version,
            config={"stills_endpoint_id": "ep-stills", "motion_endpoint_id": "ep-motion"},
        ),
    )
    assert session_config(engine, identifier)["enabled"] == "true"


def test_the_form_cannot_set_the_switch(engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch)
    with pytest.raises(ValueError):
        save(
            engine,
            vault,
            identifier,
            SaveIntegration(
                kind="runpod",
                name="RunPod",
                expected_version=session_version(engine, identifier),
                config={"enabled": "true"},
            ),
        )


def session_version(engine, identifier: str) -> int:
    with Session(engine) as session:
        return session.get(Integration, identifier).version


# ------------------------------------------------------- verification while the switch is off


def test_verification_works_with_the_switch_off_and_the_periodic_pass_skips_it(engine, monkeypatch):
    from app.integrations.discovery import refresh_catalog, refresh_due_catalogs

    vault, identifier = connection(engine, monkeypatch, env="false", status="SAVED")
    fake = Fake()
    monkeypatch.setattr(endpoint_module, "request", fake)
    result = refresh_catalog(
        engine, vault, identifier, interval_seconds=600, retry_seconds=60, force=True
    )
    assert result["status"] == "VERIFIED"
    assert fake.methods() == {"GET"}
    fake.calls.clear()
    from app.integrations.models import ProviderDiscovery

    with Session(engine) as session, session.begin():
        session.get(ProviderDiscovery, identifier).next_refresh_at = "2000-01-01T00:00:00+00:00"
    refresh_due_catalogs(engine, vault, interval_seconds=600, retry_seconds=60)
    assert fake.calls == []  # the switch is off: no background reads of his RunPod
    with Session(engine) as session:
        assert session.get(Integration, identifier).status == "VERIFIED"


# ------------------------------------------------------------------------- the checklist


def rows(answer: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["key"]: row for row in answer["rows"]}


def test_the_check_only_reads_and_never_returns_a_secret(engine, monkeypatch):
    vault, identifier = connection(
        engine,
        monkeypatch,
        secrets={
            "api_key": KEY,
            "s3_access_key_id": S3_ID,
            "s3_secret_access_key": S3_SECRET,
            "hf_token": HF,
        },
        stills_mirror_repo="mario/amn-stills",
        motion_mirror_repo="mario/amn-motion",
        stills_mirror_revision=REV,
    )
    fake = Fake()
    answer = setup_steps.checklist(engine, vault, identifier, fresh=True, transport=fake)
    assert fake.methods() <= {"GET", "HEAD"}
    assert {path for _, _, path in fake.calls if "serverless" in path} == {
        "/v2/serverless/ep-stills",
        "/v2/serverless/ep-motion",
    }
    text = json.dumps(answer, ensure_ascii=False)
    for secret in (KEY, S3_ID, S3_SECRET, HF):
        assert secret not in text
    found = rows(answer)
    assert found["api_key"]["status"] == "green" and "salvată" in found["api_key"]["words_ro"]
    assert found["hf_token"]["status"] == "green"
    assert found["endpoint_ids"]["status"] == "green"
    assert found["endpoint_stills"]["status"] == "green"
    assert found["endpoint_motion"]["status"] == "green"
    assert found["cached_model"]["status"] == "grey"
    assert "weights_revision" in found["cached_model"]["words_ro"]
    assert found["bucket"]["status"] == "green"
    assert found["mirror_repos"]["status"] == "green"
    assert found["mirror_revisions"]["status"] == "red"  # motion's revision is missing
    assert found["switch"]["status"] == "red"
    for row in answer["rows"]:
        assert row["status"] in ("green", "red", "grey")
        assert row["words_ro"]
        assert row["link"] is None or row["link"].startswith(setup_steps.LINK_PREFIXES)


def test_a_drifted_endpoint_and_a_refused_bucket_are_red_with_the_reason(engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch)
    fake = Fake(workers={"min": 1, "idleTimeout": 30}, bucket_status=403)
    fake.endpoint_status["ep-motion"] = 401
    found = rows(setup_steps.checklist(engine, vault, identifier, fresh=True, transport=fake))
    assert found["endpoint_stills"]["status"] == "red"
    assert "min" in found["endpoint_stills"]["words_ro"]
    assert "idleTimeout" in found["endpoint_stills"]["words_ro"]
    assert found["endpoint_motion"]["status"] == "red"
    assert "401" in found["endpoint_motion"]["words_ro"]
    assert found["bucket"]["status"] == "red" and "403" in found["bucket"]["words_ro"]
    assert fake.methods() <= {"GET", "HEAD"}


def test_page_open_reads_the_cached_results_without_any_request(engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch)
    never = Fake()
    first = rows(setup_steps.checklist(engine, vault, identifier, fresh=False, transport=never))
    assert first["endpoint_stills"]["status"] == "grey"
    assert "Verifică pașii" in first["endpoint_stills"]["words_ro"]
    setup_steps.checklist(engine, vault, identifier, fresh=True, transport=Fake())
    cached = setup_steps.checklist(engine, vault, identifier, fresh=False, transport=never)
    assert rows(cached)["endpoint_stills"]["status"] == "green"
    assert rows(cached)["bucket"]["status"] == "green"
    assert cached["checked_at"]
    assert never.calls == []


def test_without_a_key_nothing_is_called_and_the_rows_say_what_is_missing(engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch, secrets={})
    fake = Fake()
    found = rows(setup_steps.checklist(engine, vault, identifier, fresh=True, transport=fake))
    assert found["api_key"]["status"] == "red" and "lipsește" in found["api_key"]["words_ro"]
    assert found["endpoint_stills"]["status"] == "red"
    assert found["bucket"]["status"] == "red"
    assert fake.calls == []


def test_the_decision_rows_follow_his_cards(engine, monkeypatch):
    from app.decisions.services import propose_owner_decision
    from app.decisions.sources import runpod_infra_card

    vault, identifier = connection(engine, monkeypatch)
    with Session(engine) as session, session.begin():
        row = session.get(Integration, identifier)
        propose_owner_decision(session, **runpod_infra_card(row), source="audit")
    found = rows(setup_steps.checklist(engine, vault, identifier, fresh=False))
    assert found["decision_gpu"]["status"] == "red"
    assert "Decizii" in found["decision_gpu"]["words_ro"]
    assert found["decision_bakeoff"]["status"] == "grey"
    with Session(engine) as session, session.begin():
        row = session.get(Integration, identifier)
        row.config = {**row.config, "allow_infra_actions": "true"}
    found = rows(setup_steps.checklist(engine, vault, identifier, fresh=False))
    assert found["decision_gpu"]["status"] == "green"


# ------------------------------------------------------------------------------ the routes


def test_the_routes_need_the_owner_and_refuse_on_without_verification(
    client, headers, engine, monkeypatch
):
    vault, identifier = connection(engine, monkeypatch, status="SAVED")
    base = f"/api/v1/runpod/integrations/{identifier}"
    assert client.get(base + "/setup").status_code == 401
    body = {"schema_version": 1, "on": True}
    assert client.put(base + "/switch", json=body).status_code == 401
    refused = client.put(base + "/switch", json=body, headers=headers)
    assert refused.status_code == 409
    assert "verificat" in refused.json()["detail"]
    page = client.get(base + "/setup", headers=headers)
    assert page.status_code == 200
    assert page.json()["switch"]["on"] is False
    assert page.json()["switch"]["can_turn_on"] is False
    monkeypatch.setattr(endpoint_module, "request", Fake())
    off = client.put(base + "/switch", json={"schema_version": 1, "on": False}, headers=headers)
    assert off.status_code == 200 and off.json()["on"] is False
    missing = client.get(f"/api/v1/runpod/integrations/{uuid4()}/setup", headers=headers)
    assert missing.status_code == 404


def test_the_check_route_reads_through_the_fakes(client, headers, engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch)
    fake = Fake()
    monkeypatch.setattr(setup_steps, "request", fake)
    answer = client.post(f"/api/v1/runpod/integrations/{identifier}/setup/check", headers=headers)
    assert answer.status_code == 200
    assert rows(answer.json())["bucket"]["status"] == "green"
    assert fake.methods() <= {"GET", "HEAD"} and fake.calls


# ------------------------------------------- verified as the Owner (2026-10-09): honest words


def test_a_green_endpoint_row_says_only_what_runpod_answered(engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch)
    fake = Fake()
    fake.workers.pop("idleTimeout")  # RunPod's answer left it out: it was not checked
    found = rows(setup_steps.checklist(engine, vault, identifier, fresh=True, transport=fake))
    words = found["endpoint_stills"]["words_ro"]
    assert found["endpoint_stills"]["status"] == "green"
    assert "min 0, max 0" in words and "timeout 2400000 ms" in words and "FLASHBOOT" in words
    assert "idleTimeout 1 s" not in words
    assert "idleTimeout nu apare" in words


def test_a_check_on_an_invalid_connection_does_not_ask_for_the_check_again(engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch)
    with Session(engine) as session, session.begin():
        row = session.get(Integration, identifier)
        row.config = {**row.config, "idle_timeout_seconds": "99999"}  # outside 1..3600
    fake = Fake()
    found = rows(setup_steps.checklist(engine, vault, identifier, fresh=True, transport=fake))
    assert fake.calls == []
    for key in ("endpoint_stills", "endpoint_motion", "bucket"):
        assert found[key]["status"] == "red", key
        assert "Verifică pașii" not in found[key]["words_ro"]
        assert "Modifică" in found[key]["words_ro"]


# ------------------------------------------------- adversary: security and money (2026-10-09)


class Strict:
    """Refuses every call but the checklist's reads: GET /v2/serverless/{id} on RunPod's
    management host and one HEAD on the bucket. Records the keyword arguments too."""

    def __init__(self, *, endpoint_status: int | None = None) -> None:
        self.calls: list[tuple[str, str, str, dict[str, str], Any, dict[str, Any]]] = []
        self.endpoint_status = endpoint_status

    def __call__(self, host, method, path, headers, body=None, **kwargs):
        self.calls.append((host, method, path, dict(headers), body, kwargs))
        if host == "api.runpod.io" and method == "GET" and path.startswith("/v2/serverless/"):
            assert body is None
            if self.endpoint_status:
                raise MediaProviderError("busy", http_status=self.endpoint_status)
            identifier = path.rsplit("/", 1)[-1]
            return (
                {
                    "id": identifier,
                    "workers": {"min": 0, "max": 0, "idleTimeout": 1},
                    "timeout": 2_400_000,
                    "flashboot": "FLASHBOOT",
                },
                b"",
                "application/json",
            )
        if host == "bucket.example" and method == "HEAD":
            assert body is None
            return None, b"", ""
        raise AssertionError(f"the checklist may not send {method} {host}{path}")


def test_the_check_sends_only_the_allowed_reads_with_a_short_timeout_and_no_secret(
    engine, monkeypatch, caplog
):
    caplog.set_level("DEBUG")
    vault, identifier = connection(
        engine,
        monkeypatch,
        secrets={
            "api_key": KEY,
            "s3_access_key_id": S3_ID,
            "s3_secret_access_key": S3_SECRET,
            "hf_token": HF,
        },
    )
    strict = Strict()
    answer = setup_steps.checklist(engine, vault, identifier, fresh=True, transport=strict)
    sent = sorted((host, method) for host, method, *_ in strict.calls)
    assert sent == [
        ("api.runpod.io", "GET"),
        ("api.runpod.io", "GET"),
        ("bucket.example", "HEAD"),
    ]
    for host, _method, path, headers, _body, kwargs in strict.calls:
        assert kwargs["timeout"] <= setup_steps.CHECK_TIMEOUT_SECONDS
        assert kwargs["total_seconds"] <= setup_steps.CHECK_TIMEOUT_SECONDS
        assert "/run" not in path
        # The bucket's secret never leaves the studio (SigV4 sends only a signature), and the
        # RunPod key goes only to RunPod.
        assert S3_SECRET not in path and S3_SECRET not in json.dumps(headers)
        if host == "bucket.example":
            assert KEY not in json.dumps(headers) and "Authorization" not in headers
    with Session(engine) as session:
        stored = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == setup_steps.CHECK_EVENT)
        ).one()
        kept = json.dumps(stored.payload)
    page = json.dumps(answer, ensure_ascii=False)
    for secret in (KEY, S3_ID, S3_SECRET, HF):
        assert secret not in page and secret not in kept and secret not in caplog.text
    for row in answer["rows"]:
        for secret in (KEY, S3_ID, S3_SECRET, HF):
            assert secret not in str(row["link"])


def test_a_busy_runpod_is_read_once_never_retried(engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch)
    strict = Strict(endpoint_status=503)
    found = rows(setup_steps.checklist(engine, vault, identifier, fresh=True, transport=strict))
    endpoint_calls = [c for c in strict.calls if c[0] == "api.runpod.io"]
    assert len(endpoint_calls) == 2  # one GET per endpoint, no retry on 503
    assert found["endpoint_stills"]["status"] == "red"
    assert found["endpoint_motion"]["status"] == "red"


def test_his_on_beats_runpod_enabled_false_and_the_page_says_so(engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch, env="false")
    state = setup_steps.switch_state(engine, identifier)
    assert state["on"] is False and state["source"] == "environment"
    assert "RUNPOD_ENABLED" in state["words_ro"]
    setup_steps.set_switch(engine, vault, identifier, on=True)
    state = setup_steps.switch_state(engine, identifier)
    assert state["on"] is True and state["source"] == "switch" and state["environment"] is False
    assert "RUNPOD_ENABLED" not in state["words_ro"]
    assert effective(engine, vault) is True


def test_a_wrong_key_cannot_move_the_switch(client, engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch, env="false")
    answer = client.put(
        f"/api/v1/runpod/integrations/{identifier}/switch",
        json={"schema_version": 1, "on": True},
        headers={"Authorization": "Bearer not-the-owner"},
    )
    assert answer.status_code == 401
    assert "enabled" not in session_config(engine, identifier)
    assert effective(engine, vault) is False


def test_a_step_built_before_his_off_never_switches_the_gpu_on(engine, monkeypatch):
    """The race: a paid step built its adapter (enabled) a moment before he pressed OFF. Its
    GPU session must read his switch again and refuse, never PATCH workers.max=1."""
    from types import SimpleNamespace

    from app.models import OwnerPolicy
    from app.providers.runpod.gpu_session import GpuSessionRefused, StepPermit, open_session

    vault, identifier = connection(engine, monkeypatch, env="false")
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False  # his studio as it runs
        row = session.get(Integration, identifier)
        row.config = {**row.config, "allow_infra_actions": "true"}
    setup_steps.set_switch(engine, vault, identifier, on=True)
    with Session(engine) as session:
        row = session.get(Integration, identifier)
        built = RunPodConfig.from_integration(
            dict(row.config), vault.decrypt(row.encrypted_secrets)
        )
    assert built.enabled and built.configured
    setup_steps.set_switch(engine, vault, identifier, on=False, transport=Fake())
    fake = Fake()
    permit = StepPermit(
        action="media.stills_purchase",
        step="stills",
        storyboard_id="film-1",
        plan_hash="plan-1",
        requester="director",
        approval_id=None,
        owner_press=True,
        correlation_id=str(uuid4()),
        integration_id=identifier,
    )
    with pytest.raises(GpuSessionRefused) as refused:
        open_session(
            engine,
            SimpleNamespace(config=built, integration_id=identifier),
            purpose="image",
            permit=permit,
            transport=fake,
        )
    assert refused.value.code == "RUNPOD_OFF" and refused.value.unsent
    assert "oprit" in refused.value.reason_ro
    assert "PATCH" not in fake.methods()
    with Session(engine) as session:
        sessions = list(session.scalars(select(gpu_session.GpuSessionRow)))
    assert [(r.status, r.error_code) for r in sessions] == [("FAILED_OPEN", "RUNPOD_OFF")]


def test_a_missing_endpoint_links_to_the_serverless_list_and_says_so(engine, monkeypatch):
    vault, identifier = connection(engine, monkeypatch, motion_endpoint_id="")
    found = rows(setup_steps.checklist(engine, vault, identifier, fresh=False))
    assert found["endpoint_motion"]["link"] == setup_steps.RUNPOD_SERVERLESS
    assert found["endpoint_motion"]["link_ro"] == "Consola RunPod → Serverless"
    assert found["endpoint_stills"]["link"].endswith("/serverless/user/endpoint/ep-stills")
    assert found["endpoint_stills"]["link_ro"] == "Consola RunPod → endpointul"
