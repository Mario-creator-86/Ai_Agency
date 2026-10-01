"""The stills gate: nothing is animated until someone has looked at the still.

The Nepal film paid for twelve clips before anybody looked at a picture. Three of its stills
showed faces that the visual bible forbade, one was a woman where a bar chart should have
been, one a landscape where a black screen should have been, and quality control only found
out after the whole film was bought. A still costs 9 credits; the clip made from it costs
up to 68 credits a second. So the still is checked first, twice, at no credit cost:

1. Local checks (`local_checks`), measured with the encoder the studio already has and the
   YuNet face detector (`app.media.faces`):
   - degenerate: stripes, bands or a blank field (`app.media.qc.still_is_degenerate`);
   - sharpness: variance of the 4-neighbour Laplacian at 1080 px width, pooled over the
     tiles that hold a picture (a tile whose luma barely varies is flat sky or black and
     says nothing about focus). Floor 250. Measured 2026-09-27 on the six Nepal stills:
     592, 614, 870, 603, 893 and 331 (scene 6 is half flat black; whole-frame it read 197,
     which is why flat tiles are left out);
   - motion blur: the ratio of horizontal to vertical gradient energy. Nepal stills read
     1.1-1.5; a 12 px horizontal smear reads above 5. Blocks a static shot, warns on a
     moving one (a pan may carry some blur honestly);
   - palette: mean CIELAB distance of the picture to the colours the look block names in
     words. A score and a warning, never a block: it is a coarse measure, and the vision
     model's look_ok and the Owner's eye are the real judges of a look;
   - faces: the YuNet count, when the bible forbids faces.
2. The vision checklist (`app.media.picture_qc.judge_still`): one call per still at
   1080 px, with a verdict schema that has no field a silent model could pass by.

Everything fails closed. A check that could not run is NOT_RUN, and a NOT_RUN of a
required check blocks in PRODUCTION and warns in TEST — except the vision checklist, whose
silence blocks everywhere ("nu a fost privită"): a still nobody looked at is never bought
into motion. A face from EITHER detector blocks when the bible forbids faces. A verdict of
buy_motion whose own answers contradict it (text seen, plan not matched, a violation named)
does not pass: the answers win over the summary.

What happens next is `next_step`: a passing still buys motion; a still that should have
been a card is routed to the local compositor; a failing still is re-rolled at most twice,
with its violations rewritten as positive words the image model obeys
(`positive_instruction`), and then goes to the Owner. A block that is only "could not
measure" is never re-rolled: buying another still does not install a detector.
"""

from __future__ import annotations

import hashlib
import math
import subprocess
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from app.media.faces import FaceCount, FaceCounter, count_faces
from app.media.picture_qc import StillJudgement, judge_still
from app.media.qc import still_is_degenerate
from app.media.toolchain import find_ffmpeg

#: The width every picture check measures at: the final film's width.
MEASURE_WIDTH = 1080
#: Laplacian variance floor at 1080 px (see the module docstring for the measurements).
SHARPNESS_FLOOR = 250
#: A tile whose luma standard deviation is below this holds no picture to be sharp.
FLAT_TILE_STD = 6.0
TILES_ACROSS, TILES_DOWN = 8, 14
#: Horizontal/vertical gradient-energy ratio (either way round) at which a still carries
#: baked motion blur.
MOTION_BLUR_ANISOTROPY = 2.5
#: Mean CIELAB distance to the look's named colours above which the palette is flagged.
PALETTE_WARN_DELTA_E = 30.0
#: How many times a failing still is bought again before the Owner decides.
MAX_REROLLS = 2

ALL_CHECKS = ("degenerate", "sharpness", "motion_blur", "palette", "faces")

#: The camera moves on which baked motion blur is a defect, not a choice.
STATIC_MOVES = frozenset({"static", "locked", "locked camera", "locked-off"})

#: Named colours the look block may use, in sRGB. Deliberately plain: this is a coarse
#: distance, not a colour science claim.
COLOUR_WORDS: dict[str, tuple[int, int, int]] = {
    "slate blue": (84, 104, 130),
    "steel blue": (70, 110, 150),
    "deep blue": (30, 50, 90),
    "navy": (25, 35, 70),
    "sky blue": (135, 180, 220),
    "pale blue": (180, 200, 220),
    "blue grey": (110, 125, 140),
    "blue": (60, 90, 140),
    "teal": (40, 110, 110),
    "muted green": (105, 125, 95),
    "moss green": (95, 110, 60),
    "forest green": (40, 75, 45),
    "olive": (110, 110, 60),
    "green": (70, 120, 70),
    "ochre": (190, 140, 60),
    "amber": (210, 150, 50),
    "gold": (200, 165, 70),
    "rust": (160, 80, 45),
    "terracotta": (190, 100, 70),
    "earth brown": (110, 80, 55),
    "brown": (110, 75, 50),
    "sand": (200, 180, 140),
    "beige": (210, 195, 165),
    "cream": (235, 225, 200),
    "warm grey": (130, 122, 112),
    "cool grey": (120, 126, 134),
    "stone grey": (140, 138, 130),
    "grey": (128, 128, 128),
    "gray": (128, 128, 128),
    "charcoal": (55, 55, 58),
    "black": (15, 15, 15),
    "snow white": (240, 244, 248),
    "white": (240, 240, 240),
    "orange": (220, 120, 40),
    "deep red": (120, 30, 30),
    "red": (190, 40, 40),
}

#: Positive words for the image model, one per violation. The spec's rule: tell the model
#: what to show, never hand it a list of things to avoid.
POSITIVE_WORDS: dict[str, str] = {
    "faces": "figures small and distant, seen from behind, faces not visible",
    "readable_text": "plain surfaces and unmarked objects, clean walls and signs left blank",
    "sharpness": "sharp focus, fine natural detail across the subject",
    "motion_blur": "crisp and still, as if on a tripod",
    "degenerate": "a full, detailed scene filling the frame",
    "look": "light, palette and grain exactly as the film's look describes",
    "plan": "the subject exactly as the scene's plan describes it",
    "technical": "natural anatomy, clean edges, clean texture",
    "bible": "every rule of the visual bible kept",
}

_NONE_WORDS = frozenset(
    {"none", "nothing", "no violations", "no violation", "n/a", "-", "niciuna", "nimic"}
)


@dataclass(frozen=True)
class StillPlan:
    """What one scene's still must be, as the gate needs to know it."""

    scene: int
    still_prompt: str
    camera_move: str
    faces_forbidden: bool
    bible_rules: tuple[str, ...] = ()
    look_block: str = ""
    palette_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckResult:
    code: str
    status: str  # PASSED | FAILED | WARNING | NOT_RUN
    blocking: bool
    value: float | None
    detail_ro: str


@dataclass(frozen=True)
class StillReport:
    path: str
    sha256: str | None
    scene: int
    checks: tuple[CheckResult, ...]
    judgement: StillJudgement | None
    decision: str  # PASSED | BLOCKED
    outcome: str  # buy_motion | regenerate_still | compose_locally
    reasons_ro: tuple[str, ...]
    warnings_ro: tuple[str, ...]
    faces_found: bool
    #: What was measured wrong, as POSITIVE_WORDS codes; the re-roll rewrites these.
    violations: tuple[str, ...]
    #: Blocks that are "could not measure", which a re-roll cannot fix.
    unmeasured: tuple[str, ...]
    score: float
    measured: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NextStep:
    action: str  # buy_motion | compose_locally | reroll | needs_owner
    instruction: str
    reason_ro: str


# ------------------------------------------------------------------------ measuring


def _raw_gray(
    ffmpeg: str,
    path: Path | str,
    kernel: str | None = None,
    rdiv: float = 1.0,
    width: int = MEASURE_WIDTH,
) -> bytes | None:
    """The picture as 8-bit full-range luma at `width`, optionally convolved.

    A convolution is written with a bias of 128 and scaled by `rdiv`, so a signed response
    fits a byte; the caller undoes the scale on the variance.
    """
    chain = f"scale={width}:-2:flags=bicubic,format=gray"
    if kernel:
        chain += f",convolution=0m='{kernel}':0rdiv={rdiv}:0bias=128"
    try:
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [
                ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                chain,
                "-f",
                "rawvideo",
                "-pix_fmt",
                "gray",
                "pipe:1",
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout or len(result.stdout) % width:
        return None
    return result.stdout


def _variance(data: bytes) -> float:
    """Variance of a byte buffer, from its histogram (the counting runs in C)."""
    if not data:
        return 0.0
    histogram = Counter(data)
    count = len(data)
    mean = sum(value * n for value, n in histogram.items()) / count
    return sum(n * (value - mean) ** 2 for value, n in histogram.items()) / count


def _tiles(data: bytes, width: int) -> Iterable[bytes]:
    height = len(data) // width
    tile_w, tile_h = width // TILES_ACROSS, height // TILES_DOWN
    for row in range(TILES_DOWN):
        for column in range(TILES_ACROSS):
            left = column * tile_w
            yield b"".join(
                data[y * width + left : y * width + left + tile_w]
                for y in range(row * tile_h, (row + 1) * tile_h)
            )


def measure_sharpness(ffmpeg: str | None, path: Path | str) -> float | None:
    """Laplacian variance at 1080 px, pooled over the tiles that hold a picture.

    None only when it cannot be measured. A still in which no tile holds any picture is
    measured over the whole frame, where it reads close to 0.
    """
    if not ffmpeg or not Path(path).is_file():
        return None
    luma = _raw_gray(ffmpeg, path)
    laplacian = _raw_gray(ffmpeg, path, "0 1 0 1 -4 1 0 1 0", 0.25)
    if luma is None or laplacian is None or len(luma) != len(laplacian):
        return None
    total = weight = 0.0
    for luma_tile, laplacian_tile in zip(
        _tiles(luma, MEASURE_WIDTH), _tiles(laplacian, MEASURE_WIDTH), strict=True
    ):
        if math.sqrt(_variance(luma_tile)) < FLAT_TILE_STD:
            continue
        # The response was divided by 4 to fit a byte: its variance is 16 times smaller.
        total += _variance(laplacian_tile) * 16 * len(laplacian_tile)
        weight += len(laplacian_tile)
    if not weight:
        # No tile holds a picture: a blank field (the degenerate check names it) or a still
        # blurred until nothing varies. Either way it is measured, and it is not sharp.
        return round(_variance(laplacian) * 16, 1)
    return round(total / weight, 1)


def measure_anisotropy(ffmpeg: str | None, path: Path | str) -> float | None:
    """How much stronger the gradients run one way than the other (>= 1), or None."""
    if not ffmpeg or not Path(path).is_file():
        return None
    across = _raw_gray(ffmpeg, path, "0 0 0 -1 0 1 0 0 0", 0.5)
    down = _raw_gray(ffmpeg, path, "0 -1 0 0 0 0 0 1 0", 0.5)
    if across is None or down is None:
        return None
    energy_x, energy_y = _variance(across), _variance(down)
    if min(energy_x, energy_y) < 0.25:
        return None
    return round(max(energy_x, energy_y) / min(energy_x, energy_y), 2)


def _named_colours(words: Iterable[str]) -> list[tuple[int, int, int]]:
    found: list[tuple[int, int, int]] = []
    keys = sorted(COLOUR_WORDS, key=len, reverse=True)
    for phrase in words:
        text = " ".join(
            word[:-1] if word.endswith("s") and len(word) > 3 else word
            for word in str(phrase).lower().replace(",", " ").split()
        )
        for key in keys:
            if key in text:
                found.append(COLOUR_WORDS[key])
                break
    return found


def _lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def linear(channel: int) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def measure_palette(ffmpeg: str | None, path: Path | str, words: Sequence[str]) -> float | None:
    """Mean CIELAB distance of the picture to the nearest colour the look names, or None."""
    targets = [_lab(rgb) for rgb in _named_colours(words)]
    if not targets or not ffmpeg or not Path(path).is_file():
        return None
    try:
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [
                ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "scale=36:64:flags=area,format=rgb24",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    data = result.stdout
    if result.returncode != 0 or not data or len(data) % 3:
        return None
    distances = []
    for index in range(0, len(data), 3):
        pixel = _lab((data[index], data[index + 1], data[index + 2]))
        distances.append(min(math.dist(pixel, target) for target in targets))
    return round(sum(distances) / len(distances), 1)


# --------------------------------------------------------------------- the local checks


def _unmeasured(code: str, detail: str, environment: str) -> CheckResult:
    """A check that could not run: it blocks in PRODUCTION and warns in TEST."""
    return CheckResult(
        code=code,
        status="NOT_RUN",
        blocking=environment == "PRODUCTION",
        value=None,
        detail_ro=detail,
    )


def _faces_check(
    path: Path | str,
    plan: StillPlan,
    environment: str,
    counter: FaceCounter,
    face_model: Path | None,
) -> CheckResult:
    counted: FaceCount = counter(path, model_path=face_model)
    if counted.status != "MEASURED" or counted.faces is None:
        detail = f"Detectorul de fețe YuNet nu a rulat: {counted.detail_ro}"
        if not plan.faces_forbidden:
            return CheckResult("faces", "NOT_RUN", False, None, detail)
        return _unmeasured("faces", detail, environment)
    faces = counted.faces
    if plan.faces_forbidden and faces > 0:
        noun = "față" if faces == 1 else "fețe"
        return CheckResult(
            "faces",
            "FAILED",
            True,
            float(faces),
            f"YuNet a găsit {faces} {noun} în imagine; biblia vizuală interzice fețele",
        )
    return CheckResult("faces", "PASSED", False, float(faces), counted.detail_ro)


def local_checks(
    path: Path | str,
    plan: StillPlan,
    *,
    environment: str,
    ffmpeg_path: str | None = None,
    face_model: Path | None = None,
    face_counter: FaceCounter | None = None,
    measure: Sequence[str] = ALL_CHECKS,
) -> list[CheckResult]:
    """The zero-credit checks on one still, in a fixed order.

    `measure` narrows the set (a caller that already measured some of them, or a test);
    `decide` names every required check that is missing, so a narrowed set never passes
    silently in PRODUCTION.
    """
    ffmpeg = find_ffmpeg(ffmpeg_path)
    no_encoder = "nu există codorul ffmpeg sau fișierul imaginii"
    checks: list[CheckResult] = []
    if "degenerate" in measure:
        if not ffmpeg or not Path(path).is_file():
            checks.append(
                _unmeasured(
                    "degenerate", f"Structura nu a fost măsurată: {no_encoder}", environment
                )
            )
        else:
            broken = still_is_degenerate(ffmpeg, Path(path))
            checks.append(
                CheckResult(
                    "degenerate", "FAILED", True, None, f"Imaginea nu e o imagine: {broken}"
                )
                if broken
                else CheckResult("degenerate", "PASSED", False, None, "structură de imagine")
            )
    if "sharpness" in measure:
        sharpness = measure_sharpness(ffmpeg, path)
        if sharpness is None:
            checks.append(
                _unmeasured(
                    "sharpness", f"Claritatea nu a fost măsurată: {no_encoder}", environment
                )
            )
        elif sharpness < SHARPNESS_FLOOR:
            checks.append(
                CheckResult(
                    "sharpness",
                    "FAILED",
                    True,
                    sharpness,
                    f"Imaginea e neclară: {sharpness:.0f} sub pragul de {SHARPNESS_FLOOR} "
                    f"(la {MEASURE_WIDTH} px)",
                )
            )
        else:
            checks.append(
                CheckResult("sharpness", "PASSED", False, sharpness, f"claritate {sharpness:.0f}")
            )
    if "motion_blur" in measure:
        anisotropy = measure_anisotropy(ffmpeg, path)
        static = plan.camera_move.strip().lower() in STATIC_MOVES
        if anisotropy is None:
            checks.append(
                _unmeasured(
                    "motion_blur",
                    f"Neclaritatea de mișcare nu a fost măsurată: {no_encoder}",
                    environment,
                )
            )
        elif anisotropy >= MOTION_BLUR_ANISOTROPY:
            detail = (
                f"Imaginea are mișcare încremenită în ea (raport {anisotropy:.1f}, "
                f"prag {MOTION_BLUR_ANISOTROPY})"
            )
            checks.append(
                CheckResult("motion_blur", "FAILED", True, anisotropy, detail + " pe un cadru fix")
                if static
                else CheckResult("motion_blur", "WARNING", False, anisotropy, detail)
            )
        else:
            checks.append(
                CheckResult("motion_blur", "PASSED", False, anisotropy, f"raport {anisotropy:.1f}")
            )
    if "palette" in measure:
        distance = measure_palette(ffmpeg, path, plan.palette_words)
        if distance is None:
            checks.append(
                CheckResult(
                    "palette",
                    "NOT_RUN",
                    False,
                    None,
                    "Paleta nu a fost comparată: aspectul filmului nu numește culori cunoscute",
                )
            )
        elif distance > PALETTE_WARN_DELTA_E:
            checks.append(
                CheckResult(
                    "palette",
                    "WARNING",
                    False,
                    distance,
                    f"Culorile se depărtează de aspectul filmului (ΔE {distance:.0f}, "
                    f"prag {PALETTE_WARN_DELTA_E:.0f})",
                )
            )
        else:
            checks.append(CheckResult("palette", "PASSED", False, distance, f"ΔE {distance:.0f}"))
    if "faces" in measure:
        checks.append(
            _faces_check(path, plan, environment, face_counter or count_faces, face_model)
        )
    return checks


# --------------------------------------------------------------------------- deciding


def _required(plan: StillPlan) -> tuple[str, ...]:
    base = ("degenerate", "sharpness", "motion_blur")
    return base + (("faces",) if plan.faces_forbidden else ())


def _is_none(text: str) -> bool:
    return text.strip().lower().rstrip(".") in _NONE_WORDS


def _sha256(path: Path | str) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _score(checks: Sequence[CheckResult], judgement: StillJudgement | None) -> float:
    """How good a passing still is, 0..1, for choosing between candidates."""
    by_code = {check.code: check for check in checks}
    sharp = by_code.get("sharpness")
    palette = by_code.get("palette")
    score = 0.5 * min((sharp.value or 0) / 1000, 1.0) if sharp and sharp.value else 0.0
    if palette is not None and palette.value is not None:
        score += 0.3 * (1 - min(palette.value / 60, 1.0))
    else:
        score += 0.15
    if judgement is not None and judgement.verdict is not None and judgement.verdict.look_ok:
        score += 0.2
    return round(score, 4)


def decide(
    path: Path | str,
    plan: StillPlan,
    checks: Sequence[CheckResult],
    judgement: StillJudgement | None,
    *,
    environment: str,
) -> StillReport:
    """Fold the local checks and the vision verdict into one decision. Fail closed."""
    reasons: list[str] = []
    warnings: list[str] = []
    violations: list[str] = []
    unmeasured: list[str] = []
    faces_found = False
    for check in checks:
        if (
            check.code == "faces"
            and check.status in ("PASSED", "FAILED")
            and (check.value or 0) > 0
        ):
            faces_found = True
        if check.blocking:
            reasons.append(check.detail_ro)
            (unmeasured if check.status == "NOT_RUN" else violations).append(check.code)
        elif check.status in ("WARNING", "NOT_RUN"):
            warnings.append(check.detail_ro)
    present = {check.code for check in checks}
    for code in _required(plan):
        if code not in present:
            detail = f"Verificarea „{code}” nu a rulat pe această imagine"
            if environment == "PRODUCTION":
                reasons.append(detail)
                unmeasured.append(code)
            else:
                warnings.append(detail)

    verdict = judgement.verdict if judgement is not None else None
    if judgement is None or judgement.status != "MEASURED" or verdict is None:
        detail = (
            judgement.detail_ro
            if judgement is not None and judgement.detail_ro
            else "nu a fost privită: modelul de vedere nu a fost întrebat"
        )
        reasons.append(f"Imaginea {detail}")
        unmeasured.append("vision")
    else:
        said = f"«{verdict.reason}»"
        if verdict.faces_visible:
            faces_found = True
            if plan.faces_forbidden:
                reasons.append(
                    f"Modelul de vedere a văzut o față; biblia vizuală interzice fețele {said}"
                )
                violations.append("faces")
        if verdict.readable_text:
            reasons.append(f"Modelul de vedere a văzut text lizibil în imagine {said}")
            violations.append("readable_text")
        if not verdict.matches_plan:
            reasons.append(f"Imaginea nu arată ce cere planul scenei {said}")
            violations.append("plan")
        if not verdict.look_ok:
            reasons.append(f"Imaginea nu are aspectul filmului {said}")
            violations.append("look")
        if not verdict.technical_ok:
            reasons.append(f"Imaginea are defecte tehnice {said}")
            violations.append("technical")
        if not _is_none(verdict.bible_violations):
            reasons.append(f"Imaginea încalcă biblia vizuală: «{verdict.bible_violations}»")
            violations.append("bible")
        if verdict.verdict != "buy_motion":
            reasons.append(f"Verdictul modelului de vedere: {verdict.verdict} {said}")

    blocked = bool(reasons)
    if not blocked:
        outcome = "buy_motion"
    elif verdict is not None and verdict.verdict == "compose_locally":
        outcome = "compose_locally"
    else:
        outcome = "regenerate_still"
    measured = {check.code: check.value for check in checks if check.value is not None}
    return StillReport(
        path=str(path),
        sha256=_sha256(path),
        scene=plan.scene,
        checks=tuple(checks),
        judgement=judgement,
        decision="BLOCKED" if blocked else "PASSED",
        outcome=outcome,
        reasons_ro=tuple(reasons),
        warnings_ro=tuple(warnings),
        faces_found=faces_found,
        violations=tuple(dict.fromkeys(violations)),
        unmeasured=tuple(dict.fromkeys(unmeasured)),
        score=0.0 if blocked else _score(checks, judgement),
        measured=measured,
    )


def check_still(
    engine: Engine,
    registry: Any | None,
    path: Path | str,
    plan: StillPlan,
    correlation_id: str,
    *,
    environment: str | None = None,
    ffmpeg_path: str | None = None,
    face_model: Path | None = None,
    face_counter: FaceCounter | None = None,
    measure: Sequence[str] = ALL_CHECKS,
) -> StillReport:
    """Local checks, then one vision call, then the decision. 0 credits."""
    if environment is None:
        from app.services import studio_environment  # noqa: PLC0415

        environment = studio_environment(engine)
    checks = local_checks(
        path,
        plan,
        environment=environment,
        ffmpeg_path=ffmpeg_path,
        face_model=face_model,
        face_counter=face_counter,
        measure=measure,
    )
    judgement = judge_still(engine, registry, path, plan, correlation_id, ffmpeg_path=ffmpeg_path)
    return decide(path, plan, checks, judgement, environment=environment)


# ------------------------------------------------------------ choosing and re-rolling


def choose_best(reports: Iterable[StillReport]) -> StillReport | None:
    """The passing candidate with the best check score; None when none passes."""
    passing = [report for report in reports if report.decision == "PASSED"]
    if not passing:
        return None
    return max(passing, key=lambda report: (report.score, report.sha256 or ""))


def positive_instruction(violations: Iterable[str]) -> str:
    """The violations rewritten as words the image model obeys (English, for the model)."""
    words = [POSITIVE_WORDS[code] for code in dict.fromkeys(violations) if code in POSITIVE_WORDS]
    return "; ".join(words)


def next_step(report: StillReport, *, rerolls_done: int) -> NextStep:
    """What the stills step does with this candidate. It never pushes a failing still on."""
    if report.decision == "PASSED":
        return NextStep(
            "buy_motion", "", "Imaginea a trecut verificările; se poate cumpăra mișcarea."
        )
    if report.outcome == "compose_locally":
        return NextStep(
            "compose_locally",
            "",
            f"Scena {report.scene} se compune local, gratuit: {report.reasons_ro[-1]}",
        )
    first = report.reasons_ro[0] if report.reasons_ro else "motiv nenumit"
    if not report.violations:
        # Only "could not measure": another still would be judged by the same missing eye.
        return NextStep(
            "needs_owner",
            "",
            f"Scena {report.scene}: verificările nu au putut rula ({first}). "
            "Nu se cumpără altă imagine până nu decide Proprietarul.",
        )
    if rerolls_done < MAX_REROLLS:
        return NextStep(
            "reroll",
            positive_instruction(report.violations),
            f"Scena {report.scene}: imaginea se reface ({rerolls_done + 1}/{MAX_REROLLS}): {first}",
        )
    return NextStep(
        "needs_owner",
        positive_instruction(report.violations),
        f"Scena {report.scene}: după {MAX_REROLLS} refaceri imaginea tot nu trece ({first}). "
        "Decide Proprietarul pe foaia de filmare.",
    )
