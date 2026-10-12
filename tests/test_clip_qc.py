"""Clip QC: a bought clip is measured before it is cut into the film.

What is asserted, at 0 credits and with every provider faked:

- the motion metric is the mean signalstats YDIF at 540 px width; the floor of each camera
  move is half of what a local ffmpeg fixture of that move measures (a push-in of 3% over
  5 s, a pan of 5% of the width), built from the clip's own first frame; a still clip fails
  the push-in floor and passes 'static', which has no floor;
- a hard cut inside a clip is a YDIF spike, and fails the clip;
- YuNet looks at the first, the middle and the last frame, and a face blocks the clip when
  the bible forbids faces;
- a failing clip gets ONE retry on the same model with seed + 1 and a stronger motion
  prompt, only when what is left under the approved cap covers it; otherwise it escalates;
- a clip made of panels (a flat band on its first frame, the still it was animated from, or
  the look's one_picture false or back_to_still) goes back to its still and is never bought
  again on it (2026-10-09: scene 5's clip animated a triptych); a band that appears only on a
  later frame is the motion's fault and gets the one retry; a night clip's own black sky, a
  band at the top the picture rises out of gradually, is one picture (2026-10-10);
- in PRODUCTION no LIVE scene may be a still unless the Owner chose it for that scene, and
  assembly is refused for one he did not choose;
- technical QC holds the delivered file to the encoder's own spec (1080x1920, H.264 High,
  yuv420p, tv range, BT.709, the timeline's fps), to a bitrate floor (fail under 6 Mbps,
  warn under 8), to the narration's length plus one second, and measures the true peak on
  the delivered file.

Fixtures are built here with the local ffmpeg from tests/fixtures/nepal_1d530880/scene_0N.jpg
(540x960 copies of the Nepal stills): scene 1 a landscape with no people, scene 6 a woman's
face. Nothing reads the original media folder or data/studio.db.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.media import qc
from app.media.faces import count_faces, detector_available
from app.media.models import MediaAsset, StoryboardScene, VideoRenderJob
from app.media.picture_qc import ClipJudgement, ClipVerdict, judge_clip
from app.media.prompt_lint import MOTION_CLOSING, VEO_MOTION_CLOSING
from app.media.qc import (
    CLIP_METRIC_WIDTH,
    FLOOR_SHARE,
    MIN_VIDEO_BITRATE,
    PAN_FRACTION,
    PUSH_IN_ZOOM,
    WARN_VIDEO_BITRATE,
    FallbackNotChosen,
    calibrate_floors,
    check_clip,
    clip_retry_decision,
    cut_spikes,
    evaluate_media_qc,
    fallback_verdict,
    measure_motion,
    probe_media_file,
    qc_clip_with_retry,
    require_chosen_fallbacks,
    stronger_motion_prompt,
    technical_problems,
)
from app.media.still_gate import StillPlan
from app.models import OwnerPolicy
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

FFMPEG = shutil.which("ffmpeg")
FIXTURES = Path(__file__).parent / "fixtures" / "nepal_1d530880"
#: The 2026-10-09 triptych, 270x480 (test_still_gate's docstring): rows 159-320 a flat band.
TRIPTYCH = Path(__file__).parent / "fixtures" / "panels" / "scene_05_c7c55abb_c1.jpg"
#: A 2026-10-10 scene-5 still, 270x480 grey (test_still_gate's docstring): one photograph of
#: glowing spheres over wet ground at night, rows 0-125 its black sky, a soft-edged band.
NIGHT_SKY = Path(__file__).parent / "fixtures" / "panels" / "scene_05_d067fe4c_c1.png"
requires_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")
requires_yunet = pytest.mark.skipif(
    not detector_available(), reason="the YuNet detector is not installed"
)


def _ffmpeg(*args: str) -> None:
    result = subprocess.run(
        [str(FFMPEG), "-v", "error", "-nostdin", "-y", "-threads", "2", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]


def _frame(work: Path, scene: int) -> Path:
    out = work / f"frame_{scene:02d}.png"
    if not out.exists():
        _ffmpeg(
            "-i", str(FIXTURES / f"scene_{scene:02d}.jpg"),
            "-vf", "scale=1080:1920:flags=lanczos",
            str(out),
        )  # fmt: skip
    return out


def _vendor_clip(work: Path, name: str, vf: str, scene: int = 1, seconds: float = 5.0) -> Path:
    """A 1080x1920 24 fps H.264 clip, the shape the vendor delivers."""
    out = work / f"{name}.mp4"
    frames = int(round(seconds * 24))
    _ffmpeg(
        "-loop", "1", "-i", str(_frame(work, scene)),
        "-vf", vf, "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
        str(out),
    )  # fmt: skip
    return out


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    if FFMPEG is None:
        pytest.skip("ffmpeg is not installed")
    work = tmp_path_factory.mktemp("clips")
    n = 120
    push = (
        "scale=4320:7680:flags=bicubic,"
        f"zoompan=z='1+0.10*on/{n - 1}':d={n}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        ":s=1080x1920:fps=24"
    )
    made = {
        "static": _vendor_clip(work, "static", "fps=24"),
        "push": _vendor_clip(work, "push", push),
        "face": _vendor_clip(work, "face", "fps=24", scene=6),
    }
    # The push with a hard cut at 2.5 s to another picture: one clip, two shots.
    cut = work / "push_cut.mp4"
    _ffmpeg(
        "-i", str(made["push"]), "-loop", "1", "-t", "2.5", "-i", str(_frame(work, 2)),
        "-filter_complex",
        "[0]trim=0:2.5,setpts=PTS-STARTPTS,format=yuv420p[a];"
        "[1]fps=24,format=yuv420p[b];[a][b]concat=n=2:v=1[v]",
        "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
        str(cut),
    )  # fmt: skip
    made["cut"] = cut
    made["work"] = work
    return made


def _passing_judge(scene: int = 1):
    def judge(frames):
        assert len(frames) == 3
        return ClipJudgement(
            status="MEASURED",
            verdict=ClipVerdict(
                scene=scene,
                faces_visible=False,
                readable_text=False,
                matches_plan=True,
                look_ok=True,
                technical_ok=True,
                same_shot=True,
                one_picture=True,
                bible_violations="none",
                verdict="keep",
                reason="a valley under cloud, the camera moving in",
            ),
            detail_ro="o vale sub nori",
            run_id="run",
            looked_by="VideoEditor",
            image_width=1080,
            frames=3,
        )

    return judge


def _no_faces(path, **_kwargs):
    from app.media.faces import FaceCount

    return FaceCount(status="MEASURED", faces=0, boxes=(), detail_ro="YuNet a găsit 0 fețe")


# ------------------------------------------------- 1. the motion floor, per camera move


@requires_ffmpeg
def test_the_floor_is_half_of_a_local_fixture_measured_at_540_px(clips, tmp_path):
    assert CLIP_METRIC_WIDTH == 540
    assert (PUSH_IN_ZOOM, PAN_FRACTION, FLOOR_SHARE) == (0.03, 0.05, 0.5)
    first = _frame(clips["work"], 1)
    floors = calibrate_floors(FFMPEG, first, fps=24, work_dir=tmp_path)

    assert set(floors) == {"push_in", "pan"}
    for kind, calibration in floors.items():
        assert calibration.fixture_mean > 0, kind
        assert calibration.floor == pytest.approx(calibration.fixture_mean * FLOOR_SHARE)
        assert calibration.fps == 24 and calibration.width == 540
        assert calibration.seconds == 5.0

    # The fixture itself is measured with the same metric as any clip.
    still = measure_motion(FFMPEG, clips["static"])
    push = measure_motion(FFMPEG, clips["push"])
    assert still is not None and push is not None
    assert still.width == 540 and still.fps == pytest.approx(24)
    assert floors["push_in"].floor < push.mean and floors["push_in"].floor < push.median
    # A frozen picture can still read a mean YDIF above the floor: x264 encodes it with
    # B-frames that pulse between two reconstructions (measured: mean 1.5, against a push-in
    # fixture's 0.7). Half its frames are identical, so its median stays near zero; a real
    # move changes every frame. The floor holds the mean AND the median.
    assert still.median < floors["push_in"].floor
    assert still.median < floors["pan"].floor


@requires_ffmpeg
def test_a_still_clip_fails_the_push_in_floor_and_passes_static(clips, tmp_path):
    common = {
        "scene": 1,
        "faces_forbidden": False,
        "environment": "PRODUCTION",
        "ffmpeg_path": FFMPEG,
        "face_counter": _no_faces,
        "judge": _passing_judge(),
    }
    pushed_in = check_clip(
        clips["static"], camera_move="slow push-in", work_dir=tmp_path / "a", **common
    )
    motion = pushed_in.check("motion")
    assert motion.status == "FAILED" and motion.blocking
    assert pushed_in.passed is False
    assert "540" in motion.detail_ro and "prag" in motion.detail_ro
    assert pushed_in.measured["motion"]["fixture"] == "push_in"

    static = check_clip(clips["static"], camera_move="static", work_dir=tmp_path / "b", **common)
    assert static.check("motion").status == "PASSED"
    assert static.measured["motion"]["floor"] is None
    assert static.passed is True, static.blocks_ro

    moving = check_clip(
        clips["push"], camera_move="slow push-in", work_dir=tmp_path / "c", **common
    )
    assert moving.check("motion").status == "PASSED", moving.check("motion").detail_ro
    assert moving.passed is True, moving.blocks_ro

    # A pan is held to the pan fixture's floor, not the push-in's.
    panned = check_clip(
        clips["static"], camera_move="slow pan left", work_dir=tmp_path / "d", **common
    )
    assert panned.measured["motion"]["fixture"] == "pan"
    assert panned.check("motion").status == "FAILED"


def test_an_unknown_camera_move_has_no_floor_and_is_not_measured():
    reading = SimpleNamespace(mean=3.0, values=[0.0, 3.0, 3.0], times=[0.0, 0.04, 0.08])
    check = qc.motion_check(reading, "whip around the tower", floors={})
    assert check.status == "NOT_RUN" and check.blocking


# ------------------------------------------------------------- 2. a cut inside a clip


@requires_ffmpeg
def test_a_hard_cut_inside_a_clip_fails_the_spike_check(clips, tmp_path):
    cut = measure_motion(FFMPEG, clips["cut"])
    assert cut is not None
    spikes = cut_spikes(cut)
    assert len(spikes) == 1 and spikes[0] == pytest.approx(2.5, abs=0.1)
    assert cut_spikes(measure_motion(FFMPEG, clips["push"])) == []

    report = check_clip(
        clips["cut"],
        scene=2,
        camera_move="slow push-in",
        faces_forbidden=False,
        environment="TEST",
        ffmpeg_path=FFMPEG,
        face_counter=_no_faces,
        judge=_passing_judge(2),
        work_dir=tmp_path,
    )
    cuts = report.check("cuts")
    assert cuts.status == "FAILED" and cuts.blocking, cuts
    assert report.passed is False
    assert any("tăietură" in reason for reason in report.blocks_ro)


# -------------------------------------------- 3. faces on the first, middle, last frames


@requires_ffmpeg
@requires_yunet
def test_yunet_looks_at_the_first_middle_and_last_frames(clips, tmp_path):
    seen: list[Path] = []

    def counting(path, **kwargs):
        seen.append(Path(path))
        return count_faces(path, **kwargs)

    face = check_clip(
        clips["face"],
        scene=6,
        camera_move="static",
        faces_forbidden=True,
        environment="PRODUCTION",
        ffmpeg_path=FFMPEG,
        face_counter=counting,
        judge=_passing_judge(6),
        work_dir=tmp_path / "face",
    )
    assert len(seen) == 3
    frames = face.measured["faces"]["frames"]
    assert [frame["at"] for frame in frames] == ["first", "middle", "last"]
    assert frames[0]["time"] == pytest.approx(0.0, abs=0.05)
    assert frames[1]["time"] == pytest.approx(2.5, abs=0.1)
    assert frames[2]["time"] == pytest.approx(5.0 - 1 / 24, abs=0.1)
    assert all(frame["status"] == "MEASURED" for frame in frames)
    assert sum(frame["faces"] for frame in frames) >= 1
    check = face.check("faces")
    assert check.status == "FAILED" and check.blocking
    assert face.passed is False
    assert "YuNet" in check.detail_ro

    seen.clear()
    landscape = check_clip(
        clips["push"],
        scene=1,
        camera_move="slow push-in",
        faces_forbidden=True,
        environment="PRODUCTION",
        ffmpeg_path=FFMPEG,
        face_counter=counting,
        judge=_passing_judge(),
        work_dir=tmp_path / "landscape",
    )
    assert len(seen) == 3
    assert landscape.check("faces").status == "PASSED"
    assert landscape.passed is True, landscape.blocks_ro

    # When the bible allows faces, nobody counts them.
    seen.clear()
    allowed = check_clip(
        clips["face"],
        scene=6,
        camera_move="static",
        faces_forbidden=False,
        environment="PRODUCTION",
        ffmpeg_path=FFMPEG,
        face_counter=counting,
        judge=_passing_judge(6),
        work_dir=tmp_path / "allowed",
    )
    assert seen == [] and allowed.check("faces").status == "NOT_APPLICABLE"


@requires_ffmpeg
def test_a_face_count_that_could_not_run_blocks_in_production_only(clips, tmp_path):
    from app.media.faces import FaceCount

    def missing(path, **_kwargs):
        return FaceCount("NOT_RUN", None, (), "modelul YuNet lipsește")

    kwargs = {
        "scene": 1,
        "camera_move": "slow push-in",
        "faces_forbidden": True,
        "ffmpeg_path": FFMPEG,
        "face_counter": missing,
        "judge": _passing_judge(),
    }
    production = check_clip(
        clips["push"], environment="PRODUCTION", work_dir=tmp_path / "p", **kwargs
    )
    assert production.check("faces").status == "NOT_RUN"
    assert production.passed is False and "faces" in production.unmeasured
    test = check_clip(clips["push"], environment="TEST", work_dir=tmp_path / "t", **kwargs)
    assert test.passed is True and test.warnings_ro


@requires_ffmpeg
def test_a_vision_model_that_saw_a_face_blocks_the_clip_the_detector_passed(clips, tmp_path):
    def saw_a_face(frames):
        judgement = _passing_judge()(frames)
        verdict = judgement.verdict.model_copy(
            update={"faces_visible": True, "verdict": "regenerate_motion"}
        )
        return ClipJudgement(**{**judgement.__dict__, "verdict": verdict})

    report = check_clip(
        clips["push"],
        scene=1,
        camera_move="slow push-in",
        faces_forbidden=True,
        environment="PRODUCTION",
        ffmpeg_path=FFMPEG,
        face_counter=_no_faces,
        judge=saw_a_face,
        work_dir=tmp_path,
    )
    assert report.passed is False
    assert report.check("picture").status == "FAILED"


@requires_ffmpeg
def test_a_clip_nobody_looked_at_is_not_passed(clips, tmp_path):
    report = check_clip(
        clips["push"],
        scene=1,
        camera_move="slow push-in",
        faces_forbidden=False,
        environment="TEST",
        ffmpeg_path=FFMPEG,
        face_counter=_no_faces,
        judge=None,
        work_dir=tmp_path,
    )
    picture = report.check("picture")
    assert picture.status == "NOT_RUN" and picture.blocking
    assert "nu a fost privit" in picture.detail_ro
    assert report.passed is False


# ---------------------------------------------- the multi-frame vision checklist itself


@requires_ffmpeg
def test_judge_clip_sends_three_frames_at_1080_px_in_one_call(engine, clips):
    import base64

    from test_picture_qc import give_vision, registry_with, staff

    staffed = staff(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    answer = json.dumps(
        {
            "clips": [
                {
                    "scene": 1,
                    "faces_visible": False,
                    "readable_text": False,
                    "matches_plan": True,
                    "shows_scene": True,
                    "look_ok": True,
                    "technical_ok": True,
                    "same_shot": True,
                    "one_picture": True,
                    "bible_violations": "none",
                    "verdict": "keep",
                    "reason": "a valley under low cloud",
                }
            ]
        }
    )
    registry, model = registry_with(staffed, lambda prompt: answer)
    work = clips["work"] / "judge"
    work.mkdir(exist_ok=True)
    frames = qc.clip_frames(FFMPEG, clips["push"], work)
    plan = StillPlan(
        scene=1,
        still_prompt="A wide valley under low cloud",
        camera_move="slow push-in",
        faces_forbidden=True,
        bible_rules=("No human faces appear",),
    )

    judgement = judge_clip(engine, registry, [path for _at, _t, path in frames], plan, "corr")

    assert judgement.status == "MEASURED" and judgement.verdict.verdict == "keep"
    assert len(model.calls) == 1
    images = model.calls[0]["extra"]["images"]
    assert len(images) == 3
    for image in images:
        data = base64.b64decode(image)
        assert data[:2] == b"\xff\xd8"
        assert b"\x07\x80\x04\x38" in data  # SOF: 1920 high, 1080 wide
    prompt = model.calls[0]["prompt"]
    assert "No human faces appear" in prompt and "same_shot" in prompt
    assert "one_picture" in prompt and "always when one_picture is false" in prompt

    # No entry for this clip: nobody looked.
    registry, _ = registry_with(staffed, lambda prompt: json.dumps({"clips": []}))
    missing = judge_clip(engine, registry, [path for _at, _t, path in frames], plan, "corr")
    assert missing.status == "NOT_RUN" and missing.verdict is None
    assert "nu a fost privit" in missing.detail_ro


def test_the_clip_verdict_has_no_field_that_passes_by_default():
    from app.media.picture_qc import ClipJudgeReport

    good = {
        "scene": 1,
        "faces_visible": False,
        "readable_text": False,
        "matches_plan": True,
        "shows_scene": True,
        "look_ok": True,
        "technical_ok": True,
        "same_shot": True,
        "one_picture": True,
        "bible_violations": "none",
        "verdict": "keep",
        "reason": "x",
    }
    with pytest.raises(ValueError):
        ClipVerdict.model_validate({"scene": 1, "verdict": "keep", "reason": "x"})
    for word in ({"faces_visible": "no"}, {"one_picture": "yes"}):
        with pytest.raises(ValueError):
            ClipVerdict.model_validate({**good, **word})
    # The model's answer must say whether every frame is one picture.
    silent = {key: value for key, value in good.items() if key != "one_picture"}
    with pytest.raises(ValueError):
        ClipJudgeReport.model_validate({"clips": [silent]})
    assert ClipJudgeReport.model_validate({"clips": [good]}).clips[0].one_picture is True


# ------------------------------------------------------ 4. one retry, inside the cap


def _failed_report(code="motion", unmeasured=()):
    check = qc.ClipCheck(code, "NOT_RUN" if unmeasured else "FAILED", True, 0.1, "sub prag")
    return qc.ClipReport(
        scene=3,
        path="clip.mp4",
        checks=(check,),
        passed=False,
        blocks_ro=("Scena 3: mișcarea e sub prag",),
        warnings_ro=(),
        unmeasured=tuple(unmeasured),
        measured={},
    )


def _passed_report():
    return qc.ClipReport(
        scene=3,
        path="clip.mp4",
        checks=(qc.ClipCheck("motion", "PASSED", False, 2.0, "ok"),),
        passed=True,
        blocks_ro=(),
        warnings_ro=(),
        unmeasured=(),
        measured={},
    )


PROMPT = (
    "Slow push-in toward the terraced fields. Low cloud drifts across the ridge, slowly. "
    "Faces stay turned away from the camera. " + MOTION_CLOSING
)


def test_a_failing_clip_is_retried_once_with_seed_plus_one_inside_the_cap(tmp_path):
    bought: list[dict] = []
    reports = iter([_failed_report(), _passed_report()])

    def buy(seed, prompt):
        bought.append({"seed": seed, "prompt": prompt})
        out = tmp_path / f"retry_{seed}.mp4"
        out.write_bytes(b"clip")
        return out

    outcome = qc_clip_with_retry(
        tmp_path / "first.mp4",
        check=lambda path: next(reports),
        buy=buy,
        seed=4242,
        motion_prompt=PROMPT,
        camera_move="slow push-in",
        model_id="seedance2_5",
        price_credits=340,
        committed_credits=340,
        cap_credits=700,
    )

    assert outcome.status == "PASSED_ON_RETRY"
    assert len(bought) == 1 and bought[0]["seed"] == 4243
    stronger = bought[0]["prompt"]
    assert stronger != PROMPT and stronger.endswith(MOTION_CLOSING)
    assert "push-in" in stronger and "clearly" in stronger
    assert outcome.retry_credits == 340 and outcome.attempts == 2
    assert outcome.seeds == (4242, 4243)


def test_a_retry_the_cap_cannot_cover_escalates_without_buying(tmp_path):
    bought: list = []
    outcome = qc_clip_with_retry(
        tmp_path / "first.mp4",
        check=lambda path: _failed_report(),
        buy=lambda seed, prompt: bought.append(seed),
        seed=7,
        motion_prompt=PROMPT,
        camera_move="slow push-in",
        model_id="seedance2_5",
        price_credits=340,
        committed_credits=400,
        cap_credits=700,
    )
    assert bought == []
    assert outcome.status == "ESCALATED" and outcome.retry_credits == 0
    assert "plafon" in outcome.reason_ro and "Proprietar" in outcome.reason_ro


def test_a_second_failure_escalates_and_is_never_bought_a_third_time(tmp_path):
    bought: list[int] = []

    def buy(seed, prompt):
        bought.append(seed)
        return tmp_path / "retry.mp4"

    outcome = qc_clip_with_retry(
        tmp_path / "first.mp4",
        check=lambda path: _failed_report(),
        buy=buy,
        seed=10,
        motion_prompt=PROMPT,
        camera_move="slow push-in",
        model_id="seedance2_5",
        price_credits=100,
        committed_credits=0,
        cap_credits=10_000,
    )
    assert bought == [11]
    assert outcome.status == "ESCALATED" and outcome.attempts == 2


def test_a_clip_that_could_only_not_be_measured_is_not_bought_again(tmp_path):
    decision = clip_retry_decision(
        _failed_report(code="faces", unmeasured=("faces",)),
        seed=1,
        retries_done=0,
        committed_credits=0,
        price_credits=100,
        cap_credits=10_000,
    )
    assert decision.action == "ESCALATE" and "măsura" in decision.reason_ro


def test_the_stronger_prompt_keeps_the_dialect_of_its_model():
    veo = stronger_motion_prompt(
        "Slow pan left across the ridge. Mist drifts slowly. " + VEO_MOTION_CLOSING,
        "slow pan left",
        model_id="veo3.1_fast",
    )
    assert veo.endswith(VEO_MOTION_CLOSING)
    assert " no " not in f" {veo.lower()} " and "not " not in veo.lower()
    assert "pan left" in veo


# ---------------------------------------- 4b. a clip made of panels goes back to its still


@pytest.fixture(scope="module")
def panel_clips(clips):
    """The 2026-10-09 triptych held still for 5 s (the still a vendor animates is the clip's
    first frame); the Nepal push-in with a black strip over its lower 40 % in its last second;
    the same push-in faded to black, its last frame flat from edge to edge; and a 2026-10-10
    night still under its black sky held for 5 s."""
    work = clips["work"]
    encode = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p"]
    held: dict[str, Path] = {}
    for name, still in (("panels", TRIPTYCH), ("night", NIGHT_SKY)):
        frame = work / f"{name}.png"
        _ffmpeg("-i", str(still), "-vf", "scale=1080:1920:flags=lanczos", str(frame))
        held[name] = work / f"{name}.mp4"
        _ffmpeg(
            "-loop", "1", "-i", str(frame), "-vf", "fps=24", "-frames:v", "120",
            *encode, str(held[name]),
        )  # fmt: skip
    late = work / "late_band.mp4"
    strip = "drawbox=x=0:y=ih*0.6:w=iw:h=ih*0.4:color=black:t=fill:enable='gte(t,4)'"
    _ffmpeg("-i", str(clips["push"]), "-vf", strip, *encode, str(late))
    faded = work / "faded.mp4"
    _ffmpeg("-i", str(clips["push"]), "-vf", "fade=t=out:st=4:d=1", *encode, str(faded))
    return {**held, "late_band": late, "faded": faded}


def _clip_report(clip: Path, tmp_path: Path, *, scene: int, move: str, judge) -> qc.ClipReport:
    return check_clip(
        clip,
        scene=scene,
        camera_move=move,
        faces_forbidden=False,
        environment="PRODUCTION",
        ffmpeg_path=FFMPEG,
        face_counter=_no_faces,
        judge=judge,
        work_dir=tmp_path,
    )


@requires_ffmpeg
def test_a_clip_animated_from_a_panel_still_goes_back_to_the_still_and_buys_nothing(
    panel_clips, tmp_path
):
    report = _clip_report(
        panel_clips["panels"], tmp_path, scene=5, move="static", judge=_passing_judge(5)
    )

    panels = report.check("panels")
    assert panels.status == "FAILED" and panels.blocking
    assert "cadrul first" in panels.detail_ro and "la mijloc" in panels.detail_ro
    frames = report.measured["panels"]["frames"]
    assert [frame["at"] for frame in frames] == ["first", "middle", "last"]
    assert all(frame["splits_the_picture"] for frame in frames)
    # The look kept it, as on 2026-10-09; the band alone sends it back to its still.
    assert report.check("picture").status == "PASSED"
    assert report.passed is False and report.back_to_still is True

    bought: list[int] = []
    outcome = qc_clip_with_retry(
        Path(report.path),
        check=lambda path: report,
        buy=lambda seed, prompt: bought.append(seed),
        seed=5,
        motion_prompt=PROMPT,
        camera_move="static",
        model_id="seedance2_5",
        price_credits=100,
        committed_credits=0,
        cap_credits=10_000,
    )
    assert bought == [], "the same still was animated again"
    assert outcome.status == "BACK_TO_STILL" and outcome.clip is None
    assert outcome.attempts == 1 and outcome.retry_credits == 0
    assert "nu se mai animă" in outcome.reason_ro and "imagine nouă" in outcome.reason_ro
    assert "nu e o singură fotografie" in outcome.reason_ro


@requires_ffmpeg
@pytest.mark.parametrize(
    ("changes", "words"),
    [
        ({"one_picture": False, "verdict": "back_to_still"}, "o singură fotografie"),
        ({"one_picture": False, "verdict": "keep"}, "o singură fotografie"),
        ({"verdict": "back_to_still"}, "back_to_still"),
    ],
    ids=["panels", "panels-but-keep", "back-to-still"],
)
def test_a_clip_the_look_sends_back_to_its_still_is_not_retried_on_it(
    clips, tmp_path, changes, words
):
    """The band cannot see three similar tunnels stacked (scene_05_0d900cbd_c2): the look's
    one_picture, or its own back_to_still, routes the clip the same way."""

    def judge(frames):
        judgement = _passing_judge()(frames)
        verdict = judgement.verdict.model_copy(
            update={**changes, "reason": "three tunnels stacked one above another"}
        )
        return ClipJudgement(**{**judgement.__dict__, "verdict": verdict})

    report = _clip_report(clips["push"], tmp_path, scene=1, move="slow push-in", judge=judge)

    assert report.check("panels").status == "PASSED"
    picture = report.check("picture")
    assert picture.status == "FAILED" and words in picture.detail_ro
    assert report.back_to_still is True
    decision = clip_retry_decision(
        report, seed=1, retries_done=0, committed_credits=0, price_credits=100, cap_credits=10_000
    )
    assert decision.action == "BACK_TO_STILL" and decision.seed is None


@requires_ffmpeg
def test_a_band_on_the_last_frame_only_is_the_motions_fault_and_gets_the_one_retry(
    panel_clips, tmp_path
):
    """The still (the first frame) is one picture; the clip grew a blank strip at its end.
    Another seed on the same still can fix that, so it is the one retry, not a new still."""
    report = _clip_report(
        panel_clips["late_band"], tmp_path, scene=1, move="slow push-in", judge=_passing_judge()
    )

    panels = report.check("panels")
    assert panels.status == "FAILED", panels
    assert "cadrul last" in panels.detail_ro and "cadrul first" not in panels.detail_ro
    assert "jos" in panels.detail_ro
    assert report.back_to_still is False
    decision = clip_retry_decision(
        report, seed=1, retries_done=0, committed_credits=0, price_credits=100, cap_credits=10_000
    )
    assert decision.action == "RETRY" and decision.seed == 2


@requires_ffmpeg
def test_a_frame_flat_from_edge_to_edge_is_not_panels(panel_clips, tmp_path):
    """A fade to black leaves nothing to hold apart: a blank field is not pictures pasted
    together, and the panels check does not send a good still back for it."""
    report = _clip_report(
        panel_clips["faded"], tmp_path, scene=1, move="slow push-in", judge=_passing_judge()
    )

    last = report.measured["panels"]["frames"][-1]
    assert last["band_rows"] == last["height"] == 480 and last["splits_the_picture"] is False
    assert report.check("panels").status == "PASSED"
    assert report.back_to_still is False


@requires_ffmpeg
def test_a_night_clip_under_its_own_black_sky_is_one_picture(panel_clips, tmp_path):
    """2026-10-10: the scene-5 still's black sky is a flat band of a quarter of the height at
    the top, but the picture rises out of it (qc.SOFT_EDGE_STEP). Its clip has the same sky:
    the panels check passes it and does not send the still back."""
    report = _clip_report(
        panel_clips["night"], tmp_path, scene=5, move="static", judge=_passing_judge(5)
    )

    panels = report.check("panels")
    assert panels.status == "PASSED" and not panels.blocking, panels
    assert "banda plată de sus trece lin în imagine" in panels.detail_ro
    frames = report.measured["panels"]["frames"]
    assert [frame["at"] for frame in frames] == ["first", "middle", "last"]
    for frame in frames:
        assert frame["band_start"] == 0 and frame["band_share"] >= qc.PANEL_BAND_SHARE, frame
        assert frame["soft_edge"] is True and frame["splits_the_picture"] is False, frame
        assert frame["edge_step"] < qc.SOFT_EDGE_STEP / 2, frame
    assert report.back_to_still is False


def test_a_retry_that_shows_the_still_at_fault_comes_back_to_the_still(tmp_path):
    from dataclasses import replace

    bought: list[int] = []
    reports = iter([_failed_report(), replace(_failed_report("picture"), back_to_still=True)])

    def buy(seed, prompt):
        bought.append(seed)
        return tmp_path / "retry.mp4"

    outcome = qc_clip_with_retry(
        tmp_path / "first.mp4",
        check=lambda path: next(reports),
        buy=buy,
        seed=10,
        motion_prompt=PROMPT,
        camera_move="slow push-in",
        model_id="seedance2_5",
        price_credits=100,
        committed_credits=0,
        cap_credits=10_000,
    )
    assert bought == [11]
    assert outcome.status == "BACK_TO_STILL" and outcome.attempts == 2
    assert "imagine nouă" in outcome.reason_ro


# --------------------------------------------- 5. no still in PRODUCTION without his choice


def _production(*scenes):
    return {
        "scenes": [
            {"scene_index": index, "scene_kind": kind, "motion": motion}
            for index, kind, motion in scenes
        ]
    }


MOVED = {"model": "seedance2_5", "bytes": 1024}
STILL = {"model": None, "refused": "the model refused this shot"}


def test_no_live_scene_may_be_a_still_in_production_without_the_owners_choice():
    production = _production(
        (1, "LIVE", MOVED), (2, "LIVE", STILL), (3, "DATA_CARD", None), (4, "LIVE", MOVED)
    )
    verdict = fallback_verdict(production, environment="PRODUCTION", owner_choices=set())
    assert verdict["passed"] is False
    assert verdict["max_fallback_scenes"] == 0
    assert verdict["live_fallbacks"] == [2] and verdict["unchosen"] == [2]
    assert "Scena 2" in verdict["reason_ro"]

    chosen = fallback_verdict(production, environment="PRODUCTION", owner_choices={2})
    assert chosen["passed"] is True and chosen["owner_chosen"] == [2]

    # A setting cannot loosen it in PRODUCTION; in TEST it is a warning, as before.
    loose = fallback_verdict(
        production,
        environment="PRODUCTION",
        owner_choices=set(),
        settings=SimpleNamespace(max_fallback_scenes=3),
    )
    assert loose["passed"] is False
    test = fallback_verdict(production, environment="TEST", owner_choices=set())
    assert test["passed"] is True


def _board_with_scenes(engine, tmp_path, scenes=3):
    from test_phase5_media import _seeded_storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path, scenes=scenes)
    return storyboard_id


def test_a_fallback_without_the_owners_choice_blocks_assembly(engine, tmp_path):
    storyboard_id = _board_with_scenes(engine, tmp_path)
    production = _production((1, "LIVE", MOVED), (2, "LIVE", STILL), (3, "LIVE", MOVED))
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"

    with pytest.raises(FallbackNotChosen) as refused:
        require_chosen_fallbacks(engine, storyboard_id, production)
    assert refused.value.scenes == [2]
    assert "Scena 2" in str(refused.value) and "Proprietar" in str(refused.value)

    # His choice on the sheet, stored as the scene's own video override.
    with Session(engine) as session, session.begin():
        scene = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 2
            )
        )
        scene.production_overrides_json = {"video": {"model_id": "LOCAL_MOVE"}}
    assert require_chosen_fallbacks(engine, storyboard_id, production)["passed"] is True

    # In TEST the same film is assembled, with the warning.
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "TEST"
        scene = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 2
            )
        )
        scene.production_overrides_json = {}
    assert require_chosen_fallbacks(engine, storyboard_id, production)["passed"] is True


def test_a_local_move_chosen_on_the_shooting_sheet_counts_as_the_owners_choice(engine, tmp_path):
    """The sheet drawer records his LOCAL_MOVE as a media.sheet_scene_model_set event (PUT
    .../shooting-sheet/scenes/{n}/model). The fallback gate must read that same choice, or a
    still he chose on the sheet would fail the PRODUCTION film."""
    from app.media.shooting_sheet import LOCAL_MOVE, set_scene_model

    storyboard_id = _board_with_scenes(engine, tmp_path)
    production = _production((1, "LIVE", MOVED), (2, "LIVE", STILL), (3, "LIVE", MOVED))
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"

    set_scene_model(engine, storyboard_id, 2, LOCAL_MOVE, issued_by="owner")

    assert require_chosen_fallbacks(engine, storyboard_id, production)["passed"] is True
    # Set back to the studio's choice, the still is no longer his.
    set_scene_model(engine, storyboard_id, 2, None, issued_by="owner")
    with pytest.raises(FallbackNotChosen):
        require_chosen_fallbacks(engine, storyboard_id, production)


# --------------------------------------------------------- 6. technical and audio QC


GOOD_PROBE = {
    "available": True,
    "ok": True,
    "width": 1080,
    "height": 1920,
    "duration_seconds": 30.0,
    "video_codec": "h264",
    "video_profile": "High",
    "pix_fmt": "yuv420p",
    "color_range": "tv",
    "color_space": "bt709",
    "color_primaries": "bt709",
    "color_transfer": "bt709",
    "video_fps": 30.0,
    "video_bit_rate": 10_000_000,
}


def test_the_bitrate_floor_fails_under_6_and_warns_under_8_mbps():
    assert (MIN_VIDEO_BITRATE, WARN_VIDEO_BITRATE) == (6_000_000, 8_000_000)
    failures, warnings = technical_problems(
        GOOD_PROBE, environment="PRODUCTION", timeline_fps=30, narration_seconds=29.5
    )
    assert failures == [] and warnings == []

    low = {**GOOD_PROBE, "video_bit_rate": 5_900_000}
    failures, _ = technical_problems(
        low, environment="PRODUCTION", timeline_fps=30, narration_seconds=29.5
    )
    assert any("5,9 Mbps" in f for f in failures), failures

    middling = {**GOOD_PROBE, "video_bit_rate": 7_000_000}
    failures, warnings = technical_problems(
        middling, environment="PRODUCTION", timeline_fps=30, narration_seconds=29.5
    )
    assert failures == [] and any("7,0 Mbps" in w for w in warnings)

    # TEST films are drawn from synthetic stand-in pictures, which compress to nothing:
    # the floor is a warning there, the format is not.
    failures, warnings = technical_problems(
        low, environment="TEST", timeline_fps=30, narration_seconds=29.5
    )
    assert failures == [] and any("5,9 Mbps" in w for w in warnings)


def test_the_delivered_format_is_the_encoders_own_in_every_environment():
    for change, words in (
        ({"pix_fmt": "yuvj420p"}, "yuvj420p"),
        ({"color_range": "pc"}, "pc"),
        ({"video_profile": "Main"}, "Main"),
        ({"color_primaries": "bt470bg"}, "bt470bg"),
        ({"video_fps": 24.0}, "24"),
        ({"width": 720, "height": 1280}, "720x1280"),
    ):
        for environment in ("TEST", "PRODUCTION"):
            failures, _ = technical_problems(
                {**GOOD_PROBE, **change},
                environment=environment,
                timeline_fps=30,
                narration_seconds=29.5,
            )
            assert any(words in f for f in failures), (change, environment, failures)


def test_a_film_longer_than_its_narration_plus_one_second_fails_in_production():
    failures, _ = technical_problems(
        GOOD_PROBE, environment="PRODUCTION", timeline_fps=30, narration_seconds=29.0
    )
    assert failures == []
    failures, _ = technical_problems(
        GOOD_PROBE, environment="PRODUCTION", timeline_fps=30, narration_seconds=28.9
    )
    assert any("narați" in f for f in failures), failures
    failures, warnings = technical_problems(
        GOOD_PROBE, environment="PRODUCTION", timeline_fps=30, narration_seconds=None
    )
    assert any("narați" in f for f in failures)


def _hot_film(tmp_path) -> Path:
    """10.5 s, 1080x1920, full-range yuvj420p at about 2 Mbps, with a tone whose true peak is
    over -1 dBTP: everything the Nepal film's file got wrong, and then some."""
    out = tmp_path / "hot.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=10.5",
        "-f", "lavfi", "-i", "sine=frequency=997:sample_rate=48000:duration=10.5",
        "-filter_complex", "[1]volume=7.8[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high",
        "-b:v", "2M", "-maxrate", "2M", "-bufsize", "4M",
        "-pix_fmt", "yuvj420p", "-color_range", "pc",
        "-c:a", "aac", "-b:a", "192k",
        str(out),
    )  # fmt: skip
    return out


def _film_row(engine, tmp_path, path: Path, *, narration: float, production_extra=None):
    from hashlib import sha256

    storyboard_id = _board_with_scenes(engine, tmp_path, scenes=2)
    asset_id, job_id = str(uuid4()), str(uuid4())
    srt = path.parent / "captions.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:04,000\nFixture narration segment 1.\n\n"
        "2\n00:00:04,000 --> 00:00:08,000\nFixture narration segment 2.\n",
        encoding="utf-8",
    )
    production = {
        "scenes": [
            {"scene_index": 1, "scene_kind": "LIVE", "audio_seconds": narration / 2},
            {"scene_index": 2, "scene_kind": "LIVE", "audio_seconds": narration / 2},
        ],
        "audio": {"loudness": {"output": {"integrated_lufs": -14.0, "true_peak_dbtp": -2.0}}},
        "captions": {"srt": str(srt)},
        **(production_extra or {}),
    }
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(path),
                file_size_bytes=path.stat().st_size,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=10.5,
                provider_name="TEST_IMAGE_PROVIDER",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash=sha256(path.read_bytes()).hexdigest(),
                created_at=utc_now(),
            )
        )
        session.add(
            VideoRenderJob(
                id=job_id,
                storyboard_id=storyboard_id,
                output_asset_id=asset_id,
                status="COMPLETED",
                started_at=utc_now(),
                production_json=production,
            )
        )
    return asset_id


@requires_ffmpeg
def test_technical_qc_fails_a_2_mbps_full_range_file_and_measures_the_delivered_peak(
    engine, tmp_path
):
    film = _hot_film(tmp_path)
    probe = probe_media_file(film)
    assert probe["pix_fmt"] == "yuvj420p" and probe["color_range"] == "pc"
    assert probe["video_profile"] == "High"
    assert probe["video_bit_rate"] < 3_000_000

    asset_id = _film_row(engine, tmp_path, film, narration=8.0)
    for environment in ("TEST", "PRODUCTION"):
        with Session(engine) as session, session.begin():
            session.get(OwnerPolicy, 1).environment = environment
        report = evaluate_media_qc(engine, asset_id, str(uuid4()))
        technical = report["checks_json"]["technical_qc"]
        assert technical["passed"] is False, environment
        reasons = " ".join(report["failure_reasons_json"])
        assert "yuvj420p" in reasons and "pc" in reasons
        assert technical["pix_fmt"] == "yuvj420p" and technical["color_range"] == "pc"
        assert technical["video_bit_rate"] == probe["video_bit_rate"]
        if environment == "PRODUCTION":
            assert "Mbps" in reasons and "narați" in reasons
        else:
            assert technical["warnings"], technical

        # The true peak is read off the delivered file, not off the manifest's -2.0.
        audio = report["checks_json"]["audio_qc"]
        assert audio["measured_on"] == "delivered_file"
        assert audio["true_peak_dbtp"] > -1.0
        assert audio["passed"] is False
        assert any("dBTP" in reason for reason in report["failure_reasons_json"])
        assert audio["band_lufs"] == [-15.0, -13.0]


def test_too_many_fallbacks_no_longer_have_a_default_of_half_in_production(engine, tmp_path):
    """The 2026-09-26 rule (half the scenes) let the Nepal film's two stills through."""
    from test_phase5_media import _render_with_motion_record

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"
    asset = _render_with_motion_record(engine, tmp_path, refused=1, made=3)
    report = evaluate_media_qc(engine, asset, str(uuid4()))
    motion = report["checks_json"]["motion_qc"]
    assert motion["passed"] is False and motion["max_fallback_scenes"] == 0
    assert motion["unchosen"] == [1]


def test_duplicated_frames_are_counted_only_inside_the_scenes_that_move():
    """24 fps clips put on a 30 fps timeline repeat one frame in five: measured 20% on a
    Nepal clip, and that is the judder. Cards and stills are not counted, nor span edges."""
    production = {
        "scenes": [
            {"scene_index": 1, "scene_kind": "LIVE", "audio_seconds": 4.0, "motion": MOVED},
            {"scene_index": 2, "scene_kind": "DATA_CARD", "audio_seconds": 3.0},
            {"scene_index": 3, "scene_kind": "LIVE", "audio_seconds": 2.0, "motion": STILL},
        ]
    }
    spans = qc.moving_spans(production, {1: 5.0, 2: 3.0, 3: 6.0})
    assert spans == [(1, 0.0, 5.0)]
    times = [i / 30 for i in range(30 * 14)]
    # Inside scene 1 every fifth frame repeats; the card and the still are frozen throughout.
    values = [(0.0 if i % 5 == 0 else 1.2) if t < 5.0 else 0.0 for i, t in enumerate(times)]
    reading = qc.MotionReading(values=values, times=times, mean=0.0, width=540, fps=30.0)
    share = qc.duplicate_share(reading, spans)
    assert share == pytest.approx(0.2, abs=0.01)
    failures, _ = technical_problems(
        GOOD_PROBE,
        environment="PRODUCTION",
        timeline_fps=30,
        narration_seconds=29.5,
        duplicate_share=share,
    )
    assert any("dublate" in f for f in failures)
    assert qc.duplicate_share(reading, []) is None


# ------------------------------------- 7. one unit for every clip; duplicates on lossless shots


def _slow_turn(target: Path, *, codec: list[str], fps: int = 24, seconds: float = 3.0) -> Path:
    """A slow, smooth camera turn: every frame differs a little from the one before it."""
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=s=540x960:r={fps}:d={seconds},rotate=a='t*0.02':c=gray",
        *codec,
        str(target),
    )
    return target


@requires_ffmpeg
def test_a_ten_bit_clip_is_measured_in_the_same_unit_as_an_eight_bit_one(tmp_path):
    """Runway delivers part of its clips as 10-bit HEVC. signalstats reports YDIF in the
    source's own bit depth, so a 10-bit clip read four times its 8-bit motion and passed the
    8-bit floors four times too easily (Nepal motion_01: 1.00 read, 0.26 in 8-bit)."""
    eight = _slow_turn(
        tmp_path / "eight.mp4", codec=["-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p"]
    )
    ten = _slow_turn(
        tmp_path / "ten.mkv",
        codec=["-c:v", "ffv1", "-pix_fmt", "yuv420p10le"],
    )
    a = measure_motion(FFMPEG, eight)
    b = measure_motion(FFMPEG, ten)
    assert a is not None and b is not None
    assert b.mean == pytest.approx(a.mean, rel=0.15), (a.mean, b.mean)


@requires_ffmpeg
def test_duplicates_are_counted_on_the_lossless_shots_not_the_lossy_film(tmp_path):
    """After the final CRF 17 encode a slow vendor clip reads frame-to-frame YDIF under 0.05,
    the old duplicate line, so the zero-credit Nepal rehearsal failed technical QC with
    '12,8% din cadrele ... dublate' on a clip with no repeated frame. On the lossless shot a
    repeated frame reads exactly 0 and the slowest real motion clearly more."""
    from app.media.qc import shot_duplicate_share

    lossless = ["-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p"]
    smooth = _slow_turn(tmp_path / "shot_01.mp4", codec=lossless)
    # The same turn shot at 24 and shown at 30 fps: one frame in five repeats.
    _ffmpeg("-i", str(smooth), "-vf", "fps=30", *lossless, str(tmp_path / "shot_02.mp4"))
    production = {
        "shots": [
            {"scene_index": 1, "file": "shot_01.mp4"},
            {"scene_index": 2, "file": "shot_02.mp4"},
        ]
    }
    assert shot_duplicate_share(FFMPEG, production, tmp_path, [(1, 0.0, 3.0)]) == 0.0
    share = shot_duplicate_share(FFMPEG, production, tmp_path, [(2, 3.0, 6.0)])
    assert share is not None and 0.15 <= share <= 0.25, share
    # A moving scene whose shot file is gone cannot be counted this way.
    assert shot_duplicate_share(FFMPEG, production, tmp_path, [(3, 6.0, 9.0)]) is None


# ------------------------------------- 8. silent cards and full breaths against the narration
#
# The timeline used to shrink every 0.35 s breath so the film stayed within 0.9 s of its
# words: six speaking scenes kept about 0.11 s each and the cuts felt rushed. And a scene with
# no words at all (a black end card, a silent title) counted as film over narration. Quality
# control now allows the narration, the breaths the timeline plans after each scene's words,
# and the silent composed cards, each up to its own maximum, plus the one second it always
# allowed.


def _timeline_production(*scenes, tail=0.35):
    """A render's record with its timeline: (index, kind, spoken seconds, span seconds)."""
    clock = 0.0
    spans, entries = [], []
    for index, kind, spoken, seconds in scenes:
        spans.append(
            {
                "scene_index": index,
                "start": round(clock, 6),
                "end": round(clock + seconds, 6),
                "join_in": "cut",
                "dissolve_seconds": 0.0,
                "shot_seconds": seconds,
                "moving": False,
                "composed": kind != "LIVE",
                "held_seconds": 0.0,
            }
        )
        entries.append({"scene_index": index, "scene_kind": kind, "audio_seconds": spoken})
        clock += seconds
    return {
        "scenes": entries,
        "timeline": {
            "fps": 24,
            "spoken_tail_seconds": tail,
            "film_seconds": round(clock, 6),
            "spans": spans,
        },
    }


SIX_SPEAKING = [(n, "LIVE", 5.0, 5.35) for n in range(1, 7)]


def test_the_silent_card_maximums_come_from_what_each_card_must_show():
    """A black end card is a beat of silence or the closing call to action (the writer's
    spec): 2 s. A silent title must be read: 2.5 s. A silent chart must finish growing its
    four bars and hold: the card's own animation, 3.75 s, inside 4 s."""
    from app.media import cards

    assert qc.MAX_SILENT_CARD_SECONDS == {"BLACK": 2.0, "TITLE_CARD": 2.5, "DATA_CARD": 4.0}
    four_bars = (
        cards.BAR_START_SECONDS
        + cards.BAR_STAGGER_SECONDS * (cards.MAX_BARS - 1)
        + cards.BAR_GROW_SECONDS
        + cards.VALUE_DELAY_SECONDS
        + cards.TEXT_FADE_SECONDS
        + cards.HOLD_SECONDS
    )
    assert four_bars <= qc.MAX_SILENT_CARD_SECONDS["DATA_CARD"]
    assert qc.BREATH_SECONDS == 0.35


def test_a_silent_end_card_and_full_breaths_are_not_counted_against_the_narration():
    production = _timeline_production(*SIX_SPEAKING, (7, "BLACK", 0.0, 2.0))
    budget = qc.film_length_budget(production)
    assert budget["narration_seconds"] == pytest.approx(30.0)
    assert budget["speaking_scenes"] == 6
    assert budget["breath_seconds"] == pytest.approx(2.1)
    assert budget["silent_card_seconds"] == pytest.approx(2.0)
    assert budget["silent_cards"] == [
        {"scene_index": 7, "kind": "BLACK", "seconds": 2.0, "max_seconds": 2.0, "within": True}
    ]
    assert budget["overruns_ro"] == []
    assert budget["allowed_seconds"] == pytest.approx(30.0 + 2.1 + 2.0 + 1.0)

    probe = {**GOOD_PROBE, "duration_seconds": 34.1}
    failures, warnings = technical_problems(
        probe, environment="PRODUCTION", timeline_fps=30, narration_seconds=30.0, budget=budget
    )
    assert failures == [] and warnings == []
    # The rule as it was fails the same film by 3.1 s.
    failures, _ = technical_problems(
        probe, environment="PRODUCTION", timeline_fps=30, narration_seconds=30.0
    )
    assert any("narați" in f for f in failures)


def test_a_silence_longer_than_its_card_allows_still_fails_and_names_the_scene():
    production = _timeline_production(*SIX_SPEAKING, (7, "BLACK", 0.0, 3.4))
    budget = qc.film_length_budget(production)
    assert budget["silent_cards"][0]["within"] is False
    # Only the card's own maximum is allowed for; the rest is film over the narration.
    assert budget["silent_card_seconds"] == pytest.approx(2.0)
    assert len(budget["overruns_ro"]) == 1
    overrun = budget["overruns_ro"][0]
    assert "Scena 7" in overrun and "3,4 s" in overrun and "2,0 s" in overrun

    probe = {**GOOD_PROBE, "duration_seconds": 35.5}
    failures, _ = technical_problems(
        probe, environment="PRODUCTION", timeline_fps=30, narration_seconds=30.0, budget=budget
    )
    assert overrun in failures
    # In TEST the same floors warn, as every delivery floor does.
    failures, warnings = technical_problems(
        probe, environment="TEST", timeline_fps=30, narration_seconds=30.0, budget=budget
    )
    assert overrun not in failures and overrun in warnings


def test_a_silent_live_scene_is_not_a_card_and_counts_against_the_narration():
    production = _timeline_production(*SIX_SPEAKING, (7, "LIVE", 0.0, 2.0))
    budget = qc.film_length_budget(production)
    assert budget["silent_cards"] == [] and budget["silent_card_seconds"] == 0.0
    failures, _ = technical_problems(
        {**GOOD_PROBE, "duration_seconds": 34.1},
        environment="PRODUCTION",
        timeline_fps=30,
        narration_seconds=30.0,
        budget=budget,
    )
    assert any("narați" in f for f in failures), failures


def test_a_card_with_words_is_narration_and_has_its_breath():
    production = _timeline_production((1, "LIVE", 5.0, 5.35), (2, "DATA_CARD", 3.0, 3.35))
    budget = qc.film_length_budget(production)
    assert budget["silent_cards"] == []
    assert budget["speaking_scenes"] == 2
    assert budget["breath_seconds"] == pytest.approx(0.7)


def test_full_breaths_pass_and_a_film_past_them_fails_naming_the_breaths():
    production = _timeline_production(*SIX_SPEAKING)
    budget = qc.film_length_budget(production)
    # 30 s of words, six full breaths (2.1 s), plus the second: 33.1 s.
    for seconds, passes in ((32.1, True), (33.1, True), (33.2, False)):
        failures, _ = technical_problems(
            {**GOOD_PROBE, "duration_seconds": seconds},
            environment="PRODUCTION",
            timeline_fps=30,
            narration_seconds=30.0,
            budget=budget,
        )
        assert (failures == []) is passes, (seconds, failures)
        if not passes:
            assert any("respirați" in f and "2,1 s" in f for f in failures), failures


def test_the_breath_is_the_one_the_timeline_recorded():
    production = _timeline_production(*SIX_SPEAKING, tail=0.25)
    assert qc.film_length_budget(production)["breath_seconds"] == pytest.approx(1.5)


def test_a_render_without_a_timeline_is_budgeted_from_its_scene_record():
    """A render from before the timeline record: the spans are rebuilt from the plan."""
    production = {
        "scenes": [
            {"scene_index": 1, "scene_kind": "LIVE", "audio_seconds": 4.0},
            {"scene_index": 2, "scene_kind": "BLACK", "audio_seconds": 0.0},
        ]
    }
    budget = qc.film_length_budget(production, {1: 4.0, 2: 1.5})
    assert budget["silent_cards"] == [
        {"scene_index": 2, "kind": "BLACK", "seconds": 1.5, "max_seconds": 2.0, "within": True}
    ]
    assert budget["breath_seconds"] == pytest.approx(0.35)
    # A record that did not measure the narration has no budget to give.
    assert qc.film_length_budget({"scenes": [{"scene_index": 1}]})["narration_seconds"] is None


@requires_ffmpeg
def test_quality_control_reads_the_budget_off_the_films_own_timeline(engine, tmp_path):
    """10.5 s of film over 8 s of words: two full breaths and a 1.8 s silent end card are
    the film the Owner asked for, not 1.5 s too long."""
    film = _hot_film(tmp_path)
    production = _timeline_production(
        (1, "LIVE", 4.0, 4.35), (2, "LIVE", 4.0, 4.35), (3, "BLACK", 0.0, 1.8)
    )
    asset_id = _film_row(engine, tmp_path, film, narration=8.0, production_extra=production)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"

    report = evaluate_media_qc(engine, asset_id, str(uuid4()))

    technical = report["checks_json"]["technical_qc"]
    assert technical["length_budget"]["silent_card_seconds"] == pytest.approx(1.8)
    assert technical["length_budget"]["breath_seconds"] == pytest.approx(0.7)
    reasons = report["failure_reasons_json"]
    assert not any("narați" in reason for reason in reasons), reasons
    # The file's other faults are still there: this film is not passed by the budget.
    assert report["status"] == "FAILED"
