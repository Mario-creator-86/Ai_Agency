"""Faces: existing local-first media checks.

Private production traces omitted; implementation unchanged."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

#: Where the pinned network lives, beside the media code that uses it.
YUNET_MODEL_PATH = Path(__file__).resolve().parent / "models" / "yunet_2023mar.onnx"
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
YUNET_SOURCE = (
    "https://huggingface.co/opencv/face_detection_yunet/resolve/main/"
    "face_detection_yunet_2023mar.onnx"
)

#: YuNet's own demo uses 0.9, which is tuned for not raising false alarms. A still gate is
#: tuned the other way: a missed face costs a paid clip with a face in it, a false alarm
#: costs one re-roll of a 9-credit still.
SCORE_THRESHOLD = 0.6
NMS_THRESHOLD = 0.3
TOP_K = 5000

#: Stills are measured at most this wide; a 2K still (1530 px) is scaled down first. The
#: network works at any input size, and a face narrower than ~10 px at this width is below
#: what it can find anyway.
MAX_DETECT_WIDTH = 1080

#: The strict count's looks, as the picture's short side in px (calibrated 2026-10-12 on the
#: cyclotron film aa170155; the module docstring has the table). A picture is never scaled
#: up: a 540 px one is measured at 540 and 360. `count_faces`' own reading is always one of
#: the looks, so the strict count never misses a face the single reading finds.
STRICT_SIZES = (1080, 720, 540, 360)
#: The strict count's bar: the same number as SCORE_THRESHOLD. What changed on 2026-10-12 is
#: how many sizes look, not how sure one look must be; a lower bar needs a new calibration.
STRICT_THRESHOLD = SCORE_THRESHOLD
#: `face_scores` reports detections down to this score, so a calibration sees how close a
#: miss came. Nothing under STRICT_THRESHOLD counts as a face.
SCORE_FLOOR = 0.3
#: Boxes from different sizes that overlap at least this much (intersection over union) are
#: one face, kept at its highest score; YuNet applies the same 0.3 within one size.
MERGE_IOU = NMS_THRESHOLD


@dataclass(frozen=True)
class FaceCount:
    """How many faces the detector found, or why it did not look.

    `boxes` holds (x, y, w, h, score) in the input picture's own pixels.
    """

    status: str  # MEASURED | NOT_RUN
    faces: int | None
    boxes: tuple[tuple[int, int, int, int, float], ...]
    detail_ro: str


#: What the stills gate calls; a test passes its own to fake the detector.
FaceCounter = Callable[..., FaceCount]


class FaceScore(NamedTuple):
    """One YuNet detection at one size.

    `scale_px` is the short side of the picture the detector was shown, `score` YuNet's own
    score (not rounded, so a bar compares what the detector said), `box` (x, y, w, h) in the
    input picture's own pixels, whatever size it was found at.
    """

    scale_px: int
    score: float
    box: tuple[int, int, int, int]


class FacesNotMeasured(RuntimeError):
    """The strict count did not look: no opencv, no pinned model, an unreadable picture or
    a failing detector. Raised, never answered with an empty list, because an empty list
    means "no face" and that was not measured. `detail_ro` says why, in Romanian."""

    def __init__(self, detail_ro: str) -> None:
        super().__init__(detail_ro)
        self.detail_ro = detail_ro


def _not_run(detail_ro: str) -> FaceCount:
    return FaceCount(status="NOT_RUN", faces=None, boxes=(), detail_ro=detail_ro)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def model_problem(model_path: Path | None = None) -> str | None:
    """Why the pinned YuNet model cannot be used (in Romanian), or None when it can."""
    path = Path(model_path or YUNET_MODEL_PATH)
    if not path.is_file():
        return f"modelul YuNet lipsește ({path.name}); fețele nu au fost numărate"
    try:
        actual = _sha256(path)
    except OSError:
        return f"modelul YuNet ({path.name}) nu poate fi citit; fețele nu au fost numărate"
    if actual != YUNET_SHA256:
        return (
            f"modelul YuNet ({path.name}) nu are amprenta fixată "
            f"({actual[:12]}… în loc de {YUNET_SHA256[:12]}…); fețele nu au fost numărate"
        )
    return None


def _opencv() -> Any | None:
    """The cv2 module when it is installed and has the YuNet detector, else None."""
    try:
        import cv2  # type: ignore[import-not-found]  # noqa: PLC0415 - optional
    except ImportError:
        return None
    return cv2 if hasattr(cv2, "FaceDetectorYN") else None


def detector_available(model_path: Path | None = None) -> bool:
    """True when opencv and the pinned model are both here, so a count can be MEASURED."""
    return model_problem(model_path) is None and _opencv() is not None


def _read(image_path: Path | str, model_path: Path | None) -> tuple[Any, Any]:
    """(cv2, the decoded picture), or FacesNotMeasured with the reason in Romanian.

    The checks run in a fixed order: the pinned model, opencv, then the picture."""
    problem = model_problem(model_path)
    if problem is not None:
        raise FacesNotMeasured(problem)
    cv2 = _opencv()
    if cv2 is None:
        raise FacesNotMeasured("biblioteca opencv lipsește; fețele nu au fost numărate")
    try:
        import numpy  # type: ignore[import-not-found]  # noqa: PLC0415 - comes with opencv

        data = numpy.fromfile(str(image_path), dtype=numpy.uint8)
        picture = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except (OSError, ValueError):
        picture = None
    if picture is None:
        raise FacesNotMeasured(f"imaginea {Path(image_path).name} nu poate fi citită")
    return cv2, picture


def count_faces(
    image_path: Path | str,
    *,
    model_path: Path | None = None,
    score_threshold: float = SCORE_THRESHOLD,
) -> FaceCount:
    """Count the faces YuNet finds in one picture, or say why it could not look.

    One look, at most MAX_DETECT_WIDTH wide. Where the bible forbids faces, the money gates
    call PEOPLE_STRICT instead (2026-10-12, the module docstring says why)."""
    try:
        cv2, picture = _read(image_path, model_path)
    except FacesNotMeasured as exc:
        return _not_run(exc.detail_ro)
    height, width = picture.shape[:2]
    scale = 1.0
    if width > MAX_DETECT_WIDTH:
        scale = MAX_DETECT_WIDTH / width
        picture = cv2.resize(
            picture, (MAX_DETECT_WIDTH, round(height * scale)), interpolation=cv2.INTER_AREA
        )
        height, width = picture.shape[:2]
    try:
        detector = cv2.FaceDetectorYN.create(
            str(Path(model_path or YUNET_MODEL_PATH)),
            "",
            (width, height),
            score_threshold,
            NMS_THRESHOLD,
            TOP_K,
        )
        _, found = detector.detect(picture)
    except Exception as exc:  # noqa: BLE001 - a detector that fails has not looked
        return _not_run(
            f"detectorul YuNet a eșuat ({type(exc).__name__}); fețele nu au fost numărate"
        )
    rows = [] if found is None else found.tolist()
    boxes = tuple(
        (
            round(row[0] / scale),
            round(row[1] / scale),
            round(row[2] / scale),
            round(row[3] / scale),
            round(float(row[-1]), 3),
        )
        for row in rows
    )
    count = len(boxes)
    return FaceCount(
        status="MEASURED",
        faces=count,
        boxes=boxes,
        detail_ro=f"YuNet a găsit {count} {'față' if count == 1 else 'fețe'}",
    )


def _looks(width: int, height: int, sizes: Sequence[int]) -> list[tuple[int, int]]:
    """The (width, height) each look of the strict count shows the detector, largest first.

    `count_faces`' own look is always there, resized exactly as it resizes; a size larger
    than the picture is its own size (never scaled up); two sizes that land on the same
    pixels are one look."""
    short = min(width, height)
    looks: set[tuple[int, int]] = set()
    if width > MAX_DETECT_WIDTH:
        looks.add((MAX_DETECT_WIDTH, round(height * (MAX_DETECT_WIDTH / width))))
    else:
        looks.add((width, height))
    for size in sizes:
        side = min(int(size), short)
        if side <= 0 or side == short:
            looks.add((width, height))
        elif width <= height:
            looks.add((side, max(1, round(height * (side / width)))))
        else:
            looks.add((max(1, round(width * (side / height))), side))
    return sorted(looks, key=lambda look: (-min(look), -max(look)))


def strict_sizes(width: int, height: int, sizes: Sequence[int] = STRICT_SIZES) -> tuple[int, ...]:
    """The short sides, in px, the strict count looks at a width x height picture with."""
    return tuple(min(look) for look in _looks(width, height, sizes))


def _measure(
    image_path: Path | str,
    model_path: Path | None,
    floor: float,
    sizes: Sequence[int],
) -> tuple[list[FaceScore], tuple[int, ...]]:
    """(every detection of at least `floor`, the short sides looked at)."""
    cv2, picture = _read(image_path, model_path)
    height, width = picture.shape[:2]
    looks = _looks(width, height, sizes)
    found: list[FaceScore] = []
    try:
        detector = None
        for look_width, look_height in looks:
            look = picture
            if (look_width, look_height) != (width, height):
                look = cv2.resize(picture, (look_width, look_height), interpolation=cv2.INTER_AREA)
            if detector is None:
                detector = cv2.FaceDetectorYN.create(
                    str(Path(model_path or YUNET_MODEL_PATH)),
                    "",
                    (look_width, look_height),
                    floor,
                    NMS_THRESHOLD,
                    TOP_K,
                )
            else:
                detector.setInputSize((look_width, look_height))
            _, rows = detector.detect(look)
            across, down = look_width / width, look_height / height
            for row in [] if rows is None else rows.tolist():
                found.append(
                    FaceScore(
                        scale_px=min(look_width, look_height),
                        score=float(row[-1]),
                        box=(
                            round(row[0] / across),
                            round(row[1] / down),
                            round(row[2] / across),
                            round(row[3] / down),
                        ),
                    )
                )
    except Exception as exc:  # noqa: BLE001 - a detector that fails has not looked
        raise FacesNotMeasured(
            f"detectorul YuNet a eșuat ({type(exc).__name__}); fețele nu au fost numărate"
        ) from exc
    return found, tuple(min(look) for look in looks)


def face_scores(
    image_path: Path | str,
    *,
    model_path: Path | None = None,
    floor: float = SCORE_FLOOR,
    sizes: Sequence[int] = STRICT_SIZES,
) -> list[FaceScore]:
    """Every detection YuNet scores at least `floor` at each size in `sizes`.

    One FaceScore per detection per size, so the same face usually appears once per size
    that saw it; `merge_faces` makes them one. FacesNotMeasured when it could not look.
    """
    return _measure(image_path, model_path, floor, sizes)[0]


def _overlap(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> float:
    """Intersection over union of two (x, y, w, h) boxes."""
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[0] + first[2], second[0] + second[2])
    bottom = min(first[1] + first[3], second[1] + second[3])
    shared = max(0, right - left) * max(0, bottom - top)
    union = first[2] * first[3] + second[2] * second[3] - shared
    return shared / union if union > 0 else 0.0


def merge_faces(found: Iterable[FaceScore], *, iou: float = MERGE_IOU) -> list[FaceScore]:
    """One FaceScore per face: boxes that overlap at least `iou` are the same face, kept at
    its highest score (and the size that gave it). Highest score first.

    A face takes at most one box from each size. YuNet has already kept two boxes of one
    look apart, so they are two faces; a smaller look that boxes two blurred neighbours as
    one must not fold both into it, or the strict count would report fewer faces than the
    single reading it includes (review of 2026-10-12)."""
    kept: list[FaceScore] = []
    sizes_seen: list[set[int]] = []
    for face in sorted(found, key=lambda one: one.score, reverse=True):
        for index, other in enumerate(kept):
            if face.scale_px not in sizes_seen[index] and _overlap(face.box, other.box) >= iou:
                sizes_seen[index].add(face.scale_px)
                break
        else:
            kept.append(face)
            sizes_seen.append({face.scale_px})
    return kept


def _strict(
    image_path: Path | str,
    threshold: float,
    model_path: Path | None,
    sizes: Sequence[int],
) -> tuple[list[FaceScore], tuple[int, ...]]:
    scores, looked = _measure(image_path, model_path, min(SCORE_FLOOR, threshold), sizes)
    return merge_faces(score for score in scores if score.score >= threshold), looked


def strict_faces(
    image_path: Path | str,
    threshold: float = STRICT_THRESHOLD,
    *,
    model_path: Path | None = None,
    sizes: Sequence[int] = STRICT_SIZES,
) -> list[FaceScore]:
    """The faces found at ANY of `sizes` with at least `threshold`, one entry per face.

    Empty means YuNet looked at every size and found none; FacesNotMeasured means it did
    not look. Still 4be4364e gives one face here (0.634 at 540 px) and none to `count_faces`.
    """
    return _strict(image_path, threshold, model_path, sizes)[0]


def _sizes_ro(sizes: Sequence[int]) -> str:
    words = [str(size) for size in sizes]
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " și " + words[-1]


def count_faces_strict(
    image_path: Path | str,
    *,
    model_path: Path | None = None,
    score_threshold: float = STRICT_THRESHOLD,
) -> FaceCount:
    """`strict_faces` as a FaceCount, so it fits wherever a FaceCounter is called.

    NOT_RUN for exactly the reasons `count_faces` gives; MEASURED with one box per face
    (x, y, w, h, score) otherwise, and a Romanian sentence naming the sizes it looked at.
    """
    try:
        faces, looked = _strict(image_path, score_threshold, model_path, STRICT_SIZES)
    except FacesNotMeasured as exc:
        return _not_run(exc.detail_ro)
    count = len(faces)
    detail = (
        f"YuNet a găsit {count} {'față' if count == 1 else 'fețe'}, privind imaginea "
        f"la {_sizes_ro(looked)} px"
    )
    if faces:
        best = faces[0]
        detail += f" (cea mai clară: {best.score:.2f} la {best.scale_px} px)".replace(".", ",")
    return FaceCount(
        status="MEASURED",
        faces=count,
        boxes=tuple((*face.box, round(face.score, 3)) for face in faces),
        detail_ro=detail,
    )


#: PEOPLE_STRICT: the one face check both money gates call where the bible forbids faces
#: (the module docstring says why). Round 4 wires it as the default FaceCounter of the
#: stills gate (still_gate.local_checks) and of clip QC (qc.check_clip and
#: qc.span_picture_qc), so a still the gate passes is never refused by clip QC for a face
#: that was already in it. A test still passes its own counter.
PEOPLE_STRICT: FaceCounter = count_faces_strict
