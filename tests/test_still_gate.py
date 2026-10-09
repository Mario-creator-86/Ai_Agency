"""The stills gate: nothing is animated until someone has looked at the still.

What is asserted, all at 0 credits and with every provider faked:

- the YuNet face detector reports NOT_RUN — never "no faces" — when its model file is
  missing or is not the pinned file, and that NOT_RUN blocks a still in PRODUCTION and only
  warns in TEST;
- a face found by EITHER detector blocks the still: the local detector's face is not
  overruled by a vision model that says it saw none, and the reverse;
- a vision model that gave no entry for the still blocks it as "nu a fost privită";
- the sharpness check (at 1080 px: the trimmed Laplacian variance of the median of the
  sharpest tenth of the tiles, floor 30, and the share of it a still keeps when halved and
  restored, at most 48 %) passes a sharp subject before a dark, soft background (the five
  stills of 2026-10-09 the old whole-picture pooling rejected) and fails a blurred still, a
  blurred one carrying a hard line or a small box, and a half-resolution picture upscaled;
  baked motion blur blocks a static shot; a degenerate still blocks; the palette distance is
  a score and a warning, never a block;
- the best passing candidate is chosen by its check score (the sharper of two passing takes
  wins), a failing still is re-rolled at most twice with its violation rewritten as a
  positive instruction, then goes to the Owner.

Fixtures: tests/fixtures/nepal_1d530880/scene_0N.jpg are 540x960 JPEG (q 3) copies of the
six stills Runway delivered for the second Nepal render (1530x2720 PNG, in
backend/storage/media/1d530880-.../scene_0N.png). Looked at by eye on 2026-09-27: scenes 1
and 2 have no people; scene 3 three villagers with faces, scene 4 a farmer in three-quarter
profile, scene 5 two panels of seated women and children, scene 6 a woman's face filling
the right half. The sharpness measurements need the full-resolution stills and read them
from the media folder, read-only; they skip where that folder is absent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from app.media import faces, still_gate
from app.media.faces import FaceCount, count_faces
from app.media.picture_qc import StillJudgement, StillVerdict
from app.media.still_gate import (
    FINE_DETAIL_KEPT_MAX,
    MAX_REROLLS,
    MOTION_BLUR_ANISOTROPY,
    SHARPNESS_FLOOR,
    CheckResult,
    StillPlan,
    choose_best,
    decide,
    local_checks,
    measure_focus,
    measure_sharpness,
    next_step,
    positive_instruction,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "nepal_1d530880"
NEPAL_MEDIA = ROOT / "backend" / "storage" / "media" / "1d530880-c94a-48a1-baf5-6ad7c1796a6d"
#: The five scene-1 stills RunPod delivered on 2026-10-09 for «The Particle That Shouldn't
#: Exist (But Does)» (1530x2720 PNG), read only; the gate rejected them all at 70-182.
PARTICLE_STILLS = (
    ROOT / "backend" / "storage" / "media" / "babcf272-0667-41b9-ae70-27304eef92ca" / "stills"
)
#: What they read, measured 2026-10-09 (still_gate's docstring): (sharpness, fine detail kept).
PARTICLE_READINGS = {
    "scene_01_ac5b5e97_c1.png": (66.6, 0.157),
    "scene_01_340ebcb1_c2.png": (255.4, 0.276),
    "scene_01_14aec523_c1.png": (69.7, 0.167),
    "scene_01_b5f88e79_c2.png": (66.8, 0.205),
    "scene_01_d1e900d3_c1.png": (260.9, 0.201),
}
#: Drawn on a blurred picture, each is one hard line or a thin outline: letterbox bars (top and
#: bottom, 12 % each) and a small white box in a corner (18 % x 5 % of the frame).
LETTERBOX = (
    "drawbox=x=0:y=0:w=iw:h=ih*0.12:color=black:t=fill,"
    "drawbox=x=0:y=ih*0.88:w=iw:h=ih*0.12:color=black:t=fill"
)
SMALL_BOX = "drawbox=x=iw*0.78:y=ih*0.03:w=iw*0.18:h=ih*0.05:color=white:t=4"
#: A dark background kept soft on purpose (a tunnel out of focus): its tiles vary (luma
#: standard deviation 5-12), so the old pooling counted them, but nothing in it is sharp.
SOFT_DARK = "color=c=black:s=1080x1920,format=gray,geq=lum='44+18*sin(X/70)+18*sin(Y/90)'"
FLAT_DARK = "color=c=0x141414:s=1080x1920"
#: The sharp subject: fine texture (a coverall's weave), 2 x 4 tiles of the 8 x 14 grid.
SUBJECT = "color=c=0x6a6a6a:s=270x548,noise=alls=10:allf=t"
FFMPEG = shutil.which("ffmpeg")

needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")


def fixture(scene: int) -> Path:
    return FIXTURES / f"scene_{scene:02d}.jpg"


def original(scene: int) -> Path:
    return NEPAL_MEDIA / f"scene_{scene:02d}.png"


def plan(scene: int = 1, *, move: str = "slow push-in", faces_forbidden: bool = True, **kw):
    return StillPlan(
        scene=scene,
        still_prompt=kw.pop("still_prompt", "A remote Himalayan village under storm clouds."),
        camera_move=move,
        faces_forbidden=faces_forbidden,
        bible_rules=kw.pop("bible_rules", ("No human faces appear",)),
        palette_words=kw.pop("palette_words", ()),
        **kw,
    )


def clean_verdict(scene: int = 1, **changes) -> StillJudgement:
    fields = {
        "scene": scene,
        "faces_visible": False,
        "readable_text": False,
        "matches_plan": True,
        "look_ok": True,
        "technical_ok": True,
        "bible_violations": "none",
        "verdict": "buy_motion",
        "reason": "the village under storm clouds, as planned",
    }
    fields.update(changes)
    return StillJudgement(
        status="MEASURED",
        verdict=StillVerdict(**fields),
        detail_ro="",
        run_id="run-1",
        looked_by="Video Editor",
        image_width=1080,
    )


def no_faces(path, **_):
    return FaceCount(status="MEASURED", faces=0, boxes=(), detail_ro="0 fețe")


def one_face(path, **_):
    return FaceCount(
        status="MEASURED", faces=1, boxes=((200, 300, 60, 70, 0.93),), detail_ro="1 față"
    )


def render(tmp_path: Path, name: str, source: str, vf: str | None = None, lavfi=False) -> Path:
    target = tmp_path / name
    command = [FFMPEG, "-v", "error", "-y"]
    command += ["-f", "lavfi"] if lavfi else []
    command += ["-i", source, "-frames:v", "1"]
    command += ["-vf", vf] if vf else []
    command += ["-q:v", "2", str(target)]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    return target


# --------------------------------------------------------------------------- fixtures


@needs_ffmpeg
def test_the_nepal_fixtures_are_downscaled_540x960_jpeg_copies():
    ffprobe = shutil.which("ffprobe")
    assert ffprobe
    for scene in range(1, 7):
        probed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name,width,height",
                "-of",
                "json",
                str(fixture(scene)),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        stream = json.loads(probed.stdout)["streams"][0]
        assert (stream["codec_name"], stream["width"], stream["height"]) == ("mjpeg", 540, 960)


# ------------------------------------------------------------------------- the detector


def test_a_missing_yunet_model_is_not_run_never_zero_faces(tmp_path):
    counted = count_faces(fixture(6), model_path=tmp_path / "absent.onnx")

    assert counted.status == "NOT_RUN"
    assert counted.faces is None
    assert "lipsește" in counted.detail_ro


def test_a_model_that_is_not_the_pinned_file_is_not_run(tmp_path):
    impostor = tmp_path / "yunet_2023mar.onnx"
    impostor.write_bytes(b"not the model")

    counted = count_faces(fixture(6), model_path=impostor)

    assert counted.status == "NOT_RUN" and counted.faces is None
    assert "amprenta" in counted.detail_ro


def test_the_pinned_model_is_the_published_yunet_2023mar():
    # Pinned from the SHA256 Hugging Face publishes for opencv/face_detection_yunet
    # face_detection_yunet_2023mar.onnx (233 kB), read 2026-09-27.
    assert faces.YUNET_SHA256 == "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
    assert faces.YUNET_MODEL_PATH.name == "yunet_2023mar.onnx"


@pytest.mark.skipif(
    not faces.detector_available(),
    reason="YuNet is not installed (opencv-python-headless and the pinned ONNX file)",
)
def test_yunet_counts_on_the_nepal_stills_are_measured():
    """Measure first, then assert. Until opencv and the model are installed this test skips
    and the counts are UNMEASURED; the assertions are the robust part of the eye-checked
    ground truth (no people at all in 1 and 2; a large, clear face in 4 and 6)."""
    measured = {scene: count_faces(fixture(scene)) for scene in range(1, 7)}
    print({scene: (c.status, c.faces) for scene, c in measured.items()})
    assert all(c.status == "MEASURED" for c in measured.values())
    assert measured[1].faces == 0 and measured[2].faces == 0
    assert measured[4].faces >= 1 and measured[6].faces >= 1


@needs_ffmpeg
def test_a_missing_yunet_model_blocks_in_production(tmp_path):
    missing = tmp_path / "absent.onnx"
    checks = local_checks(fixture(1), plan(), environment="PRODUCTION", face_model=missing)
    face = next(c for c in checks if c.code == "faces")
    assert face.status == "NOT_RUN" and face.blocking is True

    report = decide(fixture(1), plan(), checks, clean_verdict(), environment="PRODUCTION")

    assert report.decision == "BLOCKED"
    assert any("YuNet" in reason for reason in report.reasons_ro)


@needs_ffmpeg
def test_a_missing_yunet_model_only_warns_in_test(tmp_path):
    missing = tmp_path / "absent.onnx"
    # Only the faces check is run: the 540 px fixture is soft when measured at 1080 px, and
    # the sharpness floor has its own tests below.
    checks = local_checks(
        fixture(1), plan(), environment="TEST", face_model=missing, measure=("faces",)
    )
    face = next(c for c in checks if c.code == "faces")
    assert face.status == "NOT_RUN" and face.blocking is False

    report = decide(fixture(1), plan(), checks, clean_verdict(), environment="TEST")

    assert report.decision == "PASSED"
    assert any("YuNet" in warning for warning in report.warnings_ro)


# ----------------------------------------------------------- either detector blocks


def test_a_face_found_by_yunet_blocks_although_the_vision_model_saw_none():
    checks = local_checks(
        fixture(4), plan(4), environment="TEST", face_counter=one_face, measure=("faces",)
    )

    report = decide(fixture(4), plan(4), checks, clean_verdict(4), environment="TEST")

    assert report.decision == "BLOCKED"
    assert report.faces_found is True
    assert any("YuNet" in reason and "față" in reason for reason in report.reasons_ro)


def test_a_face_seen_by_the_vision_model_blocks_although_yunet_found_none():
    checks = local_checks(
        fixture(3), plan(3), environment="PRODUCTION", face_counter=no_faces, measure=("faces",)
    )

    report = decide(
        fixture(3),
        plan(3),
        checks,
        clean_verdict(3, faces_visible=True, verdict="buy_motion"),
        environment="PRODUCTION",
    )

    assert report.decision == "BLOCKED" and report.faces_found is True
    assert any("modelul de vedere" in reason.lower() for reason in report.reasons_ro)


def test_faces_do_not_block_when_the_bible_allows_them():
    checks = local_checks(
        fixture(6),
        plan(6, faces_forbidden=False, bible_rules=()),
        environment="PRODUCTION",
        face_counter=one_face,
        measure=("faces",),
    )
    face = next(c for c in checks if c.code == "faces")
    assert face.blocking is False and face.value == 1


def test_a_verdict_that_contradicts_its_own_answers_does_not_pass():
    checks = local_checks(
        fixture(1), plan(), environment="TEST", face_counter=no_faces, measure=("faces",)
    )
    for change in (
        {"readable_text": True},
        {"matches_plan": False},
        {"look_ok": False},
        {"technical_ok": False},
        {"bible_violations": "a woman's face in the lower third"},
    ):
        report = decide(fixture(1), plan(), checks, clean_verdict(**change), environment="TEST")
        assert report.decision == "BLOCKED", change


def test_compose_locally_is_an_outcome_not_a_pass():
    checks = local_checks(
        fixture(5), plan(5), environment="TEST", face_counter=no_faces, measure=("faces",)
    )
    report = decide(
        fixture(5),
        plan(5),
        checks,
        clean_verdict(5, verdict="compose_locally", matches_plan=False),
        environment="TEST",
    )
    assert report.decision == "BLOCKED" and report.outcome == "compose_locally"


# ------------------------------------------------------------ the vision model's silence


def test_a_vision_model_with_no_entry_for_the_still_blocks_it(engine):
    from test_picture_qc import give_vision, registry_with, staff

    staffed = staff(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry, model = registry_with(staffed, lambda prompt: json.dumps({"stills": []}))

    report = still_gate.check_still(
        engine,
        registry,
        fixture(1),
        plan(),
        str(uuid4()),
        environment="TEST",
        face_counter=no_faces,
        measure=("faces",),
    )

    assert len(model.calls) == 1
    assert report.decision == "BLOCKED"
    assert report.judgement is not None and report.judgement.status == "NOT_RUN"
    assert any("nu a fost privită" in reason for reason in report.reasons_ro)


def test_no_vision_judgement_at_all_blocks_in_every_environment():
    checks = local_checks(
        fixture(1), plan(), environment="TEST", face_counter=no_faces, measure=("faces",)
    )
    for environment in ("TEST", "PRODUCTION"):
        report = decide(fixture(1), plan(), checks, None, environment=environment)
        assert report.decision == "BLOCKED"
        assert any("nu a fost privită" in reason for reason in report.reasons_ro)


# ------------------------------------------------------------------- sharpness and blur


@needs_ffmpeg
@pytest.mark.skipif(not NEPAL_MEDIA.is_dir(), reason="the Nepal media folder is not here")
def test_the_real_nepal_stills_pass_the_sharpness_check():
    """The six delivered 1530x2720 PNGs read 592, 614, 870, 603, 893 and 331 on the pooled
    measure of 2026-09-27 (scene 6 is half flat black). Their folder was not on the machine
    the measure of 2026-10-09 was written on, so they were not read with it; where it is,
    they pass it, both readings (a false refusal starves a film: 2026-10-09)."""
    for scene in range(1, 7):
        (check,) = local_checks(
            original(scene),
            plan(scene),
            environment="PRODUCTION",
            face_counter=no_faces,
            measure=("sharpness",),
        )
        print(scene, check.value, check.detail_ro)
        assert check.status == "PASSED", (scene, check.detail_ro)


def subject_on(
    tmp_path: Path,
    name: str,
    background: str,
    blur: float | None = None,
    drawn: str | None = None,
) -> Path:
    """A 1080x1920 still: the sharp subject over ``background``, optionally all blurred, then
    optionally with ``drawn`` (ffmpeg filters) drawn over it."""
    target = tmp_path / name
    graph = "[0][1]overlay=405:685,format=gray" + (f",gblur=sigma={blur}" if blur else "")
    graph += f",{drawn}" if drawn else ""
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", background, "-f", "lavfi", "-i"]
        + [SUBJECT, "-filter_complex", graph, "-frames:v", "1", str(target)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return target


@needs_ffmpeg
@pytest.mark.parametrize(("background", "label"), [(SOFT_DARK, "soft"), (FLAT_DARK, "flat")])
def test_a_sharp_subject_on_a_dark_background_passes_and_the_same_blurred_fails(
    tmp_path, background, label
):
    """2026-10-09: five good documentary stills (a sharp worker in a dark tunnel kept soft on
    purpose) read 70-182 pooled over every tile that varied, under the old floor of 250, and
    the film never got past scene 1. Measured here when this test was written: the subject
    (8 of the 112 tiles) reads 576 before either background (73 and 528 pooled), keeping 2 %
    when halved and restored; blurred with sigma 2 it reads 5, with sigma 4 1-2."""
    sharp = subject_on(tmp_path, f"{label}_sharp.png", background)
    focus = measure_focus(FFMPEG, sharp)
    assert focus is not None and focus.sharpness >= 10 * SHARPNESS_FLOOR, focus
    assert focus.fine_kept < FINE_DETAIL_KEPT_MAX / 10, focus
    checks = local_checks(
        sharp, plan(), environment="PRODUCTION", face_counter=no_faces, measure=("sharpness",)
    )
    (sharpness,) = checks
    assert sharpness.status == "PASSED" and sharpness.blocking is False
    for sigma in (2, 4):
        blurred = subject_on(tmp_path, f"{label}_blur{sigma}.png", background, blur=sigma)
        soft = measure_sharpness(FFMPEG, blurred)
        assert soft is not None and soft < SHARPNESS_FLOOR / 5, (sigma, soft)
        (check,) = local_checks(
            blurred,
            plan(),
            environment="PRODUCTION",
            face_counter=no_faces,
            measure=("sharpness",),
        )
        assert check.status == "FAILED" and check.blocking is True
        assert "neclară" in check.detail_ro and str(SHARPNESS_FLOOR) in check.detail_ro


def sharpness_check(path: Path) -> CheckResult:
    (check,) = local_checks(
        path, plan(), environment="PRODUCTION", face_counter=no_faces, measure=("sharpness",)
    )
    return check


@needs_ffmpeg
@pytest.mark.parametrize(("drawn", "label"), [(LETTERBOX, "letterbox"), (SMALL_BOX, "box")])
def test_a_blurred_still_with_one_hard_line_or_a_small_box_on_it_fails(tmp_path, drawn, label):
    """A tile's variance is made by any single hard line in it: the five sharpest tiles of a
    blurred still with letterbox bars (or a box drawn in a corner) read sharp on their mean
    (2026-10-09 review: 262 and 1228 on a real still blurred with sigma 4). Each tile now
    leaves out its strongest 5 %, and a subject's worth of tiles must be sharp: the blurred
    picture reads 1.6-4.6 with them, as without them. On a sharp picture they change nothing."""
    sharp = subject_on(tmp_path, f"sharp_{label}.png", SOFT_DARK, drawn=drawn)
    assert sharpness_check(sharp).status == "PASSED"
    for sigma in (2, 3, 4):
        blurred = subject_on(tmp_path, f"g{sigma}_{label}.png", SOFT_DARK, blur=sigma, drawn=drawn)
        check = sharpness_check(blurred)
        assert check.value is not None and check.value < SHARPNESS_FLOOR / 5, (sigma, check)
        assert check.status == "FAILED" and check.blocking is True and "neclară" in check.detail_ro


@needs_ffmpeg
@pytest.mark.parametrize("scene", range(1, 7))
def test_a_half_resolution_still_upscaled_fails_however_much_texture_it_has(tmp_path, scene):
    """The Nepal 540 px fixtures blown up to the vendor's 1530x2720 (bicubic) carry enough
    texture to read 52-295 on the sharpness, over the floor (2026-10-09 review: they passed the
    sharpest-tiles mean at 369-598), but halved and restored they keep 52-56 % of their
    Laplacian energy: what they have is not fine detail. A sharp still keeps 16-28 %."""
    upscaled = render(
        tmp_path, f"up_{scene}.png", str(fixture(scene)), vf="scale=1530:2720:flags=bicubic"
    )
    focus = measure_focus(FFMPEG, upscaled)
    assert focus is not None and focus.sharpness >= SHARPNESS_FLOOR, focus
    assert focus.fine_kept > FINE_DETAIL_KEPT_MAX, focus
    check = sharpness_check(upscaled)
    assert check.status == "FAILED" and check.blocking is True
    assert "moale" in check.detail_ro and f"{FINE_DETAIL_KEPT_MAX:.0%}" in check.detail_ro


@needs_ffmpeg
@pytest.mark.skipif(not PARTICLE_STILLS.is_dir(), reason="the 2026-10-09 stills are not here")
def test_the_stills_the_old_floor_rejected_pass_and_their_softened_copies_fail(tmp_path):
    """The five delivered PNGs, read only; their copies are written to tmp_path. Each copy is
    a way a still arrives soft (still_gate's docstring has every reading)."""
    for name, (sharpness, kept) in PARTICLE_READINGS.items():
        still = PARTICLE_STILLS / name
        focus = measure_focus(FFMPEG, still)
        assert focus is not None, name
        assert abs(focus.sharpness - sharpness) <= 0.05 * sharpness, (name, focus)
        assert abs(focus.fine_kept - kept) <= 0.02, (name, focus)
        assert focus.sharpness >= 2 * SHARPNESS_FLOOR, (name, focus)
        assert focus.fine_kept <= FINE_DETAIL_KEPT_MAX / 1.5, (name, focus)
        assert sharpness_check(still).status == "PASSED", name
        softened = {
            "sigma 1 at 1080": "scale=1080:-2,gblur=sigma=1",
            "saved at 540 px": "scale=540:-2:flags=bicubic",
        }
        if name == "scene_01_340ebcb1_c2.png":  # the sharpest, and the most kept
            softened |= {
                "sigma 2 at 1080": "scale=1080:-2,gblur=sigma=2",
                "sigma 4 at 1530": "gblur=sigma=4",
                "512 px and back": "scale=512:-2:flags=bicubic,scale=1530:2720:flags=bicubic",
                "sigma 4, letterbox": f"scale=1080:-2,gblur=sigma=4,{LETTERBOX}",
                "sigma 4, small box": f"scale=1080:-2,gblur=sigma=4,{SMALL_BOX}",
            }
        for n, (how, vf) in enumerate(softened.items()):
            copy = render(tmp_path, f"{n}_{name}", str(still), vf=vf)
            check = sharpness_check(copy)
            assert check.status == "FAILED" and check.blocking is True, (name, how, check)


def test_the_sharper_of_two_passing_takes_wins_and_the_score_never_saturates():
    """The score's sharpness term was value / 1000, sized for the old pooled readings: the
    sharpest-tiles readings filled it for most stills. On a log scale from the floor nothing
    in range fills it, and the sharper take of the same scene ranks first."""

    def passing(scene: int, sharpness: float):
        checks = [
            CheckResult("degenerate", "PASSED", False, None, "structură de imagine"),
            CheckResult("sharpness", "PASSED", False, sharpness, f"claritate {sharpness:.0f}"),
            CheckResult("motion_blur", "PASSED", False, 1.4, "raport 1.4"),
            CheckResult("faces", "PASSED", False, 0.0, "0 fețe"),
        ]
        report = decide(
            fixture(scene), plan(scene), checks, clean_verdict(scene), environment="PRODUCTION"
        )
        assert report.decision == "PASSED", report.reasons_ro
        return report

    # The softest and the sharpest of the 2026-10-09 stills, then readings past the old scale.
    softer, sharper = passing(1, 66.6), passing(2, 260.9)
    assert choose_best([softer, sharper]) is sharper and choose_best([sharper, softer]) is sharper
    scores = [passing(1, value).score for value in (66.6, 260.9, 1200.0, 2900.0)]
    assert scores == sorted(scores) and len(set(scores)) == 4, scores
    assert passing(1, SHARPNESS_FLOOR).score < scores[0]


@needs_ffmpeg
def test_a_blurred_still_fails_the_sharpness_floor(tmp_path):
    # A detailed 1080x1920 field passes; the same field blurred does not.
    sharp = render(
        tmp_path,
        "sharp.png",
        "color=c=gray:s=1080x1920,noise=alls=40:allf=t",
        lavfi=True,
    )
    blurred = render(tmp_path, "blurred.png", str(sharp), vf="gblur=sigma=3")
    # And a real Nepal still, softened: the 540 px fixture blurred once more.
    nepal_blurred = render(tmp_path, "nepal_blurred.png", str(fixture(3)), vf="gblur=sigma=2")

    assert measure_sharpness(FFMPEG, sharp) >= SHARPNESS_FLOOR
    assert measure_sharpness(FFMPEG, blurred) < SHARPNESS_FLOOR
    assert measure_sharpness(FFMPEG, nepal_blurred) < SHARPNESS_FLOOR

    checks = local_checks(
        nepal_blurred, plan(3), environment="TEST", face_counter=no_faces, ffmpeg_path=FFMPEG
    )
    sharpness = next(c for c in checks if c.code == "sharpness")
    assert sharpness.status == "FAILED" and sharpness.blocking is True
    assert str(SHARPNESS_FLOOR) in sharpness.detail_ro


@needs_ffmpeg
def test_baked_motion_blur_blocks_a_static_shot_and_warns_on_a_moving_one(tmp_path):
    base = render(tmp_path, "base.png", str(fixture(3)), vf="scale=1080:1920:flags=lanczos")
    smeared = render(tmp_path, "smeared.png", str(base), vf="avgblur=sizeX=12:sizeY=1")

    static = local_checks(
        smeared,
        plan(3, move="static"),
        environment="TEST",
        face_counter=no_faces,
        measure=("motion_blur",),
    )
    blur = next(c for c in static if c.code == "motion_blur")
    assert blur.status == "FAILED" and blur.blocking is True
    assert blur.value >= MOTION_BLUR_ANISOTROPY

    moving = local_checks(
        smeared,
        plan(3, move="slow pan left"),
        environment="TEST",
        face_counter=no_faces,
        measure=("motion_blur",),
    )
    blur = next(c for c in moving if c.code == "motion_blur")
    assert blur.status == "WARNING" and blur.blocking is False

    clean = local_checks(
        base,
        plan(3, move="static"),
        environment="TEST",
        face_counter=no_faces,
        measure=("motion_blur",),
    )
    assert next(c for c in clean if c.code == "motion_blur").status == "PASSED"


@needs_ffmpeg
def test_a_degenerate_still_blocks(tmp_path):
    blank = render(tmp_path, "blank.png", "color=c=0x777777:s=1080x1920", lavfi=True)

    checks = local_checks(
        blank, plan(), environment="TEST", face_counter=no_faces, measure=("degenerate",)
    )

    degenerate = next(c for c in checks if c.code == "degenerate")
    assert degenerate.status == "FAILED" and degenerate.blocking is True


def test_without_an_encoder_the_picture_checks_are_not_run_and_block_in_production(
    monkeypatch,
):
    monkeypatch.setattr(still_gate, "find_ffmpeg", lambda configured=None: None)

    production = local_checks(fixture(1), plan(), environment="PRODUCTION", face_counter=no_faces)
    test = local_checks(fixture(1), plan(), environment="TEST", face_counter=no_faces)

    sharp = next(c for c in production if c.code == "sharpness")
    assert sharp.status == "NOT_RUN" and sharp.blocking is True
    assert next(c for c in test if c.code == "sharpness").blocking is False


# ---------------------------------------------------------------------------- palette


@needs_ffmpeg
def test_the_palette_distance_is_a_score_and_a_warning_never_a_block(tmp_path):
    words = ("slate blue", "muted greens")
    near = render(tmp_path, "near.png", "color=c=0x5A6E8C:s=1080x1920", lavfi=True)
    far = render(tmp_path, "far.png", "color=c=0xFF2020:s=1080x1920", lavfi=True)

    def palette(path):
        checks = local_checks(
            path,
            plan(palette_words=words),
            environment="PRODUCTION",
            face_counter=no_faces,
            measure=("palette",),
        )
        return next(c for c in checks if c.code == "palette")

    close, clash = palette(near), palette(far)
    assert close.value < clash.value
    assert close.status == "PASSED" and clash.status == "WARNING"
    assert clash.blocking is False

    unknown = local_checks(
        near,
        plan(palette_words=("the colour of longing",)),
        environment="PRODUCTION",
        face_counter=no_faces,
        measure=("palette",),
    )
    check = next(c for c in unknown if c.code == "palette")
    assert check.status == "NOT_RUN" and check.blocking is False


# ------------------------------------------------------- choosing, re-rolling, escalating


def _report(scene, *, decision, sharp=600.0):
    checks = local_checks(
        fixture(scene), plan(scene), environment="TEST", face_counter=no_faces, measure=("faces",)
    )
    judgement = (
        clean_verdict(scene) if decision == "PASSED" else clean_verdict(scene, look_ok=False)
    )
    report = decide(fixture(scene), plan(scene), checks, judgement, environment="TEST")
    # Two passing candidates differ in their measured score; the gate ranks by it.
    return replace(report, score=sharp / 1000)


def test_the_best_passing_candidate_is_chosen_by_score():
    softer = _report(1, decision="PASSED", sharp=400.0)
    sharper = _report(2, decision="PASSED", sharp=800.0)
    failing = _report(3, decision="BLOCKED", sharp=2000.0)

    assert choose_best([softer, failing, sharper]) is sharper
    assert choose_best([failing]) is None
    assert choose_best([]) is None


def test_a_failing_still_is_rerolled_twice_with_a_positive_instruction_then_goes_to_the_owner():
    checks = local_checks(
        fixture(4), plan(4), environment="TEST", face_counter=one_face, measure=("faces",)
    )
    failed = decide(fixture(4), plan(4), checks, clean_verdict(4), environment="TEST")

    assert MAX_REROLLS == 2
    first = next_step(failed, rerolls_done=0)
    second = next_step(failed, rerolls_done=1)
    third = next_step(failed, rerolls_done=2)

    assert first.action == "reroll" and second.action == "reroll"
    assert third.action == "needs_owner"
    assert "Proprietar" in third.reason_ro
    instruction = first.instruction
    assert "seen from behind" in instruction and "faces not visible" in instruction
    # Positive words only: nothing for the model to avoid, no "no X" list.
    assert not any(word in instruction.lower().split() for word in ("no", "avoid", "without"))


def test_positive_instructions_for_each_local_violation():
    assert "sharp focus" in positive_instruction(["sharpness"])
    assert "crisp" in positive_instruction(["motion_blur"])
    assert "plain surfaces" in positive_instruction(["readable_text"])
    assert positive_instruction([]) == ""


def test_a_passing_still_buys_motion_and_compose_locally_routes_to_a_card():
    checks = local_checks(
        fixture(1), plan(), environment="TEST", face_counter=no_faces, measure=("faces",)
    )
    passed = decide(fixture(1), plan(), checks, clean_verdict(), environment="TEST")
    assert next_step(passed, rerolls_done=0).action == "buy_motion"

    card = decide(
        fixture(5),
        plan(5),
        checks,
        clean_verdict(5, verdict="compose_locally", matches_plan=False),
        environment="TEST",
    )
    assert next_step(card, rerolls_done=0).action == "compose_locally"


def test_the_gate_imports_no_provider_adapter():
    source = (ROOT / "backend" / "app" / "media" / "still_gate.py").read_text(encoding="utf-8")
    source += (ROOT / "backend" / "app" / "media" / "faces.py").read_text(encoding="utf-8")
    assert "app.providers" not in source
    assert "httpx" not in source
