"""RunPod Serverless rounds: one batch job per paid round, every item on its own journal row and
take, collected from the bucket manifest first. Every RunPod, bucket and GPU call is faked."""

import asyncio
import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from app.media import cost_plan
from app.media.production_policy import ModelCapability, SceneNeed, plan_scene_models
from app.providers.media_http import MediaProviderError
from app.providers.runpod import batch as batch_module
from app.providers.runpod.adapters import RunPodImageAdapter, RunPodVideoAdapter
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.jobs import GenerationJob
from app.providers.runpod.mock import png
from runpod_worker import contract
from sqlalchemy import select
from sqlalchemy.orm import Session

KEY = "fake-key"  # pragma: allowlist secret — synthetic test value
S3_SECRET = "synthetic-s3-secret"  # pragma: allowlist secret — synthetic test value


def serverless(**values):
    base = {
        "enabled": True,
        "mode": "serverless",
        "api_key": KEY,
        "stills_endpoint_id": "stills-ep",
        "motion_endpoint_id": "motion-ep",
        "s3_endpoint_url": "https://account.r2.example",
        "s3_bucket": "amn-films",
        "s3_access_key_id": "AKIDEXAMPLE",
        "s3_secret_access_key": S3_SECRET,
        "poll_interval": 0.01,
        "max_retries": 0,
    }
    return RunPodConfig(_env_file=None, **(base | values))


def request(scene="1", candidate=0, attempt=1, operation="image", **values):
    base = {
        "operation": operation,
        "project_id": "film-1",
        "scene_id": scene,
        "candidate_index": candidate,
        "attempt_number": attempt,
        "model": "Qwen-Image-2512" if operation == "image" else "LTX-2.5",
        "prompt": f"scene {scene} candidate {candidate}",
        "negative_prompt": None,
        "seed": batch_module.item_seed("film-1", scene, attempt, candidate),
        "width": 1530 if operation == "image" else 1080,
        "height": 2720 if operation == "image" else 1920,
        "duration": None if operation == "image" else 5.0,
        "fps": None if operation == "image" else 24,
        "references": (),
        "source_image": None if operation == "image" else png(),
        "price_usd": Decimal("0.0667"),
    }
    return batch_module.BatchRequest(**(base | values))


class Session_:
    """A stand-in GPU session: what the batch notes on it."""

    def __init__(self):
        self.id = str(uuid4())
        self.jobs = []
        self.renewals = 0

    def note_job(self, job, *, session=None):
        self.jobs.append(job)

    def renew(self):
        self.renewals += 1

    def check(self):
        pass


class Cloud:
    """RunPod queue + the Owner's bucket, faked at the transport boundary."""

    def __init__(self):
        self.calls = []
        self.objects = {}
        self.jobs = {}
        self.run_answers = []
        self.status_answers = {}

    def __call__(self, host, method, path, headers, body=None, **kwargs):
        self.calls.append((host, method, path, body))
        parts = urlsplit(path)
        if host == "account.r2.example":
            key = parts.path.removeprefix("/amn-films/")
            if method == "PUT":
                self.objects[key] = body
                return None, b"", "text/plain"
            if key not in self.objects:
                raise MediaProviderError("NoSuchKey", http_status=404)
            data = self.objects[key]
            if kwargs.get("expect_json", True):
                return json.loads(data), data, "application/json"
            return None, data, "image/png" if key.endswith(".png") else "video/mp4"
        assert host == "api.runpod.ai", host
        if method == "POST" and parts.path.endswith("/run"):
            answer = self.run_answers.pop(0) if self.run_answers else None
            if callable(answer):  # an answer decided when the /run arrives (a side effect)
                answer = answer()
            if isinstance(answer, Exception):
                raise answer
            job = f"job-{len(self.jobs) + 1}"
            self.jobs[job] = json.loads(body)
            return {"id": job, "status": "IN_QUEUE"}, b"", "application/json"
        if method == "GET" and "/status/" in parts.path:
            job = parts.path.rsplit("/", 1)[1]
            queue = self.status_answers.get(job) or [{"id": job, "status": "IN_PROGRESS"}]
            answer = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(answer, Exception):
                raise answer
            return answer, b"", "application/json"
        if method == "POST" and "/cancel/" in parts.path:
            job = parts.path.rsplit("/", 1)[1]
            return {"id": job, "status": "CANCELLED"}, b"", "application/json"
        raise AssertionError(f"unexpected {method} {path}")

    # The worker's side: finish item ``index`` of ``job`` into the bucket.
    def finish(self, job, index, *, content=None, manifest=True, gpu_seconds=30.0):
        body = self.jobs[job]["input"]
        item = body["items"][index]
        operation = body["operation"]
        content = content or (png(variation=index) if operation == "image" else b"\0\0\0 ftypmp42")
        ext = "png" if operation == "image" else "mp4"
        key = contract.output_key("amn/", item["idempotency_key"], ext)
        self.objects[key] = content
        result = {
            "index": index,
            "idempotency_key": item["idempotency_key"],
            "status": "COMPLETED",
            "url": "https://account.r2.example/amn-films/" + key + "?X-Amz-Signature=x",
            "key": key,
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "mime": "image/png" if operation == "image" else "video/mp4",
            "width": 1530 if operation == "image" else 1080,
            "height": 2720 if operation == "image" else 1920,
            "duration": None if operation == "image" else 5.0,
            "fps": None if operation == "image" else 24,
            "model": item["model"],
            "seed": item["seed"],
            "gpu_seconds": gpu_seconds,
            "error": None,
            "reused": False,
            "provenance_boxes": [],
        }
        if manifest:
            self.objects[contract.manifest_key("amn/", item["idempotency_key"])] = json.dumps(
                result
            ).encode()
        return result

    def posts(self):
        return [c for c in self.calls if c[1] == "POST" and c[2].endswith("/run")]


def adapter(engine, tmp_path, cloud, cls=RunPodImageAdapter, **values):
    made = cls(serverless(**values), engine, model="Qwen-Image-2512", storage_root=tmp_path)
    made.core.transport = cloud
    made.core.client.transport = cloud
    return made


# ------------------------------------------------------------------------------ pricing


def test_round_overhead_prices_cold_start_and_idle_tail_at_the_budget_rate(engine, tmp_path):
    made = adapter(engine, tmp_path, Cloud())
    assert made.supports_batch()
    # (120 s cold start + 1 s idle) x 4.00 USD/h
    assert made.round_overhead_usd() == Decimal(121) * Decimal("4.00") / 3600


def test_price_table_overhead_applies_only_to_round_priced_models():
    table = replace(
        cost_plan.load_price_table(),
        overhead_credits_per_round={"image": 13.2, "video": 13.2},
        round_models=frozenset({"Qwen-Image-2512"}),
    )
    assert table.round_overhead("image", "Qwen-Image-2512") == 14
    assert table.round_overhead("image", "seedream5_pro") == 0
    assert cost_plan.load_price_table().round_overhead("image", "Qwen-Image-2512") == 0


# ------------------------------------------------------------------------------ planner


def runpod_capability(**values):
    base = {
        "model_id": "LTX-2.5",
        "quality": 0.5,
        "seconds": {"min": 1, "max": 10},
        "ratios": ("9:16",),
        "tasks": ("image_to_video",),
        "quality_source": "estimat",
        "selected_default": True,
        "output": (1080, 1920),
    }
    return ModelCapability(**(base | values))


def runpod_table():
    table = cost_plan.load_price_table()
    return replace(
        table,
        rows=(
            *table.rows,
            cost_plan.PriceRow(
                "LTX-2.5",
                "video",
                "*",
                "estimate",
                "2026-10-08",
                "DOCUMENTED",
                credits_per_second=2.67,
            ),
            cost_plan.PriceRow(
                table.stills_model,
                "image",
                "*",
                "estimate",
                "2026-10-08",
                "DOCUMENTED",
                credits_per_image=7,
            ),
        ),
        seconds={**table.seconds, "LTX-2.5": {"min": 1, "max": 10}},
    )


def test_nine_sixteen_reaches_the_1080p_frame_and_the_selected_runpod_model_is_taken():
    plan = plan_scene_models(
        [SceneNeed(scene_index=1, seconds=5, tier="STANDARD")],
        [runpod_capability()],
        table=runpod_table(),
        resolution="1080p",
    )
    scene = plan["scenes"][0]
    assert scene["model_id"] == "LTX-2.5" and scene["status"] == "PLANNED"
    assert scene["reason_ro"].startswith("Profil RunPod selectat de Proprietar: LTX-2.5")
    assert "calitatea se verifică pe clip" in scene["reason_ro"]


def test_a_ratio_without_a_declared_output_reaching_the_frame_does_not_pass():
    plan = plan_scene_models(
        [SceneNeed(scene_index=1, seconds=5, tier="STANDARD")],
        [runpod_capability(output=(720, 1280))],
        table=runpod_table(),
        resolution="1080p",
    )
    assert plan["scenes"][0]["status"] != "PLANNED"


@pytest.mark.parametrize(
    ("left", "right", "same"),
    [("9:16", "1080:1920", True), ("720:1280", "9:16", True), ("16:9", "1080:1920", False)],
)
def test_ratio_normalisation(left, right, same):
    from app.media.production_policy import same_ratio

    assert same_ratio(left, right) is same


# ------------------------------------------------------------------------- submission


def test_one_round_is_one_job_with_every_item_and_takes_are_recorded_before_any_poll(
    engine, tmp_path
):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    session = Session_()
    order = []
    run = made.submit_batch(
        [request("1", 0), request("1", 1), request("2", 0), request("2", 1)],
        session=session,
        on_submitted=lambda item: order.append(("take", item.remote_item_id)),
    )
    assert len(cloud.posts()) == 1
    body = cloud.jobs["job-1"]
    assert body["input"]["contract"] == "amn.batch.v1"
    assert [it["index"] for it in body["input"]["items"]] == [0, 1, 2, 3]
    assert body["policy"]["executionTimeout"] == (120 + 4 * 180) * 1000
    # The queue wait, plus the unbilled cache-miss wait of the cached-model source (2026-10-09).
    assert body["policy"]["ttl"] == body["policy"]["executionTimeout"] + 900_000 + 3_600_000
    contract.validate_input(body["input"])
    assert session.jobs == ["job-1"]
    assert order == [("take", f"job-1:{n}") for n in range(4)]
    assert not [c for c in cloud.calls if "/status/" in c[2]]
    with Session(engine) as s:
        rows = s.scalars(select(GenerationJob).order_by(GenerationJob.batch_index)).all()
        assert [r.remote_job_id for r in rows] == [f"job-1:{n}" for n in range(4)]
        assert {r.batch_remote_id for r in rows} == {"job-1"}
        assert {r.gpu_session_id for r in rows} == {session.id}
        assert all(r.request_digest and r.hourly_rate == "4.00" for r in rows)
    assert run.remote_job_ids == ["job-1"]


def test_pictures_go_to_the_bucket_by_content_and_the_journal_keeps_digests_only(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    picture = png(variation=7)
    # Only a model that binds pictures receives one (the 2511 route, 2026-10-09).
    made.submit_batch(
        [
            request("1", 0, model="Qwen-Image-Edit-2511", references=(picture,)),
            request("1", 1, model="Qwen-Image-Edit-2511", references=(picture,)),
        ],
        session=Session_(),
        on_submitted=lambda item: None,
    )
    sha = hashlib.sha256(picture).hexdigest()
    puts = [c for c in cloud.calls if c[1] == "PUT"]
    assert len(puts) == 1 and f"/amn/inputs/{sha}.png" in puts[0][2]
    refs = cloud.jobs["job-1"]["input"]["items"][0]["reference_images"]
    assert refs[0]["sha256"] == sha and refs[0]["url"].startswith("https://account.r2.example/")
    with Session(engine) as s:
        for row in s.scalars(select(GenerationJob)):
            assert row.request["reference_images"] == [
                {"sha256": sha, "bytes": len(picture), "mime": "image/png"}
            ]
            assert "base64" not in json.dumps(row.request)


def test_long_rounds_are_chunked_and_posted_back_to_back_before_any_poll(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud, cls=RunPodVideoAdapter)
    # (2400 - 120) // 900 = 2 clips per chunk: 5 clips are 3 jobs.
    made.submit_batch(
        [request(str(n), 0, operation="video") for n in range(1, 6)],
        session=Session_(),
        on_submitted=lambda item: None,
    )
    assert len(cloud.posts()) == 3
    assert [len(cloud.jobs[j]["input"]["items"]) for j in ("job-1", "job-2", "job-3")] == [2, 2, 1]
    assert cloud.jobs["job-3"]["policy"]["executionTimeout"] == (120 + 900) * 1000
    assert cloud.jobs["job-1"]["policy"]["executionTimeout"] == (120 + 2 * 900) * 1000
    statuses = [n for n, c in enumerate(cloud.calls) if "/status/" in c[2]]
    assert not statuses


def test_bucket_missing_refuses_before_anything_is_sent(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud, s3_bucket=None)
    with pytest.raises(batch_module.BatchRefused) as refused:
        made.submit_batch([request()], session=Session_(), on_submitted=lambda item: None)
    assert refused.value.code == "NOT_CONFIGURED" and refused.value.unsent
    assert not cloud.calls
    with Session(engine) as s:
        assert s.scalar(select(GenerationJob)) is None


def test_proven_unsent_run_keeps_the_keys_reusable(engine, tmp_path):
    cloud = Cloud()
    cloud.run_answers = [MediaProviderError("connect", unsent=True)]
    made = adapter(engine, tmp_path, cloud)
    with pytest.raises(MediaProviderError):
        made.submit_batch([request()], session=Session_(), on_submitted=lambda item: None)
    with Session(engine) as s:
        row = s.scalar(select(GenerationJob))
        key = row.idempotency_key
        assert row.status == "FAILED" and row.error_code == "UNSENT" and row.cost_value == "0"
    made.submit_batch([request()], session=Session_(), on_submitted=lambda item: None)
    with Session(engine) as s:
        rows = s.scalars(select(GenerationJob)).all()
        assert len(rows) == 1 and rows[0].idempotency_key == key and rows[0].remote_job_id


def paused():
    return MediaProviderError(
        "api.runpod.ai refused the request (HTTP 409)",
        http_status=409,
        detail="Endpoint is paused (max_workers=0). Set max_workers > 0 to accept work.",
    )


class FakeClock:
    """The paused wait's monotonic clock: time moves only when the batch sleeps."""

    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(batch_module, "paused_clock", fake)
    monkeypatch.setattr(batch_module, "paused_sleep", fake.sleep)
    return fake


def pause_events(engine):
    from app.models import DomainEvent

    with Session(engine) as s:
        return [
            e.payload
            for e in s.scalars(
                select(DomainEvent).where(DomainEvent.event_type == batch_module.PAUSE_EVENT)
            )
        ]


def test_a_paused_endpoint_is_asked_again_until_it_takes_the_job(engine, tmp_path, clock, caplog):
    # 2026-10-09, live: the /run left 0.1 s after the switch-on PATCH and RunPod answered 409
    # «Endpoint is paused (max_workers=0)»: the setting had not reached its queue yet.
    import logging

    caplog.set_level(logging.INFO, logger="studio.runpod")
    cloud = Cloud()
    cloud.run_answers = [paused(), paused()]
    made = adapter(engine, tmp_path, cloud)
    taken = []
    session = Session_()
    made.submit_batch([request()], session=session, on_submitted=taken.append)
    assert len(cloud.posts()) == 3 and len(taken) == 1
    assert clock.slept == [1.0, 2.0]
    # The session is renewed before and after every wait, never left to go stale.
    assert session.renewals == 4
    with Session(engine) as s:
        row = s.scalar(select(GenerationJob))
        assert str(row.remote_job_id).startswith("job-1") and row.error_code is None
    # How long RunPod took is kept, in the log and in the studio's own events.
    (cleared,) = [r for r in caplog.records if r.getMessage() == "runpod_run_paused_cleared"]
    assert cleared.seconds == 3.0 and cleared.paused_answers == 2
    (event,) = pause_events(engine)
    assert event["cleared"] is True and event["seconds"] == 3.0 and event["ended"] is None


def test_a_cleared_pause_saves_the_job_before_its_event(engine, tmp_path, clock, monkeypatch):
    # Review 2026-10-09: the pause's event (a write that may wait out the 30 s busy timeout)
    # was written after RunPod accepted the job and before its id was saved on the rows and
    # the session: a «Oprește GPU acum» meanwhile could not cancel a job nothing named yet.
    from app.providers.runpod import gpu_session

    real = gpu_session._write_event
    session = Session_()
    seen = []

    def write(engine_, kind, aggregate_id, payload, correlation):
        if kind == batch_module.PAUSE_EVENT:
            with Session(engine) as s:
                seen.append((s.scalar(select(GenerationJob)).remote_job_id, list(session.jobs)))
        real(engine_, kind, aggregate_id, payload, correlation)

    monkeypatch.setattr(gpu_session, "_write_event", write)
    cloud = Cloud()
    cloud.run_answers = [paused()]
    made = adapter(engine, tmp_path, cloud)
    made.submit_batch([request()], session=session, on_submitted=lambda item: None)
    ((saved, noted),) = seen
    assert str(saved).startswith("job-1") and noted == ["job-1"]
    assert len(pause_events(engine)) == 1


def test_an_endpoint_still_paused_past_its_budget_is_refused_unsent_in_runpods_words(
    engine, tmp_path, clock
):
    cloud = Cloud()
    cloud.run_answers = [paused() for _ in range(20)]
    made = adapter(engine, tmp_path, cloud, paused_wait_seconds=60)
    with pytest.raises(batch_module.BatchRefused) as refused:
        made.submit_batch([request()], session=Session_(), on_submitted=lambda item: None)
    # 1 + 2 + 4 + 8 + 15 + 30 s: the budget is time, on the clock, not a count of answers.
    assert clock.slept == [1.0, 2.0, 4.0, 8.0, 15.0, 30.0] and len(cloud.posts()) == 7
    assert refused.value.code == "RUNPOD_PAUSED" and refused.value.unsent
    assert refused.value.http_status == 409
    assert "în pauză" in refused.value.reason_ro and "60 s" in refused.value.reason_ro
    assert "nu s-a cumpărat nimic" in refused.value.reason_ro
    assert "Endpoint is paused (max_workers=0)" in refused.value.reason_ro
    with Session(engine) as s:
        row = s.scalar(select(GenerationJob))
        assert row.status == "FAILED" and row.error_code == "HTTP_409" and row.cost_value == "0"
        answer = row.output["run_refusal"]
        assert answer["http_status"] == 409 and answer["code"] == "RUNPOD_PAUSED"
        assert answer["detail"].startswith("Endpoint is paused") and answer["at"]
    (event,) = pause_events(engine)
    assert event["cleared"] is False and event["ended"] == "RUNPOD_PAUSED"


def test_uncertain_run_is_resent_with_the_same_keys_next_round(engine, tmp_path):
    cloud = Cloud()
    cloud.run_answers = [MediaProviderError("lost", unanswered=True)]
    made = adapter(engine, tmp_path, cloud)
    taken = []
    run = made.submit_batch([request()], session=Session_(), on_submitted=taken.append)
    assert not taken  # no take without a job id
    outcomes = run.poll()
    assert [(o.state, o.error) for o in outcomes] == [("FAILED", "SUBMISSION_UNCERTAIN")]
    with Session(engine) as s:
        row = s.scalar(select(GenerationJob))
        key = row.idempotency_key
        assert row.error_code == "SUBMISSION_UNCERTAIN" and row.remote_job_id is None
    made.submit_batch([request()], session=Session_(), on_submitted=taken.append)
    second = cloud.jobs["job-1"]["input"]["items"][0]["idempotency_key"]
    assert second == key and len(taken) == 1


def test_redo_of_a_spent_key_moves_to_the_next_attempt(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    run = made.submit_batch([request()], session=Session_(), on_submitted=lambda item: None)
    cloud.finish("job-1", 0)
    assert [o.state for o in run.poll()] == ["COMPLETED"]
    made.submit_batch([request()], session=Session_(), on_submitted=lambda item: None)
    with Session(engine) as s:
        attempts = sorted(r.attempt for r in s.scalars(select(GenerationJob)))
    assert attempts == [1, 2]


# -------------------------------------------------------------------------- collection


def test_items_are_collected_from_manifests_while_the_job_runs(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    run = made.submit_batch(
        [request("1", 0), request("1", 1)], session=Session_(), on_submitted=lambda item: None
    )
    first = cloud.finish("job-1", 0, gpu_seconds=36.0)
    outcomes = run.poll()
    assert [o.state for o in outcomes] == ["COMPLETED"]
    assert outcomes[0].path.read_bytes().startswith(b"\x89PNG") and not run.done()
    with Session(engine) as s:
        row = s.scalar(select(GenerationJob).where(GenerationJob.batch_index == 0))
        assert row.status == "COMPLETED" and row.gpu_seconds == 36.0
        assert row.estimated_cost_usd == Decimal("36.0") * Decimal("4.00") / 3600
        assert "url" not in row.output and row.output["sha256"] == first["sha256"]
    cloud.finish("job-1", 1)
    assert [o.state for o in run.poll()] == ["COMPLETED"]
    assert run.done()


def test_status_output_is_read_when_no_manifest_and_the_key_is_checked(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    run = made.submit_batch([request()], session=Session_(), on_submitted=lambda item: None)
    result = cloud.finish("job-1", 0, manifest=False)
    cloud.status_answers["job-1"] = [
        {
            "id": "job-1",
            "status": "COMPLETED",
            "delayTime": 90_000,
            "executionTime": 40_000,
            "output": {
                "contract": "amn.batch.v1",
                "batch_key": cloud.jobs["job-1"]["input"]["batch_key"],
                "items": [result],
                "model_load_seconds": 80.0,
                "handler_seconds": 40.0,
                "gpu_seconds": 30.0,
            },
        }
    ]
    assert [o.state for o in run.poll()] == ["COMPLETED"]
    assert run.billed_seconds_estimate() == pytest.approx(131.0)
    with Session(engine) as s:
        assert s.scalar(select(GenerationJob)).billed_seconds_value == "131.000"


def test_expired_status_without_manifest_is_expired_undelivered(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    run = made.submit_batch([request()], session=Session_(), on_submitted=lambda item: None)
    cloud.status_answers["job-1"] = [MediaProviderError("gone", http_status=404)]
    outcome = run.poll()[0]
    assert outcome.state == "FAILED" and outcome.error == "EXPIRED_UNDELIVERED"


def test_one_item_failure_is_that_item_only(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    run = made.submit_batch(
        [request("1", 0), request("1", 1)], session=Session_(), on_submitted=lambda item: None
    )
    good = cloud.finish("job-1", 0, manifest=False)
    bad = {
        "index": 1,
        "idempotency_key": cloud.jobs["job-1"]["input"]["items"][1]["idempotency_key"],
        "status": "FAILED",
        "url": None,
        "error": "COMFY_NODE_ERROR",
        "reused": False,
        "provenance_boxes": [],
        "gpu_seconds": 4.0,
    }
    cloud.status_answers["job-1"] = [
        {
            "id": "job-1",
            "status": "COMPLETED",
            "delayTime": 1000,
            "executionTime": 50_000,
            "output": {
                "contract": "amn.batch.v1",
                "batch_key": cloud.jobs["job-1"]["input"]["batch_key"],
                "items": [good, bad],
                "model_load_seconds": 1.0,
                "handler_seconds": 50.0,
                "gpu_seconds": 34.0,
            },
        }
    ]
    states = sorted((o.state, o.error) for o in run.poll())
    assert states == [("COMPLETED", None), ("FAILED", "COMFY_NODE_ERROR")]


def test_a_checksum_mismatch_is_never_taken(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    run = made.submit_batch([request()], session=Session_(), on_submitted=lambda item: None)
    result = cloud.finish("job-1", 0)
    cloud.objects[result["key"]] = png(variation=99)
    # Never taken: the item fails alone (BAD_OUTPUT), its picture is not kept, and the rest of
    # the paid batch goes on (tests/test_runpod_money_adversary.py).
    (outcome,) = run.poll()
    assert outcome.state == "FAILED" and outcome.error == "BAD_OUTPUT" and outcome.path is None
    with Session(engine) as s:
        row = s.scalar(select(GenerationJob))
        assert row.status == "FAILED" and row.asset_path is None


def test_cancel_keeps_finished_items_and_the_rest_is_not_bought(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    run = made.submit_batch(
        [request("1", 0), request("1", 1), request("2", 0)],
        session=Session_(),
        on_submitted=lambda item: None,
    )
    cloud.finish("job-1", 0)
    run.cancel("Proprietarul a oprit GPU-ul")
    assert any("/cancel/job-1" in c[2] for c in cloud.calls)
    states = sorted(o.state for o in run.poll())
    assert states == ["CANCELLED", "CANCELLED", "COMPLETED"]
    assert run.done()
    with Session(engine) as s:
        cancelled = s.scalars(
            select(GenerationJob).where(GenerationJob.status == "CANCELLED")
        ).all()
        assert len(cancelled) == 2 and all(r.cost_value == "0" for r in cancelled)


def test_watchdog_collects_a_batch_item_after_a_restart(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.submit_batch([request()], session=Session_(), on_submitted=lambda item: None)
    cloud.finish("job-1", 0)
    restarted = adapter(engine, tmp_path, cloud)
    collected = asyncio.run(restarted.collect_task("job-1:0"))
    assert collected["state"] == "SUCCEEDED" and collected["outputs"][0][1] == "image/png"


def test_mock_rounds_need_no_bucket_and_cost_nothing(engine, tmp_path):
    made = RunPodImageAdapter(
        RunPodConfig(_env_file=None, enabled=True, mock=True), engine, storage_root=tmp_path
    )
    assert made.supports_batch() and made.round_overhead_usd() == 0
    run = made.submit_batch(
        [request("1", 0), request("1", 1)], session=Session_(), on_submitted=lambda item: None
    )
    outcomes = []
    while not run.done():
        outcomes += run.poll()
    assert [o.state for o in outcomes] == ["COMPLETED", "COMPLETED"]
    assert all(Path(o.path).is_file() for o in outcomes)


# ------------------------------------------------------------------------------- rounds


class Meter:
    def __init__(self):
        self.committed = 0.0
        self.attempts = 0


@pytest.fixture
def fake_session(monkeypatch):
    """The GPU session switched on/off around the rounds, recorded (CONTROL's tests cover it)."""
    from contextlib import contextmanager

    from app.media import gpu_batch

    opened = []

    @contextmanager
    def fake(engine, adapter, *, purpose, permit):
        session = Session_()
        session.renewals = 0
        session.forced = False

        def renew():
            session.renewals += 1
            if session.forced:
                from app.providers.runpod.gpu_session import GpuForcedOff

                raise GpuForcedOff()

        session.renew = renew
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


def permit():
    from app.providers.runpod.gpu_session import StepPermit

    return StepPermit(
        action="media.stills_purchase",
        step="stills",
        storyboard_id="film-1",
        plan_hash="h",
        requester="video_editor",
        approval_id=None,
        owner_press=True,
        correlation_id=str(uuid4()),
        integration_id=None,
    )


def price(requests):
    return 10.0 * len(requests) + 5.0  # 10 credits an item, 5 a round


def rounds(
    engine,
    made,
    first,
    *,
    next_round=None,
    cap=1000.0,
    stopped=lambda: None,
    meter=None,
    guard=None,
    **kw,
):
    from app.media.gpu_batch import run_rounds

    meter = meter if meter is not None else Meter()
    seen = []
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
        stopped=stopped,
        on_submitted=lambda item: None,
        on_outcome=seen.append,
        meter=meter,
        sleep=lambda s: None,
        **kw,
    )
    return summary, meter, seen


class finishing_video:  # noqa: N801 - a transport, used like the function below
    """The cloud's worker finishing every clip of a job on its first manifest read."""

    def __init__(self, inner):
        self.inner = inner

    def __call__(self, host, method, path, headers, body=None, **kwargs):
        cloud = self.inner
        if host == "account.r2.example" and method == "GET" and "/manifests/" in path:
            for job, sent in list(cloud.jobs.items()):
                for n, item in enumerate(sent["input"]["items"]):
                    key = contract.manifest_key("amn/", item["idempotency_key"])
                    if item["idempotency_key"] in path and key not in cloud.objects:
                        cloud.finish(job, n, content=VIDEO)
        return cloud(host, method, path, headers, body, **kwargs)


def _video():
    from app.providers.runpod.mock import video

    try:
        return video(5, 24)
    except Exception:  # noqa: BLE001 - no FFmpeg: a minimal MP4 header is enough here
        return b"\0\0\0 ftypisom" + b"\0" * 64


VIDEO = _video()


def finishing(cloud):
    """A cloud whose worker finishes every item of a job on its first /status read."""
    original = cloud.__call__

    def call(host, method, path, headers, body=None, **kwargs):
        if host == "account.r2.example" and method == "GET" and "/manifests/" in path:
            for job, sent in list(cloud.jobs.items()):
                for n, item in enumerate(sent["input"]["items"]):
                    if item["idempotency_key"] in path and not cloud.objects.get(
                        contract.manifest_key("amn/", item["idempotency_key"])
                    ):
                        cloud.finish(job, n)
        return original(host, method, path, headers, body, **kwargs)

    return call


def test_rounds_one_session_one_job_per_round_and_qc_failures_form_the_next(
    engine, tmp_path, fake_session
):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.core.transport = made.core.client.transport = finishing(cloud)
    calls = []

    def next_round(outcomes):
        calls.append(len(outcomes))
        return [request("1", 0, attempt=2)] if len(calls) == 1 else []

    summary, meter, seen = rounds(
        engine, made, [request("1", 0), request("1", 1)], next_round=next_round
    )
    assert summary["rounds"] == 2 and summary["items_sent"] == 3
    assert len(cloud.posts()) == 2 and len(fake_session) == 1 and fake_session[0]["closed"]
    assert meter.committed == price([1, 2]) + price([1]) == 40.0
    assert [o.state for o in seen] == ["COMPLETED"] * 3


def test_a_round_is_cut_to_the_cap_in_scene_order_and_an_empty_one_sends_nothing(
    engine, tmp_path, fake_session
):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.core.transport = made.core.client.transport = finishing(cloud)
    summary, meter, _seen = rounds(
        engine, made, [request("2", 0), request("1", 0), request("1", 1)], cap=26.0
    )
    sent = [it["scene_id"] for it in cloud.jobs["job-1"]["input"]["items"]]
    assert sent == ["1", "1"] and summary["cap_stop"].startswith("STOPPED_AT_CAP")
    nothing = Cloud()
    made = adapter(engine, tmp_path, nothing)
    summary, meter, _seen = rounds(engine, made, [request("3", 0)], cap=14.0)
    assert summary["stopped"].startswith("STOPPED_AT_CAP") and not nothing.posts()
    assert meter.committed == 0


def test_a_cut_round_keeps_every_scenes_first_candidates_before_any_reroll():
    # 2026-10-09: scene 1's re-rolls took every round and scenes 2-5 never had a first still.
    # A round cut at the cap drops re-rolls (a later attempt) before any scene's first pair.
    from app.media.gpu_batch import fit_round

    mixed = [request("1", 0, attempt=2), request("1", 1, attempt=2)]
    mixed += [request("3", 0), request("3", 1), request("2", 0, attempt=3)]
    kept = fit_round(mixed, price, 26.0)  # room for two items and the round's GPU start
    assert [(r.scene_id, r.attempt_number) for r in kept] == [("3", 1), ("3", 1)]
    every = fit_round(mixed, price, 1000.0)
    assert [(r.scene_id, r.candidate_index, r.attempt_number) for r in every] == [
        ("3", 0, 1),
        ("3", 1, 1),
        ("1", 0, 2),
        ("1", 1, 2),
        ("2", 0, 3),
    ]


def test_a_scene_a_cut_left_out_goes_before_the_rerolls_when_room_comes_back(
    engine, tmp_path, fake_session
):
    cloud = Cloud()
    # One item per job (a 300 s execution cap): scene 2's /run never leaves the studio.
    cloud.run_answers = [None, MediaProviderError("no network", unsent=True)]
    made = adapter(engine, tmp_path, cloud, execution_timeout_cap_seconds=300)
    made.core.transport = made.core.client.transport = finishing(cloud)
    asked = []

    def next_round(outcomes):
        asked.append(sorted(o.item.request.scene_id for o in outcomes))
        return [request("1", 0, attempt=2)] if len(asked) == 1 else []  # scene 1's re-roll

    summary, meter, _seen = rounds(
        engine,
        made,
        [request(str(n), 0) for n in (1, 2, 3, 4)],
        next_round=next_round,
        cap=40.0,
    )
    # Round 1 (4 x 10 + 5 = 45) is cut to scenes 1-3 (35); scene 2 was never sent and its 10
    # credits come back, so 15 are left. Round 2 is scene 4 (left out whole, its first still)
    # and scene 1's re-roll (25): cut to scene 4 (15), which is bought; the re-roll is not.
    sent = [
        (it["scene_id"], job)
        for job in sorted(cloud.jobs)
        for it in cloud.jobs[job]["input"]["items"]
    ]
    assert [scene for scene, _job in sent] == ["1", "3", "4"]
    assert sent[-1][1] not in {job for scene, job in sent[:-1]}  # scene 4 in a round of its own
    assert summary["rounds"] == 2 and asked == [["1", "2", "3"], ["4"]]
    assert summary["cap_stop"].startswith("STOPPED_AT_CAP")
    assert meter.committed == 40.0


def test_a_stop_mid_round_cancels_and_gives_back_what_was_not_made(engine, tmp_path, fake_session):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    reads = []

    def stopped():
        reads.append(1)
        return "Proprietarul a oprit autonomia." if len(reads) > 1 else None

    summary, meter, seen = rounds(engine, made, [request("1", 0), request("1", 1)], stopped=stopped)
    assert summary["stopped"] == "Proprietarul a oprit autonomia."
    assert any("/cancel/job-1" in c[2] for c in cloud.calls)
    assert sorted(o.state for o in seen) == ["CANCELLED", "CANCELLED"]
    assert meter.committed == 5.0  # the round's start-up stays counted, the items do not


def test_owner_gpu_off_mid_round_is_a_forced_off(engine, tmp_path, fake_session):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)

    def stopped():
        if fake_session:
            fake_session[-1]["session"].forced = True
        return None

    summary, _meter, seen = rounds(engine, made, [request("1", 0)], stopped=stopped)
    assert summary["forced_off"] and "GPU-ul a fost oprit" in summary["stopped"]
    assert [o.state for o in seen] == ["CANCELLED"]


def test_an_uncertain_round_stops_the_step(engine, tmp_path, fake_session):
    cloud = Cloud()
    cloud.run_answers = [MediaProviderError("lost", unanswered=True)]
    made = adapter(engine, tmp_path, cloud)
    summary, meter, seen = rounds(
        engine, made, [request("1", 0)], next_round=lambda outcomes: [request("2", 0)]
    )
    assert summary["stopped"] == "SUBMISSION_UNCERTAIN" and len(cloud.posts()) == 1
    assert meter.committed == 15.0  # possibly served: counted
    assert [o.error for o in seen] == ["SUBMISSION_UNCERTAIN"]


def test_a_failed_run_logs_runpods_answer(engine, tmp_path, fake_session, caplog):
    # 2026-10-09: the first live /run failed in 0.1 s and the studio kept no reason; the take
    # only said «refused, reason unknown». RunPod's status and sanitised words are logged now.
    import logging

    caplog.set_level(logging.INFO, logger="studio.runpod")
    cloud = Cloud()
    cloud.run_answers = [
        MediaProviderError(
            "api.runpod.ai refused the request (HTTP 503)",
            http_status=503,
            unanswered=True,
            detail="endpoint is updating",
        )
    ]
    made = adapter(engine, tmp_path, cloud)
    rounds(engine, made, [request("1", 0)])
    (logged,) = [r for r in caplog.records if r.getMessage() == "runpod_run_failed"]
    assert logged.http_status == 503 and logged.unanswered is True
    assert logged.detail == "endpoint is updating" and logged.items == 1


def test_a_refused_first_round_spends_nothing(engine, tmp_path, fake_session):
    made = adapter(engine, tmp_path, Cloud(), s3_bucket=None)
    with pytest.raises(batch_module.BatchRefused):
        rounds(engine, made, [request("1", 0)])
    # The meter is given back before the refusal travels up.


# ------------------------------------------------- a refusal that bought nothing books nothing


def refused_round(engine, made, first, **kw):
    """`rounds` that must refuse: the refusal and the meter it left."""
    meter = Meter()
    with pytest.raises(batch_module.BatchRefused) as refused:
        rounds(engine, made, first, meter=meter, **kw)
    return refused.value, meter


def only_row(engine):
    with Session(engine) as s:
        (row,) = s.scalars(select(GenerationJob)).all()
        s.expunge(row)
        return row


@pytest.mark.parametrize(
    ("error", "proven"),
    [
        (MediaProviderError("no route", unsent=True), True),
        (paused(), True),
        (
            MediaProviderError(
                "api.runpod.ai refused the request (HTTP 409)",
                http_status=409,
                detail="Endpoint is paused (max_workers=0).",
                unanswered=True,
            ),
            False,
        ),
        (MediaProviderError("conflict", http_status=409, detail="job already exists"), False),
        (MediaProviderError("slow down", http_status=429), True),
        (MediaProviderError("bad", http_status=422), True),
        (MediaProviderError("gone", http_status=404), True),
        (MediaProviderError("updating", http_status=503), False),
        (MediaProviderError("lost", unanswered=True), False),
        (batch_module.RunPodProtocolError("RunPod did not return a valid job id"), False),
        (ValueError("not a vendor answer"), False),
    ],
)
def test_one_list_says_what_refused_and_queued_nothing_means(error, proven):
    assert batch_module.refused_unqueued(error) is proven


def test_a_paused_endpoint_past_its_wait_books_nothing(engine, tmp_path, fake_session, clock):
    # 2026-10-09 17:24 UTC: the motion /run stayed paused past the wait; the raw 409 went up,
    # the meter kept the round, and the sheet wrote the Owner that the step had paid.
    cloud = Cloud()
    cloud.run_answers = [paused() for _ in range(20)]
    made = adapter(engine, tmp_path, cloud, paused_wait_seconds=30)
    refused, meter = refused_round(engine, made, [request("1", 0)])
    assert refused.code == "RUNPOD_PAUSED" and refused.unsent
    assert meter.committed == 0 and meter.attempts == 0
    assert fake_session[0]["closed"] and fake_session[0]["session"].renewals == 10


def test_the_gpu_switched_off_during_the_paused_wait_books_nothing(
    engine, tmp_path, fake_session, clock
):
    cloud = Cloud()

    def paused_then_off():
        fake_session[-1]["session"].forced = True  # his «Oprește GPU acum» meanwhile
        return paused()

    cloud.run_answers = [paused_then_off, *[paused() for _ in range(10)]]
    made = adapter(engine, tmp_path, cloud)
    refused, meter = refused_round(engine, made, [request("1", 0)])
    assert refused.code == "GPU_FORCED_OFF" and refused.unsent
    assert "GPU-ul a fost oprit" in refused.reason_ro and "în pauză" in refused.reason_ro
    assert meter.committed == 0 and meter.attempts == 0
    assert len(cloud.posts()) == 1 and clock.slept == []  # no wait and no /run after it
    row = only_row(engine)
    assert row.error_code == "HTTP_409" and row.output["run_refusal"]["code"] == "GPU_FORCED_OFF"


def test_a_stop_during_the_paused_wait_sends_no_further_run(engine, tmp_path, fake_session, clock):
    cloud = Cloud()
    pressed = []

    def paused_then_stop():
        pressed.append(1)  # STOP AUTONOMIE pressed while RunPod still answers «paused»
        return paused()

    cloud.run_answers = [paused_then_stop, *[paused() for _ in range(10)]]
    made = adapter(engine, tmp_path, cloud)
    refused, meter = refused_round(
        engine,
        made,
        [request("1", 0)],
        stopped=lambda: "Proprietarul a oprit autonomia." if pressed else None,
    )
    assert refused.code == "STOPPED" and "Proprietarul a oprit autonomia." in refused.reason_ro
    assert meter.committed == 0 and meter.attempts == 0
    assert len(cloud.posts()) == 1 and clock.slept == []


def test_his_mode_lowered_during_the_paused_wait_is_his_decision_not_a_fault(
    engine, tmp_path, fake_session, clock
):
    class Guard:
        stopped = None

        def stop_reason(self, scene):
            if pressed:
                self.stopped = {"status": "BLOCKED_MODE", "reason_ro": "Modul s-a schimbat."}
                return "Modul s-a schimbat."
            return None

    cloud = Cloud()
    pressed = []
    cloud.run_answers = [lambda: (pressed.append(1), paused())[1]]
    made = adapter(engine, tmp_path, cloud)
    refused, meter = refused_round(engine, made, [request("1", 0)], guard=Guard())
    assert refused.code == "BLOCKED_MODE" and refused.unsent
    assert meter.committed == 0 and len(cloud.posts()) == 1


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("NEEDS_APPROVAL", "STOPPED"),
        ("BLOCKED_SAFE_MODE", "STOPPED"),
        ("BLOCKED_NO_BUDGET", "BLOCKED_NO_BUDGET"),
    ],
)
def test_a_question_the_guard_meets_during_the_paused_wait_is_a_stop_never_an_unasked_question(
    engine, tmp_path, fake_session, clock, status, code
):
    # Review 2026-10-09: the guard of an unasked step reads the kernel with ask_owner=False,
    # so a NEEDS_APPROVAL it records has no question behind it. Refused NEEDS_APPROVAL, the
    # day wrote him «așteaptă răspunsul tău» and his Decisions window held nothing to answer.
    # Only a stop the day reads as his own decision keeps its status.
    class Guard:
        stopped = None

        def stop_reason(self, scene):
            if pressed:
                self.stopped = {"status": status, "reason_ro": "Politica s-a schimbat."}
                return "Politica s-a schimbat."
            return None

    cloud = Cloud()
    pressed = []
    cloud.run_answers = [lambda: (pressed.append(1), paused())[1]]
    made = adapter(engine, tmp_path, cloud)
    refused, meter = refused_round(engine, made, [request("1", 0)], guard=Guard())
    assert refused.code == code and refused.unsent
    assert getattr(refused, "approval_id", None) is None
    assert meter.committed == 0 and meter.attempts == 0 and len(cloud.posts()) == 1


def test_the_stops_kept_as_his_decision_are_the_ones_the_day_waits_on():
    from app.media.gpu_batch import HIS_DECISION_STOPS
    from app.runbook.stages import OWNER_DECIDES

    assert HIS_DECISION_STOPS <= OWNER_DECIDES
    assert "NEEDS_APPROVAL" not in HIS_DECISION_STOPS


@pytest.mark.parametrize("where", ["renew", "stop"])
def test_a_locked_database_during_the_paused_wait_books_nothing(
    engine, tmp_path, fake_session, clock, where
):
    # Review 2026-10-09: the paused wait renews the session and reads the step's stop (both
    # write under the lock) while the round is on the meter. A «database is locked» (REL-01,
    # busy_timeout 30 s) went up raw, so the sheet booked a round RunPod never queued and
    # wrote him «s-a oprit după ce a plătit»: the 17:24 UTC false booking by another road.
    from sqlalchemy.exc import OperationalError

    locked = OperationalError("UPDATE gpu_sessions", {}, Exception("database is locked"))
    pressed = []

    def paused_then_locked():
        pressed.append(1)
        if where == "renew":

            def renew():
                raise locked

            fake_session[-1]["session"].renew = renew
        return paused()

    def stopped():
        if where == "stop" and pressed:
            raise locked
        return None

    cloud = Cloud()
    cloud.run_answers = [paused_then_locked, *[paused() for _ in range(10)]]
    made = adapter(engine, tmp_path, cloud)
    refused, meter = refused_round(engine, made, [request("1", 0)], stopped=stopped)
    assert refused.code == "WAIT_UNREADABLE" and refused.unsent
    assert "nu s-a cumpărat nimic" in refused.reason_ro
    assert meter.committed == 0 and meter.attempts == 0
    assert len(cloud.posts()) == 1 and clock.slept == []  # no wait and no /run after it
    row = only_row(engine)
    assert row.status == "FAILED" and row.error_code == "HTTP_409" and row.cost_value == "0"
    assert row.output["run_refusal"]["code"] == "WAIT_UNREADABLE"


def test_a_session_unreadable_before_the_first_chunk_sends_nothing_and_books_nothing(
    engine, tmp_path, fake_session, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    def locked(self):
        raise OperationalError("SELECT gpu_sessions", {}, Exception("database is locked"))

    monkeypatch.setattr(Session_, "check", locked)
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    refused, meter = refused_round(engine, made, [request("1", 0)])
    assert refused.code == "WAIT_UNREADABLE" and "nu s-a cumpărat nimic" in refused.reason_ro
    assert meter.committed == 0 and meter.attempts == 0 and not cloud.posts()
    row = only_row(engine)
    assert row.status == "FAILED" and row.error_code == "UNSENT" and row.cost_value == "0"


class LockedJournal:
    """`JobStore.update` answering «database is locked» once ``on()`` was called: a writer held
    past the busy timeout (REL-01) that outlives the renewal reaches the refusal's own journal
    writes too (review 2026-10-10)."""

    def __init__(self, monkeypatch):
        from app.providers.runpod import jobs
        from sqlalchemy.exc import OperationalError

        self.error = OperationalError("UPDATE generation_jobs", {}, Exception("database is locked"))
        self.locked = False
        self.refused_writes = 0
        real = jobs.JobStore.update

        def update(store, identifier, **values):
            if self.locked:
                self.refused_writes += 1
                raise self.error
            return real(store, identifier, **values)

        monkeypatch.setattr(jobs.JobStore, "update", update)

    def on(self):
        self.locked = True
        return self.error


def test_a_lock_that_outlives_the_renewal_still_refuses_unsent_and_books_nothing(
    engine, tmp_path, fake_session, clock, monkeypatch
):
    # Review 2026-10-10: the renewal failed «database is locked», so the paused /run was refused
    # WAIT_UNREADABLE; but the refusal's own journal writes met the same lock, the raw
    # OperationalError left the round on the meter, and the sheet booked a round RunPod never
    # queued with the «a plătit» letter: the 17:24 UTC false booking by yet another road.
    journal = LockedJournal(monkeypatch)

    def paused_then_locked():
        def renew():
            raise journal.on()

        fake_session[-1]["session"].renew = renew
        return paused()

    cloud = Cloud()
    cloud.run_answers = [paused_then_locked]
    made = adapter(engine, tmp_path, cloud)
    refused, meter = refused_round(engine, made, [request("1", 0)])
    assert refused.code == "WAIT_UNREADABLE" and refused.unsent
    assert "nu s-a cumpărat nimic" in refused.reason_ro
    assert meter.committed == 0 and meter.attempts == 0
    assert len(cloud.posts()) == 1 and journal.refused_writes >= 1
    # The row could not be written FAILED: it stays reserved and was never answered with a job,
    # so the next step sends it again under the SAME key (`reserve_item`: RESEND).
    row = only_row(engine)
    assert row.status == "STARTING" and row.remote_job_id is None
    journal.locked = False
    made.submit_batch([request("1", 0)], session=Session_(), on_submitted=lambda item: None)
    again = only_row(engine)
    assert again.idempotency_key == row.idempotency_key and again.remote_job_id
    assert len(cloud.posts()) == 2


@pytest.mark.parametrize(
    ("road", "code", "posts"),
    [
        ("refused_429", "RUNPOD_HTTP_429", 1),
        ("session_unread", "WAIT_UNREADABLE", 0),
        ("upload_failed", "INPUT_UPLOAD_FAILED", 0),
        ("reservation_locked", "JOURNAL_UNWRITABLE", 0),
    ],
)
def test_a_refusal_whose_journal_write_is_locked_still_books_nothing(
    engine, tmp_path, fake_session, monkeypatch, road, code, posts
):
    # Review 2026-10-10: every road that proves nothing was queued writes the journal before it
    # refuses; a «database is locked» there went up raw (not a MediaProviderError), so the step
    # kept the round on its meter and the sheet booked it as an estimated purchase.
    journal = LockedJournal(monkeypatch)
    cloud = Cloud()
    first = [request("1", 0)]
    made = adapter(engine, tmp_path, cloud)
    if road == "refused_429":

        def rate_limited():
            journal.on()
            return MediaProviderError(
                "api.runpod.ai refused the request (HTTP 429)",
                http_status=429,
                detail="Too many requests",
            )

        cloud.run_answers = [rate_limited]
    elif road == "session_unread":

        def unreadable(self):
            raise journal.on()

        monkeypatch.setattr(Session_, "check", unreadable)
    elif road == "upload_failed":

        async def refused_put(*args, **kwargs):
            journal.on()
            raise MediaProviderError("bucket refused the upload", http_status=403)

        monkeypatch.setattr(batch_module.s3, "put_bytes", refused_put)
        made = adapter(engine, tmp_path, cloud, cls=RunPodVideoAdapter)
        first = [request("1", 0, operation="video")]
    else:

        def locked(session):
            raise journal.on()

        monkeypatch.setattr(batch_module, "lock_for_write", locked)
    refused, meter = refused_round(engine, made, first)
    assert refused.code == code and refused.unsent
    assert "nimic" in refused.reason_ro
    assert meter.committed == 0 and meter.attempts == 0
    assert len(cloud.posts()) == posts


def test_a_409_in_other_words_is_uncertain_and_the_close_proves_it_for_free(
    engine, tmp_path, proving_session
):
    cloud = Cloud()
    cloud.run_answers = [
        MediaProviderError(
            "api.runpod.ai refused the request (HTTP 409)",
            http_status=409,
            detail="Conflict: request already in progress",
        )
    ]
    made = adapter(engine, tmp_path, cloud)
    summary, meter, seen = rounds(engine, made, [request("1", 0)])
    assert len(cloud.posts()) == 1  # not the paused words: never sent again
    assert [o.error for o in seen] == ["SUBMISSION_UNCERTAIN"]
    # The GPU-off read the queue empty and the bucket holds no claim: proven, given back.
    assert summary["unsent_proof"]["proven"] is True
    assert meter.committed == 0
    row = only_row(engine)
    assert row.error_code == "UNSENT" and row.output["not_queued"]["by"] == "proof"
    assert row.output["run_refusal"]["http_status"] == 409
    assert row.output["run_refusal"]["code"] == "SUBMISSION_UNCERTAIN"


@pytest.mark.parametrize(
    ("status", "words"),
    [(429, "prea multe cereri"), (422, "nu acceptă conținutul"), (401, "cheia studioului")],
)
def test_a_refused_run_books_nothing_and_says_why(engine, tmp_path, fake_session, status, words):
    cloud = Cloud()
    cloud.run_answers = [
        MediaProviderError(
            f"api.runpod.ai refused the request (HTTP {status})",
            http_status=status,
            detail="RunPod's own reason",
        )
    ]
    made = adapter(engine, tmp_path, cloud)
    refused, meter = refused_round(engine, made, [request("1", 0)])
    assert refused.code == f"RUNPOD_HTTP_{status}" and refused.unsent
    assert words in refused.reason_ro and "«RunPod's own reason»" in refused.reason_ro
    assert meter.committed == 0 and meter.attempts == 0
    row = only_row(engine)
    assert row.status == "FAILED" and row.error_code == f"HTTP_{status}"
    assert row.cost_value == "0" and row.output["run_refusal"]["code"] == f"RUNPOD_HTTP_{status}"
    # Never served: the same key goes out again on the next press, a free reuse at worst.
    key = row.idempotency_key
    made.submit_batch([request("1", 0)], session=Session_(), on_submitted=lambda item: None)
    assert only_row(engine).idempotency_key == key and len(cloud.posts()) == 2


def test_a_later_round_refused_gives_back_that_round_only(engine, tmp_path, fake_session, clock):
    cloud = Cloud()
    cloud.run_answers = [None, *[paused() for _ in range(5)]]
    made = adapter(engine, tmp_path, cloud, paused_wait_seconds=0)
    made.core.transport = made.core.client.transport = finishing(cloud)
    summary, meter, _seen = rounds(
        engine,
        made,
        [request("1", 0)],
        next_round=lambda outcomes: [request("1", 0, attempt=2)] if len(outcomes) == 1 else [],
    )
    assert summary["rounds"] == 1 and len(cloud.posts()) == 2
    assert summary["stopped"].startswith("RunPod a răspuns că endpointul este în pauză")
    assert meter.committed == price([1]) == 15.0
    # Round one was bought: the stop never tells him the step bought nothing (review
    # 2026-10-09: «nu s-a cumpărat nimic» sat next to the 15 credits booked for the stair).
    assert "nu s-a cumpărat nimic" not in summary["stopped"]
    assert "ce s-a cumpărat înainte rămâne" in summary["stopped"]


def test_a_later_chunk_refused_stops_the_round_and_the_step(engine, tmp_path, fake_session, clock):
    cloud = Cloud()
    cloud.run_answers = [None, *[paused() for _ in range(5)]]
    # One item per job (a 300 s execution cap): three chunks, the second one refused.
    made = adapter(
        engine, tmp_path, cloud, execution_timeout_cap_seconds=300, paused_wait_seconds=0
    )
    made.core.transport = made.core.client.transport = finishing(cloud)
    asked = []
    summary, meter, seen = rounds(
        engine,
        made,
        [request(str(n), 0) for n in (1, 2, 3)],
        next_round=lambda outcomes: asked.append(outcomes) or [],
    )
    assert len(cloud.posts()) == 2  # the third chunk never leaves
    assert sorted((o.state, o.error) for o in seen) == [
        ("COMPLETED", None),
        ("FAILED", "UNSENT"),
        ("FAILED", "UNSENT"),
    ]
    assert asked == [] and summary["stopped"].startswith("RunPod a răspuns")
    assert "nu s-a cumpărat nimic" not in summary["stopped"]
    assert "ce s-a cumpărat înainte rămâne" in summary["stopped"]
    # 3 x 10 + 5 for the round, the two items never made (2 x 10) given back.
    assert meter.committed == 15.0


def bought_on_runway_first():
    """The step's meter as a motion step leaves its own loop: one scene bought on a per-second
    model (Runway, 340 credits) before the scenes it defers to RunPod."""
    meter = Meter()
    meter.committed, meter.attempts = 340.0, 1
    return meter


def test_a_first_round_refused_after_the_step_bought_elsewhere_ends_the_step_booked(
    engine, tmp_path, fake_session, clock
):
    # Review 2026-10-10: raised unsent, the stage refused and the sheet let the hold go,
    # dropping the 340 Runway credits the step had really spent from the books.
    cloud = Cloud()
    cloud.run_answers = [paused() for _ in range(20)]
    made = adapter(engine, tmp_path, cloud, paused_wait_seconds=30)
    meter = bought_on_runway_first()
    summary, meter, seen = rounds(engine, made, [request("1", 0)], meter=meter)
    assert summary["rounds"] == 0 and seen == []
    assert meter.committed == 340.0 and meter.attempts == 1  # RunPod's round given back
    assert "nu s-a cumpărat nimic" not in summary["stopped"]
    assert summary["stopped"].startswith("RunPod a răspuns că endpointul este în pauză")
    assert "ce s-a cumpărat înainte rămâne" in summary["stopped"]
    assert summary["refusal"]["code"] == "RUNPOD_PAUSED"
    assert summary["refusal"]["http_status"] == 409
    assert fake_session[0]["closed"]


def test_a_gpu_that_would_not_start_after_the_step_bought_elsewhere_ends_the_step_booked(
    engine, tmp_path, monkeypatch
):
    from contextlib import contextmanager

    from app.media import gpu_batch
    from app.providers.runpod.gpu_session import GpuSessionRefused

    @contextmanager
    def busy(engine, adapter, *, purpose, permit):
        raise GpuSessionRefused("GPU_BUSY", "GPU-ul RunPod este deja folosit de alt pas.")
        yield  # pragma: no cover - never reached

    monkeypatch.setattr(gpu_batch, "gpu_session", busy)
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    summary, meter, _seen = rounds(engine, made, [request("1", 0)], meter=bought_on_runway_first())
    assert cloud.posts() == [] and summary["rounds"] == 0
    assert meter.committed == 340.0 and meter.attempts == 1
    assert "nu s-a cumpărat nimic" not in summary["stopped"]
    assert "GPU_BUSY" in summary["stopped"]
    assert "ce s-a cumpărat înainte rămâne" in summary["stopped"]
    assert summary["refusal"]["code"] == "GPU_BUSY"
    # Nothing bought before: still a refusal, so the stage books nothing (as before).
    with pytest.raises(GpuSessionRefused):
        rounds(engine, made, [request("1", 0)])


@pytest.mark.parametrize(
    ("code", "words"),
    [
        (
            "COMPUTE_NOT_READY",
            "GPU-ul RunPod nu a putut fi pornit; nu s-a trimis și nu s-a cheltuit nimic.",
        ),
        ("RUNPOD_OFF", None),
        ("NOT_CONFIGURED", "RunPod Serverless nu este configurat pentru acest pas."),
        ("STOPPED", "Nu s-a trimis și nu s-a cumpărat nimic; pasul se poate porni din nou."),
    ],
)
def test_a_refusal_after_a_purchase_never_says_nothing_was_spent(code, words):
    # Review 2026-10-10: the GPU's own refusals are written for a step that bought nothing
    # («nu s-a cheltuit nimic»); after the step bought elsewhere they keep their reason and
    # code, lose that clause, and say what stays. Unchanged when nothing was bought.
    from app.providers.runpod.gpu_session import RUNPOD_OFF_WORDS, GpuSessionRefused

    said = words or RUNPOD_OFF_WORDS
    refused = GpuSessionRefused(code, said)
    after = batch_module.refusal_words(refused, bought_before=True)
    assert "nimic" not in after
    assert f"({code})" in after or after.startswith(f"{code}:")
    assert after.endswith(batch_module.REST_NOT_SENT_RO)
    assert batch_module.refusal_words(refused, bought_before=False) == said


def test_a_forced_off_after_a_purchase_keeps_its_own_words():
    from app.providers.runpod.gpu_session import FORCED_OFF_WORDS, GpuForcedOff

    assert batch_module.refusal_words(GpuForcedOff(), bought_before=True) == FORCED_OFF_WORDS


def test_a_round_whose_lost_chunk_is_proven_and_whose_next_was_refused_bought_nothing(
    engine, tmp_path, proving_session, clock
):
    # Review 2026-10-10: chunk 1 unanswered, chunk 2 paused past its wait, chunk 3 never sent.
    # The close proves chunk 1 never queued: nothing of the round reached RunPod, so its GPU
    # start goes back too and his letter says nothing was bought (it kept 5 credits and said
    # «ce s-a cumpărat înainte rămâne»).
    cloud = Cloud()
    cloud.run_answers = [
        MediaProviderError("lost", unanswered=True),
        *[paused() for _ in range(10)],
    ]
    made = adapter(
        engine, tmp_path, cloud, execution_timeout_cap_seconds=300, paused_wait_seconds=0
    )
    summary, meter, seen = rounds(engine, made, [request(str(n), 0) for n in (1, 2, 3)])
    assert sorted(o.error for o in seen) == ["SUBMISSION_UNCERTAIN", "UNSENT", "UNSENT"]
    assert summary["unsent_proof"]["proven"] is True
    assert meter.committed == 0
    assert summary["stopped"].startswith("RunPod a răspuns că endpointul este în pauză")
    assert "nu s-a cumpărat nimic" in summary["stopped"]
    assert "ce s-a cumpărat înainte rămâne" not in summary["stopped"]


def test_a_lost_round_proven_unsent_after_an_earlier_round_was_bought_never_says_nothing(
    engine, tmp_path, proving_session
):
    # Round one bought, round two's /run lost and proven never queued: the stop says the rest
    # was not bought, never «nu s-a cumpărat nimic» next to round one's credits.
    cloud = Cloud()
    cloud.run_answers = [None, MediaProviderError("lost", unanswered=True)]
    made = adapter(engine, tmp_path, cloud)
    made.core.transport = made.core.client.transport = finishing(cloud)
    summary, meter, _seen = rounds(
        engine,
        made,
        [request("1", 0)],
        next_round=lambda outcomes: [request("1", 0, attempt=2)] if len(outcomes) == 1 else [],
    )
    assert summary["rounds"] == 2 and summary["unsent_proof"]["proven"] is True
    assert meter.committed == price([1]) == 15.0
    assert "nu s-a cumpărat nimic" not in summary["stopped"].lower()
    assert "ce s-a cumpărat înainte rămâne" in summary["stopped"]


def test_an_open_purchase_under_the_same_key_refuses_unsent(engine, tmp_path, fake_session):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.submit_batch([request("1", 0)], session=Session_(), on_submitted=lambda item: None)
    refused, meter = refused_round(engine, made, [request("1", 0, prompt="other words")])
    assert refused.code == "IDEMPOTENCY_CONFLICT" and meter.committed == 0
    assert meter.attempts == 0 and len(cloud.posts()) == 1


def test_a_request_the_worker_contract_refuses_is_never_booked(
    engine, tmp_path, fake_session, monkeypatch
):
    def broken(raw):
        raise contract.ContractError("items[0].seed must be an integer")

    monkeypatch.setattr(batch_module.contract, "validate_input", broken)
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    refused, meter = refused_round(engine, made, [request("1", 0)])
    assert refused.code == "REQUEST_INVALID" and meter.committed == 0 and meter.attempts == 0
    assert not cloud.posts() and only_row(engine).error_code == "UNSENT"


def test_a_lone_pod_submit_answered_429_keeps_its_key_reusable(engine):
    from test_runpod_generation import FakeTransport, provider
    from test_runpod_generation import request as pod_request

    transport = FakeTransport(
        [MediaProviderError("slow down", http_status=429), {"id": "remote", "status": "QUEUED"}]
    )
    pod = provider(engine, transport)
    with pytest.raises(MediaProviderError):
        asyncio.run(pod.generate_image(pod_request()))
    first = only_row(engine)
    assert first.status == "FAILED" and first.error_code == "HTTP_429" and first.cost_value == "0"
    again = asyncio.run(pod.generate_image(pod_request()))
    assert again.id == first.id and again.idempotency_key == first.idempotency_key


# ----------------------------------------------------------------------- the stills step


class PictureCloud(Cloud):
    """A worker that finishes every item when its manifest is first looked for, drawing the
    picture the test chooses from the item's prompt."""

    def __init__(self, picture):
        super().__init__()
        self.picture = picture

    def __call__(self, host, method, path, headers, body=None, **kwargs):
        if host == "account.r2.example" and method == "GET" and "/manifests/" in path:
            for job, sent in list(self.jobs.items()):
                for n, item in enumerate(sent["input"]["items"]):
                    key = contract.manifest_key("amn/", item["idempotency_key"])
                    if item["idempotency_key"] in path and key not in self.objects:
                        self.finish(job, n, content=self.picture(item["prompt"]))
        return super().__call__(host, method, path, headers, body, **kwargs)


def stills_table():
    table = cost_plan.load_price_table()
    return replace(
        table,
        rows=(
            *table.rows,
            cost_plan.PriceRow(
                "Qwen-Image-2512",
                "image",
                "*",
                "estimate",
                "2026-10-08",
                "DOCUMENTED",
                credits_per_image=7,
            ),
        ),
        overhead_credits_per_round={"image": 13.4},
        round_models=frozenset({"Qwen-Image-2512"}),
    )


def test_stills_on_runpod_are_rounds_every_scene_first_then_the_rerolls(
    engine, tmp_path, fake_session
):
    # Qwen-Image-2512 binds no reference picture, so no scene waits for scene 1's still (its
    # Figure 1 could never be sent): round 1 is every scene's pair, the re-rolls come after.
    from app.media.models import SceneTake
    from app.media.stills_stage import StillsStageRefused, run_stills_stage, stills_plan
    from test_approvals import answer
    from test_stills_stage import FACE, NO_FACE, SUBJECTS, SpyJudge, a_film, faces_in

    storyboard_id = a_film(engine, tmp_path)
    cloud = PictureCloud(
        lambda prompt: FACE.read_bytes() if SUBJECTS[2] in prompt else NO_FACE[0].read_bytes()
    )
    made = adapter(engine, tmp_path, cloud)
    table = stills_table()

    def go():
        return run_stills_stage(
            engine,
            storyboard_id,
            str(uuid4()),
            plan_hash=stills_plan(engine, storyboard_id, model_id=made.model, table=table)[
                "plan_hash"
            ],
            image_adapter=made,
            registry=None,
            judge=SpyJudge(),
            storage_root=tmp_path / "media",
            table=table,
            face_counter=faces_in(),
            measure=("faces",),
        )

    plan = stills_plan(engine, storyboard_id, model_id=made.model, table=table)
    # 4 scenes x 14 credits, re-rolls x3, and the GPU start of every round priced in.
    assert plan["cost_credits"] == 4 * 14 + 2 * 14
    with pytest.raises(StillsStageRefused) as asked:
        go()
    assert asked.value.status == "NEEDS_APPROVAL" and not cloud.calls
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, imaginile.")
    result = go()

    jobs = [cloud.jobs[j]["input"]["items"] for j in sorted(cloud.jobs)]
    scenes = [[int(item["scene_id"]) for item in items] for items in jobs]
    assert scenes == [[1, 1, 2, 2, 3, 3, 4, 4], [2, 2], [2, 2]]
    assert len(fake_session) == 1 and fake_session[0]["closed"]
    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert all(by_scene[n]["status"] == "APPROVED" for n in (1, 3, 4))
    assert by_scene[2]["status"] == "NEEDS_OWNER" and by_scene[2]["rerolls"] == 2
    assert result["gpu"]["rounds"] == 3
    # 12 images x 7 credits + 3 GPU starts x 14 credits.
    assert result["spent_credits_quoted"] == 12 * 7 + 3 * 14  # GPU starts in whole credits
    with Session(engine) as s:
        rows = s.scalars(select(SceneTake).where(SceneTake.storyboard_id == storyboard_id)).all()
        assert len(rows) == 12 and all(r.remote_task_id.startswith("job-") for r in rows)
        assert sorted({r.status for r in rows if r.scene_number == 2}) == ["REJECTED"]


#: A fifth filmed scene for the five-scene film (the 2026-10-09 film had five).
FIFTH_SUBJECT = (
    "A wide view of a river delta under low grey cloud, small fishing boats far away, 24 mm "
    "lens, seen from high above."
)


def five_scene_film(engine, tmp_path):
    """Five LIVE scenes with compiled, clean prompts (test_stills_stage's look and subjects)."""
    from app.media.models import Storyboard, StoryboardScene
    from test_scene_takes import nepal_like
    from test_stills_stage import BIBLE, LOOK, SUBJECTS, TAIL

    subjects = {**SUBJECTS, 5: FIFTH_SUBJECT}
    words = {n: f"{LOOK} {subjects[n]} {TAIL}" for n in range(1, 6)}
    purposes = ("HOOK", "SETUP", "EVIDENCE", "EVIDENCE", "REVEAL")
    storyboard_id = nepal_like(
        engine,
        tmp_path,
        kinds=[("LIVE", purposes[n - 1], words[n]) for n in range(1, 6)],
    )
    with Session(engine) as s, s.begin():
        s.get(Storyboard, storyboard_id).visual_bible_json = dict(BIBLE)
        for row in s.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        ):
            row.prompt_json = {
                "scene_kind": "LIVE",
                "source": "model",
                "still_prompt": words[row.scene_index],
                "look_block": LOOK,
                "camera_move": "slow push-in",
            }
    return storyboard_id


@pytest.fixture
def proving_session(monkeypatch):
    """The GPU session faked; its close records what proves RunPod queued nothing (the queue
    read empty before the purge, the purge removed 0, the endpoint verified off), as
    `gpu_session.close_session` does, so an unanswered /run is proven unsent."""
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
            session.off_evidence = {
                "before_purge": {"in_queue": 0, "in_progress": 0, "running": 0},
                "purge_removed": 0,
                "off": {"off": True},
                "other_sessions": [],
            }
            opened[-1]["closed"] = True

    monkeypatch.setattr(gpu_batch, "gpu_session", fake)
    monkeypatch.setattr(gpu_batch, "gpu_precheck", lambda *args, **kwargs: None)
    return opened


def test_a_film_whose_scene_one_is_resent_buys_every_scene_first_and_its_rerolls_after(
    engine, tmp_path, proving_session
):
    """2026-10-09, «The Particle That Shouldn't Exist (But Does)»: scene 1's /run failed with
    no answer and was proven never queued; the next step sent scene 1's two items again with
    the same keys, and ONLY them, then re-rolled scene 1 twice; scenes 2-5 were never sent.
    Now round 1 is scene 1's re-sent pair AND every scene never sent, and scene 1's re-rolls
    come after, within the same cap."""
    from app.media.assembler import SceneRedoRefused, redo_plan, redo_scene
    from app.media.stills_stage import StillsStageRefused, run_stills_stage, stills_plan
    from test_approvals import answer
    from test_stills_stage import FACE, NO_FACE, SUBJECTS, SpyJudge, faces_in

    storyboard_id = five_scene_film(engine, tmp_path)
    # Scene 1 is refused by the gate every time (a face the bible forbids); the rest pass.
    cloud = PictureCloud(
        lambda prompt: FACE.read_bytes() if SUBJECTS[1] in prompt else NO_FACE[0].read_bytes()
    )
    cloud.run_answers = [MediaProviderError("lost", unanswered=True)]
    made = adapter(engine, tmp_path, cloud)
    table = stills_table()
    common = {
        "table": table,
        "storage_root": tmp_path / "media",
        "judge": SpyJudge(),
        "face_counter": faces_in(),
        "measure": ("faces",),
    }

    # The earlier /run: scene 1 alone («Refă imaginea»), unanswered, proven never queued.
    def redo():
        plan = redo_plan(engine, storyboard_id, "still", 1, table=table, stills_model=made.model)
        return redo_scene(
            engine,
            storyboard_id,
            str(uuid4()),
            kind="still",
            scene_index=1,
            plan_hash=plan["plan_hash"],
            image_adapter=made,
            **common,
        )

    with pytest.raises(SceneRedoRefused) as asked:
        redo()
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, refă imaginea.")
    assert redo()["still"]["status"] == "NOT_BOUGHT" and not cloud.jobs
    with Session(engine) as s:
        rows = s.scalars(select(GenerationJob)).all()
        first_keys = {row.idempotency_key for row in rows}
        assert len(first_keys) == 2 and {row.scene_id for row in rows} == {"1"}
        assert all(row.error_code == "UNSENT" for row in rows)

    # The stills step: every scene is bought; scene 1's pair goes again with the same keys.
    def go():
        plan = stills_plan(engine, storyboard_id, model_id=made.model, table=table)
        return run_stills_stage(
            engine,
            storyboard_id,
            str(uuid4()),
            plan_hash=plan["plan_hash"],
            image_adapter=made,
            registry=None,
            **common,
        )

    assert stills_plan(engine, storyboard_id, model_id=made.model, table=table)["to_buy"] == [
        1,
        2,
        3,
        4,
        5,
    ]
    with pytest.raises(StillsStageRefused) as asked:
        go()
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, imaginile.")
    result = go()

    jobs = [cloud.jobs[j]["input"]["items"] for j in sorted(cloud.jobs)]
    assert [[int(item["scene_id"]) for item in items] for items in jobs] == [
        [1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
        [1, 1],
        [1, 1],
    ]
    assert {item["idempotency_key"] for item in jobs[0][:2]} == first_keys
    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert all(by_scene[n]["status"] == "APPROVED" for n in (2, 3, 4, 5))
    assert by_scene[1]["status"] == "NEEDS_OWNER" and by_scene[1]["rerolls"] == 2
    # 14 images x 7 credits + 3 GPU starts x 14 credits, inside the approved cap.
    assert result["spent_credits_quoted"] == 14 * 7 + 3 * 14 <= result["cap_credits"]


# ------------------------------------------------------------------------ the motion step


def motion_table():
    table = runpod_table()
    return replace(
        table,
        overhead_credits_per_round={"video": 13.4},
        round_models=frozenset({"LTX-2.5"}),
    )


def test_motion_on_runpod_one_round_per_step_and_the_clip_qc_retry_is_the_next_round(
    engine, tmp_path, fake_session
):
    from app.media.assembler import MotionStepRefused, decide_take, motion_plan, run_motion_step
    from app.media.models import SceneTake
    from test_approvals import answer
    from test_clip_qc_wiring import ScriptedCheck
    from test_film_costing import a_film

    storyboard_id = a_film(engine, tmp_path, scenes=3)
    cloud = finishing_video(Cloud())
    made = RunPodVideoAdapter(serverless(), engine, model="LTX-2.5", storage_root=tmp_path)
    made.core.transport = made.core.client.transport = cloud
    capability = runpod_capability()
    table = motion_table()

    def go(step, check):
        plan = motion_plan(engine, storyboard_id, capabilities=[capability], table=table)
        return run_motion_step(
            engine,
            storyboard_id,
            str(uuid4()),
            step=step,
            plan_hash=plan["plan_hash"],
            adapter_for_model=lambda model: made if model == "LTX-2.5" else None,
            capabilities=[capability],
            table=table,
            storage_root=tmp_path / "media",
            clip_check=check,
        )

    def approved(step, check):
        with pytest.raises(MotionStepRefused) as asked:
            go(step, check)
        assert asked.value.status == "NEEDS_APPROVAL"
        answer(engine, asked.value.approval_id, "APPROVED", note="Da.")
        return go(step, check)

    plan = motion_plan(engine, storyboard_id, capabilities=[capability], table=table)
    hero = plan["steps"]["test_shot"]
    # One 5 s shot at 14 credits + one GPU start; at worst its retry round too.
    assert hero["cost_credits"] == 14 + 14 and hero["cap_credits"] == 2 * 14 + 2 * 14

    result = approved("test_shot", ScriptedCheck("FAILED", "PASSED"))
    assert [len(cloud.inner.jobs[j]["input"]["items"]) for j in sorted(cloud.inner.jobs)] == [1, 1]
    first, retry = (cloud.inner.jobs[j]["input"]["items"][0] for j in sorted(cloud.inner.jobs))
    assert retry["seed"] == first["seed"] + 1 and retry["prompt"] != first["prompt"]
    scene = {e["scene_index"]: e for e in result["scenes"]}[1]
    assert scene["status"] == "PAID" and scene["clip_qc"]["attempts"] == 2
    assert result["gpu"]["rounds"] == 2 and len(fake_session) == 1
    with Session(engine) as s:
        (paid,) = s.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.kind == "test_shot",
                SceneTake.status == "PAID",
            )
        ).all()
    decide_take(engine, paid.id, "APPROVED", decided_by="owner")

    result = approved("motion", ScriptedCheck("PASSED"))
    third = sorted(cloud.inner.jobs)[-1]
    assert [it["scene_id"] for it in cloud.inner.jobs[third]["input"]["items"]] == ["2", "3"]
    assert all(e["status"] == "PAID" for e in result["scenes"] if e["scene_index"] in (2, 3))
    assert result["spent_credits_quoted"] == 2 * 14 + 14
    assert len(fake_session) == 2 and all(s["closed"] for s in fake_session)
