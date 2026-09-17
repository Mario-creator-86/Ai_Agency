"""Deterministic Video Assembler & FFmpeg Engine.

Following docs/architecture/08_VIDEO_PIPELINE.md:
- Generates timed SRT/VTT subtitles.
- Assembles vertical 9:16 video (1080x1920) with deterministic fallback.
- Uses safe subprocess argument arrays without shell interpolation.
- Calculates SHA-256 byte digest for absolute asset provenance.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
import subprocess
import time
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import ROOT
from app.media.models import MediaAsset, Storyboard, StoryboardScene, VideoRenderJob
from app.media.production_policy import record_quoted_price
from app.media.toolchain import (
    LOUDNESS_TARGET_LUFS,
    TRUE_PEAK_TARGET_DBTP,
    find_ffmpeg,
    has_filter,
    loudnorm_filter,
    measure_loudness,
    parse_loudnorm_json,
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

#: How long one shot dissolves into the next. Long enough to read as a film, short enough
#: that a forty-five second short does not spend its time in transitions.
TRANSITION_SECONDS = 0.4

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
#: captioning and the platforms' own caption editors share. A longer line either shrinks the
#: type below what a phone shows or wraps a third line up into the picture.
CAPTION_LINE_CHARS = 42
CAPTION_MAX_LINES = 2

#: How a burnt caption is drawn, as libass style overrides. ffmpeg hands an SRT to libass at
#: its default script resolution of 384x288, so every size here is in those units and scales
#: with the frame: on a 1080x1920 film FontSize 7.5 is a 50-pixel line, which is what lets a
#: forty-two character line fit between the side margins (measured on a frame: bold at 11
#: wrapped a 42-character line in two). MarginV 58 is a fifth of 288, so the text's baseline
#: sits at the top of the bottom fifth — the band the platforms cover with their own
#: controls and caption. BorderStyle 1 is an outline with no box: white type, dark edge.
CAPTION_STYLE = (
    "FontName=Arial,FontSize=7.5,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
    "BorderStyle=1,Outline=0.9,Shadow=0,Alignment=2,MarginV=58,MarginL=10,MarginR=10"
)

#: Where a sentence ends: a terminal mark followed by space. A decimal point or an initial
#: is followed by a letter, not a space, so "3.5 billion" and "J. Webb" stay whole.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


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


def _caption_lines(sentence: str) -> list[str]:
    """A sentence as caption lines: as few as fit, and those of about equal length.

    Greedy wrapping fills the first line and leaves the last one a word or two long; the
    lines are re-wrapped at the width that shares the sentence evenly across the number of
    lines it needs, so a two-line cue reads as two lines and not as a line and a crumb.
    """
    words = sentence.split()
    if not words:
        return []
    needed = len(_wrap_words(words, CAPTION_LINE_CHARS))
    if needed <= 1:
        return [" ".join(words)]
    balanced_width = max(1, math.ceil(len(sentence) / needed))
    for width in range(balanced_width, CAPTION_LINE_CHARS + 1):
        lines = _wrap_words(words, width)
        if len(lines) <= needed:
            return lines
    return _wrap_words(words, CAPTION_LINE_CHARS)


def caption_cues(scenes: list[dict]) -> list[dict[str, Any]]:
    """Caption cues from the narration: one per sentence, timed to each scene's own audio.

    A scene begins where the scenes before it end (their ``duration_seconds``), and its words
    last as long as the narration recorded for it (``audio_seconds``, measured from the voice
    clip; the planned length when nothing was recorded). Inside the scene the sentences share
    that time by their length, so a long sentence stays up longer. A sentence that will not
    fit two lines of forty-two becomes as many consecutive cues as it needs. A scene with no
    words has no cue: a caption is never invented from a visual prompt.
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
        if text and span > 0:
            chunks: list[list[str]] = []
            for sentence in _SENTENCE_END.split(text):
                lines = _caption_lines(sentence)
                for at in range(0, len(lines), CAPTION_MAX_LINES):
                    chunks.append(lines[at : at + CAPTION_MAX_LINES])
            weights = [sum(len(line) for line in chunk) for chunk in chunks]
            total_weight = float(sum(weights)) or 1.0
            start = clock
            elapsed = 0
            for position, (chunk, weight) in enumerate(zip(chunks, weights, strict=True)):
                elapsed += weight
                # The last cue ends exactly where the narration does, whatever rounding the
                # shares before it accumulated.
                end = (
                    clock + span
                    if position == len(chunks) - 1
                    else clock + span * (elapsed / total_weight)
                )
                cues.append(
                    {
                        "scene_index": scene.get("scene_index"),
                        "start": start,
                        "end": end,
                        "lines": chunk,
                    }
                )
                start = end
        clock += planned
    return cues


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
    """Generate valid SubRip (SRT) subtitles, one cue per sentence, timed to the narration."""
    return srt_from_cues(caption_cues(scenes))


def captions_filter(srt_name: str = "captions.srt") -> str:
    """The ffmpeg filter that burns the SRT into the picture.

    The file is named relative to the encoder's working directory on purpose: the filter's
    own option parser reads a colon as a separator, so an absolute Windows path would need
    escaping twice over, and the encode already runs inside the render's folder.
    """
    return f"subtitles=filename={srt_name}:force_style='{CAPTION_STYLE}'"


def _concatenate_audio(ffmpeg_exe: str, segments: list[Path], work_dir: Path) -> Path:
    """Join the per-scene narration files into one track, with ffmpeg rather than by hand.

    The placeholder path can splice raw WAV bodies because it produced them itself and knows
    their format. A provider's audio is whatever the vendor encoded, so it is concatenated by
    the decoder instead of by byte surgery, which would silently corrupt a differing format.
    """
    if not segments:
        raise RenderEngineUnavailable("No narration audio was produced for this storyboard")
    listing = work_dir / "voice_segments.txt"
    listing.write_text(
        "".join(f"file '{segment.as_posix()}'\n" for segment in segments), encoding="utf-8"
    )
    output = work_dir / "master_audio.m4a"
    result = subprocess.run(  # noqa: S603
        [
            ffmpeg_exe,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
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
FIRST_FRAME_QUALITY = "4"


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


def _generate_motion(
    adapter: VideoProvider,
    scene: dict[str, Any],
    still: Path | None,
    seconds: float,
    ffmpeg_exe: str,
) -> tuple[bytes, dict[str, Any]]:
    """Ask the scene's model for its shot, and wait for the clip.

    With a still, the still is the first frame, so the picture the Director approved is the
    picture that moves — that is production. Without one the model films from the scene's
    words, which is what a test does on the cheapest model. A task that has not finished by
    the deadline raises; nothing invents a shot.
    """
    prompt = " ".join(str(scene.get("visual_prompt") or "").split())[:900]
    job_id = asyncio.run(
        adapter.create_generation(
            prompt,
            image_ref=_first_frame(ffmpeg_exe, still, seconds) if still is not None else None,
            duration_seconds=seconds,
            aspect_ratio="9:16",
        )
    )
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
            code = (result.raw_response or {}).get("failure_code")
            raise MediaProviderError(f"the motion task failed ({code or 'no reason given'})")
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
    prompt = " ".join(str(scene.get("visual_prompt") or "").split())[:900]
    try:
        return asyncio.run(
            ask(
                prompt,
                image_ref=_first_frame(ffmpeg_exe, still, seconds) if still is not None else None,
                duration_seconds=seconds,
                aspect_ratio="9:16",
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
                failure_kind=None if landed else "TECHNICAL",
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
    role = str(scene.get("scene_role") or "") or scene_role(
        int(scene.get("scene_index") or 1), total_scenes
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


def _shot_command(
    ffmpeg_exe: str, still: Path, clip: Path | None, span: float, target: Path
) -> list[str]:
    """One scene as one file, exactly `span` long: the generated clip, or the still pushed in.

    A shot is built and measured on its own because a single filter graph over eight inputs
    hid its own failure: the first dissolve render wrote six seconds of picture under
    forty-six seconds of audio and reported success.
    """
    if clip is not None:
        return [
            ffmpeg_exe,
            "-y",
            "-i",
            str(clip),
            "-an",
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,"
            f"tpad=stop_mode=clone:stop_duration={span:.3f},trim=duration={span:.3f},"
            "setpts=PTS-STARTPTS,setrange=pc,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            str(target),
        ]
    frames = max(2, int(round(span * 30)))
    return [
        ffmpeg_exe,
        "-y",
        "-loop",
        "1",
        "-framerate",
        "30",
        "-t",
        f"{span:.3f}",
        "-i",
        str(still),
        "-an",
        "-vf",
        "scale=1188:2112:force_original_aspect_ratio=increase,crop=1188:2112,"
        f"zoompan=z='min(1+0.10*on/{frames},1.10)':d=1:"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,"
        f"trim=duration={span:.3f},setpts=PTS-STARTPTS,setrange=pc,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        str(target),
    ]


def _dissolve_command(
    ffmpeg_exe: str,
    shots: list[Path],
    scenes_data: list[dict[str, Any]],
    audio_file: Path,
    output_mp4: Path,
    *,
    audio_filter: str = "apad",
    captions: str | None = None,
) -> list[str]:
    """One ffmpeg call over the shot files: each dissolves into the next.

    Each shot is one transition longer than its narration and each dissolve consumes exactly
    that overlap, so shot N still starts where scene N's words start — the picture never
    drifts away from the voice. ``audio_filter`` is the whole audio chain (the loudness
    normalisation and the padding); ``captions`` is the subtitles filter to burn in after the
    last dissolve, or None to leave the picture clean.
    """
    args = [ffmpeg_exe, "-y"]
    for shot in shots:
        args += ["-i", str(shot)]
    args += ["-i", str(audio_file)]

    chain = ""
    current = "0:v"
    offset = 0.0
    for index in range(1, len(shots)):
        offset += float(scenes_data[index - 1]["duration_seconds"])
        nxt = f"x{index}"
        chain += (
            f"[{current}][{index}:v]xfade=transition=fade:"
            f"duration={TRANSITION_SECONDS:.3f}:offset={offset:.3f}[{nxt}];"
        )
        current = nxt
    total = sum(float(s["duration_seconds"]) for s in scenes_data)
    burn = f",{captions}" if captions else ""
    if chain:
        chain += f"[{current}]trim=duration={total:.3f},setpts=PTS-STARTPTS{burn}[vout]"
    else:
        chain = f"[0:v]trim=duration={total:.3f},setpts=PTS-STARTPTS{burn}[vout]"

    args += [
        "-filter_complex",
        chain,
        "-map",
        "[vout]",
        "-map",
        f"{len(shots)}:a",
        "-af",
        audio_filter,
        "-t",
        f"{total:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_mp4),
    ]
    return args


def assemble_video_job(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    storage_root: Path | None = None,
    ffmpeg_path: str | None = None,
    image_adapter: ImageProvider | None = None,
    tts_adapter: TTSProvider | None = None,
    tts_adapter_for_scene: Callable[[dict[str, Any]], TTSProvider | None] | None = None,
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
) -> dict:
    """Run end-to-end video assembly and provenance recording.

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

    ``tts_adapter_for_scene`` resolves a voice per scene (a recurring character's locked
    voice, or a scene override); when it returns None for a scene, ``tts_adapter`` is used,
    and when that is None too the placeholder narrator is. ``production_plan`` is the
    resolved hierarchy the caller built; it is stored on the job with what each scene
    actually used, so a render can be audited without re-running the resolution.

    Raises RenderEngineUnavailable when ffmpeg is missing or the encode fails. No MediaAsset
    is recorded in that case, so no downstream gate can pass on a non-existent render.
    """
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
        scenes_data: list[dict[str, Any]] = [
            {
                "scene_index": s.scene_index,
                "visual_prompt": s.visual_prompt,
                "visual_type": s.visual_type,
                "duration_seconds": s.duration_seconds,
                "voiceover_segment": s.voiceover_segment,
                "shot_type": s.shot_type,
                "transition_in": s.transition_in,
            }
            for s in scenes
        ]

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
    placeholder_voice = DeterministicTTSAdapter()
    # The frames are real only when a real generator made them; this single name is what the
    # asset, the event and the QC report are all written from.
    visual_source = getattr(visual_adapter, "PROVIDER_NAME", PLACEHOLDER_VISUAL_PROVIDER)
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
    frame_files: list[Path] = []

    generated_frames: list[Path] = []
    voice_segments: list[Path] = []

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

    for position, scene in enumerate(scenes_data):
        if position:
            _stop_if_asked()  # the first scene is the render starting; the stage just asked
        index = scene["scene_index"]
        with _at_work(
            engine if image_adapter is not None else None,
            "VideoEditor",
            "generate_image",
            f"imaginea scenei {index}",
        ):
            img_res = asyncio.run(
                visual_adapter.generate_image(
                    scene["visual_prompt"],
                    width=1080,
                    height=1920,
                    extra={"title": storyboard_title, "scene_index": index},
                )
            )
        suffix = img_res.format if img_res.format in ("png", "jpeg", "webp") else "svg"
        still = work_dir / f"scene_{index:02d}.{suffix}"
        still.write_bytes(img_res.image_bytes)
        if image_adapter is not None:
            from app.media.prompt_agent import strip_on_screen_text  # noqa: PLC0415
            from app.media.qc import still_is_degenerate  # noqa: PLC0415

            measuring = find_ffmpeg(ffmpeg_path)
            broken = still_is_degenerate(measuring, still)
            if broken:
                # One more attempt, told plainly what a picture is. A still costs cents; a scene
                # of stripes costs the film.
                production.setdefault("image_retries", []).append(
                    {"scene_index": index, "reason": broken}
                )
                with _at_work(
                    engine,
                    "VideoEditor",
                    "generate_image",
                    f"imaginea scenei {index} (reluare)",
                ):
                    again = asyncio.run(
                        visual_adapter.generate_image(
                            strip_on_screen_text(scene["visual_prompt"])
                            + " A real, detailed scene: no text, no letters, no stripes, "
                            "no repeating pattern.",
                            width=1080,
                            height=1920,
                            extra={"title": storyboard_title, "scene_index": index},
                        )
                    )
                still.write_bytes(again.image_bytes)
                broken = still_is_degenerate(measuring, still)
                if broken:
                    production.setdefault("degenerate_stills", []).append(
                        {"scene_index": index, "reason": broken}
                    )

        if image_adapter is not None:
            # A real still goes to the encoder as it arrived; ffmpeg scales it to 1080x1920.
            generated_frames.append(still)
        else:
            frame_path = work_dir / f"frame_{index:02d}.ppm"
            write_placeholder_frame_ppm(frame_path, index)
            frame_files.append(frame_path)

        real_voice = scene_voices[scenes_data.index(scene)]
        voice_adapter: TTSProvider = (real_voice if all_real else None) or placeholder_voice
        voice_started = time.monotonic()
        with _at_work(
            engine if all_real else None,
            "VoiceArtist",
            "synthesize_voice",
            f"vocea scenei {index}",
        ):
            tts_res = asyncio.run(voice_adapter.synthesize(scene["voiceover_segment"]))
        production["scenes"].append(
            {
                "scene_index": index,
                "voice_provider": getattr(
                    voice_adapter, "PROVIDER_NAME", PLACEHOLDER_VOICE_PROVIDER
                ),
                "model_id": getattr(voice_adapter, "model", None) or None,
                "voice_id": getattr(voice_adapter, "voice_id", None) or None,
                "characters": len(scene["voiceover_segment"]),
                "audio_seconds": round(tts_res.duration_seconds, 3),
                "synthesis_ms": round((time.monotonic() - voice_started) * 1000, 1),
                "attempts": 1,
            }
        )
        # The captions are timed from this: the scene's words last as long as its recording.
        scene["audio_seconds"] = round(tts_res.duration_seconds, 3)
        if all_real:
            segment = work_dir / f"voice_{index:02d}.{tts_res.format}"
            segment.write_bytes(tts_res.audio_bytes)
            voice_segments.append(segment)
            # The scene lasts as long as the narration actually recorded for it, measured from
            # the returned audio. Keeping the storyboard's planned duration here would let the
            # picture drift away from the voice while looking correct.
            scene["duration_seconds"] = max(scene["duration_seconds"], tts_res.duration_seconds)
        elif not master_audio_bytes:
            master_audio_bytes = bytearray(tts_res.audio_bytes)
        elif len(tts_res.audio_bytes) > 44:
            master_audio_bytes.extend(tts_res.audio_bytes[44:])

    if image_adapter is not None:
        frame_files = generated_frames
    total_duration = sum(s["duration_seconds"] for s in scenes_data)

    # The motion pass runs after the narration, because a shot lasts as long as its words and
    # that length is measured, not planned. A scene whose model refuses is a still that pushes
    # slowly; the film is still a film.
    motion_clips: list[Path | None] = [None] * len(scenes_data)
    motion_seconds = 0.0
    motion_credits = 0.0
    failed_models: list[str] = []
    credit_price = _credit_price(engine)
    remaining_usd = motion_budget_usd
    shots_made = 0
    if image_adapter is not None and (video_adapter_for_scene or motion_chooser) and ffmpeg_exe:
        for position, (scene, still) in enumerate(zip(scenes_data, frame_files, strict=False)):
            _stop_if_asked()  # a shot is the money; the switch is read before each one
            if motion_scene_limit is not None and position >= max(0, motion_scene_limit):
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
            span_for_choice = float(scene["duration_seconds"]) + TRANSITION_SECONDS
            tier = str(scene.get("quality_tier") or scene_tier(scene, len(scenes_data)))
            decision: dict[str, Any] = {}
            if motion_chooser is not None:
                adapter, decision = motion_chooser(
                    scene, tier, span_for_choice, remaining_usd, tuple(failed_models)
                )
            else:
                adapter = video_adapter_for_scene(scene) if video_adapter_for_scene else None
            if adapter is None:
                if decision:
                    production.setdefault("motion_notes", []).append(
                        f"scene {scene['scene_index']}: {decision.get('reason', 'no model')}"
                    )
                continue
            wanted = float(scene["duration_seconds"]) + TRANSITION_SECONDS
            record: dict[str, Any] = {
                "provider": getattr(adapter, "PROVIDER_NAME", "unknown"),
                "model": getattr(adapter, "model", None),
                "integration_id": getattr(adapter, "integration_id", None),
                "asked_seconds": round(wanted, 3),
                "tier": tier,
                "scene_category": str(
                    scene.get("scene_category") or scene.get("visual_type") or "GENERAL"
                ),
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
                for entry in production["scenes"]:
                    if entry.get("scene_index") == scene["scene_index"]:
                        entry["motion"] = record
                        break
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
                model_name = getattr(adapter, "model", None)
                if model_name:
                    failed_models.append(str(model_name))
                logger.info(
                    "motion_not_generated",
                    extra={"scene_index": scene["scene_index"], "reason": str(exc)[:160]},
                )
            for entry in production["scenes"]:
                if entry.get("scene_index") == scene["scene_index"]:
                    entry["motion"] = record
                    break
    _record_outcomes(
        engine,
        production,
        render_job_id,
        environment=environment,
        run_kind=run_kind,
        credit_price=credit_price,
    )
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
        "skipped_scenes": len(scenes_data) - len(attempted),
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
        "transition_seconds": TRANSITION_SECONDS,
    }

    audio_file = work_dir / "master_audio.wav"
    if all_real:
        if not ffmpeg_exe:
            # The encoder is checked again below, but joining the narration needs it first,
            # and failing here keeps the reason specific.
            raise RenderEngineUnavailable(
                "FFmpeg is required to join provider narration audio, and it was not found."
            )
        audio_file = _concatenate_audio(ffmpeg_exe, voice_segments, work_dir)
    else:
        audio_file.write_bytes(master_audio_bytes)

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

    # 2. Captions: one cue per sentence, timed to each scene's recorded narration, written
    #    beside the film whether or not they are burnt in. The Owner's setting decides the
    #    burn; an encoder built without libass cannot, and says so in the manifest.
    cues = caption_cues(scenes_data)
    srt_file = work_dir / "captions.srt"
    srt_file.write_text(srt_from_cues(cues), encoding="utf-8")
    wants_burn = bool(getattr(settings, "captions_burn_in", True))
    can_burn = has_filter(ffmpeg_exe, "subtitles")
    burn_in = wants_burn and can_burn and bool(cues)
    production["captions"] = {
        "srt": str(srt_file),
        "cues": len(cues),
        "burned_in": burn_in,
        "style": CAPTION_STYLE if burn_in else None,
        "reason": (
            None
            if burn_in
            else (
                "captions_burn_in is off"
                if not wants_burn
                else (
                    "no narration to caption" if not cues else "the encoder has no subtitles filter"
                )
            )
        ),
    }
    captions = captions_filter(srt_file.name) if burn_in else None

    # Loudness: the joined narration is measured first, then normalised with one linear
    # gain from that measurement (two passes); when the measurement cannot be had the
    # filter normalises as it goes (one pass). The film is delivered at the platform's
    # level either way, and the manifest records both readings.
    loudness: dict[str, Any]
    if has_filter(ffmpeg_exe, "loudnorm"):
        measured = measure_loudness(ffmpeg_exe, audio_file)
        normaliser = loudnorm_filter(measured)
        loudness = {
            "applied": True,
            "target_lufs": LOUDNESS_TARGET_LUFS,
            "true_peak_target_dbtp": TRUE_PEAK_TARGET_DBTP,
            "passes": 2 if "measured_I=" in normaliser else 1,
            "filter": normaliser,
            "input": _loudness_readings(measured),
            "output": None,
        }
        # loudnorm works at 192 kHz internally and hands that on; the film is delivered at
        # the 48 kHz the platforms expect, resampled before the padding.
        audio_filter = f"{normaliser},aresample=48000,apad"
    else:
        loudness = {
            "applied": False,
            "reason": "the encoder has no loudnorm filter",
            "target_lufs": LOUDNESS_TARGET_LUFS,
            "true_peak_target_dbtp": TRUE_PEAK_TARGET_DBTP,
        }
        audio_filter = "apad"
    production["audio"] = {"loudness": loudness}

    # One shot per scene — a generated clip, or the still given a slow push — and the shots
    # dissolve into one another. A film reads as a film; a slideshow reads as a slideshow, and
    # the Owner's first short was the second thing.
    if image_adapter is not None and frame_files:
        shots: list[Path] = []
        for position, scene in enumerate(scenes_data):
            span = float(scene["duration_seconds"]) + TRANSITION_SECONDS
            still = frame_files[min(position, len(frame_files) - 1)]
            target = work_dir / f"shot_{scene['scene_index']:02d}.mp4"
            shot_args = _shot_command(ffmpeg_exe, still, motion_clips[position], span, target)
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
            shots.append(target)
        command_args = _dissolve_command(
            ffmpeg_exe,
            shots,
            scenes_data,
            audio_file,
            output_mp4,
            audio_filter=audio_filter,
            captions=captions,
        )
    else:
        concat_list = work_dir / "inputs.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for frame_path, scene in zip(frame_files, scenes_data, strict=True):
                f.write(f"file '{frame_path.name}'\n")
                f.write(f"duration {scene['duration_seconds']}\n")
            if frame_files:
                f.write(f"file '{frame_files[-1].name}'\n")

        command_args = [
            ffmpeg_exe,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-i",
            str(audio_file),
            "-vf",
            "scale=1080:1920,fps=30,format=yuv420p" + (f",{captions}" if captions else ""),
            # Narration from the local TTS placeholder is usually shorter than the storyboard
            # timeline; pad it with silence rather than truncating the video to the audio.
            "-af",
            audio_filter,
            "-t",
            f"{total_duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
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

    if loudness.get("applied"):
        # The normalising pass reports what it delivered; that report is the output reading.
        # An encode whose log lost the report is measured again from the finished film.
        report = parse_loudnorm_json(res.stderr)
        reported = report.get("output") if report else None
        delivered = (
            reported if isinstance(reported, dict) else measure_loudness(ffmpeg_exe, output_mp4)
        )
        loudness["output"] = _loudness_readings(delivered)

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
