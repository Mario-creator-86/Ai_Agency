"""Offline regression tests for test faces strict.

Providers are faked; all data is synthetic."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from app.media import faces
from app.media.faces import (
    MAX_DETECT_WIDTH,
    PEOPLE_STRICT,
    SCORE_THRESHOLD,
    STRICT_SIZES,
    STRICT_THRESHOLD,
    FaceScore,
    FacesNotMeasured,
    count_faces,
    count_faces_strict,
    face_scores,
    merge_faces,
    strict_faces,
    strict_sizes,
)

ROOT = Path(__file__).resolve().parents[1]
NEPAL = ROOT / "tests" / "fixtures" / "factual_sample"
MEDIA = Path(os.environ.get("STUDIO_REAL_MEDIA", ROOT / "backend" / "storage" / "media"))
CYCLOTRON = MEDIA / "00000000-0000-4000-8000-000000000160"
PARTICLE = MEDIA / "1c038a99-e2c7-49c0-af97-ea7437f412bb"
FFMPEG = shutil.which("ffmpeg")

needs_yunet = pytest.mark.skipif(
    not faces.detector_available(),
    reason="YuNet is not installed (opencv-python-headless and the pinned ONNX file)",
)
needs_cyclotron = pytest.mark.skipif(
    not (CYCLOTRON / "stills").is_dir(),
    reason="the cyclotron film's media (00000160) is not on this machine",
)
needs_particle = pytest.mark.skipif(
    not (PARTICLE / "stills").is_dir(),
    reason="the media of «The Particle That Shouldn't Exist» (1c038a99) is not here",
)

#: Still 4be4364e: the bald man's face, as YuNet boxes it at 540 px (0.634), in still pixels.
BALD_MAN = (414, 581, 132, 174)

#: The six scene-1 stills of 00000160, every one with people at the table behind the device
#: (looked at 2026-10-12): 4be4364e is the approved one, the rest were refused or kept PAID.
SCENE_ONE_STILLS = (
    "scene_01_3bc31f47_c1.png",  # 4be4364e, APPROVED: the bald man and the blonde woman
    "scene_01_c32bf70b_c1.png",  # 7a0be480: a man's profile at the window
    "scene_01_a8f3d5bc_c2.png",  # 3ab7ffd8, PAID: a man in glasses, in profile
    "scene_01_3b7b8a3f_c1.png",  # 4c3d35e8: a face between two backs
    "scene_01_c9f3fa83_c2.png",  # 861036ba: a head turned three-quarters away
    "scene_01_f4b20bec_c2.png",  # 8964825d: an ear and a cheek behind the device
)
#: The six clips bought from 4be4364e; clip QC refused each for faces.
SCENE_ONE_CLIPS = ("83e6d8d8", "d4623c7f", "941b4a16", "a7eabd5a", "597fff11", "10335dcb")
#: Scene-4 stills with partial faces behind the device (the investigation of 2026-10-12):
#: 657f2627 and faf0d555 are PAID back-ups `usable_take` could still choose, 7471cabb the
#: gate-approved still clips B to E were made from.
SCENE_FOUR_FACES = (
    "scene_04_51b1934b_c1.png",
    "scene_04_973ce748_c2.png",
    "scene_04_b0a19b71_c1.png",
)
#: The APPROVED stills of 2026-10-12 that show no person (looked at one by one).
CLEAN_CYCLOTRON = (
    "scene_03_62b36132_c2.png",  # ea5a56ae: the dees on a wooden desk
    "scene_04_aa45ea05_c2.png",  # e5692049: the chamber, the medal, a beige lamp
    "scene_05_60498d8c_c1.png",  # b53302d1: the napkin with the spiral
)
CLEAN_PARTICLE = (
    "scene_01_cb92812a_c1.png",  # 2b8acd8e: the detector ring in a cavern
    "scene_02_4e0e405f_c2.png",  # d78a2bc3: the tunnel; a wall lamp scores 0.522 at 720
    "scene_02_29ddea61_c2.png",  # 4d5c934f: the tunnel
    "scene_03_54d6c03d_c2.png",  # 5ccff7f5: the ring with a light at its centre
    "scene_04_df1637da_c2.png",  # 5f4c0812: the glowing rings in the rock
    "scene_05_b959724a_c2.png",  # ae98b761: the tall cylinder
)
#: The PAID clips of both films, each passed by clip QC: 1c038a99 scenes 1-5 (takes
#: 82ac5e4b, a147d909, 580dc0da, af96e54a, 0b98f293) and 00000160 scenes 2-5 (ae853e87,
#: c1d82e12, e72664e0, b0f0eadc; scene 2 shows two men only from behind, which its bible
#: allows). Clip QC counts faces on the first, middle AND last frame, and the calibration
#: measured first frames only: on the review of 2026-10-12 the highest score on any of
#: their 27 frames, at any size, was 0.49.
PAID_CLIPS = (
    (PARTICLE, "motion_01_cbd85b81.mp4"),
    (PARTICLE, "motion_02_50f2186a.mp4"),
    (PARTICLE, "motion_03_d07b7b12.mp4"),
    (PARTICLE, "motion_04_91186041.mp4"),
    (PARTICLE, "motion_05_d37c7cf0.mp4"),
    (CYCLOTRON, "motion_02_44308327.mp4"),
    (CYCLOTRON, "motion_03_6621d27a.mp4"),
    (CYCLOTRON, "motion_04_2917713f.mp4"),
    (CYCLOTRON, "motion_05_91669bef.mp4"),
)
#: Scene-4 still 306a6cad: YuNet takes the blurred brass lamp column for a face (0.668 at
#: 1080). A false positive of the single reading that the strict count keeps, unchanged.
LAMP_COLUMN = "scene_04_8641cae3_c1.png"
LAMP_COLUMN_BOX = (74, 268, 347, 462)


# --- pure rules -------------------------------------------------------------------------


def test_the_strict_count_looks_at_four_sizes_and_never_scales_up():
    assert STRICT_SIZES == (1080, 720, 540, 360)
    # A 2K still (1530 px) and a clip frame cut by clip QC (1080 px) get all four looks.
    assert strict_sizes(1530, 2720) == (1080, 720, 540, 360)
    assert strict_sizes(1080, 1920) == (1080, 720, 540, 360)
    # The Nepal fixtures (540 px) are looked at at their own size and smaller only.
    assert strict_sizes(540, 960) == (540, 360)
    assert strict_sizes(270, 480) == (270,)


def test_the_single_reading_is_always_one_of_the_strict_looks():
    """So the strict count never misses a face `count_faces` finds: its look is in the set,
    resized exactly as it resizes, with the same bar."""
    assert MAX_DETECT_WIDTH in STRICT_SIZES
    assert STRICT_THRESHOLD == SCORE_THRESHOLD == 0.6
    # A landscape picture: count_faces looks at it 1080 wide (608 high), which no short-side
    # size would land on, so that look is added.
    assert strict_sizes(1920, 1080) == (1080, 720, 608, 540, 360)


def test_one_face_seen_at_several_sizes_counts_once_at_its_best_score():
    seen = [
        FaceScore(1080, 0.348, (426, 594, 129, 176)),
        FaceScore(720, 0.630, (411, 588, 140, 169)),
        FaceScore(540, 0.634, BALD_MAN),
        FaceScore(360, 0.550, (411, 600, 134, 170)),
        FaceScore(720, 0.640, (1237, 726, 124, 214)),  # someone else, elsewhere
    ]
    merged = merge_faces(seen)
    assert [(face.scale_px, face.score) for face in merged] == [(720, 0.640), (540, 0.634)]
    assert merge_faces([]) == []


def test_two_faces_one_look_keeps_apart_are_never_merged_into_one():
    """YuNet already keeps two faces of one look apart (its own 0.3 overlap rule). A smaller
    look can box two blurred neighbours as one, with a higher score and enough overlap with
    each; merging both into it would count fewer faces than the single reading counts."""
    left = FaceScore(1080, 0.70, (0, 0, 100, 100))
    right = FaceScore(1080, 0.65, (110, 0, 100, 100))
    both = FaceScore(540, 0.80, (0, 0, 210, 100))  # overlaps each neighbour by 0.48

    merged = merge_faces([left, right, both])

    assert len(merged) == 2, "never fewer faces than the 1080 look found"
    assert merged[0] == both
    # The same face seen once per size is still one face.
    assert len(merge_faces([left, FaceScore(720, 0.66, (2, 1, 98, 101)), both])) == 1


def test_both_money_gates_are_handed_the_same_function():
    assert PEOPLE_STRICT is count_faces_strict


# --- it never answers "no face" without looking ------------------------------------------


def test_a_missing_model_is_not_run_never_zero_faces(tmp_path):
    missing = tmp_path / "absent.onnx"
    picture = NEPAL / "scene_06.jpg"

    counted = count_faces_strict(picture, model_path=missing)

    assert counted.status == "NOT_RUN" and counted.faces is None
    assert counted.detail_ro == count_faces(picture, model_path=missing).detail_ro
    with pytest.raises(FacesNotMeasured) as raised:
        strict_faces(picture, model_path=missing)
    assert "lipsește" in raised.value.detail_ro
    with pytest.raises(FacesNotMeasured):
        face_scores(picture, model_path=missing)


def test_an_impostor_model_is_not_run(tmp_path):
    impostor = tmp_path / "yunet_2023mar.onnx"
    impostor.write_bytes(b"not the pinned network")

    counted = count_faces_strict(NEPAL / "scene_06.jpg", model_path=impostor)

    assert counted.status == "NOT_RUN"
    assert "amprenta" in counted.detail_ro


@needs_yunet
def test_an_unreadable_picture_is_not_run(tmp_path):
    broken = tmp_path / "scene_01_broken.png"
    broken.write_bytes(b"\x89PNG not really")

    counted = count_faces_strict(broken)

    assert counted.status == "NOT_RUN"
    assert counted.detail_ro == "imaginea scene_01_broken.png nu poate fi citită"


class _ReplayedYuNet:
    """A stand-in for opencv that replays one face's score per look: what YuNet said about
    the bald man of still 4be4364e (0.348 at 1080, 0.630 at 720, 0.634 at 540, 0.550 at 360).
    It keeps YuNet's contract: rows under the bar the detector was created with are not
    returned."""

    IMREAD_COLOR = 1
    INTER_AREA = 3

    def __init__(self, scores: dict[int, float], *, fail: bool = False) -> None:
        self.scores = scores
        self.fail = fail
        self.looks: list[tuple[int, int]] = []
        replay = self

        class _Detector:
            def __init__(self, size: tuple[int, int], bar: float) -> None:
                self.size = size
                self.bar = bar

            def setInputSize(self, size: tuple[int, int]) -> None:  # noqa: N802 - opencv's name
                self.size = size

            def detect(self, picture):
                import numpy

                replay.looks.append(self.size)
                score = replay.scores.get(min(self.size), 0.0)
                if score < self.bar:
                    return 1, None
                ratio = min(self.size) / 1530
                row = [426 * ratio, 594 * ratio, 129 * ratio, 176 * ratio] + [0.0] * 10
                return 1, numpy.array([row + [score]], dtype=numpy.float32)

        class _FaceDetectorYN:
            @staticmethod
            def create(model, config, size, bar, nms, top_k):
                if replay.fail:
                    raise RuntimeError("the network would not load")
                return _Detector(size, bar)

        self.FaceDetectorYN = _FaceDetectorYN

    def imdecode(self, data, flag):
        import numpy

        return numpy.zeros((2720, 1530, 3), dtype=numpy.uint8)

    def resize(self, picture, size, interpolation):
        import numpy

        return numpy.zeros((size[1], size[0], 3), dtype=numpy.uint8)


@pytest.mark.skipif(
    faces.model_problem() is not None, reason="the pinned YuNet file is not in the checkout"
)
def test_the_incident_replayed_the_single_reading_passes_the_strict_count_refuses(
    tmp_path, monkeypatch
):
    still = tmp_path / "scene_01_3bc31f47_c1.png"
    still.write_bytes(b"any bytes: the replay decodes nothing")
    replay = _ReplayedYuNet({1080: 0.348, 720: 0.630, 540: 0.634, 360: 0.550})
    monkeypatch.setattr(faces, "_opencv", lambda: replay)

    today = count_faces(still)
    strict = count_faces_strict(still)

    assert today.status == "MEASURED" and today.faces == 0, "the gate approved 4be4364e"
    assert strict.status == "MEASURED" and strict.faces == 1
    assert strict.boxes[0][4] == 0.634
    assert strict.detail_ro == (
        "YuNet a găsit 1 față, privind imaginea la 1080, 720, 540 și 360 px "
        "(cea mai clară: 0,63 la 540 px)"
    )
    # The single reading is the strict count's first look, at the same pixels.
    assert replay.looks[0] == (1080, 1920)
    assert sorted(min(look) for look in replay.looks[1:]) == [360, 540, 720, 1080]


@pytest.mark.skipif(
    faces.model_problem() is not None, reason="the pinned YuNet file is not in the checkout"
)
def test_a_detector_that_fails_has_not_looked(tmp_path, monkeypatch):
    still = tmp_path / "scene_01.png"
    still.write_bytes(b"x")
    monkeypatch.setattr(faces, "_opencv", lambda: _ReplayedYuNet({}, fail=True))

    counted = count_faces_strict(still)

    assert counted.status == "NOT_RUN"
    assert counted.detail_ro.startswith("detectorul YuNet a eșuat (RuntimeError)")
    with pytest.raises(FacesNotMeasured):
        strict_faces(still)


@pytest.mark.skipif(
    faces.model_problem() is not None, reason="the pinned YuNet file is not in the checkout"
)
def test_a_clean_picture_is_measured_as_zero_faces_at_every_size(tmp_path, monkeypatch):
    still = tmp_path / "scene_03.png"
    still.write_bytes(b"x")
    monkeypatch.setattr(faces, "_opencv", lambda: _ReplayedYuNet({720: 0.522}))

    counted = count_faces_strict(still)

    assert counted.status == "MEASURED" and counted.faces == 0 and counted.boxes == ()
    assert counted.detail_ro == "YuNet a găsit 0 fețe, privind imaginea la 1080, 720, 540 și 360 px"


# --- YuNet on committed pictures ---------------------------------------------------------


def _read(path: Path):
    import cv2
    import numpy

    return cv2.imdecode(numpy.fromfile(str(path), dtype=numpy.uint8), cv2.IMREAD_COLOR)


@needs_yunet
def test_the_nepal_fixtures_keep_their_counts():
    """No people in scenes 1 and 2; faces in 3 to 6 (looked at by eye, 2026-09-27). The face
    in scene 6, seen at 540 and at 360 px, is one face."""
    strict = {n: count_faces_strict(NEPAL / f"scene_0{n}.jpg") for n in range(1, 7)}
    print({n: (c.faces, c.detail_ro) for n, c in strict.items()})

    assert all(c.status == "MEASURED" for c in strict.values())
    assert strict[1].faces == 0 and strict[2].faces == 0
    assert all(strict[n].faces >= 1 for n in (3, 4, 5, 6))
    assert strict[6].faces == 1
    for n in range(1, 7):
        today = count_faces(NEPAL / f"scene_0{n}.jpg")
        assert strict[n].faces >= today.faces, "the strict count is never looser"


@needs_yunet
def test_the_strict_look_at_the_single_readings_size_is_the_single_reading():
    """Reusing one detector across looks changes nothing: at count_faces' own size the
    strict count sees exactly the faces and scores count_faces sees."""
    for n in (3, 5, 6):
        picture = NEPAL / f"scene_0{n}.jpg"
        today = sorted(box[4] for box in count_faces(picture).boxes)
        own_look = sorted(
            round(score.score, 3)
            for score in face_scores(picture)
            if score.scale_px == 540 and score.score >= SCORE_THRESHOLD
        )
        assert own_look == today


@needs_yunet
def test_a_picture_with_nothing_in_it_is_measured_as_no_face_at_every_size(tmp_path):
    """Grey, noise, blurred noise, a landscape frame and pictures too small to resize: four
    more looks must not invent a face, and a tiny picture is measured, never NOT_RUN."""
    import cv2
    import numpy

    noise = numpy.random.default_rng(7).integers(0, 256, (2720, 1530, 3), dtype=numpy.uint8)
    pictures = {
        "grey": numpy.full((2720, 1530, 3), 128, dtype=numpy.uint8),
        "noise": noise,
        "blurred": cv2.GaussianBlur(noise, (0, 0), 6),
        "landscape": cv2.GaussianBlur(noise[:1080, :1530], (0, 0), 3),
        "tiny": noise[:12, :9],
        "one_pixel": noise[:1, :1],
    }
    for name, picture in pictures.items():
        path = tmp_path / f"{name}.png"
        assert cv2.imwrite(str(path), picture)

        counted = count_faces_strict(path)

        assert counted.status == "MEASURED" and counted.faces == 0, (name, counted.detail_ro)
    # A 1530 x 1080 landscape: the single reading's own look (1080 x 762) is one of them.
    assert count_faces_strict(tmp_path / "landscape.png").detail_ro.endswith(
        "la 1080, 762, 720, 540 și 360 px"
    )
    assert count_faces_strict(tmp_path / "tiny.png").detail_ro.endswith("la 9 px")


@needs_yunet
def test_a_blurred_face_scores_under_the_bar_at_1080_and_over_it_smaller(tmp_path):
    """The incident's mechanism on committed pictures: the face of Nepal scene 6, 130 px
    wide and blurred like a background face (sigma 9), pasted into the empty Nepal scene 1
    at 1080 x 1920. Measured 2026-10-12: 0.361 at 1080, 0.710 at 720, 0.648 at 540."""
    import cv2

    face_still = _read(NEPAL / "scene_06.jpg")
    x, y, w, h = 316, 308, 112, 138  # YuNet's box of that face at 540 px (0.899)
    margin = int(0.35 * w)
    face = face_still[max(0, y - margin) : y + h + margin, max(0, x - margin) : x + w + margin]
    face = cv2.resize(
        face, (130, round(face.shape[0] * 130 / face.shape[1])), interpolation=cv2.INTER_AREA
    )
    canvas = cv2.resize(_read(NEPAL / "scene_01.jpg"), (1080, 1920), interpolation=cv2.INTER_CUBIC)
    left, top = 400, 500
    canvas[top : top + face.shape[0], left : left + face.shape[1]] = face
    region = (slice(top - 40, top + face.shape[0] + 40), slice(left - 40, left + 130 + 40))
    canvas[region] = cv2.GaussianBlur(canvas[region], (0, 0), 9)
    still = tmp_path / "blurred_face.png"
    assert cv2.imwrite(str(still), canvas)

    best = {}
    for score in face_scores(still):
        best[score.scale_px] = max(best.get(score.scale_px, 0.0), score.score)
    print({size: round(score, 3) for size, score in best.items()})

    assert best.get(1080, 0.0) < STRICT_THRESHOLD
    assert max(best.get(720, 0.0), best.get(540, 0.0)) >= STRICT_THRESHOLD
    assert count_faces(still).faces == 0
    assert count_faces_strict(still).faces == 1


# --- YuNet on the real pictures of 2026-10-12 (read only) --------------------------------


@needs_yunet
@needs_cyclotron
def test_still_4be4364e_is_refused_before_a_clip_is_bought():
    still = CYCLOTRON / "stills" / "scene_01_3bc31f47_c1.png"

    today = count_faces(still)
    strict = strict_faces(still)

    assert today.status == "MEASURED" and today.faces == 0, "what approved it on 2026-10-12"
    assert strict, "the strict count refuses it"
    face = strict[0]
    assert face.scale_px in (720, 540) and face.score >= STRICT_THRESHOLD
    assert abs(face.box[0] - BALD_MAN[0]) < 40 and abs(face.box[1] - BALD_MAN[1]) < 40
    at_1080 = [s for s in face_scores(still) if s.scale_px == 1080]
    assert all(s.score < STRICT_THRESHOLD for s in at_1080)


@needs_yunet
@needs_cyclotron
@pytest.mark.parametrize("name", SCENE_ONE_STILLS)
def test_every_scene_one_still_with_people_is_refused(name):
    counted = count_faces_strict(CYCLOTRON / "stills" / name)
    print(name, counted.detail_ro)
    assert counted.status == "MEASURED" and counted.faces >= 1


@needs_yunet
@needs_cyclotron
@pytest.mark.parametrize("name", SCENE_FOUR_FACES)
def test_the_scene_four_stills_with_partial_faces_are_refused(name):
    counted = count_faces_strict(CYCLOTRON / "stills" / name)
    print(name, counted.detail_ro, "| single reading:", count_faces(CYCLOTRON / "stills" / name))
    assert counted.status == "MEASURED" and counted.faces >= 1


@needs_yunet
@needs_cyclotron
@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")
def test_the_first_frame_of_every_scene_one_clip_is_refused(tmp_path):
    """Cut exactly as clip QC cuts them (`qc.clip_frames`, 1080 px wide). The single reading
    found the face on 4 of the 6 (1, 1, 1, 0, 0, 1 on 2026-10-12); the strict count on all."""
    from app.media.qc import clip_frames

    clips = [CYCLOTRON / "motion" / f"motion_01_{take}.mp4" for take in SCENE_ONE_CLIPS]
    if not all(clip.is_file() for clip in clips):
        pytest.skip("the scene-1 clips of 00000160 are not all here")
    for clip in clips:
        frames = clip_frames(FFMPEG, clip, tmp_path / clip.stem)
        first = next(path for at, _, path in frames if at == "first")
        counted = count_faces_strict(first)
        print(clip.name, count_faces(first).faces, counted.detail_ro)
        assert counted.status == "MEASURED" and counted.faces >= 1, clip.name


@needs_yunet
@needs_cyclotron
@pytest.mark.parametrize("name", CLEAN_CYCLOTRON)
def test_the_approved_cyclotron_stills_without_people_pass(name):
    counted = count_faces_strict(CYCLOTRON / "stills" / name)
    assert counted.status == "MEASURED" and counted.faces == 0, counted.detail_ro


@needs_yunet
@needs_particle
@pytest.mark.parametrize("name", CLEAN_PARTICLE)
def test_the_approved_particle_stills_without_people_pass(name):
    counted = count_faces_strict(PARTICLE / "stills" / name)
    assert counted.status == "MEASURED" and counted.faces == 0, counted.detail_ro


@needs_yunet
@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")
@pytest.mark.parametrize(("film", "name"), PAID_CLIPS, ids=[name for _, name in PAID_CLIPS])
def test_the_paid_clips_pass_on_all_three_frames_clip_qc_cuts(film, name, tmp_path):
    """Clip QC will call the strict count on the first, middle and last frame: a clip it
    passed with nobody in it must not be refused for a face (22 credits each)."""
    from app.media.qc import clip_frames

    clip = film / "motion" / name
    if not clip.is_file():
        pytest.skip(f"{name} is not on this machine")
    frames = clip_frames(FFMPEG, clip, tmp_path)
    assert [at for at, _, _ in frames] == ["first", "middle", "last"]
    for at, _, path in frames:
        counted = count_faces_strict(path)
        assert counted.status == "MEASURED" and counted.faces == 0, (at, counted.detail_ro)


@needs_yunet
@needs_cyclotron
def test_the_lamp_column_false_positive_is_kept_not_made_worse():
    """306a6cad: the single reading took the blurred brass lamp column for a face. The
    strict count finds the same box at the same size and nothing else: still a false
    positive (the vision look, not this detector, has to clear it), but not a second one."""
    still = CYCLOTRON / "stills" / LAMP_COLUMN

    today = count_faces(still)
    strict = strict_faces(still)

    assert today.faces == 1 and today.boxes[0][:4] == LAMP_COLUMN_BOX
    assert [(face.scale_px, face.box) for face in strict] == [(1080, LAMP_COLUMN_BOX)]
    assert round(strict[0].score, 3) == today.boxes[0][4] == 0.668
