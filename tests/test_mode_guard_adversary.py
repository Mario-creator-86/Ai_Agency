"""The 2026-10-04 mode guard, attacked on money (spec 51, «Lowering autonomy»).

What a lowered mode must stop and what it must leave alone: SUPERVISED stops an unasked T3
motion step and asks nobody, but lets the T2 stills go on; a mode lowered and raised inside one
request reads the policy of the moment; STOP wins over the mode; a vendor 400 that is the
model's real contract still holds the scene; a failed write of the stop's record after a
purchase is HARD (never retried, never bought again); the next film under MANUAL raises no
low-balance card; a hold released by several passes at once is released once; and the
everyday paths (SUPERVISED motion on his yes, MANUAL stills on his yes) still buy everything.

Every provider is faked; no credit is spent.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.media import mode_guard
from app.media.assembler import SpentStageError, motion_plan
from app.media.production_policy import classify_failure
from app.media.shooting_sheet import build_sheet, run_sheet_step
from app.models import ApprovalRequest, OwnerPolicy
from app.runbook.services import classify_fault
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_film_costing import SEEDANCE, Account, Models, SpyVideo, hero_approved
from test_film_costing import a_film as film_with_stills
from test_film_costing import run as run_motion
from test_mode_lowered_mid_step import lower_mode, lowers_at, mode_studio, stopped_events
from test_stills_stage import SpyJudge, SpyStills, faces_in
from test_stills_stage import a_film as film_without_stills
from test_stills_stage import run as run_stills


def test_supervised_stops_unasked_motion_t3_and_asks_nobody(engine, tmp_path):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=4)
    account = Account(50_000)
    hero_approved(
        engine, storyboard_id, tmp_path, Models(SpyVideo("seedance2_5", account)), account
    )
    mode_studio(engine)
    with Session(engine) as session:
        asked_before = len(session.scalars(select(ApprovalRequest)).all())

    class Lowering(SpyVideo):
        async def create_generation(self, prompt, **kwargs):
            task = await super().create_generation(prompt, **kwargs)
            if len(self.asked) == 1:
                lower_mode(engine, "SUPERVISED")
            return task

    spy = Lowering("seedance2_5", account)
    result = run_motion(engine, storyboard_id, tmp_path, "motion", Models(spy), account)

    assert len(spy.asked) == 1
    (event,) = stopped_events(engine)
    assert event["status"] == "NEEDS_APPROVAL" and event["mode"] == "SUPERVISED"
    assert "supravegheat" in result["stopped"].lower()
    with Session(engine) as session:
        assert len(session.scalars(select(ApprovalRequest)).all()) == asked_before


def test_supervised_keeps_unasked_t2_stills_going(engine, tmp_path):
    storyboard_id = film_without_stills(engine, tmp_path)
    mode_studio(engine)
    adapter = SpyStills(balance=5_000.0)
    adapter.pictures = lowers_at(2, engine, "SUPERVISED")
    result = run_stills(engine, storyboard_id, tmp_path, adapter, SpyJudge())
    assert result["stopped"] is None
    assert stopped_events(engine) == []
    assert len(adapter.asked) > 2


def test_lowered_then_raised_inside_one_request_reads_the_policy_of_now(engine, tmp_path):
    storyboard_id = film_without_stills(engine, tmp_path)
    mode_studio(engine)
    adapter = SpyStills(balance=5_000.0)
    from test_stills_stage import NO_FACE

    def pictures(_prompt, call):
        if call == 2:
            lower_mode(engine, "MANUAL")
            lower_mode(engine, "AUTONOMOUS_CEO")  # a promotion, allowed with no stop open
        return list(NO_FACE)

    adapter.pictures = pictures
    result = run_stills(engine, storyboard_id, tmp_path, adapter, SpyJudge())
    assert result["stopped"] is None
    assert stopped_events(engine) == []


def test_stop_and_lowered_mode_together_buy_nothing_more(engine, tmp_path):
    storyboard_id = film_without_stills(engine, tmp_path)
    mode_studio(engine)
    adapter = SpyStills(balance=5_000.0)
    from test_stills_stage import NO_FACE

    def pictures(_prompt, call):
        if call == 2:
            lower_mode(engine, "MANUAL")
            with Session(engine) as session, session.begin():
                session.get(OwnerPolicy, 1).autonomy_stopped = True
        return list(NO_FACE)

    adapter.pictures = pictures
    result = run_stills(engine, storyboard_id, tmp_path, adapter, SpyJudge())
    assert len(adapter.asked) == 2
    assert "oprit autonomia" in result["stopped"]


def test_a_real_vendor_contract_400_still_holds_the_scene():
    for detail in (
        "Validation of body failed; duration: must be one of 5, 10",
        "duration must be 5 or 10 seconds for this model",
        "ratio must use one of `1280:720`, `720:1280`",
        "The model gen4_turbo does not support 1080p",
    ):
        verdict = classify_failure("HTTP_400", http_status=400, detail=detail)
        assert verdict.kind == "CONTRACT", detail
        assert verdict.blame_model is True or verdict.move_scene, detail


def test_a_failed_stop_record_after_purchases_is_hard_and_never_rebought(
    engine, tmp_path, monkeypatch
):
    """The busy database at the guard's own write: what was bought is booked, the step is
    HARD (never retried by the runbook), and nothing is bought again."""
    from functools import partial

    from app.media import shooting_sheet, stills_stage

    monkeypatch.setattr(
        shooting_sheet,
        "run_stills_stage",
        partial(
            stills_stage.run_stills_stage,
            judge=SpyJudge(),
            face_counter=faces_in(),
            measure=("faces",),
        ),
    )

    def busy(self):
        raise OperationalError("INSERT", {}, Exception("database is locked"))

    monkeypatch.setattr(mode_guard.PurchaseGuard, "_record", busy)
    storyboard_id = film_without_stills(engine, tmp_path)
    mode_studio(engine)
    adapter = SpyStills(balance=5_000.0)
    adapter.pictures = lowers_at(2, engine)
    plan_hash = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)[
        "sheet_hash"
    ]
    with pytest.raises(SpentStageError) as raised:
        run_sheet_step(
            engine,
            storyboard_id,
            "stills",
            plan_hash,
            correlation_id=str(uuid4()),
            capabilities=[SEEDANCE],
            image_adapter=adapter,
            adapter_for_model=Models(),
            storage_root=tmp_path / "media",
            unasked=True,
        )
    assert len(adapter.asked) == 2
    assert isinstance(raised.value, SpentStageError)
    assert classify_fault(raised.value) == "HARD"


def test_the_next_film_after_a_lowered_mode_reads_no_balance(engine, settings, tmp_path):
    from app.runbook import stages

    first = film_with_stills(engine, tmp_path, scenes=3)
    mode_studio(engine)
    lower_mode(engine)
    account = Account(10)
    spy = SpyVideo("seedance2_5", account)
    wiring = {
        "integration_id": None,
        "capabilities": [SEEDANCE],
        "image_adapter": SpyStills(balance=10.0),
        "account": account,
        "adapter_for_model": Models(spy),
        "resolution": None,
        "storage_root": tmp_path / "media",
    }
    assert motion_plan(engine, first, capabilities=[SEEDANCE])["steps"]["test_shot"]["to_buy"]
    film = stages._film_staircase(engine, settings, None, first, wiring, "TEST", str(uuid4()))
    assert film["refusal"] == "BLOCKED_MODE", film
    assert spy.asked == []
    # The sheet itself shows the live balance (a free GET): no card, no reading booked.
    from app.decisions.models import OwnerDecision
    from app.media.balance_rule import BALANCE_READ_EVENT
    from app.models import DomainEvent

    with Session(engine) as session:
        assert (
            session.scalars(select(OwnerDecision).where(OwnerDecision.kind == "low_balance")).all()
            == []
        )
        assert (
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == BALANCE_READ_EVENT)
            ).all()
            == []
        )
    assert account.reads <= 1
    assert not stages._passed_over(film)


def test_under_manual_his_yes_buys_the_whole_step_unasked_too(engine, tmp_path):
    """MANUAL + EVERY_PAID_STEP: his press asks, his yes buys (also when the day carries it)."""
    from test_stills_stage import approved_run

    storyboard_id = film_without_stills(engine, tmp_path)
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = False
        policy.autonomy_mode = "MANUAL"
        policy.paid_media_approval = "EVERY_PAID_STEP"
    adapter = SpyStills(balance=5_000.0)
    result = approved_run(engine, storyboard_id, tmp_path, adapter, SpyJudge(), unasked=True)
    assert result["stopped"] is None
    assert stopped_events(engine) == []
    assert len(adapter.asked) >= 4


def test_a_release_pass_twice_and_concurrently_writes_one_event(engine, tmp_path):
    import threading

    from app.media.assembler import (
        MOTION_HOLD_EVENT,
        STUDIO_DEFECT_RELEASED_EVENT,
        release_studio_defect_holds,
    )
    from app.media.stills_stage import record_take
    from app.models import DomainEvent
    from app.services import append_event
    from test_studio_defect_refusal import KEYFRAME

    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    record_take(
        engine,
        storyboard_id=storyboard_id,
        scene_number=1,
        kind="test_shot",
        prompt_hash="h",
        model_id="wan3",
        resolution="1080:1920",
        status="REFUSED",
        correlation_id=str(uuid4()),
        failure_code="HTTP_400",
        failure_detail=KEYFRAME,
    )
    with Session(engine) as session, session.begin():
        append_event(
            session,
            MOTION_HOLD_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {"scene_number": 1, "failure_kind": "CONTRACT", "status": "NEEDS_OWNER"},
            str(uuid4()),
        )
    errors: list[BaseException] = []

    def go():
        try:
            release_studio_defect_holds(engine, correlation_id=str(uuid4()))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    release_studio_defect_holds(engine, correlation_id=str(uuid4()))
    assert errors == []
    with Session(engine) as session:
        rows = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == STUDIO_DEFECT_RELEASED_EVENT)
        ).all()
    assert len(rows) == 1


def test_supervised_motion_on_his_yes_buys_every_shot(engine, tmp_path):
    """The everyday path must not break: SUPERVISED + MODE, his yes, every shot bought."""
    from test_film_costing import approved

    storyboard_id = film_with_stills(engine, tmp_path, scenes=4)
    account = Account(50_000)
    hero_approved(
        engine, storyboard_id, tmp_path, Models(SpyVideo("seedance2_5", account)), account
    )
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = False
        policy.autonomy_mode = "SUPERVISED"
        policy.paid_media_approval = "MODE"
    spy = SpyVideo("seedance2_5", account)
    result = approved(engine, storyboard_id, tmp_path, "motion", Models(spy), account)
    assert len(spy.asked) == 3
    assert result["stopped"] is None
    assert stopped_events(engine) == []
