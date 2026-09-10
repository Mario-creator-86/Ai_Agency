"""Phase 5 Quality Control (QC) Gate.

Following docs/architecture/08_VIDEO_PIPELINE.md:
- Technical QC: valid 9:16 aspect ratio, duration within bounds, file size > 0.
- Factual QC: every referenced claim must remain SUPPORTED in the database.
- Character Drift QC: check character continuity against Character Bible.
- Rights/License QC: all assets must be clear of copyright blocks.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

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
from app.media.toolchain import find_ffprobe
from app.services import append_event, utc_now

logger = logging.getLogger("studio.qc")

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
    return {
        "available": True,
        "ok": True,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "duration_seconds": round(duration, 2),
        "video_codec": video.get("codec_name"),
        "has_audio": any(st.get("codec_type") == "audio" for st in data.get("streams", [])),
        "error": None,
    }


def evaluate_media_qc(engine: Engine, media_asset_id: str, correlation_id: str) -> dict:
    """Run comprehensive Quality Control check on a rendered media asset."""
    qc_id = str(uuid4())
    verified_at = utc_now()
    checks: dict[str, dict] = {}
    failure_reasons: list[str] = []

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
        factual_passed = True
        claims_checked = []

        if render_job:
            sb = session.get(Storyboard, render_job.storyboard_id)
            if sb:
                scenes = session.scalars(
                    select(StoryboardScene).where(StoryboardScene.storyboard_id == sb.id)
                ).all()
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

        # Overall Status
        overall_passed = tech_passed and rights_passed and factual_passed and not is_placeholder
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

        return QCReportView.model_validate(report).model_dump()


def get_media_qc(engine: Engine, media_asset_id: str) -> dict | None:
    with Session(engine) as session:
        rep = session.scalar(
            select(QualityControlReport)
            .where(QualityControlReport.media_asset_id == media_asset_id)
            .order_by(QualityControlReport.verified_at.desc())
        )
        return QCReportView.model_validate(rep).model_dump() if rep else None
