"""Phase 5 Quality Control (QC) Gate.

Following docs/architecture/08_VIDEO_PIPELINE.md:
- Technical QC: valid 9:16 aspect ratio, duration within bounds, file size > 0.
- Factual QC: every referenced claim must remain SUPPORTED in the database.
- Character Drift QC: check character continuity against Character Bible.
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
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.memory import agent_for_role, remember
from app.factual.models import FactualClaim
from app.media.models import (
    CharacterBible,
    MediaAsset,
    QualityControlReport,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.schemas import QCReportView
from app.media.toolchain import (
    LOUDNESS_BAND_LUFS,
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
) -> dict:
    """Run comprehensive Quality Control check on a rendered media asset.

    ``settings`` is the studio's configuration, read for ``max_fallback_scenes``: how many
    scenes of a production film may be stills pushed slowly because the motion model
    refused. Unset, half the scenes.
    """
    qc_id = str(uuid4())
    verified_at = utc_now()
    checks: dict[str, dict] = {}
    failure_reasons: list[str] = []
    # Read before the report's own transaction opens: the environment is the studio's state,
    # never a parameter, and it decides whether a mostly-still film is a failure or a note.
    environment = studio_environment(engine)

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

        # 2c. Audio QC — the film is measured with the same filter that normalised it, so
        #     the renderer and this gate can never disagree. Behind the same guard as the
        #     rest of technical QC: no encoder, no measurement, no certificate.
        ffmpeg = find_ffmpeg()
        audio: dict[str, Any] = {
            "passed": False,
            "integrated_lufs": None,
            "true_peak_dbtp": None,
            "band_lufs": list(LOUDNESS_BAND_LUFS),
            "true_peak_ceiling_dbtp": TRUE_PEAK_CEILING_DBTP,
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
                low, high = LOUDNESS_BAND_LUFS
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

        # 2e. Motion QC — the manifest counts the scenes that moved and the scenes that fell
        #     back to a slow push because the model refused. Too many pushes is a slideshow
        #     sold as a film, and in PRODUCTION the gate says so; in TEST two motion scenes
        #     are the policy and the rest push by design, so the same count is a warning.
        recorded_motion = manifest.get("motion")
        motion_record: dict[str, Any] = recorded_motion if isinstance(recorded_motion, dict) else {}
        total_scenes = int(motion_record.get("scenes") or len(storyboard_scenes) or 0)
        fallback_scenes = int(motion_record.get("fallback_scenes") or 0)
        motion_scenes = int(motion_record.get("motion_scenes") or motion_record.get("clips") or 0)
        ceiling = getattr(settings, "max_fallback_scenes", None)
        max_fallback = (
            int(ceiling) if isinstance(ceiling, int) and ceiling >= 0 else total_scenes // 2
        )
        too_many = fallback_scenes > max_fallback
        motion_reason = (
            f"{fallback_scenes} of {total_scenes} scenes fell back to a slow push because the "
            f"motion model refused; at most {max_fallback} may (fallback ceiling, {environment})"
        )
        motion: dict[str, Any] = {
            "passed": not (too_many and environment == "PRODUCTION"),
            "environment": environment,
            "scenes": total_scenes,
            "motion_scenes": motion_scenes,
            "fallback_scenes": fallback_scenes,
            "max_fallback_scenes": max_fallback,
            "warning": motion_reason if too_many and environment != "PRODUCTION" else None,
        }
        if too_many and environment == "PRODUCTION":
            failure_reasons.append(motion_reason)
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

        # 4. Character Drift QC — NOT IMPLEMENTED. There is no visual comparison against the
        #    Character Bible yet, so this is reported as NOT_APPLICABLE with a reason rather
        #    than as a passing check (50_CONTENT_GATE_MATRIX.md gate behaviour).
        chars_checked = session.scalars(select(CharacterBible)).all()
        checks["character_drift_qc"] = {
            "status": "NOT_IMPLEMENTED",
            "passed": None,
            "characters_configured": len(chars_checked),
            "detail": ("No visual continuity comparison exists yet; this check certifies nothing."),
        }

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
