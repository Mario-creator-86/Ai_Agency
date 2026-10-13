"""The stills gate: nothing is animated until someone has looked at the still.

The Nepal film paid for twelve clips before anybody looked at a picture. Three of its stills
showed faces that the visual bible forbade, one was a woman where a bar chart should have
been, one a landscape where a black screen should have been, and quality control only found
out after the whole film was bought. A still costs 9 credits; the clip made from it costs
up to 68 credits a second. So the still is checked first, twice, at no credit cost:

1. Local checks (`local_checks`), measured with the encoder the studio already has and the
   YuNet face detector (`app.media.faces`):
   - degenerate: stripes, bands or a blank field (`app.media.qc.still_is_degenerate`);
   - panels: one picture, not several. On 2026-10-09 scene 5 of «The Particle That Shouldn't
     Exist (But Does)» was compiled into a still prompt that described a sequence of moments
     ("... holding together as atoms, then the empty accelerator tunnel from scene 1. First
     the near-black void of scenes 2 and 3, then the identical tunnel ..."), and the still
     came out as THREE STACKED PANELS: a tunnel with a glowing atom, a flat black band, an
     empty tunnel. Its clip animated the triptych. The prompt lint, this gate, the vision
     checklist (told the plan, it found a triptych matched a plan that lists three moments)
     and clip QC all passed it. Pictures pasted together are held apart by a flat band, so
     the still is read in grey at 270x480 (area scaling): a row is flat when its standard
     deviation is under 4 and its range under 24, and a run of flat full-width rows of at
     least 15 % of the height blocks the still, between two pictures or at an edge (a
     letterbox, a blank lower third), whatever is beside it, unless the picture rises out of
     it gradually at one edge (the night sky below). Clip QC and the film's QC make the same
     reading on their frames with one waiver a still does not get: a frame flat but for two
     lines of burned-in captions (under 10 % of rows not flat,
     `app.media.qc.FRAME_PICTURE_FLOOR`), or flat from edge to edge (a fade to black), has
     no pictures to hold apart. The first version waived that on stills too, beside under
     15 % of picture, and its review (2026-10-09) passed a black 1530x2720 still with a strip
     of a good still 260 or 300 px tall (9.6 % and 11 % of rows not flat, a band of about
     half the height) through this check and the degenerate one (which refuses a strip of
     200 px, 7.5 %, and passes these); a blank still now fails both. On 2026-10-10 the
     Director ordered a new scene-5 still and Qwen-Image delivered single photographs of a
     glowing cluster of spheres over wet ground at night, a black sky over the top quarter;
     this check refused every one before anybody looked, and each re-roll was paid again. A
     band glued to ONE edge (top or bottom) whose inner edge is soft is the scene's own sky,
     void or background, not a strip pasted on: no row mean within 4 rows of that edge (the
     band's last rows and the first rows past it) differs from its neighbour's by 3 or more
     (`app.media.qc.SOFT_EDGE_STEP`; the "step" below). It passes, on a still and on a frame.
     A band in the middle, a band from edge to edge and an edge band with a hard edge block
     as before, and a hard band of 15 % or more is read before a wider soft one, so a sky
     does not hide a strip pasted at the other edge. Read by `app.media.qc.flat_band`. Measured with
     it on that film's stills (1530x2720 PNG, read only; tests/fixtures/panels keeps 270x480
     JPEG copies of six of them, which read the same, and grey 270x480 PNG copies of the
     six below of 2026-10-10, the pixels flat_band reads: JPEG copies of those read a band
     a row or two off on four of them):
       scene_05_c7c55abb_c1   rows 159-320, 34 %    the triptych (fails)
       scene_02_a1d8d1bf_c1   rows 321-479, 33 %    a black lower third, to the edge, step
                                                    9.96 (fails; 11.06 on its JPEG copy)
       scene_05_d067fe4c_c1   rows 0-125, 26 %      a night sky over the spheres, step 0.53
       scene_05_b22f4a8e_c2   rows 0-107, 22 %      the same, step 0.45
       scene_05_082e6b31_c1   rows 0-144, 30 %      the same, step 0.40
       scene_05_95b4f17e_c2   rows 0-128, 27 %      the same, step 0.44
       scene_05_1927d68d_c1   rows 0-102, 21 %      spheres in a black void, step 0.34, and
                              rows 381-479, 21 %    under them, step 0.36
       scene_05_2062c362_c2   rows 0-72, 15 %       a misty grey sky, step 1.35
       every other good still 28 rows at most, 6 %  scene_02_cc3a68a6_c2's dark ceiling, 0-27
                                                    (step 1.23)
       the Nepal fixtures     49 rows at most, 10 % scene_05.jpg: 0-48 and 444-479
     The six of 2026-10-10 were refused until then and pass since. The threshold sits 1.5x
     over the widest band of the good stills of 2026-10-09 and 2.2x under the triptych's;
     the step's, 2.2x over the misty sky's and 3.3x under the black third's. A strip pasted
     with a soft edge onto a dark picture passes here: the vision checklist below sees every
     still this check passes. The second scene-5 candidate, scene_05_0d900cbd_c2, is a
     triptych of three similar tunnels with no flat band (2 flat rows): neither a single
     full-width seam (a natural edge in the good scene_04_f606d968_c2 crosses 88 % of the
     columns) nor the correlation of adjacent rows separates it, so its net is the vision
     checklist's one_picture question below;
   - sharpness (`measure_focus`), two readings at 1080 px width on an 8 x 14 grid of tiles. A
     still is in focus when its subject is: a documentary frame with a sharp subject before a
     dark, soft background (shallow depth of field) is not a blurred frame. Until 2026-10-09
     the Laplacian variance was pooled over every tile that held a picture, floor 250; the
     five stills of «The Particle That Shouldn't Exist (But Does)» (a worker in blue coveralls
     and a white hard hat, sharp, in a dark tunnel kept soft on purpose) read 70-182 on it and
     were all rejected, so scenes 2-5 were never bought. Now:
     * sharpness: each tile's 4-neighbour Laplacian variance with its strongest 5 % of
       responses left out (one hard line, a letterbox bar's edge or a box drawn on a blurred
       picture, is 1-3 % of a tile), read at the median of the sharpest tenth of the tiles (the
       6th of 112: a subject's worth of the frame). Floor 30;
     * fine detail kept: the share of those tiles' Laplacian energy left once the picture is
       halved and restored (bicubic). Real fine detail lives in the octave that takes away,
       so a sharp still keeps little of it; a 2x upscale or a picture softened before delivery
       keeps most of it, whatever its texture or contrast. At most 48 %.
     Measured 2026-10-09 with this code on the five delivered 1530x2720 PNGs (scene_01_
     ac5b5e97_c1, 340ebcb1_c2, 14aec523_c1, b5f88e79_c2, d1e900d3_c1, read only) and on copies
     of them made in a scratch folder (the sigmas at 1080 px unless said):
       as delivered                67 / 255 / 70 / 67 / 261, kept 16 / 28 / 17 / 21 / 20 %
       Gaussian sigma 1            12-49, kept 55-66 %         (fails)
       Gaussian sigma 2 and 4      22 at most, kept 75 % up    (fails; at 1080 or at 1530 px)
       saved at 540 px wide        11-51, kept 68-79 %         (fails)
       to 512 px and back up       10-45, kept 72-83 %         (fails)
       sigma 3-4 + letterbox bars  5-6                         (fails; the top-5 mean read 262)
       sigma 4 + a small white box 5-6                         (fails; the top-5 mean read 1228)
       sigma 4 + one subtitle line 11-15                       (fails)
     The six Nepal stills as tests/fixtures/factual_sample keeps them (540x960 JPEG) read
     53-305 but keep 51-54 % (52-56 % upscaled to 1530x2720 bicubic): they fail, their half
     resolution is soft at 1080. Upscaled with lanczos and an unsharp mask (the rehearsal's
     stand-ins) they keep 40-45 % and pass: a sharpened upscale is left to the vision check.
     The floor sits 2.2x under the softest real still (67) and 2x over the sharpest overlay
     on a blurred frame (15); the 48 % sits 1.7x over the real stills' 28 %, between the
     sharpened upscales' 45 % and the plain ones' 51 %;
   - motion blur: the ratio of horizontal to vertical gradient energy. Nepal stills read
     1.1-1.5; a 12 px horizontal smear reads above 5. Blocks a static shot, warns on a
     moving one (a pan may carry some blur honestly);
   - palette: mean CIELAB distance of the picture to the colours the look block names in
     words. A score and a warning, never a block: it is a coarse measure, and the vision
     model's look_ok and the Owner's eye are the real judges of a look;
   - faces: the YuNet count, when the bible forbids faces.
2. The vision checklist (`app.media.picture_qc.judge_still`): one call per still at
   1080 px, with a verdict schema that has no field a silent model could pass by. Since
   2026-10-09 it asks whether the still is ONE continuous photograph (one_picture), and tells
   the model a still is one moment, the shot's first frame: a plan that lists several
   moments is judged on its first, and a picture of several moments does not match it.
3. The fix check (2026-10-12, `app.media.fix_check`). A still bought after the Director had
   the scene's words rewritten carries what the rewrite was written to fix
   (`StillPlan.must_fix`: her review's findings with the sentence that treats each, and the
   film QC's words about the scene). The vision checklist answers, item by item, whether the
   new still still shows the mistake, and a still that repeats one is refused here
   («Imaginea repetă greșeala pe care rescrierea trebuia să o corecteze», violation
   ``finding_persists``) before any clip is bought on it; another candidate that fixes
   everything is chosen instead. The Owner, 16:50: «să se asigure că ce a fost greșit este
   acum corectat. Nu să facă aceeași greșeală la nesfârșit!» — on f06808c9 scene 4 the
   rewrite answered «two women face to face instead of a single on Nadia» in words, and only
   the film's QC, after the money, looked for the two women again.
   Since the late evening of 2026-10-12 (the review of 9ac0195) each item is answered gone,
   minor or persists: only persists refuses, a minor trace is a warning the take carries
   («DIRECTOAREA ACCEPTĂ DEFECTELE MICI!»). A still that repeats the mistake while it matches
   its plan proves the corrected WORDS do not correct it: it is not re-rolled on them (the
   same words twice more were up to four paid stills of the same mistake), the scene ends at
   once as a content refusal for the Director's ladder, which rewrites them; a still that also
   missed its plan gets one re-roll at most (`next_step`, action ``rewrite``).
   That night (the review of 5fc7468): an item she called minor that persists is a warning,
   never ``finding_persists`` (`fix_answers`); the content phrase (`REWRITE_PHRASE`) leads the
   refusal so it survives the take's 500 characters; and a round whose sibling shows every
   item corrected keeps its words (`round_step`): they can correct it.

Everything fails closed. A check that could not run is NOT_RUN, and a NOT_RUN of a
required check blocks in PRODUCTION and warns in TEST — except the vision checklist, whose
silence blocks everywhere ("nu a fost privită"): a still nobody looked at is never bought
into motion. A face from EITHER detector blocks when the bible forbids faces; panels from
EITHER reading (the flat band, or one_picture false) block and are re-rolled. A verdict of
buy_motion whose own answers contradict it (text seen, more than one picture, plan not
matched, a violation named) does not pass: the answers win over the summary.

What happens next is `next_step`: a passing still buys motion; a still that should have
been a card is routed to the local compositor; a failing still is re-rolled at most twice,
with its violations rewritten as positive words the image model obeys
(`positive_instruction`), and then goes to the Owner. A block that is only "could not
measure" is never re-rolled: buying another still does not install a detector. Before any
re-roll is bought for a round the gate refused whole, the Director looks at the refused
candidates the bible's hard limits did not stop (`may_be_overturned`; the stills step,
`stills_stage._director_looks`): her look may approve one, and then nothing is bought.
"""

from __future__ import annotations

import hashlib
import math
import subprocess
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from app.media.faces import FaceCount, FaceCounter, count_faces
from app.media.fix_check import (
    GONE,
    HARD_LIMITS,
    MINOR,
    MINOR_SEVERITY,
    PERSISTS,
    SERIOUS_SEVERITY,
    fix_status,
    minor_traces,
)
from app.media.picture_qc import StillJudgement, judge_still
from app.media.qc import PANEL_BAND_SHARE, flat_band, still_is_degenerate
from app.media.toolchain import find_ffmpeg

#: The width every picture check measures at: the final film's width.
MEASURE_WIDTH = 1080
#: Laplacian variance floor at 1080 px, read on the median of the sharpest tenth of the tiles
#: (see the module docstring for the measurements).
SHARPNESS_FLOOR = 30
TILES_ACROSS, TILES_DOWN = 8, 14
#: The sharpness is read on the sharpest 1/SHARPEST_SHARE of the tiles (11 of 112), at their
#: median: a subject's worth of the frame must be sharp, whatever the background does.
SHARPEST_SHARE = 10
#: The share of a tile's strongest Laplacian responses left out of its variance: one hard line
#: (a letterbox bar's edge, a box drawn on the picture) is 1-3 % of a tile and says nothing
#: about the focus of the rest.
TRIM_SHARE = 0.05
#: The most of its Laplacian energy (over the sharpest tenth of the tiles) a still may keep when
#: it is halved and restored: real fine detail does not survive that, an upscale or a softened
#: picture keeps most of it (see the module docstring for the measurements).
FINE_DETAIL_KEPT_MAX = 0.48
#: Where the sharpness term of a passing still's score is full, on a log scale: 100 x the floor,
#: so a sharper take of the same picture scores higher without saturating.
SHARPNESS_SCORE_SPAN = 100
#: Horizontal/vertical gradient-energy ratio (either way round) at which a still carries
#: baked motion blur.
MOTION_BLUR_ANISOTROPY = 2.5
#: Mean CIELAB distance to the look's named colours above which the palette is flagged.
PALETTE_WARN_DELTA_E = 30.0
#: How many times a failing still is bought again before the Owner decides.
MAX_REROLLS = 2
#: How many times a still that repeats a corrected mistake is bought again on the same words,
#: when it also missed its plan (one that showed its plan is never: its words are rewritten).
PERSISTS_REROLLS = 1
#: The gate's content phrase (`scene_rewrite.CONTENT_REFUSAL_PHRASES` reads «nu arată ce cere
#: scena»): a refusal that begins with it is read as CONTENT by the Director's ladder, which
#: rewrites the words instead of buying them again. It goes FIRST in such a refusal: a take's
#: failure detail keeps 500 characters, and on 2026-10-12 (the review of 5fc7468, finding 2)
#: the longer «persists» refusal pushed it past them, so the serial read the refusal as
#: TECHNICAL and re-rolled the very words that had not corrected the mistake.
REWRITE_PHRASE = "Nu arată ce cere scena după rescriere"
#: The gate's violations that say the WORDS ask for the wrong picture (what the ladder reads as
#: a content refusal): another seed on them buys the same mistake. The others (blur, a smear,
#: a technical defect, panels, a blank field) are one picture's fault, which a re-roll answers.
CONTENT_VIOLATIONS = frozenset(
    {"plan", "scene", "look", "bible", "faces", "readable_text", "finding_persists"}
)
#: The local checks' measured floors her look may be asked about (the bible's hard limits
#: never are): a still they refused is kept by her look only when she says the defect is not
#: in it (`fix_check.look_accepts`, ``measured``) — the shared contract of 2026-10-12, night.
MEASURED_VIOLATIONS = frozenset({"sharpness", "motion_blur"})

ALL_CHECKS = ("degenerate", "panels", "sharpness", "motion_blur", "palette", "faces")

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
    "panels": "one single continuous photograph filling the whole frame from edge to edge",
    "look": "light, palette and grain exactly as the film's look describes",
    "plan": "the subject exactly as the scene's plan describes it",
    "technical": "natural anatomy, clean edges, clean texture",
    "bible": "every rule of the visual bible kept",
    # A still that repeats what the rewrite was meant to correct (`StillPlan.must_fix`): the
    # corrected words are already in the prompt; the re-roll leans on them.
    "finding_persists": "the picture exactly as the scene's corrected words describe it",
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
    #: What the SCENE asks for, beside the words the still was asked with: its written picture
    #: (the storyboard scene's `visual_prompt`), the narration spoken over it and its purpose.
    #: The film's picture QC judges the finished film against these (`picture_qc`, «the
    #: picture is not what the scene asked for»); until 2026-10-12 the gate judged a still
    #: only against its prompt, so a still that matched a prompt which had lost the scene's
    #: subject was bought a clip for, assembled and failed — five paid rounds of scene 5 of
    #: «The Particle That Shouldn't Exist (And Briefly Didn't)».
    #: Since the evening of 2026-10-12 the stills step gives the scriptwriter's own line here
    #: (the package's ``writer_visual``), not ``visual_prompt``: the shot-prompt writer stores
    #: the compiled still prompt there, so the «scene» shown was the plan again and
    #: shows_scene could only repeat matches_plan (read on the database copy: equal on
    #: 1c038a99 scene 5, aa170155 scene 1 and f06808c9 scene 4).
    scene_picture: str = ""
    narration: str = ""
    purpose: str = ""
    #: What the scene's current words were rewritten to fix (`fix_check.open_findings`): each
    #: {"finding", "expected", "layer", "source", "source_id", "cause"} — quality control's own
    #: words, the correction's sentence (guidance), where it came from. Empty when nothing is
    #: open, and then nothing about the check changes. Otherwise the vision checklist answers
    #: each item gone, minor or persists (`picture_qc.judge_still`); a still on which one
    #: persists is refused (`decide`, ``finding_persists``). Clip QC reads the motion layer's
    #: items from the same field of its own plan (`assembler._clip_plan`).
    must_fix: tuple[dict[str, Any], ...] = ()


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
    #: The vision checklist's answer to each `StillPlan.must_fix` item, in its order:
    #: {"finding", "expected", "status" (gone | minor | persists | None when unanswered),
    #: "fixed" (status gone), "seen"}; empty when nothing was asked (or nobody looked).
    fixes: tuple[dict[str, Any], ...] = ()
    #: The items whose trace the look called minor: accepted, carried as a warning on the take
    #: (`fix_check.record_take_note`) and on the stills step's entry.
    minor: tuple[dict[str, str], ...] = ()

    @property
    def matched_plan(self) -> bool:
        """Whether the look said the still shows its plan (its words, drawn as asked)."""
        return "plan" not in self.violations


@dataclass(frozen=True)
class NextStep:
    #: buy_motion | compose_locally | reroll | needs_owner | rewrite — ``rewrite``: the still
    #: repeats what its corrected words were meant to fix while it shows them, so no other
    #: picture is bought on them; the scene ends as a content refusal and the Director's
    #: ladder rewrites the words (2026-10-12, the review of 9ac0195, finding 3).
    action: str
    instruction: str
    reason_ro: str


# ------------------------------------------------------------------------ measuring


def _raw_gray(
    ffmpeg: str,
    path: Path | str,
    kernel: str | None = None,
    rdiv: float = 1.0,
    width: int = MEASURE_WIDTH,
    *,
    halved: bool = False,
) -> bytes | None:
    """The picture as 8-bit full-range luma at `width`, optionally convolved.

    A convolution is written with a bias of 128 and scaled by `rdiv`, so a signed response
    fits a byte; the caller undoes the scale on the variance. ``halved``: the picture is first
    scaled to half that width and back (bicubic), which takes away its finest octave.
    """
    chain = f"scale={width}:-2:flags=bicubic,format=gray"
    if halved:
        chain += ",scale=iw/2:ih/2:flags=bicubic,scale=iw*2:ih*2:flags=bicubic"
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


def _trimmed_variance(data: bytes, share: float = TRIM_SHARE) -> float:
    """Variance of a biased convolution's bytes once the `share` of them farthest from 128 (its
    zero) is left out, from the histogram: what one hard line in the tile cannot make."""
    if not data:
        return 0.0
    histogram = Counter(data)
    drop = int(len(data) * share)
    kept: dict[int, int] = {}
    for value in sorted(histogram, key=lambda v: (-abs(v - 128), v)):
        count = histogram[value]
        taken = min(drop, count)
        drop -= taken
        if count > taken:
            kept[value] = count - taken
    total = sum(kept.values())
    if not total:
        return 0.0
    mean = sum(value * n for value, n in kept.items()) / total
    return sum(n * (value - mean) ** 2 for value, n in kept.items()) / total


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


#: The 4-neighbour Laplacian, as ffmpeg's convolution matrix.
LAPLACIAN = "0 1 0 1 -4 1 0 1 0"


@dataclass(frozen=True)
class Focus:
    """What the sharpness check reads on a still (`measure_focus`)."""

    #: Trimmed Laplacian variance at 1080 px, the median of the sharpest tenth of the tiles.
    sharpness: float
    #: The share of those tiles' Laplacian energy left once the still is halved and restored.
    fine_kept: float


def measure_focus(ffmpeg: str | None, path: Path | str) -> Focus | None:
    """How sharp the still's sharpest part is, and whether its fine detail is real.

    The subject decides whether a still is in focus, not the background: a dark tunnel or a
    sky kept soft on purpose says nothing about the focus. So each tile of the 8 x 14 grid is
    read on its own (its Laplacian variance, the strongest 5 % of its responses left out, so
    one hard line cannot make it), and the still reads the median of its sharpest tenth: a
    subject's worth of the frame (6 tiles of 112) must be sharp. Then the same picture is
    halved and restored: real fine detail lives in the octave that takes away, so a sharp
    still keeps a small share of those tiles' energy, and an upscale, or a picture softened
    before it was delivered, keeps most of it, however much texture it has.

    None only when it cannot be measured; a blank field reads close to 0, keeping all of it.
    """
    if not ffmpeg or not Path(path).is_file():
        return None
    laplacian = _raw_gray(ffmpeg, path, LAPLACIAN, 0.25)
    restored = _raw_gray(ffmpeg, path, LAPLACIAN, 0.25, halved=True)
    if laplacian is None or restored is None or len(laplacian) != len(restored):
        return None
    # The response was divided by 4 to fit a byte: its variance is 16 times smaller.
    own = [_trimmed_variance(tile) * 16 for tile in _tiles(laplacian, MEASURE_WIDTH)]
    kept = [_trimmed_variance(tile) * 16 for tile in _tiles(restored, MEASURE_WIDTH)]
    order = sorted(range(len(own)), key=lambda index: own[index], reverse=True)
    sharpest = order[: max(1, len(order) // SHARPEST_SHARE)]
    energy = sum(own[index] for index in sharpest)
    share = sum(kept[index] for index in sharpest) / energy if energy > 1e-9 else 1.0
    return Focus(sharpness=round(own[sharpest[len(sharpest) // 2]], 1), fine_kept=round(share, 3))


def measure_sharpness(ffmpeg: str | None, path: Path | str) -> float | None:
    """The sharpness `measure_focus` reads (the trimmed Laplacian variance at 1080 px of the
    median of the sharpest tenth of the tiles), or None."""
    focus = measure_focus(ffmpeg, path)
    return None if focus is None else focus.sharpness


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
    if "panels" in measure:
        band = flat_band(ffmpeg, path)
        if band is None:
            checks.append(
                _unmeasured(
                    "panels", f"Benzile imaginii nu au fost măsurate: {no_encoder}", environment
                )
            )
        elif band.splits_a_still:
            # A measured violation, so it is re-rolled with the positive words, unlike a
            # check that could not run. The frames' waiver for captions and fades
            # (qc.FRAME_PICTURE_FLOOR) is not a still's: a black still with a strip of
            # picture 9.6 % tall passed both local checks under it.
            checks.append(
                CheckResult(
                    "panels",
                    "FAILED",
                    True,
                    round(band.share, 3),
                    f"Imaginea nu e o singură fotografie: {band.detail_ro()}",
                )
            )
        else:
            # A wide band passes only glued to one edge with a soft edge: the scene's own
            # night sky or background (2026-10-10, qc.SOFT_EDGE_STEP).
            checks.append(
                CheckResult(
                    "panels",
                    "PASSED",
                    False,
                    round(band.share, 3),
                    f"o singură imagine: {band.soft_edge_ro()}"
                    if band.wide
                    else f"o singură imagine: cea mai lată bandă plată are {band.rows} rânduri "
                    f"din {band.height} ({band.share:.0%}, prag {PANEL_BAND_SHARE:.0%})",
                )
            )
    if "sharpness" in measure:
        focus = measure_focus(ffmpeg, path)
        if focus is None:
            checks.append(
                _unmeasured(
                    "sharpness", f"Claritatea nu a fost măsurată: {no_encoder}", environment
                )
            )
        elif focus.sharpness < SHARPNESS_FLOOR:
            checks.append(
                CheckResult(
                    "sharpness",
                    "FAILED",
                    True,
                    focus.sharpness,
                    f"Imaginea e neclară: {focus.sharpness:.0f} sub pragul de {SHARPNESS_FLOOR} "
                    f"(la {MEASURE_WIDTH} px)",
                )
            )
        elif focus.fine_kept > FINE_DETAIL_KEPT_MAX:
            checks.append(
                CheckResult(
                    "sharpness",
                    "FAILED",
                    True,
                    focus.sharpness,
                    f"Imaginea e moale (mărită sau estompată): înjumătățită și refăcută își "
                    f"păstrează {focus.fine_kept:.0%} din detaliul fin, peste pragul de "
                    f"{FINE_DETAIL_KEPT_MAX:.0%} (la {MEASURE_WIDTH} px)",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "sharpness",
                    "PASSED",
                    False,
                    focus.sharpness,
                    f"claritate {focus.sharpness:.0f}; la înjumătățire rămâne "
                    f"{focus.fine_kept:.0%} (prag {FINE_DETAIL_KEPT_MAX:.0%})",
                )
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
    base = ("degenerate", "panels", "sharpness", "motion_blur")
    return base + (("faces",) if plan.faces_forbidden else ())


def _is_none(text: str) -> bool:
    return text.strip().lower().rstrip(".") in _NONE_WORDS


def _sha256(path: Path | str) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _sharpness_term(value: float | None) -> float:
    """The sharpness reading as 0..1 for the score: 0 at the floor, 1 at `SHARPNESS_SCORE_SPAN`
    times it, on a log scale. The five 2026-10-09 stills read 67-261 (0.18-0.47), noise reads
    thousands; a linear /1000 saturated on the readings of the old whole-picture measure."""
    if not value or value <= SHARPNESS_FLOOR:
        return 0.0
    return min(math.log(value / SHARPNESS_FLOOR) / math.log(SHARPNESS_SCORE_SPAN), 1.0)


def _score(checks: Sequence[CheckResult], judgement: StillJudgement | None) -> float:
    """How good a passing still is, 0..1, for choosing between candidates."""
    by_code = {check.code: check for check in checks}
    sharp = by_code.get("sharpness")
    palette = by_code.get("palette")
    score = 0.5 * _sharpness_term(sharp.value) if sharp is not None else 0.0
    if palette is not None and palette.value is not None:
        score += 0.3 * (1 - min(palette.value / 60, 1.0))
    else:
        score += 0.15
    if judgement is not None and judgement.verdict is not None and judgement.verdict.look_ok:
        score += 0.2
    return round(score, 4)


def _excerpt(text: Any, limit: int) -> str:
    """At most ``limit`` characters of ``text``, cut at a word with an ellipsis."""
    said = " ".join(str(text or "").split())
    if len(said) <= limit:
        return said
    return said[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


#: The order of an item's answers, worst last: two answers for one item read as the worse.
_STATUS_RANK = {GONE: 0, MINOR: 1, PERSISTS: 2}


def fix_answers(must_fix: Sequence[Any], verdict: Any) -> list[dict[str, Any]]:
    """The look's answer to each ``must_fix`` item, by its number (1-based), as {"finding",
    "expected", "status", "fixed", "seen", "layer", "source", "source_id", "severity"}:
    ``status`` the worst of the item's answers (gone, minor, persists), None when the item was
    not answered; ``fixed`` whether it is gone; the item's own layer, source, review run and
    severity carried beside, so the lessons are settled per review run
    (`fix_check.confirm_lessons`, `fix_check.withdraw_lessons`) and clip QC knows which layer a
    persisting item lives on. Empty when nothing was asked. Read by the gate and by clip QC
    (`qc.check_clip`).

    An item the Director called MINOR (her review's ``severity``) that the look says persists
    reads as minor: a trace she accepts, a warning — never ``finding_persists``, never a
    withdrawn lesson. 2026-10-12, the Owner: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!» (the review
    of 5fc7468, finding 1: such an item refused every still that showed it again, and each was
    bought again)."""
    asked = tuple(must_fix or ())
    if not asked:
        return []
    given: dict[int, list[Any]] = {}
    for fix in getattr(verdict, "fixes", None) or []:
        given.setdefault(int(fix.item), []).append(fix)
    answers: list[dict[str, Any]] = []
    for number, item in enumerate(asked, start=1):
        said_item = dict(item or {})
        carried = {
            "layer": said_item.get("layer"),
            "source": said_item.get("source"),
            "source_id": said_item.get("source_id"),
            "severity": said_item.get("severity") or SERIOUS_SEVERITY,
        }
        finding = str(said_item.get("finding") or "")
        expected = str(said_item.get("expected") or "")
        said = [fix for fix in given.get(number) or [] if fix_status(fix) is not None]
        if not said:
            answers.append(
                {
                    "finding": finding,
                    "expected": expected,
                    "status": None,
                    "fixed": None,
                    "seen": "",
                    **carried,
                }
            )
            continue
        worst = max(said, key=lambda fix: _STATUS_RANK[str(fix_status(fix))])
        status = str(fix_status(worst))
        if status == PERSISTS and carried["severity"] == MINOR_SEVERITY:
            status = MINOR
        answers.append(
            {
                "finding": finding,
                "expected": expected,
                "status": status,
                "fixed": status == GONE,
                "seen": str(worst.seen or ""),
                **carried,
            }
        )
    return answers


def corrected_everything(report: StillReport) -> bool:
    """Whether the look answered every item of the still corrected: gone, or a minor trace
    she accepts. Such a still proves the corrected words CAN correct the mistake."""
    return bool(report.fixes) and all(fix.get("status") in (GONE, MINOR) for fix in report.fixes)


def content_refusal(report: StillReport) -> bool:
    """Whether a refused still says its WORDS ask for the wrong picture (`CONTENT_VIOLATIONS`),
    not one picture's technical fault."""
    return bool(set(report.violations) & CONTENT_VIOLATIONS)


def measured_refusal(report: StillReport) -> bool:
    """Whether a refused still was refused by a measured floor (`MEASURED_VIOLATIONS`)."""
    return bool(set(report.violations) & MEASURED_VIOLATIONS)


def _fix_answers(plan: StillPlan, verdict: Any) -> list[dict[str, Any]]:
    return fix_answers(getattr(plan, "must_fix", ()), verdict)


def persists_reason(fix: Mapping[str, Any]) -> str:
    """The refusal of a picture that shows a corrected mistake again, in the gate's words: the
    content phrase FIRST (`REWRITE_PHRASE`, read by the Director's ladder as a content refusal,
    so the words are rewritten, never re-rolled — it must survive the take's 500 characters),
    then what quality control saw, that the corrected words did not correct it (the sentence
    that failed), and what the look sees."""
    expected = _excerpt(fix.get("expected"), 120)
    words = (
        f"cuvintele «{expected}» nu au corectat-o"
        if expected
        else "cuvintele rescrise nu au corectat-o"
    )
    return (
        f"{REWRITE_PHRASE}: imaginea repetă greșeala pe care rescrierea trebuia să o corecteze "
        f"«{_excerpt(fix.get('finding'), 160)}»; {words}"
        + (f" (se vede: {_excerpt(fix.get('seen'), 120)})" if fix.get("seen") else "")
    )


def minor_warning(fix: Mapping[str, Any]) -> str:
    """The warning of a minor trace the look accepted (the Owner: «DIRECTOAREA ACCEPTĂ
    DEFECTELE MICI!»)."""
    return f"Urmă mică a greșelii «{_excerpt(fix.get('finding'), 160)}» în imagine, acceptată" + (
        f" (se vede: {_excerpt(fix.get('seen'), 120)})" if fix.get("seen") else ""
    )


def decide(
    path: Path | str,
    plan: StillPlan,
    checks: Sequence[CheckResult],
    judgement: StillJudgement | None,
    *,
    environment: str,
) -> StillReport:
    """Fold the local checks and the vision verdict into one decision. Fail closed.

    The reasons are ordered for the take's failure detail, which keeps 500 characters and is
    read back by the Director's ladder by its phrases: what the fix check found first (a
    corrected mistake seen again, an item nobody could check — the content phrase), then the
    look's other readings, then the local checks, then «nu a fost privită» (the review of
    5fc7468, finding 2: the content phrase was pushed past the cut)."""
    reasons: list[str] = []
    fix_reasons: list[str] = []
    vision_reasons: list[str] = []
    unseen_reasons: list[str] = []
    warnings: list[str] = []
    violations: list[str] = []
    unmeasured: list[str] = []
    fixes: list[dict[str, Any]] = []
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
        unseen_reasons.append(f"Imaginea {detail}")
        unmeasured.append("vision")
        if plan.must_fix:
            # A still bought on corrected words that nobody could check for the mistake: the
            # serial's ladder read the bare «nu a fost privită» as TECHNICAL and bought the
            # same words again (the review of 9ac0195, finding 8). With what it had to show
            # unknown, the refusal is about the content: the content phrase sends it to her.
            fix_reasons.append(
                "Nu s-a putut verifica dacă greșeala «"
                + _excerpt(plan.must_fix[0].get("finding"), 120)
                + "» a dispărut: până se vede, se socotește că nu arată ce cere scena după "
                "rescriere"
            )
    else:
        said = f"«{verdict.reason}»"
        # First among all the reasons (`fix_reasons`): the refusal's words land on the take's
        # failure detail (500 characters), which the Director's ladder reads back by phrase.
        fixes = _fix_answers(plan, verdict)
        for fix in fixes:
            if fix["status"] is None:
                # Only a verdict built in code can leave an item out: the report a model's
                # answer is read into refuses it (`picture_qc.still_report_schema`).
                fix_reasons.append(
                    "Modelul de vedere nu a spus dacă imaginea corectează greșeala "
                    f"«{_excerpt(fix['finding'], 160)}»"
                )
                unmeasured.append("vision")
            elif fix["status"] == PERSISTS:
                # The content phrase sends the scene to her brief at the ladder, never to the
                # serial's re-roll of the same words (`scene_rewrite.refusal_kind`).
                fix_reasons.append(persists_reason(fix))
                violations.append("finding_persists")
            elif fix["status"] == MINOR:
                # A small trace, accepted: said on the take, never a refusal.
                warnings.append(minor_warning(fix))
        if verdict.faces_visible:
            faces_found = True
            if plan.faces_forbidden:
                vision_reasons.append(
                    f"Modelul de vedere a văzut o față; biblia vizuală interzice fețele {said}"
                )
                violations.append("faces")
        if verdict.readable_text:
            vision_reasons.append(f"Modelul de vedere a văzut text lizibil în imagine {said}")
            violations.append("readable_text")
        if not verdict.one_picture:
            # 2026-10-09: scene 5's triptych of three similar tunnels had no flat band to
            # measure; the model's eye is its net. A measured violation: re-rolled.
            vision_reasons.append(
                "Modelul de vedere nu vede o singură fotografie (panouri, colaj, ecran împărțit "
                f"sau o bandă goală) {said}"
            )
            violations.append("panels")
        if not verdict.matches_plan:
            vision_reasons.append(f"Imaginea nu arată ce cere planul scenei {said}")
            violations.append("plan")
        if not verdict.shows_scene:
            # The same question the film's picture QC asks after the money is spent, asked
            # here for 7 credits: the scene's written picture and narration, not the prompt.
            vision_reasons.append(
                f"Imaginea nu arată ce cere scena (imaginea ei scrisă și narațiunea) {said}"
            )
            violations.append("scene")
        if not verdict.look_ok:
            vision_reasons.append(f"Imaginea nu are aspectul filmului {said}")
            violations.append("look")
        if not verdict.technical_ok:
            vision_reasons.append(f"Imaginea are defecte tehnice {said}")
            violations.append("technical")
        if not _is_none(verdict.bible_violations):
            vision_reasons.append(f"Imaginea încalcă biblia vizuală: «{verdict.bible_violations}»")
            violations.append("bible")
        if verdict.verdict != "buy_motion":
            vision_reasons.append(f"Verdictul modelului de vedere: {verdict.verdict} {said}")

    # What the fix check found first, the look's readings next, the local checks, then
    # «nu a fost privită»: the content phrase must survive the take's 500 characters.
    reasons = fix_reasons + vision_reasons + reasons + unseen_reasons
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
        fixes=tuple(fixes),
        minor=tuple(minor_traces(fixes)),
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
    """The passing candidate with the fewest minor traces left of what its words were
    rewritten to fix, then the best check score; None when none passes."""
    passing = [report for report in reports if report.decision == "PASSED"]
    if not passing:
        return None
    return max(passing, key=lambda report: (-len(report.minor), report.score, report.sha256 or ""))


def may_be_overturned(report: StillReport) -> bool:
    """Whether the Director may be asked to look again at a refused candidate before anything
    is bought for its scene: a refusal the gate measured whole (nothing unmeasured) whose
    reasons are a reading — the plan, the scene, the look, the technique, a corrected mistake
    seen again — and none of the bible's hard limits (`fix_check.HARD_LIMITS`: a face where
    faces are forbidden, writing, panels, a blank field), which stay the code's."""
    return (
        report.decision == "BLOCKED"
        and bool(report.violations)
        and not report.unmeasured
        and not set(report.violations) & HARD_LIMITS
        and report.outcome != "compose_locally"
    )


def positive_instruction(violations: Iterable[str]) -> str:
    """The violations rewritten as words the image model obeys (English, for the model)."""
    words = [POSITIVE_WORDS[code] for code in dict.fromkeys(violations) if code in POSITIVE_WORDS]
    return "; ".join(words)


def rewrite_step(scene: int, why: str) -> NextStep:
    """The scene's words go back to the Director's ladder (`NextStep` action ``rewrite``): its
    reason begins with the content phrase (`REWRITE_PHRASE`), so whatever take of the round
    the ladder reads, it reads a content refusal."""
    return NextStep(
        "rewrite",
        "",
        f"Scena {scene}: {REWRITE_PHRASE[:1].lower()}{REWRITE_PHRASE[1:]} — {why} Nu se "
        "cumpără altă imagine pe aceleași cuvinte; Directoarea le rescrie.",
    )


def next_step(report: StillReport, *, rerolls_done: int, words_correct: bool = False) -> NextStep:
    """What the stills step does with this candidate. It never pushes a failing still on.

    ``words_correct``: another candidate of the same round showed every item corrected
    (`corrected_everything`), so the corrected words CAN correct the mistake and this one's
    repeat of it is one picture's fault — re-rolled like any other, its words not sent back
    (2026-10-12, the review of 5fc7468, finding 13)."""
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
    if (
        "finding_persists" in report.violations
        and not words_correct
        and (report.matched_plan or rerolls_done >= PERSISTS_REROLLS)
    ):
        # 2026-10-12 (the review of 9ac0195, finding 3): the picture shows its corrected words
        # and the mistake is there again, so those words do not correct it; two more re-rolls
        # on them were up to four paid stills of the same mistake. The words are rewritten.
        persisted: Mapping[str, Any] = next(
            (fix for fix in report.fixes if fix.get("status") == PERSISTS),
            report.fixes[0] if report.fixes else {},
        )
        expected = _excerpt(persisted.get("expected"), 120)
        words = f"cuvintele «{expected}»" if expected else "cuvintele rescrise"
        how = (
            "arată planul și repetă totuși greșeala"
            if report.matched_plan
            else "repetă greșeala și după o refacere"
        )
        return rewrite_step(
            report.scene,
            f"imaginea {how} «{_excerpt(persisted.get('finding'), 120)}»: {words} nu au "
            "corectat-o.",
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


def round_step(reports: Sequence[StillReport], *, rerolls_done: int) -> NextStep | None:
    """What one round of refused candidates leads to (`next_step` of the candidate that
    decides it): a candidate that shows its corrected words and repeats the mistake decides —
    its words are rewritten, nothing more is bought on them —, else the first that was measured
    wrong, else the first. None when the round has no candidate at all.

    The words are sent back only when no candidate of the round showed every item corrected
    (`corrected_everything`): a sibling refused for something else (a blur, its plan) that
    shows the mistake gone proves the words can correct it, and the round is re-rolled
    (2026-10-12, the review of 5fc7468, finding 13)."""
    if not reports:
        return None
    words_correct = any(corrected_everything(report) for report in reports)
    deciding = next(
        (
            report
            for report in reports
            if "finding_persists" in report.violations and report.matched_plan and not words_correct
        ),
        next((report for report in reports if report.violations), reports[0]),
    )
    return next_step(deciding, rerolls_done=rerolls_done, words_correct=words_correct)
