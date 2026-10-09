"""The Owner's own choice of a still the local check rejected may start a paid shot.

Film babcf272 (2026-10-09, «The Particle That Shouldn't Exist (But Does)»): scene 1's still was
REJECTED by the old local sharpness gate (LOCAL.STILL_GATE, since recalibrated). The Owner
looked at it and chose it himself (POST /media/takes/{id}/decision APPROVED); the take kept its
LOCAL.* code, and the motion plan held the scene as «păstrată doar pentru repetiție», so his
explicit choice could never be animated.

The rule now: a still carrying a failed local check (LOCAL.*) starts a paid shot only when the
Owner himself decided THAT take APPROVED after the failure was recorded, proven by his
`media.scene_take_decided` event for the take. The rehearsal's adoption (which may write
``approved_by="owner"`` on the row) never lifts the hold, a decision made before a later
failure does not, and neither does a rejection. The plan, the sheet and the step agree.

Every provider is faked (test_film_costing's spies); no socket is opened.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.media.assembler import (
    TAKE_DECIDED_EVENT,
    MotionStepRefused,
    SceneRedoRefused,
    decide_take,
    motion_plan,
    owner_chose_flagged_still,
    redo_plan,
)
from app.media.models import SceneTake
from app.media.rehearsal import OWNER, REHEARSAL_ONLY, _upsert_take
from app.media.shooting_sheet import build_sheet
from app.media.toolchain import find_ffmpeg
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import (
    SEEDANCE,
    Account,
    Models,
    SpyVideo,
    a_film,
    approved,
    by_scene,
    run,
    takes,
)

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")

GATE_CODE = "LOCAL.STILL_GATE"


def still_of(engine, storyboard_id: str, scene: int = 1) -> SceneTake:
    with Session(engine) as session:
        row = session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == scene,
                SceneTake.kind == "still",
            )
        ).one()
        session.expunge(row)
        return row


def gate_rejected(engine, storyboard_id: str, scene: int = 1) -> str:
    """The scene's still as the stills gate left it (`stills_stage._set_verdicts`): REJECTED
    with LOCAL.STILL_GATE, nobody's approval on it."""
    with Session(engine) as session, session.begin():
        row = session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == scene,
                SceneTake.kind == "still",
            )
        ).one()
        row.status = "REJECTED"
        row.approved_by = None
        row.failure_code = GATE_CODE
        row.failure_detail = "Imaginea nu este destul de clară (claritate 41, pragul 60)."
        return row.id


def adopted_again(engine, storyboard_id: str, take_id: str, code: str = "LOCAL.FACES") -> None:
    """The rehearsal's adoption of the same file, kept 'doar pentru repetiție' (the plan
    `rehearsal._still_take` writes with keep_flagged), through `rehearsal._upsert_take`."""
    row = still_of(engine, storyboard_id)
    plan = {
        "kind": "still",
        "scene": row.scene_number,
        "path": row.path,
        "sha256": row.sha256,
        "model_id": row.model_id,
        "resolution": row.resolution,
        "seconds": None,
        "prompt_hash": row.prompt_hash,
        "status": "APPROVED",
        "approved_by": OWNER + REHEARSAL_ONLY,
        "failure_code": code,
        "failure_detail": "YuNet a găsit 1 față.",
    }
    with Session(engine) as session, session.begin():
        assert _upsert_take(session, storyboard_id, plan, str(uuid4()), utc_now()) == take_id


def scene_of(plan: dict, index: int) -> dict:
    return next(item for item in plan["scenes"] if item["scene_index"] == index)


def assert_held(engine, storyboard_id: str, tmp_path) -> None:
    """Scene 1 (the film's only scene) is in no purchase: not in the plan, not on the sheet,
    and the step neither asks the Owner about it nor buys it."""
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    item = scene_of(plan, 1)
    assert item["status"] == "NEEDS_STILL", item
    assert 1 not in plan["steps"]["test_shot"]["to_buy"]
    assert 1 not in plan["steps"]["motion"]["to_buy"]
    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    assert 1 not in sheet["steps"]["test_shot"]["to_buy"]
    assert 1 not in sheet["steps"]["motion"]["to_buy"]
    assert sheet["scenes"][0]["motion"]["step_status"] == "NEEDS_STILL"
    # «Refă mișcarea» prices nothing for it either.
    with pytest.raises(SceneRedoRefused) as redo:
        redo_plan(engine, storyboard_id, "motion", 1, capabilities=[SEEDANCE])
    assert redo.value.status == "NEEDS_STILL"
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    try:
        run(engine, storyboard_id, tmp_path, "test_shot", models, account)
    except MotionStepRefused as refused:
        assert refused.status != "NEEDS_APPROVAL", "a question was raised for a held scene"
    assert models.posts() == 0


def test_his_choice_of_a_still_the_local_gate_rejected_starts_its_paid_shot(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    take_id = gate_rejected(engine, storyboard_id)
    assert_held(engine, storyboard_id, tmp_path)

    decide_take(engine, take_id, "APPROVED", decided_by="owner", note="O aleg eu.")

    chosen = still_of(engine, storyboard_id)
    # As in the live film: his approval leaves the gate's code on the take.
    assert (chosen.status, chosen.approved_by, chosen.failure_code) == (
        "APPROVED",
        "owner",
        GATE_CODE,
    )
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    item = scene_of(plan, 1)
    assert item["status"] == "PLANNED", item
    assert item["still_take_id"] == take_id and item["still_sha256"] == chosen.sha256
    assert "repetiț" not in item["reason_ro"]
    assert plan["steps"]["test_shot"]["to_buy"] == [1]
    assert plan["steps"]["test_shot"]["cost_credits"] == 340

    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    assert sheet["steps"]["test_shot"]["to_buy"] == [1]
    assert sheet["steps"]["test_shot"]["cost_credits"] == 340
    assert sheet["scenes"][0]["still"]["take_id"] == take_id
    assert sheet["scenes"][0]["motion"]["step_status"] == "PLANNED"
    redo = redo_plan(engine, storyboard_id, "motion", 1, capabilities=[SEEDANCE])
    assert redo["buyable"] is True and redo["credits"] == 340
    assert redo["still_sha256"] == chosen.sha256

    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    result = approved(engine, storyboard_id, tmp_path, "test_shot", models, account)

    assert models.posts() == 1
    assert by_scene(result)[1]["status"] == "PAID"
    assert [take.scene_number for take in takes(engine, storyboard_id, "test_shot")] == [1]


def test_the_rehearsals_adoption_alone_never_lifts_the_hold(engine, tmp_path):
    """The adoption keeps an earlier 'owner' on the row (the Owner's full approval is never
    narrowed): approved_by says 'owner', yet no decision of his names the take."""
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    take_id = still_of(engine, storyboard_id).id

    adopted_again(engine, storyboard_id, take_id)

    row = still_of(engine, storyboard_id)
    assert (row.status, row.approved_by, row.failure_code) == ("APPROVED", "owner", "LOCAL.FACES")
    assert_held(engine, storyboard_id, tmp_path)
    reason = scene_of(motion_plan(engine, storyboard_id, capabilities=[SEEDANCE]), 1)["reason_ro"]
    assert "repetiț" in reason and "LOCAL.FACES" in reason


def test_his_decision_before_a_later_failure_does_not_lift_it(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    take_id = gate_rejected(engine, storyboard_id)
    decide_take(engine, take_id, "APPROVED", decided_by="owner")
    first = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    assert scene_of(first, 1)["status"] == "PLANNED"

    # The take is recorded again afterwards with a failed local check: his look came first.
    adopted_again(engine, storyboard_id, take_id)

    assert still_of(engine, storyboard_id).failure_code == "LOCAL.FACES"
    assert_held(engine, storyboard_id, tmp_path)

    # His look at it now, after the failure, is the decision the scene waits for.
    decide_take(engine, take_id, "APPROVED", decided_by="owner", note="Tot pe aceasta.")
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    assert scene_of(plan, 1)["status"] == "PLANNED"
    assert plan["steps"]["test_shot"]["to_buy"] == [1]


def test_his_rejection_never_lifts_it(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    take_id = gate_rejected(engine, storyboard_id)

    decide_take(engine, take_id, "REJECTED", decided_by="owner", note="Nu.")

    assert still_of(engine, storyboard_id).status == "REJECTED"
    assert_held(engine, storyboard_id, tmp_path)


def test_only_his_newest_decision_counts_and_only_an_approval(engine, tmp_path):
    """The rule itself, on an APPROVED still kept with a LOCAL.* code: his newest decision on
    THAT take must be APPROVED; a rejection after an approval holds it, and a decision about
    another take proves nothing."""
    storyboard_id = a_film(engine, tmp_path, scenes=2)
    take_id = still_of(engine, storyboard_id).id
    other_id = still_of(engine, storyboard_id, scene=2).id
    adopted_again(engine, storyboard_id, take_id)

    def decided(aggregate_id: str, decision: str) -> None:
        with Session(engine) as session, session.begin():
            append_event(
                session,
                TAKE_DECIDED_EVENT,
                "scene_take",
                aggregate_id,
                1,
                {"scene_number": 1, "kind": "still", "decision": decision, "decided_by": "owner"},
                str(uuid4()),
            )

    def lifted() -> bool:
        with Session(engine) as session:
            return owner_chose_flagged_still(session, session.get(SceneTake, take_id))

    assert lifted() is False
    decided(other_id, "APPROVED")
    assert lifted() is False, "another take's approval lifted this one"
    decided(take_id, "REJECTED")
    assert lifted() is False
    decided(take_id, "APPROVED")
    assert lifted() is True
    decided(take_id, "REJECTED")
    assert lifted() is False, "an approval he took back still counted"
