"""Phase 5 Quality Control (QC) Gate.

Following docs/architecture/08_VIDEO_PIPELINE.md:
- Technical QC: valid 9:16 aspect ratio, duration within bounds, file size > 0.
- Factual QC: every referenced claim must remain SUPPORTED in the database.
- Picture QC: a model that can see reads one frame per scene and says whether it is a
  picture at all, whether it is ONE picture (not panels) and whether it shows what the scene
  asked for (app.media.picture_qc).
- Picture spans QC: every filmed scene is judged on the first, middle and last frame of its
  span on the film's timeline, at the delivered 1080 px, with the per-clip checklist
  (picture_qc.judge_clip), YuNet counts faces on each frame when the bible forbids them, and
  each frame is read for a flat band that splits it into panels (`flat_band`).
- Character Drift QC: the same look, against the Character Bible's canonical description.
- Rights/License QC: all assets must be clear of copyright blocks.
- Audio QC: the film measures at the platform's loudness, under the true-peak ceiling.
- Captions QC: the SRT beside the film parses, keeps to two lines of forty-two, and carries
  the narration.
- Motion QC: how much of the film moves; a production film that is mostly stills pushed
  slowly because the motion model refused is a slideshow, and fails.
"""

from __future__ import annotations

import difflib
import functools
import hashlib
import importlib
import json
import logging
import math
import pkgutil
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.memory import agent_for_role, remember
from app.agents.vision import SPAN_FRAME_WIDTH, frames_at
from app.db import lock_for_write
from app.factual.editorial import dangles
from app.factual.models import FactualClaim
from app.media.cards import film_finish
from app.media.markings import planned_markings
from app.media.models import (
    MediaAsset,
    QualityControlReport,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.picture_qc import (
    CARRIED_STATUS,
    CLIP_TEMPLATE_VERSION,
    FRAME_SOURCES,
    MAX_SUBTITLE_LINES,
    CleanShot,
    FrameSource,
    StudioText,
    caption_rows,
    carried_forward,
    carry_keys,
    clean_shots,
    cut_caption_rows,
    evaluate_pictures,
    film_captions,
    film_scene_prompts,
    judge_clip,
)
from app.media.prompt_lint import bible_face_rule
from app.media.renders_cap import clip_retries, renders_of_ro
from app.media.schemas import QCReportView
from app.media.toolchain import (
    LOUDNESS_TARGET_LUFS,
    TRUE_PEAK_CEILING_DBTP,
    find_ffmpeg,
    find_ffprobe,
    has_filter,
    measure_loudness,
    silence_spans,
)
from app.services import append_event, studio_environment, utc_now

logger = logging.getLogger("studio.qc")

#: The caption rules quality control holds a film to, the same numbers the assembler writes
#: to. Named here again rather than imported so that reading a film never imports the
#: machinery that makes one.
CAPTION_LINE_CHARS = 42
CAPTION_MAX_LINES = 2

#: How closely the captions must follow the narration, word for word, to count as covering
#: it. The studio's own SRT is the narration verbatim; the margin is for a caption a hand
#: tidied, not for one that dropped a sentence.
CAPTION_COVERAGE_RATIO = 0.95

_SRT_TIMING = re.compile(
    r"^\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*$"
)


def _srt_seconds(hours: str, minutes: str, seconds: str, millis: str) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000.0


def parse_srt(text: str) -> list[dict[str, Any]]:
    """Read a SubRip file into cues, or raise ValueError where it is not one.

    Every cue is ``{"index", "start", "end", "lines"}`` in seconds. An empty file is no cues.
    A block without the arrow, or that ends before it starts, is refused rather than read
    around: a caption file the platform would reject is not one the studio delivers.
    """
    body = (text or "").lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not body:
        return []
    cues: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", body):
        lines = block.split("\n")
        if len(lines) < 2:
            raise ValueError(f"SRT block {len(cues) + 1} has no timing line")
        try:
            index = int(lines[0].strip())
        except ValueError as exc:
            raise ValueError(f"SRT block {len(cues) + 1} does not start with a number") from exc
        timing = _SRT_TIMING.match(lines[1])
        if timing is None:
            raise ValueError(f"SRT cue {index} has no 'start --> end' timing")
        start = _srt_seconds(*timing.groups()[:4])
        end = _srt_seconds(*timing.groups()[4:])
        if end < start:
            raise ValueError(f"SRT cue {index} ends before it starts")
        cues.append(
            {
                "index": index,
                "start": start,
                "end": end,
                "lines": [line.rstrip() for line in lines[2:] if line.strip()],
            }
        )
    return cues


def caption_problems(cues: list[dict[str, Any]], *, dangling: bool = False) -> list[str]:
    """What keeps these cues from being read on a phone; empty when nothing does.

    ``dangling`` adds the phrase rule (audit Q7): a cue other than the last that ends on a
    function word ("Nepal is paying for a") breaks its phrase in two. It is asked for by the
    editorial check (`editorial_problems`), which is advisory until the Owner decides, so the
    delivery check above keeps its verdict on the films made before the rule.
    """
    problems: list[str] = []
    previous_end: float | None = None
    if dangling:
        for found in dangling_caption_words(cues):
            problems.append(f"cue {found['cue']} ends on the function word '{found['word']}'")
    for cue in cues:
        index = cue.get("index")
        lines = list(cue.get("lines") or [])
        if not lines:
            problems.append(f"cue {index} is empty")
        if len(lines) > CAPTION_MAX_LINES:
            problems.append(
                f"cue {index} has {len(lines)} lines, more than {CAPTION_MAX_LINES} lines"
            )
        longest = max((len(line) for line in lines), default=0)
        if longest > CAPTION_LINE_CHARS:
            problems.append(
                f"cue {index} has a line of {longest} characters, more than {CAPTION_LINE_CHARS}"
            )
        if float(cue["end"]) <= float(cue["start"]):
            problems.append(f"cue {index} has no duration")
        if previous_end is not None and float(cue["start"]) < previous_end - 0.001:
            problems.append(f"cue {index} overlaps the cue before it")
        previous_end = float(cue["end"])
    return problems


def dangling_caption_words(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The cues (but the last) whose last word leaves its phrase open, with that word."""
    found: list[dict[str, Any]] = []
    for position, cue in enumerate(cues[:-1]):
        words = " ".join(str(line) for line in cue.get("lines") or []).split()
        if words and dangles(words[-1]):
            found.append({"cue": cue.get("index", position + 1), "word": words[-1]})
    return found


def _words(text: str) -> list[str]:
    return "".join(c.lower() if c.isalnum() else " " for c in text).split()


#: Assets whose visuals came from a local placeholder generator. Placeholder frames are not
#: broadcastable content, so QC refuses to certify them for publication.
PLACEHOLDER_PROVIDER_PREFIX = "PLACEHOLDER"


def probe_media_file(file_path: Path, ffmpeg_path: str | None = None) -> dict[str, Any]:
    """Measure a media file with ffprobe. Returns measured facts, never assumptions.

    Result keys: ``available`` (ffprobe present), ``ok`` (file parsed and has a video stream),
    ``width``, ``height``, ``duration_seconds``, ``video_codec``, ``error``.

    ``ffmpeg_path`` is the studio's configured encoder, used only to find ffprobe beside it when
    the installer put one on PATH and not the other.
    """
    ffprobe = find_ffprobe(ffmpeg_path)
    if not ffprobe:
        return {"available": False, "ok": False, "error": "ffprobe not installed"}
    try:
        res = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return {"available": True, "ok": False, "error": f"ffprobe failed: {exc}"}
    if res.returncode != 0:
        return {"available": True, "ok": False, "error": (res.stderr or "").strip()[:400]}
    try:
        data = json.loads(res.stdout)
    except ValueError as exc:
        return {"available": True, "ok": False, "error": f"unparsable ffprobe output: {exc}"}

    video = next((st for st in data.get("streams", []) if st.get("codec_type") == "video"), None)
    if not video:
        return {"available": True, "ok": False, "error": "file contains no video stream"}
    try:
        duration = float(data.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        duration = 0.0

    # A container is as long as its longest stream, so a film with six seconds of picture
    # under forty-six seconds of narration measures as forty-six. The picture is measured
    # on its own stream — frames over frame rate where both are known.
    def _number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    fps = None
    rate = str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "")
    if "/" in rate:
        top, _, bottom = rate.partition("/")
        top_value, bottom_value = _number(top), _number(bottom)
        if top_value and bottom_value:
            fps = top_value / bottom_value
    frames = _number(video.get("nb_frames"))
    stream_seconds = _number(video.get("duration"))
    if frames and fps:
        stream_seconds = frames / fps
    # The average video bitrate: the stream's own figure, else the container's minus the
    # sound's. None when neither is stated; never a guess.
    video_bit_rate = _number(video.get("bit_rate"))
    audio_rates = [
        _number(st.get("bit_rate"))
        for st in data.get("streams", [])
        if st.get("codec_type") == "audio"
    ]
    if video_bit_rate is None:
        total_rate = _number(data.get("format", {}).get("bit_rate"))
        if total_rate is not None and all(rate is not None for rate in audio_rates):
            video_bit_rate = total_rate - sum(rate or 0.0 for rate in audio_rates)
    return {
        "available": True,
        "ok": True,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "duration_seconds": round(duration, 2),
        "video_duration_seconds": round(stream_seconds, 2) if stream_seconds else None,
        "video_frames": int(frames) if frames else None,
        "video_fps": round(fps, 3) if fps else None,
        "video_codec": video.get("codec_name"),
        "video_profile": video.get("profile"),
        "pix_fmt": video.get("pix_fmt"),
        "color_range": video.get("color_range"),
        "color_space": video.get("color_space"),
        "color_primaries": video.get("color_primaries"),
        "color_transfer": video.get("color_transfer"),
        "video_bit_rate": int(video_bit_rate) if video_bit_rate else None,
        "has_audio": any(st.get("codec_type") == "audio" for st in data.get("streams", [])),
        "error": None,
    }


#: How much of a still survives being flattened along one axis, measured as SSIM against the
#: original. A real picture loses most of its structure: 0.18–0.76 across the thirteen stills
#: of the studio's two September films, and 0.89/0.91 for the smoothest of them, a plain sky.
#: Vertical stripes lose nothing when every column is squeezed to one pixel — 0.961 for the
#: payoff of "How ATLAS Caught the Higgs Boson", eleven seconds of beige bars that quality
#: control scored 1.0 and the Director approved. A blank field loses nothing either way.
DEGENERATE_SSIM = 0.94


def still_is_degenerate(ffmpeg: str | None, path: Path) -> str | None:
    """Why a still is not a picture (stripes, bands, a blank field), or None when it is one.

    Measured with the encoder the studio already has: the still is squeezed to a single row
    (and then to a single column), stretched back, and compared with itself. No image library,
    no model, no opinion. None also when it cannot be measured — this check refuses pictures,
    it never invents a refusal.
    """
    import re  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    if not ffmpeg or not Path(path).is_file():
        return None
    scores: dict[str, float] = {}
    for axis, collapse in (("columns", "270:1"), ("rows", "1:480")):
        try:
            result = subprocess.run(  # noqa: S603 - argument list, no shell
                [
                    ffmpeg,
                    "-v",
                    "info",
                    "-nostats",
                    "-i",
                    str(path),
                    "-filter_complex",
                    f"[0]scale=270:480,split[a][b];[b]scale={collapse}:flags=area,"
                    "scale=270:480:flags=neighbor[c];[a][c]ssim",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        match = re.search(r"All:([0-9.]+)", result.stderr or "")
        if not match:
            return None
        scores[axis] = float(match.group(1))
    columns, rows = scores["columns"], scores["rows"]
    if columns >= DEGENERATE_SSIM and rows >= DEGENERATE_SSIM:
        return f"blank or uniform picture, no scene (structure {columns:.2f}/{rows:.2f})"
    if columns >= DEGENERATE_SSIM:
        return f"vertical stripes, no scene (structure {columns:.2f})"
    if rows >= DEGENERATE_SSIM:
        return f"horizontal bands, no scene (structure {rows:.2f})"
    return None


# ------------------------------------------------------------- one picture, not panels
#
# 2026-10-09, «The Particle That Shouldn't Exist (But Does)»: scene 5's still came out as three
# stacked panels (a tunnel with a glowing atom, a flat black band, an empty tunnel) because its
# prompt described a sequence of moments, its clip animated the triptych, and every check
# passed both. Pictures pasted together are held apart by a flat band: the strip between two
# of them, or a blank strip at an edge (a letterbox, an empty lower third). This reads it, on
# a still (`app.media.still_gate`), on a clip's frames and on a film's frames alike. The
# thresholds and the readings they were set on are in still_gate's docstring.
#
# 2026-10-10, the same film: the Director ordered a new scene-5 still and Qwen-Image delivered
# single photographs of a glowing cluster of spheres over wet ground at night, a black night
# sky over their top quarter. This check refused every one before anybody looked (rows 0-125
# of 480, 26 %), and each re-roll was paid again. A night sky is as flat as a pasted strip,
# but the picture rises out of it: around the band's inner edge (its last 4 rows and the
# first 4 rows past it) the row mean changes by at most 0.53 between neighbouring rows on
# those stills, and by 1.35 under a misty grey sky, while a strip pasted on jumps: 9.96 at
# the black lower third of scene_02_a1d8d1bf_c1, 70 at the top of the triptych's band. So a
# band glued to ONE edge (top or bottom) whose inner edge is soft (`SOFT_EDGE_STEP`) is the
# scene's own sky, void or background and does not split the picture. A band in the middle
# (between two pictures, where no soft edge is read), a band from edge to edge and an edge
# band with a hard edge split it as before, and a hard band of PANEL_BAND_SHARE is read
# before a wider soft one (`flat_band`), so a sky does not hide a strip pasted at the other
# edge. A soft-edged strip pasted on a dark picture passes here; the vision look
# (picture_qc.judge_still, `one_picture`) sees every still that passes.

#: The size a picture's rows are read at (area-averaged grey), the degenerate check's size.
PANEL_READ_SIZE = (270, 480)
#: A row is flat when its standard deviation is under this and its range (max - min) under
#: FLAT_ROW_RANGE, in 8-bit grey at PANEL_READ_SIZE.
FLAT_ROW_STD = 4.0
FLAT_ROW_RANGE = 24
#: The least share of the height a run of flat full-width rows covers to split the picture.
PANEL_BAND_SHARE = 0.15
#: On a clip's or a film's frame, the least share of rows that are not flat beside the band
#: for it to split the frame. A film's frame carries burned-in captions, and a frame flat but
#: for them is a blank field (a fade to black, a grey vendor fake), not panels: in the
#: zero-credit dry run (test_film_dry_run, 2026-10-09) the flat grey vendor clips under
#: captions read a band of 70-74 % beside 3.1-7.3 % of rows that are not flat, 7.3 % being
#: two lines at the largest caption size (assembler.CAPTION_FONT_SIZE, CAPTION_MAX_LINES).
#: 10 % leaves 13 rows over that for accents and outline. A still is read without it
#: (`FlatBand.splits_a_still`): it carries no captions and does not fade, and a review of the
#: first version (2026-10-09), which waived any band beside under 15 % of picture everywhere,
#: passed a black still with a strip of picture 260 or 300 px tall through both local checks.
FRAME_PICTURE_FLOOR = 0.10
#: How many rows on each side of a band's inner edge are read for a soft edge: the band's last
#: rows and the first rows of picture past it. Area scaling spreads a hard edge over two rows
#: (scene_02_a1d8d1bf_c1 steps 19.0 -> 9.1 -> 2.2), and the picture's own content starts
#: further in (on scene_05_082e6b31_c1 the spheres raise the step to 7.5 within 12 rows).
SOFT_EDGE_ROWS = 4
#: A band glued to one edge is soft-edged, the scene's own sky or background, when no row mean
#: within SOFT_EDGE_ROWS of its inner edge differs from its neighbour's by this much (8-bit
#: grey at PANEL_READ_SIZE). Measured 2026-10-10: 0.34-0.53 under the night skies of scene 5,
#: 1.35 under a misty grey sky, 1.23 under scene_02_cc3a68a6_c2's dark ceiling; 9.96 at the
#: black lower third pasted under scene_02_a1d8d1bf_c1 (11.06 on its JPEG copy). 3 sits 2.2x
#: over the largest step under a sky and 3.3x under the pasted third's.
SOFT_EDGE_STEP = 3.0
#: The widest band a soft edge excuses. The widest sky measured was 30 % (scene_05_082e6b31_
#: c1); a still more than half flat is a blank field with a strip of picture faded into it,
#: which the look alone would otherwise have to catch (review of this rule, 2026-10-10).
SOFT_BAND_MAX_SHARE = 0.5
#: A flat band glued to the BOTTOM edge that is a coloured surface of the scene — a desk
#: front, a floor, the base of a wall — not a strip pasted on: its grey level is neither
#: black nor white (SURFACE_LEVELS, 8-bit) and it takes no more than SURFACE_BAND_MAX_SHARE of
#: the height. 2026-10-16 02:33Z, 87c05891: the dark wood front of Sarah's desk, 16 % of the
#: frame in every scene drawn from the episode's reference picture, refused four scenes as
#: «o bandă plată pe toată lățimea, jos» before the look saw them. Black bands (the Nepal
#: lower third, letterboxes) and white caption strips stay splits.
SURFACE_LEVELS = (24.0, 231.0)
SURFACE_BAND_MAX_SHARE = 0.3
#: A dark surface is still a drawn surface when its rows carry texture — wood grain, shading
#: — where a pasted black strip has none: the mean range of a row's grey within the band.
#: Measured 2026-10-16 05:04Z on 87c05891's desk fronts (grey level 7-12, read as black):
#: mean row range 7.5-10.7; a pasted pure strip reads 0-1.
SURFACE_TEXTURE_MIN = 4.0


@dataclass(frozen=True)
class FlatBand:
    """The run of flat full-width rows of a picture read at 270x480 that decides whether it
    is one picture (`flat_band`): the longest that splits it, else the longest."""

    #: Its first and last row (inclusive), 0 at the top; both -1 when no row is flat.
    start: int
    end: int
    #: The rows read, and the flat ones in any run.
    height: int
    flat_rows: int
    #: For a band glued to one edge (top or bottom), the largest change of row mean between
    #: neighbouring rows within SOFT_EDGE_ROWS of its inner edge; None for a band in the
    #: middle, a band from edge to edge, or no band.
    edge_step: float | None = None
    #: The band's mean grey (8-bit) over its rows; None when no band.
    level: float | None = None
    #: The mean range (max - min grey) of the band's rows: its texture; None when no band.
    texture: float | None = None

    @property
    def rows(self) -> int:
        return 0 if self.start < 0 else self.end - self.start + 1

    @property
    def share(self) -> float:
        return self.rows / self.height if self.height else 0.0

    @property
    def picture_share(self) -> float:
        """The share of the rows that are not flat: the picture beside the bands."""
        return (self.height - self.flat_rows) / self.height if self.height else 0.0

    @property
    def wide(self) -> bool:
        """At least PANEL_BAND_SHARE of the height: wide enough to split the picture."""
        return self.share >= PANEL_BAND_SHARE

    @property
    def soft_edge(self) -> bool:
        """Glued to one edge, with the picture rising out of it gradually (under
        SOFT_EDGE_STEP), and no more than SOFT_BAND_MAX_SHARE of the height: the scene's own
        sky, void or background, not a strip pasted on."""
        return (
            self.edge_step is not None
            and self.edge_step < SOFT_EDGE_STEP
            and self.share <= SOFT_BAND_MAX_SHARE
        )

    @property
    def surface(self) -> bool:
        """Glued to the bottom edge only, a coloured surface of the scene (SURFACE_LEVELS:
        neither black nor white) and no more than SURFACE_BAND_MAX_SHARE of the height: a desk
        front, a floor, the base of a wall — the picture's own, not a strip pasted on."""
        if not (self.rows > 0 and self.start > 0 and self.end == self.height - 1):
            return False
        if self.share > SURFACE_BAND_MAX_SHARE:
            return False
        coloured = self.level is not None and SURFACE_LEVELS[0] <= self.level <= SURFACE_LEVELS[1]
        textured = self.texture is not None and self.texture >= SURFACE_TEXTURE_MIN
        return coloured or textured

    @property
    def splits_a_still(self) -> bool:
        """On a still, any band of at least PANEL_BAND_SHARE of the height but a soft-edged
        one at the top or the bottom, or a coloured surface at the bottom (`surface`):
        pictures pasted together, a picture with a blank strip, or a blank field (which the
        degenerate check refuses as well). Nothing on a still is burned in and nothing fades,
        so no amount of blank beside a strip of picture makes it one photograph."""
        return self.wide and not self.soft_edge and not self.surface

    @property
    def splits_the_picture(self) -> bool:
        """On a clip's or a film's frame, a band of at least PANEL_BAND_SHARE of the height
        beside at least FRAME_PICTURE_FLOOR of picture, but a soft-edged one at the top or the
        bottom (a night clip has the still's sky). A frame that is flat but for two lines of
        captions, or flat from edge to edge, has no pictures to hold apart: it is a blank
        field, the look's and the editorial check's, and on a clip most often a fade to
        black, the motion's fault, for which a new still would be bought in vain."""
        return self.splits_a_still and self.picture_share >= FRAME_PICTURE_FLOOR

    @property
    def where_ro(self) -> str:
        if self.rows == 0:
            return "nicăieri"
        top, bottom = self.start == 0, self.end == self.height - 1
        if top and bottom:
            return "pe toată înălțimea, un câmp gol fără imagine"
        if top:
            return "sus, lipită de margine"
        if bottom:
            return "jos, lipită de margine"
        return "la mijloc, între două imagini"

    def detail_ro(self) -> str:
        """The band in the Owner's words, with its rows and the threshold."""
        if self.rows == 0:
            return f"niciun rând plat pe toată lățimea (prag {PANEL_BAND_SHARE:.0%} din înălțime)"
        return (
            f"o bandă plată pe toată lățimea, {self.where_ro} (rândurile {self.start}-{self.end} "
            f"din {self.height}, {self.share:.0%} din înălțime; prag {PANEL_BAND_SHARE:.0%})"
        )

    def soft_edge_ro(self) -> str:
        """A wide band the soft edge lets pass, in the Owner's words."""
        side = "de sus" if self.start == 0 else "de jos"
        return (
            f"banda plată {side} trece lin în imagine (cer sau fundal), nu e o bandă lipită "
            f"(rândurile {self.start}-{self.end} din {self.height}, {self.share:.0%} din "
            f"înălțime; cea mai mare treaptă între două rânduri vecine la marginea ei: "
            f"{self.edge_step or 0.0:.1f}, prag {SOFT_EDGE_STEP:.0f})"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "band_start": self.start if self.rows else None,
            "band_end": self.end if self.rows else None,
            "band_rows": self.rows,
            "band_share": round(self.share, 3),
            "flat_rows": self.flat_rows,
            "picture_share": round(self.picture_share, 3),
            "height": self.height,
            "edge_step": None if self.edge_step is None else round(self.edge_step, 2),
            "soft_edge": self.soft_edge,
            "splits_the_picture": self.splits_the_picture,
        }


def _edge_step(means: list[float], start: int, end: int) -> float | None:
    """The largest change of row mean between neighbouring rows within SOFT_EDGE_ROWS of the
    inner edge of a band glued to one edge; None for a band in the middle or edge to edge."""
    height = len(means)
    top, bottom = start == 0, end == height - 1
    if top == bottom:
        return None
    # The band's inner edge lies between row `edge` and row `edge + 1`.
    edge = end if top else start - 1
    first, last = max(0, edge - SOFT_EDGE_ROWS + 1), min(height - 1, edge + SOFT_EDGE_ROWS)
    return max(abs(means[y + 1] - means[y]) for y in range(first, last))


def flat_band(ffmpeg: str | None, path: Path | str) -> FlatBand | None:
    """The run of flat full-width rows that decides whether a picture (or a clip's first
    frame) is one picture, read in grey at 270x480 with area scaling: a row is flat when its
    standard deviation is under FLAT_ROW_STD and its range under FLAT_ROW_RANGE. The longest
    run that splits the picture (`FlatBand.splits_a_still`), else the longest run: a soft
    sky at the top does not hide a strip pasted at the bottom.

    None only when it cannot be read (no encoder, no file, an undecodable picture); a picture
    with no flat row reads a band of 0 rows.
    """
    if not ffmpeg or not Path(path).is_file():
        return None
    width, height = PANEL_READ_SIZE
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
                f"scale={width}:{height}:flags=area,format=gray",
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
    data = result.stdout
    if result.returncode != 0 or len(data) != width * height:
        return None
    means: list[float] = []
    ranges: list[int] = []
    runs: list[tuple[int, int]] = []
    run_start, flat_rows = -1, 0
    for y in range(height + 1):
        flat = False
        if y < height:
            row = data[y * width : (y + 1) * width]
            mean = sum(row) / width
            means.append(mean)
            ranges.append(max(row) - min(row))
            if max(row) - min(row) < FLAT_ROW_RANGE:
                flat = sum((value - mean) ** 2 for value in row) / width < FLAT_ROW_STD**2
        if flat:
            flat_rows += 1
            if run_start < 0:
                run_start = y
        elif run_start >= 0:
            # The run ended on the row before this one (or at the bottom edge).
            runs.append((run_start, y - 1))
            run_start = -1
    bands = [
        FlatBand(
            start,
            end,
            height,
            flat_rows,
            _edge_step(means, start, end),
            level=sum(means[start : end + 1]) / (end - start + 1),
            texture=sum(ranges[start : end + 1]) / (end - start + 1),
        )
        for start, end in runs
    ]
    if not bands:
        return FlatBand(start=-1, end=-1, height=height, flat_rows=flat_rows)
    # The topmost of equals, as before the soft edge was read.
    return max(bands, key=lambda band: (band.splits_a_still, band.rows))


# ------------------------------------------------------ how the film was made (A12)
#
# The second Nepal render (3ec1740c, 2026-09-26) was bought whole by the legacy path from
# template prompts after its shot plan was lost, and never reached quality control: it sat in
# the queue as a video with no verdict, one QC pass away from publishing. Real stills and shots
# are bought on the shooting sheet only since that day, so a film that says otherwise about
# itself fails here, whatever the file measures.

#: The day the whole-film path stopped being a way to buy a film: the Nepal film, bought whole
#: twice. A render started earlier is not judged again on the path it was made on (the films
#: made and published before the staircase), only on what it measures.
STAIRCASE_CUTOVER = "2026-09-26T00:00:00+00:00"
#: The image source a film assembled from its takes records (`assembler.TAKES_VISUAL_SOURCE`).
TAKES_SOURCE = "SCENE_TAKES"


def paid_vendor_names() -> frozenset[str]:
    """The ``PROVIDER_NAME`` of every paid vendor adapter, by the rule the legacy path's guard
    applies (`factory.is_paid_vendor_class`): a sixth vendor is paid until it is listed free."""
    return _paid_vendor_names()


@functools.lru_cache(maxsize=1)
def _paid_vendor_names() -> frozenset[str]:
    import app.providers as providers  # noqa: PLC0415
    from app.media.factory import (  # noqa: PLC0415 - factory imports the vendors
        FREE_PROVIDER_MODULES,
        is_paid_vendor_class,
    )

    names: set[str] = set()
    for found in pkgutil.iter_modules(providers.__path__):
        module_name = f"{providers.__name__}.{found.name}"
        if module_name in FREE_PROVIDER_MODULES:
            continue
        try:
            module = importlib.import_module(module_name)
        except ImportError:  # pragma: no cover - an optional vendor's library is missing
            continue
        for value in vars(module).values():
            if isinstance(value, type) and is_paid_vendor_class(value):
                name = getattr(value, "PROVIDER_NAME", None)
                if isinstance(name, str) and name:
                    names.add(name)
    return frozenset(names)


def _made_in(manifest: Mapping[str, Any], environment: str) -> str:
    """The environment the render was made in, as it recorded it; the studio's now if not."""
    motion = manifest.get("motion")
    record = motion if isinstance(motion, Mapping) else {}
    made = record.get("environment") or record.get("run_kind")
    return str(made or environment)


def _bought_inside(manifest: Mapping[str, Any], paid: frozenset[str]) -> list[str]:
    """The paid vendors the render itself bought stills or shots from, scene by scene; [] for
    a film assembled from its takes (it buys no still and no shot)."""
    image = manifest.get("image")
    if isinstance(image, Mapping) and image.get("provider") == TAKES_SOURCE:
        return []
    vendors: set[str] = set()
    for scene in manifest.get("scenes") or []:
        if not isinstance(scene, Mapping):
            continue
        still = scene.get("image")
        if isinstance(still, Mapping) and still.get("provider") in paid:
            if still.get("succeeded") is not False and (still.get("images") or 1):
                vendors.add(str(still["provider"]))
        shot = scene.get("motion")
        if (
            isinstance(shot, Mapping)
            and shot.get("provider") in paid
            and not shot.get("reused_take")
        ):
            vendors.add(str(shot["provider"]))
    return sorted(vendors)


#: Licence statuses a film may carry. LICENSED (every component with commercial-use evidence)
#: and PUBLIC_DOMAIN may go public; NEEDS_REVIEW passes quality control for a private upload
#: only, and the publishing gate refuses it public or unlisted. ORIGINAL_AI_GENERATED and
#: PROPRIETARY_STUDIO are the self-declared stamps written before the ledger (AR-15); they are
#: still read so older films keep their verdict.
PUBLIC_LICENCE_STATUSES = frozenset({"LICENSED", "PUBLIC_DOMAIN"})
LEGACY_LICENCE_STATUSES = frozenset({"ORIGINAL_AI_GENERATED", "PROPRIETARY_STUDIO"})
PRIVATE_ONLY_LICENCE_STATUSES = frozenset({"NEEDS_REVIEW"})


def rights_verdict(license_status: str | None, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Rights QC: what the film's licence status allows, read from its components' evidence.

    ``passed`` is whether the film may be uploaded at all (privately at least);
    ``public_allowed`` whether its components prove it may be seen. A status nobody wrote
    (or one this studio does not know) fails."""
    status = str(license_status or "")
    licences = manifest.get("licences") if isinstance(manifest.get("licences"), Mapping) else {}
    missing = [str(item) for item in (licences or {}).get("missing_ro") or []]
    known = PUBLIC_LICENCE_STATUSES | LEGACY_LICENCE_STATUSES | PRIVATE_ONLY_LICENCE_STATUSES
    passed = status in known
    public_allowed = status in PUBLIC_LICENCE_STATUSES or status in LEGACY_LICENCE_STATUSES
    if not passed:
        detail = f"Starea licenței „{status}” nu este una cunoscută; filmul nu poate fi publicat."
    elif status in PRIVATE_ONLY_LICENCE_STATUSES:
        detail = (
            "Licența filmului trebuie verificată: "
            + ("; ".join(missing) if missing else "o componentă nu are dovada folosirii comerciale")
            + ". Filmul poate fi încărcat privat, nu public sau nelistat."
        )
    elif status in LEGACY_LICENCE_STATUSES:
        detail = "Licență declarată de studio înainte de registrul pe componente."
    else:
        detail = "Fiecare componentă a filmului are dovada folosirii comerciale."
    return {
        "passed": passed,
        "public_allowed": passed and public_allowed,
        "license_status": status,
        "missing_ro": missing,
        "components": len((licences or {}).get("components") or []),
        "detail": detail,
    }


def _lu(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def audio_mix_verdict(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Audio mix QC: every music or ambience file the film carries is an entry of the Owner's
    library as it is now (same id, same sha256, commercial use confirmed), and the bed sits
    18-22 LU under the voice (`toolchain.BED_UNDER_VOICE_BAND_LU`) — measured where the voice
    speaks (``measured_lu_under_voice_in_speech``, a film mixed with a sound plan, 2026-10-11),
    else over the whole film, as the films before the plan were measured. Both readings and the
    bed's level in the voice's gaps (where a lift shows) are reported, with the plan that asked
    for them. A film without a bed passes, carrying the advisory that says why."""
    from app.media import music_library  # noqa: PLC0415 - read at call time, as tests patch it
    from app.media.toolchain import BED_UNDER_VOICE_BAND_LU  # noqa: PLC0415

    audio = manifest.get("audio") if isinstance(manifest.get("audio"), Mapping) else {}
    bed = (audio or {}).get("bed")
    tracks = ([bed] if isinstance(bed, Mapping) else []) + [
        item for item in (audio or {}).get("ambience") or [] if isinstance(item, Mapping)
    ]
    reasons: list[str] = []
    library = music_library.load_library() if tracks else None
    for track in tracks:
        name = str(track.get("track_id") or "?")
        entry = library.entry(name) if library is not None else None
        if entry is None:
            reasons.append(
                f"Piesa „{name}” din film nu este în biblioteca de muzică a Proprietarului "
                "(sau nu mai are licența confirmată)"
            )
        elif entry.sha256 != str(track.get("sha256") or ""):
            reasons.append(f"Piesa „{name}” din film nu este fișierul licențiat (sha256 diferit)")
    under: float | None = None
    in_speech: float | None = None
    in_gaps: float | None = None
    judged: str | None = None
    if isinstance(bed, Mapping):
        under = _lu(bed.get("measured_lu_under_voice"))
        in_speech = _lu(bed.get("measured_lu_under_voice_in_speech"))
        in_gaps = _lu(bed.get("measured_lu_under_voice_in_gaps"))
        low, high = BED_UNDER_VOICE_BAND_LU
        judged = "speech" if in_speech is not None else "film" if under is not None else None
        value = in_speech if in_speech is not None else under
        where = "sub cuvinte" if judged == "speech" else "pe tot filmul"
        if value is None:
            reasons.append("Nivelul muzicii sub voce nu a fost măsurat")
        elif value < low - 0.5:
            reasons.append(
                f"Muzica stă la {value:.1f} LU sub voce ({where}), nu la {low:.0f}-{high:.0f} LU: "
                "vocea trebuie să conducă"
            )
        elif value > high + 0.5:
            reasons.append(
                f"Muzica stă la {value:.1f} LU sub voce ({where}), nu la {low:.0f}-{high:.0f} LU: "
                "fundalul abia se mai aude"
            )
    plan = (audio or {}).get("plan") if isinstance((audio or {}).get("plan"), Mapping) else None
    replans = (audio or {}).get("replans")
    return {
        "passed": not reasons,
        "bed": (bed or {}).get("track_id") if isinstance(bed, Mapping) else None,
        "ambience": [str(track.get("track_id")) for track in tracks[1 if bed else 0 :]],
        "lu_under_voice": under,
        "lu_under_voice_in_speech": in_speech,
        "lu_under_voice_in_gaps": in_gaps,
        "judged": judged,
        "plan": (
            {
                "source": plan.get("source"),
                "by": plan.get("by"),
                "bed": plan.get("bed"),
                "levels": plan.get("levels"),
                "lifted_seconds": (bed or {}).get("lifted_seconds")
                if isinstance(bed, Mapping)
                else None,
                "summary_ro": plan.get("summary_ro"),
            }
            if plan is not None
            else None
        ),
        "replans": len(replans) if isinstance(replans, list) else 0,
        "attributions": list((audio or {}).get("attributions") or []),
        "advisory": (audio or {}).get("advisory"),
        "reasons_ro": reasons,
    }


def production_path_verdict(
    engine: Engine,
    session: Session,
    render_job: VideoRenderJob | None,
    manifest: Mapping[str, Any],
    scenes: list[StoryboardScene],
    *,
    environment: str,
) -> dict[str, Any]:
    """Whether the film was made the way a film may be made since the staircase.

    Two refusals, each with its Romanian reason. (1) In PRODUCTION, filmed scenes whose prompt
    no model wrote (template prompts are a TEST convenience; the office serial's scenes may
    come from the Owner's series look). (2) In any environment, stills or shots the whole-film
    path bought from a paid vendor inside the render, rather than takes bought on the sheet.
    Both apply to renders started from `STAIRCASE_CUTOVER` on; nothing is fetched or bought.
    """
    from app.media.assembler import shot_plan_sources  # noqa: PLC0415 - assembler reads qc

    started = str(render_job.started_at or "") if render_job is not None else ""
    judged = render_job is not None and started >= STAIRCASE_CUTOVER
    made_in = _made_in(manifest, environment)
    template_scenes: list[int] = []
    if judged and render_job is not None and made_in == "PRODUCTION" and scenes:
        sources = shot_plan_sources(engine, render_job.storyboard_id)
        template_scenes = [
            int(scene.scene_index)
            for scene in scenes
            if str(getattr(scene, "scene_kind", None) or "LIVE").upper() not in COMPOSED_KINDS
            and (scene.prompt_json or {}).get("source") not in sources
        ]
    vendors = _bought_inside(manifest, paid_vendor_names()) if judged else []
    reasons: list[str] = []
    if template_scenes:
        listed = ", ".join(map(str, template_scenes))
        reasons.append(
            ("Scena " if len(template_scenes) == 1 else "Scenele ")
            + listed
            + (" a fost filmată" if len(template_scenes) == 1 else " au fost filmate")
            + " din prompturi-șablon, nu din planul de cadre scris de model: în PRODUCTION "
            "un astfel de film nu se publică."
        )
    if vendors:
        reasons.append(
            "Filmul a fost cumpărat întreg pe calea veche de randare, de la "
            + ", ".join(vendors)
            + ", nu pas cu pas pe foaia de filmare, cu aprobarea legată de plan: nu se publică."
        )
    return {
        "passed": not reasons,
        "made_in": made_in,
        "judged": judged,
        "template_scenes": template_scenes,
        "legacy_paid": bool(vendors),
        "paid_vendors": vendors,
        "reasons_ro": reasons,
    }


#: The shortest film YouTube treats as a Short worth publishing here.
SHORTS_MIN_SECONDS = 10.0
#: What a measured length may run past the channel's maximum: the container's own rounding
#: and the last breath after the final word, never a second scene. Never past YouTube's own
#: limit (`shorts_length_ceiling`): with the channels at 180 since 2026-10-16 the slack would
#: have moved the wall itself, and a 180.9 s film is not a Short.
SHORTS_LENGTH_SLACK_SECONDS = 1.0
#: The longest a channel may set: YouTube's own limit for vertical Shorts since 2024-10-15.
SHORTS_MAX_LIMIT_SECONDS = 180
#: Per channel type, when the film's channel row carries no value of its own.
SHORTS_MAX_BY_CHANNEL_TYPE = {"MAIN_FACTUAL": 180, "OFFICE_SERIAL": 180}


def shorts_length_ceiling(max_seconds: float) -> float:
    """The longest measured film quality control accepts on a channel that takes
    ``max_seconds``: the channel's maximum plus SHORTS_LENGTH_SLACK_SECONDS, never past
    SHORTS_MAX_LIMIT_SECONDS (the Owner, 2026-10-16: «maxim 180»)."""
    return min(float(max_seconds) + SHORTS_LENGTH_SLACK_SECONDS, float(SHORTS_MAX_LIMIT_SECONDS))


def shorts_max_seconds(session: Session, media_asset_id: str) -> int:
    """The longest film the film's channel takes: its ``shorts_max_seconds`` (migration 0053,
    the Owner's policy), else its type's default (60 s factual, 70 s serial)."""
    from app.publishing.models import ChannelRecord  # noqa: PLC0415
    from app.publishing.services import channel_type_for_storyboard  # noqa: PLC0415

    job = session.scalars(
        select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
    ).first()
    board = session.get(Storyboard, job.storyboard_id) if job and job.storyboard_id else None
    kind = channel_type_for_storyboard(board) if board is not None else "MAIN_FACTUAL"
    channel = session.get(ChannelRecord, board.channel_id) if board and board.channel_id else None
    if channel is None:
        channel = session.scalars(
            select(ChannelRecord)
            .where(ChannelRecord.channel_type == kind)
            .order_by(ChannelRecord.created_at)
        ).first()
    if channel is not None:
        kind = channel.channel_type
    stated = getattr(channel, "shorts_max_seconds", None)
    value = int(stated) if stated else SHORTS_MAX_BY_CHANNEL_TYPE.get(kind, 60)
    return max(int(SHORTS_MIN_SECONDS), min(value, SHORTS_MAX_LIMIT_SECONDS))


def evaluate_media_qc(
    engine: Engine,
    media_asset_id: str,
    correlation_id: str,
    settings: Any | None = None,
    *,
    registry: Any | None = None,
    ffmpeg_path: str | None = None,
    span_judge: Callable[[list[Path], Any], Any] | None = None,
    face_counter: Callable[..., Any] | None = None,
) -> dict:
    """Run comprehensive Quality Control check on a rendered media asset.

    ``settings`` is the studio's configuration, read for ``max_fallback_scenes``: how many
    scenes of a production film may be stills pushed slowly because the motion model
    refused. Unset, half the scenes.

    ``registry`` and ``ffmpeg_path`` are what it takes to look at the pictures rather than
    only at the file: a provider that holds a model the provider says can see, and the
    encoder that cuts one frame per scene. Without either, the picture and character checks
    report NOT_APPLICABLE with the reason and the film's verdict is unchanged — never a
    pass by absence. The span check reads the flat band on each filmed scene's frames even
    with no registry (`span_picture_qc`): a scene made of panels fails the film whoever
    looks.

    ``span_judge`` and ``face_counter`` replace the per-scene look of `span_picture_qc` (the
    judge bound to ``registry`` and YuNet) for a test; nothing else passes them.
    """
    qc_id = str(uuid4())
    verified_at = utc_now()
    checks: dict[str, dict] = {}
    failure_reasons: list[str] = []
    # Read before the report's own transaction opens: the environment is the studio's state,
    # never a parameter, and it decides whether a mostly-still film is a failure or a note.
    environment = studio_environment(engine)
    # And so is the look at the pictures: it is a model run, which writes its own rows and
    # reads the day's token ceiling outside a transaction (`run_agent_task`). Two writers on
    # one SQLite connection are a lock, not a gate.
    pictures = evaluate_pictures(
        engine, registry, media_asset_id, correlation_id, ffmpeg_path=ffmpeg_path
    )
    # The same, scene by scene: three frames of each filmed scene's span at 1080 px. One
    # vision call per scene, so it runs here too, outside the report's transaction.
    spans_look = span_picture_qc(
        engine,
        registry,
        media_asset_id,
        correlation_id,
        ffmpeg_path=ffmpeg_path,
        judge=span_judge,
        face_counter=face_counter,
    )

    # Read and measured under a read session only. The measuring takes seconds (ffprobe, the
    # loudness pass, duplicate frames), and a transaction that read and then wrote was refused
    # «database is locked» whenever anything committed meanwhile (2026-10-02/03: edit_and_qc
    # failed in four runs, each after three retries; the Owner's own QC press at 05:39 too).
    # The verdict is written below in a short transaction that takes the write lock first.
    with Session(engine) as session:
        asset = session.get(MediaAsset, media_asset_id)
        if not asset:
            raise ValueError(f"Media asset {media_asset_id} not found")

        # 1. Technical QC — measured from the file itself, never from the database row that
        #    the renderer wrote. Trusting our own metadata would make this gate circular.
        file_path = Path(asset.uri_or_path)
        file_exists = file_path.is_file()
        file_bytes = file_path.read_bytes() if file_exists else b""
        file_size = len(file_bytes)

        probe: dict[str, Any] = (
            probe_media_file(file_path)
            if file_exists
            else {"available": False, "ok": False, "error": "file missing"}
        )

        if not file_exists:
            failure_reasons.append("Rendered video file missing on disk")
        elif not probe["available"]:
            failure_reasons.append("ffprobe is not installed: technical QC cannot be verified")
        elif not probe["ok"]:
            failure_reasons.append(f"File is not a decodable video: {probe.get('error')}")

        measured_w = probe.get("width") or 0
        measured_h = probe.get("height") or 0
        measured_dur = probe.get("duration_seconds") or 0.0
        is_9_16 = (
            measured_w > 0 and measured_h > 0 and abs((measured_w / measured_h) - (9 / 16)) < 0.01
        )
        # The Shorts bounds: 10 s at least, at most what the film's channel takes (audit
        # PUB-15: 60 s for factual films, 70 s for the serial, up to YouTube's 180 s).
        max_dur = shorts_max_seconds(session, asset.id)
        dur_valid = SHORTS_MIN_SECONDS <= measured_dur <= shorts_length_ceiling(max_dur)

        if probe.get("ok"):
            if not is_9_16:
                failure_reasons.append(
                    f"Measured aspect ratio {measured_w}x{measured_h} is not 9:16"
                )
            if not dur_valid:
                failure_reasons.append(
                    f"Durata măsurată, {measured_dur:.1f} s, iese din limitele unui Short pe "
                    f"acest canal ({SHORTS_MIN_SECONDS:.0f}-{max_dur} s)"
                )

        # Provenance must be verifiable, not merely present: recompute the digest.
        actual_hash = hashlib.sha256(file_bytes).hexdigest() if file_exists else None
        provenance_ok = bool(asset.provenance_hash) and actual_hash == asset.provenance_hash
        if not provenance_ok:
            failure_reasons.append("Provenance digest missing or does not match the file on disk")

        # Declared vs measured mismatch is itself a defect worth surfacing.
        declared_mismatch = probe.get("ok") and (
            asset.width != measured_w or asset.height != measured_h
        )
        if declared_mismatch:
            failure_reasons.append(
                f"Declared resolution {asset.width}x{asset.height} does not match measured "
                f"{measured_w}x{measured_h}"
            )

        tech_passed = bool(
            file_exists
            and file_size > 0
            and probe.get("ok")
            and is_9_16
            and dur_valid
            and provenance_ok
            and not declared_mismatch
        )

        checks["technical_qc"] = {
            "passed": tech_passed,
            "measured_width": measured_w,
            "measured_height": measured_h,
            "measured_duration_seconds": measured_dur,
            "max_duration_seconds": max_dur,
            "duration_valid": dur_valid,
            "video_codec": probe.get("video_codec"),
            "has_audio_stream": probe.get("has_audio"),
            "declared_width": asset.width,
            "declared_height": asset.height,
            "file_size_bytes": file_size,
            "provenance_hash_verified": provenance_ok,
            "provenance_sha256": asset.provenance_hash,
            "probe_error": probe.get("error"),
        }

        # 2. Rights / Licensing QC
        #    Read from the components' evidence once the render's record is open (below).

        # 2b. Content source QC — placeholder frames are not publishable footage.
        is_placeholder = (
            str(asset.provider_name or "").upper().startswith(PLACEHOLDER_PROVIDER_PREFIX)
        )
        if is_placeholder:
            failure_reasons.append(
                "Visuals are locally generated placeholder frames, not real footage; configure a "
                "visual generation provider before publishing"
            )
        checks["content_source_qc"] = {
            "passed": not is_placeholder,
            "provider_name": asset.provider_name,
            "detail": (
                "PLACEHOLDER visuals are blocked from publication."
                if is_placeholder
                else "Visual source accepted."
            ),
        }

        # 3. Factual Claims QC
        # Find storyboard from render job
        render_job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
        )
        manifest: dict[str, Any] = (
            render_job.production_json
            if render_job is not None and isinstance(render_job.production_json, dict)
            else {}
        )
        # 2. (continued) Rights: what the film's components prove (AR-15). NEEDS_REVIEW passes
        #    for a private upload; the publishing gate keeps it from being seen.
        rights = rights_verdict(asset.license_status, manifest)
        rights_passed = bool(rights["passed"])
        if not rights_passed:
            failure_reasons.append(f"Invalid license status: {asset.license_status}")
        checks["rights_qc"] = {**rights, "provider_name": asset.provider_name}
        # 2a. The bed and the ambience: every file in the Owner's library as licensed, the
        #     bed 18-22 LU under the voice.
        mix_check = audio_mix_verdict(manifest)
        failure_reasons.extend(mix_check["reasons_ro"])
        checks["audio_mix_qc"] = mix_check
        storyboard_scenes: list[StoryboardScene] = []
        if render_job is not None:
            sb = session.get(Storyboard, render_job.storyboard_id)
            if sb is not None:
                storyboard_scenes = list(
                    session.scalars(
                        select(StoryboardScene)
                        .where(StoryboardScene.storyboard_id == sb.id)
                        .order_by(StoryboardScene.scene_index)
                    ).all()
                )

        # 1b. The delivered file against the encoder's own spec: the format in every
        #     environment, the delivery floors (bitrate, length against the narration,
        #     duplicated frames on the scenes that move) in PRODUCTION. Read from the file;
        #     the manifest supplies only what the file cannot say: the timeline's fps, the
        #     narration's length and where the moving scenes sit.
        ffmpeg = find_ffmpeg()
        recorded_timeline = manifest.get("timeline")
        timeline: dict[str, Any] = recorded_timeline if isinstance(recorded_timeline, dict) else {}
        timeline_fps = float(timeline.get("fps") or manifest.get("fps") or DEFAULT_TIMELINE_FPS)
        narration_seconds = narration_seconds_of(manifest)
        planned = {sc.scene_index: float(sc.duration_seconds or 0.0) for sc in storyboard_scenes}
        spans = moving_spans(manifest, planned)
        # What the film may last beyond its words: the breath the timeline plans after each
        # scene's words, and the silent cards up to their own maximum (film_length_budget).
        budget = film_length_budget(manifest, planned)
        # Counted on the lossless shots when the render kept them; the lossy film only for
        # renders that did not (a slow clip reads like a repeated frame after CRF 17).
        duplicates = shot_duplicate_share(ffmpeg, manifest, file_path.parent, spans)
        if duplicates is None and spans and probe.get("ok"):
            duplicates = duplicate_share(measure_motion(ffmpeg, file_path), spans)
        delivery_failures: list[str] = []
        delivery_warnings: list[str] = []
        if probe.get("ok"):
            delivery_failures, delivery_warnings = technical_problems(
                probe,
                environment=environment,
                timeline_fps=timeline_fps,
                narration_seconds=narration_seconds,
                duplicate_share=duplicates,
                budget=budget,
            )
            failure_reasons.extend(delivery_failures)
            tech_passed = tech_passed and not delivery_failures
        checks["technical_qc"].update(
            {
                "passed": tech_passed,
                "video_profile": probe.get("video_profile"),
                "pix_fmt": probe.get("pix_fmt"),
                "color_range": probe.get("color_range"),
                "color_space": probe.get("color_space"),
                "color_primaries": probe.get("color_primaries"),
                "color_transfer": probe.get("color_transfer"),
                "video_fps": probe.get("video_fps"),
                "timeline_fps": timeline_fps,
                "video_bit_rate": probe.get("video_bit_rate"),
                "narration_seconds": (
                    round(narration_seconds, 3) if narration_seconds is not None else None
                ),
                "moving_spans": [list(span) for span in spans],
                "length_budget": budget,
                "duplicate_share": round(duplicates, 4) if duplicates is not None else None,
                "environment": environment,
                "failures": delivery_failures,
                "warnings": delivery_warnings,
            }
        )

        # 2c. Audio QC — the film is measured with the same filter that normalised it, so
        #     the renderer and this gate can never disagree. Behind the same guard as the
        #     rest of technical QC: no encoder, no measurement, no certificate. The reading
        #     is the delivered file's, after its AAC encode, never the manifest's.
        audio: dict[str, Any] = {
            "passed": False,
            "integrated_lufs": None,
            "true_peak_dbtp": None,
            "band_lufs": list(QC_LOUDNESS_BAND_LUFS),
            "true_peak_ceiling_dbtp": TRUE_PEAK_CEILING_DBTP,
            "measured_on": "delivered_file",
            "normalised": (manifest.get("audio") or {}).get("loudness", {}).get("applied"),
            "error": None,
        }
        if not file_exists or not probe.get("ok"):
            audio["error"] = "no decodable film to measure"
        elif not ffmpeg or not has_filter(ffmpeg, "loudnorm"):
            audio["error"] = "ffmpeg with loudnorm is not installed: loudness cannot be verified"
            failure_reasons.append(audio["error"])
        elif not probe.get("has_audio"):
            audio["error"] = "the film has no audio stream"
            failure_reasons.append("The film has no audio stream")
        else:
            reading = measure_loudness(ffmpeg, file_path)
            if reading is None:
                audio["error"] = "loudness could not be measured"
                failure_reasons.append("Loudness could not be measured from the film")
            else:
                integrated = float(reading["integrated_lufs"])
                peak = float(reading["true_peak_dbtp"])
                low, high = QC_LOUDNESS_BAND_LUFS
                audio["integrated_lufs"] = round(integrated, 2) if integrated > -1e9 else None
                audio["true_peak_dbtp"] = round(peak, 2) if peak > -1e9 else None
                in_band = low <= integrated <= high
                under_ceiling = peak <= TRUE_PEAK_CEILING_DBTP
                if not in_band:
                    failure_reasons.append(
                        f"Measured loudness {integrated:.1f} LUFS is outside {low:.0f}..{high:.0f}"
                        " LUFS"
                    )
                if not under_ceiling:
                    failure_reasons.append(
                        f"Measured true peak {peak:.1f} dBTP is over the "
                        f"{TRUE_PEAK_CEILING_DBTP:.0f} dBTP ceiling"
                    )
                audio["passed"] = in_band and under_ceiling
        checks["audio_qc"] = audio

        # 2d. Captions QC — the SRT beside the film is read back: it parses, keeps to two
        #     lines of forty-two, sits inside the film, and says what the narration says.
        # Read once and narrowed once: `manifest.get(...)` is `Any | None` to the checker,
        # and the old "if isinstance(manifest.get(...))" left the None in the union.
        recorded_captions = manifest.get("captions")
        captions_record: dict[str, Any] = (
            recorded_captions if isinstance(recorded_captions, dict) else {}
        )
        srt_path = Path(str(captions_record.get("srt") or (file_path.parent / "captions.srt")))
        narration = " ".join(str(sc.voiceover_segment or "") for sc in storyboard_scenes)
        captions: dict[str, Any] = {
            "passed": False,
            "srt": str(srt_path),
            "cues": 0,
            "burned_in": captions_record.get("burned_in"),
            "covers_narration": None,
            "coverage_ratio": None,
            "problems": [],
        }
        read_cues: list[dict[str, Any]] = []
        if not srt_path.is_file():
            captions["problems"] = ["no captions file beside the film"]
            failure_reasons.append("Captions are missing: no SRT beside the film")
        else:
            try:
                cues = parse_srt(srt_path.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                captions["problems"] = [f"captions do not parse: {str(exc)[:120]}"]
                failure_reasons.append(f"Captions do not parse as SRT: {str(exc)[:120]}")
            else:
                read_cues = cues
                problems = caption_problems(cues)
                captions["cues"] = len(cues)
                if cues and measured_dur and cues[-1]["end"] > measured_dur + 0.5:
                    problems.append(
                        f"the last cue ends at {cues[-1]['end']:.1f}s, after the film "
                        f"({measured_dur:.1f}s)"
                    )
                spoken = _words(narration)
                captioned = _words(" ".join(" ".join(c["lines"]) for c in cues))
                if spoken:
                    ratio = difflib.SequenceMatcher(None, spoken, captioned).ratio()
                    covers = ratio >= CAPTION_COVERAGE_RATIO
                else:
                    ratio, covers = 1.0, not captioned
                captions["coverage_ratio"] = round(ratio, 3)
                captions["covers_narration"] = covers
                if not covers:
                    problems.append(
                        f"captions carry {ratio:.0%} of the narration's words, "
                        f"under {CAPTION_COVERAGE_RATIO:.0%}"
                    )
                captions["problems"] = problems
                captions["passed"] = not problems
                for problem in problems:
                    failure_reasons.append(f"Captions: {problem}")
        checks["captions_qc"] = captions

        # 2d'. Editorial QC (audit Q10): the editing a viewer feels, measured on the delivered
        #      file and the voice track beside it. Advisory unless the Owner made it blocking;
        #      a check that could not measure (no encoder) stands down (passed None).
        editorial = editorial_problems(
            file_path,
            manifest,
            ffmpeg=ffmpeg if file_exists and probe.get("ok") else None,
            cues=read_cues,
            blocking=editorial_blocking(settings),
            settings=settings,
        )
        if editorial["passed"] is False:
            failure_reasons.extend(f"Montaj: {reason}" for reason in editorial["reasons_ro"])
        checks["editorial_qc"] = editorial

        # 2e. Motion QC — which LIVE scenes the film shows as a still. In PRODUCTION none may
        #     be, unless the Owner chose a locally animated still for that scene on the
        #     sheet, or the Director moved it locally past his renders cap (no clip of it can
        #     carry it): the old ceiling of half the scenes let the Nepal film's two stills
        #     through. The two are recorded apart: his choices are his alone. In TEST two
        #     motion scenes are the policy and the rest push by design, so the old ceiling
        #     only warns there. Cards are composed, never filmed.
        owner_choices: set[int] = set()
        cap_choices: set[int] = set()
        if render_job is not None:
            owner_choices = owner_local_moves(session, render_job.storyboard_id)
            cap_choices = cap_local_moves_of(session, render_job.storyboard_id)
        if not manifest.get("motion") and not manifest.get("scenes"):
            manifest_for_motion: dict[str, Any] = {"motion": {"scenes": len(storyboard_scenes)}}
        else:
            manifest_for_motion = manifest
        motion = fallback_verdict(
            manifest_for_motion,
            environment=environment,
            owner_choices=owner_choices,
            cap_choices=cap_choices,
            settings=settings,
        )
        if not motion["passed"]:
            failure_reasons.append(f"Motion QC: {motion['reason_ro']}")
        checks["motion_qc"] = motion

        # 2f. Production path — how the film was made, not only what the file measures. The
        #     second Nepal render was bought whole by the legacy path from template prompts and
        #     sat in the queue with no verdict (A12); it fails here, as would any like it.
        path_check = production_path_verdict(
            engine,
            session,
            render_job,
            manifest,
            storyboard_scenes,
            environment=environment,
        )
        failure_reasons.extend(path_check["reasons_ro"])
        checks["production_path_qc"] = path_check

        factual_passed = True
        claims_checked = []

        if render_job:
            sb = session.get(Storyboard, render_job.storyboard_id)
            if sb:
                scenes = storyboard_scenes
                all_claim_ids = set()
                for sc in scenes:
                    for cid in sc.claim_ids_json or []:
                        all_claim_ids.add(cid)

                for cid in all_claim_ids:
                    claim = session.get(FactualClaim, cid)
                    if claim:
                        claims_checked.append({"id": cid, "status": claim.status})
                        if claim.status != "SUPPORTED":
                            factual_passed = False
                            failure_reasons.append(
                                f"Claim '{claim.claim_text[:40]}' is {claim.status}, not SUPPORTED"
                            )
                    else:
                        factual_passed = False
                        failure_reasons.append(f"Claim ID {cid} missing from database")

        checks["factual_qc"] = {
            "passed": factual_passed,
            "total_claims_checked": len(claims_checked),
            "claims": claims_checked,
        }

        # 4. Picture QC and Character Drift QC — measured above, before this transaction.
        #    A film whose third scene is a blank field fails here, in every environment, for
        #    the same reason the degenerate-still check fails one: nothing in TEST policy
        #    deliberately produces a picture of nothing. Where the look could not happen the
        #    check says so with `passed` None and adds no failure, so the verdict is what it
        #    would have been (50_CONTENT_GATE_MATRIX.md gate behaviour).
        checks["picture_qc"] = pictures["picture_qc"]
        checks["character_drift_qc"] = pictures["character_drift_qc"]
        failure_reasons.extend(pictures["failures"])
        # 4b. The same look, scene by scene, on three frames of each filmed scene at 1080 px.
        #     A refusal or a face fails the film in every environment, as picture_qc does; a
        #     face count that could not run when the bible forbids faces fails in PRODUCTION
        #     (clip QC's rule); a look that did not happen certifies nothing (passed None).
        checks["picture_spans_qc"] = {
            key: value for key, value in spans_look.items() if key != "failures"
        }
        failure_reasons.extend(spans_look["failures"])

        # 3b. Content integrity — a still the generator returned as stripes or an empty field,
        #     measured when it was made and still broken after one more attempt. A technically
        #     perfect file of nothing is not a film.
        degenerate: list[dict] = [
            item for item in manifest.get("degenerate_stills") or [] if isinstance(item, dict)
        ]
        for item in degenerate:
            failure_reasons.append(f"Scene {item.get('scene_index')}: {item.get('reason')}")
        checks["content_integrity_qc"] = {
            "passed": not degenerate,
            "degenerate_stills": degenerate,
        }

        # Overall Status
        overall_passed = (
            tech_passed
            and rights_passed
            and factual_passed
            and not is_placeholder
            and not degenerate
            and bool(audio["passed"])
            and bool(mix_check["passed"])
            and bool(captions["passed"])
            and bool(motion["passed"])
            and bool(path_check["passed"])
            and editorial["passed"] is not False
            # Only a measured refusal counts against the film; a check that stood down
            # (None) leaves the verdict exactly where the other gates left it.
            and pictures["picture_qc"]["passed"] is not False
            and pictures["character_drift_qc"]["passed"] is not False
            and spans_look["passed"] is not False
        )
        status = "PASSED" if overall_passed else "FAILED"
        score = 1.0 if overall_passed else round(max(0.0, 1.0 - (len(failure_reasons) * 0.25)), 2)

    with Session(engine) as session, session.begin():
        lock_for_write(session)
        event = append_event(
            session,
            "media.qc_evaluated",
            "quality_control_report",
            qc_id,
            1,
            {
                "media_asset_id": media_asset_id,
                "status": status,
                "score": score,
                "failures": failure_reasons,
            },
            correlation_id,
        )

        report = QualityControlReport(
            id=qc_id,
            media_asset_id=media_asset_id,
            status=status,
            score=score,
            checks_json=checks,
            failure_reasons_json=failure_reasons,
            verified_at=verified_at,
            event_id=event.event_id,
        )
        session.add(report)
        session.flush()

        # The result is the Video Editor's own history, whatever produced the render.
        editor = agent_for_role(session, "VideoEditor")
        if editor is not None:
            remember(
                session,
                memory_class="HISTORICAL_EVENT",
                content=(
                    f"Render {media_asset_id[:8]} {status} quality control"
                    + (": " + "; ".join(failure_reasons)[:400] if failure_reasons else ".")
                ),
                source_type="event",
                source_id=qc_id,
                event_id=event.event_id,
                agent_id=editor.id,
            )

        return QCReportView.model_validate(report).model_dump()


def get_media_qc(engine: Engine, media_asset_id: str) -> dict | None:
    with Session(engine) as session:
        rep = session.scalar(
            select(QualityControlReport)
            .where(QualityControlReport.media_asset_id == media_asset_id)
            .order_by(QualityControlReport.verified_at.desc())
        )
        return QCReportView.model_validate(rep).model_dump() if rep else None


# ================================================================== clip QC, before assembly
#
# A bought clip is measured before it is cut into the film, so a clip that does not move, a
# clip with a cut inside it or a clip where a face turned toward the camera is redone alone,
# once, inside the cap the Owner approved, instead of being found by the film's QC after the
# whole film was paid for.
#
# The motion metric is one fixed measurement: the mean signalstats YDIF (the mean absolute
# luma difference between consecutive frames, 0..255) at 540 px width. Measured on the four
# Nepal clips on disk it reads 1.0-3.2, and a flat 1.0 floor would pass all four, including
# the two that barely move. So the floor is not a number written down here: it is calibrated
# per clip and per camera move, from a local ffmpeg fixture built from the clip's own first
# frame (a push-in of 3% over 5 s, or a pan of 5% of the width) measured the same way. The
# clip must move at least half as much as that fixture. 'static' has no floor. The
# multi-frame vision checklist and the Owner's look at the hero test shot are the other two
# guards; none of the three is trusted alone.

#: The width every clip and fixture is measured at.
CLIP_METRIC_WIDTH = 540
#: The fixtures' length and moves: a push-in of 3% over 5 s, a pan across 5% of the width.
FIXTURE_SECONDS = 5.0
PUSH_IN_ZOOM = 0.03
PAN_FRACTION = 0.05
#: The share of the fixture's motion a clip must reach.
FLOOR_SHARE = 0.5
#: The fixture each camera move is held to (one entry per key of prompt_lint.CAMERA_MOVES).
#: Moves that change the scale of the picture are held to the push-in; moves that slide it,
#: to the pan. 'static' has no floor. The moves of «Mișcare v2» (2026-10-11): a dolly in or
#: out changes the scale (push_in); a tracking move, a crane and a handheld drift slide the
#: frame (pan). A rack focus moves neither — it changes the blur — and no fixture here
#: measures a focus pull, so it has no floor either: its clip is judged by the picture
#: checks (`_picture_check` reads same_shot and matches_plan), and the compiler never
#: chooses it unasked (`prompt_agent.SIZE_MOVES`). The floor stays a minimum: an ample move
#: is never refused for moving too much; a deformation is the picture checks' finding.
MOVE_FIXTURE: dict[str, str | None] = {
    "static": None,
    "slow push-in": "push_in",
    "slow pull-back": "push_in",
    "dolly in": "push_in",
    "dolly out": "push_in",
    "aerial drift forward": "push_in",
    "slow pan left": "pan",
    "slow pan right": "pan",
    "tracking left": "pan",
    "tracking right": "pan",
    "tilt up": "pan",
    "tilt down": "pan",
    "pedestal up": "pan",
    "crane up": "pan",
    "crane down": "pan",
    "slow orbit": "pan",
    "handheld drift": "pan",
    "rack focus": None,
}
#: A hard cut inside a clip is one frame that differs from the one before it far more than
#: the clip's own motion: above eight times the clip's median YDIF and above 12 in absolute
#: terms. Measured: cuts between two Nepal stills read 44-66; the busiest Nepal clip's
#: largest frame-to-frame change is 4.9.
CUT_SPIKE_RATIO = 8.0
CUT_SPIKE_MIN_YDIF = 12.0
# A failing clip's retries (on the same model, with seed + 1, inside the approved cap) are
# read when it is decided: one, while the Owner's renders cap leaves a second render of the
# motion, none at a cap of one (`renders_cap.clip_retries`, `Settings.renders_per_layer`).

#: A frame whose YDIF is under this repeats the one before it. Measured: a 24 fps Nepal clip
#: converted to 30 fps has exactly 20% such frames; the clips as delivered, none (their
#: slowest frame reads 0.12).
DUPLICATE_YDIF = 0.05
#: Read on the shot intermediates, which the final encode has not touched. Since 2026-10-01
#: they are x264 High at CRF 4 (assembler.INTERMEDIATE_VIDEO_ARGS), no longer lossless.
#: Measured on such shots: a repeated frame reads at most 0.013 (the Nepal motion_04 at 12 fps
#: with a held end; a grained 12 fps clip, 0.003), where lossless it read exactly 0; the
#: slowest real Nepal clip reads 0.097 (0.104 lossless), a faint-grain still 0.13. The line
#: sits between them, with room on both sides. The lossy film cannot separate them: after
#: CRF 17 the same slow clip reads under 0.05 on real frames.
LOSSLESS_DUPLICATE_YDIF = 0.03

#: The delivered film's technical floor: the encoder's own spec (final_video_args).
DELIVERY_SIZE = (1080, 1920)
DELIVERY_PROFILE = "High"
DELIVERY_PIX_FMT = "yuv420p"
DELIVERY_RANGE = "tv"
DELIVERY_COLOUR = "bt709"
#: The timeline's frame rate when the render does not record one. TIMELINE_24_CAPTIONS moves
#: the timeline to the vendor's native 24 fps and records it in production['timeline'].
DEFAULT_TIMELINE_FPS = 30.0
#: Average video bitrate: under 6 Mbps fails, under 8 warns (a card-heavy film compresses
#: small and can be right at 7).
MIN_VIDEO_BITRATE = 6_000_000
WARN_VIDEO_BITRATE = 8_000_000
#: How much longer than its narration, its planned breaths and its silent cards a film may
#: run (film_length_budget).
DURATION_OVER_NARRATION_SECONDS = 1.0
#: The breath the timeline plans after each scene's words: the assembler's
#: LEGACY_SPOKEN_TAIL_SECONDS, read from production['timeline']['spoken_tail_seconds'] when
#: the render recorded it. The film used to be held within narration + 1.0 s, so the
#: timeline shrank every breath to keep under 0.9 s: six speaking scenes kept about 0.11 s
#: each and every cut felt rushed. A breath the writer planned is part of the film, not film
#: over the narration. This is the fallback for a render that did not record its breath;
#: renders since 2026-10-02 record 0.12 s, taken after the vendor's silence was trimmed from
#: each take, and that recorded value is what counts (the narration they record is the
#: trimmed words, so nothing is counted twice). A film timed by its frozen pauses (2026-10-16)
#: records each scene's own pad instead (`_recorded_pads`).
BREATH_SECONDS = 0.35
#: The scenes the studio composes itself: never filmed, never sent to a model.
COMPOSED_KINDS = ("DATA_CARD", "TITLE_CARD", "BLACK")
#: A scene whose recorded words are shorter than this says nothing.
SILENT_SPOKEN_SECONDS = 0.05
#: How long a composed card may stay silent, from what the writer's spec asks of each kind
#: (agent_pipeline._WRITE_INSTRUCTIONS). BLACK is "a silence or the closing call to action":
#: one beat, 2 s; a short plays in a loop, and more black than that reads as a broken file and
#: the viewer swipes. A silent TITLE_CARD must be read: its 0.25 s fade-in, about 2 s for a
#: title of a few words, and the card's 0.3 s hold, 2.5 s. A silent DATA_CARD must finish its
#: animation: four bars (MAX_BARS) grow in 0.3 + 3 x 0.6 + 1.0 s, their values fade in over
#: 0.1 + 0.25 s and the card holds 0.3 s, 3.75 s in all, inside 4 s. Silence beyond these is
#: film over the narration and fails as such, naming the scene.
MAX_SILENT_CARD_SECONDS: dict[str, float] = {"BLACK": 2.0, "TITLE_CARD": 2.5, "DATA_CARD": 4.0}
_CARD_WORDS_RO = {"BLACK": "ecran negru", "TITLE_CARD": "titlu", "DATA_CARD": "grafic"}
#: Duplicated frames tolerated on the spans of LIVE scenes that move.
MAX_DUPLICATE_SHARE = 0.02
#: How far from each span's edges duplicates are counted: a dissolve is not a duplicate.
SPAN_EDGE_SECONDS = 0.5
#: Integrated loudness of the delivered file: -14 +/- 1 LUFS.
QC_LOUDNESS_BAND_LUFS = (LOUDNESS_TARGET_LUFS - 1.0, LOUDNESS_TARGET_LUFS + 1.0)


def _ro_number(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _ffmpeg_run(args: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(  # noqa: S603 - argument list, no shell
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None


@dataclass(frozen=True)
class MotionReading:
    """Per-frame YDIF of one clip at `width`, and their mean and median over every frame but
    the first (which has nothing before it)."""

    values: list[float]
    times: list[float]
    mean: float
    width: int
    fps: float | None
    median: float = 0.0


def measure_motion(
    ffmpeg: str | None, clip: Path | str, width: int = CLIP_METRIC_WIDTH
) -> MotionReading | None:
    """The clip's per-frame YDIF at `width` px, or None when it cannot be measured."""
    if not ffmpeg or not Path(clip).is_file():
        return None
    result = _ffmpeg_run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-threads",
            "2",
            "-i",
            str(clip),
            "-an",
            "-vf",
            # format=yuv420p: YDIF in 8-bit units for every clip. signalstats reports it in
            # the source's own depth, so a 10-bit vendor clip read four times its motion.
            f"scale={width}:-2:flags=bilinear,format=yuv420p,signalstats,"
            "metadata=print:key=lavfi.signalstats.YDIF:file=-",
            "-f",
            "null",
            "-",
        ]
    )
    if result is None or result.returncode != 0:
        return None
    values: list[float] = []
    times: list[float] = []
    current: float | None = None
    for line in (result.stdout or "").splitlines():
        stamp = re.search(r"pts_time:\s*([-0-9.]+)", line)
        if stamp:
            current = float(stamp.group(1))
            continue
        value = re.search(r"lavfi\.signalstats\.YDIF=([0-9.]+)", line)
        if value:
            values.append(float(value.group(1)))
            times.append(current if current is not None else 0.0)
    if len(values) < 2:
        return None
    probe = probe_media_file(Path(clip), ffmpeg)
    fps = probe.get("video_fps")
    if not fps and times[-1] > times[0]:
        fps = (len(times) - 1) / (times[-1] - times[0])
    body = values[1:]
    return MotionReading(
        values=values,
        times=times,
        mean=sum(body) / len(body),
        width=width,
        fps=float(fps) if fps else None,
        median=_median(body),
    )


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


@dataclass(frozen=True)
class FloorCalibration:
    kind: str  # push_in | pan
    fixture_mean: float
    floor: float
    fps: float
    width: int
    seconds: float


def motion_fixture(
    ffmpeg: str, frame: Path | str, kind: str, target: Path, *, fps: float
) -> Path | None:
    """A FIXTURE_SECONDS clip of `frame` moved by the fixture `kind`, lossless, at `fps`.

    The frame is covered to 1080x1920 and upscaled four times before zoompan, whose crop
    position is a whole pixel: at four times the size a whole pixel is a quarter of one in
    the result, so the fixture moves smoothly instead of in jitters that would read as motion.
    """
    frames = max(2, int(round(FIXTURE_SECONDS * fps)))
    last = frames - 1
    if kind == "push_in":
        zoom = f"zoompan=z='1+{PUSH_IN_ZOOM}*on/{last}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    elif kind == "pan":
        zoom = (
            f"zoompan=z='1/(1-{PAN_FRACTION})':x='iw*{PAN_FRACTION}*on/{last}':y='(ih-ih/zoom)/2'"
        )
    else:
        raise ValueError(f"unknown fixture: {kind}")
    rate = f"{fps:.6g}"
    result = _ffmpeg_run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-threads",
            "2",
            "-i",
            str(frame),
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            f"scale=4320:7680:flags=bicubic,{zoom}:d={frames}:s=1080x1920:fps={rate}",
            "-frames:v",
            str(frames),
            "-c:v",
            "libx264",
            "-qp",
            "0",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ]
    )
    if result is None or result.returncode != 0 or not target.is_file():
        return None
    return target


def calibrate_floors(
    ffmpeg: str | None,
    frame: Path | str,
    *,
    fps: float,
    work_dir: Path,
    kinds: tuple[str, ...] = ("push_in", "pan"),
) -> dict[str, FloorCalibration]:
    """The motion floor of each fixture kind for a clip whose first frame is `frame`.

    A kind whose fixture could not be built or measured is left out; the caller reads its
    absence as "not measured", never as a pass.
    """
    floors: dict[str, FloorCalibration] = {}
    if not ffmpeg:
        return floors
    work_dir.mkdir(parents=True, exist_ok=True)
    for kind in kinds:
        fixture = motion_fixture(ffmpeg, frame, kind, work_dir / f"fixture_{kind}.mp4", fps=fps)
        reading = measure_motion(ffmpeg, fixture) if fixture is not None else None
        if reading is None or reading.mean <= 0:
            continue
        floors[kind] = FloorCalibration(
            kind=kind,
            fixture_mean=reading.mean,
            floor=reading.mean * FLOOR_SHARE,
            fps=fps,
            width=reading.width,
            seconds=FIXTURE_SECONDS,
        )
    return floors


def canonical_move(camera_move: str | None) -> str | None:
    """The enum name of a camera move, read from its words; None when it names none or two."""
    from app.media.prompt_lint import CAMERA_MOVES  # noqa: PLC0415 - pure text module

    text = str(camera_move or "").strip().lower()
    if text in MOVE_FIXTURE:
        return text
    found = [move for move, pattern in CAMERA_MOVES.items() if re.search(pattern, text, re.I)]
    return found[0] if len(found) == 1 else None


@dataclass(frozen=True)
class ClipCheck:
    code: str
    status: str  # PASSED | FAILED | WARNING | NOT_RUN | NOT_APPLICABLE
    blocking: bool
    value: float | None
    detail_ro: str


def motion_check(
    reading: Any, camera_move: str | None, floors: dict[str, FloorCalibration]
) -> ClipCheck:
    """The clip's mean YDIF against the floor of the camera move it was asked for."""
    move = canonical_move(camera_move)
    if move is None:
        return ClipCheck(
            "motion",
            "NOT_RUN",
            True,
            None,
            f"mișcarea de cameră cerută («{str(camera_move or '')[:60]}») nu are un prag "
            "măsurat; mișcarea clipului nu a putut fi judecată",
        )
    if reading is None:
        return ClipCheck(
            "motion", "NOT_RUN", True, None, "mișcarea clipului nu a putut fi măsurată"
        )
    mean = float(reading.mean)
    fixture = MOVE_FIXTURE[move]
    if fixture is None:
        asked = (
            "cadru static cerut"
            if move == "static"
            else f"mișcarea «{move}» nu are o fixtură locală care să o măsoare"
        )
        return ClipCheck(
            "motion",
            "PASSED",
            False,
            mean,
            f"{asked}: fără prag de mișcare (YDIF mediu {_ro_number(mean, 2)})",
        )
    calibration = floors.get(fixture)
    if calibration is None:
        return ClipCheck(
            "motion",
            "NOT_RUN",
            True,
            mean,
            f"fixtura locală pentru «{move}» nu a putut fi construită; pragul nu e cunoscut",
        )
    # The motion must be sustained: the median frame must move as well as the mean one. A
    # frozen picture encoded with B-frames pulses between two reconstructions and reads a
    # mean YDIF of 1.5 (above a push-in fixture's 0.7) with half its frames identical, so its
    # median is 0.003; a real camera move changes every frame (median close to the mean).
    median = float(getattr(reading, "median", mean))
    if mean >= calibration.floor and median >= calibration.floor:
        return ClipCheck(
            "motion",
            "PASSED",
            False,
            mean,
            f"YDIF mediu {_ro_number(mean, 2)} (median {_ro_number(median, 2)}) la "
            f"{CLIP_METRIC_WIDTH} px, peste pragul de {_ro_number(calibration.floor, 2)} "
            f"pentru «{move}»",
        )
    return ClipCheck(
        "motion",
        "FAILED",
        True,
        mean,
        f"clipul aproape nu se mișcă: YDIF mediu {_ro_number(mean, 2)}, median "
        f"{_ro_number(median, 2)} la {CLIP_METRIC_WIDTH} px, sub pragul de "
        f"{_ro_number(calibration.floor, 2)} pentru «{move}» (jumătate din fixtura locală, "
        f"{_ro_number(calibration.fixture_mean, 2)})",
    )


def cut_spikes(reading: MotionReading | None) -> list[float]:
    """The times (s) of the frames that are a hard cut from the frame before them."""
    if reading is None or len(reading.values) < 3:
        return []
    threshold = max(CUT_SPIKE_MIN_YDIF, CUT_SPIKE_RATIO * _median(reading.values[1:]))
    return [
        round(reading.times[i], 3)
        for i in range(1, len(reading.values))
        if reading.values[i] > threshold
    ]


def clip_frames(
    ffmpeg: str | None, clip: Path | str, work_dir: Path
) -> list[tuple[str, float, Path]]:
    """The clip's first, middle and last frames as 1080 px wide PNGs: (at, time, path).

    Empty when they cannot be cut; the caller reads that as "not looked at"."""
    if not ffmpeg or not Path(clip).is_file():
        return []
    probe = probe_media_file(Path(clip), ffmpeg)
    fps = probe.get("video_fps")
    count = probe.get("video_frames")
    if not count and fps and probe.get("video_duration_seconds"):
        count = int(round(float(probe["video_duration_seconds"]) * float(fps)))
    if not probe.get("ok") or not fps or not count or count < 1:
        return []
    picks = [("first", 0), ("middle", int(count) // 2), ("last", int(count) - 1)]
    work_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{Path(clip).stem}_qc"
    for old in work_dir.glob(f"{stem}_*.png"):
        old.unlink()
    select_frames = "+".join(f"eq(n\\,{n})" for _, n in picks)
    result = _ffmpeg_run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-threads",
            "2",
            "-i",
            str(clip),
            "-an",
            "-vf",
            f"select='{select_frames}',scale=1080:-2:flags=lanczos",
            "-fps_mode",
            "passthrough",
            str(work_dir / f"{stem}_%d.png"),
        ]
    )
    if result is None or result.returncode != 0:
        return []
    out = [work_dir / f"{stem}_{i}.png" for i in range(1, len(picks) + 1)]
    if not all(path.is_file() for path in out):
        return []
    return [(at, round(n / float(fps), 3), path) for (at, n), path in zip(picks, out, strict=True)]


@dataclass(frozen=True)
class ClipReport:
    scene: int
    path: str
    checks: tuple[ClipCheck, ...]
    passed: bool
    blocks_ro: tuple[str, ...]
    warnings_ro: tuple[str, ...]
    #: Blocks that are "could not measure", which a retry cannot fix.
    unmeasured: tuple[str, ...]
    measured: dict[str, Any] = field(default_factory=dict)
    #: The still itself must change, so animating it again cannot fix the clip: its first
    #: frame (the still) is split by a flat band, or the look saw more than one picture or
    #: asked for back_to_still. `clip_retry_decision` never buys motion on it again.
    back_to_still: bool = False
    #: The look's answer to each motion-layer ``must_fix`` item (2026-10-12, late evening;
    #: `still_gate.fix_answers`): {"finding", "expected", "status", "fixed", "seen"}. Empty
    #: when nothing was asked.
    fixes: tuple[dict[str, Any], ...] = ()

    def check(self, code: str) -> ClipCheck:
        return next(item for item in self.checks if item.code == code)

    @property
    def persists(self) -> bool:
        """Whether the clip shows again a mistake its movement was rewritten to correct."""
        return any(fix.get("status") == "persists" for fix in self.fixes)

    @property
    def matched_plan(self) -> bool:
        """Whether the look said the clip shows its plan (False when nobody said so)."""
        picture = (self.measured or {}).get("picture") or {}
        flags = picture.get("verdict") if isinstance(picture, dict) else None
        return isinstance(flags, dict) and flags.get("matches_plan") is True


def _is_none(text: str) -> bool:
    return str(text or "").strip().strip(".").lower() in ("none", "no", "nothing", "nimic", "")


def _cut_words(text: Any, limit: int) -> str:
    said = " ".join(str(text or "").split())
    if len(said) <= limit:
        return said
    return said[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _persists_words(fix: Mapping[str, Any]) -> str:
    """A clip that shows again what its movement was rewritten to correct (2026-10-12, late
    evening): what quality control saw and the corrected words that did not correct it."""
    expected = _cut_words(fix.get("expected"), 120)
    words = (
        f"cuvintele «{expected}» nu au corectat-o"
        if expected
        else "cuvintele rescrise nu au corectat-o"
    )
    seen = _cut_words(fix.get("seen"), 120)
    # An item of the picture (still, or both layers) is the still's (`_still_must_change`).
    which = "rescrierea mișcării" if fix.get("layer") in (None, "motion") else "rescrierea imaginii"
    return (
        f"repetă greșeala pe care {which} trebuia să o corecteze: "
        f"«{_cut_words(fix.get('finding'), 160)}»; {words}"
        + (f" (se vede: {seen})" if seen else "")
    )


def _picture_check(
    judgement: Any, *, faces_forbidden: bool, fixes: Sequence[Mapping[str, Any]] = ()
) -> ClipCheck:
    """The vision checklist, read strictly: a keep whose own answers contradict it fails.
    ``fixes`` are the look's answers to the motion-layer ``must_fix`` items: one that persists
    fails the clip (with the corrected words that did not correct it), one left unanswered is
    a clip nobody checked for it; a minor trace does not fail it."""
    if judgement is None:
        return ClipCheck(
            "picture",
            "NOT_RUN",
            True,
            None,
            "clipul nu a fost privit: niciun model care vede nu s-a uitat la cele trei cadre",
        )
    verdict = getattr(judgement, "verdict", None)
    if getattr(judgement, "status", None) != "MEASURED" or verdict is None:
        detail = str(getattr(judgement, "detail_ro", "") or "clipul nu a fost privit")
        if "nu a fost privit" not in detail:
            detail = f"clipul nu a fost privit: {detail}"
        return ClipCheck("picture", "NOT_RUN", True, None, detail)
    wrong: list[str] = []
    for fix in fixes:
        if fix.get("status") is None:
            # Only a verdict built in code can leave an item out (`clip_report_schema`).
            return ClipCheck(
                "picture",
                "NOT_RUN",
                True,
                None,
                "clipul nu a fost privit pentru greșeala «"
                + _cut_words(fix.get("finding"), 160)
                + "»: modelul de vedere nu a spus dacă a dispărut",
            )
        if fix.get("status") == "persists":
            # First among the reasons: the take's detail is cut, and the ladder reads it.
            wrong.insert(0, _persists_words(fix))
    if faces_forbidden and verdict.faces_visible:
        wrong.append("se vede o față, deși biblia vizuală interzice fețele")
    if verdict.readable_text:
        wrong.append("apare text sau un logo")
    if not verdict.matches_plan:
        wrong.append("nu arată ce cere planul")
    if not verdict.look_ok:
        wrong.append("nu păstrează aspectul filmului")
    if not verdict.technical_ok:
        wrong.append("are deformări sau artefacte")
    if not verdict.same_shot:
        wrong.append("cele trei cadre nu sunt același plan continuu")
    if not verdict.one_picture:
        wrong.append(
            "cadrele nu sunt o singură fotografie (panouri, colaj, ecran împărțit sau o bandă "
            "goală); imaginea însăși trebuie refăcută"
        )
    if not _is_none(verdict.bible_violations):
        wrong.append(f"încalcă biblia vizuală: {verdict.bible_violations}")
    if verdict.verdict != "keep" and not wrong:
        wrong.append(f"modelul cere {verdict.verdict}")
    if wrong:
        return ClipCheck(
            "picture",
            "FAILED",
            True,
            None,
            f"privit la 1080 px: {'; '.join(wrong)} («{verdict.reason}»)",
        )
    return ClipCheck("picture", "PASSED", False, None, f"privit la 1080 px: «{verdict.reason}»")


def _faces_check(
    frames: list[tuple[str, float, Path]],
    counter: Callable[..., Any],
    *,
    faces_forbidden: bool,
    measured: dict[str, Any],
) -> ClipCheck:
    """YuNet on the first, middle and last frames, when the bible forbids faces."""
    if not faces_forbidden:
        return ClipCheck("faces", "NOT_APPLICABLE", False, None, "biblia vizuală permite fețe")
    if not frames:
        return ClipCheck("faces", "NOT_RUN", True, None, "cadrele clipului nu au putut fi tăiate")
    counted: list[dict[str, Any]] = []
    for at, moment, path in frames:
        found = counter(path)
        counted.append(
            {
                "at": at,
                "time": moment,
                "status": found.status,
                "faces": found.faces,
                "detail_ro": found.detail_ro,
            }
        )
    measured["faces"] = {"frames": counted}
    seen = [entry for entry in counted if entry["status"] == "MEASURED" and entry["faces"]]
    if seen:
        return ClipCheck(
            "faces",
            "FAILED",
            True,
            float(sum(int(entry["faces"]) for entry in seen)),
            "YuNet a găsit fețe în cadrul "
            + ", ".join(f"{entry['at']} ({entry['faces']})" for entry in seen)
            + ", deși biblia vizuală interzice fețele",
        )
    problem = next((entry for entry in counted if entry["status"] != "MEASURED"), None)
    if problem is not None:
        return ClipCheck("faces", "NOT_RUN", True, None, str(problem["detail_ro"]))
    return ClipCheck("faces", "PASSED", False, 0.0, "YuNet: nicio față în cele trei cadre")


def _panels_check(
    ffmpeg: str | None,
    frames: list[tuple[str, float, Path]],
    *,
    measured: dict[str, Any],
) -> ClipCheck:
    """The flat band (`flat_band`) on the first, middle and last frames: a frame split by a
    band of at least PANEL_BAND_SHARE of its height beside at least FRAME_PICTURE_FLOOR of
    picture (`FlatBand.splits_the_picture`) is panels pasted together, or a blank strip, not
    one picture; a soft-edged band at the top or the bottom is the scene's sky. Free, and
    measured whether or not anybody looks."""
    if not frames:
        return ClipCheck("panels", "NOT_RUN", True, None, "cadrele nu au putut fi tăiate")
    read: list[dict[str, Any]] = []
    split: list[tuple[str, FlatBand]] = []
    soft: list[tuple[str, FlatBand]] = []
    unread = False
    for at, moment, path in frames:
        band = flat_band(ffmpeg, path)
        if band is None:
            unread = True
            read.append({"at": at, "time": moment, "status": "NOT_RUN"})
            continue
        read.append({"at": at, "time": moment, "status": "MEASURED", **band.as_dict()})
        if band.splits_the_picture:
            split.append((at, band))
        elif band.wide and band.soft_edge:
            soft.append((at, band))
    measured["panels"] = {
        "frames": read,
        "band_share_threshold": PANEL_BAND_SHARE,
        "picture_share_floor": FRAME_PICTURE_FLOOR,
    }
    if split:
        return ClipCheck(
            "panels",
            "FAILED",
            True,
            round(max(band.share for _at, band in split), 3),
            "nu e o singură fotografie: "
            + "; ".join(f"cadrul {at} are {band.detail_ro()}" for at, band in split),
        )
    if unread:
        return ClipCheck(
            "panels", "NOT_RUN", True, None, "benzile cadrelor nu au putut fi măsurate"
        )
    widest = max(float(entry["band_share"]) for entry in read)
    detail = (
        f"o singură imagine în fiecare cadru (cea mai lată bandă plată: {widest:.0%}, prag "
        f"{PANEL_BAND_SHARE:.0%})"
    )
    if soft:
        named = ("în cadrul " if len(soft) == 1 else "în cadrele ") + ", ".join(
            at for at, _band in soft
        )
        widest_soft = max((band for _at, band in soft), key=lambda band: band.rows)
        detail += f"; {named}, {widest_soft.soft_edge_ro()}"
    return ClipCheck("panels", "PASSED", False, widest, detail)


def _still_must_change(
    measured: dict[str, Any], judgement: Any, *, fixes: Sequence[Mapping[str, Any]] = ()
) -> bool:
    """Whether the clip's fault is its still's: the first frame (the still the clip was made
    from) is split by a flat band, or the look saw more than one picture or asked for the
    still to change, or an item checked on the clip that lives in the PICTURE (layer still,
    or both: no still was approved since it was found) is there again. Another seed on the
    same still buys the same fault (2026-10-09: scene 5 was a triptych, and its clip animated
    the triptych). A clip that repeats a mistake its MOVEMENT was rewritten to correct (layer
    motion) goes back to the motion's words, unless the look itself says the still must change.

    2026-10-12 (the review of 5fc7468, finding 5): a persisting item silenced the look's own
    ``back_to_still``, and seed + 1 was bought from a still that had to change."""
    frames = (measured.get("panels") or {}).get("frames") or []
    if any(entry.get("at") == "first" and entry.get("splits_the_picture") for entry in frames):
        return True
    verdict = getattr(judgement, "verdict", None)
    if getattr(judgement, "status", None) != "MEASURED" or verdict is None:
        return False
    if not verdict.one_picture or verdict.verdict == "back_to_still":
        return True
    return any(
        fix.get("status") == "persists" and fix.get("layer") in ("still", "both") for fix in fixes
    )


def check_clip(
    clip: Path | str,
    *,
    scene: int,
    camera_move: str | None,
    faces_forbidden: bool,
    environment: str,
    ffmpeg_path: str | None = None,
    face_counter: Callable[..., Any] | None = None,
    judge: Callable[[list[Path]], Any] | None = None,
    work_dir: Path | None = None,
    must_fix: Sequence[Mapping[str, Any]] = (),
    expected_markings: Sequence[str] = (),
) -> ClipReport:
    """Measure one bought clip before it is cut into the film, at 0 credits.

    ``expected_markings`` (2026-10-13): the plan's objects that carry their own markings
    (`still_gate.StillPlan.expected_markings`), kept on ``measured["picture"]`` so that a
    writing refusal of such a clip is the Director's to overturn (`look_may_overturn`).

    - motion: mean YDIF at 540 px against the floor of its camera move (`motion_check`);
    - cuts: a hard cut inside the clip fails it (`cut_spikes`);
    - faces: YuNet on the first, middle and last frames when the bible forbids faces;
    - panels: a flat full-width band on any of the three frames (`flat_band`);
    - picture: `judge` (normally picture_qc.judge_clip bound to the engine and registry)
      looks at the same three frames at 1080 px.

    Fail closed: a local check that could not run blocks in PRODUCTION and warns in TEST; a
    clip nobody looked at blocks in every environment, as a still does at the stills gate.
    A clip whose still is at fault (`_still_must_change`) is marked ``back_to_still``.

    ``must_fix`` (2026-10-12, late evening): what the scene's movement was rewritten to fix
    (`fix_check.open_findings`, motion layer; the same items the judge was shown on its plan).
    The look's answers are kept on the report (``fixes``, and ``measured["picture"]``): one
    that persists fails the picture check — back to the motion's words, not the still — a minor
    trace is a warning.
    """
    from app.media.faces import count_faces  # noqa: PLC0415 - opencv loads lazily

    counter = face_counter or count_faces
    ffmpeg = find_ffmpeg(ffmpeg_path)
    owned = work_dir is None
    folder = Path(tempfile.mkdtemp(prefix="clip_qc_")) if work_dir is None else work_dir
    folder.mkdir(parents=True, exist_ok=True)
    measured: dict[str, Any] = {}
    try:
        reading = measure_motion(ffmpeg, clip)
        frames = clip_frames(ffmpeg, clip, folder)
        move = canonical_move(camera_move)
        fixture = MOVE_FIXTURE.get(move) if move else None
        floors: dict[str, FloorCalibration] = {}
        if fixture and frames and reading is not None and reading.fps:
            floors = calibrate_floors(
                ffmpeg, frames[0][2], fps=reading.fps, work_dir=folder, kinds=(fixture,)
            )
        motion = motion_check(reading, camera_move, floors)
        calibration = floors.get(fixture) if fixture else None
        measured["motion"] = {
            "metric": f"mean signalstats YDIF at {CLIP_METRIC_WIDTH} px",
            "mean_ydif": round(reading.mean, 4) if reading else None,
            "median_ydif": round(reading.median, 4) if reading else None,
            "fps": reading.fps if reading else None,
            "camera_move": move,
            "fixture": fixture,
            "fixture_mean": round(calibration.fixture_mean, 4) if calibration else None,
            "floor": round(calibration.floor, 4) if calibration else None,
        }
        if reading is None:
            cuts = ClipCheck("cuts", "NOT_RUN", True, None, "tăieturile nu au putut fi căutate")
        else:
            spikes = cut_spikes(reading)
            measured["cuts"] = {"spikes_at": spikes}
            cuts = (
                ClipCheck(
                    "cuts",
                    "FAILED",
                    True,
                    float(len(spikes)),
                    "clipul are o tăietură bruscă la "
                    + ", ".join(f"{_ro_number(t, 2)} s" for t in spikes)
                    + "; un cadru trebuie să fie un singur plan continuu",
                )
                if spikes
                else ClipCheck("cuts", "PASSED", False, 0.0, "nicio tăietură în clip")
            )
        faces = _faces_check(frames, counter, faces_forbidden=faces_forbidden, measured=measured)
        panels = _panels_check(ffmpeg, frames, measured=measured)
        judgement = judge([path for _at, _moment, path in frames]) if judge and frames else None
        fixes: list[dict[str, Any]] = []
        if must_fix and getattr(judgement, "status", None) == "MEASURED":
            from app.media.still_gate import fix_answers  # noqa: PLC0415 - still_gate imports us

            fixes = fix_answers(must_fix, getattr(judgement, "verdict", None))
        picture = _picture_check(judgement, faces_forbidden=faces_forbidden, fixes=fixes)
        if judgement is not None:
            measured["picture"] = {
                "status": getattr(judgement, "status", None),
                "run_id": getattr(judgement, "run_id", None),
                "looked_by": getattr(judgement, "looked_by", None),
                # The look's own yes/no answers, so the retry can tell a clip that warped,
                # turned a face or broke its shot (`clip_deformed`) from one that barely moved.
                "verdict": _verdict_flags(getattr(judgement, "verdict", None)),
            }
            if fixes:
                measured["picture"]["fixes"] = fixes
            if expected_markings:
                measured["picture"]["planned_markings"] = [str(n) for n in expected_markings]
    finally:
        if owned:
            shutil.rmtree(folder, ignore_errors=True)

    checks: list[ClipCheck] = []
    warnings: list[str] = [
        f"Scena {scene}: urmă mică a greșelii «{_cut_words(fix.get('finding'), 160)}», "
        "acceptată" + (f" (se vede: {_cut_words(fix.get('seen'), 120)})" if fix.get("seen") else "")
        for fix in fixes
        if fix.get("status") == "minor"
    ]
    for item in (motion, cuts, faces, panels):
        if item.status == "NOT_RUN" and environment != "PRODUCTION":
            # In TEST a measurement that could not run is said, not counted: the rule the
            # stills gate keeps for its local checks.
            warnings.append(f"Scena {scene}: {item.detail_ro}")
            item = ClipCheck(item.code, "WARNING", False, item.value, item.detail_ro)
        checks.append(item)
    checks.append(picture)
    blocking = [item for item in checks if item.blocking]
    return ClipReport(
        scene=scene,
        path=str(clip),
        checks=tuple(checks),
        passed=not blocking,
        blocks_ro=tuple(f"Scena {scene}: {item.detail_ro}" for item in blocking),
        warnings_ro=tuple(warnings),
        unmeasured=tuple(item.code for item in blocking if item.status == "NOT_RUN"),
        measured=measured,
        back_to_still=bool(blocking) and _still_must_change(measured, judgement, fixes=fixes),
        fixes=tuple(fixes),
    )


# ------------------------------------------------------------- one retry, inside the cap

#: The verdict's yes/no answers kept on a clip report (`check_clip`), in the look's own names.
_VERDICT_FLAGS = (
    "faces_visible",
    "readable_text",
    "matches_plan",
    "look_ok",
    "technical_ok",
    "same_shot",
    "one_picture",
)


def _verdict_flags(verdict: Any) -> dict[str, bool]:
    """The look's boolean answers, only those it gave as booleans."""
    flags: dict[str, bool] = {}
    for name in _VERDICT_FLAGS:
        value = getattr(verdict, name, None)
        if isinstance(value, bool):
            flags[name] = value
    return flags


def clip_deformed(report: ClipReport) -> bool:
    """Whether a failed clip's fault is what the motion did to the picture — a face turned to
    the camera, warping or artefacts, a look that slid, three frames that are not one shot —
    and not how little it moved. A clip that also failed its motion floor barely moved: the
    retry then asks for the move more firmly, as before (`stronger_motion_prompt`)."""
    checks = {item.code: item for item in report.checks}
    motion = checks.get("motion")
    if motion is not None and motion.status == "FAILED":
        return False
    faces = checks.get("faces")
    if faces is not None and faces.status == "FAILED":
        return True
    picture = (report.measured or {}).get("picture") or {}
    flags = picture.get("verdict") if isinstance(picture, dict) else None
    if not isinstance(flags, dict):
        return False
    return bool(flags.get("faces_visible")) or any(
        flags.get(name) is False for name in ("technical_ok", "same_shot", "look_ok")
    )


def _retry_body(prompt: str) -> tuple[str, bool]:
    """(the prompt without its closing line and without the compiler's old stillness
    sentences, whether the closing was veo's)."""
    from app.media.prompt_lint import (  # noqa: PLC0415 - pure text module
        LEGACY_STILLNESS,
        MOTION_CLOSING,
        VEO_MOTION_CLOSING,
    )

    body = str(prompt or "").strip()
    veo_closing = False
    for ending in (MOTION_CLOSING, VEO_MOTION_CLOSING):
        if body.endswith(ending):
            body = body[: -len(ending)].rstrip()
            veo_closing = ending == VEO_MOTION_CLOSING
            break
    # A stored prompt of a film planned before 2026-10-11 asked the background to stay stable
    # and the movement to stay unhurried, then measured the clip as barely moving.
    for sentence in LEGACY_STILLNESS:
        body = " ".join(body.replace(sentence, " ").split())
    return body, veo_closing


def _with_closing(body: str, firmer: str, *, veo: bool) -> str:
    from app.media.prompt_lint import MOTION_CLOSING, VEO_MOTION_CLOSING  # noqa: PLC0415

    if firmer not in body:
        body = f"{body} {firmer}".strip()
    return f"{body} {VEO_MOTION_CLOSING if veo else MOTION_CLOSING}"


def _camera_words(move: str) -> str:
    """How the retry names the move: its own words, without the "slow" of the older keys, so
    the sentence names the one move the prompt already names (CAMERA_COUNT stays one)."""
    return move.removeprefix("slow ")


def stronger_motion_prompt(
    prompt: str, camera_move: str | None, *, model_id: str | None = None
) -> str:
    """The same motion prompt with the camera move asked for more firmly, for the one retry
    of a clip that barely moved.

    Positive words only (veo's prompt carries no negation), placed before the closing line,
    which stays the last sentence in the model's own dialect. The compiler's old stillness
    sentences, where a stored prompt carries them, are taken out: they asked for the fault.
    """
    veo = "veo" in str(model_id or "").lower()
    move = canonical_move(camera_move)
    if move is None or move == "static":
        firmer = (
            "The scene itself keeps moving clearly and steadily from the first frame to the last."
        )
    else:
        firmer = (
            f"The camera's {_camera_words(move)} is clearly visible and keeps going "
            "steadily from the first frame to the last."
        )
    body, _veo_closing = _retry_body(prompt)
    return _with_closing(body, firmer, veo=veo)


def calmer_motion_prompt(
    prompt: str, camera_move: str | None, *, model_id: str | None = None
) -> str:
    """The same motion prompt with the move's amplitude dialled down one step, for the one
    retry of a clip that moved but deformed what it moved (`clip_deformed`): the move stays,
    smooth and moderate, and every shape keeps its form. The Director's ladder (2026-10-11,
    «Mișcare v2»): ample motion is the rule, and a deformation measured by clip QC is what
    takes one step back, never the plan's silence."""
    veo = "veo" in str(model_id or "").lower()
    move = canonical_move(camera_move)
    if move is None or move == "static":
        calmer = (
            "The scene keeps moving smoothly and moderately, and every shape and edge keeps "
            "its form from the first frame to the last."
        )
    else:
        calmer = (
            f"The camera's {_camera_words(move)} stays smooth and moderate, and every shape "
            "and edge keeps its form from the first frame to the last."
        )
    body, _veo_closing = _retry_body(prompt)
    return _with_closing(body, calmer, veo=veo)


def retry_motion_prompt(
    prompt: str, camera_move: str | None, report: ClipReport, *, model_id: str | None = None
) -> str:
    """The motion prompt of the one retry, from what the first clip did wrong: firmer when it
    barely moved, one step calmer when it moved and deformed (`clip_deformed`)."""
    if clip_deformed(report):
        return calmer_motion_prompt(prompt, camera_move, model_id=model_id)
    return stronger_motion_prompt(prompt, camera_move, model_id=model_id)


@dataclass(frozen=True)
class ClipRetry:
    action: str  # ACCEPT | RETRY | ESCALATE | BACK_TO_STILL
    seed: int | None
    reason_ro: str


def clip_capped_words(scene: int) -> str:
    """Why a refused clip buys no retry once the scene's motion has had its renders: the
    Owner's cap, its number read now, and what happens instead (a clip of the scene is kept
    under the cap, `assembler._keep_clip_under_cap`: the one it has, the one the Director
    chooses among several, or the studio's own pick when she cannot, `cap_choice`)."""
    from app.media.cap_choice import CAP_KEEPS_RO  # noqa: PLC0415 - media reads the agents

    return (
        f"Scena {scene}: clipul a picat controlul, iar plafonul Proprietarului "
        f"({renders_of_ro('mișcării')}) este atins; nu se mai cumpără o reluare: "
        f"{CAP_KEEPS_RO}."
    )


def clip_retry_decision(
    report: ClipReport,
    *,
    seed: int,
    retries_done: int,
    committed_credits: float,
    price_credits: float,
    cap_credits: float,
    renders_left: int | None = None,
) -> ClipRetry:
    """What a clip's QC verdict buys: nothing more, one retry with seed + 1, a new still, or
    the Owner. A clip whose still is at fault (``report.back_to_still``) is never animated
    again from that still: another seed animates the same panels (2026-10-09, scene 5).

    ``renders_left``: how many more renders of the scene's motion the Owner's renders cap
    allows after this clip (`renders_cap`), when the caller counted them. At none, no retry
    is bought whatever the money says, and the refusal says so before the money is read: the
    cap, not the approved credits, is what stops it, and past it the Director keeps the
    closest clip (2026-10-16, «maxim încă o randare»)."""
    if report.passed:
        return ClipRetry("ACCEPT", seed, f"Scena {report.scene}: clipul a trecut controlul.")
    if report.back_to_still:
        why = next(
            (
                item.detail_ro
                for item in report.checks
                if item.blocking and item.status == "FAILED" and item.code in ("panels", "picture")
            ),
            "imaginea din care a pornit clipul nu e cea cerută",
        )
        return ClipRetry(
            "BACK_TO_STILL",
            None,
            f"Scena {report.scene}: greșeala e în imaginea din care s-a făcut clipul ({why}); "
            "aceeași imagine nu se mai animă. Scena are nevoie de o imagine nouă, apoi de "
            "mișcare nouă.",
        )
    if renders_left is not None and renders_left <= 0:
        return ClipRetry("ESCALATE", None, clip_capped_words(report.scene))
    if report.persists and report.matched_plan:
        # 2026-10-12, late evening (the review of 9ac0195, finding 3, for the clip): the clip
        # shows its corrected movement and the mistake is there again, so those words do not
        # correct it; a seed + 1 on them is the same mistake bought again. Her ladder rewrites
        # the movement (a clip QC refusal is a content refusal, `scene_rewrite.refusal_kind`).
        persisted = next(fix for fix in report.fixes if fix.get("status") == "persists")
        expected = _cut_words(persisted.get("expected"), 120)
        words = f"cuvintele «{expected}»" if expected else "cuvintele rescrise"
        return ClipRetry(
            "ESCALATE",
            None,
            f"Scena {report.scene}: clipul arată planul și repetă totuși greșeala "
            f"«{_cut_words(persisted.get('finding'), 120)}»: {words} nu au corectat-o. Nu se "
            "cumpără o reluare pe aceleași cuvinte; Directoarea rescrie mișcarea.",
        )
    if retries_done >= clip_retries():
        if not retries_done:
            # A cap of one render: the clip was the motion's only one.
            return ClipRetry("ESCALATE", None, clip_capped_words(report.scene))
        return ClipRetry(
            "ESCALATE",
            None,
            f"Scena {report.scene}: clipul a picat controlul și după reluare; nu se mai "
            "cumpără. Decide Proprietarul pe foaia de filmare.",
        )
    blocking = [item for item in report.checks if item.blocking]
    if blocking and all(item.status == "NOT_RUN" for item in blocking):
        return ClipRetry(
            "ESCALATE",
            None,
            f"Scena {report.scene}: clipul nu s-a putut măsura ("
            + ", ".join(report.unmeasured)
            + "); o reluare nu ar repara măsurarea. Decide Proprietarul.",
        )
    if committed_credits + price_credits > cap_credits:
        return ClipRetry(
            "ESCALATE",
            None,
            f"Scena {report.scene}: reluarea ar costa {price_credits:.0f} credite și ar depăși "
            f"plafonul aprobat de {cap_credits:.0f} (deja {committed_credits:.0f}); nu se "
            "cumpără. Decide Proprietarul.",
        )
    asked = (
        "mișcarea cerută mai lin, cu formele păstrate"
        if clip_deformed(report)
        else "mișcarea cerută mai ferm"
    )
    return ClipRetry(
        "RETRY",
        int(seed) + 1,
        f"Scena {report.scene}: o singură reluare pe același model, cu sămânța {int(seed) + 1} "
        f"și {asked} ({price_credits:.0f} credite, în plafon).",
    )


@dataclass(frozen=True)
class ClipQCOutcome:
    #: BACK_TO_STILL: the clip failed because of its still; no motion was bought again on it,
    #: and the scene needs a new still before any new motion. ACCEPTED_BY_LOOK (2026-10-12):
    #: clip QC refused the last clip (``reports[-1]``) and the Director's look kept it
    #: (``look``): nothing more was bought, and the clip goes on as hers.
    status: str  # PASSED | PASSED_ON_RETRY | ESCALATED | BACK_TO_STILL | ACCEPTED_BY_LOOK
    clip: Path | None
    attempts: int
    seeds: tuple[int, ...]
    reports: tuple[ClipReport, ...]
    retry_credits: float
    reason_ro: str
    prompt: str
    #: Her look at the last refused clip, when she was asked (`fix_check.director_second_look`).
    look: dict[str, Any] | None = None


ACCEPTED_BY_LOOK = "ACCEPTED_BY_LOOK"


def sent_back_by_reading(report: ClipReport) -> bool:
    """Whether a clip sent back to its still (``back_to_still``) was sent back only by a
    reading — the look's own «back_to_still», or a picture item it says is there again — and
    not by a flat band measured on the first frame nor by the look seeing more than one
    picture (panels: a hard limit of the bible)."""
    if not report.back_to_still:
        return False
    frames = ((report.measured or {}).get("panels") or {}).get("frames") or []
    if any(entry.get("at") == "first" and entry.get("splits_the_picture") for entry in frames):
        return False
    picture = (report.measured or {}).get("picture") or {}
    flags = picture.get("verdict") if isinstance(picture, dict) else None
    return isinstance(flags, dict) and flags.get("one_picture") is not False


#: The clip checks that MEASURE (YDIF against the move's floor, a hard cut): a clip they
#: refused is kept by her look only as «not in the clip» (`fix_check.look_accepts`, measured;
#: the shared contract of 2026-10-12, night — a frozen clip is serious whatever is written).
MEASURED_CLIP_CHECKS = frozenset({"motion", "cuts"})


def measured_refusal(report: ClipReport) -> bool:
    """Whether a measured clip check (`MEASURED_CLIP_CHECKS`) refused the clip."""
    return any(
        item.blocking and item.status == "FAILED" and item.code in MEASURED_CLIP_CHECKS
        for item in report.checks
    )


def look_may_overturn(report: ClipReport) -> bool:
    """Whether the Director may be asked to look again at a refused clip before anything more
    is bought for it: a refusal measured whole (nothing unmeasured) on a reading — the motion
    floor, a cut, the plan, the look, a deformation, a corrected mistake seen again, the still
    sent back by the look's own reading (`sent_back_by_reading`) — and none of the bible's
    hard limits (a face where faces are forbidden, panels), which stay the code's (the
    Owner, 2026-10-12); writing is hers (2026-10-15).

    2026-10-12 (the review of 5fc7468, finding 8): a clip the look's reading sent back to its
    still bought a new still and new motion with nobody looking whether the reading was right.
    """
    if report.passed or report.unmeasured:
        return False
    if report.back_to_still and not sent_back_by_reading(report):
        return False
    failed = {item.code for item in report.checks if item.blocking and item.status == "FAILED"}
    if not failed or failed & {"faces", "panels"}:
        return False
    picture = (report.measured or {}).get("picture") or {}
    flags = picture.get("verdict") if isinstance(picture, dict) else None
    flags = flags if isinstance(flags, dict) else {}
    if flags.get("one_picture") is False:
        return False
    # Writing is hers to judge (2026-10-15, the Owner: the scene's own writing stays; only
    # text laid over the picture or a logo is serious, and she says which).
    faces = next((item for item in report.checks if item.code == "faces"), None)
    forbidden = faces is not None and faces.status != "NOT_APPLICABLE"
    return not (flags.get("faces_visible") and forbidden)


def _her_words(look: Mapping[str, Any] | None) -> str:
    """Her confirmation, said with what it lets be bought (or escalated)."""
    if not look or look.get("verdict") != "CONFIRMED" or not look.get("reason_ro"):
        return ""
    return f" Directoarea a privit și confirmă refuzul: {look['reason_ro']}"


def _looked(
    look: Callable[[ClipReport], Mapping[str, Any] | None] | None, report: ClipReport
) -> dict[str, Any] | None:
    """Her look at a refused clip, asked only where she may overturn it."""
    if look is None or not look_may_overturn(report):
        return None
    answer = look(report)
    return dict(answer) if answer else None


def qc_clip_with_retry(
    clip: Path,
    *,
    check: Callable[[Path], ClipReport],
    buy: Callable[[int, str], Path | None],
    seed: int,
    motion_prompt: str,
    camera_move: str | None,
    model_id: str,
    price_credits: float,
    committed_credits: float,
    cap_credits: float,
    look: Callable[[ClipReport], Mapping[str, Any] | None] | None = None,
    renders_left: int | None = None,
) -> ClipQCOutcome:
    """Check a bought clip. Production supplies ``look``: a refusal goes to the existing
    Director rewrite/review ladder before a replacement is bought. Without that workflow
    callback the standalone helper retains its one mechanical retry inside the cap.
    ``buy(seed, prompt)`` returns the delivered clip or None. A clip whose still is at fault
    buys nothing and comes back BACK_TO_STILL.

    ``look(report)`` (2026-10-12; the Owner: «trece imaginile picate de la QC pe la Directoare
    și să decidă dacă au picat corect sau nu și dacă trebuie refăcute») is the Director's
    second look at a refused clip (`fix_check.director_second_look`), asked before the retry is
    bought and before a refusal goes on to a rewrite, wherever she may overturn it
    (`look_may_overturn`): a look that lets the clip stand (`fix_check.look_accepts`) buys
    nothing more — ACCEPTED_BY_LOOK, the clip kept as hers. Otherwise the replacement words
    require her separate review; an unavailable look cannot authorize a mechanical retry.
    A clip sent back to its still only by
    a reading (`sent_back_by_reading`) is shown to her too before a new still is bought; a
    refusal clip QC measured (`measured_refusal`) is kept only as «not in the clip».

    ``renders_left``: the renders of the scene's motion the Owner's cap allows after this
    clip (`clip_retry_decision`); at none, no retry is bought and the refusal names the cap."""
    from app.media.fix_check import look_accepts  # noqa: PLC0415 - a small module

    first = check(clip)
    decision = clip_retry_decision(
        first,
        seed=seed,
        retries_done=0,
        committed_credits=committed_credits,
        price_credits=price_credits,
        cap_credits=cap_credits,
        renders_left=renders_left,
    )
    if decision.action == "ACCEPT":
        return ClipQCOutcome("PASSED", clip, 1, (seed,), (first,), 0.0, decision.reason_ro, "")
    # Before a retry, a rewrite or a new still is bought for it, she looks — where she may.
    seen = _looked(look, first)
    if decision.action == "BACK_TO_STILL" and not look_accepts(
        seen, measured=measured_refusal(first)
    ):
        return ClipQCOutcome(
            "BACK_TO_STILL",
            None,
            1,
            (seed,),
            (first,),
            0.0,
            decision.reason_ro + _her_words(seen),
            "",
            look=seen,
        )
    if look_accepts(seen, measured=measured_refusal(first)):
        return ClipQCOutcome(
            ACCEPTED_BY_LOOK,
            clip,
            1,
            (seed,),
            (first,),
            0.0,
            f"Scena {first.scene}: Directoarea a privit clipul refuzat și îl păstrează: "
            f"{(seen or {}).get('reason_ro') or 'defectul e mic'}. Nu se cumpără nimic.",
            "",
            look=seen,
        )
    if decision.action == "ESCALATE" or decision.seed is None:
        return ClipQCOutcome(
            "ESCALATED",
            None,
            1,
            (seed,),
            (first,),
            0.0,
            decision.reason_ro + _her_words(seen),
            "",
            look=seen,
        )
    if look is not None:
        # The production caller has the Director's ladder. Her look at the OLD clip is
        # not approval of replacement words: Kelvin's distorted face was followed by a
        # generic calmer suffix that ignored her diagnosis. Route the refusal to her
        # brief, the Editor's rewrite and her review before buying a replacement, also
        # when the second look was unavailable or ineligible for a hard limit.
        return ClipQCOutcome(
            "ESCALATED",
            None,
            1,
            (seed,),
            (first,),
            0.0,
            f"Scena {first.scene}: promptul de înlocuire trebuie verificat de Directoare "
            "pentru defectul constatat înainte de regenerare. Refuzul merge la rescriere; "
            "nu se cumpără reluarea automată." + _her_words(seen),
            "",
            look=seen,
        )
    prompt = retry_motion_prompt(motion_prompt, camera_move, first, model_id=model_id)
    again = buy(decision.seed, prompt)
    seeds = (seed, decision.seed)
    if again is None:
        return ClipQCOutcome(
            "ESCALATED",
            None,
            2,
            seeds,
            (first,),
            float(price_credits),
            f"Scena {first.scene}: reluarea nu a livrat clipul. Decide Proprietarul."
            + _her_words(seen),
            prompt,
            look=seen,
        )
    second = check(Path(again))
    if second.passed:
        return ClipQCOutcome(
            "PASSED_ON_RETRY",
            Path(again),
            2,
            seeds,
            (first, second),
            float(price_credits),
            f"Scena {first.scene}: clipul a trecut la reluare (sămânța {decision.seed})."
            + _her_words(seen),
            prompt,
            look=seen,
        )
    final = clip_retry_decision(
        second,
        seed=decision.seed,
        retries_done=1,
        committed_credits=committed_credits + price_credits,
        price_credits=price_credits,
        cap_credits=cap_credits,
        renders_left=None if renders_left is None else renders_left - 1,
    )
    # The retry failed too: before the scene goes on to a rewrite or a new still (and a
    # purchase), she looks at the clip bought last, where she may (`look_may_overturn`).
    last_look = _looked(look, second)
    if look_accepts(last_look, measured=measured_refusal(second)):
        return ClipQCOutcome(
            ACCEPTED_BY_LOOK,
            Path(again),
            2,
            seeds,
            (first, second),
            float(price_credits),
            f"Scena {first.scene}: Directoarea a privit reluarea refuzată și o păstrează: "
            f"{(last_look or {}).get('reason_ro') or 'defectul e mic'}. Nu se cumpără "
            "nimic.",
            prompt,
            look=last_look,
        )
    seen = last_look or seen
    return ClipQCOutcome(
        "BACK_TO_STILL" if final.action == "BACK_TO_STILL" else "ESCALATED",
        None,
        2,
        seeds,
        (first, second),
        float(price_credits),
        final.reason_ro + _her_words(seen),
        prompt,
        look=seen,
    )


# ------------------------------------------ no still in PRODUCTION without the Owner's choice


class FallbackNotChosen(RuntimeError):
    """A LIVE scene would be a still in a PRODUCTION film, and the Owner did not choose it."""

    def __init__(self, scenes: list[int], message_ro: str) -> None:
        super().__init__(message_ro)
        self.scenes = scenes
        self.message_ro = message_ro


def _moved(motion: Any) -> bool:
    return isinstance(motion, dict) and bool(motion.get("bytes") or motion.get("reused_take"))


def live_fallback_scenes(production: dict[str, Any]) -> list[int] | None:
    """The LIVE scenes the film shows as a still, from the render's own per-scene record;
    None when the record has no per-scene list (a render from before it)."""
    scenes = production.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return None
    fallbacks: list[int] = []
    for entry in scenes:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("scene_kind") or "LIVE").upper() != "LIVE":
            continue  # a card is composed, never filmed
        if not _moved(entry.get("motion")):
            try:
                fallbacks.append(int(entry.get("scene_index") or 0))
            except (TypeError, ValueError):
                fallbacks.append(0)
    return sorted(fallbacks)


def owner_local_moves(session: Session, storyboard_id: str) -> set[int]:
    """The scenes the Owner chose, on the sheet, to show as a locally animated still: the
    scene's own video override names LOCAL_MOVE. Only his production command writes it."""
    from app.media.production_policy import LOCAL_MOVE  # noqa: PLC0415

    chosen: set[int] = set()
    for scene in session.scalars(
        select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
    ):
        overrides = scene.production_overrides_json or {}
        video = overrides.get("video") if isinstance(overrides, dict) else None
        if isinstance(video, dict) and video.get("model_id") == LOCAL_MOVE:
            chosen.add(int(scene.scene_index))
    # The shooting sheet records his per-scene choice as an event (the last one per scene
    # wins); a LOCAL_MOVE chosen there is his choice too.
    from app.media.shooting_sheet import SCENE_MODEL_EVENT  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415

    on_sheet: dict[int, Any] = {}
    for event in session.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.event_type == SCENE_MODEL_EVENT,
            DomainEvent.aggregate_id == storyboard_id,
        )
        .order_by(DomainEvent.sequence)
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if isinstance(payload.get("scene_index"), int):
            on_sheet[int(payload["scene_index"])] = payload.get("model_id")
    chosen |= {index for index, model in on_sheet.items() if model == LOCAL_MOVE}
    return chosen


def cap_local_moves_of(session: Session, storyboard_id: str) -> set[int]:
    """The scenes the Director moved locally past the Owner's renders cap, while the move
    stands (`renders_cap.cap_local_moves`: the scene's motion had its renders and no clip of
    it can carry the scene — his rule of 2026-10-15, the film is published with what it has)."""
    from app.media.renders_cap import cap_local_moves  # noqa: PLC0415 - it reads the assembler

    return cap_local_moves(session, storyboard_id)


def chosen_local_moves(session: Session, storyboard_id: str) -> set[int]:
    """The scenes the film may show as a locally animated still: the Owner's own choices
    (`owner_local_moves`) and the Director's past his renders cap (`cap_local_moves_of`).
    Their union, for a reader that only asks whether a still is allowed; who chose which is
    read from the two apart (`fallback_verdict`)."""
    return owner_local_moves(session, storyboard_id) | cap_local_moves_of(session, storyboard_id)


def fallback_verdict(
    production: dict[str, Any],
    *,
    environment: str,
    owner_choices: set[int],
    cap_choices: set[int] | None = None,
    settings: Any | None = None,
) -> dict[str, Any]:
    """Whether the film's stills are allowed. In PRODUCTION no LIVE scene may be a still
    unless the Owner chose a locally animated still for that very scene (``owner_choices``),
    or the Director moved it locally past his renders cap because no clip of it could carry it
    (``cap_choices``, `renders_cap.cap_local_moves`; his card of 2026-10-16); no setting
    loosens it. The record keeps the two apart: ``owner_chosen`` lists his choices only,
    ``director_cap_chosen`` hers under the cap (the dishonest-code audit of 2026-10-16,
    STUB-004: her moves were listed as his). In TEST stills are the studio's own policy, so
    the old ceiling (the setting, else half the scenes) only warns."""
    recorded = production.get("motion")
    motion: dict[str, Any] = recorded if isinstance(recorded, dict) else {}
    listed_scenes = production.get("scenes")
    scenes = listed_scenes if isinstance(listed_scenes, list) else []
    total = int(motion.get("scenes") or len(scenes) or 0)
    moving = int(motion.get("motion_scenes") or motion.get("clips") or 0)
    listed = live_fallback_scenes(production)
    count = len(listed) if listed is not None else int(motion.get("fallback_scenes") or 0)
    fallbacks = listed or []
    capped = cap_choices or set()
    his = sorted(index for index in fallbacks if index in owner_choices)
    hers = sorted(index for index in fallbacks if index in capped and index not in owner_choices)
    chosen = sorted({*his, *hers})
    unchosen = sorted(index for index in fallbacks if index not in chosen)
    record: dict[str, Any] = {
        "environment": environment,
        "scenes": total,
        "motion_scenes": moving,
        "fallback_scenes": count,
        "live_fallbacks": fallbacks,
        "owner_chosen": his,
        "director_cap_chosen": hers,
        "unchosen": unchosen,
        "warning": None,
        "reason_ro": None,
    }
    if environment == "PRODUCTION":
        record["max_fallback_scenes"] = 0
        unexplained = len(unchosen) if listed is not None else count
        record["passed"] = unexplained == 0
        if unexplained:
            named = ", ".join(f"Scena {index}" for index in unchosen) or (
                f"{unexplained} scene filmate"
            )
            record["reason_ro"] = (
                f"{named}: imagine fixă (fallback) pe care n-a ales-o nimeni. În PRODUCȚIE "
                "nicio scenă filmată nu rămâne imagine fixă decât dacă Proprietarul a ales "
                "„imagine fixă animată local” pentru ea pe foaia de filmare, sau dacă "
                "Directoarea a mutat-o local după plafonul de randări, când niciun clip al ei "
                "nu o poate acoperi."
            )
        return record
    ceiling = getattr(settings, "max_fallback_scenes", None)
    max_fallback = int(ceiling) if isinstance(ceiling, int) and ceiling >= 0 else total // 2
    record["max_fallback_scenes"] = max_fallback
    record["passed"] = True
    if count - len(chosen) > max_fallback:
        record["warning"] = (
            f"{count} of {total} scenes fell back to a slow push because the motion model "
            f"refused; at most {max_fallback} may (fallback ceiling, {environment})"
        )
    return record


def require_chosen_fallbacks(
    engine: Engine,
    storyboard_id: str,
    production: dict[str, Any],
    *,
    environment: str | None = None,
    settings: Any | None = None,
) -> dict[str, Any]:
    """The assembler's gate: raise FallbackNotChosen before a PRODUCTION film is assembled
    with a LIVE scene nobody chose to show as a still: the Owner on the sheet
    (`owner_local_moves`), or the Director past his renders cap (`cap_local_moves_of`), each
    recorded as whose it is. Returns the verdict."""
    with Session(engine) as session:
        his = owner_local_moves(session, storyboard_id)
        hers = cap_local_moves_of(session, storyboard_id)
    verdict = fallback_verdict(
        production,
        environment=environment or studio_environment(engine),
        owner_choices=his,
        cap_choices=hers,
        settings=settings,
    )
    if not verdict["passed"]:
        raise FallbackNotChosen(
            list(verdict["unchosen"]), f"{verdict['reason_ro']} Asamblarea se oprește."
        )
    return verdict


# ---------------------------------------------------------------------- the delivered file


def technical_problems(
    probe: dict[str, Any],
    *,
    environment: str,
    timeline_fps: float,
    narration_seconds: float | None,
    duplicate_share: float | None = None,
    budget: Mapping[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """What keeps the delivered file from the encoder's own spec: (failures, warnings).

    ``budget`` is `film_length_budget`'s reading of the render: the film may last its
    narration, the breaths the timeline planned and its silent cards (each up to its own
    maximum), plus DURATION_OVER_NARRATION_SECONDS; a silent card past its maximum is a floor
    of its own, naming the scene. Without one, the narration alone, as before.

    The format (size, H.264 High, yuv420p, tv range, BT.709 tags, the timeline's fps) is what
    the encoder writes whatever the picture is, so it fails in every environment. The
    delivery floors (bitrate, length against the narration, duplicated frames) depend on the
    picture: a TEST film is drawn from synthetic stand-ins that compress to nothing and is
    voiced by a placeholder, so there they warn; in PRODUCTION they fail.
    """
    failures: list[str] = []
    warnings: list[str] = []
    width, height = int(probe.get("width") or 0), int(probe.get("height") or 0)
    if (width, height) != DELIVERY_SIZE:
        failures.append(f"Rezoluția livrată este {width}x{height}, nu 1080x1920")
    if probe.get("video_codec") != "h264":
        failures.append(f"Codecul video este {probe.get('video_codec')}, nu H.264")
    if probe.get("video_profile") != DELIVERY_PROFILE:
        failures.append(f"Profilul H.264 este {probe.get('video_profile')}, nu High")
    if probe.get("pix_fmt") != DELIVERY_PIX_FMT:
        failures.append(f"Formatul de pixeli este {probe.get('pix_fmt')}, nu yuv420p")
    if probe.get("color_range") != DELIVERY_RANGE:
        failures.append(
            f"Intervalul de culoare este {probe.get('color_range') or 'nedeclarat'}, "
            "nu tv (limitat)"
        )
    for key, label in (
        ("color_space", "matricea"),
        ("color_primaries", "primarele"),
        ("color_transfer", "transferul"),
    ):
        if probe.get(key) != DELIVERY_COLOUR:
            failures.append(
                f"Eticheta de culoare ({label}) este {probe.get(key) or 'nedeclarată'}, nu bt709"
            )
    fps = probe.get("video_fps")
    if not fps or abs(float(fps) - float(timeline_fps)) > 0.01:
        failures.append(
            f"Cadența este {fps if fps else 'necunoscută'} cadre/s, nu {timeline_fps:g} "
            "cât are linia de timp"
        )

    floors: list[str] = []
    rate = probe.get("video_bit_rate")
    if not rate:
        floors.append("Debitul video nu a putut fi măsurat")
    elif rate < MIN_VIDEO_BITRATE:
        floors.append(
            f"Debitul video mediu este {_ro_number(rate / 1e6)} Mbps, sub minimul de 6 Mbps"
        )
    elif rate < WARN_VIDEO_BITRATE:
        warnings.append(
            f"Debitul video mediu este {_ro_number(rate / 1e6)} Mbps, sub cei 8 Mbps recomandați"
        )
    duration = float(probe.get("duration_seconds") or 0.0)
    breaths = float((budget or {}).get("breath_seconds") or 0.0)
    rounded = float((budget or {}).get("frame_rounding_seconds") or 0.0)
    silent = float((budget or {}).get("silent_card_seconds") or 0.0)
    allowed = narration_seconds + breaths + rounded + silent if narration_seconds is not None else 0
    if narration_seconds is None:
        floors.append(
            "Lungimea narațiunii nu este înregistrată; durata filmului nu poate fi judecată"
        )
    elif duration > allowed + DURATION_OVER_NARRATION_SECONDS + 1e-6:
        floors.append(
            f"Filmul durează {_ro_number(duration)} s, mai mult decât narațiunea "
            f"({_ro_number(narration_seconds)} s)"
            + (f", respirațiile dintre scene ({_ro_number(breaths)} s)" if breaths else "")
            + (f", rotunjirea la cadre întregi ({_ro_number(rounded)} s)" if rounded else "")
            + (f", cardurile mute ({_ro_number(silent)} s)" if silent else "")
            + f" plus {_ro_number(DURATION_OVER_NARRATION_SECONDS)} s"
        )
    floors.extend(str(overrun) for overrun in (budget or {}).get("overruns_ro") or [])
    if duplicate_share is not None and duplicate_share >= MAX_DUPLICATE_SHARE:
        floors.append(
            f"{_ro_number(duplicate_share * 100)}% din cadrele scenelor filmate sunt dublate "
            f"(cel mult {_ro_number(MAX_DUPLICATE_SHARE * 100, 0)}%): mișcarea sacadează"
        )
    if environment == "PRODUCTION":
        failures.extend(floors)
    else:
        warnings.extend(floors)
    return failures, warnings


def moving_spans(
    production: dict[str, Any], planned: dict[int, float]
) -> list[tuple[int, float, float]]:
    """(scene, start, end) of the LIVE scenes whose shot is a generated clip, on the film's
    timeline. The render's own spans when it recorded them (production['timeline']['spans']);
    otherwise rebuilt the way the assembler lays scenes end to end: each scene lasts its
    planned seconds or its narration, whichever is longer."""
    timeline = production.get("timeline")
    recorded = timeline.get("spans") if isinstance(timeline, dict) else None
    if isinstance(recorded, list) and recorded:
        return [
            (int(span["scene_index"]), float(span["start"]), float(span["end"]))
            for span in recorded
            if isinstance(span, dict) and span.get("moving")
        ]
    spans: list[tuple[int, float, float]] = []
    clock = 0.0
    for entry in production.get("scenes") or []:
        if not isinstance(entry, dict):
            continue
        index = int(entry.get("scene_index") or 0)
        length = max(float(planned.get(index) or 0.0), float(entry.get("audio_seconds") or 0.0))
        kind = str(entry.get("scene_kind") or "LIVE").upper()
        if kind == "LIVE" and _moved(entry.get("motion")) and length > 0:
            spans.append((index, clock, clock + length))
        clock += length
    return spans


def duplicate_share(
    reading: MotionReading | None, spans: list[tuple[int, float, float]]
) -> float | None:
    """The share of frames inside the spans (away from their edges) that repeat the frame
    before them; None when there is nothing to count."""
    if reading is None or not spans:
        return None
    counted = duplicated = 0
    for value, moment in zip(reading.values[1:], reading.times[1:], strict=False):
        for _index, start, end in spans:
            if start + SPAN_EDGE_SECONDS <= moment <= end - SPAN_EDGE_SECONDS:
                counted += 1
                duplicated += int(value < DUPLICATE_YDIF)
                break
    return duplicated / counted if counted else None


def shot_duplicate_share(
    ffmpeg: str | None,
    production: dict[str, Any],
    film_dir: Path,
    spans: list[tuple[int, float, float]],
) -> float | None:
    """The share of repeated frames inside the moving scenes, read on their lossless shot
    files beside the film (production['shots']); None when any moving scene's shot is not
    there, so the caller falls back to the delivered film."""
    if not ffmpeg or not spans:
        return None
    files: dict[int, Path] = {}
    for record in production.get("shots") or []:
        if isinstance(record, dict) and record.get("file"):
            files[int(record.get("scene_index") or 0)] = film_dir / str(record["file"])
    counted = duplicated = 0
    for index, _start, _end in spans:
        shot = files.get(int(index))
        if shot is None or not shot.is_file():
            return None
        reading = measure_motion(ffmpeg, shot)
        if reading is None:
            return None
        last = reading.times[-1] if reading.times else 0.0
        for value, moment in zip(reading.values[1:], reading.times[1:], strict=False):
            if SPAN_EDGE_SECONDS <= moment - reading.times[0] <= last - SPAN_EDGE_SECONDS:
                counted += 1
                duplicated += int(value < LOSSLESS_DUPLICATE_YDIF)
    return duplicated / counted if counted else None


def narration_seconds_of(production: dict[str, Any]) -> float | None:
    """How long the narration is, from the render's per-scene record; None when any scene
    did not record it."""
    scenes = production.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return None
    total = 0.0
    for entry in scenes:
        seconds = entry.get("audio_seconds") if isinstance(entry, dict) else None
        if not isinstance(seconds, int | float):
            return None
        total += float(seconds)
    return total


# --------------------------------------------------------- the film's length, scene by scene


def _seconds(value: Any) -> float | None:
    """A recorded length, or None when it was not recorded (a bool is not a length)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _kind(value: Any) -> str:
    kind = str(value or "LIVE").upper()
    return kind if kind in COMPOSED_KINDS else "LIVE"


def timeline_spans(
    production: dict[str, Any], planned: Mapping[int, float] | None = None
) -> list[dict[str, Any]]:
    """Every scene's place on the film's timeline, with its kind and its words.

    The render's own spans when it recorded them (production['timeline']['spans']); a span
    that names its kind (``kind``) or its words (``spoken_seconds``) is read as it says,
    otherwise the render's per-scene record says them. A render from before the timeline
    record is rebuilt the way it was laid out: each scene its plan or its words, whichever is
    longer, end to end. Each item: scene_index, start, end, seconds, kind, composed, moving,
    dissolve_seconds (the join into this scene) and spoken (None when not recorded).
    """
    entries: dict[int, dict[str, Any]] = {}
    for entry in production.get("scenes") or []:
        if isinstance(entry, dict):
            try:
                entries[int(entry.get("scene_index") or 0)] = entry
            except (TypeError, ValueError):
                continue
    timeline = production.get("timeline")
    recorded = timeline.get("spans") if isinstance(timeline, dict) else None
    out: list[dict[str, Any]] = []
    if isinstance(recorded, list) and recorded:
        for span in recorded:
            if not isinstance(span, dict):
                continue
            try:
                index = int(span["scene_index"])
                start, end = float(span["start"]), float(span["end"])
            except (KeyError, TypeError, ValueError):
                continue
            entry = entries.get(index, {})
            kind = _kind(span.get("kind") or span.get("scene_kind") or entry.get("scene_kind"))
            spoken = _seconds(span.get("spoken_seconds", entry.get("audio_seconds")))
            out.append(
                {
                    "scene_index": index,
                    "start": start,
                    "end": end,
                    "seconds": max(0.0, end - start),
                    "kind": kind,
                    "composed": bool(span.get("composed")) or kind in COMPOSED_KINDS,
                    "moving": bool(span.get("moving")),
                    "dissolve_seconds": float(span.get("dissolve_seconds") or 0.0),
                    "spoken": spoken,
                }
            )
        return out
    clock = 0.0
    for index, entry in entries.items():
        spoken = _seconds(entry.get("audio_seconds"))
        length = max(float((planned or {}).get(index) or 0.0), spoken or 0.0)
        kind = _kind(entry.get("scene_kind"))
        out.append(
            {
                "scene_index": index,
                "start": clock,
                "end": clock + length,
                "seconds": length,
                "kind": kind,
                "composed": kind in COMPOSED_KINDS,
                "moving": kind == "LIVE" and _moved(entry.get("motion")),
                "dissolve_seconds": 0.0,
                "spoken": spoken,
            }
        )
        clock += length
    return out


def _recorded_pads(timeline: Any) -> dict[int, float] | None:
    """Per scene, the silence the render added after its words and between its own takes
    (``spans[].pause``: ``pad`` and each inner ``pad``), for a film timed by its frozen
    pauses; None for a film recorded before them."""
    spans = timeline.get("spans") if isinstance(timeline, dict) else None
    if not isinstance(spans, list) or not spans:
        return None
    found: dict[int, float] = {}
    for span in spans:
        pause = span.get("pause") if isinstance(span, dict) else None
        if not isinstance(pause, dict):
            return None
        added = _seconds(pause.get("pad")) or 0.0
        for inner in pause.get("inner") or []:
            if isinstance(inner, dict):
                added += _seconds(inner.get("pad")) or 0.0
        try:
            found[int(span["scene_index"])] = round(added, 4)
        except (KeyError, TypeError, ValueError):
            return None
    return found


def film_length_budget(
    production: dict[str, Any], planned: Mapping[int, float] | None = None
) -> dict[str, Any]:
    """What the film may last beyond its words, read from the render's own record.

    - the narration: every scene's recorded words (narration_seconds_of);
    - the breaths: the breath the timeline plans after each speaking scene's words
      (production['timeline']['spoken_tail_seconds'], else BREATH_SECONDS);
    - the frame rounding: the timeline rounds each speaking scene's words and breath UP to a
      whole frame (`assembler.scene_spans`), so each may run up to one frame past them. It is
      read from the recorded spans (what each span ran past its words and its breath, at most
      one frame of the timeline's fps), so a span that kept a longer plan is still film over
      the narration. Before the montage a film had 6-12 speaking scenes and the rounding fitted
      inside the 1.0 s; a film of 40-56 shots rounds about 1 s on its own (2026-10-16);
    - the silent cards: a composed scene (BLACK, TITLE_CARD, DATA_CARD) with no words is a
      deliberate silence, allowed up to its kind's MAX_SILENT_CARD_SECONDS. A longer one is
      allowed only up to that maximum and is named in ``overruns_ro``. A silent LIVE scene is
      not a card: its length counts against the narration as it always did.

    ``allowed_seconds`` adds DURATION_OVER_NARRATION_SECONDS; None when the narration was not
    recorded, which technical QC reports on its own.
    """
    narration = narration_seconds_of(production)
    spans = timeline_spans(production, planned)
    timeline = production.get("timeline")
    recorded_tail = (
        _seconds(timeline.get("spoken_tail_seconds")) if isinstance(timeline, dict) else None
    )
    breath = recorded_tail if recorded_tail is not None and recorded_tail >= 0 else BREATH_SECONDS
    # A film timed by its frozen pauses («pauza vocii», 2026-10-16) recorded, per scene, the
    # silence the render added after its words (``pause.pad``, and between its own takes):
    # each speaking scene's breath is that, never a constant.
    pads = _recorded_pads(timeline)
    speaking = sum(
        1
        for span in spans
        if span["spoken"] is not None and span["spoken"] >= SILENT_SPOKEN_SECONDS
    )
    recorded_fps = _seconds(timeline.get("fps")) if isinstance(timeline, dict) else None
    frame = 1.0 / (recorded_fps if recorded_fps and recorded_fps > 0 else DEFAULT_TIMELINE_FPS)
    recorded_spans = isinstance(timeline, dict) and bool(timeline.get("spans"))
    rounding = 0.0
    if recorded_spans:
        for span in spans:
            spoken = span["spoken"]
            if spoken is None or spoken < SILENT_SPOKEN_SECONDS:
                continue
            tail = pads.get(int(span["scene_index"]), breath) if pads is not None else breath
            rounding += min(frame, max(0.0, float(span["seconds"]) - spoken - tail))
    silent_cards: list[dict[str, Any]] = []
    overruns: list[str] = []
    allowance = 0.0
    for span in spans:
        spoken = span["spoken"]
        if span["kind"] not in COMPOSED_KINDS or spoken is None or spoken >= SILENT_SPOKEN_SECONDS:
            continue
        seconds = round(float(span["seconds"]), 3)
        maximum = MAX_SILENT_CARD_SECONDS[span["kind"]]
        within = seconds <= maximum + 1e-6
        allowance += min(seconds, maximum)
        silent_cards.append(
            {
                "scene_index": span["scene_index"],
                "kind": span["kind"],
                "seconds": seconds,
                "max_seconds": maximum,
                "within": within,
            }
        )
        if not within:
            word = _CARD_WORDS_RO[span["kind"]]
            overruns.append(
                f"Scena {span['scene_index']} ({word}) tace {_ro_number(seconds)} s, peste "
                f"maximul de {_ro_number(maximum)} s al unui {word} fără narațiune"
            )
    breaths = round(breath * speaking, 3)
    if pads is not None:
        breaths = round(
            sum(
                pads.get(int(span["scene_index"]), 0.0)
                for span in spans
                if span["spoken"] is not None and span["spoken"] >= SILENT_SPOKEN_SECONDS
            ),
            3,
        )
    silent = round(allowance, 3)
    rounded = round(rounding, 3)
    return {
        "narration_seconds": round(narration, 3) if narration is not None else None,
        "speaking_scenes": speaking,
        "breath_per_scene": breath,
        "breath_seconds": breaths,
        "frame_rounding_seconds": rounded,
        "silent_cards": silent_cards,
        "silent_card_seconds": silent,
        "over_seconds": DURATION_OVER_NARRATION_SECONDS,
        "allowed_seconds": (
            round(narration + breaths + rounded + silent + DURATION_OVER_NARRATION_SECONDS, 3)
            if narration is not None
            else None
        ),
        "overruns_ro": overruns,
    }


# ------------------------------------------------- the film's pictures, three frames a scene
#
# The film-level look in picture_qc is one 480 px frame from the middle of each scene. Here
# each filmed scene is judged as a bought clip is (picture_qc.judge_clip): the first frame
# after its own dissolve in, the middle and the last frame of its span on the film's own
# timeline, at the delivered 1080 px, with YuNet counting faces on each frame when the bible
# forbids faces and the flat-band reading (`flat_band`) on each frame: a scene made of panels
# fails here, and the Owner's report (`qc_report.redo_proposals`, which reads a failed scene of
# this check as a picture to redo) asks for a new still and new motion for it. The band is
# read even when no model can look (the rehearsal's QC runs without a registry). A composed
# card is drawn by the studio, carries text by design and is never judged as a photograph.
#
# The picture is judged, never the studio's own subtitles over it (2026-10-10, film babcf272:
# the look read the burnt-in captions as «text or a logo» in every scene, the film failed, and
# the repair retired the takes the Owner had approved). A scene's frames are cut from its own
# shot beside the film while that is still the file the film was joined from
# (`picture_qc.clean_shots`): the same moments, before the captions were burnt in. Where the
# shot is gone the film's frames are cut as before. Where a subtitle is on screen at them, the
# look is shown each with only the rows the captions draw in cut out
# (`picture_qc.cut_caption_rows`): the picture above them, then the strip below them, because
# the first crop of the same day cut away everything from row 1320 down and a watermark in the
# bottom corner of the picture passed unseen (adversarial review). Where none is on screen (a
# scene without words, by the SRT's cues) the frames are shown whole. The faces and the band
# are read on the uncut frame, as they always were. The look is told which it was given and
# that the subtitles are the studio's (`picture_qc.StudioText`).

#: Which frames of a span are looked at.
SPAN_FRAME_POSITIONS = ("first", "middle", "last")

#: The assembler records timeline seconds rounded to six decimal places. The resulting
#: uncertainty is in seconds, not frames, and two rounded times can be added at a dissolve.
TIMELINE_TIME_PRECISION_SECONDS = 1e-6


def _timeline_frame_ceiling(seconds: float, fps: float, *, rounded_times: int = 1) -> int:
    frames = seconds * fps
    nearest = round(frames)
    uncertainty = fps * TIMELINE_TIME_PRECISION_SECONDS * rounded_times / 2 + 4 * math.ulp(frames)
    if abs(frames - nearest) <= uncertainty:
        return nearest
    return math.ceil(frames)


def span_frame_numbers(
    start: float, end: float, fps: float, dissolve_in: float = 0.0
) -> list[tuple[str, int]]:
    """The first, middle and last frame of a span on a ``fps`` timeline, by number.

    The first is the first whole frame once the dissolve into the scene (if any) has ended,
    so it is the scene's own picture and not a mix; the last is the frame before the span
    ends (a dissolve out of the scene happens inside the next scene's span)."""
    dissolve = max(0.0, dissolve_in)
    first = max(
        0, _timeline_frame_ceiling(start + dissolve, fps, rounded_times=2 if dissolve else 1)
    )
    last = max(first, _timeline_frame_ceiling(end, fps) - 1)
    middle = (first + last + 1) // 2
    return list(zip(SPAN_FRAME_POSITIONS, (first, middle, last), strict=True))


def _bible_rules(bible: Mapping[str, Any]) -> tuple[str, ...]:
    """The bible's rules as the clip judge is shown them (the stills step's own reading)."""
    rules: list[str] = []
    for key in ("continuity_rules", "rules", "people_rule"):
        value = bible.get(key)
        if isinstance(value, str) and value.strip():
            rules.append(value.strip())
        elif isinstance(value, list | tuple):
            rules += [str(item).strip() for item in value if str(item).strip()]
    return tuple(dict.fromkeys(rules))


def _film_subtitles(production: Mapping[str, Any], film_dir: Path) -> list[dict[str, Any]]:
    """The cues of the captions burnt into the film (the SRT beside it, which says the same
    words as its ASS script), or none when they cannot be read: the look is then told the
    subtitles repeat the narration, without the words."""
    record = production.get("captions")
    named = record.get("srt") if isinstance(record, Mapping) else None
    srt = film_dir / Path(str(named or "captions.srt")).name
    try:
        return parse_srt(srt.read_text(encoding="utf-8")) if srt.is_file() else []
    except (OSError, UnicodeDecodeError, ValueError):
        return []


def _span_subtitles(cues: list[dict[str, Any]], start: float, end: float) -> tuple[str, ...]:
    """The subtitle lines on screen at any moment of [start, end) on the film's timeline."""
    lines: list[str] = []
    for cue in cues:
        if float(cue["end"]) > start and float(cue["start"]) < end:
            lines += [str(line) for line in cue["lines"] if str(line).strip()]
    return tuple(lines[:MAX_SUBTITLE_LINES])


def _captions_on_frames(cues: list[dict[str, Any]], moments: list[float], fps: float) -> bool:
    """Whether any of the film's subtitles is on screen at one of these moments (seconds on the
    film's timeline), give or take a frame for the SRT's milliseconds and the ASS script's
    centiseconds, which round the same cue apart. No cues read (the SRT beside the film is gone
    or unreadable, though the film burnt captions) is a yes: what cannot be read is cut out."""
    if not cues:
        return True
    slack = 1.0 / fps if fps > 0 else 0.05
    return any(
        float(cue["start"]) - slack <= moment < float(cue["end"]) + slack
        for cue in cues
        for moment in moments
    )


def _shot_span_frames(
    shot: CleanShot,
    chosen: list[tuple[str, int]],
    start: float,
    fps: float,
    ffmpeg_path: str | None,
    folder: Path,
) -> list[tuple[str, float, Path]]:
    """The chosen film frames (first, middle, last) cut from the scene's own shot instead:
    (at, time on the film, path). The shot starts where the scene starts on the film's timeline
    (assembler._dissolve_command: shot N always starts where scene N's words start), so a film
    frame is the shot's frame at the same distance from the scene's start, the frames the
    viewer sees without the captions laid over them. Empty when any cannot be cut; the caller
    then cuts the film's own."""
    rate = shot.fps or fps
    last = max(0, round(shot.span * rate) - 1) if shot.span > 0 else None
    numbers: dict[str, int] = {}
    for at, number in chosen:
        within = max(0, round((number / fps - start) * rate))
        numbers[at] = min(within, last) if last is not None else within
    cut = frames_at(
        str(shot.path),
        ffmpeg_path,
        list(numbers.values()),
        folder / f"shot_{shot.scene_index:02d}",
    )
    frames: list[tuple[str, float, Path]] = []
    for at, number in chosen:
        source = cut.get(numbers[at])
        if source is None:
            return []
        named = folder / f"scene_{shot.scene_index:02d}_{at}.png"
        shutil.copyfile(source, named)
        frames.append((at, round(number / fps, 3), named))
    return frames


def span_picture_qc(
    engine: Engine,
    registry: Any | None,
    media_asset_id: str,
    correlation_id: str,
    *,
    ffmpeg_path: str | None = None,
    judge: Callable[[list[Path], Any], Any] | None = None,
    face_counter: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Look at every filmed scene of one finished film on three frames of its span.

    ``judge`` takes the three frame paths and the scene's StillPlan and returns a
    picture_qc.ClipJudgement; by default judge_clip bound to ``registry`` (one vision call per
    scene), and none without a registry. ``face_counter`` is YuNet unless a test passes its own.

    A scene fails when the look refuses it (more than one picture among its reasons), YuNet
    finds a face the bible forbids or a frame is split by a flat band (every environment), or
    when the face count could not run on a bible that forbids faces (PRODUCTION; a warning in
    TEST). A look or a band reading that did not happen certifies nothing: the scene is
    ``passed`` None and adds no failure. ``passed`` is True only when every filmed scene was
    looked at and passed. With no one to look the frames are still cut and the band read (it
    costs nothing): a scene split by a band fails, every other scene is NOT_RUN. With no film
    on disk, or no filmed scene, nothing is cut and the check is NOT_APPLICABLE with the
    reason.

    Each scene's ``frames_from`` says what was judged (2026-10-10, babcf272): SHOT, the scene's
    own shot beside the film before the captions were burnt in (faces, band and look all read
    it); FILM_CROPPED, the film's frames under a subtitle, the look shown each with the rows the
    captions draw in cut out, the picture above them and then the strip below them;
    FILM_CLEAR, the film's frames shown whole, no subtitle being on screen at them; FILM, the
    film's frames as they are (no captions burnt in, nobody to look, or the cut failed). The
    look is told which, and that the narration's subtitles are the studio's own. A ``judge``
    passed in is handed the three frames alone (above the caption rows, on FILM_CROPPED).

    Approved stays approved (2026-10-12, aa170155; `picture_qc.carried_forward`): a scene whose
    picture is exactly that of an earlier film whose span look passed it (the same carry key:
    takes, this look's version, the bible and look, the span and speed), or whose findings of
    this look the Director settled on the same takes, is not shown to the look again; its
    verdict is carried with where it came from. Only the look is carried (the review of that
    change): its frames are still cut and YuNet and the flat band still read them, for free.
    """
    from app.media.still_gate import StillPlan  # noqa: PLC0415 - still_gate imports this module

    record: dict[str, Any] = {
        "template_version": CLIP_TEMPLATE_VERSION,
        "status": "NOT_APPLICABLE",
        "passed": None,
        "detail": None,
        "frame_width": SPAN_FRAME_WIDTH,
        "faces_forbidden": False,
        "scenes": [],
        "failures": [],
        "warnings": [],
    }

    def stood_down(detail: str) -> dict[str, Any]:
        record["detail"] = detail
        return record

    environment = studio_environment(engine)
    with Session(engine) as session:
        asset = session.get(MediaAsset, media_asset_id)
        if asset is None:
            return stood_down("materialul nu există")
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
        )
        if job is None:
            return stood_down("filmul nu are o randare în spate: nu se știe unde stă fiecare scenă")
        production: dict[str, Any] = (
            job.production_json if isinstance(job.production_json, dict) else {}
        )
        board = session.get(Storyboard, job.storyboard_id)
        bible: dict[str, Any] = (
            board.visual_bible_json
            if board is not None and isinstance(board.visual_bible_json, dict)
            else {}
        )
        rows: dict[int, dict[str, Any]] = {}
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == job.storyboard_id)
        ):
            package = row.prompt_json if isinstance(row.prompt_json, dict) else {}
            rows[int(row.scene_index)] = {
                "planned": float(row.duration_seconds or 0.0),
                **film_scene_prompts(session, production, row),
                "camera_move": str(package.get("camera_move") or ""),
                "look_block": str(package.get("look_block") or ""),
            }
        film_path = str(asset.uri_or_path or "")
        # Approved stays approved (2026-10-12, aa170155, `picture_qc.carried_forward`): a scene
        # whose picture an earlier film's span look passed, or the Director settled, is not
        # shown to the look again. Its frames are still cut and read by YuNet and the band.
        keys = carry_keys(
            production,
            "picture_spans_qc",
            bible=bible,
            looks={index: row["look_block"] for index, row in rows.items()},
            planned={index: row["planned"] for index, row in rows.items()},
        )
        carried = carried_forward(session, job.storyboard_id, production, "picture_spans_qc", keys)

    faces_forbidden = bible_face_rule(bible) is not None
    record["faces_forbidden"] = faces_forbidden
    #: What the studio wrote over each scene's frames, filled in as the frames are cut; the
    #: studio's own look reads it when it is asked (a test's judge is handed the frames alone).
    studio_texts: dict[int, StudioText] = {}
    if judge is None and registry is not None:

        def judge(paths: list[Path], plan: Any) -> Any:
            return judge_clip(
                engine,
                registry,
                paths,
                plan,
                correlation_id,
                motion_prompt=rows.get(int(plan.scene), {}).get("motion_prompt", ""),
                ending_frame=rows.get(int(plan.scene), {}).get("ending_frame", ""),
                prompt_sources=rows.get(int(plan.scene), {}).get("prompt_sources"),
                ffmpeg_path=ffmpeg_path,
                studio_text=studio_texts.get(int(plan.scene)),
            )

    # With nobody to look (no model that can see, or no registry: the rehearsal's QC and the
    # Owner's re-QC) the frames are cut all the same: the flat band is free, and until the
    # review of 2026-10-09 this stood down here whenever the bible allowed faces, so a film
    # with the triptych in it passed its QC unread.
    if not Path(film_path).is_file():
        return stood_down("filmul nu este pe disc: nu are ce cadre să se taie")
    spans = timeline_spans(production, {index: row["planned"] for index, row in rows.items()})
    if not any(not span["composed"] for span in spans):
        return stood_down(
            "filmul nu are scene filmate: cardurile compuse nu se judecă drept fotografii"
        )
    timeline = production.get("timeline")
    fps = float(
        (timeline.get("fps") if isinstance(timeline, dict) else None)
        or production.get("fps")
        or DEFAULT_TIMELINE_FPS
    )
    # Every filmed scene's frames are cut, a carried one's too: YuNet and the band are free
    # and read the frame itself (the review of 2026-10-12: they were skipped on carried scenes).
    picks = {
        span["scene_index"]: span_frame_numbers(
            span["start"], span["end"], fps, span["dissolve_seconds"]
        )
        for span in spans
        if not span["composed"]
    }
    if face_counter is None:
        from app.media.faces import count_faces  # noqa: PLC0415 - opencv loads lazily

        face_counter = count_faces
    rules = _bible_rules(bible)
    band_reader = find_ffmpeg(ffmpeg_path)
    film_dir = Path(film_path).parent
    shots = clean_shots(production, film_dir)
    burned, headline = film_captions(production)
    rows_burnt = caption_rows(production)
    cues = _film_subtitles(production, film_dir) if burned else []
    starts = {span["scene_index"]: float(span["start"]) for span in spans}
    folder = Path(tempfile.mkdtemp(prefix="span_qc_"))
    measured_any = False
    try:
        # The scenes whose own shot is beside the film are cut from it; the film is decoded
        # once, for the others only.
        clean: dict[int, list[tuple[str, float, Path]]] = {}
        for index, chosen in picks.items():
            shot = shots.get(index)
            if shot is not None:
                taken = _shot_span_frames(
                    shot, chosen, starts[index], fps, ffmpeg_path, folder / "shots"
                )
                if taken:
                    clean[index] = taken
        cut = frames_at(
            film_path,
            ffmpeg_path,
            [n for index, chosen in picks.items() if index not in clean for _at, n in chosen],
            folder / "cut",
        )
        for span in spans:
            index = span["scene_index"]
            entry: dict[str, Any] = {
                "scene_index": index,
                "kind": span["kind"],
                "start": round(span["start"], 3),
                "end": round(span["end"], 3),
                "status": "NOT_APPLICABLE",
                "passed": None,
                "frames": [],
                "faces": None,
                "picture": None,
                "reason": None,
            }
            record["scenes"].append(entry)
            if span["composed"]:
                entry["reason"] = "card compus de studio: nu se judecă drept fotografie"
                continue
            # What a later film with the same picture must match to keep this verdict.
            entry["carry_key"] = keys.get(index)
            earlier = carried.get(index)
            if earlier is not None:
                entry["carried_from"] = earlier.as_dict()
            frames: list[tuple[str, float, Path]] = clean.get(index, [])
            source: FrameSource = "SHOT" if frames else "FILM"
            if not frames:
                for at, number in picks[index]:
                    cut_frame = cut.get(number)
                    if cut_frame is None:
                        frames = []
                        break
                    named = folder / f"scene_{index:02d}_{at}.png"
                    shutil.copyfile(cut_frame, named)
                    frames.append((at, round(number / fps, 3), named))
            # What the look is shown: the scene's own shot as it is; or the film's frames with
            # only the rows its captions draw in cut out, the strips below them after the
            # frames (2026-10-10, babcf272, and the review of the first crop the same day,
            # which hid the bottom 600 rows); or, where no subtitle is on screen at them, the
            # film's frames whole. The faces and the flat band are read on the uncut frames,
            # as they always were: a cut could take a face or a blank strip out of their sight.
            looked_at = frames
            strips: tuple[Path, ...] = ()
            if (
                source == "FILM"
                and frames
                and rows_burnt is not None
                and judge is not None
                and earlier is None
            ):
                if not _captions_on_frames(cues, [moment for _at, moment, _p in frames], fps):
                    source = "FILM_CLEAR"
                else:
                    pieces = [
                        cut_caption_rows(
                            band_reader,
                            path,
                            rows_burnt,
                            folder / f"scene_{index:02d}_{at}_deasupra.png",
                            folder / f"scene_{index:02d}_{at}_dedesubt.png",
                        )
                        for at, _moment, path in frames
                    ]
                    cut_apart = [piece for piece in pieces if piece is not None]
                    if len(cut_apart) == len(frames):
                        looked_at = [
                            (at, moment, above)
                            for (at, moment, _uncut), (above, _below) in zip(
                                frames, cut_apart, strict=True
                            )
                        ]
                        strips = tuple(below for _above, below in cut_apart)
                        source = "FILM_CROPPED"
            studio_texts[index] = StudioText(
                source=source,
                captions_burned_in=burned,
                # FILM_CLEAR frames carry none: words listed would only invite an excuse for
                # the picture's own lettering.
                subtitles=(
                    ()
                    if source == "FILM_CLEAR"
                    else _span_subtitles(cues, float(span["start"]), float(span["end"]))
                ),
                headline=headline,
                below_captions=strips,
            )
            entry["frames_from"] = source if frames else None
            entry["frames"] = [
                {"at": at, "time": round(number / fps, 3), "frame": number}
                for at, number in picks[index]
                if frames
            ]
            measured: dict[str, Any] = {}
            faces = _faces_check(
                frames, face_counter, faces_forbidden=faces_forbidden, measured=measured
            )
            judgement = None
            if earlier is not None:
                # Only the look is carried: what it said of this very picture before.
                picture = ClipCheck("picture", "PASSED", False, None, earlier.note_ro)
            else:
                if judge is not None and frames:
                    asked = rows.get(index, {})
                    plan = StillPlan(
                        scene=index,
                        still_prompt=str(asked.get("still_prompt") or ""),
                        camera_move=str(asked.get("camera_move") or ""),
                        faces_forbidden=faces_forbidden,
                        bible_rules=rules,
                        look_block=str(asked.get("look_block") or ""),
                        # A thermometer's scale is not writing (2026-10-13): the look is
                        # told, and her second look at the scene may overturn the reading.
                        expected_markings=planned_markings(asked.get("still_prompt")),
                    )
                    judgement = judge([path for _at, _moment, path in looked_at], plan)
                picture = _picture_check(judgement, faces_forbidden=faces_forbidden)
            # The same flat-band reading as the still's and the clip's: the scene's frames
            # are one picture each, or the scene is panels (2026-10-09, scene 5).
            panels = _panels_check(band_reader, frames, measured=measured)
            entry["faces"] = {
                "status": faces.status,
                "detail_ro": faces.detail_ro,
                **(measured.get("faces") or {}),
            }
            entry["picture"] = (
                {"status": CARRIED_STATUS, "detail_ro": earlier.note_ro}
                if earlier is not None
                else {
                    "status": picture.status,
                    "detail_ro": picture.detail_ro,
                    "run_id": getattr(judgement, "run_id", None),
                    "looked_by": getattr(judgement, "looked_by", None),
                }
            )
            entry["panels"] = {
                "status": panels.status,
                "detail_ro": panels.detail_ro,
                **(measured.get("panels") or {}),
            }
            problems: list[str] = []
            if faces.status == "FAILED":
                problems.append(faces.detail_ro)
            elif faces.status == "NOT_RUN" and faces_forbidden:
                if environment == "PRODUCTION":
                    problems.append(faces.detail_ro)
                else:
                    record["warnings"].append(f"Scena {index}: {faces.detail_ro}")
            if panels.status == "FAILED":
                problems.append(panels.detail_ro)
            if picture.status == "FAILED":
                problems.append(picture.detail_ro)
            # A carried look measured nothing today; the faces and the band did, if they ran.
            today = (faces, panels) if earlier is not None else (faces, picture, panels)
            if any(item.status in ("PASSED", "FAILED") for item in today):
                measured_any = True
            if problems:
                entry.update(status="FAILED", passed=False, reason="; ".join(problems))
                record["failures"] += [f"Scena {index}: {problem}" for problem in problems]
            elif (
                picture.status == "PASSED"
                and panels.status == "PASSED"
                and faces.status in ("PASSED", "NOT_APPLICABLE")
            ):
                entry.update(status="PASSED", passed=True, reason=picture.detail_ro)
            else:
                unmeasured = next(
                    (item for item in (picture, faces, panels) if item.status == "NOT_RUN"),
                    picture,
                )
                entry.update(status="NOT_RUN", reason=unmeasured.detail_ro)
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    filmed = [entry for entry in record["scenes"] if entry["kind"] not in COMPOSED_KINDS]
    if any(entry["passed"] is False for entry in filmed):
        record["passed"] = False
    elif filmed and all(entry["passed"] is True for entry in filmed):
        record["passed"] = True
    kept = sorted(entry["scene_index"] for entry in filmed if entry.get("carried_from"))
    record["carried_scenes"] = kept
    record["status"] = "MEASURED" if measured_any else "NOT_RUN" if filmed else "NOT_APPLICABLE"
    sources = [entry.get("frames_from") for entry in filmed]
    record["frames_from"] = {name: sources.count(name) for name in FRAME_SOURCES if name in sources}
    carried_words = (
        f"; {len(kept)} {'trecută' if len(kept) == 1 else 'trecute'} la un control anterior cu "
        f"aceleași preluări (sau acceptate de Directoare), "
        f"{'neprivită' if len(kept) == 1 else 'neprivite'} din nou de model, dar citite de "
        "YuNet și de banda plată"
        if kept
        else ""
    )
    if judge is None:
        read = sum(
            1
            for entry in filmed
            if (entry.get("panels") or {}).get("status") in ("PASSED", "FAILED")
        )
        record["detail"] = (
            "nimeni nu se uită la cadre (niciun model care vede nu este înregistrat); banda "
            f"plată a fost citită pe {read} din {len(filmed)} scene filmate, pe primul, "
            "mijlocul și ultimul cadru"
            + (", iar fețele au fost numărate de YuNet" if faces_forbidden else "")
            + carried_words
        )
        return record
    looked = sum(
        1
        for entry in filmed
        if (entry.get("picture") or {}).get("status") in ("PASSED", "FAILED")
        and not entry.get("carried_from")
    )
    # Where the frames the look saw came from, in the Owner's words (2026-10-10, babcf272: the
    # look had been shown the studio's own subtitles and nobody could tell from the report).
    where = {
        "SHOT": "pe cadrul scenei, dinainte de subtitrări",
        "FILM_CROPPED": "pe film, cu rândurile subtitrărilor scoase și restul cadrului întreg",
        "FILM_CLEAR": "pe film, în clipe fără subtitrări pe ecran",
        "FILM": (
            "pe film, cu subtitrările numite modelului ca ale studioului" if burned else "pe film"
        ),
    }
    record["detail"] = (
        f"{looked} din {len(filmed)} scene filmate privite pe primul, mijlocul și ultimul cadru "
        f"la {SPAN_FRAME_WIDTH} px"
        + "".join(f"; {count} {where[name]}" for name, count in record["frames_from"].items())
        + carried_words
    )
    return record


# --------------------------------------------------------------------------- editorial QC
# Audit Q10 (2026-10-02). Every check above is technical, factual or about a picture; none of
# them sees the editing. The zero-credit Nepal rehearsal had five dead-air gaps, ended on 4.3 s
# of near-black (freezedetect 20.29-27.875 s), cut every 4.65 s and broke its captions in the
# middle of phrases, and it would have passed. These measure that, from the delivered file and
# the voice track beside it. They are advisory (they name the fault and refuse nothing) until
# the Owner makes them blocking: settings.editorial_qc_blocking, else the look file's
# finish.editorial_qc_blocking.

#: The picture is read at this width: enough for luma levels, motion and cuts, and quick.
EDITORIAL_WIDTH = 270
#: The longest silence allowed inside the narration, measured at -45 dB on the voice track,
#: beyond the pause the timeline planned there: since 2026-10-16 every shot keeps a 0.4 s
#: breath after its words (`assembler.LEGACY_SPOKEN_TAIL_SECONDS`), and the silence at a cut is
#: that breath plus the takes' kept edges and a frame of rounding; only what runs past the
#: recorded breath is dead air (`_planned_pauses`).
MAX_NARRATION_SILENCE_SECONDS = 0.25
#: How far from a recorded span boundary a measured silence may sit and still be that
#: boundary's breath: the detector's own resolution and a kept edge of the next take.
PAUSE_BOUNDARY_TOLERANCE_SECONDS = 0.1
NARRATION_SILENCE_DB = -45.0
#: The last seconds of the film, and how long the picture may be black or frozen inside them.
END_WINDOW_SECONDS = 3.0
MAX_END_STILL_SECONDS = 1.5
#: Black in limited range: Y 16 is black, and a caption over black still reads at most 18.
BLACK_YAVG = 18.0
#: A frame whose mean difference from the one before is under this (8-bit, at 270 px) did
#: not move.
FROZEN_YDIF = 0.1
#: The longest average shot a short may have with the montage off, and what counts as a cut
#: (scdet, percent). With the montage on the limit follows its shots (`average_shot_limit`).
MAX_AVERAGE_SHOT_SECONDS = 3.5
#: How far past ``montage_shot_seconds`` of words a montage shot may run: a scene is cut only
#: when its words reach one and a half shots (`montage.shot_count` rounds), so an uncut scene
#: runs up to half a shot longer. The Owner's 160 s short at the brief's own 13-14 words a
#: scene is 28 shots of about 5.8 s, which the 3.5 s limit named on every film (2026-10-16).
MONTAGE_SHOT_TOLERANCE = 0.5
CUT_SCORE_PERCENT = 15.0
#: The picture must move inside the first half-second: the first frame decides the swipe.
OPENING_SECONDS = 0.5
MIN_OPENING_YDIF = 0.1
#: A shot whose colour sits this far from the hero (Delta E 1976) after the grade stands out.
GRADE_OUTLIER_DELTA_E = 25.0


@dataclass(frozen=True)
class PictureTrace:
    """Per-frame luma mean and difference, and the cuts scdet found, of one film."""

    times: list[float]
    yavg: list[float]
    ydif: list[float]
    cuts: list[float]
    duration: float
    #: scdet's score per frame (percent): how much each frame changed against the one before.
    scores: list[float] = field(default_factory=list)


def picture_trace(ffmpeg: str | None, film: Path | str) -> PictureTrace | None:
    """One pass over the film at EDITORIAL_WIDTH: signalstats and scdet per frame. None when
    the film cannot be read: nothing is assumed about a picture nobody measured."""
    if not ffmpeg or not Path(film).is_file():
        return None
    result = _ffmpeg_run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-threads",
            "2",
            "-i",
            str(film),
            "-an",
            "-vf",
            f"scale={EDITORIAL_WIDTH}:-2:flags=bilinear,format=yuv420p,signalstats,"
            f"scdet=threshold={CUT_SCORE_PERCENT:g},metadata=print:file=-",
            "-f",
            "null",
            "-",
        ]
    )
    if result is None or result.returncode != 0:
        return None
    times: list[float] = []
    yavg: list[float] = []
    ydif: list[float] = []
    cuts: list[float] = []
    scores: list[float] = []
    for line in (result.stdout or "").splitlines():
        stamp = re.search(r"pts_time:\s*([-0-9.]+)", line)
        if stamp:
            times.append(float(stamp.group(1)))
            yavg.append(0.0)
            ydif.append(0.0)
            scores.append(0.0)
            continue
        if not times:
            continue
        key, _, value = line.strip().partition("=")
        try:
            number = float(value)
        except ValueError:
            continue
        if key == "lavfi.signalstats.YAVG":
            yavg[-1] = number
        elif key == "lavfi.signalstats.YDIF":
            ydif[-1] = number
        elif key == "lavfi.scd.score":
            scores[-1] = number
        elif key == "lavfi.scd.time":
            cuts.append(number)
    if len(times) < 2:
        return None
    step = (times[-1] - times[0]) / (len(times) - 1) if times[-1] > times[0] else 1 / 24
    return PictureTrace(
        times=times, yavg=yavg, ydif=ydif, cuts=cuts, duration=times[-1] + step, scores=scores
    )


#: A cut the timeline recorded counts when the picture changes there: its frame scores at
#: least this (scdet, percent) and this many times the frames around it. A 15% punch-in on a
#: flat picture scores a few percent, far under a hard cut, yet it is a new framing.
CONFIRMED_CUT_PERCENT = 2.0
CONFIRMED_CUT_RATIO = 4.0


def _recorded_cuts(production: Mapping[str, Any]) -> list[float]:
    """Where the render says the picture changes: each scene's start (but the first) and
    each second framing (production['timeline'])."""
    timeline = production.get("timeline")
    spans = timeline.get("spans") if isinstance(timeline, Mapping) else None
    found: list[float] = []
    for position, span in enumerate(spans or []):
        if not isinstance(span, Mapping):
            continue
        start = _seconds(span.get("start"))
        if start is None:
            continue
        if position:
            found.append(start)
        framing = span.get("second_framing")
        at = _seconds(framing.get("at")) if isinstance(framing, Mapping) else None
        if at is not None:
            found.append(start + at)
    return found


def editorial_cut_times(trace: PictureTrace, production: Mapping[str, Any]) -> list[float]:
    """The film's cuts: every one scdet found over CUT_SCORE_PERCENT, and every cut the
    timeline recorded that the picture confirms (a spike of CONFIRMED_CUT_PERCENT at least,
    CONFIRMED_CUT_RATIO times its neighbourhood), each counted once."""
    found = list(trace.cuts)
    step = trace.duration / max(1, len(trace.times))
    for moment in _recorded_cuts(production):
        near = [i for i, t in enumerate(trace.times) if abs(t - moment) <= 1.5 * step]
        if not near:
            continue
        peak = max(near, key=lambda i: trace.scores[i] if i < len(trace.scores) else 0.0)
        score = trace.scores[peak] if peak < len(trace.scores) else 0.0
        around = [
            trace.scores[i]
            for i, t in enumerate(trace.times)
            if 3 * step < abs(t - trace.times[peak]) <= 12 * step and i < len(trace.scores)
        ]
        floor = sorted(around)[len(around) // 2] if around else 0.0
        if score >= CONFIRMED_CUT_PERCENT and score >= CONFIRMED_CUT_RATIO * max(floor, 0.1):
            found.append(trace.times[peak])
    merged: list[float] = []
    for moment in sorted(found):
        if not merged or moment - merged[-1] > 2 * step:
            merged.append(moment)
    return merged


def _longest_run(flags: list[bool], step: float) -> float:
    longest = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    return round(longest * step, 3)


def _silent_beats(production: Mapping[str, Any]) -> list[tuple[float, float]]:
    """The timeline's silent composed spans: a deliberate pause, not dead air."""
    timeline = production.get("timeline")
    spans = timeline.get("spans") if isinstance(timeline, Mapping) else None
    beats: list[tuple[float, float]] = []
    for span in spans or []:
        if not isinstance(span, Mapping):
            continue
        composed = bool(span.get("composed")) or _kind(span.get("kind")) in COMPOSED_KINDS
        spoken = _seconds(span.get("spoken_seconds"))
        start, end = _seconds(span.get("start")), _seconds(span.get("end"))
        if composed and (spoken is None or spoken <= SILENT_SPOKEN_SECONDS):
            if start is not None and end is not None and end > start:
                beats.append((start, end))
    return beats


def _planned_pauses(production: Mapping[str, Any]) -> list[tuple[float, float]]:
    """Where the timeline planned a pause after words, and how long: (the span's end, what the
    span runs past its recorded words), for every span with words."""
    timeline = production.get("timeline")
    spans = timeline.get("spans") if isinstance(timeline, Mapping) else None
    pauses: list[tuple[float, float]] = []
    for span in spans or []:
        if not isinstance(span, Mapping):
            continue
        spoken = _seconds(span.get("spoken_seconds"))
        start, end = _seconds(span.get("start")), _seconds(span.get("end"))
        if spoken is None or spoken <= SILENT_SPOKEN_SECONDS or start is None or end is None:
            continue
        pauses.append((end, max(0.0, end - start - spoken)))
    return pauses


def average_shot_limit(production: Mapping[str, Any], settings: Any | None = None) -> float:
    """The longest average shot editorial QC lets pass without a note. With the montage off,
    MAX_AVERAGE_SHOT_SECONDS. With it on, a montage shot: ``montage_shot_seconds`` of words and
    half a shot more (MONTAGE_SHOT_TOLERANCE), plus the breath the timeline recorded after
    them (else the assembler's)."""
    from app.media.montage import montage_settings  # noqa: PLC0415 - read when measured

    options = montage_settings(settings)
    if not options["enabled"] or options["max_shots"] <= 1:
        return MAX_AVERAGE_SHOT_SECONDS
    timeline = production.get("timeline")
    breath = (
        _seconds(timeline.get("spoken_tail_seconds")) if isinstance(timeline, Mapping) else None
    )
    if breath is None:
        # The assembler reads qc: imported when measured.
        from app.media.assembler import LEGACY_SPOKEN_TAIL_SECONDS  # noqa: PLC0415

        breath = LEGACY_SPOKEN_TAIL_SECONDS
    return round(float(options["shot_seconds"]) * (1 + MONTAGE_SHOT_TOLERANCE) + breath, 2)


def _voice_source(film: Path, production: Mapping[str, Any]) -> Path:
    """The narration as it was joined (production['audio']['voice_track']), else the film."""
    audio = production.get("audio")
    track = audio.get("voice_track") if isinstance(audio, Mapping) else None
    name = track.get("path") if isinstance(track, Mapping) else None
    if name:
        candidate = film.parent / Path(str(name)).name
        if candidate.is_file():
            return candidate
    return film


def _narration_silences(
    ffmpeg: str, film: Path, production: Mapping[str, Any], duration: float
) -> list[tuple[float, float]] | None:
    """The silences inside the narration: after its first word, before its last, not on a
    silent card, and longer than the breath the timeline planned where they fall (a silence
    across a span's end counts only what runs past that span's breath by
    MAX_NARRATION_SILENCE_SECONDS or more). None when the sound could not be read."""
    spans = silence_spans(
        ffmpeg,
        _voice_source(film, production),
        threshold_db=NARRATION_SILENCE_DB,
        min_seconds=MAX_NARRATION_SILENCE_SECONDS,
    )
    if spans is None:
        return None
    beats = _silent_beats(production)
    pauses = _planned_pauses(production)
    inner: list[tuple[float, float]] = []
    for position, (start, end) in enumerate(spans):
        if start <= 0.02:
            continue  # before the first word
        if position == len(spans) - 1 and end >= duration - 0.05:
            continue  # after the last word
        overlap = max(
            (min(end, b_end) - max(start, b_start) for b_start, b_end in beats), default=0.0
        )
        if overlap >= 0.5 * (end - start):
            continue  # a silent card: the pause is the scene
        if any(
            start - PAUSE_BOUNDARY_TOLERANCE_SECONDS
            <= boundary
            <= end + PAUSE_BOUNDARY_TOLERANCE_SECONDS
            and (end - start) - planned < MAX_NARRATION_SILENCE_SECONDS
            for boundary, planned in pauses
        ):
            continue  # the breath the timeline planned after a shot's words
        inner.append((start, end))
    return inner


def _grade_outliers(production: Mapping[str, Any]) -> list[dict[str, Any]]:
    grade = production.get("grade")
    shots = grade.get("shots") if isinstance(grade, Mapping) else None
    found: list[dict[str, Any]] = []
    for entry in shots or []:
        if not isinstance(entry, Mapping):
            continue
        after = _seconds(entry.get("delta_e_after"))
        if after is not None and after > GRADE_OUTLIER_DELTA_E:
            found.append({"scene_index": entry.get("scene_index"), "delta_e": round(after, 1)})
    return found


def editorial_problems(
    film: Path | str,
    production: Mapping[str, Any],
    *,
    ffmpeg: str | None = None,
    cues: list[dict[str, Any]] | None = None,
    blocking: bool = False,
    settings: Any | None = None,
) -> dict[str, Any]:
    """What a viewer would feel in the editing of ``film``, measured, with Romanian reasons.

    ``production`` is the render's manifest (the timeline's silent cards, the voice track, the
    bed, the grade); ``cues`` the captions as `parse_srt` reads them. ``status``: PASSED,
    ADVISORY (faults found, not blocking), FAILED (faults found and ``blocking``) or
    NOT_MEASURED (no encoder or no film: ``passed`` is None, never a pass by absence).
    """
    path = Path(film)
    longest_average = average_shot_limit(production, settings)
    record: dict[str, Any] = {
        "passed": None,
        "status": "NOT_MEASURED",
        "blocking": bool(blocking),
        "problems": [],
        "reasons_ro": [],
        "measurements": {},
        "limits": {
            "narration_silence_seconds": MAX_NARRATION_SILENCE_SECONDS,
            "end_still_seconds": MAX_END_STILL_SECONDS,
            "end_window_seconds": END_WINDOW_SECONDS,
            "black_yavg": BLACK_YAVG,
            "average_shot_seconds": longest_average,
            "opening_seconds": OPENING_SECONDS,
            "grade_outlier_delta_e": GRADE_OUTLIER_DELTA_E,
        },
    }
    trace = picture_trace(ffmpeg, path)
    if trace is None or not ffmpeg:
        record["detail"] = "Montajul nu a putut fi măsurat: lipsește FFmpeg sau filmul."
        return record
    step = trace.duration / len(trace.times)
    problems: list[dict[str, Any]] = []

    def problem(code: str, reason: str, **measured: Any) -> None:
        problems.append({"code": code, "reason_ro": reason, **measured})

    silences = _narration_silences(ffmpeg, path, production, trace.duration)
    longest_silence = max((end - start for start, end in silences or []), default=0.0)
    if silences:
        start, end = max(silences, key=lambda span: span[1] - span[0])
        problem(
            "dead_air",
            f"O tăcere de {_ro_number(end - start, 2)} s în mijlocul narațiunii (la "
            f"{_ro_number(start)} s; cel mult {_ro_number(MAX_NARRATION_SILENCE_SECONDS, 2)} s): "
            "în golurile vocii spectatorul pleacă.",
            seconds=round(end - start, 3),
            at=round(start, 3),
        )

    tail = [i for i, t in enumerate(trace.times) if t >= trace.duration - END_WINDOW_SECONDS]
    black_end = _longest_run([trace.yavg[i] <= BLACK_YAVG for i in tail], step)
    frozen_end = _longest_run([i > 0 and trace.ydif[i] < FROZEN_YDIF for i in tail], step)
    if black_end > MAX_END_STILL_SECONDS:
        problem(
            "black_ending",
            f"Filmul se încheie pe negru: {_ro_number(black_end)} s de negru în ultimele "
            f"{END_WINDOW_SECONDS:.0f} s (cel mult {_ro_number(MAX_END_STILL_SECONDS)} s). Un "
            "short se reia în buclă, iar un final negru îl trimite pe spectator mai departe.",
            seconds=black_end,
        )
    if frozen_end > MAX_END_STILL_SECONDS:
        problem(
            "frozen_ending",
            f"Imaginea stă încremenită {_ro_number(frozen_end)} s în ultimele "
            f"{END_WINDOW_SECONDS:.0f} s (cel mult {_ro_number(MAX_END_STILL_SECONDS)} s).",
            seconds=frozen_end,
        )

    cuts = len(editorial_cut_times(trace, production))
    average = round(trace.duration / (cuts + 1), 3)
    if average > longest_average:
        problem(
            "long_shots",
            f"Un cadru durează în medie {_ro_number(average)} s (cel mult "
            f"{_ro_number(longest_average)} s): {cuts} "
            f"{'tăietură' if cuts == 1 else 'tăieturi'} în {_ro_number(trace.duration)} s.",
            seconds=average,
        )

    opening = [trace.ydif[i] for i, t in enumerate(trace.times) if 0 < i and t < OPENING_SECONDS]
    opening_motion = round(sum(opening) / len(opening), 3) if opening else 0.0
    if opening_motion < MIN_OPENING_YDIF:
        problem(
            "static_opening",
            "Filmul începe pe o imagine nemișcată: în prima jumătate de secundă nimic nu se "
            "mișcă, iar primul cadru decide dacă spectatorul rămâne.",
            ydif=opening_motion,
        )

    dangling = dangling_caption_words(cues or [])
    for found in dangling:
        problem(
            "dangling_caption",
            f"Subtitrarea {found['cue']} se oprește pe cuvântul «{found['word']}», în mijlocul "
            "frazei.",
            cue=found["cue"],
        )

    audio = production.get("audio")
    bed = audio.get("bed") if isinstance(audio, Mapping) else None
    if not bed:
        problem(
            "no_music_bed",
            "Filmul nu are fond: biblioteca de muzică a studioului nu are încă o piesă "
            "licențiată folosibilă, așa că se aude doar vocea.",
        )

    outliers = _grade_outliers(production)
    for found in outliers:
        problem(
            "colour_outlier",
            f"Scena {found['scene_index']} se abate de la culoarea filmului și după corecție "
            f"(ΔE {_ro_number(found['delta_e'])}, peste {GRADE_OUTLIER_DELTA_E:.0f}).",
            delta_e=found["delta_e"],
        )

    grade = production.get("grade")
    record["measurements"] = {
        "duration_seconds": round(trace.duration, 3),
        "longest_silence_seconds": round(longest_silence, 3),
        "silence_measured_on": _voice_source(path, production).name,
        "black_end_seconds": black_end,
        "frozen_end_seconds": frozen_end,
        "cuts": cuts,
        "average_shot_seconds": average,
        "opening_motion": opening_motion,
        "dangling_captions": dangling,
        "bed": bool(bed),
        "grade_delta_e_max_after": (
            grade.get("delta_e_max_after") if isinstance(grade, Mapping) else None
        ),
        "grade_outliers": outliers,
    }
    record["problems"] = problems
    record["reasons_ro"] = [item["reason_ro"] for item in problems]
    if not problems:
        record.update(passed=True, status="PASSED")
    elif blocking:
        record.update(passed=False, status="FAILED")
    else:
        record.update(passed=True, status="ADVISORY")
    count = len(problems)
    record["detail"] = (
        "Montajul nu are nimic de semnalat."
        if not problems
        else f"{count} {'observație' if count == 1 else 'observații'} de montaj"
        + ("." if blocking else " (recomandări; nu blochează publicarea).")
    )
    return record


def editorial_blocking(settings: Any | None) -> bool:
    """Whether editorial QC refuses a film: the Owner's setting, else the look file's finish
    (`cards.film_finish`), else False: advisory until he decides."""
    stated = getattr(settings, "editorial_qc_blocking", None) if settings is not None else None
    if isinstance(stated, bool):
        return stated
    return bool(film_finish().get("editorial_qc_blocking", False))
