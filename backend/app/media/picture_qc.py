"""Quality control looks at the pictures before the Director does.

Until now the only eye on a finished film was the Director's, at editorial review — after
the film was assembled and after the money for every shot was spent. Everything before her
was file-level: duration, resolution, loudness, captions, how many scenes fell back to a
slow push, and an SSIM heuristic that catches a still which is flat along one axis. That
heuristic catches stripes and blank fields; it cannot tell a beautiful picture of the wrong
thing from the picture the scene asked for, and it never looked at the people in the shot —
`character_drift_qc` said NOT_IMPLEMENTED in as many words.

So the gate that measures the film now also looks at it. One frame from the middle of every
scene goes to a model the provider says can see, in one call for the whole film, with three
questions per scene: is this a picture at all (a blank field, stripes, noise, garbled
writing is not), is it ONE picture (panels pasted together or a picture with a blank band
is not: scene 5 of «The Particle That Shouldn't Exist (But Does)», 2026-10-09, was three
stacked panels and passed every check), and does it show what the scene's visual prompt and
narration asked for. The stills gate and clip QC ask the same one-picture question first.
The same call carries the characters the storyboard put in each scene, with the Character
Bible's canonical description and, where the bible holds a stored portrait, the portrait
itself; a person in the wrong outfit is named, with their scene.

Two rules shape everything below.

The first is that this check certifies only what it measured. With no registry, no employee
whose model declares vision, no frames (no encoder, or no film to cut), no usable answer, or
the day's token ceiling reached, the check is NOT_APPLICABLE with the reason and `passed`
is None, and the film's verdict is exactly what it would have been. A check that could not
run never reports a pass. Where the bible holds no characters at all, the character check
stays NOT_IMPLEMENTED, as it was.

The same rule decides what a cast is worth here. A scene's `character_ids_json` is the film's
own word on who is in the shot, and that is what this check certifies. Beside it the
storyboard records the names its prose merely spelled — read from a bare given name, which
was measured to find the Fact-Checker in "Hurricane Elena made landfall" — and those are
asked about too, recorded as OBSERVED, and never counted: a guess cannot fail a film, and a
check that looked only at guesses has measured nothing. Where a film states nobody at all,
the detail is the board's own note, so "this film has no characters by design" no longer
reads as "nobody listed them".

The second is that a failure here fails the film in every environment. The fallback-scene
gate is conditional — in TEST two motion scenes are the studio's own policy and the rest
push by design, so the same count is a warning there and a failure in PRODUCTION. Nothing
in TEST policy deliberately produces a blank scene or a stranger in a character's clothes.
The gate this one belongs beside is `content_integrity_qc`, the degenerate-still check,
which fails in both environments for exactly this defect measured on the still instead of
on the film. This follows it.

What is looked at is the picture, never the studio's own writing on it (2026-10-10, film
babcf272: the subtitles burnt into the finished film were read as «text or a logo» in every
scene, and the repair that followed retired the stills and clips the Owner had approved).
A film's frames are cut from each scene's own shot beside the film (`clean_shots`), built
before the edit burns the captions in and checked by its sha256 to be the very file the film
was joined from. Only where a shot is gone (released after quality control, or rebuilt since
by another render) are they the film's own, and then, where a subtitle is on screen over
them, the clip look is shown them with only the rows the captions draw in cut out
(`cut_caption_rows`): the picture above those rows, and the strip below them after it. Either
way the model is told where its frames were cut from and that the narration's subtitles are
the studio's (`StudioText`, `studio_text_note`); lettering inside the generated picture counts
exactly as before, wherever in the frame it is.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import logging
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.editorial import FRAME_WIDTH, MAX_FRAMES
from app.agents.identity import clipped
from app.agents.vision import frames_at, frames_for, vision_agent
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media.cards import CAPTION_BAND_TOP, FRAME_HEIGHT
from app.media.models import (
    CharacterBible,
    MediaAsset,
    QualityControlReport,
    SceneTake,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.toolchain import find_ffmpeg

if TYPE_CHECKING:
    from app.media.still_gate import StillPlan

logger = logging.getLogger("studio.picture_qc")

PICTURE_TASK = "picture_qc"
#: v2 (2026-10-09): the one-picture question, after scene 5 came out as three stacked panels.
#: v3 (2026-10-10): the model is told where its frames were cut from and that the narration's
#: subtitles are the studio's own (film babcf272 was failed for its own captions).
#: v5 (2026-10-12 review): the look is told which scene numbers its frames are, since a scene
#: carried forward is not shown and a frame numbered by its position named the wrong scene.
TEMPLATE_VERSION = "picture-qc-v5"

#: The departments asked to look, in order. The Video Editor owns the pictures, so the
#: department that made them is the department that answers for them; the Director is asked
#: only if the Video Editor's model cannot see, and she has her own look later either way.
LOOKERS = ("VideoEditor", "Director", "QualityAssurance")

#: At most this many stored portraits travel with one call. A reference image costs as much
#: as a frame, and beyond a handful the answer is about the attachments, not the film.
MAX_REFERENCE_IMAGES = 4

#: A portrait bigger than this is not sent: the bible is meant to hold a reference, not a
#: master. Measured against the frames, which are 480px JPEGs of a few tens of kilobytes.
MAX_REFERENCE_BYTES = 4_000_000


class ScenePictureVerdict(BaseModel):
    """What the model saw in one scene's frame. Nothing here has a default that reads as a
    pass: a scene the model says nothing about is a scene nobody looked at."""

    model_config = ConfigDict(extra="ignore")
    scene: int
    is_a_picture: bool
    #: One continuous photograph, not panels pasted together or a picture with a blank band.
    one_picture: bool
    shows_the_scene: bool
    reason: str = Field(default="", max_length=300)
    _clip_reason = field_validator("reason", mode="before")(clipped(300))


class CharacterVerdict(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scene: int
    character: str = Field(default="", max_length=120)
    matches: bool
    reason: str = Field(default="", max_length=300)
    _clip_reason = field_validator("reason", mode="before")(clipped(300))


class PictureReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scenes: list[ScenePictureVerdict] = Field(default_factory=list, max_length=16)
    characters: list[CharacterVerdict] = Field(default_factory=list, max_length=48)


_INSTRUCTIONS = (
    "You are the studio's quality control, and you are the first eye on this finished film. "
    "Attached are {frames} images: the first {frames} are one frame from the middle of each "
    "scene, in the order the scenes are listed below: scenes {numbers}, in that order. Answer "
    "each with its own scene number from that list, not its position.{references_note} Judge "
    "only what you can see.\n"
    "{captions_note}"
    "For every scene answer three questions from its frame alone. First: is it a picture at "
    "all? A blank or uniform field, plain stripes or bands, pure noise, a smear, or a wall "
    "of garbled writing is not a picture, however clean the file is. Second: is it ONE "
    "picture, one continuous photograph filling the frame from edge to edge? A collage, a "
    "split screen, a grid, panels stacked one above another, a comic strip, or a picture "
    "with a blank or black band across it is not one picture, however good each part is. "
    "Third: does it show what the scene asked for — its written picture and what the "
    "narration says over it, including its requested motion and ending frame? A visual "
    "effect explicitly requested by the motion is not an unrequested addition. Judge whether "
    "it is well made and consistent with the scene; the request does not excuse artefacts, "
    "unwanted faces, text or other visual-rule violations. Prompt sources identify submitted "
    "requests versus the current storyboard, which may have changed since filming. "
    "Something well made that shows none of what the scene asked "
    "for does not show it.\n"
    "{character_note}"
    'Return only JSON: {{"scenes": [{{"scene": 1, "is_a_picture": true, "one_picture": true, '
    '"shows_the_scene": true, "reason": "one short sentence"}}], "characters": '
    '[{{"scene": 1, "character": "...", "matches": true, "reason": "one short sentence"}}]}}'
    " — one entry for every scene listed, and one for every scene-and-character pair listed. "
    "The reason matters most when your answer is false: say what you actually see.\n"
)

_CHARACTER_NOTE = (
    "Some scenes have people in them who must be the same people every time. Under "
    "`characters` below, each pair gives a scene and a character with the studio's canonical "
    "description of them — face and hair, outfit, props, role symbols, palette. For every "
    "pair, say whether the person in that scene's frame is that character as described. A "
    "different outfit, different hair, missing role props: that is not a match, and say "
    "which. If that character is not in the frame at all, that is not a match either.\n"
)

_REFERENCES_NOTE = (
    " After them come {references} reference portraits from the studio's character bible, in "
    "the order they are listed under `references` below; those are what the character must "
    "look like, not frames of this film."
)


# ------------------------------------------------------------ the studio's own writing
#
# 2026-10-10, film babcf272 «The Particle That Shouldn't Exist (But Does)»: the film-level
# look (`qc.span_picture_qc` -> `judge_clip`) was shown frames of the finished film, read the
# subtitles the studio itself burns in as «text or a logo» in every scene, and failed the
# film; the repair that followed retired the stills and the test shot the Owner had approved
# and bought new ones. The subtitles are the studio's own writing, not the picture's, so a look
# at a film is shown the picture without them wherever it can be:
#
# - SHOT: the scene's own shot beside the film (production["shots"]), which the edit joins and
#   only then burns the captions over; used only while it is the very file the film was joined
#   from (its recorded sha256), because a later render of the same storyboard writes its shots
#   into the same folder under the same names.
# - FILM_CROPPED: the shot is gone (quality control releases the shots once its report is
#   recorded, so the Owner's re-QC finds none) and a subtitle is on screen over the scene's
#   frames, so the film's own frame with the rows its captions draw in cut out
#   (`cut_caption_rows`): the part above them, and after the three frames the strip of each
#   below them. Only those rows: the first crop of 2026-10-10 cut away everything from row
#   1320 down, 600 rows where the captions draw in 200, and a watermark in the bottom corner of
#   the picture was never shown to the look (adversarial review, the same day).
# - FILM_CLEAR: the shot is gone and none of the film's subtitles is on screen at the scene's
#   frames (a scene without words, by the cues of the SRT beside the film), so the film's frame
#   whole: there is nothing of the studio's to cut.
# - FILM: the film's frame as the viewer sees it (no captions burnt in, or the cut failed).
#
# Whatever the source, the model is told which it is and that the narration's subtitles never
# count as text, a logo or a breach of the bible. Lettering inside the generated picture is
# not the studio's and still fails a scene, and the free flat-band reading (`qc.flat_band`)
# still reads every frame, so the triptych of 2026-10-09 still fails as panels.

#: Where the frames a look is shown were cut from (see above).
FrameSource = Literal["SHOT", "FILM_CROPPED", "FILM_CLEAR", "FILM"]
FRAME_SOURCES: tuple[FrameSource, ...] = ("SHOT", "FILM_CROPPED", "FILM_CLEAR", "FILM")

#: The most subtitle lines shown to a look for one scene: a scene of a short carries a few
#: caption cards; more is a timeline that went wrong, and the prompt is not the place for it.
MAX_SUBTITLE_LINES = 16


@dataclass(frozen=True)
class StudioText:
    """The studio's own writing on the frames a look is shown, and where they came from."""

    source: FrameSource
    #: The film burns the narration's subtitles in (production["captions"]["burned_in"]).
    captions_burned_in: bool = False
    #: The subtitle lines on screen over these frames' part of the film, when known.
    subtitles: tuple[str, ...] = ()
    #: The film's opening title (the hook) is written at its top for its first seconds.
    headline: bool = False
    #: FILM_CROPPED: the strip of each frame below the rows its captions were cut out of, in
    #: the frames' order; the look is shown them after the frames (`cut_caption_rows`).
    below_captions: tuple[Path, ...] = ()


_SOURCE_NOTES: dict[str, str] = {
    "SHOT": (
        "These frames were cut from the scene's own shot, which the studio builds before the "
        "edit burns the subtitles of the narration into the film: none of the studio's "
        "subtitles are on them, so any lettering, number, sign or logo you see is inside the "
        "generated picture itself."
    ),
    "FILM_CROPPED": (
        "These frames were cut from the finished film, and the rows near the bottom where the "
        "studio burns the subtitles of the narration were cut out of them first: each frame "
        "shows the picture above those rows, shorter than 9:16 for that reason alone, which "
        "is not a fault, not a blank band and not a sign of panels."
    ),
    "FILM_CLEAR": (
        "These frames were cut from the finished film at moments when none of the studio's "
        "subtitles of the narration is on screen: each frame is the whole picture as the "
        "viewer sees it, and any lettering, number, sign or logo you see in it is the "
        "picture's own."
    ),
    "FILM": (
        "These frames were cut from the finished film as the viewer sees it, with the "
        "studio's subtitles of the narration burnt in near the bottom of the frame."
    ),
}

#: Said of FILM_CROPPED frames whose bottom strips travel with them (adversarial review of
#: 2026-10-10: what lies below the caption rows is the picture's, and is judged as the picture).
_BELOW_NOTE = (
    " After the three frames come {strips} more images, in the same order: the bottom of each "
    "frame, below the rows that were cut out. Each is the lower part of the same picture, shown "
    "apart only because the rows between were cut out: it is not another picture, a panel or "
    "a band, and every question about a frame covers its bottom part too, so lettering, "
    "numbers, signs, logos or faces there count."
)

_SUBTITLES_LISTED = " The subtitle words over these frames are listed under `studio_subtitles`."
_SUBTITLES_ARE_NARRATION = " The subtitles repeat the narration's words."
_HEADLINE_NOTE = (
    " During the film's first seconds the studio also writes the film's opening title at the "
    "top of the frame; that title is the studio's own as well."
)
_OURS_NOTE = (
    " The subtitles of the narration are the studio's own writing, laid over the picture: "
    "wherever any of them still shows, never count it as readable text, a caption, a logo, "
    "garbled writing, a band, or a breach of the visual bible's rules (a rule against text "
    "means text in the picture). Any other writing, such as lettering, numbers, signs or "
    "logos inside the generated picture, counts exactly as it always does."
)


def studio_text_note(text: StudioText | None) -> str:
    """The paragraph that tells a look which writing on its frames is the studio's.

    Empty when there is nothing to say: no StudioText (a bought clip, judged before any edit),
    or a film frame of a film that burns no captions in, where every letter is the picture's.
    """
    if text is None or (text.source == "FILM" and not text.captions_burned_in):
        return ""
    note = _SOURCE_NOTES[text.source]
    if text.source == "FILM_CROPPED" and text.below_captions:
        note += _BELOW_NOTE.format(strips=len(text.below_captions))
    if text.source in ("FILM_CROPPED", "FILM"):
        note += _SUBTITLES_LISTED if text.subtitles else _SUBTITLES_ARE_NARRATION
    if text.source != "SHOT" and text.headline:
        note += _HEADLINE_NOTE
    return note + _OURS_NOTE + "\n"


def film_captions(production: Mapping[str, Any]) -> tuple[bool, bool]:
    """(burnt in, with the opening title) as the render recorded its captions; (False, False)
    for a film whose render recorded none, which burnt nothing it could say."""
    record = production.get("captions")
    if not isinstance(record, Mapping) or record.get("burned_in") is not True:
        return False, False
    style = record.get("style")
    return True, isinstance(style, Mapping) and style.get("headline") is True


@dataclass(frozen=True)
class CleanShot:
    """One scene's shot beside the finished film: its picture before the edit burnt captions
    over it, verified to be the very file the film was joined from."""

    scene_index: int
    path: Path
    #: The rate the shot was built at, when its recorded source says; None means the film's.
    fps: float | None
    #: The scene's length, and the shot's own (the scene plus any dissolve overlap).
    seconds: float
    span: float


@functools.lru_cache(maxsize=64)
def _sha256_of(path: str, size: int, modified_ns: int) -> str | None:
    """The file's sha256, remembered by path, size and modification time: quality control
    verifies the same shots twice (the one-frame look and the span look), and a shot can be a
    lossless file of a hundred megabytes."""
    del size, modified_ns  # part of the cache key only
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def _file_sha256(path: Path) -> str | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return _sha256_of(str(path), stat.st_size, stat.st_mtime_ns)


def _positive(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    return float(value)


def clean_shots(production: Mapping[str, Any], film_dir: Path) -> dict[int, CleanShot]:
    """Each scene's caption-free shot beside the film (production["shots"]), by scene index.

    A shot counts only while it is on disk and its bytes are the sha256 the render recorded:
    the shots are released once the film's QC report is recorded, and another render of the
    storyboard writes shot_NN.mp4 into the same folder, so a file of that name may be another
    film's picture. A record without a sha256 (a render from before 2026-10-01) cannot be
    verified and is not used. Missing or unverifiable shots are simply absent; the caller cuts
    the film's own frames for those scenes.
    """
    found: dict[int, CleanShot] = {}
    records = production.get("shots")
    if not isinstance(records, list):
        return found
    for record in records:
        if not isinstance(record, Mapping) or not record.get("file") or not record.get("sha256"):
            continue
        try:
            index = int(record["scene_index"])
        except (KeyError, TypeError, ValueError):
            continue
        path = film_dir / Path(str(record["file"])).name
        if not path.is_file() or _file_sha256(path) != str(record["sha256"]):
            continue
        source = record.get("source")
        found[index] = CleanShot(
            scene_index=index,
            path=path,
            fps=_positive(source.get("fps")) if isinstance(source, Mapping) else None,
            seconds=_positive(record.get("duration_seconds")) or 0.0,
            span=_positive(record.get("span")) or 0.0,
        )
    return found


#: The rows of a 1080x1920 frame the burnt captions can draw in, first and past-the-last, by
#: the script they were burnt with; only these are cut out of a film frame for a look, and the
#: picture above and below them is shown (adversarial review of 2026-10-10: the first crop cut
#: away everything from row 1320 down, and a watermark in the bottom corner of the picture was
#: never seen). Measured on 2026-10-10 on gray frames, two-line cards with diacritics over
#: capitals and the largest shadow the finish allows (4 px): the ASS captions (Inter Bold 74,
#: assembler.CAPTION_BOTTOM_Y 1500) drew in rows 1365-1494, the legacy SRT style
#: (assembler.CAPTION_STYLE, films from before the ASS captions) in rows 1427-1539. Each band
#: keeps a margin for the encoder's ringing and, for the legacy style, a substitute face.
ASS_CAPTION_ROWS = (CAPTION_BAND_TOP, 1520)
LEGACY_CAPTION_ROWS = (1380, 1560)


def caption_rows(production: Mapping[str, Any]) -> tuple[int, int] | None:
    """The rows the film's burnt captions draw in, or None when it burnt none: the ASS rows
    when the render recorded its ASS script, the legacy rows when it burnt only its SRT (a
    film from before the ASS captions, or a one-scene redo of one, which burns it the same
    way: assembler.redo_scene)."""
    burned, _headline = film_captions(production)
    if not burned:
        return None
    record = production.get("captions")
    ass = record.get("ass") if isinstance(record, Mapping) else None
    return ASS_CAPTION_ROWS if ass else LEGACY_CAPTION_ROWS


def _row(rows_on_1920: int, *, up: bool) -> str:
    """An ffmpeg expression for a row of the input at the same height share as ``rows_on_1920``
    on a 1080x1920 frame, rounded to an even row (down for a top edge, up for a bottom one, so
    the cut never leaves a caption row in)."""
    rounding = "floor" if not up else "ceil"
    return f"{rounding}(ih*{rows_on_1920}/{FRAME_HEIGHT}/2)*2"


def cut_caption_rows(
    ffmpeg: str | None, frame: Path, rows: tuple[int, int], above: Path, below: Path
) -> tuple[Path, Path] | None:
    """``frame`` with the caption ``rows`` cut out: the picture above them as ``above`` and the
    strip below them as ``below``, both from one decode. None when either cannot be cut.

    Cut, never covered: a frame with a black strip painted over its captions is exactly the
    «picture with a blank band» the look is asked to refuse; and never stitched back together,
    because a seam across the picture reads as two panels stacked."""
    if not ffmpeg or not frame.is_file():
        return None
    top, bottom = _row(rows[0], up=False), _row(rows[1], up=True)
    try:
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [
                ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(frame),
                "-filter_complex",
                f"[0:v]split=2[a][b];[a]crop=w=iw:h={top}:x=0:y=0[above];"
                f"[b]crop=w=iw:h=ih-{bottom}:x=0:y={bottom}[below]",
                "-map",
                "[above]",
                "-frames:v",
                "1",
                str(above),
                "-map",
                "[below]",
                "-frames:v",
                "1",
                str(below),
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    if not all(path.is_file() and path.stat().st_size > 0 for path in (above, below)):
        return None
    return above, below


def _film_fps(production: Mapping[str, Any]) -> float:
    """The rate the film was cut at: its recorded timeline's, else 30 (a film from before the
    24 fps timeline recorded none; assembler.film_fps reads it the same way)."""
    timeline = production.get("timeline")
    return (
        _positive(timeline.get("fps") if isinstance(timeline, Mapping) else None)
        or _positive(production.get("fps"))
        or 30.0
    )


def _shot_middles(shots: Sequence[CleanShot], ffmpeg_path: str | None, fps: float) -> list[str]:
    """One frame from the middle of each shot, as base64 JPEG at FRAME_WIDTH, in order; empty
    when any of them cannot be cut, so the caller falls back to the film for all of them and
    the frames never mix two sources out of order."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg or not shots:
        return []
    folder = Path(tempfile.mkdtemp(prefix="picture_qc_"))
    try:
        images: list[str] = []
        for shot in shots:
            middle = max(0, int(shot.seconds * (shot.fps or fps) / 2))
            cut = frames_at(
                str(shot.path),
                ffmpeg_path,
                [middle],
                folder / f"scene_{shot.scene_index:02d}",
                width=FRAME_WIDTH,
            )
            frame = cut.get(middle)
            image = still_image(ffmpeg, frame, FRAME_WIDTH) if frame is not None else None
            if image is None:
                return []
            images.append(image)
        return images
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _description(character: CharacterBible) -> dict[str, Any]:
    """The bible's canonical look, with the empty parts left out rather than sent as blanks."""
    fields = {
        "face_and_hair": str(character.face_hair_desc or "").strip(),
        "outfit": str(character.outfit_desc or "").strip(),
        "props": str(character.props_desc or "").strip(),
        "role_symbols": str(character.role_symbols or "").strip(),
    }
    described: dict[str, Any] = {key: value for key, value in fields.items() if value}
    palette = character.palette_json if isinstance(character.palette_json, dict) else {}
    if palette:
        described["palette"] = palette
    return described


def _reference_asset_id(character: CharacterBible) -> str | None:
    """The first stored portrait the bible declares for this character, if any.

    A slot holds a stored asset id or null, never a description standing in for an image;
    a slot holding something that is not a string is not an asset id and is ignored.
    """
    slots = (
        character.reference_assets_json if isinstance(character.reference_assets_json, dict) else {}
    )
    for value in slots.values():
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _reference_image(session: Session, asset_id: str) -> str | None:
    """A stored portrait as base64, or None when the row or the file is not there."""
    asset = session.get(MediaAsset, asset_id)
    if asset is None:
        return None
    path = Path(asset.uri_or_path)
    try:
        if not path.is_file() or path.stat().st_size > MAX_REFERENCE_BYTES:
            return None
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None


def _not_applicable(reason: str, *, characters_configured: int = 0) -> dict[str, Any]:
    """Both checks stood down for the same reason, and neither certifies anything."""
    return {
        "picture_qc": {
            "status": "NOT_APPLICABLE",
            "passed": None,
            "detail": reason,
            "frames": 0,
            "scenes": [],
            "model_used": False,
            "run_id": None,
        },
        "character_drift_qc": {
            "status": "NOT_IMPLEMENTED" if characters_configured == 0 else "NOT_APPLICABLE",
            "passed": None,
            "detail": (
                "No character is configured in the bible; this check certifies nothing."
                if characters_configured == 0
                else reason
            ),
            "characters_configured": characters_configured,
            "characters_measured": 0,
            "characters_observed": 0,
            "characters": [],
            "reference_images": 0,
        },
        "failures": [],
    }


def film_scene_prompts(
    session: Session, production: Mapping[str, Any], scene: StoryboardScene
) -> dict[str, Any]:
    """The render's submitted prompts, or explicitly labelled storyboard fallback.

    A rewritten storyboard does not change what an older take was asked to show. RunPod's
    journal keeps the actual request for the take named in the render; no provider is called.
    Ending-frame prose is not journalled, so it is omitted when its motion was rewritten.
    """
    from app.providers.runpod.jobs import GenerationJob  # noqa: PLC0415

    package = scene.prompt_json if isinstance(scene.prompt_json, dict) else {}
    still = str(package.get("still_prompt") or scene.visual_prompt or "")
    motion = str(package.get("motion_prompt") or package.get("motion") or "")
    ending = str(package.get("ending_frame") or "")
    sources = {
        "still": "current_storyboard",
        "motion": "current_storyboard",
        "ending_frame": "current_storyboard" if ending else "unavailable",
    }
    recorded = next(
        (
            entry
            for entry in production.get("scenes") or []
            if isinstance(entry, Mapping) and entry.get("scene_index") == scene.scene_index
        ),
        {},
    )
    words = {"still": still, "motion": motion}
    for layer, key in (("still", "still_take"), ("motion", "motion")):
        entry = recorded.get(key)
        take_id = entry.get("take_id") if isinstance(entry, Mapping) else None
        take = session.get(SceneTake, take_id) if take_id else None
        if (
            take is None
            or take.storyboard_id != scene.storyboard_id
            or take.scene_number != scene.scene_index
            or take.kind not in (("still",) if layer == "still" else ("motion", "test_shot"))
            or not take.remote_task_id
        ):
            continue
        job = session.scalar(
            select(GenerationJob)
            .where(
                GenerationJob.remote_job_id == take.remote_task_id,
                GenerationJob.project_id == scene.storyboard_id,
            )
            .order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc())
            .limit(1)
        )
        request = job.request if job is not None and isinstance(job.request, dict) else {}
        submitted = request.get("prompt")
        if not isinstance(submitted, str) or not submitted.strip():
            continue
        words[layer] = submitted
        sources[layer] = "submitted_generation_job"
        if layer == "motion" and " ".join(submitted.split()) != " ".join(motion.split()):
            ending = ""
            sources["ending_frame"] = "unavailable_for_submitted_take"
    return {
        "still_prompt": words["still"],
        "motion_prompt": words["motion"],
        "ending_frame": ending,
        "prompt_sources": sources,
    }


# ------------------------------------------------------- approved stays approved (2026-10-12)
#
# 2026-10-12, film aa170155 («Why Ernest Lawrence's First Cyclotron Barely Fit on a Desk»):
# scene 1 was cut from the same still 7a0be480 and the same clip 843617b8 in four films. The
# one-frame look passed it in the reports of 14:45 and 15:03 (10-11) and 08:15 UTC, and failed it
# at 10:35 UTC («a spherical wire-cage lamp»); the Director's REPAIR bought a new still and a new
# clip for a picture nothing had changed in. Scene 3 the same at 08:15 UTC (same takes as the two
# reports of 10-11, which passed it; 18 credits for a new still). The Owner, the same afternoon:
# «Nu putem permite loopuri pe bani și picarea QC dacă deja a fost aprobată». So a scene whose
# picture is exactly that of an earlier film of the same storyboard whose look passed it is not
# looked at again by the model: its verdict is carried forward, with the report it came from and
# the note «trecută la controlul din …, aceleași preluări». A different still or a different clip
# is a different picture and is judged as before.
#
# The review of that change (the same evening) narrowed what is carried and widened the key:
#
# - The key is not the takes alone (`carry_keys`): the check's own version (a newer look asks
#   other questions), the visual bible and the scene's look (what the picture is judged against),
#   and the scene's place and speed in the film (a clip cut or slowed differently is another
#   picture on screen). An earlier entry recorded without that key (before this change) carries
#   nothing: the scene is looked at again once, and its key is recorded from then on.
# - Only the vision model's stochastic look is carried. The free detectors that read the frame
#   itself, YuNet's face count and the flat-band reading (`qc.span_picture_qc`), always run.
# - What the Director judged FALSE, or accepted as a minor defect, on exactly these takes stays
#   so (`earlier_acceptances`): the same picture is not looked at again for the check she
#   settled, and cannot turn into a purchase on the next look's mood.

#: The film-level picture checks whose per-scene verdict a later film with the same picture keeps.
CARRIED_CHECKS = ("picture_qc", "picture_spans_qc")
#: The status of a scene (and of a check that judged no scene) carried forward.
CARRIED_STATUS = "CARRIED_FORWARD"


def check_version(check: str) -> str:
    """The version of a carried check's own judgement: its template's (`TEMPLATE_VERSION` for
    the one-frame look, `CLIP_TEMPLATE_VERSION` for the span look). A verdict of another version
    is not carried."""
    return {"picture_qc": TEMPLATE_VERSION, "picture_spans_qc": CLIP_TEMPLATE_VERSION}.get(
        check, ""
    )


def scene_takes(production: Mapping[str, Any]) -> dict[int, tuple[str, str | None]]:
    """Per scene, the (still take, clip take) the film was cut from, as its render recorded
    them (``scenes[].still_take.take_id``, ``scenes[].motion.take_id``). A scene with no still
    take of record (a composed card, a render from before the take ledger) is left out: there
    is nothing it could be the same as."""
    takes: dict[int, tuple[str, str | None]] = {}
    for entry in production.get("scenes") or []:
        if not isinstance(entry, Mapping):
            continue
        index = entry.get("scene_index")
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        still = entry.get("still_take")
        motion = entry.get("motion")
        still_id = still.get("take_id") if isinstance(still, Mapping) else None
        clip_id = motion.get("take_id") if isinstance(motion, Mapping) else None
        if still_id:
            takes[index] = (str(still_id), str(clip_id) if clip_id else None)
    return takes


def _look_hash(bible: Any, look: Any) -> str:
    """The bible and the scene's look block, as one short fingerprint."""
    raw = json.dumps(
        {"bible": bible or {}, "look": str(look or "")},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def carry_keys(
    production: Mapping[str, Any],
    check: str,
    *,
    bible: Any,
    looks: Mapping[int, Any] | None = None,
    planned: Mapping[int, float] | None = None,
) -> dict[int, dict[str, Any]]:
    """Per scene with a still take of record, what a carried verdict of ``check`` must match:
    the still and clip takes, the check's version (`check_version`), the bible with the scene's
    look block (``looks``), and the scene's span on the film's timeline (start, end) with the
    speed its clip was slowed by (``motion.slowed_by``; ``planned`` lays out a render that did
    not record its spans, as `qc.timeline_spans` does). Read only."""
    from app.media.qc import timeline_spans  # noqa: PLC0415 - qc imports this module

    takes = scene_takes(production)
    if not takes:
        return {}
    spans = {
        int(span["scene_index"]): span
        for span in timeline_spans(dict(production), dict(planned or {}))
        if isinstance(span, Mapping)
    }
    speeds: dict[int, float] = {}
    for entry in production.get("scenes") or []:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("scene_index"), int):
            continue
        motion = entry.get("motion")
        slowed = motion.get("slowed_by") if isinstance(motion, Mapping) else None
        speeds[int(entry["scene_index"])] = (
            float(slowed) if isinstance(slowed, int | float) else 1.0
        )
    keys: dict[int, dict[str, Any]] = {}
    for index, (still, clip) in takes.items():
        span = spans.get(index)
        keys[index] = {
            "still": still,
            "clip": clip,
            "check": check,
            "version": check_version(check),
            "look": _look_hash(bible, (looks or {}).get(index)),
            "start": round(float(span["start"]), 3) if span is not None else None,
            "end": round(float(span["end"]), 3) if span is not None else None,
            "speed": round(speeds.get(index, 1.0), 4),
        }
    return keys


def storyboard_carry_keys(
    session: Session, storyboard_id: str, production: Mapping[str, Any], check: str
) -> dict[int, dict[str, Any]]:
    """`carry_keys` for a film of this storyboard, with the storyboard's own bible, each
    scene's look block and planned length, read as quality control reads them (the Director's
    reading of a report, `director_qc.film_qc_context`, keys the same scenes the same way)."""
    board = session.get(Storyboard, storyboard_id) if storyboard_id else None
    if board is None:
        return {}
    rows = list(
        session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        )
    )
    return carry_keys(
        production,
        check,
        bible=board.visual_bible_json,
        looks={
            int(row.scene_index): (
                row.prompt_json.get("look_block") if isinstance(row.prompt_json, dict) else None
            )
            for row in rows
        },
        planned={int(row.scene_index): float(row.duration_seconds or 0.0) for row in rows},
    )


def scene_state(checks: Mapping[str, Any], check: str, index: int) -> bool | None:
    """What one report's ``check`` said about scene ``index``: True passed, False refused, None
    when it has no measured verdict on it (no entry, not looked at, the check stood down).

    The one-frame look (``picture_qc``) passes a scene that is a picture, one picture and shows
    the scene, with no stated character of it refused by the bible's description; the span look
    (``picture_spans_qc``) a scene whose entry passed. A carried verdict reads as it was carried."""
    record = checks.get(check)
    if not isinstance(record, Mapping):
        return None
    for entry in record.get("scenes") or []:
        if not isinstance(entry, Mapping):
            continue
        if check == "picture_qc":
            if entry.get("scene") != index:
                continue
            if entry.get("status") not in ("MEASURED", CARRIED_STATUS):
                return None
            answers = [entry.get(key) for key in ("is_a_picture", "one_picture", "shows_the_scene")]
            if any(answer is False for answer in answers):
                return False
            drift = checks.get("character_drift_qc")
            people = drift.get("characters") if isinstance(drift, Mapping) else None
            if any(
                isinstance(person, Mapping)
                and person.get("scene") == index
                and person.get("status") == "MEASURED"
                and person.get("matches") is False
                for person in people or []
            ):
                return False
            return True if all(answer is True for answer in answers) else None
        if entry.get("scene_index") != index:
            continue
        passed = entry.get("passed")
        return passed if isinstance(passed, bool) else None
    return None


def _scene_entry(record: Any, check: str, index: int) -> Mapping[str, Any] | None:
    if not isinstance(record, Mapping):
        return None
    key = "scene" if check == "picture_qc" else "scene_index"
    for entry in record.get("scenes") or []:
        if isinstance(entry, Mapping) and entry.get(key) == index:
            return entry
    return None


@dataclass(frozen=True)
class EarlierPass:
    """The newest earlier report whose check passed a scene with exactly this picture."""

    report_id: str
    verified_at: str
    media_asset_id: str
    still_take: str
    clip_take: str | None

    @property
    def note_ro(self) -> str:
        when = str(self.verified_at)[:16].replace("T", " ")
        return f"trecută la controlul din {when} UTC, aceleași preluări"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "passed",
            "report_id": self.report_id,
            "verified_at": self.verified_at,
            "media_asset_id": self.media_asset_id,
            "still_take": self.still_take,
            "clip_take": self.clip_take,
        }


def _storyboard_assets(session: Session, storyboard_id: str) -> list[str]:
    return [
        str(asset_id)
        for asset_id in session.scalars(
            select(VideoRenderJob.output_asset_id).where(
                VideoRenderJob.storyboard_id == storyboard_id,
                VideoRenderJob.output_asset_id.is_not(None),
            )
        )
    ]


def earlier_passes(
    session: Session,
    storyboard_id: str,
    keys: Mapping[int, Mapping[str, Any]],
    check: str,
    *,
    before: str | None = None,
    exclude_report_ids: Sequence[str] = (),
) -> dict[int, EarlierPass]:
    """Per scene, the newest earlier QC report of a film of the same storyboard whose ``check``
    passed the scene with exactly its carry key (``keys``, `carry_keys`: the takes, the check's
    version, the bible and look, the span and speed). An entry recorded without a key carries
    nothing. ``before`` (an ISO time) and ``exclude_report_ids`` leave out the report being read
    and anything after it. Read only; nothing is judged."""
    if not keys or not storyboard_id:
        return {}
    assets = _storyboard_assets(session, storyboard_id)
    if not assets:
        return {}
    excluded = set(exclude_report_ids)
    found: dict[int, EarlierPass] = {}
    for report in session.scalars(
        select(QualityControlReport)
        .where(QualityControlReport.media_asset_id.in_(assets))
        .order_by(QualityControlReport.verified_at.desc())
    ):
        if report.id in excluded or (before is not None and str(report.verified_at) >= before):
            continue
        checks = report.checks_json if isinstance(report.checks_json, Mapping) else {}
        for index, key in keys.items():
            if index in found:
                continue
            entry = _scene_entry(checks.get(check), check, index)
            if entry is None or entry.get("carry_key") != dict(key):
                continue
            if scene_state(checks, check, index) is True:
                found[index] = EarlierPass(
                    report_id=str(report.id),
                    verified_at=str(report.verified_at),
                    media_asset_id=str(report.media_asset_id),
                    still_take=str(key.get("still") or ""),
                    clip_take=key.get("clip"),
                )
        if len(found) == len(keys):
            break
    return found


@dataclass(frozen=True)
class EarlierAcceptance:
    """The Director's newest word on a check's findings about a scene with exactly these takes:
    FALSE (quality control misread it), ACCEPTED as a minor defect, or her second look that
    overturned the refusal (``verdicts``)."""

    report_id: str
    decided_at: str
    verdicts: tuple[str, ...]
    reason: str
    still_take: str
    clip_take: str | None

    @property
    def note_ro(self) -> str:
        when = str(self.decided_at)[:16].replace("T", " ")
        return f"acceptată de Directoare la {when} UTC, aceleași preluări"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "accepted",
            "report_id": self.report_id,
            "decided_at": self.decided_at,
            "verdicts": list(self.verdicts),
            "reason": self.reason,
            "still_take": self.still_take,
            "clip_take": self.clip_take,
        }


#: Her verdicts that settle a check's findings on a picture (with ACCEPTED only as minor).
_SETTLING = frozenset({"FALSE", "ACCEPTED"})


def earlier_acceptances(
    session: Session, storyboard_id: str, production: Mapping[str, Any], check: str
) -> dict[int, EarlierAcceptance]:
    """Per scene of this film, the Director's settling of ``check``'s findings on exactly the
    takes it has now (2026-10-12 review: a scene she ACCEPTED was judged again and could turn
    REAL, and a REPAIR followed). Read from her decisions on this storyboard's reports, newest
    first; the newest decision with a word on (scene, check family, these takes) decides it:

    - her second look before a purchase overturned the refusal (``done.overturned``: nothing was
      bought for it), for the checks it named; or
    - every one of her verdicts on that check's findings about the scene is FALSE, OWNER_CHOICE
      or ACCEPTED as minor, and one of them is FALSE or ACCEPTED.

    A REAL verdict, or an ACCEPTED one with no severity or a serious one (from before the
    severities, 2026-10-12), settles nothing. Read only."""
    from app.agents.reviews import check_family  # noqa: PLC0415 - agents import media
    from app.media.director_qc import DECISION_EVENT  # noqa: PLC0415 - it imports this module
    from app.models import DomainEvent  # noqa: PLC0415

    takes = scene_takes(production)
    if not takes or not storyboard_id:
        return {}
    family = check_family(check)
    their_takes: dict[str, dict[int, tuple[str, str | None]]] = {}

    def takes_of(report_id: str) -> dict[int, tuple[str, str | None]]:
        if report_id not in their_takes:
            report = session.get(QualityControlReport, report_id)
            job = (
                session.scalar(
                    select(VideoRenderJob).where(
                        VideoRenderJob.output_asset_id == report.media_asset_id
                    )
                )
                if report is not None
                else None
            )
            recorded = job.production_json if job is not None else None
            their_takes[report_id] = scene_takes(recorded if isinstance(recorded, Mapping) else {})
        return their_takes[report_id]

    found: dict[int, EarlierAcceptance] = {}
    decided: set[int] = set()
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == DECISION_EVENT)
        .order_by(DomainEvent.sequence.desc())
    ):
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        if str(payload.get("storyboard_id") or "") != storyboard_id:
            continue
        report_id = str(payload.get("report_id") or "")
        if not report_id:
            continue
        theirs = takes_of(report_id)
        recorded_done = payload.get("done")
        done: Mapping[str, Any] = recorded_done if isinstance(recorded_done, Mapping) else {}
        for look in done.get("overturned") or []:
            if not isinstance(look, Mapping) or not isinstance(look.get("scene_index"), int):
                continue
            index = int(look["scene_index"])
            named = {check_family(name) for name in look.get("checks") or []}
            if index in decided or theirs.get(index) != takes.get(index) or index not in takes:
                continue
            if named and family not in named:
                continue
            decided.add(index)
            found[index] = EarlierAcceptance(
                report_id=report_id,
                decided_at=str(event.timestamp),
                verdicts=("OVERTURNED",),
                reason=str(look.get("reason") or "")[:300],
                still_take=takes[index][0],
                clip_take=takes[index][1],
            )
        by_scene: dict[int, list[Mapping[str, Any]]] = {}
        for verdict in payload.get("verdicts") or []:
            if not isinstance(verdict, Mapping) or verdict.get("check_level"):
                continue
            scene = verdict.get("scene_index")
            if not isinstance(scene, int) or check_family(verdict.get("check")) != family:
                continue
            by_scene.setdefault(scene, []).append(verdict)
        for index, verdicts in by_scene.items():
            if index in decided or index not in takes or theirs.get(index) != takes[index]:
                continue
            decided.add(index)
            words = [str(item.get("verdict") or "") for item in verdicts]
            settles = all(
                word in ("FALSE", "OWNER_CHOICE")
                or (word == "ACCEPTED" and item.get("severity") == "minor")
                for word, item in zip(words, verdicts, strict=True)
            ) and any(word in _SETTLING for word in words)
            if settles:
                found[index] = EarlierAcceptance(
                    report_id=report_id,
                    decided_at=str(event.timestamp),
                    verdicts=tuple(dict.fromkeys(words)),
                    reason=str(verdicts[0].get("reason") or "")[:300],
                    still_take=takes[index][0],
                    clip_take=takes[index][1],
                )
    return found


def carried_forward(
    session: Session,
    storyboard_id: str,
    production: Mapping[str, Any],
    check: str,
    keys: Mapping[int, Mapping[str, Any]],
) -> dict[int, EarlierPass | EarlierAcceptance]:
    """The scenes whose ``check`` look is not asked again: passed before with exactly this
    carry key (`earlier_passes`), or settled by the Director on exactly these takes
    (`earlier_acceptances`). A pass is named first when both are there."""
    accepted: dict[int, EarlierPass | EarlierAcceptance] = dict(
        earlier_acceptances(session, storyboard_id, production, check)
    )
    accepted.update(earlier_passes(session, storyboard_id, keys, check))
    return {index: earlier for index, earlier in accepted.items() if index in keys}


def _carried_scene(
    index: int, earlier: EarlierPass | EarlierAcceptance, key: Mapping[str, Any] | None
) -> dict[str, Any]:
    """A scene of the one-frame look carried forward: it passed, and from where."""
    return {
        "scene": index,
        "status": CARRIED_STATUS,
        "is_a_picture": True,
        "one_picture": True,
        "shows_the_scene": True,
        "reason": earlier.note_ro,
        "carried_from": earlier.as_dict(),
        "carry_key": dict(key) if key is not None else None,
    }


#: Why the character check measured nobody when its people were in carried scenes.
_CARRIED_CAST_DETAIL = (
    "the scenes that state who is in them passed an earlier check with the same takes and "
    "were not looked at again"
)


def _all_carried(
    scenes: Sequence[Mapping[str, Any]],
    carried: Mapping[int, EarlierPass | EarlierAcceptance],
    characters_configured: int,
    keys: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    """Every scene of the film passed an earlier check with the same picture, or was settled by
    the Director (2026-10-12): the look is not asked, nothing is cut, and the check passes on
    what it passed before."""
    stated = any(scene["characters"] for scene in scenes)
    picture = {
        "status": CARRIED_STATUS,
        "passed": True,
        "detail": "every scene passed an earlier check with the same takes; none was judged again",
        "frames": 0,
        "scenes_measured": 0,
        "scenes_carried": len(carried),
        "scenes": [
            _carried_scene(index, earlier, keys.get(index))
            for index, earlier in sorted(carried.items())
        ],
        "model_used": False,
        "run_id": None,
        "template_version": TEMPLATE_VERSION,
    }
    drift: dict[str, Any] = {
        "status": "NOT_IMPLEMENTED" if characters_configured == 0 else "NOT_APPLICABLE",
        "passed": None,
        "detail": (
            "No character is configured in the bible; this check certifies nothing."
            if characters_configured == 0
            else _CARRIED_CAST_DETAIL
            if stated
            else "no scene in this film lists a character"
        ),
        "characters_configured": characters_configured,
        "characters_measured": 0,
        "characters_observed": 0,
        "characters": [],
        "reference_images": 0,
    }
    return {"picture_qc": picture, "character_drift_qc": drift, "failures": []}


def _renumbered(answered: Sequence[int], shown: Sequence[int]) -> dict[int, int] | None:
    """The scene each answered number stands for, when the look numbered the frames by their
    position instead of by the scene numbers it was given (2026-10-12 review: with scenes 1-2
    carried and only scene 3 shown, «scene 1» came back for the one frame, and scene 3 was left
    unjudged): only when as many came back as were shown and they are not the shown scenes'
    numbers — by number (1 is the first frame) when they are 1..n, else, when none of them is a
    shown scene's, in the order given. None when the numbers are the shown scenes' already, or
    cannot be read either way."""
    if not answered or len(answered) != len(shown) or set(answered) == set(shown):
        return None
    if sorted(answered) == list(range(1, len(shown) + 1)):
        return {number: shown[number - 1] for number in answered}
    if set(answered) & set(shown) or len(set(answered)) != len(answered):
        return None
    return dict(zip(answered, shown, strict=True))


def evaluate_pictures(
    engine: Engine,
    registry: Any | None,
    media_asset_id: str,
    correlation_id: str,
    *,
    ffmpeg_path: str | None = None,
) -> dict[str, Any]:
    """Look at one finished film's pictures and its people.

    Returns ``{"picture_qc": {...}, "character_drift_qc": {...}, "failures": [...]}`` for
    quality control to fold into its report. Called before quality control opens its write
    transaction, because the model run writes its own rows and the day's token ceiling is
    read outside one (`app.agents.services.run_agent_task`).

    A scene whose picture is exactly that of an earlier film of the storyboard whose look passed
    it (2026-10-12, aa170155: `earlier_passes`, keyed by `carry_keys`), or whose findings of this
    look the Director settled on the same takes (`earlier_acceptances`), is not looked at
    again: its entry is CARRIED_FORWARD with where it came from, it is never sent to the model,
    and its characters are not asked about. When every scene is carried, nobody is asked at
    all. Every entry records its carry key, so a later film with the same picture can carry it.

    The look is told which scenes its frames are (2026-10-12 review: shown only scene 3, a
    model numbered its one frame «1» and the look certified nothing); numbers it gave by
    position are read back to the scenes (`_renumbered`), and a look that answered about scenes
    it was not shown and left a shown scene unanswered fails the check, never passes it.
    """
    with Session(engine) as session:
        asset = session.get(MediaAsset, media_asset_id)
        if asset is None:
            return _not_applicable("the material does not exist")
        characters_configured = len(list(session.scalars(select(CharacterBible.id))))
        path, duration = asset.uri_or_path, asset.duration_seconds
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
        )
        board = session.get(Storyboard, job.storyboard_id) if job is not None else None
        if board is None:
            # A film with no storyboard behind it has no scenes to compare its pictures with,
            # which is the same answer as a storyboard with no scenes and is given in the same
            # words. Returned here rather than folded into the `not scenes` check below so
            # that everything after this line has a storyboard to read the cast from.
            return _not_applicable(
                "the film has no storyboard scenes to compare its pictures with",
                characters_configured=characters_configured,
            )
        title = str(board.title or "")
        # What the render recorded about its shots and captions, read while the session is
        # open: the frames below come from the shots when they are still beside the film.
        production: dict[str, Any] = (
            dict(job.production_json)
            if job is not None and isinstance(job.production_json, dict)
            else {}
        )
        # The storyboard read out as plain values. Everything below this session runs with it
        # closed — the model call must not hold a connection while it waits — and a detached
        # ORM row is a lock or an error waiting for a reader who forgot which it was.
        scenes: list[dict[str, Any]] = [
            {
                "index": scene.scene_index,
                "seconds": scene.duration_seconds,
                **film_scene_prompts(session, production, scene),
                "narration": scene.voiceover_segment,
                "characters": [
                    cid for cid in (scene.character_ids_json or []) if isinstance(cid, str)
                ],
                "look_block": (
                    scene.prompt_json.get("look_block")
                    if isinstance(scene.prompt_json, dict)
                    else None
                ),
            }
            for scene in session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board.id)
                .order_by(StoryboardScene.scene_index)
            )
        ]
        if not scenes:
            return _not_applicable(
                "the film has no storyboard scenes to compare its pictures with",
                characters_configured=characters_configured,
            )
        # What the board's maker decided about its cast. Two things come from it: the names
        # its prose spelled and it refused to cast on — asked about below like any other,
        # and unable to fail the film, because the studio was never told that person is in
        # the shot — and, when the film states nobody at all, the maker's own reason for
        # that, so this check reports "no characters by design" where that is what happened
        # instead of the one sentence it used to print for every reason there could be.
        from app.media.services import storyboard_cast_record  # noqa: PLC0415 - read only

        record = storyboard_cast_record(session, board.id)
        cast_note = record["note"]
        for scene in scenes:
            scene["guessed"] = [
                cid
                for cid in record["guessed"].get(str(scene["index"]), [])
                if cid not in scene["characters"]
            ]
        # Approved stays approved (2026-10-12, aa170155): the scenes an earlier film with the
        # same picture passed, or the Director settled on the same takes, are not looked at
        # again by the model.
        indices = {scene["index"] for scene in scenes}
        keys = carry_keys(
            production,
            "picture_qc",
            bible=board.visual_bible_json,
            looks={scene["index"]: scene["look_block"] for scene in scenes},
            planned={scene["index"]: float(scene["seconds"] or 0.0) for scene in scenes},
        )
        carried = {
            index: earlier
            for index, earlier in carried_forward(
                session, board.id, production, "picture_qc", keys
            ).items()
            if index in indices
        }
        if carried and all(scene["index"] in carried for scene in scenes):
            return _all_carried(scenes, carried, characters_configured, keys)
        if registry is None or not registry.registered_ids():
            return _not_applicable(
                "no language-model provider is registered: nobody could look at the pictures",
                characters_configured=characters_configured,
            )
        looker = vision_agent(session, *LOOKERS)
        if looker is None:
            return _not_applicable(
                "no employee's model declares vision: the pictures were not looked at",
                characters_configured=characters_configured,
            )
        looker_id, looker_name = looker
        # Read the bible for the people this storyboard actually puts on screen, while the
        # session is open; the model call below must not hold one.
        wanted = [cid for scene in scenes for cid in scene["characters"] + scene["guessed"]]
        #: The characters the film itself states are in it. Only these may pull a stored
        #: portrait into the question: a guessed name buys nothing and shows nothing.
        stated_ids = {cid for scene in scenes for cid in scene["characters"]}
        bibles = (
            {
                character.id: character
                for character in session.scalars(
                    select(CharacterBible).where(CharacterBible.id.in_(set(wanted)))
                )
            }
            if wanted
            else {}
        )
        described = {
            cid: (_description(character), _reference_asset_id(character), character.canonical_name)
            for cid, character in bibles.items()
        }
        reference_images: dict[str, str] = {}
        for cid, (_, reference_id, _name) in described.items():
            if cid not in stated_ids:
                continue
            if reference_id is None or len(reference_images) >= MAX_REFERENCE_IMAGES:
                continue
            encoded = _reference_image(session, reference_id)
            if encoded is not None:
                reference_images[cid] = encoded

    # The picture without the studio's subtitles (2026-10-10, babcf272): the middle of each
    # scene's own shot when every scene up to the frame cap has one beside the film, else the
    # film's own frames as before, with the model told the subtitles are the studio's.
    burned, headline = film_captions(production)
    shots = clean_shots(production, Path(str(path or "")).parent)
    # Only the scenes not carried forward are shown (2026-10-12): a carried scene's frame is
    # never cut from its shot, and never sent.
    to_judge = [scene for scene in scenes if scene["index"] not in carried]
    wanted = to_judge[:MAX_FRAMES]
    source: FrameSource = "FILM"
    frames: list[str] = []
    framed: list[dict[str, Any]] = []
    if wanted and all(scene["index"] in shots for scene in wanted):
        frames = _shot_middles(
            [shots[scene["index"]] for scene in wanted], ffmpeg_path, _film_fps(production)
        )
        if frames:
            source = "SHOT"
            framed = wanted[: len(frames)]
    if not frames:
        # The film's frames are found by the scenes' lengths end to end, so every scene is
        # cut and the carried ones are dropped after.
        cut = frames_for(
            path,
            ffmpeg_path,
            duration,
            scene_seconds=[scene["seconds"] for scene in scenes],
        )
        cut_pairs = [
            (scene, frame)
            for scene, frame in zip(scenes, cut, strict=False)
            if scene["index"] not in carried
        ]
        framed = [scene for scene, _frame in cut_pairs]
        frames = [frame for _scene, frame in cut_pairs]
    if not frames:
        return _not_applicable(
            "no frame could be read from the film: there is no encoder, or no file to cut",
            characters_configured=characters_configured,
        )

    # One frame per scene, in order. When the encoder returned fewer than the storyboard
    # has (the frame cap, or a cut that failed), the frames are the first scenes and only
    # those are asked about; the scenes past them are named as unlooked-at, never as passed.
    looked = framed
    framed_indices = {scene["index"] for scene in framed}
    unlooked = [scene["index"] for scene in to_judge if scene["index"] not in framed_indices]

    #: (scene_index, character_id, basis) triples the model is asked about, and the ones it
    #: cannot be. `basis` is which reading put that name here: "stated" is the film's own
    #: word and is what this check certifies; "guessed" is a name the prose spelled, looked
    #: at for the record and never counted for or against the film.
    pairs: list[tuple[int, str, str]] = []
    not_applicable_characters: list[dict[str, Any]] = []
    for scene in looked:
        asked = [(cid, "stated") for cid in scene["characters"]]
        asked += [(cid, "guessed") for cid in scene["guessed"]]
        for cid, basis in asked:
            if cid not in described:
                continue
            description, reference_id, name = described[cid]
            if not description and cid not in reference_images:
                not_applicable_characters.append(
                    {
                        "scene": scene["index"],
                        "character": name,
                        "basis": basis,
                        "status": "NOT_APPLICABLE",
                        "matches": None,
                        "reason": (
                            "the bible holds no description of this character and no "
                            "reference image: there is nothing to compare the frame with"
                        ),
                    }
                )
                continue
            pairs.append((scene["index"], cid, basis))

    attached_references = [
        {"character": described[cid][2], "image": image}
        for cid, image in reference_images.items()
        if any(cid == pair_id and basis == "stated" for _, pair_id, basis in pairs)
    ]
    shown = {
        "title": title,
        "scenes": [
            {
                "scene": scene["index"],
                "picture": scene["still_prompt"],
                "motion": scene["motion_prompt"],
                "ending_frame": scene["ending_frame"],
                "prompt_sources": scene["prompt_sources"],
                "narration": scene["narration"],
            }
            for scene in looked
        ],
        "characters": [
            {
                "scene": index,
                "character": described[cid][2],
                "bible": described[cid][0],
                "reference": described[cid][2] if cid in reference_images else None,
            }
            for index, cid, _basis in pairs
        ],
        "references": [entry["character"] for entry in attached_references],
    }
    prompt = _INSTRUCTIONS.format(
        frames=len(frames),
        numbers=", ".join(str(scene["index"]) for scene in looked),
        references_note=(
            _REFERENCES_NOTE.format(references=len(attached_references))
            if attached_references
            else ""
        ),
        character_note=_CHARACTER_NOTE if pairs else "",
        captions_note=studio_text_note(
            StudioText(source=source, captions_burned_in=burned, headline=headline)
        ),
    ) + wrap_in_inert_boundary(json.dumps(shown, ensure_ascii=False)[:14000], "the-film")

    from app.agents.structured import structured_run  # noqa: PLC0415

    parsed, first, second = structured_run(
        engine,
        registry,
        looker_id,
        PICTURE_TASK,
        prompt,
        TEMPLATE_VERSION,
        correlation_id,
        PictureReport,
        '{"scenes": [...], "characters": [...]}',
        summary=(
            f"Mă uit la cele {len(frames)} cadre ale filmului «{title[:80]}» înainte de Director."
        ),
        max_tokens=4000,
        temperature=0.1,
        extra={"images": frames + [entry["image"] for entry in attached_references]},
    )
    run = second or first
    run_id = run["id"]
    if parsed is None or not parsed.scenes:
        # A model that answered nothing usable, or was refused under the day's token
        # ceiling, has not looked at anything. Say so; do not pass the film for it.
        detail = (
            f"{looker_name} gave no usable verdict on the pictures ({run['status']})"
            if parsed is None
            else f"{looker_name} returned no verdict for any scene"
        )
        logger.info("picture_qc_no_verdict", extra={"run_status": run["status"]})
        stood_down = _not_applicable(detail, characters_configured=characters_configured)
        stood_down["picture_qc"]["frames"] = len(frames)
        stood_down["picture_qc"]["frames_from"] = source
        stood_down["picture_qc"]["run_id"] = run_id
        # What an earlier check passed is still recorded; the check itself certifies nothing.
        stood_down["picture_qc"]["scenes"] = [
            _carried_scene(index, earlier, keys.get(index))
            for index, earlier in sorted(carried.items())
        ]
        stood_down["picture_qc"]["template_version"] = TEMPLATE_VERSION
        for entry in not_applicable_characters:
            stood_down["character_drift_qc"]["characters"].append(entry)
        return stood_down

    failures: list[str] = []
    scene_records: list[dict[str, Any]] = []
    shown_indices = [int(scene["index"]) for scene in looked]
    # The look numbered its frames by position (2026-10-12 review): read them back to the
    # scenes shown, scenes and characters alike; never a silent skip of the scene shown.
    renumber = _renumbered([verdict.scene for verdict in parsed.scenes], shown_indices)
    if renumber is not None:
        logger.info("picture_qc_renumbered", extra={"answered": sorted(renumber)})
    answered = {
        (renumber or {}).get(verdict.scene, verdict.scene): verdict for verdict in parsed.scenes
    }
    strangers = sorted(set(answered) - set(shown_indices))
    measured_scenes = 0
    for scene in looked:
        verdict = answered.get(scene["index"])
        if verdict is None:
            scene_records.append(
                {
                    "scene": scene["index"],
                    "status": "NOT_APPLICABLE",
                    "is_a_picture": None,
                    "one_picture": None,
                    "shows_the_scene": None,
                    "reason": (
                        f"no verdict was returned for this scene; the look answered about "
                        f"scenes {strangers}, which it was not shown"
                        if strangers
                        else "no verdict was returned for this scene"
                    ),
                    "carry_key": keys.get(scene["index"]),
                }
            )
            if strangers:
                # Never a pass by omission: the scene shown was not judged at all.
                failures.append(
                    f"Scene {scene['index']}: the look gave no verdict for this scene — it "
                    f"answered about scenes {strangers}, which it was not shown"
                )
            continue
        measured_scenes += 1
        scene_records.append(
            {
                "scene": scene["index"],
                "status": "MEASURED",
                "is_a_picture": verdict.is_a_picture,
                "one_picture": verdict.one_picture,
                "shows_the_scene": verdict.shows_the_scene,
                "reason": verdict.reason,
                # What a later film with the same picture must match to keep this verdict.
                "carry_key": keys.get(scene["index"]),
            }
        )
        if not verdict.is_a_picture:
            failures.append(
                f"Scene {scene['index']}: the frame is not a picture — "
                f"{verdict.reason or 'no scene in it'}"
            )
        elif not verdict.one_picture:
            # 2026-10-09: scene 5 was three stacked panels, and its clip animated them.
            failures.append(
                f"Scene {scene['index']}: the frame is not one picture (panels, a collage or a "
                f"blank band) — {verdict.reason or 'several pictures in one frame'}"
            )
        elif not verdict.shows_the_scene:
            failures.append(
                f"Scene {scene['index']}: the picture is not what the scene asked for — "
                f"{verdict.reason or 'it shows something else'}"
            )
    for index in unlooked:
        scene_records.append(
            {
                "scene": index,
                "status": "NOT_APPLICABLE",
                "is_a_picture": None,
                "one_picture": None,
                "shows_the_scene": None,
                "reason": "no frame was cut for this scene",
            }
        )
    scene_records += [
        _carried_scene(index, earlier, keys.get(index)) for index, earlier in carried.items()
    ]
    scene_records.sort(key=lambda entry: entry["scene"])

    # The scenes shown this time decide whether it measured anything: a look that answered
    # none of them certifies nothing, whatever an earlier film passed — unless it answered
    # about scenes it was not shown, which fails the check (2026-10-12 review).
    decided = bool(measured_scenes or failures)
    picture: dict[str, Any] = {
        "status": "MEASURED" if decided else "NOT_APPLICABLE",
        "passed": (not failures) if decided else None,
        "frames": len(frames),
        # SHOT: each scene's own shot, before the captions were burnt in; FILM: the film's.
        "frames_from": source,
        "scenes_measured": measured_scenes,
        # Passed by an earlier film with the same picture, or settled by the Director, and
        # not looked at again (2026-10-12).
        "scenes_carried": len(carried),
        "scenes": scene_records,
        "model_used": True,
        "looked_by": looker_name,
        "run_id": run_id,
        # The version a carried verdict must match (`carry_keys`).
        "template_version": TEMPLATE_VERSION,
    }
    if renumber is not None:
        picture["renumbered"] = {str(number): scene for number, scene in renumber.items()}
    if not measured_scenes:
        picture["detail"] = f"{looker_name} returned no verdict for any scene that was cut"

    character_records = list(not_applicable_characters)
    character_failures: list[str] = []
    # A character's scene is read back the same way its frame's was (`_renumbered`).
    by_pair = {
        ((renumber or {}).get(verdict.scene, verdict.scene), verdict.character.strip()): verdict
        for verdict in parsed.characters
    }
    measured_characters = 0
    observed_characters = 0
    for index, cid, basis in pairs:
        name = described[cid][2]
        person = by_pair.get((index, name))
        if person is None:
            character_records.append(
                {
                    "scene": index,
                    "character": name,
                    "basis": basis,
                    "status": "NOT_APPLICABLE",
                    "matches": None,
                    "reason": "no verdict was returned for this character in this scene",
                }
            )
            continue
        if basis == "guessed":
            # The storyboard did not put this person in the scene; its prose spelled the
            # name and the board refused to cast on it. What the model saw is worth
            # recording — it is the only place a reader can see what that guess was worth —
            # but a film is never failed for a person nobody said was in it, and a check
            # that measured only guesses has measured nothing.
            observed_characters += 1
            character_records.append(
                {
                    "scene": index,
                    "character": name,
                    "basis": basis,
                    "status": "OBSERVED",
                    "matches": person.matches,
                    "reason": person.reason,
                }
            )
            continue
        measured_characters += 1
        character_records.append(
            {
                "scene": index,
                "character": name,
                "basis": basis,
                "status": "MEASURED",
                "matches": person.matches,
                "reason": person.reason,
            }
        )
        if not person.matches:
            character_failures.append(
                f"Scene {index}: {name} is not the character the bible describes — "
                f"{person.reason or 'the person in the frame is someone else'}"
            )

    if characters_configured == 0:
        drift: dict[str, Any] = {
            "status": "NOT_IMPLEMENTED",
            "passed": None,
            "detail": "No character is configured in the bible; this check certifies nothing.",
        }
    elif measured_characters == 0:
        # Why nothing was measured, in the order the reasons actually rule each other out.
        # The last of them is the one this check used to print for all of them: it now means
        # only what it says — nobody listed anybody, and the board never said why.
        carried_cast = sum(
            1
            for scene in scenes
            if scene["index"] in carried
            for cid in scene["characters"]
            if cid in described
        )
        if carried_cast:
            detail = _CARRIED_CAST_DETAIL
        elif observed_characters:
            detail = (
                f"no scene in this film states who is in it; {observed_characters} name(s) "
                "its prose spells were looked at and certify nothing"
            )
        elif cast_note:
            detail = cast_note
        elif character_records:
            detail = "no character in this film could be compared with the bible"
        else:
            detail = "no scene in this film lists a character"
        drift = {"status": "NOT_APPLICABLE", "passed": None, "detail": detail}
    else:
        drift = {
            "status": "MEASURED",
            "passed": not character_failures,
            "detail": None,
        }
    drift.update(
        {
            "characters_configured": characters_configured,
            "characters_measured": measured_characters,
            # Looked at but not counted: the names the board read in the prose and refused
            # to cast on. Reported separately so a reader never mistakes them for evidence.
            "characters_observed": observed_characters,
            "characters": character_records,
            "reference_images": len(attached_references),
            "run_id": run_id,
        }
    )

    return {
        "picture_qc": picture,
        "character_drift_qc": drift,
        "failures": failures + character_failures,
    }


# ------------------------------------------------------------ one still, before motion
#
# The film-level look above runs after the money is spent. The stills gate
# (`app.media.still_gate`) asks the same department to look at each candidate still
# BEFORE a clip is bought: one call per still, at 1080 px. The frames above are 480 px,
# which is enough to see that a scene is a blank field and not enough to see a face in the
# lower third of a 9:16 picture.

STILL_TASK = "still_qc"
#: v2 (2026-10-09): one_picture, and a still is judged as ONE moment, the shot's first frame.
#: v3 (2026-10-12, evening): `scene_picture` is the scriptwriter's line (`writer_visual`), no
#: longer the compiled prompt again, and a script's line describes a movement or several
#: moments ("A slow drift through a dark particle-detector cavern…", "…dissolving into a
#: glowing spiral of particles, then a vast laboratory complex…" on the database copy): the
#: still is judged against its first moment, as against the plan's.
STILL_TEMPLATE_VERSION = "still-qc-v3"
#: The same, for a still bought after its scene's words were rewritten: it is also asked, item
#: by item, whether each mistake the rewrite answered is gone (`StillPlan.must_fix`,
#: `_FIXES_NOTE`). Only such a still is asked this way; any other is asked as above.
#: fixes2 (2026-10-12, late evening): each item is answered gone, minor or persists (the
#: Owner: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!»), the correction's words are guidance, not a
#: second plan, and an item about the movement is left to the clip, which is checked for it.
STILL_FIX_TEMPLATE_VERSION = "still-qc-v3-fixes2"
#: The most `must_fix` items one look answers (`fix_check.MAX_ITEMS` gives at most 4).
MAX_FIXES = 8
#: The answers one item may get (`fix_check.FIX_STATUSES`).
FixStatus = Literal["gone", "minor", "persists"]
#: The width the still is shown at. A 2K still (1530x2720) is scaled down to it.
STILL_WIDTH = 1080
#: The largest still read for judging; a vendor still is a few megabytes.
MAX_STILL_BYTES = 40_000_000

StillAction = Literal["buy_motion", "regenerate_still", "compose_locally"]

#: The question added on 2026-10-09, after scene 5 of «The Particle That Shouldn't Exist (But
#: Does)» came out as three stacked panels and every check passed it.
ONE_PICTURE = "one_picture"
#: The question added on 2026-10-12, after scene 5 of «… (And Briefly Didn't)» was bought
#: five paid rounds: each still matched its prompt and none showed the scene (a rock tunnel
#: for the detector cavern); only the film's picture QC, after the clip, said so.
SHOWS_SCENE = "shows_scene"


def _every_entry_answers(entries: Any, question: str) -> Any:
    """Refuse a model's report in which any entry leaves `question` out."""
    if isinstance(entries, list) and any(
        isinstance(entry, dict) and question not in entry for entry in entries
    ):
        raise ValueError(f"every entry must answer {question}")
    return entries


def _report_named(data: Any, key: str) -> Any:
    """Refuse a report object without its list (``stills``, ``clips``). `read_structured` tries
    every «{» of an answer: a refused report's own entry, read alone, was an empty report — «no
    answer for this scene», NOT_RUN — and the model was never asked again (the review of
    9ac0195, finding 8). A complete answer always names its list, so it reads as before."""
    if isinstance(data, dict) and key not in data:
        raise ValueError(f"the answer must be {{{key!r}: [...]}}, one entry per picture")
    return data


class FixAnswer(BaseModel):
    """The model's answer to one ``must_fix`` item (`StillPlan.must_fix`): is the mistake the
    rewrite was meant to correct gone from this still (or clip)? ``item`` is the item's number
    as shown (1-based); ``finding`` is replaced by the studio's own words for it once read
    (`judge_still`, `judge_clip`), so a refusal quotes what quality control said, not the
    model's paraphrase.

    ``status`` (2026-10-12, late evening; the Owner: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!»):
    gone; minor — a small trace is left, which the gate accepts as a warning on the take; or
    persists — the mistake is there again, which refuses it. Until then the answer was fixed
    true or false «even in part», so a still with Sarah's shoulder at the frame's edge, exactly
    as the correction asked, could be refused for «two women». ``seen`` is required for minor
    and persists (the refusal or the warning quotes it) and may be left out for gone. A legacy
    answer ``fixed`` true/false reads as gone/persists."""

    model_config = ConfigDict(extra="ignore")
    item: StrictInt = Field(ge=1)
    finding: str = Field(default="", max_length=300)
    status: FixStatus
    #: A few words on what the model sees where the mistake was.
    seen: str = Field(default="", max_length=300)
    _clip_finding = field_validator("finding", mode="before")(clipped(300))
    _clip_seen = field_validator("seen", mode="before")(clipped(300))

    @model_validator(mode="before")
    @classmethod
    def _legacy_fixed(cls, data: Any) -> Any:
        if isinstance(data, dict) and "status" not in data and isinstance(data.get("fixed"), bool):
            return {**data, "status": "gone" if data["fixed"] else "persists"}
        return data

    @field_validator("status", mode="before")
    @classmethod
    def _lower(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _seen_when_left(self) -> FixAnswer:
        if self.status != "gone" and not self.seen.strip():
            raise ValueError(
                f"item {self.item}: say in `seen` what you see when the mistake is {self.status}"
            )
        return self

    @property
    def fixed(self) -> bool:
        """Whether nothing of the mistake is left (the first version's answer)."""
        return self.status == "gone"


#: The first version's name for an item's answer, kept for its callers.
StillFix = FixAnswer


class StillVerdict(BaseModel):
    """What the model saw in one still. Every field is required and every yes/no is a
    real boolean: an answer that leaves a question out, or answers it in words, does not
    validate, and a still with no valid verdict is a still nobody looked at."""

    model_config = ConfigDict(extra="ignore")
    scene: StrictInt
    faces_visible: StrictBool
    readable_text: StrictBool
    matches_plan: StrictBool
    look_ok: StrictBool
    technical_ok: StrictBool
    #: One continuous photograph filling the frame: not a collage, a split screen, a grid,
    #: stacked panels, a comic strip or a picture with a blank or black band. Required of the
    #: model like every other answer: `StillJudgeReport`, the shape a model's answer is read
    #: into, refuses an entry without it. The default is only for a verdict built in code (the
    #: stills step's test fakes, written before the question): a model's silence never
    #: reads as one picture.
    one_picture: StrictBool = True
    #: Does the still show what the SCENE asks for — its written picture and the narration
    #: over it — not only what the prompt asked (`matches_plan`)? Required of the model like
    #: `one_picture`; the default is for verdicts built in code.
    shows_scene: StrictBool = True
    bible_violations: str = Field(min_length=1, max_length=300)
    verdict: StillAction
    reason: str = Field(min_length=1, max_length=300)
    #: The answer to each `StillPlan.must_fix` item (2026-10-12). Asked only of a still whose
    #: scene was rewritten, and then required for every item (`still_report_schema`); a still
    #: with nothing to verify is asked nothing and reads none.
    fixes: list[FixAnswer] = Field(default_factory=list, max_length=MAX_FIXES)
    _clip_violations = field_validator("bible_violations", mode="before")(clipped(300))
    _clip_reason = field_validator("reason", mode="before")(clipped(300))


def _every_fix_answered(entries: Sequence[Any], asked: int, what: str) -> None:
    """Refuse a report in which an entry leaves one of the ``asked`` items unanswered."""
    if not entries:
        # `read_structured` tries every «{» of the answer: the entry, nested in a refused
        # report, would otherwise validate as an empty report and read as «no answer for this
        # scene» without the model being asked again.
        raise ValueError(f"the answer must carry the {what}'s entry, with `fixes` for every item")
    for entry in entries:
        answered = {fix.item for fix in entry.fixes}
        missing = [number for number in range(1, asked + 1) if number not in answered]
        if missing:
            raise ValueError(
                f"the {what} of scene {entry.scene} must answer `fixes` for every must_fix "
                f"item: items {missing} are not answered"
            )


class StillJudgeReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    #: How many `must_fix` items this report must answer for every still (`still_report_schema`).
    #: 0: none were asked, and a ``fixes`` the model volunteers is not read, so a look with
    #: nothing to verify validates exactly as it did before the question existed.
    fixes_asked: ClassVar[int] = 0
    stills: list[StillVerdict] = Field(default_factory=list, max_length=4)

    @model_validator(mode="before")
    @classmethod
    def _names_its_stills(cls, data: Any) -> Any:
        return _report_named(data, "stills")

    @field_validator("stills", mode="before")
    @classmethod
    def _one_picture_answered(cls, value: Any) -> Any:
        value = _every_entry_answers(_every_entry_answers(value, ONE_PICTURE), SHOWS_SCENE)
        if cls.fixes_asked or not isinstance(value, list):
            return value
        return [
            {key: answer for key, answer in entry.items() if key != "fixes"}
            if isinstance(entry, dict)
            else entry
            for entry in value
        ]


def still_report_schema(asked: int) -> type[StillJudgeReport]:
    """The report a look is read into when it was asked about ``asked`` `must_fix` items:
    every still must answer each of them by its number — gone, minor or persists, with what it
    sees. An answer that leaves one out is refused and asked again (`structured_run`), like an
    entry without one_picture or shows_scene: silence never reads as «gone»."""
    if asked <= 0:
        return StillJudgeReport

    class FixesReport(StillJudgeReport):
        fixes_asked: ClassVar[int] = asked

        @model_validator(mode="after")
        def _every_fix_answered(self) -> FixesReport:
            _every_fix_answered(self.stills, asked, "still")
            return self

    return FixesReport


def fix_items(plan: Any) -> list[dict[str, str]]:
    """The ``must_fix`` items of a plan as the look is shown them (`MAX_FIXES` at most): what
    quality control saw (``finding``), the correction's words (``expected``, guidance) and,
    from her QC verdict, why it appeared (``cause``) when known."""
    items: list[dict[str, str]] = []
    for item in (getattr(plan, "must_fix", ()) or ())[:MAX_FIXES]:
        said = dict(item or {})
        shown = {
            "finding": str(said.get("finding") or ""),
            "expected": str(said.get("expected") or ""),
        }
        if said.get("cause"):
            shown["cause"] = str(said["cause"])
        items.append(shown)
    return items


def _studio_words(fixes: Sequence[FixAnswer], items: Sequence[Mapping[str, str]]) -> list[Any]:
    """The answers with the studio's own words for each finding; a number beyond the list
    answers nothing."""
    return [
        fix.model_copy(update={"finding": str(items[fix.item - 1]["finding"])[:300]})
        for fix in fixes
        if fix.item <= len(items)
    ]


@dataclass(frozen=True)
class StillJudgement:
    """The vision half of the stills gate. `verdict` is None whenever status is NOT_RUN."""

    status: str  # MEASURED | NOT_RUN
    verdict: StillVerdict | None
    detail_ro: str
    run_id: str | None
    looked_by: str | None
    image_width: int | None


_STILL_INSTRUCTIONS = (
    "You are the studio's quality control. Attached is ONE still, generated for scene "
    "{scene} of a factual short, before any money is spent on animating it. Judge only what "
    "you can see. The plan, the film's look and the visual bible's rules are below.\n"
    "A still is ONE moment: the first frame of the shot that will be animated from it. If "
    "the plan describes several moments (first one thing, then another), judge the still "
    "against the first moment only. A still that shows several moments at once, side by "
    "side or one above another, does not match the plan.\n"
    "Answer each question about this still:\n"
    "- faces_visible: is any human face visible, even small, partly turned or in the "
    "background? A figure seen only from behind, a silhouette or hands alone is not a face.\n"
    "- readable_text: is there any lettering, number, sign, caption or logo?\n"
    "- one_picture: is this ONE continuous photograph filling the whole frame from edge to "
    "edge? A collage, a split screen, a grid, panels stacked one above another, a comic "
    "strip, a picture inside a picture, or a picture with a blank or black band across it "
    "is not one picture.\n"
    "- matches_plan: does it show what the plan asks for, as one moment?\n"
    "- shows_scene: does it show what the SCENE asks for — the scene's written picture and "
    "the narration spoken over it, under `scene_picture` and `narration`? The plan is how "
    "the still was asked for; the scene is what the film needs. A picture that matches the "
    "plan's words but shows another place, another object or none of the scene's subject "
    "does not show the scene. The scene's written picture is the script's line and may "
    "describe a movement or several moments: the still is its first moment, so judge it "
    "against that moment. When no scene picture is given, judge by the plan.\n"
    "- look_ok: does it match the film's look (light, palette, grain)?\n"
    "- technical_ok: is it sharp where it should be, free of warped anatomy, smears, "
    "stripes or artefacts?\n"
    "- bible_violations: name the violation or write none. Check every rule listed.\n"
    "- verdict: buy_motion only if the still is right as it is (never when one_picture is "
    "false); regenerate_still if a new still could fix it; compose_locally if the plan asks "
    "for a chart, a title, numbers or a black screen, which the studio draws itself.\n"
    'Return only JSON: {{"stills": [{{"scene": {scene}, "faces_visible": false, '
    '"readable_text": false, "one_picture": true, "matches_plan": true, "shows_scene": true, '
    '"look_ok": true, "technical_ok": true, "bible_violations": "none", "verdict": '
    '"buy_motion", "reason": "one short sentence saying what you actually see"}}]}}\n'
)

#: Added to `_STILL_INSTRUCTIONS` only for a still with `must_fix` items (2026-10-12): the
#: scene's words were rewritten to correct mistakes quality control found, and this look says
#: whether the new picture still shows them, before any clip is bought on it.
#: 2026-10-12, late evening (the review of 9ac0195, finding 2): each item is answered gone,
#: minor or persists, never fixed false «even in part»; ``expected`` is guidance — what the
#: correction asked for counts as gone (Sarah's shoulder at the frame's edge, when the
#: correction asked for exactly that, is not «two women face to face»).
_FIXES_NOTE = (
    "This still was bought after the scene's words were rewritten to correct mistakes quality "
    "control found in the scene's earlier pictures. Each item under `must_fix` is one of them: "
    "`finding` is what quality control saw wrong, `expected` the words written to correct it "
    "(empty when only the finding is known) and `cause`, when given, why it appeared. "
    "`expected` is guidance: what it asks for is the correction, so a picture that shows what "
    "`expected` describes has the mistake gone, even where that looks a little like the "
    "finding (a person the correction puts at the frame's edge is not the person the finding "
    "saw in full view). For EVERY item, look at this still and answer in the still's `fixes`, "
    "by the item's number, one status: gone — the mistake is not in this picture; minor — a "
    "small trace of it is left that a viewer would hardly notice and the scene still reads as "
    "it should; persists — the picture shows the mistake again. An item about the movement, "
    "the ending or the cut, which one still cannot show, is gone here: the clip is checked for "
    "it. `seen` is a few words on what you see where the mistake was (required for minor and "
    "persists). A still with an item that persists does not get buy_motion.\n"
    'Each entry then also carries: "fixes": [{"item": 1, "finding": "the finding in a few '
    'words", "status": "gone" | "minor" | "persists", "seen": "what you see"}], one object per '
    "item.\n"
)


def still_image(ffmpeg: str | None, path: Path | str, width: int = STILL_WIDTH) -> str | None:
    """The still scaled to `width` px as base64 JPEG, or None when it cannot be made."""
    source = Path(path)
    if not ffmpeg or not source.is_file():
        return None
    try:
        if source.stat().st_size > MAX_STILL_BYTES:
            return None
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [
                ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                f"scale={width}:-2:flags=lanczos",
                "-q:v",
                "3",
                "-f",
                "image2pipe",
                "-c:v",
                "mjpeg",
                "pipe:1",
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    return base64.b64encode(result.stdout).decode("ascii")


def _still_not_run(
    detail: str,
    *,
    run_id: str | None = None,
    looked_by: str | None = None,
    width: int | None = None,
) -> StillJudgement:
    return StillJudgement(
        status="NOT_RUN",
        verdict=None,
        detail_ro=f"nu a fost privită: {detail}",
        run_id=run_id,
        looked_by=looked_by,
        image_width=width,
    )


def judge_still(
    engine: Engine,
    registry: Any | None,
    still_path: Path | str,
    plan: StillPlan,
    correlation_id: str,
    *,
    ffmpeg_path: str | None = None,
) -> StillJudgement:
    """One vision call on one candidate still, at 1080 px, by the LOOKERS.

    Returns MEASURED with the verdict only when the model answered for exactly this scene
    with every field; anything else is NOT_RUN ("nu a fost privită"), which the stills gate
    treats as a block. Nothing here passes a still by silence.

    A plan with `must_fix` items (2026-10-12, `fix_check.open_findings`) is shown them and
    asked, per item, whether the mistake is gone, left as a minor trace or persists
    (`_FIXES_NOTE`, STILL_FIX_TEMPLATE_VERSION); the answer must cover every item
    (`still_report_schema`) and its ``fixes`` carry the studio's words for each finding. A
    plan without them is asked exactly as before.
    """
    if registry is None or not registry.registered_ids():
        return _still_not_run("niciun furnizor de modele nu este înregistrat")
    with Session(engine) as session:
        looker = vision_agent(session, *LOOKERS)
    if looker is None:
        return _still_not_run("niciun angajat nu are un model care vede")
    looker_id, looker_name = looker
    image = still_image(find_ffmpeg(ffmpeg_path), still_path)
    if image is None:
        return _still_not_run(
            "imaginea nu a putut fi pregătită la 1080 px (lipsește codorul sau fișierul)",
            looked_by=looker_name,
        )
    # What the scene's words were rewritten to fix (`fix_check.open_findings`); empty for a
    # still with nothing open, which is then asked exactly as before (STILL_TEMPLATE_VERSION).
    must_fix = fix_items(plan)
    shown: dict[str, Any] = {
        "scene": plan.scene,
        "plan": plan.still_prompt,
        "scene_picture": getattr(plan, "scene_picture", "") or "",
        "narration": getattr(plan, "narration", "") or "",
        "purpose": getattr(plan, "purpose", "") or "",
    }
    if must_fix:
        # Before the look and the rules: the shown JSON is cut at 8000 characters, and these
        # items are what this look is for.
        shown["must_fix"] = [{"item": number, **item} for number, item in enumerate(must_fix, 1)]
    shown.update(
        {
            "look": plan.look_block,
            "camera_move": plan.camera_move,
            "faces_forbidden": plan.faces_forbidden,
            "bible_rules": list(plan.bible_rules),
        }
    )
    prompt = (
        _STILL_INSTRUCTIONS.format(scene=plan.scene)
        + (_FIXES_NOTE if must_fix else "")
        + wrap_in_inert_boundary(json.dumps(shown, ensure_ascii=False)[:8000], "the-still")
    )

    from app.agents.structured import structured_run  # noqa: PLC0415

    parsed, first, second = structured_run(
        engine,
        registry,
        looker_id,
        STILL_TASK,
        prompt,
        STILL_FIX_TEMPLATE_VERSION if must_fix else STILL_TEMPLATE_VERSION,
        correlation_id,
        still_report_schema(len(must_fix)),
        '{"stills": [...]}',
        summary=(
            f"Mă uit la imaginea scenei {plan.scene} înainte să se cumpere mișcarea"
            + (
                f" și verific dacă au dispărut greșelile pentru care scena a fost rescrisă "
                f"({len(must_fix)})."
                if must_fix
                else "."
            )
        ),
        max_tokens=800 + 150 * len(must_fix),
        temperature=0.1,
        extra={"images": [image]},
    )
    run = second or first
    run_id = run["id"]
    if parsed is None:
        return _still_not_run(
            f"{looker_name} nu a dat un verdict utilizabil ({run['status']})",
            run_id=run_id,
            looked_by=looker_name,
            width=STILL_WIDTH,
        )
    entries = [verdict for verdict in parsed.stills if verdict.scene == plan.scene]
    if len(entries) != 1:
        return _still_not_run(
            f"{looker_name} nu a răspuns pentru scena {plan.scene}"
            if not entries
            else f"{looker_name} a dat {len(entries)} verdicte pentru scena {plan.scene}",
            run_id=run_id,
            looked_by=looker_name,
            width=STILL_WIDTH,
        )
    verdict = entries[0]
    if must_fix:
        # The studio's own words for each item, not the model's echo of them.
        verdict = verdict.model_copy(update={"fixes": _studio_words(verdict.fixes, must_fix)})
    return StillJudgement(
        status="MEASURED",
        verdict=verdict,
        detail_ro=entries[0].reason,
        run_id=run_id,
        looked_by=looker_name,
        image_width=STILL_WIDTH,
    )


# ------------------------------------------------------------ one clip, before assembly
#
# A bought clip is looked at before it is cut into the film: three frames of it (the first,
# the middle and the last) in one call, at 1080 px, with the same plan, look and bible rules
# its still was judged against. Three frames see what one cannot: a face that turns toward
# the camera half-way, a picture that melts or changes place, writing that appears late.

CLIP_TASK = "clip_qc"
#: v2 (2026-10-09): one_picture; a clip made of panels goes back to its still.
#: v3 (2026-10-10): a film's frames come with `studio_text_note` (where they were cut from, and
#: the narration's subtitles named as the studio's) and, when their caption rows were cut out,
#: the strip of each below them; a bought clip's prompt is unchanged.
CLIP_TEMPLATE_VERSION = "clip-qc-v4"
#: The same, for a clip bought after the scene's movement was rewritten to correct what quality
#: control found (2026-10-12, late evening; the review of 9ac0195, finding 5): it is also asked,
#: item by item, whether each mistake is gone, minor or persists (`StillPlan.must_fix` of the
#: motion layer, `_CLIP_FIXES_NOTE`). Until then a finding treated in the motion's words was
#: put to the still, which cannot show a movement, answered «fixed» without looking, and was
#: never checked on the clip at all.
CLIP_FIX_TEMPLATE_VERSION = "clip-qc-v4-fixes"
#: The frames shown per clip, in order: first, middle, last.
CLIP_FRAMES = 3

ClipAction = Literal["keep", "regenerate_motion", "back_to_still"]


class ClipVerdict(BaseModel):
    """What the model saw in one clip's three frames. As with `StillVerdict`, every field is
    required and every yes/no is a real boolean; a clip with no valid verdict was not seen."""

    model_config = ConfigDict(extra="ignore")
    scene: StrictInt
    faces_visible: StrictBool
    readable_text: StrictBool
    matches_plan: StrictBool
    look_ok: StrictBool
    technical_ok: StrictBool
    same_shot: StrictBool
    #: Each frame is one continuous photograph, not panels. False means the still itself must
    #: change (clip QC routes it back to the still, never to another seed). Required of the
    #: model through `ClipJudgeReport`; the default is only for a verdict built in code, as on
    #: `StillVerdict`.
    one_picture: StrictBool = True
    bible_violations: str = Field(min_length=1, max_length=300)
    verdict: ClipAction
    reason: str = Field(min_length=1, max_length=300)
    #: The answer to each motion-layer ``must_fix`` item (2026-10-12), asked only of a clip
    #: whose scene's movement was rewritten (`clip_report_schema`), as on `StillVerdict`.
    fixes: list[FixAnswer] = Field(default_factory=list, max_length=MAX_FIXES)
    _clip_violations = field_validator("bible_violations", mode="before")(clipped(300))
    _clip_reason = field_validator("reason", mode="before")(clipped(300))


class ClipJudgeReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    #: How many ``must_fix`` items this report must answer for every clip (`clip_report_schema`);
    #: 0: none were asked, and a volunteered ``fixes`` is not read.
    fixes_asked: ClassVar[int] = 0
    clips: list[ClipVerdict] = Field(default_factory=list, max_length=4)

    @model_validator(mode="before")
    @classmethod
    def _names_its_clips(cls, data: Any) -> Any:
        return _report_named(data, "clips")

    @field_validator("clips", mode="before")
    @classmethod
    def _one_picture_answered(cls, value: Any) -> Any:
        value = _every_entry_answers(value, ONE_PICTURE)
        if cls.fixes_asked or not isinstance(value, list):
            return value
        return [
            {key: answer for key, answer in entry.items() if key != "fixes"}
            if isinstance(entry, dict)
            else entry
            for entry in value
        ]


def clip_report_schema(asked: int) -> type[ClipJudgeReport]:
    """The report a clip's look is read into when it was asked about ``asked`` items: every
    clip answers each, as `still_report_schema` asks it of a still."""
    if asked <= 0:
        return ClipJudgeReport

    class ClipFixesReport(ClipJudgeReport):
        fixes_asked: ClassVar[int] = asked

        @model_validator(mode="after")
        def _every_fix_answered(self) -> ClipFixesReport:
            _every_fix_answered(self.clips, asked, "clip")
            return self

    return ClipFixesReport


@dataclass(frozen=True)
class ClipJudgement:
    """The vision half of clip QC. `verdict` is None whenever status is NOT_RUN."""

    status: str  # MEASURED | NOT_RUN
    verdict: ClipVerdict | None
    detail_ro: str
    run_id: str | None
    looked_by: str | None
    image_width: int | None
    frames: int


_CLIP_INSTRUCTIONS = (
    "You are the studio's quality control. Attached are THREE frames of ONE generated clip "
    "for scene {scene} of a factual short, in order: the first frame, the middle frame and "
    "the last frame. {provenance} Judge only what you can see. The plan, the camera move asked "
    "for, its requested motion and ending frame, the film's look and the visual bible's "
    "rules are below. Explicitly requested motion or effects are not unrequested additions; "
    "still judge their execution, artefacts, faces, text and every bible rule. Prompt sources "
    "identify submitted requests versus a current storyboard that may have changed.\n"
    "{studio_note}"
    "Answer each question about the clip, looking at all three frames:\n"
    "- faces_visible: is any human face visible in ANY of the three frames, even small, "
    "partly turned or in the background? A figure seen only from behind, a silhouette or "
    "hands alone is not a face.\n"
    "- readable_text: is there any lettering, number, sign, caption or logo in any frame?\n"
    "- matches_plan: does the clip show what the plan asks for?\n"
    "- look_ok: does it keep the film's look (light, palette, grain) in every frame?\n"
    "- technical_ok: are all three frames free of warped or melting shapes, morphing "
    "bodies, smears, flicker artefacts and stripes?\n"
    "- same_shot: are the three frames one continuous shot of the same place, with no cut "
    "to another picture and nothing turning into something else?\n"
    "- one_picture: is each frame ONE continuous photograph filling the whole frame? A "
    "collage, a split screen, a grid, panels stacked one above another, a comic strip, or a "
    "frame with a blank or black band across it is not one picture.\n"
    "- bible_violations: name the violation or write none. Check every rule listed.\n"
    "- verdict: keep only if the clip is right as it is; regenerate_motion if animating the "
    "same still again could fix it; back_to_still if the still itself must change (always "
    "when one_picture is false: the same still animated again shows the same panels).\n"
    'Return only JSON: {{"clips": [{{"scene": {scene}, "faces_visible": false, '
    '"readable_text": false, "matches_plan": true, "look_ok": true, "technical_ok": true, '
    '"same_shot": true, "one_picture": true, "bible_violations": "none", "verdict": "keep", '
    '"reason": "one short sentence saying what you actually see"}}]}}\n'
)

#: What the clip is, said before the questions: a bought clip before the edit, or one scene of
#: the finished film looked at again by quality control (`qc.span_picture_qc`). Until
#: 2026-10-10 the film's scenes were described as clips not yet cut into the film.
_CLIP_BOUGHT = (
    "The clip was animated from an approved still and has not been cut into the film yet."
)
_CLIP_IN_FILM = "The clip is one scene of the finished film, looked at before it is delivered."
#: Added for a bought clip with motion-layer ``must_fix`` items (2026-10-12, late evening):
#: the movement's words were rewritten to correct what quality control found, and this look
#: says whether the clip shows the mistake again before it is cut into the film.
_CLIP_FIXES_NOTE = (
    "The scene's movement was rewritten to correct mistakes quality control found in its "
    "earlier clips. Each item under `must_fix` is one of them: `finding` is what quality "
    "control saw wrong, `expected` the words written to correct it (guidance: what it asks for "
    "is the correction) and `cause`, when given, why it appeared. `scene_picture` and "
    "`narration` say what the scene is. For EVERY item, look at the three frames (the last "
    "one is where the clip ends) and answer in the clip's `fixes`, by the item's number, one "
    "status: gone — the mistake is not in this clip; minor — a small trace of it is left that "
    "a viewer would hardly notice; persists — the clip shows the mistake again. `seen` is a "
    "few words on what you see where the mistake was (required for minor and persists). A clip "
    "with an item that persists does not get keep; it gets regenerate_motion unless the still "
    "itself must change.\n"
    'Each entry then also carries: "fixes": [{"item": 1, "finding": "the finding in a few '
    'words", "status": "gone" | "minor" | "persists", "seen": "what you see"}], one object per '
    "item.\n"
)


def _clip_not_run(
    detail: str,
    *,
    run_id: str | None = None,
    looked_by: str | None = None,
    width: int | None = None,
    frames: int = 0,
) -> ClipJudgement:
    return ClipJudgement(
        status="NOT_RUN",
        verdict=None,
        detail_ro=f"clipul nu a fost privit: {detail}",
        run_id=run_id,
        looked_by=looked_by,
        image_width=width,
        frames=frames,
    )


def judge_clip(
    engine: Engine,
    registry: Any | None,
    frame_paths: Sequence[Path | str],
    plan: StillPlan,
    correlation_id: str,
    *,
    motion_prompt: str = "",
    ending_frame: str = "",
    prompt_sources: Mapping[str, str] | None = None,
    ffmpeg_path: str | None = None,
    studio_text: StudioText | None = None,
) -> ClipJudgement:
    """One vision call on one clip's first, middle and last frames, at 1080 px, by the
    LOOKERS. MEASURED only when the model answered for exactly this scene with every field;
    anything else is NOT_RUN ("clipul nu a fost privit"), which clip QC treats as a block.

    ``studio_text`` is given for a scene of a finished film (`qc.span_picture_qc`): the model
    is told where the frames were cut from and that the narration's subtitles are the
    studio's own (`studio_text_note`), with the subtitle words over the scene when known; the
    strips below the caption rows it carries (FILM_CROPPED) are attached after the frames, one
    per frame, and a strip that cannot be prepared leaves the clip unseen, never judged on the
    upper part alone. A bought clip, judged before any edit, is asked exactly as before.

    A bought clip whose plan carries motion-layer ``must_fix`` items (2026-10-12, late evening,
    `fix_check.open_findings` with ``layer="motion"``) is also shown them with the scene's
    written picture and narration, and asked per item gone, minor or persists
    (`_CLIP_FIXES_NOTE`, CLIP_FIX_TEMPLATE_VERSION, `clip_report_schema`)."""
    if len(frame_paths) != CLIP_FRAMES:
        return _clip_not_run(f"s-au tăiat {len(frame_paths)} cadre, nu {CLIP_FRAMES}")
    strips = studio_text.below_captions if studio_text is not None else ()
    if strips and len(strips) != CLIP_FRAMES:
        return _clip_not_run(
            f"s-au tăiat {len(strips)} fâșii de sub subtitrări, nu {CLIP_FRAMES}: partea de jos "
            "a cadrelor nu ar fi fost privită"
        )
    if registry is None or not registry.registered_ids():
        return _clip_not_run("niciun furnizor de modele nu este înregistrat")
    with Session(engine) as session:
        looker = vision_agent(session, *LOOKERS)
    if looker is None:
        return _clip_not_run("niciun angajat nu are un model care vede")
    looker_id, looker_name = looker
    ffmpeg = find_ffmpeg(ffmpeg_path)
    images = [still_image(ffmpeg, path) for path in (*frame_paths, *strips)]
    if any(image is None for image in images):
        return _clip_not_run(
            "cadrele nu au putut fi pregătite la 1080 px (lipsește codorul sau fișierul)",
            looked_by=looker_name,
        )
    shown = {
        "scene": plan.scene,
        "plan": plan.still_prompt,
        "camera_move": plan.camera_move,
        "motion": motion_prompt,
        "ending_frame": ending_frame,
        "prompt_sources": dict(prompt_sources or {}),
        "look": plan.look_block,
        "faces_forbidden": plan.faces_forbidden,
        "bible_rules": list(plan.bible_rules),
    }
    if studio_text is not None and studio_text.source != "SHOT" and studio_text.subtitles:
        # The words are the narration's, written by the studio's own writers from researched
        # sources: data like the plan, so they travel inside the inert boundary with it.
        shown["studio_subtitles"] = list(studio_text.subtitles[:MAX_SUBTITLE_LINES])
    # What the scene's movement was rewritten to fix (`fix_check.open_findings`, motion layer);
    # only a bought clip is asked it, and a clip with nothing open is asked exactly as before.
    must_fix = fix_items(plan) if studio_text is None else []
    if must_fix:
        shown["scene_picture"] = getattr(plan, "scene_picture", "") or ""
        shown["narration"] = getattr(plan, "narration", "") or ""
        shown["must_fix"] = [{"item": number, **item} for number, item in enumerate(must_fix, 1)]
    prompt = (
        _CLIP_INSTRUCTIONS.format(
            scene=plan.scene,
            provenance=_CLIP_BOUGHT if studio_text is None else _CLIP_IN_FILM,
            studio_note=studio_text_note(studio_text),
        )
        + (_CLIP_FIXES_NOTE if must_fix else "")
        + wrap_in_inert_boundary(json.dumps(shown, ensure_ascii=False)[:8000], "the-clip")
    )

    from app.agents.structured import structured_run  # noqa: PLC0415

    parsed, first, second = structured_run(
        engine,
        registry,
        looker_id,
        CLIP_TASK,
        prompt,
        CLIP_FIX_TEMPLATE_VERSION if must_fix else CLIP_TEMPLATE_VERSION,
        correlation_id,
        clip_report_schema(len(must_fix)),
        '{"clips": [...]}',
        summary=(
            (
                f"Mă uit la clipul scenei {plan.scene} înainte să intre în film"
                + (
                    " și verific dacă au dispărut greșelile pentru care mișcarea a fost "
                    f"rescrisă ({len(must_fix)})."
                    if must_fix
                    else "."
                )
            )
            if studio_text is None
            else (
                f"Mă uit la scena {plan.scene} din filmul terminat; subtitrările studioului nu "
                "se socotesc text."
            )
        ),
        max_tokens=800 + 150 * len(must_fix),
        temperature=0.1,
        extra={"images": [image for image in images if image is not None]},
    )
    run = second or first
    run_id = run["id"]
    if parsed is None:
        return _clip_not_run(
            f"{looker_name} nu a dat un verdict utilizabil ({run['status']})",
            run_id=run_id,
            looked_by=looker_name,
            width=STILL_WIDTH,
            frames=CLIP_FRAMES,
        )
    entries = [verdict for verdict in parsed.clips if verdict.scene == plan.scene]
    if len(entries) != 1:
        return _clip_not_run(
            f"{looker_name} nu a răspuns pentru scena {plan.scene}"
            if not entries
            else f"{looker_name} a dat {len(entries)} verdicte pentru scena {plan.scene}",
            run_id=run_id,
            looked_by=looker_name,
            width=STILL_WIDTH,
            frames=CLIP_FRAMES,
        )
    verdict = entries[0]
    if must_fix:
        # The studio's own words for each item, not the model's echo of them.
        verdict = verdict.model_copy(update={"fixes": _studio_words(verdict.fixes, must_fix)})
    return ClipJudgement(
        status="MEASURED",
        verdict=verdict,
        detail_ro=entries[0].reason,
        run_id=run_id,
        looked_by=looker_name,
        image_width=STILL_WIDTH,
        frames=CLIP_FRAMES,
    )
