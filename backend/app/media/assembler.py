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
import io
import json
import logging
import math
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import ROOT
from app.db import lock_for_write
from app.factual.editorial import dangles
from app.media import music_library
from app.media.balance_rule import (
    DEFAULT_MARGIN,
    LOW_BALANCE,
    low_balance_record,
    margin_of,
    needed_credits,
    purchase_stop_ro,
    start_refusal_ro,
)
from app.media.cards import (
    CARD_KINDS,
    CardError,
    card_spec_from_json,
    compose_card,
    compose_cover,
    film_finish,
)
from app.media.cost_plan import (
    SLOWDOWN_ALLOWANCE,
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
from app.media.disk import LOW_DISK, disk_refusal
from app.media.models import (
    MediaAsset,
    QualityControlReport,
    SceneTake,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.prepared_batch import RoundWork, flow_call, purchase_flow
from app.media.production_policy import (
    FailureRecord,
    FailureVerdict,
    ModelCapability,
    need_from_scene,
    plan_scene_models,
    record_quoted_price,
    replan_after_failure,
)
from app.media.prompt_lint import LintScene, has_block, lint_film, summary_ro
from app.media.sheet_words import NO_SHOT, NO_STILL
from app.media.speaker_voices import SPEAKER_GAP_SECONDS
from app.media.toolchain import (
    AUDIO_CODEC_ARGS,
    AUDIO_CODEC_LABEL,
    BED_FADE_IN_SECONDS,
    BED_FADE_OUT_SECONDS,
    EDGE_KEEP_SECONDS,
    LOUDNESS_TARGET_LUFS,
    MASTER_SAMPLE_RATE,
    TRUE_PEAK_CEILING_DBTP,
    TRUE_PEAK_TARGET_DBTP,
    AudioMasterError,
    AudioMixError,
    encode_master_audio,
    find_ffmpeg,
    has_filter,
    measure_loudness,
    mix_bed,
    speech_edges,
)
from app.models import DomainEvent
from app.providers.deterministic_media import (
    DeterministicTTSAdapter,
    DeterministicVisualAdapter,
)
from app.providers.media_base import ImageProvider, TTSProvider, TTSResult, VideoProvider
from app.providers.media_http import (
    MediaProviderError,
    MediaProviderNotConfigured,
    TaskStillOpen,
)
from app.providers.retry import SAFE_TO_RESEND_STATUSES
from app.providers.runpod.wiring import billing_name, bind_scene, sync_take_quality
from app.services import append_event, utc_now
from app.wording import decimal as ro_decimal


def _at_work(engine: Engine | None, role_name: str, task_type: str, detail: str) -> Any:
    """The employee doing this step shows as WORKING while it runs. Nothing for placeholders."""
    if engine is None:
        return nullcontext()
    from app.agents.services import at_work  # noqa: PLC0415 - agents imports media models

    return at_work(engine, role_name, task_type, detail)


logger = logging.getLogger("studio.assembler")

DEFAULT_STORAGE_ROOT = ROOT / "backend" / "storage" / "media"


def media_root(settings: Any = None) -> Path:
    """The folder films are written to: the Owner's STUDIO_MEDIA_ROOT when the settings carry
    one, else `DEFAULT_STORAGE_ROOT` (read at call time). Every entry below that is handed
    no ``storage_root`` but the settings resolves its folder here (REL-08)."""
    from app.media.disk import media_root as configured_root  # noqa: PLC0415

    return configured_root(settings)


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
#: A scene lasts its words plus this breath, never past its plan, never cutting a word. Every
#: speaking scene keeps it whole: quality control allows the narration, this breath per
#: speaking scene, the silent cards and 1.0 s (qc.film_length_budget, which reads it from
#: production['timeline']['spoken_tail_seconds']). Until 2026-10-01 the breaths were shrunk
#: together to keep the film within 0.9 s of its words, and six scenes kept about 0.11 s each.
#: It was 0.35 s on top of the vendor's own trailing silence, never trimmed: the rehearsal film
#: measured 0.28-0.61 s of digital silence at every cut (audit Q4). Since 2026-10-02 each take's
#: silent edges are cut first (`_trimmed_take`, -45 dB, keeping EDGE_KEEP_SECONDS either side)
#: and the breath was 0.12 s, so a cut carried at most about 0.22 s with the frame rounding.
#: 2026-10-16, the Owner («de ce se taie cadrul? de ce nu-l lăsăm complet?»): every shot
#: breathes 0.4 s after its words, so its movement ends before the cut; the clip is bought
#: for it (`_voiced_clip_seconds`) and quality control counts it (`qc.film_length_budget`).
SPOKEN_TAIL_SECONDS = 0.4

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


def concat_line(path: str | Path) -> str:
    """One ``file`` line of an FFmpeg concat list (SEC-09). Inside single quotes nothing can be
    escaped, so a quote in the path is written as ``'\\''``: close the quotes, an escaped
    quote, open them again. A buyer's folder named O'Brien used to break the list and the film.
    A backslash is taken as it is inside quotes and is left alone; paths are written with
    forward slashes (``as_posix``) anyway."""
    text = path.as_posix() if isinstance(path, Path) else str(path)
    return "file '" + text.replace("'", "'\\''") + "'\n"


def run_encoder(
    command: Sequence[str],
    folder: Path,
    *,
    carry: Sequence[str] = (),
    timeout: float = 600,
) -> subprocess.CompletedProcess[str]:
    """Run an FFmpeg ``command`` for the film in ``folder``, from a short working directory.

    Every input and output of the studio's commands is an absolute path, which FFmpeg opens
    at any depth. Only the working directory is limited: Windows refuses one longer than
    MAX_PATH (260 characters), and measured 2026-10-01 a 258-character film folder given as
    ``cwd`` failed with NotADirectoryError (WinError 267) before the encoder started. So the
    encoder always runs in a fresh, short temporary folder; the few things a filter names
    *relative* to its working directory (the ASS captions and their font folder, whose
    absolute Windows paths would need escaping twice over) are listed in ``carry`` and copied
    there from ``folder`` first. The folder is removed afterwards.

    A launch that fails (OSError) or an encoder past ``timeout`` raises
    RenderEngineUnavailable with a Romanian reason, which the routes answer as 503.
    """
    staging = Path(tempfile.mkdtemp(prefix="amn_ff_"))
    try:
        for name in carry:
            source = folder / name
            if source.is_dir():
                shutil.copytree(source, staging / name)
            elif source.is_file():
                shutil.copy2(source, staging / name)
        return subprocess.run(  # noqa: S603 - argument list, no shell
            list(command),
            cwd=str(staging),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderEngineUnavailable(
            f"FFmpeg nu a terminat în {timeout:g} secunde și a fost oprit; filmul nu a fost "
            "înregistrat."
        ) from exc
    except OSError as exc:
        raise RenderEngineUnavailable(
            f"FFmpeg nu a putut porni ({type(exc).__name__}: {exc}); filmul nu a fost înregistrat."
        ) from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)


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
#: The same stop when the studio is closing instead (a restart; `shutdown_requested`): the
#: scenes made stay on disk and the render goes on after the restart.
RENDER_SHUTDOWN_REASON = (
    "Randarea s-a oprit între scene: studioul se închide (repornire). Scenele deja făcute "
    "rămân pe disc; randarea continuă după repornire."
)
#: What the motion step says when `stop_requested` ends it between two shots: his switch, or
#: the studio's closing. On 2026-10-12 at 00:03 the serial's step said «Proprietarul a oprit
#: autonomia» during a restart, with his switch off.
MOTION_STOP_REASON = "Proprietarul a oprit autonomia; nu se mai cumpără mișcare."
MOTION_SHUTDOWN_REASON = (
    "Studioul se închide (repornire); mișcarea rămasă se cumpără după repornire."
)


def motion_stop_reason(engine: Engine) -> str:
    """The motion step's words for a stop `stop_requested` asked for."""
    from app.runbook.services import shutdown_requested  # noqa: PLC0415 - runbook imports media

    return MOTION_SHUTDOWN_REASON if shutdown_requested(engine) else MOTION_STOP_REASON


def render_stop_reason(engine: Engine) -> str:
    """The render job's words for a stop `stop_requested` asked for."""
    from app.runbook.services import shutdown_requested  # noqa: PLC0415 - runbook imports media

    return RENDER_SHUTDOWN_REASON if shutdown_requested(engine) else STOP_REASON


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
#: ASS sizes a font by its line cell, not its em: 66 was Inter Bold at an em of about 54.5 px.
#: 74 since 2026-10-02 (audit Q7): a card of two to five words reads at a glance at this
#: size, and two lines of it still end at y 1500 (cards.CAPTION_BAND_TOP stays clear).
CAPTION_FONT_SIZE = 74
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


def _release_dangling(card: list[str]) -> tuple[list[str], list[str]]:
    """A full card split before the function words it would end on: (kept, carried). The
    carried words open the next card, so "Nepal is paying for a" becomes "Nepal is paying"
    and the next card starts "for a crisis". A card never shrinks below two words for it."""
    kept = list(card)
    carried: list[str] = []
    while len(kept) > CAPTION_MIN_WORDS and dangles(kept[-1]):
        carried.insert(0, kept.pop())
    return kept, carried


def _mend_dangling(groups: list[list[str]]) -> list[list[str]]:
    """The last pass over a passage's cards: a card (but the last) that still ends on a
    function word gives it to the next card, as long as that card still fits two lines and
    stays a card a glance can read (CAPTION_MAX_WORDS plus two)."""
    for position in range(len(groups) - 1):
        card, following = groups[position], groups[position + 1]
        while len(card) > 1 and dangles(card[-1]):
            moved = [card[-1], *following]
            if len(moved) > CAPTION_MAX_WORDS + 2 or _card_lines(moved) is None:
                break
            following.insert(0, card.pop())
    return [group for group in groups if group]


def caption_cards(words: list[str]) -> list[list[str]]:
    """A passage's words as caption cards of two to five words.

    The cut is chosen whole by _segmented_cards; the greedy rules below are its fallback.
    A card ends at a sentence's end once it has two words, at a clause's end once it has
    three, at five words, or before a word that would not fit two lines. A last word is never
    left alone: it joins the card before it, or takes that card's last word with it. A card
    never ends on a function word (editorial.FUNCTION_WORDS, English and Romanian): the
    rehearsal's "Nepal is paying for a" / "crisis it did not create." broke both phrases, so
    the function words move on and open the next card (audit Q7).
    """
    groups: list[list[str]] = []
    current: list[str] = []
    for position, word in enumerate(words):
        if len(current) >= CAPTION_MIN_WORDS and _card_lines([*current, word]) is None:
            kept, current = _release_dangling(current)
            groups.append(kept)
        current.append(word)
        left = len(words) - position - 1
        full = len(current) >= CAPTION_MAX_WORDS
        sentence = len(current) >= CAPTION_MIN_WORDS and _ends_with(word, _SENTENCE_MARKS)
        clause = len(current) >= CAPTION_MIN_WORDS + 1 and _ends_with(word, _CLAUSE_MARKS)
        if full or sentence or clause:
            if left == 1 and not full and _card_lines([*current, words[-1]]) is not None:
                continue  # the passage's last word joins this card instead of standing alone
            kept, current = _release_dangling(current)
            groups.append(kept)
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
    if len(words) >= CAPTION_MIN_WORDS:
        # The passage is cut whole (2026-10-02): the greedy walk below, mending function
        # words afterwards, could leave a word alone ("Right,") or make a six-word card,
        # breaking the two-to-five contract the render records. The walk stays as the
        # fallback for a passage no cut of two to five words can set (a word too long).
        chosen = _segmented_cards(words)
        if chosen is not None:
            return chosen
    return _mend_dangling(groups)


def _segmented_cards(words: list[str]) -> list[list[str]] | None:
    """A passage cut into cards of two to five words that each fit two lines, chosen whole:
    the fewest cards ending on a function word first, then cards ending at a sentence or a
    clause, then cards near four words. None when no such cut exists (a word too long)."""
    count = len(words)
    best: list[tuple[float, int] | None] = [None] * (count + 1)
    best[0] = (0.0, -1)
    for end in range(1, count + 1):
        for size in range(CAPTION_MIN_WORDS, CAPTION_MAX_WORDS + 1):
            start = end - size
            if start < 0 or best[start] is None:
                continue
            card = words[start:end]
            if _card_lines(card) is None:
                continue
            last = card[-1]
            cost = abs(size - 4) * 0.2
            if end < count:
                if dangles(last):
                    cost += 10.0
                elif not (_ends_with(last, _SENTENCE_MARKS) or _ends_with(last, _CLAUSE_MARKS)):
                    cost += 1.0
            total = best[start][0] + cost  # type: ignore[index]
            if best[end] is None or total < best[end][0]:  # type: ignore[index]
                best[end] = (total, start)
    if best[count] is None:
        return None
    cards: list[list[str]] = []
    end = count
    while end > 0:
        start = best[end][1]  # type: ignore[index]
        cards.insert(0, words[start:end])
        end = start
    return cards


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


def _shift_times(values: Any, by: float, limit: float) -> Any:
    """A list of seconds moved ``by`` earlier, held inside [0, limit]; anything else as it is."""
    if not isinstance(values, list):
        return values
    return [
        round(min(limit, max(0.0, float(v) - by)), 4)
        if isinstance(v, int | float) and not isinstance(v, bool)
        else v
        for v in values
    ]


def _trimmed_take(
    ffmpeg_exe: str, said: TTSResult, work_dir: Path, name: str
) -> tuple[TTSResult, dict[str, Any]]:
    """The take with the vendor's silence before and after its words cut away (audit Q4).

    The take is decoded to a 48 kHz, 24-bit mono WAV (``name``.wav in ``work_dir``), its
    silent edges measured (`toolchain.speech_edges`: under -45 dB for 50 ms), and all but
    EDGE_KEEP_SECONDS of each cut, never into a word the vendor timed. Its word timing and
    the vendor's character alignment move earlier by what was cut from the front, so the
    captions stay on the words. The vendor's own file, kept as the narration take, is not
    touched: this is done again, for nothing, every time the take is used. A take that cannot
    be decoded or measured is returned as it came, and the record says why.
    """
    import wave  # noqa: PLC0415

    record: dict[str, Any] = {
        "lead_seconds": 0.0,
        "trail_seconds": 0.0,
        "seconds": round(float(said.duration_seconds), 3),
    }
    source = work_dir / f"{name}_vendor.{str(said.format or 'bin')[:10]}"
    decoded = work_dir / f"{name}.wav"
    try:
        source.write_bytes(said.audio_bytes)
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [
                ffmpeg_exe,
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-i",
                str(source),
                "-vn",
                *_VOICE_WAV_ARGS,
                str(decoded),
            ],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=300,
            check=False,
        )
        if result.returncode != 0 or not decoded.is_file():
            record["error"] = f"the take could not be decoded (exit code {result.returncode})"
            return said, record
        with wave.open(str(decoded), "rb") as audio:
            params = audio.getparams()
            frames = audio.readframes(params.nframes)
        rate = params.framerate
        duration = params.nframes / rate if rate else 0.0
        lead, trail = speech_edges(ffmpeg_exe, decoded, duration)
    except (OSError, subprocess.SubprocessError, wave.Error, EOFError) as exc:
        record["error"] = f"the take could not be measured ({type(exc).__name__})"
        return said, record
    finally:
        source.unlink(missing_ok=True)
    cut_lead = max(0.0, lead - EDGE_KEEP_SECONDS)
    cut_trail = max(0.0, trail - EDGE_KEEP_SECONDS)
    words = take_word_timing(said)
    if words:
        # The vendor's clock wins over the meter: a word it timed is never cut.
        cut_lead = min(cut_lead, max(0.0, min(float(w["start"]) for w in words)))
        cut_trail = min(cut_trail, max(0.0, duration - max(float(w["end"]) for w in words)))
    first = int(round(cut_lead * rate))
    last = max(first + 1, params.nframes - int(round(cut_trail * rate)))
    step = params.sampwidth * params.nchannels
    kept = frames[first * step : last * step]
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(params.nchannels)
        out.setsampwidth(params.sampwidth)
        out.setframerate(rate)
        out.writeframes(kept)
    seconds = (last - first) / rate
    shift = first / rate
    record.update(
        lead_seconds=round(shift, 3),
        trail_seconds=round((params.nframes - last) / rate, 3),
        seconds=round(seconds, 3),
        measured_lead_seconds=round(lead, 3),
        measured_trail_seconds=round(trail, 3),
    )
    raw = copy.deepcopy(said.raw_response) if isinstance(said.raw_response, dict) else {}
    for key in ("alignment", "normalized_alignment"):
        timing = raw.get(key)
        if isinstance(timing, dict):
            for field_name in ("character_start_times_seconds", "character_end_times_seconds"):
                timing[field_name] = _shift_times(timing.get(field_name), shift, seconds)
    raw["trimmed"] = dict(record)
    timings = [
        {
            **item,
            "start": _shift_times([item["start"]], shift, seconds)[0],
            "end": _shift_times([item["end"]], shift, seconds)[0],
        }
        if isinstance(item, dict) and "start" in item and "end" in item
        else item
        for item in (said.word_timings or [])
    ]
    # The trimmed take travels in memory to the voice join; the decoded copy is not kept.
    decoded.unlink(missing_ok=True)
    return (
        TTSResult(
            audio_bytes=buffer.getvalue(),
            format="wav",
            duration_seconds=seconds,
            sample_rate=rate,
            word_timings=timings,
            cost_vr=said.cost_vr,
            raw_response=raw,
        ),
        record,
    )


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
        position = 0
        for index, group in enumerate(groups):
            start = max(begin + firsts[index], previous_end)
            end = begin + (firsts[index + 1] if index + 1 < len(groups) else span)
            # A card is up for at least a frame, and never past the passage.
            end = min(max(end, start + 1 / TIMELINE_FPS), begin + span)
            first_word = position
            position += len(group)
            if end <= start:
                continue
            # Each word is lit from its own start to the next word's (the last to the card's
            # end), so the highlight follows the voice without gaps (audit Q7).
            spoken = [
                {
                    "word": word,
                    "start": min(max(begin + starts[first_word + offset], start), end),
                    "end": min(
                        max(
                            begin + starts[first_word + offset + 1]
                            if offset + 1 < len(group)
                            else end,
                            start,
                        ),
                        end,
                    ),
                }
                for offset, word in enumerate(group)
            ]
            cues.append(_cue(scene_index, start, end, group, "alignment", spoken))
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
        # Without the voice's timing the words share the card by their characters too.
        total_chars = float(sum(len(word) + 1 for word in group)) or 1.0
        shared: list[dict[str, Any]] = []
        clock = start
        for word in group:
            share = (end - start) * (len(word) + 1) / total_chars
            shared.append({"word": word, "start": clock, "end": min(clock + share, end)})
            clock += share
        cues.append(_cue(scene_index, start, end, group, "character_share", shared))
        start = end
    return cues


def _cue(
    scene_index: Any,
    start: float,
    end: float,
    words: list[str],
    timing: str,
    spoken: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    lines = _card_lines(words) or _wrap_words(words, CAPTION_LINE_CHARS)[:CAPTION_MAX_LINES]
    cue: dict[str, Any] = {
        "scene_index": scene_index,
        "start": start,
        "end": end,
        "lines": lines,
        "timing": timing,
    }
    # The words as they are lit (start and end in film seconds), when the lines carry
    # exactly these words: a word cut across lines by _wrap_words is not highlighted.
    if spoken is not None and " ".join(lines).split() == [w["word"] for w in spoken]:
        cue["words"] = [
            {
                "word": w["word"],
                "start": round(float(w["start"]), 4),
                "end": round(float(w["end"]), 4),
            }
            for w in spoken
        ]
    return cue


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


#: Numbers on screen: digits, with the marks a figure carries ("83", "1.000", "41%", "$100").
_NUMBER_WORD = re.compile(r"\d")
#: The headline's place: top-centred, its first line at about y 420 (inside SAFE_RECT).
HEADLINE_MARGIN_V = 420
HEADLINE_FONT_SIZE = 84


def ass_colour(hex_colour: str, alpha: float = 0.0) -> str:
    """'#RRGGBB' as an ASS colour (&HAABBGGRR, alpha 0 opaque .. 255 clear)."""
    red, green, blue = hex_colour[1:3], hex_colour[3:5], hex_colour[5:7]
    transparency = max(0, min(255, round(255 * float(alpha))))
    return f"&H{transparency:02X}{blue}{green}{red}".upper()


def _override_colour(hex_colour: str) -> str:
    """'#RRGGBB' as the colour of an override tag (&HBBGGRR&)."""
    return f"&H{hex_colour[5:7]}{hex_colour[3:5]}{hex_colour[1:3]}&".upper()


def _highlighted(cue: dict[str, Any], captions: dict[str, Any]) -> str | None:
    """The card's text with each word lit while it is spoken and numbers in their own colour,
    as ASS override tags; None when the cue carries no word times (the plain text is used)."""
    spoken = cue.get("words")
    if not isinstance(spoken, list) or not spoken:
        return None
    text_colour = _override_colour(captions["text"])
    active = _override_colour(captions["active"])
    emphasis = _override_colour(captions["emphasis"])
    begin = float(cue["start"])
    remaining = list(spoken)
    rendered_lines: list[str] = []
    for line in cue["lines"]:
        pieces: list[str] = []
        for _word in line.split():
            entry = remaining.pop(0)
            word = str(entry["word"])
            base = (
                emphasis
                if captions.get("emphasis_numbers") and _NUMBER_WORD.search(word)
                else text_colour
            )
            tags = f"\\1c{base}"
            if captions.get("highlight_active_word"):
                on = max(0, round((float(entry["start"]) - begin) * 1000))
                off = max(on + 1, round((float(entry["end"]) - begin) * 1000))
                tags += f"\\t({on},{on + 1},\\1c{active})\\t({off},{off + 1},\\1c{base})"
            pieces.append(f"{{{tags}}}{_ass_text(word)}")
        rendered_lines.append(" ".join(pieces))
    return "\\N".join(rendered_lines)


def ass_from_cues(
    cues: list[dict[str, Any]],
    *,
    finish: dict[str, Any] | None = None,
    headline: str | None = None,
) -> str:
    """The burnt captions as an ASS script at 1080x1920: Inter Bold at size 74, a 3.5 px dark
    outline and a soft shadow, bottom-centred inside the safe area. The word being spoken is
    lit in the finish's active colour, timed from the voice's own word timing, and numbers
    carry the emphasis colour (audit Q7); the colours are the Owner's look setting
    (``finish``: cards.film_finish). A card whose longest line would not fit is set smaller
    for that card alone, never below 40, never outside the margins. ``headline`` is the hook,
    written at the top for its first seconds when the finish shows it (off by default)."""
    from app.media import cards  # noqa: PLC0415

    finish = finish or film_finish()
    captions = finish["captions"]
    family = cards.font_family(cards.BOLD)
    width, height = CAPTION_PLAY_RES
    shadow_px = float(captions["shadow_px"])
    back = ass_colour(captions["shadow"], 1.0 - float(captions["shadow_opacity"]))
    show_headline = bool(headline and str(headline).strip() and finish["headline"]["show"])
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
        f"Style: Caption,{family},{CAPTION_FONT_SIZE},{ass_colour(captions['text'])},"
        f"{ass_colour(captions['active'])},{ass_colour(captions['outline'])},{back},"
        f"-1,0,0,0,100,100,0,0,1,{CAPTION_OUTLINE:g},{shadow_px:g},2,{CAPTION_MARGIN_X},"
        f"{CAPTION_MARGIN_X},{CAPTION_MARGIN_V},1",
    ]
    if show_headline:
        lines.append(
            f"Style: Headline,{family},{HEADLINE_FONT_SIZE},{ass_colour(captions['text'])},"
            f"{ass_colour(captions['active'])},{ass_colour(captions['outline'])},{back},"
            f"-1,0,0,0,100,100,0,0,1,{CAPTION_OUTLINE:g},{shadow_px:g},8,{CAPTION_MARGIN_X},"
            f"{CAPTION_MARGIN_X},{HEADLINE_MARGIN_V},1"
        )
    lines += [
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if show_headline:
        seconds = float(finish["headline"]["seconds"])
        words = " ".join(str(headline).split()).split()
        text = "\\N".join(_ass_text(line) for line in _wrap_words(words, 26)[:3])
        lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(seconds)},Headline,,0,0,0,,{text}")
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
        text = _highlighted(cue, captions) or "\\N".join(_ass_text(line) for line in cue["lines"])
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
    listing.write_text("".join(concat_line(segment) for segment in segments), encoding="utf-8")
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
    prompt_text: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Ask the scene's model for its shot, and wait for the clip.

    With a still, the still is the first frame, so the picture the Director approved is the
    picture that moves — that is production. Without one the model films from the scene's
    words, which is what a test does on the cheapest model. A task that has not finished by
    the deadline raises; nothing invents a shot. ``seed`` is the film's one seed (the adapter
    sends it where the contract declares it); ``on_submitted`` hears the task id once the
    vendor has accepted the request, which is when a shot starts to cost money, and before
    any poll, so the caller can write the task down first.
    ``prompt_text`` replaces the scene's motion prompt (clip QC's one retry asks the camera
    move more firmly); the extras (the negative prompt) stay the scene's.

    From the submit on, the shot exists and may be billed. The vendor's own FAILED is a
    `MotionTaskFailed`; anything else that keeps the clip from arriving (a poll the vendor
    does not answer, the deadline, a failed download) is `TaskStillOpen`: the task is
    collected later by its id, never bought again.
    """
    prompt, extra = motion_request(adapter, scene, from_still=still is not None)
    if prompt_text:
        prompt = prompt_text
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
    try:
        return _await_motion(adapter, str(job_id))
    except MotionTaskFailed:
        raise
    except Exception as exc:  # noqa: BLE001 - every other way the clip did not arrive
        raise TaskStillOpen(
            "the motion task's clip was not collected", task_id=str(job_id)
        ) from exc


class MotionTaskFailed(MediaProviderError):
    """The vendor itself reported the motion task FAILED (or CANCELLED): a refusal, with its
    code. Every other way a submitted clip fails to arrive is `TaskStillOpen`."""


def _await_motion(adapter: VideoProvider, job_id: str) -> tuple[bytes, dict[str, Any]]:
    """Poll a submitted motion task until its clip arrives, the vendor fails it, or the
    deadline passes (raised; `_generate_motion` makes that TaskStillOpen)."""
    deadline = time.monotonic() + getattr(adapter, "timeout_seconds", MOTION_DEADLINE_SECONDS)
    attempts = 0
    while True:
        try:
            result = asyncio.run(adapter.get_generation_status(job_id))
        except MediaProviderError:
            # The shot exists and is paid for; a failed download is worth a second attempt
            # before it is left for the collection.
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
            raise MotionTaskFailed(
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


def _video_bit_rate(ffmpeg_exe: str, path: Path) -> int | None:
    """The finished film's average video bitrate as quality control measures it, or None."""
    from app.media.qc import probe_media_file  # noqa: PLC0415

    rate = probe_media_file(path, ffmpeg_exe).get("video_bit_rate")
    return int(rate) if isinstance(rate, int | float) and rate > 0 else None


def _with_crf(args: Sequence[str], crf: int) -> list[str]:
    """The same encoder arguments at another CRF."""
    out = list(args)
    out[out.index("-crf") + 1] = str(int(crf))
    return out


def encode_to_floor(
    ffmpeg_exe: str,
    command_args: Sequence[str],
    work_dir: Path,
    output_mp4: Path,
    *,
    carry: Sequence[str] = (),
    floor: int | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    """The final encode, made again at each of FLOOR_CRF_STEPS in turn while the film comes
    out under quality control's bitrate floor: the encoder keeps to the floor it is measured
    against, instead of quality control refusing the film and the free re-encode making the
    same file again. Returns the last run and the encode's record (``crf``, ``video_bit_rate``,
    and ``tightened``: every reading that fell short). A failed run is returned as it is."""
    if floor is None:
        from app.media.qc import MIN_VIDEO_BITRATE  # noqa: PLC0415

        floor = int(MIN_VIDEO_BITRATE)
    args = list(command_args)
    crf = int(args[args.index("-crf") + 1]) if "-crf" in args else FINAL_CRF
    record: dict[str, Any] = {"crf": crf, "video_bit_rate": None, "floor": floor, "tightened": []}
    steps = [step for step in FLOOR_CRF_STEPS if step < crf]
    while True:
        res = run_encoder(args, work_dir, carry=tuple(carry))
        if res.returncode != 0 or not output_mp4.is_file() or output_mp4.stat().st_size == 0:
            return res, record
        rate = _video_bit_rate(ffmpeg_exe, output_mp4)
        record["crf"], record["video_bit_rate"] = crf, rate
        if rate is None or rate >= floor or not steps:
            return res, record
        record["tightened"].append({"crf": crf, "video_bit_rate": rate})
        logger.info(
            "final_encode_under_floor",
            extra={"crf": crf, "video_bit_rate": rate, "floor": floor, "next_crf": steps[0]},
        )
        crf = steps.pop(0)
        args = _with_crf(args, crf)


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
#: A shot is an intermediate, read once by the final encode and by quality control, then
#: deleted (release_intermediates). Lossless x264 (``-qp 0``) was about 16 MB a second at
#: 1080x1920 (139 MB for an 8.6 s still push-in; 1.1 GB a film). Measured 2026-10-01 on the
#: Nepal stills and clips, x264 High at CRF 4 (veryfast, its default B-frames) is half that
#: (7.7 MB/s for the push-in, 4.7-5.9 for the vendor clips, 0.06 for a card) at 51.6-54.4 dB
#: against the lossless shot, and the CRF 17 film made from it is within 0.55 dB PSNR and
#: 0.25 VMAF of the film made from lossless shots. CRF 6 lost one repeated frame in 77 to
#: quality control's duplicate count; without B-frames or at a fixed QP the files were larger
#: and the repeats of a still push-in read 0.05-0.08. A repeated frame reads at most 0.013
#: here and the slowest real Nepal clip 0.097 (qc.LOSSLESS_DUPLICATE_YDIF = 0.03).
INTERMEDIATE_VIDEO_ARGS: tuple[str, ...] = (
    "-c:v",
    "libx264",
    "-profile:v",
    "high",
    "-preset",
    "veryfast",
    "-crf",
    "4",
    "-pix_fmt",
    "yuv420p",
    *_COLOUR_FLAGS,
)


#: The finished film's quality setting, and the tighter ones tried in turn when the encode
#: comes out under quality control's bitrate floor (`qc.MIN_VIDEO_BITRATE`, 6 Mbps). A film
#: of dark, nearly still picture at 24 fps needs few bits at CRF 17 (2026-10-16 05:35Z,
#: 7c26a7ce «Speed of Light»: 4.4 Mbps, quality control failed the film for it, and the free
#: re-encode from the same takes could only have made the same file again). More bits into a
#: dark picture are not wasted: its gradients keep more steps.
FINAL_CRF = 17
FLOOR_CRF_STEPS: tuple[int, ...] = (12, 8, 4)


def final_video_args(fps: int = TIMELINE_FPS, crf: int = FINAL_CRF) -> list[str]:
    """The finished film's video encode, in full.

    H.264 High at level 4.2 (1080x1920 at up to 60 fps), CRF 17 on the slow preset with a
    14 Mbps ceiling over a 28 Mbit buffer — what a phone screen needs for detailed, moving
    picture; the Nepal film had 2.6 Mbps. Two B-frames, a keyframe every half second and no
    scene-cut keyframes, so the platform's re-encode finds a regular GOP. 4:2:0, BT.709
    limited range, and the index at the front of the file so playback starts at once.
    ``crf`` is tightened by `encode_to_floor` when the film comes out under the floor.
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
        str(int(crf)),
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
    planned: Sequence[float],
    spoken: Sequence[float | None],
    *,
    fps: int = TIMELINE_FPS,
    kinds: Sequence[str | None] | None = None,
) -> list[float]:
    """How long each scene lasts on the timeline, on whole frames.

    A scene with words lasts spoken + SPOKEN_TAIL_SECONDS, whatever its plan said: a word
    is never cut, and the breath after the last word is the shot's (2026-10-16, the Owner:
    the clip used to be cut the moment the words ended, when the plan ran short, and the
    movement never finished). Every speaking scene keeps its whole breath, rounded up to a
    frame: quality control counts the breaths (qc.film_length_budget), and the clip was
    bought for it (`_voiced_clip_seconds`). A scene with no words keeps its plan, except a
    silent composed scene (``kinds``: BLACK, TITLE_CARD, DATA_CARD), which lasts at most what
    quality control allows its kind (qc.MAX_SILENT_CARD_SECONDS): one beat of black, a title
    read, a chart's animation.
    """
    from app.media.qc import MAX_SILENT_CARD_SECONDS  # noqa: PLC0415 - qc reads the models

    kinds = list(kinds) if kinds is not None else [None] * len(planned)
    spans: list[float] = []
    for plan, said, kind in zip(planned, spoken, kinds, strict=True):
        if isinstance(said, int | float) and float(said) > 0:
            spans.append(whole_frames(float(said) + SPOKEN_TAIL_SECONDS, fps, up=True))
        elif kind in MAX_SILENT_CARD_SECONDS:
            spans.append(whole_frames(min(float(plan), MAX_SILENT_CARD_SECONDS[kind]), fps))
        else:
            spans.append(whole_frames(float(plan), fps))
    return spans


def _dither_chain(dither: bool) -> str:
    """A vendor clip down to 8 bits: error-diffusion dither (zimg) for a 10-bit source such as
    the Nepal motion_01; an 8-bit source passes through it unchanged. Without zscale in the
    build, swscale's own ordered dither does it."""
    return "zscale=dither=error_diffusion,format=yuv420p," if dither else "format=yuv420p,"


# 2026-10-09 (film babcf272, the Owner's «Încetinește local»): a clip shorter than its shot by
# at most SLOWDOWN_ALLOWANCE is slowed down locally to fill it, 0 USD, never held on a frozen
# frame; beyond that the scene is refused and its motion redone at the right length (see
# `clip_readiness`). Measured on babcf272's own 5.0 s motion_01 slowed to a 5.9 s span
# (2026-10-10, this machine): repeating frames (setpts + fps) left 23 of 142 frames identical
# to the one before, a stutter quality control counts as duplicates; frame blending
# (framerate) left none but ghosted the edges of the walking figure; motion-compensated
# interpolation (minterpolate, mci) left none, kept the edges, and took 13 s for the shot.

# How much longer than its clip a shot may be and still be filled by slowing the clip down
# (a 5.0 s clip covers a span of up to 6.25 s) is SLOWDOWN_ALLOWANCE, imported from
# `cost_plan`: the planner prices a scene longer than its model's longest clip at that clip
# when this slow-down fills it (2026-10-10), so both read one number.

#: Frames asked of the interpolation beyond the span: at the exact factor it delivered 140 and
#: 141 of the 142 frames needed (2026-10-10); the trim then cuts the span exactly.
SLOWDOWN_EXTRA_FRAMES = 2
#: How a slowed clip's new frames are made, best first; framerate is in every ffmpeg build.
SLOWDOWN_FILTERS: tuple[str, ...] = ("minterpolate", "framerate")


def slowdown_filter(ffmpeg_exe: str | None) -> str | None:
    """The best interpolation this encoder has for a slowed clip, or None (no encoder)."""
    return next((name for name in SLOWDOWN_FILTERS if has_filter(ffmpeg_exe, name)), None)


def _slow_chain(factor: float, fps: int, interpolate: str) -> str:
    """A clip played ``factor`` times slower, its missing frames made by ``interpolate``
    (motion-compensated, or blended) on the ``fps`` timeline: never a repeated frame."""
    if interpolate == "minterpolate":
        fill = f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
    else:
        fill = f"framerate=fps={fps}"
    return f"setpts=PTS*{factor:.6f},{fill},"


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
    slow: float = 1.0,
    interpolate: str = "minterpolate",
) -> list[str]:
    """One scene as one file, exactly ``span`` long on the ``fps`` timeline: the generated clip
    trimmed to its span, or the still pushed in.

    A clip that covers its span is cut. ``slow`` (> 1) is a clip shorter than its span by at
    most SLOWDOWN_ALLOWANCE, played that much slower with its new frames interpolated
    (``interpolate``: minterpolate or framerate), so it fills the span without a frozen frame
    (the Owner, 2026-10-09). ``hold`` is kept only to cut again, as they were cut, the shots of
    films made before that rule: their last frame was held that long. A shot is built and
    measured on its own because a single filter graph over eight inputs hid its own failure:
    the first dissolve render wrote six seconds of picture under forty-six seconds of audio
    and reported success.
    """
    frames = max(1, round(span * fps))
    if clip is not None:
        held = f"tpad=stop_mode=clone:stop_duration={hold:.6f}," if hold > 0 else ""
        slowed = _slow_chain(slow, fps, interpolate) if slow > 1.0 else ""
        return [
            ffmpeg_exe,
            "-nostdin",
            "-y",
            "-i",
            str(clip),
            "-an",
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920,"
            f"setsar=1,fps={fps},{_dither_chain(dither)}{slowed}{held}trim=end_frame={frames},"
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


def _shot_source(
    *,
    still: Path | None,
    clip: Path | None,
    card: bool,
    hold: float,
    dither: bool,
    fps: int,
    slow: float = 1.0,
    interpolate: str | None = None,
) -> dict[str, Any]:
    """What a shot was cut from, so it can be cut again once its file is gone
    (release_intermediates): the still or the vendor clip with their sha256, or ``card`` for a
    composed card (recomposed from its own spec), and how it was cut (hold, dither, fps, and
    the slow-down that filled its span, with its interpolation)."""
    return {
        "card": bool(card),
        "still": str(still) if still is not None else None,
        "still_sha256": _file_sha256(still) if still is not None else None,
        "clip": str(clip) if clip is not None else None,
        "clip_sha256": _file_sha256(clip) if clip is not None else None,
        "hold": round(float(hold), 6),
        "slow": round(float(slow), 6),
        "interpolate": interpolate if slow > 1.0 else None,
        "dither": bool(dither),
        "fps": int(fps),
    }


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
    framings: Sequence[dict[str, Any] | None] | None = None,
    grades: Sequence[str | None] | None = None,
    grain: int = 0,
    lut: str | None = None,
) -> list[str]:
    """One ffmpeg call over the shot files: the film's edit.

    Shots join by a hard cut (concat), and by a dissolve (xfade) only where the scene's
    ``transition_in`` asks (scene_joins). A dissolve starts where the scene's words start
    and consumes the overlap its shot before was built with, so shot N always starts where
    scene N's words start — the picture never drifts away from the voice. ``audio_filter`` is
    an audio chain to encode the track with, or None when ``audio_file`` is the mastered
    track, which is then copied in untouched; ``captions`` is the subtitles filter to burn in
    after the edit, or None to leave the picture clean.

    ``grades`` is each shot's grade (a lutyuv toward the hero, film_grade) and ``framings``
    each shot's second framing (plan_second_framings): the shot is cut at ``at`` seconds to a
    punch-in of itself. ``lut`` (a .cube named relative to the working directory) and
    ``grain`` are the finish's film-wide look. Without them the edit is exactly what it was.
    """
    args = [ffmpeg_exe, "-nostdin", "-y"]
    for shot in shots:
        args += ["-i", str(shot)]
    args += ["-i", str(audio_file)]

    joins = scene_joins(scenes_data)
    # Every shot on one clock first: a time base of one frame, so a cut (concat) and a
    # dissolve (xfade, which refuses inputs on different time bases) join the same frames.
    chain = ""
    for index in range(len(shots)):
        grade = grades[index] if grades is not None and index < len(grades) else None
        framing = framings[index] if framings is not None and index < len(framings) else None
        head = f"[{index}:v]fps={fps},settb=1/{fps},setpts=N" + (f",{grade}" if grade else "")
        if not framing:
            chain += f"{head}[s{index}];"
            continue
        cut = max(1, round(float(framing["at"]) * fps))
        x, y, width, height = (int(value) for value in framing["crop"])
        chain += (
            f"{head},split=2[w{index}][c{index}];"
            f"[w{index}]trim=end_frame={cut},setpts=N[wa{index}];"
            f"[c{index}]trim=start_frame={cut},setpts=N,crop={width}:{height}:{x}:{y},"
            f"scale={SHOT_WIDTH}:{SHOT_HEIGHT}:flags=lanczos,setsar=1[ca{index}];"
            f"[wa{index}][ca{index}]concat=n=2:v=1:a=0,settb=1/{fps},setpts=N[s{index}];"
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
    look = f",lut3d=file={lut}:interp=tetrahedral" if lut else ""
    look += f",noise=alls={int(grain)}:allf=t" if grain and int(grain) > 0 else ""
    tail = f"fps={fps},trim=end_frame={frames},setpts=PTS-STARTPTS{look}{burn},{TO_BT709_TV}[vout]"
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


# --------------------------------------------------------------------------- one look
# Audit Q8 (2026-10-02). Every shot used to pass through nothing but the BT.709 conversion, so
# the image model's stills and the motion model's clips were joined as they came: the Nepal
# stills jumped between a cold storm blue, saturated orange mud and a sunny sky. The film is
# now graded toward its hero (the first filmed scene, the hook): each other filmed shot is
# measured (signalstats) and pulled part of the way toward the hero's luma levels, colour
# balance and saturation by one lutyuv, inside the final edit. 0 credits, nothing bought, and
# the distance before and after (Delta E 1976 on the mean colour) is recorded for QC.

#: The keys of a picture's measurement (8-bit limited range: Y 16-235, U and V around 128).
PICTURE_KEYS: tuple[str, ...] = ("y_low", "y_high", "y_avg", "u_avg", "v_avg", "sat_avg")
_SIGNALSTATS = {
    "YLOW": "y_low",
    "YHIGH": "y_high",
    "YAVG": "y_avg",
    "UAVG": "u_avg",
    "VAVG": "v_avg",
    "SATAVG": "sat_avg",
}
#: How far the grade may move a shot: luma gain, saturation and the chroma shift in 8-bit
#: units. A shot further than this from the hero is pulled as far as this, and QC names it.
GRADE_GAIN_RANGE = (0.8, 1.25)
GRADE_SATURATION_RANGE = (0.75, 1.25)
GRADE_MAX_CHROMA_SHIFT = 6.0
GRADE_DEFAULT_STRENGTH = 0.6
#: A shot whose correction would be smaller than this is left as it is.
_GRADE_NEGLIGIBLE = {"gain": 0.01, "offset": 0.5, "saturation": 0.01, "shift": 0.5}


def measure_picture(
    ffmpeg_exe: str | None, path: Path, *, every: int = 12
) -> dict[str, float] | None:
    """A picture's (or a shot's) luma levels, mean chroma and saturation, from signalstats on
    every ``every``-th frame at 270 px, averaged. None when it cannot be read."""
    if not ffmpeg_exe or not Path(path).is_file():
        return None
    try:
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [
                ffmpeg_exe,
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(path),
                "-an",
                "-vf",
                f"select='not(mod(n\\,{max(1, int(every))}))',scale=270:-2:flags=area,"
                "format=yuv420p,signalstats,metadata=print:file=-",
                "-fps_mode",
                "passthrough",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sums = dict.fromkeys(PICTURE_KEYS, 0.0)
    counts = dict.fromkeys(PICTURE_KEYS, 0)
    for line in (result.stdout or "").splitlines():
        key, _, value = line.strip().partition("=")
        name = _SIGNALSTATS.get(key.removeprefix("lavfi.signalstats."))
        if name is None:
            continue
        try:
            sums[name] += float(value)
            counts[name] += 1
        except ValueError:
            continue
    if not all(counts.values()):
        return None
    return {key: round(sums[key] / counts[key], 3) for key in PICTURE_KEYS}


def _lab(stats: dict[str, float]) -> tuple[float, float, float]:
    """The mean colour (Y, U, V in BT.709 limited range) as CIE L*a*b* (D65)."""
    y = (float(stats["y_avg"]) - 16.0) / 219.0
    cb = (float(stats["u_avg"]) - 128.0) / 224.0
    cr = (float(stats["v_avg"]) - 128.0) / 224.0
    rgb = (
        y + 1.5748 * cr,
        y - 0.1873 * cb - 0.4681 * cr,
        y + 1.8556 * cb,
    )

    def linear(value: float) -> float:
        value = min(1.0, max(0.0, value))
        return value / 4.5 if value < 0.081 else ((value + 0.099) / 1.099) ** (1 / 0.45)

    r, g, b = (linear(c) for c in rgb)
    x = 0.4124 * r + 0.3576 * g + 0.1805 * b
    yy = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = 0.0193 * r + 0.1192 * g + 0.9505 * b

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x / 0.95047), f(yy / 1.0), f(z / 1.08883)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(first: dict[str, float], second: dict[str, float]) -> float:
    """Delta E 1976 between two measured pictures' mean colours."""
    a, b = _lab(first), _lab(second)
    return round(math.sqrt(sum((p - q) ** 2 for p, q in zip(a, b, strict=True))), 3)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def grade_toward(
    shot: dict[str, float], hero: dict[str, float], *, strength: float = GRADE_DEFAULT_STRENGTH
) -> dict[str, Any] | None:
    """The correction that pulls ``shot`` part of the way (``strength``) toward ``hero``: a
    luma gain and offset that move its 10th and 90th percentiles, a saturation factor and a
    shift of U and V, each bounded. Returns the lutyuv filter, its parameters and the
    measurement the shot is predicted to have after it; None when nothing needs moving."""
    s = max(0.0, min(1.0, float(strength)))
    low, high = float(shot["y_low"]), float(shot["y_high"])
    want_low = low + s * (float(hero["y_low"]) - low)
    want_high = high + s * (float(hero["y_high"]) - high)
    gain = _clamp((want_high - want_low) / max(high - low, 1.0), *GRADE_GAIN_RANGE)
    offset = want_low - gain * low
    sat = float(shot["sat_avg"])
    saturation = _clamp(
        1.0 + s * (float(hero["sat_avg"]) / sat - 1.0) if sat > 0.5 else 1.0,
        *GRADE_SATURATION_RANGE,
    )

    def shift(key: str) -> float:
        mean = float(shot[key])
        want = mean + s * (float(hero[key]) - mean)
        scaled = (mean - 128.0) * saturation + 128.0
        return _clamp(want - scaled, -GRADE_MAX_CHROMA_SHIFT, GRADE_MAX_CHROMA_SHIFT)

    u_shift, v_shift = shift("u_avg"), shift("v_avg")
    if (
        abs(gain - 1.0) < _GRADE_NEGLIGIBLE["gain"]
        and abs(offset) < _GRADE_NEGLIGIBLE["offset"]
        and abs(saturation - 1.0) < _GRADE_NEGLIGIBLE["saturation"]
        and abs(u_shift) < _GRADE_NEGLIGIBLE["shift"]
        and abs(v_shift) < _GRADE_NEGLIGIBLE["shift"]
    ):
        return None

    def luma(value: float) -> float:
        return _clamp(value * gain + offset, 16.0, 235.0)

    def chroma(value: float, moved: float) -> float:
        return _clamp((value - 128.0) * saturation + 128.0 + moved, 16.0, 240.0)

    predicted = {
        "y_low": round(luma(low), 3),
        "y_high": round(luma(high), 3),
        "y_avg": round(luma(float(shot["y_avg"])), 3),
        "u_avg": round(chroma(float(shot["u_avg"]), u_shift), 3),
        "v_avg": round(chroma(float(shot["v_avg"]), v_shift), 3),
        "sat_avg": round(sat * saturation, 3),
    }
    graph = (
        f"lutyuv=y='clip(val*{gain:.4f}+({offset:.3f})\\,16\\,235)'"
        f":u='clip((val-128)*{saturation:.4f}+128+({u_shift:.3f})\\,16\\,240)'"
        f":v='clip((val-128)*{saturation:.4f}+128+({v_shift:.3f})\\,16\\,240)'"
    )
    return {
        "filter": graph,
        "params": {
            "gain": round(gain, 4),
            "offset": round(offset, 3),
            "saturation": round(saturation, 4),
            "u_shift": round(u_shift, 3),
            "v_shift": round(v_shift, 3),
            "strength": s,
        },
        "predicted": predicted,
    }


def film_grade(
    ffmpeg_exe: str,
    scenes: list[dict[str, Any]],
    shots: list[Path],
    composed: list[bool],
    finish: dict[str, Any],
) -> dict[str, Any]:
    """The film's grade: the hero (its first filmed scene) measured, every other filmed shot
    measured and pulled toward it. Cards keep the studio's own palette. The record names the
    reference, each shot's correction, and the Delta E to the hero before and after."""
    settings = finish["grade"]
    record: dict[str, Any] = {
        "reference_scene": None,
        "reference": None,
        "strength": float(settings["strength"]),
        "lut": settings["lut"],
        "lut_licence": settings["lut_licence"],
        "grain": int(settings["grain"]),
        "shots": [],
        "delta_e_max_before": None,
        "delta_e_max_after": None,
        "applied": False,
    }
    filmed = [i for i, is_card in enumerate(composed) if not is_card]
    if not settings["match_to_hero"] or not filmed:
        record["reason"] = (
            "potrivirea culorii cu eroul este oprită în finish.grade"
            if not settings["match_to_hero"]
            else "filmul nu are scene filmate"
        )
        return record
    hero_position = filmed[0]
    hero = measure_picture(ffmpeg_exe, shots[hero_position])
    if hero is None:
        record["reason"] = "imaginea eroului nu a putut fi măsurată"
        return record
    record["reference_scene"] = int(scenes[hero_position]["scene_index"])
    record["reference"] = hero
    befores: list[float] = []
    afters: list[float] = []
    for position in filmed:
        index = int(scenes[position]["scene_index"])
        if position == hero_position:
            record["shots"].append(
                {"scene_index": index, "filter": None, "delta_e_before": 0.0, "delta_e_after": 0.0}
            )
            continue
        stats = measure_picture(ffmpeg_exe, shots[position])
        if stats is None:
            record["shots"].append({"scene_index": index, "filter": None, "measured": False})
            continue
        grade = grade_toward(stats, hero, strength=record["strength"])
        before = delta_e(stats, hero)
        after = delta_e(grade["predicted"], hero) if grade else before
        befores.append(before)
        afters.append(after)
        record["shots"].append(
            {
                "scene_index": index,
                "filter": grade["filter"] if grade else None,
                "params": grade["params"] if grade else None,
                "measured": stats,
                "predicted": grade["predicted"] if grade else stats,
                "delta_e_before": before,
                "delta_e_after": after,
            }
        )
    record["delta_e_max_before"] = max(befores, default=0.0)
    record["delta_e_max_after"] = max(afters, default=0.0)
    record["applied"] = any(entry.get("filter") for entry in record["shots"])
    return record


def _shot_grade(grade: dict[str, Any] | None, scene_index: int) -> str | None:
    """The grade filter a film recorded for one scene's shot, if any."""
    for entry in (grade or {}).get("shots") or []:
        if isinstance(entry, dict) and entry.get("scene_index") == scene_index:
            value = entry.get("filter")
            return str(value) if value else None
    return None


# --------------------------------------------------------------------------- second framings
# Audit Q6 (2026-10-02): one picture per scene at about five seconds (4.65 s measured on the
# rehearsal) is slow for a short. A scene whose words run past SECOND_FRAMING_MIN_SPOKEN is cut
# in two inside the edit, at a caption card's start near its middle: the same take, the second
# part a 1.15x punch-in centred where the shot plan's ``second_framing`` asks (the frame's
# upper middle otherwise). Nothing is bought; a second paid clip per scene is a later choice.

SECOND_FRAMING_MIN_SPOKEN = 3.2
SECOND_FRAMING_MIN_PART = 1.2
SECOND_FRAMING_ZOOM = 1.15
SECOND_FRAMING_CENTRE = (0.5, 0.45)
#: Every shot of the timeline is this size (1080x1920, 9:16).
SHOT_WIDTH, SHOT_HEIGHT = CAPTION_PLAY_RES


def _framing_centre(scene: dict[str, Any]) -> tuple[list[float], str]:
    package = scene.get("prompt_json")
    asked = package.get("second_framing") if isinstance(package, dict) else None
    if isinstance(asked, dict):
        x, y = asked.get("centre_x"), asked.get("centre_y")
        if isinstance(x, int | float) and isinstance(y, int | float):
            return [float(x), float(y)], "model"
    return list(SECOND_FRAMING_CENTRE), "default"


def framing_crop(centre: Sequence[float], zoom: float) -> list[int]:
    """The punch-in's crop (x, y, width, height) on the 1080x1920 shot, inside the frame."""
    width = int(round(SHOT_WIDTH / zoom / 2) * 2)
    height = int(round(SHOT_HEIGHT / zoom / 2) * 2)
    x = int(round(_clamp(float(centre[0]) * SHOT_WIDTH - width / 2, 0, SHOT_WIDTH - width)))
    y = int(round(_clamp(float(centre[1]) * SHOT_HEIGHT - height / 2, 0, SHOT_HEIGHT - height)))
    return [x, y, width, height]


def plan_second_framings(
    scenes: list[dict[str, Any]],
    cues: list[dict[str, Any]],
    finish: dict[str, Any],
) -> list[dict[str, Any] | None]:
    """For each scene, where its shot cuts to a second framing of the same picture, or None.

    A LIVE scene whose words last more than the finish's ``min_spoken_seconds`` is cut at the
    caption card start closest to its middle, with at least SECOND_FRAMING_MIN_PART seconds
    on each side; a card is never reframed, and a scene with no such card start is left
    whole. ``at`` is seconds from the scene's start."""
    settings = finish["second_framing"]
    framings: list[dict[str, Any] | None] = [None] * len(scenes)
    if not settings["enabled"]:
        return framings
    zoom = float(settings["zoom"])
    clock = 0.0
    for position, scene in enumerate(scenes):
        length = float(scene.get("duration_seconds") or 0.0)
        begin, clock = clock, clock + length
        spoken = scene.get("audio_seconds")
        if (
            is_composed(scene)
            or not isinstance(spoken, int | float)
            or float(spoken) <= float(settings["min_spoken_seconds"])
        ):
            continue
        middle = length / 2
        candidates = [
            float(cue["start"]) - begin
            for cue in cues
            if cue.get("scene_index") == scene.get("scene_index")
            and SECOND_FRAMING_MIN_PART
            <= float(cue["start"]) - begin
            <= length - SECOND_FRAMING_MIN_PART
        ]
        if not candidates:
            continue
        at = min(candidates, key=lambda value: abs(value - middle))
        centre, source = _framing_centre(scene)
        centre = [_clamp(centre[0], 0.0, 1.0), _clamp(centre[1], 0.0, 1.0)]
        framings[position] = {
            "at": round(at, 6),
            "zoom": zoom,
            "centre": centre,
            "source": source,
            "crop": framing_crop(centre, zoom),
        }
    return framings


# --------------------------------------------------------------------------- hook and cover

#: Where a film's LUTs live (the finish's grade.lut names one of them, with its licence).
LUT_FOLDER = ROOT / "config" / "luts"
LUT_NAME = "grade.cube"
COVER_NAME = "cover.png"


def film_hook(engine: Engine, script_draft_id: str | None, scenes: list[dict[str, Any]]) -> str:
    """The film's hook as the script stated it (story_json['hook']), else the first sentence
    the film says. The cover and the optional headline are written from it."""
    if script_draft_id:
        from app.factual.models import ScriptDraft  # noqa: PLC0415 - media reads factual

        with Session(engine) as session:
            script = session.get(ScriptDraft, script_draft_id)
            story = script.story_json if script is not None else None
            hook = story.get("hook") if isinstance(story, dict) else None
            if isinstance(hook, str) and hook.strip():
                return " ".join(hook.split())
    for scene in scenes:
        said = " ".join(str(scene.get("voiceover_segment") or "").split())
        if said:
            match = re.match(r"(.+?[.!?…])(\s|$)", said)
            return match.group(1) if match else said
    return ""


def _install_lut(folder: Path, grade: dict[str, Any]) -> str | None:
    """Copy the finish's LUT (config/luts, with its licence named) beside the film as
    grade.cube, for the edit to read relative to its working directory; None without one."""
    name = grade.get("lut")
    if not name:
        return None
    source = LUT_FOLDER / Path(str(name)).name
    if source.suffix.lower() != ".cube" or not source.is_file():
        grade["lut_missing"] = f"LUT-ul {Path(str(name)).name} nu este în config/luts."
        grade["lut"] = None
        return None
    shutil.copy2(source, folder / LUT_NAME)
    grade["lut_sha256"] = _file_sha256(source)
    return LUT_NAME


def film_cover(
    folder: Path,
    scenes: list[dict[str, Any]],
    frames: list[Path | None],
    card_clips: list[Path | None],
    hook: str,
    finish: dict[str, Any],
    ffmpeg_exe: str,
) -> dict[str, Any]:
    """The film's cover: its hero still (the first filmed scene's) with the hook, composed
    locally (cards.compose_cover) as cover.png beside the film. 0 credits; a hook the font
    cannot draw, or no still, is recorded as the reason there is no cover."""
    record: dict[str, Any] = {"path": None, "hook": hook, "credits": 0, "reason": None}
    if not finish["cover"]["compose"]:
        record["reason"] = "coperta este oprită în finish.cover"
        return record
    hero = next(
        (
            frame
            for frame, card in zip(frames, card_clips, strict=False)
            if frame is not None and card is None and frame.suffix.lower() in _RASTER
        ),
        None,
    )
    if hero is None or not hook:
        record["reason"] = "filmul nu are o imagine filmată" if hero is None else "nu are cârlig"
        return record
    try:
        cover = compose_cover(hero, hook, folder / COVER_NAME, ffmpeg=ffmpeg_exe)
    except CardError as exc:
        record["reason"] = str(exc)
        return record
    scene_index = next(
        (
            int(scene["scene_index"])
            for scene, frame in zip(scenes, frames, strict=False)
            if frame == hero
        ),
        None,
    )
    record.update(
        path=str(cover.path),
        sha256=cover.sha256,
        still=hero.name,
        scene_index=scene_index,
        provenance=cover.provenance,
        size=[1080, 1920],
    )
    return record


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
#: A paid take whose delivered file another take of the scene already holds.
DUPLICATE_FILE_CODE = "VENDOR.DUPLICATE_FILE"
#: At most this much of a vendor's reason is kept on a take (the column's own limit).
TAKE_DETAIL_MAX = 500
#: The take kinds that are a scene's shot: the hero test shot is kept in the film.
SHOT_TAKE_KINDS: tuple[str, ...] = ("test_shot", "motion")


class TakesMissing(RuntimeError):
    """A film cannot be assembled from its takes: a LIVE scene has no approved still.

    Raised before a render job exists and before any adapter is asked: assembling from takes
    never buys a picture. The message is the Owner's, in Romanian.
    """


class ClipsNotAccepted(TakesMissing):
    """A PRODUCTION film would show a LIVE scene as a still the Owner did not choose.

    A scene without an accepted clip (approved by the Owner, or passed by clip QC) may be a
    locally animated still only when he chose LOCAL_MOVE for it on the sheet
    (`qc.require_chosen_fallbacks`). ``scenes`` names them; the message says why, per scene,
    in Romanian. A TakesMissing, so every caller that holds a film for missing takes holds
    this one too. ``details`` is each refused scene's reading (`clip_readiness`: its code,
    CLIP_SHORT for a clip too short to be slowed into its span, the seconds, the take), as the
    refusal's event (ASSEMBLY_REFUSED_EVENT) records it.
    """

    def __init__(
        self, scenes: list[int], message_ro: str, details: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(message_ro)
        self.scenes = list(scenes)
        self.message_ro = message_ro
        self.details = list(details or [])


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


#: A still the Owner's renders cap approved as the scene's picture (`stills_stage`): it is
#: the scene's whatever words it was made on, so `usable_take` matches it without its hash.
CAP_APPROVER = "director_cap"


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
    length_of: Callable[[SceneTake], float | None] | None = None,
) -> SceneTake | None:
    """A take of this scene that may be used instead of buying one, or None.

    Its prompt hash must equal the hash of one of ``field_options`` with the take's own model
    (the prompt unchanged), its file must be on disk with the sha256 recorded, an APPROVED take
    is preferred over a PAID one and a newer over an older. ``models`` narrows it to takes made
    by those models; ``min_seconds`` to shots long enough for the span: by their billed
    seconds, or by ``length_of`` (a shot's file as measured, `shot_clip_seconds`) once the
    file is checked.
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
        if (
            length_of is None
            and min_seconds is not None
            and row.seconds is not None
            and row.seconds < min_seconds
        ):
            continue
        if row.approved_by != CAP_APPROVER and not any(
            take_hash(fields, row.model_id) == row.prompt_hash for fields in field_options
        ):
            continue
        if not row.path or not row.sha256:
            continue
        path = Path(row.path)
        if not path.is_file() or _file_sha256(path) != row.sha256:
            continue
        if length_of is not None and min_seconds is not None:
            have = length_of(row)
            if have is not None and have < min_seconds:
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
    remote_task_id: str | None = None,
    take_id: str | None = None,
) -> str:
    """Write one take (and its event). The same file of the same prompt is one row: buying it
    again updates that row instead of breaking the identity the table enforces.

    ``take_id`` names the row to update: a SUBMITTED take (written the moment the vendor
    accepted its task, with ``remote_task_id``) becomes PAID, REFUSED or LOST in place, so
    one purchase is one row. Its own short transaction, the write lock taken first: the row
    that says money went out must not be refused because a reader committed in between."""
    now = utc_now()
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        existing = session.get(SceneTake, take_id) if take_id else None
        same_file = (
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
        if existing is not None and same_file is not None and same_file.id != existing.id:
            # The vendor delivered a file this scene already holds. The file keeps its one
            # row; the purchase keeps its own, REJECTED as a duplicate, its credits and task
            # id still on the books.
            existing.status = "REJECTED"
            existing.failure_code = DUPLICATE_FILE_CODE
            existing.failure_detail = "Furnizorul a predat un fișier identic cu unul deja primit."
            existing.updated_at = now
            sync_take_quality(session, existing)
            existing = same_file
        elif existing is None:
            existing = same_file
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
                "remote_task_id": remote_task_id
                or (existing.remote_task_id if existing is not None else None),
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
        if remote_task_id is not None:
            row.remote_task_id = str(remote_task_id)[:100]
        row.updated_at = now
        row.event_id = event.event_id
        if existing is None:
            session.add(row)
        sync_take_quality(session, row)
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


# ------------------------------------------------------------- narration bought once
#
# A9 / MONEY-12 (2026-10-02): every assembly voiced every scene again, so an assembly that
# failed after its narration (the master, the encode, a stop) and was tried again paid
# ElevenLabs twice. Each voiced segment is now a SceneTake of kind ``narration``: its audio
# beside the film, its word timing and the vendor's answer in a sidecar JSON, its identity
# the words and everything the voice was asked with. The next assembly of the same words in
# the same voice reads it back for nothing.

NARRATION_KIND = "narration"
#: Where a film's bought narration is kept, under the film's folder (never released).
NARRATION_FOLDER = "narration"
#: The suffix of a narration take's sidecar: its timing and the vendor's answer.
NARRATION_SIDECAR = ".json"


def bought_voice(adapter: Any) -> bool:
    """Whether this voice's narration is kept as a take. A voice of the studio's own code is
    kept only when it is a paid vendor's adapter (`factory.is_paid_vendor_adapter`): the
    local stand-in and a rehearsal's played-back recording cost nothing to say again. A
    voice from outside the studio's code is one the studio cannot vouch is free, so it is
    treated as bought."""
    if adapter is None:
        return False
    module = str(type(adapter).__module__ or "")
    if module == "app" or module.startswith("app."):
        from app.media.factory import is_paid_vendor_adapter  # noqa: PLC0415 - imports media

        return is_paid_vendor_adapter(adapter)
    return True


def stitches(voice: Any) -> bool:
    """Whether this voice is sent its neighbours' words (request stitching, audit Q3)."""
    return bool(getattr(type(voice), "ACCEPTS_STITCHING", False))


def narration_context(texts: Sequence[Sequence[str]]) -> list[list[dict[str, str | None]]]:
    """For each scene's parts, in film order, the words said just before and just after them:
    {"previous_text", "next_text"}, None at the film's two ends. Scenes without words (a
    silent card) are skipped over, so the context runs on through them."""
    flat = [
        (scene, part, text) for scene, parts in enumerate(texts) for part, text in enumerate(parts)
    ]
    spoken = [item for item in flat if " ".join(str(item[2]).split())]
    context: list[list[dict[str, str | None]]] = [
        [{"previous_text": None, "next_text": None} for _ in parts] for parts in texts
    ]
    for position, (scene, part, _text) in enumerate(spoken):
        context[scene][part] = {
            "previous_text": str(spoken[position - 1][2]) if position > 0 else None,
            "next_text": str(spoken[position + 1][2]) if position + 1 < len(spoken) else None,
        }
    return context


def _context_fields(context: dict[str, Any] | None) -> dict[str, str] | None:
    """The context as it changes a recording: only the neighbours' words that exist."""
    if not context:
        return None
    kept = {
        key: " ".join(str(context[key]).split())
        for key in ("previous_text", "next_text")
        if isinstance(context.get(key), str) and " ".join(str(context[key]).split())
    }
    return kept or None


def narration_fields(
    text: str, voice: Any, context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """What makes a narration the recording it is, besides the model: the words and every
    setting the voice is asked with. A new voice, new settings or a new adapter is a new
    recording; the same words in the same voice are the same one. ``context`` (the words
    before and after, for a voice that `stitches`) and the voice's own request settings
    (text normalisation, pronunciation dictionaries) shape the recording, so they are part of
    it when present; a voice without them keys exactly as it always did."""
    import sys  # noqa: PLC0415

    module = sys.modules.get(type(voice).__module__)
    settings = getattr(voice, "voice_settings", None)
    extra: dict[str, Any] = {}
    request_settings = getattr(voice, "request_settings", None)
    if callable(request_settings):
        asked = request_settings()
        if isinstance(asked, dict):
            options = {k: v for k, v in asked.items() if k != "voice_settings"}
            if options:
                extra["request_settings"] = options
    stitched = _context_fields(context)
    if stitched:
        extra["context"] = stitched
    return {
        "kind": NARRATION_KIND,
        "text": " ".join(str(text).split()),
        "provider": str(getattr(voice, "PROVIDER_NAME", "") or ""),
        "adapter": f"{type(voice).__module__}.{type(voice).__qualname__}",
        "adapter_version": str(getattr(voice, "ADAPTER_VERSION", "") or ""),
        "voice_id": getattr(voice, "voice_id", None) or None,
        "voice_settings": dict(settings) if isinstance(settings, dict) else {},
        "output_format": getattr(voice, "output_format", None)
        or getattr(module, "OUTPUT_FORMAT", None),
        "integration_id": getattr(voice, "integration_id", None) or None,
        **extra,
    }


def narration_key(text: str, voice: Any, context: dict[str, Any] | None = None) -> str:
    """The narration take's identity (its ``prompt_hash``): the words, the voice, and for a
    voice that `stitches`, the words around them."""
    return take_hash(
        narration_fields(text, voice, context if stitches(voice) else None),
        getattr(voice, "model", None) or None,
    )


def _voice_key(voice: Any) -> str:
    """The voice alone, without the words: which recordings belong to one voice."""
    fields = narration_fields("", voice)
    fields.pop("text")
    return take_hash(fields, getattr(voice, "model", None) or None)


def _text_sha(text: str) -> str:
    return hashlib.sha256(" ".join(str(text).split()).encode("utf-8")).hexdigest()


def _sidecar(path: Path) -> Path:
    return path.with_name(path.name + NARRATION_SIDECAR)


def reused_narration(
    engine: Engine, storyboard_id: str, scene_number: int, key: str
) -> tuple[TTSResult, str] | None:
    """(the recording, its take id) when this scene already holds a narration of these words
    in this voice, its file and sidecar intact; None otherwise. Buys nothing."""
    with Session(engine) as session:
        rows = session.scalars(
            select(SceneTake)
            .where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == scene_number,
                SceneTake.kind == NARRATION_KIND,
                SceneTake.prompt_hash == key,
                SceneTake.status.in_(REUSABLE_TAKE_STATUSES),
            )
            .order_by(SceneTake.created_at.desc())
        ).all()
        found = [(row.id, row.path, row.sha256) for row in rows]
    for take_id, stored, digest in found:
        if not stored or not digest:
            continue
        path = Path(stored)
        sidecar = _sidecar(path)
        if not path.is_file() or not sidecar.is_file() or _file_sha256(path) != digest:
            continue
        try:
            kept = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(kept, dict):
            continue
        raw = kept.get("raw_response")
        timings = kept.get("word_timings")
        return (
            TTSResult(
                audio_bytes=path.read_bytes(),
                format=str(kept.get("format") or path.suffix.lstrip(".") or "mp3"),
                duration_seconds=float(kept.get("duration_seconds") or 0.0),
                sample_rate=int(kept.get("sample_rate") or 44100),
                word_timings=list(timings) if isinstance(timings, list) else [],
                cost_vr=None,
                raw_response={**(raw if isinstance(raw, dict) else {}), "reused_take": take_id},
            ),
            take_id,
        )
    return None


def keep_narration(
    engine: Engine,
    *,
    storyboard_id: str,
    scene_number: int,
    key: str,
    voice: Any,
    said: TTSResult,
    folder: Path,
    scene_text: str,
    part: int,
    parts: int,
    correlation_id: str,
) -> str | None:
    """A narration just bought, kept as a PAID take with its audio and its sidecar.

    Never fails the render that bought it: a narration that could not be kept is logged and
    the film goes on (it would only be bought again next time)."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        fmt = str(said.format or "mp3")[:10]
        path = folder / f"scene_{scene_number:02d}_{key[:16]}.{fmt}"
        path.write_bytes(said.audio_bytes)
        _sidecar(path).write_text(
            json.dumps(
                {
                    "format": fmt,
                    "duration_seconds": said.duration_seconds,
                    "sample_rate": said.sample_rate,
                    "word_timings": said.word_timings,
                    "raw_response": said.raw_response,
                    "scene_text_sha256": _text_sha(scene_text),
                    "voice_key": _voice_key(voice),
                    "part": part,
                    "parts": parts,
                    "characters": len(" ".join(str(scene_text).split())),
                },
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )
        return record_take(
            engine,
            storyboard_id=storyboard_id,
            scene_number=scene_number,
            kind=NARRATION_KIND,
            prompt_hash=key,
            model_id=getattr(voice, "model", None) or None,
            resolution=fmt,
            status="PAID",
            correlation_id=correlation_id,
            seconds=float(said.duration_seconds),
            path=path,
            sha256=_file_sha256(path),
        )
    except (OSError, SQLAlchemyError, TypeError, ValueError) as exc:
        logger.warning(
            "narration_not_kept",
            extra={
                "storyboard_id": storyboard_id,
                "scene_number": scene_number,
                "error": type(exc).__name__,
            },
        )
        return None


def voiced_scenes(
    session: Session, storyboard_id: str, scenes: Sequence[dict[str, Any]]
) -> set[int]:
    """The scenes whose words as they are now are already voiced, every part of them, by one
    voice: the sheet prices them at 0. Voice-blind on purpose (the sheet has no adapter);
    the assemble step checks the actual voice (`narration_to_buy`) and asks for what it
    would really buy."""
    rows = session.scalars(
        select(SceneTake).where(
            SceneTake.storyboard_id == storyboard_id,
            SceneTake.kind == NARRATION_KIND,
            SceneTake.status.in_(REUSABLE_TAKE_STATUSES),
        )
    ).all()
    wanted = {
        int(scene["scene_index"]): _text_sha(str(scene.get("voiceover_segment") or ""))
        for scene in scenes
    }
    covered: dict[tuple[int, str], set[int]] = {}
    needed: dict[tuple[int, str], int] = {}
    for row in rows:
        if not row.path or wanted.get(int(row.scene_number)) is None:
            continue
        path = Path(row.path)
        try:
            kept = json.loads(_sidecar(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(kept, dict) or not path.is_file():
            continue
        if kept.get("scene_text_sha256") != wanted[int(row.scene_number)]:
            continue
        group = (int(row.scene_number), str(kept.get("voice_key") or ""))
        covered.setdefault(group, set()).add(int(kept.get("part") or 0))
        needed[group] = int(kept.get("parts") or 1)
    return {
        scene for (scene, _voice), parts in covered.items() if len(parts) >= needed[(scene, _voice)]
    }


def _scene_parts(
    scene: dict[str, Any],
    voice: Any,
    voice_segments_for_scene: Callable[[dict[str, Any]], list[dict[str, Any]] | None] | None,
) -> list[tuple[dict[str, Any], Any]]:
    """The scene's narration as the render says it: one take per speaker where the scene's
    lines say who speaks them (each in its own voice, else the scene's), otherwise the
    scene's words in the scene's voice. (part, voice) pairs."""
    given = voice_segments_for_scene(scene) if voice_segments_for_scene else None
    parts: list[dict[str, Any]] = [p for p in (given or []) if str(p.get("text") or "")]
    if not parts:
        parts = [{"text": scene["voiceover_segment"]}]
    return [(part, part.get("adapter") or voice) for part in parts]


def narration_to_buy(
    engine: Engine,
    storyboard_id: str,
    *,
    tts_adapter: Any = None,
    tts_adapter_for_scene: Callable[[dict[str, Any]], Any] | None = None,
    voice_segments_for_scene: Callable[[dict[str, Any]], list[dict[str, Any]] | None] | None = None,
) -> int:
    """How many characters an assembly with these voices would actually buy: every part a
    real voice would say that no narration take already holds. 0 for the local stand-in.
    Calls no voice."""
    _title, scenes = _storyboard_scenes(engine, storyboard_id)
    voices = [
        (tts_adapter_for_scene(scene) if tts_adapter_for_scene else None) or tts_adapter
        for scene in scenes
    ]
    if not voices or any(voice is None for voice in voices):
        return 0  # the placeholder narrates: nothing is bought
    characters = 0
    spoken = [
        _scene_parts(scene, voice, voice_segments_for_scene)
        for scene, voice in zip(scenes, voices, strict=True)
    ]
    contexts = narration_context([[str(part["text"]) for part, _ in parts] for parts in spoken])
    for scene, parts, around in zip(scenes, spoken, contexts, strict=True):
        for (part, speaker), context in zip(parts, around, strict=True):
            if not bought_voice(speaker):
                continue
            text = str(part["text"])
            key = narration_key(text, speaker, context)
            if reused_narration(engine, storyboard_id, int(scene["scene_index"]), key) is None:
                characters += len(" ".join(text.split()))
    return characters


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
    TakesMissing is raised before a render job exists. A LIVE scene's shot is its accepted
    motion take (the Owner's APPROVED, or a PAID one clip QC passed; in TEST also a PAID one
    nobody could check), else its still given a slow push, which quality control counts as a
    fallback. In PRODUCTION such a still is allowed only where the Owner chose LOCAL_MOVE for
    the scene on the sheet (`qc.require_chosen_fallbacks`); otherwise `ClipsNotAccepted` (a
    TakesMissing) names the scenes and why, before anything is spoken or encoded. Cards are
    composed. Narration, captions, the master and the encode are done as in any render; any
    image or video adapter passed is never asked. The other keyword arguments are
    `assemble_video_job`'s.

    Whether a scene's shot may be cut in is read by `assembly_readiness`, the reading the
    shooting sheet shows and the render makes (`clip_readiness`): its accepted take, long
    enough for the shot span its narration gives it (measured, or estimated before any word is
    voiced) once slowed down by at most SLOWDOWN_ALLOWANCE. A refusal is recorded
    (ASSEMBLY_REFUSED_EVENT) with each scene's seconds.

    The measured spend of the film's paid steps (each step's balance before and after, in its
    own event) is written on the film (``production['credits_measured']``) and booked once
    through the accountant (`book_film_spend`); a film assembled again from the same takes
    books nothing again.
    """
    from app.media.prompt_agent import strip_on_screen_text  # noqa: PLC0415

    environment = str(render.get("environment") or "PRODUCTION")
    _title, scenes = _storyboard_scenes(engine, storyboard_id)
    missing: list[int] = []
    shots: list[dict[str, Any]] = []
    why_not: dict[int, str] = {}
    stills: dict[int, str | None] = {}
    verdicts: dict[int, dict[str, Any]] = {}
    with Session(engine) as session:
        for scene in scenes:
            index = int(scene["scene_index"])
            if is_composed(scene):
                continue
            # The reference picture is part of the still's identity; it is read here the
            # same way the render reads it.
            chooser = render.get("reference_for_scene")
            reference = chooser(scene) if chooser else None
            fields = still_fields(str(scene["visual_prompt"] or ""), reference)
            retry = still_fields(
                strip_on_screen_text(str(scene["visual_prompt"] or "")) + DEGENERATE_RETRY_SUFFIX,
                reference,
            )
            still = usable_take(
                session, storyboard_id, index, "still", [fields, retry], statuses=("APPROVED",)
            )
            if still is None:
                missing.append(index)
                continue
            # usable_take checked the file's sha256 against the take's: the render's own hash
            # of the still it copies is this one.
            stills[index] = still.sha256
        if not missing:
            # One reading with the sheet and the render (2026-10-09, babcf272): the shot must
            # be accepted AND long enough for its span, with the same still hash and the same
            # from_prompt the render will use. Local moves and TEST are the gate's below.
            verdicts = {
                int(item["scene_index"]): item
                for item in assembly_readiness(
                    session,
                    storyboard_id,
                    scenes,
                    stills,
                    environment=environment,
                    local_moves=set(),
                    from_prompt=bool(render.get("motion_from_prompt")),
                )
            }
    if missing:
        raise TakesMissing(
            "Filmul nu se poate asambla din imaginile aprobate: "
            + ", ".join(f"Scena {n}" for n in missing)
            + " nu are o imagine aprobată pentru promptul de acum. Nimic nu a fost cumpărat."
        )
    for scene in scenes:
        index = int(scene["scene_index"])
        if is_composed(scene):
            shots.append({"scene_index": index, "scene_kind": scene_kind_of(scene)})
            continue
        verdict = verdicts[index]
        # "at_risk": words not measured yet that may leave the clip too short; the render
        # measures them and decides (`clip_readiness`).
        moving = verdict.get("how") in ("shot", "slowed", "at_risk")
        if not moving and verdict.get("why_ro"):
            why_not[index] = str(verdict["why_ro"])
        shots.append(
            {
                "scene_index": index,
                "scene_kind": LIVE_KIND,
                "motion": {"reused_take": True} if moving else None,
            }
        )
    try:
        _require_chosen_stills(
            engine,
            storyboard_id,
            {"scenes": shots},
            environment=environment,
            settings=render.get("settings"),
            why_not=why_not,
        )
    except ClipsNotAccepted as exc:
        exc.details = [verdicts[index] for index in exc.scenes if index in verdicts]
        record_assembly_refused(
            engine, storyboard_id, correlation_id, exc, stage="precheck", environment=environment
        )
        raise
    film = assemble_video_job(engine, storyboard_id, correlation_id, takes_only=True, **render)
    spend = book_film_spend(engine, storyboard_id, str(film["job_id"]))
    if spend:
        film["production"]["credits_measured"] = spend
    return film


def _require_chosen_stills(
    engine: Engine,
    storyboard_id: str,
    production: dict[str, Any],
    *,
    environment: str,
    settings: Any | None,
    why_not: dict[int, str] | None = None,
) -> dict[str, Any]:
    """`qc.require_chosen_fallbacks`, raised as `ClipsNotAccepted` with each scene's reason:
    in PRODUCTION a LIVE scene without an accepted clip is a still only by the Owner's
    LOCAL_MOVE on the sheet. Returns the verdict (recorded on the film)."""
    from app.media import qc as clip_qc  # noqa: PLC0415 - qc reads the media models

    try:
        return clip_qc.require_chosen_fallbacks(
            engine, storyboard_id, production, environment=environment, settings=settings
        )
    except clip_qc.FallbackNotChosen as exc:
        reasons = [(why_not or {}).get(index) for index in exc.scenes]
        details = " ".join(reason for reason in reasons if reason)
        raise ClipsNotAccepted(
            list(exc.scenes),
            f"{exc.message_ro}" + (f" {details}" if details else ""),
        ) from exc


#: The paid steps of a film whose own event records the account's balance before and after:
#: the stills step, each motion step (the hero test shot, the motion, a motion redo) and a
#: still redo.
SPEND_STEP_EVENTS: tuple[str, ...] = (
    "media.stills_step_finished",
    "media.motion_step_finished",
    "media.scene_redone",
)
#: The accountant's event (economy.credits.record_credit_spend), read to book a step once.
CREDITS_BOOKED_EVENT = "economy.credits_measured"


def _credits(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def film_step_spend(engine: Engine, storyboard_id: str) -> dict[str, dict[str, Any]]:
    """What each paid step of the film moved the account by, from the step's own event.

    One entry per step that bought something and saw the balance drop, keyed by its event
    (``<event_type>:<event_id>``), in the shape ``production['credits_measured']`` keeps
    (kind, unit, before, after, spent), so the QC letter reads real credits. A step that read
    no balance is not a measurement and is left out; a rise (a top-up) is not a spend.
    """
    spend: dict[str, dict[str, Any]] = {}
    with Session(engine) as session:
        for event in session.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.aggregate_id == storyboard_id,
                DomainEvent.event_type.in_(SPEND_STEP_EVENTS),
            )
            .order_by(DomainEvent.sequence)
        ):
            payload = event.payload if isinstance(event.payload, dict) else {}
            before = _credits(payload.get("balance_before"))
            after = _credits(payload.get("balance_after"))
            if before is None or after is None or before - after <= 0:
                continue
            step = payload.get("step") or (
                "stills"
                if event.event_type == "media.stills_step_finished"
                else payload.get("kind")
            )
            item: dict[str, Any] = {
                "kind": "runway",
                "unit": "credits",
                "before": before,
                "after": after,
                "spent": before - after,
                "step": step,
                "event_id": event.event_id,
            }
            per_credit = _credits(payload.get("credit_usd"))
            if per_credit:
                item["usd"] = round((before - after) * per_credit, 4)
            spend[f"{event.event_type}:{event.event_id}"] = item
    return spend


def book_film_spend(engine: Engine, storyboard_id: str, render_job_id: str) -> dict[str, Any]:
    """Book the film's measured step spend once, and write all of it on the film.

    The steps not yet booked by any film go through the accountant
    (`economy.credits.record_credit_spend`, one ``economy.credits_measured`` event on this
    render); a step an earlier film of the same takes booked is not booked again. The film's
    ``production['credits_measured']`` carries every step, booked now or before
    (``booked_now``), so its QC letter says what the film cost instead of "necunoscut".
    """
    from app.economy.credits import record_credit_spend  # noqa: PLC0415 - economy reads media

    spend = film_step_spend(engine, storyboard_id)
    if not spend:
        return {}
    booked: set[str] = set()
    with Session(engine) as session:
        for event in session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == CREDITS_BOOKED_EVENT)
        ):
            measured = (event.payload or {}).get("measured")
            if isinstance(measured, dict):
                booked |= set(measured)
    fresh = {key: item for key, item in spend.items() if key not in booked}
    if fresh:
        record_credit_spend(
            engine,
            render_job_id,
            {key: {"kind": "runway", "balance": item["before"]} for key, item in fresh.items()},
            {key: {"kind": "runway", "balance": item["after"]} for key, item in fresh.items()},
        )
    for key, item in spend.items():
        item["booked_now"] = key in fresh
    with Session(engine) as session, session.begin():
        job = session.get(VideoRenderJob, render_job_id)
        if job is not None:
            production = dict(job.production_json) if isinstance(job.production_json, dict) else {}
            production["credits_measured"] = spend
            job.production_json = production
    return spend


def _compose_card_clip(
    scene: dict[str, Any],
    work_dir: Path,
    *,
    seconds: float,
    background: Path | None,
    ffmpeg_exe: str | None,
    fps: int = TIMELINE_FPS,
    short: bool = True,
) -> dict[str, Any]:
    """One card scene's clip, composed locally from its own spec at the timeline's ``fps``:
    0 credits, no adapter. Every film is a short: a BLACK scene longer than a beat is a closing
    card on the hook's still (cards.MAX_SHORT_BLACK_SECONDS, audit Q5). ``short`` False keeps
    a card of a film made before that rule exactly as it was made (a rederived shot)."""
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
        short=short,
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
        # A BLACK scene drawn on the hook's still instead of black (a closing card).
        "closing": card.closing,
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


def _motion_record(production: dict[str, Any], scene_index: Any) -> dict[str, Any] | None:
    """The motion record on a scene's entry in the manifest, or None."""
    return next(
        (
            entry["motion"]
            for entry in production["scenes"]
            if entry.get("scene_index") == scene_index and isinstance(entry.get("motion"), dict)
        ),
        None,
    )


def _clip_slowdowns(
    ffmpeg_exe: str | None,
    scenes: list[dict[str, Any]],
    motion_clips: list[Path | None],
    card_clips: list[Path | None],
    lengths: list[float],
    production: dict[str, Any],
) -> list[float]:
    """How many times slower each LIVE clip plays to fill its shot: 1.0 for a clip that covers
    it (it is cut), and for every scene without a clip.

    The clip is measured, not read from its take: a vendor may deliver less than it billed.
    One short of its span by at most SLOWDOWN_ALLOWANCE is slowed (the factor asks
    SLOWDOWN_EXTRA_FRAMES more than the span, which the trim then cuts) and the scene's motion
    record says so (``slowed_by``, ``from_seconds``, ``to_seconds``): 0 USD, never a frozen
    frame (the Owner, 2026-10-09). One shorter still is not cut in at all: its scene loses the
    clip, its record says why (``refused``, ``readiness`` CLIP_SHORT), and the fallback gate
    refuses the film in PRODUCTION unless the Owner chose LOCAL_MOVE for it, so the studio
    redoes the motion at the right length instead (`propose_clip_redos`)."""
    slows = [1.0] * len(scenes)
    if not ffmpeg_exe:
        return slows
    for position, (scene, clip) in enumerate(zip(scenes, motion_clips, strict=True)):
        if clip is None or card_clips[position] is not None:
            continue
        have = _video_stream_seconds(ffmpeg_exe, clip)
        record = _motion_record(production, scene["scene_index"])
        if have is None:
            continue
        if record is not None:
            record["clip_seconds"] = round(have, 3)
        need = lengths[position]
        stretch = clip_stretch(have, need)
        if stretch <= 1.0:
            continue
        index = int(scene["scene_index"])
        if not clip_fits(have, need):
            motion_clips[position] = None
            words = clip_short_words(index, have, need)
            if record is not None:
                record.pop("bytes", None)
                record["reused_take"] = False
                record["refused"] = words
                record["readiness"] = {
                    "code": CLIP_SHORT,
                    "take_id": record.get("take_id"),
                    "clip_seconds": round(have, 3),
                    "span": round(need, 3),
                    "needed_seconds": round(min_clip_seconds(need), 3),
                    "why_ro": words,
                }
            continue
        frames_have = max(1, round(have * TIMELINE_FPS))
        frames_need = max(1, round(need * TIMELINE_FPS))
        slows[position] = (frames_need + SLOWDOWN_EXTRA_FRAMES) / frames_have
        if record is not None:
            record.update(
                slowed_by=round(stretch, 4),
                from_seconds=round(have, 3),
                to_seconds=round(need, 3),
                slow_factor=round(slows[position], 6),
            )
        production.setdefault("slowed_scenes", []).append(
            {
                "scene_index": index,
                "slowed_by": round(stretch, 4),
                "from_seconds": round(have, 3),
                "to_seconds": round(need, 3),
                "words_ro": slowed_words(index, have, need),
            }
        )
        # Told to the Owner on the film, as a held frame used to be.
        production.setdefault("owner_warnings", []).append(slowed_words(index, have, need))
    return slows


def _refused_reading(production: dict[str, Any], scene_index: int) -> dict[str, Any]:
    """A scene the render refused, as the refusal's event records it: the reading kept on its
    motion record (`clip_readiness`, or the clip measured too short), else its reason."""
    record = _motion_record(production, scene_index) or {}
    reading = dict(record.get("readiness") or {})
    reading.setdefault("code", NO_SHOT)
    reading.setdefault("why_ro", str(record.get("refused") or ""))
    return {"scene_index": int(scene_index), **reading}


def _timeline_record(
    scenes: list[dict[str, Any]],
    joins: list[float],
    lengths: list[float],
    holds: list[float],
    motion_clips: list[Path | None],
    card_clips: list[Path | None],
    *,
    dither: bool,
    framings: list[dict[str, Any] | None] | None = None,
    slows: list[float] | None = None,
) -> dict[str, Any]:
    """The film's timeline as the manifest keeps it, and as quality control reads it: the
    frame rate, and each scene's place (start, end), how it is joined from the scene before,
    its shot's length and whether its shot is a generated clip (``moving``), slowed down to
    fill its span (``slow_factor``, `_clip_slowdowns`). A scene cut to a second framing of its
    picture carries it (``second_framing``), and the film counts the shots on screen and their
    average length (audit Q6)."""
    spans: list[dict[str, Any]] = []
    clock = 0.0
    framings = framings if framings is not None else [None] * len(scenes)
    slows = slows if slows is not None else [1.0] * len(scenes)
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
                "slow_factor": round(slows[position], 6) if slows[position] > 1.0 else None,
                # What quality control reads of the span (qc.timeline_spans): the scene's
                # kind, and how long its words are (None: not measured).
                "kind": scene_kind_of(scene),
                "spoken_seconds": scene.get("audio_seconds"),
                "second_framing": framings[position],
            }
        )
        clock += length
    spoken = [scene.get("audio_seconds") for scene in scenes]
    narration = (
        round(sum(float(s) for s in spoken if isinstance(s, int | float)), 3)
        if all(isinstance(s, int | float) for s in spoken)
        else None
    )
    on_screen = len(spans) + sum(1 for framing in framings if framing)
    return {
        "fps": TIMELINE_FPS,
        "dither": "zscale error_diffusion" if dither else "swscale",
        "spoken_tail_seconds": SPOKEN_TAIL_SECONDS,
        "film_seconds": round(clock, 6),
        "narration_seconds": narration,
        "spans": spans,
        "shots_on_screen": on_screen,
        "average_shot_seconds": round(clock / on_screen, 3) if on_screen else None,
    }


def _write_captions(
    scenes: list[dict[str, Any]],
    work_dir: Path,
    ffmpeg_exe: str,
    *,
    wants_burn: bool,
    finish: dict[str, Any] | None = None,
    headline: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Write captions.srt and captions.ass beside the film; return the manifest's record and
    the filter that burns them (None when they are not burnt, with the reason recorded).
    ``finish`` carries the Owner's caption colours and whether the hook ``headline`` shows."""
    from app.media import cards  # noqa: PLC0415

    finish = finish or film_finish()
    cues = caption_cues(scenes)
    srt_file = work_dir / "captions.srt"
    srt_file.write_text(srt_from_cues(cues), encoding="utf-8")
    ass_file = work_dir / CAPTIONS_ASS_NAME
    reason: str | None = None
    try:
        ass_file.write_text(ass_from_cues(cues, finish=finish, headline=headline), encoding="utf-8")
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
                # The finish the captions were burnt with (audit Q7): the colours, the shadow,
                # and whether the spoken word and numbers were lit.
                "colours": {key: finish["captions"][key] for key in ("text", "active", "emphasis")},
                "shadow_px": finish["captions"]["shadow_px"],
                "shadow_opacity": finish["captions"]["shadow_opacity"],
                "highlight": bool(finish["captions"]["highlight_active_word"])
                and any(cue.get("words") for cue in cues),
                "emphasis_numbers": bool(finish["captions"]["emphasis_numbers"]),
                "headline": bool(headline) and bool(finish["headline"]["show"]),
                "phrase_aware": True,
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
    """The usable shot of a scene among its motion and test-shot takes, APPROVED first, at
    least ``seconds`` long as its file measures (`shot_clip_seconds`).

    The Owner's newest choice (`owner_clip_choice`) is the scene's shot whenever he made one
    (2026-10-10, «Aleg totuși acest clip»): it is returned when it is long enough, and nothing
    is when it is not, so a reading too short for it says so (CLIP_SHORT) instead of cutting in
    another clip behind his back."""
    chosen = owner_clip_choice(session, storyboard_id, scene_number, [fields])
    if chosen is not None:
        have = shot_clip_seconds(chosen)
        return chosen if have is None or have >= round(seconds, 3) else None
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
                length_of=shot_clip_seconds,
            )
            for kind in SHOT_TAKE_KINDS
        )
        if take is not None
    ]
    found.sort(key=lambda take: 0 if take.status == "APPROVED" else 1)
    return found[0] if found else None


#: Each shot file's measured length, by its sha256 (the same bytes always measure the same).
_CLIP_SECONDS: dict[str, float | None] = {}
_CLIP_SECONDS_MAX = 4096


def shot_clip_seconds(take: SceneTake) -> float | None:
    """How long a shot take's clip lasts: its file's picture as measured (frames over frame
    rate, `_video_stream_seconds`, the render's own measure in `_clip_slowdowns`), else its
    billed seconds (no encoder, no file, or a file that cannot be measured).

    2026-10-10 (review): the sheet and the pre-check read the billed seconds while the render
    measured the file, so a clip delivered shorter than it was billed was «Pregătit» on the
    sheet and refused by every render. One length now, measured once per file."""
    billed = float(take.seconds) if take.seconds else None
    if not take.path or not take.sha256:
        return billed
    if take.sha256 not in _CLIP_SECONDS:
        ffmpeg_exe = find_ffmpeg()
        path = Path(take.path)
        if not ffmpeg_exe or not path.is_file():
            return billed
        if len(_CLIP_SECONDS) >= _CLIP_SECONDS_MAX:
            _CLIP_SECONDS.clear()
        # Kept unrounded: the render compares the same unrounded measure with the span.
        _CLIP_SECONDS[take.sha256] = _video_stream_seconds(ffmpeg_exe, path) or None
    measured = _CLIP_SECONDS[take.sha256]
    return measured if measured is not None else billed


# ------------------------------------------------- a clip as long as the words it carries
#
# 2026-10-09 (film babcf272, «The Particle That Shouldn't Exist (But Does)»): the sheet bought
# every clip at its PLANNED seconds (`motion_seconds`: the plan plus 0.4 s) before a word was
# voiced. FILM_CONTINUE then bought the narration (18:22 UTC) and scene 3's words measured
# 6.06 s against its 5.0 s clip: the shot span the render measures from the narration was
# longer than the clip, `_usable_motion_take(min_seconds=span)` found nothing, the scene fell
# back to a still PRODUCTION refuses without his LOCAL_MOVE, and the assembly was refused four
# times (each of his approvals ran it again) while the sheet, which looked for a shot of any
# length, said «Pregătit». The Owner's answer, «Încetinește local»:
# - a clip is bought as long as the narration it will carry (`clip_plan`): the measured
#   narration when its take exists, else an estimate from the scene's words, plus the breath,
#   the dissolve and a margin; the planner rounds it up to a length the scene's model accepts
#   (its duration contract), and a scene planned longer keeps its plan;
# - at assembly a clip short of its span by at most SLOWDOWN_ALLOWANCE is slowed down locally
#   (`_clip_slowdowns`, 0 USD, never a frozen frame); beyond that the scene is refused
#   (ASSEMBLY_REFUSED_EVENT) and the studio raises its paid motion redo at the right length
#   (`propose_clip_redos`, through `redo_scene`, under his paid-media rule);
# - the sheet, the pre-check of `assemble_from_takes` and the render read ONE readiness
#   (`clip_readiness`): the same shot identity (still hash, from_prompt) and the same minimum
#   length, so the sheet never says «Pregătit» for a film the render refuses.
# The length is never part of a shot's identity (`motion_fields`): a clip sized anew, or a
# span measured anew, never orphans a take already bought.

#: Seconds per word the studio's narration voice takes, measured 2026-10-10 on film babcf272's
#: five ElevenLabs takes: 4.885 + 6.06 + 6.06 + 6.008 + 7.732 = 30.745 s (the vendor's own
#: lengths) for 77 words as `spoken_words` counts them (73 written; "1964" and "2013" said as
#: three words each): 0.399 s a word. Scene by scene the takes ran from 0.80 (scene 5, 24 short
#: words) to 1.26 (scene 3, whose "simultaneously." alone lasted 2.07 s) times this estimate.
SECONDS_PER_SPOKEN_WORD = 0.40
#: Added to an ESTIMATED narration before its clip is bought. With the slow-down allowance a
#: clip bought on the estimate covers words up to 1.10 x 1.25 = 1.375 times as long as the
#: estimate, above the worst of babcf272's five takes (1.26).
NARRATION_ESTIMATE_MARGIN = 0.10
#: Added to a MEASURED narration before its clip is bought: two frames.
MEASURED_NARRATION_MARGIN_SECONDS = 2 / TIMELINE_FPS
#: The shortest an ESTIMATED narration can turn out, as a share of the estimate: the fastest
#: of babcf272's five takes (scene 5, 7.662 s trimmed for 24 words, 9.6 s estimated) ran at
#: 0.80 of it; 0.75 leaves a margin. Only a clip too short even for that is refused before a
#: word is voiced (review of 2026-10-10: a 5.0 s clip under 30 words, 12 s estimated, was read
#: «se încetinește local … (+140%)», his press bought the narration and the render refused).
#: Wrongly refusing asks him for money; wrongly accepting costs the narration's cents, after
#: which the render measures and decides.
FASTEST_SPOKEN_SHARE = 0.75
#: The most a render's trim can cut from a take that carries no word timing: babcf272's takes
#: measured up to 0.09 s of silence before the words and 0.96 s after them (scene 2).
UNTIMED_TRIM_MAX_SECONDS = 1.0
#: Where a scene's narration length comes from, best first: the trimmed length the newest
#: render measured from these very takes; the takes' own lengths (never shorter than trimmed);
#: its words x SECONDS_PER_SPOKEN_WORD; nothing (a silent scene keeps its plan). A clip is
#: never bought shorter than the span a refused render measured for the same words
#: (NARRATION_REFUSED, `clip_plan`).
NARRATION_RENDERED = "rendered"
NARRATION_MEASURED = "measured"
NARRATION_ESTIMATED = "estimated"
NARRATION_PLANNED = "planned"
NARRATION_REFUSED = "refused"
#: A filmed scene whose clip is too short to be slowed into its shot span (beyond
#: SLOWDOWN_ALLOWANCE): its motion is redone at the right length. (NO_SHOT, NO_STILL: the
#: shooting sheet's other two reasons, `sheet_words`.)
CLIP_SHORT = "CLIP_SHORT"
#: A refused assembly, with each refused scene's reading: {storyboard_id, stage ("precheck":
#: before anything is voiced; "render": after the narration was measured), job_id,
#: environment, scenes: [{scene_index, code, clip_seconds, span, needed_seconds, take_id,
#: reason_ro}], reason_ro}. The sheet shows the newest one until a film is assembled.
ASSEMBLY_REFUSED_EVENT = "media.assembly_refused"
#: The paid motion redo the studio raised for a scene refused as CLIP_SHORT, and its outcome:
#: {storyboard_id, scene_index, plan_hash, billed_seconds, credits, cap_credits, cost_usd,
#: status, approval_id, reason_ro}.
CLIP_REDO_PROPOSED_EVENT = "media.clip_redo_proposed"
#: Half a frame of the timeline: a clip this close to its span covers it.
_HALF_FRAME = 0.5 / TIMELINE_FPS

_SPOKEN_TOKEN = re.compile(r"\d+(?:[.,:]\d+)*|[^\W\d_]+(?:['’][^\W\d_]+)*")


def spoken_words(text: str) -> int:
    """How many words a voice says for ``text``. A number is said in words too: one or two
    digits as one word, three as two, four or more as three ("1964", «nineteen sixty-four»)."""
    said = 0
    for token in _SPOKEN_TOKEN.findall(str(text or "")):
        if token[0].isdigit():
            digits = sum(1 for character in token if character.isdigit())
            said += 1 if digits <= 2 else 2 if digits == 3 else 3
        else:
            said += 1
    return said


def estimated_narration_seconds(text: str) -> float:
    """How long the studio's voice will take to say ``text``, before it is voiced."""
    return round(spoken_words(text) * SECONDS_PER_SPOKEN_WORD, 3)


def _rendered_narration(
    session: Session, storyboard_id: str
) -> dict[int, tuple[float, frozenset[str]]]:
    """Per scene, the trimmed narration length the newest render measured (``audio_seconds``,
    what its shot span was cut from) and the narration takes it was said from. Empty for a
    render with no kept takes (a placeholder voice). A FAILED render keeps them too
    (`_fail_job` writes what was built)."""
    jobs = session.scalars(
        select(VideoRenderJob)
        .where(VideoRenderJob.storyboard_id == storyboard_id)
        .order_by(VideoRenderJob.started_at.desc())
        .limit(5)
    ).all()
    for job in jobs:
        production = job.production_json if isinstance(job.production_json, dict) else {}
        found: dict[int, tuple[float, frozenset[str]]] = {}
        for entry in production.get("scenes") or []:
            if not isinstance(entry, dict):
                continue
            said = entry.get("audio_seconds")
            takes = entry.get("narration_takes")
            if (
                isinstance(said, int | float)
                and not isinstance(said, bool)
                and isinstance(takes, list)
                and takes
            ):
                found[int(entry.get("scene_index") or 0)] = (
                    float(said),
                    frozenset(str(take) for take in takes),
                )
        if found:
            return found
    return {}


@dataclass(frozen=True)
class NarrationReading:
    """How long a scene's narration lasts (``seconds``: what its clip is sized and its span
    read from), where that comes from (``source``), and the shortest the render can measure
    it (``least``: ``seconds`` itself once a render measured it)."""

    seconds: float
    source: str
    least: float


@dataclass(frozen=True)
class _KeptTake:
    """A kept take's sidecar as `take_word_timing` reads a voice's result."""

    raw_response: dict[str, Any] | None
    word_timings: Any


def _timed_seconds(kept: dict[str, Any], vendor_seconds: float) -> float | None:
    """The length of a kept take's words by the vendor's own word timing (first word's start
    to last word's end), or None when the take carries none. The render's trim never cuts into
    a timed word (`_trimmed_take`), so it never measures the take shorter than this."""
    raw = kept.get("raw_response")
    words = take_word_timing(
        _KeptTake(
            raw_response=raw if isinstance(raw, dict) else None,
            word_timings=kept.get("word_timings"),
        )
    )
    if not words:
        return None
    said = max(float(word["end"]) for word in words) - min(float(word["start"]) for word in words)
    return min(vendor_seconds, said) if said > 0 else None


def narration_readings(
    session: Session, storyboard_id: str, scenes: Sequence[dict[str, Any]]
) -> dict[int, NarrationReading]:
    """Per scene with words: its `NarrationReading`. 0 credits: reads the takes' sidecars and
    the render records, calls no voice.

    NARRATION_RENDERED when the newest render measured takes that are all current takes of
    these words (trimmed, exactly what its span was cut from). Else NARRATION_MEASURED from
    the kept takes of its words as they are now, every part present: one voice's, or (a
    dialogue, one take per speaker, each in its own voice) the newest take of each part; the
    longest such reading, at the vendor's lengths, never shorter than the trimmed ones; its
    ``least`` is the shortest by the words' own timing (or the vendor's length less
    UNTIMED_TRIM_MAX_SECONDS without one). Else NARRATION_ESTIMATED from its words
    (`estimated_narration_seconds`), ``least`` at FASTEST_SPOKEN_SHARE of it.

    2026-10-10 (review): a dialogue scene's takes are in two voices, and the reading wanted
    every part from ONE voice: such a scene stayed ESTIMATED even after a render measured it,
    the sheet said «Pregătit» for a clip every render refused, and its redo was priced at the
    estimate, below what the refusal said its words need."""
    wanted: dict[int, tuple[str, str]] = {}
    for scene in scenes:
        words = " ".join(str(scene.get("voiceover_segment") or "").split())
        if words:
            wanted[int(scene["scene_index"])] = (_text_sha(words), words)
    if not wanted:
        return {}
    rows = session.scalars(
        select(SceneTake)
        .where(
            SceneTake.storyboard_id == storyboard_id,
            SceneTake.kind == NARRATION_KIND,
            SceneTake.status.in_(REUSABLE_TAKE_STATUSES),
        )
        .order_by(SceneTake.created_at)
    ).all()
    # Each kept take of the words as they are now: (vendor seconds, timed seconds, take id),
    # by part, per (scene, parts, voice) and per (scene, parts) across voices (the newest of
    # each part wins: the rows come oldest first).
    by_voice: dict[tuple[int, int, str], dict[int, tuple[float, float, str]]] = {}
    by_part: dict[tuple[int, int, str], dict[int, tuple[float, float, str]]] = {}
    current: dict[int, set[str]] = {}
    for row in rows:
        index = int(row.scene_number)
        if index not in wanted or not row.path:
            continue
        path = Path(row.path)
        try:
            kept = json.loads(_sidecar(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(kept, dict) or not path.is_file():
            continue
        if kept.get("scene_text_sha256") != wanted[index][0]:
            continue
        seconds = kept.get("duration_seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, int | float) or seconds <= 0:
            seconds = row.seconds
        if not isinstance(seconds, int | float) or seconds <= 0:
            continue
        timed = _timed_seconds(kept, float(seconds))
        least = timed if timed is not None else max(0.0, seconds - UNTIMED_TRIM_MAX_SECONDS)
        parts = max(1, int(kept.get("parts") or 1))
        part = int(kept.get("part") or 0)
        take = (float(seconds), float(least), row.id)
        current.setdefault(index, set()).add(row.id)
        by_voice.setdefault((index, parts, str(kept.get("voice_key") or "")), {})[part] = take
        by_part.setdefault((index, parts, ""), {})[part] = take
    complete: dict[int, list[tuple[float, float]]] = {}
    for (index, parts, _voice), group in (*by_voice.items(), *by_part.items()):
        if not all(part in group for part in range(parts)):
            continue
        gaps = SPEAKER_GAP_SECONDS * (parts - 1)
        complete.setdefault(index, []).append(
            (
                sum(group[part][0] for part in range(parts)) + gaps,
                sum(group[part][1] for part in range(parts)) + gaps,
            )
        )
    rendered = _rendered_narration(session, storyboard_id) if current else {}
    readings: dict[int, NarrationReading] = {}
    for index, (_digest, words) in wanted.items():
        measured = rendered.get(index)
        if measured is not None and measured[1] <= current.get(index, set()):
            readings[index] = NarrationReading(measured[0], NARRATION_RENDERED, measured[0])
        elif complete.get(index):
            longest = max(vendor for vendor, _least in complete[index])
            shortest = min(least for _vendor, least in complete[index])
            readings[index] = NarrationReading(longest, NARRATION_MEASURED, min(longest, shortest))
        else:
            estimate = estimated_narration_seconds(words)
            readings[index] = NarrationReading(
                estimate, NARRATION_ESTIMATED, round(estimate * FASTEST_SPOKEN_SHARE, 3)
            )
    return readings


def scene_narration_lengths(
    session: Session, storyboard_id: str, scenes: Sequence[dict[str, Any]]
) -> dict[int, tuple[float, str]]:
    """Per scene with words: how long its narration lasts, and where that comes from
    (`narration_readings`)."""
    return {
        index: (reading.seconds, reading.source)
        for index, reading in narration_readings(session, storyboard_id, scenes).items()
    }


def expected_shot_spans(
    scenes: Sequence[dict[str, Any]], lengths: dict[int, tuple[float, str]]
) -> dict[int, float]:
    """Each scene's shot span as the render cuts it: its narration (``lengths``) plus the
    breath, never past its plan and never cutting a word, on whole frames (`scene_spans`),
    plus the dissolve into the next scene (`shot_spans`). A scene with no words keeps its plan."""
    planned = [float(scene.get("duration_seconds") or 0.0) for scene in scenes]
    spoken = [
        lengths[int(scene["scene_index"])][0] if int(scene["scene_index"]) in lengths else None
        for scene in scenes
    ]
    timed = [
        {**scene, "duration_seconds": span}
        for scene, span in zip(
            scenes,
            scene_spans(planned, spoken, kinds=[scene_kind_of(scene) for scene in scenes]),
            strict=True,
        )
    ]
    return {
        int(scene["scene_index"]): span
        for scene, span in zip(timed, shot_spans(timed), strict=True)
    }


def clip_plan(
    session: Session, storyboard_id: str, scenes: Sequence[dict[str, Any]]
) -> dict[int, dict[str, Any]]:
    """Per filmed scene, the length its clip is bought at: as long as the narration it will
    carry (measured when its take exists, else estimated from its words) plus the breath, the
    dissolve into the next scene and a margin, on whole frames; never shorter than its plan
    (`motion_seconds`). {seconds, planned_seconds, spoken_seconds, source}. The motion plan,
    the sheet and a motion redo price this length; the planner rounds it up to a length the
    scene's model accepts (`cost_plan.billable_seconds` with the model's contract).

    Never shorter, either, than the span the newest refused render measured for a scene it
    refused as CLIP_SHORT, while its words are the ones that render said (source
    NARRATION_REFUSED): a redo bought on a reading of the words that came out shorter than the
    render's (narration takes not kept, say) would be refused again, and paid again."""
    lengths = scene_narration_lengths(session, storyboard_id, scenes)
    joins = scene_joins(list(scenes))
    floors = _refused_spans(session, storyboard_id, scenes)
    sizes: dict[int, dict[str, Any]] = {}
    for position, scene in enumerate(scenes):
        if is_composed(scene):
            continue
        index = int(scene["scene_index"])
        planned = motion_seconds(scene)
        entry: dict[str, Any] = {
            "seconds": planned,
            "planned_seconds": planned,
            "spoken_seconds": None,
            "source": NARRATION_PLANNED,
        }
        found = lengths.get(index)
        if found is not None:
            said, source = found
            dissolve = joins[position + 1] if position + 1 < len(joins) else 0.0
            voiced = _voiced_clip_seconds(said, source, dissolve)
            entry["spoken_seconds"] = round(said, 3)
            if voiced > planned:
                entry.update(seconds=voiced, source=source)
        floor = floors.get(index)
        if floor is not None:
            refused = round(whole_frames(floor + MEASURED_NARRATION_MARGIN_SECONDS, up=True), 3)
            if refused > float(entry["seconds"]):
                entry.update(seconds=refused, source=NARRATION_REFUSED)
        sizes[index] = entry
    return sizes


def _voiced_clip_seconds(said: float, source: str, dissolve: float) -> float:
    """The clip ``said`` seconds of words need: the words, the breath, the dissolve into the
    next scene and the margin of where the length comes from (``source``), on whole frames."""
    margin = (
        said * NARRATION_ESTIMATE_MARGIN
        if source == NARRATION_ESTIMATED
        else MEASURED_NARRATION_MARGIN_SECONDS
    )
    return round(whole_frames(said + SPOKEN_TAIL_SECONDS + dissolve + margin, up=True), 3)


def script_clip_seconds(scenes: Sequence[dict[str, Any]]) -> dict[int, float]:
    """Per filmed scene of a script (by position, from 1, as its storyboard numbers them), the
    clip `clip_plan` will buy for it before a word is voiced: its words estimated, plus the
    breath, the dissolve into the next scene and the estimate's margin; never shorter than a
    plan the scene states. What the story review reads a scene's length against its motion
    model's longest clip by (2026-10-10, film 6fe6a577)."""
    joins = scene_joins(list(scenes))
    sizes: dict[int, float] = {}
    for position, scene in enumerate(scenes):
        if is_composed(scene):
            continue
        said = estimated_narration_seconds(
            str(scene.get("narration") or scene.get("voiceover_segment") or "")
        )
        dissolve = joins[position + 1] if position + 1 < len(joins) else 0.0
        voiced = _voiced_clip_seconds(said, NARRATION_ESTIMATED, dissolve) if said > 0 else 0.0
        planned = motion_seconds(scene) if scene.get("duration_seconds") else 0.0
        sizes[position + 1] = max(voiced, planned)
    return sizes


def _words_sha(scene: dict[str, Any]) -> str:
    return _text_sha(str(scene.get("voiceover_segment") or ""))


def _refused_spans(
    session: Session, storyboard_id: str, scenes: Sequence[dict[str, Any]]
) -> dict[int, float]:
    """Per scene the newest refused render measured too short for its clip (CLIP_SHORT), the
    span it measured, while the scene's words are still the ones that render said."""
    refused = latest_assembly_refusal(session, storyboard_id)
    if refused is None or refused.get("stage") != "render":
        return {}
    words = {int(scene["scene_index"]): _words_sha(scene) for scene in scenes}
    spans: dict[int, float] = {}
    for item in refused.get("scenes") or []:
        if not isinstance(item, dict) or item.get("code") != CLIP_SHORT:
            continue
        index = int(item.get("scene_index") or 0)
        span = item.get("span")
        if (
            isinstance(span, int | float)
            and not isinstance(span, bool)
            and span > 0
            and item.get("words_sha256")
            and item.get("words_sha256") == words.get(index)
        ):
            spans[index] = float(span)
    return spans


def clip_seconds_by_scene(
    engine: Engine, storyboard_id: str, scenes: Sequence[dict[str, Any]]
) -> dict[int, float]:
    """`clip_plan`'s lengths alone, per filmed scene."""
    with Session(engine) as session:
        return {
            index: float(entry["seconds"])
            for index, entry in clip_plan(session, storyboard_id, scenes).items()
        }


def min_clip_seconds(span: float) -> float:
    """The shortest clip that fills ``span`` once slowed down by at most SLOWDOWN_ALLOWANCE."""
    return float(span) / (1.0 + SLOWDOWN_ALLOWANCE)


def clip_stretch(clip_seconds: float | None, span: float) -> float:
    """How many times slower a clip must play to fill ``span``: 1.0 when it covers it (to
    half a frame), or when its length is unknown."""
    if clip_seconds is None or clip_seconds <= 0 or clip_seconds + _HALF_FRAME >= span:
        return 1.0
    return float(span) / float(clip_seconds)


def clip_fits(clip_seconds: float | None, span: float) -> bool:
    """Whether a clip covers ``span``, or fills it slowed down by at most SLOWDOWN_ALLOWANCE."""
    return clip_stretch(clip_seconds, span) <= 1.0 + SLOWDOWN_ALLOWANCE + 1e-9


def _percent_longer(clip_seconds: float, span: float) -> int:
    return math.ceil((float(span) / float(clip_seconds) - 1.0) * 100 - 1e-6)


def clip_short_words(
    scene_index: int, clip_seconds: float, span: float, *, estimated: bool = False
) -> str:
    """Why a scene's clip cannot be slowed into its span, in the Owner's words (``estimated``:
    the span was read from words not voiced yet)."""
    return (
        f"Scena {scene_index}: clipul are {ro_decimal(clip_seconds, 1)} s, iar cadrul lui cere "
        f"{ro_decimal(span)} s{' după narațiunea estimată' if estimated else ''}: ar "
        f"trebui încetinit cu {_percent_longer(clip_seconds, span)}%, peste cele "
        f"{round(SLOWDOWN_ALLOWANCE * 100)}% în care studioul îl încetinește local. Mișcarea "
        f"scenei se reface la cel puțin {ro_decimal(span)} s."
    )


def slowed_words(scene_index: int, clip_seconds: float, span: float) -> str:
    """A clip slowed into its span, in the Owner's words."""
    return (
        f"Scena {scene_index}: clipul de {ro_decimal(clip_seconds, 1)} s se încetinește local la "
        f"{ro_decimal(span)} s (+{_percent_longer(clip_seconds, span)}%), 0 USD."
    )


def clip_risk_words(
    scene_index: int, clip_seconds: float, least_span: float, span: float, *, estimated: bool
) -> str:
    """A clip that may be too short for words not measured yet, in the Owner's words."""
    after = "după narațiunea estimată" if estimated else "după narațiunea înregistrată"
    return (
        f"Scena {scene_index}: clipul de {ro_decimal(clip_seconds, 1)} s poate fi prea scurt: "
        f"{after}, cadrul lui va avea între {ro_decimal(least_span)} și {ro_decimal(span)} s, "
        f"iar studioul îl încetinește local cu cel mult {round(SLOWDOWN_ALLOWANCE * 100)}%. "
        "Asamblarea măsoară narațiunea și decide; dacă e prea scurt, studioul propune "
        "refacerea mișcării."
    )


def clip_readiness(
    session: Session,
    storyboard_id: str,
    scene: dict[str, Any],
    still_sha256: str | None,
    *,
    span: float,
    environment: str,
    from_prompt: bool = False,
    least_span: float | None = None,
    estimated: bool = False,
) -> dict[str, Any]:
    """Whether a filmed scene's shot may be cut into its film: the one reading the shooting
    sheet shows, the pre-check of `assemble_from_takes` makes before anything is voiced, and
    the render makes once the narration is measured (2026-10-09, babcf272).

    The shot is the scene's usable take for its shot identity (`motion_fields` with this
    still's sha256 and ``from_prompt``; APPROVED first), at least `min_clip_seconds` of
    ``span`` long as its file measures (`shot_clip_seconds`), accepted (`clip_accepted`: his
    APPROVED or a passing clip QC; in TEST also one nobody could check). ``how`` is "shot" (it
    covers its span) or "slowed" (it fills it slowed down by ``slowed_by``, at most
    SLOWDOWN_ALLOWANCE). Not ready: ``code`` NO_SHOT (none, or one not accepted: ``why_ro``
    says why) or CLIP_SHORT (only a clip too short to be slowed into the span).

    ``least_span``: the span is not measured yet (words not voiced, ``estimated``; or voiced
    and not trimmed by a render) and could come out as short as this. A clip too short for
    ``span`` that fits ``least_span`` is ready "at_risk": no slow-down is promised, ``risk_ro``
    says so, and the render measures the words and decides; a clip too short even for
    ``least_span`` is CLIP_SHORT before anything is bought (review of 2026-10-10).

    Returns {scene_index, ok, how, code, why_ro, take_id, clip_seconds, span, needed_seconds,
    slowed_by, risk_ro}. Reads only.
    """
    index = int(scene["scene_index"])
    fields = motion_fields(scene, still_sha256, from_prompt=from_prompt)
    least = min_clip_seconds(span)
    shortest = min_clip_seconds(least_span) if least_span is not None else least
    reading: dict[str, Any] = {
        "scene_index": index,
        "ok": False,
        "how": None,
        "code": None,
        "why_ro": "",
        "take_id": None,
        "clip_seconds": None,
        "span": round(float(span), 3),
        "needed_seconds": round(least, 3),
        "slowed_by": None,
        "risk_ro": "",
    }
    shot = _shot_take(session, storyboard_id, index, fields, least)
    at_risk = False
    if shot is None and shortest < least:
        shot = _shot_take(session, storyboard_id, index, fields, shortest)
        at_risk = shot is not None
    if shot is not None:
        have = shot_clip_seconds(shot)
        accepted, why = clip_accepted(session, shot, environment)
        reading.update(take_id=shot.id, clip_seconds=round(have, 3) if have else have)
        if not accepted:
            return {**reading, "code": NO_SHOT, "why_ro": why}
        if at_risk and have:
            return {
                **reading,
                "ok": True,
                "how": "at_risk",
                "risk_ro": clip_risk_words(
                    index, have, float(least_span or span), span, estimated=estimated
                ),
            }
        stretch = clip_stretch(have, span)
        return {
            **reading,
            "ok": True,
            "how": "slowed" if stretch > 1.0 else "shot",
            "slowed_by": round(stretch, 4) if stretch > 1.0 else None,
        }
    short = _shot_take(session, storyboard_id, index, fields, 0.0)
    have = shot_clip_seconds(short) if short is not None else None
    if short is not None and have:
        accepted, why = clip_accepted(session, short, environment)
        words = clip_short_words(index, have, span, estimated=estimated)
        return {
            **reading,
            "code": CLIP_SHORT,
            "take_id": short.id,
            "clip_seconds": round(have, 3),
            "why_ro": words if accepted else f"{words} {why}",
        }
    refusal, _record = _scene_clip_refusal(session, storyboard_id, index)
    return {**reading, "code": NO_SHOT, "why_ro": refusal or ""}


def assembly_readiness(
    session: Session,
    storyboard_id: str,
    scenes: Sequence[dict[str, Any]],
    stills: dict[int, str | None],
    *,
    environment: str,
    local_moves: set[int],
    from_prompt: bool = False,
) -> list[dict[str, Any]]:
    """Whether each filmed scene can go into the film assembled from its takes, and why not:
    what the shooting sheet shows and `assemble_from_takes` checks before anything is voiced.

    ``stills`` maps each filmed scene to its approved still's sha256 (None: it has none, code
    NO_STILL). The span is the one the render will cut (`expected_shot_spans` over
    `narration_readings`), and the shortest it can come out (the same over each reading's
    ``least``) until a render measured the words; each reading is `clip_readiness`'s, with
    ``span_source`` and the sheet's ``reason_ro``. A scene without a shot it may cut in is
    ready only by the Owner's LOCAL_MOVE for it, or as a still in TEST."""
    narration = narration_readings(session, storyboard_id, scenes)
    spans = expected_shot_spans(
        scenes, {index: (said.seconds, said.source) for index, said in narration.items()}
    )
    least_spans = expected_shot_spans(
        scenes, {index: (said.least, said.source) for index, said in narration.items()}
    )
    readings: list[dict[str, Any]] = []
    for scene in scenes:
        if scene_kind_of(scene) != LIVE_KIND:
            continue
        index = int(scene["scene_index"])
        source = narration[index].source if index in narration else NARRATION_PLANNED
        sha = stills.get(index)
        if not sha:
            readings.append(
                {
                    "scene_index": index,
                    "ok": False,
                    "how": None,
                    # the code lets the assemble card group the scenes (`blocked_words`)
                    "code": NO_STILL,
                    "why_ro": "",
                    "reason_ro": (
                        f"Scena {index} nu are o imagine aprobată pentru promptul de acum; "
                        "cumpărați sau aprobați imaginea ei pe foaia de filmare."
                    ),
                    "span": round(spans[index], 3),
                    "span_source": source,
                    "least_span": (
                        round(least_spans[index], 3) if least_spans[index] < spans[index] else None
                    ),
                }
            )
            continue
        reading = clip_readiness(
            session,
            storyboard_id,
            scene,
            sha,
            span=spans[index],
            environment=environment,
            from_prompt=from_prompt,
            least_span=least_spans[index] if least_spans[index] < spans[index] else None,
            estimated=source == NARRATION_ESTIMATED,
        )
        reading["span_source"] = source
        # The shortest the span can come out while the words are not measured yet (None once
        # they are): what the sheet's «Aleg totuși acest clip» reads each clip against
        # (`clip_fit`), as this reading reads the scene's own shot.
        reading["least_span"] = (
            round(least_spans[index], 3) if least_spans[index] < spans[index] else None
        )
        if reading["ok"]:
            reading["reason_ro"] = (
                slowed_words(index, float(reading["clip_seconds"]), spans[index])
                if reading["how"] == "slowed"
                else ""
            )
        elif index in local_moves:
            reading.update(
                ok=True,
                how="local_move",
                reason_ro=f"Scena {index}: imagine fixă animată local, aleasă de Proprietar.",
            )
        elif environment != "PRODUCTION":
            reading.update(
                ok=True,
                how="still",
                reason_ro=f"Scena {index}: fără cadru acceptat, rămâne imagine fixă (TEST).",
            )
        elif reading["code"] == CLIP_SHORT:
            reading["reason_ro"] = (
                f"{reading['why_ro']} Sau alege „imagine fixă animată local” pentru ea pe "
                "foaia de filmare."
            )
        else:
            why = str(reading["why_ro"] or "")
            reading["reason_ro"] = (
                (f"{why} " if why else "")
                + f"Scena {index} nu are un cadru acceptat, iar Proprietarul nu a ales "
                "„imagine fixă animată local” pentru ea pe foaia de filmare."
            )
        readings.append(reading)
    return readings


def record_assembly_refused(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    refusal: ClipsNotAccepted,
    *,
    stage: str,
    environment: str,
    job_id: str | None = None,
) -> str:
    """The refused assembly, as ASSEMBLY_REFUSED_EVENT, with each refused scene's seconds (its
    reading in ``refusal.details``) and the words they were read for (``words_sha256``): what
    the sheet shows, what `propose_clip_redos` reads for the scenes whose motion must be
    redone longer, and the floor `clip_plan` sizes their redo from. Returns the event id."""
    readings = {int(item.get("scene_index") or 0): item for item in refusal.details}
    with Session(engine) as session, session.begin():
        words = {
            int(index): _words_sha({"voiceover_segment": said})
            for index, said in session.execute(
                select(StoryboardScene.scene_index, StoryboardScene.voiceover_segment).where(
                    StoryboardScene.storyboard_id == storyboard_id
                )
            )
        }
        scenes = []
        for index in refusal.scenes:
            item = readings.get(int(index), {})
            scenes.append(
                {
                    "scene_index": int(index),
                    "code": item.get("code") or NO_SHOT,
                    "clip_seconds": item.get("clip_seconds"),
                    "span": item.get("span"),
                    "needed_seconds": item.get("needed_seconds"),
                    "take_id": item.get("take_id"),
                    "words_sha256": words.get(int(index)),
                    "reason_ro": str(item.get("why_ro") or item.get("reason_ro") or ""),
                }
            )
        event = append_event(
            session,
            ASSEMBLY_REFUSED_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {
                "storyboard_id": storyboard_id,
                "stage": stage,
                "job_id": job_id,
                "environment": environment,
                "scenes": scenes,
                "reason_ro": refusal.message_ro,
            },
            correlation_id,
        )
        return str(event.event_id)


def _longest_shot_since(engine: Engine, storyboard_id: str, scene_index: int, since: str) -> float:
    """The longest clip of the scene bought or sent after ``since``: as its file measures
    (`shot_clip_seconds`), else as billed (a clip still on its way)."""
    with Session(engine) as session:
        rows = session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == scene_index,
                SceneTake.kind.in_(SHOT_TAKE_KINDS),
                SceneTake.status.in_(("APPROVED", "PAID", "SUBMITTED")),
                SceneTake.created_at > since,
            )
        ).all()
        return max((shot_clip_seconds(row) or 0.0 for row in rows), default=0.0)


def latest_assembly_refusal(session: Session, storyboard_id: str) -> dict[str, Any] | None:
    """The newest refused assembly of the film (its event's payload, with ``at``), or None
    when there is none or a film was assembled since."""
    event = session.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.event_type == ASSEMBLY_REFUSED_EVENT,
            DomainEvent.aggregate_id == storyboard_id,
        )
        .order_by(DomainEvent.sequence.desc())
        .limit(1)
    ).first()
    if event is None or not isinstance(event.payload, dict):
        return None
    assembled = session.scalar(
        select(VideoRenderJob.id)
        .where(
            VideoRenderJob.storyboard_id == storyboard_id,
            VideoRenderJob.status == "COMPLETED",
            VideoRenderJob.started_at > str(event.timestamp),
        )
        .limit(1)
    )
    if assembled is not None:
        return None
    return {**event.payload, "at": str(event.timestamp), "event_id": event.event_id}


def propose_clip_redos(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    *,
    wiring: dict[str, Any],
    settings: Any | None = None,
    registry: Any = None,
    environment: str | None = None,
    scenes: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    """The studio raises, itself, the paid motion redo of each scene its newest refused
    assembly named CLIP_SHORT (a clip too short to be slowed into its span), at the length
    its narration needs (`clip_plan`, through `redo_plan`).

    Only through `redo_scene` with ``unasked=True``: the Policy Kernel, his paid-media rule
    (his question on the sheet and in the Decisions window, bound to the redo's plan_hash),
    the budgets, the film's ceiling and lease all decide; nothing is bought that his rule does
    not let through, and a question already waiting is the same question (`request_approval`
    dedupes). A clip the Owner approved himself is never retired by it unasked: the redo of it
    is his question, even where his rule and mode would let it buy unasked (``proposal``, his
    card of 2026-10-10), and nothing is retired or bought before his yes for this plan; once
    he said yes, the redo raised again (the next FILM_CONTINUE, his next press) spends it and
    retires the clip it replaces (`_owner_yes_for_redo`). ``wiring`` is the shooting sheet's
    (`runbook.stages.sheet_wiring`): integration_id, capabilities, adapter_for_model,
    account, image_adapter, resolution, storage_root.
    ``scenes`` narrows it. Each outcome is an event (CLIP_REDO_PROPOSED_EVENT) and is returned:
    {scene_index, status (NEEDS_APPROVAL, BOUGHT, or the refusal's), approval_id, plan_hash,
    billed_seconds, cost_usd, cap_usd, reason_ro}."""
    with Session(engine) as session:
        refused = latest_assembly_refusal(session, storyboard_id)
    if refused is None:
        return []
    wanted = [
        int(item["scene_index"])
        for item in refused.get("scenes") or []
        if isinstance(item, dict)
        and item.get("code") == CLIP_SHORT
        and (scenes is None or int(item["scene_index"]) in scenes)
    ]
    # Each scene's own reason (its seconds), said on his question.
    reasons = {
        int(item["scene_index"]): str(item.get("reason_ro") or "").split(" Sau alege")[0]
        for item in refused.get("scenes") or []
        if isinstance(item, dict) and item.get("code") == CLIP_SHORT
    }
    needed = {
        int(item["scene_index"]): float(item.get("needed_seconds") or 0.0)
        for item in refused.get("scenes") or []
        if isinstance(item, dict) and item.get("code") == CLIP_SHORT
    }
    # A scene whose longer clip was bought (or sent) since the refusal is not redone again:
    # the next assembly reads that clip (each redo is a new purchase).
    at = str(refused.get("at") or "")
    wanted = [
        index
        for index in wanted
        if not 0.0 < needed.get(index, 0.0) <= _longest_shot_since(engine, storyboard_id, index, at)
    ]
    capabilities = list(wiring.get("capabilities") or []) or None
    resolution = wiring.get("resolution") or getattr(settings, "motion_resolution", None)
    from app.media.shooting_sheet import price_table_for  # noqa: PLC0415 - it imports us

    # One price path (WP20): the connection's measured prices, RunPod's and the local ones, as
    # the sheet's own «Refă mișcarea» prices it, never the raw published table alone.
    table = price_table_for(engine, wiring.get("integration_id"))
    outcomes: list[dict[str, Any]] = []
    for index in wanted:
        plan: dict[str, Any] = {}
        outcome: dict[str, Any] = {"scene_index": index}
        try:
            plan = redo_plan(
                engine,
                storyboard_id,
                "motion",
                index,
                capabilities=capabilities,
                integration_id=wiring.get("integration_id"),
                resolution=resolution,
                table=table,
            )
            if not plan.get("buyable"):
                raise SceneRedoRefused(
                    "NOTHING_TO_BUY", str(plan.get("reason_ro") or ""), plan=plan
                )
            done = redo_scene(
                engine,
                storyboard_id,
                correlation_id,
                kind="motion",
                scene_index=index,
                plan_hash=str(plan["plan_hash"]),
                image_adapter=wiring.get("image_adapter"),
                adapter_for_model=wiring.get("adapter_for_model"),
                capabilities=capabilities,
                account=wiring.get("account"),
                registry=registry,
                resolution=resolution,
                settings=settings,
                environment=environment,
                integration_id=wiring.get("integration_id"),
                table=table,
                ffmpeg_path=getattr(settings, "ffmpeg_path", None),
                storage_root=wiring.get("storage_root"),
                note=(
                    (
                        reasons.get(index)
                        or f"Scena {index}: clipul este prea scurt pentru narațiunea lui."
                    )
                    + f" Studioul propune refacerea mișcării la {plan.get('billed_seconds')} s."
                ),
                # Nobody pressed it: his paid-media rule asks him (or lets his mode decide),
                # and a clip he approved himself is always his question (``proposal``).
                unasked=True,
                proposal=True,
            )
            outcome.update(status="BOUGHT", credits=done.get("credits"), reason_ro="")
        except SceneRedoRefused as exc:
            plan = exc.plan or plan
            outcome.update(
                status=exc.status, approval_id=exc.approval_id, reason_ro=exc.reason_ro[:500]
            )
        except SpentStageError as exc:
            outcome.update(status="SPENT_STOPPED", reason_ro=exc.reason_ro[:500])
        except (UnpricedError, ValueError) as exc:
            # No model or price holds the length its words need: said, never a silent stop.
            outcome.update(status="UNPRICED", reason_ro=str(exc)[:500])
        outcome.update(
            plan_hash=plan.get("plan_hash"),
            billed_seconds=plan.get("billed_seconds"),
            credits=outcome.get("credits", plan.get("credits")),
            cost_usd=plan.get("cost_usd"),
            cap_usd=plan.get("cap_usd"),
        )
        outcome.setdefault("approval_id", None)
        with Session(engine) as session, session.begin():
            append_event(
                session,
                CLIP_REDO_PROPOSED_EVENT,
                "storyboard",
                storyboard_id,
                1,
                {"storyboard_id": storyboard_id, **outcome},
                correlation_id,
            )
        outcomes.append(outcome)
    return outcomes


# --------------------------------------------------------------- clip QC on the shot takes
#
# Every shot the motion staircase buys is checked before anything else happens to it
# (qc.check_clip: its motion against the floor of its camera move, a hard cut, YuNet on its
# first, middle and last frames when the bible forbids faces, and the vision model's look).
# The report is kept on the take, as an event. A clip a check measured wrong is REJECTED and
# never cut in; a clip nobody could check stays PAID and waits for the Owner's look: in
# PRODUCTION only his APPROVED or a passing report lets a shot into the film.

#: The event a shot's clip-QC report is kept in, on its take (aggregate ``scene_take``).
CLIP_QC_EVENT = "media.clip_qc_checked"
#: The failure code of a shot the studio's clip check, not the vendor, refused.
CLIP_QC_FAILURE_CODE = "QC.CLIP"


def clip_report_record(report: Any) -> dict[str, Any]:
    """A ``qc.ClipReport`` as the take's event and the scene's record keep it.

    ``verdict`` is PASSED; FAILED when a check measured the clip wrong (the take is
    rejected); or UNCHECKED when every block is a check that could not run, which a retry
    cannot repair: the clip was paid for and waits for the Owner's look.
    """
    checks = [
        {
            "code": item.code,
            "status": item.status,
            "blocking": bool(item.blocking),
            "value": item.value,
            "detail_ro": item.detail_ro,
        }
        for item in report.checks
    ]
    if report.passed:
        verdict = "PASSED"
    elif any(item["blocking"] and item["status"] == "FAILED" for item in checks):
        verdict = "FAILED"
    else:
        verdict = "UNCHECKED"
    return {
        "scene": int(report.scene),
        "passed": bool(report.passed),
        "verdict": verdict,
        "checks": checks,
        "blocks_ro": list(report.blocks_ro),
        "warnings_ro": list(report.warnings_ro),
        "unmeasured": list(report.unmeasured),
        "measured": json.loads(json.dumps(report.measured or {}, default=str)),
    }


#: The Owner's renders cap (2026-10-15, `runbook.stages.RENDERS_PER_LAYER`): a scene's still
#: made three times is the scene's picture whatever the clip's look finds in it.
RENDERS_PER_LAYER = 3


def _still_at_renders_cap(engine: Engine, storyboard_id: str, scene_number: int) -> bool:
    """Whether the scene's still has been made RENDERS_PER_LAYER times (every paid request
    among its takes): a clip refused for the picture's fault cannot send it back for a fourth."""
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(SceneTake).where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.scene_number == int(scene_number),
                    SceneTake.kind == "still",
                )
            )
        )
    return _paid_attempts(rows, "still") >= RENDERS_PER_LAYER


def _keep_clip_under_cap(
    engine: Engine,
    take_id: str,
    record: dict[str, Any],
    *,
    storyboard_id: str,
    scene_number: int,
    seed: int | None,
    attempt: int,
    correlation_id: str,
) -> dict[str, Any]:
    """A clip refused for its picture's fault when the picture is at the renders cap: the
    clip stands as the scene's shot, accepted under the Owner's cap (`CAP_APPROVER`), its
    refusal kept as the lesson in its quality note and in the record (04:11Z, 7c26a7ce
    scenes 1-3: the stills kept under the cap carried a window, every clip of them was sent
    back to a still that could not be bought again, and the film stood still)."""
    kept = {
        **record,
        "verdict": "PASSED",
        "passed": True,
        "accepted_by": CAP_APPROVER,
        "accepted_under_cap": True,
        "cap_note_ro": (
            f"Acceptat sub plafonul Proprietarului ({RENDERS_PER_LAYER} randări ale imaginii): "
            "clipul rămâne; ce a rămas sub standard e lecție pentru filmul următor."
        ),
    }
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        row = session.get(SceneTake, take_id)
        if row is not None:
            row.status = "PAID"
            row.approved_by = CAP_APPROVER
            row.failure_code = None
            row.failure_detail = None
            row.updated_at = utc_now()
            sync_take_quality(
                session,
                row,
                accepted=True,
                reason=(kept["cap_note_ro"] + " " + "; ".join(record.get("blocks_ro") or []))[
                    :4000
                ],
            )
        append_event(
            session,
            CLIP_QC_EVENT,
            "scene_take",
            take_id,
            1,
            {
                "storyboard_id": storyboard_id,
                "scene_number": scene_number,
                "take_id": take_id,
                "seed": seed,
                "attempt": attempt,
                **kept,
            },
            correlation_id,
        )
    return kept


def _keep_clip_report(
    engine: Engine,
    take_id: str,
    record: dict[str, Any],
    *,
    storyboard_id: str,
    scene_number: int,
    seed: int | None,
    attempt: int,
    correlation_id: str,
) -> None:
    """Write one clip's report on its take; a clip measured wrong is REJECTED (QC.CLIP)."""
    with Session(engine) as session, session.begin():
        lock_for_write(session)  # read-then-write right after a purchase
        row = session.get(SceneTake, take_id)
        if row is not None and record["verdict"] == "FAILED" and row.status == "PAID":
            row.status = "REJECTED"
            row.failure_code = CLIP_QC_FAILURE_CODE
            row.failure_detail = ("Controlul clipului: " + "; ".join(record["blocks_ro"]))[
                :TAKE_DETAIL_MAX
            ]
            row.updated_at = utc_now()
        if row is not None and record["verdict"] in ("PASSED", "FAILED"):
            sync_take_quality(
                session,
                row,
                accepted=record["verdict"] == "PASSED",
                reason="; ".join(record["blocks_ro"]),
            )
        append_event(
            session,
            CLIP_QC_EVENT,
            "scene_take",
            take_id,
            1,
            {
                "storyboard_id": storyboard_id,
                "scene_number": scene_number,
                "take_id": take_id,
                "seed": seed,
                "attempt": attempt,
                **record,
            },
            correlation_id,
        )


def clip_qc_of(session: Session, take_id: str) -> dict[str, Any] | None:
    """The latest clip-QC report kept on a take, or None when it was never checked."""
    event = session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == CLIP_QC_EVENT, DomainEvent.aggregate_id == take_id)
        .order_by(DomainEvent.sequence.desc())
        .limit(1)
    ).first()
    return dict(event.payload) if event is not None and isinstance(event.payload, dict) else None


def clip_accepted(session: Session, take: SceneTake, environment: str) -> tuple[bool, str]:
    """Whether a usable shot take may be cut into the film, and the Owner's reason when not.

    His APPROVED look accepts it; otherwise its clip QC must have passed. In TEST a paid shot
    nobody could check is used (the rehearsal's takes predate clip QC); in PRODUCTION it
    waits for his look on the sheet.
    """
    if take.status == "APPROVED":
        return True, ""
    record = clip_qc_of(session, take.id) or {}
    verdict = record.get("verdict")
    if verdict == "PASSED":
        return True, ""
    if verdict != "FAILED" and environment != "PRODUCTION":
        return True, ""
    why = "; ".join(str(text) for text in record.get("blocks_ro") or []) or (
        "clipul nu a fost verificat de controlul clipului"
    )
    return False, (
        f"Scena {take.scene_number}: cadrul plătit nu a trecut controlul clipului ({why}) și "
        "Proprietarul nu l-a aprobat pe foaia de filmare."
    )


def _scene_clip_refusal(
    session: Session, storyboard_id: str, scene_number: int
) -> tuple[str | None, dict[str, Any] | None]:
    """Why a scene has no shot to cut in: its latest shot refused by clip QC, and its report."""
    row = session.scalars(
        select(SceneTake)
        .where(
            SceneTake.storyboard_id == storyboard_id,
            SceneTake.scene_number == scene_number,
            SceneTake.kind.in_(SHOT_TAKE_KINDS),
            SceneTake.failure_code == CLIP_QC_FAILURE_CODE,
        )
        .order_by(SceneTake.updated_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None, None
    detail = str(row.failure_detail or "").removeprefix("Controlul clipului: ")
    return (
        f"Scena {scene_number}: cadrul plătit a picat controlul clipului ({detail}).",
        clip_qc_of(session, row.id),
    )


# ------------------------------------------- «Aleg totuși acest clip» (the Owner, 2026-10-10)
#
# 2026-10-10 (film babcf272), his words: «te rog să introduci un buton de accept cadru movie,
# chiar dacă a fost inițial respins». A clip the studio's clip QC had rejected (QC.CLIP: the
# panels, a face, the motion floor), or one he had rejected himself, could not be chosen again:
# the sheet offered its buttons on PAID takes only, so a REJECTED clip with its file on disk was
# a dead end and the scene could only wait for a paid redo. Now:
# - ONE eligibility (`clip_choice`), read by the sheet's button and by `decide_take`: a shot take
#   with its file on disk whose identity still matches the scene (the still it was filmed from,
#   its motion package), whatever its QC verdict. Never a vendor's refusal or a LOST take (no
#   file), and never a clip filmed from a still that is no longer the scene's: the button says
#   why, disabled, and the endpoint answers 409 with the same words.
# - His newest APPROVED decision on a scene's shots wins over the studio's clip QC for that clip
#   (`owner_clip_choice`): the readiness, the render and the motion plan use THAT clip, slowed
#   locally within SLOWDOWN_ALLOWANCE when it is short, else read CLIP_SHORT (WP10's redo
#   proposal, under his rule). Never silently another clip, and never a purchase over his choice.
# - His choice buys nothing (0 credits, no approval asked); FILM_CONTINUE walks the film on, as
#   every take decision of his already does.

#: Why a shot take cannot be chosen (`clip_choice`), and how the sheet says it: "disabled" (the
#: button shown disabled, with the reason) or "none" (no clip to look at, so no button at all).
CLIP_CHOICE_OFFERS: dict[str, str] = {
    "NOT_A_SHOT": "none",
    "NOT_DELIVERED": "none",
    "REFUSED": "none",
    "LOST": "none",
    "SENT_BACK": "none",
    "DUPLICATE": "none",
    "NO_FILE": "none",
    "FILE_CHANGED": "disabled",
    "NO_SCENE": "disabled",
    "NO_STILL": "disabled",
    "STILL_CHANGED": "disabled",
    "PROMPT_CHANGED": "disabled",
}
#: The take statuses a clip may be chosen from: bought and delivered, decided or not.
CLIP_CHOICE_STATUSES: tuple[str, ...] = ("PAID", "APPROVED", "REJECTED")


class ClipChoiceRefused(ValueError):
    """The Owner's «Aleg totuși acest clip» on a take `clip_choice` refuses (409), in his words."""

    def __init__(self, code: str, reason_ro: str) -> None:
        super().__init__(reason_ro)
        self.code = code
        self.reason_ro = reason_ro

    def as_dict(self) -> dict[str, Any]:
        return {"status": "CLIP_NOT_CHOOSABLE", "code": self.code, "message": self.reason_ro}


#: Each checked file's sha256 by (path, size, mtime): the sheet reads every shot of a film on
#: every build, and a clip is megabytes; the same bytes on disk are hashed once.
_FILE_SHA: dict[tuple[str, int, int], str] = {}
_FILE_SHA_MAX = 4096


def _known_file_sha256(path: Path) -> str | None:
    """The file's sha256, hashed once per (path, size, mtime); None when it cannot be read."""
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), int(stat.st_size), int(stat.st_mtime_ns))
    if key not in _FILE_SHA:
        if len(_FILE_SHA) >= _FILE_SHA_MAX:
            _FILE_SHA.clear()
        try:
            _FILE_SHA[key] = _file_sha256(path)
        except OSError:
            return None
    return _FILE_SHA[key]


def shot_identity_matches(take: SceneTake, scene: dict[str, Any], still_sha256: str | None) -> bool:
    """Whether a shot take was filmed for the scene as it is now: from this still with its
    motion package (`motion_fields`), or from its words alone (a TEST rehearsal's shot)."""
    options = [motion_fields(scene, None, from_prompt=True)]
    if still_sha256:
        options.insert(0, motion_fields(scene, still_sha256, from_prompt=False))
    return any(take_hash(fields, take.model_id) == take.prompt_hash for fields in options)


def clip_choice(
    take: SceneTake,
    *,
    scene: dict[str, Any] | None,
    still_sha256: str | None,
    other_stills: Sequence[str | None] = (),
) -> dict[str, Any]:
    """Whether the Owner may choose this shot take as his scene's clip: the one eligibility the
    sheet's «Aleg totuși acest clip» and `decide_take` both read (2026-10-10).

    Eligible: a motion or test-shot take, bought and delivered (PAID, APPROVED or REJECTED: the
    clip QC's verdict and his own earlier «Respinge» do not matter), its file on disk with the
    sha256 it was bought with, filmed for the scene as it is now (``scene``, its approved still
    ``still_sha256``: `shot_identity_matches`). ``other_stills``: the scene's other stills, to
    tell a clip filmed from an older picture from one filmed for another motion prompt.

    Returns {eligible, code, offer ("button" | "disabled" | "none", `CLIP_CHOICE_OFFERS`),
    why_not_ro}. Reads only (the file's bytes, hashed once)."""
    index = int(take.scene_number)

    def refused(code: str, why: str) -> dict[str, Any]:
        offer = CLIP_CHOICE_OFFERS[code]
        return {"eligible": False, "code": code, "offer": offer, "why_not_ro": why}

    if take.kind not in SHOT_TAKE_KINDS:
        return refused(
            "NOT_A_SHOT", "Doar un clip filmat (mișcare sau cadru de probă) se alege astfel."
        )
    if take.status == "REFUSED":
        return refused("REFUSED", "Furnizorul a refuzat cererea: nu există niciun clip de ales.")
    if take.status == "LOST":
        return refused(
            "LOST",
            "Clipul nu a mai putut fi ridicat de la furnizor: nu există niciun fișier de ales.",
        )
    if take.status not in CLIP_CHOICE_STATUSES:
        return refused("NOT_DELIVERED", "Clipul nu a sosit încă de la furnizor.")
    code = str(take.failure_code or "")
    if code.startswith(_SENT_BACK_PREFIX):
        return refused("SENT_BACK", "Furnizorul a refuzat mișcarea: nu există niciun clip de ales.")
    if code == DUPLICATE_FILE_CODE:
        return refused(
            "DUPLICATE",
            "Furnizorul a predat același fișier ca un alt clip al scenei: alege-l pe acela.",
        )
    path = Path(str(take.path)) if take.path else None
    if path is None or not take.sha256 or not path.is_file():
        return refused("NO_FILE", "Clipul nu mai este pe disc: nu are ce să intre în film.")
    if _known_file_sha256(path) != take.sha256:
        return refused(
            "FILE_CHANGED", "Fișierul de pe disc nu mai este clipul cumpărat: nu poate fi ales."
        )
    if scene is None:
        return refused("NO_SCENE", f"Scena {index} nu mai există în storyboard.")
    if not still_sha256:
        return refused(
            "NO_STILL",
            f"Scena {index} nu are acum o imagine aprobată: un clip se alege doar împreună cu "
            "imaginea din care a fost filmat.",
        )
    if not shot_identity_matches(take, scene, still_sha256):
        older = code == REDO_STILL_REPLACED or any(
            take_hash(motion_fields(scene, sha, from_prompt=False), take.model_id)
            == take.prompt_hash
            for sha in other_stills
            if sha and sha != still_sha256
        )
        if older:
            return refused(
                "STILL_CHANGED",
                f"Clipul a fost filmat din altă imagine decât cea aleasă acum pentru scena "
                f"{index}: nu se mai potrivește cu ea.",
            )
        return refused(
            "PROMPT_CHANGED",
            f"Clipul a fost filmat pentru alt prompt de mișcare decât cel de acum al scenei "
            f"{index}.",
        )
    return {"eligible": True, "code": None, "offer": "button", "why_not_ro": ""}


def owner_take_decisions(
    session: Session, take_ids: Sequence[str]
) -> dict[str, list[dict[str, Any]]]:
    """Each take's decisions by the Owner (TAKE_DECIDED_EVENT), oldest first:
    {decision, note, at, sequence}."""
    ids = [str(take_id) for take_id in take_ids if take_id]
    found: dict[str, list[dict[str, Any]]] = {}
    if not ids:
        return found
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == TAKE_DECIDED_EVENT, DomainEvent.aggregate_id.in_(ids))
        .order_by(DomainEvent.sequence)
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("decided_by") not in (None, TAKE_DECIDER):
            continue
        found.setdefault(str(event.aggregate_id), []).append(
            {
                "decision": payload.get("decision"),
                "note": payload.get("note"),
                "final": bool(payload.get("final")),
                "at": str(event.timestamp),
                "sequence": int(event.sequence),
            }
        )
    return found


def owner_clip_choice(
    session: Session, storyboard_id: str, scene_number: int, field_options: list[dict[str, Any]]
) -> SceneTake | None:
    """The scene's clip by the Owner's newest choice, or None: among its APPROVED shot takes
    whose newest decision of his is APPROVED, the one he chose last that is still this shot
    (``field_options``, as `usable_take` reads it) with its file on disk unchanged."""
    rows = session.scalars(
        select(SceneTake).where(
            SceneTake.storyboard_id == storyboard_id,
            SceneTake.scene_number == scene_number,
            SceneTake.kind.in_(SHOT_TAKE_KINDS),
            SceneTake.status == "APPROVED",
        )
    ).all()
    if not rows:
        return None
    decisions = owner_take_decisions(session, [row.id for row in rows])
    chosen = {
        take_id: said[-1]["sequence"]
        for take_id, said in decisions.items()
        if said and said[-1]["decision"] == "APPROVED"
    }
    for row in sorted(
        (row for row in rows if row.id in chosen), key=lambda row: chosen[row.id], reverse=True
    ):
        if not any(take_hash(fields, row.model_id) == row.prompt_hash for fields in field_options):
            continue
        if not row.path or not row.sha256:
            continue
        path = Path(row.path)
        if not path.is_file() or _known_file_sha256(path) != row.sha256:
            continue
        return row
    return None


def scene_clip_context(
    engine: Engine, storyboard_id: str, scene_number: int
) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    """What `clip_choice` reads for one scene, as the shooting sheet reads it: the scene, its
    approved still's sha256 (None without one) and its other stills' sha256s."""
    with Session(engine) as session:
        row = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id,
                StoryboardScene.scene_index == scene_number,
            )
        ).first()
        if row is None:
            return None, None, []
        scene = scene_view(row)
        still = usable_take(
            session,
            storyboard_id,
            scene_number,
            "still",
            still_options(engine, scene),
            statuses=("APPROVED",),
        )
        others = [
            str(sha)
            for sha in session.scalars(
                select(SceneTake.sha256).where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.scene_number == scene_number,
                    SceneTake.kind == "still",
                )
            )
            if sha
        ]
    return scene, (str(still.sha256) if still is not None and still.sha256 else None), others


def clip_fit(
    scene_index: int,
    clip_seconds: float | None,
    span: float | None,
    *,
    least_span: float | None = None,
    estimated: bool = False,
) -> dict[str, Any]:
    """How one clip fills its scene's shot span, by the readiness's own rule (`clip_readiness`:
    `clip_stretch`, `clip_fits` within SLOWDOWN_ALLOWANCE, the "at_risk" reading of words not
    measured yet): ``how`` "shot" (it covers the span), "slowed" (slowed locally by
    ``slowed_by``, 0 USD), "at_risk", "too_short" (past the allowance: its motion is redone), or
    "unknown" (no length or no span). {how, clip_seconds, span, slowed_by, words_ro}."""
    reading: dict[str, Any] = {
        "how": "unknown",
        "clip_seconds": round(float(clip_seconds), 3) if clip_seconds else None,
        "span": round(float(span), 3) if span else None,
        "slowed_by": None,
        "words_ro": "",
    }
    if not clip_seconds or not span:
        return reading
    have = float(clip_seconds)
    stretch = clip_stretch(have, float(span))
    if stretch <= 1.0:
        return {
            **reading,
            "how": "shot",
            "words_ro": (
                f"Scena {scene_index}: clipul de {ro_decimal(have, 1)} s acoperă cadrul de "
                f"{ro_decimal(float(span))} s; se taie la lungimea lui."
            ),
        }
    if clip_fits(have, float(span)):
        return {
            **reading,
            "how": "slowed",
            "slowed_by": round(stretch, 4),
            "words_ro": slowed_words(scene_index, have, float(span)),
        }
    if least_span is not None and clip_fits(have, float(least_span)):
        return {
            **reading,
            "how": "at_risk",
            "words_ro": clip_risk_words(
                scene_index, have, float(least_span), float(span), estimated=estimated
            ),
        }
    return {
        **reading,
        "how": "too_short",
        "words_ro": clip_short_words(scene_index, have, float(span), estimated=estimated),
    }


def clip_rejection_words(
    take: SceneTake, clip_qc: dict[str, Any] | None, decisions: Sequence[dict[str, Any]]
) -> list[str]:
    """Why a clip was rejected, in the Owner's words, for his «Aleg totuși acest clip»: the clip
    QC report's blocks (FAILED, or what it could not check), his own «Respinge» with its note,
    and any other reason the take carries (a redo he asked for, say). Oldest decisions are
    history; only his newest rejection is quoted."""
    from app.media.shooting_sheet import _clock  # noqa: PLC0415 - the sheet imports us

    said: list[str] = []
    record = clip_qc or {}
    blocks = [str(text).strip().rstrip(".") for text in record.get("blocks_ro") or []]
    blocks = [text for text in blocks if text]
    if record.get("verdict") == "FAILED":
        said.append(
            "Controlul clipului l-a respins: " + ("; ".join(blocks) or "fără motiv scris") + "."
        )
    elif record.get("verdict") == "UNCHECKED":
        said.append(
            "Controlul clipului nu l-a putut verifica"
            + (f" ({'; '.join(blocks)})" if blocks else "")
            + "."
        )
    rejected = [item for item in decisions if item.get("decision") == "REJECTED"]
    if rejected:
        last = rejected[-1]
        note = " ".join(str(last.get("note") or "").split())
        when = _clock(last.get("at"), None)
        said.append(f"Respins de tine ({when})" + (f": «{note}»." if note else "."))
    code = str(take.failure_code or "")
    if (
        take.status == "REJECTED"
        and code not in (CLIP_QC_FAILURE_CODE, "OWNER.REJECTED")
        and take.failure_detail
    ):
        said.append(str(take.failure_detail).strip())
    return said


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


# ------------------------------------------------------------------- the bed under the voice

#: What a film without a usable library track says about its sound (Romanian: the Owner's).
NO_BED_ADVISORY = (
    "Biblioteca de muzică nu are nicio piesă folosibilă (config/music_library.json): filmul are "
    "doar narațiune, fără muzică dedesubt. Adaugă piese cu licență comercială confirmată ca "
    "filmele să aibă fundal sonor."
)


def _as_dict(value: Any) -> dict[str, Any]:
    """``value`` when it is a dict, else an empty one: a record read back may hold anything."""
    return value if isinstance(value, dict) else {}


def _core_message(engine: Engine, storyboard_id: str) -> str:
    """The film's core message, from its approved script; "" without one."""
    from app.factual.models import ScriptDraft  # noqa: PLC0415 - factual reads media models

    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        script = session.get(ScriptDraft, board.script_draft_id) if board is not None else None
        story = script.story_json if script is not None else None
    return str((story or {}).get("core_message") or "") if isinstance(story, dict) else ""


def _mood_text(
    engine: Engine, storyboard_id: str, title: str, scenes: Sequence[dict[str, Any]]
) -> str:
    """What the bed is chosen from: the film's title and core message, and each scene's
    words, purpose and audio intent."""
    parts: list[Any] = [title, _core_message(engine, storyboard_id)]
    for scene in scenes:
        parts += [
            scene.get("voiceover_segment"),
            scene.get("story_purpose"),
            (scene.get("prompt_json") or {}).get("audio_intent"),
        ]
    return " ".join(str(part) for part in parts if part)


def _scene_spans(scenes: Sequence[dict[str, Any]]) -> dict[int, tuple[float, float]]:
    """Each scene's (start, seconds) in the film, from the scenes' durations in order."""
    spans: dict[int, tuple[float, float]] = {}
    offset = 0.0
    for scene in scenes:
        seconds = float(scene.get("duration_seconds") or 0.0)
        spans[int(scene["scene_index"])] = (offset, seconds)
        offset += seconds
    return spans


def _tracks_of_plan(
    library: music_library.Library,
    plan: Mapping[str, Any],
    *,
    duration: float,
    made_with: Mapping[str, Any] | None = None,
) -> tuple[music_library.Track | None, list[dict[str, Any]], dict[str, music_library.Track], int]:
    """The bed and the placed ambiences a plan names, as the library vouches for them now.

    Returns (bed, ambience placements for `mix_bed`, the tracks by id, how many the plan named
    that were left out). A track the library no longer has is left out; so is one whose bytes
    are no longer the ones the film was made with (``made_with``: production['audio'] of that
    film, whose records carry each track's sha256), never replaced by another."""
    bed_id = str(plan.get("bed") or "")
    bed = library.entry(bed_id) if bed_id else None
    if bed is not None and bed.kind != "music":
        bed = None
    recorded_bed = (made_with or {}).get("bed") if made_with else None
    if (
        bed is not None
        and isinstance(recorded_bed, Mapping)
        and recorded_bed.get("track_id") == bed.id
        and recorded_bed.get("sha256") not in (None, bed.sha256)
    ):
        bed = None
    dropped = 1 if bed_id and bed is None else 0
    recorded_ambience = {
        str(item.get("track_id")): str(item.get("sha256") or "")
        for item in ((made_with or {}).get("ambience") or [])
        if isinstance(item, Mapping)
    }
    placed: list[dict[str, Any]] = []
    tracks: dict[str, music_library.Track] = {}
    for item in plan.get("scenes") or []:
        if not isinstance(item, Mapping) or not item.get("ambience"):
            continue
        name = str(item["ambience"])
        start = max(0.0, float(item.get("start") or 0.0))
        seconds = min(float(item.get("seconds") or 0.0), max(0.0, duration - start))
        track = library.entry(name)
        if track is None or track.kind != "ambience":
            dropped += 1
            continue
        if name in recorded_ambience and recorded_ambience[name] not in ("", track.sha256):
            dropped += 1
            continue
        if seconds <= 0.2:
            continue
        tracks[track.id] = track
        placed.append(
            {
                "path": track.path,
                "start": start,
                "seconds": seconds,
                "scene_index": item.get("scene_index"),
                "track_id": track.id,
            }
        )
    return bed, placed, tracks, dropped


def _mix_with_plan(
    ffmpeg_exe: str,
    voice: Path,
    target: Path,
    folder: Path,
    *,
    duration: float,
    bed: music_library.Track | None,
    placed: list[dict[str, Any]],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """`mix_bed` with a sound plan: its fades and its level per scene (`sound_design`)."""
    from app.media import sound_design  # noqa: PLC0415 - it imports this module's neighbours

    return mix_bed(
        ffmpeg_exe,
        voice,
        target,
        bed=bed.path if bed is not None else None,
        duration=duration,
        work_dir=folder,
        ambience=placed,
        fade_in=float(plan.get("fade_in_seconds") or BED_FADE_IN_SECONDS),
        fade_out=float(plan.get("fade_out_seconds") or BED_FADE_OUT_SECONDS),
        levels=sound_design.levels_for_mix(plan),
    )


def film_mix(
    engine: Engine,
    storyboard_id: str,
    ffmpeg_exe: str,
    voice: Path,
    scenes: Sequence[dict[str, Any]],
    work_dir: Path,
    *,
    duration: float,
    title: str,
    registry: Any = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """The film's sound before the master: the joined narration, a bed from the Owner's
    library ducked under it, and an ambience under the scenes whose audio_intent names one.

    Which bed, how far under the words per scene and where it may rise is the sound
    department's plan (`sound_design.sound_plan`: the Voice Artist, asked through ``registry``;
    without one, or refused twice, the deterministic plan, and the record says which). The
    plan is recorded as ``plan`` and as a `sound_design.PLAN_EVENT` on the storyboard.

    Returns the stem to master as ``path`` and the record production['audio'] keeps: ``bed``
    (the track, its licence and attribution, and the measured level under the voice — over the
    film, where the voice speaks, and in its gaps), ``ambience``, ``attributions`` (what the
    publication must credit), ``advisory`` (why there is no bed), ``plan`` and ``library`` (the
    tracks it refused, with their reasons). A mix that fails leaves the film voice only, with a
    warning for the Owner: the bed is never worth the film."""
    from app.media import sound_design  # noqa: PLC0415 - it imports this module's neighbours

    library = music_library.load_library()
    record: dict[str, Any] = {
        "bed": None,
        "ambience": [],
        "attributions": [],
        "advisory": None,
        "plan": None,
        "library": {
            "path": library.path.name,
            "tracks": len(library.tracks),
            "refused": library.refused[:20],
        },
    }
    correlation = correlation_id or str(uuid4())
    outcome = sound_design.sound_plan(
        engine,
        registry,
        film={"title": title, "core_message": _core_message(engine, storyboard_id)},
        scenes=[sound_design.scene_brief(scene) for scene in scenes],
        library=library,
        correlation_id=correlation,
        mood_text=_mood_text(engine, storyboard_id, title, scenes),
        seed=storyboard_id,
    )
    plan = sound_design.plan_record(outcome, _scene_spans(scenes))
    record["plan"] = plan
    try:
        _storyboard_event(
            engine,
            sound_design.PLAN_EVENT,
            storyboard_id,
            sound_design.plan_event_payload(plan, storyboard_id),
            correlation,
        )
    except SQLAlchemyError:
        logger.warning("sound_plan_not_recorded", extra={"storyboard_id": storyboard_id})
    bed, placed, tracks, _dropped = _tracks_of_plan(library, plan, duration=duration)
    has_music = any(track.kind == "music" for track in library.tracks)
    if bed is None:
        if outcome.source == sound_design.SOURCE_VOICE_ARTIST and has_music:
            # Her choice, not a missing library: the words stand alone, and she says why.
            who = outcome.agent_name or "departamentului de sunet"
            why = outcome.plan.why or "cuvintele stau singure"
            record["advisory"] = f"Fără muzică sub narațiune, la alegerea {who}: {why}"
        else:
            record["advisory"] = NO_BED_ADVISORY
        if not has_music:
            # Where the music comes from is his choice: the music card (DECISION_SOURCES).
            from app.decisions.sources import film_without_music  # noqa: PLC0415

            film_without_music(engine, title)
    try:
        mixed = _mix_with_plan(
            ffmpeg_exe,
            voice,
            work_dir / "mixed_audio.wav",
            work_dir,
            duration=duration,
            bed=bed,
            placed=placed,
            plan=plan,
        )
    except AudioMixError as exc:
        record["advisory"] = NO_BED_ADVISORY if bed is None else None
        record["warning"] = (
            "Muzica și ambianța nu au putut fi mixate sub narațiune; filmul are doar vocea. "
            f"Motiv tehnic: {exc}"
        )
        return {"path": voice, **record}
    if bed is not None and mixed["bed"] is not None:
        record["bed"] = {**bed.record(), **mixed["bed"], "stem": Path(mixed["bed"]["stem"]).name}
    for item in mixed["ambience"]:
        track = tracks[str(item["track_id"])]
        record["ambience"].append({**track.record(), **item, "stem": Path(item["stem"]).name})
    used = [tracks[str(i["track_id"])] for i in mixed["ambience"]]
    if bed is not None and record["bed"]:
        used.insert(0, bed)
    record["attributions"] = list(
        dict.fromkeys(track.attribution for track in used if track.attribution)
    )
    return {"path": Path(mixed["path"]), **record}


def _drop_mix_stems(folder: Path, mixed: Path, record: dict[str, Any], *, keep: Path) -> None:
    """Remove the mix's working files (the mixed stem, the bed and ambience stems)."""
    names = [mixed.name] if mixed != keep else []
    names += [
        str(item.get("stem"))
        for item in [record.get("bed"), *record.get("ambience", [])]
        if isinstance(item, dict) and item.get("stem")
    ]
    for name in names:
        (folder / Path(name).name).unlink(missing_ok=True)


def remix_film_sound(
    ffmpeg_exe: str,
    voice: Path,
    folder: Path,
    audio: dict[str, Any],
    *,
    duration: float,
    plan: Mapping[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """The bed and ambience a film was made with, mixed again under a remade voice track (an
    audio repair), with the sound plan it was made with (``audio['plan']``: the same bed, the
    same levels, the same fades) — or with ``plan``, a plan asked anew after quality control
    refused the mix (`repair_audio`). A track the library no longer vouches for is left out,
    and the record says so; nothing is chosen anew here. A film mixed before plans existed is
    remixed from its recorded tracks, as before."""
    library = music_library.load_library()
    record = dict(audio)
    used_plan = plan if plan is not None else audio.get("plan")
    target = folder / f"mixed_audio_repair_{uuid4().hex[:8]}.wav"
    bed_record = audio.get("bed") if isinstance(audio.get("bed"), dict) else None
    if isinstance(used_plan, Mapping):
        bed, placed, _tracks, dropped = _tracks_of_plan(
            library, used_plan, duration=duration, made_with=audio
        )
        record["plan"] = dict(used_plan)
        mixed = _mix_with_plan(
            ffmpeg_exe,
            voice,
            target,
            folder,
            duration=duration,
            bed=bed,
            placed=placed,
            plan=used_plan,
        )
    else:
        bed = library.entry(str(bed_record.get("track_id"))) if bed_record else None
        if bed is not None and bed_record is not None and bed.sha256 != bed_record.get("sha256"):
            bed = None
        placed = []
        for item in audio.get("ambience") or []:
            track = library.entry(str(item.get("track_id"))) if isinstance(item, dict) else None
            if track is not None and track.sha256 == item.get("sha256"):
                placed.append(
                    {
                        "path": track.path,
                        "start": float(item.get("start") or 0.0),
                        "seconds": float(item.get("seconds") or 0.0),
                        "scene_index": item.get("scene_index"),
                        "track_id": track.id,
                    }
                )
        dropped = (1 if bed_record and bed is None else 0) + (
            len(audio.get("ambience") or []) - len(placed)
        )
        mixed = mix_bed(
            ffmpeg_exe,
            voice,
            target,
            bed=bed.path if bed is not None else None,
            duration=duration,
            work_dir=folder,
            ambience=placed,
        )
    record["bed"] = (
        {**bed.record(), **mixed["bed"], "stem": Path(mixed["bed"]["stem"]).name}
        if bed is not None and mixed["bed"] is not None
        else None
    )
    record["ambience"] = []
    used: list[music_library.Track] = [bed] if bed is not None and record["bed"] else []
    for item in mixed["ambience"]:
        track = library.entry(str(item["track_id"]))
        if track is not None:
            record["ambience"].append({**track.record(), **item, "stem": Path(item["stem"]).name})
            used.append(track)
    # The credits follow the tracks actually under this remix: a plan asked anew may have
    # changed the bed, and a track left out owes no credit.
    record["attributions"] = list(
        dict.fromkeys(track.attribution for track in used if track.attribution)
    )
    if dropped:
        record["warning"] = (
            "La refacerea sunetului, piese din bibliotecă nu mai sunt cele licențiate și au fost "
            "scoase din film."
        )
    if record["bed"] is None:
        has_music = any(track.kind == "music" for track in library.tracks)
        if isinstance(used_plan, Mapping) and not used_plan.get("bed") and has_music:
            why = str(used_plan.get("why") or "cuvintele stau singure")
            record["advisory"] = (
                f"Fără muzică sub narațiune, la alegerea departamentului de sunet: {why}"
            )
        elif bed_record is None:
            record["advisory"] = NO_BED_ADVISORY
    return Path(mixed["path"]), record


# ------------------------------------------------------------------- the licence ledger
#
# A film is LICENSED only when every component of it carries commercial-use evidence; any
# component without it makes the film NEEDS_REVIEW, which quality control lets through for a
# private upload and the publishing gate refuses public or unlisted (audit AR-15). The stamp
# PROPRIETARY_STUDIO, which every film used to receive whatever it was made of, is no longer
# written.

LICENSED = "LICENSED"
NEEDS_REVIEW = "NEEDS_REVIEW"
#: The fonts every caption and card is drawn with, and the licence shipped beside them.
FONTS_LICENCE = {
    "component": "fonts",
    "vendor": "Inter (Rasmus Andersson)",
    "terms": "SIL Open Font License 1.1 (backend/app/media/fonts/OFL.txt)",
}
#: What the studio itself draws or says with its own code: cards, placeholder frames, the
#: deterministic stand-in voice. Nobody else holds a right in them.
STUDIO_TERMS = "realizat local de studio, fără furnizor"
_COMPONENT_WORDS = {
    "still": "imaginea",
    "motion": "mișcarea",
    "narration": "narațiunea",
    "card": "cardul",
    "fonts": "fonturile",
    "music": "muzica",
    "ambience": "ambianța",
}


def _fonts_component() -> dict[str, Any]:
    ofl = Path(__file__).resolve().parent / "fonts" / "OFL.txt"
    return {**FONTS_LICENCE, "commercial_use": True if ofl.is_file() else None}


def _studio_component(component: str, scene_index: Any) -> dict[str, Any]:
    return {
        "component": component,
        "scene_index": scene_index,
        "vendor": "STUDIO",
        "terms": STUDIO_TERMS,
        "commercial_use": True,
    }


def _take_component(
    session: Session,
    component: str,
    scene_index: Any,
    take_id: Any,
    fallback_integration: Any,
    purposes: tuple[str, ...],
    stamps: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """A bought component's licence: the evidence already on its take, else the Owner's
    statement on the connection its model belongs to (or the one the render used)."""
    from app.media.factory import connection_of_model, vendor_licence  # noqa: PLC0415

    take = session.get(SceneTake, str(take_id)) if take_id else None
    if take is not None and take.commercial_use is True:
        return {
            "component": component,
            "scene_index": scene_index,
            "take_id": take.id,
            "vendor": take.licence_vendor,
            "terms": take.licence_terms,
            "commercial_use": True,
            "source": "take",
        }
    integration = (
        connection_of_model(session, take.model_id, purposes) if take is not None else None
    ) or fallback_integration
    licence = vendor_licence(session, integration)
    found = {
        "component": component,
        "scene_index": scene_index,
        "take_id": take.id if take is not None else None,
        **licence,
    }
    if take is not None:
        stamps[take.id] = licence
    return found


def licence_components(engine: Engine, production: dict[str, Any]) -> list[dict[str, Any]]:
    """Every component of a rendered film with its licence evidence, read from the render's
    own record: per scene its still, its shot, its narration (or the card that replaced the
    picture), then the fonts and the library's tracks. Takes whose licence was read from a
    connection carry it from now on (``licence_vendor``, ``licence_terms``,
    ``commercial_use``), stamped once with the evidence of the day they were first used."""
    components: list[dict[str, Any]] = []
    stamps: dict[str, dict[str, Any]] = {}
    image = _as_dict(production.get("image"))
    voice = _as_dict(production.get("voice"))
    placeholder_pictures = str(image.get("provider") or "").startswith(PLACEHOLDER_VISUAL_PROVIDER)
    with Session(engine) as session:
        for scene in production.get("scenes") or []:
            if not isinstance(scene, dict):
                continue
            index = scene.get("scene_index")
            if str(scene.get("scene_kind") or LIVE_KIND) in CARD_KINDS:
                components.append(_studio_component("card", index))
            elif placeholder_pictures:
                components.append(_studio_component("still", index))
            else:
                still = _as_dict(scene.get("still_take"))
                drawn = _as_dict(scene.get("image"))
                components.append(
                    _take_component(
                        session,
                        "still",
                        index,
                        still.get("take_id"),
                        drawn.get("integration_id") or image.get("integration_id"),
                        ("image",),
                        stamps,
                    )
                )
            motion = scene.get("motion") if isinstance(scene.get("motion"), dict) else None
            if (
                motion
                and not motion.get("refused")
                and (motion.get("bytes") or motion.get("reused_take"))
            ):
                components.append(
                    _take_component(
                        session,
                        "motion",
                        index,
                        motion.get("take_id"),
                        motion.get("integration_id"),
                        ("video",),
                        stamps,
                    )
                )
            if str(scene.get("voice_provider") or "") == PLACEHOLDER_VOICE_PROVIDER:
                components.append(_studio_component("narration", index))
                continue
            takes = [t for t in scene.get("narration_takes") or [] if t]
            connections = list(scene.get("voice_integration_ids") or []) or [
                voice.get("integration_id")
            ]
            for take_id in takes or [None]:
                components.append(
                    _take_component(
                        session, "narration", index, take_id, connections[0], ("voice",), stamps
                    )
                )
            for extra in connections[1:]:
                from app.media.factory import vendor_licence  # noqa: PLC0415

                components.append(
                    {
                        "component": "narration",
                        "scene_index": index,
                        **vendor_licence(session, extra),
                    }
                )
    components.append(_fonts_component())
    audio = _as_dict(production.get("audio"))
    tracks = [audio.get("bed")] + list(audio.get("ambience") or [])
    for track in tracks:
        if not isinstance(track, dict):
            continue
        components.append(
            {
                "component": "music" if track.get("kind", "music") == "music" else "ambience",
                "track_id": track.get("track_id"),
                "vendor": "BIBLIOTECA_PROPRIETARULUI",
                "terms": track.get("licence"),
                "commercial_use": True if track.get("commercial_ok") is True else None,
                "attribution": track.get("attribution"),
                "source": "music_library",
            }
        )
    if stamps:
        _stamp_licences(engine, stamps)
    return components


def _stamp_licences(engine: Engine, stamps: dict[str, dict[str, Any]]) -> None:
    """Write each take's licence on it: once found with commercial-use evidence it stays; a
    take without evidence is written again each time, so the Owner's later yes is read."""
    try:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            for take_id, licence in stamps.items():
                take = session.get(SceneTake, take_id)
                if take is None or take.commercial_use is True:
                    continue
                take.licence_vendor = (str(licence.get("vendor") or "")[:60]) or None
                take.licence_terms = (str(licence.get("terms") or "")[:200]) or None
                take.commercial_use = True if licence.get("commercial_use") is True else None
    except SQLAlchemyError:
        # The film's own record carries the evidence; the stamp on the take is a convenience.
        logger.warning("take_licences_not_stamped", exc_info=True)


def film_licences(components: list[dict[str, Any]]) -> dict[str, Any]:
    """The film's licence status from its components: LICENSED only when there are
    components and every one carries commercial-use evidence; NEEDS_REVIEW otherwise, with
    what lacks it in Romanian."""
    missing: list[str] = []
    for component in components:
        if component.get("commercial_use") is True:
            continue
        word = _COMPONENT_WORDS.get(
            str(component.get("component")), str(component.get("component"))
        )
        where = (
            f" scenei {component['scene_index']}"
            if component.get("scene_index") is not None
            else ""
        )
        vendor = component.get("vendor") or "furnizor necunoscut"
        missing.append(f"{word}{where} ({vendor}): nicio confirmare de folosire comercială")
    status = LICENSED if components and not missing else NEEDS_REVIEW
    if not components:
        missing.append("filmul nu are nicio componentă înregistrată")
    return {
        "status": status,
        "components": components,
        "missing_ro": list(dict.fromkeys(missing)),
    }


def film_licence_ledger(engine: Engine, production: dict[str, Any]) -> dict[str, Any]:
    """`licence_components` read and judged by `film_licences`; never fails a film: a ledger
    that cannot be read is NEEDS_REVIEW with the reason."""
    try:
        ledger = film_licences(licence_components(engine, production))
    except (SQLAlchemyError, OSError, ValueError, TypeError) as exc:
        logger.warning("licence_ledger_failed", exc_info=True)
        return {
            "status": NEEDS_REVIEW,
            "components": [],
            "missing_ro": [f"licențele nu au putut fi citite ({type(exc).__name__})"],
        }
    if ledger["status"] == NEEDS_REVIEW:
        # A connection that does not state commercial use is his to answer: one card per
        # vendor connection in his window of decisions (DECISION_SOURCES). Never fails the film.
        from app.decisions.sources import film_needs_review  # noqa: PLC0415

        film_needs_review(engine, ledger["components"])
    return ledger


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
    registry: Any = None,
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
        storage_root = media_root(settings)
    work_dir = storage_root / storyboard_id
    work_dir.mkdir(parents=True, exist_ok=True)
    # Every film quality control has read gives back its intermediates before another is
    # made (release_reviewed_intermediates). A sweep that cannot finish never stops a render.
    try:
        release_reviewed_intermediates(engine, correlation_id)
    except Exception:  # noqa: BLE001
        logger.warning("intermediates_not_released", exc_info=True)

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
        script_draft_id = sb.script_draft_id
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
    #
    # Each scene's words, part by part, read once before anything is said: a voice that
    # stitches is told the words before and after its own (narration_context), so the
    # intonation runs on across a cut instead of ending the film at every scene (audit Q3).
    # One take per speaker where the scene's lines say who speaks them (S7), each in its own
    # voice and the scene's voice when that has none; otherwise the scene's words are one take
    # in the scene's voice, as they always were.
    scene_parts: list[tuple[list[dict[str, Any]], bool]] = []
    for scene in scenes_data:
        given = voice_segments_for_scene(scene) if voice_segments_for_scene else None
        listed: list[dict[str, Any]] = [p for p in (given or []) if str(p.get("text") or "")]
        scene_parts.append(
            (listed, True) if listed else ([{"text": scene["voiceover_segment"]}], False)
        )
    part_contexts = narration_context(
        [[str(part["text"] or "") for part in parts] for parts, _ in scene_parts]
    )
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

            scene_position = scenes_data.index(scene)
            real_voice = scene_voices[scene_position]
            parts, by_speaker = scene_parts[scene_position]
            voice_started = time.monotonic()
            takes: list[tuple[dict[str, Any], TTSProvider, Any]] = []
            #: Characters this render paid a voice for; a reused narration take costs 0.
            characters_bought = 0
            reused_takes: list[str] = []
            #: The narration takes this scene's words are (bought now or reused), for the
            #: licence ledger.
            narration_take_ids: list[str] = []
            trims: list[dict[str, Any]] = []
            for position, part in enumerate(parts):
                take_voice: TTSProvider = (
                    (part.get("adapter") or real_voice) if all_real else None
                ) or placeholder_voice
                context = part_contexts[scene_position][position] if all_real else None
                key = (
                    narration_key(str(part["text"]), take_voice, context)
                    if all_real and bought_voice(take_voice)
                    else None
                )
                kept = reused_narration(engine, storyboard_id, index, key) if key else None
                if kept is not None:
                    said, reused_id = kept
                    reused_takes.append(reused_id)
                    narration_take_ids.append(reused_id)
                else:
                    with _at_work(
                        engine if all_real else None,
                        "VoiceArtist",
                        "synthesize_voice",
                        f"vocea scenei {index}",
                    ):
                        stitched = _context_fields(context) if stitches(take_voice) else None
                        # The line's acting note goes with its words: the voice plays it
                        # (the Owner, 2026-10-15: «să avem intonație, surprindere, emoție»).
                        direction = " ".join(str(part.get("direction") or "").split())
                        extra_fields = {
                            **(stitched or {}),
                            **({"direction": direction} if direction else {}),
                        }
                        said = asyncio.run(
                            take_voice.synthesize(str(part["text"]), extra=extra_fields)
                            if extra_fields
                            else take_voice.synthesize(str(part["text"]))
                        )
                    if all_real:
                        characters_bought += len(" ".join(str(part["text"]).split()))
                    if key:
                        # Kept the moment it is bought, as the vendor sent it: a later part, a
                        # master or an encode that fails does not make the next attempt pay
                        # for it again.
                        kept_id = keep_narration(
                            engine,
                            storyboard_id=storyboard_id,
                            scene_number=index,
                            key=key,
                            voice=take_voice,
                            said=said,
                            folder=work_dir / NARRATION_FOLDER,
                            scene_text=str(scene.get("voiceover_segment") or ""),
                            part=position,
                            parts=len(parts),
                            correlation_id=correlation_id,
                        )
                        if kept_id:
                            narration_take_ids.append(kept_id)
                if all_real and ffmpeg_exe:
                    # The vendor's silence before and after the words is cut before the
                    # scene is measured, so no cut carries dead air (audit Q4).
                    said, trim = _trimmed_take(
                        ffmpeg_exe, said, work_dir, f"take_{index:02d}_{position + 1:02d}"
                    )
                    trims.append(trim)
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
                # The connection each voice of the scene came from, for the licence ledger.
                "voice_integration_ids": sorted(
                    {
                        str(getattr(adapter, "integration_id", None))
                        for _part, adapter, _said in takes
                        if getattr(adapter, "integration_id", None)
                    }
                ),
                "narration_takes": narration_take_ids,
                "characters": sum(len(str(t[0]["text"])) for t in takes),
                # What the books price: the characters voiced by THIS render. A narration
                # reused from an earlier attempt was bought, and booked, then.
                "characters_bought": characters_bought,
                "narration_reused": reused_takes,
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
            if trims:
                # The silence cut from the vendor's takes: before the scene's first word and
                # after its last, and take by take.
                scene_record["trimmed_silence"] = {
                    "lead_seconds": trims[0]["lead_seconds"],
                    "trail_seconds": trims[-1]["trail_seconds"],
                    "takes": trims,
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
            scene_spans(
                planned_lengths,
                spoken_lengths,
                kinds=[scene_kind_of(scene) for scene in scenes_data],
            ),
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
            # its shot once slowed down by at most SLOWDOWN_ALLOWANCE, is used as it is: the
            # Nepal film's second render bought every clip again with the same prompts.
            still_sha = _file_sha256(still)
            fields = motion_fields(scene, still_sha, from_prompt=motion_from_prompt)
            # What clip QC said of the shot (kept on its take), and, from takes, whether it
            # may be cut in: the sheet's own reading (`clip_readiness`), here on the span the
            # narration just measured. In PRODUCTION only the Owner's APPROVED or a passing
            # report; a clip too short to be slowed into its span is CLIP_SHORT.
            found_qc: dict[str, Any] | None = None
            not_accepted: str | None = None
            reading: dict[str, Any] | None = None
            if takes_only:
                with Session(engine) as session:
                    reading = clip_readiness(
                        session,
                        storyboard_id,
                        scene,
                        still_sha,
                        span=needed,
                        environment=environment,
                        from_prompt=motion_from_prompt,
                    )
                    found_take = (
                        session.get(SceneTake, reading["take_id"]) if reading["take_id"] else None
                    )
                    if found_take is not None:
                        found_qc = clip_qc_of(session, found_take.id)
                        session.expunge(found_take)
                if not reading["ok"]:
                    not_accepted, found_take = (str(reading["why_ro"] or "") or None), None
            else:
                found_take = _usable_motion_take(
                    engine, storyboard_id, scene, fields, min_clip_seconds(needed)
                )
                if found_take is not None:
                    with Session(engine) as session:
                        found_qc = clip_qc_of(session, found_take.id)
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
                        "clip_qc": found_qc,
                    },
                )
                motion_seconds += wanted
                continue
            if takes_only:
                # Assembling from takes buys nothing: no accepted shot means the still pushed,
                # which quality control counts as a fallback, and the scene says why.
                with Session(engine) as session:
                    refusal, refused_qc = _scene_clip_refusal(
                        session, storyboard_id, int(scene["scene_index"])
                    )
                refused_record: dict[str, Any] = {
                    "model": None,
                    "asked_seconds": round(wanted, 3),
                    "shot_seconds": round(needed, 3),
                    "tier": tier,
                    "scene_category": scene_kind_of(scene),
                    "story_purpose": scene.get("story_purpose"),
                    "refused": not_accepted
                    or refusal
                    or "nicio mișcare plătită pentru promptul de acum (imagine fixă)",
                    # The report of the take that was found and not accepted, else the
                    # scene's last refused clip's.
                    "clip_qc": (
                        found_qc if reading is not None and reading.get("take_id") else refused_qc
                    ),
                }
                if reading is not None:
                    # What the refusal's event and the redo proposal read: the code, the
                    # clip's and the span's seconds, the take.
                    refused_record["readiness"] = {
                        key: reading.get(key)
                        for key in (
                            "code",
                            "take_id",
                            "clip_seconds",
                            "span",
                            "needed_seconds",
                            "why_ro",
                        )
                    }
                _attach_motion(production, scene, refused_record)
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
    # Each clip is measured against the shot it fills. A clip that covers its shot is cut; one
    # short of it by at most SLOWDOWN_ALLOWANCE is slowed down locally to fill it (0 USD,
    # recorded on the scene); one shorter still is not cut in at all: never a frozen frame
    # (the Owner, 2026-10-09). Held last frames remain only in the shots of older films.
    slows = _clip_slowdowns(ffmpeg_exe, scenes_data, motion_clips, card_clips, lengths, production)
    interpolate = slowdown_filter(ffmpeg_exe) or "framerate"
    holds = [0.0] * len(scenes_data)
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
    if real_stills:
        # No LIVE scene of a PRODUCTION film is a still unless the Owner chose LOCAL_MOVE for
        # it on the sheet: refused here, before the sound is mastered and the film encoded.
        # A placeholder film has no footage at all; QC blocks it from publication anyway.
        why_not: dict[int, str] = {}
        for entry in production["scenes"]:
            record = entry.get("motion")
            text = str(record.get("refused") or "") if isinstance(record, dict) else ""
            if text:
                why_not[int(entry["scene_index"])] = (
                    text
                    if text.startswith("Scena ")
                    else f"Scena {entry['scene_index']}: mișcarea nu a fost livrată ({text})."
                )
        try:
            production["fallback_gate"] = _require_chosen_stills(
                engine,
                storyboard_id,
                production,
                environment=environment,
                settings=settings,
                why_not=why_not,
            )
        except ClipsNotAccepted as exc:
            _fail_job(str(exc), str(exc))
            # What each refused scene measured (its code, the clip's and the span's seconds),
            # recorded for the sheet and for the redo the studio raises (propose_clip_redos).
            exc.details = [_refused_reading(production, index) for index in exc.scenes]
            record_assembly_refused(
                engine,
                storyboard_id,
                correlation_id,
                exc,
                stage="render",
                environment=environment,
                job_id=render_job_id,
            )
            raise

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
    # The finish (the Owner's look file): caption colours, the hook headline, the grade,
    # the second framings and the cover. All local, all 0 credits.
    finish = film_finish()
    hook = film_hook(engine, script_draft_id, scenes_data)
    production["finish"] = {
        "file": finish["file"],
        "notes": finish["notes"],
        "editorial_qc_blocking": finish["editorial_qc_blocking"],
    }
    production["captions"], captions = _write_captions(
        scenes_data,
        work_dir,
        ffmpeg_exe,
        wants_burn=bool(getattr(settings, "captions_burn_in", True)),
        finish=finish,
        headline=hook,
    )

    # The sound is mastered once, before the picture: the joined narration is measured,
    # normalised with one linear gain from that measurement (loudnorm falls back to dynamic
    # mode when it cannot, and the Owner is told), brought back to 48 kHz, held under the
    # limiter, padded to the film's length and encoded to AAC — the only lossy encode of the
    # film's sound. The film's own encode copies this track in.
    #
    # Before the master, the bed: a licensed track from the Owner's library, ducked under the
    # voice, and an ambience where a scene's audio_intent names one (audit Q1). Nothing here
    # is bought; a film without a usable track is voice only and says so.
    # The sound department's plan (the Voice Artist through ``registry``; without one the
    # deterministic plan) decides the bed, its level per scene and where it may rise.
    mix = film_mix(
        engine,
        storyboard_id,
        ffmpeg_exe,
        audio_file,
        scenes_data,
        work_dir,
        duration=total_duration,
        title=storyboard_title,
        registry=registry,
        correlation_id=correlation_id,
    )
    mastered = work_dir / MASTERED_TRACK_NAME
    mixed_sound = Path(mix.pop("path"))
    try:
        master = encode_master_audio(ffmpeg_exe, mixed_sound, mastered, duration=total_duration)
    except AudioMasterError as exc:
        _fail_job(f"The narration could not be mastered: {exc}", str(exc))
        raise RenderEngineUnavailable(f"The narration could not be mastered: {exc}") from exc
    finally:
        # The stems are remade for nothing from the voice track and the library when a
        # repair needs them (remix_film_sound); the master is what the film keeps.
        _drop_mix_stems(work_dir, mixed_sound, mix, keep=audio_file)
    loudness = _loudness_record(master)
    production["audio"] = {"loudness": loudness, "voice_track": voice_track, **mix}
    if loudness.get("warning"):
        production.setdefault("owner_warnings", []).append(loudness["warning"])
    if mix.get("warning"):
        production.setdefault("owner_warnings", []).append(mix["warning"])

    # One shot per scene — a generated clip trimmed to its span, a composed card, or the
    # still given a slow push — on the 24 fps timeline, joined by hard cuts and by a dissolve
    # only where the script asks. A 10-bit vendor clip is dithered down to 8 bits.
    dither = has_filter(ffmpeg_exe, "zscale")
    # A long spoken scene is cut to a closer framing of its own picture at a caption card's
    # start (audit Q6): the same take, nothing bought.
    framings: list[dict[str, Any] | None] = (
        plan_second_framings(scenes_data, caption_cues(scenes_data), finish)
        if real_stills and frame_files
        else [None] * len(scenes_data)
    )
    production["timeline"] = _timeline_record(
        scenes_data,
        joins,
        lengths,
        holds,
        motion_clips,
        card_clips,
        dither=dither,
        framings=framings,
        slows=slows,
    )
    lut_name: str | None = None
    if real_stills and frame_files:
        shots: list[Path] = []
        shot_records: list[dict[str, Any]] = []
        for position, scene in enumerate(scenes_data):
            span = lengths[position]
            # A card scene's shot is its composed clip; a LIVE scene's is its generated clip
            # (slowed into its span where it is a little short) or its still given a push.
            moving = card_clips[position] or motion_clips[position]
            slow = slows[position] if card_clips[position] is None else 1.0
            shot_still = frame_files[position] or moving
            if shot_still is None:
                reason = f"Scena {scene['scene_index']} nu are nici imagine, nici card compus."
                _fail_job(reason, reason)
                raise RenderEngineUnavailable(reason)
            target = work_dir / f"shot_{scene['scene_index']:02d}.mp4"
            shot_picture: Path = shot_still

            def build_shot(
                fill: str,
                *,
                _still: Path = shot_picture,
                _clip: Path | None = moving,
                _span: float = span,
                _target: Path = target,
                _hold: float = holds[position],
                _slow: float = slow,
            ) -> tuple[subprocess.CompletedProcess[str] | None, str]:
                args = _shot_command(
                    ffmpeg_exe,
                    _still,
                    _clip,
                    _span,
                    _target,
                    fps=TIMELINE_FPS,
                    hold=_hold,
                    dither=dither,
                    slow=_slow,
                    interpolate=fill,
                )
                try:
                    return run_encoder(args, work_dir), ""
                except RenderEngineUnavailable as exc:
                    return None, str(exc)

            def unbuilt(
                result: subprocess.CompletedProcess[str] | None, _target: Path = target
            ) -> bool:
                return (
                    result is None
                    or result.returncode != 0
                    or not _target.is_file()
                    or _target.stat().st_size == 0
                )

            slowed_with = interpolate
            shot, engine_error = build_shot(interpolate)
            if unbuilt(shot) and slow > 1.0 and interpolate != "framerate":
                # 2026-10-10 (babcf272 scene 3): minterpolate died in this encoder build after
                # 1.5 s with an access violation (exit 3221225477, nothing on stderr) on the
                # scene's 5.0 s particle clip, and the film was refused for a filter the shot
                # did not need; framerate built the same shot in 0.6 s. A slowed clip whose
                # best interpolation fails is blended instead, and the shot says so.
                logger.warning(
                    "slowdown_filter_failed",
                    extra={
                        "scene_index": scene["scene_index"],
                        "filter": interpolate,
                        "exit": getattr(shot, "returncode", None),
                        "error": engine_error[:200],
                    },
                )
                slowed_with = "framerate"
                shot, engine_error = build_shot("framerate")
            if shot is None:
                _fail_job(f"Shot {scene['scene_index']} could not be built", engine_error)
                raise RenderEngineUnavailable(engine_error)
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
            record = _shot_record(scene, target, span, joins[position])
            composed = card_clips[position] is not None
            record["source"] = _shot_source(
                still=None if composed else frame_files[position],
                clip=None if composed else motion_clips[position],
                card=composed,
                hold=holds[position],
                dither=dither,
                fps=TIMELINE_FPS,
                slow=slow,
                # What built it, so a one-scene redo rebuilds it the same way.
                interpolate=slowed_with,
            )
            shot_records.append(record)
        # One look (audit Q8): every filmed shot pulled toward the hero's light and colour,
        # measured before and after; the cards keep the studio's palette.
        composed_flags = [clip is not None for clip in card_clips]
        grade = film_grade(ffmpeg_exe, scenes_data, shots, composed_flags, finish)
        lut_name = _install_lut(work_dir, grade)
        production["grade"] = grade
        grades = [_shot_grade(grade, int(scene["scene_index"])) for scene in scenes_data]
        for record, graded, framing in zip(shot_records, grades, framings, strict=True):
            record["grade"] = graded
            record["framing"] = framing
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
            framings=framings,
            grades=grades,
            grain=int(grade["grain"]),
            lut=lut_name,
        )
    else:
        concat_list = work_dir / "inputs.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            # A placeholder film has a frame for every scene, cards included.
            placeholders = [frame for frame in frame_files if frame is not None]
            for frame_path, scene in zip(placeholders, scenes_data, strict=True):
                f.write(concat_line(frame_path.name))
                f.write(f"duration {float(scene['duration_seconds']):.6f}\n")
            if placeholders:
                f.write(concat_line(placeholders[-1].name))

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
        res, encode = encode_to_floor(
            ffmpeg_exe,
            command_args,
            work_dir,
            output_mp4,
            carry=((CAPTIONS_ASS_NAME, CAPTION_FONTS_DIR) if captions else ())
            + ((lut_name,) if lut_name else ()),
        )
        production["encode"] = encode
        log_output = f"FFmpeg exit={res.returncode}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    except Exception as exc:  # noqa: BLE001
        log_output = f"FFmpeg execution failed: {exc}"
        _fail_job("FFmpeg execution failed", log_output)
        if isinstance(exc, RenderEngineUnavailable):
            raise
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

    # The cover (audit Q14): the hero still and the hook, composed locally beside the film.
    # Uploading it as the platform's thumbnail is the publishing step's, not this one's.
    if real_stills and frame_files:
        production["cover"] = film_cover(
            work_dir, scenes_data, frame_files, card_clips, hook, finish, ffmpeg_exe
        )

    # The licence of every component, from evidence (AR-15): the film is LICENSED only when
    # each one carries commercial-use evidence, NEEDS_REVIEW otherwise (private uploads only).
    production["licences"] = film_licence_ledger(engine, production)

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
            license_status=production["licences"]["status"],
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


def _refused_mix(engine: Engine, asset_id: str) -> dict[str, Any] | None:
    """The newest quality report of the film whose audio mix check failed: the check with its
    report id, or None when the mix passed (or was never judged)."""
    with Session(engine) as session:
        report = session.scalars(
            select(QualityControlReport)
            .where(QualityControlReport.media_asset_id == asset_id)
            .order_by(QualityControlReport.verified_at.desc())
        ).first()
        if report is None:
            return None
        checks = report.checks_json if isinstance(report.checks_json, dict) else {}
        check = checks.get("audio_mix_qc")
        if not isinstance(check, dict) or check.get("passed") is not False:
            return None
        return {**check, "report_id": report.id}


def _replan_sound(
    engine: Engine,
    registry: Any,
    storyboard_id: str,
    audio: dict[str, Any],
    refused: dict[str, Any],
    *,
    asked_by: str,
    correlation_id: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The sound plan asked anew after quality control refused the mix (the Owner, 2026-10-11:
    what is wrong goes back to the agent and is repaired): the Voice Artist is told the measured
    numbers, the reasons and her previous plan, and her new plan must change (`sound_design`);
    the deterministic plan is the last resort. Returns (the new plan record, the replan entry),
    or None when the film has no plan or no scenes to plan for."""
    from app.media import sound_design  # noqa: PLC0415 - it imports this module's neighbours

    previous = audio.get("plan")
    if not isinstance(previous, dict):
        return None
    try:
        title, scenes = _storyboard_scenes(engine, storyboard_id)
    except ValueError:
        return None
    library = music_library.load_library()
    refusal = sound_design.mix_refusal(audio, refused)
    refusal["asked_by"] = asked_by
    outcome = sound_design.sound_plan(
        engine,
        registry,
        film={"title": title, "core_message": _core_message(engine, storyboard_id)},
        scenes=[sound_design.scene_brief(scene) for scene in scenes],
        library=library,
        correlation_id=correlation_id,
        mood_text=_mood_text(engine, storyboard_id, title, scenes),
        seed=storyboard_id,
        previous=previous,
        refusal=refusal,
    )
    # The scenes' places in the film are the film's: read from the plan it was mixed with.
    spans = {
        int(item["scene_index"]): (
            float(item.get("start") or 0.0),
            float(item.get("seconds") or 0.0),
        )
        for item in previous.get("scenes") or []
        if isinstance(item, dict) and item.get("scene_index") is not None
    }
    current = sound_design.plan_record(outcome, spans)
    entry = sound_design.replan_record(
        previous, outcome, current, asked_by=asked_by, refusal=refusal
    )
    try:
        _storyboard_event(
            engine,
            sound_design.REPLAN_EVENT,
            storyboard_id,
            {**entry, "storyboard_id": storyboard_id},
            correlation_id,
        )
    except SQLAlchemyError:
        logger.warning("sound_replan_not_recorded", extra={"storyboard_id": storyboard_id})
    return current, entry


def repair_audio(
    engine: Engine,
    asset_id: str,
    correlation_id: str,
    *,
    ffmpeg_path: str | None = None,
    registry: Any = None,
    note: str | None = None,
    requester: str = "video_editor",
) -> dict[str, Any]:
    """Remake a finished film's sound from its voice takes, for no credits at all.

    The narration is remixed from what the render kept beside the film, mastered the way a
    new render masters it (two-pass loudnorm at -2 dBTP, the limiter, one AAC encode) and put
    under the film's picture with ``-c:v copy``: the video packets are the same packets,
    which is checked, not assumed. The film it came from is left untouched; the repaired one
    is a new asset with a render record of its own, so quality control reads its manifest,
    and that manifest says what it is a remaster of. Nothing here calls a provider for media.

    The sound plan the film was mixed with goes back under the remade voice — unless the film's
    newest quality report refused the mix (the bed covered the voice, a track not in the
    library): then the Voice Artist is asked for a new plan through ``registry`` with the
    refusal quoted, by ``note`` or ``requester`` (the Director's reason), and the remix is made
    from it (`_replan_sound`). What was asked, why and what changed is kept in
    production['audio']['replans'] and as a `sound_design.REPLAN_EVENT`.
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
    # The bed and the ambience the film was made with go back under the remade voice; a
    # track the library no longer vouches for is left out, never replaced by another. A mix
    # quality control refused is planned again first, so the same plan is not mixed again.
    previous_audio = production.get("audio") if isinstance(production.get("audio"), dict) else {}
    refused = _refused_mix(engine, asset_id)
    replanned = (
        _replan_sound(
            engine,
            registry,
            storyboard_id,
            previous_audio or {},
            refused,
            asked_by=" ".join(str(note or "").split()) or requester,
            correlation_id=correlation_id,
        )
        if refused is not None
        else None
    )
    try:
        sound, remixed = remix_film_sound(
            ffmpeg_exe,
            voice,
            folder,
            previous_audio or {},
            duration=seconds,
            plan=replanned[0] if replanned is not None else None,
        )
    except AudioMixError as exc:
        raise AudioRepairError(f"Muzica nu a putut fi mixată din nou sub voce: {exc}") from exc
    try:
        master = encode_master_audio(ffmpeg_exe, sound, mastered, duration=seconds)
    except AudioMasterError as exc:
        raise AudioRepairError(f"Narațiunea nu a putut fi masterizată: {exc}") from exc
    finally:
        _drop_mix_stems(folder, sound, remixed, keep=voice)

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
    audio_record = {**dict(production.get("audio") or {}), **remixed}
    audio_record["loudness"] = loudness
    audio_record["repaired_from"] = voice.name
    if replanned is not None:
        earlier = audio_record.get("replans")
        audio_record["replans"] = [
            *(earlier if isinstance(earlier, list) else []),
            replanned[1],
        ]
    production["audio"] = audio_record
    warnings = [w for w in production.get("owner_warnings") or [] if w != loudness["warning"]]
    if loudness["warning"]:
        warnings.append(loudness["warning"])
    if remixed.get("warning") and remixed["warning"] not in warnings:
        warnings.append(remixed["warning"])
    production["owner_warnings"] = warnings
    if "licences" in production:
        # The components may have changed (a track left out): the evidence is read again.
        production["licences"] = film_licence_ledger(engine, production)
        license_status = production["licences"]["status"]
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
#: The account must hold this much more than a paid step's next purchase before it is asked
#: or bought: its first round to start, each shot after it (`balance_rule`, the Owner's rule
#: of 2026-10-03). The cap he approved stays the step's ceiling.
PAID_STEP_BALANCE_MARGIN = DEFAULT_MARGIN
#: Each motion step in the sentence «Runda următoare a ... costă ...».
STEP_ROUND_WORDS: dict[str, str] = {
    TEST_SHOT_STEP: "cadrului de probă",
    MOTION_STEP: "restului mișcării",
}
#: Failures tried once more on the same model, the same request and the same seed.
MOTION_RETRY_KINDS: tuple[str, ...] = ("TRANSIENT", "BAD_OUTPUT", "TECHNICAL")
#: The film's resolution unless the settings name another.
MOTION_STEP_RESOLUTION = "1080p"
#: Runway's seed range (0 .. 2^32 - 1).
SEED_RANGE = 4_294_967_295
#: Why a scene whose shot the vendor accepted is not bought, in the Owner's words.
IN_FLIGHT_REASON = (
    "Scena {scene}: furnizorul a primit deja cererea plătită pentru acest cadru și nu l-a "
    "predat încă; cadrul se ridică fără o nouă cumpărare."
)
#: Why the step stops when a shot it paid for did not arrive.
IN_FLIGHT_STOP = (
    "Scena {scene}: furnizorul a primit cererea plătită, dar clipul nu a sosit încă; se ridică "
    "mai târziu, fără o nouă cumpărare. În acest pas nu se mai cumpără mișcare."
)
#: The event a hero test shot accepted by clip QC is recorded under (on its take), when the
#: Owner's own paid-media rule lets the rest of the motion be bought without asking him
#: (2026-10-02, HERO_AUTO_ACCEPT). It never makes the take APPROVED: that stays his alone.
HERO_ACCEPTED_EVENT = "media.hero_accepted_by_clip_qc"
#: Who accepted it, as the event and the sheet name it.
HERO_ACCEPTED_BY = "clip_qc"
#: Who may approve or reject a take: the Owner, on the sheet. Nobody else.
TAKE_DECIDER = "owner"
TAKE_DECISIONS: tuple[str, ...] = ("APPROVED", "REJECTED")
#: His approval marked final (2026-10-11): ``final`` on his decision, or a note that says so
#: («finală», «definitiv»). Only a final approval stands against the Director's confirmed
#: repair (`_retire_takes` ``director_repair``); any other approval of his is still his
#: choice for the sheet, and still protected from every other unasked redo.
FINAL_APPROVAL_WORDS = re.compile(r"\b(?:final[aăe]?|definitiv[aăe]?)\b", re.IGNORECASE)


def final_approval_words(note: str | None) -> bool:
    """Whether the Owner's note on his look marks the approval final."""
    return bool(note) and FINAL_APPROVAL_WORDS.search(str(note)) is not None


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


def _usd_ro(amount: float) -> str:
    """«6,80 USD»: an amount in the Owner's question, with a decimal comma."""
    return f"{float(amount):.2f}".replace(".", ",") + " USD"


#: A shot take that means the scene is already bought (or being collected).
_BOUGHT_SHOT_STATUSES = ("SUBMITTED", "PAID", "APPROVED")


#: A scene's shot takes that became a clip (a round that made nothing keeps its seed).
_MADE_SHOT_STATUSES: tuple[str, ...] = ("PAID", "APPROVED", "REJECTED", "LOST")


def _shots_made(engine: Engine, storyboard_id: str, scenes: Sequence[int]) -> dict[int, int]:
    """How many clips each of these scenes already had made, whatever their identity."""
    found: dict[int, int] = {int(index): 0 for index in scenes}
    if not found:
        return found
    with Session(engine) as session:
        for number, count in session.execute(
            select(SceneTake.scene_number, func.count(SceneTake.id))
            .where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.kind.in_(SHOT_TAKE_KINDS),
                SceneTake.status.in_(_MADE_SHOT_STATUSES),
                SceneTake.scene_number.in_(list(found)),
            )
            .group_by(SceneTake.scene_number)
        ):
            found[int(number)] = int(count)
    return found


def _scene_seed(base: int, made: int) -> int:
    """The seed a scene's next round is bought on: the film's seed, moved past the clips the
    scene already had (two seeds a round: the shot and its clip-QC retry at seed + 1).

    2026-10-12: the film's one seed on every shot meant a scene bought again on the same words
    — the serial's, whose words are the composer's and may already be today's — would have
    made the same clip and failed the same check. A round that made nothing (a refusal, a
    cancelled shot) keeps its seed, as the technical retry does."""
    return (int(base) + 2 * max(0, int(made))) % SEED_RANGE


def _shot_take_ids(
    engine: Engine, storyboard_id: str, scenes: Sequence[int]
) -> dict[int, set[str]]:
    """Every shot take of these scenes, by scene, whatever its status."""
    found: dict[int, set[str]] = {int(index): set() for index in scenes}
    if not found:
        return found
    with Session(engine) as session:
        for take_id, number in session.execute(
            select(SceneTake.id, SceneTake.scene_number).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.kind.in_(SHOT_TAKE_KINDS),
                SceneTake.scene_number.in_(list(found)),
            )
        ):
            found.setdefault(int(number), set()).add(str(take_id))
    return found


def _bought_elsewhere(
    engine: Engine, storyboard_id: str, scene_index: int, identity: str, known: set[str]
) -> bool:
    """Whether a shot of this scene's identity was bought (or submitted) by someone else since
    ``known`` was read: a take not in it, in a status that means the scene is bought."""
    with Session(engine) as session:
        ids = session.scalars(
            select(SceneTake.id).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == scene_index,
                SceneTake.kind.in_(SHOT_TAKE_KINDS),
                SceneTake.prompt_hash == identity,
                SceneTake.status.in_(_BOUGHT_SHOT_STATUSES),
            )
        ).all()
    return any(str(take_id) not in known for take_id in ids)


class SpentStageError(RuntimeError):
    """A paid step failed after it had sent a request a vendor may have charged for.

    Raised by the step's caller (`shooting_sheet.run_sheet_step`, `redo_scene`) once what
    the step committed is in the books and the Owner has his letter. ``fault_class`` is HARD
    whatever it was raised from (the runbook reads it, `runbook.services.classify_fault`), so
    neither the stage's retry nor a second attempt of the day buys the same shots again:
    measured before 2026-10-02, a "database is locked" after a purchase was TRANSIENT and
    the stage ran four times, four purchases, none of them booked.
    """

    fault_class = "HARD"

    def __init__(
        self,
        reason_ro: str,
        *,
        storyboard_id: str,
        step: str,
        credits: float,
        booked: dict[str, Any] | None,
    ) -> None:
        super().__init__(reason_ro)
        self.reason_ro = reason_ro
        self.storyboard_id = storyboard_id
        self.step = step
        self.credits = credits
        self.booked = booked


@dataclass
class SpendMeter:
    """What a paid step has sent and committed so far, read by its caller whatever happens.

    ``attempts`` counts every request handed to a vendor (sent, or possibly sent);
    ``committed`` is the credits the step counts as possibly charged (`possibly_charged`).
    The step's caller passes one in and books from it when the step raises, so a step that
    paid and then failed is never booked as free.
    """

    committed: float = 0.0
    attempts: int = 0


def budget_cut(summary: dict[str, Any], budget_words: Callable[[], str | None]) -> None:
    """A round `gpu_batch.run_rounds` cut, or left unsent, for want of room says the budget's
    words when the step's budget hold (`shooting_sheet.StepHold`), not its cap, was the bound:
    the day then reads the step as waiting on his budget, never on the cap he approved."""
    if not summary.get("cap_stop"):
        return
    words = budget_words()
    if not words:
        return
    if summary.get("stopped") == summary["cap_stop"]:
        summary["stopped"] = words
    summary["cap_stop"] = words


#: The failure code of a request that left and got no answer: it may have been served and
#: billed, so it is counted and never sent again automatically.
UNANSWERED_FAILURE_CODE = "VENDOR.UNANSWERED"
#: What the Owner reads about such a request, per scene.
UNANSWERED_REASON = (
    "Scena {scene}: cererea a plecat la furnizor și răspunsul nu a venit, așa că poate fi "
    "taxată. Nu se trimite din nou automat; creditele ei sunt numărate. Decide Proprietarul "
    "pe foaia de filmare."
)
#: A RunPod item whose /run failed with no job id and that the GPU-off then proved never
#: queued and never made (`providers.runpod.batch.BatchRun.prove_unsent`, 2026-10-09), or that
#: the Owner released on his card (`media.runpod_unsent`): a refusal that cost nothing and says
#: nothing about the scene, so it holds nothing and counts as no paid attempt.
#: A shot the step stopped before sending (his stop, a shutdown, the step's own stop): its
#: take is REFUSED with this code and detail, nothing was made or paid, and `take_failure`
#: says nothing about the scene for it (2026-10-12, «The Zero Script Club», scene 6).
CANCELLED_FAILURE_CODE = "RUNPOD.CANCELLED"
CANCELLED_DETAIL = "Nu s-a cumpărat: pasul s-a oprit înainte de acest cadru."
NOT_QUEUED_FAILURE_CODE = "RUNPOD.NOT_QUEUED"
NOT_QUEUED_DETAIL = (
    "RunPod nu a pus cererea la coadă: la oprirea GPU-ului coada era goală și lucrătorul nu "
    "a început nimic din ea. Nu s-a făcut și nu s-a plătit nimic."
)
#: What the Owner reads about such a scene in the step's result.
NOT_QUEUED_REASON = (
    "Scena {scene}: RunPod nu a pus cererea la coadă (dovedit la oprirea GPU-ului); nu s-a "
    "cumpărat nimic. Scena se poate cumpăra din nou, cu aprobarea ta."
)
#: The account dropped more than the step counted: something it does not know was charged.
UNCOUNTED_DROP_STOP = (
    "Soldul furnizorului a scăzut cu {drop:.0f} credite de la începutul pasului, iar pasul a "
    "numărat {committed:.0f}: o scădere neexplicată. Nu se mai cumpără nimic până nu verifică "
    "Proprietarul contul."
)
#: Credits of rounding the balance read may differ by before a drop counts as uncounted.
UNCOUNTED_DROP_TOLERANCE = 0.5


def possibly_charged(exc: BaseException, *, submitted: bool) -> bool:
    """Whether a failed paid request may have been charged by the vendor.

    Yes once the vendor named a task (``submitted``). Before that, no only for what provably
    never reached it or that it refused before making anything: a request that never left
    this machine (``unsent``), a missing key, the vendor's own 4xx, and a refusal raised here
    before sending (ValueError, OSError). Everything else (no answer, a 5xx, a malformed
    200, a missing task id) may have been served and billed.
    """
    if submitted:
        return True
    if not isinstance(exc, MediaProviderError) or isinstance(exc, MediaProviderNotConfigured):
        return False
    if exc.unsent:
        return False
    status = exc.http_status
    if isinstance(status, int) and (400 <= status < 500 or status in SAFE_TO_RESEND_STATUSES):
        # The vendor's own "not like that" or "not now, send it again" (Runway's 502/503/504
        # are "May retry"): nothing was made.
        return False
    return True


def outcome_unknown(exc: BaseException, *, submitted: bool) -> bool:
    """A failed request whose outcome nobody knows: no task id was heard, the vendor named
    no failure code (one that did has answered), and it may still have been charged. Such a
    request is counted against the cap and never sent again automatically (MONEY-01)."""
    if submitted or getattr(exc, "code", None):
        return False
    return possibly_charged(exc, submitted=False)


def uncounted_drop(before: float | None, balance: float | None, committed: float) -> float | None:
    """The credits the account lost beyond what the step counted, or None when it did not."""
    if before is None or balance is None:
        return None
    drop = before - balance
    return drop if drop - committed > UNCOUNTED_DROP_TOLERANCE else None


def film_seed(storyboard_id: str) -> int:
    """The film's seed: the one every scene's first round and the plan's hash are built on; a
    scene's later rounds move past it (`_scene_seed`), a round's technical retry keeps it."""
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


# ------------------------------------------- a scene's still identity, with its reference
#
# 2026-10-02 (NO_REBUY_RECOVERY_REFERENCES, A5): the stills step recorded every still as its
# words alone, while the assembly looked for it by its words AND the reference picture of the
# character the scene shows. The first reference set would have made every serial film fail
# at assembly, every day. One identity is now read everywhere a still is looked for.


def scene_reference(
    engine: Engine, scene: dict[str, Any], *, cache: dict[str, bytes] | None = None
) -> dict[str, Any] | None:
    """The reference picture this scene's still is drawn from, with its bytes, or None
    (`factory.reference_payload`: the first character the writer named decides). Raises
    `app.media.services.ReferenceRequired` for a character whose look is locked and who has
    no reference the studio can read."""
    from app.media.factory import reference_payload  # noqa: PLC0415 - factory reaches us

    found: dict[str, Any] | None = reference_payload(
        engine, scene.get("character_ids"), cache=cache
    )
    return found


def scene_still_fields(
    engine: Engine, scene: dict[str, Any], *, cache: dict[str, bytes] | None = None
) -> dict[str, Any]:
    """The still identity of a scene as `assemble_from_takes` reads it: its words and the
    reference picture it is drawn from. Raises ReferenceRequired as `scene_reference`."""
    return still_fields(
        str(scene.get("visual_prompt") or ""), scene_reference(engine, scene, cache=cache)
    )


def still_options(engine: Engine, scene: dict[str, Any]) -> list[dict[str, Any]]:
    """The identities an approved still of this scene may carry, for a lookup that only
    reads (a card's background, a redo's Figure 1): none when its locked character has no
    reference, since no still of it can be approved."""
    from app.media.services import ReferenceRequired  # noqa: PLC0415 - services imports us

    try:
        return [scene_still_fields(engine, scene)]
    except ReferenceRequired:
        return []


# ------------------------------------------------------------------ what a scene remembers
#
# 2026-10-02 (NO_REBUY_RECOVERY_REFERENCES, A2 / MONEY-03): a scene whose stills the gate sent
# to the Owner, or whose shots failed, went back into the next run's purchase: under his MODE
# rule the film bought them again every day (image requests 3, 6, 9; video POSTs 2, 4, 6),
# unasked. Each scene now remembers, from its own takes and the steps' own events, what
# happened to it since the Owner last decided about it on the sheet:
#
# - a NEEDS_OWNER outcome of a step for the scene as it is now (the event names the identity)
#   holds it: it is never in a purchase again until he decides;
# - a failure that needs him on its own (a safety or contract refusal, an unknown error, a
#   request whose answer was lost, a task never collected) holds it too, even when the
#   process died before the step could say so;
# - and past `max_paid_attempts_per_scene` paid attempts (any prompt) it waits for him, so a
#   prompt rewritten every day is not a new allowance every day.
#
# A refusal that cost nothing because the vendor or the account was not there (no credits,
# a 503) says nothing about the scene and holds nothing. Only his own acts lift a hold: his
# choice of a model for the scene (`set_scene_model`), his look at one of its takes
# (`decide_sheet_take`), a redo he approved (takes retired REDO.*), or new words for it.
#
# 2026-10-11, the Owner: a film is redone until quality control passes, and only money stops
# it. A scene quality control refused is read by the Director, who has its prompt rewritten
# (`app.media.scene_rewrite`); her rewrite is a decision about the scene like his, so its hold
# lifts and its paid attempts count again from it. The money gates stay what they are.

#: The events a step writes when a scene is left for the Owner.
STILL_HOLD_EVENT = "media.still_needs_owner"
MOTION_HOLD_EVENT = "media.motion_needs_owner"
#: The Owner's acts that lift a hold (shooting_sheet.SCENE_MODEL_EVENT, decide_take's event).
SCENE_MODEL_SET_EVENT = "media.sheet_scene_model_set"
TAKE_DECIDED_EVENT = "media.scene_take_decided"
#: Who decided a scene's rewrite after quality control refused it (`scene_rewrite.DECIDED_BY`):
#: her rewrite lifts the hold too, and the scene's paid attempts count again from it.
DIRECTOR_REWRITE = "director"
#: How many paid attempts a scene may have since the Owner last decided about it.
DEFAULT_MAX_PAID_ATTEMPTS = 3
#: A failure of these kinds that cost nothing is the vendor's or the account's, not the scene's.
FREE_FAILURE_KINDS: tuple[str, ...] = ("TRANSIENT", "TECHNICAL", "ACCOUNT")
#: A failure of these kinds holds the scene for the Owner on its own.
HOLDING_FAILURE_KINDS: tuple[str, ...] = ("SAFETY", "CONTRACT", "UNKNOWN")
#: A vendor's refusal of OUR request's parameters (`production_policy.names_our_request`).
STUDIO_DEFECT_KIND = "STUDIO_DEFECT"
#: A hold a refusal of our own request left before 2026-10-04, released (once) by a startup or
#: watchdog pass: {released_event_id, released_sequence, hold_event, scene_number, take_id,
#: model_id, failure_code, failure_detail, reason_ro}. `scene_memory` skips a released hold.
STUDIO_DEFECT_RELEASED_EVENT = "media.studio_defect_hold_released"
#: A hold an unanswered RunPod /run left, released (once) because the GPU-off proved nothing
#: was queued, or on the Owner's own card (`media.runpod_unsent`). Same payload keys as
#: `STUDIO_DEFECT_RELEASED_EVENT` (``released_event_id`` first); `scene_memory` skips it too.
RUNPOD_UNSENT_RELEASED_EVENT = "media.runpod_unsent_hold_released"
DELIVERY_RETRY_EVENT = "media.delivery_retry_authorized"
#: The key under which a hold left by an unanswered RunPod /run names what it rests on (since
#: 2026-10-09): {"job_row_ids": [...], "take_ids": [...]}, the journal rows with no job id and
#: their REFUSED takes. `media.runpod_unsent` finds them by it even after a redo sent the same
#: keys again (the rows then name the redo's GPU session).
RUNPOD_HOLD_ITEMS = "runpod_items"


def runpod_hold_items(refused: dict[str, str] | None) -> dict[str, Any]:
    """The hold event's `RUNPOD_HOLD_ITEMS` entry for a scene whose items got no job id (journal
    row id -> its REFUSED take), or nothing when it has none."""
    if not refused:
        return {}
    return {
        RUNPOD_HOLD_ITEMS: {
            "job_row_ids": list(refused),
            "take_ids": list(refused.values()),
        }
    }


#: Every event that releases a hold, read by `_released_holds`.
HOLD_RELEASED_EVENTS: tuple[str, ...] = (
    STUDIO_DEFECT_RELEASED_EVENT,
    RUNPOD_UNSENT_RELEASED_EVENT,
    DELIVERY_RETRY_EVENT,
)
#: The failure kinds a REFUSED take may carry as its code when the vendor named none.
_KIND_CODES: tuple[str, ...] = (
    "SAFETY",
    "CONTRACT",
    "TRANSIENT",
    "TECHNICAL",
    "BAD_OUTPUT",
    "QUALITY",
    "ACCOUNT",
    "UNKNOWN",
)
#: Takes the Owner retired with a redo: his act, and not the scene's failure.
_OWNER_RETIRED_CODES: tuple[str, ...] = ("REDO.OWNER", "REDO.STILL_REPLACED")
#: The code a still carries when a video model refused it for safety (`_send_still_back`).
_SENT_BACK_PREFIX = "MOTION."


@lru_cache(maxsize=1)
def _studio_settings() -> Any:
    """The studio's settings when they can be built here, else None (the same shortcut
    `providers.retry` takes: the plans are read from places with no handle on them)."""
    from app.config import Settings  # noqa: PLC0415

    try:
        return Settings()  # type: ignore[call-arg]
    except Exception:  # noqa: BLE001 - a studio without usable settings gets the defaults
        return None


def max_paid_attempts_per_scene() -> int:
    """`settings.max_paid_attempts_per_scene` (STUDIO_MAX_PAID_ATTEMPTS_PER_SCENE), else 3.

    Read from one place for every plan, so the sheet the Owner approves on the page and the
    one the day buys from hash the same."""
    value = getattr(_studio_settings(), "max_paid_attempts_per_scene", None)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return DEFAULT_MAX_PAID_ATTEMPTS


def identity_key(fields: dict[str, Any]) -> str:
    """A scene's identity whatever the model: what a step's hold event names."""
    return take_hash(fields, None)


@dataclass(frozen=True)
class SceneMemory:
    """What one scene's takes of one kind say since the Owner last decided about it."""

    scene: int
    #: Its failures as it is now (this identity), for the model choice (plan_scene_models).
    failures: tuple[FailureRecord, ...]
    #: Why it waits for the Owner, in his words; None when it may be bought.
    hold_ro: str | None
    #: Paid attempts since his last decision, any identity.
    attempts: int
    #: Whether one of those shots was the film's test shot (the hero stays the hero).
    test_shot: bool


def _http_status_of(code: str) -> int | None:
    if code.startswith("HTTP_") and code[5:].isdigit():
        return int(code[5:])
    return None


def take_failure(row: SceneTake) -> FailureRecord | None:
    """One take as a failure of its scene, or None when it says nothing about the scene (a
    success, the Owner's own rejection or redo, a duplicate file, a refusal that cost nothing
    because the vendor or the account was not there)."""
    from app.media.production_policy import classify_failure  # noqa: PLC0415

    code = str(row.failure_code or "")
    model = row.model_id
    if row.status == "LOST":
        return FailureRecord(model_id=model, kind="UNKNOWN", code=code or "LOST")
    if row.status == "REJECTED":
        if code == CLIP_QC_FAILURE_CODE or code == "LOCAL.STILL_GATE":
            return FailureRecord(model_id=model, kind="QUALITY", code=code)
        if code.startswith(_SENT_BACK_PREFIX):
            return FailureRecord(model_id=model, kind="SAFETY", code=code)
        return None
    if row.status != "REFUSED":
        return None
    charged = row.credits_quoted is not None or row.credits_measured is not None
    if code == NOT_QUEUED_FAILURE_CODE and not charged:
        # RunPod never queued it (proven, or released by the Owner): nothing was made.
        return None
    if code == CANCELLED_FAILURE_CODE and not charged:
        # The step stopped before this shot (the Owner's stop, 2026-10-11 20:58, «The Zero
        # Script Club» scene 6): nothing was made or paid. The take says nothing about the
        # scene — read as UNKNOWN it held the scene for the Owner and stood before the refusal
        # quality control had given the shot before it, so the Director's ladder never saw it.
        return None
    if code == UNANSWERED_FAILURE_CODE:
        kind = "UNKNOWN"
    elif code == "RUNPOD.EXPIRED_UNDELIVERED":
        kind = "BAD_OUTPUT"
    elif code in _KIND_CODES:
        kind = code
    elif code == "VENDOR.NO_OUTPUT":
        kind = "BAD_OUTPUT"
    else:
        kind = classify_failure(
            code or None, http_status=_http_status_of(code), detail=row.failure_detail
        ).kind
    if kind == STUDIO_DEFECT_KIND:
        # Our own request was malformed (2026-10-04, the Nepal keyframe ratio): it says nothing
        # about the scene or the model, so it neither holds the scene nor drops its model.
        return None
    if kind in FREE_FAILURE_KINDS and not charged:
        return None
    # The policy kernel's retry counting knows TRANSIENT, not the assembler's TECHNICAL.
    return FailureRecord(
        model_id=model,
        kind="TRANSIENT" if kind == "TECHNICAL" else kind,
        code=code or None,
        detail=row.failure_detail,
    )


def _charged(row: SceneTake) -> bool:
    """Whether a take was (or may have been) paid for."""
    if row.status in ("PAID", "APPROVED", "SUBMITTED", "LOST"):
        return True
    if row.credits_quoted is not None or row.credits_measured is not None:
        return True
    return row.status == "REJECTED" and bool(row.sha256)


def _paid_attempts(rows: list[SceneTake], kind_group: str) -> int:
    """Paid requests among a scene's takes. A shot is one request; the candidates of one
    stills request share its vendor task id (two candidates a request when none was heard)."""
    charged = [row for row in rows if _charged(row)]
    if kind_group != "still":
        return len(charged)
    tasks = {row.remote_task_id for row in charged if row.remote_task_id}
    loose = sum(1 for row in charged if not row.remote_task_id)
    return len(tasks) + math.ceil(loose / max(1, STILL_CANDIDATES))


def _newest_quality_refusal(rows: list[SceneTake]) -> FailureRecord | None:
    """The quality refusal that is the scene's newest word about itself, or None.

    ``rows`` are the scene's takes as it is now, oldest first. A take that came out right at
    the same moment or later (a sibling candidate the gate approved) outranks the refusal; a
    newer failure of another kind is another matter (`HOLDING_FAILURE_KINDS`, the attempts)."""
    newest: tuple[datetime | None, FailureRecord] | None = None
    for row in rows:
        record = take_failure(row)
        if record is not None:
            newest = (_stamp(row.created_at), record)
    if newest is None or newest[1].kind != "QUALITY":
        return None
    refused_at = newest[0]
    for row in rows:
        if row.status not in ("PAID", "APPROVED", "SUBMITTED"):
            continue
        good_at = _stamp(row.created_at)
        if refused_at is None or good_at is None or good_at >= refused_at:
            return None
    return newest[1]


def _quality_hold(index: int, kind_group: str, refused: FailureRecord) -> str:
    """Why a scene quality control refused is not bought again as it is: the Director rewrites
    it first (her ladder: `runbook.stages._director_rung`), nothing of it is the Owner's.

    2026-10-12: a motion step stopped by the Owner between a clip's refusal and its retry left
    scene 6 of «The Zero Script Club» with the refusal, no hold event, one paid attempt — and
    the next walk would have bought the same words again. The hold stops the stair, the walk's
    ladder reads the refusal (`scene_rewrite.quality_refused`) and she rewrites; her rewrite
    decides about the scene (`DIRECTOR_REWRITE`) and lifts this hold."""
    code = refused.code or refused.kind
    if kind_group == "still":
        return (
            f"Scena {index}: imaginea ei a fost refuzată de controlul calității ({code}); "
            "Directoarea o rescrie înainte de o nouă cumpărare, nu e decizia Proprietarului."
        )
    return (
        f"Scena {index}: cadrul ei a fost refuzat de controlul calității ({code}); "
        "Directoarea îl rescrie înainte de o nouă cumpărare, nu e decizia Proprietarului."
    )


def _hold_reason(payload: dict[str, Any], index: int) -> str:
    said = " ".join(str(payload.get("reason") or "").split())
    base = said if said else f"Scena {index} a fost lăsată Proprietarului de pasul plătit."
    return (
        base.rstrip(".")
        + ". Nu se cumpără din nou până nu decide Proprietarul pe foaia de filmare."
    )


def _event_holds(payload: dict[str, Any]) -> bool:
    """Whether a step's NEEDS_OWNER event holds its scene. A step since 2026-10-02 says so
    itself (``holds``); an older event holds unless it was an account failure (the account,
    not the scene, was the matter)."""
    if "holds" in payload:
        return bool(payload["holds"])
    return str(payload.get("failure_kind") or "") not in ("ACCOUNT",)


def scene_memory(
    engine: Engine,
    storyboard_id: str,
    kind_group: str,
    identities: dict[int, dict[str, Any]],
) -> dict[int, SceneMemory]:
    """Per scene of ``identities`` (scene -> its identity fields as it is now): its failures,
    whether it is held for the Owner and why, and its paid attempts since he last decided.

    ``kind_group`` is ``still`` (the stills step's takes, held by ``media.still_needs_owner``)
    or ``shot`` (the test shot's and the motion's, held by ``media.motion_needs_owner``).
    Reads only: 0 credits, no network.
    """
    if kind_group not in ("still", "shot"):
        raise ValueError(f"unknown take group: {kind_group}")
    wanted = {int(index): fields for index, fields in identities.items()}
    if not wanted:
        return {}
    kinds = ("still",) if kind_group == "still" else SHOT_TAKE_KINDS
    hold_event = STILL_HOLD_EVENT if kind_group == "still" else MOTION_HOLD_EVENT
    limit = max_paid_attempts_per_scene()
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(SceneTake)
                .where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.kind.in_(kinds),
                    SceneTake.scene_number.in_(list(wanted)),
                )
                .order_by(SceneTake.created_at)
            )
        )
        scene_of = {row.id: int(row.scene_number) for row in rows}
        decided: dict[int, list[datetime]] = {}
        for row in rows:
            if row.failure_code in _OWNER_RETIRED_CODES:
                stamp = _stamp(row.updated_at)
                if stamp is not None:
                    decided.setdefault(int(row.scene_number), []).append(stamp)
        if scene_of:
            for event in session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == TAKE_DECIDED_EVENT,
                    DomainEvent.aggregate_id.in_(list(scene_of)),
                )
            ):
                stamp = _stamp(event.timestamp)
                if stamp is not None:
                    decided.setdefault(scene_of[event.aggregate_id], []).append(stamp)
        said: dict[int, list[tuple[datetime | None, dict[str, Any]]]] = {}
        released = _released_holds(session, storyboard_id)
        delivery_retries: set[str] = set()
        for event in session.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.event_type.in_(
                    (
                        hold_event,
                        SCENE_MODEL_SET_EVENT,
                        SCENE_PROMPTS_REWRITTEN_EVENT,
                        DELIVERY_RETRY_EVENT,
                    )
                ),
                DomainEvent.aggregate_id == storyboard_id,
            )
            .order_by(DomainEvent.sequence)
        ):
            if event.event_id in released:
                continue  # a hold our own malformed request left, released on the books
            payload = event.payload if isinstance(event.payload, dict) else {}
            if event.event_type == DELIVERY_RETRY_EVENT:
                if payload.get("decided_by") == DIRECTOR_REWRITE and payload.get("take_id"):
                    delivery_retries.add(str(payload["take_id"]))
                continue  # a delivery decision releases its hold, never the paid-attempt count
            stamp = _stamp(event.timestamp)
            if event.event_type == SCENE_MODEL_SET_EVENT:
                index = payload.get("scene_index")
                if kind_group == "shot" and isinstance(index, int) and stamp is not None:
                    decided.setdefault(index, []).append(stamp)
                continue
            if event.event_type == SCENE_PROMPTS_REWRITTEN_EVENT:
                # The Director's rewrite of a scene quality control refused (Owner, 2026-10-11:
                # redone until it passes, only money stops it) decides about the scene: its
                # motion always, its still when she rewrote the picture (`scene_rewrite`).
                index = payload.get("scene_index")
                if (
                    payload.get("decided_by") == DIRECTOR_REWRITE
                    and isinstance(index, int)
                    and stamp is not None
                    and (kind_group == "shot" or payload.get("layer") == "still")
                ):
                    decided.setdefault(index, []).append(stamp)
                continue
            index = payload.get("scene_number")
            if isinstance(index, int) and index in wanted:
                said.setdefault(index, []).append((stamp, payload))
        for row in rows:
            session.expunge(row)

    memory: dict[int, SceneMemory] = {}
    for index, fields in wanted.items():
        cleared = max(decided.get(index, []), default=None)

        def since(stamp: datetime | None, _cleared: datetime | None = cleared) -> bool:
            return _cleared is None or stamp is None or stamp > _cleared

        recent = [
            row for row in rows if int(row.scene_number) == index and since(_stamp(row.created_at))
        ]
        mine = [row for row in recent if take_hash(fields, row.model_id) == row.prompt_hash]
        failures = tuple(record for row in mine if (record := take_failure(row)) is not None)
        attempts = _paid_attempts(recent, kind_group)
        key = identity_key(fields)
        hold: str | None = None
        for stamp, payload in said.get(index, []):
            if not since(stamp) or not _event_holds(payload):
                continue
            named = payload.get("identity")
            if named is not None and named != key:
                continue
            if named is None:
                # An event from before the identity was written on it: it holds the scene
                # only when a take of the scene as it is now came before it.
                bought = [_stamp(row.created_at) for row in mine]
                if not any(
                    when is not None and stamp is not None and when <= stamp for when in bought
                ):
                    continue
            hold = _hold_reason(payload, index)
        if hold is None:
            severe = [record for record in failures if record.kind in HOLDING_FAILURE_KINDS]
            if severe:
                what = (
                    "imaginea ei a fost refuzată sau pierdută"
                    if kind_group == "still"
                    else "cadrul ei a fost refuzat sau pierdut"
                )
                hold = (
                    f"Scena {index}: {what} ({severe[-1].code or severe[-1].kind}); nu se "
                    "cumpără din nou până nu decide Proprietarul pe foaia de filmare."
                )
        if hold is None:
            for row in reversed(mine):
                if row.status in ("PAID", "APPROVED", "SUBMITTED"):
                    break
                if take_failure(row) is None:
                    continue
                if (
                    row.failure_code == "RUNPOD.EXPIRED_UNDELIVERED"
                    and row.id not in delivery_retries
                ):
                    hold = (
                        f"Scena {index}: furnizorul nu a livrat fișierul; Directoarea verifică "
                        "livrarea înainte de o nouă cumpărare."
                    )
                break
        if hold is None:
            # Quality control's refusal, with no hold event of the step (the step stopped
            # between the refusal and its retry): the Director's rewrite comes before any
            # new purchase, the same as when the step itself held the scene.
            refused = _newest_quality_refusal(mine)
            if refused is not None:
                hold = _quality_hold(index, kind_group, refused)
        if hold is None and attempts >= limit:
            from app.wording import count as count_ro  # noqa: PLC0415

            hold = (
                f"Scena {index}: {count_ro(attempts, 'cumpărare plătită', 'cumpărări plătite')} "
                f"de la ultima decizie a Proprietarului, fără un rezultat acceptat (limita este "
                f"{limit}); nu se mai cumpără nimic pentru ea până nu decide el pe foaia de "
                "filmare."
            )
        memory[index] = SceneMemory(
            scene=index,
            failures=failures,
            hold_ro=hold,
            attempts=attempts,
            test_shot=any(row.kind == "test_shot" for row in recent),
        )
    return memory


def _released_holds(session: Session, storyboard_id: str | None = None) -> set[str]:
    """The event ids of the holds a release pass let go (`release_studio_defect_holds`, and
    `media.runpod_unsent` for a RunPod /run proven or released as never queued)."""
    query = select(DomainEvent.payload).where(DomainEvent.event_type.in_(HOLD_RELEASED_EVENTS))
    if storyboard_id is not None:
        query = query.where(DomainEvent.aggregate_id == storyboard_id)
    found: set[str] = set()
    for payload in session.scalars(query):
        if isinstance(payload, dict) and payload.get("released_event_id"):
            found.add(str(payload["released_event_id"]))
        if isinstance(payload, dict) and payload.get("decided_by") == "director":
            found.update(str(value) for value in payload.get("released_event_ids") or [])
    return found


def release_studio_defect_holds(engine: Engine, *, correlation_id: str) -> list[dict[str, Any]]:
    """Release the scene holds that a vendor's refusal of OUR request left (0 credits).

    Until 2026-10-04 a 400 naming our own request's parameters (Runway's keyframe ratio, its
    5 MB data-URI limit) was classed CONTRACT: the scene was held for the Owner and its model
    dropped (the Nepal test shot, storyboard 81438d13, scene 1 on wan3, 2026-10-03 20:56 UTC).
    A hold event (`STILL_HOLD_EVENT`, `MOTION_HOLD_EVENT`) that holds, says CONTRACT, and whose
    cause, the scene's newest refused take of that group at or before the event, is such a
    refusal (`production_policy.names_our_request`), is released: one
    `STUDIO_DEFECT_RELEASED_EVENT` per hold, which `scene_memory` reads. Idempotent (a released
    hold is never released twice) and it buys nothing; the scene is planned again on its model
    by the next sheet. Returns what it released."""
    from app.media.production_policy import names_our_request  # noqa: PLC0415

    released: list[dict[str, Any]] = []
    with Session(engine) as session:
        already = _released_holds(session)
        holds = [
            event
            for event in session.scalars(
                select(DomainEvent)
                .where(DomainEvent.event_type.in_((STILL_HOLD_EVENT, MOTION_HOLD_EVENT)))
                .order_by(DomainEvent.sequence)
            )
            if event.event_id not in already
            and isinstance(event.payload, dict)
            and _event_holds(event.payload)
            and str(event.payload.get("failure_kind") or "") == "CONTRACT"
            and isinstance(event.payload.get("scene_number"), int)
        ]
        for event in holds:
            payload = event.payload
            kinds = ("still",) if event.event_type == STILL_HOLD_EVENT else SHOT_TAKE_KINDS
            cause = session.scalar(
                select(SceneTake)
                .where(
                    SceneTake.storyboard_id == event.aggregate_id,
                    SceneTake.scene_number == int(payload["scene_number"]),
                    SceneTake.kind.in_(kinds),
                    SceneTake.status == "REFUSED",
                    SceneTake.created_at <= event.timestamp,
                )
                .order_by(SceneTake.created_at.desc())
                .limit(1)
            )
            if cause is None or not names_our_request(cause.failure_detail):
                continue
            released.append(
                {
                    "storyboard_id": event.aggregate_id,
                    "released_event_id": event.event_id,
                    "released_sequence": event.sequence,
                    "hold_event": event.event_type,
                    "scene_number": int(payload["scene_number"]),
                    "take_id": cause.id,
                    "model_id": cause.model_id,
                    "failure_code": cause.failure_code,
                    "failure_detail": cause.failure_detail,
                    "reason_ro": (
                        f"Scena {int(payload['scene_number'])} nu mai așteaptă decizia "
                        "Proprietarului: furnizorul refuzase o cerere trimisă greșit de studio "
                        f"(nu o limită a modelului {cause.model_id}), iar cererea a fost "
                        "reparată. Scena se planifică din nou pe modelul ei; nu s-a cumpărat "
                        "nimic."
                    ),
                }
            )
    if not released:
        return []
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        # Read again under the write lock: a second pass that ran meanwhile wrote nothing twice.
        already = _released_holds(session)
        for item in released:
            if item["released_event_id"] in already:
                continue
            append_event(
                session,
                STUDIO_DEFECT_RELEASED_EVENT,
                "storyboard",
                str(item["storyboard_id"]),
                1,
                {key: value for key, value in item.items() if key != "storyboard_id"},
                correlation_id,
            )
    return released


def recode_not_queued(
    session: Session,
    take_ids: Sequence[str],
    *,
    detail: str,
    correlation_id: str,
    by: str,
) -> list[str]:
    """REFUSED takes of a RunPod /run that was never queued (proven by the GPU-off, or released
    on the Owner's card): «unanswered, maybe paid» (VENDOR.UNANSWERED, credits counted) becomes
    `NOT_QUEUED_FAILURE_CODE` with no credits, so the take neither holds its scene nor counts as
    a paid attempt (`take_failure`, `_charged`). In the caller's transaction; a take that is not
    such a refusal any more (a file, another code) is left alone. Returns the takes changed."""
    changed: list[str] = []
    for take_id in take_ids:
        row = session.get(SceneTake, take_id)
        if (
            row is None
            or row.status != "REFUSED"
            or row.failure_code != UNANSWERED_FAILURE_CODE
            or row.sha256
            or row.credits_measured is not None
        ):
            continue
        quoted = row.credits_quoted
        row.failure_code = NOT_QUEUED_FAILURE_CODE
        row.failure_detail = detail[:TAKE_DETAIL_MAX]
        row.credits_quoted = None
        row.updated_at = utc_now()
        append_event(
            session,
            "media.scene_take_not_queued",
            "scene_take",
            row.id,
            1,
            {
                "storyboard_id": row.storyboard_id,
                "scene_number": row.scene_number,
                "kind": row.kind,
                "previous_failure_code": UNANSWERED_FAILURE_CODE,
                "credits_quoted_before": quoted,
                "by": by,
            },
            correlation_id,
        )
        changed.append(row.id)
    return changed


#: The code family of a failed local check on a still (the stills gate, a degenerate picture,
#: the rehearsal's faces or sharpness): such a still never starts a paid shot on its own.
LOCAL_FAILURE_PREFIX = "LOCAL."
#: What a take's recording writes (`record_take`, the rehearsal's adoption `_upsert_take`); its
#: payload names the failure code the take carries from then on.
TAKE_RECORDED_EVENT = "media.scene_take_recorded"


def owner_chose_flagged_still(session: Session, take: SceneTake) -> bool:
    """Whether the Owner himself chose this still after its local check failed (LOCAL.*).

    Proven only by his own look at THIS take (`decide_take`'s TAKE_DECIDED_EVENT, the take's
    id as its aggregate): his newest decision on it is APPROVED, no recording of the take since
    then (TAKE_RECORDED_EVENT, the rehearsal's adoption among them) names a LOCAL.* failure, and
    the row was not written after it. ``approved_by`` proves nothing here: the rehearsal's
    adoption may leave the Owner's name on a still it keeps 'doar pentru repetiție'.

    Film babcf272, 2026-10-09: scene 1's still, REJECTED by the old sharpness gate
    (LOCAL.STILL_GATE), was chosen by the Owner on the sheet, and the motion step still refused
    to animate it. Reads only: 0 credits, no network."""
    last = session.scalar(
        select(DomainEvent)
        .where(
            DomainEvent.event_type == TAKE_DECIDED_EVENT,
            DomainEvent.aggregate_id == take.id,
        )
        .order_by(DomainEvent.sequence.desc())
        .limit(1)
    )
    if last is None:
        return False
    said = last.payload if isinstance(last.payload, dict) else {}
    if said.get("decision") != "APPROVED" or said.get("decided_by") != TAKE_DECIDER:
        return False
    decided = _stamp(last.timestamp)
    written = _stamp(take.updated_at)
    if decided is None or written is None or written > decided:
        return False  # the take was written again after his look
    for payload in session.scalars(
        select(DomainEvent.payload).where(
            DomainEvent.event_type == TAKE_RECORDED_EVENT,
            DomainEvent.aggregate_id == take.id,
            DomainEvent.sequence > last.sequence,
        )
    ):
        code = payload.get("failure_code") if isinstance(payload, dict) else None
        if str(code or "").startswith(LOCAL_FAILURE_PREFIX):
            return False  # a failure recorded after his look: he has not seen this one
    return True


def _bought_shots(
    engine: Engine, storyboard_id: str, scenes: list[dict[str, Any]], redo: int | None = None
) -> tuple[dict[int, SceneTake], dict[int, SceneTake], dict[int, dict[str, Any]], dict[int, str]]:
    """Per LIVE scene: its APPROVED still, its usable shot, its shot identity, or why it waits.

    ``redo`` names the scene whose shot the Owner is having redone: its existing shot is not
    counted as bought, so the scene is planned (and priced) again on its own.

    The still is looked for by the scene's still identity with its character's reference
    picture (`scene_still_fields`), as the assembly looks for it; a locked character with no
    reference makes the scene wait (its reason is the refusal's)."""
    from app.media.services import ReferenceRequired  # noqa: PLC0415 - services imports us

    stills: dict[int, SceneTake] = {}
    shots: dict[int, SceneTake] = {}
    fields_of: dict[int, dict[str, Any]] = {}
    holds: dict[int, str] = {}
    identities: dict[int, dict[str, Any]] = {}
    loaded: dict[str, bytes] = {}
    for scene in scenes:
        if is_composed(scene):
            continue
        index = int(scene["scene_index"])
        try:
            identities[index] = scene_still_fields(engine, scene, cache=loaded)
        except ReferenceRequired as exc:
            holds[index] = str(exc)
    with Session(engine) as session:
        for scene in scenes:
            index = int(scene["scene_index"])
            if is_composed(scene) or index not in identities:
                continue
            still = usable_take(
                session,
                storyboard_id,
                index,
                "still",
                [identities[index]],
                statuses=("APPROVED",),
            )
            if still is None:
                holds[index] = (
                    f"Scena {index} nu are o imagine aprobată pentru promptul de acum; "
                    "mișcarea pornește doar dintr-o imagine aprobată."
                )
                continue
            # A still adopted with a failed local check (LOCAL.*) is approved only so the
            # zero-credit rehearsal can show it; a paid shot never starts from it, unless the
            # Owner himself chose THAT take after the failure (`owner_chose_flagged_still`).
            if str(still.failure_code or "").startswith(
                LOCAL_FAILURE_PREFIX
            ) and not owner_chose_flagged_still(session, still):
                holds[index] = (
                    f"Scena {index}: imaginea ei a fost păstrată doar pentru repetiție "
                    f"({still.failure_code}); mișcarea plătită pornește doar dintr-o imagine "
                    "nouă, aprobată, sau din aceasta după ce o alege Proprietarul pe foaia de "
                    "filmare."
                )
                continue
            session.expunge(still)
            stills[index] = still
            fields = motion_fields(scene, still.sha256, from_prompt=False)
            fields_of[index] = fields
            if index == redo:
                continue
            # The Owner's newest choice is the scene's shot whatever its length (2026-10-10):
            # a clip he chose is never bought over. One too short for its words is read
            # CLIP_SHORT by the readiness; the studio proposes its redo as his question
            # (`propose_clip_redos`), since nothing unasked retires what he approved, and only
            # his yes to it or his own «Refă mișcarea» replaces it. Planning a purchase here
            # instead would buy a clip that his choice keeps out of the film, at every step.
            shot = owner_clip_choice(session, storyboard_id, index, [fields]) or _shot_take(
                session, storyboard_id, index, fields, motion_seconds(scene)
            )
            if shot is not None:
                session.expunge(shot)
                shots[index] = shot
    return stills, shots, fields_of, holds


def _in_flight_shots(
    engine: Engine, storyboard_id: str, fields_of: dict[int, dict[str, Any]], skip: set[int]
) -> dict[int, SceneTake]:
    """Per scene: a SUBMITTED shot of its current shot identity, the vendor's task still open.

    Such a scene is IN_FLIGHT: its shot was bought (the vendor accepted the task and may bill
    it) and is collected by its task id. No step buys it again."""
    found: dict[int, SceneTake] = {}
    with Session(engine) as session:
        rows = session.scalars(
            select(SceneTake)
            .where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.kind.in_(SHOT_TAKE_KINDS),
                SceneTake.status == "SUBMITTED",
            )
            .order_by(SceneTake.created_at.desc())
        ).all()
        for row in rows:
            index = int(row.scene_number)
            fields = fields_of.get(index)
            if index in skip or index in found or fields is None:
                continue
            if take_hash(fields, row.model_id) != row.prompt_hash:
                continue
            session.expunge(row)
            found[index] = row
    return found


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
    from app.media.prompt_agent import incomplete_plan_fields, motion_prompt_for  # noqa: PLC0415
    from app.media.shooting_sheet import price_table_for  # noqa: PLC0415 - it imports us

    # The table the sheet prices with — the local selection's models at 0 credits and the
    # RunPod profile's estimated rows laid over the published tariff — never the raw published
    # table: priced raw, the Director's motion redo of the cyclotron (aa170155, 2026-10-11
    # 20:17 UTC) found no row for LTX-2.5 at 1080p, held NEEDS_OWNER «Profilul RunPod selectat
    # nu poate filma această scenă: nu are preț publicat la 1080p», and was asked again every
    # hour; the sheet's own motion step priced the same model on the same day.
    prices = table if table is not None else price_table_for(engine, None)
    _title, scenes = _storyboard_scenes(engine, storyboard_id)
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        bible = dict(board.visual_bible_json or {}) if board is not None else {}
    stills, shots, fields_of, holds = _bought_shots(engine, storyboard_id, scenes, redo)
    in_flight = _in_flight_shots(
        engine, storyboard_id, fields_of, set(shots) | ({redo} if redo is not None else set())
    )
    # What each scene still to be filmed remembers since the Owner last decided about it: its
    # failures (for the model choice) and whether it waits for him. A held scene is never
    # PLANNED, so no step buys it again (2026-10-02, MONEY-03). The scene he is having redone
    # is his own act and is not held.
    remembered = scene_memory(
        engine,
        storyboard_id,
        "shot",
        {
            index: fields
            for index, fields in fields_of.items()
            if index not in shots and index not in in_flight and index != redo
        },
    )
    for index, memory in remembered.items():
        if memory.hold_ro:
            holds[index] = memory.hold_ro
    # Who accepted each bought test shot: the Owner (APPROVED) or its clip QC under his rule
    # (HERO_ACCEPTED_EVENT). Part of the plan, and so of its hash.
    with Session(engine) as session:
        accepted = hero_acceptances(
            session, [take.id for take in shots.values() if take.kind == "test_shot"]
        )
        # 2026-10-09 (babcf272, «Încetinește local»): each clip is priced and bought as long as
        # the narration it will carry (`clip_plan`), no longer at its plan plus 0.4 s. A shot
        # already bought keeps its take (a length is no part of its identity); whether it is
        # long enough for its span is the assembly's reading (`clip_readiness`).
        sizes = clip_plan(session, storyboard_id, scenes)

    def sized(scene: dict[str, Any]) -> float:
        entry = sizes.get(int(scene["scene_index"]))
        return float(entry["seconds"]) if entry is not None else motion_seconds(scene)

    needs = [
        need_from_scene({**scene, "duration_seconds": sized(scene)}, len(scenes))
        for scene in scenes
    ]
    policy = plan_scene_models(
        needs,
        capabilities,
        allowed=allowed,
        overrides=overrides,
        failures={
            index: list(memory.failures) for index, memory in remembered.items() if memory.failures
        },
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
        flying = in_flight.get(index)
        still = stills.get(index)
        if kind != LIVE_KIND:
            status = "COMPOSED"
        elif shot is not None:
            status = "BOUGHT"
        elif still is None:
            status = "NEEDS_STILL"
        elif flying is not None:
            status = "IN_FLIGHT"
            shot = flying
        else:
            status = str(entry.get("status") or "NEEDS_OWNER")
        model_id = str(shot.model_id) if shot is not None else entry.get("model_id")
        accepted_by: str | None = None
        if status == "BOUGHT" and shot is not None:
            if shot.status == "APPROVED":
                accepted_by = TAKE_DECIDER
            elif shot.id in accepted:
                accepted_by = HERO_ACCEPTED_BY
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
                contract={
                    "still_model_id": str(still.model_id)
                    if still is not None
                    else prices.stills_model
                },
                # The still's words were judged when the still was bought: with one APPROVED
                # (`still`), only a new still would need them right, and this step buys
                # motion from the picture that exists. 2026-10-14/15 (f06808c9): scene 4's
                # new still was approved, the Accountant agreed to its motion redo, and the
                # redo was refused LINT_BLOCKED thirteen walks running on the still prompt's
                # wardrobe clause — a block on a picture nobody was going to buy again.
                composition_issues=(
                    tuple(incomplete_plan_fields(package, layers=("still",)))
                    if still is None
                    else ()
                ),
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
                "seconds": sized(scene) if kind == LIVE_KIND else 0.0,
                # Where that length comes from (`clip_plan`): the plan, or the narration
                # measured or estimated, and how long the words last.
                "seconds_source": (sizes.get(index) or {}).get("source"),
                "spoken_seconds": (sizes.get(index) or {}).get("spoken_seconds"),
                "billed_seconds": int(entry.get("billed_seconds") or 0),
                "credits": int(entry.get("credits") or 0),
                "usd_micros": int(entry.get("usd_micros") or 0),
                "price_source": entry.get("price_source"),
                "decided_by": entry.get("decided_by"),
                "reason_ro": holds.get(index)
                or (IN_FLIGHT_REASON.format(scene=index) if status == "IN_FLIGHT" else "")
                or entry.get("reason_ro")
                or "",
                "cheaper": entry.get("cheaper"),
                "better": entry.get("better"),
                "still_take_id": still.id if still is not None else None,
                "still_sha256": still.sha256 if still is not None else None,
                "take_id": shot.id if shot is not None else None,
                "take_kind": shot.kind if shot is not None else None,
                "take_status": shot.status if shot is not None else None,
                "accepted_by": accepted_by,
                "motion_prompt": motion_text,
            }
        )
    findings = lint_film(lint_scenes, bible=bible)
    raw_hero = policy.get("hero_scene")
    held = sorted(index for index, memory in remembered.items() if memory.hold_ro)
    bought_hero = next((index for index, take in shots.items() if take.kind == "test_shot"), None)
    if bought_hero is not None:
        # A bought test shot stays the film's test shot: a scene released after it (film
        # babcf272, 2026-10-09: scene 1's still chosen by the Owner once scene 2's test shot
        # was accepted) joins the remaining motion, never a second test shot of its own.
        raw_hero = bought_hero
    else:
        # A test shot that failed and waits for the Owner stays the film's test shot: another
        # scene does not become the hero (and is not bought as one) in its place.
        raw_hero = next((index for index in held if remembered[index].test_shot), raw_hero)
    hero: int | None = int(raw_hero) if raw_hero is not None else None
    by_index = {item["scene_index"]: item for item in view}

    def step(to_buy: list[int], waiting: list[int]) -> dict[str, Any]:
        each = [by_index[index]["credits"] for index in to_buy]
        cost = sum(each)
        cap = cost + max(each, default=0)
        overhead = max(
            (prices.round_overhead("video", by_index[index]["model_id"]) for index in to_buy),
            default=0,
        )
        if overhead:
            # RunPod Serverless: the step is one batch round (one GPU start: cold start + idle
            # tail) and, at worst, a second round with every shot's clip-QC retry. The Owner's
            # yes and the kernel's cost cover both rounds and both starts.
            cost += overhead
            cap = 2 * sum(each) + 2 * overhead
        return {
            "to_buy": to_buy,
            "cost_credits": cost,
            "cap_credits": cap,
            "cost_usd": round(cost * prices.credit_usd, 6),
            "cap_usd": round(cap * prices.credit_usd, 6),
            # Scenes of this step held for the Owner since a paid attempt failed: none of
            # them is bought again until he decides on the sheet.
            "held": waiting,
            # One GPU start of the step's round (RunPod Serverless), in its cost; 0 else.
            "round_overhead_credits": overhead,
        }

    planned = [item["scene_index"] for item in view if item["status"] == "PLANNED"]
    steps = {
        TEST_SHOT_STEP: step(
            [hero] if hero is not None and hero in planned else [],
            [hero] if hero is not None and hero in held else [],
        ),
        MOTION_STEP: step(
            [index for index in planned if index != hero],
            [index for index in held if index != hero],
        ),
    }
    if redo is not None:
        steps[REDO_STEP] = step([redo] if redo in planned else [], [])
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
                "accepted_by": item["accepted_by"],
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
        "memory": remembered,
        "findings": findings,
        "prices": prices,
        "bible": bible,
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
        lock_for_write(session)  # read-then-write right after a refused purchase
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
        sync_take_quality(session, row)
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


def _send_still_back_for_clip(
    engine: Engine,
    storyboard_id: str,
    scene_index: int,
    still_take_id: str | None,
    reason: str,
    correlation_id: str,
) -> bool:
    """Clip QC found the fault in the picture the clip was made from (``back_to_still``: faces
    in its frames, panels, another subject): the still goes back to the stills gate, REJECTED
    with the gate's code, so the scene's next still is a new one and nobody animates this one
    again. Returns whether it was sent back. A still the Owner approved himself stays as it is:
    his look is his (the scene then waits for him).

    2026-10-12, the cyclotron's scene 1: the new still approved by the gate at 10:43 showed two
    people facing the camera; its clip failed clip QC at 12:56 («greșeala e în imaginea din care
    s-a făcut clipul … aceeași imagine nu se mai animă»), the clip was rejected — and the still
    stayed APPROVED, so the Director's next repair joined it again as the scene's new approved
    take and bought another clip from it (36 credits, the same words, seed + 2)."""
    from app.media.stills_stage import GATE_FAILURE_CODE  # noqa: PLC0415 - it imports us

    with Session(engine) as session, session.begin():
        lock_for_write(session)  # read-then-write right after a refused purchase
        row = session.get(SceneTake, still_take_id) if still_take_id else None
        if row is None:
            # The clip was made from the scene's current still (`usable_take`): its newest
            # approved or paid one.
            row = session.scalar(
                select(SceneTake)
                .where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.scene_number == scene_index,
                    SceneTake.kind == "still",
                    SceneTake.status.in_(("APPROVED", "PAID")),
                )
                .order_by(SceneTake.created_at.desc())
                .limit(1)
            )
        if row is None or row.kind != "still" or row.status not in ("APPROVED", "PAID"):
            logger.info(
                "still_not_sent_back",
                extra={
                    "take_id": still_take_id,
                    "why": "not an approved or paid still",
                    "status": getattr(row, "status", None),
                    "kind": getattr(row, "kind", None),
                },
            )
            return False
        if str(row.approved_by or "").lower() == "owner":
            logger.info(
                "still_not_sent_back", extra={"take_id": still_take_id, "why": "his approval"}
            )
            return False
        row.status = "REJECTED"
        row.failure_code = GATE_FAILURE_CODE
        row.failure_detail = (
            "Controlul clipului a găsit greșeala în imagine; imaginea se întoarce la poarta "
            f"imaginilor și nu se mai animă. {reason}"
        )[:TAKE_DETAIL_MAX]
        row.updated_at = utc_now()
        sync_take_quality(session, row, accepted=False, reason=reason[:400])
        append_event(
            session,
            "media.still_sent_back",
            "scene_take",
            row.id,
            1,
            {
                "storyboard_id": row.storyboard_id,
                "scene_number": row.scene_number,
                "failure_kind": "CLIP_QC",
                "failure_code": GATE_FAILURE_CODE,
                "reason": reason[:400],
            },
            correlation_id,
        )
    return True


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
    final: bool = False,
) -> dict[str, Any]:
    """The Owner's look at a bought take: APPROVED or REJECTED. Only he decides.

    ``final`` (or a note that says «finală» / «definitiv», `final_approval_words`) marks his
    APPROVED as final (2026-10-11, his card «Directoarea poate reface și ce am aprobat eu»):
    the Director's confirmed repair of a real defect may replace a take he approved, and tells
    him; a take he approved as final is never replaced but by his own press.

    The hero test shot is approved this way before the rest of the motion may be bought; a
    rejected take is not used in a film unless he chooses it again. Raises PermissionError for
    anyone else.

    His APPROVED on a shot (motion or test shot) is his «Aleg totuși acest clip» (2026-10-10):
    any delivered clip `clip_choice` allows, a REJECTED one included (by the clip QC, or by him
    earlier), becomes his scene's clip and wins over the clip QC's verdict for it. One it
    refuses raises `ClipChoiceRefused` (a ValueError: 409) with its words, nothing changed. The
    clip's old failure is cleared off the take and kept on his decision's event
    (``previous_status``, ``previous_failure_code``, ``previous_failure_detail``). Nothing is
    bought or asked; the FILM_CONTINUE it queues walks the film on under his rule.
    """
    from app.db import lock_for_write  # noqa: PLC0415
    from app.media.shooting_sheet import FilmClosed, film_is_closed  # noqa: PLC0415 - it imports us

    if decided_by != TAKE_DECIDER:
        raise PermissionError("Doar Proprietarul aprobă sau respinge o înregistrare plătită.")
    if decision not in TAKE_DECISIONS:
        raise ValueError(f"Decizie necunoscută: {decision}")
    if decision == "APPROVED":
        with Session(engine) as session:
            seen = session.get(SceneTake, take_id)
            shot = seen is not None and seen.kind in SHOT_TAKE_KINDS
            if seen is not None:
                session.expunge(seen)
        if seen is not None and shot:
            # The sheet's own eligibility, read before the write lock (it reads the scene's
            # still and hashes the clip): the button he pressed and this answer never disagree.
            scene, still_sha, others = scene_clip_context(
                engine, seen.storyboard_id, int(seen.scene_number)
            )
            verdict = clip_choice(seen, scene=scene, still_sha256=still_sha, other_stills=others)
            if not verdict["eligible"]:
                raise ClipChoiceRefused(str(verdict["code"]), str(verdict["why_not_ro"]))
    with Session(engine) as session, session.begin():
        # Behind the write lock the Owner's «Închide filmul» takes: a look decided here either
        # landed before the close or meets the closed film below.
        lock_for_write(session)
        row = session.get(SceneTake, take_id)
        if row is None:
            raise ValueError("Înregistrarea nu există.")
        if film_is_closed(session, row.storyboard_id):
            # A closed film asks him nothing more: approving a take would queue a FILM_CONTINUE
            # that buys nothing (`continue_film` skips the film), and the answer would promise
            # a continuation that never comes. Nothing is changed (409 FILM_CLOSED).
            raise FilmClosed(row.storyboard_id)
        if row.status not in ("PAID", "APPROVED", "REJECTED"):
            raise ValueError(f"O înregistrare {row.status} nu se aprobă și nu se respinge.")
        if decision == "APPROVED" and (not row.path or not Path(row.path).is_file()):
            raise ValueError("Înregistrarea nu are fișierul pe disc; nu poate fi aprobată.")
        before = {
            "previous_status": row.status,
            "previous_failure_code": row.failure_code,
            "previous_failure_detail": row.failure_detail,
        }
        stands_final = decision == "APPROVED" and (bool(final) or final_approval_words(note))
        row.status = decision
        if decision == "APPROVED" and row.kind in SHOT_TAKE_KINDS:
            # His choice wins over the clip QC (or his own earlier «Respinge»): the take no
            # longer carries a failure the sheet would show under «Aprobată». The failure stays
            # on this decision's event, and the clip QC's report on its own.
            row.failure_code = None
            row.failure_detail = None
        sync_take_quality(session, row, accepted=decision == "APPROVED", reason=note)
        row.approved_by = TAKE_DECIDER if decision == "APPROVED" else None
        if decision == "REJECTED":
            row.failure_code = "OWNER.REJECTED"
            row.failure_detail = (note or "Respinsă de Proprietar.")[:TAKE_DETAIL_MAX]
        row.updated_at = utc_now()
        append_event(
            session,
            TAKE_DECIDED_EVENT,
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
                "final": stands_final,
                **before,
            },
            correlation_id or str(uuid4()),
        )
        continue_task_id = None
        if decision == "APPROVED" and row.kind != "narration":
            # His look is the decision the film was waiting for (the hero test shot above all,
            # A6): the film is walked on now, not at the next daily run. PRODUCTION only.
            from app.services import queue_film_continue  # noqa: PLC0415

            continue_task_id = queue_film_continue(
                session,
                row.storyboard_id,
                key=f"film-continue-{row.storyboard_id}-take-{row.id}",
                payload={"take_id": row.id, "cause": f"take:{row.id}"},
            )
        return {
            "take_id": row.id,
            "status": row.status,
            "kind": row.kind,
            "final": stands_final,
            "continue_task_id": continue_task_id,
        }


def _storyboard_event(
    engine: Engine, event_type: str, storyboard_id: str, payload: dict, correlation_id: str
) -> None:
    with Session(engine) as session, session.begin():
        append_event(session, event_type, "storyboard", storyboard_id, 1, payload, correlation_id)


#: Where a filmed scene's prompt package must come from before anything is bought for it in
#: PRODUCTION: the model's shot plan. Template prompts are a TEST convenience only.
SHOT_PLAN_SOURCES: tuple[str, ...] = ("model",)
#: An episode of the office serial may also be composed from the series' one fixed look, the
#: look the Owner approved (S8, prompt_agent.SOURCE_SERIES_LOOK): still linted, still gated.
SERIAL_SHOT_PLAN_SOURCES: tuple[str, ...] = ("model", "series_look")


def shot_plan_sources(engine: Engine, storyboard_id: str) -> tuple[str, ...]:
    """The package sources a storyboard's filmed scenes may be bought from in PRODUCTION.

    A factual film needs the model's plan; the office serial's episodes accept the scenes
    composed from the Owner-approved series look too, so his one-click serial is not held
    with NEEDS_SHOT_PLAN when its writer's model does not answer for every beat."""
    from app.agents.editorial import is_serial_film  # noqa: PLC0415 - agents import media
    from app.factual.models import ScriptDraft  # noqa: PLC0415

    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        script = (
            session.get(ScriptDraft, board.script_draft_id)
            if board is not None and board.script_draft_id
            else None
        )
        serial = is_serial_film(board, script)
    return SERIAL_SHOT_PLAN_SOURCES if serial else SHOT_PLAN_SOURCES


# ------------------------------------------------- the hero test shot, accepted by clip QC
#
# 2026-10-02 (HERO_AUTO_ACCEPT, A1 / AR-01 / TS-02): the rest of the motion was bought only
# after the Owner's APPROVED on the hero take, whatever his paid-media rule said, so under his
# MODE rule the day bought the hero and then waited for him every day. The hero is now also
# accepted by its clip QC, when, and only when, (a) its latest clip-QC report PASSED (not
# UNCHECKED, not FAILED, not missing) and (b) the Policy Kernel, asked without asking him
# (`may_act(..., ask_owner=False)` for media.motion_purchase at the motion step's cap), would
# let the motion step through unasked: his MODE rule, or OVER_USD with the cap within his
# amount, under a mode that allows it. The stop, safe mode, T4, the mode and the fail-closed
# budget are read by that same call. Under EVERY_PAID_STEP (or a cap over his amount, or the
# SUPERVISED mode) the hero waits for his look as before. The acceptance is an event on the
# take (HERO_ACCEPTED_EVENT, approved_by clip_qc, the report's event id); the take itself
# stays PAID: APPROVED is his alone (`decide_take`).


def hero_acceptances(session: Session, take_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """The clip-QC acceptance recorded on each of these takes, by take id (the latest)."""
    ids = [str(take_id) for take_id in take_ids if take_id]
    if not ids:
        return {}
    found: dict[str, dict[str, Any]] = {}
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == HERO_ACCEPTED_EVENT, DomainEvent.aggregate_id.in_(ids))
        .order_by(DomainEvent.sequence)
    ):
        if isinstance(event.payload, dict):
            found[str(event.aggregate_id)] = {**event.payload, "event_id": event.event_id}
    return found


def _clip_report_event(session: Session, take_id: str) -> DomainEvent | None:
    """The latest clip-QC report's event on a take (its ``event_id`` names the report)."""
    return session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == CLIP_QC_EVENT, DomainEvent.aggregate_id == take_id)
        .order_by(DomainEvent.sequence.desc())
        .limit(1)
    ).first()


def _hero_rule_words(
    verdict: dict[str, Any], rule: str, threshold: float | None, cap: float
) -> str:
    """Why the Owner's look is still needed although the hero's clip passed: his rule, his
    amount, or the mode, in his words."""
    from app.services import mode_words  # noqa: PLC0415 - services imports media

    if rule == "OVER_USD" and threshold is not None and cap > threshold:
        return (
            f"plafonul restului mișcării, {_usd_ro(cap)}, trece de pragul tău de "
            f"{_usd_ro(threshold)}"
        )
    if rule == "OVER_USD" or rule == "MODE":
        return f"modul studioului ({mode_words(str(verdict.get('mode') or ''))}) cere aprobarea ta"
    return "regula ta cere aprobarea fiecărui pas plătit al unui film"


def hero_gate(
    session: Session,
    plan: dict[str, Any],
    *,
    storyboard_id: str,
    plan_hash: str,
    cap_credits: int | None = None,
    requester: str = "video_editor",
) -> dict[str, Any]:
    """Whether the rest of the motion may be bought after the hero test shot, and why. 0
    credits, nothing written: the motion step records the acceptance (`_refuse_before_buying`),
    the sheet shows this view.

    ``status``: NO_HERO (no test shot in this film), NOT_BOUGHT (the hero is still to be
    bought), APPROVED (the Owner's look), ACCEPTED (clip QC's acceptance is recorded and still
    holds), ACCEPTS (clip QC passed and his rule lets it accept: the motion step records it),
    WAITING (his look is needed: the clip did not pass, or his rule asks him), REFUSED (the
    Policy Kernel refuses the motion outright: ``policy_status`` says why: a stop, safe mode, no
    daily budget...). ``rule_accepts`` says whether his rule and mode would let clip QC accept
    a passing hero now (what the sheet tells him before the hero is even bought).
    """
    from app.models import OwnerPolicy  # noqa: PLC0415
    from app.services import may_act, paid_media_policy  # noqa: PLC0415

    hero = plan.get("hero_scene")
    view: dict[str, Any] = {
        "scene_index": hero,
        "take_id": None,
        "status": "NO_HERO",
        "accepted_by": None,
        "clip_verdict": None,
        "clip_qc_report_id": None,
        "policy_status": None,
        "rule_accepts": False,
        "reason_ro": "",
    }
    steps = plan.get("steps") or {}
    motion_step = steps.get(MOTION_STEP) or {}
    cap = int(cap_credits) if cap_credits is not None else int(motion_step.get("cap_credits") or 0)
    if cap_credits is None:
        # Stills not yet made do not enter the ready-to-buy step. Its zero cap must not
        # present their already priced motion as free in the Owner's preview.
        pending = [
            int(item.get("credits") or 0)
            for item in plan.get("scenes") or []
            if item.get("kind") == LIVE_KIND
            and item.get("scene_index") != hero
            and item.get("status") in {"PLANNED", "NEEDS_STILL"}
        ]
        cap = max(cap, sum(pending) + max(pending, default=0))
    credit_usd = float(plan.get("credit_usd") or 0.01)
    cap_usd = round(cap * credit_usd, 6)
    rule, threshold = paid_media_policy(session.get(OwnerPolicy, 1))
    verdict = may_act(
        session,
        MOTION_STEP_ACTIONS[MOTION_STEP],
        requester=requester,
        subject=storyboard_id,
        cost_usd=cap_usd,
        context={"plan_hash": plan_hash or "?", "cap_credits": cap},
        ask_owner=False,
    )
    rule_accepts = bool(verdict["allowed"])
    view.update(rule_accepts=rule_accepts, policy_status=str(verdict["status"]))
    if hero is None:
        return view
    hero_view = next(
        (item for item in plan.get("scenes") or [] if item["scene_index"] == hero), None
    )
    if hero_view is None or hero_view.get("status") != "BOUGHT" or not hero_view.get("take_id"):
        view["status"] = "NOT_BOUGHT"
        view["reason_ro"] = (
            f"Întâi cadrul de probă (scena {hero}): restul mișcării se cumpără după el; dacă "
            "trece controlul clipului, regula ta pentru pașii plătiți îl acceptă fără să te "
            "aștepte, altfel îl privești tu pe foaia de filmare."
            if rule_accepts
            else f"Întâi cadrul de probă (scena {hero}): restul mișcării se cumpără abia după "
            "ce Proprietarul l-a văzut și l-a aprobat."
        )
        return view
    take = session.get(SceneTake, str(hero_view["take_id"]))
    view["take_id"] = take.id if take is not None else hero_view["take_id"]
    if take is not None and take.status == "APPROVED":
        view.update(
            status="APPROVED",
            accepted_by=TAKE_DECIDER,
            reason_ro=f"Cadrul de probă (scena {hero}) este aprobat de Proprietar.",
        )
        return view
    report = _clip_report_event(session, take.id) if take is not None else None
    record = dict(report.payload) if report is not None and isinstance(report.payload, dict) else {}
    clip_verdict = record.get("verdict") if take is not None and take.status == "PAID" else None
    if take is not None and take.status != "PAID":
        clip_verdict = "FAILED"
    view.update(
        clip_verdict=clip_verdict,
        clip_qc_report_id=report.event_id if report is not None else None,
    )
    looks = (
        "și așteaptă privirea Proprietarului: restul mișcării nu se cumpără până nu este "
        "aprobat pe foaia de filmare"
    )
    if clip_verdict != "PASSED":
        if clip_verdict == "FAILED":
            blocks = "; ".join(str(text) for text in record.get("blocks_ro") or [])
            said = "a picat controlul clipului" + (f" ({blocks})" if blocks else "")
        elif clip_verdict == "UNCHECKED":
            unmeasured = ", ".join(str(text) for text in record.get("unmeasured") or [])
            said = "nu a putut fi verificat de controlul clipului" + (
                f" ({unmeasured})" if unmeasured else ""
            )
        else:
            said = "nu a fost verificat încă de controlul clipului"
        view.update(status="WAITING", reason_ro=f"Cadrul de probă (scena {hero}) {said} {looks}.")
        return view
    if verdict["status"] not in ("ALLOWED", "NEEDS_APPROVAL"):
        # A stop, safe mode, no daily budget, a mode that refuses: the motion step would be
        # refused anyway; the hero is not accepted under it.
        view.update(status="REFUSED", reason_ro=str(verdict["reason"]))
        return view
    if not rule_accepts:
        why = _hero_rule_words(verdict, rule, threshold, cap_usd)
        view.update(
            status="WAITING",
            reason_ro=(
                f"Cadrul de probă (scena {hero}) a trecut controlul clipului {looks} ({why})."
            ),
        )
        return view
    accepted = hero_acceptances(session, [take.id]) if take is not None else {}
    if accepted:
        view.update(
            status="ACCEPTED",
            accepted_by=HERO_ACCEPTED_BY,
            reason_ro=(
                f"Cadrul de probă (scena {hero}) a fost acceptat de controlul clipului, cum "
                "permite regula ta pentru pașii plătiți."
            ),
        )
        return view
    view.update(
        status="ACCEPTS",
        reason_ro=(
            f"Cadrul de probă (scena {hero}) a trecut controlul clipului; regula ta pentru "
            "pașii plătiți îl acceptă fără să te aștepte, iar restul mișcării se cumpără în "
            "același pas."
        ),
    )
    return view


def _accept_hero(
    engine: Engine,
    plan: dict[str, Any],
    *,
    storyboard_id: str,
    plan_hash: str,
    cap_credits: int | None,
    requester: str,
    correlation_id: str,
) -> dict[str, Any] | None:
    """The motion step's hero gate: raises `MotionStepRefused` when the rest of the motion may
    not be bought after the hero yet; records clip QC's acceptance (once per take) when the
    Owner's rule lets it accept. Returns the acceptance written now, else None."""
    from app.models import OwnerPolicy  # noqa: PLC0415
    from app.services import paid_media_policy  # noqa: PLC0415

    with Session(engine) as session, session.begin():
        gate = hero_gate(
            session,
            plan,
            storyboard_id=storyboard_id,
            plan_hash=plan_hash,
            cap_credits=cap_credits,
            requester=requester,
        )
        status = gate["status"]
        if status in ("NO_HERO", "APPROVED", "ACCEPTED"):
            return None
        if status == "NOT_BOUGHT":
            raise MotionStepRefused("HERO_FIRST", gate["reason_ro"], plan=plan)
        if status == "WAITING":
            raise MotionStepRefused("HERO_NOT_APPROVED", gate["reason_ro"], plan=plan)
        if status == "REFUSED":
            raise MotionStepRefused(str(gate["policy_status"]), gate["reason_ro"], plan=plan)
        # ACCEPTS: written under the write lock, once per take, in the same transaction that
        # read the report and his rule.
        lock_for_write(session)
        if hero_acceptances(session, [gate["take_id"]]):
            return None
        policy = session.get(OwnerPolicy, 1)
        rule, threshold = paid_media_policy(policy)
        payload = {
            "storyboard_id": storyboard_id,
            "scene_number": gate["scene_index"],
            "take_id": gate["take_id"],
            "approved_by": HERO_ACCEPTED_BY,
            "clip_qc_report_id": gate["clip_qc_report_id"],
            "clip_qc_verdict": gate["clip_verdict"],
            "paid_media_approval": rule,
            "over_usd": threshold,
            "autonomy_mode": str(getattr(policy, "autonomy_mode", None) or "MANUAL"),
            "plan_hash": plan_hash,
            "reason_ro": gate["reason_ro"],
            "accepted_at": utc_now(),
        }
        append_event(
            session,
            HERO_ACCEPTED_EVENT,
            "scene_take",
            str(gate["take_id"]),
            1,
            payload,
            correlation_id,
        )
    logger.info(
        "hero_accepted_by_clip_qc",
        extra={"storyboard_id": storyboard_id, "take_id": gate["take_id"]},
    )
    return payload


def _refuse_before_buying(
    engine: Engine,
    state: dict[str, Any],
    step: str,
    plan_hash: str,
    *,
    environment: str,
    plan_hash_of: Callable[[Engine, str], str] | None,
    storyboard_id: str,
    current: str | None = None,
    cap_credits: int | None = None,
    requester: str = "video_editor",
    correlation_id: str = "",
) -> dict[str, Any] | None:
    """The refusals that come before anything is asked or bought, in order. ``current`` is
    the hash his yes must match when the caller read it already (before collecting).

    For the motion step, last: the hero gate (`hero_gate`). Returns clip QC's acceptance of the
    hero when this call recorded it, else None."""
    plan = state["plan"]
    if current is None:
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
        sources = shot_plan_sources(engine, storyboard_id)
        unwritten = [
            int(scene["scene_index"])
            for scene in state["scenes"]
            if not is_composed(scene)
            and (scene.get("prompt_json") or {}).get("source") not in sources
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
    if step != MOTION_STEP or plan["hero_scene"] is None:
        return None
    return _accept_hero(
        engine,
        plan,
        storyboard_id=storyboard_id,
        plan_hash=plan_hash,
        cap_credits=cap_credits,
        requester=requester,
        correlation_id=correlation_id,
    )


def _clip_plan(
    scene: dict[str, Any], bible: dict[str, Any], *, must_fix: Sequence[dict[str, Any]] = ()
) -> Any:
    """What one shot must be, as clip QC judges it: the still's plan, the camera move asked
    for, the bible's face rule and rules, the look (a still_gate.StillPlan).

    2026-10-12, late evening (the review of 9ac0195, finding 5): ``must_fix`` is what the
    scene's MOVEMENT was rewritten to fix (`fix_check.open_findings`, motion layer), which the
    clip's look answers item by item; and the scene's written picture is the writer's line for
    a factual film and the composed beat for the serial (`stills_stage._scene_picture`), never
    the compiled still prompt that ``visual_prompt`` holds."""
    from app.media import stills_stage as stills  # noqa: PLC0415 - stills_stage imports us
    from app.media.markings import planned_markings  # noqa: PLC0415
    from app.media.prompt_lint import bible_face_rule  # noqa: PLC0415
    from app.media.still_gate import StillPlan  # noqa: PLC0415

    raw = scene.get("prompt_json")
    package: dict[str, Any] = raw if isinstance(raw, dict) else {}
    intent = package.get("motion_intent")
    asked = intent.get("camera_move") if isinstance(intent, dict) else None
    look = str(package.get("look_block") or "")
    words = " ".join(str(package.get("still_prompt") or scene.get("visual_prompt") or "").split())
    picture = stills._scene_picture(package, str(scene.get("visual_prompt") or ""), words)
    return StillPlan(
        scene=int(scene["scene_index"]),
        still_prompt=words,
        camera_move=str(package.get("camera_move") or asked or ""),
        faces_forbidden=bible_face_rule(bible) is not None,
        bible_rules=stills._bible_rules(bible),
        look_block=look,
        palette_words=stills._palette_words(look),
        scene_picture=picture,
        narration=" ".join(
            str(scene.get("voiceover_segment") or scene.get("narration") or "").split()
        ),
        purpose=str(scene.get("story_purpose") or ""),
        must_fix=tuple(must_fix),
        # A thermometer's scale is not writing: the look is told, and her look may overturn
        # a writing refusal of such a clip (`qc.look_may_overturn`, 2026-10-13).
        expected_markings=planned_markings(words, picture),
    )


def _check_shot(
    engine: Engine,
    *,
    storyboard_id: str,
    correlation_id: str,
    scene: dict[str, Any],
    clip: Path,
    take_id: str,
    seed: int,
    model_id: str,
    adapter: Any,
    price: float,
    committed: float,
    cap: float,
    environment: str,
    bible: dict[str, Any],
    ffmpeg_exe: str | None,
    buy: Callable[[int, str], tuple[Path | None, str | None]],
    registry: Any = None,
    clip_judge: Callable[[int, list[Path]], Any] | None = None,
    face_counter: Callable[..., Any] | None = None,
    clip_check: Callable[..., Any] | None = None,
    retry_deferred: Callable[[], bool] | None = None,
    earlier_answers: Sequence[Sequence[Mapping[str, Any]]] = (),
) -> dict[str, Any]:
    """Clip QC on one bought shot (`qc.qc_clip_with_retry` with `qc.check_clip`, judged by
    `picture_qc.judge_clip`), with at most one retry on the same model, seed + 1 and a firmer
    motion prompt, bought by ``buy(seed, prompt) -> (clip, take_id)`` only when ``committed``
    plus ``price`` stays within ``cap``. Every report is kept on its take.

    Returns ``status`` (PAID: a shot that passed, or one nobody could check and that waits for
    the Owner's look; NEEDS_OWNER: every shot measured wrong), the surviving ``take_id``, the
    Owner's ``reason``, the scene's ``clip_qc`` record and ``cap_stop`` (STOPPED_AT_CAP when
    the retry was not bought because of the cap).

    2026-10-12, late evening: the clip is also checked for what the scene's movement was
    rewritten to fix (`fix_check.open_findings`, motion layer); before the retry is bought the
    Director looks at the refused clip (`fix_check.shot_second_look`) — a clip her look keeps
    is PAID as hers (ACCEPTED_BY_LOOK, its record PASSED with her reason) and nothing more is
    bought; what was accepted on the clip kept is written on it (`fix_check.clip_settled`).

    ``retry_deferred()`` says, after clip QC, that the retry was not bought here but deferred
    to the next RunPod round (`_ShotRounds._check`): clip QC's word on the scene is not its
    last, so nothing is settled (the review of 5fc7468, finding 6: the rewrite's lessons were
    withdrawn before the retry that could prove them was bought). ``earlier_answers``: the
    first clip's answers to the motion items, when this is its retry in a later round.
    """
    from app.media import fix_check, picture_qc  # noqa: PLC0415
    from app.media import qc as clip_qc  # noqa: PLC0415 - qc reads the media models

    index = int(scene["scene_index"])
    # Her reading of an older brief's words before the clip is checked for them (free).
    fix_check.read_film_reasons(
        engine, registry, storyboard_id=storyboard_id, correlation_id=correlation_id
    )
    # 2026-10-12, late evening: what the scene's movement was rewritten to fix is checked on
    # the clip (never on a still, which cannot show it).
    with Session(engine) as session:
        motion_items = fix_check.open_findings(
            session, storyboard_id, index, layer=fix_check.MOTION_LAYER
        )
    plan = _clip_plan(scene, bible, must_fix=motion_items)
    prompt_sent, _negative = motion_request(adapter, scene, from_still=True)

    def judge(frames: list[Path]) -> Any:
        if clip_judge is not None:
            return clip_judge(index, list(frames))
        return picture_qc.judge_clip(
            engine,
            registry,
            frames,
            plan,
            correlation_id,
            motion_prompt=prompt_sent,
            ffmpeg_path=ffmpeg_exe,
        )

    checker = clip_check or clip_qc.check_clip

    def check(path: Path) -> Any:
        return checker(
            path,
            scene=index,
            camera_move=plan.camera_move,
            faces_forbidden=plan.faces_forbidden,
            environment=environment,
            ffmpeg_path=ffmpeg_exe,
            face_counter=face_counter,
            judge=judge,
            **({"must_fix": plan.must_fix} if plan.must_fix else {}),
            **({"expected_markings": plan.expected_markings} if plan.expected_markings else {}),
        )

    checked_takes: list[str] = [take_id]

    def buy_again(new_seed: int, new_prompt: str) -> Path | None:
        path, new_take = buy(new_seed, new_prompt)
        if path is None or new_take is None:
            return None
        checked_takes.append(new_take)
        return path

    def look(report: Any) -> dict[str, Any]:
        # The Director's second look before a retry is bought (the Owner, 2026-10-12): free.
        return fix_check.shot_second_look(
            engine,
            registry,
            storyboard_id=storyboard_id,
            scene_index=index,
            clip=Path(str(report.path)),
            refusal=list(report.blocks_ro),
            correlation_id=correlation_id,
            take_ids=[checked_takes[-1]],
            ffmpeg_path=ffmpeg_exe,
        )

    outcome = clip_qc.qc_clip_with_retry(
        clip,
        check=check,
        buy=buy_again,
        seed=seed,
        motion_prompt=prompt_sent,
        camera_move=plan.camera_move,
        model_id=model_id,
        price_credits=float(price),
        committed_credits=float(committed),
        cap_credits=float(cap),
        look=look,
    )
    kept_by_her = outcome.status == clip_qc.ACCEPTED_BY_LOOK
    records: list[dict[str, Any]] = []
    for attempt, report in enumerate(outcome.reports):
        record = clip_report_record(report)
        if kept_by_her and attempt == len(outcome.reports) - 1:
            # Clip QC refused it and her look kept it: the clip passes as hers (``passed`` too:
            # the review of 5fc7468, finding 10 — a record PASSED but passed False reads as a
            # refusal to whoever reads ``passed``), its blocks kept beside her reason.
            record = {
                **record,
                "verdict": "PASSED",
                "passed": True,
                "accepted_by": fix_check.DIRECTOR_LOOK_APPROVER,
                "director_look": fix_check.look_record(outcome.look),
            }
        checked = checked_takes[min(attempt, len(checked_takes) - 1)]
        used_seed = outcome.seeds[attempt] if attempt < len(outcome.seeds) else None
        _keep_clip_report(
            engine,
            checked,
            record,
            storyboard_id=storyboard_id,
            scene_number=index,
            seed=used_seed,
            attempt=attempt + 1,
            correlation_id=correlation_id,
        )
        records.append({**record, "take_id": checked, "seed": used_seed})
    surviving = [record for record in records if record["verdict"] != "FAILED"]
    final = surviving[-1] if surviving else None
    if (
        final is None
        and outcome.status == "BACK_TO_STILL"
        and records
        and _still_at_renders_cap(engine, storyboard_id, index)
    ):
        # The picture is at fault and has had its three renders: nothing can be bought for
        # it, so the clip stands under the Owner's cap and the film goes on to its QC.
        last = records[-1]
        records[-1] = _keep_clip_under_cap(
            engine,
            last["take_id"],
            last,
            storyboard_id=storyboard_id,
            scene_number=index,
            seed=last.get("seed"),
            attempt=len(records),
            correlation_id=correlation_id,
        )
        final = records[-1]
    kept = final is not None and final["verdict"] == "PASSED"
    if outcome.reports and not (retry_deferred is not None and retry_deferred()):
        with Session(engine) as session, session.begin():
            lock_for_write(session)  # the open items are read before the note and lessons
            fix_check.clip_settled(
                session,
                storyboard_id=storyboard_id,
                scene_number=index,
                take_id=final["take_id"] if final is not None else None,
                must_fix=plan.must_fix,
                reports=list(outcome.reports),
                kept=kept,
                look=outcome.look if kept_by_her else None,
                correlation_id=correlation_id,
                earlier=earlier_answers,
            )
    clip_record: dict[str, Any] = {
        "status": outcome.status,
        "verdict": final["verdict"] if final is not None else "FAILED",
        "accepted_under_cap": bool(final is not None and final.get("accepted_under_cap")),
        "attempts": outcome.attempts,
        "seeds": list(outcome.seeds),
        "retry_credits": outcome.retry_credits,
        "retry_prompt": outcome.prompt or None,
        "reason_ro": outcome.reason_ro,
        "take_id": final["take_id"] if final is not None else None,
        "reports": records,
    }
    accepted_traces = (
        fix_check.minor_traces(getattr(outcome.reports[-1], "fixes", ()) or ())
        if kept and outcome.reports
        else []
    )
    if accepted_traces:
        # On the scene's entry too, beside the note on the take (`fix_check.accepted_on_takes`):
        # what clip QC accepted as a minor trace is not a defect to refuse again after the
        # money (the review of 5fc7468, finding 9).
        clip_record["minor_defects"] = accepted_traces
    cap_stop: str | None = None
    if (
        final is None
        and outcome.attempts == 1
        and records
        and records[0]["verdict"] == "FAILED"
        and committed + price > cap
    ):
        cap_stop = (
            f"STOPPED_AT_CAP: reluarea cadrului scenei {index} ({price:.0f} credite) ar depăși "
            f"plafonul aprobat de {cap:.0f} credite (deja {committed:.0f})."
        )
    if final is None:
        blocks = " ".join(records[-1]["blocks_ro"]) if records else ""
        status = "NEEDS_OWNER"
        if outcome.status == "BACK_TO_STILL" and _send_still_back_for_clip(
            engine,
            storyboard_id,
            index,
            scene.get("still_take_id"),
            f"{outcome.reason_ro} {blocks}".strip(),
            correlation_id,
        ):
            # The picture is at fault and goes back to the stills gate, refused: the scene
            # needs a new still before any motion, and nobody animates this one again.
            status = "NEEDS_STILL"
        return {
            "status": status,
            "take_id": records[-1]["take_id"] if records else take_id,
            "reason": f"{outcome.reason_ro} {blocks}".strip(),
            "clip_qc": clip_record,
            "cap_stop": cap_stop,
        }
    reason: str | None = None
    if final["verdict"] == "UNCHECKED":
        reason = (
            f"Scena {index}: clipul nu a putut fi verificat ("
            + ", ".join(final["unmeasured"] or ["?"])
            + "); așteaptă privirea Proprietarului pe foaia de filmare și nu intră într-un "
            "film de producție fără aprobarea lui."
        )
    return {
        "status": "PAID",
        "take_id": final["take_id"],
        "reason": reason,
        "clip_qc": clip_record,
        "cap_stop": None,
    }


# ------------------------------------------------- tasks the vendor accepted, collected later
#
# 2026-10-01 (PAID_CALLS_AND_TAKE_INTENT): the id of a task the vendor had accepted, and would
# bill, lived only in memory. A poll that ran out of time was recorded REFUSED with the id
# thrown away, a failed download lost it the same way, and a process killed while it waited
# left no row at all: the next run bought the scene again. Now the take is written SUBMITTED,
# with the task id, the moment the vendor accepts it (in its own short transaction, before any
# poll), and is collected here with a GET, which buys nothing: by the next step of the same
# film, and by the watchdog for every film.

#: How long a task the studio never collected is waited for. Runway keeps an output URL for
#: 24 to 48 hours (https://docs.dev.runwayml.com/assets/outputs/, read 2026-10-01); past the
#: lower bound the output may be gone, and the take is LOST, with a letter to the Owner.
SUBMITTED_TAKE_MAX_AGE_SECONDS = 24 * 3600
#: The event a collected (or given up) task is recorded under, on its take.
TAKE_COLLECTED_EVENT = "media.scene_take_collected"
#: A still candidate collected after its step ended: paid, on disk, not judged yet. The stills
#: step judges it (0 credits; the vision model's tokens) before it buys that scene again.
UNJUDGED_FAILURE_CODE = "COLLECTED.UNJUDGED"
UNJUDGED_DETAIL = "Ridicată de la furnizor după pasul în care a fost cumpărată; încă nejudecată."
#: A task never collected before its output expired.
LOST_FAILURE_CODE = "VENDOR.NOT_COLLECTED"
#: How a take of each kind is named in the Owner's letter.
TAKE_KIND_WORDS: dict[str, str] = {
    "still": "imaginea",
    "motion": "cadrul",
    "test_shot": "cadrul de probă",
    "narration": "narațiunea",
}


def _stamp(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def poll_task(adapter: Any, task_id: str, kind: str) -> dict[str, Any]:
    """Ask the vendor what became of a task, by its id. A GET: nothing is bought.

    Uses the adapter's ``collect_task`` (Runway's GET /v1/tasks/{id}); a video adapter with
    only ``get_generation_status`` is asked that. Returns ``state`` (RUNNING, SUCCEEDED,
    FAILED), ``outputs`` as ``(bytes, content_type)`` and the vendor's failure code and
    reason. Raises when it cannot be asked or does not answer.
    """
    collect = getattr(adapter, "collect_task", None)
    if callable(collect):
        answer: dict[str, Any] = asyncio.run(collect(task_id))
        return answer
    status_of = getattr(adapter, "get_generation_status", None)
    if kind in SHOT_TAKE_KINDS and callable(status_of):
        result = asyncio.run(status_of(task_id))
        raw = result.raw_response if isinstance(result.raw_response, dict) else {}
        if result.status == "COMPLETED":
            if not result.video_bytes:
                raise MediaProviderError("the vendor reported success without the clip")
            kind_of = str(raw.get("content_type") or "video/mp4")
            return {"state": "SUCCEEDED", "outputs": [(result.video_bytes, kind_of)]}
        if result.status == "FAILED":
            code = raw.get("failure_code")
            detail = raw.get("failure")
            return {
                "state": "FAILED",
                "outputs": [],
                "failure_code": code if isinstance(code, str) and code else None,
                "failure_detail": detail if isinstance(detail, str) and detail else None,
            }
        return {"state": "RUNNING", "outputs": []}
    raise MediaProviderError("this adapter cannot be asked about a task by its id")


def _land_output(
    engine: Engine,
    take: SceneTake,
    outputs: list[tuple[bytes, str]],
    root: Path,
    correlation_id: str,
) -> list[str]:
    """Write a collected task's outputs to disk and its take(s) PAID. Returns the take ids.

    A shot is one clip on its own take. A still task may carry several candidates: the first
    goes on the SUBMITTED take, every other on a take of its own, the task's credits shared
    between them; each is UNJUDGED until the stills step looks at it.
    """
    from app.providers.media_http import image_dimensions  # noqa: PLC0415

    index = int(take.scene_number)
    share = (
        float(take.credits_quoted) / len(outputs)
        if take.credits_quoted is not None and outputs
        else None
    )
    landed: list[str] = []
    for number, (payload, content_type) in enumerate(outputs):
        if take.kind == "still":
            fmt, _width, _height = image_dimensions(payload, content_type)
            folder = root / take.storyboard_id / "stills"
            name = f"scene_{index:02d}_{uuid4().hex[:8]}_c{number + 1}." + (
                "jpg" if fmt == "jpeg" else fmt
            )
            code, detail = UNJUDGED_FAILURE_CODE, UNJUDGED_DETAIL
        else:
            folder = root / take.storyboard_id / "motion"
            name = f"{take.kind}_{index:02d}_{uuid4().hex[:8]}.mp4"
            code, detail = None, None
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(payload)
        landed.append(
            record_take(
                engine,
                take_id=take.id if number == 0 else None,
                storyboard_id=take.storyboard_id,
                scene_number=index,
                kind=take.kind,
                prompt_hash=take.prompt_hash,
                model_id=take.model_id,
                resolution=take.resolution,
                status="PAID",
                correlation_id=correlation_id,
                seconds=take.seconds,
                seed=take.seed,
                credits_quoted=share,
                path=path,
                sha256=_file_sha256(path),
                failure_code=code,
                failure_detail=detail,
                remote_task_id=take.remote_task_id,
            )
        )
    return landed


def _collected_event(engine: Engine, take: SceneTake, payload: dict, correlation_id: str) -> None:
    with Session(engine) as session, session.begin():
        append_event(
            session,
            TAKE_COLLECTED_EVENT,
            "scene_take",
            take.id,
            1,
            {
                "storyboard_id": take.storyboard_id,
                "scene_number": take.scene_number,
                "kind": take.kind,
                "model_id": take.model_id,
                "remote_task_id": take.remote_task_id,
                **payload,
            },
            correlation_id,
        )


def _lost_letter(engine: Engine, lost: list[dict[str, Any]], correlation_id: str) -> str | None:
    """One letter to the Owner about the paid tasks given up in this pass. Deterministic."""
    from app.agents.messages import post_message  # noqa: PLC0415 - agents import media
    from app.wording import count  # noqa: PLC0415

    if not lost:
        return None
    titles: dict[str, str] = {}
    with Session(engine) as session:
        for item in lost:
            board = session.get(Storyboard, item["storyboard_id"])
            titles[item["storyboard_id"]] = str(board.title) if board is not None else "?"
    lines = [
        "Furnizorul a primit aceste cereri plătite, dar rezultatul lor nu a mai putut fi "
        "ridicat înainte să expire. Nu s-a cumpărat nimic din nou; scenele se planifică din nou "
        "pe foaia de filmare, iar decizia de a le cumpăra rămâne a ta.",
        "",
    ]
    for item in lost:
        credits = item.get("credits")
        lines.append(
            f"- «{titles[item['storyboard_id']]}», scena {item['scene_number']}: "
            f"{TAKE_KIND_WORDS.get(item['kind'], item['kind'])} ({item['model_id']}"
            + (f", {count(round(float(credits)), 'credit', 'credite')}" if credits else "")
            + f"; sarcina {item['remote_task_id']})."
        )
    subject = (
        f"{count(len(lost), 'lucrare plătită pierdută', 'lucrări plătite pierdute')} la "
        f"furnizor ({utc_now()[:10]})"
    )
    with Session(engine) as session, session.begin():
        message = post_message(
            session,
            intent="ESCALATE",
            subject=subject,
            body={"kind": "lost_paid_tasks", "takes": [item["take_id"] for item in lost]},
            body_text="\n".join(lines),
            to_owner=True,
            correlation_id=correlation_id,
        )
        return str(message.id)


def gpu_seconds_to_credits(adapter: Any, *, credit_usd: float) -> Callable[[float], float] | None:
    """Billed GPU-seconds in the step's credits at the adapter's budget rate (RunPod
    Serverless: `RunPodConfig.hourly_rate`, 4.00 USD/h; 0 for the offline mock), or None for an
    adapter not billed by the GPU-second (Runway, ComfyUI): `gpu_batch.run_rounds` then keeps
    its estimate."""
    config = getattr(adapter, "config", None)
    rate = getattr(config, "hourly_rate", None)
    if rate is None or not credit_usd or credit_usd <= 0:
        return None
    per_second = 0.0 if getattr(config, "mock", False) else float(rate) / 3600 / float(credit_usd)
    return lambda seconds: float(seconds) * per_second


def collect_submitted_takes(
    engine: Engine,
    *,
    collector_for: Callable[[SceneTake], Any],
    correlation_id: str,
    storyboard_id: str | None = None,
    kinds: Sequence[str] | None = None,
    storage_root: Path | None = None,
    now: datetime | None = None,
    max_age_seconds: float = SUBMITTED_TAKE_MAX_AGE_SECONDS,
    exclude_storyboards: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Collect every SUBMITTED take (of one film, or all) by its task id. Buys nothing.

    ``exclude_storyboards``: films whose buyer is at work now (the watchdog passes the films
    whose purchase lease is held): their tasks are that buyer's to collect, never twice.

    ``collector_for(take)`` gives the adapter that may be asked about it (None: nobody can be
    asked now). SUCCEEDED: the output is downloaded into the take, PAID (a still candidate
    UNJUDGED). FAILED: the take is REFUSED with the vendor's code. Still running, or the vendor
    did not answer: the take stays SUBMITTED, unless it is older than ``max_age_seconds``,
    when it is LOST and the Owner gets one letter for the pass. Never a POST.
    """
    moment = now or datetime.now(UTC)
    with Session(engine) as session:
        query = select(SceneTake).where(SceneTake.status == "SUBMITTED")
        if storyboard_id is not None:
            query = query.where(SceneTake.storyboard_id == storyboard_id)
        if kinds is not None:
            query = query.where(SceneTake.kind.in_(list(kinds)))
        if exclude_storyboards:
            query = query.where(SceneTake.storyboard_id.not_in(list(exclude_storyboards)))
        rows = list(session.scalars(query.order_by(SceneTake.created_at)).all())
        for row in rows:
            session.expunge(row)
    root = storage_root or DEFAULT_STORAGE_ROOT
    outcomes: list[dict[str, Any]] = []
    lost: list[dict[str, Any]] = []
    for take in rows:
        made = _stamp(take.created_at)
        age = (moment - made).total_seconds() if made is not None else max_age_seconds
        answer: dict[str, Any] | None = None
        problem: str | None = None
        if not take.remote_task_id:
            problem = "no task id"
        else:
            try:
                adapter = collector_for(take)
                if adapter is None:
                    problem = "no adapter"
                else:
                    answer = poll_task(adapter, str(take.remote_task_id), str(take.kind))
            except Exception as exc:  # noqa: BLE001 - asked again later, or given up
                problem = type(exc).__name__
        state = (answer or {}).get("state")
        base = {
            "take_id": take.id,
            "storyboard_id": take.storyboard_id,
            "scene_number": int(take.scene_number),
            "kind": take.kind,
        }
        if state == "SUCCEEDED":
            try:
                landed = _land_output(
                    engine, take, list((answer or {}).get("outputs") or []), root, correlation_id
                )
            except (MediaProviderError, OSError, ValueError) as exc:
                problem = type(exc).__name__
            else:
                _collected_event(
                    engine, take, {"outcome": "PAID", "take_ids": landed}, correlation_id
                )
                outcomes.append({**base, "status": "PAID", "take_ids": landed})
                continue
        if state == "FAILED":
            code = (answer or {}).get("failure_code")
            record_take(
                engine,
                take_id=take.id,
                storyboard_id=take.storyboard_id,
                scene_number=int(take.scene_number),
                kind=take.kind,
                prompt_hash=take.prompt_hash,
                model_id=take.model_id,
                resolution=take.resolution,
                status="REFUSED",
                correlation_id=correlation_id,
                seconds=take.seconds,
                seed=take.seed,
                credits_quoted=take.credits_quoted,
                failure_code=str(code)[:100] if code else "VENDOR.FAILED",
                failure_detail=(answer or {}).get("failure_detail"),
            )
            _collected_event(engine, take, {"outcome": "REFUSED", "code": code}, correlation_id)
            outcomes.append({**base, "status": "REFUSED", "failure_code": code})
            continue
        if age >= max_age_seconds:
            hours = int(age // 3600)
            record_take(
                engine,
                take_id=take.id,
                storyboard_id=take.storyboard_id,
                scene_number=int(take.scene_number),
                kind=take.kind,
                prompt_hash=take.prompt_hash,
                model_id=take.model_id,
                resolution=take.resolution,
                status="LOST",
                correlation_id=correlation_id,
                seconds=take.seconds,
                seed=take.seed,
                credits_quoted=take.credits_quoted,
                failure_code=LOST_FAILURE_CODE,
                failure_detail=(
                    f"Rezultatul nu a putut fi ridicat de la furnizor în {hours} ore de la "
                    "cumpărare și poate să fi expirat; nu s-a cumpărat nimic din nou."
                ),
            )
            _collected_event(engine, take, {"outcome": "LOST", "problem": problem}, correlation_id)
            item = {
                **base,
                "status": "LOST",
                "model_id": take.model_id,
                "credits": take.credits_quoted,
                "remote_task_id": take.remote_task_id,
            }
            lost.append(item)
            outcomes.append(item)
            continue
        outcomes.append({**base, "status": "SUBMITTED", "reason": problem or "RUNNING"})
    if lost:
        letter = _lost_letter(engine, lost, correlation_id)
        for item in lost:
            item["letter_id"] = letter
    if outcomes:
        logger.info(
            "submitted_takes_collected",
            extra={
                "checked": len(outcomes),
                "paid": sum(1 for o in outcomes if o["status"] == "PAID"),
                "refused": sum(1 for o in outcomes if o["status"] == "REFUSED"),
                "lost": len(lost),
            },
        )
    return outcomes


def check_unchecked_shots(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    *,
    adapter_for_model: Callable[[str], Any],
    environment: str,
    ffmpeg_path: str | None = None,
    registry: Any = None,
    clip_judge: Callable[[int, list[Path]], Any] | None = None,
    face_counter: Callable[..., Any] | None = None,
    clip_check: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """Clip QC on every paid shot of this film that was bought but never checked.

    A shot collected after its step ended, or one whose process died between landing and its
    check, has no clip-QC report; in PRODUCTION such a shot never enters the film and nothing
    else would ever check it. Checked here like any bought shot (`_check_shot`), with no retry
    bought: a shot measured wrong goes to the Owner. Only shots that carry a vendor task id
    (bought since migration 0049); older takes keep the rule they were bought under.
    """
    ffmpeg_exe = resolve_ffmpeg_path(ffmpeg_path)
    if ffmpeg_exe is None:
        return []
    with Session(engine) as session:
        rows = session.scalars(
            select(SceneTake)
            .where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.kind.in_(SHOT_TAKE_KINDS),
                SceneTake.status == "PAID",
                SceneTake.remote_task_id.is_not(None),
                SceneTake.path.is_not(None),
            )
            .order_by(SceneTake.created_at)
        ).all()
        unchecked = [row for row in rows if clip_qc_of(session, row.id) is None]
        for row in unchecked:
            session.expunge(row)
        board = session.get(Storyboard, storyboard_id)
        bible = dict(board.visual_bible_json or {}) if board is not None else {}
    if not unchecked:
        return []
    _title, scenes = _storyboard_scenes(engine, storyboard_id)
    by_index = {int(scene["scene_index"]): scene for scene in scenes}
    checked: list[dict[str, Any]] = []
    for take in unchecked:
        scene = by_index.get(int(take.scene_number))
        clip = Path(str(take.path))
        if scene is None or not clip.is_file():
            continue
        adapter = adapter_for_model(str(take.model_id))
        if adapter is None:
            continue
        verdict = _check_shot(
            engine,
            storyboard_id=storyboard_id,
            correlation_id=correlation_id,
            scene=scene,
            clip=clip,
            take_id=take.id,
            seed=int(take.seed if take.seed is not None else film_seed(storyboard_id)),
            model_id=str(take.model_id),
            adapter=adapter,
            # No retry is bought here: a cap of 0 under a price of at least 1 says so.
            price=max(1.0, float(take.credits_quoted or 0.0)),
            committed=0.0,
            cap=0.0,
            environment=environment,
            bible=bible,
            ffmpeg_exe=ffmpeg_exe,
            buy=lambda _seed, _prompt: (None, None),
            registry=registry,
            clip_judge=clip_judge,
            face_counter=face_counter,
            clip_check=clip_check,
        )
        checked.append(
            {
                "take_id": take.id,
                "scene_index": int(take.scene_number),
                "status": verdict["status"],
                "verdict": verdict["clip_qc"]["verdict"],
            }
        )
    return checked


def _record_intent(
    engine: Engine,
    task_id: str,
    *,
    storyboard_id: str,
    scene_number: int,
    kind: str,
    prompt_hash: str,
    model_id: str,
    resolution: str,
    correlation_id: str,
    credits: float | None,
    seconds: float | None = None,
    seed: int | None = None,
) -> str | None:
    """The SUBMITTED take of a task the vendor just accepted, in its own transaction.

    Written before any poll. If even this write fails the task id is logged (it is not a
    secret) so the Owner's operator can collect it by hand, and the purchase goes on: the
    shot is paid for, and polling for it is better than dropping it.
    """
    try:
        return record_take(
            engine,
            storyboard_id=storyboard_id,
            scene_number=scene_number,
            kind=kind,
            prompt_hash=prompt_hash,
            model_id=model_id,
            resolution=resolution,
            status="SUBMITTED",
            correlation_id=correlation_id,
            seconds=seconds,
            seed=seed,
            credits_quoted=credits,
            remote_task_id=task_id,
        )
    except SQLAlchemyError as exc:
        logger.error(
            "take_intent_not_recorded",
            extra={
                "storyboard_id": storyboard_id,
                "scene_number": scene_number,
                "kind": kind,
                "remote_task_id": task_id,
                "error": type(exc).__name__,
            },
        )
        return None


@dataclass
class _ShotRound:
    """One scene's shot bought in rounds on RunPod Serverless."""

    index: int
    entry: dict[str, Any]
    adapter: Any
    model_id: str
    price: int
    seconds: int
    identity: str
    still: SceneTake
    first_frame: bytes
    prompt: str
    negative: str | None
    seed: int
    committed_before: float
    #: The scene's identity as the hold event names it (`identity_key`).
    hold_identity: Any = None
    attempt: int = 1
    attempts: int = 0
    retried_failure: bool = False
    #: The clip-QC retry the first check asked for: (seed, firmer prompt), bought next round.
    qc_retry: tuple[int, str] | None = None
    first_qc: dict[str, Any] | None = None
    outcome: dict[str, Any] | None = None
    intents: dict[str, str | None] | None = None
    uncertain: bool = False
    cancelled: bool = False
    failed: str | None = None
    #: The REFUSED take of each item whose /run got no job id (journal row id -> take id).
    refused: dict[str, str] | None = None
    #: Its /run was proven never queued (`gpu_batch.run_rounds`' proof): nothing was bought.
    not_queued: bool = False


class _ShotRounds:
    """The motion stairs (test shot, motion, a scene redo) on RunPod Serverless: every shot
    of the step in ONE batch job per round, inside one GPU session, each clip checked as it
    lands (clip QC); a failing clip's one retry (seed + 1, the camera move asked more firmly)
    is the next round, inside the cap."""

    def __init__(
        self,
        engine: Engine,
        *,
        storyboard_id: str,
        correlation_id: str,
        take_kind: str,
        meter: SpendMeter,
        cap: float,
        overhead: float,
        credit_usd: float,
        work_dir: Path,
        environment: str,
        bible: dict[str, Any],
        ffmpeg_exe: str | None,
        registry: Any,
        clip_judge: Any,
        face_counter: Any,
        clip_check: Any,
        charged: list[dict[str, Any]],
        bought_now: list[int],
        over_attempts: Callable[[int], bool],
        attempts_reason: Callable[[int], str],
        sent: dict[int, int],
        scene_dicts: dict[int, dict[str, Any]],
        room: Callable[..., float] | None = None,
        budget_words: Callable[[], str | None] | None = None,
    ) -> None:
        self.engine = engine
        self.storyboard_id = storyboard_id
        self.correlation_id = correlation_id
        self.take_kind = take_kind
        self.meter = meter
        self.cap = cap
        self.overhead = overhead
        self.credit_usd = credit_usd
        self.work_dir = work_dir
        self.environment = environment
        self.bible = bible
        self.ffmpeg_exe = ffmpeg_exe
        self.registry = registry
        self.clip_judge = clip_judge
        self.face_counter = face_counter
        self.clip_check = clip_check
        self.charged = charged
        self.bought_now = bought_now
        self.over_attempts = over_attempts
        self.attempts_reason = attempts_reason
        self.sent = sent
        self.scene_dicts = scene_dicts
        # The step's budget hold (`shooting_sheet.StepHold`): what may still be committed,
        # grown for a round before it is fitted; None, the cap alone binds.
        self.room = room
        self.budget_words = budget_words or (lambda: None)
        self.states: dict[int, _ShotRound] = {}
        self.stop: str | None = None

    def _left(self) -> float:
        """What the step may still commit: the cap's rest, or what its budget hold covers."""
        if self.room is not None:
            return float(self.room(0.0))
        return float(self.cap) - self.meter.committed

    def _round_room(self, price: float) -> None:
        """Before a round is fitted: the hold grows to it, or by what the budgets have left
        (the round is then cut to what is held, `gpu_batch.run_rounds`)."""
        if self.room is not None:
            self.room(price, partial=True)

    # ------------------------------------------------------------------ requests

    def _request(self, state: _ShotRound, *, seed: int, prompt: str) -> Any:
        from decimal import Decimal  # noqa: PLC0415

        from app.providers.runpod.batch import BatchRequest  # noqa: PLC0415

        return BatchRequest(
            operation="video",
            project_id=self.storyboard_id,
            scene_id=str(state.index),
            candidate_index=0,
            attempt_number=state.attempt,
            model=state.model_id,
            prompt=prompt,
            negative_prompt=state.negative,
            seed=seed,
            width=1080,
            height=1920,
            duration=float(state.seconds),
            fps=24,
            references=(),
            source_image=state.first_frame,
            price_usd=Decimal(state.price) * Decimal(str(self.credit_usd)),
        )

    def _send(self, state: _ShotRound, *, seed: int, prompt: str) -> list[Any]:
        if self.over_attempts(state.index):
            state.outcome = {"status": "NEEDS_OWNER", "reason": self.attempts_reason(state.index)}
            return []
        from app.media.input_guard import (  # noqa: PLC0415
            REFUSAL_CODE,
            identity_of_request,
            record_refusal,
            refused_before,
        )

        request = self._request(state, seed=seed, prompt=prompt)
        identity = identity_of_request(request)
        with Session(self.engine) as session, session.begin():
            refusal = refused_before(session, identity)
            if refusal is not None:
                record_refusal(session, identity, refusal, correlation_id=self.correlation_id)
        if refusal is not None:
            state.outcome = {
                "status": "NEEDS_STILL" if refusal.layer == "still" else "NEEDS_OWNER",
                "failure_code": REFUSAL_CODE,
                "rewrite": refusal.layer is not None,
                "layer": refusal.layer,
                "reason": refusal.reason_ro,
            }
            if refusal.layer == "still":
                _send_still_back_for_clip(
                    self.engine,
                    self.storyboard_id,
                    state.index,
                    state.still.id,
                    refusal.reason_ro,
                    self.correlation_id,
                )
            return []
        state.attempts += 1
        self.sent[state.index] = self.sent.get(state.index, 0) + 1
        return [request]

    def price(self, requests: list[Any]) -> float:
        """A round's credits: each shot's price and one GPU start (cold start + idle tail)."""
        return float(sum(self.states[int(r.scene_id)].price for r in requests)) + self.overhead

    # ------------------------------------------------------------------ callbacks

    def submitted(self, item: Any) -> None:
        state = self.states[int(item.request.scene_id)]
        if state.intents is None:
            state.intents = {}
        state.intents[item.job_row_id] = _record_intent(
            self.engine,
            str(item.remote_item_id),
            storyboard_id=self.storyboard_id,
            scene_number=state.index,
            kind=self.take_kind,
            prompt_hash=state.identity,
            model_id=state.model_id,
            resolution=MOTION_RESOLUTION,
            correlation_id=self.correlation_id,
            credits=float(state.price),
            seconds=float(state.seconds),
            seed=int(item.request.seed),
        )

    def landed(self, outcome: Any) -> None:
        """A clip came back: PAID on its take, then checked at once (clip QC); the worker
        meanwhile makes the next shot."""
        from app.providers.runpod.batch import UNCERTAIN  # noqa: PLC0415

        state = self.states[int(outcome.item.request.scene_id)]
        intent = (state.intents or {}).get(outcome.item.job_row_id)
        seed = int(outcome.item.request.seed)
        if outcome.state == "COMPLETED" and outcome.path is not None:
            clip = self.work_dir / f"{self.take_kind}_{state.index:02d}_{uuid4().hex[:8]}.mp4"
            clip.write_bytes(Path(outcome.path).read_bytes())
            take_id = record_take(
                self.engine,
                take_id=intent,
                storyboard_id=self.storyboard_id,
                scene_number=state.index,
                kind=self.take_kind,
                prompt_hash=state.identity,
                model_id=state.model_id,
                resolution=MOTION_RESOLUTION,
                status="PAID",
                correlation_id=self.correlation_id,
                seconds=float(state.seconds),
                seed=seed,
                credits_quoted=float(state.price),
                path=clip,
                sha256=_file_sha256(clip),
                remote_task_id=outcome.item.remote_item_id,
            )
            self.charged.append(
                {
                    "take_id": take_id,
                    "model": state.model_id,
                    "seconds": state.seconds,
                    "spend": float(state.price),
                }
            )
            self._check(state, clip, take_id, seed)
            return
        error = str(outcome.error or outcome.state)
        uncertain = error == UNCERTAIN
        state.uncertain = state.uncertain or uncertain
        state.cancelled = state.cancelled or outcome.state == "CANCELLED"
        state.failed = error
        take_id = record_take(
            self.engine,
            take_id=intent,
            storyboard_id=self.storyboard_id,
            scene_number=state.index,
            kind=self.take_kind,
            prompt_hash=state.identity,
            model_id=state.model_id,
            resolution=MOTION_RESOLUTION,
            status="REFUSED",
            correlation_id=self.correlation_id,
            seconds=float(state.seconds),
            seed=seed,
            credits_quoted=float(state.price) if uncertain else None,
            failure_code=(
                UNANSWERED_FAILURE_CODE
                if uncertain
                else CANCELLED_FAILURE_CODE
                if outcome.state == "CANCELLED"
                else f"RUNPOD.{error}"[:100]
            ),
            failure_detail=CANCELLED_DETAIL if outcome.state == "CANCELLED" else None,
            remote_task_id=outcome.item.remote_item_id,
        )
        if uncertain:
            if state.refused is None:
                state.refused = {}
            state.refused[outcome.item.job_row_id] = take_id

    def unsent(self, outcomes: list[Any], proof: dict[str, Any]) -> None:
        """The GPU-off proved these items never queued (`gpu_batch.run_rounds`): their takes
        are re-recorded as not queued (no credits) and a scene whose every uncertain item was
        proven is no longer uncertain: nothing was bought, nothing is held."""
        touched: dict[int, _ShotRound] = {}
        for outcome in outcomes:
            state = self.states[int(outcome.item.request.scene_id)]
            take = (state.refused or {}).pop(outcome.item.job_row_id, None)
            if take is not None:
                with Session(self.engine) as session, session.begin():
                    lock_for_write(session)
                    recode_not_queued(
                        session,
                        [take],
                        detail=NOT_QUEUED_DETAIL,
                        correlation_id=self.correlation_id,
                        by="proof",
                    )
            touched[state.index] = state
        for state in touched.values():
            if not state.refused:
                state.uncertain = False
                state.not_queued = True

    def _check(self, state: _ShotRound, clip: Path, take_id: str, seed: int) -> None:
        """Clip QC on a landed clip. The first clip's one retry is not bought here: it is
        remembered and bought in the next round (a batch), still inside the cap."""
        from app.media import fix_check  # noqa: PLC0415

        asked: list[tuple[int, str]] = []
        first = state.qc_retry is None and state.first_qc is None

        def defer(new_seed: int, new_prompt: str) -> tuple[Path | None, str | None]:
            if first:
                asked.append((new_seed, new_prompt))
            return None, None

        checked = _check_shot(
            self.engine,
            storyboard_id=self.storyboard_id,
            correlation_id=self.correlation_id,
            scene=self.scene_dicts[state.index],
            clip=clip,
            take_id=take_id,
            seed=seed,
            model_id=state.model_id,
            adapter=state.adapter,
            price=float(state.price),
            committed=self.meter.committed,
            cap=float(self.cap),
            environment=self.environment,
            bible=self.bible,
            ffmpeg_exe=self.ffmpeg_exe,
            buy=defer,
            registry=self.registry,
            clip_judge=self.clip_judge,
            face_counter=self.face_counter,
            clip_check=self.clip_check,
            # The retry bought in the next round: nothing is settled before it is checked,
            # and its check reads the first clip's answers beside its own.
            retry_deferred=lambda: bool(asked),
            earlier_answers=fix_check.recorded_answers(state.first_qc),
        )
        if asked:
            state.qc_retry = asked[0]
            state.first_qc = checked["clip_qc"]
            return
        clip_record = checked["clip_qc"]
        if state.first_qc is not None:
            # The retry's report follows the first clip's: the scene's whole clip QC.
            clip_record = {
                **clip_record,
                "attempts": 2,
                "seeds": [*state.first_qc.get("seeds", [])[:1], seed],
                "reports": [*state.first_qc.get("reports", []), *clip_record.get("reports", [])],
            }
        state.entry["clip_qc"] = clip_record
        state.outcome = {
            "status": checked["status"],
            "take_id": checked["take_id"],
            "credits_quoted": float(state.price) * state.attempts,
        }
        if checked["reason"]:
            state.outcome["reason"] = checked["reason"]
        if state.first_qc is not None and checked["status"] == "NEEDS_OWNER":
            blocks = [
                b for r in clip_record.get("reports", [])[-1:] for b in r.get("blocks_ro", [])
            ]
            state.outcome["reason"] = (
                f"Scena {state.index}: clipul a picat controlul și la reluare (sămânța {seed}); "
                "decide Proprietarul. " + " ".join(blocks)
            ).strip()
        if checked["status"] == "PAID":
            self.bought_now.append(state.index)
        if checked["cap_stop"] and self.stop is None and state.first_qc is None:
            self.stop = checked["cap_stop"]

    # ------------------------------------------------------------------- deciding

    def _decide(self, state: _ShotRound) -> list[Any]:
        """The scene after its round: done, its clip-QC retry, or one retry of a shot the
        worker failed (same words, same seed, a new attempt)."""
        if state.outcome is not None:
            return []
        if state.uncertain:
            state.entry.update(failure_kind="UNANSWERED", failure_code=UNANSWERED_FAILURE_CODE)
            self.stop = UNANSWERED_REASON.format(scene=state.index)
            state.outcome = {"status": "NEEDS_OWNER", "reason": self.stop}
            return []
        if state.not_queued:
            # RunPod never queued its /run (proven at the GPU-off): not bought, not held.
            state.outcome = {
                "status": "NOT_BOUGHT",
                "reason": NOT_QUEUED_REASON.format(scene=state.index),
            }
            return []
        if state.cancelled:
            state.outcome = {
                "status": "NOT_BOUGHT",
                "reason": self.stop or "Pasul s-a oprit; restul nu s-a cumpărat.",
            }
            return []
        if state.qc_retry is not None and state.attempts < 2:
            new_seed, new_prompt = state.qc_retry
            state.attempt += 1
            return self._send(state, seed=new_seed, prompt=new_prompt)
        if state.failed is not None and not state.retried_failure:
            state.retried_failure = True
            state.failed = None
            state.attempt += 1
            return self._send(state, seed=state.seed, prompt=state.prompt)
        if state.failed is not None:
            state.entry.update(failure_kind="BAD_OUTPUT", failure_code=state.failed)
            state.outcome = {
                "status": "NEEDS_OWNER",
                "reason": f"Scena {state.index}: RunPod nu a dat cadrul de două ori "
                f"({state.failed}); decide Proprietarul.",
            }
        return []

    def next_round(self, outcomes: list[Any]) -> list[Any]:
        requests: list[Any] = []
        for index in sorted({int(o.item.request.scene_id) for o in outcomes}):
            requests += self._decide(self.states[index])
        return [] if self.stop is not None else requests

    # ----------------------------------------------------------------------- run

    @purchase_flow
    def run(
        self,
        shots: list[_ShotRound],
        *,
        permit: Any,
        guard: Any,
        stopped: Callable[[], str | None],
    ) -> Generator[RoundWork, dict[str, Any], dict[str, Any]]:
        from app.providers.runpod.batch import UNCERTAIN  # noqa: PLC0415
        from app.workflows.director_upkeep import director_wait_work  # noqa: PLC0415

        first: list[Any] = []
        for state in shots:
            self.states[state.index] = state
            first += self._send(state, seed=state.seed, prompt=state.prompt)
        summary: dict[str, Any] = {"rounds": 0, "stopped": None, "cap_stop": None}
        if first:
            summary = yield RoundWork(
                engine=self.engine,
                adapter=shots[0].adapter,
                permit=permit,
                purpose="video",
                first_round=first,
                next_round=self.next_round,
                price_credits=self.price,
                cap_left=self._left,
                make_room=self._round_room if self.room is not None else None,
                guard=guard,
                stopped=stopped,
                on_submitted=self.submitted,
                on_outcome=self.landed,
                meter=self.meter,
                credits_for_seconds=gpu_seconds_to_credits(
                    shots[0].adapter, credit_usd=self.credit_usd
                ),
                on_unsent=self.unsent,
                on_wait=director_wait_work(self.engine, self.registry),
            )
        budget_cut(summary, self.budget_words)
        if summary.get("stopped") and summary.get("stopped") != UNCERTAIN:
            self.stop = self.stop or summary["stopped"]
        for state in shots:
            if state.outcome is None:
                self._decide(state)
            if state.outcome is None and state.first_qc is not None:
                # Its clip-QC retry was never bought (a stop, the cap): the first clip's verdict.
                state.entry["clip_qc"] = state.first_qc
                state.outcome = {
                    "status": "NEEDS_OWNER",
                    "reason": str(state.first_qc.get("reason_ro") or self.stop or ""),
                }
            if state.outcome is None:
                state.outcome = {
                    "status": "NOT_BOUGHT",
                    "reason": self.stop or summary.get("cap_stop") or "Nu s-a cumpărat.",
                }
            state.entry.update(state.outcome)
            state.entry["attempts"] = state.attempts
            if state.outcome["status"] in ("NEEDS_OWNER", "NEEDS_STILL"):
                free = (
                    str(state.entry.get("failure_kind") or "") in FREE_FAILURE_KINDS
                    and self.meter.committed <= state.committed_before
                )
                _storyboard_event(
                    self.engine,
                    MOTION_HOLD_EVENT,
                    self.storyboard_id,
                    {
                        "severity": "WARNING",
                        "scene_number": state.index,
                        "status": state.outcome["status"],
                        "reason": state.outcome["reason"],
                        "failure_kind": state.entry.get("failure_kind"),
                        "suggested": None,
                        "clip_qc": (state.entry.get("clip_qc") or {}).get("verdict"),
                        "identity": state.hold_identity,
                        "holds": not free,
                        **runpod_hold_items(state.refused),
                    },
                    self.correlation_id,
                )
        summary["stopped"] = self.stop or summary.get("cap_stop")
        return summary


def _gpu_precheck(
    engine: Engine, adapter: Any, integration_id: str | None, plan: dict[str, Any]
) -> None:
    """`gpu_batch.gpu_precheck` for the adapter the step buys from, when it buys in rounds.
    It reuses the adapter the step already resolved: no extra `adapter_for_model` call."""
    from app.media import gpu_batch  # noqa: PLC0415 - gpu_batch reads runpod
    from app.providers.runpod.batch import supports_batch  # noqa: PLC0415
    from app.providers.runpod.gpu_session import GpuSessionRefused  # noqa: PLC0415

    if adapter is None or not supports_batch(adapter):
        return
    try:
        gpu_batch.gpu_precheck(engine, adapter, purpose="video", integration_id=integration_id)
    except GpuSessionRefused as exc:
        raise MotionStepRefused(str(exc.code), exc.reason_ro, plan=plan) from exc


@purchase_flow
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
    registry: Any = None,
    clip_judge: Callable[[int, list[Path]], Any] | None = None,
    face_counter: Callable[..., Any] | None = None,
    clip_check: Callable[..., Any] | None = None,
    meter: SpendMeter | None = None,
    unasked: bool = True,
    timezone: str | None = None,
    proposal: bool = False,
    director_repair: bool = False,
    budget_hold: Any = None,
) -> Generator[RoundWork, dict[str, Any], dict[str, Any]]:
    """One step of the motion staircase (``test_shot`` or ``motion``), bought only under the
    Owner's yes for this plan and this cap.

    ``meter`` (`SpendMeter`) is kept up to date as the step sends and commits, so a caller
    can book what was spent when the step raises half-way. A request that may have been
    charged without an answer (`possibly_charged`) counts against the cap, is never sent
    again automatically, and stops the step; before every request the balance is read again
    and the step stops when the account lost more than it counted (`uncounted_drop`).

    Every shot bought is checked before the step goes on (`_check_shot`: qc.check_clip, the
    vision model through ``registry`` or ``clip_judge(scene, frames)``, YuNet through
    ``face_counter``; ``clip_check`` replaces qc.check_clip in tests). A failing shot is
    bought again once, inside the cap, else the scene goes to the Owner; each report is kept
    on its take and on the scene's entry (``clip_qc``).

    ``step='scene_redo'`` with ``redo_scene`` buys that one scene's shot again under
    ``media.scene_redo`` (`redo_scene`, the per-scene redo): the scene's old shot takes are
    retired (REJECTED, ``REDO.OWNER``) in the same transaction that spends the yes; unasked,
    a shot the Owner approved himself is never retired (`SceneRedoRefused` OWNER_APPROVED,
    the transaction rolled back, 2026-10-10). Unasked with ``proposal`` (the studio's
    proposal of a longer clip, `propose_clip_redos`), a redo of a shot he approved himself is
    his question even where his rule and mode would let it buy unasked: it is raised (or his
    standing answer for this plan read, a yes spent) in that transaction, and nothing is
    retired or bought until his yes (his card of 2026-10-10).

    Before anything is planned, the film's SUBMITTED shots are collected by their task ids
    (`collect_submitted_takes`, a GET each, nothing bought), and every paid shot nobody has
    checked yet is checked (`check_unchecked_shots`). A shot is written SUBMITTED, with the
    vendor's task id, the moment the vendor accepts it; a clip that does not arrive leaves the
    scene IN_FLIGHT (collected later, never bought again) and stops the step.

    A scene a step left to the Owner is held (`scene_memory`) and is in no later step's
    purchase until he decides on the sheet; no scene is sent more than
    `max_paid_attempts_per_scene` paid requests since his last decision about it (a redo,
    his own act, is not counted). Each NEEDS_OWNER event names the scene's identity and
    whether it holds the scene.

    ``plan_hash`` is the hash of the plan he was shown (`motion_plan`; the shooting sheet may
    pass ``plan_hash_of`` so its own hash is the one his yes is bound to). ``cap_credits`` is
    the cap he approved (default: the step's cost plus one redo of its dearest shot).
    ``adapter_for_model`` gives the adapter of a model id; ``account`` reads the balance
    (default: the first adapter). Raises `MotionStepRefused` when nothing may be bought;
    otherwise returns what was bought, per scene, and what it cost, quoted and measured.

    ``unasked`` (the default) is a step nobody pressed (the day's staircase, FILM_CONTINUE, the
    day's QC repairs): refused before the balance is read when the Policy Kernel refuses it
    outright, and stopped before any later shot or retry when the Owner's mode or rule no
    longer lets it buy (`mode_guard`, spec 51). False is his own press, which goes on through
    BLOCKED_MODE and NEEDS_APPROVAL. ``timezone`` is his clock, for the stop's sentence.

    ``budget_hold`` is the sheet step's hold on the budgets (`shooting_sheet.StepHold`): it
    holds the step's first round, and is grown before every later shot, retry or round; what
    it cannot hold is not bought, and the step ends on the budget's words.
    """
    from app.economy.credits import record_measured_prices  # noqa: PLC0415
    from app.media.mode_guard import PurchaseGuard, unasked_refusal  # noqa: PLC0415
    from app.runbook.services import stop_requested  # noqa: PLC0415 - runbook imports media
    from app.services import may_act, studio_environment  # noqa: PLC0415

    actions = {**MOTION_STEP_ACTIONS, REDO_STEP: REDO_ACTION}
    if step not in actions:
        raise ValueError(f"unknown motion step: {step}")
    meter = meter if meter is not None else SpendMeter()
    storage_root = storage_root or media_root(settings)
    if (step == REDO_STEP) != (redo_scene is not None):
        raise ValueError("a scene redo names its scene, and only a scene redo does")
    resolution = resolution or str(
        getattr(settings, "motion_resolution", None) or MOTION_STEP_RESOLUTION
    )
    margin = margin_of(settings)
    caps = _capabilities(engine, capabilities, integration_id)
    environment = environment or studio_environment(engine)
    if table is None:
        # A redo reaches this step with no table of its own (`_paid_redo`): priced as the
        # sheet prices, with this connection's measured rows and the RunPod profile's estimates.
        from app.media.shooting_sheet import price_table_for  # noqa: PLC0415 - it imports us

        table = price_table_for(engine, integration_id)
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
    # The plan his yes is bound to is the one read before anything is collected: collecting
    # only ever takes scenes out of buying (an open task landed, a shot checked), and his yes
    # must not go stale because the vendor delivered.
    current = plan_hash_of(engine, storyboard_id) if plan_hash_of else plan["plan_hash"]
    # What the vendor already made for this film is collected (a GET each) and every paid
    # shot nobody checked is checked, whatever the step decides next: a shot already paid for
    # is never planned, and never bought, again.
    collected = collect_submitted_takes(
        engine,
        collector_for=lambda take: adapter_for_model(str(take.model_id)),
        correlation_id=correlation_id,
        storyboard_id=storyboard_id,
        kinds=SHOT_TAKE_KINDS,
        storage_root=storage_root,
    )
    rechecked = check_unchecked_shots(
        engine,
        storyboard_id,
        correlation_id,
        adapter_for_model=adapter_for_model,
        environment=environment,
        ffmpeg_path=ffmpeg_path,
        registry=registry,
        clip_judge=clip_judge,
        face_counter=face_counter,
        clip_check=clip_check,
    )
    # A disk too full for the clips refuses before anything is asked or bought (REL-08): a
    # shot that cannot be written is a shot paid for and lost. Collecting and checking what
    # was already paid for came first, because it buys nothing.
    no_room = disk_refusal(storage_root, settings)
    if no_room:
        raise MotionStepRefused(LOW_DISK, no_room, plan=plan)
    # The hero test shot is accepted here by its clip QC when the Owner's rule lets the motion
    # through unasked (HERO_AUTO_ACCEPT); his yes for this plan, if one is needed, is still
    # read by may_act below, bound to the hash read before anything was collected.
    hero_accepted = _refuse_before_buying(
        engine,
        state,
        step,
        plan_hash,
        environment=environment,
        plan_hash_of=None,
        storyboard_id=storyboard_id,
        current=current,
        cap_credits=cap_credits,
        requester=requester,
        correlation_id=correlation_id,
    )
    view = {item["scene_index"]: item for item in plan["scenes"]}
    step_plan = plan["steps"][step]
    to_buy = [int(index) for index in step_plan["to_buy"]]
    cap = int(cap_credits) if cap_credits is not None else int(step_plan["cap_credits"])
    cap_usd = round(cap * prices.credit_usd, 6)

    def room(wanted: float = 0.0, *, partial: bool = False) -> float:
        """The credits the step may still commit: the cap's rest and, with the sheet's budget
        hold, no more than it covers once grown for ``wanted`` more (`StepHold.room`; a round
        of shots may grow it by what is left, ``partial``, and is cut to it)."""
        rest = float(cap) - meter.committed
        if budget_hold is None:
            return rest
        return min(rest, float(budget_hold.room(meter.committed, wanted, partial=partial)))

    def budget_words(wanted: float | None = None) -> str | None:
        """The budget's words when the hold, not the cap, stopped the next purchase
        (``wanted`` credits, when known)."""
        if budget_hold is None:
            return None
        if wanted is None:
            return budget_hold.budget_words()
        return budget_hold.budget_words(meter.committed, wanted)

    take_kind = MOTION_STEP_TAKE_KINDS.get(step, "motion")
    source = account
    before: float | None = None
    read = False
    ffmpeg_exe: str | None = None
    work_dir = storage_root / storyboard_id / "motion"
    # The Owner's policy read before each later request (`mode_guard`); None with nothing to buy.
    guard: PurchaseGuard | None = None

    if to_buy:
        ffmpeg_exe = resolve_ffmpeg_path(ffmpeg_path)
        if ffmpeg_exe is None:
            raise MotionStepRefused(
                "NO_ENCODER",
                "FFmpeg nu este instalat: imaginea aprobată nu poate fi pregătită ca prim cadru.",
                plan=plan,
            )
        asked_about = {"plan_hash": plan_hash, "cap_credits": cap}
        if unasked:
            # Unasked, the Owner's mode is asked before his balance (2026-10-04): a step the
            # kernel refuses outright reads no balance and raises no low-balance card.
            refused = unasked_refusal(
                engine,
                actions[step],
                subject=storyboard_id,
                context=asked_about,
                cost_usd=cap_usd,
                requester=requester,
            )
            if refused is not None:
                raise MotionStepRefused(str(refused["status"]), str(refused["reason"]), plan=plan)
        if source is None:
            source = adapter_for_model(str(view[to_buy[0]]["model_id"]))
        # RunPod Serverless: a GPU that could not be switched on (his card not accepted, no
        # bucket) refuses here, before his yes is asked for or spent with nothing bought.
        _gpu_precheck(engine, source, integration_id, plan)
        read, before, problem = _account_balance(source)
        if problem is not None:
            raise MotionStepRefused(LOW_BALANCE, f"Nu se cumpără mișcare: {problem}.", plan=plan)
        # The Owner's rule (2026-10-03): the step starts on its next round (the test shot's one
        # shot, the motion's shots, a redo's one shot) x the margin; the cap stays the ceiling
        # and every shot after the first reads the balance again.
        first_round = int(step_plan["cost_credits"])
        if before is not None and before < needed_credits(first_round, margin):
            raise MotionStepRefused(
                LOW_BALANCE,
                start_refusal_ro(
                    before,
                    first_round,
                    cap,
                    margin,
                    STEP_ROUND_WORDS.get(step, f"refacerii scenei {redo_scene}"),
                ),
                plan=plan,
            )
        evidence = (
            f"{len(to_buy)} cadre (scenele {', '.join(map(str, to_buy))}), "
            f"{step_plan['cost_credits']} credite, plafon {cap}; cost estimat "
            f"{_usd_ro(step_plan['cost_usd'])}, plafon {_usd_ro(cap_usd)}"
            # A redo the studio raised itself says why (2026-10-09, babcf272: a clip too
            # short for its words, `propose_clip_redos`).
            + (f". {redo_note}" if unasked and redo_scene is not None and redo_note else "")
        )
        with Session(engine) as session, session.begin():
            verdict = may_act(
                session,
                actions[step],
                requester=requester,
                subject=storyboard_id,
                evidence=evidence,
                # The cap, the most his yes lets the step spend (MONEY-08, A10): OVER_USD
                # compares his threshold with it; the expected cost stays in the evidence.
                cost_usd=cap_usd,
                context=asked_about,
            )
            if (
                proposal
                and unasked
                and redo_scene is not None
                and verdict["allowed"]
                and not verdict.get("approval_id")
                and owner_approved_among(
                    session, _scene_shot_takes(session, storyboard_id, redo_scene)
                )
            ):
                # His card of 2026-10-10: the studio proposes the redo of a shot he approved
                # himself as his question, even where his rule and mode let it buy unasked.
                verdict = _proposal_asks_him(
                    session,
                    verdict,
                    action=actions[step],
                    requester=requester,
                    subject=storyboard_id,
                    evidence=evidence,
                    cost_usd=cap_usd,
                    context=asked_about,
                    scene_index=redo_scene,
                )
            if verdict["allowed"] and redo_scene is not None:
                # The yes is spent and the old shot retired together: the redo replaces it.
                # A shot the Owner approved himself is retired only by his own press, or his
                # yes for this plan (2026-10-10, babcf272): unasked and without it, this
                # raises and rolls the yes back.
                _retire_takes(
                    session,
                    _scene_shot_takes(session, storyboard_id, redo_scene),
                    REDO_FAILURE_CODE,
                    redo_note or "Proprietarul a cerut refacerea mișcării acestei scene.",
                    correlation_id,
                    redo_kind="motion",
                    owner_press=not unasked
                    or _owner_yes_for_redo(session, storyboard_id, plan_hash, cap, verdict),
                    plan_hash=plan_hash,
                    director_repair=director_repair,
                )
        if not verdict["allowed"]:
            raise MotionStepRefused(
                str(verdict["status"]),
                str(verdict["reason"]),
                approval_id=verdict.get("approval_id"),
                plan=plan,
            )
        # The same question again before every shot and retry, never spending (spec 51).
        guard = PurchaseGuard.after(
            engine,
            verdict,
            action=actions[step],
            step=step,
            storyboard_id=storyboard_id,
            requester=requester,
            cost_usd=cap_usd,
            context=asked_about,
            unasked=unasked,
            correlation_id=correlation_id,
            timezone=timezone,
        )
        work_dir.mkdir(parents=True, exist_ok=True)

    scene_dicts = {int(scene["scene_index"]): scene for scene in state["scenes"]}
    base_seed = int(plan["seed"])
    # Each scene's round is bought on its own seed: the film's, moved past the clips the scene
    # already had (`_scene_seed`), so the same words bought again make a different clip.
    made_before = _shots_made(engine, storyboard_id, to_buy)
    seed = base_seed
    results: list[dict[str, Any]] = []
    charged: list[dict[str, Any]] = []
    bought_now: list[int] = []
    stopped: str | None = None
    previous_kind: str | None = None
    # Where the balance stopped the step, if it did (`balance_rule.low_balance_record`).
    low_balance: dict[str, Any] | None = None
    # Paid requests per scene since the Owner last decided about it (scene_memory), this
    # step's included: past the limit nothing more is bought for the scene without him. A redo
    # is his own act and is not counted against it.
    limit = max_paid_attempts_per_scene()
    sent: dict[int, int] = {}
    # Every shot take the scenes to buy had when the plan was read: one that appears later and
    # is not this step's was bought by someone else, and the scene is not bought again.
    known_shots = _shot_take_ids(engine, storyboard_id, to_buy)
    # RunPod Serverless buys the step's shots in rounds of batches inside one GPU session
    # (`media.gpu_batch`): its scenes are gathered here and bought after the loop.
    from app.providers.runpod.batch import supports_batch  # noqa: PLC0415

    deferred_shots: list[_ShotRound] = []

    def over_attempts(scene_index: int) -> bool:
        return step != REDO_STEP and sent.get(scene_index, 0) >= limit

    def attempts_reason(scene_index: int) -> str:
        from app.wording import count as count_ro  # noqa: PLC0415

        return (
            f"Scena {scene_index}: "
            + count_ro(sent.get(scene_index, 0), "cumpărare plătită", "cumpărări plătite")
            + f" de la ultima decizie a Proprietarului, fără un cadru acceptat (limita este "
            f"{limit}); nu se mai cumpără nimic pentru ea până nu decide el pe foaia de filmare."
        )

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
        seed = _scene_seed(base_seed, made_before.get(index, 0))
        if supports_batch(adapter):
            prompt_words, extra_words = motion_request(adapter, scene_dicts[index], from_still=True)
            remembered_shot = state["memory"].get(index)
            sent[index] = remembered_shot.attempts if remembered_shot is not None else 0
            deferred_shots.append(
                _ShotRound(
                    index=index,
                    entry=entry,
                    adapter=adapter,
                    model_id=model_id,
                    price=price,
                    seconds=seconds,
                    identity=identity,
                    still=still_take,
                    first_frame=_first_frame(str(ffmpeg_exe), Path(str(still_take.path)), seconds),
                    prompt=prompt_words,
                    negative=extra_words.get("negative_prompt"),
                    seed=seed,
                    committed_before=meter.committed,
                    hold_identity=identity_key(state["fields"][index]),
                )
            )
            continue
        attempts = 0
        outcome: dict[str, Any] | None = None
        bought_clip: Path | None = None
        # The scene's paid attempts since the Owner last decided about it, and what this step
        # has spent before it: what its NEEDS_OWNER event, and the attempt limit, are read on.
        remembered_here = state["memory"].get(index)
        sent[index] = remembered_here.attempts if remembered_here is not None else 0
        committed_before_scene = meter.committed
        # The clip-QC retry this scene could not buy on the balance, if any.
        retry_short: dict[str, Any] = {}

        def buy_retry(
            new_seed: int,
            new_prompt: str,
            *,
            _index: int = index,
            _adapter: Any = adapter,
            _model: str = model_id,
            _price: int = price,
            _seconds: int = seconds,
            _still: SceneTake = still_take,
            _identity: str = identity,
            _short: dict[str, Any] = retry_short,
        ) -> tuple[Path | None, str | None]:
            """Clip QC's one retry of this scene: the same model and still, seed + 1, the
            camera move asked more firmly; bought like any shot (balance, stop, take)."""
            nonlocal stopped, low_balance
            if stop_requested(engine):
                stopped = motion_stop_reason(engine)
                return None, None
            lowered = guard.stop_reason(_index) if guard is not None else None
            if lowered is not None:
                stopped = lowered
                return None, None
            if over_attempts(_index):
                return None, None
            _read, balance, problem = _account_balance(source)
            if problem is not None:
                stopped = f"Nu se mai cumpără mișcare: {problem}."
                return None, None
            if balance is not None and balance < needed_credits(_price, margin):
                # The Owner's rule (2026-10-03): the retry is a purchase like any other.
                stopped = purchase_stop_ro(
                    _index, balance, _price, margin, "reluarea cadrului după controlul clipului"
                )
                low_balance = low_balance_record(_index, balance, _price, margin, stopped)
                _short.update(low_balance)
                return None, None
            drop = uncounted_drop(before, balance, meter.committed)
            if drop is not None:
                stopped = UNCOUNTED_DROP_STOP.format(drop=drop, committed=meter.committed)
                return None, None
            posted: list[str] = []
            intents: list[str | None] = []
            meter.attempts += 1
            sent[_index] = sent.get(_index, 0) + 1

            def submitted(task_id: str) -> None:
                posted.append(task_id)
                intents.append(
                    _record_intent(
                        engine,
                        task_id,
                        storyboard_id=storyboard_id,
                        scene_number=_index,
                        kind=take_kind,
                        prompt_hash=_identity,
                        model_id=_model,
                        resolution=MOTION_RESOLUTION,
                        correlation_id=correlation_id,
                        credits=max(float(_price), float(_quoted_credits(_adapter) or 0.0)),
                        seconds=float(_seconds),
                        seed=new_seed,
                    )
                )

            try:
                with _at_work(
                    engine, "VideoEditor", "generate_motion", f"reluarea scenei {_index}"
                ):
                    bind_scene(_adapter, storyboard_id, _index, "video")
                    retry_bytes, _raw = _generate_motion(
                        _adapter,
                        scene_dicts[_index],
                        Path(str(_still.path)),
                        float(_seconds),
                        str(ffmpeg_exe),
                        seed=new_seed,
                        on_submitted=submitted,
                        prompt_text=new_prompt,
                    )
            except TaskStillOpen:
                # Paid and accepted; its clip did not arrive. It stays SUBMITTED, collected
                # later; nothing more is bought in this step.
                open_spend = max(float(_price), float(_quoted_credits(_adapter) or 0.0))
                meter.committed += open_spend
                if intents and intents[-1]:
                    charged.append(
                        {
                            "take_id": intents[-1],
                            "model": _model,
                            "seconds": _seconds,
                            "spend": open_spend,
                        }
                    )
                stopped = IN_FLIGHT_STOP.format(scene=_index)
                return None, None
            except (MediaProviderError, MediaProviderNotConfigured, ValueError, OSError) as exc:
                lost: float | None = None
                unanswered = outcome_unknown(exc, submitted=bool(posted))
                if posted or unanswered:
                    # A task the vendor accepted, or a request it may have served without an
                    # answer, may be charged like a success: counted, never sent again here.
                    lost = max(float(_price), float(_quoted_credits(_adapter) or 0.0))
                    meter.committed += lost
                if unanswered:
                    stopped = UNANSWERED_REASON.format(scene=_index)
                lost_take = record_take(
                    engine,
                    take_id=intents[-1] if intents else None,
                    storyboard_id=storyboard_id,
                    scene_number=_index,
                    kind=take_kind,
                    prompt_hash=_identity,
                    model_id=_model,
                    resolution=MOTION_RESOLUTION,
                    status="REFUSED",
                    correlation_id=correlation_id,
                    seconds=float(_seconds),
                    seed=new_seed,
                    credits_quoted=lost,
                    failure_code=failure_code_of(exc)
                    or (UNANSWERED_FAILURE_CODE if unanswered else "TECHNICAL"),
                    failure_detail=failure_detail_of(exc),
                )
                if lost is not None:
                    charged.append(
                        {"take_id": lost_take, "model": _model, "seconds": _seconds, "spend": lost}
                    )
                return None, None
            paid = max(float(_price), float(_quoted_credits(_adapter) or 0.0))
            meter.committed += paid
            retry_clip = work_dir / f"{take_kind}_{_index:02d}_{uuid4().hex[:8]}.mp4"
            retry_clip.write_bytes(retry_bytes)
            retry_take = record_take(
                engine,
                take_id=intents[-1] if intents else None,
                storyboard_id=storyboard_id,
                scene_number=_index,
                kind=take_kind,
                prompt_hash=_identity,
                model_id=_model,
                resolution=MOTION_RESOLUTION,
                status="PAID",
                correlation_id=correlation_id,
                seconds=float(_seconds),
                seed=new_seed,
                credits_quoted=paid,
                path=retry_clip,
                sha256=_file_sha256(retry_clip),
            )
            charged.append(
                {"take_id": retry_take, "model": _model, "seconds": _seconds, "spend": paid}
            )
            return retry_clip, retry_take

        while outcome is None:
            if stop_requested(engine):
                stopped = motion_stop_reason(engine)
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            lowered = guard.stop_reason(index) if guard is not None else None
            if lowered is not None:
                # His mode or rule changed while the step ran: nothing more is bought.
                stopped = lowered
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            if over_attempts(index):
                outcome = {"status": "NEEDS_OWNER", "reason": attempts_reason(index)}
                break
            if price > room(price) + 1e-9:
                stopped = budget_words(float(price)) or (
                    f"STOPPED_AT_CAP: cadrul scenei {index} ({price} credite) ar depăși "
                    f"plafonul aprobat de {cap} credite (deja {meter.committed:.0f})."
                )
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            _read, balance, problem = _account_balance(source)
            if problem is not None:
                stopped = f"Nu se mai cumpără mișcare: {problem}."
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            if balance is not None and balance < needed_credits(price, margin):
                # The Owner's rule (2026-10-03): this shot is not bought on a balance that
                # cannot hold it with the margin. The scene waits for his top-up; what the step
                # bought is kept and nothing more is bought in it.
                stopped = purchase_stop_ro(
                    index,
                    balance,
                    price,
                    margin,
                    "cadrul" if attempts == 0 else "o nouă încercare a cadrului",
                )
                low_balance = low_balance_record(index, balance, price, margin, stopped)
                entry["failure_kind"] = LOW_BALANCE
                outcome = {"status": "NEEDS_OWNER", "reason": stopped}
                break
            drop = uncounted_drop(before, balance, meter.committed)
            if drop is not None:
                # The account lost more than this step counted: a charge it does not know
                # about (an answer lost on the way, another buyer). Nothing more is bought.
                stopped = UNCOUNTED_DROP_STOP.format(drop=drop, committed=meter.committed)
                outcome = {"status": "NOT_BOUGHT", "reason": stopped}
                break
            if attempts == 0 and _bought_elsewhere(
                engine, storyboard_id, index, identity, known_shots.get(index, set())
            ):
                # Another buyer (a second press, the day's staircase) bought this scene since
                # the step read its plan: the purchase lease keeps that from happening, and
                # this is the check behind it (MONEY-04). Never bought twice.
                outcome = {
                    "status": "BOUGHT_ELSEWHERE",
                    "reason": f"Scena {index} a fost cumpărată între timp de altă rulare; "
                    "nu se cumpără a doua oară.",
                }
                break
            attempts += 1
            meter.attempts += 1
            sent[index] = sent.get(index, 0) + 1
            posted: list[str] = []
            intents: list[str | None] = []

            def submitted(
                task_id: str,
                *,
                _index: int = index,
                _adapter: Any = adapter,
                _model: str = model_id,
                _price: int = price,
                _seconds: int = seconds,
                _identity: str = identity,
                _posted: list[str] = posted,
                _intents: list[str | None] = intents,
                _seed: int = seed,
            ) -> None:
                _posted.append(task_id)
                _intents.append(
                    _record_intent(
                        engine,
                        task_id,
                        storyboard_id=storyboard_id,
                        scene_number=_index,
                        kind=take_kind,
                        prompt_hash=_identity,
                        model_id=_model,
                        resolution=MOTION_RESOLUTION,
                        correlation_id=correlation_id,
                        credits=max(float(_price), float(_quoted_credits(_adapter) or 0.0)),
                        seconds=float(_seconds),
                        seed=_seed,
                    )
                )

            try:
                with _at_work(engine, "VideoEditor", "generate_motion", f"mișcarea scenei {index}"):
                    bind_scene(adapter, storyboard_id, index, "video")
                    clip_bytes, _raw = _generate_motion(
                        adapter,
                        scene_dicts[index],
                        Path(str(still_take.path)),
                        float(seconds),
                        str(ffmpeg_exe),
                        seed=seed,
                        on_submitted=submitted,
                    )
            except TaskStillOpen:
                # The vendor accepted the shot (it may bill it) and its clip did not arrive.
                # The take stays SUBMITTED with the task id: collected later, never bought
                # again. The step stops: a vendor that does not hand over what it sold is not
                # sold anything more today.
                in_flight_spend = max(float(price), float(_quoted_credits(adapter) or 0.0))
                meter.committed += in_flight_spend
                take_id = intents[-1] if intents else None
                if take_id is None:
                    take_id = _record_intent(
                        engine,
                        posted[-1] if posted else "",
                        storyboard_id=storyboard_id,
                        scene_number=index,
                        kind=take_kind,
                        prompt_hash=identity,
                        model_id=model_id,
                        resolution=MOTION_RESOLUTION,
                        correlation_id=correlation_id,
                        credits=in_flight_spend,
                        seconds=float(seconds),
                        seed=seed,
                    )
                if take_id is not None:
                    charged.append(
                        {
                            "take_id": take_id,
                            "model": model_id,
                            "seconds": seconds,
                            "spend": in_flight_spend,
                        }
                    )
                stopped = IN_FLIGHT_STOP.format(scene=index)
                outcome = {
                    "status": "IN_FLIGHT",
                    "take_id": take_id,
                    "credits_quoted": in_flight_spend,
                    "reason": IN_FLIGHT_REASON.format(scene=index),
                }
                break
            except (MediaProviderError, MediaProviderNotConfigured, ValueError, OSError) as exc:
                failure = _shot_failure(exc, previous_kind)
                previous_kind = failure.kind
                spend: float | None = None
                # A request that left and got no answer (no task id heard): the vendor may
                # have served it, so it is counted and never sent again automatically.
                unanswered = outcome_unknown(exc, submitted=bool(posted))
                if posted or unanswered:
                    # A task the vendor accepted may be charged like a success.
                    spend = max(float(price), float(_quoted_credits(adapter) or 0.0))
                    meter.committed += spend
                code = failure_code_of(exc) or (
                    UNANSWERED_FAILURE_CODE if unanswered else failure.kind
                )
                detail = failure_detail_of(exc)
                take_id = record_take(
                    engine,
                    take_id=intents[-1] if intents else None,
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
                if unanswered:
                    entry.update(
                        failure_kind="UNANSWERED",
                        failure_code=code,
                        failure_detail=detail,
                        take_id=take_id,
                    )
                    reason = UNANSWERED_REASON.format(scene=index)
                    # A vendor whose answers are being lost is sold nothing more in this step.
                    stopped = reason
                    outcome = {"status": "NEEDS_OWNER", "reason": reason}
                    break
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
                if failure.kind == STUDIO_DEFECT_KIND:
                    # Our request was wrong (the vendor names the parameter): the scene is not
                    # held for the Owner and its model stays; the next request would carry the
                    # same defect, so nothing more is sent in this step.
                    stopped = failure.reason_ro + (f" Furnizorul: «{detail}»." if detail else "")
                    outcome = {"status": "NOT_BOUGHT", "reason": f"Scena {index}: {stopped}"}
                    break
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
            meter.committed += spend
            clip = work_dir / f"{take_kind}_{index:02d}_{uuid4().hex[:8]}.mp4"
            clip.write_bytes(clip_bytes)
            take_id = record_take(
                engine,
                take_id=intents[-1] if intents else None,
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
            bought_clip = clip
            outcome = {"status": "PAID", "take_id": take_id, "credits_quoted": spend}
        if outcome["status"] == "PAID" and bought_clip is not None:
            # No shot goes on unchecked: clip QC now, with its one retry inside the cap.
            first_spend = meter.committed
            checked = _check_shot(
                engine,
                storyboard_id=storyboard_id,
                correlation_id=correlation_id,
                scene=scene_dicts[index],
                clip=bought_clip,
                take_id=str(outcome["take_id"]),
                seed=seed,
                model_id=model_id,
                adapter=adapter,
                price=float(price),
                committed=meter.committed,
                # Its one retry, inside the cap and what the budget hold covers once grown for
                # it (`StepHold`): a retry the budget cannot hold is not bought.
                cap=meter.committed + room(float(price)),
                environment=environment,
                bible=state["bible"],
                ffmpeg_exe=ffmpeg_exe,
                buy=buy_retry,
                registry=registry,
                clip_judge=clip_judge,
                face_counter=face_counter,
                clip_check=clip_check,
            )
            entry["clip_qc"] = checked["clip_qc"]
            outcome = {
                **outcome,
                "status": checked["status"],
                "take_id": checked["take_id"],
                "credits_quoted": round(
                    float(outcome["credits_quoted"]) + meter.committed - first_spend, 4
                ),
            }
            if checked["reason"]:
                outcome["reason"] = checked["reason"]
            if retry_short and checked["status"] != "PAID":
                # Its retry was not bought on the balance: the scene waits for his top-up.
                entry["failure_kind"] = LOW_BALANCE
                outcome["reason"] = f"{outcome.get('reason') or ''} {retry_short['reason_ro']}"
                outcome["reason"] = outcome["reason"].strip()
            if checked["status"] != "PAID" and index in bought_now:
                bought_now.remove(index)
            if checked["cap_stop"] and stopped is None:
                stopped = budget_words(float(price)) or checked["cap_stop"]
        entry.update(outcome)
        entry["attempts"] = attempts
        if outcome["status"] in ("NEEDS_OWNER", "NEEDS_STILL"):
            # Whether the scene is held for the Owner (scene_memory): yes, unless what went
            # wrong cost nothing and was the vendor's or the account's (no credits, a 503), or
            # the balance stopped it (his top-up is the decision, 2026-10-03).
            free = entry.get("failure_kind") == LOW_BALANCE or (
                str(entry.get("failure_kind") or "") in FREE_FAILURE_KINDS
                and meter.committed <= committed_before_scene
            )
            _storyboard_event(
                engine,
                MOTION_HOLD_EVENT,
                storyboard_id,
                {
                    "severity": "WARNING",
                    "scene_number": index,
                    "status": outcome["status"],
                    "reason": outcome["reason"],
                    "failure_kind": entry.get("failure_kind"),
                    "suggested": entry.get("suggested"),
                    "clip_qc": (entry.get("clip_qc") or {}).get("verdict"),
                    "identity": identity_key(state["fields"][index]),
                    "holds": not free,
                },
                correlation_id,
            )

    gpu: dict[str, Any] | None = None
    if deferred_shots:
        from app.providers.runpod.gpu_session import StepPermit  # noqa: PLC0415

        rounds = _ShotRounds(
            engine,
            storyboard_id=storyboard_id,
            correlation_id=correlation_id,
            take_kind=take_kind,
            meter=meter,
            cap=float(cap),
            overhead=float(prices.round_overhead("video", deferred_shots[0].model_id)),
            credit_usd=float(prices.credit_usd),
            work_dir=work_dir,
            environment=environment,
            bible=state["bible"],
            ffmpeg_exe=ffmpeg_exe,
            registry=registry,
            clip_judge=clip_judge,
            face_counter=face_counter,
            clip_check=clip_check,
            charged=charged,
            bought_now=bought_now,
            over_attempts=over_attempts,
            attempts_reason=attempts_reason,
            sent=sent,
            scene_dicts=scene_dicts,
            room=room if budget_hold is not None else None,
            budget_words=budget_words,
        )
        try:
            gpu = yield from flow_call(
                rounds.run,
                deferred_shots,
                permit=StepPermit.from_guard(
                    guard,
                    verdict,
                    action=actions[step],
                    step=step,
                    storyboard_id=storyboard_id,
                    plan_hash=plan_hash,
                    requester=requester,
                    correlation_id=correlation_id,
                    integration_id=integration_id,
                    unasked=unasked,
                ),
                guard=guard,
                stopped=lambda: motion_stop_reason(engine) if stop_requested(engine) else None,
            )
        except MediaProviderError as exc:
            if not exc.unsent:
                raise
            # The GPU was not switched on, or the round could not be sent: nothing bought.
            raise MotionStepRefused(
                str(exc.code or "COMPUTE_NOT_READY"),
                str(getattr(exc, "reason_ro", None) or exc),
                plan=plan,
            ) from exc
        stopped = stopped or gpu.get("stopped")

    after: float | None = None
    measured: float | None = None
    if to_buy and read:
        _read, after, _problem = _account_balance(source)
        if before is not None and after is not None and before - after > 0:
            measured = before - after
    if measured is not None and charged:
        total = sum(item["spend"] for item in charged) or 1.0
        with Session(engine) as session, session.begin():
            # Read-then-write after a purchase: the write lock first (app.db.lock_for_write).
            lock_for_write(session)
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
        "seed": base_seed,
        "resolution": resolution,
        "scenes": results,
        "bought_shots": len(bought_now),
        "spent_credits_quoted": round(meter.committed, 4),
        "spent_credits_measured": measured,
        "balance_before": before,
        "balance_after": after,
        "cap_credits": cap,
        "stopped": stopped,
        # The Owner's mode or rule changed while the step ran (`mode_guard`), or None.
        "mode_stopped": guard.stopped if guard is not None else None,
        # The scene the balance stopped, the balance read and what was needed (or None).
        "low_balance": low_balance,
        "needs_owner": [e["scene_index"] for e in results if e.get("status") == "NEEDS_OWNER"],
        "needs_still": [e["scene_index"] for e in results if e.get("status") == "NEEDS_STILL"],
        # Paid tasks still open at the vendor (collected later, never bought again), the
        # ones collected before this step planned anything, and the shots checked then.
        "in_flight": [e["scene_index"] for e in results if e.get("status") == "IN_FLIGHT"],
        "collected": collected,
        "rechecked": rechecked,
        # The hero test shot accepted by its clip QC in this step, under the Owner's rule
        # (HERO_ACCEPTED_EVENT's payload), or None.
        "hero_accepted": hero_accepted,
        # Clip QC: the scenes whose every shot was measured wrong (rejected, the Owner
        # decides), and those whose shot nobody could check (it waits for his look).
        "clip_qc_failed": [
            e["scene_index"] for e in results if (e.get("clip_qc") or {}).get("verdict") == "FAILED"
        ],
        "clip_unchecked": [
            e["scene_index"]
            for e in results
            if (e.get("clip_qc") or {}).get("verdict") == "UNCHECKED"
        ],
        "credit_usd": prices.credit_usd,
        # RunPod Serverless: the rounds, the GPU session's jobs and the billed estimate.
        "gpu": gpu,
    }
    _storyboard_event(engine, "media.motion_step_finished", storyboard_id, summary, correlation_id)
    return summary


# ------------------------------------------------------------- the film's intermediates
#
# 2026-10-01 (DISK_AND_BREATHS): every render kept its shot intermediates for ever, about
# 1.1 GB a film while they were lossless, and the test suite had left 321 GB of films in the
# studio's media folder. A shot and a card clip exist to be joined into the film and read once
# by quality control (qc.shot_duplicate_share). Once the film's QC report is recorded they are
# deleted; the vendor takes, the stills, the film, its captions, its voice and its mastered
# sound stay. A redo or a rejoin cuts the shots it needs again from what they were cut from
# (each shot record's ``source``; _rederive_shot), at 0 credits.

#: The event a film's released intermediates are recorded under, on the film's asset.
INTERMEDIATES_RELEASED_EVENT = "media.intermediates_released"
#: A render still writing into a storyboard's folder: nothing there is released meanwhile.
_RENDERING_STATUSES = ("PENDING", "RENDERING")


def film_intermediates(production: dict[str, Any], folder: Path) -> list[dict[str, Any]]:
    """The intermediates a film's manifest names: each scene's shot (production['shots']) and
    each composed card's clip. ``rederivable`` says whether a redo could cut the file again
    (a shot recorded with its ``source``; a card, from its own spec)."""
    found: list[dict[str, Any]] = []
    for record in production.get("shots") or []:
        if isinstance(record, dict) and record.get("file"):
            found.append(
                {
                    "kind": "shot",
                    "path": folder / Path(str(record["file"])).name,
                    "sha256": record.get("sha256"),
                    "rederivable": isinstance(record.get("source"), dict),
                }
            )
    for entry in production.get("scenes") or []:
        card = entry.get("card") if isinstance(entry, dict) else None
        if isinstance(card, dict) and card.get("path"):
            found.append(
                {
                    "kind": "card",
                    "path": Path(str(card["path"])),
                    "sha256": card.get("sha256"),
                    "rederivable": True,
                }
            )
    return found


def _inside(path: Path, folder: Path) -> str | None:
    """``path`` relative to ``folder`` (posix), or None when it lies outside it."""
    try:
        return path.resolve().relative_to(folder.resolve()).as_posix()
    except (OSError, ValueError):
        return None


def release_intermediates(
    engine: Engine, media_asset_id: str, correlation_id: str
) -> dict[str, Any]:
    """Delete a film's intermediates once its quality-control report is recorded.

    Only files inside the film's own folder, that are still the bytes this film recorded, and
    that a redo could cut again, are deleted. A file another film of the storyboard still
    needs (finished, its QC not recorded yet) stays, and nothing is released while a render of
    the storyboard is still writing. Returns ``status`` (RELEASED, NO_QC_REPORT,
    ALREADY_RELEASED, BUSY or NOT_A_FILM), the ``files`` deleted (relative to the film's
    folder), the ``bytes`` they held and what was ``kept`` and why. A release is recorded
    once, as INTERMEDIATES_RELEASED_EVENT on the film's asset.
    """
    result: dict[str, Any] = {
        "asset_id": media_asset_id,
        "status": "NOT_A_FILM",
        "files": [],
        "bytes": 0,
        "kept": [],
    }
    with Session(engine) as session:
        asset = session.get(MediaAsset, media_asset_id)
        job = session.scalar(
            select(VideoRenderJob)
            .where(VideoRenderJob.output_asset_id == media_asset_id)
            .order_by(VideoRenderJob.started_at.desc())
            .limit(1)
        )
        if asset is None or job is None or job.status != "COMPLETED":
            return result
        if session.scalar(
            select(DomainEvent.event_id)
            .where(
                DomainEvent.event_type == INTERMEDIATES_RELEASED_EVENT,
                DomainEvent.aggregate_id == media_asset_id,
            )
            .limit(1)
        ):
            return {**result, "status": "ALREADY_RELEASED"}
        if not session.scalar(
            select(QualityControlReport.id)
            .where(QualityControlReport.media_asset_id == media_asset_id)
            .limit(1)
        ):
            return {**result, "status": "NO_QC_REPORT"}
        if session.scalar(
            select(VideoRenderJob.id)
            .where(
                VideoRenderJob.storyboard_id == job.storyboard_id,
                VideoRenderJob.status.in_(_RENDERING_STATUSES),
            )
            .limit(1)
        ):
            return {**result, "status": "BUSY"}
        production = copy.deepcopy(job.production_json or {})
        folder = Path(asset.uri_or_path).parent
        # The files a finished film of this storyboard still needs: its QC has not read it.
        needed: set[tuple[str, str]] = set()
        others = session.execute(
            select(VideoRenderJob.production_json, MediaAsset.uri_or_path, MediaAsset.id)
            .join(MediaAsset, MediaAsset.id == VideoRenderJob.output_asset_id)
            .where(
                VideoRenderJob.storyboard_id == job.storyboard_id,
                VideoRenderJob.status == "COMPLETED",
                VideoRenderJob.id != job.id,
            )
        ).all()
        reviewed = set(
            session.scalars(
                select(QualityControlReport.media_asset_id).where(
                    QualityControlReport.media_asset_id.in_([row[2] for row in others])
                )
            )
        )
        for other_production, other_path, other_id in others:
            if other_id in reviewed:
                continue
            for item in film_intermediates(other_production or {}, Path(other_path).parent):
                if item.get("sha256"):
                    needed.add((str(Path(item["path"]).resolve()), str(item["sha256"])))

    released: list[str] = []
    kept: list[dict[str, str]] = []
    freed = 0
    for item in film_intermediates(production, folder):
        path = Path(item["path"])
        name = _inside(path, folder)
        if name is None:
            kept.append({"file": str(path), "reason": "în afara dosarului filmului"})
            continue
        if not path.is_file():
            continue
        if not item["rederivable"]:
            kept.append(
                {
                    "file": name,
                    "reason": "randat înainte ca sursa cadrului să fie păstrată: o refacere "
                    "nu l-ar mai putea reface",
                }
            )
            continue
        digest = _file_sha256(path)
        if item.get("sha256") and digest != item["sha256"]:
            kept.append({"file": name, "reason": "reconstruit între timp de alt film"})
            continue
        if (str(path.resolve()), digest) in needed:
            kept.append(
                {
                    "file": name,
                    "reason": "îl folosește un film mai nou, încă necitit de controlul calității",
                }
            )
            continue
        size = path.stat().st_size
        try:
            path.unlink()
        except OSError as exc:
            kept.append({"file": name, "reason": f"nu a putut fi șters ({exc.strerror})"})
            continue
        released.append(name)
        freed += size
    # A card redo's own folder is left empty once its card clip is gone.
    for work in folder.glob("redo_*"):
        if work.is_dir() and not any(work.iterdir()):
            work.rmdir()
    with Session(engine) as session, session.begin():
        append_event(
            session,
            INTERMEDIATES_RELEASED_EVENT,
            "media_asset",
            media_asset_id,
            1,
            {"files": released, "bytes": freed, "kept": kept},
            correlation_id,
        )
    return {**result, "status": "RELEASED", "files": released, "bytes": freed, "kept": kept}


def release_reviewed_intermediates(engine: Engine, correlation_id: str) -> list[dict[str, Any]]:
    """Release the intermediates of every finished film whose QC report is recorded and whose
    release is not: what each render does first, and what a caller of quality control may do
    the moment the report is written. Returns the releases made."""
    with Session(engine) as session:
        done = set(
            session.scalars(
                select(DomainEvent.aggregate_id).where(
                    DomainEvent.event_type == INTERMEDIATES_RELEASED_EVENT
                )
            )
        )
        reviewed = set(
            session.scalars(
                select(QualityControlReport.media_asset_id)
                .join(
                    VideoRenderJob,
                    VideoRenderJob.output_asset_id == QualityControlReport.media_asset_id,
                )
                .where(VideoRenderJob.status == "COMPLETED")
            )
        )
    releases: list[dict[str, Any]] = []
    for asset_id in sorted(reviewed - done):
        outcome = release_intermediates(engine, asset_id, correlation_id)
        if outcome["status"] == "RELEASED":
            releases.append(outcome)
    return releases


def release_after_qc(engine: Engine, media_asset_id: str, correlation_id: str) -> dict[str, Any]:
    """`release_intermediates` the moment a production film's QC report is recorded.

    Called where a film ends (the sheet's assemble step, the daily stage, the render route),
    so about a gigabyte of shots does not wait for the next render's sweep. A failed clean-up
    is logged and never changes the film's verdict; the sweep stays as the backstop.
    """
    try:
        return release_intermediates(engine, media_asset_id, correlation_id)
    except Exception:  # noqa: BLE001 - a clean-up never fails the film
        logger.warning("intermediates_release_failed", extra={"asset_id": media_asset_id})
        return {"asset_id": media_asset_id, "status": "FAILED", "files": [], "bytes": 0}


#: The event the watchdog's sweep of a failed render's intermediates is recorded under.
FAILED_INTERMEDIATES_SWEPT_EVENT = "media.failed_intermediates_swept"
#: What the sweep may delete in a film's own folder: a scene's shot (``shot_01.mp4``, a redo's
#: ``shot_02_redo_<stamp>.mp4``) and a composed card's clip. Nothing in a subfolder (the vendor
#: takes in motion/, the stills), never the film, its captions or its sound.
_SWEPT_NAMES = re.compile(r"^(?:shot|card)_\d{2}[A-Za-z0-9_.-]*\.mp4$")


def sweep_failed_intermediates(
    engine: Engine,
    *,
    storage_root: Path | None = None,
    older_than_days: float = 7,
    now: datetime | None = None,
    correlation_id: str = "",
) -> dict[str, Any]:
    """Delete the shot and card intermediates FAILED renders left behind (REL-08).

    A render that fails before quality control never reaches `release_intermediates`, so its
    shots (about 230 MB a film) stayed for ever. A storyboard's folder is swept only when a
    render of it FAILED more than ``older_than_days`` ago, none is still RENDERING or PENDING,
    and every finished film of it has had its intermediates released already (a film whose QC
    has not read it may still need them). Only top-level ``shot_*`` and ``card_*`` clips older
    than the same age are deleted. Returns ``files`` (relative to the media root) and
    ``bytes``; one FAILED_INTERMEDIATES_SWEPT_EVENT per storyboard swept.

    The watchdog calls this only when the Owner turned STUDIO_SWEEP_FAILED_INTERMEDIATES on.
    """
    root = Path(storage_root) if storage_root else DEFAULT_STORAGE_ROOT
    moment = now or datetime.now(UTC)
    cutoff = moment - timedelta(days=older_than_days)
    result: dict[str, Any] = {"status": "SWEPT", "files": [], "bytes": 0, "storyboards": []}
    with Session(engine) as session:
        failed = {
            str(storyboard)
            for storyboard, finished in session.execute(
                select(VideoRenderJob.storyboard_id, VideoRenderJob.finished_at).where(
                    VideoRenderJob.status == "FAILED"
                )
            )
            if (stamp := _stamp(finished)) is not None and stamp < cutoff
        }
        busy = set(
            session.scalars(
                select(VideoRenderJob.storyboard_id).where(
                    VideoRenderJob.status.in_(_RENDERING_STATUSES)
                )
            )
        )
        released = set(
            session.scalars(
                select(DomainEvent.aggregate_id).where(
                    DomainEvent.event_type == INTERMEDIATES_RELEASED_EVENT
                )
            )
        )
        unreleased = {
            str(storyboard)
            for storyboard, asset_id in session.execute(
                select(VideoRenderJob.storyboard_id, VideoRenderJob.output_asset_id).where(
                    VideoRenderJob.status == "COMPLETED"
                )
            )
            if asset_id and asset_id not in released
        }
    for storyboard_id in sorted(failed - busy - unreleased):
        folder = root / storyboard_id
        if not folder.is_dir():
            continue
        removed: list[str] = []
        freed = 0
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.is_symlink() or not _SWEPT_NAMES.match(path.name):
                continue
            try:
                info = path.stat()
                if datetime.fromtimestamp(info.st_mtime, UTC) >= cutoff:
                    continue
                path.unlink()
            except OSError:
                logger.warning("failed_intermediate_not_swept", extra={"file": str(path)})
                continue
            removed.append(f"{storyboard_id}/{path.name}")
            freed += int(info.st_size)
        if not removed:
            continue
        with Session(engine) as session, session.begin():
            append_event(
                session,
                FAILED_INTERMEDIATES_SWEPT_EVENT,
                "storyboard",
                storyboard_id,
                1,
                {"files": removed, "bytes": freed, "older_than_days": older_than_days},
                correlation_id or str(uuid4()),
            )
        result["files"].extend(removed)
        result["bytes"] += freed
        result["storyboards"].append(storyboard_id)
    return result


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


# ------------------------------------ the Owner's approved takes are never retired unasked
#
# 2026-10-10 (film babcf272, «The Particle That Shouldn't Exist (But Does)»): the studio
# assembled the film from takes the Owner had approved (scenes 1-4; scene 2 his approved test
# shot); the film-level QC failed it, partly on the studio's own burned-in subtitles; and the
# day's QC repair (`runbook.stages._apply_repairs`) redid scenes 1 and 2 by itself. Under his
# OVER_USD 5 rule nothing asked him, so `_retire_takes` retired his approved still and clip of
# scene 1 and his still and test shot of scene 2, the rewrite put new words on both scenes,
# RunPod GPU sessions opened, he forced the GPU off, every new candidate ended REFUSED, and
# both scenes were left with nothing to assemble. The Owner: nobody ever retires a still or
# clip he approved himself; the studio repairs its own mistakes, not his choices. So:
#
# - a redo nobody pressed (``unasked``: the QC repair) that would retire a take whose newest
#   decision is his APPROVED is refused before anything is asked, bought or written
#   (OWNER_APPROVED, `redo_scene`), and `_retire_takes` refuses it again in the transaction
#   that would spend the yes, for any path that reaches it. His own press of «Refă imaginea» /
#   «Refă mișcarea» on the sheet is his decision and retires them as before, and so is his yes
#   to the studio's question for that very plan (`_owner_yes_for_redo`). A clip too short for
#   its words is that question (``proposal``, `propose_clip_redos`, his card of the same day):
#   asking touches nothing of his, so it is raised even where his rule and mode would let the
#   redo buy unasked, and nothing is retired or bought before his yes (`_proposal_asks_him`);
# - a redo that retired takes and then delivered nothing (every candidate REFUSED, LOST or not
#   sent, the GPU forced off, the step refused or interrupted) gives them back as they were,
#   with the scene's words when the redo had rewritten them (`give_back_retired_takes`); the
#   watchdog gives back, once, what redos that ended before this code left
#   (`app.workflows.passes.restore_retired_takes`).
#
# Review of the same day: "delivered" is read from the takes' history, never from what they
# are now. A candidate the stills gate or the clip QC turned down is on disk and waits for his
# look (NEEDS_OWNER, «Decide Proprietarul»; `decide_take` lets him choose it): giving the old
# takes back beside it, with the old words, left his pick matching nothing, and brought the
# Director's retired defect (babcf272's three-panel scene 5) back into the next assembly. A
# new still the Owner turns down days after his own redo delivered it does not bring back the
# one he pressed away either.

#: A redo nobody pressed that would retire a take the Owner himself approved (409).
OWNER_APPROVED = "OWNER_APPROVED"
#: A take a redo retired, and one given back after the redo delivered nothing usable.
TAKE_RETIRED_EVENT = "media.scene_take_retired"
TAKE_RESTORED_EVENT = "media.scene_take_restored"
#: A scene's words put back as they were before a redo that delivered nothing rewrote them;
#: a «media.prompt*» type, as the rewrite's is (the claim checker reads that prefix).
SCENE_PROMPTS_RESTORED_EVENT = "media.prompts_restored"
#: A take made after a retirement in one of these was delivered, or may still be (one
#: SUBMITTED is still at the vendor), and so is a REJECTED one that carries its file (a gate,
#: the clip QC or the Owner turned it down after it came): the retired takes are not given
#: back beside it (`_delivered_since`).
_MAY_STILL_DELIVER: tuple[str, ...] = ("APPROVED", "PAID", "SUBMITTED")
_PICTURE_KINDS: tuple[str, ...] = ("still", *SHOT_TAKE_KINDS)
_TAKE_WORDS_RO = {"still": "imaginea", "test_shot": "cadrul de probă", "motion": "clipul"}


def _owner_stands_by(
    row: SceneTake,
    said: list[dict[str, Any]] | None,
    status: str,
    *,
    final_only: bool = False,
) -> bool:
    """Whether the Owner's own approval stands on a take that is (or was) ``status``: his
    newest look on the sheet is APPROVED (`decide_take`), or the take is APPROVED by him
    (``approved_by`` owner, as an adopted or seeded take records it) and he has not turned
    it down since.

    ``final_only``: whether his approval marked final stands (his newest look APPROVED with
    ``final``, `decide_take`); an approval he did not mark final, or one with no look of his
    on record, does not (2026-10-11: the Director's confirmed repair goes over those)."""
    newest = said[-1] if said else None
    if newest is not None and newest.get("decision") == "REJECTED":
        return False
    if newest is not None and newest.get("decision") == "APPROVED":
        return bool(newest.get("final")) if final_only else True
    if final_only:
        return False
    return status == "APPROVED" and row.approved_by == TAKE_DECIDER


def owner_approved_among(
    session: Session, take_ids: Sequence[str], *, final_only: bool = False
) -> list[str]:
    """The takes among ``take_ids`` that a redo nobody pressed may not retire: still usable
    (APPROVED or PAID) and approved by the Owner himself (`_owner_stands_by`), in the order
    given; with ``final_only``, those he approved as final. Reads only."""
    ids = list(dict.fromkeys(str(take_id) for take_id in take_ids if take_id))
    if not ids:
        return []
    rows = {row.id: row for row in session.scalars(select(SceneTake).where(SceneTake.id.in_(ids)))}
    decisions = owner_take_decisions(session, ids)
    return [
        take_id
        for take_id in ids
        if (row := rows.get(take_id)) is not None
        and row.status in REUSABLE_TAKE_STATUSES
        and _owner_stands_by(row, decisions.get(take_id), row.status, final_only=final_only)
    ]


def _owner_yes_for_redo(
    session: Session,
    storyboard_id: str,
    plan_hash: str | None,
    cap_credits: Any,
    verdict: dict[str, Any] | None = None,
) -> bool:
    """Whether the Owner himself said yes to this redo's plan: the verdict that lets it buy
    spent his answer (an ALLOWED verdict names an approval only when it spent his yes,
    `services._ask_or_spend`), or his APPROVED answer to the question for this plan, its step
    and its cap still stands, read as `may_act` reads it. Reads only.

    His yes to the question the studio raised for a plan (a clip too short for its words,
    `propose_clip_redos`; the day's QC repair, before 2026-10-10) is his decision on that
    scene as his press of «Refă» is (review 2026-10-10): the studio's own re-run of the redo,
    unasked, retires his takes on it instead of being refused OWNER_APPROVED with his yes left
    unspent."""
    if verdict is not None and verdict.get("allowed") and verdict.get("approval_id"):
        return True
    if not plan_hash:
        return False
    from app.services import _answered_approval  # noqa: PLC0415 - the kernel's own reading

    try:
        cap = int(cap_credits) if cap_credits is not None else None
    except (TypeError, ValueError):
        return False
    answered = _answered_approval(
        session,
        REDO_ACTION,
        storyboard_id,
        {"plan_hash": str(plan_hash), "step": REDO_STEP, "cap_credits": cap},
    )
    return answered is not None and answered.result == "APPROVED"


def _proposal_asks_him(
    session: Session,
    verdict: dict[str, Any],
    *,
    action: str,
    requester: str,
    subject: str,
    evidence: str,
    cost_usd: float,
    context: dict[str, Any],
    scene_index: int,
) -> dict[str, Any]:
    """The kernel's unasked ALLOWED for a redo the studio proposes of a shot the Owner
    approved himself, made his question (his card of 2026-10-10): his standing answer for this
    plan and cap is read as his paid-media rule reads it (`services._ask_or_spend`: a no
    stands, a yes is spent), else the question his rule would raise is raised, bound to the
    same plan and cap, so a later yes is the one `_owner_yes_for_redo` reads. Only after the
    kernel's stop, safe mode, T4 and budget let the step through. Writes in the caller's
    transaction."""
    from app.services import _ask_or_spend, _paid_media_context  # noqa: PLC0415 - the kernel's

    status, reason, approval_id = _ask_or_spend(
        session,
        action,
        str(verdict["tier"]),
        requester=requester,
        subject=subject,
        evidence=evidence,
        cost_usd=cost_usd,
        context=_paid_media_context(REDO_STEP, context),
        ask_owner=True,
        waiting=(
            f"Scena {scene_index}: Proprietarul a aprobat el însuși clipul; studioul propune "
            "refacerea lui, dar nu o cumpără și nu retrage nimic fără acordul lui. Întrebarea "
            "așteaptă răspunsul lui pe foaia de filmare."
        ),
    )
    return {
        **verdict,
        "allowed": status == "ALLOWED",
        "status": status,
        "reason": reason,
        "approval_id": approval_id,
    }


def _owner_choice_stands_ro(
    session: Session, take_ids: Sequence[str], redo_kind: str, *, final: bool = False
) -> str:
    """The Owner's line when a redo nobody pressed would retire what he approved himself
    (``final``: what he approved as final, which the Director's confirmed repair spares)."""
    rows = list(session.scalars(select(SceneTake).where(SceneTake.id.in_(list(take_ids)))))
    kinds = {row.kind for row in rows}
    scenes = sorted({int(row.scene_number) for row in rows})
    named = [_TAKE_WORDS_RO[kind] for kind in ("still", "test_shot", "motion") if kind in kinds]
    what = (
        " și ".join(named) if len(named) < 3 else f"{named[0]}, {named[1]} și {named[2]}"
    ) or "înregistrările"
    press = "«Refă imaginea»" if redo_kind == "still" else "«Refă mișcarea»"
    where = ", ".join(map(str, scenes)) or "?"
    if final:
        return (
            f"Scena {where}: Proprietarul a aprobat el însuși {what} ca finală; alegerea lui "
            "rămâne. Nici refacerea hotărâtă de Directoare nu retrage o aprobare finală, așa "
            f"că nu se cumpără și nu se schimbă nimic. Dacă vrea altceva, apasă el {press} pe "
            "foaia de filmare."
        )
    return (
        f"Scena {where}: Proprietarul a aprobat el însuși {what}; alegerea lui rămâne. O "
        "refacere pe care nu a cerut-o el nu retrage ce a aprobat, așa că nu se cumpără și nu "
        f"se schimbă nimic. Dacă vrea altceva, apasă el {press} pe foaia de filmare."
    )


def _retire_takes(
    session: Session,
    take_ids: list[str],
    code: str,
    detail: str,
    correlation_id: str,
    *,
    redo_kind: str,
    owner_press: bool = False,
    plan_hash: str | None = None,
    director_repair: bool = False,
) -> list[str]:
    """REJECTED with the reason, inside the caller's transaction: never used in a film again
    (unless the redo delivers nothing, `give_back_retired_takes`).

    Unless ``owner_press`` (his own «Refă» on the sheet, or his yes for this plan,
    `_owner_yes_for_redo`), a take the Owner approved himself is never retired:
    `SceneRedoRefused` (OWNER_APPROVED) is raised before anything is written, and the
    caller's transaction, his spent yes included, is rolled back (2026-10-10, film
    babcf272). ``director_repair`` (the Director's repair of a defect quality control
    measured and she confirmed, `runbook.stages._apply_repairs`) retires what he approved
    unless he marked the approval final (2026-10-11, his card: «Directoarea poate reface și
    ce am aprobat eu»; «Aprobarea ta rămâne finală doar dacă o marchezi»): only a final
    approval refuses it. ``redo_kind`` (still | motion) names the press he would use instead.
    Each retirement's event keeps what the take was (status, failure, approver), so it can
    be given back exactly."""
    standing = (
        [] if owner_press else owner_approved_among(session, take_ids, final_only=director_repair)
    )
    if standing:
        raise SceneRedoRefused(
            OWNER_APPROVED,
            _owner_choice_stands_ro(session, standing, redo_kind, final=director_repair),
        )
    retired: list[str] = []
    for take_id in take_ids:
        row = session.get(SceneTake, take_id)
        if row is None or row.status not in REUSABLE_TAKE_STATUSES:
            continue
        previous = {
            "previous_status": row.status,
            "previous_failure_code": row.failure_code,
            "previous_failure_detail": row.failure_detail,
            "previous_approved_by": row.approved_by,
        }
        row.status = "REJECTED"
        row.failure_code = code
        row.failure_detail = detail[:TAKE_DETAIL_MAX]
        row.updated_at = utc_now()
        sync_take_quality(session, row)
        append_event(
            session,
            TAKE_RETIRED_EVENT,
            "scene_take",
            row.id,
            1,
            {
                "storyboard_id": row.storyboard_id,
                "scene_number": row.scene_number,
                "kind": row.kind,
                **previous,
                "failure_code": code,
                "owner_press": bool(owner_press),
                "director_repair": bool(director_repair),
                "plan_hash": plan_hash,
            },
            correlation_id,
        )
        retired.append(row.id)
    return retired


def _given_back_ids(
    session: Session, event_type: str, key: str, aggregate_ids: Sequence[str]
) -> set[str]:
    """The ids (``payload[key]``) already given back by events of ``event_type`` on these
    aggregates."""
    found: set[str] = set()
    for event in session.scalars(
        select(DomainEvent).where(
            DomainEvent.event_type == event_type,
            DomainEvent.aggregate_id.in_(list(dict.fromkeys(aggregate_ids))),
        )
    ):
        value = (event.payload or {}).get(key)
        if value:
            found.add(str(value))
    return found


def _unreturned_retirements(
    session: Session,
    storyboard_id: str,
    scene_index: int,
    correlation_id: str,
    after_sequence: int | None,
) -> list[DomainEvent]:
    """One redo's retirements of this scene's takes (its correlation, after the mark) that
    were not given back yet, oldest first."""
    query = select(DomainEvent).where(
        DomainEvent.event_type == TAKE_RETIRED_EVENT,
        DomainEvent.correlation_id == correlation_id,
    )
    if after_sequence is not None:
        query = query.where(DomainEvent.sequence > after_sequence)
    events = [
        event
        for event in session.scalars(query.order_by(DomainEvent.sequence))
        if (event.payload or {}).get("storyboard_id") == storyboard_id
        and _as_int((event.payload or {}).get("scene_number")) == scene_index
    ]
    if not events:
        return []
    returned = _given_back_ids(
        session, TAKE_RESTORED_EVENT, "retired_event_id", [str(e.aggregate_id) for e in events]
    )
    return [event for event in events if event.event_id not in returned]


def _unreturned_rewrite(
    session: Session,
    storyboard_id: str,
    scene_index: int,
    correlation_id: str,
    *,
    before: int,
    after: int | None,
) -> DomainEvent | None:
    """The rewrite of this scene's words by the same redo (written in the transaction that
    retired its takes, just before them), unless its words were given back already."""
    query = select(DomainEvent).where(
        DomainEvent.event_type == SCENE_PROMPTS_REWRITTEN_EVENT,
        DomainEvent.aggregate_id == storyboard_id,
        DomainEvent.correlation_id == correlation_id,
        DomainEvent.sequence < before,
    )
    if after is not None:
        query = query.where(DomainEvent.sequence > after)
    newest = next(
        (
            event
            for event in session.scalars(query.order_by(DomainEvent.sequence.desc()))
            if _as_int((event.payload or {}).get("scene_index")) == scene_index
        ),
        None,
    )
    if newest is None:
        return None
    restored = _given_back_ids(
        session, SCENE_PROMPTS_RESTORED_EVENT, "rewritten_event_id", [storyboard_id]
    )
    return None if newest.event_id in restored else newest


def _delivered_since(
    session: Session,
    storyboard_id: str,
    scene_index: int,
    since: str,
    retired: Sequence[str],
    *,
    until: str | None = None,
) -> bool:
    """Whether a still or shot of the scene made after ``since`` (a retirement) was delivered,
    or may still be: APPROVED, PAID, SUBMITTED (still at the vendor), or REJECTED with its
    file (turned down by a gate, the clip QC or the Owner after it came: the redo delivered,
    whatever became of it). Only takes that never brought a file (REFUSED, LOST, QUOTED:
    refused, expired, never sent) leave the redo with nothing delivered.

    ``until`` closes the window: only takes made before it are this redo's. A paid round is
    read inside its own window (`runbook.stages._paid_redo_rounds`, 2026-10-12: 1c038a99's
    scene 5 had three rounds that delivered nothing — two stopped by a restart, one cancelled
    after a second — and the still of the fourth round «delivered» them all, so his cap of five
    fell on two real redos)."""
    made_before = (SceneTake.created_at < until,) if until else ()
    return (
        session.scalar(
            select(SceneTake.id)
            .where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == scene_index,
                SceneTake.kind.in_(_PICTURE_KINDS),
                or_(
                    SceneTake.status.in_(_MAY_STILL_DELIVER),
                    and_(SceneTake.status == "REJECTED", SceneTake.sha256.is_not(None)),
                ),
                SceneTake.created_at > since,
                *made_before,
                SceneTake.id.not_in(list(retired)),
            )
            .limit(1)
        )
        is not None
    )


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _words_of(value: Any) -> str:
    return " ".join(str(value or "").split())


#: What a rewrite (`_scene_prompt_rewrite`) writes into a scene's package besides its two
#: prompts: everything `prompt_agent.compile_prompts` returns, and the shot type it adds. An
#: event from before 2026-10-10 did not keep their values before the rewrite.
_REWRITE_COMPILED_KEYS: tuple[str, ...] = (
    "scene_kind",
    "shot_type",
    "negative_prompt",
    "look_block",
    "camera_move",
    "shot_size",
    "motion_family",
    "motion_intent",
)


def _package_before_rewrite(
    payload: dict[str, Any], current: dict[str, Any], visual: str | None
) -> tuple[dict[str, Any], str, bool, list[str]] | None:
    """The scene's package and visual prompt as they were before the rewrite this event
    records, whether they are exact, and the package's keys that stay the rewrite's; None
    when the words were changed since the rewrite (they are then someone else's and are kept).

    From 2026-10-10 the event carries the whole package and visual prompt it replaced
    (exact, nothing stays). An older event carried only the old still and motion prompts:
    they are put back over the rewritten package, and the old still prompt is also the
    visual prompt, as `prompt_agent.write_shot_prompts` stores it (the event's old still
    prompt was read from the stored still prompt, else from the visual prompt). What it did
    not keep (`_REWRITE_COMPILED_KEYS`: the motion intent, the negative prompt, the camera
    move, ...) stays as the rewrite wrote it, and is named (review 2026-10-10): the package put
    back is then one that never existed."""
    if isinstance(payload.get("old_package"), dict):
        if current != payload.get("package") or visual != payload.get("visual_prompt"):
            return None
        old_visual = str(payload.get("old_visual_prompt") or "")
        return dict(payload["old_package"]), old_visual, True, []
    if _words_of(current.get("still_prompt")) != _words_of(payload.get("still_prompt")):
        return None
    if _words_of(current.get("motion_prompt")) != _words_of(payload.get("motion_prompt")):
        return None
    old_still = str(payload.get("old_still_prompt") or "")
    if not old_still:
        return None
    package = {
        **current,
        "still_prompt": old_still,
        "motion_prompt": str(payload.get("old_motion_prompt") or ""),
    }
    return package, old_still, False, [key for key in _REWRITE_COMPILED_KEYS if key in current]


def _not_given_back(
    row: SceneTake | None, payload: dict[str, Any], said: list[dict[str, Any]] | None
) -> str | None:
    """Why a retired take does not come back (None: it may): gone, changed since its
    retirement (the Owner decided on it, another redo took it), not a usable take before,
    turned down by the Owner himself, or its file missing or changed."""
    if row is None:
        return "TAKE_GONE"
    if row.status != "REJECTED" or row.failure_code != payload.get("failure_code"):
        return "CHANGED_SINCE"
    if str(payload.get("previous_status")) not in REUSABLE_TAKE_STATUSES:
        return "NOT_REUSABLE"
    if said and said[-1]["decision"] == "REJECTED":
        return "OWNER_REJECTED"
    if not row.path or not row.sha256:
        return "NO_FILE"
    path = Path(str(row.path))
    if not path.is_file() or _known_file_sha256(path) != row.sha256:
        return "NO_FILE"
    return None


def give_back_retired_takes(
    engine: Engine,
    storyboard_id: str,
    scene_index: int,
    *,
    correlation_id: str,
    after_sequence: int | None = None,
    cause: str,
) -> dict[str, Any]:
    """The takes one redo retired (its TAKE_RETIRED_EVENTs: ``correlation_id``, this scene,
    after the event ``after_sequence`` when given) given back as they were, when nothing it
    or anyone made since was delivered (`_delivered_since`: no still or shot of the scene
    created after the retirement is APPROVED, PAID, still SUBMITTED, or REJECTED with its
    file). 0 credits, no vendor asked; each retirement is given back at most once
    (TAKE_RESTORED_EVENT names it).

    A take comes back only as the redo left it (REJECTED with the redo's code), with its file
    on disk unchanged, and never one the Owner turned down himself; the shots a retired still
    took with it stay retired when that still cannot come back. Its status, failure and
    approver come back from the retirement's event (an event from before 2026-10-10 kept only
    the status; an APPROVED or PAID take carried no failure then).

    When the same redo rewrote the scene's words (`_rewrite_scene_prompts`) and nobody changed
    them since, they are put back too (`_package_before_rewrite`, SCENE_PROMPTS_RESTORED_EVENT)
    so the takes match their prompt hash again. A take the Owner approved himself that the
    words put back do not reproduce (an older event did not keep the motion intent the
    rewrite replaced) is bound to the picture he approved: its prompt hash becomes the hash
    of the scene as restored, and the hash it had stays on its event (``bound_to_picture``,
    ``previous_prompt_hash``). Any other take that does not match comes back unmatched and is
    not used until its words match (``unmatched``).

    Words put back from an older event keep the rest of the rewritten package; the keys that
    stay the rewrite's are named (``kept_from_rewrite``, on the outcome and on the event).

    Returns {storyboard_id, scene_index, restored, bound_to_picture, unmatched, package
    (None | "restored" | "exact" | "CHANGED_SINCE"), kept_from_rewrite, skipped [{take_id,
    why}], why}."""
    scene_index = int(scene_index)
    outcome: dict[str, Any] = {
        "storyboard_id": storyboard_id,
        "scene_index": scene_index,
        "restored": [],
        "bound_to_picture": [],
        "unmatched": [],
        "package": None,
        "kept_from_rewrite": [],
        "skipped": [],
        "why": None,
    }
    with Session(engine) as session:
        retired = _unreturned_retirements(
            session, storyboard_id, scene_index, correlation_id, after_sequence
        )
        if not retired:
            outcome["why"] = "NOTHING_RETIRED"
            return outcome
        first = retired[0]
        ids = [str(event.aggregate_id) for event in retired]
        if _delivered_since(session, storyboard_id, scene_index, str(first.timestamp), ids):
            outcome["why"] = "DELIVERED_SINCE"
            return outcome
        scene_row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id,
                StoryboardScene.scene_index == scene_index,
            )
        )
        if scene_row is None:
            outcome["why"] = "NO_SCENE"
            return outcome
        rewrite = _unreturned_rewrite(
            session,
            storyboard_id,
            scene_index,
            correlation_id,
            before=int(first.sequence),
            after=after_sequence,
        )
        decisions = owner_take_decisions(session, ids)
        rows: dict[str, SceneTake] = {}
        for take_id in ids:
            row = session.get(SceneTake, take_id)
            if row is not None:
                session.expunge(row)
                rows[take_id] = row
        view = scene_view(scene_row)
        seen_package = dict(scene_row.prompt_json or {})
        seen_visual = scene_row.visual_prompt
        rewrite_payload = dict(rewrite.payload or {}) if rewrite is not None else {}
        rewrite_id = rewrite.event_id if rewrite is not None else None

    # Which takes may come back. A still that cannot keeps the shots filmed from it retired.
    eligible: list[tuple[DomainEvent, SceneTake]] = []
    still_stays = False
    for event in retired:
        payload = dict(event.payload or {})
        take = rows.get(str(event.aggregate_id))
        why = _not_given_back(take, payload, decisions.get(str(event.aggregate_id)))
        if why is not None or take is None:
            outcome["skipped"].append({"take_id": str(event.aggregate_id), "why": why})
            if payload.get("kind") == "still" and payload.get("previous_status") == "APPROVED":
                still_stays = True
            continue
        eligible.append((event, take))
    if still_stays:
        for event, take in [pair for pair in eligible if pair[1].kind in SHOT_TAKE_KINDS]:
            if (event.payload or {}).get("failure_code") == REDO_STILL_REPLACED:
                eligible.remove((event, take))
                outcome["skipped"].append({"take_id": take.id, "why": "STILL_NOT_BACK"})
    if not eligible:
        outcome["why"] = "NOTHING_TO_GIVE_BACK"
        return outcome

    # The scene's words as they were before the redo, when it rewrote them.
    package: dict[str, Any] | None = None
    visual = ""
    exact = False
    kept: list[str] = []
    if rewrite_id is not None:
        before = _package_before_rewrite(rewrite_payload, seen_package, seen_visual)
        if before is None:
            outcome["package"] = "CHANGED_SINCE"
        else:
            package, visual, exact, kept = before
            view = {**view, "prompt_json": dict(package), "visual_prompt": visual}

    # Whether each take matches the scene as it will be, and what a take of his is bound to.
    options = still_options(engine, view)
    still_sha = next(
        (
            take.sha256
            for event, take in eligible
            if take.kind == "still" and (event.payload or {}).get("previous_status") == "APPROVED"
        ),
        None,
    )
    if still_sha is None and options:
        with Session(engine) as session:
            standing = usable_take(
                session, storyboard_id, scene_index, "still", options, statuses=("APPROVED",)
            )
            still_sha = standing.sha256 if standing is not None else None
    shot_identity = (
        motion_fields(view, still_sha, from_prompt=False)
        if still_sha
        else motion_fields(view, None, from_prompt=True)
    )
    planned: list[dict[str, Any]] = []
    for event, take in eligible:
        payload = dict(event.payload or {})
        previous = str(payload["previous_status"])
        if take.kind == "still":
            matches = any(take_hash(f, take.model_id) == take.prompt_hash for f in options)
            primary: dict[str, Any] | None = options[0] if options else None
        else:
            matches = shot_identity_matches(take, view, still_sha)
            primary = shot_identity
        bind: str | None = None
        if (
            not matches
            and package is not None
            and primary is not None
            and previous == "APPROVED"
            and _owner_stands_by(take, decisions.get(take.id), previous)
        ):
            bind = take_hash(primary, take.model_id)
        planned.append(
            {
                "event": event,
                "payload": payload,
                "take_id": take.id,
                "seen_hash": take.prompt_hash,
                "previous": previous,
                "matches": matches,
                "bind": bind,
            }
        )

    now = utc_now()
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        scene_row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id,
                StoryboardScene.scene_index == scene_index,
            )
        )
        if (
            scene_row is None
            or dict(scene_row.prompt_json or {}) != seen_package
            or scene_row.visual_prompt != seen_visual
            or _delivered_since(session, storyboard_id, scene_index, str(first.timestamp), ids)
        ):
            # Written meanwhile: what was verified above no longer holds; the next look decides.
            outcome["why"] = "CHANGED_SINCE"
            return outcome
        returned = _given_back_ids(
            session, TAKE_RESTORED_EVENT, "retired_event_id", [item["take_id"] for item in planned]
        )
        for item in planned:
            row = session.get(SceneTake, item["take_id"])
            payload = item["payload"]
            if (
                item["event"].event_id in returned
                or row is None
                or row.status != "REJECTED"
                or row.failure_code != payload.get("failure_code")
                or row.prompt_hash != item["seen_hash"]
            ):
                outcome["skipped"].append({"take_id": item["take_id"], "why": "CHANGED_SINCE"})
                continue
            bind = item["bind"]
            if bind is not None and session.scalar(
                select(SceneTake.id)
                .where(
                    SceneTake.storyboard_id == row.storyboard_id,
                    SceneTake.scene_number == row.scene_number,
                    SceneTake.kind == row.kind,
                    SceneTake.prompt_hash == bind,
                    SceneTake.sha256 == row.sha256,
                    SceneTake.id != row.id,
                )
                .limit(1)
            ):
                bind = None  # the same file under those words is another row already
            row.status = item["previous"]
            # What the take carried before the redo; an older event kept the status only.
            row.failure_code = payload.get("previous_failure_code")
            row.failure_detail = payload.get("previous_failure_detail")
            if "previous_approved_by" in payload:
                row.approved_by = payload.get("previous_approved_by")
            if bind is not None:
                row.prompt_hash = bind
            row.updated_at = now
            sync_take_quality(session, row)
            append_event(
                session,
                TAKE_RESTORED_EVENT,
                "scene_take",
                row.id,
                1,
                {
                    "storyboard_id": storyboard_id,
                    "scene_number": scene_index,
                    "kind": row.kind,
                    "status": row.status,
                    "retired_event_id": item["event"].event_id,
                    "retired_code": payload.get("failure_code"),
                    "cause": cause,
                    "prompt_matches": bool(item["matches"]),
                    "bound_to_picture": bind is not None,
                    **({"previous_prompt_hash": item["seen_hash"]} if bind is not None else {}),
                    "package_restored": package is not None,
                },
                correlation_id,
            )
            outcome["restored"].append(row.id)
            if bind is not None:
                outcome["bound_to_picture"].append(row.id)
            elif not item["matches"]:
                outcome["unmatched"].append(row.id)
        if outcome["restored"] and package is not None and rewrite_id is not None:
            scene_row.prompt_json = dict(package)
            scene_row.visual_prompt = visual
            append_event(
                session,
                SCENE_PROMPTS_RESTORED_EVENT,
                "storyboard",
                storyboard_id,
                1,
                {
                    "storyboard_id": storyboard_id,
                    "scene_index": scene_index,
                    "rewritten_event_id": rewrite_id,
                    "still_prompt": _words_of(package.get("still_prompt")),
                    "motion_prompt": _words_of(package.get("motion_prompt")),
                    "replaced_still_prompt": _words_of(seen_package.get("still_prompt")),
                    "replaced_motion_prompt": _words_of(seen_package.get("motion_prompt")),
                    "exact": exact,
                    # What an older event could not put back: still as the rewrite wrote it.
                    "kept_from_rewrite": list(kept),
                    "cause": cause,
                    "takes": list(outcome["restored"]),
                },
                correlation_id,
            )
            outcome["package"] = "exact" if exact else "restored"
            outcome["kept_from_rewrite"] = list(kept)
    outcome["why"] = "GIVEN_BACK" if outcome["restored"] else "NOTHING_TO_GIVE_BACK"
    return outcome


def given_back_ro(returned: dict[str, Any]) -> str:
    """The Owner's line for takes given back after a redo that delivered nothing usable."""
    index = returned.get("scene_index")
    words = (
        f"Refacerea scenei {index} nu a adus nimic folosibil, așa că înregistrările retrase au "
        "fost repuse cum erau"
    )
    if returned.get("package") in ("restored", "exact"):
        words += ", cu promptul scenei de dinainte"
    words += "; filmul se poate asambla din ele."
    if returned.get("bound_to_picture"):
        words += (
            " Pentru înregistrările aprobate de Proprietar, aprobarea lui ține de imaginea "
            "aleasă: rămân ale scenei chiar dacă vechiul prompt nu a putut fi refăcut întocmai."
        )
    return words


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
    if table is None:
        # The same table the sheet prices with: the local selection's own models at 0
        # credits and this connection's MEASURED rows, not the raw published table — the
        # raw table named SDXL_LOCAL unpriced and refused the Owner his free still.
        from app.media.shooting_sheet import price_table_for  # noqa: PLC0415 - it imports us

        prices = price_table_for(engine, integration_id)
    else:
        prices = table
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


# ------------------------------------------ a redone still is bought on today's prompt
#
# 2026-10-09 (film babcf272, «The Particle That Shouldn't Exist (But Does)»): scene 5's still
# came back as three stacked panels (an atom in the tunnel, a flat black band, the empty
# tunnel) and its clip animated the triptych. Its stored still prompt described a sequence of
# moments ("..., then the empty accelerator tunnel from scene 1. First the near-black void of
# scenes 2 and 3, then the identical tunnel ..."). A scene's package is compiled once, when the
# shots are written (`prompt_agent.write_shot_prompts`), and «Refă imaginea» bought the STORED
# words again: a compiler fixed since could never reach a film already planned, and the redo
# would have bought the same triptych. A still redo now compiles that one scene again from its
# stored plan with today's compiler (deterministic, 0 credits, no language model). When the
# still prompt differs, the Owner's plan shows the new words and its hash is bound to them,
# and the package is rewritten in the transaction that spends his yes; the motion redo that
# follows reads the rewritten package. No other scene is touched, so every other bought take
# keeps matching its prompt. An episode of the serial (its prompt is composed from the series'
# look, `compose_serial_prompt`) and a package with no plan to compile keep their words.

#: A scene whose prompts the studio compiled again for a redo: {storyboard_id, scene_index,
#: old_still_prompt, still_prompt, old_motion_prompt, motion_prompt, reason, plan_hash} and,
#: from 2026-10-10, {old_package, old_visual_prompt, package, visual_prompt}. A
#: «media.prompt*» type: the claim checker (`agents.reviews.check_work_claims`) proves «am
#: rescris promptul» only by one, and an agent's true report of this repair was labelled
#: NEEFĂCUT under the first name, "media.scene_prompts_rewritten" (review 2026-10-09).
SCENE_PROMPTS_REWRITTEN_EVENT = "media.prompts_rewritten"
#: The plan fields the compiler builds a still from; a package with none of them (made by
#: hand, or from before the compiler) has nothing to compile again and keeps its words.
_REDO_PLAN_FIELDS: tuple[str, ...] = ("subject", "action", "environment")
#: How much of a rewritten sentence the Owner's plan quotes.
_REWRITE_EXCERPT_CHARS = 160


def _scene_prompt_rewrite(
    session: Session, storyboard_id: str, scene_index: int, still_model: str
) -> dict[str, Any] | None:
    """One filmed scene's prompts compiled again from its stored plan, as the studio writes
    them today, when the still prompt differs from the stored one; None when it does not (or
    there is nothing to compile). Reads only; 0 credits, no language model.

    Compiled as `write_shot_prompts` compiles it (the scene's kind and shot type, the film's
    bible, the factual look, the camera moves of the filmed scenes before it as stored), with
    the still compiled for the model it is bought on. Raises `SceneRedoRefused`
    (PROMPT_NOT_COMPILED) when the compiler cannot read the package: stale words are never
    bought in silence."""
    from app.agents.editorial import is_serial_film  # noqa: PLC0415 - agents import media
    from app.factual.models import ScriptDraft  # noqa: PLC0415
    from app.media.prompt_agent import compile_prompts  # noqa: PLC0415 - it imports us
    from app.media.series_look import load_factual_look  # noqa: PLC0415

    board = session.get(Storyboard, storyboard_id)
    if board is None:
        return None
    script = session.get(ScriptDraft, board.script_draft_id) if board.script_draft_id else None
    if is_serial_film(board, script):
        # A serial scene's words are the composer's: said again with today's composer when
        # they changed (2026-10-12, f06808c9: stills bought on stored words from before the
        # composer's fix came back as panels, and a redo would have bought them again).
        from app.media.scene_rewrite import serial_recomposition  # noqa: PLC0415

        return serial_recomposition(session, storyboard_id, scene_index)
    moves: list[str] = []
    target: StoryboardScene | None = None
    for row in session.scalars(
        select(StoryboardScene)
        .where(StoryboardScene.storyboard_id == storyboard_id)
        .order_by(StoryboardScene.scene_index)
    ):
        if int(row.scene_index) == scene_index:
            target = row
            break
        if scene_kind_of({"scene_kind": row.scene_kind}) == LIVE_KIND:
            move = str((row.prompt_json or {}).get("camera_move") or "").strip()
            if move:
                moves.append(move)
    if target is None or scene_kind_of({"scene_kind": target.scene_kind}) != LIVE_KIND:
        return None
    stored = dict(target.prompt_json or {})
    if not any(str(stored.get(name) or "").strip() for name in _REDO_PLAN_FIELDS):
        return None
    old_still = " ".join(str(stored.get("still_prompt") or target.visual_prompt or "").split())
    source = {**stored, "scene_kind": LIVE_KIND, "shot_type": target.shot_type}
    try:
        compiled = compile_prompts(
            source,
            dict(board.visual_bible_json or {}),
            {"still_model_id": still_model},
            previous_moves=moves,
            look=load_factual_look(),
        )
    except (ValueError, TypeError, KeyError) as exc:
        raise SceneRedoRefused(
            "PROMPT_NOT_COMPILED",
            f"Promptul imaginii scenei {scene_index} nu a putut fi scris din nou din planul "
            f"scenei ({type(exc).__name__}); nu se cumpără o imagine pe cuvintele vechi.",
        ) from exc
    new_still = " ".join(str(compiled.get("still_prompt") or "").split())
    if not new_still or new_still == old_still:
        return None
    return {
        "scene_index": scene_index,
        "old_still_prompt": old_still,
        "still_prompt": new_still,
        "old_motion_prompt": " ".join(str(stored.get("motion_prompt") or "").split()),
        "motion_prompt": " ".join(str(compiled.get("motion_prompt") or "").split()),
        # What the purchase writes, and what it must still find there to write it.
        "package": {**source, **compiled},
        "visual_prompt": str(compiled["still_prompt"]),
        "stored_package": stored,
        "stored_visual": target.visual_prompt,
    }


#: What a redo plan shows of a rewrite (the rest is the purchase's).
_REWRITE_SHOWN: tuple[str, ...] = (
    "old_still_prompt",
    "still_prompt",
    "old_motion_prompt",
    "motion_prompt",
)


def _excerpt(text: str, limit: int = _REWRITE_EXCERPT_CHARS) -> str:
    """At most ``limit`` characters of ``text``, cut at a word with an ellipsis."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _rewrite_note_ro(rewrite: dict[str, Any]) -> str:
    """The Owner's line for a rewritten still prompt: the sentences taken out and put in."""
    sentence = re.compile(r"(?<=[.!?])\s+")
    old = [s for s in sentence.split(str(rewrite["old_still_prompt"])) if s]
    new = [s for s in sentence.split(str(rewrite["still_prompt"])) if s]
    removed = " ".join(s for s in old if s not in new)
    added = " ".join(s for s in new if s not in old)
    parts = [
        f"scos „{_excerpt(removed)}”" if removed else "",
        f"pus „{_excerpt(added)}”" if added else "",
    ]
    if not removed and not added:  # the same sentences in another order
        parts = [f"acum „{_excerpt(str(rewrite['still_prompt']))}”"]
    return (
        "Promptul imaginii a fost rescris de studio din planul scenei, cu compilatorul de azi "
        "(0 credite, fără model de limbaj): "
        + "; ".join(part for part in parts if part)
        + ". Imaginea se cumpără cu promptul nou, iar pachetul scenei se rescrie la cumpărare."
    )


def _rewrite_scene_prompts(
    session: Session,
    storyboard_id: str,
    rewrite: dict[str, Any],
    *,
    plan: dict[str, Any],
    plan_hash: str,
    correlation_id: str,
) -> None:
    """The one redone scene's package rewritten, inside the transaction that spends the
    Owner's yes, with its event. A package changed since the plan was read refuses the redo
    (STALE_PLAN): the caller's transaction is rolled back and his yes stays unspent."""
    row = session.scalar(
        select(StoryboardScene).where(
            StoryboardScene.storyboard_id == storyboard_id,
            StoryboardScene.scene_index == int(rewrite["scene_index"]),
        )
    )
    if (
        row is None
        or dict(row.prompt_json or {}) != rewrite["stored_package"]
        or row.visual_prompt != rewrite["stored_visual"]
    ):
        raise SceneRedoRefused(
            "STALE_PLAN",
            f"Pachetul scenei {rewrite['scene_index']} s-a schimbat de când a fost arătat "
            "planul refacerii: nu se cumpără nimic. Deschideți refacerea din nou.",
            plan=plan,
        )
    row.prompt_json = dict(rewrite["package"])
    row.visual_prompt = str(rewrite["visual_prompt"])
    append_event(
        session,
        SCENE_PROMPTS_REWRITTEN_EVENT,
        "storyboard",
        storyboard_id,
        1,
        {
            "storyboard_id": storyboard_id,
            **{key: rewrite[key] for key in ("scene_index", *_REWRITE_SHOWN)},
            "reason": "redo",
            "plan_hash": plan_hash,
            # The whole package and visual prompt before and after (2026-10-10, babcf272): a
            # redo that delivers nothing puts the old words back exactly, so the takes it
            # retired match their prompt hash again (`give_back_retired_takes`). The two
            # prompts above alone could not restore the motion intent the hash also reads.
            "old_package": dict(rewrite["stored_package"]),
            "old_visual_prompt": rewrite["stored_visual"],
            "package": dict(rewrite["package"]),
            "visual_prompt": str(rewrite["visual_prompt"]),
        },
        correlation_id,
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
    from app.media.factory import reference_model_for_storyboard  # noqa: PLC0415

    model_id = (
        reference_model_for_storyboard(engine, plan["storyboard_id"], stills_model) or STILLS_MODEL
    )
    try:
        per_request = price_still(model_id, STILLS_RESOLUTION, STILL_CANDIDATES, table=prices)
        row = prices.row(model_id, STILLS_RESOLUTION)
    except UnpricedError as exc:
        raise SceneRedoRefused("UNPRICED", f"Nu se cumpără imagini: {exc}.", plan=plan) from exc
    # RunPod Serverless (2026-10-09): the redo is one GPU round per purchase (its pair, then
    # each re-roll), and every round pays a GPU start (cold start + idle tail) as the stills
    # step prices it. 0 for a per-image vendor, so its plan (and its hash) is unchanged.
    overhead = int(prices.round_overhead("image", model_id))
    per_round = per_request + overhead
    cap = per_round * (1 + MAX_REROLLS)
    first_live = next((s for s in scenes if not is_composed(s)), None)
    figure_one: str | None = None
    with Session(engine) as session:
        replaces = _scene_approved_stills(session, plan["storyboard_id"], index)
        invalidates = _scene_shot_takes(session, plan["storyboard_id"], index)
        # A request the vendor accepted for this scene and has not handed over yet: it is
        # collected free, by its task id, and the scene is never bought a second time meanwhile.
        in_flight = sorted(
            session.scalars(
                select(SceneTake.id).where(
                    SceneTake.storyboard_id == plan["storyboard_id"],
                    SceneTake.scene_number == index,
                    SceneTake.kind == "still",
                    SceneTake.status == "SUBMITTED",
                )
            ).all()
        )
        if first_live is not None and int(first_live["scene_index"]) != index:
            reference = usable_take(
                session,
                plan["storyboard_id"],
                int(first_live["scene_index"]),
                "still",
                still_options(engine, first_live),
                statuses=("APPROVED",),
            )
            figure_one = reference.sha256 if reference is not None else None
        # The words the studio writes for the scene today (2026-10-09, film babcf272): the
        # plan shows them, its hash binds the Owner's yes to them, and the purchase sends them.
        rewrite = _scene_prompt_rewrite(session, plan["storyboard_id"], index, model_id)
    package = scene.get("prompt_json") or {}
    from app.media.prompt_agent import incomplete_plan_fields  # noqa: PLC0415

    incomplete = incomplete_plan_fields(
        rewrite["package"] if rewrite is not None else package, layers=("still",)
    )
    if incomplete:
        raise SceneRedoRefused("LINT_BLOCKED", "; ".join(incomplete), plan=plan)
    words = " ".join(str(package.get("still_prompt") or scene.get("visual_prompt") or "").split())
    pictured = scene
    shown: dict[str, Any] | None = None
    if rewrite is not None:
        words = str(rewrite["still_prompt"])
        pictured = {**scene, "visual_prompt": rewrite["visual_prompt"]}
        shown = {key: rewrite[key] for key in _REWRITE_SHOWN}
    plan.update(
        action=REDO_ACTION,
        tier=REDO_TIER,
        free=False,
        buyable=True,
        model_id=model_id,
        resolution=STILLS_RESOLUTION,
        credits=per_round,
        cap_credits=cap,
        cost_usd=round(per_round * prices.credit_usd, 6),
        cap_usd=round(cap * prices.credit_usd, 6),
        price_source=source_label(row),
        candidates=STILL_CANDIDATES,
        max_rerolls=MAX_REROLLS,
        still_prompt=words,
        figure_one_sha256=figure_one,
        replaces=replaces,
        invalidates=invalidates,
    )
    if shown is not None:
        plan.update(prompt_rewrite=shown)
    if overhead:
        plan.update(credits_per_request=per_request, round_overhead_credits=overhead)
    gpu_start = f" și pornirea GPU-ului ({overhead} credite pe rundă)" if overhead else ""
    reason = (
        f"Imaginea scenei {index}: {STILL_CANDIDATES} variante la 2K pe {model_id}{gpu_start}, "
        f"{per_round} credite (plafon {cap}, cu cel mult {MAX_REROLLS} reluări). "
        "Imaginea veche și cadrul filmat din ea se retrag abia după aprobare; mișcarea scenei "
        "se reface apoi separat. Celelalte scene nu se ating."
    )
    if shown is not None:
        reason = f"{_rewrite_note_ro(shown)} {reason}"
    if in_flight:
        plan.update(buyable=False, in_flight=in_flight)
        reason = (
            f"Imaginile scenei {index} sunt deja cumpărate: furnizorul a primit cererea și nu "
            "le-a predat încă. Se ridică fără plată, după numărul sarcinii, și apar pe foaia de "
            "filmare; până atunci scena nu se cumpără din nou."
        )
    return _seal(
        plan,
        {
            "model_id": model_id,
            "resolution": STILLS_RESOLUTION,
            "candidates": STILL_CANDIDATES,
            "max_rerolls": MAX_REROLLS,
            "credits": per_round,
            "cap_credits": cap,
            **({"round_overhead_credits": overhead} if overhead else {}),
            "still_prompt": words,
            # The identity the new still is recorded under: its words as they will be stored.
            "identity": next(iter(still_options(engine, pictured)), None),
            "figure_one_sha256": figure_one,
            "replaces": replaces,
            "invalidates": invalidates,
            **({"in_flight": in_flight} if in_flight else {}),
            # Only a rewritten plan says so: a plan with current words keeps its hash.
            **({"prompt_rewrite": shown} if shown is not None else {}),
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
            still_options(engine, first_live),
            statuses=("APPROVED",),
        )
        return Path(str(take.path)) if take is not None and take.path else None


def _run_ffmpeg(
    command: list[str], folder: Path, carry: Sequence[str] = ()
) -> subprocess.CompletedProcess[str]:
    """A redo's encode, from a short working directory (see run_encoder). An encoder that
    cannot start or runs past its time is the redo's own refusal (ENCODE_FAILED, 409)."""
    try:
        return run_encoder(command, folder, carry=carry)
    except RenderEngineUnavailable as exc:
        raise SceneRedoRefused("ENCODE_FAILED", str(exc)) from exc


def _verified_timeline(
    film: dict[str, Any], scenes: list[dict[str, Any]], scene_index: int
) -> tuple[list[dict[str, Any]], list[int]]:
    """The film's shots, each other than ``scene_index`` checked to be the very file the film
    was joined from; a shot rebuilt since (another render) is never mixed in. With them, the
    scenes whose shot must be cut again from what it was cut from (its recorded ``source``):
    its file was released after quality control, or rebuilt since by another render."""
    folder = Path(film["path"]).parent
    timeline = _film_timeline(film["production"], scenes, folder)
    if [int(item["scene_index"]) for item in timeline] != [int(s["scene_index"]) for s in scenes]:
        raise SceneRedoRefused(
            "FILM_CHANGED",
            "Scenele storyboardului nu mai sunt cele din film: filmul nu se reasamblează pe "
            "bucăți.",
        )
    stale: list[int] = []
    for item in timeline:
        if int(item["scene_index"]) == scene_index:
            continue
        path = folder / str(item["file"])
        missing = not path.is_file()
        changed = not missing and bool(item.get("sha256")) and _file_sha256(path) != item["sha256"]
        if (missing or changed) and isinstance(item.get("source"), dict):
            stale.append(int(item["scene_index"]))
        elif missing:
            raise SceneRedoRefused(
                "NO_SHOTS", f"Cadrul scenei {item['scene_index']} lipsește de lângă film."
            )
        elif changed:
            raise SceneRedoRefused(
                "SHOT_CHANGED",
                f"Cadrul scenei {item['scene_index']} nu mai este cel din film (a fost "
                "reconstruit între timp): nu se amestecă cadre din filme diferite.",
            )
    return timeline, stale


def _source_file(
    engine: Engine,
    storyboard_id: str,
    scene_index: int,
    folder: Path,
    recorded: Any,
    digest: Any,
) -> Path | None:
    """The file a shot was cut from: where the render read it, else beside the film, else this
    scene's take with the same sha256. None when none of them is on disk with those bytes."""
    if not recorded:
        return None
    candidates = [Path(str(recorded)), folder / Path(str(recorded)).name]
    if digest:
        with Session(engine) as session:
            candidates += [
                Path(str(path))
                for path in session.scalars(
                    select(SceneTake.path).where(
                        SceneTake.storyboard_id == storyboard_id,
                        SceneTake.scene_number == scene_index,
                        SceneTake.sha256 == str(digest),
                    )
                )
                if path
            ]
    for candidate in candidates:
        if candidate.is_file() and (not digest or _file_sha256(candidate) == digest):
            return candidate
    return None


def _rederive_shot(
    engine: Engine,
    storyboard_id: str,
    film: dict[str, Any],
    scenes: list[dict[str, Any]],
    item: dict[str, Any],
    *,
    ffmpeg_exe: str,
    stamp: str,
) -> dict[str, Any]:
    """One shot cut again from what it was cut from, at 0 credits and with no adapter: a
    composed card recomposed from its spec, a LIVE scene from its still or its vendor clip
    (the file the render read, or the scene's take with the same sha256). Written under a name
    of its own, never over a file another render may hold."""
    folder = Path(film["path"]).parent
    source: dict[str, Any] = item["source"]
    index = int(item["scene_index"])
    span = float(item["span"])
    fps = int(source.get("fps") or film_fps(film["production"]))
    scene = next(s for s in scenes if int(s["scene_index"]) == index)
    hold = float(source.get("hold") or 0.0)
    # A clip slowed into its span (`_clip_slowdowns`) is slowed again the same way.
    slow = float(source.get("slow") or 1.0)
    interpolate = str(source.get("interpolate") or "framerate")
    if source.get("card"):
        background = _card_background(
            engine, storyboard_id, film["production"], scenes, folder, index
        )
        work = folder / f"redo_{stamp}"
        work.mkdir(parents=True, exist_ok=True)
        # Cut again as it was cut: a closing card stays one, and a black card of a film made
        # before the shorts' rule stays black, so the rejoined film is the film it was.
        recorded = next(
            (
                entry.get("card")
                for entry in film["production"].get("scenes") or []
                if isinstance(entry, dict)
                and entry.get("scene_index") == index
                and isinstance(entry.get("card"), dict)
            ),
            None,
        )
        try:
            card = _compose_card_clip(
                scene,
                work,
                seconds=span,
                background=background,
                ffmpeg_exe=ffmpeg_exe,
                fps=fps,
                short=bool((recorded or {}).get("closing")),
            )
        except CardError as exc:
            raise SceneRedoRefused(
                "NO_SHOTS", f"Scena {index}: cardul nu poate fi recompus: {exc}"
            ) from exc
        clip: Path | None = Path(card["path"])
        still = clip
        hold = 0.0
        slow = 1.0
    else:
        still = _source_file(
            engine, storyboard_id, index, folder, source.get("still"), source.get("still_sha256")
        )
        clip = _source_file(
            engine, storyboard_id, index, folder, source.get("clip"), source.get("clip_sha256")
        )
        lost: str | None = None
        if source.get("clip") and clip is None:
            lost = "clipul"
        elif (source.get("still") and still is None) or (still is None and clip is None):
            lost = "imaginea"
        if lost is not None:
            raise SceneRedoRefused(
                "NO_SHOTS",
                f"Cadrul scenei {index} nu mai este lângă film, iar {lost} din care a fost "
                "făcut nu mai este pe disc: filmul nu se reasamblează fără să fie randat din nou.",
            )
    picture = still if still is not None else clip
    if picture is None:  # refused above; kept for the type checker
        raise SceneRedoRefused("NO_SHOTS", f"Cadrul scenei {index} nu are sursă.")
    target = folder / f"shot_{index:02d}_{stamp}.mp4"
    built = _run_ffmpeg(
        _shot_command(
            ffmpeg_exe,
            picture,
            clip,
            span,
            target,
            fps=fps,
            hold=hold,
            dither=bool(source.get("dither", True)),
            slow=slow if clip is not None else 1.0,
            interpolate=interpolate,
        ),
        folder,
    )
    if built.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise SceneRedoRefused(
            "ENCODE_FAILED", f"Cadrul scenei {index} nu a putut fi refăcut din sursa lui."
        )
    return {
        **item,
        "file": target.name,
        "sha256": _file_sha256(target),
        "rederived": True,
        "recorded_sha256": item.get("sha256"),
    }


def _regrade(
    ffmpeg_exe: str, production: dict[str, Any], scene_index: int, shot: Path
) -> str | None:
    """A rebuilt shot's grade toward the hero the film was graded to, and the film's grade
    record updated for that scene; None when the film was not graded or the shot is the
    hero itself or cannot be measured."""
    grade = production.get("grade")
    if not isinstance(grade, dict) or not isinstance(grade.get("reference"), dict):
        return None
    if grade.get("reference_scene") == scene_index:
        return None
    stats = measure_picture(ffmpeg_exe, shot)
    if stats is None:
        return None
    hero = grade["reference"]
    found = grade_toward(stats, hero, strength=float(grade.get("strength") or 0.0))
    entry = {
        "scene_index": scene_index,
        "filter": found["filter"] if found else None,
        "params": found["params"] if found else None,
        "measured": stats,
        "predicted": found["predicted"] if found else stats,
        "delta_e_before": delta_e(stats, hero),
        "delta_e_after": delta_e(found["predicted"], hero) if found else delta_e(stats, hero),
        "regraded": True,
    }
    shots = [e for e in grade.get("shots") or [] if e.get("scene_index") != scene_index]
    grade["shots"] = sorted([*shots, entry], key=lambda e: int(e.get("scene_index") or 0))
    afters = [float(e["delta_e_after"]) for e in grade["shots"] if "delta_e_after" in e]
    grade["delta_e_max_after"] = max(afters, default=0.0)
    return str(found["filter"]) if found else None


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

    The rejoin is the film's final encode, and is held to quality control's bitrate floor the
    way the render's is (`encode_to_floor`): a dark, nearly still film the render had to
    tighten (7c26a7ce «Speed of Light», 4.4 Mbps at CRF 17) came out under the floor again
    from a plain CRF 17 rejoin, right after its redo was bought. The manifest's ``encode`` is
    the redo's own reading, never the film's it was copied from.
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
    timeline, stale = _verified_timeline(film, scenes, scene_index)
    target = next(item for item in timeline if int(item["scene_index"]) == scene_index)
    scene = next(s for s in scenes if int(s["scene_index"]) == scene_index)
    span = float(target["span"])
    # A redone shot is cut at the film's own frame rate: a film from before the 24 fps
    # timeline is rejoined at its 30, never a mix of the two.
    fps = film_fps(production)
    stamp = uuid4().hex[:8]
    if redo == "motion" and moving is not None:
        # A redone clip too short to be slowed into its span is not cut in (below): refused
        # before any shot is cut again, so nothing is left behind.
        measured = _video_stream_seconds(ffmpeg_exe, moving)
        if measured is not None and not clip_fits(measured, span):
            raise SceneRedoRefused(CLIP_SHORT, clip_short_words(scene_index, measured, span))
    # The shots released after quality control (or rebuilt since by another render) are cut
    # again from their takes first: 0 credits, no adapter, and a refusal before anything new.
    rederived: list[int] = []
    made: list[Path] = []
    try:
        for position, item in enumerate(timeline):
            if int(item["scene_index"]) in stale:
                timeline[position] = _rederive_shot(
                    engine, storyboard_id, film, scenes, item, ffmpeg_exe=ffmpeg_exe, stamp=stamp
                )
                made.append(folder / str(timeline[position]["file"]))
                rederived.append(int(item["scene_index"]))
    except SceneRedoRefused:
        for path in made:
            path.unlink(missing_ok=True)
        raise
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
    # A redone clip a little short of its span is slowed into it, like any clip of a render
    # (`_clip_slowdowns`), never held on a frozen frame (the Owner, 2026-10-09); one too short
    # to be slowed that far was refused above: the film is assembled again from its takes,
    # where its scene is refused and its motion redone at the right length.
    hold = 0.0
    slow = 1.0
    interpolate: str | None = None
    if redo == "motion" and have is not None and clip_fits(have, span):
        if clip_stretch(have, span) > 1.0:
            frames_have = max(1, round(have * fps))
            slow = (max(1, round(span * fps)) + SLOWDOWN_EXTRA_FRAMES) / frames_have
            interpolate = slowdown_filter(ffmpeg_exe) or "framerate"

    def build(fill: str) -> subprocess.CompletedProcess[str]:
        return _run_ffmpeg(
            _shot_command(
                ffmpeg_exe,
                moving,
                moving,
                span,
                shot,
                fps=fps,
                hold=hold,
                dither=has_filter(ffmpeg_exe, "zscale"),
                slow=slow,
                interpolate=fill,
            ),
            folder,
        )

    built = build(interpolate or "framerate")
    failed = built.returncode != 0 or not shot.is_file() or shot.stat().st_size == 0
    if failed and slow > 1.0 and interpolate not in (None, "framerate"):
        # The render's own fallback (2026-10-10, babcf272 scene 3): minterpolate can die on a
        # clip in this encoder build; the slowed shot is blended instead.
        interpolate = "framerate"
        built = build(interpolate)
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
        "slow_factor": round(slow, 6) if slow > 1.0 else None,
        "source": _shot_source(
            still=None,
            clip=None if redo == "card" else moving,
            card=redo == "card",
            hold=hold,
            dither=has_filter(ffmpeg_exe, "zscale"),
            fps=fps,
            slow=slow,
            interpolate=interpolate,
        ),
        # The second framing of the scene's slot is kept (it follows the captions, which do
        # not change); the grade is measured again on the new picture (audit Q6, Q8).
        "framing": target.get("framing"),
        "grade": None if redo == "card" else _regrade(ffmpeg_exe, production, scene_index, shot),
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
    raw_grade = production.get("grade")
    graded: dict[str, Any] = raw_grade if isinstance(raw_grade, dict) else {}
    lut = LUT_NAME if graded.get("lut") and (folder / LUT_NAME).is_file() else None
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
        framings=[item.get("framing") for item in timeline],
        grades=[item.get("grade") for item in timeline],
        grain=int(graded.get("grain") or 0),
        lut=lut,
    )
    try:
        joined, encode = encode_to_floor(
            ffmpeg_exe,
            command,
            folder,
            output,
            carry=((srt.name, CAPTION_FONTS_DIR) if captions else ()) + ((lut,) if lut else ()),
        )
    except RenderEngineUnavailable as exc:
        output.unlink(missing_ok=True)
        raise SceneRedoRefused("ENCODE_FAILED", str(exc)) from exc
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
    if motion_record is not None and have is not None and slow > 1.0:
        # The scene's production record says the clip was slowed, as a render's does.
        motion_record = {
            **motion_record,
            "clip_seconds": round(have, 3),
            "slowed_by": round(clip_stretch(have, span), 4),
            "from_seconds": round(have, 3),
            "to_seconds": round(span, 3),
            "slow_factor": round(slow, 6),
        }
    _redone_manifest(
        production,
        timeline,
        scene_index,
        card_record=card_record,
        motion_record=motion_record,
    )
    production["encode"] = encode
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
        "rederived_shots": rederived,
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
        "rederived_shots": rederived,
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
    licence_status = film["license_status"]
    if "licences" in production:
        # A redo may have bought a new still or shot: its evidence is read like the rest.
        production["licences"] = film_licence_ledger(engine, production)
        licence_status = production["licences"]["status"]
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
                license_status=licence_status,
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


@purchase_flow
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
    clip_judge: Callable[[int, list[Path]], Any] | None = None,
    clip_check: Callable[..., Any] | None = None,
    unasked: bool = False,
    proposal: bool = False,
    director_repair: bool = False,
) -> Generator[RoundWork, dict[str, Any], dict[str, Any]]:
    """Redo one scene (``still`` | ``motion`` | ``card``) or the film's sound (``audio``).

    ``director_repair`` (with ``unasked``): the Director's repair of a defect quality control
    measured and she confirmed (`runbook.stages._apply_repairs`, 2026-10-11): it retires a
    take the Owner approved unless he marked the approval final (`decide_take` ``final``),
    and he is told what of his was replaced. The money guards are the same as any unasked
    redo's.

    ``unasked`` is a redo nobody pressed (the day's QC repairs, `_apply_repairs`): refused
    before the balance is read when the Policy Kernel refuses it outright, and stopped before a
    later re-roll or retry when the Owner's mode or rule no longer lets it buy (`mode_guard`,
    spec 51). The default, False, is his own press. Unasked, a redo that would retire a take
    the Owner approved himself is refused first (OWNER_APPROVED, 409): nothing is collected,
    asked, bought or written (2026-10-10, film babcf272), unless he already said yes to the
    studio's question for this very plan (`_owner_yes_for_redo`): that yes is his decision.

    ``proposal`` (with ``unasked``, a motion redo) is a redo the studio proposes for him to
    answer (a clip too short for its words, `propose_clip_redos`; his card of 2026-10-10):
    asking him touches nothing of his, so it is not refused OWNER_APPROVED here. The motion
    step raises his question for it even where his rule and mode would let it buy unasked
    (what the kernel refuses outright, MANUAL or the stop, stays refused), and retires and
    buys nothing before his yes for this plan (`run_motion_step`).

    A paid redo that retired takes and then delivered nothing (no candidate came with its
    file, `_delivered_since`) gives them back, with the scene's words if it rewrote them
    (`give_back_retired_takes`): its result carries ``given_back`` and says so in ``next_ro``;
    a refusal raised after the retirement says so in its reason.

    A motion redo's new shot goes through clip QC like any shot of the motion step
    (``registry``, ``clip_judge``, ``face_counter``, ``clip_check``), with its one retry
    inside the redo's cap; the film is rejoined only with a shot QC accepted.

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
        free = _free_redo(
            engine,
            storyboard_id,
            correlation_id,
            plan,
            ffmpeg_path=ffmpeg_path,
            registry=registry,
            note=note,
            requester=requester,
        )
        return _redo_done(engine, correlation_id, plan, free, {}, (0.0, None))
    if unasked and not (proposal and kind == "motion"):
        # 2026-10-10 (babcf272): the day's QC repair retired the Owner's own approved takes of
        # scenes 1 and 2 under his OVER_USD rule. A redo nobody pressed never retires what he
        # approved himself: refused here, before anything is collected, asked or bought, and
        # without a question to him (his choice stands; his own press still redoes it). His
        # yes already given to the studio's question for this very plan is his decision too
        # (`_owner_yes_for_redo`, review 2026-10-10): the redo goes on and spends it. A
        # proposal is that question: the motion step asks it, and buys only on his yes.
        with Session(engine) as session:
            standing = owner_approved_among(
                session,
                [*plan.get("replaces", []), *plan.get("invalidates", [])],
                final_only=director_repair,
            )
            if standing and not _owner_yes_for_redo(
                session, storyboard_id, plan_hash, plan.get("cap_credits")
            ):
                raise SceneRedoRefused(
                    OWNER_APPROVED,
                    _owner_choice_stands_ro(session, standing, kind, final=director_repair),
                    plan=plan,
                )

    storage_root = storage_root or media_root(settings)
    if kind == "still" and image_adapter is not None:
        # Pictures of this scene already paid for and not yet judged (an interrupted redo's,
        # collected later by its task id) are judged first, free; one the gate approves ends
        # the press with nothing bought (review 2026-10-03: they were bought again blind).
        # Under a plan that rewrites the scene's words they were bought on the words it
        # retires: collected, never judged against them (review 2026-10-09, below).
        judged = _judge_paid_stills_first(
            engine,
            storyboard_id,
            correlation_id,
            int(plan["scene_index"]),
            image_adapter=image_adapter,
            storage_root=storage_root,
            judging=not plan.get("prompt_rewrite"),
            registry=registry,
            judge=judge,
            face_counter=face_counter,
            measure=measure,
            environment=environment,
            ffmpeg_path=ffmpeg_path,
        )
        if judged is not None:
            raise SceneRedoRefused(PAID_PICTURES_JUDGED, judged, plan=current())
        plan = current()
    _paid_redo_gate(plan, plan_hash)
    no_room = disk_refusal(storage_root, settings)
    if no_room:
        raise SceneRedoRefused(LOW_DISK, no_room, plan=plan)
    from app.media.factory import reference_image_adapter  # noqa: PLC0415

    image_adapter = reference_image_adapter(engine, storyboard_id, image_adapter)
    from app.media.shooting_sheet import (  # noqa: PLC0415 - it imports us
        FilmBusy,
        PurchaseGateRefused,
        check_film_ceiling,
        film_purchase_lease,
        hold_step_budget,
        lease_seconds,
        release_step_hold,
    )
    from app.services import studio_environment  # noqa: PLC0415

    environment = environment or studio_environment(engine)
    # One buyer per film (MONEY-04): the redo runs under the film's purchase lease, and the
    # plan is read again inside it (another buyer may have changed the film meanwhile).
    kwargs: dict[str, Any] = {
        "image_adapter": image_adapter,
        "adapter_for_model": adapter_for_model,
        "capabilities": capabilities,
        "account": account,
        "registry": registry,
        "judge": judge,
        "face_counter": face_counter,
        "measure": measure,
        "allowed": allowed,
        "overrides": overrides,
        "resolution": resolution,
        "settings": settings,
        "environment": environment,
        "integration_id": integration_id,
        "table": table,
        "ffmpeg_path": ffmpeg_path,
        "storage_root": storage_root,
        "requester": requester,
        "note": note,
        "clip_judge": clip_judge,
        "clip_check": clip_check,
        "unasked": unasked,
        "proposal": proposal,
        "director_repair": director_repair,
    }
    try:
        with film_purchase_lease(
            engine,
            storyboard_id,
            holder=correlation_id,
            step=REDO_STEP,
            ttl_seconds=lease_seconds(settings),
        ):
            # The plan is read again inside the lease: another buyer may have changed the
            # film between the Owner's press and this moment.
            plan = current()
            _paid_redo_gate(plan, plan_hash)
            cap_micros = credits_to_micros(plan["cap_credits"], plan["credit_usd"])
            try:
                check_film_ceiling(
                    engine,
                    storyboard_id,
                    cap_micros,
                    step=REDO_STEP,
                    plan_hash=str(plan_hash),
                    settings=settings,
                    environment=environment,
                    allow_over_budget=allow_over_budget,
                    correlation_id=correlation_id,
                    table=table,
                )
                reservation_id = hold_step_budget(
                    engine,
                    storyboard_id,
                    REDO_STEP,
                    cap_micros,
                    plan_hash=str(plan_hash),
                    allow_over_budget=allow_over_budget,
                    correlation_id=correlation_id,
                    detail={"kind": kind, "scene_index": plan["scene_index"]},
                )
            except PurchaseGateRefused as exc:
                raise SceneRedoRefused(exc.status, exc.reason_ro, plan=plan) from exc
            try:
                return (
                    yield from flow_call(
                        _paid_redo,
                        engine,
                        storyboard_id,
                        correlation_id,
                        plan,
                        kind=kind,
                        plan_hash=str(plan_hash),
                        current=current,
                        reservation_id=reservation_id,
                        **kwargs,
                    )
                )
            except SceneRedoRefused:
                release_step_hold(engine, reservation_id, "refacerea refuzată", correlation_id)
                raise
    except FilmBusy as exc:
        # FILM_BUSY, or FILM_CLOSED for a film the Owner closed (`FilmClosed`).
        raise SceneRedoRefused(exc.status, exc.reason_ro, plan=plan) from exc


@purchase_flow
def _paid_redo(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    plan: dict[str, Any],
    *,
    kind: str,
    plan_hash: str,
    current: Callable[..., dict[str, Any]],
    reservation_id: str | None,
    image_adapter: Any,
    adapter_for_model: Callable[[str], Any] | None,
    capabilities: list[ModelCapability] | tuple[ModelCapability, ...] | None,
    account: Any,
    registry: Any,
    judge: Callable[..., Any] | None,
    face_counter: Callable[..., Any] | None,
    measure: tuple[str, ...] | None,
    allowed: Any,
    overrides: dict[int, str | None] | None,
    resolution: str | None,
    settings: Any | None,
    environment: str,
    integration_id: str | None,
    table: PriceTable | None,
    ffmpeg_path: str | None,
    storage_root: Path | None,
    requester: str,
    note: str | None,
    clip_judge: Callable[[int, list[Path]], Any] | None,
    clip_check: Callable[..., Any] | None,
    unasked: bool = False,
    proposal: bool = False,
    director_repair: bool = False,
) -> Generator[RoundWork, dict[str, Any], dict[str, Any]]:
    """The paid part of `redo_scene`, under the film's lease and the step's budget hold: the
    hold is settled once the redo is in the books and let go when nothing was bought.

    What it retired comes back when it delivered nothing usable, whether it returned or
    raised (`_give_back_after_redo`, 2026-10-10)."""
    from app.media.shooting_sheet import close_step_hold, release_step_hold  # noqa: PLC0415

    detail: dict[str, Any] = {}
    film: dict[str, Any] | None = None
    reference = _redo_reference(plan, correlation_id)
    # Only this call's retirements are given back: the same correlation runs a still redo and
    # then a motion redo of one scene in the day's QC repair.
    mark = _event_mark(engine)
    billing_source = image_adapter if kind == "still" else account
    if billing_source is None and kind == "motion" and adapter_for_model is not None:
        billing_source = adapter_for_model(str(plan.get("model_id")))
    if billing_name(billing_source) == "runpod":
        plan = {**plan, "billing_provider": "runpod"}
    # What the redo sends and commits, read below if it raises half-way (MONEY-02, REL-01).
    meter = SpendMeter()
    try:
        if kind == "motion":
            if adapter_for_model is None:
                raise SceneRedoRefused(
                    "NO_ADAPTER",
                    "Niciun model video conectat și verificat; mișcarea nu se poate cumpăra.",
                    plan=plan,
                )
            summary = yield from flow_call(
                run_motion_step,
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
                registry=registry,
                clip_judge=clip_judge,
                face_counter=face_counter,
                clip_check=clip_check,
                meter=meter,
                unasked=unasked,
                proposal=proposal,
                director_repair=director_repair,
                timezone=getattr(settings, "timezone", None),
            )
            detail["motion"] = summary
            spent = (float(summary["spent_credits_quoted"]), summary["spent_credits_measured"])
        else:
            outcome = yield from flow_call(
                _redo_still,
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
                meter=meter,
                unasked=unasked,
                director_repair=director_repair,
            )
            detail["still"] = outcome
            spent = (float(outcome["spent_credits_quoted"]), outcome["spent_credits_measured"])
    except SceneRedoRefused as exc:
        # Its hold is let go by `redo_scene`. Refused after the retirement (2026-10-10,
        # babcf272: the GPU forced off before the round was sent), what it retired comes back.
        _say_given_back(exc, _give_back_after_redo(engine, plan, correlation_id, mark))
        raise
    except MotionStepRefused as exc:
        refused = SceneRedoRefused(
            exc.status,
            exc.reason_ro,
            approval_id=exc.approval_id,
            plan=plan,
            findings=exc.findings,
        )
        _say_given_back(refused, _give_back_after_redo(engine, plan, correlation_id, mark))
        raise refused from exc
    except Exception as exc:
        _give_back_after_redo(engine, plan, correlation_id, mark)
        try:
            _redo_interrupted(engine, plan, meter, exc, correlation_id)
        except SpentStageError as spent_error:
            close_step_hold(
                engine,
                reservation_id,
                spent_credits=spent_error.credits,
                booked=spent_error.booked,
                reference=reference,
                correlation_id=correlation_id,
            )
            raise
        release_step_hold(engine, reservation_id, "refacerea a căzut", correlation_id)
        raise
    # Into the books at once, before anything else can fail: the redo's own purchase.
    detail["booked"] = _book_redo(engine, plan, spent, correlation_id)
    quoted, measured = spent
    close_step_hold(
        engine,
        reservation_id,
        spent_credits=measured if measured is not None else quoted,
        booked=detail["booked"],
        reference=reference,
        correlation_id=correlation_id,
    )
    # Bought and booked, and nothing usable came of it (every candidate refused, the round
    # stopped): the takes it retired are given back as they were.
    given_back = _give_back_after_redo(engine, plan, correlation_id, mark)
    if given_back is not None:
        detail["given_back"] = given_back
    if kind == "motion":
        film = _film_after_motion(
            engine, storyboard_id, correlation_id, plan, detail["motion"], ffmpeg_path, environment
        )
    return _redo_done(engine, correlation_id, plan, film, detail, spent)


def _event_mark(engine: Engine) -> int:
    """The newest event's sequence: what a redo writes from here on comes after it."""
    with Session(engine) as session:
        newest = session.scalar(
            select(DomainEvent.sequence).order_by(DomainEvent.sequence.desc()).limit(1)
        )
    return int(newest or 0)


def _give_back_after_redo(
    engine: Engine, plan: dict[str, Any], correlation_id: str, mark: int
) -> dict[str, Any] | None:
    """What this redo retired (its events after ``mark``), given back when it delivered
    nothing usable (`give_back_retired_takes`); None when nothing came back. Never raises:
    the redo's own result or error is what its caller reports, and the watchdog looks again
    (`app.workflows.passes.restore_retired_takes`)."""
    if plan.get("scene_index") is None:
        return None
    try:
        returned = give_back_retired_takes(
            engine,
            str(plan["storyboard_id"]),
            int(plan["scene_index"]),
            correlation_id=correlation_id,
            after_sequence=mark,
            cause="redo_delivered_nothing",
        )
    except Exception as exc:  # noqa: BLE001 - logged; the watchdog gives them back later
        logger.warning(
            "redo_takes_not_given_back",
            extra={
                "storyboard_id": plan.get("storyboard_id"),
                "scene_index": plan.get("scene_index"),
                "error": type(exc).__name__,
            },
        )
        return None
    return returned if returned["restored"] else None


def _say_given_back(refused: SceneRedoRefused, returned: dict[str, Any] | None) -> None:
    """A refusal raised after the redo retired takes says they came back."""
    if returned is None:
        return
    refused.reason_ro = f"{refused.reason_ro} {given_back_ro(returned)}"
    refused.args = (refused.reason_ro,)


def _redo_reference(plan: dict[str, Any], correlation_id: str) -> str:
    """``redo:{film}:{kind}:{scene}:{correlation}``: one reference per paid redo."""
    from app.media.shooting_sheet import purchase_reference  # noqa: PLC0415 - it imports us

    return purchase_reference(
        f"redo:{plan['storyboard_id']}:{plan['kind']}:{plan['scene_index']}", correlation_id
    )


def _book_redo(
    engine: Engine,
    plan: dict[str, Any],
    spent: tuple[float, float | None],
    correlation_id: str,
) -> dict[str, Any] | None:
    """A paid redo into the books, measured credits else quoted, under its own reference.

    Until 2026-10-02 a redo wrote only its event: 340 credits off the account, no cost row,
    and the day's budget at 0 (MONEY-02)."""
    from app.media.shooting_sheet import book_purchase  # noqa: PLC0415 - it imports us

    quoted, measured = spent
    credits = measured if measured is not None else quoted
    return book_purchase(
        engine,
        storyboard_id=str(plan["storyboard_id"]),
        step=f"{plan['kind']}_redo",
        reference=_redo_reference(plan, correlation_id),
        credits=float(credits) if credits is not None else None,
        measured=measured is not None,
        credit_usd=float(plan["credit_usd"]),
        correlation_id=correlation_id,
        attribution={"plan_hash": plan["plan_hash"], "scene_index": plan["scene_index"]},
        billing_provider=str(plan.get("billing_provider") or "runway"),
    )


def _redo_interrupted(
    engine: Engine,
    plan: dict[str, Any],
    meter: SpendMeter,
    error: BaseException,
    correlation_id: str,
) -> None:
    """A paid redo that raised after it may have paid: what it committed is booked, the
    Owner has his letter, and the error goes up as `SpentStageError` (never retried)."""
    if not meter.attempts or meter.committed <= 0:
        return
    from app.media.shooting_sheet import book_interrupted_step  # noqa: PLC0415 - it imports us

    booked = book_interrupted_step(
        engine,
        str(plan["storyboard_id"]),
        f"{plan['kind']}_redo",
        reference=_redo_reference(plan, correlation_id),
        credits=float(meter.committed),
        measured=False,
        credit_usd=float(plan["credit_usd"]),
        error=error,
        correlation_id=correlation_id,
        attribution={"plan_hash": plan["plan_hash"], "scene_index": plan["scene_index"]},
        billing_provider=str(plan.get("billing_provider") or "runway"),
    )
    raise SpentStageError(
        f"Refacerea scenei {plan['scene_index']} s-a oprit după ce a cumpărat "
        f"({meter.committed:.0f} credite); nu se reia automat.",
        storyboard_id=str(plan["storyboard_id"]),
        step=f"{plan['kind']}_redo",
        credits=float(meter.committed),
        booked=booked,
    ) from error


def _free_redo(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    plan: dict[str, Any],
    *,
    ffmpeg_path: str | None,
    registry: Any = None,
    note: str | None = None,
    requester: str = "video_editor",
) -> dict[str, Any]:
    """A card or the sound, redone for 0 credits on the newest film. The sound redo carries
    ``registry``, ``note`` and ``requester`` to `repair_audio`: a mix quality control refused is
    planned again by the Voice Artist, told who asked and why."""
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
            engine,
            plan["base_asset_id"],
            correlation_id,
            ffmpeg_path=ffmpeg_exe,
            registry=registry,
            note=note,
            requester=requester,
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


#: A still redo pressed while pictures of the scene, already paid for, waited for judgement:
#: they were judged first, free, and one was approved; nothing was bought.
PAID_PICTURES_JUDGED = "PAID_PICTURES_JUDGED"


def _judge_paid_stills_first(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    index: int,
    *,
    image_adapter: Any,
    storage_root: Path | None,
    judging: bool = True,
    **wiring: Any,
) -> str | None:
    """The scene's paid, unjudged still candidates (and its accepted tasks, collected by id)
    judged by the stills gate before anything is bought; nothing here buys or asks a yes.

    Returns the Owner's reason when the gate approved one of them (the press ends there),
    or None when there was nothing waiting or nothing passed (the redo goes on as asked).

    ``judging`` False: the redo's plan rewrites the scene's prompt (`_scene_prompt_rewrite`).
    The pictures waiting were bought on the stored words it retires, and the gate would judge
    them against those words (review 2026-10-09: on babcf272 the vision check matched a
    triptych to a plan of three moments), so one could end the press as the scene's still,
    with nothing rewritten, against the plan he was shown. Its accepted tasks are only
    collected (free, by id: nothing paid is lost) and nothing is judged; the redo goes on
    and buys on the new words, and the old pictures stay PAID and unjudged under the identity
    the rewrite leaves."""
    from app.media import stills_stage as stills  # noqa: PLC0415 - stills_stage imports us

    def approved_and_waiting() -> tuple[set[str], bool]:
        with Session(engine) as session:
            rows = session.scalars(
                select(SceneTake).where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.scene_number == index,
                    SceneTake.kind == "still",
                    SceneTake.status.in_(("APPROVED", "PAID", "SUBMITTED")),
                )
            ).all()
            approved = {row.id for row in rows if row.status == "APPROVED"}
            waiting = any(
                row.status == "SUBMITTED"
                or (row.status == "PAID" and row.failure_code == UNJUDGED_FAILURE_CODE)
                for row in rows
            )
            return approved, waiting

    from app.media.shooting_sheet import FilmBusy, film_purchase_lease  # noqa: PLC0415

    before, waiting = approved_and_waiting()
    if not waiting:
        return None
    try:
        # Under the film's purchase lease: a buyer at work polls its own tasks, and a second
        # collector beside it would land the same candidates twice.
        with film_purchase_lease(engine, storyboard_id, holder=correlation_id, step=REDO_STEP):
            if not judging:
                collect_submitted_takes(
                    engine,
                    collector_for=lambda _take: image_adapter,
                    correlation_id=correlation_id,
                    storyboard_id=storyboard_id,
                    kinds=("still",),
                    storage_root=storage_root,
                )
                return None
            stills.settle_stills(
                engine,
                storyboard_id,
                correlation_id,
                image_adapter=image_adapter,
                storage_root=storage_root,
                **{key: value for key, value in wiring.items() if value is not None},
            )
    except FilmBusy:
        return None  # the redo itself is refused FILM_BUSY under the same lease
    after, _waiting = approved_and_waiting()
    if not after - before:
        return None
    return (
        f"Scena {index} avea imagini deja plătite, ridicate de la furnizor și încă nejudecate: "
        "au fost judecate acum, fără plată, și una a fost aprobată. Nu s-a cumpărat nimic; "
        "dacă tot vrei alta, apasă din nou «Refă»."
    )


def _paid_redo_gate(plan: dict[str, Any], plan_hash: str | None) -> None:
    """The refusals before a paid redo is asked or bought: no plan, a stale plan, nothing to
    buy. The budgets and the film's ceiling are asked next, inside the film's lease
    (`shooting_sheet.check_film_ceiling`, `shooting_sheet.hold_step_budget`), and a budget the
    cap would exceed is refused there without the Owner's explicit consent."""
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
            # The takes it retired and gave back after it delivered nothing usable.
            **(
                {"given_back": list(detail["given_back"]["restored"])}
                if detail.get("given_back")
                else {}
            ),
            # A still redo's balance before and after, read by the film that uses it
            # (film_step_spend); a motion redo's are on its own motion step's event.
            **(
                {
                    "balance_before": (detail.get("still") or {}).get("balance_before"),
                    "balance_after": (detail.get("still") or {}).get("balance_after"),
                }
                if plan["kind"] == "still"
                else {}
            ),
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
    environment: str = "PRODUCTION",
) -> dict[str, Any] | None:
    """The film rejoined with the redone shot, when one landed, clip QC accepted it and a
    film exists. A shot nobody could check is cut into a TEST film only; in PRODUCTION it
    waits for the Owner's look and the film is assembled again from the approved takes."""
    index = int(plan["scene_index"])
    entry: dict[str, Any] = next((e for e in summary["scenes"] if e["scene_index"] == index), {})
    if entry.get("status") != "PAID" or plan["base_asset_id"] is None:
        return None
    verdict = (entry.get("clip_qc") or {}).get("verdict")
    if verdict == "FAILED" or (verdict != "PASSED" and environment == "PRODUCTION"):
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
        # The redo bought its narration's length (`clip_plan`), not the plan's.
        "asked_seconds": float(plan.get("billed_seconds") or motion_seconds(scene)),
        "scene_category": scene_kind_of(scene),
        "story_purpose": scene.get("story_purpose"),
        "reused_take": False,
        "redo": True,
        "take_id": entry.get("take_id"),
        "take_status": take_status,
        "estimated_credits": entry.get("credits_quoted"),
        "bytes": clip.stat().st_size,
        "clip_qc": entry.get("clip_qc"),
    }
    try:
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
    except SceneRedoRefused as exc:
        if exc.status != CLIP_SHORT:
            raise
        # The redo is bought and booked; its clip is too short to be slowed into the film's
        # span. The film is not rejoined with it: the next assembly from takes reads it
        # (`clip_readiness`), refuses its scene and the studio raises its redo again.
        logger.warning(
            "redo_clip_too_short",
            extra={"storyboard_id": storyboard_id, "scene_index": index, "reason": exc.reason_ro},
        )
        return None


#: Why a still redo stopped with its request accepted and its pictures not yet delivered.
REDO_IN_FLIGHT_REASON = (
    "Scena {scene}: furnizorul a primit cererea plătită a refacerii, dar imaginile nu au sosit "
    "la timp; se ridică mai târziu după numărul sarcinii, fără plată, și nu se cumpără din nou."
)


def _redo_next_step(
    plan: dict[str, Any], film: dict[str, Any] | None, detail: dict[str, Any]
) -> str:
    """What happens next, in one Romanian line for the Owner."""
    index = plan["scene_index"]
    if detail.get("given_back"):
        return given_back_ro(detail["given_back"])
    if plan["kind"] == "still":
        if (detail.get("still") or {}).get("status") == "IN_FLIGHT":
            return (
                f"Imaginile scenei {index} se ridică de la furnizor fără plată când sunt gata "
                "(paznicul studioului întreabă de ele); apoi sunt judecate și apar pe foaia de "
                "filmare. Scena nu se cumpără din nou până atunci."
            )
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


@purchase_flow
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
    meter: SpendMeter | None = None,
    unasked: bool = False,
    director_repair: bool = False,
) -> Generator[RoundWork, dict[str, Any], dict[str, Any]]:
    """One scene's still bought again: one pair of candidates (at most two re-rolls within the
    cap), judged as the stills step judges them, under the Owner's yes for this redo.

    Bought on the words today's compiler writes for the scene (`_scene_prompt_rewrite`), the
    words his plan showed; when they are not the stored ones, the scene's package is rewritten
    in the transaction that spends his yes (`_rewrite_scene_prompts`), and no other scene's."""
    from app.media import stills_stage as stills  # noqa: PLC0415 - stills_stage imports us
    from app.media.mode_guard import PurchaseGuard, unasked_refusal  # noqa: PLC0415
    from app.media.prompt_lint import bible_face_rule  # noqa: PLC0415
    from app.services import may_act  # noqa: PLC0415

    index = int(plan["scene_index"])
    if image_adapter is None:
        raise SceneRedoRefused(
            "NO_ADAPTER",
            "Niciun model de imagine conectat și verificat; imaginea nu se poate cumpăra.",
            plan=plan,
        )
    from app.providers.runpod.batch import supports_batch  # noqa: PLC0415 - runpod reads media

    # RunPod Serverless buys only in rounds inside a GPU session (2026-10-09): the redo is
    # bought as the stills step buys, one scene in one GPU round (`_redo_still_rounds`).
    batching = supports_batch(image_adapter)
    # Her reading of an older brief's words before the redo's stills are checked for them
    # (free; `fix_check.read_film_reasons`, the review of 5fc7468, finding 11).
    from app.media.fix_check import read_film_reasons  # noqa: PLC0415

    read_film_reasons(engine, registry, storyboard_id=storyboard_id, correlation_id=correlation_id)
    bible, scenes = stills._read_scenes(engine, storyboard_id)
    scene = next(s for s in scenes if s.index == index)
    live = [s for s in scenes if s.kind == LIVE_KIND]
    # The words bought are the words the Owner's plan showed (2026-10-09, film babcf272): the
    # scene compiled again as its plan was, and refused when they are no longer the plan's.
    # The still model the plan was priced on, else the adapter's (`redo_scene`'s stills_model):
    # a plan without one (a locked character's refusal test, 2026-10-10) used to stop on a
    # KeyError instead of its own refusal.
    model_id = str(plan.get("model_id") or getattr(image_adapter, "model", None) or STILLS_MODEL)
    with Session(engine) as session:
        rewrite = _scene_prompt_rewrite(session, storyboard_id, index, model_id)
    if (rewrite or {}).get("still_prompt") != (plan.get("prompt_rewrite") or {}).get(
        "still_prompt"
    ):
        raise SceneRedoRefused(
            "STALE_PLAN",
            f"Promptul imaginii scenei {index} nu mai este cel din planul arătat: nu se cumpără "
            "nimic. Deschideți refacerea din nou și aprobați planul de acum.",
            plan=plan,
        )
    if rewrite is not None:
        # This one scene, as it will be stored: the new words, the identity its still is
        # recorded under, its look and its camera move (for the gate's checks).
        scene.words = str(rewrite["still_prompt"])
        scene.identity = still_fields(str(rewrite["visual_prompt"]), scene.reference)
        scene.look_block = str(rewrite["package"].get("look_block") or "")
        scene.camera_move = str(rewrite["package"].get("camera_move") or "")
        from app.media.prompt_agent import incomplete_plan_fields  # noqa: PLC0415

        scene.prompt_issues = tuple(incomplete_plan_fields(rewrite["package"], layers=("still",)))
    if environment == "PRODUCTION" and scene.source not in shot_plan_sources(engine, storyboard_id):
        raise SceneRedoRefused(
            "NEEDS_SHOT_PLAN",
            f"Scena {index} nu are promptul scris de model din planul de cadre; nu se cumpără "
            "imagini din prompturi-șablon.",
            plan=plan,
        )
    if scene.needs_reference:
        raise SceneRedoRefused(
            "NEEDS_REFERENCE",
            stills.needs_reference_reason(
                [{"scene_index": index, "reason_ro": scene.needs_reference}]
            ),
            plan=plan,
        )
    from app.media.factory import accepts_reference_image  # noqa: PLC0415 - factory reaches us

    if (
        scene.reference is not None
        and scene.reference.get("required")
        and not accepts_reference_image(image_adapter)
    ):
        # The stills step's rule, here too (adversary 2026-10-09): a locked face is never
        # redrawn from words by a model that cannot take its reference picture.
        raise SceneRedoRefused(
            "NEEDS_REFERENCE",
            f"Scena {index} arată un personaj cu înfățișarea blocată, iar modelul de imagine "
            "conectat nu poate primi imaginea lui de referință: nu se cumpără o imagine desenată "
            "din cuvinte pentru un chip fixat. Alegeți un model care primește imagini de "
            "referință.",
            plan=plan,
        )
    findings = lint_film(
        [
            LintScene(
                scene=index,
                kind=LIVE_KIND,
                still_prompt=scene.words,
                contract={"still_model_id": model_id},
                composition_issues=scene.prompt_issues,
            )
        ],
        bible=bible,
    )
    if has_block(findings):
        blocks = [f for f in findings if f.severity == "BLOCK"]
        raise SceneRedoRefused(
            "LINT_BLOCKED",
            summary_ro(findings) + " " + " ".join(f.message_ro for f in blocks[1:4]),
            plan=plan,
            findings=blocks,
        )
    if batching:
        # A GPU that could not be switched on anyway (his card not accepted, no bucket, the
        # weights not ready) refuses here, before his yes is asked for or spent (as the
        # stills step does): nothing sent, nothing spent.
        from app.media import gpu_batch  # noqa: PLC0415 - gpu_batch reads runpod
        from app.providers.runpod.gpu_session import GpuSessionRefused  # noqa: PLC0415

        try:
            gpu_batch.gpu_precheck(
                engine, image_adapter, purpose="image", integration_id=integration_id
            )
        except GpuSessionRefused as exc:
            raise SceneRedoRefused(str(exc.code), exc.reason_ro, plan=plan) from exc
    cap = int(plan["cap_credits"])
    margin = margin_of(settings)
    asked_about = {"plan_hash": plan_hash, "cap_credits": cap}
    if unasked:
        # Unasked, the Owner's mode is asked before his balance (2026-10-04).
        refused = unasked_refusal(
            engine,
            REDO_ACTION,
            subject=storyboard_id,
            context=asked_about,
            cost_usd=plan["cap_usd"],
            requester=requester,
        )
        if refused is not None:
            raise SceneRedoRefused(str(refused["status"]), str(refused["reason"]), plan=plan)
    read, before, problem = stills._read_balance(image_adapter)
    if problem is not None:
        raise SceneRedoRefused(LOW_BALANCE, f"Nu se cumpără imagini: {problem}.", plan=plan)
    # The Owner's rule (2026-10-03): the redo starts on its one purchase (a pair of candidates)
    # x the margin; each re-roll reads the balance again, and the cap stays the ceiling.
    one_purchase = int(plan["credits"])
    if before is not None and before < needed_credits(one_purchase, margin):
        raise SceneRedoRefused(
            LOW_BALANCE,
            start_refusal_ro(
                before, one_purchase, cap, margin, f"refacerii imaginii scenei {index}"
            ),
            plan=plan,
        )
    evidence = (
        f"imaginea scenei {index}: {STILL_CANDIDATES} variante la 2K, "
        f"{plan['credits']} credite, plafon {cap}; cost estimat "
        f"{_usd_ro(plan['cost_usd'])}, plafon {_usd_ro(plan['cap_usd'])}"
    )
    if rewrite is not None:
        # His card says what his yes buys (review 2026-10-09): the governance window shows
        # only the evidence, and a repair nobody pressed (the day's QC) reaches him only there.
        evidence = f"{evidence}. {_rewrite_note_ro(plan['prompt_rewrite'])}"
    with Session(engine) as session, session.begin():
        verdict = may_act(
            session,
            REDO_ACTION,
            requester=requester,
            subject=storyboard_id,
            evidence=evidence,
            # The redo's cap, with its re-rolls (MONEY-08): what OVER_USD compares.
            cost_usd=plan["cap_usd"],
            context=asked_about,
        )
        if verdict["allowed"]:
            if rewrite is not None:
                # The scene's package is rewritten with the yes that buys on it, or not at
                # all: a package changed meanwhile rolls this back and the yes stays unspent.
                _rewrite_scene_prompts(
                    session,
                    storyboard_id,
                    rewrite,
                    plan=plan,
                    plan_hash=plan_hash,
                    correlation_id=correlation_id,
                )
            # The yes is spent and the old picture retired together, with every shot that
            # started from it: a shot never outlives the still it was filmed from. What the
            # Owner approved himself is retired only by his own press, or his yes for this
            # plan (2026-10-10, babcf272): unasked and without it, this raises and rolls back
            # the rewrite and the yes with it.
            his = not unasked or _owner_yes_for_redo(
                session, storyboard_id, plan_hash, cap, verdict
            )
            _retire_takes(
                session,
                list(plan["replaces"]),
                REDO_FAILURE_CODE,
                note or "Proprietarul a cerut o imagine nouă pentru această scenă.",
                correlation_id,
                redo_kind="still",
                owner_press=his,
                plan_hash=plan_hash,
                director_repair=director_repair,
            )
            _retire_takes(
                session,
                list(plan["invalidates"]),
                REDO_STILL_REPLACED,
                f"Cadrul a fost filmat din imaginea veche a scenei {index}, înlocuită la cererea "
                "Proprietarului; nu se mai folosește.",
                correlation_id,
                redo_kind="still",
                owner_press=his,
                plan_hash=plan_hash,
                director_repair=director_repair,
            )
    if not verdict["allowed"]:
        raise SceneRedoRefused(
            str(verdict["status"]),
            str(verdict["reason"]),
            approval_id=verdict.get("approval_id"),
            plan=plan,
        )
    # The same question again before every re-roll, never spending (spec 51).
    guard = PurchaseGuard.after(
        engine,
        verdict,
        action=REDO_ACTION,
        step=REDO_STEP,
        storyboard_id=storyboard_id,
        requester=requester,
        cost_usd=plan["cap_usd"],
        context=asked_about,
        unasked=unasked,
        correlation_id=correlation_id,
        timezone=getattr(settings, "timezone", None),
    )

    first = live[0] if live else None
    figure_one: bytes | None = None
    if first is not None and first.index != index and first.reuse is not None and first.reuse.path:
        figure_one = Path(str(first.reuse.path)).read_bytes()
    if batching:
        rounds = yield from flow_call(
            _redo_still_rounds,
            engine,
            storyboard_id,
            correlation_id,
            plan,
            scene=scene,
            bible=bible,
            first_index=first.index if first is not None else None,
            figure_one=figure_one,
            image_adapter=image_adapter,
            plan_hash=plan_hash,
            verdict=verdict,
            guard=guard,
            registry=registry,
            judge=judge,
            face_counter=face_counter,
            measure=measure,
            environment=environment,
            ffmpeg_path=ffmpeg_path,
            storage_root=storage_root,
            integration_id=integration_id,
            requester=requester,
            meter=meter,
            unasked=unasked,
        )
        return {**rounds, "prompt_rewritten": rewrite is not None}
    # The character's reference first (when the vendor takes one), the film's look second.
    references, with_character, with_figure = stills._references(
        scene, figure_one, image_adapter, first=first is None or first.index == index
    )
    # The stills step's one plan builder (`stills_stage._still_plan`): the scene's written
    # picture and what its words were rewritten to fix go with every candidate of the redo.
    still_plan = stills._still_plan(
        scene, faces_forbidden=bible_face_rule(bible) is not None, rules=stills._bible_rules(bible)
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
        references=references,
        with_character=with_character,
        with_figure=with_figure,
        still_plan=still_plan,
        image_adapter=image_adapter,
        registry=registry,
        judge=judge,
        face_counter=face_counter,
        measure=measure,
        environment=environment,
        ffmpeg_path=ffmpeg_path,
        work_dir=work_dir,
        before=before,
        meter=meter,
        margin=margin,
        guard=guard,
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
        **({"director_confirmed": list(buyer.confirmed)} if buyer.confirmed else {}),
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
        # The scene's prompts compiled again and stored with this redo (2026-10-09).
        "prompt_rewritten": rewrite is not None,
    }


@purchase_flow
def _redo_still_rounds(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    plan: dict[str, Any],
    *,
    scene: Any,
    bible: dict[str, Any],
    first_index: int | None,
    figure_one: bytes | None,
    image_adapter: Any,
    plan_hash: str,
    verdict: dict[str, Any],
    guard: Any,
    registry: Any,
    judge: Callable[..., Any] | None,
    face_counter: Callable[..., Any] | None,
    measure: tuple[str, ...] | None,
    environment: str,
    ffmpeg_path: str | None,
    storage_root: Path | None,
    integration_id: str | None,
    requester: str,
    meter: SpendMeter | None,
    unasked: bool,
) -> Generator[RoundWork, dict[str, Any], dict[str, Any]]:
    """One scene's still redo on RunPod Serverless (2026-10-09): the stills step's own rounds
    (`stills_stage._StillRounds`, `gpu_batch.run_rounds`) for this one scene, under the yes
    `_redo_still` has just spent. The synchronous call opens one session; the Director's
    prepared flow combines compatible ready redos while retaining this purchase's own guard,
    cap and budget hold. The session is authorised by every participating permit (the kernel's
    ``infra.gpu_on`` for ``media.scene_redo``, this plan, this approval) and off right after its
    last result; each round (the pair, then a re-roll) is one batch job, priced with its GPU
    start and cut to what is left of the redo's cap; his mode and the autonomy stop are read
    before every round (``guard``); the film's purchase lease and the step's budget hold are
    `redo_scene`'s. A /run with no answer is proven unsent or held, as in the stills step."""
    from app.media import stills_stage as stills  # noqa: PLC0415 - stills_stage imports us
    from app.media.picture_qc import judge_still  # noqa: PLC0415
    from app.media.prompt_lint import bible_face_rule  # noqa: PLC0415
    from app.media.still_gate import ALL_CHECKS  # noqa: PLC0415
    from app.providers.runpod.gpu_session import StepPermit  # noqa: PLC0415
    from app.runbook.services import stop_requested  # noqa: PLC0415

    index = int(scene.index)
    cap = int(plan["cap_credits"])
    per_request = int(plan.get("credits_per_request") or plan["credits"])
    work_dir = (storage_root or DEFAULT_STORAGE_ROOT) / storyboard_id / "stills"
    work_dir.mkdir(parents=True, exist_ok=True)
    ledger = stills._Ledger(cap=cap, meter=meter if meter is not None else SpendMeter())
    rounds = stills._StillRounds(
        engine=engine,
        storyboard_id=storyboard_id,
        correlation_id=correlation_id,
        adapter=image_adapter,
        model_id=str(plan["model_id"]),
        # The scene goes as the film's first when it is, or while the film has no Figure 1
        # (the per-request redo's rule): it is never left waiting for a scene not bought here.
        first_live=index if first_index in (None, index) or figure_one is None else first_index,
        figure_one=figure_one,
        per_image=per_request / STILL_CANDIDATES,
        overhead=float(plan.get("round_overhead_credits") or 0),
        credit_usd=float(plan["credit_usd"]),
        ledger=ledger,
        # His press is his decision on the scene: the redo's own bound is its cap (the pair
        # and its re-rolls), not the attempt limit of a step nobody pressed.
        limit=10**9,
        work_dir=work_dir,
        environment=environment,
        registry=registry,
        judge=judge or judge_still,
        face_counter=face_counter,  # type: ignore[arg-type]
        measure=measure or ALL_CHECKS,
        ffmpeg_path=ffmpeg_path,
        faces_forbidden=bible_face_rule(bible) is not None,
        rules=stills._bible_rules(bible),
        redo=True,
    )
    entry: dict[str, Any] = {"scene_index": index, "scene_kind": LIVE_KIND}
    try:
        gpu = yield from flow_call(
            rounds.run,
            [(scene, entry)],
            permit=StepPermit.from_guard(
                guard,
                verdict,
                action=REDO_ACTION,
                step=REDO_STEP,
                storyboard_id=storyboard_id,
                plan_hash=plan_hash,
                requester=requester,
                correlation_id=correlation_id,
                integration_id=integration_id,
                unasked=unasked,
            ),
            guard=guard,
            stopped=lambda: render_stop_reason(engine) if stop_requested(engine) else None,
        )
    except MediaProviderError as exc:
        if not exc.unsent:
            raise
        # The GPU was not switched on, or the round could not even be sent: nothing bought.
        raise SceneRedoRefused(
            str(exc.code or "COMPUTE_NOT_READY"),
            str(getattr(exc, "reason_ro", None) or exc),
            plan=plan,
        ) from exc
    state = rounds.states.get(index)
    kept = ("status", "reason", "reasons", "take_id", "score", "failure_kind", "failure_code")
    return {
        **{key: entry[key] for key in kept if key in entry},
        "scene_index": index,
        "model_id": plan["model_id"],
        "rerolls": state.rerolls if state is not None else 0,
        "bought_images": ledger.images,
        "spent_credits_quoted": round(ledger.committed, 4),
        "spent_credits_measured": None,
        "balance_before": None,
        "balance_after": None,
        "cap_credits": cap,
        "retired": list(plan["replaces"]),
        "invalidated": list(plan["invalidates"]),
        "reference_unverified": rounds.unverified,
        "gpu": gpu,
    }


class _StillRedoBuyer:
    """The purchase loop of one scene's still redo, the stills step's rules for one scene:
    the cap and the balance before every request, the local checks before the vision model,
    at most two re-rolls with the violations as positive words, then the Owner."""

    def __init__(self, **context: Any) -> None:
        #: What the redo has sent and committed, read by `redo_scene` whatever happens.
        self.meter: SpendMeter = context.pop("meter", None) or SpendMeter()
        self.context = context
        self.images = 0
        self.take_ids: list[str] = []
        self.rerolls = 0
        self.unverified = False
        #: The Director's reasons where her look confirmed a refusal before a re-roll.
        self.confirmed: list[str] = []

    @property
    def committed(self) -> float:
        return self.meter.committed

    @committed.setter
    def committed(self, value: float) -> None:
        self.meter.committed = value

    def run(self) -> dict[str, Any]:
        from app.media import stills_stage as stills  # noqa: PLC0415 - stills_stage imports us
        from app.media.picture_qc import judge_still  # noqa: PLC0415
        from app.media.still_gate import ALL_CHECKS  # noqa: PLC0415
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
                outcome = {"status": "NOT_BOUGHT", "reason": render_stop_reason(engine)}
                break
            guard = c.get("guard")
            lowered = guard.stop_reason(index) if guard is not None else None
            if lowered is not None:
                # His mode or rule changed while the redo ran: no further re-roll is bought.
                outcome = {"status": "NOT_BOUGHT", "reason": lowered}
                break
            if self.committed + per_request > c["cap"]:
                outcome = {
                    "status": "NOT_BOUGHT",
                    "reason": f"STOPPED_AT_CAP: încă o cerere ({per_request} credite) ar depăși "
                    f"plafonul aprobat de {c['cap']} credite (deja {self.committed:.0f}).",
                }
                break
            _read, balance, problem = stills._read_balance(c["image_adapter"])
            if problem is not None:
                outcome = {
                    "status": "NOT_BOUGHT",
                    "reason": f"Nu se mai cumpără imagini: {problem}.",
                }
                break
            margin = float(c.get("margin") or PAID_STEP_BALANCE_MARGIN)
            if balance is not None and balance < needed_credits(per_request, margin):
                # The Owner's rule (2026-10-03): each purchase of the redo reads the balance.
                reason = purchase_stop_ro(
                    index,
                    balance,
                    per_request,
                    margin,
                    "reluarea imaginilor" if self.rerolls or retried else "imaginile refacerii",
                )
                outcome = {
                    "status": "NEEDS_OWNER",
                    "reason": reason,
                    "failure_kind": LOW_BALANCE,
                    "low_balance": low_balance_record(index, balance, per_request, margin, reason),
                }
                break
            drop = uncounted_drop(c.get("before"), balance, self.committed)
            if drop is not None:
                outcome = {
                    "status": "NOT_BOUGHT",
                    "reason": UNCOUNTED_DROP_STOP.format(drop=drop, committed=self.committed),
                }
                break
            prompt = stills._prompt(
                scene,
                instruction,
                bool(c.get("with_figure", c["references"])),
                with_character=bool(c.get("with_character", False)),
            )
            # (take id, task id) of each task the vendor accepted for this request: on the
            # books, SUBMITTED with the vendor's id, the moment it is accepted and before any
            # poll (as the stills step does). Until 2026-10-03 the redo kept the id in memory
            # only: the Owner's redo of scene 3 was charged 18 credits and left no record.
            intents: list[tuple[str | None, str]] = []

            def submitted(
                task_id: str,
                *,
                _identity: str = identity,
                _intents: list[tuple[str | None, str]] = intents,
            ) -> None:
                _intents.append((self._intent(_identity, task_id, per_request), task_id))

            self.meter.attempts += 1
            try:
                bind_scene(c["image_adapter"], c["storyboard_id"], index, "image")
                candidates, quoted = stills._buy(
                    c["image_adapter"],
                    prompt,
                    c["references"],
                    STILL_CANDIDATES,
                    on_submitted=submitted,
                )
            except TaskStillOpen as exc:
                # Accepted (and charged) and not delivered in time: the takes stay SUBMITTED
                # with their task ids and are collected later, free (the watchdog, the next
                # stills step); nothing more is bought, and this request is never sent again.
                if not intents:
                    intents.append((self._intent(identity, exc.task_id, per_request), exc.task_id))
                self.committed += per_request
                outcome = {
                    "status": "IN_FLIGHT",
                    "reason": REDO_IN_FLIGHT_REASON.format(scene=index),
                    "take_ids": [take for take, _task in intents if take],
                    "task_ids": [task for _take, task in intents],
                }
                break
            except MediaProviderError as exc:
                failure = classify_vendor_failure(exc, previous_kind)
                previous_kind = failure.kind
                charged = possibly_charged(exc, submitted=bool(intents))
                # A request with no task heard and no answer: its outcome is unknown, so it is
                # counted and never sent again automatically.
                unknown = outcome_unknown(exc, submitted=bool(intents))
                if charged:
                    self.committed += per_request  # a refusal may be paid like a success
                for intent_take, _task in intents or [(None, "")]:
                    self._take(
                        identity,
                        "REFUSED",
                        exc=exc,
                        quoted=float(per_request) if charged else None,
                        code=UNANSWERED_FAILURE_CODE if unknown else None,
                        take_id=intent_take,
                    )
                if failure.kind in stills.RETRY_KINDS and not retried and not unknown:
                    retried = True
                    continue
                if failure.kind == STUDIO_DEFECT_KIND and not unknown:
                    # Our request was wrong: no hold for the Owner, no re-roll of the defect.
                    outcome = {
                        "status": "NOT_BOUGHT",
                        "reason": f"Scena {index}: {failure.reason_ro}",
                        "failure_kind": failure.kind,
                        "failure_code": failure_code_of(exc),
                    }
                    break
                outcome = {
                    "status": "NEEDS_OWNER",
                    "reason": UNANSWERED_REASON.format(scene=index)
                    if unknown
                    else f"Scena {index}: {failure.reason_ro} Decide Proprietarul pe foaia "
                    "de filmare; aceleași cuvinte nu se trimit din nou.",
                    "failure_kind": "UNANSWERED" if unknown else failure.kind,
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
            open_intents = list(intents)
            for number, candidate in enumerate(candidates):
                suffix = candidate.format if candidate.format in ("png", "jpeg", "webp") else "png"
                path = c["work_dir"] / (
                    f"scene_{index:02d}_redo_{uuid4().hex[:8]}_c{number + 1}."
                    + ("jpg" if suffix == "jpeg" else suffix)
                )
                path.write_bytes(candidate.image_bytes)
                self.images += 1
                raw = candidate.raw_response if isinstance(candidate.raw_response, dict) else {}
                intent_take, task_id = stills._claim_intent(
                    open_intents, raw.get("task_id"), [task for _take, task in intents]
                )
                # PAID and UNJUDGED until the gate below has looked, as in the stills step: a
                # process that dies in between leaves a candidate judged later, not re-bought.
                take_id = self._take(
                    identity,
                    "PAID",
                    path=path,
                    data=candidate.image_bytes,
                    quoted=share,
                    take_id=intent_take,
                    task_id=task_id,
                    code=UNJUDGED_FAILURE_CODE,
                    detail=UNJUDGED_DETAIL,
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
            for intent_take, _task in open_intents:
                # A task the vendor accepted that handed over nothing: refused, on its own row.
                if intent_take:
                    self._take(
                        identity,
                        "REFUSED",
                        take_id=intent_take,
                        code=stills.NO_OUTPUT_CODE,
                        detail="Furnizorul a încheiat sarcina fără nicio imagine.",
                    )
            # Judged as the stills step judges a round (2026-10-12): the gate's best, else the
            # Director's look before any re-roll is bought, else the next step.
            end = stills._settle_round(
                engine,
                c["registry"],
                c["storyboard_id"],
                scene,
                verdicts,
                c["correlation_id"],
                rerolls=self.rerolls,
            )
            if end.report is not None:
                outcome = end.approved()
                break
            if end.again:
                self.rerolls += 1
                instruction = end.instruction
                if end.confirmed:
                    self.confirmed.extend(end.confirmed)
                continue
            outcome = dict(end.outcome or {})
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
                    "failure_kind": outcome.get("failure_kind"),
                    "identity": identity_key(scene.identity),
                    # A redo the balance stopped waits for his top-up, not for his decision.
                    "holds": outcome.get("failure_kind") != LOW_BALANCE,
                    # Her ladder rewrites the words (the review of 5fc7468, finding 3).
                    **({"rewrite": True} if outcome.get("rewrite") else {}),
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
        code: str | None = None,
        detail: str | None = None,
        take_id: str | None = None,
        task_id: str | None = None,
    ) -> str:
        from app.media.stills_stage import STILL_RATIO  # noqa: PLC0415

        c = self.context
        written = record_take(
            c["engine"],
            take_id=take_id,
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
            failure_code=(failure_code_of(exc) or code) if exc is not None else code,
            failure_detail=failure_detail_of(exc) if exc is not None else detail,
            remote_task_id=task_id,
        )
        if written not in self.take_ids:
            self.take_ids.append(written)
        return written

    def _intent(self, identity: str, task_id: str, per_request: int) -> str | None:
        """The SUBMITTED take of a task the vendor just accepted (`_record_intent`)."""
        from app.media.stills_stage import STILL_RATIO  # noqa: PLC0415

        c = self.context
        written = _record_intent(
            c["engine"],
            task_id,
            storyboard_id=c["storyboard_id"],
            scene_number=int(c["scene"].index),
            kind="still",
            prompt_hash=identity,
            model_id=c["model_id"],
            resolution=STILL_RATIO,
            correlation_id=c["correlation_id"],
            credits=float(per_request),
        )
        if written and written not in self.take_ids:
            self.take_ids.append(written)
        return written


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
            lock_for_write(session)
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
