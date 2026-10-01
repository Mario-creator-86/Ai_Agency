"""Counting faces in a still before a credit is spent on moving it.

The Nepal visual bible said "No human faces appear". The prompts never carried the rule,
three of the six stills came back with faces, and nobody looked before the clips were
bought. The vision model that judges a still is one eye; this module is the other, and it
does not share the first one's bias towards yes: YuNet (OpenCV Zoo's 2023 face detector, a
233 kB ONNX network) counts faces with a fixed threshold and no opinion.

What this module certifies is only what it measured. It reports NOT_RUN — never "0 faces" —
when opencv is not installed, when the model file is missing, when the file is not the one
pinned below (a swapped network is not the detector these thresholds were chosen for), or
when the picture cannot be read. What NOT_RUN costs a still is decided by the stills gate
(`app.media.still_gate`): it blocks in PRODUCTION and warns in TEST.

The model is pinned by the SHA256 that Hugging Face publishes for
opencv/face_detection_yunet face_detection_yunet_2023mar.onnx (read 2026-09-27); the same
file is in github.com/opencv/opencv_zoo under models/face_detection_yunet. It is Apache-2.0
(OpenCV Zoo). The file is not bundled until the Owner approves downloading it, together
with the opencv-python-headless dependency; until then every count is NOT_RUN.

YuNet misses small and profile faces. That is why a face from EITHER this detector or the
vision model blocks a still, and why the Owner's look at the contact sheet stays the last
gate.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def count_faces(
    image_path: Path | str,
    *,
    model_path: Path | None = None,
    score_threshold: float = SCORE_THRESHOLD,
) -> FaceCount:
    """Count the faces YuNet finds in one picture, or say why it could not look."""
    problem = model_problem(model_path)
    if problem is not None:
        return _not_run(problem)
    cv2 = _opencv()
    if cv2 is None:
        return _not_run("biblioteca opencv lipsește; fețele nu au fost numărate")
    try:
        import numpy  # type: ignore[import-not-found]  # noqa: PLC0415 - comes with opencv

        data = numpy.fromfile(str(image_path), dtype=numpy.uint8)
        picture = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except (OSError, ValueError):
        picture = None
    if picture is None:
        return _not_run(f"imaginea {Path(image_path).name} nu poate fi citită")
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
