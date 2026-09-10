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
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import ROOT
from app.media.models import MediaAsset, Storyboard, StoryboardScene, VideoRenderJob
from app.media.toolchain import find_ffmpeg
from app.providers.deterministic_media import (
    DeterministicTTSAdapter,
    DeterministicVisualAdapter,
)
from app.providers.media_base import ImageProvider, TTSProvider
from app.services import append_event, utc_now

logger = logging.getLogger("studio.assembler")

DEFAULT_STORAGE_ROOT = ROOT / "backend" / "storage" / "media"

#: Recorded on every asset produced from locally synthesised placeholder frames. The QC gate
#: refuses to pass such an asset for publication: placeholder cards are not real footage.
PLACEHOLDER_VISUAL_PROVIDER = "PLACEHOLDER_DETERMINISTIC_VISUALS"
PLACEHOLDER_VOICE_PROVIDER = "PLACEHOLDER_DETERMINISTIC_VOICE"


class RenderEngineUnavailable(RuntimeError):
    """Raised when no real video encoder is available.

    The studio never writes a stand-in file with an .mp4 name: a render either produces a real
    encoded video or it fails, so that no downstream gate can be satisfied by a fake artefact.
    """


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


def format_srt_timestamp(seconds: float) -> str:
    """Format float seconds to SubRip timestamp: HH:MM:SS,mmm"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def generate_subtitles_srt(scenes: list[dict]) -> str:
    """Generate valid SubRip (SRT) subtitles with synchronized scene timestamps."""
    srt_lines = []
    current_time = 0.0

    for idx, scene in enumerate(scenes, start=1):
        start_ts = format_srt_timestamp(current_time)
        dur = float(scene["duration_seconds"])
        end_time = current_time + dur
        end_ts = format_srt_timestamp(end_time)

        # Clean voiceover text
        text = str(scene["voiceover_segment"]).strip()
        if not text:
            text = f"[{str(scene['visual_prompt'])[:40]}]"

        srt_lines.append(str(idx))
        srt_lines.append(f"{start_ts} --> {end_ts}")
        srt_lines.append(text)
        srt_lines.append("")  # blank separator

        current_time = end_time

    return "\n".join(srt_lines)


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


def assemble_video_job(
    engine: Engine,
    storyboard_id: str,
    correlation_id: str,
    storage_root: Path | None = None,
    ffmpeg_path: str | None = None,
    image_adapter: ImageProvider | None = None,
    tts_adapter: TTSProvider | None = None,
) -> dict:
    """Run end-to-end video assembly and provenance recording.

    ``image_adapter`` and ``tts_adapter`` are the providers the Owner selected and verified.
    When either is absent the corresponding deterministic placeholder generator is used, and
    the asset is recorded under the placeholder provider name — which QC blocks from
    publication. The recorded name always says which generator actually made the frames, so a
    render can never be mistaken for publishable content it is not.

    Raises RenderEngineUnavailable when ffmpeg is missing or the encode fails. No MediaAsset
    is recorded in that case, so no downstream gate can pass on a non-existent render.
    """
    render_job_id = str(uuid4())
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

    # 1. Generate Subtitles
    srt_content = generate_subtitles_srt(scenes_data)
    srt_file = work_dir / "captions.srt"
    srt_file.write_text(srt_content, encoding="utf-8")

    # 2. Generate placeholder visual cards (SVG for the UI, raster PPM for the encoder)
    #    and voiceover segments.
    visual_adapter: ImageProvider = image_adapter or DeterministicVisualAdapter()
    voice_adapter: TTSProvider = tts_adapter or DeterministicTTSAdapter()
    # The frames are real only when a real generator made them; this single name is what the
    # asset, the event and the QC report are all written from.
    visual_source = getattr(visual_adapter, "PROVIDER_NAME", PLACEHOLDER_VISUAL_PROVIDER)
    voice_source = getattr(voice_adapter, "PROVIDER_NAME", PLACEHOLDER_VOICE_PROVIDER)

    total_duration = sum(s["duration_seconds"] for s in scenes_data)
    master_audio_bytes = bytearray()
    frame_files: list[Path] = []

    generated_frames: list[Path] = []
    voice_segments: list[Path] = []

    for scene in scenes_data:
        index = scene["scene_index"]
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
            # A real still goes to the encoder as it arrived; ffmpeg scales it to 1080x1920.
            generated_frames.append(still)
        else:
            frame_path = work_dir / f"frame_{index:02d}.ppm"
            write_placeholder_frame_ppm(frame_path, index)
            frame_files.append(frame_path)

        tts_res = asyncio.run(voice_adapter.synthesize(scene["voiceover_segment"]))
        if tts_adapter is not None:
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

    audio_file = work_dir / "master_audio.wav"
    if tts_adapter is not None:
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
    command_args: list[str] = []

    def _fail_job(reason: str, log: str) -> None:
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

    if not ffmpeg_exe:
        reason = (
            "FFmpeg is not installed or not on PATH. Install FFmpeg or set STUDIO_FFMPEG_PATH; "
            "the studio does not substitute a placeholder file for a rendered video."
        )
        _fail_job(reason, reason)
        raise RenderEngineUnavailable(reason)

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
        "scale=1080:1920,fps=30,format=yuv420p",
        # Narration from the local TTS placeholder is usually shorter than the storyboard
        # timeline; pad it with silence rather than truncating the video to the audio.
        "-af",
        "apad",
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
        "provenance_hash": provenance_hash,
        "duration_seconds": total_duration,
        "file_size_bytes": file_size,
        "render_engine": "FFMPEG",
        "visual_source": visual_source,
        "voice_source": voice_source,
    }
