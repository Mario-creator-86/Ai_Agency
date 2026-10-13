"""Adversary (2026-10-08): nothing keeps a RunPod GPU billing. The Owner: «trebuie sa se opreasca
imediat dupa, nu la 30 sec. Sunt taxat la secunda, deci trebuie oprit imediat dupa generare».

The real GPU session, the real rounds and the real guard run against one fake RunPod (management
host, queue host) and one fake bucket. Nothing reaches RunPod, a bucket or Hugging Face."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.models import OwnerPolicy
from app.providers.media_http import MediaProviderError
from app.providers.runpod import endpoint as endpoint_module
from app.providers.runpod import gpu_guard, gpu_session
from app.providers.runpod.adapters import RunPodImageAdapter
from app.providers.runpod.batch import BatchRefused
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.gpu_session import (
    GpuSessionRow,
    close_session,
    force_off,
    gpu_status,
    open_session,
)
from app.providers.runpod.jobs import GenerationJob
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_runpod_batch import Cloud, request
from test_runpod_gpu_control import (
    S3_ID,
    S3_SECRET,
    Fake,
    events,
    owner_letters,
    permit,
    rows,
    stop_autonomy,
    studio_integration,
)

KEY = "fake-runpod-key"  # pragma: allowlist secret - synthetic test value


def serverless(**values: Any) -> RunPodConfig:
    base: dict[str, Any] = {
        "enabled": True,
        "mode": "serverless",
        "api_key": KEY,
        "stills_endpoint_id": "ep-stills",
        "motion_endpoint_id": "ep-motion",
        "s3_endpoint_url": "https://account.r2.example",
        "s3_bucket": "amn-films",
        "s3_access_key_id": S3_ID,
        "s3_secret_access_key": S3_SECRET,
        "poll_interval": 0.01,
        "off_poll_seconds": 0.01,
        "off_grace_seconds": 0,
        "max_retries": 1,
    }
    return RunPodConfig(_env_file=None, **(base | values))


class RunPod:
    """RunPod's two hosts and the Owner's bucket behind one transport: the management API and
    the health/purge/cancel side are `Fake`, /run and /status and the bucket are `Cloud`."""

    def __init__(self, **fake: Any) -> None:
        self.fake = Fake(**fake)
        self.cloud = Cloud()
        self.lock = threading.Lock()

    def __call__(self, host, method, path, headers, body=None, **kwargs):
        with self.lock:
            if host == "api.runpod.ai":
                verb = path.split("/")[3]
                if verb in ("run", "status"):
                    self.fake.calls.append((host, method, path, dict(headers), None, kwargs))
                    return self.cloud(host, method, path, headers, body, **kwargs)
                if verb == "cancel":
                    self.cloud.calls.append((host, method, path, body))
                return self.fake(host, method, path, headers, body, **kwargs)
            if host == "api.runpod.io":
                return self.fake(host, method, path, headers, body, **kwargs)
        return self.cloud(host, method, path, headers, body, **kwargs)

    def cancelled(self) -> list[str]:
        return [c[2].rsplit("/", 1)[1] for c in self.fake.calls if "/cancel/" in c[2]]

    def runs(self) -> int:
        return len(self.cloud.posts())

    def workers_max(self, endpoint: str = "ep-stills") -> int:
        return int(self.fake.endpoint(endpoint)["workers"]["max"])


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(endpoint_module, "backoff_seconds", lambda attempt: 0)
    monkeypatch.setattr(gpu_session, "BUSY_POLL_SECONDS", 0.01)
    gpu_session.forget_readings()
    gpu_guard.reset_counters()


@pytest.fixture
def studio(engine, tmp_path, monkeypatch):
    """The Owner's studio, running (no stop), with a RunPod integration agents may switch on in
    approved steps; every RunPod call (also the session's own, which takes no transport) goes
    to one fake."""
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    vault, identifier = studio_integration(engine, tmp_path, monkeypatch)
    runpod = RunPod()
    monkeypatch.setattr(endpoint_module, "request", runpod)
    made = RunPodImageAdapter(
        serverless(),
        engine,
        model="Qwen-Image-2512",
        integration_id=identifier,
        storage_root=tmp_path,
    )
    made.core.transport = made.core.client.transport = runpod
    return {"vault": vault, "id": identifier, "runpod": runpod, "adapter": made}


class Meter:
    def __init__(self) -> None:
        self.committed = 0.0
        self.attempts = 0


def run(engine, studio, first, *, on_outcome=None, stopped=lambda: None, next_round=None):
    from app.media.gpu_batch import run_rounds

    meter = Meter()
    seen: list[Any] = []

    def landed(outcome):
        seen.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)

    summary = run_rounds(
        engine,
        studio["adapter"],
        permit=permit(studio["id"]),
        purpose="image",
        first_round=first,
        next_round=next_round or (lambda outcomes: []),
        price_credits=lambda requests: 10.0 * len(requests) + 5.0,
        cap_left=lambda: 1000.0 - meter.committed,
        guard=None,
        stopped=stopped,
        on_submitted=lambda item: None,
        on_outcome=landed,
        meter=meter,
        sleep=lambda s: None,
    )
    return summary, meter, seen


def finish_on_status(studio, job: str, *indexes: int) -> None:
    """The worker finishes these items of ``job`` the first time its status is read."""
    cloud = studio["runpod"].cloud
    original = cloud.__call__
    done: set[int] = set()

    def call(host, method, path, headers, body=None, **kwargs):
        if host == "account.r2.example" and "/manifests/" in path and job in cloud.jobs:
            for n in indexes:
                if n not in done:
                    done.add(n)
                    cloud.finish(job, n)
        return original(host, method, path, headers, body, **kwargs)

    studio["runpod"].cloud = _Callable(cloud, call)


class _Callable:
    """`Cloud` with a replaced call (instances' __call__ is looked up on the type)."""

    def __init__(self, inner: Cloud, call: Any) -> None:
        self._inner, self._call = inner, call

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._call(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def journal(engine) -> list[GenerationJob]:
    with Session(engine) as session:
        found = list(session.scalars(select(GenerationJob)))
        for row in found:
            session.expunge(row)
        return found


def assert_off(runpod: RunPod, endpoint: str = "ep-stills") -> None:
    assert runpod.workers_max(endpoint) == 0


# ------------------------------------------------------------------- the step raises mid-batch


def test_a_step_raising_mid_batch_cancels_its_job_and_switches_off(engine, studio):
    finish_on_status(studio, "job-1", 0)

    def broken(outcome):
        raise RuntimeError("the judge broke on the first candidate")

    with pytest.raises(RuntimeError):
        run(engine, studio, [request("1", 0), request("1", 1)], on_outcome=broken)
    runpod = studio["runpod"]
    assert runpod.runs() == 1
    assert "job-1" in runpod.cancelled()
    assert_off(runpod)
    (row,) = rows(engine)
    assert row.status == "CLOSED" and row.close_reason == "STEP_FAILED" and row.verified_off


# --------------------------------------------- the studio dies between switch-on and the close


def test_a_studio_killed_mid_batch_is_switched_off_and_cancelled_at_the_next_boot(
    engine, studio, monkeypatch
):
    session = open_session(
        engine, studio["adapter"], purpose="image", permit=permit(studio["id"]), transport=None
    )
    studio["adapter"].submit_batch(
        [request("1", 0), request("1", 1)], session=session, on_submitted=lambda item: None
    )
    runpod = studio["runpod"]
    assert runpod.workers_max() == 1
    # The process dies here: no close. The next studio is another process.
    monkeypatch.setattr(gpu_session, "PROCESS_TOKEN", str(uuid4()))
    monkeypatch.setattr(gpu_guard, "PROCESS_TOKEN", gpu_session.PROCESS_TOKEN)
    runpod.fake.calls.clear()
    summary = gpu_guard.run_gpu_guard(engine, studio["vault"], reason="BOOT", transport=runpod)
    (row,) = rows(engine)
    assert row.status == "FORCED_OFF" and row.close_reason == "GUARD_ORPHAN"
    assert "purge-queue" in runpod.fake.verbs()
    assert runpod.cancelled() == ["job-1"]
    assert_off(runpod)
    assert "ep-stills" in summary["turned_off"]


def test_a_killed_studio_never_restarted_is_switched_off_by_the_tick_of_a_live_one(engine, studio):
    """A session of a live process that stopped renewing (its thread hung) is stale."""
    session = open_session(
        engine, studio["adapter"], purpose="image", permit=permit(studio["id"]), transport=None
    )
    session.note_job("job-9")
    old = (datetime.now(UTC) - timedelta(seconds=400)).isoformat()
    with Session(engine) as db, db.begin():
        db.get(GpuSessionRow, session.id).renewed_at = old
    runpod = studio["runpod"]
    gpu_guard.run_gpu_guard(engine, studio["vault"], reason="TICK", transport=runpod)
    (row,) = rows(engine)
    assert row.status == "FORCED_OFF" and row.close_reason == "GUARD_STALE"
    assert_off(runpod)


# ------------------------------------------------------------------- the guard under STOP


def test_the_guard_switches_off_under_stop_autonomie(engine, studio):
    runpod = studio["runpod"]
    runpod.fake.endpoint("ep-stills")["workers"]["max"] = 1
    runpod.fake.default_health["workers"]["running"] = 1  # 0 once max is 0 (the fake's rule)
    stop_autonomy(engine)
    gpu_guard.run_gpu_guard(engine, studio["vault"], reason="TICK", transport=runpod)
    assert_off(runpod)
    assert "purge-queue" in runpod.fake.verbs()
    assert events(engine, "runpod.gpu_guard_off")
    readings = force_off(engine, studio["vault"], reason="OWNER_OFF", transport=runpod)
    assert readings and all(r.off for r in readings)


# ------------------------------------------------------- two films sharing the one endpoint


def test_a_film_failing_beside_another_cancels_its_own_job_and_leaves_the_gpu_to_the_other(
    engine, studio
):
    runpod = studio["runpod"]
    adapter = studio["adapter"]
    first = open_session(
        engine, adapter, purpose="image", permit=permit(studio["id"]), transport=None
    )
    second = open_session(
        engine,
        adapter,
        purpose="image",
        permit=permit(studio["id"], storyboard_id="film-2"),
        transport=None,
    )
    adapter.submit_batch([request("1", 0)], session=first, on_submitted=lambda item: None)
    adapter.submit_batch(
        [request("1", 0, project_id="film-2")], session=second, on_submitted=lambda item: None
    )
    runpod.fake.calls.clear()
    # The first film's step breaks while its job is still running: its job is cancelled, the
    # queue (the second film's job) is not purged and the GPU stays on for the second film.
    assert close_session(engine, first, reason="STEP_FAILED") is None
    assert runpod.cancelled() == ["job-1"]
    assert "purge-queue" not in runpod.fake.verbs() and runpod.fake.patched() == []
    assert runpod.workers_max() == 1
    reading = close_session(engine, second, reason="STEP_DONE")
    assert reading is not None and reading.off
    assert "job-2" in runpod.cancelled()
    assert_off(runpod)


# --------------------------------------------------------------------- a late /run after close


def test_no_run_is_posted_once_the_owner_switched_the_gpu_off(engine, studio):
    session = open_session(
        engine, studio["adapter"], purpose="image", permit=permit(studio["id"]), transport=None
    )
    runpod = studio["runpod"]
    force_off(engine, studio["vault"], reason="OWNER_OFF", transport=runpod)
    with pytest.raises(BatchRefused) as caught:
        studio["adapter"].submit_batch(
            [request("1", 0)], session=session, on_submitted=lambda item: None
        )
    assert caught.value.code == "GPU_FORCED_OFF" and caught.value.unsent
    assert runpod.runs() == 0
    (job,) = journal(engine)
    assert job.status == "FAILED" and job.error_code == "UNSENT" and job.cost_value == "0"
    assert_off(runpod)


def test_a_step_whose_gpu_was_switched_off_before_its_first_round_spends_nothing(
    engine, studio, monkeypatch
):
    from app.media import gpu_batch

    real = gpu_batch.gpu_session

    def switched_off_at_once(engine_, adapter, **kw):
        manager = real(engine_, adapter, **kw)

        class Wrapped:
            def __enter__(self):
                opened = manager.__enter__()
                force_off(engine, studio["vault"], reason="OWNER_OFF", transport=studio["runpod"])
                return opened

            def __exit__(self, *exc):
                return manager.__exit__(*exc)

        return Wrapped()

    monkeypatch.setattr(gpu_batch, "gpu_session", switched_off_at_once)
    with pytest.raises(BatchRefused):
        run(engine, studio, [request("1", 0)])
    assert studio["runpod"].runs() == 0
    assert_off(studio["runpod"])


# ---------------------------------------------------------- the close's PATCH fails (network)


def test_a_close_whose_patch_keeps_failing_retries_alarms_and_the_guard_finishes_it(engine, studio):
    runpod = studio["runpod"]
    session = open_session(
        engine, studio["adapter"], purpose="image", permit=permit(studio["id"]), transport=None
    )
    down = [MediaProviderError("network down", unsent=True) for _ in range(10)]
    runpod.fake.fail[("PATCH", "/v2/serverless/ep-stills")] = down
    runpod.fake.calls.clear()
    reading = close_session(engine, session, reason="STEP_DONE")
    assert reading is not None and not reading.off
    # Retried (max_retries=1: two attempts), never raised.
    assert len([c for c in runpod.fake.calls if c[1] == "PATCH"]) == 2
    (row,) = rows(engine)
    assert row.status == "CLOSED" and row.verified_off is False and "MAX0" in row.error_code
    assert len(events(engine, "runpod.gpu_off_unverified")) == 1
    assert any("nu a confirmat" in subject for subject in owner_letters(engine))
    # The network is back: the guard's next tick finds max=1 with no step open and ends it.
    runpod.fake.fail.clear()
    summary = gpu_guard.run_gpu_guard(engine, studio["vault"], reason="TICK", transport=runpod)
    assert "ep-stills" in summary["turned_off"]
    assert_off(runpod)


# ------------------------------------------------- RunPod's own scale-to-zero, idle, the loop


def test_runpods_own_scale_to_zero_with_idle_workers_is_off_not_a_fault(engine, studio):
    runpod = studio["runpod"]
    runpod.fake.endpoint("ep-stills")["workers"]["max"] = 0  # RunPod's 7-day rule
    runpod.fake.default_health["workers"]["idle"] = 3  # FlashBoot keeps them, not billed
    letters = owner_letters(engine)
    summary = gpu_guard.run_gpu_guard(engine, studio["vault"], reason="TICK", transport=runpod)
    assert summary["turned_off"] == [] and summary["drift"] == []
    assert runpod.fake.patched() == [] and "purge-queue" not in runpod.fake.verbs()
    assert not events(engine, "runpod.gpu_guard_off")
    assert owner_letters(engine) == letters
    status = gpu_status(engine, studio["vault"], fresh=True, transport=runpod)
    assert {e["state"] for e in status["endpoints"]} == {"OFF"}
    assert status["words_ro"] == "GPU oprit."


def test_idle_workers_after_a_close_are_verified_off_and_never_alarmed(engine, studio):
    runpod = studio["runpod"]
    runpod.fake.default_health["workers"]["idle"] = 5
    letters = owner_letters(engine)
    session = open_session(
        engine, studio["adapter"], purpose="image", permit=permit(studio["id"]), transport=None
    )
    reading = close_session(engine, session, reason="STEP_DONE")
    assert reading is not None and reading.off and reading.idle == 5
    assert not events(engine, "runpod.gpu_off_unverified") and owner_letters(engine) == letters


def test_the_verify_off_loop_ends_at_its_deadline_whatever_runpod_answers(engine, studio):
    import time

    runpod = studio["runpod"]
    busy = {"jobs": {"inProgress": 1, "inQueue": 0}, "workers": {"idle": 0, "running": 1}}
    runpod.fake.health_answers["ep-stills"] = [busy] * 100_000
    control = endpoint_module.EndpointControl(serverless(off_grace_seconds=1), "ep-stills", runpod)
    started = time.monotonic()
    import asyncio

    late = asyncio.run(control.verify_off())
    assert not late.off and time.monotonic() - started < 5
    # Unreadable every time (the network is down): also ends, said, not raised.
    runpod.fake.fail[("GET", "/v2/serverless/ep-stills")] = [
        MediaProviderError("down", unsent=True) for _ in range(10_000)
    ]
    started = time.monotonic()
    unread = asyncio.run(control.verify_off(deadline_seconds=0.2))
    assert not unread.off and unread.reason_ro and time.monotonic() - started < 5


# ------------------------------------------------- the Owner's «Oprește GPU acum» in a step


def test_the_owner_off_during_a_step_keeps_what_was_paid_and_buys_nothing_more(engine, studio):
    finish_on_status(studio, "job-1", 0)
    runpod = studio["runpod"]

    def press(outcome):
        if outcome.state == "COMPLETED":
            force_off(engine, studio["vault"], reason="OWNER_OFF", transport=runpod)

    summary, meter, seen = run(
        engine,
        studio,
        [request("1", 0), request("1", 1)],
        on_outcome=press,
        next_round=lambda outcomes: [request("2", 0)],
    )
    assert summary["forced_off"] and "GPU-ul a fost oprit" in summary["stopped"]
    assert sorted(o.state for o in seen) == ["CANCELLED", "COMPLETED"]
    assert runpod.runs() == 1  # no next round after the Owner's off
    assert "job-1" in runpod.cancelled()
    assert meter.committed == 15.0  # the made candidate and the round's start, not the other
    (row,) = rows(engine)
    assert row.status == "FORCED_OFF" and row.close_reason == "OWNER_OFF"
    assert_off(runpod)


def test_a_long_qc_inside_a_round_is_not_taken_for_a_dead_step(engine, studio):
    """The studio judges each candidate while the worker makes the next; a judgement may take
    minutes. The guard must not take that for a dead step and cancel the paid batch."""
    finish_on_status(studio, "job-1", 0, 1)
    ticks: list[dict[str, Any]] = []

    def slow_judge(outcome):
        if not ticks:
            # The first judgement took 400 s (longer than session_stale_seconds).
            with Session(engine) as db, db.begin():
                live = db.scalars(select(GpuSessionRow)).one()
                live.renewed_at = (datetime.now(UTC) - timedelta(seconds=400)).isoformat()
            ticks.append({})
            return
        # The guard ticks during the second judgement.
        ticks.append(gpu_guard.run_gpu_guard(engine, studio["vault"], reason="TICK"))

    summary, _meter, seen = run(
        engine, studio, [request("1", 0), request("1", 1)], on_outcome=slow_judge
    )
    assert not summary["forced_off"] and summary["stopped"] is None
    assert [o.state for o in seen] == ["COMPLETED", "COMPLETED"]
    assert ticks[-1]["forced"] == []
    (row,) = rows(engine)
    assert row.close_reason == "STEP_DONE" and row.verified_off


# ---------------------------------------------------------------- every endpoint, promptly


def _blocking_stills(
    runpod: RunPod,
    method_path: tuple[str, str],
    seen: threading.Event,
    patched: str = "/ep-motion",
):
    """The stills endpoint's first purge answers only once ``patched`` got its max=0 (or after
    3 s): an off that waits for one request before sending the next never sees it."""
    original = runpod.__call__
    waited: list[bool] = []

    def call(host, method, path, headers, body=None, **kwargs):
        if (method, path) == method_path and not waited:
            waited.append(seen.wait(timeout=3))
        answer = original(host, method, path, headers, body, **kwargs)
        if method == "PATCH" and path.endswith(patched):
            seen.set()
        return answer

    return call, waited


def test_the_window_close_off_never_waits_on_a_slow_purge_before_max_zero(engine, studio):
    """The window-close off has about 4 s in all: a purge that hangs (2 s, a slow network)
    must not hold back the max=0, the request that stops new workers."""
    runpod = studio["runpod"]
    runpod.fake.endpoint("ep-stills")["workers"]["max"] = 1
    seen = threading.Event()
    call, waited = _blocking_stills(
        runpod, ("POST", "/v2/ep-stills/purge-queue"), seen, patched="/ep-stills"
    )
    force_off(engine, studio["vault"], reason="LAUNCHER_STOP", fast=True, transport=call)
    assert waited == [True] and runpod.workers_max("ep-stills") == 0


@pytest.mark.parametrize("fast", [False, True])
def test_an_off_sends_every_endpoint_its_max_zero_without_waiting_on_another(engine, studio, fast):
    runpod = studio["runpod"]
    for endpoint in ("ep-stills", "ep-motion"):
        runpod.fake.endpoint(endpoint)["workers"]["max"] = 1
    seen = threading.Event()
    call, waited = _blocking_stills(runpod, ("POST", "/v2/ep-stills/purge-queue"), seen)
    readings = force_off(engine, studio["vault"], reason="LAUNCHER_STOP", fast=fast, transport=call)
    assert waited == [True]
    assert runpod.workers_max("ep-stills") == 0 and runpod.workers_max("ep-motion") == 0
    assert {r.endpoint_id for r in readings} == {"ep-stills", "ep-motion"}
    if not fast:
        assert all(r.off for r in readings)


def test_the_launcher_script_switches_off_what_a_killed_studio_left_on(engine, studio):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "runpod_gpu_off", Path(__file__).resolve().parents[1] / "scripts/runpod_gpu_off.py"
    )
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    session = open_session(
        engine, studio["adapter"], purpose="image", permit=permit(studio["id"]), transport=None
    )
    session.note_job("job-3")
    runpod = studio["runpod"]
    line = script.run(engine, studio["vault"], reason="LAUNCHER_STOP", fast=False, transport=runpod)
    assert line == "GPU RunPod: oprit și verificat."
    assert runpod.cancelled() == ["job-3"]
    (row,) = rows(engine)
    assert row.status == "FORCED_OFF" and row.close_reason == "LAUNCHER_STOP"
    assert_off(runpod)
