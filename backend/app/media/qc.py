"""Phase 5 Quality Control (QC) Gate.

Following docs/architecture/08_VIDEO_PIPELINE.md:
- Technical QC: valid 9:16 aspect ratio, duration within bounds, file size > 0.
- Factual QC: every referenced claim must remain SUPPORTED in the database.
- Picture QC: a model that can see reads one frame per scene and says whether it is a
  picture at all and whether it shows what the scene asked for (app.media.picture_qc).
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
import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.memory import agent_for_role, remember
from app.factual.models import FactualClaim
from app.media.models import (
    MediaAsset,
    QualityControlReport,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.picture_qc import evaluate_pictures
from app.media.schemas import QCReportView
from app.media.toolchain import (
    LOUDNESS_TARGET_LUFS,
    TRUE_PEAK_CEILING_DBTP,
    find_ffmpeg,
    find_ffprobe,
    has_filter,
    measure_loudness,
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


def caption_problems(cues: list[dict[str, Any]]) -> list[str]:
    """What keeps these cues from being read on a phone; empty when nothing does."""
    problems: list[str] = []
    previous_end: float | None = None
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


def evaluate_media_qc(
    engine: Engine,
    media_asset_id: str,
    correlation_id: str,
    settings: Any | None = None,
    *,
    registry: Any | None = None,
    ffmpeg_path: str | None = None,
) -> dict:
    """Run comprehensive Quality Control check on a rendered media asset.

    ``settings`` is the studio's configuration, read for ``max_fallback_scenes``: how many
    scenes of a production film may be stills pushed slowly because the motion model
    refused. Unset, half the scenes.

    ``registry`` and ``ffmpeg_path`` are what it takes to look at the pictures rather than
    only at the file: a provider that holds a model the provider says can see, and the
    encoder that cuts one frame per scene. Without either, the picture and character checks
    report NOT_APPLICABLE with the reason and the film's verdict is unchanged — never a
    pass by absence.
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

    with Session(engine) as session, session.begin():
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
        dur_valid = 10.0 <= measured_dur <= 70.0  # Shorts bounds

        if probe.get("ok"):
            if not is_9_16:
                failure_reasons.append(
                    f"Measured aspect ratio {measured_w}x{measured_h} is not 9:16"
                )
            if not dur_valid:
                failure_reasons.append(
                    f"Measured duration {measured_dur}s outside vertical Short limits (10s-70s)"
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
        valid_licenses = {
            "ORIGINAL_AI_GENERATED",
            "PROPRIETARY_STUDIO",
            "PUBLIC_DOMAIN",
            "LICENSED",
        }
        rights_passed = asset.license_status in valid_licenses
        if not rights_passed:
            failure_reasons.append(f"Invalid license status: {asset.license_status}")

        checks["rights_qc"] = {
            "passed": rights_passed,
            "license_status": asset.license_status,
            "provider_name": asset.provider_name,
        }

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

        # 2e. Motion QC — which LIVE scenes the film shows as a still. In PRODUCTION none may
        #     be, unless the Owner chose a locally animated still for that scene on the
        #     sheet: the old ceiling of half the scenes let the Nepal film's two stills
        #     through. In TEST two motion scenes are the policy and the rest push by design,
        #     so the old ceiling only warns there. Cards are composed, never filmed.
        if render_job is not None:
            owner_choices = owner_local_moves(session, render_job.storyboard_id)
        else:
            owner_choices = set()
        if not manifest.get("motion") and not manifest.get("scenes"):
            manifest_for_motion: dict[str, Any] = {"motion": {"scenes": len(storyboard_scenes)}}
        else:
            manifest_for_motion = manifest
        motion = fallback_verdict(
            manifest_for_motion,
            environment=environment,
            owner_choices=owner_choices,
            settings=settings,
        )
        if not motion["passed"]:
            failure_reasons.append(f"Motion QC: {motion['reason_ro']}")
        checks["motion_qc"] = motion

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
            and bool(captions["passed"])
            and bool(motion["passed"])
            # Only a measured refusal counts against the film; a check that stood down
            # (None) leaves the verdict exactly where the other gates left it.
            and pictures["picture_qc"]["passed"] is not False
            and pictures["character_drift_qc"]["passed"] is not False
        )
        status = "PASSED" if overall_passed else "FAILED"
        score = 1.0 if overall_passed else round(max(0.0, 1.0 - (len(failure_reasons) * 0.25)), 2)

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
#: The fixture each camera move is held to. Moves that change the scale of the picture are
#: held to the push-in; moves that slide it, to the pan. 'static' has no floor.
MOVE_FIXTURE: dict[str, str | None] = {
    "static": None,
    "slow push-in": "push_in",
    "slow pull-back": "push_in",
    "aerial drift forward": "push_in",
    "slow pan left": "pan",
    "slow pan right": "pan",
    "tilt up": "pan",
    "tilt down": "pan",
    "pedestal up": "pan",
    "slow orbit": "pan",
}
#: A hard cut inside a clip is one frame that differs from the one before it far more than
#: the clip's own motion: above eight times the clip's median YDIF and above 12 in absolute
#: terms. Measured: cuts between two Nepal stills read 44-66; the busiest Nepal clip's
#: largest frame-to-frame change is 4.9.
CUT_SPIKE_RATIO = 8.0
CUT_SPIKE_MIN_YDIF = 12.0
#: One retry per failing clip, on the same model, with seed + 1, inside the approved cap.
MAX_CLIP_RETRIES = 1
#: A frame whose YDIF is under this repeats the one before it. Measured: a 24 fps Nepal clip
#: converted to 30 fps has exactly 20% such frames; the clips as delivered, none (their
#: slowest frame reads 0.12).
DUPLICATE_YDIF = 0.05
#: On a lossless shot intermediate (x264 -qp 0) a repeated frame reads exactly 0; the slowest
#: real motion measured on the Nepal hero shot reads 0.13. The lossy film cannot separate
#: them: after CRF 17 the same slow clip reads under 0.05 on real frames.
LOSSLESS_DUPLICATE_YDIF = 0.01

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
#: How much longer than its narration a film may run.
DURATION_OVER_NARRATION_SECONDS = 1.0
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
        return ClipCheck(
            "motion",
            "PASSED",
            False,
            mean,
            f"cadru static cerut: fără prag de mișcare (YDIF mediu {_ro_number(mean, 2)})",
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

    def check(self, code: str) -> ClipCheck:
        return next(item for item in self.checks if item.code == code)


def _is_none(text: str) -> bool:
    return str(text or "").strip().strip(".").lower() in ("none", "no", "nothing", "nimic", "")


def _picture_check(judgement: Any, *, faces_forbidden: bool) -> ClipCheck:
    """The vision checklist, read strictly: a keep whose own answers contradict it fails."""
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
) -> ClipReport:
    """Measure one bought clip before it is cut into the film, at 0 credits.

    - motion: mean YDIF at 540 px against the floor of its camera move (`motion_check`);
    - cuts: a hard cut inside the clip fails it (`cut_spikes`);
    - faces: YuNet on the first, middle and last frames when the bible forbids faces;
    - picture: `judge` (normally picture_qc.judge_clip bound to the engine and registry)
      looks at the same three frames at 1080 px.

    Fail closed: a local check that could not run blocks in PRODUCTION and warns in TEST; a
    clip nobody looked at blocks in every environment, as a still does at the stills gate.
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
        judgement = judge([path for _at, _moment, path in frames]) if judge and frames else None
        picture = _picture_check(judgement, faces_forbidden=faces_forbidden)
        if judgement is not None:
            measured["picture"] = {
                "status": getattr(judgement, "status", None),
                "run_id": getattr(judgement, "run_id", None),
                "looked_by": getattr(judgement, "looked_by", None),
            }
    finally:
        if owned:
            shutil.rmtree(folder, ignore_errors=True)

    checks: list[ClipCheck] = []
    warnings: list[str] = []
    for item in (motion, cuts, faces):
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
    )


# ------------------------------------------------------------- one retry, inside the cap


def stronger_motion_prompt(
    prompt: str, camera_move: str | None, *, model_id: str | None = None
) -> str:
    """The same motion prompt with the camera move asked for more firmly, for the one retry.

    Positive words only (veo's prompt carries no negation), placed before the closing line,
    which stays the last sentence in the model's own dialect.
    """
    from app.media.prompt_lint import MOTION_CLOSING, VEO_MOTION_CLOSING  # noqa: PLC0415

    veo = "veo" in str(model_id or "").lower()
    move = canonical_move(camera_move)
    if move is None or move == "static":
        firmer = (
            "The scene itself keeps moving clearly and steadily from the first frame to the last."
        )
    else:
        firmer = (
            f"The camera {move.removeprefix('slow ')} is clearly visible and keeps going "
            "steadily from the first frame to the last."
        )
    body = str(prompt or "").strip()
    for ending in (MOTION_CLOSING, VEO_MOTION_CLOSING):
        if body.endswith(ending):
            body = body[: -len(ending)].rstrip()
            break
    if firmer not in body:
        body = f"{body} {firmer}".strip()
    return f"{body} {VEO_MOTION_CLOSING if veo else MOTION_CLOSING}"


@dataclass(frozen=True)
class ClipRetry:
    action: str  # ACCEPT | RETRY | ESCALATE
    seed: int | None
    reason_ro: str


def clip_retry_decision(
    report: ClipReport,
    *,
    seed: int,
    retries_done: int,
    committed_credits: float,
    price_credits: float,
    cap_credits: float,
) -> ClipRetry:
    """What a clip's QC verdict buys: nothing more, one retry with seed + 1, or the Owner."""
    if report.passed:
        return ClipRetry("ACCEPT", seed, f"Scena {report.scene}: clipul a trecut controlul.")
    if retries_done >= MAX_CLIP_RETRIES:
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
    return ClipRetry(
        "RETRY",
        int(seed) + 1,
        f"Scena {report.scene}: o singură reluare pe același model, cu sămânța {int(seed) + 1} "
        f"și mișcarea cerută mai ferm ({price_credits:.0f} credite, în plafon).",
    )


@dataclass(frozen=True)
class ClipQCOutcome:
    status: str  # PASSED | PASSED_ON_RETRY | ESCALATED
    clip: Path | None
    attempts: int
    seeds: tuple[int, ...]
    reports: tuple[ClipReport, ...]
    retry_credits: float
    reason_ro: str
    prompt: str


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
) -> ClipQCOutcome:
    """Check a bought clip; when it fails, buy it again ONCE on the same model with seed + 1
    and a firmer motion prompt, only when the approved cap still covers that; otherwise, or
    when the retry fails too, hand the scene to the Owner. `buy(seed, prompt)` is the caller's
    purchase of one shot and returns the new clip, or None when nothing was delivered."""
    first = check(clip)
    decision = clip_retry_decision(
        first,
        seed=seed,
        retries_done=0,
        committed_credits=committed_credits,
        price_credits=price_credits,
        cap_credits=cap_credits,
    )
    if decision.action == "ACCEPT":
        return ClipQCOutcome("PASSED", clip, 1, (seed,), (first,), 0.0, decision.reason_ro, "")
    if decision.action == "ESCALATE" or decision.seed is None:
        return ClipQCOutcome("ESCALATED", None, 1, (seed,), (first,), 0.0, decision.reason_ro, "")
    prompt = stronger_motion_prompt(motion_prompt, camera_move, model_id=model_id)
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
            f"Scena {first.scene}: reluarea nu a livrat clipul. Decide Proprietarul.",
            prompt,
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
            f"Scena {first.scene}: clipul a trecut la reluare (sămânța {decision.seed}).",
            prompt,
        )
    final = clip_retry_decision(
        second,
        seed=decision.seed,
        retries_done=1,
        committed_credits=committed_credits + price_credits,
        price_credits=price_credits,
        cap_credits=cap_credits,
    )
    return ClipQCOutcome(
        "ESCALATED", None, 2, seeds, (first, second), float(price_credits), final.reason_ro, prompt
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


def fallback_verdict(
    production: dict[str, Any],
    *,
    environment: str,
    owner_choices: set[int],
    settings: Any | None = None,
) -> dict[str, Any]:
    """Whether the film's stills are allowed. In PRODUCTION no LIVE scene may be a still
    unless the Owner chose a locally animated still for that very scene; no setting loosens
    it. In TEST stills are the studio's own policy, so the old ceiling (the setting, else half
    the scenes) only warns."""
    recorded = production.get("motion")
    motion: dict[str, Any] = recorded if isinstance(recorded, dict) else {}
    listed_scenes = production.get("scenes")
    scenes = listed_scenes if isinstance(listed_scenes, list) else []
    total = int(motion.get("scenes") or len(scenes) or 0)
    moving = int(motion.get("motion_scenes") or motion.get("clips") or 0)
    listed = live_fallback_scenes(production)
    count = len(listed) if listed is not None else int(motion.get("fallback_scenes") or 0)
    fallbacks = listed or []
    chosen = sorted(index for index in fallbacks if index in owner_choices)
    unchosen = sorted(index for index in fallbacks if index not in owner_choices)
    record: dict[str, Any] = {
        "environment": environment,
        "scenes": total,
        "motion_scenes": moving,
        "fallback_scenes": count,
        "live_fallbacks": fallbacks,
        "owner_chosen": chosen,
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
                f"{named}: imagine fixă (fallback) fără alegerea Proprietarului. În PRODUCȚIE "
                "nicio scenă filmată nu rămâne imagine fixă decât dacă Proprietarul a ales "
                "„imagine fixă animată local” pentru ea pe foaia de filmare."
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
    with a LIVE scene the Owner did not choose to show as a still. Returns the verdict."""
    with Session(engine) as session:
        chosen = owner_local_moves(session, storyboard_id)
    verdict = fallback_verdict(
        production,
        environment=environment or studio_environment(engine),
        owner_choices=chosen,
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
) -> tuple[list[str], list[str]]:
    """What keeps the delivered file from the encoder's own spec: (failures, warnings).

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
    if narration_seconds is None:
        floors.append(
            "Lungimea narațiunii nu este înregistrată; durata filmului nu poate fi judecată"
        )
    elif duration > narration_seconds + DURATION_OVER_NARRATION_SECONDS + 1e-6:
        floors.append(
            f"Filmul durează {_ro_number(duration)} s, mai mult decât narațiunea "
            f"({_ro_number(narration_seconds)} s) plus "
            f"{_ro_number(DURATION_OVER_NARRATION_SECONDS)} s"
        )
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
