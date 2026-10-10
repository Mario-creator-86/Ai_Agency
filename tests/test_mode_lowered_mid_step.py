"""A lowered mode stops a paid step before its next vendor request (spec 51, «Lowering autonomy»).

2026-10-04, 05:02 UTC: the day's stills step of the LHC film (storyboard 4d0da5d9) started under
AUTONOMOUS_CEO with the Owner's paid-media rule MODE. At 05:08:27 the mode was lowered to MANUAL
from the page. The step read only the autonomy stop between scenes, so scenes 4 to 9 were still
submitted (6 x 18 = 108 credits) under a mode that forbade them. 51_AUTONOMY_MODE_SEMANTICS.md
says lowering is «Immediate and safe» and that «active workflow external writes respect current
policy at execution time».

Now every paid loop (stills, the test shot and the motion, a redo's re-rolls) asks the Policy
Kernel's non-spending verdict (`may_act(..., ask_owner=False)`) before each request when it buys
unasked. What was bought is kept and settled; the rest is not bought, and the step says why. The
Owner's own press and a step bought on his yes for this plan go on as `may_act` would let them.
On the unasked path the sheet step asks the mode before it reads the balance, so MANUAL no
longer raises a «top up the account» card for a step the mode would refuse anyway.

Every provider is faked; no credit is spent.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.decisions.models import OwnerDecision
from app.media.assembler import SceneRedoRefused, motion_plan, redo_plan, redo_scene
from app.media.balance_rule import BALANCE_READ_EVENT
from app.media.models import SceneTake
from app.media.shooting_sheet import SheetStepRefused, build_sheet, run_sheet_step
from app.media.stills_stage import GATE_REVIEWER
from app.models import DomainEvent, OwnerPolicy
from app.schemas import AutonomyModeCommand
from app.services import change_autonomy_mode
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import SEEDANCE, Account, Models, SpyVideo, hero_approved
from test_film_costing import a_film as film_with_stills
from test_film_costing import run as run_motion
from test_scene_redo import filmed
from test_stills_stage import (
    FACE,
    SpyJudge,
    SpyStills,
    approved_run,
    faces_in,
)
from test_stills_stage import a_film as film_without_stills
from test_stills_stage import run as run_stills

STOPPED_EVENT = "media.paid_step_stopped_by_mode"


def mode_studio(engine) -> None:
    """AUTONOMOUS_CEO with the paid-media rule MODE: a paid step buys without asking him."""
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = False
        policy.autonomy_mode = "AUTONOMOUS_CEO"
        policy.paid_media_approval = "MODE"


def lower_mode(engine, mode: str = "MANUAL") -> None:
    """The Owner's press on the page's mode buttons: a versioned, recorded command."""
    with Session(engine) as session:
        version = session.get(OwnerPolicy, 1).version
    result = change_autonomy_mode(
        engine,
        AutonomyModeCommand(command_id=uuid4(), expected_version=version, autonomy_mode=mode),
    )
    assert result.status == "COMMITTED"


def studio_chosen(engine, storyboard_id: str, scene: int = 3) -> None:
    """The scene's still and clip as the stills gate and the clip QC approved them, with no
    hand of the Owner's (no decision of his, nobody's ``owner``): a redo nobody pressed is
    then refused by the mode, not by his choice (OWNER_APPROVED, 2026-10-10)."""
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == scene,
                SceneTake.status == "APPROVED",
            )
        ):
            row.approved_by = GATE_REVIEWER if row.kind == "still" else "clip_qc"


def stopped_events(engine) -> list[dict]:
    with Session(engine) as session:
        return [
            dict(row.payload)
            for row in session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == STOPPED_EVENT)
            )
        ]


def scene_takes(engine, storyboard_id: str, kind: str) -> list[SceneTake]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(SceneTake).where(
                    SceneTake.storyboard_id == storyboard_id, SceneTake.kind == kind
                )
            )
        )
        session.expunge_all()
        return rows


def lowers_at(call_number: int, engine, mode: str = "MANUAL"):
    """The image vendor's pictures, faked: two pictures with nobody in them, and the Owner
    lowers the mode while request ``call_number`` is at the vendor."""
    from test_stills_stage import NO_FACE

    def pictures(_prompt, call):
        if call == call_number:
            lower_mode(engine, mode)
        return list(NO_FACE)

    return pictures


# ---------------------------------------------------------------------- 1. the stills step


def test_a_mode_lowered_between_scene_3_and_scene_4_buys_nothing_more(engine, tmp_path):
    storyboard_id = film_without_stills(engine, tmp_path)
    mode_studio(engine)
    adapter = SpyStills(balance=5_000.0)
    adapter.pictures = lowers_at(3, engine)

    result = run_stills(engine, storyboard_id, tmp_path, adapter, SpyJudge())

    # Scenes 1-3 were bought before the mode changed; scene 4 never reached the vendor.
    assert len(adapter.asked) == 3
    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert [by_scene[n]["status"] for n in (1, 2, 3)] == ["APPROVED"] * 3
    assert by_scene[4]["status"] == "NOT_BOUGHT"
    said = result["stopped"]
    assert "modul de autonomie a fost coborât la manual" in said.lower()
    assert "restul nu s-a cumpărat" in said
    assert by_scene[4]["reason"] == said
    # What was bought is kept and settled: 3 requests x 2 pictures, measured on the balance.
    assert result["bought_images"] == 6
    assert result["spent_credits_measured"] == 54
    assert len(scene_takes(engine, storyboard_id, "still")) == 6
    (event,) = stopped_events(engine)
    assert event["step"] == "stills" and event["mode"] == "MANUAL"
    assert event["status"] == "BLOCKED_MODE"
    assert event["scene_number"] == 4
    assert event["mode_changed_sequence"] is not None


def test_the_owners_own_press_goes_on_through_a_lowered_mode(engine, tmp_path):
    storyboard_id = film_without_stills(engine, tmp_path)
    mode_studio(engine)
    adapter = SpyStills(balance=5_000.0)
    adapter.pictures = lowers_at(3, engine)

    result = run_stills(engine, storyboard_id, tmp_path, adapter, SpyJudge(), unasked=False)

    # OWNER_PRESS_PASSES: BLOCKED_MODE speaks about agents acting unasked, not about him.
    assert len(adapter.asked) == 4
    assert result["stopped"] is None
    assert stopped_events(engine) == []


def test_a_step_bought_on_his_yes_for_this_plan_is_not_stopped_by_manual(engine, tmp_path):
    """EVERY_PAID_STEP asks him in every mode, MANUAL included (`may_act`): the yes he gave
    for this plan is the answer MANUAL would have asked for, so the step goes on."""
    storyboard_id = film_without_stills(engine, tmp_path)
    adapter = SpyStills(balance=5_000.0)
    adapter.pictures = lowers_at(3, engine)

    approved_run(engine, storyboard_id, tmp_path, adapter, SpyJudge())

    assert len(adapter.asked) == 4
    assert stopped_events(engine) == []


def test_a_stricter_paid_media_rule_also_stops_the_unasked_step(engine, tmp_path):
    """Any change that makes the unasked purchase no longer allowed: here his rule."""
    storyboard_id = film_without_stills(engine, tmp_path)
    mode_studio(engine)
    adapter = SpyStills(balance=5_000.0)

    def pictures(_prompt, call):
        from test_stills_stage import NO_FACE

        if call == 2:
            with Session(engine) as session, session.begin():
                session.get(OwnerPolicy, 1).paid_media_approval = "EVERY_PAID_STEP"
        return list(NO_FACE)

    adapter.pictures = pictures
    result = run_stills(engine, storyboard_id, tmp_path, adapter, SpyJudge())

    assert len(adapter.asked) == 2
    assert result["stopped"]
    (event,) = stopped_events(engine)
    assert event["status"] == "NEEDS_APPROVAL"
    # The non-spending verdict asked nobody: no question was written for him mid-step.
    with Session(engine) as session:
        from app.models import ApprovalRequest

        assert session.scalars(select(ApprovalRequest)).all() == []


# ----------------------------------------------------------------- 2. the test shot, the motion


def test_a_mode_lowered_during_the_motion_buys_no_further_shot(engine, tmp_path):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=4)
    account = Account(50_000)
    hero_approved(
        engine, storyboard_id, tmp_path, Models(SpyVideo("seedance2_5", account)), account
    )
    mode_studio(engine)

    class Lowering(SpyVideo):
        async def create_generation(self, prompt, **kwargs):
            task = await super().create_generation(prompt, **kwargs)
            if len(self.asked) == 2:  # scene 3's shot is at the vendor
                lower_mode(engine)
            return task

    spy = Lowering("seedance2_5", account)
    models = Models(spy)
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    assert plan["steps"]["motion"]["to_buy"] == [2, 3, 4]

    result = run_motion(engine, storyboard_id, tmp_path, "motion", models, account)

    assert len(spy.asked) == 2, "a shot was POSTed after the mode was lowered"
    scenes = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert scenes[2]["status"] == "PAID" and scenes[3]["status"] == "PAID"
    assert scenes[4]["status"] == "NOT_BOUGHT"
    assert "restul nu s-a cumpărat" in result["stopped"]
    assert len(scene_takes(engine, storyboard_id, "motion")) == 2
    (event,) = stopped_events(engine)
    assert event["step"] == "motion" and event["scene_number"] == 4


# ----------------------------------------------------------------- 3. a redo's re-rolls


def test_a_mode_lowered_during_an_unasked_still_redo_buys_no_reroll(engine, tmp_path):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=4)
    filmed(engine, storyboard_id, tmp_path, b"clip")
    studio_chosen(engine, storyboard_id)
    mode_studio(engine)
    images = SpyStills(balance=1_000)

    def faces_then_lower(_prompt, call):
        # A face in both pictures: the stills gate asks for a re-roll; meanwhile the Owner
        # lowers the mode.
        if call == 1:
            lower_mode(engine)
        return [FACE, FACE]

    images.pictures = faces_then_lower
    plan = redo_plan(engine, storyboard_id, "still", 3)

    result = redo_scene(
        engine,
        storyboard_id,
        str(uuid4()),
        kind="still",
        scene_index=3,
        plan_hash=plan["plan_hash"],
        image_adapter=images,
        judge=SpyJudge(),
        face_counter=faces_in(),
        measure=("faces",),
        storage_root=tmp_path / "media",
        unasked=True,
    )

    assert len(images.asked) == 1, "a re-roll was bought after the mode was lowered"
    assert "restul nu s-a cumpărat" in result["still"]["reason"]
    (event,) = stopped_events(engine)
    assert event["step"] == "scene_redo"


# ------------------------------------------------- 4. the mode before the balance, unasked


def _sheet_step(engine, storyboard_id, account, tmp_path, *, unasked: bool):
    models = Models(SpyVideo("seedance2_5", account))
    plan_hash = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)[
        "sheet_hash"
    ]
    return run_sheet_step(
        engine,
        storyboard_id,
        "test_shot",
        plan_hash,
        correlation_id=str(uuid4()),
        capabilities=[SEEDANCE],
        account=account,
        adapter_for_model=models,
        storage_root=tmp_path / "media",
        unasked=unasked,
    )


def _low_balance_cards(engine) -> int:
    with Session(engine) as session:
        return len(
            session.scalars(select(OwnerDecision).where(OwnerDecision.kind == "low_balance")).all()
        )


def _balance_reads(engine) -> int:
    with Session(engine) as session:
        return len(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == BALANCE_READ_EVENT)
            ).all()
        )


def test_unasked_under_manual_the_mode_is_asked_before_the_balance(engine, tmp_path):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    mode_studio(engine)
    lower_mode(engine)
    account = Account(10)  # far below the test shot's price

    with pytest.raises(SheetStepRefused) as refused:
        _sheet_step(engine, storyboard_id, account, tmp_path, unasked=True)

    assert refused.value.status == "BLOCKED_MODE"
    assert account.reads == 0, "the balance was read for a step the mode refuses"
    assert _balance_reads(engine) == 0
    assert _low_balance_cards(engine) == 0


def test_his_own_press_keeps_the_balance_first(engine, tmp_path):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    mode_studio(engine)
    lower_mode(engine)
    account = Account(10)

    with pytest.raises(SheetStepRefused) as refused:
        _sheet_step(engine, storyboard_id, account, tmp_path, unasked=False)

    assert refused.value.status == "LOW_BALANCE"
    assert account.reads >= 1
    assert _low_balance_cards(engine) == 1


def test_unasked_under_every_paid_step_the_balance_still_comes_before_his_question(
    engine, tmp_path
):
    """The question is not a refusal: he is still not asked to buy what the account cannot pay."""
    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    account = Account(10)

    with pytest.raises(SheetStepRefused) as refused:
        _sheet_step(engine, storyboard_id, account, tmp_path, unasked=True)

    assert refused.value.status == "LOW_BALANCE"


def test_a_redo_asked_unasked_under_manual_is_refused_before_anything_is_bought(engine, tmp_path):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=4)
    filmed(engine, storyboard_id, tmp_path, b"clip")
    studio_chosen(engine, storyboard_id)
    mode_studio(engine)
    lower_mode(engine)
    images = SpyStills(balance=1_000)
    plan = redo_plan(engine, storyboard_id, "still", 3)

    with pytest.raises(SceneRedoRefused) as refused:
        redo_scene(
            engine,
            storyboard_id,
            str(uuid4()),
            kind="still",
            scene_index=3,
            plan_hash=plan["plan_hash"],
            image_adapter=images,
            judge=SpyJudge(),
            face_counter=faces_in(),
            measure=("faces",),
            storage_root=tmp_path / "media",
            unasked=True,
        )
    assert refused.value.status == "BLOCKED_MODE"
    assert images.asked == []


# ------------------------------------------------- 5. the day's staircase, as on 2026-10-04


def test_the_days_staircase_stops_its_stills_when_the_mode_is_lowered(
    engine, settings, tmp_path, monkeypatch
):
    """The 05:02 path: the day walks the film, the stills stair buys unasked under MODE, the
    Owner lowers the mode at scene 3; scene 4 is not bought, the stair's purchase is booked, and
    the film waits on his mode, not on a fault of its own."""
    from functools import partial

    from app.media import shooting_sheet, stills_stage
    from app.runbook import stages

    # The vision model and the face count, faked, as in every stills test.
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
    storyboard_id = film_without_stills(engine, tmp_path)
    mode_studio(engine)
    adapter = SpyStills(balance=5_000.0)
    adapter.pictures = lowers_at(3, engine)
    wiring = {
        "integration_id": None,
        "capabilities": [SEEDANCE],
        "image_adapter": adapter,
        "account": None,
        "adapter_for_model": Models(),
        "resolution": None,
        "storage_root": tmp_path / "media",
    }

    film = stages._film_staircase(
        engine, settings, None, storyboard_id, wiring, "TEST", str(uuid4())
    )

    assert len(adapter.asked) == 3
    assert film["status"] == "WAITING" and film["refusal"] == "BLOCKED_MODE"
    assert "restul nu s-a cumpărat" in film["reason"]
    (stair,) = film["bought"]
    assert stair["step"] == "stills" and stair["booked"]
    assert not stages._passed_over(film)
    (event,) = stopped_events(engine)
    assert event["unasked"] is True
