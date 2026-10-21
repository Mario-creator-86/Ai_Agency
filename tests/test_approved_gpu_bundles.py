"""Prepared purchases retain their own guards and budgets; all cloud calls are faked."""

from types import SimpleNamespace

import pytest
from app.media.assembler import SpendMeter
from test_runpod_batch import (
    Cloud,
    adapter,
    finishing,
    request,
)
from test_runpod_batch import (
    fake_session as runpod_session_fixture,
)
from test_runpod_batch import proving_session as runpod_proving_fixture

fake_session = runpod_session_fixture
proving_session = runpod_proving_fixture


def work(engine, made, scene, meter, trace, *, cap=30, stopped=lambda: None):
    from app.media.prepared_batch import RoundWork
    from app.providers.runpod.gpu_session import StepPermit

    return RoundWork(
        engine=engine,
        adapter=made,
        permit=StepPermit(
            "media.scene_redo",
            "scene_redo",
            "film-1",
            f"plan-{scene}",
            "director",
            None,
            False,
            "c",
            None,
            0.3,
        ),
        purpose="image",
        first_round=[request(str(scene))],
        next_round=lambda outcomes: [],
        price_credits=lambda items: 5 + 10 * len(items),
        cap_left=lambda: cap - meter.committed,
        guard=None,
        stopped=stopped,
        on_submitted=lambda item: trace.append(("sent", item.request.scene_id)),
        on_outcome=lambda outcome: trace.append(("landed", outcome.item.request.scene_id)),
        meter=meter,
        sleep=lambda _: None,
    )


def test_all_purchases_are_prepared_before_one_gpu_bundle(engine, tmp_path, fake_session):
    from app.media.prepared_batch import run_prepared

    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.core.transport = made.core.client.transport = finishing(cloud)
    trace = []
    meters = [SpendMeter(), SpendMeter()]

    def purchase(scene, meter):
        trace.append(("reviewed", str(scene)))
        summary = yield work(engine, made, scene, meter, trace)
        trace.append(("settled", str(scene)))
        return summary

    results = run_prepared([purchase(1, meters[0]), purchase(2, meters[1])])
    assert all(not isinstance(result, BaseException) for result in results)
    assert trace[:2] == [("reviewed", "1"), ("reviewed", "2")]
    assert len(cloud.posts()) == 1
    assert len(cloud.jobs["job-1"]["input"]["items"]) == 2
    assert [meter.committed for meter in meters] == [12.5, 12.5]
    assert [meter.attempts for meter in meters] == [1, 1]


def test_one_scenes_cap_cannot_be_borrowed_from_another(engine, tmp_path, fake_session):
    from app.media.prepared_batch import run_prepared

    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.core.transport = made.core.client.transport = finishing(cloud)
    meters = [SpendMeter(), SpendMeter()]

    def purchase(scene, meter, cap):
        return (yield work(engine, made, scene, meter, [], cap=cap))

    run_prepared([purchase(1, meters[0], 14), purchase(2, meters[1], 100)])
    assert [i["scene_id"] for i in cloud.jobs["job-1"]["input"]["items"]] == ["2"]
    assert [meter.committed for meter in meters] == [0, 15]


def test_no_gpu_work_is_dispatched_after_a_stop(engine, tmp_path, fake_session):
    from app.media.prepared_batch import run_prepared

    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    meter = SpendMeter()

    def purchase():
        return (yield work(engine, made, 1, meter, [], stopped=lambda: "STOP"))

    run_prepared([purchase()])
    assert not cloud.posts()
    assert meter.committed == 0


def test_an_unsent_bundle_refunds_each_purchase(engine, tmp_path, fake_session):
    from app.media.prepared_batch import run_prepared
    from app.providers.media_http import MediaProviderError

    cloud = Cloud()
    cloud.run_answers = [MediaProviderError("slow down", http_status=429)]
    made = adapter(engine, tmp_path, cloud)
    meters = [SpendMeter(), SpendMeter()]

    def purchase(scene, meter):
        return (yield work(engine, made, scene, meter, []))

    results = run_prepared([purchase(1, meters[0]), purchase(2, meters[1])])
    assert all(isinstance(result, MediaProviderError) and result.unsent for result in results)
    assert [meter.committed for meter in meters] == [0, 0]
    assert [meter.attempts for meter in meters] == [0, 0]


def test_uncertain_submission_proven_unsent_refunds_all_members(engine, tmp_path, proving_session):
    from app.media.prepared_batch import run_prepared
    from app.providers.media_http import MediaProviderError

    cloud = Cloud()
    cloud.run_answers = [MediaProviderError("lost", unanswered=True)]
    made = adapter(engine, tmp_path, cloud)
    meters = [SpendMeter(), SpendMeter()]

    def purchase(scene, meter):
        return (yield work(engine, made, scene, meter, []))

    results = run_prepared([purchase(1, meters[0]), purchase(2, meters[1])])
    assert all(isinstance(result, dict) and result["unsent_proof"]["proven"] for result in results)
    assert [meter.committed for meter in meters] == [0, 0]


def test_partial_cancel_refunds_only_the_unmade_members_items(engine, tmp_path, fake_session):
    from app.media.prepared_batch import run_prepared

    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    stop = []

    def finish_one(host, method, path, headers, body=None, **kwargs):
        if method == "GET" and "/manifests/" in path and cloud.jobs:
            first = cloud.jobs["job-1"]["input"]["items"][0]
            if first["idempotency_key"] in path:
                cloud.finish("job-1", 0)
        return cloud(host, method, path, headers, body, **kwargs)

    made.core.transport = made.core.client.transport = finish_one
    meters = [SpendMeter(), SpendMeter()]

    def purchase(scene, meter):
        ready = work(engine, made, scene, meter, [], stopped=lambda: "STOP" if stop else None)
        if scene == 1:
            ready.on_outcome = lambda _outcome: stop.append(True)
        return (yield ready)

    results = run_prepared([purchase(1, meters[0]), purchase(2, meters[1])])
    assert all(isinstance(result, dict) for result in results)
    assert [meter.committed for meter in meters] == [12.5, 2.5]
    assert any("/cancel/job-1" in c[2] for c in cloud.calls)


def test_bundles_keep_film_identity_even_when_scene_numbers_match(engine, tmp_path, fake_session):
    from dataclasses import replace

    from app.media.prepared_batch import run_prepared

    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    made.core.transport = made.core.client.transport = finishing(cloud)
    seen = [[], []]
    meters = [SpendMeter(), SpendMeter()]

    def purchase(index, board):
        ready = work(engine, made, 1, meters[index], [])
        ready.first_round = [replace(ready.first_round[0], project_id=board)]
        ready.permit = replace(ready.permit, storyboard_id=board)
        ready.on_outcome = lambda outcome: seen[index].append(outcome.item.request.project_id)
        return (yield ready)

    results = run_prepared([purchase(0, "film-A"), purchase(1, "film-B")])
    assert all(isinstance(result, dict) for result in results)
    assert seen == [["film-A"], ["film-B"]]
    assert len(cloud.posts()) == 1
    assert [meter.committed for meter in meters] == [12.5, 12.5]


def test_gpu_kernel_checks_every_purchase_receipt(engine, monkeypatch):
    from dataclasses import replace

    from app.providers.runpod.gpu_session import StepPermit, _kernel

    checked = []

    def may_act(_session, action, **kwargs):
        checked.append((action, kwargs["subject"], kwargs["context"]["plan_hash"]))
        return {"allowed": kwargs["subject"] != "film-B", "status": "BLOCKED_MODE"}

    monkeypatch.setattr("app.services.may_act", may_act)
    a = StepPermit(
        "media.scene_redo",
        "scene_redo",
        "film-A",
        "plan-A",
        "director",
        None,
        False,
        "c",
        None,
        0.3,
    )
    b = replace(a, storyboard_id="film-B", plan_hash="plan-B")
    assert not _kernel(engine, replace(a, batch_permits=(b,)))["allowed"]
    assert checked == [("infra.gpu_on", "film-B", "plan-B")]


def test_flow_wrapper_preserves_the_existing_synchronous_api():
    from app.media.prepared_batch import flow_call, purchase_flow

    @purchase_flow
    def purchase(value):
        if False:
            yield
        return {"value": value}

    assert purchase(3) == {"value": 3}
    flow = flow_call(purchase, 4)
    with pytest.raises(StopIteration) as done:
        next(flow)
    assert done.value.value == {"value": 4}
    assert list(flow_call(lambda: SimpleNamespace(value=5))) == []


def test_interrupted_preparation_runs_purchase_cleanup_before_closing_the_flow(engine, tmp_path):
    from app.media.prepared_batch import run_prepared

    class Interrupted(BaseException):
        pass

    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    cleaned = []

    def prepared_purchase():
        try:
            yield work(engine, made, 1, SpendMeter(), [])
        except RuntimeError:
            cleaned.append("purchase error handler")
            raise
        finally:
            cleaned.append("lease released")

    def interrupted_purchase():
        if False:
            yield
        raise Interrupted()

    with pytest.raises(Interrupted):
        run_prepared([prepared_purchase(), interrupted_purchase()])
    assert cleaned == ["purchase error handler", "lease released"]
    assert not cloud.posts()


def test_two_real_still_redos_share_dispatch_and_settle_separate_holds(
    engine, tmp_path, fake_session, monkeypatch
):
    from app.economy.models import SpendReservation
    from app.media import gpu_batch
    from app.media.assembler import SceneRedoRefused, redo_plan, redo_scene
    from app.media.models import SceneTake
    from app.media.prepared_batch import flow_call, run_prepared
    from app.media.shooting_sheet import film_purchase_lease
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from test_approvals import answer
    from test_runpod_batch import PictureCloud, stills_table
    from test_scene_redo import coloured_clip, filmed
    from test_scene_redo_prompt_rewrite import compiled_film
    from test_stills_stage import NO_FACE, SpyJudge, faces_in

    monkeypatch.setattr(gpu_batch, "gpu_precheck", lambda *a, **kw: None)
    board, _clean = compiled_film(engine, tmp_path, stale=3)
    filmed(engine, board, tmp_path, coloured_clip(tmp_path, "navy"))
    drawn = []

    def picture(_prompt):
        drawn.append(1)
        return NO_FACE[len(drawn) % 2].read_bytes()

    cloud = PictureCloud(picture)
    made = adapter(engine, tmp_path, cloud)
    table = stills_table()
    plans = {
        scene: redo_plan(engine, board, "still", scene, table=table, stills_model=made.model)
        for scene in (2, 3)
    }

    def args(scene):
        return dict(
            kind="still",
            scene_index=scene,
            plan_hash=plans[scene]["plan_hash"],
            image_adapter=made,
            table=table,
            judge=SpyJudge(),
            face_counter=faces_in(),
            measure=("faces",),
            storage_root=tmp_path / "media",
        )

    for scene in plans:
        with pytest.raises(SceneRedoRefused) as asked:
            redo_scene(engine, board, f"ask-{scene}", **args(scene))
        assert asked.value.status == "NEEDS_APPROVAL"
        answer(engine, asked.value.approval_id, "APPROVED", note="Da.")
    assert not cloud.posts()
    with film_purchase_lease(engine, board, holder="bundle", step="scene_redo"):
        results = run_prepared(
            [flow_call(redo_scene, engine, board, "bundle", **args(scene)) for scene in plans]
        )
    assert all(isinstance(result, dict) for result in results), results
    assert len(fake_session) == 1 and fake_session[0]["closed"]
    assert len(cloud.posts()) == 1
    submitted = cloud.jobs["job-1"]["input"]["items"]
    assert [i["scene_id"] for i in submitted] == ["2", "2", "3", "3"]
    with Session(engine) as session:
        takes = session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == board, SceneTake.model_id == made.model
            )
        ).all()
        assert {t.scene_number for t in takes if t.status == "APPROVED"} == {2, 3}
        assert all(t.remote_task_id for t in takes)
        holds = session.scalars(
            select(SpendReservation).where(SpendReservation.correlation_id == board)
        ).all()
        assert len([hold for hold in holds if hold.status == "SETTLED"]) == 2
        assert not any(hold.status == "RESERVED" for hold in holds)
    assert sum(r["credits"] for r in results) > 0


def test_two_real_motion_redos_send_their_accepted_frames_in_one_bundle(
    engine, tmp_path, fake_session, monkeypatch
):
    from app.media import gpu_batch
    from app.media.assembler import SceneRedoRefused, redo_plan, redo_scene
    from app.media.prepared_batch import flow_call, run_prepared
    from app.media.shooting_sheet import film_purchase_lease
    from app.providers.runpod.adapters import RunPodVideoAdapter
    from test_approvals import answer
    from test_clip_qc_wiring import ScriptedCheck
    from test_film_costing import a_film
    from test_runpod_batch import finishing_video, motion_table, runpod_capability

    monkeypatch.setattr(gpu_batch, "gpu_precheck", lambda *a, **kw: None)
    board = a_film(engine, tmp_path, scenes=3)
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud, cls=RunPodVideoAdapter)
    made.core.transport = made.core.client.transport = finishing_video(cloud)
    table, caps = motion_table(), [runpod_capability()]
    plans = {
        scene: redo_plan(engine, board, "motion", scene, table=table, capabilities=caps)
        for scene in (2, 3)
    }

    def args(scene):
        return dict(
            kind="motion",
            scene_index=scene,
            plan_hash=plans[scene]["plan_hash"],
            adapter_for_model=lambda _: made,
            capabilities=caps,
            table=table,
            clip_check=ScriptedCheck("PASSED"),
            storage_root=tmp_path / "media",
        )

    for scene in plans:
        with pytest.raises(SceneRedoRefused) as asked:
            redo_scene(engine, board, f"ask-{scene}", **args(scene))
        assert asked.value.status == "NEEDS_APPROVAL"
        answer(engine, asked.value.approval_id, "APPROVED", note="Da.")
    with film_purchase_lease(engine, board, holder="bundle", step="scene_redo"):
        results = run_prepared(
            [flow_call(redo_scene, engine, board, "bundle", **args(scene)) for scene in plans]
        )
    assert all(isinstance(result, dict) for result in results), results
    assert len(fake_session) == 1 and fake_session[0]["closed"]
    assert len(cloud.posts()) == 1
    assert cloud.jobs["job-1"]["input"]["operation"] == "video"
    items = cloud.jobs["job-1"]["input"]["items"]
    assert [i["scene_id"] for i in items] == ["2", "3"]
    assert all(i["source_image"]["sha256"] for i in items)
    assert all(result["motion"]["bought_shots"] == 1 for result in results)
