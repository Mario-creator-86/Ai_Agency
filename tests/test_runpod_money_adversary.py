"""Adversary on the money of the RunPod staircase (2026-10-08): caps, the Owner's mode, an
ambiguous submit, items that fail, crashes, and the cost booked against what RunPod used.

Every RunPod and bucket call goes to the fake ``Cloud`` of test_runpod_batch; the GPU session
is the recorded fake (CONTROL's own tests cover the real switch)."""

import asyncio
from decimal import Decimal

import pytest
from app.media.assembler import SpendMeter, _record_intent, collect_submitted_takes
from app.media.models import SceneTake
from app.providers.media_http import MediaProviderError
from app.providers.runpod.adapters import RunPodVideoAdapter
from app.providers.runpod.jobs import GenerationJob
from app.providers.runpod.mock import png
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_runpod_batch import (
    Cloud,
    Session_,
    adapter,
    finishing,
    permit,
    price,
    request,
    stills_table,
)


@pytest.fixture
def fake_session(monkeypatch):
    """The GPU session around the rounds, recorded (as test_runpod_batch's own fixture)."""
    from contextlib import contextmanager

    from app.media import gpu_batch

    opened = []

    @contextmanager
    def fake(engine, adapter, *, purpose, permit):
        session = Session_()
        opened.append({"purpose": purpose, "session": session, "closed": False})
        try:
            yield session
        finally:
            opened[-1]["closed"] = True

    monkeypatch.setattr(gpu_batch, "gpu_session", fake)
    # The real session would read his card in the kernel; the fake one stands in for it, so
    # the precheck before his yes stands aside too (tests/test_runpod_owner_setup.py).
    monkeypatch.setattr(gpu_batch, "gpu_precheck", lambda *args, **kwargs: None)
    return opened


def go(engine, made, first, *, next_round=None, cap=1000.0, guard=None, **kw):
    """`run_rounds` with the 10-credits-an-item, 5-a-round price of test_runpod_batch."""
    from app.media.gpu_batch import run_rounds

    meter = SpendMeter()
    seen: list = []
    summary = run_rounds(
        engine,
        made,
        permit=permit(),
        purpose="image",
        first_round=first,
        next_round=next_round or (lambda outcomes: []),
        price_credits=price,
        cap_left=lambda: cap - meter.committed,
        guard=guard,
        stopped=kw.pop("stopped", lambda: None),
        on_submitted=kw.pop("on_submitted", lambda item: None),
        on_outcome=seen.append,
        meter=meter,
        sleep=lambda s: None,
        **kw,
    )
    return summary, meter, seen


class Guard:
    """The step's PurchaseGuard: the Owner's mode, read before each round and while it runs."""

    def __init__(self, lowered_after: int, reason: str = "Proprietarul a coborât modul.") -> None:
        self.reads = 0
        self.lowered_after = lowered_after
        self.reason = reason

    def stop_reason(self, scene):
        self.reads += 1
        return self.reason if self.reads > self.lowered_after else None


def timed(cloud, *, delay_ms, execution_ms):
    """A worker that finishes every item into the bucket; /status reports the job's times."""
    inner = finishing(cloud)

    def call(host, method, path, headers, body=None, **kwargs):
        if method == "GET" and "/status/" in path:
            job = path.rsplit("/", 1)[1]
            answer = {
                "id": job,
                "status": "COMPLETED",
                "delayTime": delay_ms,
                "executionTime": execution_ms,
                "output": {
                    "contract": "amn.batch.v1",
                    "batch_key": cloud.jobs[job]["input"]["batch_key"],
                    "items": [],
                    "model_load_seconds": 1.0,
                    "handler_seconds": 1.0,
                    "gpu_seconds": 1.0,
                },
            }
            cloud.calls.append((host, method, path, body))
            return answer, b"", "application/json"
        return inner(host, method, path, headers, body, **kwargs)

    return call


# ------------------------------------------------------------------------------ the cap


def test_a_reroll_round_over_what_is_left_of_the_cap_is_cut_and_never_overspends(
    engine, tmp_path, fake_session
):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.core.transport = made.core.client.transport = finishing(cloud)
    calls = []

    def next_round(outcomes):
        calls.append(1)
        return [request("1", 0, attempt=2), request("1", 1, attempt=2)] if len(calls) == 1 else []

    summary, meter, _seen = go(
        engine, made, [request("1", 0), request("1", 1)], next_round=next_round, cap=40.0
    )
    # Round 1: 2 x 10 + 5 = 25; round 2 would be 25 more (50 > 40): cut to one item (15).
    assert [len(cloud.jobs[j]["input"]["items"]) for j in sorted(cloud.jobs)] == [2, 1]
    assert meter.committed == 40.0 and summary["cap_stop"].startswith("STOPPED_AT_CAP")
    keys = [cloud.jobs[j]["input"]["items"][0]["idempotency_key"] for j in sorted(cloud.jobs)]
    assert keys[0] != keys[1]  # a re-roll is a new purchase, never the spent key


# ---------------------------------------------------------------------------- the mode


def test_the_mode_lowered_before_the_round_sends_nothing(engine, tmp_path, fake_session):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    summary, meter, _seen = go(engine, made, [request("1", 0)], guard=Guard(lowered_after=0))
    assert not cloud.posts() and meter.committed == 0 and meter.attempts == 0
    assert summary["stopped"] == "Proprietarul a coborât modul."


def test_the_mode_lowered_mid_batch_cancels_keeps_what_finished_and_buys_nothing_more(
    engine, tmp_path, fake_session
):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)

    class Stopping(Guard):
        def stop_reason(self, scene):
            if self.reads == 1:
                cloud.finish("job-1", 0)  # one item is done when the mode is lowered
            return super().stop_reason(scene)

    summary, meter, seen = go(
        engine,
        made,
        [request("1", 0), request("1", 1), request("2", 0)],
        next_round=lambda outcomes: [request("3", 0)],
        guard=Stopping(lowered_after=1),
    )
    assert any("/cancel/job-1" in c[2] for c in cloud.calls)
    assert len(cloud.posts()) == 1  # no next round
    assert sorted(o.state for o in seen) == ["CANCELLED", "CANCELLED", "COMPLETED"]
    assert meter.committed == 10.0 + 5.0  # the finished item and the round's start only
    assert summary["stopped"] == "Proprietarul a coborât modul."


# ----------------------------------------------------------------------- ambiguous submit


def test_an_uncertain_chunk_then_an_unsent_chunk_is_counted_never_refused_as_free(
    engine, tmp_path, fake_session
):
    cloud = Cloud()
    # Three clips are two jobs (2 + 1): the first /run is lost, the second never leaves.
    cloud.run_answers = [
        MediaProviderError("lost", unanswered=True),
        MediaProviderError("no network", unsent=True),
    ]
    made = adapter(engine, tmp_path, cloud, cls=RunPodVideoAdapter)
    summary, meter, seen = go(
        engine, made, [request(str(n), 0, operation="video") for n in (1, 2, 3)]
    )
    # The first job may be running on the GPU: its clips and the start stay counted.
    assert meter.committed == 2 * 10.0 + 5.0 and meter.attempts == 1
    assert summary["stopped"] == "SUBMISSION_UNCERTAIN"
    assert sorted(o.error for o in seen) == [
        "SUBMISSION_UNCERTAIN",
        "SUBMISSION_UNCERTAIN",
        "UNSENT",
    ]


# --------------------------------------------------------------------- items that fail


def test_a_corrupt_item_fails_alone_and_the_round_goes_on(engine, tmp_path, fake_session):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    state = {"done": False}

    def worker(host, method, path, headers, body=None, **kwargs):
        if "/manifests/" in path and not state["done"] and cloud.jobs:
            state["done"] = True
            bad = cloud.finish("job-1", 0)
            cloud.objects[bad["key"]] = png(variation=99)  # not what the manifest says
            cloud.finish("job-1", 1)
        return cloud(host, method, path, headers, body, **kwargs)

    made.core.transport = made.core.client.transport = worker
    summary, meter, seen = go(engine, made, [request("1", 0), request("1", 1)])
    assert sorted((o.state, o.error) for o in seen) == [
        ("COMPLETED", None),
        ("FAILED", "BAD_OUTPUT"),
    ]
    assert meter.committed == price([1, 2])  # the bad picture was made: it stays counted
    assert summary["stopped"] is None
    with Session(engine) as s:
        bad = s.scalar(select(GenerationJob).where(GenerationJob.status == "FAILED"))
        assert bad.error_code == "BAD_OUTPUT" and bad.remote_job_id == "job-1:0"


def test_a_passing_network_error_while_polling_does_not_abort_the_paid_batch(
    engine, tmp_path, fake_session
):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    cloud.status_answers["job-1"] = [
        MediaProviderError("bad gateway", http_status=502),
        {"id": "job-1", "status": "IN_PROGRESS"},
    ]
    polls = {"n": 0}

    def stopped():
        polls["n"] += 1
        if polls["n"] == 3:
            cloud.finish("job-1", 0)
        return None

    _summary, _meter, seen = go(engine, made, [request("1", 0)], stopped=stopped)
    assert [o.state for o in seen] == ["COMPLETED"]
    assert not any("/cancel/" in c[2] for c in cloud.calls)


# ------------------------------------------------------------------------ the booking


def test_the_booking_is_raised_to_what_runpod_measured_never_left_below(
    engine, tmp_path, fake_session
):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.core.transport = made.core.client.transport = timed(
        cloud, delay_ms=200_000, execution_ms=400_000
    )
    # Every item comes from its manifest; /status is read once the round is over.
    summary, meter, _seen = go(
        engine, made, [request("1", 0)], credits_for_seconds=lambda seconds: seconds * 0.1
    )
    # (200 + 400) s + 1 s idle = 601 GPU-seconds = 60.1 credits, above the 15 estimated.
    assert summary["billed_seconds"] == pytest.approx(601.0)
    assert meter.committed == pytest.approx(60.1)
    assert summary["reconciled_credits"] == pytest.approx(60.1 - 15.0)
    with Session(engine) as s:
        assert s.scalar(select(GenerationJob)).billed_seconds_value == "601.000"


def test_a_measure_below_the_estimate_never_lowers_the_booking(engine, tmp_path, fake_session):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.core.transport = made.core.client.transport = timed(
        cloud, delay_ms=1_000, execution_ms=2_000
    )
    summary, meter, _seen = go(
        engine, made, [request("1", 0)], credits_for_seconds=lambda seconds: seconds * 0.1
    )
    assert summary["billed_seconds"] == pytest.approx(4.0)
    assert meter.committed == pytest.approx(15.0) and summary["reconciled_credits"] == 0


def test_the_stages_convert_gpu_seconds_at_the_budget_rate(engine, tmp_path):
    from app.media.assembler import gpu_seconds_to_credits

    made = adapter(engine, tmp_path, Cloud())
    convert = gpu_seconds_to_credits(made, credit_usd=0.01)
    # 3600 GPU-seconds at 4.00 USD/h is 4 USD = 400 credits of 0.01 USD.
    assert convert is not None and convert(3600.0) == pytest.approx(400.0)
    assert gpu_seconds_to_credits(object(), credit_usd=0.01) is None


# ---------------------------------------------------------------- crash: collected free


def test_a_crash_mid_batch_leaves_takes_the_next_step_collects_free(engine, tmp_path, fake_session):
    from test_stills_stage import a_film

    film = a_film(engine, tmp_path)
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)

    reads = []

    def crash():
        reads.append(1)
        if len(reads) > 1:  # after the round was sent, while it runs
            raise RuntimeError("the studio stopped")
        return None

    def submitted(item):
        _record_intent(
            engine,
            str(item.remote_item_id),
            storyboard_id=film,
            scene_number=int(item.request.scene_id),
            kind="still",
            prompt_hash=f"h{item.request.candidate_index}",
            model_id="Qwen-Image-2512",
            resolution="1530:2720",
            correlation_id="c",
            credits=7.0,
        )

    first = [request("1", 0, project_id=film), request("1", 1, project_id=film)]
    with pytest.raises(RuntimeError):
        go(engine, made, first, stopped=crash, on_submitted=submitted)
    assert len(cloud.posts()) == 1
    # The worker finishes both after the crash; the restarted studio only reads.
    cloud.finish("job-1", 0)
    cloud.finish("job-1", 1)
    restarted = adapter(engine, tmp_path, cloud)
    collected = collect_submitted_takes(
        engine,
        collector_for=lambda take: restarted,
        correlation_id="c",
        storyboard_id=film,
        storage_root=tmp_path / "media",
    )
    assert len(collected) == 2 and len(cloud.posts()) == 1
    with Session(engine) as s:
        takes = s.scalars(select(SceneTake).where(SceneTake.storyboard_id == film)).all()
        assert sorted(t.status for t in takes) == ["PAID", "PAID"]
        assert {r.status for r in s.scalars(select(GenerationJob))} == {"COMPLETED"}
    again = asyncio.run(restarted.collect_task("job-1:0"))
    assert again["state"] == "SUCCEEDED" and len(cloud.posts()) == 1


# --------------------------------------------------------------------- the sheet's words


def test_a_runpod_estimate_is_never_shown_as_a_published_tariff():
    from app.media.cost_plan import DOCUMENTED, ESTIMATED, PriceRow, source_label

    row = PriceRow(
        "Qwen-Image-2512", "image", "*", "RunPod estimate", "2026-10-08", ESTIMATED, None, None, 7
    )
    label = source_label(row)
    assert "tarif publicat" not in label and "estimare" in label
    published = PriceRow("gen4", "image", "*", "https://x", "2026-10-08", DOCUMENTED, None, None, 7)
    assert source_label(published).startswith("tarif publicat")


def test_runpod_pricing_rows_are_estimates(engine, monkeypatch):
    from app.integrations.models import Integration, ProviderResource
    from app.media.cost_plan import ESTIMATED, load_price_table
    from app.providers.runpod.pricing import estimated_prices
    from app.services import utc_now
    from test_runpod_gpu_policy import runpod

    _vault, identifier = runpod(engine, monkeypatch)
    with Session(engine) as s, s.begin():
        s.get(Integration, identifier).status = "VERIFIED"
        s.add(
            ProviderResource(
                id="rp-q",
                integration_id=identifier,
                resource_type="MODEL",
                remote_id="Qwen-Image-2512",
                name="Qwen-Image-2512",
                api_metadata={"purpose": "image", "gpu_seconds_per_image": 60},
                api_available=True,
                last_seen_at=utc_now(),
                pricing={},
                capabilities={},
                metadata_version=1,
                production_status="PRODUCTION",
            )
        )
    table = estimated_prices(engine, load_price_table())
    row = table.row("Qwen-Image-2512", "*")
    assert row.provenance == ESTIMATED
    assert row.credits_per_image == pytest.approx(float(Decimal(60) * 4 / 3600) / 0.01)


# ------------------------------------------------- no /run outside a round and a GPU session


def test_a_serverless_request_outside_a_round_is_never_sent(engine, tmp_path):
    from app.providers.runpod.adapters import RunPodImageAdapter

    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud, cls=RunPodImageAdapter)
    made.bind_scene(project_id="film-1", scene_id="1", operation="image")
    with pytest.raises(MediaProviderError) as refused:
        asyncio.run(made.generate_image("a still", width=1530, height=2720))
    assert refused.value.unsent and refused.value.code == "NEEDS_GPU_ROUND"
    assert not cloud.calls  # workers.max is 0 outside a session: a /run would wait and bill later


def test_a_still_redo_on_runpod_whose_gpu_may_not_switch_on_asks_and_spends_nothing(
    engine, tmp_path
):
    # 2026-10-09: the still redo on RunPod is one GPU round (tests/test_runpod_unsent_proof.py).
    # A GPU that could not be switched on (here: no connection whose card lets agents switch it
    # on) refuses before his yes is asked or spent, nothing sent.
    from uuid import uuid4

    from app.media.assembler import SceneRedoRefused, redo_plan, redo_scene
    from app.models import ApprovalRequest
    from test_film_costing import a_film

    storyboard_id = a_film(engine, tmp_path)
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    table = stills_table()
    plan = redo_plan(engine, storyboard_id, "still", 3, table=table, stills_model=made.model)
    with pytest.raises(SceneRedoRefused) as refused:
        redo_scene(
            engine,
            storyboard_id,
            str(uuid4()),
            kind="still",
            scene_index=3,
            plan_hash=plan["plan_hash"],
            image_adapter=made,
            table=table,
            storage_root=tmp_path / "media",
        )
    assert refused.value.status == "BLOCKED_INFRA_DISABLED" and not cloud.calls
    with Session(engine) as s:
        assert s.scalar(select(ApprovalRequest)) is None
