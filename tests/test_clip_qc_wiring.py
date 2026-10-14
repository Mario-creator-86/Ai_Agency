"""Clip QC is wired in: no clip reaches the film unchecked.

The clip checks (qc.check_clip, qc.qc_clip_with_retry, qc.require_chosen_fallbacks) existed
after the Nepal film but nothing called them, so a frozen clip, a hard cut or a face the
bible forbids could still be cut into a paid film. What is asserted here, with every provider
faked and 0 credits:

(a) every PAID take of the motion staircase (the hero test shot, the motion step, the motion
    redo) is checked; a failing clip is bought again ONCE on the same model with seed + 1 and a
    firmer motion prompt, only inside the approved cap (STOPPED_AT_CAP otherwise); each
    report is kept on its take and on the scene, and a failed take is REJECTED, never cut in;
(b) assembling from takes in PRODUCTION refuses a LIVE scene without an accepted clip, by
    name and before anything is spoken or encoded, unless the Owner chose LOCAL_MOVE for
    that scene on the sheet; the legacy render refuses the same way before its encode;
(c) the film books the measured spend of its steps once, so the QC letter shows credits
    instead of "necunoscut", and a film assembled again from the same takes books nothing;
(d) an office-serial scene composed from the Owner's fixed series look (source
    'series_look') is accepted by the stills step and the motion step like a model-written
    one; a factual film still needs the model's plan.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.media.assembler import (
    CLIP_QC_EVENT,
    ClipsNotAccepted,
    MotionStepRefused,
    TakesMissing,
    assemble_from_takes,
    assemble_video_job,
    decide_take,
    film_seed,
)
from app.media.models import SceneTake, Storyboard, StoryboardScene, VideoRenderJob
from app.media.production_policy import LOCAL_MOVE
from app.media.qc import ClipCheck, ClipReport
from app.media.qc_report import measured_spend
from app.media.shooting_sheet import set_scene_model
from app.media.toolchain import find_ffmpeg
from app.models import DomainEvent
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_approvals import answer
from test_film_costing import SEEDANCE, Account, Models, SpyVideo, a_film, approved, run, takes

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


# ----------------------------------------------------------------------------- the fakes


def a_report(scene: int, clip: Path | str, verdict: str) -> ClipReport:
    """A clip report as qc.check_clip writes it: PASSED, FAILED (measured), PANELS (measured,
    and the still it was animated from is at fault) or UNCHECKED."""
    if verdict == "PASSED":
        checks: tuple[ClipCheck, ...] = (
            ClipCheck("motion", "PASSED", False, 1.4, "YDIF mediu 1,40 peste prag"),
            ClipCheck("picture", "PASSED", False, None, "privit la 1080 px: «a river»"),
        )
    elif verdict == "FAILED":
        checks = (
            ClipCheck("motion", "FAILED", True, 0.01, "clipul aproape nu se mișcă"),
            ClipCheck("picture", "PASSED", False, None, "privit la 1080 px: «a river»"),
        )
    elif verdict == "PANELS":
        checks = (
            ClipCheck("motion", "PASSED", False, 1.4, "YDIF mediu 1,40 peste prag"),
            ClipCheck(
                "panels",
                "FAILED",
                True,
                0.338,
                "nu e o singură fotografie: cadrul first are o bandă plată pe toată lățimea, "
                "la mijloc, între două imagini (rândurile 159-320 din 480)",
            ),
            ClipCheck("picture", "PASSED", False, None, "privit la 1080 px: «a tunnel»"),
        )
    else:
        checks = (ClipCheck("picture", "NOT_RUN", True, None, "clipul nu a fost privit"),)
    blocks = tuple(f"Scena {scene}: {item.detail_ro}" for item in checks if item.blocking)
    return ClipReport(
        scene=scene,
        path=str(clip),
        checks=checks,
        passed=not blocks,
        blocks_ro=blocks,
        warnings_ro=(),
        unmeasured=tuple(i.code for i in checks if i.blocking and i.status == "NOT_RUN"),
        measured={"motion": {"mean_ydif": checks[0].value}},
        back_to_still=verdict == "PANELS",
    )


class ScriptedCheck:
    """qc.check_clip, faked: answers each clip with the next verdict (the last one repeats)."""

    def __init__(self, *verdicts: str):
        self.verdicts = list(verdicts) or ["PASSED"]
        self.calls: list[dict] = []

    def __call__(self, clip, **kwargs):
        self.calls.append({"clip": str(clip), **kwargs})
        verdict = self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]
        return a_report(int(kwargs["scene"]), clip, verdict)


def passing() -> ScriptedCheck:
    return ScriptedCheck("PASSED")


def events(engine, event_type: str, aggregate_id: str | None = None) -> list[DomainEvent]:
    with Session(engine) as session:
        query = select(DomainEvent).where(DomainEvent.event_type == event_type)
        if aggregate_id is not None:
            query = query.where(DomainEvent.aggregate_id == aggregate_id)
        rows = list(session.scalars(query.order_by(DomainEvent.sequence)))
        session.expunge_all()
        return rows


def shots(engine, storyboard_id: str) -> list[SceneTake]:
    return [t for t in takes(engine, storyboard_id) if t.kind in ("test_shot", "motion")]


def filmed_and_approved(engine, storyboard_id, tmp_path, models, account, **kwargs):
    """The hero test shot bought, approved by the Owner, then the rest of the motion."""
    approved(engine, storyboard_id, tmp_path, "test_shot", models, account, **kwargs)
    (hero,) = [t for t in shots(engine, storyboard_id) if t.status == "PAID"]
    decide_take(engine, hero.id, "APPROVED", decided_by="owner")
    approved(engine, storyboard_id, tmp_path, "motion", models, account, **kwargs)
    return hero


# ------------------------------------------- (a) every paid take is checked, one retry


def test_a_paid_shot_that_passes_carries_its_report_on_the_take_and_on_the_scene(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    check = passing()

    summary = approved(
        engine, storyboard_id, tmp_path, "test_shot", models, account, clip_check=check
    )

    assert models.posts() == 1
    (entry,) = summary["scenes"]
    assert entry["status"] == "PAID"
    assert entry["clip_qc"]["status"] == "PASSED" and entry["clip_qc"]["verdict"] == "PASSED"
    (call,) = check.calls
    # The check is asked what the scene asked for: its camera move, the bible's face rule.
    assert call["camera_move"] == "aerial drift forward"
    assert call["faces_forbidden"] is True
    (take,) = shots(engine, storyboard_id)
    assert take.status == "PAID" and take.id == entry["take_id"]
    (kept,) = events(engine, CLIP_QC_EVENT, take.id)
    assert kept.payload["verdict"] == "PASSED" and kept.payload["passed"] is True
    assert kept.payload["checks"][0]["code"] == "motion"


def test_a_failing_shot_waits_for_prompt_review_without_a_generic_retry(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    account = Account(10_000)
    spy = SpyVideo("seedance2_5", account)
    models = Models(spy)

    summary = approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=ScriptedCheck("FAILED", "PASSED"),
    )

    assert models.posts() == 1, "no purchase before review of replacement words"
    (first,) = spy.asked
    seed = film_seed(storyboard_id)
    assert first["extra"]["seed"] == seed
    (entry,) = summary["scenes"]
    assert entry["status"] == "NEEDS_OWNER"
    assert entry["clip_qc"]["status"] == "ESCALATED"
    assert entry["clip_qc"]["seeds"] == [seed]
    assert entry["clip_qc"]["retry_prompt"] is None
    by_seed = {t.seed: t for t in shots(engine, storyboard_id)}
    assert by_seed[seed].status == "REJECTED" and by_seed[seed].failure_code == "QC.CLIP"
    assert "nu se mișcă" in by_seed[seed].failure_detail
    assert entry["take_id"] == by_seed[seed].id
    assert summary["spent_credits_quoted"] == 340 <= summary["cap_credits"]


def test_a_shot_that_fails_is_held_for_the_director_and_is_never_assembled(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    summary = approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=ScriptedCheck("FAILED"),
    )

    assert models.posts() == 1
    (entry,) = summary["scenes"]
    assert entry["status"] == "NEEDS_OWNER" and entry["clip_qc"]["verdict"] == "FAILED"
    assert "Scena 1" in entry["reason"]
    assert summary["clip_qc_failed"] == [1]
    assert {t.status for t in shots(engine, storyboard_id)} == {"REJECTED"}
    (warning,) = events(engine, "media.motion_needs_owner", storyboard_id)
    assert warning.payload["scene_number"] == 1

    # In TEST the film is still made, the scene a still, and the scene says why.
    film = assemble_from_takes(
        engine, storyboard_id, str(uuid4()), storage_root=tmp_path / "media", environment="TEST"
    )
    (scene,) = film["production"]["scenes"]
    assert not scene["motion"].get("bytes")
    assert scene["motion"]["clip_qc"]["verdict"] == "FAILED"
    assert "controlul clipului" in scene["motion"]["refused"]

    # In PRODUCTION it is refused, by name, before anything is spoken or encoded.
    jobs_before = _jobs(engine)
    with pytest.raises(ClipsNotAccepted) as refused:
        assemble_from_takes(
            engine,
            storyboard_id,
            str(uuid4()),
            storage_root=tmp_path / "media_prod",
            environment="PRODUCTION",
        )
    assert isinstance(refused.value, TakesMissing)
    assert refused.value.scenes == [1]
    assert "Scena 1" in str(refused.value) and "controlul clipului" in str(refused.value)
    assert _jobs(engine) == jobs_before


def test_a_shot_animated_from_panels_is_not_bought_again_on_the_same_still(engine, tmp_path):
    """2026-10-09: scene 5's still was three stacked panels and its clip animated them. A seed
    + 1 on the same still animates the same panels, so nothing more is bought: the scene goes
    back to its still, rejected, with the reason."""
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    with Session(engine) as session, session.begin():
        # The gate's approval, not the Owner's: his look stays his (the test below).
        (still_row,) = session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id, SceneTake.kind == "still"
            )
        )
        still_row.approved_by = "still_gate"
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    summary = approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=ScriptedCheck("PANELS", "PASSED"),
    )

    assert models.posts() == 1, "the same still was animated again"
    (entry,) = summary["scenes"]
    # The picture is at fault: the scene needs a new still, not the Owner (2026-10-12, the
    # cyclotron's scene 1: the still stayed APPROVED and the next repair animated it again).
    assert entry["status"] == "NEEDS_STILL"
    assert entry["clip_qc"]["status"] == "BACK_TO_STILL"
    assert entry["clip_qc"]["verdict"] == "FAILED" and entry["clip_qc"]["retry_credits"] == 0
    assert "imagine nouă" in entry["reason"] and "singură fotografie" in entry["reason"]
    (take,) = shots(engine, storyboard_id)
    assert take.status == "REJECTED" and take.failure_code == "QC.CLIP"
    # The still went back to the stills gate, refused with the gate's code and the clip's reason.
    (still,) = takes(engine, storyboard_id, "still")
    assert still.status == "REJECTED" and still.failure_code == "LOCAL.STILL_GATE"
    assert "Controlul clipului" in still.failure_detail
    assert "singură fotografie" in still.failure_detail
    (sent_back,) = events(engine, "media.still_sent_back", still.id)
    assert sent_back.payload["failure_kind"] == "CLIP_QC"
    assert sent_back.payload["scene_number"] == 1


def test_a_still_the_owner_approved_is_not_sent_back_by_clip_qc(engine, tmp_path):
    """His look is his: a still he approved himself (`a_film`'s stills are his) stays APPROVED
    when its clip's fault is in the picture; the scene waits for him (NEEDS_OWNER) instead of
    buying a new still."""
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    summary = approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=ScriptedCheck("PANELS", "PASSED"),
    )

    (entry,) = summary["scenes"]
    assert entry["status"] == "NEEDS_OWNER"
    assert entry["clip_qc"]["status"] == "BACK_TO_STILL"
    (still,) = takes(engine, storyboard_id, "still")
    assert still.status == "APPROVED" and still.approved_by == "owner"
    assert events(engine, "media.still_sent_back", still.id) == []


def test_the_retry_is_not_bought_when_it_would_cross_the_approved_cap(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    summary = approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        cap_credits=340,
        clip_check=ScriptedCheck("FAILED", "PASSED"),
    )

    assert models.posts() == 1, "a retry was bought past the cap"
    assert summary["stopped"].startswith("STOPPED_AT_CAP")
    (entry,) = summary["scenes"]
    assert entry["status"] == "NEEDS_OWNER"
    assert "plafon" in entry["reason"]
    (take,) = shots(engine, storyboard_id)
    assert take.status == "REJECTED"


def test_an_unmeasured_shot_waits_for_the_owners_look_and_production_uses_it_only_then(
    engine, tmp_path
):
    """A clip nobody could look at is not thrown away (it was paid for) and not cut in either:
    it stays PAID and unchecked; in PRODUCTION only the Owner's approval accepts it."""
    from test_motion import a_clip

    storyboard_id = a_film(engine, tmp_path, scenes=1)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account, clip=a_clip(tmp_path)))

    summary = approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=ScriptedCheck("UNCHECKED"),
    )

    assert models.posts() == 1, "a retry cannot repair a check that could not run"
    (entry,) = summary["scenes"]
    assert entry["status"] == "PAID" and entry["clip_qc"]["verdict"] == "UNCHECKED"
    assert summary["clip_unchecked"] == [1]
    (take,) = shots(engine, storyboard_id)
    assert take.status == "PAID"
    with pytest.raises(ClipsNotAccepted, match="Scena 1"):
        assemble_from_takes(
            engine,
            storyboard_id,
            str(uuid4()),
            storage_root=tmp_path / "media",
            environment="PRODUCTION",
        )

    decide_take(engine, take.id, "APPROVED", decided_by="owner")
    film = assemble_from_takes(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        environment="PRODUCTION",
    )
    (scene,) = film["production"]["scenes"]
    assert scene["motion"]["take_id"] == take.id and scene["motion"]["reused_take"] is True
    assert scene["motion"]["clip_qc"]["verdict"] == "UNCHECKED"


def test_the_default_check_is_qc_check_clip_with_judge_clip_looking_at_its_frames(
    engine, tmp_path, monkeypatch
):
    from app.media import picture_qc, qc

    storyboard_id = a_film(engine, tmp_path, scenes=1)
    account = Account(10_000)
    spy = SpyVideo("seedance2_5", account)
    models = Models(spy)
    registry = object()
    looked: list[dict] = []
    checked: list[dict] = []

    def judge_clip(engine_, registry_, frames, plan, correlation_id, **kwargs):
        looked.append({"registry": registry_, "frames": list(frames), "plan": plan, **kwargs})
        return None

    def check_clip(clip, **kwargs):
        checked.append(kwargs)
        kwargs["judge"]([tmp_path / "first.png", tmp_path / "middle.png", tmp_path / "last.png"])
        return a_report(kwargs["scene"], clip, "PASSED")

    monkeypatch.setattr(picture_qc, "judge_clip", judge_clip)
    monkeypatch.setattr(qc, "check_clip", check_clip)

    approved(engine, storyboard_id, tmp_path, "test_shot", models, account, registry=registry)

    (call,) = checked
    assert call["environment"] == "TEST" and call["faces_forbidden"] is True
    (look,) = looked
    assert look["registry"] is registry and len(look["frames"]) == 3
    assert look["plan"].scene == 1 and look["plan"].faces_forbidden is True
    assert look["plan"].camera_move == "aerial drift forward"
    assert look["motion_prompt"] == spy.asked[0]["prompt"]


def test_the_motion_redo_checks_its_new_shot_and_requires_review_before_retry(engine, tmp_path):
    from app.media.assembler import redo_plan, redo_scene

    storyboard_id = a_film(engine, tmp_path, scenes=2)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    filmed_and_approved(engine, storyboard_id, tmp_path, models, account, clip_check=passing())
    posts = models.posts()

    plan = redo_plan(engine, storyboard_id, "motion", 2, capabilities=[SEEDANCE])

    def redo():
        return redo_scene(
            engine,
            storyboard_id,
            str(uuid4()),
            kind="motion",
            scene_index=2,
            plan_hash=plan["plan_hash"],
            capabilities=[SEEDANCE],
            adapter_for_model=models,
            account=account,
            storage_root=tmp_path / "media",
            clip_check=ScriptedCheck("FAILED", "PASSED"),
        )

    with pytest.raises(Exception) as asked:
        redo()
    answer(engine, asked.value.approval_id, "APPROVED")
    result = redo()

    assert models.posts() == posts + 1
    entry = {e["scene_index"]: e for e in result["motion"]["scenes"]}[2]
    assert entry["clip_qc"]["status"] == "ESCALATED"


# -------------------------------------- (b) no still in PRODUCTION without his choice


def _jobs(engine) -> int:
    with Session(engine) as session:
        return len(session.scalars(select(VideoRenderJob)).all())


def test_production_shows_a_scene_as_a_still_only_where_the_owner_chose_local_move(
    engine, tmp_path
):
    storyboard_id = a_film(engine, tmp_path, scenes=2)

    with pytest.raises(ClipsNotAccepted) as refused:
        assemble_from_takes(
            engine,
            storyboard_id,
            str(uuid4()),
            storage_root=tmp_path / "media",
            environment="PRODUCTION",
        )
    assert refused.value.scenes == [1, 2]
    assert "Scena 1" in str(refused.value) and "Scena 2" in str(refused.value)
    assert _jobs(engine) == 0, "a refused film started a render"

    for scene in (1, 2):
        set_scene_model(engine, storyboard_id, scene, LOCAL_MOVE, issued_by="owner")
    film = assemble_from_takes(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        environment="PRODUCTION",
    )

    assert Path(film["file_path"]).is_file()
    gate = film["production"]["fallback_gate"]
    assert gate["passed"] is True and gate["owner_chosen"] == [1, 2]


def test_the_legacy_render_in_production_refuses_an_unchosen_still_before_its_encode(
    engine, tmp_path
):
    from test_motion import StubImages, StubMotion, a_clip
    from test_phase5_media import _seeded_storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path)
    motion = StubMotion(a_clip(tmp_path), refuse={1})

    with pytest.raises(ClipsNotAccepted) as refused:
        assemble_video_job(
            engine,
            storyboard_id,
            str(uuid4()),
            storage_root=tmp_path / "media",
            image_adapter=StubImages(),
            video_adapter_for_scene=lambda scene: motion,
            environment="PRODUCTION",
        )

    assert refused.value.scenes == [1]
    with Session(engine) as session:
        (job,) = session.scalars(select(VideoRenderJob)).all()
        assert job.status == "FAILED" and job.output_asset_id is None
        assert "Scena 1" in job.execution_log
    assert not (tmp_path / "media" / storyboard_id / "final_short_9_16.mp4").exists()


# ------------------------------------------------- (c) the measured spend, booked once


def test_the_film_books_the_measured_spend_of_its_steps_once(engine, tmp_path):
    from app.media.qc_report import _credits_line

    storyboard_id = a_film(engine, tmp_path, scenes=2)
    # The stills step ran first: its own event carries the balance before and after.
    with Session(engine) as session, session.begin():
        from app.services import append_event

        append_event(
            session,
            "media.stills_step_finished",
            "storyboard",
            storyboard_id,
            1,
            {"storyboard_id": storyboard_id, "balance_before": 10_072.0, "balance_after": 10_000.0},
            str(uuid4()),
        )
    from test_motion import a_clip

    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account, clip=a_clip(tmp_path)))
    filmed_and_approved(engine, storyboard_id, tmp_path, models, account, clip_check=passing())

    film = assemble_from_takes(
        engine, storyboard_id, str(uuid4()), storage_root=tmp_path / "media", environment="TEST"
    )

    spend = film["production"]["credits_measured"]
    assert len(spend) == 3  # the stills step, the hero test shot, the motion step
    assert measured_spend(spend)["runway_credits"] == pytest.approx(72 + 340 + 340)
    with Session(engine) as session:
        job = session.get(VideoRenderJob, film["job_id"])
        assert measured_spend(job.production_json["credits_measured"])["runway_credits"] == 752
    line = _credits_line(spend)
    assert "necunoscut" not in line and "752" in line
    (booked,) = events(engine, "economy.credits_measured")
    assert booked.aggregate_id == film["job_id"] and len(booked.payload["measured"]) == 3

    # The same takes assembled again: the film still says what it cost, nothing is booked again.
    again = assemble_from_takes(
        engine, storyboard_id, str(uuid4()), storage_root=tmp_path / "again", environment="TEST"
    )
    assert measured_spend(again["production"]["credits_measured"])["runway_credits"] == 752
    assert len(events(engine, "economy.credits_measured")) == 1


# --------------------------------------------- (d) the office serial's fixed look


def sub(tmp_path: Path, name: str) -> Path:
    folder = tmp_path / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _serial(engine, storyboard_id: str, *, serial: bool) -> None:
    with Session(engine) as session, session.begin():
        board = session.get(Storyboard, storyboard_id)
        board.series_key = "office_serial" if serial else None
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        ):
            if row.scene_kind == "LIVE":
                row.prompt_json = {**dict(row.prompt_json or {}), "source": "series_look"}


def test_a_serial_scene_from_the_series_look_is_bought_like_a_model_scene(engine, tmp_path):
    from app.media.stills_stage import StillsStageRefused
    from test_stills_stage import SpyJudge, SpyStills
    from test_stills_stage import a_film as stills_film
    from test_stills_stage import run as stills_run

    serial = stills_film(engine, sub(tmp_path, "serial"))
    _serial(engine, serial, serial=True)
    with pytest.raises(StillsStageRefused) as asked:
        stills_run(engine, serial, tmp_path, SpyStills(), SpyJudge(), environment="PRODUCTION")
    assert asked.value.status == "NEEDS_APPROVAL", asked.value.reason_ro

    factual = stills_film(engine, sub(tmp_path, "factual"))
    _serial(engine, factual, serial=False)
    with pytest.raises(StillsStageRefused) as held:
        stills_run(engine, factual, tmp_path, SpyStills(), SpyJudge(), environment="PRODUCTION")
    assert held.value.status == "NEEDS_SHOT_PLAN"

    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    episode = a_film(engine, sub(tmp_path, "episode"), scenes=2)
    _serial(engine, episode, serial=True)
    with pytest.raises(MotionStepRefused) as motion_asked:
        run(engine, episode, tmp_path, "test_shot", models, account, environment="PRODUCTION")
    assert motion_asked.value.status == "NEEDS_APPROVAL", motion_asked.value.reason_ro

    documentary = a_film(engine, sub(tmp_path, "documentary"), scenes=2)
    _serial(engine, documentary, serial=False)
    with pytest.raises(MotionStepRefused) as motion_held:
        run(engine, documentary, tmp_path, "test_shot", models, account, environment="PRODUCTION")
    assert motion_held.value.status == "NEEDS_SHOT_PLAN"
    assert models.posts() == 0
