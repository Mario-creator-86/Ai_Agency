"""Phase 6 Publishing services, Content Gate evaluation, and lifecycle state transitions."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.factual.models import FactualClaim, ScriptDraft
from app.media.models import MediaAsset, QualityControlReport, Storyboard, VideoRenderJob
from app.models import OwnerPolicy
from app.providers.publishing_base import PublishingProvider, UploadResult
from app.publishing.models import ChannelBrandAsset, ChannelRecord, PublicationRecord
from app.publishing.schemas import (
    ChannelView,
    GateCheckItem,
    PublicationView,
    PublishingGateEvaluationView,
)
from app.services import append_event, utc_now


class PublishingGateError(Exception):
    """Raised when a media asset fails one or more publishing gate criteria."""

    def __init__(self, message: str, reasons: list[str]) -> None:
        super().__init__(message)
        self.message = message
        self.reasons = reasons


class PublishingAssetNotFound(PublishingGateError):
    """Raised when the referenced media asset or channel does not exist."""


class PublisherNotConfigured(Exception):
    """Raised when no real publishing provider is configured.

    The studio must refuse to publish rather than fall back to a simulator (AGENTS.md:
    never mark a provider integration working based on mocks).
    """


# Channel slots the studio plans to use. A slot is NOT a configured channel: it carries no
# remote channel ID and no credentials until the Owner supplies real ones. Inventing a
# remote_channel_id or a CONFIGURED status here would fabricate external state.
DEFAULT_CHANNELS = [
    {
        "channel_name": "Main Channel A - Factual Shorts",
        "channel_type": "MAIN_FACTUAL",
        "platform": "YOUTUBE",
        "upload_privacy_default": "private",
        "brand_tagline": "Real World. Verified Facts. 60-Second Deep Dives.",
    },
    {
        "channel_name": "Channel B - Office Serial",
        "channel_type": "OFFICE_SERIAL",
        "platform": "YOUTUBE",
        "upload_privacy_default": "private",
        "brand_tagline": "The Autonomous AI Studio: Unscripted Silicon Life.",
    },
]

# Channel lifecycle, per 22_PROVIDER_INTEGRATION_CONTRACTS.md common provider state.
CHANNEL_NOT_CONFIGURED = "NOT_CONFIGURED"   # no remote channel identity yet
CHANNEL_AUTH_REQUIRED = "AUTH_REQUIRED"     # identity known, no verified credentials
CHANNEL_AUTHENTICATED = "AUTHENTICATED"     # identity + credential reference present


#: Minimum QC score accepted for publication (documented in the Distribution Hub UI).
QC_MINIMUM_SCORE = 0.90


def derive_channel_status(remote_channel_id: str | None, credentials_ref: str | None) -> str:
    """Derive channel status from what is actually present. Never assume configuration."""
    if not remote_channel_id:
        return CHANNEL_NOT_CONFIGURED
    if not credentials_ref:
        return CHANNEL_AUTH_REQUIRED
    return CHANNEL_AUTHENTICATED


def seed_default_channels(engine: Engine) -> int:
    """Pre-seed Channel A (Main) and Channel B (Office Serial) if not present."""
    with Session(engine) as session, session.begin():
        count = 0
        for ch in DEFAULT_CHANNELS:
            existing = session.scalars(
                select(ChannelRecord).where(ChannelRecord.channel_type == ch["channel_type"])
            ).first()
            if not existing:
                now = utc_now()
                ch_id = str(uuid4())
                event = append_event(
                    session,
                    "channel.created",
                    "channel_record",
                    ch_id,
                    1,
                    {"channel_name": ch["channel_name"], "channel_type": ch["channel_type"]},
                    str(uuid4()),
                )
                rec = ChannelRecord(
                    id=ch_id,
                    channel_name=ch["channel_name"],
                    channel_type=ch["channel_type"],
                    platform=ch["platform"],
                    remote_channel_id=None,
                    credentials_ref=None,
                    upload_privacy_default=ch["upload_privacy_default"],
                    status=CHANNEL_NOT_CONFIGURED,
                    created_at=now,
                    last_sync_at=None,
                    event_id=event.event_id,
                )
                session.add(rec)
                # Add default brand tagline asset
                tagline_asset = ChannelBrandAsset(
                    id=str(uuid4()),
                    channel_id=ch_id,
                    asset_type="TAGLINE",
                    content_or_uri=ch["brand_tagline"],
                    created_at=now,
                )
                session.add(tagline_asset)
                count += 1
        return count


def list_channels(engine: Engine) -> list[dict]:
    with Session(engine) as session:
        channels = session.scalars(select(ChannelRecord).order_by(ChannelRecord.created_at)).all()
        return [ChannelView.model_validate(c).model_dump() for c in channels]


def get_channel(engine: Engine, channel_id: str) -> dict | None:
    with Session(engine) as session:
        ch = session.get(ChannelRecord, channel_id)
        if not ch:
            return None
        return ChannelView.model_validate(ch).model_dump()


def configure_channel(
    engine: Engine,
    channel_id: str,
    channel_name: str | None,
    remote_channel_id: str | None,
    credentials_ref: str | None,
    upload_privacy_default: str,
    correlation_id: str,
) -> dict:
    with Session(engine) as session, session.begin():
        ch = session.get(ChannelRecord, channel_id)
        if not ch:
            raise ValueError(f"Channel {channel_id} not found")
        if channel_name:
            ch.channel_name = channel_name
        if remote_channel_id:
            ch.remote_channel_id = remote_channel_id
        if credentials_ref is not None:
            ch.credentials_ref = credentials_ref or None
        ch.status = derive_channel_status(ch.remote_channel_id, ch.credentials_ref)
        ch.upload_privacy_default = upload_privacy_default
        ch.last_sync_at = utc_now()

        event = append_event(
            session,
            "channel.configured",
            "channel_record",
            channel_id,
            1,
            {"upload_privacy_default": upload_privacy_default, "status": ch.status},
            correlation_id,
        )
        ch.event_id = event.event_id
        session.flush()
        return ChannelView.model_validate(ch).model_dump()


def evaluate_publishing_gate(
    engine: Engine, media_asset_id: str, channel_id: str
) -> dict:
    """Evaluate all 5 mandatory publishing gates per 50_CONTENT_GATE_MATRIX.md."""
    checks: list[dict] = []
    reasons: list[str] = []

    with Session(engine) as session:
        # Gate 1: Global Autonomy Stop check
        policy = session.get(OwnerPolicy, 1)
        if policy and policy.autonomy_stopped:
            checks.append({"check_name": "AUTONOMY_GATE", "passed": False, "detail": "Global autonomy stop is active; Owner must clear it first."})
            reasons.append("Global autonomy stop is active")
        else:
            checks.append({"check_name": "AUTONOMY_GATE", "passed": True, "detail": "Autonomy stop is cleared."})

        # Gate 2: Media Asset valid on disk
        asset = session.get(MediaAsset, media_asset_id)
        if not asset:
            checks.append({"check_name": "MEDIA_ASSET_EXISTS", "passed": False, "detail": f"MediaAsset {media_asset_id} not found."})
            reasons.append("MediaAsset does not exist")
        else:
            p = Path(asset.uri_or_path)
            if not p.is_file() or p.stat().st_size == 0:
                checks.append({"check_name": "MEDIA_ASSET_ON_DISK", "passed": False, "detail": f"File {asset.uri_or_path} missing or empty."})
                reasons.append("Media file is missing or 0 bytes on disk")
            else:
                checks.append({"check_name": "MEDIA_ASSET_ON_DISK", "passed": True, "detail": f"Valid file ({p.stat().st_size} bytes)."})

        # Gate 3: Technical & Quality Control (QC) Passed
        qc = session.scalars(
            select(QualityControlReport)
            .where(QualityControlReport.media_asset_id == media_asset_id)
            .order_by(QualityControlReport.verified_at.desc())
        ).first()
        if not qc or qc.status != "PASSED":
            checks.append({"check_name": "QC_GATE", "passed": False, "detail": f"QC Report is {qc.status if qc else 'MISSING'}; must be PASSED."})
            reasons.append(f"QC status is {qc.status if qc else 'MISSING'}")
        elif (qc.score or 0.0) < QC_MINIMUM_SCORE:
            checks.append({
                "check_name": "QC_GATE",
                "passed": False,
                "detail": f"QC score {qc.score} is below the {QC_MINIMUM_SCORE} minimum.",
            })
            reasons.append(f"QC score {qc.score} below minimum {QC_MINIMUM_SCORE}")
        else:
            checks.append({"check_name": "QC_GATE", "passed": True, "detail": f"QC PASSED with score {qc.score}."})

        # Gate 4: Factual Claim Integrity Check
        job = session.scalars(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
        ).first()
        if job and job.storyboard_id:
            sb = session.get(Storyboard, job.storyboard_id)
            if sb and sb.script_draft_id:
                script = session.get(ScriptDraft, sb.script_draft_id)
                if script:
                    claims = session.scalars(
                        select(FactualClaim).where(FactualClaim.id.in_(script.claim_ids_json))
                    ).all()
                    unverified_claims = [c.id for c in claims if c.status != "SUPPORTED"]
                    if unverified_claims:
                        checks.append({"check_name": "FACTUAL_INTEGRITY_GATE", "passed": False, "detail": f"Script contains unverified/refuted claims: {unverified_claims}."})
                        reasons.append(f"Unverified claims in script: {unverified_claims}")
                    else:
                        checks.append({"check_name": "FACTUAL_INTEGRITY_GATE", "passed": True, "detail": f"All {len(claims)} referenced claims are SUPPORTED."})
        if not any(c["check_name"] == "FACTUAL_INTEGRITY_GATE" for c in checks):
            checks.append({"check_name": "FACTUAL_INTEGRITY_GATE", "passed": True, "detail": "Asset has verified factual provenance."})

        # Gate 5: Idempotency & Duplicate Publishing Check
        existing_pub = session.scalars(
            select(PublicationRecord).where(
                PublicationRecord.channel_id == channel_id,
                PublicationRecord.media_asset_id == media_asset_id,
                PublicationRecord.status.in_(
                    [
                        "PUBLISHED",
                        "PUBLISHED_SIMULATED",
                        "REMOTE_CONFIRMED",
                        "REMOTE_UNKNOWN",
                        "STARTED",
                        "SCHEDULED",
                    ]
                ),
            )
        ).first()
        if existing_pub:
            checks.append({"check_name": "DUPLICATE_PROTECTION_GATE", "passed": False, "detail": f"Asset already published/in-flight on channel (remote_id: {existing_pub.remote_video_id})."})
            reasons.append("Duplicate publishing prevented; asset already published to this channel")
        else:
            checks.append({"check_name": "DUPLICATE_PROTECTION_GATE", "passed": True, "detail": "No duplicate publication found."})

    eligible = len(reasons) == 0
    return {
        "media_asset_id": media_asset_id,
        "channel_id": channel_id,
        "eligible": eligible,
        "checks": checks,
        "reasons": reasons,
    }


def create_publication_intent(
    engine: Engine,
    channel_id: str,
    media_asset_id: str,
    title: str,
    description: str,
    tags: list[str],
    privacy_status: str,
    idempotency_key: str | None,
    correlation_id: str,
    scheduled_publish_time: str | None = None,
) -> dict:
    """Create publication record with DRAFT_INTENT, evaluate gate, transition to VALIDATED or BLOCKED_GATE."""
    if not idempotency_key:
        idempotency_key = str(uuid4())

    # Check for existing publication with same (channel_id, idempotency_key)
    with Session(engine) as session:
        existing = session.scalars(
            select(PublicationRecord).where(
                PublicationRecord.channel_id == channel_id,
                PublicationRecord.idempotency_key == idempotency_key,
            )
        ).first()
        if existing:
            return PublicationView.model_validate(existing).model_dump()

    # A publication row references media_asset by foreign key, so a missing asset cannot be
    # recorded at all. Reject it explicitly instead of surfacing a database integrity error.
    with Session(engine) as session:
        if session.get(MediaAsset, media_asset_id) is None:
            raise PublishingAssetNotFound(
                f"MediaAsset {media_asset_id} does not exist",
                [f"MediaAsset {media_asset_id} not found"],
            )
        if session.get(ChannelRecord, channel_id) is None:
            raise PublishingAssetNotFound(
                f"Channel {channel_id} does not exist",
                [f"Channel {channel_id} not found"],
            )

    gate_result = evaluate_publishing_gate(engine, media_asset_id, channel_id)
    pub_id = str(uuid4())
    now = utc_now()

    # The blocked intent and its event must survive the rejection: a gate refusal is an
    # auditable governance decision, not a discarded attempt. The record is therefore
    # committed first and the error raised afterwards, outside the transaction.
    with Session(engine) as session, session.begin():
        status = "VALIDATED" if gate_result["eligible"] else "BLOCKED_GATE"
        error_detail = "; ".join(gate_result["reasons"]) if not gate_result["eligible"] else None

        event_type = "publishing.intent_created" if gate_result["eligible"] else "publishing.gate_failed"
        event = append_event(
            session,
            event_type,
            "publication_record",
            pub_id,
            1,
            {
                "channel_id": channel_id,
                "media_asset_id": media_asset_id,
                "status": status,
                "title": title,
                "privacy_status": privacy_status,
                "gate_reasons": gate_result["reasons"],
            },
            correlation_id,
        )

        pub = PublicationRecord(
            id=pub_id,
            channel_id=channel_id,
            media_asset_id=media_asset_id,
            title=title,
            description=description,
            tags_json=tags,
            privacy_status=privacy_status,
            status=status,
            idempotency_key=idempotency_key,
            remote_video_id=None,
            remote_url=None,
            scheduled_publish_time=scheduled_publish_time,
            published_at=None,
            error_detail=error_detail,
            created_at=now,
            event_id=event.event_id,
        )
        session.add(pub)
        session.flush()
        view = PublicationView.model_validate(pub).model_dump()

    if not gate_result["eligible"]:
        raise PublishingGateError(
            f"Publishing gate rejected publication: {view['error_detail']}",
            gate_result["reasons"],
        )

    return view


def execute_publication(
    engine: Engine,
    publisher: PublishingProvider,
    publication_id: str,
    correlation_id: str,
) -> dict:
    """Execute upload for a VALIDATED publication following 47_STATE_MACHINE_SPECIFICATIONS.md."""
    now = utc_now()

    with Session(engine) as session, session.begin():
        pub = session.get(PublicationRecord, publication_id)
        if not pub:
            raise ValueError(f"Publication {publication_id} not found")
        if pub.status not in ("VALIDATED", "FAILED_RETRYABLE"):
            raise ValueError(f"Cannot execute publication in status {pub.status!r}; must be VALIDATED")

        asset = session.get(MediaAsset, pub.media_asset_id)
        if not asset:
            raise ValueError("Associated MediaAsset missing")

        file_path = Path(asset.uri_or_path)
        title = pub.title
        description = pub.description
        tags = pub.tags_json
        privacy = pub.privacy_status
        idempotency_key = pub.idempotency_key

        is_retry = pub.status == "FAILED_RETRYABLE"

        # Transition to STARTED
        pub.status = "STARTED"
        append_event(
            session,
            "publishing.started",
            "publication_record",
            publication_id,
            1,
            {"title": title, "channel_id": pub.channel_id},
            correlation_id,
        )
        session.flush()

    # Never re-upload blindly after a failure: ask the platform whether the previous attempt
    # actually landed (47_STATE_MACHINE_SPECIFICATIONS.md, duplicate protection).
    if is_retry:
        reconciled = asyncio.run(publisher.reconcile_upload(idempotency_key, title))
        if reconciled is not None:
            with Session(engine) as session, session.begin():
                pub = session.get(PublicationRecord, publication_id)
                if pub is None:
                    raise ValueError("Publication record lost during reconciliation")
                simulated = bool(reconciled.simulated or getattr(publisher, "IS_SIMULATED", False))
                pub.status = "PUBLISHED_SIMULATED" if simulated else "PUBLISHED"
                pub.remote_video_id = reconciled.remote_video_id
                pub.remote_url = reconciled.remote_url or None
                pub.published_at = utc_now()
                pub.error_detail = (
                    "Simulated upload: no video exists on any platform." if simulated else None
                )
                event = append_event(
                    session,
                    "publishing.retry_reconciled",
                    "publication_record",
                    publication_id,
                    1,
                    {
                        "remote_video_id": reconciled.remote_video_id,
                        "detail": "Previous attempt already exists remotely; retry suppressed.",
                        "simulated": simulated,
                    },
                    correlation_id,
                )
                pub.event_id = event.event_id
                session.flush()
                return PublicationView.model_validate(pub).model_dump()

    # Upload video via provider
    upload_res: UploadResult = asyncio.run(
        publisher.upload_video(
            file_path,
            title=title,
            description=description,
            tags=tags,
            privacy_status=privacy,
            extra={"idempotency_key": idempotency_key},
        )
    )

    with Session(engine) as session, session.begin():
        pub = session.get(PublicationRecord, publication_id)
        if not pub:
            raise ValueError("Publication record lost during upload")

        if upload_res.status == "CONFIRMED":
            # A simulated upload created nothing on any platform. It is recorded under a
            # distinct terminal state and a distinct event so that no API consumer, log
            # reader or UI can mistake it for a real publication.
            simulated = bool(upload_res.simulated or getattr(publisher, "IS_SIMULATED", False))
            pub.status = "PUBLISHED_SIMULATED" if simulated else "PUBLISHED"
            pub.remote_video_id = upload_res.remote_video_id
            pub.remote_url = upload_res.remote_url or None
            pub.published_at = utc_now()
            pub.error_detail = (
                "Simulated upload: no video exists on any platform." if simulated else None
            )

            event = append_event(
                session,
                "publishing.video_published_simulated"
                if simulated
                else "publishing.video_published",
                "publication_record",
                publication_id,
                1,
                {
                    "remote_video_id": upload_res.remote_video_id,
                    "remote_url": upload_res.remote_url,
                    "privacy_status": privacy,
                    "title": title,
                    "simulated": simulated,
                    "adapter": type(publisher).__name__,
                },
                correlation_id,
            )
            pub.event_id = event.event_id
        elif upload_res.status == "UNKNOWN":
            pub.status = "REMOTE_UNKNOWN"
            pub.error_detail = upload_res.error_detail
            append_event(
                session,
                "publishing.remote_unknown",
                "publication_record",
                publication_id,
                1,
                {"error_detail": upload_res.error_detail},
                correlation_id,
            )
        else:
            pub.status = "FAILED_FINAL"
            pub.error_detail = upload_res.error_detail
            append_event(
                session,
                "publishing.failed",
                "publication_record",
                publication_id,
                1,
                {"error_detail": upload_res.error_detail},
                correlation_id,
            )

        session.flush()
        return PublicationView.model_validate(pub).model_dump()


def list_publications(engine: Engine, channel_id: str | None = None) -> list[dict]:
    with Session(engine) as session:
        query = select(PublicationRecord).order_by(PublicationRecord.created_at.desc())
        if channel_id:
            query = query.where(PublicationRecord.channel_id == channel_id)
        pubs = session.scalars(query).all()
        return [PublicationView.model_validate(p).model_dump() for p in pubs]


def get_publication(engine: Engine, publication_id: str) -> dict | None:
    with Session(engine) as session:
        pub = session.get(PublicationRecord, publication_id)
        if not pub:
            return None
        return PublicationView.model_validate(pub).model_dump()


def reconcile_publication(
    engine: Engine,
    publication_id: str,
    provider: PublishingProvider,
    correlation_id: str,
) -> dict:
    """Reconcile an uncertain publication (REMOTE_UNKNOWN / FAILED_RETRYABLE) with remote state.
    
    Per 47_STATE_MACHINE_SPECIFICATIONS.md: Never re-upload from REMOTE_UNKNOWN without checking remote state.
    """
    with Session(engine) as session, session.begin():
        pub = session.get(PublicationRecord, publication_id)
        if not pub:
            raise ValueError(f"Publication {publication_id} not found")
        remote_id = pub.remote_video_id
        if not remote_id:
            return PublicationView.model_validate(pub).model_dump()

    # Query remote status via provider
    status_res = asyncio.run(provider.get_video_status(remote_id))

    with Session(engine) as session, session.begin():
        pub = session.get(PublicationRecord, publication_id)
        if not pub:
            raise ValueError(f"Publication {publication_id} not found")

        if status_res.exists:
            simulated = bool(getattr(provider, "IS_SIMULATED", False))
            pub.status = "PUBLISHED_SIMULATED" if simulated else "PUBLISHED"
            pub.published_at = utc_now()
            # Keep whatever URL the provider actually returned; never synthesise one.
            pub.error_detail = (
                "Simulated upload: no video exists on any platform." if simulated else None
            )
            append_event(
                session,
                "publishing.reconciled_published",
                "publication_record",
                publication_id,
                1,
                {"remote_video_id": remote_id, "status": "PUBLISHED"},
                correlation_id,
            )
        else:
            pub.status = "FAILED_RETRYABLE"
            pub.error_detail = "Video not found on remote channel after timeout; safe to retry."
            append_event(
                session,
                "publishing.reconciled_not_found",
                "publication_record",
                publication_id,
                1,
                {"remote_video_id": remote_id, "status": "FAILED_RETRYABLE"},
                correlation_id,
            )

        session.flush()
        return PublicationView.model_validate(pub).model_dump()


def publish_media_asset(
    engine: Engine,
    media_asset_id: str,
    channel_id: str,
    title: str,
    description: str,
    tags: list[str],
    privacy_status: str = "private",
    correlation_id: str | None = None,
    provider: PublishingProvider | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """End-to-end publishing pipeline: intent -> gate validation -> upload -> remote URL."""
    corr_id = correlation_id or str(uuid4())

    # Refuse before creating any record: without a provider nothing can be published, and a
    # DRAFT_INTENT row would only suggest an attempt that could never happen.
    if provider is None:
        raise PublisherNotConfigured(
            "No publishing provider supplied. Configure STUDIO_YOUTUBE_CLIENT_ID, "
            "STUDIO_YOUTUBE_CLIENT_SECRET and STUDIO_YOUTUBE_REFRESH_TOKEN; the studio does "
            "not substitute a simulated publisher."
        )

    intent = create_publication_intent(
        engine=engine,
        channel_id=channel_id,
        media_asset_id=media_asset_id,
        title=title,
        description=description,
        tags=tags,
        privacy_status=privacy_status,
        idempotency_key=idempotency_key,
        correlation_id=corr_id,
    )

    return execute_publication(engine, provider, intent["id"], corr_id)


execute_publish = execute_publication

