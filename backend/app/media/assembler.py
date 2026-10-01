"""Deterministic Video Assembler & FFmpeg Engine.

Following docs/architecture/08_VIDEO_PIPELINE.md:
- Generates timed SRT/VTT subtitles.
- Assembles vertical 9:16 video (1080x1920) with deterministic fallback.
- Uses safe subprocess argument arrays without shell interpolation.
- Calculates SHA-256 byte digest for absolute asset provenance.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import math
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import ROOT
from app.media.cards import CARD_KINDS, CardError, card_spec_from_json, compose_card
from app.media.cost_plan import (
    STILL_CANDIDATES,
    STILLS_MODEL,
    STILLS_RESOLUTION,
    PriceTable,
    UnpricedError,
    credits_to_micros,
    load_price_table,
    price_still,
    source_label,
)
from app.media.models import (
    MediaAsset,
    SceneTake,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.production_policy import (
    FailureVerdict,
    ModelCapability,
    need_from_scene,
    plan_scene_models,
    record_quoted_price,
    replan_after_failure,
)
from app.media.prompt_lint import LintScene, has_block, lint_film, summary_ro
from app.media.speaker_voices import SPEAKER_GAP_SECONDS
from app.media.toolchain import (
    AUDIO_CODEC_ARGS,
    AUDIO_CODEC_LABEL,
    LOUDNESS_TARGET_LUFS,
    MASTER_SAMPLE_RATE,
    TRUE_PEAK_CEILING_DBTP,
    TRUE_PEAK_TARGET_DBTP,
    AudioMasterError,
    encode_master_audio,
    find_ffmpeg,
    has_filter,
    measure_loudness,
)
from app.providers.deterministic_media import (
    DeterministicTTSAdapter,
    DeterministicVisualAdapter,
)
from app.providers.media_base import ImageProvider, TTSProvider, VideoProvider
from app.providers.media_http import MediaProviderError, MediaProviderNotConfigured
from app.services import append_event, utc_now


def _at_work(engine: Engine | None, role_name: str, task_type: str, detail: str) -> Any:
    """The employee doing this step shows as WORKING while it runs. Nothing for placeholders."""
    if engine is None:
        return nullcontext()
    from app.agents.services import at_work  # noqa: PLC0415 - agents imports media models

    return at_work(engine, role_name, task_type, detail)


logger = logging.getLogger("studio.assembler")

DEFAULT_STORAGE_ROOT = ROOT / "backend" / "storage" / "media"

#: The headroom a generated shot is asked for beyond its scene: at least the longest dissolve
#: it may have to cover. Films used to dissolve everywhere by this much; since 2026-10-01 they
#: cut, and dissolve (DISSOLVE_SECONDS) only where the script asks.
TRANSITION_SECONDS = 0.4

#: The film's timeline: the vendor's native 24 fps. Runway delivers 24/1 (the four Nepal
#: clips, one of them 10-bit HEVC); a 30 fps timeline copied every fifth frame of them.
TIMELINE_FPS = 24
#: A dissolve, where the script asks for one: eight frames at 24 fps, inside 0.25-0.4 s.
DISSOLVE_SECONDS = 8 / TIMELINE_FPS
#: What ``transition_in`` says when the writer wants the shot before to mix into this one.
#: Anything else, the default CUT included, is a hard cut. The first scene has nothing before it.
DISSOLVE_WORDS: tuple[str, ...] = ("DISSOLVE", "CROSSFADE", "CROSS_DISSOLVE", "MIX", "FADE")
#: A scene lasts its words plus this breath, never past its plan, never cutting a word.
SPOKEN_TAIL_SECONDS = 0.35
#: Quality control fails a film longer than its narration plus 1.0 s; the breaths are shortened
#: together so the film stays under this, a tenth of a second inside that line.
FILM_OVER_NARRATION_SECONDS = 0.9

#: How long one scene's motion may take, and how often the task is asked about.
MOTION_DEADLINE_SECONDS = 600
MOTION_POLL_SECONDS = 5

#: Recorded on every asset produced from locally synthesised placeholder frames. The QC gate
#: refuses to pass such an asset for publication: placeholder cards are not real footage.
PLACEHOLDER_VISUAL_PROVIDER = "PLACEHOLDER_DETERMINISTIC_VISUALS"
PLACEHOLDER_VOICE_PROVIDER = "PLACEHOLDER_DETERMINISTIC_VOICE"


class RenderEngineUnavailable(RuntimeError):
    """Raised when no real video encoder is available.

    The studio never writes a stand-in file with an .mp4 name: a render either produces a real
    encoded video or it fails, so that no downstream gate can be satisfied by a fake artefact.
    """


class RenderStopped(RuntimeError):
    """The Owner set AUTONOMIE OPRITĂ while the film was being made, and the render stopped.

    Between two scenes, never mid-write: the scene already voiced is on disk, the next one is
    not started, the job is FAILED with this reason and no asset is recorded. The media stage
    reports it BLOCKED (the Owner's decision), not FAILED (a fault), so no safe mode opens.
    """


#: What the render job says when the Owner's switch ends it between two scenes.
STOP_REASON = (
    "Randarea s-a oprit între scene: AUTONOMIE OPRITĂ a fost setată de Owner în timpul "
    "filmării. Scenele deja făcute rămân pe disc; nimic nu a fost înregistrat ca film."
)


def resolve_ffmpeg_path(custom_path: str | None = None) -> str | None:
    """Return path to ffmpeg executable if available.

    Delegates to the one resolver the whole studio uses, so the renderer, quality control and
    the preflight check can never disagree about whether an encoder exists. They did: this
    function looked at the environment and PATH only, while the Owner's encoder was configured
    in ``.env`` — so renders failed with "FFmpeg is not installed" on a machine that had it.
    """
    return find_ffmpeg(custom_path)


def _scene_palette(scene_index: int) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Deterministic top/bottom gradient colours for a placeholder scene frame."""
    top_colors = [(11, 19, 41), (7, 30, 48), (18, 14, 45), (5, 26, 34), (26, 12, 32)]
    top = top_colors[(scene_index - 1) % len(top_colors)]
    return top, (2, 6, 23)


def write_placeholder_frame_ppm(
    path: Path, scene_index: int, width: int = 1080, height: int = 1920
) -> None:
    """Write a real raster frame (binary PPM) that ffmpeg can encode.

    This is an honest placeholder: a deterministic gradient card, not generated artwork.
    """
    (r0, g0, b0), (r1, g1, b1) = _scene_palette(scene_index)
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    rows = bytearray()
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(r0 + (r1 - r0) * t)
        g = int(g0 + (g1 - g0) * t)
        b = int(b0 + (b1 - b0) * t)
        # Horizontal accent band marks the scene boundary visually.
        if abs(t - (scene_index % 5) / 5.0) < 0.004:
            r, g, b = 56, 189, 248
        rows += bytes((r, g, b)) * width
    path.write_bytes(header + bytes(rows))


#: What a phone can read: two lines of forty-two characters, the convention broadcast
#: captioning and the platforms' own caption editors share. The SRT beside the film keeps to
#: it, and quality control reads it back against it.
CAPTION_LINE_CHARS = 42
CAPTION_MAX_LINES = 2

#: A caption is a card of two to five words (2026-10-01): read at a glance on a phone, and
#: changed as the voice moves on. A whole sentence on screen was read ahead of the voice. A
#: passage of a single word is one card of one word; nowhere else is a word left alone.
CAPTION_MIN_WORDS = 2
CAPTION_MAX_WORDS = 5

#: The legacy SRT style, kept for films rendered before the ASS captions: a one-scene redo of
#: such a film burns its SRT again exactly as the film was made.
CAPTION_STYLE = (
    "FontName=Arial,FontSize=7.5,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
    "BorderStyle=1,Outline=0.9,Shadow=0,Alignment=2,MarginV=58,MarginL=10,MarginR=10"
)

#: The burnt captions are an ASS script at the film's own resolution, so every size below is
#: in pixels of the 1080x1920 frame. The face is the studio's bundled Inter Bold (verified by
#: its pinned SHA-256 in app.media.cards), handed to libass in a fonts folder beside the film.
CAPTION_PLAY_RES = (1080, 1920)
#: ASS sizes a font by its line cell, not its em: 66 is Inter Bold at an em of about 54.5 px.
CAPTION_FONT_SIZE = 66
CAPTION_OUTLINE = 3.5
#: The smallest a card may be set when one word will not fit a line at the full size.
CAPTION_MIN_FONT_SIZE = 40
#: Where a caption may draw: inside the cards' SAFE_RECT (x 90-990, y 300-1540), with its
#: bottom edge at or above y 1500 and clear of the right 120 px, the platform's buttons.
CAPTION_BOTTOM_Y = 1500
CAPTION_RIGHT_CLEAR = 120
#: libass margins that keep it there: the text box ends at y 1920 - 432 = 1488, which leaves
#: the outline and the descenders (measured: 2 px below the box) above 1500; 132 px a side
#: keeps the outline between x 128 and 952.
CAPTION_MARGIN_V = 432
CAPTION_MARGIN_X = 132
#: The widest a caption line may be set: the space between the margins less the outline on
#: both sides, and 4% for the shaping (kerning) a metric sum does not see.
CAPTION_LINE_PX = (CAPTION_PLAY_RES[0] - 2 * CAPTION_MARGIN_X - 2 * CAPTION_OUTLINE) * 0.96
#: The folder beside the film that libass reads the face from.
CAPTION_FONTS_DIR = "fonts"
CAPTIONS_ASS_NAME = "captions.ass"

#: Where a sentence or a clause ends: a card ends there when it has words enough.
_SENTENCE_MARKS = (".", "!", "?", "…")
_CLAUSE_MARKS = (",", ";", ":", "–", "—")
_CLOSERS = "\"'”’»)]"


def format_srt_timestamp(seconds: float) -> str:
    """Format float seconds to SubRip timestamp: HH:MM:SS,mmm"""
    # Rounded once, as whole milliseconds: rounding the fraction on its own could carry
    # 999.6 ms to 1000 and print a thousand milliseconds against the previous second.
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hrs, rest = divmod(total_ms, 3_600_000)
    mins, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def _wrap_words(words: list[str], width: int) -> list[str]:
    """Greedy word wrapping to lines of at most ``width`` characters, no word lost."""
    lines: list[str] = []
    current = ""
    for word in words:
        # A word longer than a line is cut into line-sized pieces rather than overflowing:
        # a caption line over the limit is the one thing quality control refuses outright.
        pieces = [word[i : i + width] for i in range(0, len(word), width)] or [word]
        for piece in pieces:
            if not current:
                current = piece
            elif len(current) + 1 + len(piece) <= width:
                current = f"{current} {piece}"
            else:
                lines.append(current)
                current = piece
    if current:
        lines.append(current)
    return lines


def _caption_px(text: str, size: float = CAPTION_FONT_SIZE) -> float:
    """How wide ``text`` is burnt at ASS size ``size``, from the bundled font's own metrics.

    Without the font (missing or altered, which the burn itself then refuses) a generous
    estimate stands in, so the SRT is still written.
    """
    from app.media import cards  # noqa: PLC0415 - cards imports nothing of this module

    try:
        return cards.text_width(text, cards.em_for_cell(size))
    except cards.CardError:
        return len(text) * size * 0.62


def _fits_line(text: str) -> bool:
    return len(text) <= CAPTION_LINE_CHARS and _caption_px(text) <= CAPTION_LINE_PX


def _card_lines(words: list[str]) -> list[str] | None:
    """A card's words as one line, or two lines of about equal width, that fit both the SRT
    (forty-two characters) and the burnt frame; None when they do not fit two lines."""
    text = " ".join(words)
    if _fits_line(text):
        return [text]
    best: tuple[float, list[str]] | None = None
    for cut in range(1, len(words)):
        top, bottom = " ".join(words[:cut]), " ".join(words[cut:])
        if _fits_line(top) and _fits_line(bottom):
            balance = abs(_caption_px(top) - _caption_px(bottom))
            if best is None or balance < best[0]:
                best = (balance, [top, bottom])
    return best[1] if best else None


def _ends_with(word: str, marks: tuple[str, ...]) -> bool:
    return word.rstrip(_CLOSERS).endswith(marks)


def caption_cards(words: list[str]) -> list[list[str]]:
    """A passage's words as caption cards of two to five words.

    A card ends at a sentence's end once it has two words, at a clause's end once it has
    three, at five words, or before a word that would not fit two lines. A last word is never
    left alone: it joins the card before it, or takes that card's last word with it.
    """
    groups: list[list[str]] = []
    current: list[str] = []
    for position, word in enumerate(words):
        if len(current) >= CAPTION_MIN_WORDS and _card_lines([*current, word]) is None:
            groups.append(current)
            current = []
        current.append(word)
        left = len(words) - position - 1
        full = len(current) >= CAPTION_MAX_WORDS
        sentence = len(current) >= CAPTION_MIN_WORDS and _ends_with(word, _SENTENCE_MARKS)
        clause = len(current) >= CAPTION_MIN_WORDS + 1 and _ends_with(word, _CLAUSE_MARKS)
        if full or sentence or clause:
            if left == 1 and not full and _card_lines([*current, words[-1]]) is not None:
                continue  # the passage's last word joins this card instead of standing alone
            groups.append(current)
            current = []
    if current:
        if len(current) == 1 and groups:
            last = groups[-1]
            if len(last) < CAPTION_MAX_WORDS and _card_lines([*last, *current]) is not None:
                last.extend(current)
            elif len(last) > CAPTION_MIN_WORDS:
                current.insert(0, last.pop())
                groups.append(current)
            else:
                groups.append(current)
        else:
            groups.append(current)
    return groups


def words_from_alignment(alignment: Any) -> list[dict[str, Any]] | None:
    """ElevenLabs' character alignment (``characters``, ``character_start_times_seconds``,
    ``character_end_times_seconds``) read as words: each run of non-space characters, from its
    first character's start to its last character's end. None when it is not that shape."""
    if not isinstance(alignment, dict):
        return None
    characters = alignment.get("characters")
    starts = alignment.get("character_start_times_seconds")
    ends = alignment.get("character_end_times_seconds")
    if not (
        isinstance(characters, list)
        and isinstance(starts, list)
        and isinstance(ends, list)
        and characters
        and len(characters) == len(starts) == len(ends)
    ):
        return None
    words: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for char, start, end in zip(characters, starts, ends, strict=True):
        if (
            not isinstance(char, str)
            or not isinstance(start, int | float)
            or not isinstance(end, int | float)
        ):
            return None
        if not char.strip():
            if current is not None:
                words.append(current)
                current = None
            continue
        if current is None:
            current = {"word": char, "start": float(start), "end": float(end)}
        else:
            current["word"] += char
            current["end"] = float(end)
    if current is not None:
        words.append(current)
    return words or None


def take_word_timing(said: Any) -> list[dict[str, Any]] | None:
    """The word timing a voice take came back with: the vendor's own alignment first (the
    ElevenLabs /with-timestamps shape), else the adapter's ``word_timings``; None when the
    take carries neither. Nothing is estimated here."""
    raw = getattr(said, "raw_response", None)
    if isinstance(raw, dict):
        for key in ("alignment", "normalized_alignment"):
            words = words_from_alignment(raw.get(key))
            if words:
                return words
    timings = getattr(said, "word_timings", None)
    if isinstance(timings, list) and timings:
        words = [
            {"word": str(t.get("word") or ""), "start": float(t["start"]), "end": float(t["end"])}
            for t in timings
            if isinstance(t, dict)
            and isinstance(t.get("start"), int | float)
            and isinstance(t.get("end"), int | float)
        ]
        if len(words) == len(timings):
            return words
    return None


def _aligned_starts(words: list[str], timed: Any, span: float) -> list[float] | None:
    """Each word's start from the take's timing, when that timing is about these words: as
    many timed words as words said, in order, inside the take. Otherwise None."""
    if not isinstance(timed, list) or len(timed) != len(words) or not words:
        return None
    starts: list[float] = []
    for item in timed:
        start = item.get("start") if isinstance(item, dict) else None
        if not isinstance(start, int | float) or not math.isfinite(float(start)):
            return None
        if float(start) < -0.001 or float(start) > span + 0.5:
            return None
        if starts and float(start) < starts[-1] - 0.001:
            return None
        starts.append(max(0.0, float(start)))
    return starts


def caption_cues(scenes: list[dict]) -> list[dict[str, Any]]:
    """Caption cues from the narration: cards of two to five words, timed to each scene's own
    recording.

    A scene begins where the scenes before it end (their ``duration_seconds``), and its words
    last as long as the narration recorded for it (``audio_seconds``; the planned length when
    nothing was recorded). A take that came back with the voice's own word timing (``words`` on
    the take, ``word_timings`` on a scene read whole) puts each card up on its first word;
    otherwise the take's time is shared by the cards' characters. A scene with no words has no
    cue: a caption is never invented from a visual prompt.

    A scene spoken as takes, one per speaker (``voice_segments``: each take's words, where it
    starts inside the scene and how long it lasts), is captioned take by take, and the breath
    between two speakers has no caption, so the words on screen change when the voice does.
    """
    cues: list[dict[str, Any]] = []
    clock = 0.0
    for scene in scenes:
        planned = float(scene.get("duration_seconds") or 0.0)
        spoken = scene.get("audio_seconds")
        span = float(spoken) if isinstance(spoken, int | float) and spoken > 0 else planned
        if planned > 0:
            # Words never spill into the next scene, whose own words start there.
            span = min(span, planned)
        text = " ".join(str(scene.get("voiceover_segment") or "").split())
        takes = scene.get("voice_segments")
        if isinstance(takes, list) and takes and span > 0:
            for take in takes:
                offset = float(take.get("offset") or 0.0)
                if offset >= span:
                    break
                length = min(float(take.get("seconds") or 0.0), span - offset)
                words = " ".join(str(take.get("text") or "").split())
                if words and length > 0:
                    cues.extend(
                        _timed_cues(
                            words,
                            clock + offset,
                            length,
                            scene.get("scene_index"),
                            take.get("words"),
                        )
                    )
        elif text and span > 0:
            cues.extend(
                _timed_cues(text, clock, span, scene.get("scene_index"), scene.get("word_timings"))
            )
        clock += planned
    return cues


def _timed_cues(
    text: str, begin: float, span: float, scene_index: Any, timed: Any = None
) -> list[dict[str, Any]]:
    """One passage's cards, sharing ``span`` seconds from ``begin``: from the take's word
    timing when it matches the words, else by the cards' characters."""
    words = text.split()
    groups = caption_cards(words)
    starts = _aligned_starts(words, timed, span)
    cues: list[dict[str, Any]] = []
    if starts is not None:
        firsts: list[float] = []
        position = 0
        for group in groups:
            firsts.append(min(starts[position], span))
            position += len(group)
        previous_end = begin
        for index, group in enumerate(groups):
            start = max(begin + firsts[index], previous_end)
            end = begin + (firsts[index + 1] if index + 1 < len(groups) else span)
            # A card is up for at least a frame, and never past the passage.
            end = min(max(end, start + 1 / TIMELINE_FPS), begin + span)
            if end <= start:
                continue
            cues.append(_cue(scene_index, start, end, group, "alignment"))
            previous_end = end
        return cues
    weights = [len(" ".join(group)) for group in groups]
    total_weight = float(sum(weights)) or 1.0
    start = begin
    elapsed = 0
    for position, (group, weight) in enumerate(zip(groups, weights, strict=True)):
        elapsed += weight
        # The last cue ends exactly where the narration does, whatever rounding the shares
        # before it accumulated.
        end = (
            begin + span if position == len(groups) - 1 else begin + span * (elapsed / total_weight)
        )
        cues.append(_cue(scene_index, start, end, group, "character_share"))
        start = end
    return cues


def _cue(
    scene_index: Any, start: float, end: float, words: list[str], timing: str
) -> dict[str, Any]:
    lines = _card_lines(words) or _wrap_words(words, CAPTION_LINE_CHARS)[:CAPTION_MAX_LINES]
    return {
        "scene_index": scene_index,
        "start": start,
        "end": end,
        "lines": lines,
        "timing": timing,
    }


def srt_from_cues(cues: list[dict[str, Any]]) -> str:
    """The cues as a SubRip file: index, timing, lines, blank line."""
    blocks: list[str] = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n{format_srt_timestamp(cue['start'])} --> "
            f"{format_srt_timestamp(cue['end'])}\n" + "\n".join(cue["lines"]) + "\n"
        )
    return "\n".join(blocks)


def generate_subtitles_srt(scenes: list[dict]) -> str:
    """Generate valid SubRip (SRT) subtitles, cards of two to five words, timed to the voice."""
    return srt_from_cues(caption_cues(scenes))


def _ass_time(seconds: float) -> str:
    """ASS timestamps: H:MM:SS.cc, in whole centiseconds."""
    total = max(0, int(round(float(seconds) * 100)))
    hours, rest = divmod(total, 360_000)
    minutes, rest = divmod(rest, 6_000)
    secs, centis = divmod(rest, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _ass_text(line: str) -> str:
    """A caption line as ASS event text: braces open override blocks and a backslash starts
    an escape, so neither reaches the renderer as written."""
    return line.replace("\\", "/").replace("{", "(").replace("}", ")")


def ass_from_cues(cues: list[dict[str, Any]]) -> str:
    """The burnt captions as an ASS script at 1080x1920: Inter Bold at size 66, a 3.5 px dark
    outline, bottom-centred inside the safe area. A card whose longest line would not fit at
    66 is set smaller for that card alone, never below 40, never outside the margins."""
    from app.media import cards  # noqa: PLC0415

    family = cards.font_family(cards.BOLD)
    width, height = CAPTION_PLAY_RES
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{family},{CAPTION_FONT_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,"
        f"&H00000000,-1,0,0,0,100,100,0,0,1,{CAPTION_OUTLINE:g},0,2,{CAPTION_MARGIN_X},"
        f"{CAPTION_MARGIN_X},{CAPTION_MARGIN_V},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in cues:
        widest = max((_caption_px(line) for line in cue["lines"]), default=0.0)
        override = ""
        if widest > CAPTION_LINE_PX:
            size = max(
                CAPTION_MIN_FONT_SIZE, math.floor(CAPTION_FONT_SIZE * CAPTION_LINE_PX / widest)
            )
            override = f"{{\\fs{size}}}"
        start, end = _ass_time(cue["start"]), _ass_time(cue["end"])
        if end <= start:
            end = _ass_time(float(cue["start"]) + 0.01)
        text = "\\N".join(_ass_text(line) for line in cue["lines"])
        lines.append(f"Dialogue: 0,{start},{end},Caption,,0,0,0,,{override}{text}")
    return "\n".join(lines) + "\n"


def install_caption_fonts(folder: Path) -> Path:
    """Put the verified Inter Bold in ``folder``/fonts for libass, and return that folder.

    The bytes copied are the bytes whose SHA-256 is pinned in app.media.cards; a missing or
    altered font raises (CardError) and nothing is burnt with whatever the system has.
    """
    from app.media import cards  # noqa: PLC0415

    source = cards.font_path(cards.BOLD)
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != cards.FONT_SHA256[cards.BOLD]:
        raise cards.FontIntegrityError(f"Fontul {cards.BOLD} s-a schimbat pe disc.")
    target = folder / CAPTION_FONTS_DIR
    target.mkdir(parents=True, exist_ok=True)
    copy = target / cards.BOLD
    if not copy.is_file() or copy.read_bytes() != data:
        copy.write_bytes(data)
    return target


def ass_captions_filter(name: str = CAPTIONS_ASS_NAME, fontsdir: str = CAPTION_FONTS_DIR) -> str:
    """The ffmpeg filter that burns the ASS captions, with the face from ``fontsdir``.

    Both are named relative to the encoder's working directory (the film's folder): the
    filter's option parser reads a colon as a separator, so an absolute Windows path would
    need escaping twice over.
    """
    return f"subtitles=filename={name}:fontsdir={fontsdir}"


def captions_filter(srt_name: str = "captions.srt") -> str:
    """The legacy filter that burned the SRT with CAPTION_STYLE: films rendered before the ASS
    captions are rejoined with it, so a one-scene redo keeps the captions they had."""
    return f"subtitles=filename={srt_name}:force_style='{CAPTION_STYLE}'"


#: The joined narration before mastering: mono, 48 kHz, 24-bit PCM — lossless, so the film's
#: sound is encoded to AAC exactly once.
_VOICE_WAV_ARGS: tuple[str, ...] = (
    "-ac",
    "1",
    "-ar",
    str(MASTER_SAMPLE_RATE),
    "-c:a",
    "pcm_s24le",
)
#: The joined narration beside the film, and the mastered track that goes into it.
VOICE_TRACK_NAME = "master_audio.wav"
MASTERED_TRACK_NAME = "master_audio_final.m4a"


def _concatenate_audio(
    ffmpeg_exe: str,
    segments: list[Path],
    work_dir: Path,
    pads: list[float] | None = None,
    name: str = VOICE_TRACK_NAME,
) -> Path:
    """Join the per-scene narration files into one track, with ffmpeg rather than by hand.

    The placeholder path can splice raw WAV bodies because it produced them itself and knows
    their format. A provider's audio is whatever the vendor encoded, so it is concatenated by
    the decoder instead of by byte surgery, which would silently corrupt a differing format.

    ``pads`` is the silence after each segment, in seconds: the breath between two speakers
    of a scene, and after a scene's last take whatever its picture lasts beyond its words,
    so the next scene's words start with the next scene's shot. With any silence to add the
    segments are decoded and joined by the concat filter, each padded with ``apad``.

    The joined track is a 48 kHz, 24-bit WAV (``name``): the one lossy encode of the film's
    sound is the master's, not this. It used to be AAC here and AAC again in the film.
    """
    if not segments:
        raise RenderEngineUnavailable("No narration audio was produced for this storyboard")
    output = work_dir / name
    if pads and any(pad > 0 for pad in pads):
        args = [ffmpeg_exe, "-nostdin", "-y"]
        for segment in segments:
            args += ["-i", str(segment)]
        chains = []
        for position in range(len(segments)):
            pad = pads[position] if position < len(pads) else 0.0
            chains.append(
                f"[{position}:a]aresample={MASTER_SAMPLE_RATE},"
                "aformat=sample_fmts=fltp:channel_layouts=mono"
                + (f",apad=pad_dur={pad:.3f}" if pad > 0 else "")
                + f"[s{position}]"
            )
        joined = "".join(f"[s{position}]" for position in range(len(segments)))
        graph = ";".join(chains) + f";{joined}concat=n={len(segments)}:v=0:a=1[voice]"
        args += ["-filter_complex", graph, "-map", "[voice]", *_VOICE_WAV_ARGS]
        joined_run = subprocess.run(  # noqa: S603
            [*args, str(output)], capture_output=True, text=True, timeout=600, check=False
        )
        if joined_run.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            raise RenderEngineUnavailable(
                f"FFmpeg could not join the narration segments (exit code {joined_run.returncode})"
            )
        return output
    listing = work_dir / "voice_segments.txt"
    listing.write_text(
        "".join(f"file '{segment.as_posix()}'\n" for segment in segments), encoding="utf-8"
    )
    result = subprocess.run(  # noqa: S603
        [
            ffmpeg_exe,
            "-nostdin",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-af",
            f"aresample={MASTER_SAMPLE_RATE}",
            *_VOICE_WAV_ARGS,
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        raise RenderEngineUnavailable(
            f"FFmpeg could not join the narration segments (exit code {result.returncode})"
        )
    return output


#: The first frame travels to the vendor inside the request, so it is sent at the size the
#: film is made at rather than the size the still came back at. A generated still can be
#: twelve megabytes; base64 makes that seventeen, and Runway answers 413.
FIRST_FRAME_WIDTH = 1080
FIRST_FRAME_QUALITY = "2"


def _first_frame(ffmpeg_exe: str, still: Path, seconds: float) -> bytes:
    """The scene's still, re-encoded to a first frame a request can carry."""
    target = still.with_name(f"first_{still.stem}.jpg")
    result = subprocess.run(
        [
            ffmpeg_exe,
            "-v",
            "error",
            "-y",
            "-i",
            str(still),
            "-vf",
            f"scale={FIRST_FRAME_WIDTH}:-2",
            "-q:v",
            FIRST_FRAME_QUALITY,
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise MediaProviderError("the scene's still could not be prepared as a first frame")
    return target.read_bytes()


def motion_request(
    adapter: Any, scene: dict[str, Any], *, from_still: bool
) -> tuple[str, dict[str, Any]]:
    """What the video model is sent for a scene: (promptText, extra).

    A scene the prompt compiler wrote carries a motion prompt of its own, said again in the
    dialect of the model that films it (veo's exclusions go as ``negative_prompt`` in
    ``extra``). With the approved still as the first frame only the motion is described:
    the model already sees the picture. Filmed from words alone, the picture's words come
    first. A scene from before the compiler sends its visual prompt, as it always did. The
    text is not sliced here: the adapter fits it to its contract at a sentence boundary.
    """
    from app.media.prompt_agent import motion_prompt_for  # noqa: PLC0415

    package = scene.get("prompt_json")
    package = package if isinstance(package, dict) else {}
    picture = " ".join(str(scene.get("visual_prompt") or "").split())
    model = getattr(adapter, "model", None)
    metadata = getattr(adapter, "model_metadata", None)
    motion, negative = motion_prompt_for(
        package,
        model if isinstance(model, str) else None,
        metadata if isinstance(metadata, dict) else None,
    )
    if not motion:
        prompt = picture
    elif from_still:
        prompt = motion
    else:
        prompt = " ".join(part for part in (picture, motion) if part)
    return prompt, ({"negative_prompt": negative} if negative else {})


def _generate_motion(
    adapter: VideoProvider,
    scene: dict[str, Any],
    still: Path | None,
    seconds: float,
    ffmpeg_exe: str,
    *,
    seed: int | None = None,
    on_submitted: Callable[[str], None] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Ask the scene's model for its shot, and wait for the clip.

    With a still, the still is the first frame, so the picture the Director approved is the
    picture that moves — that is production. Without one the model films from the scene's
    words, which is what a test does on the cheapest model. A task that has not finished by
    the deadline raises; nothing invents a shot. ``seed`` is the film's one seed (the adapter
    sends it where the contract declares it); ``on_submitted`` hears the task id once the
    vendor has accepted the request, which is when a shot starts to cost money.
    """
    prompt, extra = motion_request(adapter, scene, from_still=still is not None)
    if seed is not None:
        extra = {**extra, "seed": int(seed)}
    job_id = asyncio.run(
        adapter.create_generation(
            prompt,
            image_ref=_first_frame(ffmpeg_exe, still, seconds) if still is not None else None,
            duration_seconds=seconds,
            aspect_ratio="9:16",
            **({"extra": extra} if extra else {}),
        )
    )
    if on_submitted is not None:
        on_submitted(str(job_id))
    deadline = time.monotonic() + MOTION_DEADLINE_SECONDS
    attempts = 0
    while True:
        try:
            result = asyncio.run(adapter.get_generation_status(job_id))
        except MediaProviderError:
            # The shot exists and is paid for; a failed download is worth a second attempt
            # before it is written off.
            attempts += 1
            if attempts > 2 or time.monotonic() >= deadline:
                raise
            time.sleep(MOTION_POLL_SECONDS)
            continue
        if result.status == "COMPLETED" and result.video_bytes:
            return result.video_bytes, result.raw_response
        if result.status == "FAILED":
            raw = result.raw_response or {}
            code = raw.get("failure_code")
            failure = raw.get("failure")
            # The vendor's code (SAFETY.*, INTERNAL.BAD_OUTPUT, ...) travels with the error:
            # it decides whether the scene moves, retries or goes to the Owner.
            raise MediaProviderError(
                f"the motion task failed ({code or 'no reason given'})",
                code=code if isinstance(code, str) and code else None,
                detail=failure if isinstance(failure, str) and failure else None,
            )
        if time.monotonic() >= deadline:
            raise MediaProviderError("the motion task did not finish before the deadline")
        time.sleep(MOTION_POLL_SECONDS)


def _quote_motion(
    adapter: VideoProvider,
    scene: dict[str, Any],
    still: Path | None,
    seconds: float,
    ffmpeg_exe: str,
) -> float | None:
    """What the vendor says this shot would cost, in credits, before anything is bought.

    Asked only of an adapter that offers to answer, and only when the vendor's own contract
    declares the task accepts a dry run — sending a flag an API does not declare risks
    buying the shot by accident. The question carries the same body the purchase would, so
    the answer is about this shot: a price per second written down somewhere is a guess
    about a length, a format and a task at once. A vendor that will not answer leaves the
    studio with the price it measured, which is what it had before.
    """
    ask = getattr(adapter, "estimate_generation", None)
    if ask is None:
        return None
    prompt, extra = motion_request(adapter, scene, from_still=still is not None)
    try:
        return asyncio.run(
            ask(
                prompt,
                image_ref=_first_frame(ffmpeg_exe, still, seconds) if still is not None else None,
                duration_seconds=seconds,
                aspect_ratio="9:16",
                **({"extra": extra} if extra else {}),
            )
        )
    except (MediaProviderError, MediaProviderNotConfigured, ValueError, OSError) as exc:
        logger.info("motion_quote_unavailable", extra={"reason": str(exc)[:160]})
        return None


def _record_outcomes(
    engine: Engine,
    production: dict[str, Any],
    render_job_id: str,
    *,
    environment: str,
    run_kind: str | None,
    credit_price: float | None,
) -> None:
    """Record what each shot did, so the studio learns from its own results.

    A model's worth is not a number on a vendor page: it is what it delivered, for what it
    cost, in the kind of scene the studio asked for. An ordinary functional test is recorded
    too — and marked as one — so a deliberately cheap shot never teaches the studio that a
    model's picture is poor.
    """
    from app.integrations.lifecycle import ADMITTED  # noqa: PLC0415
    from app.integrations.models import ModelOutcome, ProviderResource  # noqa: PLC0415

    standing: dict[tuple[str, str], str] = {}
    with Session(engine) as session:
        for resource in session.scalars(
            select(ProviderResource).where(ProviderResource.resource_type == "MODEL")
        ):
            standing[(str(resource.integration_id), str(resource.remote_id))] = str(
                resource.production_status or ""
            )
    rows: list[ModelOutcome] = []
    for entry in production.get("scenes", []):
        motion = entry.get("motion") if isinstance(entry.get("motion"), dict) else None
        if not motion or not motion.get("model") or not motion.get("integration_id"):
            continue
        if motion.get("reused_take"):
            continue  # nothing was generated: a take bought earlier was used again
        credits = motion.get("estimated_credits")
        seconds = float(motion.get("asked_seconds") or 0)
        landed = bool(motion.get("bytes"))
        # A test that tries a model the studio has not admitted yet is that model's
        # benchmark — otherwise a new model could never earn its way in, because it is not
        # allowed to film production until it has results. A test on a model already in
        # production is only a functional check, and must never teach the studio anything
        # about that model's picture.
        where = standing.get((str(motion["integration_id"]), str(motion["model"])), "")
        kind = run_kind or (
            "PRODUCTION"
            if environment == "PRODUCTION"
            else ("TEST_FUNCTIONAL" if where in ADMITTED else "TEST_BENCHMARK")
        )
        rows.append(
            ModelOutcome(
                id=str(uuid4()),
                integration_id=str(motion["integration_id"]),
                remote_id=str(motion["model"]),
                purpose="video",
                run_kind=kind,
                environment=environment,
                scene_category=str(motion.get("scene_category") or "GENERAL"),
                quality_tier=str(motion.get("tier") or "") or None,
                seconds_requested=seconds,
                seconds_accepted=seconds if landed else 0.0,
                credits=float(credits) if isinstance(credits, int | float) else None,
                usd=(
                    round(float(credits) * credit_price, 6)
                    if isinstance(credits, int | float) and credit_price
                    else None
                ),
                first_pass=landed,
                accepted=landed,
                failure_kind=None if landed else str(motion.get("failure_kind") or "TECHNICAL"),
                render_job_id=render_job_id,
                created_at=utc_now(),
            )
        )
    if not rows:
        return
    # A film that has already been paid for is not lost because a record could not be
    # written: the outcome is what the studio learns from, not what it delivers.
    try:
        with Session(engine) as session, session.begin():
            for row in rows:
                session.add(row)
    except SQLAlchemyError as exc:
        logger.warning("model_outcomes_not_recorded", extra={"reason": str(exc)[:200]})
        production.setdefault("motion_notes", []).append(f"outcomes not recorded: {str(exc)[:120]}")


#: The writer's story purpose, read as the scene's role in the film. The hook decides whether
#: anyone watches and the reveal or payoff is what the film carries; the rest is STANDARD. A
#: stated purpose wins over the position: the last scene is not a payoff when the writer said
#: it is evidence.
PURPOSE_ROLES: dict[str, str] = {
    "HOOK": "HOOK",
    "REVEAL": "KEY",
    "PAYOFF": "KEY",
    "ENDING": "ENDING",
}


def scene_tier(scene: dict[str, Any], total_scenes: int) -> str:
    """What quality this scene has to reach, from its part in the film.

    The opening shot decides whether anyone watches and the last one decides whether anyone
    comments, so they are asked for more than the middle. A scene that carries its own tier
    (from the channel, the episode or the Owner) keeps it.
    """
    from app.media.production_policy import SCENE_ROLE_TIERS, scene_role  # noqa: PLC0415

    stated = scene.get("quality_tier")
    if isinstance(stated, str) and stated:
        return stated
    purpose = str(scene.get("story_purpose") or "").strip().upper()
    role = (
        str(scene.get("scene_role") or "")
        or PURPOSE_ROLES.get(purpose, "")
        or ("NORMAL" if purpose else "")
        or scene_role(int(scene.get("scene_index") or 1), total_scenes)
    )
    return SCENE_ROLE_TIERS.get(role, "STANDARD")


def _credit_price(engine: Engine) -> float | None:
    """What a credit costs, from the connection the Owner recorded it on."""
    from app.integrations.models import Integration  # noqa: PLC0415
    from app.media.production_policy import credit_usd  # noqa: PLC0415

    with Session(engine) as session:
        for row in session.scalars(select(Integration)):
            price = credit_usd(session, row.id)
            if price is not None:
                return price
    return None


def _loudness_readings(measured: dict | None) -> dict[str, float | None]:
    """The readings a manifest keeps: finite numbers, or None where nothing was measured.

    A silent input measures as -inf, which JSON cannot carry; the manifest says None and the
    "measured" flag says whether a reading was taken at all.
    """

    def finite(key: str) -> float | None:
        value = (measured or {}).get(key)
        if isinstance(value, int | float) and math.isfinite(float(value)):
            return round(float(value), 2)
        return None

    return {
        "measured": bool(measured),
        "integrated_lufs": finite("integrated_lufs"),
        "true_peak_dbtp": finite("true_peak_dbtp"),
        "loudness_range_lu": finite("loudness_range_lu"),
    }


def _loudness_record(master: dict[str, Any]) -> dict[str, Any]:
    """What the manifest keeps of one mastering: targets, chain, readings and any warning.

    ``output`` starts as the master's own reading of its AAC track; a render replaces it with
    the finished film's, which is the file that is delivered.
    """
    record: dict[str, Any] = {
        "applied": bool(master.get("applied")),
        "target_lufs": LOUDNESS_TARGET_LUFS,
        "true_peak_target_dbtp": TRUE_PEAK_TARGET_DBTP,
        "true_peak_ceiling_dbtp": TRUE_PEAK_CEILING_DBTP,
        "passes": master.get("passes"),
        "filter": master.get("filter"),
        "limiter": "alimiter" in str(master.get("filter") or ""),
        "codec": AUDIO_CODEC_LABEL,
        "normalization_type": master.get("normalization_type"),
        "warning": master.get("warning"),
        "input": _loudness_readings(master.get("measured")),
        "output": _loudness_readings(master.get("delivered")),
    }
    if not record["applied"]:
        record["reason"] = "the encoder has no loudnorm filter"
    return record


def _shot_frames(ffmpeg_exe: str, path: Path) -> int | None:
    """How many frames a built shot holds, as ffprobe counts them; None when it cannot."""
    from app.media.qc import probe_media_file  # noqa: PLC0415

    frames = probe_media_file(path, ffmpeg_exe).get("video_frames")
    return frames if isinstance(frames, int) and frames > 0 else None


def _video_stream_seconds(ffmpeg_exe: str, path: Path) -> float | None:
    """How long the picture actually lasts, or None when it cannot be measured."""
    from app.media.qc import probe_media_file  # noqa: PLC0415

    probe = probe_media_file(path, ffmpeg_exe)
    frames = probe.get("video_frames")
    fps = probe.get("video_fps")
    if isinstance(frames, int) and frames > 0 and isinstance(fps, int | float) and fps > 0:
        return frames / float(fps)
    seconds = probe.get("video_duration_seconds")
    return float(seconds) if isinstance(seconds, int | float) and seconds > 0 else None


#: Every picture ends its filter chain here: BT.709, limited range (luma 16-235), 4:2:0, and
#: tagged so. The shots used to be forced to full range (``setrange=pc``) and delivered that
#: way, which players show with grey blacks and clipped whites.
_COLOUR_TAGS = "range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709"
TO_BT709_TV = f"scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams={_COLOUR_TAGS}"
#: The container tags that go with it, on every file the studio encodes.
_COLOUR_FLAGS: tuple[str, ...] = (
    "-color_range",
    "tv",
    "-colorspace",
    "bt709",
    "-color_primaries",
    "bt709",
    "-color_trc",
    "bt709",
)
#: A shot is an intermediate: lossless x264 (``-qp 0``), so the film is encoded lossily once,
#: at the end, and not twice as it was (a veryfast shot, then the film).
INTERMEDIATE_VIDEO_ARGS: tuple[str, ...] = (
    "-c:v",
    "libx264",
    "-qp",
    "0",
    "-preset",
    "veryfast",
    "-pix_fmt",
    "yuv420p",
    *_COLOUR_FLAGS,
)


def final_video_args(fps: int = TIMELINE_FPS) -> list[str]:
    """The finished film's video encode, in full.

    H.264 High at level 4.2 (1080x1920 at up to 60 fps), CRF 17 on the slow preset with a
    14 Mbps ceiling over a 28 Mbit buffer — what a phone screen needs for detailed, moving
    picture; the Nepal film had 2.6 Mbps. Two B-frames, a keyframe every half second and no
    scene-cut keyframes, so the platform's re-encode finds a regular GOP. 4:2:0, BT.709
    limited range, and the index at the front of the file so playback starts at once.
    """
    return [
        "-c:v",
        "libx264",
        "-profile:v",
        "high",
        "-level:v",
        "4.2",
        "-preset",
        "slow",
        "-crf",
        "17",
        "-maxrate",
        "14M",
        "-bufsize",
        "28M",
        "-bf",
        "2",
        "-g",
        str(max(1, int(fps) // 2)),
        "-sc_threshold",
        "0",
        "-pix_fmt",
        "yuv420p",
        *_COLOUR_FLAGS,
        "-movflags",
        "+faststart",
    ]


def _audio_output_args(audio_filter: str | None) -> list[str]:
    """The film's audio: the mastered track copied in (None), or encoded here from a chain."""
    if audio_filter is None:
        return ["-c:a", "copy"]
    return ["-af", audio_filter, *AUDIO_CODEC_ARGS]


# --------------------------------------------------------------------------- the timeline
# 2026-10-01 (TIMELINE_24_CAPTIONS): the film is cut on the vendor's 24 fps, scenes join by a
# hard cut unless the script asks for a dissolve, and a scene lasts its words plus a breath.
# Every length on the timeline is a whole number of frames, so shots joined end to end never
# drift from the voice by a rounding.


def whole_frames(seconds: float, fps: int = TIMELINE_FPS, *, up: bool = False) -> float:
    """``seconds`` on a frame boundary: the nearest one, or the next one up (``up``)."""
    frames = seconds * fps
    count = math.ceil(frames - 1e-6) if up else round(frames)
    return max(1, count) / fps


def is_dissolve(transition: Any) -> bool:
    """Whether a scene's ``transition_in`` asks the shot before it to mix into it."""
    word = str(transition or "").strip().upper().replace("-", "_").replace(" ", "_")
    return word in DISSOLVE_WORDS


def scene_joins(scenes: list[dict[str, Any]]) -> list[float]:
    """How long each scene's join from the scene before it lasts: 0.0 for a hard cut (the
    default, and always for the first scene), the dissolve where ``transition_in`` asks.

    A scene that carries ``dissolve_seconds`` keeps it: a film recorded before this item
    dissolved every join by TRANSITION_SECONDS, and a one-scene redo rejoins it the same way.
    """
    joins: list[float] = []
    for position, scene in enumerate(scenes):
        recorded = scene.get("dissolve_seconds")
        if position == 0:
            joins.append(0.0)
        elif isinstance(recorded, int | float):
            joins.append(max(0.0, float(recorded)))
        else:
            joins.append(DISSOLVE_SECONDS if is_dissolve(scene.get("transition_in")) else 0.0)
    return joins


def shot_spans(scenes: list[dict[str, Any]], joins: list[float] | None = None) -> list[float]:
    """How long each scene's shot file must be: its scene, plus the overlap the next scene's
    dissolve consumes from it. A shot followed by a cut is exactly its scene."""
    joins = scene_joins(scenes) if joins is None else joins
    return [
        float(scene["duration_seconds"]) + (joins[position + 1] if position + 1 < len(joins) else 0)
        for position, scene in enumerate(scenes)
    ]


def scene_spans(
    planned: Sequence[float], spoken: Sequence[float | None], *, fps: int = TIMELINE_FPS
) -> list[float]:
    """How long each scene lasts on the timeline, on whole frames.

    A scene with words lasts min(planned, spoken + SPOKEN_TAIL_SECONDS), and never less than
    its words: a word is never cut, so words longer than the plan set the length. A scene
    with no words keeps its plan. The breaths after the words are shortened together, never
    dropped one by one, so the film stays within FILM_OVER_NARRATION_SECONDS of its words —
    quality control fails a film longer than its narration plus a second, and the planned
    lengths used to pad the Nepal film with silence.
    """
    speaking = [isinstance(s, int | float) and float(s) > 0 for s in spoken]
    tails = [
        (
            min(SPOKEN_TAIL_SECONDS, max(0.0, float(plan) - float(said or 0.0)))
            if float(plan) > 0
            else SPOKEN_TAIL_SECONDS
        )
        if talks
        else 0.0
        for plan, said, talks in zip(planned, spoken, speaking, strict=True)
    ]
    # Each scene's length is rounded up to a frame: that frame is counted in the budget.
    budget = max(0.0, FILM_OVER_NARRATION_SECONDS - sum(speaking) / fps)
    if sum(tails) > budget > 0:
        tails = [tail * budget / sum(tails) for tail in tails]
    elif budget <= 0:
        tails = [0.0] * len(tails)
    spans: list[float] = []
    for plan, said, talks, tail in zip(planned, spoken, speaking, tails, strict=True):
        if talks:
            spans.append(whole_frames(float(said or 0.0) + tail, fps, up=True))
        else:
            spans.append(whole_frames(float(plan), fps))
    return spans


def _dither_chain(dither: bool) -> str:
    """A vendor clip down to 8 bits: error-diffusion dither (zimg) for a 10-bit source such as
    the Nepal motion_01; an 8-bit source passes through it unchanged. Without zscale in the
    build, swscale's own ordered dither does it."""
    return "zscale=dither=error_diffusion,format=yuv420p," if dither else "format=yuv420p,"


def _shot_command(
    ffmpeg_exe: str,
    still: Path,
    clip: Path | None,
    span: float,
    target: Path,
    *,
    fps: int = TIMELINE_FPS,
    hold: float = 0.0,
    dither: bool = True,
) -> list[str]:
    """One scene as one file, exactly ``span`` long on the ``fps`` timeline: the generated clip
    trimmed to its span, or the still pushed in.

    A clip is cut, never stretched: the motion step buys whole seconds rounded up, so a clip
    covers its span. ``hold`` is the one exception, for a clip a vendor delivered shorter than
    asked: its last frame is held that long, and the render records it as held (quality
    control counts held frames as duplicates). A shot is built and measured on its own
    because a single filter graph over eight inputs hid its own failure: the first dissolve
    render wrote six seconds of picture under forty-six seconds of audio and reported success.
    """
    frames = max(1, round(span * fps))
    if clip is not None:
        held = f"tpad=stop_mode=clone:stop_duration={hold:.6f}," if hold > 0 else ""
        return [
            ffmpeg_exe,
            "-nostdin",
            "-y",
            "-i",
            str(clip),
            "-an",
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920,"
            f"setsar=1,fps={fps},{_dither_chain(dither)}{held}trim=end_frame={frames},"
            f"setpts=PTS-STARTPTS,{TO_BT709_TV}",
            *INTERMEDIATE_VIDEO_ARGS,
            str(target),
        ]
    return [
        ffmpeg_exe,
        "-nostdin",
        "-y",
        "-loop",
        "1",
        "-framerate",
        str(fps),
        "-t",
        f"{frames / fps:.6f}",
        "-i",
        str(still),
        "-an",
        "-vf",
        "scale=1188:2112:force_original_aspect_ratio=increase,crop=1188:2112,"
        f"zoompan=z='min(1+0.10*on/{frames},1.10)':d=1:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps},"
        f"setsar=1,trim=end_frame={frames},setpts=PTS-STARTPTS,{TO_BT709_TV}",
        *INTERMEDIATE_VIDEO_ARGS,
        str(target),
    ]


def _shot_record(
    scene: dict[str, Any], target: Path, span: float, dissolve_in: float = 0.0
) -> dict[str, Any]:
    """One built shot as the manifest keeps it: its file (by name, beside the film), its
    sha256, its span (the scene plus any dissolve overlap into the next), the scene's length
    and the dissolve it is joined by from the scene before (0.0: a cut)."""
    return {
        "scene_index": int(scene["scene_index"]),
        "file": target.name,
        "sha256": _file_sha256(target),
        "span": round(float(span), 6),
        "duration_seconds": round(float(scene["duration_seconds"]), 6),
        "dissolve_seconds": round(float(dissolve_in), 6),
    }


def _dissolve_command(
    ffmpeg_exe: str,
    shots: list[Path],
    scenes_data: list[dict[str, Any]],
    audio_file: Path,
    output_mp4: Path,
    *,
    audio_filter: str | None = "apad",
    captions: str | None = None,
    fps: int = TIMELINE_FPS,
) -> list[str]:
    """One ffmpeg call over the shot files: the film's edit.

    Shots join by a hard cut (concat), and by a dissolve (xfade) only where the scene's
    ``transition_in`` asks (scene_joins). A dissolve starts where the scene's words start
    and consumes the overlap its shot before was built with, so shot N always starts where
    scene N's words start — the picture never drifts away from the voice. ``audio_filter`` is
    an audio chain to encode the track with, or None when ``audio_file`` is the mastered
    track, which is then copied in untouched; ``captions`` is the subtitles filter to burn in
    after the edit, or None to leave the picture clean.
    """
    args = [ffmpeg_exe, "-nostdin", "-y"]
    for shot in shots:
        args += ["-i", str(shot)]
    args += ["-i", str(audio_file)]

    joins = scene_joins(scenes_data)
    # Every shot on one clock first: a time base of one frame, so a cut (concat) and a
    # dissolve (xfade, which refuses inputs on different time bases) join the same frames.
    chain = "".join(
        f"[{index}:v]fps={fps},settb=1/{fps},setpts=N[s{index}];" for index in range(len(shots))
    )
    current = "s0"
    start = 0.0
    for index in range(1, len(shots)):
        start += float(scenes_data[index - 1]["duration_seconds"])
        nxt = f"x{index}"
        if joins[index] > 0:
            chain += (
                f"[{current}][s{index}]xfade=transition=fade:"
                f"duration={joins[index]:.6f}:offset={start:.6f}[{nxt}];"
            )
        else:
            # concat answers on its own microsecond clock; it is put back on the frame clock.
            chain += f"[{current}][s{index}]concat=n=2:v=1:a=0,settb=1/{fps},setpts=N[{nxt}];"
        current = nxt
    total = sum(float(s["duration_seconds"]) for s in scenes_data)
    frames = max(1, round(total * fps))
    burn = f",{captions}" if captions else ""
    # The captions are drawn onto the limited-range picture and the result is converted and
    # tagged once more, so what is burnt in keeps to 16-235 as well.
    tail = f"fps={fps},trim=end_frame={frames},setpts=PTS-STARTPTS{burn},{TO_BT709_TV}[vout]"
    chain += f"[{current}]{tail}"

    args += [
        "-filter_complex",
        chain,
        "-map",
        "[vout]",
        "-map",
        f"{len(shots)}:a",
        *_audio_output_args(audio_filter),
        "-t",
        f"{total:.3f}",
        *final_video_args(fps),
        str(output_mp4),
    ]
    return args


# --------------------------------------------------------------------------- scene takes
# Every picture the studio pays for is a SceneTake row (migration 0048): which scene, which
# prompt package (its sha256), which model, what it was quoted, where the file is and its
# sha256. A take that was bought and not rejected is used again instead of being bought again:
# the Nepal film's second render bought all six stills and every clip a second time, with the
# same prompts, because nothing recorded that they were already paid for.

#: A take that may be used again without buying it: one someone approved, or one that was
#: bought and not (yet) rejected. REJECTED and REFUSED takes are never used.
REUSABLE_TAKE_STATUSES: tuple[str, ...] = ("APPROVED", "PAID")
#: The one kind a paid model films; every other kind (CARD_KINDS) is composed locally.
LIVE_KIND = "LIVE"
#: What a film assembled from takes alone is labelled when no image adapter was passed: real
#: pictures, bought earlier and approved, never a placeholder.
TAKES_VISUAL_SOURCE = "SCENE_TAKES"
#: Still formats a card can stand on (a placeholder SVG cannot).
_RASTER: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".ppm")
#: What the stills and the shots are asked at: the film's 9:16 frame.
STILL_RESOLUTION = "1080:1920"
MOTION_RESOLUTION = "1080:1920"
#: What a degenerate still is asked again with (a real scene, not stripes or a blank).
DEGENERATE_RETRY_SUFFIX = (
    " A real, detailed scene: no text, no letters, no stripes, no repeating pattern."
)
#: The failure code a take carries when the studio's own check, not the vendor, refused it.
DEGENERATE_FAILURE_CODE = "LOCAL.DEGENERATE_STILL"
#: At most this much of a vendor's reason is kept on a take (the column's own limit).
TAKE_DETAIL_MAX = 500
#: The take kinds that are a scene's shot: the hero test shot is kept in the film.
SHOT_TAKE_KINDS: tuple[str, ...] = ("test_shot", "motion")


class TakesMissing(RuntimeError):
    """A film cannot be assembled from its takes: a LIVE scene has no approved still.

    Raised before a render job exists and before any adapter is asked: assembling from takes
    never buys a picture. The message is the Owner's, in Romanian.
    """


def scene_kind_of(scene: dict[str, Any]) -> str:
    """The scene's kind (LIVE | DATA_CARD | TITLE_CARD | BLACK); an unknown value is LIVE."""
    kind = str(scene.get("scene_kind") or "LIVE").upper()
    return kind if kind in (LIVE_KIND, *CARD_KINDS) else LIVE_KIND


def is_composed(scene: dict[str, Any]) -> bool:
    """A card scene: composed locally at 0 credits, never sent to an image or video model."""
    return scene_kind_of(scene) in CARD_KINDS


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def take_hash(fields: dict[str, Any], model_id: str | None) -> str:
    """The sha256 of a take's prompt package: its canonical JSON plus the model that made it."""
    canonical = json.dumps(
        {**fields, "model_id": str(model_id or "")},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def still_fields(prompt: str, reference: dict[str, Any] | None) -> dict[str, Any]:
    """What makes a still the picture it is, besides the model: the words, the frame, and the
    character's reference picture when one is drawn from (a new reference is a new still)."""
    ref_bytes = (reference or {}).get("bytes")
    return {
        "kind": "still",
        "prompt": " ".join(str(prompt or "").split()),
        "resolution": STILL_RESOLUTION,
        "reference_sha256": (
            hashlib.sha256(ref_bytes).hexdigest() if isinstance(ref_bytes, bytes) else None
        ),
    }


def motion_fields(
    scene: dict[str, Any], still_sha256: str | None, *, from_prompt: bool
) -> dict[str, Any]:
    """What makes a shot the shot it is, besides the model: the compiled motion package (the
    model's dialect is a function of it), the still it starts from, and the frame. The length
    is not part of it: a take long enough for the span is used, and the assembler trims it."""
    raw = scene.get("prompt_json")
    package = raw if isinstance(raw, dict) else {}
    source = {
        key: package.get(key)
        for key in ("motion_prompt", "motion_intent", "negative_prompt", "camera_move")
        if package.get(key)
    }
    if not source:
        source = {"visual_prompt": " ".join(str(scene.get("visual_prompt") or "").split())}
    return {
        "kind": "motion",
        "package": source,
        "first_frame_sha256": None if from_prompt else still_sha256,
        "from_prompt": bool(from_prompt),
        "resolution": MOTION_RESOLUTION,
    }


def failure_code_of(exc: BaseException) -> str | None:
    """The vendor's failure code, or HTTP_<status> when it named none."""
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.strip():
        return code.strip()[:100]
    status = getattr(exc, "http_status", None)
    return f"HTTP_{status}" if isinstance(status, int) else None


def failure_detail_of(exc: BaseException) -> str | None:
    """The vendor's own reason, sanitised, with each field it refused ('ratio: ...').

    Runway's 400 names the field it refused; dropped, the studio could only guess and changed
    the model instead of fixing the request. At most TAKE_DETAIL_MAX characters.
    """
    from app.providers.media_http import sanitise_vendor_text  # noqa: PLC0415

    parts: list[str] = []
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str) and detail.strip():
        parts.append(detail.strip())
    for issue in getattr(exc, "issues", None) or []:
        if isinstance(issue, dict):
            path = str(issue.get("path") or "").strip()
            message = str(issue.get("message") or "").strip()
            if path or message:
                parts.append(f"{path}: {message}" if path else message)
    if not parts:
        parts.append(str(exc))
    text = sanitise_vendor_text("; ".join(parts), TAKE_DETAIL_MAX)
    return text[:TAKE_DETAIL_MAX] or None


def classify_vendor_failure(exc: BaseException, previous: str | None = None) -> Any:
    """The failure sorted by kind (SAFETY | CONTRACT | TRANSIENT | ...), per scene."""
    from app.media.production_policy import classify_failure  # noqa: PLC0415

    return classify_failure(
        failure_code_of(exc) if getattr(exc, "code", None) else None,
        http_status=getattr(exc, "http_status", None),
        detail=failure_detail_of(exc),
        previous=previous,
    )


def usable_take(
    session: Session,
    storyboard_id: str,
    scene_number: int,
    kind: str,
    field_options: list[dict[str, Any]],
    *,
    statuses: tuple[str, ...] = REUSABLE_TAKE_STATUSES,
    models: tuple[str, ...] | None = None,
    min_seconds: float | None = None,
) -> SceneTake | None:
    """A take of this scene that may be used instead of buying one, or None.

    Its prompt hash must equal the hash of one of ``field_options`` with the take's own model
    (the prompt unchanged), its file must be on disk with the sha256 recorded, an APPROVED take
    is preferred over a PAID one and a newer over an older. ``models`` narrows it to takes made
    by those models; ``min_seconds`` to shots long enough for the span.
    """
    rows = session.scalars(
        select(SceneTake)
        .where(
            SceneTake.storyboard_id == storyboard_id,
            SceneTake.scene_number == scene_number,
            SceneTake.kind == kind,
            SceneTake.status.in_(statuses),
        )
        .order_by(SceneTake.created_at.desc())
    ).all()
    ranked = sorted(rows, key=lambda row: 0 if row.status == "APPROVED" else 1)
    for row in ranked:
        if models is not None and row.model_id not in models:
            continue
        if min_seconds is not None and row.seconds is not None and row.seconds < min_seconds:
            continue
        if not any(take_hash(fields, row.model_id) == row.prompt_hash for fields in field_options):
            continue
        if not row.path or not row.sha256:
            continue
        path = Path(row.path)
        if not path.is_file() or _file_sha256(path) != row.sha256:
            continue
        return row
    return None


def record_take(
    engine: Engine,
    *,
    storyboard_id: str,
    scene_number: int,
    kind: str,
    prompt_hash: str,
    model_id: str | None,
    resolution: str,
    status: str,
    correlation_id: str,
    seconds: float | None = None,
    seed: int | None = None,
    credits_quoted: float | None = None,
    path: Path | None = None,
    sha256: str | None = None,
    failure_code: str | None = None,
    failure_detail: str | None = None,
) -> str:
    """Write one take (and its event). The same file of the same prompt is one row: buying it
    again updates that row instead of breaking the identity the table enforces."""
    now = utc_now()
    with Session(engine) as session, session.begin():
        existing = (
            session.scalars(
                select(SceneTake).where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.scene_number == scene_number,
                    SceneTake.kind == kind,
                    SceneTake.prompt_hash == prompt_hash,
                    SceneTake.sha256 == sha256,
                )
            ).first()
            if sha256
            else None
        )
        take_id = existing.id if existing is not None else str(uuid4())
        event = append_event(
            session,
            "media.scene_take_recorded",
            "scene_take",
            take_id,
            1,
            {
                "storyboard_id": storyboard_id,
                "scene_number": scene_number,
                "kind": kind,
                "status": status,
                "model_id": model_id,
                "prompt_hash": prompt_hash,
                "credits_quoted": credits_quoted,
                "failure_code": failure_code,
            },
            correlation_id,
        )
        row = existing or SceneTake(
            id=take_id,
            storyboard_id=storyboard_id,
            scene_number=scene_number,
            kind=kind,
            prompt_hash=prompt_hash,
            created_at=now,
        )
        row.model_id = str(model_id or "unknown")[:100]
        row.resolution = resolution
        row.seconds = seconds
        row.seed = seed
        row.credits_quoted = credits_quoted
        row.status = status
        row.failure_code = failure_code
        row.failure_detail = (failure_detail or None) and failure_detail[:TAKE_DETAIL_MAX]
        row.path = str(path) if path is not None else None
        row.sha256 = sha256
        row.updated_at = now
        row.event_id = event.event_id
        if existing is None:
            session.add(row)
    return take_id


def _quoted_credits(adapter: Any) -> float | None:
    """What the vendor said the last request cost, in credits; None when it did not say."""
    credits = getattr(adapter, "last_estimated_credits", None)
    if isinstance(credits, bool) or not isinstance(credits, int | float):
        return None
    return float(credits)


def _take_file(take: SceneTake, work_dir: Path, name: str) -> Path:
    """The take's file inside this render's folder (copied when it lives elsewhere)."""
    source = Path(str(take.path))
    target = work_dir / f"{name}{source.suffix}"
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)
    return target


def _still_for_scene(
    engine: Engine,
    storyboard_id: str,
    scene: dict[str, Any],
    drawn_by: list[ImageProvider],
    asked: dict[str, Any],
    reference: dict[str, Any] | None,
    work_dir: Path,
    *,
    correlation_id: str,
    record_takes: bool,
    takes_only: bool,
    ffmpeg_path: str | None,
    production: dict[str, Any],
    busy_engine: Engine | None,
) -> tuple[Path, list[dict[str, Any]], dict[str, Any] | None]:
    """One LIVE scene's still: a usable take when one exists, else bought (and recorded).

    Returns the still on disk, the purchase attempts (empty when nothing was bought) and what
    the take was ({take_id, status, reused}), or None for an unrecorded placeholder still.
    With ``takes_only`` nothing is bought: an APPROVED take is used or TakesMissing is raised.
    """
    from app.media.factory import still_from_chain  # noqa: PLC0415
    from app.media.prompt_agent import strip_on_screen_text  # noqa: PLC0415
    from app.media.qc import still_is_degenerate  # noqa: PLC0415

    index = int(scene["scene_index"])
    prompt = str(scene["visual_prompt"] or "")
    retry_prompt = strip_on_screen_text(prompt) + DEGENERATE_RETRY_SUFFIX
    fields = still_fields(prompt, reference)
    retry_fields = still_fields(retry_prompt, reference)

    if record_takes or takes_only:
        with Session(engine) as session:
            found = usable_take(
                session,
                storyboard_id,
                index,
                "still",
                [fields, retry_fields],
                statuses=("APPROVED",) if takes_only else REUSABLE_TAKE_STATUSES,
                models=None
                if takes_only
                else tuple(str(getattr(a, "model", None) or "unknown") for a in drawn_by),
            )
            found_info = (
                {"take_id": found.id, "status": found.status, "reused": True}
                if found is not None
                else None
            )
            if found is not None:
                session.expunge(found)
        if found is not None and found_info is not None:
            return _take_file(found, work_dir, f"scene_{index:02d}"), [], found_info
        if takes_only:
            raise TakesMissing(
                f"Scena {index} nu are o imagine aprobată pentru promptul ei de acum: filmul nu "
                "se asamblează din imagini pe care nu le-a văzut nimeni. Aprobă imaginea pe "
                "foaia de filmare sau cumpără-o la pasul de imagini."
            )

    def draw(words: str, label: str) -> tuple[Any, list[dict[str, Any]]]:
        with _at_work(busy_engine, "VideoEditor", "generate_image", label):
            return asyncio.run(
                still_from_chain(engine, drawn_by, words, width=1080, height=1920, extra=asked)
            )

    def refused(exc: MediaProviderError, words_fields: dict[str, Any]) -> None:
        if not record_takes:
            return
        attempts = getattr(exc, "attempts", None) or []
        model = (attempts[-1].get("model") if attempts else None) or getattr(
            drawn_by[0] if drawn_by else None, "model", None
        )
        record_take(
            engine,
            storyboard_id=storyboard_id,
            scene_number=index,
            kind="still",
            prompt_hash=take_hash(words_fields, model),
            model_id=model,
            resolution=STILL_RESOLUTION,
            status="REFUSED",
            correlation_id=correlation_id,
            credits_quoted=_quoted_credits(drawn_by[-1]) if drawn_by else None,
            failure_code=failure_code_of(exc),
            failure_detail=failure_detail_of(exc),
        )

    def keep(
        result: Any,
        attempts: list[dict[str, Any]],
        words_fields: dict[str, Any],
        status: str,
        why: str | None,
    ) -> str | None:
        if not record_takes:
            return None
        model = attempts[-1].get("model") if attempts else None
        drawer = next((a for a in drawn_by if getattr(a, "model", None) == model), drawn_by[0])
        return record_take(
            engine,
            storyboard_id=storyboard_id,
            scene_number=index,
            kind="still",
            prompt_hash=take_hash(words_fields, model),
            model_id=model,
            resolution=STILL_RESOLUTION,
            status=status,
            correlation_id=correlation_id,
            credits_quoted=_quoted_credits(drawer),
            path=still,
            sha256=_file_sha256(still),
            failure_code=DEGENERATE_FAILURE_CODE if why else None,
            failure_detail=why,
        )

    try:
        img_res, image_attempts = draw(prompt, f"imaginea scenei {index}")
    except MediaProviderError as exc:
        refused(exc, fields)
        raise
    suffix = img_res.format if img_res.format in ("png", "jpeg", "webp") else "svg"
    still = work_dir / f"scene_{index:02d}.{suffix}"
    still.write_bytes(img_res.image_bytes)
    if not record_takes:
        return still, image_attempts, None

    broken = still_is_degenerate(find_ffmpeg(ffmpeg_path), still)
    take_id = keep(img_res, image_attempts, fields, "REJECTED" if broken else "PAID", broken)
    if broken:
        # One more attempt, told plainly what a picture is. A still costs cents; a scene of
        # stripes costs the film. The broken one stays on the books, REJECTED.
        production.setdefault("image_retries", []).append({"scene_index": index, "reason": broken})
        try:
            again, retry_attempts = draw(retry_prompt, f"imaginea scenei {index} (reluare)")
        except MediaProviderError as exc:
            refused(exc, retry_fields)
            raise
        # The second attempt is bought like the first, so the books see both.
        image_attempts = image_attempts + retry_attempts
        suffix = again.format if again.format in ("png", "jpeg", "webp") else "svg"
        still = work_dir / f"scene_{index:02d}.{suffix}"
        still.write_bytes(again.image_bytes)
        broken = still_is_degenerate(find_ffmpeg(ffmpeg_path), still)
        if broken:
            production.setdefault("degenerate_stills", []).append(
                {"scene_index": index, "reason": broken}
            )
        take_id = keep(
            again, retry_attempts, retry_fields, "REJECTED" if broken else "PAID", broken
        )
    return (
        still,
        image_attempts,
        {"take_id": take_id, "status": "REJECTED" if broken else "PAID", "reused": False},
    )


def _storyboard_scenes(engine: Engine, storyboard_id: str) -> tuple[str, list[dict[str, Any]]]:
    """The storyboard's title and its scenes as the render reads them."""
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise ValueError(f"Storyboard {storyboard_id} not found")
        rows = session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == storyboard_id)
            .order_by(StoryboardScene.scene_index)
        ).all()
        if not rows:
            raise ValueError(f"Storyboard {storyboard_id} has no scenes")
        return board.title, [scene_view(row) for row in rows]


def scene_view(row: StoryboardScene) -> dict[str, Any]:
    """One storyboard scene as the render reads it.

    ``scene_category`` is the scene's kind: it is what the model router is told and what the
    model's outcome is recorded under. ``story_purpose`` (HOOK, SETUP, ...) travels with it,
    so the router and the tier know which scenes carry the film.
    """
    kind = scene_kind_of({"scene_kind": row.scene_kind})
    return {
        "scene_index": row.scene_index,
        "visual_prompt": row.visual_prompt,
        # The compiled package: its motion prompt is what the video model is sent
        # (motion_request), never the still's words again.
        "prompt_json": dict(row.prompt_json or {}),
        "visual_type": row.visual_type,
        "scene_kind": kind,
        "scene_category": kind,
        "story_purpose": row.story_purpose,
        "card_json": dict(row.card_json) if isinstance(row.card_json, dict) else None,
        "duration_seconds": row.duration_seconds,
        "voiceover_segment": row.voiceover_segment,
        "shot_type": row.shot_type,
        "transition_in": row.transition_in,
        # Who is in the shot, which is what decides whose reference picture the still is
        # drawn from. The scenes carried everything but their cast.
        "character_ids": list(row.character_ids_json or []),
    }


def buy_stills(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    *,
    image_chain: list[ImageProvider],
    storage_root: Path | None = None,
    reference_for_scene: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    ffmpeg_path: str | None = None,
) -> dict[str, Any]:
    """The stills step: one still per LIVE scene, each bought only when no usable take exists.

    A card scene (DATA_CARD, TITLE_CARD, BLACK) is composed locally and never reaches the image
    model. A LIVE scene whose take (APPROVED, or PAID and not rejected) matches its prompt is
    used as it is: nothing is bought twice. A vendor refusal is kept on a REFUSED take with the
    vendor's own reason and the other scenes go on; an account problem (no credits, no access)
    or a second refused request in a row stops the step. Nothing here voices, animates or
    encodes, and the Owner's stop is read before each scene.

    This is the purchase itself. Whether the step may be bought at all (the shooting sheet's
    plan_hash, the Owner's yes) is decided by the caller through ``may_act`` before this runs.
    """
    from app.runbook.services import stop_requested  # noqa: PLC0415 - runbook imports media

    adapters = [adapter for adapter in image_chain if adapter is not None]
    if not adapters:
        raise ValueError("buy_stills needs at least one image adapter")
    title, scenes = _storyboard_scenes(engine, storyboard_id)
    work_dir = (storage_root or DEFAULT_STORAGE_ROOT) / storyboard_id
    work_dir.mkdir(parents=True, exist_ok=True)
    production: dict[str, Any] = {}
    results: list[dict[str, Any]] = []
    previous_kind: str | None = None
    stopped: str | None = None
    for scene in scenes:
        index = int(scene["scene_index"])
        entry: dict[str, Any] = {"scene_index": index, "scene_kind": scene_kind_of(scene)}
        if is_composed(scene):
            entry.update(status="composed", provenance="composed", credits=0)
            results.append(entry)
            continue
        if stopped is not None:
            entry.update(status="not_bought", reason=stopped)
            results.append(entry)
            continue
        if stop_requested(engine):
            stopped = STOP_REASON
            entry.update(status="not_bought", reason=stopped)
            results.append(entry)
            continue
        reference = reference_for_scene(scene) if reference_for_scene else None
        asked: dict[str, Any] = {"title": title, "scene_index": index}
        if reference:
            asked["reference_image"] = {
                "bytes": reference["bytes"],
                "mime_type": reference["mime_type"],
            }
        try:
            still, attempts, take = _still_for_scene(
                engine,
                storyboard_id,
                scene,
                adapters,
                asked,
                reference,
                work_dir,
                correlation_id=correlation_id,
                record_takes=True,
                takes_only=False,
                ffmpeg_path=ffmpeg_path,
                production=production,
                busy_engine=engine,
            )
        except MediaProviderError as exc:
            verdict = classify_vendor_failure(exc, previous_kind)
            previous_kind = verdict.kind
            entry.update(
                status="refused",
                failure_kind=verdict.kind,
                failure_code=failure_code_of(exc),
                failure_detail=failure_detail_of(exc),
                reason=verdict.reason_ro,
            )
            results.append(entry)
            if verdict.stop_step:
                stopped = verdict.reason_ro
            continue
        previous_kind = None
        entry.update(
            status="reused" if (take or {}).get("reused") else "bought",
            provenance="take",
            path=str(still),
            take=take,
            attempts=attempts,
        )
        results.append(entry)
    return {
        "storyboard_id": storyboard_id,
        "scenes": results,
        "bought": sum(1 for r in results if r["status"] == "bought"),
        "reused": sum(1 for r in results if r["status"] == "reused"),
        "composed": sum(1 for r in results if r["status"] == "composed"),
        "refused": sum(1 for r in results if r["status"] == "refused"),
        "stopped": stopped,
        "image_retries": production.get("image_retries", []),
        "degenerate_stills": production.get("degenerate_stills", []),
    }


def assemble_from_takes(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    **render: Any,
) -> dict[str, Any]:
    """Assemble the film from its takes alone: no still and no shot is bought.

    Every LIVE scene must have an APPROVED still take for its prompt as it is now, otherwise
    TakesMissing is raised before a render job exists. A LIVE scene's shot is its usable motion
    take (APPROVED, or PAID and not rejected) when one exists, else its still given a slow
    push, which quality control counts as a fallback. Cards are composed. Narration, captions,
    the master and the encode are done as in any render; any image or video adapter passed is
    never asked. The other keyword arguments are `assemble_video_job`'s.
    """
    _title, scenes = _storyboard_scenes(engine, storyboard_id)
    missing: list[int] = []
    with Session(engine) as session:
        for scene in scenes:
            if is_composed(scene):
                continue
            # The reference picture is part of the still's identity; it is read here the
            # same way the render reads it.
            chooser = render.get("reference_for_scene")
            reference = chooser(scene) if chooser else None
            fields = still_fields(str(scene["visual_prompt"] or ""), reference)
            from app.media.prompt_agent import strip_on_screen_text  # noqa: PLC0415

            retry = still_fields(
                strip_on_screen_text(str(scene["visual_prompt"] or "")) + DEGENERATE_RETRY_SUFFIX,
                reference,
            )
            if (
                usable_take(
                    session,
                    storyboard_id,
                    int(scene["scene_index"]),
                    "still",
                    [fields, retry],
                    statuses=("APPROVED",),
                )
                is None
            ):
                missing.append(int(scene["scene_index"]))
    if missing:
        raise TakesMissing(
            "Filmul nu se poate asambla din imaginile aprobate: "
            + ", ".join(f"Scena {n}" for n in missing)
            + " nu are o imagine aprobată pentru promptul de acum. Nimic nu a fost cumpărat."
        )
    return assemble_video_job(engine, storyboard_id, correlation_id, takes_only=True, **render)


def _compose_card_clip(
    scene: dict[str, Any],
    work_dir: Path,
    *,
    seconds: float,
    background: Path | None,
    ffmpeg_exe: str | None,
    fps: int = TIMELINE_FPS,
) -> dict[str, Any]:
    """One card scene's clip, composed locally from its own spec at the timeline's ``fps``:
    0 credits, no adapter."""
    spec = card_spec_from_json(scene_kind_of(scene), scene.get("card_json"))
    index = int(scene["scene_index"])
    usable_background = (
        background if background is not None and background.suffix.lower() in _RASTER else None
    )
    card = compose_card(
        spec,
        work_dir / f"card_{index:02d}.mp4",
        duration=seconds,
        fps=fps,
        background_still=usable_background,
        ffmpeg=ffmpeg_exe,
    )
    return {
        "kind": card.kind,
        "provenance": card.provenance,
        "credits": card.credits,
        "path": str(card.path),
        "sha256": card.sha256,
        "seconds": round(seconds, 3),
        "frames": card.frames,
        "background": usable_background.name if usable_background is not None else None,
    }


def _compose_cards(
    scenes: list[dict[str, Any]],
    frames: list[Path | None],
    production: dict[str, Any],
    work_dir: Path,
    *,
    ffmpeg_exe: str | None,
    fail: Callable[[str, str], None],
    spans: list[float] | None = None,
) -> list[Path | None]:
    """Compose every card scene of the film (one clip per scene, None for a LIVE scene).

    Each card lasts its shot's span (``spans``: the scene, plus any dissolve into the next),
    at the timeline's 24 fps, and stands on the film's first real still,
    blurred and darkened (cards.py), or on its colour canvas when there is none. A card whose
    spec cannot be composed honestly (no numbers, a bad spec) fails the job: it is never
    filmed instead. Without an encoder or without real stills nothing is composed here (the
    placeholder film and the missing encoder fail or degrade as they always did).
    """
    clips: list[Path | None] = [None] * len(scenes)
    if not ffmpeg_exe:
        return clips
    background = next(
        (frame for frame in frames if frame is not None and frame.suffix.lower() in _RASTER),
        None,
    )
    for position, scene in enumerate(scenes):
        if not is_composed(scene):
            continue
        index = int(scene["scene_index"])
        span = spans[position] if spans is not None else float(scene["duration_seconds"])
        try:
            card = _compose_card_clip(
                scene, work_dir, seconds=span, background=background, ffmpeg_exe=ffmpeg_exe
            )
        except CardError as exc:
            reason = f"Scena {index}: cardul nu poate fi compus: {exc}"
            fail(reason, reason)
            raise RenderEngineUnavailable(reason) from exc
        clips[position] = Path(card["path"])
        for entry in production["scenes"]:
            if entry.get("scene_index") == index:
                entry["card"] = card
                break
    return clips


def _clip_holds(
    ffmpeg_exe: str | None,
    scenes: list[dict[str, Any]],
    motion_clips: list[Path | None],
    card_clips: list[Path | None],
    lengths: list[float],
    production: dict[str, Any],
) -> list[float]:
    """How long each LIVE clip's last frame must be held to fill its shot: 0.0 for a clip that
    covers it (it is cut), and for every scene without a clip.

    A clip shorter than its shot is a vendor delivering less than it was asked for (the motion
    step asks whole seconds rounded up). It is not hidden: the clip's measured length and the
    held seconds go on the scene's motion record, and the Owner is told in Romanian.
    """
    holds = [0.0] * len(scenes)
    if not ffmpeg_exe:
        return holds
    for position, (scene, clip) in enumerate(zip(scenes, motion_clips, strict=True)):
        if clip is None or card_clips[position] is not None:
            continue
        have = _video_stream_seconds(ffmpeg_exe, clip)
        record = next(
            (
                entry.get("motion")
                for entry in production["scenes"]
                if entry.get("scene_index") == scene["scene_index"]
                and isinstance(entry.get("motion"), dict)
            ),
            None,
        )
        if have is None:
            continue
        if record is not None:
            record["clip_seconds"] = round(have, 3)
        need = lengths[position]
        if have + 0.5 / TIMELINE_FPS < need:
            holds[position] = need - have
            if record is not None:
                record["held_seconds"] = round(need - have, 3)
            production.setdefault("owner_warnings", []).append(
                f"Scena {scene['scene_index']}: clipul are {have:.2f} s, iar cadrul cere "
                f"{need:.2f} s; ultimul cadru al clipului este ținut {need - have:.2f} s."
            )
    return holds


def _timeline_record(
    scenes: list[dict[str, Any]],
    joins: list[float],
    lengths: list[float],
    holds: list[float],
    motion_clips: list[Path | None],
    card_clips: list[Path | None],
    *,
    dither: bool,
) -> dict[str, Any]:
    """The film's timeline as the manifest keeps it, and as quality control reads it: the
    frame rate, and each scene's place (start, end), how it is joined from the scene before,
    its shot's length and whether its shot is a generated clip (``moving``)."""
    spans: list[dict[str, Any]] = []
    clock = 0.0
    for position, scene in enumerate(scenes):
        length = float(scene["duration_seconds"])
        spans.append(
            {
                "scene_index": int(scene["scene_index"]),
                "start": round(clock, 6),
                "end": round(clock + length, 6),
                "join_in": "dissolve" if joins[position] > 0 else "cut",
                "dissolve_seconds": round(joins[position], 6),
                "shot_seconds": round(lengths[position], 6),
                "moving": not is_composed(scene) and motion_clips[position] is not None,
                "composed": card_clips[position] is not None,
                "held_seconds": round(holds[position], 3),
            }
        )
        clock += length
    spoken = [scene.get("audio_seconds") for scene in scenes]
    narration = (
        round(sum(float(s) for s in spoken if isinstance(s, int | float)), 3)
        if all(isinstance(s, int | float) for s in spoken)
        else None
    )
    return {
        "fps": TIMELINE_FPS,
        "dither": "zscale error_diffusion" if dither else "swscale",
        "spoken_tail_seconds": SPOKEN_TAIL_SECONDS,
        "film_seconds": round(clock, 6),
        "narration_seconds": narration,
        "spans": spans,
    }


def _write_captions(
    scenes: list[dict[str, Any]],
    work_dir: Path,
    ffmpeg_exe: str,
    *,
    wants_burn: bool,
) -> tuple[dict[str, Any], str | None]:
    """Write captions.srt and captions.ass beside the film; return the manifest's record and
    the filter that burns them (None when they are not burnt, with the reason recorded)."""
    from app.media import cards  # noqa: PLC0415

    cues = caption_cues(scenes)
    srt_file = work_dir / "captions.srt"
    srt_file.write_text(srt_from_cues(cues), encoding="utf-8")
    ass_file = work_dir / CAPTIONS_ASS_NAME
    reason: str | None = None
    try:
        ass_file.write_text(ass_from_cues(cues), encoding="utf-8")
        install_caption_fonts(work_dir)
    except cards.CardError as exc:
        reason = f"the caption font cannot be used: {exc}"
    can_burn = has_filter(ffmpeg_exe, "subtitles")
    if reason is None:
        if not wants_burn:
            reason = "captions_burn_in is off"
        elif not cues:
            reason = "no narration to caption"
        elif not can_burn:
            reason = "the encoder has no subtitles filter"
    burn_in = reason is None
    said = " ".join(" ".join(cue["lines"]) for cue in cues)
    try:
        uncovered = cards.uncovered_characters(said)
    except cards.CardError:
        uncovered = []
    record: dict[str, Any] = {
        "srt": str(srt_file),
        "ass": str(ass_file) if ass_file.is_file() else None,
        "cues": len(cues),
        "burned_in": burn_in,
        "style": (
            {
                "font": cards.BOLD,
                "font_size": CAPTION_FONT_SIZE,
                "outline": CAPTION_OUTLINE,
                "margin_v": CAPTION_MARGIN_V,
                "margin_x": CAPTION_MARGIN_X,
                "bottom_y": CAPTION_BOTTOM_Y,
                "right_clear": CAPTION_RIGHT_CLEAR,
                "words_per_card": [CAPTION_MIN_WORDS, CAPTION_MAX_WORDS],
            }
            if burn_in
            else None
        ),
        # How each card was timed: by the voice's own word timing, or by its characters.
        "timing": {
            "alignment": len({c["scene_index"] for c in cues if c["timing"] == "alignment"}),
            "character_share": len(
                {c["scene_index"] for c in cues if c["timing"] == "character_share"}
            ),
        },
        # Characters Inter has no glyph for, which libass draws from another face.
        "uncovered_characters": uncovered,
        "reason": reason,
    }
    return record, (ass_captions_filter(ass_file.name) if burn_in else None)


def _attach_motion(
    production: dict[str, Any], scene: dict[str, Any], record: dict[str, Any]
) -> None:
    """Put a scene's motion record on its entry in the manifest."""
    for entry in production["scenes"]:
        if entry.get("scene_index") == scene["scene_index"]:
            entry["motion"] = record
            break


def _usable_motion_take(
    engine: Engine,
    storyboard_id: str,
    scene: dict[str, Any],
    fields: dict[str, Any],
    seconds: float,
) -> SceneTake | None:
    """A shot of this scene already paid for with this package and still, long enough.

    The hero test shot is such a shot: bought by the motion step's first stair and kept in
    the film, never bought again (an APPROVED take is preferred over a PAID one).
    """
    with Session(engine) as session:
        found = _shot_take(session, storyboard_id, int(scene["scene_index"]), fields, seconds)
        if found is not None:
            session.expunge(found)
        return found


def _shot_take(
    session: Session,
    storyboard_id: str,
    scene_number: int,
    fields: dict[str, Any],
    seconds: float,
) -> SceneTake | None:
    """The usable shot of a scene among its motion and test-shot takes, APPROVED first."""
    found = [
        take
        for take in (
            usable_take(
                session,
                storyboard_id,
                scene_number,
                kind,
                [fields],
                min_seconds=round(seconds, 3),
            )
            for kind in SHOT_TAKE_KINDS
        )
        if take is not None
    ]
    found.sort(key=lambda take: 0 if take.status == "APPROVED" else 1)
    return found[0] if found else None


def _record_motion_take(
    engine: Engine,
    storyboard_id: str,
    scene: dict[str, Any],
    adapter: Any,
    fields: dict[str, Any],
    seconds: float,
    *,
    correlation_id: str,
    status: str,
    path: Path | None = None,
    failure_code: str | None = None,
    failure_detail: str | None = None,
) -> str:
    """Write the take of one shot the studio asked a vendor for."""
    model_name = getattr(adapter, "model", None)
    return record_take(
        engine,
        storyboard_id=storyboard_id,
        scene_number=int(scene["scene_index"]),
        kind="motion",
        prompt_hash=take_hash(fields, model_name),
        model_id=model_name,
        resolution=MOTION_RESOLUTION,
        status=status,
        correlation_id=correlation_id,
        seconds=round(seconds, 3),
        credits_quoted=_quoted_credits(adapter),
        path=path,
        sha256=_file_sha256(path) if path is not None else None,
        failure_code=failure_code,
        failure_detail=failure_detail,
    )


def assemble_video_job(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    storage_root: Path | None = None,
    ffmpeg_path: str | None = None,
    image_adapter: ImageProvider | None = None,
    image_chain: list[ImageProvider] | None = None,
    reference_for_scene: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    tts_adapter: TTSProvider | None = None,
    tts_adapter_for_scene: Callable[[dict[str, Any]], TTSProvider | None] | None = None,
    voice_segments_for_scene: Callable[[dict[str, Any]], list[dict[str, Any]] | None] | None = None,
    video_adapter_for_scene: Callable[[dict[str, Any]], VideoProvider | None] | None = None,
    motion_chooser: Callable[..., tuple[VideoProvider | None, dict[str, Any]]] | None = None,
    environment: str = "PRODUCTION",
    run_kind: str | None = None,
    motion_budget_usd: float | None = None,
    motion_max_usd_per_second: float | None = None,
    price_tolerance_percent: float = 5.0,
    motion_scene_limit: int | None = None,
    motion_from_prompt: bool = False,
    production_plan: dict[str, Any] | None = None,
    settings: Any | None = None,
    takes_only: bool = False,
) -> dict:
    """Run end-to-end video assembly and provenance recording.

    Scenes by kind: a LIVE scene is a still (and a shot) from a paid model; a DATA_CARD,
    TITLE_CARD or BLACK scene is composed locally by `app.media.cards` from its own card spec,
    0 credits, and never reaches an image or video adapter. With a real image adapter every
    paid still and shot is a SceneTake, and a usable take of the same prompt package (APPROVED,
    or PAID and not rejected) is used instead of being bought again. ``takes_only`` (what
    `assemble_from_takes` passes) buys nothing at all: each LIVE still is its APPROVED take,
    each shot its usable motion take or else the still given a push, and no adapter is asked.

    ``settings`` is the studio's configuration, read for the Owner's delivery choices:
    ``captions_burn_in`` (default True) burns the captions into the picture; off, the SRT
    is still written beside the film for the platform to carry as a track.

    ``image_adapter`` and ``tts_adapter`` are the providers the Owner selected and verified.
    When either is absent the corresponding deterministic placeholder generator is used, and
    the asset is recorded under the placeholder provider name — which QC blocks from
    publication. The recorded name always says which generator actually made the frames, so a
    render can never be mistaken for publishable content it is not.

    ``motion_chooser`` is asked for the model of each scene, given what the scene requires
    — its tier, its length and what it may cost — and answers with an adapter and the reason
    it chose that model over the alternatives. ``environment`` says which policy answered
    (TEST takes the cheapest that can do the job, PRODUCTION the least expensive that
    reaches the quality) and, with ``run_kind``, decides whether what happens here may teach
    the studio about a model's picture: an ordinary functional test never does.

    ``motion_from_prompt`` films each shot from the scene's words instead of its approved
    still — what a test render does, on the cheapest model that accepts a prompt, so looking
    at how a film reads costs cents instead of dollars.

    ``motion_budget_usd`` is the most this render may spend on generated motion; after each
    shot the vendor's own stated cost is subtracted, and the pass stops before the shot that
    would cross the line. ``motion_scene_limit`` generates motion for the first N scenes
    only — what a test render uses, so seeing how a film reads costs one shot and not eight.

    ``video_adapter_for_scene`` resolves the motion model for a scene. With one, the scene's
    approved still is the first frame of a generated clip and the film moves; without one the
    still becomes a slow push, and either way the shots dissolve into one another instead of
    cutting. What made each shot is recorded per scene, so a film can always be read back.

    ``image_chain`` is the vendors a still may be drawn by, in order: the resolved one and at
    most one alternative the Owner approved for this purpose. Each attempt is recorded with
    its connection, its model and what it is worth at the stored price, on the scene and on
    the job, so the books charge the vendor that actually drew the picture and a refused
    attempt is not free by omission. Without it the single ``image_adapter`` is the chain,
    which is what every studio does until the Owner approves an alternative.

    ``reference_for_scene`` answers with the reference picture of the character the scene's
    cast names, or None. It is passed only to an adapter that declares it can take one, and
    the attempt records whether the still was drawn from the sheet or from the words. It may
    raise ``app.media.services.ReferenceRequired`` for a character whose look the Owner
    locked and whose reference cannot be read: the job is failed and the refusal re-raised
    rather than the scene being drawn with an invented face.

    ``tts_adapter_for_scene`` resolves a voice per scene (a recurring character's locked
    voice, or a scene override); when it returns None for a scene, ``tts_adapter`` is used,
    and when that is None too the placeholder narrator is.

    ``voice_segments_for_scene`` answers with a scene's takes, one per speaker in the order
    they speak (``{speaker, character_id, text, adapter, voice_source}``,
    `app.media.speaker_voices`), or None for a scene read whole. Each take is spoken by its
    own adapter (the scene's voice when it has none), the takes are joined with
    ``SPEAKER_GAP_SECONDS`` of silence, and the captions are timed to each take, so they
    follow the speaker. A speaker's name is never read and never captioned.

    ``production_plan`` is the
    resolved hierarchy the caller built; it is stored on the job with what each scene
    actually used, so a render can be audited without re-running the resolution.

    Raises RenderEngineUnavailable when ffmpeg is missing or the encode fails. No MediaAsset
    is recorded in that case, so no downstream gate can pass on a non-existent render.
    """
    # Imported here, not at the top: `app.media.services` reaches back into this module for a
    # render, and the two would import each other at load time.
    from app.media.services import ReferenceRequired  # noqa: PLC0415

    render_job_id = str(uuid4())
    production: dict[str, Any] = {
        "plan": production_plan or {},
        "scenes": [],
        "image": {"provider": None, "model": None},
        "voice": {"provider": None},
    }
    started_at = utc_now()
    ffmpeg_exe = resolve_ffmpeg_path(ffmpeg_path)

    if storage_root is None:
        storage_root = DEFAULT_STORAGE_ROOT
    work_dir = storage_root / storyboard_id
    work_dir.mkdir(parents=True, exist_ok=True)

    with Session(engine) as session, session.begin():
        sb = session.get(Storyboard, storyboard_id)
        if not sb:
            raise ValueError(f"Storyboard {storyboard_id} not found")

        scenes = session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == storyboard_id)
            .order_by(StoryboardScene.scene_index)
        ).all()
        if not scenes:
            raise ValueError(f"Storyboard {storyboard_id} has no scenes")

        storyboard_title = sb.title
        # Each scene carries its kind (scene_category, what the router is told and what the
        # outcome is recorded under) and its story purpose (what decides its tier).
        scenes_data: list[dict[str, Any]] = [scene_view(s) for s in scenes]

        job = VideoRenderJob(
            id=render_job_id,
            storyboard_id=storyboard_id,
            output_asset_id=None,
            status="RENDERING",
            render_engine="FFMPEG",
            command_args_json=[],
            execution_log="Assembly started...",
            started_at=started_at,
            finished_at=None,
            duration_ms=None,
            event_id=None,
        )
        session.add(job)

    # 1. Generate placeholder visual cards (SVG for the UI, raster PPM for the encoder)
    #    and voiceover segments. The captions come after: a cue is timed to the narration
    #    actually recorded for its scene, which is not known until the voice has spoken.
    visual_adapter: ImageProvider = image_adapter or DeterministicVisualAdapter()
    # The vendors a still may be drawn by, in order. One long unless the Owner approved an
    # alternative for this purpose, which is every studio until he does — and the placeholder
    # generator when there is no image provider at all, exactly as before.
    drawn_by: list[ImageProvider] = [a for a in (image_chain or []) if a is not None] or [
        visual_adapter
    ]
    placeholder_voice = DeterministicTTSAdapter()
    # The frames are real only when a real generator made them; this single name is what the
    # asset, the event and the QC report are all written from.
    visual_source = getattr(visual_adapter, "PROVIDER_NAME", PLACEHOLDER_VISUAL_PROVIDER)
    # Real stills: drawn by a real vendor, or (takes_only) the approved takes of one.
    real_stills = image_adapter is not None or takes_only
    # Every paid still and shot is a take; a placeholder picture costs nothing and is not one,
    # and a render from takes buys nothing to record.
    record_takes = image_adapter is not None and not takes_only
    if takes_only and image_adapter is None:
        visual_source = TAKES_VISUAL_SOURCE
    production["image"] = {
        "provider": visual_source,
        "model": getattr(visual_adapter, "model", None),
        "integration_id": getattr(visual_adapter, "integration_id", None),
    }
    # One real narrator for the whole video, or the placeholder: a video whose narration is
    # partly placeholder is labelled placeholder as a whole, so QC blocks it.
    scene_voices: list[TTSProvider | None] = []
    for scene in scenes_data:
        chosen = tts_adapter_for_scene(scene) if tts_adapter_for_scene else None
        scene_voices.append(chosen or tts_adapter)
    all_real = bool(scene_voices) and all(v is not None for v in scene_voices)
    voice_source = (
        getattr(scene_voices[0], "PROVIDER_NAME", PLACEHOLDER_VOICE_PROVIDER)
        if all_real
        else PLACEHOLDER_VOICE_PROVIDER
    )
    production["voice"]["provider"] = voice_source
    # Which connection the voice came from: the books price a scene by its model, and a
    # model belongs to a connection. Naming only the provider left narration unpriceable.
    used_voice = scene_voices[0] if all_real and scene_voices else None
    production["voice"]["integration_id"] = getattr(used_voice, "integration_id", None)
    production["voice"]["model"] = getattr(used_voice, "model", None)

    total_duration = sum(s["duration_seconds"] for s in scenes_data)
    master_audio_bytes = bytearray()
    #: One entry per scene: its still (real or placeholder), or None for a composed card.
    frame_files: list[Path | None] = []

    generated_frames: list[Path | None] = []
    voice_segments: list[Path] = []
    #: The silence after each file of `voice_segments`: a breath between two speakers, and
    #: after a scene's last take whatever its picture lasts beyond its words.
    voice_pads: list[float] = []
    #: Where in `voice_pads` each scene's last take sits (real narration only).
    last_pads: list[int] = []

    # The encode's command and the editor's id are filled in later; the failure helper is
    # defined here because the scene loop below can already fail the job (the Owner's stop),
    # and a closure reads these names when it is called, not where it is written.
    command_args: list[str] = []
    editor_id: str | None = None

    def _fail_job(reason: str, log: str) -> None:
        if editor_id is not None:
            from app.agents.services import mark_idle  # noqa: PLC0415

            mark_idle(engine, editor_id, "assemble_video")
        with Session(engine) as session, session.begin():
            job_rec = session.get(VideoRenderJob, render_job_id)
            if job_rec:
                job_rec.status = "FAILED"
                job_rec.execution_log = log[-8000:]
                job_rec.command_args_json = command_args
                # What the render had already built when it stopped: the scenes whose
                # narration was recorded and whose shots were generated, in the shape the
                # finished render writes. The vendor charges for those whether or not the
                # film was finished, and `economy.accountant.record_failed_render_cost`
                # reads them from here; a job that kept this empty priced a lost render
                # at nothing, and the day's budget saw a day that had spent nothing.
                job_rec.production_json = production
                job_rec.finished_at = utc_now()
            append_event(
                session,
                "media.render_failed",
                "video_render_job",
                render_job_id,
                1,
                {"storyboard_id": storyboard_id, "reason": reason},
                correlation_id,
            )
        logger.error("render_failed", extra={"reason": reason, "job_id": render_job_id})

    def _stop_if_asked() -> None:
        """Read the Owner's switch between two units of work; a set stop ends the render.

        The runbook reads it between stages, so a render of eight scenes used to run to its
        end after the Owner pressed STOP — eight shots bought for a day he had ended. One
        short read of the policy row per scene, never mid-write: the scene already made is
        on disk, the next is not started, and the job says why.
        """
        from app.runbook.services import stop_requested  # noqa: PLC0415 - runbook imports media

        if stop_requested(engine):
            _fail_job(STOP_REASON, STOP_REASON)
            raise RenderStopped(STOP_REASON)

    # A vendor that refuses a picture or a narration ends the render, and the job must
    # say so: the error carries no job id, so a job left RENDERING is a render nobody can
    # price afterwards. The Owner's stop already failed the job cleanly between two
    # scenes; a refusal now does the same, keeps what was built, and is re-raised for the
    # media stage to cost and to report.
    try:
        for position, scene in enumerate(scenes_data):
            if position:
                _stop_if_asked()  # the first scene is the render starting; the stage just asked
            index = scene["scene_index"]
            image_attempts: list[dict[str, Any]] = []
            still_take: dict[str, Any] | None = None
            if is_composed(scene):
                # A chart, a title or a black screen is composed from its own spec after the
                # narration is measured (its length is the narration's). It never reaches an
                # image or a video model: the Nepal chart and black screen went to a
                # photographic model and came back as women.
                if real_stills:
                    generated_frames.append(None)
                else:
                    frame_path = work_dir / f"frame_{index:02d}.ppm"
                    write_placeholder_frame_ppm(frame_path, index)
                    frame_files.append(frame_path)
            else:
                # The face this scene must keep, read before anything is drawn. A refusal
                # here is the studio declining to invent a locked character's look; it is
                # caught below, fails the job and is re-raised, never swallowed as a vendor
                # error.
                reference = reference_for_scene(scene) if reference_for_scene else None
                asked: dict[str, Any] = {"title": storyboard_title, "scene_index": index}
                if reference:
                    asked["reference_image"] = {
                        "bytes": reference["bytes"],
                        "mime_type": reference["mime_type"],
                    }
                still, image_attempts, still_take = _still_for_scene(
                    engine,
                    storyboard_id,
                    scene,
                    drawn_by,
                    asked,
                    reference,
                    work_dir,
                    correlation_id=correlation_id,
                    record_takes=record_takes,
                    takes_only=takes_only,
                    ffmpeg_path=ffmpeg_path,
                    production=production,
                    busy_engine=engine if image_adapter is not None else None,
                )
                if real_stills:
                    # A real still goes to the encoder as it arrived; ffmpeg scales it.
                    generated_frames.append(still)
                else:
                    frame_path = work_dir / f"frame_{index:02d}.ppm"
                    write_placeholder_frame_ppm(frame_path, index)
                    frame_files.append(frame_path)

            real_voice = scene_voices[scenes_data.index(scene)]
            # One take per speaker where the scene's lines say who speaks them (S7), each in
            # its own voice and the scene's voice when that has none; otherwise the scene's
            # words are one take in the scene's voice, as they always were.
            given = voice_segments_for_scene(scene) if voice_segments_for_scene else None
            parts: list[dict[str, Any]] = [p for p in (given or []) if str(p.get("text") or "")]
            by_speaker = bool(parts)
            if not by_speaker:
                parts = [{"text": scene["voiceover_segment"]}]
            voice_started = time.monotonic()
            takes: list[tuple[dict[str, Any], TTSProvider, Any]] = []
            for part in parts:
                take_voice: TTSProvider = (
                    (part.get("adapter") or real_voice) if all_real else None
                ) or placeholder_voice
                with _at_work(
                    engine if all_real else None,
                    "VoiceArtist",
                    "synthesize_voice",
                    f"vocea scenei {index}",
                ):
                    said = asyncio.run(take_voice.synthesize(str(part["text"])))
                takes.append((part, take_voice, said))
            voice_adapter = takes[0][1]
            gap = SPEAKER_GAP_SECONDS if len(takes) > 1 else 0.0
            spoken_seconds = sum(t[2].duration_seconds for t in takes) + gap * (len(takes) - 1)
            scene_record: dict[str, Any] = {
                "scene_index": index,
                "voice_provider": getattr(
                    voice_adapter, "PROVIDER_NAME", PLACEHOLDER_VOICE_PROVIDER
                ),
                "model_id": getattr(voice_adapter, "model", None) or None,
                "voice_id": getattr(voice_adapter, "voice_id", None) or None,
                "characters": sum(len(str(t[0]["text"])) for t in takes),
                "audio_seconds": round(spoken_seconds, 3),
                "synthesis_ms": round((time.monotonic() - voice_started) * 1000, 1),
                "attempts": 1,
                # Which vendor actually drew this scene's still. The books used to price
                # every still at the film-level record, so a scene the approved
                # alternative drew was charged to the first vendor's model.
                "image": image_attempts[-1] if image_attempts else None,
                "scene_kind": scene_kind_of(scene),
                "story_purpose": scene.get("story_purpose"),
                # Which take the still is ({take_id, status, reused}); None for a card or a
                # placeholder picture, which nobody paid for.
                "still_take": still_take,
            }
            if by_speaker:
                # Who said what, in which voice: the render can be read back take by take.
                scene_record["segments"] = [
                    {
                        "speaker": part.get("speaker"),
                        "character_id": part.get("character_id"),
                        "voice_provider": getattr(
                            adapter, "PROVIDER_NAME", PLACEHOLDER_VOICE_PROVIDER
                        ),
                        "model_id": getattr(adapter, "model", None) or None,
                        "voice_id": getattr(adapter, "voice_id", None) or None,
                        "voice_source": (
                            (part.get("voice_source") if part.get("adapter") else "scene_voice")
                            if all_real
                            else "placeholder"
                        ),
                        "characters": len(str(part["text"])),
                        "audio_seconds": round(said.duration_seconds, 3),
                    }
                    for part, adapter, said in takes
                ]
                # The captions follow the takes: each take's words are up while it is said.
                offset = 0.0
                timed: list[dict[str, Any]] = []
                for part, _adapter, said in takes:
                    timed.append(
                        {
                            "text": str(part["text"]),
                            "offset": round(offset, 3),
                            "seconds": round(said.duration_seconds, 3),
                            # The voice's own word timing, when the take came back with it:
                            # each caption card comes up on its first word.
                            "words": take_word_timing(said),
                        }
                    )
                    offset += said.duration_seconds + gap
                scene["voice_segments"] = timed
            else:
                scene["word_timings"] = take_word_timing(takes[0][2])
            production["scenes"].append(scene_record)
            production.setdefault("image_attempts", []).append(
                {"scene_index": index, "attempts": image_attempts}
            )
            # The captions are timed from this: the scene's words last as long as its recording.
            scene["audio_seconds"] = round(spoken_seconds, 3)
            if all_real:
                for position, (_part, _adapter, said) in enumerate(takes):
                    name = (
                        f"voice_{index:02d}.{said.format}"
                        if len(takes) == 1
                        else f"voice_{index:02d}_{position + 1:02d}.{said.format}"
                    )
                    segment = work_dir / name
                    segment.write_bytes(said.audio_bytes)
                    voice_segments.append(segment)
                    voice_pads.append(gap if position < len(takes) - 1 else 0.0)
                # The silence after the scene's last take is set once every scene is measured
                # (scene_spans): the scene's words plus a breath, whatever its picture lasts.
                last_pads.append(len(voice_pads) - 1)
            else:
                for position, (_part, _adapter, said) in enumerate(takes):
                    if not master_audio_bytes:
                        master_audio_bytes = bytearray(said.audio_bytes)
                    elif len(said.audio_bytes) > 44:
                        master_audio_bytes.extend(said.audio_bytes[44:])
                    if position < len(takes) - 1:
                        # The placeholder voice is 44.1 kHz 16-bit mono PCM: silence is zeros.
                        master_audio_bytes.extend(bytes(2 * int(gap * 44100)))

    except ReferenceRequired as exc:
        # Not the vendor refusing, but the studio: a character whose look the Owner locked has
        # no reference picture the render can read, and drawing the scene anyway would invent
        # the face the lock exists to fix. The job is failed like any other unfinished render
        # — so what was already bought can be priced — and the refusal goes up as itself.
        _fail_job(f"The scene needs a reference picture: {exc}", str(exc))
        raise
    except MediaProviderError as exc:
        _fail_job(f"The vendor refused the render: {exc}", str(exc))
        raise
    except TakesMissing as exc:
        _fail_job(str(exc), str(exc))
        raise

    if real_stills:
        frame_files = generated_frames

    # The timeline, now that every scene's words are measured: a scene lasts its words plus a
    # breath, never past its plan and never cutting a word, on whole frames of the 24 fps
    # timeline (scene_spans). The planned lengths used to stand when the words were shorter,
    # so the Nepal film carried seconds of silence under still pictures. Without real
    # narration the plan stands, on whole frames.
    planned_lengths = [float(scene["duration_seconds"] or 0.0) for scene in scenes_data]
    if all_real:
        spoken_lengths = [float(scene.get("audio_seconds") or 0.0) for scene in scenes_data]
        for scene, span, pad_at, words_for in zip(
            scenes_data,
            scene_spans(planned_lengths, spoken_lengths),
            last_pads,
            spoken_lengths,
            strict=True,
        ):
            scene["duration_seconds"] = span
            # The next scene's words start with its shot: the silence after this scene's last
            # take is whatever its span lasts beyond its words.
            voice_pads[pad_at] = max(0.0, span - words_for)
    else:
        for scene, plan in zip(scenes_data, planned_lengths, strict=True):
            scene["duration_seconds"] = whole_frames(plan)
    total_duration = sum(s["duration_seconds"] for s in scenes_data)
    # Hard cuts, and a dissolve only where the scene's transition_in asks: each shot is its
    # scene, plus the overlap of a dissolve into the next one.
    joins = scene_joins(scenes_data)
    lengths = shot_spans(scenes_data, joins)

    # The motion pass runs after the narration, because a shot lasts as long as its words and
    # that length is measured, not planned. A scene whose model refuses is a still that pushes
    # slowly; the film is still a film.
    motion_clips: list[Path | None] = [None] * len(scenes_data)
    card_clips = _compose_cards(
        scenes_data,
        frame_files,
        production,
        work_dir,
        ffmpeg_exe=ffmpeg_exe if real_stills else None,
        fail=_fail_job,
        spans=lengths,
    )
    motion_seconds = 0.0
    motion_credits = 0.0
    credit_price = _credit_price(engine)
    remaining_usd = motion_budget_usd
    shots_made = 0
    asks_models = bool(video_adapter_for_scene or motion_chooser) and not takes_only
    if real_stills and ffmpeg_exe and (asks_models or takes_only):
        live_position = -1
        for position, (scene, frame) in enumerate(zip(scenes_data, frame_files, strict=False)):
            if is_composed(scene) or frame is None:
                continue  # a card is composed, never filmed: no router, no adapter
            still = frame
            live_position += 1
            # A vendor is asked for the scene plus the headroom of the longest dissolve; the
            # shot it fills is the scene plus the dissolve into the next one, if any.
            wanted = float(scene["duration_seconds"]) + TRANSITION_SECONDS
            needed = lengths[position]
            tier = scene_tier(scene, len(scenes_data))
            # A shot already paid for with this package, from this still, long enough for
            # its shot, is used as it is: the Nepal film's second render bought every clip
            # again with the same prompts.
            fields = motion_fields(scene, _file_sha256(still), from_prompt=motion_from_prompt)
            found_take = _usable_motion_take(engine, storyboard_id, scene, fields, needed)
            if found_take is not None:
                reused_clip = _take_file(found_take, work_dir, f"motion_{scene['scene_index']:02d}")
                motion_clips[position] = reused_clip
                _attach_motion(
                    production,
                    scene,
                    {
                        "model": found_take.model_id,
                        "asked_seconds": round(wanted, 3),
                        "shot_seconds": round(needed, 3),
                        "tier": tier,
                        "scene_category": scene_kind_of(scene),
                        "story_purpose": scene.get("story_purpose"),
                        "reused_take": True,
                        "take_id": found_take.id,
                        "take_status": found_take.status,
                        "bytes": reused_clip.stat().st_size,
                    },
                )
                motion_seconds += wanted
                continue
            if takes_only:
                # Assembling from takes buys nothing: no usable shot means the still pushed,
                # which quality control counts as a fallback.
                _attach_motion(
                    production,
                    scene,
                    {
                        "model": None,
                        "asked_seconds": round(wanted, 3),
                        "shot_seconds": round(needed, 3),
                        "tier": tier,
                        "scene_category": scene_kind_of(scene),
                        "story_purpose": scene.get("story_purpose"),
                        "refused": "nicio mișcare plătită pentru promptul de acum (imagine fixă)",
                    },
                )
                continue
            _stop_if_asked()  # a shot is the money; the switch is read before each one
            if motion_scene_limit is not None and live_position >= max(0, motion_scene_limit):
                production.setdefault("motion_notes", []).append(
                    f"scene {scene['scene_index']}: not generated (test limit {motion_scene_limit})"
                )
                continue
            # What a shot costs is known only after the vendor names it, so the first shot
            # teaches the price and every shot after it is checked against what remains: a
            # ceiling that stops at zero would still allow one shot too many.
            likely = (motion_credits * credit_price / max(1, shots_made)) if credit_price else 0.0
            if remaining_usd is not None and shots_made and remaining_usd < likely:
                production.setdefault("motion_notes", []).append(
                    f"scene {scene['scene_index']}: not generated (the render's motion budget "
                    f"leaves {remaining_usd:.2f} USD and a shot costs about {likely:.2f})"
                )
                continue
            decision: dict[str, Any] = {}
            if motion_chooser is not None:
                # Chosen per scene, by what this scene needs (the Owner, 2026-09-27); a model
                # that failed another scene is not excluded here: a failure moves only the
                # scene it happened to.
                adapter, decision = motion_chooser(scene, tier, wanted, remaining_usd, ())
            else:
                adapter = video_adapter_for_scene(scene) if video_adapter_for_scene else None
            if adapter is None:
                if decision:
                    production.setdefault("motion_notes", []).append(
                        f"scene {scene['scene_index']}: {decision.get('reason', 'no model')}"
                    )
                continue
            record: dict[str, Any] = {
                "provider": getattr(adapter, "PROVIDER_NAME", "unknown"),
                "model": getattr(adapter, "model", None),
                "integration_id": getattr(adapter, "integration_id", None),
                "asked_seconds": round(wanted, 3),
                "shot_seconds": round(needed, 3),
                "tier": tier,
                "scene_category": scene_kind_of(scene),
                "story_purpose": scene.get("story_purpose"),
                "decision": decision or None,
            }
            # Ask the vendor what this shot costs before buying it. The quote decides,
            # not a price written down elsewhere: a steward's reading of one page once
            # outlived four renders that measured seventeen times more. A quote past a
            # ceiling means the shot is not bought at all.
            quoted = _quote_motion(
                adapter,
                scene,
                None if motion_from_prompt else still,
                wanted,
                ffmpeg_exe,
            )
            if quoted is not None:
                record["quoted_credits"] = quoted
            refusal = None
            if quoted is not None and credit_price:
                quoted_usd = float(quoted) * credit_price
                record["quoted_usd"] = round(quoted_usd, 4)
                model_name = getattr(adapter, "model", None)
                integration = getattr(adapter, "integration_id", None)
                if model_name and integration and wanted > 0:
                    stale = record_quoted_price(
                        engine,
                        str(integration),
                        str(model_name),
                        quoted_usd / wanted,
                        "per_second_usd",
                        tolerance_percent=price_tolerance_percent,
                    )
                    if stale is not None:
                        record["price_was_stale"] = stale
                        production.setdefault("motion_notes", []).append(
                            f"scene {scene['scene_index']}: the stored price was stale "
                            f"({stale['stored']:.4f} -> {stale['observed']:.4f} USD/s as "
                            "the vendor quotes it)"
                        )
                if motion_budget_usd is not None and quoted_usd > float(motion_budget_usd):
                    refusal = (
                        f"the vendor quotes {quoted_usd:.2f} USD, above the "
                        f"{float(motion_budget_usd):.2f} USD this render may spend on a shot"
                    )
                elif (
                    motion_max_usd_per_second is not None
                    and wanted > 0
                    and quoted_usd / wanted > float(motion_max_usd_per_second)
                ):
                    refusal = (
                        f"the vendor quotes {quoted_usd / wanted:.2f} USD a second, above "
                        f"the {float(motion_max_usd_per_second):.2f} USD ceiling"
                    )
                elif remaining_usd is not None and quoted_usd > remaining_usd:
                    refusal = (
                        f"the vendor quotes {quoted_usd:.2f} USD and only "
                        f"{remaining_usd:.2f} USD is left of this render's motion budget"
                    )
            if refusal is not None:
                record["refused"] = refusal
                production.setdefault("motion_notes", []).append(
                    f"scene {scene['scene_index']}: not generated ({refusal})"
                )
                _attach_motion(production, scene, record)
                continue
            try:
                with _at_work(
                    engine,
                    "VideoEditor",
                    "generate_motion",
                    f"mișcarea scenei {scene['scene_index']}",
                ):
                    clip_bytes, raw = _generate_motion(
                        adapter,
                        scene,
                        None if motion_from_prompt else still,
                        wanted,
                        ffmpeg_exe,
                    )
                credits = getattr(adapter, "last_estimated_credits", None)
                if isinstance(credits, int | float):
                    record["estimated_credits"] = float(credits)
                    motion_credits += float(credits)
                    shots_made += 1
                    if remaining_usd is not None and credit_price:
                        remaining_usd -= float(credits) * credit_price
                clip = work_dir / f"motion_{scene['scene_index']:02d}.mp4"
                clip.write_bytes(clip_bytes)
                motion_clips[position] = clip
                record["bytes"] = len(clip_bytes)
                record["task"] = (raw or {}).get("task_status")
                motion_seconds += wanted
                if record_takes:
                    record["take_id"] = _record_motion_take(
                        engine,
                        storyboard_id,
                        scene,
                        adapter,
                        fields,
                        wanted,
                        correlation_id=correlation_id,
                        status="PAID",
                        path=clip,
                    )
            except (MediaProviderError, MediaProviderNotConfigured, ValueError, OSError) as exc:
                record["refused"] = str(exc)[:200]
                # The vendor charges for a shot it generated even when the studio failed to
                # bring it home; two such shots cost six dollars and were thrown away. What
                # was paid for is recorded as paid, whether or not it reached the film.
                credits = getattr(adapter, "last_estimated_credits", None)
                if isinstance(credits, int | float):
                    record["estimated_credits"] = float(credits)
                    record["paid_but_lost"] = True
                    motion_credits += float(credits)
                    shots_made += 1
                    if remaining_usd is not None and credit_price:
                        remaining_usd -= float(credits) * credit_price
                # The failure sorted by kind, with the vendor's own reason (the field it
                # refused): a SAFETY or CONTRACT failure concerns only this scene.
                verdict = (
                    classify_vendor_failure(exc) if isinstance(exc, MediaProviderError) else None
                )
                record["failure_kind"] = verdict.kind if verdict is not None else "TECHNICAL"
                record["failure_code"] = failure_code_of(exc)
                record["failure_detail"] = failure_detail_of(exc)
                if record_takes:
                    record["take_id"] = _record_motion_take(
                        engine,
                        storyboard_id,
                        scene,
                        adapter,
                        fields,
                        wanted,
                        correlation_id=correlation_id,
                        # A shot the vendor charged for and the studio lost is paid, with no
                        # file to reuse; a refused request is REFUSED.
                        status="PAID" if record.get("paid_but_lost") else "REFUSED",
                        failure_code=record["failure_code"],
                        failure_detail=record["failure_detail"],
                    )
                logger.info(
                    "motion_not_generated",
                    extra={"scene_index": scene["scene_index"], "reason": str(exc)[:160]},
                )
            _attach_motion(production, scene, record)
    _record_outcomes(
        engine,
        production,
        render_job_id,
        environment=environment,
        run_kind=run_kind,
        credit_price=credit_price,
    )
    # Each clip is measured against the shot it fills. The motion step buys whole seconds
    # rounded up, so a clip covers its shot and is cut; one a vendor delivered short has its
    # last frame held for the rest, which is recorded on the scene and told to the Owner
    # (quality control counts those frames as duplicates).
    holds = _clip_holds(ffmpeg_exe, scenes_data, motion_clips, card_clips, lengths, production)
    # A scene the model was asked for and did not deliver — refused, failed, or priced past
    # the ceiling — is a still given a push. Counted here so quality control can read how
    # much of the film moves: a note nobody read once let a slideshow through as a film.
    attempted = [
        entry["motion"] for entry in production["scenes"] if isinstance(entry.get("motion"), dict)
    ]
    clips_made = sum(1 for clip in motion_clips if clip is not None)
    production["motion"] = {
        "clips": clips_made,
        "scenes": len(scenes_data),
        "motion_scenes": clips_made,
        "fallback_scenes": sum(1 for record in attempted if not record.get("bytes")),
        # Scenes no model was asked for: a test's scene limit, a spent budget, no model.
        # A composed card is not one: it was never meant to be filmed.
        "skipped_scenes": sum(1 for scene in scenes_data if not is_composed(scene))
        - len(attempted),
        "composed_scenes": sum(1 for clip in card_clips if clip is not None),
        "reused_takes": sum(1 for record in attempted if record.get("reused_take")),
        "seconds": round(motion_seconds, 3),
        "estimated_credits": round(motion_credits, 2) or None,
        "estimated_usd": round(motion_credits * credit_price, 4) if credit_price else None,
        "lost_credits": round(
            sum(
                float((s.get("motion") or {}).get("estimated_credits") or 0)
                for s in production["scenes"]
                if (s.get("motion") or {}).get("paid_but_lost")
            ),
            2,
        )
        or None,
        "budget_usd": motion_budget_usd,
        "max_usd_per_second": motion_max_usd_per_second,
        "scene_limit": motion_scene_limit,
        "from_prompt": motion_from_prompt,
        "environment": environment,
        "run_kind": run_kind or ("TEST_FUNCTIONAL" if environment == "TEST" else "PRODUCTION"),
        # Hard cuts by default; each dissolve the script asked for, in seconds.
        "transition_seconds": DISSOLVE_SECONDS,
        "dissolves": sum(1 for join in joins if join > 0),
    }

    audio_file = work_dir / VOICE_TRACK_NAME
    if all_real:
        if not ffmpeg_exe:
            # The encoder is checked again below, but joining the narration needs it first,
            # and failing here keeps the reason specific.
            raise RenderEngineUnavailable(
                "FFmpeg is required to join provider narration audio, and it was not found."
            )
        audio_file = _concatenate_audio(ffmpeg_exe, voice_segments, work_dir, voice_pads)
    else:
        audio_file.write_bytes(master_audio_bytes)
    # What the sound can be remade from later, for nothing: the joined voice track kept
    # beside the film, and the takes and pauses it was joined from.
    voice_track = {
        "path": audio_file.name,
        "segments": [segment.name for segment in voice_segments],
        "pads": [round(pad, 3) for pad in voice_pads],
    }

    # 3. Encode the real 9:16 video. No encoder means no video; the job fails honestly.
    output_mp4 = work_dir / "final_short_9_16.mp4"

    if not ffmpeg_exe:
        reason = (
            "FFmpeg is not installed or not on PATH. Install FFmpeg or set STUDIO_FFMPEG_PATH; "
            "the studio does not substitute a placeholder file for a rendered video."
        )
        _fail_job(reason, reason)
        raise RenderEngineUnavailable(reason)

    from app.agents.services import mark_idle, mark_working  # noqa: PLC0415

    editor_id = mark_working(engine, "VideoEditor", "assemble_video", "montajul filmului")

    # 2. Captions: cards of two to five words, timed to the voice's own word timing where the
    #    take has it and by the characters otherwise, written beside the film as an SRT (the
    #    platform's track, and what quality control reads) and as the ASS script that is
    #    burnt in. The Owner's setting decides the burn; an encoder built without libass, or a
    #    studio whose Inter Bold is missing or altered, cannot, and the manifest says so.
    production["captions"], captions = _write_captions(
        scenes_data,
        work_dir,
        ffmpeg_exe,
        wants_burn=bool(getattr(settings, "captions_burn_in", True)),
    )

    # The sound is mastered once, before the picture: the joined narration is measured,
    # normalised with one linear gain from that measurement (loudnorm falls back to dynamic
    # mode when it cannot, and the Owner is told), brought back to 48 kHz, held under the
    # limiter, padded to the film's length and encoded to AAC — the only lossy encode of the
    # film's sound. The film's own encode copies this track in.
    mastered = work_dir / MASTERED_TRACK_NAME
    try:
        master = encode_master_audio(ffmpeg_exe, audio_file, mastered, duration=total_duration)
    except AudioMasterError as exc:
        _fail_job(f"The narration could not be mastered: {exc}", str(exc))
        raise RenderEngineUnavailable(f"The narration could not be mastered: {exc}") from exc
    loudness = _loudness_record(master)
    production["audio"] = {"loudness": loudness, "voice_track": voice_track}
    if loudness.get("warning"):
        production.setdefault("owner_warnings", []).append(loudness["warning"])

    # One shot per scene — a generated clip trimmed to its span, a composed card, or the
    # still given a slow push — on the 24 fps timeline, joined by hard cuts and by a dissolve
    # only where the script asks. A 10-bit vendor clip is dithered down to 8 bits.
    dither = has_filter(ffmpeg_exe, "zscale")
    production["timeline"] = _timeline_record(
        scenes_data, joins, lengths, holds, motion_clips, card_clips, dither=dither
    )
    if real_stills and frame_files:
        shots: list[Path] = []
        shot_records: list[dict[str, Any]] = []
        for position, scene in enumerate(scenes_data):
            span = lengths[position]
            # A card scene's shot is its composed clip; a LIVE scene's is its generated clip
            # or its still given a push.
            moving = card_clips[position] or motion_clips[position]
            shot_still = frame_files[position] or moving
            if shot_still is None:
                reason = f"Scena {scene['scene_index']} nu are nici imagine, nici card compus."
                _fail_job(reason, reason)
                raise RenderEngineUnavailable(reason)
            target = work_dir / f"shot_{scene['scene_index']:02d}.mp4"
            shot_args = _shot_command(
                ffmpeg_exe,
                shot_still,
                moving,
                span,
                target,
                fps=TIMELINE_FPS,
                hold=holds[position],
                dither=dither,
            )
            shot = subprocess.run(
                shot_args,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            if shot.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
                log = f"shot {scene['scene_index']} failed\n{shot.stdout}\n{shot.stderr}"
                _fail_job(f"Shot {scene['scene_index']} could not be built", log)
                raise RenderEngineUnavailable(
                    f"FFmpeg could not build shot {scene['scene_index']}. See render job log."
                )
            # A shot is counted before it is joined: one frame short of its span would pull
            # every later shot ahead of its words.
            built = _shot_frames(ffmpeg_exe, target)
            wanted_frames = max(1, round(span * TIMELINE_FPS))
            if built is not None and built < wanted_frames:
                reason = (
                    f"Shot {scene['scene_index']} has {built} frames but its span needs "
                    f"{wanted_frames}: the film would drift from its narration. Nothing was "
                    "recorded."
                )
                _fail_job(reason, reason)
                raise RenderEngineUnavailable(reason)
            shots.append(target)
            shot_records.append(_shot_record(scene, target, span, joins[position]))
        # Which shot file each scene is, with its sha256 and its span on the timeline: a
        # one-scene redo rebuilds one of them and rejoins the others exactly as they are.
        production["shots"] = shot_records
        command_args = _dissolve_command(
            ffmpeg_exe,
            shots,
            scenes_data,
            mastered,
            output_mp4,
            audio_filter=None,
            captions=captions,
        )
    else:
        concat_list = work_dir / "inputs.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            # A placeholder film has a frame for every scene, cards included.
            placeholders = [frame for frame in frame_files if frame is not None]
            for frame_path, scene in zip(placeholders, scenes_data, strict=True):
                f.write(f"file '{frame_path.name}'\n")
                f.write(f"duration {float(scene['duration_seconds']):.6f}\n")
            if placeholders:
                f.write(f"file '{placeholders[-1].name}'\n")

        command_args = [
            ffmpeg_exe,
            "-nostdin",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-i",
            str(mastered),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            f"scale=1080:1920,fps={TIMELINE_FPS},"
            + TO_BT709_TV
            + (f",{captions},{TO_BT709_TV}" if captions else ""),
            # The mastered track is already padded to the film's length; it is copied in.
            *_audio_output_args(None),
            "-t",
            f"{total_duration:.3f}",
            *final_video_args(TIMELINE_FPS),
            str(output_mp4),
        ]
    try:
        res = subprocess.run(
            command_args,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        log_output = f"FFmpeg exit={res.returncode}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    except Exception as exc:  # noqa: BLE001
        log_output = f"FFmpeg execution failed: {exc}"
        _fail_job("FFmpeg execution failed", log_output)
        raise RenderEngineUnavailable(f"FFmpeg execution failed: {exc}") from exc

    if res.returncode != 0 or not output_mp4.is_file() or output_mp4.stat().st_size == 0:
        _fail_job(f"FFmpeg exited with code {res.returncode}", log_output)
        raise RenderEngineUnavailable(
            f"FFmpeg failed to encode the video (exit code {res.returncode}). See render job log."
        )
    mark_idle(engine, editor_id, "assemble_video")

    # The output reading is the finished film's, after the AAC encode: that is the file the
    # platform and quality control measure. The master's own reading is kept beside it.
    loudness["output"] = _loudness_readings(measure_loudness(ffmpeg_exe, output_mp4))

    # A film is its picture. The first dissolve render put six seconds of video under
    # forty-six of narration and reported success, because a container's duration is its
    # longest stream. The video stream is measured here, before anything is recorded.
    picture = _video_stream_seconds(ffmpeg_exe, output_mp4)
    if picture is not None and picture + 1.0 < total_duration:
        reason = (
            f"The picture is {picture:.2f}s long but the film is {total_duration:.2f}s: "
            "the encode dropped shots. Nothing was recorded."
        )
        _fail_job(reason, f"{log_output}\n{reason}")
        raise RenderEngineUnavailable(reason)

    # 4. Calculate Provenance Digest
    file_bytes = output_mp4.read_bytes()
    provenance_hash = hashlib.sha256(file_bytes).hexdigest()
    file_size = len(file_bytes)
    finished_at = utc_now()
    output_asset_id = str(uuid4())

    with Session(engine) as session, session.begin():
        # Register MediaAsset
        event = append_event(
            session,
            "media.video_rendered",
            "media_asset",
            output_asset_id,
            1,
            {
                "storyboard_id": storyboard_id,
                "render_engine": "FFMPEG",
                "visual_source": visual_source,
                "voice_source": voice_source,
                "provenance_hash": provenance_hash,
                "file_size_bytes": file_size,
                "duration_seconds": total_duration,
            },
            correlation_id,
        )

        asset = MediaAsset(
            id=output_asset_id,
            asset_type="RENDERED_VIDEO",
            uri_or_path=str(output_mp4),
            file_size_bytes=file_size,
            mime_type="video/mp4",
            width=1080,
            height=1920,
            duration_seconds=round(total_duration, 2),
            provider_name=visual_source,
            remote_job_id=None,
            license_status="PROPRIETARY_STUDIO",
            provenance_hash=provenance_hash,
            created_at=finished_at,
            event_id=event.event_id,
        )
        session.add(asset)

        # Update VideoRenderJob
        job_rec = session.get(VideoRenderJob, render_job_id)
        if job_rec:
            job_rec.output_asset_id = output_asset_id
            job_rec.status = "COMPLETED"
            job_rec.command_args_json = command_args
            job_rec.production_json = production
            job_rec.execution_log = log_output[-8000:]
            job_rec.finished_at = finished_at
            job_rec.event_id = event.event_id

        # Update Storyboard
        sb_rec = session.get(Storyboard, storyboard_id)
        if sb_rec:
            sb_rec.status = "RENDERED"

        session.flush()

    return {
        "job_id": render_job_id,
        "output_asset_id": output_asset_id,
        "file_path": str(output_mp4),
        "provenance_hash": provenance_hash,
        "duration_seconds": total_duration,
        "file_size_bytes": file_size,
        "render_engine": "FFMPEG",
        "visual_source": visual_source,
        "voice_source": voice_source,
        "production": production,
    }


# --------------------------------------------------------------------------- audio repair


class AudioRepairError(RuntimeError):
    """A film's sound could not be remade. The message is the Owner's, in Romanian."""


#: Legacy renders joined the narration to AAC under this name, before the WAV master.
_LEGACY_VOICE_TRACK = "master_audio.m4a"


def video_stream_sha256(ffmpeg_exe: str, path: Path) -> str:
    """The SHA-256 over every packet of a file's first video stream, as ffmpeg reads them.

    The picture's identity independent of its container: a remux that copies the video
    stream gives the same hash, a re-encode never does.
    """
    result = subprocess.run(  # noqa: S603 - argument list, no shell
        [
            ffmpeg_exe,
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-c",
            "copy",
            "-f",
            "streamhash",
            "-hash",
            "sha256",
            "-",
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=600,
        check=False,
    )
    line = (result.stdout or "").strip().splitlines()
    if result.returncode != 0 or not line or "=" not in line[0]:
        raise AudioRepairError(f"Imaginea filmului nu a putut fi citită: {path.name}.")
    return line[0].split("=", 1)[1].strip().lower()


def _repair_voice_source(ffmpeg_exe: str, folder: Path, production: dict[str, Any]) -> Path:
    """The narration a repair remixes from, in the order that loses least.

    1. the joined voice track the render kept (lossless WAV);
    2. the takes it was joined from, joined again with their recorded pauses;
    3. a legacy render's joined AAC track, which is one lossy generation older.
    """
    track = (production.get("audio") or {}).get("voice_track") or {}
    named = folder / str(track.get("path") or VOICE_TRACK_NAME)
    if named.is_file() and named.stat().st_size > 0:
        return named
    segments = [folder / str(name) for name in track.get("segments") or []]
    if segments and all(segment.is_file() for segment in segments):
        pads = [float(pad) for pad in track.get("pads") or []]
        return _concatenate_audio(
            ffmpeg_exe, segments, folder, pads, name=f"voice_rejoined_{uuid4().hex[:8]}.wav"
        )
    legacy = folder / _LEGACY_VOICE_TRACK
    if legacy.is_file() and legacy.stat().st_size > 0:
        return legacy
    raise AudioRepairError(
        "Nu există pistele de voce ale filmului lângă el: sunetul nu poate fi refăcut "
        "fără să fie înregistrată din nou narațiunea."
    )


def remux_with_audio(ffmpeg_exe: str, video: Path, audio: Path, target: Path) -> list[str]:
    """Put a mastered track under a film's picture, copying both streams as they are."""
    command = [
        ffmpeg_exe,
        "-nostdin",
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-map_metadata",
        "0",
        "-movflags",
        "+faststart",
        str(target),
    ]
    result = subprocess.run(  # noqa: S603 - argument list, no shell
        command,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=600,
        check=False,
    )
    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise AudioRepairError(
            f"Filmul nu a putut fi reasamblat cu sunetul nou (cod {result.returncode})."
        )
    return command


def repair_audio(
    engine: Engine,
    asset_id: str,
    correlation_id: str,
    *,
    ffmpeg_path: str | None = None,
) -> dict[str, Any]:
    """Remake a finished film's sound from its voice takes, for no credits at all.

    The narration is remixed from what the render kept beside the film, mastered the way a
    new render masters it (two-pass loudnorm at -2 dBTP, the limiter, one AAC encode) and put
    under the film's picture with ``-c:v copy``: the video packets are the same packets,
    which is checked, not assumed. The film it came from is left untouched; the repaired one
    is a new asset with a render record of its own, so quality control reads its manifest,
    and that manifest says what it is a remaster of. Nothing here calls a provider.
    """
    ffmpeg_exe = find_ffmpeg(ffmpeg_path)
    if not ffmpeg_exe:
        raise AudioRepairError("FFmpeg nu este instalat: sunetul nu poate fi refăcut.")

    with Session(engine) as session:
        asset = session.get(MediaAsset, asset_id)
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == asset_id)
        )
        if asset is None or job is None:
            raise AudioRepairError("Filmul cerut nu există sau nu are o randare înregistrată.")
        source = Path(asset.uri_or_path)
        production = copy.deepcopy(job.production_json or {})
        storyboard_id = job.storyboard_id
        width, height = asset.width, asset.height
        provider_name = asset.provider_name
        license_status = asset.license_status
    if not source.is_file():
        raise AudioRepairError(f"Fișierul filmului lipsește: {source.name}.")

    folder = source.parent
    seconds = _video_stream_seconds(ffmpeg_exe, source)
    if seconds is None:
        raise AudioRepairError("Durata imaginii filmului nu a putut fi măsurată.")
    voice = _repair_voice_source(ffmpeg_exe, folder, production)
    stamp = uuid4().hex[:8]
    mastered = folder / f"master_audio_repair_{stamp}.m4a"
    try:
        master = encode_master_audio(ffmpeg_exe, voice, mastered, duration=seconds)
    except AudioMasterError as exc:
        raise AudioRepairError(f"Narațiunea nu a putut fi masterizată: {exc}") from exc

    target = folder / f"{source.stem}_audio_{stamp}.mp4"
    command = remux_with_audio(ffmpeg_exe, source, mastered, target)
    picture = video_stream_sha256(ffmpeg_exe, source)
    if video_stream_sha256(ffmpeg_exe, target) != picture:
        target.unlink(missing_ok=True)
        raise AudioRepairError(
            "Imaginea s-a schimbat la reasamblare; filmul reparat a fost aruncat."
        )

    loudness = _loudness_record(master)
    loudness["output"] = _loudness_readings(measure_loudness(ffmpeg_exe, target))
    audio_record = dict(production.get("audio") or {})
    audio_record["loudness"] = loudness
    audio_record["repaired_from"] = voice.name
    production["audio"] = audio_record
    warnings = [w for w in production.get("owner_warnings") or [] if w != loudness["warning"]]
    if loudness["warning"]:
        warnings.append(loudness["warning"])
    production["owner_warnings"] = warnings
    production["remaster"] = {
        "kind": "audio",
        "of_asset": asset_id,
        "of_job": job.id,
        "voice_source": voice.name,
        "credits": 0,
        "video_stream_sha256": picture,
    }

    file_bytes = target.read_bytes()
    provenance_hash = hashlib.sha256(file_bytes).hexdigest()
    finished_at = utc_now()
    output_asset_id = str(uuid4())
    render_job_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session,
            "media.audio_repaired",
            "media_asset",
            output_asset_id,
            1,
            {
                "storyboard_id": storyboard_id,
                "source_asset_id": asset_id,
                "provenance_hash": provenance_hash,
                "file_size_bytes": len(file_bytes),
                "video_stream_sha256": picture,
                "normalization_type": loudness["normalization_type"],
                "credits": 0,
            },
            correlation_id,
        )
        session.add(
            MediaAsset(
                id=output_asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(target),
                file_size_bytes=len(file_bytes),
                mime_type="video/mp4",
                width=width,
                height=height,
                duration_seconds=round(seconds, 2),
                provider_name=provider_name,
                remote_job_id=None,
                license_status=license_status,
                provenance_hash=provenance_hash,
                created_at=finished_at,
                event_id=event.event_id,
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=render_job_id,
                storyboard_id=storyboard_id,
                output_asset_id=output_asset_id,
                status="COMPLETED",
                render_engine="FFMPEG",
                command_args_json=command,
                production_json=production,
                execution_log=None,
                started_at=finished_at,
                finished_at=finished_at,
                event_id=event.event_id,
            )
        )
    return {
        "job_id": render_job_id,
        "output_asset_id": output_asset_id,
        "source_asset_id": asset_id,
        "file_path": str(target),
        "provenance_hash": provenance_hash,
        "video_stream_sha256": picture,
        "loudness": loudness,
        "credits": 0,
    }


# ------------------------------------------------------------------------- the motion step
#
# The last, dearest stair of the money staircase. The Nepal film (2026-09-26) bought every
# clip twice, on five models, with no price shown and no question asked, and the books kept
# 0.74 USD of the 966 credits the account lost. Here a shot is bought only:
#
# - from an APPROVED still (the stills step) and on the model the sheet gave its scene: the
#   cheapest model that covers what the scene needs (production_policy.plan_scene_models,
#   the Owner's decision of 2026-09-27), or his own choice on the sheet;
# - under the Owner's yes for its own step, bound to the plan he was shown (plan_hash) and to
#   a cap: first ONE hero test shot (media.test_shot), kept in the film; the rest
#   (media.motion_purchase) only once he has looked at the hero and approved its take;
# - within the cap, checked before every POST (STOPPED_AT_CAP), and within the balance, read
#   before every shot (a free GET): the step halts below the shot's price.
#
# A failure concerns its scene only and never buys another model in the same step: SAFETY
# sends the scene's picture back to the stills gate (the sheet shows the next-cheapest
# capable model for the Owner to choose), a refused request (400) waits for the Owner and a
# second one in a row stops the step, an account problem stops it, and a transient or
# technical failure is tried once more on the same model with the same seed. The balance
# before and after the step is what it cost, written on the takes and as MEASURED prices.

TEST_SHOT_STEP = "test_shot"
MOTION_STEP = "motion"
#: The Policy Kernel's action for each step of the motion staircase.
MOTION_STEP_ACTIONS: dict[str, str] = {
    TEST_SHOT_STEP: "media.test_shot",
    MOTION_STEP: "media.motion_purchase",
}
#: The take kind each step writes.
MOTION_STEP_TAKE_KINDS: dict[str, str] = {TEST_SHOT_STEP: "test_shot", MOTION_STEP: "motion"}
#: The account must hold this much more than a paid step's cap before it is asked or bought.
PAID_STEP_BALANCE_MARGIN = 1.15
#: Failures tried once more on the same model, the same request and the same seed.
MOTION_RETRY_KINDS: tuple[str, ...] = ("TRANSIENT", "BAD_OUTPUT", "TECHNICAL")
#: The film's resolution unless the settings name another.
MOTION_STEP_RESOLUTION = "1080p"
#: Runway's seed range (0 .. 2^32 - 1).
SEED_RANGE = 4_294_967_295
#: Who may approve or reject a take: the Owner, on the sheet. Nobody else.
TAKE_DECIDER = "owner"
TAKE_DECISIONS: tuple[str, ...] = ("APPROVED", "REJECTED")


class MotionStepRefused(RuntimeError):
    """The motion step bought nothing. ``status`` says why; ``reason_ro`` is the Owner's.

    NEEDS_APPROVAL is a 202 for the route (his question waits, with ``approval_id``); every
    other status (STALE_PLAN, NEEDS_SHOT_PLAN, LINT_BLOCKED, HERO_FIRST, HERO_NOT_APPROVED,
    LOW_BALANCE, NO_ENCODER, REFUSED_BY_OWNER, BLOCKED_*) is a 409.
    """

    def __init__(
        self,
        status: str,
        reason_ro: str,
        *,
        approval_id: str | None = None,
        plan: dict[str, Any] | None = None,
        findings: list[Any] | None = None,
    ) -> None:
        super().__init__(reason_ro)
        self.status = status
        self.reason_ro = reason_ro
        self.approval_id = approval_id
        self.plan = plan
        self.findings = list(findings or [])

    @property
    def http_status(self) -> int:
        return 202 if self.status == "NEEDS_APPROVAL" else 409


def film_seed(storyboard_id: str) -> int:
    """The film's one seed, the same on every shot and every retry of the film."""
    digest = hashlib.sha256(f"film-seed:{storyboard_id}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % SEED_RANGE


def motion_seconds(scene: dict[str, Any]) -> float:
    """How long a scene's shot must be: its planned span plus the transition it overlaps.

    The vendor bills whole seconds, rounded UP to a length its contract accepts
    (cost_plan.billable_seconds), and the assembler trims: a shot is never stretched.
    """
    return round(float(scene.get("duration_seconds") or 0.0) + TRANSITION_SECONDS, 3)


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _capabilities(
    engine: Engine,
    capabilities: list[ModelCapability] | tuple[ModelCapability, ...] | None,
    integration_id: str | None,
) -> list[ModelCapability]:
    if capabilities is not None:
        return list(capabilities)
    if not integration_id:
        raise ValueError("the motion plan needs the models' capabilities or the connection")
    from app.media.production_policy import scene_model_capabilities  # noqa: PLC0415

    with Session(engine) as session:
        return scene_model_capabilities(session, integration_id)


def _bought_shots(
    engine: Engine, storyboard_id: str, scenes: list[dict[str, Any]], redo: int | None = None
) -> tuple[dict[int, SceneTake], dict[int, SceneTake], dict[int, dict[str, Any]], dict[int, str]]:
    """Per LIVE scene: its APPROVED still, its usable shot, its shot identity, or why it waits.

    ``redo`` names the scene whose shot the Owner is having redone: its existing shot is not
    counted as bought, so the scene is planned (and priced) again on its own."""
    stills: dict[int, SceneTake] = {}
    shots: dict[int, SceneTake] = {}
    fields_of: dict[int, dict[str, Any]] = {}
    holds: dict[int, str] = {}
    with Session(engine) as session:
        for scene in scenes:
            index = int(scene["scene_index"])
            if is_composed(scene):
                continue
            still = usable_take(
                session,
                storyboard_id,
                index,
                "still",
                [still_fields(str(scene["visual_prompt"] or ""), None)],
                statuses=("APPROVED",),
            )
            if still is None:
                holds[index] = (
                    f"Scena {index} nu are o imagine aprobată pentru promptul de acum; "
                    "mișcarea pornește doar dintr-o imagine aprobată."
                )
                continue
            # A still adopted with a failed local check (LOCAL.*) is approved only so the
            # zero-credit rehearsal can show it; a paid shot never starts from it.
            if str(still.failure_code or "").startswith("LOCAL."):
                holds[index] = (
                    f"Scena {index}: imaginea ei a fost păstrată doar pentru repetiție "
                    f"({still.failure_code}); mișcarea plătită pornește doar dintr-o imagine "
                    "nouă, aprobată."
                )
                continue
            session.expunge(still)
            stills[index] = still
            fields = motion_fields(scene, still.sha256, from_prompt=False)
            fields_of[index] = fields
            if index == redo:
                continue
            shot = _shot_take(session, storyboard_id, index, fields, motion_seconds(scene))
            if shot is not None:
                session.expunge(shot)
                shots[index] = shot
    return stills, shots, fields_of, holds


def _motion_state(
    engine: Engine,
    storyboard_id: str,
    *,
    capabilities: list[ModelCapability],
    allowed: Any = None,
    overrides: dict[int, str | None] | None = None,
    resolution: str = MOTION_STEP_RESOLUTION,
    table: PriceTable | None = None,
    redo: int | None = None,
) -> dict[str, Any]:
    """Everything the plan and the step read: scenes, stills, shots already bought, the
    per-scene model choice, the lint and the two steps' purchases. 0 credits, no network.

    With ``redo`` (a scene the Owner is having redone) that scene's shot is planned again and
    a third step, ``scene_redo``, buys it alone."""
    from app.media.prompt_agent import motion_prompt_for  # noqa: PLC0415

    prices = table or load_price_table()
    _title, scenes = _storyboard_scenes(engine, storyboard_id)
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        bible = dict(board.visual_bible_json or {}) if board is not None else {}
    stills, shots, fields_of, holds = _bought_shots(engine, storyboard_id, scenes, redo)
    needs = [
        need_from_scene({**scene, "duration_seconds": motion_seconds(scene)}, len(scenes))
        for scene in scenes
    ]
    policy = plan_scene_models(
        needs,
        capabilities,
        allowed=allowed,
        overrides=overrides,
        keep={index: str(take.model_id) for index, take in shots.items()},
        bought=list(shots),
        hold=holds,
        stills_paid=True,
        resolution=resolution,
        table=prices,
    )
    chosen = {int(entry["scene_index"]): entry for entry in policy["scenes"]}

    view: list[dict[str, Any]] = []
    lint_scenes: list[LintScene] = []
    for scene in scenes:
        index = int(scene["scene_index"])
        entry = chosen.get(index, {})
        kind = scene_kind_of(scene)
        raw = scene.get("prompt_json")
        package: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
        shot = shots.get(index)
        still = stills.get(index)
        if kind != LIVE_KIND:
            status = "COMPOSED"
        elif shot is not None:
            status = "BOUGHT"
        elif still is None:
            status = "NEEDS_STILL"
        else:
            status = str(entry.get("status") or "NEEDS_OWNER")
        model_id = str(shot.model_id) if shot is not None else entry.get("model_id")
        motion_text = ""
        if kind == LIVE_KIND and model_id:
            motion_text, _negative = motion_prompt_for(package, model_id, None)
        still_text = ""
        if kind == LIVE_KIND:
            still_text = str(package.get("still_prompt") or scene.get("visual_prompt") or "")
        lint_scenes.append(
            LintScene(
                scene=index,
                kind=kind,
                still_prompt=still_text,
                motion_prompt=motion_text,
                model_id=model_id,
            )
        )
        view.append(
            {
                "scene_index": index,
                "kind": kind,
                "tier": entry.get("tier"),
                "status": status,
                "model_id": model_id,
                "resolution": entry.get("resolution"),
                "seconds": motion_seconds(scene) if kind == LIVE_KIND else 0.0,
                "billed_seconds": int(entry.get("billed_seconds") or 0),
                "credits": int(entry.get("credits") or 0),
                "usd_micros": int(entry.get("usd_micros") or 0),
                "price_source": entry.get("price_source"),
                "decided_by": entry.get("decided_by"),
                "reason_ro": holds.get(index) or entry.get("reason_ro") or "",
                "cheaper": entry.get("cheaper"),
                "better": entry.get("better"),
                "still_take_id": still.id if still is not None else None,
                "still_sha256": still.sha256 if still is not None else None,
                "take_id": shot.id if shot is not None else None,
                "take_kind": shot.kind if shot is not None else None,
                "take_status": shot.status if shot is not None else None,
                "motion_prompt": motion_text,
            }
        )
    findings = lint_film(lint_scenes, bible=bible)
    raw_hero = policy.get("hero_scene")
    hero: int | None = int(raw_hero) if raw_hero is not None else None
    by_index = {item["scene_index"]: item for item in view}

    def step(to_buy: list[int]) -> dict[str, Any]:
        each = [by_index[index]["credits"] for index in to_buy]
        cost = sum(each)
        cap = cost + max(each, default=0)
        return {
            "to_buy": to_buy,
            "cost_credits": cost,
            "cap_credits": cap,
            "cost_usd": round(cost * prices.credit_usd, 6),
            "cap_usd": round(cap * prices.credit_usd, 6),
        }

    planned = [item["scene_index"] for item in view if item["status"] == "PLANNED"]
    steps = {
        TEST_SHOT_STEP: step([hero] if hero is not None and hero in planned else []),
        MOTION_STEP: step([index for index in planned if index != hero]),
    }
    if redo is not None:
        steps[REDO_STEP] = step([redo] if redo in planned else [])
    hashed: dict[str, Any] = {
        "storyboard_id": storyboard_id,
        "resolution": resolution,
        "seed": film_seed(storyboard_id),
        "hero_scene": hero,
        "scenes": [
            {
                "scene_index": item["scene_index"],
                "kind": item["kind"],
                "status": item["status"],
                "model_id": item["model_id"],
                "billed_seconds": item["billed_seconds"],
                "credits": item["credits"],
                "decided_by": item["decided_by"],
                "still_sha256": item["still_sha256"],
                "motion": (fields_of.get(item["scene_index"]) or {}).get("package"),
                "motion_prompt": item["motion_prompt"],
                "take_id": item["take_id"],
                "take_status": item["take_status"],
            }
            for item in view
        ],
        "steps": {
            name: {"to_buy": s["to_buy"], "cost": s["cost_credits"], "cap": s["cap_credits"]}
            for name, s in steps.items()
        },
    }
    if redo is not None:
        hashed["redo"] = redo
    plan = {
        **hashed,
        "scenes": view,
        "steps": steps,
        "credit_usd": prices.credit_usd,
        "price_source": policy.get("price_source"),
        "saved_credits": policy.get("saved_credits"),
        "premium_credits": policy.get("premium_credits"),
        "summary_ro": policy.get("summary_ro"),
        "lint": [finding.as_dict() for finding in findings],
        "lint_blocked": has_block(findings),
        "lint_summary_ro": summary_ro(findings) if findings else "",
        "plan_hash": hashlib.sha256(_canonical_json(hashed).encode("utf-8")).hexdigest(),
    }
    return {
        "plan": plan,
        "policy": policy,
        "needs": needs,
        "scenes": scenes,
        "stills": stills,
        "fields": fields_of,
        "findings": findings,
        "prices": prices,
    }


def motion_plan(
    engine: Engine,
    storyboard_id: str,
    *,
    capabilities: list[ModelCapability] | tuple[ModelCapability, ...] | None = None,
    integration_id: str | None = None,
    allowed: Any = None,
    overrides: dict[int, str | None] | None = None,
    resolution: str = MOTION_STEP_RESOLUTION,
    table: PriceTable | None = None,
) -> dict[str, Any]:
    """The motion staircase as the Owner is shown it, with its plan_hash. 0 credits.

    Per scene: its kind, its approved still (sha256), the model chosen for it and why, the
    billed seconds, the credits and the cheaper and better alternatives; the scenes already
    bought (the hero test shot among them, with its take's status); the film's one seed; the
    lint of the prompts as they will be sent; and the two steps, each with what it buys, its
    cost and its cap (its cost plus one redo of its dearest shot). The hash covers all of it:
    a changed prompt, model, still, price or the Owner's look at the hero is a new plan, and a
    yes for the old one buys nothing.
    """
    caps = _capabilities(engine, capabilities, integration_id)
    state = _motion_state(
        engine,
        storyboard_id,
        capabilities=caps,
        allowed=allowed,
        overrides=overrides,
        resolution=resolution,
        table=table,
    )
    plan: dict[str, Any] = state["plan"]
    return plan


def _account_balance(source: Any) -> tuple[bool, float | None, str | None]:
    """(read, balance, problem) from anything with an async ``credit_balance()``."""
    reader = getattr(source, "credit_balance", None)
    if not callable(reader):
        return False, None, None
    try:
        balance = asyncio.run(reader())
    except Exception as exc:  # noqa: BLE001 - any failure to read stops the purchase
        return True, None, f"soldul furnizorului nu a putut fi citit ({str(exc)[:120]})"
    if isinstance(balance, bool) or not isinstance(balance, int | float):
        return True, None, None
    return True, float(balance), None


def _shot_failure(exc: BaseException, previous: str | None) -> FailureVerdict:
    """A failed shot sorted by kind. With no vendor code and no HTTP status (a task that failed
    without a reason, a clip that did not arrive) it is TECHNICAL: tried once more."""
    if isinstance(exc, MediaProviderError) and (
        getattr(exc, "code", None) or getattr(exc, "http_status", None) is not None
    ):
        verdict: FailureVerdict = classify_vendor_failure(exc, previous)
        return verdict
    return FailureVerdict(
        kind="TECHNICAL",
        action="retry_same",
        reason_ro=(
            "Clipul nu a ajuns (eroare tehnică, fără motiv de la furnizor); se reîncearcă o "
            "singură dată pe același model."
        ),
        blame_model=False,
        detail=failure_detail_of(exc),
    )


def _send_still_back(
    engine: Engine,
    still_take_id: str | None,
    verdict: FailureVerdict,
    model_id: str,
    correlation_id: str,
) -> None:
    """A safety refusal of the shot sends the scene's picture back to the stills gate."""
    if not still_take_id:
        return
    with Session(engine) as session, session.begin():
        row = session.get(SceneTake, still_take_id)
        if row is None:
            return
        row.status = "REJECTED"
        row.failure_code = f"MOTION.{verdict.code or 'SAFETY'}"[:100]
        row.failure_detail = (
            f"{model_id} a refuzat mișcarea din motive de siguranță; imaginea se întoarce la "
            "poarta imaginilor și nu se mai trimite nimănui așa cum este."
        )[:TAKE_DETAIL_MAX]
        row.updated_at = utc_now()
        append_event(
            session,
            "media.still_sent_back",
            "scene_take",
            row.id,
            1,
            {
                "storyboard_id": row.storyboard_id,
                "scene_number": row.scene_number,
                "failure_kind": verdict.kind,
                "failure_code": verdict.code,
                "model_id": model_id,
            },
            correlation_id,
        )


def _suggest_move(
    state: dict[str, Any],
    scene_index: int,
    verdict: FailureVerdict,
    bought: list[int],
    *,
    allowed: Any,
    capabilities: list[ModelCapability],
    resolution: str,
) -> dict[str, Any] | None:
    """The failed scene's next-cheapest capable model, for the Owner to choose on the sheet.

    Only that scene changes; nothing is bought on the suggestion in this step (the yes was
    given for the model the sheet named).
    """
    try:
        replanned = replan_after_failure(
            state["policy"],
            state["needs"],
            capabilities,
            scene_index=scene_index,
            failure=verdict,
            bought=bought,
            allowed=allowed,
            resolution=resolution,
            table=state["prices"],
        )
    except (ValueError, KeyError) as exc:
        logger.info("motion_replan_unavailable", extra={"reason": str(exc)[:160]})
        return None
    moved = next(
        (s for s in replanned.get("scenes", []) if int(s["scene_index"]) == scene_index), None
    )
    if moved is None:
        return None
    suggested = moved.get("suggested") or {}
    model_id = moved.get("model_id") or suggested.get("model_id")
    credits = moved.get("credits") or suggested.get("credits") or 0
    return {
        "model_id": model_id,
        "credits": int(credits),
        "status": moved.get("status"),
        "reason_ro": moved.get("reason_ro") or "",
    }


def decide_take(
    engine: Engine,
    take_id: str,
    decision: str,
    *,
    decided_by: str,
    note: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """The Owner's look at a bought take: APPROVED or REJECTED. Only he decides.

    The hero test shot is approved this way before the rest of the motion may be bought; a
    rejected take is never used in a film again. Raises PermissionError for anyone else.
    """
    if decided_by != TAKE_DECIDER:
        raise PermissionError("Doar Proprietarul aprobă sau respinge o înregistrare plătită.")
    if decision not in TAKE_DECISIONS:
        raise ValueError(f"Decizie necunoscută: {decision}")
    with Session(engine) as session, session.begin():
        row = session.get(SceneTake, take_id)
        if row is None:
            raise ValueError("Înregistrarea nu există.")
        if row.status not in ("PAID", "APPROVED", "REJECTED"):
            raise ValueError(f"O înregistrare {row.status} nu se aprobă și nu se respinge.")
        if decision == "APPROVED" and (not row.path or not Path(row.path).is_file()):
            raise ValueError("Înregistrarea nu are fișierul pe disc; nu poate fi aprobată.")
        row.status = decision
        row.approved_by = TAKE_DECIDER if decision == "APPROVED" else None
        if decision == "REJECTED":
            row.failure_code = "OWNER.REJECTED"
            row.failure_detail = (note or "Respinsă de Proprietar.")[:TAKE_DETAIL_MAX]
        row.updated_at = utc_now()
        append_event(
            session,
            "media.scene_take_decided",
            "scene_take",
            row.id,
            1,
            {
                "storyboard_id": row.storyboard_id,
                "scene_number": row.scene_number,
                "kind": row.kind,
                "decision": decision,
                "decided_by": TAKE_DECIDER,
                "note": note,
            },
            correlation_id or str(uuid4()),
        )
        return {"take_id": row.id, "status": row.status, "kind": row.kind}


def _storyboard_event(
    engine: Engine, event_type: str, storyboard_id: str, payload: dict, correlation_id: str
) -> None:
    with Session(engine) as session, session.begin():
        append_event(session, event_type, "storyboard", storyboard_id, 1, payload, correlation_id)


def _refuse_before_buying(
    engine: Engine,
    state: dict[str, Any],
    step: str,
    plan_hash: str,
    *,
    environment: str,
    plan_hash_of: Callable[[Engine, str], str] | None,
    storyboard_id: str,
) -> None:
    """The refusals that come before anything is asked or bought, in order."""
    plan = state["plan"]
    current = plan_hash_of(engine, storyboard_id) if plan_hash_of else plan["plan_hash"]
    if not plan_hash or plan_hash != current:
        raise MotionStepRefused(
            "STALE_PLAN",
            "Foaia de filmare s-a schimbat de când a fost aprobată (sau aprobarea numește alt "
            "plan): nu se cumpără nicio mișcare. Deschideți foaia din nou și aprobați planul "
            "de acum.",
            plan=plan,
        )
    if environment == "PRODUCTION":
        unwritten = [
            int(scene["scene_index"])
            for scene in state["scenes"]
            if not is_composed(scene) and (scene.get("prompt_json") or {}).get("source") != "model"
        ]
        if unwritten:
            raise MotionStepRefused(
                "NEEDS_SHOT_PLAN",
                "Scenele "
                + ", ".join(map(str, unwritten))
                + " nu au promptul scris de model din planul de cadre; nu se cumpără mișcare "
                "din prompturi-șablon.",
                plan=plan,
            )
    if plan["lint_blocked"]:
        blocks = [f for f in state["findings"] if f.severity == "BLOCK"]
        raise MotionStepRefused(
            "LINT_BLOCKED",
            plan["lint_summary_ro"] + " " + " ".join(f.message_ro for f in blocks[1:4]),
            plan=plan,
            findings=blocks,
        )
    hero = plan["hero_scene"]
    if step != MOTION_STEP or hero is None:
        return
    hero_view = next(item for item in plan["scenes"] if item["scene_index"] == hero)
    if hero_view["status"] != "BOUGHT":
        raise MotionStepRefused(
            "HERO_FIRST",
            f"Întâi cadrul de probă (scena {hero}): restul mișcării se cumpără abia după ce "
            "Proprietarul l-a văzut și l-a aprobat.",
            plan=plan,
        )
    if hero_view["take_status"] != "APPROVED":
        raise MotionStepRefused(
            "HERO_NOT_APPROVED",
            f"Cadrul de probă (scena {hero}) așteaptă privirea Proprietarului: restul mișcării "
            "nu se cumpără până nu este aprobat pe foaia de filmare.",
            plan=plan,
        )


def run_motion_step(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    *,
    step: str,
    plan_hash: str,
    adapter_for_model: Callable[[str], Any],
    capabilities: list[ModelCapability] | tuple[ModelCapability, ...] | None = None,
    account: Any = None,
    cap_credits: int | None = None,
    allowed: Any = None,
    overrides: dict[int, str | None] | None = None,
    resolution: str | None = None,
    settings: Any | None = None,
    environment: str | None = None,
    plan_hash_of: Callable[[Engine, str], str] | None = None,
    integration_id: str | None = None,
    table: PriceTable | None = None,
    ffmpeg_path: str | None = None,
    storage_root: Path | None = None,
    requester: str = "video_editor",
    redo_scene: int | None = None,
    redo_note: str | None = None,
) -> dict[str, Any]:
    """One step of the motion staircase (``test_shot`` or ``motion``), bought only under the
    Owner's yes for this plan and this cap.

    ``step='scene_redo'`` with ``redo_scene`` buys that one scene's shot again under
    ``media.scene_redo`` (`redo_scene`, the per-scene redo): the scene's old shot takes are
    retired (REJECTED, ``REDO.OWNER``) in the same transaction that spends the yes.

    ``plan_hash`` is the hash of the plan he was shown (`motion_plan`; the shooting sheet may
    pass ``plan_hash_of`` so its own hash is the one his yes is bound to). ``cap_credits`` is
    the cap he approved (default: the step's cost plus one redo of its dearest shot).
    ``adapter_for_model`` gives the adapter of a model id; ``account`` reads the balance
    (default: the first adapter). Raises `MotionStepRefused` when nothing may be bought;
    otherwise returns what was bought, per scene, and what it cost, quoted and measured.
    """
    from app.economy.credits import record_measured_prices  # noqa: PLC0415
    from app.runbook.services import stop_requested  # noqa: PLC0415 - runbook imports media
    from app.services import may_act, studio_environment  # noqa: PLC0415

    actions = {**MOTION_STEP_ACTIONS, REDO_STEP: REDO_ACTION}
    if step not in actions:
        raise ValueError(f"unknown motion step: {step}")
    if (step == REDO_STEP) != (redo_scene is not None):
        raise ValueError("a scene redo names its scene, and only a scene redo does")
    resolution = resolution or str(
        getattr(settings, "motion_resolution", None) or MOTION_STEP_RESOLUTION
    )
    margin = float(getattr(settings, "paid_step_balance_margin", None) or PAID_STEP_BALANCE_MARGIN)
    caps = _capabilities(engine, capabilities, integration_id)
    state = _motion_state(
        engine,
        storyboard_id,
        capabilities=caps,
        allowed=allowed,
        overrides=overrides,
        resolution=resolution,
        table=table,
        redo=redo_scene,
    )
    plan = state["plan"]
    prices: PriceTable = state["prices"]
    _refuse_before_buying(
        engine,
        state,
        step,
        plan_hash,
        environment=environment or studio_environment(engine),
        plan_hash_of=plan_hash_of,
        storyboard_id=storyboard_id,
    )
    view = {item["scene_index"]: item for item in plan["scenes"]}
    step_plan = plan["steps"][step]
    to_buy = [int(index) for index in step_plan["to_buy"]]
    cap = int(cap_credits) if cap_credits is not None else int(step_plan["cap_credits"])
    take_kind = MOTION_STEP_TAKE_KINDS.get(step, "motion")
    source = account
    before: float | None = None
    read = False
    ffmpeg_exe: str | None = None
    work_dir = (storage_root or DEFAULT_STORAGE_ROOT) / storyboard_id / "motion"

    if to_buy:
        ffmpeg_exe = resolve_ffmpeg_path(ffmpeg_path)
        if ffmpeg_exe is None:
            raise MotionStepRefused(
                "NO_ENCODER",
                "FFmpeg nu este instalat: imaginea aprobată nu poate fi pregătită ca prim cadru.",
                plan=plan,
            )
        if source is None:
            source = adapter_for_model(str(view[to_buy[0]]["model_id"]))
        read, before, problem = _account_balance(source)
        if problem is not None:
            raise MotionStepRefused("LOW_BALANCE", f"Nu se cumpără mișcare: {problem}.", plan=plan)
        if before is not None and before < cap * margin:
            raise MotionStepRefused(
                "LOW_BALANCE",
                f"Soldul furnizorului ({before:.0f} credite) este sub plafonul pasului "
                f"({cap} credite) plus marja de {round((margin - 1) * 100)}%: alimentați "
                "contul înainte de aprobare.",
                plan=plan,
            )
        with Session(engine) as session, session.begin():
            verdict = may_act(
                session,
                actions[step],
                requester=requester,
                subject=storyboard_id,
                evidence=(
                    f"{len(to_buy)} cadre (scenele {', '.join(map(str, to_buy))}), "
                    f"{step_plan['cost_credits']} credite, plafon {cap}"
                ),
                cost_usd=step_plan["cost_usd"],
                context={"plan_hash": plan_hash, "cap_credits": cap},
            )
            if verdict["allowed"] and redo_scene is not None:
                # The yes is spent and the old shot retired together: the redo replaces it.
                _retire_takes(
                    session,
                    _scene_shot_takes(session, storyboard_id, redo_scene),
                    REDO_FAILURE_CODE,
                    redo_note or "Proprietarul a cerut refacerea mișcării acestei scene.",
                    correlation_id,
                )
        if not verdict["allowed"]:
            raise MotionStepRefused(
                str(verdict["status"]),
                str(verdict["reason"]),
                approval_id=verdict.get("approval_id"),
                plan=plan,
            )
        work_dir.mkdir(parents=True, exist_ok=True)

    scene_dicts = {int(scene["scene_index"]): scene for scene in state["scenes"]}
    seed = int(plan["seed"])
    results: list[dict[str, Any]] = []
    charged: list[dict[str, Any]] = []
    bought_now: list[int] = []
    stopped: str | None = None
    previous_kind: str | None = None
    committed = 0.0

    for index, item in sorted(view.items()):
        entry: dict[str, Any] = {
            "scene_index": index,
            "scene_kind": item["kind"],
            "model_id": item["model_id"],
        }
        results.append(entry)
        if index not in to_buy:
            if item["status"] == "COMPOSED":
                entry.update(status="composed", provenance="composed", credits=0)
            elif item["status"] == "BOUGHT":
                entry.update(
                    status=item["take_status"],
                    reused=True,
                    take_id=item["take_id"],
                    take_kind=item["take_kind"],
                    credits=0,
                )
            elif item["status"] == "PLANNED":
                entry.update(status="OTHER_STEP")
            else:
                entry.update(status=item["status"], reason=item["reason_ro"])
            continue
        if stopped is not None:
            entry.update(status="NOT_BOUGHT", reason=stopped)
            continue
        model_id = str(item["model_id"])
        price = int(item["credits"])
        seconds = int(item["billed_seconds"])
        adapter = adapter_for_model(model_id)
        if adapter is None:
            entry.update(
                status="NEEDS_OWNER",
                reason=f"Modelul {model_id} nu este conectat; decide Proprietarul pe foaia "
                "de filmare.",
            )
            continue
        still_take: SceneTake = state["stills"][index]
        identity = take_hash(state["fields"][index], model_id)
        attempts = 0
        outcome: dict[str, Any] | None = None
        while outcome is None:
            if stop_requested(engine):
                stopped = "Proprietarul a oprit autonomia; nu se mai cumpără mișcare."
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            if committed + price > cap:
                stopped = (
                    f"STOPPED_AT_CAP: cadrul scenei {index} ({price} credite) ar depăși "
                    f"plafonul aprobat de {cap} credite (deja {committed:.0f})."
                )
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            _read, balance, problem = _account_balance(source)
            if problem is not None or (balance is not None and balance < price):
                stopped = (
                    f"Nu se mai cumpără mișcare: {problem}."
                    if problem
                    else f"Soldul furnizorului ({balance:.0f} credite) nu mai acoperă cadrul "
                    f"scenei {index} ({price} credite)."
                )
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            attempts += 1
            posted: list[str] = []
            try:
                with _at_work(engine, "VideoEditor", "generate_motion", f"mișcarea scenei {index}"):
                    clip_bytes, _raw = _generate_motion(
                        adapter,
                        scene_dicts[index],
                        Path(str(still_take.path)),
                        float(seconds),
                        str(ffmpeg_exe),
                        seed=seed,
                        on_submitted=posted.append,
                    )
            except (MediaProviderError, MediaProviderNotConfigured, ValueError, OSError) as exc:
                failure = _shot_failure(exc, previous_kind)
                previous_kind = failure.kind
                spend: float | None = None
                if posted:
                    # A task the vendor accepted may be charged like a success.
                    spend = max(float(price), float(_quoted_credits(adapter) or 0.0))
                    committed += spend
                code = failure_code_of(exc) or failure.kind
                detail = failure_detail_of(exc)
                take_id = record_take(
                    engine,
                    storyboard_id=storyboard_id,
                    scene_number=index,
                    kind=take_kind,
                    prompt_hash=identity,
                    model_id=model_id,
                    resolution=MOTION_RESOLUTION,
                    status="REFUSED",
                    correlation_id=correlation_id,
                    seconds=float(seconds),
                    seed=seed,
                    credits_quoted=spend,
                    failure_code=code,
                    failure_detail=detail,
                )
                if spend is not None:
                    charged.append(
                        {"take_id": take_id, "model": model_id, "seconds": seconds, "spend": spend}
                    )
                if failure.kind in MOTION_RETRY_KINDS and attempts < 2:
                    continue
                entry.update(
                    failure_kind=failure.kind,
                    failure_code=code,
                    failure_detail=detail,
                    take_id=take_id,
                )
                if failure.kind in ("SAFETY", "CONTRACT"):
                    bought = [i for i, v in view.items() if v["status"] == "BOUGHT"] + bought_now
                    entry["suggested"] = _suggest_move(
                        state,
                        index,
                        failure,
                        bought,
                        allowed=allowed,
                        capabilities=caps,
                        resolution=resolution,
                    )
                if failure.kind == "SAFETY":
                    _send_still_back(engine, still_take.id, failure, model_id, correlation_id)
                    outcome = {
                        "status": "NEEDS_STILL",
                        "reason": f"Scena {index}: {model_id} a refuzat mișcarea din motive de "
                        "siguranță; aceeași imagine nu se mai trimite. Imaginea se întoarce la "
                        "poarta imaginilor; modelul următor se alege pe foaia de filmare.",
                    }
                    break
                if failure.stop_step:
                    stopped = failure.reason_ro + (f" Furnizorul: «{detail}»." if detail else "")
                if failure.kind in MOTION_RETRY_KINDS:
                    reason = (
                        f"{model_id} a eșuat de două ori pe această scenă ({failure.kind}); "
                        "decide Proprietarul."
                    )
                else:
                    reason = (
                        f"{failure.reason_ro} Nu se încearcă alt model în acest pas; decide "
                        "Proprietarul pe foaia de filmare."
                    )
                outcome = {"status": "NEEDS_OWNER", "reason": f"Scena {index}: {reason}"}
                break
            previous_kind = None
            spend = max(float(price), float(_quoted_credits(adapter) or 0.0))
            committed += spend
            clip = work_dir / f"{take_kind}_{index:02d}_{uuid4().hex[:8]}.mp4"
            clip.write_bytes(clip_bytes)
            take_id = record_take(
                engine,
                storyboard_id=storyboard_id,
                scene_number=index,
                kind=take_kind,
                prompt_hash=identity,
                model_id=model_id,
                resolution=MOTION_RESOLUTION,
                status="PAID",
                correlation_id=correlation_id,
                seconds=float(seconds),
                seed=seed,
                credits_quoted=spend,
                path=clip,
                sha256=_file_sha256(clip),
            )
            charged.append(
                {"take_id": take_id, "model": model_id, "seconds": seconds, "spend": spend}
            )
            bought_now.append(index)
            outcome = {"status": "PAID", "take_id": take_id, "credits_quoted": spend}
        entry.update(outcome)
        entry["attempts"] = attempts
        if outcome["status"] in ("NEEDS_OWNER", "NEEDS_STILL"):
            _storyboard_event(
                engine,
                "media.motion_needs_owner",
                storyboard_id,
                {
                    "severity": "WARNING",
                    "scene_number": index,
                    "status": outcome["status"],
                    "reason": outcome["reason"],
                    "failure_kind": entry.get("failure_kind"),
                    "suggested": entry.get("suggested"),
                },
                correlation_id,
            )

    after: float | None = None
    measured: float | None = None
    if to_buy and read:
        _read, after, _problem = _account_balance(source)
        if before is not None and after is not None and before - after > 0:
            measured = before - after
    if measured is not None and charged:
        total = sum(item["spend"] for item in charged) or 1.0
        with Session(engine) as session, session.begin():
            for item in charged:
                row = session.get(SceneTake, item["take_id"])
                if row is not None:
                    row.credits_measured = round(measured * item["spend"] / total, 4)
        if integration_id:
            record_measured_prices(
                engine,
                integration_id,
                {integration_id: {"kind": "runway", "balance": before}},
                {integration_id: {"kind": "runway", "balance": after}},
                [
                    {
                        "kind": take_kind,
                        "model_id": item["model"],
                        "resolution": resolution,
                        "seconds": item["seconds"],
                    }
                    for item in charged
                ],
                table=prices,
            )

    summary = {
        "storyboard_id": storyboard_id,
        "step": step,
        "plan_hash": plan_hash,
        "seed": seed,
        "resolution": resolution,
        "scenes": results,
        "bought_shots": len(bought_now),
        "spent_credits_quoted": round(committed, 4),
        "spent_credits_measured": measured,
        "balance_before": before,
        "balance_after": after,
        "cap_credits": cap,
        "stopped": stopped,
        "needs_owner": [e["scene_index"] for e in results if e.get("status") == "NEEDS_OWNER"],
        "needs_still": [e["scene_index"] for e in results if e.get("status") == "NEEDS_STILL"],
        "credit_usd": prices.credit_usd,
    }
    _storyboard_event(engine, "media.motion_step_finished", storyboard_id, summary, correlation_id)
    return summary


# ------------------------------------------------------------------------ the scene redo
#
# After the film, a failed scene is redone alone, and nothing else is bought or rebuilt. The
# Nepal film failed on two composed scenes and 0.07 dB of sound, and the studio's only answer
# was to buy the whole film again: every still, every clip, with the same prompts. Here:
#
# - ``card``: the card is recomposed locally from its own spec and the film is rejoined from
#   the shot files already built, which are checked against their recorded sha256 and never
#   rewritten. 0 credits, no adapter, no question to the Owner (nothing is bought);
# - ``audio``: the sound is remastered under the same picture (`repair_audio`, -c:v copy);
# - ``motion``: ONE shot of that scene, under the Owner's yes for ``media.scene_redo`` bound
#   to this redo's own plan_hash and cap (`run_motion_step` with ``step='scene_redo'``); the
#   scene's old shot is retired in the transaction that spends the yes, and once the new shot
#   lands the film is rejoined with only that shot rebuilt;
# - ``still``: one pair of candidates for that scene (at most two re-rolls inside the cap),
#   under the same kind of yes; the old still and every shot filmed from it are retired, since
#   a shot never outlives the picture it started from. The new still waits for a motion redo.
#
# A redo's plan_hash covers that scene only (its prompt, still, model, seconds, credits, cap
# and the takes it replaces), so a change elsewhere in the film does not void a yes the Owner
# gave for this scene, and a yes for this scene buys no other.

#: What can be redone: one scene's still, motion or card, or the film's sound.
REDO_KINDS: tuple[str, ...] = ("still", "motion", "card", "audio")
#: The redo kinds that buy something, each under the Owner's yes.
PAID_REDO_KINDS: tuple[str, ...] = ("still", "motion")
#: The Policy Kernel's action and the sheet step a paid redo's yes is bound to.
REDO_ACTION = "media.scene_redo"
REDO_STEP = "scene_redo"
REDO_TIER = "T3"
#: The failure code of a take the Owner had redone, and of a shot whose still was replaced.
REDO_FAILURE_CODE = "REDO.OWNER"
REDO_STILL_REPLACED = "REDO.STILL_REPLACED"


class SceneRedoRefused(RuntimeError):
    """A redo did nothing. ``status`` says why; ``reason_ro`` is the Owner's.

    NEEDS_APPROVAL is a 202 (his question waits, with ``approval_id``), NOT_FOUND a 404,
    UNKNOWN_KIND a 422, and every other status (STALE_PLAN, NO_PLAN, KIND_MISMATCH, NO_FILM,
    LOW_BALANCE, LINT_BLOCKED, ...) a 409.
    """

    def __init__(
        self,
        status: str,
        reason_ro: str,
        *,
        approval_id: str | None = None,
        plan: dict[str, Any] | None = None,
        findings: list[Any] | None = None,
    ) -> None:
        super().__init__(reason_ro)
        self.status = status
        self.reason_ro = reason_ro
        self.approval_id = approval_id
        self.plan = plan
        self.findings = list(findings or [])

    @property
    def http_status(self) -> int:
        return {"NEEDS_APPROVAL": 202, "NOT_FOUND": 404, "UNKNOWN_KIND": 422}.get(self.status, 409)

    def as_dict(self) -> dict[str, Any]:
        plan = self.plan or {}
        return {
            "error": "SceneRedoRefused",
            "status": self.status,
            "message": self.reason_ro,
            "approval_id": self.approval_id,
            "plan_hash": plan.get("plan_hash"),
            "cost_usd": plan.get("cost_usd"),
            "cap_credits": plan.get("cap_credits"),
            "findings": [f.as_dict() if hasattr(f, "as_dict") else f for f in self.findings[:20]],
        }


def _scene_shot_takes(session: Session, storyboard_id: str, scene_index: int) -> list[str]:
    """The scene's shots that could still go into a film (APPROVED or PAID), oldest first."""
    return list(
        session.scalars(
            select(SceneTake.id)
            .where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == scene_index,
                SceneTake.kind.in_(SHOT_TAKE_KINDS),
                SceneTake.status.in_(REUSABLE_TAKE_STATUSES),
            )
            .order_by(SceneTake.created_at, SceneTake.id)
        ).all()
    )


def _scene_approved_stills(session: Session, storyboard_id: str, scene_index: int) -> list[str]:
    return list(
        session.scalars(
            select(SceneTake.id)
            .where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == scene_index,
                SceneTake.kind == "still",
                SceneTake.status == "APPROVED",
            )
            .order_by(SceneTake.created_at, SceneTake.id)
        ).all()
    )


def _retire_takes(
    session: Session, take_ids: list[str], code: str, detail: str, correlation_id: str
) -> list[str]:
    """REJECTED with the reason, inside the caller's transaction: never used in a film again."""
    retired: list[str] = []
    for take_id in take_ids:
        row = session.get(SceneTake, take_id)
        if row is None or row.status not in REUSABLE_TAKE_STATUSES:
            continue
        previous = row.status
        row.status = "REJECTED"
        row.failure_code = code
        row.failure_detail = detail[:TAKE_DETAIL_MAX]
        row.updated_at = utc_now()
        append_event(
            session,
            "media.scene_take_retired",
            "scene_take",
            row.id,
            1,
            {
                "storyboard_id": row.storyboard_id,
                "scene_number": row.scene_number,
                "kind": row.kind,
                "previous_status": previous,
                "failure_code": code,
            },
            correlation_id,
        )
        retired.append(row.id)
    return retired


def _latest_film(engine: Engine, storyboard_id: str) -> dict[str, Any] | None:
    """The storyboard's newest finished film whose file is on disk, with its manifest."""
    with Session(engine) as session:
        jobs = session.scalars(
            select(VideoRenderJob)
            .where(
                VideoRenderJob.storyboard_id == storyboard_id,
                VideoRenderJob.status == "COMPLETED",
                VideoRenderJob.output_asset_id.is_not(None),
            )
            .order_by(VideoRenderJob.finished_at.desc(), VideoRenderJob.started_at.desc())
        ).all()
        for job in jobs:
            asset = session.get(MediaAsset, job.output_asset_id)
            if asset is None or not Path(asset.uri_or_path).is_file():
                continue
            return {
                "asset_id": asset.id,
                "job_id": job.id,
                "path": asset.uri_or_path,
                "production": copy.deepcopy(job.production_json or {}),
                "provider_name": asset.provider_name,
                "license_status": asset.license_status,
                "width": asset.width,
                "height": asset.height,
            }
    return None


def _seal(plan: dict[str, Any], hashed: dict[str, Any], reason_ro: str) -> dict[str, Any]:
    """The plan with its Romanian line and its plan_hash (over what this redo would do)."""
    identity = {
        "storyboard_id": plan["storyboard_id"],
        "kind": plan["kind"],
        "scene_index": plan["scene_index"],
        **hashed,
    }
    return {
        **plan,
        "reason_ro": reason_ro,
        "plan_hash": hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest(),
    }


def redo_plan(
    engine: Engine,
    storyboard_id: str,
    kind: str,
    scene_index: int | None = None,
    *,
    capabilities: list[ModelCapability] | tuple[ModelCapability, ...] | None = None,
    integration_id: str | None = None,
    allowed: Any = None,
    overrides: dict[int, str | None] | None = None,
    resolution: str | None = None,
    table: PriceTable | None = None,
    stills_model: str | None = None,
) -> dict[str, Any]:
    """What one redo would do, cost and replace, with its plan_hash. 0 credits, no network.

    A card or audio redo is free (``free``) and needs no yes. A still or motion redo names its
    model, credits, cap, the takes it replaces and (for a still) the shots it invalidates; the
    Owner's yes for ``media.scene_redo`` is bound to this hash. Raises `SceneRedoRefused` for
    an unknown kind (UNKNOWN_KIND), scene (NOT_FOUND) or a kind the scene does not have
    (KIND_MISMATCH).
    """
    if kind not in REDO_KINDS:
        raise SceneRedoRefused(
            "UNKNOWN_KIND",
            f"Refacere necunoscută: {kind}. Se pot reface imaginea, mișcarea sau cardul unei "
            "scene, ori sunetul filmului.",
        )
    try:
        _title, scenes = _storyboard_scenes(engine, storyboard_id)
    except ValueError as exc:
        raise SceneRedoRefused("NOT_FOUND", "Storyboardul nu există sau nu are scene.") from exc
    film = _latest_film(engine, storyboard_id)
    prices = table or load_price_table()
    plan: dict[str, Any] = {
        "storyboard_id": storyboard_id,
        "kind": kind,
        "scene_index": None,
        "scene_kind": None,
        "action": None,
        "tier": None,
        "free": True,
        "buyable": False,
        "model_id": None,
        "resolution": None,
        "credits": 0,
        "cap_credits": 0,
        "cost_usd": 0.0,
        "cap_usd": 0.0,
        "credit_usd": prices.credit_usd,
        "price_source": None,
        "replaces": [],
        "invalidates": [],
        "base_asset_id": film["asset_id"] if film else None,
        "base_job_id": film["job_id"] if film else None,
    }
    if kind == "audio":
        reason = (
            "Sunetul filmului se remasterizează din pistele de voce păstrate, sub aceeași imagine "
            "(pachetele video rămân identice): 0 credite."
            if film
            else "Nu există încă un film randat: nu are ce sunet să fie refăcut."
        )
        return _seal(plan, {"base_asset_id": plan["base_asset_id"]}, reason)
    scene = next((s for s in scenes if int(s["scene_index"]) == scene_index), None)
    if scene is None:
        raise SceneRedoRefused("NOT_FOUND", f"Scena {scene_index} nu există în acest storyboard.")
    index = int(scene["scene_index"])
    scene_kind = scene_kind_of(scene)
    plan.update(scene_index=index, scene_kind=scene_kind)
    if kind == "card":
        if not is_composed(scene):
            raise SceneRedoRefused(
                "KIND_MISMATCH",
                f"Scena {index} este filmată ({scene_kind}), nu un card compus: i se reface "
                "imaginea sau mișcarea, nu cardul.",
                plan=plan,
            )
        return _seal(
            plan,
            {"card_json": scene.get("card_json"), "base_asset_id": plan["base_asset_id"]},
            f"Cardul scenei {index} se recompune local din cifrele lui, iar filmul se "
            "reasamblează din celelalte cadre, neschimbate: 0 credite.",
        )
    if is_composed(scene):
        raise SceneRedoRefused(
            "KIND_MISMATCH",
            f"Scena {index} este un card compus local ({scene_kind}): nu are imagine sau "
            "mișcare cumpărate; i se reface cardul, gratuit.",
            plan=plan,
        )
    if kind == "still":
        return _still_redo_plan(engine, plan, scenes, scene, prices, stills_model)
    return _motion_redo_plan(
        engine,
        plan,
        scene,
        capabilities=capabilities,
        integration_id=integration_id,
        allowed=allowed,
        overrides=overrides,
        resolution=resolution or MOTION_STEP_RESOLUTION,
        table=prices,
    )


def _still_redo_plan(
    engine: Engine,
    plan: dict[str, Any],
    scenes: list[dict[str, Any]],
    scene: dict[str, Any],
    prices: PriceTable,
    stills_model: str | None,
) -> dict[str, Any]:
    from app.media.still_gate import MAX_REROLLS  # noqa: PLC0415 - still_gate reaches qc

    index = int(scene["scene_index"])
    model_id = stills_model or STILLS_MODEL
    try:
        per_request = price_still(model_id, STILLS_RESOLUTION, STILL_CANDIDATES, table=prices)
        row = prices.row(model_id, STILLS_RESOLUTION)
    except UnpricedError as exc:
        raise SceneRedoRefused("UNPRICED", f"Nu se cumpără imagini: {exc}.", plan=plan) from exc
    cap = per_request * (1 + MAX_REROLLS)
    first_live = next((s for s in scenes if not is_composed(s)), None)
    figure_one: str | None = None
    with Session(engine) as session:
        replaces = _scene_approved_stills(session, plan["storyboard_id"], index)
        invalidates = _scene_shot_takes(session, plan["storyboard_id"], index)
        if first_live is not None and int(first_live["scene_index"]) != index:
            reference = usable_take(
                session,
                plan["storyboard_id"],
                int(first_live["scene_index"]),
                "still",
                [still_fields(str(first_live["visual_prompt"] or ""), None)],
                statuses=("APPROVED",),
            )
            figure_one = reference.sha256 if reference is not None else None
    package = scene.get("prompt_json") or {}
    words = " ".join(str(package.get("still_prompt") or scene.get("visual_prompt") or "").split())
    plan.update(
        action=REDO_ACTION,
        tier=REDO_TIER,
        free=False,
        buyable=True,
        model_id=model_id,
        resolution=STILLS_RESOLUTION,
        credits=per_request,
        cap_credits=cap,
        cost_usd=round(per_request * prices.credit_usd, 6),
        cap_usd=round(cap * prices.credit_usd, 6),
        price_source=source_label(row),
        candidates=STILL_CANDIDATES,
        max_rerolls=MAX_REROLLS,
        still_prompt=words,
        figure_one_sha256=figure_one,
        replaces=replaces,
        invalidates=invalidates,
    )
    reason = (
        f"Imaginea scenei {index}: {STILL_CANDIDATES} variante la 2K pe {model_id}, "
        f"{per_request} credite (plafon {cap}, cu cel mult {MAX_REROLLS} reluări). "
        "Imaginea veche și cadrul filmat din ea se retrag abia după aprobare; mișcarea scenei "
        "se reface apoi separat. Celelalte scene nu se ating."
    )
    return _seal(
        plan,
        {
            "model_id": model_id,
            "resolution": STILLS_RESOLUTION,
            "candidates": STILL_CANDIDATES,
            "max_rerolls": MAX_REROLLS,
            "credits": per_request,
            "cap_credits": cap,
            "still_prompt": words,
            "identity": still_fields(str(scene.get("visual_prompt") or ""), None),
            "figure_one_sha256": figure_one,
            "replaces": replaces,
            "invalidates": invalidates,
        },
        reason,
    )


def _motion_redo_plan(
    engine: Engine,
    plan: dict[str, Any],
    scene: dict[str, Any],
    *,
    capabilities: list[ModelCapability] | tuple[ModelCapability, ...] | None,
    integration_id: str | None,
    allowed: Any,
    overrides: dict[int, str | None] | None,
    resolution: str,
    table: PriceTable,
) -> dict[str, Any]:
    index = int(scene["scene_index"])
    try:
        caps = _capabilities(engine, capabilities, integration_id)
    except ValueError as exc:
        raise SceneRedoRefused(
            "NO_MODELS",
            "Nu se știe ce modele video sunt conectate: mișcarea nu poate fi planificată.",
            plan=plan,
        ) from exc
    state = _motion_state(
        engine,
        plan["storyboard_id"],
        capabilities=caps,
        allowed=allowed,
        overrides=overrides,
        resolution=resolution,
        table=table,
        redo=index,
    )
    item = next(entry for entry in state["plan"]["scenes"] if entry["scene_index"] == index)
    if item["status"] == "NEEDS_STILL":
        raise SceneRedoRefused("NEEDS_STILL", item["reason_ro"], plan=plan)
    step = state["plan"]["steps"][REDO_STEP]
    with Session(engine) as session:
        replaces = _scene_shot_takes(session, plan["storyboard_id"], index)
    buyable = bool(step["to_buy"])
    fields = state["fields"].get(index) or {}
    plan.update(
        action=REDO_ACTION,
        tier=REDO_TIER,
        free=False,
        buyable=buyable,
        model_id=item["model_id"],
        resolution=resolution,
        status=item["status"],
        billed_seconds=item["billed_seconds"],
        seed=state["plan"]["seed"],
        credits=step["cost_credits"],
        cap_credits=step["cap_credits"],
        cost_usd=step["cost_usd"],
        cap_usd=step["cap_usd"],
        price_source=item["price_source"],
        cheaper=item["cheaper"],
        better=item["better"],
        still_sha256=item["still_sha256"],
        motion_prompt=item["motion_prompt"],
        lint_blocked=state["plan"]["lint_blocked"],
        replaces=replaces,
    )
    if buyable:
        reason = (
            f"Mișcarea scenei {index}: un singur cadru pe {item['model_id']}, "
            f"{item['billed_seconds']} s, {step['cost_credits']} credite (plafon "
            f"{step['cap_credits']}). Cadrul vechi se retrage abia după aprobare; celelalte "
            "scene nu se ating."
        )
    else:
        reason = f"Scena {index} nu are ce cumpăra: {item['reason_ro'] or item['status']}."
    return _seal(
        plan,
        {
            "model_id": item["model_id"],
            "resolution": resolution,
            "status": item["status"],
            "billed_seconds": item["billed_seconds"],
            "credits": step["cost_credits"],
            "cap_credits": step["cap_credits"],
            "still_sha256": item["still_sha256"],
            "package": fields.get("package"),
            "motion_prompt": item["motion_prompt"],
            "seed": state["plan"]["seed"],
            "replaces": replaces,
        },
        reason,
    )


def _film_timeline(
    production: dict[str, Any], scenes: list[dict[str, Any]], folder: Path
) -> list[dict[str, Any]]:
    """The film's shots in order, as the render recorded them (production['shots']); for an
    older render, rebuilt from the shot files beside it and the lengths it measured. A film
    rendered before 2026-10-01 dissolved every join by TRANSITION_SECONDS, and is rejoined
    the way it was made."""
    recorded = production.get("shots")
    if isinstance(recorded, list) and recorded:
        items = [dict(item) for item in recorded if isinstance(item, dict)]
        for position, item in enumerate(items):
            item.setdefault("dissolve_seconds", TRANSITION_SECONDS if position else 0.0)
        return items
    voice = (production.get("voice") or {}).get("provider")
    real_voice = voice not in (None, PLACEHOLDER_VOICE_PROVIDER)
    entries = {
        int(entry.get("scene_index") or 0): entry
        for entry in production.get("scenes") or []
        if isinstance(entry, dict)
    }
    timeline: list[dict[str, Any]] = []
    for scene in scenes:
        index = int(scene["scene_index"])
        path = folder / f"shot_{index:02d}.mp4"
        if not path.is_file():
            raise SceneRedoRefused(
                "NO_SHOTS",
                f"Cadrul scenei {index} nu mai este lângă film: filmul nu poate fi reasamblat "
                "fără să fie randat din nou.",
            )
        planned = float(scene.get("duration_seconds") or 0.0)
        spoken = float((entries.get(index) or {}).get("audio_seconds") or 0.0)
        length = max(planned, spoken) if real_voice else planned
        timeline.append(
            {
                "scene_index": index,
                "file": path.name,
                "sha256": None,
                "span": round(length + TRANSITION_SECONDS, 3),
                "duration_seconds": round(length, 3),
                "dissolve_seconds": TRANSITION_SECONDS if timeline else 0.0,
            }
        )
    return timeline


def film_fps(production: dict[str, Any]) -> int:
    """The frame rate a film was cut at: its recorded timeline's, or 30 for a film from
    before the 24 fps timeline (which recorded none)."""
    timeline = production.get("timeline")
    fps = timeline.get("fps") if isinstance(timeline, dict) else None
    return int(fps) if isinstance(fps, int | float) and fps > 0 else 30


def _card_background(
    engine: Engine,
    storyboard_id: str,
    production: dict[str, Any],
    scenes: list[dict[str, Any]],
    folder: Path,
    scene_index: int,
) -> Path | None:
    """What the card stood on in the film (the first real still), else the first LIVE
    scene's approved still, else nothing (the colour canvas)."""
    for entry in production.get("scenes") or []:
        if isinstance(entry, dict) and entry.get("scene_index") == scene_index:
            name = (entry.get("card") or {}).get("background")
            if name and (folder / str(name)).is_file():
                return folder / str(name)
    first_live = next((s for s in scenes if not is_composed(s)), None)
    if first_live is None:
        return None
    with Session(engine) as session:
        take = usable_take(
            session,
            storyboard_id,
            int(first_live["scene_index"]),
            "still",
            [still_fields(str(first_live["visual_prompt"] or ""), None)],
            statuses=("APPROVED",),
        )
        return Path(str(take.path)) if take is not None and take.path else None


def _run_ffmpeg(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - argument list, no shell
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=600,
        check=False,
    )


def _verified_timeline(
    film: dict[str, Any], scenes: list[dict[str, Any]], scene_index: int
) -> list[dict[str, Any]]:
    """The film's shots, each other than ``scene_index`` checked to be the very file the film
    was joined from; a shot rebuilt since (another render) is never mixed in."""
    folder = Path(film["path"]).parent
    timeline = _film_timeline(film["production"], scenes, folder)
    if [int(item["scene_index"]) for item in timeline] != [int(s["scene_index"]) for s in scenes]:
        raise SceneRedoRefused(
            "FILM_CHANGED",
            "Scenele storyboardului nu mai sunt cele din film: filmul nu se reasamblează pe "
            "bucăți.",
        )
    for item in timeline:
        if int(item["scene_index"]) == scene_index:
            continue
        path = folder / str(item["file"])
        if not path.is_file():
            raise SceneRedoRefused(
                "NO_SHOTS", f"Cadrul scenei {item['scene_index']} lipsește de lângă film."
            )
        if item.get("sha256") and _file_sha256(path) != item["sha256"]:
            raise SceneRedoRefused(
                "SHOT_CHANGED",
                f"Cadrul scenei {item['scene_index']} nu mai este cel din film (a fost "
                "reconstruit între timp): nu se amestecă cadre din filme diferite.",
            )
    return timeline


def _rebuild_film(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    *,
    scene_index: int,
    redo: str,
    ffmpeg_exe: str,
    moving: Path | None = None,
    motion_record: dict[str, Any] | None = None,
    credits_quoted: float | None = None,
) -> dict[str, Any]:
    """The newest film with one scene's shot rebuilt and every other shot file reused.

    The other shots are read, never rewritten: each must still be the file the film was made
    from (its recorded sha256), or nothing is built. The film's own sound is copied in. The
    film it came from is left untouched; the result is a new asset with its own render record,
    whose manifest says what it was remade from and what it cost.
    """
    film = _latest_film(engine, storyboard_id)
    if film is None:
        raise SceneRedoRefused(
            "NO_FILM",
            "Nu există încă un film randat al acestui storyboard: nu are ce să fie reasamblat.",
        )
    production: dict[str, Any] = film["production"]
    source = Path(film["path"])
    folder = source.parent
    _title, scenes = _storyboard_scenes(engine, storyboard_id)
    timeline = _verified_timeline(film, scenes, scene_index)
    target = next(item for item in timeline if int(item["scene_index"]) == scene_index)
    scene = next(s for s in scenes if int(s["scene_index"]) == scene_index)
    span = float(target["span"])
    # A redone shot is cut at the film's own frame rate: a film from before the 24 fps
    # timeline is rejoined at its 30, never a mix of the two.
    fps = film_fps(production)
    stamp = uuid4().hex[:8]
    card_record: dict[str, Any] | None = None
    if redo == "card":
        work = folder / f"redo_{stamp}"
        work.mkdir(parents=True, exist_ok=True)
        background = _card_background(
            engine, storyboard_id, production, scenes, folder, scene_index
        )
        try:
            card_record = _compose_card_clip(
                scene, work, seconds=span, background=background, ffmpeg_exe=ffmpeg_exe, fps=fps
            )
        except CardError as exc:
            raise SceneRedoRefused(
                "CARD_INVALID", f"Scena {scene_index}: cardul nu poate fi compus: {exc}"
            ) from exc
        moving = Path(card_record["path"])
    if moving is None:
        raise ValueError("a rebuilt shot needs its clip")
    shot = folder / f"shot_{scene_index:02d}_redo_{stamp}.mp4"
    have = _video_stream_seconds(ffmpeg_exe, moving)
    hold = span - have if have is not None and have + 0.5 / fps < span else 0.0
    built = _run_ffmpeg(
        _shot_command(
            ffmpeg_exe,
            moving,
            moving,
            span,
            shot,
            fps=fps,
            hold=hold,
            dither=has_filter(ffmpeg_exe, "zscale"),
        ),
        folder,
    )
    if built.returncode != 0 or not shot.is_file() or shot.stat().st_size == 0:
        raise SceneRedoRefused(
            "ENCODE_FAILED", f"Cadrul nou al scenei {scene_index} nu a putut fi construit."
        )
    rebuilt = {
        "scene_index": scene_index,
        "file": shot.name,
        "sha256": _file_sha256(shot),
        "span": round(span, 6),
        "duration_seconds": target["duration_seconds"],
        "dissolve_seconds": target.get("dissolve_seconds", 0.0),
        "held_seconds": round(hold, 3),
    }
    timeline = [rebuilt if int(i["scene_index"]) == scene_index else i for i in timeline]

    captions: str | None = None
    caption_record = production.get("captions") or {}
    if caption_record.get("burned_in"):
        # The captions the film was burnt with: its ASS script in Inter Bold, or for a film
        # from before the ASS captions its SRT in the legacy style.
        ass = caption_record.get("ass")
        srt = folder / Path(str(ass or caption_record.get("srt") or "captions.srt")).name
        if not srt.is_file():
            raise SceneRedoRefused(
                "CAPTIONS_MISSING",
                "Subtitrările filmului nu mai sunt lângă el: filmul nu se reasamblează fără ele.",
            )
        if ass:
            try:
                install_caption_fonts(folder)
            except CardError as exc:
                raise SceneRedoRefused(
                    "CAPTIONS_MISSING",
                    f"Fontul subtitrărilor nu poate fi folosit: {exc}",
                ) from exc
            captions = ass_captions_filter(srt.name)
        else:
            captions = captions_filter(srt.name)
    output = folder / f"{source.stem}_redo_{stamp}.mp4"
    command = _dissolve_command(
        ffmpeg_exe,
        [folder / str(item["file"]) for item in timeline],
        [
            {
                "duration_seconds": float(item["duration_seconds"]),
                "dissolve_seconds": float(item.get("dissolve_seconds") or 0.0),
            }
            for item in timeline
        ],
        source,
        output,
        audio_filter=None,
        captions=captions,
        fps=fps,
    )
    joined = _run_ffmpeg(command, folder)
    total = sum(float(item["duration_seconds"]) for item in timeline)
    picture = _video_stream_seconds(ffmpeg_exe, output) if output.is_file() else None
    if joined.returncode != 0 or picture is None or picture + 1.0 < total:
        output.unlink(missing_ok=True)
        raise SceneRedoRefused(
            "ENCODE_FAILED",
            f"Filmul nu a putut fi reasamblat cu scena {scene_index} refăcută "
            f"(cod {joined.returncode}).",
        )

    reused = [int(i["scene_index"]) for i in timeline if int(i["scene_index"]) != scene_index]
    _redone_manifest(
        production,
        timeline,
        scene_index,
        card_record=card_record,
        motion_record=motion_record,
    )
    loudness = (production.get("audio") or {}).get("loudness")
    if isinstance(loudness, dict):
        loudness["output"] = _loudness_readings(measure_loudness(ffmpeg_exe, output))
    production["remaster"] = {
        "kind": "scene_redo",
        "redo": redo,
        "scene_index": scene_index,
        "of_asset": film["asset_id"],
        "of_job": film["job_id"],
        "reused_shots": reused,
        "rebuilt_shots": [scene_index],
        "credits": 0 if redo == "card" else None,
        "credits_quoted": credits_quoted,
    }
    recorded = _record_redone_film(
        engine,
        storyboard_id,
        correlation_id,
        film=film,
        output=output,
        command=command,
        production=production,
        seconds=total,
        log=joined.stderr or "",
        redo=redo,
        scene_index=scene_index,
    )
    return {
        **recorded,
        "file_path": str(output),
        "duration_seconds": round(total, 3),
        "of_asset": film["asset_id"],
        "reused_shots": reused,
        "rebuilt_shots": [scene_index],
    }


def _redone_manifest(
    production: dict[str, Any],
    timeline: list[dict[str, Any]],
    scene_index: int,
    *,
    card_record: dict[str, Any] | None,
    motion_record: dict[str, Any] | None,
) -> None:
    """The film's manifest with the redone scene's shot, card or motion record in place."""
    production["shots"] = timeline
    for entry in production.get("scenes") or []:
        if isinstance(entry, dict) and entry.get("scene_index") == scene_index:
            if card_record is not None:
                entry["card"] = card_record
            if motion_record is not None:
                entry["motion"] = motion_record
    moved = [
        e["motion"]
        for e in production.get("scenes") or []
        if isinstance(e, dict) and isinstance(e.get("motion"), dict)
    ]
    if isinstance(production.get("motion"), dict):
        clips = sum(1 for record in moved if record.get("bytes"))
        production["motion"].update(
            clips=clips,
            motion_scenes=clips,
            fallback_scenes=sum(1 for record in moved if not record.get("bytes")),
        )


def _record_redone_film(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    *,
    film: dict[str, Any],
    output: Path,
    command: list[str],
    production: dict[str, Any],
    seconds: float,
    log: str,
    redo: str,
    scene_index: int,
) -> dict[str, Any]:
    """A new MediaAsset and a COMPLETED render job for the rejoined film."""
    file_bytes = output.read_bytes()
    provenance_hash = hashlib.sha256(file_bytes).hexdigest()
    finished_at = utc_now()
    output_asset_id = str(uuid4())
    render_job_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session,
            "media.video_rendered",
            "media_asset",
            output_asset_id,
            1,
            {
                "storyboard_id": storyboard_id,
                "render_engine": "FFMPEG",
                "remade_from": film["asset_id"],
                "redo": redo,
                "scene_index": scene_index,
                "provenance_hash": provenance_hash,
                "file_size_bytes": len(file_bytes),
                "duration_seconds": seconds,
            },
            correlation_id,
        )
        session.add(
            MediaAsset(
                id=output_asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(output),
                file_size_bytes=len(file_bytes),
                mime_type="video/mp4",
                width=film["width"] or 1080,
                height=film["height"] or 1920,
                duration_seconds=round(seconds, 2),
                provider_name=film["provider_name"],
                remote_job_id=None,
                license_status=film["license_status"],
                provenance_hash=provenance_hash,
                created_at=finished_at,
                event_id=event.event_id,
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=render_job_id,
                storyboard_id=storyboard_id,
                output_asset_id=output_asset_id,
                status="COMPLETED",
                render_engine="FFMPEG",
                command_args_json=command,
                production_json=production,
                execution_log=log[-8000:],
                started_at=finished_at,
                finished_at=finished_at,
                event_id=event.event_id,
            )
        )
    return {
        "output_asset_id": output_asset_id,
        "job_id": render_job_id,
        "provenance_hash": provenance_hash,
    }


def redo_scene(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    *,
    kind: str,
    scene_index: int | None = None,
    plan_hash: str | None = None,
    image_adapter: Any = None,
    adapter_for_model: Callable[[str], Any] | None = None,
    capabilities: list[ModelCapability] | tuple[ModelCapability, ...] | None = None,
    account: Any = None,
    registry: Any = None,
    judge: Callable[..., Any] | None = None,
    face_counter: Callable[..., Any] | None = None,
    measure: tuple[str, ...] | None = None,
    allowed: Any = None,
    overrides: dict[int, str | None] | None = None,
    resolution: str | None = None,
    settings: Any | None = None,
    environment: str | None = None,
    integration_id: str | None = None,
    table: PriceTable | None = None,
    ffmpeg_path: str | None = None,
    storage_root: Path | None = None,
    requester: str = "video_editor",
    note: str | None = None,
    allow_over_budget: bool = False,
) -> dict[str, Any]:
    """Redo one scene (``still`` | ``motion`` | ``card``) or the film's sound (``audio``).

    Card and audio cost 0 credits and need no yes. A still or motion redo buys only under the
    Owner's yes for ``media.scene_redo`` bound to ``plan_hash`` (`redo_plan`), spent once;
    raises `SceneRedoRefused` (202 with his question, or 409/404 with the reason) when nothing
    may be bought. Every other take and every other shot file is reused; nothing here
    renders the whole film again.
    """
    resolution = (
        resolution or getattr(settings, "motion_resolution", None) or MOTION_STEP_RESOLUTION
    )
    stills_model = str(getattr(image_adapter, "model", None) or STILLS_MODEL)

    def current(engine_: Engine = engine) -> dict[str, Any]:
        return redo_plan(
            engine_,
            storyboard_id,
            kind,
            scene_index,
            capabilities=capabilities,
            integration_id=integration_id,
            allowed=allowed,
            overrides=overrides,
            resolution=resolution,
            table=table,
            stills_model=stills_model,
        )

    plan = current()
    if kind in ("card", "audio"):
        free = _free_redo(engine, storyboard_id, correlation_id, plan, ffmpeg_path=ffmpeg_path)
        return _redo_done(engine, correlation_id, plan, free, {}, (0.0, None))

    _paid_redo_gate(engine, plan, plan_hash, allow_over_budget=allow_over_budget)
    from app.services import studio_environment  # noqa: PLC0415

    environment = environment or studio_environment(engine)
    detail: dict[str, Any] = {}
    film: dict[str, Any] | None = None
    if kind == "motion":
        if adapter_for_model is None:
            raise SceneRedoRefused(
                "NO_ADAPTER",
                "Niciun model video conectat și verificat; mișcarea nu se poate cumpăra.",
                plan=plan,
            )
        try:
            summary = run_motion_step(
                engine,
                storyboard_id,
                correlation_id,
                step=REDO_STEP,
                plan_hash=str(plan_hash),
                adapter_for_model=adapter_for_model,
                capabilities=capabilities,
                account=account,
                cap_credits=int(plan["cap_credits"]),
                allowed=allowed,
                overrides=overrides,
                resolution=resolution,
                settings=settings,
                environment=environment,
                plan_hash_of=lambda engine_, _board: str(current(engine_)["plan_hash"]),
                integration_id=integration_id,
                table=table,
                ffmpeg_path=ffmpeg_path,
                storage_root=storage_root,
                requester=requester,
                redo_scene=int(plan["scene_index"]),
                redo_note=note,
            )
        except MotionStepRefused as exc:
            raise SceneRedoRefused(
                exc.status,
                exc.reason_ro,
                approval_id=exc.approval_id,
                plan=plan,
                findings=exc.findings,
            ) from exc
        detail["motion"] = summary
        spent = (float(summary["spent_credits_quoted"]), summary["spent_credits_measured"])
        film = _film_after_motion(engine, storyboard_id, correlation_id, plan, summary, ffmpeg_path)
    else:
        outcome = _redo_still(
            engine,
            storyboard_id,
            correlation_id,
            plan,
            plan_hash=str(plan_hash),
            image_adapter=image_adapter,
            registry=registry,
            judge=judge,
            face_counter=face_counter,
            measure=measure,
            environment=environment,
            ffmpeg_path=ffmpeg_path,
            storage_root=storage_root,
            integration_id=integration_id,
            table=table,
            requester=requester,
            note=note,
            settings=settings,
        )
        detail["still"] = outcome
        spent = (float(outcome["spent_credits_quoted"]), outcome["spent_credits_measured"])
    return _redo_done(engine, correlation_id, plan, film, detail, spent)


def _free_redo(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    plan: dict[str, Any],
    *,
    ffmpeg_path: str | None,
) -> dict[str, Any]:
    """A card or the sound, redone for 0 credits on the newest film."""
    if plan["base_asset_id"] is None:
        raise SceneRedoRefused("NO_FILM", plan["reason_ro"], plan=plan)
    ffmpeg_exe = resolve_ffmpeg_path(ffmpeg_path)
    if ffmpeg_exe is None:
        raise SceneRedoRefused(
            "NO_ENCODER", "FFmpeg nu este instalat: nimic nu poate fi refăcut.", plan=plan
        )
    if plan["kind"] == "card":
        return _rebuild_film(
            engine,
            storyboard_id,
            correlation_id,
            scene_index=int(plan["scene_index"]),
            redo="card",
            ffmpeg_exe=ffmpeg_exe,
        )
    try:
        repaired = repair_audio(
            engine, plan["base_asset_id"], correlation_id, ffmpeg_path=ffmpeg_exe
        )
    except AudioRepairError as exc:
        raise SceneRedoRefused("AUDIO_REPAIR_FAILED", str(exc), plan=plan) from exc
    return {
        "output_asset_id": repaired["output_asset_id"],
        "job_id": repaired["job_id"],
        "file_path": repaired["file_path"],
        "provenance_hash": repaired["provenance_hash"],
        "video_stream_sha256": repaired["video_stream_sha256"],
        "of_asset": plan["base_asset_id"],
    }


def _paid_redo_gate(
    engine: Engine, plan: dict[str, Any], plan_hash: str | None, *, allow_over_budget: bool
) -> None:
    """The refusals before a paid redo is asked or bought: no plan, a stale plan, nothing to
    buy, a budget the cap would exceed without the Owner's explicit consent."""
    if not plan_hash:
        raise SceneRedoRefused(
            "NO_PLAN",
            "O refacere plătită se cumpără doar pentru planul arătat Proprietarului: cererea nu "
            "numește planul (plan_hash).",
            plan=plan,
        )
    if plan_hash != plan["plan_hash"]:
        raise SceneRedoRefused(
            "STALE_PLAN",
            "Planul refacerii s-a schimbat de când a fost văzut (sau cererea numește alt plan): "
            "nu se cumpără nimic. Deschideți refacerea din nou și aprobați planul de acum.",
            plan=plan,
        )
    if not plan["buyable"]:
        raise SceneRedoRefused("NOTHING_TO_BUY", plan["reason_ro"], plan=plan)
    if allow_over_budget:
        return
    from app.media.shooting_sheet import _budget_refusal  # noqa: PLC0415 - it imports us

    budget = _budget_refusal(engine, credits_to_micros(plan["cap_credits"], plan["credit_usd"]))
    if budget is not None:
        period, reason = budget
        raise SceneRedoRefused(
            "OVER_DAILY_BUDGET" if period == "DAILY" else "OVER_BUDGET", reason, plan=plan
        )


def _redo_done(
    engine: Engine,
    correlation_id: str,
    plan: dict[str, Any],
    film: dict[str, Any] | None,
    detail: dict[str, Any],
    spent: tuple[float, float | None],
) -> dict[str, Any]:
    """The redo's result and its event (media.scene_redone)."""
    quoted, measured = spent
    credits = 0 if plan["free"] else quoted
    result: dict[str, Any] = {
        "storyboard_id": plan["storyboard_id"],
        "kind": plan["kind"],
        "scene_index": plan["scene_index"],
        "plan_hash": plan["plan_hash"],
        "credits": credits,
        "credits_quoted": quoted,
        "credits_measured": measured,
        "film": film,
        "next_ro": _redo_next_step(plan, film, detail),
        **detail,
    }
    _storyboard_event(
        engine,
        "media.scene_redone",
        plan["storyboard_id"],
        {
            "kind": plan["kind"],
            "scene_index": plan["scene_index"],
            "plan_hash": plan["plan_hash"],
            "credits": credits,
            "credits_measured": measured,
            "film_asset_id": (film or {}).get("output_asset_id"),
            "of_asset": plan["base_asset_id"],
        },
        correlation_id,
    )
    return result


def _film_after_motion(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    plan: dict[str, Any],
    summary: dict[str, Any],
    ffmpeg_path: str | None,
) -> dict[str, Any] | None:
    """The film rejoined with the redone shot, when one landed and a film exists."""
    index = int(plan["scene_index"])
    entry: dict[str, Any] = next((e for e in summary["scenes"] if e["scene_index"] == index), {})
    if entry.get("status") != "PAID" or plan["base_asset_id"] is None:
        return None
    ffmpeg_exe = resolve_ffmpeg_path(ffmpeg_path)
    with Session(engine) as session:
        take = session.get(SceneTake, entry.get("take_id"))
        clip = Path(str(take.path)) if take is not None and take.path else None
        take_status = take.status if take is not None else None
    if ffmpeg_exe is None or clip is None or not clip.is_file():
        return None
    _title, scenes = _storyboard_scenes(engine, storyboard_id)
    scene = next(s for s in scenes if int(s["scene_index"]) == index)
    record = {
        "model": entry.get("model_id"),
        "asked_seconds": motion_seconds(scene),
        "scene_category": scene_kind_of(scene),
        "story_purpose": scene.get("story_purpose"),
        "reused_take": False,
        "redo": True,
        "take_id": entry.get("take_id"),
        "take_status": take_status,
        "estimated_credits": entry.get("credits_quoted"),
        "bytes": clip.stat().st_size,
    }
    return _rebuild_film(
        engine,
        storyboard_id,
        correlation_id,
        scene_index=index,
        redo="motion",
        ffmpeg_exe=ffmpeg_exe,
        moving=clip,
        motion_record=record,
        credits_quoted=entry.get("credits_quoted"),
    )


def _redo_next_step(
    plan: dict[str, Any], film: dict[str, Any] | None, detail: dict[str, Any]
) -> str:
    """What happens next, in one Romanian line for the Owner."""
    index = plan["scene_index"]
    if plan["kind"] == "still":
        if (detail.get("still") or {}).get("status") == "APPROVED":
            return (
                f"Scena {index} are o imagine nouă. Mișcarea ei se reface separat (cu aprobare); "
                "până atunci filmul nu se reasamblează."
            )
        return f"Scena {index} așteaptă decizia Proprietarului pe foaia de filmare."
    if film is not None:
        return (
            "Filmul a fost reasamblat; controlul de calitate se rulează din nou pe filmul nou. "
            "Filmul vechi a rămas neschimbat."
        )
    if plan["kind"] == "motion":
        return (
            f"Cadrul nou al scenei {index} așteaptă privirea Proprietarului; filmul se "
            "reasamblează din înregistrările aprobate."
        )
    return "Nimic de reasamblat."


def _redo_still(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    plan: dict[str, Any],
    *,
    plan_hash: str,
    image_adapter: Any,
    registry: Any,
    judge: Callable[..., Any] | None,
    face_counter: Callable[..., Any] | None,
    measure: tuple[str, ...] | None,
    environment: str,
    ffmpeg_path: str | None,
    storage_root: Path | None,
    integration_id: str | None,
    table: PriceTable | None,
    requester: str,
    note: str | None,
    settings: Any | None,
) -> dict[str, Any]:
    """One scene's still bought again: one pair of candidates (at most two re-rolls within the
    cap), judged as the stills step judges them, under the Owner's yes for this redo."""
    from app.media import stills_stage as stills  # noqa: PLC0415 - stills_stage imports us
    from app.media.prompt_lint import bible_face_rule  # noqa: PLC0415
    from app.media.still_gate import StillPlan  # noqa: PLC0415
    from app.services import may_act  # noqa: PLC0415

    index = int(plan["scene_index"])
    if image_adapter is None:
        raise SceneRedoRefused(
            "NO_ADAPTER",
            "Niciun model de imagine conectat și verificat; imaginea nu se poate cumpăra.",
            plan=plan,
        )
    bible, scenes = stills._read_scenes(engine, storyboard_id)
    scene = next(s for s in scenes if s.index == index)
    live = [s for s in scenes if s.kind == LIVE_KIND]
    if environment == "PRODUCTION" and scene.source != "model":
        raise SceneRedoRefused(
            "NEEDS_SHOT_PLAN",
            f"Scena {index} nu are promptul scris de model din planul de cadre; nu se cumpără "
            "imagini din prompturi-șablon.",
            plan=plan,
        )
    findings = lint_film(
        [LintScene(scene=index, kind=LIVE_KIND, still_prompt=scene.words)], bible=bible
    )
    if has_block(findings):
        blocks = [f for f in findings if f.severity == "BLOCK"]
        raise SceneRedoRefused(
            "LINT_BLOCKED",
            summary_ro(findings) + " " + " ".join(f.message_ro for f in blocks[1:4]),
            plan=plan,
            findings=blocks,
        )
    cap = int(plan["cap_credits"])
    margin = float(getattr(settings, "paid_step_balance_margin", None) or PAID_STEP_BALANCE_MARGIN)
    read, before, problem = stills._read_balance(image_adapter)
    if problem is not None:
        raise SceneRedoRefused("LOW_BALANCE", f"Nu se cumpără imagini: {problem}.", plan=plan)
    if before is not None and before < cap * margin:
        raise SceneRedoRefused(
            "LOW_BALANCE",
            f"Soldul Runway ({before:.0f} credite) este sub plafonul refacerii ({cap} credite) "
            f"plus marja de {round((margin - 1) * 100)}%: alimentați contul înainte de aprobare.",
            plan=plan,
        )
    with Session(engine) as session, session.begin():
        verdict = may_act(
            session,
            REDO_ACTION,
            requester=requester,
            subject=storyboard_id,
            evidence=(
                f"imaginea scenei {index}: {STILL_CANDIDATES} variante la 2K, "
                f"{plan['credits']} credite, plafon {cap}"
            ),
            cost_usd=plan["cost_usd"],
            context={"plan_hash": plan_hash, "cap_credits": cap},
        )
        if verdict["allowed"]:
            # The yes is spent and the old picture retired together, with every shot that
            # started from it: a shot never outlives the still it was filmed from.
            _retire_takes(
                session,
                list(plan["replaces"]),
                REDO_FAILURE_CODE,
                note or "Proprietarul a cerut o imagine nouă pentru această scenă.",
                correlation_id,
            )
            _retire_takes(
                session,
                list(plan["invalidates"]),
                REDO_STILL_REPLACED,
                f"Cadrul a fost filmat din imaginea veche a scenei {index}, înlocuită la cererea "
                "Proprietarului; nu se mai folosește.",
                correlation_id,
            )
    if not verdict["allowed"]:
        raise SceneRedoRefused(
            str(verdict["status"]),
            str(verdict["reason"]),
            approval_id=verdict.get("approval_id"),
            plan=plan,
        )

    first = live[0] if live else None
    figure_one: bytes | None = None
    if first is not None and first.index != index and first.reuse is not None and first.reuse.path:
        figure_one = Path(str(first.reuse.path)).read_bytes()
    still_plan = StillPlan(
        scene=index,
        still_prompt=scene.words,
        camera_move=scene.camera_move,
        faces_forbidden=bible_face_rule(bible) is not None,
        bible_rules=stills._bible_rules(bible),
        look_block=scene.look_block,
        palette_words=stills._palette_words(scene.look_block),
    )
    work_dir = (storage_root or DEFAULT_STORAGE_ROOT) / storyboard_id / "stills"
    work_dir.mkdir(parents=True, exist_ok=True)
    buyer = _StillRedoBuyer(
        engine=engine,
        storyboard_id=storyboard_id,
        correlation_id=correlation_id,
        scene=scene,
        model_id=str(plan["model_id"]),
        per_request=int(plan["credits"]),
        cap=cap,
        references=[figure_one] if figure_one is not None else [],
        still_plan=still_plan,
        image_adapter=image_adapter,
        registry=registry,
        judge=judge,
        face_counter=face_counter,
        measure=measure,
        environment=environment,
        ffmpeg_path=ffmpeg_path,
        work_dir=work_dir,
    )
    outcome = buyer.run()
    measured = _measured_still_spend(
        engine,
        image_adapter,
        buyer,
        read=read,
        before=before,
        integration_id=integration_id,
        table=table,
    )
    return {
        **outcome,
        "scene_index": index,
        "model_id": plan["model_id"],
        "rerolls": buyer.rerolls,
        "bought_images": buyer.images,
        "spent_credits_quoted": round(buyer.committed, 4),
        "spent_credits_measured": measured["measured"],
        "balance_before": before,
        "balance_after": measured["after"],
        "cap_credits": cap,
        "retired": list(plan["replaces"]),
        "invalidated": list(plan["invalidates"]),
        "reference_unverified": buyer.unverified,
    }


class _StillRedoBuyer:
    """The purchase loop of one scene's still redo, the stills step's rules for one scene:
    the cap and the balance before every request, the local checks before the vision model,
    at most two re-rolls with the violations as positive words, then the Owner."""

    def __init__(self, **context: Any) -> None:
        self.context = context
        self.committed = 0.0
        self.images = 0
        self.take_ids: list[str] = []
        self.rerolls = 0
        self.unverified = False

    def run(self) -> dict[str, Any]:
        from app.media import stills_stage as stills  # noqa: PLC0415 - stills_stage imports us
        from app.media.picture_qc import judge_still  # noqa: PLC0415
        from app.media.still_gate import (  # noqa: PLC0415
            ALL_CHECKS,
            choose_best,
            next_step,
            positive_instruction,
        )
        from app.runbook.services import stop_requested  # noqa: PLC0415

        c = self.context
        engine: Engine = c["engine"]
        scene = c["scene"]
        index = int(scene.index)
        per_request = int(c["per_request"])
        identity = take_hash(scene.identity, c["model_id"])
        instruction = ""
        retried = False
        previous_kind: str | None = None
        outcome: dict[str, Any] | None = None
        while outcome is None:
            if stop_requested(engine):
                outcome = {"status": "NOT_BOUGHT", "reason": STOP_REASON}
                break
            if self.committed + per_request > c["cap"]:
                outcome = {
                    "status": "NOT_BOUGHT",
                    "reason": f"STOPPED_AT_CAP: încă o cerere ({per_request} credite) ar depăși "
                    f"plafonul aprobat de {c['cap']} credite (deja {self.committed:.0f}).",
                }
                break
            _read, balance, problem = stills._read_balance(c["image_adapter"])
            if problem is not None or (balance is not None and balance < per_request):
                outcome = {
                    "status": "NOT_BOUGHT",
                    "reason": f"Nu se mai cumpără imagini: {problem}."
                    if problem
                    else f"Soldul Runway ({balance:.0f} credite) nu mai acoperă o cerere "
                    f"({per_request} credite).",
                }
                break
            prompt = stills._prompt(scene, instruction, bool(c["references"]))
            try:
                candidates, quoted = stills._buy(
                    c["image_adapter"], prompt, c["references"], STILL_CANDIDATES
                )
            except MediaProviderError as exc:
                failure = classify_vendor_failure(exc, previous_kind)
                previous_kind = failure.kind
                self.committed += per_request  # a refusal may be paid like a success
                self._take(identity, "REFUSED", exc=exc)
                if failure.kind in stills.RETRY_KINDS and not retried:
                    retried = True
                    continue
                outcome = {
                    "status": "NEEDS_OWNER",
                    "reason": f"Scena {index}: {failure.reason_ro} Decide Proprietarul pe foaia "
                    "de filmare; aceleași cuvinte nu se trimit din nou.",
                    "failure_kind": failure.kind,
                    "failure_code": failure_code_of(exc),
                }
                break
            previous_kind = None
            self.committed += max(float(per_request), float(quoted or 0))
            self.unverified = self.unverified or (
                bool(c["references"])
                and not bool(getattr(c["image_adapter"], "REFERENCE_IMAGE_VERIFIED", False))
            )
            share = (quoted / len(candidates)) if quoted and candidates else per_request / 2
            verdicts: list[tuple[str, Any]] = []
            for number, candidate in enumerate(candidates):
                suffix = candidate.format if candidate.format in ("png", "jpeg", "webp") else "png"
                path = c["work_dir"] / (
                    f"scene_{index:02d}_redo_{uuid4().hex[:8]}_c{number + 1}."
                    + ("jpg" if suffix == "jpeg" else suffix)
                )
                path.write_bytes(candidate.image_bytes)
                self.images += 1
                take_id = self._take(
                    identity, "PAID", path=path, data=candidate.image_bytes, quoted=share
                )
                report = stills._judge_candidate(
                    engine,
                    c["registry"],
                    path,
                    c["still_plan"],
                    c["correlation_id"],
                    environment=c["environment"],
                    judge=c["judge"] or judge_still,
                    face_counter=c["face_counter"],
                    measure=c["measure"] or ALL_CHECKS,
                    ffmpeg_path=c["ffmpeg_path"],
                )
                verdicts.append((take_id, report))
            reports = [report for _take, report in verdicts]
            best = choose_best(reports)
            stills._set_verdicts(engine, verdicts, best)
            if best is not None:
                chosen = next(take for take, report in verdicts if report is best)
                outcome = {"status": "APPROVED", "take_id": chosen, "score": best.score}
                break
            failing = next((r for r in reports if r.violations), reports[0] if reports else None)
            if failing is None:
                outcome = {
                    "status": "NEEDS_OWNER",
                    "reason": f"Scena {index}: furnizorul nu a dat nicio imagine.",
                }
                break
            step = next_step(failing, rerolls_done=self.rerolls)
            if step.action == "reroll":
                self.rerolls += 1
                instruction = positive_instruction([v for r in reports for v in r.violations])
                continue
            outcome = {
                "status": "COMPOSE_LOCALLY" if step.action == "compose_locally" else "NEEDS_OWNER",
                "reason": step.reason_ro,
                "reasons": list(dict.fromkeys(text for r in reports for text in r.reasons_ro)),
            }
        if outcome["status"] in ("NEEDS_OWNER", "COMPOSE_LOCALLY"):
            _storyboard_event(
                engine,
                "media.still_needs_owner",
                c["storyboard_id"],
                {
                    "severity": "WARNING",
                    "scene_number": index,
                    "status": outcome["status"],
                    "reason": outcome["reason"],
                    "rerolls": self.rerolls,
                    "redo": True,
                },
                c["correlation_id"],
            )
        return outcome

    def _take(
        self,
        identity: str,
        status: str,
        *,
        exc: BaseException | None = None,
        path: Path | None = None,
        data: bytes | None = None,
        quoted: float | None = None,
    ) -> str:
        from app.media.stills_stage import STILL_RATIO  # noqa: PLC0415

        c = self.context
        take_id = record_take(
            c["engine"],
            storyboard_id=c["storyboard_id"],
            scene_number=int(c["scene"].index),
            kind="still",
            prompt_hash=identity,
            model_id=c["model_id"],
            resolution=STILL_RATIO,
            status=status,
            correlation_id=c["correlation_id"],
            credits_quoted=float(quoted) if quoted is not None else None,
            path=path,
            sha256=hashlib.sha256(data).hexdigest() if data is not None else None,
            failure_code=failure_code_of(exc) if exc is not None else None,
            failure_detail=failure_detail_of(exc) if exc is not None else None,
        )
        self.take_ids.append(take_id)
        return take_id


def _measured_still_spend(
    engine: Engine,
    image_adapter: Any,
    buyer: _StillRedoBuyer,
    *,
    read: bool,
    before: float | None,
    integration_id: str | None,
    table: PriceTable | None,
) -> dict[str, float | None]:
    """The balance drop across the redo, written on each picture bought and as MEASURED."""
    from app.economy.credits import record_measured_prices  # noqa: PLC0415
    from app.media import stills_stage as stills  # noqa: PLC0415 - stills_stage imports us

    after: float | None = None
    measured: float | None = None
    if read:
        _read, after, _problem = stills._read_balance(image_adapter)
        if before is not None and after is not None and before - after > 0:
            measured = before - after
    if measured is not None and buyer.images:
        each = measured / buyer.images
        with Session(engine) as session, session.begin():
            for take_id in buyer.take_ids:
                row = session.get(SceneTake, take_id)
                if row is not None and row.sha256:
                    row.credits_measured = each
        if integration_id:
            record_measured_prices(
                engine,
                integration_id,
                {integration_id: {"kind": "runway", "balance": before}},
                {integration_id: {"kind": "runway", "balance": after}},
                [
                    {
                        "kind": "still",
                        "model_id": buyer.context["model_id"],
                        "resolution": STILLS_RESOLUTION,
                        "count": buyer.images,
                    }
                ],
                table=table or load_price_table(),
            )
    return {"after": after, "measured": measured}
