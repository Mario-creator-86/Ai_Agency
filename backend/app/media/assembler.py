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
import time
from collections.abc import Callable
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
from app.providers.media_base import ImageProvider, TTSProvider, VideoProvider
from app.providers.media_http import MediaProviderError, MediaProviderNotConfigured
from app.services import append_event, utc_now

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
    still: Path,
    seconds: float,
    ffmpeg_exe: str,
) -> tuple[bytes, dict[str, Any]]:
    """Ask the scene's model to move its approved still, and wait for the clip.

    The still is the first frame, so the picture the Director approves is the picture that
    moves. A task that has not finished by the deadline raises — nothing invents a shot.
    """
    prompt = " ".join(str(scene.get("visual_prompt") or "").split())[:900]
    job_id = asyncio.run(
        adapter.create_generation(
            prompt,
            image_ref=_first_frame(ffmpeg_exe, still, seconds),
            duration_seconds=seconds,
            aspect_ratio="9:16",
        )
    )
    deadline = time.monotonic() + MOTION_DEADLINE_SECONDS
    while True:
        result = asyncio.run(adapter.get_generation_status(job_id))
        if result.status == "COMPLETED" and result.video_bytes:
            return result.video_bytes, result.raw_response
        if result.status == "FAILED":
            code = (result.raw_response or {}).get("failure_code")
            raise MediaProviderError(f"the motion task failed ({code or 'no reason given'})")
        if time.monotonic() >= deadline:
            raise MediaProviderError("the motion task did not finish before the deadline")
        time.sleep(MOTION_POLL_SECONDS)


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
) -> list[str]:
    """One ffmpeg call over the shot files: each dissolves into the next.

    Each shot is one transition longer than its narration and each dissolve consumes exactly
    that overlap, so shot N still starts where scene N's words start — the picture never
    drifts away from the voice.
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
    if chain:
        chain += f"[{current}]trim=duration={total:.3f},setpts=PTS-STARTPTS[vout]"
    else:
        chain = f"[0:v]trim=duration={total:.3f},setpts=PTS-STARTPTS[vout]"

    args += [
        "-filter_complex",
        chain,
        "-map",
        "[vout]",
        "-map",
        f"{len(shots)}:a",
        "-af",
        "apad",
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
    production_plan: dict[str, Any] | None = None,
) -> dict:
    """Run end-to-end video assembly and provenance recording.

    ``image_adapter`` and ``tts_adapter`` are the providers the Owner selected and verified.
    When either is absent the corresponding deterministic placeholder generator is used, and
    the asset is recorded under the placeholder provider name — which QC blocks from
    publication. The recorded name always says which generator actually made the frames, so a
    render can never be mistaken for publishable content it is not.

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

    # 1. Generate Subtitles
    srt_content = generate_subtitles_srt(scenes_data)
    srt_file = work_dir / "captions.srt"
    srt_file.write_text(srt_content, encoding="utf-8")

    # 2. Generate placeholder visual cards (SVG for the UI, raster PPM for the encoder)
    #    and voiceover segments.
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

        real_voice = scene_voices[scenes_data.index(scene)]
        voice_adapter: TTSProvider = (real_voice if all_real else None) or placeholder_voice
        voice_started = time.monotonic()
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
    if image_adapter is not None and video_adapter_for_scene is not None and ffmpeg_exe:
        for position, (scene, still) in enumerate(zip(scenes_data, frame_files, strict=False)):
            adapter = video_adapter_for_scene(scene)
            if adapter is None:
                continue
            wanted = float(scene["duration_seconds"]) + TRANSITION_SECONDS
            record: dict[str, Any] = {
                "provider": getattr(adapter, "PROVIDER_NAME", "unknown"),
                "model": getattr(adapter, "model", None),
                "integration_id": getattr(adapter, "integration_id", None),
                "asked_seconds": round(wanted, 3),
            }
            try:
                clip_bytes, raw = _generate_motion(adapter, scene, still, wanted, ffmpeg_exe)
                clip = work_dir / f"motion_{scene['scene_index']:02d}.mp4"
                clip.write_bytes(clip_bytes)
                motion_clips[position] = clip
                record["bytes"] = len(clip_bytes)
                record["task"] = (raw or {}).get("task_status")
                motion_seconds += wanted
            except (MediaProviderError, MediaProviderNotConfigured, ValueError, OSError) as exc:
                record["refused"] = str(exc)[:200]
                logger.info(
                    "motion_not_generated",
                    extra={"scene_index": scene["scene_index"], "reason": str(exc)[:160]},
                )
            for entry in production["scenes"]:
                if entry.get("scene_index") == scene["scene_index"]:
                    entry["motion"] = record
                    break
    production["motion"] = {
        "clips": sum(1 for clip in motion_clips if clip is not None),
        "scenes": len(scenes_data),
        "seconds": round(motion_seconds, 3),
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
        command_args = _dissolve_command(ffmpeg_exe, shots, scenes_data, audio_file, output_mp4)
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
        "provenance_hash": provenance_hash,
        "duration_seconds": total_duration,
        "file_size_bytes": file_size,
        "render_engine": "FFMPEG",
        "visual_source": visual_source,
        "voice_source": voice_source,
        "production": production,
    }
