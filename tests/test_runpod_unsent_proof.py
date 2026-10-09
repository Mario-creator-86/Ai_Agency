"""A RunPod /run that failed without a job id (2026-10-09, «The Particle That Shouldn't Exist»).

The first live stills round failed in 0.12 s; RunPod's console showed no job, no worker, no log
and $0, yet the studio kept both items SUBMISSION_UNCERTAIN, held scene 1 for the Owner and the
film could not move. Here:

1. the GPU-off procedure keeps what proves nothing was queued (the queue read before the
   purge, RunPod's own purge count, the verified off) and the worker's bucket record (no claim,
   no manifest) proves nothing was made: then the items are UNSENT, the round is given back and
   the scene is not held; anything less keeps today's behaviour;
2. a hold left before that evidence existed is put in front of the Owner as a card with what
   the studio recorded; his yes releases it (the release pass, at boot and in the watchdog);
3. «Refă imaginea» on a RunPod image model is one GPU round under his yes.

Every RunPod, bucket and GPU call goes to a fake transport; nothing reaches a vendor.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from app.decisions.models import OwnerDecision
from app.decisions.services import DecideCommand, decide_owner_decision
from app.media import assembler
from app.media.assembler import SpendMeter
from app.media.models import SceneTake
from app.models import ApprovalRequest, DomainEvent
from app.providers.media_http import MediaProviderError
from app.providers.runpod import batch as batch_module
from app.providers.runpod import endpoint as endpoint_module
from app.providers.runpod import gpu_session as gpu_session_module
from app.providers.runpod.adapters import RunPodImageAdapter
from app.providers.runpod.gpu_session import GpuSessionRow, close_session, open_session
from app.providers.runpod.jobs import GenerationJob
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_runpod_batch import (
    Cloud,
    PictureCloud,
    Session_,
    adapter,
    price,
    request,
    stills_table,
)
from test_runpod_gpu_control import (  # noqa: F401 - no_wait, running_studio: autouse fixtures
    Fake,
    config,
    no_wait,
    permit,
    rows,
    running_studio,
)
from test_runpod_gpu_policy import runpod

#: His stills mirror (test_runpod_owner_setup): the cached model the stills endpoint reads.
MIRROR = {"stills_mirror_repo": "owner/amn-stills", "stills_mirror_revision": "a" * 40}


class Live(Fake):
    """RunPod's two hosts (test_runpod_gpu_control.Fake), its /run and the Owner's bucket."""

    def __init__(self, *, removed: int | None = 0, **values: Any) -> None:
        super().__init__(**values)
        self.removed = removed
        self.objects: dict[str, Any] = {}
        self.bucket_error: Exception | None = None
        self.run_error: Exception = MediaProviderError(
            "api.runpod.ai refused the request (HTTP 503)",
            http_status=503,
            unanswered=True,
            detail="endpoint is updating",
        )

    def __call__(self, host, method, path, headers, body=None, **kwargs):
        if host == "bucket.example":
            self.calls.append((host, method, path, dict(headers), None, kwargs))
            if self.bucket_error is not None:
                raise self.bucket_error
            key = urlsplit(path).path.removeprefix("/amn-out/")
            if method == "PUT":
                self.objects[key] = body
                return None, b"", "text/plain"
            if key not in self.objects:
                raise MediaProviderError("NoSuchKey", http_status=404)
            return self.objects[key], b"", "application/json"
        if host == "api.runpod.ai" and method == "POST" and path.endswith("/run"):
            self.calls.append((host, method, path, dict(headers), json.loads(body), kwargs))
            raise self.run_error
        if host == "api.runpod.ai" and path.endswith("/purge-queue"):
            self.calls.append((host, method, path, dict(headers), None, kwargs))
            answer: dict[str, Any] = {"status": "completed"}
            if self.removed is not None:
                answer["removed"] = self.removed
            return answer, b"", "application/json"
        return super().__call__(host, method, path, headers, body, **kwargs)

    def runs(self) -> list[dict[str, Any]]:
        return [c[4] for c in self.calls if c[1] == "POST" and c[2].endswith("/run")]


@pytest.fixture
def recorded_gpu(monkeypatch):
    """The GPU session faked and recorded (test_runpod_batch's own fixture): no close evidence,
    so the sessions of the tests written before 2026-10-09 prove nothing."""
    from contextlib import contextmanager

    from app.media import gpu_batch

    opened: list[dict[str, Any]] = []

    @contextmanager
    def fake(engine, adapter, *, purpose, permit):
        session = Session_()
        opened.append({"purpose": purpose, "session": session, "closed": False})
        try:
            yield session
        finally:
            opened[-1]["closed"] = True

    monkeypatch.setattr(gpu_batch, "gpu_session", fake)
    monkeypatch.setattr(gpu_batch, "gpu_precheck", lambda *args, **kwargs: None)
    return opened


def live_adapter(engine, tmp_path, live: Live, identifier: str, **values: Any):
    made = RunPodImageAdapter(
        config(**(MIRROR | values)),
        engine,
        model="Qwen-Image-2512",
        integration_id=identifier,
        storage_root=tmp_path,
    )
    made.core.transport = made.core.client.transport = live
    return made


@pytest.fixture
def studio(engine, tmp_path, monkeypatch):
    """His RunPod connection (agents may switch the GPU on) and the faked RunPod + bucket."""
    _vault, identifier = runpod(engine, monkeypatch, allow=True, **MIRROR)
    live = Live()
    monkeypatch.setattr(endpoint_module, "request", live)
    return identifier, live, live_adapter(engine, tmp_path, live, identifier)


def live_rounds(engine, made, identifier, requests):
    """`run_rounds` inside the REAL GPU session (open, close, verify) on the faked RunPod."""
    from app.media.gpu_batch import run_rounds

    meter = SpendMeter()
    seen: list[Any] = []
    unsent: list[tuple[list[Any], dict[str, Any]]] = []
    summary = run_rounds(
        engine,
        made,
        permit=permit(identifier),
        purpose="image",
        first_round=requests,
        next_round=lambda outcomes: [],
        price_credits=price,
        cap_left=lambda: 1000.0 - meter.committed,
        guard=None,
        stopped=lambda: None,
        on_submitted=lambda item: None,
        on_outcome=seen.append,
        meter=meter,
        sleep=lambda s: None,
        on_unsent=lambda outcomes, proof: unsent.append((outcomes, proof)),
    )
    return summary, meter, seen, unsent


def jobs(engine) -> list[GenerationJob]:
    with Session(engine) as s:
        found = list(
            s.scalars(
                select(GenerationJob).order_by(
                    GenerationJob.created_at, GenerationJob.idempotency_key
                )
            )
        )
        for row in found:
            s.expunge(row)
        return found


def events(engine, kind: str) -> list[DomainEvent]:
    with Session(engine) as s:
        return list(s.scalars(select(DomainEvent).where(DomainEvent.event_type == kind)))


# ------------------------------------------------------------------- the GPU-off evidence


def test_the_purge_keeps_runpods_own_count_and_a_missing_count_is_unknown():
    import asyncio

    live = Live(removed=0)
    control = endpoint_module.EndpointControl(config(), "ep-stills", transport=live)
    assert asyncio.run(control.purge_queue()) == 0 and control.last_purge_removed == 0
    live.removed = None  # an answer without «removed» is not «0 removed»
    assert asyncio.run(control.purge_queue()) == 0 and control.last_purge_removed is None


def test_a_close_after_an_uncertain_run_reads_the_queue_before_the_purge_and_keeps_it(
    engine, studio
):
    identifier, live, made = studio
    session = open_session(engine, made, purpose="image", permit=permit(identifier))
    session.note_uncertain(["key-a", "key-b"])
    live.calls.clear()
    reading = close_session(engine, session, reason="STEP_DONE")
    assert reading is not None and reading.off
    # The queue is read BEFORE anything is taken out of it, then purged, then max=0, verified.
    assert live.verbs()[:3] == ["health", "purge-queue", "PATCH"]
    (row,) = rows(engine)
    evidence = row.off_reading["evidence"]
    assert evidence["before_purge"]["in_queue"] == 0
    assert evidence["before_purge"]["in_progress"] == 0
    assert evidence["before_purge"]["running"] == 0
    assert evidence["purge_removed"] == 0 and evidence["other_sessions"] == []
    assert evidence["uncertain_items"] == 2 and row.off_reading["off"] is True
    assert session.off_evidence is not None and session.off_evidence["off"]["off"] is True


def test_the_queue_read_before_the_purge_is_one_short_try_that_never_holds_back_the_off(
    engine, studio
):
    # 2026-10-09 review: that read comes exactly when RunPod's API is failing; with the
    # control's retries (up to 4 x 60 s) the purge and the max=0 would wait behind it.
    identifier, live, made = studio
    session = open_session(engine, made, purpose="image", permit=permit(identifier))
    session.note_uncertain(["key-a"])
    live.calls.clear()
    live.fail[("GET", "/v2/ep-stills/health")] = [
        MediaProviderError("RunPod did not answer", unanswered=True)
    ]
    reading = close_session(engine, session, reason="STEP_DONE")
    assert reading is not None and reading.off
    # One try, then straight to the purge and the max=0 (the control would have retried).
    assert live.verbs()[:3] == ["health", "purge-queue", "PATCH"]
    first = live.calls[0]
    assert first[5]["timeout"] <= gpu_session_module.EVIDENCE_READ_SECONDS
    (row,) = rows(engine)
    evidence = row.off_reading["evidence"]
    assert evidence["before_purge"] is None and evidence["before_purge_problem"]
    # Unread is never zero: the proof fails on it, the safe side.
    assert "QUEUE_UNREAD_BEFORE_PURGE" in batch_module.queue_problems(session.off_evidence)


# ------------------------------------------------------------------ the proof, in the step


def test_a_run_runpod_never_queued_is_proven_unsent_given_back_and_logged(engine, studio, caplog):
    caplog.set_level(logging.INFO, logger="studio.runpod")
    identifier, live, made = studio
    summary, meter, seen, unsent = live_rounds(
        engine, made, identifier, [request("1", 0), request("1", 1)]
    )
    assert len(live.runs()) == 1
    assert [o.error for o in seen] == ["SUBMISSION_UNCERTAIN", "SUBMISSION_UNCERTAIN"]
    # The worker's own record was read: no claim and no manifest for either key.
    bucket_reads = [c[2] for c in live.calls if c[0] == "bucket.example"]
    assert sum("/claims/" in path for path in bucket_reads) == 2
    assert sum("/manifests/" in path for path in bucket_reads) == 2
    for row in jobs(engine):
        assert row.status == "FAILED" and row.error_code == "UNSENT"
        assert row.cost_value == "0" and row.remote_job_id is None
        assert row.output["not_queued"]["proven"] is True
        assert row.gpu_session_id is not None
    # Nothing was made: the round (its items and its GPU start) is given back.
    assert meter.committed == 0
    assert summary["stopped"] == batch_module.NOT_QUEUED_STOP
    assert summary["unsent_proof"]["proven"] is True
    (outcomes, proof) = unsent[0]
    assert len(outcomes) == 2 and proof["evidence"]["purge_removed"] == 0
    (logged,) = [r for r in caplog.records if r.getMessage() == "runpod_run_proof"]
    assert logged.proven is True and logged.problems == []
    assert [r for r in caplog.records if r.getMessage() == "runpod_run_failed"]
    (event,) = events(engine, batch_module.PROOF_EVENT)
    assert event.payload["proven"] is True
    # The same keys stay reusable: the next round sends them again, never a new attempt.
    keys = {row.idempotency_key for row in jobs(engine)}
    live.run_error = MediaProviderError("again", unsent=True)
    with pytest.raises(MediaProviderError):
        live_rounds(engine, made, identifier, [request("1", 0), request("1", 1)])
    assert {row.idempotency_key for row in jobs(engine)} == keys


def test_the_next_switch_on_after_a_run_booked_as_never_queued_purges_the_queue_first(
    engine, studio, monkeypatch
):
    # 2026-10-09 review: the proof is one reading at the close. A /run RunPod answered late
    # (a 502/504, the client's deadline) could be queued after it and wait at max=0; the next
    # switch-on must not run it (billed and booked nowhere): its queue is purged first.
    identifier, live, made = studio
    fresh = open_session(engine, made, purpose="image", permit=permit(identifier))
    assert "purge-queue" not in live.verbs()  # an ordinary switch-on is the PATCH alone
    close_session(engine, fresh, reason="STEP_DONE")
    live_rounds(engine, made, identifier, [request("1", 0), request("1", 1)])
    assert all(row.error_code == "UNSENT" for row in jobs(engine))
    live.calls.clear()
    live.removed = 1  # the late job of that /run, waiting in the queue
    session = open_session(engine, made, purpose="image", permit=permit(identifier))
    verbs = live.verbs()
    assert verbs.index("purge-queue") < verbs.index("PATCH")
    assert live.patched()[0]["workers"]["max"] == 1
    opened = [
        e for e in events(engine, "runpod.gpu_session_opened") if e.aggregate_id == session.id
    ]
    assert opened[0].payload["purged_first"]["removed"] == 1
    close_session(engine, session, reason="STEP_DONE")
    # Once the longest job ttl has passed, nothing of it can still wait: the PATCH alone again.
    later = datetime.now().astimezone() + timedelta(days=1)
    monkeypatch.setattr(gpu_session_module, "_now", lambda: later)
    live.calls.clear()
    again = open_session(engine, made, purpose="image", permit=permit(identifier))
    assert "purge-queue" not in live.verbs()
    close_session(engine, again, reason="STEP_DONE")


@pytest.mark.parametrize(
    ("setup", "problem"),
    [
        (lambda live: setattr(live, "removed", 1), "PURGE_REMOVED:1"),
        (lambda live: setattr(live, "removed", None), "PURGE_UNANSWERED"),
        (
            lambda live: live.health_answers.__setitem__(
                "ep-stills",
                [
                    {
                        "jobs": {"inQueue": 0, "inProgress": 1, "completed": 0, "failed": 0},
                        "workers": {"idle": 0, "running": 1},
                    }
                ],
            ),
            "IN_PROGRESS_BEFORE_PURGE:1",
        ),
        (lambda live: setattr(live, "claimed", True), "WORKER_CLAIM"),
        (
            lambda live: setattr(
                live, "bucket_error", MediaProviderError("denied", http_status=403)
            ),
            "BUCKET_UNREADABLE",
        ),
    ],
)
def test_anything_less_than_the_proof_keeps_the_items_uncertain_and_counted(
    engine, studio, caplog, setup, problem
):
    caplog.set_level(logging.INFO, logger="studio.runpod")
    identifier, live, made = studio
    setup(live)
    if getattr(live, "claimed", False):
        # The worker's claim on the first item: it started GPU work on it.
        original = live.__class__.__call__

        def claimed(host, method, path, headers, body=None, **kwargs):
            if host == "bucket.example" and "/claims/" in path:
                live.calls.append((host, method, path, dict(headers), None, kwargs))
                return {"job_id": "job-x", "claimed_at": 1.0}, b"", "application/json"
            return original(live, host, method, path, headers, body, **kwargs)

        made.core.transport = made.core.client.transport = claimed
    summary, meter, _seen, unsent = live_rounds(
        engine, made, identifier, [request("1", 0), request("1", 1)]
    )
    assert summary["stopped"] == "SUBMISSION_UNCERTAIN" and not unsent
    assert meter.committed == price([1, 2])  # possibly served: still counted
    for row in jobs(engine):
        assert row.error_code == "SUBMISSION_UNCERTAIN" and row.status != "FAILED"
    (logged,) = [r for r in caplog.records if r.getMessage() == "runpod_run_proof"]
    assert logged.proven is False
    assert any(p.startswith(problem) for p in logged.problems), logged.problems


def test_a_session_that_recorded_no_evidence_proves_nothing(engine, tmp_path, recorded_gpu):
    # The recorded fake session of the older tests: no close evidence, today's behaviour.
    cloud = Cloud()
    cloud.run_answers = [MediaProviderError("lost", unanswered=True)]
    made = adapter(engine, tmp_path, cloud)
    from test_runpod_batch import rounds

    summary, meter, _seen = rounds(engine, made, [request("1", 0)])
    assert summary["stopped"] == "SUBMISSION_UNCERTAIN" and meter.committed == 15.0
    assert summary["unsent_proof"]["proven"] is False
    assert summary["unsent_proof"]["problems"] == ["NO_EVIDENCE"]
    assert not [c for c in cloud.calls if "/claims/" in c[2]]
    (row,) = jobs(engine)
    assert row.gpu_session_id == recorded_gpu[0]["session"].id  # the session is named


# --------------------------------------------------------------- the stills step, end to end


def stills_go(engine, made, storyboard_id, tmp_path, correlation=None):
    from app.media.stills_stage import run_stills_stage, stills_plan
    from test_stills_stage import SpyJudge, faces_in

    table = stills_table()
    return run_stills_stage(
        engine,
        storyboard_id,
        correlation or str(uuid4()),
        plan_hash=stills_plan(engine, storyboard_id, model_id=made.model, table=table)["plan_hash"],
        image_adapter=made,
        registry=None,
        judge=SpyJudge(),
        storage_root=tmp_path / "media",
        table=table,
        face_counter=faces_in(),
        measure=("faces",),
        integration_id=made.integration_id,
    )


def approved_stills(engine, made, storyboard_id, tmp_path, correlation=None):
    from app.media.stills_stage import StillsStageRefused
    from test_approvals import answer

    with pytest.raises(StillsStageRefused) as asked:
        stills_go(engine, made, storyboard_id, tmp_path)
    assert asked.value.status == "NEEDS_APPROVAL"
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, imaginile.")
    return stills_go(engine, made, storyboard_id, tmp_path, correlation)


def scene_identity(engine, storyboard_id: str, index: int) -> dict[str, Any]:
    from app.media.stills_stage import _read_scenes

    _bible, scenes = _read_scenes(engine, storyboard_id)
    return next(scene.identity for scene in scenes if scene.index == index)


def still_takes(engine, storyboard_id: str) -> list[SceneTake]:
    with Session(engine) as s:
        found = list(
            s.scalars(
                select(SceneTake).where(
                    SceneTake.storyboard_id == storyboard_id, SceneTake.kind == "still"
                )
            )
        )
        for row in found:
            s.expunge(row)
        return found


def test_a_stills_round_runpod_never_queued_leaves_the_scene_free(engine, tmp_path, studio):
    from app.media.stills_stage import stills_plan
    from test_stills_stage import a_film

    _identifier, live, made = studio
    storyboard_id = a_film(engine, tmp_path)
    result = approved_stills(engine, made, storyboard_id, tmp_path)
    assert len(live.runs()) == 1
    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert by_scene[1]["status"] == "NOT_BOUGHT"
    assert "nu a pus cererea la coadă" in by_scene[1]["reason"]
    assert result["spent_credits_quoted"] == 0
    assert result["gpu"]["unsent_proof"]["proven"] is True
    takes = still_takes(engine, storyboard_id)
    assert len(takes) == 2
    assert all(t.status == "REFUSED" and t.failure_code == "RUNPOD.NOT_QUEUED" for t in takes)
    assert all(t.credits_quoted is None for t in takes)
    # Not held for the Owner: no hold event, nothing in the scene's memory, buyable again.
    assert events(engine, assembler.STILL_HOLD_EVENT) == []
    memory = assembler.scene_memory(
        engine, storyboard_id, "still", {1: scene_identity(engine, storyboard_id, 1)}
    )
    assert memory[1].hold_ro is None and memory[1].attempts == 0
    plan = stills_plan(engine, storyboard_id, model_id=made.model, table=stills_table())
    assert 1 in plan["to_buy"]


# ------------------------------------------------- the release of a hold left before 2026-10-09


def legacy_hold(engine, tmp_path, recorded_gpu, **session_values: Any) -> dict[str, Any]:
    """The film of 2026-10-09 as it stands: scene 1 held UNANSWERED, two uncertain rows with no
    job id, and the GPU session's legacy record (no purge answer, no queue read before it).
    The hold event of that day named neither its rows nor its takes."""
    from app.media import stills_stage
    from test_stills_stage import a_film

    storyboard_id = a_film(engine, tmp_path)
    cloud = PictureCloud(lambda prompt: b"")
    cloud.run_answers = [MediaProviderError("lost", unanswered=True)]
    made = adapter(engine, tmp_path, cloud)
    correlation = str(uuid4())
    named = stills_stage.runpod_hold_items
    stills_stage.runpod_hold_items = lambda refused: {}  # type: ignore[assignment]
    try:
        result = approved_stills(engine, made, storyboard_id, tmp_path, correlation)
    finally:
        stills_stage.runpod_hold_items = named  # type: ignore[assignment]
    (hold,) = events(engine, assembler.STILL_HOLD_EVENT)
    assert assembler.RUNPOD_HOLD_ITEMS not in hold.payload
    assert {e["scene_index"]: e for e in result["scenes"]}[1]["status"] == "NEEDS_OWNER"
    found = jobs(engine)
    assert len(found) == 2 and all(r.error_code == "SUBMISSION_UNCERTAIN" for r in found)
    created = sorted(datetime.fromisoformat(r.created_at) for r in found)
    session_id = str(uuid4())
    with Session(engine) as s, s.begin():
        for row in s.scalars(select(GenerationJob)):
            row.gpu_session_id = None  # the rows of 2026-10-09 did not name their session
        values: dict[str, Any] = {
            "id": session_id,
            "integration_id": str(uuid4()),
            "endpoint_id": "stills-ep",
            "purpose": "image",
            "step": "stills",
            "storyboard_id": storyboard_id,
            "correlation_id": correlation,
            "process_token": "earlier-process",
            "status": "CLOSED",
            "workers_max": 1,
            "opened_at": (created[0] - timedelta(seconds=1)).isoformat(),
            "renewed_at": (created[0] - timedelta(seconds=1)).isoformat(),
            "expires_at": (created[0] + timedelta(hours=1)).isoformat(),
            "closed_at": (created[-1] + timedelta(seconds=1)).isoformat(),
            "close_reason": "STEP_DONE",
            "verified_off": True,
            "off_reading": {
                "endpoint_id": "stills-ep",
                "off": True,
                "workers_max": 0,
                "running": 0,
                "in_progress": 0,
                "in_queue": 0,
                "idle": 0,
                "reason_ro": None,
                "read_at": (created[-1] + timedelta(seconds=1)).isoformat(),
            },
            "remote_job_ids": [],
        } | session_values
        s.add(GpuSessionRow(**values))
    return {
        "storyboard_id": storyboard_id,
        "correlation": correlation,
        "session_id": session_id,
        "cloud": cloud,
        "made": made,
    }


def open_cards(engine) -> list[OwnerDecision]:
    from app.media.runpod_unsent import CARD_KIND

    with Session(engine) as s:
        found = list(
            s.scalars(
                select(OwnerDecision).where(
                    OwnerDecision.kind == CARD_KIND, OwnerDecision.status == "PENDING"
                )
            )
        )
        for row in found:
            s.expunge(row)
        return found


def held(engine, storyboard_id: str) -> str | None:
    return assembler.scene_memory(
        engine, storyboard_id, "still", {1: scene_identity(engine, storyboard_id, 1)}
    )[1].hold_ro


def test_todays_hold_is_his_card_with_the_evidence_and_his_yes_releases_the_scene(
    engine, tmp_path, recorded_gpu
):
    from app.decisions.seed import seed_owner_decisions
    from app.media.runpod_unsent import propose_release_cards
    from app.media.stills_stage import stills_plan

    film = legacy_hold(engine, tmp_path, recorded_gpu)
    storyboard_id = film["storyboard_id"]
    assert held(engine, storyboard_id)
    before = len(film["cloud"].calls)

    # At boot (the audit's seed) the card is proposed once; the watchdog's pass adds nothing.
    seed_owner_decisions(engine)
    (card,) = open_cards(engine)
    assert propose_release_cards(engine, correlation_id=str(uuid4()))["cards"] == []
    assert len(open_cards(engine)) == 1
    assert "Nu s-a trimis nimic" in card.title_ro and "scena 1" in card.title_ro
    assert "0 la coadă, 0 în lucru, 0 workeri" in card.why_ro
    assert "golirii cozii nu a fost înregistrat" in card.why_ro
    assert card.subject_id == storyboard_id
    # Proposing decided nothing: the scene is still held and the rows still uncertain.
    assert held(engine, storyboard_id)
    assert all(r.error_code == "SUBMISSION_UNCERTAIN" for r in jobs(engine))

    answer = decide_owner_decision(
        engine,
        card.id,
        DecideCommand(
            command_id=uuid4(),
            expected_version=card.version,
            decision="ACCEPT",
            option_key="release",
        ),
        issued_by="owner",
    )
    assert answer
    assert held(engine, storyboard_id) is None
    for row in jobs(engine):
        assert row.status == "FAILED" and row.error_code == "UNSENT" and row.cost_value == "0"
        assert row.output["not_queued"]["by"] == "owner"
    takes = still_takes(engine, storyboard_id)
    assert all(t.failure_code == "RUNPOD.NOT_QUEUED" and t.credits_quoted is None for t in takes)
    (released,) = events(engine, assembler.RUNPOD_UNSENT_RELEASED_EVENT)
    assert released.payload["scene_number"] == 1
    assert released.payload["gpu_session_id"] == film["session_id"]
    plan = stills_plan(engine, storyboard_id, model_id=film["made"].model, table=stills_table())
    assert 1 in plan["to_buy"]
    # Nothing was sent anywhere to decide or to release, and a second pass changes nothing.
    assert len(film["cloud"].calls) == before
    assert propose_release_cards(engine, correlation_id=str(uuid4()))["cards"] == []
    assert len(events(engine, assembler.RUNPOD_UNSENT_RELEASED_EVENT)) == 1


def test_his_no_keeps_the_scene_held_and_is_not_asked_again(engine, tmp_path, recorded_gpu):
    from app.media.runpod_unsent import propose_release_cards

    film = legacy_hold(engine, tmp_path, recorded_gpu)
    propose_release_cards(engine, correlation_id=str(uuid4()))
    (card,) = open_cards(engine)
    decide_owner_decision(
        engine,
        card.id,
        DecideCommand(
            command_id=uuid4(), expected_version=card.version, decision="ACCEPT", option_key="keep"
        ),
        issued_by="owner",
    )
    assert held(engine, film["storyboard_id"])
    assert propose_release_cards(engine, correlation_id=str(uuid4()))["cards"] == []
    assert all(r.error_code == "SUBMISSION_UNCERTAIN" for r in jobs(engine))


@pytest.mark.parametrize(
    "values",
    [
        {"remote_job_ids": ["job-9"]},  # RunPod accepted a job in that session
        {"verified_off": False},
        {
            "off_reading": {
                "endpoint_id": "stills-ep",
                "off": False,
                "workers_max": 0,
                "running": 0,
                "in_progress": 0,
                "in_queue": 1,
                "idle": 0,
                "reason_ro": "1 la coadă",
                "read_at": "2026-10-09T11:45:38+00:00",
            }
        },
    ],
)
def test_no_card_when_what_was_recorded_is_not_clean(engine, tmp_path, recorded_gpu, values):
    from app.media.runpod_unsent import propose_release_cards

    film = legacy_hold(engine, tmp_path, recorded_gpu, **values)
    assert propose_release_cards(engine, correlation_id=str(uuid4()))["cards"] == []
    assert open_cards(engine) == [] and held(engine, film["storyboard_id"])


def test_no_card_when_another_step_used_the_endpoint_meanwhile(engine, tmp_path, recorded_gpu):
    from app.media.runpod_unsent import propose_release_cards

    film = legacy_hold(engine, tmp_path, recorded_gpu)
    with Session(engine) as s, s.begin():
        mine = s.get(GpuSessionRow, film["session_id"])
        s.add(
            GpuSessionRow(
                id=str(uuid4()),
                integration_id=mine.integration_id,
                endpoint_id=mine.endpoint_id,
                purpose="image",
                step="scene_redo",
                storyboard_id="another-film",
                correlation_id=str(uuid4()),
                process_token="earlier-process",
                status="CLOSED",
                workers_max=1,
                opened_at=mine.opened_at,
                renewed_at=mine.opened_at,
                expires_at=mine.expires_at,
                closed_at=mine.closed_at,
                close_reason="STEP_DONE",
                verified_off=True,
                remote_job_ids=["job-7"],
            )
        )
    assert propose_release_cards(engine, correlation_id=str(uuid4()))["cards"] == []
    assert held(engine, film["storyboard_id"])


def test_a_legacy_hold_whose_keys_an_earlier_attempt_reserved_is_still_his_card(
    engine, tmp_path, recorded_gpu
):
    # 2026-10-09 review: a key reserved by an earlier attempt (proven unsent, or a 4xx) and
    # sent again keeps its first creation time, before the session that left it uncertain.
    from app.media.runpod_unsent import propose_release_cards

    film = legacy_hold(engine, tmp_path, recorded_gpu)
    with Session(engine) as s, s.begin():
        for row in s.scalars(select(GenerationJob)):
            row.created_at = (
                datetime.fromisoformat(row.created_at) - timedelta(hours=2)
            ).isoformat()
    assert len(propose_release_cards(engine, correlation_id=str(uuid4()))["cards"]) == 1
    (card,) = open_cards(engine)
    assert "scena 1" in card.title_ro and "(2 imagini)" in card.why_ro
    assert held(engine, film["storyboard_id"])


def stuck_on_runpod(engine, tmp_path, made, live) -> str:
    """The stills step on the faked RunPod: scene 1's /run unanswered, the proof not made."""
    from test_stills_stage import a_film

    storyboard_id = a_film(engine, tmp_path)
    result = approved_stills(engine, made, storyboard_id, tmp_path)
    assert len(live.runs()) == 1
    assert result["gpu"]["unsent_proof"]["proven"] is False
    assert {e["scene_index"]: e for e in result["scenes"]}[1]["status"] == "NEEDS_OWNER"
    assert held(engine, storyboard_id)
    return storyboard_id


@pytest.mark.parametrize("kind", ["claims", "manifests"])
def test_no_card_when_the_proof_found_the_worker_started_or_made_the_item(
    engine, tmp_path, studio, kind
):
    # 2026-10-09 review: the worker's claim (GPU work started) or manifest (the item made)
    # is a sign, not a gap: the scene stays held for the sheet, nothing is booked unsent.
    from app.media.runpod_unsent import propose_release_cards

    _identifier, live, made = studio
    original = made.core.transport

    def found(host, method, path, headers, body=None, **kwargs):
        if host == "bucket.example" and f"/{kind}/" in path:
            live.calls.append((host, method, path, dict(headers), None, kwargs))
            return {"job_id": "job-x", "claimed_at": 1.0}, b"", "application/json"
        return original(host, method, path, headers, body, **kwargs)

    made.core.transport = made.core.client.transport = found
    storyboard_id = stuck_on_runpod(engine, tmp_path, made, live)
    proof = [e.payload for e in events(engine, batch_module.PROOF_EVENT)]
    assert any(p.startswith("WORKER_") for p in proof[0]["problems"])
    assert propose_release_cards(engine, correlation_id=str(uuid4())) == {
        "cards": [],
        "released": [],
    }
    assert open_cards(engine) == [] and held(engine, storyboard_id)
    assert all(row.error_code == "SUBMISSION_UNCERTAIN" for row in jobs(engine))


def test_his_card_says_what_the_proof_could_not_read_as_recorded(
    engine, tmp_path, studio, monkeypatch
):
    # 2026-10-09 review: the queue read before the purge failed, so the bucket was never
    # read either; the card must not say the queue was empty or that the bucket read failed.
    from app.media.runpod_unsent import propose_release_cards

    _identifier, live, made = studio

    def unread(health):
        raise RuntimeError("the queue could not be read")

    monkeypatch.setattr(gpu_session_module, "_health_record", unread)
    storyboard_id = stuck_on_runpod(engine, tmp_path, made, live)
    (proof,) = [e.payload for e in events(engine, batch_module.PROOF_EVENT)]
    assert proof["problems"] == ["QUEUE_UNREAD_BEFORE_PURGE"]
    assert not [c for c in live.calls if c[0] == "bucket.example" and "/claims/" in c[2]]
    assert len(propose_release_cards(engine, correlation_id=str(uuid4()))["cards"]) == 1
    (card,) = open_cards(engine)
    assert "Coada nu a putut fi citită înainte de golire" in card.why_ro
    assert "ce a lăsat lucrătorul în bucket nu a fost citit" in card.why_ro
    assert "Golirea cozii nu a scos nicio lucrare" in card.why_ro
    assert "era goală" not in card.why_ro and "nu s-a putut citi" not in card.why_ro
    assert " UTC," in card.why_ro and "utc" not in card.why_ro
    assert card.subject_id == storyboard_id


def test_a_step_stopped_between_its_takes_and_its_rows_holds_nothing_and_buys_nothing_twice(
    engine, tmp_path, studio, monkeypatch
):
    # The proven round re-records its takes before its journal rows: a process that stops in
    # between leaves the rows uncertain (their keys are sent again, never new ones) and no
    # scene held by a round that was proven unsent.
    from app.media.stills_stage import stills_plan
    from test_stills_stage import a_film

    _identifier, live, made = studio
    storyboard_id = a_film(engine, tmp_path)

    def crash(self, proof):
        raise RuntimeError("the process stopped here")

    monkeypatch.setattr(batch_module.BatchRun, "mark_unsent", crash)
    with pytest.raises(RuntimeError):
        approved_stills(engine, made, storyboard_id, tmp_path)
    assert all(t.failure_code == "RUNPOD.NOT_QUEUED" for t in still_takes(engine, storyboard_id))
    assert all(r.error_code == "SUBMISSION_UNCERTAIN" for r in jobs(engine))
    assert held(engine, storyboard_id) is None
    plan = stills_plan(engine, storyboard_id, model_id=made.model, table=stills_table())
    assert 1 in plan["to_buy"]
    # And no card is proposed for it: nothing holds the scene.
    from app.media.runpod_unsent import propose_release_cards

    assert propose_release_cards(engine, correlation_id=str(uuid4()))["cards"] == []


def test_the_watchdog_runs_the_release_pass(engine, tmp_path, recorded_gpu):
    from types import SimpleNamespace

    from app.workflows.watchdog import run_watchdog

    legacy_hold(engine, tmp_path, recorded_gpu)
    result = run_watchdog(
        engine,
        SimpleNamespace(media_root=tmp_path / "media"),
        correlation_id=str(uuid4()),
        collector_for=lambda take: None,
    )
    assert len(result["runpod_unsent_holds"]["cards"]) == 1
    assert len(open_cards(engine)) == 1


# -------------------------------------------------------------- «Refă imaginea» on RunPod


def redo_go(engine, made, storyboard_id, tmp_path, scene=1):
    from app.media.assembler import redo_plan, redo_scene
    from test_stills_stage import SpyJudge, faces_in

    table = stills_table()
    plan = redo_plan(engine, storyboard_id, "still", scene, table=table, stills_model=made.model)
    return plan, redo_scene(
        engine,
        storyboard_id,
        str(uuid4()),
        kind="still",
        scene_index=scene,
        plan_hash=plan["plan_hash"],
        image_adapter=made,
        table=table,
        storage_root=tmp_path / "media",
        judge=SpyJudge(),
        face_counter=faces_in(),
        measure=("faces",),
        integration_id=made.integration_id,
    )


def test_a_still_redo_on_runpod_is_one_gpu_round_under_his_yes(engine, tmp_path, recorded_gpu):
    from app.economy.models import ProviderCostRecord
    from app.media.assembler import SceneRedoRefused, redo_plan
    from test_approvals import answer
    from test_stills_stage import NO_FACE, a_film

    storyboard_id = a_film(engine, tmp_path)
    drawn = iter(NO_FACE * 4)  # two different pictures: the candidates are two files
    cloud = PictureCloud(lambda prompt: next(drawn).read_bytes())
    made = adapter(engine, tmp_path, cloud)
    plan = redo_plan(
        engine, storyboard_id, "still", 1, table=stills_table(), stills_model=made.model
    )
    # Its two pictures (2 x 7 credits) and its GPU start (14), each re-roll round the same.
    assert plan["credits"] == 2 * 7 + 14 and plan["cap_credits"] == 3 * (2 * 7 + 14)
    assert plan["round_overhead_credits"] == 14
    with pytest.raises(SceneRedoRefused) as asked:
        redo_go(engine, made, storyboard_id, tmp_path)
    assert asked.value.status == "NEEDS_APPROVAL"
    assert not cloud.calls and not recorded_gpu  # nothing sent, no GPU before his yes
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, refă imaginea.")
    _plan, result = redo_go(engine, made, storyboard_id, tmp_path)

    assert len(cloud.posts()) == 1
    items = cloud.jobs["job-1"]["input"]["items"]
    assert [item["scene_id"] for item in items] == ["1", "1"]
    assert len(recorded_gpu) == 1 and recorded_gpu[0]["closed"]
    assert recorded_gpu[0]["purpose"] == "image"
    still = result["still"]
    assert still["status"] == "APPROVED" and still["bought_images"] == 2
    assert still["spent_credits_quoted"] == 2 * 7 + 14
    with Session(engine) as s:
        booked = s.scalars(select(ProviderCostRecord)).all()
        assert [row.provider for row in booked] == ["runpod"]
        approval = s.get(ApprovalRequest, asked.value.approval_id)
        assert approval is not None and approval.consumed_at is not None
    takes = still_takes(engine, storyboard_id)
    assert sorted(t.status for t in takes) in (["APPROVED", "PAID"], ["APPROVED", "REJECTED"])
    assert still["take_id"] in {t.id for t in takes if t.status == "APPROVED"}
    assert all(t.remote_task_id.startswith("job-1:") for t in takes)


def test_a_still_redo_on_runpod_asks_nothing_while_the_gpu_may_not_switch_on(engine, tmp_path):
    from app.media.assembler import SceneRedoRefused
    from test_stills_stage import NO_FACE, a_film

    storyboard_id = a_film(engine, tmp_path)
    cloud = PictureCloud(lambda prompt: NO_FACE[0].read_bytes())
    made = adapter(engine, tmp_path, cloud)  # no connection that lets agents switch it on
    with pytest.raises(SceneRedoRefused) as refused:
        redo_go(engine, made, storyboard_id, tmp_path)
    assert refused.value.status == "BLOCKED_INFRA_DISABLED"
    assert not cloud.calls
    with Session(engine) as s:
        assert s.scalar(select(ApprovalRequest)) is None


def test_a_still_redo_round_runpod_never_queued_is_given_back_and_not_held(
    engine, tmp_path, studio
):
    from app.media.assembler import SceneRedoRefused
    from test_approvals import answer
    from test_stills_stage import a_film

    _identifier, live, made = studio
    storyboard_id = a_film(engine, tmp_path)
    with pytest.raises(SceneRedoRefused) as asked:
        redo_go(engine, made, storyboard_id, tmp_path)
    answer(engine, asked.value.approval_id, "APPROVED", note="Da.")
    _plan, result = redo_go(engine, made, storyboard_id, tmp_path)
    assert len(live.runs()) == 1
    assert result["still"]["status"] == "NOT_BOUGHT"
    assert result["still"]["spent_credits_quoted"] == 0
    assert events(engine, assembler.STILL_HOLD_EVENT) == []
    assert held(engine, storyboard_id) is None
    # The GPU was switched on for the redo and off right after, verified.
    (row,) = rows(engine)
    assert row.step == "scene_redo" and row.status == "CLOSED" and row.verified_off


def redo_proven(engine, tmp_path, made, live, storyboard_id) -> dict[str, Any]:
    """«Refă imaginea» on the held scene, approved; RunPod's /run unanswered again, and this
    time the GPU-off proves nothing was queued or made (the same keys go out again)."""
    from app.media.assembler import SceneRedoRefused
    from test_approvals import answer

    keys = {row.idempotency_key for row in jobs(engine)}
    live.removed = 0
    with pytest.raises(SceneRedoRefused) as asked:
        redo_go(engine, made, storyboard_id, tmp_path)
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, refă imaginea.")
    _plan, result = redo_go(engine, made, storyboard_id, tmp_path)
    assert result["still"]["status"] == "NOT_BOUGHT"
    assert {row.idempotency_key for row in jobs(engine)} == keys  # the same keys, sent again
    assert all(row.error_code == "UNSENT" for row in jobs(engine))
    return result


def test_a_held_scene_redone_and_proven_unsent_is_released_and_its_card_withdrawn(
    engine, tmp_path, studio
):
    # 2026-10-09 review: the redo sends the held scene's keys again; its proof covers the
    # earlier /run of those keys too (no claim, no manifest, nothing queued). Before, the card
    # was withdrawn while the hold stayed: the film stuck with no way out.
    from app.decisions.services import refresh_owner_decisions
    from app.media.runpod_unsent import propose_release_cards

    _identifier, live, made = studio
    live.removed = None  # the purge's answer carries no count: not proven
    storyboard_id = stuck_on_runpod(engine, tmp_path, made, live)
    (hold,) = events(engine, assembler.STILL_HOLD_EVENT)
    assert len(hold.payload[assembler.RUNPOD_HOLD_ITEMS]["job_row_ids"]) == 2
    assert len(propose_release_cards(engine, correlation_id=str(uuid4()))["cards"]) == 1
    (card,) = open_cards(engine)
    assert "Coada citită înainte de golire era goală." in card.why_ro
    assert "Răspunsul golirii cozii nu a spus câte lucrări a scos" in card.why_ro

    redo_proven(engine, tmp_path, made, live, storyboard_id)
    assert held(engine, storyboard_id) is None
    (released,) = events(engine, assembler.RUNPOD_UNSENT_RELEASED_EVENT)
    assert released.payload["released_event_id"] == hold.event_id
    assert released.payload["by"] == "proof"
    assert set(released.payload["rows"].values()) == {"PROVEN"}
    takes = still_takes(engine, storyboard_id)
    assert len(takes) == 4
    assert all(t.failure_code == "RUNPOD.NOT_QUEUED" and t.credits_quoted is None for t in takes)
    # His card's question has gone away because the hold was released, not before.
    assert refresh_owner_decisions(engine)["withdrawn"] == 1
    assert open_cards(engine) == []
    assert propose_release_cards(engine, correlation_id=str(uuid4())) == {
        "cards": [],
        "released": [],
    }


def test_a_redo_not_proven_either_keeps_the_held_scene_and_its_card(engine, tmp_path, studio):
    from app.decisions.services import refresh_owner_decisions
    from app.media.assembler import SceneRedoRefused
    from app.media.runpod_unsent import propose_release_cards
    from test_approvals import answer

    _identifier, live, made = studio
    live.removed = None
    storyboard_id = stuck_on_runpod(engine, tmp_path, made, live)
    propose_release_cards(engine, correlation_id=str(uuid4()))
    (card,) = open_cards(engine)
    with pytest.raises(SceneRedoRefused) as asked:
        redo_go(engine, made, storyboard_id, tmp_path)
    answer(engine, asked.value.approval_id, "APPROVED", note="Da.")
    _plan, result = redo_go(engine, made, storyboard_id, tmp_path)
    assert result["still"]["status"] == "NEEDS_OWNER"
    # The first card stays (its rows were sent again, never answered); the redo's hold has its
    # own, and nothing was booked unsent.
    assert refresh_owner_decisions(engine)["withdrawn"] == 0
    assert card.id in {c.id for c in open_cards(engine)}
    assert len(propose_release_cards(engine, correlation_id=str(uuid4()))["cards"]) == 1
    assert all(row.error_code == "SUBMISSION_UNCERTAIN" for row in jobs(engine))
    assert held(engine, storyboard_id)

    def accept(decision: OwnerDecision) -> None:
        decide_owner_decision(
            engine,
            decision.id,
            DecideCommand(
                command_id=uuid4(),
                expected_version=decision.version,
                decision="ACCEPT",
                option_key="release",
            ),
            issued_by="owner",
        )

    # His way out: the redo's card marks the rows it sent unsent; the first card, about the
    # first /run, still stands on its own record and releases its own hold.
    (redo_card,) = [c for c in open_cards(engine) if c.id != card.id]
    accept(redo_card)
    assert all(row.output["not_queued"]["by"] == "owner" for row in jobs(engine))
    assert held(engine, storyboard_id)  # the first hold is still in force
    assert refresh_owner_decisions(engine)["withdrawn"] == 0
    (first,) = open_cards(engine)
    assert first.id == card.id
    accept(first)
    assert held(engine, storyboard_id) is None
    assert len(events(engine, assembler.RUNPOD_UNSENT_RELEASED_EVENT)) == 2


def test_the_films_legacy_hold_redone_and_proven_unsent_is_released(
    engine, tmp_path, studio, monkeypatch
):
    # The film of 2026-10-09: its hold names no rows, its session kept no evidence and no
    # proof, its rows name no session. A redo that proves the same keys never queued releases
    # it all the same (the rows are found by the time they were reserved in that session).
    from app.media import stills_stage
    from app.media.runpod_unsent import propose_release_cards

    _identifier, live, made = studio
    live.removed = None
    monkeypatch.setattr(stills_stage, "runpod_hold_items", lambda refused: {})
    monkeypatch.setattr(batch_module, "PROOF_EVENT", "test.proof_not_kept_then")
    storyboard_id = stuck_on_runpod(engine, tmp_path, made, live)
    monkeypatch.setattr(stills_stage, "runpod_hold_items", assembler.runpod_hold_items)
    monkeypatch.setattr(batch_module, "PROOF_EVENT", "runpod.run_queue_proof")
    with Session(engine) as s, s.begin():
        (gpu,) = s.scalars(select(GpuSessionRow)).all()
        gpu.off_reading = {k: v for k, v in gpu.off_reading.items() if k != "evidence"}
        for row in s.scalars(select(GenerationJob)):
            row.gpu_session_id = None
    assert len(propose_release_cards(engine, correlation_id=str(uuid4()))["cards"]) == 1
    (card,) = open_cards(engine)
    assert "golirii cozii nu a fost înregistrat" in card.why_ro

    redo_proven(engine, tmp_path, made, live, storyboard_id)
    assert held(engine, storyboard_id) is None
    (released,) = events(engine, assembler.RUNPOD_UNSENT_RELEASED_EVENT)
    assert released.payload["by"] == "proof"
    for row in jobs(engine):
        assert row.output["resent"][0]["gpu_session_id"] is None


# ------------------------------------------------------------ the motion stairs, the same rule


def test_a_motion_round_runpod_never_queued_is_not_bought_and_not_held(engine, tmp_path, studio):
    from app.media.assembler import MotionStepRefused, motion_plan, run_motion_step
    from app.providers.runpod.adapters import RunPodVideoAdapter
    from test_approvals import answer
    from test_clip_qc_wiring import ScriptedCheck
    from test_film_costing import a_film
    from test_runpod_batch import motion_table, runpod_capability

    identifier, live, _stills = studio
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    made = RunPodVideoAdapter(
        config(
            **MIRROR,
            motion_mirror_repo="owner/amn-motion",
            motion_mirror_revision="b" * 40,
        ),
        engine,
        model="LTX-2.5",
        integration_id=identifier,
        storage_root=tmp_path,
    )
    made.core.transport = made.core.client.transport = live
    capability = runpod_capability()
    table = motion_table()

    def go():
        plan = motion_plan(engine, storyboard_id, capabilities=[capability], table=table)
        return run_motion_step(
            engine,
            storyboard_id,
            str(uuid4()),
            step="test_shot",
            plan_hash=plan["plan_hash"],
            adapter_for_model=lambda model: made if model == "LTX-2.5" else None,
            capabilities=[capability],
            table=table,
            storage_root=tmp_path / "media",
            clip_check=ScriptedCheck("PASSED"),
            integration_id=identifier,
        )

    with pytest.raises(MotionStepRefused) as asked:
        go()
    answer(engine, asked.value.approval_id, "APPROVED", note="Da.")
    result = go()
    assert len(live.runs()) == 1
    scene = {e["scene_index"]: e for e in result["scenes"]}[1]
    assert scene["status"] == "NOT_BOUGHT" and "nu a pus cererea la coadă" in scene["reason"]
    assert result["spent_credits_quoted"] == 0
    assert events(engine, assembler.MOTION_HOLD_EVENT) == []
    with Session(engine) as s:
        (take,) = s.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id, SceneTake.kind == "test_shot"
            )
        ).all()
        assert take.status == "REFUSED" and take.failure_code == "RUNPOD.NOT_QUEUED"
        assert take.credits_quoted is None
    for row in jobs(engine):
        assert row.error_code == "UNSENT" and row.cost_value == "0"
