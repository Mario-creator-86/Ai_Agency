"""Where the RunPod weights live (the Owner's cards, 2026-10-09): RunPod CACHED MODELS, one
cached model per endpoint, each his own private Hugging Face mirror. The studio cannot set or
read the endpoint's Model field (no REST field), so it checks what every result reports
(``weights_revision``) against the mirror revision it expects; a mismatch or MODELS_MISSING
stops the step, switches the GPU off and puts a card in his Decisions window. A cache miss can
happen on ANY round and its wait is unbilled, so the cache wait is always inside the job's TTL.
Every RunPod and bucket call is faked; nothing reaches RunPod or Hugging Face."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest
from app.decisions.models import OwnerDecision
from app.providers.runpod import batch as batch_module
from app.providers.runpod import weights
from app.providers.runpod.config import SECRET_FIELDS, RunPodConfig
from app.providers.runpod.endpoint import EndpointControl
from pydantic import ValidationError
from runpod_worker import contract
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_runpod_batch import (  # noqa: F401 - the fixture is used by name
    Cloud,
    Session_,
    adapter,
    fake_session,
    request,
    rounds,
    serverless,
)

STILLS_REV = "a" * 40
OTHER_REV = "b" * 40


# ------------------------------------------------------------------------------ settings


def test_defaults_follow_his_cards():
    c = RunPodConfig(_env_file=None)
    assert c.model_source == "cache"
    assert c.model_cache_wait_seconds == 3600
    assert c.stills_mirror_repo is None and c.stills_mirror_revision is None
    assert c.motion_mirror_repo is None and c.motion_mirror_revision is None
    assert c.network_volumes == [] and c.data_center_ids == []
    assert "hf_token" in SECRET_FIELDS
    assert c.hf_token.get_secret_value() == ""


def test_the_form_strings_become_lists_and_bad_values_are_refused():
    c = RunPodConfig.from_integration(
        {
            "model_source": "volume",
            "network_volumes": "vol_abc, vol_def",
            "data_center_ids": "EU-RO-1",
            "stills_mirror_repo": "mario/amn-stills",
            "stills_mirror_revision": STILLS_REV,
        },
        {"hf_token": "hf_synthetic"},  # pragma: allowlist secret - synthetic test value
    )
    assert c.network_volumes == ["vol_abc", "vol_def"] and c.data_center_ids == ["EU-RO-1"]
    assert c.mirror_for("image") == ("mario/amn-stills", STILLS_REV)
    assert c.mirror_for("video") == (None, None)
    assert c.hf_token.get_secret_value() == "hf_synthetic"
    for bad in (
        {"model_source": "disk"},
        {"stills_mirror_repo": "no-owner"},
        {"motion_mirror_repo": "a/b/c"},
        {"stills_mirror_revision": "main"},
        {"network_volumes": "vol bad"},
        {"model_cache_wait_seconds": "-1"},
    ):
        with pytest.raises(ValidationError):
            RunPodConfig.from_integration(bad, {})


def test_the_cache_wait_is_always_inside_the_ttl_and_never_in_the_execution_timeout():
    cache = serverless()
    policy = batch_module.chunk_policy(cache, "image", 2)
    assert policy["executionTimeout"] == (120 + 2 * 180) * 1000
    assert policy["ttl"] == policy["executionTimeout"] + (900 + 3600) * 1000
    baked = batch_module.chunk_policy(serverless(model_source="baked"), "image", 2)
    assert baked["ttl"] == baked["executionTimeout"] + 900 * 1000
    shorter = batch_module.chunk_policy(serverless(model_cache_wait_seconds=600), "video", 1)
    assert shorter["ttl"] == shorter["executionTimeout"] + (900 + 600) * 1000


class Management:
    def __init__(self):
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, host, method, path, headers, body=None, **kwargs):
        data = json.loads(body) if body else {}
        self.bodies.append(data)
        workers = data.get("workers") or {"min": 0, "max": 0, "idleTimeout": 1}
        return {"id": "ep", "workers": workers}, b"", "application/json"


@pytest.mark.parametrize(
    ("source", "expected"),
    [("cache", False), ("baked", False), ("volume", True)],
)
def test_the_volume_fields_are_sent_only_for_the_volume_fallback(source, expected):
    transport = Management()
    c = serverless(model_source=source, network_volumes="vol_abc", data_center_ids="EU-RO-1")
    asyncio.run(EndpointControl(c, "stills-ep", transport).apply_baseline())
    body = transport.bodies[-1]
    assert ("networkVolumes" in body) is expected
    assert "networkVolumeIds" not in body  # the v2 name is networkVolumes
    if expected:
        assert body["networkVolumes"] == ["vol_abc"] and body["dataCenterIds"] == ["EU-RO-1"]


# ----------------------------------------------------------------------- the weights check


def test_a_result_reporting_another_revision_is_a_mismatch():
    c = serverless(stills_mirror_repo="mario/amn-stills", stills_mirror_revision=STILLS_REV)
    assert weights.check_result(c, "image", {"weights_revision": STILLS_REV}) is None
    problem = weights.check_result(c, "image", {"weights_revision": OTHER_REV})
    assert problem is not None and problem.code == "WRONG_REVISION"
    assert problem.expected_revision == STILLS_REV and problem.reported_revision == OTHER_REV
    assert problem.endpoint_id == "stills-ep" and problem.expected_repo == "mario/amn-stills"
    # An old worker that reports nothing is not called wrong.
    assert weights.check_result(c, "image", {}) is None


@pytest.mark.parametrize("code", ["MODELS_MISSING", "WRONG_REVISION"])
def test_the_worker_codes_are_problems_whatever_the_source(code):
    for source in ("cache", "volume", "baked"):
        c = serverless(model_source=source)
        problem = weights.check_result(c, "video", {}, error=f"{code}: snapshot not found")
        assert problem is not None and problem.code == code and problem.purpose == "video"
    assert weights.check_result(serverless(), "image", {}, error="OOM") is None


def test_a_simulation_is_never_checked():
    c = serverless(mock=True, stills_mirror_revision=STILLS_REV)
    assert weights.check_result(c, "image", {"weights_revision": OTHER_REV}) is None


def test_the_words_name_the_endpoint_what_is_expected_and_the_console_step():
    c = serverless(stills_mirror_repo="mario/amn-stills", stills_mirror_revision=STILLS_REV)
    problem = weights.check_result(c, "image", {"weights_revision": OTHER_REV})
    assert problem is not None
    words = problem.words_ro()
    assert "stills-ep" in words and "mario/amn-stills" in words and STILLS_REV[:12] in words
    assert "Manage → Edit Endpoint → Model" in words


def test_readiness_refuses_the_cache_before_the_mirror_exists():
    assert weights.readiness_problem(serverless(), "image") is not None
    ready = serverless(stills_mirror_repo="mario/amn-stills", stills_mirror_revision=STILLS_REV)
    assert weights.readiness_problem(ready, "image") is None
    assert weights.readiness_problem(ready, "video") is not None
    assert weights.readiness_problem(serverless(model_source="baked"), "video") is None
    assert weights.readiness_problem(serverless(mock=True), "image") is None


# ------------------------------------------------------------------ a round that reports it


def _status_with(cloud: Cloud, job: str, *, revision: str | None, error: str | None = None):
    sent = cloud.jobs[job]["input"]
    items = []
    for index, _item in enumerate(sent["items"]):
        result = cloud.finish(job, index, manifest=False)
        if error:
            result = {
                "index": index,
                "idempotency_key": result["idempotency_key"],
                "status": "FAILED",
                "error": error,
                "gpu_seconds": 0.0,
            }
        if revision:
            result["weights_revision"] = revision
        items.append(result)
    output = {
        "contract": contract.CONTRACT,
        "batch_key": sent["batch_key"],
        "items": items,
        "model_load_seconds": 5.0,
        "handler_seconds": 9.0,
        "gpu_seconds": 4.0,
    }
    if revision:
        output["weights_revision"] = revision
    cloud.status_answers[job] = [
        {"id": job, "status": "COMPLETED", "output": output, "delayTime": 1, "executionTime": 2}
    ]


def test_a_batch_whose_result_carries_another_revision_reports_the_problem(engine, tmp_path):
    cloud = Cloud()
    made = adapter(
        engine,
        tmp_path,
        cloud,
        stills_mirror_repo="mario/amn-stills",
        stills_mirror_revision=STILLS_REV,
    )
    run = made.submit_batch([request("1", 0)], session=Session_(), on_submitted=lambda i: None)
    _status_with(cloud, "job-1", revision=OTHER_REV)
    outcomes = run.poll()
    assert [o.state for o in outcomes] == ["COMPLETED"]  # made and paid: kept, judged later
    assert run.weights_problem is not None
    assert run.weights_problem.code == "WRONG_REVISION"


def test_models_missing_in_a_failed_job_is_reported(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    run = made.submit_batch([request("1", 0)], session=Session_(), on_submitted=lambda i: None)
    cloud.status_answers["job-1"] = [
        {"id": "job-1", "status": "FAILED", "error": "MODELS_MISSING: no snapshot"}
    ]
    outcomes = run.poll()
    assert [o.state for o in outcomes] == ["FAILED"]
    assert run.weights_problem is not None and run.weights_problem.code == "MODELS_MISSING"


def test_a_manifest_with_the_expected_revision_is_kept_with_it(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud, stills_mirror_revision=STILLS_REV)
    run = made.submit_batch([request("1", 0)], session=Session_(), on_submitted=lambda i: None)
    result = cloud.finish("job-1", 0)
    key = contract.manifest_key("amn/", result["idempotency_key"])
    cloud.objects[key] = json.dumps({**result, "weights_revision": STILLS_REV}).encode()
    outcomes = run.poll()
    assert [o.state for o in outcomes] == ["COMPLETED"] and run.weights_problem is None
    from app.providers.runpod.jobs import GenerationJob

    with Session(engine) as s:
        row = s.scalars(select(GenerationJob)).one()
        assert row.output["weights_revision"] == STILLS_REV


# --------------------------------------------------------- the step stops, the card is his


def test_a_mismatch_stops_the_rounds_closes_the_gpu_and_raises_his_card(
    engine,
    tmp_path,
    fake_session,  # noqa: F811 - the fixture imported from test_runpod_batch
):
    cloud = Cloud()
    made = adapter(
        engine,
        tmp_path,
        cloud,
        stills_mirror_repo="mario/amn-stills",
        stills_mirror_revision=STILLS_REV,
    )
    original = cloud.__call__

    def answering(host, method, path, headers, body=None, **kwargs):
        if method == "GET" and "/status/" in path:
            job = path.rsplit("/", 1)[1]
            if job not in cloud.status_answers:
                _status_with(cloud, job, revision=OTHER_REV)
        return original(host, method, path, headers, body, **kwargs)

    made.core.transport = made.core.client.transport = answering
    asked_again = []

    def next_round(outcomes):
        asked_again.append(len(outcomes))
        return [request("1", 0, attempt=2)]

    summary, _meter, _seen = rounds(engine, made, [request("1", 0)], next_round=next_round)
    assert summary["rounds"] == 1 and not asked_again  # no further round
    assert summary["weights_problem"]["code"] == "WRONG_REVISION"
    assert "Manage → Edit Endpoint → Model" in summary["stopped"]
    assert fake_session[0]["closed"]  # the session's close is the workers.max=0
    with Session(engine) as s:
        card = s.scalars(select(OwnerDecision).where(OwnerDecision.kind == "runpod_weights")).one()
        assert card.status == "PENDING"
        text = (
            card.title_ro
            + card.why_ro
            + card.effect_ro
            + json.dumps(card.options, ensure_ascii=False)
        )
        assert "stills-ep" in text and "mario/amn-stills" in text and STILLS_REV[:12] in text
        assert "Manage → Edit Endpoint → Model" in text
    # The hold: the next step on that endpoint is refused before anything is sent.
    hold = weights.weights_hold(engine, None, "image", made.config)
    assert hold is not None and "Manage → Edit Endpoint → Model" in hold
    assert weights.weights_hold(engine, None, "video", made.config) is None


def test_his_done_releases_the_hold_and_a_new_expected_revision_too(engine, tmp_path):
    from uuid import uuid4

    from app.decisions.services import OWNER, DecideCommand, decide_owner_decision

    c = serverless(stills_mirror_repo="mario/amn-stills", stills_mirror_revision=STILLS_REV)
    problem = weights.check_result(c, "image", {"weights_revision": OTHER_REV})
    assert problem is not None
    weights.raise_weights_card(engine, problem, None)
    assert weights.weights_hold(engine, None, "image", c) is not None
    # A new copy changes what is expected: the old card no longer holds.
    newer = serverless(stills_mirror_repo="mario/amn-stills", stills_mirror_revision="c" * 40)
    assert weights.weights_hold(engine, None, "image", newer) is None
    with Session(engine) as s:
        card = s.scalars(select(OwnerDecision).where(OwnerDecision.kind == "runpod_weights")).one()
        identifier, version = card.id, card.version
    decide_owner_decision(
        engine,
        identifier,
        DecideCommand(command_id=uuid4(), expected_version=version, decision="ACCEPT"),
        issued_by=OWNER,
    )
    assert weights.weights_hold(engine, None, "image", c) is not None  # waits for his act
    with Session(engine) as s:
        version = s.get(OwnerDecision, identifier).version
    decide_owner_decision(
        engine,
        identifier,
        DecideCommand(command_id=uuid4(), expected_version=version, decision="DONE"),
        issued_by=OWNER,
    )
    assert weights.weights_hold(engine, None, "image", c) is None


# ------------------------------------------------------------------ the unbilled wait words


def test_a_job_still_in_queue_shows_the_unbilled_model_wait(engine, tmp_path):
    weights.forget_waits()
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud, model_wait_notice_seconds=0)
    run = made.submit_batch([request("1", 0)], session=Session_(), on_submitted=lambda i: None)
    cloud.status_answers["job-1"] = [{"id": "job-1", "status": "IN_QUEUE"}]
    assert run.poll() == []
    wait = weights.model_wait("stills-ep")
    assert wait is not None and wait == weights.WAIT_WORDS_RO
    assert weights.WAIT_WORDS_RO == "aștept descărcarea modelului (neplătită)"
    cloud.status_answers["job-1"] = [{"id": "job-1", "status": "IN_PROGRESS"}]
    run.poll()
    assert weights.model_wait("stills-ep") is None


def test_a_short_queue_is_not_called_a_model_download(engine, tmp_path):
    weights.forget_waits()
    weights.note_queue("ep-x", since=time.monotonic(), notice_seconds=60)
    assert weights.model_wait("ep-x") is None
    weights.note_queue("ep-x", since=time.monotonic() - 61, notice_seconds=60)
    assert weights.model_wait("ep-x") == weights.WAIT_WORDS_RO
    weights.clear_queue("ep-x")
    assert weights.model_wait("ep-x") is None


# ------------------------------------------------------- refused before his yes is spent


def test_precheck_refuses_a_cache_without_its_mirror_and_an_endpoint_on_hold(
    engine, tmp_path, monkeypatch
):
    from app.providers.runpod.gpu_session import GpuSessionRefused, precheck
    from test_runpod_gpu_policy import runpod

    _vault, identifier = runpod(engine, monkeypatch, allow=True)
    made = adapter(engine, tmp_path, Cloud())
    made.integration_id = identifier
    with pytest.raises(GpuSessionRefused) as refused:
        precheck(engine, made, purpose="image")
    assert refused.value.code == "WEIGHTS_NOT_READY" and refused.value.unsent
    assert "Hugging Face" in refused.value.reason_ro

    ready = adapter(
        engine,
        tmp_path,
        Cloud(),
        stills_mirror_repo="mario/amn-stills",
        stills_mirror_revision=STILLS_REV,
    )
    ready.integration_id = identifier
    precheck(engine, ready, purpose="image")
    problem = weights.check_result(ready.config, "image", {"weights_revision": OTHER_REV})
    assert problem is not None
    weights.raise_weights_card(engine, problem, identifier)
    with pytest.raises(GpuSessionRefused) as held:
        precheck(engine, ready, purpose="image")
    assert held.value.code == "WEIGHTS_MISMATCH"
    assert "Manage → Edit Endpoint → Model" in held.value.reason_ro


def test_the_gpu_switch_says_the_unbilled_wait(engine, tmp_path, monkeypatch):
    from app.integrations.vault import CredentialVault
    from app.providers.runpod.gpu_session import gpu_status
    from test_runpod_gpu_policy import runpod

    weights.forget_waits()
    vault, _identifier = runpod(engine, monkeypatch, allow=True)
    assert isinstance(vault, CredentialVault)
    status = gpu_status(engine, vault)
    assert status["model_wait_ro"] is None
    weights.note_queue("ep-stills", since=time.monotonic() - 120, notice_seconds=60)
    status = gpu_status(engine, vault)
    assert status["model_wait_ro"] == weights.WAIT_WORDS_RO
    stills = next(e for e in status["endpoints"] if e["endpoint_id"] == "ep-stills")
    assert stills["model_wait_ro"] == weights.WAIT_WORDS_RO
    assert weights.WAIT_WORDS_RO in status["words_ro"]
    weights.forget_waits()


# ------------------------------------------------- completeness critic (2026-10-09)
# The worker reads its mirror pin from the endpoint's environment (AMN_MIRROR_REPO /
# AMN_MIRROR_REVISION) or its image's mirrors.lock.json; the studio cannot set either (an env
# change is a release, the Model field has no API). His console step must therefore name the
# env pin with the exact values, or his Model fix alone still ends in WRONG_REVISION.


def test_the_words_and_the_card_name_the_endpoint_pin_with_the_exact_values():
    from app.decisions.sources import runpod_weights_card

    c = serverless(stills_mirror_repo="mario/amn-stills", stills_mirror_revision=STILLS_REV)
    problem = weights.check_result(c, "image", {}, error="WRONG_REVISION: no revision pinned")
    assert problem is not None
    for words in (
        problem.words_ro(),
        runpod_weights_card(problem, "conn-1")["options"][0]["apply"]["steps_ro"],
    ):
        assert "AMN_MIRROR_REPO" in words and "AMN_MIRROR_REVISION" in words
        assert STILLS_REV in words  # the whole commit: he types it exactly
        assert "mario/amn-stills" in words


def test_the_console_steps_list_each_endpoint_with_its_model_and_pin():
    c = serverless(
        stills_mirror_repo="mario/amn-stills",
        stills_mirror_revision=STILLS_REV,
        motion_mirror_repo="mario/amn-motion",
        motion_mirror_revision=OTHER_REV,
    )
    steps = weights.console_steps_ro(c)
    assert len(steps) == 2
    assert "stills-ep" in steps[0] and "mario/amn-stills" in steps[0] and STILLS_REV in steps[0]
    assert "motion-ep" in steps[1] and "mario/amn-motion" in steps[1] and OTHER_REV in steps[1]
    assert all("AMN_MIRROR_REVISION" in s and "Model" in s for s in steps)
    # A purpose with no mirror yet has no step to give.
    assert len(weights.console_steps_ro(serverless(stills_mirror_repo="mario/amn-stills"))) == 0


def test_a_cache_wait_longer_than_a_gpu_session_is_refused():
    # The longest round's ttl (execution cap + queue wait + cache wait) must fit in one GPU
    # session, or the session's own end would cut the unbilled download short.
    with pytest.raises(ValidationError):
        serverless(model_cache_wait_seconds=20_000)
    assert serverless(model_cache_wait_seconds=20_000, session_max_seconds=30_000)
    assert serverless(model_cache_wait_seconds=20_000, model_source="baked")


def test_the_pod_pip_fallback_is_the_workers_own_pin():
    from pathlib import Path

    from app.providers.runpod import pods

    lines = (Path(pods.WORKER_DIR) / "requirements-mirror.txt").read_text("utf-8").splitlines()
    pinned = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    assert RunPodConfig(_env_file=None).mirror_pod_pip in pinned
