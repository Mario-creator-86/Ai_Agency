"""Adversary, 2026-10-01: a bad film cannot be bought, end to end, with the REAL clip checks.

The wiring tests (test_clip_qc_wiring.py) script the clip check's verdict. Here the studio's own
qc.check_clip measures what the faked vendor delivered, so what is asserted is what the Owner's
next paid film would meet: a frozen clip on a moving shot and a clip showing a face the bible
forbids are measured wrong, bought again at most once inside the cap, REJECTED, and never
assembled into a PRODUCTION film; and a question he answers after the plan changed buys
nothing. Every provider is faked; 0 credits.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from app.media.assembler import ClipsNotAccepted, MotionStepRefused, assemble_from_takes
from app.media.faces import detector_available
from app.media.models import VideoRenderJob
from app.media.picture_qc import ClipJudgement, ClipVerdict
from app.media.shooting_sheet import SCENE_MODEL_EVENT, set_scene_model
from app.models import DomainEvent
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_approvals import answer
from test_film_costing import SEEDANCE, VEO_FAST, Account, Models, SpyVideo, a_film, approved, run

FFMPEG = shutil.which("ffmpeg")
FIXTURES = Path(__file__).parent / "fixtures" / "nepal_1d530880"
requires_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")
requires_yunet = pytest.mark.skipif(
    not detector_available(), reason="the YuNet detector is not installed"
)


def _vendor_clip(work: Path, picture: str) -> bytes:
    """Five seconds of a real Nepal picture, held still: 1080x1920, 24 fps, H.264."""
    out = work / f"held_{picture}.mp4"
    subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-nostdin", "-y", "-threads", "2",
            "-loop", "1", "-i", str(FIXTURES / picture),
            "-vf", "scale=1080:1920:flags=lanczos,fps=24", "-frames:v", "120",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
            str(out),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return out.read_bytes()


def _judge_says_keep(_scene: int, frames: list[Path]) -> ClipJudgement:
    """The vision model, faked as a lenient one: it keeps whatever it is shown."""
    assert len(frames) == 3
    return ClipJudgement(
        status="MEASURED",
        verdict=ClipVerdict(
            scene=1,
            faces_visible=False,
            readable_text=False,
            matches_plan=True,
            look_ok=True,
            technical_ok=True,
            same_shot=True,
            bible_violations="none",
            verdict="keep",
            reason="looks fine",
        ),
        detail_ro="arată bine",
        run_id="run",
        looked_by="VideoEditor",
        image_width=1080,
        frames=3,
    )


def _no_faces(_path, **_kwargs):
    from app.media.faces import FaceCount

    return FaceCount(status="MEASURED", faces=0, boxes=(), detail_ro="YuNet a găsit 0 fețe")


def _jobs(engine) -> int:
    with Session(engine) as session:
        return len(session.scalars(select(VideoRenderJob)).all())


def _never_in_production(engine, storyboard_id: str, tmp_path: Path) -> None:
    jobs = _jobs(engine)
    with pytest.raises(ClipsNotAccepted) as refused:
        assemble_from_takes(
            engine,
            storyboard_id,
            str(uuid4()),
            storage_root=tmp_path / "prod",
            environment="PRODUCTION",
        )
    assert refused.value.scenes == [1]
    assert _jobs(engine) == jobs, "a refused film started a render"


@requires_ffmpeg
def test_a_frozen_clip_on_an_aerial_drift_is_measured_wrong_and_never_assembled(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account, clip=_vendor_clip(tmp_path, "scene_01.jpg")))

    summary = approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_judge=_judge_says_keep,
        face_counter=_no_faces,
    )

    # One purchase and one retry inside the 680-credit cap; never a third.
    assert models.posts() == 2
    assert summary["spent_credits_quoted"] <= summary["cap_credits"]
    (entry,) = summary["scenes"]
    assert entry["status"] == "NEEDS_OWNER"
    assert entry["clip_qc"]["verdict"] == "FAILED"
    for report in entry["clip_qc"]["reports"]:
        motion = next(c for c in report["checks"] if c["code"] == "motion")
        assert motion["status"] == "FAILED", report
    assert summary["clip_qc_failed"] == [1]
    _never_in_production(engine, storyboard_id, tmp_path)


@requires_ffmpeg
@requires_yunet
def test_a_face_the_bible_forbids_is_caught_by_yunet_when_the_vision_model_misses_it(
    engine, tmp_path
):
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account, clip=_vendor_clip(tmp_path, "scene_06.jpg")))

    summary = approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_judge=_judge_says_keep,  # the real YuNet counts the faces (face_counter=None)
    )

    assert models.posts() == 2
    (entry,) = summary["scenes"]
    assert entry["status"] == "NEEDS_OWNER" and entry["clip_qc"]["verdict"] == "FAILED"
    faces = next(c for c in entry["clip_qc"]["reports"][0]["checks"] if c["code"] == "faces")
    assert faces["status"] == "FAILED", faces
    _never_in_production(engine, storyboard_id, tmp_path)


def _ask(engine, storyboard_id, tmp_path, models, account, **kwargs) -> MotionStepRefused:
    with pytest.raises(MotionStepRefused) as asked:
        run(engine, storyboard_id, tmp_path, "test_shot", models, account, **kwargs)
    return asked.value


def test_a_yes_given_after_the_plan_changed_buys_nothing(engine, tmp_path):
    from app.services import ApprovalClosed

    storyboard_id = a_film(engine, tmp_path, scenes=1)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account), SpyVideo("veo3.1_fast", account))
    caps = [SEEDANCE, VEO_FAST]
    changed = {1: "veo3.1_fast"}

    first = _ask(engine, storyboard_id, tmp_path, models, account, capabilities=caps)
    assert first.status == "NEEDS_APPROVAL"
    old_plan = first.plan["plan_hash"]

    # The plan changes (the hero goes to another model): the old question is closed by the
    # new one, so his late yes to it cannot even be recorded.
    second = _ask(
        engine, storyboard_id, tmp_path, models, account, capabilities=caps, overrides=changed
    )
    assert second.status == "NEEDS_APPROVAL" and second.plan["plan_hash"] != old_plan
    with pytest.raises(ApprovalClosed):
        answer(engine, first.approval_id, "APPROVED", note="Da.")

    # The old plan's hash names a sheet that no longer exists.
    stale = _ask(
        engine,
        storyboard_id,
        tmp_path,
        models,
        account,
        capabilities=caps,
        overrides=changed,
        plan_hash=old_plan,
    )
    assert stale.status == "STALE_PLAN"
    assert models.posts() == 0, "a question about another plan bought a shot"


def test_a_yes_given_before_the_plan_changed_is_not_spent_on_the_new_plan(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account), SpyVideo("veo3.1_fast", account))
    caps = [SEEDANCE, VEO_FAST]

    first = _ask(engine, storyboard_id, tmp_path, models, account, capabilities=caps)
    answer(engine, first.approval_id, "APPROVED", note="Da, pe seedance2_5.")

    # Then the hero's model changes: his yes named the old plan, so the new one is asked.
    again = _ask(
        engine,
        storyboard_id,
        tmp_path,
        models,
        account,
        capabilities=caps,
        overrides={1: "veo3.1_fast"},
    )
    assert again.status == "NEEDS_APPROVAL"
    assert again.approval_id != first.approval_id
    assert models.posts() == 0, "a yes about one plan bought another"


def test_an_agent_cannot_choose_a_scenes_model(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    for agent in ("video_editor", "director", "ceo", ""):
        with pytest.raises(PermissionError, match="Doar Proprietarul"):
            set_scene_model(engine, storyboard_id, 1, "veo3.1_fast", issued_by=agent)
    with Session(engine) as session:
        assert not session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == SCENE_MODEL_EVENT)
        ).all()
